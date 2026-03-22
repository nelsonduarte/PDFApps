"""PDFApps – TabOCR: OCR text recognition tool."""

import os

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QComboBox, QFileDialog, QMessageBox, QApplication,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.utils import section, info_lbl
from app.constants import TEXT_SEC
from app.widgets import DropFileEdit


_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


class TabOCR(BasePage):
    _LANGS = [
        ("Português",          "por"),
        ("Inglês",             "eng"),
        ("Português + Inglês", "por+eng"),
        ("Espanhol",           "spa"),
        ("Francês",            "fra"),
        ("Alemão",             "deu"),
    ]

    def __init__(self, status_fn):
        super().__init__("fa5s.search", "OCR – Reconhecer Texto",
                         "Extrai texto de PDFs digitalizados/escaneados usando OCR.",
                         "Executar OCR", status_fn)
        f = self._form

        f.addWidget(section("Ficheiro PDF (digitalizado)"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        f.addWidget(section("Opções"))
        row_lang = QHBoxLayout()
        lbl_lang = QLabel("Idioma do documento:")
        lbl_lang.setStyleSheet(f"color:{TEXT_SEC};")
        self.cmb_lang = QComboBox()
        self._lang_codes = [c for _, c in self._LANGS]
        for name, _ in self._LANGS:
            self.cmb_lang.addItem(name)
        row_lang.addWidget(lbl_lang); row_lang.addWidget(self.cmb_lang); row_lang.addStretch()
        f.addLayout(row_lang)

        row_fmt = QHBoxLayout()
        lbl_fmt = QLabel("Formato de saída:")
        lbl_fmt.setStyleSheet(f"color:{TEXT_SEC};")
        self.cmb_fmt = QComboBox()
        self.cmb_fmt.addItems(["PDF pesquisável (.pdf)", "Texto simples (.txt)"])
        self.cmb_fmt.currentIndexChanged.connect(self._on_fmt_change)
        row_fmt.addWidget(lbl_fmt); row_fmt.addWidget(self.cmb_fmt); row_fmt.addStretch()
        f.addLayout(row_fmt)

        f.addWidget(section("Ficheiro de saída"))
        self.drop_out = DropFileEdit("ocr_output.pdf", save=True, default_name="ocr_output.pdf")
        f.addWidget(self.drop_out)
        f.addStretch()

    def _on_fmt_change(self, idx):
        p = self.drop_out.path()
        if p:
            base = os.path.splitext(p)[0]
            self.drop_out.set_path(base + (".pdf" if idx == 0 else ".txt"))

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", "", "PDF (*.pdf)")
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path():
            base = os.path.splitext(p)[0]
            ext = ".pdf" if self.cmb_fmt.currentIndex() == 0 else ".txt"
            self.drop_out.set_path(base + "_ocr" + ext)
        try:
            import fitz
            doc = fitz.open(p)
            self.lbl_info.setText(f"  {doc.page_count} páginas")
            doc.close()
        except Exception as e:
            self.lbl_info.setText(f"  Erro: {e}")

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _ensure_tesseract(self):
        """Localiza o Tesseract, define TESSDATA_PREFIX e atualiza idiomas disponíveis."""
        import pytesseract
        tess_exe = None
        for path in _TESSERACT_PATHS:
            if os.path.isfile(path):
                tess_exe = path
                break

        if tess_exe:
            pytesseract.pytesseract.tesseract_cmd = tess_exe
            # TESSDATA_PREFIX deve apontar para a pasta tessdata (não para o seu pai)
            tess_dir = os.path.dirname(tess_exe)
            tessdata = os.path.join(tess_dir, "tessdata")
            if os.path.isdir(tessdata):
                os.environ["TESSDATA_PREFIX"] = tessdata

        try:
            pytesseract.get_tesseract_version()
        except Exception:
            QMessageBox.critical(self, "Tesseract não encontrado",
                "O motor Tesseract OCR não está instalado ou não foi encontrado.\n\n"
                "Instala em:\nhttps://github.com/UB-Mannheim/tesseract/wiki\n\n"
                "Inclui os language packs de que precisas (por, eng…).")
            return None

        # Detetar idiomas instalados e atualizar o dropdown
        try:
            installed = pytesseract.get_languages(config="")
            self._update_lang_combo(installed)
        except Exception:
            pass

        return pytesseract

    def _update_lang_combo(self, installed: list):
        """Mostra só os idiomas instalados + combinações possíveis."""
        entries = []
        label_map = {"por": "Português", "eng": "Inglês", "spa": "Espanhol",
                     "fra": "Francês",   "deu": "Alemão",  "ita": "Italiano"}
        for code, label in [(c, label_map.get(c, c)) for c in installed if c != "osd"]:
            entries.append((label, code))
        # combinação por+eng se ambos disponíveis
        if "por" in installed and "eng" in installed:
            entries.append(("Português + Inglês", "por+eng"))
        if not entries:
            entries = [("Inglês (padrão)", "eng")]
        current_codes = [e[1] for e in entries]
        self.cmb_lang.clear()
        for name, _ in entries:
            self.cmb_lang.addItem(name)
        self._lang_codes = current_codes

    def _run(self):
        import io as _io
        pdf_path = self.drop_in.path(); out_path = self.drop_out.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Aviso", "Seleciona um PDF válido."); return
        if not out_path:
            QMessageBox.warning(self, "Aviso", "Escolhe o ficheiro de saída."); return
        try:
            import pytesseract
        except ImportError:
            QMessageBox.critical(self, "Dependência em falta",
                "Instala a biblioteca pytesseract:\n  pip install pytesseract")
            return
        tess = self._ensure_tesseract()
        if tess is None: return
        try:
            import fitz
        except ImportError:
            QMessageBox.critical(self, "Dependência em falta",
                "Instala a biblioteca PyMuPDF:\n\npip install pymupdf")
            return
        try:
            from PIL import Image
        except ImportError:
            QMessageBox.critical(self, "Dependência em falta",
                "Instala a biblioteca Pillow:\n\npip install Pillow")
            return
        try:
            codes = getattr(self, "_lang_codes", [c for _, c in self._LANGS])
            lang  = codes[self.cmb_lang.currentIndex()]
            fmt  = self.cmb_fmt.currentIndex()  # 0=pdf, 1=txt
            doc  = fitz.open(pdf_path)
            n    = doc.page_count
            self._status(f"A iniciar OCR em {n} página(s)…")
            QApplication.processEvents()

            if fmt == 1:
                texts = []
                for i, page in enumerate(doc):
                    self._status(f"OCR: página {i+1}/{n}…")
                    QApplication.processEvents()
                    pix = page.get_pixmap(dpi=300)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    texts.append(pytesseract.image_to_string(img, lang=lang))
                doc.close()
                with open(out_path, "w", encoding="utf-8") as fh:
                    fh.write("\f".join(texts))
            else:
                pdf_pages = []
                for i, page in enumerate(doc):
                    self._status(f"OCR: página {i+1}/{n}…")
                    QApplication.processEvents()
                    pix = page.get_pixmap(dpi=300)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    pdf_bytes = pytesseract.image_to_pdf_or_hocr(img, lang=lang, extension="pdf")
                    pdf_pages.append(pdf_bytes)
                doc.close()
                writer = PdfWriter()
                for page_bytes in pdf_pages:
                    writer.append(PdfReader(_io.BytesIO(page_bytes)))
                with open(out_path, "wb") as fh:
                    writer.write(fh)

            self._status(f"✔  OCR concluído → {out_path}")
            QMessageBox.information(self, "Concluído",
                f"OCR concluído com sucesso!\n\nFicheiro guardado em:\n{out_path}")
        except Exception as e:
            QMessageBox.critical(self, "Erro no OCR", str(e))
