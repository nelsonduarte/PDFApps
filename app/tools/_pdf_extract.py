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
import math
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
# Table-detection tunables
# ---------------------------------------------------------------------------
#
# Cluster-population threshold for ``detect_table_regions``: when the
# number of cell candidates on a page is at or below this value, the
# row / column axis clusterer only requires 1 sibling per axis (so
# small synthetic grids of 3x3 or fewer cells are still detected). Once
# the candidate count exceeds the threshold we raise the bar to 2, which
# filters out spurious singleton rows / columns left behind by residual
# strokes and decorations on busy real-world pages.
_TABLE_CLUSTER_THRESHOLD = 8

# Vertical gap multiplier used to split a single BFS-connected component
# into two stacked tables. After the connectivity pass builds a "share
# row OR share col" component, we measure the median row height inside
# that component; any consecutive pair of rows whose Y-gap exceeds
# ``_TABLE_STACK_SPLIT_K`` times that median is treated as a hard
# boundary between two independent tables. k = 2.0 is conservative:
# regular table line-spacing is ~1x row_height and white space between
# unrelated tables is typically 2-3x row_height.
_TABLE_STACK_SPLIT_K = 2.0


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
    # ``fill_color`` is captured at detection time and kept for Phase E3
    # fallback rendering (native Word shading when we move away from
    # rasterization). It is not consumed by the current E2 emit path.
    fill_color: tuple[float, float, float] | None
    widget_indices: list[int] = field(default_factory=list)
    annotation_indices: list[int] = field(default_factory=list)


@dataclass
class TableCell:
    """A single cell of a detected :class:`TableRegion`.

    ``text_block_indices`` references the parent page's ``text_blocks``
    list — same indexing convention used by :class:`CardRegion`.
    """

    bbox: tuple[float, float, float, float]
    row: int
    col: int
    text_block_indices: list[int] = field(default_factory=list)


@dataclass
class TableRegion:
    """A rectangular grid of cells reconstructed as a real Word table.

    Phase E3 of the convert refactor: instead of letting tabular text
    collapse into a paragraph soup, the DOCX writer emits ``<w:tbl>``
    via ``docx.Document.add_table(rows, cols)`` so the original
    structure (rows, columns, borders) survives the conversion.

    Cells are stored row-major (``cells[row * cols + col]``) but each
    cell also carries explicit ``row`` / ``col`` indices for callers
    that need random access.
    """

    bbox: tuple[float, float, float, float]
    rows: int
    cols: int
    cells: list[TableCell]
    text_block_indices: list[int]
    drawing_indices: list[int] = field(default_factory=list)
    has_borders: bool = True
    # Widgets / annotations whose bbox falls inside the table's union
    # bbox. The convert pipeline uses these to avoid emitting a form
    # field's value or a sticky-note's content a second time after the
    # table cell already rendered it — same suppression contract used by
    # :class:`CardRegion`.
    widget_indices: list[int] = field(default_factory=list)
    annotation_indices: list[int] = field(default_factory=list)


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

    # Step 7: sort top-to-bottom and emit CardRegion instances. Widgets
    # and annotations whose bbox is contained in the final card bbox are
    # tracked so callers can suppress them when the card is rasterized
    # (otherwise a form/sticky-note inside a card would render twice).
    final_groups.sort(key=lambda g: g["bbox"][1])
    widgets = page_assets.widgets
    annotations = page_assets.annotations
    out: list[CardRegion] = []
    for g in final_groups:
        gbb = tuple(g["bbox"])  # type: ignore[assignment]
        w_idx: list[int] = []
        for wi, w in enumerate(widgets):
            if _bbox_area(w.bbox) <= 0:
                continue
            if _bbox_contains(gbb, w.bbox):
                w_idx.append(wi)
        a_idx: list[int] = []
        for ai, a in enumerate(annotations):
            if _bbox_area(a.bbox) <= 0:
                continue
            if _bbox_contains(gbb, a.bbox):
                a_idx.append(ai)
        out.append(
            CardRegion(
                bbox=gbb,  # type: ignore[arg-type]
                text_block_indices=sorted(g["text_block_indices"]),
                drawing_indices=sorted(g["drawing_indices"]),
                fill_color=g["fill_color"],
                widget_indices=sorted(w_idx),
                annotation_indices=sorted(a_idx),
            )
        )
    _log.debug(
        "cards page %d: candidates=%d kept=%d final=%d",
        page_assets.page_index,
        len(candidates),
        len(kept),
        len(out),
    )
    return out


def detect_table_regions(
    page_assets: PageAssets,
    *,
    min_cells: int = 4,
    min_rows: int = 2,
    min_cols: int = 2,
    align_tol: float = 3.0,
    min_cell_area: float = 100.0,
    presence_ratio: float = 0.8,
    page_coverage_threshold: float = 0.9,
    cluster_min_population: int | None = None,
) -> list["TableRegion"]:
    """Detect rectangular grids of cells and return them as TableRegion.

    A "table" is a grid of axis-aligned filled or stroked rectangles
    (each rectangle = one cell) such that:

    * left edges cluster into ``>= min_cols`` columns (``align_tol`` px),
    * top edges cluster into ``>= min_rows`` rows,
    * at least ``presence_ratio`` of the ``rows * cols`` cells are
      actually present in the drawings list (missing cells are tolerated
      as empty cells in the result),
    * the region overall encloses at least one text block (purely
      decorative grids are dropped).

    Cells that span the entire page (a page-fill background mistaken for
    a single-row "table") are filtered via ``page_coverage_threshold``.

    The result is a list of :class:`TableRegion`, sorted top-to-bottom,
    each carrying its full grid (with empty cells materialised so
    callers don't need to test for ``None``) and the indices of the
    text blocks consumed by every cell.

    Args:
        page_assets: assets for a single page.
        min_cells: minimum total cell count (rows * cols) — rejects
            tiny accidental matches.
        min_rows: minimum number of distinct top-edge clusters.
        min_cols: minimum number of distinct left-edge clusters.
        align_tol: px tolerance for grouping equal X / Y coordinates.
        min_cell_area: minimum bbox area for a drawing to count as a
            cell candidate (filters strokes-as-glyphs / hairline noise).
        presence_ratio: fraction of (rows * cols) cells that must be
            backed by an actual drawing (rest become empty cells).
        page_coverage_threshold: candidate sets whose union bbox covers
            more than this fraction of the page area are discarded
            (page background / full-page frame).
    """
    drawings = page_assets.drawings
    if not drawings:
        return []

    page_area = max(1.0, page_assets.width * page_assets.height)

    # Step 1: gather cell candidates — filled OR stroked rectangles
    # with non-trivial area. Stroked-only candidates matter because a
    # lot of tables are drawn as line art (no fill).
    # Minimum side length for a real cell — separator strokes / banner
    # underlines are rendered as very thin filled rects (height < 4 px,
    # full row width) and would otherwise win the smallest-first dedup
    # below and crowd out the actual visible cells.
    min_cell_side = 8.0
    raw_cands: list[tuple[int, tuple[float, float, float, float]]] = []
    for di, d in enumerate(drawings):
        if d.fill is None and d.stroke is None:
            continue
        bbox = d.bbox
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w < min_cell_side or h < min_cell_side:
            continue
        if _bbox_area(bbox) < min_cell_area:
            continue
        raw_cands.append((di, bbox))

    # Slide-builder PDFs render each "visible" cell as a stack of
    # overlapping fill rectangles (background body + top stripe +
    # rounded-corner stitches). Each rect has a slightly different
    # (x0, y0), which explodes the column/row clusters and breaks the
    # grid detection. Deduplicate first: pick a single canonical
    # rectangle per visually overlapping group. We iterate
    # *largest-first within each cluster* but only after dropping
    # outliers that are much larger than the typical candidate (page
    # backgrounds, banner frames). The size-band filter uses the
    # median candidate area as the typical size and keeps candidates
    # within [0.2, 3.0] * median area, which empirically isolates
    # real cells from both noise dots and frame backgrounds.
    cell_dedup_ratio = 0.6
    areas = sorted(_bbox_area(b) for _, b in raw_cands)
    median_area = areas[len(areas) // 2] if areas else 0.0
    if median_area > 0:
        band_lo = 0.2 * median_area
        band_hi = 3.0 * median_area
        band = [
            (di, bb)
            for di, bb in raw_cands
            if band_lo <= _bbox_area(bb) <= band_hi
        ]
    else:
        band = list(raw_cands)
    cands: list[tuple[int, tuple[float, float, float, float]]] = []
    for di, bbox in sorted(band, key=lambda x: -_bbox_area(x[1])):
        if any(
            _bbox_overlap_ratio(bbox, kept_bb) >= cell_dedup_ratio
            for _, kept_bb in cands
        ):
            continue
        cands.append((di, bbox))

    # Need at least ``ceil(min_cells * presence_ratio)`` candidates to
    # have a chance of meeting the grid criterion. The logical grid
    # size check (rows * cols >= min_cells) is enforced later, after
    # we know the row / column count.
    floor = max(2, math.ceil(min_cells * presence_ratio))
    if len(cands) < floor:
        return []

    # Step 2: cluster by left edge (columns) and top edge (rows).
    # ``_cluster_axis`` keeps only clusters whose population is at
    # least ``min_population`` — real grid columns/rows have multiple
    # cells sharing the same edge; one-off values are decorations or
    # text bbox starts that should not seed a row/column.
    def _cluster_axis(
        values: list[float], *, min_population: int = 2
    ) -> list[float]:
        if not values:
            return []
        s = sorted(values)
        clusters: list[list[float]] = [[s[0]]]
        for v in s[1:]:
            if abs(v - clusters[-1][-1]) <= align_tol:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return [
            sum(c) / len(c) for c in clusters if len(c) >= min_population
        ]

    lefts = [b[0] for _, b in cands]
    tops = [b[1] for _, b in cands]
    # Default cluster-population threshold: scale with candidate count.
    # Small synthetic test grids (≤ ~6 candidates) keep population=1 so
    # missing-cell layouts still detect; real-world busy slide decks
    # bump to population=2 so spurious singleton rows/columns from
    # decorations don't survive.
    if cluster_min_population is None:
        cluster_min_population = (
            2 if len(cands) > _TABLE_CLUSTER_THRESHOLD else 1
        )
    col_x = _cluster_axis(lefts, min_population=cluster_min_population)
    row_y = _cluster_axis(tops, min_population=cluster_min_population)

    if len(col_x) < min_cols or len(row_y) < min_rows:
        return []

    def _bucket(v: float, anchors: list[float]) -> int:
        best, best_dist = -1, float("inf")
        for i, a in enumerate(anchors):
            d = abs(v - a)
            if d < best_dist:
                best, best_dist = i, d
        return best if best_dist <= align_tol else -1

    # Step 3: build a (row, col) -> drawing-index map. Connected
    # cells that share a row/col but live in different connected
    # components are grouped together later, so we keep one map per
    # full grid candidate and refine after.
    grid: dict[tuple[int, int], tuple[int, tuple[float, float, float, float]]] = {}
    for di, bbox in cands:
        col = _bucket(bbox[0], col_x)
        row = _bucket(bbox[1], row_y)
        if col < 0 or row < 0:
            continue
        # Multiple drawings stack on the same cell (fill + stroke). Keep
        # the largest bbox so cell extents match the visible cell.
        key = (row, col)
        prev = grid.get(key)
        if prev is None or _bbox_area(bbox) > _bbox_area(prev[1]):
            grid[key] = (di, bbox)

    if not grid:
        return []

    # Step 4: split into connected components on the (row, col)
    # lattice so two unrelated tables on the same page (one above the
    # other) are reported separately. Connectivity is "share a row OR
    # share a column" rather than strict 4-neighbour — this matters
    # when a table skips one of the page-wide column clusters (e.g.
    # the table sits in cols 0/2/3/4 because column 1 is occupied by
    # a header banner with a different alignment that does not appear
    # in the data table rows). With pure 4-connectivity the table's
    # column 0 would split from columns 2/3/4 even though they
    # clearly belong together.
    occupied = set(grid.keys())
    by_row: dict[int, list[tuple[int, int]]] = {}
    by_col: dict[int, list[tuple[int, int]]] = {}
    for key in occupied:
        by_row.setdefault(key[0], []).append(key)
        by_col.setdefault(key[1], []).append(key)
    visited: set[tuple[int, int]] = set()
    components: list[set[tuple[int, int]]] = []
    for key in occupied:
        if key in visited:
            continue
        comp: set[tuple[int, int]] = set()
        stack = [key]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            comp.add(cur)
            # Connect to every cell in the same row and every cell in
            # the same column. This makes the component definition
            # closure-of-row-or-column-sharing — a clean way to express
            # "this is one table".
            for nb in by_row.get(cur[0], ()):
                if nb not in visited:
                    stack.append(nb)
            for nb in by_col.get(cur[1], ()):
                if nb not in visited:
                    stack.append(nb)
        components.append(comp)

    # Step 4b: gap-split post-process. Two visually distinct tables can
    # share column alignment (e.g. two stacked summaries with the same
    # column headers) and therefore land in the same connected component
    # via the "share a col" edge. Split them by looking at the vertical
    # Y-gap between consecutive rows inside each component: any gap that
    # exceeds ``_TABLE_STACK_SPLIT_K`` * median_row_height is treated as
    # a hard boundary between two separate tables.
    def _split_component_on_y_gaps(
        comp: set[tuple[int, int]],
    ) -> list[set[tuple[int, int]]]:
        comp_rows = sorted({r for r, _ in comp})
        if len(comp_rows) < 2:
            return [comp]
        # Use the present-cell bboxes (grid[(r, c)]) to compute each
        # row's actual Y extent. Falling back to the row_y cluster
        # anchor would lose the row's height, which is what we measure
        # against.
        row_extents: dict[int, tuple[float, float]] = {}
        for (r, c) in comp:
            _, bb = grid[(r, c)]
            top, bottom = bb[1], bb[3]
            cur_ext = row_extents.get(r)
            if cur_ext is None:
                row_extents[r] = (top, bottom)
            else:
                row_extents[r] = (min(cur_ext[0], top), max(cur_ext[1], bottom))
        # Median row height inside this component.
        heights = sorted(
            max(0.0, bot - top) for top, bot in row_extents.values()
        )
        median_h = heights[len(heights) // 2] if heights else 0.0
        if median_h <= 0.0:
            return [comp]
        # Walk rows top-to-bottom and split where the gap (top of next
        # row - bottom of current row) exceeds the threshold.
        threshold = _TABLE_STACK_SPLIT_K * median_h
        groups: list[list[int]] = [[comp_rows[0]]]
        for i in range(1, len(comp_rows)):
            prev_r = comp_rows[i - 1]
            cur_r = comp_rows[i]
            gap = row_extents[cur_r][0] - row_extents[prev_r][1]
            if gap > threshold:
                groups.append([cur_r])
            else:
                groups[-1].append(cur_r)
        if len(groups) <= 1:
            return [comp]
        # Re-partition the component's cells according to the row groups.
        row_to_group: dict[int, int] = {}
        for gi, rows in enumerate(groups):
            for r in rows:
                row_to_group[r] = gi
        parts: list[set[tuple[int, int]]] = [set() for _ in groups]
        for (r, c) in comp:
            parts[row_to_group[r]].add((r, c))
        return parts

    split_components: list[set[tuple[int, int]]] = []
    for comp in components:
        split_components.extend(_split_component_on_y_gaps(comp))
    components = split_components

    regions: list[TableRegion] = []
    for comp in components:
        rows_in = sorted({r for r, _ in comp})
        cols_in = sorted({c for _, c in comp})
        n_rows = len(rows_in)
        n_cols = len(cols_in)
        if n_rows < min_rows or n_cols < min_cols:
            continue
        if n_rows * n_cols < min_cells:
            continue
        present = len(comp)
        if present < presence_ratio * (n_rows * n_cols):
            continue

        # Local row/col indices for this component (0..n-1).
        row_local = {r: i for i, r in enumerate(rows_in)}
        col_local = {c: i for i, c in enumerate(cols_in)}

        # Per-row / per-column anchor coordinates for extrapolating
        # missing cells.
        row_top = {r: row_y[r] for r in rows_in}
        col_left = {c: col_x[c] for c in cols_in}

        # Compute right/bottom anchors from the present cells.
        col_right: dict[int, float] = {}
        row_bottom: dict[int, float] = {}
        for (r, c) in comp:
            _, bb = grid[(r, c)]
            col_right[c] = max(col_right.get(c, bb[2]), bb[2])
            row_bottom[r] = max(row_bottom.get(r, bb[3]), bb[3])
        # Fallback: any column/row lacking an explicit right/bottom
        # gets a width/height equal to the cluster's neighbour gap.
        sorted_cols = sorted(cols_in)
        for i, c in enumerate(sorted_cols):
            if c in col_right:
                continue
            if i + 1 < len(sorted_cols):
                col_right[c] = col_x[sorted_cols[i + 1]] - 1.0
            else:
                col_right[c] = col_x[c] + 50.0
        sorted_rows = sorted(rows_in)
        for i, r in enumerate(sorted_rows):
            if r in row_bottom:
                continue
            if i + 1 < len(sorted_rows):
                row_bottom[r] = row_y[sorted_rows[i + 1]] - 1.0
            else:
                row_bottom[r] = row_y[r] + 20.0

        # Union bbox across all cells (present + extrapolated).
        x0 = min(col_left[c] for c in cols_in)
        y0 = min(row_top[r] for r in rows_in)
        x1 = max(col_right[c] for c in cols_in)
        y1 = max(row_bottom[r] for r in rows_in)
        union_bbox = (x0, y0, x1, y1)

        # Discard if the region covers (almost) the whole page — that's
        # a page-background drawing, not a table.
        if _bbox_area(union_bbox) >= page_coverage_threshold * page_area:
            continue

        # Build cells row-major, materialising empty ones.
        cells: list[TableCell] = []
        drawing_idx_list: list[int] = []
        any_text = False
        consumed_text: list[int] = []
        seen_text: set[int] = set()
        # Precompute cell bboxes so we can pre-assign each text block
        # to whichever cell contains its centroid (handles the common
        # PyMuPDF case where adjacent columns of one table row land in
        # a single text block — strict containment then fails).
        cell_bboxes: dict[tuple[int, int], tuple[float, float, float, float]] = {}
        for r in sorted_rows:
            for c in sorted_cols:
                cbb_present = grid.get((r, c))
                if cbb_present is not None:
                    cell_bboxes[(r, c)] = cbb_present[1]
                else:
                    cell_bboxes[(r, c)] = (
                        col_left[c], row_top[r],
                        col_right[c], row_bottom[r],
                    )
        # Region bbox (already computed as union_bbox) — only text
        # blocks whose centroid sits inside the region are candidates.
        rx0, ry0, rx1, ry1 = union_bbox
        text_assignment: dict[int, tuple[int, int]] = {}
        for ti, tb in enumerate(page_assets.text_blocks):
            if _bbox_area(tb.bbox) <= 0:
                continue
            tx = (tb.bbox[0] + tb.bbox[2]) / 2.0
            ty = (tb.bbox[1] + tb.bbox[3]) / 2.0
            if not (rx0 - 2.0 <= tx <= rx1 + 2.0 and ry0 - 2.0 <= ty <= ry1 + 2.0):
                continue
            # Find the cell whose bbox contains the centroid; fall
            # back to the closest cell (centroid distance) for blocks
            # straddling boundaries.
            best_key = None
            best_dist = float("inf")
            for key, cbb in cell_bboxes.items():
                cx = (cbb[0] + cbb[2]) / 2.0
                cy = (cbb[1] + cbb[3]) / 2.0
                if (cbb[0] - 2.0 <= tx <= cbb[2] + 2.0
                        and cbb[1] - 2.0 <= ty <= cbb[3] + 2.0):
                    best_key = key
                    best_dist = 0.0
                    break
                dist = (cx - tx) ** 2 + (cy - ty) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_key = key
            if best_key is not None:
                text_assignment[ti] = best_key
        for r in sorted_rows:
            for c in sorted_cols:
                bb = cell_bboxes[(r, c)]
                cbb_present = grid.get((r, c))
                if cbb_present is not None:
                    drawing_idx_list.append(cbb_present[0])
                t_in_cell = sorted(
                    ti for ti, key in text_assignment.items() if key == (r, c)
                )
                if t_in_cell:
                    any_text = True
                    consumed_text.extend(t_in_cell)
                cells.append(
                    TableCell(
                        bbox=bb,
                        row=row_local[r],
                        col=col_local[c],
                        text_block_indices=t_in_cell,
                    )
                )

        if not any_text:
            # Decorative grid (no text content) — skip.
            continue

        # Borders: heuristic — if a majority of present cells have a
        # stroke, render as "Table Grid". Otherwise default to True so
        # the table is still visually delimited (safe default).
        stroked = 0
        present_count = 0
        for (r, c) in comp:
            di, _ = grid[(r, c)]
            d = drawings[di]
            present_count += 1
            if d.stroke is not None:
                stroked += 1
        has_borders = present_count == 0 or stroked >= present_count // 2

        # Capture widgets / annotations whose bbox is contained inside
        # the table's union bbox so the convert pipeline can suppress
        # them after the cell text already rendered the same content.
        # Same geometric-containment contract used by ``detect_card_regions``.
        widgets = page_assets.widgets
        annotations = page_assets.annotations
        w_idx: list[int] = []
        for wi, w in enumerate(widgets):
            if _bbox_area(w.bbox) <= 0:
                continue
            if _bbox_contains(union_bbox, w.bbox):
                w_idx.append(wi)
        a_idx: list[int] = []
        for ai, a in enumerate(annotations):
            if _bbox_area(a.bbox) <= 0:
                continue
            if _bbox_contains(union_bbox, a.bbox):
                a_idx.append(ai)

        regions.append(
            TableRegion(
                bbox=union_bbox,
                rows=n_rows,
                cols=n_cols,
                cells=cells,
                text_block_indices=sorted(set(consumed_text)),
                drawing_indices=sorted(set(drawing_idx_list)),
                has_borders=has_borders,
                widget_indices=sorted(w_idx),
                annotation_indices=sorted(a_idx),
            )
        )

    regions.sort(key=lambda tr: tr.bbox[1])
    _log.debug(
        "tables page %d: candidates=%d cols=%d rows=%d → regions=%d",
        page_assets.page_index,
        len(cands),
        len(col_x),
        len(row_y),
        len(regions),
    )
    return regions


__all__ = [
    "Annotation",
    "CardRegion",
    "Drawing",
    "ImageAsset",
    "PageAssets",
    "TableCell",
    "TableRegion",
    "TextBlock",
    "TextLine",
    "TextSpan",
    "Widget",
    "detect_card_regions",
    "detect_repeated_regions",
    "detect_table_regions",
    "extract_page_assets",
]
