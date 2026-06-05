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

    def __init__(self):
        self._pending: list = []
        self._redo_stack: list = []
        self._list_count = 0  # stand-in for _pending_list row count

    # Mirror of the real _add() post-fix:
    def _add(self, edit: dict, *, _from_redo: bool = False):
        if not _from_redo:
            self._redo_stack.clear()
        self._pending.append(edit)
        self._list_count += 1

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
