"""Unicode-safe PDF password handling.

Pure module: no ``PySide6`` import, no ``app.*`` import. Everything
except :func:`resolve_file_password` talks to a ``pymupdf.Document`` /
``pypdf.PdfReader`` through duck typing (``.authenticate(...)`` /
``.decrypt(...)``) and touches no filesystem; that one function opens a
path because probing bytes on disk is the whole point of it. All of it
is testable headless.

Why this exists
---------------
The two PDF engines we ship disagree about what a password *is*:

* **MuPDF (PyMuPDF) does not normalise at all.** ``pdf_crypt.c``'s
  ``pdf_saslprep_from_utf8`` is a stub (``/* TODO: stringprep with
  SASLprep profile */``) that copies the UTF-8 bytes verbatim for R>=5,
  and converts UTF-8 to PDFDocEncoding for R<=4.
* **pypdf >= 6.12 implements SASLprep in full** (``_encryption._saslprep``,
  which ends in ``unicodedata.normalize("NFKC", ...)``) and applies it in
  ``_encode_password`` whenever ``V >= 5`` *and* the argument is a ``str``.
  For ``V < 5`` it encodes ``str`` as Latin-1 (falling back to UTF-8).
  A ``bytes`` argument bypasses all of that and is used verbatim.

ISO 32000-2 §7.6.4.3.3 mandates SASLprep (RFC 4013, whose "Normalize"
step is **NFKC**, not NFC) for R6/AES-256, so pypdf is the conformant
one. But pikepdf/QPDF and MuPDF do not normalise, and files they produce
must keep opening. Applying SASLprep unilaterally would trade one
interoperability bug for another.

So on the READ side we do not pick a winner: we try a small, ordered,
de-duplicated list of candidate spellings and remember the one that
actually authenticated. On the CONSUME side both engines are handed the
*same UTF-8 byte sequence* (``pypdf`` gets ``bytes`` directly, which
skips its SASLprep branch; ``pymupdf`` gets the ``str``, which MuPDF
encodes to the same UTF-8 bytes), so they can no longer diverge by
construction for R>=5.

R<=4 caveat (documented, not fixed)
-----------------------------------
For R<=4 the spec defines no canonical form at all -- it defers to the
"host system code page" -- so there is no conformance target and no
spelling that both engines are guaranteed to agree on. MuPDF maps UTF-8
to PDFDocEncoding while pypdf's ``str`` path uses Latin-1 and its
``bytes`` path uses whatever it is given. We therefore also try the
plain ``str`` form against pypdf for non-ASCII candidates
(:func:`pypdf_password_forms`), which reproduces the Latin-1 semantics
that matched MuPDF's PDFDocEncoding before this module existed. That is
best effort: a non-ASCII password that cannot be represented in
PDFDocEncoding (e.g. a combining acute, U+0301) is simply unopenable by
MuPDF, whatever we pass it.

Cost note: no ``report`` / ``should_cancel`` callables here on purpose.
The worst case is six authentication attempts and the slowest engine
measured ~20 ms per AES-256 attempt, i.e. well under a tenth of a
second in total; a cancellation protocol would be ceremony with no
consumer.
"""

from __future__ import annotations

import stringprep
import unicodedata

__all__ = [
    "saslprep",
    "password_candidates",
    "pypdf_password_forms",
    "authenticate_pymupdf",
    "decrypt_pypdf",
    "resolve_file_password",
]


# RFC 4013 §2.3 -- prohibited output. Kept as a table so the error
# message can name the offending class; the check itself is only used to
# decide whether the SASLprep candidate is usable at all.
_PROHIBITED = (
    # RFC 4013 §2.5: a *stored* string (which a PDF password is) must
    # also reject unassigned code points, i.e. table A.1 of RFC 3454 --
    # anything unassigned in Unicode 3.2, which includes every emoji.
    # pypdf checks this too and falls back to raw UTF-8 when it trips,
    # so omitting it here made our candidate list disagree with what
    # pypdf actually hashes for any emoji-bearing password.
    (stringprep.in_table_a1, "unassigned code point"),
    (stringprep.in_table_c12, "non-ASCII space"),
    (stringprep.in_table_c21, "ASCII control"),
    (stringprep.in_table_c22, "non-ASCII control"),
    (stringprep.in_table_c3, "private use"),
    (stringprep.in_table_c4, "non-character code point"),
    (stringprep.in_table_c5, "surrogate code"),
    (stringprep.in_table_c6, "inappropriate for plain text"),
    (stringprep.in_table_c7, "inappropriate for canonical representation"),
    (stringprep.in_table_c8, "change display properties or deprecated"),
    (stringprep.in_table_c9, "tagging character"),
)


def saslprep(pwd: str) -> str:
    """Return ``pwd`` prepared with the SASLprep profile (RFC 4013).

    Implemented here on ``unicodedata`` + the stdlib ``stringprep``
    module rather than importing ``pypdf._encryption._saslprep``: that
    symbol is private to a third-party package and can move or change
    semantics in a patch release, and we need a variant that never
    escapes as an exception into the PDF-open path (see
    :func:`password_candidates`).

    Raises:
        ValueError: the prepared string contains a prohibited character
            (RFC 4013 §2.3), an unassigned code point (§2.5) or violates
            the bidirectional rules (RFC 3454 §6). Callers that only want
            a candidate spelling should treat that as "no SASLprep
            candidate", not as an error to surface.
    """
    # §2.1 Mapping: table B.1 maps to nothing, table C.1.2 maps to SPACE.
    mapped = []
    for ch in pwd:
        if stringprep.in_table_b1(ch):
            continue
        mapped.append(" " if stringprep.in_table_c12(ch) else ch)

    # §2.2 Normalization: NFKC (this is the step that makes SASLprep
    # differ from the NFC this codebase used to apply -- NFKC folds
    # compatibility characters such as U+FB01 LATIN SMALL LIGATURE FI
    # into "fi", NFC does not).
    out = unicodedata.normalize("NFKC", "".join(mapped))

    # §2.3 Prohibited output + §2.5 unassigned. The message names the
    # character *class* only: this exception can reach a caller that
    # logs it, and the code point would be one character of the user's
    # password.
    for ch in out:
        for check, label in _PROHIBITED:
            if check(ch):
                raise ValueError(f"SASLprep: prohibited {label}")

    # §2.4 Bidirectional characters (RFC 3454 §6).
    has_randal = any(stringprep.in_table_d1(ch) for ch in out)
    if has_randal:
        if any(stringprep.in_table_d2(ch) for ch in out):
            raise ValueError(
                "SASLprep: RandALCat and LCat characters must not mix")
        if not (stringprep.in_table_d1(out[0])
                and stringprep.in_table_d1(out[-1])):
            raise ValueError(
                "SASLprep: RandALCat string must start and end with "
                "RandALCat characters")
    return out


def password_candidates(pwd: str) -> list[str]:
    """Return the ordered, de-duplicated spellings to try for ``pwd``.

    Order is deliberate:

    1. ``pwd`` exactly as typed -- what MuPDF, pikepdf and QPDF hash,
       and also the form a macOS user's NFD keystrokes arrive in.
    2. ``saslprep(pwd)`` -- what pypdf (and any ISO 32000-2 conformant
       producer) hashes for AES-256.
    3. ``NFC(pwd)`` -- what this application itself wrote into its
       password cache before this module existed, so files unlocked by
       an older build keep opening.

    NFD is deliberately **not** a candidate: no producer canonicalises
    to NFD, and the NFD case is already covered by candidate 1 because
    NFD is what the user types.
    """
    if not pwd:
        return [pwd]
    out = [pwd]
    try:
        prepped = saslprep(pwd)
    except ValueError:
        # A password containing prohibited or bidi-invalid characters
        # has no SASLprep spelling; that is a missing candidate, not a
        # failure to open the file. Drop it and keep going.
        #
        # Scoped to ValueError on purpose, and it is not a wider net in
        # disguise: ``saslprep`` raises TypeError for a non-``str``
        # argument, which would mean a caller handed a PDF password
        # ``None`` (or ``bytes``). That is a bug in the caller, not a
        # password with no canonical spelling, and it must surface
        # rather than be absorbed as "one fewer candidate" and
        # re-reported as "wrong password".
        prepped = None
    if prepped is not None and prepped not in out:
        out.append(prepped)
    nfc = unicodedata.normalize("NFC", pwd)
    if nfc not in out:
        out.append(nfc)
    return out


def pypdf_password_forms(pwd: str) -> list[tuple[str, str | bytes]]:
    """Return ``(candidate, argument)`` pairs to feed ``PdfReader.decrypt``.

    Every candidate is offered first as raw UTF-8 ``bytes``. That is the
    byte-for-byte parity path with MuPDF: ``PdfReader.decrypt`` accepts
    ``Union[str, bytes]`` and its ``bytes`` branch skips
    ``_encode_password``'s SASLprep/Latin-1 logic entirely.

    Non-ASCII candidates are then offered again as ``str`` so pypdf
    applies its own encoding. That is the R<=4 escape hatch described in
    the module docstring: for ``V < 5`` pypdf encodes ``str`` as Latin-1,
    which is what matches MuPDF's PDFDocEncoding. ASCII candidates are
    skipped in that second pass because Latin-1, UTF-8 and SASLprep all
    agree on ASCII, so the attempt would be an exact duplicate.
    """
    cands = password_candidates(pwd)
    forms: list[tuple[str, str | bytes]] = []
    seen: set[bytes] = set()
    for cand in cands:
        raw = cand.encode("utf-8")
        if raw in seen:
            continue
        seen.add(raw)
        forms.append((cand, raw))
    for cand in cands:
        if cand.isascii():
            continue
        forms.append((cand, cand))
    return forms


def authenticate_pymupdf(doc, pwd: str) -> str | None:
    """Authenticate ``doc`` (a ``pymupdf.Document``) against every candidate.

    Returns the candidate spelling that worked -- the caller should
    cache *that* string, not the one the user typed and not a normalised
    form -- or ``None`` if none did.
    """
    if not pwd:
        return None
    for cand in password_candidates(pwd):
        try:
            if doc.authenticate(cand):
                return cand
        except Exception:
            # A candidate the C layer refuses to marshal (e.g. an
            # embedded NUL) must not abort the remaining attempts.
            continue
    return None


def decrypt_pypdf(reader, pwd: str) -> str | None:
    """Decrypt ``reader`` (a ``pypdf.PdfReader``) against every candidate.

    Returns the candidate spelling that worked, or ``None``.
    ``PdfReader.decrypt`` returns ``PasswordType.NOT_DECRYPTED`` (0) on a
    wrong password and leaves a reader whose ``pages`` is empty, which is
    how tools used to silently write blank PDFs -- so a ``None`` here
    must be treated as an error by the caller, never ignored.
    """
    if not pwd:
        return None
    for cand, arg in pypdf_password_forms(pwd):
        try:
            if reader.decrypt(arg) != 0:
                return cand
        except Exception:
            # pypdf raises on some malformed /Encrypt dictionaries and on
            # unsupported filters; a later candidate cannot fix that, but
            # neither should one bad attempt mask a good one.
            continue
    return None


def resolve_file_password(path: str, pwd: str) -> "str | None":
    """Return the spelling that really unlocks the file at ``path``.

    Returns ``""`` when the file opens with no password at all, the
    winning candidate string when one of them authenticates, and
    ``None`` when the file is locked and nothing derived from ``pwd``
    opens it.

    This is the *probe* counterpart to the read-side helpers above, and
    it exists because predicting what a producer did to a password is a
    losing game. The encrypt tool used to compute ``saslprep(typed)`` to
    guess how pypdf had just locked its own output; pypdf, however,
    falls back to raw UTF-8 whenever its SASLprep raises (unassigned
    code points -- every emoji -- prohibited characters, bidi
    violations), so the guess was wrong for exactly the passwords where
    it mattered, and it was pinned to one third-party version's
    behaviour. Opening the bytes we just wrote answers the question
    instead of predicting it.

    The only I/O in this module. Still headless and Qt-free, so it stays
    here with the rest of the spelling logic rather than growing a
    second home.
    """
    pymupdf_answer = None
    try:
        import pymupdf
        doc = pymupdf.open(path)
        try:
            if not doc.needs_pass:
                return ""
            pymupdf_answer = authenticate_pymupdf(doc, pwd)
        finally:
            doc.close()
    except Exception:
        # Missing binary wheel, unreadable path, or a flavour MuPDF
        # refuses: fall through to pypdf rather than reporting "locked".
        pymupdf_answer = None
    if pymupdf_answer is not None:
        return pymupdf_answer
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        # NOT a Windows file-lock guard, despite the symmetry with
        # ``doc.close()`` above: ``PdfReader(path)`` reads the whole file
        # into a ``BytesIO`` inside a ``with`` block
        # (``_initialize_stream``), so the OS handle is already closed
        # when ``__init__`` returns and ``os.replace`` over ``path``
        # succeeds with the reader still alive (measured on pypdf 6.14.2
        # and 6.16.2 against an instrument that does raise
        # ``PermissionError`` for a genuinely retained handle).
        # ``close()`` releases that ``BytesIO`` and the resolved-object
        # cache eagerly instead of at collection time -- for a large
        # encrypted PDF that is the file's whole size held in the heap of
        # a caller that only wanted to learn one password spelling.
        try:
            if not reader.is_encrypted:
                return ""
            return decrypt_pypdf(reader, pwd)
        finally:
            reader.close()
    except Exception:
        return None
