"""Regression tests for the screenChanged signal binding pattern
in viewer/editor canvases.

Prior to this fix, ``showEvent`` called ``disconnect`` before ``connect``
in a ``contextlib.suppress(TypeError, RuntimeError)`` block. Under
PySide6 6.11 the "signal was never connected" case emits a
RuntimeWarning rather than raising, so the suppress didn't catch it
and the following warning showed up on the very first show::

    libpyside: Failed to disconnect (<bound method
    _SelectCanvas._on_screen_changed>) from signal
    "screenChanged(QScreen*)"

The fix tracks the previously-connected QWindow in
``_screen_signal_window`` and only calls ``disconnect`` when the
top-level window actually changes (e.g. widget was reparented).
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

VIEWER_CANVAS = _REPO_ROOT / "app" / "viewer" / "canvas.py"
EDITOR_CANVAS = _REPO_ROOT / "app" / "editor" / "canvas.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _show_event_block(src: str) -> str:
    """Return the source of the first ``def showEvent`` in src (best-effort)."""
    idx = src.find("def showEvent(")
    assert idx >= 0, "showEvent not found"
    return src[idx:idx + 1500]


# ── Guard 1: tracker attribute exists on both canvases ─────────────────────

def test_viewer_canvas_tracks_screen_signal_window():
    src = _read(VIEWER_CANVAS)
    assert "_screen_signal_window" in src or "UniqueConnection" in src, (
        "_SelectCanvas.showEvent should either track the connected window "
        "or use Qt.UniqueConnection to avoid the disconnect-before-connect "
        "RuntimeWarning."
    )


def test_editor_canvas_tracks_screen_signal_window():
    src = _read(EDITOR_CANVAS)
    assert "_screen_signal_window" in src or "UniqueConnection" in src, (
        "PdfEditCanvas.showEvent should either track the connected window "
        "or use Qt.UniqueConnection to avoid the disconnect-before-connect "
        "RuntimeWarning."
    )


# ── Guard 2: tracker attribute is initialised in __init__ ─────────────────

def test_viewer_canvas_tracker_initialised_in_init():
    src = _read(VIEWER_CANVAS)
    # UniqueConnection alternative would not need the attribute.
    if "UniqueConnection" in src:
        return
    # The tracker must be initialised (assigned to None) somewhere in
    # __init__, otherwise the first showEvent hits AttributeError.
    assert "self._screen_signal_window = None" in src, (
        "_SelectCanvas.__init__ must initialise _screen_signal_window = None"
    )


def test_editor_canvas_tracker_initialised_in_init():
    src = _read(EDITOR_CANVAS)
    if "UniqueConnection" in src:
        return
    assert "self._screen_signal_window = None" in src, (
        "PdfEditCanvas.__init__ must initialise _screen_signal_window = None"
    )


# ── Guard 3: no bare disconnect + connect in showEvent ────────────────────

def test_no_bare_disconnect_before_connect_viewer():
    """The old anti-pattern was ``disconnect`` on every showEvent even when
    nothing was previously connected. Ensure any remaining ``disconnect``
    call is guarded by a prior-window check."""
    src = _read(VIEWER_CANVAS)
    block = _show_event_block(src)
    if "screenChanged.disconnect" not in block:
        return  # UniqueConnection-only path is fine too
    assert any(
        marker in block
        for marker in (
            "prev_win",
            "prev is not None",
            "getattr",
            "_screen_signal_window",
            "UniqueConnection",
        )
    ), (
        "viewer canvas showEvent: disconnect must be guarded by a "
        "prior-window check, not called unconditionally on every show."
    )


def test_no_bare_disconnect_before_connect_editor():
    src = _read(EDITOR_CANVAS)
    block = _show_event_block(src)
    if "screenChanged.disconnect" not in block:
        return
    assert any(
        marker in block
        for marker in (
            "prev_win",
            "prev is not None",
            "getattr",
            "_screen_signal_window",
            "UniqueConnection",
        )
    ), (
        "editor canvas showEvent: disconnect must be guarded by a "
        "prior-window check, not called unconditionally on every show."
    )


# ── Guard 4: same-window re-show is a no-op ───────────────────────────────

def test_viewer_showevent_short_circuits_on_same_window():
    """When win is the same object as _screen_signal_window we must
    return early. Otherwise we'd still call connect() and stack a
    duplicate handler."""
    src = _read(VIEWER_CANVAS)
    if "UniqueConnection" in src:
        return
    block = _show_event_block(src)
    assert "win is prev_win" in block or "win == prev_win" in block, (
        "viewer canvas showEvent must short-circuit when the top-level "
        "QWindow hasn't changed since the previous show."
    )


def test_editor_showevent_short_circuits_on_same_window():
    src = _read(EDITOR_CANVAS)
    if "UniqueConnection" in src:
        return
    block = _show_event_block(src)
    assert "win is prev_win" in block or "win == prev_win" in block, (
        "editor canvas showEvent must short-circuit when the top-level "
        "QWindow hasn't changed since the previous show."
    )
