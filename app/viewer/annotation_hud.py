"""PDFApps – Floating HUD toolbar for presentation-mode annotations."""

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QFrame
import qtawesome as qta

from app.constants import (
    ACCENT, BG_CARD, BORDER, TEXT_PRI, TEXT_SEC,
    _LC, _LO, _LP, _LQ,
)
from app.i18n import t
from app.viewer.annotation_layer import ToolMode


def _rgba(hex_color: str, alpha: int) -> str:
    """Compose an rgba(...) QSS literal from a theme hex constant."""
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


_HUD_HEIGHT = 64
_BTN_SIZE = 42
_ICON_PX = 20
_SWATCH_SIZE = 28
_BAND_RADIUS = 14
_COLORS = [
    ("#EF4444", "red"),
    ("#10B981", "green"),
    ("#3B82F6", "blue"),
    ("#FBBF24", "yellow"),
    ("#111111", "black"),
    ("#FFFFFF", "white"),
]

_TOOLS = [
    (ToolMode.POINTER,     "fa5s.mouse-pointer", "present.pointer"),
    (ToolMode.PEN,         "fa5s.pen",           "present.pen"),
    (ToolMode.HIGHLIGHTER, "fa5s.highlighter",   "present.highlighter"),
    (ToolMode.ERASER,      "fa5s.eraser",        "present.eraser"),
    (ToolMode.LASER,       "fa5s.dot-circle",    "present.laser"),
]

# FontAwesome renders the pen and highlighter with their writing tips at the
# bottom-right, which visually clashes with the mouse-pointer icon whose tip
# points up-left (standard cursor arrow convention). We apply a +90° clockwise
# rotation via QTransform (not qtawesome's ``rotated=`` kwarg) so the same
# quarter-turn behaviour survives the icon → pixmap conversion path used by
# the cursor helper in :mod:`app.viewer.annotation_layer`. That maps the
# FontAwesome bottom-right tip to the top-left corner — matching the
# mouse-pointer and making every "pointing" icon in the HUD row read as
# pointing the same way. (Pixel analysis confirms 90° — not 180° — is the
# quarter turn that maps bottom-right → top-left.)
_ICON_ROTATION: dict[str, float] = {
    "fa5s.pen": 90.0,
    "fa5s.highlighter": 90.0,
}

# 1 px black outline dilation on each side for HUD icons; the extra padding
# keeps the glyph readable against the translucent band background on both
# dark and light slides while giving qtawesome the full requested pixel
# budget (rotation is applied to a full-size render, then the outline is
# composited around it).
_HUD_OUTLINE_PAD = 2
_HUD_OUTLINE_COLOR = "#000000"
_HUD_OUTLINE_OFFSETS = (
    (-1, 0), (1, 0), (0, -1), (0, 1),
    (-1, -1), (1, 1), (-1, 1), (1, -1),
)


def _tool_qta_icon(name: str, color: str) -> QIcon:
    """Build a HUD icon with a 1 px black outline for visibility.

    Rotation is applied via :class:`QTransform` on the resulting pixmap so
    the transform is guaranteed to survive the icon → pixmap conversion
    used by the cursor helper (qtawesome's ``rotated=`` kwarg does not
    always round-trip through that path). The outline is composited by
    drawing the icon in black at 8 dilated offsets before drawing the
    fill-coloured glyph on top.

    The glyph is rendered at ``_ICON_PX - 2 * _HUD_OUTLINE_PAD`` so the
    combined glyph + outline fits exactly the ``_ICON_PX`` box configured
    on each ``QPushButton.setIconSize`` — otherwise Qt would scale the
    pixmap down and blur the outline.
    """
    rotation = _ICON_ROTATION.get(name)
    outer = _ICON_PX
    glyph = max(1, outer - _HUD_OUTLINE_PAD * 2)

    base_pix = qta.icon(name, color=color).pixmap(glyph, glyph)
    outline_pix = qta.icon(name, color=_HUD_OUTLINE_COLOR).pixmap(glyph, glyph)

    if rotation:
        t = QTransform()
        t.rotate(rotation)
        mode = Qt.TransformationMode.SmoothTransformation
        base_pix = base_pix.transformed(t, mode)
        outline_pix = outline_pix.transformed(t, mode)

    result = QPixmap(outer, outer)
    result.fill(Qt.GlobalColor.transparent)

    painter = QPainter(result)
    for dx, dy in _HUD_OUTLINE_OFFSETS:
        painter.drawPixmap(_HUD_OUTLINE_PAD + dx, _HUD_OUTLINE_PAD + dy, outline_pix)
    painter.drawPixmap(_HUD_OUTLINE_PAD, _HUD_OUTLINE_PAD, base_pix)
    painter.end()
    return QIcon(result)


class AnnotationHUD(QFrame):
    """Bottom-centred floating toolbar. Sibling of `AnnotationOverlay`,
    raised above it. Signals user intent only — never mutates the overlay
    directly; the host `PresentationWidget` owns the wiring."""

    tool_selected = Signal(int)
    color_selected = Signal(QColor)
    clear_requested = Signal()

    def __init__(self, parent: QWidget, dark_mode: bool):
        super().__init__(parent)
        self._dark_mode = bool(dark_mode)
        self._active_tool = int(ToolMode.POINTER)
        self._active_color = QColor("#EF4444")

        self.setObjectName("present_hud")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(6)

        self._tool_btns: dict[int, QPushButton] = {}
        for mode, icon_name, tip_key in _TOOLS:
            b = QPushButton(self)
            b.setCheckable(True)
            b.setFixedSize(_BTN_SIZE, _BTN_SIZE)
            b.setIconSize(QSize(_ICON_PX, _ICON_PX))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setProperty("_icon_name", icon_name)
            b.setProperty("_tip_key", tip_key)
            b.clicked.connect(lambda _checked=False, m=int(mode): self._on_tool_clicked(m))
            self._tool_btns[int(mode)] = b
            lay.addWidget(b)

        sep = QFrame(self)
        sep.setObjectName("present_hud_sep")
        sep.setFixedWidth(1)
        lay.addWidget(sep)
        self._sep = sep

        self._clear_btn = QPushButton(self)
        self._clear_btn.setFixedSize(_BTN_SIZE, _BTN_SIZE)
        self._clear_btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._clear_btn.setProperty("_icon_name", "fa5s.trash")
        self._clear_btn.setProperty("_tip_key", "present.clear")
        self._clear_btn.clicked.connect(self.clear_requested)
        lay.addWidget(self._clear_btn)

        sep2 = QFrame(self)
        sep2.setObjectName("present_hud_sep")
        sep2.setFixedWidth(1)
        lay.addWidget(sep2)
        self._sep2 = sep2

        self._swatches: list[QPushButton] = []
        for hex_color, _label in _COLORS:
            s = QPushButton(self)
            s.setFixedSize(_SWATCH_SIZE, _SWATCH_SIZE)
            s.setCursor(Qt.CursorShape.PointingHandCursor)
            s.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            s.setProperty("_swatch_color", hex_color)
            s.setToolTip(t("present.color"))
            s.clicked.connect(lambda _checked=False, c=hex_color:
                              self._on_color_clicked(QColor(c)))
            self._swatches.append(s)
            lay.addWidget(s)

        self.setFixedHeight(_HUD_HEIGHT)
        self._apply_styles()
        self._refresh_icons()
        self._refresh_active()
        self._refresh_tooltips()

    # ── public API ────────────────────────────────────────────────────────

    def set_active_tool(self, mode: int) -> None:
        self._active_tool = int(mode)
        self._refresh_active()

    def set_active_color(self, color: QColor) -> None:
        if isinstance(color, QColor):
            self._active_color = QColor(color)
        else:
            self._active_color = QColor(color)
        self._refresh_active()

    def update_theme(self, dark: bool) -> None:
        self._dark_mode = bool(dark)
        self._apply_styles()
        self._refresh_icons()
        self._refresh_active()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        w = self.sizeHint().width()
        x = max(0, (parent.width() - w) // 2)
        y = parent.height() - self.height() - 28
        self.setGeometry(x, y, w, self.height())

    # ── styling / icon refresh ────────────────────────────────────────────

    def _theme_colors(self) -> tuple[str, str, str, str]:
        if self._dark_mode:
            bg = BG_CARD
            border = BORDER
            fg = TEXT_PRI
            sec = TEXT_SEC
        else:
            bg = _LC
            border = _LO
            fg = _LP
            sec = _LQ
        return bg, border, fg, sec

    def _apply_styles(self) -> None:
        bg, border, fg, sec = self._theme_colors()
        band_bg = _rgba(BG_CARD, 225) if self._dark_mode else _rgba(_LC, 235)
        self.setStyleSheet(
            f"#present_hud {{"
            f"  background: {band_bg};"
            f"  border: 1px solid {border};"
            f"  border-radius: {_BAND_RADIUS}px;"
            f"}}"
        )
        # Per-button base styles (active styling applied in _refresh_active).
        # Hover tint derived from secondary text colour so it adapts to theme.
        hover_bg = _rgba(sec, 40)
        btn_qss = (
            f"QPushButton {{"
            f"  background: transparent;"
            f"  border: 1px solid transparent;"
            f"  border-radius: 8px;"
            f"  color: {fg};"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {hover_bg};"
            f"}}"
        )
        for b in list(self._tool_btns.values()) + [self._clear_btn]:
            b.setStyleSheet(btn_qss)

        # VLine separators paint a frame line, not a background — using
        # border-left + min-width on a plain frame paints reliably.
        sep_color = border
        for s in (self._sep, self._sep2):
            s.setStyleSheet(
                f"#present_hud_sep {{"
                f"  border: none;"
                f"  border-left: 1px solid {sep_color};"
                f"  min-width: 1px;"
                f"  max-width: 1px;"
                f"  background: transparent;"
                f"}}")

    def _refresh_icons(self) -> None:
        _bg, _border, fg, _sec = self._theme_colors()
        for b in list(self._tool_btns.values()) + [self._clear_btn]:
            name = b.property("_icon_name")
            if name:
                b.setIcon(_tool_qta_icon(name, color=fg))
        for s in self._swatches:
            hex_color = s.property("_swatch_color")
            self._style_swatch(s, hex_color, active=False)

    def _refresh_tooltips(self) -> None:
        for b in list(self._tool_btns.values()) + [self._clear_btn]:
            key = b.property("_tip_key")
            if key:
                b.setToolTip(t(key))
        for s in self._swatches:
            s.setToolTip(t("present.color"))

    def _style_swatch(self, btn: QPushButton, hex_color: str, active: bool) -> None:
        _bg, border, _fg, _sec = self._theme_colors()
        ring = ACCENT if active else border
        ring_w = 2 if active else 1
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {hex_color};"
            f"  border: {ring_w}px solid {ring};"
            f"  border-radius: {_SWATCH_SIZE // 2}px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  border: 2px solid {ACCENT};"
            f"}}"
        )

    def _refresh_active(self) -> None:
        _bg, border, fg, sec = self._theme_colors()
        active_fill = _rgba(ACCENT, 40)
        active_hover = _rgba(ACCENT, 70)
        inactive_hover = _rgba(sec, 40)
        active_qss = (
            f"QPushButton {{"
            f"  background: {active_fill};"
            f"  border: 2px solid {ACCENT};"
            f"  border-radius: 8px;"
            f"  color: {ACCENT};"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {active_hover};"
            f"}}"
        )
        inactive_qss = (
            f"QPushButton {{"
            f"  background: transparent;"
            f"  border: 1px solid transparent;"
            f"  border-radius: 8px;"
            f"  color: {fg};"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {inactive_hover};"
            f"}}"
        )
        for mode, b in self._tool_btns.items():
            is_active = (mode == self._active_tool)
            b.setChecked(is_active)
            b.setStyleSheet(active_qss if is_active else inactive_qss)
            name = b.property("_icon_name")
            if name:
                col = ACCENT if is_active else fg
                b.setIcon(_tool_qta_icon(name, color=col))
        self._clear_btn.setStyleSheet(inactive_qss)
        name = self._clear_btn.property("_icon_name")
        if name:
            self._clear_btn.setIcon(_tool_qta_icon(name, color=fg))

        active_hex = self._active_color.name().lower()
        for s in self._swatches:
            hex_color = s.property("_swatch_color") or ""
            active = hex_color.lower() == active_hex
            self._style_swatch(s, hex_color, active=active)

    # ── signal proxies ────────────────────────────────────────────────────

    def _on_tool_clicked(self, mode: int) -> None:
        self.tool_selected.emit(int(mode))

    def _on_color_clicked(self, color: QColor) -> None:
        self.color_selected.emit(QColor(color))
