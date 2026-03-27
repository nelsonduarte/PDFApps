"""PDFApps – MainWindow: application main window."""

import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem,
    QStackedWidget, QSplitter, QStatusBar, QFrame,
    QApplication, QLineEdit, QMenu, QTabBar,
)
import qtawesome as qta

from app.constants import ACCENT, TEXT_PRI, TEXT_SEC, _LQ, DESKTOP
from app.i18n import t, set_language, get_language, get_recent_files, add_recent_file
from app.styles import STYLE, STYLE_LIGHT
from app.utils import resource_path, _make_palette
from app.widgets import DropFileEdit
from app.viewer.panel import PdfViewerPanel
from app.tools.split import TabDividir
from app.tools.merge import TabJuntar
from app.tools.rotate import TabRotar
from app.tools.extract import TabExtrair
from app.tools.reorder import TabReordenar
from app.tools.compress import TabComprimir
from app.tools.encrypt import TabEncriptar
from app.tools.watermark import TabMarcaDagua
from app.tools.ocr import TabOCR
from app.tools.convert import TabConverter
from app.editor.tab import TabEditar
from app.tools.info import TabInfo


_NAV_KEYS = [
    ("nav.split",     "fa5s.cut",                TabDividir),
    ("nav.merge",     "fa5s.object-group",        TabJuntar),
    ("nav.rotate",    "fa5s.sync-alt",            TabRotar),
    ("nav.extract",   "fa5s.file-export",         TabExtrair),
    ("nav.reorder",   "fa5s.sort",                TabReordenar),
    ("nav.compress",  "fa5s.compress-arrows-alt", TabComprimir),
    ("nav.encrypt",   "fa5s.lock",                TabEncriptar),
    ("nav.watermark", "fa5s.stamp",               TabMarcaDagua),
    ("nav.ocr",       "fa5s.search",              TabOCR),
    ("nav.convert",   "fa5s.exchange-alt",        TabConverter),
    ("nav.edit",      "fa5s.edit",                TabEditar),
    ("nav.info",      "fa5s.info-circle",         TabInfo),
]

def _build_nav_items():
    return [(t(key), icon, cls) for key, icon, cls in _NAV_KEYS]

NAV_ITEMS = _build_nav_items()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("app.name"))
        import sys as _sys
        if _sys.platform == "darwin":
            candidates = ["icon.icns", "icon.png", "icon.ico"]
        elif _sys.platform == "win32":
            candidates = ["icon.ico", "icon.png"]
        else:
            candidates = ["icon.png", "icon.ico"]
        for _ico in candidates:
            _ico_path = resource_path(_ico)
            if os.path.exists(_ico_path):
                self.setWindowIcon(QIcon(_ico_path))
                break
        self.resize(1220, 700)
        self.showMaximized()
        self.setMinimumSize(860, 540)

        self._sb = QStatusBar(); self.setStatusBar(self._sb)
        self._sb.showMessage(t("app.ready"))

        central = QWidget()
        root_v = QVBoxLayout(central)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)

        workspace_bar = QWidget(); workspace_bar.setObjectName("workspace_bar")
        wb_h = QHBoxLayout(workspace_bar)
        wb_h.setContentsMargins(16, 10, 16, 10)
        wb_h.setSpacing(8)

        wb_col = QVBoxLayout(); wb_col.setContentsMargins(0, 0, 0, 0); wb_col.setSpacing(1)
        wb_title = QLabel(t("workspace.title")); wb_title.setObjectName("workspace_title")
        wb_hint = QLabel(t("workspace.subtitle"))
        wb_hint.setObjectName("workspace_hint")
        wb_col.addWidget(wb_title); wb_col.addWidget(wb_hint)
        wb_h.addLayout(wb_col, 1)

        self._open_pdf_btn = QPushButton()
        self._open_pdf_btn.setIcon(qta.icon("fa5s.folder-open", color=TEXT_PRI))
        self._open_pdf_btn.setObjectName("viewer_nav_btn")
        self._open_pdf_btn.setFixedSize(28, 28)
        self._open_pdf_btn.setToolTip(t("btn.open_pdf"))
        self._open_pdf_btn.clicked.connect(self._open_pdf)
        wb_h.addWidget(self._open_pdf_btn)

        self._recent_btn = QPushButton()
        self._recent_btn.setIcon(qta.icon("fa5s.history", color=TEXT_PRI))
        self._recent_btn.setObjectName("viewer_nav_btn")
        self._recent_btn.setFixedSize(28, 28)
        self._recent_btn.setToolTip(t("recent.title"))
        self._recent_btn.clicked.connect(self._show_recent_menu)
        wb_h.addWidget(self._recent_btn)

        self._quick_merge_btn = QPushButton(t("btn.merge")); self._quick_merge_btn.setObjectName("quick_btn")
        self._quick_ocr_btn = QPushButton(t("btn.ocr")); self._quick_ocr_btn.setObjectName("quick_btn")
        self._quick_edit_btn = QPushButton(t("btn.edit")); self._quick_edit_btn.setObjectName("quick_btn")
        wb_h.addWidget(self._quick_merge_btn)
        wb_h.addWidget(self._quick_ocr_btn)
        wb_h.addWidget(self._quick_edit_btn)

        # zoom widget
        self._zoom_widget = QWidget()
        zw_h = QHBoxLayout(self._zoom_widget); zw_h.setContentsMargins(0,0,0,0); zw_h.setSpacing(4)
        _zm = QPushButton(); _zm.setIcon(qta.icon("fa5s.search-minus", color=TEXT_PRI))
        _zm.setFixedSize(28, 28); _zm.setObjectName("viewer_nav_btn"); _zm.setToolTip(t("zoom.out"))
        self._lbl_zoom = QLabel("100%"); self._lbl_zoom.setMinimumWidth(42); self._lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _zp = QPushButton(); _zp.setIcon(qta.icon("fa5s.search-plus", color=TEXT_PRI))
        _zp.setFixedSize(28, 28); _zp.setObjectName("viewer_nav_btn"); _zp.setToolTip(t("zoom.in"))
        _z0 = QPushButton(t("zoom.reset")); _z0.setObjectName("viewer_nav_btn"); _z0.setFixedHeight(28)
        _z0.setToolTip(t("zoom.reset_tip"))
        zw_h.addWidget(_zm); zw_h.addWidget(self._lbl_zoom); zw_h.addWidget(_zp); zw_h.addWidget(_z0)
        self._zoom_widget.setVisible(False)
        self._zm_btn = _zm; self._zp_btn = _zp; self._z0_btn = _z0
        wb_h.addWidget(self._zoom_widget)

        # page navigation widget
        self._page_nav_widget = QWidget()
        pn_h = QHBoxLayout(self._page_nav_widget); pn_h.setContentsMargins(0,0,0,0); pn_h.setSpacing(4)
        _prev_pg = QPushButton(); _prev_pg.setIcon(qta.icon("fa5s.chevron-left", color=TEXT_PRI))
        _prev_pg.setFixedSize(28, 28); _prev_pg.setObjectName("viewer_nav_btn"); _prev_pg.setToolTip(t("nav.prev_page"))
        self._page_input = QLineEdit("1"); self._page_input.setFixedWidth(40); self._page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_input.setObjectName("page_input")
        self._page_total_lbl = QLabel(t("nav.page_total")); self._page_total_lbl.setMinimumWidth(30)
        _next_pg = QPushButton(); _next_pg.setIcon(qta.icon("fa5s.chevron-right", color=TEXT_PRI))
        _next_pg.setFixedSize(28, 28); _next_pg.setObjectName("viewer_nav_btn"); _next_pg.setToolTip(t("nav.next_page"))
        pn_h.addWidget(_prev_pg); pn_h.addWidget(self._page_input)
        pn_h.addWidget(self._page_total_lbl); pn_h.addWidget(_next_pg)
        self._page_nav_widget.setVisible(False)
        self._prev_pg_btn = _prev_pg; self._next_pg_btn = _next_pg
        _prev_pg.clicked.connect(self._goto_prev_page)
        _next_pg.clicked.connect(self._goto_next_page)
        self._page_input.returnPressed.connect(self._goto_input_page)
        wb_h.addWidget(self._page_nav_widget)

        self._tool_badge = QLabel(t("workspace.mode_viewer")); self._tool_badge.setObjectName("workspace_badge")
        wb_h.addWidget(self._tool_badge)

        self._help_btn = QPushButton("?")
        self._help_btn.setObjectName("theme_btn")
        self._help_btn.setToolTip(t("help.tip"))
        self._help_btn.setFixedSize(28, 28)
        self._help_btn.clicked.connect(lambda: __import__('webbrowser').open("https://nelsonduarte.github.io/PDFApps-en/#guide"))
        wb_h.addWidget(self._help_btn)

        _lang_labels = {"en": "EN", "pt": "PT", "es": "ES", "fr": "FR", "de": "DE"}
        self._lang_btn = QPushButton(_lang_labels.get(get_language(), "EN"))
        self._lang_btn.setObjectName("theme_btn")
        self._lang_btn.setToolTip(t("lang.selector"))
        self._lang_btn.setFixedSize(28, 28)
        self._lang_btn.clicked.connect(self._show_language_menu)
        wb_h.addWidget(self._lang_btn)

        self._theme_btn = QPushButton("☀")
        self._theme_btn.setObjectName("theme_btn")
        self._theme_btn.setToolTip(t("theme.toggle"))
        self._theme_btn.setFixedSize(28, 28)
        self._theme_btn.clicked.connect(self._toggle_theme)
        wb_h.addWidget(self._theme_btn)

        root_v.addWidget(workspace_bar)

        body = QWidget(); body.setObjectName("workspace_shell")
        main_h = QHBoxLayout(body)
        main_h.setContentsMargins(10, 10, 10, 8)
        main_h.setSpacing(10)

        # ── Sidebar ──────────────────────────────────────────────────────────
        self._sidebar = QWidget(); self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(228)
        sb_lay  = QVBoxLayout(self._sidebar)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.setSpacing(0)

        brand = QWidget(); brand.setObjectName("brand_area")
        bv = QVBoxLayout(brand); bv.setContentsMargins(0, 0, 0, 0); bv.setSpacing(0)
        ico_lbl = QLabel()
        from PySide6.QtGui import QPixmap as _QPixmap
        _app_pix = _QPixmap(resource_path("icon.ico")).scaled(
            28, 28, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        if _app_pix.isNull():
            _app_pix = qta.icon('fa5s.file-pdf', color=ACCENT).pixmap(28, 28)
        ico_lbl.setPixmap(_app_pix)
        ico_lbl.setObjectName("app_icon")
        ico_lbl.setContentsMargins(16, 0, 0, 0)
        self._brand_title = QLabel(t("app.name")); self._brand_title.setObjectName("app_title")
        self._brand_sub = QLabel(t("app.subtitle")); self._brand_sub.setObjectName("app_sub")
        bv.addWidget(ico_lbl); bv.addWidget(self._brand_title); bv.addWidget(self._brand_sub)
        sb_lay.addWidget(brand)

        sep = QFrame(); sep.setObjectName("nav_sep"); sep.setFixedHeight(1)
        sb_lay.addWidget(sep)

        self.nav = QListWidget(); self.nav.setObjectName("nav_list")
        self.nav.setSpacing(0)
        self.nav.setIconSize(QSize(18, 18))
        for name, icon_name, _ in NAV_ITEMS:
            item = QListWidgetItem(qta.icon(icon_name, color=TEXT_SEC), name)
            self.nav.addItem(item)
        sb_lay.addWidget(self.nav, 1)

        self._footer_w = QWidget(); self._footer_w.setObjectName("sidebar")
        footer_h = QHBoxLayout(self._footer_w)
        footer_h.setContentsMargins(14, 8, 14, 10); footer_h.setSpacing(0)
        footer_lbl = QLabel(t("app.credits")); footer_lbl.setObjectName("sidebar_footer")
        footer_h.addWidget(footer_lbl, 1)
        sb_lay.addWidget(self._footer_w)
        self._sidebar_collapsed = False
        self._dark_mode = True
        self._qapp: QApplication = QApplication.instance()  # type: ignore[assignment]

        # ── Tool stack (hidden by default) ─────────────────────────
        self.stack = QStackedWidget(); self.stack.setObjectName("content_area")
        for _, __, cls in NAV_ITEMS:
            self.stack.addWidget(cls(self._set_status))
        self.stack.setVisible(False)

        # ── Tabbed viewer ──────────────────────────────────────────────
        self._tab_container = QWidget()
        tc_lay = QVBoxLayout(self._tab_container)
        tc_lay.setContentsMargins(0, 0, 0, 0)
        tc_lay.setSpacing(0)

        self._tab_bar = QTabBar()
        self._tab_bar.setTabsClosable(True)
        self._tab_bar.setMovable(True)
        self._tab_bar.setExpanding(False)
        self._tab_bar.setObjectName("viewer_tabs")
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        self._tab_bar.tabCloseRequested.connect(self._close_tab)
        self._tab_bar.setVisible(False)
        tc_lay.addWidget(self._tab_bar)

        self._viewer_stack = QStackedWidget()
        self._viewers: list[PdfViewerPanel] = []
        # Create first empty viewer
        self._add_viewer_tab()
        tc_lay.addWidget(self._viewer_stack, 1)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(1)
        self._splitter.addWidget(self.stack)
        self._splitter.addWidget(self._tab_container)
        self._splitter.setCollapsible(0, True)
        self._splitter.setCollapsible(1, False)

        main_h.addWidget(self._sidebar)

        # Collapse / expand button (vertical strip between sidebar and content)
        self._collapse_btn = QPushButton("«")
        self._collapse_btn.setObjectName("collapse_btn")
        self._collapse_btn.setFixedWidth(18)
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.setToolTip("Collapse / Expand")
        self._collapse_btn.clicked.connect(self._toggle_sidebar)
        main_h.addWidget(self._collapse_btn)

        main_h.addWidget(self._splitter, 1)
        root_v.addWidget(body, 1)
        self.setCentralWidget(central)

        self._current_tool = -1
        self.nav.itemClicked.connect(self._on_nav_clicked)
        self._quick_merge_btn.clicked.connect(lambda: self._open_tool_by_name("Merge"))
        self._quick_ocr_btn.clicked.connect(lambda: self._open_tool_by_name("OCR"))
        self._quick_edit_btn.clicked.connect(lambda: self._open_tool_by_name("Edit"))

        # Connect all DropFileEdit widgets to load in active viewer
        for i in range(self.stack.count()):
            for dfe in self.stack.widget(i).findChildren(DropFileEdit):
                dfe.path_changed.connect(lambda p: self._viewer.load(p))

    # ── Viewer property (always returns the active tab's viewer) ──────
    @property
    def _viewer(self) -> PdfViewerPanel:
        return self._viewers[self._viewer_stack.currentIndex()] if self._viewers else self._viewers[0]

    def _add_viewer_tab(self, path: str = "") -> PdfViewerPanel:
        v = PdfViewerPanel()
        self._viewers.append(v)
        self._viewer_stack.addWidget(v)
        idx = self._tab_bar.addTab(t("viewer.title"))
        self._tab_bar.setCurrentIndex(idx)
        self._tab_bar.setVisible(self._tab_bar.count() > 1)
        # Wire up scroll → page nav
        v._canvas_scroll.verticalScrollBar().valueChanged.connect(
            lambda _: self._update_page_nav())
        # Wrap load to update tab title + recent files + page nav
        original_load = v.load
        def _make_wrapped(viewer, orig, tab_idx_ref):
            def _wrapped(*args, **kwargs):
                orig(*args, **kwargs)
                if args:
                    add_recent_file(args[0])
                    name = os.path.basename(args[0])
                    # Find this viewer's current tab index
                    for i in range(len(self._viewers)):
                        if self._viewers[i] is viewer:
                            self._tab_bar.setTabText(i, name)
                            self._tab_bar.setTabToolTip(i, args[0])
                            break
                from PySide6.QtCore import QTimer
                QTimer.singleShot(100, self._update_page_nav)
                if self._current_tool == -1:
                    self._setup_zoom_bar(True, canvas=viewer._canvas)
            return _wrapped
        v.load = _make_wrapped(v, original_load, idx)
        if path:
            v.load(path)
        return v

    def _on_tab_changed(self, idx: int):
        if idx < 0 or idx >= len(self._viewers):
            return
        self._viewer_stack.setCurrentIndex(idx)
        self._update_page_nav()
        if self._current_tool == -1:
            self._setup_zoom_bar(True, canvas=self._viewer._canvas)

    def _close_tab(self, idx: int):
        if self._tab_bar.count() <= 1:
            return  # Keep at least one tab
        viewer = self._viewers.pop(idx)
        self._tab_bar.removeTab(idx)
        self._viewer_stack.removeWidget(viewer)
        viewer._canvas.close_doc()
        viewer.deleteLater()
        self._tab_bar.setVisible(self._tab_bar.count() > 1)
        self._update_page_nav()

    def _open_tool_by_name(self, tool_name: str):
        for i, (name, _, _) in enumerate(NAV_ITEMS):
            if name == tool_name:
                self.nav.setCurrentRow(i)
                self._current_tool = i
                self.stack.setCurrentIndex(i)
                self.stack.setVisible(True)
                self._viewer.setVisible(False)
                self._tool_badge.setText(t("workspace.mode_tool", name=name))
                self._try_auto_load(i)
                return

    def _try_auto_load(self, index: int):
        path = self._viewer.current_path()
        if path:
            widget = self.stack.widget(index)
            fn = getattr(widget, "auto_load", None)
            if callable(fn):
                fn(path)

    def _edit_tool_idx(self) -> int:
        return next(i for i, (_, __, cls) in enumerate(NAV_ITEMS) if cls is TabEditar)

    def _setup_zoom_bar(self, active: bool, canvas=None):
        self._zoom_widget.setVisible(active)
        # Disconnect previous connections
        try:
            self._zm_btn.clicked.disconnect()
            self._zp_btn.clicked.disconnect()
            self._z0_btn.clicked.disconnect()
        except Exception:
            pass
        if canvas is None:
            canvas = getattr(self.stack.widget(self._edit_tool_idx()), '_canvas', None)
        if canvas is None:
            return
        if active:
            self._zm_btn.clicked.connect(canvas.zoom_out)
            self._zp_btn.clicked.connect(canvas.zoom_in)
            self._z0_btn.clicked.connect(canvas.zoom_reset)
            canvas.zoom_changed.connect(lambda pct: self._lbl_zoom.setText(f"{pct}%"))
            self._lbl_zoom.setText(f"{round(canvas._zoom_factor * 100)}%")

    def _on_nav_clicked(self, item):
        row = self.nav.row(item)
        edit_idx = self._edit_tool_idx()
        if row == self._current_tool:
            self.nav.clearSelection()
            self._current_tool = -1
            self.stack.setVisible(False)
            self._tab_container.setVisible(True)
            self._tool_badge.setText(t("workspace.mode_viewer"))
            self._setup_zoom_bar(True, canvas=self._viewer._canvas)
        else:
            self._setup_zoom_bar(False)
            self._current_tool = row
            self.stack.setCurrentIndex(row)
            self.stack.setVisible(True)
            self._tab_container.setVisible(False)
            self._tool_badge.setText(t("workspace.mode_tool", name=NAV_ITEMS[row][0]))
            self._try_auto_load(row)
            if row == edit_idx:
                self._setup_zoom_bar(True)

    def _open_pdf(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if path:
            self._load_and_track(path)

    def _load_and_track(self, path: str):
        # If current tab has a PDF, open in new tab; otherwise reuse
        if self._viewer.current_path():
            self._add_viewer_tab(path)
        else:
            self._viewer.load(path)
        add_recent_file(path)

    def _show_recent_menu(self):
        menu = QMenu(self)
        recents = get_recent_files()
        if not recents:
            action = menu.addAction(t("recent.empty"))
            action.setEnabled(False)
        else:
            for path in recents:
                import os
                name = os.path.basename(path)
                action = menu.addAction(f"  {name}")
                action.setToolTip(path)
                action.triggered.connect(lambda checked, p=path: self._load_and_track(p))
            menu.addSeparator()
            clear_action = menu.addAction(t("recent.clear"))
            clear_action.triggered.connect(self._clear_recent)
        menu.exec(self._recent_btn.mapToGlobal(self._recent_btn.rect().bottomLeft()))

    def _clear_recent(self):
        import json
        from app.i18n import _CONFIG_PATH
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg["recent_files"] = []
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        except Exception:
            pass

    def _set_status(self, msg: str):
        self._sb.showMessage(msg)

    # ── Page navigation (workspace bar) ───────────────────────────────────

    def _update_page_nav(self):
        """Update the page nav widget from the viewer's scroll position."""
        canvas = self._viewer._canvas
        entries = canvas._entries
        if not entries:
            self._page_nav_widget.setVisible(False)
            return
        self._page_nav_widget.setVisible(True)
        sb_val = self._viewer._canvas_scroll.verticalScrollBar().value()
        idx = canvas.page_at_y(sb_val)
        total = len(entries)
        self._page_input.setText(str(idx + 1))
        self._page_total_lbl.setText(f"/ {total}")
        self._prev_pg_btn.setEnabled(idx > 0)
        self._next_pg_btn.setEnabled(idx < total - 1)

    def _goto_prev_page(self):
        canvas = self._viewer._canvas
        if not canvas._entries:
            return
        sb = self._viewer._canvas_scroll.verticalScrollBar()
        idx = canvas.page_at_y(sb.value())
        if idx > 0:
            sb.setValue(canvas.scroll_to_page(idx - 1))

    def _goto_next_page(self):
        canvas = self._viewer._canvas
        if not canvas._entries:
            return
        sb = self._viewer._canvas_scroll.verticalScrollBar()
        idx = canvas.page_at_y(sb.value())
        if idx < len(canvas._entries) - 1:
            sb.setValue(canvas.scroll_to_page(idx + 1))

    def _goto_input_page(self):
        """Navigate to the page number typed by the user."""
        canvas = self._viewer._canvas
        if not canvas._entries:
            return
        try:
            page_num = int(self._page_input.text())
        except ValueError:
            return
        page_num = max(1, min(page_num, len(canvas._entries)))
        self._page_input.setText(str(page_num))
        sb = self._viewer._canvas_scroll.verticalScrollBar()
        sb.setValue(canvas.scroll_to_page(page_num - 1))

    def _show_language_menu(self):
        _langs = [("en", "English"), ("pt", "Português"), ("es", "Español"), ("fr", "Français"), ("de", "Deutsch"), ("zh", "中文"), ("it", "Italiano"), ("nl", "Nederlands")]
        menu = QMenu(self)
        current = get_language()
        for code, name in _langs:
            action = menu.addAction(f"  {'● ' if code == current else '  '}{name}")
            action.triggered.connect(lambda checked, c=code, n=name: self._set_language(c, n))
        menu.exec(self._lang_btn.mapToGlobal(self._lang_btn.rect().bottomLeft()))

    def _set_language(self, code: str, name: str):
        from PySide6.QtWidgets import QMessageBox
        set_language(code)
        _labels = {"en": "EN", "pt": "PT", "es": "ES", "fr": "FR", "de": "DE", "zh": "ZH", "it": "IT", "nl": "NL"}
        self._lang_btn.setText(_labels.get(code, "EN"))
        QMessageBox.information(self, t("lang.selector"),
                                t("lang.restart", lang=name))

    def _toggle_sidebar(self):
        self._sidebar_collapsed = not self._sidebar_collapsed
        icon_color = TEXT_SEC if self._dark_mode else _LQ
        if self._sidebar_collapsed:
            self._sidebar.setFixedWidth(50)
            self._brand_title.setVisible(False)
            self._brand_sub.setVisible(False)
            self._footer_w.setVisible(False)
            self._collapse_btn.setText("»")
            for i in range(self.nav.count()):
                self.nav.item(i).setText("")
            self.nav.setIconSize(QSize(22, 22))
        else:
            self._sidebar.setFixedWidth(228)
            self._brand_title.setVisible(True)
            self._brand_sub.setVisible(True)
            self._footer_w.setVisible(True)
            self._collapse_btn.setText("«")
            for i, (_, icon_name, _) in enumerate(NAV_ITEMS):
                self.nav.item(i).setText(NAV_ITEMS[i][0])
            self.nav.setIconSize(QSize(18, 18))

    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        style      = STYLE if self._dark_mode else STYLE_LIGHT
        icon_color = TEXT_SEC if self._dark_mode else _LQ
        self._qapp.setPalette(_make_palette(self._dark_mode))
        self._qapp.setStyleSheet(style)
        self._theme_btn.setText("☀" if self._dark_mode else "🌙")
        for i, (_, icon_name, _) in enumerate(NAV_ITEMS):
            self.nav.item(i).setIcon(qta.icon(icon_name, color=icon_color))
        self._viewer.update_theme(self._dark_mode)
