"""Regression tests for the editor undo/redo stack (CRIT-1).

The bug: ``EditorTab._redo()`` called ``self._add(edit)``, and the
first line of ``_add`` was ``self._redo_stack.clear()``. After a
single redo, the remaining redo entries were silently dropped.

These tests exercise the post-fix invariant: consecutive redos
restore every undone edit, in the original LIFO order, without
ever wiping the redo stack mid-sequence. They avoid touching Qt
widgets by using a thin headless harness that mirrors the real
``_add/_undo/_redo`` semantics.
"""

import os
import sys
from pathlib import Path

import pytest

# Make project root importable so we can read EditorTab's source
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Headless harness ─────────────────────────────────────────────────────

class _UndoHarness:
    """Mirror EditorTab's _add/_undo/_redo without the Qt widgets.

    Only the fields touched by those three methods are reproduced —
    that's enough to assert the redo-stack invariant the bug broke."""

    _MAX_REDO = 100
    _MAX_PENDING = 500

    def __init__(self):
        self._pending: list = []
        self._redo_stack: list = []
        self._list_count = 0  # stand-in for _pending_list row count
        self.dropped_paths: list = []  # records temp paths the trim unlinked

    # Mirror of the real _add() post-fix:
    def _add(self, edit: dict, *, _from_redo: bool = False):
        import os
        import tempfile
        if not _from_redo:
            self._redo_stack.clear()
        self._pending.append(edit)
        self._list_count += 1
        if len(self._pending) > self._MAX_PENDING:
            to_drop = self._pending[:-self._MAX_PENDING]
            self._pending = self._pending[-self._MAX_PENDING:]
            tmp_root = os.path.normcase(tempfile.gettempdir())
            for old in to_drop:
                p = old.get("path")
                if (p and os.path.isfile(p)
                        and os.path.normcase(p).startswith(tmp_root)):
                    try:
                        os.unlink(p)
                        self.dropped_paths.append(p)
                    except OSError:
                        pass
            self._list_count = len(self._pending)

    def _undo(self):
        if not self._pending:
            return
        edit = self._pending.pop()
        self._redo_stack.append(edit)
        if len(self._redo_stack) > self._MAX_REDO:
            self._redo_stack.pop(0)
        self._list_count -= 1

    def _redo(self):
        if not self._redo_stack:
            return
        edit = self._redo_stack.pop()
        self._add(edit, _from_redo=True)


def _mk(i: int) -> dict:
    return {"type": "redact", "page": 0, "id": i}


# ── Tests ────────────────────────────────────────────────────────────────


def test_three_edits_three_undos_three_redos_restores_all():
    """3 edits → undo×3 → redo×3 leaves the same 3 edits in order.

    Pre-fix this test failed: after the first redo the redo stack
    was cleared, so the second and third redos were no-ops.
    """
    h = _UndoHarness()
    h._add(_mk(1))
    h._add(_mk(2))
    h._add(_mk(3))
    assert [e["id"] for e in h._pending] == [1, 2, 3]

    h._undo(); h._undo(); h._undo()
    assert h._pending == []
    assert [e["id"] for e in h._redo_stack] == [3, 2, 1]

    h._redo(); h._redo(); h._redo()
    assert [e["id"] for e in h._pending] == [1, 2, 3]
    assert h._redo_stack == []


def test_redo_preserves_remaining_stack():
    """A single redo only consumes one entry; the rest stay redoable.

    Sequence:
      add(0), add(1), add(2) -> _pending=[0,1,2], _redo=[]
      undo×3                  -> _pending=[],     _redo=[2,1,0] (LIFO)
      redo                    -> _pending=[0],    _redo=[2,1]

    The bug being guarded: pre-fix the redo would clear the stack so
    _redo would become [] and the next two redo calls would be no-ops.
    """
    h = _UndoHarness()
    for i in range(3):
        h._add(_mk(i))
    for _ in range(3):
        h._undo()
    h._redo()  # restores id=0 (pushed first into redo_stack -> top)
    assert [e["id"] for e in h._pending] == [0]
    # The remaining redo entries must still be present — this is
    # exactly what the bug broke.
    assert [e["id"] for e in h._redo_stack] == [2, 1]


def test_new_edit_after_undo_clears_redo():
    """New edits MUST still clear the redo stack (normal _add path)."""
    h = _UndoHarness()
    h._add(_mk(1)); h._add(_mk(2))
    h._undo()
    assert [e["id"] for e in h._redo_stack] == [2]
    # User performs a new edit instead of redoing — redo branch
    # is discarded as expected.
    h._add(_mk(99))
    assert h._redo_stack == []


def test_editor_tab_source_matches_fix():
    """Static check: the real EditorTab._redo passes _from_redo=True
    and _add accepts the kwarg. Guards against accidental regressions
    in the production code (we can't easily import the Qt class here
    without instantiating QWidget)."""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "editor" / "tab.py").read_text(encoding="utf-8")
    assert "_from_redo: bool = False" in src, "the fix kwarg is missing from _add"
    assert "_from_redo=True" in src, "_redo no longer flags the call as redo"
    assert "if not _from_redo:" in src, "_add no longer gates the redo_stack clear"


# ── R5/A2: _pending unbounded growth ─────────────────────────────────────


def test_pending_caps_at_max():
    """Adding 600 edits leaves _pending at MAX_PENDING (500) with the
    100 oldest dropped.

    Pre-fix _pending grew without bound; long-edit sessions leaked
    memory and pinned temp signature/image files until the tab
    closed.
    """
    h = _UndoHarness()
    for i in range(600):
        h._add({"type": "redact", "page": 0, "id": i})
    assert len(h._pending) == h._MAX_PENDING
    # Oldest dropped: the surviving range starts at id=100.
    ids = [e["id"] for e in h._pending]
    assert ids[0] == 100
    assert ids[-1] == 599
    # _pending_list shadow must stay in sync — otherwise the QListWidget
    # rows diverge from the underlying edit indices.
    assert h._list_count == len(h._pending)


def test_pending_trim_unlinks_temp_files(tmp_path, monkeypatch):
    """When an edit dropped by the trim owns a temp-file path, the
    file must be unlinked. Files outside the system tempdir (real
    source images the user picked) must be left alone."""
    import tempfile as _tf
    # Force the tempdir to our pytest tmp so we don't pollute the real
    # /tmp during the test.
    monkeypatch.setattr(_tf, "gettempdir", lambda: str(tmp_path))

    h = _UndoHarness()
    # First 50 edits own real temp files; the remaining 600 are simple
    # redacts. The trim will drop the first 150 entries (650 - 500), so
    # all 50 temp files belong to the dropped slice.
    temp_paths = []
    for i in range(50):
        p = tmp_path / f"sig_{i}.png"
        p.write_bytes(b"PNG_BYTES")
        temp_paths.append(str(p))
        h._add({"type": "signature", "page": 0, "path": str(p)})

    # Add a user-owned image OUTSIDE the tempdir (simulate real source
    # picked from Desktop). It will get trimmed too but must NOT be
    # deleted from disk.
    user_dir = tmp_path.parent / "user_pick"
    user_dir.mkdir(exist_ok=True)
    user_path = user_dir / "real_image.png"
    user_path.write_bytes(b"PNG_USER")
    h._add({"type": "image", "page": 0, "path": str(user_path)})

    for i in range(600):
        h._add({"type": "redact", "page": 0, "id": i})

    assert len(h._pending) == h._MAX_PENDING
    # Every temp file the harness owned should have been unlinked.
    for p in temp_paths:
        assert not os.path.isfile(p), f"trim must unlink dropped temp: {p}"
    # The user-picked image must survive disk-side even though it
    # fell out of the rolling window.
    assert os.path.isfile(user_path), "user-picked file must not be deleted"


def test_undo_empty_pending_is_noop():
    """After trim drops oldest edits the undo button still works
    cleanly — calling _undo on an empty list returns silently rather
    than raising IndexError."""
    h = _UndoHarness()
    # Empty start
    h._undo()
    assert h._pending == []
    assert h._redo_stack == []
    # After a full trim cycle then drain-undo, the next undo must
    # also be a no-op.
    for i in range(550):
        h._add({"type": "redact", "page": 0, "id": i})
    while h._pending:
        h._undo()
    h._undo()  # extra undo on an already-empty stack
    assert h._pending == []


def test_pending_max_constants_in_source():
    """Static guard: the production constants must exist and the
    trim block must reference both _MAX_PENDING and a tempdir check."""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "editor" / "tab.py").read_text(encoding="utf-8")
    assert "_MAX_PENDING" in src, "production constant missing"
    assert "tempfile.gettempdir" in src, \
        "trim must restrict unlink to the system tempdir"


# ── PR-B revisor finding #1 — QListWidget vs _pending drift ─────────────


def test_pending_list_widget_count_matches_pending_after_trim():
    """The real QListWidget must stay in sync with ``_pending`` after
    the cap-trim. Regression for PR-B revisor finding #1.

    Pre-fix the trim computed ``extra = list.count() - len(_pending)``
    *before* the new edit's ``addItem`` ran. In steady state at the
    cap, that diff was 0 so no ``takeItem`` ever fired, and the
    subsequent ``addItem`` left the QListWidget with +1 row vs the
    underlying ``_pending`` list. The next ``_undo`` then removed the
    wrong label (the visible most-recent row, not the row matching the
    popped edit).
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QListWidget
    _app = QApplication.instance() or QApplication([])  # noqa: F841

    from app.editor.tab import TabEditar

    class _Canvas:
        def set_overlays(self, *a, **kw): pass

    class _Stub:
        _MAX_PENDING = TabEditar._MAX_PENDING
        _MAX_REDO = TabEditar._MAX_REDO

        def __init__(self):
            self._pending: list = []
            self._redo_stack: list = []
            self._pending_list = QListWidget()
            self._canvas = _Canvas()

        def _status(self, *a, **kw): pass

        # Bind the real production method so we test the real code path.
        _add = TabEditar._add
        _undo = TabEditar._undo

    s = _Stub()

    # Push past the cap by 50 edits.
    for i in range(TabEditar._MAX_PENDING + 50):
        s._add({"type": "redact", "page": 0, "id": i})

    assert len(s._pending) == TabEditar._MAX_PENDING, \
        "production trim should bound _pending to _MAX_PENDING"
    assert s._pending_list.count() == len(s._pending), (
        f"QListWidget rows ({s._pending_list.count()}) drifted from "
        f"_pending size ({len(s._pending)}) — PR-B finding #1 regressed"
    )

    # _undo must remove the row matching the popped edit, leaving the
    # widget and the list in lock-step. Pre-fix the widget would be 1
    # row ahead so an undo would take the wrong label.
    before_count = s._pending_list.count()
    s._undo()
    assert s._pending_list.count() == len(s._pending)
    assert s._pending_list.count() == before_count - 1
