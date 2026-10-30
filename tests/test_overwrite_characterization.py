"""Characterisation tests for where the tools write, and over what.

Step 0 of the document-centred work, whose increments are I2 (only the
main input's ``path_changed`` reaches the viewer), I3 (one
``_sync_active_tool()``, called on opening a tool, changing tab, loading
a document, closing and after the pipeline), I4 (the editor stops losing
edits), I5 (outputs never in the temp folder), I6 (temp file lifecycle)
and I7 (the top bar follows the active canvas); later, normal mode goes.
Pin what the code does *today*, through the real load and run paths,
before any of it changes. These defects are pinned:

* **A/B.** A tool pre-fills its output from the input only while the
  output field is empty (``if not self.drop_out.path():`` in each
  ``_load_input``, ``if paths and not self.drop_out.path():`` in
  Import's ``_pick_files``). Load A, then B, and the output stays A's:
  B's result is written to ``<folder of A>/<stem of A>_<suffix>``.
  The same guard is what keeps an output the user picked (through the
  field's button, or dropped on the field) when the input changes,
  which is wanted and pinned without a marker. Encrypt and Converter
  (one file) re-derive the output on every load, Encrypt on every mode
  change and Converter on every format change too: a derived name
  follows B, the mode and the format, which is wanted and pinned
  without a marker, but an output the user picked is lost, a defect
  pinned with the marker.
* **Silent overwrite.** The tools that still resolve through
  ``BasePage._resolve_output_file`` / ``_resolve_output_dir`` (and
  ``TabEditar._run``) replace an existing output without asking. A
  pipeline (compact mode) temp output is replaced without asking too,
  which is wanted, and pinned without a marker.
* **Stuck input in compact mode.** ``MainWindow._try_auto_load`` hands
  the viewer's PDF to the tool's ``auto_load``, which loads only while
  ``drop_in`` is empty, and ``MainWindow._on_tab_changed`` reloads
  nothing, so a tool reopened on another viewer tab keeps the first
  tab's PDF. Pinned through ``MainWindow`` for every tool with that
  guard. The guard itself is pinned without a marker. I3 is where this
  changes. The editor escapes: its
  ``set_compact_mode`` reloads the path it is given, pinned without a
  marker.
* **The open tool does not follow the viewer.** Stuck input's other
  half, one test per I3 trigger: a tool opened before the PDF stays
  empty and keeps asking (through ``_load_and_track`` and through
  ``PdfViewerPanel._open_dialog``, which does not pass there), a second
  PDF or a tab change leaves it on the other PDF, and closing the only
  tab leaves it compact on the closed PDF.
* **Edits lost on reopen** (I4). Closing and reopening the editor on the
  same PDF drops its pending edits, without asking.
* **Output in the temp folder** (I5). With a pipeline result in the
  viewer, Split, OCR and Converter write next to it, in the folder the
  pipeline's cleanup deletes.
* **Every field loads the viewer.** ``MainWindow.__init__`` connects
  the ``path_changed`` of every ``DropFileEdit`` of every tool to
  ``self._viewer.load``: the main input (``drop_in``, the editor's
  ``_drop_in``), which is wanted and pinned without a marker, and
  every other field, which is the defect. Pre-filling an output
  (on a load, an Encrypt mode change, a pipeline result reloaded into
  the tool) or choosing a secondary input (Watermark's mark through its
  button, an image dropped on the editor's image field) loads that path
  into the viewer when it is a file (a PDF of the user's; the
  watermark, which then becomes the pipeline's original; an encrypted
  one, which asks for its password and, on cancel, leaves the tab
  empty; a ``.txt`` or a ``.png``, which warns "invalid format"), and
  in every case renames the tab after it and records it in the recent
  files, even when no such file exists, or when it is a folder
  (Split), which the recent files' ``lexists`` filter keeps.

Tests marked ``known_defect`` pass today and pin a defect; each reason
says which increment changes it, or that none is scheduled, and whatever
changes it rewrites the test deliberately. List them with
``pytest -m known_defect``.

How the tools are driven: inputs go in through ``drop_in.set_path``,
whose ``path_changed`` runs the real ``_load_input``; ``_run`` is
called as the action button would. An output "the user picked" is
picked the way the user does it: a click on the field's own button,
with ``QFileDialog.getSaveFileName`` (``getExistingDirectory`` for a
folder) answering a path in a third folder. Watermark's mark is chosen
through its field's button too, ``getOpenFileName`` answering the mark.
A path "dropped" on a field arrives as a file manager delivers it: a
``QDragEnterEvent`` the field accepts, then a ``QDropEvent`` with the
file's URL (``_drop_on``). Replaced, so an offscreen run never blocks or
leaves the test thread:

* every modal, through ``_fail_closed_modals``: each call is recorded
  and answered as a cancel (a menu is closed with no action), and the
  ``env`` fixture fails the test on any record.
  ``QMessageBox.information`` / ``warning`` (the tools' normal outcome)
  are recorded instead of shown, and each tool's ``show_error`` is
  recorded and fails the test;
* ``_run_background`` runs inline (``_inline_background``); Compress
  and OCR start their own ``TaskRunner`` through ``run_task``, which
  runs ``do_work`` inline here;
* Compress's ``_compress_pdf`` is a stand-in that copies the source to
  the destination it is given: what is under test is the destination
  the tool resolves, not the compression (which may report "no gain"
  on a tiny PDF and write nothing). Each run checks the stand-in got
  the source and destination expected (``_check_stand_ins``);
* OCR never runs Tesseract: ``pytesseract`` is a fake module whose
  ``image_to_string`` returns ``"ocr"`` per page, ``--list-langs`` is
  answered ``["eng"]`` and the binary lookups return ``None``. Each run
  checks one call per source page, in the language the combo shows.

The ``MainWindow`` tests keep the user's configuration out of reach the
way ``test_viewer_shared_doc`` does: ``app.i18n._CONFIG_PATH`` points
at a file in ``tmp_path`` and ``UpdateController.check_async`` is a
no-op, so there is no network. Unlike that module, they also replace
``SingleInstanceServer`` with one that never listens, so a test window
cannot receive a PDF the user double-clicks meanwhile (see
``_window``). Measured: the recent files are the ``recent_files`` key
of that same file (``add_recent_file``,
``get_recent_files`` and ``_update_config`` read the module global at
call time), as are the tool usage and the layout saved on close. The
tests read the recents back from it.

Reach. Measured with every tool in a ``MainWindow``: the output field of
Rotate, Extract, Reorder, Compress, Page Numbers, N-up, Watermark, OCR,
Encrypt and Split is hidden for good (``setVisible(False)`` in each
``__init__``), and Converter's two output fields are hidden until a
format change in normal mode shows one. The visible ones are Merge's,
Import's and the editor's (normal mode). On a hidden field a user can
neither click the button nor drop a file, so the tests that pick or drop
an output there drive a state the UI does not reach today; they pin what
the code does with it, which matters if those fields are shown again.

Sources: A is one page reading "ALFA", B three pages reading "BRAVO",
in two folders with spaces and non-ASCII names; an existing output the
user owns is two pages reading "ORIGINAL USER FILE". ``_label`` tells
an output's origin from its text, or from its page count where the
text does not survive (OCR text, PNG pages), and answers "MISSING"
when nothing is there.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QMimeData,
    QObject,
    QPoint,
    QPointF,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QMessageBox,
    QWidget,
)

_unused_app = QApplication.instance() or QApplication([])

import pymupdf  # noqa: E402
import shiboken6  # noqa: E402
from _fail_closed_modals import (  # noqa: E402
    _MenuCloser,
    install_fail_closed_modals,
)
from _inline_background import run_background_inline  # noqa: E402

from app.editor.tab import TabEditar  # noqa: E402
from app.i18n import t  # noqa: E402
from app.tools.compress import TabComprimir  # noqa: E402
from app.tools.convert import TabConverter  # noqa: E402
from app.tools.encrypt import TabEncriptar  # noqa: E402
from app.tools.extract import TabExtrair  # noqa: E402
from app.tools.import_pdf import TabImport  # noqa: E402
from app.tools.info import TabInfo  # noqa: E402
from app.tools.merge import TabJuntar  # noqa: E402
from app.tools.nup import TabNUp  # noqa: E402
from app.tools.ocr import TabOCR  # noqa: E402
from app.tools.page_numbers import TabPageNumbers  # noqa: E402
from app.tools.reorder import TabReordenar  # noqa: E402
from app.tools.rotate import TabRotar  # noqa: E402
from app.tools.split import TabDividir  # noqa: E402
from app.tools.watermark import TabMarcaDagua  # noqa: E402

_AB_REASON = (
    "A/B: the output is pre-filled from the input only while it is "
    "empty, so a second input keeps the first input's output; I3 does "
    "not change these tests, which act at page level, below the "
    "MainWindow where its sync runs: it syncs the active tool with the "
    "document, and how the output is derived then is not decided")
_PICK_LOST_REASON = (
    "A/B: Encrypt and Converter (one file) re-derive the output on every "
    "load (Encrypt on every mode change, Converter on every format "
    "change too), so an output the user picked is lost; no increment "
    "from I2 to I7 covers it. A user can reach this only on Converter, "
    "in normal mode, which goes later: Encrypt's output field is hidden "
    "for good, in both modes")
_OVERWRITE_REASON = (
    "silent overwrite: an existing output is replaced without asking; "
    "no increment from I2 to I7 covers it")
_COMPACT_REASON = (
    "stuck input in compact mode: MainWindow._try_auto_load hands the "
    "viewer's PDF to auto_load, which loads only while drop_in is empty, "
    "so a tool reopened on another viewer tab keeps the first PDF; I3 "
    "syncs the tool with the viewer's current PDF")
_TOOL_BEFORE_PDF_REASON = (
    "tool opened before the PDF: loading a document does not tell the "
    "open tool, which stays empty and in normal mode, so it keeps asking "
    "for a file; I3's load trigger changes it, and only from where both "
    "gestures pass: PdfViewerPanel._open_dialog calls load without going "
    "through _load_and_track, so a trigger there leaves that gesture as "
    "it is, and one in _add_viewer_tab's _wrapped does not")
_INFO_BEFORE_PDF_REASON = (
    "Information opened before the PDF: loading a document does not tell "
    "the open tool, and Information has auto_load but no main input, so "
    "it stays blank with a PDF on screen; I3's load trigger changes it "
    "only if its sync also reaches a tool with no main input: a sync that "
    "looks for drop_in skips Information")
_SECOND_PDF_REASON = (
    "second PDF with a tool open: the new tab does not tell the open "
    "tool, which stays on the first PDF while the viewer shows the "
    "second; I3's load trigger changes it (its tab-change trigger alone "
    "fires on the still empty new tab and leaves the tool empty)")
_TAB_CHANGE_REASON = (
    "tab change with a tool open: _on_tab_changed does not tell the open "
    "tool, which stays on the other tab's PDF; I3's tab-change trigger "
    "changes it")
_CLOSE_REASON = (
    "closing the only tab with a tool open: _close_tab does not tell the "
    "open tool, which stays compact on the closed PDF; a run then "
    "writes a temp file that reappears in the empty viewer, with "
    "original_path '' in the pipeline state; I3's close trigger changes "
    "it")
_PENDING_LOST_REASON = (
    "edits lost on reopen: set_compact_mode reloads the path it is "
    "given even when it is the editor's current document, and _load_pdf "
    "clears the pending edits, with no question asked; I4 changes it")
_TEMP_OUTPUT_REASON = (
    "output in the temp folder: a tool outside the pipeline derives its "
    "output from the viewer's pipeline result, next to it, and the "
    "pipeline's cleanup deletes that folder with the user's result in "
    "it; I5 changes it")
_VIEWER_REASON = (
    "every field loads the viewer: MainWindow connects the path_changed "
    "of every DropFileEdit (outputs, Watermark's mark, the editor's "
    "image) to viewer.load; I2 keeps only the main input wired, so no "
    "other field loads the viewer, renames the tab or adds to the "
    "recent files")

_ORIGINAL = "ORIGINAL USER FILE"
_MISSING = "MISSING"
_FMT_PNG = 0
_FMT_DOCX = 2
_FMT_TXT = 3
_OCR_TXT = 1
_ENCRYPT = 0
_DECRYPT = 1

# The modules that import show_error (Import has none: its errors go
# through _run_background, which the inline stand-in records).
_TOOL_MODULES = (
    "app.tools.compress", "app.tools.convert", "app.tools.encrypt",
    "app.tools.extract", "app.tools.merge", "app.tools.nup",
    "app.tools.ocr", "app.tools.page_numbers", "app.tools.reorder",
    "app.tools.rotate", "app.tools.split", "app.tools.watermark",
    "app.editor.tab",
)


# -- files -------------------------------------------------------------------


def _make_pdf(path: Path, word: str, pages: int,
              user_pw: str | None = None) -> str:
    doc = pymupdf.open()
    for i in range(pages):
        # Mid-page: clear of the bands Page Numbers scans for existing
        # numbers, so no "replace existing numbers?" question.
        doc.new_page().insert_text((72, 300), f"{word} page {i + 1}")
    if user_pw:
        doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256,
                 user_pw=user_pw, owner_pw=user_pw)
    else:
        doc.save(str(path))
    doc.close()
    return str(path)


def _make_watermark(path: Path) -> str:
    doc = pymupdf.open()
    doc.new_page().draw_rect(pymupdf.Rect(100, 400, 300, 500), color=None,
                             fill=(1, 0, 0))
    doc.save(str(path))
    doc.close()
    return str(path)


def _write_original(path: str) -> None:
    """The user's own file, sitting where the tool will write."""
    if path.endswith(".txt"):
        Path(path).write_text(_ORIGINAL, encoding="utf-8")
    else:
        _make_pdf(Path(path), _ORIGINAL, 2)


def _label(path: str) -> str:
    """Which source a written output came from: "A", "B", "A+B" (Merge),
    "ORIGINAL" (left as the user had it), "MISSING" (nothing there) or a
    description."""
    p = Path(path)
    if not p.exists():
        return _MISSING
    if p.is_dir():
        n = len(list(p.glob("page_*.png")))
        return {0: _MISSING, 1: "A", 3: "B"}.get(n, f"{n} page images")
    if p.suffix == ".txt":
        text = p.read_text(encoding="utf-8")
        if _ORIGINAL in text:
            return "ORIGINAL"
        if "ALFA" in text:
            return "A"
        if "BRAVO" in text:
            return "B"
        # OCR text: one "ocr" per page, joined by form feeds.
        return {1: "A", 3: "B"}.get(text.count("\f") + 1, repr(text))
    doc = pymupdf.open(str(p))
    try:
        if doc.needs_pass:
            doc.authenticate("")  # Encrypt's output: empty user password
        text = "".join(page.get_text() for page in doc)
    finally:
        doc.close()
    found = [name for name, word in (("A", "ALFA"), ("B", "BRAVO"),
                                     ("ORIGINAL", _ORIGINAL))
             if word in text]
    return "+".join(found) or repr(text[:60])


def _written(path: str) -> bool:
    p = Path(path)
    if p.is_dir():
        return any(p.glob("page_*.png"))
    return p.exists()


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == \
        os.path.normcase(os.path.normpath(b))


def _pages(path: str) -> int:
    doc = pymupdf.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()


# -- tools -------------------------------------------------------------------


def _file_out(suffix: str, ext: str = ".pdf"):
    return lambda src: os.path.splitext(src)[0] + suffix + ext


def _folder_out(src: str) -> str:
    return os.path.dirname(src)


def _no_setup(page, env):
    pass


def _set_pages(page, env):
    page.edit_pages.setText("1")


def _set_watermark(page, env):
    # Through the field's own button, as the user picks it. The tool
    # does not listen to drop_wm, but in a MainWindow the pick also
    # loads the mark into the viewer (pinned in section 4). The
    # fail-closed Open dialog goes back once the pick is made.
    fail_closed = QFileDialog.__dict__["getOpenFileName"]
    asked = []

    def _open(*a, **k):
        asked.append("getOpenFileName")
        return env.wm, ""
    env.monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            staticmethod(_open))
    page.drop_wm.btn.click()
    env.monkeypatch.setattr(QFileDialog, "getOpenFileName", fail_closed)
    assert asked == ["getOpenFileName"]
    assert _same(page.drop_wm.path(), env.wm)


def _set_owner_password(page, env):
    page.edit_owner.setText(env.owner_pw)
    page.edit_owner_confirm.setText(env.owner_pw)


def _ocr_txt(page, env):
    page.cmb_fmt.setCurrentIndex(_OCR_TXT)


def _convert_png(page, env):
    page.cmb_format.setCurrentIndex(_FMT_PNG)


def _convert_txt(page, env):
    page.cmb_format.setCurrentIndex(_FMT_TXT)


def _add_note(tab, env):
    # The editor's own entry point for a new edit; _load_pdf clears the
    # pending list, so this runs after the last load.
    tab._add({"type": "note", "page": 0, "point": pymupdf.Point(72, 120),
              "text": "nota"})


def _spec(id, cls, out, *, produced=None, before_load=_no_setup,
          before_run=_no_setup, inline=False, in_attr="drop_in",
          out_attr="drop_out", pipeline_suffix=None):
    """One tool, as these tests drive it.

    ``out(src)`` is the output ``_load_input`` pre-fills for ``src``;
    ``produced(out)`` is what a run writes for that output (the file
    itself, or ``part_1.pdf`` / the ``page_NNN.png`` set in a folder).
    ``pipeline_suffix`` is the suffix of the pipeline temp name, which
    ``_make_pipeline_temp`` derives from the widget's ``default_name``,
    not from the suffix ``_load_input`` uses.
    """
    return SimpleNamespace(
        id=id, cls=cls, out=out, produced=produced or (lambda o: o),
        before_load=before_load, before_run=before_run, inline=inline,
        in_attr=in_attr, out_attr=out_attr, pipeline_suffix=pipeline_suffix,
        folder=out is _folder_out)


SPECS = {s.id: s for s in (
    _spec("rotate", TabRotar, _file_out("_rotated"),
          pipeline_suffix="_rotated"),
    _spec("extract", TabExtrair, _file_out("_extracted"),
          before_run=_set_pages, pipeline_suffix="_extracted"),
    _spec("reorder", TabReordenar, _file_out("_reordered"),
          pipeline_suffix="_reordered"),
    _spec("compress", TabComprimir, _file_out("_compressed"),
          pipeline_suffix="_compressed"),
    _spec("page_numbers", TabPageNumbers, _file_out("_numbered"),
          inline=True, pipeline_suffix="_numbered"),
    _spec("nup", TabNUp, _file_out("_nup"), inline=True,
          pipeline_suffix="_nup"),
    # Two sources of truth: _load_input pre-fills "_watermark", the
    # widget's default_name (pipeline temp, Save dialog) is
    # "watermarked.pdf".
    _spec("watermark", TabMarcaDagua, _file_out("_watermark"),
          before_run=_set_watermark, inline=True,
          pipeline_suffix="_watermarked"),
    # "_ocr" here, "ocr_output.pdf" as default_name.
    _spec("ocr", TabOCR, _file_out("_ocr", ".txt"), before_load=_ocr_txt),
    # "_enc" here, "result.pdf" as default_name.
    _spec("encrypt", TabEncriptar, _file_out("_enc"),
          before_run=_set_owner_password, pipeline_suffix="_result"),
    _spec("split", TabDividir, _folder_out,
          produced=lambda folder: os.path.join(folder, "part_1.pdf")),
    _spec("convert_png", TabConverter, _folder_out, before_load=_convert_png,
          inline=True, out_attr="_drop_folder"),
    _spec("convert_txt", TabConverter, _file_out("", ".txt"),
          before_load=_convert_txt, inline=True, out_attr="_drop_file"),
    # "_edited" here (tab.py _load_pdf), in _run's Save dialog
    # suggestion and in "output_edited.pdf" as default_name.
    _spec("editor", TabEditar, _file_out("_edited"), before_run=_add_note,
          in_attr="_drop_in", out_attr="_drop_out"),
)}

# The tools whose output stays at the first input's (A/B). The same
# guard keeps an output the user picked: the list was measured for
# both (Import, driven differently, has both too).
_STUCK_OUTPUT = ["rotate", "extract", "reorder", "compress", "page_numbers",
                 "nup", "watermark", "ocr", "split", "convert_png", "editor"]
# The tools whose output follows each new input, the user's pick
# included.
_FOLLOWING_OUTPUT = ["encrypt", "convert_txt"]
# The tools that pre-fill an output and replace it without asking.
_SILENT_OVERWRITE = ["rotate", "extract", "reorder", "compress",
                     "page_numbers", "nup", "watermark", "ocr", "encrypt",
                     "split", "editor"]
# The tools with _pipeline_supported = True.
_PIPELINE = ["rotate", "extract", "reorder", "compress", "page_numbers",
             "nup", "watermark", "encrypt"]
# The tools whose auto_load loads only while drop_in is empty.
_GUARDED_AUTO_LOAD = ["rotate", "extract", "reorder", "compress",
                      "page_numbers", "nup", "watermark", "ocr", "encrypt",
                      "split", "convert_txt"]
# _STUCK_OUTPUT less the fields that refuse the drop: the folder fields
# (Split, Converter's images) and OCR's text output take only a PDF
# (the field's filter), so a folder or a .txt is refused. Of the rest
# only the editor's field is visible (see "Reach" above).
_DROPPABLE_OUTPUT = ["rotate", "extract", "reorder", "compress",
                     "page_numbers", "nup", "watermark", "editor"]
# One spec per tool with a main input (Merge and Import have none).
_MAIN_INPUT = ["rotate", "extract", "reorder", "compress", "page_numbers",
               "nup", "watermark", "ocr", "encrypt", "split", "convert_txt",
               "editor"]


# -- harness -----------------------------------------------------------------


@pytest.fixture
def env(monkeypatch, tmp_path):
    """The sources, the fail-closed modals and the tool stand-ins.

    ``env.modals`` records every modal reached (all of them fail
    closed); ``env.infos`` / ``env.warnings`` the information and
    warning boxes; ``env.errors`` every ``show_error`` and every
    exception a background ``do_work`` raised; ``env.compress_calls``
    the (source, destination) of each ``_compress_pdf`` and
    ``env.ocr_langs`` the language of each page OCR'd. Teardown deletes
    the pages, then fails the test on any modal or error.
    """
    folder_a = tmp_path / "pasta A ç"
    folder_b = tmp_path / "pasta B ã"
    folder_a.mkdir()
    folder_b.mkdir()
    ns = SimpleNamespace(
        tmp=tmp_path,
        a=_make_pdf(folder_a / "alfa ç.pdf", "ALFA", 1),
        b=_make_pdf(folder_b / "bravo ã.pdf", "BRAVO", 3),
        wm=_make_watermark(tmp_path / "marca ç.pdf"),
        # Built at runtime: an inline literal would be a secret-scanner
        # hit (see .gitguardian.yaml).
        owner_pw=secrets.token_hex(8),
        modals=[], infos=[], warnings=[], errors=[], statuses=[],
        boxes=[], pages=[], compress_calls=[], ocr_langs=[],
        monkeypatch=monkeypatch,
    )
    install_fail_closed_modals(monkeypatch, ns.modals)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(
        lambda *a, **k: ns.infos.append(tuple(a[1:3]))))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(
        lambda *a, **k: ns.warnings.append(tuple(a[1:3]))))
    for mod in _TOOL_MODULES:
        monkeypatch.setattr(mod + ".show_error",
                            lambda *a, **k: ns.errors.append(a[1:]))

    def _sync_run_task(parent, runner, progress_dlg, on_finished,
                       on_error=None):
        progress_dlg.close()
        try:
            result = runner.do_work()
        except Exception as exc:  # recorded and asserted on at teardown
            ns.errors.append(("do_work", repr(exc)))
            return None
        on_finished(result)
        return None

    def _fake_compress(src, dst, level="recommended", progress_fn=None,
                       password=None):
        ns.compress_calls.append((src, dst))
        data = Path(src).read_bytes()
        fd, tmp = tempfile.mkstemp(suffix=".pdf",
                                   dir=os.path.dirname(dst) or ".")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dst)
        return len(data), len(data)

    fake_tess = types.ModuleType("pytesseract")
    fake_tess.pytesseract = SimpleNamespace(tesseract_cmd="tesseract")

    def _image_to_string(img, lang=None, **_kw):
        ns.ocr_langs.append(lang)
        return "ocr"
    fake_tess.image_to_string = _image_to_string

    monkeypatch.setitem(sys.modules, "pytesseract", fake_tess)
    monkeypatch.setattr("app.tools.ocr._find_tesseract", lambda: None)
    monkeypatch.setattr("app.tools.ocr._find_tessdata", lambda _exe: None)
    monkeypatch.setattr("app.tools.ocr.list_installed_langs",
                        lambda _cmd: ["eng"])
    monkeypatch.setattr("app.tools.ocr.run_task", _sync_run_task)
    monkeypatch.setattr("app.tools.compress.run_task", _sync_run_task)
    monkeypatch.setattr("app.tools.compress._compress_pdf", _fake_compress)

    def prepare(page, spec):
        if spec.inline:
            ns.boxes.append(run_background_inline(page, monkeypatch))
        spec.before_load(page, ns)
        return page

    def make(spec):
        page = spec.cls(ns.statuses.append)
        ns.pages.append(page)
        return prepare(page, spec)

    ns.make = make
    ns.prepare = prepare
    yield ns
    for page in ns.pages:
        if shiboken6.isValid(page):
            canvas = getattr(page, "_canvas", None)
            if canvas is not None:
                canvas.close_doc()
            page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert ns.modals == [], f"modal(s) reached: {ns.modals!r}"
    assert ns.errors == [], f"errors: {ns.errors!r}"
    background_errors = [b["error"] for b in ns.boxes if "error" in b]
    assert background_errors == [], background_errors


def _load(page, spec, path: str) -> None:
    getattr(page, spec.in_attr).set_path(path)


def _in(page, spec) -> str:
    return getattr(page, spec.in_attr).path()


def _out(page, spec) -> str:
    return getattr(page, spec.out_attr).path()


def _run(page, spec, env) -> None:
    spec.before_run(page, env)
    page._run()


def _params(ids, mark=None):
    marks = [mark] if mark is not None else []
    return [pytest.param(SPECS[i], id=i, marks=marks) for i in ids]


def _check_stand_ins(env, spec, page, src: str, dst: str = "") -> None:
    """One run reached the stand-ins as expected: Compress handed
    ``_compress_pdf`` ``src`` and ``dst``; OCR read every page of
    ``src`` in the language its combo shows; no other tool touched
    either."""
    if spec.id == "compress":
        assert len(env.compress_calls) == 1, env.compress_calls
        got_src, got_dst = env.compress_calls[0]
        assert _same(got_src, src) and _same(got_dst, dst), \
            env.compress_calls
    else:
        assert env.compress_calls == []
    if spec.id == "ocr":
        lang = page.cmb_lang.currentData()
        assert lang
        assert env.ocr_langs == [lang] * _pages(src)
    else:
        assert env.ocr_langs == []


def _user_pick(page, spec, env, monkeypatch) -> str:
    """Pick an output through the field's own button, as the user does:
    in a third folder, with the name the output derived from A has (a
    change that told a derived output by its name would lose this pick).
    A folder is a subfolder of that third folder, named likewise."""
    folder = env.tmp / "escolha ç"
    folder.mkdir(exist_ok=True)
    pick = str(folder / os.path.basename(spec.out(env.a)))
    if spec.folder:
        os.mkdir(pick)
    asked = []

    def _save(*a, **k):
        asked.append("getSaveFileName")
        return pick, ""

    def _dir(*a, **k):
        asked.append("getExistingDirectory")
        return pick
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(_save))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(_dir))
    getattr(page, spec.out_attr).btn.click()
    assert asked == ["getExistingDirectory" if spec.folder
                     else "getSaveFileName"]
    assert _same(_out(page, spec), pick)
    return pick


def _drop_on(field, path: str) -> None:
    """Drop ``path`` on ``field`` as a file manager does: a drag enter
    the field accepts, then the drop of the file's URL."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    enter = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    enter.ignore()
    QApplication.sendEvent(field, enter)
    assert enter.isAccepted()
    drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(field, drop)


# -- 1. A/B: the output follows the first input ------------------------------


@pytest.mark.parametrize(
    "spec", _params(_STUCK_OUTPUT,
                    pytest.mark.known_defect(reason=_AB_REASON)))
def test_second_input_keeps_the_first_inputs_output(env, spec):
    # Pinned for whoever changes it: re-deriving gives spec.out(env.b).
    page = env.make(spec)
    _load(page, spec, env.a)
    assert _same(_out(page, spec), spec.out(env.a))
    _load(page, spec, env.b)
    assert _same(_in(page, spec), env.b)
    assert _same(_out(page, spec), spec.out(env.a))


@pytest.mark.parametrize(
    "spec", _params(_STUCK_OUTPUT,
                    pytest.mark.known_defect(reason=_AB_REASON)))
def test_run_on_second_input_writes_into_first_inputs_output(env, spec):
    # Pinned for whoever changes it: re-deriving puts B's result in
    # spec.out(env.b) and writes nothing next to A.
    page = env.make(spec)
    _load(page, spec, env.a)
    _load(page, spec, env.b)
    _run(page, spec, env)
    assert _label(spec.produced(spec.out(env.a))) == "B"
    assert not _written(spec.produced(spec.out(env.b)))
    assert env.warnings == []
    assert len(env.infos) == 1
    _check_stand_ins(env, spec, page, env.b, spec.out(env.a))


@pytest.mark.parametrize("spec", _params(_FOLLOWING_OUTPUT))
def test_second_input_moves_the_output_with_it(env, spec):
    """Encrypt and Converter (one file) re-derive the output on every
    load. For a derived output that is the wanted result; for an output
    the user picked it is a defect, pinned by
    ``test_user_picked_output_is_lost_on_second_input``."""
    page = env.make(spec)
    _load(page, spec, env.a)
    _load(page, spec, env.b)
    assert _same(_out(page, spec), spec.out(env.b))
    _run(page, spec, env)
    assert _label(spec.produced(spec.out(env.b))) == "B"
    assert not _written(spec.produced(spec.out(env.a)))
    assert len(env.infos) == 1
    _check_stand_ins(env, spec, page, env.b, spec.out(env.b))


@pytest.mark.parametrize("spec", _params(_STUCK_OUTPUT))
def test_user_picked_output_survives_second_input(env, spec, monkeypatch):
    """An output the user picked stays when the input changes, and B's
    result lands there. Today this comes from the same "pre-fill only
    while empty" guard as the A/B defect, so anything that re-derives
    the output must keep it. The pick is named as the output derived
    from A, in another folder: a name cannot tell it from a derived one."""
    page = env.make(spec)
    _load(page, spec, env.a)
    pick = _user_pick(page, spec, env, monkeypatch)
    _load(page, spec, env.b)
    assert _same(_in(page, spec), env.b)
    assert _same(_out(page, spec), pick)
    _run(page, spec, env)
    assert _label(spec.produced(pick)) == "B"
    assert not _written(spec.produced(spec.out(env.a)))
    assert not _written(spec.produced(spec.out(env.b)))
    assert env.warnings == []
    assert len(env.infos) == 1
    _check_stand_ins(env, spec, page, env.b, pick)


@pytest.mark.parametrize("spec", _params(_DROPPABLE_OUTPUT))
def test_user_dropped_output_survives_second_input(env, spec):
    """An output the user dropped on the field (a file of theirs, dragged
    from the file manager) stays when the input changes, as a picked one
    does: anything that re-derives the output must tell a drop from a
    pre-fill too, not only a pick through the button. Named as the
    output derived from A, in another folder: a name cannot tell them
    apart. The drop asked nothing, so it is not confirmed. Not run: what
    a run does over an existing output is section 2."""
    page = env.make(spec)
    _load(page, spec, env.a)
    field = getattr(page, spec.out_attr)
    folder = env.tmp / "escolha ç"
    folder.mkdir()
    dropped = str(folder / os.path.basename(spec.out(env.a)))
    _write_original(dropped)
    _drop_on(field, dropped)
    assert _same(_out(page, spec), dropped)
    _load(page, spec, env.b)
    assert _same(_in(page, spec), env.b)
    assert _same(_out(page, spec), dropped)
    assert not field.is_confirmed()
    assert _label(dropped) == "ORIGINAL"


def test_encrypt_mode_change_moves_a_derived_output(env):
    """A derived output follows the mode, "_enc" to "_dec" and back:
    wanted, and what any fix for the lost pick must keep."""
    spec = SPECS["encrypt"]
    page = env.make(spec)
    _load(page, spec, env.a)
    base = os.path.splitext(env.a)[0]
    assert _same(_out(page, spec), base + "_enc.pdf")
    page.cmb_mode.setCurrentIndex(_DECRYPT)
    assert _same(_out(page, spec), base + "_dec.pdf")
    page.cmb_mode.setCurrentIndex(_ENCRYPT)
    assert _same(_out(page, spec), base + "_enc.pdf")


def test_convert_format_change_moves_a_derived_output(env):
    """A derived one-file output follows the format, ".txt" to ".docx"
    and back: wanted, and what any fix for the lost pick must keep."""
    spec = SPECS["convert_txt"]
    page = env.make(spec)
    _load(page, spec, env.a)
    base = os.path.splitext(env.a)[0]
    assert _same(_out(page, spec), base + ".txt")
    page.cmb_format.setCurrentIndex(_FMT_DOCX)
    assert _same(_out(page, spec), base + ".docx")
    page.cmb_format.setCurrentIndex(_FMT_TXT)
    assert _same(_out(page, spec), base + ".txt")


@pytest.mark.parametrize(
    "spec", _params(_FOLLOWING_OUTPUT,
                    pytest.mark.known_defect(reason=_PICK_LOST_REASON)))
def test_user_picked_output_is_lost_on_second_input(env, spec, monkeypatch):
    # Pinned for whoever changes it: the output stays the user's pick,
    # and B's result lands there, as in
    # test_user_picked_output_survives_second_input.
    page = env.make(spec)
    _load(page, spec, env.a)
    pick = _user_pick(page, spec, env, monkeypatch)
    _load(page, spec, env.b)
    assert _same(_out(page, spec), spec.out(env.b))
    _run(page, spec, env)
    assert _label(spec.produced(spec.out(env.b))) == "B"
    assert _label(spec.produced(pick)) == _MISSING
    assert len(env.infos) == 1
    _check_stand_ins(env, spec, page, env.b, spec.out(env.b))


@pytest.mark.known_defect(reason=_PICK_LOST_REASON)
def test_encrypt_user_picked_output_is_lost_on_mode_change(env, monkeypatch):
    # Pinned for whoever changes it: Decrypt keeps the user's pick.
    spec = SPECS["encrypt"]
    page = env.make(spec)
    _load(page, spec, env.a)
    _user_pick(page, spec, env, monkeypatch)
    page.cmb_mode.setCurrentIndex(_DECRYPT)
    assert _same(_out(page, spec),
                 os.path.splitext(env.a)[0] + "_dec.pdf")


@pytest.mark.known_defect(reason=_PICK_LOST_REASON)
def test_convert_user_picked_output_is_lost_on_format_change(
        env, monkeypatch):
    # Pinned for whoever changes it: the format keeps the user's pick
    # (whether its extension follows the new format is that change's
    # call).
    spec = SPECS["convert_txt"]
    page = env.make(spec)
    _load(page, spec, env.a)
    pick = _user_pick(page, spec, env, monkeypatch)
    page.cmb_format.setCurrentIndex(_FMT_DOCX)
    assert _same(_out(page, spec), os.path.splitext(env.a)[0] + ".docx")
    assert os.path.dirname(_out(page, spec)) != os.path.dirname(pick)


# Import takes its sources from a list filled through a file dialog,
# not from drop_in, so it has its own driver.


def _import_sources(env) -> tuple[str, str]:
    # Text sources in their own folders: Import derives "<stem>.pdf",
    # which next to env.a would be env.a itself.
    a_dir = env.tmp / "texto A ç"
    b_dir = env.tmp / "texto B ã"
    a_dir.mkdir()
    b_dir.mkdir()
    a = a_dir / "alfa ç.txt"
    b = b_dir / "bravo ã.txt"
    a.write_text("ALFA", encoding="utf-8")
    b.write_text("BRAVO", encoding="utf-8")
    return str(a), str(b)


def _import_pick_files(page, monkeypatch, paths: list[str]) -> None:
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: (list(paths), "")))
    page._add_btn.click()


@pytest.mark.known_defect(reason=_AB_REASON)
def test_import_second_pick_keeps_the_first_output(env, monkeypatch):
    # Pinned for whoever changes it: after removing A and picking B the
    # output is B's "<stem>.pdf", and B's result lands there.
    a, b = _import_sources(env)
    page = env.make(SimpleNamespace(cls=TabImport, inline=True,
                                    before_load=_no_setup))
    _import_pick_files(page, monkeypatch, [a])
    out_a = os.path.splitext(a)[0] + ".pdf"
    out_b = os.path.splitext(b)[0] + ".pdf"
    assert _same(page.drop_out.path(), out_a)
    page._remove_btn.click()
    assert page._get_files() == []
    _import_pick_files(page, monkeypatch, [b])
    assert page._get_files() == [b]
    assert _same(page.drop_out.path(), out_a)
    page._run()
    assert _label(out_a) == "B"
    assert _label(out_b) == _MISSING
    assert env.warnings == []
    assert len(env.infos) == 1


def test_import_user_picked_output_survives_picking_files(env, monkeypatch):
    """An output the user picked before adding the files stays, and the
    result lands there; anything that re-derives Import's output must
    keep it. The pick is named as the output derived from A, in another
    folder: a name cannot tell it from a derived one."""
    a, _b = _import_sources(env)
    page = env.make(SimpleNamespace(cls=TabImport, inline=True,
                                    before_load=_no_setup))
    folder = env.tmp / "escolha ç"
    folder.mkdir()
    pick = str(folder / (Path(a).stem + ".pdf"))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (pick, "")))
    page.drop_out.btn.click()
    assert _same(page.drop_out.path(), pick)
    _import_pick_files(page, monkeypatch, [a])
    assert _same(page.drop_out.path(), pick)
    page._run()
    assert _label(pick) == "A"
    assert _label(os.path.splitext(a)[0] + ".pdf") == _MISSING
    assert len(env.infos) == 1


# -- 2. silent overwrite -----------------------------------------------------


@pytest.mark.parametrize(
    "spec", _params(_SILENT_OVERWRITE,
                    pytest.mark.known_defect(reason=_OVERWRITE_REASON)))
def test_existing_prefilled_output_is_replaced_without_asking(env, spec):
    # Pinned for whoever changes it: a run that asks first (Replace /
    # Choose another name / Cancel) is one modal, and Cancel leaves the
    # user's file as it was.
    target = spec.produced(spec.out(env.a))
    _write_original(target)
    page = env.make(spec)
    _load(page, spec, env.a)
    _run(page, spec, env)
    assert env.modals == []
    assert _label(target) == "A"
    assert env.warnings == []
    assert len(env.infos) == 1
    _check_stand_ins(env, spec, page, env.a, target)


@pytest.mark.known_defect(reason=_OVERWRITE_REASON)
def test_merge_second_run_replaces_the_first_runs_pick_without_asking(
        env, monkeypatch):
    # Pinned for whoever changes it: the second run asks before replacing
    # the file the first run's Save dialog chose (that dialog covered its
    # own run only).
    chosen = str(env.tmp / "junção final ç.pdf")
    save_calls = []

    def _save(parent, caption="", directory="", filt="", *a, **k):
        save_calls.append(directory)
        return chosen, ""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(_save))

    page = env.make(SimpleNamespace(cls=TabJuntar, inline=False,
                                    before_load=_no_setup))
    page._on_drop([env.a, env.b])
    page._run()
    assert len(save_calls) == 1
    assert _label(chosen) == "A+B"
    # The user replaces the merged file with their own between runs,
    # and merges the two PDFs again in the other order.
    _write_original(chosen)
    page._clear_all()
    page._on_drop([env.b, env.a])
    page._run()
    assert len(save_calls) == 1
    assert env.modals == []
    assert _label(chosen) == "A+B"
    assert len(env.infos) == 2


@pytest.mark.parametrize("spec", _params(_PIPELINE))
def test_pipeline_temp_output_is_replaced_without_asking(env, spec):
    """In compact mode a pipeline tool writes a temp file of its own,
    which it may replace without asking; the user's file next to the
    input is not touched."""
    page = env.make(spec)
    pipe = env.tmp / "pipeline"
    pipe.mkdir()
    page._pipeline_tmp_dir = str(pipe)
    done = []
    page.pipeline_done.connect(done.append)
    page.set_compact_mode(True, env.a)
    assert page._pipeline_active
    temp = page._make_pipeline_temp(env.a, page.drop_out)
    # Named from the widget's default_name, not from _load_input's suffix.
    assert Path(temp).name == Path(env.a).stem + spec.pipeline_suffix + ".pdf"
    _write_original(temp)
    users = spec.out(env.a)
    _write_original(users)
    _run(page, spec, env)
    assert env.modals == []
    assert done == [temp]
    assert _label(temp) == "A"
    assert _label(users) == "ORIGINAL"
    assert env.infos == []
    _check_stand_ins(env, spec, page, env.a, temp)


# -- 3. stuck input in compact mode ------------------------------------------


@pytest.mark.parametrize("spec", _params(_GUARDED_AUTO_LOAD))
def test_auto_load_loads_only_while_the_input_is_empty(env, spec):
    """auto_load's own guard: it loads a path only while ``drop_in`` is
    empty, and loads the next one once ``drop_in`` is cleared.

    Not the stuck-input defect, which needs MainWindow to show (see
    ``test_window_tool_reopened_on_second_tab_runs_on_first_pdf``). I3
    syncs the tool from ``MainWindow``; clearing ``drop_in`` when it
    differs from the viewer's PDF relies on both halves of this guard, as
    ``_on_pipeline_done`` already does (it clears ``drop_in`` and
    ``drop_out`` before calling ``auto_load``). A sync that drops the
    guard inside ``auto_load`` instead rewrites this test deliberately."""
    page = env.make(spec)
    page.auto_load(env.a)
    assert _same(_in(page, spec), env.a)
    page.auto_load(env.b)
    assert _same(_in(page, spec), env.a)
    getattr(page, spec.in_attr).clear()
    page.auto_load(env.b)
    assert _same(_in(page, spec), env.b)


def test_editor_compact_mode_reloads_the_new_input(env):
    """The editor escapes: its set_compact_mode reloads whatever path it
    is given, after auto_load (guarded like the tools') declined it."""
    spec = SPECS["editor"]
    tab = env.make(spec)
    tab.set_compact_mode(True, env.a)
    assert _same(tab._doc_path, env.a)
    tab.auto_load(env.b)
    tab.set_compact_mode(True, env.b)
    assert _same(tab._doc_path, env.b)
    assert _same(_in(tab, spec), env.b)


class _NoInstanceServer(QObject):
    """Stands in for SingleInstanceServer: never listens."""

    new_paths = Signal(list)


def _window(monkeypatch, tmp_path):
    from app.update_controller import UpdateController
    from app.window import MainWindow

    monkeypatch.setattr("app.i18n._CONFIG_PATH",
                        str(tmp_path / "config.json"))
    monkeypatch.setattr(UpdateController, "check_async", lambda self: None)
    # A real SingleInstanceServer listens on the user's own pipe
    # (measured on Windows: \\.\pipe\pdfapps-single-instance-<hash>,
    # bound by a test process), so a PDF the user double-clicks while
    # the suite runs can be forwarded to a test window, which opens it
    # in a new tab and raises itself. Seen once: the current tab changed
    # under test_window_tool_reopened_on_second_tab_runs_on_first_pdf,
    # with Qt's "does not support raise()" from _on_second_instance.
    monkeypatch.setattr("app.window.SingleInstanceServer", _NoInstanceServer)
    win = MainWindow()
    assert isinstance(win._instance_server, _NoInstanceServer)
    return win


def _recents(tmp_path) -> list[str]:
    """The recent files, read back from the throwaway config."""
    cfg = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    return cfg.get("recent_files", [])


def _assert_recents(tmp_path, expected: list[str]) -> None:
    got = _recents(tmp_path)
    assert len(got) == len(expected) and all(
        _same(g, e) for g, e in zip(got, expected, strict=True)), got


def _nav_item(win, cls):
    from app.window import NAV_ITEMS

    index = next(i for i, item in enumerate(NAV_ITEMS) if item[2] is cls)
    for row in range(win.nav.count()):
        item = win.nav.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == index:
            return win.stack.widget(index), item
    raise AssertionError(f"no nav row for {cls.__name__}")


def _close_window(win, qtbot, tmp_path):
    # Drop the pipeline result first, so closeEvent has no unsaved
    # pipeline to ask about.
    for viewer in list(win._viewers):
        win._cleanup_pipeline(id(viewer))
    win.close()
    win.deleteLater()
    qtbot.wait(50)
    # Recents, tool usage and the layout saved on close landed in the
    # throwaway config: proof the _CONFIG_PATH patch reached them.
    assert (tmp_path / "config.json").is_file()


@pytest.mark.parametrize(
    "spec", _params(_GUARDED_AUTO_LOAD,
                    pytest.mark.known_defect(reason=_COMPACT_REASON)))
def test_window_tool_reopened_on_second_tab_runs_on_first_pdf(
        env, spec, monkeypatch, qtbot):
    # After I3: reopened on B's tab, the tool loads B, and its run works
    # on B: a pipeline tool shows B's result in B's tab, the others
    # write B's result next to B.
    win = _window(monkeypatch, env.tmp)
    try:
        page, item = _nav_item(win, spec.cls)
        env.prepare(page, spec)
        win._load_and_track(env.a)
        qtbot.wait(50)
        win._on_nav_clicked(item)
        assert _same(_in(page, spec), env.a)
        assert page._compact_active

        win._load_and_track(env.b)  # opens in a second tab
        qtbot.wait(50)
        assert win._tab_bar.count() == 2
        tab_b = win._viewer
        assert _same(tab_b.current_path(), env.b)

        win._on_nav_clicked(item)  # close the tool
        win._on_nav_clicked(item)  # and open it again, on B's tab
        assert win.stack.currentWidget() is page
        assert _same(_in(page, spec), env.a)

        pipe = env.tmp / "pipeline"
        pipe.mkdir()
        page._pipeline_tmp_dir = str(pipe)
        _run(page, spec, env)
        qtbot.wait(50)
        assert win._viewer is tab_b
        if spec.id in _PIPELINE:
            shown = tab_b.current_path()
            assert Path(shown).name == \
                Path(env.a).stem + spec.pipeline_suffix + ".pdf"
            assert _label(shown) == "A"
            assert env.infos == []
            _check_stand_ins(env, spec, page, env.a, shown)
        else:
            assert _label(spec.produced(spec.out(env.a))) == "A"
            assert _label(spec.produced(spec.out(env.b))) == _MISSING
            assert len(env.infos) == 1
            _check_stand_ins(env, spec, page, env.a, spec.out(env.a))
        # The tab's title is another defect's, pinned on its own by
        # test_window_pipeline_result_renames_tab_after_its_prefilled_output
        # (section 4): asserted here, I2 would have to rewrite this
        # stuck-input test too.
    finally:
        _close_window(win, qtbot, env.tmp)


def test_window_editor_reopened_on_second_tab_loads_second_pdf(
        env, monkeypatch, qtbot):
    """The editor escapes the stuck input through its own
    set_compact_mode, which MainWindow._try_auto_load calls after
    auto_load."""
    win = _window(monkeypatch, env.tmp)
    try:
        editor, item = _nav_item(win, TabEditar)
        win._load_and_track(env.a)
        qtbot.wait(50)
        win._on_nav_clicked(item)
        assert _same(editor._doc_path, env.a)

        win._load_and_track(env.b)
        qtbot.wait(50)
        win._on_nav_clicked(item)
        win._on_nav_clicked(item)
        assert _same(editor._doc_path, env.b)
        assert _same(editor._drop_in.path(), env.b)
    finally:
        _close_window(win, qtbot, env.tmp)


def _gesture_load_and_track(win, env, path: str) -> None:
    win._load_and_track(path)


def _gesture_open_dialog(win, env, path: str) -> None:
    # The placeholder's own button: PdfViewerPanel._open_dialog, which
    # calls self.load and never reaches _load_and_track. The fail-closed
    # Open dialog goes back once the answer is taken.
    fail_closed = QFileDialog.__dict__["getOpenFileName"]
    asked = []

    def _open(*a, **k):
        asked.append("getOpenFileName")
        return path, ""
    env.monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            staticmethod(_open))
    win._viewer._ph_btn.click()
    env.monkeypatch.setattr(QFileDialog, "getOpenFileName", fail_closed)
    assert asked == ["getOpenFileName"]


@pytest.mark.known_defect(reason=_TOOL_BEFORE_PDF_REASON)
@pytest.mark.parametrize(
    "gesture", [_gesture_load_and_track, _gesture_open_dialog],
    ids=["load_and_track", "open_dialog"])
@pytest.mark.parametrize("spec", _params(_MAIN_INPUT))
def test_window_tool_opened_before_the_pdf_keeps_asking(
        env, spec, gesture, monkeypatch, qtbot):
    # After I3: the tool loads A and goes compact, from both gestures.
    # The editor hides the viewer while open, so its open_dialog case is
    # a state the UI does not reach today; its load_and_track case is
    # Ctrl+O.
    win = _window(monkeypatch, env.tmp)
    try:
        page, item = _nav_item(win, spec.cls)
        env.prepare(page, spec)
        win._on_nav_clicked(item)  # no PDF in the viewer: normal mode
        gesture(win, env, env.a)
        qtbot.wait(50)
        assert win._tab_bar.count() == 1
        assert _same(win._viewer.current_path(), env.a)
        assert win.stack.currentWidget() is page
        assert _in(page, spec) == ""
        if spec.id == "editor":  # no _compact_active of its own
            assert not page._doc_path
        else:
            assert not page._compact_active
        page._run()  # the complaint: "select a PDF", with one on screen
        assert len(env.warnings) == 1
        assert env.infos == []
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_INFO_BEFORE_PDF_REASON)
def test_window_info_ignores_the_pdf_opened_after_it(
        env, monkeypatch, qtbot):
    # After I3: Information shows A's details.
    win = _window(monkeypatch, env.tmp)
    try:
        page, item = _nav_item(win, TabInfo)
        win._on_nav_clicked(item)  # no PDF in the viewer
        assert page.txt.toPlainText() == ""
        win._load_and_track(env.a)
        qtbot.wait(50)
        assert _same(win._viewer.current_path(), env.a)
        assert win.stack.currentWidget() is page
        assert page.txt.toPlainText() == ""
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_SECOND_PDF_REASON)
def test_window_second_pdf_leaves_the_open_tool_on_the_first(
        env, monkeypatch, qtbot):
    # After I3: the tool follows the viewer to B.
    win = _window(monkeypatch, env.tmp)
    try:
        rotate = _open_tool_on(win, qtbot, TabRotar, env.a)
        assert _same(rotate.drop_in.path(), env.a)
        win._load_and_track(env.b)
        qtbot.wait(50)
        assert win._tab_bar.count() == 2
        assert _same(win._viewer.current_path(), env.b)
        assert _same(rotate.drop_in.path(), env.a)
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_TAB_CHANGE_REASON)
def test_window_tab_change_leaves_the_open_tool_on_the_other_tabs_pdf(
        env, monkeypatch, qtbot):
    # After I3: back on A's tab, the tool is on A.
    win = _window(monkeypatch, env.tmp)
    try:
        win._load_and_track(env.a)
        qtbot.wait(50)
        rotate = _open_tool_on(win, qtbot, TabRotar, env.b)
        assert win._tab_bar.count() == 2
        assert _same(rotate.drop_in.path(), env.b)
        win._tab_bar.setCurrentIndex(0)
        qtbot.wait(50)
        assert _same(win._viewer.current_path(), env.a)
        assert _same(rotate.drop_in.path(), env.b)
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_CLOSE_REASON)
def test_window_closing_the_tab_leaves_the_tool_on_the_closed_pdf(
        env, monkeypatch, qtbot):
    # After I3: the tool is empty and in normal mode, and has nothing to
    # run on.
    spec = SPECS["rotate"]
    win = _window(monkeypatch, env.tmp)
    try:
        rotate = _open_tool_on(win, qtbot, TabRotar, env.a)
        win._tab_bar.tabCloseRequested.emit(0)
        qtbot.wait(50)
        assert win._viewer.current_path() == ""
        assert _same(rotate.drop_in.path(), env.a)
        assert rotate._compact_active

        pipe = env.tmp / "pipeline"
        pipe.mkdir()
        rotate._pipeline_tmp_dir = str(pipe)
        _run(rotate, spec, env)
        qtbot.wait(50)
        temp = str(pipe / (Path(env.a).stem + spec.pipeline_suffix + ".pdf"))
        assert _same(win._viewer.current_path(), temp)
        assert _label(temp) == "A"
        assert win._pipeline_state[id(win._viewer)]["original_path"] == ""
    finally:
        _close_window(win, qtbot, env.tmp)


# -- 4. an output field loads the viewer -------------------------------------


def _open_tool_on(win, qtbot, cls, path: str):
    """Open ``path`` in the viewer, then the tool, which loads it in
    compact mode and pre-fills its output."""
    page, item = _nav_item(win, cls)
    win._load_and_track(path)
    qtbot.wait(50)
    win._on_nav_clicked(item)
    qtbot.wait(50)
    assert page._compact_active
    return page


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_existing_prefilled_output_replaces_the_viewers_pdf(
        env, monkeypatch, qtbot):
    # After I2: the viewer keeps A, the tab keeps A's name and the
    # output does not enter the recent files.
    out = SPECS["rotate"].out(env.a)
    _write_original(out)
    win = _window(monkeypatch, env.tmp)
    try:
        rotate = _open_tool_on(win, qtbot, TabRotar, env.a)
        assert _same(rotate.drop_in.path(), env.a)
        assert _same(rotate.drop_out.path(), out)
        assert win._tab_bar.count() == 1
        assert _same(win._viewer.current_path(), out)
        assert _label(win._viewer.current_path()) == "ORIGINAL"
        assert win._tab_bar.tabText(0) == Path(out).name
        assert [Path(p).name for p in _recents(env.tmp)] == \
            [Path(out).name, Path(env.a).name]
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_missing_prefilled_output_renames_tab_and_enters_recents(
        env, monkeypatch, qtbot):
    # After I2: the tab keeps A's name and the recent files hold A only.
    out = SPECS["rotate"].out(env.a)
    win = _window(monkeypatch, env.tmp)
    try:
        _open_tool_on(win, qtbot, TabRotar, env.a)
        assert not os.path.exists(out)
        assert _same(win._viewer.current_path(), env.a)
        assert win._tab_bar.tabText(0) == Path(out).name
        assert [Path(p).name for p in _recents(env.tmp)] == \
            [Path(out).name, Path(env.a).name]
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_existing_encrypted_output_asks_password_and_empties_tab(
        env, monkeypatch, qtbot):
    # After I2: no password prompt, and the viewer keeps A.
    out = SPECS["encrypt"].out(env.a)
    _make_pdf(Path(out), "ENCRYPTED", 1, user_pw=secrets.token_hex(8))
    win = _window(monkeypatch, env.tmp)
    try:
        encrypt = _open_tool_on(win, qtbot, TabEncriptar, env.a)
        assert _same(encrypt.drop_out.path(), out)
        # The viewer's own password dialog, cancelled by the stub.
        assert [(name, details[0]) for name, details in env.modals] == \
            [("QDialog.exec", "_PdfPasswordDialog")]
        env.modals.clear()  # expected here; teardown fails on any other
        assert win._viewer.current_path() == ""
        assert win._viewer._pymupdf_doc is None
        assert win._tab_bar.tabText(0) == Path(out).name
        assert [Path(p).name for p in _recents(env.tmp)] == \
            [Path(out).name, Path(env.a).name]
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_existing_txt_output_warns_invalid_format(
        env, monkeypatch, qtbot):
    # After I2: no warning, the tab keeps A's name, the recents hold A.
    out = SPECS["convert_txt"].out(env.a)
    _write_original(out)
    win = _window(monkeypatch, env.tmp)
    try:
        page, _item = _nav_item(win, TabConverter)
        _convert_txt(page, env)
        _open_tool_on(win, qtbot, TabConverter, env.a)
        assert _same(page._drop_file.path(), out)
        assert env.warnings == [(t("viewer.invalid_format"),
                                 t("viewer.invalid_msg"))]
        assert _same(win._viewer.current_path(), env.a)
        assert win._tab_bar.tabText(0) == Path(out).name
        assert [Path(p).name for p in _recents(env.tmp)] == \
            [Path(out).name, Path(env.a).name]
        assert _label(out) == "ORIGINAL"
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_drop_on_tool_in_normal_mode_puts_missing_output_in_recents(
        env, monkeypatch, qtbot):
    # After I2: the recent files hold A only. Dropping A on the input
    # field loads A into the viewer, which is wanted and stays.
    out = SPECS["rotate"].out(env.a)
    win = _window(monkeypatch, env.tmp)
    try:
        rotate, item = _nav_item(win, TabRotar)
        win._on_nav_clicked(item)  # no PDF in the viewer: normal mode
        assert not rotate._compact_active
        rotate.drop_in.set_path(env.a)  # what dropEvent calls
        qtbot.wait(50)
        assert _same(rotate.drop_out.path(), out)
        assert not os.path.exists(out)
        assert _same(win._viewer.current_path(), env.a)
        assert win._tab_bar.tabText(0) == Path(env.a).name
        assert [Path(p).name for p in _recents(env.tmp)] == \
            [Path(env.a).name, Path(out).name]
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.parametrize("spec", _params(_MAIN_INPUT))
def test_window_drop_on_main_input_loads_the_viewer(
        env, spec, monkeypatch, qtbot):
    """A PDF dropped on a tool's main input, in normal mode, opens in the
    viewer, names the tab and enters the recent files: wanted, and kept
    by I2. Only the main input stays wired (``drop_in``, the editor's
    ``_drop_in``): the document the tool works on is the one the viewer
    shows. Watermark's mark and the editor's image are inputs too, but
    not the document, and stop loading the viewer with every output (the
    tests below)."""
    win = _window(monkeypatch, env.tmp)
    try:
        page, item = _nav_item(win, spec.cls)
        env.prepare(page, spec)
        win._on_nav_clicked(item)  # no PDF in the viewer: normal mode
        assert win._viewer.current_path() == ""
        _drop_on(getattr(page, spec.in_attr), env.a)
        qtbot.wait(50)
        assert _same(_in(page, spec), env.a)
        assert _same(win._viewer.current_path(), env.a)
        assert _label(win._viewer.current_path()) == "A"
        assert win._tab_bar.count() == 1
        assert win._tab_bar.tabText(0) == Path(env.a).name
        assert _same(_recents(env.tmp)[0], env.a)
    finally:
        _close_window(win, qtbot, env.tmp)


def test_window_drop_on_main_input_loads_the_current_tab(
        env, monkeypatch, qtbot):
    """The main input loads the tab current when the drop happens, not
    the tab that was current when the window was built, and not a new
    tab. Replacing that tab's document instead of opening another is
    what the code does today; I2 keeps the wiring and this result."""
    folder_c = env.tmp / "pasta C õ"
    folder_c.mkdir()
    c = _make_pdf(folder_c / "charlie õ.pdf", "CHARLIE", 2)
    win = _window(monkeypatch, env.tmp)
    try:
        rotate, item = _nav_item(win, TabRotar)
        win._on_nav_clicked(item)  # no PDF in the viewer: normal mode
        assert not rotate._compact_active
        win._load_and_track(env.a)
        qtbot.wait(50)
        win._load_and_track(env.b)
        qtbot.wait(50)
        assert win._tab_bar.count() == 2
        assert win._viewer is win._viewers[1]

        _drop_on(rotate.drop_in, c)
        qtbot.wait(50)
        assert win._tab_bar.count() == 2
        assert win._viewer is win._viewers[1]
        assert _same(win._viewers[0].current_path(), env.a)
        assert _same(win._viewers[1].current_path(), c)
        assert win._tab_bar.tabText(0) == Path(env.a).name
        assert win._tab_bar.tabText(1) == Path(c).name
    finally:
        _close_window(win, qtbot, env.tmp)


# Every DropFileEdit that is not a tool's main input: (tool, attribute).
_OTHER_FIELDS = (
    (TabComprimir, "drop_out"),
    (TabConverter, "_drop_file"),
    (TabConverter, "_drop_folder"),
    (TabEditar, "_drop_out"),
    (TabEditar, "_img_drop"),
    (TabEncriptar, "drop_out"),
    (TabExtrair, "drop_out"),
    (TabImport, "drop_out"),
    (TabJuntar, "drop_out"),
    (TabMarcaDagua, "drop_out"),
    (TabMarcaDagua, "drop_wm"),
    (TabNUp, "drop_out"),
    (TabOCR, "drop_out"),
    (TabPageNumbers, "drop_out"),
    (TabReordenar, "drop_out"),
    (TabRotar, "drop_out"),
    (TabDividir, "drop_out"),
)


def test_window_field_table_lists_every_field(env, monkeypatch, qtbot):
    """``_OTHER_FIELDS`` plus the main inputs are every ``DropFileEdit``
    of every tool, so a new field cannot escape the per-field test
    below."""
    from app.widgets import DropFileEdit
    from app.window import NAV_ITEMS

    win = _window(monkeypatch, env.tmp)
    try:
        expected = [(SPECS[i].cls, SPECS[i].in_attr) for i in _MAIN_INPUT]
        expected += _OTHER_FIELDS
        listed = {id(getattr(_nav_item(win, cls)[0], attr))
                  for cls, attr in expected}
        assert len(listed) == len(expected)
        found = []
        for index in range(len(NAV_ITEMS)):
            found += win.stack.widget(index).findChildren(DropFileEdit)
        assert [f for f in found if id(f) not in listed] == []
        assert len(found) == len(expected)
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
@pytest.mark.parametrize(
    ("cls", "attr"), _OTHER_FIELDS,
    ids=[f"{cls.__name__}-{attr}" for cls, attr in _OTHER_FIELDS])
def test_window_field_loads_the_viewer(env, cls, attr, monkeypatch, qtbot):
    # After I2 every case fails: the viewer and the tab keep A and the
    # recent files hold A only. One case still passing after that change
    # names a field left wired. The stimulus is the same for every field
    # (a PDF, set as a pick or a drop would); the tool need not be open.
    other = _make_pdf(env.tmp / "outro ç.pdf", "OUTRO", 1)
    win = _window(monkeypatch, env.tmp)
    try:
        page, _item = _nav_item(win, cls)
        win._load_and_track(env.a)
        qtbot.wait(50)
        getattr(page, attr).set_path(other)
        qtbot.wait(50)
        assert win._tab_bar.count() == 1
        assert _same(win._viewer.current_path(), other)
        assert win._tab_bar.tabText(0) == Path(other).name
        _assert_recents(env.tmp, [other, env.a])
    finally:
        _close_window(win, qtbot, env.tmp)


def _rotate_open_on_existing_output(env, monkeypatch, qtbot):
    # One effect per test below: a change that removes only some of them
    # (the output still loads the viewer, only untracked) changes the
    # result of those tests and leaves the others passing.
    out = SPECS["rotate"].out(env.a)
    _write_original(out)
    win = _window(monkeypatch, env.tmp)
    try:
        _open_tool_on(win, qtbot, TabRotar, env.a)
    except BaseException:
        _close_window(win, qtbot, env.tmp)
        raise
    return win, out


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_rotate_output_effect_viewer_shows_it(
        env, monkeypatch, qtbot):
    # After I2: the viewer keeps A.
    win, out = _rotate_open_on_existing_output(env, monkeypatch, qtbot)
    try:
        assert _same(win._viewer.current_path(), out)
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_rotate_output_effect_tab_takes_its_name(
        env, monkeypatch, qtbot):
    # After I2: the tab keeps A's name.
    win, out = _rotate_open_on_existing_output(env, monkeypatch, qtbot)
    try:
        assert win._tab_bar.tabText(0) == Path(out).name
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_rotate_output_effect_enters_recents(
        env, monkeypatch, qtbot):
    # After I2: the recent files hold A only.
    win, out = _rotate_open_on_existing_output(env, monkeypatch, qtbot)
    try:
        _assert_recents(env.tmp, [out, env.a])
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_editor_prefilled_output_renames_tab_and_enters_recents(
        env, monkeypatch, qtbot):
    # After I2: the tab keeps A's name and the recent files hold A only.
    # The editor pre-fills "<A>_edited.pdf" when it loads the viewer's
    # PDF; the viewer behind it stays on A, that output not existing.
    out = SPECS["editor"].out(env.a)
    win = _window(monkeypatch, env.tmp)
    try:
        editor, item = _nav_item(win, TabEditar)
        win._load_and_track(env.a)
        qtbot.wait(50)
        win._on_nav_clicked(item)
        qtbot.wait(50)
        assert _same(editor._doc_path, env.a)
        assert _same(editor._drop_out.path(), out)
        assert not os.path.exists(out)
        assert _same(win._viewer.current_path(), env.a)
        assert win._tab_bar.tabText(0) == Path(out).name
        _assert_recents(env.tmp, [out, env.a])
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_merge_save_dialog_output_names_the_empty_tab(
        env, monkeypatch, qtbot):
    # After I2: the empty tab keeps its placeholder title and the recent
    # files stay empty. The Save dialog's answer reaches the field before
    # the file exists, so the viewer has nothing to show.
    chosen = str(env.tmp / "merged out.pdf")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (chosen, "")))
    win = _window(monkeypatch, env.tmp)
    try:
        page, item = _nav_item(win, TabJuntar)
        win._on_nav_clicked(item)
        assert win._tab_bar.tabText(0) == t("viewer.title")
        page._on_drop([env.a, env.b])
        page._run()
        qtbot.wait(50)
        assert _label(chosen) == "A+B"
        assert len(env.infos) == 1
        assert win._viewer.current_path() == ""
        assert win._tab_bar.tabText(0) == Path(chosen).name
        _assert_recents(env.tmp, [chosen])
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_pipeline_result_renames_tab_after_its_prefilled_output(
        env, monkeypatch, qtbot):
    # After I2: after the run the tab reads "● <A's name>" (the unsaved
    # mark _on_pipeline_done sets) and the recent files hold A only. The
    # output reloaded here sits in the temp folder, which is I5's.
    spec = SPECS["rotate"]
    win = _window(monkeypatch, env.tmp)
    try:
        rotate = _open_tool_on(win, qtbot, TabRotar, env.a)
        # The run's own effect only: the pre-fill on opening the tool is
        # pinned by
        # test_window_missing_prefilled_output_renames_tab_and_enters_recents.
        recents_before = _recents(env.tmp)
        pipe = env.tmp / "pipeline"
        pipe.mkdir()
        rotate._pipeline_tmp_dir = str(pipe)
        _run(rotate, spec, env)
        qtbot.wait(50)
        temp = str(pipe / (Path(env.a).stem + spec.pipeline_suffix + ".pdf"))
        assert _same(win._viewer.current_path(), temp)
        assert _label(temp) == "A"
        # _on_pipeline_done marks the tab "● alfa ç.pdf", then hands the
        # result to auto_load, whose pre-fill loads the viewer.
        reloaded_out = spec.out(temp)
        assert _same(rotate.drop_in.path(), temp)
        assert _same(rotate.drop_out.path(), reloaded_out)
        assert not os.path.exists(reloaded_out)
        assert win._tab_bar.tabText(0) == Path(reloaded_out).name
        _assert_recents(env.tmp, [reloaded_out, *recents_before])
        assert env.infos == []
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_watermark_pick_replaces_the_viewers_pdf(
        env, monkeypatch, qtbot):
    # After I2: the viewer, its tab and the recent files keep A, and the
    # pipeline's Save suggests "<A>_edited.pdf" next to A.
    spec = SPECS["watermark"]
    win = _window(monkeypatch, env.tmp)
    try:
        page = _open_tool_on(win, qtbot, TabMarcaDagua, env.a)
        env.prepare(page, spec)
        assert _same(page.drop_in.path(), env.a)
        _set_watermark(page, env)
        qtbot.wait(50)
        assert win._tab_bar.count() == 1
        assert _same(win._viewer.current_path(), env.wm)
        assert win._tab_bar.tabText(0) == Path(env.wm).name
        assert _same(_recents(env.tmp)[0], env.wm)

        pipe = env.tmp / "pipeline"
        pipe.mkdir()
        page._pipeline_tmp_dir = str(pipe)
        page._run()  # on A, stamped with the mark
        qtbot.wait(50)
        temp = win._viewer.current_path()
        assert Path(temp).name == \
            Path(env.a).stem + spec.pipeline_suffix + ".pdf"
        assert _label(temp) == "A"
        state = win._pipeline_state[id(win._viewer)]
        assert _same(state["original_path"], env.wm)

        suggested = []

        def _save(parent, caption="", directory="", *a, **k):
            suggested.append(directory)
            return "", ""  # cancelled: nothing saved
        monkeypatch.setattr(QFileDialog, "getSaveFileName",
                            staticmethod(_save))
        win._save_pipeline()
        assert len(suggested) == 1
        assert _same(suggested[0], os.path.join(
            os.path.dirname(env.wm), Path(env.wm).stem + "_edited.pdf"))
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_split_prefilled_folder_renames_tab_and_enters_recents(
        env, monkeypatch, qtbot):
    # After I2: the tab keeps A's name and the recent files hold A only.
    # Unwiring keyed on the save flag misses this field: Split's output is
    # a folder field, not a save one.
    from app.i18n import get_recent_files

    folder = os.path.dirname(env.a)
    win = _window(monkeypatch, env.tmp)
    try:
        split = _open_tool_on(win, qtbot, TabDividir, env.a)
        assert not split.drop_out._save
        assert _same(split.drop_out.path(), folder)
        assert _same(win._viewer.current_path(), env.a)
        assert win._tab_bar.tabText(0) == Path(folder).name
        _assert_recents(env.tmp, [folder, env.a])
        # The folder exists, so the lexists filter keeps it.
        got = get_recent_files()
        assert len(got) == 2 and _same(got[0], folder), got
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_import_prefilled_output_names_the_empty_tab(
        env, monkeypatch, qtbot):
    # After I2: the empty tab keeps its placeholder title and the recent
    # files stay empty.
    src_dir = env.tmp / "texto ç"
    src_dir.mkdir()
    src = src_dir / "texto ç.txt"
    src.write_text("ALFA", encoding="utf-8")
    out = str(src_dir / "texto ç.pdf")
    win = _window(monkeypatch, env.tmp)
    try:
        page, item = _nav_item(win, TabImport)
        win._on_nav_clicked(item)
        assert win._tab_bar.tabText(0) == t("viewer.title")
        _import_pick_files(page, monkeypatch, [str(src)])
        qtbot.wait(50)
        assert _same(page.drop_out.path(), out)
        assert not os.path.exists(out)
        assert win._viewer.current_path() == ""
        assert win._tab_bar.tabText(0) == Path(out).name
        _assert_recents(env.tmp, [out])
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_encrypt_mode_change_renames_tab_and_enters_recents(
        env, monkeypatch, qtbot):
    # After I2: the tab keeps A's name and the recent files hold A only.
    base = os.path.splitext(env.a)[0]
    enc, dec = base + "_enc.pdf", base + "_dec.pdf"
    win = _window(monkeypatch, env.tmp)
    try:
        encrypt = _open_tool_on(win, qtbot, TabEncriptar, env.a)
        assert win._tab_bar.tabText(0) == Path(enc).name
        encrypt.cmb_mode.setCurrentIndex(_DECRYPT)
        qtbot.wait(50)
        assert _same(encrypt.drop_out.path(), dec)
        assert not os.path.exists(dec)
        assert _same(win._viewer.current_path(), env.a)
        assert win._tab_bar.tabText(0) == Path(dec).name
        _assert_recents(env.tmp, [dec, enc, env.a])
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.known_defect(reason=_VIEWER_REASON)
def test_window_editor_image_drop_warns_invalid_format(
        env, monkeypatch, qtbot):
    # After I2: no warning, the tab keeps its name and the image stays
    # out of the recent files, as when the image is picked through the
    # field's button (_pick_image blocks the field's signals).
    img = env.tmp / "imagem ç.png"
    pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4), False).save(
        str(img))
    win = _window(monkeypatch, env.tmp)
    try:
        editor, item = _nav_item(win, TabEditar)
        win._load_and_track(env.a)
        qtbot.wait(50)
        win._on_nav_clicked(item)
        qtbot.wait(50)
        assert _same(editor._doc_path, env.a)
        # Only what the drop changes is asserted: the editor's own
        # pre-fill of "<A>_edited.pdf" before it is the output's
        # defect, pinned by
        # test_window_editor_prefilled_output_renames_tab_and_enters_recents.
        recents_before = _recents(env.tmp)
        assert win._tab_bar.tabText(0) != img.name
        _drop_on(editor._img_drop, str(img))
        qtbot.wait(50)
        assert _same(editor._img_drop.path(), str(img))
        assert env.warnings == [(t("viewer.invalid_format"),
                                 t("viewer.invalid_msg"))]
        assert _same(win._viewer.current_path(), env.a)
        assert win._tab_bar.tabText(0) == img.name
        _assert_recents(env.tmp, [str(img), *recents_before])
    finally:
        _close_window(win, qtbot, env.tmp)


# -- 5. the editor's edits on reopen -----------------------------------------


@pytest.mark.known_defect(reason=_PENDING_LOST_REASON)
def test_editor_pending_edit_is_lost_on_reopen(env, monkeypatch, qtbot):
    # After I4: the edit survives closing and reopening the editor on the
    # same PDF.
    spec = SPECS["editor"]
    win = _window(monkeypatch, env.tmp)
    try:
        editor, item = _nav_item(win, TabEditar)
        win._load_and_track(env.a)
        qtbot.wait(50)
        win._on_nav_clicked(item)
        qtbot.wait(50)
        assert _same(editor._doc_path, env.a)
        _add_note(editor, env)
        assert len(editor._pending) == 1
        assert len(editor._user_pending) == 1

        win._on_nav_clicked(item)  # close the editor
        win._on_nav_clicked(item)  # and open it again, on the same PDF
        qtbot.wait(50)
        assert win.stack.currentWidget() is editor
        assert _same(editor._doc_path, env.a)
        assert _same(_in(editor, spec), env.a)
        assert editor._pending == []
        assert editor._user_pending == []
        assert env.modals == []
    finally:
        _close_window(win, qtbot, env.tmp)


def test_window_second_pdf_keeps_the_editors_pending_edit(
        env, monkeypatch, qtbot):
    """Opening a second PDF with the editor open must not lose its edits
    in silence. Today nothing reaches the editor, so they survive by
    accident: a sync on the load or on the tab change would reload it, and
    reloading clears them. I3 has to decide what to do here (ask, keep the
    editor where it is, or something else), without losing the work."""
    win = _window(monkeypatch, env.tmp)
    try:
        editor, item = _nav_item(win, TabEditar)
        win._load_and_track(env.a)
        qtbot.wait(50)
        win._on_nav_clicked(item)
        qtbot.wait(50)
        assert _same(editor._doc_path, env.a)
        _add_note(editor, env)
        assert len(editor._user_pending) == 1

        win._load_and_track(env.b)
        qtbot.wait(50)
        assert win._tab_bar.count() == 2
        assert _same(win._viewer.current_path(), env.b)
        assert len(editor._user_pending) == 1
        assert env.modals == []
        assert _same(editor._doc_path, env.a)
    finally:
        # A pending edit would make closeEvent ask about unsaved edits.
        win.stack.widget(win._edit_tool_idx())._pending.clear()
        _close_window(win, qtbot, env.tmp)


# -- 6. a tool's output in the pipeline's temp folder ------------------------


@pytest.mark.known_defect(reason=_TEMP_OUTPUT_REASON)
@pytest.mark.parametrize("spec", _params(["split", "ocr", "convert_txt"]))
def test_tool_output_points_into_the_pipeline_temp_folder(
        env, spec, monkeypatch, qtbot):
    # After I5: the output is outside the temp folder, and the result
    # outlives the pipeline's cleanup.
    win = _window(monkeypatch, env.tmp)
    try:
        rotate = _open_tool_on(win, qtbot, TabRotar, env.a)
        pipe = env.tmp / "pipeline"
        pipe.mkdir()
        rotate._pipeline_tmp_dir = str(pipe)
        _run(rotate, SPECS["rotate"], env)
        qtbot.wait(50)
        temp = win._viewer.current_path()
        assert _same(os.path.dirname(temp), str(pipe))

        page, item = _nav_item(win, spec.cls)
        env.prepare(page, spec)
        win._on_nav_clicked(item)
        qtbot.wait(50)
        assert _same(_in(page, spec), temp)
        out = spec.out(temp)
        assert _same(_out(page, spec), out)
        target = spec.produced(out)
        assert _same(os.path.dirname(target), str(pipe))

        _run(page, spec, env)
        qtbot.wait(50)
        assert _label(target) == "A"
        assert len(env.infos) == 1
        win._cleanup_pipeline(id(win._viewer))
        assert not os.path.exists(target)
    finally:
        _close_window(win, qtbot, env.tmp)


# -- 7. the fail-closed modals: menus ----------------------------------------


@pytest.mark.parametrize("spelling", ["exec()", "exec(pos)",
                                      "QMenu.exec(actions, pos)"])
def test_fail_closed_modals_close_a_menu(monkeypatch, spelling):
    """Every spelling of a menu reaches the record and returns no action
    at once. The class patch the helper used before catches only the
    static overload: ``menu.exec(pos)``, the spelling of every context
    menu in the app, stayed open until a timer closed it."""
    record = []
    install_fail_closed_modals(monkeypatch, record)
    parent = QWidget()
    menu = QMenu("menu ç", parent)
    menu.addAction(QAction("x", menu))
    escaped = []

    def _close_open_menus():
        # A menu the helper missed: close it so the test fails instead
        # of hanging.
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QMenu) and w.isVisible():
                escaped.append(w.title())
                w.close()
    safety = QTimer(parent)
    safety.setSingleShot(True)
    safety.timeout.connect(_close_open_menus)
    safety.start(2000)
    try:
        if spelling == "exec()":
            chosen = menu.exec()
        elif spelling == "exec(pos)":
            chosen = menu.exec(QPoint(5, 5))
        else:
            chosen = QMenu.exec(menu.actions(), QPoint(5, 5))
        safety.stop()
        assert escaped == []
        assert chosen is None
        title = "" if spelling.startswith("QMenu.") else "menu ç"
        assert record == [("QMenu.exec", ("QMenu", title, ""))]
    finally:
        safety.stop()
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_fail_closed_modals_menu_closer_leaves_the_event_filter():
    """Disarmed, the closer is out of the application's event filters:
    no test after the arming one pays for a Python call on every event."""
    calls = []

    class _Counting(_MenuCloser):
        def eventFilter(self, obj, event):
            calls.append(event.type())
            return super().eventFilter(obj, event)

    closer = _Counting()
    probe = QObject()
    closer.record = []
    QApplication.sendEvent(probe, QEvent(QEvent.Type.User))
    assert QEvent.Type.User in calls
    closer.record = None
    calls.clear()
    QApplication.sendEvent(probe, QEvent(QEvent.Type.User))
    assert calls == []


def test_fail_closed_modals_menu_closer_goes_with_the_monkeypatch():
    """Once the monkeypatch is undone, a menu shows as it would without
    the helper: the closer is disarmed and records nothing."""
    record = []
    with pytest.MonkeyPatch.context() as mp:
        install_fail_closed_modals(mp, record)
    menu = QMenu()
    menu.addAction(QAction("x", menu))
    try:
        menu.popup(QPoint(5, 5))
        QApplication.processEvents()
        assert menu.isVisible()
        assert record == []
    finally:
        menu.close()
        menu.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
