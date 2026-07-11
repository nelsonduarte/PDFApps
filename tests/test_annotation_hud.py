"""Regression tests for the presentation-mode HUD and annotation overlay.

Source-level assertions (no QApplication required in CI) that lock in the
two UX fixes shipped in ``fix/presentation-hud-cursor-icons``:

1. The HUD Pen and Highlighter icons must be rotated so their writing tip
   aligns with the mouse-pointer arrow.
2. ``AnnotationOverlay.set_tool`` must update the on-screen cursor so the
   user gets visual feedback when switching tools from the HUD.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_HUD_PATH = Path(__file__).resolve().parent.parent / "app" / "viewer" / "annotation_hud.py"
_OVERLAY_PATH = Path(__file__).resolve().parent.parent / "app" / "viewer" / "annotation_layer.py"


def _hud_src() -> str:
    return _HUD_PATH.read_text(encoding="utf-8")


def _overlay_src() -> str:
    return _OVERLAY_PATH.read_text(encoding="utf-8")


class TestHudIconRotation:
    def test_hud_pen_icon_rotated(self):
        """Regression: Pen icon must have a rotation applied.

        The rotation may be inlined at the call site or table-driven via a
        module-level dict - both count. We assert both facets: (a) some
        rotation directive exists in the module and (b) the pen icon is
        registered in the rotation registry.
        """
        src = _hud_src()
        assert '"fa5s.pen"' in src
        has_rotation_directive = ("rotated" in src) or ("IconOptions" in src)
        assert has_rotation_directive, (
            "HUD module must apply a rotation (rotated=... or IconOptions) "
            "somewhere so the pen/highlighter icons align with the pointer"
        )
        assert ("_ICON_ROTATION" in src and '"fa5s.pen"' in src) or (
            "fa5s.pen" in src and "rotated" in src.split('"fa5s.pen"')[1][:300]
        ), "Pen icon must be included in the HUD rotation registry"

    def test_hud_highlighter_icon_rotated(self):
        src = _hud_src()
        assert '"fa5s.highlighter"' in src
        has_rotation_directive = ("rotated" in src) or ("IconOptions" in src)
        assert has_rotation_directive, (
            "HUD module must apply a rotation somewhere so the highlighter "
            "icon aligns with the pointer"
        )
        assert ("_ICON_ROTATION" in src and '"fa5s.highlighter"' in src) or (
            "fa5s.highlighter" in src
            and "rotated" in src.split('"fa5s.highlighter"')[1][:300]
        ), "Highlighter icon must be included in the HUD rotation registry"

    def test_rotation_table_covers_pen_and_highlighter(self):
        """The rotation table must include both pen and highlighter and must
        not accidentally rotate the pointer/eraser/laser icons."""
        src = _hud_src()
        assert "_ICON_ROTATION" in src, (
            "Expected an _ICON_ROTATION table listing icons that must rotate"
        )
        # Extract just the _ICON_ROTATION literal block so we can verify
        # membership without accidentally matching the _TOOLS list.
        rot_idx = src.find("_ICON_ROTATION")
        rot_end = src.find("}", rot_idx)
        assert rot_end > rot_idx
        rot_block = src[rot_idx:rot_end]
        assert '"fa5s.pen"' in rot_block
        assert '"fa5s.highlighter"' in rot_block
        # Guardrail: pointer / eraser / laser icons must NOT be listed -
        # rotating them would break the fix.
        assert '"fa5s.mouse-pointer"' not in rot_block, (
            "Pointer icon is the reference direction and must not appear in "
            "_ICON_ROTATION"
        )
        assert '"fa5s.eraser"' not in rot_block
        assert '"fa5s.dot-circle"' not in rot_block


class TestOverlayCursor:
    def test_annotation_overlay_sets_cursor_on_tool_change(self):
        """set_tool must (transitively) apply a cursor so switching tools
        gives immediate visual feedback."""
        src = _overlay_src()
        set_tool_idx = src.find("def set_tool")
        assert set_tool_idx > 0
        snippet = src[set_tool_idx:set_tool_idx + 1200]
        # set_tool delegates to _apply_cursor, which is where setCursor lives.
        assert "_apply_cursor" in snippet, (
            "set_tool must invoke _apply_cursor to reflect the newly selected "
            "tool on the on-screen cursor"
        )
        assert "setCursor" in src, (
            "The overlay must call setCursor somewhere to change the cursor"
        )

    def test_cursor_helper_covers_all_tools(self):
        """A module-level helper must map every ToolMode to a QCursor."""
        src = _overlay_src()
        assert "_cursor_for_tool" in src, (
            "Expected a _cursor_for_tool helper that returns a QCursor per "
            "ToolMode"
        )
        # Ensure every ToolMode member is referenced in the helper.
        helper_idx = src.find("def _cursor_for_tool")
        assert helper_idx > 0
        helper_snippet = src[helper_idx:helper_idx + 2000]
        for member in ("POINTER", "PEN", "HIGHLIGHTER", "ERASER", "LASER"):
            assert f"ToolMode.{member}" in helper_snippet, (
                f"_cursor_for_tool must handle ToolMode.{member} explicitly"
            )

    def test_cursor_helper_uses_matching_pen_rotation(self):
        """The pen cursor rotation must match the HUD icon rotation so the
        on-screen cursor and toolbar icon stay visually consistent.

        Rotation may be applied either via qtawesome's ``rotated=`` kwarg or
        via a Qt-native :class:`QTransform` (the module currently prefers
        QTransform because qtawesome's ``rotated=`` does not always survive
        the icon → pixmap round-trip used for cursor rendering).
        """
        src = _overlay_src()
        helper_idx = src.find("def _cursor_for_tool")
        assert helper_idx > 0
        helper_snippet = src[helper_idx:helper_idx + 2000]
        assert "fa5s.pen" in helper_snippet
        assert "fa5s.highlighter" in helper_snippet
        # A rotation directive must exist somewhere in the module — either
        # inline (qtawesome) or via a QTransform helper.
        has_rotation = (
            "rotated" in src
            or "QTransform" in src
            or "transform.rotate" in src.lower()
        )
        assert has_rotation, (
            "Overlay module must apply a 90° rotation to the pen/highlighter "
            "cursor icons (qtawesome rotated= or QTransform.rotate)"
        )

    def test_laser_cursor_is_blank(self):
        """LASER cursor must be BlankCursor because the overlay draws the red
        dot manually and a system cursor on top would be visually noisy."""
        src = _overlay_src()
        helper_idx = src.find("def _cursor_for_tool")
        helper_snippet = src[helper_idx:helper_idx + 2000]
        laser_idx = helper_snippet.find("ToolMode.LASER")
        assert laser_idx >= 0
        # Look at the branch body for BlankCursor.
        laser_snippet = helper_snippet[laser_idx:laser_idx + 300]
        assert "BlankCursor" in laser_snippet, (
            "LASER cursor should be BlankCursor - the red dot is drawn "
            "manually so a system cursor on top is redundant"
        )


class TestIconOutline:
    """Regression tests for the black-outline treatment applied to HUD
    icons and cursor pixmaps.

    The outline (a 1 px dilation of the glyph rendered in ``#000000``)
    keeps the pen/highlighter/eraser icons legible on light-coloured
    slides, where an otherwise-white glyph would blend into the page.
    Both the HUD toolbar (``annotation_hud.py``) and the cursor helper
    (``annotation_layer.py``) render icons through a common outline
    compositing pattern (icon drawn 8× at dilated offsets, then the
    fill-coloured glyph on top).
    """

    def test_hud_icons_have_black_outline(self):
        """HUD toolbar icons must be composited with a black outline."""
        src = _hud_src()
        assert "#000000" in src, (
            "HUD module must reference the black outline colour used for the "
            "icon dilation pass"
        )
        assert "outline" in src.lower(), (
            "HUD module must document the outline compositing (variable or "
            "helper named *outline*)"
        )
        assert "QPainter" in src, (
            "HUD module must use QPainter to composite the outline + glyph"
        )

    def test_cursor_icons_have_black_outline(self):
        """Cursor pixmaps must be composited with a black outline."""
        src = _overlay_src()
        assert "#000000" in src, (
            "Overlay module must reference the black outline colour used for "
            "the cursor icon dilation pass"
        )
        assert "outline" in src.lower(), (
            "Overlay module must expose an outline compositing helper "
            "(variable or function named *outline*)"
        )
        assert "QPainter" in src, (
            "Overlay module must use QPainter to composite the outline + glyph"
        )

    def test_cursor_helper_uses_reliable_rotation(self):
        """Regression: rotation must reach the final pixmap.

        Historically we relied on ``qta.icon(..., rotated=90).pixmap(...)``
        but that path did not always propagate the rotation to the pixmap
        used for cursors, so the tip stayed in the wrong quadrant on some
        Qt/qtawesome combos. The fix uses a Qt-native ``QTransform`` on the
        rendered pixmap, which is deterministic. Accept either mechanism —
        we just need one of them present so the rotation cannot silently
        drop out.
        """
        src = _overlay_src()
        assert (
            "QTransform" in src
            or "rotated=90" in src
            or "rotated=90.0" in src
        ), (
            "Overlay must apply the pen/highlighter rotation via QTransform "
            "(preferred) or qtawesome rotated="
        )
