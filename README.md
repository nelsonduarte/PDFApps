# PDFApps

> PDF editor and manager for Windows, macOS and Linux — fast, offline and subscription-free.

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-6.10-green?logo=qt&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![License](https://img.shields.io/badge/license-MIT-orange)

---

## Features

PDFApps brings together all everyday PDF operations in one place, with no internet connection or external service accounts required.

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

- Modern dark interface with collapsible sidebar
- Full drag and drop support across all file fields
- 100% offline — your files never leave your computer
- Cross-platform: Windows, macOS and Linux
- Installer with automatic OCR engine (Tesseract) detection and installation — Windows

---

## Requirements

### Running (end user)

| Platform | Requirement |
|---|---|
| **Windows** 10/11 64-bit | `PDFAppsSetup.exe` — includes everything; Tesseract installed automatically |
| **macOS** 10.14+ | `PDFApps.app` — Tesseract via `brew install tesseract tesseract-lang` |
| **Linux** (Ubuntu/Debian/Arch) | `PDFApps` binary — Tesseract via `sudo apt install tesseract-ocr` |

### Development

- Python 3.14+
- Dependencies in [requirements.txt](requirements.txt)

> **Tesseract OCR** is required for text recognition functionality.
> - **Windows**: the installer handles this automatically
> - **macOS**: `brew install tesseract tesseract-lang`
> - **Linux**: `sudo apt install tesseract-ocr tesseract-ocr-por tesseract-ocr-eng`

---

## Installation

### Windows

1. Download `PDFAppsSetup.exe` from the `dist/` folder
2. Run the installer and follow the steps
3. PDFApps will be available in the Start Menu and, optionally, on the Desktop

To uninstall, go to **Settings → Apps** or use the uninstall shortcut in the Start Menu.

---

### Linux (Ubuntu / Debian)

**Option A — From source (recommended)**

```bash
# 1. System dependencies
sudo apt update
sudo apt install python3-pip python3-venv tesseract-ocr tesseract-ocr-por tesseract-ocr-eng

# 2. Clone the repository
git clone <repository-url>
cd PDFApps

# 3. Virtual environment and Python dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Run
python3 pdfapps.py
```

**Option B — Build a native binary**

```bash
# (with venv active)
python -m PyInstaller --noconfirm pdfapps.spec

# Run
./dist/PDFApps
```

> PyInstaller does not cross-compile — the binary must be built on Linux itself.

---

### macOS

**Option A — From source (recommended)**

```bash
# 1. Install Homebrew (if needed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. System dependencies
brew install python tesseract tesseract-lang

# 3. Clone the repository
git clone <repository-url>
cd PDFApps

# 4. Virtual environment and Python dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Run
python3 pdfapps.py
```

**Option B — Build a native binary (.app)**

```bash
# (with venv active)
python -m PyInstaller --noconfirm pdfapps.spec

# Run
open dist/PDFApps
```

> PyInstaller does not cross-compile — the binary must be built on macOS itself.

---

## Development environment setup

```bash
# Clone the repository
git clone <repository-url>
cd PDFApps

# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run
python pdfapps.py        # Windows
python3 pdfapps.py       # macOS / Linux
```

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

## License

This project is licensed under the [MIT License](LICENSE).
