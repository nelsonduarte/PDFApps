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
        super().__init__("fa5s.sync-alt", "Rodar páginas",
                         "Roda uma ou todas as páginas do PDF.",
                         "Rodar e guardar", status_fn)
        f = self._form
        f.addWidget(section("Ficheiro de origem"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox("Opções de rotação")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pages = QLineEdit()
        self.edit_pages.setPlaceholderText("ex: 1,3,5-8  (vazio = todas)")
        self.cmb_angle = QComboBox()
        self.cmb_angle.addItems(["90°  (sentido horário)",
                                  "180°",
                                  "270°  (sentido anti-horário)"])
        form.addRow("Páginas:", self.edit_pages)
        form.addRow("Ângulo:", self.cmb_angle)
        f.addWidget(grp)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit("rotado.pdf", save=True, default_name="rotado.pdf")
        f.addWidget(self.drop_out); f.addStretch()

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_rotado" + ext)
        try:
            r = PdfReader(p); self.lbl_info.setText(f"  {len(r.pages)} páginas")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _run(self):
        pdf_path = self.drop_in.path(); out_path = self.drop_out.path()
        angle = {0: 90, 1: 180, 2: 270}[self.cmb_angle.currentIndex()]
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona um PDF válido."); return
        if not out_path:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        try:
            reader = PdfReader(pdf_path); total = len(reader.pages)
            txt = self.edit_pages.text().strip()
            pages = parse_pages(txt, total) if txt else list(range(total))
            w = PdfWriter()
            for i, page in enumerate(reader.pages):
                if i in pages: page.rotate(angle)
                w.add_page(page)
            with open(out_path, "wb") as f: w.write(f)
            self._status(f"✔  PDF rodado: {os.path.basename(out_path)}")
            QMessageBox.information(self, "Concluído", f"PDF guardado em:\n{out_path}")
        except Exception as e: QMessageBox.critical(self, "Erro", str(e))
