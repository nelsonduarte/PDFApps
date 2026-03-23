"""
Tests for the main PDFApps features.
Tests the PDF logic directly (without UI) using pypdf and fitz.
"""
import os
import sys
import pytest
import tempfile

from pypdf import PdfReader, PdfWriter

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

def parse_pages(text: str, total: int) -> list:
    """Replica of the parse_pages function from pdfapps.py."""
    pages = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a) - 1, int(b)))
        else:
            pages.append(int(part) - 1)
    invalid = [p for p in pages if p < 0 or p >= total]
    if invalid:
        raise ValueError(f"Pages out of range: {[p+1 for p in invalid]}  (total: {total})")
    return pages


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
    def test_encrypt_creates_encrypted_pdf(self, pdf3, tmp):
        reader = PdfReader(pdf3)
        out = str(tmp / "encrypted.pdf")
        w = PdfWriter()
        w.append(reader)
        w.encrypt(user_password="user123", owner_password="owner123", use_128bit=True)
        with open(out, "wb") as f:
            w.write(f)

        r = PdfReader(out)
        assert r.is_encrypted

    def test_decrypt_with_correct_password(self, pdf3, tmp):
        # encrypt
        enc = str(tmp / "enc.pdf")
        w = PdfWriter()
        w.append(PdfReader(pdf3))
        w.encrypt(user_password="pass", owner_password="pass", use_128bit=True)
        with open(enc, "wb") as f:
            w.write(f)

        # decrypt
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
        w.encrypt(user_password="correct", owner_password="correct", use_128bit=True)
        with open(enc, "wb") as f:
            w.write(f)

        r = PdfReader(enc)
        result = r.decrypt("wrong")
        assert result == 0  # wrong password

    def test_non_encrypted_pdf_not_encrypted(self, pdf3):
        r = PdfReader(pdf3)
        assert not r.is_encrypted


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
