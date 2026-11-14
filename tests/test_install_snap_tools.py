"""Tests for scripts/install_snap_tools.py, the step of snap-build.yml that
installs LXD and Snapcraft with retries before snapcore/action-build.

The ids in the test names (U, E, W, T, S, L, D) only trace each test to
the design and the reviews it came from, which are not in the
repository: the rest of the name, and a docstring or comment where the
name is not enough, says what the test proves. The U, L and D tests
drive ``main`` with a fake ``run``, ``sleep`` and ``clock``; the E tests
run real subprocesses (a stub that plays snap, lxd, chown and sudo); the
W tests read snap-build.yml.

The Store messages marked "measured" are copied, line breaks included,
from the failed runs of 2026-11-12 (T1_EOF to T3_STORE; the fourth run
failed with the text of the third) and from two external logs (F5, F6);
the others are realistic, not copied from a log of ours, so they prove
the filter and not the exact wording of the runner's snapd.

A snap that is not installed is always ``snap list`` with exit 1 and
``error: no matching snaps installed`` (cmd/snapd/cli/cmd_list.go:67 in
canonical/snapd at 10725b7): any other text means "unknown" to the script
and turns the run into exit 4.
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest
from _workflow_steps import (
    ROOT,
    bash_flags,
    find_step,
    load_workflow,
    run_bash_script,
    write_fake_commands,
)

SCRIPT = ROOT / "scripts" / "install_snap_tools.py"


def _load():
    spec = importlib.util.spec_from_file_location("_install_snap_tools", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tools = _load()

Kind = tools.Kind

LXD = "5.21/stable"
SNAPCRAFT = "9.x/stable"

# Measured, with their original line breaks.
T1_EOF = ('error: cannot install "lxd": Post "https://api.snapcraft.io/v2/snaps/refresh":\n'
          "       EOF\n")
T2_DEADLINE = (
    "error: cannot perform the following tasks:\n"
    '- Ensure prerequisites for "lxd" are available (cannot install snap base "core26": '
    'Post "https://api.snapcraft.io/v2/snaps/refresh": context deadline exceeded)\n')
T3_STORE = "error: unable to contact snap store\n"
F5_CANCELED = (
    "error: cannot perform the following tasks:\n"
    '- Ensure prerequisites for "dart-sass" are available (cannot install snap base '
    '"core24": Post "https://api.snapcraft.io/v2/snaps/refresh": net/http: request '
    "canceled while waiting for connection (Client.Timeout exceeded while awaiting "
    "headers))\n")
F6_EOF = ('error: cannot install "dart-sass": Post\n'
          '       "https://api.snapcraft.io/v2/snaps/refresh": EOF\n')

STORE_POST = 'error: cannot install "lxd": Post "https://api.snapcraft.io/v2/snaps/refresh": '
LOCAL_POST = ('error: cannot communicate with server: Post "http://localhost/v2/snaps/lxd": '
              "dial unix /run/snapd.socket: ")
LOCAL_REFUSED = LOCAL_POST + "connect: connection refused\n"
NOT_FOUND = 'error: snap "lxdd" not found\n'
CONFLICT_LXD = 'error: snap "lxd" has "install-snap" change in progress\n'
CONFLICT_CORE24 = 'error: snap "core24" has "auto-refresh" change in progress\n'
ABSENT_TEXT = "error: no matching snaps installed\n"
NO_CHANGES_TEXT = "no changes found\n"
IN_PROGRESS_5 = (
    "ID   Status  Spawn                 Ready                 Summary\n"
    '4    Done    2026-11-12T19:00:00Z  2026-11-12T19:01:00Z  Initialize system state\n'
    '5    Doing   2026-11-12T20:00:00Z  -                     Auto-refresh snap "core24"\n')


@pytest.fixture(autouse=True)
def _no_step_summary(monkeypatch):
    # CI sets it; a test that does not ask for a summary must not append
    # to the summary of the job running the suite.
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def test_the_tests_never_see_the_step_summary_of_the_job():
    # Green on a machine that never sets it; in CI, where the runner sets
    # it, this is what fails if the fixture above goes.
    assert "GITHUB_STEP_SUMMARY" not in os.environ


# -- the fake run, sleep and clock ---------------------------------------

class R:
    """A canned answer: exit status, output, and how long it takes."""

    def __init__(self, rc=0, out="", seconds=1.0, timeout=False):
        self.rc, self.out, self.seconds, self.timeout = rc, out, seconds, timeout


TIMEOUT = R(timeout=True)
ABSENT = R(1, ABSENT_TEXT)
NO_CHANGES = R(0, NO_CHANGES_TEXT)


def listed(name, channel):
    return R(0, "Name       Version  Rev    Tracking     Publisher   Notes\n"
                f"{name:<10} 1.0      41296  {channel:<12} canonical** -\n")


def _key(argv):
    a = list(argv)
    if a[:2] == ["sudo", "-n"]:
        a = a[2:]
    if a[0] == "chown":
        return "chown"
    if a[1] == "list":
        return " ".join(a)
    return " ".join(a[:2])


class Fake:
    """Answers each call from a queue per command; the last answer of a
    queue repeats. A call with no answer fails the test."""

    def __init__(self, responses, start=1000.0):
        defaults = {
            "snap wait": [R(0, "")],
            "lxd waitready": [R(0, "")],
            "snap list lxd snapcraft core24 snapd": [R(0, "Name Version Rev Tracking\n")],
        }
        self.queues = {**defaults}
        for k, v in responses.items():
            self.queues[k] = list(v) if isinstance(v, list) else [v]
        self.now = start
        self.calls = []  # (argv, timeout, clock at the start)
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def run(self, argv, timeout):
        assert timeout > 0, (list(argv), timeout)
        self.calls.append((list(argv), timeout, self.now))
        queue = self.queues.get(_key(argv))
        assert queue, f"unexpected call {list(argv)}"
        r = queue.pop(0) if len(queue) > 1 else queue[0]
        if r.timeout or r.seconds > timeout:
            self.now += timeout
            return tools.Result(rc=None, output=r.out, timed_out=True)
        self.now += r.seconds
        return tools.Result(rc=r.rc, output=r.out, timed_out=False)

    def argvs(self):
        return [argv for argv, _, _ in self.calls]

    def called(self):
        return [_key(argv) for argv in self.argvs()]

    def requests(self, name=None):
        return [argv for argv in self.argvs()
                if _key(argv) in ("snap install", "snap refresh")
                and (name is None or argv[-1] == name)]

    def timeouts(self, key):
        return [t for argv, t, _ in self.calls if _key(argv) == key]


def snapcraft_ok(channel=SNAPCRAFT):
    """snapcraft already installed on the channel, with nothing to update."""
    return {"snap list snapcraft": listed("snapcraft", channel),
            "snap refresh": R(0, 'snap "snapcraft" has no updates available\n')}


def lxd_installs(*install, watch=None, lists=None):
    """LXD absent, then installed on 5.21/stable; ``install`` and ``watch`` answer
    the requests and the watches (a watch that ends well by default)."""
    if watch is None:
        watch = R(0, "")
    return {"snap list lxd": lists or [ABSENT, listed("lxd", LXD)],
            "snap install": list(install),
            "snap watch": watch if isinstance(watch, list) else [watch]}


def run_main(fake, *extra, lxd=LXD, snapcraft=SNAPCRAFT, root=(0, 0), **kw):
    argv = ["--lxd-channel", lxd, "--snapcraft-channel", snapcraft, *extra]
    return tools.main(argv, run=fake.run, sleep=fake.sleep, clock=fake.clock,
                      root_owner=lambda: root, **kw)


def error_lines(out):
    return [line for line in out.splitlines() if line.startswith("::error")]


# -- classification -------------------------------------------------------

@pytest.mark.parametrize("text", [T1_EOF, T2_DEADLINE, T3_STORE],
                         ids=["T1-eof", "T2-deadline", "T3-store"])
def test_u1_the_measured_store_failures_are_retried(text):
    """The texts of the failed runs of 2026-11-12, as snap wrapped them,
    are classified as retryable. The fourth run's text is T3_STORE's, so
    it has no case of its own."""
    assert tools.classify(text, 1)[0] is Kind.RETRY


@pytest.mark.parametrize("text", [
    F5_CANCELED,
    F6_EOF,
    ('error: cannot get nonce from store: Post "https://api.snapcraft.io/api/v1/snaps/'
     'auth/nonces": dial tcp: lookup api.snapcraft.io: no such host\n'),
    ('error: cannot install "lxd": got unexpected HTTP status code 408 via POST to\n'
     '       "https://api.snapcraft.io/v2/snaps/refresh"\n'),
    ('error: cannot install "lxd": got unexpected HTTP status code 503 via POST to\n'
     '       "https://api.snapcraft.io/v2/snaps/refresh"\n'),
    ('error: cannot get device session from store: store server returned status 502 '
     'and body "<html>"\n'),
    'error: cannot install "lxd": too many requests\n',
    STORE_POST + "unexpected EOF\n",
    STORE_POST + "dial tcp: lookup api.snapcraft.io on 127.0.0.53:53: server misbehaving\n",
    STORE_POST + "dial tcp: lookup api.snapcraft.io: Temporary failure in name resolution\n",
    STORE_POST + "dial tcp 185.125.188.58:443: connect: connection refused\n",
    STORE_POST + "read tcp 10.1.0.4:5000->185.125.188.58:443: read: connection reset by peer\n",
    STORE_POST + "dial tcp 185.125.188.58:443: i/o timeout\n",
    STORE_POST + "net/http: TLS handshake timeout\n",
    STORE_POST + "net/http: timeout awaiting response headers\n",
    # F5 has both of these; each one alone is retried too
    STORE_POST + "net/http: request canceled (Client.Timeout exceeded while awaiting headers)\n",
    STORE_POST + "net/http: request canceled while waiting for connection\n",
], ids=["F5", "F6", "nonce", "408", "503", "status-502", "429", "unexpected-eof",
        "misbehaving", "eai-again", "refused", "reset", "io-timeout", "tls", "headers",
        "client-timeout", "canceled-waiting"])
def test_u3_other_transient_store_errors_are_retried(text):
    assert tools.classify(text, 1)[0] is Kind.RETRY


@pytest.mark.parametrize("code", ["404", "400"])
def test_u3_other_4xx_statuses_are_definitive(code):
    text = (f'error: cannot install "lxd": got unexpected HTTP status code {code} '
            'via POST to "https://api.snapcraft.io/v2/snaps/refresh"\n')
    assert tools.classify(text, 1) == (Kind.DEFINITIVE, "unknown")


DEFINITIVE_EXAMPLES = [
    NOT_FOUND,
    "error: snap \"lxd\" not available on channel \"5.21/stable\" (see 'snap info lxd')\n",
    ('error: cannot install "lxd": snap "lxd" assumes unsupported features: snapd2.99\n'
     "       (try to refresh snapd)\n"),
    ('error: This revision of snap "lxd" was published using classic confinement and\n'
     "       thus may perform arbitrary system changes outside of the security sandbox\n"
     '       that snaps are usually confined to, which may put your system at risk.\n'
     "       snap \"lxd\" requires classic confinement\n"),
    'error: cannot install "lxd" due to low disk space\n',
    "sudo: a password is required\n",
    "something nobody has seen before\n",
    ('error: cannot install "lxd": got unexpected HTTP status code 404 via POST to\n'
     '       "https://api.snapcraft.io/v2/snaps/refresh"\n'),
]


@pytest.mark.parametrize("text", DEFINITIVE_EXAMPLES,
                         ids=["not-found", "channel", "assumes", "classic", "disk",
                              "sudo", "unknown", "404"])
def test_u4_a_definitive_error_stops_at_once_with_exit_4(text, capsys):
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(1, text)})
    assert run_main(fake) == 4
    assert len(fake.requests()) == 1
    assert fake.sleeps == []
    (line,) = error_lines(capsys.readouterr().out)
    assert line.startswith("::error title=Snap Store::lxd: ")
    assert "attempt 1/5, definitive" in line


def test_u5_a_retryable_error_uses_every_attempt_then_exits_3(capsys):
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(1, T3_STORE)})
    assert run_main(fake) == 3
    assert len(fake.requests("lxd")) == 5
    assert fake.sleeps == [15, 30, 60, 120]
    (line,) = error_lines(capsys.readouterr().out)
    assert "5/5" in line
    assert "unable to contact snap store" in line
    assert "attempts used up" in line


def test_u6_an_attempt_that_cannot_fit_before_the_deadline_does_not_start(capsys):
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(1, T3_STORE, seconds=40),
                 "snap changes": NO_CHANGES})
    assert run_main(fake, "--deadline-seconds", "300") == 3
    # 4 attempts of 40 s and waits of 15, 30 and 60 s end at 265 s; the
    # 5th would need 120 s of wait plus 50 s.
    assert len(fake.requests()) == 4
    assert fake.sleeps == [15, 30, 60]
    (line,) = error_lines(capsys.readouterr().out)
    assert "attempt 4/5, deadline" in line
    # The diagnostic, once, with its own 30 s.
    assert fake.timeouts("snap changes") == [30]


def test_u6_the_wait_counts_when_an_attempt_must_fit(capsys):
    """With a deadline the 50 s of an attempt alone does not reach, only
    the wait before it decides: no 120 s wait for an attempt that would
    then have 13 s."""
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(1, T3_STORE, seconds=40),
                 "snap changes": NO_CHANGES})
    assert run_main(fake, "--deadline-seconds", "400") == 3
    # Seed and snap list take 1 s each: the 4th attempt ends at 267 s.
    # 267 + 50 = 317 s is within the 400 s, but after the 120 s wait the
    # 5th would start at 387 s, 13 s before the deadline.
    assert len(fake.requests()) == 4
    assert fake.sleeps == [15, 30, 60]
    (line,) = error_lines(capsys.readouterr().out)
    assert "attempt 4/5, deadline" in line


def test_u6_lxd_using_up_the_deadline_stops_the_first_snapcraft_attempt(capsys):
    fake = Fake({**lxd_installs(R(0, "7\n"), watch=R(0, "", seconds=60)),
                 "snap list snapcraft": ABSENT, "snap changes": NO_CHANGES})
    assert run_main(fake, "--deadline-seconds", "100") == 3
    assert fake.requests("snapcraft") == []
    assert len(fake.requests("lxd")) == 1
    (line,) = error_lines(capsys.readouterr().out)
    assert line.startswith("::error title=Snap Store::snapcraft: ")
    assert "deadline" in line


def test_u7_success_on_the_third_attempt_then_snapcraft():
    fake = Fake({"snap list lxd": [ABSENT, listed("lxd", LXD)],
                 "snap install": [R(1, T3_STORE), R(1, T1_EOF), R(0, "7\n"), R(0, "8\n")],
                 "snap watch": R(0, ""),
                 "snap list snapcraft": [ABSENT, listed("snapcraft", SNAPCRAFT)]})
    assert run_main(fake) == 0
    assert len(fake.requests("lxd")) == 3
    assert fake.sleeps == [15, 30]
    assert len(fake.requests("snapcraft")) == 1
    keys = fake.called()
    assert keys.index("snap list snapcraft") > max(
        i for i, argv in enumerate(fake.argvs()) if argv[-1:] == ["lxd"])


def test_u8_a_definitive_lxd_failure_skips_snapcraft():
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(1, NOT_FOUND)})
    assert run_main(fake) == 4
    assert not [argv for argv in fake.argvs() if "snapcraft" in argv]


def test_u9_an_installed_lxd_is_left_alone():
    fake = Fake({"snap list lxd": listed("lxd", LXD), **snapcraft_ok()})
    assert run_main(fake) == 0
    assert fake.requests("lxd") == []


def test_l4_an_lxd_on_the_channel_gives_no_warning(capsys):
    fake = Fake({"snap list lxd": listed("lxd", LXD), **snapcraft_ok()})
    assert run_main(fake) == 0
    assert not [line for line in capsys.readouterr().out.splitlines()
                if line.startswith("::warning")]


def test_u9_an_installed_lxd_on_another_channel_warns_and_is_not_changed(capsys):
    fake = Fake({"snap list lxd": listed("lxd", "6/stable"), **snapcraft_ok()})
    assert run_main(fake) == 0
    assert fake.requests("lxd") == []
    out = capsys.readouterr().out
    assert any(line.startswith("::warning title=Snap Store::lxd is installed from 6/stable")
               for line in out.splitlines())


def test_u9_an_installed_snapcraft_is_refreshed_to_the_channel():
    fake = Fake({"snap list lxd": listed("lxd", LXD),
                 "snap list snapcraft": [listed("snapcraft", "latest/stable"),
                                         listed("snapcraft", SNAPCRAFT)],
                 "snap refresh": R(0, "9\n"), "snap watch": R(0, "")})
    assert run_main(fake) == 0
    assert fake.requests() == [["sudo", "-n", "snap", "refresh", "--no-wait",
                                "--channel=9.x/stable", "--classic", "snapcraft"]]


def test_u10_a_request_that_times_out_is_followed_to_its_end():
    fake = Fake({"snap list lxd": [ABSENT, listed("lxd", LXD)],
                 "snap install": TIMEOUT,
                 "snap changes": R(0, IN_PROGRESS_5), "snap watch": R(0, ""),
                 **snapcraft_ok()})
    assert run_main(fake) == 0
    assert len(fake.requests("lxd")) == 1
    assert ["snap", "changes", "--abs-time"] in fake.argvs()
    assert ["sudo", "-n", "snap", "watch", "5"] in fake.argvs()
    keys = fake.called()
    assert keys.index("snap changes") < keys.index("snap watch")


def test_u10b_a_timed_out_request_with_nothing_installed_counts_as_failed():
    fake = Fake({"snap list lxd": [ABSENT, ABSENT, listed("lxd", LXD)],
                 "snap install": [TIMEOUT, R(0, "7\n")],
                 "snap changes": R(0, "WARNING: snapd is about to reboot the system\n"
                                      + NO_CHANGES_TEXT),
                 "snap watch": R(0, ""), **snapcraft_ok()})
    assert run_main(fake) == 0
    assert len(fake.requests("lxd")) == 2
    assert fake.sleeps == [15]
    assert ["sudo", "-n", "snap", "watch", "7"] in fake.argvs()


# What `snap install` of an installed snap prints, with exit 0 and no change.
ALREADY_INSTALLED = "snap \"{}\" is already installed, see 'snap help refresh'\n"


def test_u10c_snapcraft_found_on_another_channel_by_the_reconciliation_is_refreshed():
    """A timed-out install whose reconciliation finds snapcraft on another
    track is followed by a refresh to the channel: a second install would
    change nothing and end as a definitive list-mismatch."""
    fake = Fake({"snap list lxd": listed("lxd", LXD),
                 "snap list snapcraft": [ABSENT, listed("snapcraft", "latest/stable"),
                                         listed("snapcraft", SNAPCRAFT)],
                 "snap install": [TIMEOUT, R(0, ALREADY_INSTALLED.format("snapcraft"))],
                 "snap refresh": R(0, "9\n"), "snap watch": R(0, ""),
                 "snap changes": NO_CHANGES})
    assert run_main(fake) == 0
    assert [argv[3] for argv in fake.requests("snapcraft")] == ["install", "refresh"]
    assert fake.requests("snapcraft")[1] == [
        "sudo", "-n", "snap", "refresh", "--no-wait", "--channel=9.x/stable", "--classic",
        "snapcraft"]


def test_u10c_lxd_found_on_another_channel_by_the_reconciliation_is_left_as_it_is(capsys):
    """The same rule as for an LXD found installed at the start: no second
    request, which could downgrade it, and a warning."""
    fake = Fake({"snap list lxd": [ABSENT, listed("lxd", "6/stable")],
                 "snap install": [TIMEOUT, R(0, ALREADY_INSTALLED.format("lxd"))],
                 "snap changes": NO_CHANGES, **snapcraft_ok()})
    assert run_main(fake) == 0
    assert len(fake.requests("lxd")) == 1
    out = capsys.readouterr().out
    assert ("::warning title=Snap Store::lxd is installed from 6/stable, not 5.21/stable; "
            "left as it is") in out.splitlines()


def test_u10d_a_snap_gone_after_elsewhere_is_installed_again():
    """The request follows the last reconciliation: a refresh after the
    snap was seen on another channel, an install once it is gone again."""
    fake = Fake({"snap list lxd": listed("lxd", LXD),
                 "snap list snapcraft": [ABSENT, listed("snapcraft", "latest/stable"), ABSENT,
                                         listed("snapcraft", SNAPCRAFT)],
                 "snap install": [TIMEOUT, R(0, "8\n")],
                 "snap refresh": [TIMEOUT, R(1, 'error: snap "snapcraft" is not installed\n')],
                 "snap watch": R(0, ""), "snap changes": R(0, NO_CHANGES_TEXT)})
    assert run_main(fake) == 0
    assert [argv[3] for argv in fake.requests("snapcraft")] == ["install", "refresh", "install"]


def test_u10e_a_snap_always_on_another_channel_uses_up_the_attempts(capsys):
    """Found on another channel after every timed-out request: each one
    counts as a failed attempt, with no definitive end and no success."""
    fake = Fake({"snap list lxd": listed("lxd", LXD),
                 "snap list snapcraft": [ABSENT, listed("snapcraft", "latest/stable")],
                 "snap install": TIMEOUT, "snap refresh": TIMEOUT,
                 "snap changes": NO_CHANGES})
    assert run_main(fake, "--attempt-timeout", "10") == 3
    assert [argv[3] for argv in fake.requests("snapcraft")] == ["install"] + ["refresh"] * 4
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ("::error title=Snap Store::snapcraft: refresh timed out "
                    "(attempt 5/5, attempts used up)")


def test_u11_the_summary_has_a_row_per_store_call_and_goes_to_the_step_summary(
        tmp_path, monkeypatch):
    step_summary = tmp_path / "step summary é.md"
    step_summary.write_text("earlier step\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary))
    fake = Fake({"snap list lxd": [ABSENT, listed("lxd", LXD)],
                 "snap install": [R(1, T3_STORE), R(0, "7\n"), R(0, "8\n")],
                 "snap watch": R(0, ""),
                 "snap list snapcraft": [ABSENT, listed("snapcraft", SNAPCRAFT)],
                 "snap list lxd snapcraft core24 snapd":
                     R(0, "Name Version Rev Tracking\ncore24 20250101 888 latest/stable\n")})
    assert run_main(fake) == 0
    text = step_summary.read_text(encoding="utf-8")
    assert text.startswith("earlier step\n## Install LXD and Snapcraft")
    rows = [line for line in text.splitlines() if line.startswith("| ")]
    assert [row.split(" | ")[0:2] for row in rows[1:]] == [
        ["| lxd", "1"], ["| lxd", "2"], ["| snapcraft", "1"]]
    assert "unable to contact snap store" in rows[1]
    assert "core24 20250101 888 latest/stable" in text


def test_u11_a_percent_sign_is_escaped_in_the_error_line(capsys):
    fake = Fake({"snap list lxd": ABSENT,
                 "snap install": R(1, 'error: snap "lxd" is 100% broken\n')})
    assert run_main(fake) == 4
    (line,) = error_lines(capsys.readouterr().out)
    assert "100%25 broken" in line
    assert "100% " not in line


def test_u11_a_pipe_in_a_cell_does_not_split_the_summary_row(tmp_path):
    """The rule of a Store status has "|" in it; unescaped, the row would
    have more cells than the header."""
    summary = tmp_path / "summary.md"
    status_503 = ('error: cannot install "lxd": got unexpected HTTP status code 503 via POST to\n'
                  '       "https://api.snapcraft.io/v2/snaps/refresh"\n')
    fake = Fake({**lxd_installs(R(1, status_503), R(0, "7\n")), **snapcraft_ok()})
    assert run_main(fake, "--summary", str(summary)) == 0
    lines = summary.read_text(encoding="utf-8").splitlines()
    header = lines[lines.index("### Calls to the Store") + 2]
    rows = [line for line in lines if line.startswith("| lxd | 1 ")]
    assert rows == [(
        r"| lxd | 1 | 1.0 | exit 1 | retry "
        r"| (?:store server returned status\|unexpected HTTP status code) (?:408\|5\d\d)\b "
        r'| cannot install "lxd": got unexpected HTTP status code 503 via POST to '
        r'"https://api.snapcraft.io/v2/snaps/refresh" |')]
    unescaped_pipe = r"(?<!\\)\|"
    assert len(re.split(unescaped_pipe, rows[0])) == len(re.split(unescaped_pipe, header))


def test_u12_importing_the_script_has_no_side_effect(capsys):
    _load()
    assert capsys.readouterr() == ("", "")


def test_u13_the_exact_calls_in_order_with_the_channels_given():
    fake = Fake({"snap list lxd": [ABSENT, listed("lxd", "6/edge")],
                 "snap install": [R(0, "7\n"), R(0, "8\n")],
                 "snap watch": R(0, ""),
                 "snap list snapcraft": [ABSENT, listed("snapcraft", "8.x/candidate")]})
    assert run_main(fake, lxd="6/edge", snapcraft="8.x/candidate") == 0
    assert fake.argvs() == [
        ["sudo", "-n", "snap", "wait", "system", "seed.loaded"],
        ["snap", "list", "lxd"],
        ["sudo", "-n", "snap", "install", "--no-wait", "--channel=6/edge", "lxd"],
        ["sudo", "-n", "snap", "watch", "7"],
        ["snap", "list", "lxd"],
        ["snap", "list", "snapcraft"],
        ["sudo", "-n", "snap", "install", "--no-wait", "--channel=8.x/candidate",
         "--classic", "snapcraft"],
        ["sudo", "-n", "snap", "watch", "8"],
        ["snap", "list", "snapcraft"],
        ["sudo", "-n", "lxd", "waitready", "--timeout=120"],
        ["snap", "list", "lxd", "snapcraft", "core24", "snapd"],
    ]
    assert not [argv for argv in fake.argvs() if "init" in argv]


def test_u13_lxd_waitready_gives_up_on_its_own_before_the_script_kills_it():
    """The --timeout of lxd waitready and the timeout of its subprocess,
    both as main used them: lxd must give its own verdict first. The 30 s
    between them are for sudo and for lxd to start."""
    fake = Fake({"snap list lxd": listed("lxd", LXD), **snapcraft_ok()})
    assert run_main(fake) == 0
    ((argv, timeout, _),) = [c for c in fake.calls if _key(c[0]) == "lxd waitready"]
    (own,) = [int(a.partition("=")[2]) for a in argv if a.startswith("--timeout=")]
    assert timeout - own >= 30, (own, timeout)


def test_u13_root_not_owning_slash_is_fixed_first():
    fake = Fake({"chown": R(0, ""), "snap list lxd": listed("lxd", LXD), **snapcraft_ok()})
    assert run_main(fake, root=(1001, 1001)) == 0
    assert fake.argvs()[0] == ["sudo", "-n", "chown", "root:root", "/"]


def test_u13_a_failed_chown_exits_4(capsys):
    fake = Fake({"chown": R(1, "chown: changing ownership of '/': Operation not permitted\n")})
    assert run_main(fake, root=(1001, 1001)) == 4
    assert fake.called() == ["chown"]
    (line,) = error_lines(capsys.readouterr().out)
    assert line.startswith("::error title=Snap Store::chown root:root /: ")


def test_u14_the_waits_double_up_to_a_cap():
    assert tools.delays(6) == [15, 30, 60, 120, 120]
    assert tools.delays(5) == [15, 30, 60, 120]
    assert tools.delays(1) == []


@pytest.mark.parametrize(("text", "rc", "expected"), [
    # "cannot communicate with server" decides before the transport error
    (LOCAL_POST + "i/o timeout\n", 1, (Kind.UNCERTAIN, "snapd-local")),
    (LOCAL_REFUSED, 1, (Kind.UNCERTAIN, "snapd-local")),
    (LOCAL_POST + "unexpected EOF\n", 1, (Kind.UNCERTAIN, "snapd-local")),
    ("error: cannot communicate with server: timeout exceeded while waiting for response\n",
     1, (Kind.UNCERTAIN, "snapd-local")),
    # the same transports, from the Store
    (STORE_POST + "dial tcp 185.125.188.58:443: i/o timeout\n", 1, (Kind.RETRY, r"\bi/o timeout\b")),
    (STORE_POST + "dial tcp 185.125.188.58:443: connect: connection refused\n", 1,
     (Kind.RETRY, "connection refused")),
    (STORE_POST + "unexpected EOF\n", 1, (Kind.RETRY, '": unexpected EOF\\b')),
    # conflict
    ("", 10, (Kind.CONFLICT, "conflict-exit-10")),
    ('error: snap "lxd" has "install-snap" change in progress (i/o timeout)\n', 1,
     (Kind.CONFLICT, "conflict-text")),
    ("error: transition to snapd snap in progress, no other changes allowed until this is done\n",
     1, (Kind.CONFLICT, "conflict-text")),
    (('error: other changes in progress (conflicting change "install-snap"), change "remodel"\n'
      "       not allowed until they are done\n"), 1, (Kind.CONFLICT, "conflict-text")),
    # sudo failures decide first, over the whole text
    ("sudo: a password is required\n" + STORE_POST + "i/o timeout\n", 1,
     (Kind.DEFINITIVE, "sudo")),
    ("sudo: a password is required\ncannot communicate with server\n", 1,
     (Kind.DEFINITIVE, "sudo")),
    ("sudo: snap: command not found\n", 1, (Kind.DEFINITIVE, "sudo")),
    # sudo 1.9.15 wording, without "This incident will be reported"
    ("runner is not in the sudoers file.\n", 1, (Kind.DEFINITIVE, "sudo")),
    (("sudo: a terminal is required to read the password; either use the -S option to read\n"
      "from standard input or configure an askpass helper\n"), 1, (Kind.DEFINITIVE, "sudo")),
    # a sudo warning does not decide
    ("sudo: unable to resolve host fv-az1: Name or service not known\n" + LOCAL_REFUSED, 1,
     (Kind.UNCERTAIN, "snapd-local")),
    ("sudo: unable to resolve host fv-az1: Name or service not known\n" + T1_EOF, 1,
     (Kind.RETRY, '"https?://[^"]+": EOF\\b')),
    # only the text from the last line starting with "error: " decides
    (('Download snap "core24" (1234) from channel "latest/stable" retrying: dial tcp '
      "1.2.3.4:443: i/o timeout\n"
      "error: cannot perform the following tasks:\n"
      '- Mount snap "lxd" (41296) (snap "lxd" assumes unsupported features: snapd2.99 '
      "(try to refresh snapd))\n"), 1, (Kind.DEFINITIVE, "unknown")),
    # ... and "error: " inside a message is not that line: with two
    # tasks, the "internal error:" of the second does not hide the Store
    # error of the first (S-N1)
    (("error: cannot perform the following tasks:\n"
      '- Ensure prerequisites for "lxd" are available (cannot install snap base "core24": '
      'Post "https://api.snapcraft.io/v2/snaps/refresh": context deadline exceeded)\n'
      '- Setup snap "lxd" (41296) security profiles (internal error: x)\n'), 1,
     (Kind.RETRY, "context deadline exceeded")),
    (('error: cannot communicate with server: Get "http://localhost/v2/changes/5": stream\n'
      "       error: stream ID 3; CANCEL\n"), 1, (Kind.UNCERTAIN, "snapd-local")),
    (('error: cannot communicate with server: Get "http://localhost/v2/changes/5": '
      "remote error: tls: bad certificate\n"), 1, (Kind.UNCERTAIN, "snapd-local")),
])
def test_u15_precedence_between_the_rules(text, rc, expected):
    assert tools.classify(text, rc) == expected


@pytest.mark.parametrize(("text", "rc", "expected"), [
    # a timeout decides before any text
    ("", None, (Kind.UNCERTAIN, "timeout")),
    (LOCAL_REFUSED, None, (Kind.UNCERTAIN, "timeout")),
    # "cannot communicate with server" on a progress line, before the
    # last "error: ", does not decide: rule 2 reads only the cause
    ('cannot communicate with server: retrying\nerror: snap "x" not found\n', 1,
     (Kind.DEFINITIVE, "unknown")),
    # the conflict without a change kind
    ('error: snap "lxd" has changes in progress\n', 1, (Kind.CONFLICT, "conflict-text")),
    # ... and, like rule 2, rule 3 reads only the cause
    ('snap "core24" has "auto-refresh" change in progress\nerror: snap "x" not found\n', 1,
     (Kind.DEFINITIVE, "unknown")),
    # rule 1 reads the normalised text, like the others
    ("sudo: a password\n  is required\n", 1, (Kind.DEFINITIVE, "sudo")),
], ids=["timeout", "timeout-over-text", "local-on-a-progress-line", "changes",
        "conflict-on-a-progress-line", "sudo-wrapped"])
def test_u15_more_precedence_between_the_rules(text, rc, expected):
    assert tools.classify(text, rc) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("error: first\nerror: second\n", "second"),
    ("one\ntwo\n", "two"),
    ("one\n   \n", "one"),
    ("  one   two  \n", "one two"),
    ("", ""),
], ids=["last-error", "last-line", "blank-line", "spaces", "empty"])
def test_last_message_takes_the_last_error_or_the_last_line_with_text(raw, expected):
    assert tools.last_message(raw) == expected


def test_u16_snapcraft_failing_after_lxd_still_fails_the_run(capsys):
    fake = Fake({**lxd_installs(R(0, "7\n"), R(1, 'error: snap "snapcraft" not found\n')),
                 "snap list snapcraft": ABSENT})
    assert run_main(fake) == 4
    (line,) = error_lines(capsys.readouterr().out)
    assert line.startswith("::error title=Snap Store::snapcraft: ")


def test_u17_a_conflict_waits_for_the_change_and_retries_at_once():
    fake = Fake({**lxd_installs(R(10, CONFLICT_LXD), R(0, "7\n")),
                 "snap changes": R(0, IN_PROGRESS_5), **snapcraft_ok()})
    assert run_main(fake) == 0
    assert ["snap", "changes", "--abs-time"] in fake.argvs()
    assert ["sudo", "-n", "snap", "watch", "5"] in fake.argvs()
    assert len(fake.requests("lxd")) == 2
    assert fake.sleeps == []


@pytest.mark.parametrize("changes", [NO_CHANGES, TIMEOUT], ids=["nothing", "no-answer"])
def test_u17b_a_conflict_with_nothing_to_wait_for_backs_off(changes):
    fake = Fake({**lxd_installs(R(10, CONFLICT_LXD), R(0, "7\n")),
                 "snap changes": changes, **snapcraft_ok()})
    assert run_main(fake) == 0
    assert [argv for argv in fake.argvs() if argv[-2:-1] == ["watch"]] == [
        ["sudo", "-n", "snap", "watch", "7"]]
    assert fake.sleeps == [15]
    assert len(fake.requests("lxd")) == 2


def test_u17c_a_failed_change_of_another_snap_does_not_decide_the_attempt():
    fake = Fake({**lxd_installs(
        R(10, CONFLICT_CORE24), R(0, "7\n"),
        watch=[R(1, "error: cannot perform the following tasks:\n"
                    '- Download snap "core24" (888) from channel "latest/stable" '
                    "(snap \"core24\" not found)\n"), R(0, "")]),
        "snap changes": R(0, IN_PROGRESS_5), **snapcraft_ok()})
    assert run_main(fake) == 0
    changes = [argv for argv in fake.argvs() if _key(argv) == "snap changes"]
    assert changes == [["snap", "changes", "--abs-time"]]
    assert ["sudo", "-n", "snap", "watch", "5"] in fake.argvs()
    assert len(fake.requests("lxd")) == 2
    assert fake.sleeps == []


def test_u17c_a_watch_that_cannot_reach_snapd_is_not_a_wait():
    # A watch that ends because the local snapd does not answer has not
    # seen the change end, so the next request waits 15 s instead of
    # going at once (S-N2).
    fake = Fake({**lxd_installs(
        R(10, CONFLICT_CORE24), R(0, "7\n"),
        watch=[R(1, 'error: cannot communicate with server: Get "http://localhost/v2/'
                    'changes/5": dial unix /run/snapd.socket: connect: connection refused\n'),
               R(0, "")]),
        "snap changes": R(0, IN_PROGRESS_5), **snapcraft_ok()})
    assert run_main(fake) == 0
    assert ["sudo", "-n", "snap", "watch", "5"] in fake.argvs()
    assert fake.sleeps == [15]
    assert len(fake.requests("lxd")) == 2


@pytest.mark.parametrize(("watch", "expected"), [
    (R(1, ""), "(definitive, unknown) with no output"),
    (R(1, 'error: snap "core24" not found\n'), '(definitive, unknown): snap "core24" not found'),
], ids=["no-text", "text"])
def test_u17c_the_note_of_a_failed_change_in_progress_never_ends_in_a_colon(
        watch, expected, tmp_path):
    summary = tmp_path / "summary.md"
    fake = Fake({**lxd_installs(R(10, CONFLICT_CORE24), R(0, "7\n"), watch=[watch, R(0, "")]),
                 "snap changes": R(0, IN_PROGRESS_5), **snapcraft_ok()})
    assert run_main(fake, "--summary", str(summary)) == 0
    notes = [line for line in summary.read_text(encoding="utf-8").splitlines()
             if line.startswith("- change ")]
    assert notes == ["- change 5 in progress ended with exit 1 " + expected]


def test_u17d_the_watch_of_a_change_in_progress_is_cut_to_the_deadline(capsys):
    """A change in progress that does not end: its watch gets only what is
    left, and nothing but the diagnostic starts after the deadline."""
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(10, CONFLICT_LXD),
                 "snap changes": R(0, IN_PROGRESS_5), "snap watch": R(0, "", seconds=500)})
    assert run_main(fake, "--deadline-seconds", "100") == 3
    # Every call but the watch takes 1 s.
    assert [(_key(argv), t, now) for argv, t, now in fake.calls] == [
        ("snap wait", 100, 1000), ("snap list lxd", 130, 1001), ("snap install", 98, 1002),
        ("snap changes", 130, 1003), ("snap watch", 96, 1004), ("snap changes", 30, 1100)]
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ('::error title=Snap Store::lxd: snap "lxd" has "install-snap" change in '
                    "progress (attempt 1/5, deadline)")


@pytest.mark.parametrize("argv", [
    ["--snapcraft-channel", SNAPCRAFT],
    ["--lxd-channel", LXD],
    ["--lxd-channel", "stable", "--snapcraft-channel", SNAPCRAFT],
    ["--lxd-channel", "5.21", "--snapcraft-channel", SNAPCRAFT],
    ["--lxd-channel", "5.21/stable/hotfix", "--snapcraft-channel", SNAPCRAFT],
    ["--lxd-channel", "5.21/stable;x", "--snapcraft-channel", SNAPCRAFT],
    ["--lxd-channel", LXD, "--snapcraft-channel", "stable"],
    ["--lxd-channel", LXD, "--snapcraft-channel", "9.x/stable\n"],
    ["--lxd-channel", "-5.21/stable", "--snapcraft-channel", SNAPCRAFT],
    ["--lxd-channel", "5.21/", "--snapcraft-channel", SNAPCRAFT],
    ["--lxd-channel", LXD, "--snapcraft-channel", SNAPCRAFT, "--attempts", "0"],
    ["--lxd-channel", LXD, "--snapcraft-channel", SNAPCRAFT, "--deadline-seconds", "0"],
    ["--lxd-channel", LXD, "--snapcraft-channel", SNAPCRAFT, "--attempt-timeout", "-1"],
])
def test_u18_bad_arguments_exit_2_before_any_call(argv):
    fake = Fake({})
    with pytest.raises(SystemExit) as exc:
        tools.main(argv, run=fake.run, sleep=fake.sleep, clock=fake.clock,
                   root_owner=lambda: (1001, 1001))
    assert exc.value.code == 2
    assert fake.calls == []


def test_u19_a_request_with_no_change_is_confirmed_with_snap_list():
    fake = Fake({"snap list lxd": listed("lxd", LXD), **snapcraft_ok()})
    assert run_main(fake) == 0
    assert "snap watch" not in fake.called()
    assert fake.called().count("snap list snapcraft") == 2


def test_u19_a_request_with_no_change_on_another_channel_is_definitive(capsys):
    fake = Fake({"snap list lxd": listed("lxd", LXD),
                 "snap list snapcraft": listed("snapcraft", "latest/stable"),
                 "snap refresh": R(0, 'snap "snapcraft" has no updates available\n')})
    assert run_main(fake) == 4
    (line,) = error_lines(capsys.readouterr().out)
    assert "snapcraft latest/stable, expected 9.x/stable" in line


def test_u20_a_change_that_fails_on_the_store_is_retried():
    fake = Fake({**lxd_installs(R(0, "7\n"), R(0, "8\n"), watch=[R(1, T2_DEADLINE), R(0, "")]),
                 **snapcraft_ok()})
    assert run_main(fake) == 0
    assert len(fake.requests("lxd")) == 2
    assert fake.sleeps == [15]


def test_u21_a_local_snapd_that_does_not_answer_exits_4_after_one_request(capsys):
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(1, LOCAL_REFUSED),
                 "snap changes": R(1, LOCAL_REFUSED.replace("snaps/lxd", "changes"))})
    assert run_main(fake) == 4
    assert len(fake.requests()) == 1
    (line,) = error_lines(capsys.readouterr().out)
    assert "local snapd unavailable" in line
    assert "dial unix /run/snapd.socket: connect: connection refused" in line


def test_u22_the_change_id_is_the_last_line_of_digits():
    out = "7\nWARNING: There are 2 new warnings. See 'snap warnings'.\n"
    assert tools.parse_change_id(out) == "7"
    assert tools.parse_change_id("12\n7\n") == "7"
    fake = Fake({**lxd_installs(R(0, out)), **snapcraft_ok()})
    assert run_main(fake) == 0
    assert ["sudo", "-n", "snap", "watch", "7"] in fake.argvs()


def test_u22_the_parsers_skip_warnings_and_empty_answers():
    assert tools.parse_change_id("snap \"lxd\" has no updates available\n") is None
    # only a line of nothing but digits is an id
    assert tools.parse_change_id("7\n2 new warnings\n") == "7"
    assert tools.parse_change_id("7\n\n") == "7"
    warn = "WARNING: snapd is about to reboot the system\n" + IN_PROGRESS_5
    assert tools.parse_in_progress(warn) == ["5"]
    assert tools.parse_in_progress(NO_CHANGES_TEXT) == []
    assert tools.parse_tracking(listed("lxd", LXD).out, "lxd") == LXD
    assert tools.parse_tracking(listed("lxd", LXD).out, "snapcraft") is None


def test_u23_no_watch_when_the_deadline_falls_after_the_request(capsys):
    # deadline at 1100; seed and snap list take 1 s each, so the request
    # gets 98 s and its answer comes exactly at the deadline.
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(0, "7\n", seconds=98),
                 "snap changes": NO_CHANGES})
    assert run_main(fake, "--deadline-seconds", "100") == 3
    assert "snap watch" not in fake.called()
    assert all(t > 0 for _, t, _ in fake.calls)
    # The ::error line says which change was left unwatched, not
    # "no error message".
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ("::error title=Snap Store::lxd: change 7 started, not watched: "
                    "the deadline came with the request's answer (attempt 1/5, deadline)")


def test_u23b_a_deadline_failure_never_ends_without_a_message(capsys):
    """A conflict (exit 10) with no text, answered at the deadline: the
    ::error line still says what happened, with the exit status."""
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(10, "", seconds=98),
                 "snap changes": NO_CHANGES})
    assert run_main(fake, "--deadline-seconds", "100") == 3
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ("::error title=Snap Store::lxd: install exited 10 with no output "
                    "(attempt 1/5, deadline)")


def test_u23b_attempts_used_up_without_a_message_still_say_what_happened(capsys):
    """Five conflicts (exit 10) with no text and nothing to wait for: the
    attempts run out, and the ::error line does not say only "no error
    message"."""
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(10, ""),
                 "snap changes": NO_CHANGES})
    assert run_main(fake) == 3
    assert len(fake.requests("lxd")) == 5
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ("::error title=Snap Store::lxd: install exited 10 with no output "
                    "(attempt 5/5, attempts used up)")


def test_u23b_the_error_line_has_the_message_of_the_last_attempt(capsys):
    """Four Store errors, then a conflict with no text: the ::error line
    says "attempt 5/5", so its message is the 5th attempt's, the exit
    status, not the Store error of the attempts before it."""
    fake = Fake({"snap list lxd": ABSENT,
                 "snap install": [R(1, T3_STORE)] * 4 + [R(10, "")],
                 "snap changes": NO_CHANGES})
    assert run_main(fake) == 3
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ("::error title=Snap Store::lxd: install exited 10 with no output "
                    "(attempt 5/5, attempts used up)")


def test_u23d_a_failure_message_falls_back_to_the_exit_status():
    def result(rc, output):
        return tools.Result(rc=rc, output=output, timed_out=False)

    assert tools.failure_message("install", result(1, "")) == "install exited 1 with no output"
    # An "error: " with nothing after it is no text either.
    assert (tools.failure_message("snap watch 7", result(2, "error: \n"))
            == "snap watch 7 exited 2 with no output")
    assert tools.failure_message("install", result(1, T3_STORE)) == "unable to contact snap store"


@pytest.mark.parametrize(("responses", "code", "expected"), [
    ({"snap list lxd": ABSENT, "snap install": R(1, "")}, 4,
     "lxd: install exited 1 with no output (attempt 1/5, definitive)"),
    ({"snap list lxd": listed("lxd", LXD),
      "snap list snapcraft": listed("snapcraft", "latest/stable"),
      "snap refresh": R(1, "")}, 4,
     "snapcraft: refresh exited 1 with no output (attempt 1/5, definitive)"),
    (lxd_installs(R(0, "7\n"), watch=R(1, "")), 4,
     "lxd: snap watch 7 exited 1 with no output (attempt 1/5, definitive)"),
    ({"snap list lxd": R(1, "")}, 4,
     ("lxd: snap list lxd exited 1 with no output "
      "(before any Store attempt, local snapd unavailable)")),
    ({"snap list lxd": R(0, "")}, 4,
     ("lxd: snap list lxd exited 0 with no output "
      "(before any Store attempt, local snapd unavailable)")),
    ({"snap list lxd": [ABSENT, R(1, "")], "snap install": TIMEOUT,
      "snap changes": NO_CHANGES}, 4,
     "lxd: snap list lxd exited 1 with no output (attempt 1/5, local snapd unavailable)"),
], ids=["install", "refresh", "watch", "first-list", "first-list-exit-0", "reconciliation"])
def test_u23d_a_call_that_fails_with_no_text_keeps_its_exit_status(
        responses, code, expected, capsys):
    """The ::error line names the call and its exit status instead of
    "no error message"."""
    assert run_main(Fake(responses)) == code
    (line,) = error_lines(capsys.readouterr().out)
    assert line == "::error title=Snap Store::" + expected


def test_u23d_the_summary_row_of_a_call_with_no_text_keeps_its_exit_status(tmp_path):
    """The case "install" above, with the summary: its row has the same
    message as the ::error line, not an empty cell."""
    summary = tmp_path / "summary.md"
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(1, "")})
    assert run_main(fake, "--summary", str(summary)) == 4
    rows = [line for line in summary.read_text(encoding="utf-8").splitlines()
            if line.startswith("| lxd ")]
    assert rows == [("| lxd | 1 | 1.0 | exit 1 | definitive | unknown "
                     "| install exited 1 with no output |")]


def test_u23e_a_message_is_cut_to_message_limit_characters(capsys):
    assert tools.MESSAGE_LIMIT == 300
    assert tools.last_message("error: " + "x" * 400 + "\n") == "x" * 300
    assert tools.last_message("no error prefix " + "z" * 400 + "\n") == ("no error prefix "
                                                                         + "z" * 284)
    assert tools.last_message("error: " + "x" * 300 + "\n") == "x" * 300
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(1, "error: " + "y" * 400 + "\n")})
    assert run_main(fake) == 4
    (line,) = error_lines(capsys.readouterr().out)
    assert line == "::error title=Snap Store::lxd: " + "y" * 300 + " (attempt 1/5, definitive)"


@pytest.mark.parametrize(("output", "expected"), [
    ("", "head with no output"),
    ("error: \n", "head with no output"),
    ("error: boom\n", "head: boom"),
], ids=["empty", "empty-error", "text"])
def test_u23f_with_last_message_never_ends_in_a_colon(output, expected):
    assert tools.with_last_message("head", output) == expected


def test_u23c_the_snap_changes_at_the_deadline_have_their_own_heading(tmp_path):
    """The diagnostic is not provenance: it goes under a heading of its
    own, in a block of its own."""
    summary = tmp_path / "summary.md"
    fake = Fake({"snap list lxd": ABSENT, "snap install": TIMEOUT,
                 "snap changes": R(0, IN_PROGRESS_5)})
    assert run_main(fake, "--deadline-seconds", "100", "--summary", str(summary)) == 3
    lines = summary.read_text(encoding="utf-8").splitlines()
    assert "### Provenance" not in lines
    at = lines.index(tools.DIAGNOSTIC_HEADING)
    assert tools.DIAGNOSTIC_HEADING == "### snap changes at the deadline"
    assert lines[at + 1:at + 3] == ["", "```"]
    assert lines[at + 3:at + 6] == IN_PROGRESS_5.splitlines()
    assert lines[at + 6] == "```"


def test_u23c_provenance_and_diagnostic_stay_apart_in_the_summary():
    text = tools.render_summary([], ["lxd 5.21 41296 5.21/stable"], ["5 Doing -"])
    assert text.endswith("### Provenance\n\n```\nlxd 5.21 41296 5.21/stable\n```\n\n"
                         "### snap changes at the deadline\n\n```\n5 Doing -\n```\n")


def test_u24a_an_unanswered_confirmation_is_reconciled():
    fake = Fake({**lxd_installs(R(0, "7\n"), lists=[ABSENT, TIMEOUT, listed("lxd", LXD)]),
                 "snap changes": NO_CHANGES, **snapcraft_ok()})
    assert run_main(fake) == 0
    assert "snap changes" in fake.called()
    assert fake.called().count("snap list lxd") == 3
    assert len(fake.requests("lxd")) == 1


def test_u24b_an_unanswered_first_snap_list_is_definitive(capsys):
    fake = Fake({"snap list lxd": TIMEOUT})
    assert run_main(fake) == 4
    assert fake.requests() == []
    # The first snap list, which alone decides, gets the 130 s that
    # snap changes gets, not the 30 s of the later ones (S-N3).
    assert fake.timeouts("snap list lxd") == [130]
    (line,) = error_lines(capsys.readouterr().out)
    assert line.startswith("::error title=Snap Store::lxd: ")
    assert "local snapd unavailable" in line


def test_u24c_no_matching_snaps_means_install():
    fake = Fake({**lxd_installs(R(0, "7\n")), **snapcraft_ok()})
    assert run_main(fake) == 0
    assert fake.requests("lxd")[0][3] == "install"


def test_u25_a_failed_seed_wait_warns_and_goes_on(capsys):
    fake = Fake({"snap wait": R(1, "error: too early for operation, device not yet seeded or "
                                   "device model not acknowledged\n"),
                 "snap list lxd": listed("lxd", LXD), **snapcraft_ok()})
    assert run_main(fake) == 0
    assert fake.called()[:2] == ["snap wait", "snap list lxd"]
    out = capsys.readouterr().out
    assert any(line.startswith("::warning title=Snap Store::snap wait system seed.loaded "
                               "exited 1: too early for operation")
               for line in out.splitlines())


@pytest.mark.parametrize(("seed", "expected"), [
    (R(1, ""), "snap wait system seed.loaded exited 1 with no output"),
    (TIMEOUT, "snap wait system seed.loaded timed out with no output"),
], ids=["exit-1", "timeout"])
def test_u25_a_seed_wait_with_no_text_says_so(seed, expected, capsys):
    fake = Fake({"snap wait": seed, "snap list lxd": listed("lxd", LXD), **snapcraft_ok()})
    assert run_main(fake) == 0
    warnings = [line for line in capsys.readouterr().out.splitlines()
                if line.startswith("::warning")]
    assert warnings == ["::warning title=Snap Store::" + expected]


def test_u25_the_seed_wait_is_cut_to_the_deadline(capsys):
    """With a deadline shorter than its 120 s, the seed wait gets what is
    left and nothing but the diagnostic starts after the deadline."""
    fake = Fake({"snap wait": TIMEOUT, "snap changes": NO_CHANGES})
    assert run_main(fake, "--deadline-seconds", "100") == 3
    assert [(_key(argv), t, now) for argv, t, now in fake.calls] == [
        ("snap wait", 100, 1000), ("snap changes", 30, 1100)]
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ("::error title=Snap Store::lxd: no attempt fits before the deadline "
                    "(before any Store attempt, deadline)")


def test_u26_the_wait_for_changes_gets_130_s_even_with_less_left():
    fake = Fake({**lxd_installs(R(10, CONFLICT_LXD), R(0, "7\n")),
                 "snap changes": NO_CHANGES, **snapcraft_ok()})
    assert run_main(fake, "--deadline-seconds", "100") == 0
    (start,) = [now for argv, _, now in fake.calls if _key(argv) == "snap changes"]
    assert 1100 - start < 130
    assert fake.timeouts("snap changes") == [130]


def test_u26_the_reconciliation_gets_130_s_even_with_less_left():
    fake = Fake({**lxd_installs(TIMEOUT, lists=[ABSENT, listed("lxd", LXD)]),
                 "snap changes": NO_CHANGES, **snapcraft_ok()})
    assert run_main(fake, "--deadline-seconds", "100", "--attempt-timeout", "10") == 0
    assert fake.timeouts("snap changes") == [130]


def test_u26_no_wait_for_changes_at_the_deadline_and_one_diagnostic(capsys):
    # The request takes the whole deadline: the reconciliation does not
    # run snap changes; only the diagnostic does, once, with 30 s.
    fake = Fake({"snap list lxd": ABSENT, "snap install": TIMEOUT, "snap changes": NO_CHANGES})
    assert run_main(fake, "--deadline-seconds", "100") == 3
    assert fake.timeouts("snap changes") == [30]
    assert fake.called().count("snap list lxd") == 1
    (line,) = error_lines(capsys.readouterr().out)
    assert "attempt 1/5, deadline" in line


@pytest.mark.parametrize("seconds", [88, 120], ids=["at", "past"])
def test_d7_no_snap_list_after_the_deadline_in_the_reconciliation(seconds, capsys):
    """The snap changes of the reconciliation starts before the deadline
    and ends at it or 32 s after it: no snap list follows, unlike in
    confirm(), and the only call that starts after the deadline is the
    diagnostic."""
    fake = Fake({"snap list lxd": [ABSENT, listed("lxd", LXD)], "snap install": TIMEOUT,
                 "snap changes": R(0, NO_CHANGES_TEXT, seconds=seconds)})
    assert run_main(fake, "--deadline-seconds", "100", "--attempt-timeout", "10") == 3
    assert fake.called().count("snap list lxd") == 1
    assert [(_key(argv), t) for argv, t, now in fake.calls if now >= 1100] == [
        ("snap changes", 30)]
    (line,) = error_lines(capsys.readouterr().out)
    assert line == "::error title=Snap Store::lxd: install timed out (attempt 1/5, deadline)"


class _OversleepingFake(Fake):
    """A sleep that ends ``extra`` seconds later than asked, as on a runner
    that stalls: the check before a wait cannot see it coming."""

    extra = 200

    def sleep(self, seconds):
        super().sleep(seconds)
        self.now += self.extra


@pytest.mark.parametrize("extra", [82, 200], ids=["to-the-deadline", "past-it"])
def test_d3_no_request_after_a_sleep_that_ran_past_the_deadline(extra, capsys):
    # The 15 s wait starts at 1003: with 82 s more it ends exactly at the
    # deadline, and a request then would get 0 s.
    fake = _OversleepingFake({"snap list lxd": ABSENT, "snap install": R(1, T3_STORE),
                              "snap changes": NO_CHANGES})
    fake.extra = extra
    assert run_main(fake, "--deadline-seconds", "100") == 3
    assert fake.sleeps == [15]
    assert len(fake.requests()) == 1
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ("::error title=Snap Store::lxd: unable to contact snap store "
                    "(attempt 1/5, deadline)")


OWN_COMMANDS = ("::error title=Snap Store::", "::warning title=Snap Store::")


@pytest.mark.parametrize(("responses", "extra", "code", "child"), [
    ({"snap list lxd": listed("lxd", LXD), **snapcraft_ok(),
      "snap list lxd snapcraft core24 snapd": R(0, "::warning::from-provenance\n")},
     [], 0, "::warning::from-provenance"),
    ({"snap list lxd": ABSENT, "snap install": TIMEOUT,
      "snap changes": R(0, "::error::from-diagnostic\n")},
     ["--deadline-seconds", "100"], 3, "::error::from-diagnostic"),
], ids=["provenance", "diagnostic"])
def test_t1_no_line_of_a_child_reaches_stdout_as_a_workflow_command(
        responses, extra, code, child, tmp_path, capsys):
    summary = tmp_path / "summary.md"
    fake = Fake(responses)
    assert run_main(fake, *extra, "--summary", str(summary)) == code
    out = capsys.readouterr().out
    commands = [line for line in out.splitlines() if line.startswith("::")]
    assert all(line.startswith(OWN_COMMANDS) for line in commands), commands
    # still in the log, behind the prefix, and in the step summary as it was
    assert f"  | {child}" in out
    assert child in summary.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("waitready", [R(1, "error: timed out waiting for LXD\n"), TIMEOUT],
                         ids=["exit-1", "timeout"])
def test_t2_a_failed_lxd_waitready_exits_4_without_the_provenance(waitready, capsys):
    fake = Fake({"snap list lxd": listed("lxd", LXD), **snapcraft_ok(),
                 "lxd waitready": waitready})
    assert run_main(fake) == 4
    assert "lxd waitready" in fake.called()
    assert "snap list lxd snapcraft core24 snapd" not in fake.called()
    (line,) = error_lines(capsys.readouterr().out)
    assert line.startswith("::error title=Snap Store::lxd waitready: ")
    assert line.endswith("(definitive)")


def test_t3_a_snap_list_unanswered_in_the_reconciliation_exits_4(capsys):
    fake = Fake({"snap list lxd": [ABSENT, TIMEOUT], "snap install": TIMEOUT,
                 "snap changes": NO_CHANGES})
    assert run_main(fake) == 4
    assert len(fake.requests()) == 1
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ("::error title=Snap Store::lxd: snap list lxd timed out "
                    "(attempt 1/5, local snapd unavailable)")


@pytest.mark.parametrize(("responses", "extra", "root", "code", "expected"), [
    ({"snap list lxd": TIMEOUT}, [], (0, 0), 4,
     "lxd: snap list lxd timed out (before any Store attempt, local snapd unavailable)"),
    ({**lxd_installs(R(0, "7\n"), watch=R(0, "", seconds=60)),
      "snap list snapcraft": ABSENT, "snap changes": NO_CHANGES},
     ["--deadline-seconds", "100"], (0, 0), 3,
     "snapcraft: no attempt fits before the deadline (before any Store attempt, deadline)"),
    ({"chown": R(1, "chown: changing ownership of '/': Operation not permitted\n")},
     [], (1001, 1001), 4,
     ("chown root:root /: chown: changing ownership of '/': Operation not permitted "
      "(definitive)")),
], ids=["first-list", "deadline", "chown"])
def test_s7_a_failure_before_any_store_attempt_does_not_count_attempt_0(
        responses, extra, root, code, expected, capsys):
    assert run_main(Fake(responses), *extra, root=root) == code
    (line,) = error_lines(capsys.readouterr().out)
    assert line == "::error title=Snap Store::" + expected


def test_the_watch_and_the_request_are_cut_to_the_deadline():
    fake = Fake({**lxd_installs(R(0, "7\n")), **snapcraft_ok()})
    assert run_main(fake, "--deadline-seconds", "120") == 0
    (install,) = fake.timeouts("snap install")
    (watch,) = fake.timeouts("snap watch")
    assert install == 118  # min(150, what is left)
    assert watch == 117


# -- the calls not cut to the deadline ------------------------------------
# What test_w6 adds up: each of these calls keeps its own timeout, even
# with less left, and the step's timeout-minutes is checked against them.

def test_a1_the_calls_not_cut_to_the_deadline_keep_their_own_timeouts():
    fake = Fake({"chown": R(0, ""), **lxd_installs(R(0, "7\n"), R(0, "8\n")),
                 "snap list snapcraft": [ABSENT, listed("snapcraft", SNAPCRAFT)]})
    assert run_main(fake, root=(1001, 1001)) == 0
    assert fake.timeouts("chown") == [tools.CHOWN_TIMEOUT]
    assert fake.timeouts("snap list lxd") == [tools.FIRST_LIST_TIMEOUT, tools.LIST_TIMEOUT]
    assert fake.timeouts("snap list snapcraft") == [tools.FIRST_LIST_TIMEOUT,
                                                    tools.LIST_TIMEOUT]
    assert fake.timeouts("lxd waitready") == [tools.WAITREADY_TIMEOUT]
    assert fake.timeouts("snap list lxd snapcraft core24 snapd") == [tools.PROVENANCE_TIMEOUT]


def test_a1_the_tail_of_test_w6_runs_whole_after_the_deadline():
    """A watch that ends well exactly at the deadline: the confirming snap
    list, lxd waitready and the provenance all start after it, each with
    its own timeout, and the run is green."""
    fake = Fake({"snap list lxd": listed("lxd", LXD),
                 "snap list snapcraft": [ABSENT, listed("snapcraft", SNAPCRAFT)],
                 "snap install": R(0, "8\n"), "snap watch": R(0, "", seconds=96)})
    assert run_main(fake, "--deadline-seconds", "100") == 0
    # seed, the two first lists and the install take 1 s each; the watch
    # gets the 96 s left and uses them all.
    assert [(_key(argv), t) for argv, t, now in fake.calls if now >= 1100] == [
        ("snap list snapcraft", tools.LIST_TIMEOUT),
        ("lxd waitready", tools.WAITREADY_TIMEOUT),
        ("snap list lxd snapcraft core24 snapd", tools.PROVENANCE_TIMEOUT)]


def test_a1_the_snap_list_of_a_reconciliation_keeps_its_30_s_with_less_left():
    # seed 1 s, snap list 1 s, the install times out at 10 s and snap
    # changes takes 80 s: 8 s are left when the snap list starts.
    fake = Fake({**lxd_installs(TIMEOUT, lists=[ABSENT, listed("lxd", LXD)]),
                 "snap changes": R(0, NO_CHANGES_TEXT, seconds=80), **snapcraft_ok()})
    assert run_main(fake, "--deadline-seconds", "100", "--attempt-timeout", "10") == 3
    ((_, _, start),) = [c for c in fake.calls if _key(c[0]) == "snap list lxd"][1:]
    assert 1100 - start < tools.LIST_TIMEOUT
    assert fake.timeouts("snap list lxd") == [tools.FIRST_LIST_TIMEOUT, tools.LIST_TIMEOUT]
    assert fake.timeouts("snap list lxd") == [130, 30]
    assert len(fake.requests("lxd")) == 1


@pytest.mark.parametrize("seconds", [10, 20], ids=["to-the-deadline", "past-it"])
def test_a1_chown_keeps_its_own_timeout_past_a_short_deadline(seconds, capsys):
    """chown is not cut either: with a deadline shorter than its timeout
    it still gets its 30 s, and when it ends at or after the deadline,
    nothing but the diagnostic follows it (no seed wait of 0 s)."""
    fake = Fake({"chown": R(0, "", seconds=seconds), "snap changes": NO_CHANGES})
    assert run_main(fake, "--deadline-seconds", "10", root=(1001, 1001)) == 3
    assert [(_key(argv), t, now) for argv, t, now in fake.calls] == [
        ("chown", tools.CHOWN_TIMEOUT, 1000),
        ("snap changes", tools.DIAGNOSTIC_TIMEOUT, 1000 + seconds)]
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ("::error title=Snap Store::lxd: no attempt fits before the deadline "
                    "(before any Store attempt, deadline)")


@pytest.mark.parametrize(("waitready", "expected"), [
    (R(1, ""), "lxd waitready: exit 1 (definitive)"),
    (TIMEOUT, "lxd waitready: timed out (definitive)"),
    (R(1, "error: timed out waiting for LXD\n"),
     "lxd waitready: timed out waiting for LXD (definitive)"),
], ids=["exit-1", "timeout", "text"])
def test_a2_a_failed_lxd_waitready_says_how_it_failed(waitready, expected, capsys):
    fake = Fake({"snap list lxd": listed("lxd", LXD), **snapcraft_ok(),
                 "lxd waitready": waitready})
    assert run_main(fake) == 4
    (line,) = error_lines(capsys.readouterr().out)
    assert line == "::error title=Snap Store::" + expected


# -- the rows of the summary ----------------------------------------------

def _rows(summary, snap="lxd"):
    return [line for line in summary.read_text(encoding="utf-8").splitlines()
            if line.startswith(f"| {snap} ")]


def test_c1_the_row_of_an_attempt_with_a_watch_is_the_watch_s(tmp_path):
    """The request answered exit 0 with a change id; the watch failed: the
    row has the watch's exit status, kind, rule and message, and the time
    of both calls."""
    summary = tmp_path / "summary.md"
    fake = Fake({**lxd_installs(R(0, "7\n"), watch=R(1, ""))})
    assert run_main(fake, "--summary", str(summary)) == 4
    assert _rows(summary) == [
        "| lxd | 1 | 2.0 | exit 1 | definitive | unknown | snap watch 7 exited 1 with no output |"]


def test_c1_the_rows_of_a_watch_that_fails_on_the_store_then_ends_well(tmp_path):
    summary = tmp_path / "summary.md"
    fake = Fake({**lxd_installs(R(0, "7\n"), R(0, "8\n"),
                                watch=[R(1, T3_STORE, seconds=3), R(0, "")]),
                 **snapcraft_ok()})
    assert run_main(fake, "--summary", str(summary)) == 0
    assert _rows(summary) == [
        ("| lxd | 1 | 4.0 | exit 1 | retry | unable to contact snap store "
         "| unable to contact snap store |"),
        "| lxd | 2 | 3.0 | exit 0 | success | confirmed |  |"]
    assert _rows(summary, "snapcraft") == [
        "| snapcraft | 1 | 2.0 | exit 0 | success | confirmed |  |"]
    text = summary.read_text(encoding="utf-8")
    assert "- lxd: installed\n- snapcraft: installed\n" in text


@pytest.mark.parametrize(("install", "watch", "row", "message"), [
    (R(0, "7\n", seconds=98), None, "| lxd | 1 | 98.0 | exit 0 | deadline | deadline |  |",
     "change 7 started, not watched: the deadline came with the request's answer"),
    (R(0, "7\n"), TIMEOUT, "| lxd | 1 | 98.0 | timed out | deadline | deadline |  |",
     "change 7 still running at the deadline"),
], ids=["not-watched", "watch-timed-out"])
def test_c1_the_row_and_the_error_of_a_change_left_at_the_deadline(
        install, watch, row, message, tmp_path, capsys):
    summary = tmp_path / "summary.md"
    fake = Fake({**lxd_installs(install, watch=watch), "snap changes": NO_CHANGES})
    assert run_main(fake, "--deadline-seconds", "100", "--summary", str(summary)) == 3
    assert _rows(summary) == [row]
    assert "- lxd: failed, deadline" in summary.read_text(encoding="utf-8").splitlines()
    (line,) = error_lines(capsys.readouterr().out)
    assert line == f"::error title=Snap Store::lxd: {message} (attempt 1/5, deadline)"


def test_c1_the_row_of_a_timed_out_request(tmp_path):
    summary = tmp_path / "summary.md"
    fake = Fake({**lxd_installs(TIMEOUT, lists=[ABSENT, listed("lxd", LXD)]),
                 "snap changes": NO_CHANGES, **snapcraft_ok()})
    assert run_main(fake, "--attempt-timeout", "10", "--summary", str(summary)) == 0
    assert _rows(summary) == [
        "| lxd | 1 | 10.0 | timed out | uncertain | timeout | install timed out |"]


def test_c1_a_pipe_in_the_message_of_a_request_is_escaped(tmp_path):
    summary = tmp_path / "summary.md"
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(1, "error: a | b\n")})
    assert run_main(fake, "--summary", str(summary)) == 4
    assert _rows(summary) == [r"| lxd | 1 | 1.0 | exit 1 | definitive | unknown | a \| b |"]


def test_u6_an_attempt_that_fits_exactly_before_the_deadline_starts(capsys):
    """At 1002, after the seed wait and the snap list, an attempt of 50 s
    ends exactly at the deadline: it starts, with those 50 s."""
    fake = Fake({**lxd_installs(R(0, "7\n")), **snapcraft_ok(), "snap changes": NO_CHANGES})
    assert run_main(fake, "--deadline-seconds", "52") == 3
    assert fake.timeouts("snap install") == [50]
    (line,) = error_lines(capsys.readouterr().out)
    assert line.startswith("::error title=Snap Store::snapcraft: ")


@pytest.mark.parametrize("seconds", [97, 120], ids=["at", "past"])
def test_u17d_no_watch_of_a_change_in_progress_found_at_the_deadline(seconds, capsys):
    """snap changes ends at or after the deadline and lists a change in
    progress: it is not watched, not even with 0 s."""
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(10, CONFLICT_LXD),
                 "snap changes": [R(0, IN_PROGRESS_5, seconds=seconds), NO_CHANGES]})
    assert run_main(fake, "--deadline-seconds", "100") == 3
    assert "snap watch" not in fake.called()
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ('::error title=Snap Store::lxd: snap "lxd" has "install-snap" change in '
                    "progress (attempt 1/5, deadline)")


def test_u17d_a_conflict_on_the_last_attempt_that_meets_the_deadline_is_a_deadline(capsys):
    """With one attempt, the wait for a change in progress runs into the
    deadline: a deadline failure with its diagnostic, not "attempts used
    up"."""
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(10, CONFLICT_LXD),
                 "snap changes": R(0, IN_PROGRESS_5), "snap watch": R(0, "", seconds=500)})
    assert run_main(fake, "--attempts", "1", "--deadline-seconds", "100") == 3
    assert fake.timeouts("snap changes") == [tools.CHANGES_TIMEOUT, tools.DIAGNOSTIC_TIMEOUT]
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ('::error title=Snap Store::lxd: snap "lxd" has "install-snap" change in '
                    "progress (attempt 1/1, deadline)")


def test_d7_a_change_still_running_at_the_deadline_in_the_reconciliation(tmp_path, capsys):
    """The watch of the reconciliation runs into the deadline: a deadline
    failure, not a local snapd one, and no note about that change."""
    summary = tmp_path / "summary.md"
    fake = Fake({"snap list lxd": ABSENT, "snap install": TIMEOUT,
                 "snap changes": R(0, IN_PROGRESS_5), "snap watch": R(0, "", seconds=500)})
    assert run_main(fake, "--deadline-seconds", "100", "--attempt-timeout", "10",
                    "--summary", str(summary)) == 3
    assert fake.timeouts("snap watch") == [87]
    assert "### Notes" not in summary.read_text(encoding="utf-8").splitlines()
    (line,) = error_lines(capsys.readouterr().out)
    assert line == "::error title=Snap Store::lxd: install timed out (attempt 1/5, deadline)"


@pytest.mark.parametrize("changes", [
    R(1, "error: cannot list changes\n"),
    # Defensive: snap exits non-zero with this text; an exit 0 with it
    # still counts as no answer.
    R(0, "error: cannot communicate with server: connection refused\n"),
], ids=["exit-1", "local-text"])
def test_u21_a_snap_changes_that_fails_leaves_no_answer(changes, capsys):
    fake = Fake({"snap list lxd": ABSENT, "snap install": TIMEOUT, "snap changes": changes})
    assert run_main(fake, "--attempt-timeout", "10") == 4
    assert len(fake.requests()) == 1
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ("::error title=Snap Store::lxd: install timed out "
                    "(attempt 1/5, local snapd unavailable)")


def test_u17_the_changes_in_progress_are_watched_in_the_order_snap_lists_them():
    in_progress = IN_PROGRESS_5 + (
        '6    Doing   2026-11-12T20:01:00Z  -                     Auto-refresh snap "snapd"\n')
    fake = Fake({**lxd_installs(R(10, CONFLICT_LXD), R(0, "7\n")),
                 "snap changes": R(0, in_progress), **snapcraft_ok()})
    assert run_main(fake) == 0
    assert [argv[-1] for argv in fake.argvs() if _key(argv) == "snap watch"] == ["5", "6", "7"]


def test_u17_a_change_in_progress_that_ends_well_leaves_no_note(tmp_path):
    summary = tmp_path / "summary.md"
    fake = Fake({**lxd_installs(R(10, CONFLICT_LXD), R(0, "7\n")),
                 "snap changes": R(0, IN_PROGRESS_5), **snapcraft_ok()})
    assert run_main(fake, "--summary", str(summary)) == 0
    assert "### Notes" not in summary.read_text(encoding="utf-8").splitlines()


def test_u17c_the_note_of_a_snapcraft_change_goes_to_the_summary_too(tmp_path):
    summary = tmp_path / "summary.md"
    fake = Fake({"snap list lxd": listed("lxd", LXD),
                 "snap list snapcraft": [ABSENT, listed("snapcraft", SNAPCRAFT)],
                 "snap install": [R(10, CONFLICT_CORE24), R(0, "8\n")],
                 "snap changes": R(0, IN_PROGRESS_5),
                 "snap watch": [R(1, 'error: snap "core24" not found\n'), R(0, "")]})
    assert run_main(fake, "--summary", str(summary)) == 0
    lines = summary.read_text(encoding="utf-8").splitlines()
    at = lines.index("### Notes")
    assert lines[at + 1:at + 3] == [
        "", ('- change 5 in progress ended with exit 1 (definitive, unknown): '
             'snap "core24" not found')]


def test_u9_the_warning_about_the_lxd_channel_is_also_a_note(tmp_path):
    summary = tmp_path / "summary.md"
    fake = Fake({"snap list lxd": listed("lxd", "6/stable"), **snapcraft_ok()})
    assert run_main(fake, "--summary", str(summary)) == 0
    lines = summary.read_text(encoding="utf-8").splitlines()
    at = lines.index("### Notes")
    assert lines[at + 1:at + 3] == [
        "", "- lxd is installed from 6/stable, not 5.21/stable; left as it is"]


def test_u24a_an_unanswered_confirmation_with_no_snapd_keeps_its_message(tmp_path, capsys):
    summary = tmp_path / "summary.md"
    fake = Fake({**lxd_installs(R(0, "7\n"), lists=[ABSENT, TIMEOUT]), "snap changes": TIMEOUT})
    assert run_main(fake, "--summary", str(summary)) == 4
    assert _rows(summary) == [
        "| lxd | 1 | 32.0 | exit 0 | uncertain | list-unknown | snap list lxd timed out |"]
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ("::error title=Snap Store::lxd: snap list lxd timed out "
                    "(attempt 1/5, local snapd unavailable)")


def test_u19_a_change_that_ends_well_with_the_snap_absent_is_definitive(tmp_path, capsys):
    summary = tmp_path / "summary.md"
    fake = Fake(lxd_installs(R(0, "7\n"), lists=[ABSENT]))
    assert run_main(fake, "--summary", str(summary)) == 4
    expected = "snap list shows lxd not installed, expected 5.21/stable"
    assert _rows(summary) == [
        f"| lxd | 1 | 3.0 | exit 0 | definitive | list-mismatch | {expected} |"]
    (line,) = error_lines(capsys.readouterr().out)
    assert line == f"::error title=Snap Store::lxd: {expected} (attempt 1/5, definitive)"


def test_u11_the_summary_is_written_as_utf_8(tmp_path):
    # "→" is not in cp1252, the locale encoding of a Windows test machine.
    summary = tmp_path / "summary.md"
    fake = Fake({"snap list lxd": ABSENT, "snap install": R(1, "error: não → ok\n")})
    assert run_main(fake, "--summary", str(summary)) == 4
    assert _rows(summary) == ["| lxd | 1 | 1.0 | exit 1 | definitive | unknown | não → ok |"]


def test_u11_an_empty_github_step_summary_writes_no_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", "")
    monkeypatch.chdir(tmp_path)
    fake = Fake({"snap list lxd": listed("lxd", LXD), **snapcraft_ok()})
    assert run_main(fake) == 0
    assert list(tmp_path.iterdir()) == []


def test_u11_the_provenance_names_the_craft_providers_found(tmp_path, monkeypatch):
    site = tmp_path / "site-packages"
    for version in ("2.1.0", "1.20.0"):
        (site / f"craft_providers-{version}.dist-info").mkdir(parents=True)
    monkeypatch.setattr(tools, "PROVENANCE_GLOB",
                        os.path.join(glob.escape(str(site)), "craft_providers-*.dist-info"))
    summary = tmp_path / "summary.md"
    fake = Fake({"snap list lxd": listed("lxd", LXD), **snapcraft_ok()})
    assert run_main(fake, "--summary", str(summary)) == 0
    lines = summary.read_text(encoding="utf-8").splitlines()
    assert lines[lines.index("### Provenance") + 2:] == [
        "```", "Name Version Rev Tracking",
        "craft-providers: craft_providers-1.20.0.dist-info, craft_providers-2.1.0.dist-info",
        "```"]


def test_u11_the_provenance_says_when_craft_providers_is_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "PROVENANCE_GLOB",
                        os.path.join(glob.escape(str(tmp_path)), "craft_providers-*.dist-info"))
    summary = tmp_path / "summary.md"
    fake = Fake({"snap list lxd": listed("lxd", LXD), **snapcraft_ok()})
    assert run_main(fake, "--summary", str(summary)) == 0
    assert "craft-providers: not found" in summary.read_text(encoding="utf-8").splitlines()


def test_t1_a_workflow_command_cannot_be_split_by_a_line_break():
    """No message reaches these with a line break today (they are
    normalised); the escaping is still what @actions/core does."""
    assert tools.render_warning("a%b\r\nc") == "::warning title=Snap Store::a%25b%0D%0Ac"
    outcome = tools.Outcome(snap="lxd", ok=False, cause=tools.CAUSE_DEFINITIVE, attempt=1,
                            attempts=5, message="x\r\ny")
    assert tools.render_error("lxd", outcome) == (
        "::error title=Snap Store::lxd: x%0D%0Ay (attempt 1/5, definitive)")
    outcome.message = ""
    assert tools.render_error("lxd", outcome) == (
        "::error title=Snap Store::lxd: no error message (attempt 1/5, definitive)")


def test_t1_each_call_is_logged_with_its_timeout_and_how_it_ended(capsys):
    fake = Fake({"snap list lxd": ABSENT, "snap install": [TIMEOUT, R(1, NOT_FOUND)],
                 "snap changes": NO_CHANGES})
    assert run_main(fake, "--attempt-timeout", "10") == 4
    out = capsys.readouterr().out.splitlines()
    at = out.index("$ sudo -n snap install --no-wait --channel=5.21/stable lxd  (timeout 10 s)")
    assert out[at + 1] == "  timed out after 10.0 s"
    at = out.index("$ sudo -n snap install --no-wait --channel=5.21/stable lxd  (timeout 10 s)",
                   at + 1)
    assert out[at + 1:at + 3] == ["  exit 1 after 1.0 s", '  | error: snap "lxdd" not found']


def test_main_counts_the_deadline_on_the_monotonic_clock(monkeypatch):
    """With no clock given, main uses time.monotonic, which a change of the
    wall clock does not move."""
    fake = Fake({**lxd_installs(R(0, "7\n")), **snapcraft_ok()})
    monkeypatch.setattr(tools.time, "monotonic", fake.clock)
    assert tools.main(["--lxd-channel", LXD, "--snapcraft-channel", SNAPCRAFT,
                       "--deadline-seconds", "120"],
                      run=fake.run, sleep=fake.sleep, root_owner=lambda: (0, 0)) == 0
    assert fake.timeouts("snap install") == [118]


# -- real subprocesses ----------------------------------------------------

_STUB = r'''
import json
import os
import sys
import time

STATE = {state!r}


def key(args):
    if args[0] in ("chown", "sudo"):
        return args[0]
    if args[1] == "list":
        return " ".join(args)
    return " ".join(args[:2])


def main():
    args = sys.argv[1:]
    with open(STATE, encoding="utf-8") as fh:
        state = json.load(fh)
    state["calls"].append(args)
    queue = state["responses"].get(key(args)) or []
    answer = (queue.pop(0) if len(queue) > 1 else queue[0]) if queue else None
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    if args[0] == "sudo":
        if args[1:2] != ["-n"]:
            sys.stderr.write("sudo: a password is required\n")
            return 1
        os.execvp(args[2], args[2:])
    if answer is None:
        sys.stderr.write("stub: no answer for " + key(args) + "\n")
        return 99
    sys.stdout.write(answer.get("out", ""))
    sys.stdout.flush()
    sys.stderr.write(answer.get("err", ""))
    sys.stderr.flush()
    time.sleep(answer.get("sleep", 0))
    return answer.get("rc", 0)


sys.exit(main())
'''


class Stub:
    def __init__(self, directory: Path, responses: dict):
        directory.mkdir(parents=True, exist_ok=True)
        self.state = directory / "state.json"
        self.state.write_text(json.dumps({"calls": [], "responses": responses}),
                              encoding="utf-8")
        self.path = directory / "stub.py"
        self.path.write_text(_STUB.format(state=str(self.state)), encoding="utf-8")

    def commands(self):
        base = (sys.executable, "-I", str(self.path))
        return tools.Commands(sudo=(), snap=(*base, "snap"), lxd=(*base, "lxd"),
                              chown=(*base, "chown"))

    def calls(self):
        return json.loads(self.state.read_text(encoding="utf-8"))["calls"]


def _ok(out=""):
    return {"rc": 0, "out": out}


S_ABSENT = {"rc": 1, "err": ABSENT_TEXT}
S_NO_CHANGES = {"rc": 0, "err": NO_CHANGES_TEXT}


def _list(name, channel):
    return {"rc": 0, "out": listed(name, channel).out}


def test_e1_main_with_real_processes(tmp_path, capsys):
    stub = Stub(tmp_path / "stub dir ç", {
        "chown": [_ok()],
        "snap wait": [_ok()],
        "snap list lxd": [S_ABSENT, _list("lxd", LXD)],
        "snap install": [{"rc": 1, "err": T1_EOF}, _ok("42\n"), _ok("43\n")],
        "snap watch": [_ok()],
        "snap list snapcraft": [S_ABSENT, _list("snapcraft", SNAPCRAFT)],
        "lxd waitready": [_ok()],
        "snap list lxd snapcraft core24 snapd": [_ok("Name Version Rev Tracking\n")],
    })
    sleeps = []
    rc = tools.main(["--lxd-channel", LXD, "--snapcraft-channel", SNAPCRAFT],
                    sleep=sleeps.append, commands=stub.commands(),
                    root_owner=lambda: (1001, 1001))
    assert rc == 0
    assert sleeps == [15]
    assert stub.calls() == [
        ["chown", "root:root", "/"],
        ["snap", "wait", "system", "seed.loaded"],
        ["snap", "list", "lxd"],
        ["snap", "install", "--no-wait", f"--channel={LXD}", "lxd"],
        ["snap", "install", "--no-wait", f"--channel={LXD}", "lxd"],
        ["snap", "watch", "42"],
        ["snap", "list", "lxd"],
        ["snap", "list", "snapcraft"],
        ["snap", "install", "--no-wait", f"--channel={SNAPCRAFT}", "--classic", "snapcraft"],
        ["snap", "watch", "43"],
        ["snap", "list", "snapcraft"],
        ["lxd", "waitready", "--timeout=120"],
        ["snap", "list", "lxd", "snapcraft", "core24", "snapd"],
    ]
    out = capsys.readouterr().out
    # stderr of the child is captured, line by line
    assert '  | error: cannot install "lxd": Post "https://api.snapcraft.io/v2/snaps/refresh":' in out
    assert "  |        EOF" in out
    assert error_lines(out) == []


def test_e1_a_definitive_error_from_a_real_process_exits_4(tmp_path, capsys):
    stub = Stub(tmp_path / "stub", {
        "snap wait": [_ok()], "snap list lxd": [S_ABSENT],
        "snap install": [{"rc": 1, "err": NOT_FOUND}],
    })
    rc = tools.main(["--lxd-channel", LXD, "--snapcraft-channel", SNAPCRAFT],
                    sleep=lambda s: None, commands=stub.commands(),
                    root_owner=lambda: (0, 0))
    assert rc == 4
    (line,) = error_lines(capsys.readouterr().out)
    assert line == ('::error title=Snap Store::lxd: snap "lxdd" not found '
                    "(attempt 1/5, definitive)")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX executables on PATH")
def test_e2_the_program_goes_through_sudo_n(tmp_path):
    stub = Stub(tmp_path / "stub", {
        "snap wait": [_ok()],
        "snap list lxd": [S_ABSENT, _list("lxd", LXD)],
        "snap install": [_ok("42\n"), _ok("43\n")],
        "snap watch": [_ok()],
        "snap list snapcraft": [S_ABSENT, _list("snapcraft", SNAPCRAFT)],
        "lxd waitready": [_ok()],
        "chown": [_ok()],
        "snap list lxd snapcraft core24 snapd": [_ok("Name Version Rev Tracking\n")],
    })
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("sudo", "snap", "lxd", "chown"):
        exe = bindir / name
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{stub.path}" {name} "$@"\n',
                       encoding="utf-8", newline="\n")
        exe.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_STEP_SUMMARY"}
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--lxd-channel", LXD,
         "--snapcraft-channel", SNAPCRAFT, "--summary", str(tmp_path / "summary.md")],
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    sudo = [call for call in stub.calls() if call[0] == "sudo"]
    assert ["sudo", "-n", "snap", "install", "--no-wait", f"--channel={LXD}", "lxd"] in sudo
    assert ["sudo", "-n", "snap", "watch", "42"] in sudo
    assert ["sudo", "-n", "lxd", "waitready", "--timeout=120"] in sudo
    # snap list and snap changes never go through sudo
    assert not [call for call in sudo if call[2:4] in (["snap", "list"], ["snap", "changes"])]


def test_e3_help_lists_the_exit_codes():
    proc = subprocess.run([sys.executable, "-I", str(SCRIPT), "--help"],
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    assert "  3  a retryable" in proc.stdout
    assert "  4  a definitive" in proc.stdout


@pytest.mark.parametrize(("option", "dest"), [
    ("--attempts", "attempts"),
    ("--deadline-seconds", "deadline_seconds"),
    ("--attempt-timeout", "attempt_timeout"),
])
def test_e3_help_shows_the_defaults_the_parser_uses(option, dest, capsys):
    # CONTRIBUTING.md sends readers to --help for the defaults, so a value
    # written by hand in a help= would be a second source that drifts.
    with pytest.raises(SystemExit) as exc:
        tools.main(["--help"])
    assert exc.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    shown = re.search(re.escape(option) + r" [A-Z_]+ [^()]*\(default: ([^)]*)\)", text)
    assert shown, (option, text)
    default = tools._parser().get_default(dest)
    assert type(default)(shown.group(1)) == default, (option, shown.group(1), default)


def test_e4a_a_request_that_hangs_is_killed_and_reconciled(tmp_path, capsys):
    stub = Stub(tmp_path / "stub", {
        "snap wait": [_ok()], "snap list lxd": [S_ABSENT],
        "snap install": [{"rc": 0, "out": "partial\n", "sleep": 30}],
        "snap changes": [S_NO_CHANGES],
    })
    start = time.monotonic()
    rc = tools.main(["--lxd-channel", LXD, "--snapcraft-channel", SNAPCRAFT,
                     "--attempt-timeout", "1", "--attempts", "1"],
                    commands=stub.commands(), root_owner=lambda: (0, 0))
    elapsed = time.monotonic() - start
    out = capsys.readouterr().out
    assert rc == 3
    assert "Traceback" not in out
    keys = [" ".join(call[:2]) for call in stub.calls()]
    assert keys.index("snap changes") > keys.index("snap install")
    (line,) = error_lines(out)
    assert line.startswith("::error title=Snap Store::lxd: ")
    assert elapsed < 15, elapsed


def test_e4b_a_watch_that_hangs_stops_at_the_deadline(tmp_path, capsys):
    stub = Stub(tmp_path / "stub", {
        "snap wait": [_ok()], "snap list lxd": [S_ABSENT],
        "snap install": [_ok("7\n")],
        "snap watch": [{"rc": 0, "sleep": 30}],
        "snap changes": [S_NO_CHANGES],
    })
    start = time.monotonic()
    rc = tools.main(["--lxd-channel", LXD, "--snapcraft-channel", SNAPCRAFT,
                     "--deadline-seconds", "4"],
                    commands=stub.commands(), root_owner=lambda: (0, 0), min_attempt=0.5)
    elapsed = time.monotonic() - start
    out = capsys.readouterr().out
    assert rc == 3
    assert "Traceback" not in out
    assert ["snap", "watch", "7"] in stub.calls()
    assert ["snap", "changes", "--abs-time"] in stub.calls()
    (line,) = error_lines(out)
    assert "deadline" in line
    assert elapsed < 15, elapsed


def test_e5_a_missing_executable_exits_4_without_a_traceback(tmp_path, capsys):
    missing = str(tmp_path / "no such dir" / "snap")
    rc = tools.main(["--lxd-channel", LXD, "--snapcraft-channel", SNAPCRAFT],
                    commands=tools.Commands(sudo=(), snap=(missing,), lxd=(missing,),
                                            chown=(missing,)),
                    root_owner=lambda: (0, 0))
    out = capsys.readouterr().out
    assert rc == 4
    assert "Traceback" not in out
    (line,) = error_lines(out)
    assert line.startswith("::error title=Snap Store::lxd: ")
    assert "Error" in line  # the OSError's type, e.g. FileNotFoundError


@pytest.mark.parametrize(("partial", "expected"), [
    (b"partial-output-marker\n", ["partial-output-marker"]),
    # On POSIX, nothing read yet is None in the TimeoutExpired.
    (b"", []),
    # UTF-8 is decoded, and a byte that is not UTF-8 replaced, as in a
    # call that does not time out.
    ("não →\n".encode() + b"\xff\n", ["não →", "�"]),
], ids=["text", "nothing", "utf-8"])
def test_e6_default_run_returns_the_partial_output_of_a_timeout_as_text(
        partial, expected, tmp_path):
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text(
        "import sys, time\n"
        f"sys.stdout.buffer.write({partial!r})\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n", encoding="utf-8")
    start = time.monotonic()
    result = tools.default_run([sys.executable, "-I", str(sleeper)], 1.0)
    assert time.monotonic() - start < 15
    assert result.timed_out
    assert result.rc is None
    assert isinstance(result.output, str)
    assert result.output.splitlines() == expected


_RUN_IN_CHILD = r'''
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("tools", sys.argv[1])
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)
r = tools.default_run([sys.executable, "-I", sys.argv[2]], 60.0)
sys.stdout.write(repr((r.rc, r.output)))
'''


def test_e7_default_run_gives_the_child_no_stdin(tmp_path):
    """The script's own stdin is a pipe with data here: a child that reads
    its stdin must get end of file at once, not that data (nor, on a
    runner, wait on a stdin that never ends)."""
    reader = tmp_path / "reader.py"
    reader.write_text("import sys\nsys.stdout.write('read ' + repr(sys.stdin.read()))\n",
                      encoding="utf-8")
    parent = tmp_path / "parent.py"
    parent.write_text(_RUN_IN_CHILD, encoding="utf-8")
    proc = subprocess.run([sys.executable, "-I", str(parent), str(SCRIPT), str(reader)],
                          input="data of the parent\n", capture_output=True, text=True,
                          encoding="utf-8", timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == repr((0, "read ''"))


def test_e8_default_run_decodes_utf_8_and_replaces_what_is_not(tmp_path):
    child = tmp_path / "child.py"
    child.write_text("import sys\nsys.stdout.buffer.write('não →\\n'.encode() + b'\\xff\\n')\n",
                     encoding="utf-8")
    result = tools.default_run([sys.executable, "-I", str(child)], 60.0)
    assert result == tools.Result(rc=0, output="não →\n�\n", timed_out=False)


def test_e5_default_run_turns_an_os_error_into_exit_127(tmp_path):
    missing = tools.default_run([str(tmp_path / "missing")], 60.0)
    assert (missing.rc, missing.timed_out) == (127, False)
    assert missing.output.startswith("FileNotFoundError: ")
    # Not only a missing file: a directory is a PermissionError.
    directory = tools.default_run([str(tmp_path)], 60.0)
    assert (directory.rc, directory.timed_out) == (127, False)
    assert directory.output.startswith("PermissionError: ")


# -- snap-build.yml -------------------------------------------------------

def _build_job():
    workflow = load_workflow("snap-build.yml")
    return workflow, workflow["jobs"]["build"]


def _script_step(steps):
    (index,) = [i for i, s in enumerate(steps)
                if "scripts/install_snap_tools.py" in s.get("run", "")]
    return index, steps[index]


def _step_named(steps, name):
    (index,) = [i for i, s in enumerate(steps) if s.get("name") == name]
    return index, steps[index]


def _arg(run, option):
    words = shlex.split(run)
    return words[words.index(option) + 1]


def test_w1_the_script_runs_before_the_build():
    _, job = _build_job()
    steps = job["steps"]
    script, _ = _script_step(steps)
    (build,) = [i for i, s in enumerate(steps) if s.get("id") == "build"]
    assert script < build


def test_w2_the_script_installs_the_snapcraft_channel_the_action_refreshes_to():
    _, job = _build_job()
    steps = job["steps"]
    _, script = _script_step(steps)
    (build,) = [s for s in steps if s.get("id") == "build"]
    assert _arg(script["run"], "--snapcraft-channel") == build["with"]["snapcraft-channel"]
    assert tools.validate_channel(_arg(script["run"], "--lxd-channel"))


def test_w3_the_script_is_in_both_paths_filters():
    workflow, _ = _build_job()
    on = workflow.get("on", workflow.get(True))
    for event in ("pull_request", "push"):
        assert "scripts/install_snap_tools.py" in on[event]["paths"], event


def test_w4_only_the_probe_may_fail():
    _, job = _build_job()
    steps = job["steps"]
    _, probe = _step_named(steps, "Probe the Snap Store")
    _, script = _script_step(steps)
    assert probe.get("continue-on-error") is True
    assert not script.get("continue-on-error", False)
    # continue-on-error does not cover a hang: without its own timeout the
    # probe could use up the job's before the build starts.
    assert 0 < probe.get("timeout-minutes", 0) < job["timeout-minutes"]


NEW_STEPS = ("Probe the Snap Store", "Install LXD and Snapcraft",
             "Show what snapcraft mounted in the instance", "Upload the snapcraft logs")


def test_w5_no_secret_or_token_reaches_the_new_steps():
    """None of the four steps this change adds to snap-build.yml reads a
    secret or the GitHub token, in its run, env, with or if, nor has an
    expression in its shell script; neither do the env of the job and of
    the workflow."""
    workflow, job = _build_job()
    steps = [_step_named(job["steps"], name)[1] for name in NEW_STEPS]
    assert [s for s in steps if "run" in s] == steps[:3]
    for step in steps:
        for part in ("run", "env", "with", "if"):
            text = str(step.get(part, ""))
            assert "secrets." not in text, (step["name"], part)
            assert "github.token" not in text, (step["name"], part)
        assert "${{" not in step.get("run", ""), step["name"]
    for scope in (job.get("env", {}), workflow.get("env", {})):
        assert "secrets." not in str(scope)
        assert "github.token" not in str(scope)


def test_w6_the_install_step_times_out_after_the_script_would():
    _, job = _build_job()
    _, script = _script_step(job["steps"])
    words = shlex.split(script["run"])
    deadline = (float(_arg(script["run"], "--deadline-seconds"))
                if "--deadline-seconds" in words
                else tools._parser().get_default("deadline_seconds"))
    # What can still run past the deadline, the longest of: a confirming
    # snap list, lxd waitready and the provenance; or a call of 130 s
    # started just before it, then the diagnostic.
    tail = max(tools.LIST_TIMEOUT + tools.WAITREADY_TIMEOUT + tools.PROVENANCE_TIMEOUT,
               tools.CHANGES_TIMEOUT + tools.DIAGNOSTIC_TIMEOUT,
               tools.FIRST_LIST_TIMEOUT + tools.DIAGNOSTIC_TIMEOUT)
    # chown, the first call, is not cut either: a chown longer than the
    # deadline would move the start of that tail to its own end.
    start_of_tail = max(deadline, tools.CHOWN_TIMEOUT)
    assert start_of_tail + tail < script["timeout-minutes"] * 60 < job["timeout-minutes"] * 60


def test_t4_the_local_build_instructions_use_the_channels_of_ci():
    _, job = _build_job()
    _, script = _script_step(job["steps"])
    readme = (ROOT / "snap" / "local" / "README.md").read_text(encoding="utf-8")
    channels = dict(re.findall(r"^sudo snap install (\S+)[^\n]*--channel=(\S+)", readme,
                               re.MULTILINE))
    assert channels == {"snapcraft": _arg(script["run"], "--snapcraft-channel"),
                        "lxd": _arg(script["run"], "--lxd-channel")}


# Like curl: the -w line is written even when the transfer fails, then
# with HTTP 000.
_FAKE_CURL = r'''#!/bin/sh
fmt=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-w" ]; then fmt="$2"; shift; fi
  shift
done
rc="${FAKE_CURL_RC:-0}"
if [ "$rc" -eq 0 ]; then code=200; else code=000; fi
printf '%s' "$fmt" | sed "s/%{http_code}/$code/; s/%{[a-z_]*}/0.1/g; s/\\\\n\$//"
printf '\n'
if [ "$rc" -ne 0 ]; then echo "curl: ($rc) Connection timed out" >&2; fi
exit "$rc"
'''


@pytest.mark.parametrize("curl_rc", [0, 28], ids=["answered", "failed"])
def test_w7_the_probe_writes_one_row_per_request(tmp_path, curl_rc):
    workflow = load_workflow("snap-build.yml")
    step = find_step(workflow, "build", "Probe the Snap Store")
    bindir = tmp_path / "bin"
    write_fake_commands(bindir, {"curl": _FAKE_CURL,
                                 "snap": "#!/bin/sh\necho fake snap\n",
                                 "sleep": "#!/bin/sh\nexit 0\n"})
    summary = tmp_path / "summary.md"
    proc = run_bash_script(step["run"], bash_flags(workflow, "build", step),
                           tmp_path=tmp_path, cwd=tmp_path, bindir=bindir,
                           env={"GITHUB_STEP_SUMMARY": str(summary),
                                "FAKE_CURL_RC": str(curl_rc)})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = [line for line in summary.read_text(encoding="utf-8").splitlines()
            if re.match(r"\| [0-9] \|", line)]
    if curl_rc:
        assert rows == [f"| {n} | curl-exit-28 | | | | | |" for n in range(1, 6)]
    else:
        assert rows == [f"| {n} | 200 | 0.1 | 0.1 | 0.1 | 0.1 | 0.1 |" for n in range(1, 6)]
