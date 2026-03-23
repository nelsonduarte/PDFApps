# PDFApps

> PDF editor and manager for Windows, macOS and Linux — fast, offline and subscription-free.

[![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.10-green?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](#)
[![License](https://img.shields.io/badge/license-MIT-orange)](LICENSE)
[![GitHub Sponsors](https://img.shields.io/badge/sponsor-♥-ea4aaa?logo=github)](https://github.com/sponsors/nelsonduarte)

---

## Why PDFApps?

Most PDF tools are either paid, browser-based, or require uploading your files to the cloud. **PDFApps** is different:

- **100% offline** — your files never leave your computer
- **No subscriptions** — free and open source, forever
- **All-in-one** — split, merge, compress, encrypt, OCR, edit and more in a single app
- **Cross-platform** — works on Windows, macOS and Linux
- **Fast** — lazy rendering opens large PDFs instantly

---

## Screenshots

<p align="center">
  <img src="screenshots/viewer.png" alt="PDF Viewer" width="800">
  <br><em>Integrated PDF viewer with continuous scroll and lazy rendering</em>
</p>

<p align="center">
  <img src="screenshots/editor.png" alt="Visual PDF Editor" width="800">
  <br><em>Visual PDF editor — redact, insert text, images, highlights and notes</em>
</p>

<p align="center">
  <img src="screenshots/tools.png" alt="PDF Tools" width="800">
  <br><em>All-in-one PDF tools — split, merge, compress, encrypt, OCR and more</em>
</p>

<p align="center">
  <img src="screenshots/light-theme.png" alt="Light Theme" width="800">
  <br><em>Light theme support</em>
</p>

---

## Features

| Tool | Description |
|---|---|
| **Split** | Split the PDF into multiple files by user-defined page ranges |
| **Merge** | Combine multiple PDFs (drag and drop) into a single output, with free ordering |
| **Rotate** | Rotate individual pages or the entire document at any angle |
| **Extract pages** | Export a subset of pages to a new PDF |
| **Reorder** | Drag-and-drop interface to reorder or remove pages with preview |
| **Compress** | Reduce file size with three compression levels (extreme / recommended / low) |
| **Encrypt** | Protect the PDF with a password or remove existing protection |
| **Watermark** | Overlay a watermark/stamp PDF on pages with opacity and position control |
| **OCR** | Recognise text in scanned PDFs — supports PT, EN, ES, FR and DE |
| **Edit** | Inline visual editor: redact, insert text, image, highlight, notes, forms and edit existing text |
| **Info** | Show metadata, page count, size and document properties |

### Integrated viewer

- Continuous scroll through all pages (Adobe Acrobat style)
- **Lazy rendering** — opens instantly; pages rendered in background as they are viewed
- Zoom with Ctrl+scroll or zoom buttons
- Text selection and copy by dragging
- Password-protected PDF support
- Drag & drop file support

### Other highlights

- Modern dark/light theme with collapsible sidebar
- Full drag and drop support across all file fields
- Cross-platform: Windows, macOS and Linux
- Installer with automatic OCR engine (Tesseract) detection and installation — Windows

---

## Getting started

### Download

| Platform | How to get it |
|---|---|
| **Windows** 10/11 64-bit | Download `PDFAppsSetup.exe` from [Releases](https://github.com/nelsonduarte/PDFApps-en/releases) |
| **macOS** 10.14+ | Build from source (see below) — Tesseract via `brew install tesseract tesseract-lang` |
| **Linux** | Build from source (see below) — Tesseract via `sudo apt install tesseract-ocr` |

### Run from source

```bash
# Clone the repository
git clone https://github.com/nelsonduarte/PDFApps-en.git
cd PDFApps-en

# Create virtual environment
python -m venv venv

# Activate — Windows
venv\Scripts\activate
# Activate — macOS / Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run
python pdfapps.py
```

> **Tesseract OCR** is required for text recognition:
> - **Windows**: the installer handles this automatically
> - **macOS**: `brew install tesseract tesseract-lang`
> - **Linux**: `sudo apt install tesseract-ocr tesseract-ocr-por tesseract-ocr-eng`

---

## Build

The build process generates three executables in the `dist/` folder:

```bash
# 1. Main application
python -m PyInstaller --noconfirm pdfapps.spec

# 2. Uninstaller
python -m PyInstaller --noconfirm uninstaller.spec

# 3. Installer (bundles the two above)
python -m PyInstaller --noconfirm installer.spec
```

| File | Description |
|---|---|
| `dist/PDFApps.exe` | Main application (~78 MB) |
| `dist/PDFAppsUninstall.exe` | Standalone uninstaller (~11 MB) |
| `dist/PDFAppsSetup.exe` | **Installer for distribution** (~99 MB) |

> PyInstaller does not cross-compile — the binary must be built on the target platform.

---

## Tech stack

| Component | Technology | Version |
|---|---|---|
| GUI | [PySide6](https://doc.qt.io/qtforpython/) (Qt 6) | 6.10.2 |
| PDF rendering | [PyMuPDF](https://pymupdf.readthedocs.io/) (fitz) | 1.27.2 |
| PDF manipulation | [pypdf](https://pypdf.readthedocs.io/) | 6.8.0 |
| OCR | [Tesseract](https://github.com/tesseract-ocr/tesseract) + [pytesseract](https://github.com/madmaze/pytesseract) | 0.3.13 |
| Image processing | [Pillow](https://python-pillow.org/) | 12.1.1 |
| Icons | [QtAwesome](https://github.com/spyder-ide/qtawesome) | 1.4.1 |
| Packaging | [PyInstaller](https://pyinstaller.org/) | 6.19.0 |

---

## Project structure

```
PDFApps/
├── pdfapps.py              # Application entry point
├── installer.py            # Installer (tkinter UI)
├── uninstaller.py          # Uninstaller
├── pdfapps.spec            # PyInstaller config — app
├── installer.spec          # PyInstaller config — installer
├── uninstaller.spec        # PyInstaller config — uninstaller
├── icon.ico                # Application icon
├── requirements.txt        # Python dependencies
├── app/                    # Modular source code
│   ├── constants.py        # Colours and design constants
│   ├── styles.py           # Qt stylesheet (dark/light theme)
│   ├── utils.py            # Shared utilities
│   ├── widgets.py          # Reusable widgets (DropFileEdit, etc.)
│   ├── base.py             # Base class for tools (BasePage)
│   ├── window.py           # Main window (MainWindow)
│   ├── tools/              # PDF manipulation tools
│   │   ├── split.py
│   │   ├── merge.py
│   │   ├── rotate.py
│   │   ├── extract.py
│   │   ├── reorder.py
│   │   ├── compress.py
│   │   ├── encrypt.py
│   │   ├── watermark.py
│   │   ├── info.py
│   │   └── ocr.py
│   ├── viewer/             # Integrated PDF viewer
│   │   ├── canvas.py       # Lazy page rendering in background threads (fitz)
│   │   └── panel.py        # Viewer panel with controls
│   └── editor/             # Visual PDF editor
│       ├── canvas.py       # Edit canvas (PdfEditCanvas)
│       ├── tab.py          # Edit tab (TabEditar)
│       └── dialogs.py      # Auxiliary dialogs
└── dist/                   # Generated executables (after build)
```

---

## Contributing

Contributions are welcome! Feel free to open issues or submit pull requests.

---

## Support the project

If you find PDFApps useful, consider [sponsoring the project](https://github.com/sponsors/nelsonduarte) to help keep it alive and growing.

---

## License

This project is licensed under the [MIT License](LICENSE).
