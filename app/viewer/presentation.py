"""PDFApps – Presentation mode: fullscreen single-page viewer."""

import contextlib

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QApplication


class PresentationWidget(QWidget):
    """Fullscreen single-page PDF viewer with keyboard navigation."""

    def __init__(self, path: str, password: str, start_page: int, total_pages: int):
        super().__init__()
        self._path = path
        self._password = password
        self._current = start_page
        self._total = total_pages
        self._pixmap = None
        self._ready = False
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
        # because it triggers resizeEvent immediately
        self._counter = QLabel(self)
        self._counter.setStyleSheet(
            "background: rgba(0,0,0,0.6); color: white; "
            "padding: 6px 16px; border-radius: 8px; font-size: 14px;"
        )
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(lambda: self._counter.setVisible(False))

        self.setWindowFlags(Qt.WindowType.Window)
        self.setStyleSheet("background: #000000;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setWindowState(Qt.WindowState.WindowFullScreen)

        self._ready = True
        QTimer.singleShot(0, self._render)

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
            self._pixmap = None

        self._update_counter()
        self.update()

    def closeEvent(self, event):
        # Release the fitz document handle. Swallowing exceptions here
        # because the alternative is a Qt-level crash during teardown
        # if fitz is mid-finalize on the worker thread.
        if self._doc is not None:
            with contextlib.suppress(Exception):
                self._doc.close()
            self._doc = None
        super().closeEvent(event)

    def _update_counter(self):
        self._counter.setText(f"{self._current + 1} / {self._total}")
        self._counter.adjustSize()
        lw = self._counter.width()
        self._counter.move(self.width() // 2 - lw // 2, self.height() - 50)
        self._counter.setVisible(True)
        self._hide_timer.start(3000)

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

    def resizeEvent(self, _):
        if not self._ready:
            return
        self._update_counter()
        QTimer.singleShot(0, self._render)
