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
    QScrollArea, QFrame, QFileDialog, QApplication,
)
import qtawesome as qta

from app.i18n import t
from app.constants import (
    ACCENT, DESKTOP,
    BG_BASE, BG_CARD, BG_INPUT,
    BORDER, TEXT_PRI, TEXT_SEC,
    SUCCESS_DARK, SUCCESS_LIGHT,
    _LA, _LB, _LC, _LI, _LN, _LO, _LP,
)


def resource_path(rel):
    """Returns the correct path both in dev and in PyInstaller exe."""
    base = getattr(sys, '_MEIPASS',
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


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
        if "-" in part:
            a, b = part.split("-", 1)
            a_int, b_int = int(a), int(b)
            if b_int - a_int + 1 > _MAX_PAGES:
                raise ValueError(f"Range too large: {a}-{b} (max {_MAX_PAGES})")
            pages.extend(range(a_int - 1, b_int))
        else:
            pages.append(int(part) - 1)
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


def pick_pdfs(parent: QWidget) -> list:
    paths, _ = QFileDialog.getOpenFileNames(
        parent, t("btn.select_pdfs"), DESKTOP, t("file_filter.pdf"))
    return paths


def pick_folder(parent: QWidget) -> str:
    return QFileDialog.getExistingDirectory(parent, t("btn.select_folder"))


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


# ── Compression helper ────────────────────────────────────────────────────────

class CancelledError(Exception):
    """Raised when the user cancels a long-running operation."""

# Compression presets — DPI + JPEG quality + grayscale flag
_COMPRESS_LEVELS = {
    "extreme":     {"dpi": 72,  "quality": 40, "grayscale": True},
    "recommended": {"dpi": 150, "quality": 65, "grayscale": False},
    "low":         {"dpi": 300, "quality": 80, "grayscale": False},
}


_GS_CACHE: tuple[bool, str | None] = (False, None)  # (resolved, path)


def _find_gs():
    """Find Ghostscript executable. Cached at module level — the lookup
    runs `glob.glob` over `C:\\Program Files\\gs\\...` on Windows, which
    stutters on slow disks and was being repeated on every compress run
    plus once per `_on_done` callback."""
    global _GS_CACHE
    if _GS_CACHE[0]:
        return _GS_CACHE[1]
    import shutil as _sh, platform as _pl
    names = (["gswin64c", "gswin32c", "gs"]
             if _pl.system() == "Windows" else ["gs"])
    for n in names:
        p = _sh.which(n)
        if p and os.path.isfile(p):
            _GS_CACHE = (True, os.path.abspath(p))
            return _GS_CACHE[1]
    # Windows: check common install paths
    if _pl.system() == "Windows":
        import glob
        for pattern in [r"C:\Program Files\gs\gs*\bin\gswin64c.exe",
                        r"C:\Program Files\gs\gs*\bin\gswin32c.exe",
                        r"C:\Program Files (x86)\gs\gs*\bin\gswin32c.exe"]:
            matches = sorted(glob.glob(pattern), reverse=True)
            for p in matches:
                if os.path.isfile(p):
                    _GS_CACHE = (True, os.path.abspath(p))
                    return _GS_CACHE[1]
    _GS_CACHE = (True, None)
    return None


def _compress_pdf(src: str, dst: str, level: str = "recommended",
                  progress_fn=None) -> tuple:
    """
    3-pass compression pipeline (keeps the smallest result):

      Pass A — Ghostscript (if installed)
        · Full PDF re-render with image downsampling + JPEG recompression
        · Grayscale conversion on extreme level
        · Best overall compression — same engine used by iLovePDF / SmallPDF

      Pass B — PyMuPDF (fitz)
        · scrub()  →  remove metadata, thumbnails, attached files
        · subset_fonts()  →  keep only used glyphs
        · rewrite_images()  →  DPI downsampling + JPEG re-encode
        · save() with garbage=4 + deflate + use_objstms

      Pass C — pikepdf (if installed)
        · recompress_flate  →  re-encode all Flate streams at optimal level
        · object_stream_mode=generate  →  group small objects for compression
        · Best structural optimization

    Falls back gracefully if Ghostscript or pikepdf are not available.
    Raises ValueError if no pass reduced the file.
    """
    import tempfile, shutil, subprocess, time

    cfg     = _COMPRESS_LEVELS.get(level, _COMPRESS_LEVELS["recommended"])
    dpi     = cfg["dpi"]
    quality = cfg["quality"]
    gray    = cfg["grayscale"]
    before  = os.path.getsize(src)
    temps: list = []

    def _prog(stage, cur=0, tot=0):
        if progress_fn and progress_fn(stage, cur, tot) is False:
            # Loop var is `_p`, not `t` — the module-level `t` from
            # app.i18n is shadowed inside this function otherwise, and
            # any future translated string here would silently call a
            # str path. Best-effort cleanup; the outer try/except at
            # the bottom retries any survivors after each pass's
            # finally has had a chance to release file handles
            # (Windows can't unlink a tempfile while pikepdf/fitz
            # still has it open).
            for _p in temps:
                try: os.unlink(_p)
                except Exception: pass
            raise CancelledError()

    # ── Pass A : Ghostscript — full re-render ────────────────────────────
    _prog("passA")
    gs = _find_gs()
    p = None
    if gs:
        try:
            presets = {
                "extreme":     "/screen",
                "recommended": "/ebook",
                "low":         "/printer",
            }
            fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
            cmd = [
                gs, "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                f"-dPDFSETTINGS={presets[level]}",
                "-dNOPAUSE", "-dQUIET", "-dBATCH",
                "-dDownsampleColorImages=true",
                "-dDownsampleGrayImages=true",
                "-dDownsampleMonoImages=true",
                f"-dColorImageResolution={dpi}",
                f"-dGrayImageResolution={dpi}",
                f"-dMonoImageResolution={max(dpi, 150)}",
                "-dColorImageDownsampleThreshold=1.0",
                "-dGrayImageDownsampleThreshold=1.0",
                "-dColorImageDownsampleType=/Bicubic",
                "-dGrayImageDownsampleType=/Bicubic",
            ]
            if gray:
                cmd += ["-sColorConversionStrategy=Gray",
                        "-dProcessColorModel=/DeviceGray",
                        "-dOverrideICC"]
            cmd += [f"-sOutputFile={p}", src]
            # Spawn gs as a polled subprocess so the cancel button works
            # mid-render. subprocess.run(timeout=120) blocks the worker
            # thread for the whole timeout window, leaving Cancel dead
            # for up to two minutes on big PDFs.
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            deadline = time.monotonic() + 120
            cancelled = False
            try:
                while True:
                    if proc.poll() is not None:
                        break
                    if progress_fn and progress_fn("passA", 0, 0) is False:
                        cancelled = True
                        break
                    if time.monotonic() > deadline:
                        break
                    time.sleep(0.2)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try: proc.wait(timeout=2)
                        except subprocess.TimeoutExpired: pass
            if cancelled:
                try: os.unlink(p)
                except Exception: pass
                raise CancelledError()
            if proc.returncode == 0 and os.path.isfile(p) and os.path.getsize(p) > 0:
                temps.append(p)
            else:
                try: os.unlink(p)
                except Exception: pass
        except CancelledError:
            raise
        except Exception:
            if p:
                try: os.unlink(p)
                except Exception: pass

    # ── Pass B : PyMuPDF — scrub + rewrite_images ────────────────────────
    _prog("passB_setup")
    doc = None
    p = None
    try:
        import fitz
        doc = fitz.open(src)

        # 1. Remove dead weight
        try:
            doc.scrub(metadata=True, xml_metadata=True,
                      thumbnails=True, attached_files=True)
        except Exception:
            pass

        # Cancel checkpoint between scrub (slow on heavy XMP /
        # attachments) and subset_fonts (also slow on font-heavy PDFs).
        _prog("passB_setup")

        # 2. Font subsetting
        try:
            doc.subset_fonts()
        except Exception:
            pass

        # 3. Rewrite all images (replaces the old manual loop)
        _prog("passB_images", 0, 1)
        try:
            doc.rewrite_images(
                dpi_threshold=dpi + 10,
                dpi_target=dpi,
                quality=quality,
                lossy=True,
                lossless=True,
                bitonal=True,
                color=True,
                gray=True,
                set_to_gray=gray,
            )
        except Exception:
            pass
        _prog("passB_images", 1, 1)

        # 4. Save with all compression flags
        _prog("passB_save")
        fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
        save_kw = dict(garbage=4, deflate=True, deflate_fonts=True, clean=True)
        try:
            doc.save(p, **save_kw, use_objstms=True)
        except TypeError:
            doc.save(p, **save_kw)
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            temps.append(p)
            p = None  # ownership transferred to temps
    except CancelledError:
        # Re-raise so do_work cancels cleanly. The bare `except
        # Exception:` below would otherwise swallow it and the pipeline
        # would silently continue into Pass C.
        raise
    except Exception:
        pass
    finally:
        if doc is not None:
            try: doc.close()
            except Exception: pass
        if p:
            try: os.unlink(p)
            except Exception: pass

    # ── Pass C : pikepdf — structural optimization ───────────────────────
    _prog("passC")
    pdf = None
    p = None
    try:
        import pikepdf
        # Optimize the best result so far (or the original)
        best_so_far = min(temps, key=lambda f: os.path.getsize(f)) if temps else src
        pdf = pikepdf.open(best_so_far)
        fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
        # Cancel checkpoint between open and save — pdf.save is the
        # slow part (linearize + recompress_flate). Without this, a
        # cancel during the parse window would still pay the full save
        # cost before honouring the request.
        _prog("passC")
        pdf.save(p,
                 object_stream_mode=pikepdf.ObjectStreamMode.generate,
                 compress_streams=True,
                 recompress_flate=True,
                 linearize=True)
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            temps.append(p)
            p = None  # ownership transferred to temps
    except CancelledError:
        # Close pdf eagerly so any tempfile pikepdf was holding open
        # (Pass A/B's output passed in as `best_so_far`) can be
        # unlinked. Then retry the temps cleanup that _prog attempted
        # but Windows refused while the handle was live.
        if pdf is not None:
            try: pdf.close()
            except Exception: pass
            pdf = None
        for _p in temps:
            try: os.unlink(_p)
            except Exception: pass
        raise
    except Exception:
        pass
    finally:
        if pdf is not None:
            with contextlib.suppress(Exception):
                pdf.close()
        if p:
            with contextlib.suppress(Exception):
                os.unlink(p)

    if not temps:
        raise RuntimeError("Install pypdf and/or PyMuPDF:\n"
                           "  pip install pypdf pymupdf pillow")

    # ── Choose the best result ──────────────────────────────────────────
    best      = min(temps, key=lambda p: os.path.getsize(p))
    best_size = os.path.getsize(best)

    for _p in temps:
        if _p != best:
            try: os.unlink(_p)
            except Exception: pass

    if best_size >= before:
        with contextlib.suppress(Exception):
            os.unlink(best)
        raise ValueError(f"No gain: {before/1024:.0f} KB → {best_size/1024:.0f} KB")

    # Atomic write: rename within the same volume, else copy to a temp
    # file next to dst and atomic-rename. shutil.move falls back to a
    # plain copy + unlink across volumes (best lives in %TEMP%, dst
    # usually on the user's disk) — a crash mid-copy would leave dst
    # truncated and overwrite a previous good output.
    dst_dir = os.path.dirname(dst) or "."
    try:
        os.replace(best, dst)
    except OSError:
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=dst_dir)
        os.close(fd)
        try:
            shutil.copyfile(best, tmp)
            os.replace(tmp, dst)
        except Exception:
            with contextlib.suppress(Exception):
                os.unlink(tmp)
            raise
        with contextlib.suppress(Exception):
            os.unlink(best)
    return before, best_size


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
