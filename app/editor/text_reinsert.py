"""PDFApps – pure typographic-fidelity helpers for text-edit reinsertion.

High-fidelity text-edit reinsertion. When the user edits an existing text span
the old code redacted the span with an opaque WHITE rectangle and re-typed the
text with a base-14 font at an inflated size (``max(size, bbox_height)``),
collapsing the family and dropping bold/italic. The helpers below reproduce the
original size, weight, colour and — when the source font is fully embedded
(non-subset) and covers the new glyphs — the exact typeface, using a transparent
redaction (no white box) plus ``Page.insert_htmlbox`` (HarfBuzz shaping + Noto
glyph fallback). Everything is wrapped so a failure degrades gracefully to a
base-14 ``insert_text`` instead of corrupting the page. See issue #147.

These functions are pure (no Qt/UI/``self`` state): PyMuPDF (``fitz``) and the
document/page objects are passed in as arguments, so they can be unit-tested
headless. Kept in a dedicated module (extracted from ``app.editor.tab``) to keep
the UI tab lean; ``app.editor.tab`` re-uses ``_reinsert_edited_text`` from here.
"""

import html
import logging


_log = logging.getLogger(__name__)


_EMBED_FAMILY = "PDFAppsEmbeddedFont"
# Legibility floor for the reinserted text. ``insert_htmlbox`` may scale text
# down to make it fit; below this fraction of the original point size the result
# is effectively illegible, so we surface a non-blocking warning instead of
# shrinking silently (issue S1). We keep PyMuPDF's default ``scale_low=0`` (see
# ``_warn_if_downscaled``) because a positive ``scale_low`` makes insert_htmlbox
# draw NOTHING on overflow — total text loss, worse than an over-shrunk line.
_MIN_LEGIBLE_SCALE = 0.6
# Style tokens stripped (as suffixes) when reducing a PostScript/BaseFont name
# to a comparable "core" family, so e.g. ``ArialMT`` and ``Arial Regular`` and
# ``Arial-BoldMT`` all reduce to ``arial``. Matching is only a HINT — the
# extracted font is still verified glyph-by-glyph before use.
_FONT_STYLE_SUFFIXES = (
    "regular", "book", "roman", "medium", "semibold", "demibold",
    "bold", "italic", "oblique", "light", "black", "heavy", "condensed",
    "mt", "ps",
)


def _font_core(name):
    """Reduce a font name to a comparable lowercase alphanumeric core."""
    s = "".join(c for c in (name or "").split("+")[-1].lower() if c.isalnum())
    changed = True
    while changed:
        changed = False
        for suf in _FONT_STYLE_SUFFIXES:
            if s.endswith(suf) and len(s) - len(suf) >= 3:
                s = s[:-len(suf)]
                changed = True
    return s


def _font_matches(core, basefont, name):
    if not core:
        return False
    for cand in (_font_core(basefont), _font_core(name)):
        if cand and (core == cand or core in cand or cand in core):
            return True
    return False


def _text_edit_size(edit):
    """Original span font size (points). ``font_size`` is the true span size;
    ``size`` is the inflated visual size kept for the inline editor. Falls back
    to a small floor only when both are missing/zero."""
    size = float(edit.get("font_size") or 0) or float(edit.get("size") or 0)
    return size if size >= 1.0 else 4.0


def _text_edit_color_hex(edit):
    c = edit.get("color", 0)
    if isinstance(c, bool):
        c = 0
    if isinstance(c, int):
        return "#%06x" % (c & 0xFFFFFF)
    if isinstance(c, float):
        return "#%06x" % (int(c) & 0xFFFFFF)
    if c:
        try:
            r, g, b = c[0], c[1], c[2]
            return "#%02x%02x%02x" % (
                max(0, min(255, int(r * 255))),
                max(0, min(255, int(g * 255))),
                max(0, min(255, int(b * 255))))
        except Exception:
            pass
    return "#000000"


def _text_edit_color_rgb(edit):
    c = edit.get("color", 0)
    if isinstance(c, bool):
        c = 0
    if isinstance(c, int):
        return (((c >> 16) & 0xFF) / 255, ((c >> 8) & 0xFF) / 255, (c & 0xFF) / 255)
    if c:
        try:
            return (float(c[0]), float(c[1]), float(c[2]))
        except Exception:
            pass
    return (0, 0, 0)


def _text_edit_style(edit):
    """Return (serif, mono, bold, italic) from the span's PyMuPDF ``flags``
    (bold=16, italic=2, serif=4, mono=8) complemented by name substrings — the
    flags are documented as an unreliable hint, so we OR in the name heuristic."""
    flags = int(edit.get("flags", 0) or 0)
    fname = (edit.get("font", "") or "").lower()
    serif = bool(flags & 4) or any(
        k in fname for k in ("times", "serif", "roman", "georgia", "garamond", "minion"))
    mono = bool(flags & 8) or any(
        k in fname for k in ("mono", "courier", "consol"))
    bold = bool(flags & 16) or any(
        k in fname for k in ("bold", "black", "heavy", "semibold"))
    italic = bool(flags & 2) or any(
        k in fname for k in ("italic", "oblique"))
    return serif, mono, bold, italic


def _base14_fontname(edit):
    """Best-matching base-14 font code for the defensive insert_text fallback."""
    serif, mono, bold, italic = _text_edit_style(edit)
    if mono:
        tbl = {(0, 0): "cour", (1, 0): "cobo", (0, 1): "coit", (1, 1): "cobi"}
    elif serif:
        tbl = {(0, 0): "tiro", (1, 0): "tibo", (0, 1): "tiit", (1, 1): "tibi"}
    else:
        tbl = {(0, 0): "helv", (1, 0): "hebo", (0, 1): "heit", (1, 1): "hebi"}
    return tbl[(int(bold), int(italic))]


def _generic_font_style(edit):
    """CSS (family, weight, style) for the generic-family htmlbox fallback."""
    serif, mono, bold, italic = _text_edit_style(edit)
    family = "monospace" if mono else ("serif" if serif else "sans-serif")
    return family, ("bold" if bold else "normal"), ("italic" if italic else "normal")


def _build_embed_archive(fitz, doc, page, edit, new_txt):
    """Return ``(archive, ref)`` embedding the span's ORIGINAL font, or
    ``(None, None)``. Only fully embedded (non-subset) fonts whose glyph set
    covers the new text are used; subset fonts (``ABCDEF+`` prefix) are skipped
    because their trimmed cmap/coverage cannot be reliably re-embedded.

    MUST be called BEFORE the redaction: ``apply_redactions`` removes the span
    and can drop the now-unreferenced font from ``page.get_fonts()``.
    """
    core = _font_core(edit.get("font", ""))
    if not core:
        return None, None
    try:
        fonts = page.get_fonts(full=False)
    except Exception:
        return None, None
    xref = None
    for f in fonts:
        # get_fonts tuple: (xref, ext, type, basefont, name, encoding)
        fxref, basefont, name = f[0], f[3], f[4]
        if "+" in (basefont or ""):
            continue  # subsetted — unreliable to re-embed standalone
        if fxref and int(fxref) > 0 and _font_matches(core, basefont, name):
            xref = int(fxref)
            break
    if not xref:
        return None, None
    try:
        _n, ext_, _t, content = doc.extract_font(xref)
    except Exception:
        return None, None
    if not content or len(content) < 256:
        return None, None
    # Verify the extracted font actually covers every non-space glyph of the
    # new text; otherwise fall through so htmlbox's Noto fallback can kick in.
    try:
        probe = fitz.Font(fontbuffer=content)
        for ch in new_txt:
            if ch.isspace():
                continue
            if not probe.has_glyph(ord(ch)):
                return None, None
    except Exception:
        return None, None
    ref = "pdfapps_embed." + ((ext_ or "ttf").lstrip(".") or "ttf")
    try:
        arch = fitz.Archive()
        arch.add(content, ref)
    except Exception:
        return None, None
    return arch, ref


def _text_edit_redaction_rect(fitz, edit, size):
    """Vertically TIGHT redaction rectangle for removing the original span.

    PyMuPDF's span ``bbox`` is inflated by the font's ascender/descender —
    often ~1.35x the point size — so redacting the raw bbox of a single line at
    normal (~1.2x) leading reaches into, and erases glyphs of, the lines
    directly above and below (the adjacent-line clipping bug, A1). We instead
    rebuild the band from the baseline with the documented PyMuPDF recipe::

        y1 = origin.y - size * descender / (ascender - descender)   # descenders
        y0 = y1 - size                                              # ~body top

    The band is only ~one point size tall (not the inflated line height) yet it
    still straddles the baseline, so ``apply_redactions`` — which removes a
    glyph whose bbox merely INTERSECTS the rectangle — still deletes every
    target glyph, while neighbours a full line-height away are left untouched.
    Missing/degenerate metrics (or a band that would fall outside the original
    bbox) fall back to the raw bbox, which is always safe for removal."""
    bbox = fitz.Rect(edit["bbox"])
    origin = edit.get("origin") or (bbox.x0, bbox.y1)
    asc = float(edit.get("ascender") or 0)
    desc = float(edit.get("descender") or 0)
    span = asc - desc
    if size > 0 and asc > 0 and desc < 0 and span > 1e-3:
        y1 = float(origin[1]) - size * desc / span
        y0 = y1 - size
        # Adopt the tight band only when it is well-formed AND contained within
        # the inflated bbox (with a hair of slack): this guarantees we never
        # *expand* the deleted area and guards against odd origin/metrics.
        if (y1 - y0) >= size * 0.5 and y0 >= bbox.y0 - 0.5 and y1 <= bbox.y1 + 0.5:
            return fitz.Rect(bbox.x0, y0, bbox.x1, y1)
    return bbox


def _text_edit_layout_rect(fitz, page, edit, size):
    """Layout rectangle for insert_htmlbox. insert_htmlbox lays text from the
    TOP of the rect, so we anchor the top at ``origin_y - ascender*size`` (the
    original ascent line) which lands the new baseline within ~1pt of the
    original for the exact font and within a couple of points for a substitute.
    The rect runs to the right page margin (widest single line, avoiding
    scale-down) and extends DOWN to the bottom page margin so longer edited text
    WRAPS at its original size across several lines instead of being silently
    scaled to an illegible size (S1). htmlbox draws only glyphs, never a filled
    box, so the extra height is visually free."""
    bbox = fitz.Rect(edit["bbox"])
    origin = edit.get("origin") or (bbox.x0, bbox.y1)
    asc = float(edit.get("ascender") or 0) or 0.9
    x0 = float(origin[0])
    top = float(origin[1]) - asc * size
    right = page.rect.x1 - 2.0
    if right <= x0 + size:
        right = min(page.rect.x1, x0 + size * 8)
    bottom = max(top + 3.0 * size, page.rect.y1 - 2.0)
    return fitz.Rect(x0, top, right, bottom)


def _warn_if_downscaled(htmlbox_result, edit, warn_fn):
    """Inspect ``Page.insert_htmlbox``'s ``(spare_height, scale)`` return value.

    We keep the default ``scale_low=0`` so text is never dropped, but a scale
    below ``_MIN_LEGIBLE_SCALE`` (or a reported fit failure) means the edit had
    to shrink to an illegible size. Rather than let that happen silently we log
    it and notify ``warn_fn`` (if given) so the caller can raise a non-blocking
    heads-up. Any unexpected return shape is ignored defensively."""
    try:
        spare_height, scale = htmlbox_result
        scale = float(scale)
    except Exception:
        return
    if scale < _MIN_LEGIBLE_SCALE or (spare_height is not None and spare_height < 0):
        _log.warning(
            "edited text did not fit its box at the original size "
            "(scale=%.2f); it was reduced to fit. old=%r",
            scale, (edit.get("old_text") or "")[:40])
        if warn_fn is not None:
            try:
                warn_fn(edit)
            except Exception:
                _log.exception("text-fit warn_fn raised")


def _reinsert_edited_text(fitz, doc, page, edit, warn_fn=None):
    """Redact the original span transparently and reinsert the edited text with
    the original size/weight/colour and — when possible — the exact font.
    Returns True if the original embedded font was reused (so the caller may run
    ``subset_fonts`` afterwards).

    ``warn_fn`` (optional): called with ``edit`` when the reinserted text did
    not fit at its original size and had to be scaled below the legibility floor
    — lets the caller surface a non-blocking heads-up instead of an unexplained
    tiny line (S1)."""
    bbox = fitz.Rect(edit["bbox"])
    new_txt = (edit.get("new_text") or "").strip()
    size = _text_edit_size(edit)
    # Capture the source font BEFORE redaction removes the glyphs (and the font).
    arch = ref = None
    if new_txt:
        arch, ref = _build_embed_archive(fitz, doc, page, edit, new_txt)
    # 1) Remove the original glyphs WITHOUT the white-rectangle artifact:
    #    a transparent redaction (no fill, no cross-out) that only deletes text
    #    (images=0, graphics=0) so a coloured background/line-art survives. The
    #    rectangle is a vertically TIGHT body band (not the inflated line-height
    #    bbox) so adjacent lines are not clipped — see _text_edit_redaction_rect.
    redact_rect = _text_edit_redaction_rect(fitz, edit, size)
    try:
        page.add_redact_annot(redact_rect, fill=False, cross_out=False)
        page.apply_redactions(images=0, graphics=0, text=0)
    except Exception:
        # Last-resort removal guarantee (previous behaviour): opaque white box.
        page.add_redact_annot(redact_rect, fill=(1, 1, 1))
        page.apply_redactions()
    if not new_txt:
        return False
    color_hex = _text_edit_color_hex(edit)
    rect = _text_edit_layout_rect(fitz, page, edit, size)
    body = "<div>%s</div>" % html.escape(new_txt)
    # 2) Reinsert with fidelity. ``white-space:pre-wrap`` preserves the original
    #    spacing yet lets long edited text WRAP into the tall box (S1) instead of
    #    being scaled down to fit on one line. Any failure degrades to a base-14
    #    insert_text at the original baseline (already correct size/weight/
    #    colour), never leaving the page corrupted.
    try:
        if arch is not None:
            css = ("@font-face {{ font-family: {fam}; src: url({ref}); }}\n"
                   "* {{ margin:0; padding:0; white-space:pre-wrap;"
                   " font-family:{fam}; font-size:{sz}pt; color:{col}; }}"
                   ).format(fam=_EMBED_FAMILY, ref=ref, sz=size, col=color_hex)
            _warn_if_downscaled(
                page.insert_htmlbox(rect, body, css=css, archive=arch),
                edit, warn_fn)
            return True
        family, weight, style = _generic_font_style(edit)
        css = ("* {{ margin:0; padding:0; white-space:pre-wrap;"
               " font-family:{fam}; font-size:{sz}pt; color:{col};"
               " font-weight:{w}; font-style:{s}; }}"
               ).format(fam=family, sz=size, col=color_hex, w=weight, s=style)
        _warn_if_downscaled(page.insert_htmlbox(rect, body, css=css), edit, warn_fn)
        return False
    except Exception:
        _log.exception("htmlbox reinsertion failed; using base-14 insert_text")
        try:
            origin = edit.get("origin") or (bbox.x0, bbox.y1)
            page.insert_text(fitz.Point(float(origin[0]), float(origin[1])),
                             new_txt, fontsize=size,
                             fontname=_base14_fontname(edit),
                             color=_text_edit_color_rgb(edit))
        except Exception:
            _log.exception("base-14 insert_text fallback also failed")
        return False
