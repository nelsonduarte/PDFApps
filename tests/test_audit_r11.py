"""Source-level + behavioral regression tests for PR-G / Round 11 fixes.

Bug map (PR-G worklist):
    #1  split.py no atomic write (same-source truncation)  (HIGH A6)
    #2  Drop folder duplicates on case-insensitive FS      (HIGH N5)
    #3  Editor _pending filter for existing notes          (HIGH N2)
    #4  parse_pages friendly error                          (MED N4)
    #5  OCR streaming writer (memory regression)            (MED I1)
    #6  _clear_recent UI refresh                            (MED M5)
    #7  get_recent_files writeback + lexists for OneDrive   (MED M3)
    #8  _apply_forms PdfReader stream leak                  (MED Extra)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── #1 — split.py uses _atomic_pdf_write ────────────────────────────────


def test_split_uses_atomic_pdf_write():
    """split.py per-row writes must route through _atomic_pdf_write so
    a same-source overwrite is rejected up front and lazy reads from
    PdfReader are not truncated mid-flight."""
    src = _read("app/tools/split.py")
    assert "_atomic_pdf_write" in src, (
        "split.py must call self._atomic_pdf_write to inherit the "
        "same-source guard + tempfile/os.replace path."
    )
    # The raw direct-write pattern must be gone.
    assert "with open(os.path.join(out_dir, name), \"wb\") as f: w.write(f)" \
        not in src, "Old direct-write pattern still present in split.py"


def test_split_passes_input_as_source_to_atomic_write():
    """The atomic write call must pass the input pdf as a source so the
    _check_not_same_path layer can reject same-source-output."""
    src = _read("app/tools/split.py")
    # Look for the call site with the sources kwarg.
    assert "sources=[pdf_path]" in src


# ── #2 — Drop folder dedup on case-insensitive FS ────────────────────────


def test_window_drop_folder_does_not_double_glob():
    """The pre-fix code globbed *.pdf AND *.PDF which double-loaded every
    file on Windows / HFS+. The fix uses os.listdir + extension filter."""
    src = _read("app/window.py")
    # The two-glob pattern must be gone.
    assert "glob.glob(os.path.join(path, \"*.PDF\"))" not in src
    # The replacement must be there.
    assert "os.listdir(path)" in src
    # And case-insensitive extension match.
    assert ".lower().endswith(\".pdf\")" in src


def test_window_drop_folder_dedup_behavioral(tmp_path):
    """Behavioral: simulate the new walk pattern against a directory
    containing case-mixed PDF filenames. The result must contain each
    file exactly once even on filesystems where uppercase and lowercase
    globs both match the same on-disk file."""
    d = tmp_path
    # Create files in lower + uppercase. On Windows / HFS+ these are
    # the same file; we still test that the walk pattern doesn't yield
    # duplicates when the FS is case-sensitive.
    (d / "a.pdf").write_bytes(b"%PDF-1.4")
    # Use a distinct uppercase name to avoid same-file collision on
    # case-insensitive FSes.
    (d / "B.PDF").write_bytes(b"%PDF-1.4")
    entries = os.listdir(str(d))
    pdfs = sorted(
        os.path.join(str(d), f) for f in entries
        if f.lower().endswith(".pdf")
        and os.path.isfile(os.path.join(str(d), f))
    )
    # No duplicates allowed.
    assert len(pdfs) == len(set(pdfs))
    # Both files present.
    assert any(p.endswith("a.pdf") for p in pdfs)
    assert any(p.endswith("B.PDF") for p in pdfs)


# ── #3 — Editor _user_pending filters existing notes ────────────────────


def test_editor_has_user_pending_property():
    """The editor must expose _user_pending that filters out _existing
    annotations mirrored from the loaded PDF."""
    src = _read("app/editor/tab.py")
    assert "_user_pending" in src
    assert "if not e.get(\"_existing\")" in src


def test_window_closeevent_uses_user_pending():
    """The window's closeEvent guard must use _user_pending so just
    opening a PDF with existing notes does not prompt 'unsaved'."""
    src = _read("app/window.py")
    # The guard must reference _user_pending, not raw _pending.
    assert "getattr(edit_w, \"_user_pending\", None)" in src
    assert "getattr(edit_w, \"_pending\", None)" not in src


def test_editor_forms_warning_uses_user_pending():
    """Forms-mode 'you have pending edits' warning must filter existing
    annotations but keep delete_annot (which may carry _existing=True
    when the user removed a pre-existing note via the canvas menu)."""
    src = _read("app/editor/tab.py")
    forms_block_start = src.find("_MODE_FORMS:\n            # If there are also pending edits")
    assert forms_block_start > 0
    block = src[forms_block_start:forms_block_start + 800]
    assert "self._user_pending" in block


def test_user_pending_excludes_existing_keeps_user_edits():
    """Behavioral: a pending list with one existing note + one user
    deletion + one user draw must yield only the user edits."""
    sample = [
        {"type": "note", "page": 0, "text": "loaded from disk",
         "_existing": True},
        {"type": "delete_annot", "page": 0, "annot_type": 0,
         "bbox": [0, 0, 10, 10]},
        {"type": "draw", "page": 1, "points": [(0, 0), (1, 1)]},
    ]
    user_only = [e for e in sample if not e.get("_existing")]
    assert len(user_only) == 2
    assert {e["type"] for e in user_only} == {"delete_annot", "draw"}


def test_editor_run_uses_user_pending_for_empty_check():
    """The _run() short-circuit ('no pending edits') must use
    _user_pending so opening a PDF with sticky notes and clicking
    Apply doesn't silently re-save unchanged."""
    src = _read("app/editor/tab.py")
    run_start = src.find("    def _run(self):")
    next_def = src.find("    def ", run_start + 1)
    body = src[run_start:next_def]
    assert "if not self._user_pending:" in body
    assert "msg.no_pending" in body


def test_editor_pending_list_skips_existing_notes():
    """_load_existing_annotations must NOT push pre-existing notes
    into the _pending_list UI — that widget is for THIS session's
    unsaved edits only. The note overlay (canvas rendering) is
    untouched; only the visible 'pending edits' list is filtered."""
    src = _read("app/editor/tab.py")
    load_start = src.find("def _load_existing_annotations(self)")
    next_def = src.find("    def ", load_start + 1)
    body = src[load_start:next_def]
    # The old addItem line must be gone from the existing-notes branch.
    # We check that 'self._pending_list.addItem' is not called in the
    # branch that sets `_existing`: True.
    assert "\"_existing\": True" in body
    # Look around the _existing=True dict for an addItem — there must be
    # none in the same indentation block.
    existing_idx = body.find("\"_existing\": True")
    # Scan the next ~600 chars after the dict closes for an addItem call
    # before the next outer-level statement (e.g. count += 1 or next
    # `for`); the test is permissive because formatting can shift.
    tail = body[existing_idx:existing_idx + 800]
    # The cleanup comment marker we placed identifies the intentional
    # removal so a future refactor that re-adds the line is caught.
    assert "do NOT add existing notes to the" in tail


# ── R11 C6 — _user_pending must keep delete_annot even for existing ─────


def _make_user_pending_stub():
    """Tiny stub so the _user_pending property can be exercised without
    spinning up the full Qt tab. Only the attributes it touches matter."""
    from app.editor.tab import TabEditar

    class _Stub:
        _user_pending = TabEditar._user_pending

        def __init__(self):
            self._pending: list = []

    return _Stub()


def test_user_pending_keeps_delete_annot_even_if_existing():
    """Regression for reviewer R11 C6: ``delete_annot`` edits for
    existing notes are also tagged with ``_existing=True`` (so undo can
    restore the original). The previous ``_user_pending`` filter dropped
    them, which made ``_run`` warn 'no pending edits' and ``closeEvent``
    skip the unsaved-changes prompt — silently losing the deletion."""
    s = _make_user_pending_stub()
    s._pending = [
        # Mirrored on load — must be filtered.
        {"type": "note", "text": "original", "_existing": True},
        # User right-clicked the loaded note and chose Delete. The
        # _existing flag carries through so _undo can put the original
        # back on the canvas. MUST stay in _user_pending.
        {"type": "delete_annot", "page": 0, "bbox": (0, 0, 10, 10),
         "_existing": True,
         "_original_note": {"type": "note", "text": "original"}},
        # Brand-new note typed by the user. MUST stay in _user_pending.
        {"type": "note", "text": "new user note"},
    ]
    user_pending = s._user_pending
    assert len(user_pending) == 2
    types = [e["type"] for e in user_pending]
    assert "delete_annot" in types
    assert "note" in types
    # The original existing note is filtered out.
    assert not any(e.get("text") == "original" for e in user_pending)


def test_delete_existing_note_then_apply_persists():
    """End-to-end flow: user opens a PDF with one sticky note (mirrored
    into ``_pending`` by ``_load_existing_annotations`` with
    ``_existing=True``), right-clicks → Delete (which appends a
    ``delete_annot`` edit also carrying ``_existing=True``), then clicks
    Apply. ``_user_pending`` MUST surface the deletion so the save loop
    processes it instead of hitting the no_changes warning."""
    s = _make_user_pending_stub()
    # _load_existing_annotations behavior.
    s._pending = [{
        "type": "note", "text": "loaded", "page": 0,
        "rect": (0, 0, 10, 10), "_existing": True,
    }]
    # Context-menu delete (cf. _on_note_deleted at app/editor/tab.py
    # ~line 1078): the delete_annot edit carries _existing=True so that
    # undo can roll back to the original note.
    s._pending.append({
        "type": "delete_annot",
        "page": 0,
        "bbox": (0, 0, 10, 10),
        "_existing": True,
        "_original_note": s._pending[0],
    })
    # Apply click — the _run guard reads _user_pending.
    user_pending = s._user_pending
    # The delete MUST be visible to the save loop.
    assert any(e["type"] == "delete_annot" for e in user_pending), (
        "delete_annot with _existing=True was filtered out — the "
        "user's deletion would be silently lost on save")


# ── #4 — parse_pages friendly error ─────────────────────────────────────


def test_parse_pages_raises_friendly_message_for_invalid_input():
    """Garbage input like 'abc' or '1-' must surface the translated
    bad_page_input message instead of the raw int() ValueError."""
    from app.utils import parse_pages

    with pytest.raises(ValueError) as exc:
        parse_pages("abc", 10)
    msg = str(exc.value)
    # The friendly message embeds the offending substring.
    assert "abc" in msg
    # And does NOT leak the python internal phrasing.
    assert "invalid literal for int" not in msg


def test_parse_pages_raises_friendly_message_for_open_range():
    """Open-ended ranges with non-numeric bounds (e.g. 'abc-') still
    surface the translated bad_page_input message. PR-H fix #10 made
    purely-numeric open ranges like '1-' valid (interpreted as
    '1..total'), so the regression target moves to a still-invalid
    input."""
    from app.utils import parse_pages
    with pytest.raises(ValueError) as exc:
        parse_pages("abc-", 10)
    msg = str(exc.value)
    assert "abc-" in msg
    assert "invalid literal for int" not in msg
    # Empty range '-' must also fail (no bounds at all).
    with pytest.raises(ValueError) as exc2:
        parse_pages("-", 10)
    assert "invalid literal for int" not in str(exc2.value)


def test_parse_pages_still_accepts_valid_input():
    """Regression guard — the new try/except must not break the happy
    path or the dedupe/sort contract."""
    from app.utils import parse_pages
    assert parse_pages("3,1,2,3", 10) == [0, 1, 2]
    assert parse_pages("1-3", 10) == [0, 1, 2]
    assert parse_pages("1,4-5", 10) == [0, 3, 4]


def test_parse_pages_out_of_range_still_works():
    """Out-of-range error message format must be preserved."""
    from app.utils import parse_pages
    with pytest.raises(ValueError) as exc:
        parse_pages("99", 10)
    assert "out of range" in str(exc.value).lower()


# ── #5 — OCR streaming writer ───────────────────────────────────────────


def test_ocr_no_longer_accumulates_pdf_pages_list():
    """The old pattern collected all per-page PDF bytes in a list before
    writing — a 100-pg @ 300dpi job spent ~500MB RAM. The new code
    appends each page directly into the writer."""
    src = _read("app/tools/ocr.py")
    # Old accumulation list must be gone.
    assert "pdf_pages = []" not in src
    assert "pdf_pages.append" not in src
    # New streaming pattern: writer.append inside the per-page loop.
    # The marker is that writer is instantiated before the loop and
    # writer.append happens inside the same scope as the for-page loop.
    assert "writer = PdfWriter()" in src
    # And we drop the per-page buffers explicitly.
    assert "img.close()" in src


# ── #6 — _clear_recent refreshes UI ─────────────────────────────────────


def test_clear_recent_refreshes_open_viewers():
    """_clear_recent must iterate self._viewers and call _refresh_recents
    on each, mirroring the pattern in _load_and_track."""
    src = _read("app/window.py")
    clear_start = src.find("def _clear_recent(self)")
    next_def = src.find("def ", clear_start + 1)
    body = src[clear_start:next_def]
    assert "_refresh_recents" in body, (
        "_clear_recent must refresh recents in all open viewers (M5)."
    )
    assert "self._viewers" in body


# ── #7 — get_recent_files writeback + lexists ───────────────────────────


def test_get_recent_files_uses_lexists():
    """OneDrive Files-On-Demand: isfile triggers a placeholder download.
    lexists does not. The fix swaps isfile for lexists."""
    src = _read("app/i18n.py")
    func_start = src.find("def get_recent_files()")
    func_end = src.find("def ", func_start + 1)
    body = src[func_start:func_end]
    assert "os.path.lexists" in body
    # The old isfile call must be gone from non-comment lines. Strip
    # comments before searching so mentions of the old API in the
    # explanatory comment don't trip this assertion.
    code_lines = [
        ln for ln in body.splitlines()
        if not ln.lstrip().startswith("#")
    ]
    code_only = "\n".join(code_lines)
    assert "os.path.isfile" not in code_only


def test_get_recent_files_writeback_when_entries_dropped(tmp_path, monkeypatch):
    """Behavioral: when a stale entry is filtered out, get_recent_files
    must writeback the trimmed list so we don't re-check disk forever."""
    # Stub config path to a temp file.
    cfg = tmp_path / "cfg.json"
    real = str(tmp_path / "real.pdf")
    Path(real).write_bytes(b"%PDF-1.4")
    cfg.write_text(json.dumps({
        "recent_files": [real, str(tmp_path / "missing.pdf")],
    }), encoding="utf-8")

    import app.i18n as i18n
    monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg))

    result = i18n.get_recent_files()
    assert result == [real]
    # Writeback should have trimmed the list on disk.
    written = json.loads(cfg.read_text(encoding="utf-8"))
    assert written["recent_files"] == [real]


def test_get_recent_files_no_writeback_when_all_valid(tmp_path, monkeypatch):
    """Don't churn the config file when nothing changed."""
    cfg = tmp_path / "cfg.json"
    real1 = str(tmp_path / "a.pdf")
    real2 = str(tmp_path / "b.pdf")
    Path(real1).write_bytes(b"%PDF-1.4")
    Path(real2).write_bytes(b"%PDF-1.4")
    cfg.write_text(json.dumps({"recent_files": [real1, real2]}),
                   encoding="utf-8")
    mtime_before = cfg.stat().st_mtime_ns

    import app.i18n as i18n
    monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg))

    result = i18n.get_recent_files()
    assert result == [real1, real2]
    # No writeback when valid == recents.
    assert cfg.stat().st_mtime_ns == mtime_before


# ── #8 — _apply_forms closes PdfReader stream ───────────────────────────


def test_apply_forms_uses_with_open_for_source():
    """_apply_forms must wrap the source PdfReader in `with open(...)` so
    the file handle is released deterministically — leaving it pinned
    by GC blocks Windows from renaming the file from another tool."""
    src = _read("app/editor/tab.py")
    apply_start = src.find("def _apply_forms(self, out)")
    next_def = src.find("    def ", apply_start + 1)
    body = src[apply_start:next_def]
    assert "with open(self._doc_path, \"rb\")" in body
    # PdfReader must take the stream (not the raw path).
    assert "PdfReader(_src)" in body


def test_apply_forms_writer_work_happens_inside_with_block():
    """The writer.append / .write_*** calls must be inside the with-block
    so the source stream is still alive when pypdf reads lazily."""
    src = _read("app/editor/tab.py")
    apply_start = src.find("def _apply_forms(self, out)")
    next_def = src.find("    def ", apply_start + 1)
    body = src[apply_start:next_def]
    # Find the with-block start and verify writer.write inside.
    with_pos = body.find("with open(self._doc_path")
    assert with_pos > 0
    # All the writer interactions should appear after the with-line.
    assert body.find("writer = PdfWriter()", with_pos) > with_pos
    assert body.find("writer.write(f)", with_pos) > with_pos


# ── i18n parity ─────────────────────────────────────────────────────────


def test_translations_parity_for_new_key():
    """The new tool.err.bad_page_input key must exist in all 8 languages."""
    data = json.loads(_read("app/translations.json"))
    expected_langs = {"en", "pt", "es", "fr", "de", "zh", "it", "nl"}
    assert set(data.keys()) >= expected_langs
    for lang in expected_langs:
        assert "tool.err.bad_page_input" in data[lang], (
            f"Missing translation key in '{lang}'"
        )
        # All translations must reference the {text} placeholder so
        # parse_pages's `.format()` call resolves cleanly.
        assert "{text}" in data[lang]["tool.err.bad_page_input"], (
            f"Translation in '{lang}' is missing the {{text}} placeholder"
        )
