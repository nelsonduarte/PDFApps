"""Regression tests: Compress keeps gradients drawn with shading patterns.

Pass B of ``_compress_pdf`` calls ``Document.rewrite_images()``. On
PyMuPDF 1.28.0 and 1.28.2 that call runs MuPDF's colour filter over every
content stream, and the filter copies a shading pattern selected with
``scn`` / ``SCN`` into the /Shading resources as ``null`` (see
app/_shading_patterns.py). The ``/P1 scn`` left in the content then names
nothing: a gradient fill came out white, an image mask painted with a
gradient vanished, and a Word 365 ``TwoColorGradient`` shape disappeared
(mean render difference 5.25 on the real file). At the ``recommended``
and ``low`` levels the file handed to the user was pass B's. At
``extreme``, the ``recolor()`` that ``rewrite_images(set_to_gray=True)``
runs first also rebuilds each shading pattern without its /Matrix, which
moves the gradient (the ``word_like`` fixture has one).

The sources are built by code. Each content stream is stored uncompressed
and repeats its drawing, so pass B gains from deflate alone and
``_compress_pdf`` never ends in its "no gain" error, whether or not it
rewrites images. Ghostscript and pikepdf are disabled unless a test says
otherwise, so the output is pass B's own.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# app.i18n.t() needs a QCoreApplication (QSettings); offscreen keeps CI
# display-free.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

_unused_app = QApplication.instance() or QApplication([])

import pymupdf

from app import utils

LEVELS = ("extreme", "recommended", "low")

# Mean absolute difference per sample (0-255) between the renders of
# source and output (in gray at extreme). Measured with this fix: 0.00 on
# every affected fixture and level, from pass B alone and from the whole
# pipeline with Ghostscript at recommended and low. Measured without it:
# 26.6 (stroke) to 133.5 on these fixtures, and 5.25 on the Word 365
# file, whose gradient covers only part of one page. Keeping recolor() at
# extreme gave 15.0 on word_like. 1.0 sits clear of all of them.
MAX_MEAN_DIFF = 1.0

_AXIAL = ("<</ShadingType 2 /ColorSpace /DeviceRGB /Coords [0 0 300 0]"
          " /Function <</FunctionType 2 /Domain [0 1] /C0 [1 0 0]"
          " /C1 [0 0 1] /N 1>> /Extend [true true]>>")

# Modelled on the Word 365 case (the file itself was not available): the
# pattern sits inside a Form XObject and has a /Matrix and a stitching
# function.
_WORD_AXIAL = ("<</ShadingType 2 /ColorSpace /DeviceRGB"
               " /Coords [0 0 1 0] /Extend [true true]"
               " /Function <</FunctionType 3 /Domain [0 1] /Bounds [0.5]"
               " /Encode [0 1 0 1] /Functions ["
               " <</FunctionType 2 /Domain [0 1] /C0 [0.27 0.45 0.77]"
               " /C1 [0.62 0.76 0.90] /N 1>>"
               " <</FunctionType 2 /Domain [0 1] /C0 [0.62 0.76 0.90]"
               " /C1 [0.98 0.85 0.40] /N 1>>]>>>>")

_REPEAT = 300


# ── fixture builders ─────────────────────────────────────────────────────


def _obj(doc, src: str) -> int:
    xref = doc.get_new_xref()
    doc.update_object(xref, src)
    return xref


def _stream(doc, data: bytes, dict_src: str = "<<>>") -> int:
    xref = _obj(doc, dict_src)
    doc.update_stream(xref, data, compress=False)
    return xref


def _page(doc, ops: bytes, resources: str) -> None:
    page = doc.new_page(width=300, height=300)
    contents = _stream(doc, ops * _REPEAT)
    doc.xref_set_key(page.xref, "Contents", f"{contents} 0 R")
    doc.xref_set_key(page.xref, "Resources", resources)


def _rgb_image(doc, w: int, h: int, noise: bool) -> int:
    if noise:
        raw = os.urandom(w * h * 3)
    else:
        raw = bytes(v for y in range(h) for x in range(w)
                    for v in (x * 255 // w, y * 255 // h, 128))
    return _stream(doc, raw,
                   f"<</Type /XObject /Subtype /Image /Width {w} /Height {h}"
                   " /ColorSpace /DeviceRGB /BitsPerComponent 8>>")


def _shading_pattern(doc, shading: str = _AXIAL, extra: str = "",
                     pattern_type: str = "2") -> int:
    sh = _obj(doc, shading)
    return _obj(doc, f"<</Type /Pattern /PatternType {pattern_type}"
                     f" /Shading {sh} 0 R{extra}>>")


def _fill(doc):
    pat = _shading_pattern(doc)
    _page(doc, b"/Pattern cs /P1 scn 20 20 260 260 re f\n",
          f"<</Pattern <</P1 {pat} 0 R>>>>")


def _stroke(doc):
    pat = _shading_pattern(doc)
    _page(doc, b"/Pattern CS /P1 SCN 16 w 40 40 220 220 re S\n",
          f"<</Pattern <</P1 {pat} 0 R>>>>")


def _image_mask(doc):
    pat = _shading_pattern(doc)
    w = h = 400
    mask = bytes((0xF0 if (y // 20) % 2 == 0 else 0x0F)
                 for y in range(h) for _ in range(w // 8))
    im = _stream(doc, mask,
                 f"<</Type /XObject /Subtype /Image /Width {w} /Height {h}"
                 " /ImageMask true /BitsPerComponent 1 /Decode [1 0]>>")
    _page(doc, b"/Pattern cs /P1 scn q 260 0 0 260 20 20 cm /Im1 Do Q\n",
          f"<</Pattern <</P1 {pat} 0 R>> /XObject <</Im1 {im} 0 R>>>>")


def _direct_pattern(doc):
    """The pattern is a direct object inside /Resources, not an xref."""
    sh = _obj(doc, _AXIAL)
    _page(doc, b"/Pattern cs /P1 scn 20 20 260 260 re f\n",
          f"<</Pattern <</P1 <</PatternType 2 /Shading {sh} 0 R>>>>>>")


def _indirect_pattern_type(doc):
    """/PatternType is a reference to an object holding 2. MuPDF resolves
    it, so the colour filter treats the pattern as a shading pattern."""
    two = _obj(doc, "2")
    pat = _shading_pattern(doc, pattern_type=f"{two} 0 R")
    _page(doc, b"/Pattern cs /P1 scn 20 20 260 260 re f\n",
          f"<</Pattern <</P1 {pat} 0 R>>>>")


def _matrix_fill(doc):
    """A pattern /Matrix on the page itself, which recolor() drops: the
    gradient then spans the whole page width instead of x 75 to 225."""
    pat = _shading_pattern(doc, extra=" /Matrix [0.5 0 0 1 75 0]")
    _page(doc, b"/Pattern cs /P1 scn 20 20 260 260 re f\n",
          f"<</Pattern <</P1 {pat} 0 R>>>>")


def _word_like(doc):
    pat = _shading_pattern(doc, _WORD_AXIAL,
                           " /Matrix [260 0 0 120 20 160]")
    form = _stream(doc, b"/Pattern cs /P15 scn 20 160 260 120 re f*\n",
                   "<</Type /XObject /Subtype /Form /BBox [0 0 300 300]"
                   f" /Resources <</Pattern <</P15 {pat} 0 R>>>>>>")
    photo = _rgb_image(doc, 400, 200, noise=False)
    _page(doc, b"/Fm1 Do q 260 0 0 120 20 20 cm /Im1 Do Q\n",
          f"<</XObject <</Fm1 {form} 0 R /Im1 {photo} 0 R>>>>")


def _sh_operator(doc):
    sh = _obj(doc, _AXIAL)
    _page(doc, b"q 20 20 260 260 re W n /Sh1 sh Q\n",
          f"<</Shading <</Sh1 {sh} 0 R>>>>")


def _tiling_image(doc):
    img = _rgb_image(doc, 300, 300, noise=True)
    tile = _stream(doc, b"q 50 0 0 50 0 0 cm /Im1 Do Q\n",
                   "<</Type /Pattern /PatternType 1 /PaintType 1"
                   " /TilingType 1 /BBox [0 0 50 50] /XStep 50 /YStep 50"
                   f" /Resources <</XObject <</Im1 {img} 0 R>>>>>>")
    _page(doc, b"/Pattern cs /T1 scn 20 20 260 260 re f\n",
          f"<</Pattern <</T1 {tile} 0 R>>>>")


def _photo(doc):
    img = _rgb_image(doc, 600, 600, noise=True)
    _page(doc, b"q 260 0 0 260 20 20 cm /Im1 Do Q\n",
          f"<</XObject <</Im1 {img} 0 R>>>>")


AFFECTED = {
    "fill": _fill,
    "stroke": _stroke,
    "image_mask": _image_mask,
    "direct_pattern": _direct_pattern,
    "indirect_pattern_type": _indirect_pattern_type,
    "matrix_fill": _matrix_fill,
    "word_like": _word_like,
}
UNAFFECTED = {
    "sh_operator": _sh_operator,
    "tiling_image": _tiling_image,
    "photo": _photo,
}


def _build(tmp_path: Path, kind: str) -> Path:
    doc = pymupdf.open()
    {**AFFECTED, **UNAFFECTED}[kind](doc)
    path = tmp_path / f"fonte {kind} ç.pdf"
    doc.save(str(path))
    doc.close()
    return path


# ── helpers ──────────────────────────────────────────────────────────────


def _compress(src: Path, dst: Path, level: str, *, gs: bool = False) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        if not gs:
            mp.setattr(utils, "_find_gs", lambda: None)
        mp.setitem(sys.modules, "pikepdf", None)
        before, after = utils._compress_pdf(str(src), str(dst), level=level)
    assert after < before, (before, after)
    assert utils._is_valid_pdf(str(dst))
    return dst


_OPERAND_OP = re.compile(rb"/([^\s/\[\]<>(){}%]+)\s+(scn|SCN|sh|Do)(?![A-Za-z])")


def _numbers(value: str) -> tuple:
    return tuple(round(float(v), 3) for v in value.strip("[]").split())


def _shadings_in_use(path: Path) -> set:
    """What every content stream paints with a shading, by resource lookup.

    For each ``/Name scn|SCN`` the name is resolved in that stream's own
    /Pattern resources, for ``/Name sh`` in its /Shading resources, and
    Form XObjects and tiling patterns are followed. A shading is recorded
    by its type, its /Coords and the pattern /Matrix (identity when
    absent), which a gray conversion keeps; a name that resolves to
    nothing is recorded as missing.
    """
    found: set = set()
    with pymupdf.open(str(path)) as doc:

        def walk(owner: int, content: bytes, depth: int) -> None:
            assert depth < 8
            for m in _OPERAND_OP.finditer(content):
                name, op = m.group(1).decode(), m.group(2)
                if op in (b"scn", b"SCN"):
                    base = f"Resources/Pattern/{name}"
                    ptype = doc.xref_get_key(owner, f"{base}/PatternType")
                    if ptype[0] == "xref":
                        target = int(ptype[1].split()[0])
                        ptype = ("int", doc.xref_object(target).strip())
                    if ptype == ("int", "2"):
                        shade = f"{base}/Shading"
                        matrix = doc.xref_get_key(owner, f"{base}/Matrix")
                    elif ptype == ("int", "1"):
                        kind, ref = doc.xref_get_key(owner, base)
                        assert kind == "xref"
                        tile = int(ref.split()[0])
                        walk(tile, doc.xref_stream(tile), depth + 1)
                        continue
                    else:
                        found.add(("missing pattern", name))
                        continue
                elif op == b"sh":
                    shade = f"Resources/Shading/{name}"
                    matrix = ("array", "[1 0 0 1 0 0]")
                else:
                    base = f"Resources/XObject/{name}"
                    if doc.xref_get_key(owner, f"{base}/Subtype") != ("name", "/Form"):
                        continue
                    kind, ref = doc.xref_get_key(owner, base)
                    assert kind == "xref"
                    form = int(ref.split()[0])
                    walk(form, doc.xref_stream(form), depth + 1)
                    continue
                stype = doc.xref_get_key(owner, f"{shade}/ShadingType")
                coords = doc.xref_get_key(owner, f"{shade}/Coords")
                if stype[0] != "int":
                    found.add(("missing shading", name))
                    continue
                if matrix[0] == "null":
                    matrix = ("array", "[1 0 0 1 0 0]")
                found.add((op.decode().lower(), stype[1], _numbers(coords[1]),
                           _numbers(matrix[1])))

        for page in doc:
            walk(page.xref, page.read_contents(), 0)
    return found


def _render(path: Path, gray: bool) -> list:
    cs = pymupdf.csGRAY if gray else pymupdf.csRGB
    with pymupdf.open(str(path)) as doc:
        return [bytes(p.get_pixmap(alpha=False, colorspace=cs).samples) for p in doc]


def _mean_diff(a: Path, b: Path, gray: bool) -> float:
    ra, rb = _render(a, gray), _render(b, gray)
    assert [len(x) for x in ra] == [len(x) for x in rb]
    total = sum(sum(abs(x - y) for x, y in zip(pa, pb)) for pa, pb in zip(ra, rb))
    return total / sum(len(x) for x in ra)


def _objects_but_id(path: Path) -> tuple:
    """Every object (dictionary and decoded stream) and the trailer, all
    but /ID. The second /ID string is random on every save, and MuPDF
    writes it as hex or as an escaped literal depending on its bytes, so
    two saves of the same document can differ in size by a few bytes
    (measured: 32 of 3000 saves of one page)."""
    with pymupdf.open(str(path)) as doc:
        objects = []
        for x in range(1, doc.xref_length()):
            if doc.xref_get_key(x, "Type") == ("name", "/XRef"):
                continue
            stream = doc.xref_stream(x) if doc.xref_is_stream(x) else None
            objects.append((doc.xref_object(x, compressed=True), stream))
        trailer = {k: doc.xref_get_key(-1, k)
                   for k in doc.xref_get_keys(-1) if k != "ID"}
    return trailer, objects


def _image_filters(path: Path) -> list:
    with pymupdf.open(str(path)) as doc:
        return sorted(doc.xref_get_key(x, "Filter")[1]
                      for x in range(1, doc.xref_length())
                      if doc.xref_get_key(x, "Subtype") == ("name", "/Image"))


# ── affected: the gradient survives pass B on every level ───────────────


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("kind", sorted(AFFECTED))
def test_shading_pattern_survives_pass_b(tmp_path, kind, level):
    src = _build(tmp_path, kind)
    in_use = _shadings_in_use(src)
    assert in_use and all(entry[0] in ("scn", "sh") for entry in in_use)

    out = _compress(src, tmp_path / f"saída {kind}.pdf", level)

    # Structure: each name the content selects still resolves to a
    # shading of the same type and geometry.
    assert _shadings_in_use(out) == in_use
    # Pixels: extreme converts to gray on purpose, so compare in gray there.
    gray = utils._COMPRESS_LEVELS[level]["grayscale"]
    assert _mean_diff(src, out, gray) < MAX_MEAN_DIFF


# ── unaffected: shadings survive and images are still rewritten ─────────


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("kind", sorted(UNAFFECTED))
def test_without_shading_patterns_pass_b_output_is_unchanged(
        tmp_path, monkeypatch, kind, level):
    """No shading pattern: pass B still calls rewrite_images(), and its
    output holds exactly the objects the pre-fix pass B produced (fonts
    subset, the same rewrite_images() call, the same save()), replayed
    here from the arguments _compress_pdf actually passed. Only the
    random /ID may differ."""
    src = _build(tmp_path, kind)
    in_use = _shadings_in_use(src)

    real_rewrite = pymupdf.Document.rewrite_images
    real_save = pymupdf.Document.save
    rewrites: list = []
    saves: list = []

    def spy_rewrite(self, *args, **kwargs):
        rewrites.append((args, kwargs))
        return real_rewrite(self, *args, **kwargs)

    def spy_save(self, *args, **kwargs):
        saves.append(kwargs)
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(pymupdf.Document, "rewrite_images", spy_rewrite)
    monkeypatch.setattr(pymupdf.Document, "save", spy_save)

    out = _compress(src, tmp_path / f"saída {kind}.pdf", level)

    assert len(rewrites) == 1
    assert len(saves) == 1
    assert _shadings_in_use(out) == in_use

    replay = tmp_path / "replay.pdf"
    with pymupdf.open(str(src)) as doc:
        doc.subset_fonts()
        real_rewrite(doc, *rewrites[0][0], **rewrites[0][1])
        real_save(doc, str(replay), **saves[0])
    assert _objects_but_id(out) == _objects_but_id(replay)

    if kind != "sh_operator":
        # A set: at extreme, recolor() gives each of the repeated "Do"
        # its own gray copy of the image, before and after this fix.
        assert set(_image_filters(out)) == {"/DCTDecode"}
        assert out.stat().st_size < src.stat().st_size // 2


# ── the detector itself ─────────────────────────────────────────────────


@pytest.mark.parametrize("kind", sorted({**AFFECTED, **UNAFFECTED}))
def test_has_shading_pattern(tmp_path, kind):
    from app._shading_patterns import has_shading_pattern

    with pymupdf.open(str(_build(tmp_path, kind))) as doc:
        assert has_shading_pattern(doc) is (kind in AFFECTED)


def test_has_shading_pattern_ignores_other_pattern_type_numbers():
    from app._shading_patterns import has_shading_pattern

    doc = pymupdf.open()
    doc.new_page()
    _obj(doc, "<</Type /Pattern /PatternType 1 /Note (none)>>")
    _obj(doc, "<</Foo /PatternType /Bar 2>>")
    _obj(doc, "<</PatternType 20>>")
    assert has_shading_pattern(doc) is False
    _obj(doc, "<</PatternType 2>>")
    assert has_shading_pattern(doc) is True
    doc.close()


@pytest.mark.parametrize("target", ("2", "2.0", "1"))
def test_has_shading_pattern_fails_closed_on_indirect_pattern_type(target):
    """An indirect /PatternType is a match whatever it points to: the scan
    reads one object at a time and never resolves the reference, so even
    a reference to 1 (a tiling pattern) skips the image rewrite."""
    from app._shading_patterns import has_shading_pattern

    doc = pymupdf.open()
    doc.new_page()
    value = _obj(doc, target)
    assert has_shading_pattern(doc) is False
    _obj(doc, f"<</Type /Pattern /PatternType {value} 0 R>>")
    assert has_shading_pattern(doc) is True
    doc.close()


# ── a detector error fails closed ───────────────────────────────────────


@pytest.mark.parametrize("kind", ("fill", "photo"))
def test_detector_error_skips_rewrite(tmp_path, monkeypatch, kind):
    """If has_shading_pattern() raises, pass B must still save its output
    without calling rewrite_images(): the check sits inside the try that
    guards the rewrite, so it neither fails pass B nor falls back to the
    rewrite that loses gradients."""
    src = _build(tmp_path, kind)

    def broken_detector(doc):
        raise RuntimeError("detector failure")

    real_rewrite = pymupdf.Document.rewrite_images
    rewrites: list = []

    def spy_rewrite(self, *args, **kwargs):
        rewrites.append((args, kwargs))
        return real_rewrite(self, *args, **kwargs)

    monkeypatch.setattr(utils, "has_shading_pattern", broken_detector)
    monkeypatch.setattr(pymupdf.Document, "rewrite_images", spy_rewrite)

    out = _compress(src, tmp_path / f"saída {kind}.pdf", "recommended")

    assert rewrites == []
    assert _shadings_in_use(out) == _shadings_in_use(src)
    assert "/DCTDecode" not in _image_filters(out)


# ── canary: the upstream bug this fix works around ──────────────────────


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="rewrite_images() turns a shading pattern into /Shading null "
           "(MuPDF pdf-op-color.c, PyMuPDF 1.28.0 to 1.28.2). An XPASS "
           "means the installed PyMuPDF fixed it, and the skip in "
           "_compress_pdf pass B can be reviewed.")
def test_canary_rewrite_images_still_drops_shading_patterns(tmp_path):
    src = _build(tmp_path, "fill")
    in_use = _shadings_in_use(src)
    out = tmp_path / "rewritten.pdf"
    with pymupdf.open(str(src)) as doc:
        doc.rewrite_images(dpi_threshold=160, dpi_target=150, quality=75)
        doc.save(str(out))
    assert _shadings_in_use(out) == in_use


# ── with Ghostscript: what the user receives keeps the gradient ─────────


@pytest.mark.parametrize("level", ("recommended", "low"))
@pytest.mark.parametrize("kind", ("fill", "stroke", "image_mask",
                                  "direct_pattern"))
def test_delivered_file_keeps_gradient_with_ghostscript(tmp_path, kind, level):
    """The whole pipeline (pass A and pass B, smallest wins). Ghostscript
    rewrites patterns into its own resources, so only pixels are compared.
    extreme is left out: Ghostscript's gray conversion differs from
    MuPDF's by up to 16.8 on the image mask, unrelated to this bug."""
    if utils._find_gs() is None:
        pytest.skip("Ghostscript not installed")
    src = _build(tmp_path, kind)
    out = _compress(src, tmp_path / f"saída {kind}.pdf", level, gs=True)
    assert _mean_diff(src, out, gray=False) < MAX_MEAN_DIFF
