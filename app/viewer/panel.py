"""PDFApps – PdfViewerPanel: PDF viewer with drag & drop and text selection."""

import os

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QFileDialog, QMessageBox, QDialog,
    QLineEdit, QSplitter, QTreeWidget, QTreeWidgetItem,
)
from PySide6.QtGui import QKeySequence, QShortcut
import qtawesome as qta

from app.constants import ACCENT, TEXT_SEC, _LQ, DESKTOP
from app.utils import _paint_bg
from app.i18n import t
from app.viewer.canvas import _SelectCanvas


class PdfViewerPanel(QWidget):
    """PDF viewer with drag & drop, native text selection and navigation."""

    def __init__(self):
        super().__init__()
        self.setObjectName("viewer_panel")
        self.setMinimumWidth(260)
        self.setAcceptDrops(False)
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

        self._name_lbl = QLabel(t("viewer.title"))
        self._name_lbl.setObjectName("viewer_title")
        hdr_lay.addWidget(self._name_lbl, 1)

        def _nav_btn(icon_name):
            b = QPushButton()
            b.setIcon(qta.icon(icon_name, color=TEXT_SEC))
            b.setObjectName("viewer_nav_btn")
            b.setFixedSize(28, 28)
            b.setEnabled(False)
            return b

        def _a11y(btn, tip):
            btn.setToolTip(tip); btn.setAccessibleName(tip)

        self._open_btn     = _nav_btn('fa5s.folder-open')
        self._open_btn.setEnabled(True)
        _a11y(self._open_btn, t("btn.open_pdf"))
        self._open_btn.clicked.connect(self._open_dialog)

        self._toc_btn      = _nav_btn('fa5s.bookmark')
        _a11y(self._toc_btn, t("viewer.toc"))
        self._toc_btn.clicked.connect(self._toggle_toc)
        self._toc_btn.setVisible(False)  # only visible when PDF has TOC

        self._night_btn    = _nav_btn('fa5s.moon')
        _a11y(self._night_btn, t("viewer.night_mode"))
        self._night_btn.setCheckable(True)
        self._night_btn.clicked.connect(self._toggle_night_mode)

        self._zoom_out_btn = _nav_btn('fa5s.search-minus')
        _a11y(self._zoom_out_btn, t("zoom.out"))
        self._zoom_out_btn.clicked.connect(lambda: self._canvas.zoom_out())

        self._zoom_lbl = QLabel(t("zoom.fit"))
        self._zoom_lbl.setObjectName("viewer_page_lbl")
        self._zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_lbl.setMinimumWidth(52)

        self._zoom_in_btn  = _nav_btn('fa5s.search-plus')
        _a11y(self._zoom_in_btn, t("zoom.in"))
        self._zoom_in_btn.clicked.connect(lambda: self._canvas.zoom_in())

        self._fit_btn      = _nav_btn('fa5s.compress-arrows-alt')
        _a11y(self._fit_btn, t("zoom.fit_tip"))
        self._fit_btn.clicked.connect(self._zoom_fit)

        self._prev_btn     = _nav_btn('fa5s.chevron-left')
        _a11y(self._prev_btn, t("nav.prev_page"))
        self._prev_btn.clicked.connect(self._prev_page)

        self._page_lbl = QLabel("— / —")
        self._page_lbl.setObjectName("viewer_page_lbl")
        self._page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._next_btn     = _nav_btn('fa5s.chevron-right')
        _a11y(self._next_btn, t("nav.next_page"))
        self._next_btn.clicked.connect(self._next_page)

        self._print_btn    = _nav_btn('fa5s.print')
        _a11y(self._print_btn, t("viewer.print"))
        self._print_btn.clicked.connect(self._print_pdf)

        for w in (self._open_btn, self._toc_btn, self._zoom_out_btn, self._zoom_lbl,
                  self._zoom_in_btn, self._fit_btn,
                  self._prev_btn, self._page_lbl, self._next_btn,
                  self._night_btn, self._print_btn):
            hdr_lay.addWidget(w)
        self._hdr = hdr
        self._hdr.setVisible(False)
        layout.addWidget(hdr)

        # ── Placeholder ─────────────────────────────────────────────────────
        ph_widget = QWidget(); ph_widget.setObjectName("viewer_ph_widget")
        ph_lay = QVBoxLayout(ph_widget)
        ph_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_lay.setSpacing(14)
        ph_drag = QLabel(t("viewer.drag_hint"))
        ph_drag.setObjectName("viewer_placeholder")
        ph_drag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ph_btn = QPushButton(t("viewer.open_btn"))
        self._ph_btn.setIcon(qta.icon('fa5s.folder-open', color='#FFFFFF'))
        self._ph_btn.setObjectName("btn_primary")
        self._ph_btn.setFixedWidth(160)
        self._ph_btn.clicked.connect(self._open_dialog)

        ph_lay.addWidget(self._ph_btn, 0, Qt.AlignmentFlag.AlignCenter)
        ph_lay.addWidget(ph_drag)

        # Recent files section
        from app.i18n import get_recent_files, add_recent_file
        self._recents_container = QWidget()
        self._recents_container.setMaximumWidth(400)
        self._recent_links: list[QPushButton] = []
        self._recent_del_btns: list[QPushButton] = []
        rc_lay = QVBoxLayout(self._recents_container)
        rc_lay.setContentsMargins(0, 16, 0, 0); rc_lay.setSpacing(4)
        recents = get_recent_files()
        if recents:
            rec_title = QLabel(t("viewer.recent"))
            rec_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rec_title.setStyleSheet("font-size: 10pt; font-weight: 600; opacity: 0.7;")
            rc_lay.addWidget(rec_title)
            for rp in recents[:5]:
                if not os.path.isfile(rp):
                    continue
                fname = os.path.basename(rp)
                row = QWidget()
                row_h = QHBoxLayout(row); row_h.setContentsMargins(0, 0, 0, 0); row_h.setSpacing(0)
                link = QPushButton(f"📄  {fname}")
                link.setObjectName("recent_link")
                link.setToolTip(rp)
                link.setCursor(Qt.CursorShape.PointingHandCursor)
                link.setFlat(True)
                link.setStyleSheet(self._recent_link_style(dark=True))
                link.clicked.connect(lambda checked, p=rp: self.load(p))
                self._recent_links.append(link)
                del_btn = QPushButton()
                del_btn.setIcon(qta.icon("fa5s.trash-alt", color=TEXT_SEC))
                del_btn.setFixedSize(28, 28)
                del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                del_btn.setFlat(True)
                del_btn.setToolTip(t("btn.remove"))
                del_btn.setAccessibleName(t("btn.remove"))
                del_btn.setStyleSheet(
                    f"QPushButton {{ border: 1px solid transparent; background: transparent; }}"
                    f"QPushButton:hover {{ background: rgba(239,68,68,0.15); border-radius: 4px; }}"
                    f"QPushButton:focus {{ border: 1px solid {ACCENT}; border-radius: 4px; }}")
                del_btn.clicked.connect(lambda checked, p=rp, r=row: self._remove_recent(p, r))
                self._recent_del_btns.append(del_btn)
                row_h.addWidget(link, 1)
                row_h.addWidget(del_btn)
                rc_lay.addWidget(row)
        ph_lay.addWidget(self._recents_container, 0, Qt.AlignmentFlag.AlignCenter)

        self._placeholder = ph_widget
        layout.addWidget(self._placeholder, 1)

        # ── TOC tree (left of canvas) ──────────────────────────────────
        self._toc_tree = QTreeWidget()
        self._toc_tree.setObjectName("toc_tree")
        self._toc_tree.setHeaderHidden(True)
        self._toc_tree.setMinimumWidth(180)
        self._toc_tree.itemClicked.connect(self._on_toc_clicked)

        # ── Canvas with continuous scroll of all pages ──────────────────
        self._canvas = _SelectCanvas()
        self._canvas.zoom_changed.connect(self._on_zoom_changed)
        self._canvas_scroll = QScrollArea()
        self._canvas_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._canvas_scroll.setWidgetResizable(False)
        self._canvas_scroll.setWidget(self._canvas)
        self._canvas_scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._canvas_scroll.viewport().installEventFilter(self)
        self._canvas_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # Splitter: TOC | canvas
        self._viewer_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._viewer_splitter.addWidget(self._toc_tree)
        self._viewer_splitter.addWidget(self._canvas_scroll)
        self._viewer_splitter.setStretchFactor(0, 0)
        self._viewer_splitter.setStretchFactor(1, 1)
        self._viewer_splitter.setSizes([220, 800])
        self._viewer_splitter.setCollapsible(0, True)
        self._viewer_splitter.setCollapsible(1, False)
        self._viewer_splitter.setVisible(False)
        self._toc_tree.setVisible(False)  # hidden until a PDF with TOC is loaded
        layout.addWidget(self._viewer_splitter, 1)

        # ── Search bar (Ctrl+F) ───────────────────────────────────────────
        self._search_bar = QWidget()
        self._search_bar.setObjectName("search_bar")
        sb_lay = QHBoxLayout(self._search_bar)
        sb_lay.setContentsMargins(8, 4, 8, 4)
        sb_lay.setSpacing(4)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(t("search.placeholder"))
        self._search_input.setObjectName("search_input")
        self._search_input.returnPressed.connect(self._search_next)
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._search_lbl = QLabel("")
        self._search_lbl.setMinimumWidth(60)
        self._search_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._search_prev_btn = QPushButton()
        self._search_prev_btn.setIcon(qta.icon("fa5s.chevron-up", color=TEXT_SEC))
        self._search_prev_btn.setFixedSize(28, 28); self._search_prev_btn.setObjectName("viewer_nav_btn")
        self._search_prev_btn.setToolTip(t("search.prev")); self._search_prev_btn.setAccessibleName(t("search.prev"))
        self._search_prev_btn.clicked.connect(self._search_prev)
        self._search_next_btn = QPushButton()
        self._search_next_btn.setIcon(qta.icon("fa5s.chevron-down", color=TEXT_SEC))
        self._search_next_btn.setFixedSize(28, 28); self._search_next_btn.setObjectName("viewer_nav_btn")
        self._search_next_btn.setToolTip(t("search.next")); self._search_next_btn.setAccessibleName(t("search.next"))
        self._search_next_btn.clicked.connect(self._search_next)
        self._search_close_btn = QPushButton()
        self._search_close_btn.setIcon(qta.icon("fa5s.times", color=TEXT_SEC))
        self._search_close_btn.setFixedSize(28, 28); self._search_close_btn.setObjectName("viewer_nav_btn")
        self._search_close_btn.setToolTip(t("search.close")); self._search_close_btn.setAccessibleName(t("search.close"))
        self._search_close_btn.clicked.connect(self._close_search)
        sb_lay.addWidget(self._search_input, 1)
        sb_lay.addWidget(self._search_lbl)
        sb_lay.addWidget(self._search_prev_btn); sb_lay.addWidget(self._search_next_btn); sb_lay.addWidget(self._search_close_btn)
        self._search_bar.setVisible(False)
        layout.addWidget(self._search_bar)
        self._search_results: list[tuple[int, list]] = []  # [(page_idx, [fitz_rects]), ...]
        self._search_current = -1

        # Shortcuts
        QShortcut(QKeySequence("Ctrl+F"), self, self._toggle_search)
        QShortcut(QKeySequence("Escape"), self._search_input, self._close_search)

        # ── Status bar (text selection) ──────────────────────────────────
        self._sel_status = QLabel(t("viewer.select_copy"))
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
            self._sel_status.setText(t("viewer.copied", n=len(text)))
            self._sel_status.setStyleSheet("color: #0D9488; padding: 4px;")
        else:
            self._sel_status.setText(t("viewer.no_text"))
            self._sel_status.setStyleSheet("color: #D97706; padding: 4px;")
        QTimer.singleShot(4000, lambda: (
            self._sel_status.setText(t("viewer.select_copy")),
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

    @staticmethod
    def _recent_link_style(dark: bool) -> str:
        hover_bg = "rgba(255,255,255,0.05)" if dark else "rgba(0,0,0,0.05)"
        focus_border = ACCENT
        return (
            "QPushButton#recent_link { text-align: left; padding: 4px 12px; "
            "border: 1px solid transparent; background: transparent; font-size: 10pt; }"
            f"QPushButton#recent_link:hover {{ background: {hover_bg}; border-radius: 6px; }}"
            f"QPushButton#recent_link:focus {{ border: 1px solid {focus_border}; border-radius: 6px; }}")

    def update_theme(self, dark: bool) -> None:
        self._canvas.set_dark_mode(dark)
        c = TEXT_SEC if dark else _LQ
        self._open_btn.setIcon(qta.icon('fa5s.folder-open',          color=c))
        self._toc_btn.setIcon(qta.icon('fa5s.bookmark',              color=c))
        self._night_btn.setIcon(qta.icon('fa5s.moon',                color=c))
        self._prev_btn.setIcon(qta.icon('fa5s.chevron-left',          color=c))
        self._next_btn.setIcon(qta.icon('fa5s.chevron-right',         color=c))
        self._zoom_out_btn.setIcon(qta.icon('fa5s.search-minus',      color=c))
        self._zoom_in_btn.setIcon(qta.icon('fa5s.search-plus',        color=c))
        self._fit_btn.setIcon(qta.icon('fa5s.compress-arrows-alt',    color=c))
        self._print_btn.setIcon(qta.icon('fa5s.print',                color=c))
        self._search_prev_btn.setIcon(qta.icon('fa5s.chevron-up',     color=c))
        self._search_next_btn.setIcon(qta.icon('fa5s.chevron-down',   color=c))
        self._search_close_btn.setIcon(qta.icon('fa5s.times',         color=c))
        # Update recent files section
        link_style = self._recent_link_style(dark)
        for link in self._recent_links:
            link.setStyleSheet(link_style)
        for btn in self._recent_del_btns:
            btn.setIcon(qta.icon("fa5s.trash-alt", color=c))

    # ── Drag & drop ──────────────────────────────────────────────────────────
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            urls = e.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith(".pdf"):
                e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        self.load(e.mimeData().urls()[0].toLocalFile())

    # ── Open dialog ────────────────────────────────────────────────────────
    def _remove_recent(self, path: str, row_widget):
        """Remove a file from recents and hide its row."""
        from app.i18n import _CONFIG_PATH
        import json
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            recents = cfg.get("recent_files", [])
            normed = os.path.normpath(path)
            recents = [r for r in recents if os.path.normpath(r) != normed]
            cfg["recent_files"] = recents
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        except Exception:
            pass
        row_widget.setVisible(False)

    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window(), t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if path:
            self.load(path)

    # ── API ──────────────────────────────────────────────────────────────────
    def current_path(self) -> str:
        return self._current_path

    # ── TOC / Bookmarks ─────────────────────────────────────────────────
    def _populate_toc(self, doc):
        """Read the PDF outline and build the tree. Hides the panel if empty."""
        self._toc_tree.clear()
        try:
            toc = doc.get_toc()
        except Exception:
            toc = []
        if not toc:
            self._toc_tree.setVisible(False)
            self._toc_btn.setVisible(False)
            return
        # toc is a list of [level, title, page] (page is 1-indexed)
        stack = [(0, self._toc_tree.invisibleRootItem())]
        for level, title, page in toc:
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else self._toc_tree.invisibleRootItem()
            item = QTreeWidgetItem(parent, [title])
            item.setData(0, Qt.ItemDataRole.UserRole, max(0, page - 1))
            item.setToolTip(0, title)
            stack.append((level, item))
        self._toc_tree.expandToDepth(1)
        self._toc_tree.setVisible(True)
        self._toc_btn.setVisible(True)
        self._toc_btn.setEnabled(True)

    def _on_toc_clicked(self, item, column):
        page_idx = item.data(0, Qt.ItemDataRole.UserRole)
        if page_idx is None:
            return
        y = self._canvas.scroll_to_page(int(page_idx))
        self._canvas_scroll.verticalScrollBar().setValue(y)

    def _toggle_toc(self):
        visible = self._toc_tree.isVisible()
        self._toc_tree.setVisible(not visible)
        if not visible:
            self._viewer_splitter.setSizes([220, max(800, self._viewer_splitter.width() - 220)])
        # Re-layout pages after splitter change
        if self._canvas._doc and self._canvas._zoom_factor == 1.0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(50, self._canvas._layout_and_schedule)

    def _toggle_night_mode(self):
        self._canvas.set_night_mode(self._night_btn.isChecked())

    def load(self, path: str):
        if not path or not os.path.isfile(path):
            return
        if not path.lower().endswith(".pdf"):
            QMessageBox.warning(self, t("viewer.invalid_format"),
                                t("viewer.invalid_msg"))
            return
        import fitz
        if self._fitz_doc:
            self._fitz_doc.close()
            self._fitz_doc = None
        try:
            doc = fitz.open(path)
        except Exception as ex:
            QMessageBox.critical(self, t("viewer.error_open"),
                                 t("viewer.error_open_msg", ex=ex))
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
        self._viewer_splitter.setVisible(True)
        self._sel_status.setVisible(True)
        self._name_lbl.setText(os.path.basename(path))
        self._zoom_lbl.setText(t("zoom.fit"))
        for btn in (self._zoom_out_btn, self._zoom_in_btn, self._fit_btn,
                    self._print_btn, self._night_btn):
            btn.setEnabled(True)
        self._populate_toc(doc)

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
        self._zoom_lbl.setText(t("zoom.fit"))

    # ── Print ────────────────────────────────────────────────────────────────
    def _print_pdf(self):
        if not self._fitz_doc:
            return
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        from PySide6.QtGui import QPainter, QImage
        from PySide6.QtCore import QRectF

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(os.path.basename(self._current_path))

        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle(t("viewer.print"))
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return

        painter = QPainter()
        if not painter.begin(printer):
            return

        page_count = len(self._fitz_doc)
        for i in range(page_count):
            if i > 0:
                printer.newPage()
            page = self._fitz_doc[i]
            # Render at high DPI for print quality
            dpi = printer.resolution()
            zoom = dpi / 72.0
            mat = __import__("fitz").Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img = QImage(pix.samples, pix.width, pix.height,
                         pix.stride, QImage.Format.Format_RGB888)
            target = QRectF(painter.viewport())
            source = QRectF(0, 0, img.width(), img.height())
            # Scale to fit page while maintaining aspect ratio
            scale = min(target.width() / source.width(),
                        target.height() / source.height())
            w = source.width() * scale
            h = source.height() * scale
            x = (target.width() - w) / 2
            y = (target.height() - h) / 2
            painter.drawImage(QRectF(x, y, w, h), img, source)

        painter.end()
