"""High-fidelity text-edit reinsertion (issue #147, "Nível A").

These tests exercise the save-path helpers that replace an edited text span.
The old behaviour (regressions these tests would catch):

  * font size was inflated to ``max(size, bbox_height)`` (line-height, not size);
  * bold / italic were dropped (always plain base-14);
  * the family collapsed to helv/tiro/cour;
  * the original span was covered with an OPAQUE WHITE rectangle, leaving a
    white block over non-white backgrounds.

The new pipeline uses a transparent redaction plus ``Page.insert_htmlbox`` with
an ``@font-face`` archive (exact font when embeddable) or a generic family with
Noto glyph fallback, degrading to a base-14 ``insert_text`` on any failure.

Run with ``QT_QPA_PLATFORM=offscreen`` (the helpers are pure, no widgets).
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pymupdf = pytest.importorskip("pymupdf")
fitz = pymupdf

from app.editor.tab import (  # noqa: E402
    _font_core, _font_matches, _text_edit_size, _text_edit_color_hex,
    _text_edit_color_rgb, _base14_fontname, _generic_font_style,
    _reinsert_edited_text,
)

_DEJAVU = "C:/Windows/Fonts/DejaVuSans.ttf"


# ── helpers ──────────────────────────────────────────────────────────────

def _first_span(page):
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                return span
    return None


def _edit_from_span(span, new_text, page_idx=0):
    """Build the edit dict exactly as canvas._commit_inline emits it."""
    bb = span["bbox"]
    return {
        "type": "text_edit", "page": page_idx,
        "bbox": list(bb), "old_text": span.get("text", ""),
        "new_text": new_text,
        "size": max(float(span.get("size") or 0), float(bb[3] - bb[1])),
        "font_size": float(span.get("size") or 0),
        "color": span.get("color", 0),
        "font": span.get("font", ""),
        "flags": int(span.get("flags", 0) or 0),
        "ascender": float(span.get("ascender") or 0),
        "descender": float(span.get("descender") or 0),
        "origin": list(span.get("origin", (bb[0], bb[3]))),
    }


def _page_with_text(text, fontname, size, color=(0, 0, 0), *,
                    width=400, height=200, at=(30, 100), bg=None):
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    if bg is not None:
        page.draw_rect(fitz.Rect(10, 10, width - 10, height - 40),
                       color=bg, fill=bg)
    page.insert_text(at, text, fontsize=size, fontname=fontname, color=color)
    return doc, page


def _edit_roundtrip(doc, page, new_text):
    """Apply the edit, save+reopen through bytes, return the resulting span."""
    span = _first_span(page)
    edit = _edit_from_span(span, new_text)
    embedded = _reinsert_edited_text(fitz, doc, page, edit)
    data = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    reopened = fitz.open("pdf", data)
    result = _first_span(reopened[0])
    reopened.close()
    return edit, embedded, result


# ── font-name matching (unit) ────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("ArialMT", "arial"),
    ("Arial-BoldMT", "arial"),
    ("DejaVuSans", "dejavusans"),
    ("DejaVu Sans Book", "dejavusans"),
    ("Times-Roman", "times"),
    ("ABCDEF+Calibri-Bold", "calibri"),
])
def test_font_core_reduces_style_suffixes(name, expected):
    assert _font_core(name) == expected


@pytest.mark.parametrize("span_font,basefont,name,expect", [
    ("DejaVuSans", "DejaVu Sans Book", "DVS", True),
    ("ArialMT", "Arial Regular", "F0", True),
    ("Arial-BoldMT", "Arial Bold", "F1", True),
    ("Calibri", "Calibri Regular", "F2", True),
    ("ArialMT", "Calibri Regular", "F3", False),
])
def test_font_matches(span_font, basefont, name, expect):
    assert _font_matches(_font_core(span_font), basefont, name) is expect


# ── size / colour parsing (unit) ─────────────────────────────────────────

def test_size_uses_raw_span_size_not_inflated():
    # font_size=10 but the inflated "size" is 18 (bbox height). Must pick 10.
    assert _text_edit_size({"font_size": 10.0, "size": 18.0}) == 10.0


def test_size_floor_when_missing():
    assert _text_edit_size({"font_size": 0, "size": 0}) == 4.0


def test_color_hex_from_srgb_int():
    assert _text_edit_color_hex({"color": 0xB31A1A}) == "#b31a1a"
    assert _text_edit_color_hex({"color": 0}) == "#000000"


def test_color_rgb_from_int():
    r, g, b = _text_edit_color_rgb({"color": 0xFF0000})
    assert (round(r), round(g), round(b)) == (1, 0, 0)


@pytest.mark.parametrize("edit,expected", [
    ({"flags": 0, "font": "Helvetica"}, "helv"),
    ({"flags": 16, "font": "Helvetica-Bold"}, "hebo"),
    ({"flags": 2, "font": "Helvetica-Oblique"}, "heit"),
    ({"flags": 4, "font": "Times-Roman"}, "tiro"),
    ({"flags": 16 | 4, "font": "Times-Bold"}, "tibo"),
    ({"flags": 8, "font": "Courier"}, "cour"),
])
def test_base14_fontname_variants(edit, expected):
    assert _base14_fontname(edit) == expected


# ── discriminative save-path tests ───────────────────────────────────────

def test_size_preserved_not_inflated():
    """A size-12 span must reinsert at ~12pt, not the inflated bbox height."""
    doc, page = _page_with_text("Original", "helv", 12)
    _edit, _embedded, result = _edit_roundtrip(doc, page, "Modified")
    assert result is not None
    assert result["size"] == pytest.approx(12.0, abs=0.6)


def test_color_preserved():
    doc, page = _page_with_text("Original", "helv", 14, color=(0.7, 0.1, 0.1))
    _edit, _embedded, result = _edit_roundtrip(doc, page, "Recoloured")
    r = (result["color"] >> 16) & 0xFF
    g = (result["color"] >> 8) & 0xFF
    b = result["color"] & 0xFF
    assert r > 150 and g < 60 and b < 60


def test_bold_preserved():
    doc, page = _page_with_text("Bold", "hebo", 16)
    _edit, _embedded, result = _edit_roundtrip(doc, page, "StillBold")
    # PyMuPDF bold flag is bit 4 (value 16).
    assert result["flags"] & 16, "bold weight was dropped"


def test_italic_preserved():
    doc, page = _page_with_text("Ital", "tiit", 16)
    _edit, _embedded, result = _edit_roundtrip(doc, page, "StillItalic")
    # italic flag is bit 1 (value 2).
    assert result["flags"] & 2, "italic style was dropped"


def test_baseline_position_near_original():
    doc, page = _page_with_text("Original", "helv", 14)
    span = _first_span(page)
    orig_oy = span["origin"][1]
    _edit, _embedded, result = _edit_roundtrip(doc, page, "Moved")
    # generic-substitute font: baseline within a few points of the original.
    assert abs(result["origin"][1] - orig_oy) < 3.0


def test_transparent_redaction_preserves_background():
    """No opaque white box: a coloured background survives under the edit."""
    bg = (0.85, 0.30, 0.30)
    doc, page = _page_with_text("Original", "helv", 16, color=(1, 1, 1),
                                bg=bg, at=(30, 60))
    span = _first_span(page)
    bbox = fitz.Rect(span["bbox"])
    edit = _edit_from_span(span, "Modified")
    _reinsert_edited_text(fitz, doc, page, edit)
    pm = page.get_pixmap(dpi=150)
    # sample a corner of the old span bbox (background, away from new glyphs)
    px = int((bbox.x0 + 1) / page.rect.width * pm.width)
    py = int((bbox.y0 + 1) / page.rect.height * pm.height)
    r, g, b = pm.pixel(px, py)[:3]
    doc.close()
    # expected background ~ (216, 76, 76); a white box would be (255,255,255)
    assert r > 190 and g < 130 and b < 130, (
        "background not preserved (white-box artifact): got %s" % ((r, g, b),))


def test_no_new_white_fill_drawn():
    """The redaction must not add an opaque white vector fill over the span."""
    doc, page = _page_with_text("Original", "helv", 14, bg=(0.2, 0.6, 0.9))
    span = _first_span(page)
    edit = _edit_from_span(span, "Edited")
    _reinsert_edited_text(fitz, doc, page, edit)
    # No filled path should be white (1,1,1) covering the region.
    white_fills = [
        d for d in page.get_drawings()
        if d.get("fill") is not None
        and tuple(round(c, 3) for c in d["fill"]) == (1.0, 1.0, 1.0)
    ]
    doc.close()
    assert not white_fills, "an opaque white fill was drawn over the edit"


def test_glyph_fallback_no_crash_and_renders():
    """Editing in characters outside the base font uses Noto fallback, no tofu."""
    doc, page = _page_with_text("Hello", "helv", 16)
    _edit, _embedded, result = _edit_roundtrip(doc, page, "\u4e2d\u6587")  # CJK
    assert result is not None
    assert result["text"] == "\u4e2d\u6587"


def test_defensive_fallback_on_htmlbox_failure(monkeypatch):
    """If insert_htmlbox raises, the base-14 insert_text path still writes a
    valid, readable PDF instead of crashing or corrupting the page."""
    doc, page = _page_with_text("Original", "helv", 15)
    span = _first_span(page)
    edit = _edit_from_span(span, "Fallback")

    def _boom(*a, **k):
        raise RuntimeError("forced htmlbox failure")

    monkeypatch.setattr(fitz.Page, "insert_htmlbox", _boom)
    embedded = _reinsert_edited_text(fitz, doc, page, edit)
    assert embedded is False
    data = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    reopened = fitz.open("pdf", data)
    result = _first_span(reopened[0])
    txt = reopened[0].get_text()
    reopened.close()
    assert result is not None
    assert "Fallback" in txt
    assert result["size"] == pytest.approx(15.0, abs=0.6)


def test_empty_new_text_only_redacts():
    """Clearing a span removes it (no reinsertion, no crash)."""
    doc, page = _page_with_text("DeleteMe", "helv", 14)
    span = _first_span(page)
    edit = _edit_from_span(span, "   ")  # whitespace -> treated as empty
    embedded = _reinsert_edited_text(fitz, doc, page, edit)
    txt = page.get_text().strip()
    doc.close()
    assert embedded is False
    assert "DeleteMe" not in txt


@pytest.mark.skipif(not os.path.exists(_DEJAVU),
                    reason="DejaVuSans.ttf not available on this platform")
def test_embedded_font_reused_exactly():
    """A fully embedded (non-subset) font is re-embedded, preserving the exact
    typeface and size — the headline #147 fidelity win."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_font(fontname="DVS", fontfile=_DEJAVU)
    page.insert_text((30, 100), "Original", fontsize=16, fontname="DVS",
                     color=(0.1, 0.2, 0.7))
    _edit, embedded, result = _edit_roundtrip(doc, page, "Modified")
    assert embedded is True, "embedded font was not reused"
    assert "DejaVu" in result["font"], (
        "expected DejaVu family, got %r" % result["font"])
    assert result["size"] == pytest.approx(16.0, abs=0.5)


@pytest.mark.skipif(not os.path.exists(_DEJAVU),
                    reason="DejaVuSans.ttf not available on this platform")
def test_subset_font_skipped_falls_back_to_generic():
    """A subsetted font (ABCDEF+ prefix) is NOT re-embedded; the generic family
    path is used instead (documented limitation)."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_font(fontname="DVS", fontfile=_DEJAVU)
    page.insert_text((30, 100), "Original", fontsize=16, fontname="DVS")
    # Force subsetting: BaseFont gains an "ABCDEF+" prefix.
    doc.subset_fonts()
    data = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    doc = fitz.open("pdf", data)
    page = doc[0]
    basefonts = [f[3] for f in page.get_fonts(full=False)]
    assert any("+" in (bf or "") for bf in basefonts), (
        "test setup failed: font not subsetted (%s)" % basefonts)
    _edit, embedded, result = _edit_roundtrip(doc, page, "Modified")
    assert embedded is False  # subset skipped
    assert result is not None
    assert result["size"] == pytest.approx(16.0, abs=0.6)
