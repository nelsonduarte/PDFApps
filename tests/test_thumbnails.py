"""Regression tests for the viewer thumbnails sidebar.

Blends source-level guards (cheap, no Qt event loop needed) with
behavioural tests on the ``ThumbnailModel`` (which is pure Qt data, no
threading). Full end-to-end rendering requires a real ``QApplication``
and is exercised by the smoke import + manual QA on the release
candidate — see the parent task's manual test plan.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


THUMBS_SRC = (ROOT / "app" / "viewer" / "thumbnails.py").read_text(
    encoding="utf-8")
PANEL_SRC = (ROOT / "app" / "viewer" / "panel.py").read_text(
    encoding="utf-8")


# ── Import / API surface ──────────────────────────────────────────────


def test_module_imports():
    from app.viewer import thumbnails
    assert hasattr(thumbnails, "ThumbnailPanel")
    assert hasattr(thumbnails, "ThumbnailModel")
    assert hasattr(thumbnails, "ThumbnailDelegate")
    assert hasattr(thumbnails, "ThumbnailWorker")


def test_public_signal_present():
    """Guards against a rename of the signal the viewer wires into."""
    assert "page_requested" in THUMBS_SRC
    assert "Signal(int)" in THUMBS_SRC


def test_worker_uses_qthread():
    assert "class ThumbnailWorker(QThread)" in THUMBS_SRC


def test_worker_pixmap_lifetime_uses_copy():
    """The QImage-from-Pixmap pattern requires .copy() so pixels don't
    disappear when the fitz Pixmap is freed on the next loop iteration
    (same pattern as the print loop and OCR Round 3)."""
    assert ".copy()" in THUMBS_SRC


def test_worker_emits_qimage_not_qpixmap():
    """QPixmap construction is main-thread-only in Qt. The worker must
    emit QImage; the panel converts to QPixmap in a main-thread slot."""
    # Signal should carry QImage, not QPixmap.
    assert "Signal(int, QImage)" in THUMBS_SRC, (
        "ThumbnailWorker.thumbnail_ready must emit QImage, not QPixmap, "
        "since QPixmap construction requires the main GUI thread"
    )
    # The main-thread slot converts image -> pixmap.
    assert "QPixmap.fromImage" in THUMBS_SRC


def test_signal_uses_queued_connection():
    """Py3.14 PySide6 requires explicit QueuedConnection for
    cross-thread signals so slots run on the receiver's thread
    (see memory/project_compress_freeze_py314.md)."""
    assert "QueuedConnection" in THUMBS_SRC


def test_image_ready_slot_decorated():
    """@Slot decorator on the receiver keeps Py3.14 PySide6 routing
    predictable for cross-thread signal delivery."""
    assert "@Slot(int, QImage)" in THUMBS_SRC
    assert "_on_image_ready" in THUMBS_SRC


def test_worker_passes_password_to_fitz():
    """Encrypted PDFs would raise on every page render without this."""
    assert "authenticate" in THUMBS_SRC


def test_delegate_highlights_current_page():
    assert "set_current_page" in THUMBS_SRC
    assert "_current_page" in THUMBS_SRC


def test_cache_has_size_limit():
    """The dict cache must be capped so long PDFs don't leak memory."""
    assert "CACHE_MAX" in THUMBS_SRC


# ── Model behaviour ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def qapp():
    """Session-scoped QApplication for the model tests. QListView is
    not built here, but QAbstractListModel / QModelIndex constructors
    dereference the Qt runtime, so an app must exist."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_model_starts_empty(qapp):
    from app.viewer.thumbnails import ThumbnailModel
    m = ThumbnailModel()
    assert m.rowCount() == 0
    assert m.cache_size() == 0


def test_model_row_count_matches_page_count(qapp):
    from app.viewer.thumbnails import ThumbnailModel
    m = ThumbnailModel()
    m.set_document("/nonexistent.pdf", 10)
    assert m.rowCount() == 10
    m.clear()
    assert m.rowCount() == 0
    assert m.cache_size() == 0


def test_model_cache_evicts_lru(qapp):
    """Insert CACHE_MAX + 5 pixmaps and confirm the oldest 5 are
    evicted so the cache stays at the cap."""
    from PySide6.QtGui import QPixmap
    from app.viewer.thumbnails import CACHE_MAX, ThumbnailModel
    m = ThumbnailModel()
    m.set_document("/x.pdf", CACHE_MAX + 5)
    for i in range(CACHE_MAX + 5):
        m.cache_pixmap(i, QPixmap(1, 1))
    assert m.cache_size() == CACHE_MAX


def test_model_data_returns_none_out_of_range(qapp):
    from PySide6.QtCore import Qt
    from app.viewer.thumbnails import ThumbnailModel
    m = ThumbnailModel()
    m.set_document("/x.pdf", 3)
    bad = m.index(99)
    assert m.data(bad, Qt.ItemDataRole.DecorationRole) is None
    good = m.index(0)
    # No pixmap cached yet → decoration is None (delegate paints ...
    # placeholder), display returns 1-based page number.
    assert m.data(good, Qt.ItemDataRole.DecorationRole) is None
    assert m.data(good, Qt.ItemDataRole.DisplayRole) == "1"


# ── Panel integration ────────────────────────────────────────────────


def test_panel_wires_thumbnail_panel():
    """Viewer must instantiate ThumbnailPanel and route its signal."""
    assert "ThumbnailPanel" in PANEL_SRC
    assert "page_requested" in PANEL_SRC
    assert "_on_thumbnail_clicked" in PANEL_SRC


def test_panel_syncs_current_page_on_scroll():
    """Scrolling the canvas must update the thumbnail highlight."""
    assert "self._thumbnails.set_current_page(idx)" in PANEL_SRC


def test_panel_loads_thumbnails_on_open():
    assert "self._thumbnails.set_document(" in PANEL_SRC


def test_panel_clears_thumbnails_on_close_and_replace():
    """Both the closeEvent and the doc-replace path must stop the
    worker so a stale QThread doesn't outlive the panel."""
    assert PANEL_SRC.count("self._thumbnails.clear()") >= 2


def test_panel_updates_thumbnails_theme():
    assert "self._thumbnails.update_theme(dark)" in PANEL_SRC


# ── i18n ──────────────────────────────────────────────────────────────


def test_i18n_keys_present_in_all_langs():
    with open(ROOT / "app" / "translations.json", encoding="utf-8") as f:
        data = json.load(f)
    langs = ["en", "pt", "es", "fr", "de", "it", "nl", "zh"]
    for lang in langs:
        assert lang in data, f"language {lang} missing"
        for key in ("viewer.sidebar.pages",
                    "viewer.sidebar.contents",
                    "viewer.thumbnails.loading"):
            assert key in data[lang], f"{lang}: {key} missing"
            assert data[lang][key].strip(), f"{lang}: {key} empty"


def test_i18n_key_parity():
    """Every language dict must expose exactly the same keys."""
    with open(ROOT / "app" / "translations.json", encoding="utf-8") as f:
        data = json.load(f)
    reference = set(data["en"].keys())
    for lang, entries in data.items():
        assert set(entries.keys()) == reference, (
            f"{lang} diverges: "
            f"+{set(entries) - reference} -{reference - set(entries)}"
        )
