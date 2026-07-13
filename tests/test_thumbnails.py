"""Regression tests for the viewer thumbnails sidebar.

Blends source-level guards (cheap, no Qt event loop needed) with
behavioural tests on the ``ThumbnailModel`` (which is pure Qt data, no
threading). Full end-to-end rendering requires a real ``QApplication``
and is exercised by the smoke import + manual QA on the release
candidate — see the parent task's manual test plan.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Headless-safe: the end-to-end render test builds real QWidgets, so a
# QApplication on the offscreen platform must exist before Qt classes
# are dereferenced (matches tests/test_atomic_pdf_write.py).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


THUMBS_SRC = (ROOT / "app" / "viewer" / "thumbnails.py").read_text(
    encoding="utf-8")
PANEL_SRC = (ROOT / "app" / "viewer" / "panel.py").read_text(
    encoding="utf-8")


# ── Import / API surface ──────────────────────────────────────────────


def test_module_imports():
    from app.viewer import thumbnails
    assert hasattr(thumbnails, "ThumbnailPanel")
    assert hasattr(thumbnails, "ThumbnailModel")
    assert hasattr(thumbnails, "ThumbnailDelegate")
    assert hasattr(thumbnails, "ThumbnailWorker")


def test_public_signal_present():
    """Guards against a rename of the signal the viewer wires into."""
    assert "page_requested" in THUMBS_SRC
    assert "Signal(int)" in THUMBS_SRC


def test_worker_uses_qthread():
    assert "class ThumbnailWorker(QThread)" in THUMBS_SRC


def test_worker_pixmap_lifetime_uses_copy():
    """The QImage-from-Pixmap pattern requires .copy() so pixels don't
    disappear when the fitz Pixmap is freed on the next loop iteration
    (same pattern as the print loop and OCR Round 3)."""
    assert ".copy()" in THUMBS_SRC


def test_worker_emits_qimage_not_qpixmap():
    """QPixmap construction is main-thread-only in Qt. The worker must
    emit QImage; the panel converts to QPixmap in a main-thread slot."""
    # Signal should carry QImage, not QPixmap. It also carries the
    # generation/epoch (trailing int) so stale thumbnails from a
    # superseded document can be dropped by the panel.
    assert "Signal(int, QImage, int)" in THUMBS_SRC, (
        "ThumbnailWorker.thumbnail_ready must emit QImage, not QPixmap, "
        "since QPixmap construction requires the main GUI thread"
    )
    # The main-thread slot converts image -> pixmap.
    assert "QPixmap.fromImage" in THUMBS_SRC


def test_signal_uses_queued_connection():
    """Py3.14 PySide6 requires explicit QueuedConnection for
    cross-thread signals so slots run on the receiver's thread
    (see memory/project_compress_freeze_py314.md)."""
    assert "QueuedConnection" in THUMBS_SRC


def test_image_ready_slot_decorated():
    """@Slot decorator on the receiver keeps Py3.14 PySide6 routing
    predictable for cross-thread signal delivery."""
    assert "@Slot(int, QImage, int)" in THUMBS_SRC
    assert "_on_image_ready" in THUMBS_SRC


def test_worker_passes_password_to_fitz():
    """Encrypted PDFs would raise on every page render without this."""
    assert "authenticate" in THUMBS_SRC


def test_delegate_highlights_current_page():
    assert "set_current_page" in THUMBS_SRC
    assert "_current_page" in THUMBS_SRC


def test_cache_has_size_limit():
    """The dict cache must be capped so long PDFs don't leak memory."""
    assert "CACHE_MAX" in THUMBS_SRC


def test_worker_renders_dpr_aware():
    """Thumbnails must render at target_size * devicePixelRatio and tag
    the image with the ratio, otherwise HiDPI screens show a soft,
    upscaled image (regression fix). The DPR must be read live, never
    hardcoded."""
    # Worker takes a dpr and sets it on the emitted image.
    assert "dpr" in THUMBS_SRC
    assert "setDevicePixelRatio" in THUMBS_SRC
    # Render must be matrix-driven (fit to the target box) rather than a
    # fixed low DPI that then gets upscaled on paint.
    assert "fitz.Matrix(zoom, zoom)" in THUMBS_SRC
    assert "dpi=40" not in THUMBS_SRC, (
        "fixed 40 DPI render is the blurry-thumbnail regression"
    )
    # DPR is read off the live widget, not a constant.
    assert "devicePixelRatioF()" in THUMBS_SRC


def test_delegate_scales_dpr_aware():
    """The paint path must scale in device pixels (target * dpr) and
    re-tag the pixmap so the drawn thumbnail is crisp on HiDPI."""
    assert "pix.devicePixelRatio()" in THUMBS_SRC


# ── Model behaviour ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def qapp():
    """Session-scoped QApplication for the model tests. QListView is
    not built here, but QAbstractListModel / QModelIndex constructors
    dereference the Qt runtime, so an app must exist."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_model_starts_empty(qapp):
    from app.viewer.thumbnails import ThumbnailModel
    m = ThumbnailModel()
    assert m.rowCount() == 0
    assert m.cache_size() == 0


def test_model_row_count_matches_page_count(qapp):
    from app.viewer.thumbnails import ThumbnailModel
    m = ThumbnailModel()
    m.set_document("/nonexistent.pdf", 10)
    assert m.rowCount() == 10
    m.clear()
    assert m.rowCount() == 0
    assert m.cache_size() == 0


def test_model_cache_evicts_lru(qapp):
    """Insert CACHE_MAX + 5 pixmaps and confirm the oldest 5 are
    evicted so the cache stays at the cap."""
    from PySide6.QtGui import QPixmap
    from app.viewer.thumbnails import CACHE_MAX, ThumbnailModel
    m = ThumbnailModel()
    m.set_document("/x.pdf", CACHE_MAX + 5)
    for i in range(CACHE_MAX + 5):
        m.cache_pixmap(i, QPixmap(1, 1))
    assert m.cache_size() == CACHE_MAX


def test_model_data_returns_none_out_of_range(qapp):
    from PySide6.QtCore import Qt
    from app.viewer.thumbnails import ThumbnailModel
    m = ThumbnailModel()
    m.set_document("/x.pdf", 3)
    bad = m.index(99)
    assert m.data(bad, Qt.ItemDataRole.DecorationRole) is None
    good = m.index(0)
    # No pixmap cached yet → decoration is None (delegate paints ...
    # placeholder), display returns 1-based page number.
    assert m.data(good, Qt.ItemDataRole.DecorationRole) is None
    assert m.data(good, Qt.ItemDataRole.DisplayRole) == "1"


# ── End-to-end render (real fitz + QThread worker) ────────────────────


def _make_real_pdf(path: Path, pages: int = 2) -> Path:
    """Write a small multi-page PDF with visible text via fitz."""
    import fitz
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 144), f"Thumbnail test page {i + 1}",
                         fontsize=24)
    doc.save(str(path))
    doc.close()
    return path


def test_end_to_end_worker_populates_cache(qapp, tmp_path):
    """Real reproduction of the sidebar bug: build a genuine PDF,
    hand it to a ThumbnailPanel, spin the event loop, and assert the
    background worker actually delivered pixmaps into the model cache.

    If this fails with cache_size() == 0 the render pipeline is broken
    (import fitz, get_pixmap, epoch guard, or main-thread QPixmap
    conversion) — exactly the placeholder-forever symptom."""
    from PySide6.QtTest import QTest
    from app.viewer.thumbnails import ThumbnailPanel

    pdf = _make_real_pdf(tmp_path / "e2e.pdf", pages=2)

    panel = ThumbnailPanel()
    try:
        panel.set_document(str(pdf), 2)
        # Wait until the worker finishes (or a generous timeout).
        deadline = 5000
        waited = 0
        while panel._model.cache_size() < 2 and waited < deadline:
            QTest.qWait(50)
            waited += 50
        assert panel._model.cache_size() >= 1, (
            "worker delivered no thumbnails — render pipeline is broken"
        )
        assert panel._model.cache_size() == 2, (
            f"expected 2 thumbnails, got {panel._model.cache_size()}"
        )
        # The delivered pixmap must be a real, non-null image.
        from PySide6.QtCore import Qt
        pix = panel._model.data(
            panel._model.index(0), Qt.ItemDataRole.DecorationRole)
        assert pix is not None and not pix.isNull()
    finally:
        panel.clear()
        panel.deleteLater()


def test_worker_hidpi_render_is_higher_res_and_tagged(qapp, tmp_path):
    """A dpr=2 render must produce ~2× the raw pixels of a dpr=1 render
    and carry devicePixelRatio==2, while keeping the same logical
    (device-independent) size. This is the crux of the sharpness fix:
    the widget draws it at THUMB size but with HiDPI detail instead of
    upscaling a low-res image."""
    from PySide6.QtTest import QTest
    from app.viewer.thumbnails import ThumbnailWorker

    pdf = _make_real_pdf(tmp_path / "hidpi.pdf", pages=1)

    def _render(dpr: float):
        got: list = []
        w = ThumbnailWorker(str(pdf), [0], epoch=1, dpr=dpr)
        w.thumbnail_ready.connect(lambda i, img, e: got.append(img))
        w.start()
        w.wait(3000)
        QTest.qWait(50)
        assert got, f"no thumbnail delivered at dpr={dpr}"
        return got[0]

    img1 = _render(1.0)
    img2 = _render(2.0)

    assert img1.devicePixelRatio() == 1.0
    assert img2.devicePixelRatio() == 2.0
    # Roughly double the raw pixels along each axis.
    assert img2.width() >= int(img1.width() * 1.7)
    assert img2.height() >= int(img1.height() * 1.7)
    # Same logical footprint (device-independent size) within rounding.
    log1_w = img1.width() / img1.devicePixelRatio()
    log2_w = img2.width() / img2.devicePixelRatio()
    assert abs(log1_w - log2_w) <= 2


def test_worker_signals_render_failed_on_bad_path(qapp, tmp_path):
    """A worker that can open nothing must not die silently: it emits
    render_failed so the panel can log/reflect instead of leaving the
    sidebar stuck on placeholders forever."""
    from PySide6.QtTest import QTest
    from app.viewer.thumbnails import ThumbnailWorker

    bad = str(tmp_path / "does_not_exist.pdf")
    worker = ThumbnailWorker(bad, [0, 1, 2], epoch=7)
    got: list[tuple[int, str]] = []
    worker.render_failed.connect(lambda e, r: got.append((e, r)))

    worker.start()
    waited = 0
    while worker.isRunning() and waited < 3000:
        QTest.qWait(20)
        waited += 20
    worker.wait(2000)
    # Let the queued signal drain on the main thread.
    QTest.qWait(50)
    assert got, "worker did not emit render_failed on an unopenable path"
    assert got[0][0] == 7  # epoch propagated


def test_worker_no_render_failed_when_cancelled(qapp, tmp_path):
    """Cancellation is not a failure — no render_failed should fire."""
    from PySide6.QtTest import QTest
    from app.viewer.thumbnails import ThumbnailWorker

    pdf = _make_real_pdf(tmp_path / "cancel.pdf", pages=1)
    worker = ThumbnailWorker(str(pdf), [0], epoch=1)
    got: list = []
    worker.render_failed.connect(lambda e, r: got.append((e, r)))
    worker.cancel()  # cancel before start → loop breaks immediately
    worker.start()
    worker.wait(2000)
    QTest.qWait(50)
    assert got == []


def test_hidden_tab_thumbnails_paint_when_shown(qapp, tmp_path):
    """Exercise the real app scenario: the ThumbnailPanel lives as the
    second ("Pages") tab of a QTabWidget while another tab is active, so
    the panel is HIDDEN when the document is loaded — mirroring
    ``ViewerPage`` where the "Contents" tab (index 0) stays active for a
    PDF that has a TOC while ``set_document`` runs on the parked Pages
    tab (see app/viewer/panel.py:161-168, 605).

    What this test actually validates
    ---------------------------------
    * The background worker fills the model cache even while the panel is
      hidden (``cache_size == pages``) — rendering does not depend on
      visibility.
    * While the panel is the *inactive* tab it receives ZERO delegate
      paints (the "before" snapshot), so the "after" assertion is
      genuinely discriminating rather than trivially true.
    * Once the QTabWidget switches to the Pages tab, the delegate is
      painted with NON-NULL pixmaps and ``data(DecorationRole)`` returns
      a real pixmap for the visible rows — the cached-while-hidden
      thumbnails reach the paint path instead of staying "…" placeholders.

    What this test does NOT prove
    -----------------------------
    The ``offscreen`` QPA backend does not reproduce the *field* bug: a
    counterfactual run with ``ThumbnailModel.refresh_decorations``
    neutered still paints every row with a non-null pixmap the moment the
    tab is revealed, because offscreen Qt re-reads the model on show
    anyway. So this is a regression test for the hidden→visible FLOW; it
    cannot, on this platform, confirm or refute that the ``showEvent``
    ``refresh_decorations`` repaint fix is what resolves the on-device
    placeholder-forever symptom. That distinction is intentional — see
    the parent task notes — rather than a trivially-green assert that
    would give false confidence in the fix.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLabel, QTabWidget
    from app.viewer.thumbnails import ThumbnailDelegate, ThumbnailPanel

    pages = 3
    pdf = _make_real_pdf(tmp_path / "hidden_tab.pdf", pages=pages)

    # Instrument the delegate: count paints and how many carried a real
    # (non-null) pixmap. Subclassing (not monkeypatching the instance) so
    # PySide6's C++ virtual dispatch reliably reaches our override.
    paint_log = {"total": 0, "with_pixmap": 0}

    class CountingDelegate(ThumbnailDelegate):
        def paint(self, painter, option, index):
            paint_log["total"] += 1
            pix = index.data(Qt.ItemDataRole.DecorationRole)
            if pix is not None and not pix.isNull():
                paint_log["with_pixmap"] += 1
            super().paint(painter, option, index)

    panel = ThumbnailPanel()
    delegate = CountingDelegate(panel)
    panel._view.setItemDelegate(delegate)
    panel._delegate = delegate

    tabs = QTabWidget()
    other = QLabel("contents")
    try:
        tabs.addTab(other, "Contents")   # index 0 – active
        tabs.addTab(panel, "Pages")      # index 1 – starts hidden
        tabs.setCurrentIndex(0)
        tabs.resize(400, 600)
        tabs.show()
        QTest.qWait(50)

        assert not panel.isVisible(), (
            "precondition failed: the Pages tab must start hidden so the "
            "hidden→visible transition is actually exercised"
        )

        # Load the document while the panel is the inactive tab.
        panel.set_document(str(pdf), pages)
        waited = 0
        while panel._model.cache_size() < pages and waited < 5000:
            QTest.qWait(50)
            waited += 50

        # The worker renders regardless of visibility.
        assert panel._model.cache_size() == pages, (
            f"worker did not fill cache while hidden: "
            f"{panel._model.cache_size()}/{pages}"
        )

        # A genuinely-hidden inactive tab must not have been painted yet;
        # this is what makes the post-switch assertion meaningful.
        before = dict(paint_log)
        assert before["with_pixmap"] == 0, (
            "expected zero delegate paints while the panel was hidden, "
            f"got {before}"
        )

        # Reveal the Pages tab; give the showEvent + its queued
        # singleShot(0) second refresh time to run.
        tabs.setCurrentIndex(1)
        QTest.qWait(50)
        QTest.qWait(100)

        assert panel.isVisible(), "panel should be visible after switching"

        after = dict(paint_log)
        painted_with_pixmap = after["with_pixmap"] - before["with_pixmap"]
        assert painted_with_pixmap > 0, (
            "after revealing the Pages tab the delegate was never painted "
            f"with a real pixmap (before={before}, after={after}) — the "
            "cached-while-hidden thumbnails never reached the paint path"
        )

        # And the model still serves a real pixmap for the first row.
        pix = panel._model.data(
            panel._model.index(0), Qt.ItemDataRole.DecorationRole)
        assert pix is not None and not pix.isNull(), (
            "DecorationRole returned no pixmap for row 0 after the tab "
            "became visible"
        )
    finally:
        panel.clear()
        tabs.deleteLater()
        panel.deleteLater()


def test_large_doc_top_pages_not_evicted_when_shown(qapp, tmp_path):
    """Regression for the ebook placeholder-forever bug.

    A PDF longer than ``CACHE_MAX`` used to be rendered eagerly, page by
    page, into an LRU cache smaller than the document. By the time the
    worker finished, the EARLY pages (the top of the list — exactly what
    the user sees when they open the Pages tab) had been evicted by the
    later ones, so row 0 held no pixmap and nothing ever re-rendered it:
    placeholders forever. It only reproduced with big docs, and it was
    *permanent* (rather than merely flickering) when the Pages tab was
    parked behind the Contents tab of a TOC PDF — hidden while the worker
    ran, so the early pages were never even painted before eviction.

    This is a cache/data assertion (not a paint one) so the offscreen QPA
    backend reproduces it deterministically: the fix renders only the
    visible window lazily, so the on-screen rows are always populated and
    the cache never exceeds a small sliding window.

    Discriminating power
    --------------------
    The old eager code rendered ``range(page_count)`` up-front into an LRU
    cache smaller than the document, so it (a) evicted row 0 (leaving it
    ``None``) and (b) ended with ``cache_size() == CACHE_MAX`` (200). Both
    final assertions below therefore FAIL against the old code and only
    PASS against the lazy-window fix:

    * we join the real workers (no fixed short sleep that could sample the
      cache *before* eviction happens) — under the old code the join
      settles with row 0 evicted;
    * we require ``cache_size()`` to be a SMALL window (``< 30``), which
      the eager 200-entry cache can never satisfy.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLabel, QTabWidget
    from app.viewer.thumbnails import CACHE_MAX, ThumbnailPanel

    pages = CACHE_MAX + 40  # longer than the cache → old code evicted top
    pdf = _make_real_pdf(tmp_path / "ebook.pdf", pages=pages)

    panel = ThumbnailPanel()
    tabs = QTabWidget()
    other = QLabel("contents")
    try:
        tabs.addTab(other, "Contents")   # index 0 – active (TOC case)
        tabs.addTab(panel, "Pages")      # index 1 – hidden during load
        tabs.setCurrentIndex(0)
        tabs.resize(320, 600)
        tabs.show()
        QTest.qWait(30)
        assert not panel.isVisible()

        panel.set_document(str(pdf), pages)
        # Reveal the Pages tab and JOIN the real render workers until they
        # settle (row 0 delivered, nothing in flight, no thread running) —
        # a deterministic wait rather than a short fixed sleep that could
        # sample the cache before the old eager code had a chance to evict
        # the top of the list.
        tabs.setCurrentIndex(1)
        m = panel._model

        def _settled() -> bool:
            row0 = m.data(m.index(0), Qt.ItemDataRole.DecorationRole)
            workers_done = all(not w.isRunning() for w in panel._workers)
            return (row0 is not None
                    and not panel._inflight
                    and workers_done)

        waited = 0
        while not _settled() and waited < 5000:
            QTest.qWait(50)
            waited += 50

        # The row the user is looking at (top of the list) must have a
        # real thumbnail — the whole point of the fix. Under the old eager
        # code it has been LRU-evicted by the trailing pages: None.
        pix0 = m.data(m.index(0), Qt.ItemDataRole.DecorationRole)
        assert pix0 is not None and not pix0.isNull(), (
            "top page has no thumbnail — eager-render-then-evict "
            "regression is back"
        )
        # The cache must be a SMALL sliding window, not the whole document
        # capped at CACHE_MAX. The old eager code ends at CACHE_MAX (200),
        # so this fails there and only passes with lazy windowing.
        assert m.cache_size() < 30, (
            f"cache holds {m.cache_size()} pages — expected a small "
            "visible window; the whole document was rendered eagerly "
            "(lazy windowing is broken / regressed)"
        )
    finally:
        panel.clear()
        tabs.deleteLater()
        panel.deleteLater()


# ── Panel integration ────────────────────────────────────────────────


def test_panel_wires_thumbnail_panel():
    """Viewer must instantiate ThumbnailPanel and route its signal."""
    assert "ThumbnailPanel" in PANEL_SRC
    assert "page_requested" in PANEL_SRC
    assert "_on_thumbnail_clicked" in PANEL_SRC


def test_panel_syncs_current_page_on_scroll():
    """Scrolling the canvas must update the thumbnail highlight."""
    assert "self._thumbnails.set_current_page(idx)" in PANEL_SRC


def test_panel_loads_thumbnails_on_open():
    assert "self._thumbnails.set_document(" in PANEL_SRC


def test_panel_clears_thumbnails_on_close_and_replace():
    """Both the closeEvent and the doc-replace path must stop the
    worker so a stale QThread doesn't outlive the panel."""
    assert PANEL_SRC.count("self._thumbnails.clear()") >= 2


def test_panel_updates_thumbnails_theme():
    assert "self._thumbnails.update_theme(dark)" in PANEL_SRC


def test_panel_activates_contents_tab_when_toc_present():
    """Guard the TOC regression: the outline branch must re-select the
    Contents tab so it doesn't stay parked on Pages after a prior no-TOC
    document switched the active tab."""
    assert "self._sidebar_tabs.setCurrentIndex(self._toc_tab_idx)" in PANEL_SRC


def test_toc_tab_active_by_default_across_reload(qapp, tmp_path):
    """Behavioural regression: after loading a no-TOC PDF (which hides the
    Contents tab and activates Pages) then a PDF WITH a TOC, the Contents
    tab must be visible AND active — the original behaviour. Before the
    fix it stayed on the Pages tab, so the outline appeared to be gone."""
    import fitz
    from PySide6.QtTest import QTest
    from app.viewer.panel import PdfViewerPanel

    def _make(name, toc):
        p = tmp_path / name
        d = fitz.open()
        for i in range(6):
            pg = d.new_page(width=595, height=842)
            pg.insert_text((72, 144), f"P{i + 1}", fontsize=20)
        if toc:
            d.set_toc(toc)
        d.save(str(p))
        d.close()
        return str(p)

    toc_pdf = _make("toc.pdf", [[1, "Ch1", 1], [1, "Ch2", 4]])
    plain_pdf = _make("plain.pdf", None)

    panel = PdfViewerPanel()
    try:
        panel.resize(900, 600)
        panel.show()
        QTest.qWait(30)
        tabs = panel._sidebar_tabs

        panel.load(toc_pdf)
        QTest.qWait(60)
        assert tabs.isTabVisible(panel._toc_tab_idx)
        assert tabs.currentIndex() == panel._toc_tab_idx

        panel.load(plain_pdf)
        QTest.qWait(60)
        # No TOC → Contents hidden, Pages active.
        assert not tabs.isTabVisible(panel._toc_tab_idx)
        assert tabs.currentIndex() == panel._pages_tab_idx

        panel.load(toc_pdf)
        QTest.qWait(60)
        # TOC back → both tabs present and Contents active by default.
        assert tabs.isTabVisible(panel._toc_tab_idx)
        assert tabs.isTabVisible(panel._pages_tab_idx)
        assert tabs.currentIndex() == panel._toc_tab_idx, (
            "Contents tab must be active by default when the PDF has a TOC"
        )
    finally:
        panel._thumbnails.clear()
        panel.close()
        panel.deleteLater()
        QTest.qWait(30)


# ── i18n ──────────────────────────────────────────────────────────────


def test_i18n_keys_present_in_all_langs():
    with open(ROOT / "app" / "translations.json", encoding="utf-8") as f:
        data = json.load(f)
    langs = ["en", "pt", "es", "fr", "de", "it", "nl", "zh"]
    for lang in langs:
        assert lang in data, f"language {lang} missing"
        for key in ("viewer.sidebar.pages",
                    "viewer.sidebar.contents",
                    "viewer.thumbnails.loading"):
            assert key in data[lang], f"{lang}: {key} missing"
            assert data[lang][key].strip(), f"{lang}: {key} empty"


def test_i18n_key_parity():
    """Every language dict must expose exactly the same keys."""
    with open(ROOT / "app" / "translations.json", encoding="utf-8") as f:
        data = json.load(f)
    reference = set(data["en"].keys())
    for lang, entries in data.items():
        assert set(entries.keys()) == reference, (
            f"{lang} diverges: "
            f"+{set(entries) - reference} -{reference - set(entries)}"
        )
