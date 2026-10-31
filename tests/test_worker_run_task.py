"""``run_task`` must not touch the progress dialog once the task ended.

The defect: ``QProgressDialog.setValue`` pumps the event loop, so the
queued ``finished`` can be delivered inside a ``setValue`` made by
``_drain``. ``_final`` closed the dialog and ran the handler, then the
outer ``_drain`` resumed with a stale value and ``setValue`` showed the
modal again, stuck at 85 % over the "PDF saved" flow until the user
pressed Cancel. Whether ``finished`` lands inside that pump depends on
when the worker gets there, so the same file can show it on one run and
not the next. Nothing here relies on timing:

* ``_start`` lets the worker queue every signal while the main thread
  is blocked on an event, so the queue content is known before anything
  is delivered;
* ``_SpyDialog`` is a real ``QProgressDialog`` that delivers the whole
  queue after every real ``setValue``, so the first delivered progress
  always nests the rest, whatever Qt does on its own: how much its pump
  delivers varies with the version and with whether it considers the
  dialog shown yet. The ``real_dialog`` tests use the plain class with
  the dialog already shown, which is the route production takes.

A real message box would block the run in its own event loop, out of
reach of every timeout here: see ``_no_real_box``.
"""

from __future__ import annotations

import atexit
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QEventLoop,
    QObject,
    Qt,
    QThread,
    QTimer,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QWidget,
)
from shiboken6 import delete, isValid

_unused_app = QApplication.instance() or QApplication([])

import pymupdf

from app.tools.compress import TabComprimir
from app.tools.convert import TabConverter
from app.tools.import_pdf import TabImport
from app.tools.nup import TabNUp
from app.tools.ocr import TabOCR
from app.tools.page_numbers import TabPageNumbers
from app.tools.watermark import TabMarcaDagua
from app.worker import TaskRunner, run_task

_DEADLINE_S = 20
# Longer than any wait a runner in this file does, all bound by _DEADLINE_S.
_STOP_MS = (_DEADLINE_S + 5) * 1000
_MAIN = threading.get_ident()
# Owners of a thread that would not stop. Never released: see _dispose.
_NEVER_DESTROYED: list = []


class _SpyDialog(QProgressDialog):
    """Real dialog that records what it is asked to do and in what order."""

    created: ClassVar[list] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log: list[tuple] = []
        self.threads: set[int] = set()
        _SpyDialog.created.append(self)

    def _note(self, *entry):
        self.log.append(entry)
        self.threads.add(threading.get_ident())

    def setValue(self, value):
        self._note("setValue", value)
        super().setValue(value)
        QCoreApplication.processEvents()
        # processEvents alone is not enough everywhere: with PySide6 6.11.0 on
        # Linux, below our floor, it stopped after the next progress, leaving
        # `finished` for later (measured; 6.11.2 on Linux and 6.11.3 on Windows
        # delivered it all). What a real pump delivers is not ours to rely on.
        QCoreApplication.sendPostedEvents()

    def setRange(self, low, high):
        self._note("setRange", low, high)
        super().setRange(low, high)

    def setLabelText(self, text):
        self._note("setLabelText", text)
        super().setLabelText(text)

    def reset(self):
        self._note("reset")
        super().reset()

    def showEvent(self, event):
        self._note("show")
        super().showEvent(event)


def _configure(dlg):
    """The set-up every production call site does before ``run_task``."""
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setValue(0)
    if isinstance(dlg, _SpyDialog):
        dlg.log.clear()
    return dlg


class _Scripted(TaskRunner):
    """Emits a fixed script, then returns or raises."""

    def __init__(self, script=(), result="ok", exc=None):
        super().__init__()
        self._script = script
        self._result = result
        self._exc = exc

    def do_work(self):
        for pct, label in self._script:
            self.progress.emit(pct, label)
        if self._exc is not None:
            raise self._exc
        return self._result


def _start(parent, runner, dlg, on_finished, on_error=None, after=None):
    """The real ``run_task``, returning once every signal is in the queue.

    The worker is held until run_task has connected, and the marker
    connects after it: Qt activates connections in order, so when the
    marker runs, on the worker thread, the queued relay is already posted.
    ``after`` runs at that point, still on the worker thread.
    """
    gate = threading.Event()
    queued = threading.Event()
    work = runner.do_work

    def _gated():
        assert gate.wait(_DEADLINE_S)
        return work()

    def _mark(_payload):
        if after is not None:
            after()
        queued.set()

    runner.do_work = _gated
    thread = run_task(parent, runner, dlg, on_finished, on_error)
    runner.finished.connect(_mark, Qt.ConnectionType.DirectConnection)
    runner.error.connect(_mark, Qt.ConnectionType.DirectConnection)
    gate.set()
    assert queued.wait(_DEADLINE_S), "worker did not finish its script"
    return thread


def _pump_until(condition, what: str):
    deadline = time.monotonic() + _DEADLINE_S
    while not condition():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents,
                                       20)


def _thread_gone(thread) -> bool:
    return not isValid(thread) or not thread.isRunning()


class _Handlers:
    """Records the callbacks, and the state the dialog and thread are in."""

    def __init__(self, dlg, modal_loop: bool = False):
        self.dlg = dlg
        self.thread = None
        self.modal_loop = modal_loop
        self.done: list = []
        self.errors: list = []
        self.dialog_visible_in_handler: list[bool] = []
        self.thread_running_in_handler: list[bool] = []
        self.log_size_in_handler: int | None = None
        self.threads: set[int] = set()

    def _note(self):
        self.threads.add(threading.get_ident())
        if isinstance(self.dlg, _SpyDialog):
            self.log_size_in_handler = len(self.dlg.log)
        self.dialog_visible_in_handler.append(self.dlg.isVisible())
        # None: delivered before the caller stored the thread, so not by the
        # main loop. The thread assertion has to get to report that.
        self.thread_running_in_handler.append(
            self.thread is not None and self.thread.isRunning())
        if self.modal_loop:
            # What QMessageBox.exec does inside a handler.
            loop = QEventLoop()
            QTimer.singleShot(0, loop.quit)
            loop.exec()

    def on_done(self, result):
        self._note()
        self.done.append(result)

    def on_error(self, exc):
        self._note()
        self.errors.append(exc)

    def dialog_calls_after_handler(self) -> list[tuple]:
        """What the dialog was told after run_task handed over to the
        handler: the close comes first, so this must stay empty."""
        return self.dlg.log[self.log_size_in_handler:]


def _drive(parent, runner, dlg, handlers=None, after=None) -> _Handlers:
    """Queue everything with the main thread blocked, then deliver it."""
    handlers = handlers or _Handlers(dlg)
    # The handlers read the thread, and only run once the loop is pumped.
    handlers.thread = _start(parent, runner, dlg, handlers.on_done,
                             handlers.on_error, after=after)
    _pump_until(lambda: _thread_gone(handlers.thread),
                "the worker thread to stop")
    return handlers


class _Stepped(TaskRunner):
    """Emits one batch per step, then waits to be told to go on."""

    def __init__(self, *steps):
        super().__init__()
        self._steps = steps
        self.reached = threading.Semaphore(0)
        self.go_on = threading.Semaphore(0)

    def do_work(self):
        for batch in self._steps:
            for pct, label in batch:
                self.progress.emit(pct, label)
            self.reached.release()
            # A raise, so the failure names its cause: `assert False` is cryptic.
            if not self.go_on.acquire(timeout=_DEADLINE_S):
                raise TimeoutError("the test never told the worker to go on")
        return "ok"

    def wait_for_step(self):
        """Blocks the main thread, so all the step emitted is in the queue."""
        assert self.reached.acquire(timeout=_DEADLINE_S), (
            "the worker did not reach its next step")

    def next_step(self):
        self.go_on.release()
        self.wait_for_step()


@contextmanager
def _stepped(parent, *steps):
    """Run a _Stepped under the spy dialog, and see it through to its end.

    The end is only checked if the body passed: a failure there is the one
    worth reading, so it just lets the worker out, for _dispose to stop it.
    """
    dlg = _spy(parent)
    runner = _Stepped(*steps)
    go_on = runner.go_on
    seen = _Handlers(dlg)
    seen.thread = run_task(parent, runner, dlg, seen.on_done, seen.on_error)
    try:
        yield dlg, runner
    except BaseException:
        go_on.release(len(steps))
        raise
    go_on.release()
    _pump_until(lambda: _thread_gone(seen.thread), "the worker thread to stop")
    assert seen.done == ["ok"], f"handler got {seen.done}, errors {seen.errors}"
    assert not dlg.isVisible()


def _relays(owner) -> list:
    """Found by name: run_task's class is local to the call."""
    return [child for child in owner.findChildren(QObject)
            if type(child).__name__ == "_Dispatcher"]


def _dispose(*owners):
    """Delete ``owners``, but none with a thread of its own still running.

    A failure can leave the thread alive: an assertion before it stopped,
    or a handler that raised, which skips the ``thread.quit()`` after it.
    Destroying a running QThread aborts the process ("QThread: Destroyed
    while thread is still running"), and the pytest summary goes with it.
    So: ask them to stop, and an owner whose thread still refuses is kept
    alive for good, and reported as the failure it is. PySide destroys
    what it owns at interpreter exit, which would abort after the summary
    (measured), so that run also leaves before PySide gets there.
    """
    stuck = []
    for owner in owners:
        threads = owner.findChildren(QThread)
        for thread in threads:
            thread.quit()
        stopped = [thread.wait(_STOP_MS) for thread in threads]
        if all(stopped):
            owner.deleteLater()
        else:
            _NEVER_DESTROYED.append(owner)
            atexit.register(os._exit, 1)
            stuck.append(owner)
            # A worker that ends later would deliver its result into an
            # innocent test, or another module, where no sweeper closes the box.
            for relay in _relays(owner):
                relay.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not stuck, f"worker thread did not stop, owned by {stuck!r}"


@pytest.fixture(autouse=True)
def _no_real_box():
    """Close any real dialog and fail the test that opened it.

    An error before the task starts opens a real box inside ``page._run``,
    and its event loop never gives control back to ``_pump_until``: without
    this the run blocks until something kills it, with no summary. No test
    here wants a real one: the tools' "done" box is patched in ``tools``,
    the only button clicked is the progress dialog's Cancel, and
    ``modal_loop`` spins a bare QEventLoop. The progress dialog itself is
    what is under test, so it is left alone.

    Being autouse it wraps ``parent`` and ``tools``, so it also covers their
    teardown. The timer has no parent for that reason: nothing that outlives
    the test can own it, and this frame holds it until after ``stop``.
    """
    opened: list[str] = []

    def _sweep():
        for window in QApplication.topLevelWidgets():
            if (isinstance(window, QDialog) and window.isVisible()
                    and not isinstance(window, QProgressDialog)):
                text = window.text() if isinstance(window, QMessageBox) else ""
                opened.append(f"{type(window).__name__}: {text[:60]}")
                window.done(0)

    timer = QTimer()
    timer.timeout.connect(_sweep)
    timer.start(100)
    yield
    timer.stop()
    assert not opened, f"a real dialog opened: {opened}"


@pytest.fixture
def parent():
    _SpyDialog.created.clear()
    widget = QWidget()
    widget.show()
    yield widget
    _dispose(widget)


def _spy(parent, maximum=100) -> _SpyDialog:
    return _configure(_SpyDialog("start", "Cancel", 0, maximum, parent))


def _real_dialog_shown(parent, maximum=100) -> QProgressDialog:
    dlg = _configure(QProgressDialog("start", "Cancel", 0, maximum, parent))
    _pump_until(dlg.isVisible, "the dialog to appear")
    return dlg


# -- the reported defect -----------------------------------------------------


def test_stale_progress_does_not_reopen_the_dialog(parent):
    """The measured sequence: 65, then 100 nested, then 85 showed it again."""
    dlg = _spy(parent)
    runner = _Scripted([(65, "pass B"), (70, "saving"), (85, "pass C")])

    seen = _drive(parent, runner, dlg)

    assert seen.done == ["ok"] and seen.errors == []
    assert not dlg.isVisible()
    assert seen.dialog_calls_after_handler() == []
    assert ("setValue", 85) not in dlg.log
    assert seen.threads == {_MAIN} and dlg.threads == {_MAIN}


def test_stale_progress_with_a_modal_handler(parent):
    """A handler spinning its own loop, as the "PDF saved" box does."""
    dlg = _spy(parent)
    runner = _Scripted([(65, "a"), (85, "b")])

    seen = _drive(parent, runner, dlg, _Handlers(dlg, modal_loop=True))

    assert seen.done == ["ok"]
    assert not dlg.isVisible()
    assert seen.dialog_calls_after_handler() == []


def test_real_dialog_nests_and_stays_closed(parent):
    """No spy: the plain class, shown, pumps the loop by itself."""
    dlg = _real_dialog_shown(parent)
    runner = _Scripted([(65, "a"), (70, "b"), (85, "pass C")])

    seen = _drive(parent, runner, dlg, _Handlers(dlg, modal_loop=True))

    assert seen.done == ["ok"]
    assert seen.dialog_visible_in_handler == [False]
    assert not dlg.isVisible()
    assert dlg.value() != 85
    assert QApplication.activeModalWidget() is None


def test_dialog_is_closed_when_the_last_progress_was_the_maximum(parent):
    """Import reports n of n: the nested close finds the value already there.

    ``setValue(maximum)`` returns early when the bar holds that value,
    so a close built on it left the dialog on screen behind the handler's
    message box.
    """
    dlg = _real_dialog_shown(parent, maximum=3)

    seen = _drive(parent, _Scripted([(3, "3/3")]), dlg)

    assert seen.dialog_visible_in_handler == [False]
    assert not dlg.isVisible()


def test_pending_busy_sentinel_is_dropped_too(parent):
    """A pending -1 would have flipped the closed dialog to a busy bar."""
    dlg = _spy(parent)
    runner = _Scripted([(65, "a"), (-1, "busy")])

    seen = _drive(parent, runner, dlg)

    assert seen.done == ["ok"]
    assert dlg.maximum() == 100
    assert not any(entry[0] == "setRange" for entry in dlg.log)
    assert seen.dialog_calls_after_handler() == []


def test_progress_emitted_after_finished_is_ignored(parent):
    """Signals are FIFO per sender, so this needs a misbehaving subclass;
    the dialog must survive it anyway."""
    dlg = _spy(parent)
    runner = _Scripted()
    late = runner.progress

    seen = _drive(parent, runner, dlg,
                  after=lambda: late.emit(50, "after the end"))
    QCoreApplication.processEvents()

    assert seen.done == ["ok"]
    assert ("setValue", 50) not in dlg.log
    assert not dlg.isVisible()


def test_close_precedes_the_handler_which_precedes_thread_quit(parent):
    """The order callers rely on: the box opens over a closed dialog, and
    the thread outlives the handler."""
    dlg = _spy(parent)
    runner = _Scripted([(65, "a"), (85, "b")])

    seen = _drive(parent, runner, dlg)

    assert seen.dialog_visible_in_handler == [False]
    assert seen.thread_running_in_handler == [True]


# -- progress while the task runs --------------------------------------------


def test_value_coalesced_during_set_value_is_shown(parent):
    """The second value lands nested in the first setValue: only the outer
    _drain is left to show it, and there is no third signal to retry."""
    with _stepped(parent, [(10, "first"), (20, "second")]) as (dlg, runner):
        runner.wait_for_step()

        _pump_until(lambda: ("setValue", 20) in dlg.log, "the second progress")

        assert ("setLabelText", "second") in dlg.log


def test_progress_after_a_finished_drain_is_shown(parent):
    """A drain that ended must leave the way open for the next one."""
    with _stepped(parent, [(10, "a")], [(50, "b")]) as (dlg, runner):
        runner.wait_for_step()
        _pump_until(lambda: ("setValue", 10) in dlg.log, "the first progress")

        runner.next_step()

        _pump_until(lambda: ("setValue", 50) in dlg.log, "the later progress")


def test_busy_sentinel_then_progress_restores_the_range(parent):
    with _stepped(parent, [(-1, "busy")], [(50, "b")]) as (dlg, runner):
        runner.wait_for_step()
        _pump_until(lambda: dlg.maximum() == 0, "the busy bar")

        runner.next_step()

        _pump_until(lambda: dlg.maximum() == 100 and dlg.value() == 50,
                    "the range restored")


# -- cancel ------------------------------------------------------------------


class _CancelledMidway(TaskRunner):
    """Reports, then waits for the Cancel click, then reports once more.

    Tools check ``is_cancelled`` only at their next checkpoint, so a
    progress emitted after the click is a real sequence.
    """

    def __init__(self):
        super().__init__()
        self.saw_cancel = threading.Event()

    def do_work(self):
        self.progress.emit(10, "first")
        deadline = time.monotonic() + _DEADLINE_S
        while not self.is_cancelled():
            assert time.monotonic() < deadline
            QThread.msleep(1)
        self.saw_cancel.set()
        self.progress.emit(50, "after the click")


def test_cancel_midway_closes_and_reports_none(parent):
    dlg = _spy(parent)
    runner = _CancelledMidway()
    saw_cancel = runner.saw_cancel
    seen = _Handlers(dlg)
    seen.thread = run_task(parent, runner, dlg, seen.on_done, seen.on_error)

    _pump_until(lambda: ("setValue", 10) in dlg.log, "the first progress")
    # First: routed to the emitter's thread, the rest fails for other reasons.
    assert dlg.threads == {_MAIN}
    assert dlg.isVisible()
    dlg.log.clear()
    dlg.findChild(QPushButton).click()
    assert not dlg.isVisible()

    assert saw_cancel.wait(_DEADLINE_S), "Cancel did not reach the runner"
    _pump_until(lambda: _thread_gone(seen.thread), "the worker thread to stop")

    assert seen.threads == {_MAIN} and dlg.threads == {_MAIN}
    assert seen.done == [None] and seen.errors == []
    assert ("show",) not in dlg.log, f"Cancel was undone: {dlg.log!r}"
    assert ("setValue", 50) not in dlg.log
    assert not dlg.isVisible()


# -- error -------------------------------------------------------------------


def test_error_midway_reaches_on_error_with_the_dialog_closed(parent, capsys):
    dlg = _spy(parent)
    boom = ValueError("boom")
    runner = _Scripted([(65, "a"), (85, "b")], exc=boom)

    seen = _drive(parent, runner, dlg)

    # First: routed to the emitter's thread, the rest fails for other reasons.
    assert seen.threads == {_MAIN} and dlg.threads == {_MAIN}
    assert seen.errors == [boom] and seen.done == []
    assert seen.dialog_visible_in_handler == [False]
    assert seen.thread_running_in_handler == [True]
    assert not dlg.isVisible()
    assert seen.dialog_calls_after_handler() == []
    assert ("setValue", 85) not in dlg.log
    assert "boom" in capsys.readouterr().err


def test_error_without_on_error_still_closes_and_stops(parent, capsys):
    dlg = _spy(parent)
    runner = _Scripted([(65, "a")], exc=ValueError("boom"))

    thread = _start(parent, runner, dlg, lambda r: None)
    _pump_until(lambda: _thread_gone(thread), "the worker thread to stop")

    assert not dlg.isVisible()
    capsys.readouterr()


# -- dialog destroyed --------------------------------------------------------


class _HeldAfterFirstProgress(TaskRunner):
    """Reports, waits for ``release``, reports again, then ends."""

    def __init__(self, exc=None):
        super().__init__()
        self.release = threading.Event()
        self._exc = exc

    def do_work(self):
        self.progress.emit(10, "first")
        assert self.release.wait(_DEADLINE_S)
        self.progress.emit(50, "to a dead dialog")
        if self._exc is not None:
            raise self._exc
        return "ok"


@pytest.mark.parametrize("exc", [None, ValueError("boom")],
                         ids=["finished", "error"])
def test_dialog_destroyed_midway_still_runs_handler_and_stops(parent, exc,
                                                              monkeypatch):
    """The dialog's C++ object dies while the worker runs: every call on the
    wrapper now raises RuntimeError, in ``_drain`` for the progress and in
    ``_final`` for the close. An exception escaping a slot does not fail
    anything by itself, so it is caught at the hook PySide reports it to.
    """
    raised: list[BaseException] = []
    monkeypatch.setattr(sys, "excepthook", lambda _t, e, _tb: raised.append(e))
    dlg = _real_dialog_shown(parent)
    runner = _HeldAfterFirstProgress(exc)
    # Until parent's teardown has waited for the thread. isRunning() is false
    # before the worker deletes its runner, and with the dialog gone so is the
    # reference held by run_task's lambda: a wrapper released by this frame
    # probably deleted the object a second time, and it segfaulted 6 runs in
    # 10 (Linux).
    parent.keep_runner_alive = runner
    release = runner.release
    results: list = []
    thread = run_task(parent, runner, dlg, results.append, results.append)

    _pump_until(lambda: dlg.value() == 10, "the first progress")
    delete(dlg)
    assert not isValid(dlg)
    release.set()
    _pump_until(lambda: raised or _thread_gone(thread),
                "the worker thread to stop")

    assert raised == []
    assert results == [exc if exc is not None else "ok"]
    assert _thread_gone(thread)


# -- no progress -------------------------------------------------------------


def test_task_without_progress_closes(parent):
    dlg = _spy(parent)

    seen = _drive(parent, _Scripted(), dlg)
    # The set-up armed Qt's show-now timer; it must not outlive the close.
    QCoreApplication.processEvents()

    assert seen.done == ["ok"]
    assert not dlg.isVisible()
    assert seen.dialog_calls_after_handler() == []


def test_task_without_progress_starting_in_busy_mode_closes(parent):
    """setValue(max) is a no-op with range (0, 0); the close must not be."""
    dlg = _configure(_SpyDialog("start", "Cancel", 0, 0, parent))

    seen = _drive(parent, _Scripted([(-1, "busy")]), dlg)

    assert seen.done == ["ok"]
    assert not dlg.isVisible()


# -- two tasks ---------------------------------------------------------------


def test_second_task_is_not_affected_by_the_first(parent):
    """The "ended" state is per run_task call: a shared one would silence
    the second task's progress."""
    first = _spy(parent)
    seen_first = _drive(parent, _Scripted([(65, "a"), (85, "b")]), first)
    log_first = list(first.log)

    second = _spy(parent)
    seen_second = _drive(parent, _Scripted([(30, "c"), (60, "d")]), second)

    assert seen_first.done == ["ok"] and seen_second.done == ["ok"]
    assert ("setValue", 30) in second.log
    assert first.log == log_first, "the second task touched the first dialog"
    assert not first.isVisible() and not second.isVisible()
    assert seen_second.dialog_calls_after_handler() == []


def test_a_runner_instance_cannot_be_reused(parent):
    """Why "two tasks on the same runner" means two instances.

    ``thread.finished`` deletes the runner, so a second ``run_task`` on
    the same instance has no C++ object to move. Pinned because every
    guard above assumes one run per ``run_task`` state.
    """
    dlg = _spy(parent)
    runner = _Scripted([(50, "a")])

    _drive(parent, runner, dlg)
    _pump_until(lambda: not isValid(runner), "the runner to be deleted")

    with pytest.raises(RuntimeError):
        run_task(parent, runner, _spy(parent), lambda r: None)


def test_thread_object_is_deleted_after_it_stops(parent):
    seen = _drive(parent, _Scripted(), _spy(parent))

    _pump_until(lambda: not isValid(seen.thread), "the thread to be deleted")


def test_dispose_finds_the_relay_it_has_to_drop(parent):
    """Renamed, the relay would silently survive _dispose's search."""
    seen = _drive(parent, _Scripted(), _spy(parent))

    assert seen.done == ["ok"]
    names = [type(child).__name__ for child in parent.findChildren(QObject)]
    assert _relays(parent), f"no relay among {names}"


# -- the real tools ----------------------------------------------------------


@pytest.fixture
def tools(monkeypatch, parent):
    """Real pages through their real ``_run``, with the spy dialog.

    ``run_task`` is wrapped only to hold delivery until the queue is full.
    The pages reach it, and their dialog class, through two kinds of
    import, patched separately: Compress and OCR at module level,
    ``_run_background`` lazily.
    """
    monkeypatch.setattr("app.worker.run_task", _start)
    monkeypatch.setattr("app.tools.compress.run_task", _start)
    monkeypatch.setattr("app.tools.ocr.run_task", _start)
    monkeypatch.setattr("PySide6.QtWidgets.QProgressDialog", _SpyDialog)
    monkeypatch.setattr("app.tools.compress.QProgressDialog", _SpyDialog)
    infos: list = []
    marks: list = []

    def _box(*a, **k):
        infos.append(a[1:3])
        marks.append(len(_SpyDialog.created[-1].log))

    monkeypatch.setattr(QMessageBox, "information", staticmethod(_box))
    errors: list = []
    monkeypatch.setattr("app.utils.show_error",
                        lambda *a, **k: errors.append(a[1:]))
    monkeypatch.setattr("app.tools.compress.show_error",
                        lambda *a, **k: errors.append(a[1:]))
    monkeypatch.setattr("app.tools.ocr.show_error",
                        lambda *a, **k: errors.append(a[1:]))
    pages: list = []

    def run(page):
        pages.append(page)
        before = len(_SpyDialog.created)
        page._run()
        assert len(_SpyDialog.created) == before + 1, "no dialog was opened"
        dlg = _SpyDialog.created[-1]
        thread = (page._runner_thread
                  if isinstance(page, (TabComprimir, TabOCR))
                  else page._bg_thread)
        _pump_until(lambda: _thread_gone(thread), "the tool's thread to stop")
        assert errors == []
        assert not dlg.isVisible()
        assert marks, "the tool never reported its result"
        assert dlg.log[marks[-1]:] == [], "dialog touched after the handler"
        assert page.action_btn.isEnabled()
        return dlg, infos

    yield run
    _dispose(*pages)


def _pdf(path: Path, pages: int = 4) -> str:
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 100), f"Hello page {i + 1}")
    doc.save(path)
    doc.close()
    return str(path)


def test_compress_page_stays_closed_and_runs_twice(tools, tmp_path,
                                                   monkeypatch):
    def fake_compress(src, dst, level, progress_fn=None, password=None):
        for stage in ("passA", "passB_setup", "passB_save", "passC"):
            assert progress_fn(stage, 0, 0) is True
        Path(dst).write_bytes(b"%PDF-")
        return 1000, 500

    monkeypatch.setattr("app.tools.compress._compress_pdf", fake_compress)
    page = TabComprimir(lambda *_: None)
    page.drop_in.set_path(_pdf(tmp_path / "relatório final.pdf"))

    page.drop_out.set_path(str(tmp_path / "um.pdf"))
    dlg1, infos = tools(page)
    page.drop_out.set_path(str(tmp_path / "dois.pdf"))
    dlg2, infos = tools(page)

    assert len(infos) == 2
    assert dlg1 is not dlg2
    # passC is the 85 of the report; passA delivers first and nests it.
    assert ("setValue", 85) not in dlg1.log
    assert ("setValue", 85) not in dlg2.log


@pytest.mark.parametrize("fmt, ext", [(3, ".txt"), (6, ".html")],
                         ids=["txt", "html"])
def test_converter_page_stays_closed(tools, tmp_path, fmt, ext):
    src = _pdf(tmp_path / "entrada.pdf")
    page = TabConverter(lambda *_: None)
    page.cmb_format.setCurrentIndex(fmt)
    page.drop_in.set_path(src)
    page._drop_file.set_path(str(tmp_path / f"saida{ext}"))

    _dlg, infos = tools(page)

    assert len(infos) == 1
    assert (tmp_path / f"saida{ext}").is_file()


def test_converter_images_page_stays_closed(tools, tmp_path):
    src = _pdf(tmp_path / "entrada.pdf")
    page = TabConverter(lambda *_: None)
    page.cmb_format.setCurrentIndex(0)
    page.drop_in.set_path(src)
    out = tmp_path / "imagens"
    out.mkdir()
    page._drop_folder.set_path(str(out))

    _dlg, infos = tools(page)

    assert len(infos) == 1
    assert len(list(out.glob("*.png"))) == 4


def test_import_page_stays_closed(tools, tmp_path):
    """Import is the n-of-n reporter: 1, 2, 3 of 3 with a nested close."""
    page = TabImport(lambda *_: None)
    page.cmb_type.setCurrentIndex(0)
    for i in range(3):
        src = tmp_path / f"nota {i}.txt"
        src.write_text(f"linha {i}\n", encoding="utf-8")
        page._file_list.addItem(str(src))
    out = tmp_path / "saida.pdf"
    page.drop_out.set_path(str(out))

    _dlg, infos = tools(page)

    assert len(infos) == 1
    assert out.is_file()


def test_nup_page_stays_closed(tools, tmp_path):
    page = TabNUp(lambda *_: None)
    page.drop_in.set_path(_pdf(tmp_path / "entrada.pdf"))
    out = tmp_path / "saida.pdf"
    page.drop_out.set_path(str(out))

    _dlg, infos = tools(page)

    assert len(infos) == 1
    assert out.is_file()


def test_page_numbers_page_stays_closed(tools, tmp_path):
    page = TabPageNumbers(lambda *_: None)
    page.drop_in.set_path(_pdf(tmp_path / "entrada.pdf"))
    out = tmp_path / "saida.pdf"
    page.drop_out.set_path(str(out))

    _dlg, infos = tools(page)

    assert len(infos) == 1
    assert out.is_file()


def test_watermark_page_stays_closed(tools, tmp_path):
    page = TabMarcaDagua(lambda *_: None)
    page.drop_in.set_path(_pdf(tmp_path / "entrada.pdf"))
    page.drop_wm.set_path(_pdf(tmp_path / "selo.pdf", pages=1))
    out = tmp_path / "saida.pdf"
    page.drop_out.set_path(str(out))

    _dlg, infos = tools(page)

    assert len(infos) == 1
    assert out.is_file()


def test_ocr_page_stays_closed(tools, tmp_path, monkeypatch):
    """Tesseract is faked: what is under test is the dialog, not the OCR."""
    monkeypatch.setitem(sys.modules, "pytesseract", SimpleNamespace(
        image_to_string=lambda img, lang=None: "texto"))
    monkeypatch.setattr("app.tools.ocr.QProgressDialog", _SpyDialog)
    page = TabOCR(lambda *_: None)
    monkeypatch.setattr(page, "_ensure_tesseract", lambda: "tesseract")
    monkeypatch.setattr(page, "_selected_lang_code", lambda: "eng")
    page.cmb_lang.addItem("English", "eng")
    page.cmb_fmt.setCurrentIndex(1)
    page.drop_in.set_path(_pdf(tmp_path / "entrada.pdf"))
    out = tmp_path / "saida.txt"
    page.drop_out.set_path(str(out))

    _dlg, infos = tools(page)

    assert len(infos) == 1
    assert out.read_text(encoding="utf-8").count("texto") == 4
