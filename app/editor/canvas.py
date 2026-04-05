"""PDFApps – PdfEditCanvas: continuous-scroll visual PDF edit canvas."""

from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtWidgets import QWidget, QSizePolicy

from app.constants import ACCENT, BG_INNER, TEXT_SEC
from app.i18n import t

_NOTE_ICON_SIZE = 22
_PAGE_GAP = 4


class PdfEditCanvas(QWidget):
    rect_selected = Signal(int, object)   # (page_idx, fitz.Rect)
    point_clicked = Signal(int, object)   # (page_idx, fitz.Point)
    note_deleted  = Signal(dict)
    zoom_changed  = Signal(int)

    def __init__(self):
        super().__init__()
        self._doc         = None
        self._page_idx    = 0   # kept for compatibility (current page indicator)
        self._zoom        = 1.0
        self._zoom_factor = 1.0
        self._base_avail  = 300
        self._page_pixmaps = []   # list of QPixmap, one per page
        self._page_offsets = []   # list of (y_offset, width, height) per page
        self._drag_start  = None
        self._drag_rect   = None
        self._overlays    = []    # ALL overlays (all pages)
        self._select_mode = False
        self._open_note   = None
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
        """Scroll to page (called by tab navigation arrows)."""
        if self._doc and 0 <= idx < self._doc.page_count:
            self._page_idx = idx

    def scroll_to_page(self, idx: int) -> int:
        """Return Y offset for a given page index."""
        if 0 <= idx < len(self._page_offsets):
            return self._page_offsets[idx][0]
        return 0

    def page_at_y(self, y: int) -> int:
        """Return which page index is at scroll position y."""
        for i, (yo, w, h) in enumerate(self._page_offsets):
            if y < yo + h + _PAGE_GAP:
                return i
        return max(0, len(self._page_offsets) - 1)

    def get_span_at(self, page_idx, pdf_pt):
        """Returns the closest fitz span to pdf_pt on the given page."""
        if not self._doc: return None
        import fitz
        page = self._doc[page_idx]
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
        if self._doc: self._doc.close(); self._doc = None

    def close_doc(self):
        self.release_doc()
        self._page_pixmaps.clear()
        self._page_offsets.clear()
        self._overlays = []; self._open_note = None
        self.setMinimumSize(300, 400)
        self.setMaximumSize(16777215, 16777215)
        self.update()

    def _render(self):
        if not self._doc: return
        import fitz
        from PySide6.QtGui import QPixmap as QP

        # Determine available width
        if self._zoom_factor == 1.0:
            from PySide6.QtWidgets import QScrollArea as _SA
            vp = self.parent()
            sa = vp.parent() if vp else None
            avail = sa.viewport().width() - 4 if isinstance(sa, _SA) else self.width()
            self._base_avail = max(avail, 300)

        dpr = self.devicePixelRatioF() or 1.0
        self._page_pixmaps.clear()
        self._page_offsets.clear()

        y_off = 0
        max_w = 0
        for i in range(self._doc.page_count):
            page = self._doc[i]
            self._zoom = (self._base_avail / page.rect.width) * self._zoom_factor
            rz = self._zoom * dpr
            pix = page.get_pixmap(matrix=fitz.Matrix(rz, rz), annots=False)
            qp = QP(); qp.loadFromData(pix.tobytes("png"))
            qp.setDevicePixelRatio(dpr)
            pw = round(qp.width() / dpr)
            ph = round(qp.height() / dpr)
            self._page_pixmaps.append(qp)
            self._page_offsets.append((y_off, pw, ph))
            max_w = max(max_w, pw)
            y_off += ph + _PAGE_GAP

        # Store zoom for coordinate conversion (use last page's zoom — all should be same if same width)
        if self._doc.page_count > 0:
            self._zoom = (self._base_avail / self._doc[0].rect.width) * self._zoom_factor

        total_h = y_off - _PAGE_GAP if y_off > 0 else 400
        self.setFixedSize(max(max_w, 300), max(total_h, 400))
        self.zoom_changed.emit(round(self._zoom_factor * 100))
        self.update()

    def _page_and_local(self, sx, sy):
        """Convert screen coords to (page_index, local_x, local_y)."""
        for i, (yo, w, h) in enumerate(self._page_offsets):
            if sy < yo + h + _PAGE_GAP // 2 or i == len(self._page_offsets) - 1:
                return i, sx, sy - yo
        return 0, sx, sy

    def _to_pdf(self, page_idx, sx, sy):
        import fitz
        return fitz.Point(sx / self._zoom, sy / self._zoom)

    def _rect_to_pdf(self, page_idx, local_rect):
        import fitz
        z = self._zoom
        return fitz.Rect(local_rect.left()/z, local_rect.top()/z,
                         local_rect.right()/z, local_rect.bottom()/z)

    def paintEvent(self, _):
        from PySide6.QtGui import QPainter, QColor, QPen, QFont
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG_INNER))

        if not self._page_pixmaps:
            p.setPen(QColor(TEXT_SEC))
            f = QFont(); f.setPointSize(11); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, t("edit.open_prompt"))
            p.end()
            return

        # Draw pages
        for i, qpix in enumerate(self._page_pixmaps):
            yo, pw, ph = self._page_offsets[i]
            p.drawPixmap(0, yo, qpix)

        # Draw overlays
        z = self._zoom
        for e in self._overlays:
            pg = e.get("page", 0)
            if pg >= len(self._page_offsets):
                continue
            yo = self._page_offsets[pg][0]
            etype = e["type"]

            if etype == "redact":
                r = e["rect"]; fill = e["fill"]
                qr = QRect(int(r.x0*z), yo+int(r.y0*z), max(1,int(r.width*z)), max(1,int(r.height*z)))
                p.fillRect(qr, QColor(int(fill[0]*255), int(fill[1]*255), int(fill[2]*255), 210))
                p.setPen(QPen(QColor("#EF4444"), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(qr)
            elif etype == "highlight":
                r = e["rect"]; c = e["color"]
                qr = QRect(int(r.x0*z), yo+int(r.y0*z), max(1,int(r.width*z)), max(1,int(r.height*z)))
                p.fillRect(qr, QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255), 120))
            elif etype == "text":
                pt = e["point"]; c = e["color"]
                p.setPen(QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255)))
                f2 = QFont(); f2.setPointSize(max(4, int(e["size"] * z * 0.75))); p.setFont(f2)
                p.drawText(int(pt.x*z), yo+int(pt.y*z), e["text"])
            elif etype in ("image", "signature"):
                r = e["rect"]
                qr = QRect(int(r.x0*z), yo+int(r.y0*z), max(1,int(r.width*z)), max(1,int(r.height*z)))
                from PySide6.QtGui import QPixmap as _QPixmap
                img_px = _QPixmap(e["path"])
                if not img_px.isNull():
                    p.drawPixmap(qr, img_px)
                border = "#22C55E" if etype == "signature" else ACCENT
                p.setPen(QPen(QColor(border), 2, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(qr)
            elif etype == "note":
                pt = e["point"]
                px, py = int(pt.x*z), yo+int(pt.y*z)
                note_idx = self._overlays.index(e) if e in self._overlays else -1
                icon_r = QRect(px, py - _NOTE_ICON_SIZE, _NOTE_ICON_SIZE, _NOTE_ICON_SIZE)
                p.setBrush(QColor("#FBBF24")); p.setPen(QPen(QColor("#D97706"), 1))
                p.drawRoundedRect(icon_r, 4, 4)
                fi = QFont(); fi.setPointSize(10); fi.setBold(True); p.setFont(fi)
                p.setPen(QColor("#1C1917")); p.drawText(icon_r, Qt.AlignmentFlag.AlignCenter, "\u270e")
                if self._open_note == note_idx:
                    bx = px + _NOTE_ICON_SIZE + 6
                    by = py - _NOTE_ICON_SIZE - 4
                    ft = QFont(); ft.setPointSize(9); p.setFont(ft)
                    fm = p.fontMetrics()
                    lines = e["text"].split("\n")
                    tw = max(fm.horizontalAdvance(ln) for ln in lines) + 20
                    th = fm.height() * len(lines) + 16
                    bw, bh = max(120, min(tw, 260)), max(32, th)
                    br = QRect(bx, by, bw, bh)
                    p.setBrush(QColor(0,0,0,30)); p.setPen(Qt.PenStyle.NoPen)
                    p.drawRoundedRect(QRect(bx+2, by+2, bw, bh), 6, 6)
                    p.setBrush(QColor("#FFFDF5")); p.setPen(QPen(QColor("#D97706"), 1))
                    p.drawRoundedRect(br, 6, 6)
                    p.setPen(QColor("#000000"))
                    p.drawText(QRect(bx+10, by+8, bw-20, bh-16),
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                               e["text"])
            elif etype == "text_edit":
                r = e["bbox"]
                qr = QRect(int(r[0]*z), yo+int(r[1]*z),
                           max(1, int((r[2]-r[0])*z)), max(1, int((r[3]-r[1])*z)))
                p.fillRect(qr, QColor(239, 68, 68, 60))
                p.setPen(QPen(QColor("#EF4444"), 1, Qt.PenStyle.DashLine))
                p.drawRect(qr)
                mid_y = qr.top() + qr.height() // 2
                p.setPen(QPen(QColor("#EF4444"), 1)); p.drawLine(qr.left(), mid_y, qr.right(), mid_y)
                new_txt = e.get("new_text", "")
                if new_txt:
                    p.setPen(QColor("#22C55E"))
                    fn = QFont(); fn.setPointSize(max(4, int(e["size"] * z * 0.75))); p.setFont(fn)
                    p.drawText(int(r[0]*z), yo+int(r[3]*z) + max(10, int(e["size"]*z*0.85)), new_txt)

        # Drag rect
        if self._drag_rect:
            if self._select_mode:
                p.setPen(QPen(QColor("#3B82F6"), 2, Qt.PenStyle.SolidLine))
                p.setBrush(QColor(59, 130, 246, 50))
            else:
                p.setPen(QPen(QColor("#EF4444"), 2, Qt.PenStyle.DashLine))
                p.setBrush(QColor(239, 68, 68, 50))
            p.drawRect(self._drag_rect)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = e.position().toPoint()
            self._drag_rect = None

    def mouseMoveEvent(self, e):
        if self._drag_start and (e.buttons() & Qt.MouseButton.LeftButton):
            self._drag_rect = QRect(self._drag_start, e.position().toPoint()).normalized()
            self.update()

    def _note_icon_at(self, pos: QPoint) -> int:
        z = self._zoom
        margin = 10
        for i, e in enumerate(self._overlays):
            if e.get("type") != "note": continue
            pg = e.get("page", 0)
            if pg >= len(self._page_offsets): continue
            yo = self._page_offsets[pg][0]
            pt = e["point"]
            px, py = int(pt.x * z), yo + int(pt.y * z)
            hit_r = QRect(px - margin, py - _NOTE_ICON_SIZE - margin,
                          _NOTE_ICON_SIZE + margin * 2, _NOTE_ICON_SIZE + margin * 2)
            if hit_r.contains(pos):
                return i
        return -1

    def _annot_note_at(self, pos: QPoint):
        if not self._doc:
            return -1, None
        import fitz
        page_idx, lx, ly = self._page_and_local(pos.x(), pos.y())
        pdf_pt = self._to_pdf(page_idx, lx, ly)
        page = self._doc[page_idx]
        for annot in page.annots() or []:
            if annot.type[0] == fitz.PDF_ANNOT_TEXT:
                expanded = annot.rect + fitz.Rect(-10, -10, 10, 10)
                if expanded.contains(pdf_pt):
                    txt = annot.info.get("content", "") or annot.get_text() or ""
                    for i, e in enumerate(self._overlays):
                        if e.get("type") == "note" and e.get("text", "").strip() == txt.strip():
                            return i, txt.strip()
                    if txt.strip():
                        pt = fitz.Point(annot.rect.x0, annot.rect.y0 + annot.rect.height)
                        self._overlays.append({
                            "type": "note", "page": page_idx,
                            "point": pt, "text": txt.strip(),
                            "_existing": True,
                        })
                        return len(self._overlays) - 1, txt.strip()
        return -1, None

    def contextMenuEvent(self, e):
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
                if self._doc and overlay.get("_existing"):
                    import fitz
                    page = self._doc[overlay.get("page", 0)]
                    for annot in page.annots() or []:
                        if annot.type[0] == fitz.PDF_ANNOT_TEXT:
                            txt = annot.info.get("content", "") or ""
                            if txt.strip() == overlay.get("text", "").strip():
                                page.delete_annot(annot)
                                break
                self._overlays.pop(hit)
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
            # Convert drag rect to page-local PDF coords
            page_idx, lx, ly = self._page_and_local(
                self._drag_rect.left(), self._drag_rect.top())
            yo = self._page_offsets[page_idx][0] if page_idx < len(self._page_offsets) else 0
            local_rect = QRect(self._drag_rect.left(), self._drag_rect.top() - yo,
                               self._drag_rect.width(), self._drag_rect.height())
            self._page_idx = page_idx
            self.rect_selected.emit(page_idx, self._rect_to_pdf(page_idx, local_rect))
        else:
            hit = self._note_icon_at(pos)
            if hit < 0:
                hit, _ = self._annot_note_at(pos)
            if hit >= 0:
                self._open_note = None if self._open_note == hit else hit
                self.update()
                self._drag_start = None; self._drag_rect = None
                return
            if self._open_note is not None:
                self._open_note = None
                self.update()
            page_idx, lx, ly = self._page_and_local(pos.x(), pos.y())
            self._page_idx = page_idx
            self.point_clicked.emit(page_idx, self._to_pdf(page_idx, lx, ly))
        self._drag_start = None; self._drag_rect = None
        self.update()
