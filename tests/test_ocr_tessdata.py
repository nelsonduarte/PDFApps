"""Regression tests for ``app.tools.ocr._find_tessdata``.

The bug: on macOS Homebrew the ``tesseract`` binary lives in
``<prefix>/bin`` but the language data lives in
``<prefix>/share/tessdata`` — ``/usr/local`` on Intel and
``/opt/homebrew`` on Apple Silicon. The old ``_find_tessdata`` only
looked for a ``tessdata`` folder *adjacent* to the binary and, as a
fixed fallback, ``/usr/local/share/tessdata`` (Intel only). On an
Apple Silicon Mac (e.g. a MacBook Air M5) it therefore returned
``None`` and the app never set ``TESSDATA_PREFIX``, so extra language
packs such as Hebrew were silently invisible.

The fix is additive:

1. Derive ``<prefix>/share/tessdata`` relative to the binary
   (``<prefix>/bin/tesseract`` -> ``<prefix>/share/tessdata``). This
   covers Intel, Apple Silicon *and* non-standard install prefixes in
   one generic step.
2. Add ``/opt/homebrew/share/tessdata`` to the fixed
   ``linux``/``darwin`` fallback list, for the case where the binary is
   resolved via ``PATH`` and the derived prefix does not match.

The precedence enforced by ``_find_tessdata`` (first match wins) is:

1. ``<bindir>/tessdata`` adjacent to the binary (Windows / bundled).
2. Versioned ``<prefix>/share/tesseract-ocr/<version>/tessdata`` under the
   binary's own prefix, reverse-sorted so the newest version wins (the
   snap fix described below). For ``/usr/bin/tesseract`` this is the same
   lookup as step 3.
3. Versioned Linux ``/usr/share/tesseract-ocr/<version>/tessdata``,
   reverse-sorted so the newest version wins.
4. The relative ``<prefix>/share/tessdata`` derivation from the Homebrew
   fix above, deliberately *after* the versioned lookups so a stale flat
   ``/usr/share/tessdata`` (which is what the derivation yields for
   ``/usr/bin/tesseract``) never shadows a newer versioned directory
   (issue #27, PR #146 review).
5. Fixed ``/usr/share``, ``/usr/local/share``, ``/opt/homebrew/share``
   and snap fallbacks.

The Windows lookup is unchanged, and ``/usr/bin/tesseract`` gets the
same lookup as before. The exception is step 2: a binary under another
prefix that carries its own versioned
``<prefix>/share/tesseract-ocr/<version>/tessdata`` now gets that
directory, ahead of ``/usr/share``'s. That is the snap fix below, and it
applies equally to e.g. ``/usr/local/bin/tesseract``
(``test_binary_prefix_versioned_wins_over_usr_share``).

Snap regression (stable rev 43, 1.15.0): the snap stages the Ubuntu 22.04
``tesseract-ocr`` debs, so the binary is ``$SNAP/usr/bin/tesseract`` and
the data is ``$SNAP/usr/share/tesseract-ocr/4.00/tessdata``. None of the
old probes looked there (the prefix derivation yields the flat
``$SNAP/usr/share/tessdata``), ``_find_tessdata`` returned ``None``,
``TESSDATA_PREFIX`` was never set, and the binary fell back to its
compiled-in ``/usr/share/tesseract-ocr/4.00/tessdata``, which inside the
snap resolves against the base snap's rootfs, where no Tesseract data is
installed. Step 2 fixes it without naming ``$SNAP`` or ``4.00``.

Most tests never touch the real filesystem: ``os.path.isdir``,
``glob.glob`` and ``sys.platform`` are monkeypatched so they run
identically on Windows and Linux hosts. The two adjacent-tessdata tests
patch only ``os.path.isdir``: the adjacent probe returns before any glob.
CI runs the suite on Linux only (``tests.yml``, ubuntu-latest; no macOS
job runs it), so the ``darwin`` cases are exercised by faking
``sys.platform``. The tests that build a snap tree with ``_make_snap``
create the real layout in ``tmp_path`` and fake only ``sys.platform``
(plus ``SNAP`` in the environment in three of them, and ``shutil.which``
in the PATH-lookup test, ``test_snap_chain_from_path_lookup``).
``test_snap_lookup_follows_the_binary_not_the_snap_env`` is the
exception: it uses no ``tmp_path``, fakes ``os.path.isdir``,
``glob.glob`` and ``sys.platform`` like the tests above, and sets
``SNAP``.
"""

from __future__ import annotations

import ast
import fnmatch
import glob as _glob
import os
import sys
from pathlib import Path

import pytest

# Make the project root importable so ``from app.tools...`` works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# _find_tessdata is a plain function and needs no GUI, but importing the
# module pulls in PySide6 widget classes; force the offscreen platform so
# a headless runner never tries to open a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.tools.ocr import _find_tessdata  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _norm(path):
    """Collapse ``os.sep`` differences so a test can be written with forward
    slashes yet still match paths that ``os.path.join`` built with ``\\`` on
    Windows. ``None`` passes through so a regression that returns ``None``
    fails as a plain assertion rather than an ``AttributeError``."""
    return None if path is None else path.replace("\\", "/")


def _fake_isdir(existing):
    """Return an ``os.path.isdir`` replacement that reports *only* the given
    (separator-normalised) directories as existing."""
    wanted = {_norm(p) for p in existing}

    def _isdir(path):
        return _norm(path) in wanted

    return _isdir


def _glob_over(existing, calls=None):
    """Return a ``glob.glob`` replacement that matches the pattern against
    the simulated directories *existing* only, one path component at a time
    so ``*`` never crosses a separator, as in the real glob. Patterns and
    results are separator-normalised; every pattern is appended to *calls*
    when a list is given."""
    dirs = sorted({_norm(p) for p in existing})

    def _glob_fn(pattern):
        pat = _norm(pattern)
        if calls is not None:
            calls.append(pat)
        want = pat.split("/")
        return [d for d in dirs
                if len(d.split("/")) == len(want)
                and all(fnmatch.fnmatchcase(part, w)
                        for part, w in zip(d.split("/"), want))]

    return _glob_fn


def _patch_fs(monkeypatch, existing, *, platform=None, glob_results=None):
    """Install a fake ``os.path.isdir`` (and optionally ``glob.glob`` /
    ``sys.platform``) covering exactly *existing*."""
    monkeypatch.setattr(os.path, "isdir", _fake_isdir(existing))
    if platform is not None:
        monkeypatch.setattr(sys, "platform", platform)
    if glob_results is not None:
        monkeypatch.setattr(_glob, "glob", lambda pattern: list(glob_results))


# ---------------------------------------------------------------------------
# prefix-relative derivation (step 4: runs after the adjacent probe AND both
# versioned globs, so glob is patched empty and steps 2 and 3 find nothing;
# os.path.isdir sees only the listed dirs, so no real host tessdata dir can
# match). Step 5's fixed list also names /opt/homebrew/share/tessdata and
# /usr/local/share/tessdata, so only test_custom_prefix tells step 4 from 5.
# ---------------------------------------------------------------------------
def test_apple_silicon_homebrew(monkeypatch):
    # <prefix>/bin/tesseract -> <prefix>/share/tessdata on /opt/homebrew.
    # Only the share/tessdata dir exists; the adjacent bin/tessdata does not
    # and macOS has no versioned /usr/share/tesseract-ocr layout.
    _patch_fs(
        monkeypatch,
        {"/opt/homebrew/share/tessdata"},
        platform="darwin",
        glob_results=[],
    )
    result = _find_tessdata("/opt/homebrew/bin/tesseract")
    assert _norm(result) == "/opt/homebrew/share/tessdata"


def test_intel_homebrew_regression(monkeypatch):
    # /usr/local (Intel Homebrew) must keep working via the same derivation.
    _patch_fs(
        monkeypatch,
        {"/usr/local/share/tessdata"},
        platform="darwin",
        glob_results=[],
    )
    result = _find_tessdata("/usr/local/bin/tesseract")
    assert _norm(result) == "/usr/local/share/tessdata"


def test_custom_prefix(monkeypatch):
    # A non-standard prefix proves the derivation is generic, not hard-coded.
    _patch_fs(
        monkeypatch,
        {"/opt/custom/share/tessdata"},
        platform="linux",
        glob_results=[],
    )
    result = _find_tessdata("/opt/custom/bin/tesseract")
    assert _norm(result) == "/opt/custom/share/tessdata"


# ---------------------------------------------------------------------------
# adjacent tessdata (Windows-style install) still wins first
# ---------------------------------------------------------------------------
def test_adjacent_bin_tessdata_takes_precedence(monkeypatch):
    # When BOTH the adjacent bin/tessdata and the derived share/tessdata
    # exist, the adjacent one (Windows layout) must be returned first.
    _patch_fs(monkeypatch, {
        "/opt/homebrew/bin/tessdata",
        "/opt/homebrew/share/tessdata",
    })
    result = _find_tessdata("/opt/homebrew/bin/tesseract")
    assert _norm(result) == "/opt/homebrew/bin/tessdata"


def test_windows_adjacent(monkeypatch):
    # A real Windows install path: tessdata sits next to tesseract.exe.
    # Compute the adjacent path exactly as the function does so the test is
    # OS-agnostic (ntpath vs posixpath split \\ differently).
    tess_exe = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    adjacent = os.path.join(os.path.dirname(tess_exe), "tessdata")
    _patch_fs(monkeypatch, {adjacent})
    result = _find_tessdata(tess_exe)
    assert _norm(result) == _norm(adjacent)


# ---------------------------------------------------------------------------
# fixed macOS fallback (binary found via PATH, derived prefix does not match)
# ---------------------------------------------------------------------------
def test_apple_silicon_fixed_fallback(monkeypatch):
    # tesseract resolved from an unrelated location -> derived
    # /weird/share/tessdata is absent, so the explicit
    # /opt/homebrew/share/tessdata fallback must catch it.
    _patch_fs(
        monkeypatch,
        {"/opt/homebrew/share/tessdata"},
        platform="darwin",
        glob_results=[],
    )
    result = _find_tessdata("/weird/place/tesseract")
    assert _norm(result) == "/opt/homebrew/share/tessdata"


# ---------------------------------------------------------------------------
# Linux regressions (unchanged behaviour)
# ---------------------------------------------------------------------------
def test_linux_versioned_tessdata(monkeypatch):
    # Debian/Ubuntu layout: /usr/share/tesseract-ocr/<version>/tessdata.
    _patch_fs(
        monkeypatch,
        {"/usr/share/tesseract-ocr/5/tessdata"},
        platform="linux",
        glob_results=["/usr/share/tesseract-ocr/5/tessdata"],
    )
    result = _find_tessdata("/usr/bin/tesseract")
    assert _norm(result) == "/usr/share/tesseract-ocr/5/tessdata"


def test_linux_reverse_sort_prefers_latest(monkeypatch):
    # When 4.00 and 5 coexist (Ubuntu 24.04), the reverse sort must pick 5.
    _patch_fs(
        monkeypatch,
        {
            "/usr/share/tesseract-ocr/4.00/tessdata",
            "/usr/share/tesseract-ocr/5/tessdata",
        },
        platform="linux",
        # Deliberately unsorted to prove the function sorts, not glob.
        glob_results=[
            "/usr/share/tesseract-ocr/4.00/tessdata",
            "/usr/share/tesseract-ocr/5/tessdata",
        ],
    )
    result = _find_tessdata("/usr/bin/tesseract")
    assert _norm(result) == "/usr/share/tesseract-ocr/5/tessdata"


def test_linux_versioned_wins_over_flat_usr_share(monkeypatch):
    # PR #146 review regression: for /usr/bin/tesseract the relative prefix
    # derivation yields the flat /usr/share/tessdata. If that derivation ran
    # before the versioned lookup (the bug), a stale /usr/share/tessdata
    # would shadow a newer /usr/share/tesseract-ocr/5/tessdata. Both dirs
    # exist here; the versioned lookup runs first, so 5 must win (issue #27).
    #
    # This test FAILS against the pre-fix ordering (which returned
    # /usr/share/tessdata) and PASSES once the versioned glob is checked
    # before the relative derivation.
    _patch_fs(
        monkeypatch,
        {
            "/usr/share/tessdata",
            "/usr/share/tesseract-ocr/5/tessdata",
        },
        platform="linux",
        glob_results=["/usr/share/tesseract-ocr/5/tessdata"],
    )
    result = _find_tessdata("/usr/bin/tesseract")
    assert _norm(result) == "/usr/share/tesseract-ocr/5/tessdata"


# ---------------------------------------------------------------------------
# nothing found
# ---------------------------------------------------------------------------
def test_nothing_found_returns_none(monkeypatch):
    _patch_fs(monkeypatch, set(), platform="darwin", glob_results=[])
    assert _find_tessdata("/opt/homebrew/bin/tesseract") is None


def test_none_binary_returns_none(monkeypatch):
    # No binary and no system paths -> None (never raises on tess_exe=None).
    _patch_fs(monkeypatch, set(), platform="linux", glob_results=[])
    assert _find_tessdata(None) is None


# ---------------------------------------------------------------------------
# step 2: versioned tessdata under the binary's own prefix (the snap fix),
# gated to linux/darwin. The tests that take tmp_path build the real layout
# there with _make_snap and fake only sys.platform, so they also run on a
# Windows host; three of them also set SNAP in the environment, and
# test_snap_chain_from_path_lookup also fakes shutil.which. The others use no
# tmp_path and fake os.path.isdir, glob.glob and sys.platform, as above; one
# of them, test_snap_lookup_follows_the_binary_not_the_snap_env, sets SNAP.
# ---------------------------------------------------------------------------
def _make_snap(root, versions=("4.00",)):
    """Build the slice of a PDFApps snap that matters for OCR under *root*
    and return ``(tesseract_path, {version: tessdata_dir})``."""
    bindir = root / "usr" / "bin"
    bindir.mkdir(parents=True)
    tess = bindir / "tesseract"
    tess.write_bytes(b"")
    dirs = {}
    for v in versions:
        d = root / "usr" / "share" / "tesseract-ocr" / v / "tessdata"
        d.mkdir(parents=True)
        (d / "eng.traineddata").write_bytes(b"")
        dirs[v] = str(d)
    return str(tess), dirs


def test_snap_versioned_tessdata_under_binary_prefix(monkeypatch, tmp_path):
    # The rev 43 failure: binary $SNAP/usr/bin/tesseract, data in
    # $SNAP/usr/share/tesseract-ocr/4.00/tessdata. Before the fix this
    # returned None (or, on a host with Tesseract installed, the host's
    # /usr/share/tesseract-ocr/<v>/tessdata, which a strict snap cannot see).
    snap = tmp_path / "snap" / "pdfapps" / "43"
    tess, dirs = _make_snap(snap)
    monkeypatch.setenv("SNAP", str(snap))
    monkeypatch.setattr(sys, "platform", "linux")
    assert _norm(_find_tessdata(tess)) == _norm(dirs["4.00"])


def test_snap_newest_version_wins_and_is_not_pinned_to_4_00(
        monkeypatch, tmp_path):
    # A core24 snap ships tesseract-ocr/5/tessdata; nothing may be pinned to
    # 4.00, and when two versions coexist the newest wins, as on the host.
    snap = tmp_path / "snap" / "pdfapps" / "50"
    tess, dirs = _make_snap(snap, versions=("4.00", "5"))
    monkeypatch.setenv("SNAP", str(snap))
    monkeypatch.setattr(sys, "platform", "linux")
    assert _norm(_find_tessdata(tess)) == _norm(dirs["5"])


def test_snap_versioned_wins_over_flat_share_tessdata(monkeypatch, tmp_path):
    # Same rule as issue #27, applied to the binary's prefix: a flat
    # <prefix>/share/tessdata must not shadow the versioned directory.
    snap = tmp_path / "snap" / "pdfapps" / "43"
    tess, dirs = _make_snap(snap)
    (snap / "usr" / "share" / "tessdata").mkdir()
    monkeypatch.setattr(sys, "platform", "linux")
    assert _norm(_find_tessdata(tess)) == _norm(dirs["4.00"])


def test_prefix_with_glob_metacharacters_is_matched_literally(
        monkeypatch, tmp_path):
    # The prefix is fed to glob: an install path containing [ ] must be
    # escaped, or the pattern matches nothing and OCR breaks again.
    root = tmp_path / "Tess [x86]"
    tess, dirs = _make_snap(root)
    monkeypatch.setattr(sys, "platform", "linux")
    assert _norm(_find_tessdata(tess)) == _norm(dirs["4.00"])


def test_snap_lookup_follows_the_binary_not_the_snap_env(monkeypatch):
    # SNAP leaks into processes started from a snapped terminal (e.g. the
    # VS Code snap). A system /usr/bin/tesseract must keep its own system
    # data even when a snap tree is on disk and SNAP is set.
    snap_dir = "/snap/pdfapps/43/usr/share/tesseract-ocr/4.00/tessdata"
    system_dir = "/usr/share/tesseract-ocr/5/tessdata"
    monkeypatch.setenv("SNAP", "/snap/pdfapps/43")
    patterns = []

    def _fake_glob(pattern):
        patterns.append(_norm(pattern))
        if _norm(pattern) == "/usr/share/tesseract-ocr/*/tessdata":
            return [system_dir]
        return []

    monkeypatch.setattr(os.path, "isdir", _fake_isdir({snap_dir, system_dir}))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(_glob, "glob", _fake_glob)
    assert _norm(_find_tessdata("/usr/bin/tesseract")) == system_dir
    assert not any(p.startswith("/snap/") for p in patterns)


def test_windows_never_globs_the_binary_prefix(monkeypatch):
    # The new prefix lookup is gated to linux/darwin like the existing
    # versioned glob: Windows resolution must not change at all.
    calls = []
    tess_exe = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    monkeypatch.setattr(os.path, "isdir", _fake_isdir(set()))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(_glob, "glob",
                        lambda pattern: calls.append(pattern) or [])
    assert _find_tessdata(tess_exe) is None
    assert calls == []


def test_windows_forward_slash_path_never_globs_the_binary_prefix(
        monkeypatch):
    # Same gate with a forward-slash path, which posixpath also splits: on a
    # Linux host the backslash-only path above derives an empty prefix and
    # would skip the prefix glob even without the platform gate. A versioned
    # tessdata exists under the derived prefix, so an ungated lookup would
    # both call glob and return it.
    calls = []
    tess_exe = "C:/Program Files/Tesseract-OCR/bin/tesseract.exe"
    versioned = "C:/Program Files/Tesseract-OCR/share/tesseract-ocr/5/tessdata"
    monkeypatch.setattr(os.path, "isdir", _fake_isdir({versioned}))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(_glob, "glob", _glob_over({versioned}, calls))
    assert _find_tessdata(tess_exe) is None
    assert calls == []


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_binary_prefix_versioned_wins_over_usr_share(monkeypatch, platform):
    # Step 2 runs before step 3: a binary under /usr/local that carries its
    # own versioned tessdata gets it ahead of /usr/share's, even when both
    # exist.
    local = "/usr/local/share/tesseract-ocr/5/tessdata"
    system = "/usr/share/tesseract-ocr/5/tessdata"
    monkeypatch.setattr(os.path, "isdir", _fake_isdir({local, system}))
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(_glob, "glob", _glob_over({local, system}))
    assert _norm(_find_tessdata("/usr/local/bin/tesseract")) == local


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_binary_prefix_lookup_on_a_prefix_no_host_has(monkeypatch, platform):
    # The prefix exists on no host, so only the patched glob.glob can find
    # the data: a module that bound glob at import time (``from glob import
    # glob``) bypasses the patch and returns None whether or not the host
    # has Tesseract. The darwin case pins that step 2 is not Linux-only.
    data = "/qa-nonexistent-prefix/share/tesseract-ocr/9/tessdata"
    tess_exe = "/qa-nonexistent-prefix/bin/tesseract"
    monkeypatch.setattr(os.path, "isdir", _fake_isdir({data}))
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(_glob, "glob", _glob_over({data}))
    assert _norm(_find_tessdata(tess_exe)) == data


def test_snap_chain_from_path_lookup(monkeypatch, tmp_path):
    # End to end over the two helpers, as _ensure_tesseract uses them: PATH
    # inside the snap resolves tesseract to $SNAP/usr/bin/tesseract, and
    # the tessdata found must be the one shipped next to it.
    from app.tools import _ocr_paths

    snap = tmp_path / "snap" / "pdfapps" / "43"
    tess, dirs = _make_snap(snap)
    monkeypatch.setenv("SNAP", str(snap))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(_ocr_paths.shutil, "which",
                        lambda name: tess if name == "tesseract" else None)
    found = _ocr_paths._find_tesseract()
    assert found == tess
    assert _norm(_ocr_paths._find_tessdata(found)) == _norm(dirs["4.00"])


# ---------------------------------------------------------------------------
# module boundary
# ---------------------------------------------------------------------------
def test_ocr_reexports_the_pure_helpers():
    # _ensure_tesseract resolves both names through app.tools.ocr's globals.
    from app.tools import _ocr_paths, ocr

    assert ocr._find_tessdata is _ocr_paths._find_tessdata
    assert ocr._find_tesseract is _ocr_paths._find_tesseract


# An allowlist, not a denylist of Qt and app: a denylist let relative
# imports (``from . import ocr``) and third-party Qt-adjacent modules such as
# shiboken6 and qtawesome through.
_OCR_PATHS_ALLOWED_IMPORTS = frozenset(
    {"__future__", "glob", "os", "shutil", "sys"})


def _disallowed_imports(source):
    """Every import in *source*, at any depth, that is relative or whose
    top-level module is outside the allowlist."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            bad.extend(a.name for a in node.names
                       if a.name.split(".")[0]
                       not in _OCR_PATHS_ALLOWED_IMPORTS)
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if node.level > 0 or top not in _OCR_PATHS_ALLOWED_IMPORTS:
                bad.append("." * node.level + (node.module or ""))
    return bad


def test_ocr_paths_module_imports_only_the_allowlist():
    path = (Path(__file__).resolve().parent.parent
            / "app" / "tools" / "_ocr_paths.py")
    assert _disallowed_imports(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("source", [
    "from . import ocr",
    "from .ocr import TabOCR",
    "import shiboken6",
    "import qtawesome",
    "from PySide6.QtCore import QObject",
    "import app.i18n",
    "from app.i18n import t",
    "def f():\n    import PySide6\n",
])
def test_import_allowlist_rejects(source):
    assert _disallowed_imports(source)


def test_import_allowlist_accepts_the_stdlib_it_names():
    assert _disallowed_imports(
        "from __future__ import annotations\nimport glob\nimport os.path\n"
        "from shutil import which\nimport sys\n") == []
