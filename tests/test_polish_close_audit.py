"""Source-level + behavioral regression tests for PR-L polish fixes.

Bug map (PR-L worklist — final audit close-out):
    #1  viewer recents use os.path.lexists (OneDrive Files-On-Demand)
    #2  Brand SVG icon DPR scaling honours actual displayDevicePixelRatio
    #3  import_pdf (txt-to-pdf) warns on non-Latin1 input characters
    #4  format_size_localized helper for KB/MB displays (5 callsites)
    #5  CONTRIBUTING.md config.json schema covers 5 keys
    #6  CONTRIBUTING.md documents environment variables
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── #1 — viewer recents use os.path.lexists ─────────────────────────────


def test_viewer_recents_uses_lexists():
    """app/viewer/panel.py:_refresh_recents must use os.path.lexists,
    not os.path.isfile, to avoid hydrating OneDrive Files-On-Demand
    placeholders on viewer startup. Matches the PR-G fix in
    app/i18n.py:_load_translations (line 290)."""
    src = _read("app/viewer/panel.py")
    # The recents loop must rely on lexists.
    assert "os.path.lexists(rp)" in src, (
        "viewer/panel.py recents loop must use os.path.lexists to "
        "skip OneDrive placeholder hydration."
    )
    # And the old isfile call must be gone from that loop (be tolerant
    # of other isfile uses elsewhere in the file by checking the local
    # window).
    idx = src.find("os.path.lexists(rp)")
    window = src[max(0, idx - 200): idx + 200]
    assert "os.path.isfile(rp)" not in window, (
        "Old isfile check must be removed from the recents loop."
    )


# ── #2 — Brand SVG icon DPR scaling ─────────────────────────────────────


def test_brand_icon_uses_dynamic_dpr():
    """app/window.py brand icon must scale by self.devicePixelRatioF()
    rather than the hardcoded 2.0 value. Same pattern PR-J #4 applied
    to PasswordDialog."""
    src = _read("app/window.py")
    # Look for the brand area construction.
    assert "brand_area" in src
    # devicePixelRatioF must be queried.
    assert "devicePixelRatioF()" in src, (
        "window.py must call devicePixelRatioF() when sizing the brand pixmap."
    )
    # The fixed 2.0 magic-number scaling must be gone.
    assert "setDevicePixelRatio(2.0)" not in src, (
        "Hardcoded setDevicePixelRatio(2.0) must be replaced by dynamic dpr."
    )
    # Defensive guard against dpr <= 0 should exist (PR-J #4 pattern).
    assert "dpr <= 0" in src or "dpr = 1.0" in src


# ── #3 — import_pdf txt-to-pdf CJK warning ──────────────────────────────


def test_import_pdf_txt_warns_on_non_latin1():
    """app/tools/import_pdf.py _convert_txt must emit the
    tool.warn.font_latin_only status when the input txt file contains
    codepoints above U+00FF, matching the existing page_numbers.py
    warning (PR-I L4)."""
    src = _read("app/tools/import_pdf.py")
    # The warning key must be referenced inside _convert_txt.
    convert_idx = src.find("def _convert_txt(")
    assert convert_idx != -1, "Expected _convert_txt method in import_pdf.py"
    # Grab a generous slice of that method.
    slice_ = src[convert_idx: convert_idx + 2500]
    assert "tool.warn.font_latin_only" in slice_, (
        "_convert_txt must surface tool.warn.font_latin_only for non-Latin1 input."
    )
    # The threshold guard must use ord(...) > 0xFF (Helvetica Latin-1 cap).
    assert "0xFF" in slice_ or "255" in slice_


# ── #4 — format_size_localized helper + 5 callsites ─────────────────────


def test_format_size_localized_helper_exists():
    """app/utils.py must export format_size_localized that delegates to
    QLocale and falls back gracefully when Qt is unavailable."""
    src = _read("app/utils.py")
    assert "def format_size_localized(" in src, (
        "app/utils.py must define format_size_localized helper."
    )
    assert "QLocale.system().toString" in src, (
        "format_size_localized must use QLocale.system().toString for i18n."
    )
    # Fallback path required for headless tests where Qt may fail to import.
    assert "except Exception" in src
    # Fallback returns the period-formatted value.
    assert "{value:." in src or "{value:.{decimals}f}" in src


def test_format_size_localized_callsites_updated():
    """The 5 identified callsites must use format_size_localized rather
    than raw f-string with `:.1f`."""
    # compress.py:108 — pages_info call.
    compress = _read("app/tools/compress.py")
    assert "format_size_localized" in compress
    # No more raw `:.1f` for size in compress.py.
    assert "size/1024:.1f" not in compress
    assert "size / 1024:.1f" not in compress

    # convert.py:174 — pages_info call.
    convert = _read("app/tools/convert.py")
    assert "format_size_localized" in convert
    assert "size/1024:.1f" not in convert
    assert "size / 1024:.1f" not in convert

    # info.py:83, 106 — 2 sites.
    info = _read("app/tools/info.py")
    assert "format_size_localized" in info
    assert "size/1024:.1f" not in info
    assert "size / 1024:.1f" not in info

    # editor/dialogs.py:120 — _TextEditDialog font_size label.
    dlg = _read("app/editor/dialogs.py")
    assert "format_size_localized" in dlg
    assert "font_size:.1f" not in dlg


def test_format_size_localized_runtime_behavior():
    """Calling the helper must yield a string with a decimal separator,
    even if QLocale is not available."""
    from app.utils import format_size_localized
    result = format_size_localized(1234.5)
    assert isinstance(result, str)
    # The result must contain either '.' or ',' as the decimal separator.
    assert "." in result or "," in result
    # Reasonable rounding: should not contain '.1234'-level precision past
    # the requested 1 decimal.
    # The integer part contains "1234" or a localized grouped form.
    digits = [c for c in result if c.isdigit()]
    assert len(digits) >= 5, f"expected ≥5 digits in {result!r}"


def test_format_size_localized_fallback_path():
    """When QLocale import raises, the helper must fall back to f-string."""
    import builtins
    import importlib
    import sys

    from app import utils

    # Save original import.
    real_import = builtins.__import__

    def blocking_import(name, *args, **kwargs):
        if name == "PySide6.QtCore" or name.startswith("PySide6.QtCore."):
            raise ImportError("simulated QtCore missing")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = blocking_import
    try:
        # Need to reimport so the inner ``from PySide6.QtCore import QLocale``
        # is reattempted; but the helper imports lazily inside the function,
        # so a fresh call is enough.
        result = utils.format_size_localized(3.5)
        assert result == "3.5", f"fallback path must yield '3.5', got {result!r}"
    finally:
        builtins.__import__ = real_import


# ── #5 — CONTRIBUTING.md config.json schema documents 5 keys ────────────


def test_contributing_config_schema_lists_five_keys():
    """CONTRIBUTING.md config.json schema must enumerate all five keys."""
    src = _read("CONTRIBUTING.md")
    assert "`config.json` schema" in src or "config.json schema" in src
    for key in (
        "`language`",
        "`dark_mode`",
        "`recent_files`",
        "`max_recent_files`",
        "`tool_usage`",
    ):
        assert key in src, f"CONTRIBUTING.md schema missing entry for {key}"
    # XDG / Windows path resolution must be mentioned.
    assert "XDG_CONFIG_HOME" in src
    assert ".pdfapps_config.json" in src


# ── #6 — CONTRIBUTING.md documents environment variables ────────────────


def test_contributing_documents_environment_variables():
    """CONTRIBUTING.md must contain an Environment Variables section that
    covers the platform vars, PyInstaller internals, and TESSDATA_PREFIX."""
    src = _read("CONTRIBUTING.md")
    assert "## Environment Variables" in src
    # Platform vars.
    for var in ("XDG_CONFIG_HOME", "FLATPAK_ID", "SNAP", "APPIMAGE", "APPDIR"):
        assert var in src, f"CONTRIBUTING.md env section missing {var}"
    # PyInstaller internals.
    for var in (
        "_PYI_APPLICATION_HOME_DIR",
        "_PYI_PARENT_PROCESS_LEVEL",
        "_PYI_ARCHIVE_FILE",
        "_MEIPASS",
    ):
        assert var in src, f"CONTRIBUTING.md env section missing {var}"
    # Tesseract.
    assert "TESSDATA_PREFIX" in src
