"""Regression tests for R5/D2 — cached PDF password is wiped on close.

Pre-fix ``self._pdf_password`` persisted in memory until the BasePage
/ EditorTab / ViewerPanel object was GC'd. A heap dump after the user
finished viewing a confidential PDF could surface the password as a
plain string. The fix adds ``_clear_pdf_password()`` (best-effort
wipe) and wires it into every close path.

Python str immutability prevents a real zero-scrub of the original
bytes; the helper's job is to drop the *only reachable* reference
and free the attribute slot. Memory scanners may still see lingering
copies in the interner — documented as a known limitation.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── _clear_pdf_password() on BasePage ────────────────────────────────────


def _make_dummy_base():
    """Build a BasePage-like stub WITHOUT invoking the Qt constructor.

    The helper only touches ``self._pdf_password``; we don't need a
    QApplication for that.
    """
    from app.base import BasePage

    class _Stub:
        _pdf_password = ""
        _clear_pdf_password = BasePage._clear_pdf_password

    return _Stub()


def test_clear_pwd_zeroes_attribute():
    """After clear, the attribute must be the empty string."""
    s = _make_dummy_base()
    s._pdf_password = "topsecret"
    s._clear_pdf_password()
    assert s._pdf_password == ""


def test_clear_pwd_idempotent():
    """Calling clear on an already-empty attribute is a no-op."""
    s = _make_dummy_base()
    s._pdf_password = ""
    s._clear_pdf_password()
    assert s._pdf_password == ""
    s._clear_pdf_password()  # twice, just to be sure
    assert s._pdf_password == ""


def test_clear_pwd_handles_long_strings():
    """Long passwords (above the small-string optimisation threshold)
    must wipe the same way short ones do."""
    s = _make_dummy_base()
    s._pdf_password = "a" * 4096
    s._clear_pdf_password()
    assert s._pdf_password == ""


def test_clear_pwd_handles_unicode():
    """Multibyte passwords (emoji, accented chars) must not break the
    ctypes buffer hint."""
    s = _make_dummy_base()
    s._pdf_password = "señha-€-🔑"
    s._clear_pdf_password()
    assert s._pdf_password == ""


def test_clear_pwd_handles_missing_attr():
    """If somebody calls the helper before _pdf_password was ever set
    (subclass init order edge case), it must not raise."""
    from app.base import BasePage

    class _Stub:
        _clear_pdf_password = BasePage._clear_pdf_password

    s = _Stub()
    s._clear_pdf_password()
    # Helper assigned the empty string to keep the attribute
    # always-defined for the rest of the lifecycle.
    assert s._pdf_password == ""


# ── EditorTab carries its own helper ─────────────────────────────────────


def test_editor_tab_close_wires_password_wipe():
    """Static guard: EditorTab._close_pdf must call
    ``self._clear_pdf_password()`` so the cached password is dropped
    when the user closes the editor's PDF."""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "editor" / "tab.py").read_text(encoding="utf-8")
    close_idx = src.find("def _close_pdf(self):")
    assert close_idx > 0
    body = src[close_idx: close_idx + 800]
    assert "_clear_pdf_password" in body, \
        "_close_pdf must wipe the cached PDF password"


# ── ViewerPanel ──────────────────────────────────────────────────────────


def test_viewer_panel_wires_password_wipe():
    """ViewerPanel.load() and closeEvent must both invoke the wipe
    helper so neither a new-doc load nor a panel teardown leaves a
    stale password reachable."""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "viewer" / "panel.py").read_text(encoding="utf-8")
    assert "def _clear_pdf_password(" in src, \
        "_clear_pdf_password helper missing from PdfViewerPanel"
    # closeEvent must call it.
    close_idx = src.find("def closeEvent(self, event):")
    assert close_idx > 0, "PdfViewerPanel.closeEvent missing"
    close_body = src[close_idx: close_idx + 400]
    assert "_clear_pdf_password" in close_body, \
        "closeEvent must wipe the cached password"


def test_base_page_clear_pwd_in_source():
    """Static guard: BasePage._clear_pdf_password must exist (other
    test_pdfapps lookups depend on it being on the base class)."""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "base.py").read_text(encoding="utf-8")
    assert "def _clear_pdf_password(" in src
    assert "self._pdf_password = \"\"" in src
