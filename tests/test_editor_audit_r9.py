"""Source-level regression tests for PR-D / Round 9 editor audit fixes.

Like ``tests/test_round8_fixes.py``, most of these read the touched
source files and assert the new wiring is in place. A few hit the
production code path directly with stand-in stubs where doing so adds
real coverage without requiring a Qt event loop.

Bug map (matches PR-D worklist):
    #1  Encryption silently stripped on save              (CRIT)
    #2  Forms mode discards pending edits                 (HIGH)
    #3  Existing note delete doesn't persist              (HIGH)
    #4  Image mode reopens dialog every time              (HIGH)
    #5  QPixmap loaded from disk every paintEvent         (HIGH)
    #6  Note delete not in _redo_stack                    (HIGH)
    #7  Signature dialog mute when empty                  (HIGH)
    #8  Forms edits not in _pending                       (MED)
    #9  Text mode change during _inline_edit              (MED)
    #10 Redact cross-page rect not clipped                (MED)
    #11 Signature in-progress stroke ignored              (MED)
    #12 _load_form_fields swallows exceptions             (MED)
    + LOWs: KeyError safety, enumerate, TIFF, auto_regen, theme bg, leak reset
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── #1 — Encryption preserved on save ────────────────────────────────────


def test_run_detects_encrypted_input():
    src = _read("app/editor/tab.py")
    # R10 (CRIT-2): the encryption peek now uses a short-lived
    # ``peek = fitz.open(...)`` BEFORE releasing the canvas so a user
    # cancel in the encryption prompt no longer strands the editor on
    # the placeholder. Allow either the legacy ``doc.needs_pass``
    # phrasing or the new ``peek.needs_pass`` one — both detect input
    # encryption, the rest of the prompt-choice flow is unchanged.
    assert ("was_encrypted = bool(doc.needs_pass)" in src
            or "was_encrypted = bool(peek.needs_pass)" in src)
    assert "_prompt_encryption_choice" in src


def test_prompt_encryption_choice_offers_three_paths():
    src = _read("app/editor/tab.py")
    body = src[src.find("def _prompt_encryption_choice"):
               src.find("def _on_note_deleted")]
    # All three button keys must be wired.
    assert 'editor.encrypt.save_protected' in body
    assert 'editor.encrypt.save_unprotected' in body
    assert 'btn.cancel' in body
    # Returns the three sentinel strings.
    assert '"protect"' in body
    assert '"plaintext"' in body
    # Default button must be the safe "keep protection" choice.
    assert "setDefaultButton(keep_btn)" in body


def test_fitz_save_path_supports_aes_256_reencryption():
    src = _read("app/editor/tab.py")
    fitz_block = src[src.find('encrypt_choice = "plaintext"'):
                     src.find("def _apply_forms")]
    assert 'fitz.PDF_ENCRYPT_AES_256' in fitz_block
    assert 'user_pw=self._pdf_password' in fitz_block
    assert 'owner_pw=self._pdf_password' in fitz_block


def test_pypdf_forms_path_supports_aes_256_reencryption():
    src = _read("app/editor/tab.py")
    forms_block = src[src.find("def _apply_forms"):]
    assert 'writer.encrypt' in forms_block
    assert 'algorithm="AES-256"' in forms_block
    # Also covers the LOW: auto_regenerate flipped from False to True.
    assert 'auto_regenerate=True' in forms_block


# ── #2 — Forms + pending warn before discard ─────────────────────────────


def test_forms_mode_warns_when_pending_present():
    src = _read("app/editor/tab.py")
    run_block = src[src.find("def _run("):
                    src.find("def _apply_forms")]
    assert 'editor.forms.has_pending' in run_block
    # The warning must short-circuit when the user picks No.
    assert "QMessageBox.StandardButton.No" in run_block


# ── #3 — delete_annot pending edit type ──────────────────────────────────


def test_existing_notes_carry_stable_match_fields():
    src = _read("app/editor/tab.py")
    block = src[src.find("def _load_existing_annotations"):
                src.find("def auto_load")]
    assert '_annot_type' in block
    assert '_annot_bbox' in block


def test_canvas_late_discovered_notes_also_tag_match_fields():
    src = _read("app/editor/canvas.py")
    block = src[src.find("def _annot_note_at"):
                src.find("def contextMenuEvent")]
    assert '_annot_type' in block
    assert '_annot_bbox' in block


def test_run_loop_applies_delete_annot_edits():
    src = _read("app/editor/tab.py")
    run_block = src[src.find("def _run("):
                    src.find("def _apply_forms")]
    assert 'e["type"] == "delete_annot"' in run_block
    assert "page.delete_annot" in run_block or "pg.delete_annot" in run_block


def test_existing_filter_does_not_drop_delete_annot():
    """The pre-existing ``if e.get("_existing"): continue`` guard skipped
    every entry already saved in the PDF. delete_annot edits are
    flagged ``_existing=True`` but MUST be processed, so the guard now
    excludes them explicitly."""
    src = _read("app/editor/tab.py")
    assert 'e.get("_existing") and e.get("type") != "delete_annot"' in src


# ── #4 — Image mode no longer reopens the picker every time ──────────────


def test_image_mode_only_picks_when_empty():
    src = _read("app/editor/tab.py")
    block = src[src.find("if idx == _MODE_IMAGE"):
                src.find("def _pick_pdf")]
    # Guard mirrors the signature path.
    assert "self._img_drop.path()" in block
    assert "os.path.isfile" in block


# ── #5 — Pixmap cache + enumerate ────────────────────────────────────────


def test_overlay_pixmap_lru_cache_exists():
    src = _read("app/editor/canvas.py")
    assert "from functools import lru_cache" in src
    assert "_load_overlay_pixmap" in src
    assert "@lru_cache" in src


def test_paint_event_uses_cached_pixmap():
    src = _read("app/editor/canvas.py")
    paint = src[src.find("def paintEvent("):
                src.find("def mousePressEvent")]
    # No more raw QPixmap(path) inside paintEvent — uses the cache.
    assert "_load_overlay_pixmap(path, mtime)" in paint
    assert "_QPixmap(e[\"path\"])" not in paint


def test_paint_event_uses_enumerate_index():
    """LOW: ``self._overlays.index(e)`` per overlay was O(n²)."""
    src = _read("app/editor/canvas.py")
    paint = src[src.find("def paintEvent("):
                src.find("def mousePressEvent")]
    assert "for ov_idx, e in enumerate(self._overlays):" in paint
    assert "self._overlays.index(e)" not in paint


# ── #6 — Note delete pushes to redo stack ────────────────────────────────


def test_note_deleted_pushes_to_redo_stack():
    src = _read("app/editor/tab.py")
    block = src[src.find("def _on_note_deleted"):
                src.find("def _clear_pending")]
    assert "self._redo_stack.append(removed)" in block
    # Must NOT clear the existing redo stack — that was the CRIT-1 bug.
    assert "self._redo_stack.clear()" not in block


def test_note_deleted_existing_registers_delete_annot_pending():
    src = _read("app/editor/tab.py")
    block = src[src.find("def _on_note_deleted"):
                src.find("def _clear_pending")]
    assert '"type": "delete_annot"' in block
    assert "self._pending.append(edit)" in block


# ── #7 — Signature dialog now warns on empty draw / type / import ────────


def test_signature_dialog_validates_empty_tabs():
    src = _read("app/editor/dialogs.py")
    block = src[src.find("def _validate_tab"):
                src.find("def result_path")]
    assert "editor.signature.empty_draw" in block
    assert "editor.signature.empty_type" in block
    assert "editor.signature.empty_import" in block
    # _on_accept defers to the validator.
    on_accept = src[src.find("def _on_accept"):
                    src.find("def result_path")]
    assert "self._validate_tab(tab)" in on_accept


# ── #8 — Forms undo is explicitly surfaced ───────────────────────────────


def test_forms_undo_message_in_run():
    src = _read("app/editor/tab.py")
    assert 'editor.forms.undo_unavailable' in src
    # _on_mode_btn switches the tooltip; _undo emits a status hint.
    assert "self._btn_undo.setToolTip(tip)" in src


# ── #9 — Mode change cancels inline edit ─────────────────────────────────


def test_mode_change_cancels_inline_edit():
    src = _read("app/editor/tab.py")
    block = src[src.find("def _on_mode_btn"):
                src.find("def _pick_pdf")]
    assert "self._canvas._cancel_inline()" in block
    assert "_inline_edit.isVisible()" in block


# ── #10 — Redact rect clamped + zero-area rejected ───────────────────────


def test_rect_to_pdf_clamps_to_page_bbox():
    src = _read("app/editor/canvas.py")
    block = src[src.find("def _rect_to_pdf"):
                src.find("def paintEvent")]
    # Intersection against the page rect.
    assert "self._doc[page_idx].rect" in block
    assert "r & page_rect" in block
    # Degenerate rects return None.
    assert "return None" in block


def test_release_handler_skips_none_rect():
    src = _read("app/editor/canvas.py")
    block = src[src.find("def mouseReleaseEvent"):]
    assert "if pdf_rect is not None:" in block


# ── #11 — Signature in-progress stroke now counted ───────────────────────


def test_signature_canvas_includes_in_progress_stroke():
    src = _read("app/editor/dialogs.py")
    block = src[src.find("class _SignatureCanvas"):
                src.find("class _SignatureDialog")]
    is_empty = block[block.find("def is_empty"):
                     block.find("def _all_strokes") if "_all_strokes" in block
                     else block.find("def to_image")]
    assert "self._current" in is_empty
    # to_image consumes the in-progress stroke via _all_strokes.
    to_image = block[block.find("def to_image"):]
    assert "_all_strokes" in to_image


# ── #12 — _load_form_fields logs + surfaces failure ──────────────────────


def test_load_form_fields_logs_and_shows_status():
    src = _read("app/editor/tab.py")
    block = src[src.find("def _load_form_fields"):
                src.find("def _on_draw_color_changed")]
    assert "_log.warning" in block
    assert "editor.forms.load_failed" in block
    assert "self._form_status.setText" in block
    # Distinguishes "no fields" from "load failed".
    assert "editor.forms.no_fields" in block


# ── LOWs ─────────────────────────────────────────────────────────────────


def test_labels_dict_uses_get_with_default():
    src = _read("app/editor/tab.py")
    block = src[src.find("def _add"):
                src.find("def _undo")]
    assert "labels.get(edit[\"type\"]" in block


def test_inline_edit_uses_theme_color():
    src = _read("app/editor/canvas.py")
    style_block = src[src.find("def _style_inline_edit"):
                      src.find("def _reposition_inline")]
    # Hardcoded #FFFFFFE6 must no longer appear in the actual style
    # string — only in the comment explaining what changed.
    assert "background: #FFFFFFE6" not in style_block
    # Theme-aware bg lookup.
    assert "_LI" in style_block or "self._bg_color" in style_block


def test_signature_import_filter_includes_tiff():
    src = _read("app/editor/dialogs.py")
    block = src[src.find("def _pick_image"):
                src.find("def _validate_tab") if "_validate_tab" in src
                else src.find("def _on_accept")]
    assert "*.tif" in block


def test_inline_commit_resets_insert_state():
    src = _read("app/editor/canvas.py")
    commit = src[src.find("def _commit_inline"):
                 src.find("def _cancel_inline")]
    # All four insert-state attributes get reset.
    assert "self._inline_insert_font = " in commit
    assert "self._inline_insert_size = 12" in commit
    assert "self._inline_insert_color = (0, 0, 0)" in commit
    assert "self._inline_original = " in commit


# ── i18n parity ──────────────────────────────────────────────────────────


def test_new_i18n_keys_present_in_every_locale():
    """Each new key must exist for every shipping locale."""
    data = json.loads((ROOT / "app" / "translations.json")
                      .read_text(encoding="utf-8"))
    locales = list(data.keys())
    assert len(locales) == 8, f"Expected 8 locales, got {locales}"
    new_keys = [
        "editor.encrypt.warning_title",
        "editor.encrypt.warning_text",
        "editor.encrypt.save_protected",
        "editor.encrypt.save_unprotected",
        "editor.forms.has_pending",
        "editor.forms.undo_unavailable",
        "editor.forms.load_failed",
        "editor.forms.no_fields",
        "editor.signature.empty_draw",
        "editor.signature.empty_type",
        "editor.signature.empty_import",
        "edit.label.note_delete",
    ]
    for key in new_keys:
        for loc in locales:
            val = data[loc].get(key)
            assert val, f"locale {loc!r} missing key {key!r}"


def test_translations_parity_unchanged():
    """All locales must carry the same key set — drift would indicate
    a partially-translated PR."""
    data = json.loads((ROOT / "app" / "translations.json")
                      .read_text(encoding="utf-8"))
    ref = set(data["en"].keys())
    for loc, payload in data.items():
        diff = ref.symmetric_difference(set(payload.keys()))
        assert not diff, f"locale {loc!r} diverges from en by {len(diff)} keys"


# ── Behavioural sanity: _on_note_deleted with a tiny stub ────────────────


def test_note_deleted_keeps_undo_redo_in_sync():
    """Stand-in for behavioural coverage of the redo-push without
    spinning up a real Qt event loop. Mirrors the pattern from
    tests/test_editor_undo.py."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QListWidget
    _app = QApplication.instance() or QApplication([])
    from app.editor.tab import TabEditar

    class _Stub:
        _MAX_REDO = TabEditar._MAX_REDO
        _MAX_PENDING = TabEditar._MAX_PENDING

        def __init__(self):
            self._pending = []
            self._redo_stack = []
            self._pending_list = QListWidget()

            class _CV:
                def set_overlays(self, _ovs): pass

            self._canvas = _CV()

        def _status(self, *a, **kw): pass

        _on_note_deleted = TabEditar._on_note_deleted

    s = _Stub()
    overlay = {"type": "note", "page": 0, "text": "hello"}
    s._pending.append(dict(overlay))
    s._pending_list.addItem("note")

    assert len(s._pending) == 1
    s._on_note_deleted(overlay)
    # Pending dropped, redo grew.
    assert len(s._pending) == 0
    assert len(s._redo_stack) == 1
    assert s._pending_list.count() == 0


def test_note_deleted_existing_enqueues_delete_annot():
    """When an existing PDF annotation already in ``_pending`` (loaded by
    ``_load_existing_annotations`` with ``_existing=True``) is deleted via
    the canvas context menu, ``_on_note_deleted`` must:

    * pop the original note from ``_pending``
    * push the original onto ``_redo_stack`` (so Ctrl+Z works)
    * append a ``delete_annot`` edit so the save loop actually drops the
      annotation from the output file
    * stash the original note on the edit (``_original_note``) so the
      undo path can put it back on the canvas

    Regression for PR-D review finding #1: the first ``for`` loop in
    ``_on_note_deleted`` returned early and the ``delete_annot`` branch
    after it was never reached for the common case."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QListWidget
    _app = QApplication.instance() or QApplication([])
    from app.editor.tab import TabEditar

    class _Stub:
        _MAX_REDO = TabEditar._MAX_REDO
        _MAX_PENDING = TabEditar._MAX_PENDING

        def __init__(self):
            self._pending = []
            self._redo_stack = []
            self._pending_list = QListWidget()

            class _CV:
                def __init__(self): self.set_overlays_calls = 0
                def set_overlays(self, _ovs): self.set_overlays_calls += 1

            self._canvas = _CV()

        def _status(self, *a, **kw): pass

        _on_note_deleted = TabEditar._on_note_deleted
        _undo = TabEditar._undo

    s = _Stub()
    bbox = [10.0, 20.0, 30.0, 40.0]
    existing = {
        "type": "note",
        "page": 2,
        "text": "hello",
        "_existing": True,
        "_annot_type": 0,        # fitz.PDF_ANNOT_TEXT
        "_annot_bbox": bbox,
    }
    s._pending.append(existing)
    s._pending_list.addItem("note")

    # Caller hands us the overlay dict (same structure as _pending entry).
    s._on_note_deleted(dict(existing))

    # The original note is gone from _pending, redo_stack has it.
    assert len(s._redo_stack) == 1
    assert s._redo_stack[0].get("_existing") is True
    # A delete_annot edit must have been enqueued in its place.
    types = [e.get("type") for e in s._pending]
    assert "delete_annot" in types, (
        "missing delete_annot — existing-note deletion will not persist")
    da = next(e for e in s._pending if e.get("type") == "delete_annot")
    assert da["page"] == 2
    assert da["bbox"] == bbox
    assert da["annot_type"] == 0
    assert da.get("_existing") is True
    # Original note stashed for undo restore.
    assert da.get("_original_note", {}).get("text") == "hello"

    # ── Undo behaviour: rolling back the delete_annot must put the
    #    original note back into _pending so the canvas overlay reappears.
    s._undo()
    assert all(e.get("type") != "delete_annot" for e in s._pending)
    notes = [e for e in s._pending
             if e.get("type") == "note" and e.get("text") == "hello"]
    assert len(notes) == 1, (
        "undo of delete_annot must restore the original note overlay")


def test_overlay_pixmap_cache_returns_same_instance(tmp_path):
    """Cache check: same (path, mtime) tuple returns the same QPixmap
    instance — proves the LRU is actually wired."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])

    from app.editor.canvas import _load_overlay_pixmap

    # Use a tiny png we can write deterministically.
    src = tmp_path / "sig.png"
    src.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    mtime = src.stat().st_mtime
    pix_a = _load_overlay_pixmap(str(src), mtime)
    pix_b = _load_overlay_pixmap(str(src), mtime)
    assert pix_a is pix_b, "LRU cache should return identical object"
