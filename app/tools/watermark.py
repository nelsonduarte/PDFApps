"""PDFApps – TabMarcaDagua: watermark PDF tool."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QLineEdit, QComboBox, QFileDialog, QMessageBox,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.i18n import t
from app.utils import section, info_lbl, parse_pages, show_error
from app.constants import DESKTOP
from app.widgets import DropFileEdit


class TabMarcaDagua(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.stamp", t("tool.watermark.name"),
                         t("tool.watermark.desc"),
                         t("tool.watermark.btn"), status_fn)
        self._pipeline_supported = True
        f = self._form
        sec_src = section(t("tool.watermark.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try: self.drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        f.addWidget(section(t("tool.watermark.wm_file")))
        self.drop_wm = DropFileEdit(t("tool.watermark.wm_hint"))
        f.addWidget(self.drop_wm)

        grp = QGroupBox(t("tool.watermark.options"))
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pages = QLineEdit()
        self.edit_pages.setPlaceholderText(t("tool.watermark.pages_hint"))
        self.cmb_layer = QComboBox()
        full = [t("tool.watermark.below"), t("tool.watermark.above")]
        short = [s.split("(")[0].strip() for s in full]
        self.cmb_layer.addItems(short)
        for i, full_text in enumerate(full):
            self.cmb_layer.setItemData(i, full_text, Qt.ItemDataRole.ToolTipRole)
        self.cmb_layer.setMinimumContentsLength(8)
        form.addRow(t("tool.watermark.pages_label"), self.edit_pages)
        form.addRow(t("tool.watermark.position_label"), self.cmb_layer)
        f.addWidget(grp)

        sec_out = section(t("tool.watermark.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit("watermarked.pdf", save=True, default_name="watermarked.pdf")
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
            self.drop_out.set_path(base + "_watermark" + ext)
        try:
            r = self._open_reader(p); self.lbl_info.setText(t("edit.status.pages", n=len(r.pages)))
        except Exception as e: self.lbl_info.setText(t("tool.split.error_info", e=e))

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _prompt_watermark_password(self, wm_path: str) -> str | None:
        """Resolve an encryption password for the watermark PDF.

        Returns:
            ""        — watermark PDF is plaintext (no password needed)
            "<pwd>"  — user supplied a valid password
            None      — user cancelled the prompt (caller aborts)

        Kept separate from ``self._pdf_password`` (which holds the
        *source* PDF's password) so a corporate stamp PDF and the user's
        own document don't leak credentials into one another.
        """
        from app.utils import prompt_pdf_password
        ok, pwd = prompt_pdf_password(wm_path, self)
        if not ok:
            return None
        return pwd

    def _run(self):
        pdf_path = self.drop_in.path(); wm_path = self.drop_wm.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("tool.watermark.select_source")); return
        if not wm_path or not os.path.isfile(wm_path):
            QMessageBox.warning(self, t("msg.warning"), t("tool.watermark.select_wm")); return
        out_path = self._resolve_output_file(self.drop_out, pdf_path)
        if not out_path: return

        # R8 bonus #6: the watermark PDF can itself be encrypted (rare
        # but observed when users borrow a corporate stamp PDF).
        # PdfReader(wm_path) used to raise PdfReadError cryptically;
        # prompt for the watermark's password explicitly here so the
        # error surface matches the source-PDF flow. Tracked separately
        # from self._pdf_password (which holds the *source* PDF's
        # password) so neither leaks into the other.
        wm_pwd = self._prompt_watermark_password(wm_path)
        if wm_pwd is None:
            return  # user cancelled

        # Pre-flight on the main thread: validate inputs and resolve page
        # targets so the worker can be a tight loop with no Qt calls.
        try:
            wm_reader = PdfReader(wm_path)
            if wm_reader.is_encrypted and wm_pwd:
                wm_reader.decrypt(wm_pwd)
            if not wm_reader.pages:
                QMessageBox.warning(self, t("msg.warning"), t("tool.watermark.empty_wm"))
                return
            reader = self._open_reader(pdf_path)
            if not reader.pages:
                QMessageBox.warning(self, t("msg.warning"), t("tool.watermark.empty_source"))
                return
            total = len(reader.pages)
            txt = self.edit_pages.text().strip()
            targets = set(parse_pages(txt, total)) if txt else set(range(total))
        except Exception as e:
            show_error(self, e)
            return

        over = self.cmb_layer.currentIndex() == 1
        pwd = self._pdf_password

        def do_work(worker):
            r = PdfReader(pdf_path)
            if r.is_encrypted and pwd:
                r.decrypt(pwd)
            wm = PdfReader(wm_path)
            if wm.is_encrypted and wm_pwd:
                wm.decrypt(wm_pwd)
            wm_page = wm.pages[0]
            w = PdfWriter()
            n = len(r.pages)
            for i, page in enumerate(r.pages):
                if worker.is_cancelled():
                    return None
                w.add_page(page)
                if i in targets:
                    w.pages[i].merge_page(wm_page, over=over)
                worker.progress.emit(int((i + 1) / n * 100),
                                     t("progress.watermark.page",
                                       current=i + 1, total=n))
            if worker.is_cancelled():
                return None
            self._atomic_pdf_write(w, out_path, sources=[pdf_path, wm_path])
            return out_path

        def on_done(saved):
            self._status(t("tool.watermark.status.done", name=os.path.basename(saved)))
            msg = t("tool.watermark.done", path=saved)
            if self._pipeline_active:
                self._pipeline_success(msg, saved)
            else:
                QMessageBox.information(self, t("msg.done"), msg)

        self._run_background(do_work, total=100,
                             label=t("progress.watermark.applying"),
                             on_done=on_done)
