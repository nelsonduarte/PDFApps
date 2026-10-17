"""Run a tool's ``_run_background`` work synchronously in a test.

Not a test module: pytest does not collect it because its name matches
neither ``test_*.py`` nor ``*_test.py``. The tests import it by bare
name, which works because ``tests/`` has no ``__init__.py`` (same
mechanism as ``_requirements_parsing.py``).

Four test modules carry a private copy of this stand-in
(``test_encrypted_pdf_tools``, ``test_import_encoding_and_editor_doc``,
``test_unicode_passwords``, ``test_wrong_password_dialog``). New tests
import it from here instead of adding a fifth copy; the existing ones
are left untouched.
"""

from __future__ import annotations


class FakeWorker:
    """Stands in for the ``TaskRunner`` handed to a ``do_work`` closure.

    ``progress.emit(pct, label)`` calls are recorded in ``emitted``.
    With ``cancel_after=N`` the worker reports itself cancelled once N
    progress updates have been emitted, which is how a user pressing
    Cancel mid-run looks to the closure.
    """

    def __init__(self, cancel_after: int | None = None):
        self.progress = self
        self.emitted: list[tuple] = []
        self._cancel_after = cancel_after

    def emit(self, *args):
        self.emitted.append(args)

    def is_cancelled(self) -> bool:
        return (self._cancel_after is not None
                and len(self.emitted) >= self._cancel_after)


def run_background_inline(page, monkeypatch, worker: FakeWorker | None = None
                          ) -> dict:
    """Make ``page._run_background`` run ``do_work`` inline on the test
    thread, without the progress dialog or a ``QThread``.

    Returns a dict filled once the tool runs: ``calls`` (int),
    ``worker``, and either ``result`` or ``error``. ``on_done`` is
    called with a non-``None`` result, as ``BasePage._run_background``
    does. An exception is recorded rather than routed to
    ``show_error``, whose dialog would block an offscreen run. Not
    reproduced: the action button being disabled during the run, and
    the "cancelled" status line the real helper shows for a ``None``
    result.
    """
    box: dict = {"calls": 0}

    def _fake(do_work_fn, total=0, label="", on_done=None, on_err=None,
              cancelled_status=""):
        box["calls"] += 1
        w = worker if worker is not None else FakeWorker()
        box["worker"] = w
        try:
            result = do_work_fn(w)
        except Exception as exc:  # recorded, not swallowed: asserted on
            box["error"] = exc
            return
        box["result"] = result
        if on_done is not None and result is not None:
            on_done(result)

    monkeypatch.setattr(page, "_run_background", _fake)
    return box
