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
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QGroupBox, QScrollArea,
    QLabel, QLineEdit, QPushButton, QSpinBox, QComboBox,
    QListWidget, QListWidgetItem, QAbstractItemView,
    QFileDialog, QMessageBox, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame, QStatusBar, QSplitter,
    QDialog, QLayout,
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

ACCENT   = "#14B8A6"   # teal principal
ACCENT_H = "#0D9488"   # hover
ACCENT_P = "#0F766E"   # pressed
BG_BASE  = "#0B0F12"   # fundo global
BG_SIDE  = "#11161A"   # sidebar
BG_CARD  = "#182127"   # cards / tool header
BG_INPUT = "#1D2A33"   # inputs
BG_INNER = "#121B22"   # scroll area
BORDER   = "#2A3944"   # bordas
TEXT_PRI = "#E6F4F1"   # texto primário
TEXT_SEC = "#93A9A3"   # texto secundário

STYLE = f"""
/* ── Globals ─────────────────────────────────────────────────────────── */
QMainWindow {{ background: {BG_BASE}; }}
QWidget     {{ background: transparent; color: {TEXT_PRI};
              font-family: "Segoe UI Variable Text", "Segoe UI", Arial, sans-serif; font-size: 12pt; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ── Sidebar ─────────────────────────────────────────────────────────── */
#sidebar    {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #151C22, stop:1 #0F1418);
              border-right: 1px solid {BORDER}; }}
#brand_area {{ background: {BG_SIDE}; padding: 20px 0 12px 0; }}

#app_title {{ font-size: 15pt; font-weight: 700; color: #FFFFFF;
             background: transparent; padding: 0 16px 2px 16px; }}
#app_sub   {{ font-size: 10pt; color: #7E9A94;
             background: transparent; padding: 0 16px 14px 16px; }}

#nav_sep   {{ background: {BORDER}; max-height: 1px; margin: 4px 12px 8px 12px; }}

#nav_list  {{ background: transparent; border: none; outline: none;
             color: #AFC1BC; font-size: 11pt; }}
#nav_list::item          {{ padding: 10px 14px; margin: 2px 8px; border-radius: 6px; }}
#nav_list::item:hover    {{ background: #22303A; color: {TEXT_PRI}; }}
#nav_list::item:selected {{ background: #134E4A; border: 1px solid #2FAE99;
                           color: #D9FFF9; font-weight: 700; }}

#sidebar_footer {{ background: transparent; color: #6A847E;
                  font-size: 9pt; padding: 10px 16px; }}

#workspace_bar {{ background: #10181E; border-bottom: 1px solid {BORDER}; }}
#workspace_title {{ font-size: 11pt; font-weight: 700; color: #E6F4F1; background: transparent; }}
#workspace_hint  {{ font-size: 9pt; color: #89A69F; background: transparent; }}
#workspace_badge {{
    background: #134E4A; border: 1px solid #2FAE99; color: #D9FFF9;
    border-radius: 10px; padding: 5px 10px; font-size: 9pt; font-weight: 600;
}}
#quick_btn {{
    background: #18252E; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 6px 14px; min-height: 30px; font-size: 10pt; font-weight: 600;
}}
#quick_btn:hover   {{ background: #223340; border-color: #3C5E6B; }}
#quick_btn:pressed {{ background: #111B22; }}
#workspace_shell {{ background: transparent; }}

/* ── Tool header ─────────────────────────────────────────────────────── */
#tool_header  {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #1C2B34, stop:1 #17242D);
                border-bottom: 1px solid {BORDER};
                min-height: 68px; padding: 0 24px; }}
#th_title     {{ font-size: 15pt; font-weight: 700; background: transparent;
                color: {TEXT_PRI}; }}
#th_desc      {{ font-size: 11pt; background: transparent; color: #9AB3AD; }}

/* ── Scroll inner ────────────────────────────────────────────────────── */
#scroll_inner {{ background: {BG_INNER}; }}

/* ── Action bar ──────────────────────────────────────────────────────── */
#action_bar   {{ background: {BG_CARD}; border-top: 1px solid {BORDER}; }}

/* ── Primary button ──────────────────────────────────────────────────── */
#btn_primary {{
    background: {ACCENT}; color: #FFFFFF; border: none;
    border-radius: 8px; font-size: 12pt; font-weight: 700;
    padding: 10px 30px; min-height: 44px;
}}
#btn_primary:hover   {{ background: {ACCENT_H}; }}
#btn_primary:pressed {{ background: {ACCENT_P}; }}
#btn_primary:disabled {{ background: #2A3C45; color: #7D9B96; }}

/* ── Secondary buttons ───────────────────────────────────────────────── */
QPushButton {{
    background: #1B2B35; border: 1px solid {BORDER};
    border-radius: 8px; padding: 7px 16px; color: {TEXT_PRI}; font-size: 11pt;
}}
QPushButton:hover   {{ background: #253945; border-color: #476573; color: #FFFFFF; }}
QPushButton:pressed {{ background: #141F27; }}

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


/* -- Mode buttons (checkable) -----------------------------------------------*/
QPushButton:checkable {{ background: #18252E; border: 1px solid #2A3944;
    border-radius: 6px; padding: 6px 8px; text-align: left; font-size: 10pt; }}
QPushButton:checkable:hover   {{ background: #223340; border-color: #3C5E6B; }}
QPushButton:checkable:checked {{ background: #0D3D38; border: 1px solid #14B8A6; color: #14B8A6; }}
QPushButton:checkable:pressed {{ background: #0A2E2A; }}
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

#theme_btn {{
    background: #1B2B35; border: 1px solid {BORDER}; border-radius: 14px;
    font-size: 13pt; padding: 0; min-width: 28px; max-width: 28px;
}}
#theme_btn:hover {{ background: #253945; border-color: #476573; }}
"""

# ── Tema claro ────────────────────────────────────────────────────────────────
_LA = "#0F766E"; _LAH = "#0D9488"; _LAP = "#0F5F58"
_LB = "#F4F7F6"; _LS = "#E9EFEC"; _LC = "#FFFFFF"
_LI = "#F2F7F5"; _LN = "#ECF3F1"; _LO = "#C7D8D3"
_LP = "#1A2B28"; _LQ = "#5D7470"

STYLE_LIGHT = f"""
QMainWindow {{ background: {_LB}; }}
QWidget     {{ background: transparent; color: {_LP};
              font-family: "Segoe UI Variable Text", "Segoe UI", Arial, sans-serif; font-size: 12pt; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

#sidebar    {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #EEF6F4, stop:1 #E3EEEB);
              border-right: 1px solid {_LO}; }}
#brand_area {{ background: {_LS}; padding: 20px 0 12px 0; }}
#app_title  {{ font-size: 15pt; font-weight: 700; color: {_LP};
              background: transparent; padding: 0 16px 2px 16px; }}
#app_sub    {{ font-size: 10pt; color: {_LQ};
              background: transparent; padding: 0 16px 14px 16px; }}
#nav_sep    {{ background: {_LO}; max-height: 1px; margin: 4px 12px 8px 12px; }}
#nav_list   {{ background: transparent; border: none; outline: none;
              color: {_LQ}; font-size: 11pt; }}
#nav_list::item          {{ padding: 10px 14px; margin: 2px 8px; border-radius: 6px; }}
#nav_list::item:hover    {{ background: #D9E8E4; color: {_LP}; }}
#nav_list::item:selected {{ background: #D6F2EC; border: 1px solid #83CABB;
                           color: #0E5A51; font-weight: 700; }}
#sidebar_footer {{ background: transparent; color: {_LQ};
                  font-size: 9pt; padding: 10px 16px; }}

#workspace_bar {{ background: #F0F6F4; border-bottom: 1px solid {_LO}; }}
#workspace_title {{ font-size: 11pt; font-weight: 700; color: {_LP}; background: transparent; }}
#workspace_hint  {{ font-size: 9pt; color: {_LQ}; background: transparent; }}
#workspace_badge {{
    background: #D6F2EC; border: 1px solid #83CABB; color: #0E5A51;
    border-radius: 10px; padding: 5px 10px; font-size: 9pt; font-weight: 600;
}}
#quick_btn {{
    background: #FFFFFF; border: 1px solid {_LO}; border-radius: 8px;
    padding: 6px 14px; min-height: 30px; font-size: 10pt; font-weight: 600;
}}
#quick_btn:hover   {{ background: #E3EFEB; border-color: #8EBCB2; }}
#quick_btn:pressed {{ background: #D2E3DE; }}
#workspace_shell {{ background: transparent; }}

#tool_header  {{ background: {_LC}; border-bottom: 1px solid {_LO};
                min-height: 68px; padding: 0 24px; }}
#th_title     {{ font-size: 15pt; font-weight: 700; background: transparent; color: {_LP}; }}
#th_desc      {{ font-size: 11pt; background: transparent; color: {_LQ}; }}

#scroll_inner {{ background: {_LN}; }}
#action_bar   {{ background: {_LC}; border-top: 1px solid {_LO}; }}

#btn_primary {{
    background: {_LA}; color: #FFFFFF; border: none;
    border-radius: 8px; font-size: 12pt; font-weight: 700;
    padding: 10px 30px; min-height: 44px;
}}
#btn_primary:hover   {{ background: {_LAH}; }}
#btn_primary:pressed {{ background: {_LAP}; }}
#btn_primary:disabled {{ background: #CBD5E1; color: #94A3B8; }}

QPushButton {{
    background: {_LC}; border: 1px solid {_LO};
    border-radius: 8px; padding: 7px 16px; color: {_LP}; font-size: 11pt;
}}
QPushButton:hover   {{ background: #E0ECE8; border-color: #8EBCB2; color: {_LP}; }}
QPushButton:pressed {{ background: #D2E3DE; }}

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
    background: #E7F0ED; border: 1px solid #BFD4CD; border-radius: 14px; font-size: 13pt;
    padding: 0; min-width: 28px; max-width: 28px;
}}
#theme_btn:hover {{ background: #DBEAE5; border-color: #9FC2B8; }}
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
        self._filters      = filters
        self._save         = save
        self._default      = default_name
        self._path_value   = ""
        self._placeholder  = placeholder
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

    # ── API ──────────────────���────────────────────────────────────────��────��
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
        self._lbl.setText(self._placeholder)
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
        self.drop_in.path_changed.connect(self._load_input)
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
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path(): self.drop_out.set_path(os.path.dirname(p))
        try:
            r = PdfReader(p); self._total = len(r.pages)
            self.lbl_info.setText(f"  {self._total} páginas no ficheiro")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

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
        self.drop_out = DropFileEdit(save=True, default_name="juntado.pdf")
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

    def auto_load(self, path: str):
        if not path: return
        existing = [self.lst.item(i).text() for i in range(self.lst.count())]
        if path not in existing:
            self.lst.addItem(QListWidgetItem(path))

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
        self.drop_in.path_changed.connect(self._load_input)
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
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_rotado" + ext)
        try:
            r = PdfReader(p); self.lbl_info.setText(f"  {len(r.pages)} páginas")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

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
        self.drop_in.path_changed.connect(self._load_input)
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
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_extraido" + ext)
        try:
            r = PdfReader(p); self.lbl_info.setText(f"  {len(r.pages)} páginas")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

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
        self.drop_in.path_changed.connect(self._load_input)
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
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_reordenado" + ext)
        try:
            reader = PdfReader(p); self._reader = reader
            n = len(reader.pages); self.lbl_info.setText(f"  {n} páginas")
            self._populate(list(range(n)))
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

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

# Presets de compressão (equivalente aos 3 níveis do ilovepdf)
# max_px: dimensão máxima (lado maior) em píxeis após redimensionamento
#         72 dpi ≈ 600 px | 150 dpi ≈ 1240 px | 300 dpi = sem resize
_COMPRESS_LEVELS = {
    "extreme":     {"max_px": 600,  "quality": 45},
    "recommended": {"max_px": 1240, "quality": 70},
    "low":         {"max_px": 9999, "quality": 85},  # 9999 = não redimensiona
}


def _compress_pdf(src: str, dst: str, level: str = "recommended") -> tuple[int, int]:
    """
    Pipeline de compressão em 2 passes independentes (inspirado no ilovepdf):

      Passo A — pypdf
        · compress_content_streams(level=9)  →  zlib máx em todos os streams
        · compress_identical_objects()       →  deduplica objectos iguais

      Passo B — fitz (PyMuPDF)
        · scrub()          →  remove metadados, thumbnails, ficheiros anexos
        · subset_fonts()   →  mantém só os glifos usados
        · DPI downsampling →  redimensiona imagens acima do DPI alvo
                              (via PIL se disponível, ou factor de escala directo)
        · JPEG re-encode   →  re-codifica cada imagem com a qualidade do nível
        · save() com use_objstms=True + garbage=4 + deflate

    O resultado mais pequeno dos dois passes é guardado em dst.
    Lança ValueError se nenhum passe reduzir o ficheiro.
    Lança RuntimeError se nenhuma biblioteca estiver disponível.
    """
    import tempfile, shutil, io

    cfg          = _COMPRESS_LEVELS.get(level, _COMPRESS_LEVELS["recommended"])
    max_px       = cfg["max_px"]
    jpeg_quality = cfg["quality"]
    before       = os.path.getsize(src)
    temps: list[str] = []

    # ── Passo A : pypdf — streams + deduplica objectos ─────────────────────
    try:
        reader = PdfReader(src)
        writer = PdfWriter()
        for page in reader.pages:
            page.compress_content_streams(level=9)
            writer.add_page(page)
        if reader.metadata:
            writer.add_metadata(reader.metadata)
        try:
            writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
        except Exception:
            pass
        fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
        with open(p, "wb") as fh:
            writer.write(fh)
        temps.append(p)
    except Exception:
        pass

    # ── Passo B : fitz — scrub + subset_fonts + DPI + JPEG ─────────────────
    try:
        import fitz

        doc = fitz.open(src)

        # 1. Remove peso morto
        try:
            doc.scrub(metadata=True, xml_metadata=True,
                      thumbnails=True, attached_files=True)
        except Exception:
            pass

        # 2. Subset de fontes (mantém só glifos usados)
        try:
            doc.subset_fonts()
        except Exception:
            pass

        # 3. Redimensiona + re-codifica imagens
        seen: set[int] = set()
        for pg in doc:
            for img_tuple in pg.get_images(full=True):
                xref  = img_tuple[0]
                smask = img_tuple[8]
                if xref in seen:
                    continue
                seen.add(xref)
                if smask != 0:      # tem máscara de transparência → salta
                    continue
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.width < 32 or pix.height < 32:
                        continue
                    if pix.alpha:
                        pix = fitz.Pixmap(pix, 0)
                    if pix.n == 4:  # CMYK → RGB
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    if pix.n not in (1, 3):
                        continue

                    # Redimensiona se o lado maior excede max_px
                    longest = max(pix.width, pix.height)
                    scale = min(1.0, max_px / longest) if longest > max_px else 1.0

                    if scale < 0.99:
                        nw = max(1, int(pix.width  * scale))
                        nh = max(1, int(pix.height * scale))
                        try:
                            from PIL import Image as _PILImage
                            mode = "L" if pix.n == 1 else "RGB"
                            img = _PILImage.frombytes(mode, (pix.width, pix.height),
                                                      pix.samples)
                            _lanczos = getattr(
                                getattr(_PILImage, "Resampling", _PILImage),
                                "LANCZOS", 1)
                            img = img.resize((nw, nh), _lanczos)
                            buf = io.BytesIO()
                            img.save(buf, format="JPEG", quality=jpeg_quality,
                                     optimize=True, progressive=True)
                            jpeg = buf.getvalue()
                        except ImportError:
                            # PIL não disponível — usa shrink nativo do fitz
                            factor = max(1, int(1 / scale))
                            pix.shrink(factor)
                            jpeg = pix.tobytes("jpeg", jpg_quality=jpeg_quality)
                    else:
                        jpeg = pix.tobytes("jpeg", jpg_quality=jpeg_quality)

                    doc.replace_image(xref, stream=jpeg)
                except Exception:
                    pass

        # 4. Guarda com todas as flags de compressão
        fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
        save_kw = dict(garbage=4, deflate=True, deflate_fonts=True, clean=True)
        try:
            doc.save(p, **save_kw, use_objstms=True)
        except TypeError:           # versões mais antigas sem use_objstms
            doc.save(p, **save_kw)
        doc.close()
        temps.append(p)
    except Exception:
        pass

    if not temps:
        raise RuntimeError("Instala pypdf e/ou PyMuPDF:\n"
                           "  pip install pypdf pymupdf pillow")

    # ── Escolhe o melhor resultado ──────────────────────────────────────────
    best      = min(temps, key=lambda p: os.path.getsize(p))
    best_size = os.path.getsize(best)

    for p in temps:
        if p != best:
            try: os.unlink(p)
            except Exception: pass

    if best_size >= before:
        try: os.unlink(best)
        except Exception: pass
        raise ValueError(f"Sem ganho: {before/1024:.0f} KB → {best_size/1024:.0f} KB")

    shutil.move(best, dst)
    return before, best_size


class TabComprimir(BasePage):
    _LEVEL_KEYS = ["extreme", "recommended", "low"]

    def __init__(self, status_fn):
        super().__init__("fa5s.compress-arrows-alt", "Comprimir PDF",
                         "Reduz o tamanho do ficheiro comprimindo streams e objectos.",
                         "Comprimir PDF", status_fn)
        f = self._form
        f.addWidget(section("Ficheiro de origem"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox("Nível de compressão")
        gl  = QFormLayout(grp)
        gl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.cmb_level = QComboBox()
        self.cmb_level.addItems([
            "Extreme  —  DPI 72 · JPEG 45 %  (máx. compressão)",
            "Recomendado  —  DPI 150 · JPEG 70 %  (equilíbrio)",
            "Baixo  —  DPI 300 · JPEG 85 %  (mín. perda)",
        ])
        self.cmb_level.setCurrentIndex(1)
        gl.addRow("Nível:", self.cmb_level)
        f.addWidget(grp)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit(save=True, default_name="comprimido.pdf")
        f.addWidget(self.drop_out)

        self.lbl_result = QLabel("")
        self.lbl_result.setStyleSheet(
            "font-weight:600; font-size:11pt; color:#059669; "
            "background:transparent; padding:10px 4px;")
        f.addWidget(self.lbl_result)
        f.addStretch()

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_comprimido" + ext)
        size = os.path.getsize(p)
        try:
            r = PdfReader(p)
            self.lbl_info.setText(f"  {len(r.pages)} páginas  ·  {size/1024:.1f} KB")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _run(self):
        pdf_path = self.drop_in.path(); out_path = self.drop_out.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona um PDF válido."); return
        if not out_path:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        level = self._LEVEL_KEYS[self.cmb_level.currentIndex()]
        self._status(f"A comprimir ({level})…")
        QApplication.processEvents()
        try:
            before, after = _compress_pdf(pdf_path, out_path, level)
            ratio = (1 - after / before) * 100 if before else 0
            msg = f"  {before/1024:.0f} KB  →  {after/1024:.0f} KB  (−{ratio:.0f}%)"
            self.lbl_result.setText(msg)
            self._status(f"✔  Compressão: {msg.strip()}")
            QMessageBox.information(self, "Concluído", f"PDF guardado em:\n{out_path}")
        except ValueError as e:
            before_kb = os.path.getsize(pdf_path) / 1024
            msg = f"  {before_kb:.0f} KB  (sem ganho)"
            self.lbl_result.setText(msg)
            self._status("ℹ  O ficheiro já está optimizado — sem ganho de compressão")
            QMessageBox.information(self, "Sem ganho",
                f"Não foi possível reduzir o tamanho.\n\n{e}\n\n"
                f"O ficheiro de saída não foi guardado.")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))


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
        self.drop_in.path_changed.connect(self._load_input)
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
        self.edit_user.setPlaceholderText("Opcional — se vazio, usa a senha do proprietário")
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
        # actualizar sufixo do output quando o modo muda
        p = self.drop_in.path()
        if p:
            base, ext = os.path.splitext(p)
            suffix = "_enc" if idx == 0 else "_dec"
            self.drop_out.set_path(base + suffix + ext)

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        base, ext = os.path.splitext(p)
        suffix = "_enc" if self.cmb_mode.currentIndex() == 0 else "_dec"
        self.drop_out.set_path(base + suffix + ext)
        try:
            r = PdfReader(p)
            encrypted = r.is_encrypted
            estado = "🔒 encriptado" if encrypted else "🔓 sem protecção"
            # len(r.pages) falha se encriptado e sem senha — usar page_count alternativo
            try:
                n_pages = len(r.pages)
            except Exception:
                n_pages = "?"
            self.lbl_info.setText(f"  {n_pages} páginas  ·  {estado}")
        except Exception as e:
            self.lbl_info.setText(f"  Erro: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

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
                user_pwd = self.edit_user.text() or owner  # se vazio, usar a mesma senha para abrir
                w = PdfWriter(); w.append(reader)
                w.encrypt(user_password=user_pwd,
                          owner_password=owner, use_128bit=True)
                with open(out_path, "wb") as f: w.write(f)
                self._status(f"✔  PDF encriptado: {os.path.basename(out_path)}")
                QMessageBox.information(self, "Concluído", f"PDF encriptado:\n{out_path}")
            else:
                if reader.is_encrypted:
                    result = reader.decrypt(self.edit_pwd.text())
                    if result == 0:
                        QMessageBox.warning(self, "Aviso", "Senha incorrecta — não foi possível desencriptar o PDF.")
                        return
                w = PdfWriter(); w.append(reader)
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
        self.drop_in.path_changed.connect(self._load_input)
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
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_marca" + ext)
        try:
            r = PdfReader(p); self.lbl_info.setText(f"  {len(r.pages)} páginas")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

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
                    page.merge_page(wm_page, over=over)
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
        self.drop_in.path_changed.connect(self._show)
        f.addWidget(self.drop_in)

        self.txt = QTextEdit()
        self.txt.setReadOnly(True)
        from PySide6.QtGui import QFont
        self.txt.setFont(QFont("Consolas", 10))
        self.txt.setMinimumHeight(260)
        self.txt.setStyleSheet(
            "QTextEdit { background:#0F172A; color:#94A3B8; "
            "border:1px solid #1E293B; border-radius:8px; padding:14px; }")
        f.addWidget(self.txt); f.addStretch()
        # botão de acção carrega o ficheiro directamente
        self.action_btn.setText("Abrir PDF e mostrar info")

    def _pick_and_show(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if p: self.drop_in.set_path(p)

    def _run(self):
        p = self.drop_in.path()
        if not p or not os.path.isfile(p):
            p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
            if not p: return
            self.drop_in.set_path(p)
        self._show(p)

    def auto_load(self, path: str):
        if path and not self.drop_in.path():
            self.drop_in.set_path(path)
            self._show(path)

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
    def current_path(self) -> str:
        return getattr(self, "_current_path", "")

    def load(self, path: str):
        if not path or not path.lower().endswith(".pdf") or not os.path.isfile(path):
            return
        self._current_path = path
        self._doc.close()
        self._doc.setPassword("")
        self._doc.load(path)

        # tratar PDF protegido com senha
        wrong = False
        while self._doc.error() == QPdfDocument.Error.IncorrectPassword:
            dlg = _PdfPasswordDialog(os.path.basename(path), wrong=wrong, parent=self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            self._doc.close()
            self._doc.setPassword(dlg.password())
            self._doc.load(path)
            wrong = True

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
        self.drop_in.path_changed.connect(self._load_input)
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
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
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

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

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
            # TESSDATA_PREFIX deve apontar para a pasta tessdata (não para o seu pai)
            tess_dir = os.path.dirname(tess_exe)
            tessdata = os.path.join(tess_dir, "tessdata")
            if os.path.isdir(tessdata):
                os.environ["TESSDATA_PREFIX"] = tessdata

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
        except ImportError:
            QMessageBox.critical(self, "Dependência em falta",
                "Instala a biblioteca PyMuPDF:\n\npip install pymupdf")
            return
        try:
            from PIL import Image
        except ImportError:
            QMessageBox.critical(self, "Dependência em falta",
                "Instala a biblioteca Pillow:\n\npip install Pillow")
            return
        try:
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
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMinimumSize(300, 400)

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
        # ── drag rect ─────────────────────────────────────────────────────────
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
        if self._drag_rect and self._drag_rect.width() > 3 and self._drag_rect.height() > 3:
            self.rect_selected.emit(self._rect_to_pdf(self._drag_rect))
        else:
            self.point_clicked.emit(self._to_pdf(pos.x(), pos.y()))
        self._drag_start = None; self._drag_rect = None
        self.update()



# ══════════════════════════════════════════════════════════════════════════════
#  Ferramenta 11 – Editar PDF (canvas visual)
# ══════════════════════════════════════════════════════════════════════════════

class _PdfPasswordDialog(QDialog):
    """Diálogo estilizado para introduzir a senha de um PDF protegido."""
    def __init__(self, filename: str, wrong: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF Protegido")
        self.setModal(True)
        self.setMinimumWidth(400)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 20)
        v.setSpacing(16)

        # ícone + título
        top = QHBoxLayout(); top.setSpacing(14)
        ico = QLabel()
        ico.setPixmap(qta.icon("fa5s.lock", color=ACCENT).pixmap(36, 36))
        ico.setFixedSize(40, 40)
        top.addWidget(ico)
        title_col = QVBoxLayout(); title_col.setSpacing(2)
        lbl_title = QLabel("PDF Protegido com Senha")
        lbl_title.setStyleSheet(f"font-size:13pt; font-weight:700; color:{TEXT_PRI};")
        lbl_file  = QLabel(filename)
        lbl_file.setStyleSheet(f"font-size:9pt; color:{TEXT_SEC};")
        lbl_file.setWordWrap(True)
        title_col.addWidget(lbl_title); title_col.addWidget(lbl_file)
        top.addLayout(title_col, 1)
        v.addLayout(top)

        # separador
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER};"); v.addWidget(sep)

        # campo senha
        lbl_pwd = QLabel("Senha:")
        lbl_pwd.setStyleSheet(f"color:{TEXT_SEC}; font-size:10pt;")
        v.addWidget(lbl_pwd)
        self._edit = QLineEdit()
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit.setPlaceholderText("Introduz a senha do PDF…")
        v.addWidget(self._edit)

        # aviso senha errada
        self._warn = QLabel("⚠  Senha incorrecta. Tenta novamente.")
        self._warn.setStyleSheet("color:#F87171; font-size:9pt;")
        self._warn.setVisible(wrong)
        v.addWidget(self._warn)

        # botões
        btns = QHBoxLayout(); btns.setSpacing(8)
        btns.addStretch()
        ca = QPushButton("Cancelar"); ca.setFixedHeight(36)
        ca.clicked.connect(self.reject)
        ok = QPushButton("  Abrir  "); ok.setObjectName("btn_primary")
        ok.setFixedHeight(36); ok.clicked.connect(self.accept)
        self._edit.returnPressed.connect(self.accept)
        btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)

    def password(self) -> str:
        return self._edit.text()


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


class _NoteDialog(QDialog):
    """Popup para escrever um comentário estilo Adobe."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Adicionar comentário"); self.setModal(True)
        self.setMinimumWidth(360)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Comentário:"))
        self.edit = QTextEdit()
        self.edit.setPlaceholderText("Escreve o comentário aqui…")
        self.edit.setMinimumHeight(90)
        v.addWidget(self.edit)
        btns = QHBoxLayout()
        ok = QPushButton("OK"); ok.setObjectName("btn_primary"); ok.clicked.connect(self.accept)
        ca = QPushButton("Cancelar"); ca.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)


class TabEditar(QWidget):
    """Editor visual: clica/arrasta directamente no PDF renderizado."""

    _HI_COLORS  = {"Amarelo": (1,1,0), "Verde": (0,1,0), "Rosa": (1,0.4,0.7), "Azul claro": (0.5,0.8,1)}
    _RED_FILLS  = {"Preto": (0,0,0), "Branco": (1,1,1), "Cinzento": (0.5,0.5,0.5)}
    _MODE_DEFS = [
        ("Redigir / Censurar",    "fa5s.eraser"),
        ("Adicionar texto",       "fa5s.font"),
        ("Adicionar imagem",      "fa5s.image"),
        ("Destacar (highlight)",  "fa5s.highlighter"),
        ("Nota / Comentario",     "fa5s.sticky-note"),
        ("Preencher formularios", "fa5s.clipboard-list"),
    ]

    def __init__(self, status_fn):
        super().__init__()
        self._status   = status_fn
        self._pending  = []
        self._doc_path = None
        self._mode_idx = 0
        self.setObjectName("content_area")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        root.addWidget(ToolHeader("fa5s.edit", "Editar PDF",
                                  "Clica ou arrasta directamente no PDF para editar."))

        # body: canvas esquerda | controlos direita
        body = QSplitter(Qt.Orientation.Horizontal)

        self._canvas = PdfEditCanvas()
        self._canvas.rect_selected.connect(self._on_rect)
        self._canvas.point_clicked.connect(self._on_point)
        canvas_scroll = QScrollArea()
        canvas_scroll.setFrameShape(QFrame.Shape.NoFrame)
        canvas_scroll.setWidgetResizable(False)
        canvas_scroll.setWidget(self._canvas)
        canvas_scroll.setMinimumWidth(320)
        canvas_scroll.viewport().installEventFilter(self)
        self._canvas_scroll = canvas_scroll
        body.addWidget(canvas_scroll)

        # painel de controlos (scrollavel)
        ctrl_inner = QWidget(); ctrl_inner.setObjectName("scroll_inner")
        ctrl_inner.setMinimumWidth(0)
        cv = QVBoxLayout(ctrl_inner); cv.setContentsMargins(10, 10, 10, 10); cv.setSpacing(8)
        cv.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        # -- Ficheiro PDF --
        grp_file = QGroupBox("Ficheiro PDF")
        gf = QVBoxLayout(grp_file); gf.setSpacing(4)
        self._drop_in = DropFileEdit()
        self._drop_in.btn.clicked.disconnect()
        self._drop_in.btn.clicked.connect(self._pick_pdf)
        self._drop_in.path_changed.connect(self._load_pdf)
        self._drop_in._clr.clicked.connect(self._close_pdf)
        self._lbl_info = info_lbl()
        gf.addWidget(self._drop_in); gf.addWidget(self._lbl_info)
        cv.addWidget(grp_file)

        # -- Pagina --
        grp_page = QGroupBox("Pagina")
        gp = QHBoxLayout(grp_page); gp.setSpacing(6)
        self._btn_prev = QPushButton()
        self._btn_prev.setIcon(qta.icon("fa5s.chevron-left", color=TEXT_PRI))
        self._btn_prev.setFixedSize(28, 28); self._btn_prev.setObjectName("viewer_nav_btn")
        self._btn_prev.clicked.connect(self._prev_page)
        self._lbl_page = QLabel("---"); self._lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_next = QPushButton()
        self._btn_next.setIcon(qta.icon("fa5s.chevron-right", color=TEXT_PRI))
        self._btn_next.setFixedSize(28, 28); self._btn_next.setObjectName("viewer_nav_btn")
        self._btn_next.clicked.connect(self._next_page)
        gp.addWidget(self._btn_prev); gp.addWidget(self._lbl_page, 1); gp.addWidget(self._btn_next)
        cv.addWidget(grp_page)
        self._page_idx = 0

        # -- Modo de edicao --
        grp_mode = QGroupBox("Modo de edicao")
        gm = QGridLayout(grp_mode); gm.setSpacing(4)
        self._mode_btns: list[QPushButton] = []
        self._mode_btn_idx: dict[int, int] = {}   # id(btn) → mode index
        for i, (label, icon_name) in enumerate(self._MODE_DEFS):
            btn = QPushButton(f"  {label}")
            btn.setIcon(qta.icon(icon_name, color=TEXT_SEC))
            btn.setCheckable(True)
            self._mode_btn_idx[id(btn)] = i
            btn.clicked.connect(lambda checked, b=btn: self._on_mode_btn(b))
            self._mode_btns.append(btn)
            gm.addWidget(btn, i, 0)
        self._mode_btns[0].setChecked(True)
        self._mode_btns[0].setIcon(qta.icon(self._MODE_DEFS[0][1], color=ACCENT))
        self._mode_btns[0].setStyleSheet(
            f"background:#0D3D38; border:1px solid {ACCENT}; "
            f"color:{ACCENT}; border-radius:6px; padding:6px 8px; text-align:center;")
        cv.addWidget(grp_mode)

        # -- Opcoes por modo --
        grp_opts = QGroupBox("Opcoes")
        go = QVBoxLayout(grp_opts); go.setContentsMargins(6, 6, 6, 6)
        self._opt_stack = QStackedWidget()

        # 0 - Redigir
        w0 = QWidget(); v0 = QVBoxLayout(w0); v0.setContentsMargins(0,4,0,0); v0.setSpacing(4)
        v0.addWidget(QLabel("Cor:"))
        self._red_color = QComboBox(); self._red_color.addItems(list(self._RED_FILLS.keys()))
        v0.addWidget(self._red_color)
        hint0 = QLabel("Arrasta para selecionar a area."); hint0.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v0.addWidget(hint0); v0.addStretch()
        self._opt_stack.addWidget(w0)

        # 1 - Texto
        w1 = QWidget(); v1 = QVBoxLayout(w1); v1.setContentsMargins(0,4,0,0)
        hint1 = QLabel("Clica no PDF para posicionar.\nAs opcoes surgem num popup.")
        hint1.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v1.addWidget(hint1); v1.addStretch()
        self._opt_stack.addWidget(w1)

        # 2 - Imagem
        w2 = QWidget(); v2 = QVBoxLayout(w2); v2.setContentsMargins(0,4,0,0); v2.setSpacing(4)
        v2.addWidget(QLabel("Imagem:"))
        self._img_drop = DropFileEdit(placeholder="Arrasta imagem aqui...",
                                      filters="Imagens (*.png *.jpg *.jpeg *.bmp *.tiff *.webp)")
        self._img_drop.btn.clicked.disconnect()
        self._img_drop.btn.clicked.connect(self._pick_image)
        v2.addWidget(self._img_drop)
        hint2 = QLabel("Arrasta no PDF para definir a area."); hint2.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v2.addWidget(hint2); v2.addStretch()
        self._opt_stack.addWidget(w2)

        # 3 - Highlight
        w3 = QWidget(); v3 = QVBoxLayout(w3); v3.setContentsMargins(0,4,0,0); v3.setSpacing(4)
        v3.addWidget(QLabel("Cor:"))
        self._hi_color = QComboBox(); self._hi_color.addItems(list(self._HI_COLORS.keys()))
        v3.addWidget(self._hi_color)
        hint3 = QLabel("Arrasta para selecionar o texto."); hint3.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v3.addWidget(hint3); v3.addStretch()
        self._opt_stack.addWidget(w3)

        # 4 - Nota
        w4 = QWidget(); v4 = QVBoxLayout(w4); v4.setContentsMargins(0,4,0,0); v4.setSpacing(4)
        v4.addWidget(QLabel("Texto da nota:"))
        self._note_txt = QTextEdit(); self._note_txt.setMaximumHeight(80)
        v4.addWidget(self._note_txt)
        hint4 = QLabel("Clica no PDF para posicionar."); hint4.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v4.addWidget(hint4); v4.addStretch()
        self._opt_stack.addWidget(w4)

        # 5 - Formularios
        w5 = QWidget(); v5 = QVBoxLayout(w5); v5.setContentsMargins(0,4,0,0); v5.setSpacing(4)
        v5.addWidget(QLabel("Campos detectados:"))
        self._form_table = QTableWidget(0, 2)
        self._form_table.setHorizontalHeaderLabels(["Campo", "Valor"])
        self._form_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._form_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._form_table.setObjectName("pdf_table"); self._form_table.setMinimumHeight(130)
        v5.addWidget(self._form_table)
        self._opt_stack.addWidget(w5)

        go.addWidget(self._opt_stack)
        cv.addWidget(grp_opts)

        # -- Edicoes pendentes --
        grp_pend = QGroupBox("Edicoes pendentes")
        gpe = QVBoxLayout(grp_pend); gpe.setSpacing(4)
        self._pending_list = QListWidget(); self._pending_list.setMaximumHeight(110)
        gpe.addWidget(self._pending_list)
        btn_clear = QPushButton("Limpar tudo"); btn_clear.clicked.connect(self._clear_pending)
        gpe.addWidget(btn_clear)
        cv.addWidget(grp_pend)

        # -- Guardar --
        grp_save = QGroupBox("Guardar em")
        gs = QVBoxLayout(grp_save)
        self._drop_out = DropFileEdit("output_editado.pdf", save=True, default_name="output_editado.pdf")
        gs.addWidget(self._drop_out)
        cv.addWidget(grp_save)
        cv.addStretch()

        # forçar largura mínima zero em todos os groupboxes do painel direito
        for gb in ctrl_inner.findChildren(QGroupBox):
            gb.setMinimumWidth(0)

        ctrl_scroll = QScrollArea()
        ctrl_scroll.setWidgetResizable(True)
        ctrl_scroll.setFrameShape(QFrame.Shape.NoFrame)
        ctrl_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ctrl_scroll.setWidget(ctrl_inner)
        ctrl_scroll.setMinimumWidth(350)
        ctrl_scroll.setMaximumWidth(500)
        body.addWidget(ctrl_scroll)
        body.setSizes([800, 380])
        root.addWidget(body, 1)

        action_bar, _ = ActionBar("Aplicar e Guardar", self._run)
        root.addWidget(action_bar)

        self._update_nav()

    def paintEvent(self, event):
        _paint_bg(self)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent, QTimer
        if obj is self._canvas_scroll.viewport() and event.type() == QEvent.Type.Resize:
            if self._canvas._doc and self._canvas._zoom_factor == 1.0:
                QTimer.singleShot(0, self._canvas._render)
        return super().eventFilter(obj, event)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _update_nav(self):
        n = self._canvas.page_count()
        self._btn_prev.setEnabled(n > 0 and self._page_idx > 0)
        self._btn_next.setEnabled(n > 0 and self._page_idx < n - 1)
        self._lbl_page.setText(f"{self._page_idx+1} / {n}" if n else "—")

    def _prev_page(self):
        if self._page_idx > 0:
            self._page_idx -= 1; self._canvas.set_page(self._page_idx); self._update_nav()
            self._canvas.set_overlays([e for e in self._pending if e["page"] == self._page_idx])

    def _next_page(self):
        if self._page_idx < self._canvas.page_count() - 1:
            self._page_idx += 1; self._canvas.set_page(self._page_idx); self._update_nav()
            self._canvas.set_overlays([e for e in self._pending if e["page"] == self._page_idx])

    def _on_mode_btn(self, btn):
        idx = self._mode_btn_idx.get(id(btn), 0)
        self._mode_idx = idx
        for i, b in enumerate(self._mode_btns):
            active = b is btn
            b.setChecked(active)
            b.setIcon(qta.icon(self._MODE_DEFS[i][1], color=ACCENT if active else TEXT_SEC))
            if active:
                b.setStyleSheet(
                    f"background:#0D3D38; border:1px solid {ACCENT}; "
                    f"color:{ACCENT}; border-radius:6px; padding:6px 8px; text-align:center;")
            else:
                b.setStyleSheet(
                    "background:#18252E; border:1px solid #2A3944; "
                    "color:#93A9A3; border-radius:6px; padding:6px 8px; text-align:center;")
        self._opt_stack.setCurrentIndex(idx)
        if idx == 2:  # Adicionar imagem — abre picker logo
            self._pick_image()


    def _pick_pdf(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if p: self._load_pdf(p)

    def _load_pdf(self, p: str):
        if not p or not os.path.isfile(p):
            return
        self._doc_path = p
        self._drop_in.blockSignals(True)
        self._drop_in.set_path(p)
        self._drop_in.blockSignals(False)
        if not self._drop_out.path():
            self._drop_out.set_path(os.path.splitext(p)[0] + "_editado.pdf")
        self._pending.clear(); self._pending_list.clear()
        try:
            self._canvas.load(p)
        except ModuleNotFoundError as ex:
            QMessageBox.critical(self, "Dependência em falta",
                "A ferramenta Editar requer PyMuPDF.\n\n"
                "Instala com:\n  pip install pymupdf\n\n"
                f"Detalhe: {ex}")
            return
        except Exception as ex:
            QMessageBox.critical(self, "Erro", f"Não foi possível abrir o PDF:\n{ex}"); return
        self._page_idx = 0
        n = self._canvas.page_count()
        self._lbl_info.setText(f"  {n} páginas")
        self._update_nav()
        self._load_form_fields(p)

    def auto_load(self, path: str):
        if path and not self._drop_in.path(): self._load_pdf(path)

    def _close_pdf(self):
        self._doc_path = None
        self._canvas.close_doc()
        self._canvas.set_overlays([])
        self._pending.clear(); self._pending_list.clear()
        self._lbl_info.setText("")
        self._page_idx = 0
        self._update_nav()

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
        mode = self._mode_idx
        if mode in (1, 4):  # modos de clique: usar o centro do rect como ponto
            import fitz
            center = fitz.Point((pdf_rect.x0 + pdf_rect.x1) / 2,
                                (pdf_rect.y0 + pdf_rect.y1) / 2)
            self._on_point(center); return
        if mode == 0:   # redact
            self._add({"type": "redact", "page": self._page_idx, "rect": pdf_rect,
                       "fill": self._RED_FILLS[self._red_color.currentText()]})
        elif mode == 2:  # image
            img = self._img_drop.path()
            if not img or not os.path.isfile(img):
                self._pick_image()
                img = self._img_drop.path()
                if not img or not os.path.isfile(img): return
            self._add({"type": "image", "page": self._page_idx, "rect": pdf_rect, "path": img})
        elif mode == 3:  # highlight
            self._add({"type": "highlight", "page": self._page_idx, "rect": pdf_rect,
                       "color": self._HI_COLORS[self._hi_color.currentText()]})

    def _on_point(self, pdf_pt):
        mode = self._mode_idx
        if mode == 1:   # text
            dlg = _TextDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted: return
            txt = dlg.edit.text().strip()
            if not txt: return
            self._add({"type": "text", "page": self._page_idx, "point": pdf_pt,
                       "text": txt, "size": dlg.font_size.value(), "color": dlg.color_tuple()})
        elif mode == 4:  # note
            dlg = _NoteDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted: return
            txt = dlg.edit.toPlainText().strip()
            if not txt: return
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
        lbl = labels[edit["type"]](edit)
        self._pending_list.addItem(lbl)
        self._status(f"✏  {lbl} adicionado — {len(self._pending)} edição(ões) pendente(s)")
        self._canvas.set_overlays([e for e in self._pending if e["page"] == self._page_idx])

    def _clear_pending(self):
        self._pending.clear(); self._pending_list.clear()
        self._canvas.set_overlays([])

    # ── aplicar ──────────────────────────────────────────────────────────────

    def _run(self):
        if not self._doc_path or not os.path.isfile(self._doc_path):
            QMessageBox.warning(self, "Aviso", "Abre um PDF primeiro."); return
        out = self._drop_out.path()
        if not out:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        if self._mode_idx == 5:
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
