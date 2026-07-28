"""Regression tests for the import-encoding / zero-page / editor-doc audit.

Bug map (adversarial bug hunt):

* MAJOR #1 — ``TabImport`` TXT/MD/HTML converters read user files with a
  strict ``open(..., encoding="utf-8")`` (no ``errors=``), so a Notepad/
  Excel ``.txt`` saved as Windows-1252/Latin-1 crashed the real
  conversion with ``UnicodeDecodeError`` — *after* the font pre-scan (which
  already used ``errors="replace"``) had told the user the file was fine.
  The fix aligns the three ``do_work`` read sites with the pre-scan.

* MINOR #2 — when every input was empty/rejected the ``fitz.Document``
  had zero pages and ``doc.save()`` raised the cryptic
  ``ValueError: cannot save with zero pages`` (in ``_convert_images`` this
  also masked the "N images skipped" feedback). The fix returns a
  ``_NoContent`` sentinel that drives the friendly, translated
  ``tool.import.no_content`` message.

* MINOR #3 — ``PdfEditCanvas.load`` closed the previous doc then assigned
  ``self._doc = fitz.open(path)``. A corrupt PDF that raised left
  ``self._doc`` pointing at the *already-closed* Document (use-after-close).
  The fix clears ``self._doc`` before ``fitz.open`` and only publishes on
  success.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# A QApplication is needed by app.i18n.t() and by the tool/canvas widgets
# we instantiate. Offscreen keeps headless CI display-free.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402
_unused_app = QApplication.instance() or QApplication([])

import fitz  # noqa: E402

from app.i18n import t  # noqa: E402
from app.tools.import_pdf import (  # noqa: E402
    TabImport, _NoContent, QMessageBox,
)
from app.editor.canvas import PdfEditCanvas  # noqa: E402


class _FakeWorker:
    """Minimal TaskRunner stand-in for driving a captured do_work()."""

    def is_cancelled(self):
        return False

    class _Sig:
        def emit(self, *a, **k):
            pass

    progress = _Sig()


def _make_page():
    """A TabImport whose status messages are captured into ``.messages``."""
    msgs = []
    page = TabImport(status_fn=msgs.append)
    page.messages = msgs
    return page


def _drive(page, method_name, sources, out_path, monkeypatch):
    """Call a converter but intercept ``_run_background`` so the closure
    runs synchronously on a fake worker. Returns (result, on_done)."""
    captured = {}

    def fake_bg(do_work_fn, total, label, on_done=None, on_err=None,
                cancelled_status=""):
        captured["do_work"] = do_work_fn
        captured["on_done"] = on_done

    monkeypatch.setattr(page, "_run_background", fake_bg)
    getattr(page, method_name)(sources, out_path)
    result = captured["do_work"](_FakeWorker())
    return result, captured["on_done"]


# ── MAJOR #1 — legacy encodings tolerated ────────────────────────────────


def test_txt_cp1252_produces_valid_pdf(tmp_path, monkeypatch):
    """A .txt written as Windows-1252 (``Ol\\xe1 mundo``) must convert
    without UnicodeDecodeError. With the strict-utf8 bug the do_work
    closure raised before producing any output."""
    src = tmp_path / "cp1252.txt"
    src.write_bytes(b"Ol\xe1 mundo")  # 0xE1 = 'á' in cp1252, invalid utf-8
    out = tmp_path / "out.pdf"

    result, _ = _drive(_make_page(), "_convert_txt", [str(src)], str(out),
                       monkeypatch)

    assert result == str(out)
    assert out.exists()
    doc = fitz.open(str(out))
    try:
        assert doc.page_count >= 1
    finally:
        doc.close()


def test_md_latin1_produces_valid_pdf(tmp_path, monkeypatch):
    """Latin-1 .md must not crash the real conversion."""
    src = tmp_path / "latin1.md"
    src.write_bytes(b"# Caf\xe9\n\nvinho \xe0 mesa")  # invalid utf-8 bytes
    out = tmp_path / "out.pdf"

    result, _ = _drive(_make_page(), "_convert_md", [str(src)], str(out),
                       monkeypatch)

    assert result == str(out)
    assert out.exists()
    doc = fitz.open(str(out))
    try:
        assert doc.page_count >= 1
    finally:
        doc.close()


def test_html_latin1_produces_valid_pdf(tmp_path, monkeypatch):
    """Latin-1 .html must not crash the real conversion."""
    pytest.importorskip("bs4")
    src = tmp_path / "latin1.html"
    src.write_bytes(
        b"<html><body><p>caf\xe9 \xe0 la maison</p></body></html>")
    out = tmp_path / "out.pdf"

    result, _ = _drive(_make_page(), "_convert_html", [str(src)], str(out),
                       monkeypatch)

    assert result == str(out)
    assert out.exists()
    doc = fitz.open(str(out))
    try:
        assert doc.page_count >= 1
    finally:
        doc.close()


def test_strict_utf8_read_would_have_raised(tmp_path):
    """Guard the premise: the cp1252 bytes really are invalid utf-8, so a
    strict read (the old behaviour) *would* have raised. This keeps the
    above tests honest — they'd pass trivially if the bytes were ASCII."""
    src = tmp_path / "cp1252.txt"
    src.write_bytes(b"Ol\xe1 mundo")
    with pytest.raises(UnicodeDecodeError):
        with open(src, "r", encoding="utf-8") as f:
            f.read()


# ── MINOR #2 — zero-page save guarded ────────────────────────────────────


def test_images_all_rejected_returns_no_content(tmp_path, monkeypatch):
    """Dropping only non-image files into the image list leaves the doc
    page-less. do_work must return a _NoContent sentinel (not let
    doc.save() raise ValueError) and preserve any skip count."""
    not_images = [str(tmp_path / "a.txt"), str(tmp_path / "b.pdf")]
    for p in not_images:
        Path(p).write_text("x")
    out = tmp_path / "out.pdf"

    result, on_done = _drive(_make_page(), "_convert_images", not_images,
                             str(out), monkeypatch)

    assert isinstance(result, _NoContent)
    assert not out.exists()  # nothing written


def test_no_content_on_done_shows_friendly_message(tmp_path, monkeypatch):
    """The images on_done must surface tool.import.no_content via a
    warning box instead of crashing — and must NOT call self._done."""
    not_images = [str(tmp_path / "a.txt")]
    Path(not_images[0]).write_text("x")
    out = tmp_path / "out.pdf"
    page = _make_page()

    warned = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.setdefault("text", a[2]))
    done_called = []
    monkeypatch.setattr(page, "_done", lambda p: done_called.append(p))

    result, on_done = _drive(page, "_convert_images", not_images, str(out),
                             monkeypatch)
    on_done(result)  # must not raise ValueError

    assert warned.get("text") == t("tool.import.no_content")
    assert not done_called
    assert not out.exists()


def test_docx_zero_page_guarded(monkeypatch):
    """The docx converter shares the zero-page guard: a doc left page-less
    returns _NoContent rather than raising on save. Simulated with an
    empty source list so no python-docx dependency is required."""
    pytest.importorskip("docx")
    out = "unused.pdf"
    page = _make_page()
    result, _ = _drive(page, "_convert_docx", [], out, monkeypatch)
    assert isinstance(result, _NoContent)


def test_no_content_key_present_in_all_languages():
    """tool.import.no_content must ship for all 8 supported languages so
    t() never falls back to the raw key name, and must not carry a stray
    {n} placeholder (it takes no arguments)."""
    import json
    root = Path(__file__).resolve().parent.parent
    data = json.loads((root / "app" / "translations.json").read_text(
        encoding="utf-8"))
    assert set(data.keys()) == {"en", "pt", "es", "fr", "de", "zh", "it",
                                "nl"}
    for lang, kv in data.items():
        assert "tool.import.no_content" in kv, f"missing in {lang}"
        assert "{n}" not in kv["tool.import.no_content"], lang


# ── MINOR #3 — corrupt load leaves _doc None, not a closed doc ────────────


def _valid_pdf(path: Path) -> Path:
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(str(path))
    doc.close()
    return path


def test_canvas_load_corrupt_leaves_doc_none(tmp_path):
    """A corrupt PDF that makes fitz.open raise must leave self._doc as
    None — not a reference to the previous, already-closed Document."""
    canvas = PdfEditCanvas()

    good = _valid_pdf(tmp_path / "good.pdf")
    canvas.load(str(good))
    assert canvas._doc is not None
    assert canvas.page_count() >= 1

    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not a pdf at all")
    with pytest.raises(Exception):
        canvas.load(str(corrupt))

    # The core assertion: no dangling closed-Document reference.
    assert canvas._doc is None
    assert canvas.page_count() == 0


def test_canvas_reload_valid_after_failed_load(tmp_path):
    """After a failed load, a subsequent valid load must work — proving
    the None reset didn't wedge the canvas into a broken state."""
    canvas = PdfEditCanvas()

    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF garbage not really")
    with pytest.raises(Exception):
        canvas.load(str(corrupt))
    assert canvas._doc is None

    good = _valid_pdf(tmp_path / "good.pdf")
    canvas.load(str(good))
    assert canvas._doc is not None
    assert canvas.page_count() >= 1
