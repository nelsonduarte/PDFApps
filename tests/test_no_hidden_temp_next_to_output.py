"""Temp files next to a user's PDF must not have a name starting with a dot.

The snap ``home`` interface denies creating dotfiles directly in ``$HOME``.
On Ubuntu 26.04.1 with snap 1.15.2 rev 45 the AppArmor denial (``mknod``)
made Forms save and delete-comment fail with PermissionError for a PDF in
``~``, and the user saw only a generic error. The same operations worked in
``~/Documents``, because the rule only covers the top level.

AppArmor is not available here, so ``_deny_hidden`` reproduces its observable
effect: mkstemp raises PermissionError for a prefix starting with a dot. The
static guard covers temp files of paths these behavioural tests do not drive.
"""

from __future__ import annotations

import ast
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

_app = QApplication.instance() or QApplication([])

import pymupdf  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402

from app.editor.tab import TabEditar  # noqa: E402
from app.viewer.panel import PdfViewerPanel  # noqa: E402

# ── static guard ───────────────────────────────────────────────────────────

# Index of ``prefix`` when it is passed positionally.
_PREFIX_POSITION = {
    "mkstemp": 1,
    "mkdtemp": 1,
    "TemporaryDirectory": 1,
    "NamedTemporaryFile": 5,
    "TemporaryFile": 5,
}


def _module_strings(tree):
    return {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def _leading_text(node, names):
    """The statically known start of a string expression, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        return _leading_text(node.values[0], names)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _leading_text(node.left, names)
    if isinstance(node, ast.Name):
        return names.get(node.id)
    return None


def _hidden_temp_calls(source):
    """Line and prefix of every tempfile call whose prefix starts with a dot."""
    tree = ast.parse(source)
    names = _module_strings(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        position = _PREFIX_POSITION.get(called)
        if position is None:
            continue
        prefix = next((k.value for k in node.keywords if k.arg == "prefix"), None)
        if prefix is None and len(node.args) > position:
            prefix = node.args[position]
        if prefix is None:
            continue
        text = _leading_text(prefix, names)
        if text is not None and text.startswith("."):
            found.append((node.lineno, text))
    return found


def _python_sources():
    for folder in ("app", "tests"):
        yield from sorted((ROOT / folder).rglob("*.py"))
    for name in ("pdfapps.py", "installer.py", "uninstaller.py"):
        yield ROOT / name


def test_no_temp_file_anywhere_uses_a_prefix_starting_with_a_dot():
    offenders = []
    sources = list(_python_sources())
    assert len(sources) > 50, "the scan lost its input: %d files" % len(sources)
    for path in sources:
        for line, prefix in _hidden_temp_calls(path.read_text(encoding="utf-8")):
            offenders.append("%s:%d prefix=%r" % (path.relative_to(ROOT), line, prefix))
    assert not offenders, (
        "the snap home interface denies these in ~: " + "; ".join(offenders)
    )


@pytest.mark.parametrize("source", [
    'tempfile.mkstemp(prefix=".x")',
    'tempfile.mkstemp(".pdf", ".x")',
    'mkstemp(prefix=".x", dir=d)',
    'tempfile.mkdtemp(prefix=".x")',
    'tempfile.TemporaryDirectory(prefix=".x")',
    'tempfile.NamedTemporaryFile(prefix=".x")',
    'tempfile.NamedTemporaryFile("wb", -1, None, None, ".pdf", ".x")',
    'tempfile.TemporaryFile(prefix=".x")',
    'tempfile.mkstemp(prefix=f".x_{n}")',
    'tempfile.mkstemp(prefix=".x_" + n)',
    'P = ".x"\ntempfile.mkstemp(prefix=P)',
])
def test_guard_catches_a_hidden_prefix(source):
    assert _hidden_temp_calls(source)


@pytest.mark.parametrize("source", [
    'tempfile.mkstemp(suffix=".pdf", dir=d)',
    'tempfile.mkstemp(prefix="pdfapps_save_", suffix=".pdf")',
    'tempfile.mkstemp(".pdf", "x")',
    'tempfile.mkstemp(prefix=os.path.basename(p) + ".")',
    'tempfile.mkstemp(prefix=f"{n}.x")',
    'tempfile.NamedTemporaryFile("wb", suffix=".x")',
    'something_else(prefix=".x")',
])
def test_guard_does_not_flag_a_visible_prefix(source):
    assert not _hidden_temp_calls(source)


# ── helpers ────────────────────────────────────────────────────────────────


@pytest.fixture
def folder(tmp_path):
    path = tmp_path / "pasta com espaços ção"
    path.mkdir()
    return path


@pytest.fixture
def created(monkeypatch):
    """Record every temp file mkstemp makes, denying a hidden one as AppArmor
    does on the top level of the home folder."""
    names = []
    real = tempfile.mkstemp

    def _deny_hidden(suffix=None, prefix=None, dir=None, text=False):
        if prefix and prefix.startswith("."):
            raise PermissionError(13, "Permission denied (apparmor mknod)")
        fd, path = real(suffix=suffix, prefix=prefix, dir=dir, text=text)
        names.append(path)
        return fd, path

    monkeypatch.setattr(tempfile, "mkstemp", _deny_hidden)
    return names


def _listing(path):
    return sorted(os.listdir(path))


# ── Forms save ─────────────────────────────────────────────────────────────


def _make_form_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    widget = pymupdf.Widget()
    widget.field_name = "nome"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_value = "antes"
    widget.rect = pymupdf.Rect(72, 72, 272, 100)
    page.add_widget(widget)
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def forms(folder, monkeypatch):
    src = _make_form_pdf(folder / "form.pdf")
    errors = []
    monkeypatch.setattr("app.editor.tab.show_error",
                        lambda _parent, exc, *a, **k: errors.append(exc))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    tab = TabEditar(lambda *a, **k: None)
    tab._doc_path = src
    tab._load_form_fields(src)
    assert tab._form_table.rowCount() == 1
    tab._form_table.item(0, 1).setText("depois")
    yield SimpleNamespace(tab=tab, src=src, errors=errors,
                          out=str(folder / "out.pdf"), folder=folder)
    tab.deleteLater()


def test_forms_save_succeeds_where_a_hidden_temp_is_denied(forms, created):
    forms.tab._apply_forms(forms.out)

    assert forms.errors == []
    assert PdfReader(forms.out).get_fields()["nome"]["/V"] == "depois"
    assert _listing(forms.folder) == ["form.pdf", "out.pdf"]
    assert len(created) == 1
    assert os.path.dirname(created[0]) == str(forms.folder)
    assert os.path.basename(created[0]).startswith("pdfapps_save_")


def test_forms_failed_write_removes_the_temp_and_keeps_the_output(
        forms, created, monkeypatch):
    Path(forms.out).write_bytes(b"previous")

    def _fail(self, stream):
        stream.write(b"partial")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(PdfWriter, "write", _fail)
    forms.tab._apply_forms(forms.out)

    assert [type(e) for e in forms.errors] == [OSError]
    assert len(created) == 1, "the failure must come after the temp exists"
    assert _listing(forms.folder) == ["form.pdf", "out.pdf"]
    assert Path(forms.out).read_bytes() == b"previous"


def test_forms_failed_replace_removes_the_temp_and_keeps_the_output(
        forms, created, monkeypatch):
    Path(forms.out).write_bytes(b"previous")

    def _fail(_src, _dst):
        raise PermissionError(13, "sharing violation")

    monkeypatch.setattr(os, "replace", _fail)
    forms.tab._apply_forms(forms.out)

    assert [type(e) for e in forms.errors] == [PermissionError]
    assert len(created) == 1
    assert _listing(forms.folder) == ["form.pdf", "out.pdf"]
    assert Path(forms.out).read_bytes() == b"previous"


def test_forms_denied_temp_reports_and_writes_nothing(forms, monkeypatch):
    def _denied(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(tempfile, "mkstemp", _denied)
    forms.tab._apply_forms(forms.out)

    assert [type(e) for e in forms.errors] == [PermissionError]
    assert _listing(forms.folder) == ["form.pdf"]


def test_forms_save_leaves_an_old_hidden_temp_alone(forms, created):
    old = forms.folder / ".pdfapps_save_old.pdf"
    old.write_bytes(b"left by an older version")

    forms.tab._apply_forms(forms.out)

    assert forms.errors == []
    assert PdfReader(forms.out).get_fields()["nome"]["/V"] == "depois"
    assert old.read_bytes() == b"left by an older version"
    assert _listing(forms.folder) == [old.name, "form.pdf", "out.pdf"]


# ── delete comment ─────────────────────────────────────────────────────────


class _Menu:
    """QMenu whose exec picks the first action, the delete-comment one."""

    def __init__(self, _parent):
        self._action = object()

    def addAction(self, *_a):
        return self._action

    def exec(self, *_a):
        return self._action


def _annot_count(path):
    with pymupdf.open(path) as doc:
        return len(list(doc[0].annots() or []))


@pytest.fixture
def viewer(folder, qtbot, monkeypatch):
    path = folder / "notas.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello")
    page.add_text_annot((100, 150), "nota")
    doc.save(str(path))
    doc.close()

    errors = []
    monkeypatch.setattr("app.utils.show_error",
                        lambda _parent, exc, *a, **k: errors.append(exc))
    monkeypatch.setattr("PySide6.QtWidgets.QMenu", _Menu)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a)))

    panel = PdfViewerPanel()
    qtbot.addWidget(panel)
    panel.load(str(path))
    for _ in range(5):
        _app.processEvents()
    canvas = panel._canvas
    assert canvas._entries[0].annots, "the fixture note was not read"
    monkeypatch.setattr(canvas, "_note_icon_at", lambda _pos: (0, 0))
    event = SimpleNamespace(pos=lambda: QPoint(1, 1), globalPos=lambda: QPoint(1, 1))
    return SimpleNamespace(canvas=canvas, path=str(path), folder=folder,
                           errors=errors, warnings=warnings,
                           delete=lambda: canvas.contextMenuEvent(event))


def test_delete_comment_succeeds_where_a_hidden_temp_is_denied(viewer, created):
    viewer.delete()

    assert viewer.errors == []
    assert _annot_count(viewer.path) == 0
    assert _listing(viewer.folder) == ["notas.pdf"]
    assert len(created) == 1
    assert os.path.dirname(created[0]) == str(viewer.folder)
    assert os.path.basename(created[0]).startswith("pdfapps_backup_")
    assert created[0].endswith(".pdf.bak")


def test_delete_comment_failed_backup_copy_removes_it(viewer, created, monkeypatch):
    before = Path(viewer.path).read_bytes()

    def _fail(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(shutil, "copy2", _fail)
    viewer.delete()

    assert [type(e) for e in viewer.errors] == [OSError]
    assert len(created) == 1
    assert _listing(viewer.folder) == ["notas.pdf"]
    assert Path(viewer.path).read_bytes() == before


def test_delete_comment_denied_backup_reports_and_changes_nothing(viewer, monkeypatch):
    before = Path(viewer.path).read_bytes()

    def _denied(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(tempfile, "mkstemp", _denied)
    viewer.delete()

    assert [type(e) for e in viewer.errors] == [PermissionError]
    assert _listing(viewer.folder) == ["notas.pdf"]
    assert Path(viewer.path).read_bytes() == before


def test_delete_comment_without_a_match_removes_the_backup(viewer, created):
    entry = viewer.canvas._entries[0]
    rect, _text = entry.annots[0]
    entry.annots[0] = (rect, "another text")

    viewer.delete()

    assert len(viewer.warnings) == 1
    assert len(created) == 1
    assert _listing(viewer.folder) == ["notas.pdf"]
    assert _annot_count(viewer.path) == 1


def test_delete_comment_failed_delete_removes_the_backup(viewer, created, monkeypatch):
    def _fail(self, annot):
        raise RuntimeError("damaged annotation")

    monkeypatch.setattr(pymupdf.Page, "delete_annot", _fail)
    viewer.delete()

    assert [type(e) for e in viewer.errors] == [RuntimeError]
    assert len(created) == 1
    assert _listing(viewer.folder) == ["notas.pdf"]
    assert _annot_count(viewer.path) == 1


def test_delete_comment_failed_save_restores_from_the_backup(viewer, created, monkeypatch):
    before = Path(viewer.path).read_bytes()
    moves = []
    real_move = shutil.move

    def _move(src, dst):
        # The open Document holds the PDF on Windows, so the rename can only
        # succeed once it is released. saveIncr failing is what is tested,
        # not the file lock.
        moves.append((src, dst))
        viewer.canvas._doc.close()
        return real_move(src, dst)

    def _fail(self):
        with open(viewer.path, "ab") as stream:
            stream.write(b"half an update")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pymupdf.Document, "saveIncr", _fail)
    monkeypatch.setattr(shutil, "move", _move)
    viewer.delete()

    assert [type(e) for e in viewer.errors] == [OSError]
    assert moves == [(created[0], viewer.path)]
    assert Path(viewer.path).read_bytes() == before
    assert _listing(viewer.folder) == ["notas.pdf"]


def test_delete_comment_failed_restore_keeps_the_backup_for_the_user(
        viewer, created, monkeypatch):
    def _fail(*_a, **_k):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(pymupdf.Document, "saveIncr", _fail)
    monkeypatch.setattr(shutil, "move", _fail)
    before = Path(viewer.path).read_bytes()
    viewer.delete()

    assert [type(e) for e in viewer.errors] == [OSError]
    assert _listing(viewer.folder) == sorted(
        [os.path.basename(created[0]), "notas.pdf"])
    assert Path(created[0]).read_bytes() == before


def test_delete_comment_leaves_an_old_hidden_backup_alone(viewer, created):
    old = viewer.folder / ".pdfapps_backup_old.pdf.bak"
    old.write_bytes(b"left by an older version")

    viewer.delete()

    assert viewer.errors == []
    assert _annot_count(viewer.path) == 0
    assert old.read_bytes() == b"left by an older version"
    assert _listing(viewer.folder) == [old.name, "notas.pdf"]
