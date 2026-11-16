"""Suite-wide pytest configuration.

Registers the custom markers and, before any test module imports ``app``,
points the per-user locations taken from the environment (HOME,
USERPROFILE, APPDATA, LOCALAPPDATA, the XDG config, data, state and
cache homes, and on Windows HOMEDRIVE and HOMEPATH) into a throwaway
folder. ``app.i18n`` reads the config at import time, ``PdfViewerPanel``
rewrites its recent files, ``pdfapps.py`` opens its log next to it, and
on Windows qtawesome installs its fonts for the user (GDI and HKCU) when
``%LOCALAPPDATA%`` lacks them. Without this the suite used the real ones
of whoever ran it.

Known limits: on Windows, Qt's ``QDir.homePath()`` and
``QStandardPaths.HomeLocation`` come from the account's profile, not from
the environment, and still name the real home. TEMP, TMP and TMPDIR are
left alone; on Windows TEMP is a folder inside the real profile.

Only what pytest loads is covered: ``pytest --noconftest``, running a test
file as a script or importing it in a REPL bypasses this module (see
CONTRIBUTING.md, "Running the tests").
"""

import atexit
import importlib.util
import os
import shutil
import site
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest


def _inside(path, root) -> bool:
    """True if ``path`` is ``root`` or below it.

    realpath expands 8.3 short names even when the tail does not exist yet
    (the Windows runner's TEMP is C:\\Users\\RUNNER~1\\...), which
    Path.is_relative_to does not; normcase folds case on Windows. The
    rstrip keeps a drive root (C:\\) from requiring a doubled separator.
    """
    p = os.path.normcase(os.path.realpath(path))
    r = os.path.normcase(os.path.realpath(root)).rstrip(os.sep)
    return p == r or p.startswith(r + os.sep)


def _git_home() -> str | None:
    """The folder git takes ``~`` from, in git's own order, or None.

    HOME whenever it is set, even empty. Without it, Git for Windows takes
    HOMEDRIVE+HOMEPATH when that is a folder (a home share may be
    disconnected), and USERPROFILE after it; any other git has no ``~``.
    Measured with git 2.56.0.windows.2 and git 2.53.0 on Ubuntu. Python's
    expanduser reads USERPROFILE first, so it alone is not where git looks.
    """
    home = os.environ.get("HOME")
    if home is not None or sys.platform != "win32":
        return home
    drive, path = os.environ.get("HOMEDRIVE"), os.environ.get("HOMEPATH")
    if drive is not None and path is not None and os.path.isdir(drive + path):
        return drive + path
    return os.environ.get("USERPROFILE")


def _git_global_candidates(home: str | None,
                           xdg_config_home: str | None) -> tuple[Path, ...]:
    """Where git looks for the global config without GIT_CONFIG_GLOBAL.

    In git's order, joined as git joins them: an empty home is the root of
    the disk (/.gitconfig). There Git for Windows skips the XDG one, and
    without a home every git keeps only an XDG_CONFIG_HOME of its own.
    """
    if xdg_config_home:
        xdg = xdg_config_home
    elif home is None or (home == "" and sys.platform == "win32"):
        xdg = None
    else:
        xdg = home + "/.config"
    return tuple(Path(p) for p in (
        None if xdg is None else xdg + "/git/config",
        None if home is None else home + "/.gitconfig") if p is not None)


def _git_config_value(path: Path) -> str:
    # Backslash and double quote are escapes inside git config values.
    text = path.as_posix().replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _qtawesome_font_files() -> list[tuple[str, str]]:
    """(name, source) of every file qtawesome installs, sorted by name.

    find_spec locates the package without importing it (and Qt). qtawesome
    walks its fonts folder and installs every file flat, under its name.
    Empty when qtawesome is not installed.
    """
    spec = importlib.util.find_spec("qtawesome")
    if spec is None or not spec.submodule_search_locations:
        return []
    fonts = Path(next(iter(spec.submodule_search_locations))) / "fonts"
    return sorted((f, os.path.join(walk_root, f))
                  for walk_root, _, files in os.walk(fonts) for f in files)


def _fail_closed() -> None:
    # Imported here, after the environment below: app.i18n resolves the
    # config paths and reads the config when it is first imported.
    repo_root = str(Path(__file__).resolve().parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from app import i18n

    escaped = [
        (name, value) for name, value in (
            ("app.i18n._CONFIG_PATH", i18n._CONFIG_PATH),
            ("app.i18n._SIGNATURE_PATH", i18n._SIGNATURE_PATH),
            ("app.i18n._LEGACY_CONFIG", i18n._LEGACY_CONFIG),
            ("app.i18n._LEGACY_SIGNATURE", i18n._LEGACY_SIGNATURE),
            ('os.path.expanduser("~")', os.path.expanduser("~")),
        ) if not _inside(value, _ROOT)
    ]
    if escaped:
        raise pytest.UsageError(
            "tests/conftest.py could not isolate the suite from the real home: "
            + "; ".join(f"{name} = {value}" for name, value in escaped))


def _pin_language() -> None:
    from app import i18n

    # A plain assignment, once: an autouse fixture requesting monkeypatch
    # would be torn down before the _LANG leak guard of
    # test_watermark_characterization.py and break it. The CI runs in "en".
    i18n._LANG = "en"


# ── 1. what has to be read before the environment changes ──

_ORIG_USER_BASE = site.getuserbase()
# Git looks for the global config under HOME; Git for Windows, without
# HOME, under HOMEDRIVE+HOMEPATH and then USERPROFILE (see _git_home).
_ORIG_GIT_HOME = _git_home()
_ORIG_XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME")
_GIT_GLOBAL_PRESET = "GIT_CONFIG_GLOBAL" in os.environ
# What GIT_CONFIG_GLOBAL named at start, if anything: the file a
# `git config --global` would have written to.
_ORIG_GIT_CONFIG_GLOBAL = os.environ.get("GIT_CONFIG_GLOBAL")
# Where git looks for the global config when GIT_CONFIG_GLOBAL is unset, in
# its order, and of those the ones that exist.
_GIT_GLOBAL_CANDIDATES = _git_global_candidates(_ORIG_GIT_HOME,
                                                _ORIG_XDG_CONFIG_HOME)
_GIT_GLOBAL_CONFIGS = tuple(p for p in _GIT_GLOBAL_CANDIDATES if p.is_file())

# ── 2-4. the fake home ──

# TEMP, TMP and TMPDIR stay: pytest's tmp_path and app code that compares
# with tempfile.gettempdir() would see the value change mid-session. So
# the fake home sits inside tempfile.gettempdir(), which a real home does
# not: the temp file cleanup in app/editor/tab.py (the previous signature,
# the dropped pending edits) would take files under it for its own.
_ROOT = Path(tempfile.mkdtemp(prefix="pdfapps-test-home-"))
_ROOT_PID = os.getpid()


def _remove_root_at_exit() -> None:
    # pytest_unconfigure runs only once pytest_configure has, and a usage
    # error (an unknown option) is raised after this module is loaded and
    # before that: without this the folder stays in TEMP. The pid check
    # keeps a forked child that exits through atexit from removing the
    # folder its parent still uses.
    if os.getpid() == _ROOT_PID:
        shutil.rmtree(_ROOT, ignore_errors=True)


atexit.register(_remove_root_at_exit)

# An error from here to the end of section 9 ends the session before
# pytest_unconfigure could remove the folder. The atexit handler would
# too, but only when the interpreter exits, not in a process that runs
# pytest.main() and goes on.
try:
    _HOME = _ROOT / "home"
    _HOME_DIRS = {
        "APPDATA": _HOME / "AppData" / "Roaming",
        # Must exist: SHGetKnownFolderPath(LocalAppData) fails with
        # 0x80070003 when the folder under the profile is missing.
        "LOCALAPPDATA": _HOME / "AppData" / "Local",
        "XDG_CONFIG_HOME": _HOME / ".config",
        "XDG_DATA_HOME": _HOME / ".local" / "share",
        "XDG_STATE_HOME": _HOME / ".local" / "state",
        "XDG_CACHE_HOME": _HOME / ".cache",
    }
    _USER_FONTS = _HOME_DIRS["LOCALAPPDATA"] / "Microsoft" / "Windows" / "Fonts"
    (_HOME / "Desktop").mkdir(parents=True)
    for _d in _HOME_DIRS.values():
        _d.mkdir(parents=True, exist_ok=True)
    # XDG_RUNTIME_DIR stays: Qt checks its owner and mode.
    os.environ["HOME"] = str(_HOME)
    os.environ["USERPROFILE"] = str(_HOME)
    if sys.platform == "win32":
        # Git for Windows takes these when HOME is unset (a child started
        # with an environment that drops it), before USERPROFILE.
        os.environ["HOMEDRIVE"], os.environ["HOMEPATH"] = os.path.splitdrive(
            str(_HOME))
    for _name, _d in _HOME_DIRS.items():
        os.environ[_name] = str(_d)
    os.environ["PDFAPPS_TEST_HOME"] = str(_ROOT)

    # ── 5. user site-packages ──

    # The user site derives from APPDATA on Windows and HOME elsewhere, so a
    # child of a non-venv Python with `pip install --user` dependencies would
    # stop finding PySide6 or pypdf. No effect in a venv without system site.
    os.environ.setdefault("PYTHONUSERBASE", _ORIG_USER_BASE)

    # ── 6. the global git config ──

    # With GIT_CONFIG_GLOBAL set, git reads neither ~/.gitconfig nor
    # $XDG_CONFIG_HOME/git/config, so the real ones are pulled in through an
    # [include] in a wrapper of our own, in the order git reads them. Never
    # point GIT_CONFIG_GLOBAL at a real file: `git config --global` writes to
    # whatever it names, and the wrapper takes those writes instead.
    # Known limits: a `~` in an include.path or an includeIf "gitdir:~/..."
    # of the real config now expands against the fake HOME, and the default
    # core.excludesFile and core.attributesFile (under XDG_CONFIG_HOME) are
    # no longer found. The tests that run git only read.
    if not _GIT_GLOBAL_PRESET and _GIT_GLOBAL_CONFIGS:
        _wrapper = _ROOT / "gitconfig-global"
        _wrapper.write_text(
            "[include]\n"
            + "".join(f"\tpath = {_git_config_value(p.resolve())}\n"
                      for p in _GIT_GLOBAL_CONFIGS),
            encoding="utf-8")
        os.environ["GIT_CONFIG_GLOBAL"] = str(_wrapper)

    # ── 7. qtawesome's fonts, already in place ──

    # With all its files present in %LOCALAPPDATA%\Microsoft\Windows\Fonts,
    # qtawesome copies nothing, calls no AddFontResourceW and writes nothing
    # to HKCU.
    if sys.platform == "win32":
        _USER_FONTS.mkdir(parents=True, exist_ok=True)
        for _f, _src in _qtawesome_font_files():
            shutil.copy(_src, _USER_FONTS / _f)

    # ── 8. what the fonts folder held before any test ──

    # Recorded here, apart from section 7, for T-ISO-5: the first test that
    # draws an icon makes qtawesome install whatever is missing (into the real
    # GDI and HKCU too), and from then on the folder looks complete, so a
    # check made during the tests depends on their order.
    _QTA_FONTS = (tuple(f for f, _ in _qtawesome_font_files())
                  if sys.platform == "win32" else ())
    _QTA_FONTS_MISSING_AT_START = tuple(
        f for f in _QTA_FONTS if not (_USER_FONTS / f).is_file())

    # ── 9. fail closed, then pin the language ──

    _fail_closed()
    _pin_language()
except BaseException:
    shutil.rmtree(_ROOT, ignore_errors=True)
    raise


class Isolation(NamedTuple):
    root: Path
    inside: Callable[[str, str], bool]
    # GIT_CONFIG_GLOBAL came from outside the suite and was left alone.
    git_global_preset: bool
    # The real global git configs found at start; unless GIT_CONFIG_GLOBAL
    # was preset, the wrapper includes them, and there is none without them.
    git_global_configs: tuple[Path, ...]
    # Where git would have read and written the global config at start,
    # whether those files existed or not.
    git_global_candidates: tuple[Path, ...]
    # What GIT_CONFIG_GLOBAL named at start, or None.
    git_config_global_at_start: str | None
    # The conftest's model of git's home lookup, so a test can run it on
    # an environment of its own.
    git_home: Callable[[], str | None]
    git_global_candidates_for: Callable[[str | None, str | None],
                                        tuple[Path, ...]]
    # The user base read at start, before the environment changed; the
    # conftest hands it on through PYTHONUSERBASE.
    user_base_at_start: str
    # Windows only, else empty: the files qtawesome installs, and those of
    # them not in the fake LOCALAPPDATA fonts folder before any test ran.
    qta_fonts: tuple[str, ...]
    qta_fonts_missing_at_start: tuple[str, ...]
    # What the conftest ran to set app.i18n._LANG, so a test can check it
    # on a machine whose own language is already English.
    pin_language: Callable[[], None]


@pytest.fixture(scope="session")
def pdfapps_isolation() -> Isolation:
    """What the conftest set up, as recorded before any test ran.

    Not autouse and without monkeypatch on purpose (see the _LANG note).
    """
    return Isolation(
        root=_ROOT,
        inside=_inside,
        git_global_preset=_GIT_GLOBAL_PRESET,
        git_global_configs=_GIT_GLOBAL_CONFIGS,
        git_global_candidates=_GIT_GLOBAL_CANDIDATES,
        git_config_global_at_start=_ORIG_GIT_CONFIG_GLOBAL,
        git_home=_git_home,
        git_global_candidates_for=_git_global_candidates,
        user_base_at_start=_ORIG_USER_BASE,
        qta_fonts=_QTA_FONTS,
        qta_fonts_missing_at_start=_QTA_FONTS_MISSING_AT_START,
        pin_language=_pin_language,
    )


def pytest_configure(config):
    # A test with this marker pins behaviour that is wrong on purpose:
    # it characterises a known defect as the code has it today, so a
    # planned fix makes it fail and it is then rewritten together with
    # that fix. Not an xfail: it must pass today. List them with
    # `pytest -m known_defect`.
    config.addinivalue_line(
        "markers",
        "known_defect(reason): characterises a known defect as it "
        "behaves today; to be rewritten deliberately with the fix "
        "named in reason",
    )


def pytest_unconfigure(config):
    # The environment is left naming the removed folder. A process that
    # calls pytest.main() again runs this module again, but app.i18n stays
    # imported with the first folder's paths, so _fail_closed() ends that
    # session with a UsageError before any test runs. Restoring the
    # environment here would not change that, would leave the process's
    # environment and app.i18n disagreeing, and would not happen after a
    # usage error, which never reaches this hook.
    shutil.rmtree(_ROOT, ignore_errors=True)
