"""PDFApps – TabOCR: OCR text recognition tool."""

import os
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QComboBox, QFileDialog, QMessageBox,
    QProgressDialog,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.i18n import t
from app.utils import section, info_lbl, show_error
from app.worker import TaskRunner, run_task
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


def _find_tessdata(tess_exe: str | None) -> str | None:
    """Locate the tessdata directory across platforms.

    Precedence (first match wins):

    1. ``<bindir>/tessdata`` adjacent to the binary — Windows and any
       install that bundles the data next to the executable.
    2. The versioned Linux layout
       ``/usr/share/tesseract-ocr/<version>/tessdata``, reverse-sorted so
       the newest version wins. Checked *before* the relative prefix
       derivation (step 3) on purpose: the binary often has a stale
       default baked in (Ubuntu 24.04 ships v5 but still points at
       .../4.00/tessdata, see issue #27), and a flat ``/usr/share/tessdata``
       — which step 3 would derive from ``/usr/bin/tesseract`` — must never
       shadow a newer versioned directory.
    3. ``<prefix>/share/tessdata`` derived relative to the binary
       (``<prefix>/bin/tesseract`` -> ``<prefix>/share/tessdata``). This
       covers Homebrew (Intel ``/usr/local``, Apple Silicon
       ``/opt/homebrew``) and non-standard install prefixes; on those
       systems the versioned glob in step 2 finds nothing so we land here.
    4. Fixed fallbacks for older Debian, manual installs, Homebrew and
       snap layouts.

    Without TESSDATA_PREFIX set explicitly, OCR would otherwise fail with
    'Error opening data file .../4.00/tessdata/eng.traineddata'."""
    import sys
    # 1. tessdata adjacent to the binary (Windows and bundled installs).
    if tess_exe:
        adjacent = os.path.join(os.path.dirname(tess_exe), "tessdata")
        if os.path.isdir(adjacent):
            return adjacent
    # 2. Versioned Linux layout, newest first. Kept ahead of the relative
    #    prefix derivation so a stale /usr/share/tessdata never shadows a
    #    newer /usr/share/tesseract-ocr/<version>/tessdata (issue #27).
    if sys.platform.startswith(("linux", "darwin")):
        import glob
        for p in sorted(glob.glob("/usr/share/tesseract-ocr/*/tessdata"),
                        reverse=True):
            if os.path.isdir(p):
                return p
    # 3. Homebrew (Intel /usr/local, Apple Silicon /opt/homebrew) and
    #    custom prefixes: <prefix>/bin/tesseract -> <prefix>/share/tessdata.
    if tess_exe:
        prefixed = os.path.join(os.path.dirname(os.path.dirname(tess_exe)),
                                "share", "tessdata")
        if os.path.isdir(prefixed):
            return prefixed
    # 4. Older Debian, manual installs, Homebrew (Intel + Apple Silicon),
    #    snap fallbacks.
    if sys.platform.startswith(("linux", "darwin")):
        for p in ("/usr/share/tessdata",
                  "/usr/local/share/tessdata",
                  "/opt/homebrew/share/tessdata",
                  "/snap/tesseract/current/usr/share/tesseract-ocr/tessdata"):
            if os.path.isdir(p):
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
        tessdata = _find_tessdata(tess_exe)
        if tessdata:
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
                     "fra": t("tool.ocr.lang.fr"),     "deu": t("tool.ocr.lang.de"),  "ita": t("tool.ocr.lang.it")}
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
        pdf_path = self.drop_in.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.select_valid_pdf")); return
        out_path = self._resolve_output_file(self.drop_out, pdf_path)
        if not out_path: return
        try:
            import pytesseract  # noqa: F401 — surface ImportError before launching worker
        except ImportError:
            QMessageBox.critical(self, t("msg.missing_dep"), t("tool.ocr.dep_pytesseract"))
            return
        tess = self._ensure_tesseract()
        if tess is None: return
        try:
            import fitz  # noqa: F401 — surface ImportError before launching thread
        except ImportError:
            QMessageBox.critical(self, t("msg.missing_dep"), t("tool.ocr.dep_pymupdf"))
            return
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            QMessageBox.critical(self, t("msg.missing_dep"), t("tool.ocr.dep_pillow"))
            return

        codes = getattr(self, "_lang_codes", [c for _, c in self._LANGS])
        if not codes:
            QMessageBox.warning(self, t("msg.warning"), t("tool.ocr.no_langs"))
            return
        idx = max(0, min(self.cmb_lang.currentIndex(), len(codes) - 1))
        lang = codes[idx]
        fmt = self.cmb_fmt.currentIndex()
        pwd = self._pdf_password

        # Quickly count pages so the progress dialog has the correct max.
        try:
            with self._open_fitz(pdf_path) as _doc:
                n_pages = _doc.page_count
        except Exception as e:
            show_error(self, e); return

        progress = QProgressDialog(t("progress.ocr.page", current=1, total=n_pages),
                                   t("progress.cancel"), 0, n_pages, self)
        progress.setWindowTitle(t("progress.ocr.title"))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        class _OcrRunner(TaskRunner):
            def do_work(_self):
                import io as _io
                import fitz
                from PIL import Image
                import pytesseract
                doc = fitz.open(pdf_path)
                if doc.needs_pass:
                    # Verify authenticate() succeeded: an unchecked call
                    # on a doc whose password changed since _load_input
                    # would leave it locked and OCR empty pages. Mirror
                    # _open_fitz and raise a clear password error.
                    if not (pwd and doc.authenticate(pwd)):
                        raise ValueError(t("tool.err.wrong_password"))
                try:
                    if fmt == 1:
                        texts = []
                        for i, page in enumerate(doc):
                            if _self.is_cancelled():
                                return None
                            _self.progress.emit(
                                i, t("progress.ocr.page",
                                     current=i + 1, total=n_pages))
                            pix = page.get_pixmap(dpi=300)
                            # Strip alpha so the byte layout matches the
                            # "RGB" mode passed to PIL — frombytes assumes
                            # 3 bytes/pixel; with alpha present we'd be
                            # reading RGBA as RGB and Tesseract would get
                            # an image with shifted colour channels and
                            # produce gibberish text.
                            if pix.alpha:
                                pix = fitz.Pixmap(pix, 0)
                            # Convert non-RGB colourspaces (CMYK n=4 without
                            # alpha from press-ready scans, greyscale n=1)
                            # to RGB so PIL.frombytes("RGB", ...) gets the
                            # 3-bytes-per-pixel layout it expects.
                            if pix.n != 3:
                                pix = fitz.Pixmap(fitz.csRGB, pix)
                            img = Image.frombytes(
                                "RGB", (pix.width, pix.height), pix.samples)
                            texts.append(
                                pytesseract.image_to_string(img, lang=lang))
                        # Reject same input==output and write atomically
                        # so a mistaken overlap doesn't truncate the PDF.
                        self._check_not_same_path(out_path, [pdf_path])
                        out_dir = os.path.dirname(out_path) or os.getcwd()
                        _fd, _tmp = tempfile.mkstemp(suffix=".txt", dir=out_dir)
                        try:
                            with os.fdopen(_fd, "w", encoding="utf-8") as fh:
                                fh.write("\f".join(texts))
                            os.replace(_tmp, out_path)
                        except Exception:
                            if os.path.exists(_tmp):
                                try: os.unlink(_tmp)
                                except OSError: pass
                            raise
                    else:
                        # R11 I1: stream pages to the writer as they're
                        # processed instead of accumulating all per-page
                        # PDF bytes in a list before the final write.
                        # This reduces peak memory usage for large PDFs;
                        # the exact savings depend on pypdf's internal
                        # page copy behavior. Each per-page BytesIO is
                        # dropped as soon as writer.append() finishes
                        # copying its objects.
                        writer = PdfWriter()
                        for i, page in enumerate(doc):
                            if _self.is_cancelled():
                                return None
                            _self.progress.emit(
                                i, t("progress.ocr.page",
                                     current=i + 1, total=n_pages))
                            pix = page.get_pixmap(dpi=300)
                            # Strip alpha + convert non-RGB colourspaces to
                            # RGB so PIL.frombytes("RGB", ...) gets the
                            # expected 3-bytes-per-pixel layout (see comment
                            # in the .txt branch above).
                            if pix.alpha:
                                pix = fitz.Pixmap(pix, 0)
                            if pix.n != 3:
                                pix = fitz.Pixmap(fitz.csRGB, pix)
                            img = Image.frombytes(
                                "RGB", (pix.width, pix.height), pix.samples)
                            page_bytes = pytesseract.image_to_pdf_or_hocr(
                                img, lang=lang, extension="pdf")
                            writer.append(
                                PdfReader(_io.BytesIO(page_bytes)))
                            # Drop large per-page buffers now; without
                            # this they linger until the next loop
                            # iteration rebinds the locals.
                            pix = None
                            img.close()
                            del page_bytes
                        self._atomic_pdf_write(
                            writer, out_path, sources=[pdf_path])
                finally:
                    doc.close()
                return out_path

        self.action_btn.setEnabled(False)

        def _on_done(result):
            self.action_btn.setEnabled(True)
            if result is None:
                self._status(t("progress.cancelled"))
                return
            self._status(t("tool.ocr.status.done", path=result))
            QMessageBox.information(self, t("msg.done"),
                                    t("tool.ocr.done", path=result))

        def _on_err(exc):
            self.action_btn.setEnabled(True)
            # Accept either Exception (new TaskRunner contract) or str
            # (legacy callers); route through show_error so users see
            # a friendly translated dialog instead of a raw traceback.
            if not isinstance(exc, BaseException):
                exc = RuntimeError(str(exc))
            show_error(self, exc)

        self._runner = _OcrRunner()
        self._runner_thread = run_task(self, self._runner, progress, _on_done, _on_err)
