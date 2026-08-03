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
   one generic step, checked right after the adjacent ``bin/tessdata``
   probe.
2. Add ``/opt/homebrew/share/tessdata`` to the fixed
   ``linux``/``darwin`` fallback list, for the case where the binary is
   resolved via ``PATH`` and the derived prefix does not match.

Nothing about the existing Windows-adjacent or Linux
``/usr/share/tesseract-ocr/<version>/tessdata`` (reverse-sorted)
behaviour changes.

These tests never touch the real filesystem or the real ``sys.platform``
— everything is monkeypatched so they run identically on the Windows and
Linux CI runners (there is no macOS runner).
"""

from __future__ import annotations

import glob as _glob
import os
import sys
from pathlib import Path

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


def _patch_fs(monkeypatch, existing, *, platform=None, glob_results=None):
    """Install a fake ``os.path.isdir`` (and optionally ``glob.glob`` /
    ``sys.platform``) covering exactly *existing*."""
    monkeypatch.setattr(os.path, "isdir", _fake_isdir(existing))
    if platform is not None:
        monkeypatch.setattr(sys, "platform", platform)
    if glob_results is not None:
        monkeypatch.setattr(_glob, "glob", lambda pattern: list(glob_results))


# ---------------------------------------------------------------------------
# prefix-relative derivation (platform independent — runs in the tess_exe
# block before any sys.platform check)
# ---------------------------------------------------------------------------
def test_apple_silicon_homebrew(monkeypatch):
    # <prefix>/bin/tesseract -> <prefix>/share/tessdata on /opt/homebrew.
    # Only the share/tessdata dir exists; the adjacent bin/tessdata does not.
    _patch_fs(monkeypatch, {"/opt/homebrew/share/tessdata"})
    result = _find_tessdata("/opt/homebrew/bin/tesseract")
    assert _norm(result) == "/opt/homebrew/share/tessdata"


def test_intel_homebrew_regression(monkeypatch):
    # /usr/local (Intel Homebrew) must keep working via the same derivation.
    _patch_fs(monkeypatch, {"/usr/local/share/tessdata"})
    result = _find_tessdata("/usr/local/bin/tesseract")
    assert _norm(result) == "/usr/local/share/tessdata"


def test_custom_prefix(monkeypatch):
    # A non-standard prefix proves the derivation is generic, not hard-coded.
    _patch_fs(monkeypatch, {"/opt/custom/share/tessdata"})
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
