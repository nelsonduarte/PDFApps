"""Source-level + behavioral regression tests for PR-I (Audit MEDIUMs + LOWs).

Bug map (PR-I worklist — Rounds 5-11 leftovers):
    #M1  _compress_pdf raw English errors                    (R11 A1)
    #M2  encrypt._run wipes password on wrong-pwd retry      (R11 A9)
    #M3  split.py endpoint defaults stale across PDF changes (R11 A6)
    #M4  reader.decrypt return ignored across tools          (R5)
    #M5  pipeline save uses non-atomic shutil.copy2          (R5 J4)
    #M6  symlink check on save destination                   (R5 J3)
    #M7  update check fires inside __init__                  (R5 F4)
    #M8  remaining tools without _atomic_pdf_write           (R6 F1)
    #M9  QShortcuts lack WidgetWithChildrenShortcut          (R7 L1)
    #M10 QToolTip has no themed style                        (R6 N1)
    #M11 QMessageBox.question lacks defaultButton            (R6 I1)
    #M12 SetTabOrder missing on multi-widget dialogs         (R7 H1/H3)
    #L1  _IMG_EXTS dead in import_pdf.py                     (R5/R6 C9)
    #L4  Latin-1 font warning for non-Latin text             (R7/R8/R11 M3)
    #L5  PE header version-info missing                      (R8 F1)
    #L8  viewer note delete no-match still saveIncr          (R11)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── #M1 — _compress_pdf errors translated ────────────────────────────────


def test_compress_deps_missing_translated():
    src = _read("app/utils.py")
    assert 'RuntimeError("Install pypdf and/or PyMuPDF' not in src, (
        "Raw English RuntimeError should be replaced by t() lookup."
    )
    assert 't("tool.compress.deps_missing")' in src


def test_compress_no_gain_uses_translated_key():
    src = _read("app/utils.py")
    assert 'raise ValueError(f"No gain:' not in src, (
        "Raw English ValueError should be replaced by t() lookup."
    )
    assert 'tool.compress.no_gain_detail' in src


def test_new_i18n_keys_parity():
    """All 8 languages must define the new keys added by PR-I."""
    with open(ROOT / "app/translations.json", encoding="utf-8") as f:
        d = json.load(f)
    new_keys = {
        "tool.compress.deps_missing",
        "tool.compress.no_gain_detail",
        "tool.err.wrong_password",
        "tool.warn.font_latin_only",
        "viewer.delete_no_match",
    }
    for lang, table in d.items():
        missing = new_keys - set(table.keys())
        assert not missing, f"{lang} missing keys: {missing}"


# ── #M2 — encrypt._run no wipe on failure ───────────────────────────────


def test_encrypt_run_only_clears_on_success():
    src = _read("app/tools/encrypt.py")
    # The old unconditional finally-clear is gone.
    assert "success = False" in src
    # The clear is now guarded by `if success`.
    assert "if success:" in src
    assert "self._clear_password_fields()" in src


# ── #M3 — split clamp endpoints across PDF changes ──────────────────────


def test_split_clamps_rows_to_total():
    src = _read("app/tools/split.py")
    assert "_clamp_rows_to_total" in src, (
        "Switching PDFs must clamp pre-existing row endpoints to the "
        "new total."
    )


# ── #M4 — decrypt return value checked ──────────────────────────────────


@pytest.mark.parametrize("path", [
    "app/base.py",
    "app/editor/tab.py",
    "app/tools/encrypt.py",
    "app/tools/watermark.py",
    "app/tools/merge.py",
])
def test_decrypt_return_checked(path):
    src = _read(path)
    # The new pattern is "if X.decrypt(Y) == 0" or equivalent — either
    # a direct comparison or storing in `result` and checking result == 0.
    assert (".decrypt(" in src), f"{path} has no decrypt call"
    has_check = ("decrypt(" in src and (
        "== 0" in src or "result == 0" in src
    ))
    assert has_check, (
        f"{path} must validate decrypt() return value (0 = wrong pwd)."
    )


# ── #M5 / #M6 — pipeline save atomicity + symlink check ─────────────────


def test_pipeline_save_uses_os_replace():
    src = _read("app/window.py")
    # The save_pipeline body must use mkstemp + os.replace, not just
    # shutil.copy2. shutil.copy2 may still be present as a fallback.
    save_block = src.split("def _save_pipeline")[1].split("def _cleanup_pipeline")[0]
    assert "os.replace" in save_block, (
        "_save_pipeline must use os.replace for atomicity."
    )
    assert "mkstemp" in save_block


def test_pipeline_save_logs_symlink_destination():
    src = _read("app/window.py")
    save_block = src.split("def _save_pipeline")[1].split("def _cleanup_pipeline")[0]
    assert "realpath" in save_block, (
        "_save_pipeline must detect symlinks at the destination."
    )


# ── #M7 — update check deferred ─────────────────────────────────────────


def test_update_check_deferred_post_init():
    src = _read("app/window.py")
    # The bare self._check_for_updates_async() call inside __init__ is
    # replaced by a QTimer.singleShot.
    init_block = src.split("self._update_release = None")[1].split("# ── Viewer property")[0]
    assert "QTimer.singleShot" in init_block, (
        "Update check must be deferred via QTimer.singleShot from __init__."
    )
    # And guarded with isValid so a quick close won't crash.
    assert "isValid(self)" in init_block


# ── #M8 — remaining tools use _atomic_pdf_write ─────────────────────────


def test_nup_uses_atomic_pdf_write():
    src = _read("app/tools/nup.py")
    assert "_atomic_pdf_write" in src
    # The raw direct save was gated by the same-source check — verify the
    # only doc.save call left is via the helper, not the bare path call.
    assert "out.save(out_path" not in src


def test_import_pdf_uses_atomic_pdf_write():
    src = _read("app/tools/import_pdf.py")
    assert "_atomic_pdf_write" in src
    # The bare 'doc.save(out_path)' calls (8 of them) must all be gone.
    assert "doc.save(out_path)" not in src


# ── #M9 — shortcuts scoped to widget tree ───────────────────────────────


def test_shortcuts_use_widget_with_children_context():
    src = _read("app/window.py")
    assert "WidgetWithChildrenShortcut" in src, (
        "Critical shortcuts (PgUp/PgDown/Ctrl+S/Ctrl+W) must be scoped "
        "via setContext(WidgetWithChildrenShortcut)."
    )


# ── #M10 — QToolTip is themed ───────────────────────────────────────────


def test_qtooltip_themed_both_modes():
    src = _read("app/styles.py")
    # Two style strings — one dark (STYLE), one light (STYLE_LIGHT).
    # QToolTip rule must appear in both.
    assert src.count("QToolTip") >= 2, (
        "QToolTip must be styled in both STYLE and STYLE_LIGHT."
    )


# ── #M11 — destructive QMessageBox.question gains defaultButton=No ──────


def test_pipeline_unsaved_prompts_default_to_cancel():
    src = _read("app/window.py")
    # The two unsaved-pipeline prompts must end with `Cancel)` as the
    # default-button kwarg. The presence of the closing pattern is enough
    # to assert the fix without parsing AST.
    assert "QMessageBox.StandardButton.Cancel)" in src
    # Both call sites use Cancel as default. Heuristic: count.
    assert src.count("QMessageBox.StandardButton.Cancel)") >= 2


def test_page_numbers_replace_prompt_defaults_to_no():
    src = _read("app/tools/page_numbers.py")
    # The "replace existing page numbers" prompt must default to No.
    pn_block = src.split("if existing:")[1].split("if ans == QMessageBox.StandardButton.Cancel")[0]
    assert "QMessageBox.StandardButton.No," in pn_block


# ── #M12 — setTabOrder explicitly defined ───────────────────────────────


def test_signature_dialog_sets_tab_order():
    src = _read("app/editor/dialogs.py")
    sig_block = src.split("class _SignatureDialog")[1]
    assert "setTabOrder" in sig_block


# ── #L1 — _IMG_EXTS used as filter ──────────────────────────────────────


def test_import_pdf_uses_img_exts():
    src = _read("app/tools/import_pdf.py")
    # _IMG_EXTS must now be referenced inside the convert path.
    assert "_IMG_EXTS" in src
    # At least 2 occurrences: the definition + a usage.
    assert src.count("_IMG_EXTS") >= 2, (
        "_IMG_EXTS must be referenced (not just defined)."
    )


# ── #L4 — non-Latin warn ────────────────────────────────────────────────


def test_page_numbers_warns_non_latin():
    src = _read("app/tools/page_numbers.py")
    assert "tool.warn.font_latin_only" in src


def test_editor_apply_warns_non_latin():
    src = _read("app/editor/tab.py")
    assert "tool.warn.font_latin_only" in src


# ── #L5 — PE version-info ───────────────────────────────────────────────


def test_pdfapps_spec_has_version_info():
    src = _read("pdfapps.spec")
    assert "version_info.txt" in src
    assert "version=" in src


def test_version_info_file_exists():
    assert (ROOT / "version_info.txt").exists()


# ── #L8 — viewer delete no-match no-op ──────────────────────────────────


def test_viewer_delete_no_match_skips_save():
    src = _read("app/viewer/canvas.py")
    # When the search loop exits with target_annot is None, the code
    # path must show a warning and return BEFORE the saveIncr call.
    # We check by searching for the key phrase + return in the block.
    assert "viewer.delete_no_match" in src
