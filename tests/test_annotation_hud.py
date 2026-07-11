"""Regression tests for the presentation-mode annotation overlay.

Source-level assertions (no QApplication required in CI) that lock in the
tool-specific cursor behaviour added by ``fix/presentation-hud-cursor-icons``.
Additional HUD-icon rotation tests live below once the HUD fix is applied.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_OVERLAY_PATH = Path(__file__).resolve().parent.parent / "app" / "viewer" / "annotation_layer.py"


def _overlay_src() -> str:
    return _OVERLAY_PATH.read_text(encoding="utf-8")


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
        on-screen cursor and toolbar icon stay visually consistent."""
        src = _overlay_src()
        helper_idx = src.find("def _cursor_for_tool")
        assert helper_idx > 0
        helper_snippet = src[helper_idx:helper_idx + 2000]
        # Pen and highlighter should be rendered rotated in the cursor helper
        # (same rotation the HUD uses so the metaphor is consistent).
        assert "fa5s.pen" in helper_snippet and "rotated" in helper_snippet
        assert "fa5s.highlighter" in helper_snippet

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
