"""PDFApps – utility functions and reusable UI factory helpers."""

import contextlib
import logging
import logging.handlers
import os
import sys

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPalette, QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QFileDialog,
)
import qtawesome as qta

from app.i18n import t
from app.constants import (
    ACCENT, DESKTOP,
    BG_BASE, BG_CARD, BG_INPUT,
    TEXT_PRI,
    SUCCESS_DARK, SUCCESS_LIGHT,
    _LA, _LB, _LC, _LI, _LN, _LO, _LP,
)


def resource_path(rel):
    """Returns the correct path both in dev and in PyInstaller exe."""
    base = getattr(sys, '_MEIPASS',
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


def format_size_localized(value: float, decimals: int = 1) -> str:
    """Format a numeric value using the system locale's decimal separator.

    DE/FR/IT/ES typically use comma; EN/PT use period. Falls back to a plain
    ``f"{value:.{decimals}f}"`` (period) if QLocale is unavailable, e.g. in
    headless test environments where the Qt plugin failed to load.
    """
    try:
        from PySide6.QtCore import QLocale
        return QLocale.system().toString(float(value), 'f', decimals)
    except Exception:
        return f"{value:.{decimals}f}"


def _make_palette(dark: bool) -> QPalette:
    p = QPalette()
    if dark:
        p.setColor(QPalette.ColorRole.Window,          QColor(BG_BASE))
        p.setColor(QPalette.ColorRole.WindowText,      QColor(TEXT_PRI))
        p.setColor(QPalette.ColorRole.Base,            QColor(BG_INPUT))
        p.setColor(QPalette.ColorRole.AlternateBase,   QColor(BG_CARD))
        p.setColor(QPalette.ColorRole.Text,            QColor(TEXT_PRI))
        p.setColor(QPalette.ColorRole.Button,          QColor("#1E2235"))
        p.setColor(QPalette.ColorRole.ButtonText,      QColor(TEXT_PRI))
        p.setColor(QPalette.ColorRole.Highlight,       QColor(ACCENT))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    else:
        p.setColor(QPalette.ColorRole.Window,          QColor(_LB))
        p.setColor(QPalette.ColorRole.WindowText,      QColor(_LP))
        p.setColor(QPalette.ColorRole.Base,            QColor(_LI))
        p.setColor(QPalette.ColorRole.AlternateBase,   QColor(_LN))
        p.setColor(QPalette.ColorRole.Text,            QColor(_LP))
        p.setColor(QPalette.ColorRole.Button,          QColor(_LC))
        p.setColor(QPalette.ColorRole.ButtonText,      QColor(_LP))
        p.setColor(QPalette.ColorRole.Highlight,       QColor(_LA))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    return p


def _paint_bg(widget: QWidget) -> None:
    """Makes QWidget subclasses honour 'background:' in the stylesheet."""
    from PySide6.QtWidgets import QStyleOption, QStyle
    opt = QStyleOption()
    opt.initFrom(widget)
    p = QPainter(widget)
    widget.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, p, widget)


def parse_pages(text: str, total: int) -> list:
    _MAX_PAGES = 100_000
    pages: list = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        # R7 E5 follow-up: accept open-ended ranges so '3-' means
        # 'from page 3 to the end' and '-5' means 'from page 1 to
        # page 5'. Without this, '3-' raised ValueError because
        # int('') failed. Reject '-' alone (no bounds at all);
        # otherwise default the missing side to the document's
        # extreme. Matches the pdftk-style 1- range syntax.
        if "-" in part:
            a, b = part.split("-", 1)
            a = a.strip(); b = b.strip()
            if not a and not b:
                raise ValueError(
                    t("tool.err.bad_page_input", text=part))
            try:
                a_int = int(a) if a else 1
                b_int = int(b) if b else total
            except ValueError as exc:
                raise ValueError(
                    t("tool.err.bad_page_input", text=part)) from exc
        else:
            try:
                a_int = b_int = int(part)
            except ValueError as exc:
                # int() raised "invalid literal for int() with base 10" —
                # re-raise with a translated, user-actionable message so
                # show_error() surfaces something useful instead of the
                # raw Python error.
                raise ValueError(
                    t("tool.err.bad_page_input", text=part)) from exc
        if "-" in part:
            if b_int - a_int + 1 > _MAX_PAGES:
                raise ValueError(
                    f"Range too large: {a_int}-{b_int} (max {_MAX_PAGES})")
            pages.extend(range(a_int - 1, b_int))
        else:
            pages.append(a_int - 1)
        if len(pages) > _MAX_PAGES:
            raise ValueError(f"Too many pages selected (max {_MAX_PAGES})")
    invalid = [p for p in pages if p < 0 or p >= total]
    if invalid:
        # p is the 0-based internal index. Convert to the 1-based number the
        # user actually typed, and be explicit about the valid range so
        # entering 0 doesn't produce a confusing "[0]" message.
        bad = sorted({(p + 1) if p >= 0 else 0 for p in invalid})
        raise ValueError(
            f"Pages out of range: {bad}  (valid: 1-{total})")
    # Dedupe + sort: callers like rotate.py would otherwise rotate the
    # same page twice (compounding angles), extract.py would emit
    # duplicate pages, and watermark.py / page_numbers.py would do
    # double work. Input like "3,1,2,3" now returns [0, 1, 2] instead
    # of [2, 0, 1, 2].
    return sorted(set(pages))


#: Megapixel hard limit applied to user-supplied raster images before
#: they reach QPixmap / PyMuPDF. A 100MP cap rejects gigapixel scans
#: (e.g. a malicious or accidentally-saved 50000x50000 TIFF) that would
#: otherwise allocate multi-GB pixmaps and crash the process, while
#: still admitting every realistic phone-camera / scanner output (the
#: largest current consumer cameras top out around 200MP — at that
#: point the warning is intentional and the user knows to downscale).
_IMAGE_PIXEL_LIMIT = 100_000_000


def check_image_size(path: str) -> tuple[bool, int, int]:
    """Return ``(ok, width, height)`` for the image at ``path``.

    ``ok`` is ``False`` when the image exceeds :data:`_IMAGE_PIXEL_LIMIT`
    (width * height > 100 megapixels). Used by the editor signature
    picker and the PDF import-images path to short-circuit before
    allocating a giant pixmap. On any read error returns ``(True, 0, 0)``
    so callers fall back to their existing failure path (a missing /
    corrupted image is the existing tool's responsibility to surface).
    """
    try:
        from PIL import Image
        with Image.open(path) as img:
            w, h = img.size
    except Exception:
        return True, 0, 0
    return (w * h) <= _IMAGE_PIXEL_LIMIT, w, h


def pick_pdfs(parent: QWidget) -> list:
    paths, _ = QFileDialog.getOpenFileNames(
        parent, t("btn.select_pdfs"), DESKTOP, t("file_filter.pdf"))
    return paths


def pick_folder(parent: QWidget) -> str:
    return QFileDialog.getExistingDirectory(parent, t("btn.select_folder"))


def normalize_password(pwd: str) -> str:
    """Return ``pwd`` normalised to Unicode NFC form (R6 C1 / R11 review C2).

    Passwords typed on macOS frequently land in NFD (decomposed) form,
    while Windows clipboards produce NFC (composed) form. The on-screen
    glyphs are identical but the underlying byte sequences are not, so a
    password that authenticates on one OS may fail on the other.

    Normalising at the WRITE side of the cache (i.e. wherever
    ``self._pdf_password = pwd`` happens) makes the cached value
    deterministic and frees every downstream consumer
    (``editor/tab.py``, ``viewer/panel.py``, ``tools/*``) from having to
    remember to normalise on read. Returns falsy inputs unchanged so the
    helper is safe to apply unconditionally.
    """
    if not pwd:
        return pwd
    try:
        import unicodedata
        return unicodedata.normalize("NFC", pwd)
    except (TypeError, ValueError):
        # str inputs only ever raise on absurd code points; falling
        # back to the raw string is safer than crashing.
        return pwd


def wipe_pdf_password(obj) -> None:
    """Best-effort wipe of the cached PDF password attribute on ``obj``.

    Python ``str`` is immutable, so we cannot scrub the original bytes —
    the interpreter may keep the original buffer alive via interning or
    constant tables. What we *can* do is drop the only reachable
    reference so the password no longer surfaces in the live object
    graph. The ctypes block allocates a zeroed buffer of the same length
    as a defensive hint to memory scanners; it does not touch the
    original PyUnicode storage.

    Centralised here so BasePage, EditorTab and PdfViewerPanel share a
    single implementation (used to be three near-identical copies — the
    review for PR-B flagged the duplication as DRY rot).

    Always assigns ``obj._pdf_password = ""`` afterwards, so callers can
    rely on the attribute being defined for the rest of the object's
    lifecycle.
    """
    try:
        pwd = getattr(obj, "_pdf_password", "")
    except Exception:
        pwd = ""
    if pwd:
        with contextlib.suppress(Exception):
            import ctypes
            buf = ctypes.create_string_buffer(len(pwd.encode("utf-8")))
            ctypes.memset(ctypes.addressof(buf), 0, len(buf))
            del buf
    obj._pdf_password = ""


def prompt_pdf_password(path: str, parent=None) -> tuple[bool, str]:
    """Open the PDF and, if encrypted, prompt the user for a password.

    Returns:
        (True, "")          → PDF is not encrypted, just open normally
        (True, "<pwd>")     → PDF is encrypted and the password authenticated
        (False, "")         → user cancelled the dialog (silent abort)

    Detects encryption with PyMuPDF (handles all PDF flavours). The caller
    opens the file with whatever library (pypdf, fitz) using the returned
    password.

    On any unexpected error during detection the function returns
    `(True, "")` so the caller can still try to open and surface its own
    library-specific error message — i.e. password prompting is best-effort,
    never a hard gate.
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(path)
    except Exception:
        return True, ""
    try:
        if not doc.needs_pass:
            return True, ""
        from app.editor.dialogs import _PdfPasswordDialog
        from PySide6.QtWidgets import QDialog
        wrong = False
        while True:
            dlg = _PdfPasswordDialog(os.path.basename(path), wrong=wrong, parent=parent)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return False, ""
            pwd = dlg.password()
            if doc.authenticate(pwd):
                return True, pwd
            wrong = True
    finally:
        doc.close()


# ── UI factory helpers ────────────────────────────────────────────────────────

def ToolHeader(icon_name: str, title: str, desc: str) -> QWidget:
    """Fixed header at the top of each tool."""
    w = QWidget(); w.setObjectName("tool_header")
    h = QHBoxLayout(w); h.setContentsMargins(24, 14, 24, 14); h.setSpacing(12)
    ico = QPushButton()
    ico.setIcon(qta.icon(icon_name, color=ACCENT))
    ico.setIconSize(QSize(22, 22))
    ico.setFixedSize(36, 36)
    ico.setObjectName("th_icon")
    ico.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    col = QVBoxLayout(); col.setSpacing(3)
    t = QLabel(title); t.setObjectName("th_title")
    t.setWordWrap(True)
    d = QLabel(desc);  d.setObjectName("th_desc")
    d.setWordWrap(True)
    col.addWidget(t); col.addWidget(d)
    h.addWidget(ico, 0); h.addLayout(col, 1)
    w.setMinimumWidth(0)
    return w


def _action_progress_stylesheet(dark: bool) -> str:
    """Theme-aware stylesheet for the ActionBar's thin progress strip."""
    if dark:
        # Track = BG_INPUT (matches surrounding cards); chunk = accent teal.
        return (
            f"QProgressBar {{ background: {BG_INPUT}; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}"
        )
    # Light theme: track = subtle off-white card, chunk = light-mode accent.
    return (
        f"QProgressBar {{ background: {_LO}; border-radius: 3px; }}"
        f"QProgressBar::chunk {{ background: {_LA}; border-radius: 3px; }}"
    )


def ActionBar(btn_text: str, slot) -> tuple:
    """Bottom bar with primary action button and optional progress bar.

    Returns ``(bar_widget, button)`` for backwards compatibility. The
    returned ``bar_widget`` carries an ``update_theme(dark)`` method so
    MainWindow's theme-walker can re-skin the progress strip on dark /
    light toggle (the old version hardcoded slate + emerald, which made
    the strip look out of place in light mode).
    """
    from PySide6.QtWidgets import QProgressBar
    bar = QWidget(); bar.setObjectName("action_bar")
    v = QVBoxLayout(bar); v.setContentsMargins(20, 8, 20, 8); v.setSpacing(6)
    progress = QProgressBar(); progress.setVisible(False)
    progress.setFixedHeight(6); progress.setTextVisible(False)
    progress.setObjectName("action_progress")
    progress.setStyleSheet(_action_progress_stylesheet(is_dark()))
    v.addWidget(progress)
    h = QHBoxLayout(); h.setContentsMargins(0, 0, 0, 0)
    h.addStretch()
    btn = QPushButton(btn_text); btn.setObjectName("btn_primary")
    btn.setMinimumWidth(200); btn.setFixedHeight(42)
    btn.clicked.connect(slot)
    h.addWidget(btn)
    v.addLayout(h)
    bar.progress = progress  # accessible by tools

    def _update_theme(dark: bool) -> None:
        try:
            progress.setStyleSheet(_action_progress_stylesheet(dark))
        except RuntimeError:
            pass  # widget destroyed
    # Attach as a bound attribute so MainWindow.findChildren-style theme
    # walking (or BasePage subclasses that explicitly forward) can call
    # it without a class change.
    bar.update_theme = _update_theme  # type: ignore[attr-defined]
    return bar, btn


def section(text: str) -> QLabel:
    lbl = QLabel(text.upper()); lbl.setObjectName("section_lbl")
    return lbl


def info_lbl() -> QLabel:
    lbl = QLabel(""); lbl.setObjectName("info_lbl")
    return lbl


def primary_btn(text: str) -> QPushButton:
    b = QPushButton(text); b.setObjectName("btn_primary")
    b.setFixedHeight(38); return b


def danger_btn(text: str) -> QPushButton:
    b = QPushButton(text); b.setObjectName("btn_danger"); return b


def scrolled(widget: QWidget) -> QScrollArea:
    sa = QScrollArea(); sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame); sa.setWidget(widget)
    return sa


# ── Shared PDF error types + validity helpers ─────────────────────────────────
# The Ghostscript compression pipeline (``_find_gs`` / ``_win_short_path`` /
# ``_compress_pdf``) lives in ``app.pdf_compress`` (R5 split); the exception
# types and ``_is_valid_pdf`` stay here because they are shared by other
# tools (worker.py, tools/convert.py) and imported back by pdf_compress.

class CancelledError(Exception):
    """Raised when the user cancels a long-running operation."""


class WrongPasswordError(Exception):
    """Raised when an encrypted PDF cannot be unlocked with the supplied
    password (missing or wrong).

    Deliberately NOT a subclass of ``ValueError``: the compress tool
    treats ``ValueError`` from ``_compress_pdf`` as the friendly
    "no size gain" outcome, so a password failure must be a distinct
    type to reach the real error path instead of being reported as
    "no gain". Carries the translated ``tool.err.wrong_password``
    message so callers can surface it directly.
    """


def _is_valid_pdf(path: str) -> bool:
    """Return True if ``path`` is a readable, non-empty PDF with pages.

    Guards against a compression pass silently emitting a zero-page or
    otherwise corrupt file (e.g. saving a still-locked encrypted doc)
    and having it accepted as a successful result. Any parse error or
    a page count of zero is treated as invalid.
    """
    try:
        if not path or not os.path.isfile(path) or os.path.getsize(path) <= 0:
            return False
    except OSError:
        return False
    try:
        import fitz
        doc = fitz.open(path)
        try:
            # A still-encrypted doc reports needs_pass and 0 readable
            # pages; treat that as invalid so it is never accepted.
            if doc.needs_pass:
                return False
            return doc.page_count > 0
        finally:
            doc.close()
    except Exception:
        pass  # fitz probe failed/unavailable — fall through to the pypdf fallback below.
    # fitz unavailable — fall back to pypdf (a guaranteed dependency).
    try:
        from pypdf import PdfReader
        r = PdfReader(path)
        if r.is_encrypted:
            return False
        return len(r.pages) > 0
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Theme helpers — for places that need to pick a color without dependency
# injection from MainWindow._dark_mode. Reads the user's `dark_mode`
# preference from the config file (always fresh, ~1ms cost).
# ─────────────────────────────────────────────────────────────────────────────

def is_dark() -> bool:
    """Return the user's current dark-mode preference.
    Defaults to True (the original ship default) when config is missing
    or corrupted."""
    try:
        import json
        from app.i18n import _CONFIG_PATH
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return bool(json.load(f).get("dark_mode", True))
    except Exception:
        return True


def error_color() -> str:
    """Return the right error/red shade for the current theme. Brighter
    on dark backgrounds, darker on light — so the text stays readable."""
    return "#F87171" if is_dark() else "#DC2626"


def success_color(dark: bool | None = None) -> str:
    """Return the right emerald shade for the current theme: brighter on
    dark backgrounds, deeper on light."""
    if dark is None:
        dark = is_dark()
    return SUCCESS_DARK if dark else SUCCESS_LIGHT


def result_label_style(dark: bool | None = None) -> str:
    """Stylesheet for the green 'result' summary label that compress /
    convert / import tools display after a successful run. Theme-aware
    so the label stays legible after a runtime theme toggle (the old
    hardcoded ``#059669`` was emerald-600, fine on light backgrounds
    but visually loud and slightly off on the dark teal theme)."""
    return (f"font-weight:600; font-size:11pt; color:{success_color(dark)}; "
            "background:transparent; padding:10px 4px;")


# ─────────────────────────────────────────────────────────────────────────────
# Logging + user-friendly error dialogs
# ─────────────────────────────────────────────────────────────────────────────

_logging_initialised = False


def _log_path() -> str:
    """Return the path to the rotating log file (next to the user config)."""
    from app.i18n import _CONFIG_PATH
    return os.path.join(os.path.dirname(_CONFIG_PATH), "pdfapps.log")


def setup_logging() -> None:
    """Configure a rotating file logger at the user-config dir.
    Idempotent — safe to call multiple times."""
    global _logging_initialised
    if _logging_initialised:
        return
    _logging_initialised = True
    try:
        log_path = _log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        ))
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
    except Exception:
        # Never let logging setup crash the app
        pass


def show_error(parent, exc: BaseException) -> None:
    """Show a translated, friendly error dialog with collapsible technical
    details. Logs the full exception (with traceback) to the log file.

    Replaces the historical pattern:
        QMessageBox.critical(self, t("msg.error"), str(e))
    which dumped raw Python traceback / paths onto the user. The new dialog
    shows a localized "something went wrong" message; the technical detail
    is in the collapsed "Show Details" pane, and the full traceback is in
    the log file at `pdfapps.log` next to the config.
    """
    from PySide6.QtWidgets import QMessageBox
    # logging.exception() relies on sys.exc_info() being active, but this
    # helper is typically called from a queued slot on the main thread —
    # by then the originating `except` block has already exited and
    # sys.exc_info() is (None, None, None). Pass the exception instance
    # explicitly via exc_info= so the traceback still lands in the log.
    logging.error(
        "UI error surfaced: %s: %s",
        type(exc).__name__, exc, exc_info=exc,
    )
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(t("msg.error"))
    box.setText(t("msg.unexpected"))
    box.setDetailedText(f"{type(exc).__name__}: {exc}")
    box.exec()
