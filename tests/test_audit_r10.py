"""Source-level regression tests for PR-F / Round 10 audit fixes.

Bug map (matches PR-F worklist):
    #1  Viewer saveIncr without backup / atomic write   (CRIT)
    #2  Editor release_doc before encryption prompt     (CRIT - PR-D regression)
    #3  Editor _load_overlay_pixmap LRU leak             (HIGH)
    #4  Viewer try/except annot race (delete OK, save fail) (HIGH)
    #5  Recents UI stale after add_recent_file           (HIGH)
    #6  Forms apply on PDF without /AcroForm crashes     (HIGH)
    #7  Viewer note match by content-only (collision)    (HIGH)
    #8  Editor delete without confirmation               (MED)
    #9  Snap/.SRCINFO regex too greedy                   (MED)
    #10 Tab close during OCR race (pre-existing, audited) (MED)
    #11 _load_overlay_pixmap caches null QPixmap on OSError (LOW)
    #12 Drop folder / web URL silently ignored           (LOW)
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── #1 — saveIncr backup + confirmation ──────────────────────────────────


def test_viewer_save_incr_uses_backup_before_persisting():
    """The delete-comment context menu must copy the PDF to a same-
    directory .bak before page.delete_annot+saveIncr so a power loss
    leaves the original recoverable."""
    src = _read("app/viewer/canvas.py")
    # backup_path is the variable we introduced; shutil.copy2 + bak
    # suffix are the markers for the backup step.
    assert "backup_path" in src
    assert "shutil.copy2" in src
    assert ".pdf.bak" in src


def test_viewer_save_incr_restores_backup_on_failure():
    """saveIncr() error path must shutil.move(backup_path, src) so
    we never silently corrupt the user's PDF."""
    src = _read("app/viewer/canvas.py")
    assert "shutil.move(backup_path, self._path)" in src


# ── #2 — release_doc deferred past encryption prompt ─────────────────────


def test_editor_run_releases_canvas_after_prompt():
    """release_doc() must be reached only AFTER
    _prompt_encryption_choice() so cancelling does not strand the
    canvas with _doc=None."""
    src = _read("app/editor/tab.py")
    run_body_start = src.find("def _run(self)")
    run_body_end = src.find("def _fitz_permissions_of", run_body_start)
    body = src[run_body_start:run_body_end]
    prompt_pos = body.find("_prompt_encryption_choice")
    release_pos = body.find("self._canvas.release_doc()")
    assert prompt_pos > 0 and release_pos > 0
    # The encryption peek must happen BEFORE the canvas release.
    assert prompt_pos < release_pos, (
        "release_doc() must run after the encryption prompt (CRIT-2)"
    )


def test_editor_run_uses_peek_for_encryption_check():
    """The peek doc pattern is the marker that we read needs_pass
    without releasing the canvas-held doc."""
    src = _read("app/editor/tab.py")
    assert "peek = fitz.open(self._doc_path)" in src
    assert "peek.close()" in src


# ── #3 — Overlay pixmap cache eviction + clear hook ──────────────────────


def test_overlay_pixmap_cache_has_clear_hook():
    src = _read("app/editor/canvas.py")
    assert "_OVERLAY_PIXMAP_CACHE" in src
    assert "def clear_overlay_pixmap_cache" in src
    assert "clear_overlay_pixmap_cache()" in src  # called from close_doc


def test_overlay_pixmap_cache_has_fifo_eviction():
    """When the cache hits the cap, we evict the oldest entry —
    next(iter(_OVERLAY_PIXMAP_CACHE)) returns the first inserted key
    in CPython 3.7+ dicts."""
    src = _read("app/editor/canvas.py")
    assert "_OVERLAY_PIXMAP_CACHE_MAX" in src
    assert "next(iter(_OVERLAY_PIXMAP_CACHE))" in src


def test_overlay_pixmap_no_longer_uses_lru_cache():
    src = _read("app/editor/canvas.py")
    # Old decorator path must be gone — the manual cache replaces it.
    assert "from functools import lru_cache" not in src
    # Strip comments before checking — the migration note legitimately
    # mentions the old decorator by name.
    code_only = "\n".join(
        line.split("#", 1)[0]
        for line in src.splitlines()
    )
    assert "@lru_cache" not in code_only


# ── #4 — saveIncr separated from delete_annot + reload on error ─────────


def test_viewer_reloads_doc_on_save_failure():
    """When saveIncr() raises, the in-memory delete is discarded by
    reopening the file so the next paintEvent reflects on-disk state."""
    src = _read("app/viewer/canvas.py")
    # Reload-on-error markers: re-open via fitz.open + re-auth.
    assert "self._doc.close()" in src
    assert "new_doc = fitz.open(saved_path)" in src
    assert "saved_password" in src


# ── #5 — Recents UI refresh hook ────────────────────────────────────────


def test_viewer_panel_has_refresh_recents():
    src = _read("app/viewer/panel.py")
    assert "def _refresh_recents" in src
    # __init__ delegates to it (so single source of truth).
    assert "self._refresh_recents()" in src


def test_window_load_and_track_refreshes_recents():
    """_load_and_track must call _refresh_recents on every open
    viewer after add_recent_file so the placeholder shows the
    up-to-date list on next return."""
    src = _read("app/window.py")
    # Locate the _load_and_track body.
    body = src[src.find("def _load_and_track"):
               src.find("def _open_in_new_tab")]
    assert "_refresh_recents" in body


# ── #6 — Forms apply guard ──────────────────────────────────────────────


def test_apply_forms_guards_against_missing_acroform():
    """_apply_forms must short-circuit with editor.forms.no_fields
    when the writer has no /AcroForm — pypdf's
    update_page_form_field_values raises a cryptic error otherwise."""
    src = _read("app/editor/tab.py")
    forms_body = src[src.find("def _apply_forms"):
                     src.find("def _apply_forms") + 2500]
    assert '"/AcroForm" not in writer._root_object' in forms_body
    assert 'editor.forms.no_fields' in forms_body


# ── #7 — bbox tiebreaker on viewer note delete ──────────────────────────


def test_viewer_note_delete_tiebreaks_on_bbox():
    """Two notes with identical content must be disambiguated by bbox
    proximity so the right one is deleted."""
    src = _read("app/viewer/canvas.py")
    assert "abs(ar.x0 - rect.x0) < 1" in src
    assert "abs(ar.y0 - rect.y0) < 1" in src


# ── #8 — Editor delete confirmation ──────────────────────────────────────


def test_editor_delete_prompts_for_confirmation():
    """contextMenuEvent's delete path must surface a QMessageBox.question
    using the existing viewer.confirm_delete_comment string."""
    src = _read("app/editor/canvas.py")
    ctx_start = src.find("def contextMenuEvent")
    ctx_body = src[ctx_start: ctx_start + 2000]
    assert "QMessageBox.question" in ctx_body
    assert "viewer.confirm_delete_comment" in ctx_body
    assert "QMessageBox.StandardButton.No" in ctx_body


# ── #9 — .SRCINFO regex anchored to tarball context ─────────────────────


def test_srcinfo_regex_is_anchored():
    """The version-bump step must anchor v{ANY} replacements to a
    file/path context so future history comments are not rewritten."""
    src = _read(".github/workflows/release.yml")
    # No unanchored v{ANY} substitution for aur/pdfapps/.SRCINFO.
    aur_block_start = src.find('"aur/pdfapps/.SRCINFO"')
    aur_block_end = src.find('"aur/pdfapps-bin/.SRCINFO"', aur_block_start)
    aur_block = src[aur_block_start:aur_block_end]
    # The bare unanchored ``v{ANY}`` rule is gone.
    assert "rf'v{ANY}'" not in aur_block
    # New anchored rules:
    assert ".tar.gz" in aur_block


def test_srcinfo_bin_regex_is_anchored():
    src = _read(".github/workflows/release.yml")
    bin_start = src.find('"aur/pdfapps-bin/.SRCINFO"')
    bin_end = src.find("winget/nelsonduarte", bin_start)
    bin_block = src[bin_start:bin_end]
    assert "rf'v{ANY}'" not in bin_block
    assert "rf'pdfapps-{ANY}'" not in bin_block  # unanchored is gone
    assert "/v{ANY}/" in bin_block


# ── #10 — Tab close ordering audit (existing behaviour) ─────────────────


def test_window_closeevent_waits_for_workers_before_destroy():
    """Pre-existing: window.closeEvent must call wait_for_workers()
    on each stacked page before super().closeEvent() so QThreads are
    not destroyed mid-run. Audited in R10 #10 — no change required."""
    src = _read("app/window.py")
    close_body = src[src.find("def closeEvent"):
                     src.find("def _toggle_sidebar")]
    assert "wait_for_workers" in close_body
    # super().closeEvent must come AFTER the wait loop.
    wait_idx = close_body.find("wait_for_workers")
    super_idx = close_body.find("super().closeEvent")
    assert 0 < wait_idx < super_idx


# ── #11 — Uncached fallback on getmtime failure ─────────────────────────


def test_overlay_pixmap_uncached_on_mtime_error():
    """An OSError on os.path.getmtime() must not poison the cache —
    fall back to QPixmap(path) directly."""
    src = _read("app/editor/canvas.py")
    paint_body = src[src.find("def paintEvent"):
                     src.find("def mousePressEvent")]
    # The except OSError path must NOT route through _load_overlay_pixmap
    # (which would cache the null pixmap forever).
    assert "except OSError:" in paint_body
    # The fallback line is QPixmap(path) — not _load_overlay_pixmap(...).
    fallback_block = paint_body[paint_body.find("except OSError"):
                                paint_body.find("except OSError") + 200]
    assert "img_px = QPixmap(path)" in fallback_block


# ── #12 — Folder + URL drop handling ────────────────────────────────────


def test_drop_event_handles_folders_and_urls():
    src = _read("app/window.py")
    drop_body = src[src.find("def dropEvent"):
                    src.find("def dropEvent") + 2000]
    # Folder drop iterates glob, URL drop surfaces a warning.
    assert "os.path.isdir(path)" in drop_body
    assert "viewer.drop_url_not_supported" in drop_body
    assert "*.pdf" in drop_body


def test_drop_url_translation_parity():
    """8 locales must define viewer.drop_url_not_supported so users in
    every language get the warning."""
    data = json.loads(
        (ROOT / "app" / "translations.json").read_text(encoding="utf-8"))

    seen = 0

    def walk(obj):
        nonlocal seen
        if isinstance(obj, dict):
            if "viewer.drop_url_not_supported" in obj:
                seen += 1
                assert isinstance(
                    obj["viewer.drop_url_not_supported"], str)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    assert seen == 8, (
        f"viewer.drop_url_not_supported missing in some locale "
        f"(got {seen}/8)"
    )
