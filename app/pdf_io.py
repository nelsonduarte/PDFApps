"""PDFApps – pdf_io: low-level atomic PDF write helpers.

Extracted from :class:`app.base.BasePage` (R3) so the same safe-write
logic is shared by BOTH the tool pages (via
``BasePage._atomic_pdf_write``) and the visual editor
(``TabEditar._run``) WITHOUT either side re-implementing the tempfile +
``os.replace`` dance, the same-source guard, or the PyMuPDF/pypdf writer
dispatch.

This module is deliberately pure and low-level: it imports only stdlib
at load time (``app.i18n`` is imported lazily inside the one function
that needs a translated message). It pulls in no Qt and no other app
module, so it sits at the bottom of the dependency graph and is safe to
import from ``app.base`` and ``app.editor.tab`` alike with no import
cycle.
"""

import contextlib
import os
import sys
import tempfile
from typing import Iterable

__all__ = ["atomic_pdf_write", "check_not_same_path", "is_file_in_use_error",
           "is_same_file", "resolves_to_any"]


def _same_by_path(a: str, b: str) -> bool:
    return (os.path.normcase(os.path.realpath(a))
            == os.path.normcase(os.path.realpath(b)))


def is_same_file(a: str, b: str) -> bool:
    """Are ``a`` and ``b`` the same file, also through another hard link?

    False when either does not exist. ``os.path.samefile`` compares only
    ``st_ino`` and ``st_dev``; a file system with no file id reports 0
    there (on Windows, some virtual and network drives), and then every
    file on it would be the same file, so only the paths can tell.
    """
    try:
        sa, sb = os.stat(a), os.stat(b)
    except OSError:
        return False
    if 0 in (sa.st_ino, sa.st_dev, sb.st_ino, sb.st_dev):
        return _same_by_path(a, b)
    return os.path.samestat(sa, sb)


def resolves_to_any(dst: str,
                    sources: "Iterable[str] | None" = None) -> bool:
    """Would writing ``dst`` replace one of ``sources``?

    :func:`is_same_file` catches what ``realpath`` cannot: another hard
    link to the same file.
    """
    try:
        dst_real = os.path.realpath(dst)
    except OSError:
        return False
    for src in (sources or ()):
        if not src:
            continue
        try:
            if os.path.realpath(src) == dst_real or is_same_file(src, dst):
                return True
        except OSError:
            continue
    return False


def check_not_same_path(dst: str,
                        sources: "Iterable[str] | None" = None) -> None:
    """Raise RuntimeError if ``dst`` resolves to any of ``sources``
    (:func:`resolves_to_any`).

    Shared invariant for every tool that takes a PDF in and writes
    a result back to disk: if the user picks the same path for
    input and output, opening the output for writing truncates the
    input before the writer's lazy stream reads complete and we
    get silent dataloss + corrupted output.
    """
    from app.i18n import t
    if resolves_to_any(dst, sources):
        raise RuntimeError(t("tool.err.same_source_output"))


# ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION.
# Measured on Windows 11 with PyMuPDF 1.28.2 holding the file open:
# os.replace onto it fails with 5 and os.unlink with 32; os.replace onto a
# read-only file fails with 5 too. Python maps all three to PermissionError.
_WIN_FILE_IN_USE = frozenset({5, 32, 33})
# ERROR_USER_MAPPED_FILE: measured, shutil.copy2 onto a file another
# handle has memory-mapped fails with it as an OSError (errno 22), with
# no file name. Only an existing, open file can be mapped.
_WIN_USER_MAPPED_FILE = 1224


def is_file_in_use_error(exc: BaseException, platform: "str | None" = None) -> bool:
    """Did Windows refuse to let us read or write an existing file, because
    a program holds it open (the viewer included) or it is read-only?

    The file named is ``filename2`` for ``os.replace`` (its destination),
    ``filename`` otherwise. One that does not exist, such as a temp file
    in a folder that cannot be written, is another problem, which closing
    a file would not solve.
    """
    if platform is None:
        platform = sys.platform
    if platform != "win32" or not isinstance(exc, OSError):
        return False
    winerror = getattr(exc, "winerror", None)
    if winerror == _WIN_USER_MAPPED_FILE:
        return True
    if not isinstance(exc, PermissionError):
        return False
    if winerror is not None and winerror not in _WIN_FILE_IN_USE:
        return False
    target = exc.filename2 or exc.filename
    if not isinstance(target, (str, os.PathLike)):
        return False
    return os.path.isfile(target)


def atomic_pdf_write(writer, dst: str, *,
                     sources: "Iterable[str] | None" = None,
                     save_opts: "dict | None" = None,
                     close_writer: bool = False) -> None:
    """Write a PdfWriter (pypdf) or pymupdf.Document to ``dst`` atomically.

    Two defensive layers fix the silent dataloss bug where opening
    ``open(dst, "wb")`` truncates the input file BEFORE the writer's
    lazy stream reads complete (PdfWriter holds references into
    the PdfReader; same applies to pymupdf.Document.save() with
    incremental flags).

    1. Reject up-front if ``dst`` resolves to any path in
       ``sources`` (via ``os.path.realpath``, or is another hard link to
       one, see :func:`check_not_same_path`). This catches the
       "user picked the same path for input and output" case which
       was producing corrupt output + losing the original.

    2. Write to a same-directory tempfile and atomically rename to
       ``dst`` via :func:`os.replace` (works on POSIX and Windows).

    ``writer`` may be a pypdf ``PdfWriter`` (uses ``writer.write(fh)``)
    or a PyMuPDF ``pymupdf.Document`` (uses ``writer.save(tmp)``).
    Anything else with a ``.write(fh)`` method is accepted.

    ``close_writer`` closes the writer AFTER a successful save but
    BEFORE ``os.replace``. The visual editor needs this: it opens the
    document from the SAME file it may be overwriting, so on Windows
    the handle must be released before the rename or ``os.replace``
    fails with a sharing violation. The tool pages leave the writer
    open (default ``False``) — they never save back onto the input
    handle, and some reuse the writer/doc after the call.

    Raises :class:`RuntimeError` with a translated message when the
    same-source check fails; the caller's existing ``show_error``
    path surfaces it as a friendly dialog.
    """
    check_not_same_path(dst, sources)

    dst_dir = os.path.dirname(dst) or os.getcwd()
    # mkstemp returns an OS-level fd; close via os.fdopen so the
    # writer can stream into it. Same-volume placement guarantees
    # os.replace() stays atomic.
    fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=dst_dir)
    # Detect pymupdf.Document via its module to avoid importing PyMuPDF
    # here (this module is imported by every page through BasePage).
    # Document reports module="pymupdf" on every PyMuPDF from 1.24.3,
    # the first release where ``import pymupdf`` exists, even when
    # reached through the deprecated ``fitz`` alias, which re-exports the
    # same class; only releases from before the package rename said
    # "fitz". The floor in requirements.txt is not a guarantee here:
    # distribution channels ship older builds (Fedora 44 shipped 1.27.1).
    writer_mod = type(writer).__module__
    is_pymupdf_doc = writer_mod.startswith("pymupdf") and hasattr(writer, "save")
    try:
        if is_pymupdf_doc:
            # pymupdf.Document.save(path, ...) accepts a filesystem
            # path and writes through cleanly. We close the fd
            # we opened first so save() can take exclusive access.
            os.close(fd)
            writer.save(tmp, **(save_opts or {}))
        else:
            # pypdf.PdfWriter (and anything else with .write(fh))
            # streams into the open file handle.
            with os.fdopen(fd, "wb") as fh:
                writer.write(fh)
        # Release the writer's file lock (if any) before the rename —
        # see the ``close_writer`` note in the docstring. Placed
        # between save and replace to preserve the editor's original
        # save→close→replace ordering exactly.
        if close_writer:
            writer.close()
        os.replace(tmp, dst)
    except Exception:
        with contextlib.suppress(Exception):
            if os.path.exists(tmp):
                os.unlink(tmp)
        raise
