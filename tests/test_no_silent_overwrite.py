"""Converter and Import never replace an existing output without asking.

Both tools pre-fill the output next to the input (``<stem>.xlsx`` for
Converter, ``<stem>.pdf`` for Import), so ``_resolve_output_file`` never
reached the Save dialog and ``TIC.pdf`` -> XLSX silently replaced the
user's own ``TIC.xlsx``. They now resolve through
``BasePage._resolve_output_file_guarded`` (and, for Converter's
``page_NNN`` images, ``_guard_folder_outputs``), which asks Replace /
Choose another name / Cancel when the target exists and was not picked
in a Save dialog for that same run. A Save dialog's answer covers one
run only: the run after it asks again, because the file on disk is by
then the one that run wrote, or one the user edited since.

Every test drives the real ``_run`` (or the real load + run flow): the
pre-flight, the guard and the ``do_work`` closure run for real, with
``_run_background`` executed inline. The real ``_ask_overwrite`` box is
built every time; ``QDialog.exec`` (which ``QMessageBox`` inherits) is
replaced by a stub that clicks the scripted button, so the button to
answer mapping is under test too. Every other modal fails closed: the
``QMessageBox`` / ``QFileDialog`` statics and any ``exec`` nobody
scripted are recorded as unexpected and answered as a cancel, so a
stray dialog fails the test instead of hanging the offscreen run.
"""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

_unused_app = QApplication.instance() or QApplication([])

import pymupdf

from app.i18n import t
from app.tools.convert import TabConverter
from app.tools.import_pdf import TabImport
from app.widgets import DropFileEdit

_FMT_PNG = 0
_FMT_DOCX = 2
_FMT_TXT = 3
_FMT_PPTX = 4
_FMT_XLSX = 5
_FMT_HTML = 6
_FMT_EPUB = 7
_IMPORT_TXT = 0

# Every single-file format the Converter writes, with the module its
# writer needs (None: no third-party writer).
_FILE_FORMATS = [
    pytest.param(_FMT_DOCX, ".docx", "docx", id="docx"),
    pytest.param(_FMT_TXT, ".txt", None, id="txt"),
    pytest.param(_FMT_PPTX, ".pptx", "pptx", id="pptx"),
    pytest.param(_FMT_XLSX, ".xlsx", "openpyxl", id="xlsx"),
    pytest.param(_FMT_HTML, ".html", None, id="html"),
    pytest.param(_FMT_EPUB, ".epub", "ebooklib", id="epub"),
]

_ROLE = {
    "replace": QMessageBox.ButtonRole.DestructiveRole,
    "rename": QMessageBox.ButtonRole.ActionRole,
    "cancel": QMessageBox.ButtonRole.RejectRole,
}


# -- helpers -----------------------------------------------------------------


def _digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _listing(folder) -> list[str]:
    return sorted(os.listdir(folder))


def _holds_text(path, text: str) -> bool:
    """``text`` is in the file, or in any member of it when it is a
    zip container (DOCX, PPTX, XLSX, EPUB)."""
    needle = text.encode("utf-8")
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            return any(needle in z.read(n) for n in z.namelist())
    return needle in Path(path).read_bytes()


def _make_pdf(path: Path, pages: int = 1) -> str:
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Hello page {i + 1}")
    doc.save(str(path))
    doc.close()
    return str(path)


class _Worker:
    def __init__(self):
        self.progress = self

    def emit(self, *args):
        pass

    def is_cancelled(self) -> bool:
        return False


@pytest.fixture
def ui(monkeypatch):
    """Fail-closed modal stand-ins plus a scripted overwrite answer.

    ``rec.answers`` is the queue of answers ("replace" / "rename" /
    "cancel") the overwrite box gets, in order; an overwrite box with
    no answer queued, or any other dialog's ``exec``, is recorded in
    ``rec.unexpected`` and returns without a click, which the tool must
    read as a cancel. ``rec.save_as`` / ``rec.dirs`` queue what the
    Save dialog and the folder picker return; each call is recorded in
    ``rec.save_calls`` / ``rec.dir_calls``, and a call with nothing
    queued is unexpected and answered as a cancel.
    """
    rec = SimpleNamespace(answers=[], asked=[], unexpected=[], infos=[],
                          warnings=[], errors=[], save_as=[], save_calls=[],
                          dirs=[], dir_calls=[], bg_calls=0, pages=[])

    def _exec(box):
        if isinstance(box, QMessageBox) \
                and box.windowTitle() == t("overwrite.title"):
            rec.asked.append(SimpleNamespace(
                text=box.text(),
                buttons={box.buttonRole(b): b.text() for b in box.buttons()},
                default=box.defaultButton(), escape=box.escapeButton(),
                cancel=next(b for b in box.buttons()
                            if box.buttonRole(b) == _ROLE["cancel"])))
            if rec.answers:
                role = _ROLE[rec.answers.pop(0)]
                for b in box.buttons():
                    if box.buttonRole(b) == role:
                        b.click()
                        break
                return 0
        rec.unexpected.append(("exec", type(box).__name__, box.windowTitle()))
        return QDialog.DialogCode.Rejected

    def _save(parent, caption="", directory="", filt="", *a, **k):
        rec.save_calls.append(directory)
        if rec.save_as:
            return rec.save_as.pop(0), ""
        rec.unexpected.append(("getSaveFileName", directory))
        return "", ""

    def _dir(parent, caption="", directory="", *a, **k):
        rec.dir_calls.append(directory)
        if rec.dirs:
            return rec.dirs.pop(0)
        rec.unexpected.append(("getExistingDirectory", directory))
        return ""

    def _unexpected(name, answer):
        def _stub(*a, **k):
            rec.unexpected.append((name,))
            return answer
        return staticmethod(_stub)

    monkeypatch.setattr(QDialog, "exec", _exec)
    # QMessageBox inherits exec today; patched too so a PySide6 that
    # binds its own override cannot slip past the stub into a real
    # modal loop.
    monkeypatch.setattr(QMessageBox, "exec", _exec)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(_save))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(_dir))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        _unexpected("getOpenFileName", ("", "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        _unexpected("getOpenFileNames", ([], "")))
    monkeypatch.setattr(QMessageBox, "question",
                        _unexpected("question", QMessageBox.StandardButton.No))
    monkeypatch.setattr(QMessageBox, "critical",
                        _unexpected("critical", QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "about", _unexpected("about", None))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(
        lambda *a, **k: rec.infos.append(a[1:3])))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(
        lambda *a, **k: rec.warnings.append(a[1:3])))
    monkeypatch.setattr("app.tools.convert.show_error",
                        lambda *a, **k: rec.errors.append(a[1:]))

    def _prompt(path, parent=None):
        rec.unexpected.append(("prompt_pdf_password", path))
        return False, ""
    monkeypatch.setattr("app.utils.prompt_pdf_password", _prompt)

    def inline(page):
        def _bg(do_work_fn, total=0, label="", on_done=None, on_err=None,
                cancelled_status=""):
            rec.bg_calls += 1
            result = do_work_fn(_Worker())
            if on_done is not None and result is not None:
                on_done(result)
        monkeypatch.setattr(page, "_run_background", _bg)
        rec.pages.append(page)
        return page

    rec.inline = inline
    yield rec
    # A failing test's traceback keeps its page alive; left to
    # interpreter shutdown, after QApplication, its destruction crashed
    # the process (0xC0000374) and hid the pytest summary.
    for page in rec.pages:
        page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not rec.unexpected, f"unexpected dialogs: {rec.unexpected!r}"
    assert not rec.errors, f"show_error called: {rec.errors!r}"
    # A scripted answer nobody consumed means a dialog the test relied
    # on never opened.
    unused = (rec.answers, rec.save_as, rec.dirs)
    assert not any(unused), f"unused answers / save_as / dirs: {unused!r}"


def _converter(ui, src: str, fmt: int) -> TabConverter:
    page = ui.inline(TabConverter(lambda *_: None))
    page.cmb_format.setCurrentIndex(fmt)
    # The real flow: dropping / opening the source runs _load_input,
    # which pre-fills <stem><ext> next to it.
    page.drop_in.set_path(src)
    return page


def _importer(ui, monkeypatch, sources: list[str]) -> TabImport:
    page = ui.inline(TabImport(lambda *_: None))
    page.cmb_type.setCurrentIndex(_IMPORT_TXT)
    # The real flow: "Add files" runs _pick_files, which pre-fills
    # <first stem>.pdf when the output is empty.
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: (list(sources), "")))
    page._pick_files()
    return page


# -- Converter: one output file ----------------------------------------------


@pytest.fixture
def conv_src(tmp_path):
    folder = tmp_path / "pasta com espaços ç"
    folder.mkdir()
    return _make_pdf(folder / "relatório final.pdf")


def test_converter_prefills_the_existing_sibling(ui, conv_src):
    """Premise: the pre-filled output is the sibling the user owns."""
    page = _converter(ui, conv_src, _FMT_TXT)
    assert os.path.normcase(os.path.normpath(page._drop_file.path())) == \
        os.path.normcase(os.path.normpath(conv_src[:-4] + ".txt"))


def test_converter_absent_output_runs_without_asking(ui, conv_src):
    target = conv_src[:-4] + ".txt"
    page = _converter(ui, conv_src, _FMT_TXT)
    page._run()
    assert ui.asked == []
    assert ui.bg_calls == 1
    assert "Hello page 1" in Path(target).read_text(encoding="utf-8")


@pytest.mark.parametrize(("fmt", "ext", "dep"), _FILE_FORMATS)
def test_converter_existing_output_cancel_keeps_original(ui, conv_src, fmt,
                                                         ext, dep):
    """The measured report: converting TIC.pdf to XLSX replaced TIC.xlsx.

    The guard runs before each format's dependency check, so ``dep`` is
    not needed: a missing writer must not let this case skip."""
    target = Path(conv_src[:-4] + ext)
    target.write_bytes(b"ORIGINAL USER FILE")
    before, listing = _digest(target), _listing(target.parent)
    ui.answers.append("cancel")
    page = _converter(ui, conv_src, fmt)
    page._run()
    assert len(ui.asked) == 1
    assert target.name in ui.asked[0].text
    assert _digest(target) == before
    assert _listing(target.parent) == listing  # no temp file, no output
    assert ui.bg_calls == 0
    assert ui.infos == []


def test_converter_closing_the_box_is_a_cancel(ui, conv_src):
    """Escape / title-bar X: exec returns with no button clicked."""
    target = Path(conv_src[:-4] + ".txt")
    target.write_bytes(b"ORIGINAL USER FILE")
    before = _digest(target)
    page = _converter(ui, conv_src, _FMT_TXT)
    page._run()
    assert len(ui.asked) == 1
    assert _digest(target) == before
    assert ui.bg_calls == 0
    # The unscripted exec is recorded as unexpected by design; it is
    # the point of this test, so clear it before the fixture checks.
    assert [u[0] for u in ui.unexpected] == ["exec"]
    ui.unexpected.clear()


@pytest.mark.parametrize(("fmt", "ext", "dep"), _FILE_FORMATS)
def test_converter_existing_output_replace_overwrites(ui, conv_src, fmt, ext,
                                                      dep):
    if dep:
        pytest.importorskip(dep)
    target = Path(conv_src[:-4] + ext)
    target.write_bytes(b"ORIGINAL USER FILE")
    ui.answers.append("replace")
    page = _converter(ui, conv_src, fmt)
    page._run()
    assert len(ui.asked) == 1
    assert ui.bg_calls == 1
    assert not _holds_text(target, "ORIGINAL USER FILE")
    assert _holds_text(target, "Hello page 1")


def test_converter_existing_output_rename_writes_chosen_path(ui, conv_src,
                                                             tmp_path):
    target = Path(conv_src[:-4] + ".txt")
    target.write_bytes(b"ORIGINAL USER FILE")
    before = _digest(target)
    chosen = tmp_path / "outro nome ã.txt"
    ui.answers.append("rename")
    ui.save_as.append(str(chosen))
    page = _converter(ui, conv_src, _FMT_TXT)
    page._run()
    assert len(ui.asked) == 1
    # The Save dialog opens on the clashing name, in its folder.
    assert len(ui.save_calls) == 1
    assert os.path.normcase(os.path.normpath(ui.save_calls[0])) == \
        os.path.normcase(os.path.normpath(str(target)))
    assert _digest(target) == before
    assert "Hello page 1" in chosen.read_text(encoding="utf-8")
    assert page._drop_file.path() == str(chosen)

    # The Save dialog's answer covered that run only: the next run onto
    # the file it wrote asks again, and Cancel leaves it as it is.
    first_result = _digest(chosen)
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 2
    assert chosen.name in ui.asked[1].text
    assert _digest(chosen) == first_result
    assert ui.bg_calls == 1


def test_converter_rename_then_external_edit_then_rerun_asks(ui, conv_src,
                                                             tmp_path):
    """qa-tester: "Choose another name", run, edit the output outside
    the app, run again (Ctrl+S runs ``_run``)."""
    target = Path(conv_src[:-4] + ".txt")
    target.write_bytes(b"ORIGINAL USER FILE")
    chosen = tmp_path / "outro nome ã.txt"
    ui.answers += ["rename", "cancel"]
    ui.save_as.append(str(chosen))
    page = _converter(ui, conv_src, _FMT_TXT)
    page._run()
    chosen.write_bytes(b"EDITED BY THE USER")
    edited = _digest(chosen)
    page._run()
    assert len(ui.asked) == 2
    assert _digest(chosen) == edited
    assert ui.bg_calls == 1


def test_converter_browse_saved_path_second_run_asks(ui, conv_src, tmp_path):
    """qa-tester: "Save as" to a new file, run, edit it, run again."""
    chosen = tmp_path / "novo ç.txt"
    page = _converter(ui, conv_src, _FMT_TXT)
    ui.save_as.append(str(chosen))
    page._drop_file.btn.click()
    assert not page._drop_file.is_confirmed()
    page._run()
    assert ui.asked == []
    assert "Hello page 1" in chosen.read_text(encoding="utf-8")
    chosen.write_bytes(b"EDITED BY THE USER")
    edited = _digest(chosen)
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 1
    assert _digest(chosen) == edited
    assert ui.bg_calls == 1


def test_converter_resolve_save_dialog_path_second_run_asks(ui, conv_src,
                                                            tmp_path):
    """The Save dialog an empty field falls through to covers its own
    run only, like the "Save as" button."""
    chosen = tmp_path / "pedido ç.txt"
    page = _converter(ui, conv_src, _FMT_TXT)
    page._drop_file.clear()
    ui.save_as.append(str(chosen))
    page._run()
    assert ui.asked == []
    assert page._drop_file.path() == str(chosen)
    chosen.write_bytes(b"EDITED BY THE USER")
    edited = _digest(chosen)
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 1
    assert _digest(chosen) == edited
    assert ui.bg_calls == 1


def test_converter_rename_then_cancelled_save_dialog_writes_nothing(
        ui, conv_src):
    target = Path(conv_src[:-4] + ".txt")
    target.write_bytes(b"ORIGINAL USER FILE")
    before, listing = _digest(target), _listing(target.parent)
    ui.answers.append("rename")
    ui.save_as.append("")
    page = _converter(ui, conv_src, _FMT_TXT)
    page._run()
    assert len(ui.save_calls) == 1
    assert _digest(target) == before
    assert _listing(target.parent) == listing
    assert ui.bg_calls == 0


def test_converter_output_from_browse_dialog_is_not_asked_again(ui, conv_src):
    """The output field's own "Save as" button runs QFileDialog, which
    already asked about replacing; a second question would be noise."""
    target = Path(conv_src[:-4] + ".txt")
    target.write_bytes(b"ORIGINAL USER FILE")
    page = _converter(ui, conv_src, _FMT_TXT)
    ui.save_as.append(str(target))
    page._drop_file.btn.click()
    page._run()
    assert ui.asked == []
    assert "Hello page 1" in target.read_text(encoding="utf-8")


def test_converter_output_from_resolve_save_dialog_is_not_asked(ui, conv_src):
    """An empty output field falls through to the Save dialog inside
    _resolve_output_file: no second question on top of it."""
    target = Path(conv_src[:-4] + ".txt")
    target.write_bytes(b"ORIGINAL USER FILE")
    page = _converter(ui, conv_src, _FMT_TXT)
    page._drop_file.clear()
    ui.save_as.append(str(target))
    page._run()
    assert len(ui.save_calls) == 1
    assert ui.asked == []
    assert "Hello page 1" in target.read_text(encoding="utf-8")


def test_converter_new_input_drops_the_confirmation(ui, conv_src, tmp_path):
    """A path confirmed for one input does not cover the next input's
    pre-filled sibling."""
    page = _converter(ui, conv_src, _FMT_TXT)
    picked = tmp_path / "picked.txt"
    picked.write_bytes(b"x")  # only an existing pick is confirmed
    ui.save_as.append(str(picked))
    page._drop_file.btn.click()
    assert page._drop_file.is_confirmed()
    other = _make_pdf(tmp_path / "outro.pdf")
    sibling = tmp_path / "outro.txt"
    sibling.write_bytes(b"ORIGINAL USER FILE")
    before = _digest(sibling)
    page.drop_in.set_path(other)
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 1
    assert _digest(sibling) == before


def test_converter_clear_drops_the_confirmation(ui, conv_src):
    """qa-tester: "Save as" onto the sibling, the field's X, reload the
    same input (which pre-fills that sibling again), run."""
    target = Path(conv_src[:-4] + ".txt")
    target.write_bytes(b"ORIGINAL USER FILE")
    before = _digest(target)
    page = _converter(ui, conv_src, _FMT_TXT)
    ui.save_as.append(str(target))
    page._drop_file.btn.click()
    page._drop_file._clr.click()
    assert page._drop_file.path() == ""
    page._load_input(conv_src)
    assert page._drop_file.path() == conv_src[:-4] + ".txt"
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 1
    assert _digest(target) == before
    assert ui.bg_calls == 0


def test_converter_browse_absent_path_created_before_run_asks(ui, conv_src,
                                                             tmp_path):
    """qa-tester P1: "Save as" to a name that does not exist (the Save
    dialog asks nothing), a file appears there before the run."""
    chosen = tmp_path / "ainda não existe.txt"
    page = _converter(ui, conv_src, _FMT_TXT)
    ui.save_as.append(str(chosen))
    page._drop_file.btn.click()
    assert page._drop_file.path() == str(chosen)
    chosen.write_bytes(b"CREATED BY ANOTHER PROGRAM")
    before = _digest(chosen)
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 1
    assert chosen.name in ui.asked[0].text
    assert _digest(chosen) == before
    assert ui.bg_calls == 0


def test_converter_browse_existing_second_run_asks(ui, conv_src, tmp_path):
    """The Save dialog's Replace covers the run after it, not the one
    after that."""
    chosen = tmp_path / "existente ç.txt"
    chosen.write_bytes(b"ORIGINAL USER FILE")
    page = _converter(ui, conv_src, _FMT_TXT)
    ui.save_as.append(str(chosen))
    page._drop_file.btn.click()
    page._run()
    assert ui.asked == []
    assert "Hello page 1" in chosen.read_text(encoding="utf-8")
    chosen.write_bytes(b"EDITED BY THE USER")
    edited = _digest(chosen)
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 1
    assert _digest(chosen) == edited
    assert ui.bg_calls == 1


def test_converter_rebrowse_same_absent_path_drops_old_mark(ui, conv_src,
                                                           tmp_path):
    """Browse onto an existing file (marked), the file is deleted, Browse
    to the same path again (the dialog asks nothing now), the file is
    created again before the run: the old answer must not cover it."""
    chosen = tmp_path / "reescolhido ç.txt"
    chosen.write_bytes(b"ORIGINAL USER FILE")
    page = _converter(ui, conv_src, _FMT_TXT)
    ui.save_as.append(str(chosen))
    page._drop_file.btn.click()
    assert page._drop_file.is_confirmed()
    chosen.unlink()
    ui.save_as.append(str(chosen))
    page._drop_file.btn.click()
    assert page._drop_file.path() == str(chosen)
    assert not page._drop_file.is_confirmed()
    chosen.write_bytes(b"CREATED OUTSIDE")
    before = _digest(chosen)
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 1
    assert _digest(chosen) == before
    assert ui.bg_calls == 0


def test_converter_browse_existing_deleted_before_run_mark_still_spent(
        ui, conv_src, tmp_path):
    """The mark is spent by the run it was meant for even when that run
    found nothing to replace: otherwise it would cover the file that
    run wrote, and a later edit of it."""
    chosen = tmp_path / "apagado ç.txt"
    chosen.write_bytes(b"ORIGINAL USER FILE")
    page = _converter(ui, conv_src, _FMT_TXT)
    ui.save_as.append(str(chosen))
    page._drop_file.btn.click()
    chosen.unlink()
    page._run()
    assert ui.asked == []
    chosen.write_bytes(b"EDITED BY THE USER")
    edited = _digest(chosen)
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 1
    assert _digest(chosen) == edited
    assert ui.bg_calls == 1


def test_converter_format_round_trip_does_not_revive_the_confirmation(
        ui, conv_src):
    """qa-tester P2: "Save as" onto the sibling, switch format away and
    back (which pre-fills that sibling again), edit it, run."""
    target = Path(conv_src[:-4] + ".txt")
    target.write_bytes(b"ORIGINAL USER FILE")
    page = _converter(ui, conv_src, _FMT_TXT)
    ui.save_as.append(str(target))
    page._drop_file.btn.click()
    page.cmb_format.setCurrentIndex(_FMT_DOCX)
    page.cmb_format.setCurrentIndex(_FMT_TXT)
    assert page._drop_file.path() == str(target)
    target.write_bytes(b"EDITED BY THE USER")
    edited = _digest(target)
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 1
    assert _digest(target) == edited
    assert ui.bg_calls == 0


def test_converter_input_round_trip_does_not_revive_the_confirmation(
        ui, conv_src, tmp_path):
    """qa-tester P2: "Save as" onto the sibling, load another input,
    load this one again (which pre-fills that sibling again), edit it,
    run."""
    target = Path(conv_src[:-4] + ".txt")
    target.write_bytes(b"ORIGINAL USER FILE")
    other = _make_pdf(tmp_path / "outro ç.pdf")
    page = _converter(ui, conv_src, _FMT_TXT)
    ui.save_as.append(str(target))
    page._drop_file.btn.click()
    page._load_input(other)
    page._load_input(conv_src)
    assert page._drop_file.path() == str(target)
    target.write_bytes(b"EDITED BY THE USER")
    edited = _digest(target)
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 1
    assert _digest(target) == edited
    assert ui.bg_calls == 0


def test_widget_set_path_elsewhere_revokes_mark():
    w = DropFileEdit(save=True)
    try:
        w.set_path("C:/x/out.pdf")
        w.mark_confirmed()
        w.set_path("C:/x/out.pdf")  # the same path keeps it
        assert w.is_confirmed()
        w.set_path("C:/x/other.pdf")
        w.set_path("C:/x/out.pdf")
        assert not w.is_confirmed()
    finally:
        w.deleteLater()


def test_widget_clear_resets_mark():
    w = DropFileEdit(save=True)
    try:
        w.set_path("C:/x/out.pdf")
        w.mark_confirmed()
        assert w.is_confirmed()
        w.clear()
        w.set_path("C:/x/out.pdf")
        assert not w.is_confirmed()
    finally:
        w.deleteLater()


def test_converter_pipeline_never_asks(ui, conv_src, tmp_path):
    """Guards the pipeline bypass in ``_resolve_output_file_guarded``.

    Production never reaches this state today: TabConverter leaves
    ``_pipeline_supported`` False, so ``set_compact_mode`` never turns
    ``_pipeline_active`` on. The flag is forced here so the bypass is
    covered before a pipeline tool calls the guard."""
    target = Path(conv_src[:-4] + ".txt")
    target.write_bytes(b"ORIGINAL USER FILE")
    before = _digest(target)
    page = _converter(ui, conv_src, _FMT_TXT)
    page._pipeline_active = True
    tmp_dir = tmp_path / "pipeline"
    tmp_dir.mkdir()
    page._pipeline_tmp_dir = str(tmp_dir)
    temp_out = Path(page._make_pipeline_temp(conv_src, page._drop_file))
    temp_out.write_bytes(b"previous pipeline step")
    page._run()
    assert ui.asked == []
    assert ui.save_calls == []
    assert _digest(target) == before
    assert "Hello page 1" in temp_out.read_text(encoding="utf-8")


# -- Converter: page_NNN images in a folder ----------------------------------


@pytest.fixture
def img_src(tmp_path):
    folder = tmp_path / "imagens ç"
    folder.mkdir()
    return _make_pdf(folder / "doc.pdf", pages=2)


def test_images_no_clash_runs_without_asking(ui, img_src):
    folder = Path(img_src).parent
    (folder / "notes.png").write_bytes(b"unrelated")
    page = _converter(ui, img_src, _FMT_PNG)
    page._run()
    assert ui.asked == []
    assert (folder / "page_001.png").exists()
    assert (folder / "page_002.png").exists()
    assert (folder / "notes.png").read_bytes() == b"unrelated"


def test_images_clash_cancel_writes_nothing(ui, img_src):
    folder = Path(img_src).parent
    (folder / "page_002.png").write_bytes(b"ORIGINAL PNG")
    listing = _listing(folder)
    ui.answers.append("cancel")
    page = _converter(ui, img_src, _FMT_PNG)
    statuses = []
    page._status = statuses.append
    page._run()
    assert len(ui.asked) == 1
    assert "page_002.png" in ui.asked[0].text
    assert ui.asked[0].buttons[_ROLE["rename"]] == t("overwrite.choose_folder")
    assert (folder / "page_002.png").read_bytes() == b"ORIGINAL PNG"
    assert _listing(folder) == listing
    assert ui.bg_calls == 0
    # No "starting PNG export" left in the status bar for a run that
    # never started.
    assert statuses == []


def test_images_clash_replace_overwrites(ui, img_src):
    folder = Path(img_src).parent
    (folder / "page_001.png").write_bytes(b"ORIGINAL PNG")
    ui.answers.append("replace")
    page = _converter(ui, img_src, _FMT_PNG)
    page._run()
    assert len(ui.asked) == 1
    assert (folder / "page_001.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_images_clash_other_folder_writes_there_and_rechecks(ui, img_src,
                                                             tmp_path):
    folder = Path(img_src).parent
    (folder / "page_001.png").write_bytes(b"ORIGINAL PNG")
    busy = tmp_path / "ocupada"
    busy.mkdir()
    (busy / "page_002.png").write_bytes(b"ALSO ORIGINAL")
    free = tmp_path / "livre ç"
    free.mkdir()
    # First folder clashes; the picked one clashes too and is asked
    # about again; the third is free.
    ui.answers += ["rename", "rename"]
    ui.dirs += [str(busy), str(free)]
    page = _converter(ui, img_src, _FMT_PNG)
    page._run()
    assert len(ui.asked) == 2
    assert (folder / "page_001.png").read_bytes() == b"ORIGINAL PNG"
    assert (busy / "page_002.png").read_bytes() == b"ALSO ORIGINAL"
    assert sorted(os.listdir(free)) == ["page_001.png", "page_002.png"]
    assert page._drop_folder.path() == str(free)


# -- Import ------------------------------------------------------------------


@pytest.fixture
def imp_src(tmp_path):
    folder = tmp_path / "notas ç"
    folder.mkdir()
    src = folder / "apontamentos ã.txt"
    src.write_text("line one\nline two\n", encoding="utf-8")
    return str(src)


def _pdf_text(path) -> str:
    with pymupdf.open(str(path)) as doc:
        return "".join(p.get_text() for p in doc)


def test_import_prefills_the_existing_sibling(ui, monkeypatch, imp_src):
    page = _importer(ui, monkeypatch, [imp_src])
    assert page.drop_out.path() == imp_src[:-4] + ".pdf"


def test_import_absent_output_runs_without_asking(ui, monkeypatch, imp_src):
    page = _importer(ui, monkeypatch, [imp_src])
    page._run()
    assert ui.asked == []
    assert "line one" in _pdf_text(imp_src[:-4] + ".pdf")


def test_import_existing_output_cancel_keeps_original(ui, monkeypatch,
                                                      imp_src):
    target = Path(imp_src[:-4] + ".pdf")
    _make_pdf(target)
    before, listing = _digest(target), _listing(target.parent)
    ui.answers.append("cancel")
    page = _importer(ui, monkeypatch, [imp_src])
    page._run()
    assert len(ui.asked) == 1
    assert target.name in ui.asked[0].text
    assert ui.asked[0].buttons[_ROLE["rename"]] == t("overwrite.choose_name")
    assert _digest(target) == before
    assert _listing(target.parent) == listing
    assert ui.bg_calls == 0
    assert ui.infos == []


def test_import_existing_output_replace_overwrites(ui, monkeypatch, imp_src):
    target = Path(imp_src[:-4] + ".pdf")
    _make_pdf(target)
    ui.answers.append("replace")
    page = _importer(ui, monkeypatch, [imp_src])
    page._run()
    assert len(ui.asked) == 1
    assert "line one" in _pdf_text(target)


def test_import_existing_output_rename_writes_chosen_path(ui, monkeypatch,
                                                          imp_src, tmp_path):
    target = Path(imp_src[:-4] + ".pdf")
    _make_pdf(target)
    before = _digest(target)
    chosen = tmp_path / "escolhido ç.pdf"
    ui.answers.append("rename")
    ui.save_as.append(str(chosen))
    page = _importer(ui, monkeypatch, [imp_src])
    page._run()
    assert len(ui.save_calls) == 1
    assert _digest(target) == before
    assert "line one" in _pdf_text(chosen)
    assert page.drop_out.path() == str(chosen)


def test_import_swapped_sources_onto_saved_path_asks(ui, monkeypatch,
                                                           imp_src, tmp_path):
    """qa-tester: "Save as" to a new file, run, swap the sources, run."""
    chosen = tmp_path / "guardado ç.pdf"
    page = _importer(ui, monkeypatch, [imp_src])
    ui.save_as.append(str(chosen))
    page.drop_out.btn.click()
    assert not page.drop_out.is_confirmed()
    page._run()
    assert ui.asked == []
    assert "line one" in _pdf_text(chosen)
    first_result = _digest(chosen)

    other = Path(imp_src).with_name("outras notas.txt")
    other.write_text("other text\n", encoding="utf-8")
    page._file_list.clear()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: ([str(other)], "")))
    page._pick_files()
    assert page.drop_out.path() == str(chosen)  # kept, not re-filled
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 1
    assert _digest(chosen) == first_result
    assert ui.bg_calls == 1


def test_import_browse_absent_path_created_before_run_asks(ui, monkeypatch,
                                                          imp_src, tmp_path):
    """qa-tester P1: "Save as" to a PDF that does not exist yet, another
    tool of the app (Merge) writes it, then Import runs."""
    chosen = tmp_path / "junção ç.pdf"
    page = _importer(ui, monkeypatch, [imp_src])
    ui.save_as.append(str(chosen))
    page.drop_out.btn.click()
    assert page.drop_out.path() == str(chosen)
    _make_pdf(chosen, pages=2)
    before = _digest(chosen)
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 1
    assert chosen.name in ui.asked[0].text
    assert _digest(chosen) == before
    assert ui.bg_calls == 0


def test_import_output_from_browse_dialog_is_not_asked_again(ui, monkeypatch,
                                                             imp_src):
    """The Save dialog already asked about the file it was pointed at:
    one question per run, not two."""
    target = Path(imp_src[:-4] + ".pdf")
    _make_pdf(target)
    page = _importer(ui, monkeypatch, [imp_src])
    ui.save_as.append(str(target))
    page.drop_out.btn.click()
    page._run()
    assert ui.asked == []
    assert ui.bg_calls == 1
    assert "line one" in _pdf_text(target)


def test_import_browse_existing_second_run_asks(ui, monkeypatch, imp_src,
                                                tmp_path):
    chosen = tmp_path / "existente ç.pdf"
    _make_pdf(chosen)
    page = _importer(ui, monkeypatch, [imp_src])
    ui.save_as.append(str(chosen))
    page.drop_out.btn.click()
    page._run()
    assert ui.asked == []
    first_result = _digest(chosen)
    ui.answers.append("cancel")
    page._run()
    assert len(ui.asked) == 1
    assert _digest(chosen) == first_result
    assert ui.bg_calls == 1


def test_import_pipeline_never_asks(ui, monkeypatch, imp_src, tmp_path):
    """Same unreachable state as ``test_converter_pipeline_never_asks``:
    TabImport leaves ``_pipeline_supported`` False, so production never
    runs it with ``_pipeline_active`` on. Forced here to cover the
    bypass before a pipeline tool calls the guard."""
    target = Path(imp_src[:-4] + ".pdf")
    _make_pdf(target)
    before = _digest(target)
    page = _importer(ui, monkeypatch, [imp_src])
    page._pipeline_active = True
    tmp_dir = tmp_path / "pipeline"
    tmp_dir.mkdir()
    page._pipeline_tmp_dir = str(tmp_dir)
    temp_out = Path(page._make_pipeline_temp(imp_src, page.drop_out))
    _make_pdf(temp_out)
    page._run()
    assert ui.asked == []
    assert ui.save_calls == []
    assert _digest(target) == before
    assert "line one" in _pdf_text(temp_out)


# -- the question itself -----------------------------------------------------


def test_overwrite_box_defaults_to_cancel(ui, conv_src):
    """Enter or Escape on the box must never replace."""
    Path(conv_src[:-4] + ".txt").write_bytes(b"x")
    ui.answers.append("cancel")
    page = _converter(ui, conv_src, _FMT_TXT)
    page._run()
    box = ui.asked[0]
    assert box.default is box.cancel
    assert box.escape is box.cancel
    assert box.buttons == {
        _ROLE["replace"]: t("overwrite.replace"),
        _ROLE["rename"]: t("overwrite.choose_name"),
        _ROLE["cancel"]: t("btn.cancel"),
    }
