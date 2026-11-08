"""Page renders must never build or touch a QPixmap off the GUI thread.

Qt only allows ``QPixmap`` on the GUI thread; ``QImage`` may be used on
any thread. Both page renderers (``_PageJob`` in the viewer,
``_EditPageJob`` in the editor) used to build the QPixmap inside the
pool worker (``QPixmap.loadFromData``), and a hang was caught with the
pool thread inside that call while the GUI thread was laying out pages.

The guard swaps ``PySide6.QtGui.QPixmap`` (what a function-local
``from PySide6.QtGui import QPixmap`` reads at call time, the form the
old workers used) and the module-level ``QPixmap`` names of the render
modules (bound at import time, which patching ``PySide6.QtGui`` alone
would miss) for a subclass that records every construction or use made
from a thread other than ``threading.main_thread()``.
"""

from __future__ import annotations

import faulthandler
import gc
import importlib
import os
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtGui
from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QScrollArea

_app = QApplication.instance() or QApplication([])

import pymupdf

import app.editor.canvas as editor_canvas
import app.viewer.canvas as viewer_canvas
from app.editor.canvas import PdfEditCanvas
from app.viewer.canvas import _SelectCanvas

_REAL_QPIXMAP = QPixmap
_N_PAGES = 6
_RENDER_DEADLINE_S = 20.0


# ── Fixtures ────────────────────────────────────────────────────────────


def _make_pdf(path: Path, n_pages: int = _N_PAGES) -> Path:
    """Pages with text, an opaque image and an image with an alpha
    channel (SMask), so the rendered page mixes all three."""
    doc = pymupdf.open()
    opaque = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 24, 24), 0)
    opaque.clear_with(90)
    translucent = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 24, 24), 1)
    translucent.clear_with(200)
    translucent.set_alpha(bytes([120]) * (24 * 24))
    for i in range(n_pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"Page {i + 1}: texto com acentos",
                         fontsize=18)
        page.insert_image(pymupdf.Rect(72, 120, 272, 320), pixmap=opaque)
        page.insert_image(pymupdf.Rect(200, 250, 400, 450),
                          pixmap=translucent)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def pdf_path(tmp_path):
    folder = tmp_path / "pasta com espaços ç"
    folder.mkdir()
    return _make_pdf(folder / "páginas de teste.pdf")


@pytest.fixture
def guard(monkeypatch):
    """Patch every QPixmap name the render path can reach; return the
    list that collects off-GUI-thread uses."""
    violations: list[tuple[str, str]] = []

    def _check(what: str) -> None:
        cur = threading.current_thread()
        if cur is not threading.main_thread():
            violations.append((what, cur.name))

    class _GuardedQPixmap(_REAL_QPIXMAP):
        def __init__(self, *args, **kwargs):
            _check("QPixmap()")
            super().__init__(*args, **kwargs)

        def loadFromData(self, *args, **kwargs):
            _check("QPixmap.loadFromData")
            return super().loadFromData(*args, **kwargs)

        def setDevicePixelRatio(self, *args, **kwargs):
            _check("QPixmap.setDevicePixelRatio")
            return super().setDevicePixelRatio(*args, **kwargs)

        @staticmethod
        def fromImage(*args, **kwargs):
            _check("QPixmap.fromImage")
            return _REAL_QPIXMAP.fromImage(*args, **kwargs)

    monkeypatch.setattr(QtGui, "QPixmap", _GuardedQPixmap)
    mods = [viewer_canvas, editor_canvas]
    try:
        mods.append(importlib.import_module("app.page_image"))
    except ImportError:
        pass
    for mod in mods:
        monkeypatch.setattr(mod, "QPixmap", _GuardedQPixmap, raising=False)
    return violations


def _pump_until(cond, deadline_s: float = _RENDER_DEADLINE_S) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        _app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def _host(canvas) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidget(canvas)
    sa.resize(820, 640)
    sa.show()
    _app.processEvents()
    return sa


def _teardown(sa: QScrollArea) -> None:
    sa.close()
    sa.deleteLater()
    for _ in range(5):
        _app.processEvents()


def _open_viewer(path: Path, dpr: float | None = None,
                 night: bool = False):
    canvas = _SelectCanvas()
    if dpr is not None:
        canvas.devicePixelRatioF = lambda: dpr  # type: ignore[method-assign]
    if night:
        canvas._night_mode = True
    sa = _host(canvas)
    canvas.load(pymupdf.open(str(path)), 0, path=str(path))
    assert _pump_until(lambda: bool(canvas._entries)
                       and canvas._entries[0].pixmap is not None
                       and not canvas._pending), "viewer never rendered"
    canvas._pool.waitForDone(5000)
    _app.processEvents()
    return canvas, sa


def _open_editor(path: Path, dpr: float | None = None):
    canvas = PdfEditCanvas()
    if dpr is not None:
        canvas.devicePixelRatioF = lambda: dpr  # type: ignore[method-assign]
    sa = _host(canvas)
    canvas.load(str(path))
    assert _pump_until(lambda: bool(canvas._page_pixmaps)
                       and canvas._page_pixmaps[0] is not None
                       and not canvas._pending), "editor never rendered"
    QThreadPool.globalInstance().waitForDone(5000)
    _app.processEvents()
    return canvas, sa


def _base_reference(path: Path, idx: int, zoom: float, dpr: float,
                    night: bool = False) -> QPixmap:
    """What the workers produced at 1ef2721, rebuilt on the GUI thread:
    PNG round-trip through ``QPixmap.loadFromData`` plus the DPR tag."""
    doc = pymupdf.open(str(path))
    try:
        rz = zoom * dpr
        pix = doc[idx].get_pixmap(matrix=pymupdf.Matrix(rz, rz), annots=False)
        if night:
            pix.invert_irect()
        qp = _REAL_QPIXMAP()
        assert qp.loadFromData(pix.tobytes("png"))
        qp.setDevicePixelRatio(dpr)
        return qp
    finally:
        doc.close()


def _assert_same_pixmap(shown: QPixmap, ref: QPixmap) -> None:
    assert isinstance(shown, _REAL_QPIXMAP)
    assert not shown.isNull()
    assert shown.devicePixelRatio() == ref.devicePixelRatio()
    assert shown.size() == ref.size()
    assert shown.hasAlpha() == ref.hasAlpha()
    # PNG is lossless and the same decoder runs in both paths, so no
    # tolerance is needed: compare the images exactly.
    assert shown.toImage() == ref.toImage()


# ── T1: no QPixmap off the GUI thread ──────────────────────────────────


def test_viewer_render_builds_no_qpixmap_off_gui_thread(guard, pdf_path):
    canvas, sa = _open_viewer(pdf_path)
    try:
        rendered = [e for e in canvas._entries if e.pixmap is not None]
        assert len(rendered) >= 2, "too few pages rendered to prove anything"
        assert guard == [], f"QPixmap used off the GUI thread: {guard[:5]}"
    finally:
        canvas.close_doc()
        _teardown(sa)


def test_editor_render_builds_no_qpixmap_off_gui_thread(guard, pdf_path):
    canvas, sa = _open_editor(pdf_path)
    try:
        rendered = [p for p in canvas._page_pixmaps if p is not None]
        assert len(rendered) >= 2, "too few pages rendered to prove anything"
        assert guard == [], f"QPixmap used off the GUI thread: {guard[:5]}"
    finally:
        canvas.close_doc()
        _teardown(sa)


def test_render_signals_carry_qimage(pdf_path, monkeypatch):
    """What crosses the thread boundary is a QImage that owns its
    pixels, not a QPixmap."""
    seen: list[object] = []
    orig_viewer = _SelectCanvas._on_page_ready
    orig_editor = PdfEditCanvas._on_page_ready

    def _spy_viewer(self, gen, idx, image, words):
        seen.append(image)
        return orig_viewer(self, gen, idx, image, words)

    def _spy_editor(self, gen, idx, image):
        seen.append(image)
        return orig_editor(self, gen, idx, image)

    monkeypatch.setattr(_SelectCanvas, "_on_page_ready", _spy_viewer)
    monkeypatch.setattr(PdfEditCanvas, "_on_page_ready", _spy_editor)
    vc, vsa = _open_viewer(pdf_path)
    ec, esa = _open_editor(pdf_path)
    try:
        assert seen
        assert all(type(x) is QImage and not x.isNull() for x in seen), \
            {type(x).__name__ for x in seen}
    finally:
        vc.close_doc()
        ec.close_doc()
        _teardown(vsa)
        _teardown(esa)


# ── T3: the page shown is the same as before ───────────────────────────


@pytest.mark.parametrize("night", [False, True], ids=["day", "night"])
@pytest.mark.parametrize("dpr", [1.0, 2.0], ids=["dpr1", "dpr2"])
def test_viewer_page_pixels_match_base(pdf_path, dpr, night):
    canvas, sa = _open_viewer(pdf_path, dpr=dpr, night=night)
    try:
        for idx in (0, 1):
            shown = canvas._entries[idx].pixmap
            ref = _base_reference(pdf_path, idx, canvas._zoom, dpr, night)
            _assert_same_pixmap(shown, ref)
            # The page raster stays opaque (get_pixmap's alpha=False),
            # even though the page draws a translucent image.
            assert not shown.hasAlpha()
    finally:
        canvas.close_doc()
        _teardown(sa)


@pytest.mark.parametrize("dpr", [1.0, 2.0], ids=["dpr1", "dpr2"])
def test_editor_page_pixels_match_base(pdf_path, dpr):
    canvas, sa = _open_editor(pdf_path, dpr=dpr)
    try:
        for idx in (0, 1):
            shown = canvas._page_pixmaps[idx]
            ref = _base_reference(pdf_path, idx, canvas._zoom, dpr)
            _assert_same_pixmap(shown, ref)
            assert not shown.hasAlpha()
    finally:
        canvas.close_doc()
        _teardown(sa)


def test_page_image_owns_its_pixels_after_document_close(pdf_path):
    from app.page_image import render_page_image
    doc = pymupdf.open(str(pdf_path))
    img = render_page_image(doc[0], 1.25, 2.0)
    ref = _base_reference(pdf_path, 0, 1.25, 2.0).toImage()
    doc.close()
    del doc
    gc.collect()
    assert type(img) is QImage
    assert img.devicePixelRatio() == 2.0
    assert img == ref


def test_page_image_fallback_matches_png_path(pdf_path, monkeypatch):
    """If the PNG decode fails, the samples fallback must give the same
    pixels and DPR, and own its buffer once the document is gone."""
    from app import page_image
    doc = pymupdf.open(str(pdf_path))
    try:
        normal = page_image.render_page_image(doc[0], 1.0, 2.0)
    finally:
        doc.close()

    class _NoDecode(QImage):
        def loadFromData(self, *args, **kwargs):
            return False

    monkeypatch.setattr(page_image, "QImage", _NoDecode)
    doc = pymupdf.open(str(pdf_path))
    fallback = page_image.render_page_image(doc[0], 1.0, 2.0)
    doc.close()
    del doc
    gc.collect()
    assert fallback.devicePixelRatio() == 2.0
    assert fallback.size() == normal.size()
    fmt = QImage.Format.Format_RGB32
    assert fallback.convertToFormat(fmt) == normal.convertToFormat(fmt)


# ── T2: stress, must not hang ──────────────────────────────────────────


_STRESS_ROUNDS = 6
_STRESS_WATCHDOG_S = 120


def test_viewer_open_close_zoom_page_stress_does_not_hang(guard, pdf_path,
                                                          tmp_path):
    """Open and close viewer panels while zooming and paging with
    processEvents pumping. faulthandler dumps every stack and kills the
    process if it wedges, instead of hanging the suite."""
    from app.viewer.panel import PdfViewerPanel

    other = _make_pdf(tmp_path / "outro ficheiro.pdf", n_pages=9)
    faulthandler.dump_traceback_later(_STRESS_WATCHDOG_S, exit=True)
    t0 = time.monotonic()
    try:
        for rnd in range(_STRESS_ROUNDS):
            panel = PdfViewerPanel()
            panel.resize(900, 700)
            panel.show()
            panel.load(str(pdf_path if rnd % 2 == 0 else other))
            canvas = panel._canvas
            for step in range(10):
                if step % 3 == 0:
                    canvas.zoom_in()
                elif step % 3 == 1:
                    canvas.zoom_out()
                else:
                    panel._next_page()
                for _ in range(3):
                    _app.processEvents()
                if step == 5:
                    # Swap the document mid-render.
                    panel.load(str(other if rnd % 2 == 0 else pdf_path))
            _pump_until(lambda c=canvas: not c._pending, deadline_s=5.0)
            canvas._pool.waitForDone(5000)
            panel.close()
            panel.deleteLater()
            for _ in range(5):
                _app.processEvents()
        elapsed = time.monotonic() - t0
    finally:
        faulthandler.cancel_dump_traceback_later()
    assert elapsed < _STRESS_WATCHDOG_S
    assert guard == [], f"QPixmap used off the GUI thread: {guard[:5]}"


def test_editor_zoom_reload_stress_does_not_hang(guard, pdf_path, tmp_path):
    other = _make_pdf(tmp_path / "outro editor.pdf", n_pages=9)
    faulthandler.dump_traceback_later(_STRESS_WATCHDOG_S, exit=True)
    try:
        canvas = PdfEditCanvas()
        sa = _host(canvas)
        for rnd in range(_STRESS_ROUNDS):
            canvas.load(str(pdf_path if rnd % 2 == 0 else other))
            for step in range(8):
                (canvas.zoom_in if step % 2 == 0 else canvas.zoom_out)()
                for _ in range(3):
                    _app.processEvents()
            _pump_until(lambda c=canvas: not c._pending, deadline_s=5.0)
        QThreadPool.globalInstance().waitForDone(5000)
        canvas.close_doc()
        _teardown(sa)
    finally:
        faulthandler.cancel_dump_traceback_later()
    assert guard == [], f"QPixmap used off the GUI thread: {guard[:5]}"
