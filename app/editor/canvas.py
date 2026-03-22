"""PDFApps – PdfEditCanvas: visual PDF edit canvas with fitz rendering."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget

from app.constants import ACCENT, BG_INNER, TEXT_SEC


class PdfEditCanvas(QWidget):
    rect_selected = Signal(object)   # fitz.Rect em coords PDF
    point_clicked = Signal(object)   # fitz.Point em coords PDF

    zoom_changed = Signal(int)   # percentagem actual

    def __init__(self):
        super().__init__()
        self._doc         = None
        self._page_idx    = 0
        self._zoom        = 1.0
        self._zoom_factor = 1.0
        self._base_avail  = 300
        self._qpix        = None
        self._drag_start  = None
        self._drag_rect   = None
        self._overlays    = []
        self._select_mode = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMinimumSize(300, 400)

    def set_select_mode(self, active: bool):
        self._select_mode = active
        self.setCursor(Qt.CursorShape.IBeamCursor if active else Qt.CursorShape.CrossCursor)

    def set_overlays(self, overlays: list):
        self._overlays = overlays
        self.update()

    def load(self, path: str):
        import fitz
        if self._doc: self._doc.close()
        self._doc = fitz.open(path)
        self._page_idx = 0
        self._zoom_factor = 1.0
        # diferir render para o splitter estar posicionado
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._render)

    def zoom_in(self):
        self._zoom_factor = min(4.0, round(self._zoom_factor * 1.25, 4))
        self._render()

    def zoom_out(self):
        self._zoom_factor = max(0.2, round(self._zoom_factor / 1.25, 4))
        self._render()

    def zoom_reset(self):
        self._zoom_factor = 1.0
        self._render()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if e.angleDelta().y() > 0: self.zoom_in()
            else: self.zoom_out()
            e.accept()
        else:
            super().wheelEvent(e)

    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    def set_page(self, idx: int):
        if self._doc and 0 <= idx < self._doc.page_count:
            self._page_idx = idx
            self._render()

    def get_span_at(self, pdf_pt):
        """Devolve o span fitz mais próximo de pdf_pt (usa o doc já aberto — sem re-abrir o ficheiro)."""
        if not self._doc: return None
        import fitz
        page = self._doc[self._page_idx]
        click = fitz.Point(pdf_pt.x, pdf_pt.y)
        found, best_dist = None, 30.0
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0: continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bbox = fitz.Rect(span["bbox"])
                    if bbox.contains(click):
                        return span
                    cx = max(bbox.x0, min(click.x, bbox.x1))
                    cy = max(bbox.y0, min(click.y, bbox.y1))
                    dist = ((click.x - cx)**2 + (click.y - cy)**2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist; found = span
        return found

    def close_doc(self):
        if self._doc: self._doc.close(); self._doc = None
        self._qpix = None; self._overlays = []
        self.setFixedSize(300, 400); self.update()

    def _render(self):
        if not self._doc: return
        import fitz
        from PySide6.QtGui import QPixmap as QP
        page = self._doc[self._page_idx]
        if self._zoom_factor == 1.0:
            from PySide6.QtWidgets import QScrollArea as _SA
            vp = self.parent()
            sa = vp.parent() if vp else None
            avail = sa.viewport().width() - 4 if isinstance(sa, _SA) else self.width()
            self._base_avail = max(avail, 300)
        # renderizar a resolução mais alta (DPR × zoom) para qualidade nítida
        dpr = self.devicePixelRatioF() or 1.0
        self._zoom = (self._base_avail / page.rect.width) * self._zoom_factor
        render_zoom = self._zoom * dpr
        pix = page.get_pixmap(matrix=fitz.Matrix(render_zoom, render_zoom))
        qp = QP(); qp.loadFromData(pix.tobytes("png"))
        qp.setDevicePixelRatio(dpr)
        self._qpix = qp
        # tamanho lógico (sem DPR) para o layout
        self.setFixedSize(round(qp.width() / dpr), round(qp.height() / dpr))
        self.zoom_changed.emit(round(self._zoom_factor * 100))
        self.update()

    def _to_pdf(self, sx, sy):
        import fitz
        return fitz.Point(sx / self._zoom, sy / self._zoom)

    def _rect_to_pdf(self, r):
        import fitz
        return fitz.Rect(r.left()/self._zoom, r.top()/self._zoom,
                         r.right()/self._zoom, r.bottom()/self._zoom)

    def paintEvent(self, _):
        from PySide6.QtGui import QPainter, QColor, QPen, QFont
        from PySide6.QtCore import QRect
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG_INNER))
        if self._qpix:
            p.drawPixmap(0, 0, self._qpix)
        else:
            p.setPen(QColor(TEXT_SEC))
            f = QFont(); f.setPointSize(11); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Abre um PDF para editar")
        # ── overlays dos edits pendentes ─────────────────────────────────────
        z = self._zoom
        for e in self._overlays:
            t = e["type"]
            if t == "redact":
                r = e["rect"]
                fill = e["fill"]
                qr = QRect(int(r.x0*z), int(r.y0*z), max(1,int(r.width*z)), max(1,int(r.height*z)))
                p.fillRect(qr, QColor(int(fill[0]*255), int(fill[1]*255), int(fill[2]*255), 210))
                p.setPen(QPen(QColor("#EF4444"), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(qr)
            elif t == "highlight":
                r = e["rect"]; c = e["color"]
                qr = QRect(int(r.x0*z), int(r.y0*z), max(1,int(r.width*z)), max(1,int(r.height*z)))
                p.fillRect(qr, QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255), 120))
            elif t == "text":
                pt = e["point"]; c = e["color"]
                p.setPen(QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255)))
                f2 = QFont(); f2.setPointSize(max(4, int(e["size"] * z * 0.75))); p.setFont(f2)
                p.drawText(int(pt.x*z), int(pt.y*z), e["text"])
            elif t == "image":
                r = e["rect"]
                qr = QRect(int(r.x0*z), int(r.y0*z), max(1,int(r.width*z)), max(1,int(r.height*z)))
                from PySide6.QtGui import QPixmap as _QPixmap
                img_px = _QPixmap(e["path"])
                if not img_px.isNull():
                    p.drawPixmap(qr, img_px)
                p.setPen(QPen(QColor(ACCENT), 2, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(qr)
            elif t == "note":
                pt = e["point"]
                px, py = int(pt.x*z), int(pt.y*z)
                # ícone de nota (fundo amarelo)
                icon_r = QRect(px, py - 18, 22, 22)
                p.setBrush(QColor("#FBBF24")); p.setPen(QPen(QColor("#D97706"), 1))
                p.drawRoundedRect(icon_r, 4, 4)
                fi = QFont(); fi.setPointSize(10); fi.setBold(True); p.setFont(fi)
                p.setPen(QColor("#1C1917")); p.drawText(icon_r, Qt.AlignmentFlag.AlignCenter, "✎")
                # preview do texto ao lado
                p.setPen(QColor("#FBBF24"))
                ft = QFont(); ft.setPointSize(8); p.setFont(ft)
                preview = e["text"][:40] + ("…" if len(e["text"]) > 40 else "")
                p.drawText(px + 26, py - 4, preview)
            elif t == "text_edit":
                r = e["bbox"]
                qr = QRect(int(r[0]*z), int(r[1]*z),
                           max(1, int((r[2]-r[0])*z)), max(1, int((r[3]-r[1])*z)))
                # original: fundo vermelho translúcido + risco
                p.fillRect(qr, QColor(239, 68, 68, 60))
                p.setPen(QPen(QColor("#EF4444"), 1, Qt.PenStyle.DashLine))
                p.drawRect(qr)
                mid_y = qr.top() + qr.height() // 2
                p.setPen(QPen(QColor("#EF4444"), 1)); p.drawLine(qr.left(), mid_y, qr.right(), mid_y)
                # novo texto: verde abaixo
                new_txt = e.get("new_text", "")
                if new_txt:
                    p.setPen(QColor("#22C55E"))
                    fn = QFont(); fn.setPointSize(max(4, int(e["size"] * z * 0.75))); p.setFont(fn)
                    p.drawText(int(r[0]*z), int(r[3]*z) + max(10, int(e["size"]*z*0.85)), new_txt)
        # ── drag rect ─────────────────────────────────────────────────────────
        if self._drag_rect:
            if self._select_mode:
                p.setPen(QPen(QColor("#3B82F6"), 2, Qt.PenStyle.SolidLine))
                p.setBrush(QColor(59, 130, 246, 50))
            else:
                p.setPen(QPen(QColor("#EF4444"), 2, Qt.PenStyle.DashLine))
                p.setBrush(QColor(239, 68, 68, 50))
            p.drawRect(self._drag_rect)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = e.position().toPoint()
            self._drag_rect  = None

    def mouseMoveEvent(self, e):
        if self._drag_start and (e.buttons() & Qt.MouseButton.LeftButton):
            from PySide6.QtCore import QRect
            self._drag_rect = QRect(self._drag_start, e.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton: return
        pos = e.position().toPoint()
        if self._drag_rect and self._drag_rect.width() > 3 and self._drag_rect.height() > 3:
            self.rect_selected.emit(self._rect_to_pdf(self._drag_rect))
        else:
            self.point_clicked.emit(self._to_pdf(pos.x(), pos.y()))
        self._drag_start = None; self._drag_rect = None
        self.update()
