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
from app.viewer.canvas import _SelectCanvas  # noqa: E402
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


def test_reopen_document_swaps_handle_and_emits_live(qtbot, tmp_path):
    """Behavioural M2: _reopen_document (the failed-saveIncr recovery
    step) must close the old handle, open a FRESH live Document, publish
    it on self._doc and emit doc_replaced with it — so the panel (shared
    owner) never keeps pointing at the closed one."""
    pdf = _make_pdf(tmp_path / "reopen_ok.pdf")
    canvas = _SelectCanvas()
    qtbot.addWidget(canvas)
    canvas.load(fitz.open(str(pdf)), path=str(pdf))
    _pump(qtbot)

    emitted: list = []
    canvas.doc_replaced.connect(lambda d: emitted.append(d))
    old_doc = canvas._doc

    new_doc = canvas._reopen_document()

    assert new_doc is not None, "reopen should have produced a live handle"
    assert canvas._doc is new_doc, "canvas did not publish the reopened handle"
    assert not new_doc.is_closed
    assert new_doc is not old_doc
    assert old_doc.is_closed, "the stale (pre-reopen) handle must be closed"
    assert emitted == [new_doc], "doc_replaced must carry the fresh handle"


def test_reopen_failure_leaves_doc_none_not_closed(qtbot, tmp_path, monkeypatch):
    """MINOR 3 root cause: a DOUBLE failure — the reopen fitz.open() also
    raises — must leave self._doc == None (every accessor guards for that),
    NEVER a closed Document (latent use-after-close). The panel is told via
    doc_replaced(None) so it drops the shared reference too."""
    pdf = _make_pdf(tmp_path / "reopen_fail.pdf")
    canvas = _SelectCanvas()
    qtbot.addWidget(canvas)
    canvas.load(fitz.open(str(pdf)), path=str(pdf))
    _pump(qtbot)

    emitted: list = []
    canvas.doc_replaced.connect(lambda d: emitted.append(d))
    old_doc = canvas._doc

    def _boom_open(*a, **k):
        raise RuntimeError("reopen boom")

    monkeypatch.setattr(fitz, "open", _boom_open)

    new_doc = canvas._reopen_document()

    assert new_doc is None
    assert canvas._doc is None, "doc left pointing at a closed Document (use-after-close)"
    assert emitted == [None], "panel not told to drop the shared reference on double failure"
    assert old_doc.is_closed, "the stale handle must have been closed"
    # A subsequent layout/schedule must not crash on the None doc.
    canvas._layout_and_schedule()  # guarded no-op, must not raise


def test_reopen_document_wired_into_failed_save_path():
    """The failed-saveIncr except block must delegate to _reopen_document
    (which owns the None-before-open ordering) rather than reopening
    inline — a regression to inline reopen could drop the guard."""
    idx = CANVAS_SRC.index("self._doc.saveIncr()")
    after = CANVAS_SRC[idx: idx + 1600]
    assert "self._reopen_document()" in after, \
        "failed-save path no longer routes through _reopen_document (MINOR 3)"


def test_canvas_signal_declared_and_panel_wired():
    """The canvas exposes doc_replaced and the panel connects it."""
    assert "doc_replaced = Signal(object)" in CANVAS_SRC
    panel_src = (ROOT / "app" / "viewer" / "panel.py").read_text(encoding="utf-8")
    assert "self._canvas.doc_replaced.connect(self._on_doc_replaced)" in panel_src


# ── race: render workers cancelled before saveIncr ──────────────────────


def test_prepare_for_save_bumps_gen_and_clears_pending(qtbot):
    """Behavioural race guard: _prepare_for_save must invalidate the epoch
    (_gen++) and clear _pending so any render that lands after a saveIncr
    is discarded by _on_page_ready. An idle pool drains immediately, so it
    reports success."""
    canvas = _SelectCanvas()
    qtbot.addWidget(canvas)
    canvas._gen = 3
    canvas._pending = {0, 1, 2}

    drained = canvas._prepare_for_save()

    assert canvas._gen == 4, "generation not bumped — late renders not invalidated"
    assert canvas._pending == set(), "_pending not cleared before save"
    assert drained is True, "idle render pool should drain within the timeout"


def test_prepare_for_save_uses_bounded_wait_and_survives_timeout(qtbot):
    """MINOR 1: the join must be BOUNDED (a real timeout in ms), never the
    unbounded waitForDone() (-1) that could pin the UI thread forever. Even
    when the wait times out, the epoch guard must already be advanced so a
    late render is dropped — i.e. proceeding past the timeout is safe."""
    canvas = _SelectCanvas()
    qtbot.addWidget(canvas)
    canvas._gen = 0
    canvas._pending = {5}

    recorded: dict = {}

    class _StuckPool:
        def waitForDone(self, msecs=-1):
            recorded["msecs"] = msecs
            return False  # simulate a render that outlives the wait

    canvas._pool = _StuckPool()

    drained = canvas._prepare_for_save()

    assert recorded["msecs"] == 5000, \
        "waitForDone must be called with a finite timeout, not the default -1"
    assert drained is False, "a timed-out join must be reported as such"
    # Safe to proceed anyway: the epoch/pending were already invalidated.
    assert canvas._gen == 1
    assert canvas._pending == set()


def test_render_pool_is_dedicated_not_global(qtbot):
    """MINOR 1 root cause: the viewer must use its OWN QThreadPool so the
    pre-save join can never block on unrelated jobs (e.g. an editor tab)
    sitting on the process-wide global pool."""
    from PySide6.QtCore import QThreadPool
    canvas = _SelectCanvas()
    qtbot.addWidget(canvas)
    assert canvas._pool is not QThreadPool.globalInstance(), \
        "viewer render pool must be dedicated, not the global instance"


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


def test_loading_new_doc_cancels_pending_search(qtbot, tmp_path):
    """MINOR 2: a debounced search armed against the previous document
    must be cancelled when a new document loads — otherwise the pending
    timer fires _do_search against the freshly loaded file (benign today
    thanks to the closed-doc guard, but incoherent: it would flash the old
    query's hits on the new doc)."""
    pdf1 = _make_pdf(tmp_path / "d1.pdf", text="Alpha")
    pdf2 = _make_pdf(tmp_path / "d2.pdf", text="Beta")
    panel = PdfViewerPanel()
    qtbot.addWidget(panel)
    panel.load(str(pdf1))
    _pump(qtbot)

    # Arm a debounced search against doc 1.
    panel._search_input.setText("Alpha")
    assert panel._search_debounce.isActive()
    assert panel._pending_search_query == "Alpha"

    # Spy AFTER arming so we can prove the stale search never fires.
    fired: list[str] = []
    orig = panel._do_search
    panel._do_search = lambda q: fired.append(q) or orig(q)

    # Swap in a new document.
    panel.load(str(pdf2))
    _pump(qtbot)

    assert not panel._search_debounce.isActive(), \
        "stale search still armed after loading a new document"
    assert panel._pending_search_query == "", "pending query not cleared on load"
    # Firing the (now-cleared) debounce must be a no-op — nothing scans doc 2.
    panel._run_pending_search()
    assert fired == [], f"stale search fired against the new document: {fired}"


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
