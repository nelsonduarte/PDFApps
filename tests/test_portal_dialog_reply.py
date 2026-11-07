"""What a file dialog answers is checked before anything is written.

Measured on the snap of 1.15.3, Ubuntu 26.04.1. With the session bus out of
reach Qt uses its own dialog, which opens in ``doc/<id>`` of a shared PDF, and
accepting it said "saved" with nothing on the host. With the portal, a leftover
file of the derived name in that folder made Qt send it as ``current_file``:
the dialog proposed the original, and accepting replaced the PDF with the
tool's output (a TXT, a DOCX), while the app said it worked.

Doc paths are simulated as in ``test_portal_phantom``: real files in a folder
of the test, translated just for the rule. The real tools and dialogs helpers
run, and a reply really gets written.
"""

import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from app import portal as portal_mod
from app.i18n import t
from app.pdf_io import check_not_same_path
from app.portal import (
    portal_free_suggestion,
    portal_rejects_folder,
    portal_rejects_saved_file,
)
from app.tools.import_pdf import TabImport
from app.utils import ask_save_path
from test_overwrite_characterization import (  # noqa: F401
    SPECS,
    _close_window,
    _import_pick_files,
    _import_sources,
    _load,
    _no_setup,
    _out,
    _params,
    _run,
    _same,
    _window,
    _written,
    env,
)
from test_portal_phantom import (  # noqa: F401
    _DOC,
    _SOURCE,
    _UID,
    _convert_spec,
    _dialogs,
    _pick_for,
    portal,
    uid,
)

_FILE_SPECS = [s.id for s in SPECS.values() if not s.folder]
# The editor and Compress may write over their input, as may the pipeline's
# Save as: their output is still that document (the user's decision on A-1).
_REPLACING = ["editor", "compress"]
_REFUSING = [i for i in _FILE_SPECS if i not in _REPLACING]
_FOLDER_SPECS = [s.id for s in SPECS.values() if s.folder]


def _portal_warning():
    return (t("msg.warning"), t("tool.err.portal_output"))


def _own_input_warning():
    return (t("msg.warning"), t("tool.err.same_source_output"))


def _listing_of(*names):
    return lambda _folder: list(names)


def _unreadable(_folder):
    raise OSError(5, "Input/output error")


# -- the rule on a Save dialog's answer --------------------------------------


@pytest.mark.parametrize("reply, inputs, listdir, refused", [
    # In the doc folder of an input only that very file is real, and a
    # leftover of that name does not make it so.
    (f"{_DOC}/ab12/x.pdf", [f"{_DOC}/ab12/a.pdf"], _listing_of("a.pdf"), True),
    (f"{_DOC}/ab12/x.pdf", [f"{_DOC}/ab12/a.pdf"], _listing_of("a.pdf", "x.pdf"), True),
    # Knowing the input settles it, whatever the folder lists or fails to.
    (f"{_DOC}/ab12/x.pdf", [f"{_DOC}/ab12/a.pdf"], _listing_of("x.pdf"), True),
    (f"{_DOC}/ab12/x.pdf", [f"{_DOC}/ab12/a.pdf"], _listing_of(), True),
    (f"{_DOC}/ab12/x.pdf", [f"{_DOC}/ab12/a.pdf"], _unreadable, True),
    (f"{_DOC}/ab12/a.pdf", [f"{_DOC}/ab12/a.pdf"], _listing_of("a.pdf"), False),
    (f"/{_DOC}/ab12/./a.pdf", [f"{_DOC}/ab12/a.pdf"], _listing_of("a.pdf"), False),
    # An input below a folder grant: the id's own children are still no file.
    (f"{_DOC}/ab12/x.pdf", [f"{_DOC}/ab12/pasta/a.pdf"], _listing_of("pasta"), True),
    (f"{_DOC}/ab12/pasta/x.pdf", [f"{_DOC}/ab12/pasta/a.pdf"], _unreadable, False),
    # The id itself, which accepting the fallback's folder returns.
    (f"{_DOC}/ab12", [], _listing_of("a.pdf"), True),
    (f"{_DOC}/ab12/", [f"{_DOC}/ab12/a.pdf"], _listing_of("a.pdf"), True),
    # A new file through the portal: an id of its own.
    (f"{_DOC}/cd34/x.pdf", [f"{_DOC}/ab12/a.pdf"], _listing_of(), False),
    (f"{_DOC}/cd34/x.pdf", [f"{_DOC}/ab12/a.pdf"], _listing_of("x.pdf"), False),
    (f"{_DOC}/cd34/x.pdf", [f"{_DOC}/ab12/a.pdf"], _unreadable, False),
    (f"{_DOC}/cd34/x.pdf", [], _listing_of(), False),
    # The fallback navigated to another shared file and typed a new name.
    (f"{_DOC}/cd34/x.pdf", [f"{_DOC}/ab12/a.pdf"], _listing_of("c.pdf"), True),
    (f"{_DOC}/cd34/x.pdf", [], _listing_of("c.pdf"), True),
    # One id per file: with two names at most one is real, and nothing says
    # which, so a leftover cannot pass as the shared file.
    (f"{_DOC}/cd34/x.pdf", [f"{_DOC}/ab12/a.pdf"], _listing_of("c.pdf", "x.pdf"), True),
    (f"{_DOC}/cd34/x.pdf", [], _listing_of("x.pdf", "c.pdf"), True),
    # The input itself is what the caller decides on, leftovers or not.
    (f"{_DOC}/ab12/a.pdf", [f"{_DOC}/ab12/a.pdf"], _listing_of("a.pdf", "x.pdf"), False),
    # The blind spot: the shared file gone, only a leftover or nothing there.
    (f"{_DOC}/cd34/x.pdf", [], _listing_of("x.pdf"), False),
    # Below a folder grant, and everywhere else.
    (f"{_DOC}/cd34/pasta/x.pdf", [], _unreadable, False),
    ("/home/u/x.pdf", [f"{_DOC}/ab12/a.pdf"], _unreadable, False),
    (f"/run/user/{_UID + 1}/doc/ab12/x.pdf", [], _unreadable, False),
    ("", [], _unreadable, False),
])
def test_save_answer(uid, reply, inputs, listdir, refused):
    assert portal_rejects_saved_file(reply, inputs, listdir=listdir) is refused


def test_save_answer_takes_any_iterable_of_inputs(uid):
    inputs = iter([f"{_DOC}/ab12/a.pdf"])
    assert portal_rejects_saved_file(f"{_DOC}/ab12/x.pdf", inputs,
                                     listdir=_unreadable) is True


@pytest.mark.parametrize("reply, isdir, refused", [
    (f"{_DOC}/ab12", True, True),
    (f"{_DOC}/ab12/", True, True),
    (f"/{_DOC}/ab12", True, True),
    # Measured real: /doc/63dd77b/c5 and /doc/e6f4c9ae/o.
    (f"{_DOC}/63dd77b/c5", True, False),
    (f"{_DOC}/63dd77b/c5", False, True),
    (f"{_DOC}/63dd77b/c5/sub", False, False),
    ("/home/u/pasta", False, False),
    ("", False, False),
])
def test_folder_answer(uid, reply, isdir, refused):
    assert portal_rejects_folder(reply, isdir=lambda _p: isdir) is refused


def test_a_platform_without_a_uid_refuses_nothing(monkeypatch):
    monkeypatch.setattr(portal_mod, "_current_uid", lambda: None)
    assert not portal_rejects_saved_file(f"{_DOC}/ab12", [], listdir=_unreadable)
    assert not portal_rejects_folder(f"{_DOC}/ab12")


# -- what the dialog is told to suggest --------------------------------------


def _existing(*paths):
    return lambda p: p in paths


@pytest.mark.parametrize("suggested, taken, expected", [
    (f"{_DOC}/ab12/x.pdf", [], f"{_DOC}/ab12/x.pdf"),
    (f"{_DOC}/ab12/x.pdf", [f"{_DOC}/ab12/x.pdf"], f"{_DOC}/ab12/x (1).pdf"),
    (f"{_DOC}/ab12/x.pdf", [f"{_DOC}/ab12/x.pdf", f"{_DOC}/ab12/x (1).pdf"],
     f"{_DOC}/ab12/x (2).pdf"),
    (f"{_DOC}/ab12/x", [f"{_DOC}/ab12/x"], f"{_DOC}/ab12/x (1)"),
    (f"/{_DOC}/ab12/x.pdf", [f"{_DOC}/ab12/x.pdf"], f"{_DOC}/ab12/x (1).pdf"),
    # Below a grant, or outside the portal, current_file means what it says.
    (f"{_DOC}/ab12/pasta/x.pdf", [f"{_DOC}/ab12/pasta/x.pdf"], f"{_DOC}/ab12/pasta/x.pdf"),
    ("/home/u/x.pdf", ["/home/u/x.pdf"], "/home/u/x.pdf"),
    (f"{_DOC}/ab12", [f"{_DOC}/ab12"], f"{_DOC}/ab12"),
    ("x.pdf", ["x.pdf"], "x.pdf"),
    ("", [""], ""),
])
def test_suggestion(uid, suggested, taken, expected):
    assert portal_free_suggestion(suggested, exists=_existing(*taken)) == expected


def test_suggestion_with_every_name_taken_keeps_the_folder(uid):
    """No name then, but no current_file either."""
    assert portal_free_suggestion(f"{_DOC}/ab12/x.pdf",
                                  exists=lambda _p: True) == f"{_DOC}/ab12"


# -- the helper's contract ---------------------------------------------------


def test_ask_save_path_outside_the_portal_passes_everything_through(
        env, monkeypatch, tmp_path):
    existing = tmp_path / "existe.pdf"
    existing.write_bytes(b"x")
    asked = _dialogs(monkeypatch, str(existing))

    assert ask_save_path(None, "c", str(existing), "f") == str(existing)
    assert asked == [str(existing)]
    assert env.warnings == []


def test_ask_save_path_cancel_says_nothing(env, monkeypatch):
    _dialogs(monkeypatch, "")
    assert ask_save_path(None, "c", "x.pdf", "f") == ""
    assert env.warnings == []


# -- C2: every Save dialog that can hand over a phantom ----------------------


def _assert_refused(env, page, spec, src):
    field = getattr(page, spec.out_attr)
    assert field._chosen_path == ""
    assert os.listdir(os.path.dirname(src)) == [os.path.basename(src)]
    assert env.warnings == [_portal_warning()]
    assert env.infos == []
    assert env.compress_calls == [] and env.ocr_langs == []


@pytest.mark.parametrize("spec", _params(_FILE_SPECS))
@pytest.mark.parametrize("derived", [True, False], ids=["suggestion", "typed"])
def test_answer_in_the_input_doc_writes_nothing(env, portal, spec, derived, monkeypatch):
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    reply = spec.out(src) if derived else portal.path("ab12cd34", "x" + os.path.splitext(spec.out(src))[1])
    asked = _dialogs(monkeypatch, reply)

    _run(page, spec, env)

    assert len(asked) == 1, asked
    _assert_refused(env, page, spec, src)
    assert getattr(page, spec.out_attr).is_portal_phantom()

    # Today the second run did not even ask, and wrote again.
    _run(page, spec, env)
    assert len(asked) == 2, asked
    assert os.listdir(os.path.dirname(src)) == [_SOURCE]


@pytest.mark.parametrize("spec", _params(_FILE_SPECS))
def test_answer_naming_a_leftover_in_the_input_doc_writes_nothing(
        env, portal, spec, monkeypatch):
    """The leftover is listed, so only knowing the input can tell it from
    the shared file."""
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    leftover = spec.out(src)
    open(leftover, "wb").close()
    _dialogs(monkeypatch, leftover)

    _run(page, spec, env)

    assert os.path.getsize(leftover) == 0
    assert env.warnings == [_portal_warning()]
    assert env.infos == []
    assert getattr(page, spec.out_attr)._chosen_path == ""


@pytest.mark.parametrize("spec", _params(["rotate", "convert_txt", "editor"]))
def test_field_button_refuses_a_leftover_beside_the_input(env, portal, spec, monkeypatch):
    """The field does not know the input and the name is listed. Accepted, it
    would count as granted and every later run would write to the leftover."""
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    leftover = spec.out(src)
    open(leftover, "wb").close()
    _dialogs(monkeypatch, leftover)

    getattr(page, spec.out_attr).btn.click()

    assert getattr(page, spec.out_attr)._chosen_path == ""
    assert env.warnings == [_portal_warning()]
    assert os.path.getsize(leftover) == 0


def test_answer_naming_a_leftover_in_another_doc_writes_nothing(env, portal, monkeypatch):
    spec = SPECS["rotate"]
    src = portal.share(env.a, _SOURCE)
    other = portal.share(env.b, "b.pdf", "cd34cd34")
    leftover = portal.path("cd34cd34", "x.pdf")
    open(leftover, "wb").close()
    before = Path(other).read_bytes()
    page = env.make(spec)
    _load(page, spec, src)
    _dialogs(monkeypatch, leftover)

    _run(page, spec, env)

    assert os.path.getsize(leftover) == 0
    assert Path(other).read_bytes() == before
    assert env.warnings == [_portal_warning()]
    assert env.infos == []
    assert page.drop_out._chosen_path == ""


def test_refused_answer_leaves_an_empty_field_empty(env, portal, monkeypatch):
    spec = SPECS["rotate"]
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    page.drop_out.clear()
    _dialogs(monkeypatch, spec.out(src))

    _run(page, spec, env)

    assert page.drop_out.path() == ""
    _assert_refused(env, page, spec, src)


@pytest.mark.parametrize("spec", _params(["rotate", "convert_txt", "editor"]))
def test_field_button_refuses_it_too(env, portal, spec, monkeypatch):
    """The field does not know the input: the doc's listing decides."""
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    before = _out(page, spec)
    _dialogs(monkeypatch, spec.out(src))

    getattr(page, spec.out_attr).btn.click()

    assert _out(page, spec) == before
    assert getattr(page, spec.out_attr)._chosen_path == ""
    assert env.warnings == [_portal_warning()]


def test_choose_another_name_refuses_a_phantom(env, portal, monkeypatch):
    spec = SPECS["convert_txt"]
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    first = portal.path("ef56ab78", "plain.txt")
    open(first, "w", encoding="utf-8").close()
    _dialogs(monkeypatch, first)
    page._drop_file.btn.click()
    _run(page, spec, env)
    phantom = portal.path("ab12cd34", "outro.txt")
    asked = _dialogs(monkeypatch, phantom)
    monkeypatch.setattr(page, "_ask_overwrite",
                        lambda *a, **k: page.OVERWRITE_RENAME)

    _run(page, spec, env)

    assert len(asked) == 1
    assert env.warnings == [_portal_warning()]
    assert os.listdir(os.path.dirname(src)) == [_SOURCE]
    assert _same(_out(page, spec), first)


def _pipeline_window(env, monkeypatch, original, content=b"pipeline result"):
    win = _window(monkeypatch, env.tmp)
    temp = env.tmp / "pipeline result.pdf"
    temp.write_bytes(content)
    win._pipeline_state[id(win._viewer)] = {
        "original_path": original, "temp_path": str(temp)}
    return win


def _pipeline_has_result(win) -> bool:
    return bool(win._pipeline_state.get(id(win._viewer), {}).get("temp_path"))


def _assert_pipeline_saved_over(env, win, src):
    """``src`` now holds the result ``_pipeline_window`` got (``env.b``)."""
    assert Path(src).read_bytes() == Path(env.b).read_bytes()
    assert env.warnings == []
    assert not _pipeline_has_result(win)
    assert _same(win._viewer.current_path(), src)


@pytest.mark.parametrize("name", ["alfa ç_edited.pdf", "x.pdf"])
def test_pipeline_answer_in_the_input_doc_writes_nothing(
        env, portal, monkeypatch, qtbot, name):
    src = portal.share(env.a, _SOURCE)
    win = _pipeline_window(env, monkeypatch, src)
    try:
        asked = _dialogs(monkeypatch, portal.path("ab12cd34", name))
        win._save_pipeline()
        assert len(asked) == 1
        assert os.listdir(os.path.dirname(src)) == [_SOURCE]
        assert env.warnings == [_portal_warning()]
        assert _pipeline_has_result(win), "the result must stay to try again"
        assert win._viewer.current_path() == ""
    finally:
        _close_window(win, qtbot, env.tmp)


# -- C2: folders -------------------------------------------------------------


@pytest.mark.parametrize("spec", _params(_FOLDER_SPECS))
def test_the_doc_folder_answer_is_refused(env, portal, spec, monkeypatch):
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    asked = _dialogs(monkeypatch, os.path.dirname(src))

    _run(page, spec, env)

    assert len(asked) == 1, asked
    _assert_refused(env, page, spec, src)
    assert getattr(page, spec.out_attr).is_portal_phantom()


def test_another_ids_doc_folder_answer_is_refused(env, portal, monkeypatch):
    spec = SPECS["split"]
    src = portal.share(env.a, _SOURCE)
    other = os.path.dirname(portal.share(env.b, "b.pdf", "cd34cd34"))
    page = env.make(spec)
    _load(page, spec, src)
    _dialogs(monkeypatch, other)

    _run(page, spec, env)

    assert os.listdir(other) == ["b.pdf"]
    assert env.warnings == [_portal_warning()]


@pytest.mark.parametrize("spec", _params(_FOLDER_SPECS))
def test_folder_button_refuses_it_too(env, portal, spec, monkeypatch):
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    _dialogs(monkeypatch, os.path.dirname(src))

    getattr(page, spec.out_attr).btn.click()

    assert getattr(page, spec.out_attr)._chosen_path == ""
    assert env.warnings == [_portal_warning()]


def test_choose_another_folder_refuses_the_doc_folder(env, portal, monkeypatch):
    spec = SPECS["convert_png"]
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    pick = _pick_for(portal, spec)
    _dialogs(monkeypatch, pick)
    page._drop_folder.btn.click()
    _run(page, spec, env)
    assert _written(pick)
    asked = _dialogs(monkeypatch, os.path.dirname(src))
    monkeypatch.setattr(page, "_ask_overwrite",
                        lambda *a, **k: page.OVERWRITE_RENAME)

    _run(page, spec, env)

    assert len(asked) == 1
    assert env.warnings == [_portal_warning()]
    assert os.listdir(os.path.dirname(src)) == [_SOURCE]
    assert _same(_out(page, spec), pick)


# -- real grants keep working ------------------------------------------------


@pytest.mark.parametrize("spec", _params(_FILE_SPECS + _FOLDER_SPECS))
def test_real_grant_is_written(env, portal, spec, monkeypatch):
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    pick = _pick_for(portal, spec)
    asked = _dialogs(monkeypatch, pick)

    _run(page, spec, env)

    assert len(asked) == 1
    assert env.warnings == []
    assert _written(spec.produced(pick))
    assert not getattr(page, spec.out_attr).is_portal_phantom()


def test_folder_grant_in_the_inputs_own_id_is_written(env, portal, monkeypatch):
    """The input's folder is below a grant: real, though the field's rule
    could not tell, and the picker hands it back."""
    spec = SPECS["split"]
    src = portal.share(env.a, _SOURCE, os.path.join("ab12cd34", "pasta"))
    page = env.make(spec)
    _load(page, spec, src)
    assert getattr(page, spec.out_attr).is_portal_phantom()
    _dialogs(monkeypatch, os.path.dirname(src))
    monkeypatch.setattr(page, "_ask_overwrite",
                        lambda *a, **k: pytest.fail("no clash here"),
                        raising=False)

    _run(page, spec, env)

    assert env.warnings == []
    assert _written(spec.produced(os.path.dirname(src)))


def test_saving_again_over_a_previous_real_file_is_written(env, portal, monkeypatch):
    """The portal hands the same id back for the same file: measured with
    /doc/c762858/reg.pdf."""
    spec = SPECS["rotate"]
    src = portal.share(env.a, _SOURCE)
    previous = portal.share(env.b, "reg.pdf", "c762858")
    page = env.make(spec)
    _load(page, spec, src)
    _dialogs(monkeypatch, previous)

    _run(page, spec, env)

    assert env.warnings == []
    assert os.listdir(os.path.dirname(previous)) == ["reg.pdf"]
    assert env.infos


def test_pipeline_answer_naming_a_leftover_in_the_input_doc_writes_nothing(
        env, portal, monkeypatch, qtbot):
    src = portal.share(env.a, _SOURCE)
    leftover = portal.path("ab12cd34", "x.pdf")
    open(leftover, "wb").close()
    win = _pipeline_window(env, monkeypatch, src)
    try:
        _dialogs(monkeypatch, leftover)
        win._save_pipeline()
        assert os.path.getsize(leftover) == 0
        assert env.warnings == [_portal_warning()]
    finally:
        _close_window(win, qtbot, env.tmp)


def test_pipeline_real_grant_is_written(env, portal, monkeypatch, qtbot):
    src = portal.share(env.a, _SOURCE)
    win = _pipeline_window(env, monkeypatch, src, Path(env.b).read_bytes())
    try:
        pick = portal.path("ef56ab78", "guardado ç.pdf")
        _dialogs(monkeypatch, pick)
        win._save_pipeline()
        assert env.warnings == []
        assert Path(pick).read_bytes() == Path(env.b).read_bytes()
        assert not _pipeline_has_result(win)
    finally:
        _close_window(win, qtbot, env.tmp)


# -- C1: the original is never what the dialog proposes ----------------------


@pytest.mark.parametrize("spec", _params(_FILE_SPECS))
def test_a_leftover_is_not_what_the_dialog_is_told(env, portal, spec, monkeypatch):
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    leftover = spec.out(src)
    open(leftover, "w", encoding="utf-8").close()
    asked = _dialogs(monkeypatch)

    _run(page, spec, env)

    assert len(asked) == 1, asked
    # Qt sends current_file only for a path that exists.
    assert not os.path.lexists(asked[0])
    # current_folder and the name, as with no leftover.
    assert _same(os.path.dirname(asked[0]), os.path.dirname(src))
    stem, ext = os.path.splitext(leftover)
    assert _same(asked[0], f"{stem} (1){ext}")


@pytest.mark.parametrize("spec", _params(_FILE_SPECS))
def test_no_leftover_means_the_exact_derived_name(env, portal, spec, monkeypatch):
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    asked = _dialogs(monkeypatch)

    _run(page, spec, env)

    assert len(asked) == 1
    assert _same(asked[0], spec.out(src))


@pytest.mark.parametrize("spec", _params(_FOLDER_SPECS))
def test_a_folder_picker_still_opens_in_the_doc_folder(env, portal, spec, monkeypatch):
    """From there the portal opens the real folder (measured)."""
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    asked = _dialogs(monkeypatch)

    _run(page, spec, env)

    assert _same(asked[0], os.path.dirname(src))


def test_pipeline_suggestion_avoids_a_leftover(env, portal, monkeypatch, qtbot):
    src = portal.share(env.a, _SOURCE)
    leftover = portal.path("ab12cd34", "relatório ç_edited.pdf")
    open(leftover, "wb").close()
    win = _pipeline_window(env, monkeypatch, src)
    try:
        asked = _dialogs(monkeypatch)
        win._save_pipeline()
        assert len(asked) == 1
        assert not os.path.lexists(asked[0])
        assert _same(asked[0], portal.path("ab12cd34", "relatório ç_edited (1).pdf"))
    finally:
        _close_window(win, qtbot, env.tmp)


def test_an_existing_file_outside_the_portal_is_still_suggested(env, monkeypatch):
    spec = SPECS["rotate"]
    page = env.make(spec)
    _load(page, spec, env.a)
    derived = spec.out(env.a)
    page.drop_out.clear()
    Path(derived).write_bytes(b"do utilizador")
    asked = _dialogs(monkeypatch)

    _run(page, spec, env)

    assert _same(asked[0], derived)


# -- writing over the input --------------------------------------------------


def _assert_input_kept(env, src, before):
    assert Path(src).read_bytes() == before
    assert env.warnings == [_own_input_warning()]
    assert env.infos == []
    assert env.compress_calls == [] and env.ocr_langs == []


@pytest.mark.parametrize("spec", _params(_REFUSING))
def test_answer_naming_the_input_replaces_nothing_in_the_portal(
        env, portal, spec, monkeypatch):
    src = portal.share(env.a, _SOURCE)
    before = Path(src).read_bytes()
    page = env.make(spec)
    _load(page, spec, src)
    derived = _out(page, spec)
    _dialogs(monkeypatch, src)

    _run(page, spec, env)

    _assert_input_kept(env, src, before)
    assert _out(page, spec) == derived
    assert getattr(page, spec.out_attr)._chosen_path == ""
    assert os.listdir(os.path.dirname(src)) == [_SOURCE]


@pytest.mark.parametrize("spec", _params(_REFUSING))
def test_answer_naming_the_input_with_a_leftover_beside_it(env, portal, spec, monkeypatch):
    """The rule has to know the input for the warning to say what happened:
    the folder is fine, it is this file that must not be replaced."""
    src = portal.share(env.a, _SOURCE)
    before = Path(src).read_bytes()
    page = env.make(spec)
    _load(page, spec, src)
    open(spec.out(src), "wb").close()
    _dialogs(monkeypatch, src)

    _run(page, spec, env)

    _assert_input_kept(env, src, before)


def test_pipeline_answer_naming_the_input_with_a_leftover_beside_it(
        env, portal, monkeypatch, qtbot):
    """The input is the one real file of its doc folder, whatever else the
    folder lists: replacing it is the user's choice, and it reaches the host."""
    src = portal.share(env.a, _SOURCE)
    leftover = portal.path("ab12cd34", "alfa_edited.pdf")
    open(leftover, "wb").close()
    win = _pipeline_window(env, monkeypatch, src, Path(env.b).read_bytes())
    try:
        _dialogs(monkeypatch, src)
        assert win._save_pipeline() is True
        _assert_pipeline_saved_over(env, win, src)
        assert sorted(os.listdir(os.path.dirname(src))) == sorted(
            [_SOURCE, os.path.basename(leftover)])
    finally:
        _close_window(win, qtbot, env.tmp)


@pytest.mark.parametrize("spec", _params(_REFUSING))
def test_answer_naming_the_input_replaces_nothing_outside_the_portal(
        env, spec, monkeypatch):
    src = env.a
    before = Path(src).read_bytes()
    page = env.make(spec)
    _load(page, spec, src)
    getattr(page, spec.out_attr).clear()
    _dialogs(monkeypatch, src)

    _run(page, spec, env)

    _assert_input_kept(env, src, before)
    assert _out(page, spec) == ""


@pytest.mark.parametrize("spec", _params(_REFUSING))
def test_field_holding_the_input_replaces_nothing(env, spec, monkeypatch):
    src = env.a
    before = Path(src).read_bytes()
    page = env.make(spec)
    _load(page, spec, src)
    getattr(page, spec.out_attr).set_path(src)
    asked = _dialogs(monkeypatch)
    monkeypatch.setattr(page, "_ask_overwrite",
                        lambda *a, **k: pytest.fail("asked to replace the input"),
                        raising=False)

    _run(page, spec, env)

    assert asked == []
    _assert_input_kept(env, src, before)


@pytest.mark.parametrize("gesture", ["portal", "plain", "field"])
def test_compress_writes_over_its_input_when_told_to(env, portal, monkeypatch, gesture):
    """Compress may replace its input (A-1): the result is the same document,
    and ``_compress_pdf`` only replaces it once done reading it (see
    ``test_replace_own_input``). The stand-in records what it was given.
    Only the Save dialog may name the input (M-1): a field holding it, which
    no dialog chose, gets that dialog first."""
    spec = SPECS["compress"]
    src = portal.share(env.a, _SOURCE) if gesture == "portal" else env.a
    page = env.make(spec)
    _load(page, spec, src)
    if gesture == "field":
        page.drop_out.set_path(src)
    else:
        page.drop_out.clear()
    asked = _dialogs(monkeypatch, src)

    _run(page, spec, env)

    assert len(asked) == 1
    assert env.warnings == []
    assert [(_same(s, src), _same(d, src)) for s, d in env.compress_calls] == \
        [(True, True)]
    assert len(env.infos) == 1
    assert _same(_out(page, spec), src)


@pytest.mark.parametrize("gesture", ["field", "dialog"])
def test_merge_refuses_any_of_its_sources_before_reading_them(env, monkeypatch, gesture):
    """S-1: only ``paths[0]`` was checked up front; the second source was
    caught by the atomic write, after reading every file, as an error."""
    from app.tools.merge import TabJuntar
    target = env.b
    before = Path(target).read_bytes()
    page = env.make(SimpleNamespace(cls=TabJuntar, inline=False,
                                    before_load=_no_setup))
    page._on_drop([env.a, env.b])
    if gesture == "field":
        page.drop_out.set_path(target)
    asked = _dialogs(monkeypatch, target)

    page._run()

    assert len(asked) == (0 if gesture == "field" else 1)
    assert env.warnings == [_own_input_warning()]
    assert env.infos == []
    assert Path(target).read_bytes() == before


def test_watermark_refuses_its_mark_before_reading_it(env, monkeypatch):
    """S-1: the mark is an input too; it was caught only by the atomic write."""
    spec = SPECS["watermark"]
    before = Path(env.wm).read_bytes()
    page = env.make(spec)
    _load(page, spec, env.a)
    spec.before_run(page, env)
    page.drop_out.set_path(env.wm)
    asked = _dialogs(monkeypatch)

    page._run()

    assert asked == []
    assert env.warnings == [_own_input_warning()]
    assert env.infos == []
    assert Path(env.wm).read_bytes() == before


@pytest.mark.parametrize("spec", [
    pytest.param(_convert_spec(name, index, ext), id=name)
    for name, index, ext in (("docx", 2, ".docx"), ("pptx", 4, ".pptx"),
                             ("xlsx", 5, ".xlsx"), ("html", 6, ".html"),
                             ("epub", 7, ".epub"))])
def test_every_converter_format_refuses_the_input(env, spec, monkeypatch):
    """Measured with DOCX: the PDF became a ZIP, and the app said it worked."""
    before = Path(env.a).read_bytes()
    page = env.make(spec)
    _load(page, spec, env.a)
    page._drop_file.clear()
    _dialogs(monkeypatch, env.a)

    _run(page, spec, env)

    _assert_input_kept(env, env.a, before)


def test_a_hard_link_to_the_input_is_the_input(env, monkeypatch, tmp_path):
    spec = SPECS["convert_txt"]
    link = tmp_path / "outro nome.txt"
    os.link(env.a, link)
    before = Path(env.a).read_bytes()
    page = env.make(spec)
    _load(page, spec, env.a)
    page._drop_file.clear()
    _dialogs(monkeypatch, str(link))

    _run(page, spec, env)

    _assert_input_kept(env, env.a, before)


def test_same_path_check_with_no_file_at_the_destination(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    check_not_same_path(str(tmp_path / "novo.pdf"), [str(src)])


@pytest.mark.parametrize("in_portal", [True, False], ids=["portal", "plain"])
def test_choose_another_name_refuses_the_input(env, portal, monkeypatch, in_portal):
    spec = SPECS["convert_txt"]
    src = portal.share(env.a, _SOURCE) if in_portal else env.a
    before = Path(src).read_bytes()
    page = env.make(spec)
    _load(page, spec, src)
    first = portal.path("ef56ab78", "plain.txt")
    open(first, "w", encoding="utf-8").close()
    _dialogs(monkeypatch, first)
    page._drop_file.btn.click()
    _run(page, spec, env)
    _dialogs(monkeypatch, src)
    monkeypatch.setattr(page, "_ask_overwrite",
                        lambda *a, **k: page.OVERWRITE_RENAME)

    _run(page, spec, env)

    assert Path(src).read_bytes() == before
    assert env.warnings == [_own_input_warning()]
    assert _same(_out(page, spec), first)


def _import_page(env):
    return env.make(SimpleNamespace(cls=TabImport, inline=True,
                                    before_load=_no_setup))


@pytest.mark.parametrize("which", [0, 1], ids=["first_file", "second_file"])
def test_import_refuses_any_of_its_sources(env, monkeypatch, which):
    """Measured with one: t5.txt became a PDF. It reads them all."""
    sources = _import_sources(env)
    target = sources[which]
    before = Path(target).read_bytes()
    page = _import_page(env)
    _import_pick_files(page, monkeypatch, list(sources))
    page.drop_out.clear()
    _dialogs(monkeypatch, target)

    page._run()

    _assert_input_kept(env, target, before)


def test_import_refuses_its_source_in_the_portal(env, portal, monkeypatch):
    text, _ = _import_sources(env)
    src = portal.share(text, "t5.txt")
    before = Path(src).read_bytes()
    page = _import_page(env)
    _import_pick_files(page, monkeypatch, [src])
    _dialogs(monkeypatch, src)

    page._run()

    _assert_input_kept(env, src, before)
    assert os.listdir(os.path.dirname(src)) == ["t5.txt"]


def test_import_answer_in_the_source_doc_writes_nothing(env, portal, monkeypatch):
    text, _ = _import_sources(env)
    src = portal.share(text, "t5.txt")
    page = _import_page(env)
    _import_pick_files(page, monkeypatch, [src])
    _dialogs(monkeypatch, page.drop_out.path())

    page._run()

    assert env.warnings == [_portal_warning()]
    assert os.listdir(os.path.dirname(src)) == ["t5.txt"]


@pytest.mark.parametrize("in_portal", [True, False], ids=["portal", "plain"])
def test_pipeline_answer_naming_the_input_replaces_it(
        env, portal, monkeypatch, qtbot, in_portal):
    """The Save dialog asked before replacing, and the result is still that
    document: the user may want it in place of the original."""
    src = portal.share(env.a, _SOURCE) if in_portal else env.a
    win = _pipeline_window(env, monkeypatch, src, Path(env.b).read_bytes())
    try:
        _dialogs(monkeypatch, src)
        assert win._save_pipeline() is True
        _assert_pipeline_saved_over(env, win, src)
    finally:
        _close_window(win, qtbot, env.tmp)


def test_pipeline_outside_the_portal_saves_as_before(env, monkeypatch, qtbot):
    win = _pipeline_window(env, monkeypatch, env.a, Path(env.b).read_bytes())
    try:
        pick = str(env.tmp / "guardado.pdf")
        asked = _dialogs(monkeypatch, pick)
        win._save_pipeline()
        assert _same(asked[0], os.path.join(os.path.dirname(env.a),
                                            "alfa ç_edited.pdf"))
        assert env.warnings == []
        assert Path(pick).read_bytes() == Path(env.b).read_bytes()
        assert _same(win._viewer.current_path(), pick)
    finally:
        _close_window(win, qtbot, env.tmp)


# -- the editor keeps the choice ---------------------------------------------


def _note_count(path):
    with pymupdf.open(path) as doc:
        return len(list(doc[0].annots() or []))


@pytest.mark.parametrize("in_portal", [True, False], ids=["portal", "plain"])
def test_editor_applies_over_its_own_pdf_when_the_answer_says_so(
        env, portal, monkeypatch, in_portal):
    spec = SPECS["editor"]
    src = portal.share(env.a, _SOURCE) if in_portal else env.a
    tab = env.make(spec)
    _load(tab, spec, src)
    tab._drop_out.clear()
    asked = _dialogs(monkeypatch, src)
    assert _note_count(src) == 0

    _run(tab, spec, env)

    assert len(asked) == 1
    assert env.warnings == []
    assert _note_count(src) == 1
    assert len(env.infos) == 1


def test_editor_own_pdf_stays_a_choice_with_a_leftover_beside_it(env, portal, monkeypatch):
    """The dialog no longer proposes the original here (see the suggestion
    tests), so this answer is one the user picked, and a leftover in the doc
    does not make the open PDF any less real."""
    spec = SPECS["editor"]
    src = portal.share(env.a, _SOURCE)
    tab = env.make(spec)
    _load(tab, spec, src)
    leftover = spec.out(src)
    open(leftover, "wb").close()
    tab._drop_out.clear()
    asked = _dialogs(monkeypatch, src)

    _run(tab, spec, env)

    assert not os.path.lexists(asked[0])
    assert not _same(asked[0], src)
    assert env.warnings == []
    assert _note_count(src) == 1
    assert os.path.getsize(leftover) == 0


def test_editor_answer_naming_a_leftover_is_not_its_own_pdf(env, portal, monkeypatch):
    """Replacing the open PDF is a choice; a name beside it in the doc is
    not the file the choice is about."""
    spec = SPECS["editor"]
    src = portal.share(env.a, _SOURCE)
    tab = env.make(spec)
    _load(tab, spec, src)
    leftover = spec.out(src)
    open(leftover, "wb").close()
    _dialogs(monkeypatch, leftover)

    _run(tab, spec, env)

    assert os.path.getsize(leftover) == 0
    assert _note_count(src) == 0
    assert env.warnings == [_portal_warning()]


# -- nothing asks around the helpers -----------------------------------------


_OUTPUT_DIALOGS = ("getSaveFileName", "getSaveFileUrl",
                   "getExistingDirectory", "getExistingDirectoryUrl")


def _output_dialog_uses(tree):
    """(enclosing function or "", name) of each way to reach an output
    dialog: an attribute, a string for getattr, or a QFileDialog(...) of
    one's own, at any depth, async functions and module level included."""
    parents = {child: node for node in ast.walk(tree)
               for child in ast.iter_child_nodes(node)}
    for node in ast.walk(tree):
        name = ""
        if isinstance(node, ast.Attribute) and node.attr in _OUTPUT_DIALOGS:
            name = node.attr
        elif isinstance(node, ast.Constant) and node.value in _OUTPUT_DIALOGS:
            name = node.value
        elif isinstance(node, ast.Call):
            func = node.func
            called = getattr(func, "id", "") or getattr(func, "attr", "")
            if called == "QFileDialog":
                name = "QFileDialog"
        if not name:
            continue
        owner = parents.get(node)
        while owner is not None and not isinstance(
                owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = parents.get(owner)
        yield (owner.name if owner is not None else ""), name


def test_only_the_checked_helpers_open_an_output_dialog():
    """Any other call would hand its answer to the writers unchecked, and
    the portal only shows the result on the host, where no test here looks."""
    root = Path(portal_mod.__file__).parent
    paths = [*root.rglob("*.py"), root.parent / "pdfapps.py"]
    calls = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(root.parent).as_posix()
        calls.update((rel, *use) for use in _output_dialog_uses(tree))
    assert calls == {("app/utils.py", "ask_save_path", "getSaveFileName"),
                     ("app/utils.py", "ask_output_folder", "getExistingDirectory")}


@pytest.mark.parametrize("source", [
    "x = QFileDialog.getSaveFileUrl()",
    "async def f():\n    QtWidgets.QFileDialog(None)",
    "def f():\n    getattr(QFileDialog, 'getExistingDirectory')()",
    "class C:\n    d = QFileDialog.getExistingDirectoryUrl",
])
def test_the_dialog_guard_sees_every_way_in(source):
    assert list(_output_dialog_uses(ast.parse(source)))


# -- the message -------------------------------------------------------------


def test_the_message_is_in_every_language():
    path = Path(portal_mod.__file__).parent / "translations.json"
    catalogue = json.loads(path.read_text(encoding="utf-8"))
    texts = {lang: keys.get("tool.err.portal_output", "")
             for lang, keys in catalogue.items()}
    assert len(texts) == 8
    assert all(texts.values()), texts
    assert len(set(texts.values())) == 8, "an untranslated copy"
