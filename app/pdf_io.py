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
import tempfile
from typing import Iterable

__all__ = ["atomic_pdf_write", "check_not_same_path"]


def check_not_same_path(dst: str,
                        sources: "Iterable[str] | None" = None) -> None:
    """Raise RuntimeError if ``dst`` resolves to any of ``sources``.

    Shared invariant for every tool that takes a PDF in and writes
    a result back to disk: if the user picks the same path for
    input and output, opening the output for writing truncates the
    input before the writer's lazy stream reads complete and we
    get silent dataloss + corrupted output.
    """
    from app.i18n import t
    try:
        dst_real = os.path.realpath(dst)
    except OSError:
        return
    for src in (sources or ()):
        if not src:
            continue
        try:
            if os.path.realpath(src) == dst_real:
                raise RuntimeError(t("tool.err.same_source_output"))
        except OSError:
            continue


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
       ``sources`` (via ``os.path.realpath``) — this catches the
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
