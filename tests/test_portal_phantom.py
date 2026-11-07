"""An output the document portal would swallow goes through the Save dialog.

Measured on Ubuntu 26.04.1, xdg-desktop-portal 1.21.1, snap 1.15.2: a PDF
opened from a hidden folder, or from /run/media without removable-media,
arrives as ``/run/user/<uid>/doc/<id>/name.pdf``, one ``<id>`` per file. A
derived output in that folder reported success, left ``.xdp-<name>-XXXXXX``
behind and never reached the host. ``os.path.exists`` and ``os.replace`` do
not see it, so the path itself decides.

No test here can create ``/run/user`` on every platform, so the tool tests
keep real files in a folder of the test and translate that folder to the doc
path just for the check (``portal`` below): the real tools, the real funnel
and the real rule run, and a dialog's reply really gets written.
"""

import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QComboBox, QFileDialog, QLineEdit

from app import portal as portal_mod
from app.editor.tab import _MODE_FORMS
from app.i18n import t
from app.portal import (
    portal_free_suggestion,
    portal_phantom_output,
    portal_rejects_folder,
    portal_rejects_saved_file,
)
from app.tools.convert import TabConverter
from app.tools.encrypt import TabEncriptar
from app.tools.import_pdf import TabImport
from app.tools.merge import TabJuntar
from app.tools.ocr import TabOCR
from app.widgets import DropFileEdit
from test_overwrite_characterization import (  # noqa: F401
    SPECS,
    _STUCK_OUTPUT,
    _drop_on,
    _file_out,
    _folder_out,
    _import_pick_files,
    _import_sources,
    _label,
    _load,
    _no_setup,
    _out,
    _params,
    _run,
    _same,
    _spec,
    _written,
    env,
)

_UID = 1000
_DOC = f"/run/user/{_UID}/doc"
_ALL = list(SPECS)


# -- the rule ----------------------------------------------------------------


@pytest.fixture
def uid(monkeypatch):
    monkeypatch.setattr(portal_mod, "_current_uid", lambda: _UID)


@pytest.mark.parametrize("out, granted, expected", [
    # A direct child: real only under the granted name.
    (f"{_DOC}/ab12/foo.pdf", [], True),
    (f"{_DOC}/ab12/foo_rotated.pdf", [f"{_DOC}/ab12/foo.pdf"], True),
    (f"{_DOC}/ab12/foo.pdf", [f"{_DOC}/cd34/foo.pdf"], True),
    (f"{_DOC}/ab12/foo.pdf", [f"{_DOC}/ab12/foo.pdf"], False),
    (f"{_DOC}/ab12/./foo.pdf", [f"{_DOC}/ab12/foo.pdf"], False),
    (f"{_DOC}/ab12/foo.pdf", [f"{_DOC}/ab12//foo.pdf"], False),
    (f"{_DOC}/ab12/foo.pdf", ["", f"{_DOC}/ab12/foo.pdf"], False),
    (f"{_DOC}/ab12/foo.pdf", [""], True),
    # The doc folder itself: the parent of a shared file, never real.
    (f"{_DOC}/ab12", [], True),
    (f"{_DOC}/ab12/", [], True),
    (f"{_DOC}/ab12", [f"{_DOC}/ab12"], True),
    # Deeper is a folder grant, and it is real.
    (f"{_DOC}/ab12/pasta/x.pdf", [], False),
    (f"{_DOC}/ab12/pasta/sub/x.pdf", [], False),
    # Normalised before deciding, failing closed.
    (f"{_DOC}/ab12/../cd34/foo.pdf", [], True),
    (f"{_DOC}/ab12/pasta/../foo.pdf", [], True),
    # Two leading slashes: normpath keeps them, Linux reads them as one.
    (f"/{_DOC}/ab12/foo.pdf", [], True),
    (f"/{_DOC}/ab12", [], True),
    (f"/{_DOC}/ab12/foo.pdf", [f"{_DOC}/ab12/foo.pdf"], False),
    (f"{_DOC}/ab12/foo.pdf", [f"/{_DOC}/ab12/foo.pdf"], False),
    (f"/{_DOC}/ab12/pasta/x.pdf", [], False),
    (f"//{_DOC}/ab12/foo.pdf", [], True),
    ("//home/u/foo.pdf", [], False),
    # The mount itself or a look-alike: not a doc path.
    (_DOC, [], False),
    (f"{_DOC}/", [], False),
    (f"/run/user/{_UID}/document/ab12/foo.pdf", [], False),
    (f"/run/user/{_UID}/docs/ab12/foo.pdf", [], False),
    (f"/run/user/{_UID}/doc2/ab12/foo.pdf", [], False),
    ("/run/user/abc/doc/ab12/foo.pdf", [], False),
    ("/run/user//doc/ab12/foo.pdf", [], False),
    (f"/var/run/user/{_UID}/doc/ab12/foo.pdf", [], False),
    (f"run/user/{_UID}/doc/ab12/foo.pdf", [], False),
    (f"/home/u/run/user/{_UID}/doc/ab12/foo.pdf", [], False),
    # Another user's portal.
    (f"/run/user/{_UID + 1}/doc/ab12/foo.pdf", [], False),
    (f"/run/user/{_UID + 1}/doc/ab12", [], False),
    # Everywhere else.
    ("/home/u/foo.pdf", [], False),
    ("", [], False),
    ("foo.pdf", [], False),
    (r"C:\Users\u\foo.pdf", [], False),
    (rf"\\run\user\{_UID}\doc\ab12\foo.pdf", [], False),
    (rf"C:\run\user\{_UID}\doc\ab12\foo.pdf", [], False),
])
def test_rule(uid, out, granted, expected):
    assert portal_phantom_output(out, granted) is expected


def test_platform_without_a_uid_never_matches(monkeypatch):
    monkeypatch.setattr(portal_mod, "_current_uid", lambda: None)
    assert portal_phantom_output(f"{_DOC}/ab12/foo.pdf", []) is False
    assert portal_phantom_output(f"{_DOC}/ab12", []) is False


def test_uid_comes_from_getuid_when_there_is_one(monkeypatch):
    monkeypatch.setattr(os, "getuid", lambda: 4321, raising=False)
    assert portal_mod._current_uid() == 4321
    monkeypatch.delattr(os, "getuid")
    assert portal_mod._current_uid() is None


# -- the tools ---------------------------------------------------------------


class _Portal:
    def __init__(self, root):
        self.root = root

    def share(self, source: str, name: str, doc_id: str = "ab12cd34") -> str:
        """``source`` as the portal hands it over, in its own doc folder."""
        folder = self.root / doc_id
        folder.mkdir(parents=True, exist_ok=True)
        return str(shutil.copy(source, folder / name))

    def path(self, doc_id: str, *rest: str) -> str:
        folder = self.root / doc_id
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder.joinpath(*rest))


@pytest.fixture
def portal(monkeypatch, tmp_path):
    root = tmp_path / "docroot"
    root.mkdir()
    prefix = str(root).replace("\\", "/")

    def _doc_path(p: str) -> str:
        p = p.replace("\\", "/")
        return _DOC + p[len(prefix):] if p.startswith(prefix) else p

    def _real_path(p: str) -> str:
        return prefix + p[len(_DOC):] if p.startswith(_DOC) else p

    def _free_suggestion(suggested: str) -> str:
        doc = _doc_path(suggested)
        free = portal_free_suggestion(
            doc, exists=lambda p: os.path.lexists(_real_path(p)))
        return suggested if free == doc else _real_path(free)

    monkeypatch.setattr(portal_mod, "_current_uid", lambda: _UID)
    monkeypatch.setattr(
        "app.widgets.portal_phantom_output",
        lambda out, granted: portal_phantom_output(
            _doc_path(out), [_doc_path(g) for g in granted]))
    monkeypatch.setattr("app.utils.portal_free_suggestion", _free_suggestion)
    monkeypatch.setattr(
        "app.utils.portal_rejects_saved_file",
        lambda reply, inputs=(): portal_rejects_saved_file(
            _doc_path(reply), [_doc_path(i) for i in inputs],
            listdir=lambda folder: os.listdir(_real_path(folder))))
    monkeypatch.setattr(
        "app.utils.portal_rejects_folder",
        lambda reply: portal_rejects_folder(
            _doc_path(reply),
            isdir=lambda folder: os.path.isdir(_real_path(folder))))
    return _Portal(root)


def _dialogs(monkeypatch, reply: str = "") -> list:
    """Script both output dialogs; returns what each was asked to start at.
    The default reply is the user's cancel."""
    asked = []

    def _save(parent=None, caption="", directory="", *a, **k):
        asked.append(directory)
        return reply, ""

    def _folder(parent=None, caption="", directory="", *a, **k):
        asked.append(directory)
        return reply
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(_save))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(_folder))
    return asked


def _pick_for(portal, spec, doc_id="ef56ab78") -> str:
    """What the portal returns for a new output: a new id, granted."""
    if spec.folder:
        pick = portal.path(doc_id, "pasta real")
        os.makedirs(pick, exist_ok=True)
        return pick
    return portal.path(doc_id, "escolhido ç" + os.path.splitext(spec.out("x.pdf"))[1])


_SOURCE = "relatório ç.pdf"


@pytest.mark.parametrize("spec", _params(_ALL))
def test_derived_output_opens_the_dialog_with_the_derived_name(
        env, portal, spec, monkeypatch):
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    assert _same(_out(page, spec), spec.out(src))
    asked = _dialogs(monkeypatch)

    _run(page, spec, env)

    # In the doc folder: from there the portal opens the real folder.
    assert len(asked) == 1, asked
    assert _same(asked[0], spec.out(src))
    assert _same(_out(page, spec), spec.out(src))
    assert os.listdir(os.path.dirname(src)) == [_SOURCE]
    assert env.compress_calls == [] and env.ocr_langs == []
    assert env.statuses == [] or spec.id == "editor"


@pytest.mark.parametrize("spec", _params(_ALL))
def test_the_answer_of_that_dialog_is_written_with_no_more_questions(
        env, portal, spec, monkeypatch):
    src = portal.share(env.a, _SOURCE)
    before = Path(src).read_bytes()
    page = env.make(spec)
    _load(page, spec, src)
    pick = _pick_for(portal, spec)
    asked = _dialogs(monkeypatch, pick)

    _run(page, spec, env)

    assert len(asked) == 1, asked
    assert _same(_out(page, spec), pick)
    assert _written(spec.produced(pick))
    assert os.listdir(os.path.dirname(src)) == [_SOURCE]
    assert Path(src).read_bytes() == before
    # The teardown of env fails on an overwrite box or an error.


@pytest.mark.parametrize("spec", _params(["rotate", "extract", "split",
                                          "convert_png", "editor"]))
def test_the_next_run_keeps_that_answer(env, portal, spec, monkeypatch):
    page = env.make(spec)
    _load(page, spec, portal.share(env.a, _SOURCE))
    pick = _pick_for(portal, spec)
    asked = _dialogs(monkeypatch, pick)
    answers = iter(["replace"])
    monkeypatch.setattr(page, "_ask_overwrite",
                        lambda *a, **k: next(answers), raising=False)

    _run(page, spec, env)
    _run(page, spec, env)

    assert len(asked) == 1, asked
    assert _same(_out(page, spec), pick)


@pytest.mark.parametrize("spec", _params(_ALL))
def test_output_picked_on_the_field_needs_no_second_dialog(
        env, portal, spec, monkeypatch):
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    pick = _pick_for(portal, spec)
    asked = _dialogs(monkeypatch, pick)
    getattr(page, spec.out_attr).btn.click()
    assert len(asked) == 1

    _run(page, spec, env)

    assert len(asked) == 1, asked
    assert _written(spec.produced(pick))


def test_picking_a_file_that_exists_asks_only_in_the_dialog(
        env, portal, monkeypatch):
    spec = SPECS["convert_txt"]
    page = env.make(spec)
    _load(page, spec, portal.share(env.a, _SOURCE))
    pick = portal.path("ef56ab78", "plain.txt")
    open(pick, "w", encoding="utf-8").close()
    asked = _dialogs(monkeypatch, pick)
    page._drop_file.btn.click()

    _run(page, spec, env)

    assert len(asked) == 1
    assert _label(pick) == "A"  # and no overwrite box (env's teardown)


@pytest.mark.parametrize("cancelled_first", [False, True],
                         ids=["first_run", "after_cancel"])
@pytest.mark.parametrize("written_before", [False, True],
                         ids=["not_written", "already_written"])
def test_phantom_is_not_asked_about_replacing(env, portal, monkeypatch,
                                              written_before, cancelled_first):
    """Today the app asks "Replace the existing file?" about a plain.txt
    that does not exist on the host, right after the Save dialog."""
    spec = SPECS["convert_txt"]
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    phantom = _out(page, spec)
    if written_before:
        open(phantom, "w", encoding="utf-8").close()
    # An existing destination: the Save dialog has just asked about it.
    pick = _pick_for(portal, spec)
    open(pick, "w", encoding="utf-8").close()
    monkeypatch.setattr(
        page, "_ask_overwrite",
        lambda *a, **k: pytest.fail("asked about a file that is not there"),
        raising=False)
    if cancelled_first:
        _dialogs(monkeypatch)
        _run(page, spec, env)
    asked = _dialogs(monkeypatch, pick)

    _run(page, spec, env)

    assert len(asked) == 1
    assert _label(pick) == "A"


def test_ocr_format_switch_on_a_picked_output(env, portal, monkeypatch):
    """The output's id is not the input's, so comparing with the input
    would call this real: foo.pdf was granted, foo.txt was not."""
    src = portal.share(env.a, _SOURCE)
    page = env.make(SimpleNamespace(cls=TabOCR, inline=False,
                                    before_load=_no_setup))
    page.drop_in.set_path(src)
    pick = portal.path("ef56ab78", "foo.pdf")
    asked = _dialogs(monkeypatch, pick)
    page.drop_out.btn.click()
    assert len(asked) == 1
    page.cmb_fmt.setCurrentIndex(1)
    assert _same(page.drop_out.path(), portal.path("ef56ab78", "foo.txt"))
    assert page.drop_out.is_portal_phantom()
    asked = _dialogs(monkeypatch)

    page._run()

    assert len(asked) == 1
    assert os.path.splitext(asked[0])[1] == ".txt"
    assert _same(os.path.dirname(asked[0]), os.path.dirname(src))
    assert _same(page.drop_out.path(), portal.path("ef56ab78", "foo.txt"))
    assert env.ocr_langs == []


def test_ocr_switching_back_stays_closed(env, portal, monkeypatch):
    """Back on the granted name it would be real. One dialog too many is
    the accepted cost of not tracking every name a field ever held."""
    page = env.make(SimpleNamespace(cls=TabOCR, inline=False,
                                    before_load=_no_setup))
    page.drop_in.set_path(portal.share(env.a, _SOURCE))
    _dialogs(monkeypatch, portal.path("ef56ab78", "foo.pdf"))
    page.drop_out.btn.click()
    assert not page.drop_out.is_portal_phantom()
    page.cmb_fmt.setCurrentIndex(1)
    page.cmb_fmt.setCurrentIndex(0)
    assert page.drop_out.is_portal_phantom()


@pytest.mark.parametrize("cancelled_first", [False, True],
                         ids=["first_run", "after_cancel"])
@pytest.mark.parametrize("spec", _params(_STUCK_OUTPUT))
def test_output_held_over_from_another_input(env, portal, spec, monkeypatch,
                                             cancelled_first):
    """A was in a doc folder, B is elsewhere: comparing with B's id would
    write B's result into A's doc folder and say it worked. A cancelled
    dialog on A changes nothing about that."""
    src_a = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    field = getattr(page, spec.out_attr)
    _load(page, spec, src_a)
    if cancelled_first:
        _dialogs(monkeypatch)
        _run(page, spec, env)
    _load(page, spec, env.b)
    assert _same(_out(page, spec), spec.out(src_a))
    asked = _dialogs(monkeypatch)

    _run(page, spec, env)

    assert len(asked) == 1, asked
    b_dir, b_stem = os.path.split(os.path.splitext(env.b)[0])
    if spec.folder:
        assert _same(asked[0], b_dir)
    else:
        ext = os.path.splitext(spec.out("x.pdf"))[1]
        name = (b_stem + "_edited" + ext if spec.id == "editor" else
                f"{b_stem}_{os.path.splitext(field._default)[0]}{ext}")
        assert _same(asked[0], os.path.join(b_dir, name))
    assert os.listdir(os.path.dirname(src_a)) == [_SOURCE]


def test_import_derived_and_held_over(env, portal, monkeypatch):
    text_a, text_b = _import_sources(env)
    src = portal.share(text_a, "nota ç.txt")
    page = env.make(SimpleNamespace(cls=TabImport, inline=True,
                                    before_load=_no_setup))
    _import_pick_files(page, monkeypatch, [src])
    phantom = os.path.splitext(src)[0] + ".pdf"
    assert _same(page.drop_out.path(), phantom)
    page._remove_btn.click()
    _import_pick_files(page, monkeypatch, [text_b])
    asked = _dialogs(monkeypatch)
    page._run()
    assert len(asked) == 1
    assert _same(asked[0], os.path.join(os.path.dirname(text_b),
                                        "bravo ã_output.pdf"))

    page.drop_out.set_path(phantom)
    page._remove_btn.click()
    _import_pick_files(page, monkeypatch, [src])
    asked = _dialogs(monkeypatch)
    page._run()
    assert len(asked) == 1
    assert _same(asked[0], phantom)
    assert os.listdir(os.path.dirname(src)) == ["nota ç.txt"]


def test_merge_field_holding_a_phantom(env, portal, monkeypatch):
    src = portal.share(env.a, _SOURCE)
    page = env.make(SimpleNamespace(cls=TabJuntar, inline=False,
                                    before_load=_no_setup))
    page._on_drop([src, env.b])
    phantom = os.path.join(os.path.dirname(src), "merged.pdf")
    page.drop_out.set_path(phantom)
    pick = portal.path("ef56ab78", "junta ç.pdf")
    asked = _dialogs(monkeypatch, pick)

    page._run()

    assert len(asked) == 1
    assert _same(asked[0], phantom)
    assert _label(pick) == "A+B"
    assert os.listdir(os.path.dirname(src)) == [_SOURCE]
    assert len(env.infos) == 1


def test_forms_output(env, portal, monkeypatch):
    src = portal.share(env.a, "form.pdf")
    spec = SPECS["editor"]
    tab = env.make(spec)
    _load(tab, spec, src)
    tab._mode_idx = _MODE_FORMS
    assert _same(tab._drop_out.path(), portal.path("ab12cd34", "form_edited.pdf"))
    asked = _dialogs(monkeypatch)

    tab._run()

    assert len(asked) == 1
    assert _same(asked[0], portal.path("ab12cd34", "form_edited.pdf"))
    assert _same(tab._drop_out.path(), portal.path("ab12cd34", "form_edited.pdf"))
    assert os.listdir(os.path.dirname(src)) == ["form.pdf"]


# -- cancelling the dialog ---------------------------------------------------


def _format(index):
    return lambda page, env: page.cmb_format.setCurrentIndex(index)


def _decrypt_mode(page, env):
    page.cmb_mode.setCurrentIndex(1)


def _convert_spec(name, index, ext):
    return _spec(f"convert_{name}", TabConverter, _file_out("", ext),
                 before_load=_format(index), inline=True, out_attr="_drop_file")


# Every derived output a tool can hold: SPECS has one per tool, and a tool's
# other modes derive other names through other code.
_CANCEL_SPECS = [
    *SPECS.values(),
    _spec("ocr_pdf", TabOCR, _file_out("_ocr")),
    _spec("decrypt", TabEncriptar, _file_out("_dec"), before_load=_decrypt_mode),
    _spec("convert_jpg", TabConverter, _folder_out, before_load=_format(1),
          inline=True, out_attr="_drop_folder"),
    _convert_spec("docx", 2, ".docx"),
    _convert_spec("pptx", 4, ".pptx"),
    _convert_spec("xlsx", 5, ".xlsx"),
    _convert_spec("html", 6, ".html"),
    _convert_spec("epub", 7, ".epub"),
]
_cancel_params = pytest.mark.parametrize(
    "spec", [pytest.param(s, id=s.id) for s in _CANCEL_SPECS])


def _cancelling_dialogs(monkeypatch) -> list:
    """Both output dialogs cancel; returns (start path, filter) per dialog."""
    asked = []

    def _save(parent=None, caption="", directory="", file_filter="", *a, **k):
        asked.append((directory, file_filter))
        return "", ""

    def _folder(parent=None, caption="", directory="", *a, **k):
        asked.append((directory, None))
        return ""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(_save))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(_folder))
    return asked


def _form_state(page) -> dict:
    """What the user can see or the next run can read from the form."""
    fields = [
        (f.path(), f._chosen_path, f._confirmed_path, f._lbl.text(),
         f._lbl.toolTip(), f._lbl.property("has_file"), f._clr.isHidden())
        for f in page.findChildren(DropFileEdit)]
    return {
        "fields": fields,
        "combos": [c.currentIndex() for c in page.findChildren(QComboBox)],
        "edits": [e.text() for e in page.findChildren(QLineEdit)],
    }


@_cancel_params
def test_cancel_then_run_again_asks_the_same(env, portal, spec, monkeypatch):
    """The field is what names the dialog, so a Cancel that emptied it made
    the second dialog fall back on the widget's default name, under which
    Accept saves the wrong format."""
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    asked = _cancelling_dialogs(monkeypatch)

    _run(page, spec, env)
    _run(page, spec, env)

    assert len(asked) == 2, asked
    assert asked[1] == asked[0]
    assert _same(asked[0][0], spec.out(src))
    assert os.listdir(os.path.dirname(src)) == [_SOURCE]


@_cancel_params
def test_cancel_leaves_the_form_as_it_was(env, portal, spec, monkeypatch):
    page = env.make(spec)
    _load(page, spec, portal.share(env.a, _SOURCE))
    spec.before_run(page, env)
    field = getattr(page, spec.out_attr)
    before = _form_state(page)
    changes = []
    field.path_changed.connect(changes.append)
    _cancelling_dialogs(monkeypatch)

    page._run()

    assert _form_state(page) == before
    assert changes == []
    assert field.is_portal_phantom()


@pytest.mark.parametrize("spec", _params(_ALL))
def test_cancel_then_accept_writes_the_pick(env, portal, spec, monkeypatch):
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    _dialogs(monkeypatch)
    _run(page, spec, env)
    pick = _pick_for(portal, spec)
    asked = _dialogs(monkeypatch, pick)

    _run(page, spec, env)

    assert len(asked) == 1, asked
    assert _same(asked[0], spec.out(src))
    assert _same(_out(page, spec), pick)
    assert _written(spec.produced(pick))
    assert os.listdir(os.path.dirname(src)) == [_SOURCE]


@pytest.mark.parametrize("spec", _params(["rotate", "convert_txt", "editor"]))
def test_accepting_the_suggestion_as_is_grants_nothing(env, portal, spec, monkeypatch):
    """Only the fallback dialog answers with the name it was given: the
    portal's answer has an id of its own. This used to pin the opposite, a
    guess that the prova of 1.15.3 measured as a save that never happened."""
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    suggested = _out(page, spec)
    asked = _dialogs(monkeypatch, suggested)

    _run(page, spec, env)

    assert len(asked) == 1, asked
    assert getattr(page, spec.out_attr).is_portal_phantom()
    assert _same(_out(page, spec), suggested)
    assert not _written(suggested)
    assert env.warnings == [(t("msg.warning"), t("tool.err.portal_output"))]


def test_ocr_format_switch_after_a_cancel(env, portal, monkeypatch):
    """_on_fmt_change only rewrites a field that has a path."""
    src = portal.share(env.a, _SOURCE)
    page = env.make(SimpleNamespace(cls=TabOCR, inline=False,
                                    before_load=_no_setup))
    page.drop_in.set_path(src)
    base = os.path.splitext(src)[0] + "_ocr"
    asked = _cancelling_dialogs(monkeypatch)
    page._run()
    assert _same(asked[0][0], base + ".pdf")

    page.cmb_fmt.setCurrentIndex(1)
    assert _same(page.drop_out.path(), base + ".txt")
    page._run()
    assert _same(asked[1][0], base + ".txt")

    page.cmb_fmt.setCurrentIndex(0)
    page._run()
    assert _same(asked[2][0], base + ".pdf")
    assert env.ocr_langs == []


def test_merge_cancel_then_run_again_asks_the_same(env, portal, monkeypatch):
    src = portal.share(env.a, _SOURCE)
    page = env.make(SimpleNamespace(cls=TabJuntar, inline=False,
                                    before_load=_no_setup))
    page._on_drop([src, env.b])
    phantom = os.path.join(os.path.dirname(src), "merged.pdf")
    page.drop_out.set_path(phantom)
    asked = _cancelling_dialogs(monkeypatch)

    page._run()
    page._run()

    assert len(asked) == 2
    assert asked[1] == asked[0]
    assert _same(asked[0][0], phantom)
    assert _same(page.drop_out.path(), phantom)


def test_import_cancel_then_run_again_asks_the_same(env, portal, monkeypatch):
    text_a, _ = _import_sources(env)
    src = portal.share(text_a, "nota ç.txt")
    page = env.make(SimpleNamespace(cls=TabImport, inline=True,
                                    before_load=_no_setup))
    _import_pick_files(page, monkeypatch, [src])
    phantom = page.drop_out.path()
    asked = _cancelling_dialogs(monkeypatch)

    page._run()
    page._run()

    assert len(asked) == 2
    assert asked[1] == asked[0]
    assert _same(asked[0][0], os.path.splitext(src)[0] + ".pdf")
    assert page.drop_out.path() == phantom


# -- the editor with nothing to apply ----------------------------------------


def test_editor_with_no_edits_on_a_portal_pdf_asks_nothing(
        env, portal, monkeypatch):
    spec = SPECS["editor"]
    tab = env.make(spec)
    _load(tab, spec, portal.share(env.a, _SOURCE))
    derived = _out(tab, spec)
    asked = _dialogs(monkeypatch)

    tab._run()

    assert asked == []
    assert env.warnings == [(t("msg.warning"), t("msg.no_pending"))]
    assert _same(_out(tab, spec), derived)


def test_editor_with_no_edits_and_an_empty_field_still_asks_first(
        env, portal, monkeypatch):
    """Outside the portal the order of dialog and warning is as it was."""
    spec = SPECS["editor"]
    tab = env.make(spec)
    _load(tab, spec, env.a)
    tab._drop_out.clear()
    pick = os.path.join(os.path.dirname(env.a), "escolhido.pdf")
    asked = _dialogs(monkeypatch, pick)

    tab._run()

    assert len(asked) == 1
    assert env.warnings == [(t("msg.warning"), t("msg.no_pending"))]
    assert _same(_out(tab, spec), pick)
    assert not os.path.exists(pick)


def test_choose_another_name_is_granted(env, portal, monkeypatch):
    spec = SPECS["convert_txt"]
    page = env.make(spec)
    _load(page, spec, portal.share(env.a, _SOURCE))
    first = portal.path("ef56ab78", "plain.txt")
    open(first, "w", encoding="utf-8").close()
    asked = _dialogs(monkeypatch, first)
    page._drop_file.btn.click()
    _run(page, spec, env)
    # One dialog, the click's: its answer is granted and written unasked.
    assert len(asked) == 1, asked
    assert _label(first) == "A"
    assert not page._drop_file.is_portal_phantom()
    second = portal.path("0a0b0c0d", "outro.txt")
    asked = _dialogs(monkeypatch, second)
    monkeypatch.setattr(page, "_ask_overwrite",
                        lambda *a, **k: page.OVERWRITE_RENAME)

    _run(page, spec, env)

    assert len(asked) == 1
    assert _label(second) == "A"
    assert not page._drop_file.is_portal_phantom()


def test_choose_another_folder_is_granted(env, portal, monkeypatch):
    spec = SPECS["convert_png"]
    page = env.make(spec)
    _load(page, spec, portal.share(env.a, _SOURCE))
    first = portal.path("ef56ab78", "pasta")
    os.mkdir(first)
    asked = _dialogs(monkeypatch, first)
    page._drop_folder.btn.click()
    _run(page, spec, env)
    # One dialog, the click's: its answer is granted and written unasked.
    assert len(asked) == 1, asked
    assert _written(first)
    assert not page._drop_folder.is_portal_phantom()
    second = portal.path("0a0b0c0d", "outra")
    os.mkdir(second)
    asked = _dialogs(monkeypatch, second)
    monkeypatch.setattr(page, "_ask_overwrite",
                        lambda *a, **k: page.OVERWRITE_RENAME)

    _run(page, spec, env)

    assert len(asked) == 1
    assert _written(second)
    assert not page._drop_folder.is_portal_phantom()


def test_drop_on_the_output_fails_closed(env, portal, monkeypatch):
    """The portal does hand over a dropped file, but nothing here measured
    how a write to it behaves: one dialog is the accepted cost."""
    spec = SPECS["rotate"]
    page = env.make(spec)
    _load(page, spec, env.a)
    dropped = portal.share(env.b, "largado.pdf", "dd00dd00")
    _drop_on(page.drop_out, dropped)
    assert _same(page.drop_out.path(), dropped)
    asked = _dialogs(monkeypatch)

    _run(page, spec, env)

    assert len(asked) == 1


def test_clear_revokes_the_grant(env, portal, monkeypatch):
    page = env.make(SPECS["rotate"])
    pick = portal.path("ef56ab78", "a.pdf")
    _dialogs(monkeypatch, pick)
    page.drop_out.btn.click()
    assert not page.drop_out.is_portal_phantom()
    page.drop_out.clear()
    page.drop_out.set_path(pick)
    assert page.drop_out.is_portal_phantom()


def test_below_a_folder_grant_is_real(env, portal, monkeypatch):
    """Measured: Split and Images write for real below a granted folder."""
    spec = SPECS["rotate"]
    src = portal.share(env.a, _SOURCE, os.path.join("ab12cd34", "pasta"))
    page = env.make(spec)
    _load(page, spec, src)
    asked = _dialogs(monkeypatch)

    _run(page, spec, env)

    assert asked == []
    assert _written(spec.out(src))


def test_folder_of_a_file_below_a_grant_fails_closed(env, portal, monkeypatch):
    """It is real, but it looks like an unknown direct child: one dialog."""
    spec = SPECS["split"]
    src = portal.share(env.a, _SOURCE, os.path.join("ab12cd34", "pasta"))
    page = env.make(spec)
    _load(page, spec, src)
    asked = _dialogs(monkeypatch)

    _run(page, spec, env)

    assert len(asked) == 1


@pytest.mark.parametrize("current_uid", [None, _UID + 1],
                         ids=["no_uid_platform", "another_user"])
@pytest.mark.parametrize("spec", _params(["rotate", "split", "convert_txt",
                                          "editor"]))
def test_outside_the_current_portal_nothing_changes(
        env, portal, spec, current_uid, monkeypatch):
    monkeypatch.setattr(portal_mod, "_current_uid", lambda: current_uid)
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    derived = _out(page, spec)
    asked = _dialogs(monkeypatch)

    _run(page, spec, env)

    assert asked == []
    assert _same(_out(page, spec), derived)
    assert _written(spec.produced(derived))


@pytest.mark.parametrize("spec", _params(["rotate", "split", "convert_txt",
                                          "editor"]))
def test_ordinary_folder_gets_no_dialog(env, portal, spec, monkeypatch):
    page = env.make(spec)
    _load(page, spec, env.a)
    derived = _out(page, spec)
    asked = _dialogs(monkeypatch)

    _run(page, spec, env)

    assert asked == []
    assert _written(spec.produced(derived))


def test_pipeline_output_never_opens_the_dialog(env, portal, monkeypatch):
    """Compact mode writes to its own temp file; the doc path the field
    picked up is not used, and stays for when compact mode ends."""
    spec = SPECS["rotate"]
    src = portal.share(env.a, _SOURCE)
    page = env.make(spec)
    _load(page, spec, src)
    derived = _out(page, spec)
    page.set_compact_mode(True)
    assert page._pipeline_active
    asked = _dialogs(monkeypatch)

    temp = page._resolve_output_file(page.drop_out, src)
    guarded = page._resolve_output_file_guarded(page.drop_out, src)

    assert asked == []
    assert temp == guarded
    assert not temp.startswith(str(portal.root))
    assert _same(_out(page, spec), derived)
    page.cleanup_pipeline()
