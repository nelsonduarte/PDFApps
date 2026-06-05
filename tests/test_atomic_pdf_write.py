"""Regression tests for BasePage._atomic_pdf_write / _check_not_same_path
(N7-CRIT-1).

The bug: 8 PDF tools wrote output with ``open(out_path, "wb")``. When
the user picked the same path for input and output, the ``open("wb")``
truncated the original PDF BEFORE PdfWriter's lazy stream reads
completed → silent dataloss + corrupted output.

The fix landed two defensive layers in ``BasePage``:

1. ``_check_not_same_path`` rejects up-front via ``os.path.realpath``
   equality.

2. ``_atomic_pdf_write`` writes to a same-directory tempfile and
   atomically renames via ``os.replace``.

These tests exercise both layers without instantiating a QWidget —
the helpers are ``@staticmethod`` exactly so they can be unit-tested
straight from the class.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# A QCoreApplication is needed by app.i18n.t() (it calls QSettings).
# Use the offscreen platform so headless CI doesn't try to open a
# display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

from app.base import BasePage  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402


def _make_pdf(path: Path, pages: int = 2) -> Path:
    import fitz
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=595, height=842)
    doc.save(str(path))
    doc.close()
    return path


def _writer_for(path: Path) -> PdfWriter:
    r = PdfReader(str(path))
    w = PdfWriter()
    for page in r.pages:
        w.add_page(page)
    return w


# ── _check_not_same_path ────────────────────────────────────────────────


def test_check_rejects_exact_same_path(tmp_path: Path):
    src = _make_pdf(tmp_path / "in.pdf")
    with pytest.raises(RuntimeError):
        BasePage._check_not_same_path(str(src), [str(src)])


def test_check_rejects_via_realpath(tmp_path: Path):
    """A relative path and an absolute path to the same file must
    both flag as colliding (realpath equality)."""
    src = _make_pdf(tmp_path / "in.pdf")
    rel = os.path.relpath(str(src))
    with pytest.raises(RuntimeError):
        BasePage._check_not_same_path(rel, [str(src)])


def test_check_allows_distinct_paths(tmp_path: Path):
    src = _make_pdf(tmp_path / "in.pdf")
    dst = tmp_path / "out.pdf"
    # Must not raise.
    BasePage._check_not_same_path(str(dst), [str(src)])


def test_check_skips_empty_or_missing_sources(tmp_path: Path):
    dst = tmp_path / "out.pdf"
    # Empty string + None + non-existent are all tolerated.
    BasePage._check_not_same_path(str(dst), ["", None, str(tmp_path / "ghost.pdf")])


# ── _atomic_pdf_write (PdfWriter branch) ────────────────────────────────


def test_atomic_write_same_source_raises_and_preserves_input(tmp_path: Path):
    """The defining regression: dst == src must raise BEFORE any
    bytes hit disk, and the source PDF must remain readable."""
    src = _make_pdf(tmp_path / "in.pdf", pages=3)
    src_bytes_before = src.read_bytes()
    w = _writer_for(src)
    with pytest.raises(RuntimeError):
        BasePage._atomic_pdf_write(w, str(src), sources=[str(src)])
    # Critical assertion: the source file is byte-identical.
    assert src.read_bytes() == src_bytes_before
    # And still parses correctly.
    assert len(PdfReader(str(src)).pages) == 3


def test_atomic_write_writes_to_distinct_dst(tmp_path: Path):
    src = _make_pdf(tmp_path / "in.pdf", pages=2)
    dst = tmp_path / "out.pdf"
    w = _writer_for(src)
    BasePage._atomic_pdf_write(w, str(dst), sources=[str(src)])
    assert dst.exists()
    assert len(PdfReader(str(dst)).pages) == 2


def test_atomic_write_uses_os_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The implementation MUST use os.replace for the final rename —
    that's what makes the write atomic on Windows + POSIX. If a future
    refactor swaps in os.rename or shutil.move this test catches it."""
    src = _make_pdf(tmp_path / "in.pdf")
    dst = tmp_path / "out.pdf"
    w = _writer_for(src)

    calls = []
    real_replace = os.replace

    def spy(a, b):
        calls.append((a, b))
        return real_replace(a, b)

    monkeypatch.setattr("app.base.os.replace", spy)
    BasePage._atomic_pdf_write(w, str(dst), sources=[str(src)])
    assert calls, "os.replace was not called — the rename isn't atomic"
    assert calls[-1][1] == str(dst)


def test_atomic_write_cleans_tempfile_on_writer_error(tmp_path: Path):
    """If writer.write raises, the tempfile must be cleaned up — we
    don't want orphans accumulating in the user's output folder."""
    dst = tmp_path / "out.pdf"

    class _Boom:
        def write(self, _fh):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        BasePage._atomic_pdf_write(_Boom(), str(dst), sources=[])
    # No tempfile lingering in the destination directory.
    leftover = [p for p in tmp_path.iterdir() if p.suffix == ".pdf"]
    assert leftover == []


# ── _atomic_pdf_write (fitz.Document branch) ────────────────────────────


def test_atomic_write_accepts_fitz_document(tmp_path: Path):
    import fitz
    src = _make_pdf(tmp_path / "in.pdf", pages=2)
    dst = tmp_path / "out.pdf"
    doc = fitz.open(str(src))
    try:
        BasePage._atomic_pdf_write(doc, str(dst),
                                   sources=[str(src)],
                                   save_opts={"garbage": 4, "deflate": True})
    finally:
        doc.close()
    assert dst.exists()
    assert len(fitz.open(str(dst))) == 2


def test_atomic_write_fitz_rejects_same_source(tmp_path: Path):
    import fitz
    src = _make_pdf(tmp_path / "in.pdf")
    src_bytes_before = src.read_bytes()
    doc = fitz.open(str(src))
    try:
        with pytest.raises(RuntimeError):
            BasePage._atomic_pdf_write(doc, str(src), sources=[str(src)])
    finally:
        doc.close()
    # Source intact.
    assert src.read_bytes() == src_bytes_before
