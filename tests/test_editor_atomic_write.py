"""Behavioural tests for the shared atomic PDF writer as the editor uses it.

R3 unified ``TabEditar._run``'s save (a duplicated mkstemp/``doc.save``/
``os.replace`` block) onto :func:`app.pdf_io.atomic_pdf_write` — the same
low-level helper every ``BasePage`` tool already used. These tests drive
that helper with the EXACT ``save_opts`` shapes ``_run`` builds (plain
and AES-256 re-encryption with a permissions flag) plus the
``close_writer=True`` ordering the editor relies on, proving the save
behaviour is preserved without instantiating a Qt widget.

Run with ``QT_QPA_PLATFORM=offscreen`` (``app.pdf_io`` imports ``app.i18n``
lazily for its one error message, which needs a QCoreApplication).
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402
_unused_app = QApplication.instance() or QApplication([])

pymupdf = pytest.importorskip("pymupdf")

from app.pdf_io import atomic_pdf_write  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────


def _make_doc(marker: str = "Hello editor", pages: int = 2):
    """A small text-bearing document, unsaved (in memory)."""
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"{marker} {i}", fontsize=14)
    return doc


def _plain_opts() -> dict:
    """Exactly what TabEditar._run builds for a non-encrypted save."""
    return dict(garbage=4, deflate=True)


def _encrypted_opts(password: str, perms: int = -1) -> dict:
    """Exactly what TabEditar._run builds for the AES-256 re-encrypt save
    (owner_pw == user_pw, permissions read from the source doc)."""
    return dict(
        garbage=4, deflate=True,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw=password,
        owner_pw=password,
        permissions=perms,
    )


# ── plain save (the common editor path) ──────────────────────────────────


def test_editor_plain_save_produces_valid_pdf(tmp_path: Path):
    out = tmp_path / "out.pdf"
    doc = _make_doc("Plain save", pages=3)
    atomic_pdf_write(doc, str(out), save_opts=_plain_opts(), close_writer=True)

    assert out.exists()
    reopened = pymupdf.open(str(out))
    try:
        assert reopened.page_count == 3
        # PyMuPDF reports needs_pass as an int (0/1), so compare
        # truthiness rather than the ``bool`` singleton.
        assert not reopened.needs_pass
        assert "Plain save 0" in reopened[0].get_text()
        assert "Plain save 2" in reopened[2].get_text()
    finally:
        reopened.close()


def test_editor_close_writer_closes_doc_before_return(tmp_path: Path):
    """close_writer=True must leave the PyMuPDF doc closed once the helper
    returns — this is what let the editor overwrite the same file it had
    open (the handle is released before os.replace)."""
    out = tmp_path / "out.pdf"
    doc = _make_doc()
    atomic_pdf_write(doc, str(out), save_opts=_plain_opts(), close_writer=True)
    assert doc.is_closed is True


def test_default_leaves_writer_open_for_base_tools(tmp_path: Path):
    """The BasePage default (close_writer omitted) must NOT close the doc —
    tool pages keep it alive and close it themselves."""
    out = tmp_path / "out.pdf"
    doc = _make_doc()
    try:
        atomic_pdf_write(doc, str(out), save_opts=_plain_opts())
        assert doc.is_closed is False
    finally:
        doc.close()


# ── close-before-replace ORDERING (the Windows overwrite invariant) ──────
#
# The two tests above only inspect ``doc.is_closed`` AFTER the helper
# returns. That cannot distinguish the correct save→close→replace order
# from a regression that moved ``writer.close()`` to AFTER ``os.replace``:
# in both cases the doc ends up closed on return. On Windows the editor
# overwrites the very file it has open, so the handle MUST be released
# before the rename or ``os.replace`` raises a sharing violation — but on
# POSIX (the CI) that reorder is silent and would slip through.
#
# These tests pin the ordering PORTABLY by probing the writer's state at
# the instant ``os.replace`` fires: we monkeypatch the ``os.replace`` that
# ``app.pdf_io`` actually calls with a spy that records ``doc.is_closed``
# as it runs, then delegates to the real rename so the write still lands.


def test_close_writer_true_closes_doc_before_os_replace(tmp_path: Path,
                                                        monkeypatch):
    """close_writer=True: the PyMuPDF handle is already released at the exact
    moment os.replace is invoked. Falsifies a save→replace→close reorder,
    which would observe an OPEN doc here and fail the assertion (while the
    weaker 'closed on return' test would still pass)."""
    out = tmp_path / "out.pdf"
    doc = _make_doc()

    real_replace = os.replace
    seen: dict = {}

    def _spy(src, dst):
        seen["closed_at_replace"] = doc.is_closed
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _spy)
    atomic_pdf_write(doc, str(out), save_opts=_plain_opts(), close_writer=True)

    assert seen["closed_at_replace"] is True   # closed BEFORE the rename
    assert out.exists()                         # rename still completed


def test_default_leaves_writer_open_at_os_replace(tmp_path: Path,
                                                  monkeypatch):
    """The inverse contract: with close_writer omitted (BasePage default)
    the writer is STILL OPEN when os.replace fires — tool pages own the
    doc's lifetime. Probed at the same instant so the pair fixes the exact
    relationship between close_writer and the handle state at the rename."""
    out = tmp_path / "out.pdf"
    doc = _make_doc()

    real_replace = os.replace
    seen: dict = {}

    def _spy(src, dst):
        seen["closed_at_replace"] = doc.is_closed
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _spy)
    try:
        atomic_pdf_write(doc, str(out), save_opts=_plain_opts())
        assert seen["closed_at_replace"] is False  # still open at the rename
        assert out.exists()
    finally:
        doc.close()


# ── AES-256 re-encryption (the encrypted editor path) ────────────────────


def test_editor_aes256_save_round_trips_with_password(tmp_path: Path):
    out = tmp_path / "secret.pdf"
    pw = "Corr3ct-Horse"
    doc = _make_doc("Secret body", pages=2)
    atomic_pdf_write(doc, str(out),
                     save_opts=_encrypted_opts(pw), close_writer=True)

    assert out.exists()
    # Output is genuinely encrypted: opening without the password locks it.
    # needs_pass / authenticate return ints (1/0) in PyMuPDF — compare
    # truthiness, not the bool singletons.
    locked = pymupdf.open(str(out))
    try:
        assert locked.needs_pass
        assert locked.authenticate(pw)  # correct password unlocks (non-zero)
        assert locked.page_count == 2
        assert "Secret body 0" in locked[0].get_text()
        assert "Secret body 1" in locked[1].get_text()
    finally:
        locked.close()


def test_editor_aes256_rejects_wrong_password(tmp_path: Path):
    out = tmp_path / "secret.pdf"
    doc = _make_doc("Body", pages=1)
    atomic_pdf_write(doc, str(out),
                     save_opts=_encrypted_opts("right-pw"), close_writer=True)

    locked = pymupdf.open(str(out))
    try:
        assert locked.needs_pass
        assert locked.authenticate("wrong-pw") == 0  # wrong password fails
    finally:
        locked.close()


def test_save_opts_forwarded_verbatim_to_pymupdf_writer(tmp_path: Path):
    """The helper must forward ``save_opts`` VERBATIM as kwargs to a
    PyMuPDF-style writer's ``save()`` — that is precisely what carries the
    editor's encryption / user_pw / owner_pw / permissions options
    through untouched. Asserted deterministically with a recording
    stand-in (real PyMuPDF's signed permissions int makes an on-disk
    round-trip brittle, and ``owner_pw == user_pw`` grants owner rights
    that mask the restricted flag). ``close_writer=True`` must also fire
    between save and rename."""
    out = tmp_path / "o.pdf"

    class _RecordingDoc:
        def __init__(self):
            self.saved_kwargs = None
            self.closed = False

        def save(self, path, **kw):
            self.saved_kwargs = dict(kw)
            with open(path, "wb") as fh:
                fh.write(b"%PDF-1.7\n%%EOF\n")

        def close(self):
            self.closed = True

    # The helper detects a pymupdf.Document by its class module — spoof it so
    # this pure stand-in takes the same ``writer.save(tmp, **save_opts)``
    # branch the editor's real PyMuPDF doc does.
    _RecordingDoc.__module__ = "pymupdf"

    doc = _RecordingDoc()
    opts = dict(garbage=4, deflate=True, encryption=99,
                user_pw="u", owner_pw="o", permissions=1234)
    atomic_pdf_write(doc, str(out), save_opts=opts, close_writer=True)

    assert doc.saved_kwargs == opts   # nothing dropped, added or mutated
    assert doc.closed is True         # close_writer honoured before rename
    assert out.exists()


# ── same-source guard still active on the PyMuPDF + close_writer path ───────


def test_editor_save_rejects_same_source_and_preserves_input(tmp_path: Path):
    """Even with close_writer=True, the up-front same-source check must
    fire BEFORE any bytes are written, leaving the input intact."""
    src = tmp_path / "in.pdf"
    _make_doc("Original", pages=2).save(str(src))
    before = src.read_bytes()

    doc = pymupdf.open(str(src))
    try:
        with pytest.raises(RuntimeError):
            atomic_pdf_write(doc, str(src), sources=[str(src)],
                             save_opts=_plain_opts(), close_writer=True)
    finally:
        doc.close()
    assert src.read_bytes() == before
