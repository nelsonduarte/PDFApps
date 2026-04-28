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

from PySide6.QtCore import QObject, QThread, Signal, Slot

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

    @Slot()
    def cancel(self) -> None:
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

    def _on_progress(pct, label):
        if pct is not None:
            progress_dlg.setValue(int(pct))
        if label:
            progress_dlg.setLabelText(label)

    runner.progress.connect(_on_progress)
    progress_dlg.canceled.connect(runner.cancel)

    def _final(handler, arg):
        try:
            progress_dlg.setValue(progress_dlg.maximum())
        except RuntimeError:
            pass  # dialog destroyed (e.g. user closed window)
        if handler is not None:
            handler(arg)
        thread.quit()

    runner.finished.connect(lambda r: _final(on_finished, r))
    runner.error.connect(lambda e: _final(on_error, e))
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(runner.deleteLater)
    thread.started.connect(runner.run)
    thread.start()
    return thread
