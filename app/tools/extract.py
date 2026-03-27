"""PDFApps – TabExtrair: extract PDF pages tool."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QLineEdit, QLabel, QFileDialog, QMessageBox,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.i18n import t
from app.utils import section, info_lbl, parse_pages
from app.widgets import DropFileEdit


class TabExtrair(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.file-export", t("tool.extract.name"),
                         t("tool.extract.desc"),
                         t("tool.extract.btn"), status_fn)
        f = self._form
        f.addWidget(section(t("tool.extract.source")))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox(t("tool.extract.section"))
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pages = QLineEdit()
        self.edit_pages.setPlaceholderText(t("tool.extract.hint"))
        hint = QLabel(t("tool.extract.help"))
        hint.setObjectName("info_lbl")
        form.addRow(t("tool.extract.pages_label"), self.edit_pages)
        form.addRow("", hint)
        f.addWidget(grp)

        f.addWidget(section(t("tool.extract.output")))
        self.drop_out = DropFileEdit("extracted.pdf", save=True, default_name="extracted.pdf")
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
            self.drop_out.set_path(base + "_extracted" + ext)
        try:
            r = PdfReader(p); self.lbl_info.setText(t("edit.status.pages", n=len(r.pages)))
        except Exception as e: self.lbl_info.setText(t("tool.split.error_info", e=e))

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _run(self):
        pdf_path = self.drop_in.path(); out_path = self.drop_out.path()
        txt = self.edit_pages.text().strip()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.select_valid_pdf")); return
        if not txt:
            QMessageBox.warning(self, t("msg.warning"), t("tool.extract.specify")); return
        if not out_path:
            QMessageBox.warning(self, t("msg.warning"), t("msg.choose_output")); return
        try:
            reader = PdfReader(pdf_path)
            pages  = parse_pages(txt, len(reader.pages))
            w = PdfWriter()
            for p in pages: w.add_page(reader.pages[p])
            with open(out_path, "wb") as f: w.write(f)
            self._status(f"✔  {len(pages)} → {os.path.basename(out_path)}")
            QMessageBox.information(self, t("msg.done"),
                t("tool.extract.done", n=len(pages), path=out_path))
        except Exception as e: QMessageBox.critical(self, t("msg.error"), str(e))
