"""PDFApps — generic background-task helper.

Tools whose action runs for more than a fraction of a second
(compress, ocr, convert, import) used to call QApplication.processEvents()
inside the work loop and block the event queue between iterations. The
UI stuttered, the cancel button only responded between pages, and a
hung subprocess could freeze the whole app.

This module provides:
  * TaskRunner — a QObject base class with progress / finished / error
    signals and a cooperative cancel flag.
  * run_task() — wires a runner to a QThread and a QProgressDialog with
    sane cleanup so each tool needs only the do_work() body.
"""

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from app.utils import CancelledError  # re-exported for convenience  # noqa: F401


class TaskRunner(QObject):
    """Base class for a unit of work that runs in a worker thread.

    Subclasses override `do_work()` and may emit `self.progress` to
    update the UI. They poll `self.is_cancelled()` (or check the
    progress callback's False return value) to abort cooperatively.

    Signals:
        progress(int pct, str label)
            Emitted from the worker thread; routed to the progress
            dialog by `run_task`. `pct` is 0–100.
        finished(object result)
            Emitted on successful completion, OR with `None` when the
            user cancelled. The handler must distinguish.
        error(str message)
            Emitted on any uncaught exception inside `do_work()`.
    """

    progress = Signal(int, str)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self._cancelled = False

    def cancel(self) -> None:
        # NOT a @Slot: cross-thread signal→slot would queue this on the
        # worker thread, which is busy inside do_work() and would never
        # process the queue. We need cancel to mutate the flag *now*.
        # Python bool assignment is atomic under the GIL, so this is
        # safe from any thread.
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    @Slot()
    def run(self) -> None:
        try:
            result = self.do_work()
        except CancelledError:
            self.finished.emit(None)
            return
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))
            return
        self.finished.emit(result)

    def do_work(self):
        raise NotImplementedError


def run_task(parent, runner: TaskRunner, progress_dlg,
             on_finished, on_error=None):
    """Run a TaskRunner in a QThread bound to a QProgressDialog.

    - runner.progress  → progress_dlg.setValue + setLabelText
    - progress_dlg.canceled → runner.cancel
    - runner.finished  → on_finished(result), then quit thread
    - runner.error     → on_error(msg) (default: nothing), then quit
    - thread.finished  → deleteLater for both thread and runner

    Returns the QThread so the caller can keep a reference (otherwise
    Python may garbage-collect the wrapper before Qt hands the worker
    back to the main thread).
    """
    thread = QThread(parent)
    runner.moveToThread(thread)

    # QProgressDialog.setValue() calls QApplication.processEvents() internally
    # to keep the cancel button responsive. Combined with rapid queued
    # progress signals, that drains more _on_progress slots while we're
    # already painting the dialog — causing recursive repaints, "endPaint
    # with active painter" warnings, and crashes. We guard against
    # re-entrancy and coalesce pending values: an inner call just stores
    # the latest pct/label; the outermost call drains them in a loop.
    _state = {"in": False, "pct": None, "label": None}

    def _drain():
        _state["in"] = True
        try:
            while _state["pct"] is not None or _state["label"]:
                p = _state["pct"]; l = _state["label"]
                _state["pct"] = None; _state["label"] = None
                try:
                    if p is not None:
                        # Sentinel: pct = -1 → indeterminate / busy bar
                        # (used by tools that wrap a single blocking
                        # call with no progress callback). Any non-
                        # negative pct restores the 0–100 range.
                        if p < 0:
                            if progress_dlg.maximum() != 0:
                                progress_dlg.setRange(0, 0)
                        else:
                            if progress_dlg.maximum() == 0:
                                progress_dlg.setRange(0, 100)
                            progress_dlg.setValue(int(p))
                    if l:
                        progress_dlg.setLabelText(l)
                except RuntimeError:
                    # Dialog already destroyed (page closed mid-task,
                    # window quit during a queued progress signal).
                    # Drop any further pending updates.
                    _state["pct"] = None; _state["label"] = None
                    return
        finally:
            _state["in"] = False

    def _on_progress(pct, label):
        _state["pct"] = pct
        _state["label"] = label
        if _state["in"]:
            return
        _drain()

    # Force QueuedConnection on cross-thread signals whose receivers are
    # plain Python callables (closures / lambdas). PySide6 cannot infer a
    # callable's thread affinity, so it falls back to DirectConnection —
    # which would run _on_progress on the worker thread and call
    # progress_dlg.setValue() across threads, deadlocking against the
    # main thread's GUI mutex. Queued dispatch posts the call onto the
    # main thread's event loop, where the dialog actually lives.
    runner.progress.connect(_on_progress, Qt.ConnectionType.QueuedConnection)
    # Wrap runner.cancel in a lambda so the call dispatches as a plain
    # Python invocation on the dialog's (main) thread — not as a queued
    # cross-thread Qt slot call. With a bare bound method, PySide6
    # routes the invocation through QMetaObject.invokeMethod which
    # respects the runner's thread affinity and the call ends up
    # queued on the worker thread, where do_work() never gets to
    # process it.
    progress_dlg.canceled.connect(lambda: runner.cancel())

    def _final(handler, arg):
        try:
            # If the dialog is in busy/indeterminate mode (max==0),
            # setValue(max) is a no-op and the dialog won't auto-hide.
            # Restore the 0–100 range first, then snap to max.
            if progress_dlg.maximum() == 0:
                progress_dlg.setRange(0, 100)
            progress_dlg.setValue(progress_dlg.maximum())
        except RuntimeError:
            pass  # dialog destroyed (e.g. user closed window)
        if handler is not None:
            handler(arg)
        thread.quit()

    runner.finished.connect(lambda r: _final(on_finished, r),
                            Qt.ConnectionType.QueuedConnection)
    runner.error.connect(lambda e: _final(on_error, e),
                         Qt.ConnectionType.QueuedConnection)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(runner.deleteLater)
    thread.started.connect(runner.run)
    thread.start()
    return thread
