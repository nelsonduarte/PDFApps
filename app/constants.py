"""PDFApps – design system constants (colours / theme)."""

import os as _os


def _snap_real_home(environ=_os.environ) -> str:
    """The user's home when running in a snap, "" otherwise.

    Inside a snap ``~`` is the private ``~/snap/<name>/<rev>``, which the
    user cannot find and which a refresh replaces.
    """
    if not environ.get("SNAP"):
        return ""
    home = environ.get("SNAP_REAL_HOME", "")
    return home if _os.path.isdir(home) else ""


def dialog_start(name: str = "") -> str:
    """Start path for a file dialog given a bare file name, or none.

    Outside a snap returns ``name`` as it is. Inside one Qt would resolve a
    bare name, or no path at all, against the working directory, and the
    snap launcher moves that into the read-only ``$SNAP``: accepting the
    suggestion then failed with EROFS.
    """
    home = _snap_real_home()
    return _os.path.join(home, name) if name else home


DESKTOP = _snap_real_home() or _os.path.join(_os.path.expanduser("~"), "Desktop")

APP_VERSION = "1.15.2"
GITHUB_REPO = "nelsonduarte/PDFApps"

ACCENT   = "#14B8A6"   # main teal
ACCENT_H = "#0D9488"   # hover
ACCENT_P = "#0F766E"   # pressed
BG_BASE  = "#0B0F12"   # global background
BG_SIDE  = "#11161A"   # sidebar
BG_CARD  = "#182127"   # cards / tool header
BG_INPUT = "#1D2A33"   # inputs
BG_INNER = "#121B22"   # scroll area
BORDER   = "#2A3944"   # borders
TEXT_PRI = "#E6F4F1"   # primary text
TEXT_SEC = "#B0C4BE"   # secondary text

# Theme-aware success green for "result" labels. Brighter shade on dark
# backgrounds, deeper shade on light — keeps contrast comfortable in both.
SUCCESS_DARK  = "#34D399"   # emerald-400 on dark bg
SUCCESS_LIGHT = "#059669"   # emerald-600 on light bg

# ── Light theme ────────────────────────────────────────────────────────────────
_LA = "#0F766E"; _LAH = "#0D9488"; _LAP = "#0F5F58"
_LB = "#F4F7F6"; _LS = "#E9EFEC"; _LC = "#FFFFFF"
_LI = "#F2F7F5"; _LN = "#ECF3F1"; _LO = "#C7D8D3"
_LP = "#1A2B28"; _LQ = "#3D5450"

# Narrowest the tool panel gets: the window enforces it (app/window.py) and
# the toast decides from it whether two buttons share a row (app/base.py).
TOOL_PANEL_MIN_WIDTH = 320
