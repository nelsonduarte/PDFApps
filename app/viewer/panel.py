"""PDFApps – PdfViewerPanel: PDF viewer with drag & drop and text selection."""

import os

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QFileDialog, QMessageBox, QDialog,
    QLineEdit,
)
from PySide6.QtGui import QKeySequence, QShortcut
import qtawesome as qta

from app.constants import ACCENT, TEXT_SEC, _LQ
from app.utils import _paint_bg
from app.viewer.canvas import _SelectCanvas


class PdfViewerPanel(QWidget):
    """PDF viewer with drag & drop, native text selection and navigation."""

    def __init__(self):
        super().__init__()
        self.setObjectName("viewer_panel")
        self.setMinimumWidth(260)
        self.setAcceptDrops(True)
        self._current_path = ""
        self._fitz_doc     = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────────
        hdr = QWidget(); hdr.setObjectName("viewer_header")
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(12, 8, 8, 8)
        hdr_lay.setSpacing(6)

        self._name_lbl = QLabel("PDF Viewer")
        self._name_lbl.setObjectName("viewer_title")
        hdr_lay.addWidget(self._name_lbl, 1)

        def _nav_btn(icon_name):
            b = QPushButton()
            b.setIcon(qta.icon(icon_name, color=TEXT_SEC))
            b.setObjectName("viewer_nav_btn")
            b.setFixedSize(28, 28)
            b.setEnabled(False)
            return b

        self._open_btn     = _nav_btn('fa5s.folder-open')
        self._open_btn.setEnabled(True)
        self._open_btn.setToolTip("Open PDF")
        self._open_btn.clicked.connect(self._open_dialog)

        self._zoom_out_btn = _nav_btn('fa5s.search-minus')
        self._zoom_out_btn.setToolTip("Zoom out (Ctrl+Scroll)")
        self._zoom_out_btn.clicked.connect(lambda: self._canvas.zoom_out())

        self._zoom_lbl = QLabel("Fit")
        self._zoom_lbl.setObjectName("viewer_page_lbl")
        self._zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_lbl.setMinimumWidth(52)

        self._zoom_in_btn  = _nav_btn('fa5s.search-plus')
        self._zoom_in_btn.setToolTip("Zoom in (Ctrl+Scroll)")
        self._zoom_in_btn.clicked.connect(lambda: self._canvas.zoom_in())

        self._fit_btn      = _nav_btn('fa5s.compress-arrows-alt')
        self._fit_btn.setToolTip("Fit to window")
        self._fit_btn.clicked.connect(self._zoom_fit)

        self._prev_btn     = _nav_btn('fa5s.chevron-left')
        self._prev_btn.clicked.connect(self._prev_page)

        self._page_lbl = QLabel("— / —")
        self._page_lbl.setObjectName("viewer_page_lbl")
        self._page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._next_btn     = _nav_btn('fa5s.chevron-right')
        self._next_btn.clicked.connect(self._next_page)

        for w in (self._open_btn, self._zoom_out_btn, self._zoom_lbl,
                  self._zoom_in_btn, self._fit_btn,
                  self._prev_btn, self._page_lbl, self._next_btn):
            hdr_lay.addWidget(w)
        self._hdr = hdr
        self._hdr.setVisible(False)
        layout.addWidget(hdr)

        # ── Placeholder ─────────────────────────────────────────────────────
        ph_widget = QWidget(); ph_widget.setObjectName("viewer_ph_widget")
        ph_lay = QVBoxLayout(ph_widget)
        ph_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_lay.setSpacing(14)
        ph_icon = QLabel()
        from PySide6.QtGui import QPixmap as _QPixmap
        from app.utils import resource_path as _rp
        _ph_pix = _QPixmap(_rp("icon.ico")).scaled(
            56, 56, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        if _ph_pix.isNull():
            _ph_pix = qta.icon('fa5s.file-pdf', color='#2E3A55').pixmap(56, 56)
        ph_icon.setPixmap(_ph_pix)
        ph_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_text = QLabel("Drag a PDF here\nor use the button  to open")
        ph_text.setObjectName("viewer_placeholder")
        ph_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ph_btn = QPushButton("  Open PDF")
        self._ph_btn.setIcon(qta.icon('fa5s.folder-open', color='#FFFFFF'))
        self._ph_btn.setObjectName("btn_primary")
        self._ph_btn.setFixedWidth(160)
        self._ph_btn.clicked.connect(self._open_dialog)
        ph_lay.addWidget(ph_icon); ph_lay.addWidget(ph_text)
        ph_lay.addWidget(self._ph_btn, 0, Qt.AlignmentFlag.AlignCenter)
        self._placeholder = ph_widget
        layout.addWidget(self._placeholder, 1)

        # ── Canvas with continuous scroll of all pages ──────────────────
        self._canvas = _SelectCanvas()
        self._canvas.zoom_changed.connect(self._on_zoom_changed)
        self._canvas_scroll = QScrollArea()
        self._canvas_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._canvas_scroll.setWidgetResizable(False)
        self._canvas_scroll.setWidget(self._canvas)
        self._canvas_scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._canvas_scroll.setVisible(False)
        self._canvas_scroll.viewport().installEventFilter(self)
        self._canvas_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
        layout.addWidget(self._canvas_scroll, 1)

        # ── Search bar (Ctrl+F) ───────────────────────────────────────────
        self._search_bar = QWidget()
        self._search_bar.setObjectName("search_bar")
        sb_lay = QHBoxLayout(self._search_bar)
        sb_lay.setContentsMargins(8, 4, 8, 4)
        sb_lay.setSpacing(4)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search in PDF...")
        self._search_input.setObjectName("search_input")
        self._search_input.returnPressed.connect(self._search_next)
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._search_lbl = QLabel("")
        self._search_lbl.setMinimumWidth(60)
        self._search_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _prev_s = QPushButton()
        _prev_s.setIcon(qta.icon("fa5s.chevron-up", color=TEXT_SEC))
        _prev_s.setFixedSize(28, 28); _prev_s.setObjectName("viewer_nav_btn")
        _prev_s.setToolTip("Previous match")
        _prev_s.clicked.connect(self._search_prev)
        _next_s = QPushButton()
        _next_s.setIcon(qta.icon("fa5s.chevron-down", color=TEXT_SEC))
        _next_s.setFixedSize(28, 28); _next_s.setObjectName("viewer_nav_btn")
        _next_s.setToolTip("Next match")
        _next_s.clicked.connect(self._search_next)
        _close_s = QPushButton()
        _close_s.setIcon(qta.icon("fa5s.times", color=TEXT_SEC))
        _close_s.setFixedSize(28, 28); _close_s.setObjectName("viewer_nav_btn")
        _close_s.setToolTip("Close search (Esc)")
        _close_s.clicked.connect(self._close_search)
        sb_lay.addWidget(self._search_input, 1)
        sb_lay.addWidget(self._search_lbl)
        sb_lay.addWidget(_prev_s); sb_lay.addWidget(_next_s); sb_lay.addWidget(_close_s)
        self._search_bar.setVisible(False)
        layout.addWidget(self._search_bar)
        self._search_results: list[tuple[int, list]] = []  # [(page_idx, [fitz_rects]), ...]
        self._search_current = -1

        # Shortcuts
        QShortcut(QKeySequence("Ctrl+F"), self, self._toggle_search)
        QShortcut(QKeySequence("Escape"), self._search_input, self._close_search)

        # ── Status bar (text selection) ──────────────────────────────────
        self._sel_status = QLabel("Drag over text to select and copy")
        self._sel_status.setObjectName("viewer_sel_status")
        self._sel_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sel_status.setVisible(False)
        layout.addWidget(self._sel_status)
        self._canvas.text_copied.connect(self._on_text_copied)

    def _on_zoom_changed(self, pct: int):
        self._zoom_lbl.setText(f"{pct}%")
        self._update_page_label()

    def _on_scroll(self, val: int):
        self._canvas.on_scroll()
        self._update_page_label()

    def _on_text_copied(self, text: str):
        from PySide6.QtCore import QTimer
        if text:
            self._sel_status.setText(f"Copied to clipboard  ({len(text)} chars)")
            self._sel_status.setStyleSheet("color: #22c55e; padding: 4px;")
        else:
            self._sel_status.setText("No text found (scanned PDF or no text layer)")
            self._sel_status.setStyleSheet("color: #f59e0b; padding: 4px;")
        QTimer.singleShot(4000, lambda: (
            self._sel_status.setText("Drag over text to select and copy"),
            self._sel_status.setStyleSheet(""),
        ))

    def paintEvent(self, event):
        _paint_bg(self)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QTimer
        if obj is self._canvas_scroll.viewport():
            if event.type() == QEvent.Type.Wheel:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    if event.angleDelta().y() > 0:
                        self._canvas.zoom_in()
                    else:
                        self._canvas.zoom_out()
                    return True
            elif event.type() == QEvent.Type.Resize:
                if self._canvas._doc and self._canvas._zoom_factor == 1.0:
                    QTimer.singleShot(0, self._canvas._layout_and_schedule)
        return super().eventFilter(obj, event)

    def update_theme(self, dark: bool) -> None:
        c = TEXT_SEC if dark else _LQ
        self._open_btn.setIcon(qta.icon('fa5s.folder-open',          color=c))
        self._prev_btn.setIcon(qta.icon('fa5s.chevron-left',          color=c))
        self._next_btn.setIcon(qta.icon('fa5s.chevron-right',         color=c))
        self._zoom_out_btn.setIcon(qta.icon('fa5s.search-minus',      color=c))
        self._zoom_in_btn.setIcon(qta.icon('fa5s.search-plus',        color=c))
        self._fit_btn.setIcon(qta.icon('fa5s.compress-arrows-alt',    color=c))

    # ── Drag & drop ──────────────────────────────────────────────────────────
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            urls = e.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith(".pdf"):
                e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        self.load(e.mimeData().urls()[0].toLocalFile())

    # ── Open dialog ────────────────────────────────────────────────────────
    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window(), "Open PDF", "", "PDF Files (*.pdf);;All (*.*)")
        if path:
            self.load(path)

    # ── API ──────────────────────────────────────────────────────────────────
    def current_path(self) -> str:
        return self._current_path

    def load(self, path: str):
        if not path or not os.path.isfile(path):
            return
        if not path.lower().endswith(".pdf"):
            QMessageBox.warning(self, "Invalid format",
                                "Please select a PDF file (.pdf).")
            return
        import fitz
        if self._fitz_doc:
            self._fitz_doc.close()
            self._fitz_doc = None
        try:
            doc = fitz.open(path)
        except Exception as ex:
            QMessageBox.critical(self, "Error opening PDF",
                                 f"Could not open the file:\n{ex}")
            return
        self._pdf_password = ""
        if doc.needs_pass:
            from app.editor.dialogs import _PdfPasswordDialog
            wrong = False
            while True:
                dlg = _PdfPasswordDialog(os.path.basename(path), wrong=wrong, parent=self)
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    doc.close(); return
                if doc.authenticate(dlg.password()):
                    self._pdf_password = dlg.password()
                    break
                wrong = True
        self._current_path = path
        self._fitz_doc     = doc
        self._canvas.load(doc, 0, path=path, password=getattr(self, "_pdf_password", ""))
        self._canvas_scroll.verticalScrollBar().setValue(0)
        self._placeholder.setVisible(False)
        self._canvas_scroll.setVisible(True)
        self._sel_status.setVisible(True)
        self._name_lbl.setText(os.path.basename(path))
        self._zoom_lbl.setText("Fit")
        for btn in (self._zoom_out_btn, self._zoom_in_btn, self._fit_btn):
            btn.setEnabled(True)

    # ── Search ──────────────────────────────────────────────────────────
    def _toggle_search(self):
        if self._search_bar.isVisible():
            self._close_search()
        else:
            self._search_bar.setVisible(True)
            self._search_input.setFocus()
            self._search_input.selectAll()

    def _close_search(self):
        self._search_bar.setVisible(False)
        self._search_results.clear()
        self._search_current = -1
        self._search_lbl.setText("")
        self._canvas.set_search_highlights([])
        self._canvas.update()

    def _on_search_text_changed(self, text: str):
        if not text.strip():
            self._search_results.clear()
            self._search_current = -1
            self._search_lbl.setText("")
            self._canvas.set_search_highlights([])
            self._canvas.update()
            return
        self._do_search(text.strip())

    def _do_search(self, query: str):
        if not self._fitz_doc:
            return
        results = []
        for page_idx in range(self._fitz_doc.page_count):
            page = self._fitz_doc[page_idx]
            rects = page.search_for(query)
            if rects:
                results.append((page_idx, rects))
        self._search_results = results
        total = sum(len(rects) for _, rects in results)
        if total == 0:
            self._search_lbl.setText("0 / 0")
            self._search_current = -1
            self._canvas.set_search_highlights([])
            self._canvas.update()
            return
        self._search_current = 0
        self._update_search_highlight()

    def _search_next(self):
        if not self._search_results:
            text = self._search_input.text().strip()
            if text:
                self._do_search(text)
            return
        total = sum(len(rects) for _, rects in self._search_results)
        if total == 0:
            return
        self._search_current = (self._search_current + 1) % total
        self._update_search_highlight()

    def _search_prev(self):
        if not self._search_results:
            return
        total = sum(len(rects) for _, rects in self._search_results)
        if total == 0:
            return
        self._search_current = (self._search_current - 1) % total
        self._update_search_highlight()

    def _update_search_highlight(self):
        total = sum(len(rects) for _, rects in self._search_results)
        self._search_lbl.setText(f"{self._search_current + 1} / {total}")
        # Build highlight list for canvas: [(page_idx, fitz_rect), ...]
        all_highlights = []
        flat_idx = 0
        current_page = 0
        current_rect_idx = 0
        for page_idx, rects in self._search_results:
            for rect in rects:
                all_highlights.append((page_idx, rect))
                if flat_idx == self._search_current:
                    current_page = page_idx
                    current_rect_idx = flat_idx
                flat_idx += 1
        self._canvas.set_search_highlights(all_highlights, self._search_current)
        # Scroll to current match
        if current_page < len(self._canvas._entries):
            entry = self._canvas._entries[current_page]
            # Get the rect of current match
            _, cur_rect = all_highlights[self._search_current]
            z = self._canvas._zoom
            y_target = entry.y_off + int(cur_rect.y0 * z) - 100
            self._canvas_scroll.verticalScrollBar().setValue(max(0, y_target))
        self._canvas.update()

    # ── Navigation ────────────────────────────────────────────────────────
    def _update_page_label(self):
        pages = self._canvas._entries
        if not pages:
            self._page_lbl.setText("— / —")
            self._prev_btn.setEnabled(False)
            self._next_btn.setEnabled(False)
            return
        sb_val = self._canvas_scroll.verticalScrollBar().value()
        idx = self._canvas.page_at_y(sb_val)
        total = len(pages)
        self._page_lbl.setText(f"{idx + 1} / {total}")
        self._prev_btn.setEnabled(idx > 0)
        self._next_btn.setEnabled(idx < total - 1)

    def _prev_page(self):
        if not self._canvas._entries:
            return
        sb = self._canvas_scroll.verticalScrollBar()
        idx = self._canvas.page_at_y(sb.value())
        if idx > 0:
            sb.setValue(self._canvas.scroll_to_page(idx - 1))

    def _next_page(self):
        if not self._canvas._entries:
            return
        sb = self._canvas_scroll.verticalScrollBar()
        idx = self._canvas.page_at_y(sb.value())
        if idx < len(self._canvas._entries) - 1:
            sb.setValue(self._canvas.scroll_to_page(idx + 1))

    # ── Zoom ─────────────────────────────────────────────────────────────────
    def _zoom_fit(self):
        self._canvas.zoom_reset()
        self._zoom_lbl.setText("Fit")
