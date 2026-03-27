"""PDFApps – reusable drop-zone widgets."""

import os

from PySide6.QtCore import Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QFileDialog,
)
import qtawesome as qta

from app.constants import ACCENT, DESKTOP
from app.i18n import t


class DropFileEdit(QWidget):
    """File field with drag & drop, status icon and clear button."""

    path_changed = Signal(str)

    def __init__(self, placeholder=None,
                 filters=None,
                 save=False, default_name="result.pdf"):
        super().__init__()
        self._filters      = filters or t("file_filter.pdf")
        self._save         = save
        self._default      = default_name
        self._path_value   = ""
        self._placeholder  = placeholder or t("widget.drop_hint")
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

    # ── drag & drop ──────────────────────────────────────────────────────────
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
        lbl = QLabel()
        lbl.setPixmap(qta.icon('fa5s.folder-open', color='#4A5568').pixmap(20, 20))
        lbl.setObjectName("drop_icon")
        lbl.setFixedWidth(26)
        h.addWidget(lbl)
        self._lbl = QLabel(t("widget.drop_multi"))
        self._lbl.setObjectName("drop_zone_lbl")
        h.addWidget(self._lbl, 1)
        self.btn = QPushButton(t("btn.add"))
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
