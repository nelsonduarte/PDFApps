"""A wrong password must be presented as a warning, never as a crash.

The Unicode-password fix multiplied the sites that raise on a bad
password (merge, watermark pre-flight and worker, the editor's form
loader and save path). Every one of them reached ``show_error``, which
put the generic

    "Something went wrong. Click 'Show Details' below for the technical
     error, and the full traceback has been written to the log file."

in the primary text and hid the real, already-translated sentence behind
"Show Details", prefixed with ``ValueError:`` -- a Python class name, in
front of an end user, in eight locales.

These tests assert what the dialog is actually *told to show*, not just
that an exception was raised: primary text, icon, and the presence or
absence of a details pane. Asserting only ``pytest.raises`` cannot tell
the two presentations apart, which is exactly the gap that let the
defect ship.

The generic path is pinned here too. Without that, "present wrong
passwords as warnings" could quietly degrade into "present everything as
a warning", which would hide real faults and stop writing tracebacks to
the log.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

_unused_app = QApplication.instance() or QApplication([])

import pymupdf  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402

from app.i18n import t  # noqa: E402
from app.utils import WrongPasswordError, show_error  # noqa: E402


# ── dialog capture ───────────────────────────────────────────────────────


class _Shown:
    """What a QMessageBox was configured to display before exec()."""

    def __init__(self):
        self.icon = None
        self.title = None
        self.text = None
        self.detailed = None
        self.shown = False


def _capture_message_box(monkeypatch) -> _Shown:
    """Record the setters ``show_error`` calls and neutralise ``exec``.

    Patching the setters rather than replacing ``QMessageBox`` keeps the
    real widget (and therefore the real Qt behaviour of ``show_error``)
    in play; only the modal block is removed.
    """
    seen = _Shown()

    monkeypatch.setattr(QMessageBox, "setIcon",
                        lambda self, i: setattr(seen, "icon", i))
    monkeypatch.setattr(QMessageBox, "setWindowTitle",
                        lambda self, s: setattr(seen, "title", s))
    monkeypatch.setattr(QMessageBox, "setText",
                        lambda self, s: setattr(seen, "text", s))
    monkeypatch.setattr(QMessageBox, "setDetailedText",
                        lambda self, s: setattr(seen, "detailed", s))

    def _exec(self):
        seen.shown = True
        return 0

    monkeypatch.setattr(QMessageBox, "exec", _exec)
    return seen


# ── fixtures ─────────────────────────────────────────────────────────────


def _plain_pdf(tmp_path: Path, name: str = "plain.pdf", pages: int = 2) -> str:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    out = str(tmp_path / name)
    doc.save(out)
    doc.close()
    return out


def _locked_pdf(tmp_path: Path, pwd: str, name: str, pages: int = 2) -> str:
    """A PDF locked with the raw UTF-8 bytes of ``pwd``."""
    plain = _plain_pdf(tmp_path, "src_for_" + name, pages=pages)
    w = PdfWriter()
    w.append(PdfReader(plain))
    w.encrypt(user_password=pwd.encode("utf-8"),   # type: ignore[arg-type]
              owner_password=pwd.encode("utf-8"),  # type: ignore[arg-type]
              algorithm="AES-256")
    out = str(tmp_path / name)
    with open(out, "wb") as fh:
        w.write(fh)
    return out


class _FakeWorker:
    """Stand-in for the TaskRunner handed to a ``do_work`` closure."""

    def __init__(self):
        self.progress = self

    def emit(self, *_a):
        pass

    def is_cancelled(self):
        return False


def _run_background_inline(page, monkeypatch, on_err_sink: list):
    """Run ``do_work`` inline and route its exception through the real
    ``_wrap_err`` contract: the error handler receives the exception
    instance, exactly as ``TaskRunner.error`` (a ``Signal(object)``)
    delivers it."""
    def _fake(do_work_fn, total=0, label="", on_done=None, on_err=None,
              cancelled_status=""):
        try:
            result = do_work_fn(_FakeWorker())
        except Exception as exc:
            on_err_sink.append(exc)
            if on_err is not None:
                on_err(exc)
            else:
                # Mirror BasePage._run_background's default arm.
                from app.utils import show_error as _se
                _se(page, exc)
            return
        if on_done is not None and result is not None:
            on_done(result)

    monkeypatch.setattr(page, "_run_background", _fake)


# ── 1. show_error itself ─────────────────────────────────────────────────


def test_wrong_password_is_shown_as_a_warning_not_a_crash(monkeypatch):
    """The core of the fix, asserted on all four visible properties."""
    seen = _capture_message_box(monkeypatch)

    show_error(None, WrongPasswordError(t("tool.err.wrong_password")))

    assert seen.shown, "no dialog was shown at all"
    assert seen.text == t("tool.err.wrong_password"), (
        "the real message must be the PRIMARY text, not buried in "
        "details: got %r" % (seen.text,)
    )
    assert seen.text != t("msg.unexpected")
    assert seen.icon == QMessageBox.Icon.Warning, (
        "a recoverable typo must not carry the critical/error icon"
    )
    assert seen.title == t("msg.warning")
    assert seen.detailed is None, (
        "a wrong password has no technical detail worth a 'Show Details' "
        "pane: got %r" % (seen.detailed,)
    )


def test_wrong_password_dialog_never_leaks_the_python_class_name(monkeypatch):
    """``WrongPasswordError:`` / ``ValueError:`` must not reach the user."""
    seen = _capture_message_box(monkeypatch)

    show_error(None, WrongPasswordError(t("tool.err.wrong_password")))

    body = "%s %s" % (seen.text, seen.detailed)
    assert "WrongPasswordError" not in body
    assert "ValueError" not in body
    assert "Error:" not in body


def test_wrong_password_dialog_mentions_no_traceback_or_log(monkeypatch):
    """The generic text tells the user a traceback was written to a log
    file. For a typo that is both false-flavoured and alarming."""
    seen = _capture_message_box(monkeypatch)

    show_error(None, WrongPasswordError(t("tool.err.wrong_password")))

    lowered = (seen.text or "").lower()
    assert "traceback" not in lowered
    assert "log" not in lowered


def test_an_empty_wrong_password_error_still_says_something(monkeypatch):
    """Defensive: a bare ``WrongPasswordError()`` must not render an
    empty dialog. Cheap to guarantee, and the alternative is a message
    box with no text at all."""
    seen = _capture_message_box(monkeypatch)

    show_error(None, WrongPasswordError())

    assert seen.text == t("tool.err.wrong_password")


# ── 2. the generic path must be untouched ────────────────────────────────


@pytest.mark.parametrize("exc", [
    RuntimeError("boom"),
    ValueError("a plain ValueError is NOT a password failure"),
    OSError("disk went away"),
    Exception("generic"),
])
def test_other_exceptions_still_take_the_generic_crash_path(exc, monkeypatch):
    """This is the test that stops the fix becoming "everything is a
    warning". A real fault must keep its critical icon, its generic
    primary text and its details pane.

    ``ValueError`` is in the list on purpose: ``WrongPasswordError`` is
    deliberately not a subclass of it, and an ``isinstance`` check that
    accidentally widened to ``ValueError`` would silently reclassify
    every "no size gain" and page-range error as a password warning.
    """
    seen = _capture_message_box(monkeypatch)

    show_error(None, exc)

    assert seen.shown
    assert seen.text == t("msg.unexpected"), (
        "a real fault lost its generic explanation: %r" % (seen.text,)
    )
    assert seen.icon == QMessageBox.Icon.Critical
    assert seen.title == t("msg.error")
    assert seen.detailed == "%s: %s" % (type(exc).__name__, exc), (
        "the technical details pane must survive for real faults"
    )


def test_generic_path_still_logs_with_a_traceback(monkeypatch, caplog):
    """The log entry (with exc_info) is half of what the details pane
    promises the user. It must not be collateral damage."""
    _capture_message_box(monkeypatch)

    with caplog.at_level("ERROR"):
        show_error(None, RuntimeError("boom"))

    assert any(r.levelname == "ERROR" and r.exc_info
               for r in caplog.records), (
        "the generic path stopped logging the traceback"
    )


def test_wrong_password_logs_a_warning_without_a_traceback(monkeypatch,
                                                           caplog):
    """A typo is not an ERROR, and a stack dump of one is noise."""
    _capture_message_box(monkeypatch)

    with caplog.at_level("WARNING"):
        show_error(None, WrongPasswordError(t("tool.err.wrong_password")))

    records = [r for r in caplog.records
               if "password" in r.getMessage().lower()]
    assert records, "the wrong password was not logged at all"
    assert all(r.levelname == "WARNING" for r in records)
    assert all(not r.exc_info for r in records)


# ── 3. end to end, per multiplied site ───────────────────────────────────


def test_merge_wrong_password_reaches_the_user_as_a_warning(tmp_path,
                                                            monkeypatch):
    """merge.py: raise -> ``except Exception`` -> ``show_error``."""
    from app.tools.merge import TabJuntar

    good = _plain_pdf(tmp_path, "merge_good.pdf")
    locked = _locked_pdf(tmp_path, "correct-horse", "merge_locked.pdf")
    out = str(tmp_path / "merged.pdf")

    seen = _capture_message_box(monkeypatch)

    page = TabJuntar(lambda *a, **k: None)
    try:
        page.lst.addItem(good)
        page.lst.addItem(locked)
        page._pwd_map[locked] = "definitely-not-it"
        page.drop_out.set_path(out)
        page._run()

        assert seen.shown, "a wrong password produced no dialog"
        assert seen.text == t("tool.err.wrong_password"), (
            "merge showed the crash text instead of the password "
            "message: %r" % (seen.text,)
        )
        assert seen.icon == QMessageBox.Icon.Warning
        assert seen.detailed is None
        assert not os.path.isfile(out), (
            "merge wrote an output despite one input never decrypting"
        )
    finally:
        page.deleteLater()


def test_watermark_preflight_wrong_password_is_a_warning(tmp_path,
                                                         monkeypatch):
    """watermark.py pre-flight: the encrypted *stamp* PDF."""
    from app.tools.watermark import TabMarcaDagua

    src = _plain_pdf(tmp_path, "wm_src.pdf")
    wm = _locked_pdf(tmp_path, "correct-horse", "wm_locked.pdf", pages=1)
    out = str(tmp_path / "wm_out.pdf")

    seen = _capture_message_box(monkeypatch)

    page = TabMarcaDagua(lambda *a, **k: None)
    try:
        monkeypatch.setattr(page, "_prompt_watermark_password",
                            lambda p: "definitely-not-it")
        page.drop_in.blockSignals(True)
        page.drop_in.set_path(src)
        page.drop_in.blockSignals(False)
        page.drop_wm.blockSignals(True)
        page.drop_wm.set_path(wm)
        page.drop_wm.blockSignals(False)
        page.drop_out.set_path(out)

        page._run()

        assert seen.shown
        assert seen.text == t("tool.err.wrong_password"), (
            "watermark pre-flight showed the crash text: %r" % (seen.text,)
        )
        assert seen.icon == QMessageBox.Icon.Warning
        assert seen.detailed is None
    finally:
        page.deleteLater()


def test_watermark_worker_wrong_password_is_a_warning(tmp_path, monkeypatch):
    """watermark.py ``do_work``: the in-worker guard, reached through the
    ``_run_background`` error contract rather than a direct call."""
    from app.tools.watermark import TabMarcaDagua

    src = _locked_pdf(tmp_path, "correct-horse", "wmw_locked.pdf", pages=2)
    wm = _plain_pdf(tmp_path, "wmw_stamp.pdf", pages=1)
    out = str(tmp_path / "wmw_out.pdf")

    seen = _capture_message_box(monkeypatch)
    raised: list = []

    page = TabMarcaDagua(lambda *a, **k: None)
    try:
        # Correct password for the pre-flight, so the worker guard is the
        # thing under test; the worker re-reads `pwd` captured at that
        # moment, so flip it after the pre-flight has passed.
        page._pdf_password = "correct-horse"
        monkeypatch.setattr(page, "_prompt_watermark_password", lambda p: "")

        def _fake_bg(do_work_fn, total=0, label="", on_done=None,
                     on_err=None, cancelled_status=""):
            # Force the worker's own guard to fire by making its decrypt
            # attempt fail, which is the "password cleared between
            # checks" case the guard exists for.
            monkeypatch.setattr("app.tools.watermark.decrypt_pypdf",
                                lambda *_a, **_k: None)
            try:
                do_work_fn(_FakeWorker())
            except Exception as exc:
                raised.append(exc)
                if on_err is not None:
                    on_err(exc)
                else:
                    show_error(page, exc)

        monkeypatch.setattr(page, "_run_background", _fake_bg)

        page.drop_in.blockSignals(True)
        page.drop_in.set_path(src)
        page.drop_in.blockSignals(False)
        page.drop_wm.blockSignals(True)
        page.drop_wm.set_path(wm)
        page.drop_wm.blockSignals(False)
        page.drop_out.set_path(out)

        page._run()

        assert raised, "the worker guard never fired"
        assert isinstance(raised[0], WrongPasswordError), (
            "the worker raised %s, which show_error cannot recognise"
            % (type(raised[0]).__name__,)
        )
        assert seen.shown
        assert seen.text == t("tool.err.wrong_password")
        assert seen.icon == QMessageBox.Icon.Warning
        assert seen.detailed is None
    finally:
        page.deleteLater()


def test_editor_save_wrong_password_is_a_warning(tmp_path, monkeypatch):
    """editor/tab.py ``_apply_forms``: the editor's own save path, which
    catches ``Exception`` and calls ``show_error`` directly."""
    from app.editor.tab import TabEditar

    src = _locked_pdf(tmp_path, "correct-horse", "editor_locked.pdf")
    out = str(tmp_path / "editor_out.pdf")

    seen = _capture_message_box(monkeypatch)

    tab = TabEditar(lambda *a, **k: None)
    try:
        tab._doc_path = src
        tab._pdf_password = "definitely-not-it"
        monkeypatch.setattr(tab, "_prompt_encryption_choice",
                            lambda: "plaintext")

        tab._apply_forms(out)

        assert seen.shown, "the editor swallowed the password failure"
        assert seen.text == t("tool.err.wrong_password"), (
            "the editor showed the crash text: %r" % (seen.text,)
        )
        assert seen.icon == QMessageBox.Icon.Warning
        assert seen.detailed is None
    finally:
        tab.deleteLater()


def test_editor_form_loader_still_reports_inline_not_via_dialog(tmp_path,
                                                                monkeypatch):
    """``_load_form_fields`` deliberately reports inline in its status
    label and never opens a dialog. Changing the exception type must not
    have re-routed it: its ``except Exception`` still catches, because
    ``WrongPasswordError`` derives from ``Exception``."""
    from app.editor.tab import TabEditar

    src = _locked_pdf(tmp_path, "correct-horse", "forms_locked.pdf")
    seen = _capture_message_box(monkeypatch)

    tab = TabEditar(lambda *a, **k: None)
    try:
        tab._pdf_password = "definitely-not-it"
        tab._load_form_fields(src)

        assert tab._form_status.text() == t("editor.forms.load_failed")
        assert not seen.shown, (
            "the inline status path started opening a dialog"
        )
    finally:
        tab.deleteLater()


# ── 4. the type contract the routing depends on ──────────────────────────


def test_every_wrong_password_raise_uses_the_recognised_type():
    """The routing in ``show_error`` is type-based, so a single site left
    raising ``ValueError`` silently regresses to the crash dialog while
    every behavioural test elsewhere still passes.

    Enumerated by text because the raise sites live inside worker
    closures that need a locked PDF and a running tool page each to
    reach; this catches a re-introduction at any of them for the cost of
    a file read.
    """
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted((root / "app").rglob("*.py")):
        for i, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            compact = line.replace(" ", "")
            if 'tool.err.wrong_password' not in compact:
                continue
            if 'raise' not in compact:
                continue
            if 'raiseWrongPasswordError(' not in compact:
                offenders.append("%s:%d" % (path.relative_to(root), i))

    assert not offenders, (
        "these raise sites bypass show_error's warning branch and will "
        "be shown to the user as a crash: %s" % (offenders,)
    )


def test_wrong_password_error_is_still_not_a_value_error():
    """Restated here next to the routing it now also protects.

    If it ever became a ``ValueError``, compress's ``except ValueError``
    would report a locked file as the friendly "no size gain" outcome.
    """
    assert not issubclass(WrongPasswordError, ValueError)
    assert issubclass(WrongPasswordError, Exception)
