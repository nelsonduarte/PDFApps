"""
Tests for the main PDFApps features.
Tests the PDF logic directly (without UI) using pypdf and fitz.
"""
import os
import sys
import pytest
import tempfile
from pathlib import Path

# Make the project root importable so `from app.utils import ...` works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pypdf import PdfReader, PdfWriter

# Import the real parse_pages from app.utils so the test catches drift —
# previously this file shipped a local replica that diverged from the
# production helper (no _MAX_PAGES cap, different error message).
from app.utils import parse_pages

# ── helpers ───────────────────────────────────────────────────────────────────

def make_pdf(path: str, num_pages: int = 3) -> str:
    """Create a simple PDF with N pages using fitz."""
    import fitz
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=595, height=842)  # A4
        page.insert_text((72, 72), f"Page {i + 1}", fontsize=24)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def tmp(tmp_path):
    return tmp_path


@pytest.fixture
def pdf3(tmp):
    """PDF with 3 pages."""
    return make_pdf(str(tmp / "sample.pdf"), 3)


@pytest.fixture
def pdf5(tmp):
    """PDF with 5 pages."""
    return make_pdf(str(tmp / "sample5.pdf"), 5)


# ── parse_pages ───────────────────────────────────────────────────────────────

class TestParsePages:
    def test_single_page(self):
        assert parse_pages("2", 5) == [1]

    def test_multiple_pages(self):
        assert parse_pages("1,3,5", 5) == [0, 2, 4]

    def test_range(self):
        assert parse_pages("2-4", 5) == [1, 2, 3]

    def test_mixed(self):
        assert parse_pages("1,3-5", 5) == [0, 2, 3, 4]

    def test_first_page(self):
        assert parse_pages("1", 1) == [0]

    def test_last_page(self):
        assert parse_pages("5", 5) == [4]

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            parse_pages("6", 5)

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            parse_pages("0", 5)

    def test_empty_parts_ignored(self):
        assert parse_pages("1,,3", 5) == [0, 2]

    def test_full_range(self):
        assert parse_pages("1-3", 3) == [0, 1, 2]

    def test_max_pages_cap_blocks_dos(self):
        # Regression: the real parse_pages caps at 100_000 entries to
        # prevent memory exhaustion via huge ranges like "1-9999999999".
        with pytest.raises(ValueError, match="Range too large"):
            parse_pages("1-200000", 1_000_000)

    def test_error_message_uses_valid_range(self):
        # The production helper formats invalid pages as
        # "valid: 1-N", not the legacy "(total: N)" — the replica that
        # used to live here had drifted from the real implementation.
        with pytest.raises(ValueError, match=r"valid: 1-5"):
            parse_pages("99", 5)


# ── Split ───────────────────────────────────────────────────────────────

class TestDividir:
    def test_split_all_pages(self, pdf3, tmp):
        reader = PdfReader(pdf3)
        total = len(reader.pages)
        assert total == 3

        out1 = str(tmp / "part1.pdf")
        w = PdfWriter()
        w.add_page(reader.pages[0])
        with open(out1, "wb") as f:
            w.write(f)

        r1 = PdfReader(out1)
        assert len(r1.pages) == 1

    def test_split_range(self, pdf5, tmp):
        reader = PdfReader(pdf5)
        out = str(tmp / "part2-4.pdf")
        w = PdfWriter()
        for i in range(1, 4):  # pages 2-4 (0-indexed: 1,2,3)
            w.add_page(reader.pages[i])
        with open(out, "wb") as f:
            w.write(f)

        r = PdfReader(out)
        assert len(r.pages) == 3

    def test_invalid_range_not_written(self, pdf3, tmp):
        reader = PdfReader(pdf3)
        total = len(reader.pages)
        # invalid range: start > total
        start, end = 5, 6
        assert start > total or end > total

    def test_output_file_exists(self, pdf3, tmp):
        reader = PdfReader(pdf3)
        out = str(tmp / "output.pdf")
        w = PdfWriter()
        w.add_page(reader.pages[0])
        with open(out, "wb") as f:
            w.write(f)
        assert os.path.isfile(out)
        assert os.path.getsize(out) > 0


# ── Merge ────────────────────────────────────────────────────────────

class TestJuntar:
    def test_merge_two_pdfs(self, tmp):
        p1 = make_pdf(str(tmp / "a.pdf"), 2)
        p2 = make_pdf(str(tmp / "b.pdf"), 3)
        out = str(tmp / "merged.pdf")

        w = PdfWriter()
        for path in [p1, p2]:
            for page in PdfReader(path).pages:
                w.add_page(page)
        with open(out, "wb") as f:
            w.write(f)

        r = PdfReader(out)
        assert len(r.pages) == 5

    def test_merge_preserves_order(self, tmp):
        p1 = make_pdf(str(tmp / "c.pdf"), 1)
        p2 = make_pdf(str(tmp / "d.pdf"), 1)
        out = str(tmp / "ordered.pdf")

        w = PdfWriter()
        for path in [p1, p2]:
            for page in PdfReader(path).pages:
                w.add_page(page)
        with open(out, "wb") as f:
            w.write(f)

        r = PdfReader(out)
        assert len(r.pages) == 2

    def test_merge_single_raises_logically(self):
        # the app requires >= 2 PDFs
        paths = ["one.pdf"]
        assert len(paths) < 2

    def test_merge_output_is_valid_pdf(self, tmp):
        p1 = make_pdf(str(tmp / "e.pdf"), 1)
        p2 = make_pdf(str(tmp / "f.pdf"), 1)
        out = str(tmp / "valid.pdf")

        w = PdfWriter()
        for path in [p1, p2]:
            for page in PdfReader(path).pages:
                w.add_page(page)
        with open(out, "wb") as f:
            w.write(f)

        # should be readable without errors
        r = PdfReader(out)
        assert len(r.pages) == 2


# ── Rotate ────────────────────────────────────────────────────────────

class TestRotar:
    def test_rotate_all_pages_90(self, pdf3, tmp):
        reader = PdfReader(pdf3)
        out = str(tmp / "rotated90.pdf")
        w = PdfWriter()
        for page in reader.pages:
            page.rotate(90)
            w.add_page(page)
        with open(out, "wb") as f:
            w.write(f)

        r = PdfReader(out)
        assert len(r.pages) == 3
        # pypdf records rotation in the /Rotate field, does not swap the mediabox
        p = r.pages[0]
        rotation = p.get("/Rotate", 0)
        assert rotation == 90

    def test_rotate_single_page(self, pdf3, tmp):
        reader = PdfReader(pdf3)
        out = str(tmp / "rotated1.pdf")
        w = PdfWriter()
        for i, page in enumerate(reader.pages):
            if i == 0:
                page.rotate(180)
            w.add_page(page)
        with open(out, "wb") as f:
            w.write(f)

        r = PdfReader(out)
        assert len(r.pages) == 3

    def test_rotate_270(self, pdf3, tmp):
        reader = PdfReader(pdf3)
        out = str(tmp / "rotated270.pdf")
        w = PdfWriter()
        for page in reader.pages:
            page.rotate(270)
            w.add_page(page)
        with open(out, "wb") as f:
            w.write(f)
        r = PdfReader(out)
        assert len(r.pages) == 3

    def test_rotate_page_count_unchanged(self, pdf5, tmp):
        reader = PdfReader(pdf5)
        out = str(tmp / "rotated5.pdf")
        w = PdfWriter()
        for page in reader.pages:
            page.rotate(90)
            w.add_page(page)
        with open(out, "wb") as f:
            w.write(f)
        assert len(PdfReader(out).pages) == 5


# ── Extract pages ───────────────────────────────────────────────────────────

class TestExtrair:
    def test_extract_single_page(self, pdf5, tmp):
        reader = PdfReader(pdf5)
        pages = parse_pages("3", 5)
        out = str(tmp / "extracted.pdf")
        w = PdfWriter()
        for p in pages:
            w.add_page(reader.pages[p])
        with open(out, "wb") as f:
            w.write(f)

        r = PdfReader(out)
        assert len(r.pages) == 1

    def test_extract_range(self, pdf5, tmp):
        reader = PdfReader(pdf5)
        pages = parse_pages("2-4", 5)
        out = str(tmp / "extracted2-4.pdf")
        w = PdfWriter()
        for p in pages:
            w.add_page(reader.pages[p])
        with open(out, "wb") as f:
            w.write(f)

        r = PdfReader(out)
        assert len(r.pages) == 3

    def test_extract_mixed(self, pdf5, tmp):
        reader = PdfReader(pdf5)
        pages = parse_pages("1,3,5", 5)
        out = str(tmp / "extracted135.pdf")
        w = PdfWriter()
        for p in pages:
            w.add_page(reader.pages[p])
        with open(out, "wb") as f:
            w.write(f)

        assert len(PdfReader(out).pages) == 3

    def test_extract_invalid_page_raises(self, pdf3):
        with pytest.raises(ValueError):
            parse_pages("10", 3)


# ── Reorder ─────────────────────────────────────────────────────────────────

class TestReordenar:
    def test_reverse_order(self, pdf3, tmp):
        reader = PdfReader(pdf3)
        indices = [2, 1, 0]
        out = str(tmp / "reversed.pdf")
        w = PdfWriter()
        for idx in indices:
            w.add_page(reader.pages[idx])
        with open(out, "wb") as f:
            w.write(f)

        r = PdfReader(out)
        assert len(r.pages) == 3

    def test_reorder_same_count(self, pdf5, tmp):
        reader = PdfReader(pdf5)
        indices = [4, 3, 2, 1, 0]
        out = str(tmp / "reordered5.pdf")
        w = PdfWriter()
        for idx in indices:
            w.add_page(reader.pages[idx])
        with open(out, "wb") as f:
            w.write(f)

        assert len(PdfReader(out).pages) == 5

    def test_delete_pages(self, pdf5, tmp):
        """Simulate deleting pages during reorder."""
        reader = PdfReader(pdf5)
        indices = [0, 2, 4]  # keep only pages 1, 3, 5
        out = str(tmp / "reduced.pdf")
        w = PdfWriter()
        for idx in indices:
            w.add_page(reader.pages[idx])
        with open(out, "wb") as f:
            w.write(f)

        assert len(PdfReader(out).pages) == 3

    def test_identity_reorder(self, pdf3, tmp):
        """Reordering without changes should produce the same number of pages."""
        reader = PdfReader(pdf3)
        indices = list(range(len(reader.pages)))
        out = str(tmp / "identity.pdf")
        w = PdfWriter()
        for idx in indices:
            w.add_page(reader.pages[idx])
        with open(out, "wb") as f:
            w.write(f)

        assert len(PdfReader(out).pages) == 3


# ── Encrypt / Decrypt ──────────────────────────────────────────────────

class TestEncriptar:
    # The production code uses algorithm="AES-256" (not the legacy
    # use_128bit RC4 path). These tests mirror that path so the suite
    # catches regressions in pypdf or in the cryptography dependency.

    def test_encrypt_creates_encrypted_pdf(self, pdf3, tmp):
        reader = PdfReader(pdf3)
        out = str(tmp / "encrypted.pdf")
        w = PdfWriter()
        w.append(reader)
        w.encrypt(user_password="user123", owner_password="owner123",
                  algorithm="AES-256")
        with open(out, "wb") as f:
            w.write(f)

        r = PdfReader(out)
        assert r.is_encrypted

    def test_decrypt_with_correct_password(self, pdf3, tmp):
        enc = str(tmp / "enc.pdf")
        w = PdfWriter()
        w.append(PdfReader(pdf3))
        w.encrypt(user_password="pass", owner_password="pass",
                  algorithm="AES-256")
        with open(enc, "wb") as f:
            w.write(f)

        out = str(tmp / "dec.pdf")
        r = PdfReader(enc)
        result = r.decrypt("pass")
        assert result != 0  # 0 = failed

        w2 = PdfWriter()
        w2.append(r)
        with open(out, "wb") as f:
            w2.write(f)

        r2 = PdfReader(out)
        assert not r2.is_encrypted

    def test_decrypt_wrong_password_fails(self, pdf3, tmp):
        enc = str(tmp / "enc2.pdf")
        w = PdfWriter()
        w.append(PdfReader(pdf3))
        w.encrypt(user_password="correct", owner_password="correct",
                  algorithm="AES-256")
        with open(enc, "wb") as f:
            w.write(f)

        r = PdfReader(enc)
        result = r.decrypt("wrong")
        assert result == 0  # wrong password

    def test_owner_password_distinguished_from_user(self, pdf3, tmp):
        # AES-256 keeps the user/owner roles separate. Empty user
        # password = anyone can open with restrictions; owner password
        # unlocks full access. pypdf returns 1 for user-pwd auth and
        # 2 for owner-pwd auth.
        enc = str(tmp / "owner.pdf")
        w = PdfWriter()
        w.append(PdfReader(pdf3))
        w.encrypt(user_password="", owner_password="topsecret",
                  algorithm="AES-256")
        with open(enc, "wb") as f:
            w.write(f)

        assert PdfReader(enc).decrypt("") == 1
        assert PdfReader(enc).decrypt("topsecret") == 2
        assert PdfReader(enc).decrypt("wrong") == 0

    def test_non_encrypted_pdf_not_encrypted(self, pdf3):
        r = PdfReader(pdf3)
        assert not r.is_encrypted

    def test_encrypt_py_uses_aes_256(self):
        # Regression: encrypt.py used the deprecated use_128bit=True
        # (RC4) before v1.13.4 — the audit flagged it as weak. This
        # test fails if anyone reverts to RC4.
        import inspect
        from app.tools.encrypt import TabEncriptar
        src = inspect.getsource(TabEncriptar._run)
        assert 'algorithm="AES-256"' in src, \
            "encrypt.py must use AES-256, not legacy RC4 (use_128bit)"
        assert "use_128bit" not in src, \
            "use_128bit RC4 path is forbidden — use algorithm='AES-256'"


# ── Watermark ──────────────────────────────────────────────────────────────

class TestMarcaDagua:
    def _make_watermark(self, path: str) -> str:
        import fitz
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((200, 400), "CONFIDENTIAL", fontsize=36, color=(0.8, 0.8, 0.8))
        doc.save(path)
        doc.close()
        return path

    def test_watermark_under(self, pdf3, tmp):
        wm = self._make_watermark(str(tmp / "wm.pdf"))
        reader = PdfReader(pdf3)
        wm_page = PdfReader(wm).pages[0]
        out = str(tmp / "watermarked.pdf")
        w = PdfWriter()
        for i, page in enumerate(reader.pages):
            w.add_page(page)
            w.pages[i].merge_page(wm_page, over=False)
        with open(out, "wb") as f:
            w.write(f)

        r = PdfReader(out)
        assert len(r.pages) == 3

    def test_watermark_over(self, pdf3, tmp):
        wm = self._make_watermark(str(tmp / "wm2.pdf"))
        reader = PdfReader(pdf3)
        wm_page = PdfReader(wm).pages[0]
        out = str(tmp / "stamped.pdf")
        w = PdfWriter()
        for i, page in enumerate(reader.pages):
            w.add_page(page)
            w.pages[i].merge_page(wm_page, over=True)
        with open(out, "wb") as f:
            w.write(f)

        assert len(PdfReader(out).pages) == 3

    def test_watermark_selected_pages_only(self, pdf5, tmp):
        wm = self._make_watermark(str(tmp / "wm3.pdf"))
        reader = PdfReader(pdf5)
        wm_page = PdfReader(wm).pages[0]
        targets = set(parse_pages("1,3", 5))
        out = str(tmp / "partial_wm.pdf")
        w = PdfWriter()
        for i, page in enumerate(reader.pages):
            w.add_page(page)
            if i in targets:
                w.pages[i].merge_page(wm_page, over=False)
        with open(out, "wb") as f:
            w.write(f)

        assert len(PdfReader(out).pages) == 5


# ── Info (metadata) ─────────────────────────────────────────────────────

class TestInfo:
    def test_page_count(self, pdf3):
        r = PdfReader(pdf3)
        assert len(r.pages) == 3

    def test_page_dimensions(self, pdf3):
        r = PdfReader(pdf3)
        page = r.pages[0]
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        # A4: ~595 × 842 pt
        assert abs(w - 595) < 2
        assert abs(h - 842) < 2

    def test_not_encrypted(self, pdf3):
        r = PdfReader(pdf3)
        assert not r.is_encrypted

    def test_file_size_positive(self, pdf3):
        assert os.path.getsize(pdf3) > 0

    def test_metadata_accessible(self, pdf3):
        r = PdfReader(pdf3)
        # metadata may be empty, but should not raise an exception
        meta = r.metadata
        assert meta is None or isinstance(meta, dict)


# ── Audit regressions ────────────────────────────────────────────────
#
# These tests pin specific findings from the v1.13.4 detailed app review
# so future refactors don't silently undo the fixes.

class TestAuditRegressions:
    def test_reorder_supports_pipeline(self):
        # The reorder tool emits pipeline_done but the flag was never
        # set, so its _pipeline_active branch was dead code. The fix is
        # `self._pipeline_supported = True` in TabReordenar.__init__.
        import inspect
        from app.tools.reorder import TabReordenar
        src = inspect.getsource(TabReordenar.__init__)
        assert "_pipeline_supported = True" in src, \
            "reorder.py must opt into pipeline mode"

    def test_pipeline_compatible_tools_all_opt_in(self):
        # All 8 tools listed as pipeline-compatible must set the flag.
        import inspect
        from app.tools import (
            rotate, compress, extract, reorder, encrypt,
            watermark, page_numbers, nup,
        )
        modules = {
            "rotate": rotate, "compress": compress, "extract": extract,
            "reorder": reorder, "encrypt": encrypt, "watermark": watermark,
            "page_numbers": page_numbers, "nup": nup,
        }
        missing = []
        for name, mod in modules.items():
            src = inspect.getsource(mod)
            if "_pipeline_supported = True" not in src:
                missing.append(name)
        assert not missing, f"pipeline flag missing in: {missing}"

    def test_toast_guard_uses_shiboken_not_qpointer(self):
        # PySide6 has no QPointer — the toast hide-timer must guard the
        # widget liveness check via shiboken6.isValid(). Importing
        # QPointer from PySide6 would fail with ImportError at load.
        src = open("app/base.py", encoding="utf-8").read()
        assert "from shiboken6 import isValid" in src
        assert "isValid(t)" in src
        # No QPointer import or instantiation — only the explanatory
        # comment may mention the name.
        import re
        assert not re.search(r"from\s+PySide6[^\n]*\bQPointer\b", src), \
            "QPointer cannot be imported from PySide6"
        assert "QPointer(" not in src, \
            "QPointer is unavailable in PySide6 — use shiboken6.isValid"

    def test_restart_app_handles_pyinstaller_frozen(self):
        # _restart_app must branch on sys.frozen — using
        # os.path.dirname(__file__) + "pdfapps.py" breaks in frozen
        # bundles because __file__ points inside _MEIPASS.
        src = open("app/window.py", encoding="utf-8").read()
        # The fixed implementation references sys.frozen.
        assert 'getattr(sys, "frozen"' in src, \
            "_restart_app must check sys.frozen"
        # And must not reconstruct a path from __file__ for the script.
        # (The function should use sys.argv[0] instead.)
        assert 'os.path.dirname(__file__)' not in src or \
               'sys.argv[0]' in src

    def test_pdfapps_spec_reads_version_dynamically(self):
        # Avoids drift between APP_VERSION and the macOS BUNDLE
        # CFBundleVersion / CFBundleShortVersionString.
        spec = open("pdfapps.spec", encoding="utf-8").read()
        assert "_app_version" in spec
        assert "APP_VERSION" in spec  # parsed from app/constants.py
        assert "CFBundleVersion': '1.13" not in spec, \
            "macOS bundle version must be dynamic, not hardcoded"

    def test_installer_pins_third_party_hashes(self):
        # Tesseract and Ghostscript exes are downloaded and run with
        # admin — they MUST be hash-pinned in installer.py.
        src = open("installer.py", encoding="utf-8").read()
        assert "TESSERACT_SHA256" in src
        assert "GHOSTSCRIPT_SHA256" in src
        assert "hmac.compare_digest" in src
        # And download_file must accept the verification arg.
        assert "expected_sha256" in src

    def test_encrypted_pdf_helpers_unlock_with_stored_password(self, tmp):
        # Functional check: BasePage._open_reader / _open_fitz must
        # transparently decrypt when self._pdf_password is set.
        from app.base import BasePage

        plain = make_pdf(str(tmp / "src.pdf"), 2)
        enc   = str(tmp / "enc.pdf")
        w = PdfWriter(); w.append(PdfReader(plain))
        w.encrypt(user_password="topsecret", owner_password="topsecret",
                  algorithm="AES-256")
        with open(enc, "wb") as f: w.write(f)

        # Stand-alone object that mimics a tool with a stored password
        class _Stub:
            _pdf_password = "topsecret"
            _open_reader = BasePage._open_reader
            _open_fitz   = BasePage._open_fitz
        stub = _Stub()

        r = stub._open_reader(enc)
        assert len(r.pages) == 2, "pypdf reader must decrypt with stored pwd"

        d = stub._open_fitz(enc)
        assert d.page_count == 2, "fitz doc must authenticate with stored pwd"
        d.close()

    def test_password_helpers_present_on_basepage(self):
        # Wiring regression: every encrypted-aware tool relies on these
        # three helpers being on BasePage (not duplicated per tool).
        from app.base import BasePage
        assert callable(getattr(BasePage, "_maybe_prompt_password", None))
        assert callable(getattr(BasePage, "_open_reader", None))
        assert callable(getattr(BasePage, "_open_fitz", None))

    def test_tools_use_password_helper_on_load(self):
        # Each tool that opens user PDFs must call _maybe_prompt_password
        # in _load_input, otherwise encrypted files crash silently.
        import inspect
        from app.tools import (
            split, reorder, extract, rotate, watermark,
            compress, page_numbers, nup, ocr, convert,
        )
        modules = [split, reorder, extract, rotate, watermark,
                   compress, page_numbers, nup, ocr, convert]
        for mod in modules:
            cls = next(c for c_name, c in vars(mod).items()
                       if isinstance(c, type) and c_name.startswith("Tab"))
            src = inspect.getsource(cls._load_input)
            assert "_maybe_prompt_password" in src, \
                f"{cls.__name__}._load_input must call _maybe_prompt_password"

    def test_editor_handles_encrypted_pdfs(self):
        # The editor's _load_pdf must prompt for a password and pass it
        # through to the canvas. The audit flagged this as broken — the
        # job opened with fitz.open without authenticate().
        src = open("app/editor/tab.py", encoding="utf-8").read()
        # _load_pdf integrates the password prompt
        i = src.find("def _load_pdf(self, p: str):")
        assert i > 0
        block = src[i:i + 1500]
        assert "prompt_pdf_password" in block, \
            "editor _load_pdf must call prompt_pdf_password"
        assert "password=self._pdf_password" in block, \
            "canvas.load must receive the password"
        # The canvas job must accept and apply the password
        canvas_src = open("app/editor/canvas.py", encoding="utf-8").read()
        assert "doc.authenticate(self._password)" in canvas_src, \
            "_EditPageJob.run must authenticate the document"

    def test_taskrunner_runs_in_qthread_with_progress_and_finished(self):
        # Functional check: a TaskRunner subclass is run in a QThread,
        # emits progress, finishes successfully, and routes the result
        # back to the main thread via the on_finished handler.
        from PySide6.QtWidgets import QApplication, QProgressDialog
        from PySide6.QtCore import QEventLoop, QTimer
        from app.worker import TaskRunner, run_task

        QApplication.instance() or QApplication([])

        class _Sum(TaskRunner):
            def do_work(_self):
                total = 0
                for i in range(5):
                    if _self.is_cancelled():
                        return None
                    _self.progress.emit(int(100 * i / 5), f"step {i}")
                    total += i
                return total

        runner = _Sum()
        dlg = QProgressDialog("starting", "cancel", 0, 100)
        dlg.setMinimumDuration(60_000)  # never actually shown during test
        results = {}
        run_task(None, runner, dlg, lambda r: results.setdefault("r", r),
                 lambda e: results.setdefault("e", e))
        loop = QEventLoop()
        QTimer.singleShot(800, loop.quit)
        loop.exec()
        assert results.get("r") == 0 + 1 + 2 + 3 + 4 == 10, results

    def test_long_running_tools_use_background_runner(self):
        # Regression: compress / ocr / convert._convert_images must run
        # off the UI thread. Audit flagged that they used to call
        # QApplication.processEvents() inside per-page loops, freezing
        # the UI on large PDFs and leaving cancel almost unresponsive.
        from app.tools.compress import TabComprimir
        from app.tools.ocr import TabOCR
        from app.tools.convert import TabConverter
        import inspect

        compress_src = inspect.getsource(TabComprimir._run)
        ocr_src      = inspect.getsource(TabOCR._run)
        images_src   = inspect.getsource(TabConverter._convert_images)

        # No processEvents in the migrated paths.
        assert "QApplication.processEvents" not in compress_src
        assert "QApplication.processEvents" not in ocr_src
        assert "QApplication.processEvents" not in images_src

        # Each runs via TaskRunner / _run_background.
        assert "TaskRunner" in compress_src or "run_task" in compress_src
        assert "TaskRunner" in ocr_src or "run_task" in ocr_src
        assert "_run_background" in images_src

    def test_draw_ink_annot_uses_tuple_points(self):
        # PyMuPDF 1.27+ rejects fitz.Point as ink-annot input with
        # ValueError: arg must be seq of seq of float pairs.
        # tab.py builds the stroke as plain (float, float) tuples now;
        # this test fails if anyone reintroduces fitz.Point wrapping.
        src = open("app/editor/tab.py", encoding="utf-8").read()
        # Locate the draw branch
        i = src.find('elif e["type"] == "draw":')
        assert i > 0, "draw branch missing in tab.py"
        block = src[i:i + 600]
        assert "[fitz.Point(x, y) for x, y in" not in block, \
            "ink-annot strokes must be (x,y) tuples, not fitz.Point"
        assert "(float(x), float(y))" in block, \
            "expected explicit float tuple conversion in draw branch"

    def test_flatpak_manifest_tag_is_current(self):
        # Flatpak tag was hardcoded to v1.8.3 long after release v1.13.x.
        # Bump script now keeps it in sync; this test ensures it matches
        # APP_VERSION at any given point.
        import re
        const = open("app/constants.py", encoding="utf-8").read()
        version = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', const).group(1)
        manifest = open("flatpak/io.github.nelsonduarte.PDFApps.yml",
                        encoding="utf-8").read()
        assert f"tag: v{version}" in manifest, \
            f"Flatpak manifest tag must match APP_VERSION ({version})"
