"""PDFApps – TabOCR: OCR text recognition tool."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QComboBox, QFileDialog, QMessageBox,
    QApplication, QProgressDialog,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.i18n import t
from app.utils import section, info_lbl
from app.constants import TEXT_SEC, DESKTOP
from app.widgets import DropFileEdit


def _find_tesseract() -> str | None:
    """Returns the tesseract executable path or None if not found."""
    import shutil, sys
    found = shutil.which("tesseract")
    if found:
        return found
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/opt/homebrew/bin/tesseract",
            "/usr/local/bin/tesseract",
        ]
    else:
        candidates = [
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
            "/snap/bin/tesseract",
        ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


class TabOCR(BasePage):
    _LANG_KEYS = [
        ("tool.ocr.lang.pt",    "por"),
        ("tool.ocr.lang.en",    "eng"),
        ("tool.ocr.lang.pt_en", "por+eng"),
        ("tool.ocr.lang.es",    "spa"),
        ("tool.ocr.lang.fr",    "fra"),
        ("tool.ocr.lang.de",    "deu"),
    ]

    @property
    def _LANGS(self):
        return [(t(k), c) for k, c in self._LANG_KEYS]

    def __init__(self, status_fn):
        super().__init__("fa5s.search", t("tool.ocr.name"),
                         t("tool.ocr.desc"),
                         t("tool.ocr.btn"), status_fn)
        f = self._form

        sec_src = section(t("tool.ocr.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try: self.drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        f.addWidget(section(t("tool.ocr.options")))
        row_lang = QHBoxLayout()
        lbl_lang = QLabel(t("tool.ocr.lang_label"))
        lbl_lang.setStyleSheet(f"color:{TEXT_SEC};")
        self.cmb_lang = QComboBox()
        self._lang_codes = [c for _, c in self._LANGS]
        for name, _ in self._LANGS:
            self.cmb_lang.addItem(name)
        row_lang.addWidget(lbl_lang); row_lang.addWidget(self.cmb_lang); row_lang.addStretch()
        f.addLayout(row_lang)

        row_fmt = QHBoxLayout()
        lbl_fmt = QLabel(t("tool.ocr.format_label"))
        lbl_fmt.setStyleSheet(f"color:{TEXT_SEC};")
        self.cmb_fmt = QComboBox()
        self.cmb_fmt.addItems([t("tool.ocr.format.pdf"), t("tool.ocr.format.txt")])
        self.cmb_fmt.currentIndexChanged.connect(self._on_fmt_change)
        row_fmt.addWidget(lbl_fmt); row_fmt.addWidget(self.cmb_fmt); row_fmt.addStretch()
        f.addLayout(row_fmt)

        sec_out = section(t("tool.ocr.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit("ocr_output.pdf", save=True, default_name="ocr_output.pdf")
        f.addWidget(self.drop_out)
        f.addStretch()
        self._compact_hidden = [sec_src, self.drop_in, self.lbl_info]
        sec_out.setVisible(False)
        self.drop_out.setVisible(False)

    def _on_fmt_change(self, idx):
        p = self.drop_out.path()
        if p:
            base = os.path.splitext(p)[0]
            self.drop_out.set_path(base + (".pdf" if idx == 0 else ".txt"))

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
            base = os.path.splitext(p)[0]
            ext = ".pdf" if self.cmb_fmt.currentIndex() == 0 else ".txt"
            self.drop_out.set_path(base + "_ocr" + ext)
        try:
            doc = self._open_fitz(p)
            self.lbl_info.setText(t("edit.status.pages", n=doc.page_count))
            doc.close()
        except Exception as e:
            self.lbl_info.setText(t("tool.split.error_info", e=e))

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _ensure_tesseract(self):
        """Locate Tesseract, set TESSDATA_PREFIX and update available languages."""
        import pytesseract, sys
        tess_exe = _find_tesseract()

        if tess_exe:
            pytesseract.pytesseract.tesseract_cmd = tess_exe
            tess_dir = os.path.dirname(tess_exe)
            tessdata = os.path.join(tess_dir, "tessdata")
            if os.path.isdir(tessdata):
                os.environ["TESSDATA_PREFIX"] = tessdata

        try:
            pytesseract.get_tesseract_version()
        except Exception:
            if sys.platform == "win32":
                install_hint = "https://github.com/UB-Mannheim/tesseract/wiki"
            elif sys.platform == "darwin":
                install_hint = "brew install tesseract tesseract-lang"
            else:
                install_hint = "sudo apt install tesseract-ocr tesseract-ocr-por tesseract-ocr-eng"
            QMessageBox.critical(self, t("tool.ocr.tess_not_found"),
                t("tool.ocr.tess_msg", hint=install_hint))
            return None

        try:
            installed = pytesseract.get_languages(config="")
            self._update_lang_combo(installed)
        except Exception:
            pass

        return pytesseract

    def _update_lang_combo(self, installed: list):
        """Show only installed languages + possible combinations."""
        entries = []
        label_map = {"por": t("tool.ocr.lang.pt"), "eng": t("tool.ocr.lang.en"), "spa": t("tool.ocr.lang.es"),
                     "fra": t("tool.ocr.lang.fr"),     "deu": t("tool.ocr.lang.de"),  "ita": "Italian"}
        for code, label in [(c, label_map.get(c, c)) for c in installed if c != "osd"]:
            entries.append((label, code))
        if "por" in installed and "eng" in installed:
            entries.append((t("tool.ocr.lang.pt_en"), "por+eng"))
        if not entries:
            entries = [(t("tool.ocr.lang.en"), "eng")]
        current_codes = [e[1] for e in entries]
        self.cmb_lang.clear()
        for name, _ in entries:
            self.cmb_lang.addItem(name)
        self._lang_codes = current_codes

    def _run(self):
        import io as _io
        pdf_path = self.drop_in.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.select_valid_pdf")); return
        out_path = self._resolve_output_file(self.drop_out, pdf_path)
        if not out_path: return
        try:
            import pytesseract
        except ImportError:
            QMessageBox.critical(self, t("msg.missing_dep"), t("tool.ocr.dep_pytesseract"))
            return
        tess = self._ensure_tesseract()
        if tess is None: return
        try:
            import fitz
        except ImportError:
            QMessageBox.critical(self, t("msg.missing_dep"), t("tool.ocr.dep_pymupdf"))
            return
        try:
            from PIL import Image
        except ImportError:
            QMessageBox.critical(self, t("msg.missing_dep"), t("tool.ocr.dep_pillow"))
            return
        try:
            codes = getattr(self, "_lang_codes", [c for _, c in self._LANGS])
            if not codes:
                QMessageBox.warning(self, t("msg.warning"), t("tool.ocr.no_langs"))
                return
            idx = max(0, min(self.cmb_lang.currentIndex(), len(codes) - 1))
            lang = codes[idx]
            fmt  = self.cmb_fmt.currentIndex()
            with self._open_fitz(pdf_path) as doc:
                n = doc.page_count

                progress = QProgressDialog(t("progress.ocr.page", current=1, total=n),
                                           t("progress.cancel"), 0, n, self)
                progress.setWindowTitle(t("progress.ocr.title"))
                progress.setWindowModality(Qt.WindowModality.WindowModal)
                progress.setMinimumDuration(0)
                progress.setValue(0)
                cancelled = False

                if fmt == 1:
                    texts = []
                    for i, page in enumerate(doc):
                        progress.setLabelText(t("progress.ocr.page", current=i+1, total=n))
                        progress.setValue(i)
                        QApplication.processEvents()
                        if progress.wasCanceled():
                            cancelled = True; break
                        pix = page.get_pixmap(dpi=300)
                        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                        texts.append(pytesseract.image_to_string(img, lang=lang))
                else:
                    pdf_pages = []
                    for i, page in enumerate(doc):
                        progress.setLabelText(t("progress.ocr.page", current=i+1, total=n))
                        progress.setValue(i)
                        QApplication.processEvents()
                        if progress.wasCanceled():
                            cancelled = True; break
                        pix = page.get_pixmap(dpi=300)
                        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                        pdf_bytes = pytesseract.image_to_pdf_or_hocr(img, lang=lang, extension="pdf")
                        pdf_pages.append(pdf_bytes)

            # doc closed here via context manager; write output if not cancelled
            if not cancelled:
                if fmt == 1:
                    with open(out_path, "w", encoding="utf-8") as fh:
                        fh.write("\f".join(texts))
                else:
                    writer = PdfWriter()
                    for page_bytes in pdf_pages:
                        writer.append(PdfReader(_io.BytesIO(page_bytes)))
                    with open(out_path, "wb") as fh:
                        writer.write(fh)

            progress.setValue(n)
            if cancelled:
                self._status(t("progress.cancelled"))
            else:
                self._status(f"✔  OCR → {out_path}")
                QMessageBox.information(self, t("msg.done"),
                    t("tool.ocr.done", path=out_path))
        except Exception as e:
            QMessageBox.critical(self, t("tool.ocr.error"), str(e))
