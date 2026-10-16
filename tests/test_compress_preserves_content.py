"""Regression tests: Compress keeps every piece of content (pass B).

Pass B of ``_compress_pdf`` (PyMuPDF) used to call ``doc.scrub(...)`` and
save with ``clean=True``. On PyMuPDF 1.28.2 that destroyed content:

* S1: ``scrub`` treats the invisible text of an OCR layer
  (``render_mode=3``) as hidden text and redacts it, so a searchable scan
  came out of Compress unsearchable. Visible text and drawings that
  overlap the invisible text (S1b) went with it.
* S2: the other ``scrub`` defaults removed links, reset filled form fields
  to their ``/DV``, emptied the attachments, dropped comment replies
  (``/IRT``) and popups, removed JavaScript, ``/Info``, XMP and the page
  ``/Thumb``, and applied pending redactions.
* S3: ``save(clean=True)`` rewrites the content streams and duplicates a
  glyph drawn over another one: ``(f)Tj 0 0 TD (faeces)Tj`` read back as
  "ffaeces" (also on 1.28.0).

Each test builds a compressible source (a noise image, so pass B has a
real size gain), compresses it with Ghostscript and pikepdf disabled, so
the output is pass B's own, and compares the content of input and output.
"""

from __future__ import annotations

import io
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# app.i18n.t() needs a QCoreApplication (QSettings); offscreen keeps CI
# display-free.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402
_unused_app = QApplication.instance() or QApplication([])

import pymupdf  # noqa: E402

from app import utils  # noqa: E402

LEVELS = ("recommended", "extreme")


# ── helpers ──────────────────────────────────────────────────────────────


def _noise_pixmap(side: int = 1000) -> pymupdf.Pixmap:
    """High-entropy RGB raster: Flate barely shrinks it, the JPEG re-encode
    of pass B does, so _compress_pdf never ends in its "no gain" error."""
    return pymupdf.Pixmap(pymupdf.csRGB, side, side,
                          os.urandom(side * side * 3), False)


def _compress(src: Path, dst: Path, level: str) -> Path:
    """Run _compress_pdf with only pass B able to produce an output."""
    with pytest.MonkeyPatch.context() as mp:
        # Pass A would replace the document whenever gs wins; pass C would
        # re-save pass B's output. Neither is under test here.
        mp.setattr(utils, "_find_gs", lambda: None)
        mp.setitem(sys.modules, "pikepdf", None)
        before, after = utils._compress_pdf(str(src), str(dst), level=level)
    assert after < before, (before, after)
    assert utils._is_valid_pdf(str(dst))
    return dst


def _words(path: Path) -> list[Counter]:
    """Per-page multiset of the extracted words."""
    with pymupdf.open(str(path)) as d:
        return [Counter(w[4] for w in p.get_text("words")) for p in d]


def _trace_types(path: Path) -> list[set]:
    """Per-page set of text render types (3 = invisible)."""
    with pymupdf.open(str(path)) as d:
        return [{span["type"] for span in p.get_texttrace()} for p in d]


# ── T1.1 (S1): invisible OCR layer ──────────────────────────────────────


def _make_ocr_like(path: Path) -> Path:
    doc = pymupdf.open()
    pix = _noise_pixmap()
    for i in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, pixmap=pix)
        for k in range(8):
            page.insert_text(
                (40, 60 + k * 30),
                f"searchable ocr line {k} the the page {i}",
                fontsize=14, render_mode=3)
    doc.save(str(path))
    doc.close()
    return path


@pytest.mark.parametrize("level", LEVELS)
def test_invisible_ocr_text_layer_survives(tmp_path, level):
    src = _make_ocr_like(tmp_path / "ocr like.pdf")
    words_in = _words(src)
    assert all(words_in) and words_in[0]["the"] == 16
    assert _trace_types(src) == [{3}, {3}]

    out = _compress(src, tmp_path / "saída ç.pdf", level)

    assert _words(out) == words_in
    # Still invisible: pass B must neither drop nor reveal the layer.
    assert _trace_types(out) == [{3}, {3}]


def _tesseract_or_skip(monkeypatch):
    """Point pytesseract at Tesseract the way the OCR tool does, or skip."""
    pytesseract = pytest.importorskip("pytesseract")
    pytest.importorskip("PIL")
    from app.tools._ocr_paths import _find_tessdata, _find_tesseract
    exe = _find_tesseract()
    if not exe:
        pytest.skip("Tesseract is not installed")
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", exe)
    tessdata = _find_tessdata(exe)
    if tessdata:
        monkeypatch.setenv("TESSDATA_PREFIX", tessdata)
    try:
        langs = pytesseract.get_languages(config="")
    except Exception as e:  # noqa: BLE001 - any failure means "cannot OCR"
        pytest.skip(f"Tesseract does not run: {e}")
    else:
        if "eng" not in langs:
            pytest.skip("Tesseract has no 'eng' language data")
    return pytesseract


def _make_real_ocr(path: Path, pytesseract) -> Path:
    """An OCR'd scan built the way TabOCR._run builds its PDF output:
    300-dpi page raster -> image_to_pdf_or_hocr(extension="pdf") ->
    PdfWriter.append."""
    from PIL import Image
    from pypdf import PdfReader, PdfWriter

    scan = pymupdf.open()
    page = scan.new_page(width=595, height=842)
    page.draw_rect(page.rect, color=None, fill=(1.0, 0.98, 0.94))
    page.insert_text((60, 70), "The quick brown fox jumps over the lazy dog",
                     fontsize=16)
    for i in range(6):
        page.insert_text((60, 130 + i * 52), f"Searchable OCR line number {i}",
                         fontsize=22)
    # A photo-like region: without it the Flate-stored text scan is
    # already smaller than its JPEG re-encode and Compress reports
    # "no gain" (Tesseract stamps the image at 70 dpi, so nothing is
    # downsampled either).
    page.insert_image(pymupdf.Rect(60, 480, 535, 800),
                      pixmap=_noise_pixmap(800))
    pix = page.get_pixmap(dpi=300)
    scan.close()
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    page_bytes = pytesseract.image_to_pdf_or_hocr(img, lang="eng",
                                                  extension="pdf")
    img.close()
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(page_bytes)))
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def test_real_tesseract_ocr_layer_survives(tmp_path, monkeypatch):
    pytesseract = _tesseract_or_skip(monkeypatch)
    src = _make_real_ocr(tmp_path / "ocr real.pdf", pytesseract)
    words_in = _words(src)
    # Exact OCR output varies with the Tesseract version; only require a
    # real text layer.
    assert sum(words_in[0].values()) >= 20 and words_in[0]["line"] >= 3, \
        words_in
    assert _trace_types(src) == [{3}]

    out = _compress(src, tmp_path / "out.pdf", "extreme")

    assert _words(out) == words_in
    assert _trace_types(out) == [{3}]


# ── T1.2 (S1b): visible text and a drawing over invisible text ──────────


def _make_overlap(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(50, 450, 545, 800), pixmap=_noise_pixmap())
    page.insert_text((50, 300), "INVISIBLE OCR WORDS HERE", fontsize=20,
                     render_mode=3)
    page.insert_text((70, 304), "VISIBLE STAMP", fontsize=20,
                     color=(1, 0, 0))
    page.draw_rect(pymupdf.Rect(45, 280, 400, 310), color=(0, 0, 1),
                   width=2)
    page.draw_line((45, 295), (400, 295), color=(0, 0.5, 0), width=1)
    page.insert_text((50, 100), "VISIBLE FAR AWAY", fontsize=20)
    doc.save(str(path))
    doc.close()
    return path


@pytest.mark.parametrize("level", LEVELS)
def test_visible_text_and_drawings_over_invisible_text_survive(tmp_path,
                                                               level):
    src = _make_overlap(tmp_path / "overlap.pdf")
    with pymupdf.open(str(src)) as d:
        drawings_in = len(d[0].get_drawings())
    assert drawings_in >= 2
    words_in = _words(src)
    assert words_in[0]["STAMP"] == 1 and words_in[0]["INVISIBLE"] == 1

    out = _compress(src, tmp_path / "out.pdf", level)

    assert _words(out) == words_in
    with pymupdf.open(str(out)) as d:
        assert len(d[0].get_drawings()) == drawings_in


# ── T1.3 (S2): everything else a PDF can carry ──────────────────────────

_XMP = ('<?xpacket begin=""?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:title>XMP Title</dc:title></rdf:Description></rdf:RDF>'
        '</x:xmpmeta><?xpacket end="w"?>')
_INFO = {"title": "Rich Title", "author": "Rich Author",
         "subject": "Rich Subject", "keywords": "k1,k2"}
_EMB_BYTES = b"a,b\n1,2\n"
_ANNOT_FILE_BYTES = b"annot attachment body"
_THUMB_BYTES = b"\x80"
_FIELDS = {"name": ("Alice Filled", "(Default Name)"),
           "city": ("Lisboa Filled", "(Porto Default)")}


def _make_rich(path: Path) -> Path:
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
    p1, p2, p3 = doc[0], doc[1], doc[2]

    p1.insert_text((50, 60), "Visible heading", fontsize=20)
    p1.insert_text((50, 400), "Pending redaction target", fontsize=14)
    p1.add_redact_annot(pymupdf.Rect(48, 385, 300, 405))
    p1.insert_link({"kind": pymupdf.LINK_GOTO, "page": 1,
                    "from": pymupdf.Rect(50, 45, 250, 65),
                    "to": pymupdf.Point(0, 0)})
    p1.insert_link({"kind": pymupdf.LINK_GOTO, "page": 2,
                    "from": pymupdf.Rect(50, 450, 250, 470),
                    "to": pymupdf.Point(0, 0)})
    p1.insert_link({"kind": pymupdf.LINK_URI, "uri": "https://pdf-apps.com",
                    "from": pymupdf.Rect(50, 500, 300, 520)})
    # Reply first in /Annots: with the parent first, the old scrub() raised
    # on page 1 (it deletes the reply while iterating the annotations) and
    # never reached the rest of this fixture, so most checks below could
    # not tell the old pass B from the new one.
    reply = p1.add_text_annot(pymupdf.Point(400, 140), "reply comment")
    parent = p1.add_text_annot(pymupdf.Point(400, 100), "parent comment")
    parent.set_popup(pymupdf.Rect(420, 100, 560, 180))
    parent.update()
    doc.xref_set_key(reply.xref, "IRT", f"{parent.xref} 0 R")

    p2.insert_image(pymupdf.Rect(50, 50, 545, 545), pixmap=_noise_pixmap(1200))
    ocg = doc.add_ocg("Layer One", on=True)
    p2.insert_text((50, 600), "Text on a layer", fontsize=16, oc=ocg)

    for i, (name, (value, _dv)) in enumerate(_FIELDS.items()):
        w = pymupdf.Widget()
        w.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        w.field_name = name
        w.rect = pymupdf.Rect(50, 100 + 40 * i, 300, 125 + 40 * i)
        w.field_value = value
        p3.add_widget(w)
    w = pymupdf.Widget()
    w.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
    w.field_name = "agree"
    w.rect = pymupdf.Rect(50, 180, 65, 195)
    w.field_value = True
    p3.add_widget(w)
    p3.add_file_annot(pymupdf.Point(400, 100), _ANNOT_FILE_BYTES, "note.txt")
    doc.embfile_add("data.csv", _EMB_BYTES, filename="data.csv",
                    desc="doc-level attachment")

    doc.set_toc([[1, "Intro", 1], [1, "Image", 2], [1, "Form", 3]])
    doc.set_page_labels([{"startpage": 0, "prefix": "A-", "style": "D",
                          "firstpagenum": 1}])
    doc.set_metadata(_INFO)
    doc.set_xml_metadata(_XMP)

    cat = doc.pdf_catalog()
    st = doc.get_new_xref()
    doc.update_object(st, "<</Type/StructTreeRoot/K []>>")
    doc.xref_set_key(cat, "StructTreeRoot", f"{st} 0 R")
    doc.xref_set_key(cat, "MarkInfo", "<</Marked true>>")
    js = doc.get_new_xref()
    doc.update_object(js, "<</S/JavaScript/JS(app.alert\\('doc js'\\);)>>")
    jsn = doc.get_new_xref()
    doc.update_object(jsn, f"<</Names[(init) {js} 0 R]>>")
    doc.xref_set_key(cat, "Names/JavaScript", f"{jsn} 0 R")
    th = doc.get_new_xref()
    doc.update_object(th, "<</Type/XObject/Subtype/Image/Width 1/Height 1"
                          "/ColorSpace/DeviceGray/BitsPerComponent 8>>")
    doc.update_stream(th, _THUMB_BYTES, new=True)
    doc.xref_set_key(p1.xref, "Thumb", f"{th} 0 R")
    for wd in p3.widgets():
        if wd.field_name in _FIELDS:
            doc.xref_set_key(wd.xref, "DV", _FIELDS[wd.field_name][1])
        elif wd.field_name == "agree":
            doc.xref_set_key(wd.xref, "DV", "/Off")
    doc.save(str(path))
    doc.close()
    return path


def _fields(d) -> dict:
    return {w.field_name: w.field_value for p in d for w in p.widgets()}


def _js_sources(d) -> list:
    out = []
    for x in range(1, d.xref_length()):
        if d.xref_get_key(x, "S")[1] == "/JavaScript":
            out.append(d.xref_get_key(x, "JS")[1])
    return sorted(out)


def _annots_by_content(page) -> dict:
    return {a.info["content"]: a for a in page.annots()}


def _ref_xref(d, xref, key) -> int | None:
    kind, val = d.xref_get_key(xref, key)
    return int(val.split()[0]) if kind == "xref" else None


@pytest.fixture(scope="module", params=LEVELS)
def rich(request, tmp_path_factory):
    """(input, output) of one compression of the rich fixture, per level."""
    work = tmp_path_factory.mktemp(f"rich-{request.param}")
    src = _make_rich(work / "rich é.pdf")
    out = _compress(src, work / "rich out.pdf", request.param)
    din, dout = pymupdf.open(str(src)), pymupdf.open(str(out))
    yield din, dout
    din.close()
    dout.close()


def test_rich_words(rich):
    din, dout = rich
    words = [Counter(w[4] for w in p.get_text("words")) for p in din]
    assert words[0]["redaction"] == 1 and words[1]["layer"] == 1
    assert [Counter(w[4] for w in p.get_text("words")) for p in dout] == words


def test_rich_form_values_not_reset_to_default(rich):
    din, dout = rich
    fields_in = _fields(din)
    assert fields_in == {"name": "Alice Filled", "city": "Lisboa Filled",
                         "agree": "Yes"}
    for w in din[2].widgets():
        assert din.xref_get_key(w.xref, "DV")[1] != din.xref_get_key(
            w.xref, "V")[1]
    assert _fields(dout) == fields_in


def test_rich_links(rich):
    din, dout = rich

    def links(d):
        return [(lk["kind"], lk.get("page"), lk.get("uri"))
                for lk in d[0].get_links()]

    assert len(links(din)) == 3
    assert links(dout) == links(din)


def test_rich_attachments_bytes(rich):
    for d in rich:
        assert d.embfile_names() == ["data.csv"]
        assert d.embfile_get("data.csv") == _EMB_BYTES
        page = d[2]  # an Annot is only usable while its Page is alive
        (fa,) = list(page.annots(types=(pymupdf.PDF_ANNOT_FILE_ATTACHMENT,)))
        assert fa.get_file() == _ANNOT_FILE_BYTES


def test_rich_comment_popup_and_reply(rich):
    for d in rich:
        page = d[0]
        annots = _annots_by_content(page)
        parent, reply = annots["parent comment"], annots["reply comment"]
        assert parent.has_popup
        assert _ref_xref(d, reply.xref, "IRT") == parent.xref


def test_rich_annotation_types_include_pending_redaction(rich):
    din, dout = rich

    def types(d):
        return [sorted(a.type[1] for a in p.annots()) for p in d]

    assert "Redact" in types(din)[0]
    assert types(dout) == types(din)


def test_rich_info_and_xmp(rich):
    din, dout = rich
    assert {k: dout.metadata[k] for k in _INFO} == _INFO
    assert dout.get_xml_metadata() == din.get_xml_metadata() == _XMP


def test_rich_javascript(rich):
    din, dout = rich
    assert _js_sources(din) and all(s not in ("", "()")
                                    for s in _js_sources(din))
    assert _js_sources(dout) == _js_sources(din)


def test_rich_layer_structure_toc_labels(rich):
    din, dout = rich
    for d in rich:
        assert sorted(v["name"] for v in d.get_ocgs().values()) == [
            "Layer One"]
        cat = d.pdf_catalog()
        assert d.xref_get_key(cat, "StructTreeRoot")[0] == "xref"
        assert d.xref_get_key(cat, "MarkInfo")[0] == "dict"
    assert len(din.get_toc()) == 3
    assert dout.get_toc() == din.get_toc()
    assert dout.get_page_labels() == din.get_page_labels()


def test_rich_thumbnail(rich):
    for d in rich:
        th = _ref_xref(d, d[0].xref, "Thumb")
        assert th is not None
        assert d.xref_stream(th) == _THUMB_BYTES


# ── T1.4 (S3): overprinted glyphs are not duplicated ────────────────────


def _make_overprint(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    # Registers /helv in the page resources for the hand-written stream.
    page.insert_text((0, -50), " ", fontname="helv", fontsize=1)
    doc.update_stream(page.get_contents()[0],
                      b"BT /helv 24 Tf 1 0 0 1 100 700 Tm "
                      b"(f)Tj 0 0 TD (faeces)Tj ET")
    noise = doc.new_page(width=595, height=842)
    noise.insert_image(noise.rect, pixmap=_noise_pixmap())
    doc.save(str(path))
    doc.close()
    return path


@pytest.mark.parametrize("level", LEVELS)
def test_overprinted_glyph_is_not_duplicated(tmp_path, level):
    src = _make_overprint(tmp_path / "overprint.pdf")
    assert _words(src)[0] == Counter({"faeces": 1})

    out = _compress(src, tmp_path / "out.pdf", level)

    assert _words(out)[0] == Counter({"faeces": 1})
