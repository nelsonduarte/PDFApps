"""PDFApps – UpdateController: the MainWindow auto-update subsystem.

Extracted verbatim from ``app/window.py`` (R4 refactor). Owns the
background update-check worker (a ``QObject`` moved onto a ``QThread``),
the notify/decision step and the update dialog. Behaviour, threading and
worker lifecycle are unchanged — only the code's home moved.

Threading note (preserved deliberately): the controller is a ``QObject``
whose parent is the main window, so it keeps main-thread affinity. The
worker's ``done`` signal therefore delivers ``_on_update_found`` back on
the main thread via Qt's automatic queued connection — exactly as it did
when these were ``MainWindow`` methods. No lambda crosses the thread
boundary (a bound QObject method is used), which is the Py3.14-safe
pattern this project relies on.
"""

import contextlib
import os

from PySide6.QtCore import QObject

from app.i18n import t


class UpdateController(QObject):
    """Encapsulates the MainWindow auto-update check, worker and dialog.

    Composed by ``MainWindow`` as ``self._update_controller``. The window
    still owns the toolbar update button (part of its layout) and passes
    it in so the controller can reveal it when an update is found and wire
    its click to :meth:`show_update_dialog`.
    """

    def __init__(self, window, update_button):
        # Parent to the window → main-thread affinity + lifetime tied to
        # the window. This is what makes the worker's cross-thread ``done``
        # signal resume on the main thread.
        super().__init__(window)
        self._window = window
        self._update_btn = update_button
        self._update_release = None
        self._update_thread = None
        self._update_worker = None
        # Holds the in-flight urlopen response of the background update
        # check so release_worker can abort a blocked network read from
        # closeEvent instead of waiting out the socket timeout.
        self._update_cancel = None

    def check_async(self):
        # Skip auto-update inside Flatpak/Snap — the host package
        # manager handles updates. MSIX/Microsoft Store installs are
        # short-circuited inside check_for_update() itself (the Store
        # updates packaged apps automatically), so they never reach the
        # NSIS download path.
        if os.environ.get("FLATPAK_ID") or os.environ.get("SNAP"):
            return
        # Pre-import the updater module on the main thread BEFORE the
        # worker thread starts. The worker would otherwise lazy-import
        # `app.updater`, which transitively pulls in `urllib.request`
        # → `http.client` → `ssl`. On Python 3.14, importing those
        # heavy modules from a non-main thread while the main thread
        # is still busy creating Qt widgets races against each other
        # (CPython's import machinery + Qt's widget construction +
        # garbage collection on the worker side) and produces a
        # Windows access-violation crash. Doing the import here keeps
        # all that import work on the main thread; the worker only
        # calls the already-imported function.
        from app.updater import check_for_update
        from PySide6.QtCore import QThread, QObject, Signal as _Sig

        # Shared holder so the main thread can close the worker's urlopen
        # response and unblock its network read on shutdown (M4).
        self._update_cancel = {"resp": None}

        class _Worker(QObject):
            done = _Sig()
            def __init__(self, cancel_holder):
                super().__init__()
                self.release = None
                self._cancel = cancel_holder
            def run(self):
                self.release = check_for_update(self._cancel)
                if self.release:
                    self.done.emit()
                self.thread().quit()

        self._update_thread = QThread()
        self._update_worker = _Worker(self._update_cancel)
        self._update_worker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.done.connect(self._on_update_found)
        self._update_thread.finished.connect(self._update_thread.deleteLater)
        self._update_thread.start()

    def _on_update_found(self):
        if self._update_worker is not None:
            self._update_release = self._update_worker.release
        self._notify_update()
        # R8-H2: the worker QObject lived for the lifetime of the
        # application before this — only the QThread was scheduled for
        # deleteLater. Drop the worker after the check completes so the
        # closure (and its captured release dict) is freed.
        self.release_worker()

    def release_worker(self):
        """Tear down the update worker/thread defensively.

        Safe to call from both ``_on_update_found`` (the happy path) and
        ``MainWindow.closeEvent`` (in case the worker never emitted
        ``done`` — e.g. no update available, network failure).

        The check worker runs ``check_for_update()`` which blocks in
        ``urllib.request.urlopen(..., timeout=10)``. ``quit()`` only signals
        the worker's event loop AFTER ``run()`` returns, so it cannot
        interrupt a network read that is still parked inside urlopen. If the
        user closes the window during the ~10 s window right after launch
        the old code's ``wait(1000)`` returned False and closeEvent went on
        to destroy the MainWindow with the QThread still running ("QThread:
        Destroyed while thread is still running" + possible abort()).

        Root-cause fix: (1) close the in-flight urlopen response so the
        blocked read raises and ``run()`` returns immediately; (2) wait long
        enough to cover the urlopen timeout; (3) ``terminate()`` as a last
        resort so a running QThread is never left to be destroyed."""
        # (1) Abort the blocked network read, if any.
        holder = getattr(self, "_update_cancel", None)
        if holder is not None:
            resp = holder.get("resp")
            if resp is not None:
                with contextlib.suppress(Exception):
                    resp.close()
        worker = getattr(self, "_update_worker", None)
        if worker is not None:
            with contextlib.suppress(RuntimeError):
                worker.deleteLater()
            self._update_worker = None
        thread = getattr(self, "_update_thread", None)
        if thread is not None:
            with contextlib.suppress(RuntimeError):
                if thread.isRunning():
                    thread.quit()
                    # (2) Cover the urlopen timeout; the aborted read above
                    # should return well before this elapses.
                    if not thread.wait(12000):
                        # (3) Last resort — never destroy a running QThread.
                        thread.terminate()
                        thread.wait(2000)
            self._update_thread = None
        self._update_cancel = None

    def _notify_update(self):
        """Show update notification dialog automatically."""
        # Guard against a race with closeEvent -> release_worker,
        # which nulls _update_worker (and thus leaves _update_release
        # unset/None) between the worker's done.emit() on the worker thread
        # and this queued slot running on the main thread. Without this
        # guard the .get() below raises AttributeError on None.
        if not self._update_release:
            return
        self._update_btn.setVisible(True)
        tag = self._update_release.get("tag_name", "?")
        from PySide6.QtWidgets import QMessageBox
        msg = t("update.available").format(version=tag)
        msg += "\n\n" + t("update.installer_info")
        msg += "\n\n" + t("update.install") + "?"
        reply = QMessageBox.question(
            self._window, "PDFApps", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.show_update_dialog()

    def show_update_dialog(self):
        if self._update_release:
            from app.updater import UpdateDialog
            # Wired here and not looked up on the dialog's parent: the
            # controller is what composes the window with the updater,
            # and the dialog stays testable without a MainWindow. On
            # Linux the update ends in execve, which skips closeEvent.
            dlg = UpdateDialog(
                self._update_release, parent=self._window,
                confirm_discard=self._window._confirm_update_restart,
                before_exec=self._window._prepare_update_restart,
            )
            dlg.exec()
