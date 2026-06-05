"""PDFApps – entry point."""
import argparse
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

try:
    import fitz  # PyMuPDF — used by viewer render, editor, most tools
    del fitz
except ImportError:
    _app = QApplication(sys.argv)
    QMessageBox.critical(None, "Missing dependency",
                         "Install PyMuPDF:\n\npip install pymupdf")
    sys.exit(1)

from app.constants import APP_VERSION
from app.window import MainWindow
from app.styles import STYLE, STYLE_LIGHT
from app.utils import _make_palette, setup_logging


def _load_dark_pref() -> bool:
    try:
        import json
        from app.i18n import _CONFIG_PATH
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("dark_mode", True)
    except Exception:
        return True


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the PDFApps command-line.

    Accepting *multiple* positional PDF paths fixes R8-M1: previously
    only ``sys.argv[1]`` was loaded, so dragging-and-dropping more than
    one file onto the executable (or "Open With" multi-selection on
    Windows / macOS) silently dropped every file after the first.
    ``argparse`` also brings standard ``--help`` / ``--version`` for
    free; the old hand-rolled parser treated ``-h`` as an invalid path
    and launched into the welcome screen.
    """
    parser = argparse.ArgumentParser(
        prog="pdfapps",
        description="PDFApps — fast desktop PDF editor.",
        add_help=True,
    )
    parser.add_argument(
        "files", nargs="*", metavar="PDF",
        help=("One or more PDF files to open. Each file opens in its "
              "own tab. Defaults to the welcome screen."),
    )
    parser.add_argument(
        "-v", "--version", action="version",
        version=f"PDFApps {APP_VERSION}",
    )
    return parser.parse_args(argv)


def main():
    setup_logging()
    # Parse BEFORE QApplication so --help / --version exit cleanly
    # without bringing up the Qt event loop (and the splash screen).
    args = _parse_args(sys.argv[1:])
    app = QApplication(sys.argv)
    app.setApplicationName(" ")
    app.setApplicationDisplayName(" ")
    app.setStyle("Fusion")
    dark = _load_dark_pref()
    app.setPalette(_make_palette(dark))
    app.setStyleSheet(STYLE if dark else STYLE_LIGHT)

    window = MainWindow()
    window.show()

    # Open PDFs passed as arguments (e.g.: double-click on a .pdf file
    # or multi-select "Open With" on Windows/macOS). Each valid path
    # opens through _load_and_track so it lands in a new tab and is
    # appended to the recents list, matching drag-and-drop semantics.
    for pdf_arg in args.files:
        if os.path.isfile(pdf_arg) and pdf_arg.lower().endswith(".pdf"):
            window._load_and_track(pdf_arg)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
