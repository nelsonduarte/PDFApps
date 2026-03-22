"""PDFApps – TabJuntar: merge PDFs tool."""

import os

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QAbstractItemView, QPushButton, QMessageBox,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.utils import section, danger_btn, pick_pdfs
from app.widgets import DropFileEdit, MultiDropWidget


class TabJuntar(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.object-group", "Juntar PDFs",
                         "Combina vários ficheiros PDF numa única documento.",
                         "Juntar PDFs", status_fn)
        f = self._form

        grp = QGroupBox("PDFs a juntar  (arrasta para reordenar)")
        vl  = QVBoxLayout(grp); vl.setSpacing(8)
        self.drop_multi = MultiDropWidget(self._on_drop)
        self.drop_multi.btn.clicked.connect(self._add_files)
        vl.addWidget(self.drop_multi)
        self.lst = QListWidget()
        self.lst.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.lst.setAlternatingRowColors(True)
        self.lst.setMinimumHeight(180)
        vl.addWidget(self.lst)
        hb = QHBoxLayout()
        for txt, slot in [("▲ Subir", self._up), ("▼ Descer", self._dn),
                          ("−  Remover", self._remove), ("Limpar", self.lst.clear)]:
            btn = danger_btn(txt) if "Remover" in txt else QPushButton(txt)
            btn.clicked.connect(slot); hb.addWidget(btn)
        hb.addStretch(); vl.addLayout(hb)
        f.addWidget(grp)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit(save=True, default_name="juntado.pdf")
        f.addWidget(self.drop_out)
        f.addStretch()

    def _on_drop(self, paths: list):
        for p in paths: self.lst.addItem(QListWidgetItem(p))

    def _add_files(self):
        for p in pick_pdfs(self): self.lst.addItem(QListWidgetItem(p))

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
        if r >= 0: self.lst.takeItem(r)

    def auto_load(self, path: str):
        if not path: return
        existing = [self.lst.item(i).text() for i in range(self.lst.count())]
        if path not in existing:
            self.lst.addItem(QListWidgetItem(path))

    def _run(self):
        paths = [self.lst.item(i).text() for i in range(self.lst.count())]
        out   = self.drop_out.path()
        if len(paths) < 2:
            QMessageBox.warning(self, "Aviso", "Adiciona pelo menos 2 PDFs."); return
        if not out:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        try:
            w = PdfWriter()
            for p in paths:
                for page in PdfReader(p).pages: w.add_page(page)
            with open(out, "wb") as f: w.write(f)
            self._status(f"✔  PDF criado: {os.path.basename(out)}")
            QMessageBox.information(self, "Concluído", f"PDF criado em:\n{out}")
        except Exception as e: QMessageBox.critical(self, "Erro", str(e))
