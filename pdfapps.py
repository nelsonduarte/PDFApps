"""PDFApps – entry point."""
import sys
import os

from PySide6.QtWidgets import QApplication, QMessageBox

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    _app = QApplication(sys.argv)
    QMessageBox.critical(None, "Missing dependency",
                         "Install the pypdf library:\n\npip install pypdf")
    sys.exit(1)

from app.window import MainWindow
from app.styles import STYLE, STYLE_LIGHT
from app.utils import _make_palette


def _load_dark_pref() -> bool:
    try:
        import json
        from app.i18n import _CONFIG_PATH
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("dark_mode", True)
    except Exception:
        return True


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(" ")
    app.setApplicationDisplayName(" ")
    app.setStyle("Fusion")
    dark = _load_dark_pref()
    app.setPalette(_make_palette(dark))
    app.setStyleSheet(STYLE if dark else STYLE_LIGHT)

    window = MainWindow()
    window.show()

    # Open PDF passed as argument (e.g.: double-click on a .pdf file)
    if len(sys.argv) > 1:
        pdf_arg = sys.argv[1]
        if os.path.isfile(pdf_arg) and pdf_arg.lower().endswith(".pdf"):
            window._viewer.load(pdf_arg)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
