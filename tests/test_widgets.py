"""Unit tests for pure logic inside app.widgets.

DropFileEdit._parse_extensions is used at both dragEnter and drop time
to decide whether a file is acceptable for the drop zone. Any regression
here silently allows (or rejects) files that shouldn't be.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

# DropFileEdit._parse_extensions is a staticmethod — we can call it
# without instantiating the widget (which would need a QApplication).
from app.widgets import DropFileEdit


parse = DropFileEdit._parse_extensions


class TestParseExtensions:
    def test_pdf_with_all_files_fallback(self):
        # The default file_filter.pdf translation. The ";;All (*.*)"
        # secondary group must not relax the filter back to everything.
        assert parse("PDF Files (*.pdf);;All (*.*)") == (".pdf",)

    def test_single_extension(self):
        assert parse("Word Document (*.docx)") == (".docx",)

    def test_multiple_extensions(self):
        exts = parse("Images (*.png *.jpg *.jpeg *.bmp *.tiff *.webp)")
        assert exts == (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp")

    def test_lowercased(self):
        # The primary group can mix case; the parser folds to lower so
        # `endswith()` comparisons are consistent.
        assert parse("PDF (*.PDF)") == (".pdf",)

    def test_only_wildcard_returns_empty(self):
        # "All (*.*)" alone means "accept anything" → () means no filter.
        assert parse("All (*.*)") == ()

    def test_empty_string_returns_empty(self):
        assert parse("") == ()

    def test_none_returns_empty(self):
        assert parse(None) == ()

    def test_uses_primary_group_only(self):
        # The parser must *only* look at the first group (before ;;),
        # otherwise the "All (*.*)" in the fallback would let everything
        # through.
        exts = parse("PDF (*.pdf);;All (*.*)")
        assert ".pdf" in exts
        assert ".*" not in exts

    def test_ignores_filter_without_extensions(self):
        # Some filters may not include any *.ext pattern (e.g. a label).
        assert parse("Folder") == ()
