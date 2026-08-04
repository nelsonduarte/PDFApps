"""Editor inline-edit UX quick-wins (issue #147).

Two low-risk discoverability/consistency wins are covered here:

  1. Clicking OUTSIDE an inline text edit now CONFIRMS it (Word-style),
     instead of silently discarding what the user typed. Enter/Tab still
     commit; Escape still discards. Switching editor modes mid-edit
     likewise commits (once) rather than throwing the edit away.

  2. The editor now STARTS in Text mode (the most useful, least
     destructive action) with a prominent hint, so users discover the
     click-to-edit interaction instead of landing in Redact.

All tests run headless with ``QT_QPA_PLATFORM=offscreen``.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fitz = pytest.importorskip("pymupdf")

from PySide6.QtCore import Qt, QEvent  # noqa: E402
from PySide6.QtGui import QFocusEvent, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


# A span dict shaped exactly like the ones the canvas passes to
# begin_inline_text_edit (text + bbox + style metadata).
_SPAN = {
    "text": "Original", "bbox": [10.0, 20.0, 110.0, 40.0],
    "size": 12.0, "color": 0, "font": "Helvetica", "flags": 0,
}


@pytest.fixture(scope="module")
def _app():
    return QApplication.instance() or QApplication([])


def _make_canvas(_app):
    from app.editor.canvas import PdfEditCanvas
    c = PdfEditCanvas()
    c.show()  # child _inline_edit is only isVisible() once an ancestor is
    return c


def _focus_out(widget):
    """Deliver a real FocusOut so it routes through the canvas eventFilter."""
    QApplication.sendEvent(widget, QFocusEvent(QEvent.Type.FocusOut))


def _press_escape(widget):
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                   Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, ev)


# ── PEDIDO 1: click-outside / focus-out confirms ─────────────────────────

def test_focus_out_commits_changed_edit(_app):
    """Editing a span then clicking away COMMITS the change (was: discard)."""
    c = _make_canvas(_app)
    committed = []
    c.text_edit_committed.connect(lambda p, e: committed.append(e))
    c.begin_inline_text_edit(_SPAN, 0)
    assert c._inline_edit.isVisible(), "precondition: inline editor shown"
    c._inline_edit.setText("Modified")

    _focus_out(c._inline_edit)

    assert len(committed) == 1, "focus-out must commit the edit exactly once"
    assert committed[0]["new_text"] == "Modified"
    assert committed[0]["type"] == "text_edit"
    # State fully reset so the hidden editor can't double-commit.
    assert c._inline_mode is None
    assert not c._inline_edit.isVisible()


def test_focus_out_unchanged_edit_creates_no_pending(_app):
    """A focus-out with no text change must NOT emit a spurious edit."""
    c = _make_canvas(_app)
    committed = []
    c.text_edit_committed.connect(lambda p, e: committed.append(e))
    c.begin_inline_text_edit(_SPAN, 0)  # text left == original

    _focus_out(c._inline_edit)

    assert committed == [], "unchanged edit must not create a pending edit"
    assert c._inline_mode is None  # still tidied up / hidden
    assert not c._inline_edit.isVisible()


def test_escape_still_discards_edit(_app):
    """Escape keeps its cancel semantics even though focus-out now commits."""
    c = _make_canvas(_app)
    committed = []
    c.text_edit_committed.connect(lambda p, e: committed.append(e))
    c.begin_inline_text_edit(_SPAN, 0)
    c._inline_edit.setText("Modified")

    _press_escape(c._inline_edit)

    assert committed == [], "Escape must discard, not commit"
    assert c._inline_mode is None
    assert not c._inline_edit.isVisible()


def test_focus_out_empty_insert_creates_no_pending(_app):
    """Focus-out on an empty INSERT must not insert whitespace-only text."""
    c = _make_canvas(_app)
    inserted = []
    c.text_inserted.connect(lambda p, e: inserted.append(e))
    c.begin_inline_text_insert(0, fitz.Point(30, 40), 12.0, (0, 0, 0),
                               "Helvetica")

    _focus_out(c._inline_edit)

    assert inserted == [], "empty insert must not create a pending edit"
    assert c._inline_mode is None


def test_focus_out_commits_nonempty_insert(_app):
    """Focus-out on a non-empty INSERT commits the new text exactly once."""
    c = _make_canvas(_app)
    inserted = []
    c.text_inserted.connect(lambda p, e: inserted.append(e))
    c.begin_inline_text_insert(0, fitz.Point(30, 40), 12.0, (0, 0, 0),
                               "Helvetica")
    c._inline_edit.setText("New text")

    _focus_out(c._inline_edit)

    assert len(inserted) == 1, "insert must commit exactly once on focus-out"
    assert inserted[0]["text"] == "New text"
    assert c._inline_mode is None


def test_focus_out_does_not_double_commit(_app):
    """The focus-out that hide() itself may trigger must not commit twice.

    _commit_inline resets ``_inline_mode`` to None *before* emitting, so any
    re-entrant focus-out early-returns. A second manual focus-out is a no-op.
    """
    c = _make_canvas(_app)
    committed = []
    c.text_edit_committed.connect(lambda p, e: committed.append(e))
    c.begin_inline_text_edit(_SPAN, 0)
    c._inline_edit.setText("Modified")

    _focus_out(c._inline_edit)
    _focus_out(c._inline_edit)  # extra focus-out on the now-hidden editor

    assert len(committed) == 1, "edit must be committed once, never twice"


# ── PEDIDO 1: switching modes mid-edit commits (once) ────────────────────

def test_mode_switch_commits_edit_once(_app):
    """Changing editor mode while editing COMMITS the in-progress edit."""
    from app.editor.tab import TabEditar, _MODE_TEXT
    tab = TabEditar(lambda *a, **k: None)
    tab.show()
    c = tab._canvas
    c.begin_inline_text_edit(_SPAN, 0)
    c._inline_edit.setText("Modified")
    before = len(tab._pending)

    # Switch away from Text (default) to Redact (index 0).
    tab._on_mode_btn(tab._mode_btns[0])

    assert len(tab._pending) == before + 1, "mode switch must commit the edit"
    assert tab._pending[-1]["new_text"] == "Modified"
    assert c._inline_mode is None
    assert tab._mode_idx == 0  # the new mode really took effect
    assert _MODE_TEXT == 1  # sanity on the constant used elsewhere


def test_mode_switch_unchanged_edit_no_spurious_pending(_app):
    """Switching modes with an untouched edit must not add a pending edit."""
    from app.editor.tab import TabEditar
    tab = TabEditar(lambda *a, **k: None)
    tab.show()
    c = tab._canvas
    c.begin_inline_text_edit(_SPAN, 0)  # unchanged text
    before = len(tab._pending)

    tab._on_mode_btn(tab._mode_btns[0])

    assert len(tab._pending) == before, "no spurious pending on unchanged edit"
    assert c._inline_mode is None


# ── PEDIDO 4: default Text mode + prominent hint ─────────────────────────

def test_editor_starts_in_text_mode(_app):
    """The editor boots into Text mode, not Redact (#147 discoverability)."""
    from app.editor.tab import TabEditar, _MODE_TEXT
    tab = TabEditar(lambda *a, **k: None)

    assert tab._mode_idx == _MODE_TEXT
    checked = [i for i, b in enumerate(tab._mode_btns) if b.isChecked()]
    assert checked == [_MODE_TEXT], "exactly the Text button is active"
    # The whole mode is wired, not just the button: options page, canvas
    # text-mode flag all follow.
    assert tab._opt_stack.currentIndex() == _MODE_TEXT
    assert tab._canvas._text_mode is True


def test_text_mode_hint_is_prominent(_app):
    """The Text-mode hint is shown and visually prominent (accent + bold)."""
    from app.i18n import t
    from app.constants import ACCENT
    from app.editor.tab import TabEditar
    tab = TabEditar(lambda *a, **k: None)

    assert tab._text_hint.text() == t("edit.hint.text")
    style = tab._text_hint.styleSheet().lower()
    assert ACCENT.lower() in style, "hint should use the accent colour"
    assert "bold" in style, "hint should be bold to stand out"
