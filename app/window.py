"""PDFApps – MainWindow: application main window."""

import os

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem,
    QStackedWidget, QSplitter, QStatusBar, QFrame,
    QApplication, QLineEdit, QMenu, QTabBar,
    QFileDialog, QMessageBox,
)
from PySide6.QtGui import QColor
import qtawesome as qta

from app.constants import ACCENT, TEXT_PRI, TEXT_SEC, _LQ, DESKTOP, BORDER
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
from app.tools.import_pdf import TabImport
from app.tools.page_numbers import TabPageNumbers
from app.tools.nup import TabNUp


# Grouped sidebar tools — order here = stack index order.
_NAV_GROUPS = [
    ("nav.group.organize", [
        ("nav.split",         "fa5s.cut",                TabDividir),
        ("nav.merge",         "fa5s.object-group",       TabJuntar),
        ("nav.reorder",       "fa5s.sort",               TabReordenar),
        ("nav.extract",       "fa5s.file-export",        TabExtrair),
    ]),
    ("nav.group.transform", [
        ("nav.rotate",        "fa5s.sync-alt",           TabRotar),
        ("nav.compress",      "fa5s.compress-arrows-alt",TabComprimir),
        ("nav.page_numbers",  "fa5s.list-ol",            TabPageNumbers),
        ("nav.nup",           "fa5s.th",                 TabNUp),
    ]),
    ("nav.group.security", [
        ("nav.encrypt",       "fa5s.lock",               TabEncriptar),
        ("nav.watermark",     "fa5s.stamp",              TabMarcaDagua),
    ]),
    ("nav.group.convert", [
        ("nav.ocr",           "fa5s.eye",                TabOCR),
        ("nav.convert",       "fa5s.exchange-alt",       TabConverter),
        ("nav.import",        "fa5s.file-import",        TabImport),
    ]),
    ("nav.group.annotate", [
        ("nav.edit",          "fa5s.edit",               TabEditar),
    ]),
    ("nav.group.inspect", [
        ("nav.info",          "fa5s.info-circle",        TabInfo),
    ]),
]

# Flat list for stack building — order must match grouped order above.
_NAV_KEYS = [(key, icon, cls) for _, tools in _NAV_GROUPS for key, icon, cls in tools]

def _build_nav_items():
    return [(t(key), icon, cls) for key, icon, cls in _NAV_KEYS]

NAV_ITEMS = _build_nav_items()


class MainWindow(QMainWindow):
    _update_ready = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("app.name"))
        _ico_path = resource_path("icon.ico")
        if os.path.exists(_ico_path):
            self.setWindowIcon(QIcon(_ico_path))
        else:
            _svg = resource_path("pdfapps.svg")
            if os.path.exists(_svg):
                self.setWindowIcon(QIcon(_svg))
        self.resize(1220, 700)
        self.showMaximized()
        self.setMinimumSize(860, 540)

        self._sb = QStatusBar(); self.setStatusBar(self._sb)
        self._sb.showMessage(t("app.ready"))
        self.setAcceptDrops(True)

        central = QWidget()
        root_v = QVBoxLayout(central)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)

        self._workspace_bar = QWidget(); self._workspace_bar.setObjectName("workspace_bar")
        wb_h = QHBoxLayout(self._workspace_bar)
        wb_h.setContentsMargins(16, 10, 16, 10)
        wb_h.setSpacing(8)

        def _a11y(btn, tip):
            """Set both tooltip and accessible name on a button."""
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)

        self._sidebar_toggle_btn = QPushButton()
        self._ico_bars = qta.icon("fa5s.bars", color=TEXT_PRI)
        self._ico_times = qta.icon("fa5s.times", color=TEXT_PRI)
        self._sidebar_toggle_btn.setIcon(self._ico_bars)
        self._sidebar_toggle_btn.setObjectName("viewer_nav_btn")
        self._sidebar_toggle_btn.setFixedSize(28, 28)
        _a11y(self._sidebar_toggle_btn, t("sidebar.collapse_expand"))
        self._sidebar_toggle_btn.clicked.connect(self._toggle_sidebar)
        wb_h.addWidget(self._sidebar_toggle_btn)

        self._breadcrumb = QLabel(t("workspace.title"))
        self._breadcrumb.setObjectName("workspace_title")
        wb_h.addWidget(self._breadcrumb, 1)

        self._open_pdf_btn = QPushButton()
        self._open_pdf_btn.setIcon(qta.icon("fa5s.folder-open", color=TEXT_PRI))
        self._open_pdf_btn.setObjectName("viewer_nav_btn")
        self._open_pdf_btn.setFixedSize(28, 28)
        _a11y(self._open_pdf_btn, t("btn.open_pdf"))
        self._open_pdf_btn.clicked.connect(self._open_pdf)
        wb_h.addWidget(self._open_pdf_btn)

        # Recent button removed — recents shown in viewer placeholder

        self._toc_top_btn = QPushButton()
        self._toc_top_btn.setIcon(qta.icon("fa5s.bookmark", color=TEXT_PRI))
        self._toc_top_btn.setObjectName("viewer_nav_btn")
        self._toc_top_btn.setFixedSize(28, 28)
        _a11y(self._toc_top_btn, t("viewer.toc"))
        self._toc_top_btn.setVisible(False)
        self._toc_top_btn.clicked.connect(lambda: self._viewer._toggle_toc())
        wb_h.addWidget(self._toc_top_btn)

        self._night_top_btn = QPushButton()
        self._night_top_btn.setIcon(qta.icon("fa5s.moon", color=TEXT_PRI))
        self._night_top_btn.setObjectName("viewer_nav_btn")
        self._night_top_btn.setFixedSize(28, 28)
        _a11y(self._night_top_btn, t("viewer.night_mode"))
        self._night_top_btn.setCheckable(True)
        self._night_top_btn.clicked.connect(self._toggle_night_mode_top)
        wb_h.addWidget(self._night_top_btn)

        self._print_top_btn = QPushButton()
        self._print_top_btn.setIcon(qta.icon("fa5s.print", color=TEXT_PRI))
        self._print_top_btn.setObjectName("viewer_nav_btn")
        self._print_top_btn.setFixedSize(28, 28)
        _a11y(self._print_top_btn, t("viewer.print"))
        self._print_top_btn.clicked.connect(lambda: self._viewer._print_pdf())
        wb_h.addWidget(self._print_top_btn)

        self._present_btn = QPushButton()
        self._present_btn.setIcon(qta.icon("fa5s.tv", color=TEXT_PRI))
        self._present_btn.setObjectName("viewer_nav_btn")
        self._present_btn.setFixedSize(28, 28)
        _a11y(self._present_btn, t("viewer.presentation") + " (F5)")
        self._present_btn.clicked.connect(self._start_presentation)
        wb_h.addWidget(self._present_btn)

        self._search_top_btn = QPushButton()
        self._search_top_btn.setIcon(qta.icon("fa5s.search", color=TEXT_PRI))
        self._search_top_btn.setObjectName("viewer_nav_btn")
        self._search_top_btn.setFixedSize(28, 28)
        _a11y(self._search_top_btn, t("search.placeholder") + " (Ctrl+F)")
        self._search_top_btn.clicked.connect(lambda: self._viewer._toggle_search())
        wb_h.addWidget(self._search_top_btn)

        # zoom widget
        self._zoom_widget = QWidget()
        zw_h = QHBoxLayout(self._zoom_widget); zw_h.setContentsMargins(0,0,0,0); zw_h.setSpacing(4)
        _zm = QPushButton(); _zm.setIcon(qta.icon("fa5s.search-minus", color=TEXT_PRI))
        _zm.setFixedSize(28, 28); _zm.setObjectName("viewer_nav_btn"); _a11y(_zm, t("zoom.out"))
        self._lbl_zoom = QLabel("100%"); self._lbl_zoom.setMinimumWidth(42); self._lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _zp = QPushButton(); _zp.setIcon(qta.icon("fa5s.search-plus", color=TEXT_PRI))
        _zp.setFixedSize(28, 28); _zp.setObjectName("viewer_nav_btn"); _a11y(_zp, t("zoom.in"))
        _z0 = QPushButton(t("zoom.reset")); _z0.setObjectName("viewer_nav_btn"); _z0.setFixedHeight(28)
        _a11y(_z0, t("zoom.reset_tip"))
        zw_h.addWidget(_zm); zw_h.addWidget(self._lbl_zoom); zw_h.addWidget(_zp); zw_h.addWidget(_z0)
        self._zoom_widget.setVisible(False)
        self._zm_btn = _zm; self._zp_btn = _zp; self._z0_btn = _z0
        wb_h.addWidget(self._zoom_widget)

        # page navigation widget
        self._page_nav_widget = QWidget()
        pn_h = QHBoxLayout(self._page_nav_widget); pn_h.setContentsMargins(0,0,0,0); pn_h.setSpacing(4)
        _prev_pg = QPushButton(); _prev_pg.setIcon(qta.icon("fa5s.chevron-left", color=TEXT_PRI))
        _prev_pg.setFixedSize(28, 28); _prev_pg.setObjectName("viewer_nav_btn"); _a11y(_prev_pg, t("nav.prev_page"))
        self._page_input = QLineEdit("1"); self._page_input.setFixedWidth(40); self._page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_input.setObjectName("page_input")
        self._page_total_lbl = QLabel(t("nav.page_total")); self._page_total_lbl.setMinimumWidth(30)
        _next_pg = QPushButton(); _next_pg.setIcon(qta.icon("fa5s.chevron-right", color=TEXT_PRI))
        _next_pg.setFixedSize(28, 28); _next_pg.setObjectName("viewer_nav_btn"); _a11y(_next_pg, t("nav.next_page"))
        pn_h.addWidget(_prev_pg); pn_h.addWidget(self._page_input)
        pn_h.addWidget(self._page_total_lbl); pn_h.addWidget(_next_pg)
        self._page_nav_widget.setVisible(False)
        self._prev_pg_btn = _prev_pg; self._next_pg_btn = _next_pg
        _prev_pg.clicked.connect(self._goto_prev_page)
        _next_pg.clicked.connect(self._goto_next_page)
        self._page_input.returnPressed.connect(self._goto_input_page)
        wb_h.addWidget(self._page_nav_widget)

        # (tool badge removed — breadcrumb replaces it)

        # Undo/redo buttons for editor (hidden by default)
        self._undo_top_btn = QPushButton()
        self._undo_top_btn.setIcon(qta.icon("fa5s.undo", color=TEXT_PRI))
        self._undo_top_btn.setObjectName("viewer_nav_btn")
        self._undo_top_btn.setFixedSize(28, 28)
        _a11y(self._undo_top_btn, t("btn.undo") if "btn.undo" != t("btn.undo") else "Undo (Ctrl+Z)")
        self._undo_top_btn.setVisible(False)
        wb_h.addWidget(self._undo_top_btn)
        self._redo_top_btn = QPushButton()
        self._redo_top_btn.setIcon(qta.icon("fa5s.redo", color=TEXT_PRI))
        self._redo_top_btn.setObjectName("viewer_nav_btn")
        self._redo_top_btn.setFixedSize(28, 28)
        _a11y(self._redo_top_btn, t("btn.redo") if "btn.redo" != t("btn.redo") else "Redo (Ctrl+Y)")
        self._redo_top_btn.setVisible(False)
        wb_h.addWidget(self._redo_top_btn)

        self._help_btn = QPushButton("?")
        self._help_btn.setObjectName("theme_btn")
        _a11y(self._help_btn, t("help.tip"))
        self._help_btn.setFixedSize(28, 28)
        self._help_btn.clicked.connect(lambda: __import__('webbrowser').open("https://nelsonduarte.github.io/PDFApps/#guide"))
        wb_h.addWidget(self._help_btn)

        _lang_labels = {"en": "EN", "pt": "PT", "es": "ES", "fr": "FR", "de": "DE", "zh": "ZH", "it": "IT", "nl": "NL"}
        self._lang_btn = QPushButton(_lang_labels.get(get_language(), "EN"))
        self._lang_btn.setObjectName("theme_btn")
        _a11y(self._lang_btn, t("lang.selector"))
        self._lang_btn.setFixedSize(28, 28)
        self._lang_btn.clicked.connect(self._show_language_menu)
        wb_h.addWidget(self._lang_btn)

        self._theme_btn = QPushButton("☀")
        self._theme_btn.setObjectName("theme_btn")
        _a11y(self._theme_btn, t("theme.toggle"))
        self._theme_btn.setFixedSize(28, 28)
        self._theme_btn.clicked.connect(self._toggle_theme)
        wb_h.addWidget(self._theme_btn)

        # Update button — hidden by default, shown when update is available
        self._update_btn = QPushButton()
        self._update_btn.setIcon(qta.icon("fa5s.arrow-circle-up", color=ACCENT))
        self._update_btn.setObjectName("viewer_nav_btn")
        self._update_btn.setFixedSize(28, 28)
        _a11y(self._update_btn, t("update.check"))
        self._update_btn.setVisible(False)
        self._update_btn.setStyleSheet(
            f"QPushButton {{ border: 1.5px solid {ACCENT}; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: rgba(20,184,166,0.15); }}"
        )
        self._update_btn.clicked.connect(self._show_update_dialog)
        wb_h.addWidget(self._update_btn)
        self._update_release = None
        self._update_ready.connect(self._notify_update)
        self._check_for_updates_async()

        root_v.addWidget(self._workspace_bar)

        body = QWidget(); body.setObjectName("workspace_shell")
        main_h = QHBoxLayout(body)
        main_h.setContentsMargins(10, 10, 10, 0)
        main_h.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────────
        self._sidebar = QWidget(); self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(228)
        sb_lay  = QVBoxLayout(self._sidebar)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.setSpacing(0)

        brand = QWidget(); brand.setObjectName("brand_area")
        bh = QHBoxLayout(brand); bh.setContentsMargins(12, 10, 10, 10); bh.setSpacing(8)
        ico_lbl = QLabel()
        from PySide6.QtGui import QPixmap as _QPixmap
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtGui import QPainter, QImage
        _svg_path = resource_path("pdfapps.svg")
        _h = 36  # target height
        if os.path.exists(_svg_path):
            renderer = QSvgRenderer(_svg_path)
            vb = renderer.viewBox()
            ratio = vb.width() / vb.height() if vb.height() else 1.0
            _w = int(_h * ratio)
            img = QImage(_w * 2, _h * 2, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0)
            p = QPainter(img)
            renderer.render(p)
            p.end()
            _app_pix = _QPixmap.fromImage(img)
            _app_pix.setDevicePixelRatio(2.0)
        else:
            _w = _h
            _ico_path = resource_path("icon.ico")
            _app_pix = _QPixmap(_ico_path).scaled(
                _w * 2, _h * 2, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            _app_pix.setDevicePixelRatio(2.0)
        ico_lbl.setPixmap(_app_pix)
        ico_lbl.setObjectName("app_icon")
        ico_lbl.setFixedSize(_w, _h)
        ico_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bh.addWidget(ico_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        brand_text = QVBoxLayout(); brand_text.setContentsMargins(0, 0, 0, 0); brand_text.setSpacing(1)
        self._brand_title = QLabel(t("app.name")); self._brand_title.setObjectName("app_title")
        self._brand_sub = QLabel(t("app.subtitle")); self._brand_sub.setObjectName("app_sub")
        brand_text.addWidget(self._brand_title); brand_text.addWidget(self._brand_sub)
        bh.addLayout(brand_text, 1)
        sb_lay.addWidget(brand)

        sep = QFrame(); sep.setObjectName("nav_sep"); sep.setFixedHeight(1)
        sb_lay.addWidget(sep)

        self._nav_search = QLineEdit()
        self._nav_search.setPlaceholderText("🔍 " + t("nav.search"))
        self._nav_search.setClearButtonEnabled(True)
        self._nav_search.setObjectName("nav_search")
        self._nav_search.textChanged.connect(self._filter_nav)
        sb_lay.addWidget(self._nav_search)

        self.nav = QListWidget(); self.nav.setObjectName("nav_list")
        self.nav.setSpacing(0)
        self.nav.setIconSize(QSize(18, 18))

        # Load tool usage counts for "Frequent" section
        self._tool_usage = {}
        try:
            from app.i18n import _CONFIG_PATH
            import json
            with open(_CONFIG_PATH, "r", encoding="utf-8") as _cf:
                self._tool_usage = json.load(_cf).get("tool_usage", {})
        except Exception:
            pass
        # Add top 3 frequent tools (if any usage data)
        sorted_usage = sorted(self._tool_usage.items(), key=lambda x: x[1], reverse=True)
        freq_tools = [(k, v) for k, v in sorted_usage if v >= 2][:3]
        if freq_tools:
            hdr = QListWidgetItem(t("nav.group.frequent").upper())
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            hdr.setData(Qt.ItemDataRole.UserRole, -1)
            hdr.setForeground(QColor(ACCENT))
            from PySide6.QtGui import QFont as _QF
            f = _QF(); f.setPointSize(9); f.setBold(True); f.setLetterSpacing(_QF.SpacingType.AbsoluteSpacing, 1.5)
            hdr.setFont(f); hdr.setSizeHint(QSize(0, 26))
            self.nav.addItem(hdr)
            for nav_key, _count in freq_tools:
                for idx, (key, icon_name, _) in enumerate(_NAV_KEYS):
                    if key == nav_key:
                        item = QListWidgetItem(qta.icon(icon_name, color=ACCENT), t(key))
                        item.setData(Qt.ItemDataRole.UserRole, idx)
                        self.nav.addItem(item)
                        break

        tool_idx = 0
        for group_key, tools in _NAV_GROUPS:
            # Separator line between groups (skip before first group)
            if tool_idx > 0:
                sep_item = QListWidgetItem()
                sep_item.setFlags(Qt.ItemFlag.NoItemFlags)
                sep_item.setData(Qt.ItemDataRole.UserRole, -1)
                sep_item.setSizeHint(QSize(0, 24))
                self.nav.addItem(sep_item)
                sep_line = QFrame()
                sep_line.setFixedHeight(1)
                sep_line.setStyleSheet(f"background:{BORDER}; margin: 0 8px 0 4px;")
                self.nav.setItemWidget(sep_item, sep_line)
            # Section header (non-selectable)
            hdr = QListWidgetItem(t(group_key).upper())
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            hdr.setData(Qt.ItemDataRole.UserRole, -1)
            hdr.setForeground(QColor(TEXT_SEC))
            from PySide6.QtGui import QFont as _QF
            f = _QF(); f.setPointSize(9); f.setBold(True); f.setLetterSpacing(_QF.SpacingType.AbsoluteSpacing, 1.5)
            hdr.setFont(f)
            hdr.setSizeHint(QSize(0, 26))
            self.nav.addItem(hdr)
            for key, icon_name, _ in tools:
                item = QListWidgetItem(qta.icon(icon_name, color=TEXT_SEC), t(key))
                item.setData(Qt.ItemDataRole.UserRole, tool_idx)
                # Tooltip with tool description
                desc_key = key.replace("nav.", "tool.") + ".desc"
                tip = t(desc_key)
                if tip != desc_key:
                    item.setToolTip(tip)
                self.nav.addItem(item)
                tool_idx += 1
        sb_lay.addWidget(self.nav, 1)

        self._footer_w = QWidget(); self._footer_w.setObjectName("sidebar")
        footer_h = QHBoxLayout(self._footer_w)
        footer_h.setContentsMargins(14, 8, 14, 10); footer_h.setSpacing(0)
        footer_lbl = QLabel(t("app.credits")); footer_lbl.setObjectName("sidebar_footer")
        footer_h.addWidget(footer_lbl, 1)
        sb_lay.addWidget(self._footer_w)
        self._sidebar_collapsed = False
        # Load saved theme preference
        self._dark_mode = True
        try:
            from app.i18n import _CONFIG_PATH
            import json
            with open(_CONFIG_PATH, "r", encoding="utf-8") as _cf:
                self._dark_mode = json.load(_cf).get("dark_mode", True)
        except Exception:
            pass
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

        tab_row = QHBoxLayout(); tab_row.setContentsMargins(0, 0, 0, 0); tab_row.setSpacing(0)
        self._tab_bar = QTabBar()
        self._tab_bar.setTabsClosable(True)
        self._tab_bar.setMovable(True)
        self._tab_bar.setExpanding(False)
        self._tab_bar.setObjectName("viewer_tabs")
        self._current_tool = -1
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        self._tab_bar.tabCloseRequested.connect(self._close_tab)
        self._tab_bar.setVisible(False)
        tab_row.addWidget(self._tab_bar, 1)
        tc_lay.addLayout(tab_row)

        self._viewer_stack = QStackedWidget()
        self._viewers: list[PdfViewerPanel] = []
        # Create first empty viewer
        self._add_viewer_tab()
        tc_lay.addWidget(self._viewer_stack, 1)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(1)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._tab_container)
        self._splitter.addWidget(self.stack)
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, True)

        main_h.addWidget(self._sidebar)
        main_h.addWidget(self._splitter, 1)
        root_v.addWidget(body, 1)
        self.setCentralWidget(central)

        # Restore saved layout
        try:
            from app.i18n import _CONFIG_PATH
            import json
            with open(_CONFIG_PATH, "r", encoding="utf-8") as _cf:
                _saved = json.load(_cf)
            if "splitter_sizes" in _saved:
                self._splitter.setSizes(_saved["splitter_sizes"])
        except Exception:
            pass

        self._current_tool = -1
        self.nav.itemClicked.connect(self._on_nav_clicked)
        # Connect all DropFileEdit widgets to load in active viewer
        for i in range(self.stack.count()):
            for dfe in self.stack.widget(i).findChildren(DropFileEdit):
                dfe.path_changed.connect(lambda p: self._viewer.load(p))

        # Pipeline: connect tool signals to reload viewer with result
        from app.base import BasePage
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if isinstance(w, BasePage):
                w.pipeline_done.connect(self._on_pipeline_done)
        # Per-viewer pipeline state: {viewer_id: {original_path, temp_path}}
        self._pipeline_state: dict[int, dict] = {}

        # Keyboard shortcuts
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("F5"), self, self._start_presentation)
        QShortcut(QKeySequence("F11"), self, self._toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+O"), self, self._open_pdf)
        QShortcut(QKeySequence("Ctrl+P"), self, lambda: self._viewer._print_pdf())
        QShortcut(QKeySequence("Ctrl+W"), self, self._close_current_tab)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_current_tool)
        QShortcut(QKeySequence("PgUp"), self, self._goto_prev_page)
        QShortcut(QKeySequence("PgDown"), self, self._goto_next_page)
        # Quick tool shortcuts: Ctrl+1..9 for tools 1-9,
        # Ctrl+Shift+1..6 for tools 10-15
        for idx in range(len(NAV_ITEMS)):
            if idx < 9:
                QShortcut(QKeySequence(f"Ctrl+{idx+1}"), self,
                          lambda i=idx: self._activate_tool(i))
            else:
                QShortcut(QKeySequence(f"Ctrl+Shift+{idx-8}"), self,
                          lambda i=idx: self._activate_tool(i))
        self._fullscreen = False

        # Apply saved theme (if light mode was saved)
        if not self._dark_mode:
            self._apply_theme()

    # ── Viewer property (always returns the active tab's viewer) ──────
    @property
    def _viewer(self) -> PdfViewerPanel:
        idx = self._viewer_stack.currentIndex()
        if 0 <= idx < len(self._viewers):
            return self._viewers[idx]
        return self._viewers[0]

    def _add_viewer_tab(self, path: str = "") -> PdfViewerPanel:
        v = PdfViewerPanel()
        self._viewers.append(v)
        self._viewer_stack.addWidget(v)
        idx = self._tab_bar.addTab(t("viewer.title"))
        self._tab_bar.setCurrentIndex(idx)
        self._update_tab_visibility()
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
                self._update_tab_visibility()
                if self._current_tool == -1:
                    self._setup_zoom_bar(True, canvas=viewer._canvas)
            return _wrapped
        v.load = _make_wrapped(v, original_load, idx)
        if path:
            v.load(path)
        return v

    def _update_tab_visibility(self):
        has_doc = any(v.current_path() for v in self._viewers)
        self._tab_bar.setVisible(has_doc)

    def _on_tab_changed(self, idx: int):
        if idx < 0 or idx >= len(self._viewers):
            return
        self._viewer_stack.setCurrentIndex(idx)
        self._update_page_nav()
        if self._current_tool == -1:
            self._setup_zoom_bar(True, canvas=self._viewer._canvas)
        self._refresh_viewer_top_buttons()

    def _close_tab(self, idx: int):
        viewer = self._viewers[idx] if idx < len(self._viewers) else self._viewers[0]
        if self._viewer_has_unsaved(viewer):
            ans = QMessageBox.question(
                self, t("msg.warning"), t("pipeline.unsaved_prompt"),
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if ans == QMessageBox.StandardButton.Cancel:
                return
            if ans == QMessageBox.StandardButton.Save:
                self._save_pipeline()
                return  # save_pipeline reloads, don't close
        self._cleanup_pipeline(id(viewer))
        if self._tab_bar.count() <= 1:
            # Last tab — close document and reset to placeholder
            viewer = self._viewers[0]
            viewer._canvas.close_doc()
            viewer._fitz_doc = None
            viewer._current_path = ""
            viewer._viewer_splitter.setVisible(False)
            viewer._toc_tree.clear()
            viewer._toc_tree.setVisible(False)
            viewer._toc_btn.setVisible(False)
            viewer._sel_status.setVisible(False)
            viewer._placeholder.setVisible(True)
            viewer._hdr.setVisible(False)
            viewer._name_lbl.setText(t("viewer.title"))
            self._tab_bar.setTabText(0, t("viewer.title"))
            self._tab_bar.setTabToolTip(0, "")
            self._update_tab_visibility()
            self._update_page_nav()
            self._setup_zoom_bar(False)
            self._page_nav_widget.setVisible(False)
            self._refresh_viewer_top_buttons()
            return
        viewer = self._viewers.pop(idx)
        self._tab_bar.removeTab(idx)
        self._viewer_stack.removeWidget(viewer)
        viewer._canvas.close_doc()
        viewer.deleteLater()
        self._update_tab_visibility()
        self._update_page_nav()

    def _open_tool_by_name(self, tool_name: str):
        for i, (name, _, _) in enumerate(NAV_ITEMS):
            if name == tool_name:
                # Find the nav row with matching tool index
                for r in range(self.nav.count()):
                    if self.nav.item(r).data(Qt.ItemDataRole.UserRole) == i:
                        self.nav.setCurrentRow(r)
                        break
                self._current_tool = i
                self.stack.setCurrentIndex(i)
                self.stack.setVisible(True)
                self._tab_container.setVisible(False)
                self._breadcrumb.setText(f"{t('workspace.title')}  ›  {name}")
                self._try_auto_load(i)
                return

    def _try_auto_load(self, index: int):
        # Track tool usage for "Frequent" section
        nav_key = _NAV_KEYS[index][0]
        self._tool_usage[nav_key] = self._tool_usage.get(nav_key, 0) + 1
        try:
            from app.i18n import _CONFIG_PATH
            import json
            cfg = {}
            try:
                with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass
            cfg["tool_usage"] = self._tool_usage
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        except Exception:
            pass
        widget = self.stack.widget(index)
        path = self._viewer.current_path()
        if path:
            fn = getattr(widget, "auto_load", None)
            if callable(fn):
                fn(path)
        # Toggle "compact mode" for tools that support it: when a viewer PDF
        # is loaded, hide the source/output pickers so the user can act with
        # a single button.
        compact_fn = getattr(widget, "set_compact_mode", None)
        if callable(compact_fn):
            compact_fn(bool(path), path or "")

    def _edit_tool_idx(self) -> int:
        return next(i for i, (_, __, cls) in enumerate(NAV_ITEMS) if cls is TabEditar)

    def _setup_zoom_bar(self, active: bool, canvas=None):
        self._zoom_widget.setVisible(active)
        # Disconnect previous connections safely
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for btn in (self._zm_btn, self._zp_btn, self._z0_btn):
                try:
                    btn.clicked.disconnect()
                except (RuntimeError, TypeError):
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

    def _activate_tool(self, tool_idx: int):
        """Activate a tool by its stack index (for keyboard shortcuts)."""
        for r in range(self.nav.count()):
            it = self.nav.item(r)
            if it.data(Qt.ItemDataRole.UserRole) == tool_idx:
                self.nav.setCurrentRow(r)
                self._on_nav_clicked(it)
                return

    def _filter_nav(self, text: str):
        """Show/hide nav items based on search text."""
        q = text.lower().strip()
        visible_groups = set()
        for r in range(self.nav.count()):
            it = self.nav.item(r)
            tool_idx = it.data(Qt.ItemDataRole.UserRole)
            if tool_idx is not None and tool_idx >= 0:
                match = not q or q in it.text().lower()
                it.setHidden(not match)
                if match:
                    visible_groups.add(r)
        # Show/hide group headers: visible if any child below is visible
        for r in range(self.nav.count()):
            it = self.nav.item(r)
            if it.data(Qt.ItemDataRole.UserRole) == -1:
                # Header — show if any tool below (until next header) is visible
                has_visible = False
                for r2 in range(r + 1, self.nav.count()):
                    it2 = self.nav.item(r2)
                    if it2.data(Qt.ItemDataRole.UserRole) == -1:
                        break
                    if not it2.isHidden():
                        has_visible = True; break
                it.setHidden(not has_visible)

    def _on_nav_clicked(self, item):
        row = item.data(Qt.ItemDataRole.UserRole)
        if row is None or row < 0:
            self.nav.clearSelection()
            return  # clicked a section header
        edit_idx = self._edit_tool_idx()
        if row == self._current_tool:
            self.nav.clearSelection()
            self._current_tool = -1
            self.stack.setVisible(False)
            self._tab_container.setVisible(True)
            self._breadcrumb.setText(t("workspace.title"))
            self._setup_zoom_bar(True, canvas=self._viewer._canvas)
            self._undo_top_btn.setVisible(False)
            self._redo_top_btn.setVisible(False)
        else:
            self._setup_zoom_bar(False)
            self._current_tool = row
            self.stack.setCurrentIndex(row)
            self.stack.setVisible(True)
            # Editor takes the whole area (it has its own canvas);
            # other tools open as a fixed-width side panel with the viewer
            # still visible.
            if row == edit_idx:
                self.stack.setMinimumWidth(0)
                self.stack.setMaximumWidth(16777215)
                self._tab_container.setVisible(False)
                self._setup_zoom_bar(True)
                # Show undo/redo in workspace bar
                edit_w = self.stack.widget(edit_idx)
                self._undo_top_btn.setVisible(True)
                self._redo_top_btn.setVisible(True)
                self._undo_top_btn.clicked.connect(edit_w._undo)
                self._redo_top_btn.clicked.connect(edit_w._redo)
            else:
                self.stack.setMinimumWidth(320)
                self.stack.setMaximumWidth(600)
                self._tab_container.setVisible(True)
                self._undo_top_btn.setVisible(False)
                self._redo_top_btn.setVisible(False)
                # Ensure the splitter allocates space for the tool panel
                total = self._splitter.width()
                tool_w = max(380, min(450, total // 3))
                self._splitter.setSizes([total - tool_w, tool_w])
            self._breadcrumb.setText(f"{t('workspace.title')}  ›  {NAV_ITEMS[row][0]}")
            self._try_auto_load(row)

    def _open_pdf(self):
        from PySide6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(
            self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        for path in paths:
            self._load_and_track(path)

    def _load_and_track(self, path: str):
        """Load PDF — opens in new tab if current tab already has a document."""
        if self._viewer.current_path():
            self._add_viewer_tab(path)
        else:
            self._viewer.load(path)
        add_recent_file(path)
        self._refresh_viewer_top_buttons()

    def _open_in_new_tab(self):
        """Open a PDF in a new tab."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if path:
            self._add_viewer_tab(path)
            add_recent_file(path)

    def _show_recent_menu(self):
        menu = QMenu(self)
        recents = get_recent_files()
        if not recents:
            action = menu.addAction(t("recent.empty"))
            action.setEnabled(False)
        else:
            for path in recents:
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
        set_language(code)
        _labels = {"en": "EN", "pt": "PT", "es": "ES", "fr": "FR", "de": "DE", "zh": "ZH", "it": "IT", "nl": "NL"}
        self._lang_btn.setText(_labels.get(code, "EN"))
        ans = QMessageBox.question(
            self, t("lang.selector"), t("lang.restart", lang=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ans == QMessageBox.StandardButton.Yes:
            self._restart_app()

    def _restart_app(self):
        """Restart the application as a fully detached process."""
        import sys
        from PySide6.QtCore import QProcess
        script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pdfapps.py")
        # Pass any PDF arguments that were on the original command line
        args = [script] + [a for a in sys.argv[1:] if a.lower().endswith(".pdf")]
        QProcess.startDetached(sys.executable, args, os.path.dirname(script))
        QApplication.instance().exit(0)

    # ── Drag & drop PDF on window ──────────────────────────────────────────
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            urls = e.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith(".pdf"):
                e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".pdf"):
                self._load_and_track(path)


    def _toggle_night_mode_top(self):
        active = self._night_top_btn.isChecked()
        self._viewer._canvas.set_night_mode(active)

    def _refresh_viewer_top_buttons(self):
        """Show/hide TOC button and sync night btn for the active viewer."""
        try:
            v = self._viewer
            self._toc_top_btn.setVisible(v._toc_tree.topLevelItemCount() > 0)
            self._night_top_btn.setChecked(v._canvas._night_mode)
        except Exception:
            self._toc_top_btn.setVisible(False)
            self._night_top_btn.setChecked(False)

    # ── Keyboard shortcut helpers ────────────────────────────────────────
    def _close_current_tab(self):
        idx = self._tab_bar.currentIndex()
        if idx >= 0:
            self._close_tab(idx)

    def _save_current_tool(self):
        """Ctrl+S: save pipeline result, or run current tool."""
        vid = id(self._viewer)
        ps = self._pipeline_state.get(vid)
        if ps and ps.get("temp_path"):
            self._save_pipeline()
        elif self._current_tool >= 0:
            w = self.stack.widget(self._current_tool)
            if hasattr(w, '_run'):
                w._run()

    # ── Pipeline ─────────────────────────────────────────────────────────
    def _on_pipeline_done(self, temp_path: str):
        """A tool finished in pipeline mode — reload result in viewer."""
        viewer = self._viewer
        vid = id(viewer)
        ps = self._pipeline_state.get(vid)
        if ps is None:
            ps = {"original_path": viewer.current_path(), "temp_path": None}
            self._pipeline_state[vid] = ps
        ps["temp_path"] = temp_path
        # Reload the viewer with the pipeline result
        viewer.load(temp_path)
        # Mark tab as dirty
        idx = self._viewer_stack.currentIndex()
        orig_name = os.path.basename(ps["original_path"])
        self._tab_bar.setTabText(idx, f"● {orig_name}")
        self._sb.showMessage(t("pipeline.applied"))
        # Re-auto-load the current tool so it picks up the new file
        if self._current_tool >= 0:
            w = self.stack.widget(self._current_tool)
            fn = getattr(w, "auto_load", None)
            if callable(fn):
                # Reset drop_in/drop_out so auto_load can set the new path
                # and the next run generates a fresh temp output
                for attr in ("drop_in", "drop_out"):
                    drop = getattr(w, attr, None)
                    if drop:
                        drop.clear()
                fn(temp_path)

    def _save_pipeline(self):
        """Save the current pipeline result to a user-chosen file."""
        import shutil
        vid = id(self._viewer)
        ps = self._pipeline_state.get(vid)
        if not ps or not ps.get("temp_path"):
            return
        orig = ps["original_path"]
        base, ext = os.path.splitext(os.path.basename(orig))
        suggested = os.path.join(os.path.dirname(orig), base + "_edited" + ext)
        path, _ = QFileDialog.getSaveFileName(
            self, t("btn.choose"), suggested, t("file_filter.pdf"))
        if not path:
            return
        shutil.copy2(ps["temp_path"], path)
        # Load the saved file in the viewer (replaces temp)
        self._viewer.load(path)
        idx = self._viewer_stack.currentIndex()
        self._tab_bar.setTabText(idx, os.path.basename(path))
        self._tab_bar.setTabToolTip(idx, path)
        # Cleanup pipeline state
        self._cleanup_pipeline(vid)
        self._sb.showMessage(t("pipeline.saved"))

    def _cleanup_pipeline(self, viewer_id: int):
        """Remove pipeline temp files and state for a viewer."""
        ps = self._pipeline_state.pop(viewer_id, None)
        if not ps:
            return
        # Cleanup temp dirs from all tools
        from app.base import BasePage
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if isinstance(w, BasePage):
                w.cleanup_pipeline()

    def _viewer_has_unsaved(self, viewer=None) -> bool:
        """Check if a viewer has unsaved pipeline changes."""
        v = viewer or self._viewer
        ps = self._pipeline_state.get(id(v))
        return bool(ps and ps.get("temp_path"))

    # ── Fullscreen & Presentation ──────────────────────────────────────────
    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self._workspace_bar.setVisible(False)
            self._sidebar.setVisible(False)
            self._sb.setVisible(False)
            self.showFullScreen()
        else:
            self._workspace_bar.setVisible(True)
            if not self._sidebar_collapsed:
                self._sidebar.setVisible(True)
            self._sb.setVisible(True)
            self.showMaximized()

    def _start_presentation(self):
        viewer = self._viewer
        if not viewer._current_path:
            return
        canvas = viewer._canvas
        sb = viewer._canvas_scroll.verticalScrollBar()
        start_page = canvas.page_at_y(sb.value()) if canvas.page_count() > 0 else 0
        from app.viewer.presentation import PresentationWidget
        self._presentation = PresentationWidget(
            viewer._current_path,
            getattr(viewer, "_pdf_password", ""),
            start_page,
            canvas.page_count(),
        )
        self._presentation.show()

    def closeEvent(self, event):
        """Save layout state on close, prompt for unsaved pipeline changes."""
        # Check for unsaved pipeline changes
        for v in self._viewers:
            if self._viewer_has_unsaved(v):
                ans = QMessageBox.question(
                    self, t("msg.warning"), t("pipeline.unsaved_prompt"),
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel)
                if ans == QMessageBox.StandardButton.Cancel:
                    event.ignore(); return
                if ans == QMessageBox.StandardButton.Save:
                    self._save_pipeline()
                break  # only prompt once
        # Cleanup all pipeline temp files
        for v in list(self._viewers):
            self._cleanup_pipeline(id(v))
        try:
            from app.i18n import _CONFIG_PATH
            import json
            cfg = {}
            try:
                with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass
            cfg["splitter_sizes"] = self._splitter.sizes()
            cfg["sidebar_width"] = self._sidebar.width()
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        except Exception:
            pass
        super().closeEvent(event)

    def _toggle_sidebar(self):
        # Cycle: full → icons-only → hidden → full
        if not self._sidebar_collapsed and self._sidebar.width() > 60:
            # Full → icons-only
            self._sidebar_collapsed = False
            self._sidebar.setFixedWidth(52)
            self._nav_search.setVisible(False)
            self._footer_w.setVisible(False)
            # Hide text from nav items, keep icons
            for r in range(self.nav.count()):
                it = self.nav.item(r)
                idx = it.data(Qt.ItemDataRole.UserRole)
                if idx is not None and idx < 0:
                    it.setHidden(True)  # hide headers & separators
            self._sidebar_toggle_btn.setIcon(self._ico_bars)
        elif not self._sidebar_collapsed:
            # Icons-only → hidden
            self._sidebar_collapsed = True
            self._sidebar.setVisible(False)
            self._sidebar_toggle_btn.setIcon(self._ico_bars)
        else:
            # Hidden → full
            self._sidebar_collapsed = False
            self._sidebar.setVisible(True)
            self._sidebar.setFixedWidth(228)
            self._nav_search.setVisible(True)
            self._footer_w.setVisible(True)
            for r in range(self.nav.count()):
                it = self.nav.item(r)
                idx = it.data(Qt.ItemDataRole.UserRole)
                if idx is not None and idx < 0:
                    it.setHidden(False)
            self._sidebar_toggle_btn.setIcon(self._ico_times)

    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        self._apply_theme()
        # Save preference
        from app.i18n import _CONFIG_PATH
        import json
        cfg = {}
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
        cfg["dark_mode"] = self._dark_mode
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

    def _apply_theme(self):
        style = STYLE if self._dark_mode else STYLE_LIGHT
        nav_color = TEXT_SEC if self._dark_mode else _LQ
        bar_color = TEXT_PRI if self._dark_mode else _LQ
        self._qapp.setPalette(_make_palette(self._dark_mode))
        self._qapp.setStyleSheet(style)
        self._theme_btn.setText("☀" if self._dark_mode else "🌙")
        # Update sidebar nav icons (skip section headers)
        for r in range(self.nav.count()):
            it = self.nav.item(r)
            tool_idx = it.data(Qt.ItemDataRole.UserRole)
            if tool_idx is not None and tool_idx >= 0:
                _, icon_name, _ = _NAV_KEYS[tool_idx]
                it.setIcon(qta.icon(icon_name, color=nav_color))
            else:
                it.setForeground(QColor(nav_color))
        # Update workspace bar icons
        self._ico_bars = qta.icon("fa5s.bars", color=bar_color)
        self._ico_times = qta.icon("fa5s.times", color=bar_color)
        self._sidebar_toggle_btn.setIcon(
            self._ico_bars if self._sidebar_collapsed else self._ico_times)
        self._open_pdf_btn.setIcon(qta.icon("fa5s.folder-open", color=bar_color))
        # (recent button removed)
        self._toc_top_btn.setIcon(qta.icon("fa5s.bookmark", color=bar_color))
        self._night_top_btn.setIcon(qta.icon("fa5s.moon", color=bar_color))
        self._print_top_btn.setIcon(qta.icon("fa5s.print", color=bar_color))
        self._present_btn.setIcon(qta.icon("fa5s.tv", color=bar_color))
        self._undo_top_btn.setIcon(qta.icon("fa5s.undo", color=bar_color))
        self._redo_top_btn.setIcon(qta.icon("fa5s.redo", color=bar_color))
        self._search_top_btn.setIcon(qta.icon("fa5s.search", color=bar_color))
        self._zm_btn.setIcon(qta.icon("fa5s.search-minus", color=bar_color))
        self._zp_btn.setIcon(qta.icon("fa5s.search-plus", color=bar_color))
        self._prev_pg_btn.setIcon(qta.icon("fa5s.chevron-left", color=bar_color))
        self._next_pg_btn.setIcon(qta.icon("fa5s.chevron-right", color=bar_color))
        for v in self._viewers:
            v.update_theme(self._dark_mode)
        # Update all tools that support theme switching
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if hasattr(w, 'update_theme'):
                w.update_theme(self._dark_mode)

    # ── Auto-update ───────────────────────────────────────────────────────

    def _check_for_updates_async(self):
        # Skip auto-update inside Flatpak/Snap (package manager handles updates)
        if os.environ.get("FLATPAK_ID") or os.environ.get("SNAP"):
            return
        from PySide6.QtCore import QThread, QObject, Signal as _Sig

        class _Worker(QObject):
            done = _Sig()
            def __init__(self):
                super().__init__()
                self.release = None
            def run(self):
                from app.updater import check_for_update
                self.release = check_for_update()
                if self.release:
                    self.done.emit()
                self.thread().quit()

        self._update_thread = QThread()
        self._update_worker = _Worker()
        self._update_worker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.done.connect(self._on_update_found)
        self._update_thread.finished.connect(self._update_thread.deleteLater)
        self._update_thread.start()

    def _on_update_found(self):
        self._update_release = self._update_worker.release
        self._notify_update()

    def _notify_update(self):
        """Show update notification dialog automatically."""
        self._update_btn.setVisible(True)
        tag = self._update_release.get("tag_name", "?")
        from PySide6.QtWidgets import QMessageBox
        msg = t("update.available").format(version=tag)
        msg += "\n\n" + t("update.installer_info")
        msg += "\n\n" + t("update.install") + "?"
        reply = QMessageBox.question(
            self, "PDFApps", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._show_update_dialog()

    def _show_update_dialog(self):
        if self._update_release:
            from app.updater import UpdateDialog
            dlg = UpdateDialog(self._update_release, parent=self)
            dlg.exec()
