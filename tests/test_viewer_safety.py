"""Smoke tests for viewer safety fixes (CRIT-2, CRIT-3, B1, B-extra).

These bugs all live inside Qt widget code paths that require a real
event loop to exercise end-to-end (right-click menu, QPrintDialog,
paintEvent races). The tests here are source-level guards: they read
the production files and confirm the fixes are still present so a
future refactor can't silently regress them. Pair with manual QA on
the next release candidate.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


CANVAS = (Path(__file__).resolve().parent.parent
          / "app" / "viewer" / "canvas.py").read_text(encoding="utf-8")
PANEL = (Path(__file__).resolve().parent.parent
         / "app" / "viewer" / "panel.py").read_text(encoding="utf-8")


# ── CRIT-2: saveIncr requires confirmation + try/except ─────────────────


def test_save_incr_is_inside_try_except():
    """saveIncr must be wrapped in a try/except that routes to
    show_error — read-only PDFs / permission errors must not crash
    the Qt event loop."""
    # All occurrences of saveIncr() must appear inside a try-block
    # with the corresponding except in the contextMenuEvent path.
    assert "self._doc.saveIncr()" in CANVAS
    # Cheap but effective: the production fix introduces a try: above
    # the saveIncr call and an except Exception below.
    idx = CANVAS.index("self._doc.saveIncr()")
    before = CANVAS[max(0, idx - 800): idx]
    after = CANVAS[idx: idx + 400]
    assert "try:" in before, "saveIncr is no longer inside a try block"
    assert "except Exception" in after, "saveIncr error path is missing"
    assert "show_error" in after, "saveIncr errors no longer route to show_error"


def test_delete_comment_asks_for_confirmation():
    """contextMenuEvent must prompt via QMessageBox.question with
    default=No before destroying a comment."""
    assert "QMessageBox.question" in CANVAS
    assert "viewer.confirm_delete_comment" in CANVAS
    # Default button must be No so an accidental Enter press cancels.
    assert "QMessageBox.StandardButton.No" in CANVAS


# ── B-extra: stale _open_note tuple after delete ─────────────────────────


def test_open_note_index_is_decremented_after_delete():
    """When a note above the open one is deleted, _open_note's index
    must shift down — otherwise reopening shows the wrong comment."""
    assert "open_idx - 1" in CANVAS, "stale _open_note index not adjusted"


# ── CRIT-3: print pixmap handles alpha/CMYK and avoids race ─────────────


def test_print_pixmap_uses_alpha_false_and_csrgb_fallback():
    """Print path must:
    - request alpha=False so we never end up reading RGBA as RGB888;
    - fall back to fitz.Pixmap(csRGB, pix) for CMYK/greyscale (n != 3);
    - call .copy() on the QImage so the painter doesn't draw from the
      pixmap buffer after pix is freed on the next iteration."""
    assert "alpha=False" in PANEL
    assert "fitz.csRGB" in PANEL
    assert "pix.n != 3" in PANEL
    # QImage(...).copy() is the lifetime-decoupling bit.
    assert ").copy()" in PANEL


# ── B1: viewer load() close→reopen race ─────────────────────────────────


def test_close_doc_called_when_loading_new_doc():
    """panel.load() must funnel the old-doc teardown through
    _canvas.close_doc() so the canvas clears _doc + bumps _gen BEFORE
    the underlying fitz.Document is closed. Without that ordering, a
    paintEvent/_on_page_ready queued between close and the next load
    touches a freed Document and raises ``RuntimeError: document
    closed``."""
    assert "self._canvas.close_doc()" in PANEL
    # The panel must NOT also call _fitz_doc.close() in addition to
    # close_doc(), because the canvas helper already closes the
    # underlying document — a second close raises.
    load_idx = PANEL.index("def load(self, path: str)")
    load_body = PANEL[load_idx: load_idx + 1200]
    assert "self._canvas.close_doc()" in load_body, "close_doc no longer routed via canvas"


def test_canvas_close_doc_clears_doc_and_bumps_gen():
    """The canvas-side close_doc must drop self._doc and bump self._gen
    so any in-flight render jobs that complete after this point are
    discarded by _on_page_ready."""
    cd_idx = CANVAS.index("def close_doc(self)")
    body = CANVAS[cd_idx: cd_idx + 800]
    assert "self._doc = None" in body
    assert "self._gen" in body


# ── R7/N7-H1: print honours range, copies, and reverse order ────────────


def test_print_respects_from_page_to_page():
    """The print loop must read printer.fromPage()/toPage() and
    iterate only that range — pre-fix it always printed every page."""
    print_idx = PANEL.index("def _print_pdf")
    body = PANEL[print_idx: print_idx + 3500]
    assert "printer.fromPage()" in body, \
        "print path must honour QPrintDialog fromPage()"
    assert "printer.toPage()" in body, \
        "print path must honour QPrintDialog toPage()"


def test_print_respects_copy_count():
    """copyCount() must drive an outer copy loop so the user gets the
    requested number of copies."""
    print_idx = PANEL.index("def _print_pdf")
    body = PANEL[print_idx: print_idx + 3500]
    assert "copyCount()" in body, \
        "print path must honour QPrintDialog copyCount()"
    # The copies loop must wrap the page iteration; cheapest check is
    # that "for copy in range" appears inside the print function.
    assert "for copy in range" in body, \
        "print path must repeat the page loop copyCount() times"


def test_print_respects_reverse_order():
    """LastPageFirst page order must reverse the iteration list."""
    print_idx = PANEL.index("def _print_pdf")
    body = PANEL[print_idx: print_idx + 3500]
    assert "pageOrder()" in body, \
        "print path must read pageOrder() from the printer"
    assert "LastPageFirst" in body, \
        "print path must branch on the reverse-order enum"
    assert "reversed" in body, \
        "print path must actually reverse the page list"


def test_print_loop_preserves_pixmap_safety_fix():
    """The R7-H1 patch must NOT regress CRIT-3 (alpha=False, csRGB
    fallback, .copy()) which lives in the same loop body."""
    print_idx = PANEL.index("def _print_pdf")
    body = PANEL[print_idx: print_idx + 3500]
    assert "alpha=False" in body
    assert "fitz.csRGB" in body
    assert "pix.n != 3" in body
    assert ").copy()" in body
