"""PDFApps – reusable widgets: drop-zone, color picker."""

import os

from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QColor, QPixmap, QPainter
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QFileDialog, QColorDialog,
)
import qtawesome as qta

from app.constants import ACCENT, DESKTOP
from app.i18n import t


def _drop_icon(icon_name: str, color: str) -> QPushButton:
    """Create a small flat icon button for drop zones."""
    b = QPushButton()
    b.setIcon(qta.icon(icon_name, color=color))
    b.setIconSize(QSize(18, 18))
    b.setFixedSize(26, 26)
    b.setObjectName("drop_icon")
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setCursor(Qt.CursorShape.ArrowCursor)
    return b


class DropFileEdit(QWidget):
    """File field with drag & drop, status icon and clear button."""

    path_changed = Signal(str)

    def __init__(self, placeholder=None,
                 filters=None,
                 save=False, default_name="result.pdf"):
        super().__init__()
        self._filters      = filters or t("file_filter.pdf")
        self._accept_exts  = self._parse_extensions(self._filters)
        self._save         = save
        self._default      = default_name
        self._path_value   = ""
        self._placeholder  = placeholder or t("widget.drop_hint")
        self.setAcceptDrops(True)
        self.setObjectName("drop_zone")

        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 10, 10)
        h.setSpacing(10)

        self._ico = _drop_icon('fa5s.cloud-upload-alt', '#4A5568')
        h.addWidget(self._ico)

        self._lbl = QLabel(placeholder)
        self._lbl.setObjectName("drop_zone_lbl")
        self._lbl.setWordWrap(True)
        self._lbl.setMinimumWidth(0)
        h.addWidget(self._lbl, 1)
        self.setMinimumWidth(0)

        self._clr = QPushButton()
        self._clr.setIcon(qta.icon('fa5s.times', color='#4A5568'))
        self._clr.setObjectName("drop_clear")
        self._clr.setFixedSize(24, 24)
        self._clr.setVisible(False)
        self._clr.clicked.connect(self.clear)
        h.addWidget(self._clr)

        self.btn = QPushButton(t("widget.save_as") if save else t("widget.open"))
        self.btn.setFixedWidth(140 if save else 110)
        self.btn.clicked.connect(self._browse)
        h.addWidget(self.btn)

    # ── API ──────────────────────────────────────────────────────────────────
    def path(self) -> str:
        return self._path_value

    def set_path(self, p: str):
        self._path_value = p
        name = os.path.basename(p)
        self._lbl.setText(f"  {name}")
        self.path_changed.emit(p)
        self._lbl.setToolTip(p)
        self._lbl.setProperty("has_file", "true")
        self._ico.setIcon(qta.icon('fa5s.file-pdf', color=ACCENT))
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
        self._ico.setIcon(qta.icon('fa5s.cloud-upload-alt', color='#4A5568'))
        self._ico.setProperty("has_file", "false")
        self._clr.setIcon(qta.icon('fa5s.times', color='#4A5568'))
        self._clr.setVisible(False)
        for w in (self._lbl, self._ico):
            w.style().unpolish(w); w.style().polish(w)

    # ── drag & drop ──────────────────────────────────────────────────────────
    @staticmethod
    def _parse_extensions(filter_str: str) -> tuple:
        """Extract accepted extensions from a Qt file filter like
        'PDF Files (*.pdf);;All (*.*)'. Uses only the primary group
        (before ';;'). Returns () if the filter is empty or only '*.*'."""
        import re
        if not filter_str:
            return ()
        first = filter_str.split(";;")[0]
        exts = tuple("." + m.lower()
                     for m in re.findall(r"\*\.([A-Za-z0-9]+)", first))
        return () if not exts or exts == (".*",) else exts

    def _url_accepted(self, url) -> bool:
        if not self._accept_exts:
            return True
        return url.toLocalFile().lower().endswith(self._accept_exts)

    def dragEnterEvent(self, e: QDragEnterEvent):
        urls = e.mimeData().urls() if e.mimeData().hasUrls() else []
        if urls and self._url_accepted(urls[0]):
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
        if urls and self._url_accepted(urls[0]):
            self.set_path(urls[0].toLocalFile())

    def _browse(self):
        if self._save:
            p, _ = QFileDialog.getSaveFileName(self, t("widget.save_as"), self._default, self._filters)
        else:
            p, _ = QFileDialog.getOpenFileName(self, t("widget.open_file"), DESKTOP, self._filters)
        if p:
            self.set_path(p)


class MultiDropWidget(QWidget):
    """Drop zone for multiple PDFs."""

    def __init__(self, on_drop_callback):
        super().__init__()
        self._cb = on_drop_callback
        self.setAcceptDrops(True)
        self.setObjectName("drop_zone")
        self.setMinimumHeight(48)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 10, 10)
        h.setSpacing(10)
        ico = _drop_icon('fa5s.folder-open', '#4A5568')
        h.addWidget(ico)
        self._lbl = QLabel(t("widget.drop_multi"))
        self._lbl.setObjectName("drop_zone_lbl")
        self._lbl.setWordWrap(True)
        self._lbl.setMinimumWidth(0)
        h.addWidget(self._lbl, 1)
        self.btn = QPushButton(t("btn.add"))
        self.btn.setFixedWidth(110)
        h.addWidget(self.btn)
        self.setMinimumWidth(0)

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


class ColorPickerButton(QPushButton):
    """Button that shows a color swatch and opens QColorDialog on click."""

    color_changed = Signal(tuple)  # emits (r, g, b) as 0.0-1.0 floats

    def __init__(self, initial: tuple = (0, 0, 0), parent=None):
        super().__init__(parent)
        self._color = initial  # (r, g, b) 0.0-1.0
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._update_swatch()

    def color_tuple(self) -> tuple:
        return self._color

    def set_color(self, rgb: tuple):
        self._color = rgb
        self._update_swatch()

    def _update_swatch(self):
        r, g, b = self._color
        hex_c = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
        # Determine text color based on luminance
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        txt = "#FFFFFF" if lum < 0.5 else "#000000"
        self.setStyleSheet(
            f"QPushButton {{ background: {hex_c}; color: {txt}; border: 1px solid #888;"
            f" border-radius: 4px; padding: 2px 10px; font-size: 10pt; }}"
            f"QPushButton:hover {{ border-color: {ACCENT}; }}")
        self.setText(hex_c.upper())

    def _pick(self):
        r, g, b = self._color
        initial = QColor(int(r * 255), int(g * 255), int(b * 255))
        color = QColorDialog.getColor(initial, self, t("edit.color"))
        if color.isValid():
            self._color = (color.redF(), color.greenF(), color.blueF())
            self._update_swatch()
            self.color_changed.emit(self._color)
