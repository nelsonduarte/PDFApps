"""Helpers shared by ``tests/test_no_cwd_executables.py`` and
``tests/test_no_cwd_executables_installers.py``.

In both files no test may start a real program: an autouse fixture in
each runs ``launches_forbidden``. Its net is laid when each test starts,
so it does not cover what runs before: the module-scoped ``installer``
and ``uninstaller`` fixtures import those scripts first, and a program
started while a script is imported would be outside it.
"""

from __future__ import annotations

import asyncio.base_events
import asyncio.subprocess
import ctypes
import multiprocessing.process
import os
import re
import subprocess
import sys
import types
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def touch(path: Path) -> str:
    """An empty file at *path*, with its folders; its path as a string."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return str(path)


def which_answer(kind: str, tmp_path: Path, monkeypatch, stem: str) -> str:
    """What a fake ``shutil.which`` answers. Relative answers, and the one
    with a root but no drive, name a file that exists from the current
    folder, so only being relative refuses them. For those the current
    folder moves to *tmp_path*: the path without a drive resolves against
    the drive of the current folder, and the checkout and the temporary
    folder may sit on different drives (D: and C: on the Windows runner)."""
    if kind in ("relative", "dot_relative"):
        monkeypatch.chdir(tmp_path)
        touch(tmp_path / f"{stem}.EXE")
        name = f"{stem}.EXE"
        return name if kind == "relative" else os.path.join(".", name)
    if kind == "rooted_no_drive":
        monkeypatch.chdir(tmp_path)
        exe = touch(tmp_path / "abs" / f"{stem}.EXE")
        return os.path.splitdrive(exe)[1]
    return touch(tmp_path / "abs" / kind.replace("tesseract", stem))


class Spy:
    """Stands in for ``subprocess.run`` or ``subprocess.Popen`` and keeps
    the arguments of each call."""

    def __init__(self):
        self.calls: list[tuple[list, dict]] = []

    def __call__(self, args, *a, **kw):
        self.calls.append((list(args), kw))
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


_SPAWN_SUFFIXES = ("l", "le", "lp", "lpe", "v", "ve", "vp", "vpe")
_ASYNCIO_FUNCTIONS = ("create_subprocess_exec", "create_subprocess_shell")
# Every QProcess method that starts a program, static or not.
_QPROCESS_STARTS = ("start", "startDetached", "startCommand", "execute",
                    "open")
# The process functions of os. os takes them from a C module (nt or
# posix), which keeps its own reference: nt.startfile(...) bypasses a stub
# set on os, so both are replaced. fork too: after a fork the child would
# record a launch in its own copy of the record and go on running the
# session, while the parent passed.
_OS_LAUNCHERS = ("system", "popen", "startfile", "posix_spawn",
                 "posix_spawnp", "fork", "forkpty",
                 *(f"exec{s}" for s in _SPAWN_SUFFIXES),
                 *(f"spawn{s}" for s in _SPAWN_SUFFIXES))
# DLL functions that start a program, or hand a file or a URL to the
# program that opens it, by their exported names. Taken from the exports of
# the DLLs that hold them (Windows 11, glibc 2.43): the documented ones and
# the internal ones they call, as a test may reach either.
_DLL_LAUNCHERS = frozenset({
    # shell32
    "ShellExecuteW", "ShellExecuteA", "ShellExecuteExW", "ShellExecuteExA",
    "ShellExecuteEx", "RealShellExecuteW", "RealShellExecuteA",
    "RealShellExecuteExW", "RealShellExecuteExA", "WOWShellExecute",
    "ShellExec_RunDLL", "ShellExec_RunDLLA", "ShellExec_RunDLLW",
    "RunAsNewUser_RunDLLW", "SHCreateProcessAsUserW",
    "SHOpenFolderAndSelectItems",
    # kernel32, kernelbase, advapi32
    "CreateProcessW", "CreateProcessA", "CreateProcessInternalW",
    "CreateProcessInternalA", "NtVdm64CreateProcessInternalW", "WinExec",
    "LoadModule", "CreateProcessAsUserW", "CreateProcessAsUserA",
    "CreateProcessWithLogonW", "CreateProcessWithTokenW",
    # ntdll
    "NtCreateUserProcess", "ZwCreateUserProcess", "NtCreateProcess",
    "NtCreateProcessEx", "ZwCreateProcess", "ZwCreateProcessEx",
    "RtlCreateUserProcess", "RtlCreateUserProcessEx",
    # url, ieframe, shdocvw: a URL to the browser
    "FileProtocolHandler", "FileProtocolHandlerA", "OpenURL", "OpenURLA",
    "IELaunchURL",
    # The C runtimes (msvcrt, ucrtbase and its "_o_" copies, libc and its
    # internal aliases). wordexp runs the shell for a "$(...)" in its words;
    # daemon forks, as fork and clone do (see _OS_LAUNCHERS).
    "system", "_wsystem", "_o_system", "_o__wsystem", "__libc_system",
    "popen", "_popen", "_wpopen", "_o__popen", "_o__wpopen", "_IO_popen",
    "posix_spawn", "posix_spawnp", "pidfd_spawn", "pidfd_spawnp",
    "execveat", "fexecve", "wordexp", "fork", "vfork", "forkpty", "_Fork",
    "__fork", "__libc_fork", "__vfork", "clone", "__clone", "daemon",
})
# The C runtime's exec* and spawn*, with the "_", "_w" and "_o_" prefixes
# of msvcrt and ucrtbase.
_CRT_EXEC_SPAWN = re.compile(r"(?:_o_)?_?w?(?:exec|spawn)[lv]p?e?")


def _is_dll_launcher(name) -> bool:
    # ctypes takes a name as bytes too (dll[b"ShellExecuteW"]); an ordinal,
    # an int, is never one of these.
    if isinstance(name, bytes):
        name = name.decode("latin-1")
    return isinstance(name, str) and (
        name in _DLL_LAUNCHERS or _CRT_EXEC_SPAWN.fullmatch(name) is not None)


def _launchers() -> list[tuple[object, str, str]]:
    """(owner, attribute, label) of each launcher replaced by a stub."""
    found: list[tuple[object, str, str]] = []

    def add(owner, label, names):
        found.extend((owner, n, f"{label}.{n}") for n in names)

    add(subprocess, "subprocess", ("Popen", "run", "call", "check_call",
                                   "check_output", "getoutput",
                                   "getstatusoutput"))
    # startfile apart: missing off Windows, it is set in any case.
    add(os, "os", [n for n in _OS_LAUNCHERS if n != "startfile"])
    add(sys.modules[os.name], os.name, _OS_LAUNCHERS)
    # get() too: get(name).open(url) starts that browser.
    add(webbrowser, "webbrowser", ("open", "open_new", "open_new_tab", "get"))
    # Both modules hold the functions; the loop's methods catch a function
    # bound by "from asyncio import ..." before the test started.
    add(asyncio, "asyncio", _ASYNCIO_FUNCTIONS)
    add(asyncio.subprocess, "asyncio.subprocess", _ASYNCIO_FUNCTIONS)
    add(asyncio.base_events.BaseEventLoop, "BaseEventLoop",
        ("subprocess_exec", "subprocess_shell"))
    # Every start method and Pool goes through Process.start.
    add(multiprocessing.process.BaseProcess, "multiprocessing.BaseProcess",
        ("start",))
    if sys.platform == "win32":
        import _winapi
        # What subprocess and multiprocessing call in the end, looked up on
        # _winapi at each call: it also catches a Popen bound by "from
        # subprocess import Popen" before the test, in any module.
        add(_winapi, "_winapi", ("CreateProcess",))
        # The DLLs themselves stay real (windows_path needs kernel32); only
        # these functions are replaced.
        add(ctypes.windll.shell32, "shell32",
            ("ShellExecuteW", "ShellExecuteA", "ShellExecuteExW",
             "ShellExecuteExA"))
        add(ctypes.windll.kernel32, "kernel32",
            ("CreateProcessW", "CreateProcessA", "WinExec"))
        add(ctypes.windll.advapi32, "advapi32",
            ("CreateProcessAsUserW", "CreateProcessAsUserA",
             "CreateProcessWithLogonW", "CreateProcessWithTokenW"))
    else:
        import _posixsubprocess
        # The same role off Windows: subprocess's fork and exec, and
        # multiprocessing's helper processes. subprocess (since Python 3.11)
        # calls its own name for it, bound when it was imported ("from
        # _posixsubprocess import fork_exec as _fork_exec"), so that name is
        # replaced too: without it, a Popen bound by "from subprocess import
        # Popen" before the test, outside the modules of PDFApps, started its
        # program whenever subprocess did not take its os.posix_spawn route
        # (with cwd=, start_new_session=True and the like).
        add(_posixsubprocess, "_posixsubprocess", ("fork_exec",))
        add(subprocess, "subprocess", ("_fork_exec",))
    # The functions already fetched from a DLL that ctypes' loaders keep
    # (windll.Shell32, cdll.msvcrt...): they no longer go through the
    # lookup that _guard_dll_lookups replaces.
    for loader in ("cdll", "pydll", "windll", "oledll"):
        for attr, dll in list(vars(getattr(ctypes, loader, object)).items()):
            if isinstance(dll, ctypes.CDLL):
                add(dll, f"ctypes.{loader}.{attr}",
                    [n for n in vars(dll) if _is_dll_launcher(n)])
    seen: set[tuple[int, str]] = set()
    unique = []
    for o, n, label in found:
        if hasattr(o, n) and (id(o), n) not in seen:
            seen.add((id(o), n))
            unique.append((o, n, label))
    return unique


# Launches through a stub whose test had already ended (an object kept
# past its test, such as an instance of the QProcess subclass, still holds
# the stubs). The program does not start, as the stub raises, but no one
# checks that test's record any more: the next test of the two files
# reports them.
_AFTER_THEIR_TEST: list[tuple[str, tuple]] = []


def take_launches_after_their_test() -> list[tuple[str, tuple]]:
    """The launches recorded after their test had ended, emptied."""
    late = list(_AFTER_THEIR_TEST)
    _AFTER_THEIR_TEST.clear()
    return late


def forbid_real_launches(monkeypatch, test=None) -> list[tuple[str, tuple]]:
    """Make the ways a test could start a real program, listed below,
    fail instead, and keep a record of each attempt. Once ``test.ended``
    is true, attempts go to the launches after their test instead.

    The tests spy on the one function the code uses today; a regression
    to another one (``os.startfile``, ``os.system``) would start the real
    program before any assert failed, as happened once with the Explorer.
    Replaced, all through *monkeypatch*: the launch functions of
    ``subprocess``, ``os`` (``fork`` and ``forkpty`` included) and of the
    C module ``os`` takes them from (``nt`` or ``posix``), ``webbrowser``,
    ``asyncio`` and the asyncio event loop; ``multiprocessing``'s
    ``Process.start``; Qt's ``QDesktopServices.openUrl``; the name
    ``QProcess`` of ``PySide6.QtCore`` (not the class it names), by a
    subclass whose every way of starting a program is a stub; on Windows
    ``_winapi.CreateProcess``, off Windows ``_posixsubprocess.fork_exec``
    and ``subprocess``'s own name for it, ``subprocess._fork_exec``; the DLL
    functions that start a program, or hand a file or a URL to the program
    that opens it, named in ``_DLL_LAUNCHERS`` and ``_CRT_EXEC_SPAWN``
    (shell32's ``ShellExecute*``, kernel32's ``CreateProcess*``,
    ``WinExec`` and ``LoadModule``, advapi32's ``CreateProcess*``, ntdll's
    ``*CreateUserProcess``, the C runtime's ``system``, ``popen``,
    ``exec*``, ``spawn*``, ``posix_spawn*``, ``fork`` and the like), on the
    DLLs ctypes' loaders keep and through any lookup by name, ``str`` or
    ``bytes``, during the test (``ctypes.WinDLL("shell32").ShellExecuteW``,
    ``shell32["WinExec"]``, ``shell32[b"WinExec"]``); and, in the modules
    of PDFApps (``app``, the three scripts at the root, by their real
    paths), each name bound to one of those launchers before the test
    (``from os import startfile``, ``from PySide6.QtCore import
    QProcess``, ``open_url = QDesktopServices.openUrl``). Each stub raises
    ``AssertionError``, but production code may swallow it
    (``_register_file_association_win`` catches every ``Exception``), so
    the caller must also check that the record stayed empty. A test's own
    spy, set later on the same ``monkeypatch``, takes precedence. Laid
    when no other net is, it first checks that none of these is still a
    stub, which only a net not undone in full would leave.

    Outside the net, and this list is not complete: whatever runs before
    the test (see the module's docstring); a launcher bound before the
    test outside the modules of PDFApps (a library's ``from os import
    system``), or kept in a closure, a default argument, an object's
    attribute or a ``functools.partial``; a subclass of ``QProcess`` made
    before the test, in any module (those of PDFApps included), and an
    instance of ``QProcess`` made before the test: the net replaces the
    name, not the class, so both still reach Qt's own start methods
    (measured with a marker program on Windows and on WSL); a DLL function
    reached without a lookup by name (a ctypes prototype called with
    ``(name, dll)``, an address from ``GetProcAddress``, an ordinal), or
    fetched before the test from a DLL object that ctypes' loaders do not
    keep; a DLL function that starts a program under a name not in the
    list, of which the DLLs named above and others export more (zipfldr's
    ``RouteTheCall``, which started a marker program past the net on
    Windows; the ``*_RunDLL`` entry points of shell32 other than
    ``ShellExec_RunDLL`` and ``RunAsNewUser_RunDLLW``; hlink's navigation;
    remote execution such as libc's ``rexec`` and ``rcmd``), and a system
    call made by number (libc's ``syscall``); other extension modules that
    start programs (pywin32's ``win32api.ShellExecute``, COM's
    ``Shell.Application``); and a stub called after its test ended, by an
    object kept past it: the program does not start, as the stub raises,
    and the next test of the two files reports it, but after the last one
    nothing does.
    """
    launched: list[tuple[str, tuple]] = []

    def stub_for(name):
        def stub(*args, **kwargs):
            ended = test is not None and test.ended
            (_AFTER_THEIR_TEST if ended else launched).append((name, args))
            raise AssertionError(f"a test tried to start a program: "
                                 f"{name}{args!r}")
        stub.forbids_real_launch = True
        return stub

    from PySide6 import QtCore, QtGui

    outermost = not _net_laid()
    # Before _guard_dll_lookups, because _launchers() asks hasattr() of the
    # shell32, kernel32 and advapi32 functions it names, and that lookup
    # must reach the real DLL, which keeps the real function. With the
    # guard laid first, that lookup and the check below get the guard's
    # stubs instead, which the DLL does not keep: the check fails the setup
    # of every test ("launchers still stubs before the net:
    # ['shell32.ShellExecuteW', ...]"), with pytest 9.1.1 and 9.2.0 alike.
    # Without the check, pytest 9.1.1's monkeypatch, which puts back the
    # value it read, takes those stubs as the values to put back: it left
    # them on the DLLs (found at the end of the session). 9.2.0 reads the
    # DLL's own entry instead, finds none, and deletes the one it added.
    launchers = _launchers()
    others = [(os, "startfile", "os.startfile"),
              (QtGui.QDesktopServices, "openUrl", "QDesktopServices.openUrl"),
              (QtCore, "QProcess", "QtCore.QProcess")]
    if outermost:
        # "is True": a mock in a launcher's place answers any attribute.
        left = [label for owner, name, label in [*launchers, *others]
                if getattr(getattr(owner, name, None), "forbids_real_launch",
                           False) is True]
        assert left == [], f"launchers still stubs before the net: {left}"
    replaced: dict[int, tuple[object, object]] = {}

    def replace(owner, name, stub, raising=True, wrap=None):
        real = getattr(owner, name, None)
        if real is not None:
            replaced.setdefault(id(real), (real, stub))
        monkeypatch.setattr(owner, name, stub if wrap is None else wrap(stub),
                            raising=raising)

    for owner, name, label in launchers:
        replace(owner, name, stub_for(label))
    # Missing off Windows; created there too, as the tests set
    # sys.platform to "win32" on every platform.
    replace(os, "startfile", stub_for("os.startfile"), raising=False)
    replace(QtGui.QDesktopServices, "openUrl",
            stub_for("QDesktopServices.openUrl"), wrap=staticmethod)
    replace(QtCore, "QProcess",
            _qprocess_without_starts(QtCore.QProcess, stub_for))
    _guard_dll_lookups(monkeypatch, stub_for)
    for module in _project_modules():
        for attr, value in list(vars(module).items()):
            hit = replaced.get(id(value))
            if hit is not None and hit[0] is value:
                monkeypatch.setattr(module, attr, hit[1])
    return launched


def _net_laid() -> bool:
    """Whether a net of ``forbid_real_launches`` is laid: its lookup guard
    is in place."""
    return getattr(ctypes.CDLL.__getattr__, "forbids_real_launch",
                   False) is True


def _guard_dll_lookups(monkeypatch, stub_for):
    """A DLL function that starts a program, looked up by name on any
    ctypes DLL during the test, is a stub. Not kept on the DLL, as a real
    function would be: the stub must not outlive the test."""
    real_getitem = ctypes.CDLL.__getitem__
    real_getattr = ctypes.CDLL.__getattr__

    def getitem(dll, name_or_ordinal):
        if _is_dll_launcher(name_or_ordinal):
            return stub_for(f"{dll._name}[{name_or_ordinal!r}]")
        return real_getitem(dll, name_or_ordinal)

    def getattr_(dll, name):
        if _is_dll_launcher(name):
            return stub_for(f"{dll._name}.{name}")
        return real_getattr(dll, name)

    for method in (getitem, getattr_):
        method.forbids_real_launch = True
    monkeypatch.setattr(ctypes.CDLL, "__getitem__", getitem)
    monkeypatch.setattr(ctypes.CDLL, "__getattr__", getattr_)


_REAL_PATHS: dict[str, str] = {}


def _real_path(path: str) -> str:
    """*path* with its links, junctions, subst drives and short names
    resolved, and its case folded where the platform folds it. Kept per
    path, as the modules are walked before every test."""
    path = os.path.abspath(path)
    real = _REAL_PATHS.get(path)
    if real is None:
        real = _REAL_PATHS[path] = os.path.normcase(os.path.realpath(path))
    return real


_APP = _real_path(str(ROOT / "app")) + os.sep
_SCRIPTS = frozenset(_real_path(str(ROOT / n))
                     for n in ("pdfapps.py", "installer.py", "uninstaller.py"))


def _project_modules(app: str = _APP, scripts: frozenset[str] = _SCRIPTS):
    """The loaded modules of PDFApps: those under *app*, and the scripts at
    the root under any module name (the installers' tests load them under
    names of their own). Compared by real paths: a module may have been
    loaded through another path to the same file."""
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if isinstance(path, str):
            path = _real_path(path)
            if path.startswith(app) or path in scripts:
                yield module


def _qprocess_without_starts(real, stub_for):
    """A subclass of *real* whose every start method is a stub. Called on
    the class (``QProcess.startDetached(program, args)``), the program
    comes first; called on an instance, its ``program()`` takes the
    instance's place in the record."""

    def method(name):
        stub = stub_for(f"QProcess.{name}")

        def start(*args, **kwargs):
            if args and isinstance(args[0], real):
                args = (args[0].program(), *args[1:])
            return stub(*args, **kwargs)
        start.forbids_real_launch = True
        return start

    namespace = {name: method(name) for name in _QPROCESS_STARTS}
    namespace["forbids_real_launch"] = True
    return type("QProcess", (real,), namespace)


def _no_launches_after_their_test():
    late = take_launches_after_their_test()
    assert late == [], f"launched after their test had ended: {late}"


def launches_forbidden(monkeypatch):
    """The body of each file's autouse fixture: no test may start a real
    program through the launchers ``forbid_real_launches`` replaces;
    checked after the test too, as production code may swallow the
    AssertionError, and for launches after an earlier test had ended."""
    _no_launches_after_their_test()
    test = types.SimpleNamespace(ended=False)
    launched = forbid_real_launches(monkeypatch, test)
    yield launched
    test.ended = True
    assert launched == [], launched
    _no_launches_after_their_test()
