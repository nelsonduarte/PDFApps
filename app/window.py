"""PDFApps – MainWindow: application main window."""

import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem,
    QStackedWidget, QSplitter, QStatusBar, QFrame,
    QApplication,
)
import qtawesome as qta

from app.constants import ACCENT, TEXT_PRI, TEXT_SEC, _LQ
from app.styles import STYLE, STYLE_LIGHT
from app.utils import resource_path, _make_palette
from app.widgets import DropFileEdit
from app.viewer.panel import PdfViewerPanel
from app.tools.dividir import TabDividir
from app.tools.juntar import TabJuntar
from app.tools.rotar import TabRotar
from app.tools.extrair import TabExtrair
from app.tools.reordenar import TabReordenar
from app.tools.comprimir import TabComprimir
from app.tools.encriptar import TabEncriptar
from app.tools.marca_dagua import TabMarcaDagua
from app.tools.ocr import TabOCR
from app.editor.tab import TabEditar
from app.tools.info import TabInfo


NAV_ITEMS = [
    ("Dividir",         "fa5s.cut",                TabDividir),
    ("Juntar",          "fa5s.object-group",        TabJuntar),
    ("Rodar",           "fa5s.sync-alt",            TabRotar),
    ("Extrair páginas", "fa5s.file-export",         TabExtrair),
    ("Reordenar",       "fa5s.sort",                TabReordenar),
    ("Comprimir",       "fa5s.compress-arrows-alt", TabComprimir),
    ("Encriptar",       "fa5s.lock",                TabEncriptar),
    ("Marca d'água",    "fa5s.stamp",               TabMarcaDagua),
    ("OCR",             "fa5s.search",              TabOCR),
    ("Editar",          "fa5s.edit",                TabEditar),
    ("Informação",      "fa5s.info-circle",         TabInfo),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDFApps")
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
        self._sb.showMessage("Pronto")

        central = QWidget()
        root_v = QVBoxLayout(central)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)

        workspace_bar = QWidget(); workspace_bar.setObjectName("workspace_bar")
        wb_h = QHBoxLayout(workspace_bar)
        wb_h.setContentsMargins(16, 10, 16, 10)
        wb_h.setSpacing(8)

        wb_col = QVBoxLayout(); wb_col.setContentsMargins(0, 0, 0, 0); wb_col.setSpacing(1)
        wb_title = QLabel("Workspace"); wb_title.setObjectName("workspace_title")
        wb_hint = QLabel("Escolhe uma ferramenta na barra lateral ou usa os atalhos rápidos.")
        wb_hint.setObjectName("workspace_hint")
        wb_col.addWidget(wb_title); wb_col.addWidget(wb_hint)
        wb_h.addLayout(wb_col, 1)

        self._quick_merge_btn = QPushButton("Juntar"); self._quick_merge_btn.setObjectName("quick_btn")
        self._quick_ocr_btn = QPushButton("OCR"); self._quick_ocr_btn.setObjectName("quick_btn")
        self._quick_edit_btn = QPushButton("Editar"); self._quick_edit_btn.setObjectName("quick_btn")
        wb_h.addWidget(self._quick_merge_btn)
        wb_h.addWidget(self._quick_ocr_btn)
        wb_h.addWidget(self._quick_edit_btn)

        # zoom widget — só visível na ferramenta Editar
        self._zoom_widget = QWidget()
        zw_h = QHBoxLayout(self._zoom_widget); zw_h.setContentsMargins(0,0,0,0); zw_h.setSpacing(4)
        _zm = QPushButton(); _zm.setIcon(qta.icon("fa5s.search-minus", color=TEXT_PRI))
        _zm.setFixedSize(28, 28); _zm.setObjectName("viewer_nav_btn"); _zm.setToolTip("Diminuir zoom (Ctrl+scroll)")
        self._lbl_zoom = QLabel("100%"); self._lbl_zoom.setMinimumWidth(42); self._lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _zp = QPushButton(); _zp.setIcon(qta.icon("fa5s.search-plus", color=TEXT_PRI))
        _zp.setFixedSize(28, 28); _zp.setObjectName("viewer_nav_btn"); _zp.setToolTip("Aumentar zoom (Ctrl+scroll)")
        _z0 = QPushButton("Repor"); _z0.setObjectName("viewer_nav_btn"); _z0.setFixedHeight(28)
        _z0.setToolTip("Repor zoom 100%")
        zw_h.addWidget(_zm); zw_h.addWidget(self._lbl_zoom); zw_h.addWidget(_zp); zw_h.addWidget(_z0)
        self._zoom_widget.setVisible(False)
        self._zm_btn = _zm; self._zp_btn = _zp; self._z0_btn = _z0
        wb_h.addWidget(self._zoom_widget)

        self._tool_badge = QLabel("Modo: Visualizador"); self._tool_badge.setObjectName("workspace_badge")
        wb_h.addWidget(self._tool_badge)

        self._theme_btn = QPushButton("☀")
        self._theme_btn.setObjectName("theme_btn")
        self._theme_btn.setToolTip("Alternar tema claro/escuro")
        self._theme_btn.setFixedSize(28, 28)
        self._theme_btn.clicked.connect(self._toggle_theme)
        wb_h.addWidget(self._theme_btn)

        root_v.addWidget(workspace_bar)

        body = QWidget(); body.setObjectName("workspace_shell")
        main_h = QHBoxLayout(body)
        main_h.setContentsMargins(10, 10, 10, 8)
        main_h.setSpacing(10)

        # ── Sidebar ──────────────────────────────────────────────────────────
        sidebar = QWidget(); sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(228)
        sb_lay  = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.setSpacing(0)

        brand = QWidget(); brand.setObjectName("brand_area")
        bv = QVBoxLayout(brand); bv.setContentsMargins(0, 0, 0, 0); bv.setSpacing(0)
        ico_lbl = QLabel()
        ico_lbl.setPixmap(qta.icon('fa5s.file-pdf', color=ACCENT).pixmap(28, 28))
        ico_lbl.setObjectName("app_icon")
        ico_lbl.setContentsMargins(16, 0, 0, 0)
        ttl_lbl = QLabel("PDFApps"); ttl_lbl.setObjectName("app_title")
        sub_lbl = QLabel("PDF Editor"); sub_lbl.setObjectName("app_sub")
        bv.addWidget(ico_lbl); bv.addWidget(ttl_lbl); bv.addWidget(sub_lbl)
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

        footer_w = QWidget(); footer_w.setObjectName("sidebar")
        footer_h = QHBoxLayout(footer_w)
        footer_h.setContentsMargins(14, 8, 14, 10); footer_h.setSpacing(0)
        footer_lbl = QLabel("pypdf  +  PySide6"); footer_lbl.setObjectName("sidebar_footer")
        footer_h.addWidget(footer_lbl, 1)
        sb_lay.addWidget(footer_w)
        self._dark_mode = True
        self._qapp: QApplication = QApplication.instance()  # type: ignore[assignment]

        # ── Stack de ferramentas (oculto por defeito) ─────────────────────────
        self.stack = QStackedWidget(); self.stack.setObjectName("content_area")
        for _, __, cls in NAV_ITEMS:
            self.stack.addWidget(cls(self._set_status))
        self.stack.setVisible(False)

        # ── Viewer (ocupa tudo quando nenhuma ferramenta está ativa) ──────────
        self._viewer = PdfViewerPanel()

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(1)
        self._splitter.addWidget(self.stack)
        self._splitter.addWidget(self._viewer)
        self._splitter.setCollapsible(0, True)
        self._splitter.setCollapsible(1, False)

        main_h.addWidget(sidebar)
        main_h.addWidget(self._splitter, 1)
        root_v.addWidget(body, 1)
        self.setCentralWidget(central)

        self._current_tool = -1
        self.nav.itemClicked.connect(self._on_nav_clicked)
        self._quick_merge_btn.clicked.connect(lambda: self._open_tool_by_name("Juntar"))
        self._quick_ocr_btn.clicked.connect(lambda: self._open_tool_by_name("OCR"))
        self._quick_edit_btn.clicked.connect(lambda: self._open_tool_by_name("Editar"))

        # Ligar todos os DropFileEdit ao viewer
        for i in range(self.stack.count()):
            for dfe in self.stack.widget(i).findChildren(DropFileEdit):
                dfe.path_changed.connect(self._viewer.load)

    def _open_tool_by_name(self, tool_name: str):
        for i, (name, _, _) in enumerate(NAV_ITEMS):
            if name == tool_name:
                self.nav.setCurrentRow(i)
                self._current_tool = i
                self.stack.setCurrentIndex(i)
                self.stack.setVisible(True)
                self._viewer.setVisible(False)
                self._tool_badge.setText(f"Modo: {name}")
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

    def _setup_zoom_bar(self, active: bool):
        self._zoom_widget.setVisible(active)
        canvas = getattr(self.stack.widget(self._edit_tool_idx()), '_canvas', None)
        if canvas is None:
            return
        if active:
            self._zm_btn.clicked.connect(canvas.zoom_out)
            self._zp_btn.clicked.connect(canvas.zoom_in)
            self._z0_btn.clicked.connect(canvas.zoom_reset)
            canvas.zoom_changed.connect(lambda pct: self._lbl_zoom.setText(f"{pct}%"))
        else:
            try:
                self._zm_btn.clicked.disconnect(canvas.zoom_out)
                self._zp_btn.clicked.disconnect(canvas.zoom_in)
                self._z0_btn.clicked.disconnect(canvas.zoom_reset)
                canvas.zoom_changed.disconnect()
            except Exception:
                pass

    def _on_nav_clicked(self, item):
        row = self.nav.row(item)
        edit_idx = self._edit_tool_idx()
        if row == self._current_tool:
            self.nav.clearSelection()
            self._current_tool = -1
            self.stack.setVisible(False)
            self._viewer.setVisible(True)
            self._tool_badge.setText("Modo: Visualizador")
            self._setup_zoom_bar(False)
        else:
            if self._current_tool == edit_idx:
                self._setup_zoom_bar(False)
            self._current_tool = row
            self.stack.setCurrentIndex(row)
            self.stack.setVisible(True)
            self._viewer.setVisible(False)
            self._tool_badge.setText(f"Modo: {NAV_ITEMS[row][0]}")
            self._try_auto_load(row)
            if row == edit_idx:
                self._setup_zoom_bar(True)

    def _set_status(self, msg: str):
        self._sb.showMessage(msg)

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
