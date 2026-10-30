"""PDFApps - pdf_preserve: snapshot what a PDF carries, report what was lost.

The compress tool promises to preserve everything except image
resolution. This module is the oracle that checks the promise: take a
:func:`snapshot` of the source, another of a compressed candidate, and
:func:`losses` lists every item the candidate no longer carries.

Pure by design: no Qt and no ``app.*`` imports, so it sits at the bottom
of the dependency graph and is testable headless. The caller hands in an
open ``pymupdf.Document``; ``pymupdf`` itself is imported lazily, inside
:func:`snapshot`, only for its flag constants (it is already loaded by
then, so the import costs nothing and app start-up does not pay for it).

Lost versus gained
------------------
Only losses count. An item the candidate carries and the source did not
(a regenerated XMP packet where there was none, an extra page label) is
not reported. An item whose value *changed* is a loss, because the
original value is gone. Per item:

=====================  ============================  ==========================
item                   reported as                   loss when
=====================  ============================  ==========================
page count             ``pages``                     fewer pages
page size              ``mediabox:pageN``            displayed width/height
                                                     differ by > 0.01 pt (and
                                                     are not just swapped)
crop window            ``cropbox:pageN``             displayed CropBox insets
                                                     differ by > 0.01 pt
orientation            ``rotation:pageN``            displayed width/height
                                                     swapped, or the dominant
                                                     displayed text direction
                                                     changed
text (incl. Tr 3)      ``text:pageN``                any NFKC character
                                                     occurrence gone
                                                     (multiset, whitespace
                                                     and order ignored); in
                                                     Symbol / ZapfDingbats,
                                                     fewer glyphs of that font
images                 ``images:pageN``              fewer image placements
                                                     drawn (zero-area ones
                                                     ignored)
links                  ``links:pageN``               any (kind, page, uri,
                                                     file, name) gone
file attachment annot  ``file_annot:pageN``          any (filename, content
                                                     digest, /Contents) gone
other annotations      ``annots:pageN``              any (subtype, /Contents
                                                     digest) gone
popups / replies       ``popups:pageN``,             fewer Popup / IRT annots
                       ``replies:pageN``
pending redactions     ``redactions:pageN``          fewer Redact annots
thumbnail              ``thumbnail:pageN``           /Thumb present -> absent
form fields            ``form:NAME``                 any (type, value) of the
                                                     field gone or changed
outline                ``outline``                   any (level, title, page)
                                                     TOC entry gone
embedded files         ``attachment:NAME``           (name, content digest)
                                                     gone or changed
page labels            ``page_labels``               were set and differ
/Info                  ``info:KEY``                  was non-empty and differs
                                                     (every key but ModDate)
XMP                    ``xmp``                       was present and content
                                                     differs
JavaScript             ``javascript``                any non-empty reachable
                                                     JS payload gone
catalog entries        ``catalog:KEY``               was present and is gone
                                                     or its content differs
StructTreeRoot         ``struct_tree``               present -> absent
MarkInfo               ``mark_info``                 present -> absent
optional content       ``ocg:NAME``                  any (name, on/off) gone
signatures             ``signature:NAME``            signed field (/V) gone
=====================  ============================  ==========================

The full, stable set of keys (the compress tool shows them to the user):
``pages``, ``outline``, ``page_labels``, ``xmp``, ``javascript``,
``struct_tree``, ``mark_info``; per page ``mediabox:pageN``,
``cropbox:pageN``, ``rotation:pageN``, ``text:pageN``, ``images:pageN``,
``links:pageN``, ``file_annot:pageN``, ``annots:pageN``, ``popups:pageN``,
``replies:pageN``, ``redactions:pageN``, ``thumbnail:pageN`` (N 1-based);
``info:`` + one of :data:`_INFO_KEYS` (``title``, ``author``, ``subject``,
``keywords``, ``creator``, ``producer``, ``creationDate``); ``catalog:`` +
one of :data:`_CATALOG_KEYS` (``Lang``, ``ViewerPreferences``,
``PageMode``, ``PageLayout``, ``OutputIntents``, ``OpenAction``); and the
open-ended ``info:NAME`` (any other /Info key), ``form:NAME``,
``attachment:NAME``, ``ocg:NAME`` and ``signature:NAME``, whose suffix
comes from the document.

An open-ended ``info:NAME`` is the key's PDF name as MuPDF serialises
it, without the slash: printable ASCII, every delimiter, space, ``#``
and non-ASCII byte written as ``#xx`` (``/Odd Key`` is ``info:Odd#20Key``).
A name that would read as one of the fixed ``info:`` keys above (a
custom ``/title``) gets its first character escaped too
(``info:#74itle``), so a document can never produce a fixed key.

Notes per item
--------------
Page geometry is compared as the page is displayed: the MediaBox size
and the CropBox insets (distance from each MediaBox edge) after /Rotate,
with the origin dropped. Ghostscript rewrites ``[10 20 605 862]`` as
``[0 0 595 842]``, rounds 595.2756 to 595.28, and may bake a /Rotate 90
into the content (595x842 R90 becomes 842x595 R0); none of these change
what is displayed and none is a loss. Its AutoRotatePages can also turn
a page for real (the displayed size swaps, or the text ends up upside
down); that is ``rotation:pageN``. Turning a page upside down keeps its
size, so the displayed direction of the text decides. Without text there
is nothing to tell a baked rotation from a turned page, so a 180-degree
turn of a page without text is not detected (Ghostscript's auto-rotation
is driven by text and leaves such pages alone). A turned page is reported
once, as ``rotation``, not also as ``cropbox``.

Text is a multiset of characters, not of words: Ghostscript writes
"files" with an "fi" ligature glyph (NFKC folds it back) and MuPDF can
lose the space after a ligature ("tradeoff since" comes back as
"tradeoffsince"), so word boundaries are not stable across a lossless
rewrite. Characters are: "ficheiro" coming back as "9cheiro" loses an
"f" and an "i", and an OCR layer removed loses all of its characters.

Text in the base-14 Symbol and ZapfDingbats fonts is counted as glyphs
per font, not as characters: these fonts carry no Unicode mapping, so
the extracted "character" depends on the codes and the font's /Encoding,
both of which Ghostscript rewrites in the subset it embeds ("3 4 n l u"
in ZapfDingbats came back as "\\x13 \\x14 G I N", rendered identically).
The count includes the characters MuPDF extracts as whitespace, because
the rewritten glyphs can land on a whitespace code (9 of 75 ZapfDingbats
glyphs did). A glyph deleted is still a loss. The FontDescriptor's
Symbolic flag is not used to pick these fonts: it is set on ordinary
text fonts as a matter of course (every LibreOffice and pdfTeX font
measured, and Ghostscript sets it on the Calibri, Arial and Times New
Roman subsets it writes), which would turn ordinary text into a glyph
count and stop a "fi" read back as "9" from being a loss; and a
non-embedded Symbol or ZapfDingbats has no FontDescriptor to carry it.

Images are counted as placements drawn on the page, not as entries of
the page's resources: a resource dictionary shared by every page, an
image never drawn, or one image stored three times and deduplicated, all
change the resource count without changing what is drawn. A placement
with zero area (a degenerate matrix) draws nothing and Ghostscript drops
it, so it does not count. Every other placement counts whatever its
opacity: a semi-transparent watermark or logo is content, and
Ghostscript keeps an image drawn under any fill alpha, 0 included
(measured).

A link to a page is identified by its target page, whether it is a GoTo
or a named destination (Ghostscript resolves named destinations), when
that page is known; page 0 included.

Catalog entries and /Info values are compared by content, the same
whether a value (or anything inside it) is a direct object or a
reference to one, because a rewrite moves objects in and out of line:
references are resolved recursively, a reference to a page becomes its
page number, the order of a dictionary's keys does not count, and a
stream contributes its decoded data (its /Length, /Filter and
/DecodeParms do not count). A string inside a value compares by its
bytes; ``N 0 R`` written inside a string is text, not a reference.

An entry whose value is ``null``, or a reference to an object that does
not exist, is absent (ISO 32000 says so), whether it is a whole catalog
or /Info entry, a dictionary entry inside one, or the /StructTreeRoot,
/MarkInfo, /Thumb, /IRT or signature /V whose presence is checked:
MuPDF's garbage collection rewrites such a reference as ``null``, and
the entry disappearing is no loss. A GoTo /OpenAction is compared by its
destination, which is what Ghostscript writes in its place; a named
destination (direct or an indirect object) is first looked up (a string
in the /Names /Dests tree, a name in the catalog's /Dests), because
Ghostscript writes the array it names. A name it cannot resolve stays a
name, so an /OpenAction that Ghostscript drops is still a loss. A
JavaScript /OpenAction is left to ``javascript``.

A string stored as an indirect object (an annotation's /Contents, an
/Info value) is compared by its text, like a direct one: Ghostscript
writes it inline.

OCGs are keyed by name and default on/off state, not by xref: a
``garbage=4`` save renumbers objects.

Annotation subtypes that have a dedicated row (Link, Widget, Popup,
Redact, FileAttachment) are kept out of ``annots:pageN`` so that one
lost item yields exactly one key; the /Contents of Link, Widget, Popup
and Redact annotations is not tracked. A Widget's *appearance* text still
counts as page text, which is what a reader sees.

Encryption is deliberately not part of the snapshot: the compressed
output is written decrypted, and an authenticated encrypted document
must snapshot equal to its decrypted copy.

Not covered (out of scope for now): associated files (/AF), form fields
without a widget, named destinations themselves (only links resolved
through them), annotation appearance streams (/AP), and the fact that
any rewrite invalidates a digital signature (``signature:NAME`` only
says the signed value is still there).

Known limits:

* A Symbol or ZapfDingbats glyph swapped for another of the same font
  goes unnoticed, since those fonts are only counted (see above). Other
  symbol fonts (SymbolMT, Wingdings, any embedded font with its own
  encoding) are compared character by character like any text, so a
  rewrite that changes what MuPDF extracts from them is reported as a
  text loss.
* A 180-degree turn of a page without text is not detected (see the
  page geometry notes).
* /Info and catalog values are canonicalised recursively. A chain of
  references reachable from one of them that is deeper than Python's
  recursion limit allows (331 objects with the default limit of 1000,
  measured) makes :func:`snapshot` raise :class:`SnapshotError`
  ("RecursionError: ..."), so the caller rejects the candidate instead of
  comparing it. That fails closed, also inside a ``TaskRunner`` thread.
"""

from __future__ import annotations

import functools
import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pymupdf

__all__ = ["PageSnapshot", "Snapshot", "SnapshotCancelled", "SnapshotError",
           "losses", "snapshot"]

_INFO_KEYS = ("title", "author", "subject", "keywords",
              "creator", "producer", "creationDate")

# /Info keys read through doc.metadata (the _INFO_KEYS above) or left out
# on purpose (ModDate: every rewrite sets it); any other key is open-ended.
_STANDARD_INFO_NAMES = frozenset({"Title", "Author", "Subject", "Keywords", "Creator",
                                  "Producer", "CreationDate", "ModDate"})

# Marks a top-level /Info or catalog value that is a string, so that the
# string "/True" and the name /True stay apart.
_STRING_PREFIX = "string:"

# Base-14 fonts without a Unicode mapping: their text is compared as a
# glyph count per font (see the module docstring).
_SYMBOLIC_FONTS = frozenset({"Symbol", "ZapfDingbats"})
_SUBSET_TAG_RE = re.compile(r"^[A-Z]{6}\+")

_CATALOG_KEYS = ("Lang", "ViewerPreferences", "PageMode", "PageLayout",
                 "OutputIntents", "OpenAction")

# Ghostscript writes boxes with two decimals (595.2756 -> 595.28).
_BOX_TOLERANCE = 0.01

# Area (pt^2) of an image placement below which it draws nothing; only
# there to absorb float noise in a degenerate matrix.
_MIN_IMAGE_AREA = 1e-9

# Subtypes with their own row in the table above; counting them again in
# the generic per-page multiset would report one loss under two keys.
_DEDICATED_SUBTYPES = frozenset(
    {"Link", "Widget", "Popup", "Redact", "FileAttachment"})

# A stream's encoding, not its content: recompressing changes these.
_STREAM_ENCODING_KEYS = frozenset({"/Length", "/Filter", "/DecodeParms", "/DL"})

# How many objects a walk (JavaScript, values, name trees) visits between
# cancel polls.
_POLL_EVERY = 256

# A reference outside literal strings: the first branch consumes a whole
# literal string, so "(see 12 0 R)" yields no group 1. Hex strings
# cannot hold an "R".
_REF_OUTSIDE_STRINGS_RE = re.compile(r"\((?:\\.|[^\\)])*\)|(\d+)\s+\d+\s+R\b", re.DOTALL)
_FULL_REF_RE = re.compile(r"(\d+)\s+\d+\s+R")
# One token of MuPDF's compact serialisation (literal strings as in _JS_RE
# below). Used to split arrays and dictionaries into their elements.
_TOKEN_RE = re.compile(
    r"\((?:\\.|[^\\)])*\)"
    r"|<<|>>|<[0-9A-Fa-f\s]*>|\[|\]"
    r"|\d+\s+\d+\s+R\b"
    r"|/[^\s()<>\[\]{}/%]*"
    r"|[^\s()<>\[\]{}/%]+",
    re.DOTALL)
# Applied to MuPDF's own compact serialisation (xref_object), which always
# escapes "(", ")" and "\" inside literal strings, so a literal string body
# is exactly a run of escapes or non-")" characters.
_JS_RE = re.compile(
    r"/JS\s*(?:\((?P<lit>(?:\\.|[^\\)])*)\)"
    r"|<(?P<hex>[0-9A-Fa-f\s]*)>"
    r"|(?P<ref>\d+)\s+\d+\s+R)",
    re.DOTALL)
_LITERAL_ESCAPES = {"n": b"\n", "r": b"\r", "t": b"\t", "b": b"\b",
                    "f": b"\f", "(": b"(", ")": b")", "\\": b"\\"}


class SnapshotError(Exception):
    """The document could not be inventoried.

    Deliberately a plain ``Exception`` subclass: not ``ValueError`` (the
    compress tool reads that as "no size gain") and not
    ``WrongPasswordError`` (that routes to the password dialog). A
    caller that cannot snapshot a candidate must reject it.
    """


class SnapshotCancelled(Exception):
    """``should_cancel()`` returned True; the snapshot was abandoned.

    Not a :class:`SnapshotError`, so a cancel is never mistaken for an
    unreadable candidate. This module cannot import the app's
    ``CancelledError`` (it imports nothing from ``app``); the caller that
    runs it under a ``TaskRunner`` converts this into its own cancel.
    """


@dataclass(frozen=True)
class PageSnapshot:
    mediabox: tuple[float, float]               # displayed (width, height)
    cropbox: tuple[float, float, float, float]  # displayed insets (l, t, r, b)
    orientation: int | None   # dominant displayed text direction, in quarter
                              # turns clockwise; None without text
    chars: frozenset          # of (NFKC character, count), no whitespace
    symbols: frozenset        # of (symbolic font, glyph count)
    images: int               # image placements drawn, zero-area ones excluded
    links: frozenset          # of ((kind, page, uri, file, name), count)
    file_annots: frozenset    # of ((filename, sha256, sha256 of /Contents), count)
    annots: frozenset         # of ((subtype, sha256 of /Contents), count),
                              # dedicated subtypes excluded
    popups: int
    replies: int
    redactions: int
    thumbnail: bool


@dataclass(frozen=True)
class Snapshot:
    pages: tuple[PageSnapshot, ...]
    forms: frozenset          # of (name, frozenset of ((type, value), count))
    outline: frozenset        # of ((level, title, page), count)
    attachments: frozenset    # of ((name, sha256), count)
    page_labels: tuple
    info: tuple[tuple[str, str], ...]  # (key, value); other keys: (escaped
                                       # name, canonical value), non-empty only
    xmp: str | None           # sha256 of the packet, None when absent
    javascript: frozenset     # of (sha256 of a non-empty payload, count)
    catalog: tuple[tuple[str, str], ...]  # (key, sha256 of its content)
    struct_tree: bool
    mark_info: bool
    ocgs: frozenset           # of ((name, on), count)
    signatures: frozenset     # field names whose signature carries /V


# --- snapshot ---------------------------------------------------------------

def snapshot(doc: pymupdf.Document,
             should_cancel: Callable[[], bool] | None = None) -> Snapshot:
    """Inventory every preserved item of an open, authenticated PDF.

    Raises :class:`SnapshotError` when ``doc`` is closed, not a PDF,
    still locked, or when PyMuPDF fails while reading it.

    ``should_cancel`` is polled once per page and every few hundred
    objects visited by the walks over the JavaScript, the /Info and
    catalog values and the name tree; when it returns True the snapshot
    stops with :class:`SnapshotCancelled`. An exception raised by
    ``should_cancel`` itself propagates unchanged. Neither is ever
    wrapped in :class:`SnapshotError`.

    The content of ``doc`` is never changed, but on a page with /Rotate
    PyMuPDF's text extraction sets /Rotate to 0 and back, which leaves
    ``doc.is_dirty`` True (PyMuPDF 1.28.2). The caller should snapshot a
    Document of its own, opened for the purpose, and not one that the
    viewer shows or that is saved incrementally later.

    Never reads ``doc.needs_pass``: on PyMuPDF 1.28.2, reading it after
    ``authenticate()`` breaks the decryption of every stream read
    afterwards (content streams then yield no text and the XMP packet
    comes back as garbage), which would turn every encrypted source into
    a bogus snapshot. ``is_encrypted`` turns False on a successful
    ``authenticate()`` and has no such side effect.

    The caller must not have broken the document already: a successful
    ``authenticate()`` followed by a failed one, or by a read of
    ``needs_pass``, leaves the Document in that same state, with
    ``is_encrypted`` still False. :func:`snapshot` cannot tell: on a
    simple document it returns a snapshot with no text and a wrong XMP
    digest instead of raising (on a richer one some PyMuPDF call may
    trip over the garbage and a :class:`SnapshotError` results, but that
    is luck, not detection). Authenticate once, with the right password,
    and do not read ``needs_pass`` afterwards.
    """
    poll = _Poll(should_cancel)
    try:
        if doc.is_closed:
            raise SnapshotError("document is closed")
        # Not just a nicer message: on a non-PDF Document (XPS, EPUB,
        # text...) reading Page.xref, as the page loop below does, crashes
        # the whole process with an access violation (PyMuPDF 1.28.2)
        # instead of raising.
        if not doc.is_pdf:
            raise SnapshotError("not a PDF document")
        if doc.is_encrypted:
            raise SnapshotError("document is still encrypted")
        return _snapshot(doc, poll)
    except (SnapshotError, SnapshotCancelled):
        raise
    except Exception as exc:
        if exc is poll.raised:
            raise
        raise SnapshotError(f"{type(exc).__name__}: {exc}") from exc


class _Poll:
    """Calls ``should_cancel`` and remembers what it raised, if anything,
    so :func:`snapshot` can let that exception through unwrapped."""

    __slots__ = ("_fn", "_ticks", "raised")

    def __init__(self, fn: Callable[[], bool] | None) -> None:
        self._fn = fn
        self._ticks = 0
        self.raised: BaseException | None = None

    def tick(self) -> None:
        """One object visited; polls every :data:`_POLL_EVERY` of them."""
        self._ticks += 1
        if self._ticks % _POLL_EVERY == 0:
            self()

    def __call__(self) -> None:
        if self._fn is None:
            return
        try:
            stop = self._fn()
        except Exception as exc:
            self.raised = exc
            raise
        if stop:
            raise SnapshotCancelled()


def _snapshot(doc, poll: _Poll) -> Snapshot:
    import pymupdf

    strings = _Strings(pymupdf)
    try:
        return _inventory(doc, poll, pymupdf, strings)
    finally:
        strings.close()


def _inventory(doc, poll: _Poll, mu: ModuleType, strings: _Strings) -> Snapshot:
    forms: dict[str, Counter] = {}
    signatures: set[str] = set()
    page_numbers: dict[int, int] = {}
    pages = []
    for page in doc:
        poll()
        page_numbers[page.xref] = page.number
        pages.append(_page_snapshot(doc, page, mu, forms, signatures, strings))
    cat = doc.pdf_catalog()
    xmp = doc.get_xml_metadata() or ""
    canon = _Canon(doc, page_numbers, poll)
    return Snapshot(
        pages=tuple(pages),
        forms=frozenset((name, _freeze_counter(c)) for name, c in forms.items()),
        outline=_multiset(tuple(e[:3]) for e in doc.get_toc(simple=True)),
        attachments=_multiset(
            (name, _sha256(doc.embfile_get(name))) for name in doc.embfile_names()),
        page_labels=tuple(tuple(sorted(d.items())) for d in doc.get_page_labels()),
        info=_info(doc, strings, canon),
        xmp=_sha256(xmp.encode("utf-8", "surrogatepass")) if xmp else None,
        javascript=_multiset(_js_payload_digests(doc, poll)),
        catalog=_catalog_digests(doc, cat, strings, canon, poll),
        struct_tree=_has_key(doc, cat, "StructTreeRoot"),
        mark_info=_has_key(doc, cat, "MarkInfo"),
        ocgs=_multiset((v.get("name"), bool(v.get("on")))
                       for v in (doc.get_ocgs() or {}).values()),
        signatures=frozenset(signatures),
    )


class _Strings:
    """Text of a serialised PDF string, decoded exactly as PyMuPDF decodes
    a direct string value (``xref_get_key`` kind "string").

    PyMuPDF only decodes a string it finds as a dictionary value, never
    an indirect string object, and its decoding has quirks (PDFDocEncoding,
    UTF-16 with or without a BOM, language escapes, a NUL ends the text)
    that a reimplementation would have to track. So the string is put,
    as a value, into a scratch in-memory document and read back: the
    same MuPDF code decodes both forms. The scratch document is created
    on first use only, and nothing is written into the document being
    inventoried (see :func:`snapshot` for what still marks it dirty).
    """

    __slots__ = ("_doc", "_mu", "_xref")

    def __init__(self, mu: ModuleType) -> None:
        self._mu = mu
        self._doc: pymupdf.Document | None = None
        self._xref = 0

    def text(self, token: str) -> str:
        doc = self._doc
        if doc is None:
            doc = self._doc = self._mu.open()
            self._xref = doc.get_new_xref()
        doc.update_object(self._xref, f"<</V {token}>>")
        kind, value = doc.xref_get_key(self._xref, "V")
        return value if kind == "string" else ""

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None


def _page_snapshot(doc, page, mu: ModuleType, forms: dict,
                   signatures: set, strings: _Strings) -> PageSnapshot:
    subtypes: Counter[str] = Counter()
    annots: Counter[tuple[str, str]] = Counter()
    replies = 0
    for xref, _type, _id in page.annot_xrefs():
        subtype = doc.xref_get_key(xref, "Subtype")[1].lstrip("/")
        subtypes[subtype] += 1
        if subtype not in _DEDICATED_SUBTYPES:
            annots[(subtype, _contents_digest(doc, xref, strings))] += 1
        if _has_key(doc, xref, "IRT"):
            replies += 1

    # The census above already says whether the page has links, widgets or
    # file attachments; most pages have none, so skip loading them.
    links: list[tuple] = []
    if subtypes["Link"]:
        internal = (mu.LINK_GOTO, mu.LINK_NAMED)
        links = [_link_identity(lk, internal) for lk in page.get_links()]
    if subtypes["Widget"]:
        for w in page.widgets():
            name = w.field_name or ""
            forms.setdefault(name, Counter())[
                (w.field_type_string, _freeze(w.field_value))] += 1
            if (w.field_type_string == "Signature"
                    and (_has_key(doc, w.xref, "V")
                         or _has_key(doc, w.xref, "Parent/V"))):
                signatures.add(name)
    file_annots: list[tuple] = []
    if subtypes["FileAttachment"]:
        file_annots = [(a.file_info.get("filename"), _sha256(a.get_file()),
                        _contents_digest(doc, a.xref, strings))
                       for a in page.annots() if a.type[1] == "FileAttachment"]

    mediabox, cropbox = _displayed_geometry(page)
    chars, symbols, orientation = _page_text(page, mu.TEXTFLAGS_WORDS)
    return PageSnapshot(
        mediabox=mediabox,
        cropbox=cropbox,
        orientation=orientation,
        chars=_freeze_counter(chars),
        symbols=_freeze_counter(symbols),
        images=_image_count(page, mu),
        links=_multiset(links),
        file_annots=_multiset(file_annots),
        annots=_freeze_counter(annots),
        popups=subtypes["Popup"],
        replies=replies,
        redactions=subtypes["Redact"],
        thumbnail=_has_key(doc, page.xref, "Thumb"),
    )


def _displayed_geometry(page) -> tuple[tuple[float, float],
                                       tuple[float, float, float, float]]:
    """MediaBox size and CropBox insets as the page is displayed."""
    mb, cb = page.mediabox, page.cropbox
    width, height = mb.width, mb.height
    # page.mediabox is in PDF units; page.cropbox keeps x in PDF units but
    # measures y down from the top edge of the MediaBox (PyMuPDF 1.28.2).
    insets = (cb.x0 - mb.x0, cb.y0, width - (cb.x1 - mb.x0), height - cb.y1)
    for _ in range(_quarter_turns(page)):
        left, top, right, bottom = insets
        insets = (bottom, left, top, right)
        width, height = height, width
    return (width, height), insets


def _page_text(page, flags: int) -> tuple[Counter[str], Counter[str], int | None]:
    """Characters, glyphs per symbolic font, and dominant text direction.

    ``flags`` must not include TEXT_PRESERVE_IMAGES: with it, extractDICT
    re-encodes every non-JPEG image as PNG to hand it back, which made a
    300-page 300 dpi scan take 49 s (Flate), 26 s (CCITT) and 29 s
    (JBIG2) to snapshot instead of 0.1 to 0.2 s. Images are counted by
    :func:`_image_count`, which never decodes them.
    """
    textpage = page.get_textpage(flags=flags)
    chars: Counter[str] = Counter()
    symbols: Counter[str] = Counter()
    weight = [0, 0, 0, 0]
    turns = _quarter_turns(page)
    for block in textpage.extractDICT()["blocks"]:
        for line in block.get("lines", ()):
            plain = []
            glyphs = 0
            for span in line["spans"]:
                font = _SUBSET_TAG_RE.sub("", span["font"])
                if font in _SYMBOLIC_FONTS:
                    symbols[font] += len(span["text"])
                    glyphs += len(span["text"])
                else:
                    plain.append(span["text"])
            text = "".join(unicodedata.normalize("NFKC", "".join(plain)).split())
            chars.update(text)
            if text or glyphs:
                weight[_displayed_quarter(line["dir"], turns)] += len(text) + glyphs
    orientation = (max(range(4), key=weight.__getitem__)
                   if any(weight) else None)
    return chars, symbols, orientation


def _image_count(page, mu: ModuleType) -> int:
    """Image placements drawn, seen by a device that only looks at their
    matrices (no image is decoded). A degenerate matrix draws nothing.

    Not ``page.get_image_info()``: the MuPDF text device behind it skips
    every image drawn with a fill alpha under 0.5, so removing a
    semi-transparent watermark or logo was no loss. On 13,701 pages of
    the test corpus the two counts are otherwise identical.
    """
    counter = _image_counter(mu.mupdf)()
    # page.this as is: PyMuPDF's own get_bboxlog() runs it the same way.
    mu.mupdf.fz_run_page(page.this, counter, mu.mupdf.FzMatrix(), mu.mupdf.FzCookie())
    mu.mupdf.fz_close_device(counter)
    return counter.count


@functools.cache
def _image_counter(mupdf: ModuleType) -> type:
    """The device class :func:`_image_count` runs a page through. Built on
    first use because it subclasses a PyMuPDF class, and this module does
    not import PyMuPDF when it is loaded."""

    device: Any = mupdf.FzDevice2

    class ImageCounter(device):
        def __init__(self) -> None:
            super().__init__()
            self.count = 0
            self.use_virtual_fill_image()
            self.use_virtual_fill_image_mask()

        def fill_image(self, _ctx, _image, ctm, _alpha, _color_params) -> None:
            if abs(ctm.a * ctm.d - ctm.b * ctm.c) > _MIN_IMAGE_AREA:
                self.count += 1

        def fill_image_mask(self, ctx, image, ctm, _colorspace, _color, alpha,
                            color_params) -> None:
            self.fill_image(ctx, image, ctm, alpha, color_params)

    return ImageCounter


def _quarter_turns(page) -> int:
    return (page.rotation // 90) % 4


def _displayed_quarter(direction: tuple[float, float], turns: int) -> int:
    """Quarter (0 right, 1 down, 2 left, 3 up) of a text direction given
    in unrotated page space, once the page's /Rotate is applied."""
    dx, dy = direction
    for _ in range(turns):
        dx, dy = -dy, dx    # one clockwise quarter turn, y pointing down
    if abs(dx) >= abs(dy):
        return 0 if dx > 0 else 2
    return 1 if dy > 0 else 3


def _link_identity(link: dict, internal: tuple[int, int]) -> tuple:
    kind, page = link.get("kind"), link.get("page")
    if kind in internal and isinstance(page, int) and page >= 0:
        return (internal[0], page, None, None, None)
    return (kind, page, link.get("uri"), link.get("file"),
            link.get("name") or link.get("nameddest"))


def _contents_digest(doc, xref: int, strings: _Strings) -> str:
    kind, value = doc.xref_get_key(xref, "Contents")
    if kind == "xref":
        token = _object_source(doc, int(value.split()[0]))
        value = strings.text(token) if _is_string(token) else ""
    elif kind != "string":
        value = ""
    return _sha256(value.encode("utf-8", "surrogatepass"))


def _info(doc, strings: _Strings, canon: _Canon) -> tuple[tuple[str, str], ...]:
    """The standard keys through ``doc.metadata``, then every other /Info
    key except ModDate, by its escaped name (see the module docstring)."""
    meta = doc.metadata or {}
    standard = [(k, meta.get(k) or "") for k in _INFO_KEYS]
    other = []
    entries = _entries(_source(doc, *doc.xref_get_key(-1, "Info")))
    for name, token in entries.items():
        if name[1:] in _STANDARD_INFO_NAMES:
            continue
        value = _value(doc, token, strings, canon)
        if value is not None and value != _STRING_PREFIX:
            other.append((_info_key(name[1:]), value))
    return tuple(standard + sorted(other))


def _value(doc, token: str, strings: _Strings, canon: _Canon) -> str | None:
    """Canonical form of a top-level /Info or catalog value; None when it
    is absent (``null``, or a reference to an object that does not
    exist). A string, direct or indirect, is compared by its text, as
    PyMuPDF decodes it."""
    target = _deref(doc, token)
    if _is_string(target):
        return _STRING_PREFIX + strings.text(target)
    value = canon.value(token)
    return None if value == "null" else value


def _info_key(name: str) -> str:
    """``name`` as MuPDF escapes it, kept apart from the fixed keys."""
    if name in _INFO_KEYS:
        name = f"#{ord(name[0]):02X}{name[1:]}"
    return name


def _catalog_digests(doc, cat: int, strings: _Strings, canon: _Canon,
                     poll: _Poll) -> tuple[tuple[str, str], ...]:
    entries = _entries(_object_source(doc, cat))
    out = []
    for key in _CATALOG_KEYS:
        token = entries.get(f"/{key}")
        if token is not None and key == "OpenAction":
            token = _open_action_target(doc, cat, token, poll)
        value = None if token is None else _value(doc, token, strings, canon)
        if value is not None:
            out.append((key, _sha256(value.encode("utf-8", "surrogatepass"))))
    return tuple(out)


def _open_action_target(doc, cat: int, token: str, poll: _Poll) -> str | None:
    """The serialised value /OpenAction is compared by; None for a
    JavaScript action, which the ``javascript`` check covers."""
    action = doc.xref_get_key(cat, "OpenAction/S")[1]
    if action == "/JavaScript":
        return None
    if action == "/GoTo":
        # Ghostscript writes <</S/GoTo/D[p /Fit]>> as plain [p /Fit], and
        # a named destination as the array the name stands for.
        dest = _deref(doc, _entries(_deref(doc, token)).get("/D", ""))
        if _is_string(dest) or dest.startswith("/"):
            named = _named_destination(doc, cat, dest, poll)
            if named is not None:
                return named
        if dest:
            return dest
    return token


def _named_destination(doc, cat: int, name: str, poll: _Poll) -> str | None:
    """The destination array ``name`` (a serialised PDF string or name)
    stands for: a string in the /Names /Dests tree, a name in /Dests."""
    if name.startswith("/"):
        found = _entries(_source(doc, *doc.xref_get_key(cat, "Dests"))).get(name)
    else:
        found = _name_tree_value(doc, _source(doc, *doc.xref_get_key(cat, "Names/Dests")),
                                 _string_bytes(name), poll)
    for _ in range(3):    # value -> indirect -> <</D ...>> -> indirect array
        if found is None:
            return None
        found = _deref(doc, found)
        if found.startswith("["):
            return found
        found = _entries(found).get("/D")
    return None


def _name_tree_value(doc, root: str, key: bytes, poll: _Poll) -> str | None:
    """The value stored under the string ``key`` in a name tree (the
    serialised root node); a plain walk, every node visited once, so a
    /Kids cycle ends."""
    nodes = [root]
    seen: set[int] = set()
    while nodes:
        poll.tick()
        node = _entries(nodes.pop())
        items = _elements(_deref(doc, node.get("/Names", "")))
        for k, v in zip(items[::2], items[1::2]):
            if _is_string(k) and _string_bytes(k) == key:
                return v
        for kid in _elements(_deref(doc, node.get("/Kids", ""))):
            m = _FULL_REF_RE.fullmatch(kid)
            xref = int(m.group(1)) if m else 0
            if xref and xref not in seen:
                seen.add(xref)
                nodes.append(_object_source(doc, xref))
    return None


# --- MuPDF's compact serialisation ------------------------------------------

def _source(doc, kind: str, value: str) -> str:
    """Serialised form of an ``xref_get_key`` result: the object's own
    source when it is a reference, else the value itself."""
    if kind == "xref":
        return _object_source(doc, int(value.split()[0]))
    return value


def _object_source(doc, xref: int) -> str:
    if not 0 < xref < doc.xref_length() or doc.xref_is_stream(xref):
        return ""
    return doc.xref_object(xref, compressed=True).strip()


def _deref(doc, token: str) -> str:
    m = _FULL_REF_RE.fullmatch(token)
    return _object_source(doc, int(m.group(1))) if m else token


def _elements(src: str) -> list[str]:
    """Top-level elements of one serialised array or dictionary (a
    dictionary gives key, value, key, value...)."""
    out: list[str] = []
    depth = 0
    start = 0
    for m in _TOKEN_RE.finditer(src):
        token = m.group()
        if token in ("[", "<<"):
            depth += 1
            if depth == 2:
                start = m.start()
        elif token in ("]", ">>"):
            depth -= 1
            if depth == 1:
                out.append(src[start:m.end()])
        elif depth == 1:
            out.append(token)
    return out


def _entries(src: str) -> dict[str, str]:
    """Key -> serialised value of a serialised dictionary; {} otherwise."""
    if not src.startswith("<<"):
        return {}
    items = _elements(src)
    return dict(zip(items[::2], items[1::2]))


def _is_string(token: str) -> bool:
    return token.startswith("(") or (token.startswith("<") and not token.startswith("<<"))


def _string_bytes(token: str) -> bytes:
    if token.startswith("("):
        return _decode_literal(token[1:-1])
    return _decode_hex(token[1:-1])


class _Canon:
    """Canonical text of a serialised value, equal for equal content
    whatever the object numbers and whether each part is direct or
    stored as its own object (a rewrite renumbers, inlines and splits).

    A dictionary or array becomes a digest of its canonical elements, a
    dictionary with its keys sorted and its ``null`` entries dropped. A
    reference becomes the canonical form of its target: a page its page
    number, a stream a digest of its dictionary (encoding keys left out)
    and decoded data, an object that does not exist ``null``. A string
    becomes its bytes. The serialisation is split token by token, so a
    ``N 0 R`` inside a string stays text.

    Each object is visited once per :meth:`value` call. Results are kept
    for the whole snapshot, which keeps a graph shared between values
    linear, except those computed through a reference cycle: these
    depend on where the walk entered the cycle, so they are only kept
    until the next :meth:`value` call, and the digest of a value never
    depends on what another value visited first.
    """

    __slots__ = ("_cycles", "_doc", "_local", "_memo", "_n", "_pages", "_poll")

    def __init__(self, doc, page_numbers: dict[int, int], poll: _Poll) -> None:
        self._doc = doc
        self._n = doc.xref_length()
        self._pages = page_numbers
        self._poll = poll
        self._memo: dict[int, str] = {}
        self._local: dict[int, str] = {}
        self._cycles = 0

    def value(self, token: str) -> str:
        self._local = {}
        return self._of(token)

    def _of(self, token: str, skip: frozenset = frozenset(), prefix: str = "") -> str:
        # Dictionaries are handled here, not in a helper, and arrays with a
        # list comprehension (inlined since Python 3.12), to spend as few
        # stack frames per nesting level as possible: the walk is
        # recursive, and a deeper chain than Python's recursion limit
        # allows becomes a SnapshotError.
        if token.startswith("<<"):
            items = _elements(token)
            parts = []
            for key, value in sorted(zip(items[::2], items[1::2])):
                if key not in skip:
                    canonical = self._of(value)
                    if canonical != "null":
                        parts.append(f"{key} {canonical}")
            return _digest(prefix + "<<" + " ".join(parts) + ">>")
        if token.startswith("["):
            return _digest("[" + " ".join([self._of(e) for e in _elements(token)]) + "]")
        if _is_string(token):
            return "s:" + _string_bytes(token).hex()
        m = _FULL_REF_RE.fullmatch(token)
        return self._ref(int(m.group(1))) if m else token

    def _ref(self, xref: int) -> str:
        if xref in self._pages:
            return f"<page {self._pages[xref]}>"
        known = self._memo.get(xref)
        if known is not None:
            return known
        known = self._local.get(xref)
        if known is not None:     # in progress (a cycle) or computed through one
            self._cycles += 1
            return known
        self._poll.tick()
        self._local[xref] = "<cycle>"
        cycles = self._cycles
        doc = self._doc
        if not 0 < xref < self._n:
            value = "null"
        elif doc.xref_is_stream(xref):
            data = _sha256(doc.xref_stream(xref) or b"")
            value = self._of(doc.xref_object(xref, compressed=True),
                             _STREAM_ENCODING_KEYS, f"stream {data} ")
        else:
            value = self._of(doc.xref_object(xref, compressed=True).strip())
        if self._cycles == cycles:
            del self._local[xref]
            self._memo[xref] = value
        else:
            self._local[xref] = value
        return value


def _digest(body: str) -> str:
    return f"<{_sha256(body.encode('utf-8', 'surrogatepass'))}>"


def _js_payload_digests(doc, poll: _Poll) -> list[str]:
    """Digest of every non-empty /JS payload reachable from the trailer.

    Reachability matters: an orphaned JavaScript action (left behind by
    an incremental save that dropped its last reference) is not part of
    the document, and ``save(garbage=...)`` legitimately removes it. A
    plain scan of every xref would report that removal as a loss.

    Walking every reachable object, rather than looking at /OpenAction,
    /AA, /A and the /Names/JavaScript tree one by one, also catches
    actions nested inline in another dictionary or chained via /Next.
    """
    n = doc.xref_length()
    seen: set[int] = set()
    stack = list(_refs(doc.pdf_trailer()))
    digests: list[str] = []
    while stack:
        xref = stack.pop()
        if xref in seen or not 0 < xref < n:
            continue
        seen.add(xref)
        if len(seen) % _POLL_EVERY == 0:
            poll()
        src = doc.xref_object(xref, compressed=True)
        stack.extend(_refs(src))
        if "/JS" not in src:
            continue
        for m in _JS_RE.finditer(src):
            if m.group("lit") is not None:
                payload = _decode_literal(m.group("lit"))
            elif m.group("hex") is not None:
                payload = _decode_hex(m.group("hex"))
            else:
                payload = _indirect_payload(doc, int(m.group("ref")), n)
            if payload and payload.strip():
                digests.append(_sha256(payload))
    return digests


def _refs(src: str) -> Iterator[int]:
    """Object numbers referenced in a serialisation, not counting a
    ``N 0 R`` written inside a literal string: that would make an orphan
    reachable, and its garbage collection a loss."""
    return (int(m.group(1)) for m in _REF_OUTSIDE_STRINGS_RE.finditer(src) if m.group(1))


def _indirect_payload(doc, xref: int, n: int) -> bytes:
    """``/JS N 0 R``: a stream, or (rarer) an indirect string object."""
    if not 0 < xref < n:
        return b""
    if doc.xref_is_stream(xref):
        return doc.xref_stream(xref) or b""
    src = doc.xref_object(xref, compressed=True).strip()
    if src.startswith("(") and src.endswith(")"):
        return _decode_literal(src[1:-1])
    if src.startswith("<") and not src.startswith("<<") and src.endswith(">"):
        return _decode_hex(src[1:-1])
    return b""


def _decode_literal(body: str) -> bytes:
    """Bytes of a PDF literal string body (escapes resolved).

    Decoding, not just hashing the escaped text, makes the same script
    digest the same whether it is stored as a literal, a hex string or
    a stream.

    The backslash-EOL branch follows the PDF spec but never fires on
    MuPDF's serialisation: PyMuPDF 1.28.2 already drops a backslash-EOL
    while parsing, so it never writes one back.
    """
    out = bytearray()
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        i += 1
        if c != "\\" or i >= n:
            out += c.encode("utf-8", "surrogatepass")
            continue
        e = body[i]
        i += 1
        if e in _LITERAL_ESCAPES:
            out += _LITERAL_ESCAPES[e]
        elif e in "01234567":
            j = i
            while j < n and j < i + 2 and body[j] in "01234567":
                j += 1
            out.append(int(body[i - 1:j], 8) & 0xFF)
            i = j
        elif e == "\r":
            if i < n and body[i] == "\n":
                i += 1
        elif e != "\n":
            out += e.encode("utf-8", "surrogatepass")
    return bytes(out)


def _decode_hex(body: str) -> bytes:
    digits = "".join(body.split())
    if len(digits) % 2:
        digits += "0"
    return bytes.fromhex(digits)


# --- losses -----------------------------------------------------------------

def losses(before: Snapshot, after: Snapshot) -> list[str]:
    """Stable, readable keys for every item ``before`` has and ``after`` lost.

    Page numbers in keys are 1-based. Per-page items are compared over
    the pages both snapshots have; a shorter ``after`` is reported once
    as ``pages``. The order is deterministic: the order of
    :data:`_CHECKS`, then page order, then name order.
    """
    out: list[str] = []
    for check in _CHECKS:
        out.extend(check(before, after))
    return out


def _check_pages(before: Snapshot, after: Snapshot) -> list[str]:
    return ["pages"] if len(after.pages) < len(before.pages) else []


def _per_page(name: str, lost: Callable) -> Callable:
    def check(before: Snapshot, after: Snapshot) -> list[str]:
        return [f"{name}:page{i}"
                for i, (b, a) in enumerate(zip(before.pages, after.pages), 1)
                if lost(b, a)]
    check.__name__ = f"_check_{name}"
    return check


def _multiset_lost(attr: str):
    return lambda b, a: bool(_missing(getattr(b, attr), getattr(a, attr)))


def _count_lost(attr: str):
    return lambda b, a: getattr(a, attr) < getattr(b, attr)


def _close(x: tuple, y: tuple) -> bool:
    return all(abs(p - q) <= _BOX_TOLERANCE for p, q in zip(x, y))


def _turned(b: PageSnapshot, a: PageSnapshot) -> bool:
    if not _close(b.mediabox, a.mediabox) and _close(b.mediabox, a.mediabox[::-1]):
        return True
    return (b.orientation is not None and a.orientation is not None
            and b.orientation != a.orientation)


def _resized(b: PageSnapshot, a: PageSnapshot) -> bool:
    return not (_close(b.mediabox, a.mediabox)
                or _close(b.mediabox, a.mediabox[::-1]))


def _recropped(b: PageSnapshot, a: PageSnapshot) -> bool:
    return not _close(b.cropbox, a.cropbox) and not _turned(b, a)


_check_mediabox = _per_page("mediabox", _resized)
_check_cropbox = _per_page("cropbox", _recropped)
_check_rotation = _per_page("rotation", _turned)
_check_text = _per_page("text", lambda b, a: bool(_missing(b.chars, a.chars)
                                                  or _missing(b.symbols, a.symbols)))
_check_images = _per_page("images", _count_lost("images"))
_check_links = _per_page("links", _multiset_lost("links"))
_check_file_annots = _per_page("file_annot", _multiset_lost("file_annots"))
_check_annots = _per_page("annots", _multiset_lost("annots"))
_check_popups = _per_page("popups", _count_lost("popups"))
_check_replies = _per_page("replies", _count_lost("replies"))
_check_redactions = _per_page("redactions", _count_lost("redactions"))
_check_thumbnails = _per_page("thumbnail", lambda b, a: b.thumbnail and not a.thumbnail)


def _check_forms(before: Snapshot, after: Snapshot) -> list[str]:
    after_forms = dict(after.forms)
    return [f"form:{name}" for name, entries in sorted(before.forms, key=_by_name)
            if _missing(entries, after_forms.get(name, frozenset()))]


def _check_outline(before: Snapshot, after: Snapshot) -> list[str]:
    return ["outline"] if _missing(before.outline, after.outline) else []


def _check_attachments(before: Snapshot, after: Snapshot) -> list[str]:
    return [f"attachment:{name}"
            for name in sorted({str(item[0]) for item in _missing(
                before.attachments, after.attachments)})]


def _check_page_labels(before: Snapshot, after: Snapshot) -> list[str]:
    return (["page_labels"]
            if before.page_labels and before.page_labels != after.page_labels
            else [])


def _check_info(before: Snapshot, after: Snapshot) -> list[str]:
    after_info = dict(after.info)
    return [f"info:{k}" for k, v in before.info if v and after_info.get(k) != v]


def _check_xmp(before: Snapshot, after: Snapshot) -> list[str]:
    return ["xmp"] if before.xmp is not None and before.xmp != after.xmp else []


def _check_javascript(before: Snapshot, after: Snapshot) -> list[str]:
    return ["javascript"] if _missing(before.javascript, after.javascript) else []


def _check_catalog(before: Snapshot, after: Snapshot) -> list[str]:
    after_catalog = dict(after.catalog)
    return [f"catalog:{k}" for k, v in before.catalog if after_catalog.get(k) != v]


def _check_struct_tree(before: Snapshot, after: Snapshot) -> list[str]:
    return ["struct_tree"] if before.struct_tree and not after.struct_tree else []


def _check_mark_info(before: Snapshot, after: Snapshot) -> list[str]:
    return ["mark_info"] if before.mark_info and not after.mark_info else []


def _check_ocgs(before: Snapshot, after: Snapshot) -> list[str]:
    return [f"ocg:{name}" for name in sorted(
        {str(item[0]) for item in _missing(before.ocgs, after.ocgs)})]


def _check_signatures(before: Snapshot, after: Snapshot) -> list[str]:
    return [f"signature:{name}"
            for name in sorted(before.signatures - after.signatures)]


_CHECKS = (
    _check_pages,
    _check_mediabox,
    _check_cropbox,
    _check_rotation,
    _check_text,
    _check_images,
    _check_links,
    _check_file_annots,
    _check_annots,
    _check_popups,
    _check_replies,
    _check_redactions,
    _check_thumbnails,
    _check_forms,
    _check_outline,
    _check_attachments,
    _check_page_labels,
    _check_info,
    _check_xmp,
    _check_javascript,
    _check_catalog,
    _check_struct_tree,
    _check_mark_info,
    _check_ocgs,
    _check_signatures,
)


# --- helpers ----------------------------------------------------------------

def _multiset(items: Iterable) -> frozenset:
    return _freeze_counter(Counter(items))


def _freeze_counter(c: Counter) -> frozenset:
    return frozenset(c.items())


def _missing(before: frozenset, after: frozenset) -> Counter:
    """Items (with multiplicity) in ``before`` that ``after`` lacks."""
    return Counter(dict(before)) - Counter(dict(after))


def _by_name(entry: tuple) -> str:
    return str(entry[0])


def _freeze(value):
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _has_key(doc, xref: int, key: str) -> bool:
    """Whether ``key`` is set: not ``null`` and not a reference to an
    object that does not exist, which ISO 32000 treats as absent."""
    kind, value = doc.xref_get_key(xref, key)
    if kind == "xref":
        return _exists(doc, int(value.split()[0]))
    return kind != "null"


def _exists(doc, xref: int) -> bool:
    if not 0 < xref < doc.xref_length():
        return False
    return doc.xref_is_stream(xref) or doc.xref_object(xref, compressed=True).strip() != "null"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
