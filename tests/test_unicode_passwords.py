"""Regression tests for Unicode PDF password handling.

The bug: the user typed the correct password, the prompt accepted it,
the viewer opened the document -- and every tool then reported "wrong
password" while the thumbnail strip stayed blank.

Root cause: the cache write sites ran the accepted password through
``unicodedata.normalize("NFC", ...)``. NFC matches *neither* engine:

* MuPDF (PyMuPDF) does not normalise at all -- it hashes the raw
  UTF-8 bytes for R>=5 (``pdf_saslprep_from_utf8`` in ``pdf-crypt.c`` is
  a documented stub).
* pypdf >= 6.12 implements SASLprep (RFC 4013) in full, whose
  normalisation step is **NFKC**, and applies it to ``str`` passwords
  whenever ``V >= 5``.

So the app invented a third spelling and then fed it to two engines that
wanted the other two.

Second, opposite bug: the encrypt tool writes AES-256 through pypdf,
which SASLpreps the password on the way in. A password containing
U+FB01 (LATIN SMALL LIGATURE FI) is stored as "fi" but handed back to
PyMuPDF as U+FB01, so the app produced files it could not itself reopen.
NFC does not reveal this one -- U+FB01's decomposition is a
*compatibility* decomposition, which NFC preserves and only NFKC folds.

Everything here is behavioural. There is deliberately no assertion on
source text: the previous guards for this area asserted the literal line
``self._pdf_password = normalize_password(pwd)``, which pinned the bug
in place instead of testing anything.
"""

from __future__ import annotations

import os
import sys
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

_unused_app = QApplication.instance() or QApplication([])

import pymupdf  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402

from app.base import BasePage  # noqa: E402
from app.tools.encrypt import _pwd_cache_key  # noqa: E402
from app.pdf_password import (  # noqa: E402
    authenticate_pymupdf,
    decrypt_pypdf,
    password_candidates,
    pypdf_password_forms,
    saslprep,
)

# Built from code points instead of literal glyphs: an editor, a git
# filter or a copy-paste that normalised this file would silently
# disarm every test below (NFD would become NFC and U+FB01 "fi").
NFD = "cafe" + chr(0x0301)      # 'e' + COMBINING ACUTE ACCENT
NFC = "caf" + chr(0x00E9)       # LATIN SMALL LETTER E WITH ACUTE
FI = "of" + chr(0xFB01) + "ce"  # LATIN SMALL LIGATURE FI
FI_FOLDED = "office"
SOFT_HYPHEN = chr(0x00AD)       # stringprep table B.1 -> mapped away
NBSP = chr(0x00A0)              # table C.1.2 -> mapped to U+0020
BEL = chr(0x0007)               # table C.2.1 -> prohibited output
ARABIC_ALEF = chr(0x0627)       # table D.1 -> RandALCat
EMOJI = chr(0x1F600)            # table A.1: unassigned in Unicode 3.2
UNASSIGNED = chr(0x0378)        # table A.1, still unassigned today
FULLWIDTH = chr(0xFF21) + "bc"  # NFKC -> "Abc"

assert unicodedata.normalize("NFC", NFD) == NFC
assert unicodedata.normalize("NFC", FI) == FI, (
    "U+FB01 has a compatibility decomposition, which NFC preserves; "
    "that is exactly why the NFC-based code could not see this bug."
)


# ── fixtures ─────────────────────────────────────────────────────────────


def _plain_pdf(tmp_path: Path, pages: int = 2) -> str:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    out = str(tmp_path / "plain.pdf")
    doc.save(out)
    doc.close()
    return out


def _encrypt_raw(tmp_path: Path, pwd: str, name: str,
                 algorithm: str = "AES-256") -> str:
    """Lock a PDF with the *exact UTF-8 bytes* of ``pwd``.

    ``PdfWriter.encrypt`` is annotated ``str`` but ``_encode_password``
    passes a ``bytes`` argument straight through, skipping SASLprep and
    Latin-1. That is what we need to emulate a producer that does not
    normalise (MuPDF, pikepdf/QPDF, and most commercial writers): with a
    ``str`` password pypdf would helpfully NFKC the fixture and the test
    would silently stop reproducing the bug.
    """
    plain = _plain_pdf(tmp_path)
    w = PdfWriter()
    w.append(PdfReader(plain))
    w.encrypt(user_password=pwd.encode("utf-8"),   # type: ignore[arg-type]
              owner_password=pwd.encode("utf-8"),  # type: ignore[arg-type]
              algorithm=algorithm)
    out = str(tmp_path / name)
    with open(out, "wb") as fh:
        w.write(fh)
    return out


def _encrypt_via_pypdf_str(tmp_path: Path, pwd: str, name: str,
                           algorithm: str = "AES-256") -> str:
    """Lock a PDF the way pypdf does for a ``str`` password.

    For AES-256 that means SASLprep(NFKC) then UTF-8, i.e. the ISO
    32000-2 conformant spelling.
    """
    plain = _plain_pdf(tmp_path)
    w = PdfWriter()
    w.append(PdfReader(plain))
    w.encrypt(user_password=pwd, owner_password=pwd, algorithm=algorithm)
    out = str(tmp_path / name)
    with open(out, "wb") as fh:
        w.write(fh)
    return out


def _cached(pwd: str):
    """A minimal stand-in for a tool page holding a cached password."""

    class _Stub:
        _pdf_password = pwd
        _open_reader = BasePage._open_reader
        _open_pymupdf = BasePage._open_pymupdf

    return _Stub()


# ── app.pdf_password unit tests ──────────────────────────────────────────


def test_saslprep_folds_compatibility_ligature():
    """NFKC, not NFC. This single assertion is the whole second bug."""
    assert saslprep(FI) == FI_FOLDED
    assert unicodedata.normalize("NFC", FI) == FI, (
        "U+FB01 must survive NFC, otherwise the fixture proves nothing."
    )


def test_saslprep_maps_and_normalises():
    # RFC 4013 §2.1: table B.1 (soft hyphen) maps to nothing...
    assert saslprep("a" + SOFT_HYPHEN + "b") == "ab"
    # ...and table C.1.2 (non-ASCII space) maps to U+0020.
    assert saslprep("a" + NBSP + "b") == "a b"
    # §2.2: NFKC composes the decomposed form.
    assert saslprep(NFD) == NFC


def test_saslprep_rejects_prohibited_and_bidi():
    with pytest.raises(ValueError):
        saslprep("a" + BEL + "b")      # §2.3, table C.2.1 ASCII control
    with pytest.raises(ValueError):
        # §2.4: a RandALCat string must also END with RandALCat.
        saslprep(ARABIC_ALEF + "1")


def test_candidates_are_ordered_deduped_and_exclude_nfd():
    """raw, SASLprep(raw), NFC(raw) -- in that order, never NFD."""
    assert password_candidates("abc") == ["abc"]
    assert password_candidates(FI) == [FI, FI_FOLDED]
    # For NFD input SASLprep and NFC agree, so only two survive.
    assert password_candidates(NFD) == [NFD, NFC]
    for cand in password_candidates(NFC):
        assert unicodedata.is_normalized("NFC", cand), (
            "NFD must never be manufactured as a candidate: no producer "
            "canonicalises to it, and the user's own typing already "
            "covers that case via the raw candidate."
        )


def test_pypdf_forms_offer_raw_utf8_bytes_first():
    """Bytes first: that branch of pypdf skips SASLprep/Latin-1 entirely,
    which is what gives byte-for-byte parity with MuPDF for R>=5."""
    forms = pypdf_password_forms(NFD)
    assert forms[0] == (NFD, NFD.encode("utf-8"))
    assert all(isinstance(a, bytes) for _, a in forms[:2])
    # Non-ASCII candidates are re-offered as str so pypdf applies its own
    # Latin-1 encoding for V<5 (the R<=4 escape hatch).
    assert (NFC, NFC) in forms


def test_pypdf_forms_do_not_duplicate_ascii_attempts():
    """ASCII is the hot path: Latin-1, UTF-8 and SASLprep all agree, so
    exactly one attempt must be generated."""
    assert pypdf_password_forms("topsecret") == [("topsecret", b"topsecret")]


# ── 1. NFD round trip (the reported bug) ─────────────────────────────────


def test_nfd_locked_file_opens_in_both_engines(tmp_path):
    """A file locked with raw NFD bytes, unlocked with the typed NFD form.

    Before the fix: the prompt accepted (PyMuPDF hashes raw bytes), the
    cache stored NFC, and ``_open_reader`` raised ``Incorrect password``
    because pypdf SASLpreps a ``str`` back to NFC-but-hashed-differently
    -- while ``_open_pymupdf`` also failed, leaving thumbnails blank.
    """
    path = _encrypt_raw(tmp_path, NFD, "nfd.pdf")

    # These two assertions ARE the old bug, pinned so the discrimination
    # survives the deletion of ``normalize_password``: the NFC spelling
    # that used to be written into the cache authenticates in NEITHER
    # engine. Whatever the helpers do internally, they cannot succeed by
    # canonicalising to NFC.
    probe = pymupdf.open(path)
    try:
        assert probe.authenticate(NFC) == 0
    finally:
        probe.close()
    assert PdfReader(path).decrypt(NFC) == 0

    stub = _cached(NFD)
    doc = stub._open_pymupdf(path)
    try:
        assert doc.page_count == 2
    finally:
        doc.close()
    assert len(stub._open_reader(path).pages) == 2


# ── 2. Inverse round trip: NFC file, NFD typed ───────────────────────────


def test_nfc_locked_file_accepts_typed_nfd(tmp_path, monkeypatch):
    """macOS keystrokes arrive decomposed; the file is composed.

    Exercised through ``prompt_pdf_password`` because that is where the
    old code compared the raw typed string and nothing else -- an NFD
    typist could never get past the dialog on an NFC-locked file.
    """
    from app import utils
    from app.editor import dialogs

    path = _encrypt_raw(tmp_path, NFC, "nfc.pdf")

    # The dialog gives up after three tries. prompt_pdf_password loops
    # until the user cancels, so a fake that always accepts would turn a
    # regression into an infinite hang instead of a failure.
    attempts = {"n": 0}

    class _FakeDialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            attempts["n"] += 1
            return (QDialog.DialogCode.Accepted if attempts["n"] <= 3
                    else QDialog.DialogCode.Rejected)

        def password(self):
            return NFD

    monkeypatch.setattr(dialogs, "_PdfPasswordDialog", _FakeDialog)
    ok, pwd = utils.prompt_pdf_password(path, None)
    assert ok is True, "typed NFD must be accepted on the first attempt"
    assert attempts["n"] == 1
    assert pwd == NFC, "prompt must return the spelling that authenticated"

    stub = _cached(pwd)
    doc = stub._open_pymupdf(path)
    try:
        assert doc.page_count == 2
    finally:
        doc.close()
    assert len(stub._open_reader(path).pages) == 2


# ── 3. U+FB01 through the encrypt tool (second bug) ──────────────────────


def _encrypt_with_tool(tmp_path, monkeypatch, typed: str, name: str):
    """Drive the real ``TabEncriptar`` and return ``(page, out_path)``."""
    from PySide6.QtWidgets import QMessageBox

    from app.tools.encrypt import TabEncriptar

    src = _plain_pdf(tmp_path)
    out = str(tmp_path / name)

    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))

    page = TabEncriptar(lambda *a, **k: None)
    # drop_in first: set_path fires path_changed -> _load_input, which
    # rewrites drop_out from the input name.
    page.drop_in.set_path(src)
    page.drop_out.set_path(out)
    page.cmb_mode.setCurrentIndex(0)
    page.edit_owner.setText(typed)
    page.edit_owner_confirm.setText(typed)
    page.edit_user.setText(typed)
    page._run()
    assert os.path.isfile(out)
    return page, out


# Passwords that combine a code point unassigned in Unicode 3.2 (every
# emoji, plus U+0378) with something NFKC rewrites (a ligature, a
# fullwidth letter, a decomposed sequence). pypdf's own SASLprep raises
# on the unassigned code point and falls back to raw UTF-8, so any
# attempt to *predict* the written spelling is wrong for exactly these.
_TOOL_PASSWORDS = [
    pytest.param(NFD, id="nfd"),
    pytest.param(FI, id="ligature"),
    pytest.param(FULLWIDTH, id="fullwidth"),
    pytest.param("topsecret", id="ascii"),
    pytest.param(NFD + EMOJI, id="nfd+emoji"),
    pytest.param(FI + EMOJI, id="ligature+emoji"),
    pytest.param(FI + UNASSIGNED, id="ligature+unassigned"),
    pytest.param(NFD + UNASSIGNED, id="nfd+unassigned"),
    pytest.param(FULLWIDTH + EMOJI, id="fullwidth+emoji"),
]


@pytest.mark.parametrize("typed", _TOOL_PASSWORDS)
def test_encrypt_tool_can_reopen_what_it_just_wrote(tmp_path, monkeypatch,
                                                    typed):
    """The app must be able to reopen the file it just wrote.

    ``TabEncriptar`` encrypts with pypdf AES-256, which SASLpreps a
    ``str`` password; reopening goes through PyMuPDF, which does not. So the
    recorded spelling must come from the bytes on disk, never from a
    prediction: pypdf silently falls back to raw UTF-8 whenever its own
    SASLprep raises, which is the case for every emoji-bearing password
    (RFC 4013 §2.5, unassigned in Unicode 3.2).

    Five of these nine passwords produced a file the app rejected before
    this fix.
    """
    from app.editor import dialogs

    page, out = _encrypt_with_tool(tmp_path, monkeypatch, typed,
                                   "locked.pdf")

    recorded = page._written_pwd[_pwd_cache_key(out)]
    probe = pymupdf.open(out)
    try:
        assert probe.needs_pass
        assert probe.authenticate(recorded) != 0, (
            f"recorded spelling {ascii(recorded)} does not unlock the file "
            f"the tool just wrote for typed {ascii(typed)}"
        )
    finally:
        probe.close()

    # Candidate expansion recovers the on-disk spelling from what the
    # user typed, so a user who re-opens the file by hand also gets in.
    doc = pymupdf.open(out)
    try:
        assert authenticate_pymupdf(doc, typed) == recorded
    finally:
        doc.close()

    # Reloading the tool's own output must not re-prompt, and the cached
    # value must be usable raw by both engines.
    def _boom(*a, **k):
        raise AssertionError("must not prompt for a password we just set")

    monkeypatch.setattr(dialogs, "_PdfPasswordDialog", _boom)
    page._load_input(out)
    assert page._pdf_password == recorded
    assert len(page._open_reader(out).pages) == 2
    reopened = page._open_pymupdf(out)
    try:
        assert reopened.page_count == 2
    finally:
        reopened.close()


def test_encrypt_tool_records_probed_spelling_not_a_prediction(tmp_path,
                                                               monkeypatch):
    """U+FB01 alone: pypdf SASLpreps it, so disk holds "office".

    Asserted against the file rather than against ``saslprep(typed)`` so
    the test states what the tool must *achieve* (record whatever really
    locks the file) instead of what a given pypdf release happens to do.
    """
    page, out = _encrypt_with_tool(tmp_path, monkeypatch, FI, "fi.pdf")
    recorded = page._written_pwd[_pwd_cache_key(out)]

    probe = pymupdf.open(out)
    try:
        assert probe.authenticate(recorded) != 0
    finally:
        probe.close()
    assert recorded in (FI, FI_FOLDED)
    if recorded == FI_FOLDED:
        # The interesting branch: the tool wrote a spelling the user
        # never typed, and knows it.
        probe = pymupdf.open(out)
        try:
            assert probe.authenticate(FI) == 0
        finally:
            probe.close()


def test_encrypt_tool_owner_only_output_records_an_empty_password(
        tmp_path, monkeypatch):
    """Owner password set, user password empty: the file opens freely.

    ``_cache_written_password`` must record "" for it, not the owner
    password, otherwise reloading the tool's own output seeds a value
    that unlocks nothing. Probing the file answers this for free; a
    prediction has to special-case it.
    """
    from PySide6.QtWidgets import QMessageBox

    from app.editor import dialogs
    from app.tools.encrypt import TabEncriptar

    src = _plain_pdf(tmp_path)
    out = str(tmp_path / "owner_only.pdf")
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))

    page = TabEncriptar(lambda *a, **k: None)
    page.drop_in.set_path(src)
    page.drop_out.set_path(out)
    page.cmb_mode.setCurrentIndex(0)
    page.edit_owner.setText(FI)
    page.edit_owner_confirm.setText(FI)
    page.edit_user.setText("")
    page._run()

    assert os.path.isfile(out)
    assert page._written_pwd[_pwd_cache_key(out)] == ""

    def _boom(*a, **k):
        raise AssertionError("an owner-only PDF must not prompt")

    monkeypatch.setattr(dialogs, "_PdfPasswordDialog", _boom)
    page._load_input(out)
    assert page._pdf_password == ""
    assert len(page._open_reader(out).pages) == 2


def test_encrypt_tool_probes_the_output_instead_of_predicting(tmp_path,
                                                              monkeypatch):
    """The recorded spelling must survive a change of pypdf behaviour.

    pypdf only grew its SASLprep-on-write in 6.12; 6.10.x hashes the raw
    UTF-8 of a ``str`` password, and its ``bytes`` branch always has. We
    emulate such a producer by handing the writer ``bytes`` (the
    documented ``_encode_password`` bypass) and assert the tool still
    knows how its own output is locked.

    A tool that *predicts* ``saslprep(typed)`` records "office" for a
    file locked with U+FB01 and then cannot reopen what it just wrote --
    which is what the reviewer measured on WSL with pypdf 6.10.2.
    """
    from app.tools import encrypt as encrypt_mod
    from app.editor import dialogs

    real_writer = encrypt_mod.PdfWriter

    class _LegacyWriter(real_writer):
        def encrypt(self, user_password, owner_password=None, **kw):
            def _raw(v):
                return v.encode("utf-8") if isinstance(v, str) else v
            return super().encrypt(user_password=_raw(user_password),
                                   owner_password=_raw(owner_password), **kw)

    monkeypatch.setattr(encrypt_mod, "PdfWriter", _LegacyWriter)

    page, out = _encrypt_with_tool(tmp_path, monkeypatch, FI, "legacy.pdf")

    recorded = page._written_pwd[_pwd_cache_key(out)]
    assert recorded == FI, (
        "this producer did not fold the ligature, so the typed spelling "
        "is what locks the file -- a predicted saslprep() would record "
        f"{ascii(FI_FOLDED)} and lock the app out of its own output"
    )
    probe = pymupdf.open(out)
    try:
        assert probe.authenticate(recorded) != 0
    finally:
        probe.close()

    def _boom(*a, **k):
        raise AssertionError("must not prompt for a password we just set")

    monkeypatch.setattr(dialogs, "_PdfPasswordDialog", _boom)
    page._load_input(out)
    assert page._pdf_password == FI
    assert len(page._open_reader(out).pages) == 2


def test_encrypt_tool_drops_a_stale_written_password(tmp_path, monkeypatch):
    """A2: the seed must be verified against the file, not trusted.

    Encrypt A -> B with PPP, let something else overwrite B, reload B.
    Copying the stale entry onto ``_pdf_password`` unconditionally left
    the tool holding PPP for a file locked with QQQ -- and, because the
    cache survives a cancelled prompt, a *third* PPP file then opened
    with no prompt at all.
    """
    import shutil

    from app.editor import dialogs

    page, out = _encrypt_with_tool(tmp_path, monkeypatch, "PPP", "b.pdf")
    assert page._written_pwd[_pwd_cache_key(out)] == "PPP"
    assert page._pdf_password == ""      # the source was a plain PDF

    shutil.copyfile(_encrypt_raw(tmp_path, "QQQ", "qqq.pdf"), out)

    class _Cancel:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return QDialog.DialogCode.Rejected

        def password(self):
            return ""

    monkeypatch.setattr(dialogs, "_PdfPasswordDialog", _Cancel)
    page._load_input(out)

    assert page._pdf_password == "", (
        "a stale written-password entry must not be copied onto the cache"
    )
    assert _pwd_cache_key(out) not in page._written_pwd


def test_encrypt_tool_does_not_clobber_the_source_password(tmp_path,
                                                           monkeypatch):
    """Re-encrypting an already-encrypted source must stay re-runnable.

    The written-password cache is keyed by output path precisely so it
    cannot overwrite ``_pdf_password``, which still belongs to the input.
    """
    from PySide6.QtWidgets import QMessageBox

    from app.tools.encrypt import TabEncriptar

    src = _encrypt_raw(tmp_path, "sourcepw", "src_enc.pdf")
    out = str(tmp_path / "relocked.pdf")

    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))

    page = TabEncriptar(lambda *a, **k: None)
    page._pdf_password = "sourcepw"
    page.drop_in.set_path(src)
    page.drop_out.set_path(out)
    page.cmb_mode.setCurrentIndex(0)
    for field in (page.edit_owner, page.edit_owner_confirm, page.edit_user):
        field.setText("newpw")
    page._run()

    assert page._pdf_password == "sourcepw"
    # A second run against the same source must still authenticate.
    assert len(page._open_reader(src).pages) == 2


# ── 4. ASCII control ─────────────────────────────────────────────────────


@pytest.mark.parametrize("algorithm", ["AES-256", "AES-128", "RC4-128"])
def test_ascii_password_unchanged_at_every_layer(tmp_path, algorithm):
    path = _encrypt_via_pypdf_str(tmp_path, "topsecret",
                                  f"ascii_{algorithm}.pdf", algorithm)
    stub = _cached("topsecret")
    doc = stub._open_pymupdf(path)
    try:
        assert doc.page_count == 2
    finally:
        doc.close()
    assert len(stub._open_reader(path).pages) == 2

    probe = pymupdf.open(path)
    try:
        assert authenticate_pymupdf(probe, "topsecret") == "topsecret"
    finally:
        probe.close()
    assert decrypt_pypdf(PdfReader(path), "topsecret") == "topsecret"


def test_wrong_password_still_raises(tmp_path):
    """Candidate expansion must not turn a wrong password into a right
    one, and must not fall back to a silently empty reader.

    The type is asserted, not just the fact of raising:
    ``WrongPasswordError`` is what ``show_error`` keys on to present a
    warning instead of a crash dialog, and it is deliberately not a
    ``ValueError`` so compress's "no gain" handler cannot swallow it.
    """
    from app.utils import WrongPasswordError

    path = _encrypt_raw(tmp_path, NFD, "nfd_wrong.pdf")
    stub = _cached("definitely-not-it")
    with pytest.raises(WrongPasswordError):
        stub._open_reader(path)
    with pytest.raises(WrongPasswordError):
        stub._open_pymupdf(path)


# ── 5. Engine parity ─────────────────────────────────────────────────────


@pytest.mark.parametrize("locked_with,typed", [
    (NFD, NFD),
    (NFC, NFD),
    (NFC, NFC),
    (FI_FOLDED, FI),
    ("topsecret", "topsecret"),
])
def test_open_helpers_agree_for_the_same_cached_password(tmp_path,
                                                         locked_with, typed):
    """Whatever the cache holds, pypdf and PyMuPDF must reach the same
    verdict. The reported symptom was exactly this disagreement: viewer
    open, tools "wrong password"."""
    path = _encrypt_raw(tmp_path, locked_with,
                        f"parity_{abs(hash((locked_with, typed)))}.pdf")

    probe = pymupdf.open(path)
    try:
        winner = authenticate_pymupdf(probe, typed)
    finally:
        probe.close()
    assert winner is not None

    stub = _cached(winner)
    doc = stub._open_pymupdf(path)
    try:
        pymupdf_pages = doc.page_count
    finally:
        doc.close()
    assert pymupdf_pages == len(stub._open_reader(path).pages) == 2


# ── R<=4 (no canonical form) best-effort guard ───────────────────────────


@pytest.mark.parametrize("algorithm", ["AES-128", "RC4-128"])
def test_legacy_revision_non_ascii_password_still_opens(tmp_path, algorithm):
    """R<=4 defers to the "host system code page", so there is no
    canonical form to converge on: pypdf encodes ``str`` as Latin-1 and
    MuPDF maps UTF-8 to PDFDocEncoding.

    Feeding pypdf raw UTF-8 bytes alone would REGRESS these files, which
    is why non-ASCII candidates are also offered as ``str``. Without that
    second pass this test fails.
    """
    path = _encrypt_via_pypdf_str(tmp_path, NFC, f"legacy_{algorithm}.pdf",
                                  algorithm)
    # The Latin-1 and UTF-8 encodings genuinely differ here.
    assert NFC.encode("latin-1") != NFC.encode("utf-8")
    assert PdfReader(path).decrypt(NFC.encode("utf-8")) == 0

    stub = _cached(NFC)
    assert len(stub._open_reader(path).pages) == 2
    doc = stub._open_pymupdf(path)
    try:
        assert doc.page_count == 2
    finally:
        doc.close()


# ── secondary password caches must be wiped too ──────────────────────────


def test_wipe_clears_secondary_password_caches():
    from app.utils import wipe_pdf_password

    class _Obj:
        def __init__(self):
            self._pdf_password = "s3cret"
            self._pwd_map = {"a.pdf": "one"}
            self._written_pwd = {"b.pdf": "two"}

    obj = _Obj()
    wipe_pdf_password(obj)
    assert obj._pdf_password == ""
    assert obj._pwd_map == {}
    assert obj._written_pwd == {}


def test_wipe_still_works_without_secondary_caches():
    from app.utils import wipe_pdf_password

    class _Obj:
        _pdf_password = "s3cret"

    obj = _Obj()
    wipe_pdf_password(obj)
    assert obj._pdf_password == ""


# -- RFC 4013 section 2.5: unassigned code points ------------------------


def test_saslprep_rejects_unassigned_code_points():
    """RFC 4013 §2.5: a *stored* string must reject table A.1 (unassigned
    in Unicode 3.2). Every emoji lands there.

    Omitting A.1 made our SASLprep succeed where pypdf's fails, so our
    candidate list disagreed with the bytes pypdf actually hashes.
    """
    with pytest.raises(ValueError):
        saslprep(EMOJI)
    with pytest.raises(ValueError):
        saslprep("a" + UNASSIGNED)
    # And the whole password loses its SASLprep candidate as a result --
    # which is exactly what pypdf does (it logs and falls back to raw
    # UTF-8), so the two sides agree again.
    assert password_candidates(NFD + EMOJI) == [NFD + EMOJI, NFC + EMOJI]
    assert password_candidates(FI + EMOJI) == [FI + EMOJI]


def test_nfc_candidate_recovers_an_unassigned_code_point_password(tmp_path):
    """The NFC candidate is load-bearing, not decoration.

    When SASLprep bails out (unassigned code point) NFC is the only
    remaining candidate that can bridge a macOS NFD typist to a file
    locked with the composed spelling.
    """
    path = _encrypt_raw(tmp_path, NFC + EMOJI, "emoji_nfc.pdf")

    probe = pymupdf.open(path)
    try:
        assert probe.authenticate(NFD + EMOJI) == 0, (
            "fixture broken: the typed spelling must NOT open the file"
        )
    finally:
        probe.close()

    doc = pymupdf.open(path)
    try:
        assert authenticate_pymupdf(doc, NFD + EMOJI) == NFC + EMOJI
    finally:
        doc.close()

    stub = _cached(NFC + EMOJI)
    assert len(stub._open_reader(path).pages) == 2


def test_decrypt_pypdf_returns_the_exact_spelling_it_used(tmp_path):
    """The return value is consumed as a *value*, not as a boolean.

    ``_compress_pdf`` rebinds its ``password`` local to it and hands that
    to Ghostscript / PyMuPDF / pikepdf, so canonicalising the winner on
    the way out would re-introduce the very divergence this module exists
    to remove.
    """
    path = _encrypt_raw(tmp_path, NFD, "dec_exact.pdf")
    winner = decrypt_pypdf(PdfReader(path), NFD)
    assert winner == NFD
    assert PdfReader(path).decrypt(winner.encode("utf-8")) != 0


# -- BasePage._maybe_prompt_password re-anchors on the new file ----------


def test_maybe_prompt_password_reanchors_the_cache_on_the_new_file(
        tmp_path, monkeypatch):
    """A cached password from file A must be re-anchored for file B.

    Same typed password, two files locked with two different spellings of
    it (a producer that SASLpreps, and one that does not). Without
    re-anchoring, ``_maybe_prompt_password`` still returns True -- the
    candidate list opens B -- but leaves A's spelling in the cache, and
    the ~23 raw ``self._pdf_password`` reads under ``tools/`` then fail
    in BOTH engines. That is the original symptom, one file later.
    """
    from app.editor import dialogs
    from app.tools.encrypt import TabEncriptar

    file_a = _encrypt_raw(tmp_path, NFD, "anchor_a.pdf")
    file_b = _encrypt_raw(tmp_path, NFC, "anchor_b.pdf")

    def _boom(*a, **k):
        raise AssertionError("must not prompt: a candidate unlocks file B")

    monkeypatch.setattr(dialogs, "_PdfPasswordDialog", _boom)

    page = TabEncriptar(lambda *a, **k: None)
    try:
        page._pdf_password = NFD                  # anchored on file A
        assert page._maybe_prompt_password(file_a) is True
        assert page._pdf_password == NFD

        assert page._maybe_prompt_password(file_b) is True
        assert page._pdf_password == NFC, (
            "the cache must hold the spelling that unlocked THIS file"
        )
        probe = pymupdf.open(file_b)
        try:
            assert probe.authenticate(page._pdf_password) != 0, (
                "a raw read of self._pdf_password must authenticate file B"
            )
        finally:
            probe.close()
        assert len(page._open_reader(file_b).pages) == 2
    finally:
        page.deleteLater()


# -- PdfViewerPanel: cache write site + thumbnail rendering --------------


def _fake_password_dialog(pwd: str, attempts: dict):
    """Dialog stub that accepts three times then cancels.

    The real dialog gives up after three tries; ``load`` and
    ``prompt_pdf_password`` loop until the user cancels, so a stub that
    always accepts would turn a regression into an infinite hang instead
    of a red test.
    """

    class _FakeDialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            attempts["n"] += 1
            return (QDialog.DialogCode.Accepted if attempts["n"] <= 3
                    else QDialog.DialogCode.Rejected)

        def password(self):
            return pwd

    return _FakeDialog


def _wait_for_thumbnails(panel, want: int, timeout_ms: int = 15000) -> None:
    from PySide6.QtTest import QTest
    waited = 0
    while panel._thumbnails._model.cache_size() < want and waited < timeout_ms:
        QTest.qWait(50)
        waited += 50


def test_viewer_panel_caches_the_spelling_that_unlocked_the_document(
        tmp_path, monkeypatch):
    """The reported symptom, end to end, in the widget it was seen in.

    The panel used to store ``NFC(typed)``. For a file locked with the
    raw NFD bytes that value opens nothing: it is propagated verbatim to
    the canvas, to ``ThumbnailWorker`` (whose ``doc.authenticate`` then
    fails, leaving ``page_count == 0`` and the "rendered 0/2 pages"
    warning) and, via ``MainWindow._on_tab_changed``, to every tool.
    """
    from PySide6.QtCore import Qt

    from app.editor import dialogs
    from app.viewer.panel import PdfViewerPanel

    path = _encrypt_raw(tmp_path, NFD, "panel_nfd.pdf")
    attempts = {"n": 0}
    monkeypatch.setattr(dialogs, "_PdfPasswordDialog",
                        _fake_password_dialog(NFD, attempts))

    panel = PdfViewerPanel()
    try:
        panel.load(path)
        assert attempts["n"] == 1, "the typed spelling must be accepted first"
        assert panel._pdf_password == NFD, (
            "the panel must cache the spelling that authenticated, not a "
            "canonicalised one"
        )
        assert panel._pymupdf_doc is not None
        assert panel._pymupdf_doc.page_count == 2

        model = panel._thumbnails._model
        assert model.rowCount() == 2
        _wait_for_thumbnails(panel, 2)
        for row in range(2):
            pix = model.data(model.index(row), Qt.ItemDataRole.DecorationRole)
            assert pix is not None and not pix.isNull(), (
                f"thumbnail row {row} never rendered -- the worker was "
                f"handed a password that does not unlock the document"
            )
    finally:
        panel._thumbnails.clear()
        panel.deleteLater()


def test_viewer_panel_caches_the_winning_candidate_not_the_typed_string(
        tmp_path, monkeypatch):
    """The panel must cache what *authenticated*, not what was typed.

    The test above only proves the panel does not mangle a spelling that
    already works: for a file locked with the typed bytes, a bare
    ``doc.authenticate(typed)`` caches the same string that
    ``authenticate_pymupdf`` would return, so reverting the call site keeps
    it green. It does not discriminate.

    Here the two values are forced apart. The file is sealed by MuPDF
    with "office" (the NFKC-folded spelling); the dialog returns
    "of<U+FB01>ce" (the ligature). MuPDF hashes raw UTF-8, so the typed
    string opens nothing -- only candidate 2, ``saslprep(typed)``, does.
    A call site that stores ``dlg.password()`` therefore caches a
    password that does not unlock the document it just opened, and hands
    that dead string to the canvas, to ``ThumbnailWorker`` and (via
    ``MainWindow._try_auto_load``) to every tool: the blank thumbnail
    strip described at app/viewer/panel.py's cache write site.
    """
    from PySide6.QtCore import Qt

    from app.editor import dialogs
    from app.viewer.panel import PdfViewerPanel

    path = _mupdf_sealed(tmp_path, FI_FOLDED, "panel_ligature.pdf", pages=2)
    # Guard the fixture: if the typed spelling ever opened this file
    # directly the test would be vacuous, because both call sites would
    # cache the same string.
    probe = pymupdf.open(path)
    try:
        assert probe.needs_pass
        assert not probe.authenticate(FI), (
            "MuPDF accepted the ligature spelling -- the fixture no "
            "longer forces typed and winning apart"
        )
        assert probe.authenticate(FI_FOLDED)
    finally:
        probe.close()

    attempts = {"n": 0}
    monkeypatch.setattr(dialogs, "_PdfPasswordDialog",
                        _fake_password_dialog(FI, attempts))

    panel = PdfViewerPanel()
    try:
        panel.load(path)
        assert attempts["n"] == 1, (
            "the prompt looped -- the candidate list never unlocked the file"
        )
        assert panel._pdf_password == FI_FOLDED, (
            "the panel cached the typed spelling instead of the candidate "
            "that authenticated"
        )
        assert panel._pdf_password != FI

        # The concrete downstream symptom: both consumers are handed the
        # cached value verbatim, and a dead password leaves the strip blank.
        assert panel._canvas._password == FI_FOLDED
        assert panel._thumbnails._password == FI_FOLDED

        model = panel._thumbnails._model
        assert model.rowCount() == 2
        _wait_for_thumbnails(panel, 2)
        for row in range(2):
            pix = model.data(model.index(row), Qt.ItemDataRole.DecorationRole)
            assert pix is not None and not pix.isNull(), (
                f"thumbnail row {row} never rendered -- the worker was "
                f"handed a password that does not unlock the document"
            )
    finally:
        panel._thumbnails.clear()
        panel.deleteLater()


# -- TabEditar: same two properties -------------------------------------


def test_editor_tab_caches_the_spelling_that_unlocked_the_document(
        tmp_path, monkeypatch):
    """Editor counterpart of the panel test: the prompt path."""
    from app.editor import dialogs
    from app.editor.tab import TabEditar

    path = _encrypt_raw(tmp_path, NFD, "editor_nfd.pdf")
    attempts = {"n": 0}
    monkeypatch.setattr(dialogs, "_PdfPasswordDialog",
                        _fake_password_dialog(NFD, attempts))

    tab = TabEditar(lambda *a, **k: None)
    try:
        tab._load_pdf(path)
        assert attempts["n"] == 1
        assert tab._pdf_password == NFD
        assert tab._canvas.page_count() == 2, (
            "the canvas holds a locked document -- page_count 0 is the "
            "blank-editor symptom"
        )
    finally:
        tab._canvas.close_doc()
        tab.deleteLater()


def test_editor_tab_reanchors_a_password_propagated_from_the_viewer(
        tmp_path, monkeypatch):
    """``_load_pdf``'s silent-retry branch must expand candidates.

    ``MainWindow._on_tab_changed`` copies the viewer's cached password
    onto the editor. When the editor then opens a file locked with a
    different spelling of the same password, a raw
    ``probe.authenticate(self._pdf_password)`` clears the cache and
    prompts the user for a password they already gave.
    """
    from app.editor import dialogs
    from app.editor.tab import TabEditar

    path = _encrypt_raw(tmp_path, NFC, "editor_prop.pdf")

    def _boom(*a, **k):
        raise AssertionError(
            "must not prompt: the propagated password unlocks this file")

    monkeypatch.setattr(dialogs, "_PdfPasswordDialog", _boom)

    tab = TabEditar(lambda *a, **k: None)
    try:
        tab._pdf_password = NFD          # what the viewer propagated
        tab._load_pdf(path)
        assert tab._pdf_password == NFC
        assert tab._canvas.page_count() == 2
        assert len(_cached(tab._pdf_password)._open_reader(path).pages) == 2
    finally:
        tab._canvas.close_doc()
        tab.deleteLater()


# -- wrong password must never yield a silently empty document ----------


def test_wrong_password_never_produces_a_zero_page_merge(tmp_path,
                                                         monkeypatch):
    """Behavioural replacement for the ``.decrypt(...) == 0`` text guard.

    ``PdfReader.decrypt`` returns 0 and hands back a reader whose
    ``pages`` is empty. Merging that writes a valid-looking PDF with the
    encrypted input silently missing.
    """
    from app.tools.merge import TabJuntar

    good = _plain_pdf(tmp_path)
    locked = _encrypt_raw(tmp_path, NFD, "merge_locked.pdf")
    out = str(tmp_path / "merged.pdf")

    errors = []
    monkeypatch.setattr("app.tools.merge.show_error",
                        lambda *a, **k: errors.append(a))

    page = TabJuntar(lambda *a, **k: None)
    try:
        page.lst.addItem(good)
        page.lst.addItem(locked)
        page._pwd_map[locked] = "definitely-not-it"
        page.drop_out.set_path(out)
        page._run()

        assert errors, "a wrong password must surface an error"
        assert not os.path.isfile(out), (
            "the merge wrote an output file despite one input never being "
            "decrypted -- that file is silently missing its pages"
        )
    finally:
        page.deleteLater()


def test_editor_form_loader_reports_failure_on_a_wrong_password(tmp_path):
    """A locked reader yields zero fields, which used to be shown to the
    user as the cheerful "this PDF has no form fields"."""
    from app.editor.tab import TabEditar
    from app.i18n import t

    path = _encrypt_raw(tmp_path, NFD, "forms_locked.pdf")

    tab = TabEditar(lambda *a, **k: None)
    try:
        tab._pdf_password = "definitely-not-it"
        tab._load_form_fields(path)
        assert tab._form_table.rowCount() == 0
        assert tab._form_status.text() == t("editor.forms.load_failed"), (
            "a wrong password must not be reported as 'no fields'"
        )
    finally:
        tab.deleteLater()


# -- every cached password dies with the window -------------------------


def test_main_window_close_wipes_every_password_cache(tmp_path, monkeypatch):
    """A1: the real ``closeEvent``, not a synthetic stand-in.

    ``BasePage._clear_pdf_password`` had no production call site that
    reached the tool pages, and Qt does not deliver ``closeEvent`` to
    child widgets, so the viewer's own handler never fired either. All
    four deposits survived until the process died.
    """
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtTest import QTest

    from app.editor.tab import TabEditar
    from app.tools.encrypt import TabEncriptar
    from app.tools.merge import TabJuntar
    from app.update_controller import UpdateController
    from app.window import MainWindow

    # No network, and no writes to the real config.json.
    monkeypatch.setattr(UpdateController, "check_async", lambda self: None)
    monkeypatch.setattr("app.i18n._update_config", lambda *a, **k: None)

    win = MainWindow()
    try:
        pages = [win.stack.widget(i) for i in range(win.stack.count())]
        enc = next(p for p in pages if isinstance(p, TabEncriptar))
        mrg = next(p for p in pages if isinstance(p, TabJuntar))
        edt = next(p for p in pages if isinstance(p, TabEditar))
        viewer = win._viewers[0]

        enc._pdf_password = "src-secret"
        enc._written_pwd[str(tmp_path / "out.pdf")] = "written-secret"
        mrg._pdf_password = "merge-secret"
        mrg._pwd_map[str(tmp_path / "in.pdf")] = "merge-secret"
        edt._pdf_password = "editor-secret"
        viewer._pdf_password = "viewer-secret"

        win.closeEvent(QCloseEvent())

        assert enc._pdf_password == ""
        assert enc._written_pwd == {}
        assert mrg._pdf_password == ""
        assert mrg._pwd_map == {}
        assert edt._pdf_password == ""
        assert viewer._pdf_password == ""
    finally:
        win.close()
        win.deleteLater()
        QTest.qWait(50)


def _build_test_window(monkeypatch):
    """Return ``(win, saved, released)`` for a MainWindow safe to close.

    ``saved`` and ``released`` are lists the caller can assert on to
    prove ``closeEvent`` reached its tail (layout persistence and
    update-worker release) instead of aborting halfway.
    """
    from app.update_controller import UpdateController
    from app.window import MainWindow

    saved: list[bool] = []
    released: list[bool] = []
    monkeypatch.setattr(UpdateController, "check_async", lambda self: None)
    monkeypatch.setattr("app.i18n._update_config",
                        lambda *a, **k: saved.append(True))
    monkeypatch.setattr(UpdateController, "release_worker",
                        lambda self: released.append(True))
    return MainWindow(), saved, released


def test_main_window_close_survives_a_holder_that_raises_on_attribute_access(
        monkeypatch):
    """A1: one hostile holder must not abort the whole close.

    ``getattr(holder, "_clear_pdf_password", None)`` sat *outside* the
    ``contextlib.suppress`` block, and the ``None`` default only swallows
    ``AttributeError``. Any other exception raised during attribute
    lookup (a stale wrapper, a ``__getattr__`` override, a property)
    escaped ``_wipe_all_pdf_passwords``, escaped ``closeEvent``, and took
    ``release_worker()`` plus the ``splitter_sizes`` / ``sidebar_mode``
    persistence down with it.
    """
    import contextlib

    from PySide6.QtGui import QCloseEvent
    from PySide6.QtTest import QTest

    from app.tools.encrypt import TabEncriptar
    from app.tools.merge import TabJuntar

    class _Poison:
        """Stands in for a holder whose attribute access blows up.

        The ``RuntimeError`` is the point of the test and must not be
        softened into the ``AttributeError`` that ``__getattr__`` is
        conventionally expected to raise (CodeQL
        ``py/unexpected-raise-in-special-method`` flags it for that
        reason). ``AttributeError`` is precisely the one exception the
        ``getattr(holder, ..., None)`` default swallows on its own, so
        with it this test keeps passing even when the lookup is moved
        back outside ``contextlib.suppress`` -- the very regression it
        exists to catch. Verified by mutation: ``RuntimeError`` fails
        against the reintroduced bug, ``AttributeError`` passes.
        """

        def __getattr__(self, name):
            raise RuntimeError("holder is gone: " + name)

    win, saved, released = _build_test_window(monkeypatch)
    poison = _Poison()
    try:
        pages = [win.stack.widget(i) for i in range(win.stack.count())]
        enc = next(p for p in pages if isinstance(p, TabEncriptar))
        mrg = next(p for p in pages if isinstance(p, TabJuntar))
        viewer = win._viewers[0]
        enc._pdf_password = "src-secret"
        mrg._pdf_password = "merge-secret"
        viewer._pdf_password = "viewer-secret"

        # Iterated before the real viewer, so a raise here would also
        # skip the viewer's own wipe.
        win._viewers.insert(0, poison)

        win.closeEvent(QCloseEvent())

        assert enc._pdf_password == "", "iteration stopped at the bad holder"
        assert mrg._pdf_password == ""
        assert viewer._pdf_password == "", \
            "holders after the bad one were never reached"
        assert released, "closeEvent aborted before release_worker()"
        assert saved, "closeEvent aborted before persisting the layout"
    finally:
        with contextlib.suppress(ValueError):
            win._viewers.remove(poison)
        win.close()
        win.deleteLater()
        QTest.qWait(50)


def test_main_window_close_wipes_a_panel_whose_cpp_object_is_gone(monkeypatch):
    """A1: a dead C++ wrapper must be wiped, not skipped.

    The cached password lives in the *Python* ``__dict__``, which
    outlives the C++ widget, so guarding the loop with
    ``shiboken6.isValid`` would skip exactly the object whose secret is
    still reachable. The assertion is twofold: the close must not raise,
    and the dead panel's password must end up empty like every other
    holder's.
    """
    import contextlib

    import shiboken6
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtTest import QTest

    from app.tools.encrypt import TabEncriptar
    from app.viewer.panel import PdfViewerPanel

    win, saved, released = _build_test_window(monkeypatch)
    dead = PdfViewerPanel()
    dead._pdf_password = "dead-panel-secret"
    shiboken6.delete(dead)
    assert not shiboken6.isValid(dead)
    try:
        pages = [win.stack.widget(i) for i in range(win.stack.count())]
        enc = next(p for p in pages if isinstance(p, TabEncriptar))
        enc._pdf_password = "src-secret"
        viewer = win._viewers[0]
        viewer._pdf_password = "viewer-secret"
        win._viewers.insert(0, dead)

        win.closeEvent(QCloseEvent())

        assert dead.__dict__.get("_pdf_password") == "", \
            "the dead wrapper's Python-side password survived the wipe"
        assert enc._pdf_password == ""
        assert viewer._pdf_password == ""
        assert released and saved
    finally:
        with contextlib.suppress(ValueError):
            win._viewers.remove(dead)
        win.close()
        win.deleteLater()
        QTest.qWait(50)


def test_language_restart_wipes_cached_passwords(monkeypatch):
    """``_restart_app`` leaves through ``QApplication.exit(0)``, which
    unwinds the event loop directly: Qt never delivers ``closeEvent``,
    so the language-change restart used to leave every cached password
    in the heap of a process that lingers while its replacement starts.
    """
    import PySide6.QtCore as _qtcore
    from PySide6.QtTest import QTest

    from app.tools.encrypt import TabEncriptar
    from app.tools.merge import TabJuntar

    started: list[bool] = []
    exited: list[int] = []

    class _FakeProcess:
        def setProgram(self, *a): pass
        def setArguments(self, *a): pass
        def setWorkingDirectory(self, *a): pass
        def setProcessEnvironment(self, *a): pass
        def startDetached(self): started.append(True)

    class _FakeInstance:
        def exit(self, code): exited.append(code)

    class _FakeApp:
        @staticmethod
        def instance():
            return _FakeInstance()

    win, _saved, _released = _build_test_window(monkeypatch)
    try:
        pages = [win.stack.widget(i) for i in range(win.stack.count())]
        enc = next(p for p in pages if isinstance(p, TabEncriptar))
        mrg = next(p for p in pages if isinstance(p, TabJuntar))
        enc._pdf_password = "src-secret"
        enc._written_pwd["x.pdf"] = "written-secret"
        mrg._pwd_map["y.pdf"] = "merge-secret"
        viewer = win._viewers[0]
        viewer._pdf_password = "viewer-secret"

        monkeypatch.setattr(_qtcore, "QProcess", _FakeProcess)
        monkeypatch.setattr("app.window.QApplication", _FakeApp)
        win._restart_app()

        assert started and exited == [0], "the relaunch itself must still run"
        assert enc._pdf_password == ""
        assert enc._written_pwd == {}
        assert mrg._pwd_map == {}
        assert viewer._pdf_password == ""
    finally:
        win.close()
        win.deleteLater()
        QTest.qWait(50)


# -- S3: the written-password map must be keyed case-insensitively -------


def test_written_password_key_is_case_normalised(tmp_path, monkeypatch):
    """``os.path.abspath`` preserves case, so encrypting to ``Out.pdf``
    and re-loading ``out.pdf`` (the same file on Windows) missed the
    seeded entry and re-prompted for a password just typed."""
    from app.tools.encrypt import TabEncriptar

    src = tmp_path / "Out.pdf"
    src.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr("app.tools.encrypt.resolve_file_password",
                        lambda p, pwd: pwd)

    tab = TabEncriptar(lambda *a, **k: None)
    try:
        tab._cache_written_password(str(src), "s3cret")
        assert tab._written_pwd.get(_pwd_cache_key(str(src))) == "s3cret"
        if os.path.normcase("A") == os.path.normcase("a"):
            other = str(tmp_path / "out.pdf")
            assert tab._written_pwd.get(_pwd_cache_key(other)) == "s3cret", \
                "a differently-cased spelling of the same file missed the seed"
    finally:
        tab.deleteLater()


# -- closing one tab must wipe that tab's password ----------------------


def test_closing_a_viewer_tab_wipes_that_tab_password(monkeypatch):
    """``_close_tab`` pops the panel and calls ``deleteLater()``.

    ``PdfViewerPanel.closeEvent`` would clear the cache, but
    ``deleteLater()`` destroys the widget without ever delivering
    ``closeEvent``, and by then the panel has already left
    ``self._viewers`` -- so ``_wipe_all_pdf_passwords`` at window close
    cannot reach it either. The password of a tab the user explicitly
    closed used to outlive the whole session.
    """
    from PySide6.QtTest import QTest

    win, _saved, _released = _build_test_window(monkeypatch)
    try:
        v = win._add_viewer_tab()
        v._pdf_password = "tab-secret"
        assert win._tab_bar.count() > 1, "need a second tab to exercise the pop"

        win._close_tab(win._viewers.index(v))

        assert not any(x is v for x in win._viewers), "the tab was not closed"
        assert v.__dict__.get("_pdf_password") == "", (
            "the closed tab's password survived; nothing will ever reach "
            "this panel again"
        )
    finally:
        win.close()
        win.deleteLater()
        QTest.qWait(50)


def test_closing_the_last_viewer_tab_wipes_its_password(monkeypatch):
    """The last tab is reset to a placeholder instead of being popped.

    The panel object survives and is reused for the next document, so no
    ``closeEvent`` is ever delivered to it either: without an explicit
    wipe the previous document's password stays cached and is handed to
    whatever the user opens next in that tab.
    """
    from PySide6.QtTest import QTest

    win, _saved, _released = _build_test_window(monkeypatch)
    try:
        assert win._tab_bar.count() == 1
        v = win._viewers[0]
        v._pdf_password = "last-tab-secret"

        win._close_tab(0)

        assert win._viewers[0] is v, "the last tab must be kept as placeholder"
        assert v.__dict__.get("_pdf_password") == "", (
            "the reset placeholder still holds the closed document's password"
        )
    finally:
        win.close()
        win.deleteLater()
        QTest.qWait(50)


def test_closed_tab_password_is_wiped_before_the_widget_is_deleted(monkeypatch):
    """Order matters: the wipe must precede ``deleteLater()``.

    Wiping afterwards would race Qt's deferred deletion and would make
    the wipe depend on a wrapper that may already be gone.
    """
    from PySide6.QtTest import QTest

    win, _saved, _released = _build_test_window(monkeypatch)
    order: list[str] = []
    try:
        v = win._add_viewer_tab()
        v._pdf_password = "ordering-secret"

        real_clear = v._clear_pdf_password
        real_delete = v.deleteLater

        def _clear():
            order.append("wipe")
            real_clear()

        def _delete():
            order.append("deleteLater")
            real_delete()

        v._clear_pdf_password = _clear
        v.deleteLater = _delete

        win._close_tab(win._viewers.index(v))

        assert order == ["wipe", "deleteLater"], order
    finally:
        win.close()
        win.deleteLater()
        QTest.qWait(50)


# -- the restart path must drain workers before wiping ------------------


def _fake_relaunch(monkeypatch):
    """Neutralise the process relaunch performed by ``_restart_app``."""
    import PySide6.QtCore as _qtcore

    started: list[bool] = []
    exited: list[int] = []

    class _FakeProcess:
        def setProgram(self, *a): pass
        def setArguments(self, *a): pass
        def setWorkingDirectory(self, *a): pass
        def setProcessEnvironment(self, *a): pass
        def startDetached(self): started.append(True)

    class _FakeInstance:
        def exit(self, code): exited.append(code)

    class _FakeApp:
        @staticmethod
        def instance():
            return _FakeInstance()

    monkeypatch.setattr(_qtcore, "QProcess", _FakeProcess)
    monkeypatch.setattr("app.window.QApplication", _FakeApp)
    return started, exited


def _record_wait_then_wipe(win, monkeypatch) -> list[str]:
    """Instrument every page's ``wait_for_workers`` plus the sweep.

    Returns the live event list: one ``"wait"`` per page drained,
    then ``"WIPE"`` when the password sweep runs.
    """
    events: list[str] = []
    for i in range(win.stack.count()):
        page = win.stack.widget(i)
        if callable(getattr(page, "wait_for_workers", None)):
            monkeypatch.setattr(
                page, "wait_for_workers",
                lambda *a, **k: events.append("wait"))
    real_wipe = win._wipe_all_pdf_passwords

    def _wipe():
        events.append("WIPE")
        real_wipe()

    monkeypatch.setattr(win, "_wipe_all_pdf_passwords", _wipe)
    return events


def _pages_with_workers(win) -> int:
    return sum(
        1 for i in range(win.stack.count())
        if callable(getattr(win.stack.widget(i), "wait_for_workers", None)))


def test_restart_drains_every_worker_before_wiping_passwords(monkeypatch):
    """``_restart_app`` skipped the worker drain that ``closeEvent`` does.

    A compress / OCR / convert QThread still running when the user
    changes language kept reading ``self._pdf_password`` while the sweep
    emptied it, and was then destroyed mid-flight -- the two failures
    the wait in ``closeEvent`` exists to prevent.
    """
    from PySide6.QtTest import QTest

    win, _saved, _released = _build_test_window(monkeypatch)
    try:
        started, exited = _fake_relaunch(monkeypatch)
        expected_waits = _pages_with_workers(win)
        assert expected_waits > 0, "no page exposes wait_for_workers"
        events = _record_wait_then_wipe(win, monkeypatch)

        win._restart_app()

        assert events.count("wait") == expected_waits, (
            "_restart_app drained {} of {} pages".format(
                events.count("wait"), expected_waits)
        )
        assert "WIPE" in events, "the password sweep did not run"
        assert events.index("WIPE") == expected_waits, (
            "the sweep ran before every worker was drained: {}".format(events)
        )
        assert started and exited == [0], "the relaunch itself must still run"
    finally:
        win.close()
        win.deleteLater()
        QTest.qWait(50)


def test_close_and_restart_share_the_same_drain_then_wipe_order(monkeypatch):
    """Both teardown paths must produce an identical event sequence.

    Asserted against ``closeEvent`` itself rather than a hardcoded
    count, so the two cannot silently drift apart again.
    """
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtTest import QTest

    win, _saved, _released = _build_test_window(monkeypatch)
    try:
        _fake_relaunch(monkeypatch)
        events = _record_wait_then_wipe(win, monkeypatch)
        win._restart_app()
        restart_events = list(events)
        events.clear()
        win.closeEvent(QCloseEvent())
        close_events = list(events)

        assert restart_events == close_events, (
            "restart={} close={}".format(restart_events, close_events)
        )
        assert "WIPE" in restart_events
    finally:
        win.close()
        win.deleteLater()
        QTest.qWait(50)


def test_worker_drain_survives_a_page_that_raises(monkeypatch):
    """One hostile page must not abort the drain, the sweep or the relaunch.

    Same failure mode already fixed in ``_wipe_all_pdf_passwords``: the
    attribute lookup sits inside the ``suppress``, because
    ``getattr(..., None)`` only swallows ``AttributeError``.
    """
    from PySide6.QtTest import QTest

    from app.tools.encrypt import TabEncriptar

    win, _saved, _released = _build_test_window(monkeypatch)
    try:
        started, exited = _fake_relaunch(monkeypatch)
        pages = [win.stack.widget(i) for i in range(win.stack.count())]
        enc = next(p for p in pages if isinstance(p, TabEncriptar))
        enc._pdf_password = "src-secret"

        def _boom(*a, **k):
            raise RuntimeError("worker wait exploded")

        monkeypatch.setattr(pages[0], "wait_for_workers", _boom)

        win._restart_app()

        assert enc._pdf_password == "", (
            "a raising page aborted the drain and took the sweep with it"
        )
        assert started and exited == [0], (
            "a raising page aborted the relaunch"
        )
    finally:
        win.close()
        win.deleteLater()
        QTest.qWait(50)


# ── AVISO 3: behavioural cover for the eight decrypt_pypdf call sites ────
#
# Every test below seals its fixture with **MuPDF**, not pypdf. That is
# the whole point: MuPDF hashes the raw UTF-8 bytes of the password it
# is given, so a file locked with an NFD spelling is unlocked by
# ``PdfReader.decrypt(nfd_bytes)`` but NOT by ``PdfReader.decrypt(nfd_str)``
# -- pypdf SASLpreps (NFKC) the ``str`` form for AES-256 and gets a
# different key. Measured on the fixture below: ``decrypt(str)`` returns
# 0, ``decrypt(bytes)`` returns 2.
#
# ``0`` is the silent-failure value: pypdf hands back a reader whose
# ``pages`` is empty rather than raising, which is how these tools used
# to write valid-looking PDFs with the encrypted input missing. So
# reverting any of these call sites to a bare ``.decrypt(self._pdf_password)``
# flips the tool from "correct artefact" to "wrong-password error or
# silently truncated output", and each assertion below names which.


def _mupdf_sealed(tmp_path: Path, pwd: str, name: str, pages: int = 3) -> str:
    """Lock a PDF with MuPDF using the exact bytes of ``pwd``.

    Deliberately not ``PdfWriter.encrypt``: pypdf would SASLprep a
    ``str`` password on the way in, producing a file that its own
    ``decrypt(str)`` reopens and thus a fixture that cannot tell the
    fixed code from the broken code.
    """
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    out = str(tmp_path / name)
    doc.save(out, encryption=pymupdf.PDF_ENCRYPT_AES_256,
             owner_pw=pwd, user_pw=pwd)
    doc.close()
    return out


def test_mupdf_sealed_fixture_actually_discriminates(tmp_path):
    """Guard the guard: if this stops holding, every test below is vacuous.

    pypdf must reject the ``str`` spelling (returning 0, not raising) and
    accept the raw UTF-8 ``bytes`` spelling of the same password.
    """
    path = _mupdf_sealed(tmp_path, NFD, "discriminates.pdf")

    from pypdf.errors import FileNotDecryptedError

    as_str = PdfReader(path)
    assert as_str.decrypt(NFD) == 0, (
        "pypdf accepted the str spelling -- the fixture no longer "
        "reproduces the MuPDF/pypdf divergence"
    )
    # Measured, and worth pinning because it differs from the
    # pypdf-sealed fixtures above: for *this* file a rejected password
    # makes page access raise FileNotDecryptedError rather than quietly
    # yielding zero pages. Either way the tool fails visibly, which is
    # what lets the call-site tests below tell fixed from broken; this
    # assertion records which of the two modes it is today.
    with pytest.raises(FileNotDecryptedError):
        len(as_str.pages)

    as_bytes = PdfReader(path)
    assert as_bytes.decrypt(NFD.encode("utf-8")) != 0
    assert len(as_bytes.pages) == 3


class _FakeWorker:
    """Stands in for the TaskRunner passed to a ``do_work`` closure.

    Lets the pure-ish worker body run synchronously on the test thread,
    which is what makes the two watermark call sites reachable without
    the modal progress dialog.
    """

    def __init__(self):
        self.progress = self
        self.emitted = []

    def emit(self, *a):
        self.emitted.append(a)

    def is_cancelled(self):
        return False


def _capture_background(page, monkeypatch):
    """Make ``_run_background`` run ``do_work`` inline and record it.

    Returns a dict filled with ``result`` / ``error`` once the tool runs.
    """
    box: dict = {}

    def _fake(do_work_fn, total=0, label="", on_done=None, on_err=None,
              cancelled_status=""):
        try:
            box["result"] = do_work_fn(_FakeWorker())
        except Exception as exc:  # recorded, not swallowed: asserted on
            box["error"] = exc
            return
        if on_done is not None and box["result"] is not None:
            on_done(box["result"])

    monkeypatch.setattr(page, "_run_background", _fake)
    return box


# -- site 1: app/editor/tab.py -- _load_form_fields --------------------


def test_editor_form_loader_reads_fields_from_a_mupdf_sealed_pdf(tmp_path):
    """``decrypt_pypdf(_r, self._pdf_password)`` at editor/tab.py.

    Reverting it to ``_r.decrypt(self._pdf_password)`` makes decrypt
    return 0, which raises the wrong-password error and shows the user
    "load failed" for a password that is in fact correct.
    """
    from app.editor.tab import TabEditar
    from app.i18n import t

    src = _mupdf_sealed(tmp_path, NFD, "forms_src.pdf", pages=1)

    tab = TabEditar(lambda *a, **k: None)
    try:
        tab._pdf_password = NFD
        tab._load_form_fields(src)
        assert tab._form_status.text() != t("editor.forms.load_failed"), (
            "the correct password was reported as a load failure"
        )
    finally:
        tab.deleteLater()


# -- site 2: app/editor/tab.py -- _apply_forms -------------------------


def test_editor_apply_forms_writes_an_output_for_a_mupdf_sealed_pdf(
        tmp_path, monkeypatch):
    """``decrypt_pypdf(_r, self._pdf_password)`` in ``_apply_forms``.

    The fixture is a MuPDF-sealed PDF with no ``/AcroForm``, so the
    *correct* outcome is the friendly "no form fields" status and an
    untouched file. Reverted to ``_r.decrypt(self._pdf_password)`` the
    guard fires first and raises wrong-password instead, which reaches
    the user through ``show_error``. The two outcomes are distinct and
    both observable, which is what makes this discriminate.
    """
    from app.editor.tab import TabEditar
    from app.i18n import t

    src = _mupdf_sealed(tmp_path, NFD, "apply_src.pdf", pages=2)
    out = str(tmp_path / "apply_out.pdf")

    errors = []
    monkeypatch.setattr("app.editor.tab.show_error",
                        lambda *a, **k: errors.append(a))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information",
                        staticmethod(lambda *a, **k: None))

    tab = TabEditar(lambda *a, **k: None)
    try:
        tab._doc_path = src
        tab._pdf_password = NFD
        # Modal in production; the encryption choice is not the subject.
        monkeypatch.setattr(tab, "_prompt_encryption_choice",
                            lambda: "plaintext")
        tab._apply_forms(out)

        assert not errors, (
            "the correct password surfaced an error: %r" % (errors,)
        )
        assert tab._form_status.text() == t("editor.forms.no_fields"), (
            "the reader was never decrypted, so _apply_forms could not "
            "reach the /AcroForm check: got %r"
            % (tab._form_status.text(),)
        )
    finally:
        tab.deleteLater()


# -- site 3: app/tools/encrypt.py -- manual override -------------------


def test_encrypt_manual_override_decrypts_a_mupdf_sealed_pdf(
        tmp_path, monkeypatch):
    """``decrypt_pypdf(reader, manual_pwd)`` in TabEncriptar._run.

    The ``edit_pwd`` field is the manual override used when the user
    skipped the prompt. Reverted, a correct NFD password is rejected
    with "wrong password" and the decrypted output is never written.
    """
    from app.tools.encrypt import TabEncriptar

    src = _mupdf_sealed(tmp_path, NFD, "enc_src.pdf", pages=3)
    out = str(tmp_path / "enc_out.pdf")

    warnings = []
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning",
                        staticmethod(lambda *a, **k: warnings.append(a)))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information",
                        staticmethod(lambda *a, **k: None))

    tab = TabEncriptar(lambda *a, **k: None)
    try:
        # Decrypt mode, and no cached source password, so the manual
        # override branch is the one that runs.
        tab.cmb_mode.setCurrentIndex(1)
        tab._pdf_password = ""
        tab.drop_in.blockSignals(True)
        tab.drop_in.set_path(src)
        tab.drop_in.blockSignals(False)
        tab.drop_out.set_path(out)
        tab.edit_pwd.setText(NFD)

        tab._run()

        assert not warnings, (
            "the correct password was reported as wrong: %r" % (warnings,)
        )
        assert os.path.isfile(out), "no decrypted output written"
        assert len(PdfReader(out).pages) == 3, (
            "decrypted output is truncated -- reader was never unlocked"
        )
    finally:
        tab.deleteLater()


# -- site 4: app/tools/merge.py ----------------------------------------


def test_merge_includes_every_page_of_a_mupdf_sealed_input(
        tmp_path, monkeypatch):
    """``decrypt_pypdf(reader, pwd)`` in TabJuntar._run.

    This is the site with the measured user-visible delta: reverted, the
    merge raises "wrong password" and writes no file at all, for a
    password the viewer already accepted.
    """
    from app.tools.merge import TabJuntar

    good = _plain_pdf(tmp_path, pages=2)
    locked = _mupdf_sealed(tmp_path, NFD, "merge_src.pdf", pages=3)
    out = str(tmp_path / "merge_out.pdf")

    errors = []
    monkeypatch.setattr("app.tools.merge.show_error",
                        lambda *a, **k: errors.append(a))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information",
                        staticmethod(lambda *a, **k: None))

    page = TabJuntar(lambda *a, **k: None)
    try:
        page.lst.addItem(good)
        page.lst.addItem(locked)
        # Seeded with the spelling the user typed, exactly as
        # _maybe_prompt_password would have cached it.
        page._pwd_map[locked] = NFD
        page.drop_out.set_path(out)
        page._run()

        assert not errors, "the correct password surfaced an error: %r" % (errors,)
        assert os.path.isfile(out), "the merge produced no file"
        assert len(PdfReader(out).pages) == 5, (
            "the encrypted input contributed no pages -- silently truncated"
        )
    finally:
        page.deleteLater()


# -- sites 5 and 6: app/tools/watermark.py -----------------------------


def test_watermark_preflight_accepts_a_mupdf_sealed_watermark(
        tmp_path, monkeypatch):
    """``decrypt_pypdf(wm_reader, wm_pwd)`` -- watermark.py pre-flight.

    The stamp PDF itself is encrypted (the corporate-stamp case the
    branch exists for). Reverted, the pre-flight raises wrong-password
    and the run aborts before any background work starts.
    """
    from app.tools.watermark import TabMarcaDagua

    src = _plain_pdf(tmp_path, pages=2)
    wm = _mupdf_sealed(tmp_path, NFD, "wm_sealed.pdf", pages=1)
    out = str(tmp_path / "wm_out.pdf")

    errors = []
    monkeypatch.setattr("app.tools.watermark.show_error",
                        lambda *a, **k: errors.append(a))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning",
                        staticmethod(lambda *a, **k: errors.append(a)))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information",
                        staticmethod(lambda *a, **k: None))

    page = TabMarcaDagua(lambda *a, **k: None)
    try:
        monkeypatch.setattr(page, "_prompt_watermark_password",
                            lambda p: NFD)
        box = _capture_background(page, monkeypatch)
        page.drop_in.blockSignals(True); page.drop_in.set_path(src)
        page.drop_in.blockSignals(False)
        page.drop_wm.blockSignals(True); page.drop_wm.set_path(wm)
        page.drop_wm.blockSignals(False)
        page.drop_out.set_path(out)

        page._run()

        assert not errors, (
            "the correct watermark password was rejected: %r" % (errors,)
        )
        assert "error" not in box, "the worker raised: %r" % (box.get("error"),)
        assert box.get("result") == out, (
            "the background work never produced the output path"
        )
        assert os.path.isfile(out)
        assert len(PdfReader(out).pages) == 2
    finally:
        page.deleteLater()


def test_watermark_worker_accepts_a_mupdf_sealed_source(
        tmp_path, monkeypatch):
    """``decrypt_pypdf(r, pwd)`` inside watermark's ``do_work``.

    The in-worker guard re-opens the *source* PDF. Reverted, the worker
    raises wrong-password after the pre-flight passed, so the user gets
    an error dialog at the end of a run that had already validated its
    inputs.
    """
    from app.tools.watermark import TabMarcaDagua

    src = _mupdf_sealed(tmp_path, NFD, "wm_src_sealed.pdf", pages=3)
    wm = _plain_pdf(tmp_path, pages=1)
    out = str(tmp_path / "wm_src_out.pdf")

    errors = []
    monkeypatch.setattr("app.tools.watermark.show_error",
                        lambda *a, **k: errors.append(a))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning",
                        staticmethod(lambda *a, **k: errors.append(a)))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information",
                        staticmethod(lambda *a, **k: None))

    page = TabMarcaDagua(lambda *a, **k: None)
    try:
        # Source password, cached exactly as the prompt would leave it.
        page._pdf_password = NFD
        monkeypatch.setattr(page, "_prompt_watermark_password", lambda p: "")
        box = _capture_background(page, monkeypatch)
        page.drop_in.blockSignals(True); page.drop_in.set_path(src)
        page.drop_in.blockSignals(False)
        page.drop_wm.blockSignals(True); page.drop_wm.set_path(wm)
        page.drop_wm.blockSignals(False)
        page.drop_out.set_path(out)

        page._run()

        assert not errors, "the correct password was rejected: %r" % (errors,)
        assert "error" not in box, "the worker raised: %r" % (box.get("error"),)
        assert box.get("result") == out
        assert os.path.isfile(out)
        assert len(PdfReader(out).pages) == 3, (
            "the watermarked output lost the encrypted source's pages"
        )
    finally:
        page.deleteLater()


# -- sites 7 and 8: app/utils.py -- the compression gate ---------------


def test_compress_gate_accepts_a_mupdf_sealed_pdf(tmp_path):
    """``authenticate_pymupdf(probe, password)`` -- the PyMuPDF arm of the gate.

    The password here is deliberately **not** NFD: MuPDF hashes the raw
    UTF-8 bytes of whatever it is handed, so for an NFD-sealed file a
    bare ``probe.authenticate(typed)`` happens to succeed and the
    mutation survives (measured). The discriminating input is a file
    sealed with the *SASLprep/NFKC* spelling -- what an ISO 32000-2
    conformant producer writes -- opened with the ligature the user
    actually typed: ``probe.authenticate(typed)`` returns 0 there, and
    only the candidate list recovers it.
    """
    from app.utils import WrongPasswordError, _compress_pdf

    typed = FI                       # "of<U+FB01>ce"
    stored = saslprep(typed)         # "office"
    assert stored != typed, "the fixture must exercise the folded spelling"
    src = _mupdf_sealed(tmp_path, stored, "compress_src.pdf", pages=2)
    dst = str(tmp_path / "compress_out.pdf")

    probe = pymupdf.open(src)
    try:
        assert probe.authenticate(typed) == 0, (
            "a bare authenticate() accepted the typed spelling -- this "
            "fixture can no longer tell the candidate list from its absence"
        )
    finally:
        probe.close()

    try:
        _compress_pdf(src, dst, level=1, password=typed)
    except WrongPasswordError as exc:  # the discriminating failure
        pytest.fail(
            "the compression gate rejected a correct password: %s" % (exc,))
    except Exception:
        # Any other failure is a missing external tool (Ghostscript etc.),
        # not the password gate this test is about. The gate runs before
        # every pass, so reaching this point already proves it passed.
        pass


def test_compress_gate_still_rejects_a_wrong_password(tmp_path):
    """The gate must stay a gate: a genuinely wrong password still raises.

    Without this, widening the candidate list to "accept anything" would
    also pass the test above.
    """
    from app.utils import WrongPasswordError, _compress_pdf

    src = _mupdf_sealed(tmp_path, NFD, "compress_bad.pdf", pages=2)
    dst = str(tmp_path / "compress_bad_out.pdf")

    with pytest.raises(WrongPasswordError):
        _compress_pdf(src, dst, level=1, password="definitely-not-it")


def test_compress_gate_pypdf_fallback_accepts_a_mupdf_sealed_pdf(
        tmp_path, monkeypatch):
    """The pypdf fallback arm of the same gate (``decrypt_pypdf``).

    Only reachable when the PyMuPDF probe raises, so PyMuPDF is forced to fail
    here. Reverted to ``pr.decrypt(password)`` this arm returns 0 and the
    gate rejects a correct password.
    """
    import builtins

    from app.utils import WrongPasswordError, _compress_pdf

    src = _mupdf_sealed(tmp_path, NFD, "compress_fb.pdf", pages=2)
    dst = str(tmp_path / "compress_fb_out.pdf")

    real_import = builtins.__import__

    def _no_pymupdf(name, *a, **k):
        # Blocking ``pymupdf`` alone is enough: app/ never imports the
        # deprecated alias (tests/test_no_legacy_fitz_import.py enforces
        # it), so the probe in _compress_pdf can only reach PyMuPDF
        # through this name, even when the alias is already cached in
        # sys.modules.
        if name == "pymupdf":
            raise ImportError("PyMuPDF disabled for this test")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_pymupdf)
    try:
        _compress_pdf(src, dst, level=1, password=NFD)
    except WrongPasswordError as exc:
        pytest.fail(
            "the pypdf fallback arm rejected a correct password: %s" % (exc,))
    except Exception:
        # As above: a later pass needing an absent external tool is not
        # this test's subject.
        pass
