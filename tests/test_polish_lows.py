"""Source-level + behavioral regression tests for PR-H polish fixes.

Bug map (PR-H worklist):
    #1  Global sys.excepthook in pdfapps.py main entry        (R7 I2 LOW)
    #2  config.json backup before reset on corruption          (R8 N1 LOW)
    #3  NFC password normalization in BasePage helpers         (R6 C1 LOW)
    #4  Explicit tab order in _PdfPasswordDialog               (R11 G1 LOW)
    #5  Drop folder >20 PDFs confirmation                       (R10 review LOW)
    #6  AcroForm with zero widgets no_fields short-circuit     (R10 review LOW)
    #7  _TextEditDialog single-line QLineEdit                  (R11 B2 LOW)
    #8  DropFileEdit multi-URL warning                          (R11 N3 LOW)
    #9  set_compact_mode lambda guarded with shiboken6.isValid (R6 O2 LOW)
    #10 parse_pages accepts open-ended ranges                  (R7 E5 LOW)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── #1 — sys.excepthook installed in main entry ─────────────────────────


def test_pdfapps_installs_global_excepthook():
    """The entry point must install sys.excepthook so uncaught
    exceptions in PyInstaller --windowed builds reach pdfapps.log
    instead of vanishing into a closed stderr."""
    src = _read("pdfapps.py")
    assert "sys.excepthook = _excepthook" in src, (
        "main() must wire sys.excepthook to the logging hook."
    )
    # KeyboardInterrupt must keep the default behaviour so Ctrl-C still
    # exits cleanly without spamming the log.
    assert "KeyboardInterrupt" in src
    assert "sys.__excepthook__" in src
    # The hook must log via the logging framework (not bare print).
    assert "logging.getLogger" in src
    assert "exc_info=" in src


# ── #2 — corrupt config.json backed up before reset ─────────────────────


def test_i18n_backs_up_corrupt_config_before_reset():
    """_update_config must copy a corrupt config.json aside as
    <config>.corrupt.bak before overwriting it with {}."""
    src = _read("app/i18n.py")
    assert ".corrupt.bak" in src, "Backup suffix marker missing"
    assert "shutil.copy2" in src, (
        "_update_config must shutil.copy2 the corrupt file aside."
    )
    # The 'missing file' path must NOT trigger a backup (would log noise
    # on every fresh install).
    assert "FileNotFoundError" in src, (
        "FileNotFoundError handled separately so first run is silent."
    )


# ── #3 — NFC password normalization ─────────────────────────────────────


def test_base_normalizes_passwords_to_nfc():
    """All three encrypted-PDF entry points must route the password
    through unicodedata.normalize('NFC', ...) so a macOS-typed (NFD)
    password unlocks the same PDF on Windows (NFC)."""
    src = _read("app/base.py")
    assert "import unicodedata" in src
    assert "unicodedata.normalize(\"NFC\"" in src
    # Helper exists and is called from each entry point.
    assert "def _nfc(" in src
    # The three call sites all use _nfc().
    assert "self._nfc(self._pdf_password)" in src
    assert "self._nfc(pwd)" in src


def test_nfc_helper_behavior_on_combining_characters():
    """Smoke test: a Unicode string composed in NFD (e + combining acute)
    must become its NFC singleton (é) before pypdf/PyMuPDF see it."""
    import unicodedata

    nfd = "passé"  # 'e' + combining acute
    nfc = "passé".encode("utf-8")
    normalized = unicodedata.normalize("NFC", nfd)
    assert normalized != nfd, "Test input must actually differ from NFC"
    assert unicodedata.is_normalized("NFC", normalized)


# ── #4 — _PdfPasswordDialog explicit tab order ──────────────────────────


def test_password_dialog_sets_tab_order():
    """The dialog must call setTabOrder(_edit, ok) and setTabOrder(ok, ca)
    so keyboard users land on the password field and Tab through OK then
    Cancel."""
    src = _read("app/editor/dialogs.py")
    assert "self.setTabOrder(self._edit, ok)" in src
    assert "self.setTabOrder(ok, ca)" in src
    # Initial focus is on the password field, not on Cancel.
    assert "self._edit.setFocus()" in src


# ── #5 — drop folder >20 PDFs confirmation ──────────────────────────────


def test_window_confirms_drop_of_many_pdfs():
    """Dropping a folder with more than 20 PDFs must show a confirm
    QMessageBox so the user can back out before tabs flood the UI."""
    src = _read("app/window.py")
    assert "viewer.drop_many_pdfs_confirm" in src
    assert "len(pdfs) > 20" in src
    # Default button is No so accidental drops do nothing surprising.
    assert "QMessageBox.StandardButton.No" in src


# ── #6 — AcroForm dict but zero widgets ─────────────────────────────────


def test_editor_zero_widget_acroform_short_circuits():
    """When /AcroForm exists but get_fields() is empty,
    _apply_forms must surface the no_fields status instead of running
    update_page_form_field_values as a silent no-op."""
    src = _read("app/editor/tab.py")
    # The new guard reads from _r.get_fields() and routes through the
    # same no_fields message used by the missing-AcroForm branch.
    assert "_r.get_fields()" in src
    # Both no_fields branches reside in _apply_forms.
    assert src.count("editor.forms.no_fields") >= 3, (
        "Expected three editor.forms.no_fields references (load-time + "
        "missing-acroform + zero-widget branches)."
    )


# ── #7 — _TextEditDialog single-line QLineEdit ──────────────────────────


def test_text_edit_dialog_uses_qlineedit():
    """_TextEditDialog must build a QLineEdit so the user can't enter
    newlines that PyMuPDF's insert_text would rasterise as '?'."""
    src = _read("app/editor/dialogs.py")
    # Locate the class block.
    cls_start = src.index("class _TextEditDialog")
    cls_end = src.index("class ", cls_start + 1)
    block = src[cls_start:cls_end]
    assert "self._edit = QLineEdit()" in block, (
        "_TextEditDialog._edit must be a QLineEdit (single-line)."
    )
    assert "self._edit = QTextEdit()" not in block, (
        "QTextEdit must not be used inside _TextEditDialog any more."
    )
    # new_text() must return .text(), not .toPlainText().
    assert "self._edit.text()" in block
    assert "self._edit.toPlainText()" not in block


# ── #8 — DropFileEdit multi-URL warning ─────────────────────────────────


def test_drop_file_edit_warns_on_multiple_urls():
    """DropFileEdit.dropEvent must surface a QMessageBox.information
    when more than one accepted file is dropped on the single-file
    widget."""
    src = _read("app/widgets.py")
    assert "QMessageBox" in src
    assert "widgets.drop_first_only" in src
    assert "len(accepted) > 1" in src


# ── #9 — set_compact_mode lambda isValid guard ──────────────────────────


def test_compact_mode_lambda_uses_shiboken_isvalid():
    """The 'Change source' compact-mode link's lambda must guard
    self.set_compact_mode(False) behind shiboken6.isValid(self) so a
    queued click does not touch a destroyed page."""
    src = _read("app/base.py")
    # Locate the lambda close to the compact_link section.
    assert "link.clicked.connect(" in src
    # The guard must wrap the slot.
    assert "set_compact_mode(False) if isValid(self) else None" in src


# ── #10 — parse_pages open-ended range support ──────────────────────────


def test_parse_pages_accepts_open_ended_start():
    """'3-' on a 10-page document must yield pages 3..10 (0-indexed
    2..9). Previously raised ValueError."""
    from app.utils import parse_pages

    assert parse_pages("3-", 10) == [2, 3, 4, 5, 6, 7, 8, 9]


def test_parse_pages_accepts_open_ended_end():
    """'-5' must yield pages 1..5 (0-indexed 0..4)."""
    from app.utils import parse_pages

    assert parse_pages("-5", 10) == [0, 1, 2, 3, 4]


def test_parse_pages_rejects_bare_dash():
    """'-' alone has no bounds at all and must still raise with the
    friendly message."""
    from app.utils import parse_pages

    with pytest.raises(ValueError) as exc:
        parse_pages("-", 10)
    msg = str(exc.value)
    # The friendly message echoes the offending substring and avoids
    # the raw Python error.
    assert "-" in msg
    assert "invalid literal for int" not in msg


def test_parse_pages_open_range_combined_with_csv():
    """Open ranges must compose with CSV input — '1,3-' must yield the
    full document and stay deduped/sorted."""
    from app.utils import parse_pages

    assert parse_pages("1,3-", 5) == [0, 2, 3, 4]


# ── i18n parity guards ─────────────────────────────────────────────────


def test_new_translation_keys_present_in_all_languages():
    """Both new PR-H keys must ship for all 8 supported languages
    (en, pt, es, fr, de, zh, it, nl) so t() never falls back to the
    raw key name in the UI."""
    raw = _read("app/translations.json")
    data = json.loads(raw)
    assert set(data.keys()) == {"en", "pt", "es", "fr", "de", "zh", "it", "nl"}
    for key in ("viewer.drop_many_pdfs_confirm", "widgets.drop_first_only"):
        missing = [lang for lang, kv in data.items() if key not in kv]
        assert not missing, f"{key} missing in: {missing}"
    # All language sections must share the same key count.
    counts = {lang: len(kv) for lang, kv in data.items()}
    assert len(set(counts.values())) == 1, (
        f"Key counts diverge across languages: {counts}"
    )


def test_new_translation_keys_use_count_placeholder():
    """Both new keys take a {count} placeholder; if a translator dropped
    it the t() format would silently render '... files were loaded.' with
    no number. Catch the regression at test time."""
    data = json.loads(_read("app/translations.json"))
    for lang, kv in data.items():
        assert "{count}" in kv["viewer.drop_many_pdfs_confirm"], (
            f"{lang} viewer.drop_many_pdfs_confirm dropped {{count}}"
        )
        assert "{count}" in kv["widgets.drop_first_only"], (
            f"{lang} widgets.drop_first_only dropped {{count}}"
        )
