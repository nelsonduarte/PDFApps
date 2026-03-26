"""PDFApps – TabReordenar: reorder PDF pages tool."""

import os

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QAbstractItemView, QPushButton, QFileDialog, QMessageBox,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.i18n import t
from app.utils import section, info_lbl, danger_btn
from app.widgets import DropFileEdit


class TabReordenar(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.sort", t("tool.reorder.name"),
                         t("tool.reorder.desc"),
                         t("tool.reorder.btn"), status_fn)
        self._reader = None
        f = self._form
        f.addWidget(section(t("tool.reorder.source")))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox(t("tool.reorder.list"))
        vl  = QVBoxLayout(grp); vl.setSpacing(8)
        self.lst = QListWidget()
        self.lst.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.lst.setAlternatingRowColors(True)
        self.lst.setMinimumHeight(200)
        vl.addWidget(self.lst)
        hb = QHBoxLayout()
        for txt, slot in [(t("btn.up"), self._up), (t("btn.down"), self._dn),
                          (t("btn.delete"), self._del), (t("btn.reset_order"), self._reset)]:
            btn = danger_btn(txt) if "Delete" in txt or "Apagar" in txt else QPushButton(txt)
            btn.clicked.connect(slot); hb.addWidget(btn)
        hb.addStretch(); vl.addLayout(hb)
        f.addWidget(grp)

        f.addWidget(section(t("tool.reorder.output")))
        self.drop_out = DropFileEdit("reordered.pdf", save=True, default_name="reordered.pdf")
        f.addWidget(self.drop_out); f.addStretch()

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), "", t("file_filter.pdf"))
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_reordered" + ext)
        try:
            reader = PdfReader(p); self._reader = reader
            n = len(reader.pages); self.lbl_info.setText(f"  {n} pages")
            self._populate(list(range(n)))
        except Exception as e: self.lbl_info.setText(f"  Error: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _populate(self, indices: list):
        self.lst.clear()
        for i in indices:
            item = QListWidgetItem(t("tool.reorder.page", n=i + 1))
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
            QMessageBox.warning(self, t("msg.warning"), t("msg.open_pdf_first")); return
        out = self.drop_out.path()
        if not out:
            QMessageBox.warning(self, t("msg.warning"), t("msg.choose_output")); return
        try:
            indices = [self.lst.item(i).data(256) for i in range(self.lst.count())]
            w = PdfWriter()
            for idx in indices: w.add_page(self._reader.pages[idx])
            with open(out, "wb") as f: w.write(f)
            self._status(f"✔  PDF reordered: {os.path.basename(out)}")
            QMessageBox.information(self, "Done", f"PDF saved at:\n{out}")
        except Exception as e: QMessageBox.critical(self, "Error", str(e))
