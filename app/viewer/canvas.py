"""PDFApps – _SelectCanvas: renderiza todas as páginas PDF em scroll contínuo."""

from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtWidgets import QWidget, QApplication
import qtawesome as qta

from app.constants import BG_INNER, TEXT_SEC

_PAGE_GAP = 12   # pixels de espaço entre páginas


class _SelectCanvas(QWidget):
    """Renderiza todas as páginas PDF em scroll contínuo (estilo Acrobat).
    Suporta seleção de texto por arrastar em qualquer página.
    """

    zoom_changed = Signal(int)   # percentagem de zoom actual
    text_copied  = Signal(str)   # texto copiado (vazio = nenhum encontrado)

    def __init__(self):
        super().__init__()
        self._doc         = None   # fitz.Document
        self._zoom        = 1.0
        self._zoom_factor = 1.0
        self._base_avail  = 700
        # list of (QPixmap, y_offset, page_height, page_width, words_list)
        self._pages       = []
        self._drag_start  = None
        self._drag_end    = None
        self._sel_rects   = []
        self._sel_text    = ""
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setMinimumSize(300, 400)

    # ── API pública ───────────────────────────────────────────────────────────

    def load(self, doc, page_idx: int = 0):
        self._doc = doc
        self._zoom_factor = 1.0
        self._clear_selection()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._render)

    def scroll_to_page(self, idx: int) -> int:
        """Devolve o y_offset da página idx (para usar no QScrollBar)."""
        if 0 <= idx < len(self._pages):
            return self._pages[idx][1]
        return 0

    def page_at_y(self, y: int) -> int:
        """Devolve o índice da página visível na posição vertical y."""
        for i, (_, y_off, ph, _pw, _w) in enumerate(self._pages):
            if y_off <= y < y_off + ph + _PAGE_GAP:
                return i
        return max(0, len(self._pages) - 1)

    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    def zoom_in(self):
        self._zoom_factor = min(4.0, round(self._zoom_factor * 1.25, 4))
        self._render()

    def zoom_out(self):
        self._zoom_factor = max(0.2, round(self._zoom_factor / 1.25, 4))
        self._render()

    def zoom_reset(self):
        self._zoom_factor = 1.0
        self._render()

    def close_doc(self):
        if self._doc:
            self._doc.close()
            self._doc = None
        self._pages = []
        self._clear_selection()
        self.setFixedSize(300, 400)
        self.update()

    # ── Internos ─────────────────────────────────────────────────────────────

    def _clear_selection(self):
        self._drag_start = None
        self._drag_end   = None
        self._sel_rects  = []
        self._sel_text   = ""

    def _page_word_to_screen(self, y_offset: int, x0, y0, x1, y1) -> QRect:
        z = self._zoom
        return QRect(int(x0 * z), y_offset + int(y0 * z),
                     max(1, int((x1 - x0) * z)),
                     max(1, int((y1 - y0) * z)))

    def _render(self):
        if not self._doc:
            return
        try:
            import fitz
            from PySide6.QtGui import QPixmap as QP, QImage

            # Recalcular largura disponível quando zoom == 1.0 (ajustar à janela)
            if self._zoom_factor == 1.0:
                from PySide6.QtWidgets import QScrollArea as _SA
                vp = self.parent()
                sa = vp.parent() if vp else None
                avail = sa.viewport().width() - 4 if isinstance(sa, _SA) else self.width()
                self._base_avail = max(avail, 300)

            ref_width = self._doc[0].rect.width
            dpr = self.devicePixelRatioF() or 1.0
            self._zoom = (self._base_avail / ref_width) * self._zoom_factor
            render_zoom = self._zoom * dpr

            pages = []
            total_h = 0
            max_w = 0

            for i in range(self._doc.page_count):
                page = self._doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(render_zoom, render_zoom))
                img = pix.tobytes("png")
                qp = QP()
                if not qp.loadFromData(img):
                    qi = QImage(pix.samples_mv, pix.width, pix.height,
                                pix.stride, QImage.Format.Format_RGB888)
                    qp = QP.fromImage(qi)
                qp.setDevicePixelRatio(dpr)
                ph = round(qp.height() / dpr)
                pw = round(qp.width() / dpr)
                words = page.get_text("words")  # (x0,y0,x1,y1,word,...)
                pages.append((qp, total_h, ph, pw, words))
                total_h += ph + _PAGE_GAP
                max_w = max(max_w, pw)

            self._pages = pages
            self.setFixedSize(max_w, max(total_h, 400))
            self._clear_selection()
            self.zoom_changed.emit(round(self._zoom_factor * 100))
            self.update()
        except Exception:
            import traceback
            traceback.print_exc()

    def _compute_selection(self):
        import fitz
        if not self._drag_start or not self._drag_end:
            return
        sx1 = min(self._drag_start.x(), self._drag_end.x())
        sy1 = min(self._drag_start.y(), self._drag_end.y())
        sx2 = max(self._drag_start.x(), self._drag_end.x())
        sy2 = max(self._drag_start.y(), self._drag_end.y())

        rects, words = [], []
        for (_, y_off, ph, _pw, page_words) in self._pages:
            if y_off + ph < sy1 or y_off > sy2:
                continue
            sel_r = fitz.Rect(
                sx1 / self._zoom,
                max(0.0, (sy1 - y_off) / self._zoom),
                sx2 / self._zoom,
                (sy2 - y_off) / self._zoom,
            )
            for w in page_words:
                x0, y0, x1, y1, word = w[0], w[1], w[2], w[3], w[4]
                if sel_r.intersects(fitz.Rect(x0, y0, x1, y1)):
                    rects.append(self._page_word_to_screen(y_off, x0, y0, x1, y1))
                    words.append(word)

        self._sel_rects = rects
        self._sel_text  = " ".join(words)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        from PySide6.QtGui import QPainter, QColor, QPen
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG_INNER))
        for (qpix, y_off, ph, pw, _) in self._pages:
            p.drawPixmap(0, y_off, qpix)
            p.setPen(QPen(QColor("#0d0d1a"), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(0, y_off, pw - 1, ph - 1)
        if not self._pages:
            from PySide6.QtGui import QFont
            p.setPen(QColor(TEXT_SEC))
            f = QFont(); f.setPointSize(11); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Abre um PDF para visualizar")
        for r in self._sel_rects:
            p.fillRect(r, QColor(59, 130, 246, 90))
        if self._drag_start and self._drag_end:
            drag_r = QRect(self._drag_start, self._drag_end).normalized()
            p.setPen(QPen(QColor("#3B82F6"), 1))
            p.setBrush(QColor(59, 130, 246, 25))
            p.drawRect(drag_r)

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
        self._compute_selection()
        self._drag_start = None
        self._drag_end   = None
        if self._sel_text:
            QApplication.clipboard().setText(self._sel_text)
        self.text_copied.emit(self._sel_text)
        self.update()
        e.accept()

    # ── Teclado ───────────────────────────────────────────────────────────────

    def keyPressEvent(self, e):
        if (e.modifiers() & Qt.KeyboardModifier.ControlModifier
                and e.key() == Qt.Key.Key_C and self._sel_text):
            QApplication.clipboard().setText(self._sel_text)
            e.accept()
        else:
            super().keyPressEvent(e)

    # ── Menu contextual ───────────────────────────────────────────────────────

    def contextMenuEvent(self, e):
        from PySide6.QtWidgets import QMenu
        if not self._sel_text:
            return
        menu = QMenu(self)
        act = menu.addAction(
            qta.icon("fa5s.copy", color=TEXT_SEC),
            f"  Copiar  ({len(self._sel_text)} car.)")
        act.triggered.connect(lambda: QApplication.clipboard().setText(self._sel_text))
        menu.exec(e.globalPos())
