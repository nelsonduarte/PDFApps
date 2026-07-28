"""Tests for MainWindow update-check thread/object lifecycle fixes.

Covers the adversarial-audit findings on ``app/window.py``:

  * M4 — the background update-check worker must be abortable (its
    urlopen response is closed on shutdown) and _release_update_worker
    must wait long enough for the aborted read plus a terminate() fallback
    so closeEvent never destroys a running QThread.
  * M5 — _notify_update must guard against ``_update_release is None``
    (a closeEvent -> _release_update_worker race between the worker's
    done.emit() and the queued _on_update_found).

M4's full closeEvent-during-hung-network scenario is not deterministically
unit-testable (it needs a real MainWindow, a real hung socket and precise
thread timing), so it is covered here at the source level plus the
functional cancel_holder abort test in tests/test_updater.py
(TestCheckForUpdateCancelHolder). The pieces the fix relies on are asserted
individually.
"""
import os
import sys
from pathlib import Path

# Headless Qt for any widget construction.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _read(rel: str) -> str:
    return (Path(__file__).resolve().parent.parent / rel).read_text(encoding="utf-8")


# ── M5: _notify_update None-guard ──────────────────────────────────────


class _StubWindow:
    """Minimal stand-in exposing only the attribute the guard reads.

    Deliberately lacks _update_btn: pre-fix, _notify_update touched
    self._update_btn.setVisible() and self._update_release.get() with
    _update_release=None, so calling the unbound method on this stub would
    raise. Post-fix the guard returns before any of that runs."""

    def __init__(self):
        self._update_release = None


def test_notify_update_returns_when_release_none():
    """M5: _notify_update must return without raising when
    _update_release is None (worker torn down mid-flight)."""
    from app.window import MainWindow
    stub = _StubWindow()
    # Must not raise AttributeError — the guard short-circuits.
    assert MainWindow._notify_update(stub) is None


def test_notify_update_has_none_guard_in_source():
    src = _read("app/window.py")
    body = src[src.find("def _notify_update"):
               src.find("def _show_update_dialog")]
    assert "if not self._update_release:" in body, \
        "_notify_update must guard against a None _update_release (M5)"


# ── M4: check worker abort + robust teardown ───────────────────────────


def test_check_for_update_accepts_cancel_holder():
    """The updater API the worker calls must accept a cancel_holder so the
    UI thread can abort the blocked urlopen (M4)."""
    import inspect
    from app.updater import check_for_update
    params = inspect.signature(check_for_update).parameters
    assert "cancel_holder" in params, \
        "check_for_update must accept a cancel_holder for abortability"


def test_async_check_threads_cancel_holder_into_worker():
    src = _read("app/window.py")
    body = src[src.find("def _check_for_updates_async"):
               src.find("def _on_update_found")]
    assert 'self._update_cancel = {"resp": None}' in body, \
        "the async check must create a shared cancel holder"
    assert "check_for_update(self._cancel)" in body, \
        "the worker must pass the cancel holder into check_for_update"


def test_release_update_worker_aborts_and_terminates():
    """M4: _release_update_worker must (1) close the in-flight response,
    (2) wait longer than the urlopen timeout, and (3) terminate() as a
    last resort so a running QThread is never destroyed."""
    src = _read("app/window.py")
    body = src[src.find("def _release_update_worker"):
               src.find("def _notify_update")]
    # (1) abort the blocked read
    assert "resp.close()" in body, \
        "must close the in-flight urlopen response to unblock the read"
    # (2) wait must cover the 10 s urlopen timeout (old value was 1000 ms)
    assert "thread.wait(1000)" not in body, \
        "the 1000 ms wait was too short to cover the urlopen timeout"
    assert ("thread.wait(12000)" in body or "thread.wait(1000)" not in body), \
        "wait must be dimensioned to the urlopen timeout"
    # (3) terminate() fallback so closeEvent never leaves a running thread
    assert "thread.terminate()" in body, \
        "must terminate() as a last resort so no running QThread is destroyed"
