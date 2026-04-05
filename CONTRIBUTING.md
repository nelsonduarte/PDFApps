# Contributing to PDFApps

Thank you for your interest in contributing to PDFApps! This guide covers the full codebase architecture, every module, class, and function — so you can understand the code and start contributing right away.

---

## Table of Contents

- [Getting Started](#getting-started)
- [Architecture Overview](#architecture-overview)
- [Directory Structure](#directory-structure)
- [Entry Point](#entry-point)
- [Main Window](#main-window)
- [Base Page (Tool Template)](#base-page-tool-template)
- [Constants & Design Tokens](#constants--design-tokens)
- [Stylesheets](#stylesheets)
- [Widgets](#widgets)
- [Utilities](#utilities)
- [Internationalization (i18n)](#internationalization-i18n)
- [Viewer System](#viewer-system)
- [Editor System](#editor-system)
- [Tool System](#tool-system)
- [Auto-Updater](#auto-updater)
- [Installer & Uninstaller](#installer--uninstaller)
- [Build & Release](#build--release)
- [Key Data Flows](#key-data-flows)
- [Conventions & Guidelines](#conventions--guidelines)

---

## Getting Started

### Prerequisites

- Python 3.14+
- Windows / macOS / Linux
- (Optional) [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) — for the OCR tool
- (Optional) [Ghostscript](https://www.ghostscript.com/) — for advanced PDF compression

### Setup

```bash
git clone https://github.com/nelsonduarte/PDFApps.git
cd PDFApps
python -m venv venv
venv/Scripts/activate        # Windows
# source venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
python pdfapps.py
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `PySide6` | Qt 6 GUI framework |
| `pypdf` | PDF manipulation (split, merge, encrypt, metadata) |
| `pymupdf` (fitz) | PDF rendering (viewer, editor, compression) |
| `qtawesome` | Font Awesome icons in Qt widgets |
| `pillow` | Image processing (import tool, icon generation) |
| `pytesseract` | OCR engine wrapper (Tesseract integration) |
| `python-docx` | DOCX export in the convert tool |
| `pyinstaller` | Executable building (dev/CI only) |

**Optional runtime dependencies:**
- **Ghostscript** (`gs` / `gswin64c`) — used by the compression pipeline for high-quality image downsampling
- **Tesseract** — used by the OCR tool to add text layers to scanned PDFs

---

## Architecture Overview

PDFApps is a **modular desktop application** built with PySide6. The app is organized around a single `MainWindow` that manages three main areas: a sidebar for navigation, a tabbed PDF viewer, and a stack of tool panels.

```
┌─────────────────────────────────────────────────────────────┐
│ Workspace Bar                                               │
│ [≡] Workspace title    [📁][🕐][🖨][🔍][−][%][+] ... [?][PT][☀]│
├──────────┬──────────────────────────────────────────────────┤
│          │  QSplitter (horizontal)                          │
│ Sidebar  │  ┌──────────────────┬───────────────────────┐    │
│          │  │ Tool Stack       │ Tabbed Viewer          │    │
│ PDFApps  │  │ (QStackedWidget) │ (QTabBar +             │    │
│ logo     │  │                  │  QStackedWidget of     │    │
│          │  │ Hidden when no   │  PdfViewerPanel)       │    │
│ 13 tools │  │ tool is active;  │                        │    │
│ (nav)    │  │ shown when user  │ Each tab holds one     │    │
│          │  │ selects a tool   │ PdfViewerPanel with    │    │
│ footer   │  │ from sidebar     │ its own _SelectCanvas  │    │
│          │  └──────────────────┴───────────────────────┘    │
├──────────┴──────────────────────────────────────────────────┤
│ QStatusBar                                                  │
└─────────────────────────────────────────────────────────────┘
```

### Key Principles

- **Offline first** — no network calls except the optional update check on startup
- **Single entry point** — `pdfapps.py` bootstraps the entire application
- **Consistent tool UX** — all 13 tools inherit from `BasePage` for a uniform layout
- **Lazy rendering** — the viewer only renders visible pages plus a small buffer
- **Theme-aware** — every widget, icon, and style adapts to dark/light mode
- **i18n everywhere** — all user-facing strings go through `t()` with 8 languages

---

## Directory Structure

```
PDFApps/
├── pdfapps.py              # Entry point — bootstraps QApplication + MainWindow
├── installer.py            # Cross-platform installer (tkinter GUI, ~970 lines)
├── uninstaller.py          # Cross-platform uninstaller (tkinter GUI, ~230 lines)
├── requirements.txt        # Python dependencies
│
├── pdfapps.spec            # PyInstaller spec — main app executable
├── installer.spec          # PyInstaller spec — installer (bundles app + uninstaller)
├── uninstaller.spec        # PyInstaller spec — uninstaller
│
├── icon.ico                # Multi-size Windows icon (PNG-compressed, up to 512px)
├── icon_512.png            # High-res icon source (2048px)
├── pdfapps.svg             # Vector logo (used in sidebar brand area)
│
├── app/                    # ── Main application package ──
│   ├── __init__.py
│   ├── window.py           # MainWindow — layout, navigation, tabs, theme (~720 lines)
│   ├── base.py             # BasePage — standard 3-section tool layout template
│   ├── constants.py        # Color tokens, version string, paths
│   ├── styles.py           # QSS stylesheets (dark + light, ~450 lines)
│   ├── widgets.py          # DropFileEdit, MultiDropWidget (drag & drop)
│   ├── utils.py            # Helpers: compression, palettes, UI factories (~360 lines)
│   ├── i18n.py             # Translation system + config management (~150 lines)
│   ├── translations.json   # 300+ keys × 8 languages
│   ├── updater.py          # Auto-update via GitHub Releases API
│   │
│   ├── viewer/             # ── PDF viewer subsystem ──
│   │   ├── __init__.py
│   │   ├── panel.py        # PdfViewerPanel — viewer UI (header, search, print)
│   │   ├── canvas.py       # _SelectCanvas — threaded continuous-scroll renderer (~450 lines)
│   │   └── presentation.py # PresentationWidget — fullscreen slideshow (F5)
│   │
│   ├── editor/             # ── PDF editor subsystem ──
│   │   ├── __init__.py
│   │   ├── tab.py          # TabEditar — editor tool with 8 modes (~650 lines)
│   │   ├── canvas.py       # PdfEditCanvas — single-page edit canvas with overlays
│   │   └── dialogs.py      # Text, note, password, text-edit dialogs
│   │
│   └── tools/              # ── 13 tool tabs ──
│       ├── split.py        # TabDividir — split PDF by page ranges
│       ├── merge.py        # TabJuntar — merge multiple PDFs
│       ├── rotate.py       # TabRotar — rotate pages by angle
│       ├── extract.py      # TabExtrair — extract page subsets
│       ├── reorder.py      # TabReordenar — drag-reorder pages
│       ├── compress.py     # TabComprimir — 3-pass compression pipeline
│       ├── encrypt.py      # TabEncriptar — encrypt / decrypt PDFs
│       ├── watermark.py    # TabMarcaDagua — watermark overlay
│       ├── ocr.py          # TabOCR — add OCR text layer (Tesseract)
│       ├── convert.py      # TabConverter — export to PNG/JPG/DOCX/TXT
│       ├── import_pdf.py   # TabImport — import TXT/images/Markdown → PDF
│       └── info.py         # TabInfo — display PDF metadata
│
├── docs/                   # GitHub Pages website
│   ├── index.html          # Landing page (JS-based i18n, 8 languages)
│   └── *.png               # Screenshots
│
└── .github/workflows/
    └── build.yml           # CI/CD — build on 3 platforms + create GitHub Release
```

---

## Entry Point

### `pdfapps.py`

The main entry point (~52 lines). Bootstrapping flow:

1. **Dependency check** — verifies `pypdf` is installed; shows an error dialog if not
2. **Config loading** — reads `~/.pdfapps_config.json` for dark mode preference
3. **QApplication** — creates the app with Fusion style
4. **Theme application** — sets palette and stylesheet based on saved preference
5. **MainWindow** — creates and shows the main window
6. **CLI argument** — if a PDF path was passed (e.g., double-click on a .pdf file), opens it
7. **Event loop** — `app.exec()`

```python
def main():
    # 1. Check pypdf
    # 2. Load dark_mode from config
    # 3. QApplication with Fusion style
    # 4. Apply palette + stylesheet
    # 5. MainWindow().show()
    # 6. Open sys.argv[1] if present
    # 7. sys.exit(app.exec())
```

**Config file:** `~/.pdfapps_config.json`
```json
{
  "dark_mode": true,
  "language": "pt",
  "recent_files": ["C:/path/to/file1.pdf", "C:/path/to/file2.pdf"]
}
```

---

## Main Window

### `app/window.py` — `MainWindow(QMainWindow)`

The central orchestrator (~720 lines). This is the largest and most important file.

#### Signals

| Signal | Type | Purpose |
|--------|------|---------|
| `_update_ready` | `Signal()` | Emitted when a new version is found (cross-thread) |

#### Layout Construction (`__init__`)

The constructor builds the entire UI in this order:

1. **Window setup** — title, icon, size (1280×780), status bar
2. **Workspace bar** — horizontal toolbar at the top:
   - Sidebar toggle button (hamburger `≡` / close `✕`)
   - Title + subtitle labels
   - Open PDF, Recent, Print, Search buttons
   - Zoom widget (−, %, +, Reset)
   - Page navigation widget (‹, input, /total, ›)
   - Tool badge label ("Mode: Viewer" / "Mode: Split")
   - Help, Language, Theme buttons
   - Update button (hidden, shown when update available)
3. **Body** — horizontal layout containing:
   - **Sidebar** (fixed 228px) — brand area, nav list (13 items), footer
   - **QSplitter** — tool stack (left) + tabbed viewer (right)
4. **Navigation wiring** — connects sidebar clicks to tool switching
5. **Theme loading** — applies saved dark/light preference

#### Navigation System

Tools are defined in `NAV_ITEMS` — a list of tuples:
```python
NAV_ITEMS = [
    (t("nav.split"),     "fa5s.cut",          TabDividir),
    (t("nav.merge"),     "fa5s.layer-group",   TabJuntar),
    (t("nav.rotate"),    "fa5s.sync-alt",      TabRotar),
    # ... 10 more tools ...
]
```

Each tuple maps a translated name, a Font Awesome icon, and a Tab class. The sidebar `QListWidget` is populated from this list, and clicking an item calls `_on_nav_clicked()`.

#### Methods Reference

**Properties:**

| Method | Returns | Description |
|--------|---------|-------------|
| `_viewer` | `PdfViewerPanel` | Returns the active tab's viewer panel |

**Tab Management:**

| Method | Parameters | Description |
|--------|-----------|-------------|
| `_add_viewer_tab(path="")` | `path: str` | Creates a new viewer tab; loads PDF if path given |
| `_update_tab_visibility()` | — | Shows/hides tab bar based on open document count |
| `_on_tab_changed(idx)` | `idx: int` | Switches active viewer when tab changes |
| `_close_tab(idx)` | `idx: int` | Closes tab; resets to placeholder if last tab |

**Navigation:**

| Method | Parameters | Description |
|--------|-----------|-------------|
| `_on_nav_clicked(item)` | `QListWidgetItem` | Toggles tool visibility; shows tool stack or viewer |
| `_open_tool_by_name(name)` | `name: str` | Opens a tool programmatically by its nav name |
| `_try_auto_load(index)` | `index: int` | Calls `auto_load(path)` on the tool if viewer has a PDF |
| `_edit_tool_idx()` | — | Returns the index of TabEditar in NAV_ITEMS |

**File Operations:**

| Method | Parameters | Description |
|--------|-----------|-------------|
| `_open_pdf()` | — | Opens file dialog, calls `_load_and_track()` |
| `_load_and_track(path)` | `path: str` | Loads PDF; opens new tab if current tab has a document |
| `_open_in_new_tab()` | — | Opens file dialog and loads in a new tab |
| `_show_recent_menu()` | — | Shows popup menu with recent files list |
| `_clear_recent()` | — | Clears recent files from config |

**Page Navigation (workspace bar):**

| Method | Parameters | Description |
|--------|-----------|-------------|
| `_update_page_nav()` | — | Updates page input and total label from viewer scroll position |
| `_goto_prev_page()` | — | Scrolls viewer to previous page |
| `_goto_next_page()` | — | Scrolls viewer to next page |
| `_goto_input_page()` | — | Scrolls to the page number typed in the input field |
| `_setup_zoom_bar(active, canvas)` | `active: bool, canvas=None` | Connects/disconnects zoom buttons to a canvas |

**UI State:**

| Method | Parameters | Description |
|--------|-----------|-------------|
| `_toggle_sidebar()` | — | Toggles sidebar visibility (fully hides/shows) |
| `_toggle_fullscreen()` | — | Toggles fullscreen (F11): hides/shows workspace bar, sidebar, status bar |
| `_start_presentation()` | — | Starts presentation mode (F5): opens `PresentationWidget` fullscreen |
| `_toggle_theme()` | — | Switches dark↔light mode and saves preference |
| `_apply_theme()` | — | Reapplies QSS, palette, and all icon colors |
| `_set_status(msg)` | `msg: str` | Shows message in status bar |
| `_show_language_menu()` | — | Shows language selection popup |
| `_set_language(code, name)` | `code: str, name: str` | Changes language, shows restart message |

**Drag & Drop:**

| Method | Parameters | Description |
|--------|-----------|-------------|
| `dragEnterEvent(e)` | `QDragEnterEvent` | Accepts drop if dragged file is a PDF |
| `dropEvent(e)` | `QDropEvent` | Opens dropped PDF via `_load_and_track()` |

**Auto-Update:**

| Method | Parameters | Description |
|--------|-----------|-------------|
| `_check_for_updates_async()` | — | Spawns QThread to check GitHub Releases API |
| `_on_update_found()` | — | Called in worker thread when update exists |
| `_notify_update()` | — | Shows update notification (main thread, via signal) |
| `_show_update_dialog()` | — | Opens UpdateDialog for download + install |

---

## Base Page (Tool Template)

### `app/base.py` — `BasePage(QWidget)`

Abstract base class that all 13 tool tabs inherit from. Provides a consistent 3-section layout:

```
┌──────────────────────────────┐
│ ToolHeader                   │  ← Fixed at top (icon + title + description)
│ (icon, title, desc)          │
├──────────────────────────────┤
│                              │
│ Scrollable form area         │  ← self._form (QVBoxLayout)
│                              │     Subclasses add their widgets here
│ [DropFileEdit]               │
│ [Options GroupBox]           │
│ [Output DropFileEdit]        │
│                              │
├──────────────────────────────┤
│ ActionBar (primary button)   │  ← Fixed at bottom
└──────────────────────────────┘
```

#### Methods

| Method | Parameters | Description |
|--------|-----------|-------------|
| `__init__(icon, title, desc, action_text, status_fn)` | icon: str, title/desc/action_text: str, status_fn: callable | Creates layout with header, scroll area, action bar |
| `_build()` | — | Override point — add widgets to `self._form` |
| `_run()` | — | Override point — called when action button is clicked |
| `paintEvent(event)` | — | Ensures stylesheet backgrounds render correctly |

#### Key Attributes

- `self._form` — `QVBoxLayout` inside the scroll area; add your tool's widgets here
- `self._status` — callable to update the status bar: `self._status("Done!")`

---

## Constants & Design Tokens

### `app/constants.py`

Central location for all color constants, version, and paths.

```python
APP_VERSION = "1.7.9"
GITHUB_REPO = "nelsonduarte/PDFApps"
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
```

#### Dark Theme Colors

| Constant | Value | Usage |
|----------|-------|-------|
| `ACCENT` | `#14B8A6` | Primary teal — buttons, selections, active states |
| `ACCENT_H` | `#0D9488` | Hover state |
| `ACCENT_P` | `#0F766E` | Pressed state |
| `BG_BASE` | `#0B0F12` | Window background |
| `BG_SIDE` | `#11161A` | Sidebar background |
| `BG_CARD` | `#182127` | Cards, headers, tab bar |
| `BG_INPUT` | `#1D2A33` | Input fields, drop zones |
| `BG_INNER` | `#121B22` | Scroll area / canvas background |
| `BORDER` | `#2A3944` | Borders and separators |
| `TEXT_PRI` | `#E6F4F1` | Primary text |
| `TEXT_SEC` | `#93A9A3` | Secondary / muted text |

#### Light Theme Colors

Prefixed with `_L`: `_LA` (accent), `_LB` (base bg), `_LS` (sidebar bg), `_LC` (card bg), `_LI` (input bg), `_LN` (inner bg), `_LO` (border), `_LP` (primary text), `_LQ` (secondary text).

---

## Stylesheets

### `app/styles.py`

Two complete Qt Style Sheets (~450 lines total): `STYLE` (dark) and `STYLE_LIGHT` (light). Both use Python f-string formatting with the color constants.

#### Key QSS Selectors

| Selector | Widget | Notes |
|----------|--------|-------|
| `#sidebar` | Left navigation panel | Fixed width 228px |
| `#brand_area` | Logo + app name area | Top of sidebar |
| `#nav_list` | Tool navigation list | Custom selected/hover states |
| `#nav_list::item:selected` | Active tool | Teal accent background |
| `#workspace_bar` | Top toolbar | Dark header with border-bottom |
| `#workspace_title` | "Workspace" label | Bold, primary text |
| `#workspace_badge` | Mode indicator | "Mode: Viewer" pill |
| `#viewer_tabs` | Tab bar | Closable, movable tabs |
| `#viewer_nav_btn` | Toolbar icon buttons | 28×28, transparent bg, rounded hover |
| `#content_area` | Tool stack container | — |
| `#tool_header` | Tool header section | Icon + title + description |
| `#th_icon` | Tool header icon button | 40×40, teal border |
| `#action_bar` | Bottom action bar | Fixed at bottom of tool |
| `#btn_primary` | Primary action button | Teal background, white text |
| `#btn_danger` | Danger button | Red background |
| `#drop_zone` | File drop widget | Dashed border, hover highlight |
| `#theme_btn` | Theme/language/help buttons | 28×28, bordered |
| `#page_input` | Page number input | Small text field in nav |
| `QStatusBar` | Bottom status bar | Subtle text, thin |
| `QSplitter::handle` | Splitter between panels | 1px, border color |

#### Helper Function

| Function | Parameters | Returns | Description |
|----------|-----------|---------|-------------|
| `_make_palette(dark)` | `dark: bool` | `QPalette` | Creates themed palette for dark/light mode |

---

## Widgets

### `app/widgets.py`

#### `DropFileEdit(QWidget)` — File Selector with Drag & Drop

The primary input widget used by every tool. Supports both "open" mode (select existing file) and "save" mode (choose output path).

**Signals:**

| Signal | Type | Description |
|--------|------|-------------|
| `path_changed` | `Signal(str)` | Emitted whenever the file path changes |

**Constructor:**
```python
DropFileEdit(
    placeholder: str = None,   # hint text (e.g., "Drop PDF here")
    filters: str = None,       # file dialog filter (e.g., "PDF (*.pdf)")
    save: bool = False,        # True = save dialog, False = open dialog
    default_name: str = "result.pdf"  # default filename for save dialog
)
```

**Methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `path()` | `str` | Returns the current file path (empty if none) |
| `set_path(p)` | — | Sets path, updates UI display, emits `path_changed` |
| `clear()` | — | Resets to placeholder state, emits `path_changed("")` |

**Drag & Drop:**
- `dragEnterEvent` — accepts if drag contains file URLs
- `dropEvent` — extracts first URL, calls `set_path()`
- `_browse()` — opens native file dialog (save or open mode)

#### `MultiDropWidget(QWidget)` — Multi-File Drop Zone

Used by Merge and Import tools for accepting multiple files.

**Constructor:**
```python
MultiDropWidget(on_drop_callback: callable)
# callback receives list of PDF file paths
```

**Behavior:**
- Accepts multiple file drops
- Filters to `.pdf` files only
- Calls `on_drop_callback(paths)` with the filtered list

---

## Utilities

### `app/utils.py`

A collection of helper functions used across the application (~360 lines).

#### Resource Management

| Function | Signature | Description |
|----------|-----------|-------------|
| `resource_path` | `(rel: str) -> str` | Resolves paths for both dev mode and PyInstaller bundles. Uses `sys._MEIPASS` when frozen. |

#### Theme Helpers

| Function | Signature | Description |
|----------|-----------|-------------|
| `_make_palette` | `(dark: bool) -> QPalette` | Creates a complete `QPalette` with all color roles for dark or light theme |
| `_paint_bg` | `(widget: QWidget)` | Forces a `QWidget` subclass to honour stylesheet backgrounds via `QStyleOption` painting |

#### Page Parsing

| Function | Signature | Description |
|----------|-----------|-------------|
| `parse_pages` | `(text: str, total: int) -> list[int]` | Parses `"1,3,5-7"` into `[0, 2, 4, 5, 6]` (zero-indexed). Raises `ValueError` if out of range. |

#### File Dialogs

| Function | Signature | Description |
|----------|-----------|-------------|
| `pick_pdfs` | `(parent) -> list[str]` | Multi-select PDF file dialog |
| `pick_folder` | `(parent) -> str` | Directory selection dialog |

#### UI Factories

These create pre-styled widgets used by `BasePage` and tools:

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `ToolHeader` | `(icon_name, title, desc)` | `QWidget` | Fixed header with icon button (40×40), title, and description |
| `ActionBar` | `(btn_text, slot)` | `(QWidget, QPushButton)` | Bottom bar with primary action button |
| `section` | `(text)` | `QLabel` | Uppercase section label |
| `info_lbl` | `()` | `QLabel` | Empty info/status label |
| `primary_btn` | `(text)` | `QPushButton` | Teal primary button |
| `danger_btn` | `(text)` | `QPushButton` | Red danger button |
| `scrolled` | `(widget)` | `QScrollArea` | Wraps widget in frameless scroll area |

#### Compression Pipeline

```python
_compress_pdf(
    src: str,                # source PDF path
    dst: str,                # destination PDF path
    level: str = "recommended",  # "extreme" | "recommended" | "low"
    progress_fn = None       # callback(stage: str, current: int, total: int) → False to cancel
) -> tuple[int, int]         # (before_size, after_size) in bytes
```

**Three-pass strategy** — runs all available passes, keeps the smallest result:

| Pass | Engine | What it Does |
|------|--------|-------------|
| **A** | Ghostscript (if installed) | Full page re-render with image downsampling |
| **B** | PyMuPDF (fitz) | Metadata scrub, font subsetting, image rewrite |
| **C** | pikepdf (if installed) | Structural optimization, object stream compression |

**Compression levels:**

| Level | DPI | Quality | Grayscale |
|-------|-----|---------|-----------|
| `"extreme"` | 72 | 40% | Yes |
| `"recommended"` | 150 | 65% | No |
| `"low"` | 300 | 80% | No |

**Raises:** `CancelledError` if cancelled, `ValueError` if no compression gain, `RuntimeError` if no engines available.

#### Ghostscript Detection

| Function | Signature | Description |
|----------|-----------|-------------|
| `_find_gs` | `() -> str \| None` | Searches PATH, then Windows common install paths for `gswin64c`, `gswin32c`, or `gs` |

#### Exceptions

| Class | Description |
|-------|-------------|
| `CancelledError` | Raised when user cancels a long-running operation |

---

## Internationalization (i18n)

### `app/i18n.py`

The translation system (~150 lines). All user-facing strings go through the `t()` function.

#### Core Function

```python
from app.i18n import t

t("app.name")                          # → "PDFApps"
t("tool.split.desc")                   # → "Split a PDF into multiple files"
t("update.available", version="1.8")   # → format string with kwargs
```

**Fallback chain:** current language → English → raw key string.

#### Functions Reference

| Function | Signature | Description |
|----------|-----------|-------------|
| `t` | `(key: str, **kwargs) -> str` | Returns translated string. Supports `str.format(**kwargs)`. |
| `init` | `()` | Initializes i18n: loads JSON, detects language. Called once at import. |
| `get_language` | `() -> str` | Returns active language code (e.g., `"pt"`) |
| `set_language` | `(lang: str)` | Changes language and saves to config |
| `available_languages` | `() -> list[str]` | Returns list of available language codes |
| `get_recent_files` | `() -> list[str]` | Returns recent file paths from config (max 10) |
| `add_recent_file` | `(path: str)` | Adds path to recent list (deduplicates, max 10) |

#### Internal Functions

| Function | Description |
|----------|-------------|
| `_load_translations()` | Loads `translations.json` into global `_TRANSLATIONS` dict |
| `_detect_system_language()` | Detects OS language via Windows `kernel32.GetUserDefaultUILanguage()` or `locale.getlocale()` |
| `_load_config_language()` | Reads saved language from `~/.pdfapps_config.json` |
| `_save_config_language(lang)` | Writes language to config file |

#### Language Detection Priority

1. Saved preference in `~/.pdfapps_config.json`
2. Windows API: `kernel32.GetUserDefaultUILanguage()` → maps LCID to language code
3. Unix: `locale.getlocale()` → extracts language prefix
4. Fallback order: PT → ES → FR → DE → ZH → IT → NL → EN

#### `app/translations.json` Structure

```json
{
  "en": {
    "app.name": "PDFApps",
    "app.subtitle": "PDF Editor",
    "app.credits": "pypdf  +  PySide6",
    "workspace.title": "Workspace",
    "nav.split": "Split",
    "tool.split.name": "Split PDF",
    "tool.split.desc": "Split a PDF into multiple files",
    "tool.split.btn": "Split",
    "tool.split.source": "Source PDF",
    "update.available": "Version {version} is available!",
    ...
  },
  "pt": { ... },
  "es": { ... },
  "fr": { ... },
  "de": { ... },
  "zh": { ... },
  "it": { ... },
  "nl": { ... }
}
```

**Supported languages:** EN, PT, ES, FR, DE, ZH, IT, NL (8 total, 300+ keys each)

#### How to Add a Translation Key

1. Add the key to **all 8 language blocks** in `app/translations.json`
2. Use `t("your.new.key")` in code
3. For format strings: `t("your.key", name=value)` — use `{name}` in the JSON value

#### How to Add a New Language

1. Add a new block in `translations.json` with the language code as key
2. Add the code to `_lang_labels` dict in `app/window.py`
3. Add installer/uninstaller translations in `installer.py` (`_INSTALLER_STRINGS`)
4. Add website translations in `docs/index.html` (the `const T = {...}` block)
5. Update the LCID mapping in `_detect_system_language()` if needed

---

## Viewer System

The viewer is split into two layers: a high-level panel (UI) and a low-level canvas (rendering).

### `app/viewer/panel.py` — `PdfViewerPanel(QWidget)`

The viewer UI wrapper. Each open tab in the viewer holds one `PdfViewerPanel`.

#### Layout

```
┌──────────────────────────────────────────────┐
│ Header: filename  │  ‹  ›  │  −  %  +  fit  │  ← hidden when no PDF
├──────────────────────────────────────────────┤
│                                              │
│              _SelectCanvas                   │  ← scroll area
│           (continuous page scroll)           │
│                                              │
├──────────────────────────────────────────────┤
│ [🔍 Search input] [▲] [▼] [✕]  n/m results  │  ← hidden by default
├──────────────────────────────────────────────┤
│ Selection status: "Drag to select and copy"  │
└──────────────────────────────────────────────┘
```

#### Methods

**Loading & State:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `load` | `(path: str)` | Loads a PDF. Handles password-protected files (shows dialog). Updates header. |
| `current_path` | `() -> str` | Returns path of currently loaded PDF |

**Search (Ctrl+F):**

| Method | Description |
|--------|-------------|
| `_toggle_search()` | Shows/hides the search bar |
| `_close_search()` | Closes search bar, clears highlights |
| `_on_search_text_changed(text)` | Triggers search as user types |
| `_do_search(query)` | Searches all pages for text, builds highlight list |
| `_search_next()` | Moves to next match |
| `_search_prev()` | Moves to previous match |
| `_update_search_highlight()` | Updates highlight colors and scrolls to current match |

**Navigation:**

| Method | Description |
|--------|-------------|
| `_prev_page()` | Scrolls to previous page |
| `_next_page()` | Scrolls to next page |
| `_update_page_label()` | Updates "Page X / Y" display based on scroll position |
| `_zoom_fit()` | Resets zoom to fit width |

**Other:**

| Method | Description |
|--------|-------------|
| `_print_pdf()` | Opens system print dialog and renders all pages |
| `update_theme(dark)` | Updates all icon colors for theme change |
| `_on_text_copied(text)` | Shows "Copied!" status for 4 seconds |
| `eventFilter(obj, event)` | Handles Ctrl+Wheel zoom and viewport resize |

### `app/viewer/canvas.py` — `_SelectCanvas(QWidget)`

The low-level continuous-scroll PDF renderer (~450 lines). This is the most performance-critical component.

#### Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `_PAGE_GAP` | `4` | Pixels between pages in continuous scroll |
| `_BUFFER_PGS` | `2` | Extra pages to pre-render above/below visible area |
| `_MAX_THREADS` | `2` | Maximum concurrent render workers |
| `_NOTE_ICON_SIZE` | `22` | Annotation note icon size in pixels |

#### Architecture

```
_SelectCanvas
├── _entries: list[_PageEntry]        # one per page
│   └── _PageEntry
│       ├── y_off: int                # vertical offset in canvas
│       ├── w, h: int                 # page dimensions at current zoom
│       ├── pixmap: QPixmap | None    # rendered image (None = not yet rendered)
│       ├── words: list | None        # text words for search/selection
│       └── annots: list[(QRect, str)]# PDF annotations
│
├── QThreadPool (max 2 workers)
│   └── _PageJob (QRunnable)          # renders one page in background
│       ├── Opens fitz.Document
│       ├── Renders at zoom × devicePixelRatio
│       ├── Extracts word list
│       └── Emits _RenderSignals.page_ready
│
└── paintEvent()                      # only draws visible entries
```

#### Signals

| Signal | Type | Description |
|--------|------|-------------|
| `zoom_changed` | `Signal(int)` | Current zoom percentage (e.g., 150) |
| `text_copied` | `Signal(str)` | Text copied to clipboard (empty if no text layer) |

#### Key Methods

**Document Management:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `load` | `(doc, page_idx=0, path="", password="")` | Loads fitz.Document, creates page entries, triggers initial render |
| `close_doc` | `()` | Closes document, clears all page entries and pixmaps |
| `page_count` | `() -> int` | Returns total number of pages |

**Navigation & Zoom:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `scroll_to_page` | `(idx: int) -> int` | Returns Y offset for given page index |
| `page_at_y` | `(y: int) -> int` | Returns page index at given Y position |
| `zoom_in` | `()` | Zoom in by 1.25× (max 4.0×) |
| `zoom_out` | `()` | Zoom out by ÷1.25 (min 0.2×) |
| `zoom_reset` | `()` | Reset zoom to fit-width |

**Search:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `set_search_highlights` | `(highlights: list, current: int=-1)` | Sets search result rects to paint. Each item: `(page_idx, QRect)`. |

**Rendering Pipeline (internal):**

| Method | Description |
|--------|-------------|
| `_layout_and_schedule()` | Calculates page dimensions at current zoom, positions entries vertically, loads annotations, schedules visible page renders |
| `_visible_range()` | Returns `(first_page, last_page)` indices currently visible (+ buffer) |
| `_schedule_visible()` | Queues `_PageJob` for each unrendered visible page |
| `_on_page_ready(gen, idx, pixmap, words)` | Callback from worker thread; stores pixmap and words in `_entries[idx]` |
| `_invalidate_and_relayout()` | Clears all pixmaps and re-layouts (e.g., after zoom change) |
| `_load_annotations()` | Reads PDF annotations (comments/notes) from all pages |

**Text Selection (internal):**

| Method | Description |
|--------|-------------|
| `_find_closest_word(pos)` | Returns `(page_idx, word_idx)` for the word nearest to screen position |
| `_compute_selection()` | Builds selection rectangles and extracts text between drag start and end |
| `_clear_selection()` | Resets selection state |

**Paint & Input:**

| Method | Description |
|--------|-------------|
| `paintEvent(_)` | Paints: background → page pixmaps → placeholder text → annotations → search highlights → selection rects |
| `mousePressEvent(e)` | Starts text selection drag |
| `mouseMoveEvent(e)` | Updates selection while dragging |
| `mouseReleaseEvent(e)` | Completes selection, copies text to clipboard |
| `contextMenuEvent(e)` | Shows right-click menu (Copy / Delete annotation) |

#### `_PageJob(QRunnable)` — Background Page Renderer

Runs in `QThreadPool`. Each job:

1. Opens `fitz.Document(path)` independently (thread-safe)
2. Renders page at `zoom × devicePixelRatio` for crisp display
3. Extracts word list via `page.get_text("words")`
4. Emits `page_ready(generation, page_index, pixmap, words)`

The `generation` counter prevents stale results from a previous zoom level being applied.

### `app/viewer/presentation.py` — `PresentationWidget(QWidget)`

A standalone fullscreen widget for slideshow-style PDF viewing. Launched via F5 or the toolbar button.

- Opens as a **top-level window** (`Qt.WindowType.Window`) in fullscreen state
- Renders one page at a time, scaled to fit the screen
- Black background with the page centered
- Cursor hidden for a clean presentation look

**Keyboard Navigation:**

| Key | Action |
|-----|--------|
| `Right`, `Down`, `Space`, `PageDown` | Next page |
| `Left`, `Up`, `Backspace`, `PageUp` | Previous page |
| `Home` | First page |
| `End` | Last page |
| `Escape` | Close presentation |

**Page counter overlay:** Shows `"3 / 15"` at the bottom center, auto-hides after 3 seconds via `QTimer`, re-shown on every page change.

**Methods:**

| Method | Description |
|--------|-------------|
| `__init__(path, password, start_page, total_pages)` | Creates widget, initialises all attributes before `setWindowState` (avoids `resizeEvent` crash) |
| `_render()` | Opens fitz doc, renders current page at screen-fit zoom × DPR, stores pixmap |
| `_update_counter()` | Updates counter label text and position, starts hide timer |
| `paintEvent(_)` | Fills black, draws centered pixmap |
| `keyPressEvent(e)` | Handles all navigation keys |
| `resizeEvent(_)` | Repositions counter and re-renders (guarded by `_ready` flag) |

**Important implementation detail:** All instance attributes (`_counter`, `_hide_timer`, etc.) must be created **before** calling `setWindowState(WindowFullScreen)`, because Qt fires `resizeEvent` immediately during that call.

### Fullscreen Mode (F11)

Fullscreen is handled directly in `MainWindow._toggle_fullscreen()`:

- **Enter:** Hides `_workspace_bar`, `_sidebar`, and status bar; calls `showFullScreen()`
- **Exit:** Restores visibility (respecting `_sidebar_collapsed` state); calls `showMaximized()`
- Bound to F11 via `QShortcut`

---

## Editor System

The editor is split into three files: the tool tab (UI + logic), the canvas (rendering + interaction), and dialogs.

### `app/editor/tab.py` — `TabEditar(QWidget)`

The visual PDF editor tool (~650 lines). Does **not** inherit from `BasePage` — it has its own layout because the editor needs a canvas + control panel side-by-side.

#### Layout

```
┌──────────────────────────────────────────────────────────┐
│ ToolHeader (icon, "Edit PDF", description)               │
├──────────────────────────┬───────────────────────────────┤
│                          │ Control panel (fixed 380px)   │
│ PdfEditCanvas            │ ┌───────────────────────────┐ │
│ (QScrollArea)            │ │ PDF file selector         │ │
│                          │ │ Page navigation (‹ n/m ›) │ │
│ Shows current page       │ │                           │ │
│ with overlays drawn      │ │ Mode buttons:             │ │
│ on top                   │ │  [Redact/Censor]          │ │
│                          │ │  [Add Text]               │ │
│                          │ │  [Add Image]              │ │
│                          │ │  [Highlight]              │ │
│                          │ │  [Note/Comment]           │ │
│                          │ │  [Fill Forms]             │ │
│                          │ │  [Edit Text]              │ │
│                          │ │  [Select]                 │ │
│                          │ │                           │ │
│                          │ │ [Undo] [Redo] [Clear]     │ │
│                          │ └───────────────────────────┘ │
├──────────────────────────┴───────────────────────────────┤
│ ActionBar — "Apply and Save"                             │
└──────────────────────────────────────────────────────────┘
```

#### 8 Editing Modes

| # | Mode | Mouse Action | Creates Overlay | Dialog |
|---|------|-------------|----------------|--------|
| 1 | Redact/Censor | Draw rectangle | `{type: "redact", rect, fill, page}` | — |
| 2 | Add Text | Click point | `{type: "text", point, text, size, color, page}` | `_TextDialog` |
| 3 | Add Image | Draw rectangle | `{type: "image", rect, path, page}` | File picker |
| 4 | Highlight | Draw rectangle | `{type: "highlight", rect, color, page}` | — |
| 5 | Note/Comment | Click point | `{type: "note", point, text, page}` | `_NoteDialog` |
| 6 | Fill Forms | Auto-detect | Form field table | — |
| 7 | Edit Text | Click on text | `{type: "text_edit", bbox, old, new, page}` | `_TextEditDialog` |
| 8 | Select | Text selection | — | — |

#### Overlay System

Edits are stored as a list of dicts in `self._pending`. Each dict contains:
```python
{
    "type": "redact",           # overlay type
    "page": 0,                  # page index
    "rect": fitz.Rect(...),     # bounding rectangle (PDF coordinates)
    "fill": (0, 0, 0),          # fill color (RGB, 0-1 range)
}
```

Overlays are painted by `PdfEditCanvas.paintEvent()` on top of the PDF pixmap. When the user clicks "Apply and Save", all overlays are applied permanently to the PDF via fitz.

#### Methods

**PDF Management:**

| Method | Description |
|--------|-------------|
| `_pick_pdf()` | Opens file picker |
| `_load_pdf(path)` | Loads PDF, loads existing annotations and form fields |
| `_close_pdf()` | Closes PDF and resets all state |
| `auto_load(path)` | Auto-loads PDF if the field is empty (called by MainWindow) |
| `_load_existing_annotations()` | Reads existing PDF text annotations as note overlays |
| `_load_form_fields(path)` | Reads PDF form fields into editable table |

**Editing:**

| Method | Description |
|--------|-------------|
| `_on_mode_btn(btn)` | Handles mode button click, updates cursor and canvas state |
| `_on_rect(pdf_rect)` | Called when user draws a rectangle on canvas |
| `_on_point(pdf_pt)` | Called when user clicks a point on canvas |
| `_add(edit)` | Adds edit dict to `_pending` list, clears redo stack |
| `_undo()` | Removes last edit, pushes to redo stack |
| `_redo()` | Pops from redo stack, pushes to pending |
| `_on_note_deleted(overlay)` | Removes deleted note from pending list |
| `_clear_pending()` | Clears all pending edits and redo stack |
| `_pick_image()` | Opens image file picker (for Add Image mode) |

**Saving:**

| Method | Description |
|--------|-------------|
| `_run()` | Applies all pending edits to PDF via fitz and saves to user-selected path |
| `_apply_forms(out)` | Applies form field changes from the table widget |

**Navigation:**

| Method | Description |
|--------|-------------|
| `_update_nav()` | Updates "Page X / Y" label and button states |
| `_prev_page()` | Goes to previous page |
| `_next_page()` | Goes to next page |

**Theme:**

| Method | Description |
|--------|-------------|
| `update_theme(dark)` | Updates mode button colors and icons for theme |

### `app/editor/canvas.py` — `PdfEditCanvas(QWidget)`

Single-page canvas for the editor. Simpler than the viewer canvas — no threading, no continuous scroll.

#### Signals

| Signal | Type | Description |
|--------|------|-------------|
| `rect_selected` | `Signal(object)` | User finished drawing a rectangle (fitz.Rect in PDF coords) |
| `point_clicked` | `Signal(object)` | User clicked a point (fitz.Point in PDF coords) |
| `note_deleted` | `Signal(dict)` | User deleted a note overlay via context menu |
| `zoom_changed` | `Signal(int)` | Zoom percentage changed |

#### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `load` | `(path: str)` | Opens PDF with fitz, renders first page |
| `set_page` | `(idx: int)` | Switches to page and re-renders |
| `set_overlays` | `(overlays: list)` | Sets overlay list to paint on canvas |
| `set_select_mode` | `(active: bool)` | Toggles text selection cursor |
| `get_span_at` | `(pdf_pt) -> dict\|None` | Returns closest text span to a PDF point |
| `close_doc` | `()` | Fully closes document and resets canvas |
| `release_doc` | `()` | Closes fitz doc to release file lock |
| `zoom_in` / `zoom_out` / `zoom_reset` | `()` | Zoom controls (1.25× steps) |
| `page_count` | `() -> int` | Total pages |
| `_render` | `()` | Renders current page at zoom × DPR |
| `_to_pdf` | `(sx, sy) -> (float, float)` | Converts screen → PDF coordinates |
| `paintEvent` | `(_)` | Paints page pixmap + all overlay types |
| `mouseReleaseEvent` | `(e)` | Emits `rect_selected` or `point_clicked` depending on drag vs click |
| `contextMenuEvent` | `(e)` | Right-click menu to delete note annotations |

### `app/editor/dialogs.py` — Editor Dialogs

| Dialog | Purpose | Key Attributes |
|--------|---------|---------------|
| `_PdfPasswordDialog` | Password input for encrypted PDFs | `.password()` → str |
| `_TextDialog` | New text insertion (text, size, color) | `.edit` (QLineEdit), `.font_size` (QSpinBox), `.color_tuple()` → RGB |
| `_TextEditDialog` | Edit existing text (shows original) | `.new_text()` → str |
| `_NoteDialog` | Note/comment input | `.edit` (QTextEdit) |

---

## Tool System

All tools live in `app/tools/` and inherit from `BasePage`. They follow the same pattern:

```python
from app.base import BasePage
from app.widgets import DropFileEdit
from app.utils import section, info_lbl
from app.i18n import t

class TabMyTool(BasePage):
    def __init__(self, status_fn):
        super().__init__(
            icon="fa5s.icon-name",
            title=t("tool.mytool.name"),
            desc=t("tool.mytool.desc"),
            btn_text=t("tool.mytool.btn"),
            status_fn=status_fn,
        )
        # Add widgets to self._form
        self._src = DropFileEdit(t("tool.mytool.source"))
        self._form.addWidget(self._src)
        # ... options, output selector, etc.

    def _run(self):
        # Called when action button is clicked
        path = self._src.path()
        if not path:
            return
        # Process PDF...
        self._status(t("app.ready"))
```

### Tool Reference

| # | Class | File | Library | Description |
|---|-------|------|---------|-------------|
| 1 | `TabDividir` | `split.py` | pypdf | Split by page ranges. Table widget for defining ranges + output names. |
| 2 | `TabJuntar` | `merge.py` | pypdf | Merge multiple PDFs. Drag-reorder list + move up/down buttons. |
| 3 | `TabRotar` | `rotate.py` | pypdf | Rotate pages. Page range input + angle combo (90°/180°/270°). |
| 4 | `TabExtrair` | `extract.py` | pypdf | Extract page subsets. Page range input. |
| 5 | `TabReordenar` | `reorder.py` | pypdf | Drag-reorder pages. Visual page list with up/down/delete/reset. |
| 6 | `TabComprimir` | `compress.py` | gs/fitz/pikepdf | 3-pass compression. Level combo (Extreme/Recommended/Low). Shows before/after sizes. |
| 7 | `TabEncriptar` | `encrypt.py` | pypdf | Encrypt/decrypt. Mode toggle, owner + user password fields. |
| 8 | `TabMarcaDagua` | `watermark.py` | pypdf | Overlay watermark PDF. Layer position (below/above content). |
| 9 | `TabOCR` | `ocr.py` | pytesseract/fitz | Add text layer to scanned PDFs. Language combo (PT/EN/ES/FR/DE). Progress dialog. |
| 10 | `TabConverter` | `convert.py` | fitz/docx | Export to PNG/JPG/DOCX/TXT. DPI selection for images. Output folder. |
| 11 | `TabEditar` | `editor/tab.py` | fitz | Visual editor (see [Editor System](#editor-system)). Not a BasePage subclass. |
| 12 | `TabImport` | `import_pdf.py` | fitz/PIL | Import TXT/images/Markdown → PDF. Type combo, file list. Batch support. |
| 13 | `TabInfo` | `info.py` | pypdf | Read-only metadata display: path, size, pages, author, title, dates, fonts, encryption. |

### Adding a New Tool

1. Create `app/tools/my_tool.py` with a class inheriting `BasePage`
2. Add translation keys to `app/translations.json` (all 8 languages):
   ```json
   "nav.my_tool": "My Tool",
   "tool.my_tool.name": "My Tool",
   "tool.my_tool.desc": "Description of what it does",
   "tool.my_tool.btn": "Run",
   "tool.my_tool.source": "Source PDF"
   ```
3. Import and register in `app/window.py` → `NAV_ITEMS`:
   ```python
   from app.tools.my_tool import TabMyTool
   # Add to NAV_ITEMS list:
   (t("nav.my_tool"), "fa5s.icon-name", TabMyTool),
   ```
4. The tool automatically appears in the sidebar and integrates with navigation, theme switching, and auto-load.

---

## Auto-Updater

### `app/updater.py`

Checks for updates via the GitHub Releases API and downloads/installs them.

#### Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `check_for_update` | `() -> dict \| None` | Fetches latest release from GitHub API. Returns release dict if remote version > local, else `None`. |
| `_find_asset` | `(release: dict) -> dict \| None` | Finds platform-specific binary: `PDFAppsSetup.exe` (Win), `PDFApps-macOS.zip`, `PDFApps-Linux.tar.gz` |
| `_download` | `(url, dest, signals)` | Downloads file with progress reporting. Emits `signals.progress(0-100)`, `signals.finished(path)`, or `signals.error(msg)`. |
| `_apply_update_windows` | `(downloaded_installer: str)` | Runs installer with `ShellExecuteW(None, "runas", ...)`. Raises `OSError` if return ≤ 32. |
| `_apply_update_unix` | `(downloaded: str)` | Replaces running binary and restarts via `os.execv()`. Creates backup, restores on failure. |

#### Classes

**`_Signals(QObject)`** — cross-thread communication:

| Signal | Type | When |
|--------|------|------|
| `progress` | `Signal(int)` | Download progress 0-100 |
| `finished` | `Signal(str)` | Download completed (path to file) |
| `error` | `Signal(str)` | Download failed (error message) |

**`UpdateDialog(QDialog)`** — download and install UI:

| Method | Description |
|--------|-------------|
| `__init__(release, parent)` | Shows version info, install button, progress bar |
| `_start_download()` | Creates QThread worker, starts download |
| `_on_progress(pct)` | Updates progress bar |
| `_on_finished(path)` | Applies update (platform-specific), shows restart message, quits app |
| `_on_error(msg)` | Shows error in status label |

#### Critical Design Constraint

> The installer must **never** use `uac_admin=True` in its PyInstaller manifest. It must self-elevate via `ShellExecuteW("runas")` at startup. This ensures backward compatibility — old app versions using `subprocess.Popen` can still launch the installer without `WinError 740`.

---

## Installer & Uninstaller

Both use **tkinter** (not PySide6) so they run as lightweight standalone executables.

### `installer.py` (~970 lines)

Cross-platform GUI installer with:

- **8-language support** — auto-detects OS language, same detection as the main app
- **Installation steps:**
  1. Copy `PDFApps.exe` and `PDFAppsUninstall.exe` to chosen folder
  2. Create desktop shortcut (optional)
  3. Create Start Menu / application menu entry (optional)
  4. Register PDF file association in Windows registry (optional)
  5. Download and install Tesseract OCR (optional)
  6. Download and install Ghostscript (optional)

- **Platform-specific behavior:**
  - **Windows:** Registry keys (`HKCU\Software\PDFApps`, ProgID `PDFApps.Document`), shortcuts via shell
  - **macOS:** `.app` bundle creation, Homebrew integration
  - **Linux:** `.desktop` file, `update-desktop-database`

- **Self-elevation:** Calls `ShellExecuteW("runas")` at startup if not already admin (Windows only). The spec has `uac_admin=False`.

### `uninstaller.py` (~230 lines)

- Confirmation dialog → removes installation folder, shortcuts, registry entries
- 8-language support with same OS detection

### PyInstaller Specs

**`installer.spec`** — bundles `PDFApps.exe` + `PDFAppsUninstall.exe` + `icon.ico` as data files. Excludes PySide6/pypdf/qtawesome (not needed). **`uac_admin=False`**.

**`uninstaller.spec`** — bundles `icon.ico`. Excludes PySide6/pypdf/qtawesome.

---

## Build & Release

### Build Order

```bash
# 1. Build main app
python -m PyInstaller --clean --noconfirm pdfapps.spec

# 2. Build uninstaller (must exist before installer)
python -m PyInstaller --clean --noconfirm uninstaller.spec

# 3. Build installer (bundles PDFApps.exe + PDFAppsUninstall.exe from dist/)
python -m PyInstaller --clean --noconfirm installer.spec
```

> **Important:** Always use `venv/Scripts/python.exe -m PyInstaller`, not the `pyinstaller` command directly — it may silently use the wrong Python.

### PyInstaller Data Files

The main app spec (`pdfapps.spec`) must explicitly include:

| Data | Why |
|------|-----|
| `qtawesome/fonts` | Font Awesome icons fail at runtime without bundled fonts |
| `icon.ico` | Window icon |
| `pdfapps.svg` | Sidebar brand logo |
| `app/translations.json` | i18n strings |

### Version Bumping

Before any release, update version in **all three** locations:

| File | Field |
|------|-------|
| `app/constants.py` | `APP_VERSION = "X.Y.Z"` |
| `installer.py` | `APP_VERSION = "X.Y.Z"` |
| `docs/index.html` | `v1.X.Y` in hero section |

### Release Workflow

```bash
# 1. Bump version in all 3 files
# 2. Commit
git add app/constants.py installer.py docs/index.html
git commit -m "chore: bump version to v1.8.0"

# 3. Tag and push — triggers CI
git tag v1.8.0
git push origin main v1.8.0
```

### CI/CD (`.github/workflows/build.yml`)

Triggered on `v*` tag push. Builds on three platforms (matrix strategy):

| Platform | Builds | Release Asset |
|----------|--------|--------------|
| `windows-latest` | `PDFApps.exe` + `PDFAppsSetup.exe` + `PDFAppsUninstall.exe` | `PDFApps.exe`, `PDFAppsSetup.exe` |
| `ubuntu-22.04` | `PDFApps` → `PDFApps-Linux.tar.gz` | `PDFApps-Linux.tar.gz` |
| `macos-latest` | `PDFApps` → `PDFApps-macOS.zip` | `PDFApps-macOS.zip` |

Both `PDFApps.exe` (bare app) and `PDFAppsSetup.exe` (installer) are published. The bare exe is needed for backward compatibility with old updater versions that download `PDFApps.exe`.

---

## Key Data Flows

### PDF Loading (Viewer)

```
User opens PDF (file dialog / drag & drop / CLI argument / recent menu)
  │
  ▼
MainWindow._load_and_track(path)
  ├── If current tab has a document → _add_viewer_tab(path) (new tab)
  └── PdfViewerPanel.load(path)
        ├── If encrypted → show _PdfPasswordDialog
        ├── Open fitz.Document(path, password)
        ├── Update header (filename, page count)
        └── _SelectCanvas.load(doc)
              ├── Create _PageEntry slots (one per page)
              ├── Calculate page layouts at current zoom
              ├── Render first page synchronously
              └── _schedule_visible()
                    ├── Determine viewport + buffer range
                    └── Queue _PageJob for each unrendered page
                          ├── (in thread) fitz renders page → QPixmap
                          ├── (in thread) Extract word list for search
                          └── Emit page_ready signal
                                └── Canvas stores pixmap, calls update()
```

### Tool Execution

```
User selects tool from sidebar
  │
  ▼
MainWindow._on_nav_clicked(item)
  ├── stack.setCurrentIndex(row)     # show tool UI
  ├── stack.setVisible(True)          # show tool stack
  ├── _tab_container.setVisible(False)# hide viewer
  └── _try_auto_load(row)            # load current PDF if tool supports it
        │
        ▼
User fills form → clicks action button
  │
  ▼
BasePage._run() (overridden by tool)
  ├── Validate inputs
  ├── Process PDF (pypdf / fitz / pytesseract / etc.)
  ├── Show progress dialog if needed
  ├── Save output file
  └── Update status bar
```

### Theme Switch

```
User clicks theme button (☀ / 🌙)
  │
  ▼
MainWindow._toggle_theme()
  ├── self._dark_mode = not self._dark_mode
  └── _apply_theme()
        ├── Set QSS globally: STYLE or STYLE_LIGHT
        ├── Update QPalette via _make_palette(dark)
        ├── Recreate sidebar toggle button icons
        ├── Update all sidebar nav icons with new color
        ├── Update all workspace bar button icons
        ├── Call update_theme(dark) on every PdfViewerPanel
        ├── Call update_theme(dark) on TabEditar
        └── Save preference to ~/.pdfapps_config.json
```

### Compression Pipeline

```
TabComprimir._run()
  │
  ▼
_compress_pdf(src, dst, level, progress_fn)
  ├── Pass A: Ghostscript (if installed)
  │     └── Re-render entire PDF with image downsampling
  │         DPI and quality depend on level
  │
  ├── Pass B: PyMuPDF (fitz)
  │     ├── Scrub metadata
  │     ├── Subset fonts
  │     ├── Rewrite images with reduced quality
  │     └── Save with deflate compression
  │
  ├── Pass C: pikepdf (if installed)
  │     └── Structural optimization + object stream compression
  │
  └── Compare all results → keep smallest → copy to dst
      Return (before_size, after_size)
```

### Update Flow (Windows)

```
App startup
  │
  ▼
MainWindow._check_for_updates_async()
  └── QThread → check_for_update()
        ├── GET https://api.github.com/repos/.../releases/latest
        ├── Compare tag_name vs APP_VERSION
        └── If newer → emit _update_ready signal
              │
              ▼
        _notify_update() → show notification dialog
              │
              ▼
User clicks update button → UpdateDialog
  ├── _start_download() → QThread → _download()
  │     ├── Downloads PDFAppsSetup.exe to temp dir
  │     └── Progress bar updates via signals
  │
  └── _on_finished(path)
        ├── _apply_update_windows(path)
        │     └── ShellExecuteW(None, "runas", path) → UAC prompt
        │           └── Installer runs with admin privileges
        ├── Show "restart" message
        └── QApplication.quit()
```

---

## Conventions & Guidelines

### Code Style

- **Commits:** English, conventional commits format (`feat:`, `fix:`, `chore:`, `refactor:`)
- **Language:** Code and comments in English; user-facing strings via `t()` i18n system
- **Imports:** Standard library → PySide6/Qt → third-party → app modules

### Icons & DPI

- Always use `QPushButton` + `setIcon()` + `setIconSize()` — Qt handles DPI scaling automatically
- **Never** use `QLabel` + pixmap with hardcoded `setDevicePixelRatio()`
- Every `qta.icon()` with a color must have a corresponding update in `_apply_theme()` for theme switching
- Store buttons as `self._` instance attributes if they need icon updates later

### Theme Awareness

- Use color constants from `app.constants` — never hardcode hex in `setStyleSheet()`
- After adding any icon button, verify it updates in `_apply_theme()` / `update_theme()`
- Test every UI change in both dark and light mode

### Before a Release

- [ ] Version bumped in all 3 locations (`constants.py`, `installer.py`, `docs/index.html`)
- [ ] All translation keys present in all 8 languages
- [ ] Tested in both dark and light mode
- [ ] Tested tool execution with real PDFs
- [ ] Tested failure paths (invalid input, missing files, cancelled operations)
- [ ] Tested backward compatibility (old updater versions can launch the new installer)
- [ ] Run the app from source: `python pdfapps.py`

---

## License

PDFApps is licensed under the [MIT License](LICENSE). By contributing, you agree that your contributions will be licensed under the same license.
