"""Behavioural regression tests for the viewer shared-fitz-handle,
saveIncr↔render race, search debounce and password-cancel fixes.

These target the adversarial-audit bugs in ``app/viewer/canvas.py`` and
``app/viewer/panel.py``:

* M2   — panel._fitz_doc must never keep pointing at a Document the
         canvas closed+reopened in the failed-saveIncr path; and
         _do_search / _print_pdf must not crash on a closed handle.
* race — the delete-comment path must cancel in-flight render workers
         (bump _gen + clear _pending) before saveIncr appends to disk.
* debounce — rapid keystrokes must coalesce into a single _do_search.
* cancel-password — cancelling the prompt for a new encrypted PDF must
         restore a coherent placeholder state.

All widget tests run on the offscreen platform.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

import fitz  # noqa: E402
from app.i18n import t  # noqa: E402
from app.viewer.panel import PdfViewerPanel  # noqa: E402

CANVAS_SRC = (ROOT / "app" / "viewer" / "canvas.py").read_text(encoding="utf-8")


# ── Fixtures ────────────────────────────────────────────────────────────


def _make_pdf(path: Path, text: str = "Hello World", n_annots: int = 0):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), text, fontsize=18)
    for i in range(n_annots):
        page.add_text_annot((100, 150 + 40 * i), f"note {i}")
    doc.save(str(path))
    doc.close()
    return path


def _make_encrypted_pdf(path: Path, password: str = "secret"):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Encrypted", fontsize=18)
    doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256,
             owner_pw=password, user_pw=password)
    doc.close()
    return path


def _pump(qtbot=None, ms: int = 60):
    """Flush the QTimer.singleShot(0) layout + queued events."""
    for _ in range(5):
        _app.processEvents()
    if qtbot is not None:
        qtbot.wait(ms)


# ── M2: shared fitz handle stays valid ──────────────────────────────────


def test_doc_replaced_signal_repoints_panel_handle(qtbot, tmp_path):
    """When the canvas closes+reopens the shared Document, the panel must
    follow the new handle (root cause of M2). Without the doc_replaced
    wiring, _fitz_doc stays pinned to the closed Document."""
    pdf = _make_pdf(tmp_path / "a.pdf")
    panel = PdfViewerPanel()
    qtbot.addWidget(panel)
    panel.load(str(pdf))
    _pump(qtbot)

    old = panel._fitz_doc
    assert old is not None
    # Emulate exactly what the canvas failed-saveIncr path does: it closes
    # the shared doc and emits a fresh handle.
    old.close()
    new = fitz.open(str(pdf))
    panel._canvas.doc_replaced.emit(new)

    assert panel._fitz_doc is new
    assert not panel._fitz_doc.is_closed
    # Search now works against the live handle.
    panel._do_search("Hello")
    assert panel._search_results  # found the text, no crash


def test_do_search_survives_closed_document(qtbot, tmp_path):
    """Defensive guard: even if _fitz_doc is a closed Document (e.g. a
    race we failed to repoint), a keystroke must not raise
    RuntimeError: document closed."""
    pdf = _make_pdf(tmp_path / "b.pdf")
    panel = PdfViewerPanel()
    qtbot.addWidget(panel)
    panel.load(str(pdf))
    _pump(qtbot)

    panel._fitz_doc.close()  # simulate the stale/closed handle
    # Must not raise.
    panel._do_search("Hello")


def test_print_pdf_guards_closed_document(qtbot, tmp_path, monkeypatch):
    """_print_pdf must short-circuit on a closed Document BEFORE building
    the print dialog — otherwise len(closed_doc) raises."""
    pdf = _make_pdf(tmp_path / "c.pdf")
    panel = PdfViewerPanel()
    qtbot.addWidget(panel)
    panel.load(str(pdf))
    _pump(qtbot)
    panel._fitz_doc.close()

    # Fail loudly if the guard is missing and execution reaches the dialog.
    import PySide6.QtPrintSupport as qps

    class _Boom:
        def __init__(self, *a, **k):
            raise AssertionError("print reached dialog on a closed doc")

    monkeypatch.setattr(qps, "QPrintDialog", _Boom)
    # Must return quietly, no exception, no dialog.
    assert panel._print_pdf() is None


def test_canvas_error_path_emits_doc_replaced_source():
    """End-to-end driving of the delete-comment context menu is not
    feasible headless (QMenu.exec spins a blocking native popup loop that
    PySide won't let us monkeypatch). Guard the two canvas-internal halves
    of the M2 fix at source level instead:

    the failed-saveIncr except block must reopen the Document AND emit
    doc_replaced with the fresh handle, so the panel (shared owner) is
    repointed off the closed one.
    """
    idx = CANVAS_SRC.index("self._doc.saveIncr()")
    after = CANVAS_SRC[idx: idx + 2600]
    assert "self._doc = new_doc" in after, "reopen path missing"
    # The emit must come after the reopen and carry the new handle.
    reopen_at = after.index("self._doc = new_doc")
    assert "self.doc_replaced.emit(new_doc)" in after[reopen_at:], \
        "canvas no longer notifies the panel of the reopened Document (M2)"


def test_canvas_signal_declared_and_panel_wired():
    """The canvas exposes doc_replaced and the panel connects it."""
    assert "doc_replaced = Signal(object)" in CANVAS_SRC
    panel_src = (ROOT / "app" / "viewer" / "panel.py").read_text(encoding="utf-8")
    assert "self._canvas.doc_replaced.connect(self._on_doc_replaced)" in panel_src


# ── race: render workers cancelled before saveIncr ──────────────────────


def test_race_guard_cancels_renders_before_saveincr():
    """The delete-comment path must cancel/join in-flight render workers
    (bump _gen, clear _pending, waitForDone) BEFORE saveIncr() appends to
    the same file — otherwise a worker mid-fitz.open() reads a
    half-written incremental update. Guarded at source level because the
    QMenu popup loop can't be driven headless."""
    save_idx = CANVAS_SRC.index("self._doc.saveIncr()")
    # Window between the `if self._path:` guard and the saveIncr call.
    before = CANVAS_SRC[max(0, save_idx - 700): save_idx]
    assert "self._gen += 1" in before, "renders not invalidated before saveIncr"
    assert "self._pending.clear()" in before, "_pending not cleared before saveIncr"
    assert "waitForDone()" in before, "in-flight workers not joined before saveIncr"


# ── debounce: rapid keystrokes coalesce ─────────────────────────────────


def test_search_is_debounced(qtbot, tmp_path):
    """Typing several characters quickly must NOT run a full-document
    scan per keystroke — the search fires once, after the debounce."""
    pdf = _make_pdf(tmp_path / "f.pdf", text="Hello World")
    panel = PdfViewerPanel()
    qtbot.addWidget(panel)
    panel.load(str(pdf))
    _pump(qtbot)

    calls: list[str] = []
    orig = panel._do_search

    def _spy(q):
        calls.append(q)
        return orig(q)

    panel._do_search = _spy

    panel._search_input.setText("H")
    panel._search_input.setText("He")
    panel._search_input.setText("Hello")
    # No synchronous scan yet — the debounce timer is pending.
    assert calls == [], "search ran synchronously per keystroke (no debounce)"
    assert panel._search_debounce.isActive()

    # Fire the debounce.
    panel._run_pending_search()
    assert calls == ["Hello"], f"expected one debounced search, got {calls}"
    assert panel._search_results, "debounced search produced no results"


def test_empty_query_clears_without_debounce(qtbot, tmp_path):
    """Clearing the box resets immediately and cancels any pending scan."""
    pdf = _make_pdf(tmp_path / "g.pdf")
    panel = PdfViewerPanel()
    qtbot.addWidget(panel)
    panel.load(str(pdf))
    _pump(qtbot)

    panel._search_input.setText("Hello")
    assert panel._search_debounce.isActive()
    panel._search_input.setText("")
    assert not panel._search_debounce.isActive()
    assert panel._search_results == []


# ── cancel password: coherent placeholder state ─────────────────────────


def test_cancel_password_restores_placeholder(qtbot, tmp_path, monkeypatch):
    """Opening a new encrypted PDF over an already-open document and
    cancelling the password prompt must leave the viewer in a coherent
    placeholder state (placeholder shown, splitter hidden, title reset,
    navigation disabled) — not an empty splitter with a stale title."""
    plain = _make_pdf(tmp_path / "plain.pdf")
    enc = _make_encrypted_pdf(tmp_path / "enc.pdf")

    panel = PdfViewerPanel()
    qtbot.addWidget(panel)
    panel.load(str(plain))
    _pump(qtbot)
    # Sanity: a document is open, splitter shown / placeholder hidden.
    # isVisibleTo(panel) reflects the local setVisible flags without
    # needing the (never-shown) top-level window to be exposed.
    assert panel._viewer_splitter.isVisibleTo(panel)
    assert not panel._placeholder.isVisibleTo(panel)

    # Cancel the password dialog for the new encrypted file.
    from PySide6.QtWidgets import QDialog
    import app.editor.dialogs as dialogs
    monkeypatch.setattr(dialogs._PdfPasswordDialog, "exec",
                        lambda self, *a, **k: QDialog.DialogCode.Rejected)

    panel.load(str(enc))

    assert panel._fitz_doc is None
    assert panel._placeholder.isVisibleTo(panel)
    assert not panel._viewer_splitter.isVisibleTo(panel)
    assert not panel._sidebar_tabs.isVisibleTo(panel)
    assert panel._name_lbl.text() == t("viewer.title")
    assert not panel._sel_status.isVisibleTo(panel)
    for btn in (panel._prev_btn, panel._next_btn, panel._zoom_in_btn,
                panel._zoom_out_btn, panel._fit_btn, panel._print_btn):
        assert not btn.isEnabled(), "navigation left enabled after cancel"
