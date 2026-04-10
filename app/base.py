"""PDFApps – BasePage: standard page layout (header + scroll + action bar)."""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
                               QPushButton, QLabel)

from app.constants import DESKTOP, ACCENT
from app.i18n import t
from app.utils import ToolHeader, ActionBar, scrolled, _paint_bg


class BasePage(QWidget):
    """Standard layout: fixed header + scroll area + action bar."""

    def __init__(self, icon, title, desc, action_text, status_fn):
        super().__init__()
        self._status = status_fn
        self.setObjectName("content_area")

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
        """Return the output file path, prompting via Save dialog if empty."""
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

    def _show_toast(self, message: str, file_path: str = "") -> None:
        """Show a brief success toast above the action bar with optional
        'Open file' / 'Open folder' buttons."""
        import os, subprocess, sys
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
            btn_file.clicked.connect(lambda: (
                subprocess.Popen(["explorer", "/select,", os.path.normpath(file_path)])
                if sys.platform == "win32"
                else subprocess.Popen(["xdg-open", file_path])))
            h.addWidget(btn_file)
            btn_folder = QPushButton(t("toast.open_folder"))
            btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_folder.clicked.connect(lambda: (
                subprocess.Popen(["explorer", os.path.dirname(os.path.normpath(file_path))])
                if sys.platform == "win32"
                else subprocess.Popen(["xdg-open", os.path.dirname(file_path)])))
            h.addWidget(btn_folder)

        # Insert above action bar
        layout = self.layout()
        idx = layout.indexOf(self._action_bar)
        layout.insertWidget(idx, toast)
        self._toast_widget = toast
        QTimer.singleShot(8000, lambda: toast.setVisible(False))

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
