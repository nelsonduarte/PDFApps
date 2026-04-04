"""PDFApps – PdfEditCanvas: visual PDF edit canvas with fitz rendering."""

from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtWidgets import QWidget, QSizePolicy

from app.constants import ACCENT, BG_INNER, TEXT_SEC
from app.i18n import t

# Size of the note icon in pixels
_NOTE_ICON_SIZE = 22


class PdfEditCanvas(QWidget):
    rect_selected = Signal(object)   # fitz.Rect in PDF coords
    point_clicked = Signal(object)   # fitz.Point in PDF coords
    note_deleted  = Signal(dict)     # overlay dict of deleted note

    zoom_changed = Signal(int)   # current percentage

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
        self._open_note   = None   # index of the note overlay with open balloon
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMinimumSize(300, 400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_select_mode(self, active: bool):
        self._select_mode = active

    def set_overlays(self, overlays: list):
        self._overlays = overlays
        self._open_note = None
        self.update()

    def load(self, path: str):
        import fitz
        if self._doc: self._doc.close()
        self._doc = fitz.open(path)
        self._page_idx = 0
        self._zoom_factor = 1.0
        # defer render until the splitter is positioned
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
        """Returns the closest fitz span to pdf_pt (uses the already open doc — no file re-open)."""
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

    def release_doc(self):
        """Close the fitz document to release the file lock, keeping the canvas state."""
        if self._doc: self._doc.close(); self._doc = None

    def close_doc(self):
        """Fully close and reset the canvas."""
        self.release_doc()
        self._qpix = None; self._overlays = []; self._open_note = None
        self.setMinimumSize(300, 400)
        self.setMaximumSize(16777215, 16777215)  # remove fixed size constraint
        self.update()

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
        # render at higher resolution (DPR × zoom) for crisp quality
        dpr = self.devicePixelRatioF() or 1.0
        self._zoom = (self._base_avail / page.rect.width) * self._zoom_factor
        render_zoom = self._zoom * dpr
        pix = page.get_pixmap(matrix=fitz.Matrix(render_zoom, render_zoom), annots=False)
        qp = QP(); qp.loadFromData(pix.tobytes("png"))
        qp.setDevicePixelRatio(dpr)
        self._qpix = qp
        # logical size (without DPR) for layout
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
                       t("edit.open_prompt"))
        # ── pending edit overlays ─────────────────────────────────────
        z = self._zoom
        for e in self._overlays:
            etype = e["type"]
            if etype == "redact":
                r = e["rect"]
                fill = e["fill"]
                qr = QRect(int(r.x0*z), int(r.y0*z), max(1,int(r.width*z)), max(1,int(r.height*z)))
                p.fillRect(qr, QColor(int(fill[0]*255), int(fill[1]*255), int(fill[2]*255), 210))
                p.setPen(QPen(QColor("#EF4444"), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(qr)
            elif etype == "highlight":
                r = e["rect"]; c = e["color"]
                qr = QRect(int(r.x0*z), int(r.y0*z), max(1,int(r.width*z)), max(1,int(r.height*z)))
                p.fillRect(qr, QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255), 120))
            elif etype == "text":
                pt = e["point"]; c = e["color"]
                p.setPen(QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255)))
                f2 = QFont(); f2.setPointSize(max(4, int(e["size"] * z * 0.75))); p.setFont(f2)
                p.drawText(int(pt.x*z), int(pt.y*z), e["text"])
            elif etype == "image":
                r = e["rect"]
                qr = QRect(int(r.x0*z), int(r.y0*z), max(1,int(r.width*z)), max(1,int(r.height*z)))
                from PySide6.QtGui import QPixmap as _QPixmap
                img_px = _QPixmap(e["path"])
                if not img_px.isNull():
                    p.drawPixmap(qr, img_px)
                p.setPen(QPen(QColor(ACCENT), 2, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(qr)
            elif etype == "note":
                pt = e["point"]
                px, py = int(pt.x*z), int(pt.y*z)
                note_idx = self._overlays.index(e) if e in self._overlays else -1
                # note icon (yellow background)
                icon_r = QRect(px, py - _NOTE_ICON_SIZE, _NOTE_ICON_SIZE, _NOTE_ICON_SIZE)
                p.setBrush(QColor("#FBBF24")); p.setPen(QPen(QColor("#D97706"), 1))
                p.drawRoundedRect(icon_r, 4, 4)
                fi = QFont(); fi.setPointSize(10); fi.setBold(True); p.setFont(fi)
                p.setPen(QColor("#1C1917")); p.drawText(icon_r, Qt.AlignmentFlag.AlignCenter, "✎")
                # balloon only when this note is open
                if self._open_note == note_idx:
                    balloon_x = px + _NOTE_ICON_SIZE + 6
                    balloon_y = py - _NOTE_ICON_SIZE - 4
                    ft = QFont(); ft.setPointSize(9); p.setFont(ft)
                    fm = p.fontMetrics()
                    lines = e["text"].split("\n")
                    text_w = max(fm.horizontalAdvance(ln) for ln in lines) + 20
                    text_h = fm.height() * len(lines) + 16
                    balloon_w = max(120, min(text_w, 260))
                    balloon_h = max(32, text_h)
                    balloon_r = QRect(balloon_x, balloon_y, balloon_w, balloon_h)
                    # shadow
                    shadow_r = QRect(balloon_x + 2, balloon_y + 2, balloon_w, balloon_h)
                    p.setBrush(QColor(0, 0, 0, 30)); p.setPen(Qt.PenStyle.NoPen)
                    p.drawRoundedRect(shadow_r, 6, 6)
                    # balloon background
                    p.setBrush(QColor("#FFFDF5")); p.setPen(QPen(QColor("#D97706"), 1))
                    p.drawRoundedRect(balloon_r, 6, 6)
                    # text in black
                    p.setPen(QColor("#000000"))
                    text_rect = QRect(balloon_x + 10, balloon_y + 8,
                                      balloon_w - 20, balloon_h - 16)
                    p.drawText(text_rect,
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                               e["text"])
            elif etype == "text_edit":
                r = e["bbox"]
                qr = QRect(int(r[0]*z), int(r[1]*z),
                           max(1, int((r[2]-r[0])*z)), max(1, int((r[3]-r[1])*z)))
                # original: translucent red background + strikethrough
                p.fillRect(qr, QColor(239, 68, 68, 60))
                p.setPen(QPen(QColor("#EF4444"), 1, Qt.PenStyle.DashLine))
                p.drawRect(qr)
                mid_y = qr.top() + qr.height() // 2
                p.setPen(QPen(QColor("#EF4444"), 1)); p.drawLine(qr.left(), mid_y, qr.right(), mid_y)
                # new text: green below
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

    def _note_icon_at(self, pos: QPoint) -> int:
        """Return the overlay index of a note icon under *pos*, or -1."""
        z = self._zoom
        margin = 10
        for i, e in enumerate(self._overlays):
            if e.get("type") != "note":
                continue
            pt = e["point"]
            px, py = int(pt.x * z), int(pt.y * z)
            hit_r = QRect(px - margin, py - _NOTE_ICON_SIZE - margin,
                          _NOTE_ICON_SIZE + margin * 2, _NOTE_ICON_SIZE + margin * 2)
            if hit_r.contains(pos):
                return i
        return -1

    def _annot_note_at(self, pos: QPoint):
        """Check if there's a text annotation in the fitz doc at this position.
        Returns (index_in_overlays, annot_text) or (-1, None)."""
        if not self._doc:
            return -1, None
        import fitz
        pdf_pt = self._to_pdf(pos.x(), pos.y())
        page = self._doc[self._page_idx]
        for annot in page.annots() or []:
            if annot.type[0] == fitz.PDF_ANNOT_TEXT:
                # Expand the annot rect for easier clicking
                expanded = annot.rect + fitz.Rect(-10, -10, 10, 10)
                if expanded.contains(pdf_pt):
                    # Find matching overlay
                    txt = annot.info.get("content", "") or annot.get_text() or ""
                    for i, e in enumerate(self._overlays):
                        if e.get("type") == "note" and e.get("text", "").strip() == txt.strip():
                            return i, txt.strip()
                    # No matching overlay found — create a temporary one
                    if txt.strip():
                        pt = fitz.Point(annot.rect.x0, annot.rect.y0 + annot.rect.height)
                        self._overlays.append({
                            "type": "note", "page": self._page_idx,
                            "point": pt, "text": txt.strip(),
                            "_existing": True,
                        })
                        return len(self._overlays) - 1, txt.strip()
        return -1, None

    def contextMenuEvent(self, e):
        """Right-click context menu to delete note annotations."""
        pos = e.pos()
        hit = self._note_icon_at(pos)
        if hit < 0:
            hit, _ = self._annot_note_at(pos)
        if hit >= 0:
            from PySide6.QtWidgets import QMenu
            menu = QMenu(self)
            delete_action = menu.addAction(t("viewer.delete_comment"))
            action = menu.exec(e.globalPos())
            if action == delete_action:
                overlay = self._overlays[hit]
                # Remove from fitz doc if it's an existing annotation
                if self._doc and overlay.get("_existing"):
                    import fitz
                    page = self._doc[overlay.get("page", self._page_idx)]
                    for annot in page.annots() or []:
                        if annot.type[0] == fitz.PDF_ANNOT_TEXT:
                            txt = annot.info.get("content", "") or ""
                            if txt.strip() == overlay.get("text", "").strip():
                                page.delete_annot(annot)
                                break
                # Remove from overlays
                self._overlays.pop(hit)
                # Notify parent (TabEditar) to remove from pending edits
                if hasattr(self, "note_deleted"):
                    self.note_deleted.emit(overlay)
                if self._open_note == hit:
                    self._open_note = None
                elif self._open_note is not None and self._open_note > hit:
                    self._open_note -= 1
                self.update()
            return
        super().contextMenuEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton: return
        pos = e.position().toPoint()
        if self._drag_rect and self._drag_rect.width() > 3 and self._drag_rect.height() > 3:
            self.rect_selected.emit(self._rect_to_pdf(self._drag_rect))
        else:
            # check if a note overlay icon was clicked
            hit = self._note_icon_at(pos)
            if hit < 0:
                # fallback: check fitz annotations directly
                hit, _ = self._annot_note_at(pos)
            if hit >= 0:
                self._open_note = None if self._open_note == hit else hit
                self.update()
                self._drag_start = None; self._drag_rect = None
                return
            # close any open balloon when clicking elsewhere
            if self._open_note is not None:
                self._open_note = None
                self.update()
            self.point_clicked.emit(self._to_pdf(pos.x(), pos.y()))
        self._drag_start = None; self._drag_rect = None
        self.update()
