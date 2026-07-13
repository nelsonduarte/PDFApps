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
import os

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QRect, QSize, QStandardPaths, Qt,
    QThread, QTimer, Signal, Slot,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QListView, QStyle, QStyledItemDelegate,
    QVBoxLayout, QWidget,
)

from app.constants import ACCENT, TEXT_SEC


_log = logging.getLogger(__name__)


class _FlushFileHandler(logging.FileHandler):
    """FileHandler that flushes + fsyncs after every record.

    The project's hang-debugging notes warn that PowerShell terminal
    redirection is unreliable for capturing the moments right before a
    freeze / kill. Writing to a dedicated file with line-buffering plus
    an explicit ``fsync`` guarantees the thumbnail diagnostics survive a
    hard process kill so the user can re-send the log and we can close
    the diagnosis without guessing (see memory/feedback_diag_logging.md).
    """

    def emit(self, record):  # noqa: D401
        super().emit(record)
        with contextlib.suppress(Exception):
            self.flush()
            os.fsync(self.stream.fileno())


# Basename of the kill-proof diagnostic log. Only written when the env
# var PDFAPPS_THUMB_DEBUG is set (any value) so production runs stay
# quiet; the resolved path is stable so the user can be told exactly
# where to look.
THUMB_LOG_NAME = "pdfapps_thumbnails.log"


def _thumb_log_path() -> str:
    """Resolve the diagnostic log path inside a per-user data directory.

    The old implementation dropped the log in a FIXED, predictable name
    under the *shared* system temp dir (``/tmp`` on Linux/macOS). That is
    exactly the symlink-following / attacker-pre-created-file pattern the
    project's security notes warn about (see memory/feedback_security.md):
    another user can pre-create or symlink ``/tmp/pdfapps_thumbnails.log``
    and our append-mode open would follow it.

    Writing under a per-user location owned by the current user (Windows:
    ``%LOCALAPPDATA%/PDFApps``; Linux: ``~/.local/share/PDFApps``; macOS:
    ``~/Library/Application Support/PDFApps``) removes the shared-dir
    race: the directory is not world-writable, so a plain append open is
    safe. A fixed ``PDFApps`` subfolder keeps the path deterministic
    regardless of the (deliberately blank) QApplication name.
    """
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericDataLocation)
    if not base:
        # No usable data location (headless / unset HOME): fall back to a
        # per-user dotdir in the home directory rather than shared temp.
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(base, "PDFApps")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, THUMB_LOG_NAME)


def _install_debug_log() -> None:
    """Attach the kill-proof file handler when PDFAPPS_THUMB_DEBUG is set.

    Idempotent — safe to call from every ThumbnailPanel constructor.
    """
    if not os.environ.get("PDFAPPS_THUMB_DEBUG"):
        return
    for h in _log.handlers:
        if isinstance(h, _FlushFileHandler):
            return
    with contextlib.suppress(Exception):
        log_path = _thumb_log_path()
        handler = _FlushFileHandler(log_path, mode="a", encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s"))
        handler.setLevel(logging.DEBUG)
        _log.addHandler(handler)
        _log.setLevel(logging.DEBUG)
        _log.info("── thumbnail debug log opened (pid=%d) ──", os.getpid())


THUMB_WIDTH = 120     # px – target thumbnail width before aspect-fit
THUMB_HEIGHT = 160    # px – target thumbnail height (portrait ~ 1.33)
THUMB_PADDING = 12    # px around the thumbnail inside a row
PAGE_NUM_HEIGHT = 20  # px reserved for the page-number label
CACHE_MAX = 200       # LRU-ish cap on cached QPixmaps
# How many rows above/below the viewport to pre-render so scrolling a
# little doesn't reveal a wall of "…" placeholders before the worker
# catches up.
VISIBLE_BUFFER = 4
# When the panel is hidden (e.g. parked behind the "Contents" tab for a
# PDF that has a TOC) the viewport has no usable geometry, so we render a
# window of this many pages around the anchor (the current reading page)
# up-front. When the tab is later revealed, showEvent recomputes the
# real visible range and fills any gaps. This is the core of the fix:
# we NEVER eagerly render the whole document (which, for a doc longer
# than CACHE_MAX, evicted its own early pages before the user could see
# them and left the top of the list on placeholders forever).
HIDDEN_WINDOW = 12


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
    # Emitted once when the worker finishes having rendered ZERO pages
    # despite pages being requested (import failure, open failure, or
    # every page raising). Carries (epoch, reason) so the panel can log
    # it against the right generation instead of failing silently.
    render_failed = Signal(int, str)  # (epoch, reason)

    def __init__(self, doc_path: str, page_indices: list[int],
                 password: str = "", epoch: int = 0, dpr: float = 1.0,
                 parent=None) -> None:
        super().__init__(parent)
        self._doc_path = doc_path
        self._pages = list(page_indices)
        self._password = password
        # Device-pixel ratio of the screen the panel is on. Thumbnails
        # are rendered at target_size * dpr real pixels and tagged with
        # this ratio so a HiDPI display shows crisp (not upscaled-blurry)
        # pages. Never hardcoded — the panel reads the live value off its
        # widget/screen and passes it in (see memory/feedback_icons.md).
        self._dpr = float(dpr) if dpr and dpr > 0 else 1.0
        # Generation this worker was launched for. Emitted alongside
        # each thumbnail so the panel can discard images produced for a
        # document that has since been replaced (see ThumbnailPanel).
        self._epoch = epoch
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        # ``import fitz`` lives INSIDE the try: a failed import (missing
        # binary wheel, broken install) must surface as a warning + a
        # render_failed signal, NOT silently kill the QThread with an
        # unhandled ImportError that leaves the sidebar stuck on
        # placeholders forever.
        requested = len(self._pages)
        rendered = 0
        doc = None
        try:
            import fitz  # local — keeps import cost off UI startup path
            try:
                doc = fitz.open(self._doc_path)
            except Exception as exc:
                _log.warning(
                    "ThumbnailWorker: failed to open %r: %s",
                    self._doc_path, exc,
                )
                return
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
                    # Render at the ACTUAL device-pixel size the thumbnail
                    # occupies: target box (THUMB_WIDTH×THUMB_HEIGHT) times
                    # the screen's device-pixel ratio. A fixed 40 DPI used
                    # to render ~331×468 for A4 and then the delegate
                    # downscaled to a 120×160 *logical* pixmap with no DPR
                    # set — so on a 2× HiDPI screen Qt upscaled that 120 px
                    # image to fill 240 device px: visibly soft/blurry.
                    # Computing zoom from the page rect keeps the aspect
                    # ratio (KeepAspectRatio via min) and hits the exact
                    # pixel budget, so the pixmap is drawn ~1:1 and sharp.
                    rect = page.rect
                    tw = THUMB_WIDTH * self._dpr
                    th = THUMB_HEIGHT * self._dpr
                    if rect.width > 0 and rect.height > 0:
                        zoom = min(tw / rect.width, th / rect.height)
                    else:
                        zoom = self._dpr
                    mat = fitz.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=mat, alpha=False,
                                          annots=False)
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
                    # Tag with the device-pixel ratio so the receiving
                    # QPixmap paints at its device-independent (logical)
                    # size while carrying full HiDPI detail. Preserved by
                    # QPixmap.fromImage on the main thread.
                    img.setDevicePixelRatio(self._dpr)
                    rendered += 1
                    self.thumbnail_ready.emit(idx, img, self._epoch)
                except Exception as exc:
                    # Skip page — bad object / partial doc, keep going —
                    # but log it: a wall of these is the difference
                    # between "one bad page" and "the whole doc failed".
                    _log.warning(
                        "ThumbnailWorker: failed to render page %d: %s",
                        idx + 1, exc,
                    )
                    continue
        except Exception as exc:
            # import fitz / unexpected fatal — don't let the thread die
            # mute; the panel needs to know rendering never happened.
            _log.error(
                "ThumbnailWorker: fatal error, no thumbnails produced: %s",
                exc,
            )
        finally:
            if doc is not None:
                with contextlib.suppress(Exception):
                    doc.close()
            # Zero pages rendered when pages were requested and we
            # weren't cancelled is a hard failure — make it loud and
            # give the panel a chance to reflect it.
            if requested and rendered == 0 and not self._cancelled:
                _log.warning(
                    "ThumbnailWorker: rendered 0/%d pages for %r",
                    requested, self._doc_path,
                )
                with contextlib.suppress(RuntimeError):
                    self.render_failed.emit(
                        self._epoch,
                        f"rendered 0/{requested} pages",
                    )


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

    def has_pixmap(self, page_idx: int) -> bool:
        """True if ``page_idx`` currently has a cached (non-evicted)
        pixmap. Used by the panel's lazy renderer to avoid re-requesting
        pages that are already cached, while still allowing a page that
        was LRU-evicted to be re-rendered when scrolled back into view."""
        return page_idx in self._cache

    def refresh_decorations(self) -> None:
        """Re-emit ``dataChanged`` for every row's decoration.

        The worker fills ``self._cache`` while the panel may be hidden
        (sidebar parked on the Contents tab). Qt drops/coalesces the
        per-row ``dataChanged`` repaints for a hidden viewport, so those
        pixmaps never reach the screen. When the panel becomes visible
        again the view must be told to re-query DecorationRole for the
        rows it now shows — a bare ``viewport().update()`` repaints but
        does NOT force the view to re-read the model, so on some
        platforms the cached-but-never-delivered pixmaps stay invisible.
        Emitting dataChanged here guarantees a fresh read against the
        now-populated cache.
        """
        if self._page_count <= 0:
            return
        top = self.index(0)
        bottom = self.index(self._page_count - 1)
        self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.DecorationRole])


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
            # Scale in DEVICE pixels (target × DPR) then tag the result
            # with the same ratio, so the pixmap paints at its logical
            # THUMB box size while retaining full HiDPI detail — no soft
            # upscaling on a 2× screen. Geometry below uses the logical
            # (device-independent) size.
            dpr = pix.devicePixelRatio() or 1.0
            scaled = pix.scaled(
                round(THUMB_WIDTH * dpr), round(THUMB_HEIGHT * dpr),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            lw = round(scaled.width() / dpr)
            lh = round(scaled.height() / dpr)
            cx = thumb_x + (THUMB_WIDTH - lw) // 2
            cy = thumb_y + (THUMB_HEIGHT - lh) // 2
            painter.drawPixmap(cx, cy, scaled)
            # 1 px hairline so a white-page thumbnail is still visible
            # against a light background.
            painter.setPen(QColor(0, 0, 0, 60))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(cx, cy, lw - 1, lh - 1)
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
        _install_debug_log()
        self.setObjectName("thumbnail_panel")
        self._doc_path = ""
        self._password = ""
        # Multiple short-lived workers may run concurrently: as the user
        # scrolls we spin one up per newly-visible batch rather than
        # cancelling / blocking on the previous one. Finished workers are
        # pruned lazily. The epoch guard drops any results for a
        # superseded document.
        self._workers: list[ThumbnailWorker] = []
        # Pages that have been handed to a live worker but whose pixmap
        # has not yet arrived. Prevents re-requesting an in-flight page
        # on every scroll tick. Cleared per-page in _on_image_ready and
        # wholesale on set_document / clear. A page that is LRU-evicted
        # from the model cache is NOT in this set, so it is re-rendered
        # when scrolled back into view — that is what keeps long
        # documents from stranding their early pages on placeholders.
        self._inflight: set[int] = set()
        # Page to centre the pre-render window on while the panel is
        # hidden (tracks the current reading page via set_current_page).
        self._anchor = 0
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
        # Debounce scroll-driven render requests so a flick doesn't spawn
        # a worker per pixel. The timer coalesces bursts into one render
        # of the settled visible range.
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(120)
        self._scroll_timer.timeout.connect(self._render_visible)
        sb = self._view.verticalScrollBar()
        if sb is not None:
            sb.valueChanged.connect(lambda _=0: self._scroll_timer.start())
        layout.addWidget(self._view)

    # ── Public API ────────────────────────────────────────────────

    def set_document(self, doc_path: str, page_count: int,
                     password: str = "") -> None:
        """Reset model + kick off background rendering of the pages the
        user is about to see (NOT the whole document)."""
        self._doc_path = doc_path
        self._password = password or ""
        self._stop_all_workers()
        # New generation: any thumbnail still queued from a prior worker
        # now carries a stale epoch and will be dropped in _on_image_ready.
        self._epoch += 1
        self._inflight.clear()
        self._anchor = 0
        self._model.set_document(doc_path, page_count)
        self._delegate.set_current_page(-1)
        _log.debug(
            "set_document: %r page_count=%d epoch=%d visible=%s",
            doc_path, page_count, self._epoch, self.isVisible(),
        )
        if page_count > 0 and doc_path:
            self._render_visible()

    def clear(self) -> None:
        """Unload the current document."""
        self._doc_path = ""
        self._password = ""
        self._stop_all_workers()
        # New generation — see set_document.
        self._epoch += 1
        self._inflight.clear()
        self._anchor = 0
        self._model.clear()
        self._delegate.set_current_page(-1)

    def set_current_page(self, page_idx: int) -> None:
        """Highlight given page and scroll to it (if visible)."""
        if not (0 <= page_idx < self._model.rowCount()):
            return
        # Remember the reading position so a hidden panel pre-renders the
        # right window (the pages the user will land on when they open
        # the Pages tab) instead of always page 1.
        self._anchor = page_idx
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
        # If the panel is hidden the scrollbar signal above won't have
        # fired a render; make sure the window around the new anchor is
        # requested so switching to the tab shows real thumbnails.
        self._render_visible()

    def update_theme(self, dark: bool) -> None:
        """Repaint so ACCENT / TEXT_SEC track the theme."""
        self._delegate.set_dark(dark)
        self._view.viewport().update()

    # ── Internals ─────────────────────────────────────────────────

    def _on_activated(self, index: QModelIndex) -> None:
        if index.isValid():
            self.page_requested.emit(index.row())

    def _row_height(self) -> int:
        """Uniform row height from the delegate's size hint."""
        return (self._delegate.sizeHint(None, self._model.index(0)).height()
                or 1)

    def _visible_range(self) -> list[int]:
        """Compute which page rows should be rendered right now.

        When the panel has real geometry we return the rows in the
        viewport padded by VISIBLE_BUFFER. When it is hidden / not yet
        laid out (viewport height 0 — exactly the state the Pages tab is
        in while parked behind the Contents tab of a TOC PDF) the
        viewport can't tell us anything, so we fall back to a window
        around the anchor. This is the crux of the fix: we render the
        pages the user will actually look at instead of the whole doc.
        """
        total = self._model.rowCount()
        if total <= 0:
            return []
        row_h = self._row_height()
        vp = self._view.viewport()
        vp_h = vp.height() if vp is not None else 0
        if vp_h <= 0 or not self._view.isVisible():
            first = max(0, self._anchor - VISIBLE_BUFFER)
            last = min(total - 1, self._anchor + HIDDEN_WINDOW)
            return list(range(first, last + 1))
        sb = self._view.verticalScrollBar()
        top = sb.value() if sb is not None else 0
        first = top // row_h
        last = (top + vp_h) // row_h
        first = max(0, first - VISIBLE_BUFFER)
        last = min(total - 1, last + VISIBLE_BUFFER)
        return list(range(first, last + 1))

    def _render_visible(self) -> None:
        """Request rendering of the currently-visible (or hidden-window)
        pages that aren't already cached or in flight."""
        if not self._doc_path or self._model.rowCount() <= 0:
            return
        # Prune workers that have finished so the list can't grow without
        # bound over a long scrolling session.
        self._workers = [w for w in self._workers if w.isRunning()]
        want = self._visible_range()
        missing = [p for p in want
                   if p not in self._inflight and not self._model.has_pixmap(p)]
        if not missing:
            return
        self._inflight.update(missing)
        _log.debug(
            "render_visible: want=[%d..%d] missing=%d inflight=%d "
            "cache=%d workers=%d",
            want[0] if want else -1, want[-1] if want else -1,
            len(missing), len(self._inflight),
            self._model.cache_size(), len(self._workers),
        )
        self._start_worker(missing)

    def _start_worker(self, page_indices: list[int]) -> None:
        # Read the LIVE device-pixel ratio off the view (falls back to the
        # panel, then 1.0) so thumbnails render sharp on HiDPI screens.
        # Never hardcoded — see memory/feedback_icons.md.
        try:
            dpr = (self._view.devicePixelRatioF()
                   or self.devicePixelRatioF() or 1.0)
        except Exception:
            dpr = 1.0
        worker = ThumbnailWorker(
            self._doc_path, page_indices, self._password, self._epoch,
            dpr, self)
        # Explicit QueuedConnection so the slot runs on this (main)
        # thread rather than the worker — required for QPixmap
        # construction, and matches the Py3.14 PySide6 routing rules
        # documented in memory/project_compress_freeze_py314.md.
        worker.thumbnail_ready.connect(
            self._on_image_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.render_failed.connect(
            self._on_render_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        # When the worker's run() returns, reconcile _inflight on the
        # main thread: release any requested page it did NOT deliver so a
        # later scroll can re-request it (see _on_worker_finished). Queued
        # so the slot runs here, not in the worker thread.
        worker.finished.connect(
            self._on_worker_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._workers.append(worker)
        _log.debug("start_worker: %d pages epoch=%d",
                   len(page_indices), self._epoch)
        worker.start()

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
        # This page is no longer in flight; a future scroll that re-visits
        # it will now see has_pixmap() True and skip it (or, if evicted,
        # re-request it).
        self._inflight.discard(page_idx)
        pix = QPixmap.fromImage(img)
        # fromImage propagates the image's devicePixelRatio, but re-assert
        # it explicitly so the delegate can always read the correct HiDPI
        # scale off the pixmap regardless of binding quirks.
        pix.setDevicePixelRatio(img.devicePixelRatio())
        self._model.cache_pixmap(page_idx, pix)
        _log.debug(
            "image_ready: page %d (%dx%d) cache=%d",
            page_idx + 1, img.width(), img.height(), self._model.cache_size(),
        )

    @Slot(int, str)
    def _on_render_failed(self, epoch: int, reason: str) -> None:
        """Runs on the main thread. Surface a worker that produced no
        thumbnails instead of leaving the sidebar silently stuck on
        placeholders. Stale generations are ignored."""
        # A worker that rendered zero pages left ALL its requested pages
        # pinned in _inflight; release them (idempotent with the finished
        # handler) so they aren't stranded on placeholders forever.
        worker = self.sender()
        if isinstance(worker, ThumbnailWorker):
            self._release_inflight_for(worker)
        if epoch != self._epoch:
            return
        _log.warning(
            "Thumbnail rendering failed for %r: %s",
            self._doc_path, reason,
        )

    @Slot()
    def _on_worker_finished(self) -> None:
        """Runs on the main thread when a worker's run() returns.

        Reconcile bookkeeping so a page can never be stranded in
        ``_inflight`` by a worker that failed to deliver it, and drop the
        finished QThread so they don't accumulate over a long session.
        """
        worker = self.sender()
        if not isinstance(worker, ThumbnailWorker):
            return
        self._release_inflight_for(worker)
        with contextlib.suppress(ValueError):
            self._workers.remove(worker)
        # run() has returned by the time finished fires and we've already
        # reconciled its inflight pages, so it's safe to schedule deletion
        # (MINOR-1: don't leak finished QThreads parented to the panel).
        worker.deleteLater()

    def _release_inflight_for(self, worker: ThumbnailWorker) -> None:
        """Release from ``_inflight`` every page this worker was asked to
        render but did NOT deliver (i.e. is not in the model cache).

        Called when a worker finishes or fails. Without it, a page the
        worker skipped — out of range, a per-page render exception, or a
        whole-document open failure — would stay pinned in ``_inflight``
        forever, and ``_render_visible`` (which excludes in-flight pages)
        would never request it again: placeholder-forever by failed page.
        Delivered pages were already discarded from ``_inflight`` in
        ``_on_image_ready`` and remain cached, so they are left alone.
        Not re-triggering a render here is deliberate: a genuinely broken
        page is retried only when the user scrolls it back into view,
        never in a tight busy-loop.
        """
        # Stale generation: set_document/clear already cleared _inflight
        # for the new document, so this worker's page numbers no longer
        # refer to the current in-flight set. Touching it would corrupt
        # the new generation's bookkeeping.
        if worker._epoch != self._epoch:
            return
        for page in worker._pages:
            if not self._model.has_pixmap(page):
                self._inflight.discard(page)

    def _stop_all_workers(self) -> None:
        """Cancel + join every live worker. Called on doc change / close
        so a stale QThread can't outlive the panel or leak thumbnails
        into the next document."""
        workers, self._workers = self._workers, []
        for worker in workers:
            worker.cancel()
            # Disconnect BEFORE waiting so a thumbnail emitted between the
            # cancel flag check and the worker unwinding can't sneak into
            # the model for the old document. The epoch guard in
            # _on_image_ready is the belt; this disconnect is the braces.
            with contextlib.suppress(RuntimeError, TypeError):
                worker.thumbnail_ready.disconnect(self._on_image_ready)
            with contextlib.suppress(RuntimeError, TypeError):
                worker.render_failed.disconnect(self._on_render_failed)
            # 2 s is generous — a single page render at 40 DPI is well
            # under 100 ms; the cancel flag is polled between pages so
            # worst case we wait for the current page to finish.
            worker.wait(2000)

    def showEvent(self, event):  # noqa: D401
        """Render + repaint the now-visible rows when the panel appears.

        The Pages tab is typically hidden when the document loads (parked
        behind the Contents tab for a PDF that has a TOC), so this is
        where the real visible range first becomes knowable. We (1) kick
        the lazy renderer for the pages now on screen and (2) force the
        view to re-read DecorationRole against the cache so any pixmaps
        that arrived while hidden are painted instead of staying on ``…``
        placeholders.
        """
        super().showEvent(event)
        if self._view is None:
            return
        _log.debug("showEvent: visible=%s cache=%d",
                   self.isVisible(), self._model.cache_size())
        self._render_visible()
        vp = self._view.viewport()
        if vp is not None:
            self._model.refresh_decorations()
            vp.update()

            # Layout can still be incomplete when showEvent fires (the tab
            # was just switched — viewport size is still the collapsed
            # placeholder value). Re-run after the current event-loop
            # iteration against the final geometry so we render/repaint the
            # rows that are actually on screen.
            def _refresh_again():
                if self._view is None:
                    return
                self._render_visible()
                self._model.refresh_decorations()
                v = self._view.viewport()
                if v is not None:
                    v.update()
            QTimer.singleShot(0, _refresh_again)

    def resizeEvent(self, event):  # noqa: D401
        """Render + repaint newly-visible rows on resize so growing the
        panel (or the first real layout after a collapsed one) fills in
        thumbnails instead of leaving fresh rows on placeholders."""
        super().resizeEvent(event)
        if self._view is None:
            return
        self._render_visible()
        vp = self._view.viewport()
        if vp is not None:
            self._model.refresh_decorations()
            vp.update()

    def closeEvent(self, event):  # noqa: D401
        self._stop_all_workers()
        super().closeEvent(event)
