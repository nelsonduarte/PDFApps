"""PDFApps – stylesheet strings (dark + light themes)."""

from app.constants import (
    ACCENT, ACCENT_H, ACCENT_P,
    BG_BASE, BG_SIDE, BG_CARD, BG_INPUT, BG_INNER,
    BORDER, TEXT_PRI, TEXT_SEC,
    _LA, _LAH, _LAP, _LB, _LS, _LC, _LI, _LN, _LO, _LP, _LQ,
)

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
#viewer_sel_status  {{ font-size: 9pt; color: {TEXT_SEC}; background: {BG_CARD};
                       border-top: 1px solid {BORDER}; padding: 4px 8px; }}
QPdfView {{ background: {BG_INNER}; border: none; }}
QSplitter::handle {{ background: {BORDER}; width: 1px; }}

#theme_btn {{
    background: #1B2B35; border: 1px solid {BORDER}; border-radius: 14px;
    font-size: 13pt; padding: 0; min-width: 28px; max-width: 28px;
}}
#theme_btn:hover {{ background: #253945; border-color: #476573; }}
"""

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
#viewer_sel_status  {{ font-size: 9pt; color: {_LQ}; background: {_LC};
                       border-top: 1px solid {_LO}; padding: 4px 8px; }}
QPdfView {{ background: {_LN}; border: none; }}
QSplitter::handle {{ background: {_LO}; width: 1px; }}

#theme_btn {{
    background: #E7F0ED; border: 1px solid #BFD4CD; border-radius: 14px; font-size: 13pt;
    padding: 0; min-width: 28px; max-width: 28px;
}}
#theme_btn:hover {{ background: #DBEAE5; border-color: #9FC2B8; }}
"""
