"""PDFApps – TabRotar: rotate PDF pages tool."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QLineEdit, QComboBox, QFileDialog, QMessageBox,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.utils import section, info_lbl, parse_pages
from app.widgets import DropFileEdit


class TabRotar(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.sync-alt", "Rotate pages",
                         "Rotate one or all pages of the PDF.",
                         "Rotate and save", status_fn)
        f = self._form
        f.addWidget(section("Source file"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox("Rotation options")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pages = QLineEdit()
        self.edit_pages.setPlaceholderText("e.g.: 1,3,5-8  (empty = all)")
        self.cmb_angle = QComboBox()
        self.cmb_angle.addItems(["90°  (clockwise)",
                                  "180°",
                                  "270°  (counter-clockwise)"])
        form.addRow("Pages:", self.edit_pages)
        form.addRow("Angle:", self.cmb_angle)
        f.addWidget(grp)

        f.addWidget(section("Output file"))
        self.drop_out = DropFileEdit("rotated.pdf", save=True, default_name="rotated.pdf")
        f.addWidget(self.drop_out); f.addStretch()

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF (*.pdf)")
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_rotated" + ext)
        try:
            r = PdfReader(p); self.lbl_info.setText(f"  {len(r.pages)} pages")
        except Exception as e: self.lbl_info.setText(f"  Error: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _run(self):
        pdf_path = self.drop_in.path(); out_path = self.drop_out.path()
        angle = {0: 90, 1: 180, 2: 270}[self.cmb_angle.currentIndex()]
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Warning", "Select a valid PDF."); return
        if not out_path:
            QMessageBox.warning(self, "Warning", "Choose the output file."); return
        try:
            reader = PdfReader(pdf_path); total = len(reader.pages)
            txt = self.edit_pages.text().strip()
            pages = parse_pages(txt, total) if txt else list(range(total))
            w = PdfWriter()
            for i, page in enumerate(reader.pages):
                if i in pages: page.rotate(angle)
                w.add_page(page)
            with open(out_path, "wb") as f: w.write(f)
            self._status(f"✔  PDF rotated: {os.path.basename(out_path)}")
            QMessageBox.information(self, "Done", f"PDF saved at:\n{out_path}")
        except Exception as e: QMessageBox.critical(self, "Error", str(e))
