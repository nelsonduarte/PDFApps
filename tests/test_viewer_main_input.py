"""I2: only a tool's main input loads the viewer.

``MainWindow.__init__`` used to connect the ``path_changed`` of every
``DropFileEdit`` of every tool to the viewer. Only the main input is the
document the tool works on (``drop_in``, the editor's ``_drop_in``); every
other field is an output, an output folder or a secondary input (the
watermark's mark, the editor's image). Wired, those fields made the viewer
open a file that already existed where the tool was about to write, and on
Windows the write that followed failed with WinError 5: the viewer held
the file. They also put outputs and folders in the tab's title and in the
recent files, and since ``add_recent_file`` trims the list to ten before
``get_recent_files`` filters it, each output that went in pushed a real
file out for good.

The tests here drive the gestures that reached the viewer through a field
that is not the main input: a Save dialog's answer (Merge), a folder
picker's answer (Split, Converter's "another folder"), a pre-fill on the
Open button (Encrypt, Split, every tool with a PDF output), a format change
(OCR, Converter) and the editor's pre-fill in compact mode. The harness is
``test_overwrite_characterization``'s (``env``, ``_window``).

``windows_lock`` stands in for what Windows does while a viewer holds a
file: ``os.replace`` onto the ``current_path()`` of any viewer raises the
``PermissionError`` Windows raises (WinError 5), so the lock is caught on
every platform. It does not cover a write over the tool's own input, which
is AR8's, nor the folder outputs, where the viewer never opens a folder.
The ``*_real_windows`` variants run with no stand-in, on Windows only.

Reach, measured on the code at ``ee7d89b``. Split's output field is hidden
for good and ``_load_input`` fills it whenever it is empty, so on Windows,
macOS and a Linux without the document portal the folder picker of
``_resolve_output_dir`` is reached only once the field is cleared by code;
in a Snap or a Flatpak it is reached through the portal, whose doc folder
``_resolve_output_dir`` refuses (``is_portal_phantom``). Both routes are
driven. Every other gesture here is reachable through the interface.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pymupdf
import pytest
from _inline_background import run_background_inline
from PySide6.QtWidgets import QFileDialog
from test_overwrite_characterization import (  # noqa: F401
    _FMT_PNG,
    _FMT_TXT,
    _OCR_TXT,
    SPECS,
    _add_note,
    _close_window,
    _import_pick_files,
    _import_sources,
    _label,
    _make_pdf,
    _nav_item,
    _open_tool_on,
    _pages,
    _recents,
    _same,
    _set_owner_password,
    _set_pages,
    _set_watermark,
    _window,
    env,
)
from test_portal_phantom import portal  # noqa: F401

from app.editor.tab import TabEditar
from app.i18n import get_recent_files, t
from app.tools.compress import TabComprimir
from app.tools.convert import TabConverter, _image_name
from app.tools.encrypt import TabEncriptar
from app.tools.extract import TabExtrair
from app.tools.import_pdf import TabImport
from app.tools.merge import TabJuntar
from app.tools.nup import TabNUp
from app.tools.ocr import TabOCR
from app.tools.page_numbers import TabPageNumbers
from app.tools.reorder import TabReordenar
from app.tools.rotate import TabRotar
from app.tools.split import TabDividir
from app.tools.watermark import TabMarcaDagua

_real_windows = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the viewer's lock on a file it holds exists only on Windows")


def _recents_now(tmp_path) -> list[str]:
    cfg = tmp_path / "config.json"
    return _recents(tmp_path) if cfg.is_file() else []


def _open_button(env, field, path: str) -> None:
    """A click on ``field``'s own Open button, the dialog answering
    ``path``. The fail-closed Open dialog goes back once it answered."""
    fail_closed = QFileDialog.__dict__["getOpenFileName"]
    asked = []

    def _open(*a, **k):
        asked.append("getOpenFileName")
        return path, ""
    env.monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            staticmethod(_open))
    field.btn.click()
    env.monkeypatch.setattr(QFileDialog, "getOpenFileName", fail_closed)
    assert asked == ["getOpenFileName"]


def _open_tool_empty(win, cls):
    """Open the tool with no PDF in the viewer: normal mode."""
    page, item = _nav_item(win, cls)
    win._on_nav_clicked(item)
    assert win._viewer.current_path() == ""
    assert win.stack.currentWidget() is page
    return page


def _pick_folder_answer(env, folder: str) -> list:
    asked = []

    def _dir(*a, **k):
        asked.append("getExistingDirectory")
        return folder
    env.monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                            staticmethod(_dir))
    return asked


@pytest.fixture
def windows_lock(monkeypatch):
    """``os.replace`` onto a file a viewer shows fails as on Windows.

    Each refusal is recorded in the list returned. Only the destination
    counts, as measured on Windows 11 (see ``_WIN_FILE_IN_USE`` in
    ``app/pdf_io.py``): with PyMuPDF holding a file open, ``os.replace``
    onto it fails with WinError 5."""
    from app.viewer.panel import PdfViewerPanel

    real_replace = os.replace
    shown = []
    refused = []

    real_load = PdfViewerPanel.load

    def _load(self, path, *a, **k):
        if self not in shown:
            shown.append(self)
        return real_load(self, path, *a, **k)
    monkeypatch.setattr(PdfViewerPanel, "load", _load)

    def _replace(src, dst, *a, **k):
        target = os.path.normcase(os.path.abspath(os.fspath(dst)))
        for viewer in shown:
            held = viewer.current_path()
            if held and os.path.normcase(os.path.abspath(held)) == target:
                refused.append(os.fspath(dst))
                err = PermissionError(13, "Access is denied", os.fspath(src),
                                      None, os.fspath(dst))
                err.winerror = 5
                raise err
        return real_replace(src, dst, *a, **k)
    monkeypatch.setattr(os, "replace", _replace)
    return refused


# -- N1: a Save dialog's answer ----------------------------------------------


def _merge_into_existing(env, monkeypatch, qtbot):
    chosen = str(env.tmp / "junção existente ç.pdf")
    _make_pdf(Path(chosen), "STALE", 2)
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (chosen, "")))
    win = _window(monkeypatch, env.tmp)
    try:
        page = _open_tool_empty(win, TabJuntar)
        page._on_drop([env.a, env.b])
    except BaseException:
        _close_window(win, qtbot, env.tmp)
        raise
    return win, page, chosen


def test_merge_save_dialog_answer_that_exists_stays_out_of_the_viewer(
        env, monkeypatch, qtbot):
    """N1: the Save dialog answers a file that exists and is no input
    (``BasePage._ask_output_file``'s ``set_chosen_path``). The empty tab
    stays empty, keeps its title and the recent files stay empty."""
    win, page, chosen = _merge_into_existing(env, monkeypatch, qtbot)
    try:
        page._run()
        qtbot.wait(50)
        assert win._viewer.current_path() == ""
        assert win._tab_bar.tabText(0) == t("viewer.title")
        assert _recents_now(env.tmp) == []
        assert _label(chosen) == "A+B"
        assert len(env.infos) == 1
    finally:
        _close_window(win, qtbot, env.tmp)


@_real_windows
def test_merge_save_dialog_answer_that_exists_is_written_real_windows(
        env, monkeypatch, qtbot):
    """N1 with no stand-in: the merge replaces the file the dialog named."""
    win, page, chosen = _merge_into_existing(env, monkeypatch, qtbot)
    try:
        page._run()
        qtbot.wait(50)
        assert env.errors == []
        assert _label(chosen) == "A+B"
        assert len(env.infos) == 1
    finally:
        _close_window(win, qtbot, env.tmp)


# -- N2, N3: a folder picker's answer -----------------------------------------


@pytest.mark.parametrize("route", ["cleared", "portal"])
def test_split_folder_picker_answer_stays_out_of_the_viewer(
        env, portal, route, monkeypatch, qtbot):  # noqa: F811
    """N2: Split's folder picker answers a folder
    (``BasePage._resolve_output_dir``'s ``set_chosen_path``). The tab keeps
    the document's name and the recent files are what they were."""
    src = env.a if route == "cleared" else portal.share(env.a, "relatório ç.pdf")
    picked = env.tmp / "pasta escolhida ç"
    picked.mkdir()
    win = _window(monkeypatch, env.tmp)
    try:
        split = _open_tool_on(win, qtbot, TabDividir, src)
        assert _same(split.drop_out.path(), os.path.dirname(src))
        if route == "cleared":
            split.drop_out.clear()
        else:
            assert split.drop_out.is_portal_phantom()
        recents_before = _recents(env.tmp)
        asked = _pick_folder_answer(env, str(picked))
        split._run()
        qtbot.wait(50)
        assert asked == ["getExistingDirectory"]
        assert _same(split.drop_out.path(), str(picked))
        assert (picked / "part_1.pdf").is_file()
        assert _same(win._viewer.current_path(), src)
        assert win._tab_bar.tabText(0) == Path(src).name
        assert _recents(env.tmp) == recents_before
        assert len(env.infos) == 1
    finally:
        _close_window(win, qtbot, env.tmp)


def test_convert_png_another_folder_answer_stays_out_of_the_viewer(
        env, monkeypatch, qtbot):
    """N3: Converter to PNG finds a page image where it would write, the
    user answers "choose another folder" and the picker answers one
    (``BasePage._guard_folder_outputs``'s ``set_chosen_path``)."""
    spec = SPECS["convert_png"]
    clash = os.path.join(os.path.dirname(env.a), _image_name(0, "png"))
    Path(clash).write_bytes(b"not a page of A")
    picked = env.tmp / "outra pasta ç"
    picked.mkdir()
    win = _window(monkeypatch, env.tmp)
    try:
        page, _item = _nav_item(win, TabConverter)
        env.prepare(page, spec)
        assert page.cmb_format.currentIndex() == _FMT_PNG
        _open_tool_on(win, qtbot, TabConverter, env.a)
        recents_before = _recents(env.tmp)
        monkeypatch.setattr(page, "_ask_overwrite",
                            lambda *a, **k: page.OVERWRITE_RENAME)
        asked = _pick_folder_answer(env, str(picked))
        page._run()
        qtbot.wait(50)
        assert asked == ["getExistingDirectory"]
        assert _label(str(picked)) == "A"
        assert Path(clash).read_bytes() == b"not a page of A"
        assert _same(win._viewer.current_path(), env.a)
        assert win._tab_bar.tabText(0) == Path(env.a).name
        assert _recents(env.tmp) == recents_before
    finally:
        _close_window(win, qtbot, env.tmp)


# -- N4, N4b, N5: a pre-fill on the Open button -------------------------------


def _encrypt_twice(env, win, qtbot, user_pw: str):
    """Encrypt A through the Open button, then open A again the same way:
    the second load pre-fills the output the first run wrote."""
    page = _open_tool_empty(win, TabEncriptar)
    out = os.path.splitext(env.a)[0] + "_enc.pdf"
    _open_button(env, page.drop_in, env.a)
    assert _same(page.drop_out.path(), out)
    _set_owner_password(page, env)
    page.edit_user.setText(user_pw)
    page._run()
    qtbot.wait(50)
    assert os.path.isfile(out)
    assert len(env.infos) == 1
    _open_button(env, page.drop_in, env.a)
    qtbot.wait(50)
    assert _same(page.drop_out.path(), out)
    return page, out


def test_encrypt_reopen_with_user_password_output_asks_nothing(
        env, monkeypatch, qtbot):
    """N4: the output the first run wrote needs a password to open, and
    the second Open pre-fills it: nothing asks for that password. Before
    I2 the viewer loaded the output and asked (``_PdfPasswordDialog``)."""
    win = _window(monkeypatch, env.tmp)
    try:
        _encrypt_twice(env, win, qtbot, user_pw=env.owner_pw[::-1])
        assert env.modals == []
        assert win._viewer.current_path() == ""
        assert win._tab_bar.tabText(0) == t("viewer.title")
    finally:
        _close_window(win, qtbot, env.tmp)


def test_encrypt_reopen_leaves_the_output_out_of_the_viewer(
        env, monkeypatch, qtbot):
    """N4b: the same with no user password: the viewer, its tab and the
    recent files stay empty (the Open button does not preview, which is
    I3's). Before I2 the viewer opened the output, named the tab after it
    and put it in the recent files."""
    win = _window(monkeypatch, env.tmp)
    try:
        _encrypt_twice(env, win, qtbot, user_pw="")
        assert win._viewer.current_path() == ""
        assert win._tab_bar.tabText(0) == t("viewer.title")
        assert get_recent_files() == []
    finally:
        _close_window(win, qtbot, env.tmp)


@_real_windows
def test_encrypt_second_run_replaces_its_output_real_windows(
        env, monkeypatch, qtbot):
    """N4b with no stand-in: the second run replaces the first one's
    output, which the viewer no longer holds."""
    win = _window(monkeypatch, env.tmp)
    try:
        page, out = _encrypt_twice(env, win, qtbot, user_pw="")
        _set_owner_password(page, env)
        page._run()
        qtbot.wait(50)
        assert env.errors == []
        assert len(env.infos) == 2
        assert _label(out) == "A"
    finally:
        _close_window(win, qtbot, env.tmp)


def test_split_open_button_leaves_the_folder_out_of_the_viewer(
        env, monkeypatch, qtbot):
    """N5: Split's pre-fill of its output folder, on the Open button,
    leaves the tab's title and the recent files alone. Before I2 the folder
    named the tab and, existing, stayed in the recent files."""
    win = _window(monkeypatch, env.tmp)
    try:
        split = _open_tool_empty(win, TabDividir)
        _open_button(env, split.drop_in, env.a)
        qtbot.wait(50)
        assert _same(split.drop_out.path(), os.path.dirname(env.a))
        assert win._tab_bar.tabText(0) == t("viewer.title")
        assert get_recent_files() == []
    finally:
        _close_window(win, qtbot, env.tmp)


# -- N6, N7, N8, N9: pre-fills in compact mode and format changes --------------


def test_rotate_prefill_keeps_ten_real_recent_files(env, monkeypatch, qtbot):
    """N6: ten real PDFs in the recent files, A first; opening Rotate on A
    pre-fills an output that does not exist, and the ten stay. Before I2
    the output went in at the top, ``add_recent_file`` trimmed the tenth
    real file off, and ``get_recent_files`` then dropped the missing
    output: nine left, for good."""
    others = [_make_pdf(env.tmp / f"recente {i} ç.pdf", f"R{i}", 1)
              for i in range(9)]
    recents = [os.path.normpath(p) for p in [env.a, *others]]
    (env.tmp / "config.json").write_text(
        json.dumps({"recent_files": recents}), encoding="utf-8")
    win = _window(monkeypatch, env.tmp)
    try:
        assert get_recent_files() == recents
        _open_tool_on(win, qtbot, TabRotar, env.a)
        assert get_recent_files() == recents
    finally:
        _close_window(win, qtbot, env.tmp)


def test_extract_after_rotate_works_on_the_document(env, monkeypatch, qtbot):
    """N7: ``<A>_rotated.pdf`` exists from an earlier session. After
    Rotate, opened on A, the next tool opened works on A. Before I2 Rotate's
    pre-fill loaded that file into the viewer, and the next tool took it as
    its input."""
    stale = SPECS["rotate"].out(env.a)
    _make_pdf(Path(stale), "STALE", 2)
    win = _window(monkeypatch, env.tmp)
    try:
        _open_tool_on(win, qtbot, TabRotar, env.a)
        extract, item = _nav_item(win, TabExtrair)
        win._on_nav_clicked(item)  # straight from Rotate to Extract
        qtbot.wait(50)
        assert win.stack.currentWidget() is extract
        assert extract._compact_active
        assert win._tab_bar.count() == 1
        assert _same(extract.drop_in.path(), env.a)
        assert _same(win._viewer.current_path(), env.a)
        assert _same(extract.drop_out.path(), SPECS["extract"].out(env.a))
    finally:
        _close_window(win, qtbot, env.tmp)


def _editor_on_existing_output(env, monkeypatch, qtbot):
    out = SPECS["editor"].out(env.a)
    _make_pdf(Path(out), "STALE", 2)
    win = _window(monkeypatch, env.tmp)
    try:
        editor, item = _nav_item(win, TabEditar)
        win._load_and_track(env.a)
        qtbot.wait(50)
        win._on_nav_clicked(item)
        qtbot.wait(50)
        assert _same(editor._doc_path, env.a)
        assert _same(editor._drop_out.path(), out)
    except BaseException:
        _close_window(win, qtbot, env.tmp)
        raise
    return win, editor, out


def test_editor_compact_prefill_leaves_the_hidden_viewer_on_the_document(
        env, monkeypatch, qtbot):
    """N8: the editor, opened on A, pre-fills ``<A>_edited.pdf``, which
    exists: the viewer the editor hides stays on A. Before I2 it switched to
    that file and held it."""
    win, _editor, _out = _editor_on_existing_output(env, monkeypatch, qtbot)
    try:
        assert _same(win._viewer.current_path(), env.a)
        assert win._tab_bar.tabText(0) == Path(env.a).name
        assert get_recent_files() == [os.path.normpath(env.a)]
    finally:
        _close_window(win, qtbot, env.tmp)


@_real_windows
def test_editor_compact_run_replaces_its_output_real_windows(
        env, monkeypatch, qtbot):
    """N8 with no stand-in: applying an edit replaces ``<A>_edited.pdf``,
    which the hidden viewer no longer holds."""
    win, editor, out = _editor_on_existing_output(env, monkeypatch, qtbot)
    try:
        _add_note(editor, env)
        editor._run()
        qtbot.wait(50)
        assert env.errors == []
        assert _pages(out) == _pages(env.a)
    finally:
        _close_window(win, qtbot, env.tmp)


def _ocr_to_txt(page, env):
    page.cmb_fmt.setCurrentIndex(_OCR_TXT)


def _convert_to_txt(page, env):
    page.cmb_format.setCurrentIndex(_FMT_TXT)


@pytest.mark.parametrize(("cls", "attr", "txt", "switch"), [
    (TabOCR, "drop_out", lambda a: os.path.splitext(a)[0] + "_ocr.txt",
     _ocr_to_txt),
    (TabConverter, "_drop_file", lambda a: os.path.splitext(a)[0] + ".txt",
     _convert_to_txt),
], ids=["ocr", "convert"])
def test_format_change_to_an_existing_txt_warns_nothing(
        env, cls, attr, txt, switch, monkeypatch, qtbot):
    """N9: a format change re-derives the output as ``.txt``
    (``TabOCR._on_fmt_change``, ``TabConverter._on_format_changed``), and
    that file exists: no warning, and the tab and the recent files stay as
    they were. Before I2 the viewer warned "invalid format" and the tab and
    the recent files took the ``.txt``."""
    out = txt(env.a)
    Path(out).write_text("ORIGINAL", encoding="utf-8")
    win = _window(monkeypatch, env.tmp)
    try:
        page = _open_tool_on(win, qtbot, cls, env.a)
        recents_before = _recents(env.tmp)
        switch(page, env)
        qtbot.wait(50)
        assert _same(getattr(page, attr).path(), out)
        assert env.warnings == []
        assert _same(win._viewer.current_path(), env.a)
        assert win._tab_bar.tabText(0) == Path(env.a).name
        assert _recents(env.tmp) == recents_before
    finally:
        _close_window(win, qtbot, env.tmp)


# -- N10: every tool with a PDF output, under the Windows lock ---------------


def _ocr_pdf_pages(monkeypatch):
    """OCR to PDF asks Tesseract for one PDF page per image."""
    def _page_pdf(img, lang=None, extension="pdf", **_kw):
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 300), "ocr")
        try:
            return doc.tobytes()
        finally:
            doc.close()
    monkeypatch.setattr(sys.modules["pytesseract"], "image_to_pdf_or_hocr",
                        _page_pdf, raising=False)


def _none(page, env):
    pass


def _watermark_first(page, env):
    # The mark is picked before A is opened. Before I2 a mark picked after
    # A became the viewer's document, so the output was no longer the file
    # the viewer held, and the case did not tell the two states apart.
    _set_watermark(page, env)


# (id, class, output suffix, before the Open button, before the run)
_LOCK_CASES = [
    ("rotate", TabRotar, "_rotated", _none, _none),
    ("extract", TabExtrair, "_extracted", _none, _set_pages),
    ("reorder", TabReordenar, "_reordered", _none, _none),
    ("compress", TabComprimir, "_compressed", _none, _none),
    ("page_numbers", TabPageNumbers, "_numbered", _none, _none),
    ("nup", TabNUp, "_nup", _none, _none),
    ("watermark", TabMarcaDagua, "_watermark", _watermark_first, _none),
    ("ocr", TabOCR, "_ocr", _none, _none),
    ("encrypt", TabEncriptar, "_enc", _none, _set_owner_password),
    ("editor", TabEditar, "_edited", _none, _add_note),
]
_INLINE = {"page_numbers", "nup", "watermark"}


@pytest.mark.parametrize(
    ("tool_id", "cls", "suffix", "before_open", "before_run"), _LOCK_CASES,
    ids=[c[0] for c in _LOCK_CASES])
def test_open_button_then_run_replaces_a_stale_output_under_the_lock(
        env, windows_lock, tool_id, cls, suffix, before_open, before_run,
        monkeypatch, qtbot):
    """N10: a result of an earlier session sits where the tool writes. The
    tool is opened with no PDF in the viewer, A goes in through its Open
    button, and the run replaces that result. Before I2 the output's
    pre-fill loaded it into the viewer, and the run could not replace it.
    Compress passed before I2 too: since M-1 its pre-fill blocked the
    field's signals. Replacing a file that exists without asking is the
    silent overwrite, pinned elsewhere and not I2's."""
    out = os.path.splitext(env.a)[0] + suffix + ".pdf"
    shutil.copy(env.b, out)  # three pages; A's result has one
    if tool_id == "ocr":
        _ocr_pdf_pages(monkeypatch)
    win = _window(monkeypatch, env.tmp)
    try:
        page = _open_tool_empty(win, cls)
        if tool_id in _INLINE:
            env.boxes.append(run_background_inline(page, monkeypatch))
        before_open(page, env)
        field = page._drop_in if tool_id == "editor" else page.drop_in
        _open_button(env, field, env.a)
        qtbot.wait(50)
        out_field = page._drop_out if tool_id == "editor" else page.drop_out
        assert _same(out_field.path(), out)
        before_run(page, env)
        page._run()
        qtbot.wait(50)
        assert windows_lock == []
        assert env.errors == []
        assert _pages(out) == _pages(env.a)
    finally:
        _close_window(win, qtbot, env.tmp)


def test_import_pick_then_run_replaces_a_stale_output_under_the_lock(
        env, windows_lock, monkeypatch, qtbot):
    """N10 for Import: its pick pre-fills ``<stem>.pdf``, which exists; the
    user answers the overwrite question with Replace."""
    src, _b = _import_sources(env)
    out = os.path.splitext(src)[0] + ".pdf"
    shutil.copy(env.b, out)
    win = _window(monkeypatch, env.tmp)
    try:
        page = _open_tool_empty(win, TabImport)
        env.boxes.append(run_background_inline(page, monkeypatch))
        _import_pick_files(page, monkeypatch, [src])
        qtbot.wait(50)
        assert _same(page.drop_out.path(), out)
        monkeypatch.setattr(page, "_ask_overwrite",
                            lambda *a, **k: page.OVERWRITE_REPLACE)
        page._run()
        qtbot.wait(50)
        assert windows_lock == []
        assert env.errors == []
        assert _pages(out) == 1
    finally:
        _close_window(win, qtbot, env.tmp)
