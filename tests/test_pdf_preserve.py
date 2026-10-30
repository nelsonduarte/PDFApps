"""Tests for app.pdf_preserve: the "did compress keep everything" oracle.

Every fixture is built in ``tmp_path`` with PyMuPDF. The core contract is
one row per preserved item: an original carrying the item, a copy that
differs from it by that item alone, and ``losses`` must name exactly that
item's key. Swapping the pair (copy as ``before``) checks that gaining an
item is not reported as a loss, except where the item's *value* changed,
which is a loss in both directions.

The second half pins the rewrites that are *not* losses (measured on
Ghostscript 10.05 and PyMuPDF 1.28.2 output): rounded or re-based boxes,
a /Rotate baked into the content, ligature glyphs, lost word spaces,
deduplicated or unshared image resources, named destinations resolved
to page links, and renumbered objects.
"""

from __future__ import annotations

import codecs
import dataclasses
import re
import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import pdf_preserve  # noqa: E402
from app.pdf_preserve import (  # noqa: E402
    Snapshot, SnapshotCancelled, SnapshotError, losses, snapshot)


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

# A PDF text string in UTF-16BE (with its byte order mark), the usual
# encoding of a script; MuPDF serialises it as a hex string.
UTF16_JS = codecs.BOM_UTF16_BE + "app.alert(1);".encode("utf-16-be")

XMP = ('<?xpacket begin=""?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
       '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
       '<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">'
       '<dc:title>XMP Title</dc:title></rdf:Description></rdf:RDF>'
       '</x:xmpmeta><?xpacket end="w"?>')


def _base() -> pymupdf.Document:
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 72), f"Page {i + 1} body text", fontsize=12)
    return doc


def _snap(path) -> Snapshot:
    doc = pymupdf.open(path)
    try:
        return snapshot(doc)
    finally:
        doc.close()


def _save(doc, path, **kw) -> None:
    doc.save(path, **kw)
    doc.close()


def _new_obj(doc, source: str) -> int:
    xref = doc.get_new_xref()
    doc.update_object(xref, source)
    return xref


def _new_stream(doc, data: bytes, header: str = "") -> int:
    xref = _new_obj(doc, f"<<{header}/Length 0>>")
    doc.update_stream(xref, data, new=True)
    return xref


def _append_annot(doc, page, annot_xref: int) -> None:
    kind, value = doc.xref_get_key(page.xref, "Annots")
    ref = f"{annot_xref} 0 R"
    doc.xref_set_key(page.xref, "Annots",
                     value.replace("]", f" {ref}]") if kind == "array" else f"[{ref}]")


def _drop_from_annots(doc, page, annot_xref: int) -> None:
    refs = [x for x, _t, _i in page.annot_xrefs() if x != annot_xref]
    doc.xref_set_key(page.xref, "Annots",
                     "[" + " ".join(f"{x} 0 R" for x in refs) + "]")


def _widget(page, field_type, name, rect, value=None):
    w = pymupdf.Widget()
    w.field_type = field_type
    w.field_name = name
    w.rect = pymupdf.Rect(rect)
    if value is not None:
        w.field_value = value
    return page.add_widget(w)


def _thumbnail(doc, page) -> None:
    th = _new_obj(doc, "<</Type/XObject/Subtype/Image/Width 1/Height 1"
                       "/ColorSpace/DeviceGray/BitsPerComponent 8/Length 1>>")
    doc.update_stream(th, b"\x80", new=True)
    doc.xref_set_key(page.xref, "Thumb", f"{th} 0 R")


def _doc_js(doc, js_value: str) -> None:
    """Document-level JavaScript in /Names/JavaScript."""
    js = _new_obj(doc, f"<</S/JavaScript/JS{js_value}>>")
    tree = _new_obj(doc, f"<</Names[(init) {js} 0 R]>>")
    doc.xref_set_key(doc.pdf_catalog(), "Names/JavaScript", f"{tree} 0 R")


def _gray_image(page, rect) -> None:
    pix = pymupdf.Pixmap(pymupdf.csGRAY, 64, 64, bytes(range(64)) * 64, False)
    page.insert_image(pymupdf.Rect(rect), pixmap=pix)


def _image_xobject(doc, shade: int = 0x80) -> int:
    return _new_stream(doc, bytes([shade]) * 64,
                       "/Type/XObject/Subtype/Image/Width 8/Height 8"
                       "/ColorSpace/DeviceGray/BitsPerComponent 8")


def _draw_images(doc, page, resources: str, names) -> None:
    """Replace the page's content with one ``Do`` per name, each at its
    own spot, and its /Resources with ``resources``."""
    ops = b"".join(b"q 80 0 0 80 %d 400 cm /%s Do Q\n" % (40 + 100 * i, n.encode())
                   for i, n in enumerate(names))
    doc.xref_set_key(page.xref, "Contents", f"{_new_stream(doc, ops)} 0 R")
    doc.xref_set_key(page.xref, "Resources", resources)


def _ligature_page(doc, ops: bytes) -> None:
    """A page whose Helvetica maps code 128 to the /fi glyph and 129 to
    /ff, as Ghostscript's output does."""
    page = doc.new_page(width=595, height=842)
    font = _new_obj(doc, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica"
                         "/Encoding<</Type/Encoding/BaseEncoding/WinAnsiEncoding"
                         "/Differences[128/fi 129/ff]>>>>")
    content = _new_stream(doc, b"BT /F1 12 Tf 50 700 Td " + ops + b" ET")
    doc.xref_set_key(page.xref, "Contents", f"{content} 0 R")
    doc.xref_set_key(page.xref, "Resources", f"<</Font<</F1 {font} 0 R>>>>")


def _text_pdf(path, lines):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    for i, line in enumerate(lines):
        page.insert_text((50, 72 + 30 * i), line, fontsize=12)
    _save(doc, path)


def _words(path) -> list[str]:
    doc = pymupdf.open(path)
    try:
        return [w[4] for w in doc[0].get_text("words")]
    finally:
        doc.close()


# -- per-item additions (applied to _base() to make the original) ------------

def add_page(doc):
    doc.new_page(width=595, height=842)


def add_mediabox(doc):
    doc[0].set_mediabox(pymupdf.Rect(0, 0, 612, 842))


def add_cropbox(doc):
    # Margins only: no text falls outside, so the text stays as it was.
    doc[0].set_cropbox(pymupdf.Rect(20, 20, 575, 822))


def add_rotation(doc):
    doc[0].set_rotation(90)


def add_rotation_180(doc):
    doc[0].set_rotation(180)


def add_text(doc):
    doc[0].insert_text((50, 200), "extra visible words", fontsize=12)


def add_invisible_text(doc):
    doc[0].insert_text((50, 300), "hidden ocr layer", fontsize=12, render_mode=3)


def add_text_page2(doc):
    doc[1].insert_text((50, 200), "second page extra", fontsize=12)


def add_image(doc):
    _gray_image(doc[0], (300, 300, 400, 400))


def add_uri_link(doc):
    doc[0].insert_link({"kind": pymupdf.LINK_URI, "uri": "https://pdf-apps.com",
                        "from": pymupdf.Rect(50, 500, 300, 520)})


def add_goto_link(doc):
    doc[0].insert_link({"kind": pymupdf.LINK_GOTO, "page": 1, "to": pymupdf.Point(0, 0),
                        "from": pymupdf.Rect(50, 60, 250, 80)})


def add_file_annot(doc):
    doc[0].add_file_annot(pymupdf.Point(400, 100), b"annot attachment body", "note.txt")


def add_highlight(doc):
    doc[0].add_highlight_annot(pymupdf.Rect(48, 60, 200, 80))


def add_highlight_with_contents(doc):
    page = doc[0]   # an Annot is unbound once its Page is collected
    annot = page.add_highlight_annot(pymupdf.Rect(48, 60, 200, 80))
    annot.set_info(content="important reviewer remark")
    annot.update()


def add_text_annot(doc):
    doc[0].add_text_annot(pymupdf.Point(400, 100), "a comment")


def add_reply(doc):
    parent = doc[0].add_text_annot(pymupdf.Point(400, 100), "parent comment")
    reply = doc[0].add_text_annot(pymupdf.Point(400, 140), "reply comment")
    doc.xref_set_key(reply.xref, "IRT", f"{parent.xref} 0 R")


def add_redaction(doc):
    doc[0].add_redact_annot(pymupdf.Rect(300, 600, 400, 620))


def add_thumbnail(doc):
    _thumbnail(doc, doc[0])


def add_empty_text_field(doc):
    _widget(doc[0], pymupdf.PDF_WIDGET_TYPE_TEXT, "name", (50, 400, 300, 425))


def add_filled_text_field(doc):
    _widget(doc[0], pymupdf.PDF_WIDGET_TYPE_TEXT, "name", (50, 400, 300, 425), "Alice")


def add_outline(doc):
    doc.set_toc([[1, "Intro", 1], [1, "Second", 2]])


def add_attachment(doc):
    doc.embfile_add("data.csv", b"a,b\n1,2\n", filename="data.csv")


def add_page_labels(doc):
    doc.set_page_labels([{"startpage": 0, "prefix": "A-", "style": "D", "firstpagenum": 1}])


def _add_info(key):
    def add(doc):
        doc.set_metadata({key: f"some {key}"})
    add.__name__ = f"add_info_{key}"
    return add


def _info_xref(doc) -> int:
    kind, ref = doc.xref_get_key(-1, "Info")
    if kind != "xref":
        doc.set_metadata({"title": doc.metadata.get("title") or ""})
        kind, ref = doc.xref_get_key(-1, "Info")
    return int(ref.split()[0])


def _set_info_raw(doc, entries: str) -> None:
    """Append raw ``/Key value`` pairs to the /Info dictionary (names with
    #xx escapes and indirect values, which set_metadata cannot write)."""
    info = _info_xref(doc)
    src = doc.xref_object(info, compressed=True)
    doc.update_object(info, src[:-2] + entries + ">>")


def add_info_custom(doc):
    _set_info_raw(doc, "/Company(ACME Lda)")


def _add_catalog(key, value):
    def add(doc):
        doc.xref_set_key(doc.pdf_catalog(), key, value(doc) if callable(value) else value)
    add.__name__ = f"add_catalog_{key}"
    return add


def _output_intents(doc) -> str:
    icc = _new_stream(doc, b"not really an ICC profile, but a stream all the same", "/N 3")
    return (f"[<</Type/OutputIntent/S/GTS_PDFA1/OutputConditionIdentifier(sRGB)"
            f"/DestOutputProfile {icc} 0 R>>]")


def _open_at_page2(doc) -> str:
    return f"[{doc[1].xref} 0 R/Fit]"


def add_xmp(doc):
    doc.set_xml_metadata(XMP)


def add_doc_javascript(doc):
    _doc_js(doc, r"(app.alert\('doc js'\);)")


def add_doc_javascript_hex(doc):
    # UTF-16BE, the usual encoding of a PDF text string; MuPDF serialises
    # it as a hex string, so this exercises the hex branch.
    _doc_js(doc, "<" + UTF16_JS.hex() + ">")


def add_doc_javascript_stream(doc):
    js = _new_stream(doc, b"app.alert('stream js');")
    _doc_js(doc, f" {js} 0 R")


def add_doc_javascript_indirect_string(doc):
    code = _new_obj(doc, r"(app.alert\('indirect string'\);)")
    _doc_js(doc, f" {code} 0 R")


def add_open_action_javascript(doc):
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction",
                     r"<</S/JavaScript/JS(app.alert\('open'\);)>>")


def add_link_javascript(doc):
    act = _new_obj(doc, r"<</S/JavaScript/JS(app.alert\('link js'\);)>>")
    link = _new_obj(doc, f"<</Type/Annot/Subtype/Link/Rect[50 600 250 620]"
                         f"/Border[0 0 0]/A {act} 0 R>>")
    _append_annot(doc, doc[0], link)


def add_struct_tree(doc):
    st = _new_obj(doc, "<</Type/StructTreeRoot/K []>>")
    doc.xref_set_key(doc.pdf_catalog(), "StructTreeRoot", f"{st} 0 R")


def add_mark_info(doc):
    doc.xref_set_key(doc.pdf_catalog(), "MarkInfo", "<</Marked true>>")


def add_ocg(doc):
    doc.add_ocg("Layer One", on=True)


def add_ocg_after_orphan(doc):
    # The orphan is dropped by garbage collection, which renumbers the OCG.
    _new_obj(doc, "<</Orphan true>>")
    doc.add_ocg("Layer One", on=True)


def add_signed_field(doc):
    w = _widget(doc[0], pymupdf.PDF_WIDGET_TYPE_SIGNATURE, "sig", (50, 700, 250, 750))
    sv = _new_obj(doc, "<</Type/Sig/Filter/Adobe.PPKLite/SubFilter/adbe.pkcs7.detached"
                       "/ByteRange[0 0 0 0]/Contents<00>>>")
    doc.xref_set_key(w.xref, "V", f"{sv} 0 R")


def add_signed_parent_field(doc):
    """The signature value on a parent field, the widget only a /Kids entry
    (how many signing tools write it)."""
    w = _widget(doc[0], pymupdf.PDF_WIDGET_TYPE_SIGNATURE, "sig", (50, 700, 250, 750))
    sv = _new_obj(doc, "<</Type/Sig/Filter/Adobe.PPKLite/ByteRange[0 0 0 0]/Contents<00>>>")
    parent = _new_obj(doc, f"<</FT/Sig/T(sig)/V {sv} 0 R/Kids[{w.xref} 0 R]>>")
    for key in ("T", "FT", "V"):
        doc.xref_set_key(w.xref, key, "null")
    doc.xref_set_key(w.xref, "Parent", f"{parent} 0 R")
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm/Fields", f"[{parent} 0 R]")


# -- strips: remove just the item from a reopened original -------------------
# Used where "the base document without the addition" would differ by more
# than the item (an annotation that drags its popup along, a field whose
# appearance carries text, ...). A strip may return save() keywords for
# the copy.

def strip_file_content(doc):
    for annot in doc[0].annots(types=(pymupdf.PDF_ANNOT_FILE_ATTACHMENT,)):
        annot.update_file(buffer_=b"different bytes")


def strip_file_annot_contents(doc):
    for annot in doc[0].annots(types=(pymupdf.PDF_ANNOT_FILE_ATTACHMENT,)):
        doc.xref_set_key(annot.xref, "Contents", "(another description)")


def strip_annot_contents(doc):
    for x, _t, _i in doc[0].annot_xrefs():
        if doc.xref_get_key(x, "Subtype")[1] == "/Highlight":
            doc.xref_set_key(x, "Contents", "()")


def strip_popup(doc):
    page = doc[0]
    for annot in page.annots(types=(pymupdf.PDF_ANNOT_TEXT,)):
        popup = annot.popup_xref
        assert popup, "fixture assumption: a Text annot gets a Popup"
        doc.xref_set_key(annot.xref, "Popup", "null")
        _drop_from_annots(doc, page, popup)


def strip_irt(doc):
    for x, _t, _i in doc[0].annot_xrefs():
        if doc.xref_get_key(x, "IRT")[0] != "null":
            doc.xref_set_key(x, "IRT", "null")


def strip_field_value(doc):
    for w in doc[0].widgets():
        doc.xref_set_key(w.xref, "V", "null")


def strip_signature_value(doc):
    for w in doc[0].widgets():
        doc.xref_set_key(w.xref, "V", "null")


def strip_parent_signature_value(doc):
    for w in doc[0].widgets():
        kind, ref = doc.xref_get_key(w.xref, "Parent")
        assert kind == "xref", "fixture assumption: the widget has a parent field"
        doc.xref_set_key(int(ref.split()[0]), "V", "null")


def strip_attachment(doc):
    # Not _base(): embfile_add also sets /PageMode /UseAttachments, which
    # is its own item.
    doc.embfile_del("data.csv")


def strip_attachment_content(doc):
    # Delete and re-add: embfile_upd(buffer_=bytes) raises AttributeError
    # inside PyMuPDF 1.28.2 itself.
    doc.embfile_del("data.csv")
    doc.embfile_add("data.csv", b"x,y\n9,9\n", filename="data.csv")


def strip_open_action_target(doc):
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction", f"[{doc[0].xref} 0 R/Fit]")


def strip_output_intent_profile(doc):
    _kind, intents = doc.xref_get_key(doc.pdf_catalog(), "OutputIntents")
    profile = re.search(r"/DestOutputProfile (\d+) 0 R", intents)
    assert profile, "fixture assumption: the profile is an indirect stream"
    doc.update_stream(int(profile.group(1)), b"a different profile")


def strip_xmp_content(doc):
    doc.set_xml_metadata(XMP.replace("XMP Title", "Other Title"))


def strip_names_javascript(doc):
    doc.xref_set_key(doc.pdf_catalog(), "Names/JavaScript", "null")


def strip_link_javascript(doc):
    # Rewrites the action object: xref_set_key(x, "A/JS", "()") does not
    # store an empty string, PyMuPDF 1.28.2 writes a placeholder text.
    for x, _t, _i in doc[0].annot_xrefs():
        kind, ref = doc.xref_get_key(x, "A")
        if kind == "xref" and doc.xref_get_key(x, "A/S")[1] == "/JavaScript":
            doc.update_object(int(ref.split()[0]), "<</S/JavaScript/JS()>>")


def strip_ocg_on(doc):
    doc.set_layer(-1, off=list(doc.get_ocgs()))
    return {"garbage": 4}


# (id, key, add, strip, reverse_is_gain)
#   strip None   -> the copy is _base() without the addition
#   reverse_is_gain False -> the item is a changed value, so swapping the
#                            pair is a loss of the other value, not a gain
CASES = [
    ("pages", "pages", add_page, None, True),
    ("mediabox", "mediabox:page1", add_mediabox, None, False),
    ("cropbox", "cropbox:page1", add_cropbox, None, False),
    ("rotation", "rotation:page1", add_rotation, None, False),
    ("rotation-180", "rotation:page1", add_rotation_180, None, False),
    ("text", "text:page1", add_text, None, True),
    ("text-invisible", "text:page1", add_invisible_text, None, True),
    ("text-page2", "text:page2", add_text_page2, None, True),
    ("images", "images:page1", add_image, None, True),
    ("links-uri", "links:page1", add_uri_link, None, True),
    ("links-goto", "links:page1", add_goto_link, None, True),
    ("file-annot-content", "file_annot:page1", add_file_annot, strip_file_content, False),
    ("file-annot-contents", "file_annot:page1", add_file_annot,
     strip_file_annot_contents, False),
    ("annots", "annots:page1", add_highlight, None, True),
    ("annots-contents", "annots:page1", add_highlight_with_contents,
     strip_annot_contents, False),
    ("popups", "popups:page1", add_text_annot, strip_popup, True),
    ("replies", "replies:page1", add_reply, strip_irt, True),
    ("redactions", "redactions:page1", add_redaction, None, True),
    ("thumbnail", "thumbnail:page1", add_thumbnail, None, True),
    ("form-field", "form:name", add_empty_text_field, None, True),
    ("form-value", "form:name", add_filled_text_field, strip_field_value, False),
    ("outline", "outline", add_outline, None, True),
    ("attachment", "attachment:data.csv", add_attachment, strip_attachment, True),
    ("attachment-content", "attachment:data.csv", add_attachment, strip_attachment_content, False),
    ("page-labels", "page_labels", add_page_labels, None, True),
    ("info-title", "info:title", _add_info("title"), None, True),
    ("info-author", "info:author", _add_info("author"), None, True),
    ("info-subject", "info:subject", _add_info("subject"), None, True),
    ("info-keywords", "info:keywords", _add_info("keywords"), None, True),
    ("info-creator", "info:creator", _add_info("creator"), None, True),
    ("info-producer", "info:producer", _add_info("producer"), None, True),
    ("info-creation-date", "info:creationDate", _add_info("creationDate"), None, True),
    ("info-custom", "info:Company", add_info_custom, None, True),
    ("xmp", "xmp", add_xmp, None, True),
    ("xmp-content", "xmp", add_xmp, strip_xmp_content, False),
    ("js-names", "javascript", add_doc_javascript, None, True),
    ("js-names-dropped", "javascript", add_doc_javascript, strip_names_javascript, True),
    ("js-hex", "javascript", add_doc_javascript_hex, None, True),
    ("js-stream", "javascript", add_doc_javascript_stream, None, True),
    ("js-indirect-string", "javascript", add_doc_javascript_indirect_string, None, True),
    ("js-open-action-inline", "javascript", add_open_action_javascript, None, True),
    ("js-link-action", "javascript", add_link_javascript, None, True),
    ("js-link-emptied", "javascript", add_link_javascript, strip_link_javascript, True),
    ("catalog-lang", "catalog:Lang", _add_catalog("Lang", "(pt-PT)"), None, True),
    ("catalog-viewer-prefs", "catalog:ViewerPreferences",
     _add_catalog("ViewerPreferences", "<</DisplayDocTitle true>>"), None, True),
    ("catalog-page-mode", "catalog:PageMode",
     _add_catalog("PageMode", "/UseOutlines"), None, True),
    ("catalog-page-layout", "catalog:PageLayout",
     _add_catalog("PageLayout", "/TwoColumnLeft"), None, True),
    ("catalog-output-intents", "catalog:OutputIntents",
     _add_catalog("OutputIntents", _output_intents), None, True),
    ("catalog-output-intent-profile", "catalog:OutputIntents",
     _add_catalog("OutputIntents", _output_intents), strip_output_intent_profile, False),
    ("catalog-open-action", "catalog:OpenAction",
     _add_catalog("OpenAction", _open_at_page2), None, True),
    ("catalog-open-action-target", "catalog:OpenAction",
     _add_catalog("OpenAction", _open_at_page2), strip_open_action_target, False),
    ("struct-tree", "struct_tree", add_struct_tree, None, True),
    ("mark-info", "mark_info", add_mark_info, None, True),
    ("ocg", "ocg:Layer One", add_ocg, None, True),
    ("ocg-state", "ocg:Layer One", add_ocg_after_orphan, strip_ocg_on, False),
    ("signature", "signature:sig", add_signed_field, strip_signature_value, True),
    ("signature-on-parent", "signature:sig", add_signed_parent_field,
     strip_parent_signature_value, True),
]


def _build_pair(tmp_path, add, strip):
    orig = tmp_path / "original.pdf"
    copy = tmp_path / "copy.pdf"
    doc = _base()
    add(doc)
    _save(doc, orig)
    if strip is None:
        doc, save_kw = _base(), {}
    else:
        doc = pymupdf.open(orig)
        save_kw = strip(doc) or {}
    _save(doc, copy, **save_kw)
    return orig, copy


# ---------------------------------------------------------------------------
# 1. one item lost -> exactly that key
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key, add, strip, reverse_is_gain",
                         [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_losing_one_item_reports_exactly_its_key(tmp_path, key, add, strip,
                                                 reverse_is_gain):
    orig, copy = _build_pair(tmp_path, add, strip)
    before, after = _snap(orig), _snap(copy)

    assert losses(before, after) == [key]
    if reverse_is_gain:
        assert losses(after, before) == [], "gaining an item was reported as a loss"
    else:
        assert losses(after, before) == [key]


def test_every_check_has_a_case():
    """A check added to _CHECKS without a CASES row would be untested."""
    keys = {c[1].split(":")[0] for c in CASES}
    names = {chk.__name__.removeprefix("_check_") for chk in pdf_preserve._CHECKS}
    aliases = {"forms": "form", "attachments": "attachment", "ocgs": "ocg",
               "signatures": "signature"}
    assert {aliases.get(n, n) for n in names} == keys


def test_every_info_and_catalog_key_has_a_case():
    """The fixed info: and catalog: keys each have a row; the open-ended
    info:NAME (any other /Info key) has at least one."""
    keys = {c[1] for c in CASES}
    assert {f"info:{k}" for k in pdf_preserve._INFO_KEYS} <= keys
    assert {f"catalog:{k}" for k in pdf_preserve._CATALOG_KEYS} <= keys
    assert any(k.startswith("info:") and k[5:] not in pdf_preserve._INFO_KEYS
               for k in keys)


def test_ocg_state_case_really_renumbers_the_layer(tmp_path):
    """Guards the ocg-state row: it only proves the name keying if the
    garbage=4 save moved the OCG to another xref."""
    orig, copy = _build_pair(tmp_path, add_ocg_after_orphan, strip_ocg_on)
    a, b = pymupdf.open(orig), pymupdf.open(copy)
    try:
        assert set(a.get_ocgs()) != set(b.get_ocgs())
        assert [v["on"] for v in a.get_ocgs().values()] == [True]
        assert [v["on"] for v in b.get_ocgs().values()] == [False]
    finally:
        a.close()
        b.close()


# ---------------------------------------------------------------------------
# 2. no false positives on a lossless rewrite of a document carrying everything
# ---------------------------------------------------------------------------

def _make_rich(path) -> None:
    """One PDF carrying every item of the list (adapted from the plan's
    make_rich.py)."""
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
    p1, p2, p3 = doc[0], doc[1], doc[2]
    p1.insert_text((50, 60), "Visible heading", fontsize=20)
    p1.insert_text((50, 300), "INVISIBLE OCR WORDS HERE", fontsize=20, render_mode=3)
    p1.insert_text((50, 400), "Pending redaction target", fontsize=14)
    p1.add_redact_annot(pymupdf.Rect(48, 385, 300, 405))
    p1.insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(50, 45, 250, 65),
                    "page": 1, "to": pymupdf.Point(0, 0)})
    p1.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(50, 500, 300, 520),
                    "uri": "https://pdf-apps.com"})
    parent = p1.add_text_annot(pymupdf.Point(400, 100), "parent comment")
    reply = p1.add_text_annot(pymupdf.Point(400, 140), "reply comment")
    doc.xref_set_key(reply.xref, "IRT", f"{parent.xref} 0 R")
    p1.add_highlight_annot(pymupdf.Rect(48, 45, 200, 65))
    p1.set_cropbox(pymupdf.Rect(10, 20, 585, 832))
    _gray_image(p2, (50, 50, 300, 300))
    ocg = doc.add_ocg("Layer One", on=True)
    doc.add_ocg("Layer Off", on=False)
    p2.insert_text((50, 600), "Text on a layer", fontsize=16, oc=ocg)
    p2.set_rotation(90)
    _widget(p3, pymupdf.PDF_WIDGET_TYPE_TEXT, "name", (50, 100, 300, 125), "Alice Filled")
    _widget(p3, pymupdf.PDF_WIDGET_TYPE_CHECKBOX, "agree", (50, 180, 65, 195), True)
    p3.add_file_annot(pymupdf.Point(400, 100), b"annot body", "note.txt")
    doc.embfile_add("data.csv", b"a,b\n1,2\n", filename="data.csv")
    doc.set_toc([[1, "Intro", 1], [1, "Image", 2], [1, "Form", 3]])
    doc.set_page_labels([{"startpage": 0, "prefix": "A-", "style": "D", "firstpagenum": 1}])
    doc.set_metadata({"title": "Rich Title", "author": "Rich Author",
                      "subject": "S", "keywords": "k1,k2", "creator": "Writer",
                      "producer": "LibreOffice", "creationDate": "D:20200101000000Z"})
    doc.set_xml_metadata(XMP)
    add_struct_tree(doc)
    add_mark_info(doc)
    add_doc_javascript(doc)
    add_link_javascript(doc)
    cat = doc.pdf_catalog()
    doc.xref_set_key(cat, "Lang", "(pt-PT)")
    doc.xref_set_key(cat, "ViewerPreferences", "<</DisplayDocTitle true>>")
    doc.xref_set_key(cat, "PageLayout", "/TwoColumnLeft")
    doc.xref_set_key(cat, "OutputIntents", _output_intents(doc))
    doc.xref_set_key(cat, "OpenAction", _open_at_page2(doc))
    _thumbnail(doc, p1)
    sig = _widget(p3, pymupdf.PDF_WIDGET_TYPE_SIGNATURE, "sig", (50, 220, 250, 270))
    sv = _new_obj(doc, "<</Type/Sig/Filter/Adobe.PPKLite/ByteRange[0 0 0 0]/Contents<00>>>")
    doc.xref_set_key(sig.xref, "V", f"{sv} 0 R")
    _save(doc, path, garbage=1)


@pytest.fixture(scope="module")
def rich_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("rich") / "rich.pdf"
    _make_rich(path)
    return path


def test_rich_fixture_carries_every_item(rich_pdf):
    """Guards the zero-loss test below: it only proves something if the
    fixture actually has each item to lose."""
    s = _snap(rich_pdf)
    p1, p2, p3 = s.pages
    assert len(s.pages) == 3
    assert p2.mediabox == (842, 595) and p2.orientation == 1
    assert p1.cropbox == (10, 20, 10, 10)
    chars1 = dict(p1.chars)
    assert chars1.get("I") >= 3 and chars1.get("V") >= 2   # the OCR layer
    assert p2.images == 1
    assert len(p1.links) == 2
    assert len(p3.file_annots) == 1
    assert {sub for (sub, _), _n in p1.annots} == {"Text", "Highlight"}
    assert p1.popups >= 2 and p1.replies == 1 and p1.redactions == 1
    assert p1.thumbnail
    assert {name for name, _ in s.forms} == {"name", "agree", "sig"}
    assert len(s.outline) == 3 and len(s.attachments) == 1
    assert s.page_labels and all(v for _, v in s.info) and s.xmp
    assert sum(n for _, n in s.javascript) == 2
    assert {k for k, _ in s.catalog} == set(pdf_preserve._CATALOG_KEYS)
    assert s.struct_tree and s.mark_info
    assert dict(s.ocgs) == {("Layer One", True): 1, ("Layer Off", False): 1}
    assert s.signatures == frozenset({"sig"})


def test_lossless_resave_reports_nothing(rich_pdf, tmp_path):
    out = tmp_path / "resaved.pdf"
    doc = pymupdf.open(rich_pdf)
    _save(doc, out, garbage=4, deflate=True, clean=False)

    before, after = _snap(rich_pdf), _snap(out)
    assert losses(before, after) == []
    assert losses(after, before) == []
    assert before == after and hash(before) == hash(after)


def test_orphan_javascript_dropped_by_garbage_collection_is_not_a_loss(tmp_path):
    """An action nothing references is not in the document. A scan of
    every xref would count it and then call its garbage collection a loss,
    making every such source uncompressible."""
    src = tmp_path / "orphan.pdf"
    out = tmp_path / "collected.pdf"
    doc = _base()
    add_doc_javascript(doc)
    _save(doc, src)
    doc = pymupdf.open(src)
    strip_names_javascript(doc)
    _save(doc, src.with_name("orphaned.pdf"))   # no garbage: the action stays as an orphan
    doc = pymupdf.open(src.with_name("orphaned.pdf"))
    orphan_kept = any("/JavaScript" in doc.xref_object(x)
                      for x in range(1, doc.xref_length()))
    _save(doc, out, garbage=4)

    assert orphan_kept, "fixture assumption: the orphan survives a plain save"
    before, after = _snap(src.with_name("orphaned.pdf")), _snap(out)
    assert before.javascript == frozenset()
    assert losses(before, after) == []


def test_reference_written_inside_a_string_does_not_reach_an_orphan(tmp_path):
    """"(see 12 0 R)" is text: following it made an orphaned script part of
    the document, and its garbage collection a loss."""
    src, out = tmp_path / "orphan.pdf", tmp_path / "collected.pdf"
    doc = _base()
    js = _new_obj(doc, r"<</S/JavaScript/JS(app.alert\('orphan'\);)>>")
    doc.set_metadata({"title": "T"})
    _set_info_raw(doc, f"/Note(see {js} 0 R)")
    _save(doc, src)
    doc = pymupdf.open(src)
    _save(doc, out, garbage=4)
    doc = pymupdf.open(out)
    try:
        assert not any("/JavaScript" in doc.xref_object(x)
                       for x in range(1, doc.xref_length())), "fixture: orphan collected"
    finally:
        doc.close()
    before = _snap(src)
    assert before.javascript == frozenset()
    assert losses(before, _snap(out)) == []


# ---------------------------------------------------------------------------
# 3. JavaScript payloads: same script, whatever the string form
# ---------------------------------------------------------------------------

def _js_pdf(path, js_value=None, stream=None) -> Snapshot:
    doc = _base()
    if stream is not None:
        js_value = f" {_new_stream(doc, stream)} 0 R"
    _doc_js(doc, js_value)
    _save(doc, path)
    return _snap(path)


def test_same_script_as_literal_or_stream_is_not_a_loss(tmp_path):
    a = _js_pdf(tmp_path / "literal.pdf", r"(app.alert\('same'\);\nvar x = \(1\);)")
    b = _js_pdf(tmp_path / "stream.pdf", stream=b"app.alert('same');\nvar x = (1);")
    assert a.javascript == b.javascript and len(a.javascript) == 1
    assert losses(a, b) == [] and losses(b, a) == []


def test_octal_escapes_digest_like_the_stream_bytes(tmp_path):
    # MuPDF folds printable octal escapes back into plain characters.
    a = _js_pdf(tmp_path / "abc.pdf", r"(\101\102C)")
    b = _js_pdf(tmp_path / "abc_stream.pdf", stream=b"ABC")
    assert a.javascript == b.javascript and len(a.javascript) == 1
    # A non-printable byte stays a three-digit escape in MuPDF's
    # serialisation, so this one goes through the octal decoder.
    path = tmp_path / "e9.pdf"
    c = _js_pdf(path, r"(caf\351 is a longer piece of text)")
    doc = pymupdf.open(path)
    try:
        assert any(r"\351" in doc.xref_object(x) for x in range(1, doc.xref_length())), \
            "fixture assumption: the escape survives MuPDF's serialisation"
    finally:
        doc.close()
    d = _js_pdf(tmp_path / "e9_stream.pdf", stream=b"caf\xe9 is a longer piece of text")
    assert c.javascript == d.javascript and len(c.javascript) == 1


def test_hex_string_digests_like_the_literal_and_the_stream(tmp_path):
    payload = UTF16_JS
    hexed = _js_pdf(tmp_path / "hex.pdf", "<" + payload.hex() + ">")
    literal = _js_pdf(tmp_path / "lit.pdf",
                      "(" + "".join(f"\\{b:03o}" for b in payload) + ")")
    stream = _js_pdf(tmp_path / "stream.pdf", stream=payload)
    assert len(hexed.javascript) == 1
    assert hexed.javascript == literal.javascript == stream.javascript


def test_literal_decoder_drops_a_backslash_eol():
    """The PDF line continuation. MuPDF never hands one to the decoder
    (see the next test), so it is checked here directly."""
    assert pdf_preserve._decode_literal("AB\\\nC") == b"ABC"
    assert pdf_preserve._decode_literal("AB\\\r\nC") == b"ABC"
    assert pdf_preserve._decode_literal("AB\\\rC") == b"ABC"
    assert pdf_preserve._decode_literal("A\\nB") == b"A\nB"


@pytest.mark.parametrize("eol", ["\n", "\r\n", "\r"])
def test_backslash_eol_continuation_digests_like_the_joined_stream(tmp_path, eol):
    """PyMuPDF 1.28.2 drops the backslash-EOL itself while parsing, as
    the spec says, so the decoder never sees one."""
    a = _js_pdf(tmp_path / "cont.pdf", f"(AB\\{eol}C)")
    b = _js_pdf(tmp_path / "joined.pdf", stream=b"ABC")
    assert a.javascript == b.javascript and len(a.javascript) == 1


@pytest.mark.parametrize("payload", ["()", "( )", "<>"])
def test_empty_javascript_is_not_counted(tmp_path, payload):
    assert _js_pdf(tmp_path / "empty_js.pdf", payload).javascript == frozenset()


# ---------------------------------------------------------------------------
# 4. text is a multiset of NFKC characters
# ---------------------------------------------------------------------------

def test_reordered_words_are_not_a_loss(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    _text_pdf(a, ["alpha beta gamma", "delta"])
    _text_pdf(b, ["delta gamma", "beta", "alpha"])
    assert losses(_snap(a), _snap(b)) == []


def test_one_fewer_occurrence_of_a_repeated_word_is_a_loss(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    _text_pdf(a, ["alpha alpha beta"])
    _text_pdf(b, ["alpha beta"])
    assert losses(_snap(a), _snap(b)) == ["text:page1"]
    assert losses(_snap(b), _snap(a)) == []


def test_ligature_glyph_is_not_a_loss(tmp_path):
    """Ghostscript writes "files" with the fi ligature glyph."""
    a, b = tmp_path / "plain.pdf", tmp_path / "ligature.pdf"
    _text_pdf(a, ["files"])
    doc = pymupdf.open()
    _ligature_page(doc, rb"(\200les) Tj")
    _save(doc, b)
    assert _words(b) == [chr(0xFB01) + "les"], "fixture assumption: the ligature is extracted"
    assert losses(_snap(a), _snap(b)) == []
    assert losses(_snap(b), _snap(a)) == []


def test_space_lost_after_a_ligature_is_not_a_loss(tmp_path):
    """MuPDF reads Ghostscript's "tradeoff since" back as one word."""
    a, b = tmp_path / "spaced.pdf", tmp_path / "joined.pdf"
    _text_pdf(a, ["tradeoff since"])
    doc = pymupdf.open()
    _ligature_page(doc, rb"(tradeo\201since) Tj")
    _save(doc, b)
    assert _words(b) == ["tradeo" + chr(0xFB00) + "since"], "fixture assumption"
    assert losses(_snap(a), _snap(b)) == []


def test_glyph_misread_as_another_character_is_a_loss(tmp_path):
    """Ghostscript's Impress output: "ficheiro" came back as "9cheiro"."""
    a, b = tmp_path / "ok.pdf", tmp_path / "broken.pdf"
    _text_pdf(a, ["o ficheiro foi gravado"])
    _text_pdf(b, ["o 9cheiro foi gravado"])
    assert losses(_snap(a), _snap(b)) == ["text:page1"]


def test_invisible_text_layer_removed_is_a_text_loss(tmp_path):
    """The OCR case: the page looks identical, only the Tr 3 layer is gone."""
    a, b = tmp_path / "ocr.pdf", tmp_path / "flattened.pdf"
    doc = _base()
    add_invisible_text(doc)
    _save(doc, a)
    doc = pymupdf.open(a)
    page = doc[0]
    page.add_redact_annot(page.search_for("hidden ocr layer")[0])
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
    _save(doc, b)

    assert losses(_snap(a), _snap(b)) == ["text:page1"]


def _symbol_pdf(path, basefont: str, codes: bytes, encoding: str = "") -> None:
    """A Helvetica line, then ``codes`` shown in ``basefont``, a base-14
    font without /ToUnicode: with ``encoding`` "WinAnsiEncoding" as
    PyMuPDF's insert_text writes it (MuPDF then extracts the raw codes),
    or with its built-in encoding, as Ghostscript rewrites it."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    helv = _new_obj(doc, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")
    enc = f"/Encoding/{encoding}" if encoding else ""
    sym = _new_obj(doc, f"<</Type/Font/Subtype/Type1/BaseFont/{basefont}{enc}>>")
    shown = "".join(f"\\{c:03o}" for c in codes).encode()
    content = _new_stream(doc, b"BT /F1 12 Tf 50 700 Td (Checklist) Tj ET "
                               b"BT /F2 14 Tf 50 650 Td (" + shown + b") Tj ET")
    doc.xref_set_key(page.xref, "Contents", f"{content} 0 R")
    doc.xref_set_key(page.xref, "Resources", f"<</Font<</F1 {helv} 0 R/F2 {sym} 0 R>>>>")
    _save(doc, path)


def _spans(path) -> list[tuple[str, str]]:
    doc = pymupdf.open(path)
    try:
        tp = doc[0].get_textpage(flags=pymupdf.TEXTFLAGS_WORDS)
        return [(s["font"], s["text"]) for b in tp.extractDICT()["blocks"]
                for line in b["lines"] for s in line["spans"]]
    finally:
        doc.close()


def _symbol_text(path, font) -> str:
    return "".join(t for f, t in _spans(path) if f == font)


SYMBOLIC = ["Symbol", "ZapfDingbats"]


@pytest.mark.parametrize("font", SYMBOLIC)
def test_symbolic_glyphs_extracted_as_other_characters_are_not_a_loss(tmp_path, font):
    """Ghostscript rewrites the encoding of the Symbol / ZapfDingbats it
    embeds: the same glyphs are drawn, MuPDF extracts other characters
    (measured: ZapfDingbats "34nlu" came back as "\\x13\\x14GIN")."""
    a, b = tmp_path / "src.pdf", tmp_path / "recoded.pdf"
    _symbol_pdf(a, font, b"34nlu", "WinAnsiEncoding")
    _symbol_pdf(b, font, b"34nlu")
    assert _symbol_text(a, font) == "34nlu", "fixture assumption"
    assert not set(_symbol_text(b, font)) & set("nlu"), "fixture assumption"
    assert losses(_snap(a), _snap(b)) == []
    assert losses(_snap(b), _snap(a)) == []


@pytest.mark.parametrize("font", SYMBOLIC)
def test_symbolic_glyph_extracted_as_whitespace_is_not_a_loss(tmp_path, font):
    """9 of 75 ZapfDingbats glyphs came back under a code MuPDF extracts
    as whitespace; they are still glyphs drawn."""
    a, b = tmp_path / "src.pdf", tmp_path / "recoded.pdf"
    _symbol_pdf(a, font, b"34nlu", "WinAnsiEncoding")
    _symbol_pdf(b, font, b"\x09\x20GIN", "WinAnsiEncoding")
    assert _symbol_text(b, font) == "\t GIN", "fixture assumption"
    assert losses(_snap(a), _snap(b)) == []


@pytest.mark.parametrize("font", SYMBOLIC)
def test_symbolic_glyph_deleted_is_a_loss(tmp_path, font):
    a, b = tmp_path / "src.pdf", tmp_path / "fewer.pdf"
    _symbol_pdf(a, font, b"34nlu", "WinAnsiEncoding")
    _symbol_pdf(b, font, b"34nl")
    assert losses(_snap(a), _snap(b)) == ["text:page1"]
    assert losses(_snap(b), _snap(a)) == []


def test_symbolic_glyphs_count_per_font(tmp_path):
    """Five Symbol glyphs do not stand in for five ZapfDingbats glyphs."""
    a, b = tmp_path / "zapf.pdf", tmp_path / "symbol.pdf"
    _symbol_pdf(a, "ZapfDingbats", b"34nlu")
    _symbol_pdf(b, "Symbol", b"34nlu")
    assert losses(_snap(a), _snap(b)) == ["text:page1"]


def test_plain_text_next_to_symbols_is_still_compared_by_character(tmp_path):
    src, a, b = tmp_path / "src.pdf", tmp_path / "fi.pdf", tmp_path / "nine.pdf"
    _symbol_pdf(src, "ZapfDingbats", b"34nlu")
    for path, word in ((a, "ficheiro"), (b, "9cheiro")):
        doc = pymupdf.open(src)
        doc[0].insert_text((50, 600), word, fontsize=12)
        _save(doc, path)
    assert losses(_snap(a), _snap(b)) == ["text:page1"]


def test_subset_tagged_symbolic_font_is_recognised(tmp_path):
    """Ghostscript's /printer preset writes "JFBHBH+ZapfDingbats"; PyMuPDF
    strips the tag by default, but not when TOOLS asks for it."""
    a, b = tmp_path / "src.pdf", tmp_path / "subset.pdf"
    _symbol_pdf(a, "ZapfDingbats", b"34nlu", "WinAnsiEncoding")
    _symbol_pdf(b, "JFBHBH+ZapfDingbats", b"\x13\x14GIN", "WinAnsiEncoding")
    keep = pymupdf.TOOLS.set_subset_fontnames()
    pymupdf.TOOLS.set_subset_fontnames(True)
    try:
        assert _symbol_text(b, "JFBHBH+ZapfDingbats") == "\x13\x14GIN", "fixture assumption"
        assert losses(_snap(a), _snap(b)) == []
    finally:
        pymupdf.TOOLS.set_subset_fontnames(keep)


def _symbols_only_pdf(path, text_matrix: str) -> None:
    """A /Rotate 180 page whose only text is ZapfDingbats glyphs."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    sym = _new_obj(doc, "<</Type/Font/Subtype/Type1/BaseFont/ZapfDingbats>>")
    content = _new_stream(doc, b"BT /F2 24 Tf " + text_matrix.encode()
                          + b" Tm (34nlu34nlu) Tj ET")
    doc.xref_set_key(page.xref, "Contents", f"{content} 0 R")
    doc.xref_set_key(page.xref, "Resources", f"<</Font<</F2 {sym} 0 R>>>>")
    page.set_rotation(180)
    _save(doc, path)


def test_page_of_symbols_only_turned_upside_down_is_a_rotation_loss(tmp_path):
    """The text direction is weighed over Symbol / ZapfDingbats glyphs too,
    so a page carrying nothing else still has an orientation."""
    a, b = tmp_path / "upright.pdf", tmp_path / "flipped.pdf"
    _symbols_only_pdf(a, "1 0 0 1 100 400")
    _symbols_only_pdf(b, "-1 0 0 -1 495 442")
    sa, sb = _snap(a), _snap(b)
    assert sa.pages[0].chars == frozenset() and sa.pages[0].symbols, "fixture: symbols only"
    assert sa.pages[0].symbols == sb.pages[0].symbols
    assert losses(sa, sb) == ["rotation:page1"]


# ---------------------------------------------------------------------------
# 5. page geometry: compared as displayed
# ---------------------------------------------------------------------------

def _geometry_pdf(path, width, height, *, mediabox=None, cropbox=None,
                  rotate=0, text_rotate=0) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    for k in range(4):
        page.insert_text((120, 200 + 40 * k), f"geometry line {k}", fontsize=14,
                         rotate=text_rotate)
    if mediabox:
        doc.xref_set_key(page.xref, "MediaBox", mediabox)
    if cropbox:
        doc.xref_set_key(page.xref, "CropBox", cropbox)
    if rotate:
        page.set_rotation(rotate)
    _save(doc, path)


def test_mediabox_rounded_to_two_decimals_is_not_a_loss(tmp_path):
    a, b = tmp_path / "pdftex.pdf", tmp_path / "gs.pdf"
    _geometry_pdf(a, 595.2756, 841.8898)
    _geometry_pdf(b, 595.28, 841.89)
    assert losses(_snap(a), _snap(b)) == []
    assert losses(_snap(b), _snap(a)) == []


def test_real_mediabox_change_is_a_loss(tmp_path):
    a, b = tmp_path / "a4.pdf", tmp_path / "letter.pdf"
    _geometry_pdf(a, 595, 842)
    _geometry_pdf(b, 612, 842)
    assert losses(_snap(a), _snap(b)) == ["mediabox:page1"]


def test_mediabox_origin_moved_to_zero_is_not_a_loss(tmp_path):
    a, b = tmp_path / "shifted.pdf", tmp_path / "zero.pdf"
    _geometry_pdf(a, 595, 842, mediabox="[10 20 605 862]")
    _geometry_pdf(b, 595, 842)
    assert losses(_snap(a), _snap(b)) == []


def test_rotation_baked_into_the_content_is_not_a_loss(tmp_path):
    """595x842 /Rotate 90 rewritten as 842x595 /Rotate 0 with the text
    drawn turned: the same page on screen."""
    a, b = tmp_path / "r90.pdf", tmp_path / "baked.pdf"
    _geometry_pdf(a, 595, 842, rotate=90)
    _geometry_pdf(b, 842, 595, text_rotate=270)
    sa, sb = _snap(a), _snap(b)
    assert sa.pages[0].orientation == sb.pages[0].orientation == 1, "fixture assumption"
    assert losses(sa, sb) == [] and losses(sb, sa) == []


def test_crop_with_moved_origin_and_baked_rotation_is_not_a_loss(tmp_path):
    """What Ghostscript's /printer preset writes for an asymmetric crop on
    a /Rotate 90 page with a shifted MediaBox."""
    a, b = tmp_path / "src.pdf", tmp_path / "baked.pdf"
    _geometry_pdf(a, 595, 842, mediabox="[10 20 605 862]", cropbox="[40 70 500 800]",
                  rotate=90)
    _geometry_pdf(b, 842, 595, cropbox="[50 105 780 565]", text_rotate=270)
    sa, sb = _snap(a), _snap(b)
    assert sa.pages[0].cropbox == (50, 30, 62, 105), "fixture assumption"
    assert losses(sa, sb) == [] and losses(sb, sa) == []


def test_crop_window_moved_is_a_loss(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    _geometry_pdf(a, 595, 842, cropbox="[30 50 480 790]")
    _geometry_pdf(b, 595, 842, cropbox="[40 50 490 790]")
    assert losses(_snap(a), _snap(b)) == ["cropbox:page1"]


def test_page_turned_by_auto_rotation_is_one_rotation_loss(tmp_path):
    """Ghostscript's /screen preset turned a 595x842 /Rotate 90 page into
    842x595 /Rotate 270: portrait on screen instead of landscape, crop
    insets permuted. One key, not rotation plus cropbox."""
    a, b = tmp_path / "src.pdf", tmp_path / "turned.pdf"
    _geometry_pdf(a, 595, 842, cropbox="[30 50 480 790]", rotate=90)
    _geometry_pdf(b, 842, 595, cropbox="[52 115 792 565]", rotate=270, text_rotate=270)
    assert losses(_snap(a), _snap(b)) == ["rotation:page1"]


def test_upside_down_page_is_a_rotation_loss(tmp_path):
    """Same size on screen, text upside down: only the text direction
    tells (Ghostscript's /screen preset does this to /Rotate 180 pages)."""
    a, b = tmp_path / "r180.pdf", tmp_path / "flipped.pdf"
    _geometry_pdf(a, 595, 842, rotate=180)
    _geometry_pdf(b, 595, 842, rotate=180, text_rotate=180)
    assert losses(_snap(a), _snap(b)) == ["rotation:page1"]


def test_page_without_text_turned_a_quarter_is_a_rotation_loss(tmp_path):
    """No text to read a direction from: the swapped size alone tells."""
    a, b = tmp_path / "upright.pdf", tmp_path / "turned.pdf"
    for path, rot in ((a, 0), (b, 90)):
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        _gray_image(page, (60, 60, 200, 200))
        if rot:
            page.set_rotation(rot)
        _save(doc, path)
    sa, sb = _snap(a), _snap(b)
    assert sa.pages[0].orientation is None, "fixture assumption: no text"
    assert losses(sa, sb) == ["rotation:page1"]


def test_rotation_of_a_page_without_text_is_judged_by_size_only(tmp_path):
    a, b = tmp_path / "img_r90.pdf", tmp_path / "img_baked.pdf"
    for path, w, h, rot in ((a, 595, 842, 90), (b, 842, 595, 0)):
        doc = pymupdf.open()
        page = doc.new_page(width=w, height=h)
        _gray_image(page, (60, 60, 200, 200))
        if rot:
            page.set_rotation(rot)
        _save(doc, path)
    sa, sb = _snap(a), _snap(b)
    assert sa.pages[0].orientation is None
    assert losses(sa, sb) == []


# ---------------------------------------------------------------------------
# 6. images: placements drawn, not resource entries
# ---------------------------------------------------------------------------

def _images_pdf(path, build) -> None:
    doc = pymupdf.open()
    build(doc)
    _save(doc, path)


def _page_resources(path) -> list[int]:
    doc = pymupdf.open(path)
    try:
        return [len(p.get_images()) for p in doc]
    finally:
        doc.close()


def test_shared_resources_rewritten_per_page_is_not_a_loss(tmp_path):
    """Word-like output: every page lists every image in one shared
    /Resources; Ghostscript gives each page only what it draws."""
    def shared(doc):
        doc.new_page()
        doc.new_page()
        p1, p2 = doc[0], doc[1]   # new_page() unbinds earlier Page objects
        a, b = _image_xobject(doc, 0x40), _image_xobject(doc, 0xC0)
        res = _new_obj(doc, f"<</XObject<</ImA {a} 0 R/ImB {b} 0 R>>>>")
        _draw_images(doc, p1, f"{res} 0 R", ["ImA"])
        _draw_images(doc, p2, f"{res} 0 R", ["ImB"])

    def own(doc):
        doc.new_page()
        doc.new_page()
        p1, p2 = doc[0], doc[1]   # new_page() unbinds earlier Page objects
        a, b = _image_xobject(doc, 0x40), _image_xobject(doc, 0xC0)
        _draw_images(doc, p1, f"<</XObject<</ImA {a} 0 R>>>>", ["ImA"])
        _draw_images(doc, p2, f"<</XObject<</ImB {b} 0 R>>>>", ["ImB"])

    a, b = tmp_path / "shared.pdf", tmp_path / "own.pdf"
    _images_pdf(a, shared)
    _images_pdf(b, own)
    assert _page_resources(a) == [2, 2] and _page_resources(b) == [1, 1], "fixture"
    assert losses(_snap(a), _snap(b)) == []


def test_identical_images_deduplicated_is_not_a_loss(tmp_path):
    def three(doc):
        page = doc.new_page()
        x = [_image_xobject(doc) for _ in range(3)]
        _draw_images(doc, page, f"<</XObject<</I1 {x[0]} 0 R/I2 {x[1]} 0 R/I3 {x[2]} 0 R>>>>",
                     ["I1", "I2", "I3"])

    def one(doc):
        page = doc.new_page()
        x = _image_xobject(doc)
        _draw_images(doc, page, f"<</XObject<</I1 {x} 0 R>>>>", ["I1", "I1", "I1"])

    a, b = tmp_path / "three.pdf", tmp_path / "one.pdf"
    _images_pdf(a, three)
    _images_pdf(b, one)
    assert _page_resources(a) == [3] and _page_resources(b) == [1], "fixture"
    sa, sb = _snap(a), _snap(b)
    assert sa.pages[0].images == sb.pages[0].images == 3
    assert losses(sa, sb) == []


def test_image_in_resources_but_never_drawn_is_not_a_loss(tmp_path):
    def unused(doc):
        page = doc.new_page()
        a, b = _image_xobject(doc, 0x40), _image_xobject(doc, 0xC0)
        _draw_images(doc, page, f"<</XObject<</ImA {a} 0 R/ImB {b} 0 R>>>>", ["ImA"])

    def pruned(doc):
        page = doc.new_page()
        a = _image_xobject(doc, 0x40)
        _draw_images(doc, page, f"<</XObject<</ImA {a} 0 R>>>>", ["ImA"])

    a, b = tmp_path / "unused.pdf", tmp_path / "pruned.pdf"
    _images_pdf(a, unused)
    _images_pdf(b, pruned)
    assert _page_resources(a) == [2], "fixture"
    assert losses(_snap(a), _snap(b)) == []


def test_one_placement_of_a_drawn_image_removed_is_a_loss(tmp_path):
    """The resource count does not move; only the placements tell."""
    def twice(doc):
        page = doc.new_page()
        x = _image_xobject(doc)
        _draw_images(doc, page, f"<</XObject<</I1 {x} 0 R>>>>", ["I1", "I1"])

    def once(doc):
        page = doc.new_page()
        x = _image_xobject(doc)
        _draw_images(doc, page, f"<</XObject<</I1 {x} 0 R>>>>", ["I1"])

    a, b = tmp_path / "twice.pdf", tmp_path / "once.pdf"
    _images_pdf(a, twice)
    _images_pdf(b, once)
    assert _page_resources(a) == _page_resources(b) == [1], "fixture"
    assert losses(_snap(a), _snap(b)) == ["images:page1"]


def _placements_pdf(path, matrices) -> None:
    """One image drawn once per matrix ("a b c d e f")."""
    def build(doc):
        page = doc.new_page()
        x = _image_xobject(doc)
        ops = b"".join(b"q %s cm /I1 Do Q\n" % m.encode() for m in matrices)
        doc.xref_set_key(page.xref, "Contents", f"{_new_stream(doc, ops)} 0 R")
        doc.xref_set_key(page.xref, "Resources", f"<</XObject<</I1 {x} 0 R>>>>")
    _images_pdf(path, build)


@pytest.mark.parametrize("degenerate", ["0 0 0 80 100 300", "80 0 0 0 100 300",
                                        "1 1 1 1 100 300"])
def test_zero_area_placement_dropped_is_not_a_loss(tmp_path, degenerate):
    """Ghostscript drops a placement that draws nothing (measured on a
    zero-width one). The last matrix is degenerate with a non-empty bbox."""
    a, b = tmp_path / "with.pdf", tmp_path / "without.pdf"
    _placements_pdf(a, [degenerate, "80 0 0 80 300 300"])
    _placements_pdf(b, ["80 0 0 80 300 300"])
    doc = pymupdf.open(a)
    try:
        assert len(doc[0].get_image_info()) == 2, "fixture: MuPDF lists both placements"
    finally:
        doc.close()
    sa, sb = _snap(a), _snap(b)
    assert sa.pages[0].images == sb.pages[0].images == 1
    assert losses(sa, sb) == []


def test_visible_placement_next_to_a_zero_area_one_is_still_counted(tmp_path):
    a, b = tmp_path / "with.pdf", tmp_path / "only_degenerate.pdf"
    _placements_pdf(a, ["0 0 0 80 100 300", "80 0 0 80 300 300"])
    _placements_pdf(b, ["0 0 0 80 100 300"])
    assert losses(_snap(a), _snap(b)) == ["images:page1"]


def test_tiny_placement_removed_is_a_loss(tmp_path):
    """Half a point square still draws: the area threshold only absorbs
    float noise in a degenerate matrix."""
    a, b = tmp_path / "with.pdf", tmp_path / "without.pdf"
    _placements_pdf(a, ["0.5 0 0 0.5 100 300", "80 0 0 80 300 300"])
    _placements_pdf(b, ["80 0 0 80 300 300"])
    assert losses(_snap(a), _snap(b)) == ["images:page1"]


def _alpha_placements_pdf(path, draws, mask=False) -> None:
    """One image (or stencil mask) drawn once per (matrix, fill alpha)."""
    def build(doc):
        page = doc.new_page()
        if mask:
            x = _new_stream(doc, b"\xaa" * 8, "/Type/XObject/Subtype/Image/Width 8/Height 8"
                                              "/ImageMask true/BitsPerComponent 1")
        else:
            x = _image_xobject(doc)
        alphas = sorted({ca for _m, ca in draws})
        states = "".join(f"/A{i}<</ca {ca}>>" for i, ca in enumerate(alphas))
        ops = b"".join(b"q /A%d gs %s cm /I1 Do Q\n" % (alphas.index(ca), m.encode())
                       for m, ca in draws)
        doc.xref_set_key(page.xref, "Contents", f"{_new_stream(doc, ops)} 0 R")
        doc.xref_set_key(page.xref, "Resources",
                         f"<</XObject<</I1 {x} 0 R>>/ExtGState<<{states}>>>>")
    _images_pdf(path, build)


@pytest.mark.parametrize("ca", ["0.3", "0.49", "0"])
def test_image_under_low_fill_alpha_removed_is_a_loss(tmp_path, ca):
    """A semi-transparent watermark or logo. MuPDF's own image list
    (get_image_info) leaves out every image drawn with a fill alpha under
    0.5; Ghostscript keeps such an image, alpha 0 included (measured)."""
    a, b = tmp_path / "with.pdf", tmp_path / "without.pdf"
    _alpha_placements_pdf(a, [("80 0 0 80 100 300", ca), ("80 0 0 80 300 300", "1")])
    _alpha_placements_pdf(b, [("80 0 0 80 300 300", "1")])
    doc = pymupdf.open(a)
    try:
        assert len(doc[0].get_image_info()) == 1, "fixture: MuPDF's image list misses it"
    finally:
        doc.close()
    assert losses(_snap(a), _snap(b)) == ["images:page1"]
    assert losses(_snap(b), _snap(a)) == []


def test_stencil_mask_placement_removed_is_a_loss(tmp_path):
    """An /ImageMask image is drawn through a different device call."""
    a, b = tmp_path / "with.pdf", tmp_path / "without.pdf"
    _alpha_placements_pdf(a, [("80 0 0 80 100 300", "1"), ("80 0 0 80 300 300", "1")],
                          mask=True)
    _alpha_placements_pdf(b, [("80 0 0 80 300 300", "1")], mask=True)
    assert _snap(a).pages[0].images == 2
    assert losses(_snap(a), _snap(b)) == ["images:page1"]


def test_snapshot_never_extracts_image_payloads(tmp_path, monkeypatch):
    """Counting placements must not make MuPDF hand back the images: with
    TEXT_PRESERVE_IMAGES, extractDICT re-encodes every non-JPEG image as
    PNG (49 s for a 300-page 300 dpi Flate scan)."""
    path = tmp_path / "img.pdf"
    doc = _base()
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 300, 300), 0)
    doc[0].insert_image(pymupdf.Rect(100, 100, 400, 400), pixmap=pix)
    _save(doc, path)
    real = pymupdf.TextPage.extractDICT
    image_blocks = []

    def spy(self, *args, **kwargs):
        out = real(self, *args, **kwargs)
        image_blocks.extend(b for b in out["blocks"] if b["type"] == 1)
        return out

    monkeypatch.setattr(pymupdf.TextPage, "extractDICT", spy)
    s = _snap(path)
    assert s.pages[0].images == 1
    assert image_blocks == [], "extractDICT returned encoded image blocks"


# ---------------------------------------------------------------------------
# 7. links, outline, layers, /Info, file annotations
# ---------------------------------------------------------------------------

def _named_links_pdf(path) -> None:
    """Page 2 links to named destinations on pages 1 and 3."""
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    dests = _new_obj(doc, f"<</Names[(chap0)[{doc[0].xref} 0 R/XYZ 0 0 0]"
                          f"(chap2)[{doc[2].xref} 0 R/Fit]]>>")
    doc.xref_set_key(doc.pdf_catalog(), "Names", f"<</Dests {dests} 0 R>>")
    for i, name in enumerate(("chap0", "chap2")):
        link = _new_obj(doc, f"<</Type/Annot/Subtype/Link/Rect[10 {10 + 30 * i} 100 {30 + 30 * i}]"
                             f"/A<</S/GoTo/D({name})>>>>")
        _append_annot(doc, doc[1], link)
    _save(doc, path)


def _goto_links_pdf(path, targets=(0, 2)) -> None:
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    for i, target in enumerate(targets):
        doc[1].insert_link({"kind": pymupdf.LINK_GOTO, "page": target,
                            "to": pymupdf.Point(0, 0),
                            "from": pymupdf.Rect(10, 10 + 30 * i, 100, 30 + 30 * i)})
    _save(doc, path)


def test_named_destination_resolved_to_a_page_link_is_not_a_loss(tmp_path):
    a, b = tmp_path / "named.pdf", tmp_path / "goto.pdf"
    _named_links_pdf(a)
    _goto_links_pdf(b)
    doc = pymupdf.open(a)
    try:
        kinds = sorted((lk["kind"], lk["page"]) for lk in doc[1].get_links())
    finally:
        doc.close()
    assert kinds == [(pymupdf.LINK_NAMED, 0), (pymupdf.LINK_NAMED, 2)], "fixture"
    assert losses(_snap(a), _snap(b)) == []
    assert losses(_snap(b), _snap(a)) == []


def test_link_to_another_page_is_a_loss(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    _goto_links_pdf(a, targets=(0, 2))
    _goto_links_pdf(b, targets=(0, 1))
    assert losses(_snap(a), _snap(b)) == ["links:page2"]


def test_link_to_another_uri_is_a_loss(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    for path, uri in ((a, "https://pdf-apps.com/a"), (b, "https://example.com/a")):
        doc = _base()
        doc[0].insert_link({"kind": pymupdf.LINK_URI, "uri": uri,
                            "from": pymupdf.Rect(50, 500, 300, 520)})
        _save(doc, path)
    assert losses(_snap(a), _snap(b)) == ["links:page1"]


def test_outline_entry_pointing_elsewhere_is_a_loss(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    for path, page in ((a, 2), (b, 1)):
        doc = _base()
        doc.set_toc([[1, "Chapter", page]])
        _save(doc, path)
    assert losses(_snap(a), _snap(b)) == ["outline"]


def test_one_of_two_layers_with_the_same_name_removed_is_a_loss(tmp_path):
    a, b = tmp_path / "two.pdf", tmp_path / "one.pdf"
    doc = _base()
    doc.add_ocg("Twin", on=True)
    doc.add_ocg("Twin", on=True)
    _save(doc, a)
    doc = pymupdf.open(a)
    keep = next(iter(doc.get_ocgs()))
    cat = doc.pdf_catalog()
    doc.xref_set_key(cat, "OCProperties/OCGs", f"[{keep} 0 R]")
    doc.xref_set_key(cat, "OCProperties/D/ON", f"[{keep} 0 R]")
    doc.xref_set_key(cat, "OCProperties/D/Order", f"[{keep} 0 R]")
    _save(doc, b, garbage=4)
    doc = pymupdf.open(b)
    try:
        assert [v["name"] for v in doc.get_ocgs().values()] == ["Twin"], "fixture"
    finally:
        doc.close()
    assert losses(_snap(a), _snap(b)) == ["ocg:Twin"]


def test_info_value_replaced_is_a_loss(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    for path, title in ((a, "A"), (b, "B")):
        doc = _base()
        doc.set_metadata({"title": title})
        _save(doc, path)
    assert losses(_snap(a), _snap(b)) == ["info:title"]


def test_mod_date_is_not_compared(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    for path, date in ((a, "D:20200101000000Z"), (b, "D:20261016000000Z")):
        doc = _base()
        doc.set_metadata({"modDate": date})
        _save(doc, path)
    assert losses(_snap(a), _snap(b)) == []


def test_file_annotation_deleted_reports_it_and_its_popup(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    doc = _base()
    add_file_annot(doc)
    _save(doc, a)
    doc = pymupdf.open(a)
    page = doc[0]
    page.delete_annot(next(page.annots(types=(pymupdf.PDF_ANNOT_FILE_ATTACHMENT,))))
    _save(doc, b)
    assert losses(_snap(a), _snap(b)) == ["file_annot:page1", "popups:page1"]


def test_open_action_target_is_judged_by_page_number_not_page_content(tmp_path):
    """Compression rewrites the target page itself (images, resources);
    the open action still lands on the same page."""
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    doc = _base()
    _add_catalog("OpenAction", _open_at_page2)(doc)
    _save(doc, a)
    doc = pymupdf.open(a)
    _gray_image(doc[1], (300, 300, 400, 400))
    _save(doc, b, garbage=4)
    assert losses(_snap(a), _snap(b)) == []


def test_goto_open_action_rewritten_as_a_plain_destination_is_not_a_loss(tmp_path):
    """Ghostscript writes <</S/GoTo/D[p /Fit]>> as [p /Fit] (measured on
    GS9_Color_Management.pdf, Ghostscript.pdf and ghostpdl.pdf)."""
    a, b, c = tmp_path / "action.pdf", tmp_path / "dest.pdf", tmp_path / "other.pdf"
    for path, value in ((a, lambda d: f"<</S/GoTo/D[{d[1].xref} 0 R/Fit]>>"),
                        (b, _open_at_page2),
                        (c, lambda d: f"<</S/GoTo/D[{d[0].xref} 0 R/Fit]>>")):
        doc = _base()
        _add_catalog("OpenAction", value)(doc)
        _save(doc, path)
    assert losses(_snap(a), _snap(b)) == [] and losses(_snap(b), _snap(a)) == []
    assert losses(_snap(c), _snap(b)) == ["catalog:OpenAction"]


def _named_open_action(path, open_action, n_pages=3) -> None:
    """Page 2 is named "chap" in the /Names /Dests tree."""
    doc = _base()
    for _ in range(n_pages - 2):
        doc.new_page()
    names = _new_obj(doc, f"<</Names[(chap)[{doc[1].xref} 0 R/XYZ 0 700 0]]>>")
    doc.xref_set_key(doc.pdf_catalog(), "Names", f"<</Dests {names} 0 R>>")
    if open_action is not None:
        doc.xref_set_key(doc.pdf_catalog(), "OpenAction", open_action(doc))
    _save(doc, path)


def _explicit(page_index, view="/XYZ 0 700 0"):
    return lambda d: f"[{d[page_index].xref} 0 R{view}]"


def test_named_open_action_resolved_to_its_destination_is_not_a_loss(tmp_path):
    """Ghostscript 10.05 writes <</S/GoTo/D(chap)>> as the array "chap"
    names: [p2 /XYZ 0 700 0]."""
    a, b = tmp_path / "named.pdf", tmp_path / "resolved.pdf"
    _named_open_action(a, lambda d: "<</S/GoTo/D(chap)>>")
    _named_open_action(b, _explicit(1))
    assert losses(_snap(a), _snap(b)) == []
    assert losses(_snap(b), _snap(a)) == []


def test_named_open_action_dropped_is_still_a_loss(tmp_path):
    """Ghostscript 10.05 drops <</S/GoTo/D/chap>> (catalog /Dests)."""
    a, b = tmp_path / "named.pdf", tmp_path / "dropped.pdf"
    _named_open_action(a, lambda d: "<</S/GoTo/D(chap)>>")
    _named_open_action(b, None)
    assert losses(_snap(a), _snap(b)) == ["catalog:OpenAction"]


@pytest.mark.parametrize("elsewhere", [_explicit(2), _explicit(1, "/Fit")],
                         ids=["other-page", "other-view"])
def test_named_open_action_to_another_destination_is_a_loss(tmp_path, elsewhere):
    a, b = tmp_path / "named.pdf", tmp_path / "elsewhere.pdf"
    _named_open_action(a, lambda d: "<</S/GoTo/D(chap)>>")
    _named_open_action(b, elsewhere)
    assert losses(_snap(a), _snap(b)) == ["catalog:OpenAction"]


def test_named_open_action_that_names_nothing_is_kept_as_a_name(tmp_path):
    a, b = tmp_path / "dangling.pdf", tmp_path / "resolved.pdf"
    _named_open_action(a, lambda d: "<</S/GoTo/D(nowhere)>>")
    _named_open_action(b, _explicit(1))
    assert losses(_snap(a), _snap(b)) == ["catalog:OpenAction"]


def test_named_open_action_through_an_indirect_action(tmp_path):
    a, b = tmp_path / "named.pdf", tmp_path / "resolved.pdf"
    _named_open_action(a, lambda d: f"{_new_obj(d, '<</S/GoTo/D(chap)>>')} 0 R")
    _named_open_action(b, _explicit(1))
    assert losses(_snap(a), _snap(b)) == []


def test_named_open_action_whose_name_is_an_indirect_string(tmp_path):
    """<</S/GoTo/D 9 0 R>> with 9 0 obj (chap): Ghostscript 10.05 writes the
    array "chap" names, as for a direct string."""
    a, b, c = tmp_path / "indirect.pdf", tmp_path / "resolved.pdf", tmp_path / "other.pdf"
    _named_open_action(a, lambda d: f"<</S/GoTo/D {_new_obj(d, '(chap)')} 0 R>>")
    _named_open_action(b, _explicit(1))
    _named_open_action(c, _explicit(2))
    assert losses(_snap(a), _snap(b)) == []
    assert losses(_snap(a), _snap(c)) == ["catalog:OpenAction"]


def test_named_open_action_in_a_kids_node_with_a_d_dictionary(tmp_path):
    """The name tree split into /Kids, the value an indirect <</D [...]>>."""
    a, b, c = tmp_path / "kids.pdf", tmp_path / "resolved.pdf", tmp_path / "other.pdf"
    doc = _base()
    doc.new_page()
    dest = _new_obj(doc, f"<</D[{doc[2].xref} 0 R/Fit]>>")
    leaf = _new_obj(doc, f"<</Limits[(alpha)(zeta)]/Names[(alpha)[{doc[0].xref} 0 R/Fit]"
                         f"(zeta) {dest} 0 R]>>")
    root = _new_obj(doc, f"<</Kids[{leaf} 0 R]>>")
    doc.xref_set_key(doc.pdf_catalog(), "Names", f"<</Dests {root} 0 R>>")
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction", "<</S/GoTo/D(zeta)>>")
    _save(doc, a)
    for path, page in ((b, 2), (c, 0)):
        doc = _base()
        doc.new_page()
        _add_catalog("OpenAction", _explicit(page, "/Fit"))(doc)
        _save(doc, path)
    assert losses(_snap(a), _snap(b)) == []
    assert losses(_snap(a), _snap(c)) == ["catalog:OpenAction"]


def test_named_open_action_with_a_utf16_name(tmp_path):
    """The name as a hex UTF-16 string, matched byte for byte."""
    a, b = tmp_path / "hex.pdf", tmp_path / "resolved.pdf"
    doc = _base()
    doc.xref_set_key(doc.pdf_catalog(), "Names",
                     f"<</Dests<</Names[<FEFF00E9>[{doc[1].xref} 0 R/Fit]]>>>>")
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction", "<</S/GoTo/D<FEFF00E9>>>")
    _save(doc, a)
    doc = _base()
    _add_catalog("OpenAction", _explicit(1, "/Fit"))(doc)
    _save(doc, b)
    assert losses(_snap(a), _snap(b)) == []


def _tree_open_action(path, tree, name="(chap)") -> None:
    """Three pages; ``tree(doc)`` returns the /Names /Dests root, and the
    /OpenAction is <</S/GoTo/D name>>."""
    doc = _base()
    doc.new_page()
    doc.xref_set_key(doc.pdf_catalog(), "Names", f"<</Dests {tree(doc)}>>")
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction", f"<</S/GoTo/D{name}>>")
    _save(doc, path)


def _explicit_pdf(path, page_index) -> None:
    doc = _base()
    doc.new_page()
    _add_catalog("OpenAction", _explicit(page_index, "/Fit"))(doc)
    _save(doc, path)


def test_named_open_action_through_indirect_names_and_kids_arrays(tmp_path):
    """/Kids and /Names may each be an indirect array."""
    def tree(doc):
        names = _new_obj(doc, f"[(chap)[{doc[2].xref} 0 R/Fit]]")
        leaf = _new_obj(doc, f"<</Limits[(chap)(chap)]/Names {names} 0 R>>")
        kids = _new_obj(doc, f"[{leaf} 0 R]")
        return f"{_new_obj(doc, f'<</Kids {kids} 0 R>>')} 0 R"

    a, b, c = tmp_path / "tree.pdf", tmp_path / "resolved.pdf", tmp_path / "other.pdf"
    _tree_open_action(a, tree)
    _explicit_pdf(b, 2)
    _explicit_pdf(c, 0)
    assert losses(_snap(a), _snap(b)) == []
    assert losses(_snap(a), _snap(c)) == ["catalog:OpenAction"]


def test_name_tree_with_a_kids_cycle_ends(tmp_path):
    """Two nodes whose /Kids point at each other, and a name in neither: the
    walk visits each node once. should_cancel is the watchdog: the walk
    polls it, so a walk that never ends fails here instead of hanging."""
    def tree(doc):
        x, y = doc.get_new_xref(), doc.get_new_xref()
        doc.update_object(x, f"<</Kids[{y} 0 R]>>")
        doc.update_object(y, f"<</Kids[{x} 0 R]/Names[(other)[{doc[2].xref} 0 R/Fit]]>>")
        return f"<</Kids[{x} 0 R]>>"

    polls = []

    def watchdog():
        polls.append(1)
        if len(polls) > 100:
            raise AssertionError("the name tree walk does not end")
        return False

    a, b = tmp_path / "cycle.pdf", tmp_path / "resolved.pdf"
    _tree_open_action(a, tree)
    _explicit_pdf(b, 2)
    doc = pymupdf.open(a)
    try:
        cyclic = snapshot(doc, should_cancel=watchdog)
    finally:
        doc.close()
    assert losses(cyclic, _snap(b)) == ["catalog:OpenAction"]


def test_name_open_action_resolved_through_catalog_dests(tmp_path):
    """<</S/GoTo/D/chap>> with a catalog /Dests dictionary: resolved to
    its array like a string name is (Ghostscript 10.05 drops it, which the
    dropped test above covers)."""
    a, b, c = tmp_path / "name.pdf", tmp_path / "resolved.pdf", tmp_path / "other.pdf"
    doc = _base()
    doc.xref_set_key(doc.pdf_catalog(), "Dests", f"<</chap[{doc[1].xref} 0 R/Fit]>>")
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction", "<</S/GoTo/D/chap>>")
    _save(doc, a)
    for path, page in ((b, 1), (c, 0)):
        doc = _base()
        _add_catalog("OpenAction", _explicit(page, "/Fit"))(doc)
        _save(doc, path)
    assert losses(_snap(a), _snap(b)) == []
    assert losses(_snap(a), _snap(c)) == ["catalog:OpenAction"]


def test_indirect_destination_array_is_compared_inline(tmp_path):
    a, b = tmp_path / "indirect.pdf", tmp_path / "inline.pdf"
    doc = _base()
    _add_catalog("OpenAction", lambda d: f"{_new_obj(d, f'[{d[1].xref} 0 R/Fit]')} 0 R")(doc)
    _save(doc, a)
    doc = _base()
    _add_catalog("OpenAction", _explicit(1, "/Fit"))(doc)
    _save(doc, b)
    assert losses(_snap(a), _snap(b)) == [] and losses(_snap(b), _snap(a)) == []


def _contents_pdf(path, kind, contents: str, indirect: bool) -> None:
    """One annotation of ``kind`` whose /Contents is the PDF string
    ``contents``, direct or as an indirect object."""
    doc = _base()
    page = doc[0]
    if kind == "text":
        annot = page.add_text_annot((100, 200), "placeholder")
    elif kind == "file":
        annot = page.add_file_annot((100, 200), b"payload", "p.txt")
    else:
        annot = page.add_highlight_annot(pymupdf.Rect(48, 60, 200, 80))
    value = f"{_new_obj(doc, contents)} 0 R" if indirect else contents
    doc.xref_set_key(annot.xref, "Contents", value)
    _save(doc, path)


@pytest.mark.parametrize("kind", ["text", "file", "highlight"])
def test_indirect_contents_inlined_is_not_a_loss(tmp_path, kind):
    """Ghostscript writes an indirect /Contents inline (measured on a Text
    and a FileAttachment annotation)."""
    a, b = tmp_path / "indirect.pdf", tmp_path / "inline.pdf"
    _contents_pdf(a, kind, "(same comment)", indirect=True)
    _contents_pdf(b, kind, "(same comment)", indirect=False)
    assert losses(_snap(a), _snap(b)) == []
    assert losses(_snap(b), _snap(a)) == []


def test_indirect_contents_is_compared_by_text_not_encoding(tmp_path):
    """UTF-16 indirect, PDFDocEncoding inline: the same text."""
    a, b = tmp_path / "utf16.pdf", tmp_path / "pdfdoc.pdf"
    _contents_pdf(a, "highlight", "<FEFF00630061006600E9>", indirect=True)
    _contents_pdf(b, "highlight", r"(caf\351)", indirect=False)
    assert losses(_snap(a), _snap(b)) == [] and losses(_snap(b), _snap(a)) == []


def test_indirect_contents_changed_is_a_loss(tmp_path):
    a, b = tmp_path / "indirect.pdf", tmp_path / "other.pdf"
    _contents_pdf(a, "highlight", "(reviewer remark)", indirect=True)
    _contents_pdf(b, "highlight", "(another remark)", indirect=False)
    assert losses(_snap(a), _snap(b)) == ["annots:page1"]


def _info_pdf(path, entries: str = "") -> None:
    doc = _base()
    doc.set_metadata({"title": "T"})
    if entries:
        _set_info_raw(doc, entries)
    _save(doc, path)


def test_custom_info_key_dropped_is_a_loss(tmp_path):
    """Ghostscript 10.05 keeps only the standard /Info keys."""
    a, b = tmp_path / "custom.pdf", tmp_path / "dropped.pdf"
    _info_pdf(a, "/Company(ACME Lda)/SourceRef(DOC-0042)")
    _info_pdf(b)
    assert losses(_snap(a), _snap(b)) == ["info:Company", "info:SourceRef"]
    assert losses(_snap(b), _snap(a)) == []


@pytest.mark.parametrize("before, after, key", [
    ("/Company(ACME Lda)", "/Company(Other Lda)", "info:Company"),
    ("/Trapped/True", "", "info:Trapped"),
    ("/Trapped/True", "/Trapped(/True)", "info:Trapped"),
    ("/Odd#20Key(spaced)", "", "info:Odd#20Key"),
    ("/Caf#C3#A9(utf8 name)", "", "info:Caf#C3#A9"),
    ("/title(custom lower-case title)", "", "info:#74itle"),
], ids=["value", "name-value", "name-to-string", "escaped-space", "non-ascii", "collision"])
def test_custom_info_key_lost(tmp_path, before, after, key):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    _info_pdf(a, before)
    _info_pdf(b, after)
    assert losses(_snap(a), _snap(b)) == [key]


def test_serialised_object_splits_into_its_top_level_elements():
    """MuPDF's compact form: escaped parentheses inside a literal string,
    nested arrays and dictionaries, references, hex strings."""
    src = r"<</A(x\)y \(z)/B[1 0 R(q)[2]]/C<</D 2>>/E<FEFF00E9>/F 3 0 R/G -1.5>>"
    assert pdf_preserve._elements(src) == [
        "/A", r"(x\)y \(z)", "/B", "[1 0 R(q)[2]]", "/C", "<</D 2>>",
        "/E", "<FEFF00E9>", "/F", "3 0 R", "/G", "-1.5"]
    assert pdf_preserve._entries("[1 2]") == {}


def test_custom_info_value_inlined_or_empty_is_not_a_loss(tmp_path):
    a, b = tmp_path / "indirect.pdf", tmp_path / "inline.pdf"
    doc = _base()
    doc.set_metadata({"title": "T"})
    _set_info_raw(doc, f"/Company {_new_obj(doc, '<FEFF00410043004D0045>')} 0 R/Empty()")
    _save(doc, a)
    _info_pdf(b, "/Company(ACME)")
    sa = _snap(a)
    assert ("Company", "string:ACME") in sa.info and "Empty" not in dict(sa.info)
    assert losses(sa, _snap(b)) == [] and losses(_snap(b), sa) == []


def test_strings_are_decoded_in_one_scratch_document(tmp_path, monkeypatch):
    """Indirect strings are decoded in a scratch in-memory Document: one per
    snapshot, opened on first use and closed at the end, not one each."""
    path = tmp_path / "strings.pdf"
    doc = _base()
    doc.set_metadata({"title": "T"})
    _set_info_raw(doc, "".join(f"/K{i} {_new_obj(doc, f'(value {i})')} 0 R" for i in range(5)))
    _save(doc, path)
    src = pymupdf.open(path)
    opened = []
    real_open = pymupdf.open

    def counting_open(*args, **kwargs):
        scratch = real_open(*args, **kwargs)
        opened.append(scratch)
        return scratch

    monkeypatch.setattr(pymupdf, "open", counting_open)
    try:
        s = snapshot(src)
    finally:
        src.close()
    assert ("K4", "string:value 4") in s.info
    assert len(opened) == 1 and opened[0].is_closed


def test_custom_info_keys_follow_the_standard_ones_in_name_order(tmp_path):
    path = tmp_path / "order.pdf"
    _info_pdf(path, "/Zeta(z)/Alpha(a)")
    keys = [k for k, _v in _snap(path).info]
    assert keys == [*pdf_preserve._INFO_KEYS, "Alpha", "Zeta"]


def _dangling(doc) -> str:
    return f"{doc.xref_length() + 999} 0 R"


def _set_catalog_raw(doc, entries: str) -> None:
    cat = doc.pdf_catalog()
    doc.update_object(cat, doc.xref_object(cat, compressed=True)[:-2] + entries + ">>")


def _set_page_raw(doc, entries: str) -> None:
    page = doc[0].xref
    doc.update_object(page, doc.xref_object(page, compressed=True)[:-2] + entries + ">>")


# (id, addition, rewrite): rewrite is the garbage level of a re-save of the
# original, or None for a copy built without the addition.
DANGLING = [
    ("info-dangling", lambda d: _set_info_raw(d, f"/Bar {_dangling(d)}"), 4),
    ("info-free-object", lambda d: _set_info_raw(d, f"/Bar {d.get_new_xref()} 0 R"), 4),
    ("info-null", lambda d: _set_info_raw(d, "/Foo null"), None),
    ("catalog-dangling-gc1", lambda d: _set_catalog_raw(d, f"/ViewerPreferences {_dangling(d)}"),
     1),
    ("catalog-dangling-gc4", lambda d: _set_catalog_raw(d, f"/ViewerPreferences {_dangling(d)}"),
     4),
    ("catalog-free-object", lambda d: _set_catalog_raw(d, f"/Lang {d.get_new_xref()} 0 R"), 4),
    ("catalog-null", lambda d: _set_catalog_raw(d, "/PageMode null"), None),
    ("nested-dangling", lambda d: _set_catalog_raw(
        d, f"/ViewerPreferences<</Direction/R2L/Extra {_dangling(d)}>>"), 4),
    ("struct-tree-dangling", lambda d: _set_catalog_raw(d, f"/StructTreeRoot {_dangling(d)}"), 4),
    ("struct-tree-free-object",
     lambda d: _set_catalog_raw(d, f"/StructTreeRoot {d.get_new_xref()} 0 R"), 4),
    ("mark-info-dangling", lambda d: _set_catalog_raw(d, f"/MarkInfo {_dangling(d)}"), 4),
    ("thumbnail-dangling", lambda d: _set_page_raw(d, f"/Thumb {_dangling(d)}"), 4),
]


@pytest.mark.parametrize("add, rewrite", [c[1:] for c in DANGLING],
                         ids=[c[0] for c in DANGLING])
def test_dangling_or_null_entry_collected_is_not_a_loss(tmp_path, add, rewrite):
    """ISO 32000: a reference to an object that does not exist is null, and
    a null entry is the same as no entry. MuPDF's garbage collection writes
    such a reference as null (measured, among others, on a catalog
    /ViewerPreferences 99999 0 R in the compress tool's Pass B)."""
    a, b = tmp_path / "original.pdf", tmp_path / "rewritten.pdf"
    doc = _base()
    doc.set_metadata({"title": "T"})
    add(doc)
    _save(doc, a)
    if rewrite is None:
        doc = _base()
        doc.set_metadata({"title": "T"})
        _save(doc, b)
    else:
        doc = pymupdf.open(a)
        _save(doc, b, garbage=rewrite)
    assert losses(_snap(a), _snap(b)) == []
    assert losses(_snap(b), _snap(a)) == []


def test_entry_pointing_to_an_existing_object_is_still_a_loss(tmp_path):
    """The other side of the null rule: a reference that resolves is a
    value, and losing it is a loss."""
    a, b = tmp_path / "original.pdf", tmp_path / "dropped.pdf"
    doc = _base()
    doc.set_metadata({"title": "T"})
    _set_info_raw(doc, f"/Bar {_new_obj(doc, '5')} 0 R")
    _set_catalog_raw(doc, f"/ViewerPreferences {_new_obj(doc, '<</Direction/R2L>>')} 0 R")
    _set_page_raw(doc, f"/Thumb {_image_xobject(doc)} 0 R")
    _save(doc, a)
    doc = _base()
    doc.set_metadata({"title": "T"})
    _save(doc, b)
    assert losses(_snap(a), _snap(b)) == [
        "thumbnail:page1", "info:Bar", "catalog:ViewerPreferences"]


# (key, value, inner, other): the /Info entry /key ``value``, with
# ``inner`` either stored as its own object or written in line; ``other``
# in line instead is a different value.
INDIRECT_INFO = [
    ("Count", "{}", "5", "6"),
    ("Arr", "{}", "[1 (two) /Three]", "[/Three (two) 1]"),
    ("Dict", "{}", "<</K 1/L(x)>>", "<</K 1/L(y)>>"),
    ("Nested", "[{} 7]", "<</K 1>>", "<</K 2>>"),
]


@pytest.mark.parametrize("key, value, inner, other", INDIRECT_INFO,
                         ids=["number", "array", "dict", "nested"])
def test_info_value_direct_or_indirect_is_not_a_loss(tmp_path, key, value, inner, other):
    paths = [tmp_path / f"{n}.pdf" for n in ("indirect", "inline", "other")]
    for path, part, indirect in zip(paths, (inner, inner, other), (True, False, False),
                                    strict=True):
        doc = _base()
        doc.set_metadata({"title": "T"})
        entry = value.format(f"{_new_obj(doc, part)} 0 R" if indirect else part)
        _set_info_raw(doc, f"/{key} {entry}")
        _save(doc, path)
    indirect, inline, changed = (_snap(p) for p in paths)
    assert losses(indirect, inline) == [] and losses(inline, indirect) == []
    assert losses(indirect, changed) == [f"info:{key}"]


VIEWER_PREFS = "<</DisplayDocTitle true/Direction/R2L>>"
INTENT = "<</Type/OutputIntent/S/GTS_PDFA1/OutputConditionIdentifier(sRGB)/DestOutputProfile {}>>"


def _catalog_value_pdf(path, key: str, build) -> None:
    doc = _base()
    doc.xref_set_key(doc.pdf_catalog(), key, build(doc))
    _save(doc, path)


def _icc(doc) -> str:
    return f"{_new_stream(doc, b'not really an ICC profile', '/N 3')} 0 R"


CATALOG_FORMS = {
    "ViewerPreferences": [
        lambda d: VIEWER_PREFS,
        lambda d: f"{_new_obj(d, VIEWER_PREFS)} 0 R",
        lambda d: "<</Direction/R2L/DisplayDocTitle true>>",
    ],
    "OutputIntents": [
        lambda d: "[" + INTENT.format(_icc(d)) + "]",
        lambda d: f"{_new_obj(d, '[' + INTENT.format(_icc(d)) + ']')} 0 R",
        lambda d: f"[{_new_obj(d, INTENT.format(_icc(d)))} 0 R]",
    ],
}


@pytest.mark.parametrize("key", list(CATALOG_FORMS))
def test_catalog_value_direct_indirect_or_reordered_is_not_a_loss(tmp_path, key):
    """The same content written in line, as its own object, with an inner
    dictionary as its own object, or with its keys in another order."""
    snaps = []
    for i, build in enumerate(CATALOG_FORMS[key]):
        path = tmp_path / f"form{i}.pdf"
        _catalog_value_pdf(path, key, build)
        snaps.append(_snap(path))
    for x in snaps:
        for y in snaps:
            assert losses(x, y) == []


def test_null_entry_inside_a_value_is_the_same_as_none(tmp_path):
    a, b = tmp_path / "null.pdf", tmp_path / "absent.pdf"
    _catalog_value_pdf(a, "ViewerPreferences", lambda d: "<</Direction/R2L/Extra null>>")
    _catalog_value_pdf(b, "ViewerPreferences", lambda d: "<</Direction/R2L>>")
    doc = pymupdf.open(a)
    try:
        assert doc.xref_get_key(doc.pdf_catalog(), "ViewerPreferences/Extra")[0] == "null"
        assert "/Extra null" in doc.xref_object(doc.pdf_catalog()), "fixture: null kept"
    finally:
        doc.close()
    assert losses(_snap(a), _snap(b)) == [] and losses(_snap(b), _snap(a)) == []


def test_reference_written_inside_a_string_is_text(tmp_path):
    """"(see 12 0 R)" is a string: replacing the "12 0 R" in it by object
    12's digest made a renumbering, or another object 12, a loss."""
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    numbers = []
    for path, other in ((a, "(alpha)"), (b, "(beta)")):
        doc = _base()
        doc.set_metadata({"title": "T"})
        n = _new_obj(doc, other)
        numbers.append(n)
        _set_info_raw(doc, f"/Refs[(see {n} 0 R)]")
        _set_catalog_raw(doc, f"/ViewerPreferences<</Note(see {n} 0 R)>>")
        _save(doc, path)
    assert numbers[0] == numbers[1], "fixture: the same object number, other content"
    assert losses(_snap(a), _snap(b)) == []


@pytest.mark.parametrize("info_link, catalog_target", [
    ("{y}", "{x}"),
    ("[{x} {z}]", "{z}"),
], ids=["cycle-entered-elsewhere", "through-a-finished-cycle"])
def test_value_in_a_reference_cycle_digests_the_same_whoever_reaches_it_first(
        tmp_path, info_link, catalog_target):
    """Objects X and Y point at each other, Z points at Y. An /Info value
    walked first enters the cycle at another object than the catalog
    value does (directly, or through Z after the cycle was finished):
    the catalog digest must not change with it, or losing the /Info key
    also reports the catalog entry."""
    a, b = tmp_path / "both.pdf", tmp_path / "catalog_only.pdf"
    for path, info_too in ((a, True), (b, False)):
        doc = _base()
        doc.set_metadata({"title": "T"})
        x, y, z = doc.get_new_xref(), doc.get_new_xref(), doc.get_new_xref()
        doc.update_object(x, f"<</Name/X/Other {y} 0 R>>")
        doc.update_object(y, f"<</Name/Y/Other {x} 0 R>>")
        doc.update_object(z, f"<</Name/Z/To {y} 0 R>>")
        refs = {"x": f"{x} 0 R", "y": f"{y} 0 R", "z": f"{z} 0 R"}
        _set_catalog_raw(doc, "/ViewerPreferences " + catalog_target.format(**refs))
        if info_too:
            _set_info_raw(doc, "/Link " + info_link.format(**refs))
        _save(doc, path)
    sa, sb = _snap(a), _snap(b)
    assert dict(sa.catalog) == dict(sb.catalog)
    assert losses(sa, sb) == ["info:Link"]


def test_javascript_open_action_is_left_to_the_javascript_check(tmp_path):
    a = tmp_path / "a.pdf"
    doc = _base()
    add_open_action_javascript(doc)
    _save(doc, a)
    assert _snap(a).catalog == ()


# ---------------------------------------------------------------------------
# 8. encryption: authenticated encrypted == decrypted
# ---------------------------------------------------------------------------

def _encrypt(src, dst, method="AES_256", user="user pw", owner="owner pw") -> None:
    doc = pymupdf.open(src)
    _save(doc, dst, encryption=getattr(pymupdf, f"PDF_ENCRYPT_{method}"),
          user_pw=user, owner_pw=owner)


@pytest.mark.parametrize("method", ["AES_256", "AES_128", "RC4_128"])
def test_authenticated_encrypted_snapshot_equals_decrypted(rich_pdf, tmp_path, method):
    enc = tmp_path / f"enc_{method}.pdf"
    _encrypt(rich_pdf, enc, method)

    locked = pymupdf.open(enc)
    try:
        assert locked.authenticate("user pw")
        encrypted = snapshot(locked)
    finally:
        locked.close()
    plain = _snap(rich_pdf)

    assert encrypted == plain
    assert losses(plain, encrypted) == [] and losses(encrypted, plain) == []


@pytest.mark.parametrize("method", ["AES_256", "RC4_128"])
def test_encrypted_custom_info_and_indirect_contents_equal_decrypted(tmp_path, method):
    """The strings read from serialised objects (custom /Info values, an
    indirect /Contents) come back decrypted once authenticated."""
    plain, enc = tmp_path / "plain.pdf", tmp_path / "enc.pdf"
    doc = _base()
    doc.set_metadata({"title": "T"})
    _set_info_raw(doc, f"/Company(ACME Lda)/Ref {_new_obj(doc, '<FEFF00410043004D0045>')} 0 R"
                       "/Trapped/True")
    annot = doc[0].add_text_annot((100, 200), "placeholder")
    doc.xref_set_key(annot.xref, "Contents", f"{_new_obj(doc, '(indirect remark)')} 0 R")
    _save(doc, plain)
    _encrypt(plain, enc, method)

    locked = pymupdf.open(enc)
    try:
        assert locked.authenticate("user pw")
        encrypted = snapshot(locked)
    finally:
        locked.close()
    expected = _snap(plain)
    assert {("Company", "string:ACME Lda"), ("Ref", "string:ACME"),
            ("Trapped", "/True")} <= set(expected.info)
    assert encrypted == expected


@pytest.mark.parametrize("method", ["AES_256", "AES_128", "RC4_128"])
@pytest.mark.parametrize("then", ["bad password", "needs_pass"])
def test_broken_decryption_state_gives_a_bogus_snapshot_silently(tmp_path, method, then):
    """Pins a PyMuPDF 1.28.2 trap the docstring of snapshot() warns about:
    after a good authenticate(), a failed one or a needs_pass read breaks
    the decryption, is_encrypted stays False, and snapshot() cannot tell.
    On this plain document it returns a snapshot with no text and a wrong
    XMP digest. If this starts raising SnapshotError, the trap is gone or
    detected; update the docstring."""
    plain, enc = tmp_path / "plain.pdf", tmp_path / "enc.pdf"
    doc = _base()
    add_xmp(doc)
    _save(doc, plain, deflate=True)
    _encrypt(plain, enc, method)
    doc = pymupdf.open(enc)
    try:
        assert doc.authenticate("user pw")
        if then == "bad password":
            assert not doc.authenticate("wrong")
        else:
            assert doc.needs_pass
        assert not doc.is_encrypted
        broken = snapshot(doc)
    finally:
        doc.close()
    assert broken.pages[0].chars == frozenset()
    assert losses(_snap(plain), broken) == ["text:page1", "text:page2", "xmp"]


# ---------------------------------------------------------------------------
# 9. failures are typed; cancellation is not a failure
# ---------------------------------------------------------------------------

def test_snapshot_error_is_not_a_password_or_value_error(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from app.utils import WrongPasswordError

    assert issubclass(SnapshotError, Exception)
    assert not issubclass(SnapshotError, WrongPasswordError)
    assert not issubclass(SnapshotError, ValueError)
    assert not issubclass(SnapshotCancelled, SnapshotError)


def test_locked_document_raises_snapshot_error(rich_pdf, tmp_path):
    enc = tmp_path / "locked.pdf"
    _encrypt(rich_pdf, enc, user="u", owner="o")
    locked = pymupdf.open(enc)
    try:
        with pytest.raises(SnapshotError) as info:
            snapshot(locked)
    finally:
        locked.close()
    # Refused up front, not by whichever PyMuPDF call happened to trip
    # first on the locked document (that would arrive as __cause__).
    assert info.value.__cause__ is None


def test_closed_document_raises_snapshot_error(rich_pdf):
    doc = pymupdf.open(rich_pdf)
    doc.close()
    with pytest.raises(SnapshotError) as info:
        snapshot(doc)
    assert info.value.__cause__ is None


def test_non_pdf_document_raises_snapshot_error():
    doc = pymupdf.open(stream=b"plain text, not a PDF", filetype="txt")
    try:
        with pytest.raises(SnapshotError) as info:
            snapshot(doc)
    finally:
        doc.close()
    assert info.value.__cause__ is None


def test_non_pdf_document_is_refused_before_any_page_is_read(monkeypatch):
    """The is_pdf guard must fire before the inventory starts: on a
    non-PDF Document, reading Page.xref crashes the process (PyMuPDF
    1.28.2), so the test above can only die with it if the guard is gone.
    Here the inventory is replaced by a stub that records the call."""
    reached = []

    def inventory(doc, poll):
        reached.append(doc)
        raise AssertionError("inventory reached on a non-PDF document")

    monkeypatch.setattr(pdf_preserve, "_snapshot", inventory)
    doc = pymupdf.open(stream=b"plain text, not a PDF", filetype="txt")
    try:
        with pytest.raises(SnapshotError) as info:
            snapshot(doc)
    finally:
        doc.close()
    assert reached == []
    assert info.value.__cause__ is None


def test_not_a_document_raises_snapshot_error():
    with pytest.raises(SnapshotError) as info:
        snapshot(object())
    assert isinstance(info.value.__cause__, AttributeError)


def test_pymupdf_failure_mid_snapshot_is_wrapped(tmp_path, monkeypatch):
    path = tmp_path / "plain.pdf"
    _save(_base(), path)

    def boom(_doc, _poll):
        raise RuntimeError("cannot read object")

    monkeypatch.setattr(pdf_preserve, "_js_payload_digests", boom)
    with pytest.raises(SnapshotError, match="cannot read object"):
        _snap(path)


class _Countdown:
    """should_cancel() that says True on its ``at``-th call."""

    def __init__(self, at):
        self.at, self.calls = at, 0

    def __call__(self):
        self.calls += 1
        return self.calls >= self.at


def _many_pages(path, n) -> None:
    doc = pymupdf.open()
    for i in range(n):
        doc.new_page().insert_text((50, 72), f"page {i}")
    _save(doc, path)


@pytest.mark.parametrize("at", [1, 3])
def test_cancel_between_pages_raises_snapshot_cancelled(tmp_path, at):
    path = tmp_path / "five.pdf"
    _many_pages(path, 5)
    cancel = _Countdown(at)
    doc = pymupdf.open(path)
    try:
        with pytest.raises(SnapshotCancelled) as info:
            snapshot(doc, should_cancel=cancel)
    finally:
        doc.close()
    assert not isinstance(info.value, SnapshotError)
    assert cancel.calls == at


def test_cancel_during_the_javascript_walk(tmp_path):
    """The page loop polls once per page; the next poll comes from the
    object walk, which visits a few hundred objects per poll."""
    path = tmp_path / "many.pdf"
    pages = 300
    _many_pages(path, pages)
    cancel = _Countdown(pages + 1)
    doc = pymupdf.open(path)
    try:
        with pytest.raises(SnapshotCancelled):
            snapshot(doc, should_cancel=cancel)
    finally:
        doc.close()
    assert cancel.calls == pages + 1


def test_reference_chain_too_deep_to_canonicalise_fails_closed(tmp_path):
    """A catalog value reaching a chain of objects deeper than the recursive
    walk can follow: a SnapshotError (the candidate is rejected), not a
    crash and not a snapshot that ignores the chain."""
    path = tmp_path / "deep.pdf"
    doc = _base()
    xrefs = [doc.get_new_xref() for _ in range(2000)]
    for i, x in enumerate(xrefs):
        doc.update_object(x, f"<</I {i}/Next {xrefs[i + 1]} 0 R>>" if i + 1 < len(xrefs)
                          else f"<</I {i}>>")
    doc.xref_set_key(doc.pdf_catalog(), "ViewerPreferences", f"{xrefs[0]} 0 R")
    _save(doc, path)
    with pytest.raises(SnapshotError, match="RecursionError"):
        _snap(path)


def test_cancel_during_the_info_value_walk(tmp_path, monkeypatch):
    """An /Info value reaching hundreds of objects polls should_cancel as
    the walk visits them; the cancel lands there, before the JavaScript
    walk starts."""
    path = tmp_path / "big_info.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.set_metadata({"title": "T"})
    refs = " ".join(f"{_new_obj(doc, f'<</N {i}>>')} 0 R" for i in range(600))
    _set_info_raw(doc, f"/Big[{refs}]")
    _save(doc, path)

    def javascript_walk(_doc, _poll):
        raise AssertionError("the JavaScript walk was reached")

    monkeypatch.setattr(pdf_preserve, "_js_payload_digests", javascript_walk)
    cancel = _Countdown(2)    # 1: the only page; 2: the /Info walk
    doc = pymupdf.open(path)
    try:
        with pytest.raises(SnapshotCancelled):
            snapshot(doc, should_cancel=cancel)
    finally:
        doc.close()
    assert cancel.calls == 2


def test_cancel_during_the_name_tree_walk(tmp_path, monkeypatch):
    """A named /OpenAction looked up in a name tree of hundreds of nodes:
    the walk polls should_cancel as it visits them."""
    def tree(doc):
        leaves = [_new_obj(doc, f"<</Names[(n{i})[{doc[0].xref} 0 R/Fit]]>>")
                  for i in range(600)]
        return "<</Kids[" + " ".join(f"{x} 0 R" for x in leaves) + "]>>"

    path = tmp_path / "big_tree.pdf"
    _tree_open_action(path, tree, name="(absent)")
    monkeypatch.setattr(pdf_preserve, "_js_payload_digests", lambda _doc, _poll: [])
    cancel = _Countdown(4)    # 1-3: the three pages; 4: the name tree walk
    doc = pymupdf.open(path)
    try:
        with pytest.raises(SnapshotCancelled):
            snapshot(doc, should_cancel=cancel)
    finally:
        doc.close()
    assert cancel.calls == 4


def test_exception_from_should_cancel_is_not_wrapped(tmp_path, monkeypatch):
    """The app's CancelledError is a plain Exception; raised from the
    callback it must reach the caller as itself, not as SnapshotError."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from app.utils import CancelledError

    path = tmp_path / "plain.pdf"
    _save(_base(), path)

    def cancelled():
        raise CancelledError()

    doc = pymupdf.open(path)
    try:
        with pytest.raises(CancelledError) as info:
            snapshot(doc, should_cancel=cancelled)
    finally:
        doc.close()
    assert not isinstance(info.value, SnapshotError)


def test_should_cancel_false_changes_nothing(rich_pdf):
    calls = []
    doc = pymupdf.open(rich_pdf)
    try:
        polled = snapshot(doc, should_cancel=lambda: calls.append(1) and False)
    finally:
        doc.close()
    assert polled == _snap(rich_pdf)
    assert len(calls) >= 3


# ---------------------------------------------------------------------------
# 10. the snapshot is a value
# ---------------------------------------------------------------------------

def test_snapshot_is_frozen_and_hashable(rich_pdf):
    s = _snap(rich_pdf)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.xmp = None
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.pages[0].images = 0
    assert hash(s) == hash(_snap(rich_pdf))


def test_shorter_document_reports_pages_once_and_compares_the_rest(tmp_path):
    a, b = tmp_path / "three.pdf", tmp_path / "one.pdf"
    doc = _base()
    add_page(doc)
    add_text_page2(doc)
    _save(doc, a)
    doc = pymupdf.open(a)
    doc.delete_pages([1, 2])
    _save(doc, b)

    assert losses(_snap(a), _snap(b)) == ["pages"]
