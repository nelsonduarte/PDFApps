"""PDFApps – TabJuntar: merge PDFs tool."""

import os

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QAbstractItemView, QPushButton, QMessageBox,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.i18n import t
from app.utils import section, danger_btn, pick_pdfs
from app.widgets import DropFileEdit, MultiDropWidget


class TabJuntar(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.object-group", t("tool.merge.name"),
                         t("tool.merge.desc"),
                         t("tool.merge.btn"), status_fn)
        # Per-file password map. BasePage._pdf_password is single-string;
        # merge needs one password per input PDF since they may differ.
        self._pwd_map: dict[str, str] = {}
        f = self._form

        grp = QGroupBox(t("tool.merge.list"))
        vl  = QVBoxLayout(grp); vl.setSpacing(8)
        self.drop_multi = MultiDropWidget(self._on_drop)
        self.drop_multi.btn.clicked.connect(self._add_files)
        vl.addWidget(self.drop_multi)
        self.lst = QListWidget()
        self.lst.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.lst.setAlternatingRowColors(True)
        self.lst.setMinimumHeight(180)
        self.lst.setMinimumWidth(0)
        from PySide6.QtCore import Qt as _Qt
        self.lst.setHorizontalScrollBarPolicy(_Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lst.setTextElideMode(_Qt.TextElideMode.ElideMiddle)
        vl.addWidget(self.lst)
        hb = QHBoxLayout()
        for icon, slot, tip in [
            ("▲", self._up,         t("btn.up")),
            ("▼", self._dn,         t("btn.down")),
            ("−", self._remove,     t("btn.remove")),
            ("✕", self._clear_all,  t("btn.clear")),
        ]:
            btn = danger_btn(icon) if slot == self._remove else QPushButton(icon)
            btn.setToolTip(tip)
            btn.setFixedWidth(40)
            btn.clicked.connect(slot); hb.addWidget(btn)
        hb.addStretch(); vl.addLayout(hb)
        f.addWidget(grp)

        f.addWidget(section(t("tool.merge.output")))
        self.drop_out = DropFileEdit(save=True, default_name="merged.pdf")
        f.addWidget(self.drop_out)
        f.addStretch()

    def _add_path(self, p: str) -> bool:
        """Prompt for password if encrypted, store it, append to list."""
        if not self._maybe_prompt_password(p):
            return False
        self._pwd_map[p] = self._pdf_password
        self.lst.addItem(QListWidgetItem(p))
        return True

    def _on_drop(self, paths: list):
        for p in paths:
            self._add_path(p)

    def _add_files(self):
        for p in pick_pdfs(self):
            self._add_path(p)

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
        if r >= 0:
            item = self.lst.takeItem(r)
            self._pwd_map.pop(item.text(), None)

    def _clear_all(self):
        self.lst.clear()
        self._pwd_map.clear()

    def auto_load(self, path: str):
        if not path: return
        existing = [self.lst.item(i).text() for i in range(self.lst.count())]
        if path not in existing:
            self._add_path(path)

    def _run(self):
        paths = [self.lst.item(i).text() for i in range(self.lst.count())]
        if len(paths) < 2:
            QMessageBox.warning(self, t("msg.warning"), t("tool.merge.min2")); return
        # Validate all files exist before starting
        missing = [p for p in paths if not os.path.isfile(p)]
        if missing:
            QMessageBox.critical(self, t("msg.error"),
                                 t("tool.merge.missing_files", files="\n".join(missing)))
            return
        out = self._resolve_output_file(self.drop_out, paths[0])
        if not out: return
        try:
            w = PdfWriter()
            for p in paths:
                reader = PdfReader(p)
                if reader.is_encrypted:
                    pwd = self._pwd_map.get(p, "")
                    if pwd:
                        reader.decrypt(pwd)
                for page in reader.pages:
                    w.add_page(page)
            with open(out, "wb") as f: w.write(f)
            self._status(f"✔  PDF → {os.path.basename(out)}")
            QMessageBox.information(self, t("msg.done"), t("tool.merge.done", path=out))
        except Exception as e: QMessageBox.critical(self, t("msg.error"), str(e))
