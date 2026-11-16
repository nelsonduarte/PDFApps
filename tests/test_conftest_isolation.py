"""The suite runs in a fake home, never in the one of whoever runs it.

tests/conftest.py sets this up before any test module imports ``app``.
Before it, ``app.i18n`` read the real config at import time,
``PdfViewerPanel`` rewrote the real recent files, and the language of a
local run was the developer's. These tests pin the isolation itself;
the conftest also fails the session closed when the config paths escape.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _font_install_recorder import FontInstallRecorder

from app import constants, i18n

REPO_ROOT = Path(__file__).resolve().parent.parent

_HOME_VARS = (
    "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME",
    "PDFAPPS_TEST_HOME",
)

# For every child below, and for every git command. The git tests run git
# before or after their child, so the two together stay below the CI's
# faulthandler_timeout (300 s in .github/workflows/tests.yml, which also
# ends the run): a hung child or git fails its test, not the whole job.
# Checked against the workflow by
# test_the_child_timeout_stays_below_the_ci_faulthandler_timeout.
_CHILD_TIMEOUT = 120
_GIT_TIMEOUT = 60


def _real_home() -> str:
    """The account's home, whatever the environment says."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        # FOLDERID_Profile {5E6C858F-0E22-4760-9AFE-EA3317B67173}; resolved
        # from the user's token and registry, not from USERPROFILE.
        guid = _GUID(0x5E6C858F, 0x0E22, 0x4760,
                     (ctypes.c_ubyte * 8)(0x9A, 0xFE, 0xEA, 0x33,
                                          0x17, 0xB6, 0x71, 0x73))
        out = ctypes.c_wchar_p()
        # A private WinDLL: argtypes set on the shared ctypes.windll object
        # would leak into every other user of shell32 in the process.
        shell32 = ctypes.WinDLL("shell32")
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p)]
        hr = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                          ctypes.byref(out))
        try:
            assert hr == 0, f"SHGetKnownFolderPath failed: 0x{hr & 0xFFFFFFFF:08X}"
            return str(out.value)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
    import pwd
    return pwd.getpwuid(os.getuid()).pw_dir


def _same(a, b) -> bool:
    return (os.path.normcase(os.path.realpath(a))
            == os.path.normcase(os.path.realpath(b)))


# ── T-ISO-1 ──


def test_every_home_variable_points_into_the_fake_home(pdfapps_isolation):
    root, inside = pdfapps_isolation.root, pdfapps_isolation.inside
    marker = os.environ.get("PDFAPPS_TEST_HOME")
    assert marker, "PDFAPPS_TEST_HOME is not set: tests/conftest.py did not isolate"
    assert os.path.isdir(marker)
    assert _same(marker, root)
    for name in _HOME_VARS:
        value = os.environ.get(name)
        assert value, f"{name} is not set"
        assert inside(value, root), f"{name} = {value} is outside {root}"
    if sys.platform == "win32":
        # Where Git for Windows takes ~ from when HOME is unset.
        drive, path = os.environ.get("HOMEDRIVE"), os.environ.get("HOMEPATH")
        assert drive is not None and path is not None, (drive, path)
        assert inside(drive + path, root), f"HOMEDRIVE+HOMEPATH = {drive + path}"


def test_the_app_paths_are_inside_the_fake_home(pdfapps_isolation):
    root, inside = pdfapps_isolation.root, pdfapps_isolation.inside
    paths = {
        "_CONFIG_PATH": i18n._CONFIG_PATH,
        "_SIGNATURE_PATH": i18n._SIGNATURE_PATH,
        "_LEGACY_CONFIG": i18n._LEGACY_CONFIG,
        "_LEGACY_SIGNATURE": i18n._LEGACY_SIGNATURE,
        "expanduser('~')": os.path.expanduser("~"),
    }
    # In the snap DESKTOP is the real home on purpose (SNAP_REAL_HOME).
    if "SNAP" not in os.environ:
        paths["constants.DESKTOP"] = constants.DESKTOP
    for name, value in paths.items():
        assert inside(value, root), f"{name} = {value} is outside {root}"


def test_inside_compares_whole_path_components(tmp_path, pdfapps_isolation):
    inside = pdfapps_isolation.inside
    root = tmp_path / "b"
    root.mkdir()
    assert inside(root, root)
    assert inside(str(root / "x" / "y.txt"), root)  # need not exist
    assert not inside(tmp_path, root)
    assert not inside(tmp_path / "other", root)
    # A sibling whose name starts with the root's: /a/bc is not in /a/b.
    assert not inside(tmp_path / "bc" / "x", root)
    # A drive or filesystem root as the root needs no doubled separator.
    assert inside(tmp_path, Path(tmp_path.anchor))
    # Case is folded on Windows only. There realpath already gives a folder
    # that exists in its stored case; normcase covers a tail that does not
    # exist.
    assert inside(tmp_path / "B" / "x", root) == (sys.platform == "win32")
    assert (inside(root / "NEW" / "x", root / "New")
            == (sys.platform == "win32"))


# ── T-ISO-2 (defence in depth: passes with the old conftest in a run
# already isolated from outside, bites only in CI or a plain local run) ──


def test_the_config_is_not_the_real_one():
    real = _real_home()
    assert not _same(os.path.expanduser("~"), real)
    assert not _same(i18n._CONFIG_PATH, os.path.join(real, ".pdfapps_config.json"))
    # Not "outside the real home": on Windows TEMP, and the fake home with
    # it, is inside the profile.
    real_xdg = os.path.normcase(os.path.realpath(
        os.path.join(real, ".config", "pdfapps")))
    assert not os.path.normcase(os.path.realpath(i18n._CONFIG_PATH)).startswith(
        real_xdg + os.sep)


# ── T-ISO-3 ──


_CHILD = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
from app import i18n
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    fh.write(i18n._CONFIG_PATH + "\n" + os.environ.get("LOCALAPPDATA", "") + "\n")
"""


def test_child_processes_inherit_the_fake_home(tmp_path, pdfapps_isolation):
    root, inside = pdfapps_isolation.root, pdfapps_isolation.inside
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    out = tmp_path / "seen.txt"
    subprocess.run([sys.executable, "-I", str(script), str(REPO_ROOT), str(out)],
                   check=True, timeout=_CHILD_TIMEOUT)
    config_path, localappdata = out.read_text(encoding="utf-8").splitlines()
    assert inside(config_path, root), config_path
    assert inside(localappdata, root), localappdata


# ── T-ISO-4 ──


def _child_env(tmp_path, plugin_name, plugin_src, extra_env):
    """The environment of a child pytest, with a TEMP of its own.

    ``plugin_src`` is written as module ``plugin_name`` where the child
    imports it from, for ``-p``. The child's tests/conftest.py makes its
    fake home in ``tmp_path / "t"``. An ``extra_env`` value of None
    removes that variable. Returns the environment and that TEMP.
    """
    temp = tmp_path / "t"
    temp.mkdir()
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / f"{plugin_name}.py").write_text(plugin_src, encoding="utf-8")
    env = dict(os.environ)
    # A -k or -m of the outer run would deselect the child's tests.
    env.pop("PYTEST_ADDOPTS", None)
    # Set by the child's conftest once its folder exists, so a record that
    # names one proves that conftest ran. The home variables it inherits
    # from this session are overwritten there before anything reads them.
    env.pop("PDFAPPS_TEST_HOME", None)
    env.update(TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp),
               PYTHONPATH=os.pathsep.join(
                   p for p in (str(plugin), env.get("PYTHONPATH")) if p),
               # Read back as UTF-8 below: on Windows a child otherwise
               # writes to a pipe in the ANSI code page, which has no
               # character for most of a non-ASCII path.
               PYTHONIOENCODING="utf-8")
    for name, value in extra_env.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return env, temp


def _child_pytest(tmp_path, plugin_name, plugin_src, args, **extra_env):
    """Run pytest in a child, from the repo (see _child_env).

    The plugin is loaded with ``-p``, so it is imported before the child's
    tests/conftest.py. Returns the process and the child's TEMP.
    """
    env, temp = _child_env(tmp_path, plugin_name, plugin_src, extra_env)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-p", plugin_name, *args],
        cwd=str(REPO_ROOT), env=env, capture_output=True, encoding="utf-8",
        errors="backslashreplace", timeout=_CHILD_TIMEOUT, check=False)
    return proc, temp


_PYTEST_COMMAND = re.compile(r"(?:^|\s)pytest(?:\s|$)")
# A number as written, quoted or not; not one followed by ${{ ... }} or $VAR.
_LITERAL_TIMEOUT = re.compile(r"faulthandler_timeout=(\d+)(?=[\s'\"]|$)")


def test_the_child_timeout_stays_below_the_ci_faulthandler_timeout():
    # Inside a test function: PyYAML is imported here, not at collection.
    from _workflow_steps import load_workflow

    workflow = load_workflow("tests.yml")
    # Per step that runs pytest. Numbered: two steps may share a name, or
    # have none, and one would hide the other.
    timeouts: dict[str, list[int]] = {}
    for name, job in workflow["jobs"].items():
        for number, step in enumerate(job.get("steps", []), 1):
            # A shell comment that names pytest does not run it.
            lines = [line for line in (step.get("run") or "").splitlines()
                     if not line.lstrip().startswith("#")]
            if any(_PYTEST_COMMAND.search(line) for line in lines):
                timeouts[f"{name} step {number} ({step.get('name')})"] = [
                    int(t) for line in lines for t in _LITERAL_TIMEOUT.findall(line)]
    assert timeouts, "no step of tests.yml runs pytest"
    # Each run is checked, not only the shortest: a run without the option
    # has no timeout at all.
    unset = [key for key, values in timeouts.items() if not values]
    assert not unset, f"no faulthandler_timeout written in {unset}: {timeouts}"
    # Only numbers written in those commands are read here. One from an
    # env, an expression, a shell variable or PYTEST_ADDOPTS (which an
    # earlier step can also set through $GITHUB_ENV) would go unchecked.
    text = repr(workflow)
    found = [t for values in timeouts.values() for t in values]
    assert text.count("faulthandler_timeout") == len(found), (
        f"tests.yml names faulthandler_timeout {text.count('faulthandler_timeout')} "
        f"times, but only {len(found)} are numbers in a pytest command: {timeouts}")
    assert "PYTEST_ADDOPTS" not in text, (
        "tests.yml sets PYTEST_ADDOPTS, which can change faulthandler_timeout "
        "where this test does not look")
    assert min(found) > _CHILD_TIMEOUT + _GIT_TIMEOUT, (
        f"_CHILD_TIMEOUT + _GIT_TIMEOUT = {_CHILD_TIMEOUT + _GIT_TIMEOUT} s, but "
        f"tests.yml ends the run after {min(found)} s ({timeouts}): a hung "
        "child or git would fail the whole job")


def test_the_suite_runs_in_english():
    # Passes without the pin wherever app.i18n detects English, as on the
    # CI runners; fails if an earlier test left _LANG changed.
    assert i18n._LANG == "en", (
        f"app.i18n._LANG is {i18n._LANG!r}: either tests/conftest.py did not "
        "pin it, or an earlier test changed it without monkeypatch")


def test_the_conftest_pins_the_language(monkeypatch, pdfapps_isolation):
    # The function the conftest runs sets English from another language.
    # Not that the conftest runs it: the next test covers that.
    monkeypatch.setattr(i18n, "_LANG", "pt")
    pdfapps_isolation.pin_language()
    assert i18n._LANG == "en"


_SYSTEM_IN_PORTUGUESE = r"""
import locale
import os

# Imported before tests/conftest.py, and so before app.i18n: its detection
# reads locale.getlocale() on Linux and macOS, and on Windows when its
# table of Windows UI languages does not map the one in use, English
# included (one it maps is taken first, and is not English either).
locale.getlocale = lambda *args, **kwargs: ("pt_PT", "UTF-8")


def pytest_sessionfinish(session):
    from app import i18n

    with open(os.environ["PDFAPPS_RECORD_LANG"], "w", encoding="utf-8") as fh:
        fh.write(i18n._detect_system_language() + "\n")
"""


def test_a_session_on_a_non_english_system_runs_in_english(tmp_path):
    record = tmp_path / "lang.txt"
    proc, _ = _child_pytest(
        tmp_path, "pdfapps_system_in_portuguese", _SYSTEM_IN_PORTUGUESE,
        ["tests/test_conftest_isolation.py::test_the_suite_runs_in_english"],
        PDFAPPS_RECORD_LANG=str(record))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # Without the pin the child would not have been in English: otherwise
    # its pass above would prove nothing.
    assert record.read_text(encoding="utf-8").strip() != "en"


# ── the fake home does not outlive the session ──


_RECORD_ROOT = r"""
import os

import pytest


def pytest_sessionfinish(session):
    root = os.environ["PDFAPPS_TEST_HOME"]
    with open(os.environ["PDFAPPS_RECORD_ROOT"], "w", encoding="utf-8") as fh:
        fh.write(f"{root}\n{os.path.isdir(root)}\n")


# After the conftest's pytest_unconfigure, before its atexit handler,
# which would remove the folder too.
@pytest.hookimpl(wrapper=True)
def pytest_unconfigure(config):
    yield
    root = os.environ["PDFAPPS_TEST_HOME"]
    with open(os.environ["PDFAPPS_RECORD_ROOT"], "a", encoding="utf-8") as fh:
        fh.write(f"{os.path.isdir(root)}\n")
"""


def test_a_session_removes_its_fake_home(tmp_path):
    record = tmp_path / "root.txt"
    # A test that does not read the language, so that a broken pin (the
    # child would take the system's) fails only the tests about the pin.
    node = ("tests/test_conftest_isolation.py"
            "::test_every_home_variable_points_into_the_fake_home")
    proc, temp = _child_pytest(tmp_path, "pdfapps_record_root", _RECORD_ROOT,
                               [node], PDFAPPS_RECORD_ROOT=str(record))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    root, existed, after_unconfigure = record.read_text(
        encoding="utf-8").splitlines()
    # The child really used this TEMP: otherwise an empty folder below
    # would prove nothing.
    assert _same(os.path.dirname(root), temp), root
    assert existed == "True", root
    # Removed by pytest_unconfigure, the only cleanup for a process that
    # runs pytest.main() and goes on.
    assert after_unconfigure == "False", root
    assert not list(temp.glob("pdfapps-test-home-*")), os.listdir(temp)


_RECORD_ROOT_AT_EXIT = r"""
import atexit
import os


# Registered before the conftest's own handler, so it runs after it.
@atexit.register
def _record():
    root = os.environ.get("PDFAPPS_TEST_HOME", "")
    with open(os.environ["PDFAPPS_RECORD_ROOT"], "w", encoding="utf-8") as fh:
        fh.write(root + "\n")
"""


def test_a_usage_error_removes_the_fake_home(tmp_path):
    # pytest parses the options after loading the conftest, and on a usage
    # error never calls pytest_unconfigure.
    record = tmp_path / "root.txt"
    proc, temp = _child_pytest(
        tmp_path, "pdfapps_record_root_at_exit", _RECORD_ROOT_AT_EXIT,
        ["tests/test_conftest_isolation.py", "--pdfapps-no-such-option"],
        PDFAPPS_RECORD_ROOT=str(record))
    assert proc.returncode == pytest.ExitCode.USAGE_ERROR, proc.stdout + proc.stderr
    # A conftest that raises on import exits with the same status, and its
    # own except clause removes the folder without the atexit handler.
    assert "--pdfapps-no-such-option" in proc.stderr, proc.stdout + proc.stderr
    root = record.read_text(encoding="utf-8").strip()
    # The child's conftest ran and made its folder in this TEMP.
    assert root and _same(os.path.dirname(root), temp), root
    assert not list(temp.glob("pdfapps-test-home-*")), os.listdir(temp)


# ── the conftest fails closed ──


_HOME_ESCAPES = _RECORD_ROOT_AT_EXIT + r"""

_expanduser = os.path.expanduser


def _escaped(path):
    text = os.fspath(path)
    if isinstance(text, str) and (text == "~" or text.startswith(("~/", "~\\"))):
        return os.environ["PDFAPPS_OUTSIDE_HOME"] + text[1:]
    return _expanduser(path)


# Before the child's tests/conftest.py: whatever it sets, "~" now expands
# to a folder outside its fake home, and so do the app.i18n paths.
os.path.expanduser = _escaped
"""


def test_a_home_that_escapes_fails_the_session_closed(tmp_path):
    outside = tmp_path / "outside home"
    outside.mkdir()
    record = tmp_path / "root.txt"
    # A test that passes with any home, so only the conftest can fail it.
    node = ("tests/test_conftest_isolation.py"
            "::test_the_conftest_pins_the_language")
    proc, temp = _child_pytest(tmp_path, "pdfapps_home_escapes", _HOME_ESCAPES,
                               [node], PDFAPPS_OUTSIDE_HOME=str(outside),
                               PDFAPPS_RECORD_ROOT=str(record))
    out = proc.stdout + proc.stderr
    assert proc.returncode == pytest.ExitCode.USAGE_ERROR, out
    assert "could not isolate the suite from the real home" in out, out
    assert f'os.path.expanduser("~") = {outside}' in out, out
    root = record.read_text(encoding="utf-8").strip()
    assert root and _same(os.path.dirname(root), temp), root
    assert not list(temp.glob("pdfapps-test-home-*")), os.listdir(temp)
    assert list(outside.iterdir()) == []


_PYTEST_MAIN_TWICE = r"""
import os
import sys

import pytest

record, temp, *args = sys.argv[1:]
lines = []
for _ in range(2):
    code = pytest.main(args)
    root = os.environ.get("PDFAPPS_TEST_HOME", "")
    lines.append(f"{int(code)}\n{root}\n{bool(root) and os.path.isdir(root)}")
# Still before the atexit handlers: only what pytest.main() removed is gone.
left = [n for n in os.listdir(temp) if n.startswith("pdfapps-test-home-")]
with open(record, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + f"\n{left}\n")
"""


def _pytest_main_twice(tmp_path, plugin_name, plugin_src, node, **extra_env):
    """Call pytest.main() twice in one child, from the repo.

    Returns the process; for each call, its exit code, the
    PDFAPPS_TEST_HOME it left in os.environ (checked to be in the child's
    TEMP) and whether that folder still existed when the call returned;
    and the fake homes left in that TEMP before the atexit handlers ran.
    """
    env, temp = _child_env(tmp_path, plugin_name, plugin_src, extra_env)
    script = tmp_path / "twice.py"
    script.write_text(_PYTEST_MAIN_TWICE, encoding="utf-8")
    record = tmp_path / "twice.txt"
    # Not -I: see test_a_forked_child_leaves_the_fake_home_alone.
    proc = subprocess.run(
        [sys.executable, "-B", str(script), str(record), str(temp),
         "-q", "-p", "no:cacheprovider", "-p", plugin_name, node],
        cwd=str(REPO_ROOT), env=env, capture_output=True, encoding="utf-8",
        errors="backslashreplace", timeout=_CHILD_TIMEOUT, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    code1, root1, existed1, code2, root2, existed2, left = record.read_text(
        encoding="utf-8").splitlines()
    for root in (root1, root2):
        # The child's conftest ran and made its folder in this TEMP.
        assert root and _same(os.path.dirname(root), temp), root
    return proc, (int(code1), root1, existed1), (int(code2), root2, existed2), left


def test_a_conftest_that_fails_removes_its_folder_before_pytest_main_returns(
        tmp_path):
    # The atexit handler runs only when the interpreter exits; a process
    # that calls pytest.main() and goes on depends on the except clause.
    outside = tmp_path / "outside home"
    outside.mkdir()
    node = ("tests/test_conftest_isolation.py"
            "::test_the_conftest_pins_the_language")
    proc, first, second, left = _pytest_main_twice(
        tmp_path, "pdfapps_home_escapes", _HOME_ESCAPES, node,
        PDFAPPS_OUTSIDE_HOME=str(outside),
        PDFAPPS_RECORD_ROOT=str(tmp_path / "root.txt"))
    out = proc.stdout + proc.stderr
    assert first[0] == second[0] == pytest.ExitCode.USAGE_ERROR, out
    assert "could not isolate the suite from the real home" in out, out
    assert first[2] == second[2] == "False", (first, second)
    assert left == "[]", left


def test_a_second_pytest_main_in_the_same_process_fails_closed(tmp_path):
    # pytest_unconfigure removes the folder and leaves the environment
    # naming it. The second call runs the conftest again, but app.i18n
    # keeps the first folder's paths, so that session must stop before
    # any test, never run against a home that is gone or the real one.
    node = ("tests/test_conftest_isolation.py"
            "::test_every_home_variable_points_into_the_fake_home")
    proc, first, second, left = _pytest_main_twice(
        tmp_path, "pdfapps_nothing", "", node)
    out = proc.stdout + proc.stderr
    assert first[0] == pytest.ExitCode.OK, out
    assert first[2] == "False", first
    assert second[0] == pytest.ExitCode.USAGE_ERROR, out
    assert f"app.i18n._CONFIG_PATH = {first[1]}" in out, out
    assert not _same(second[1], first[1]), (first, second)
    assert second[2] == "False", second
    assert left == "[]", left


_FORK = r"""
import importlib.util
import os
import sys

spec = importlib.util.spec_from_file_location("pdfapps_conftest", sys.argv[1])
conftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conftest)
pid = os.fork()
if pid == 0:
    # A normal exit: the child runs the atexit handlers it inherited.
    sys.exit(0)
os.waitpid(pid, 0)
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    fh.write(f"{conftest._ROOT}\n{os.path.isdir(conftest._ROOT)}\n")
"""


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs os.fork")
def test_a_forked_child_leaves_the_fake_home_alone(tmp_path):
    temp = tmp_path / "t"
    temp.mkdir()
    script = tmp_path / "fork.py"
    script.write_text(_FORK, encoding="utf-8")
    record = tmp_path / "root.txt"
    # PYTHONIOENCODING: see _child_pytest.
    env = dict(os.environ, TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp),
               PYTHONIOENCODING="utf-8")
    # Not -I: it turns the user site off, and a Python outside a venv with
    # pytest from `pip install --user` would then fail on the import.
    proc = subprocess.run([sys.executable, "-B", str(script),
                           str(REPO_ROOT / "tests" / "conftest.py"), str(record)],
                          env=env, capture_output=True, encoding="utf-8",
                          errors="backslashreplace", timeout=_CHILD_TIMEOUT,
                          check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    root, existed = record.read_text(encoding="utf-8").splitlines()
    assert _same(os.path.dirname(root), temp), root
    assert existed == "True", root
    # The parent's own exit still removes it.
    assert not list(temp.glob("pdfapps-test-home-*")), os.listdir(temp)


# ── T-ISO-5 ──


@pytest.mark.skipif(sys.platform != "win32",
                    reason="qtawesome installs fonts only on Windows")
def test_qtawesome_finds_its_fonts_and_installs_nothing(monkeypatch,
                                                         pdfapps_isolation):
    root, inside = pdfapps_isolation.root, pdfapps_isolation.inside
    iconic_font = pytest.importorskip("qtawesome.iconic_font")
    # Checked first so a run that leaked the real LOCALAPPDATA never even
    # reaches qtawesome, recorders or not.
    assert inside(os.environ["LOCALAPPDATA"], root), os.environ["LOCALAPPDATA"]

    # The fonts folder as the conftest found it before any test ran. By
    # now an earlier test may have drawn an icon, and qtawesome would then
    # have filled the folder itself (writing to the real GDI and HKCU), so
    # what is there now proves nothing about the conftest.
    shipped = sorted(
        f for _, _, files in os.walk(
            Path(os.path.realpath(iconic_font.__file__)).parent / "fonts")
        for f in files)
    assert shipped, "qtawesome ships no fonts: nothing below would be measured"
    # The conftest looked at the same folder qtawesome installs from.
    assert list(pdfapps_isolation.qta_fonts) == shipped
    assert pdfapps_isolation.qta_fonts_missing_at_start == (), (
        "tests/conftest.py did not put these qtawesome fonts in the fake "
        f"LOCALAPPDATA: {pdfapps_isolation.qta_fonts_missing_at_start}")

    calls: list = []
    # raising=True: if a qtawesome release renames these, fail loudly
    # instead of passing without measuring anything.
    monkeypatch.setattr(iconic_font, "gdi32",
                        FontInstallRecorder("gdi32", calls), raising=True)
    monkeypatch.setattr(iconic_font, "winreg",
                        FontInstallRecorder("winreg", calls), raising=True)

    font = iconic_font.IconicFont.__new__(iconic_font.IconicFont)
    fonts_dir = font._get_fonts_directory()

    assert calls == []
    assert inside(fonts_dir, root), fonts_dir


# ── the global git config ──


def _git_global_targets() -> list[str]:
    """The files `git config --global` would write to, found as git does.

    GIT_CONFIG_GLOBAL alone when set. Otherwise ~/.gitconfig and
    $XDG_CONFIG_HOME/git/config, either of which git may write to, with ~
    from HOME; without HOME, Git for Windows takes HOMEDRIVE+HOMEPATH when
    that is a folder and USERPROFILE after it, and any other git has no ~
    and refuses to write. An empty ~ is the root of the disk: refused.
    """
    target = os.environ.get("GIT_CONFIG_GLOBAL")
    if target is not None:
        return [target]
    home, source = os.environ.get("HOME"), "HOME"
    if home is None and sys.platform == "win32":
        drive, path = os.environ.get("HOMEDRIVE"), os.environ.get("HOMEPATH")
        if drive is not None and path is not None and os.path.isdir(drive + path):
            home = drive + path
        else:
            home = os.environ.get("USERPROFILE")
            source = "USERPROFILE (without HOME, for Git for Windows)"
    if home is None:
        return []
    if home == "":
        pytest.fail(f"{source} is empty for git, which would then write to "
                    "/.gitconfig at the root of the disk: not run")
    return [os.path.join(home, ".gitconfig"),
            os.path.join(os.environ.get("XDG_CONFIG_HOME")
                         or os.path.join(home, ".config"), "git", "config")]


def _under(path, root) -> bool:
    p = os.path.normcase(os.path.realpath(path))
    r = os.path.normcase(os.path.realpath(root))
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:  # another drive: not under root
        return False


def _refuse_a_real_global_config(root, candidates_at_start,
                                 git_config_global_at_start) -> None:
    """Fail unless every file `git config --global` would write to is fake.

    Each target must lie under ``root``, and must be none of: where git
    looked for the global config at start (``candidates_at_start``), what
    GIT_CONFIG_GLOBAL named at start, and ~/.gitconfig and
    ~/.config/git/config of the account's own home. The targets are worked
    out here, independently of the conftest, the way git works them out,
    and compared with commonpath and file by file, not with the conftest's
    _inside, which a regression can break together with the home it
    guards. Only the forbidden list leans on the conftest: its candidates
    are the ones the conftest recorded at start, before it changed the
    environment.
    """
    targets = _git_global_targets()
    for written in targets:
        if not _under(written, root):
            pytest.fail(f"`git config --global` would write to {written}, "
                        f"outside {root}: not run")
    real = _real_home()
    forbidden = [*candidates_at_start, os.path.join(real, ".gitconfig"),
                 os.path.join(real, ".config", "git", "config")]
    if git_config_global_at_start is not None:
        forbidden.append(git_config_global_at_start)
    for written in targets:
        for real_config in forbidden:
            if _same(written, real_config):
                pytest.fail(f"`git config --global` would write to {written}, "
                            f"which is {real_config}: not run")


def test_the_git_guard_refuses_a_real_global_config(tmp_path, monkeypatch):
    # Only monkeypatch: nothing here runs git or writes a config. No config
    # file below exists, so realpath keeps the case of its name as given.
    h = tmp_path / "h"
    h.mkdir()
    real = str(h / ".gitconfig")

    def env(**values):
        for name in ("GIT_CONFIG_GLOBAL", "HOME", "XDG_CONFIG_HOME",
                     "HOMEDRIVE", "HOMEPATH", "USERPROFILE"):
            monkeypatch.delenv(name, raising=False)
        for name, value in values.items():
            monkeypatch.setenv(name, str(value))

    def refused(root, candidates, at_start=None, why="which is"):
        with pytest.raises(pytest.fail.Exception, match=why):
            _refuse_a_real_global_config(root, candidates, at_start)

    # Every target in (a) to (g) is under tmp_path, so there only the
    # forbidden list can refuse.
    # (a) GIT_CONFIG_GLOBAL names a config git found at start.
    env(GIT_CONFIG_GLOBAL=real)
    refused(tmp_path, [real])
    # (b) No GIT_CONFIG_GLOBAL: ~/.gitconfig, with ~ from HOME.
    env(HOME=h)
    refused(tmp_path, [real])
    # (c) $XDG_CONFIG_HOME/git/config.
    xdg = tmp_path / "x"
    env(HOME=h, XDG_CONFIG_HOME=xdg)
    refused(tmp_path, [str(xdg / "git" / "config")])
    if sys.platform == "win32":
        # (d) The same file in another case is the same file there.
        env(GIT_CONFIG_GLOBAL=real.upper())
        refused(tmp_path, [real])
        # (f) Without HOME, HOMEDRIVE+HOMEPATH when it is a folder...
        drive, path = os.path.splitdrive(str(h))
        env(HOMEDRIVE=drive, HOMEPATH=path, USERPROFILE=tmp_path / "u")
        refused(tmp_path, [real])
        # ...and USERPROFILE when it is not.
        drive, path = os.path.splitdrive(str(tmp_path / "gone"))
        env(HOMEDRIVE=drive, HOMEPATH=path, USERPROFILE=h)
        refused(tmp_path, [real])
    # (g) What GIT_CONFIG_GLOBAL named at start.
    at_start = str(tmp_path / "start.gitconfig")
    env(GIT_CONFIG_GLOBAL=at_start)
    refused(tmp_path, [], at_start)
    # (h) Outside the fake root, whatever the forbidden list says: through
    # GIT_CONFIG_GLOBAL, in a sibling whose name starts with the root's,
    # and through an XDG_CONFIG_HOME of its own.
    fake = tmp_path / "fake"
    env(GIT_CONFIG_GLOBAL=tmp_path / "elsewhere" / ".gitconfig")
    refused(fake, [], why="outside")
    env(GIT_CONFIG_GLOBAL=tmp_path / "fake2" / ".gitconfig")
    refused(fake, [], why="outside")
    env(HOME=fake / "home", XDG_CONFIG_HOME=tmp_path / "x")
    refused(fake, [], why="outside")
    # (e) A fake target, with the real ones elsewhere, is let through.
    env(GIT_CONFIG_GLOBAL=fake / ".gitconfig")
    _refuse_a_real_global_config(fake, [real, str(xdg / "git" / "config")],
                                 at_start)
    env(HOME=fake / "home")
    _refuse_a_real_global_config(fake, [real], None)
    # (i) Without HOME, only Git for Windows takes ~ from USERPROFILE; any
    # other git has no ~ and writes nowhere.
    env(USERPROFILE=h)
    if sys.platform == "win32":
        refused(tmp_path, [real])
    else:
        _refuse_a_real_global_config(tmp_path, [real], None)
    # (j) An empty HOME is the root of the disk for git, never a fake home.
    env(HOME="")
    refused(tmp_path, [], why="^HOME is empty")
    if sys.platform == "win32":
        # Git for Windows takes an empty USERPROFILE as HOME.
        env(USERPROFILE="")
        refused(tmp_path, [], why=re.escape(
            "USERPROFILE (without HOME, for Git for Windows) is empty"))


def test_the_conftest_finds_git_s_home_as_git_does(tmp_path, pdfapps_isolation):
    # The model the conftest records the real configs with, on
    # environments of its own; the tests below check it against git. Both
    # platforms' rules, on either: the two functions read nothing but the
    # environment, sys.platform and whether a folder exists.
    git_home = pdfapps_isolation.git_home
    candidates = pdfapps_isolation.git_global_candidates_for
    h, x = str(tmp_path / "h"), str(tmp_path / "x")
    drive, path = os.path.splitdrive(str(tmp_path))
    for platform in ("win32", "linux"):
        win = platform == "win32"
        with pytest.MonkeyPatch.context() as m:
            m.setattr(sys, "platform", platform)
            for name in ("HOME", "HOMEDRIVE", "HOMEPATH", "USERPROFILE"):
                m.delenv(name, raising=False)
            # An empty HOME is git's ~ as it is, the root of the disk.
            m.setenv("HOME", "")
            assert git_home() == "", platform
            m.setenv("HOME", h)
            assert git_home() == h, platform
            m.delenv("HOME")
            m.setenv("USERPROFILE", x)
            assert git_home() == (x if win else None), platform
            m.setenv("HOMEDRIVE", drive)
            m.setenv("HOMEPATH", path)
            assert git_home() == (drive + path if win else None), platform
            # A home share that is not there (a disconnected drive).
            m.setenv("HOMEPATH", path + os.sep + "no such folder")
            assert git_home() == (x if win else None), platform

            # An empty XDG_CONFIG_HOME is unset for git.
            assert candidates(h, "") == candidates(h, None), platform
            # There Git for Windows skips the XDG config; other gits do not.
            root_xdg = () if win else (Path("/.config/git/config"),)
            assert candidates("", None) == (*root_xdg, Path("/.gitconfig")), platform
            assert candidates("", x) == (Path(x, "git", "config"),
                                         Path("/.gitconfig")), platform
            assert candidates(None, None) == (), platform
            assert candidates(None, x) == (Path(x, "git", "config"),), platform
            assert candidates(h, None) == (Path(h, ".config", "git", "config"),
                                           Path(h, ".gitconfig")), platform
            assert candidates(h, x) == (Path(x, "git", "config"),
                                        Path(h, ".gitconfig")), platform


_USER_BASE = r"""
import site
import sys

with open(sys.argv[1], "w", encoding="utf-8") as fh:
    fh.write(site.getuserbase() + "\n")
"""


def test_a_child_keeps_the_user_base_of_the_session(tmp_path, pdfapps_isolation):
    # A child of a Python outside a venv would otherwise look for its
    # `pip install --user` packages under the fake APPDATA or HOME.
    at_start = pdfapps_isolation.user_base_at_start
    # Read before the conftest changed the environment.
    assert not pdfapps_isolation.inside(at_start, pdfapps_isolation.root), at_start
    assert os.environ.get("PYTHONUSERBASE") == at_start
    script = tmp_path / "user_base.py"
    script.write_text(_USER_BASE, encoding="utf-8")
    out = tmp_path / "user_base.txt"
    # Not -I: it implies -E, which ignores PYTHONUSERBASE.
    subprocess.run([sys.executable, "-B", str(script), str(out)],
                   check=True, timeout=_CHILD_TIMEOUT)
    assert out.read_text(encoding="utf-8").strip() == at_start


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git on PATH")
def test_git_global_writes_land_in_the_fake_home(tmp_path, pdfapps_isolation):
    """`git config --global` must never write to the real ~/.gitconfig.

    GIT_CONFIG_GLOBAL names the file git writes to, so it must be the
    wrapper in the fake home, never a real global config. Checked before
    anything is written, so a regression fails here without writing.
    """
    root, inside = pdfapps_isolation.root, pdfapps_isolation.inside
    if pdfapps_isolation.git_global_preset:
        # Left alone, so still what the conftest recorded at start, which
        # the guard below refuses should the preset ever be missed.
        assert (pdfapps_isolation.git_config_global_at_start
                == os.environ.get("GIT_CONFIG_GLOBAL"))
        pytest.skip("GIT_CONFIG_GLOBAL was set outside the suite and left alone")
    target = os.environ.get("GIT_CONFIG_GLOBAL")
    if target is not None:
        assert inside(target, root), f"GIT_CONFIG_GLOBAL = {target} is outside {root}"
    configs = pdfapps_isolation.git_global_configs
    if not configs:
        # Nothing to carry over, so no wrapper: git falls back to the fake
        # HOME's .gitconfig.
        assert target is None, f"GIT_CONFIG_GLOBAL = {target} with no global config"
        assert inside(os.environ["HOME"], root)
    else:
        # Without the wrapper the writes below would still land in the
        # fake HOME, so only this tells that the developer's global config
        # (user.*, safe.directory) went missing for the tests that run git.
        assert target is not None, (
            f"the global git config {[str(p) for p in configs]} existed at "
            "start but GIT_CONFIG_GLOBAL is unset: the conftest's wrapper is missing")
        # encoding: git writes UTF-8 whatever the locale, and text=True
        # would read it in the ANSI code page on Windows (cp1252 here), so
        # a non-ASCII home or TEMP came back garbled. Strict here: these
        # values are the paths the conftest wrote to the wrapper in UTF-8.
        includes = subprocess.run(
            ["git", "config", "--file", target, "--get-all", "include.path"],
            capture_output=True, encoding="utf-8", timeout=_GIT_TIMEOUT, check=True,
        ).stdout.splitlines()
        assert includes == [p.resolve().as_posix() for p in configs]
        # --includes: with --global, `git config` alone does not follow
        # them; every other git command does. surrogateescape, here and
        # below: a value is printed as the bytes of the file, and an older
        # global config may be in Latin-1, which strict UTF-8 refuses to
        # decode.
        seen = subprocess.run(["git", "config", "--global", "--includes", "--list"],
                              capture_output=True, encoding="utf-8",
                              errors="surrogateescape", timeout=_GIT_TIMEOUT,
                              check=True).stdout.splitlines()
        for path in includes:
            # Written with forward slashes. Only on Windows: elsewhere a
            # backslash may be part of a folder's name.
            if sys.platform == "win32":
                assert "\\" not in path, path
            assert os.path.isfile(path), path
            # What the developer's global config says still reaches git.
            own = subprocess.run(["git", "config", "--file", path, "--list"],
                                 capture_output=True, encoding="utf-8",
                                 errors="surrogateescape", timeout=_GIT_TIMEOUT,
                                 check=True).stdout.splitlines()
            assert set(own) <= set(seen), (path, own, seen)

    _refuse_a_real_global_config(root, pdfapps_isolation.git_global_candidates,
                                 pdfapps_isolation.git_config_global_at_start)
    key = "pdfapps-isolation-test.probe"
    env = dict(os.environ)
    subprocess.run(["git", "config", "--global", key, "1"],
                   env=env, cwd=str(tmp_path), check=True, timeout=_GIT_TIMEOUT)
    try:
        # -z: the origin comes NUL-terminated and unquoted. surrogateescape
        # for the path, not the value "1": git prints it as raw bytes on
        # POSIX, where a path need not be UTF-8.
        origin = subprocess.run(
            ["git", "config", "--global", "--show-origin", "-z", "--get", key],
            env=env, cwd=str(tmp_path), capture_output=True, encoding="utf-8",
            errors="surrogateescape", check=True, timeout=_GIT_TIMEOUT,
        ).stdout.split("\0")[0]
        assert origin.startswith("file:"), origin
        written = origin[len("file:"):]
        assert inside(written, root), written
    finally:
        subprocess.run(["git", "config", "--global", "--remove-section",
                        "pdfapps-isolation-test"],
                       env=env, cwd=str(tmp_path), timeout=_GIT_TIMEOUT, check=False)


_RECORD_GIT_WRAPPER = r"""
import os


# Before the conftest's pytest_unconfigure removes the wrapper.
def pytest_sessionfinish(session):
    target = os.environ.get("GIT_CONFIG_GLOBAL", "")
    text = ""
    if target:
        with open(target, encoding="utf-8") as fh:
            text = fh.read()
    with open(os.environ["PDFAPPS_RECORD_GIT"], "w", encoding="utf-8") as fh:
        fh.write(target + "\n" + text)
"""

_GIT_TEST = ("tests/test_conftest_isolation.py"
             "::test_git_global_writes_land_in_the_fake_home")

# Appended to _RECORD_GIT_WRAPPER off Windows. Without HOME, Python's
# expanduser("~") takes the account's home from the password database,
# where git takes none: this puts a home of the test's there instead of
# the real one, before the conftest records git's.
_ACCOUNT_HOME_ELSEWHERE = r"""
import pwd

_getpwuid = pwd.getpwuid


def _getpwuid_with_the_test_s_home(uid):
    entry = _getpwuid(uid)
    if uid != os.getuid():
        return entry
    return pwd.struct_passwd(
        (*entry[:5], os.environ["PDFAPPS_ACCOUNT_HOME"], *entry[6:]))


pwd.getpwuid = _getpwuid_with_the_test_s_home
with open(os.environ["PDFAPPS_RECORD_ACCOUNT"], "w", encoding="utf-8") as fh:
    fh.write(os.path.expanduser("~") + "\n")
"""


def _wrapper_includes(record) -> list[str]:
    """The include.path values of the child's wrapper, as git reads them."""
    return _git_config_of_the_wrapper(record, "--get-all", "include.path")


def _git_config_of_the_wrapper(record, *args) -> list[str]:
    """`git config --file <the child's wrapper> *args`, line by line.

    Through git, not by hand: a quote or a backslash in a path is escaped
    in the file. Empty when the child had no wrapper.
    """
    target, *wrapper = record.read_text(encoding="utf-8").splitlines()
    if not target:
        return []
    copy = record.with_name(record.name + ".gitconfig")
    copy.write_text("".join(line + "\n" for line in wrapper), encoding="utf-8")
    proc = subprocess.run(
        ["git", "config", "--file", str(copy), *args],
        capture_output=True, encoding="utf-8", errors="surrogateescape",
        timeout=_GIT_TIMEOUT, check=False)
    # A missing key exits 1 and says nothing: no include at all.
    assert proc.returncode == 0 or (proc.returncode == 1 and not proc.stderr), (
        f"git config {' '.join(args)} exited {proc.returncode}: {proc.stderr}")
    return proc.stdout.splitlines()


def _assert_the_child_git_test_included(proc, temp, record, gitconfig, before):
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "1 passed" in proc.stdout and "skipped" not in proc.stdout, out
    target = record.read_text(encoding="utf-8").splitlines()[0]
    # The child took the branch with the wrapper, in its own TEMP,
    # including the config of the home it was given.
    assert _same(os.path.dirname(os.path.dirname(target)), temp), target
    includes = _wrapper_includes(record)
    assert gitconfig.resolve().as_posix() in includes, includes
    assert gitconfig.read_bytes() == before


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git on PATH")
def test_the_git_test_passes_in_a_non_ascii_home_and_temp(tmp_path):
    # The child's TEMP is inside this home too, so both the developer's
    # config that the wrapper includes and the wrapper itself have
    # non-ASCII paths, and the config a non-ASCII value, all of which git
    # prints back in UTF-8.
    home = tmp_path / "João ção 中文"
    home.mkdir()
    gitconfig = home / ".gitconfig"
    gitconfig.write_text("[user]\n\tname = João ção 中文\n", encoding="utf-8")
    before = gitconfig.read_bytes()
    record = tmp_path / "wrapper.txt"
    proc, temp = _child_pytest(
        home, "pdfapps_record_git_wrapper", _RECORD_GIT_WRAPPER, [_GIT_TEST],
        HOME=str(home), USERPROFILE=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        # Inherited, it would name this session's wrapper and the child's
        # test would skip.
        GIT_CONFIG_GLOBAL=None, PDFAPPS_RECORD_GIT=str(record))
    _assert_the_child_git_test_included(proc, temp, record, gitconfig, before)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git on PATH")
def test_the_git_test_passes_with_a_global_config_not_in_utf8(tmp_path):
    # git prints a value as the bytes in the file, and an older global
    # config may be in Latin-1: the git test reads it through the wrapper.
    home = tmp_path / "home"
    home.mkdir()
    gitconfig = home / ".gitconfig"
    gitconfig.write_bytes(b"[user]\n\tname = Jos\xe9\n")
    before = gitconfig.read_bytes()
    record = tmp_path / "wrapper.txt"
    proc, temp = _child_pytest(
        tmp_path, "pdfapps_record_git_wrapper", _RECORD_GIT_WRAPPER, [_GIT_TEST],
        HOME=str(home), USERPROFILE=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        GIT_CONFIG_GLOBAL=None, PDFAPPS_RECORD_GIT=str(record))
    _assert_the_child_git_test_included(proc, temp, record, gitconfig, before)


_NOT_ON_WINDOWS = pytest.mark.skipif(
    sys.platform == "win32", reason="Windows allows no such file name")


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git on PATH")
@pytest.mark.parametrize("name", [
    pytest.param('home q"uo te', id="double quote", marks=_NOT_ON_WINDOWS),
    pytest.param("home b\\ack", id="backslash", marks=_NOT_ON_WINDOWS),
    pytest.param("home #semi;colon", id="comment characters"),
])
def test_the_git_test_passes_in_a_home_whose_name_git_escapes(tmp_path, name):
    # In a git config value a double quote opens or closes a quoted part
    # and a backslash starts an escape; outside quotes, # and ; start a
    # comment. So the wrapper quotes each path and escapes the first two.
    home = tmp_path / name
    home.mkdir()
    gitconfig = home / ".gitconfig"
    gitconfig.write_text("[user]\n\tname = escaped\n", encoding="utf-8")
    before = gitconfig.read_bytes()
    record = tmp_path / "wrapper.txt"
    # The plugin and the child's TEMP stay outside that home: ; separates
    # PYTHONPATH entries on Windows.
    proc, temp = _child_pytest(
        tmp_path, "pdfapps_record_git_wrapper", _RECORD_GIT_WRAPPER, [_GIT_TEST],
        HOME=str(home), USERPROFILE=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        GIT_CONFIG_GLOBAL=None, PDFAPPS_RECORD_GIT=str(record))
    _assert_the_child_git_test_included(proc, temp, record, gitconfig, before)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git on PATH")
def test_a_preset_git_config_global_is_left_alone(tmp_path):
    # The child's conftest must record GIT_CONFIG_GLOBAL as preset and
    # leave it alone, so its git test skips on the preset branch, where it
    # also checks what the conftest recorded at start.
    preset = tmp_path / "preset.gitconfig"
    preset.write_text("[user]\n\tname = preset\n", encoding="utf-8")
    before = preset.read_bytes()
    record = tmp_path / "wrapper.txt"
    proc, _ = _child_pytest(
        tmp_path, "pdfapps_record_git_wrapper", _RECORD_GIT_WRAPPER,
        [_GIT_TEST, "-rs"],
        GIT_CONFIG_GLOBAL=str(preset), PDFAPPS_RECORD_GIT=str(record))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    # The skip of the preset branch, not any other.
    assert "1 skipped" in proc.stdout, out
    assert "set outside the suite and left alone" in proc.stdout, out
    target = record.read_text(encoding="utf-8").splitlines()[0]
    assert _same(target, preset), target
    assert preset.read_bytes() == before


@pytest.mark.skipif(sys.platform != "win32",
                    reason="only Git for Windows reads HOMEDRIVE and HOMEPATH")
@pytest.mark.skipif(shutil.which("git") is None, reason="needs git on PATH")
def test_without_home_the_global_config_comes_from_homedrive(tmp_path):
    # A home share: HOMEDRIVE+HOMEPATH names another folder than
    # USERPROFILE, and HOME is unset.
    share, profile = tmp_path / "share", tmp_path / "profile"
    share.mkdir()
    profile.mkdir()
    gitconfig = share / ".gitconfig"
    gitconfig.write_text("[user]\n\tname = share\n", encoding="utf-8")
    before = gitconfig.read_bytes()
    drive, path = os.path.splitdrive(str(share))
    # The premise, read only: this git takes ~ from there, not USERPROFILE.
    env = {name: value for name, value in os.environ.items()
           if name not in ("HOME", "XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL")}
    env.update(HOMEDRIVE=drive, HOMEPATH=path, USERPROFILE=str(profile))
    premise = subprocess.run(
        ["git", "config", "--global", "--show-origin", "-z", "--get", "user.name"],
        env=env, cwd=str(tmp_path), capture_output=True, encoding="utf-8",
        errors="surrogateescape", check=False, timeout=_GIT_TIMEOUT)
    origin = premise.stdout.split("\0")[0]
    assert premise.returncode == 0 and _same(origin[len("file:"):], gitconfig), (
        "this git no longer takes ~ from HOMEDRIVE+HOMEPATH: revisit _git_home "
        f"(exit {premise.returncode}, {origin!r}, {premise.stderr!r})")
    record = tmp_path / "wrapper.txt"
    proc, temp = _child_pytest(
        tmp_path, "pdfapps_record_git_wrapper", _RECORD_GIT_WRAPPER, [_GIT_TEST],
        HOME=None, HOMEDRIVE=drive, HOMEPATH=path, USERPROFILE=str(profile),
        XDG_CONFIG_HOME=None, GIT_CONFIG_GLOBAL=None,
        PDFAPPS_RECORD_GIT=str(record))
    _assert_the_child_git_test_included(proc, temp, record, gitconfig, before)
    assert list(profile.iterdir()) == []


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git on PATH")
@pytest.mark.parametrize("home", [
    pytest.param("", id="empty HOME"),
    pytest.param(None, id="no HOME", marks=pytest.mark.skipif(
        sys.platform == "win32",
        reason="Git for Windows takes ~ from elsewhere: see the test above")),
])
def test_git_takes_no_home_from_elsewhere(tmp_path, home):
    # An empty HOME is git's ~ as it is (the root of the disk), and outside
    # Windows git has no ~ without HOME. Either way, the wrapper must not
    # include the config of the home that HOMEDRIVE+HOMEPATH and
    # USERPROFILE name, nor, outside Windows, that of the account's home.
    other = tmp_path / "other"
    other.mkdir()
    gitconfig = other / ".gitconfig"
    gitconfig.write_text("[user]\n\tname = pdfapps-other-home\n", encoding="utf-8")
    before = gitconfig.read_bytes()
    plugin_src, extra_env = _RECORD_GIT_WRAPPER, {}
    account = tmp_path / "account"
    if sys.platform != "win32":
        account.mkdir()
        (account / ".gitconfig").write_text(
            "[user]\n\tname = pdfapps-account-home\n", encoding="utf-8")
        plugin_src += _ACCOUNT_HOME_ELSEWHERE
        extra_env.update(PDFAPPS_ACCOUNT_HOME=str(account),
                         PDFAPPS_RECORD_ACCOUNT=str(tmp_path / "account.txt"))
    drive, path = os.path.splitdrive(str(other))
    # The premise, read only: this git does not read that config.
    env = {name: value for name, value in os.environ.items()
           if name not in ("HOME", "XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL")}
    env.update(HOMEDRIVE=drive, HOMEPATH=path, USERPROFILE=str(other))
    if home is not None:
        env["HOME"] = home
    premise = subprocess.run(
        ["git", "config", "--global", "--show-origin", "-z", "--get", "user.name"],
        env=env, cwd=str(tmp_path), capture_output=True, encoding="utf-8",
        errors="surrogateescape", check=False, timeout=_GIT_TIMEOUT)
    origin = premise.stdout.split("\0")[0]
    assert not origin or not _same(origin[len("file:"):], gitconfig), (
        "this git takes ~ from HOMEDRIVE+HOMEPATH or USERPROFILE here: "
        f"revisit _git_home ({origin})")
    record = tmp_path / "wrapper.txt"
    proc, _ = _child_pytest(
        tmp_path, "pdfapps_record_git_wrapper", plugin_src, [_GIT_TEST],
        HOME=home, HOMEDRIVE=drive, HOMEPATH=path, USERPROFILE=str(other),
        XDG_CONFIG_HOME=None, GIT_CONFIG_GLOBAL=None,
        PDFAPPS_RECORD_GIT=str(record), **extra_env)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "1 passed" in proc.stdout and "skipped" not in proc.stdout, out
    if home is None:
        # The child's Python took that home for the account's: otherwise
        # the check below would prove nothing for it.
        seen_home = (tmp_path / "account.txt").read_text(encoding="utf-8").strip()
        assert _same(seen_home, account), seen_home
    # Usually no wrapper at all; one would come only from a config at the
    # root of the disk, never from the other home or the account's.
    wrapper = record.read_text(encoding="utf-8").splitlines()[1:]
    assert not any(gitconfig.resolve().as_posix() in line for line in wrapper), wrapper
    read = _git_config_of_the_wrapper(record, "--includes", "--list")
    assert not [line for line in read
                if line.endswith(("=pdfapps-other-home", "=pdfapps-account-home"))], read
    assert gitconfig.read_bytes() == before
