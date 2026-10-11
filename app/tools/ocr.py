"""PDFApps – TabOCR: OCR text recognition tool."""

import os
import subprocess
import tempfile

import shiboken6
from PySide6.QtCore import (
    QCoreApplication, QObject, QRunnable, QThreadPool, Qt, Signal, Slot)
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QComboBox, QFileDialog, QMessageBox,
    QProgressDialog,
)
from pypdf import PdfReader, PdfWriter

from app.base import BasePage
from app.i18n import get_language, t
from app.utils import (section, info_lbl, show_error,
                       WrongPasswordError)
from app.worker import TaskRunner, run_task
from app.constants import TEXT_SEC, DESKTOP
from app.widgets import DropFileEdit
# Looked up through this module's globals by _locate_tesseract, and imported
# from here by tests: keep the names bound in app.tools.ocr.
from app.tools._ocr_paths import _find_tessdata, _find_tesseract
from app.tools._ocr_langs import (
    default_code, list_installed_langs, offered_codes)


def _locate_tesseract(pytesseract) -> None:
    """Point pytesseract at the Tesseract binary and its tessdata."""
    tess_exe = _find_tesseract()
    if tess_exe:
        pytesseract.pytesseract.tesseract_cmd = tess_exe
    tessdata = _find_tessdata(tess_exe)
    if tessdata:
        os.environ["TESSDATA_PREFIX"] = tessdata


_scan_pool = None


def _lang_scan_pool() -> QThreadPool:
    """The thread pool the language scan runs on, created on first use.

    Not the global pool: the editor caps that at 2 threads for its page
    renders, and the scan queued behind them (3.02 s behind two 3 s jobs,
    against 0.04 s on this pool). Parented to the application, and
    deleted with it at exit (measured with PySide6 6.11.1 and 6.11.2: it
    is deleted at exit, and the exit waits for the job, with or without
    the parent). The scan's timeout bounds that wait when Tesseract is a
    single process: with one that sleeps 20 s, the app exited 4.1 s after
    the window closed, 1 s into the scan. On Windows, a wrapper whose
    child keeps the pipe open can hold it longer: with a tesseract.bat,
    19.1 to 19.4 s, as subprocess.run reads the pipe to its end after the
    kill. On Linux, subprocess.run only waits for the killed process: with
    a sh wrapper whose child kept the pipe, the app exited 4.0 to 4.2 s
    after the window closed, and the child ran on.
    """
    global _scan_pool
    # The pool is deleted with the application it belongs to, so a
    # QApplication created after that one needs a new pool.
    if _scan_pool is None or not shiboken6.isValid(_scan_pool):
        _scan_pool = QThreadPool(QCoreApplication.instance())
        _scan_pool.setMaxThreadCount(1)
    return _scan_pool


class _LangScanSignals(QObject):
    done = Signal(object)  # installed codes, or None if the scan failed


class _LangScanJob(QRunnable):
    """Runs ``tesseract --list-langs`` off the GUI thread."""

    def __init__(self, tesseract_cmd: str, signals: _LangScanSignals):
        super().__init__()
        self._tesseract_cmd = tesseract_cmd
        self._signals = signals
        self.setAutoDelete(True)

    def run(self):
        try:
            installed = list_installed_langs(self._tesseract_cmd)
        except Exception:
            # Tesseract missing, too slow or --list-langs failed: the combo
            # keeps the list it shows. _run repeats the call, and reports a
            # Tesseract that cannot start.
            installed = None
        try:
            self._signals.done.emit(installed)
        except RuntimeError:
            # The app was closed while the scan ran and its teardown
            # deleted the signals object ("Signal source has been
            # deleted"). Nothing is left to receive the result; uncaught,
            # the error reached pdfapps._excepthook and was logged as a
            # CRITICAL uncaught exception on every such exit.
            pass


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
        for name, code in self._LANGS:
            self.cmb_lang.addItem(name, code)
        # Until the scan or _run rebuilds the list, show the entry the
        # rule picks from the fixed list, so a Run made before the scan's
        # result arrives (or after a failed scan) uses the language shown.
        # Run still uses another code when the rule picks otherwise from
        # the installed list: the UI language's code is installed but not
        # in the fixed list (it, zh, nl), or the code shown is not
        # installed. Run goes ahead with the rule's pick in that case.
        fixed = [c for _, c in self._LANG_KEYS]
        self.cmb_lang.setCurrentIndex(
            fixed.index(default_code(fixed, get_language())))
        # The code the user picked, or that the rule picked from the
        # installed list. None until then: the next rebuild applies
        # default_code. Kept apart from the combo, whose selection is
        # empty while the code is not installed, so the pick comes back
        # when the code is installed again.
        self._lang_pick = None
        self.cmb_lang.activated.connect(self._on_lang_activated)
        self._lang_scan_started = False
        # Parentless: the scan job emits on it from a pool thread, so it
        # must outlive a page destroyed mid-scan. The receiver is a method
        # of this page, so Qt drops the queued result once the page is
        # gone, and the slot needs no shiboken6.isValid check. A lambda
        # is not tied to the page: its call reached the deleted page.
        self._lang_scan_signals = _LangScanSignals()
        self._lang_scan_signals.done.connect(
            self._on_langs_scanned, Qt.ConnectionType.QueuedConnection)
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
            doc = self._open_pymupdf(p)
            self.lbl_info.setText(t("edit.status.pages", n=doc.page_count))
            doc.close()
        except Exception as e:
            self.lbl_info.setText(t("tool.split.error_info", e=e))

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def showEvent(self, event):
        super().showEvent(event)
        # On first show, not in __init__: every tool page is built at
        # startup, and a session that never opens OCR never runs
        # tesseract.
        if not self._lang_scan_started:
            self._lang_scan_started = True
            self._start_lang_scan()

    def _start_lang_scan(self):
        try:
            import pytesseract
        except ImportError:
            return  # _run reports the missing dependency
        _locate_tesseract(pytesseract)
        _lang_scan_pool().start(_LangScanJob(
            pytesseract.pytesseract.tesseract_cmd, self._lang_scan_signals))

    @Slot(object)
    def _on_langs_scanned(self, installed):
        if installed is not None:
            self._update_lang_combo(installed)

    def _on_lang_activated(self, idx):
        self._lang_pick = self.cmb_lang.itemData(idx)

    def _ensure_tesseract(self):
        """Locate Tesseract, set TESSDATA_PREFIX and update available languages."""
        import pytesseract, sys
        _locate_tesseract(pytesseract)

        try:
            installed = list_installed_langs(
                pytesseract.pytesseract.tesseract_cmd)
        except (OSError, subprocess.CalledProcessError):
            # OSError: no binary to start. An exit code other than 0 or 1
            # gets the same dialog, for parity: pytesseract 0.3.13 raises
            # TesseractNotFoundError for it (pytesseract.py:432-433), and
            # get_tesseract_version, which this call replaces, reached
            # this dialog on any non-zero exit. Tesseract exits 0 for
            # --list-langs even with an unusable tessdata, while a copy
            # missing its DLLs exits 0xC0000135 on Windows and one missing
            # libtesseract exits 127 on Linux.
            if sys.platform == "win32":
                install_hint = "https://github.com/UB-Mannheim/tesseract/wiki"
            elif sys.platform == "darwin":
                install_hint = "brew install tesseract tesseract-lang"
            else:
                install_hint = "sudo apt install tesseract-ocr tesseract-ocr-por tesseract-ocr-eng"
            QMessageBox.critical(self, t("tool.ocr.tess_not_found"),
                t("tool.ocr.tess_msg", hint=install_hint))
            return None
        except subprocess.TimeoutExpired:
            # Tesseract started but --list-langs timed out: keep the list
            # shown and let the OCR call report any error.
            pass
        else:
            self._update_lang_combo(installed)

        return pytesseract

    def _selected_lang_code(self):
        """Tesseract code of the selected entry, or None if none is."""
        return self.cmb_lang.currentData()

    def _update_lang_combo(self, installed: list):
        """Show only installed languages + possible combinations."""
        # _run rebuilds the combo after the user picked a language and
        # before it reads the pick, and clear() followed by the first
        # addItem selects index 0. Left there, every run used the first
        # installed code (osd aside), whatever the user had chosen, so the
        # pick is restored by code. A code that is not installed leaves
        # nothing selected, so _run asks the user to choose instead of
        # OCRing in another language.
        codes = offered_codes(installed)
        if self._lang_pick is None:
            self._lang_pick = default_code(codes, get_language())
        target = self._lang_pick
        label_map = {"por": t("tool.ocr.lang.pt"), "eng": t("tool.ocr.lang.en"), "spa": t("tool.ocr.lang.es"),
                     "fra": t("tool.ocr.lang.fr"),     "deu": t("tool.ocr.lang.de"),  "ita": t("tool.ocr.lang.it"),
                     "chi_sim": t("tool.ocr.lang.zh"), "nld": t("tool.ocr.lang.nl"),
                     "por+eng": t("tool.ocr.lang.pt_en")}
        self.cmb_lang.clear()
        for code in codes:
            self.cmb_lang.addItem(label_map.get(code, code), code)
        self.cmb_lang.setCurrentIndex(
            codes.index(target) if target in codes else -1)

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
            import pymupdf  # noqa: F401 — surface ImportError before launching thread
        except ImportError:
            QMessageBox.critical(self, t("msg.missing_dep"), t("tool.ocr.dep_pymupdf"))
            return
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            QMessageBox.critical(self, t("msg.missing_dep"), t("tool.ocr.dep_pillow"))
            return

        if self.cmb_lang.count() == 0:
            QMessageBox.warning(self, t("msg.warning"), t("tool.ocr.no_langs"))
            return
        lang = self._selected_lang_code()
        if lang is None:
            QMessageBox.warning(self, t("msg.warning"),
                                t("tool.ocr.lang_unavailable"))
            return
        fmt = self.cmb_fmt.currentIndex()
        pwd = self._pdf_password

        # Quickly count pages so the progress dialog has the correct max.
        try:
            with self._open_pymupdf(pdf_path) as _doc:
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
                import pymupdf
                from PIL import Image
                import pytesseract
                doc = pymupdf.open(pdf_path)
                if doc.needs_pass:
                    # Verify authenticate() succeeded: an unchecked call
                    # on a doc whose password changed since _load_input
                    # would leave it locked and OCR empty pages. Mirror
                    # _open_pymupdf and raise a clear password error.
                    if not (pwd and doc.authenticate(pwd)):
                        raise WrongPasswordError(t("tool.err.wrong_password"))
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
                                pix = pymupdf.Pixmap(pix, 0)
                            # Convert non-RGB colourspaces (CMYK n=4 without
                            # alpha from press-ready scans, greyscale n=1)
                            # to RGB so PIL.frombytes("RGB", ...) gets the
                            # 3-bytes-per-pixel layout it expects.
                            if pix.n != 3:
                                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
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
                                pix = pymupdf.Pixmap(pix, 0)
                            if pix.n != 3:
                                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
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
