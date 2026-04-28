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
from app.constants import DESKTOP
from app.widgets import DropFileEdit


class TabReordenar(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.sort", t("tool.reorder.name"),
                         t("tool.reorder.desc"),
                         t("tool.reorder.btn"), status_fn)
        self._pipeline_supported = True
        self._page_count = 0
        f = self._form
        sec_src = section(t("tool.reorder.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try: self.drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
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
        for txt, slot, tip in [
            ("▲",  self._up,    t("btn.up")),
            ("▼",  self._dn,    t("btn.down")),
            ("−",  self._del,   t("btn.delete")),
            ("↺",  self._reset, t("btn.reset_order")),
        ]:
            btn = danger_btn(txt) if slot == self._del else QPushButton(txt)
            btn.setToolTip(tip)
            btn.setFixedWidth(40)
            btn.clicked.connect(slot); hb.addWidget(btn)
        hb.addStretch(); vl.addLayout(hb)
        f.addWidget(grp)

        sec_out = section(t("tool.reorder.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit("reordered.pdf", save=True, default_name="reordered.pdf")
        f.addWidget(self.drop_out); f.addStretch()
        self._compact_hidden = [sec_src, self.drop_in, self.lbl_info]
        sec_out.setVisible(False)
        self.drop_out.setVisible(False)

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_reordered" + ext)
        try:
            with open(p, "rb") as fh:
                reader = PdfReader(fh)
                n = len(reader.pages)
            self._page_count = n
            self.lbl_info.setText(t("edit.status.pages", n=n))
            self._populate(list(range(n)))
        except Exception as e:
            self._page_count = 0
            self.lbl_info.setText(t("tool.split.error_info", e=e))

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
        if self._page_count: self._populate(list(range(self._page_count)))

    def _run(self):
        if not self._page_count:
            QMessageBox.warning(self, t("msg.warning"), t("msg.open_pdf_first")); return
        out = self._resolve_output_file(self.drop_out, self.drop_in.path())
        if not out: return
        try:
            indices = [self.lst.item(i).data(256) for i in range(self.lst.count())]
            with open(self.drop_in.path(), "rb") as fin:
                reader = PdfReader(fin)
                w = PdfWriter()
                for idx in indices: w.add_page(reader.pages[idx])
                with open(out, "wb") as f: w.write(f)
            self._status(f"✔  → {os.path.basename(out)}")
            msg = t("tool.reorder.done", path=out)
            if self._pipeline_active:
                self._pipeline_success(msg, out)
            else:
                QMessageBox.information(self, t("msg.done"), msg)
        except Exception as e: QMessageBox.critical(self, t("msg.error"), str(e))
