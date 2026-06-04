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


@dataclass
class CardRegion:
    """A rasterizable callout / card region detected on a page.

    Union of one or more filled drawings that contain text blocks. Phase
    E2 of the convert refactor renders these as inline PNG images so the
    DOCX preserves the visual look of colored callouts that are awkward
    to recreate via Word styling.
    """

    bbox: tuple[float, float, float, float]
    text_block_indices: list[int]
    drawing_indices: list[int]
    fill_color: tuple[float, float, float] | None


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


def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = bbox
    w = max(0.0, x1 - x0)
    h = max(0.0, y1 - y0)
    return w * h


def _bbox_contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    tol: float = 2.0,
) -> bool:
    """Return True when ``inner`` fits inside ``outer`` (with ``tol`` slack)."""
    ox0, oy0, ox1, oy1 = outer
    ix0, iy0, ix1, iy1 = inner
    return (
        ix0 >= ox0 - tol
        and iy0 >= oy0 - tol
        and ix1 <= ox1 + tol
        and iy1 <= oy1 + tol
    )


def _bbox_overlap_ratio(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """Overlap area as a fraction of the smaller of the two bboxes."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    smaller = min(_bbox_area(a), _bbox_area(b))
    if smaller <= 0.0:
        return 0.0
    return inter / smaller


def _bbox_union(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (
        min(a[0], b[0]),
        min(a[1], b[1]),
        max(a[2], b[2]),
        max(a[3], b[3]),
    )


def _looks_like_grid(
    bboxes: list[tuple[float, float, float, float]],
    *,
    align_tol: float = 2.0,
    overlap_dedup_ratio: float = 0.6,
) -> bool:
    """Cheap "is this a grid of cells?" heuristic.

    A grid has at least 3 *distinct* rectangles whose left edges line up
    in >=2 columns AND whose top edges line up in >=2 rows.

    Real-world callout cards are often rendered as many *overlapping*
    fill rectangles with the same colour (frame + body + rounded-corner
    stitches) which would otherwise spuriously match the grid pattern.
    We therefore deduplicate overlapping rectangles before counting
    columns/rows — the surviving set approximates the true cell layout.
    """
    if len(bboxes) < 3:
        return False

    # Deduplicate: collapse heavily overlapping rectangles. We iterate
    # in ascending-area order so smaller rects survive — that way a true
    # grid of cells beats an outer wrapper frame, and a card's frame +
    # inner body + corner patches collapse onto a single canonical rect.
    distinct: list[tuple[float, float, float, float]] = []
    for b in sorted(bboxes, key=_bbox_area):
        ovl = any(
            _bbox_overlap_ratio(b, d) >= overlap_dedup_ratio for d in distinct
        )
        if not ovl:
            distinct.append(b)

    if len(distinct) < 3:
        return False

    def _cluster(values: list[float]) -> int:
        if not values:
            return 0
        s = sorted(values)
        clusters = 1
        ref = s[0]
        for v in s[1:]:
            if abs(v - ref) > align_tol:
                clusters += 1
                ref = v
        return clusters

    lefts = [b[0] for b in distinct]
    tops = [b[1] for b in distinct]
    col_clusters = _cluster(lefts)
    row_clusters = _cluster(tops)
    # Multi-column AND multi-row pattern → grid/table.
    return col_clusters >= 2 and row_clusters >= 2


def detect_card_regions(
    page_assets: PageAssets,
    *,
    min_drawing_area: float = 800.0,
    white_threshold: float = 0.97,
    merge_overlap_ratio: float = 0.6,
) -> list["CardRegion"]:
    """Detect colored callout / card regions on a page.

    A "card" is a filled vector drawing whose fill is non-white and whose
    bbox encloses at least one text block. Overlapping or adjacent cards
    (e.g. a colored frame + an inner body rectangle) are merged into a
    single region.

    Regions that look like tabular grids (>=3 filled rectangles aligned
    in columns AND rows) are intentionally excluded — those are
    deferred to Phase E3.

    Args:
        page_assets: assets for a single page.
        min_drawing_area: ignore filled drawings whose bbox is smaller
            than this many square points (filters icons / glyph fills).
        white_threshold: a drawing whose RGB components are all >= this
            value is treated as page background and ignored.
        merge_overlap_ratio: two card candidates are merged when their
            overlap (as a fraction of the smaller bbox) reaches this
            ratio.

    Returns:
        Ordered (top-to-bottom) list of :class:`CardRegion`. Empty when
        the page has no qualifying cards.
    """
    drawings = page_assets.drawings
    if not drawings:
        return []

    # Step 1: candidate filled drawings (significant area, non-white).
    candidates: list[tuple[int, Drawing]] = []
    for di, d in enumerate(drawings):
        if d.fill is None:
            continue
        if _bbox_area(d.bbox) < min_drawing_area:
            continue
        try:
            r, g, b = d.fill[0], d.fill[1], d.fill[2]
        except (TypeError, IndexError):
            continue
        if min(r, g, b) >= white_threshold:
            continue  # essentially white / transparent
        candidates.append((di, d))

    if not candidates:
        return []

    # Step 2: for each candidate, collect contained text-block indices.
    text_blocks = page_assets.text_blocks
    per_candidate_text: list[list[int]] = []
    for _, d in candidates:
        contained: list[int] = []
        for ti, tb in enumerate(text_blocks):
            if _bbox_area(tb.bbox) <= 0:
                continue
            if _bbox_contains(d.bbox, tb.bbox):
                contained.append(ti)
        per_candidate_text.append(contained)

    # Step 3: keep only candidates with >=1 text block inside (drop
    # decorative dividers).
    kept: list[tuple[int, Drawing, list[int]]] = []
    for (di, d), texts in zip(candidates, per_candidate_text):
        if texts:
            kept.append((di, d, texts))
    if not kept:
        return []

    # Step 4: drop candidates that participate in a tabular grid. A
    # candidate is "in a grid" when there are at least 2 other kept
    # candidates whose left-edge AND top-edge cluster with it (i.e. the
    # candidate has at least one sibling in the same column AND at
    # least one sibling in the same row). This catches per-cell card
    # detections on tables (each cell is its own candidate but together
    # they form a grid) without needing a single outer frame.
    if len(kept) >= 3:
        align_tol = 2.0
        lefts = [d.bbox[0] for _, d, _ in kept]
        tops = [d.bbox[1] for _, d, _ in kept]

        def _same(a: float, b: float) -> bool:
            return abs(a - b) <= align_tol

        in_grid_idx: set[int] = set()
        for i, (_, d, _) in enumerate(kept):
            li, ti = lefts[i], tops[i]
            has_row_sibling = any(
                j != i and _same(tops[j], ti) and not _same(lefts[j], li)
                for j in range(len(kept))
            )
            has_col_sibling = any(
                j != i and _same(lefts[j], li) and not _same(tops[j], ti)
                for j in range(len(kept))
            )
            if has_row_sibling and has_col_sibling:
                in_grid_idx.add(i)
        if in_grid_idx:
            kept = [k for i, k in enumerate(kept) if i not in in_grid_idx]
            if not kept:
                return []

    # Step 5: merge overlapping / contiguous cards into one region.
    # Each group: dict with bbox, drawing_indices, text_block_indices,
    # fill_color (taken from the first/largest drawing).
    groups: list[dict] = []
    for di, d, texts in kept:
        merged = False
        for g in groups:
            if _bbox_overlap_ratio(g["bbox"], d.bbox) >= merge_overlap_ratio:
                g["bbox"] = _bbox_union(g["bbox"], d.bbox)
                g["drawing_indices"].append(di)
                for ti in texts:
                    if ti not in g["text_block_indices"]:
                        g["text_block_indices"].append(ti)
                merged = True
                break
        if not merged:
            groups.append(
                {
                    "bbox": d.bbox,
                    "drawing_indices": [di],
                    "text_block_indices": list(texts),
                    "fill_color": (
                        float(d.fill[0]),
                        float(d.fill[1]),
                        float(d.fill[2]),
                    )
                    if d.fill
                    else None,
                }
            )

    # Step 6: discard groups that themselves look like tabular grids of
    # cells (e.g. a card-builder rendered a table as a single composite
    # group of sub-rects). We probe by counting filled-drawing children
    # whose bbox is contained inside the union bbox of the group — if
    # those children form a 2+ row x 2+ column matrix the region is
    # almost certainly a table.
    final_groups: list[dict] = []
    for g in groups:
        children: list[tuple[float, float, float, float]] = []
        gbb = g["bbox"]
        for di, d in enumerate(drawings):
            if d.fill is None:
                continue
            if _bbox_area(d.bbox) < min_drawing_area:
                continue
            if not _bbox_contains(gbb, d.bbox, tol=2.0):
                continue
            children.append(d.bbox)
        if len(children) >= 3 and _looks_like_grid(children):
            continue  # deferred to Phase E3
        final_groups.append(g)

    # Step 6: sort top-to-bottom and emit CardRegion instances.
    final_groups.sort(key=lambda g: g["bbox"][1])
    out: list[CardRegion] = []
    for g in final_groups:
        out.append(
            CardRegion(
                bbox=tuple(g["bbox"]),  # type: ignore[arg-type]
                text_block_indices=sorted(g["text_block_indices"]),
                drawing_indices=sorted(g["drawing_indices"]),
                fill_color=g["fill_color"],
            )
        )
    return out


__all__ = [
    "Annotation",
    "CardRegion",
    "Drawing",
    "ImageAsset",
    "PageAssets",
    "TextBlock",
    "TextLine",
    "TextSpan",
    "Widget",
    "detect_card_regions",
    "detect_repeated_regions",
    "extract_page_assets",
]
