"""Replace every modal a tool could open with a stub that fails closed.

Not a test module: pytest does not collect it (its name matches neither
``test_*.py`` nor ``*_test.py``). Tests import it by bare name, which
works because ``tests/`` has no ``__init__.py`` (same mechanism as
``_inline_background.py``).

An offscreen run has nobody to click a modal, so a modal nobody stubbed
hangs the run until CI's job timeout. Each stub here records the call
and returns at once with the answer the real modal gives when the user
cancels it, so a code path that reaches one stops in milliseconds and
the test fails on the record instead of hanging.

The table started as the one ``test_watermark_characterization``
measured (PySide6 6.11.2), plus the ``exec_`` spellings. That module
keeps its own copy, and so does the ``ui`` fixture of
``test_no_silent_overwrite``, which scripts the overwrite box instead of
failing it. Not covered: ``QMessageBox.warning`` and
``QMessageBox.information`` (callers record them, they are the tools'
normal outcome), and ``QPrintDialog`` / ``QPageSetupDialog``, which
define their own ``exec`` in QtPrintSupport.

Menus are not in the table. ``QMenu.exec`` has a static overload, and
PySide6 6.11.2 binds the instance spelling on the object itself:
patching the class attribute catches ``menu.exec_()`` and the static
``QMenu.exec(actions, pos)``, but not ``menu.exec()`` nor
``menu.exec(pos)``, the spelling every context menu of the app uses
(measured: a real menu stayed open 1.5 s, until a timer closed it).
Menus are caught when they are shown instead, by an application event
filter (``_MenuCloser``): it records the menu and closes it from its own
event loop, so ``exec`` returns no action, whatever the spelling, and a
``popup`` closes on the next event-loop pass.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFontDialog,
    QInputDialog,
    QMenu,
    QMessageBox,
)

# (class, attribute, the reply of a cancelled real modal). Escape for
# the QMessageBox statics: No on question's default Yes|No buttons, Ok
# for critical. reject() for the rest; the ok flag the callers branch
# on is False wherever there is one.
FAIL_CLOSED_MODALS: tuple[tuple[type, str, object], ...] = (
    (QMessageBox, "question", QMessageBox.StandardButton.No),
    (QMessageBox, "critical", QMessageBox.StandardButton.Ok),
    (QMessageBox, "about", None),
    (QFileDialog, "getSaveFileName", ("", "")),
    (QFileDialog, "getOpenFileName", ("", "")),
    (QFileDialog, "getOpenFileNames", ([], "")),
    (QFileDialog, "getExistingDirectory", ""),
    (QInputDialog, "getText", ("", False)),
    (QInputDialog, "getMultiLineText", ("", False)),
    (QInputDialog, "getItem", ("", False)),
    (QInputDialog, "getInt", (0, False)),
    (QInputDialog, "getDouble", (0.0, False)),
    (QColorDialog, "getColor", QColor()),
    (QFontDialog, "getFont", (False, QFont())),
    # Every QDialog subclass in QtWidgets inherits exec, QMessageBox
    # included: the box an instance-built question (``_ask_overwrite``,
    # the editor's encryption choice) opens lands here.
    (QDialog, "exec", QDialog.DialogCode.Rejected),
    (QDialog, "exec_", QDialog.DialogCode.Rejected),
    # QMessageBox inherits exec today; patched too so a PySide6 that
    # binds its own override cannot slip past into a real modal loop.
    (QMessageBox, "exec", QDialog.DialogCode.Rejected),
    (QMessageBox, "exec_", QDialog.DialogCode.Rejected),
)


def _describe_exec(box) -> tuple:
    if isinstance(box, QMenu):
        return (type(box).__name__, box.title(), "")
    text = box.text() if isinstance(box, QMessageBox) else ""
    return (type(box).__name__, box.windowTitle(), text)


class _MenuCloser(QObject):
    """Records and closes every ``QMenu`` shown while armed.

    Armed by setting ``record`` to a list, which installs it as an event
    filter of the application; set back to ``None`` (what
    ``monkeypatch`` does on undo) it removes itself, so no test after
    the arming one pays for a Python call on every event. The close is
    deferred to the menu's own event loop: ``QMenu.exec`` shows the menu
    before it starts that loop, and a close that early would be lost.
    """

    def __init__(self) -> None:
        super().__init__()
        self._record: list | None = None

    @property
    def record(self) -> list | None:
        return self._record

    @record.setter
    def record(self, value: list | None) -> None:
        app = QApplication.instance()
        if value is not None and self._record is None:
            app.installEventFilter(self)
        elif value is None and self._record is not None:
            app.removeEventFilter(self)
        self._record = value

    def eventFilter(self, obj, event) -> bool:
        if (self._record is not None and event.type() == QEvent.Type.Show
                and isinstance(obj, QMenu)):
            self._record.append(("QMenu.exec", _describe_exec(obj)))
            QTimer.singleShot(0, obj, obj.close)
        return False


_MENU_CLOSER = _MenuCloser()


def install_fail_closed_modals(monkeypatch, record: list) -> None:
    """Patch every entry of ``FAIL_CLOSED_MODALS`` through ``monkeypatch``,
    and arm the menu closer until ``monkeypatch`` undoes it.

    Each call is appended to ``record`` as ``("Class.attr", details)``
    and answered with the table's cancel reply; a menu, whatever opened
    it, as ``("QMenu.exec", details)``, closed with no action chosen.
    The caller asserts that ``record`` is empty after the code under
    test returns, never inside a stub: a stub raising from inside a slot
    would be swallowed by Qt and the tool would carry on. A test that
    expects one particular modal patches it again, after this call, with
    a scripted stand-in.
    """
    for cls, name, answer in FAIL_CLOSED_MODALS:
        label = f"{cls.__name__}.{name}"
        if name in ("exec", "exec_"):
            def _exec(box, *_a, _label=label, _answer=answer, **_k):
                record.append((_label, _describe_exec(box)))
                return _answer
            monkeypatch.setattr(cls, name, _exec)
        else:
            def _static(*a, _label=label, _answer=answer, **_k):
                record.append((_label, tuple(str(x) for x in a[1:3])))
                return _answer
            monkeypatch.setattr(cls, name, staticmethod(_static))
    monkeypatch.setattr(_MENU_CLOSER, "record", record)


