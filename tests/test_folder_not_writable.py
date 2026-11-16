"""A folder that refuses a new file is said so, in every tool (N4).

``tempfile.mkstemp`` in a folder the user may not create files in raises
a PermissionError that names the temp file it tried, which does not
exist, in a folder that does. ``show_error`` showed it as "something went
wrong"; it now says the folder takes no new files and what to do. The
save that hit it most, the pipeline's Save as, used to hide it behind a
copy straight onto the destination, which truncated it first (see
``tests/test_replace_own_input.py``, point 11).
"""

from __future__ import annotations

import errno
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import typing
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from app import utils
from app.i18n import t
from app.pdf_io import is_unwritable_folder_error

_TEMP_NAME = "tmpk3x9q1zz.pdf"


def _refused_in(folder: Path) -> PermissionError:
    """What ``mkstemp`` raises in ``folder`` when it may not create files."""
    return PermissionError(errno.EACCES, "Permission denied", str(folder / _TEMP_NAME))


# -- the helper ---------------------------------------------------------------


def test_the_helper_tells_type_checkers_it_is_a_permission_error():
    """``show_error`` reads ``exc.errno`` and ``exc.filename`` after it:
    with a plain bool return, mypy flags them on a BaseException."""
    hints = typing.get_type_hints(is_unwritable_folder_error)
    assert hints["return"] == typing.TypeGuard[PermissionError]


def test_a_temp_file_refused_in_a_folder_that_exists(tmp_path):
    assert is_unwritable_folder_error(_refused_in(tmp_path)) is True


def test_a_path_like_name_counts_too(tmp_path):
    exc = PermissionError(errno.EACCES, "Permission denied", tmp_path / _TEMP_NAME)
    assert is_unwritable_folder_error(exc) is True


def test_a_refused_replace_names_its_destination_and_is_another_problem(tmp_path):
    """``os.replace`` fills ``filename2``: it is about that file, even when
    the first name does not exist."""
    exc = PermissionError(errno.EACCES, "Permission denied",
                          str(tmp_path / _TEMP_NAME), None,
                          str(tmp_path / "destino ç.pdf"))
    assert not os.path.lexists(exc.filename)
    assert is_unwritable_folder_error(exc) is False


def test_an_existing_file_refused_is_not_the_folder(tmp_path):
    held = tmp_path / "só leitura ç.pdf"
    held.write_bytes(b"x")
    exc = PermissionError(errno.EACCES, "Permission denied", str(held))
    assert is_unwritable_folder_error(exc) is False


def test_a_dangling_link_exists_as_a_name(tmp_path):
    """``lexists``, not ``exists``: a link to nothing still takes the name."""
    link = tmp_path / "ligação ç.pdf"
    try:
        os.symlink(tmp_path / "nada", link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"no symlinks here: {exc}")
    assert not link.exists() and os.path.lexists(link)
    refused = PermissionError(errno.EACCES, "Permission denied", str(link))
    assert is_unwritable_folder_error(refused) is False


def test_a_bare_temp_name_in_the_current_folder(tmp_path, monkeypatch):
    """A name with no folder part is in the current folder, which exists."""
    monkeypatch.chdir(tmp_path)
    exc = PermissionError(errno.EACCES, "Permission denied", _TEMP_NAME)
    assert is_unwritable_folder_error(exc) is True


def test_a_closed_descriptor_in_place_of_the_name(tmp_path):
    """A descriptor that is surely not open: on Windows ``os.path.lexists``
    is True for an open one, which hides a type check that lets an int
    through (then ``os.path`` raises TypeError, inside ``show_error``)."""
    fd = os.open(tmp_path / "x", os.O_CREAT | os.O_WRONLY)
    os.close(fd)
    exc = PermissionError(errno.EACCES, "denied", fd)
    assert is_unwritable_folder_error(exc) is False


def test_a_folder_that_does_not_exist_either(tmp_path):
    assert is_unwritable_folder_error(_refused_in(tmp_path / "falta")) is False


@pytest.mark.parametrize("exc", [
    PermissionError(errno.EACCES, "denied"),
    PermissionError("denied"),
    # A file descriptor where the name goes, as an open of a descriptor
    # gives: os.path would raise TypeError on it, inside show_error.
    PermissionError(errno.EACCES, "denied", 3),
    FileNotFoundError(errno.ENOENT, "missing", "nada ç.pdf"),
    OSError("disk went away"),
    RuntimeError("Permission denied"),
], ids=["no_name", "no_errno", "fd_not_path", "not_found", "plain_os_error",
        "not_os_error"])
def test_other_errors_are_not_a_folder_that_refuses_files(exc):
    assert is_unwritable_folder_error(exc) is False


def test_not_found_with_the_same_shape_is_not_it(tmp_path):
    """The same names as the mkstemp case, but a missing file, not a refusal."""
    exc = FileNotFoundError(errno.ENOENT, "missing", str(tmp_path / _TEMP_NAME))
    assert is_unwritable_folder_error(exc) is False


@pytest.mark.skipif(os.name != "posix", reason="POSIX folder modes")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root creates files in a read-only folder")
def test_what_mkstemp_raises_in_a_real_read_only_folder(tmp_path):
    folder = tmp_path / "só leitura ç"
    folder.mkdir()
    os.chmod(folder, 0o555)
    try:
        with pytest.raises(PermissionError) as info:
            tempfile.mkstemp(suffix=".pdf", dir=str(folder))
    finally:
        os.chmod(folder, 0o755)
    assert info.value.filename2 is None
    assert is_unwritable_folder_error(info.value) is True


def _icacls(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["icacls", *args], capture_output=True, check=False)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACLs")
def test_what_mkstemp_raises_in_a_folder_an_acl_closes(tmp_path):
    """No stand-in: an ACL that denies the user creating files in the
    folder. ``mkstemp`` tries its names, then raises the last refusal."""
    user = os.environ.get("USERNAME")
    if not user or shutil.which("icacls") is None:
        pytest.skip("no icacls or no USERNAME")
    folder = tmp_path / "sem escrita ç"
    folder.mkdir()
    try:
        denied = _icacls(str(folder), "/deny", f"{user}:(WD)")
    except OSError as exc:
        pytest.skip(f"icacls did not run: {exc}")
    try:
        if denied.returncode != 0:
            pytest.skip(f"icacls refused the deny: {denied.returncode}")
        with pytest.raises(PermissionError) as info:
            tempfile.mkstemp(suffix=".pdf", dir=str(folder))
    finally:
        removed = _icacls(str(folder), "/remove:d", user)
    assert removed.returncode == 0, removed.stdout
    assert info.value.filename2 is None
    assert is_unwritable_folder_error(info.value) is True


# -- what the user is shown ---------------------------------------------------


def _boxes_shown(monkeypatch) -> list:
    """Every QMessageBox ``exec``'d: (icon, title, text, details)."""
    boxes = []

    def _exec(box):
        boxes.append((box.icon(), box.windowTitle(), box.text(), box.detailedText()))
        return 0
    monkeypatch.setattr(QMessageBox, "exec", _exec)
    return boxes


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_show_error_says_the_folder_takes_no_new_files(
        qapp, tmp_path, monkeypatch, platform):
    folder = tmp_path / "pasta ç"
    folder.mkdir()
    monkeypatch.setattr(sys, "platform", platform)
    boxes = _boxes_shown(monkeypatch)

    utils.show_error(None, _refused_in(folder))

    assert [(b[0], b[1], b[2]) for b in boxes] == \
        [(QMessageBox.Icon.Warning, t("msg.warning"), t("msg.folder_not_writable"))]
    assert boxes[0][3].startswith("PermissionError: ")
    assert _TEMP_NAME in boxes[0][3], "the details name the file tried"


def test_a_descriptor_in_place_of_the_name_is_still_shown(qapp, monkeypatch):
    """The generic dialog, and no TypeError from inside show_error."""
    monkeypatch.setattr(sys, "platform", "win32")
    boxes = _boxes_shown(monkeypatch)

    utils.show_error(None, PermissionError(errno.EACCES, "denied", 3))

    assert [(b[0], b[2]) for b in boxes] == \
        [(QMessageBox.Icon.Critical, t("msg.unexpected"))]


def test_a_refused_replace_is_not_shown_as_the_folder(qapp, tmp_path, monkeypatch):
    """Off Windows a refused replace onto a file stays the generic error."""
    monkeypatch.setattr(sys, "platform", "linux")
    boxes = _boxes_shown(monkeypatch)
    exc = PermissionError(errno.EACCES, "Permission denied",
                          str(tmp_path / _TEMP_NAME), None,
                          str(tmp_path / "destino ç.pdf"))

    utils.show_error(None, exc)

    assert [(b[0], b[2]) for b in boxes] == \
        [(QMessageBox.Icon.Critical, t("msg.unexpected"))]


def test_a_file_in_use_is_asked_about_first(qapp, tmp_path, monkeypatch):
    """Constructed to match both: Windows' "user-mapped file" code on a
    name that does not exist. The file in use comes first, as the
    docstring of ``show_error`` says; only an exception that matches both
    can tell the order."""
    folder = tmp_path / "pasta ç"
    folder.mkdir()
    exc = _refused_in(folder)
    exc.winerror = 1224
    monkeypatch.setattr(sys, "platform", "win32")
    assert is_unwritable_folder_error(exc) is True
    boxes = _boxes_shown(monkeypatch)

    utils.show_error(None, exc)

    assert [b[2] for b in boxes] == [t("msg.file_in_use")]


def test_the_log_has_the_os_fields_and_not_the_text(qapp, tmp_path, monkeypatch, caplog):
    """As for a file in use (CodeQL traces a password into these)."""
    text = "texto que não vai para o registo"
    target = str(tmp_path / _TEMP_NAME)
    exc = PermissionError(errno.EACCES, text, target)
    boxes = _boxes_shown(monkeypatch)

    with caplog.at_level(logging.DEBUG):
        utils.show_error(None, exc)

    records = [r for r in caplog.records
               if r.getMessage().startswith("Folder not writable: ")]
    assert len(records) == 1, [r.getMessage() for r in caplog.records]
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info is None, "no traceback"
    assert text not in caplog.text
    logged = records[0].getMessage()
    assert f"errno={errno.EACCES} " in logged and repr(target) in logged
    assert [b[2] for b in boxes] == [t("msg.folder_not_writable")]
    assert text in boxes[0][3]


# -- the text, in every language ----------------------------------------------


def test_the_message_is_in_every_language():
    path = Path(__file__).resolve().parent.parent / "app" / "translations.json"
    langs = json.loads(path.read_text(encoding="utf-8"))
    texts = {lang: keys.get("msg.folder_not_writable", "")
             for lang, keys in langs.items()}
    assert len(texts) == 8 and all(text.strip() for text in texts.values()), texts
    assert len(set(texts.values())) == len(texts), "one text per language"
    assert not any(chr(0x2014) in text for text in texts.values())
    assert all(set(keys) == set(langs["en"]) for keys in langs.values())
    assert texts["en"] == ("PDFApps cannot create files in this folder. "
                           "Choose another folder, or check its permissions.")
