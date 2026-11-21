"""No program the installer or the uninstaller starts may come from the
current folder; and the copies of the rule and of the Windows folders
agree.

The app's side, and why, is in ``tests/test_no_cwd_executables.py``.
``installer.py`` and ``uninstaller.py`` cannot import the app, so they
keep copies: of the rule (``installer.py``), and of the Windows folder
(both, as ``app/_exe_paths.py`` has it). ``System32`` is found only by
the two scripts. One table of cases runs against every copy, the rule's
copy in ``app/tools/_ocr_paths.py`` included. The two
scripts import ``tkinter``, so these tests are skipped where it is
missing.
"""

from __future__ import annotations

import ctypes
import glob
import importlib.util
import ntpath
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import ClassVar

import pytest
from _cwd_exec_helpers import ROOT, Spy, launches_forbidden, touch, which_answer

from app import _exe_paths
from app.tools import _ocr_paths


@pytest.fixture(autouse=True)
def no_real_launches(monkeypatch):
    # _register_file_association_win swallows every Exception: the check
    # after each test is what catches a launch there.
    yield from launches_forbidden(monkeypatch)


def _load_script(stem: str):
    """installer.py or uninstaller.py as a module of its own, without
    running its ``__main__`` block, in ``sys.modules`` until the tests of
    this file are done."""
    pytest.importorskip("tkinter")
    spec = importlib.util.spec_from_file_location(
        f"_pdfapps_{stem}_under_test", ROOT / f"{stem}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Where the fixture looks for names bound to a launcher before a test
    # (see forbid_real_launches).
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        if sys.modules.get(spec.name) is module:
            del sys.modules[spec.name]


def test_the_scripts_are_where_the_fixture_looks(installer, uninstaller):
    for script in (installer, uninstaller):
        assert sys.modules[script.__name__] is script


@pytest.fixture(scope="module")
def installer():
    yield from _load_script("installer")


@pytest.fixture(scope="module")
def uninstaller():
    yield from _load_script("uninstaller")


# ---------------------------------------------------------------------------
# T5: the installer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["relative", "tesseract.BAT", "tesseract"])
def test_t5_tesseract_installed_refuses(installer, monkeypatch, tmp_path,
                                        kind):
    answer = which_answer(kind, tmp_path, monkeypatch, "tesseract")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(installer, "TESSERACT_EXE",
                        str(tmp_path / "missing" / "tesseract.exe"))
    monkeypatch.setattr(shutil, "which",
                        lambda name: answer if name == "tesseract" else None)
    assert installer.tesseract_installed() is False


def test_t5_tesseract_installed_accepts_an_absolute_exe(
        installer, monkeypatch, tmp_path):
    answer = touch(tmp_path / "bin" / "tesseract.EXE")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(installer, "TESSERACT_EXE",
                        str(tmp_path / "missing" / "tesseract.exe"))
    monkeypatch.setattr(shutil, "which", lambda name: answer)
    assert installer.tesseract_installed() is True


# Both which() calls of ghostscript_installed, one at a time.
@pytest.mark.parametrize("name", ["gswin64c", "gs"])
@pytest.mark.parametrize("kind", ["relative", "tesseract.BAT", "tesseract"])
def test_t5_ghostscript_installed_refuses(installer, monkeypatch, tmp_path,
                                          kind, name):
    answer = which_answer(kind, tmp_path, monkeypatch, name)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which",
                        lambda n: answer if n == name else None)
    monkeypatch.setattr(glob, "glob", lambda pattern: [])
    assert installer.ghostscript_installed() is False


@pytest.mark.parametrize("name", ["gswin64c", "gs"])
def test_t5_ghostscript_installed_accepts_an_absolute_exe(
        installer, monkeypatch, tmp_path, name):
    answer = touch(tmp_path / "bin" / f"{name}.EXE")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which",
                        lambda n: answer if n == name else None)
    monkeypatch.setattr(glob, "glob", lambda pattern: [])
    assert installer.ghostscript_installed() is True


def test_t5_shortcut_runs_powershell_by_full_path(installer, monkeypatch,
                                                  tmp_path):
    spy = Spy()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", spy)
    installer.create_shortcut_windows(str(tmp_path / "PDFApps.exe"),
                                      str(tmp_path / "PDFApps.lnk"))
    assert len(spy.calls) == 1
    program = spy.calls[0][0][0]
    assert ntpath.isabs(program), program
    assert program.lower().endswith(
        "\\windowspowershell\\v1.0\\powershell.exe"), program


class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_winreg():
    return types.SimpleNamespace(
        HKEY_CURRENT_USER=object(), REG_SZ=1, REG_NONE=0,
        CreateKey=lambda root, key: _FakeKey(),
        SetValueEx=lambda *a: None)


def test_t5_association_runs_ie4uinit_by_full_path(installer, monkeypatch,
                                                   tmp_path):
    spy = Spy()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg())
    monkeypatch.setattr(subprocess, "run", spy)
    installer._register_file_association_win(str(tmp_path / "PDFApps.exe"))
    # The function swallows every exception: without this, a failure
    # before the call would pass in silence.
    assert len(spy.calls) == 1
    program = spy.calls[0][0][0]
    assert ntpath.isabs(program), program
    assert program.lower().endswith("\\ie4uinit.exe"), program


# ---------------------------------------------------------------------------
# T6: the uninstaller
# ---------------------------------------------------------------------------

_TIMEOUT_LINE = re.compile(r'^"(?P<exe>[^"]+)" /t 5 /nobreak > nul$')


def _schedule(uninstaller, monkeypatch, tmp_path, name="PDFApps"):
    spy = Spy()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(subprocess, "Popen", spy)
    uninstaller._schedule_dir_removal(str(tmp_path / name))
    return spy


def test_t6_removal_runs_cmd_and_timeout_by_full_path(
        uninstaller, monkeypatch, tmp_path):
    spy = _schedule(uninstaller, monkeypatch, tmp_path)
    assert len(spy.calls) == 1
    args = spy.calls[0][0]
    assert ntpath.isabs(args[0]), args
    assert args[0].lower().endswith("\\cmd.exe"), args
    assert args[1] == "/c"
    bat = Path(args[2])
    try:
        lines = bat.read_text().splitlines()
    finally:
        bat.unlink()
    timeout = [m for m in map(_TIMEOUT_LINE.match, lines) if m]
    assert len(timeout) == 1, lines
    exe = timeout[0]["exe"]
    assert ntpath.isabs(exe) and exe.lower().endswith("\\timeout.exe"), exe
    assert not any(line.lower().startswith("timeout") for line in lines)


@pytest.mark.parametrize("bad", ["\r", "\n", '"', "%", "&", "|", "<", ">",
                                 "^"])
def test_t6_install_dir_unsafe_in_a_bat_schedules_nothing(
        uninstaller, monkeypatch, tmp_path, bad):
    # The folder goes into the BAT between quotes; any of these would let
    # it out of its quotes or of its line.
    spy = _schedule(uninstaller, monkeypatch, tmp_path, f"PDF{bad}Apps")
    assert spy.calls == []
    assert list(tmp_path.glob("pdfapps_*.bat")) == []


# ---------------------------------------------------------------------------
# T9: the copies of the rule agree
# ---------------------------------------------------------------------------

def _rule_copies(installer):
    return {
        "app._exe_paths": _exe_paths.is_usable_executable,
        "app.tools._ocr_paths": _ocr_paths._is_usable_executable,
        "installer": installer._is_usable_executable,
    }


def _rule_cases(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exe = touch(tmp_path / "abs" / "prog.exe")
    upper = touch(tmp_path / "abs" / "PROG.EXE")
    bare = touch(tmp_path / "abs" / "prog")
    touch(tmp_path / "rel.exe")
    # A folder passes every other check: it exists, and this one even has
    # the suffix. Only "an existing file" refuses both.
    folder_exe = tmp_path / "abs" / "dir.exe"
    folder_exe.mkdir()
    cases = [
        (None, True, False),
        ("", True, False),
        ("rel.exe", True, False),
        (os.path.join(".", "rel.exe"), True, False),
        (str(tmp_path / "abs" / "missing.exe"), True, False),
        (str(tmp_path / "abs"), True, False),  # a folder
        (str(folder_exe), True, False),
        (str(tmp_path / "abs"), False, False),
        (exe, True, True),
        (upper, True, True),
        (bare, True, False),
        (bare, False, True),
        ("rel.exe", False, False),
    ]
    for suffix in (".bat", ".cmd", ".com", ".vbs", ".js", ".ws", ".msc"):
        other = touch(tmp_path / "abs" / f"prog{suffix}")
        cases += [(other, True, False), (other, False, True)]
    if sys.platform == "win32":
        cases.append((os.path.splitdrive(exe)[1], True, False))
    return cases


def test_t9_rule_copies_agree(installer, monkeypatch, tmp_path):
    cases = _rule_cases(tmp_path, monkeypatch)
    wrong = [
        (copy, path, windows)
        for copy, rule in _rule_copies(installer).items()
        for path, windows, expected in cases
        if rule(path, windows=windows) is not expected
    ]
    assert wrong == []


# ---------------------------------------------------------------------------
# T9 and T10: the Windows folders, with a fake kernel32, in every copy
# ---------------------------------------------------------------------------

_SHARED = "W:\\Partilhada"
# Not _SHARED plus System32: a copy that built System32 from the Windows
# folder instead of asking GetSystemDirectoryW would give the same path.
_SYSTEM = "Y:\\Sistema"
_PRIVATE = "P:\\Privada"
_ROOT_VAR = "S:\\Raiz"
# Longer than MAX_PATH (260): a buffer of that size would not hold it.
_LONG = "W:\\" + "x" * 300

_HOW = ["zero", "too_small", "relative", "drive_relative", "no_drive"]


class _FakeKernel32:
    """kernel32 with the three folder functions, each writing its own
    value into the buffer it is given. *broken* names the functions that
    misbehave, and how."""

    _VALUES: ClassVar[dict[str, str]] = {
        "GetSystemWindowsDirectoryW": _SHARED,
        "GetSystemDirectoryW": _SYSTEM,
        "GetWindowsDirectoryW": _PRIVATE,
    }

    def __init__(self, broken: dict[str, str] | None = None):
        self.calls: list[str] = []
        self.functions = {}
        for name, value in self._VALUES.items():
            self.functions[name] = self._function(
                name, value, (broken or {}).get(name))

    def _function(self, name, value, how):
        def func(buf, size):
            self.calls.append(name)
            assert size == len(buf)
            # A failed call may leave a path-like value in the buffer: only
            # the returned length says whether it is the answer.
            if how == "zero":
                buf.value = "W:\\Lixo"
                return 0
            if how == "too_small":
                buf.value = "W:\\Parti"
                return size  # the size it would need
            written = {None: value, "relative": "Windows",
                       "drive_relative": "C:Windows",
                       "no_drive": "\\Partilhada", "long": _LONG}[how]
            if len(written) >= size:
                # As the API does: the size it needs, the NUL included.
                return len(written) + 1
            buf.value = written
            return len(written)
        func.__name__ = name
        return func

    def __getattr__(self, name):
        try:
            return self.__dict__["functions"][name]
        except KeyError:
            raise AttributeError(name) from None


# Each copy of the Windows folder, and of System32 where there is one:
# the app has no System32 copy, as it starts nothing from there.
_COPIES = ["app._exe_paths", "installer", "uninstaller"]
_SYSTEM32_COPIES = ["installer", "uninstaller"]


@pytest.fixture
def copies(installer, uninstaller):
    return {
        "app._exe_paths": (_exe_paths.windows_dir, None),
        "installer": (installer._windows_dir, installer._system32_dir),
        "uninstaller": (uninstaller._windows_dir, uninstaller._system32_dir),
    }


def _use_kernel32(monkeypatch, fake):
    monkeypatch.setattr(ctypes, "windll",
                        types.SimpleNamespace(kernel32=fake), raising=False)


def _isabs_as_python_312(monkeypatch):
    """ntpath.isabs as Python 3.12 has it, which still calls a path with
    a root and no drive (``\\Windows``) absolute; 3.13 stopped."""
    real = ntpath.isabs
    monkeypatch.setattr(
        ntpath, "isabs",
        lambda p: real(p) or os.fspath(p).replace("/", "\\").startswith("\\"))


def _kernel32_cases():
    """No kernel32; a sound one; and each way of misbehaving, in the
    Windows folder function, in the System32 one, and in both."""
    yield "no kernel32", None
    yield "sound", {}
    yield "windows long", {"GetSystemWindowsDirectoryW": "long"}
    yield "system32 long", {"GetSystemDirectoryW": "long"}
    for how in _HOW:
        yield f"windows {how}", {"GetSystemWindowsDirectoryW": how}
        yield f"system32 {how}", {"GetSystemDirectoryW": how}
        yield f"both {how}", {"GetSystemWindowsDirectoryW": how,
                              "GetSystemDirectoryW": how}


@pytest.mark.parametrize("isabs", ["current", "python_312"])
def test_t9_folder_copies_agree(copies, monkeypatch, isabs):
    if isabs == "python_312":
        _isabs_as_python_312(monkeypatch)
    disagree = []
    for label, broken in _kernel32_cases():
        if broken is None:
            monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(),
                                raising=False)
        else:
            _use_kernel32(monkeypatch, _FakeKernel32(broken))
        for root in (None, _ROOT_VAR, "C:", "\\Windows"):
            if root is None:
                monkeypatch.delenv("SystemRoot", raising=False)
            else:
                monkeypatch.setenv("SystemRoot", root)
            windows = {c: copies[c][0]() for c in _COPIES}
            system32 = {c: copies[c][1]() for c in _SYSTEM32_COPIES}
            for answers in (windows, system32):
                if len(set(answers.values())) != 1:
                    disagree.append((label, root, answers))
    assert disagree == []


@pytest.mark.parametrize("copy", _COPIES)
def test_t10_folders_come_from_the_shared_windows_folder(
        copies, monkeypatch, copy):
    fake = _FakeKernel32()
    _use_kernel32(monkeypatch, fake)
    monkeypatch.setenv("SystemRoot", _ROOT_VAR)
    windows_dir, system32_dir = copies[copy]
    assert windows_dir() == _SHARED
    if system32_dir is not None:
        assert system32_dir() == _SYSTEM
    assert "GetSystemWindowsDirectoryW" in fake.calls
    assert "GetWindowsDirectoryW" not in fake.calls
    # No argtypes or restype on the shared ctypes.windll functions.
    for func in fake.functions.values():
        assert not hasattr(func, "argtypes"), func.__name__
        assert not hasattr(func, "restype"), func.__name__


@pytest.mark.parametrize("copy", _COPIES)
def test_t10_a_folder_longer_than_max_path_is_kept(copies, monkeypatch,
                                                  copy):
    # Holds the size of each buffer: one of 260 would get back the size it
    # needs, refuse the answer and fall back to SystemRoot.
    _use_kernel32(monkeypatch, _FakeKernel32(
        {"GetSystemWindowsDirectoryW": "long", "GetSystemDirectoryW": "long"}))
    monkeypatch.setenv("SystemRoot", _ROOT_VAR)
    windows_dir, system32_dir = copies[copy]
    assert windows_dir() == _LONG
    if system32_dir is not None:
        assert system32_dir() == _LONG


@pytest.mark.parametrize("copy", _COPIES)
@pytest.mark.parametrize("how", _HOW)
def test_t10_an_unusable_answer_falls_back_to_systemroot(
        copies, monkeypatch, copy, how):
    fake = _FakeKernel32({"GetSystemWindowsDirectoryW": how,
                          "GetSystemDirectoryW": how})
    _use_kernel32(monkeypatch, fake)
    monkeypatch.setenv("SystemRoot", _ROOT_VAR)
    windows_dir, system32_dir = copies[copy]
    assert windows_dir() == _ROOT_VAR
    if system32_dir is not None:
        assert system32_dir() == ntpath.join(_ROOT_VAR, "System32")


@pytest.mark.parametrize("copy", _COPIES)
@pytest.mark.parametrize("system_root", [None, "C:", "\\Windows"],
                         ids=["unset", "drive_only", "no_drive"])
def test_t10_last_resort_is_c_windows(copies, monkeypatch, copy,
                                      system_root):
    # No kernel32 at all, as off Windows.
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(),
                        raising=False)
    if system_root is None:
        monkeypatch.delenv("SystemRoot", raising=False)
    else:
        monkeypatch.setenv("SystemRoot", system_root)
    windows_dir, system32_dir = copies[copy]
    explorer = ntpath.join(windows_dir(), "explorer.exe")
    assert explorer == "C:\\Windows\\explorer.exe"
    assert ntpath.isabs(explorer)
    if system32_dir is not None:
        assert system32_dir() == "C:\\Windows\\System32"


@pytest.mark.parametrize("copy", _COPIES)
def test_t10_a_folder_without_drive_is_refused_as_on_python_312(
        copies, monkeypatch, copy):
    # Under 3.14 ntpath.isabs alone refuses \Partilhada; under 3.12 only
    # the drive check does.
    _isabs_as_python_312(monkeypatch)
    assert ntpath.isabs("\\Partilhada")
    _use_kernel32(monkeypatch, _FakeKernel32(
        {"GetSystemWindowsDirectoryW": "no_drive",
         "GetSystemDirectoryW": "no_drive"}))
    monkeypatch.setenv("SystemRoot", _ROOT_VAR)
    windows_dir, system32_dir = copies[copy]
    assert windows_dir() == _ROOT_VAR
    if system32_dir is not None:
        assert system32_dir() == ntpath.join(_ROOT_VAR, "System32")
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace())
    monkeypatch.setenv("SystemRoot", "\\Windows")
    assert windows_dir() == "C:\\Windows"


def test_t10_explorer_and_system_programs_use_those_folders(
        installer, uninstaller, monkeypatch, tmp_path):
    fake = _FakeKernel32()
    _use_kernel32(monkeypatch, fake)
    monkeypatch.setenv("SystemRoot", _ROOT_VAR)
    assert _exe_paths.windows_path("explorer.exe") == _SHARED + "\\explorer.exe"

    spy = Spy()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", spy)
    installer.create_shortcut_windows(str(tmp_path / "a.exe"),
                                      str(tmp_path / "a.lnk"))
    assert spy.calls[0][0][0] == (
        _SYSTEM + "\\WindowsPowerShell\\v1.0\\powershell.exe")

    spy = _schedule(uninstaller, monkeypatch, tmp_path)
    args = spy.calls[0][0]
    assert args[0] == _SYSTEM + "\\cmd.exe"
    bat = Path(args[2])
    try:
        text = bat.read_text()
    finally:
        bat.unlink()
    assert f'"{_SYSTEM}\\timeout.exe" /t 5 /nobreak > nul' in text.splitlines()


def test_t10_a_system_folder_unsafe_in_a_bat_schedules_nothing(
        uninstaller, monkeypatch, tmp_path):
    class _Odd(_FakeKernel32):
        _VALUES: ClassVar[dict[str, str]] = {
            **_FakeKernel32._VALUES, "GetSystemDirectoryW": "W:\\Odd&Dir"}
    _use_kernel32(monkeypatch, _Odd())
    spy = _schedule(uninstaller, monkeypatch, tmp_path)
    assert spy.calls == []
    assert list(tmp_path.glob("pdfapps_*.bat")) == []
