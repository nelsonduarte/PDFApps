"""No program PDFApps starts may come from the current folder.

On Windows a program named without a folder is looked up by
``CreateProcess`` in the folder of the running program and then in the
current folder, before ``PATH``; ``shutil.which`` puts the current folder
first too and answers ``.\\name.EXE`` for a file there. A file planted in
the folder PDFApps was started from would run in place of the real one.
The fix: the rule a path found by ``which`` must pass (absolute, an
existing file, ``.exe`` on Windows), and absolute paths for the programs
that ship with Windows; the Help button opens its page through the shell
on Windows, not through ``webbrowser``, whose fallback starts browsers by
bare name. Nothing here sets the environment variable that closes the
current folder to the lookup: every child would inherit it, and
``test_t7_no_source_names_the_variable`` guards that choice.

The installer, the uninstaller and the copies of the rule and of the
Windows folders they keep are tested in
``tests/test_no_cwd_executables_installers.py``. In both files no test
may start a real program: an autouse fixture replaces the launchers
listed in ``forbid_real_launches`` (``tests/_cwd_exec_helpers.py``),
whose docstring says what stays outside.
"""

from __future__ import annotations

import ast
import asyncio.base_events
import asyncio.subprocess
import contextlib
import ctypes
import glob
import multiprocessing.process
import ntpath
import os
import platform
import posixpath
import re
import shutil
import subprocess
import sys
import types
import webbrowser
from pathlib import Path
from unittest import mock

import pytest
from _cwd_exec_helpers import (
    ROOT,
    Spy,
    _project_modules,
    _real_path,
    forbid_real_launches,
    launches_forbidden,
    take_launches_after_their_test,
    touch,
    which_answer,
)

from app import _browser, _exe_paths, base, utils
from app.tools import _ocr_paths
from app.tools import ocr as ocr_mod

_VAR = "NoDefaultCurrentDirectoryInExePath"
# The real Popen, bound before any test in a module that is not one of
# PDFApps', as "from subprocess import Popen" would bind it: the net must
# still catch it, below where its name points.
_EARLY_POPEN = subprocess.Popen


@pytest.fixture(autouse=True)
def no_real_launches(monkeypatch):
    yield from launches_forbidden(monkeypatch)


def _sources() -> list[Path]:
    """Every file the PDFApps programs are built from."""
    files = sorted(p for p in (ROOT / "app").rglob("*.py")
                   if "__pycache__" not in p.parts)
    return files + [ROOT / n for n in
                    ("pdfapps.py", "installer.py", "uninstaller.py")]


def test_sources_include_the_entry_points():
    # The installer and the uninstaller start most of the programs the
    # guard and T7 look for; dropping them would leave both blind there.
    sources = _sources()
    names = {p.name for p in sources if p.parent == ROOT}
    assert names == {"pdfapps.py", "installer.py", "uninstaller.py"}
    assert all(p.is_file() for p in sources)
    assert ROOT / "app" / "base.py" in sources
    # A module in a subfolder: "app" must be searched at every depth.
    assert ROOT / "app" / "tools" / "ocr.py" in sources


_SPAWN_NAMES = [f"{kind}{s}" for kind in ("exec", "spawn")
                for s in ("l", "le", "lp", "lpe", "v", "ve", "vp", "vpe")]
_QPROCESS_STARTS = ("start", "startDetached", "startCommand", "execute",
                    "open")


def _launchers():
    """Every launcher the fixture must replace, named here rather than
    taken from the helper, so that dropping one there is noticed."""
    from PySide6 import QtCore, QtGui

    names = [(subprocess, n) for n in (
        "Popen", "run", "call", "check_call", "check_output", "getoutput",
        "getstatusoutput")]
    os_names = ("system", "popen", "startfile", "posix_spawn", "posix_spawnp",
                "fork", "forkpty", *_SPAWN_NAMES)
    # os and the C module it takes them from, each with its own reference.
    names += [(m, n) for m in (os, sys.modules[os.name]) for n in os_names]
    names += [(webbrowser, n) for n in ("open", "open_new", "open_new_tab",
                                        "get")]
    names += [(m, n) for m in (asyncio, asyncio.subprocess)
              for n in ("create_subprocess_exec", "create_subprocess_shell")]
    names += [(asyncio.base_events.BaseEventLoop, n)
              for n in ("subprocess_exec", "subprocess_shell")]
    names.append((multiprocessing.process.BaseProcess, "start"))
    names.append((QtGui.QDesktopServices, "openUrl"))
    # The class, then each start method of whatever the name now holds.
    names.append((QtCore, "QProcess"))
    names += [(QtCore.QProcess, n) for n in _QPROCESS_STARTS]
    # Any lookup by name of a DLL function, on any DLL.
    names += [(ctypes.CDLL, n) for n in ("__getattr__", "__getitem__")]
    if sys.platform == "win32":
        import _winapi
        names.append((_winapi, "CreateProcess"))
        names += [(ctypes.windll.shell32, n) for n in (
            "ShellExecuteW", "ShellExecuteA", "ShellExecuteExW",
            "ShellExecuteExA")]
        names += [(ctypes.windll.kernel32, n) for n in (
            "CreateProcessW", "CreateProcessA", "WinExec")]
        names += [(ctypes.windll.advapi32, n) for n in (
            "CreateProcessAsUserW", "CreateProcessAsUserA",
            "CreateProcessWithLogonW", "CreateProcessWithTokenW")]
    else:
        import _posixsubprocess
        names.append((_posixsubprocess, "fork_exec"))
        # subprocess's own name for it, bound when subprocess was imported.
        names.append((subprocess, "_fork_exec"))
    return [(m, n) for m, n in names
            if (m is os and n == "startfile") or hasattr(m, n)]


def test_every_launcher_is_replaced():
    missing = [f"{getattr(m, '__name__', m)}.{n}" for m, n in _launchers()
               if not getattr(getattr(m, n), "forbids_real_launch", False)]
    assert missing == []


@pytest.mark.parametrize(("module", "name", "as_list"), [
    (os, "system", False),
    (os, "startfile", False),
    (subprocess, "Popen", True),
    (subprocess, "getoutput", False),
    (webbrowser, "open", False),
])
def test_real_launches_fail_and_are_recorded(no_real_launches, tmp_path,
                                             module, name, as_list):
    launcher = getattr(module, name)
    # Checked before the call, and the program does not exist and has a
    # full path: without the stub, nothing would start.
    assert getattr(launcher, "forbids_real_launch", False), name
    program = str(tmp_path / "missing" / "tool.exe")
    args = ([program],) if as_list else (program,)
    with pytest.raises(AssertionError, match="tried to start a program"):
        launcher(*args)
    assert no_real_launches == [(f"{module.__name__}.{name}", args)]
    no_real_launches.clear()  # or the fixture fails this test after it


def test_qprocess_starts_fail_and_are_recorded(no_real_launches, tmp_path):
    from PySide6.QtCore import QProcess

    assert getattr(QProcess, "forbids_real_launch", False)
    # Each method checked before any call, as in the test above.
    for name in ("start", "startDetached", "execute"):
        method = getattr(QProcess, name)
        assert getattr(method, "forbids_real_launch", False), name
    program = str(tmp_path / "missing" / "tool.exe")
    proc = QProcess()
    proc.setProgram(program)
    with pytest.raises(AssertionError, match="tried to start a program"):
        proc.start()
    with pytest.raises(AssertionError, match="tried to start a program"):
        proc.startDetached()
    with pytest.raises(AssertionError, match="tried to start a program"):
        QProcess.startDetached(program, [])
    with pytest.raises(AssertionError, match="tried to start a program"):
        QProcess.execute(program, [])
    assert no_real_launches == [
        ("QProcess.start", (program,)),
        ("QProcess.startDetached", (program,)),
        ("QProcess.startDetached", (program, [])),
        ("QProcess.execute", (program, [])),
    ]
    no_real_launches.clear()


# Each a DLL other than the objects whose attributes the fixture replaces,
# or a lookup other than by attribute: (DLL, how to fetch, name).
if sys.platform == "win32":
    _DLL_ROUTES = [
        ("windll.Shell32", "attribute", "ShellExecuteW"),
        ("cdll.shell32", "attribute", "ShellExecuteW"),
        ("oledll.shell32", "attribute", "ShellExecuteW"),
        ("WinDLL.shell32", "attribute", "ShellExecuteExA"),
        ("windll.shell32", "item", "ShellExecuteW"),
        ("windll.shell32", "bytes", "ShellExecuteW"),
        ("WinDLL.kernel32", "attribute", "WinExec"),
        ("WinDLL.kernel32", "attribute", "CreateProcessInternalW"),
        ("WinDLL.advapi32", "item", "CreateProcessWithLogonW"),
        ("cdll.msvcrt", "attribute", "system"),
        ("cdll.msvcrt", "item", "_wspawnv"),
        ("cdll.ucrtbase", "attribute", "_o__wsystem"),
    ]
else:
    _DLL_ROUTES = [
        ("CDLL.libc", "attribute", "system"),
        ("CDLL.libc", "item", "execv"),
        ("CDLL.libc", "bytes", "system"),
        ("CDLL.libc", "attribute", "posix_spawnp"),
        ("CDLL.libc", "attribute", "pidfd_spawnp"),
        ("CDLL.libc", "attribute", "wordexp"),
        ("CDLL.libc", "attribute", "fork"),
    ]


def _dll(where):
    loader, name = where.split(".")
    if loader == "CDLL":
        return ctypes.CDLL(None)
    if loader == "WinDLL":
        return ctypes.WinDLL(name)
    return getattr(getattr(ctypes, loader), name)


@pytest.mark.parametrize(("where", "how", "name"), _DLL_ROUTES)
def test_dll_launchers_fail_however_fetched(no_real_launches, tmp_path,
                                            where, how, name):
    dll = _dll(where)
    kept_before = name in vars(dll)
    if how == "attribute":
        func = getattr(dll, name)
    else:
        func = dll[name.encode() if how == "bytes" else name]
    assert getattr(func, "forbids_real_launch", False), (where, name)
    # Not kept on the DLL by the lookup: after the test, the name must
    # reach the real function again.
    assert (name in vars(dll)) is kept_before
    program = str(tmp_path / "missing" / "tool.exe")
    with pytest.raises(AssertionError, match="tried to start a program"):
        func(program)
    assert [args for _, args in no_real_launches] == [(program,)]
    no_real_launches.clear()


def test_launchers_bound_early_in_the_apps_modules_are_replaced(
        no_real_launches, monkeypatch, tmp_path):
    """``from os import system`` in a module of PDFApps, before the test:
    the name keeps the function it was bound to, whatever os holds. A
    second net, laid inside this test, plays the fixture; the first one's
    stubs stand in for the real launchers."""
    from PySide6 import QtCore, QtGui

    modules = []
    # A module of app, a script at the root under a name of its own (as
    # the installers' tests load them), and a module of neither.
    for name, path in (("app._cwd_exec_probe", ROOT / "app" / "_probe.py"),
                       ("_cwd_exec_probe_script", ROOT / "installer.py"),
                       ("_cwd_exec_probe_outside", tmp_path / "_probe.py")):
        module = types.ModuleType(name)
        module.__file__ = str(path)
        module.system = os.system
        module.QProcess = QtCore.QProcess
        module.open_url = QtGui.QDesktopServices.openUrl
        monkeypatch.setitem(sys.modules, name, module)
        modules.append(module)
    inside, script, outside = modules
    first_system = os.system
    first_open_url = QtGui.QDesktopServices.openUrl
    program = str(tmp_path / "missing" / "tool.exe")
    with pytest.MonkeyPatch.context() as mp:
        launched = forbid_real_launches(mp)
        assert os.system is not first_system
        assert QtGui.QDesktopServices.openUrl is not first_open_url
        for module in (inside, script):
            assert module.system is os.system
            assert module.QProcess is QtCore.QProcess
            assert module.open_url is QtGui.QDesktopServices.openUrl
        # Only the modules of PDFApps.
        assert outside.system is first_system
        assert outside.open_url is first_open_url
        with pytest.raises(AssertionError, match="tried to start a program"):
            inside.system(program)
        with pytest.raises(AssertionError, match="tried to start a program"):
            script.open_url(program)
        assert launched == [("os.system", (program,)),
                            ("QDesktopServices.openUrl", (program,))]
    assert inside.system is script.system is first_system
    assert inside.open_url is script.open_url is first_open_url
    assert no_real_launches == []


def test_the_apps_modules_are_found_by_their_real_path(no_real_launches,
                                                       monkeypatch, tmp_path):
    """By a real module of app, and by a module whose path goes through a
    link (a junction on Windows) to the folder searched."""
    assert any(module is base for module in _project_modules())
    real = tmp_path / "real"
    (real / "app").mkdir(parents=True)
    link = tmp_path / "link"
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(real), str(link))
    else:
        link.symlink_to(real, target_is_directory=True)
    module = types.ModuleType("_cwd_exec_probe_linked")
    module.__file__ = str(link / "app" / "_probe.py")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    app = _real_path(str(real / "app")) + os.sep
    assert not os.path.normcase(module.__file__).startswith(app)
    assert any(m is module for m in _project_modules(app, frozenset()))


def test_a_launch_after_its_test_ended_is_reported(no_real_launches,
                                                   tmp_path):
    """A QProcess made during a test and kept past it still has the stubs
    of that test, whose record no one checks any more."""
    from PySide6 import QtCore

    program = str(tmp_path / "missing" / "tool.exe")
    with pytest.MonkeyPatch.context() as mp:
        # A test of its own, inside this one: setup, body, teardown.
        net = launches_forbidden(mp)
        assert next(net) == []
        proc = QtCore.QProcess()
        proc.setProgram(program)
        with pytest.raises(StopIteration):
            next(net)
    with pytest.raises(AssertionError, match="tried to start a program"):
        proc.start()
    # The next test to start reports it, and only once.
    late = re.escape(repr([("QProcess.start", (program,))]))
    with (pytest.MonkeyPatch.context() as mp,
          pytest.raises(AssertionError,
                        match="after their test had ended: " + late)):
        next(launches_forbidden(mp))
    assert take_launches_after_their_test() == []
    assert no_real_launches == []


def test_a_swallowed_launch_fails_the_test(no_real_launches, tmp_path):
    """Production code may catch the stub's AssertionError; the check after
    the test still fails it. A test of its own, inside this one."""
    assert getattr(os.system, "forbids_real_launch", False)
    program = str(tmp_path / "missing" / "tool.exe")
    with pytest.MonkeyPatch.context() as mp:
        net = launches_forbidden(mp)
        assert next(net) == []
        with contextlib.suppress(AssertionError):
            # A stub of the net laid above, never the real os.system: it
            # raises before any shell could run.
            os.system(program)  # nosec B605
        with pytest.raises(AssertionError,
                           match=re.escape(repr([("os.system", (program,))]))):
            next(net)
    assert no_real_launches == []


def test_stubs_an_earlier_net_left_are_reported(no_real_launches):
    """Laid when no other net is, the net first checks that no launcher is
    still a stub, which only a net not undone in full would leave. Played
    by this test's own net, with the sign that a net is laid hidden behind
    a lookup that still goes through its guard."""
    guard = ctypes.CDLL.__getattr__

    def unmarked_guard(dll, name):
        # The guard's lookups, without the attribute that marks a net.
        return guard(dll, name)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ctypes.CDLL, "__getattr__", unmarked_guard)
        # A mock answers any attribute, forbids_real_launch too: it is not
        # one of the net's stubs.
        mp.setattr(webbrowser, "open", mock.MagicMock())
        with pytest.raises(AssertionError,
                           match="still stubs before the net") as raised:
            forbid_real_launches(mp)
    for label in ("'os.system'", "'subprocess.Popen'", "'QtCore.QProcess'",
                  "'QDesktopServices.openUrl'"):
        assert label in str(raised.value), label
    assert "'webbrowser.open'" not in str(raised.value)
    assert ctypes.CDLL.__getattr__ is guard
    assert no_real_launches == []


@pytest.mark.parametrize("option", ["cwd", "start_new_session"])
def test_a_popen_bound_early_outside_the_app_is_caught(no_real_launches,
                                                       tmp_path, option):
    """_EARLY_POPEN is the real Popen. Off Windows, cwd= and
    start_new_session=True keep subprocess off its os.posix_spawn route,
    so it calls its own name for _posixsubprocess.fork_exec."""
    if sys.platform == "win32":
        where = "_winapi.CreateProcess"
        import _winapi
        stub = _winapi.CreateProcess
    elif hasattr(subprocess, "_fork_exec"):
        where = "subprocess._fork_exec"
        stub = subprocess._fork_exec
    else:
        # Python 3.10 has no name of its own for it in subprocess.
        import _posixsubprocess
        where = "_posixsubprocess.fork_exec"
        stub = _posixsubprocess.fork_exec
    # Checked before the call, as above.
    assert getattr(stub, "forbids_real_launch", False), where
    program = str(tmp_path / "missing" / "tool.exe")
    kwargs = ({"cwd": str(tmp_path)} if option == "cwd"
              else {"start_new_session": True})
    with pytest.raises(AssertionError, match="tried to start a program"):
        _EARLY_POPEN([program], **kwargs)
    assert [name for name, _ in no_real_launches] == [where]
    no_real_launches.clear()


# Every name the fixture refuses to look up in a DLL, written out here
# rather than taken from the helper, as _launchers() is above; the C
# runtime's exec* and spawn* are built from their prefixes and suffixes.
_DLL_LAUNCHER_NAMES = [
    "ShellExecuteW", "ShellExecuteA", "ShellExecuteExW", "ShellExecuteExA",
    "ShellExecuteEx", "RealShellExecuteW", "RealShellExecuteA",
    "RealShellExecuteExW", "RealShellExecuteExA", "WOWShellExecute",
    "ShellExec_RunDLL", "ShellExec_RunDLLA", "ShellExec_RunDLLW",
    "RunAsNewUser_RunDLLW", "SHCreateProcessAsUserW",
    "SHOpenFolderAndSelectItems",
    "CreateProcessW", "CreateProcessA", "CreateProcessInternalW",
    "CreateProcessInternalA", "NtVdm64CreateProcessInternalW", "WinExec",
    "LoadModule", "CreateProcessAsUserW", "CreateProcessAsUserA",
    "CreateProcessWithLogonW", "CreateProcessWithTokenW",
    "NtCreateUserProcess", "ZwCreateUserProcess", "NtCreateProcess",
    "NtCreateProcessEx", "ZwCreateProcess", "ZwCreateProcessEx",
    "RtlCreateUserProcess", "RtlCreateUserProcessEx",
    "FileProtocolHandler", "FileProtocolHandlerA", "OpenURL", "OpenURLA",
    "IELaunchURL",
    "system", "_wsystem", "_o_system", "_o__wsystem", "__libc_system",
    "popen", "_popen", "_wpopen", "_o__popen", "_o__wpopen", "_IO_popen",
    "posix_spawn", "posix_spawnp", "pidfd_spawn", "pidfd_spawnp",
    "execveat", "fexecve", "wordexp", "fork", "vfork", "forkpty", "_Fork",
    "__fork", "__libc_fork", "__vfork", "clone", "__clone", "daemon",
    *(f"{prefix}{kind}{suffix}"
      for prefix in ("", "_", "_w", "_o__", "_o__w")
      for kind in ("exec", "spawn")
      for suffix in ("l", "le", "lp", "lpe", "v", "ve", "vp", "vpe")),
]


def _a_loaded_dll():
    return ctypes.CDLL("msvcrt" if sys.platform == "win32" else None)


def test_every_dll_launcher_name_is_refused(no_real_launches):
    # The lookup is refused by name, before the DLL is asked: so any DLL
    # will do, whether it exports the function or not.
    dll = _a_loaded_dll()
    missing = [n for n in _DLL_LAUNCHER_NAMES
               if not getattr(getattr(dll, n), "forbids_real_launch", False)
               or not getattr(dll[n], "forbids_real_launch", False)
               or not getattr(dll[n.encode()], "forbids_real_launch", False)]
    assert missing == []
    # Other names still reach the DLL.
    assert not hasattr(dll, "no_such_function_here")


def test_a_lookup_by_ordinal_reaches_the_dll(no_real_launches):
    # An ordinal is no name: the guard hands it to the DLL as it is.
    if sys.platform == "win32":
        func = ctypes.WinDLL("kernel32")[1]
        assert not getattr(func, "forbids_real_launch", False)
        assert isinstance(func, ctypes._CFuncPtr)
    else:
        # ctypes looks up ordinals on Windows only.
        with pytest.raises(TypeError, match="function name must be"):
            ctypes.CDLL(None)[1]


def test_dll_launchers_fetched_before_the_test_are_replaced(
        no_real_launches, monkeypatch, tmp_path):
    """A function a DLL kept from an earlier lookup no longer goes through
    the lookup. A second net, laid inside this test, plays the fixture; a
    plain function stands in for the real one the DLL kept."""
    dll = _a_loaded_dll()
    monkeypatch.setattr(ctypes.cdll, "_cwd_exec_probe", dll, raising=False)

    def kept(*args):
        return 0

    monkeypatch.setattr(dll, "system", kept, raising=False)
    program = str(tmp_path / "missing" / "tool.exe")
    with pytest.MonkeyPatch.context() as mp:
        launched = forbid_real_launches(mp)
        assert getattr(dll.system, "forbids_real_launch", False)
        with pytest.raises(AssertionError, match="tried to start a program"):
            dll.system(program)
        assert launched == [("ctypes.cdll._cwd_exec_probe.system",
                             (program,))]
    assert dll.system is kept
    assert no_real_launches == []


def _inside(path: str, folder: Path) -> bool:
    full = os.path.normcase(os.path.abspath(path))
    return os.path.dirname(full) == os.path.normcase(str(folder))


# ---------------------------------------------------------------------------
# T1: the real which() on Windows, with a program planted in the current
# folder and nothing on PATH
# ---------------------------------------------------------------------------

_windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="which() looks in the current folder only on Windows")


def _plant(monkeypatch, tmp_path, planted: str) -> Path:
    cwd = tmp_path / "cwd"
    touch(cwd / planted)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(cwd)
    # Whatever the environment of whoever runs the suite: with the
    # variable set, which() would skip the current folder and the test
    # would pass for the wrong reason.
    monkeypatch.delenv(_VAR, raising=False)
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    # Control: the real which() does answer the planted file.
    stem = planted.split(".")[0]
    found = shutil.which(stem)
    assert found is not None and _inside(found, cwd), found
    return cwd


@_windows_only
@pytest.mark.parametrize("planted", ["tesseract.exe", "tesseract.BAT"])
def test_t1_find_tesseract_skips_the_current_folder(
        monkeypatch, tmp_path, planted):
    cwd = _plant(monkeypatch, tmp_path, planted)
    found = _ocr_paths._find_tesseract()
    # Not None: a Tesseract installed in its fixed folder is legitimate.
    assert found is None or not _inside(found, cwd), found


@_windows_only
@pytest.mark.parametrize("planted", ["gswin64c.exe", "gswin64c.BAT"])
def test_t1_find_gs_skips_the_current_folder(monkeypatch, tmp_path, planted):
    cwd = _plant(monkeypatch, tmp_path, planted)
    # The cache is usually filled at collection time (skipif conditions in
    # other test files call _find_gs); without the reset, _find_gs answers
    # from it and never looks.
    monkeypatch.setattr(utils, "_GS_CACHE", (False, None))
    # _find_gs asks platform.system(). With platform's cache still empty
    # (these two files run alone) and its WMI query failing, the stdlib
    # runs "ver" through subprocess, which the fixture refuses, and the
    # test failed now and then. This is the only test of the two files
    # that reaches platform: the others fake it or never call it.
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    found = utils._find_gs()
    assert found is None or not _inside(found, cwd), found


# ---------------------------------------------------------------------------
# T2: a fake which(), on every platform
# ---------------------------------------------------------------------------

_REFUSED_ON_WINDOWS = [
    "relative",
    "dot_relative",
    "tesseract.cmd",
    "tesseract.bat",
    "tesseract.BAT",
    "tesseract.com",
    "tesseract",
]


@pytest.mark.parametrize("kind", _REFUSED_ON_WINDOWS)
def test_t2_find_tesseract_refuses(monkeypatch, tmp_path, kind):
    answer = which_answer(kind, tmp_path, monkeypatch, "tesseract")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which",
                        lambda name: answer if name == "tesseract" else None)
    monkeypatch.setattr(_ocr_paths, "_tesseract_candidates", list)
    assert _ocr_paths._find_tesseract() is None


@_windows_only
def test_t2_find_tesseract_refuses_a_path_without_drive(monkeypatch, tmp_path):
    # \Users\...\tesseract.EXE: rooted, but relative to the current drive.
    # os.path.isabs refuses it on the 3.14 of the Windows job; this case
    # holds it against a check of the leading separator.
    answer = which_answer("rooted_no_drive", tmp_path, monkeypatch,
                           "tesseract")
    assert os.path.isfile(answer)  # it does resolve, from this drive
    monkeypatch.setattr(shutil, "which", lambda name: answer)
    monkeypatch.setattr(_ocr_paths, "_tesseract_candidates", list)
    assert _ocr_paths._find_tesseract() is None


def test_t2_find_tesseract_accepts_an_absolute_exe(monkeypatch, tmp_path):
    answer = touch(tmp_path / "bin" / "tesseract.EXE")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda name: answer)
    monkeypatch.setattr(_ocr_paths, "_tesseract_candidates", list)
    assert _ocr_paths._find_tesseract() == answer


def test_t2_find_tesseract_off_windows_needs_no_suffix(monkeypatch, tmp_path):
    answer = touch(tmp_path / "bin" / "tesseract")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda name: answer)
    monkeypatch.setattr(_ocr_paths, "_tesseract_candidates", list)
    assert _ocr_paths._find_tesseract() == answer


def _fake_gs_lookup(monkeypatch, answers: dict[str, str]):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(shutil, "which", lambda name: answers.get(name))
    monkeypatch.setattr(glob, "glob", lambda pattern: [])
    monkeypatch.setattr(utils, "_GS_CACHE", (False, None))


@pytest.mark.parametrize("name", ["gswin64c", "gswin32c", "gs"])
@pytest.mark.parametrize("kind", _REFUSED_ON_WINDOWS)
def test_t2_find_gs_refuses(monkeypatch, tmp_path, kind, name):
    answer = which_answer(kind, tmp_path, monkeypatch, name)
    _fake_gs_lookup(monkeypatch, {name: answer})
    assert utils._find_gs() is None


@_windows_only
def test_t2_find_gs_refuses_a_path_without_drive(monkeypatch, tmp_path):
    answer = which_answer("rooted_no_drive", tmp_path, monkeypatch,
                           "gswin64c")
    assert os.path.isfile(answer)
    _fake_gs_lookup(monkeypatch, {"gswin64c": answer})
    assert utils._find_gs() is None


@pytest.mark.parametrize("name", ["gswin64c", "gswin32c", "gs"])
def test_t2_find_gs_accepts_an_absolute_exe(monkeypatch, tmp_path, name):
    answer = touch(tmp_path / "gs" / "bin" / f"{name}.EXE")
    _fake_gs_lookup(monkeypatch, {name: answer})
    assert utils._find_gs() == os.path.abspath(answer)


# ---------------------------------------------------------------------------
# T3: never the bare name "tesseract"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("plat", "isabs"), [
    ("win32", ntpath.isabs),
    ("darwin", posixpath.isabs),
    ("linux", posixpath.isabs),
])
def test_t3_locate_tesseract_falls_back_to_an_absolute_path(
        monkeypatch, plat, isabs):
    fake = types.SimpleNamespace(
        pytesseract=types.SimpleNamespace(tesseract_cmd="tesseract"))
    monkeypatch.setattr(sys, "platform", plat)
    monkeypatch.setattr(ocr_mod, "_find_tesseract", lambda: None)
    monkeypatch.setattr(ocr_mod, "_find_tessdata", lambda exe: None)
    ocr_mod._locate_tesseract(fake)
    cmd = fake.pytesseract.tesseract_cmd
    assert cmd == _ocr_paths._tesseract_candidates()[0]
    assert isabs(cmd), cmd


def test_t3_locate_tesseract_keeps_what_it_found(monkeypatch):
    fake = types.SimpleNamespace(
        pytesseract=types.SimpleNamespace(tesseract_cmd="tesseract"))
    monkeypatch.setattr(ocr_mod, "_find_tesseract", lambda: "/x/tesseract")
    monkeypatch.setattr(ocr_mod, "_find_tessdata", lambda exe: None)
    ocr_mod._locate_tesseract(fake)
    assert fake.pytesseract.tesseract_cmd == "/x/tesseract"


# ---------------------------------------------------------------------------
# T4: the Explorer by its full path, with the app's own environment
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("opener", ["_reveal_file", "_open_folder"])
@pytest.mark.parametrize("variable_set", [True, False],
                         ids=["variable_set", "variable_unset"])
def test_t4_explorer_by_full_path(monkeypatch, tmp_path, opener,
                                  variable_set):
    if variable_set:
        monkeypatch.setenv(_VAR, "1")
    else:
        monkeypatch.delenv(_VAR, raising=False)
    target = touch(tmp_path / "out.pdf")
    spy = Spy()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "Popen", spy)
    getattr(base, opener)(target)
    assert len(spy.calls) == 1
    args, kw = spy.calls[0]
    assert ntpath.isabs(args[0]), args
    assert args[0].lower().endswith("\\explorer.exe"), args
    # executable= would be looked up by CreateProcess in the current
    # folder only, whatever args[0] says.
    assert kw.get("executable") is None
    # The Explorer inherits the app's environment, as before: whoever set
    # the variable keeps it in the Explorer, and the app adds none.
    assert kw.get("env") is None
    assert (_VAR in os.environ) is variable_set


# ---------------------------------------------------------------------------
# T7: the process never sets the variable (decision A2)
# ---------------------------------------------------------------------------

def test_t7_no_source_names_the_variable():
    """Setting it in the process would hand it to every child, the
    Explorer included, and taking it off again would take it from users
    who had it. Putting it in one child's ``env`` is a deliberate change
    of this test.

    It looks for the name as one string literal: a name built from parts
    ("NoDefault" + "CurrentDirectoryInExePath", an f-string, a join)
    gets past it. T4's check that the Explorer gets no ``env`` of its own
    catches such a change only for the Explorer."""
    offenders = []
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and node.value == _VAR:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


# ---------------------------------------------------------------------------
# T11: the pure module stays pure
# ---------------------------------------------------------------------------

_EXE_PATHS_ALLOWED = frozenset({"__future__", "ctypes", "ntpath", "os"})
_BROWSER_ALLOWED = frozenset({"__future__", "os", "sys", "webbrowser"})


def _disallowed_imports(source, allowed):
    """Every import in *source*, at any depth, that is relative or whose
    top-level module is outside *allowed*."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            bad.extend(a.name for a in node.names
                       if a.name.split(".")[0] not in allowed)
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if node.level > 0 or top not in allowed:
                bad.append("." * node.level + (node.module or ""))
    return bad


@pytest.mark.parametrize(("module", "allowed"), [
    (_exe_paths, _EXE_PATHS_ALLOWED),
    (_browser, _BROWSER_ALLOWED),
])
def test_t11_pure_modules_import_only_their_allowlist(module, allowed):
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert _disallowed_imports(source, allowed) == []


@pytest.mark.parametrize("source", [
    "from . import utils",
    "import app.i18n",
    "from app import pdf_io",
    "import shiboken6",
    "def f():\n    import PySide6\n",
])
def test_t11_allowlist_rejects(source):
    assert _disallowed_imports(source, _EXE_PATHS_ALLOWED)


def test_t11_allowlist_accepts_what_it_names():
    assert _disallowed_imports(
        "from __future__ import annotations\nimport ntpath\nimport os\n"
        "def f():\n    import ctypes\n", _EXE_PATHS_ALLOWED) == []


# ---------------------------------------------------------------------------
# No literal program found by lookup in the launch calls the guard knows
# ---------------------------------------------------------------------------
#
# What the guard sees: a string literal naming the program, either in the
# call itself or through a name bound to it with "=", ":=" or an
# annotated assignment, in the same function (or module, or class body),
# or at module level for a name the function does not make its own, or
# as the default of a parameter; one level of names for the argument, and
# one more for the first item of a list; a literal on either side of
# "or"/"and", in either branch of "x if c else y", or inside a ":=" counts
# ("found or 'tesseract'"). The calls it knows are in _MODULE_LAUNCHERS,
# _METHOD_LAUNCHERS and _QPROCESS_METHODS; for each, the program that
# CreateProcess looks up in the current folder only: the "executable="
# keyword, or the third positional argument of the subprocess functions
# (args, bufsize, executable).
# Plus "<anything>.tesseract_cmd" set by "=", by an annotated assignment
# or by setattr(x, "tesseract_cmd", ...).
# Out of its reach, by design of a static check:
#   * a module or a function reached another way than "import x [as y]"
#     or "from x import f [as g]": "sp = subprocess", getattr(...),
#     "from x import *", importlib, functools.partial, a subclass of
#     Popen;
#   * launches through ctypes other than ShellExecuteW/A's file argument,
#     such as kernel32's CreateProcessW/A and WinExec, advapi32's
#     CreateProcess* and shell32's ShellExecuteExW/ExA (its program is
#     a field of a structure), and _winapi.CreateProcess;
#   * launchers it does not know: QDesktopServices.openUrl,
#     multiprocessing.set_executable, webbrowser.get(name);
#   * a program list built by .append/.insert/.extend, by "+=" alone, by
#     list() or a comprehension, or with a starred item ([*names, p]);
#     a call whose arguments up to the program's are star-args (*argv);
#     any argument passed in **kwargs, "executable" included;
#   * a program in an f-string, a bytes literal or any other non-literal
#     string (joined, formatted, read from a file or from shutil.which:
#     T1 and T2 cover the finders);
#   * a name bound in an enclosing function (a closure), by unpacking or
#     by a for loop; a parameter, but for its default; a default that is
#     itself a name ("def f(exe=EXE)", with EXE = "explorer"); the
#     defaults of a lambda; an attribute (self.EXE, a class attribute
#     read through self);
#   * tesseract_cmd set by "+=", by a tuple target
#     ("t.tesseract_cmd, x = ..."), by setattr with the attribute's name
#     in a variable, by builtins.setattr or through __dict__;
#   * QProcess.start, startCommand and execute on a receiver other than
#     QProcess itself, QProcess(...) or a name bound to QProcess(...) in
#     the same scope (self._proc.start(...) is not seen);
#   * a name in _POSIX_ONLY used on a branch that does run on Windows:
#     the allowlist is by name, not by branch;
#   * a relative "file:" URL, which the scheme rule below lets pass;
#   * launches inside libraries (webbrowser, pytesseract,
#     multiprocessing, pty).
# Flagged although harmless, so a rewrite is needed to pass: a literal
# left of "%" ("%s" % exe); a name bound to a literal and later rebound
# to a full path, as every binding counts; a local variable named like a
# module alias of the file ("sp = Spinner()" with "import subprocess as
# sp" elsewhere); a command line that starts with a builtin of cmd.exe
# under shell=True ("echo hi"), which is no program; a nested function
# that reads a name its enclosing function binds to a full path, when the
# module binds the same name to a bare one (the module's is read); a
# lambda's parameter named like such a module constant. A URL is not a
# program: "://" or a scheme of two or more letters ("mailto:") passes.

# Launch functions of a module: the index of the argument that names the
# program, and how it names it.
_ARGV, _COMMAND, _PROGRAM = "argv", "command", "program"
_SPAWN = ("l", "le", "lp", "lpe", "v", "ve", "vp", "vpe")
_MODULE_LAUNCHERS = {
    "subprocess": {
        **{name: (0, _ARGV) for name in
           ("Popen", "run", "call", "check_call", "check_output")},
        "getoutput": (0, _COMMAND),
        "getstatusoutput": (0, _COMMAND),
    },
    "os": {
        "startfile": (0, _PROGRAM),
        "system": (0, _COMMAND),
        "popen": (0, _COMMAND),
        "posix_spawn": (0, _PROGRAM),
        "posix_spawnp": (0, _PROGRAM),
        **{f"exec{s}": (0, _PROGRAM) for s in _SPAWN},
        **{f"spawn{s}": (1, _PROGRAM) for s in _SPAWN},
    },
    "asyncio": {
        "create_subprocess_exec": (0, _PROGRAM),
        "create_subprocess_shell": (0, _COMMAND),
    },
}
# Methods whose names nothing else in the code uses, on any receiver.
_METHOD_LAUNCHERS = {
    "setProgram": (0, _PROGRAM),
    "startDetached": (0, _PROGRAM),
    "ShellExecuteW": (2, _PROGRAM),
    "ShellExecuteA": (2, _PROGRAM),
}
# QProcess methods with common names (re's Match.start, a cursor's
# execute), matched only on a receiver known to be a QProcess.
_QPROCESS_METHODS = {
    "start": (0, _PROGRAM),
    "startCommand": (0, _COMMAND),
    "execute": (0, _PROGRAM),
}
_KEYWORDS = ("args", "program", "command", "cmd", "file", "path", "filepath")

# Programs started by bare name only on branches that never run on
# Windows, where the lookup does not include the current folder.
_POSIX_ONLY = {
    # macOS: app/base.py _reveal_file and _open_folder, app/updater.py
    # _apply_update_macos_dmg, installer.py open_file.
    "open",
    # Linux: app/base.py _reveal_file and _open_folder.
    "xdg-open",
    # Linux: installer.py _register_file_association_linux.
    "xdg-mime",
    # Linux: installer.py _register_file_association_linux and
    # uninstaller.py remove_shortcuts.
    "update-desktop-database",
    # macOS: installer.py install_tesseract_macos and
    # install_ghostscript_macos.
    "brew",
    # Linux: installer.py install_tesseract_linux and
    # install_ghostscript_linux.
    "sudo",
}

_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


# Two letters at least: "C:tool.exe" is a drive-relative path, not a URL.
_URL_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]+:")


def _found_by_lookup(program: str) -> bool:
    """Whether Windows would look *program* up (a name without a folder)
    or resolve it against the current folder (a relative path). A URL is
    not a program; a path with a root but no drive resolves against the
    current drive, not the current folder."""
    if not program or "://" in program or _URL_SCHEME.match(program):
        return False
    if program.startswith(("/", "\\")):
        return False
    return not (ntpath.splitdrive(program)[0] and ntpath.isabs(program))


def _first_word(command: str) -> str:
    command = command.strip()
    if command.startswith('"'):
        return command[1:].split('"', 1)[0]
    return command.split()[0] if command else command


def _own_nodes(scope):
    """The nodes of *scope*, without those of the functions and classes
    defined in it."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _bindings(scope) -> dict[str, list[ast.expr]]:
    """What each name is bound to by "=", ":=" or an annotated
    assignment in *scope* itself."""
    bound: dict[str, list[ast.expr]] = {}
    for node in _own_nodes(scope):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bound.setdefault(target.id, []).append(value)
    return bound


def _parameters(scope) -> list[tuple[ast.arg, ast.expr | None]]:
    """Each parameter of the function *scope*, with its default."""
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    a = scope.args
    positional = [*a.posonlyargs, *a.args]
    defaults = [None] * (len(positional) - len(a.defaults)) + a.defaults
    return [*zip(positional, defaults), *zip(a.kwonlyargs, a.kw_defaults),
            *((p, None) for p in (a.vararg, a.kwarg) if p)]


def _scope_bindings(scope, module_bound) -> dict[str, list[ast.expr]]:
    """What each name may be bound to in *scope*: its own bindings, the
    defaults of its parameters and, for the names it does not make local,
    the module's (a function reads a module constant; it does not read
    the names of a class or of an enclosing function)."""
    bound = _bindings(scope)
    if isinstance(scope, ast.Module):
        return bound
    local = {n.id for n in _own_nodes(scope)
             if isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Load)}
    for param, default in _parameters(scope):
        local.add(param.arg)
        if default is not None:
            bound.setdefault(param.arg, []).append(default)
    for name, values in module_bound.items():
        if name not in local:
            bound[name] = values
    return bound


def _values(expr, bound) -> list[ast.expr]:
    """*expr*, or what the scope binds it to if it is a name."""
    if isinstance(expr, ast.Name):
        return bound.get(expr.id, [])
    return [expr]


def _alternatives(value):
    """What *value* may evaluate to, as far as literals go: each side of
    "or" and "and", each branch of "x if c else y", the left of "+", the
    value of ":=" ([(exe := "explorer"), p])."""
    if isinstance(value, ast.NamedExpr):
        yield from _alternatives(value.value)
    elif isinstance(value, ast.BoolOp):
        for operand in value.values:
            yield from _alternatives(operand)
    elif isinstance(value, ast.IfExp):
        yield from _alternatives(value.body)
        yield from _alternatives(value.orelse)
    elif isinstance(value, ast.BinOp):  # ["cmd"] + rest, "cmd %s" % x
        yield from _alternatives(value.left)
    else:
        yield value


def _resolved(expr, bound):
    for value in _values(expr, bound):
        yield from _alternatives(value)


def _literal_programs(expr, bound, how):
    """The programs *expr* names as string literals, read as *how*."""
    for value in _resolved(expr, bound):
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            yield value.value if how == _PROGRAM else _first_word(value.value)
        elif (how == _ARGV and isinstance(value, (ast.List, ast.Tuple))
              and value.elts and not isinstance(value.elts[0], ast.Starred)):
            for first in _resolved(value.elts[0], bound):
                if (isinstance(first, ast.Constant)
                        and isinstance(first.value, str)):
                    yield first.value


def _program_argument(call, index):
    if any(isinstance(a, ast.Starred) for a in call.args[:index + 1]):
        return None
    if index < len(call.args):
        return call.args[index]
    return next((k.value for k in call.keywords if k.arg in _KEYWORDS),
                None)


def _imports(tree):
    """Local names of the launch modules and functions, and of QProcess,
    under any alias."""
    modules: dict[str, str] = {}
    functions: dict[str, tuple[int, str]] = {}
    qprocess = {"QProcess"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in _MODULE_LAUNCHERS:
                    modules[a.asname or a.name] = a.name
        elif isinstance(node, ast.ImportFrom):
            known = _MODULE_LAUNCHERS.get(node.module or "", {})
            for a in node.names:
                if a.name in known:
                    functions[a.asname or a.name] = known[a.name]
                elif a.name == "QProcess":
                    qprocess.add(a.asname or a.name)
    # The usual names, imported or not: a snippet in a test has no imports.
    for name in _MODULE_LAUNCHERS:
        modules.setdefault(name, name)
    return modules, functions, qprocess


def _is_qprocess(expr, bound, qprocess) -> bool:
    for value in [expr, *_values(expr, bound)]:
        if isinstance(value, ast.Call):
            value = value.func
        if isinstance(value, ast.Name) and value.id in qprocess:
            return True
        if isinstance(value, ast.Attribute) and value.attr == "QProcess":
            return True
    return False


def _launch(call, bound, modules, functions, qprocess):
    """(index, how) of the program argument if *call* is a known launch."""
    func = call.func
    if isinstance(func, ast.Name):
        return functions.get(func.id)
    if not isinstance(func, ast.Attribute):
        return None
    if isinstance(func.value, ast.Name) and func.value.id in modules:
        return _MODULE_LAUNCHERS[modules[func.value.id]].get(func.attr)
    if func.attr in _METHOD_LAUNCHERS:
        return _METHOD_LAUNCHERS[func.attr]
    if (func.attr in _QPROCESS_METHODS
            and _is_qprocess(func.value, bound, qprocess)):
        return _QPROCESS_METHODS[func.attr]
    return None


def _tesseract_cmd_value(node):
    """What *node* sets pytesseract's ``tesseract_cmd`` to, if it sets it:
    by "=", by an annotated assignment or by setattr."""
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        targets = [node.target]
    elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
          and node.func.id == "setattr" and len(node.args) == 3
          and isinstance(node.args[1], ast.Constant)
          and node.args[1].value == "tesseract_cmd"):
        return node.args[2]
    else:
        return None
    if any(isinstance(t, ast.Attribute) and t.attr == "tesseract_cmd"
           for t in targets):
        return node.value
    return None


def _programs(node, bound, modules, functions, qprocess) -> list[str]:
    """The literal programs *node* would start, if it is a known launch
    or sets tesseract_cmd."""
    programs: list[str] = []
    launch = (_launch(node, bound, modules, functions, qprocess)
              if isinstance(node, ast.Call) else None)
    if launch:
        arg = _program_argument(node, launch[0])
        if arg is not None:
            programs += _literal_programs(arg, bound, launch[1])
        # Popen(["C:\\Windows\\explorer.exe"], executable="explorer.exe")
        # starts the second, looked up in the current folder only.
        for keyword in node.keywords:
            if keyword.arg == "executable":
                programs += _literal_programs(keyword.value, bound, _PROGRAM)
        # The same as Popen(args, bufsize, executable); run, call and the
        # check_* functions hand their positional arguments to Popen.
        if (launch[1] == _ARGV and len(node.args) > 2
                and not any(isinstance(a, ast.Starred)
                            for a in node.args[:3])):
            programs += _literal_programs(node.args[2], bound, _PROGRAM)
    value = _tesseract_cmd_value(node)
    if value is not None:
        programs += _literal_programs(value, bound, _PROGRAM)
    return programs


def _bare_program_launches(source):
    """(line, program) for each literal program found by lookup that a
    known launch call, or a tesseract_cmd assignment, would start."""
    tree = ast.parse(source)
    modules, functions, qprocess = _imports(tree)
    module_bound = _bindings(tree)
    found = []
    for scope in ast.walk(tree):
        if not isinstance(scope, _SCOPES):
            continue
        bound = _scope_bindings(scope, module_bound)
        for node in _own_nodes(scope):
            programs = _programs(node, bound, modules, functions, qprocess)
            found += [(node.lineno, p) for p in programs
                      if _found_by_lookup(p) and p not in _POSIX_ONLY]
    return found


def test_known_launch_calls_have_no_literal_program_found_by_lookup():
    """No launch the guard knows, in any source file, names its program
    with a string literal that Windows would look up.

    Not seen, as the comment at the top of this section details: a module
    aliased by assignment or reached by getattr, ctypes launches other
    than ShellExecuteW/A (CreateProcessW, WinExec, ShellExecuteExW/ExA),
    launchers it does not know (QDesktopServices.openUrl,
    _winapi.CreateProcess), a list built by append or list(), star-args,
    **kwargs or a starred first item, an f-string or a bytes literal, a
    closure, an attribute, a default that is a name or a lambda's,
    tesseract_cmd set by "+=", a tuple target or setattr with a variable,
    QProcess.start on a receiver such as self._proc, a POSIX-only name on
    a branch that runs on Windows, and launches inside libraries.
    """
    offenders = [
        f"{path.relative_to(ROOT)}:{line}: {program!r}"
        for path in _sources()
        for line, program in _bare_program_launches(
            path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


@pytest.mark.parametrize("source", [
    # subprocess, literal in the call
    'subprocess.Popen(["explorer", p])',
    'subprocess.run(["cmd"] + rest)',
    'subprocess.call(("ie4uinit.exe", "-show"))',
    'subprocess.check_output(args=["powershell", "-c", x])',
    'subprocess.check_call("timeout /t 5")',
    'subprocess.run(["bin\\\\tool.exe"])',
    'subprocess.run(["C:tool.exe"])',
    'import subprocess as sp\nsp.run(["tesseract"])',
    'from subprocess import Popen as P\nP(["gswin64c"])',
    # subprocess, through a name bound in the same scope
    'def f(p):\n    cmd = ["explorer", p]\n    subprocess.Popen(cmd)',
    'def f(p):\n    cmd = ("gswin64c", p)\n    subprocess.Popen(cmd, x=1)',
    'def f(p):\n    cmd = ["gswin64c"]\n    cmd += [p]\n    subprocess.run(cmd)',
    'def f(rest):\n    cmd: list = ["cmd"] + rest\n    subprocess.run(cmd)',
    'def f(p):\n    prog = "explorer"\n    subprocess.Popen([prog, p])',
    'cmd = ["explorer"]\nsubprocess.Popen(cmd)',
    'if (cmd := ["explorer"]):\n    subprocess.Popen(cmd)',
    # os
    'os.startfile("explorer")',
    'os.system("explorer /select,x")',
    'os.system(\'"cmd" /c dir\')',
    'os.popen("explorer")',
    'os.spawnlp(os.P_NOWAIT, "explorer", "explorer")',
    'os.spawnv(os.P_WAIT, "cmd.exe", ["cmd.exe"])',
    'os.execvp("explorer", ["explorer"])',
    'os.execl("cmd", "cmd")',
    'os.posix_spawnp("explorer", [], {})',
    # asyncio
    'asyncio.create_subprocess_exec("explorer", p)',
    'asyncio.create_subprocess_shell("cmd /c dir")',
    'import os as o\no.system("cmd /c dir")',
    'from os import startfile\nstartfile("explorer")',
    'from os import system as sh\nsh("cmd /c dir")',
    'def f():\n    c = "cmd /c dir"\n    os.system(c)',
    # QProcess
    'QProcess.startDetached("explorer", [p])',
    'q = QProcess()\nq.setProgram("explorer")\nq.start()',
    'self._proc.setProgram("explorer")',
    'def f():\n    q = QProcess()\n    q.start("explorer", [p])',
    'QProcess().start("explorer")',
    'QProcess.execute("explorer", [p])',
    'from PySide6.QtCore import QProcess as QP\nq = QP(None)\nq.start("cmd")',
    'q = QtCore.QProcess()\nq.startCommand("cmd /c dir")',
    # ShellExecuteW and ShellExecuteA, the file argument
    'ctypes.windll.shell32.ShellExecuteW(None, "open", "explorer", p, None, 1)',
    'shell32.ShellExecuteA(None, "runas", "cmd.exe", p, None, 1)',
    ('def f(p):\n    exe = "explorer"\n'
     + '    shell32.ShellExecuteW(None, "open", exe, p, None, 1)'),
    # tesseract_cmd
    'pytesseract.pytesseract.tesseract_cmd = "tesseract"',
    'def f(t):\n    t.tesseract_cmd = "tesseract.exe"',
    'def f(t):\n    name = "tesseract"\n    t.tesseract_cmd = name',
    # a literal as a fallback or a branch
    't.tesseract_cmd = found or "tesseract"',
    'subprocess.run([exe if exe else "gswin64c", p])',
    'def f(found, p):\n    cmd = [found or "gs", p]\n    subprocess.run(cmd)',
    'os.startfile(path if path else "explorer")',
    # executable=: CreateProcess looks it up in the current folder only
    'subprocess.Popen([r"C:\\x\\explorer.exe"], executable="explorer.exe")',
    'def f(p):\n    exe = "cmd.exe"\n    subprocess.run([p], executable=exe)',
    'asyncio.create_subprocess_exec(p, executable="explorer")',
    'subprocess.Popen([r"C:\\x\\explorer.exe"], -1, "explorer.exe")',
    'subprocess.run([r"C:\\x\\cmd.exe"], 0, "cmd.exe")',
    # a module constant read in a function or a method
    'EXPLORER = "explorer"\ndef f(p):\n    subprocess.Popen([EXPLORER, p])',
    'CMD = ["explorer"]\ndef f():\n    subprocess.Popen(CMD)',
    'EXE = "cmd.exe"\nclass A:\n    def f(self):\n        subprocess.run([EXE])',
    # a parameter's default
    'def f(cmd=["explorer"]):\n    subprocess.run(cmd)',
    'def f(p, exe="explorer"):\n    subprocess.Popen([exe, p])',
    'def f(p, *, exe="explorer"):\n    subprocess.Popen([exe, p])',
    # getoutput and getstatusoutput run a command line
    'subprocess.getoutput("cmd /c dir")',
    'subprocess.getstatusoutput("explorer")',
    'subprocess.getoutput(cmd="cmd /c ver")',
    'os.popen(cmd="explorer")',
    # ":=" inside the list
    'subprocess.run([(prog := "explorer"), p])',
    # tesseract_cmd by an annotated assignment or by setattr
    't.tesseract_cmd: str = "tesseract"',
    'setattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")',
])
def test_bare_program_guard_flags(source):
    assert _bare_program_launches(source)


@pytest.mark.parametrize("source", [
    'subprocess.Popen([path, "/select,", p])',
    'subprocess.run([sys.executable, "-c", code])',
    'subprocess.Popen(["open", "-R", p])',
    'subprocess.run(["sudo", pm] + args)',
    'subprocess.run(["C:\\\\Windows\\\\System32\\\\cmd.exe"])',
    'subprocess.run(["/usr/bin/tesseract"])',
    'other.run(["explorer"])',
    'def f(p):\n    cmd = [gs, p]\n    subprocess.Popen(cmd)',
    # Bound in another function: out of reach, as the comment says.
    'def g():\n    cmd = ["explorer"]\ndef f(cmd):\n    subprocess.Popen(cmd)',
    'os.startfile(url)',
    'os.startfile("https://pdf-apps.com")',
    'os.path.join("cmd", "x")',
    'os.execve(update.current, sys.argv, env)',
    'proc.setProgram(program)\nproc.startDetached()',
    'm.start("name")',
    'cursor.execute("select 1")',
    'timer.start(100)',
    'shell32.ShellExecuteW(None, "runas", installer_path, params, None, 1)',
    't.tesseract_cmd = tess_exe or _tesseract_candidates()[0]',
    't.tesseract_cmd = "/usr/bin/tesseract"',
    't._tesseract_cmd = "tesseract"',
    'setattr(t, "other", "tesseract")',
    'subprocess.Popen([exe], executable="C:\\\\Windows\\\\explorer.exe")',
    # The third positional argument is executable only for subprocess.
    'subprocess.Popen([exe], -1, sys.executable)',
    'subprocess.run([r"C:\\x\\a.exe"], -1, "C:\\\\x\\\\a.exe")',
    'asyncio.create_subprocess_exec(exe, "/c", "dir")',
    'os.spawnl(os.P_WAIT, exe, "dir", p)',
    # Star-args before the third positional argument, or before the
    # program: where it lands is not known, so it is out of reach, as the
    # comment says.
    'subprocess.Popen(*argv, -1, "explorer.exe")',
    'os.spawnl(*a, "explorer")',
    # A URL, by its scheme
    'os.startfile("mailto:support@example.com")',
    # A module constant the function does not see: a parameter or a local
    # name hides it, and a method does not read its class's names.
    'EXE = "explorer"\ndef f(EXE):\n    subprocess.Popen([EXE])',
    # A default belongs to the last parameters, not to the first.
    'def f(exe, p="x"):\n    subprocess.Popen([exe, p])',
    ('EXE = "explorer"\ndef f():\n'
     + '    EXE = "C:\\\\Windows\\\\explorer.exe"\n    subprocess.Popen([EXE])'),
    'class A:\n    EXE = "explorer"\n    def f(self):\n        subprocess.Popen([EXE])',
])
def test_bare_program_guard_passes(source):
    assert _bare_program_launches(source) == []


def test_bare_program_guard_reports_the_executable_keyword():
    # The list names an absolute Explorer; only executable= is at fault.
    source = ('subprocess.Popen([r"C:\\x\\explorer.exe", "/select,", p],\n'
              '                 executable="explorer.exe")')
    assert _bare_program_launches(source) == [(1, "explorer.exe")]


# ---------------------------------------------------------------------------
# The Help button: no browser started by bare name on Windows
# ---------------------------------------------------------------------------

_URL = "https://pdf-apps.com/docs#first-steps"


def _no_webbrowser(monkeypatch):
    used = []
    monkeypatch.setattr(webbrowser, "open",
                        lambda *a, **k: used.append(a) or True)
    return used


def test_browser_on_windows_uses_the_shell_handler(monkeypatch):
    started = []
    used = _no_webbrowser(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "startfile", started.append, raising=False)
    monkeypatch.setenv("BROWSER", "firefox")
    opened = _browser.open(_URL)
    assert opened is True
    assert started == [_URL]
    assert used == []


def test_browser_on_windows_does_not_fall_back_to_names(monkeypatch):
    # webbrowser would go on to firefox, chrome... found by which(),
    # current folder first.
    used = _no_webbrowser(monkeypatch)

    def _no_handler(url):
        raise OSError(22, "No application is associated", url)

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "startfile", _no_handler, raising=False)
    opened = _browser.open(_URL)
    assert opened is False
    assert used == []


@pytest.mark.parametrize("plat", ["linux", "darwin"])
def test_browser_elsewhere_is_webbrowser(monkeypatch, plat):
    started = []
    used = _no_webbrowser(monkeypatch)
    monkeypatch.setattr(sys, "platform", plat)
    monkeypatch.setattr(os, "startfile", started.append, raising=False)
    opened = _browser.open(_URL)
    assert opened is True
    assert used == [(_URL,)]
    assert started == []


def test_help_button_opens_through_the_browser_module(monkeypatch, tmp_path,
                                                      qtbot):
    from PySide6.QtCore import QObject, Signal

    from app.update_controller import UpdateController
    from app.window import MainWindow

    class _NoInstanceServer(QObject):
        new_paths = Signal(list)

    monkeypatch.setattr("app.i18n._CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(UpdateController, "check_async", lambda self: None)
    monkeypatch.setattr("app.window.SingleInstanceServer", _NoInstanceServer)
    opened = []
    used = _no_webbrowser(monkeypatch)
    monkeypatch.setattr(_browser, "open", opened.append)
    win = MainWindow()
    try:
        win._help_btn.click()
    finally:
        win.close()
        win.deleteLater()
        qtbot.wait(50)
    assert opened == [_URL]
    assert used == []
