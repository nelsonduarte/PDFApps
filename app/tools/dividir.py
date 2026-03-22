"""PDFApps – TabDividir: split PDF tool."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSpinBox, QPushButton, QFileDialog, QMessageBox,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.utils import section, info_lbl, danger_btn, pick_folder
from app.widgets import DropFileEdit


class TabDividir(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.cut", "Dividir PDF",
                         "Corta o PDF em vários ficheiros por intervalos de páginas.",
                         "Dividir PDF", status_fn)
        self._total = 0
        f = self._form

        f.addWidget(section("Ficheiro de origem"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in)
        f.addWidget(self.lbl_info)

        grp = QGroupBox("Intervalos de páginas")
        vt  = QVBoxLayout(grp); vt.setSpacing(8)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Início", "Fim", "Nome do ficheiro de saída"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setFixedHeight(160)
        vt.addWidget(self.table)
        hb = QHBoxLayout()
        btn_add = QPushButton("＋  Adicionar linha")
        btn_rem = danger_btn("−  Remover")
        btn_add.clicked.connect(self._add_row)
        btn_rem.clicked.connect(self._remove_row)
        hb.addWidget(btn_add); hb.addWidget(btn_rem); hb.addStretch()
        vt.addLayout(hb)
        f.addWidget(grp)

        f.addWidget(section("Pasta de saída"))
        self.drop_out = DropFileEdit("Pasta onde serão guardados os ficheiros…")
        self.drop_out.btn.setText("Escolher…")
        self.drop_out.btn.clicked.disconnect()
        self.drop_out.btn.clicked.connect(self._pick_output)
        f.addWidget(self.drop_out)
        f.addStretch()
        self._add_row()

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path(): self.drop_out.set_path(os.path.dirname(p))
        try:
            r = PdfReader(p); self._total = len(r.pages)
            self.lbl_info.setText(f"  {self._total} páginas no ficheiro")
        except Exception as e: self.lbl_info.setText(f"  Erro: {e}")

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
        self.table.setItem(r, 2, QTableWidgetItem(f"parte_{r+1}.pdf"))

    def _remove_row(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def _run(self):
        pdf_path = self.drop_in.path(); out_dir = self.drop_out.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona um PDF válido."); return
        if not out_dir:
            QMessageBox.warning(self, "Aviso", "Escolhe a pasta de saída."); return
        try:
            reader = PdfReader(pdf_path); total = len(reader.pages)
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e)); return
        os.makedirs(out_dir, exist_ok=True)
        erros, gerados = [], []
        for r in range(self.table.rowCount()):
            start = self.table.cellWidget(r, 0).value()
            end   = self.table.cellWidget(r, 1).value()
            name  = self.table.item(r, 2).text().strip() or f"parte_{r+1}.pdf"
            if not name.lower().endswith(".pdf"): name += ".pdf"
            if start < 1 or end < start or end > total:
                erros.append(f"Linha {r+1}: {start}–{end} inválido"); continue
            w = PdfWriter()
            for p in range(start - 1, end): w.add_page(reader.pages[p])
            with open(os.path.join(out_dir, name), "wb") as f: w.write(f)
            gerados.append(name)
        if erros: QMessageBox.warning(self, "Aviso", "Ignorados:\n" + "\n".join(erros))
        if gerados:
            self._status(f"✔  {len(gerados)} ficheiro(s) criado(s) em {out_dir}")
            QMessageBox.information(self, "Concluído",
                f"{len(gerados)} ficheiro(s) criado(s) em:\n{out_dir}\n\n" + "\n".join(gerados))
