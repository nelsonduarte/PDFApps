"""PDFApps – Annotation overlay for presentation mode (pen, highlighter, eraser, laser)."""

from dataclasses import dataclass, field
from enum import IntEnum

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QPainterPathStroker, QPen,
)
from PySide6.QtWidgets import QWidget


class ToolMode(IntEnum):
    POINTER = 0
    PEN = 1
    HIGHLIGHTER = 2
    ERASER = 3
    LASER = 4


@dataclass
class Stroke:
    path: QPainterPath
    color: QColor
    width: int
    kind: int = ToolMode.PEN
    points: list = field(default_factory=list)


_PEN_WIDTH = 3
_HIGHLIGHTER_WIDTH = 18
_LASER_RADIUS = 14
_ERASER_TOL = 6
_POINT_MERGE_SQ = 4


class AnnotationOverlay(QWidget):
    """Transparent click-through-when-idle overlay that captures freehand
    strokes and renders an optional laser-pointer dot. Lives as a child of
    `PresentationWidget`, sized to the parent's rect, raised above the page."""

    def __init__(self, parent: QWidget, dark_mode: bool):
        super().__init__(parent)
        self._dark_mode = bool(dark_mode)
        self._tool = ToolMode.POINTER
        self._pen_color = QColor("#EF4444")
        self._pen_width = _PEN_WIDTH
        self._highlighter_color = QColor(251, 191, 36, 90)
        self._highlighter_width = _HIGHLIGHTER_WIDTH

        self._strokes: dict[int, list[Stroke]] = {}
        self._current_stroke: Stroke | None = None
        self._current_page: int = 0
        self._laser_pos: QPoint | None = None

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Without mouse tracking, mouseMoveEvent only fires while a button is
        # held. In LASER mode the overlay is opaque-to-mouse (passthrough is
        # False), so the parent's mouseMoveEvent never sees the motion either
        # — the laser dot stays frozen until the user clicks. Enabling
        # tracking on the overlay AND on the parent (see PresentationWidget)
        # makes the laser follow the cursor and keeps the HUD auto-hide timer
        # alive across every tool mode.
        self.setMouseTracking(True)
        self._apply_cursor()

    # ── public API ────────────────────────────────────────────────────────

    def set_tool(self, tool: int) -> None:
        new_tool = ToolMode(int(tool))
        if new_tool == self._tool:
            return
        self._current_stroke = None
        if self._tool == ToolMode.LASER and new_tool != ToolMode.LASER:
            self._laser_pos = None
        self._tool = new_tool
        # Pointer mode lets clicks pass through; drawing tools capture them.
        passthrough = new_tool == ToolMode.POINTER
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, passthrough)
        self._apply_cursor()
        self.update()

    def tool(self) -> int:
        return int(self._tool)

    def set_pen_color(self, color: QColor) -> None:
        c = color if isinstance(color, QColor) else QColor(color)
        # When the highlighter is active, route the chosen hue to the
        # highlighter colour (preserving its translucent alpha) so swatch
        # clicks / hotkeys 1-6 don't silently no-op.
        if self._tool == ToolMode.HIGHLIGHTER:
            self._highlighter_color = QColor(c.red(), c.green(), c.blue(), 90)
        else:
            self._pen_color = QColor(c)

    def pen_color(self) -> QColor:
        return QColor(self._pen_color)

    def set_current_page(self, idx: int) -> None:
        if idx == self._current_page and self._current_stroke is None:
            return
        self._current_page = int(idx)
        self._current_stroke = None
        self._laser_pos = None
        # Drop any phantom mouse grab so a press during page change can't
        # leak across pages. mouseGrabber() is a static method on QWidget.
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self.update()

    def clear_current_page(self) -> None:
        if self._current_page in self._strokes:
            del self._strokes[self._current_page]
        self._current_stroke = None
        self.update()

    def clear_all(self) -> None:
        self._strokes.clear()
        self._current_stroke = None
        self._laser_pos = None
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self.update()

    def update_theme(self, dark: bool) -> None:
        self._dark_mode = bool(dark)
        self._apply_cursor()

    def set_laser_pos(self, pos: QPoint | None) -> None:
        if self._tool != ToolMode.LASER:
            return
        self._laser_pos = QPoint(pos) if pos is not None else None
        self.update()

    # ── internals ─────────────────────────────────────────────────────────

    def _apply_cursor(self) -> None:
        t = self._tool
        if t == ToolMode.POINTER:
            self.unsetCursor()
        elif t == ToolMode.LASER:
            self.setCursor(Qt.CursorShape.BlankCursor)
        elif t == ToolMode.ERASER:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def _new_stroke(self, start: QPoint) -> Stroke:
        if self._tool == ToolMode.HIGHLIGHTER:
            color = QColor(self._highlighter_color)
            width = self._highlighter_width
            kind = ToolMode.HIGHLIGHTER
        else:
            color = QColor(self._pen_color)
            width = self._pen_width
            kind = ToolMode.PEN
        path = QPainterPath()
        path.moveTo(start)
        return Stroke(path=path, color=color, width=width, kind=kind,
                      points=[QPoint(start)])

    def _erase_at(self, pos: QPoint) -> bool:
        page_strokes = self._strokes.get(self._current_page)
        if not page_strokes:
            return False
        hit_idx = -1
        for i in range(len(page_strokes) - 1, -1, -1):
            s = page_strokes[i]
            stroker = QPainterPathStroker()
            stroker.setWidth(max(2, s.width) + _ERASER_TOL)
            stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
            stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            outline = stroker.createStroke(s.path)
            if outline.contains(pos):
                hit_idx = i
                break
        if hit_idx >= 0:
            page_strokes.pop(hit_idx)
            if not page_strokes:
                self._strokes.pop(self._current_page, None)
            return True
        return False

    # ── events ────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)
            return
        pos = e.position().toPoint()
        if self._tool in (ToolMode.PEN, ToolMode.HIGHLIGHTER):
            self._current_stroke = self._new_stroke(pos)
            self.update()
            e.accept()
            return
        if self._tool == ToolMode.ERASER:
            if self._erase_at(pos):
                self.update()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        # Drawing tools mark the overlay opaque-to-mouse, so the parent's
        # mouseMoveEvent never fires. Notify the parent so its HUD auto-hide
        # timer keeps resetting. The parent's _show_hud() owns a 100 ms
        # debounce; this call is cheap at ~125 Hz.
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, "_show_hud"):
            parent._show_hud()
        pos = e.position().toPoint()
        if self._tool == ToolMode.LASER:
            self._laser_pos = pos
            self.update()
            e.accept()
            return
        if self._current_stroke is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            last = self._current_stroke.points[-1]
            dx = pos.x() - last.x()
            dy = pos.y() - last.y()
            if dx * dx + dy * dy >= _POINT_MERGE_SQ:
                self._current_stroke.path.lineTo(pos)
                self._current_stroke.points.append(QPoint(pos))
                self.update()
            e.accept()
            return
        if self._tool == ToolMode.ERASER and (e.buttons() & Qt.MouseButton.LeftButton):
            if self._erase_at(pos):
                self.update()
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(e)
            return
        if self._current_stroke is not None:
            if len(self._current_stroke.points) >= 2:
                self._strokes.setdefault(self._current_page, []).append(
                    self._current_stroke)
            self._current_stroke = None
            self.update()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e):
        if self._tool == ToolMode.LASER and self._laser_pos is not None:
            self._laser_pos = None
            self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(Qt.BrushStyle.NoBrush)

        for s in self._strokes.get(self._current_page, ()):
            pen = QPen(s.color, s.width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPath(s.path)

        if self._current_stroke is not None and len(self._current_stroke.points) >= 1:
            s = self._current_stroke
            pen = QPen(s.color, s.width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPath(s.path)

        if self._tool == ToolMode.LASER and self._laser_pos is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(239, 68, 68, 200))
            p.drawEllipse(self._laser_pos, _LASER_RADIUS, _LASER_RADIUS)
            p.setBrush(QColor(255, 255, 255, 80))
            p.drawEllipse(self._laser_pos, _LASER_RADIUS // 3, _LASER_RADIUS // 3)
        p.end()
