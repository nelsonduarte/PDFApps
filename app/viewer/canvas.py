"""PDFApps – _SelectCanvas: continuous scroll with lazy rendering via threads."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRect, QObject, QRunnable, QThreadPool
from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtGui import QPixmap, QColor, QPainter, QPen, QFont
import qtawesome as qta

from app.constants import BG_INNER, TEXT_SEC, _LN
from app.i18n import t

_PAGE_GAP       = 4    # px between pages
_BUFFER_PGS     = 2    # extra pages to pre-render outside the visible area
_MAX_THREADS    = 2    # simultaneous render workers
_NOTE_ICON_SIZE = 22   # note icon size in pixels


# ── Worker ────────────────────────────────────────────────────────────────────

class _RenderSignals(QObject):
    page_ready = Signal(int, int, object, object)  # gen, idx, QPixmap, words


class _PageJob(QRunnable):
    """Renders a fitz page in a background thread."""

    def __init__(self, path: str, password: str, idx: int,
                 zoom: float, dpr: float, gen: int, signals: _RenderSignals,
                 night_mode: bool = False):
        super().__init__()
        self._path       = path
        self._password   = password
        self._idx        = idx
        self._zoom       = zoom
        self._dpr        = dpr
        self._gen        = gen
        self._night_mode = night_mode
        self.signals     = signals
        self.setAutoDelete(True)

    def run(self):
        try:
            import fitz
            from PySide6.QtGui import QPixmap as QP, QImage
            doc = fitz.open(self._path)
            if self._password:
                doc.authenticate(self._password)
            page  = doc[self._idx]
            rz    = self._zoom * self._dpr
            pix   = page.get_pixmap(matrix=fitz.Matrix(rz, rz), annots=False)
            if self._night_mode:
                pix.invert_irect()
            words = page.get_text("words")
            img   = pix.tobytes("png")
            doc.close()
            qp = QP()
            if not qp.loadFromData(img):
                from PySide6.QtGui import QImage
                qi = QImage(pix.samples_mv, pix.width, pix.height,
                            pix.stride, QImage.Format.Format_RGB888)
                qp = QP.fromImage(qi)
            qp.setDevicePixelRatio(self._dpr)
            self.signals.page_ready.emit(self._gen, self._idx, qp, words)
        except Exception:
            import traceback
            traceback.print_exc()


# ── Page entry ─────────────────────────────────────────────────────────

class _PageEntry:
    __slots__ = ("y_off", "w", "h", "pixmap", "words", "annots")

    def __init__(self, y_off: int, w: int, h: int):
        self.y_off  = y_off
        self.w      = w
        self.h      = h
        self.pixmap = None   # QPixmap | None — filled by worker
        self.words  = None   # list | None   — filled by worker
        self.annots = None   # list | None   — [(rect, text), ...]


# ── Canvas ────────────────────────────────────────────────────────────────────

class _SelectCanvas(QWidget):
    """Continuous scroll of all pages with lazy background rendering."""

    zoom_changed = Signal(int)   # current zoom percentage
    text_copied  = Signal(str)   # copied text (empty = no text layer)

    def __init__(self):
        super().__init__()
        self._doc         = None    # fitz.Document (main thread only)
        self._path        = ""
        self._password    = ""
        self._zoom        = 1.0
        self._zoom_factor = 1.0
        self._base_avail  = 700
        self._entries: list[_PageEntry] = []
        self._gen         = 0       # generation — invalidates old renders
        self._pending: set[int] = set()
        self._signals     = _RenderSignals()
        self._signals.page_ready.connect(self._on_page_ready)
        self._night_mode  = False
        self._drag_start  = None
        self._drag_end    = None
        self._sel_rects: list[QRect] = []
        self._sel_text    = ""
        self._open_note   = None   # (page_idx, annot_idx) of open balloon
        self._search_highlights: list[tuple[int, object]] = []  # [(page_idx, fitz_rect), ...]
        self._search_current = -1   # index of current match in _search_highlights
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setMinimumSize(300, 400)
        self._bg_color = BG_INNER

    # ── Public API ───────────────────────────────────────────────────────────

    def load(self, doc, page_idx: int = 0, path: str = "", password: str = ""):
        self._doc      = doc
        self._path     = path or (doc.name if doc else "")
        self._password = password
        self._zoom_factor = 1.0
        self._gen     += 1
        self._pending.clear()
        self._clear_selection()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._layout_and_schedule)

    def on_scroll(self):
        """Called when scroll changes — schedules newly visible pages."""
        self._schedule_visible()

    def scroll_to_page(self, idx: int) -> int:
        if 0 <= idx < len(self._entries):
            return self._entries[idx].y_off
        return 0

    def page_at_y(self, y: int) -> int:
        for i, e in enumerate(self._entries):
            if e.y_off <= y < e.y_off + e.h + _PAGE_GAP:
                return i
        return max(0, len(self._entries) - 1)

    def page_count(self) -> int:
        return len(self._entries)

    def set_search_highlights(self, highlights: list, current: int = -1):
        self._search_highlights = highlights
        self._search_current = current

    def zoom_in(self):
        self._zoom_factor = min(4.0, round(self._zoom_factor * 1.25, 4))
        self._invalidate_and_relayout()

    def zoom_out(self):
        self._zoom_factor = max(0.2, round(self._zoom_factor / 1.25, 4))
        self._invalidate_and_relayout()

    def zoom_reset(self):
        self._zoom_factor = 1.0
        self._invalidate_and_relayout()

    def set_dark_mode(self, dark: bool):
        # Force dark bg in night mode regardless of app theme
        if self._night_mode:
            self._bg_color = "#000000"
        else:
            self._bg_color = BG_INNER if dark else _LN
        self.update()

    def set_night_mode(self, active: bool):
        if self._night_mode == active:
            return
        self._night_mode = active
        self._bg_color = "#000000" if active else BG_INNER
        # Invalidate cached pixmaps and re-render with new flag
        self._invalidate_and_relayout()

    def close_doc(self):
        self._gen += 1
        self._pending.clear()
        if self._doc is not None:
            try:
                self._doc.close()
            except ValueError:
                pass
            self._doc = None
        self._entries = []
        self._clear_selection()
        self.setFixedSize(300, 400)
        self.update()

    # ── Layout ───────────────────────────────────────────────────────────────

    def _invalidate_and_relayout(self):
        self._gen += 1
        self._pending.clear()
        for e in self._entries:
            e.pixmap = None
        self._layout_and_schedule()

    def _layout_and_schedule(self):
        """Calculate dimensions of all pages (fast — no pixel rendering)
        and schedule rendering of visible pages in background."""
        if not self._doc:
            return

        if self._zoom_factor == 1.0:
            from PySide6.QtWidgets import QScrollArea as _SA
            vp = self.parent()
            sa = vp.parent() if vp else None
            avail = sa.viewport().width() - 4 if isinstance(sa, _SA) else self.width()
            self._base_avail = max(avail, 300)

        ref_w = self._doc[0].rect.width
        self._zoom = (self._base_avail / ref_w) * self._zoom_factor

        entries: list[_PageEntry] = []
        total_h = 0
        max_w   = 0
        for i in range(self._doc.page_count):
            r  = self._doc[i].rect
            pw = round(r.width  * self._zoom)
            ph = round(r.height * self._zoom)
            entries.append(_PageEntry(total_h, pw, ph))
            total_h += ph + _PAGE_GAP
            max_w    = max(max_w, pw)

        self._entries = entries
        self.setFixedSize(max_w, max(total_h, 400))
        self.zoom_changed.emit(round(self._zoom_factor * 100))
        self._load_annotations()
        self._open_note = None
        self.update()          # show placeholders immediately
        self._schedule_visible()

    def _load_annotations(self):
        """Load text annotations for all pages."""
        if not self._doc:
            return
        import fitz
        for page_idx in range(self._doc.page_count):
            if page_idx >= len(self._entries):
                break
            page = self._doc[page_idx]
            notes = []
            for annot in page.annots():
                if annot.type[0] == fitz.PDF_ANNOT_TEXT:
                    txt = annot.info.get("content", "")
                    if txt:
                        notes.append((annot.rect, txt))
            self._entries[page_idx].annots = notes

    # ── Lazy render ──────────────────────────────────────────────────────────

    def _visible_range(self) -> tuple[int, int]:
        from PySide6.QtWidgets import QScrollArea as _SA
        vp = self.parent()
        sa = vp.parent() if vp else None
        n  = len(self._entries)
        if not isinstance(sa, _SA) or not n:
            return (0, min(n - 1, _BUFFER_PGS * 2))

        y0 = sa.verticalScrollBar().value()
        y1 = y0 + sa.viewport().height()

        first = last = 0
        found = False
        for i, e in enumerate(self._entries):
            if not found and e.y_off + e.h >= y0:
                first = i
                found = True
            if e.y_off <= y1:
                last = i

        return (max(0, first - _BUFFER_PGS), min(n - 1, last + _BUFFER_PGS))

    def _schedule_visible(self):
        if not self._entries or not self._path:
            return
        first, last = self._visible_range()
        dpr = self.devicePixelRatioF() or 1.0
        gen = self._gen
        pool = QThreadPool.globalInstance()
        pool.setMaxThreadCount(_MAX_THREADS)
        for i in range(first, last + 1):
            e = self._entries[i]
            if e.pixmap is None and i not in self._pending:
                self._pending.add(i)
                pool.start(_PageJob(self._path, self._password, i,
                                    self._zoom, dpr, gen, self._signals,
                                    night_mode=self._night_mode))

    def _on_page_ready(self, gen: int, idx: int, pixmap, words):
        if gen != self._gen:
            return  # outdated render after zoom change — discard
        self._pending.discard(idx)
        if 0 <= idx < len(self._entries):
            self._entries[idx].pixmap = pixmap
            self._entries[idx].words  = words
            self.update()

    # ── Text selection ─────────────────────────────────────────────────────

    def _clear_selection(self):
        self._drag_start = None
        self._drag_end   = None
        self._sel_rects  = []
        self._sel_text   = ""

    def _page_word_to_screen(self, y_off: int, x0, y0, x1, y1) -> QRect:
        z = self._zoom
        return QRect(int(x0 * z), y_off + int(y0 * z),
                     max(1, int((x1 - x0) * z)),
                     max(1, int((y1 - y0) * z)))

    def _find_closest_word(self, pos) -> tuple[int, int]:
        """Return (page_idx, word_idx) for the word closest to screen pos."""
        z = self._zoom
        best_page, best_idx, best_dist = -1, -1, float("inf")
        for pi, e in enumerate(self._entries):
            if not e.words:
                continue
            # Skip pages far from the click
            if pos.y() < e.y_off - 50 or pos.y() > e.y_off + e.h + 50:
                continue
            px = pos.x() / z
            py = (pos.y() - e.y_off) / z
            for wi, w in enumerate(e.words):
                cx = (w[0] + w[2]) / 2
                cy = (w[1] + w[3]) / 2
                d = (px - cx) ** 2 + (py - cy) ** 2
                if d < best_dist:
                    best_dist = d
                    best_page = pi
                    best_idx = wi
        return best_page, best_idx

    def _compute_selection(self):
        if not self._drag_start or not self._drag_end:
            return
        p1_page, p1_word = self._find_closest_word(self._drag_start)
        p2_page, p2_word = self._find_closest_word(self._drag_end)
        if p1_page < 0 or p2_page < 0:
            return
        # Ensure start <= end in reading order
        if (p1_page, p1_word) > (p2_page, p2_word):
            p1_page, p1_word, p2_page, p2_word = p2_page, p2_word, p1_page, p1_word
        rects, words = [], []
        for pi in range(p1_page, p2_page + 1):
            e = self._entries[pi]
            if not e.words:
                continue
            w_start = p1_word if pi == p1_page else 0
            w_end   = p2_word if pi == p2_page else len(e.words) - 1
            for wi in range(w_start, w_end + 1):
                w = e.words[wi]
                # Extend rect to fill gap to next word on same line
                x0, y0, x1, y1 = w[0], w[1], w[2], w[3]
                if wi < w_end:
                    nw = e.words[wi + 1]
                    # Same line if vertical overlap > 50%
                    line_h = y1 - y0
                    overlap = min(y1, nw[3]) - max(y0, nw[1])
                    if overlap > line_h * 0.5:
                        x1 = nw[0]  # extend to start of next word
                rects.append(self._page_word_to_screen(e.y_off, x0, y0, x1, y1))
                words.append(w[4])
        self._sel_rects = rects
        self._sel_text  = " ".join(words)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self._bg_color))

        if not self._entries:
            p.setPen(QColor(TEXT_SEC))
            f = QFont(); f.setPointSize(11); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       t("viewer.open_prompt"))
            return

        first, last = self._visible_range()
        for i in range(first, last + 1):
            e = self._entries[i]
            if e.pixmap:
                p.drawPixmap(0, e.y_off, e.pixmap)
            else:
                p.fillRect(0, e.y_off, e.w, e.h, QColor("#252F45"))
                p.setPen(QColor(TEXT_SEC))
                f = QFont(); f.setPointSize(9); p.setFont(f)
                p.drawText(QRect(0, e.y_off, e.w, e.h),
                           Qt.AlignmentFlag.AlignCenter, t("viewer.loading"))
            p.setPen(QPen(QColor("#0d0d1a"), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(0, e.y_off, e.w - 1, e.h - 1)

        # ── Note icons ──
        z = self._zoom
        for page_idx in range(first, last + 1):
            entry = self._entries[page_idx]
            if not entry.annots:
                continue
            for annot_idx, (rect, txt) in enumerate(entry.annots):
                px = int(rect.x0 * z)
                py = entry.y_off + int(rect.y0 * z)
                # Draw pencil icon
                icon_r = QRect(px, py, _NOTE_ICON_SIZE, _NOTE_ICON_SIZE)
                p.setBrush(QColor("#FBBF24"))
                p.setPen(QPen(QColor("#D97706"), 1))
                p.drawRoundedRect(icon_r, 4, 4)
                fi = QFont(); fi.setPointSize(10); fi.setBold(True); p.setFont(fi)
                p.setPen(QColor("#1C1917"))
                p.drawText(icon_r, Qt.AlignmentFlag.AlignCenter, "✎")
                # Draw balloon if this note is open
                if self._open_note == (page_idx, annot_idx):
                    balloon_x = px + _NOTE_ICON_SIZE + 6
                    balloon_y = py
                    ft = QFont(); ft.setPointSize(9); p.setFont(ft)
                    fm = p.fontMetrics()
                    lines = txt.split("\n")
                    text_w = max(fm.horizontalAdvance(ln) for ln in lines) + 20
                    text_h = fm.height() * len(lines) + 16
                    balloon_w = max(140, min(text_w, 300))
                    balloon_h = max(36, text_h)
                    balloon_r = QRect(balloon_x, balloon_y, balloon_w, balloon_h)
                    # Shadow
                    shadow_r = QRect(balloon_x + 2, balloon_y + 2, balloon_w, balloon_h)
                    p.setBrush(QColor(0, 0, 0, 30)); p.setPen(Qt.PenStyle.NoPen)
                    p.drawRoundedRect(shadow_r, 6, 6)
                    # Balloon background
                    p.setBrush(QColor("#FFFDF5")); p.setPen(QPen(QColor("#D97706"), 1))
                    p.drawRoundedRect(balloon_r, 6, 6)
                    # Text in black
                    p.setPen(QColor("#000000"))
                    text_rect = QRect(balloon_x + 10, balloon_y + 8,
                                      balloon_w - 20, balloon_h - 16)
                    p.drawText(text_rect,
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                               txt)

        # ── Search highlights ──
        z = self._zoom
        for hi_idx, (pg_idx, fr) in enumerate(self._search_highlights):
            if pg_idx < first or pg_idx > last:
                continue
            ey = self._entries[pg_idx].y_off
            rx = int(fr.x0 * z)
            ry = ey + int(fr.y0 * z)
            rw = int((fr.x1 - fr.x0) * z)
            rh = int((fr.y1 - fr.y0) * z)
            if hi_idx == self._search_current:
                p.fillRect(rx, ry, rw, rh, QColor(249, 115, 22, 140))  # orange for current
                p.setPen(QPen(QColor("#F97316"), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(rx, ry, rw, rh)
            else:
                p.fillRect(rx, ry, rw, rh, QColor(250, 204, 21, 100))  # yellow for others

        # ── Selection (Acrobat-style word-flow highlight) ──
        for r in self._sel_rects:
            p.fillRect(r, QColor(59, 130, 246, 90))

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self._drag_start = e.position().toPoint()
            self._drag_end   = self._drag_start
            self._sel_rects  = []
            self._sel_text   = ""
            self.update()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_start and (e.buttons() & Qt.MouseButton.LeftButton):
            self._drag_end = e.position().toPoint()
            self._compute_selection()
            self.update()
            e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or not self._drag_start:
            return
        self._drag_end = e.position().toPoint()
        # Check for click (no drag) on a note icon
        is_click = (abs(self._drag_start.x() - self._drag_end.x()) < 4
                     and abs(self._drag_start.y() - self._drag_end.y()) < 4)
        if is_click:
            hit = self._note_icon_at(self._drag_end)
            if hit is not None:
                self._open_note = None if self._open_note == hit else hit
                self._drag_start = None
                self._drag_end = None
                self.update()
                e.accept()
                return
            # Close any open balloon when clicking elsewhere
            if self._open_note is not None:
                self._open_note = None
                self.update()
        self._compute_selection()
        self._drag_start = None
        self._drag_end   = None
        if self._sel_text:
            QApplication.clipboard().setText(self._sel_text)
        self.text_copied.emit(self._sel_text)
        self.update()
        e.accept()

    def _note_icon_at(self, pos):
        """Return (page_idx, annot_idx) if pos hits a note icon, else None."""
        z = self._zoom
        margin = 8
        for page_idx, entry in enumerate(self._entries):
            if not entry.annots:
                continue
            if pos.y() < entry.y_off - margin or pos.y() > entry.y_off + entry.h + margin:
                continue
            for annot_idx, (rect, txt) in enumerate(entry.annots):
                px = int(rect.x0 * z)
                py = entry.y_off + int(rect.y0 * z)
                hit_r = QRect(px - margin, py - margin,
                              _NOTE_ICON_SIZE + margin * 2, _NOTE_ICON_SIZE + margin * 2)
                if hit_r.contains(pos):
                    return (page_idx, annot_idx)
        return None

    # ── Keyboard ───────────────────────────────────────────────────────────────

    def keyPressEvent(self, e):
        if (e.modifiers() & Qt.KeyboardModifier.ControlModifier
                and e.key() == Qt.Key.Key_C and self._sel_text):
            QApplication.clipboard().setText(self._sel_text)
            e.accept()
        else:
            super().keyPressEvent(e)

    # ── Context menu ───────────────────────────────────────────────────────

    def contextMenuEvent(self, e):
        from PySide6.QtWidgets import QMenu
        pos = e.pos()
        # Check if right-click is on a note icon
        hit = self._note_icon_at(pos)
        if hit is not None:
            menu = QMenu(self)
            delete_action = menu.addAction(t("viewer.delete_comment"))
            action = menu.exec(e.globalPos())
            if action == delete_action:
                page_idx, annot_idx = hit
                entry = self._entries[page_idx]
                if entry.annots and annot_idx < len(entry.annots):
                    rect, txt = entry.annots[annot_idx]
                    # Remove annotation from fitz doc
                    if self._doc:
                        import fitz
                        page = self._doc[page_idx]
                        for annot in page.annots() or []:
                            if annot.type[0] == fitz.PDF_ANNOT_TEXT:
                                content = annot.info.get("content", "") or ""
                                if content.strip() == txt.strip():
                                    page.delete_annot(annot)
                                    break
                        # Save the doc
                        if self._path:
                            self._doc.saveIncr()
                    # Remove from entry annots list
                    entry.annots.pop(annot_idx)
                    if self._open_note == hit:
                        self._open_note = None
                    self.update()
            return
        if not self._sel_text:
            return
        menu = QMenu(self)
        act  = menu.addAction(
            qta.icon("fa5s.copy", color=TEXT_SEC),
            f"  Copy  ({len(self._sel_text)} chars)")
        act.triggered.connect(lambda: QApplication.clipboard().setText(self._sel_text))
        menu.exec(e.globalPos())
