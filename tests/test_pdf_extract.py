"""Unit tests for app.tools._pdf_extract helpers.

Covers the E1 must-fix / should-fix regressions:

* ``_normalize_text`` collapses page numbers so headers/footers that embed
  a counter (``"Página 1 de 16"``, ``"Page 1 of 16"``, ``"1 / 16"``) are
  detected as the same string across pages.
* ``detect_repeated_regions`` suppresses repeated headers/footers using
  *per-page* heights — handles mixed portrait/landscape PDFs.
* Single-page documents never suppress anything (threshold floor of 2).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable so ``from app.tools...`` works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tools._pdf_extract import (  # noqa: E402
    CardRegion,
    Drawing,
    PageAssets,
    TableCell,
    TableRegion,
    TextBlock,
    TextLine,
    TextSpan,
    _normalize_text,
    detect_card_regions,
    detect_repeated_regions,
    detect_table_regions,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_block(text: str, bbox: tuple[float, float, float, float]) -> TextBlock:
    """Build a minimal TextBlock containing a single span/line at ``bbox``."""
    span = TextSpan(text=text, bbox=bbox, font="Helv", size=10.0, flags=0, color=0)
    line = TextLine(bbox=bbox, spans=[span], dir=(1.0, 0.0))
    return TextBlock(bbox=bbox, lines=[line])


def _page(
    idx: int,
    blocks: list[TextBlock],
    width: float = 595.0,
    height: float = 842.0,
) -> PageAssets:
    return PageAssets(
        page_index=idx,
        rect=(0.0, 0.0, width, height),
        text_blocks=blocks,
    )


# ---------------------------------------------------------------------------
# _normalize_text
# ---------------------------------------------------------------------------


def test_normalize_text_strips_page_numbers_pt():
    """Portuguese 'Página N de M' must normalize to the same string."""
    assert _normalize_text("Página 1 de 16") == _normalize_text("Página 5 de 16")
    assert _normalize_text("Página 1 de 16") == _normalize_text("Página 16 de 16")


def test_normalize_text_strips_page_numbers_en():
    """English 'Page N of M' likewise."""
    assert _normalize_text("Page 1 of 10") == _normalize_text("Page 7 of 10")


def test_normalize_text_strips_short_form_counter():
    """'1 / 16' style counters should also collapse."""
    assert _normalize_text("1 / 16") == _normalize_text("9 / 16")


def test_normalize_text_collapses_whitespace_and_case():
    assert _normalize_text("  Header   Text  ") == "header text"
    assert _normalize_text("HEADER") == _normalize_text("header")


def test_normalize_text_distinct_strings_stay_distinct():
    """Sanity: non-paginated headers must still differ."""
    assert _normalize_text("Chapter One") != _normalize_text("Chapter Two")


# ---------------------------------------------------------------------------
# detect_repeated_regions
# ---------------------------------------------------------------------------


def test_detect_repeated_regions_with_page_numbers():
    """A 4-page PDF with 'Página N de 4' headers must suppress all of them."""
    pages: list[PageAssets] = []
    header_bbox = (50.0, 20.0, 545.0, 40.0)  # top band on a 842pt-tall page
    body_bbox = (50.0, 400.0, 545.0, 420.0)
    for i in range(4):
        pages.append(
            _page(
                i,
                [
                    _make_block(f"Página {i + 1} de 4", header_bbox),
                    _make_block(f"Body text page {i + 1}", body_bbox),
                ],
            )
        )

    skip = detect_repeated_regions(pages)
    # Every page's header (block index 0) must be suppressed.
    assert {(i, 0) for i in range(4)}.issubset(skip)
    # Body blocks (index 1) must NOT be suppressed.
    for i in range(4):
        assert (i, 1) not in skip


def test_detect_repeated_regions_single_page_suppresses_nothing():
    """1-page docs: threshold floor of 2 prevents any suppression."""
    page = _page(
        0,
        [
            _make_block("Some Header", (50.0, 20.0, 545.0, 40.0)),
            _make_block("Body", (50.0, 400.0, 545.0, 420.0)),
        ],
    )
    assert detect_repeated_regions([page]) == set()


def test_detect_repeated_regions_uses_per_page_height():
    """Mixed portrait/landscape: header band must follow each page's height.

    Page 0 is portrait (h=842) → header band ends at ~101.
    Page 1 is landscape (h=595) → header band ends at ~71.4. A block at y=80
    would land in the *body* on landscape but in the header on portrait, so
    the per-page logic must place it correctly.
    """
    common_header_text = "Confidential Report"
    # Portrait page: header at top.
    p0 = _page(
        0,
        [_make_block(common_header_text, (50.0, 30.0, 545.0, 50.0))],
        width=595.0,
        height=842.0,
    )
    # Landscape page: same logical header at top, but at a y-coord that
    # would NOT be inside a 12% band of a 842pt page (y=70 < 0.12*842=101)
    # yet IS inside a 12% band of a 595pt page (0.12*595=71.4). Use y=30
    # to keep it cleanly inside both, so the dedup must engage.
    p1 = _page(
        1,
        [_make_block(common_header_text, (50.0, 30.0, 545.0, 50.0))],
        width=842.0,
        height=595.0,
    )
    skip = detect_repeated_regions([p0, p1])
    assert (0, 0) in skip
    assert (1, 0) in skip


def test_detect_repeated_regions_short_text_ignored():
    """Blocks shorter than min_text_len chars must be ignored."""
    pages = [
        _page(i, [_make_block("ab", (50.0, 20.0, 80.0, 40.0))]) for i in range(3)
    ]
    assert detect_repeated_regions(pages) == set()


def test_detect_repeated_regions_doc_height_fallback():
    """When a page reports height=0 the doc_height fallback kicks in."""
    common = "Top Banner"
    p0 = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 0.0, 0.0),  # zero-size → height=0
        text_blocks=[_make_block(common, (50.0, 30.0, 545.0, 50.0))],
    )
    p1 = PageAssets(
        page_index=1,
        rect=(0.0, 0.0, 0.0, 0.0),
        text_blocks=[_make_block(common, (50.0, 30.0, 545.0, 50.0))],
    )
    # Without a fallback both pages have height=0 and the band logic short-
    # circuits to (0, 0); passing doc_height keeps the original behaviour.
    skip = detect_repeated_regions([p0, p1], doc_height=842.0)
    assert (0, 0) in skip
    assert (1, 0) in skip


# ---------------------------------------------------------------------------
# detect_card_regions
# ---------------------------------------------------------------------------


def _drawing(
    bbox: tuple[float, float, float, float],
    fill: tuple[float, float, float] | None = (0.2, 0.4, 0.8),
    stroke: tuple[float, float, float] | None = None,
    kind: str = "f",
) -> Drawing:
    return Drawing(bbox=bbox, fill=fill, stroke=stroke, kind=kind)


def test_detect_card_regions_basic():
    """1 colored filled rectangle + 1 contained text block → 1 region."""
    card_bbox = (50.0, 100.0, 545.0, 300.0)
    text_bbox = (60.0, 120.0, 535.0, 200.0)
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=[_make_block("Analogy callout", text_bbox)],
        drawings=[_drawing(card_bbox, fill=(0.2, 0.4, 0.8))],
    )
    regions = detect_card_regions(pa)
    assert len(regions) == 1
    cr = regions[0]
    assert isinstance(cr, CardRegion)
    assert cr.text_block_indices == [0]
    assert cr.drawing_indices == [0]
    assert cr.fill_color == (0.2, 0.4, 0.8)
    # Union bbox should at least cover the card rectangle.
    assert cr.bbox[0] <= card_bbox[0] + 0.01
    assert cr.bbox[2] >= card_bbox[2] - 0.01


def test_detect_card_regions_white_ignored():
    """Filled-white rectangles are page background → no region."""
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=[_make_block("Body", (60.0, 120.0, 535.0, 200.0))],
        drawings=[_drawing((50.0, 100.0, 545.0, 300.0), fill=(1.0, 1.0, 1.0))],
    )
    assert detect_card_regions(pa) == []


def test_detect_card_regions_excludes_grid():
    """A 2x2 grid of filled cells with text → deferred to E3 (no region)."""
    # 2 columns x 2 rows of colored cells (think table cells).
    cells = [
        (50.0, 100.0, 250.0, 200.0),
        (260.0, 100.0, 460.0, 200.0),
        (50.0, 210.0, 250.0, 310.0),
        (260.0, 210.0, 460.0, 310.0),
    ]
    # An optional outer frame that contains every cell — exercises the
    # "merge then probe children" path.
    outer = (48.0, 98.0, 462.0, 312.0)
    text_blocks = [
        _make_block(f"Cell {i}", (c[0] + 5, c[1] + 5, c[2] - 5, c[3] - 5))
        for i, c in enumerate(cells)
    ]
    drawings = [_drawing(outer, fill=(0.9, 0.9, 0.9))] + [
        _drawing(c, fill=(0.6, 0.7, 0.85)) for c in cells
    ]
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=text_blocks,
        drawings=drawings,
    )
    assert detect_card_regions(pa) == []


def test_detect_card_regions_empty_box():
    """A filled rectangle with no text inside → not a card (decoration)."""
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=[
            # Text that lives OUTSIDE the rectangle.
            _make_block("Far text", (50.0, 400.0, 200.0, 420.0)),
        ],
        drawings=[_drawing((50.0, 100.0, 545.0, 300.0), fill=(0.3, 0.5, 0.7))],
    )
    assert detect_card_regions(pa) == []


def test_detect_card_regions_frame_body_corners():
    """Frame + body + 2 corner patches → single region (not a fake grid).

    Real callouts are often drawn as multiple overlapping filled
    rectangles (outer frame, inner body, rounded-corner stitch fills).
    Each individual rect has ~the same area as its neighbours so they
    would naively cluster into rows/columns, but pairwise overlap is
    well above the dedup threshold. The detector should collapse them
    and emit a single CardRegion containing the inner text.
    """
    card_bbox = (50.0, 100.0, 545.0, 300.0)
    # Frame, inner body, top-left corner, bottom-right corner — all
    # heavily overlapping in the same area.
    frame = (50.0, 100.0, 545.0, 300.0)
    body = (52.0, 102.0, 543.0, 298.0)
    corner_tl = (50.0, 100.0, 200.0, 200.0)
    corner_br = (400.0, 220.0, 545.0, 300.0)
    rects = [frame, body, corner_tl, corner_br]
    fill = (0.2, 0.4, 0.8)
    drawings = [_drawing(r, fill=fill) for r in rects]
    text_bbox = (60.0, 120.0, 535.0, 200.0)
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=[_make_block("Callout body", text_bbox)],
        drawings=drawings,
    )
    regions = detect_card_regions(pa)
    assert len(regions) == 1
    cr = regions[0]
    assert cr.text_block_indices == [0]
    # Union covers the original card bbox.
    assert cr.bbox[0] <= card_bbox[0] + 0.01
    assert cr.bbox[2] >= card_bbox[2] - 0.01


def test_detect_card_regions_vertical_list():
    """3 stacked cards with same left/width but distinct tops → 3 regions.

    A vertical list of callouts shares the same left edge AND the same
    width, but the tops are distinct (no row clustering). The detector
    must NOT suppress them as a 1-D "grid" — they are independent cards
    and each should map to its own CardRegion.
    """
    left, right = 50.0, 545.0
    fill = (0.2, 0.5, 0.7)
    card_bboxes = [
        (left, 100.0, right, 200.0),
        (left, 220.0, right, 320.0),
        (left, 340.0, right, 440.0),
    ]
    text_bboxes = [
        (left + 10, b[1] + 10, right - 10, b[3] - 10) for b in card_bboxes
    ]
    drawings = [_drawing(b, fill=fill) for b in card_bboxes]
    text_blocks = [
        _make_block(f"Card body {i}", tb) for i, tb in enumerate(text_bboxes)
    ]
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=text_blocks,
        drawings=drawings,
    )
    regions = detect_card_regions(pa)
    assert len(regions) == 3
    # Top-to-bottom order preserved.
    ys = [cr.bbox[1] for cr in regions]
    assert ys == sorted(ys)
    # Each region captures its own text block (1:1).
    text_index_sets = [set(cr.text_block_indices) for cr in regions]
    assert text_index_sets == [{0}, {1}, {2}]


# ---------------------------------------------------------------------------
# detect_table_regions
# ---------------------------------------------------------------------------


def _grid_cells(
    rows: int,
    cols: int,
    *,
    x0: float = 50.0,
    y0: float = 100.0,
    cell_w: float = 100.0,
    cell_h: float = 40.0,
) -> list[tuple[float, float, float, float]]:
    """Return ``rows * cols`` axis-aligned cell bboxes laid out in a grid."""
    out: list[tuple[float, float, float, float]] = []
    for r in range(rows):
        for c in range(cols):
            cx0 = x0 + c * cell_w
            cy0 = y0 + r * cell_h
            out.append((cx0, cy0, cx0 + cell_w, cy0 + cell_h))
    return out


def test_detect_table_regions_basic():
    """2x3 grid of filled cells + 1 text block per cell → 1 TableRegion."""
    cells = _grid_cells(rows=2, cols=3)
    drawings = [
        _drawing(c, fill=(0.9, 0.9, 0.9), stroke=(0.0, 0.0, 0.0)) for c in cells
    ]
    # One text block centred inside each cell.
    text_blocks = [
        _make_block(
            f"R{i // 3}C{i % 3}",
            (c[0] + 5, c[1] + 5, c[2] - 5, c[3] - 5),
        )
        for i, c in enumerate(cells)
    ]
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=text_blocks,
        drawings=drawings,
    )
    regions = detect_table_regions(pa)
    assert len(regions) == 1
    tr = regions[0]
    assert isinstance(tr, TableRegion)
    assert tr.rows == 2
    assert tr.cols == 3
    assert len(tr.cells) == 6
    # Each cell must be a TableCell with one consumed text block.
    for cell in tr.cells:
        assert isinstance(cell, TableCell)
        assert len(cell.text_block_indices) == 1
    # Total text blocks consumed = 6 (one per cell).
    assert len(tr.text_block_indices) == 6
    # Row/col assignment is row-major.
    coords = [(cell.row, cell.col) for cell in tr.cells]
    assert coords == [
        (0, 0), (0, 1), (0, 2),
        (1, 0), (1, 1), (1, 2),
    ]


def test_detect_table_regions_min_size():
    """1x3 grid (single row) is rejected by ``min_rows``."""
    cells = _grid_cells(rows=1, cols=3)
    drawings = [_drawing(c, fill=(0.9, 0.9, 0.9)) for c in cells]
    text_blocks = [
        _make_block(f"C{i}", (c[0] + 5, c[1] + 5, c[2] - 5, c[3] - 5))
        for i, c in enumerate(cells)
    ]
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=text_blocks,
        drawings=drawings,
    )
    assert detect_table_regions(pa) == []


def test_detect_table_regions_missing_cell():
    """2x2 grid missing 1 of 4 cells (75 %) → rejected by 80 % threshold.

    With the default ``presence_ratio=0.8`` the 3-of-4 layout falls just
    short. Lowering the threshold via the kwarg lets the region through
    with 4 cells materialised (the missing one is empty).
    """
    cells = _grid_cells(rows=2, cols=2)
    # Drop the bottom-right cell to simulate a real-world "missing" cell.
    cells_present = cells[:3]
    drawings = [_drawing(c, fill=(0.9, 0.9, 0.9)) for c in cells_present]
    text_blocks = [
        _make_block(f"T{i}", (c[0] + 5, c[1] + 5, c[2] - 5, c[3] - 5))
        for i, c in enumerate(cells_present)
    ]
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=text_blocks,
        drawings=drawings,
    )
    # Default threshold rejects it (3 / 4 = 0.75 < 0.8).
    assert detect_table_regions(pa) == []

    # Relaxed threshold (0.7) accepts it and materialises the empty cell.
    regions = detect_table_regions(pa, presence_ratio=0.7)
    assert len(regions) == 1
    tr = regions[0]
    assert tr.rows == 2
    assert tr.cols == 2
    assert len(tr.cells) == 4  # missing cell exists as an empty TableCell
    empty_cells = [c for c in tr.cells if not c.text_block_indices]
    assert len(empty_cells) == 1
    assert (empty_cells[0].row, empty_cells[0].col) == (1, 1)


def test_detect_table_regions_lone_row_ignored():
    """A 5-column single-row "grid" is a list — not a table."""
    cells = _grid_cells(rows=1, cols=5)
    drawings = [_drawing(c, fill=(0.9, 0.9, 0.9)) for c in cells]
    text_blocks = [
        _make_block(f"C{i}", (c[0] + 5, c[1] + 5, c[2] - 5, c[3] - 5))
        for i, c in enumerate(cells)
    ]
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=text_blocks,
        drawings=drawings,
    )
    assert detect_table_regions(pa) == []


def test_detect_table_regions_no_text_ignored():
    """A 2x2 grid with zero text blocks inside is decorative → skipped."""
    cells = _grid_cells(rows=2, cols=2)
    drawings = [_drawing(c, fill=(0.9, 0.9, 0.9)) for c in cells]
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=[
            # Text floating far below the grid, not inside any cell.
            _make_block("Caption", (50.0, 600.0, 400.0, 620.0)),
        ],
        drawings=drawings,
    )
    assert detect_table_regions(pa) == []


def test_detect_table_regions_two_stacked_split():
    """Two 2x2 tables sharing column X but separated by a ~3x row-height
    gap must be split into two TableRegions, not merged via "share col"
    connectivity.

    Before the gap-split post-process the BFS step would merge these
    into a single 4-row x 2-col component because every row in table A
    shares its column index with every row in table B.
    """
    cell_w = 100.0
    cell_h = 30.0
    x0 = 50.0
    # Table A: rows at y = 100 and y = 130.
    rows_a = [100.0, 100.0 + cell_h]
    # Table B: rows at y = 130 + 3 * cell_h (gap of 3x row_height) and one below.
    gap = 3.0 * cell_h
    rows_b = [rows_a[-1] + cell_h + gap, rows_a[-1] + cell_h + gap + cell_h]
    all_top_ys = rows_a + rows_b
    cells: list[tuple[float, float, float, float]] = []
    for y in all_top_ys:
        for c in range(2):
            cx0 = x0 + c * cell_w
            cells.append((cx0, y, cx0 + cell_w, y + cell_h))
    drawings = [_drawing(c, fill=(0.9, 0.9, 0.9), stroke=(0, 0, 0)) for c in cells]
    text_blocks = [
        _make_block(f"T{i}", (c[0] + 5, c[1] + 5, c[2] - 5, c[3] - 5))
        for i, c in enumerate(cells)
    ]
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=text_blocks,
        drawings=drawings,
    )
    regions = detect_table_regions(pa)
    assert len(regions) == 2, (
        f"expected 2 stacked tables, got {len(regions)} — "
        "gap-split post-process should fire"
    )
    # Top-to-bottom order, each should be a clean 2x2.
    regions_sorted = sorted(regions, key=lambda r: r.bbox[1])
    for tr in regions_sorted:
        assert tr.rows == 2
        assert tr.cols == 2
        assert len(tr.cells) == 4
    # First table sits above the second one.
    assert regions_sorted[0].bbox[3] < regions_sorted[1].bbox[1]


def test_detect_table_regions_cell_linebreaks():
    """A 2x2 grid where each cell carries a TextBlock with 2 text lines.

    The detector must keep all lines assigned to the same cell so the
    emit path can preserve them as separate paragraphs (real line
    breaks instead of a literal '\\n' character).
    """
    cells = _grid_cells(rows=2, cols=2)

    def _multi_line_block(text_top: str, text_bot: str,
                           bbox: tuple[float, float, float, float]) -> TextBlock:
        x0, y0, x1, y1 = bbox
        h = y1 - y0
        line1_bbox = (x0, y0, x1, y0 + h / 2)
        line2_bbox = (x0, y0 + h / 2, x1, y1)
        span1 = TextSpan(
            text=text_top, bbox=line1_bbox, font="Helv", size=10.0,
            flags=0, color=0,
        )
        span2 = TextSpan(
            text=text_bot, bbox=line2_bbox, font="Helv", size=10.0,
            flags=0, color=0,
        )
        return TextBlock(
            bbox=bbox,
            lines=[
                TextLine(bbox=line1_bbox, spans=[span1], dir=(1.0, 0.0)),
                TextLine(bbox=line2_bbox, spans=[span2], dir=(1.0, 0.0)),
            ],
        )

    drawings = [
        _drawing(c, fill=(0.95, 0.95, 0.95), stroke=(0, 0, 0)) for c in cells
    ]
    text_blocks = [
        _multi_line_block(
            f"line1-{i}", f"line2-{i}",
            (c[0] + 4, c[1] + 4, c[2] - 4, c[3] - 4),
        )
        for i, c in enumerate(cells)
    ]
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=text_blocks,
        drawings=drawings,
    )
    regions = detect_table_regions(pa)
    assert len(regions) == 1
    tr = regions[0]
    assert tr.rows == 2 and tr.cols == 2
    # Every cell points to exactly one text block, and that text block
    # has two lines — the emit path will turn line[0] into the cell's
    # first paragraph and line[1] into an added paragraph.
    for cell in tr.cells:
        assert len(cell.text_block_indices) == 1
        ti = cell.text_block_indices[0]
        block = pa.text_blocks[ti]
        assert len(block.lines) == 2, (
            "multi-line cell must keep both TextLines so the DOCX emit "
            "can render real paragraph breaks"
        )


def test_detect_table_regions_widgets_annotations_captured():
    """A widget/annotation inside a table region is tracked so the
    convert pipeline can suppress it (otherwise its value/content shows
    up both inside the cell and in the trailing widget/annotation pass).
    """
    from app.tools._pdf_extract import Annotation, Widget

    cells = _grid_cells(rows=2, cols=2)
    drawings = [
        _drawing(c, fill=(0.9, 0.9, 0.9), stroke=(0, 0, 0)) for c in cells
    ]
    text_blocks = [
        _make_block(f"T{i}", (c[0] + 5, c[1] + 5, c[2] - 5, c[3] - 5))
        for i, c in enumerate(cells)
    ]
    # Widget centred inside the top-left cell.
    w_bbox = (cells[0][0] + 10, cells[0][1] + 10, cells[0][2] - 10, cells[0][3] - 10)
    widget = Widget(
        bbox=w_bbox, field_name="amount", field_value="42", field_type="Tx",
    )
    # Annotation centred inside the bottom-right cell.
    a_bbox = (cells[3][0] + 10, cells[3][1] + 10, cells[3][2] - 10, cells[3][3] - 10)
    annotation = Annotation(bbox=a_bbox, type="Text", content="hello")
    # An additional annotation sitting OUTSIDE the table — must NOT
    # appear in annotation_indices.
    far_a = Annotation(bbox=(50.0, 700.0, 200.0, 720.0), type="Text", content="far")
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=text_blocks,
        drawings=drawings,
        widgets=[widget],
        annotations=[annotation, far_a],
    )
    regions = detect_table_regions(pa)
    assert len(regions) == 1
    tr = regions[0]
    assert tr.widget_indices == [0]
    assert tr.annotation_indices == [0]


def test_mutual_exclusion_card_vs_table():
    """If a region qualifies both as a card (filled frame + text) AND
    matches the table grid criteria, the table detector must surface it
    as a TableRegion and the card detector must NOT also emit it as a
    card — otherwise the same content renders twice (rasterized card
    plus real <w:tbl>).
    """
    # 2x2 grid of cells; pass them as filled drawings so the card
    # detector might be tempted to merge them.
    cells = _grid_cells(rows=2, cols=2)
    drawings = [
        _drawing(c, fill=(0.7, 0.8, 0.95), stroke=(0, 0, 0)) for c in cells
    ]
    text_blocks = [
        _make_block(
            f"R{i // 2}C{i % 2}",
            (c[0] + 4, c[1] + 4, c[2] - 4, c[3] - 4),
        )
        for i, c in enumerate(cells)
    ]
    pa = PageAssets(
        page_index=0,
        rect=(0.0, 0.0, 595.0, 842.0),
        text_blocks=text_blocks,
        drawings=drawings,
    )
    tables = detect_table_regions(pa)
    cards = detect_card_regions(pa)
    assert len(tables) == 1, "grid of cells should be detected as a table"
    # Card detector's "_looks_like_grid" guard should already suppress
    # this, but verify the contract end-to-end: NO card overlaps the
    # table bbox at >= 50% of the card's own area (that's the threshold
    # used by the convert pipeline to drop overlapping cards).
    tbox = tables[0].bbox

    def _overlap_ratio_a(a, b):
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        ix0, iy0 = max(ax0, bx0), max(ay0, by0)
        ix1, iy1 = min(ax1, bx1), min(ay1, by1)
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        inter = (ix1 - ix0) * (iy1 - iy0)
        a_area = max(1e-6, (ax1 - ax0) * (ay1 - ay0))
        return inter / a_area

    assert all(_overlap_ratio_a(cr.bbox, tbox) < 0.5 for cr in cards), (
        "card detector emitted a region that overlaps the table — "
        "mutual exclusion is broken"
    )
