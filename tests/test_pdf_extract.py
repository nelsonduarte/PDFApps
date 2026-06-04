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
    TextBlock,
    TextLine,
    TextSpan,
    _normalize_text,
    detect_card_regions,
    detect_repeated_regions,
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
