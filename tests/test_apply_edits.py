"""Headless tests for the pure edit-application dispatcher (R1 refactor).

``app.editor.apply_edits.apply_pending_edits`` is the pure PDF/``fitz`` logic
extracted from ``TabEditar._run``: it applies a list of pending edits to an
already-open ``fitz.Document`` with NO file I/O and NO Qt. These tests exercise
it directly, without any widget, proving the refactor's headline win —
testability. Each edit type is applied to a real in-memory document and the
resulting document (via a save+reopen round-trip through bytes) is asserted.

Run with ``QT_QPA_PLATFORM=offscreen`` (no widgets are instantiated).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pymupdf = pytest.importorskip("pymupdf")
fitz = pymupdf

from app.editor.apply_edits import apply_pending_edits, ApplyResult  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────

def _page_with_text(text, *, fontname="helv", size=14, at=(30, 60),
                    width=400, height=200, color=(0, 0, 0)):
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.insert_text(at, text, fontsize=size, fontname=fontname, color=color)
    return doc, page


def _first_span(page):
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                return span
    return None


def _text_edit(span, new_text, page_idx=0):
    """Build a text_edit dict as canvas._commit_inline emits it."""
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


def _reopen(doc):
    """Save+reopen through bytes so we assert the persisted result, not the
    live in-memory object."""
    data = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return fitz.open("pdf", data)


# ── return type ──────────────────────────────────────────────────────────

def test_returns_apply_result_empty_for_no_edits():
    doc, _page = _page_with_text("Untouched")
    result = apply_pending_edits(doc, [])
    assert isinstance(result, ApplyResult)
    assert result.text_fit_warnings == []
    assert result.embedded_font is False
    assert "Untouched" in doc[0].get_text()
    doc.close()


# ── text_edit: new text in, old text out ─────────────────────────────────

def test_text_edit_reinserts_new_and_removes_old():
    doc, page = _page_with_text("OriginalWord", size=14)
    span = _first_span(page)
    result = apply_pending_edits(doc, [_text_edit(span, "ReplacedWord")])
    assert isinstance(result, ApplyResult)
    reopened = _reopen(doc)
    txt = reopened[0].get_text()
    reopened.close()
    assert "ReplacedWord" in txt          # new text persisted
    assert "OriginalWord" not in txt      # old span removed


# ── redact: removes the covered text ─────────────────────────────────────

def test_redact_removes_covered_text():
    doc, page = _page_with_text("SECRETdata", size=16, at=(30, 60))
    span = _first_span(page)
    rect = fitz.Rect(span["bbox"])
    result = apply_pending_edits(
        doc, [{"type": "redact", "page": 0, "rect": rect, "fill": (1, 1, 1)}])
    assert isinstance(result, ApplyResult)
    reopened = _reopen(doc)
    txt = reopened[0].get_text()
    reopened.close()
    assert "SECRET" not in txt


# ── plain text insert ────────────────────────────────────────────────────

def test_text_insert_adds_new_text():
    doc, _page = _page_with_text("Base")
    edit = {"type": "text", "page": 0, "point": (30, 120),
            "text": "InsertedLine", "size": 12, "color": (0, 0, 0),
            "font": "Helvetica"}
    apply_pending_edits(doc, [edit])
    reopened = _reopen(doc)
    txt = reopened[0].get_text()
    reopened.close()
    assert "InsertedLine" in txt


# ── draw: creates an ink annotation ──────────────────────────────────────

def test_draw_creates_ink_annot():
    doc, page = _page_with_text("Canvas")
    before = len(list(page.annots() or []))
    edit = {"type": "draw", "page": 0,
            "points": [(40, 40), (60, 60), (80, 40)],
            "color": (1, 0, 0), "width": 3}
    apply_pending_edits(doc, [edit])
    annots = list(page.annots() or [])
    count = len(annots)
    last_kind = annots[-1].type[1] if annots else None
    doc.close()
    assert count == before + 1
    assert last_kind == "Ink"


def test_draw_ignored_when_fewer_than_two_points():
    doc, page = _page_with_text("Canvas")
    edit = {"type": "draw", "page": 0, "points": [(40, 40)],
            "color": (1, 0, 0), "width": 3}
    apply_pending_edits(doc, [edit])
    annots = list(page.annots() or [])
    doc.close()
    assert annots == []


# ── note: creates a text annotation ──────────────────────────────────────

def test_note_creates_text_annot():
    doc, page = _page_with_text("Sheet")
    edit = {"type": "note", "page": 0, "point": (50, 50),
            "text": "a comment"}
    apply_pending_edits(doc, [edit])
    annots = list(page.annots() or [])
    count = len(annots)
    first_kind = annots[0].type[1] if annots else None
    doc.close()
    assert count == 1
    assert first_kind == "Text"


# ── delete_annot: removes a matching annotation ──────────────────────────

def test_delete_annot_removes_matching_annotation():
    doc, page = _page_with_text("Sheet")
    annot = page.add_text_annot((50, 50), "to be deleted")
    target_type = annot.type[0]
    target_bbox = list(annot.rect)
    assert len(list(page.annots() or [])) == 1
    edit = {"type": "delete_annot", "page": 0,
            "annot_type": target_type, "bbox": target_bbox}
    apply_pending_edits(doc, [edit])
    remaining = list(page.annots() or [])
    doc.close()
    assert remaining == []


def test_delete_annot_leaves_non_matching_annotation():
    doc, page = _page_with_text("Sheet")
    page.add_text_annot((50, 50), "keep me")
    # bbox nowhere near the real annot -> no match, nothing deleted
    edit = {"type": "delete_annot", "page": 0,
            "annot_type": 0, "bbox": [300, 300, 320, 320]}
    apply_pending_edits(doc, [edit])
    remaining = list(page.annots() or [])
    doc.close()
    assert len(remaining) == 1


# ── _existing gate: only delete_annot survives the skip ───────────────────

def test_existing_non_delete_edits_are_skipped():
    doc, page = _page_with_text("KeepThis")
    span = _first_span(page)
    edit = _text_edit(span, "ShouldNotAppear")
    edit["_existing"] = True   # already saved in the PDF -> must be skipped
    apply_pending_edits(doc, [edit])
    reopened = _reopen(doc)
    txt = reopened[0].get_text()
    reopened.close()
    assert "KeepThis" in txt
    assert "ShouldNotAppear" not in txt


def test_existing_delete_annot_still_applied():
    doc, page = _page_with_text("Sheet")
    annot = page.add_text_annot((50, 50), "existing note")
    edit = {"type": "delete_annot", "page": 0, "_existing": True,
            "annot_type": annot.type[0], "bbox": list(annot.rect)}
    apply_pending_edits(doc, [edit])
    remaining = list(page.annots() or [])
    doc.close()
    assert remaining == []   # delete_annot bypasses the _existing skip


# ── warnings: accumulated in result AND forwarded to warn_fn ──────────────

def test_unfittable_text_edit_warns_via_result_and_callback():
    """A replacement far too large for a tiny page must raise the non-blocking
    text-fit warning: recorded in ApplyResult.text_fit_warnings AND forwarded
    to the optional warn_fn callback (preserving the previous semantics)."""
    doc, page = _page_with_text("x", size=14, width=120, height=90, at=(20, 40))
    span = _first_span(page)
    huge = "word " * 400
    edit = _text_edit(span, huge)
    live = []
    result = apply_pending_edits(doc, [edit], warn_fn=live.append)
    reopened = _reopen(doc)
    txt = reopened[0].get_text()
    reopened.close()
    assert result.text_fit_warnings, "no warning accumulated in the result"
    assert result.text_fit_warnings[0] is edit
    assert live and live[0] is edit, "warn_fn callback was not forwarded"
    assert "word" in txt, "text was dropped instead of shrunk"


def test_fitting_text_edit_produces_no_warnings():
    doc, page = _page_with_text("Short", size=12, width=400, height=300)
    span = _first_span(page)
    result = apply_pending_edits(doc, [_text_edit(span, "AlsoShort")])
    assert result.text_fit_warnings == []
    doc.close()


# ── image / signature: embeds a raster into the page ─────────────────────

def _write_png(dir_path, name="stamp.png", size=12, value=90):
    """Write a tiny valid PNG to ``dir_path`` and return its path string.

    Uses only ``fitz`` (no PIL dependency): a solid-grey RGB pixmap saved as
    PNG. Small but real, so ``insert_image`` genuinely embeds a raster.
    """
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, size, size))
    pix.clear_with(value)
    path = dir_path / name
    pix.save(str(path))
    return str(path)


@pytest.mark.parametrize("edit_type", ["image", "signature"])
def test_image_and_signature_embed_raster(tmp_path, edit_type):
    """Both ``image`` and ``signature`` route through the same branch and must
    embed the on-disk raster into the target page. Parametrising over the two
    type strings makes this discriminative: dropping either from the branch's
    ``in ("image", "signature")`` tuple would fail here."""
    doc, page = _page_with_text("Backdrop", width=300, height=200)
    assert page.get_images() == [], "page unexpectedly had an image to start"
    img_path = _write_png(tmp_path, name=f"{edit_type}.png")
    edit = {"type": edit_type, "page": 0,
            "rect": fitz.Rect(40, 40, 140, 140), "path": img_path}
    result = apply_pending_edits(doc, [edit])
    assert isinstance(result, ApplyResult)
    reopened = _reopen(doc)               # persist + reload through bytes
    images = reopened[0].get_images()
    reopened.close()
    assert len(images) == 1, (
        f"{edit_type} edit did not embed exactly one raster: {images}")


# ── highlight: creates a coloured highlight annotation ───────────────────

def test_highlight_creates_coloured_highlight_annot():
    """A ``highlight`` edit must add exactly one Highlight annotation over the
    target rect and stamp it with the requested stroke colour (proving both
    ``add_highlight_annot`` and the ``set_colors(stroke=...)`` call run)."""
    doc, page = _page_with_text("HighlightMe", size=16, at=(30, 60))
    span = _first_span(page)
    before = len(list(page.annots() or []))
    colour = (0.1, 0.7, 0.3)             # distinct from the default yellow
    edit = {"type": "highlight", "page": 0,
            "rect": fitz.Rect(span["bbox"]), "color": colour}
    apply_pending_edits(doc, [edit])
    annots = list(page.annots() or [])
    count = len(annots)
    kind = annots[-1].type[1] if annots else None
    stroke = annots[-1].colors.get("stroke") if annots else None
    doc.close()
    assert count == before + 1
    assert kind == "Highlight"
    assert stroke is not None
    assert all(abs(a - b) < 0.05 for a, b in zip(stroke, colour, strict=True)), (
        f"highlight stroke colour {stroke} != requested {colour}")


# ── batch: several edit types in one call ────────────────────────────────

def test_mixed_batch_applies_all_edits():
    doc, page = _page_with_text("FirstLine", size=14, at=(30, 50),
                                width=420, height=260)
    span = _first_span(page)
    edits = [
        _text_edit(span, "EditedFirst"),
        {"type": "text", "page": 0, "point": (30, 120),
         "text": "AddedText", "size": 12, "color": (0, 0, 0),
         "font": "Helvetica"},
        {"type": "note", "page": 0, "point": (200, 80), "text": "note"},
        {"type": "draw", "page": 0,
         "points": [(40, 200), (80, 220), (120, 200)],
         "color": (0, 0, 1), "width": 2},
    ]
    result = apply_pending_edits(doc, edits)
    annots = list(page.annots() or [])
    annot_kinds = sorted(a.type[1] for a in annots)
    reopened = _reopen(doc)
    txt = reopened[0].get_text()
    reopened.close()
    assert "EditedFirst" in txt
    assert "FirstLine" not in txt
    assert "AddedText" in txt
    assert annot_kinds == ["Ink", "Text"]
    assert isinstance(result, ApplyResult)
