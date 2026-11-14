"""Install LXD and Snapcraft from the Snap Store, retrying what is transient.

snap-build.yml runs this on the runner's own python3 before
snapcore/action-build, so the action finds both snaps installed and only
refreshes them. It uses the standard library only and must run on Python
3.10, the python3 of ubuntu-22.04, where publish.yml's snap job runs and
is to run this script too. tests/test_audit_pr_j.py lints it with ruff
for py310, which rejects newer syntax (except*, a type statement) but not
newer APIs: StrEnum, tomllib, typing.Self or datetime.UTC pass that lint
and fail only on a 3.10, which no CI job runs this on.

The file:line references to snapd below are to canonical/snapd at
commit 10725b7.

Why the retries look like this:
- snapd already retries each Store request, up to 6 times in 38 s with
  10 s per request (store/store.go:71,73-80).
- The failures we saw (2026-11-12) reached the end of that window, 40 to
  110 s in. So the attempts here work on another scale, 15 to 120 s
  apart and up to one deadline, for bad windows of a few minutes.
- For a window of 25 minutes or more, like the one of 2026-11-12, a red
  run is the right result.
- The retry regex of canonical/microceph's actionutils.sh does not match
  any of our four failures, hence the list below.

A request is made with --no-wait and then followed with `snap watch`,
which does not abort the change: killing the client on a timeout (a
SIGKILL, through sudo) would not abort it either, and a slow download
that would end green is waited for instead of failing the run.

The exit status is in EXIT_CODES below. 1 is left to an uncaught
exception, so it always means a bug in this script.
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

EXIT_CODES = """\
exit status:
  0  LXD and Snapcraft are installed and LXD is ready
  1  only an uncaught exception, a bug in this script
  2  invalid arguments
  3  a retryable Store error used up the attempts or the deadline
  4  a definitive error: sudo, the local snapd, a missing executable,
     or an error from the Store that retrying does not fix
"""

EXIT_OK = 0
EXIT_RETRYABLE = 3
EXIT_DEFINITIVE = 4

ERROR_TITLE = "Snap Store"
MESSAGE_LIMIT = 300

# A call whose timeout is not cut to session.remaining() can run past the
# deadline. test_w6 (tests/test_install_snap_tools.py) adds up the longest
# such tail to check the step's timeout-minutes: a new call like that, or
# a longer timeout below, means revisiting it.
CHOWN_TIMEOUT = 30.0
SEED_TIMEOUT = 120.0
# The first `snap list` of a snap decides alone: a missing answer there
# is a definitive failure, with no reconciliation behind it. So it gets
# the same 130 s as `snap changes` (see below), not the 30 s of the later
# ones, which only ever lead to a reconciliation.
FIRST_LIST_TIMEOUT = 130.0
LIST_TIMEOUT = 30.0
# When it cannot reach snapd, the client retries its GETs for up to
# 120 s (client/client.go:315-321). 130 s lets it give its own verdict
# before this script kills it, which matters while snapd restarts (for
# instance, while it refreshes itself).
CHANGES_TIMEOUT = 130.0
DIAGNOSTIC_TIMEOUT = 30.0
# lxd waitready has a --timeout of its own, so that it ends with its own
# message; the 30 s more of the subprocess timeout leave room for sudo
# and for lxd to start, and should never be what ends it.
WAITREADY_SECONDS = 120
WAITREADY_TIMEOUT = WAITREADY_SECONDS + 30.0
PROVENANCE_TIMEOUT = 30.0

PROVENANCE_GLOB = ("/snap/snapcraft/current/lib/python3*/site-packages/"
                   "craft_providers-*.dist-info")

_CHANNEL = re.compile(r"[a-z0-9][a-z0-9.-]*/(?:stable|candidate|beta|edge)")

# Rule 1, a real sudo failure, searched in the whole text: the command
# never ran, so there is no `error: ` line from snap. A sudo warning such
# as "sudo: unable to resolve host" is not one: the command runs anyway.
_SUDO_FAILURE = re.compile(
    r"\bsudo: a password is required\b"
    r"|\bsudo: a terminal is required\b"
    r"|\bsudo: [^ :]+: command not found\b"
    r"|\bis not in the sudoers file\b")
# Rule 2. Whatever transport error follows it is about snapd's local
# socket, not the Store (client/client.go:205-218). snapd may have taken
# the request, so this is reconciled instead of repeated blindly.
_SNAPD_LOCAL = "cannot communicate with server"
# Rule 3, besides exit status 10 (a retryable client error,
# cmd/snapd/cli/main.go:450-459). The two last alternatives are the exclusive
# changes (overlord/snapstate/conflict.go:173-238), which have no
# `snap "x" has` form.
_CONFLICT = re.compile(
    r'snap "[^"]+" has (?:"[^"]+" change|changes) in progress'
    r"|no other changes allowed until this is done"
    # Defensive: in that snapd commit this message is a ChangeConflictError,
    # which exits with 10 and is caught by the status before the text.
    # It only matters for a snapd that does not return 10.
    r"|not allowed until they are done")
CONFLICT_EXIT = 10
# Rule 4, searched in the text of the cause.
_RETRYABLE = [re.compile(p) for p in (
    r"unable to contact snap store",
    r"context deadline exceeded",
    r'"https?://[^"]+": EOF\b',
    r'": unexpected EOF\b',
    r"Client\.Timeout exceeded while awaiting headers",
    r"request canceled while waiting for connection",
    r"cannot get nonce from store",
    # 429 never gets here as a status: snapd turns it into
    # "too many requests" first (store/store.go:200-203).
    r"(?:store server returned status|unexpected HTTP status code) (?:408|5\d\d)\b",
    r"\btoo many requests\b",
    r"connection reset by peer",
    r"\bi/o timeout\b",
    r"TLS handshake timeout",
    r"timeout awaiting response headers",
    r"server misbehaving",
    r"Temporary failure in name resolution",
    r"connection refused",
)]
# snap's CLI prints an error as "error: <message>" at the start of a line
# (cmd/snapd/cli/error.go:42, cmd/snapd/cli/main.go:534). Matched on the
# raw text, by line: "remote error: tls", "internal error:" or "stream
# error:" inside a message are not that prefix.
_ERROR_LINE = re.compile(r"^error: ", re.MULTILINE)
_DIGITS = re.compile(r"[0-9]+")


class Kind(Enum):
    SUCCESS = "success"
    RETRY = "retry"
    DEFINITIVE = "definitive"
    CONFLICT = "conflict"
    UNCERTAIN = "uncertain"


class Listed(Enum):
    INSTALLED = "installed"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class Waited(Enum):
    WAITED = "waited"
    NOTHING = "nothing"
    NO_ANSWER = "no answer"
    DEADLINE = "deadline"


class Reconciled(Enum):
    SUCCESS = "success"
    CONTINUE = "continue"
    ELSEWHERE = "installed on another channel"
    LOCAL_DOWN = "local snapd unavailable"
    DEADLINE = "deadline"


# Causes of a failure, and the exit status each one gives.
CAUSE_DEADLINE = "deadline"
CAUSE_ATTEMPTS = "attempts used up"
CAUSE_DEFINITIVE = "definitive"
CAUSE_LOCAL = "local snapd unavailable"
_CAUSE_EXIT = {
    CAUSE_DEADLINE: EXIT_RETRYABLE,
    CAUSE_ATTEMPTS: EXIT_RETRYABLE,
    CAUSE_DEFINITIVE: EXIT_DEFINITIVE,
    CAUSE_LOCAL: EXIT_DEFINITIVE,
}


@dataclass(frozen=True)
class Result:
    rc: int | None  # None if and only if timed_out
    output: str  # stdout and stderr together, always str
    timed_out: bool


Runner = Callable[[Sequence[str], float], Result]


@dataclass(frozen=True)
class Commands:
    sudo: tuple[str, ...] = ("sudo", "-n")
    snap: tuple[str, ...] = ("snap",)
    lxd: tuple[str, ...] = ("lxd",)
    chown: tuple[str, ...] = ("chown",)


@dataclass(frozen=True)
class Listing:
    state: Listed
    channel: str | None
    message: str


@dataclass(frozen=True)
class Call:
    """One attempt at the Store: the request and, if any, its watch."""
    snap: str
    attempt: int
    seconds: float
    result: str
    kind: str
    rule: str
    message: str


@dataclass
class Outcome:
    snap: str
    ok: bool
    cause: str = ""
    attempt: int = 0
    attempts: int = 0
    message: str = ""
    calls: list[Call] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return EXIT_OK if self.ok else _CAUSE_EXIT[self.cause]


# -- pure functions -------------------------------------------------------

def normalise(text: str) -> str:
    """Every run of whitespace, line breaks included, as one space.

    snap's CLI wraps its errors at about 72 columns when stdout is not a
    terminal (cmd/snapd/cli/error.go:46-88), and a change's errors come on
    several lines from snapd itself.
    """
    return re.sub(r"\s+", " ", text).strip()


def _last_error_line(raw: str) -> int | None:
    starts = [m.start() for m in _ERROR_LINE.finditer(raw)]
    return starts[-1] if starts else None


def cause_text(raw: str) -> str:
    """The normalised text from the last line starting with ``error: ``,
    or all of it if there is none."""
    start = _last_error_line(raw)
    return normalise(raw if start is None else raw[start:])


def last_message(raw: str) -> str:
    """What follows the last ``error: ``, or else the last non-empty
    line, normalised and cut to MESSAGE_LIMIT characters."""
    start = _last_error_line(raw)
    if start is not None:
        text = normalise(raw[start + len("error: "):])
    else:
        lines = [line for line in raw.splitlines() if line.strip()]
        text = normalise(lines[-1]) if lines else ""
    return text[:MESSAGE_LIMIT]


def failure_message(command: str, r: Result) -> str:
    """last_message, or, when the output has no text, the command and its
    exit status, which the ::error line would otherwise not show."""
    return last_message(r.output) or f"{command} exited {r.rc} with no output"


def with_last_message(head: str, output: str) -> str:
    """``head: <last_message>``, or ``head with no output`` when the
    output has no text, so a warning or a note never ends in ": "."""
    message = last_message(output)
    return f"{head}: {message}" if message else f"{head} with no output"


def classify(output: str, rc: int | None) -> tuple[Kind, str]:
    """The kind of a failed call and the name of the rule that decided.

    The first rule that matches decides. Rule 1 reads the whole text; the
    others read only the text of the cause (cause_text), so a progress
    line or a sudo warning printed before the final error cannot decide.
    """
    if rc is None:
        return Kind.UNCERTAIN, "timeout"
    if _SUDO_FAILURE.search(normalise(output)):
        return Kind.DEFINITIVE, "sudo"
    cause = cause_text(output)
    if _SNAPD_LOCAL in cause:
        return Kind.UNCERTAIN, "snapd-local"
    if rc == CONFLICT_EXIT:
        return Kind.CONFLICT, "conflict-exit-10"
    if _CONFLICT.search(cause):
        return Kind.CONFLICT, "conflict-text"
    for rx in _RETRYABLE:
        if rx.search(cause):
            return Kind.RETRY, rx.pattern
    return Kind.DEFINITIVE, "unknown"


def delays(attempts: int, base: int = 15, factor: int = 2, cap: int = 120) -> list[int]:
    """The waits before attempts 2..attempts. No jitter: one job, and a
    deterministic test."""
    return [min(base * factor ** i, cap) for i in range(attempts - 1)]


def parse_change_id(output: str) -> str | None:
    """The last line that is only digits. ``--no-wait`` prints the change
    id, and snap may print its warnings notice after it
    (cmd/snapd/cli/main.go:681)."""
    ids = [line.strip() for line in output.splitlines()
           if _DIGITS.fullmatch(line.strip())]
    return ids[-1] if ids else None


def parse_in_progress(changes_output: str) -> list[str]:
    """Ids of the changes whose Ready column is ``-``, from
    ``snap changes --abs-time`` (cmd/snapd/cli/cmd_changes.go:118-123). A
    ``WARNING:`` line or ``no changes found`` gives nothing."""
    ids = []
    for line in changes_output.splitlines():
        fields = line.split()
        if len(fields) >= 4 and _DIGITS.fullmatch(fields[0]) and fields[3] == "-":
            ids.append(fields[0])
    return ids


def parse_tracking(list_output: str, name: str) -> str | None:
    """The Tracking column (the 4th) of ``name`` in ``snap list``."""
    for line in list_output.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[0] == name:
            return fields[3]
    return None


def validate_channel(text: str) -> str:
    """A channel with an explicit track and risk, like ``5.21/stable``.

    ``stable`` alone is refused: it means ``latest/stable``, and that
    ambiguity is what a channel argument is here to remove.
    """
    if not _CHANNEL.fullmatch(text):
        raise argparse.ArgumentTypeError(
            f"{text!r} is not <track>/<stable|candidate|beta|edge>")
    return text


def _escape(text: str) -> str:
    # The escaping of workflow command data, as @actions/core does it.
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def render_error(snap: str, outcome: Outcome) -> str:
    message = outcome.message or "no error message"
    if not outcome.attempts:
        # chown or lxd waitready: not a call to the Store
        detail = outcome.cause
    elif outcome.attempt:
        detail = f"attempt {outcome.attempt}/{outcome.attempts}, {outcome.cause}"
    else:
        detail = f"before any Store attempt, {outcome.cause}"
    return f"::error title={ERROR_TITLE}::{_escape(f'{snap}: {message} ({detail})')}"


def render_warning(text: str) -> str:
    return f"::warning title={ERROR_TITLE}::{_escape(text)}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


DIAGNOSTIC_HEADING = "### snap changes at the deadline"


def render_summary(outcomes: Sequence[Outcome], provenance: Sequence[str],
                   diagnostics: Sequence[str] = ()) -> str:
    lines = ["## Install LXD and Snapcraft", ""]
    for o in outcomes:
        state = "installed" if o.ok else f"failed, {o.cause}"
        lines.append(f"- {o.snap}: {state}")
    lines += ["", "### Calls to the Store", "",
              "| snap | n | seconds | result | kind | rule | last message |",
              "|---|---|---|---|---|---|---|"]
    for o in outcomes:
        for c in o.calls:
            lines.append(
                f"| {c.snap} | {c.attempt} | {c.seconds:.1f} | {_cell(c.result)} "
                f"| {c.kind} | {_cell(c.rule)} | {_cell(c.message)} |")
    notes = [n for o in outcomes for n in o.notes]
    if notes:
        lines += ["", "### Notes", ""]
        lines += [f"- {n}" for n in notes]
    if provenance:
        lines += ["", "### Provenance", "", "```"]
        lines += list(provenance)
        lines.append("```")
    for output in diagnostics:
        lines += ["", DIAGNOSTIC_HEADING, "", "```", *output.splitlines(), "```"]
    return "\n".join(lines) + "\n"


# -- the default runner ---------------------------------------------------

def _as_text(data: object) -> str:
    # A TimeoutExpired carries bytes on POSIX and str on Windows, even
    # with text=True (subprocess.py:560-570 and 1262-1271).
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


def default_run(argv: Sequence[str], timeout: float) -> Result:
    """Run ``argv``; never raises TimeoutExpired nor OSError."""
    try:
        proc = subprocess.run(
            list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
            timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return Result(rc=None, output=_as_text(exc.output), timed_out=True)
    except OSError as exc:
        # A missing sudo or snap gives exit status 4 and an ::error line,
        # not a traceback.
        return Result(rc=127, output=f"{type(exc).__name__}: {exc}", timed_out=False)
    return Result(rc=proc.returncode, output=proc.stdout or "", timed_out=False)


def _root_owner() -> tuple[int, int]:
    st = os.stat("/")
    return st.st_uid, st.st_gid


# -- the steps with effects -----------------------------------------------

class Session:
    """One run of the script: the injected effects and the deadline."""

    def __init__(self, *, run: Runner, sleep: Callable[[float], None],
                 clock: Callable[[], float], commands: Commands,
                 deadline: float, attempts: int, attempt_timeout: float,
                 min_attempt: float) -> None:
        self._run = run
        self.sleep = sleep
        self.clock = clock
        self.commands = commands
        self.deadline = deadline
        self.attempts = attempts
        self.attempt_timeout = attempt_timeout
        self.min_attempt = min_attempt
        self.diagnostics: list[str] = []

    def remaining(self) -> float:
        return self.deadline - self.clock()

    def run(self, argv: Sequence[str], timeout: float) -> Result:
        print(f"$ {' '.join(argv)}  (timeout {timeout:.0f} s)", flush=True)
        start = self.clock()
        result = self._run(argv, timeout)
        status = "timed out" if result.timed_out else f"exit {result.rc}"
        print(f"  {status} after {self.clock() - start:.1f} s", flush=True)
        for line in result.output.splitlines():
            # A prefix, so no line of a child can pass for a workflow command.
            print(f"  | {line}", flush=True)
        return result

    def sudo_snap(self, *args: str) -> list[str]:
        return [*self.commands.sudo, *self.commands.snap, *args]

    def snap(self, *args: str) -> list[str]:
        return [*self.commands.snap, *args]

    # snap list -----------------------------------------------------------

    def snap_list(self, name: str, timeout: float) -> Listing:
        r = self.run(self.snap("list", name), timeout)
        if r.timed_out:
            return Listing(Listed.UNKNOWN, None, f"snap list {name} timed out")
        if r.rc == 0:
            channel = parse_tracking(r.output, name)
            if channel is None:
                return Listing(Listed.UNKNOWN, None,
                               failure_message(f"snap list {name}", r))
            return Listing(Listed.INSTALLED, channel, "")
        # cmd/snapd/cli/cmd_list.go:67,100-114
        if "no matching snaps installed" in normalise(r.output):
            return Listing(Listed.ABSENT, None, last_message(r.output))
        return Listing(Listed.UNKNOWN, None, failure_message(f"snap list {name}", r))

    def confirm(self, name: str, channel: str) -> tuple[Kind, str, str]:
        # Not held to the deadline: the change is over, and refusing to
        # look would turn a success into a deadline failure.
        listing = self.snap_list(name, LIST_TIMEOUT)
        if listing.state is Listed.INSTALLED and listing.channel == channel:
            return Kind.SUCCESS, "confirmed", ""
        if listing.state is Listed.UNKNOWN:
            return Kind.UNCERTAIN, "list-unknown", listing.message
        seen = listing.channel if listing.state is Listed.INSTALLED else "not installed"
        return (Kind.DEFINITIVE, "list-mismatch",
                f"snap list shows {name} {seen}, expected {channel}")

    # waiting for changes in progress -----------------------------------

    def wait_in_progress(self, notes: list[str]) -> Waited:
        """Wait for every change in progress, of any snap.

        Unfiltered: a conflict can come from a change of another snap, or
        from an exclusive change (overlord/snapstate/conflict.go:164-243).
        Only a watch that ended with 0, or that failed for a reason other
        than the local snapd, counts as having waited for a change.
        """
        if self.clock() >= self.deadline:
            return Waited.DEADLINE
        r = self.run(self.snap("changes", "--abs-time"), CHANGES_TIMEOUT)
        if r.timed_out or r.rc != 0 or _SNAPD_LOCAL in normalise(r.output):
            return Waited.NO_ANSWER
        ids = parse_in_progress(r.output)
        if not ids:
            return Waited.NOTHING
        waited = False
        for change in ids:
            if self.remaining() <= 0:
                return Waited.DEADLINE
            w = self.run(self.sudo_snap("watch", change), self.remaining())
            if w.timed_out:
                return Waited.DEADLINE
            if w.rc == 0:
                waited = True
                continue
            kind, rule = classify(w.output, w.rc)
            # The change may be another snap's: its result does not decide
            # this attempt, the next request does.
            notes.append(with_last_message(
                f"change {change} in progress ended with exit {w.rc} "
                f"({kind.value}, {rule})", w.output))
            if not (kind is Kind.UNCERTAIN and rule == "snapd-local"):
                waited = True
        return Waited.WAITED if waited else Waited.NOTHING

    def reconcile(self, name: str, channel: str, notes: list[str]) -> tuple[Reconciled, str]:
        """After a timeout or a lost answer: did the change happen?"""
        waited = self.wait_in_progress(notes)
        if waited is Waited.NO_ANSWER:
            # The request's own message stays the one reported.
            return Reconciled.LOCAL_DOWN, ""
        # Unlike confirm(), no look once the deadline has passed: here
        # nothing has shown that the change ended well, and the snap changes
        # above, which the deadline does not cut, may already have run up
        # to 130 s past it. A success found then would still go on to lxd
        # waitready and the provenance, a longer tail than test_w6 counts,
        # so a change that ended well while that snap changes ran counts
        # as a deadline failure (exit 3).
        if waited is Waited.DEADLINE or self.clock() >= self.deadline:
            return Reconciled.DEADLINE, ""
        listing = self.snap_list(name, LIST_TIMEOUT)
        if listing.state is Listed.INSTALLED and listing.channel == channel:
            return Reconciled.SUCCESS, ""
        if listing.state is Listed.UNKNOWN:
            return Reconciled.LOCAL_DOWN, listing.message
        if listing.state is Listed.INSTALLED:
            return Reconciled.ELSEWHERE, listing.channel or ""
        return Reconciled.CONTINUE, ""

    def leave_lxd(self, installed: str, channel: str, outcome: Outcome) -> None:
        # Not switched: it could be a downgrade of a running LXD.
        text = f"lxd is installed from {installed}, not {channel}; left as it is"
        print(render_warning(text), flush=True)
        outcome.notes.append(text)

    # failures ------------------------------------------------------------

    def fail(self, outcome: Outcome, cause: str, attempt: int, message: str) -> Outcome:
        outcome.ok = False
        outcome.cause = cause
        outcome.attempt = attempt
        outcome.attempts = self.attempts
        outcome.message = message or outcome.message
        if not outcome.message and cause == CAUSE_DEADLINE and attempt == 0:
            # Without it the ::error line would say only "no error message".
            # After an attempt there is always a message: a call that failed
            # with no text gives its exit status (failure_message).
            outcome.message = "no attempt fits before the deadline"
        if cause == CAUSE_DEADLINE:
            # Only for the summary: what snapd was doing at the deadline.
            r = self.run(self.snap("changes", "--abs-time"), DIAGNOSTIC_TIMEOUT)
            self.diagnostics.append(r.output)
        return outcome

    # one snap ------------------------------------------------------------

    def ensure_snap(self, name: str, channel: str, classic: bool) -> Outcome:
        outcome = Outcome(snap=name, ok=True, attempts=self.attempts)
        if self.clock() >= self.deadline:
            return self.fail(outcome, CAUSE_DEADLINE, 0, "")
        listing = self.snap_list(name, FIRST_LIST_TIMEOUT)
        if listing.state is Listed.UNKNOWN:
            return self.fail(outcome, CAUSE_LOCAL, 0, listing.message)
        if name == "lxd" and listing.state is Listed.INSTALLED:
            if listing.channel != channel:
                self.leave_lxd(listing.channel or "", channel, outcome)
            return outcome
        op = "refresh" if listing.state is Listed.INSTALLED else "install"
        waits = delays(self.attempts)
        skip_wait = True  # the first attempt does not wait
        for n in range(1, self.attempts + 1):
            wait = 0 if skip_wait else waits[n - 2]
            if self.clock() + wait + self.min_attempt > self.deadline:
                return self.fail(outcome, CAUSE_DEADLINE, n - 1, "")
            if wait:
                self.sleep(wait)
            skip_wait = False
            if self.remaining() <= 0:
                return self.fail(outcome, CAUSE_DEADLINE, n - 1, "")
            argv = self.sudo_snap(op, "--no-wait", f"--channel={channel}",
                                  *(["--classic"] if classic else []), name)
            started = self.clock()
            r = self.run(argv, min(self.attempt_timeout, self.remaining()))
            shown = r
            if r.timed_out:
                kind, rule, message = Kind.UNCERTAIN, "timeout", f"{op} timed out"
            elif r.rc == 0:
                change = parse_change_id(r.output)
                if change is None:
                    # "already installed", "no updates available"
                    kind, rule, message = self.confirm(name, channel)
                else:
                    if self.remaining() <= 0:
                        self._record(outcome, n, started, r, "deadline", "deadline", "")
                        return self.fail(outcome, CAUSE_DEADLINE, n,
                                         f"change {change} started, not watched: "
                                         "the deadline came with the request's answer")
                    w = self.run(self.sudo_snap("watch", change), self.remaining())
                    shown = w
                    if w.timed_out:
                        self._record(outcome, n, started, w, "deadline", "deadline", "")
                        return self.fail(outcome, CAUSE_DEADLINE, n,
                                         f"change {change} still running at the deadline")
                    if w.rc == 0:
                        kind, rule, message = self.confirm(name, channel)
                    else:
                        kind, rule = classify(w.output, w.rc)
                        message = failure_message(f"snap watch {change}", w)
            else:
                kind, rule = classify(r.output, r.rc)
                message = failure_message(op, r)
            self._record(outcome, n, started, shown, kind.value, rule, message)
            # The last attempt's message wins, even a bare exit status over
            # an earlier Store error: the ::error line says "attempt N/M",
            # so its text is attempt N's, the "last error" CONTRIBUTING.md
            # promises. The cause of every attempt stays in the summary.
            if message:
                outcome.message = message

            if kind is Kind.SUCCESS:
                return outcome
            if kind is Kind.DEFINITIVE:
                return self.fail(outcome, CAUSE_DEFINITIVE, n, message)
            if kind is Kind.CONFLICT:
                waited = self.wait_in_progress(outcome.notes)
                if waited is Waited.DEADLINE:
                    return self.fail(outcome, CAUSE_DEADLINE, n, "")
                # Never again at once without having seen a change end.
                skip_wait = waited is Waited.WAITED
                continue
            if kind is Kind.UNCERTAIN:
                state, why = self.reconcile(name, channel, outcome.notes)
                if state is Reconciled.SUCCESS:
                    return outcome
                if state is Reconciled.LOCAL_DOWN:
                    return self.fail(outcome, CAUSE_LOCAL, n, why)
                if state is Reconciled.DEADLINE:
                    return self.fail(outcome, CAUSE_DEADLINE, n, "")
                # The same rules as for a snap found installed at the start:
                # `snap install` of an installed snap changes nothing, and
                # a wrong track would end as a definitive list-mismatch.
                if state is Reconciled.ELSEWHERE:
                    if name == "lxd":
                        self.leave_lxd(why, channel, outcome)
                        return outcome
                    op = "refresh"
                else:
                    op = "install"
            # Kind.RETRY, or a reconciliation that found the snap absent or
            # on another channel.
        return self.fail(outcome, CAUSE_ATTEMPTS, self.attempts, "")

    def _record(self, outcome: Outcome, n: int, started: float, r: Result,
                kind: str, rule: str, message: str) -> None:
        result = "timed out" if r.timed_out else f"exit {r.rc}"
        outcome.calls.append(Call(outcome.snap, n, self.clock() - started,
                                  result, kind, rule, message))


# -- entry point ----------------------------------------------------------

def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def _positive_float(text: str) -> float:
    value = float(text)
    if not value > 0:
        raise argparse.ArgumentTypeError("must be more than 0")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").partition("\n")[0], epilog=EXIT_CODES,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lxd-channel", required=True, type=validate_channel)
    parser.add_argument("--snapcraft-channel", required=True, type=validate_channel,
                        help="the same as the action-build's snapcraft-channel")
    parser.add_argument("--attempts", type=_positive_int, default=5,
                        help="Store attempts per snap (default: %(default)s)")
    parser.add_argument("--deadline-seconds", type=_positive_float, default=900.0,
                        help="one deadline for both snaps, counted from the start "
                             "(default: %(default).0f)")
    parser.add_argument("--attempt-timeout", type=_positive_float, default=150.0,
                        help="timeout of one install or refresh request; not of "
                             "the watch that follows it (default: %(default).0f)")
    parser.add_argument(
        "--summary", type=Path, default=os.environ.get("GITHUB_STEP_SUMMARY") or None,
        help="file to append the Markdown summary to "
             "(default: $GITHUB_STEP_SUMMARY when set)")
    return parser


def _local_failure(subject: str, r: Result) -> Outcome:
    message = last_message(r.output) or ("timed out" if r.timed_out else f"exit {r.rc}")
    return Outcome(snap=subject, ok=False, cause=CAUSE_DEFINITIVE, message=message)


def _provenance(session: Session) -> list[str]:
    r = session.run(session.snap("list", "lxd", "snapcraft", "core24", "snapd"),
                    PROVENANCE_TIMEOUT)
    lines = r.output.splitlines()
    dists = sorted(Path(p).name for p in glob.glob(PROVENANCE_GLOB))
    lines.append("craft-providers: " + (", ".join(dists) or "not found"))
    return lines


def main(argv: Sequence[str] | None = None, *, run: Runner | None = None,
         sleep: Callable[[float], None] | None = None,
         clock: Callable[[], float] | None = None,
         commands: Commands | None = None,
         root_owner: Callable[[], tuple[int, int]] | None = None,
         min_attempt: float = 50.0) -> int:
    args = _parser().parse_args(argv)
    clock = clock or time.monotonic
    cmds = commands or Commands()
    session = Session(
        run=run or default_run, sleep=sleep or time.sleep, clock=clock,
        commands=cmds, deadline=clock() + args.deadline_seconds,
        attempts=args.attempts, attempt_timeout=args.attempt_timeout,
        min_attempt=min_attempt)

    outcomes: list[Outcome] = []
    provenance: list[str] = []
    failure: Outcome | None = None

    if (root_owner or _root_owner)() != (0, 0):
        # As the action does (action-build src/tools.ts:24-29): LXD
        # refuses to start when / is not owned by root.
        r = session.run([*cmds.sudo, *cmds.chown, "root:root", "/"], CHOWN_TIMEOUT)
        if r.timed_out or r.rc != 0:
            failure = _local_failure("chown root:root /", r)

    if failure is None:
        if session.remaining() > 0:
            r = session.run(session.sudo_snap("wait", "system", "seed.loaded"),
                            min(SEED_TIMEOUT, session.remaining()))
            if r.timed_out or r.rc != 0:
                # Not decisive: whatever broke it shows again, and is
                # classified, in the calls that follow.
                text = with_last_message(
                    "snap wait system seed.loaded "
                    + ("timed out" if r.timed_out else f"exited {r.rc}"), r.output)
                print(render_warning(text), flush=True)

        for name, channel, classic in (("lxd", args.lxd_channel, False),
                                       ("snapcraft", args.snapcraft_channel, True)):
            outcome = session.ensure_snap(name, channel, classic)
            outcomes.append(outcome)
            if not outcome.ok:
                failure = outcome
                break

    if failure is None:
        r = session.run(
            [*cmds.sudo, *cmds.lxd, "waitready", f"--timeout={WAITREADY_SECONDS}"],
            WAITREADY_TIMEOUT)
        if r.timed_out or r.rc != 0:
            failure = _local_failure("lxd waitready", r)
        else:
            provenance = _provenance(session)

    summary = render_summary(outcomes, provenance, session.diagnostics)
    # The provenance and the diagnostic are output of snap, so, as in
    # Session.run, no line of the summary may pass for a workflow command.
    for line in summary.splitlines():
        print(f"  | {line}", flush=True)
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(summary)

    if failure is None:
        return EXIT_OK
    print(render_error(failure.snap, failure), flush=True)
    return failure.exit_code


if __name__ == "__main__":
    sys.exit(main())
