"""PDFApps – BasePage: standard page layout (header + scroll + action bar)."""

import os
import subprocess
import sys
import tempfile
import shutil

from PySide6.QtCore import Qt, QTimer, Signal
from shiboken6 import isValid
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
                               QPushButton, QLabel)

from app.constants import DESKTOP, ACCENT
from app.i18n import t
from app.utils import ToolHeader, ActionBar, scrolled, _paint_bg


def _reveal_file(path: str) -> None:
    """Open the OS file manager and highlight the given file when possible.
    Falls back to opening the parent folder on Linux (xdg-open can't select)."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])
    except OSError:
        pass


def _open_folder(path: str) -> None:
    """Open the folder containing the given file (or the folder itself)."""
    try:
        folder = os.path.dirname(path) if os.path.isfile(path) else path
        if sys.platform == "win32":
            subprocess.Popen(["explorer", os.path.normpath(folder)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except OSError:
        pass


class BasePage(QWidget):
    """Standard layout: fixed header + scroll area + action bar."""

    pipeline_done = Signal(str)  # emitted with temp output path

    def __init__(self, icon, title, desc, action_text, status_fn):
        super().__init__()
        self._status = status_fn
        self.setObjectName("content_area")
        self._pipeline_active = False
        self._pipeline_supported = False  # subclasses set True if they emit pipeline_done
        self._pipeline_tmp_dir: str | None = None
        # Password captured by _maybe_prompt_password for the loaded PDF.
        # Persists for the lifetime of one input file so _run can re-open
        # the same PDF (or fitz.Document) without re-prompting.
        self._pdf_password: str = ""

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        page_layout.addWidget(ToolHeader(icon, title, desc))

        # scrollable content
        self._inner = QWidget(); self._inner.setObjectName("scroll_inner")
        self._inner.setMinimumWidth(0)
        self._form  = QVBoxLayout(self._inner)
        self._form.setContentsMargins(24, 20, 24, 20)
        self._form.setSpacing(10)
        scroll_area = scrolled(self._inner)
        scroll_area.setMinimumWidth(0)
        page_layout.addWidget(scroll_area, 1)
        # Allow this page to shrink below its content's natural width — the
        # splitter needs this so the side panel can be made narrow.
        self.setMinimumWidth(0)

        # Widgets hidden when entering "compact mode" (input/output already
        # known from the viewer). Subclasses populate this list during build.
        self._compact_hidden: list = []
        self._compact_active = False
        self._compact_link: QPushButton | None = None

        # fixed action bar
        self._action_bar, self.action_btn = ActionBar(action_text, self._run)
        page_layout.addWidget(self._action_bar)

    def paintEvent(self, event):
        _paint_bg(self)

    def _build(self):
        """Subclasses add widgets to self._form here."""

    def _run(self):
        """Main logic called by the action button."""

    def _prompt_save_as(self, default_name: str = "result.pdf",
                        start_dir: str = "", filter_key: str = "file_filter.pdf") -> str:
        """Open a Save File dialog and return the chosen path (or "")."""
        base = start_dir if start_dir and os.path.isdir(start_dir) else DESKTOP
        suggested = os.path.join(base, default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, t("btn.choose"), suggested, t(filter_key))
        return path or ""

    def _prompt_save_dir(self, start_dir: str = "") -> str:
        """Open a folder picker and return the chosen directory (or "")."""
        base = start_dir if start_dir and os.path.isdir(start_dir) else DESKTOP
        return QFileDialog.getExistingDirectory(self, t("btn.choose"), base) or ""

    def _resolve_output_file(self, drop_widget, input_path: str = "",
                             filter_key: str = "file_filter.pdf") -> str:
        """Return the output file path, prompting via Save dialog if empty.
        In pipeline mode, returns a temp file path instead of prompting."""
        # Pipeline mode: save to temp file, skip dialog
        if self._pipeline_active:
            return self._make_pipeline_temp(input_path, drop_widget)
        out = drop_widget.path()
        if out:
            return out
        default_name = getattr(drop_widget, "_default", "") or "result.pdf"
        if input_path:
            base, ext = os.path.splitext(os.path.basename(input_path))
            stem, sfx = os.path.splitext(default_name)
            if sfx:
                default_name = base + "_" + stem + sfx
        start_dir = os.path.dirname(input_path) if input_path else ""
        out = self._prompt_save_as(default_name, start_dir, filter_key)
        if out:
            drop_widget.set_path(out)
        return out

    def _make_pipeline_temp(self, input_path: str, drop_widget=None) -> str:
        """Create a temp file path for pipeline output."""
        if self._pipeline_tmp_dir is None:
            self._pipeline_tmp_dir = tempfile.mkdtemp(prefix="pdfapps_")
        default_name = (getattr(drop_widget, "_default", "") or "result.pdf") if drop_widget else "result.pdf"
        if input_path:
            base, ext = os.path.splitext(os.path.basename(input_path))
            stem, sfx = os.path.splitext(default_name)
            if sfx:
                default_name = base + "_" + stem + sfx
        return os.path.join(self._pipeline_tmp_dir, default_name)

    def _pipeline_success(self, message: str, out_path: str) -> None:
        """Call after a successful tool run in pipeline mode:
        shows a toast and emits the pipeline_done signal."""
        self._show_toast(message, out_path)
        self.pipeline_done.emit(out_path)

    def cleanup_pipeline(self) -> None:
        """Remove temp files created during pipeline."""
        if self._pipeline_tmp_dir and os.path.isdir(self._pipeline_tmp_dir):
            shutil.rmtree(self._pipeline_tmp_dir, ignore_errors=True)
            self._pipeline_tmp_dir = None

    def set_compact_mode(self, active: bool, path: str = "") -> None:
        """Hide source/output boilerplate when the input PDF is implicit
        (e.g. coming from the viewer with a loaded document)."""
        # Pre-load the source path if provided
        if active and path:
            fn = getattr(self, "auto_load", None)
            if callable(fn):
                fn(path)

        for w in self._compact_hidden:
            try:
                w.setVisible(not active)
            except RuntimeError:
                pass  # widget destroyed

        # Lazily create the small "Change source..." link the first time we
        # enter compact mode.
        if active and self._compact_link is None:
            link = QPushButton("← " + t("compact.change_source"))
            link.setObjectName("compact_link")
            link.setFlat(True)
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.setStyleSheet(
                f"QPushButton#compact_link {{ color:{ACCENT}; border:none; "
                f"background:transparent; padding:2px 4px; text-align:left; }}"
                f"QPushButton#compact_link:hover {{ text-decoration: underline; }}"
            )
            link.clicked.connect(lambda: self.set_compact_mode(False))
            self._form.insertWidget(0, link)
            self._compact_link = link

        if self._compact_link is not None:
            self._compact_link.setVisible(active)

        self._compact_active = active
        self._pipeline_active = active and self._pipeline_supported

    def _show_toast(self, message: str, file_path: str = "") -> None:
        """Show a brief success toast above the action bar with optional
        'Open file' / 'Open folder' buttons."""
        import os
        # Remove previous toast if any
        old = getattr(self, "_toast_widget", None)
        if old:
            old.setParent(None); old.deleteLater()

        toast = QWidget(); toast.setObjectName("toast")
        toast.setStyleSheet(
            f"#toast {{ background: #065F46; border: 1px solid #10B981; "
            f"border-radius: 8px; padding: 8px 12px; }}"
            f"#toast QLabel {{ color: white; font-size: 10pt; background: transparent; }}"
            f"#toast QPushButton {{ color: #A7F3D0; border: none; background: transparent; "
            f"font-size: 10pt; text-decoration: underline; padding: 0 4px; }}"
            f"#toast QPushButton:hover {{ color: white; }}")
        h = QHBoxLayout(toast); h.setContentsMargins(8, 4, 8, 4); h.setSpacing(8)
        h.addWidget(QLabel(f"✔ {message}"), 1)
        if file_path and os.path.exists(file_path):
            btn_file = QPushButton(t("toast.open_file"))
            btn_file.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_file.clicked.connect(lambda: _reveal_file(file_path))
            h.addWidget(btn_file)
            btn_folder = QPushButton(t("toast.open_folder"))
            btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_folder.clicked.connect(lambda: _open_folder(file_path))
            h.addWidget(btn_folder)

        # Insert above action bar
        layout = self.layout()
        idx = layout.indexOf(self._action_bar)
        layout.insertWidget(idx, toast)
        self._toast_widget = toast
        # Guard the timer: if a newer toast already deleteLater'd this one,
        # the lambda must not touch the dead C++ object. PySide6 has no
        # QPointer, so use shiboken6.isValid() to check liveness.
        QTimer.singleShot(
            8000, lambda t=toast: t.setVisible(False) if isValid(t) else None)

    def _resolve_output_dir(self, drop_widget, input_path: str = "") -> str:
        """Return the output directory, prompting via folder picker if empty."""
        out = drop_widget.path()
        if out:
            return out
        start_dir = os.path.dirname(input_path) if input_path else ""
        out = self._prompt_save_dir(start_dir)
        if out:
            drop_widget.set_path(out)
        return out

    # ── encrypted-PDF helpers ──────────────────────────────────────────────

    def _maybe_prompt_password(self, path: str) -> bool:
        """If the PDF at `path` is encrypted, prompt the user; on success
        store the password on `self._pdf_password` and return True. Plain
        PDFs return True with the password cleared. Returns False if the
        user cancelled the prompt — caller should abort the load.

        If a password is already stored (e.g. propagated from the viewer
        in compact mode), it is tried silently first. Only if it fails
        is the user prompted."""
        try:
            import fitz
            doc = fitz.open(path)
        except Exception:
            return True  # let downstream surface its own error
        try:
            if not doc.needs_pass:
                self._pdf_password = ""
                return True
            if self._pdf_password and doc.authenticate(self._pdf_password):
                return True
        finally:
            doc.close()
        from app.utils import prompt_pdf_password
        ok, pwd = prompt_pdf_password(path, self)
        if not ok:
            return False
        self._pdf_password = pwd
        return True

    def _open_reader(self, path: str):
        """Open a pypdf PdfReader, decrypting with the stored password if
        the file is encrypted."""
        from pypdf import PdfReader
        r = PdfReader(path)
        if r.is_encrypted and self._pdf_password:
            r.decrypt(self._pdf_password)
        return r

    def _open_fitz(self, path: str):
        """Open a PyMuPDF Document, authenticating with the stored
        password if needed."""
        import fitz
        doc = fitz.open(path)
        if doc.needs_pass and self._pdf_password:
            doc.authenticate(self._pdf_password)
        return doc
