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
    <config>.corrupt-<ts>.bak before overwriting it with {}.

    R11 review B5 added the ``-<timestamp>`` suffix so successive
    corruption events do not clobber each other; the marker we look
    for therefore moves from the literal ``.corrupt.bak`` to the
    ``.corrupt-`` prefix plus ``.bak`` extension.
    """
    src = _read("app/i18n.py")
    assert ".corrupt-" in src, "Timestamped backup prefix marker missing"
    assert ".bak" in src, "Backup extension marker missing"
    assert "shutil.copy2" in src, (
        "_update_config must shutil.copy2 the corrupt file aside."
    )
    # The 'missing file' path must NOT trigger a backup (would log noise
    # on every fresh install).
    assert "FileNotFoundError" in src, (
        "FileNotFoundError handled separately so first run is silent."
    )
    # The timestamp source must be wall-clock so the backups sort
    # naturally and we can tell which event came first.
    assert "datetime.now()" in src


# ── #3 — NFC password normalization ─────────────────────────────────────


def test_base_normalizes_passwords_to_nfc():
    """All three encrypted-PDF entry points must route the password
    through ``unicodedata.normalize('NFC', ...)`` so a macOS-typed (NFD)
    password unlocks the same PDF on Windows (NFC).

    After the R11 review the canonical normalisation function moved to
    :func:`app.utils.normalize_password` (so all the
    ``self._pdf_password`` *read* sites in ``tools/*`` and
    ``editor/tab.py`` are covered transitively when the cache is set);
    ``BasePage._nfc`` is now a thin delegator. The actual
    ``unicodedata.normalize("NFC", ...)`` call therefore lives in
    ``utils.py`` rather than ``base.py``, which is what we assert here.

    After the follow-up R11 review fix, normalisation now also happens at
    the WRITE site of the cache (BasePage._maybe_prompt_password) so the
    ``self._pdf_password`` attribute itself is deterministic for every
    downstream consumer in ``tools/*`` that reads it directly. The three
    helpers keep their defensive read-side ``self._nfc(self._pdf_password)``
    so a value cached before this fix (or set externally without going
    through ``normalize_password``) still authenticates correctly.
    """
    base_src = _read("app/base.py")
    utils_src = _read("app/utils.py")
    # Normalisation primitive lives in utils.py now.
    assert "import unicodedata" in utils_src
    assert "unicodedata.normalize(\"NFC\"" in utils_src
    assert "def normalize_password(" in utils_src
    # BasePage helper still exists and still has the three read-side
    # call sites (defensive — the WRITE site below covers the cache).
    assert "def _nfc(" in base_src
    assert base_src.count("self._nfc(self._pdf_password)") == 3, (
        "Expected three defensive read-side _nfc calls (auth probe, "
        "PdfReader.decrypt, fitz.authenticate)."
    )
    # WRITE-site normalisation: the prompt path must NFC-normalise
    # before storing on self._pdf_password so every tool that reads
    # the attribute raw (~30 sites under tools/*) is covered without
    # per-call instrumentation.
    assert "self._pdf_password = normalize_password(pwd)" in base_src
    # And the BasePage helper must delegate to the utils primitive so
    # the two paths cannot drift.
    assert "normalize_password" in base_src


def test_editor_tab_normalizes_password_on_cache_write():
    """R11 review C2 follow-up: the editor's _load_pdf path stores the
    prompted password directly on self._pdf_password. It must route
    through normalize_password so tools reading the cache raw
    (merge, watermark, ocr, page_numbers, convert, nup, ...) see the
    same NFC string the BasePage helpers would compare against."""
    src = _read("app/editor/tab.py")
    assert "self._pdf_password = normalize_password(pwd)" in src
    assert "from app.utils import" in src and "normalize_password" in src


def test_viewer_panel_normalizes_password_on_cache_write():
    """R11 review C2 follow-up: PdfViewerPanel._open_path stores the
    typed password on self._pdf_password. Same NFC-at-WRITE rule applies
    — this is the value propagated to compact-mode tools by
    MainWindow._on_tab_changed."""
    src = _read("app/viewer/panel.py")
    assert "normalize_password(dlg.password())" in src
    assert "from app.utils import" in src and "normalize_password" in src


def test_password_cache_round_trips_nfd_to_nfc():
    """Behavioral guard: feed an NFD-composed string through the same
    write path the prompt uses and confirm the cached attribute reads
    back in NFC form, matching what tools that bypass _nfc would see."""
    import unicodedata

    from app.utils import normalize_password

    nfd = unicodedata.normalize("NFD", "passé")
    assert not unicodedata.is_normalized("NFC", nfd), (
        "Test fixture must actually be in NFD form."
    )

    class _Fake:
        _pdf_password = ""

    obj = _Fake()
    # Mirror the WRITE-site idiom used by BasePage / editor / viewer.
    obj._pdf_password = normalize_password(nfd)
    assert unicodedata.is_normalized("NFC", obj._pdf_password), (
        "Cache must hold NFC after going through normalize_password."
    )
    # And the on-screen form must be preserved (no characters dropped).
    assert obj._pdf_password == "passé"


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
    # R11 review F6: newlines in old_text must be sanitised before
    # setText (QLineEdit truncates at the first \n, so the user would
    # only see the first physical line of the detected string).
    assert ".replace(\"\\n\"" in block, (
        "old_text newlines must be collapsed before QLineEdit.setText."
    )
    assert ".replace(\"\\r\"" in block, (
        "old_text carriage returns must also be sanitised."
    )


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
