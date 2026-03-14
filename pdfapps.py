"""
PDFApps  –  PySide6 + pypdf
pip install PySide6 pypdf
"""
import os
import sys


def resource_path(rel):
    """Retorna o caminho correto tanto em dev como no exe PyInstaller."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

from PySide6.QtCore import Qt, Signal, QPointF, QSize, QEvent
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QPalette, QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QStackedWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QScrollArea,
    QLabel, QLineEdit, QPushButton, QSpinBox, QComboBox,
    QListWidget, QListWidgetItem, QAbstractItemView,
    QFileDialog, QMessageBox, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame, QStatusBar, QSplitter,
    QDialog,
)
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
import qtawesome as qta

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    QApplication(sys.argv)
    QMessageBox.critical(None, "Dependência em falta",
                         "Instala a biblioteca pypdf:\n\npip install pypdf")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
#  Design system  —  tema escuro moderno
# ══════════════════════════════════════════════════════════════════════════════

ACCENT   = "#3B82F6"   # azul
ACCENT_H = "#2563EB"   # hover
ACCENT_P = "#1D4ED8"   # pressed
BG_BASE  = "#111827"   # fundo global
BG_SIDE  = "#0D1117"   # sidebar
BG_CARD  = "#1E2438"   # cards / tool header
BG_INPUT = "#242B42"   # inputs
BG_INNER = "#161D2E"   # scroll area
BORDER   = "#2E3650"   # bordas
TEXT_PRI = "#F0F4FF"   # texto primário
TEXT_SEC = "#94A3B8"   # texto secundário

STYLE = f"""
/* ── Globals ─────────────────────────────────────────────────────────── */
QMainWindow {{ background: {BG_BASE}; }}
QWidget     {{ background: transparent; color: {TEXT_PRI};
              font-family: 'Segoe UI', Arial, sans-serif; font-size: 12pt; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ── Sidebar ─────────────────────────────────────────────────────────── */
#sidebar    {{ background: {BG_SIDE}; border-right: 1px solid {BORDER}; }}
#brand_area {{ background: {BG_SIDE}; padding: 20px 0 12px 0; }}

#app_title {{ font-size: 15pt; font-weight: 700; color: #FFFFFF;
             background: transparent; padding: 0 16px 2px 16px; }}
#app_sub   {{ font-size: 10pt; color: #6B7FA3;
             background: transparent; padding: 0 16px 14px 16px; }}

#nav_sep   {{ background: {BORDER}; max-height: 1px; margin: 4px 12px 8px 12px; }}

#nav_list  {{ background: transparent; border: none; outline: none;
             color: #A8B4CC; font-size: 11pt; }}
#nav_list::item          {{ padding: 10px 14px; margin: 2px 8px; border-radius: 6px; }}
#nav_list::item:hover    {{ background: #1E2235; color: {TEXT_PRI}; }}
#nav_list::item:selected {{ background: {ACCENT}; color: #FFFFFF; font-weight: 600; }}

#sidebar_footer {{ background: transparent; color: #4A5C7A;
                  font-size: 9pt; padding: 10px 16px; }}

/* ── Tool header ─────────────────────────────────────────────────────── */
#tool_header  {{ background: {BG_CARD}; border-bottom: 1px solid {BORDER};
                min-height: 68px; padding: 0 24px; }}
#th_title     {{ font-size: 15pt; font-weight: 700; background: transparent;
                color: {TEXT_PRI}; }}
#th_desc      {{ font-size: 11pt; background: transparent; color: #8899BB; }}

/* ── Scroll inner ────────────────────────────────────────────────────── */
#scroll_inner {{ background: {BG_INNER}; }}

/* ── Action bar ──────────────────────────────────────────────────────── */
#action_bar   {{ background: {BG_CARD}; border-top: 1px solid {BORDER}; }}

/* ── Primary button ──────────────────────────────────────────────────── */
#btn_primary {{
    background: {ACCENT}; color: #FFFFFF; border: none;
    border-radius: 6px; font-size: 12pt; font-weight: 600;
    padding: 10px 28px; min-height: 42px;
}}
#btn_primary:hover   {{ background: {ACCENT_H}; }}
#btn_primary:pressed {{ background: {ACCENT_P}; }}
#btn_primary:disabled {{ background: #1E2D4A; color: #4A5568; }}

/* ── Secondary buttons ───────────────────────────────────────────────── */
QPushButton {{
    background: #1E2235; border: 1px solid {BORDER};
    border-radius: 6px; padding: 7px 16px; color: {TEXT_PRI}; font-size: 11pt;
}}
QPushButton:hover   {{ background: #252B40; border-color: #3B4460; color: #FFFFFF; }}
QPushButton:pressed {{ background: #161B2C; }}

#btn_danger {{
    background: #1A1020; color: #F87171; font-size: 11pt;
    border: 1px solid #3D1F1F; border-radius: 6px; padding: 7px 16px;
}}
#btn_danger:hover {{ background: #2D1515; color: #FCA5A5; border-color: #6B2222; }}

/* ── Section labels ──────────────────────────────────────────────────── */
#section_lbl {{
    font-size: 9pt; font-weight: 700; color: {TEXT_SEC};
    background: transparent; padding: 12px 0 4px 0;
    letter-spacing: 1px;
}}

/* ── Cards (GroupBox) ────────────────────────────────────────────────── */
QGroupBox {{
    background: {BG_CARD}; border: 1px solid {BORDER};
    border-radius: 8px; margin-top: 20px;
    padding: 16px 14px 12px 14px;
    font-size: 10pt; font-weight: 600; color: #A8B8D0;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 2px 8px; left: 14px; top: -1px;
    background: {BG_CARD}; color: #B8C8E0;
}}
QGroupBox QWidget  {{ background: transparent; }}
QGroupBox QLabel   {{ background: transparent; }}
QGroupBox QLineEdit, QGroupBox QSpinBox,
QGroupBox QComboBox {{ background: {BG_INPUT}; }}

/* ── Inputs ──────────────────────────────────────────────────────────── */
QLineEdit, QSpinBox, QComboBox {{
    background: {BG_INPUT}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 8px 12px; color: {TEXT_PRI};
    font-size: 11pt; min-height: 22px;
}}
QLineEdit:focus, QSpinBox:focus {{
    border: 1px solid {ACCENT}; background: #202640;
}}
QLineEdit[readOnly="true"] {{ background: {BG_CARD}; color: {TEXT_SEC}; }}

QComboBox::drop-down       {{ border: none; width: 26px; }}
QComboBox::down-arrow      {{ width: 11px; }}
QComboBox QAbstractItemView {{
    background: {BG_INPUT}; border: 1px solid {BORDER};
    border-radius: 6px; color: {TEXT_PRI}; font-size: 11pt;
    selection-background-color: {ACCENT}; selection-color: white;
}}

QTextEdit {{
    background: {BG_SIDE}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 12px; color: #C8D5E8; font-size: 11pt;
}}

/* ── Drop zone ───────────────────────────────────────────────────────── */
#drop_zone {{
    background: {BG_CARD}; border: 1px dashed {BORDER};
    border-radius: 8px; min-height: 60px;
}}
#drop_zone[drag_active="true"] {{
    background: #0F1D3A; border: 1px dashed {ACCENT};
}}
#drop_zone_lbl {{ font-size: 11pt; color: {TEXT_SEC}; background: transparent; }}
#drop_zone_lbl[has_file="true"] {{ color: {TEXT_PRI}; font-weight: 600; }}
#drop_clear {{
    background: transparent; border: none; color: {TEXT_SEC};
    font-size: 14pt; padding: 0 4px; min-width: 0;
}}
#drop_clear:hover {{ color: #F87171; border: none; }}

/* ── Lists & Tables ──────────────────────────────────────────────────── */
QListWidget, QTableWidget {{
    background: {BG_CARD}; border: 1px solid {BORDER};
    border-radius: 8px; outline: none; font-size: 11pt;
    alternate-background-color: #1E2338; color: {TEXT_PRI};
}}
QListWidget::item          {{ padding: 9px 14px; margin: 0; border-radius: 4px; }}
QListWidget::item:selected {{ background: {ACCENT}; color: #FFFFFF; }}
QListWidget::item:hover    {{ background: #252B40; }}
QTableWidget::item:selected {{ background: {ACCENT}; color: #FFFFFF; }}
QHeaderView::section {{
    background: {BG_CARD}; border: none;
    border-bottom: 1px solid {BORDER};
    padding: 8px 12px; font-weight: 700;
    color: {TEXT_SEC}; font-size: 10pt;
}}
QTableWidget {{ gridline-color: {BORDER}; }}

/* ── Scrollbars ──────────────────────────────────────────────────────── */
QScrollBar:vertical   {{ width: 6px; background: transparent; margin: 0; border: none; }}
QScrollBar:horizontal {{ height: 6px; background: transparent; margin: 0; border: none; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: #2D3748; border-radius: 3px; min-height: 20px;
}}
QScrollBar::handle:vertical:hover,
QScrollBar::handle:horizontal:hover {{ background: #4A5568; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ── Info label ──────────────────────────────────────────────────────── */
#info_lbl {{ color: {TEXT_SEC}; font-size: 10pt; background: transparent;
            padding: 2px 4px; }}

/* ── Status bar ──────────────────────────────────────────────────────── */
QStatusBar {{ background: {BG_SIDE}; border-top: 1px solid {BORDER};
             color: #8899BB; font-size: 10pt; padding: 4px 14px; }}

/* ── PDF Viewer panel ────────────────────────────────────────────────── */
#viewer_panel  {{ background: {BG_SIDE}; border-left: 1px solid {BORDER}; }}
#viewer_header {{ background: {BG_CARD}; border-bottom: 1px solid {BORDER}; }}
#viewer_title  {{ font-size: 10pt; font-weight: 600; color: {TEXT_PRI};
                 background: transparent; }}
#viewer_page_lbl {{ font-size: 10pt; color: {TEXT_SEC}; background: transparent;
                   min-width: 54px; }}
#viewer_nav_btn  {{ background: #1E2235; border: 1px solid {BORDER};
                   border-radius: 6px; color: {TEXT_PRI};
                   min-width: 30px; min-height: 30px; padding: 0; }}
#viewer_nav_btn:hover   {{ background: {ACCENT}; border-color: {ACCENT}; }}
#viewer_nav_btn:pressed {{ background: {ACCENT_P}; }}
#viewer_nav_btn:disabled {{ background: #141827; border-color: #1E2235; }}
#viewer_placeholder {{ font-size: 12pt; color: #4A5C7A; background: {BG_SIDE}; }}
QPdfView {{ background: {BG_INNER}; border: none; }}
QSplitter::handle {{ background: {BORDER}; width: 1px; }}
"""

# ── Tema claro ────────────────────────────────────────────────────────────────
_LA = "#3B82F6"; _LAH = "#2563EB"; _LAP = "#1D4ED8"
_LB = "#F8FAFC"; _LS = "#EEF2F7"; _LC = "#FFFFFF"
_LI = "#F1F5F9"; _LN = "#F5F7FA"; _LO = "#CBD5E1"
_LP = "#1E293B"; _LQ = "#64748B"

STYLE_LIGHT = f"""
QMainWindow {{ background: {_LB}; }}
QWidget     {{ background: transparent; color: {_LP};
              font-family: 'Segoe UI', Arial, sans-serif; font-size: 12pt; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

#sidebar    {{ background: {_LS}; border-right: 1px solid {_LO}; }}
#brand_area {{ background: {_LS}; padding: 20px 0 12px 0; }}
#app_title  {{ font-size: 15pt; font-weight: 700; color: {_LP};
              background: transparent; padding: 0 16px 2px 16px; }}
#app_sub    {{ font-size: 10pt; color: {_LQ};
              background: transparent; padding: 0 16px 14px 16px; }}
#nav_sep    {{ background: {_LO}; max-height: 1px; margin: 4px 12px 8px 12px; }}
#nav_list   {{ background: transparent; border: none; outline: none;
              color: {_LQ}; font-size: 11pt; }}
#nav_list::item          {{ padding: 10px 14px; margin: 2px 8px; border-radius: 6px; }}
#nav_list::item:hover    {{ background: #DDE6F0; color: {_LP}; }}
#nav_list::item:selected {{ background: {_LA}; color: #FFFFFF; font-weight: 600; }}
#sidebar_footer {{ background: transparent; color: {_LQ};
                  font-size: 9pt; padding: 10px 16px; }}

#tool_header  {{ background: {_LC}; border-bottom: 1px solid {_LO};
                min-height: 68px; padding: 0 24px; }}
#th_title     {{ font-size: 15pt; font-weight: 700; background: transparent; color: {_LP}; }}
#th_desc      {{ font-size: 11pt; background: transparent; color: {_LQ}; }}

#scroll_inner {{ background: {_LN}; }}
#action_bar   {{ background: {_LC}; border-top: 1px solid {_LO}; }}

#btn_primary {{
    background: {_LA}; color: #FFFFFF; border: none;
    border-radius: 6px; font-size: 12pt; font-weight: 600;
    padding: 10px 28px; min-height: 42px;
}}
#btn_primary:hover   {{ background: {_LAH}; }}
#btn_primary:pressed {{ background: {_LAP}; }}
#btn_primary:disabled {{ background: #CBD5E1; color: #94A3B8; }}

QPushButton {{
    background: {_LC}; border: 1px solid {_LO};
    border-radius: 6px; padding: 7px 16px; color: {_LP}; font-size: 11pt;
}}
QPushButton:hover   {{ background: #EEF2F7; border-color: #94A3B8; color: {_LP}; }}
QPushButton:pressed {{ background: #DDE6F0; }}

#btn_danger {{
    background: #FEF2F2; color: #DC2626; font-size: 11pt;
    border: 1px solid #FECACA; border-radius: 6px; padding: 7px 16px;
}}
#btn_danger:hover {{ background: #FEE2E2; color: #B91C1C; border-color: #FCA5A5; }}

#section_lbl {{
    font-size: 9pt; font-weight: 700; color: {_LQ};
    background: transparent; padding: 12px 0 4px 0; letter-spacing: 1px;
}}

QGroupBox {{
    background: {_LC}; border: 1px solid {_LO};
    border-radius: 8px; margin-top: 20px; padding: 16px 14px 12px 14px;
    font-size: 10pt; font-weight: 600; color: {_LQ};
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 2px 8px; left: 14px; top: -1px;
    background: {_LC}; color: {_LQ};
}}
QGroupBox QWidget  {{ background: transparent; }}
QGroupBox QLabel   {{ background: transparent; }}
QGroupBox QLineEdit, QGroupBox QSpinBox,
QGroupBox QComboBox {{ background: {_LI}; }}

QLineEdit, QSpinBox, QComboBox {{
    background: {_LI}; border: 1px solid {_LO};
    border-radius: 6px; padding: 8px 12px; color: {_LP};
    font-size: 11pt; min-height: 22px;
}}
QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {_LA}; background: #EBF2FF; }}
QLineEdit[readOnly="true"] {{ background: {_LC}; color: {_LQ}; }}

QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ width: 11px; }}
QComboBox QAbstractItemView {{
    background: {_LC}; border: 1px solid {_LO};
    border-radius: 6px; color: {_LP}; font-size: 11pt;
    selection-background-color: {_LA}; selection-color: white;
}}

QTextEdit {{
    background: {_LC}; border: 1px solid {_LO};
    border-radius: 8px; padding: 12px; color: {_LP}; font-size: 11pt;
}}

#drop_zone {{
    background: {_LC}; border: 1px dashed {_LO};
    border-radius: 8px; min-height: 60px;
}}
#drop_zone[drag_active="true"] {{ background: #EBF2FF; border: 1px dashed {_LA}; }}
#drop_zone_lbl {{ font-size: 11pt; color: {_LQ}; background: transparent; }}
#drop_zone_lbl[has_file="true"] {{ color: {_LP}; font-weight: 600; }}
#drop_clear {{
    background: transparent; border: none; color: {_LQ};
    font-size: 14pt; padding: 0 4px; min-width: 0;
}}
#drop_clear:hover {{ color: #DC2626; border: none; }}

QListWidget, QTableWidget {{
    background: {_LC}; border: 1px solid {_LO};
    border-radius: 8px; outline: none; font-size: 11pt;
    alternate-background-color: {_LN}; color: {_LP};
}}
QListWidget::item          {{ padding: 9px 14px; margin: 0; border-radius: 4px; }}
QListWidget::item:selected {{ background: {_LA}; color: #FFFFFF; }}
QListWidget::item:hover    {{ background: #DDE6F0; }}
QTableWidget::item:selected {{ background: {_LA}; color: #FFFFFF; }}
QHeaderView::section {{
    background: {_LC}; border: none; border-bottom: 1px solid {_LO};
    padding: 8px 12px; font-weight: 700; color: {_LQ}; font-size: 10pt;
}}
QTableWidget {{ gridline-color: {_LO}; }}

QScrollBar:vertical   {{ width: 6px; background: transparent; margin: 0; border: none; }}
QScrollBar:horizontal {{ height: 6px; background: transparent; margin: 0; border: none; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {_LO}; border-radius: 3px; min-height: 20px;
}}
QScrollBar::handle:vertical:hover,
QScrollBar::handle:horizontal:hover {{ background: #94A3B8; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

#info_lbl {{ color: {_LQ}; font-size: 10pt; background: transparent; padding: 2px 4px; }}

QStatusBar {{ background: {_LS}; border-top: 1px solid {_LO};
             color: {_LQ}; font-size: 10pt; padding: 4px 14px; }}

#viewer_panel  {{ background: {_LN}; border-left: 1px solid {_LO}; }}
#viewer_header {{ background: {_LC}; border-bottom: 1px solid {_LO}; }}
#viewer_title  {{ font-size: 10pt; font-weight: 600; color: {_LP}; background: transparent; }}
#viewer_page_lbl {{ font-size: 10pt; color: {_LQ}; background: transparent; min-width: 54px; }}
#viewer_nav_btn  {{ background: {_LI}; border: 1px solid {_LO};
                   border-radius: 6px; color: {_LP};
                   min-width: 30px; min-height: 30px; padding: 0; }}
#viewer_nav_btn:hover   {{ background: {_LA}; border-color: {_LA}; color: white; }}
#viewer_nav_btn:pressed {{ background: {_LAP}; }}
#viewer_nav_btn:disabled {{ background: {_LN}; border-color: {_LO}; color: {_LO}; }}
#viewer_placeholder {{ font-size: 12pt; color: {_LQ}; background: {_LN}; }}
QPdfView {{ background: {_LN}; border: none; }}
QSplitter::handle {{ background: {_LO}; width: 1px; }}

#theme_btn {{
    background: transparent; border: none; font-size: 16pt;
    padding: 0; min-width: 28px; max-width: 28px;
}}
#theme_btn:hover {{ background: transparent; border: none; }}
"""


def _make_palette(dark: bool) -> QPalette:
    p = QPalette()
    if dark:
        p.setColor(QPalette.ColorRole.Window,          QColor(BG_BASE))
        p.setColor(QPalette.ColorRole.WindowText,      QColor(TEXT_PRI))
        p.setColor(QPalette.ColorRole.Base,            QColor(BG_INPUT))
        p.setColor(QPalette.ColorRole.AlternateBase,   QColor(BG_CARD))
        p.setColor(QPalette.ColorRole.Text,            QColor(TEXT_PRI))
        p.setColor(QPalette.ColorRole.Button,          QColor("#1E2235"))
        p.setColor(QPalette.ColorRole.ButtonText,      QColor(TEXT_PRI))
        p.setColor(QPalette.ColorRole.Highlight,       QColor(ACCENT))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    else:
        p.setColor(QPalette.ColorRole.Window,          QColor(_LB))
        p.setColor(QPalette.ColorRole.WindowText,      QColor(_LP))
        p.setColor(QPalette.ColorRole.Base,            QColor(_LI))
        p.setColor(QPalette.ColorRole.AlternateBase,   QColor(_LN))
        p.setColor(QPalette.ColorRole.Text,            QColor(_LP))
        p.setColor(QPalette.ColorRole.Button,          QColor(_LC))
        p.setColor(QPalette.ColorRole.ButtonText,      QColor(_LP))
        p.setColor(QPalette.ColorRole.Highlight,       QColor(_LA))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    return p


# ══════════════════════════════════════════════════════════════════════════════
#  Widget reutilizáveis
# ══════════════════════════════════════════════════════════════════════════════

class DropFileEdit(QWidget):
    """Campo de ficheiro com drag & drop, ícone de estado e botão de limpar."""

    path_changed = Signal(str)

    def __init__(self, placeholder="Arrasta o ficheiro PDF aqui ou usa o botão →",
                 filters="Ficheiros PDF (*.pdf);;Todos (*.*)",
                 save=False, default_name="resultado.pdf"):
        super().__init__()
        self._filters    = filters
        self._save       = save
        self._default    = default_name
        self._path_value = ""
        self.setAcceptDrops(True)
        self.setObjectName("drop_zone")

        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 10, 10)
        h.setSpacing(10)

        self._ico = QLabel()
        self._ico.setPixmap(qta.icon('fa5s.cloud-upload-alt', color='#4A5568').pixmap(20, 20))
        self._ico.setObjectName("drop_icon")
        self._ico.setFixedWidth(26)
        h.addWidget(self._ico)

        self._lbl = QLabel(placeholder)
        self._lbl.setObjectName("drop_zone_lbl")
        self._lbl.setWordWrap(True)
        h.addWidget(self._lbl, 1)

        self._clr = QPushButton()
        self._clr.setIcon(qta.icon('fa5s.times', color='#4A5568'))
        self._clr.setObjectName("drop_clear")
        self._clr.setFixedSize(24, 24)
        self._clr.setVisible(False)
        self._clr.clicked.connect(self.clear)
        h.addWidget(self._clr)

        self.btn = QPushButton("Guardar como…" if save else "  Abrir…  ")
        self.btn.setFixedWidth(140 if save else 110)
        self.btn.clicked.connect(self._browse)
        h.addWidget(self.btn)

    # ── API ─────────────────────────────────────────────────────────────────
    def path(self) -> str:
        return self._path_value

    def set_path(self, p: str):
        self._path_value = p
        name = os.path.basename(p)
        self._lbl.setText(f"  {name}")
        self.path_changed.emit(p)
        self._lbl.setToolTip(p)
        self._lbl.setProperty("has_file", "true")
        self._ico.setPixmap(qta.icon('fa5s.file-pdf', color=ACCENT).pixmap(20, 20))
        self._ico.setProperty("has_file", "true")
        self._clr.setIcon(qta.icon('fa5s.times', color='#F87171'))
        self._clr.setVisible(True)
        for w in (self._lbl, self._ico):
            w.style().unpolish(w); w.style().polish(w)

    def clear(self):
        self._path_value = ""
        self._lbl.setText("Arrasta o ficheiro PDF aqui ou usa o botão →")
        self._lbl.setToolTip("")
        self._lbl.setProperty("has_file", "false")
        self._ico.setPixmap(qta.icon('fa5s.cloud-upload-alt', color='#4A5568').pixmap(20, 20))
        self._ico.setProperty("has_file", "false")
        self._clr.setIcon(qta.icon('fa5s.times', color='#4A5568'))
        self._clr.setVisible(False)
        for w in (self._lbl, self._ico):
            w.style().unpolish(w); w.style().polish(w)

    # ── drag & drop ─────────────────────────────────────────────────────────
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.setProperty("drag_active", "true")
            self.style().unpolish(self); self.style().polish(self)

    def dragLeaveEvent(self, _):
        self.setProperty("drag_active", "false")
        self.style().unpolish(self); self.style().polish(self)

    def dropEvent(self, e: QDropEvent):
        self.setProperty("drag_active", "false")
        self.style().unpolish(self); self.style().polish(self)
        urls = e.mimeData().urls()
        if urls:
            self.set_path(urls[0].toLocalFile())

    def _browse(self):
        if self._save:
            p, _ = QFileDialog.getSaveFileName(self, "Guardar como", self._default, self._filters)
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Abrir ficheiro", "", self._filters)
        if p:
            self.set_path(p)


class MultiDropWidget(QWidget):
    """Zona de drop para múltiplos PDFs."""

    def __init__(self, on_drop_callback):
        super().__init__()
        self._cb = on_drop_callback
        self.setAcceptDrops(True)
        self.setObjectName("drop_zone")
        self.setMinimumHeight(48)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 10, 10)
        h.setSpacing(10)
        lbl = QLabel()
        lbl.setPixmap(qta.icon('fa5s.folder-open', color='#4A5568').pixmap(20, 20))
        lbl.setObjectName("drop_icon")
        lbl.setFixedWidth(26)
        h.addWidget(lbl)
        self._lbl = QLabel("Arrasta vários PDFs aqui  ou  usa o botão →")
        self._lbl.setObjectName("drop_zone_lbl")
        h.addWidget(self._lbl, 1)
        self.btn = QPushButton("  Adicionar…  ")
        self.btn.setFixedWidth(110)
        h.addWidget(self.btn)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.setProperty("drag_active", "true")
            self.style().unpolish(self); self.style().polish(self)

    def dragLeaveEvent(self, _):
        self.setProperty("drag_active", "false")
        self.style().unpolish(self); self.style().polish(self)

    def dropEvent(self, e: QDropEvent):
        self.setProperty("drag_active", "false")
        self.style().unpolish(self); self.style().polish(self)
        paths = [u.toLocalFile() for u in e.mimeData().urls()
                 if u.toLocalFile().lower().endswith(".pdf")]
        if paths:
            self._cb(paths)


def ToolHeader(icon_name: str, title: str, desc: str) -> QWidget:
    """Cabeçalho fixo no topo de cada ferramenta."""
    w = QWidget(); w.setObjectName("tool_header")
    h = QHBoxLayout(w); h.setContentsMargins(24, 14, 24, 14); h.setSpacing(16)
    ico = QLabel()
    ico.setPixmap(qta.icon(icon_name, color=ACCENT).pixmap(30, 30))
    ico.setObjectName("th_icon"); ico.setFixedSize(38, 38)
    col = QVBoxLayout(); col.setSpacing(3)
    t = QLabel(title); t.setObjectName("th_title")
    d = QLabel(desc);  d.setObjectName("th_desc")
    col.addWidget(t); col.addWidget(d)
    h.addWidget(ico); h.addLayout(col); h.addStretch()
    return w


def ActionBar(btn_text: str, slot) -> tuple[QWidget, QPushButton]:
    """Barra inferior com botão de acção principal."""
    bar = QWidget(); bar.setObjectName("action_bar")
    h = QHBoxLayout(bar); h.setContentsMargins(20, 12, 20, 12)
    h.addStretch()
    btn = QPushButton(btn_text); btn.setObjectName("btn_primary")
    btn.setMinimumWidth(200); btn.setFixedHeight(42)
    btn.clicked.connect(slot)
    h.addWidget(btn)
    return bar, btn


def section(text: str) -> QLabel:
    lbl = QLabel(text.upper()); lbl.setObjectName("section_lbl")
    return lbl


def info_lbl() -> QLabel:
    lbl = QLabel(""); lbl.setObjectName("info_lbl")
    return lbl


def primary_btn(text: str) -> QPushButton:
    b = QPushButton(text); b.setObjectName("btn_primary")
    b.setFixedHeight(38); return b


def danger_btn(text: str) -> QPushButton:
    b = QPushButton(text); b.setObjectName("btn_danger"); return b


def scrolled(widget: QWidget) -> QScrollArea:
    sa = QScrollArea(); sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame); sa.setWidget(widget)
    return sa


def parse_pages(text: str, total: int) -> list[int]:
    pages: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part: continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a) - 1, int(b)))
        else:
            pages.append(int(part) - 1)
    invalid = [p for p in pages if p < 0 or p >= total]
    if invalid:
        raise ValueError(f"Páginas fora do intervalo: {[p+1 for p in invalid]}  (total: {total})")
    return pages


def pick_pdfs(parent: QWidget) -> list[str]:
    paths, _ = QFileDialog.getOpenFileNames(
        parent, "Selecionar PDFs", "", "PDF (*.pdf);;Todos (*.*)")
    return paths


def pick_folder(parent: QWidget) -> str:
    return QFileDialog.getExistingDirectory(parent, "Selecionar pasta")


def _paint_bg(widget: QWidget) -> None:
    """Faz QWidget subclasses honrarem 'background:' no stylesheet."""
    from PySide6.QtWidgets import QStyleOption, QStyle
    opt = QStyleOption()
    opt.initFrom(widget)
    p = QPainter(widget)
    widget.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, p, widget)


# ══════════════════════════════════════════════════════════════════════════════
#  Página base
# ══════════════════════════════════════════════════════════════════════════════

class BasePage(QWidget):
    """Estrutura padrão: header fixo + scroll area + action bar."""

    def __init__(self, icon, title, desc, action_text, status_fn):
        super().__init__()
        self._status = status_fn
        self.setObjectName("content_area")

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        page_layout.addWidget(ToolHeader(icon, title, desc))

        # conteúdo scrollável
        self._inner = QWidget(); self._inner.setObjectName("scroll_inner")
        self._form  = QVBoxLayout(self._inner)
        self._form.setContentsMargins(24, 20, 24, 20)
        self._form.setSpacing(10)
        page_layout.addWidget(scrolled(self._inner), 1)

        # barra de acção fixa
        self._action_bar, self.action_btn = ActionBar(action_text, self._run)
        page_layout.addWidget(self._action_bar)

    def paintEvent(self, event):
        _paint_bg(self)

    def _build(self):
        """Subclasses adicionam widgets ao self._form aqui."""

    def _run(self):
        """Lógica principal chamada pelo botão de acção."""


# ══════════════════════════════════════════════════════════════════════════════
#  Ferramenta 1 – Dividir
# ══════════════════════════════════════════════════════════════════════════════

class TabDividir(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.cut", "Dividir PDF",
                         "Corta o PDF em vários ficheiros por intervalos de páginas.",
                         "Dividir PDF", status_fn)
        self._total = 0
        f = self._form

        f.addWidget(section("Ficheiro de origem"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in)
        f.addWidget(self.lbl_info)

        grp = QGroupBox("Intervalos de páginas")
        vt  = QVBoxLayout(grp); vt.setSpacing(8)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Início", "Fim", "Nome do ficheiro de saída"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setFixedHeight(160)
        vt.addWidget(self.table)
        hb = QHBoxLayout()
        btn_add = QPushButton("＋  Adicionar linha")
        btn_rem = danger_btn("−  Remover")
        btn_add.clicked.connect(self._add_row)
        btn_rem.clicked.connect(self._remove_row)
        hb.addWidget(btn_add); hb.addWidget(btn_rem); hb.addStretch()
        vt.addLayout(hb)
        f.addWidget(grp)

        f.addWidget(section("Pasta de saída"))
        self.drop_out = DropFileEdit("Pasta onde serão guardados os ficheiros…")
        self.drop_out.btn.setText("Escolher…")
        self.drop_out.btn.clicked.disconnect()
        self.drop_out.btn.clicked.connect(self._pick_output)
        f.addWidget(self.drop_out)
        f.addStretch()
        self._add_row()

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if not p: return
        self.drop_in.set_path(p)
        if not self.drop_out.path(): self.drop_out.set_path(os.path.dirname(p))
        try:
            r = PdfReader(p); self._total = len(r.pages)
            self.lbl_info.setText(f"  {self._total} páginas no ficheiro")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def _pick_output(self):
        d = pick_folder(self)
        if d: self.drop_out.set_path(d)

    def _add_row(self):
        r = self.table.rowCount(); self.table.insertRow(r)
        spn_s = QSpinBox(); spn_s.setRange(1, 9999); spn_s.setValue(1)
        spn_e = QSpinBox(); spn_e.setRange(1, 9999); spn_e.setValue(max(1, self._total))
        self.table.setCellWidget(r, 0, spn_s)
        self.table.setCellWidget(r, 1, spn_e)
        self.table.setItem(r, 2, QTableWidgetItem(f"parte_{r+1}.pdf"))

    def _remove_row(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def _run(self):
        pdf_path = self.drop_in.path(); out_dir = self.drop_out.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona um PDF válido."); return
        if not out_dir:
            QMessageBox.warning(self, "Aviso", "Escolhe a pasta de saída."); return
        try:
            reader = PdfReader(pdf_path); total = len(reader.pages)
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e)); return
        os.makedirs(out_dir, exist_ok=True)
        erros, gerados = [], []
        for r in range(self.table.rowCount()):
            start = self.table.cellWidget(r, 0).value()
            end   = self.table.cellWidget(r, 1).value()
            name  = self.table.item(r, 2).text().strip() or f"parte_{r+1}.pdf"
            if not name.lower().endswith(".pdf"): name += ".pdf"
            if start < 1 or end < start or end > total:
                erros.append(f"Linha {r+1}: {start}–{end} inválido"); continue
            w = PdfWriter()
            for p in range(start - 1, end): w.add_page(reader.pages[p])
            with open(os.path.join(out_dir, name), "wb") as f: w.write(f)
            gerados.append(name)
        if erros: QMessageBox.warning(self, "Aviso", "Ignorados:\n" + "\n".join(erros))
        if gerados:
            self._status(f"✔  {len(gerados)} ficheiro(s) criado(s) em {out_dir}")
            QMessageBox.information(self, "Concluído",
                f"{len(gerados)} ficheiro(s) criado(s) em:\n{out_dir}\n\n" + "\n".join(gerados))


# ══════════════════════════════════════════════════════════════════════════════
#  Ferramenta 2 – Juntar
# ══════════════════════════════════════════════════════════════════════════════

class TabJuntar(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.object-group", "Juntar PDFs",
                         "Combina vários ficheiros PDF numa única documento.",
                         "Juntar PDFs", status_fn)
        f = self._form

        grp = QGroupBox("PDFs a juntar  (arrasta para reordenar)")
        vl  = QVBoxLayout(grp); vl.setSpacing(8)
        self.drop_multi = MultiDropWidget(self._on_drop)
        self.drop_multi.btn.clicked.connect(self._add_files)
        vl.addWidget(self.drop_multi)
        self.lst = QListWidget()
        self.lst.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.lst.setAlternatingRowColors(True)
        self.lst.setMinimumHeight(180)
        vl.addWidget(self.lst)
        hb = QHBoxLayout()
        for txt, slot in [("▲ Subir", self._up), ("▼ Descer", self._dn),
                          ("−  Remover", self._remove), ("Limpar", self.lst.clear)]:
            btn = danger_btn(txt) if "Remover" in txt else QPushButton(txt)
            btn.clicked.connect(slot); hb.addWidget(btn)
        hb.addStretch(); vl.addLayout(hb)
        f.addWidget(grp)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit("juntado.pdf", save=True, default_name="juntado.pdf")
        f.addWidget(self.drop_out)
        f.addStretch()

    def _on_drop(self, paths: list[str]):
        for p in paths: self.lst.addItem(QListWidgetItem(p))

    def _add_files(self):
        for p in pick_pdfs(self): self.lst.addItem(QListWidgetItem(p))

    def _up(self):
        r = self.lst.currentRow()
        if r > 0:
            item = self.lst.takeItem(r); self.lst.insertItem(r-1, item)
            self.lst.setCurrentRow(r-1)

    def _dn(self):
        r = self.lst.currentRow()
        if r < self.lst.count()-1:
            item = self.lst.takeItem(r); self.lst.insertItem(r+1, item)
            self.lst.setCurrentRow(r+1)

    def _remove(self):
        r = self.lst.currentRow()
        if r >= 0: self.lst.takeItem(r)

    def _run(self):
        paths = [self.lst.item(i).text() for i in range(self.lst.count())]
        out   = self.drop_out.path()
        if len(paths) < 2:
            QMessageBox.warning(self, "Aviso", "Adiciona pelo menos 2 PDFs."); return
        if not out:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        try:
            w = PdfWriter()
            for p in paths:
                for page in PdfReader(p).pages: w.add_page(page)
            with open(out, "wb") as f: w.write(f)
            self._status(f"✔  PDF criado: {os.path.basename(out)}")
            QMessageBox.information(self, "Concluído", f"PDF criado em:\n{out}")
        except Exception as e: QMessageBox.critical(self, "Erro", str(e))


# ══════════════════════════════════════════════════════════════════════════════
#  Ferramenta 3 – Rodar
# ══════════════════════════════════════════════════════════════════════════════

class TabRotar(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.sync-alt", "Rodar páginas",
                         "Roda uma ou todas as páginas do PDF.",
                         "Rodar e guardar", status_fn)
        f = self._form
        f.addWidget(section("Ficheiro de origem"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox("Opções de rotação")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pages = QLineEdit()
        self.edit_pages.setPlaceholderText("ex: 1,3,5-8  (vazio = todas)")
        self.cmb_angle = QComboBox()
        self.cmb_angle.addItems(["90°  (sentido horário)",
                                  "180°",
                                  "270°  (sentido anti-horário)"])
        form.addRow("Páginas:", self.edit_pages)
        form.addRow("Ângulo:", self.cmb_angle)
        f.addWidget(grp)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit("rotado.pdf", save=True, default_name="rotado.pdf")
        f.addWidget(self.drop_out); f.addStretch()

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if not p: return
        self.drop_in.set_path(p)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_rotado" + ext)
        try:
            r = PdfReader(p); self.lbl_info.setText(f"  {len(r.pages)} páginas")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def _run(self):
        pdf_path = self.drop_in.path(); out_path = self.drop_out.path()
        angle = {0: 90, 1: 180, 2: 270}[self.cmb_angle.currentIndex()]
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona um PDF válido."); return
        if not out_path:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        try:
            reader = PdfReader(pdf_path); total = len(reader.pages)
            txt = self.edit_pages.text().strip()
            pages = parse_pages(txt, total) if txt else list(range(total))
            w = PdfWriter()
            for i, page in enumerate(reader.pages):
                if i in pages: page.rotate(angle)
                w.add_page(page)
            with open(out_path, "wb") as f: w.write(f)
            self._status(f"✔  PDF rodado: {os.path.basename(out_path)}")
            QMessageBox.information(self, "Concluído", f"PDF guardado em:\n{out_path}")
        except Exception as e: QMessageBox.critical(self, "Erro", str(e))


# ══════════════════════════════════════════════════════════════════════════════
#  Ferramenta 4 – Extrair páginas
# ══════════════════════════════════════════════════════════════════════════════

class TabExtrair(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.file-export", "Extrair páginas",
                         "Copia páginas específicas para um novo PDF.",
                         "Extrair páginas", status_fn)
        f = self._form
        f.addWidget(section("Ficheiro de origem"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox("Páginas a extrair")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pages = QLineEdit()
        self.edit_pages.setPlaceholderText("ex: 1,3,5-8,10")
        hint = QLabel("Usa vírgulas e hífens.  Ex:  1, 3, 5-8, 10")
        hint.setObjectName("info_lbl")
        form.addRow("Páginas:", self.edit_pages)
        form.addRow("", hint)
        f.addWidget(grp)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit("extraido.pdf", save=True, default_name="extraido.pdf")
        f.addWidget(self.drop_out); f.addStretch()

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if not p: return
        self.drop_in.set_path(p)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_extraido" + ext)
        try:
            r = PdfReader(p); self.lbl_info.setText(f"  {len(r.pages)} páginas")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def _run(self):
        pdf_path = self.drop_in.path(); out_path = self.drop_out.path()
        txt = self.edit_pages.text().strip()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona um PDF válido."); return
        if not txt:
            QMessageBox.warning(self, "Aviso", "Indica as páginas a extrair."); return
        if not out_path:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        try:
            reader = PdfReader(pdf_path)
            pages  = parse_pages(txt, len(reader.pages))
            w = PdfWriter()
            for p in pages: w.add_page(reader.pages[p])
            with open(out_path, "wb") as f: w.write(f)
            self._status(f"✔  {len(pages)} página(s) extraída(s): {os.path.basename(out_path)}")
            QMessageBox.information(self, "Concluído",
                f"{len(pages)} página(s) extraída(s) para:\n{out_path}")
        except Exception as e: QMessageBox.critical(self, "Erro", str(e))


# ══════════════════════════════════════════════════════════════════════════════
#  Ferramenta 5 – Reordenar
# ══════════════════════════════════════════════════════════════════════════════

class TabReordenar(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.sort", "Reordenar páginas",
                         "Arrasta as páginas para alterar a sua ordem ou remove-as.",
                         "Guardar PDF reordenado", status_fn)
        self._reader: PdfReader | None = None
        f = self._form
        f.addWidget(section("Ficheiro de origem"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox("Ordem das páginas  (arrasta para reordenar)")
        vl  = QVBoxLayout(grp); vl.setSpacing(8)
        self.lst = QListWidget()
        self.lst.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.lst.setAlternatingRowColors(True)
        self.lst.setMinimumHeight(200)
        vl.addWidget(self.lst)
        hb = QHBoxLayout()
        for txt, slot in [("▲ Subir", self._up), ("▼ Descer", self._dn),
                          ("−  Apagar", self._del), ("↺  Repor ordem", self._reset)]:
            btn = danger_btn(txt) if "Apagar" in txt else QPushButton(txt)
            btn.clicked.connect(slot); hb.addWidget(btn)
        hb.addStretch(); vl.addLayout(hb)
        f.addWidget(grp)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit("reordenado.pdf", save=True, default_name="reordenado.pdf")
        f.addWidget(self.drop_out); f.addStretch()

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if not p: return
        self.drop_in.set_path(p)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_reordenado" + ext)
        try:
            reader = PdfReader(p); self._reader = reader
            n = len(reader.pages); self.lbl_info.setText(f"  {n} páginas")
            self._populate(list(range(n)))
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def _populate(self, indices: list[int]):
        self.lst.clear()
        for i in indices:
            item = QListWidgetItem(f"   Página  {i + 1}")
            item.setData(256, i); self.lst.addItem(item)

    def _up(self):
        r = self.lst.currentRow()
        if r > 0:
            item = self.lst.takeItem(r); self.lst.insertItem(r-1, item)
            self.lst.setCurrentRow(r-1)

    def _dn(self):
        r = self.lst.currentRow()
        if r < self.lst.count()-1:
            item = self.lst.takeItem(r); self.lst.insertItem(r+1, item)
            self.lst.setCurrentRow(r+1)

    def _del(self):
        r = self.lst.currentRow()
        if r >= 0: self.lst.takeItem(r)

    def _reset(self):
        if self._reader: self._populate(list(range(len(self._reader.pages))))

    def _run(self):
        if not self._reader:
            QMessageBox.warning(self, "Aviso", "Abre um PDF primeiro."); return
        out = self.drop_out.path()
        if not out:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        try:
            indices = [self.lst.item(i).data(256) for i in range(self.lst.count())]
            w = PdfWriter()
            for idx in indices: w.add_page(self._reader.pages[idx])
            with open(out, "wb") as f: w.write(f)
            self._status(f"✔  PDF reordenado: {os.path.basename(out)}")
            QMessageBox.information(self, "Concluído", f"PDF guardado em:\n{out}")
        except Exception as e: QMessageBox.critical(self, "Erro", str(e))


# ══════════════════════════════════════════════════════════════════════════════
#  Ferramenta 6 – Comprimir
# ══════════════════════════════════════════════════════════════════════════════

class TabComprimir(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.compress-arrows-alt", "Comprimir PDF",
                         "Reduz o tamanho do ficheiro comprimindo streams e objectos.",
                         "Comprimir PDF", status_fn)
        f = self._form
        f.addWidget(section("Ficheiro de origem"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit("comprimido.pdf", save=True, default_name="comprimido.pdf")
        f.addWidget(self.drop_out)

        self.lbl_result = QLabel("")
        self.lbl_result.setStyleSheet(
            "font-weight:600; font-size:11pt; color:#059669; "
            "background:transparent; padding:10px 4px;")
        f.addWidget(self.lbl_result)
        f.addStretch()

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if not p: return
        self.drop_in.set_path(p)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_comprimido" + ext)
        size = os.path.getsize(p)
        try:
            r = PdfReader(p)
            self.lbl_info.setText(f"  {len(r.pages)} páginas  ·  {size/1024:.1f} KB")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def _run(self):
        pdf_path = self.drop_in.path(); out_path = self.drop_out.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona um PDF válido."); return
        if not out_path:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        try:
            import fitz  # PyMuPDF
            before = os.path.getsize(pdf_path)
            doc = fitz.open(pdf_path)
            buf = doc.tobytes(
                garbage=4,
                deflate=True,
                deflate_images=True,
                deflate_fonts=True,
                clean=True,
            )
            doc.close()
            after = len(buf)
            ratio = (1 - after / before) * 100 if before else 0
            if after >= before:
                msg = f"  {before/1024:.0f} KB  →  {after/1024:.0f} KB  (sem ganho)"
                self.lbl_result.setText(msg)
                self._status("ℹ  O ficheiro já está optimizado — sem ganho de compressão")
                QMessageBox.information(self, "Sem ganho",
                    f"O ficheiro já está bem comprimido.\n\n"
                    f"Original: {before/1024:.0f} KB\n"
                    f"Resultado: {after/1024:.0f} KB\n\n"
                    f"O ficheiro de saída não foi guardado.")
                return
            with open(out_path, "wb") as f:
                f.write(buf)
            msg = f"  {before/1024:.0f} KB  →  {after/1024:.0f} KB  (−{ratio:.0f}%)"
            self.lbl_result.setText(msg)
            self._status(f"✔  Compressão: {msg.strip()}")
            QMessageBox.information(self, "Concluído", f"PDF guardado em:\n{out_path}")
        except Exception as e: QMessageBox.critical(self, "Erro", str(e))


# ══════════════════════════════════════════════════════════════════════════════
#  Ferramenta 7 – Encriptar / Desencriptar
# ══════════════════════════════════════════════════════════════════════════════

class TabEncriptar(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.lock", "Encriptar / Desencriptar",
                         "Protege o PDF com senha ou remove a protecção existente.",
                         "Executar", status_fn)
        f = self._form
        f.addWidget(section("Ficheiro PDF"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp_mode = QGroupBox("Operação")
        hm = QHBoxLayout(grp_mode)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["🔒  Encriptar  —  proteger com senha",
                                  "🔓  Desencriptar  —  remover protecção"])
        self.cmb_mode.currentIndexChanged.connect(self._on_mode)
        hm.addWidget(self.cmb_mode)
        f.addWidget(grp_mode)

        self.grp_enc = QGroupBox("Senhas de encriptação")
        fe = QFormLayout(self.grp_enc)
        fe.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_owner = QLineEdit(); self.edit_owner.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_user  = QLineEdit(); self.edit_user.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_user.setPlaceholderText("Opcional — limita a abertura")
        fe.addRow("Senha do proprietário *:", self.edit_owner)
        fe.addRow("Senha do utilizador:", self.edit_user)
        f.addWidget(self.grp_enc)

        self.grp_dec = QGroupBox("Senha actual do PDF")
        fd = QFormLayout(self.grp_dec)
        fd.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pwd = QLineEdit(); self.edit_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_pwd.setPlaceholderText("Deixa em branco se não tiver senha")
        fd.addRow("Senha:", self.edit_pwd)
        f.addWidget(self.grp_dec)
        self._on_mode(0)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit("resultado.pdf", save=True, default_name="resultado.pdf")
        f.addWidget(self.drop_out); f.addStretch()

    def _on_mode(self, idx: int):
        self.grp_enc.setVisible(idx == 0)
        self.grp_dec.setVisible(idx == 1)

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if not p: return
        self.drop_in.set_path(p)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_enc" + ext)
        try:
            r = PdfReader(p)
            estado = "🔒 encriptado" if r.is_encrypted else "🔓 sem protecção"
            self.lbl_info.setText(f"  {len(r.pages)} páginas  ·  {estado}")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def _run(self):
        pdf_path = self.drop_in.path(); out_path = self.drop_out.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona um PDF válido."); return
        if not out_path:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        try:
            reader = PdfReader(pdf_path)
            if self.cmb_mode.currentIndex() == 0:
                owner = self.edit_owner.text()
                if not owner:
                    QMessageBox.warning(self, "Aviso", "Introduz a senha do proprietário."); return
                w = PdfWriter(); w.append_pages_from_reader(reader)
                w.encrypt(user_password=self.edit_user.text(),
                          owner_password=owner, use_128bit=True)
                with open(out_path, "wb") as f: w.write(f)
                self._status(f"✔  PDF encriptado: {os.path.basename(out_path)}")
                QMessageBox.information(self, "Concluído", f"PDF encriptado:\n{out_path}")
            else:
                if reader.is_encrypted: reader.decrypt(self.edit_pwd.text())
                w = PdfWriter(); w.append_pages_from_reader(reader)
                with open(out_path, "wb") as f: w.write(f)
                self._status(f"✔  PDF desencriptado: {os.path.basename(out_path)}")
                QMessageBox.information(self, "Concluído", f"PDF desencriptado:\n{out_path}")
        except Exception as e: QMessageBox.critical(self, "Erro", str(e))


# ══════════════════════════════════════════════════════════════════════════════
#  Ferramenta 8 – Marca d'água
# ══════════════════════════════════════════════════════════════════════════════

class TabMarcaDagua(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.stamp", "Marca d'água",
                         "Sobrepõe um PDF (marca, carimbo) sobre as páginas.",
                         "Aplicar marca d'água", status_fn)
        f = self._form
        f.addWidget(section("PDF de origem"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        f.addWidget(section("PDF da marca d'água  (1 página)"))
        self.drop_wm = DropFileEdit("Arrasta o PDF da marca d'água aqui…")
        f.addWidget(self.drop_wm)

        grp = QGroupBox("Opções")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pages = QLineEdit()
        self.edit_pages.setPlaceholderText("ex: 1,3,5-8  (vazio = todas)")
        self.cmb_layer = QComboBox()
        self.cmb_layer.addItems(["Por baixo  (fundo / marca d'água clássica)",
                                  "Por cima  (carimbo / frente)"])
        form.addRow("Páginas:", self.edit_pages)
        form.addRow("Posição:", self.cmb_layer)
        f.addWidget(grp)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit("com_marca.pdf", save=True, default_name="com_marca.pdf")
        f.addWidget(self.drop_out); f.addStretch()

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if not p: return
        self.drop_in.set_path(p)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_marca" + ext)
        try:
            r = PdfReader(p); self.lbl_info.setText(f"  {len(r.pages)} páginas")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def _run(self):
        pdf_path = self.drop_in.path(); wm_path = self.drop_wm.path()
        out_path = self.drop_out.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona o PDF de origem."); return
        if not wm_path or not os.path.isfile(wm_path):
            QMessageBox.warning(self, "Aviso", "Seleciona o PDF de marca d'água."); return
        if not out_path:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        try:
            reader  = PdfReader(pdf_path)
            wm_page = PdfReader(wm_path).pages[0]
            total   = len(reader.pages)
            txt     = self.edit_pages.text().strip()
            targets = set(parse_pages(txt, total)) if txt else set(range(total))
            over    = self.cmb_layer.currentIndex() == 1
            w = PdfWriter()
            for i, page in enumerate(reader.pages):
                if i in targets:
                    page.merge_page(wm_page) if over else page.merge_page(wm_page, over=False)
                w.add_page(page)
            with open(out_path, "wb") as f: w.write(f)
            self._status(f"✔  Marca d'água aplicada: {os.path.basename(out_path)}")
            QMessageBox.information(self, "Concluído", f"PDF guardado em:\n{out_path}")
        except Exception as e: QMessageBox.critical(self, "Erro", str(e))


# ══════════════════════════════════════════════════════════════════════════════
#  Ferramenta 9 – Informação
# ══════════════════════════════════════════════════════════════════════════════

class TabInfo(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.info-circle", "Informação",
                         "Mostra metadados, dimensões e propriedades do PDF.",
                         "Ver informação", status_fn)
        f = self._form
        f.addWidget(section("Ficheiro PDF"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_and_show)
        f.addWidget(self.drop_in)

        self.txt = QTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setFont(__import__("PySide6.QtGui", fromlist=["QFont"]).QFont("Consolas", 10))
        self.txt.setMinimumHeight(260)
        self.txt.setStyleSheet(
            "QTextEdit { background:#0F172A; color:#94A3B8; "
            "border:1px solid #1E293B; border-radius:8px; padding:14px; }")
        f.addWidget(self.txt); f.addStretch()
        # botão de acção carrega o ficheiro directamente
        self.action_btn.setText("Abrir PDF e mostrar info")

    def _pick_and_show(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if p: self.drop_in.set_path(p); self._show(p)

    def _run(self):
        p = self.drop_in.path()
        if not p or not os.path.isfile(p):
            p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
            if not p: return
            self.drop_in.set_path(p)
        self._show(p)

    def _show(self, path: str):
        try:
            reader = PdfReader(path); meta = reader.metadata or {}
            size   = os.path.getsize(path)
            lines  = [
                f"  📄  {os.path.basename(path)}",
                f"  📁  {path}",
                "",
                f"  Páginas       {len(reader.pages)}",
                f"  Tamanho       {size/1024:.1f} KB  ({size:,} bytes)".replace(",", " "),
                f"  Encriptado    {'Sim' if reader.is_encrypted else 'Não'}",
                "",
                "  " + "─" * 44,
            ]
            for key, label in {
                "/Title": "Título", "/Author": "Autor", "/Subject": "Assunto",
                "/Creator": "Criado por", "/Producer": "Produzido por",
                "/CreationDate": "Criado em", "/ModDate": "Modificado em",
            }.items():
                val = meta.get(key, "")
                if val: lines.append(f"  {label:<16}{val}")
            if len(reader.pages) > 0:
                pg = reader.pages[0]
                w, h = float(pg.mediabox.width), float(pg.mediabox.height)
                lines += ["",
                    f"  Dimensão pág.1   {w:.0f} × {h:.0f} pt",
                    f"                   {w/72*25.4:.0f} × {h/72*25.4:.0f} mm",
                ]
            self.txt.setPlainText("\n".join(lines))
            self._status(f"ℹ  {os.path.basename(path)}  ·  {len(reader.pages)} páginas  ·  {size/1024:.1f} KB")
        except Exception as e:
            self.txt.setPlainText(f"Erro ao ler o PDF:\n{e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Painel de pré-visualização PDF
# ══════════════════════════════════════════════════════════════════════════════

class PdfViewerPanel(QWidget):
    """Visualizador PDF com drag & drop, botão abrir e navegação de páginas."""

    def __init__(self):
        super().__init__()
        self.setObjectName("viewer_panel")
        self.setMinimumWidth(260)
        self.setAcceptDrops(True)
        self._doc = QPdfDocument(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Cabeçalho ───────────────────────────────────────────────────────
        hdr = QWidget(); hdr.setObjectName("viewer_header")
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(12, 8, 8, 8)
        hdr_lay.setSpacing(6)

        self._name_lbl = QLabel("Visualizador PDF")
        self._name_lbl.setObjectName("viewer_title")
        hdr_lay.addWidget(self._name_lbl, 1)

        self._open_btn = QPushButton()
        self._open_btn.setIcon(qta.icon('fa5s.folder-open', color=TEXT_SEC))
        self._open_btn.setObjectName("viewer_nav_btn")
        self._open_btn.setFixedSize(28, 28)
        self._open_btn.setToolTip("Abrir PDF")
        self._open_btn.clicked.connect(self._open_dialog)

        self._prev_btn = QPushButton()
        self._prev_btn.setIcon(qta.icon('fa5s.chevron-left', color=TEXT_SEC))
        self._prev_btn.setObjectName("viewer_nav_btn")
        self._prev_btn.setFixedSize(28, 28)
        self._prev_btn.clicked.connect(self._prev_page)
        self._prev_btn.setEnabled(False)

        self._page_lbl = QLabel("— / —")
        self._page_lbl.setObjectName("viewer_page_lbl")
        self._page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._next_btn = QPushButton()
        self._next_btn.setIcon(qta.icon('fa5s.chevron-right', color=TEXT_SEC))
        self._next_btn.setObjectName("viewer_nav_btn")
        self._next_btn.setFixedSize(28, 28)
        self._next_btn.clicked.connect(self._next_page)
        self._next_btn.setEnabled(False)

        self._zoom_out_btn = QPushButton()
        self._zoom_out_btn.setIcon(qta.icon('fa5s.search-minus', color=TEXT_SEC))
        self._zoom_out_btn.setObjectName("viewer_nav_btn")
        self._zoom_out_btn.setFixedSize(28, 28)
        self._zoom_out_btn.setToolTip("Diminuir zoom (Ctrl+Scroll)")
        self._zoom_out_btn.clicked.connect(self._zoom_out)
        self._zoom_out_btn.setEnabled(False)

        self._zoom_lbl = QLabel("Ajustar")
        self._zoom_lbl.setObjectName("viewer_page_lbl")
        self._zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_lbl.setMinimumWidth(52)

        self._zoom_in_btn = QPushButton()
        self._zoom_in_btn.setIcon(qta.icon('fa5s.search-plus', color=TEXT_SEC))
        self._zoom_in_btn.setObjectName("viewer_nav_btn")
        self._zoom_in_btn.setFixedSize(28, 28)
        self._zoom_in_btn.setToolTip("Aumentar zoom (Ctrl+Scroll)")
        self._zoom_in_btn.clicked.connect(self._zoom_in)
        self._zoom_in_btn.setEnabled(False)

        self._fit_btn = QPushButton()
        self._fit_btn.setIcon(qta.icon('fa5s.compress-arrows-alt', color=TEXT_SEC))
        self._fit_btn.setObjectName("viewer_nav_btn")
        self._fit_btn.setFixedSize(28, 28)
        self._fit_btn.setToolTip("Ajustar à janela")
        self._fit_btn.clicked.connect(self._zoom_fit)
        self._fit_btn.setEnabled(False)

        hdr_lay.addWidget(self._open_btn)
        hdr_lay.addWidget(self._zoom_out_btn)
        hdr_lay.addWidget(self._zoom_lbl)
        hdr_lay.addWidget(self._zoom_in_btn)
        hdr_lay.addWidget(self._fit_btn)
        hdr_lay.addWidget(self._prev_btn)
        hdr_lay.addWidget(self._page_lbl)
        hdr_lay.addWidget(self._next_btn)
        layout.addWidget(hdr)

        # ── Placeholder ─────────────────────────────────────────────────────
        ph_widget = QWidget()
        ph_widget.setObjectName("viewer_ph_widget")
        ph_lay = QVBoxLayout(ph_widget)
        ph_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_lay.setSpacing(14)

        ph_icon = QLabel()
        ph_icon.setPixmap(qta.icon('fa5s.file-pdf', color='#2E3A55').pixmap(56, 56))
        ph_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        ph_text = QLabel("Arrasta um PDF aqui\nou usa o botão  para abrir")
        ph_text.setObjectName("viewer_placeholder")
        ph_text.setAlignment(Qt.AlignmentFlag.AlignCenter)

        ph_btn = QPushButton("  Abrir PDF")
        ph_btn.setIcon(qta.icon('fa5s.folder-open', color='#FFFFFF'))
        ph_btn.setObjectName("btn_primary")
        ph_btn.setFixedWidth(160)
        ph_btn.clicked.connect(self._open_dialog)

        ph_lay.addWidget(ph_icon)
        ph_lay.addWidget(ph_text)
        ph_lay.addWidget(ph_btn, 0, Qt.AlignmentFlag.AlignCenter)

        self._placeholder = ph_widget
        layout.addWidget(self._placeholder, 1)

        # ── Vista PDF ───────────────────────────────────────────────────────
        self._view = QPdfView(self)
        self._view.setDocument(self._doc)
        self._view.setPageMode(QPdfView.PageMode.MultiPage)
        self._view.setZoomMode(QPdfView.ZoomMode.FitInView)
        self._view.setObjectName("pdf_view")
        self._view.setVisible(False)
        layout.addWidget(self._view, 1)

        self._view.pageNavigator().currentPageChanged.connect(self._update_page_label)
        self._view.installEventFilter(self)

    def paintEvent(self, event):
        _paint_bg(self)

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
        path = e.mimeData().urls()[0].toLocalFile()
        self.load(path)

    # ── Abrir diálogo ────────────────────────────────────────────────────────
    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir PDF", "", "Ficheiros PDF (*.pdf);;Todos (*.*)")
        if path:
            self.load(path)

    # ── API ─────────────────────────────────────────────────────────────────
    def load(self, path: str):
        if not path or not path.lower().endswith(".pdf") or not os.path.isfile(path):
            return
        self._doc.close()
        self._doc.load(path)
        ok = (self._doc.status() == QPdfDocument.Status.Ready)
        self._view.setVisible(ok)
        self._placeholder.setVisible(not ok)
        if ok:
            self._name_lbl.setText(os.path.basename(path))
            nav = self._view.pageNavigator()
            nav.jump(0, QPointF(), nav.currentZoom())
            self._view.setZoomMode(QPdfView.ZoomMode.FitInView)
            self._zoom_lbl.setText("Ajustar")
            self._zoom_out_btn.setEnabled(True)
            self._zoom_in_btn.setEnabled(True)
            self._fit_btn.setEnabled(True)
            self._update_page_label()

    # ── Navegação ────────────────────────────────────────────────────────────
    def _update_page_label(self):
        total = self._doc.pageCount()
        if total > 0:
            current = self._view.pageNavigator().currentPage() + 1
            self._page_lbl.setText(f"{current} / {total}")
            self._prev_btn.setEnabled(current > 1)
            self._next_btn.setEnabled(current < total)
        else:
            self._page_lbl.setText("— / —")
            self._prev_btn.setEnabled(False)
            self._next_btn.setEnabled(False)

    def _prev_page(self):
        nav = self._view.pageNavigator()
        if nav.currentPage() > 0:
            nav.jump(nav.currentPage() - 1, QPointF(), nav.currentZoom())

    def _next_page(self):
        nav = self._view.pageNavigator()
        if nav.currentPage() < self._doc.pageCount() - 1:
            nav.jump(nav.currentPage() + 1, QPointF(), nav.currentZoom())

    # ── Zoom ─────────────────────────────────────────────────────────────────
    _ZOOM_STEP = 0.20
    _ZOOM_MIN  = 0.25
    _ZOOM_MAX  = 4.00

    def _zoom_in(self):
        self._set_zoom(self._view.zoomFactor() + self._ZOOM_STEP)

    def _zoom_out(self):
        self._set_zoom(self._view.zoomFactor() - self._ZOOM_STEP)

    def _zoom_fit(self):
        self._view.setZoomMode(QPdfView.ZoomMode.FitInView)
        self._zoom_lbl.setText("Ajustar")

    def _set_zoom(self, factor: float):
        factor = max(self._ZOOM_MIN, min(self._ZOOM_MAX, factor))
        self._view.setZoomMode(QPdfView.ZoomMode.Custom)
        self._view.setZoomFactor(factor)
        self._zoom_lbl.setText(f"{int(factor * 100)}%")

    def eventFilter(self, obj, event):
        if obj is self._view and event.type() == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if event.angleDelta().y() > 0:
                    self._zoom_in()
                else:
                    self._zoom_out()
                return True
        return super().eventFilter(obj, event)


# ══════════════════════════════════════════════════════════════════════════════
#  Ferramenta 10 – OCR
# ══════════════════════════════════════════════════════════════════════════════

_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

class TabOCR(BasePage):
    _LANGS = [
        ("Português",          "por"),
        ("Inglês",             "eng"),
        ("Português + Inglês", "por+eng"),
        ("Espanhol",           "spa"),
        ("Francês",            "fra"),
        ("Alemão",             "deu"),
    ]

    def __init__(self, status_fn):
        super().__init__("fa5s.search", "OCR – Reconhecer Texto",
                         "Extrai texto de PDFs digitalizados/escaneados usando OCR.",
                         "Executar OCR", status_fn)
        f = self._form

        f.addWidget(section("Ficheiro PDF (digitalizado)"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        f.addWidget(section("Opções"))
        row_lang = QHBoxLayout()
        lbl_lang = QLabel("Idioma do documento:")
        lbl_lang.setStyleSheet(f"color:{TEXT_SEC};")
        self.cmb_lang = QComboBox()
        self._lang_codes = [c for _, c in self._LANGS]
        for name, _ in self._LANGS:
            self.cmb_lang.addItem(name)
        row_lang.addWidget(lbl_lang); row_lang.addWidget(self.cmb_lang); row_lang.addStretch()
        f.addLayout(row_lang)

        row_fmt = QHBoxLayout()
        lbl_fmt = QLabel("Formato de saída:")
        lbl_fmt.setStyleSheet(f"color:{TEXT_SEC};")
        self.cmb_fmt = QComboBox()
        self.cmb_fmt.addItems(["PDF pesquisável (.pdf)", "Texto simples (.txt)"])
        self.cmb_fmt.currentIndexChanged.connect(self._on_fmt_change)
        row_fmt.addWidget(lbl_fmt); row_fmt.addWidget(self.cmb_fmt); row_fmt.addStretch()
        f.addLayout(row_fmt)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit("ocr_output.pdf", save=True, default_name="ocr_output.pdf")
        f.addWidget(self.drop_out)
        f.addStretch()

    def _on_fmt_change(self, idx):
        p = self.drop_out.path()
        if p:
            base = os.path.splitext(p)[0]
            self.drop_out.set_path(base + (".pdf" if idx == 0 else ".txt"))

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if not p: return
        self.drop_in.set_path(p)
        if not self.drop_out.path():
            base = os.path.splitext(p)[0]
            ext = ".pdf" if self.cmb_fmt.currentIndex() == 0 else ".txt"
            self.drop_out.set_path(base + "_ocr" + ext)
        try:
            import fitz
            doc = fitz.open(p)
            self.lbl_info.setText(f"  {doc.page_count} páginas")
            doc.close()
        except Exception as e:
            self.lbl_info.setText(f"  Erro: {e}")

    def _ensure_tesseract(self):
        """Localiza o Tesseract, define TESSDATA_PREFIX e atualiza idiomas disponíveis."""
        import pytesseract
        tess_exe = None
        for path in _TESSERACT_PATHS:
            if os.path.isfile(path):
                tess_exe = path
                break

        if tess_exe:
            pytesseract.pytesseract.tesseract_cmd = tess_exe
            # Garante que TESSDATA_PREFIX aponta para a pasta do Tesseract
            tess_dir = os.path.dirname(tess_exe)
            tessdata = os.path.join(tess_dir, "tessdata")
            if os.path.isdir(tessdata):
                os.environ["TESSDATA_PREFIX"] = tess_dir

        try:
            pytesseract.get_tesseract_version()
        except Exception:
            QMessageBox.critical(self, "Tesseract não encontrado",
                "O motor Tesseract OCR não está instalado ou não foi encontrado.\n\n"
                "Instala em:\nhttps://github.com/UB-Mannheim/tesseract/wiki\n\n"
                "Inclui os language packs de que precisas (por, eng…).")
            return None

        # Detetar idiomas instalados e atualizar o dropdown
        try:
            installed = pytesseract.get_languages(config="")
            self._update_lang_combo(installed)
        except Exception:
            pass

        return pytesseract

    def _update_lang_combo(self, installed: list):
        """Mostra só os idiomas instalados + combinações possíveis."""
        entries = []
        label_map = {"por": "Português", "eng": "Inglês", "spa": "Espanhol",
                     "fra": "Francês",   "deu": "Alemão",  "ita": "Italiano"}
        for code, label in [(c, label_map.get(c, c)) for c in installed if c != "osd"]:
            entries.append((label, code))
        # combinação por+eng se ambos disponíveis
        if "por" in installed and "eng" in installed:
            entries.append(("Português + Inglês", "por+eng"))
        if not entries:
            entries = [("Inglês (padrão)", "eng")]
        current_codes = [e[1] for e in entries]
        self.cmb_lang.clear()
        for name, _ in entries:
            self.cmb_lang.addItem(name)
        self._lang_codes = current_codes

    def _run(self):
        import io as _io
        pdf_path = self.drop_in.path(); out_path = self.drop_out.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona um PDF válido."); return
        if not out_path:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        try:
            import pytesseract
        except ImportError:
            QMessageBox.critical(self, "Dependência em falta",
                "Instala a biblioteca pytesseract:\n  pip install pytesseract")
            return
        tess = self._ensure_tesseract()
        if tess is None: return
        try:
            import fitz
            from PIL import Image
            codes = getattr(self, "_lang_codes", [c for _, c in self._LANGS])
            lang  = codes[self.cmb_lang.currentIndex()]
            fmt  = self.cmb_fmt.currentIndex()  # 0=pdf, 1=txt
            doc  = fitz.open(pdf_path)
            n    = doc.page_count
            self._status(f"A iniciar OCR em {n} página(s)…")
            QApplication.processEvents()

            if fmt == 1:
                texts = []
                for i, page in enumerate(doc):
                    self._status(f"OCR: página {i+1}/{n}…")
                    QApplication.processEvents()
                    pix = page.get_pixmap(dpi=300)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    texts.append(pytesseract.image_to_string(img, lang=lang))
                doc.close()
                with open(out_path, "w", encoding="utf-8") as fh:
                    fh.write("\f".join(texts))
            else:
                pdf_pages = []
                for i, page in enumerate(doc):
                    self._status(f"OCR: página {i+1}/{n}…")
                    QApplication.processEvents()
                    pix = page.get_pixmap(dpi=300)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    pdf_bytes = pytesseract.image_to_pdf_or_hocr(img, lang=lang, extension="pdf")
                    pdf_pages.append(pdf_bytes)
                doc.close()
                writer = PdfWriter()
                for page_bytes in pdf_pages:
                    writer.append(PdfReader(_io.BytesIO(page_bytes)))
                with open(out_path, "wb") as fh:
                    writer.write(fh)

            self._status(f"✔  OCR concluído → {out_path}")
            QMessageBox.information(self, "Concluído",
                f"OCR concluído com sucesso!\n\nFicheiro guardado em:\n{out_path}")
        except Exception as e:
            QMessageBox.critical(self, "Erro no OCR", str(e))


# ══════════════════════════════════════════════════════════════════════════════
#  Canvas de edição visual (renderiza PDF e captura cliques/arrastos)
# ══════════════════════════════════════════════════════════════════════════════

class PdfEditCanvas(QWidget):
    rect_selected = Signal(object)   # fitz.Rect em coords PDF
    point_clicked = Signal(object)   # fitz.Point em coords PDF

    def __init__(self):
        super().__init__()
        self._doc        = None
        self._page_idx   = 0
        self._zoom       = 1.0
        self._qpix       = None
        self._drag_start = None
        self._drag_rect  = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMinimumSize(300, 400)

    def load(self, path: str):
        import fitz
        if self._doc: self._doc.close()
        self._doc = fitz.open(path)
        self._page_idx = 0
        self._render()

    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    def set_page(self, idx: int):
        if self._doc and 0 <= idx < self._doc.page_count:
            self._page_idx = idx
            self._render()

    def close_doc(self):
        if self._doc: self._doc.close(); self._doc = None

    def _render(self):
        if not self._doc: return
        import fitz
        from PySide6.QtGui import QPixmap as QP
        page = self._doc[self._page_idx]
        avail = max(self.width(), 300)
        self._zoom = avail / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(self._zoom, self._zoom))
        qp = QP(); qp.loadFromData(pix.tobytes("png"))
        self._qpix = qp
        self.setFixedSize(qp.width(), qp.height())

    def _to_pdf(self, sx, sy):
        import fitz
        return fitz.Point(sx / self._zoom, sy / self._zoom)

    def _rect_to_pdf(self, r):
        import fitz
        return fitz.Rect(r.left()/self._zoom, r.top()/self._zoom,
                         r.right()/self._zoom, r.bottom()/self._zoom)

    def paintEvent(self, _):
        from PySide6.QtGui import QPainter, QColor, QPen
        p = QPainter(self)
        if self._qpix: p.drawPixmap(0, 0, self._qpix)
        if self._drag_rect:
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
        if self._drag_rect and self._drag_rect.width() > 6 and self._drag_rect.height() > 6:
            self.rect_selected.emit(self._rect_to_pdf(self._drag_rect))
        else:
            self.point_clicked.emit(self._to_pdf(pos.x(), pos.y()))
        self._drag_start = None; self._drag_rect = None
        self.update()

    def resizeEvent(self, _):
        self._render(); self.update()


# ══════════════════════════════════════════════════════════════════════════════
#  Ferramenta 11 – Editar PDF (canvas visual)
# ══════════════════════════════════════════════════════════════════════════════

class _TextDialog(QDialog):
    """Popup para inserir texto ao clicar no canvas."""
    _COLORS = {"Preto": (0,0,0), "Azul": (0,0,1), "Vermelho": (1,0,0), "Verde": (0,0.6,0)}

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Inserir texto"); self.setModal(True)
        v = QVBoxLayout(self)
        self.edit = QLineEdit(); self.edit.setPlaceholderText("Texto a inserir…")
        v.addWidget(self.edit)
        row = QHBoxLayout()
        row.addWidget(QLabel("Tamanho:"))
        self.font_size = QSpinBox(); self.font_size.setMinimum(4); self.font_size.setMaximum(144); self.font_size.setValue(12)
        row.addWidget(self.font_size); row.addSpacing(12)
        row.addWidget(QLabel("Cor:"))
        self.color = QComboBox(); self.color.addItems(list(self._COLORS.keys()))
        row.addWidget(self.color); row.addStretch()
        v.addLayout(row)
        btns = QHBoxLayout()
        ok = QPushButton("OK"); ok.setObjectName("btn_primary"); ok.clicked.connect(self.accept)
        ca = QPushButton("Cancelar"); ca.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)
        self.setMinimumWidth(360)

    def color_tuple(self):
        return list(self._COLORS.values())[self.color.currentIndex()]


class TabEditar(QWidget):
    """Editor visual: clica/arrasta directamente no PDF renderizado."""

    _HI_COLORS  = {"Amarelo": (1,1,0), "Verde": (0,1,0), "Rosa": (1,0.4,0.7), "Azul claro": (0.5,0.8,1)}
    _RED_FILLS  = {"Preto": (0,0,0), "Branco": (1,1,1), "Cinzento": (0.5,0.5,0.5)}
    _MODE_NAMES = ["Redigir / Censurar", "Adicionar texto", "Adicionar imagem",
                   "Destacar (highlight)", "Nota / Comentário", "Preencher formulários"]

    def __init__(self, status_fn):
        super().__init__()
        self._status   = status_fn
        self._pending  = []
        self._doc_path = None
        self.setObjectName("content_area")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        root.addWidget(ToolHeader("fa5s.edit", "Editar PDF",
                                  "Clica ou arrasta directamente no PDF para editar."))

        # ── body: canvas esquerda | controlos direita ────────────────────────
        body = QSplitter(Qt.Orientation.Horizontal)

        self._canvas = PdfEditCanvas()
        self._canvas.rect_selected.connect(self._on_rect)
        self._canvas.point_clicked.connect(self._on_point)
        canvas_scroll = scrolled(self._canvas)
        canvas_scroll.setMinimumWidth(320)
        body.addWidget(canvas_scroll)

        # painel de controlos
        ctrl = QWidget(); ctrl.setObjectName("scroll_inner"); ctrl.setFixedWidth(268)
        cv = QVBoxLayout(ctrl); cv.setContentsMargins(14, 14, 14, 14); cv.setSpacing(8)

        cv.addWidget(section("Ficheiro PDF"))
        self._drop_in = DropFileEdit()
        self._drop_in.btn.clicked.disconnect()
        self._drop_in.btn.clicked.connect(self._pick_pdf)
        self._lbl_info = info_lbl()
        cv.addWidget(self._drop_in); cv.addWidget(self._lbl_info)

        cv.addWidget(section("Página"))
        pnav = QHBoxLayout()
        self._btn_prev = QPushButton("◀"); self._btn_prev.setFixedWidth(32)
        self._btn_prev.clicked.connect(self._prev_page)
        self._lbl_page = QLabel("—"); self._lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_next = QPushButton("▶"); self._btn_next.setFixedWidth(32)
        self._btn_next.clicked.connect(self._next_page)
        pnav.addWidget(self._btn_prev); pnav.addWidget(self._lbl_page, 1); pnav.addWidget(self._btn_next)
        cv.addLayout(pnav)
        self._page_idx = 0

        cv.addWidget(section("Modo"))
        self._cmb_mode = QComboBox(); self._cmb_mode.addItems(self._MODE_NAMES)
        self._cmb_mode.currentIndexChanged.connect(self._on_mode_change)
        cv.addWidget(self._cmb_mode)

        # opções por modo
        self._opt_stack = QStackedWidget()

        # 0 – Redigir
        w0 = QWidget(); v0 = QVBoxLayout(w0); v0.setContentsMargins(0,4,0,0); v0.setSpacing(4)
        v0.addWidget(QLabel("Cor:"))
        self._red_color = QComboBox(); self._red_color.addItems(list(self._RED_FILLS.keys()))
        v0.addWidget(self._red_color)
        hint0 = QLabel("Arrasta para selecionar a área."); hint0.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v0.addWidget(hint0); v0.addStretch()
        self._opt_stack.addWidget(w0)

        # 1 – Texto
        w1 = QWidget(); v1 = QVBoxLayout(w1); v1.setContentsMargins(0,4,0,0)
        hint1 = QLabel("Clica no PDF para posicionar.\nAs opções surgem num popup.")
        hint1.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v1.addWidget(hint1); v1.addStretch()
        self._opt_stack.addWidget(w1)

        # 2 – Imagem
        w2 = QWidget(); v2 = QVBoxLayout(w2); v2.setContentsMargins(0,4,0,0); v2.setSpacing(4)
        v2.addWidget(QLabel("Imagem:"))
        self._img_drop = DropFileEdit(placeholder="Arrasta imagem aqui…",
                                      filters="Imagens (*.png *.jpg *.jpeg *.bmp *.tiff *.webp)")
        self._img_drop.btn.clicked.disconnect()
        self._img_drop.btn.clicked.connect(self._pick_image)
        v2.addWidget(self._img_drop)
        hint2 = QLabel("Arrasta no PDF para definir a área."); hint2.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v2.addWidget(hint2); v2.addStretch()
        self._opt_stack.addWidget(w2)

        # 3 – Highlight
        w3 = QWidget(); v3 = QVBoxLayout(w3); v3.setContentsMargins(0,4,0,0); v3.setSpacing(4)
        v3.addWidget(QLabel("Cor:"))
        self._hi_color = QComboBox(); self._hi_color.addItems(list(self._HI_COLORS.keys()))
        v3.addWidget(self._hi_color)
        hint3 = QLabel("Arrasta para selecionar o texto."); hint3.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v3.addWidget(hint3); v3.addStretch()
        self._opt_stack.addWidget(w3)

        # 4 – Nota
        w4 = QWidget(); v4 = QVBoxLayout(w4); v4.setContentsMargins(0,4,0,0); v4.setSpacing(4)
        v4.addWidget(QLabel("Texto da nota:"))
        self._note_txt = QTextEdit(); self._note_txt.setMaximumHeight(80)
        v4.addWidget(self._note_txt)
        hint4 = QLabel("Clica no PDF para posicionar."); hint4.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v4.addWidget(hint4); v4.addStretch()
        self._opt_stack.addWidget(w4)

        # 5 – Formulários
        w5 = QWidget(); v5 = QVBoxLayout(w5); v5.setContentsMargins(0,4,0,0); v5.setSpacing(4)
        v5.addWidget(QLabel("Campos detectados:"))
        self._form_table = QTableWidget(0, 2)
        self._form_table.setHorizontalHeaderLabels(["Campo", "Valor"])
        self._form_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._form_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._form_table.setObjectName("pdf_table"); self._form_table.setMinimumHeight(130)
        v5.addWidget(self._form_table)
        self._opt_stack.addWidget(w5)

        cv.addWidget(self._opt_stack)

        cv.addWidget(section("Edições pendentes"))
        self._pending_list = QListWidget(); self._pending_list.setMaximumHeight(110)
        cv.addWidget(self._pending_list)
        btn_clear = QPushButton("Limpar tudo"); btn_clear.clicked.connect(self._clear_pending)
        cv.addWidget(btn_clear)

        cv.addWidget(section("Guardar em"))
        self._drop_out = DropFileEdit("output_editado.pdf", save=True, default_name="output_editado.pdf")
        cv.addWidget(self._drop_out)
        cv.addStretch()

        body.addWidget(ctrl)
        body.setSizes([700, 268])
        root.addWidget(body, 1)

        action_bar, _ = ActionBar("Aplicar e Guardar", self._run)
        root.addWidget(action_bar)

        self._update_nav()

    def paintEvent(self, event):
        _paint_bg(self)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _update_nav(self):
        n = self._canvas.page_count()
        self._btn_prev.setEnabled(n > 0 and self._page_idx > 0)
        self._btn_next.setEnabled(n > 0 and self._page_idx < n - 1)
        self._lbl_page.setText(f"{self._page_idx+1} / {n}" if n else "—")

    def _prev_page(self):
        if self._page_idx > 0:
            self._page_idx -= 1; self._canvas.set_page(self._page_idx); self._update_nav()

    def _next_page(self):
        if self._page_idx < self._canvas.page_count() - 1:
            self._page_idx += 1; self._canvas.set_page(self._page_idx); self._update_nav()

    def _on_mode_change(self, idx):
        self._opt_stack.setCurrentIndex(idx)

    def _pick_pdf(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if not p: return
        self._doc_path = p
        self._drop_in.set_path(p)
        self._drop_out.set_path(os.path.splitext(p)[0] + "_editado.pdf")
        self._pending.clear(); self._pending_list.clear()
        self._canvas.load(p)
        self._page_idx = 0
        n = self._canvas.page_count()
        self._lbl_info.setText(f"  {n} páginas")
        self._update_nav()
        self._load_form_fields(p)

    def _pick_image(self):
        p, _ = QFileDialog.getOpenFileName(self, "Selecionar imagem", "",
                                           "Imagens (*.png *.jpg *.jpeg *.bmp *.tiff *.webp)")
        if p: self._img_drop.set_path(p)

    def _load_form_fields(self, path):
        self._form_table.setRowCount(0)
        try:
            for name, field in (PdfReader(path).get_fields() or {}).items():
                r = self._form_table.rowCount(); self._form_table.insertRow(r)
                self._form_table.setItem(r, 0, QTableWidgetItem(name))
                self._form_table.setItem(r, 1, QTableWidgetItem(str(field.get("/V", "") or "")))
        except Exception:
            pass

    # ── canvas callbacks ─────────────────────────────────────────────────────

    def _on_rect(self, pdf_rect):
        mode = self._cmb_mode.currentIndex()
        if mode == 0:   # redact
            self._add({"type": "redact", "page": self._page_idx, "rect": pdf_rect,
                       "fill": self._RED_FILLS[self._red_color.currentText()]})
        elif mode == 2:  # image
            img = self._img_drop.path()
            if not img or not os.path.isfile(img):
                QMessageBox.warning(self, "Aviso", "Seleciona uma imagem primeiro."); return
            self._add({"type": "image", "page": self._page_idx, "rect": pdf_rect, "path": img})
        elif mode == 3:  # highlight
            self._add({"type": "highlight", "page": self._page_idx, "rect": pdf_rect,
                       "color": self._HI_COLORS[self._hi_color.currentText()]})

    def _on_point(self, pdf_pt):
        mode = self._cmb_mode.currentIndex()
        if mode == 1:   # text
            dlg = _TextDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted: return
            txt = dlg.edit.text().strip()
            if not txt: return
            self._add({"type": "text", "page": self._page_idx, "point": pdf_pt,
                       "text": txt, "size": dlg.font_size.value(), "color": dlg.color_tuple()})
        elif mode == 4:  # note
            txt = self._note_txt.toPlainText().strip()
            if not txt:
                QMessageBox.warning(self, "Aviso", "Escreve o texto da nota primeiro."); return
            self._add({"type": "note", "page": self._page_idx, "point": pdf_pt, "text": txt})

    def _add(self, edit: dict):
        self._pending.append(edit)
        labels = {
            "redact":    lambda e: f"Redigir — pág. {e['page']+1}",
            "text":      lambda e: f"Texto '{e['text'][:18]}' — pág. {e['page']+1}",
            "image":     lambda e: f"Imagem '{os.path.basename(e['path'])}' — pág. {e['page']+1}",
            "highlight": lambda e: f"Highlight — pág. {e['page']+1}",
            "note":      lambda e: f"Nota — pág. {e['page']+1}",
        }
        self._pending_list.addItem(labels[edit["type"]](edit))

    def _clear_pending(self):
        self._pending.clear(); self._pending_list.clear()

    # ── aplicar ──────────────────────────────────────────────────────────────

    def _run(self):
        if not self._doc_path or not os.path.isfile(self._doc_path):
            QMessageBox.warning(self, "Aviso", "Abre um PDF primeiro."); return
        out = self._drop_out.path()
        if not out:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        if self._cmb_mode.currentIndex() == 5:
            self._apply_forms(out); return
        if not self._pending:
            QMessageBox.warning(self, "Aviso", "Nenhuma edição pendente."); return
        try:
            import fitz
            doc = fitz.open(self._doc_path)
            for e in self._pending:
                pg = doc[e["page"]]
                if e["type"] == "redact":
                    pg.add_redact_annot(e["rect"], fill=e["fill"]); pg.apply_redactions()
                elif e["type"] == "text":
                    pg.insert_text(e["point"], e["text"], fontsize=e["size"], color=e["color"])
                elif e["type"] == "image":
                    pg.insert_image(e["rect"], filename=e["path"])
                elif e["type"] == "highlight":
                    a = pg.add_highlight_annot(e["rect"]); a.set_colors(stroke=e["color"]); a.update()
                elif e["type"] == "note":
                    pg.add_text_annot(e["point"], e["text"])
            doc.save(out, garbage=4, deflate=True); doc.close()
            self._pending.clear(); self._pending_list.clear()
            self._status(f"✔  Guardado → {out}")
            QMessageBox.information(self, "Concluído", f"PDF guardado em:\n{out}")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))

    def _apply_forms(self, out):
        try:
            writer = PdfWriter(); writer.append(PdfReader(self._doc_path))
            fields = {self._form_table.item(r, 0).text():
                      (self._form_table.item(r, 1).text() if self._form_table.item(r, 1) else "")
                      for r in range(self._form_table.rowCount())}
            for page in writer.pages:
                writer.update_page_form_field_values(page, fields, auto_regenerate=False)
            with open(out, "wb") as f: writer.write(f)
            self._status(f"✔  Formulário guardado → {out}")
            QMessageBox.information(self, "Concluído", f"Formulário guardado em:\n{out}")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))


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


# ══════════════════════════════════════════════════════════════════════════════
#  Janela principal
# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDFApps")
        ico_path = resource_path("icon.ico")
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))
        self.resize(1220, 700)
        self.setMinimumSize(860, 540)

        self._sb = QStatusBar(); self.setStatusBar(self._sb)
        self._sb.showMessage("Pronto")

        central = QWidget()
        main_h  = QHBoxLayout(central)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────────
        sidebar = QWidget(); sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(188)
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
        self.nav.setIconSize(QSize(16, 16))
        for name, icon_name, _ in NAV_ITEMS:
            item = QListWidgetItem(qta.icon(icon_name, color=TEXT_SEC), name)
            self.nav.addItem(item)
        sb_lay.addWidget(self.nav, 1)

        footer_w = QWidget(); footer_w.setObjectName("sidebar")
        footer_h = QHBoxLayout(footer_w)
        footer_h.setContentsMargins(14, 6, 10, 8); footer_h.setSpacing(0)
        footer_lbl = QLabel("pypdf  +  PySide6"); footer_lbl.setObjectName("sidebar_footer")
        self._theme_btn = QPushButton("☀")
        self._theme_btn.setObjectName("theme_btn")
        self._theme_btn.setToolTip("Alternar tema claro/escuro")
        self._theme_btn.setFixedSize(28, 28)
        self._theme_btn.clicked.connect(self._toggle_theme)
        footer_h.addWidget(footer_lbl, 1)
        footer_h.addWidget(self._theme_btn)
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
        self.setCentralWidget(central)

        self._current_tool = -1
        self.nav.itemClicked.connect(self._on_nav_clicked)

        # Ligar todos os DropFileEdit ao viewer
        for i in range(self.stack.count()):
            for dfe in self.stack.widget(i).findChildren(DropFileEdit):
                dfe.path_changed.connect(self._viewer.load)

    def _on_nav_clicked(self, item):
        row = self.nav.row(item)
        if row == self._current_tool:
            # clique no mesmo → fecha o painel de ferramenta
            self.nav.clearSelection()
            self._current_tool = -1
            self.stack.setVisible(False)
        else:
            self._current_tool = row
            self.stack.setCurrentIndex(row)
            self.stack.setVisible(True)
            self._splitter.setSizes([460, 600])

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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName(" ")
    app.setApplicationDisplayName(" ")
    app.setStyle("Fusion")
    app.setPalette(_make_palette(True))
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
