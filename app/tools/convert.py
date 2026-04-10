"""PDFApps – TabConverter: convert PDF to images, DOCX or TXT."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QComboBox, QLabel, QFileDialog,
    QMessageBox, QApplication,
)
from pypdf import PdfReader

from app.base import BasePage
from app.i18n import t
from app.utils import section, info_lbl, pick_folder
from app.constants import DESKTOP
from app.widgets import DropFileEdit


class TabConverter(BasePage):
    _DPI_VALUES = [72, 150, 300]

    def __init__(self, status_fn):
        super().__init__("fa5s.exchange-alt", t("tool.convert.name"),
                         t("tool.convert.desc"),
                         t("tool.convert.btn"), status_fn)
        f = self._form

        # -- Source file --
        sec_src = section(t("tool.convert.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try: self.drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        # -- Output format --
        grp_fmt = QGroupBox(t("tool.convert.format_section"))
        gf = QFormLayout(grp_fmt)
        gf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.cmb_format = QComboBox()
        self.cmb_format.addItems([
            t("tool.convert.png"), t("tool.convert.jpg"),
            t("tool.convert.docx"), t("tool.convert.txt"),
        ])
        self.cmb_format.currentIndexChanged.connect(self._on_format_changed)
        gf.addRow(t("tool.convert.format_label"), self.cmb_format)
        f.addWidget(grp_fmt)

        # -- Image options (visible for PNG/JPG) --
        self._grp_dpi = QGroupBox(t("tool.convert.img_options"))
        gd = QFormLayout(self._grp_dpi)
        gd.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.cmb_dpi = QComboBox()
        self.cmb_dpi.addItems([
            t("tool.convert.dpi_72"), t("tool.convert.dpi_150"), t("tool.convert.dpi_300"),
        ])
        self.cmb_dpi.setCurrentIndex(1)
        gd.addRow(t("tool.convert.dpi_label"), self.cmb_dpi)
        f.addWidget(self._grp_dpi)

        # -- Output folder (images) --
        sec_out_folder = section(t("tool.convert.output_folder"))
        f.addWidget(sec_out_folder)
        self._sec_out_folder = sec_out_folder
        self._drop_folder = DropFileEdit(placeholder=t("tool.convert.folder_hint"))
        try: self._drop_folder.btn.clicked.disconnect()
        except RuntimeError: pass
        self._drop_folder.btn.clicked.connect(self._pick_folder)
        f.addWidget(self._drop_folder)

        # -- Output file (DOCX / TXT) --
        self._section_file = section(t("tool.convert.output_file"))
        self._section_file.setVisible(False)
        f.addWidget(self._section_file)
        self._drop_file = DropFileEdit(save=True, default_name="converted.docx")
        self._drop_file.setVisible(False)
        f.addWidget(self._drop_file)

        self.lbl_result = QLabel("")
        self.lbl_result.setStyleSheet(
            "font-weight:600; font-size:11pt; color:#059669; "
            "background:transparent; padding:10px 4px;")
        f.addWidget(self.lbl_result)
        f.addStretch()
        self._compact_hidden = [sec_src, self.drop_in, self.lbl_info]
        # Hide all output sections — save dialog prompts automatically
        for w in (sec_out_folder, self._drop_folder, self._section_file, self._drop_file):
            w.setVisible(False)

    # ── UI callbacks ──────────────────────────────────────────────────────

    def _on_format_changed(self, index: int):
        is_image = index <= 1
        self._grp_dpi.setVisible(is_image)
        if not self._compact_active:
            self._drop_folder.setVisible(is_image)
            self._sec_out_folder.setVisible(is_image)
            self._section_file.setVisible(not is_image)
            self._drop_file.setVisible(not is_image)
        if not is_image:
            ext = ".docx" if index == 2 else ".txt"
            inp = self.drop_in.path()
            if inp:
                base = os.path.splitext(inp)[0]
                self._drop_file.set_path(base + ext)

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if p:
            self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        size = os.path.getsize(p)
        try:
            r = PdfReader(p)
            self.lbl_info.setText(t("tool.compress.pages_info", n=len(r.pages), size=f"{size/1024:.1f}"))
        except Exception as e:
            self.lbl_info.setText(t("tool.split.error_info", e=e))
        # auto-set output paths
        base = os.path.splitext(p)[0]
        if not self._drop_folder.path():
            self._drop_folder.blockSignals(True)
            self._drop_folder.set_path(os.path.dirname(p))
            self._drop_folder.blockSignals(False)
        fmt = self.cmb_format.currentIndex()
        if fmt >= 2:
            ext = ".docx" if fmt == 2 else ".txt"
            self._drop_file.set_path(base + ext)

    def _pick_folder(self):
        d = pick_folder(self)
        if d:
            self._drop_folder.blockSignals(True)
            self._drop_folder.set_path(d)
            self._drop_folder.blockSignals(False)

    def auto_load(self, path: str):
        if path and not self.drop_in.path():
            self._load_input(path)

    # ── conversion logic ──────────────────────────────────────────────────

    def _run(self):
        pdf_path = self.drop_in.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.select_valid_pdf"))
            return

        fmt = self.cmb_format.currentIndex()
        self.lbl_result.setText("")

        if fmt <= 1:
            self._convert_images(pdf_path, fmt)
        elif fmt == 2:
            self._convert_docx(pdf_path)
        else:
            self._convert_txt(pdf_path)

    def _convert_images(self, pdf_path: str, fmt: int):
        out_dir = self._resolve_output_dir(self._drop_folder, pdf_path)
        if not out_dir:
            return
        os.makedirs(out_dir, exist_ok=True)
        ext = "png" if fmt == 0 else "jpg"
        dpi = self._DPI_VALUES[self.cmb_dpi.currentIndex()]
        self._status(f"→ {ext.upper()} @ {dpi} DPI…")
        QApplication.processEvents()
        try:
            import fitz
            doc = fitz.open(pdf_path)
            matrix = fitz.Matrix(dpi / 72, dpi / 72)
            total = doc.page_count
            for i, page in enumerate(doc):
                pix = page.get_pixmap(matrix=matrix)
                if pix.alpha:
                    pix = fitz.Pixmap(pix, 0)
                if pix.n == 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                out_file = os.path.join(out_dir, f"page_{i + 1:03d}.{ext}")
                if ext == "png":
                    pix.save(out_file)
                else:
                    try:
                        from PIL import Image
                        mode = "L" if pix.n == 1 else "RGB"
                        img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
                        img.save(out_file, "JPEG", quality=95)
                    except ImportError:
                        pix.save(out_file)
                self._status(f"{i + 1}/{total}…")
                QApplication.processEvents()
            doc.close()
            self.lbl_result.setText(f"  {total} → {out_dir}")
            self._status(f"✔  {total} images")
            QMessageBox.information(self, t("msg.done"),
                                    t("tool.convert.done_images", n=total, folder=out_dir))
        except Exception as e:
            QMessageBox.critical(self, t("msg.error"), str(e))

    def _convert_docx(self, pdf_path: str):
        out_path = self._resolve_output_file(self._drop_file, pdf_path,
                                             filter_key="file_filter.docx")
        if not out_path:
            return
        self._status("→ DOCX…")
        QApplication.processEvents()
        try:
            import fitz
        except ImportError:
            QMessageBox.critical(self, t("msg.missing_dep"), t("tool.ocr.dep_pymupdf"))
            return
        try:
            from docx import Document
        except ImportError:
            QMessageBox.critical(self, t("msg.missing_dep"), t("tool.convert.dep_docx"))
            return
        try:
            doc = fitz.open(pdf_path)
            docx_doc = Document()
            for i, page in enumerate(doc):
                if i > 0:
                    docx_doc.add_page_break()
                text = page.get_text()
                for paragraph in text.split('\n'):
                    docx_doc.add_paragraph(paragraph)
            docx_doc.save(out_path)
            doc.close()
            self.lbl_result.setText(f"  → {os.path.basename(out_path)}")
            self._status(f"✔  DOCX → {out_path}")
            QMessageBox.information(self, t("msg.done"),
                                    t("tool.convert.done_docx", path=out_path))
        except Exception as e:
            QMessageBox.critical(self, t("msg.error"), str(e))

    def _convert_txt(self, pdf_path: str):
        out_path = self._resolve_output_file(self._drop_file, pdf_path,
                                             filter_key="file_filter.txt")
        if not out_path:
            return
        self._status("→ TXT…")
        QApplication.processEvents()
        try:
            import fitz
            doc = fitz.open(pdf_path)
            with open(out_path, 'w', encoding='utf-8') as f:
                for i, page in enumerate(doc):
                    if i > 0:
                        f.write(f'\n\n--- Page {i + 1} ---\n\n')
                    f.write(page.get_text())
            doc.close()
            self.lbl_result.setText(f"  → {os.path.basename(out_path)}")
            self._status(f"✔  TXT → {out_path}")
            QMessageBox.information(self, t("msg.done"),
                                    t("tool.convert.done_txt", path=out_path))
        except Exception as e:
            QMessageBox.critical(self, t("msg.error"), str(e))
