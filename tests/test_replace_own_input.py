"""Writing over an input, and closing with a result that was not saved.

* C-1: closing with a pipeline result and choosing Save went on closing
  whatever the Save dialog did, and the teardown deleted the result: a
  Cancel, an answer the dialog refused, or a failed write lost it. The
  Save also acted on the current tab, so a result in another tab was lost
  even when the user did pick a path.
* A-1 (the user's decision, option A): Compress and the pipeline's Save as
  may replace their input, as the editor may; the other tools refuse. The
  replacement goes through a temp file and ``os.replace``: the input is
  never opened for writing.
* A-2: ``os.path.samefile`` compares only ``st_ino`` and ``st_dev``. A
  file system with no file id reports 0, and every pair of files on it
  looked the same.
* M-1 (the user's decision): Compress kept its hidden output while the
  input changed, so compressing A and then picking A's output as the input
  replaced that file unasked. Only a Save dialog's answer, for the current
  input, may name the input now. Filling that hidden field on each load
  also loaded the previous run's result into the viewer, which held it,
  and the next run could not replace it.
* A read or write Windows refuses (the file is open, in the viewer or
  elsewhere, or read-only) is shown with what to do, and the toast's
  button, Ctrl+S and a tab's close prompt show a failed save instead of
  letting it reach ``sys.excepthook``.
"""

import contextlib
import errno
import logging
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox
from test_overwrite_characterization import (  # noqa: F401
    SPECS,
    _close_window,
    _import_pick_files,
    _import_sources,
    _nav_item,
    _no_setup,
    _same,
    _window,
    env,
)
from test_portal_phantom import (  # noqa: F401
    _SOURCE,
    _dialogs,
    portal,
)

from app import utils
from app.i18n import t
from app.pdf_io import (
    check_not_same_path,
    is_file_in_use_error,
    is_same_file,
    resolves_to_any,
)
from app.tools.compress import TabComprimir
from app.tools.import_pdf import TabImport
from app.tools.rotate import TabRotar

# -- A-2: no file id ---------------------------------------------------------


def _stat_result(ino: int, dev: int, size: int = 1) -> os.stat_result:
    return os.stat_result((stat.S_IFREG | 0o644, ino, dev, 1, 0, 0, size, 0, 0, 0))


def _fake_stat(monkeypatch, fakes: dict) -> None:
    """``os.stat`` answering ``fakes`` (path -> stat_result) for those paths."""
    real = os.stat
    wanted = {os.path.normcase(os.path.abspath(p)): r for p, r in fakes.items()}

    def _stat(path, *a, **k):
        key = os.path.normcase(os.path.abspath(os.fspath(path)))
        if key in wanted:
            return wanted[key]
        return real(path, *a, **k)
    monkeypatch.setattr(os, "stat", _stat)


@pytest.fixture
def two_files(tmp_path):
    a = tmp_path / "um ç.pdf"
    b = tmp_path / "dois ã.pdf"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    return str(a), str(b)


@pytest.mark.parametrize("ino, dev", [(0, 7), (5, 0), (0, 0)],
                         ids=["no_ino", "no_dev", "neither"])
def test_two_files_with_no_file_id_are_not_the_same(
        monkeypatch, two_files, ino, dev):
    a, b = two_files
    _fake_stat(monkeypatch, {a: _stat_result(ino, dev), b: _stat_result(ino, dev)})
    assert os.path.samefile(a, b), "the premise: samefile is fooled"

    assert is_same_file(a, b) is False
    assert resolves_to_any(b, [a]) is False
    check_not_same_path(b, [a])


def test_a_file_with_no_file_id_is_still_itself(monkeypatch, two_files):
    a, _b = two_files
    _fake_stat(monkeypatch, {a: _stat_result(0, 0)})
    assert is_same_file(a, a) is True
    assert is_same_file(a, os.path.join(os.path.dirname(a), ".", os.path.basename(a)))
    with pytest.raises(RuntimeError):
        check_not_same_path(a, [a])


def test_the_same_inode_on_another_device_is_another_file(monkeypatch, two_files):
    a, b = two_files
    _fake_stat(monkeypatch, {a: _stat_result(5, 7), b: _stat_result(5, 8)})
    assert is_same_file(a, b) is False
    assert resolves_to_any(b, [a]) is False

    _fake_stat(monkeypatch, {a: _stat_result(5, 7), b: _stat_result(5, 7)})
    assert is_same_file(a, b) is True, "the control: one id is one file"


def test_with_no_file_id_the_case_of_the_name_counts_as_the_os_does(
        monkeypatch, tmp_path):
    """Windows names are case-insensitive, POSIX ones are not (macOS
    included: ``normcase`` changes nothing there). Neither file exists, so
    ``realpath`` keeps each name as given and only the comparison decides."""
    lower = str(tmp_path / "relatório ç.pdf")
    upper = str(tmp_path / "RELATÓRIO Ç.pdf")
    _fake_stat(monkeypatch, {lower: _stat_result(0, 0), upper: _stat_result(0, 0)})
    assert os.path.realpath(lower) != os.path.realpath(upper), "the premise"

    expected = sys.platform == "win32"
    assert is_same_file(lower, upper) is expected
    assert resolves_to_any(upper, [lower]) is expected


def _link_or_skip(src: str, link: str) -> None:
    """``os.link``, skipping only where the file system has no hard links:
    any other error is the test's to report."""
    try:
        os.link(src, link)
    except (NotImplementedError, PermissionError) as exc:
        pytest.skip(f"no hard links here: {exc!r}")
    except OSError as exc:
        # EPERM needs no entry: Python raises it as PermissionError.
        if exc.errno in (errno.ENOTSUP, errno.EXDEV):
            pytest.skip(f"no hard links here: {exc!r}")
        raise


def test_a_hard_link_is_the_same_file(two_files):
    a, _b = two_files
    link = os.path.join(os.path.dirname(a), "ligação.pdf")
    _link_or_skip(a, link)
    assert is_same_file(link, a) is True
    assert resolves_to_any(link, [a]) is True


def test_a_destination_that_does_not_exist_is_no_input(two_files):
    a, _b = two_files
    missing = os.path.join(os.path.dirname(a), "novo.pdf")
    assert is_same_file(missing, a) is False
    assert is_same_file(a, missing) is False
    assert resolves_to_any(missing, [a, "", None]) is False


# -- A-1: Compress over its input, the real _compress_pdf --------------------


def _compressible_pdf(path: Path) -> str:
    """Five pages of text with every stream left uncompressed."""
    doc = pymupdf.open()
    for n in range(5):
        page = doc.new_page()
        for line in range(55):
            page.insert_text((36, 30 + line * 13), f"pagina {n} linha {line} " * 4)
    doc.save(str(path), deflate=False, garbage=0)
    doc.close()
    return str(path)


def _file_id(path: str) -> tuple:
    st = os.stat(path)
    return st.st_dev, st.st_ino


@pytest.fixture
def compress_src(tmp_path, monkeypatch):
    # Ghostscript or not, on every machine the same passes run.
    monkeypatch.setattr(utils, "_find_gs", lambda: None)
    folder = tmp_path / "pasta ç"
    folder.mkdir()
    return _compressible_pdf(folder / "original ã.pdf")


def test_compress_onto_its_input_replaces_it_with_a_new_file(compress_src):
    before = os.path.getsize(compress_src)
    old_id = _file_id(compress_src)

    got_before, after = utils._compress_pdf(compress_src, compress_src)

    assert got_before == before and after < before
    assert os.path.getsize(compress_src) == after
    with pymupdf.open(compress_src) as doc:
        assert doc.page_count == 5
        assert "pagina 4 linha 54" in doc[4].get_text()
    # A new file took the name: the input was never rewritten in place.
    assert _file_id(compress_src) != old_id
    assert os.listdir(os.path.dirname(compress_src)) == [os.path.basename(compress_src)]


def test_compress_onto_its_input_leaves_it_whole_when_the_replace_fails(
        compress_src, monkeypatch):
    before = Path(compress_src).read_bytes()
    real_replace = os.replace

    def _replace(src, dst, *a, **k):
        if _same(os.fspath(dst), compress_src):
            raise PermissionError(13, "Permission denied", os.fspath(dst))
        return real_replace(src, dst, *a, **k)
    monkeypatch.setattr(os, "replace", _replace)

    with pytest.raises(PermissionError):
        utils._compress_pdf(compress_src, compress_src)

    assert Path(compress_src).read_bytes() == before
    assert os.listdir(os.path.dirname(compress_src)) == [os.path.basename(compress_src)]


# -- M-1: Compress replaces its input only when told to, for that input ------


def _compress_page(env):
    page = env.make(SPECS["compress"])
    assert not page.drop_out.isVisibleTo(page), "the premise: a hidden field"
    return page


def test_compress_output_as_the_next_input_is_not_replaced(env, monkeypatch):
    """M-1, as measured: compress A, then pick A's output as the input. The
    hidden field kept the old output, now the input, and the run replaced
    it with no question."""
    page = _compress_page(env)
    page.drop_in.set_path(env.a)
    page._run()
    first_out = os.path.splitext(env.a)[0] + "_compressed.pdf"
    assert env.compress_calls == [(page.drop_in.path(), page.drop_out.path())]
    assert _same(page.drop_out.path(), first_out) and os.path.isfile(first_out)
    asked = _dialogs(monkeypatch, first_out)
    page.drop_in.set_path(first_out)
    old_id, before = _file_id(first_out), Path(first_out).read_bytes()

    page._run()

    second_out = os.path.splitext(first_out)[0] + "_compressed.pdf"
    assert asked == []
    assert [(_same(s, first_out), _same(d, second_out))
            for s, d in env.compress_calls[1:]] == [(True, True)]
    assert _file_id(first_out) == old_id
    assert Path(first_out).read_bytes() == before
    assert env.warnings == [] and len(env.infos) == 2


def test_compress_field_naming_its_input_asks_first(env, monkeypatch):
    """The field holds the input, and no Save dialog chose it: the run asks
    through that dialog, as the field is hidden and a warning to choose
    another name would leave nowhere to do it. A Cancel writes nothing; the
    input picked there is replaced, as the dialog asked about it."""
    page = _compress_page(env)
    page.drop_in.set_path(env.a)
    page.drop_out.set_path(env.a)
    old_id = _file_id(env.a)
    asked = _dialogs(monkeypatch, "")

    page._run()

    assert len(asked) == 1 and env.compress_calls == []
    assert env.warnings == [] and env.infos == []
    assert _file_id(env.a) == old_id
    asked = _dialogs(monkeypatch, env.a)

    page._run()

    assert len(asked) == 1
    assert [(_same(s, env.a), _same(d, env.a)) for s, d in env.compress_calls] == \
        [(True, True)]
    assert page.drop_out.is_chosen()
    assert env.warnings == [] and len(env.infos) == 1


def test_compress_dialog_answer_stops_counting_on_a_new_input(env, monkeypatch):
    """A Save dialog's answer covers the input it was given for. Here it
    names what is also the next input's own output, a hard link to that
    input: it no longer lets the run write there unasked."""
    page = _compress_page(env)
    page.drop_in.set_path(env.a)
    b_out = os.path.splitext(env.b)[0] + "_compressed.pdf"
    _link_or_skip(env.b, b_out)
    page.drop_out.set_chosen_path(b_out)  # the dialog's answer, for A
    assert page.drop_out.is_chosen()
    page.drop_in.set_path(env.b)
    assert _same(page.drop_out.path(), b_out)
    assert not page.drop_out.is_chosen()
    old_id = _file_id(env.b)
    asked = _dialogs(monkeypatch, "")

    page._run()

    assert len(asked) == 1 and env.compress_calls == []
    assert _file_id(env.b) == old_id == _file_id(b_out)
    assert env.warnings == [] and env.infos == []


def test_compress_twice_on_one_input_leaves_the_viewer_alone(env, monkeypatch, qtbot):
    """The output field is filled on every load, and MainWindow loads every
    field into the viewer: on the second load the viewer opened the first
    run's result and held it, and on Windows the second run could not
    replace it (WinError 5)."""
    win = _window(monkeypatch, env.tmp)
    try:
        page, item = _nav_item(win, TabComprimir)
        win._on_nav_clicked(item)
        assert not page._pipeline_active and not win._viewer.current_path()
        out = os.path.splitext(env.a)[0] + "_compressed.pdf"
        page._load_input(env.a)
        assert not win._viewer.current_path()
        page._run()
        assert os.path.isfile(out)

        page._load_input(env.a)

        assert _same(page.drop_out.path(), out)
        assert not win._viewer.current_path()
        page._run()
        assert env.errors == []
        assert [(_same(s, env.a), _same(d, out)) for s, d in env.compress_calls] \
            == [(True, True), (True, True)]
        assert env.warnings == [] and len(env.infos) == 2
    finally:
        _close_window(win, qtbot, env.tmp)


# -- A-1: the pipeline's Save as over the original ---------------------------


def _pending(win, viewer, original: str, content: bytes) -> str:
    """A pipeline result for ``viewer``, where a tool writes one: in a tool
    page's own temp dir, which ``_cleanup_pipeline`` deletes."""
    page = next(w for w in (win.stack.widget(i) for i in range(win.stack.count()))
                if isinstance(w, TabRotar))
    temp = page._make_pipeline_temp(original)
    Path(temp).write_bytes(content)
    win._pipeline_state[id(viewer)] = {"original_path": original, "temp_path": temp}
    return temp


def _has_result(win, viewer) -> bool:
    return bool(win._pipeline_state.get(id(viewer), {}).get("temp_path"))


def test_pipeline_save_over_the_original_is_a_new_file(env, monkeypatch, qtbot):
    win = _window(monkeypatch, env.tmp)
    try:
        result = Path(env.b).read_bytes()
        _pending(win, win._viewer, env.a, result)
        old_id = _file_id(env.a)
        _dialogs(monkeypatch, env.a)

        assert win._save_pipeline() is True

        assert Path(env.a).read_bytes() == result
        assert _file_id(env.a) != old_id
        assert env.warnings == []
        assert not _has_result(win, win._viewer)
    finally:
        _close_window(win, qtbot, env.tmp)


def _failing_replace_onto(monkeypatch, target: str) -> None:
    real_replace = os.replace

    def _replace(src, dst, *a, **k):
        if _same(os.fspath(dst), target):
            # What Windows answers while a viewer has the file open (measured
            # with PyMuPDF 1.28.2: WinError 5).
            raise PermissionError(13, "Permission denied", os.fspath(dst))
        return real_replace(src, dst, *a, **k)
    monkeypatch.setattr(os, "replace", _replace)


def test_pipeline_save_over_the_original_never_truncates_it(env, monkeypatch, qtbot):
    """The copy2 fallback opens the destination for writing: on the
    original, a failed replace would have rewritten it in place."""
    win = _window(monkeypatch, env.tmp)
    try:
        before = Path(env.a).read_bytes()
        temp = _pending(win, win._viewer, env.a, Path(env.b).read_bytes())
        _dialogs(monkeypatch, env.a)
        _failing_replace_onto(monkeypatch, env.a)

        with pytest.raises(PermissionError):
            win._save_pipeline()

        assert Path(env.a).read_bytes() == before
        assert _has_result(win, win._viewer) and os.path.isfile(temp)
        assert sorted(os.listdir(os.path.dirname(env.a))) == [os.path.basename(env.a)]
    finally:
        _close_window(win, qtbot, env.tmp)


def test_pipeline_save_onto_a_hard_link_of_the_original_never_truncates_it(
        env, monkeypatch, qtbot):
    """Another name, the same file: copy2 onto the link would rewrite the
    original in place, so the paths alone cannot tell it is the original."""
    link = os.path.join(os.path.dirname(env.a), "ligação ç.pdf")
    _link_or_skip(env.a, link)
    win = _window(monkeypatch, env.tmp)
    try:
        before = Path(env.a).read_bytes()
        temp = _pending(win, win._viewer, env.a, Path(env.b).read_bytes())
        _dialogs(monkeypatch, link)
        _failing_replace_onto(monkeypatch, link)

        with pytest.raises(PermissionError):
            win._save_pipeline()

        assert Path(env.a).read_bytes() == before
        assert _has_result(win, win._viewer) and os.path.isfile(temp)
        assert sorted(os.listdir(os.path.dirname(env.a))) == sorted(
            [os.path.basename(env.a), os.path.basename(link)])
    finally:
        _close_window(win, qtbot, env.tmp)


def test_pipeline_save_elsewhere_keeps_its_last_resort_copy(env, monkeypatch, qtbot):
    """The boundary: any other destination still falls back to copy2."""
    win = _window(monkeypatch, env.tmp)
    try:
        result = Path(env.b).read_bytes()
        _pending(win, win._viewer, env.a, result)
        other = str(env.tmp / "outro ç.pdf")
        Path(other).write_bytes(b"old")
        _dialogs(monkeypatch, other)
        _failing_replace_onto(monkeypatch, other)

        assert win._save_pipeline() is True

        assert Path(other).read_bytes() == result
    finally:
        _close_window(win, qtbot, env.tmp)


# -- A-1: a tool that refuses, after "Choose another name" -------------------


@pytest.mark.parametrize("which", [0, 1], ids=["first", "second"])
def test_choose_another_name_refuses_any_of_imports_files(env, monkeypatch, which):
    """Import reads every file in its list, not only the first, so the name
    picked after "Choose another name" is checked against all of them: the
    first as much as the last."""
    a, b = _import_sources(env)
    answer = (a, b)[which]
    page = env.make(SimpleNamespace(cls=TabImport, inline=True,
                                    before_load=_no_setup))
    _import_pick_files(page, monkeypatch, [a, b])
    taken = env.tmp / "já existe ç.pdf"
    taken.write_bytes(b"the user's own file")
    page.drop_out.set_path(str(taken))
    overwrite_asked = []

    def _ask_overwrite(*args, **kwargs):
        overwrite_asked.append((args, kwargs))
        return page.OVERWRITE_RENAME
    monkeypatch.setattr(page, "_ask_overwrite", _ask_overwrite)
    asked = _dialogs(monkeypatch, answer)
    answer_before = Path(answer).read_bytes()

    page._run()

    # Through the Rename branch: one question, about the field's file.
    assert [(len(args), kwargs) for args, kwargs in overwrite_asked] == [(1, {})]
    assert [_same(p, str(taken)) for p in overwrite_asked[0][0][0]] == [True]
    assert len(asked) == 1
    assert env.warnings == [(t("msg.warning"), t("tool.err.same_source_output"))]
    assert Path(answer).read_bytes() == answer_before
    assert taken.read_bytes() == b"the user's own file"
    assert env.infos == []


# -- C-1: closing with a result that was not saved ---------------------------


def _answer_close_prompt(monkeypatch, answer: str) -> list:
    asked = []

    def _question(parent, title, text, *a, **k):
        asked.append(text)
        return getattr(QMessageBox.StandardButton, answer)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(_question))
    return asked


def _close(win) -> bool:
    event = QCloseEvent()
    win.closeEvent(event)
    return event.isAccepted()


def _errors_shown(monkeypatch) -> list:
    shown = []
    monkeypatch.setattr("app.window.show_error",
                        lambda parent, exc: shown.append(exc))
    return shown


@pytest.fixture
def two_tabs(env, monkeypatch, qtbot):
    """A window with A's tab, which has the result, and B's, the current."""
    win = _window(monkeypatch, env.tmp)
    win._load_and_track(env.a)
    first = win._viewer
    temp = _pending(win, first, env.a, Path(env.b).read_bytes())
    win._load_and_track(env.b)
    assert win._viewer is not first and win._tab_bar.count() == 2
    yield win, first, temp
    _close_window(win, qtbot, env.tmp)


@pytest.fixture
def one_tab(env, monkeypatch, qtbot):
    win = _window(monkeypatch, env.tmp)
    win._load_and_track(env.a)
    temp = _pending(win, win._viewer, env.a, Path(env.b).read_bytes())
    yield win, win._viewer, temp
    _close_window(win, qtbot, env.tmp)


def _assert_kept(win, viewer, temp):
    assert _has_result(win, viewer), "the result must stay to try again"
    assert os.path.isfile(temp), "the teardown deleted it"


@pytest.mark.parametrize("tabs", ["one_tab", "two_tabs"])
def test_close_with_save_cancelled_stays_open(request, env, monkeypatch, tabs):
    win, viewer, temp = request.getfixturevalue(tabs)
    asked = _answer_close_prompt(monkeypatch, "Save")
    saves = _dialogs(monkeypatch, "")

    assert _close(win) is False

    assert len(asked) == 1 and len(saves) == 1
    _assert_kept(win, viewer, temp)


@pytest.mark.parametrize("tabs", ["one_tab", "two_tabs"])
def test_close_with_a_refused_save_answer_stays_open(
        request, env, portal, monkeypatch, tabs):
    """A doc folder answer the portal would swallow: the dialog warns, and
    the window must not then close and delete the result."""
    win, viewer, temp = request.getfixturevalue(tabs)
    _answer_close_prompt(monkeypatch, "Save")
    src = portal.share(env.a, _SOURCE)
    win._pipeline_state[id(viewer)]["original_path"] = src
    saves = _dialogs(monkeypatch, portal.path("ab12cd34", "outro.pdf"))

    assert _close(win) is False

    assert len(saves) == 1
    assert env.warnings == [(t("msg.warning"), t("tool.err.portal_output"))]
    _assert_kept(win, viewer, temp)


@pytest.mark.parametrize("where, error", [
    ("missing_folder", FileNotFoundError),
    # The original held open by a viewer, as on Windows: not a missing
    # file, so a handler for that alone lets it out of closeEvent.
    ("the_original", PermissionError),
], ids=["missing_folder", "the_original"])
@pytest.mark.parametrize("tabs", ["one_tab", "two_tabs"])
def test_close_with_a_failed_save_stays_open_and_says_why(
        request, env, monkeypatch, tabs, where, error):
    win, viewer, temp = request.getfixturevalue(tabs)
    _answer_close_prompt(monkeypatch, "Save")
    shown = _errors_shown(monkeypatch)
    before = Path(env.a).read_bytes()
    if where == "the_original":
        _failing_replace_onto(monkeypatch, env.a)
        _dialogs(monkeypatch, env.a)
    else:
        _dialogs(monkeypatch, str(env.tmp / "pasta que falta" / "x.pdf"))

    assert _close(win) is False

    assert [type(e) for e in shown] == [error]
    assert Path(env.a).read_bytes() == before
    if where == "the_original":
        # The temp file the save wrote next to the original went with it.
        assert os.listdir(os.path.dirname(env.a)) == [os.path.basename(env.a)]
    _assert_kept(win, viewer, temp)


@pytest.mark.parametrize("tabs", ["one_tab", "two_tabs"])
def test_close_with_a_save_that_worked_closes(request, env, monkeypatch, tabs):
    """The control: the tab with the result is the one saved, then the
    window closes."""
    win, viewer, temp = request.getfixturevalue(tabs)
    _answer_close_prompt(monkeypatch, "Save")
    saved = str(env.tmp / "guardado ç.pdf")
    _dialogs(monkeypatch, saved)

    assert _close(win) is True

    assert Path(saved).read_bytes() == Path(env.b).read_bytes()
    assert _same(viewer.current_path(), saved)
    assert not os.path.exists(temp), "saved, so the teardown may delete it"


def test_closing_the_other_tab_saves_that_tabs_result(env, monkeypatch, two_tabs):
    win, first, temp = two_tabs
    _answer_close_prompt(monkeypatch, "Save")
    saved = str(env.tmp / "guardado ç.pdf")
    _dialogs(monkeypatch, saved)
    current = win._tab_bar.currentIndex()
    assert win._viewers[current] is not first
    current_tab = (win._tab_bar.tabText(current), win._tab_bar.tabToolTip(current))

    win._close_tab(win._viewers.index(first))

    assert Path(saved).read_bytes() == Path(env.b).read_bytes()
    assert not _has_result(win, first) and not os.path.exists(temp)
    assert _same(first.current_path(), saved)
    assert win._tab_bar.tabText(win._viewers.index(first)) == "guardado ç.pdf"
    # The tab the user is on is not the one saved: its name stays.
    assert (win._tab_bar.tabText(current),
            win._tab_bar.tabToolTip(current)) == current_tab


def test_the_toasts_save_button_saves_the_current_tab(env, monkeypatch, one_tab):
    """The button reaches ``_try_save_pipeline`` signal to signal, with no
    argument: its ``viewer`` parameter must stay unset."""
    from PySide6.QtWidgets import QPushButton
    win, viewer, temp = one_tab
    page = next(w for w in (win.stack.widget(i) for i in range(win.stack.count()))
                if isinstance(w, TabRotar))
    page._show_toast("ok", temp, with_save=True)
    button = page._toast_widget.findChild(QPushButton, "toast_save")
    saved = str(env.tmp / "pelo botão.pdf")
    _dialogs(monkeypatch, saved)

    button.click()

    assert Path(saved).read_bytes() == Path(env.b).read_bytes()
    assert not _has_result(win, viewer) and not os.path.exists(temp)


# -- a read or write Windows refuses: the file is open, or read-only --------


def _refused(winerror, src: str, dst: str = "") -> PermissionError:
    """What a refused write raises: ``os.replace(src, dst)``, or an open of
    ``src`` alone (``dst`` empty), for reading as much as for writing."""
    exc = PermissionError(errno.EACCES, "Access is denied", src, None, dst or None)
    exc.winerror = winerror
    return exc


@pytest.mark.parametrize("winerror, exists, platform, expected", [
    (5, True, "win32", True),
    (32, True, "win32", True),
    (33, True, "win32", True),
    # ERROR_WRITE_PROTECT, also a PermissionError: not a held file.
    (19, True, "win32", False),
    # A temp file in a folder that cannot be written: closing a file
    # would not help.
    (5, False, "win32", False),
    (5, True, "linux", False),
    (5, True, "darwin", False),
], ids=["access_denied", "sharing_violation", "lock_violation", "write_protect",
        "missing_file", "linux", "macos"])
def test_a_file_windows_refuses_to_replace(tmp_path, winerror, exists, platform,
                                           expected):
    held = tmp_path / "aberto ç.pdf"
    if exists:
        held.write_bytes(b"x")
    exc = _refused(winerror, str(tmp_path / "tmpab12.pdf"), str(held))
    assert is_file_in_use_error(exc, platform) is expected


def test_a_refused_open_with_no_win32_code_counts_too(tmp_path):
    """The C runtime's open (``shutil.copy2``) sets errno alone: measured on
    a read-only file, PermissionError with winerror None."""
    held = tmp_path / "só leitura ç.pdf"
    held.write_bytes(b"x")
    assert is_file_in_use_error(_refused(None, str(held)), "win32") is True
    assert is_file_in_use_error(_refused(None, str(held)), "linux") is False


@pytest.mark.parametrize("exc", [
    FileNotFoundError(errno.ENOENT, "missing", "x.pdf"),
    RuntimeError("Permission denied"),
    PermissionError(errno.EACCES, "denied", 3),
], ids=["not_found", "not_os_error", "fd_not_path"])
def test_other_errors_are_not_a_file_in_use(exc):
    assert is_file_in_use_error(exc, "win32") is False


def _mapped(winerror) -> OSError:
    """What ``shutil.copy2`` onto a mapped file raises: no file name."""
    exc = OSError(errno.EINVAL, "The requested operation cannot be performed "
                  "on a file with a user-mapped section open")
    exc.winerror = winerror
    return exc


@pytest.mark.parametrize("winerror, platform, expected", [
    (1224, "win32", True),
    (1224, "linux", False),
    # ERROR_INVALID_PARAMETER, the same errno: not a held file.
    (87, "win32", False),
    (None, "win32", False),
], ids=["user_mapped_file", "linux", "invalid_parameter", "errno_only"])
def test_a_file_another_handle_maps(winerror, platform, expected):
    assert is_file_in_use_error(_mapped(winerror), platform) is expected


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file mappings")
def test_a_copy_onto_a_mapped_file_counts_as_measured(tmp_path):
    import mmap
    import shutil
    src = tmp_path / "novo ç.pdf"
    dst = tmp_path / "mapeado ç.pdf"
    src.write_bytes(b"%PDF-1.4 novo " * 64)
    dst.write_bytes(b"%PDF-1.4 mapeado " * 64)
    with (open(dst, "rb") as fh,
          mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ),
          pytest.raises(OSError) as info):
        shutil.copy2(src, dst)
    assert info.value.winerror == 1224
    assert not isinstance(info.value, PermissionError)
    assert is_file_in_use_error(info.value) is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file locks")
def test_a_pdf_the_viewer_holds_is_refused_as_measured(tmp_path):
    """The real thing: PyMuPDF holds the file open, as the viewer does."""
    target = tmp_path / "no visualizador ç.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(target))
    doc.close()
    src = tmp_path / "novo.pdf"
    src.write_bytes(b"%PDF-1.4")
    held = pymupdf.open(str(target))
    try:
        with pytest.raises(PermissionError) as info:
            os.replace(src, target)
    finally:
        held.close()
    assert info.value.winerror == 5
    assert is_file_in_use_error(info.value) is True


def _boxes_shown(monkeypatch) -> list:
    """Every QMessageBox ``exec``'d: (icon, title, text, details)."""
    boxes = []

    def _exec(box):
        boxes.append((box.icon(), box.windowTitle(), box.text(), box.detailedText()))
        return 0
    monkeypatch.setattr(QMessageBox, "exec", _exec)
    return boxes


@pytest.mark.parametrize("platform, key, icon", [
    ("win32", "msg.file_in_use", QMessageBox.Icon.Warning),
    ("linux", "msg.unexpected", QMessageBox.Icon.Critical),
], ids=["windows", "elsewhere"])
def test_show_error_says_the_file_is_open(tmp_path, monkeypatch, platform, key, icon):
    held = tmp_path / "aberto ç.pdf"
    held.write_bytes(b"x")
    exc = _refused(5, str(tmp_path / "tmpab12.pdf"), str(held))
    monkeypatch.setattr(sys, "platform", platform)
    boxes = _boxes_shown(monkeypatch)

    utils.show_error(None, exc)

    assert [(b[0], b[2]) for b in boxes] == [(icon, t(key))]
    assert held.name in boxes[0][3], "the details name the file"


def test_the_file_in_use_log_has_the_os_fields_and_not_the_text(
        tmp_path, monkeypatch, caplog):
    held = tmp_path / "aberto ç.pdf"
    held.write_bytes(b"x")
    temp = str(tmp_path / "tmpab12.pdf")
    text = "texto que não vai para o registo"
    exc = PermissionError(errno.EACCES, text, temp, None, str(held))
    exc.winerror = 32
    monkeypatch.setattr(sys, "platform", "win32")
    boxes = _boxes_shown(monkeypatch)

    with caplog.at_level(logging.WARNING):
        utils.show_error(None, exc)

    logged = [r.getMessage() for r in caplog.records]
    assert len(logged) == 1, logged
    assert logged[0].startswith("File in use: ")
    assert text not in logged[0]
    assert f"errno={errno.EACCES} winerror=32 " in logged[0]
    assert repr(temp) in logged[0] and repr(str(held)) in logged[0]
    # What the user is shown keeps the whole exception.
    assert [b[2] for b in boxes] == [t("msg.file_in_use")]
    assert text in boxes[0][3] and held.name in boxes[0][3]


def test_the_file_in_use_message_is_in_every_language():
    import json
    path = Path(__file__).resolve().parent.parent / "app" / "translations.json"
    langs = json.loads(path.read_text(encoding="utf-8"))
    texts = {lang: keys.get("msg.file_in_use", "") for lang, keys in langs.items()}
    assert len(texts) == 8 and all(text.strip() for text in texts.values()), texts
    assert len(set(texts.values())) == len(texts), "one text per language"
    assert not any(chr(0x2014) in text for text in texts.values())
    assert all(set(keys) == set(langs["en"]) for keys in langs.values())
    # It is shown for a refused read too, and in tools whose output field
    # is hidden: no "replace", no "save it under another name".
    wrong = {lang: [w for w in _NO_SUCH_REMEDY[lang] if w in text.lower()]
             for lang, text in texts.items()}
    assert set(wrong) == set(_NO_SUCH_REMEDY)
    assert all(found == [] for found in wrong.values()), wrong


# Lower case, per language: "replace" and "another name".
_NO_SUCH_REMEDY = {
    "en": ("replac", "another name"),
    "pt": ("substitu", "outro nome"),
    "es": ("reemplaz", "otro nombre"),
    "fr": ("remplac", "autre nom"),
    "de": ("ersetz", "anderen namen"),
    "zh": ("替换", "其他名称"),
    "it": ("sostitu", "altro nome"),
    "nl": ("vervang", "andere naam"),
}


@contextlib.contextmanager
def _held_by_another_program(path: str):
    """``path`` open with no sharing at all, as some programs hold a file."""
    import ctypes.wintypes
    wintypes = ctypes.wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    generic_read, open_existing = 0x80000000, 3
    handle = k32.CreateFileW(path, generic_read, 0, None, open_existing, 0, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        k32.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows share modes")
@pytest.mark.parametrize("lang", ["en", "pt"])
def test_a_split_input_another_program_holds_says_so(env, monkeypatch, lang):
    """Measured: Split's input held with no sharing. The read is refused
    (PermissionError, no Win32 code), and the message said Windows would
    not let it replace the file and to save it under another name."""
    monkeypatch.setattr("app.i18n._LANG", lang)
    spec = SPECS["split"]
    page = env.make(spec)
    page.drop_in.set_path(env.a)
    folder = os.path.dirname(env.a)
    assert _same(page.drop_out.path(), folder)
    refused = []

    def _show_error(parent, exc):
        refused.append(exc)
        utils.show_error(parent, exc)
    monkeypatch.setattr("app.tools.split.show_error", _show_error)
    boxes = _boxes_shown(monkeypatch)

    with _held_by_another_program(env.a):
        spec.before_run(page, env)
        page._run()

    assert [type(e) for e in refused] == [PermissionError]
    assert refused[0].winerror is None and _same(refused[0].filename, env.a)
    assert [(b[0], b[1], b[2]) for b in boxes] == \
        [(QMessageBox.Icon.Warning, t("msg.warning"), t("msg.file_in_use"))]
    assert [w for w in _NO_SUCH_REMEDY[lang] if w in boxes[0][2].lower()] == []
    assert os.path.basename(env.a) in boxes[0][3]
    assert os.listdir(folder) == [os.path.basename(env.a)]
    assert env.warnings == [] and env.infos == []


def _rotate(win) -> TabRotar:
    return next(w for w in (win.stack.widget(i) for i in range(win.stack.count()))
                if isinstance(w, TabRotar))


def _close_tab_button(win, viewer, temp) -> None:
    win._tab_bar.tabCloseRequested.emit(win._viewers.index(viewer))


def _toast_button(win, viewer, temp) -> None:
    from PySide6.QtWidgets import QPushButton
    page = _rotate(win)
    page._show_toast("ok", temp, with_save=True)
    page._toast_widget.findChild(QPushButton, "toast_save").click()


def _ctrl_s(win, viewer, temp) -> None:
    from PySide6.QtGui import QKeySequence, QShortcut
    (shortcut,) = [s for s in win.findChildren(QShortcut)
                   if s.key() == QKeySequence("Ctrl+S")]
    shortcut.activated.emit()


_GESTURES = {"close_tab": _close_tab_button, "toast": _toast_button,
             "ctrl_s": _ctrl_s}


@pytest.mark.parametrize("gesture, tabs", [
    ("close_tab", "one_tab"),
    ("close_tab", "two_tabs"),
    ("toast", "one_tab"),
    ("ctrl_s", "one_tab"),
])
def test_a_save_the_original_refuses_is_shown_and_keeps_all(
        request, env, monkeypatch, gesture, tabs):
    """Saved over the original, which a viewer holds: the error reached
    ``sys.excepthook`` as an unexpected one from these three. It is shown
    as the close prompt's was, and nothing is lost."""
    win, viewer, temp = request.getfixturevalue(tabs)
    _answer_close_prompt(monkeypatch, "Save")
    shown = _errors_shown(monkeypatch)
    hooked = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc_info: hooked.append(exc_info[0]))
    before = Path(env.a).read_bytes()
    tabs_before = win._tab_bar.count()
    _failing_replace_onto(monkeypatch, env.a)
    saves = _dialogs(monkeypatch, env.a)

    _GESTURES[gesture](win, viewer, temp)

    assert hooked == []
    assert [type(e) for e in shown] == [PermissionError]
    assert len(saves) == 1
    assert win._tab_bar.count() == tabs_before
    assert any(v is viewer for v in win._viewers)
    assert Path(env.a).read_bytes() == before
    assert os.listdir(os.path.dirname(env.a)) == [os.path.basename(env.a)]
    _assert_kept(win, viewer, temp)


def test_the_user_reads_that_the_file_is_open(env, monkeypatch, one_tab):
    """End to end, the real ``show_error``: what Ctrl+S shows on Windows."""
    win, viewer, temp = one_tab
    monkeypatch.setattr(sys, "platform", "win32")
    boxes = _boxes_shown(monkeypatch)
    _failing_replace_onto(monkeypatch, env.a)
    _dialogs(monkeypatch, env.a)

    _ctrl_s(win, viewer, temp)

    assert [(b[0], b[1], b[2]) for b in boxes] == \
        [(QMessageBox.Icon.Warning, t("msg.warning"), t("msg.file_in_use"))]
    _assert_kept(win, viewer, temp)
