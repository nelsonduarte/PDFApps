"""PDFApps – TabDividir: split PDF tool."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSpinBox, QPushButton, QFileDialog, QMessageBox,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.i18n import t
from app.utils import section, info_lbl, danger_btn, pick_folder
from app.constants import DESKTOP
from app.widgets import DropFileEdit


class TabDividir(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.cut", t("tool.split.name"),
                         t("tool.split.desc"),
                         t("tool.split.btn"), status_fn)
        self._total = 0
        f = self._form

        sec_src = section(t("tool.split.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try: self.drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in)
        f.addWidget(self.lbl_info)

        grp = QGroupBox(t("tool.split.ranges"))
        vt  = QVBoxLayout(grp); vt.setSpacing(8)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([t("tool.split.start"), t("tool.split.end"), ""])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setFixedHeight(160)
        vt.addWidget(self.table)
        hb = QHBoxLayout()
        btn_add = QPushButton(t("btn.add_row"))
        btn_rem = danger_btn(t("btn.remove"))
        btn_add.clicked.connect(self._add_row)
        btn_rem.clicked.connect(self._remove_row)
        hb.addWidget(btn_add); hb.addWidget(btn_rem); hb.addStretch()
        vt.addLayout(hb)
        f.addWidget(grp)

        sec_out = section(t("tool.split.output_folder"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit(t("tool.split.folder_hint"))
        self.drop_out.btn.setText(t("btn.choose"))
        try: self.drop_out.btn.clicked.disconnect()
        except RuntimeError: pass
        self.drop_out.btn.clicked.connect(self._pick_output)
        f.addWidget(self.drop_out)
        f.addStretch()
        self._add_row()
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
        if not self.drop_out.path(): self.drop_out.set_path(os.path.dirname(p))
        try:
            r = PdfReader(p); self._total = len(r.pages)
            self.lbl_info.setText(t("tool.split.pages_info", n=self._total))
        except Exception as e: self.lbl_info.setText(t("tool.split.error_info", e=e))

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
        self.table.setItem(r, 2, QTableWidgetItem(f"part_{r+1}.pdf"))

    def _remove_row(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def _run(self):
        pdf_path = self.drop_in.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.select_valid_pdf")); return
        out_dir = self._resolve_output_dir(self.drop_out, pdf_path)
        if not out_dir:
            return
        try:
            reader = PdfReader(pdf_path); total = len(reader.pages)
        except Exception as e:
            QMessageBox.critical(self, t("msg.error"), str(e)); return
        os.makedirs(out_dir, exist_ok=True)
        errors, generated = [], []
        for r in range(self.table.rowCount()):
            start = self.table.cellWidget(r, 0).value()
            end   = self.table.cellWidget(r, 1).value()
            import re as _re
            name  = self.table.item(r, 2).text().strip() or f"part_{r+1}.pdf"
            name = os.path.basename(name)  # prevent path traversal
            name = _re.sub(r'[^\w\-. ]', '_', name)  # strip unsafe chars
            if not name or name.startswith('.'):
                name = f"part_{r+1}.pdf"
            if not name.lower().endswith(".pdf"): name += ".pdf"
            if start < 1 or end < start or end > total:
                errors.append(f"Row {r+1}: {start}–{end} invalid"); continue
            w = PdfWriter()
            for p in range(start - 1, end): w.add_page(reader.pages[p])
            with open(os.path.join(out_dir, name), "wb") as f: w.write(f)
            generated.append(name)
        if errors: QMessageBox.warning(self, t("msg.warning"), t("tool.split.skipped", errors="\n".join(errors)))
        if generated:
            self._status(f"✔  {len(generated)} file(s) → {out_dir}")
            QMessageBox.information(self, t("msg.done"),
                t("tool.split.done", n=len(generated), folder=out_dir, files="\n".join(generated)))
