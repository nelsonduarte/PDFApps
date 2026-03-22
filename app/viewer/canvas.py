"""PDFApps – _SelectCanvas: renders PDF pages via fitz with text selection."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QApplication
import qtawesome as qta

from app.constants import BG_INNER, TEXT_SEC


class _SelectCanvas(QWidget):
    """Renderiza páginas PDF via fitz e suporta seleção de texto por arrastar."""

    zoom_changed   = Signal(int)   # percentagem actual
    text_copied    = Signal(str)   # texto copiado (vazio = nenhum encontrado)

    def __init__(self):
        super().__init__()
        self._doc         = None   # fitz.Document
        self._page_idx    = 0
        self._zoom        = 1.0
        self._zoom_factor = 1.0
        self._base_avail  = 700
        self._qpix        = None
        self._words       = []     # [(x0,y0,x1,y1,word,...)]
        self._drag_start  = None   # QPoint screen
        self._drag_end    = None   # QPoint screen
        self._sel_rects   = []     # [QRect screen]
        self._sel_text    = ""
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setMinimumSize(300, 400)

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, doc, page_idx: int = 0):
        self._doc = doc
        self._page_idx = page_idx
        self._zoom_factor = 1.0
        self._clear_selection()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._render)

    def set_page(self, idx: int):
        if self._doc and 0 <= idx < self._doc.page_count:
            self._page_idx = idx
            self._clear_selection()
            self._render()

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
        self._qpix = None
        self._words = []
        self._clear_selection()
        self.setFixedSize(300, 400)
        self.update()

    # ── Internos ─────────────────────────────────────────────────────────────

    def _clear_selection(self):
        self._drag_start = None
        self._drag_end   = None
        self._sel_rects  = []
        self._sel_text   = ""

    def _to_pdf(self, qpt):
        import fitz
        return fitz.Point(qpt.x() / self._zoom, qpt.y() / self._zoom)

    def _word_to_screen(self, x0, y0, x1, y1):
        from PySide6.QtCore import QRect
        z = self._zoom
        return QRect(int(x0 * z), int(y0 * z),
                     max(1, int((x1 - x0) * z)),
                     max(1, int((y1 - y0) * z)))

    def _render(self):
        if not self._doc:
            return
        try:
            import fitz
            from PySide6.QtGui import QPixmap as QP
            page = self._doc[self._page_idx]
            if self._zoom_factor == 1.0:
                from PySide6.QtWidgets import QScrollArea as _SA
                vp = self.parent()
                sa = vp.parent() if vp else None
                avail = sa.viewport().width() - 4 if isinstance(sa, _SA) else self.width()
                self._base_avail = max(avail, 300)
            dpr = self.devicePixelRatioF() or 1.0
            self._zoom = (self._base_avail / page.rect.width) * self._zoom_factor
            render_zoom = self._zoom * dpr
            pix = page.get_pixmap(matrix=fitz.Matrix(render_zoom, render_zoom))
            img = pix.tobytes("png")
            qp = QP()
            if not qp.loadFromData(img):
                # Fallback: try via QImage for unusual colorspaces
                from PySide6.QtGui import QImage
                qi = QImage(pix.samples_mv, pix.width, pix.height,
                            pix.stride, QImage.Format.Format_RGB888)
                qp = QP.fromImage(qi)
            qp.setDevicePixelRatio(dpr)
            self._qpix = qp
            self.setFixedSize(round(qp.width() / dpr), round(qp.height() / dpr))
            self._words = page.get_text("words")  # (x0,y0,x1,y1,word,block,line,word_no)
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
        sp = self._to_pdf(self._drag_start)
        ep = self._to_pdf(self._drag_end)
        sel_r = fitz.Rect(min(sp.x, ep.x), min(sp.y, ep.y),
                          max(sp.x, ep.x), max(sp.y, ep.y))
        rects, words = [], []
        for w in self._words:
            x0, y0, x1, y1, word = w[0], w[1], w[2], w[3], w[4]
            if sel_r.intersects(fitz.Rect(x0, y0, x1, y1)):
                rects.append(self._word_to_screen(x0, y0, x1, y1))
                words.append(word)
        self._sel_rects = rects
        self._sel_text  = " ".join(words)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        from PySide6.QtGui import QPainter, QColor, QPen
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG_INNER))
        if self._qpix:
            p.drawPixmap(0, 0, self._qpix)
        else:
            from PySide6.QtGui import QFont
            p.setPen(QColor(TEXT_SEC))
            f = QFont(); f.setPointSize(11); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Abre um PDF para visualizar")
        for r in self._sel_rects:
            p.fillRect(r, QColor(59, 130, 246, 90))
        if self._drag_start and self._drag_end:
            from PySide6.QtCore import QRect
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

    # ── Scroll ────────────────────────────────────────────────────────────────
    # O Ctrl+scroll é tratado pelo eventFilter de PdfViewerPanel (instalado no
    # canvas e no viewport), garantindo que o QScrollArea não interfere.
