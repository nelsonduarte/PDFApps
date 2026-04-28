"""PDFApps – TabRotar: rotate PDF pages tool."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QLineEdit, QComboBox, QFileDialog, QMessageBox,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.i18n import t
from app.utils import section, info_lbl, parse_pages
from app.constants import DESKTOP
from app.widgets import DropFileEdit


class TabRotar(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.sync-alt", t("tool.rotate.name"),
                         t("tool.rotate.desc"),
                         t("tool.rotate.btn"), status_fn)
        self._pipeline_supported = True
        f = self._form
        sec_src = section(t("tool.rotate.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try: self.drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox(t("tool.rotate.options"))
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pages = QLineEdit()
        self.edit_pages.setPlaceholderText(t("tool.rotate.pages_hint"))
        self.cmb_angle = QComboBox()
        self.cmb_angle.addItems([t("tool.rotate.90"), t("tool.rotate.180"), t("tool.rotate.270")])
        form.addRow(t("tool.rotate.pages_label"), self.edit_pages)
        form.addRow(t("tool.rotate.angle_label"), self.cmb_angle)
        f.addWidget(grp)

        sec_out = section(t("tool.rotate.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit("rotated.pdf", save=True, default_name="rotated.pdf")
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
        if not self._maybe_prompt_password(p):
            self.drop_in.blockSignals(True); self.drop_in.set_path("")
            self.drop_in.blockSignals(False); return
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_rotated" + ext)
        try:
            r = self._open_reader(p); self.lbl_info.setText(t("edit.status.pages", n=len(r.pages)))
        except Exception as e: self.lbl_info.setText(t("tool.split.error_info", e=e))

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _run(self):
        pdf_path = self.drop_in.path()
        angle = {0: 90, 1: 180, 2: 270}[self.cmb_angle.currentIndex()]
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.select_valid_pdf")); return
        out_path = self._resolve_output_file(self.drop_out, pdf_path)
        if not out_path: return
        try:
            reader = self._open_reader(pdf_path); total = len(reader.pages)
            txt = self.edit_pages.text().strip()
            pages = parse_pages(txt, total) if txt else list(range(total))
            w = PdfWriter()
            for i, page in enumerate(reader.pages):
                if i in pages: page.rotate(angle)
                w.add_page(page)
            with open(out_path, "wb") as f: w.write(f)
            self._status(f"✔  PDF → {os.path.basename(out_path)}")
            if self._pipeline_active:
                self._pipeline_success(t("tool.rotate.done", path=out_path), out_path)
            else:
                QMessageBox.information(self, t("msg.done"), t("tool.rotate.done", path=out_path))
        except Exception as e: QMessageBox.critical(self, t("msg.error"), str(e))
