"""Characterisation tests for the watermark tool (``TabMarcaDagua``).

Increment I0 of the watermark redesign: pin what the tool does *today*,
through its real code path, before any of it changes. Every test builds
its PDFs in ``tmp_path``, fills the page's widgets, and calls
``TabMarcaDagua._run``. The pre-flight, the ``do_work`` closure and the
atomic write run for real; only the parts that would block an offscreen
run or leave the test thread are replaced (see the ``run_tool``
fixture):

* ``_run_background`` runs ``do_work`` inline on the test thread;
* ``QMessageBox.warning`` / ``QMessageBox.information`` and the tool's
  ``show_error`` are recorded instead of shown;
* the other modals the tool's code could reach fail closed: the
  ``QMessageBox`` statics ``question`` / ``critical`` / ``about``, the
  ``QFileDialog`` statics ``getSaveFileName`` / ``getOpenFileName`` /
  ``getOpenFileNames`` / ``getExistingDirectory``, the ``QInputDialog``
  statics ``getText`` / ``getMultiLineText`` / ``getItem`` / ``getInt``
  / ``getDouble``, ``QColorDialog.getColor``, ``QFontDialog.getFont``,
  and ``QDialog.exec`` (which instances of every ``QDialog`` subclass
  in ``QtWidgets`` inherit) are recorded as unexpected and answered as
  a cancel, and the test fails;
* a top-level window visible when ``_run`` returns that was not
  visible before the source was loaded (one shown with ``show()``
  rather than ``exec()``, a new tooltip window) fails the test;
* ``app.utils.prompt_pdf_password`` is a fail-closed stub that answers
  for each path and never opens the password dialog; a contract test
  ties its "no dialog" branches to the real function's.

Outside ``run_tool``, one test replaces ``_prompt_save_as`` (the Save
dialog, above the ``QFileDialog`` stand-ins), the contract test replaces
``app.editor.dialogs._PdfPasswordDialog`` and, as a safety net,
``QDialog.exec``, and the layer-label tests switch language by patching
``app.i18n._LANG``. An autouse fixture fails any test that leaves
``app.i18n._LANG`` changed.

Placement and layering are asserted on a render of the output (MuPDF,
not pypdf), never on page counts. The watermark is a solid red
rectangle and the source pages carry only vector fills and a flat grey
image, so no assertion depends on system fonts or anti-aliased text.

Tests marked ``known_defect`` fix behaviour the redesign changes on
purpose (absolute placement, document structure loss (outline, title,
page labels, AcroForm, attachments), "Below" as the default, the silent
use of page 1 of a multi-page watermark, the untrimmed Chinese layer
label). They pass today and are expected to be rewritten, deliberately,
with the fix their reason names.

A few tests pin behaviour whose policy the user has not decided yet
(output encryption, the two default output names). They carry no
``known_defect`` marker because nobody has called them defects; each
says so in a comment.
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton, QApplication, QColorDialog, QComboBox, QDialog,
    QFileDialog, QFontDialog, QGroupBox, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QWidget,
)

_unused_app = QApplication.instance() or QApplication([])

import pymupdf  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from _inline_background import FakeWorker, run_background_inline  # noqa: E402
from app.i18n import available_languages, get_language, t  # noqa: E402
from app.tools.watermark import TabMarcaDagua  # noqa: E402


def _known_defect(reason: str):
    return pytest.mark.known_defect(reason)


@pytest.fixture(autouse=True)
def _language_is_not_leaked():
    # Deliberately does not request monkeypatch: being autouse it is set
    # up first and torn down last, so a monkeypatched _LANG is already
    # restored when this checks. A plain assignment is not, and would
    # silently run every later test in another language. The leak is
    # undone before failing so only the offending test errors;
    # sys.modules avoids a second import style for app.i18n (CodeQL
    # py/import-and-import-from).
    before = get_language()
    yield
    after = get_language()
    sys.modules["app.i18n"]._LANG = before
    assert after == before, (
        "the test left app.i18n._LANG at %r (was %r); switch it with "
        "monkeypatch.setattr so teardown restores it" % (after, before))


# -- geometry (PDF points; PyMuPDF top-left origin) --------------------------

A4 = (595, 842)
A4_LANDSCAPE = (842, 595)
A5 = (420, 595)

RED = (1, 0, 0)
GREEN = (0, 1, 0)
BLUE = (0, 0, 1)

# Watermark: a 400 x 120 pt solid rectangle centred on an A4 page.
WM_W, WM_H = 400.0, 120.0
WM_RECT = pymupdf.Rect(97.5, 361, 497.5, 481)
WM_AREA = WM_W * WM_H

# Small solid square drawn on every source page, to prove the source
# content survives the merge.
SRC_MARK_RECT = pymupdf.Rect(10, 10, 40, 40)
SRC_MARK_AREA = 30.0 * 30.0

ZOOM = 0.5           # render scale: 1 px == 2 pt
POS_TOL = 3.0        # pt, centroid tolerance (1.5 px)
EXTENT_TOL = 4.0     # pt, bbox edge tolerance (2 px)
AREA_TOL = 0.05      # relative, pixel-count tolerance


# -- fixture builders --------------------------------------------------------


def _make_watermark(path: Path, colours=(RED,)) -> str:
    """One A4 page per colour, each with ``WM_RECT`` filled in it."""
    doc = pymupdf.open()
    for colour in colours:
        pg = doc.new_page(width=A4[0], height=A4[1])
        pg.draw_rect(WM_RECT, color=None, fill=colour)
    doc.save(str(path))
    doc.close()
    return str(path)


def _opaque_grey_image() -> pymupdf.Pixmap:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
    pix.clear_with(128)
    return pix


def _make_source(path: Path, specs, *, encrypt_pw: str = "") -> str:
    """Build a source PDF, one page per spec dict.

    Spec keys: ``size`` (w, h), ``opaque`` (full-page grey image under
    everything), ``cropbox`` (PyMuPDF rect, unrotated space),
    ``rotate`` (degrees). Every page also gets the green
    ``SRC_MARK_RECT``.
    """
    doc = pymupdf.open()
    for spec in specs:
        w, h = spec.get("size", A4)
        pg = doc.new_page(width=w, height=h)
        if spec.get("opaque"):
            pg.insert_image(pg.rect, pixmap=_opaque_grey_image(),
                            keep_proportion=False)
        pg.draw_rect(SRC_MARK_RECT, color=None, fill=GREEN)
        if spec.get("cropbox") is not None:
            pg.set_cropbox(pymupdf.Rect(*spec["cropbox"]))
        if spec.get("rotate"):
            pg.set_rotation(spec["rotate"])
    if encrypt_pw:
        doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256,
                 owner_pw=encrypt_pw, user_pw=encrypt_pw)
    else:
        doc.save(str(path))
    doc.close()
    return str(path)


def _make_rich_source(path: Path) -> str:
    """Two A4 pages carrying every piece of document-level structure the
    tool is known to drop: outline, title, page labels, AcroForm and an
    embedded file."""
    doc = pymupdf.open()
    for _ in range(2):
        pg = doc.new_page(width=A4[0], height=A4[1])
        pg.draw_rect(SRC_MARK_RECT, color=None, fill=GREEN)
    doc.set_toc([[1, "Capítulo um", 1], [1, "Capítulo dois", 2]])
    doc.set_metadata({"title": "Relatório anual"})
    doc.set_page_labels([{"startpage": 0, "prefix": "P-", "style": "D",
                          "firstpagenum": 1}])
    widget = pymupdf.Widget()
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "nome"
    widget.field_value = "abc"
    widget.rect = pymupdf.Rect(50, 700, 250, 730)
    doc[0].add_widget(widget)
    doc.embfile_add("nota.txt", b"anexo de teste", filename="nota.txt")
    doc.save(str(path))
    doc.close()
    return str(path)


# -- render probe ------------------------------------------------------------


def _is_red(r, g, b):
    return r >= 200 and g <= 80 and b <= 80


def _is_green(r, g, b):
    return g >= 200 and r <= 80 and b <= 80


def _is_blue(r, g, b):
    return b >= 200 and r <= 80 and g <= 80


def _colour_stats(pdf_path: str, index: int, predicate) -> SimpleNamespace:
    """Render page ``index`` as MuPDF displays it (rotation and CropBox
    applied) and locate the pixels matching ``predicate``.

    Returns ``area`` in square points, the centroid ``cx``/``cy`` and
    the bounding box ``x0``/``y0``/``x1``/``y1``, all in points of the
    displayed page, plus that page's ``width``/``height``.
    """
    doc = pymupdf.open(pdf_path)
    try:
        pg = doc[index]
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), alpha=False)
        width, height = pg.rect.width, pg.rect.height
        samples, stride, w, h = pix.samples, pix.stride, pix.width, pix.height
    finally:
        doc.close()
    count = 0
    sx = sy = 0
    x0 = y0 = 10 ** 9
    x1 = y1 = -1
    for y in range(h):
        row = samples[y * stride: y * stride + w * 3]
        for x, (r, g, b) in enumerate(zip(row[0::3], row[1::3], row[2::3])):
            if predicate(r, g, b):
                count += 1
                sx += x
                sy += y
                if x < x0:
                    x0 = x
                if x > x1:
                    x1 = x
                if y < y0:
                    y0 = y
                if y > y1:
                    y1 = y
    px = 1.0 / ZOOM
    if not count:
        return SimpleNamespace(area=0.0, cx=None, cy=None, x0=None, y0=None,
                               x1=None, y1=None, width=width, height=height)
    return SimpleNamespace(
        area=count * px * px,
        cx=(sx / count + 0.5) * px, cy=(sy / count + 0.5) * px,
        x0=x0 * px, y0=y0 * px, x1=(x1 + 1) * px, y1=(y1 + 1) * px,
        width=width, height=height,
    )


def _red(pdf_path, index):
    return _colour_stats(pdf_path, index, _is_red)


# -- driver ------------------------------------------------------------------


def _needs_password(path: str) -> bool:
    """The prompt stub's "would the real prompt open a dialog?" test.

    Kept in step with the real ``prompt_pdf_password`` by
    ``test_prompt_stand_in_matches_the_real_prompt_pdf_password``.
    """
    try:
        doc = pymupdf.open(path)
    except Exception:
        # The real prompt_pdf_password answers (True, "") here too and
        # leaves the error to the caller's own open.
        return False
    try:
        return bool(doc.needs_pass)
    finally:
        doc.close()


def _widget_text(w) -> str:
    if isinstance(w, (QLabel, QAbstractButton, QLineEdit)):
        return w.text()
    if isinstance(w, QComboBox):
        return w.currentText()
    if isinstance(w, QGroupBox):
        return w.title()
    return ""


def _widget_census(page) -> list:
    """``page`` and every widget under it, as sorted (type, objectName,
    text, tooltip, hidden, enabled) tuples. Comparing two censuses
    catches a toast or a new label added to the page, and a changed
    text, tooltip, visibility or enabled state of the page or of a
    widget in it. "Text" is what ``_widget_text`` reads, empty for
    every other widget type. Nothing else is read (no icon, pixmap,
    placeholder, style sheet, property, combo item or window title)."""
    return sorted((type(w).__name__, w.objectName(), _widget_text(w),
                   w.toolTip(), w.isHidden(), w.isEnabled())
                  for w in [page] + page.findChildren(QWidget))


def _census_diff(before, after) -> str:
    added = Counter(after) - Counter(before)
    removed = Counter(before) - Counter(after)
    return "widgets added: %r; removed: %r" % (
        sorted(added.elements()), sorted(removed.elements()))


def _visible_top_levels() -> list:
    return [w for w in QApplication.topLevelWidgets() if w.isVisible()]


# Modals the tool has no business opening in these runs, each with the
# reply the real one gives when the user cancels it, measured offscreen
# with PySide6 6.11.2: Escape for the QMessageBox statics, reject() for
# the rest. question gets No, which Escape answers on its default
# Yes|No buttons (with a Cancel button it would answer Cancel), and
# critical gets Ok, the only default button. getItem, getInt, getDouble
# and getFont really hand back the current item, the value and the
# initial font they were given, which a fixed answer cannot: getInt,
# getDouble and getFont answer what they return for their default
# arguments, getItem what it returns for an out-of-range current. The
# ok flag, which callers branch on, is False in every case that has
# one: the QInputDialog statics and getFont. Instances
# of every QDialog subclass in QtWidgets inherit exec from QDialog, so
# one stand-in covers them; QPrintDialog and QPageSetupDialog (in
# QtPrintSupport) define their own exec and are not covered.
_FAIL_CLOSED_MODALS: tuple[tuple[type, str, object], ...] = (
    (QMessageBox, "question", QMessageBox.StandardButton.No),
    (QMessageBox, "critical", QMessageBox.StandardButton.Ok),
    (QMessageBox, "about", None),
    (QFileDialog, "getSaveFileName", ("", "")),
    (QFileDialog, "getOpenFileName", ("", "")),
    (QFileDialog, "getOpenFileNames", ([], "")),
    (QFileDialog, "getExistingDirectory", ""),
    (QInputDialog, "getText", ("", False)),
    (QInputDialog, "getMultiLineText", ("", False)),
    (QInputDialog, "getItem", ("", False)),
    (QInputDialog, "getInt", (0, False)),
    (QInputDialog, "getDouble", (0.0, False)),
    (QColorDialog, "getColor", QColor()),
    (QFontDialog, "getFont", (False, QFont())),
    (QDialog, "exec", QDialog.DialogCode.Rejected),
)


@pytest.fixture
def run_tool(monkeypatch):
    """Drive ``TabMarcaDagua`` the way the UI does, minus every dialog.

    The source goes in through ``drop_in.set_path``, whose
    ``path_changed`` signal runs the real ``_load_input`` (password
    check, default output name). ``QMessageBox.warning``,
    ``QMessageBox.information`` and ``show_error`` are recorded instead
    of shown, and ``_run_background`` runs inline (``rec.box``).

    Every other modal in ``_FAIL_CLOSED_MODALS`` is replaced by a stub
    that records the call in ``rec.unexpected_dialogs`` and answers as
    a cancel, so a code path that reaches one (an empty output field
    falling through to the Save dialog, say) fails the test in
    milliseconds instead of hanging the offscreen run.

    ``app.utils.prompt_pdf_password`` (looked up at call time by both
    ``BasePage._maybe_prompt_password`` and the tool's watermark
    prompt) is replaced by a fail-closed stub that never opens the real
    dialog, which is modal and would hang an offscreen run:

    * a PDF that needs no password gets ``(True, "")``, as from the
      real function's no-dialog branch;
    * the encrypted source gets ``(True, src_password)``;
    * any other path is an unexpected prompt: it is recorded in
      ``rec.unexpected_prompts`` and answered ``(False, "")``, the
      "user cancelled" reply, so the tool stops cleanly.

    ``rec.widgets_before`` / ``rec.widgets_after`` are the page's
    ``_widget_census`` just before and just after ``_run``; both are
    taken after the inputs are loaded, so a change made while loading
    is in both. A test that must see those compares ``widgets_after``
    with that of a reference run instead.

    A top-level window that is visible when ``_run`` returns and was
    not visible before the source was loaded (a parentless
    ``QMessageBox`` shown with ``show()``, a new ``QToolTip`` window)
    fails the test, whether loading or ``_run`` showed it. Windows
    other tests left visible were already visible then, so they are
    not counted. Not caught: a window shown and hidden again before
    ``_run`` returns, and a window that was already visible before
    loading, such as a tooltip window reused for a new text.

    The checks on ``rec.unexpected_prompts`` and
    ``rec.unexpected_dialogs`` are made after ``_run`` returns, never
    inside a stub. ``_load_input`` runs from a signal, and an exception
    raised in a slot does not propagate to the ``emit`` caller, so the
    tool would carry on. With pytest-qt loaded the test still fails, in
    the call phase, with "Exceptions caught in Qt event loop"; with
    ``-p no:pytest-qt`` it passes silently.
    """
    created = []

    def _drive(src, wm, *, out=None, pages=None, layer=None,
               src_password="", worker=None, clear_out=False):
        rec = SimpleNamespace(warnings=[], infos=[], errors=[], statuses=[],
                              prompts=[], unexpected_prompts=[],
                              unexpected_dialogs=[])
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda *a, **k: rec.warnings.append(a)))
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(lambda *a, **k: rec.infos.append(a)))
        monkeypatch.setattr("app.tools.watermark.show_error",
                            lambda *a, **k: rec.errors.append(a))

        def _fail_closed(cls, name, answer):
            def _stub(*a, **k):
                rec.unexpected_dialogs.append(
                    ("%s.%s" % (cls.__name__, name), a[1:3]))
                return answer
            # exec is an instance method; the others are statics.
            return _stub if name == "exec" else staticmethod(_stub)
        for cls, name, answer in _FAIL_CLOSED_MODALS:
            monkeypatch.setattr(cls, name, _fail_closed(cls, name, answer))

        def _prompt(path, parent=None):
            rec.prompts.append(path)
            if not _needs_password(path):
                return True, ""
            if src_password and path == src:
                return True, src_password
            rec.unexpected_prompts.append(path)
            return False, ""
        monkeypatch.setattr("app.utils.prompt_pdf_password", _prompt)

        page = TabMarcaDagua(rec.statuses.append)
        created.append(page)
        rec.page = page
        rec.box = run_background_inline(page, monkeypatch, worker)

        windows_before = _visible_top_levels()
        page.drop_in.set_path(src)
        page.drop_wm.set_path(wm)
        if out is not None:
            page.drop_out.set_path(out)
        if clear_out:
            page.drop_out.clear()
        if pages is not None:
            page.edit_pages.setText(pages)
        if layer is not None:
            page.cmb_layer.setCurrentIndex(layer)

        rec.widgets_before = _widget_census(page)
        page._run()
        new_windows = [w for w in _visible_top_levels()
                       if not any(w is b for b in windows_before)]
        rec.new_windows = [(type(w).__name__, w.windowTitle(),
                            _widget_text(w)) for w in new_windows]
        # Hidden before the asserts, so a leaked window does not stay
        # shown for the rest of the session.
        for w in new_windows:
            w.hide()
        rec.widgets_after = _widget_census(page)
        rec.out = page.drop_out.path()
        assert not rec.unexpected_prompts, (
            "%d unexpected password prompt(s), answered as cancelled: %r"
            % (len(rec.unexpected_prompts), rec.unexpected_prompts))
        assert not rec.unexpected_dialogs, (
            "%d unexpected modal(s), answered as cancelled: %r"
            % (len(rec.unexpected_dialogs), rec.unexpected_dialogs))
        assert not rec.new_windows, (
            "_run left new visible windows: %r" % (rec.new_windows,))
        return rec

    yield _drive
    for page in created:
        page.deleteLater()


def _assert_clean_run(rec):
    assert not rec.errors, "show_error was called: %r" % (rec.errors,)
    assert not rec.warnings, "a warning was shown: %r" % (rec.warnings,)
    assert "error" not in rec.box, "do_work raised: %r" % (
        rec.box.get("error"),)
    assert rec.box.get("result") == rec.out
    assert os.path.isfile(rec.out)


def _assert_mark_at(stats, cx, cy, w, h, area, what):
    assert stats.area > 0, "%s: no watermark pixels at all" % what
    assert stats.cx == pytest.approx(cx, abs=POS_TOL), (what, stats)
    assert stats.cy == pytest.approx(cy, abs=POS_TOL), (what, stats)
    assert stats.x1 - stats.x0 == pytest.approx(w, abs=EXTENT_TOL), (
        what, stats)
    assert stats.y1 - stats.y0 == pytest.approx(h, abs=EXTENT_TOL), (
        what, stats)
    assert stats.area == pytest.approx(area, rel=AREA_TOL), (what, stats)


# -- harness contract --------------------------------------------------------


def test_prompt_stand_in_matches_the_real_prompt_pdf_password(
        tmp_path, monkeypatch):
    # run_tool's prompt stub answers (True, "") without a dialog exactly
    # when _needs_password is False. This holds the real function to
    # the same branches, so a change on either side fails here instead
    # of the stub quietly answering for a path the real one would not.
    # prompt_pdf_password imports _PdfPasswordDialog inside the
    # function, after the needs_pass check, so patching the module
    # attribute reaches it at call time.
    from app.utils import prompt_pdf_password

    opened = []

    class _CancellingDialog:
        def __init__(self, name, wrong=False, parent=None):
            opened.append(name)

        def exec(self):
            return QDialog.DialogCode.Rejected

        def password(self):
            return ""

    monkeypatch.setattr("app.editor.dialogs._PdfPasswordDialog",
                        _CancellingDialog)
    # Safety net: should the patch above stop reaching the function,
    # the real modal dialog is recorded here and rejected instead of
    # hanging the offscreen run.
    real_execs = []
    monkeypatch.setattr(QDialog, "exec",
                        lambda self: real_execs.append(type(self).__name__)
                        or QDialog.DialogCode.Rejected)

    plain = _make_source(tmp_path / "plain.pdf", [{}])
    not_pdf = tmp_path / "não é um pdf.pdf"
    not_pdf.write_bytes(b"this is not a PDF\n")
    # Fixture assumption: MuPDF refuses it, so both functions take their
    # "could not open" branch.
    with pytest.raises(pymupdf.FileDataError):
        pymupdf.open(str(not_pdf))
    sealed = _make_source(tmp_path / "sealed.pdf", [{}],
                          encrypt_pw="segredo-ç")

    cases = [(plain, (True, ""), 0), (str(not_pdf), (True, ""), 0),
             (sealed, (False, ""), 1)]
    for path, answer, dialogs in cases:
        opened.clear()
        assert prompt_pdf_password(path) == answer, path
        assert not real_execs, "the real dialog opened: %r" % (real_execs,)
        assert len(opened) == dialogs, (path, opened)
        assert _needs_password(path) == (dialogs > 0), path


# -- pages covered -----------------------------------------------------------


def test_empty_pages_field_marks_every_page_and_keeps_source_content(
        tmp_path, run_tool):
    src = _make_source(tmp_path / "src.pdf", [{}, {}, {}])
    wm = _make_watermark(tmp_path / "wm.pdf")
    out = str(tmp_path / "out.pdf")

    rec = run_tool(src, wm, out=out)

    _assert_clean_run(rec)
    assert len(PdfReader(out).pages) == 3
    for i in range(3):
        _assert_mark_at(_red(out, i), 297.5, 421, WM_W, WM_H, WM_AREA,
                        "page %d" % (i + 1))
        green = _colour_stats(out, i, _is_green)
        assert green.area == pytest.approx(SRC_MARK_AREA, rel=0.15), (
            "page %d lost its own content" % (i + 1))
    # One progress update per page, ending at 100 %.
    assert [e[0] for e in rec.box["worker"].emitted] == [33, 66, 100]
    assert len(rec.infos) == 1, "the done dialog was not shown once"
    assert rec.statuses, "no status message after a successful run"


@pytest.mark.parametrize("pages, marked", [
    ("2-3", {1, 2}),
    ("1, 4-", {0, 3, 4}),
    ("5", {4}),
], ids=["range", "single-and-open-ended", "last-page"])
def test_pages_field_limits_the_mark_to_the_listed_pages(
        tmp_path, run_tool, pages, marked):
    src = _make_source(tmp_path / "src.pdf", [{}] * 5)
    wm = _make_watermark(tmp_path / "wm.pdf")
    out = str(tmp_path / "out.pdf")

    rec = run_tool(src, wm, out=out, pages=pages)

    _assert_clean_run(rec)
    assert len(PdfReader(out).pages) == 5, "pages outside the range dropped"
    for i in range(5):
        red = _red(out, i)
        if i in marked:
            assert red.area == pytest.approx(WM_AREA, rel=AREA_TOL), (
                "page %d should carry the mark" % (i + 1))
        else:
            assert red.area == 0, (
                "page %d is outside %r but got the mark" % (i + 1, pages))


def test_invalid_pages_field_reports_an_error_and_writes_nothing(
        tmp_path, run_tool):
    src = _make_source(tmp_path / "src.pdf", [{}] * 3)
    wm = _make_watermark(tmp_path / "wm.pdf")
    out = str(tmp_path / "out.pdf")

    rec = run_tool(src, wm, out=out, pages="abc")

    assert len(rec.errors) == 1, "a bad page list must surface one error"
    assert rec.box["calls"] == 0, "background work started anyway"
    assert not os.path.exists(out)


# -- layer: above / below ----------------------------------------------------


_LAYER_KEYS = ("tool.watermark.below", "tool.watermark.above")

# Languages whose layer labels open their parenthetical with an ASCII
# "(", which is what the combo trims at today.
_TRIMMED_LABEL_LANGS = ["en", "pt", "es", "fr", "de", "it", "nl"]
# Languages whose labels use the full-width U+FF08, which the trim misses.
_UNTRIMMED_LABEL_LANGS = ["zh"]


def _layer_items(monkeypatch, lang=None):
    """(item text, tooltip) of each layer combo entry, built in ``lang``.

    The language is switched by patching ``app.i18n._LANG``, which
    ``t()`` reads at call time; monkeypatch restores it at teardown, and
    nothing is written to the user's config (``set_language`` would).
    """
    if lang is not None:
        monkeypatch.setattr("app.i18n._LANG", lang)
    page = TabMarcaDagua(lambda *a, **k: None)
    try:
        cmb = page.cmb_layer
        return [(cmb.itemText(i), cmb.itemData(i, Qt.ItemDataRole.ToolTipRole))
                for i in range(cmb.count())]
    finally:
        page.deleteLater()


def test_layer_combo_items_are_below_then_above(monkeypatch):
    # Index 1 is what _run treats as "over"; the labels must agree. The
    # tooltip carries the full translated label, the item text a
    # non-empty leading part of it.
    items = _layer_items(monkeypatch)
    assert len(items) == 2
    for (text, tip), key in zip(items, _LAYER_KEYS):
        assert tip == t(key), key
        assert text and t(key).startswith(text), (key, text)


def test_layer_label_language_cases_cover_every_language():
    # A ninth language must be sorted into one of the lists by hand.
    assert sorted(_TRIMMED_LABEL_LANGS + _UNTRIMMED_LABEL_LANGS) == sorted(
        available_languages()), (
        "each language in translations.json must be in exactly one list: "
        "the combo cuts each layer label at the first ASCII '(', so a "
        "language whose layer labels open their parenthetical with '(' "
        "goes in _TRIMMED_LABEL_LANGS, and one that uses the full-width "
        "U+FF08 instead goes in _UNTRIMMED_LABEL_LANGS; languages: %r"
        % (available_languages(),))


@pytest.mark.parametrize("lang", _TRIMMED_LABEL_LANGS)
def test_layer_combo_shows_a_short_label_and_the_full_one_as_tooltip(
        monkeypatch, lang):
    items = _layer_items(monkeypatch, lang)
    assert len(items) == 2
    for (text, tip), key in zip(items, _LAYER_KEYS):
        full = t(key)
        assert tip == full, (lang, key)
        assert text, (lang, key)
        assert text != full, (lang, key, text)
        assert full.startswith(text), (lang, key, text)
        assert "(" not in text and text == text.strip(), (lang, key, text)


@_known_defect("I6: layer labels trimmed at the full-width parenthesis "
               "too; today the Chinese label is shown whole")
@pytest.mark.parametrize("lang", _UNTRIMMED_LABEL_LANGS)
def test_layer_combo_shows_the_full_chinese_label_untrimmed(
        monkeypatch, lang):
    # Characterises a known defect: the combo trims at the ASCII "(",
    # but the Chinese labels open their parenthetical with the
    # full-width U+FF08, so the whole label is the item text.
    items = _layer_items(monkeypatch, lang)
    assert len(items) == 2
    for (text, tip), key in zip(items, _LAYER_KEYS):
        full = t(key)
        assert "（" in full and "(" not in full, (
            "fixture assumption: %s in %s has a full-width parenthesis"
            % (key, lang))
        assert tip == full, (lang, key)
        assert text == full, (lang, key, text)


def test_above_draws_the_mark_over_a_full_page_opaque_image(
        tmp_path, run_tool):
    src = _make_source(tmp_path / "src.pdf", [{"opaque": True}])
    wm = _make_watermark(tmp_path / "wm.pdf")
    out = str(tmp_path / "out.pdf")

    rec = run_tool(src, wm, out=out, layer=1)

    _assert_clean_run(rec)
    _assert_mark_at(_red(out, 0), 297.5, 421, WM_W, WM_H, WM_AREA, "above")


def test_below_is_hidden_by_a_full_page_opaque_image(tmp_path, run_tool):
    src = _make_source(tmp_path / "src.pdf", [{"opaque": True}])
    wm = _make_watermark(tmp_path / "wm.pdf")
    out = str(tmp_path / "out.pdf")

    rec = run_tool(src, wm, out=out, layer=0)

    _assert_clean_run(rec)
    assert _red(out, 0).area == 0, "the image should cover a mark below it"
    # Hidden, not missing: the red fill is in the page's content.
    doc = pymupdf.open(out)
    try:
        fills = [d.get("fill") for d in doc[0].get_drawings()]
    finally:
        doc.close()
    assert any(f is not None and tuple(round(c, 2) for c in f) == RED
               for f in fills), "the mark was never merged into the page"


@_known_defect("I4: the default layer becomes 'Above'; today a scanned "
               "page silently hides the watermark")
def test_default_layer_is_below_so_an_opaque_page_hides_the_mark(
        tmp_path, run_tool):
    # Characterises a known defect: with the combo left untouched the
    # mark goes below the content, and on a scanned (full-page image)
    # page the user gets an output that looks unchanged.
    src = _make_source(tmp_path / "src.pdf", [{"opaque": True}])
    wm = _make_watermark(tmp_path / "wm.pdf")
    out = str(tmp_path / "out.pdf")

    rec = run_tool(src, wm, out=out)

    assert rec.page.cmb_layer.currentIndex() == 0
    _assert_clean_run(rec)
    assert _red(out, 0).area == 0


# -- position ----------------------------------------------------------------

# Each case: source page spec, then the expected render of a mark that
# was centred on an A4 page, in points of the *displayed* page:
# centroid (cx, cy), bbox width/height, visible area.
_POSITION_CASES = [
    pytest.param(
        {"size": A4}, (297.5, 421.0, WM_W, WM_H, WM_AREA),
        id="a4-centred"),
    # Characterises a known defect: same PDF coordinates, so on a
    # landscape page the mark sits left of centre and high (page centre
    # is 421, 297.5).
    pytest.param(
        {"size": A4_LANDSCAPE}, (297.5, 174.0, WM_W, WM_H, WM_AREA),
        id="a4-landscape-off-centre",
        marks=_known_defect("I4: placement relative to the target page")),
    # Characterises a known defect: A5 is 420 pt wide, so the mark
    # (x 97.5 to 497.5) is cut at the right edge: 322.5 of 400 pt show.
    pytest.param(
        {"size": A5}, (258.75, 174.0, 322.5, WM_H, 322.5 * WM_H),
        id="a5-clipped",
        marks=_known_defect("I4: placement relative to the target page")),
    # Characterises a known defect: /Rotate 90 rotates the merged mark
    # with the page, so a horizontal mark displays vertical.
    pytest.param(
        {"size": A4, "rotate": 90}, (421.0, 297.5, WM_H, WM_W, WM_AREA),
        id="rotate90-vertical",
        marks=_known_defect("I4: placement honours /Rotate")),
    # Characterises a known defect: the mark keeps MediaBox coordinates,
    # so with the CropBox moved 150 pt right it is off-centre in the
    # visible page (445 x 842, centre 222.5, 421) and its left 52.5 pt
    # are cropped away.
    pytest.param(
        {"size": A4, "cropbox": (150, 0, 595, 842)},
        (173.75, 421.0, 347.5, WM_H, 347.5 * WM_H),
        id="cropbox-shifted-off-centre",
        marks=_known_defect("I4: placement relative to the CropBox")),
]


@pytest.mark.parametrize("spec, expected", _POSITION_CASES)
def test_mark_keeps_its_absolute_pdf_position_on_the_target_page(
        tmp_path, run_tool, spec, expected):
    src = _make_source(tmp_path / "src.pdf", [spec])
    wm = _make_watermark(tmp_path / "wm.pdf")
    out = str(tmp_path / "out.pdf")

    rec = run_tool(src, wm, out=out, layer=1)

    _assert_clean_run(rec)
    cx, cy, w, h, area = expected
    _assert_mark_at(_red(out, 0), cx, cy, w, h, area, str(spec))


# -- multi-page watermark ----------------------------------------------------


@_known_defect("I4: a multi-page watermark PDF is no longer used "
               "silently; page 1 is today taken without telling the user")
def test_multi_page_watermark_uses_page_one_without_a_warning(
        tmp_path, run_tool):
    # Characterises a known defect: page 2 of the watermark (blue) is
    # ignored and nothing tells the user. What "nothing" covers here:
    # - modals: no QMessageBox.warning and no show_error
    #   (_assert_clean_run); every modal in _FAIL_CLOSED_MODALS fails
    #   the test inside run_tool; exactly one QMessageBox.information,
    #   the usual done one;
    # - windows: run_tool fails the test if a top-level window that was
    #   not visible before the source was loaded is visible when _run
    #   returns (a parentless QMessageBox shown with show(), a new
    #   QToolTip.showText tooltip window);
    # - the status line: exactly the usual one;
    # - lbl_info: still the source page count;
    # - the census of the page and its widgets, both unchanged by _run
    #   and, at the end, equal to that of a reference run with a
    #   one-page watermark at the same paths, so a notice given while
    #   loading the watermark counts too: catches a toast, a new or
    #   duplicated widget, and a changed tooltip, visibility, enabled
    #   state or text, where text is that of a QLabel, button or
    #   QLineEdit, the QComboBox's current text and the QGroupBox's
    #   title.
    # Not covered:
    # - any widget property other than the census fields (type,
    #   objectName, text, tooltip, visibility, enabled), such as a style
    #   sheet (setStyleSheet), a dynamic property (setProperty), an icon
    #   (setIcon), a pixmap (a QLabel's setPixmap is caught only through
    #   the text it clears, so not on a label that had none), placeholder
    #   text, the combo's item texts, tooltips and data (only its current
    #   text is read) and the page's window title;
    # - the action bar's QProgressBar: its value, range and text are
    #   not read (the census has its type, objectName, tooltip,
    #   visibility and enabled state only);
    # - a window shown and hidden again before _run returns, one shown
    #   only after _run returns (from a timer, say), and one that was
    #   already visible before loading, such as a tooltip window reused
    #   for a new text;
    # - a modal outside _FAIL_CLOSED_MODALS, such as
    #   QMessageBox.aboutQt, the QFileDialog *Url statics, or
    #   QPrintDialog / QPageSetupDialog.exec (their own exec, not
    #   QDialog's): nothing stands in for it, so the run blocks on it
    #   instead of failing;
    # - a modal stand-in left patched by plain assignment in some test
    #   instead of monkeypatch.setattr: nothing restores it or fails
    #   on it, so later tests run against it. Only app.i18n._LANG has a
    #   guard against that (_language_is_not_leaked).
    src = _make_source(tmp_path / "src.pdf", [{}, {}])
    wm_path = tmp_path / "wm.pdf"
    out = str(tmp_path / "out.pdf")

    # Reference: same paths, one-page watermark. Every census text that
    # holds a path (the three file fields) is then the same in both.
    wm = _make_watermark(wm_path)
    ref = run_tool(src, wm, out=out, layer=1)
    _assert_clean_run(ref)
    os.remove(out)

    wm = _make_watermark(wm_path, colours=(RED, BLUE))
    rec = run_tool(src, wm, out=out, layer=1)

    _assert_clean_run(rec)
    for i in range(2):
        assert _red(out, i).area == pytest.approx(WM_AREA, rel=AREA_TOL)
        assert _colour_stats(out, i, _is_blue).area == 0, (
            "page %d shows watermark page 2" % (i + 1))
    # QMessageBox.information(parent, title, text): one call, the done one.
    assert len(rec.infos) == 1, rec.infos
    assert rec.infos[0][1:] == (t("msg.done"), t("tool.watermark.done",
                                                 path=out))
    assert rec.statuses == [t("tool.watermark.status.done", name="out.pdf")]
    assert rec.page.lbl_info.text() == t("edit.status.pages", n=2)
    assert rec.widgets_after == rec.widgets_before, (
        "_run changed the page: " + _census_diff(rec.widgets_before,
                                                 rec.widgets_after))
    assert rec.widgets_after == ref.widgets_after, (
        "the two-page watermark changed the page, against the one-page "
        "reference: " + _census_diff(ref.widgets_after, rec.widgets_after))


# -- document-level structure ------------------------------------------------


def _toc(doc):
    return doc.get_toc()


def _title(doc):
    return (doc.metadata or {}).get("title") or ""


def _labels(doc):
    return doc.get_page_labels()


def _acroform(doc):
    return doc.xref_get_key(doc.pdf_catalog(), "AcroForm")[0] != "null"


def _attachments(doc):
    return doc.embfile_count()


@_known_defect("I4: the output keeps the source's document structure")
@pytest.mark.parametrize("probe", [_toc, _title, _labels, _acroform,
                                   _attachments],
                         ids=["outline", "title", "page-labels", "acroform",
                              "attachments"])
def test_document_structure_of_the_source_is_lost(tmp_path, run_tool, probe):
    # Characterises a known defect: the pages are copied into a fresh
    # PdfWriter, so everything hanging off the source's catalogue and
    # Info dictionary is dropped.
    src = _make_rich_source(tmp_path / "src.pdf")
    wm = _make_watermark(tmp_path / "wm.pdf")
    out = str(tmp_path / "out.pdf")

    s = pymupdf.open(src)
    try:
        assert probe(s), "fixture bug: the source lacks what is probed"
    finally:
        s.close()

    rec = run_tool(src, wm, out=out)

    _assert_clean_run(rec)
    o = pymupdf.open(out)
    try:
        assert not probe(o), "the output kept it: %r" % (probe(o),)
    finally:
        o.close()


@_known_defect("I4: the output keeps the source's AcroForm, so its "
               "widgets stay real form fields")
def test_form_widget_survives_on_the_page_without_its_acroform(
        tmp_path, run_tool):
    # Characterises a known defect: the page's /Annots are copied with
    # the page, so the widget annotation is still there, but the
    # catalogue's /AcroForm is gone: an orphaned field.
    src = _make_rich_source(tmp_path / "src.pdf")
    wm = _make_watermark(tmp_path / "wm.pdf")
    out = str(tmp_path / "out.pdf")

    rec = run_tool(src, wm, out=out)

    _assert_clean_run(rec)
    o = pymupdf.open(out)
    try:
        assert [w.field_name for w in o[0].widgets()] == ["nome"]
        assert not _acroform(o)
    finally:
        o.close()


# -- output name -------------------------------------------------------------


def test_loaded_source_prefills_the_output_currently_named_watermark(
        tmp_path, run_tool):
    # First default name: loading the source fills the output field
    # with "<source stem>_watermark<ext>" next to it (_load_input), so
    # no Save dialog opens. This pins the current behaviour only.
    # Whether this and the "_watermarked" name of the Save dialog
    # should be unified is a policy the user has not decided; if that
    # decision changes the name, this test is updated on purpose.
    folder = tmp_path / "pasta com espaços"
    folder.mkdir()
    src = _make_source(folder / "relatório final ção.pdf", [{}])
    wm = _make_watermark(tmp_path / "wm.pdf")

    rec = run_tool(src, wm)

    expected = str(folder / "relatório final ção_watermark.pdf")
    assert rec.out == expected
    _assert_clean_run(rec)
    assert _red(expected, 0).area > 0


def test_cleared_output_falls_back_to_a_save_dialog_currently_named_watermarked(
        tmp_path, run_tool, monkeypatch):
    # Second default name: with the output field cleared, the Save
    # dialog proposes "<base>_watermarked.pdf" (from drop_out's
    # default_name), not the "_watermark" suffix _load_input uses.
    # This pins the current behaviour only. Whether the two suffixes
    # should be unified is a policy the user has not decided; if that
    # decision changes the name, this test is updated on purpose.
    src = _make_source(tmp_path / "doc.pdf", [{}])
    wm = _make_watermark(tmp_path / "wm.pdf")
    asked = []
    # Replaced above QFileDialog, so run_tool's fail-closed
    # getSaveFileName stand-in is never reached on this path.
    monkeypatch.setattr(TabMarcaDagua, "_prompt_save_as",
                        lambda self, name, start, *a, **k:
                        asked.append((name, start)) or "")

    rec = run_tool(src, wm, clear_out=True)

    assert asked == [("doc_watermarked.pdf", str(tmp_path))]
    assert rec.box["calls"] == 0, "ran without an output path"
    assert not rec.errors and not rec.warnings


# -- encryption --------------------------------------------------------------


@pytest.mark.parametrize("src_pw", ["", "segredo-ç"],
                         ids=["plain-source", "aes256-source"])
def test_output_is_written_unencrypted_today(tmp_path, run_tool, src_pw):
    # Pins the current behaviour only: the output is never encrypted,
    # even when the source was. Whether the output should keep the
    # source's encryption is a policy the user has not decided; if that
    # decision changes it, this test is updated on purpose.
    src = _make_source(tmp_path / "src.pdf", [{}, {}], encrypt_pw=src_pw)
    wm = _make_watermark(tmp_path / "wm.pdf")
    out = str(tmp_path / "out.pdf")
    if src_pw:
        assert PdfReader(src).is_encrypted, "fixture bug: source not sealed"

    rec = run_tool(src, wm, out=out, src_password=src_pw)

    _assert_clean_run(rec)
    assert rec.page._pdf_password == src_pw
    # prompt_pdf_password is consulted for the source only when it is
    # sealed, and for the watermark always (no dialog for a plain file).
    assert rec.prompts == ([src] if src_pw else []) + [wm]
    assert not PdfReader(out).is_encrypted
    o = pymupdf.open(out)
    try:
        assert not o.needs_pass and not o.is_encrypted
    finally:
        o.close()
    for i in range(2):
        assert _red(out, i).area == pytest.approx(WM_AREA, rel=AREA_TOL)


# -- cancellation ------------------------------------------------------------


def test_cancel_midway_returns_none_and_writes_nothing(tmp_path, run_tool):
    src = _make_source(tmp_path / "src.pdf", [{}] * 4)
    wm = _make_watermark(tmp_path / "wm.pdf")
    out = str(tmp_path / "out.pdf")

    rec = run_tool(src, wm, out=out, worker=FakeWorker(cancel_after=2))

    assert rec.box["calls"] == 1
    assert "error" not in rec.box
    assert rec.box["result"] is None
    assert len(rec.box["worker"].emitted) == 2, "kept working after cancel"
    assert not os.path.exists(out)
    assert not rec.infos, "the done dialog appeared for a cancelled run"
    leftovers = [p.name for p in tmp_path.iterdir()
                 if p.name not in ("src.pdf", "wm.pdf")]
    assert not leftovers, "temp files left behind: %r" % (leftovers,)


def test_cancel_after_the_last_page_writes_nothing(tmp_path, run_tool):
    # Cancel lands after the last page was merged: the in-loop check
    # never fires, so only the check after the loop stops the write.
    src = _make_source(tmp_path / "src.pdf", [{}] * 4)
    wm = _make_watermark(tmp_path / "wm.pdf")
    out = str(tmp_path / "out.pdf")

    rec = run_tool(src, wm, out=out, worker=FakeWorker(cancel_after=4))

    assert rec.box["calls"] == 1
    assert "error" not in rec.box
    assert len(rec.box["worker"].emitted) == 4, "the loop stopped early"
    assert rec.box["result"] is None
    assert not os.path.exists(out)
    assert not rec.infos, "the done dialog appeared for a cancelled run"
    leftovers = [p.name for p in tmp_path.iterdir()
                 if p.name not in ("src.pdf", "wm.pdf")]
    assert not leftovers, "temp files left behind: %r" % (leftovers,)
