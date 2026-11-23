"""Viewer tabs keep their order, and each shows and closes its own document.

A tab's index in ``MainWindow._tab_bar`` is also its index in
``_viewers`` and ``_viewer_stack``, which code across ``MainWindow``
relies on (for example ``_on_tab_changed`` and ``_close_tab``), and
nothing handles ``tabMoved``, so a tab dragged elsewhere would show, and
close, another tab's document. Dragging stays off until tab reordering is
supported (redesign step I10).

The window is built by ``_window`` from ``test_overwrite_characterization``:
the config in ``tmp_path``, no update check and no single-instance server.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyle, QTabBar
from test_overwrite_characterization import _close_window, _make_pdf, _window

_ALFA = "Alfa ç.pdf"
_BRAVO = "Bravo ü.pdf"


def _key(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _open_two_tabs(win, qtbot, tmp_path) -> QTabBar:
    win._load_and_track(_make_pdf(tmp_path / _ALFA, "ALFA", 1))
    win._load_and_track(_make_pdf(tmp_path / _BRAVO, "BRAVO", 1))  # 2nd tab
    qtbot.wait(50)
    bar = win._tab_bar
    assert len(win._viewers) == win._viewer_stack.count() == bar.count() == 2
    assert bar.isVisible()
    return bar


def _drag_first_tab_past_second(bar: QTabBar) -> None:
    # With the bar movable, Qt swaps the two during the moves, before the
    # release (measured with PySide6 6.11.3, offscreen), so no wait is
    # needed after it.
    start = bar.tabRect(0).center()
    end = QPoint(bar.tabRect(1).right() + 20, start.y())
    QTest.mousePress(bar, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, start)
    for x in range(start.x(), end.x(), 4):
        QTest.mouseMove(bar, QPoint(x, start.y()))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, end)


def _tab_of(bar: QTabBar, name: str) -> int:
    names = [os.path.basename(bar.tabToolTip(i)) for i in range(bar.count())]
    assert names.count(name) == 1, names
    return names.index(name)


def _click_close_button(bar: QTabBar, index: int) -> None:
    side = QTabBar.ButtonPosition(bar.style().styleHint(
        QStyle.StyleHint.SH_TabBar_CloseButtonPosition, None, bar))
    button = bar.tabButton(index, side)
    assert button is not None
    assert button.isVisible()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)


def test_viewer_tabs_cannot_be_dragged(monkeypatch, qtbot, tmp_path):
    """Until tab reordering is supported, the bar cannot move a tab."""
    win = _window(monkeypatch, tmp_path)
    try:
        bar = _open_two_tabs(win, qtbot, tmp_path)
        assert bar.isMovable() is False
        with qtbot.assertNotEmitted(bar.tabMoved):
            _drag_first_tab_past_second(bar)
    finally:
        _close_window(win, qtbot, tmp_path)


def test_dragging_a_tab_keeps_each_tab_on_its_own_document(
        monkeypatch, qtbot, tmp_path):
    """What the user sees after a drag: holds with or without reordering."""
    win = _window(monkeypatch, tmp_path)
    try:
        bar = _open_two_tabs(win, qtbot, tmp_path)
        _drag_first_tab_past_second(bar)

        # Ends on Alfa's tab, so the close button clicked below is on a tab
        # that is not the current one.
        for name in (_BRAVO, _ALFA, _BRAVO, _ALFA):
            i = _tab_of(bar, name)
            QTest.mouseClick(bar, Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier,
                             bar.tabRect(i).center())
            assert bar.currentIndex() == i
            shown = win._viewer_stack.currentWidget()
            assert shown is win._viewer
            assert _key(shown.current_path()) == _key(bar.tabToolTip(i))

        _click_close_button(bar, _tab_of(bar, _BRAVO))

        alfa = _key(str(tmp_path / _ALFA))
        assert len(win._viewers) == win._viewer_stack.count() == bar.count() == 1
        assert _key(win._viewers[0].current_path()) == alfa
        assert _key(bar.tabToolTip(0)) == alfa
    finally:
        _close_window(win, qtbot, tmp_path)
