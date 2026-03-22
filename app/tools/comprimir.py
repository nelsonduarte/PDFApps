"""PDFApps – TabComprimir: compress PDF tool."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QComboBox, QLabel, QFileDialog, QMessageBox, QApplication,
)
from pypdf import PdfReader

from app.base import BasePage
from app.utils import section, info_lbl, _compress_pdf
from app.widgets import DropFileEdit


class TabComprimir(BasePage):
    _LEVEL_KEYS = ["extreme", "recommended", "low"]

    def __init__(self, status_fn):
        super().__init__("fa5s.compress-arrows-alt", "Comprimir PDF",
                         "Reduz o tamanho do ficheiro comprimindo streams e objectos.",
                         "Comprimir PDF", status_fn)
        f = self._form
        f.addWidget(section("Ficheiro de origem"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox("Nível de compressão")
        gl  = QFormLayout(grp)
        gl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.cmb_level = QComboBox()
        self.cmb_level.addItems([
            "Extreme  —  DPI 72 · JPEG 45 %  (máx. compressão)",
            "Recomendado  —  DPI 150 · JPEG 70 %  (equilíbrio)",
            "Baixo  —  DPI 300 · JPEG 85 %  (mín. perda)",
        ])
        self.cmb_level.setCurrentIndex(1)
        gl.addRow("Nível:", self.cmb_level)
        f.addWidget(grp)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit(save=True, default_name="comprimido.pdf")
        f.addWidget(self.drop_out)

        self.lbl_result = QLabel("")
        self.lbl_result.setStyleSheet(
            "font-weight:600; font-size:11pt; color:#059669; "
            "background:transparent; padding:10px 4px;")
        f.addWidget(self.lbl_result)
        f.addStretch()

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_comprimido" + ext)
        size = os.path.getsize(p)
        try:
            r = PdfReader(p)
            self.lbl_info.setText(f"  {len(r.pages)} páginas  ·  {size/1024:.1f} KB")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _run(self):
        pdf_path = self.drop_in.path(); out_path = self.drop_out.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona um PDF válido."); return
        if not out_path:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        level = self._LEVEL_KEYS[self.cmb_level.currentIndex()]
        self._status(f"A comprimir ({level})…")
        QApplication.processEvents()
        try:
            before, after = _compress_pdf(pdf_path, out_path, level)
            ratio = (1 - after / before) * 100 if before else 0
            msg = f"  {before/1024:.0f} KB  →  {after/1024:.0f} KB  (−{ratio:.0f}%)"
            self.lbl_result.setText(msg)
            self._status(f"✔  Compressão: {msg.strip()}")
            QMessageBox.information(self, "Concluído", f"PDF guardado em:\n{out_path}")
        except ValueError as e:
            before_kb = os.path.getsize(pdf_path) / 1024
            msg = f"  {before_kb:.0f} KB  (sem ganho)"
            self.lbl_result.setText(msg)
            self._status("ℹ  O ficheiro já está optimizado — sem ganho de compressão")
            QMessageBox.information(self, "Sem ganho",
                f"Não foi possível reduzir o tamanho.\n\n{e}\n\n"
                f"O ficheiro de saída não foi guardado.")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))
