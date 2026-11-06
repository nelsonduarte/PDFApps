"""Replace the running one-file binary with the one in a release tarball.

No Qt in here, so all of it can be tested headless. The update has two
halves because they need different threads. :func:`install_new_binary`
blocks for seconds (extraction, then the ``--version`` probe), so the dialog
in ``app/updater.py`` runs it off the GUI thread. :func:`restart_into` runs
the ``before_exec`` callback the window hands in, which pumps the GUI event
loop, so it stays on the GUI thread. Either may raise :class:`UpdateError`,
for the dialog to show.

The order of the steps is what keeps a failed update from costing the user
their copy of PDFApps. Everything that can be refused is refused while the
installed binary is still untouched, and the backup outlives the swap,
because only ``os.execve`` can say whether the new binary starts. The new
process deletes it once its window is up (:func:`discard_backup_after_update`).
"""

from __future__ import annotations

import contextlib
import dataclasses
import glob
import gzip
import logging
import os
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import zlib
from collections.abc import Callable, MutableMapping

from app._font_subset import WORKER_FLAG
from app._subprocess_env import is_bootloader_var, system_tool_env

_log = logging.getLogger("updater")

TARBALL_SUFFIX = ".tar.gz"
# The one member build.yml packs: tar -czf ... -C dist PDFApps
_BINARY_MEMBER = "PDFApps"
_BACKUP_SUFFIX = ".pdfapps-backup"
# Created next to a backup whose restore failed. The user was shown that
# backup's path as the copy to recover, so nothing may delete it any more.
_RESTORE_FAILED_SUFFIX = ".restore-failed"
# How the process that execve starts learns which backup is now obsolete.
BACKUP_ENV = "PDFAPPS_UPDATE_BACKUP"

_ELF_MAGIC = b"\x7fELF"
# Measured about 1.7 s for the real one-file build on Ubuntu 26.04; the
# margin is for slow disks, and the GUI thread is not waiting on it.
_PROBE_TIMEOUT = 60.0
# After the kill: the group dies within milliseconds, so this only bounds
# the wait for a descendant that escaped it.
_KILL_GRACE = 2.0
# Read at call time, so a test can point it at a fake tree.
_PROC = "/proc"


class UpdateError(Exception):
    """The update did not happen. The message is translated, for the user."""


class RestoreFailed(UpdateError):
    """Neither binary could be put in place; *backup* is the copy to keep."""

    def __init__(self, message: str, backup: str):
        super().__init__(message)
        self.backup = backup


class UpdateBlocked(UpdateError):
    """The restart would cost the user work, so the update does not go on.

    Raised by a ``before_exec`` callback (or the prompt before the
    download); :func:`restart_into` puts the old binary back and passes
    it on with its own message, which says what to do.
    """


@dataclasses.dataclass(frozen=True)
class InstalledUpdate:
    """The new binary is at *current*; *backup* holds the one it replaced."""

    current: str
    backup: str


def _t(key: str, **kwargs) -> str:
    # Deferred like in pdf_io: nothing else in this module needs app.i18n.
    from app.i18n import t
    return t(key, **kwargs)


def _bad_archive(detail: str) -> UpdateError:
    _log.warning("refused update archive: %s", detail)
    return UpdateError(_t("update.error.bad_archive"))


def _probe_failed(detail: str) -> UpdateError:
    _log.warning("new binary failed its --version probe: %s", detail)
    return UpdateError(_t("update.error.probe_failed", error=detail))


def _probe_wrong_version(answer: str, expected: str) -> UpdateError:
    # It did start: "did not start" would send the user looking for a
    # problem with their system that is not there.
    _log.warning("new binary answered %r to --version, expected %s",
                 answer, expected)
    return UpdateError(_t("update.error.probe_wrong_version",
                          expected=expected, error=answer))


def _binary_member(tar: tarfile.TarFile) -> tarfile.TarInfo:
    """The only member the archive may hold, after checking all of them.

    The exact name rules out ``..`` and absolute paths, and ``isreg`` rules
    out a symlink or hardlink called ``PDFApps``.
    """
    members = tar.getmembers()
    for member in members:
        if member.name != _BINARY_MEMBER:
            raise _bad_archive(f"unexpected member {member.name!r}")
        if not member.isreg():
            raise _bad_archive(f"{member.name!r} is not a regular file")
    if len(members) != 1:
        raise _bad_archive(f"{len(members)} members instead of one")
    return members[0]


def _check_elf(path: str) -> None:
    """Refuse anything but an ELF executable, such as an archive."""
    with open(path, "rb") as f:
        head = f.read(4)
    if head != _ELF_MAGIC:
        raise _bad_archive(f"member starts with {head!r}, not an executable")


def _inherited_mode(current: str) -> int:
    """The installed binary's permissions, plus what its owner needs to run it.

    Forcing 0755 used to open a binary installed as 0700 to every user.
    """
    return stat.S_IMODE(os.stat(current).st_mode) & 0o777 | 0o700


def _stage_new_binary(tarball: str, current: str) -> str:
    """Extract the new binary next to *current* and return its path.

    Same directory, so the swap can be one atomic rename. It goes through
    ``extractfile`` under a name of our choosing, so nothing in the archive
    decides where bytes land.
    """
    # No leading dot in any of these prefixes (staged, probe, restore). Not
    # because of the snap, where is_system_install() keeps the updater from
    # running at all: the rule is for the whole of app/. The snap home
    # interface denies dotfiles at the top of $HOME, so
    # tests/test_no_hidden_temp_next_to_output.py fails on any tempfile
    # prefix that starts with a dot, whatever code it is in. Not
    # "PDFApps_update_" either, the downloaded tarball's prefix: with the
    # binary kept in the temp dir, its staged copy would be named like a
    # download.
    fd, staged = tempfile.mkstemp(prefix="pdfapps_staged_",
                                  dir=os.path.dirname(current))
    try:
        with os.fdopen(fd, "wb") as out:
            try:
                with gzip.open(tarball, "rb") as gz, \
                        tarfile.open(fileobj=gz, mode="r:") as tar:
                    source = tar.extractfile(_binary_member(tar))
                    if source is None:
                        raise _bad_archive("the member has no data")
                    shutil.copyfileobj(source, out)
                    # gzip checks its CRC only at the end of the stream,
                    # which tarfile never reads: without this, a damaged
                    # stream inflated to a damaged binary unnoticed.
                    while gz.read(1 << 20):
                        pass
            # BadGzipFile is an OSError: caught here, before the caller
            # takes it for a failure to write.
            except (tarfile.TarError, EOFError, zlib.error,
                    gzip.BadGzipFile) as exc:
                raise _bad_archive(str(exc)) from exc
            # On disk before the rename publishes it: after a power cut the
            # installed name must not point at data that was never written.
            out.flush()
            os.fsync(out.fileno())
        _check_elf(staged)
        os.chmod(staged, _inherited_mode(current))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(staged)
        raise
    return staged


def _kill_process_group(proc: subprocess.Popen) -> None:
    # The one-file bootloader forks the Python process, so killing only
    # proc would leave that child running and holding its extraction.
    if sys.platform == "win32":
        proc.kill()
    else:
        # start_new_session made proc the leader of its own group.
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)


def _reap_after_kill(proc: subprocess.Popen) -> None:
    """Collect *proc* after the kill without waiting on anyone else.

    ``communicate`` reads until every holder of the pipes closes them, and
    a descendant that left the process group (``setsid``) is not killed
    with it: a probe with a 1 s timeout came back after 8.3 s, as long as
    such a descendant lived (measured), and one that never exits would
    hold the dialog forever.
    """
    try:
        proc.communicate(timeout=_KILL_GRACE)
    except subprocess.TimeoutExpired:
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                with contextlib.suppress(OSError):
                    pipe.close()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=_KILL_GRACE)


def _probe_version(staged: str, expected_version: str, *,
                   timeout: float = _PROBE_TIMEOUT) -> None:
    """Run ``staged --version`` and refuse it unless it answers *expected_version*.

    It runs before anything is replaced, so a binary that cannot start here
    costs nothing. It catches a truncated or foreign ELF, a library the
    bootloader needs and this system lacks, and a temp dir that is noexec
    or full, since the one-file build extracts itself there before Python
    starts. Loading pdfapps.py imports Qt, pypdf, PyMuPDF and app.window,
    so their libraries are loaded too. What ``--version`` does NOT reach
    is anything that needs a ``QApplication``, such as the platform plugin
    (xcb): argparse exits before one is created. A binary that dies only
    there passes this probe and fails in ``execve``'s new process, after
    the swap; that risk is accepted, and the backup kept until the new
    window is up is what covers it.

    The environment is the one :func:`restart_into` launches with. Without
    it the new bootloader finds the old one's variables and fails with
    "Security validation failure", a false negative (measured).
    """
    version = expected_version.removeprefix("v")
    # Its own TMPDIR, in the temp dir the real launch extracts to (same
    # filesystem, so noexec and free space are tested), and removed
    # afterwards: a killed probe leaves its ~200 MB extraction behind.
    scratch = tempfile.mkdtemp(prefix="pdfapps_probe_")
    try:
        env = _fresh_launch_environ()
        env["TMPDIR"] = scratch
        try:
            proc = subprocess.Popen(
                [staged, "--version"], env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True,
            )
        except OSError as exc:
            raise _probe_failed(str(exc)) from exc
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_group(proc)
            _reap_after_kill(proc)
            raise _probe_failed(f"no answer after {timeout:g} s") from None
        answer = out.decode("utf-8", "replace")
        if proc.returncode != 0:
            tail = err.decode("utf-8", "replace").strip()[-300:]
            raise _probe_failed(f"exit status {proc.returncode}: {tail}")
        if version not in answer.split():
            raise _probe_wrong_version(answer.strip()[:100], version)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _backup_path_pattern(current: str) -> str:
    return os.path.join(
        tempfile.gettempdir(),
        glob.escape(os.path.basename(current)) + ".*" + _BACKUP_SUFFIX,
    )


def _owned_regular_file(path: str) -> bool:
    """A regular file, not a link, owned by this user.

    The temp dir may be shared, and anyone can create names there that
    match our pattern.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    getuid = getattr(os, "getuid", None)
    return getuid is None or st.st_uid == getuid()


def _is_backup_of(path: str, current: str) -> bool:
    folder, name = os.path.split(path)
    prefix = os.path.basename(current) + "."
    return (
        os.path.normcase(os.path.realpath(folder))
        == os.path.normcase(os.path.realpath(tempfile.gettempdir()))
        and name.startswith(prefix)
        and name.endswith(_BACKUP_SUFFIX)
        and len(name) > len(prefix) + len(_BACKUP_SUFFIX)
        and _owned_regular_file(path)
    )


def _restore_failed_pending(current: str) -> bool:
    """Whether a backup the user was told to recover from still exists."""
    for marker in glob.glob(_backup_path_pattern(current) + _RESTORE_FAILED_SUFFIX):
        backup = marker[:-len(_RESTORE_FAILED_SUFFIX)]
        if _owned_regular_file(marker) and os.path.lexists(backup):
            return True
    return False


def _discard_stale_backups(current: str, keep: str) -> None:
    """Remove the backups earlier updates left behind, all but *keep*.

    Normally the process an update starts deletes its own backup
    (:func:`discard_backup_after_update`); this catches the ones it could
    not, such as when that process crashed first. Nothing is removed while
    a failed restore is pending: the user was told where that copy is.
    """
    if _restore_failed_pending(current):
        _log.warning("a failed restore is pending, keeping every backup")
        return
    keep = os.path.normcase(os.path.abspath(keep))
    for path in glob.glob(_backup_path_pattern(current)):
        if os.path.normcase(os.path.abspath(path)) == keep:
            continue
        if _is_backup_of(path, current):
            with contextlib.suppress(OSError):
                os.unlink(path)


def _make_backup(current: str) -> str:
    # Place the backup in the system temp dir rather than next to the
    # binary. On OneDrive-installed copies the previous "<exe>.bak"
    # neighbour file became visible to the user's sync history and was
    # uploaded over wifi every update. tempfile.gettempdir() lives
    # outside OneDrive and is auto-cleaned by the OS.
    #
    # A copy, not a move: the temp dir is frequently on another volume
    # than the binary, where a move is copy + delete anyway, and this way
    # the installed binary never stops existing during the update.
    fd, backup = tempfile.mkstemp(
        suffix=_BACKUP_SUFFIX, prefix=os.path.basename(current) + ".")
    os.close(fd)
    try:
        shutil.copy2(current, backup)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(backup)
        raise
    return backup


def _restore_backup(backup: str, current: str) -> None:
    fd, staged = tempfile.mkstemp(
        prefix="pdfapps_restore_", dir=os.path.dirname(current))
    os.close(fd)
    try:
        shutil.copy2(backup, staged)
        os.replace(staged, current)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(staged)
        raise
    with contextlib.suppress(OSError):
        os.unlink(backup)


def _mark_restore_failed(backup: str) -> None:
    # Empty, so it still fits when the failure was a full disk. O_EXCL and
    # O_NOFOLLOW: the temp dir may be shared, never write through a link.
    # O_NONBLOCK as well: this runs on the GUI thread, and opening a FIFO
    # planted under this name for writing waits for a reader, which froze
    # the app for as long as nobody opened it (measured without O_EXCL).
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        os.close(os.open(backup + _RESTORE_FAILED_SUFFIX, flags, 0o600))
    except OSError as exc:
        _log.error("could not protect the backup %s: %s", backup, exc)


def _fresh_launch_environ() -> dict[str, str]:
    """``os.environ`` as the new binary needs it to start from scratch.

    Measured with a minimal --onefile build: with ``_PYI_*`` and
    ``_MEIPASS2`` kept, the new binary takes itself for the child phase of
    the old one and runs from the old ``_MEIPASS``, so the same PID shows the
    old bundle and files added by the new version are invisible. The sweep
    has to cover both prefixes together: clearing only some of these is
    worse than clearing none (see ``_restart_app`` in app/window.py).

    The bundle also leaves ``LD_LIBRARY_PATH`` pointing at the old extraction
    directory, and the old bootloader process stays alive after ``execve``,
    keeping that directory on disk. Left there, the new bootloader records it
    as the value from before launch, and ``system_tool_env`` would hand it to
    Ghostscript in the new process: the failure of v1.15.1 again.
    """
    env = system_tool_env()
    if env is None:
        env = dict(os.environ)
    return {k: v for k, v in env.items() if not is_bootloader_var(k)}


def _parent_pid(proc: str, pid: int) -> int | None:
    try:
        with open(os.path.join(proc, str(pid), "stat"), "rb") as f:
            data = f.read()
        # The command name, in parentheses, may itself hold ") ".
        return int(data.rsplit(b")", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        return None


def _lineage(proc: str, pid: int | None) -> set[int]:
    """*pid* and its ancestors."""
    seen: set[int] = set()
    while pid and pid not in seen:
        seen.add(pid)
        pid = _parent_pid(proc, pid)
    return seen


def _descendants(parents: dict[int, int], pid: int) -> set[int]:
    """The processes below *pid* in a ``{pid: ppid}`` map, not *pid* itself."""
    children: dict[int, list[int]] = {}
    for child, parent in parents.items():
        children.setdefault(parent, []).append(child)
    found: set[int] = set()
    todo = [pid]
    while todo:
        for child in children.get(todo.pop(), ()):
            if child not in found and child != pid:
                found.add(child)
                todo.append(child)
    return found


def _is_subset_child(proc: str, pid: int) -> bool:
    """Whether *pid* is the font-subset child of Compress.

    pdfapps.py takes that role when the first argument is the flag, so
    this asks the same of the command line. The one-file bootloader forks
    its Python process with the same arguments, so both answer yes.
    """
    try:
        with open(os.path.join(proc, str(pid), "cmdline"), "rb") as f:
            args = f.read().split(b"\0")
    except OSError:
        return False
    return args[1:2] == [WORKER_FLAG.encode()]


def _instances_of(current: str, *, proc: str | None = None,
                  own_pid: int | None = None) -> list[int]:
    """Processes of this user, other than this one, that run *current*.

    A one-file build keeps reading its modules from the path of its binary
    for as long as it runs. Replacing that file under another instance
    made its next import fail with ``zlib.error`` (measured in WSL with two
    instances of one binary). " (deleted)" is an instance that started
    before an earlier swap and still reads from the path.

    Ancestors are this process, not others: the bootloader that forked
    it and, after an earlier update in this session, the old bootloader
    that ``execve`` left waiting. So is the font-subset child of Compress,
    which runs ``sys.executable`` with a flag: taken for another window, it
    hid the "task running" message behind "open in another window"
    (measured). Other descendants are not: a window started below this one,
    through a shell that is still alive, is another instance, and when all
    descendants were left out it was not counted and its imports broke after
    the swap (measured). Fails open: where ``/proc`` cannot be read (not
    Linux, ``hidepid``), nobody is found and the update goes on as it did
    before this check.
    """
    proc = _PROC if proc is None else proc
    own_pid = os.getpid() if own_pid is None else own_pid
    try:
        entries = os.listdir(proc)
    except OSError:
        return []
    mine = _lineage(proc, own_pid)
    targets = {current, current + " (deleted)"}
    getuid = getattr(os, "getuid", None)
    parents: dict[int, int] = {}
    found = []
    for name in entries:
        if not (name.isascii() and name.isdigit()):
            continue
        pid = int(name)
        # Of every process, other users' too: the chain down from this
        # one may pass through any of them.
        ppid = _parent_pid(proc, pid)
        if ppid is not None:
            parents[pid] = ppid
        if pid in mine:
            continue
        entry = os.path.join(proc, name)
        try:
            if getuid is not None and os.stat(entry).st_uid != getuid():
                continue
            exe = os.readlink(os.path.join(entry, "exe"))
        except OSError:
            continue
        if exe in targets:
            found.append(pid)
    mine |= {pid for pid in _descendants(parents, own_pid)
             if _is_subset_child(proc, pid)}
    return sorted(pid for pid in found if pid not in mine)


def _refuse_if_shared(current: str) -> None:
    others = _instances_of(current)
    if others:
        _log.warning("not replacing %s: it also runs as pid %s",
                     current, others)
        raise UpdateError(_t("update.error.other_instance"))


def refuse_if_running_elsewhere() -> None:
    """Raise :class:`UpdateError` while another PDFApps runs this binary.

    For the dialog, before anything is downloaded; :func:`install_new_binary`
    asks again right before the swap. A source run has nothing to replace
    (and its ``sys.executable`` is the interpreter, which other programs
    run too), so it is not asked here.
    """
    if getattr(sys, "frozen", False):
        _refuse_if_shared(os.path.realpath(sys.executable))


def install_new_binary(downloaded: str, asset_name: str,
                       expected_version: str) -> InstalledUpdate:
    """Put the binary from the verified tarball *downloaded* in place.

    Blocks for seconds; call it off the GUI thread. *asset_name* is the
    release asset's own name, because the path of the download proves
    nothing: its temp name once ended in ``.gz``, the check for ``.tar.gz``
    was false, and the tarball itself was copied over the executable
    (v1.12.2 to v1.15.2). *expected_version* is the release tag, which the
    new binary must report.

    Raises :class:`UpdateError` when refused or failed; the installed binary
    is then the one that was there before. *downloaded* is removed either way.
    """
    try:
        # A source run in a Python under $HOME (pyenv, uv) is not caught by
        # is_system_install(), and there sys.executable is the interpreter.
        if not getattr(sys, "frozen", False):
            raise UpdateError(_t("update.error.not_frozen"))
        # macOS updates through the dmg in app/updater.py; this only
        # knows how to replace an ELF.
        if sys.platform == "darwin" or not asset_name.endswith(TARBALL_SUFFIX):
            raise _bad_archive(f"unsupported asset {asset_name!r} on {sys.platform}")
        current = os.path.realpath(sys.executable)
        staged: str | None = None
        backup: str | None = None
        try:
            staged = _stage_new_binary(downloaded, current)
            _probe_version(staged, expected_version)
            backup = _make_backup(current)
            # Only once the new backup exists: with a full temp dir,
            # _make_backup fails, and the old backup was the only copy.
            _discard_stale_backups(current, keep=backup)
            # Again, after seconds of extraction and probe: an instance
            # started meanwhile would be cut off just the same.
            _refuse_if_shared(current)
            os.replace(staged, current)
            return InstalledUpdate(current, backup)
        except BaseException as exc:
            for leftover in (staged, backup):
                if leftover is not None:
                    with contextlib.suppress(OSError):
                        os.unlink(leftover)
            if isinstance(exc, OSError):
                raise UpdateError(
                    _t("update.error.apply_failed", error=exc)) from exc
            raise
    finally:
        # Drop the ~100 MB installer tempfile on every exit — success
        # AND failure (R5/F3). Previously os.remove(downloaded) only ran
        # on the success path, so a failed apply left the artefact in
        # /tmp until the OS reboot cleaned it up.
        with contextlib.suppress(Exception):
            if os.path.isfile(downloaded):
                os.unlink(downloaded)


def restart_into(update: InstalledUpdate,
                 before_exec: Callable[[], None] | None = None) -> None:
    """Become the new binary, or put the old one back and raise.

    *before_exec* runs first, on the caller's thread: ``execve`` ends the
    process without ``closeEvent``, so the window does its teardown there,
    or raises :class:`UpdateBlocked` when the restart would cost the user
    work. Nothing is cleared here (passwords stay, for instance), because
    if ``execve`` fails this process goes on running with them.

    Never returns on success. On failure raises :class:`UpdateError` (the
    :class:`UpdateBlocked` itself, when that was the cause), or
    :class:`RestoreFailed` when the old binary could not be put back.
    """
    env = _fresh_launch_environ()
    env[BACKUP_ENV] = update.backup
    try:
        if before_exec is not None:
            before_exec()
        os.execve(update.current, sys.argv, env)
    # Not only OSError: execve raises ValueError on an empty argv, and any
    # failure here must leave the user with a binary that starts.
    except Exception as exc:
        try:
            _restore_backup(update.backup, update.current)
        except OSError as restore_exc:
            _mark_restore_failed(update.backup)
            raise RestoreFailed(_t(
                "update.error.restore_failed",
                path=update.backup, error=restore_exc,
            ), update.backup) from exc
        if isinstance(exc, UpdateBlocked):
            # Its message says what to do; "could not be started" is false.
            raise
        raise UpdateError(_t("update.error.restart_failed", error=exc)) from exc


def discard_backup_after_update(
        environ: MutableMapping[str, str] | None = None) -> None:
    """Delete the backup the previous process kept for its ``execve``.

    Called once the new version's window is shown, which is what the
    backup was kept for. Only the one file named in :data:`BACKUP_ENV`,
    and only if it is a backup of this binary in this temp dir, owned by
    this user and not marked by a failed restore. The variable is removed
    in any case, so that no child process inherits it.
    """
    env = os.environ if environ is None else environ
    backup = env.pop(BACKUP_ENV, None)
    if not backup or not getattr(sys, "frozen", False):
        return
    current = os.path.realpath(sys.executable)
    if not _is_backup_of(backup, current):
        _log.warning("not deleting %r: not a backup of %s", backup, current)
        return
    if os.path.lexists(backup + _RESTORE_FAILED_SUFFIX):
        return
    try:
        os.unlink(backup)
    except OSError as exc:
        _log.warning("could not delete the update backup %s: %s", backup, exc)
