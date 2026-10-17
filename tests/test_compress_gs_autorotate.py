"""Regression tests: the Ghostscript pass of ``_compress_pdf`` must not
turn pages.

The bug: pass A ran gs with ``-dPDFSETTINGS=/screen`` (extreme) or
``/ebook`` (recommended, the default level) and no ``AutoRotatePages``.
Those presets set ``AutoRotatePages`` to ``/PageByPage`` and ``/All``
(``Resource/Init/gs_pdfwr.ps``). ``/screen`` (``/PageByPage``) turns each
page to its own dominant text direction; ``/ebook`` (``/All``) applies the
rotation of the whole document's dominant direction to every page.
Measured with gs 9.55.0, 10.05.0 and 10.06.0 and the production
arguments: a ``/Rotate 180`` page with upright text came out upside down,
a ``/Rotate 0`` page of text at 90 degrees (a table set sideways) came out
landscape, and a ``/Rotate 90`` page of horizontal text came out at 270.
Under ``/ebook`` a page of horizontal text came out turned because the
next page held text at 90 degrees, and a ``/Rotate 90`` page was not
turned to the direction of its own text.
Whenever pass A produced the smallest file, that was the file the user got.
``/printer`` (low) already defaults to ``/None``.

The fix passes ``-dAutoRotatePages=/None`` on every level. Ghostscript
documents the switch under "Setting page orientation" in
https://ghostscript.readthedocs.io/en/latest/VectorDevices.html.

The first test fakes ``_find_gs``, ``subprocess.Popen`` and
``subprocess.run`` and checks the argv, so it runs without Ghostscript.
The others run the real gs and are skipped when ``_find_gs()`` finds none.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import utils  # noqa: E402

_FLAG = "-dAutoRotatePages=/None"

_PRESETS = {"extreme": "/screen", "recommended": "/ebook", "low": "/printer"}


# ── argv of pass A (no Ghostscript needed) ───────────────────────────────

class _FakeProc:
    returncode = 1

    def poll(self):
        return 1

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 1

    def kill(self):
        pass


def _fake_version_run(args, **kwargs):
    return subprocess.CompletedProcess(args, 0, stdout=b"10.05.0\n",
                                       stderr=b"")


@pytest.mark.parametrize("level", ["extreme", "recommended", "low"])
def test_pass_a_turns_off_auto_rotation_on_every_level(
        monkeypatch, tmp_path, level):
    src = tmp_path / "in put é.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "hello")
    doc.save(str(src))
    doc.close()

    gs = str(tmp_path / "gs bin" / "gs")
    calls: list[list[str]] = []

    def fake_popen(cmd, **kwargs):
        calls.append(list(cmd))
        return _FakeProc()

    monkeypatch.setattr(utils, "_find_gs", lambda: gs)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", _fake_version_run)
    try:
        utils._compress_pdf(str(src), str(tmp_path / "out.pdf"), level=level)
    except (ValueError, RuntimeError):
        pass  # no size gain on a one-line PDF; only the gs argv matters

    assert len(calls) == 1, calls
    cmd = calls[0]
    assert cmd[0] == gs
    # The level really reached pass A (an unknown level never spawns gs).
    assert f"-dPDFSETTINGS={_PRESETS[level]}" in cmd
    assert cmd.count(_FLAG) == 1, cmd
    assert [a for a in cmd if a.startswith("-dAutoRotatePages=")] == [_FLAG]
    # gs applies a switch only to the input files that follow it.
    assert cmd.index(_FLAG) < len(cmd) - 1
    assert cmd[-1] == utils._win_short_path(str(src))


# ── real Ghostscript ─────────────────────────────────────────────────────

_needs_gs = pytest.mark.skipif(not utils._find_gs(),
                               reason="Ghostscript not installed")

_RENDER_DPI = 36

# Mean absolute difference per grey pixel (0..255) between the source and
# the output render. Measured with gs 10.05.0 on these fixtures: 0.0 with
# the flag on every page; without it the /Rotate 180 page differs by
# 11.01 and the other pages change size, except page 1 of "mixed2" under
# /screen, which gs leaves alone.
_MAX_MEAN_DIFF = 1.0


def _add_page(doc, kind: str, lines: int = 20) -> None:
    page = doc.new_page(width=595, height=842)
    # The full font program, embedded: gs subsets it, so pass A ends far
    # below the source size and the run never stops at "no gain".
    page.insert_font(fontname="F1", fontbuffer=pymupdf.Font("helv").buffer)
    if kind == "text90":
        for k in range(18):
            page.insert_text((60 + 26 * k, 780),
                             f"Line {k} of a table set sideways at 90 degrees",
                             fontname="F1", fontsize=12, rotate=90)
    else:
        for k in range(lines):
            page.insert_text((60, 60 + 28 * k),
                             f"Line {k} of a page stored with a /Rotate entry",
                             fontname="F1", fontsize=12)
        page.set_rotation({"rotate180": 180, "rotate90": 90}.get(kind, 0))


def _make(path: Path, kind: str) -> Path:
    doc = pymupdf.open()
    if kind == "mixed2":
        # Page 2 must hold most of the document's text: /ebook (/All)
        # then turns page 1 as well, to the direction of page 2. With 20
        # lines on page 1 the horizontal text dominates and gs turns
        # neither page under /ebook.
        _add_page(doc, "text0", lines=4)
        _add_page(doc, "text90")
    else:
        _add_page(doc, kind)
    doc.save(str(path))
    doc.close()
    return path


def _view(path: Path):
    """What a viewer shows: per page displayed size and grey render, and
    the producer."""
    with pymupdf.open(str(path)) as doc:
        pages = []
        for page in doc:
            pix = page.get_pixmap(dpi=_RENDER_DPI, colorspace=pymupdf.csGRAY)
            rect = (round(page.rect.width), round(page.rect.height))
            pages.append((rect, (pix.width, pix.height), bytes(pix.samples)))
        return pages, doc.metadata.get("producer") or ""


def _compress_with_pass_a_only(src: Path, dst: Path, level: str) -> None:
    # Pass B and pass C would replace pass A's file whenever theirs is
    # smaller, and which pass wins depends on the PyMuPDF and pikepdf
    # versions. Pass B's save raising leaves it with no output (its
    # except clause swallows the error); pass C cannot import pikepdf.
    def no_save(self, *args, **kwargs):
        raise RuntimeError("pass B disabled by the test")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pymupdf.Document, "save", no_save)
        mp.setitem(sys.modules, "pikepdf", None)
        before, after = utils._compress_pdf(str(src), str(dst), level=level)
    assert after < before


@_needs_gs
@pytest.mark.parametrize("level", ["recommended", "extreme"])
@pytest.mark.parametrize("kind, src_rects", [
    pytest.param("rotate180", [(595, 842)], id="rotate180"),
    pytest.param("text90", [(595, 842)], id="text90"),
    pytest.param("rotate90", [(842, 595)], id="rotate90"),
    pytest.param("mixed2", [(595, 842), (595, 842)], id="mixed2"),
])
def test_gs_pass_keeps_page_orientation(tmp_path, level, kind, src_rects):
    src = _make(tmp_path / f"{kind} é.pdf", kind)
    dst = tmp_path / f"out {kind} ç.pdf"
    s_pages, _ = _view(src)
    assert [rect for rect, _, _ in s_pages] == src_rects

    _compress_with_pass_a_only(src, dst, level)

    o_pages, producer = _view(dst)
    assert "Ghostscript" in producer, (
        f"the output did not come from pass A (producer {producer!r})")
    assert len(o_pages) == len(s_pages)
    for n, ((s_rect, s_size, s_px), (o_rect, o_size, o_px)) in enumerate(
            zip(s_pages, o_pages), start=1):
        assert o_rect == s_rect, (
            f"gs turned page {n}: displayed {o_rect}, source {s_rect}")
        assert o_size == s_size
        diff = sum(abs(a - b) for a, b in zip(s_px, o_px)) / len(s_px)
        assert diff <= _MAX_MEAN_DIFF, (
            f"page {n} does not look like the source (mean grey "
            f"difference {diff:.2f}); gs turned its content")
