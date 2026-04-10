"""PDFApps – TabEncriptar: encrypt/decrypt PDF tool."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QHBoxLayout, QComboBox, QLineEdit,
    QFileDialog, QMessageBox,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.i18n import t
from app.utils import section, info_lbl
from app.constants import DESKTOP
from app.widgets import DropFileEdit


class TabEncriptar(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.lock", t("tool.encrypt.name"),
                         t("tool.encrypt.desc"),
                         t("tool.encrypt.btn"), status_fn)
        f = self._form
        sec_src = section(t("tool.encrypt.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try: self.drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp_mode = QGroupBox(t("tool.encrypt.operation"))
        hm = QHBoxLayout(grp_mode)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems([t("tool.encrypt.encrypt_opt"), t("tool.encrypt.decrypt_opt")])
        self.cmb_mode.currentIndexChanged.connect(self._on_mode)
        hm.addWidget(self.cmb_mode)
        f.addWidget(grp_mode)

        self.grp_enc = QGroupBox(t("tool.encrypt.passwords"))
        fe = QFormLayout(self.grp_enc)
        fe.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_owner = QLineEdit(); self.edit_owner.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_owner_confirm = QLineEdit(); self.edit_owner_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_user  = QLineEdit(); self.edit_user.setEchoMode(QLineEdit.EchoMode.Password)
        fe.addRow(t("tool.encrypt.owner_label"), self.edit_owner)
        fe.addRow(t("tool.encrypt.confirm_label"), self.edit_owner_confirm)
        fe.addRow(t("tool.encrypt.user_label"), self.edit_user)
        f.addWidget(self.grp_enc)

        self.grp_dec = QGroupBox(t("tool.encrypt.current"))
        fd = QFormLayout(self.grp_dec)
        fd.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pwd = QLineEdit(); self.edit_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        fd.addRow(t("tool.encrypt.current_label"), self.edit_pwd)
        f.addWidget(self.grp_dec)
        self._on_mode(0)

        sec_out = section(t("tool.encrypt.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit("result.pdf", save=True, default_name="result.pdf")
        f.addWidget(self.drop_out); f.addStretch()
        self._compact_hidden = [sec_src, self.drop_in, self.lbl_info, sec_out, self.drop_out]

    def _on_mode(self, idx: int):
        self.grp_enc.setVisible(idx == 0)
        self.grp_dec.setVisible(idx == 1)
        p = self.drop_in.path()
        if p:
            base, ext = os.path.splitext(p)
            suffix = "_enc" if idx == 0 else "_dec"
            self.drop_out.set_path(base + suffix + ext)

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
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
            status = t("tool.encrypt.status_enc") if encrypted else t("tool.encrypt.status_dec")
            try:
                n_pages = len(r.pages)
            except Exception:
                n_pages = "?"
            self.lbl_info.setText(t("edit.status.pages", n=n_pages) + f"  ·  {status}")
        except Exception as e:
            self.lbl_info.setText(t("tool.split.error_info", e=e))

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _run(self):
        pdf_path = self.drop_in.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.select_valid_pdf")); return
        out_path = self._resolve_output_file(self.drop_out, pdf_path)
        if not out_path: return
        try:
            reader = PdfReader(pdf_path)
            if self.cmb_mode.currentIndex() == 0:
                owner = self.edit_owner.text()
                if not owner:
                    QMessageBox.warning(self, t("msg.warning"), t("tool.encrypt.enter_owner")); return
                if owner != self.edit_owner_confirm.text():
                    QMessageBox.warning(self, t("msg.warning"), t("tool.encrypt.mismatch")); return
                user_pwd = self.edit_user.text() or owner
                w = PdfWriter(); w.append(reader)
                w.encrypt(user_password=user_pwd,
                          owner_password=owner, use_128bit=True)
                with open(out_path, "wb") as f: w.write(f)
                self._status(f"✔  {os.path.basename(out_path)}")
                QMessageBox.information(self, t("msg.done"), t("tool.encrypt.done_enc", path=out_path))
            else:
                if reader.is_encrypted:
                    result = reader.decrypt(self.edit_pwd.text())
                    if result == 0:
                        QMessageBox.warning(self, t("msg.warning"), t("tool.encrypt.wrong_pass"))
                        return
                w = PdfWriter(); w.append(reader)
                with open(out_path, "wb") as f: w.write(f)
                self._status(f"✔  {os.path.basename(out_path)}")
                QMessageBox.information(self, t("msg.done"), t("tool.encrypt.done_dec", path=out_path))
        except Exception as e: QMessageBox.critical(self, t("msg.error"), str(e))
