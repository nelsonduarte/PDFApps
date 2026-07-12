"""PDFApps – PDF page thumbnails panel for the viewer sidebar.

A lightweight ``QListView`` that shows one clickable thumbnail per
page. Thumbnails are rendered off the UI thread by a ``QThread`` worker
(pymupdf's ``fitz.open`` is not thread-safe across the same
``Document`` handle, so the worker opens its own copy) and cached in an
insertion-ordered dict capped at ``CACHE_MAX`` entries — long documents
never blow up memory.

Public API
----------
``ThumbnailPanel.set_document(path, page_count, password="")``
    Load a document. Resets the model and kicks off rendering.

``ThumbnailPanel.clear()``
    Unload the current document.

``ThumbnailPanel.set_current_page(idx)``
    Highlight + scroll to a page.

``ThumbnailPanel.page_requested (Signal[int])``
    User clicked / keyed a thumbnail. The viewer should scroll canvas
    there.

``ThumbnailPanel.update_theme(dark)``
    Repaint delegate so ACCENT / TEXT_SEC track the theme.
"""

from __future__ import annotations

import contextlib
import logging

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QRect, QSize, Qt, QThread, QTimer,
    Signal, Slot,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QListView, QStyle, QStyledItemDelegate,
    QVBoxLayout, QWidget,
)

from app.constants import ACCENT, TEXT_SEC


_log = logging.getLogger(__name__)


THUMB_WIDTH = 120     # px – target thumbnail width before aspect-fit
THUMB_HEIGHT = 160    # px – target thumbnail height (portrait ~ 1.33)
THUMB_PADDING = 12    # px around the thumbnail inside a row
PAGE_NUM_HEIGHT = 20  # px reserved for the page-number label
CACHE_MAX = 200       # LRU-ish cap on cached QPixmaps


# ── Worker ────────────────────────────────────────────────────────────


class ThumbnailWorker(QThread):
    """Render a batch of page thumbnails in a background thread.

    The worker opens its own ``fitz.Document`` copy — pymupdf documents
    are NOT thread-safe across the main-thread handle used by the
    canvas. Password is applied when set. ``cancel()`` sets a flag the
    render loop polls between pages; wait 2 s in the caller for a
    graceful shutdown before dropping the reference.
    """

    # Emits QImage (thread-safe) rather than QPixmap: Qt requires
    # QPixmap to be constructed / mutated only in the main GUI thread,
    # so the receiver slot ``ThumbnailPanel._on_image_ready`` performs
    # the ``QPixmap.fromImage()`` conversion on the main thread before
    # handing the pixmap to the model.
    thumbnail_ready = Signal(int, QImage, int)  # (page_index, thumbnail, epoch)

    def __init__(self, doc_path: str, page_indices: list[int],
                 password: str = "", epoch: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._doc_path = doc_path
        self._pages = list(page_indices)
        self._password = password
        # Generation this worker was launched for. Emitted alongside
        # each thumbnail so the panel can discard images produced for a
        # document that has since been replaced (see ThumbnailPanel).
        self._epoch = epoch
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        import fitz  # local — keeps import cost off UI startup path

        try:
            doc = fitz.open(self._doc_path)
        except Exception:
            return
        try:
            if self._password and doc.needs_pass:
                with contextlib.suppress(Exception):
                    doc.authenticate(self._password)
            page_count = doc.page_count
            for idx in self._pages:
                if self._cancelled:
                    break
                if idx < 0 or idx >= page_count:
                    continue
                try:
                    _log.debug(
                        "ThumbnailWorker: rendering page %d/%d",
                        idx + 1, page_count,
                    )
                    page = doc[idx]
                    # 40 DPI ≈ 330×467 px for A4 — plenty of detail
                    # for a 120×160 downscale with smooth transform.
                    pix = page.get_pixmap(dpi=40, alpha=False, annots=False)
                    if pix.n != 3:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    # ``QImage`` views ``pix.samples`` directly; the
                    # Pixmap is freed on the next loop iteration, so
                    # ``.copy()`` an eager copy of the pixels BEFORE
                    # emitting — otherwise the receiver sees a
                    # dangling buffer (same fix pattern as the print
                    # loop and OCR round 3).
                    #
                    # Emit QImage (thread-safe) — the main-thread slot
                    # converts to QPixmap. Constructing QPixmap here in
                    # the worker thread is invalid per Qt's threading
                    # model (silent no-op or crash on some platforms).
                    img = QImage(
                        pix.samples, pix.width, pix.height,
                        pix.stride, QImage.Format.Format_RGB888,
                    ).copy()
                    self.thumbnail_ready.emit(idx, img, self._epoch)
                except Exception:
                    # Skip page — bad object / partial doc, keep going.
                    continue
        finally:
            with contextlib.suppress(Exception):
                doc.close()


# ── Model ─────────────────────────────────────────────────────────────


class ThumbnailModel(QAbstractListModel):
    """List model: one row per page. Decoration = QPixmap thumbnail."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._page_count = 0
        self._cache: dict[int, QPixmap] = {}
        self._doc_path = ""

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else self._page_count

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        row = index.row()
        if row < 0 or row >= self._page_count:
            return None
        if role == Qt.ItemDataRole.DecorationRole:
            return self._cache.get(row)  # None → delegate paints placeholder
        if role == Qt.ItemDataRole.DisplayRole:
            return str(row + 1)
        return None

    def set_document(self, doc_path: str, page_count: int) -> None:
        self.beginResetModel()
        self._doc_path = doc_path
        self._page_count = max(0, int(page_count))
        self._cache.clear()
        self.endResetModel()

    def clear(self) -> None:
        self.set_document("", 0)

    def cache_pixmap(self, page_idx: int, pix: QPixmap) -> None:
        # Refresh insertion order for LRU eviction: pop + re-add.
        if page_idx in self._cache:
            self._cache.pop(page_idx, None)
        self._cache[page_idx] = pix
        # Evict oldest entries until we're back under the cap. ``dict``
        # preserves insertion order since Python 3.7, so the first
        # iterator element is the oldest.
        while len(self._cache) > CACHE_MAX:
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        idx = self.index(page_idx)
        self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])

    # Expose the cache size for tests / debug.
    def cache_size(self) -> int:
        return len(self._cache)


# ── Delegate ──────────────────────────────────────────────────────────


class ThumbnailDelegate(QStyledItemDelegate):
    """Paint each row: thumbnail + page number, with current-page
    highlight in ACCENT and hover feedback."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_page = -1
        self._dark = True

    def set_current_page(self, page_idx: int) -> int:
        old = self._current_page
        self._current_page = page_idx
        return old

    def set_dark(self, dark: bool) -> None:
        self._dark = bool(dark)

    def sizeHint(self, option, index):  # noqa: D401
        return QSize(
            THUMB_WIDTH + 2 * THUMB_PADDING,
            THUMB_HEIGHT + 2 * THUMB_PADDING + PAGE_NUM_HEIGHT,
        )

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        page_idx = index.row()
        rect = option.rect
        pix = index.data(Qt.ItemDataRole.DecorationRole)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Row background — current selection or hover feedback.
        if page_idx == self._current_page:
            accent = QColor(ACCENT)
            accent.setAlpha(60)
            painter.setBrush(accent)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect.adjusted(4, 4, -4, -4), 6, 6)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            hover = QColor(255, 255, 255, 20) if self._dark \
                else QColor(0, 0, 0, 20)
            painter.setBrush(hover)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect.adjusted(4, 4, -4, -4), 6, 6)

        # Thumbnail region.
        thumb_x = rect.x() + THUMB_PADDING
        thumb_y = rect.y() + THUMB_PADDING
        thumb_rect = QRect(thumb_x, thumb_y, THUMB_WIDTH, THUMB_HEIGHT)

        if pix is not None and not pix.isNull():
            scaled = pix.scaled(
                THUMB_WIDTH, THUMB_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            cx = thumb_x + (THUMB_WIDTH - scaled.width()) // 2
            cy = thumb_y + (THUMB_HEIGHT - scaled.height()) // 2
            painter.drawPixmap(cx, cy, scaled)
            # 1 px hairline so a white-page thumbnail is still visible
            # against a light background.
            painter.setPen(QColor(0, 0, 0, 60))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(cx, cy, scaled.width() - 1, scaled.height() - 1)
        else:
            # Placeholder while the worker catches up.
            painter.setPen(QColor(TEXT_SEC))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(thumb_rect)
            painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, "…")

        # Page number label under the thumbnail.
        if page_idx == self._current_page:
            painter.setPen(QColor(ACCENT))
        else:
            painter.setPen(QColor(TEXT_SEC))
        num_rect = QRect(
            rect.x(), thumb_y + THUMB_HEIGHT + 2,
            rect.width(), PAGE_NUM_HEIGHT,
        )
        painter.drawText(num_rect, Qt.AlignmentFlag.AlignCenter,
                         str(page_idx + 1))

        painter.restore()


# ── Panel ─────────────────────────────────────────────────────────────


class ThumbnailPanel(QWidget):
    """Sidebar container hosting the QListView of thumbnails.

    Emits :pyattr:`page_requested` when the user clicks / activates a
    thumbnail. Owns the current ``ThumbnailWorker`` and shuts it down
    cleanly on doc change / close event.
    """

    page_requested = Signal(int)  # 0-based page index

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("thumbnail_panel")
        self._doc_path = ""
        self._password = ""
        self._worker: ThumbnailWorker | None = None
        # Monotonic generation counter. Bumped on every set_document /
        # clear so late thumbnails from a superseded worker (still in the
        # queued-connection event queue) can be identified and dropped
        # instead of being cached against the NEW document's indices.
        self._epoch = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._model = ThumbnailModel(self)
        self._delegate = ThumbnailDelegate(self)

        self._view = QListView(self)
        self._view.setModel(self._model)
        self._view.setItemDelegate(self._delegate)
        self._view.setViewMode(QListView.ViewMode.ListMode)
        self._view.setUniformItemSizes(True)
        self._view.setMouseTracking(True)
        self._view.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._view.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.clicked.connect(self._on_activated)
        self._view.activated.connect(self._on_activated)  # keyboard Enter
        layout.addWidget(self._view)

    # ── Public API ────────────────────────────────────────────────

    def set_document(self, doc_path: str, page_count: int,
                     password: str = "") -> None:
        """Reset model + kick off background rendering."""
        self._doc_path = doc_path
        self._password = password or ""
        self._stop_worker()
        # New generation: any thumbnail still queued from a prior worker
        # now carries a stale epoch and will be dropped in _on_image_ready.
        self._epoch += 1
        self._model.set_document(doc_path, page_count)
        self._delegate.set_current_page(-1)
        if page_count > 0 and doc_path:
            self._start_worker(list(range(page_count)))

    def clear(self) -> None:
        """Unload the current document."""
        self._doc_path = ""
        self._password = ""
        self._stop_worker()
        # New generation — see set_document.
        self._epoch += 1
        self._model.clear()
        self._delegate.set_current_page(-1)

    def set_current_page(self, page_idx: int) -> None:
        """Highlight given page and scroll to it (if visible)."""
        if not (0 <= page_idx < self._model.rowCount()):
            return
        old = self._delegate.set_current_page(page_idx)
        idx = self._model.index(page_idx)
        self._view.setCurrentIndex(idx)
        self._view.scrollTo(
            idx, QAbstractItemView.ScrollHint.EnsureVisible)
        # Repaint both the previous and the new row so the highlight
        # tracks correctly even though the model data didn't change.
        vp = self._view.viewport()
        if old >= 0:
            old_rect = self._view.visualRect(self._model.index(old))
            vp.update(old_rect)
        vp.update(self._view.visualRect(idx))

    def update_theme(self, dark: bool) -> None:
        """Repaint so ACCENT / TEXT_SEC track the theme."""
        self._delegate.set_dark(dark)
        self._view.viewport().update()

    # ── Internals ─────────────────────────────────────────────────

    def _on_activated(self, index: QModelIndex) -> None:
        if index.isValid():
            self.page_requested.emit(index.row())

    def _start_worker(self, page_indices: list[int]) -> None:
        self._worker = ThumbnailWorker(
            self._doc_path, page_indices, self._password, self._epoch, self)
        # Explicit QueuedConnection so the slot runs on this (main)
        # thread rather than the worker — required for QPixmap
        # construction, and matches the Py3.14 PySide6 routing rules
        # documented in memory/project_compress_freeze_py314.md.
        self._worker.thumbnail_ready.connect(
            self._on_image_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        self._worker.start()

    @Slot(int, QImage, int)
    def _on_image_ready(self, page_idx: int, img: QImage, epoch: int) -> None:
        """Runs on the main GUI thread. Convert the worker's QImage
        into a QPixmap and hand it to the model.

        QPixmap construction is only valid on the main thread; doing it
        here (instead of in the worker) is why the parent signal
        carries QImage."""
        # Drop thumbnails from a superseded document: a queued emission
        # from the previous worker can still be delivered after
        # set_document/clear bumped the epoch, and caching it would paint
        # the old document's page into the new document's index.
        if epoch != self._epoch:
            _log.debug(
                "Dropping stale thumbnail page %d (epoch %d != %d)",
                page_idx + 1, epoch, self._epoch,
            )
            return
        _log.debug(
            "Thumbnail received for page %d (%dx%d)",
            page_idx + 1, img.width(), img.height(),
        )
        pix = QPixmap.fromImage(img)
        self._model.cache_pixmap(page_idx, pix)

    def _stop_worker(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        # Disconnect BEFORE waiting so a thumbnail emitted between the
        # cancel flag check and the worker unwinding can't sneak into
        # the model for the old document. The epoch guard in
        # _on_image_ready is the belt; this disconnect is the braces.
        with contextlib.suppress(RuntimeError, TypeError):
            self._worker.thumbnail_ready.disconnect(self._on_image_ready)
        # 2 s is generous — a single page render at 40 DPI is well
        # under 100 ms; the cancel flag is polled between pages so
        # worst case we wait for the current page to finish.
        self._worker.wait(2000)
        self._worker = None

    def showEvent(self, event):  # noqa: D401
        """Force a viewport repaint when the panel becomes visible.

        The worker fills the model's pixmap cache in the background even
        while this widget is hidden (e.g. the sidebar is on the
        "Contents" tab). Qt normally coalesces / drops repaints for
        hidden widgets, so ``dataChanged`` signals emitted during that
        window never reach the viewport. Calling ``update()`` here on
        first show — and on every subsequent show — makes the QListView
        redraw all visible rows against the current cache so any
        pixmaps that arrived while hidden appear immediately instead of
        remaining as ``…`` placeholders.
        """
        super().showEvent(event)
        if self._view is not None:
            vp = self._view.viewport()
            if vp is not None:
                vp.update()
                # Layout can still be incomplete when showEvent fires
                # (e.g. the tab was just switched — viewport size is
                # still the collapsed placeholder value). Schedule a
                # second update after the current event-loop iteration
                # so it runs against the final resized geometry. Without
                # this, the first update() marks the wrong (tiny) area
                # dirty and Qt does not repaint the newly-resized
                # region.
                QTimer.singleShot(0, vp.update)

    def resizeEvent(self, event):  # noqa: D401
        """Force viewport repaint on resize so newly-visible rows paint
        against the current cache (not against stale/degenerate
        geometry from before the layout settled)."""
        super().resizeEvent(event)
        if self._view is not None:
            vp = self._view.viewport()
            if vp is not None:
                vp.update()

    def closeEvent(self, event):  # noqa: D401
        self._stop_worker()
        super().closeEvent(event)
