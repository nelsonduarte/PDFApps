"""PDFApps – TabEncriptar: encrypt/decrypt PDF tool."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QHBoxLayout, QComboBox, QLineEdit,
    QFileDialog, QMessageBox,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.utils import section, info_lbl
from app.widgets import DropFileEdit


class TabEncriptar(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.lock", "Encriptar / Desencriptar",
                         "Protege o PDF com senha ou remove a protecção existente.",
                         "Executar", status_fn)
        f = self._form
        f.addWidget(section("Ficheiro PDF"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp_mode = QGroupBox("Operação")
        hm = QHBoxLayout(grp_mode)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["🔒  Encriptar  —  proteger com senha",
                                  "🔓  Desencriptar  —  remover protecção"])
        self.cmb_mode.currentIndexChanged.connect(self._on_mode)
        hm.addWidget(self.cmb_mode)
        f.addWidget(grp_mode)

        self.grp_enc = QGroupBox("Senhas de encriptação")
        fe = QFormLayout(self.grp_enc)
        fe.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_owner = QLineEdit(); self.edit_owner.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_user  = QLineEdit(); self.edit_user.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_user.setPlaceholderText("Opcional — se vazio, usa a senha do proprietário")
        fe.addRow("Senha do proprietário *:", self.edit_owner)
        fe.addRow("Senha do utilizador:", self.edit_user)
        f.addWidget(self.grp_enc)

        self.grp_dec = QGroupBox("Senha actual do PDF")
        fd = QFormLayout(self.grp_dec)
        fd.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pwd = QLineEdit(); self.edit_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_pwd.setPlaceholderText("Deixa em branco se não tiver senha")
        fd.addRow("Senha:", self.edit_pwd)
        f.addWidget(self.grp_dec)
        self._on_mode(0)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit("resultado.pdf", save=True, default_name="resultado.pdf")
        f.addWidget(self.drop_out); f.addStretch()

    def _on_mode(self, idx: int):
        self.grp_enc.setVisible(idx == 0)
        self.grp_dec.setVisible(idx == 1)
        # actualizar sufixo do output quando o modo muda
        p = self.drop_in.path()
        if p:
            base, ext = os.path.splitext(p)
            suffix = "_enc" if idx == 0 else "_dec"
            self.drop_out.set_path(base + suffix + ext)

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        base, ext = os.path.splitext(p)
        suffix = "_enc" if self.cmb_mode.currentIndex() == 0 else "_dec"
        self.drop_out.set_path(base + suffix + ext)
        try:
            r = PdfReader(p)
            encrypted = r.is_encrypted
            estado = "🔒 encriptado" if encrypted else "🔓 sem protecção"
            # len(r.pages) falha se encriptado e sem senha — usar page_count alternativo
            try:
                n_pages = len(r.pages)
            except Exception:
                n_pages = "?"
            self.lbl_info.setText(f"  {n_pages} páginas  ·  {estado}")
        except Exception as e:
            self.lbl_info.setText(f"  Erro: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _run(self):
        pdf_path = self.drop_in.path(); out_path = self.drop_out.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona um PDF válido."); return
        if not out_path:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        try:
            reader = PdfReader(pdf_path)
            if self.cmb_mode.currentIndex() == 0:
                owner = self.edit_owner.text()
                if not owner:
                    QMessageBox.warning(self, "Aviso", "Introduz a senha do proprietário."); return
                user_pwd = self.edit_user.text() or owner  # se vazio, usar a mesma senha para abrir
                w = PdfWriter(); w.append(reader)
                w.encrypt(user_password=user_pwd,
                          owner_password=owner, use_128bit=True)
                with open(out_path, "wb") as f: w.write(f)
                self._status(f"✔  PDF encriptado: {os.path.basename(out_path)}")
                QMessageBox.information(self, "Concluído", f"PDF encriptado:\n{out_path}")
            else:
                if reader.is_encrypted:
                    result = reader.decrypt(self.edit_pwd.text())
                    if result == 0:
                        QMessageBox.warning(self, "Aviso", "Senha incorrecta — não foi possível desencriptar o PDF.")
                        return
                w = PdfWriter(); w.append(reader)
                with open(out_path, "wb") as f: w.write(f)
                self._status(f"✔  PDF desencriptado: {os.path.basename(out_path)}")
                QMessageBox.information(self, "Concluído", f"PDF desencriptado:\n{out_path}")
        except Exception as e: QMessageBox.critical(self, "Erro", str(e))
