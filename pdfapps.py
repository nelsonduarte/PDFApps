"""PDFApps – entry point."""
import sys
import os

from PySide6.QtWidgets import QApplication, QMessageBox

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    _app = QApplication(sys.argv)
    QMessageBox.critical(None, "Dependência em falta",
                         "Instala a biblioteca pypdf:\n\npip install pypdf")
    sys.exit(1)

from app.window import MainWindow
from app.styles import STYLE, STYLE_LIGHT
from app.utils import _make_palette


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(" ")
    app.setApplicationDisplayName(" ")
    app.setStyle("Fusion")
    app.setPalette(_make_palette(True))
    app.setStyleSheet(STYLE)

    window = MainWindow()
    window.show()

    # Abrir PDF passado como argumento (ex: duplo clique num ficheiro .pdf)
    if len(sys.argv) > 1:
        pdf_arg = sys.argv[1]
        if os.path.isfile(pdf_arg) and pdf_arg.lower().endswith(".pdf"):
            window._viewer.load(pdf_arg)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
