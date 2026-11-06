"""Run PyMuPDF's font subsetter in a child process.

Helper for ``app.utils._compress_pdf``. This module imports no Qt and no
``app.*``, so it can be tested headless.

``Document.subset_fonts()`` can crash natively. Measured on Windows with
PyMuPDF 1.28.2: access violation (0xC0000005) in 30 runs out of 30 on one
public PDF, 0 out of 30 on Linux, and nothing in the file predicts it. A
``try/except`` cannot catch that, so in the app's own process the whole
application died and left the temporary of Ghostscript's pass in %TEMP%.
Here only the child dies and the caller carries on without subsetting.

The parent side is :func:`run_subset`. The child side is :func:`worker_main`,
reached from the top of ``pdfapps.py`` through :data:`WORKER_FLAG`, before
that file imports PySide6.

What the child loads depends on how it runs. From source: no Qt and none of
the app beyond this module (167 modules, measured). In the one-file bundle it
does load some Qt, 17 ``PySide6.*``/``shiboken6`` modules of 194 (measured):
PyInstaller's runtime hook ``pyi_rth_pyside6`` runs before ``pdfapps.py`` and
imports ``PySide6.QtCore`` to embed a ``qt.conf``. There is no QApplication in
either case.

The child inherits the whole environment, on purpose. ``_PYI_*`` and
``_MEIPASS*`` are what tell the PyInstaller bootloader that this is another
process of the running application, which then reuses its extraction
directory instead of unpacking the whole one-file bundle again, and the
Linux bundle needs its ``LD_LIBRARY_PATH``. So do not sweep them as
``_restart_app`` does (that one starts a new application), and do not use
``_subprocess_env.system_tool_env`` (that one is for system binaries).

There is no ``-I`` in the source command either: the snap finds its
libraries through ``PYTHONPATH``.

Known limit, accepted for 1.15.3 and described in SECURITY.md: the caller
gives the child a path in the folder that ``_compress_pdf`` makes with
``mkdtemp`` for each call, ``pdfapps-compress-*`` in the system temporary
folder, where every other temporary of the pipeline lives too. For an
encrypted source what the child writes there is a decrypted copy. The
folder is removed when ``_compress_pdf`` returns or raises, unless
something still uses it (then it stays, with a warning in the log), and
after an abrupt death of the application nothing removes it, not even the
next start. It still keeps other users out: mode 0700 on Linux, and on Windows
an ACL that lets in only the owner, SYSTEM and Administrators (both
measured, Python 3.14; macOS not measured). What is lost there is the
deletion, not the access control. Removing such folders at startup is left
for a later correction.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time

_log = logging.getLogger(__name__)

# Also spelled out at the top of pdfapps.py, which must test it before it
# can import anything from app. tests/test_font_subset.py keeps both equal.
WORKER_FLAG = "--internal-subset-fonts"

# Bound on one child process of the compress pipeline: this subset, and
# Ghostscript in pass A (app/utils.py reads it from here).
CHILD_TIMEOUT_S = 120

_POLL_S = 0.2
_KILL_WAIT_S = 5

SUBSET_OK = "ok"
SUBSET_FAILED = "failed"
SUBSET_CANCELLED = "cancelled"

_RC_FAILED = 2
_RC_PARENT_GONE = 3

_PR_SET_PDEATHSIG = 1
_PARENT_WATCH_S = 1.0
# After the parent's own deadline, so it only ever fires for an orphan.
_ALARM_MARGIN_S = 30


# ── Child side ───────────────────────────────────────────────────────────

def subset(src: str, dst: str, password: str | None = None) -> None:
    """Write *src* to *dst* with its fonts subset. Raises on any failure."""
    import pymupdf

    doc = pymupdf.open(src)
    try:
        if doc.needs_pass and not (password and doc.authenticate(password)):
            raise ValueError("the PDF did not open with the given password")
        doc.subset_fonts()
        # clean=False for the reason given at pass B's save: clean=True
        # rewrites content streams and duplicates overprinted glyphs.
        doc.save(dst, clean=False)
    finally:
        doc.close()


def _silence_crash_reporting() -> None:
    """Keep a native crash away from Windows Error Reporting.

    Measured with a real crash, launched as Explorer launches an app: 1.81 s
    with WerFault and events 1000 and 1001 in the log without this, 0.41 s
    and no WerFault with it. Git Bash hands its descendants error mode 3, so
    a measurement started from there never sees the WER path; such a test
    needs CREATE_DEFAULT_ERROR_MODE.
    """
    if sys.platform != "win32":
        return
    import ctypes
    # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
    ctypes.windll.kernel32.SetErrorMode(0x8003)


def _read_job_bytes() -> bytes:
    # Measured in the frozen child, on Windows and Linux: sys.stdin is a
    # TextIOWrapper over the pipe. None is what the windowed parent has, with
    # no stdin at all. The fallback is for a child that ever gets None too,
    # since the pipe would still be fd 0 and the job must not be lost.
    if sys.stdin is not None:
        return sys.stdin.buffer.read()
    with os.fdopen(0, "rb", closefd=False) as stream:
        return stream.read()


def _set_pdeathsig() -> bool:
    """Ask Linux to SIGKILL this process when its parent goes away."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(_PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0) == 0
    except (OSError, AttributeError, ValueError):
        return False


def _watch_parent(parent_pid: int) -> None:
    while True:
        time.sleep(_PARENT_WATCH_S)
        if os.getppid() != parent_pid:
            os._exit(_RC_PARENT_GONE)


def _tie_life_to_parent(parent_pid: int | None) -> None:
    """End this process when the parent dies (POSIX; Windows uses a Job).

    Without this, a parent killed while the child runs leaves the child
    holding the bundle's extraction directory.

    PR_SET_PDEATHSIG fires when the *thread* that forked dies, not the
    process. That thread is the one in run_subset, which stays blocked on
    this child for its whole life, so the two end together.

    macOS has no prctl, hence the thread polling getppid(). It is weaker:
    it needs the GIL, which a native subset_fonts() call may hold, so there
    the exit can come only when that call returns. For a call that never
    returns there is also an alarm: SIGALRM's default action ends the process
    in the kernel, with no Python involved. A disposition of SIG_IGN survives
    exec, so the default is set first or a parent ignoring it would disarm
    this. Both are also the fallback if prctl is refused.

    *parent_pid* None is only for scripts/smoke_font_subset_child.py, which
    starts the bundle as a new application: the bootloader then stands
    between it and the Python code, and nothing is left to tie to.
    """
    if sys.platform == "win32" or parent_pid is None:
        return
    if not _set_pdeathsig():
        threading.Thread(target=_watch_parent, args=(parent_pid,),
                         daemon=True).start()
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.alarm(CHILD_TIMEOUT_S + _ALARM_MARGIN_S)
    # Checked after arming: a parent that died before prctl ran never sends
    # the signal. The Popen caller is the direct parent in the one-file
    # bundle too: with the inherited _PYI_* variables the child's bootloader
    # does not fork again (measured on Linux).
    if os.getppid() != parent_pid:
        os._exit(_RC_PARENT_GONE)


def worker_main() -> None:
    """Child entry point. Never returns: rc 0 only after a complete save.

    os._exit on every path: an exception reaching the windowed bootloader
    opens its "Unhandled exception in script" dialog and blocks there.
    """
    try:
        _silence_crash_reporting()
        job = json.loads(_read_job_bytes().decode("ascii"))
        _tie_life_to_parent(job.get("parent_pid"))
        subset(job["src"], job["dst"], job.get("password"))
    except Exception:  # the rc is the only thing the parent can read
        os._exit(_RC_FAILED)
    except KeyboardInterrupt:
        os._exit(_RC_FAILED)
    except SystemExit:
        os._exit(_RC_FAILED)
    os._exit(0)


# ── Parent side ──────────────────────────────────────────────────────────

def child_command() -> list[str]:
    """Command that reaches worker_main.

    Never sys.argv[0]: it is relative to a working directory that may have
    changed, and in a bundle it can name a launcher.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, WORKER_FLAG]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [sys.executable, os.path.join(root, "pdfapps.py"), WORKER_FLAG]


def _no_window_flags() -> int:
    # The windowed bundle has no console to share. POSIX accepts only 0.
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def _create_job_for(proc: subprocess.Popen):
    """Put *proc* in a kill-on-close Job; return the handle, or None.

    The system closes the handle when this process dies, however it dies,
    and that kills the child. Without it, measured: about 15 s after the
    parent's death the orphan's bootloader opens a visible "Failed to
    remove temporary directory" dialog, and 24 MB of _MEI stay behind.

    The child is only assigned after it starts, which is safe because it
    blocks on stdin until run_subset writes the job. No failure here may
    cost the subset (nested Jobs can be refused), so any of them, ctypes'
    ArgumentError included, is only logged.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        import ctypes.wintypes as wintypes

        class _Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _Basic),
                        ("IoInfo", ctypes.c_uint64 * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        # A private WinDLL: argtypes set on the shared ctypes.windll object
        # would leak into every other user of kernel32 in the process.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p,
                                              wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE,
                                                      wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        extended_limit_information = 9
        if not (kernel32.SetInformationJobObject(
                    job, extended_limit_information,
                    ctypes.byref(info), ctypes.sizeof(info))
                and kernel32.AssignProcessToJobObject(
                    job, int(proc._handle))):  # type: ignore[attr-defined]
            error = ctypes.WinError(ctypes.get_last_error())
            kernel32.CloseHandle(job)
            raise error
        return job
    except Exception as exc:
        _log.warning("font subset child: no kill-on-close Job (%r); "
                     "carrying on without it", exc)
        return None


def _close_job(job) -> None:
    if job is None or sys.platform != "win32":
        return
    try:
        import ctypes
        import ctypes.wintypes as wintypes
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle(job)
    except Exception as exc:  # a leaked handle must not change the outcome
        _log.warning("font subset child: Job not closed (%r)", exc)


def _feed_stdin(stream, payload: bytes) -> None:
    # A failure means the child died before reading: its rc says what
    # happened. close() flushes too, so it can fail in the same way.
    for step in (lambda: stream.write(payload), stream.close):
        try:
            step()
        except (OSError, ValueError):
            pass  # run_subset learns the outcome from the child, not here


def _kill_and_wait(proc: subprocess.Popen) -> None:
    """Return only with the child gone, so its files can be deleted."""
    try:
        if proc.poll() is None:
            proc.kill()
    except OSError as exc:  # still waited for below; on Windows the Job helps
        _log.warning("font subset child: kill failed (%r)", exc)
    try:
        proc.wait(timeout=_KILL_WAIT_S)
    except subprocess.TimeoutExpired:
        _log.warning("font subset child: pid %s still alive %s s after kill",
                     proc.pid, _KILL_WAIT_S)


def _wait_for_child(proc: subprocess.Popen, should_cancel) -> str | None:
    """Return None when the child exits, or why it should be stopped."""
    deadline = time.monotonic() + CHILD_TIMEOUT_S
    while True:
        try:
            proc.wait(timeout=_POLL_S)
            return None
        except subprocess.TimeoutExpired:
            pass
        if should_cancel is not None and should_cancel():
            return SUBSET_CANCELLED
        if time.monotonic() > deadline:
            return "timeout"


def _is_good_output(path: str, expected_pages: int) -> bool:
    """Whether *path* is a whole, decrypted PDF with the expected pages.

    is_repaired matters: PyMuPDF rebuilds the xref of a truncated file and
    can report the full page count for it. A file the child has just saved
    never needs that, even when the source did.

    It has to be read last, because the repair is lazy and only happens when
    a damaged object is reached. Measured on a three-page PDF with one wrong
    xref offset at a time, 12 objects: after opening it catches 1 of them,
    after load_page on every page 8 (not the font or the content streams),
    after xref_object on every object all 12. The walk reads no stream: 0.18 s
    on 1527 pages and 20486 objects, 0.93 s at worst on a 71 MB, 660-page
    output.

    Reading each page's own object is for a /Kids entry that leads nowhere.
    load_page takes "9999 0 R" without complaint and gives a blank default
    page, and .xref then returns that number; only the read fails. Measured:
    on a /Page with inherited attributes, in a nested tree, in an object
    stream or with no /Type at all the read returns the dictionary, so none
    of those is refused. On a /Kids entry naming a free object or an integer
    it returns no dictionary. An empty dictionary is accepted, since MuPDF
    takes it for a blank page.
    """
    try:
        import pymupdf

        doc = pymupdf.open(path)
        try:
            if doc.needs_pass or doc.page_count != expected_pages:
                return False
            for number in range(expected_pages):
                page_xref = doc.load_page(number).xref
                if not doc.xref_object(page_xref,
                                       compressed=True).startswith("<<"):
                    return False
            for xref in range(1, doc.xref_length()):
                doc.xref_object(xref, compressed=True)
            return not doc.is_repaired
        finally:
            doc.close()
    except Exception:  # any failure to read it means the output is unusable
        return False


def run_subset(src: str, dst: str, password: str | None, expected_pages: int,
               should_cancel=None) -> str:
    """Subset *src* into *dst* in a child process.

    Returns SUBSET_OK, SUBSET_CANCELLED, or SUBSET_FAILED for a crash, a
    timeout, an unusable output or anything else going wrong here: no
    Exception leaves this function, so the caller can carry on without the
    subset. The caller owns *dst* and its directory, and deletes them: when
    this returns, the child is gone. *should_cancel* is polled every 0.2 s.

    The password travels through stdin, so that it is in neither the
    command line nor the environment, and it must stay out of the log.
    """
    try:
        return _run_child(src, dst, password, expected_pages, should_cancel)
    except Exception as exc:
        # The type only: the message of an error here could quote the job.
        _log.warning("font subset child: %s", type(exc).__name__)
        return SUBSET_FAILED


def _run_child(src: str, dst: str, password: str | None, expected_pages: int,
               should_cancel) -> str:
    payload = json.dumps({"src": src, "dst": dst, "password": password,
                          "parent_pid": os.getpid()}).encode("ascii")
    try:
        proc = subprocess.Popen(child_command(), stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=_no_window_flags())
    except (OSError, ValueError) as exc:
        _log.warning("font subset child: did not start (%r)", exc)
        return SUBSET_FAILED
    job = None
    feeder = None
    try:
        job = _create_job_for(proc)
        # From a thread: a job larger than the pipe buffer (4 KB on Windows)
        # would block here if the child never reads it, with no Cancel and no
        # timeout, and killing the child is what releases this thread.
        feeder = threading.Thread(target=_feed_stdin,
                                  args=(proc.stdin, payload), daemon=True)
        feeder.start()
        stopped_for = _wait_for_child(proc, should_cancel)
    finally:
        _kill_and_wait(proc)
        if feeder is not None and feeder.ident is not None:
            feeder.join(timeout=_KILL_WAIT_S)
        _close_job(job)

    rc = proc.returncode
    if stopped_for == SUBSET_CANCELLED:
        _log.info("font subset child: cancelled, rc=%s", rc)
        return SUBSET_CANCELLED
    if stopped_for is not None:
        _log.warning("font subset child: %s, rc=%s", stopped_for, rc)
        return SUBSET_FAILED
    if rc != 0:
        # A crash no longer reaches the Store's health reports, so this
        # line is the only record of it.
        _log.warning("font subset child: failed, rc=%s", rc)
        return SUBSET_FAILED
    if not _is_good_output(dst, expected_pages):
        _log.warning("font subset child: rc=0 but the output is unusable")
        return SUBSET_FAILED
    _log.info("font subset child: ok, rc=0")
    return SUBSET_OK
