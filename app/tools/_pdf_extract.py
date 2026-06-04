"""Shared PDF page asset extraction helpers.

Provides dataclasses that capture text, images, drawings, widgets and
annotations for a single PDF page, plus a helper that detects repeated
header/footer regions across pages so that converters can suppress them
from the body flow.

Designed to be reused by the layout-aware DOCX/PPTX/HTML conversion
backends. Phase E1 of the convert refactor.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import fitz  # noqa: F401

_log = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")
_DIGITS_RE = re.compile(r"\d+")


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class TextSpan:
    """A single styled run inside a text line."""

    text: str
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    font: str
    size: float
    flags: int  # PyMuPDF span flags (bold=16, italic=2, ...)
    color: int  # sRGB int


@dataclass
class TextLine:
    """A line of text inside a block."""

    bbox: tuple[float, float, float, float]
    spans: list[TextSpan]
    dir: tuple[float, float]  # writing direction; (1.0, 0.0) for horizontal


@dataclass
class TextBlock:
    """A text block (paragraph-ish) from PyMuPDF's rawdict."""

    bbox: tuple[float, float, float, float]
    lines: list[TextLine]


@dataclass
class ImageAsset:
    """A raster image embedded in the page."""

    bbox: tuple[float, float, float, float]
    xref: int
    ext: str
    bytes: bytes
    width: int
    height: int


@dataclass
class Drawing:
    """A vector graphic primitive."""

    bbox: tuple[float, float, float, float]
    fill: tuple[float, float, float] | None  # RGB 0..1
    stroke: tuple[float, float, float] | None
    kind: str  # 'f' filled, 's' stroke, 'fs', ...


@dataclass
class Widget:
    """A form field on the page."""

    bbox: tuple[float, float, float, float]
    field_name: str
    field_value: str
    field_type: str


@dataclass
class Annotation:
    """A PDF annotation (sticky note, FreeText, highlight, ...)."""

    bbox: tuple[float, float, float, float]
    type: str
    content: str


@dataclass
class PageAssets:
    """Container with every asset extracted from a single PDF page."""

    page_index: int
    rect: tuple[float, float, float, float]
    text_blocks: list[TextBlock] = field(default_factory=list)
    images: list[ImageAsset] = field(default_factory=list)
    drawings: list[Drawing] = field(default_factory=list)
    widgets: list[Widget] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)

    @property
    def width(self) -> float:
        return float(self.rect[2] - self.rect[0])

    @property
    def height(self) -> float:
        return float(self.rect[3] - self.rect[1])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _span_text(span: dict) -> str:
    """Reconstruct visible text from a rawdict span.

    rawdict spans expose either a flat ``text`` field (rare) or a per-char
    ``chars`` list. We prefer ``chars`` when present so that we get the
    exact glyph stream — including ligatures resolved by PyMuPDF.
    """
    chars = span.get("chars")
    if chars:
        return "".join((c.get("c") or "") for c in chars)
    return span.get("text", "") or ""


def _safe_bbox(value) -> tuple[float, float, float, float]:
    try:
        x0, y0, x1, y1 = value  # rect or 4-tuple
        return float(x0), float(y0), float(x1), float(y1)
    except Exception:
        return (0.0, 0.0, 0.0, 0.0)


def _normalize_text(text: str) -> str:
    """Normalize text for repeated-region detection.

    Collapses whitespace, lowercases and replaces any run of digits with a
    single ``#`` placeholder. The placeholder is critical because headers and
    footers often embed a page counter — e.g. ``"Página 1 de 16"``,
    ``"Page 1 of 16"`` or ``"1 / 16"``. Without the placeholder each page
    would produce a unique normalized string and the frequency-based dedup
    would never reach its threshold.
    """
    t = _WS_RE.sub(" ", (text or "")).strip().lower()
    return _DIGITS_RE.sub("#", t)


def _block_text(block: TextBlock) -> str:
    parts: list[str] = []
    for line in block.lines:
        for span in line.spans:
            parts.append(span.text)
        parts.append(" ")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_page_assets(doc: "fitz.Document", page_idx: int) -> PageAssets:
    """Extract every relevant asset from a single PDF page.

    The returned ``PageAssets`` is intentionally cheap to construct: PyMuPDF
    objects are not retained. Callers can therefore close the document while
    still consuming the assets (except for bytes-backed images, which we copy
    eagerly).
    """
    page = doc[page_idx]
    # ``page.rect`` already follows the page's rotation in modern PyMuPDF,
    # but ``page.bound()`` is the documented "effective rectangle" helper
    # and is robust across versions / mediabox vs cropbox differences. We
    # use it so PageAssets.width / .height are always the post-rotation
    # values that match what text/image bboxes are expressed in.
    try:
        eff_rect = page.bound()
    except Exception:
        eff_rect = page.rect
    pa = PageAssets(page_index=page_idx, rect=_safe_bbox(eff_rect))

    # -- Text blocks via rawdict ------------------------------------------------
    try:
        raw = page.get_text("rawdict")
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("rawdict failed on page %d: %s", page_idx, exc)
        raw = {"blocks": []}

    for b in raw.get("blocks", []):
        if b.get("type", 0) != 0:
            continue
        block_lines: list[TextLine] = []
        for ln in b.get("lines", []):
            spans: list[TextSpan] = []
            for s in ln.get("spans", []):
                text = _span_text(s)
                if not text:
                    continue
                spans.append(
                    TextSpan(
                        text=text,
                        bbox=_safe_bbox(s.get("bbox", (0, 0, 0, 0))),
                        font=s.get("font", "") or "",
                        size=float(s.get("size", 0.0) or 0.0),
                        flags=int(s.get("flags", 0) or 0),
                        color=int(s.get("color", 0) or 0),
                    )
                )
            if not spans:
                continue
            block_lines.append(
                TextLine(
                    bbox=_safe_bbox(ln.get("bbox", (0, 0, 0, 0))),
                    spans=spans,
                    dir=tuple(ln.get("dir", (1.0, 0.0))),  # type: ignore[arg-type]
                )
            )
        if not block_lines:
            continue
        pa.text_blocks.append(
            TextBlock(bbox=_safe_bbox(b.get("bbox", (0, 0, 0, 0))), lines=block_lines)
        )

    # -- Images via get_images(full=True) --------------------------------------
    try:
        img_list = page.get_images(full=True) or []
    except Exception as exc:
        _log.warning("get_images failed on page %d: %s", page_idx, exc)
        img_list = []

    for img_info in img_list:
        try:
            xref = int(img_info[0])
            try:
                rects = page.get_image_rects(xref) or []
            except Exception:
                rects = []
            if not rects:
                continue
            extracted = doc.extract_image(xref)
            if not extracted:
                continue
            for r in rects:
                pa.images.append(
                    ImageAsset(
                        bbox=_safe_bbox(r),
                        xref=xref,
                        ext=extracted.get("ext", "png"),
                        bytes=extracted.get("image", b""),
                        width=int(extracted.get("width", 0) or 0),
                        height=int(extracted.get("height", 0) or 0),
                    )
                )
        except Exception as exc:  # pragma: no cover - defensive
            _log.debug("image extract failed on page %d: %s", page_idx, exc)
            continue

    # -- Drawings (vector primitives) ------------------------------------------
    try:
        drawings = page.get_drawings() or []
    except Exception as exc:
        _log.warning("get_drawings failed on page %d: %s", page_idx, exc)
        drawings = []

    for d in drawings:
        r = d.get("rect")
        if r is None:
            continue
        fill = d.get("fill")
        stroke = d.get("color")
        try:
            pa.drawings.append(
                Drawing(
                    bbox=_safe_bbox(r),
                    fill=tuple(fill) if fill else None,  # type: ignore[arg-type]
                    stroke=tuple(stroke) if stroke else None,  # type: ignore[arg-type]
                    kind=str(d.get("type", "") or ""),
                )
            )
        except Exception:
            continue

    # -- Widgets ---------------------------------------------------------------
    try:
        for w in page.widgets() or []:
            try:
                # Distinguish "missing value" from "falsy value" so checkbox
                # widgets with field_value=False (unchecked) and numeric
                # fields with value 0 keep their state instead of collapsing
                # to an empty string via ``False or ""`` / ``0 or ""``.
                _val = getattr(w, "field_value", None)
                field_value = "" if _val is None else str(_val)
                pa.widgets.append(
                    Widget(
                        bbox=_safe_bbox(w.rect),
                        field_name=getattr(w, "field_name", "") or "",
                        field_value=field_value,
                        field_type=getattr(w, "field_type_string", "") or "",
                    )
                )
            except Exception:
                continue
    except Exception as exc:
        _log.debug("widgets iteration failed on page %d: %s", page_idx, exc)

    # -- Annotations -----------------------------------------------------------
    try:
        for a in page.annots() or []:
            try:
                info = a.info or {}
                a_type = a.type
                if isinstance(a_type, (tuple, list)) and len(a_type) >= 2:
                    type_str = str(a_type[1])
                else:
                    type_str = str(a_type)
                pa.annotations.append(
                    Annotation(
                        bbox=_safe_bbox(a.rect),
                        type=type_str,
                        content=(info.get("content", "") or "")
                        or (info.get("title", "") or ""),
                    )
                )
            except Exception:
                continue
    except Exception as exc:
        _log.debug("annots iteration failed on page %d: %s", page_idx, exc)

    return pa


def detect_repeated_regions(
    pages: list[PageAssets],
    doc_height: float = 0.0,
    *,
    margin_ratio: float = 0.12,
    freq_ratio: float = 0.5,
    min_text_len: int = 3,
) -> set[tuple[int, int]]:
    """Detect repeated header/footer blocks across pages.

    The header/footer band of each page is derived from *that page's own*
    height — so mixed portrait/landscape and rotated PDFs are handled
    correctly. ``doc_height`` is kept for backwards compatibility and is
    only used as a fallback when an individual :class:`PageAssets` reports
    a zero / unknown height.

    Args:
        pages: list of :class:`PageAssets`, one per PDF page.
        doc_height: optional fallback page height (used only when a page's
            own ``height`` is zero/unknown). Defaults to ``0.0``.
        margin_ratio: top/bottom band size as a fraction of page height.
            Defaults to 12 %.
        freq_ratio: a block is considered repeated when its normalized text
            appears (in the header or footer band) on at least this fraction
            of pages. Defaults to 50 %.
        min_text_len: ignore blocks whose normalized text is shorter than
            this many characters.

    Returns:
        Set of ``(page_idx, block_idx)`` tuples that should be suppressed
        from the body flow.
    """
    if not pages:
        return set()

    n_pages = len(pages)
    threshold = max(2, int(round(freq_ratio * n_pages)))

    header_counter: Counter[str] = Counter()
    footer_counter: Counter[str] = Counter()
    classification: dict[tuple[int, int], tuple[str, str]] = {}

    for pa in pages:
        height = pa.height or doc_height or 1.0
        header_limit = height * margin_ratio
        footer_limit = height * (1.0 - margin_ratio)

        # Track unique normalized text per page+band so a single page with
        # two identical headers doesn't inflate the counter.
        seen_header: set[str] = set()
        seen_footer: set[str] = set()

        for bi, block in enumerate(pa.text_blocks):
            text_norm = _normalize_text(_block_text(block))
            if len(text_norm) < min_text_len:
                continue
            x0, y0, x1, y1 = block.bbox
            cy = (y0 + y1) / 2.0
            if cy <= header_limit:
                classification[(pa.page_index, bi)] = ("header", text_norm)
                if text_norm not in seen_header:
                    header_counter[text_norm] += 1
                    seen_header.add(text_norm)
            elif cy >= footer_limit:
                classification[(pa.page_index, bi)] = ("footer", text_norm)
                if text_norm not in seen_footer:
                    footer_counter[text_norm] += 1
                    seen_footer.add(text_norm)

    repeated_header = {t for t, c in header_counter.items() if c >= threshold}
    repeated_footer = {t for t, c in footer_counter.items() if c >= threshold}

    suppressed: set[tuple[int, int]] = set()
    for key, (band, text_norm) in classification.items():
        if band == "header" and text_norm in repeated_header:
            suppressed.add(key)
        elif band == "footer" and text_norm in repeated_footer:
            suppressed.add(key)
    return suppressed


__all__ = [
    "Annotation",
    "Drawing",
    "ImageAsset",
    "PageAssets",
    "TextBlock",
    "TextLine",
    "TextSpan",
    "Widget",
    "detect_repeated_regions",
    "extract_page_assets",
]
