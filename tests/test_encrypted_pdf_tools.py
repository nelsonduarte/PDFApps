"""Regression tests for encrypted-PDF handling across the PDF tools.

Covers the adversarial-audit findings:

* MAJOR M1 — ``_compress_pdf`` ignored the password of an encrypted
  source. Every pass discarded its output (gs exit!=0, fitz locked doc
  swallowed, pikepdf PasswordError swallowed), leaving ``temps`` empty
  so the function raised the MISLEADING ``tool.compress.deps_missing``
  even with all dependencies installed. The fix threads a ``password``
  parameter through every pass, gates on encryption up front, and never
  accepts an empty/locked output as success.

* MINOR — ``doc.authenticate(...)`` return value was ignored in the
  nup / page_numbers / ocr / convert workers. A password that changed
  between validation and execution left the worker operating on a
  locked document, producing empty/garbled output instead of a clear
  error. The fix verifies the return and raises
  ``tool.err.wrong_password``.

* MINOR — reorder could write a 0-page (invalid) PDF when every page
  was removed. The fix aborts with a warning before writing.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# A QCoreApplication is needed by app.i18n.t() (QSettings) and by the
# tool pages we instantiate. Offscreen keeps headless CI display-free.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402
_app = QApplication.instance() or QApplication([])

import fitz  # noqa: E402

from app.i18n import t  # noqa: E402
from app.utils import _compress_pdf, WrongPasswordError, _is_valid_pdf  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────


def _compressible_pixmap(side: int = 1000):
    """A high-entropy RGB pixmap generated in C via os.urandom.

    High entropy means the raster barely deflates, so the source PDF
    stores it near-raw. Downsampling it to a 72-dpi A4 page (Pass A/B)
    then cuts the pixel count by ~3x and re-encodes to JPEG, which
    guarantees ``_compress_pdf`` finds a real size gain instead of
    raising its "no gain" ValueError. Using os.urandom keeps setup
    fast (no Python per-pixel loop).
    """
    samples = os.urandom(side * side * 3)
    return fitz.Pixmap(fitz.csRGB, side, side, samples, False)


def _make_encrypted_pdf(path: Path, password: str, pages: int = 2) -> Path:
    """Create an AES-256 encrypted, genuinely-compressible PDF."""
    doc = fitz.open()
    pix = _compressible_pixmap()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_image(fitz.Rect(0, 0, 595, 842), pixmap=pix)
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw=password,
        user_pw=password,
    )
    doc.close()
    return path


class _FakeWorker:
    """Minimal TaskRunner stand-in for driving a captured do_work()."""

    def is_cancelled(self):
        return False

    class _Sig:
        def emit(self, *a, **k):
            pass

    progress = _Sig()


# ── MAJOR M1 — compress honours the password ─────────────────────────────


def test_wrong_password_error_is_not_a_valueerror():
    """WrongPasswordError must NOT be a ValueError — the compress tool
    treats ValueError from _compress_pdf as the friendly "no gain"
    outcome, so a password failure must reach the real error path."""
    assert not issubclass(WrongPasswordError, ValueError)


def test_compress_encrypted_correct_password(tmp_path: Path):
    """Correct password → valid, non-empty, decrypted, smaller output."""
    src = _make_encrypted_pdf(tmp_path / "enc.pdf", "s3cret", pages=2)
    dst = tmp_path / "out.pdf"
    before, after = _compress_pdf(str(src), str(dst), level="extreme",
                                  password="s3cret")
    assert dst.exists()
    assert after <= before
    # Output must be a valid, readable, *decrypted* PDF with pages.
    assert _is_valid_pdf(str(dst))
    out = fitz.open(str(dst))
    try:
        assert not out.needs_pass
        assert out.page_count == 2
    finally:
        out.close()


def test_compress_encrypted_wrong_password(tmp_path: Path):
    """Wrong password → WrongPasswordError (NOT deps_missing / no_gain),
    and no output file is produced."""
    src = _make_encrypted_pdf(tmp_path / "enc.pdf", "s3cret")
    dst = tmp_path / "out.pdf"
    with pytest.raises(WrongPasswordError) as ei:
        _compress_pdf(str(src), str(dst), level="recommended",
                      password="wrong-pw")
    assert t("tool.err.wrong_password") in str(ei.value)
    assert t("tool.compress.deps_missing") not in str(ei.value)
    assert not dst.exists()


def test_compress_encrypted_missing_password(tmp_path: Path):
    """No password for an encrypted source → WrongPasswordError, not the
    misleading deps_missing RuntimeError."""
    src = _make_encrypted_pdf(tmp_path / "enc.pdf", "s3cret")
    dst = tmp_path / "out.pdf"
    with pytest.raises(WrongPasswordError):
        _compress_pdf(str(src), str(dst), level="recommended", password=None)
    assert not dst.exists()


def test_compress_plain_pdf_still_works(tmp_path: Path):
    """A non-encrypted PDF must compress exactly as before (no
    regression from the encryption gate)."""
    src = tmp_path / "plain.pdf"
    # Build a plain compressible PDF (same noise image, no encryption).
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(0, 0, 595, 842), pixmap=_compressible_pixmap())
    doc.save(str(src))
    doc.close()

    dst = tmp_path / "out.pdf"
    before, after = _compress_pdf(str(src), str(dst), level="extreme",
                                  password=None)
    assert dst.exists()
    assert after <= before
    assert _is_valid_pdf(str(dst))


# ── _is_valid_pdf — rejects locked / empty outputs ───────────────────────


def test_is_valid_pdf_rejects_encrypted(tmp_path: Path):
    """A still-encrypted file is never a valid *result* (a locked doc
    saved by a broken pass must not be accepted as success)."""
    enc = _make_encrypted_pdf(tmp_path / "enc.pdf", "pw")
    assert _is_valid_pdf(str(enc)) is False


def test_is_valid_pdf_rejects_empty(tmp_path: Path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    assert _is_valid_pdf(str(empty)) is False
    assert _is_valid_pdf(str(tmp_path / "missing.pdf")) is False


def test_is_valid_pdf_accepts_normal(tmp_path: Path):
    p = tmp_path / "ok.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(str(p))
    doc.close()
    assert _is_valid_pdf(str(p)) is True


# ── MINOR — worker authenticate() return is verified ─────────────────────


def _capture_do_work(page, entry):
    """Run ``entry`` (the page's launch method) but intercept
    ``_run_background`` so the worker's do_work closure is captured
    instead of executed on a thread. Returns the captured callable."""
    captured = {}

    def _fake_bg(do_work_fn, *a, **k):
        captured["fn"] = do_work_fn

    page._run_background = _fake_bg
    entry()
    return captured.get("fn")


def test_nup_worker_raises_on_auth_failure(tmp_path, monkeypatch):
    """nup do_work must raise tool.err.wrong_password when
    authenticate() fails (defence-in-depth for a changed password)."""
    from app.tools.nup import TabNUp

    src = _make_encrypted_pdf(tmp_path / "enc.pdf", "pw", pages=4)
    page = TabNUp(lambda *a, **k: None)
    page._pdf_password = "pw"  # correct → pre-flight passes
    page.drop_in.set_path(str(src))
    page.drop_out.set_path(str(tmp_path / "out.pdf"))

    do_work = _capture_do_work(page, page._run)
    assert do_work is not None, "nup._run did not reach _run_background"

    # Simulate the source becoming un-authenticatable at execution time.
    class _Locked:
        needs_pass = True

        def authenticate(self, _pw):
            return 0

        def close(self):
            pass

    monkeypatch.setattr(fitz, "open", lambda *a, **k: _Locked())
    with pytest.raises(ValueError) as ei:
        do_work(_FakeWorker())
    assert t("tool.err.wrong_password") in str(ei.value)


def test_convert_images_worker_raises_on_auth_failure(tmp_path, monkeypatch):
    """convert._convert_images do_work must raise on auth failure."""
    from app.tools.convert import TabConverter

    src = _make_encrypted_pdf(tmp_path / "enc.pdf", "pw", pages=2)
    page = TabConverter(lambda *a, **k: None)
    page._pdf_password = "pw"
    # Point the output folder widget at a temp dir so _resolve_output_dir
    # doesn't prompt.
    page._drop_folder.set_path(str(tmp_path))

    do_work = _capture_do_work(
        page, lambda: page._convert_images(str(src), 0))
    assert do_work is not None, "_convert_images did not reach _run_background"

    class _Locked:
        needs_pass = True

        def authenticate(self, _pw):
            return 0

        def close(self):
            pass

    monkeypatch.setattr(fitz, "open", lambda *a, **k: _Locked())
    with pytest.raises(ValueError) as ei:
        do_work(_FakeWorker())
    assert t("tool.err.wrong_password") in str(ei.value)


def test_worker_authenticate_checks_are_present():
    """Static regression guard for every worker authenticate site:
    a bare ``doc.authenticate(pwd)`` without a checked return must not
    creep back in. Each file must verify the return and raise the
    wrong_password error."""
    root = Path(__file__).resolve().parent.parent / "app" / "tools"
    for name in ("nup.py", "page_numbers.py", "ocr.py", "convert.py"):
        compact = (root / name).read_text(encoding="utf-8").replace(" ", "")
        # The old unchecked one-liner (`<doc>.authenticate(pwd)` as a bare
        # statement) must be gone — the call may now only appear inside a
        # checked `if not (pwd and <doc>.authenticate(pwd)):` guard.
        assert ".authenticate(pwd)\n" not in compact, \
            f"{name}: unchecked authenticate(pwd) statement still present"
        assert "ifnot(pwdand" in compact, \
            f"{name}: missing checked authenticate guard"
        assert 'tool.err.wrong_password' in compact, \
            f"{name} must raise wrong_password when authenticate fails"


# ── MINOR — reorder aborts on empty page list ────────────────────────────


def test_reorder_empty_list_aborts(tmp_path, monkeypatch):
    """Removing every page must warn and NOT write an invalid 0-page PDF."""
    from app.tools import reorder as reorder_mod
    from app.tools.reorder import TabReordenar

    src = tmp_path / "in.pdf"
    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
    doc.save(str(src))
    doc.close()

    page = TabReordenar(lambda *a, **k: None)
    page._load_input(str(src))
    assert page._page_count == 3

    # Remove every row.
    while page.lst.count():
        page.lst.setCurrentRow(0)
        page._del()
    assert page.lst.count() == 0

    warned = {}
    monkeypatch.setattr(reorder_mod.QMessageBox, "warning",
                        lambda *a, **k: warned.setdefault("hit", True))
    # If _run ever reached the writer with no pages it would call
    # _resolve_output_file (Save dialog) — make that explode so the test
    # fails loudly instead of hanging on a dialog.
    monkeypatch.setattr(page, "_resolve_output_file",
                        lambda *a, **k: pytest.fail(
                            "reorder must abort before resolving output"))
    out = tmp_path / "out.pdf"
    page.drop_out.set_path(str(out))

    page._run()
    assert warned.get("hit"), "reorder must warn when all pages removed"
    assert not out.exists()


def test_reorder_normal_still_writes(tmp_path, monkeypatch):
    """Sanity: a non-empty reorder still produces a valid PDF."""
    from app.tools import reorder as reorder_mod
    from app.tools.reorder import TabReordenar

    src = tmp_path / "in.pdf"
    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
    doc.save(str(src))
    doc.close()

    # The success path pops a modal QMessageBox.information — stub it so
    # the headless test doesn't block.
    monkeypatch.setattr(reorder_mod.QMessageBox, "information",
                        lambda *a, **k: None)

    page = TabReordenar(lambda *a, **k: None)
    page._load_input(str(src))
    out = tmp_path / "out.pdf"
    page.drop_out.set_path(str(out))
    page._run()
    assert out.exists()
    assert _is_valid_pdf(str(out))
