"""PDFApps – TabMarcaDagua: watermark PDF tool."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QLineEdit, QComboBox, QFileDialog, QMessageBox,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.utils import section, info_lbl, parse_pages
from app.widgets import DropFileEdit


class TabMarcaDagua(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.stamp", "Marca d'água",
                         "Sobrepõe um PDF (marca, carimbo) sobre as páginas.",
                         "Aplicar marca d'água", status_fn)
        f = self._form
        f.addWidget(section("PDF de origem"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        f.addWidget(section("PDF da marca d'água  (1 página)"))
        self.drop_wm = DropFileEdit("Arrasta o PDF da marca d'água aqui…")
        f.addWidget(self.drop_wm)

        grp = QGroupBox("Opções")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pages = QLineEdit()
        self.edit_pages.setPlaceholderText("ex: 1,3,5-8  (vazio = todas)")
        self.cmb_layer = QComboBox()
        self.cmb_layer.addItems(["Por baixo  (fundo / marca d'água clássica)",
                                  "Por cima  (carimbo / frente)"])
        form.addRow("Páginas:", self.edit_pages)
        form.addRow("Posição:", self.cmb_layer)
        f.addWidget(grp)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit("com_marca.pdf", save=True, default_name="com_marca.pdf")
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
            self.drop_out.set_path(base + "_marca" + ext)
        try:
            r = PdfReader(p); self.lbl_info.setText(f"  {len(r.pages)} páginas")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _run(self):
        pdf_path = self.drop_in.path(); wm_path = self.drop_wm.path()
        out_path = self.drop_out.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona o PDF de origem."); return
        if not wm_path or not os.path.isfile(wm_path):
            QMessageBox.warning(self, "Aviso", "Seleciona o PDF de marca d'água."); return
        if not out_path:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        try:
            reader  = PdfReader(pdf_path)
            wm_page = PdfReader(wm_path).pages[0]
            total   = len(reader.pages)
            txt     = self.edit_pages.text().strip()
            targets = set(parse_pages(txt, total)) if txt else set(range(total))
            over    = self.cmb_layer.currentIndex() == 1
            w = PdfWriter()
            for i, page in enumerate(reader.pages):
                w.add_page(page)
                if i in targets:
                    w.pages[i].merge_page(wm_page, over=over)
            with open(out_path, "wb") as f: w.write(f)
            self._status(f"✔  Marca d'água aplicada: {os.path.basename(out_path)}")
            QMessageBox.information(self, "Concluído", f"PDF guardado em:\n{out_path}")
        except Exception as e: QMessageBox.critical(self, "Erro", str(e))
