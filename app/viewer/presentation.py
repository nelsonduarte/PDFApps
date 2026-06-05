"""PDFApps – Presentation mode: fullscreen single-page viewer."""

import contextlib
import logging
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QApplication
from shiboken6 import isValid

from app.viewer.annotation_layer import AnnotationOverlay, ToolMode
from app.viewer.annotation_hud import AnnotationHUD


_log = logging.getLogger(__name__)

_HUD_AUTO_HIDE_MS = 3000
_HUD_RESTART_DEBOUNCE_MS = 100

_PALETTE_HOTKEYS = {
    Qt.Key.Key_1: "#EF4444",
    Qt.Key.Key_2: "#10B981",
    Qt.Key.Key_3: "#3B82F6",
    Qt.Key.Key_4: "#FBBF24",
    Qt.Key.Key_5: "#111111",
    Qt.Key.Key_6: "#FFFFFF",
}


class PresentationWidget(QWidget):
    """Fullscreen single-page PDF viewer with keyboard navigation and a
    PowerPoint-style annotation HUD (pen / highlighter / eraser / laser).
    Annotations are session-scoped — kept per page while the window lives,
    discarded on close."""

    def __init__(self, path: str, password: str, start_page: int,
                 total_pages: int, dark_mode: bool = True):
        super().__init__()
        self._path = path
        self._password = password
        self._current = start_page
        self._total = total_pages
        self._pixmap = None
        self._ready = False
        self._dark_mode = bool(dark_mode)
        self._hud_last_shown_ms = 0.0

        # Hold the document open for the lifetime of the widget — the
        # previous version reopened (+ optionally authenticated) the
        # PDF on every Escape/arrow key, which stalled navigation for
        # 100–500 ms on multi-MB or encrypted files. Failures here
        # propagate to the caller (`_start_presentation`) so the user
        # still sees a friendly error dialog.
        import fitz
        self._doc = fitz.open(self._path)
        if self._password:
            self._doc.authenticate(self._password)

        # All child widgets and timers must exist before setWindowState
        # because it triggers resizeEvent immediately.
        self._counter = QLabel(self)
        self._counter.setStyleSheet(
            "background: rgba(0,0,0,0.6); color: white; "
            "padding: 6px 16px; border-radius: 8px; font-size: 14px;"
        )
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._overlay = AnnotationOverlay(self, self._dark_mode)
        self._overlay.set_current_page(self._current)
        self._overlay.setGeometry(self.rect())

        self._hud = AnnotationHUD(self, self._dark_mode)
        self._hud.tool_selected.connect(self._on_tool_selected)
        self._hud.color_selected.connect(self._on_color_selected)
        self._hud.clear_requested.connect(self._on_clear_requested)
        self._hud.set_active_tool(int(ToolMode.POINTER))
        self._hud.set_active_color(self._overlay.pen_color())
        self._hud.hide()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(
            lambda: self._counter.setVisible(False)
            if isValid(self._counter) else None)

        self._hud_hide_timer = QTimer(self)
        self._hud_hide_timer.setSingleShot(True)
        self._hud_hide_timer.timeout.connect(
            lambda: self._hud.hide() if isValid(self._hud) else None)

        self.setWindowFlags(Qt.WindowType.Window)
        self.setStyleSheet("background: #000000;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setWindowState(Qt.WindowState.WindowFullScreen)

        self._ready = True
        QTimer.singleShot(0, self._render)

    def update_theme(self, dark: bool) -> None:
        self._dark_mode = bool(dark)
        if isValid(self._overlay):
            self._overlay.update_theme(self._dark_mode)
        if isValid(self._hud):
            self._hud.update_theme(self._dark_mode)

    def _render(self):
        import fitz
        try:
            if self._doc is None:
                self._pixmap = None
                return
            page = self._doc[self._current]
            screen = self.screen() or QApplication.primaryScreen()
            geom = screen.geometry()
            dpr = screen.devicePixelRatio() or 1.0
            sw, sh = geom.width(), geom.height()
            zoom = min(sw / page.rect.width, sh / page.rect.height)
            rz = zoom * dpr
            pix = page.get_pixmap(matrix=fitz.Matrix(rz, rz))
            qp = QPixmap()
            qp.loadFromData(pix.tobytes("png"))
            qp.setDevicePixelRatio(dpr)
            self._pixmap = qp
        except Exception:
            _log.exception("presentation _render failed")
            self._pixmap = None

        self._overlay.set_current_page(self._current)
        self._overlay.raise_()
        self._hud.raise_()
        self._update_counter()
        self.update()

    def _update_counter(self):
        self._counter.setText(f"{self._current + 1} / {self._total}")
        self._counter.adjustSize()
        lw = self._counter.width()
        self._counter.move(self.width() // 2 - lw // 2, self.height() - 50)
        self._counter.setVisible(True)
        self._counter.raise_()
        self._hide_timer.start(3000)

    def _show_hud(self):
        if not isValid(self._hud):
            return
        if not self._hud.isVisible():
            self._hud.reposition()
            self._hud.show()
            self._hud.raise_()
        now = time.monotonic() * 1000.0
        if now - self._hud_last_shown_ms < _HUD_RESTART_DEBOUNCE_MS:
            return
        self._hud_last_shown_ms = now
        self._hud_hide_timer.start(_HUD_AUTO_HIDE_MS)
        # Show the system cursor while the HUD is up so the user can aim at
        # buttons. Drawing tools install their own cursor through the
        # overlay; pointer mode uses the default arrow.
        if self._overlay.tool() == ToolMode.POINTER:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _on_tool_selected(self, mode: int):
        self._overlay.set_tool(int(mode))
        self._hud.set_active_tool(int(mode))
        if int(mode) == int(ToolMode.POINTER):
            self.setCursor(Qt.CursorShape.ArrowCursor
                           if self._hud.isVisible()
                           else Qt.CursorShape.BlankCursor)
        else:
            self.setCursor(Qt.CursorShape.BlankCursor)
        self._show_hud()

    def _on_color_selected(self, color):
        self._overlay.set_pen_color(color)
        self._hud.set_active_color(color)
        self._show_hud()

    def _on_clear_requested(self):
        self._overlay.clear_current_page()
        self.update()
        self._show_hud()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000000"))
        if self._pixmap:
            dpr = self._pixmap.devicePixelRatio() or 1.0
            pw = self._pixmap.width() / dpr
            ph = self._pixmap.height() / dpr
            x = (self.width() - pw) / 2
            y = (self.height() - ph) / 2
            p.drawPixmap(int(x), int(y), self._pixmap)
        p.end()

    def keyPressEvent(self, e):
        key = e.key()

        # Skip annotation hotkeys when any modifier is held so Ctrl+C /
        # Ctrl+P / Ctrl+1 etc. don't accidentally trigger tool / colour
        # changes during a presentation.
        if e.modifiers() & (Qt.KeyboardModifier.ControlModifier
                            | Qt.KeyboardModifier.AltModifier
                            | Qt.KeyboardModifier.MetaModifier):
            super().keyPressEvent(e)
            return

        if key == Qt.Key.Key_P:
            self._on_tool_selected(int(ToolMode.PEN))
            return
        if key == Qt.Key.Key_H:
            self._on_tool_selected(int(ToolMode.HIGHLIGHTER))
            return
        if key == Qt.Key.Key_E:
            self._on_tool_selected(int(ToolMode.ERASER))
            return
        if key == Qt.Key.Key_L:
            self._on_tool_selected(int(ToolMode.LASER))
            return
        if key == Qt.Key.Key_C:
            self._on_clear_requested()
            return
        if key in _PALETTE_HOTKEYS:
            current = self._overlay.tool()
            if current in (int(ToolMode.PEN), int(ToolMode.HIGHLIGHTER)):
                color = QColor(_PALETTE_HOTKEYS[key])
                self._overlay.set_pen_color(color)
                self._hud.set_active_color(color)
                self._show_hud()
                return

        if key == Qt.Key.Key_Escape:
            self.close()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down,
                     Qt.Key.Key_Space, Qt.Key.Key_PageDown):
            if self._current < self._total - 1:
                self._current += 1
                self._render()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up,
                     Qt.Key.Key_Backspace, Qt.Key.Key_PageUp):
            if self._current > 0:
                self._current -= 1
                self._render()
        elif key == Qt.Key.Key_Home:
            self._current = 0
            self._render()
        elif key == Qt.Key.Key_End:
            self._current = self._total - 1
            self._render()

    def mouseMoveEvent(self, e):
        self._show_hud()
        if self._overlay.tool() == int(ToolMode.LASER):
            self._overlay.set_laser_pos(e.position().toPoint())
        super().mouseMoveEvent(e)

    def resizeEvent(self, _):
        if not self._ready:
            return
        if isValid(self._overlay):
            self._overlay.setGeometry(self.rect())
        if isValid(self._hud):
            self._hud.reposition()
        self._update_counter()
        QTimer.singleShot(0, self._render)

    def closeEvent(self, event):
        # Drop annotation state first so paintEvent on the overlay does not
        # touch stale stroke buffers during teardown.
        if isValid(self._overlay):
            self._overlay.clear_all()
        for tmr in (getattr(self, "_hide_timer", None),
                    getattr(self, "_hud_hide_timer", None)):
            if tmr is not None and isValid(tmr):
                tmr.stop()
        # Release the fitz document handle. Swallowing exceptions here
        # because the alternative is a Qt-level crash during teardown
        # if fitz is mid-finalize on the worker thread.
        if self._doc is not None:
            with contextlib.suppress(Exception):
                self._doc.close()
            self._doc = None
        super().closeEvent(event)
