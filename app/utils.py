"""PDFApps – utility functions and reusable UI factory helpers."""

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QFileDialog,
)
import qtawesome as qta

from app.constants import (
    ACCENT,
    BG_BASE, BG_CARD, BG_INPUT,
    BORDER, TEXT_PRI, TEXT_SEC,
    _LA, _LB, _LC, _LI, _LN, _LP,
)


def resource_path(rel):
    """Returns the correct path both in dev and in PyInstaller exe."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
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
    pages: list = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a) - 1, int(b)))
        else:
            pages.append(int(part) - 1)
    invalid = [p for p in pages if p < 0 or p >= total]
    if invalid:
        raise ValueError(f"Pages out of range: {[p+1 for p in invalid]}  (total: {total})")
    return pages


def pick_pdfs(parent: QWidget) -> list:
    paths, _ = QFileDialog.getOpenFileNames(
        parent, "Select PDFs", "", "PDF (*.pdf);;All (*.*)")
    return paths


def pick_folder(parent: QWidget) -> str:
    return QFileDialog.getExistingDirectory(parent, "Select folder")


# ── UI factory helpers ────────────────────────────────────────────────────────

def ToolHeader(icon_name: str, title: str, desc: str) -> QWidget:
    """Fixed header at the top of each tool."""
    w = QWidget(); w.setObjectName("tool_header")
    h = QHBoxLayout(w); h.setContentsMargins(24, 14, 24, 14); h.setSpacing(16)
    ico = QLabel()
    ico.setPixmap(qta.icon(icon_name, color=ACCENT).pixmap(30, 30))
    ico.setObjectName("th_icon"); ico.setFixedSize(38, 38)
    col = QVBoxLayout(); col.setSpacing(3)
    t = QLabel(title); t.setObjectName("th_title")
    d = QLabel(desc);  d.setObjectName("th_desc")
    col.addWidget(t); col.addWidget(d)
    h.addWidget(ico); h.addLayout(col); h.addStretch()
    return w


def ActionBar(btn_text: str, slot) -> tuple:
    """Bottom bar with primary action button."""
    bar = QWidget(); bar.setObjectName("action_bar")
    h = QHBoxLayout(bar); h.setContentsMargins(20, 12, 20, 12)
    h.addStretch()
    btn = QPushButton(btn_text); btn.setObjectName("btn_primary")
    btn.setMinimumWidth(200); btn.setFixedHeight(42)
    btn.clicked.connect(slot)
    h.addWidget(btn)
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

# Compression presets (equivalent to ilovepdf's 3 levels)
_COMPRESS_LEVELS = {
    "extreme":     {"max_px": 600,  "quality": 45},
    "recommended": {"max_px": 1240, "quality": 70},
    "low":         {"max_px": 9999, "quality": 85},  # 9999 = no resize
}


def _compress_pdf(src: str, dst: str, level: str = "recommended") -> tuple:
    """
    Compression pipeline with 2 independent passes (inspired by ilovepdf):

      Pass A — pypdf
        · compress_content_streams(level=9)  →  max zlib on all streams
        · compress_identical_objects()       →  deduplicate identical objects

      Pass B — fitz (PyMuPDF)
        · scrub()          →  remove metadata, thumbnails, attached files
        · subset_fonts()   →  keep only used glyphs
        · DPI downsampling →  resize images above target DPI
                              (via PIL if available, or direct scale factor)
        · JPEG re-encode   →  re-encode each image with the level's quality
        · save() with use_objstms=True + garbage=4 + deflate

    The smallest result from both passes is saved to dst.
    Raises ValueError if no pass reduced the file.
    Raises RuntimeError if no library is available.
    """
    import tempfile, shutil, io
    from pypdf import PdfReader, PdfWriter

    cfg          = _COMPRESS_LEVELS.get(level, _COMPRESS_LEVELS["recommended"])
    max_px       = cfg["max_px"]
    jpeg_quality = cfg["quality"]
    before       = os.path.getsize(src)
    temps: list = []

    # ── Pass A : pypdf — streams + deduplicate objects ─────────────────────
    try:
        reader = PdfReader(src)
        writer = PdfWriter()
        for page in reader.pages:
            page.compress_content_streams(level=9)
            writer.add_page(page)
        if reader.metadata:
            writer.add_metadata(reader.metadata)
        try:
            writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
        except Exception:
            pass
        fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
        with open(p, "wb") as fh:
            writer.write(fh)
        temps.append(p)
    except Exception:
        pass

    # ── Pass B : fitz — scrub + subset_fonts + DPI + JPEG ─────────────────
    try:
        import fitz

        doc = fitz.open(src)

        # 1. Remove dead weight
        try:
            doc.scrub(metadata=True, xml_metadata=True,
                      thumbnails=True, attached_files=True)
        except Exception:
            pass

        # 2. Font subsetting (keep only used glyphs)
        try:
            doc.subset_fonts()
        except Exception:
            pass

        # 3. Resize + re-encode images
        seen: set = set()
        for pg in doc:
            for img_tuple in pg.get_images(full=True):
                xref  = img_tuple[0]
                smask = img_tuple[8]
                if xref in seen:
                    continue
                seen.add(xref)
                if smask != 0:      # has transparency mask → skip
                    continue
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.width < 32 or pix.height < 32:
                        continue
                    if pix.alpha:
                        pix = fitz.Pixmap(pix, 0)
                    if pix.n == 4:  # CMYK → RGB
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    if pix.n not in (1, 3):
                        continue

                    # Resize if the longest side exceeds max_px
                    longest = max(pix.width, pix.height)
                    scale = min(1.0, max_px / longest) if longest > max_px else 1.0

                    if scale < 0.99:
                        nw = max(1, int(pix.width  * scale))
                        nh = max(1, int(pix.height * scale))
                        try:
                            from PIL import Image as _PILImage
                            mode = "L" if pix.n == 1 else "RGB"
                            img = _PILImage.frombytes(mode, (pix.width, pix.height),
                                                      pix.samples)
                            _lanczos = getattr(
                                getattr(_PILImage, "Resampling", _PILImage),
                                "LANCZOS", 1)
                            img = img.resize((nw, nh), _lanczos)
                            buf = io.BytesIO()
                            img.save(buf, format="JPEG", quality=jpeg_quality,
                                     optimize=True, progressive=True)
                            jpeg = buf.getvalue()
                        except ImportError:
                            # PIL not available — use fitz native shrink
                            factor = max(1, int(1 / scale))
                            pix.shrink(factor)
                            jpeg = pix.tobytes("jpeg", jpg_quality=jpeg_quality)
                    else:
                        jpeg = pix.tobytes("jpeg", jpg_quality=jpeg_quality)

                    doc.replace_image(xref, stream=jpeg)
                except Exception:
                    pass

        # 4. Save with all compression flags
        fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
        save_kw = dict(garbage=4, deflate=True, deflate_fonts=True, clean=True)
        try:
            doc.save(p, **save_kw, use_objstms=True)
        except TypeError:           # older versions without use_objstms
            doc.save(p, **save_kw)
        doc.close()
        temps.append(p)
    except Exception:
        pass

    if not temps:
        raise RuntimeError("Install pypdf and/or PyMuPDF:\n"
                           "  pip install pypdf pymupdf pillow")

    # ── Choose the best result ──────────────────────────────────────────
    best      = min(temps, key=lambda p: os.path.getsize(p))
    best_size = os.path.getsize(best)

    for p in temps:
        if p != best:
            try: os.unlink(p)
            except Exception: pass

    if best_size >= before:
        try: os.unlink(best)
        except Exception: pass
        raise ValueError(f"No gain: {before/1024:.0f} KB → {best_size/1024:.0f} KB")

    shutil.move(best, dst)
    return before, best_size
