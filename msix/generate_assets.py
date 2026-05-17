"""Generate the MSIX visual assets (Store logo, tiles, splash screen)
from the project's icon_512.png and pdfapps.svg.

Microsoft Store / sideload requires PNGs at specific resolutions.
This script produces them all from the existing 512×512 master so
the package only carries ONE source-of-truth icon.

Usage (from project root):
    py msix/generate_assets.py

Output: msix/Assets/*.png at the resolutions listed below.
"""
import os
import sys

try:
    from PIL import Image
except ImportError:
    print("error: Pillow required (`pip install pillow`).")
    sys.exit(1)


# (filename, width, height, use_svg_renderer)
TARGETS = [
    ("Square44x44Logo.png",   44,  44,  False),
    ("Square71x71Logo.png",   71,  71,  False),
    ("Square150x150Logo.png", 150, 150, False),
    ("Square310x310Logo.png", 310, 310, False),
    ("Wide310x150Logo.png",   310, 150, False),
    ("StoreLogo.png",         50,  50,  False),
    ("SplashScreen.png",      620, 300, False),
]

# Target-size variants of Square44x44Logo. Windows shell picks the best
# match for each rendering context: small (16) for tooltip/treeview,
# 24-40 for list view, 48 for medium desktop icons, 96 for large desktop
# icons, 256 for extra-large/jumbo desktop icons. Without these, Windows
# stretches the 44×44 base PNG, which looks pixelated at 256×256 — the
# default desktop "Large icons" size for PDF file association icons.
TARGETSIZE_VARIANTS = [16, 24, 32, 48, 96, 256]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(here)
    src = os.path.join(project_root, "icon_512.png")
    if not os.path.isfile(src):
        print(f"error: {src} not found")
        sys.exit(2)

    assets_dir = os.path.join(here, "Assets")
    os.makedirs(assets_dir, exist_ok=True)

    master = Image.open(src).convert("RGBA")

    for name, w, h, _ in TARGETS:
        out = os.path.join(assets_dir, name)
        if w == h:
            # Square — fit master, pad transparent if needed (master is
            # already square so this is a straight resize).
            img = master.resize((w, h), Image.LANCZOS)
        else:
            # Wide / splash — center the master on a transparent canvas.
            canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            inner = min(w, h)
            scaled = master.resize((inner, inner), Image.LANCZOS)
            canvas.paste(scaled, ((w - inner) // 2, (h - inner) // 2),
                         scaled)
            img = canvas
        img.save(out, "PNG", optimize=True)
        print(f"wrote {os.path.relpath(out, project_root)} ({w}x{h})")

    # Generate Square44x44Logo.targetsize-N.png variants so Windows can
    # render the PDF file association icon at the right resolution on
    # desktop and in Explorer instead of stretching the 44×44 base.
    for size in TARGETSIZE_VARIANTS:
        name = f"Square44x44Logo.targetsize-{size}.png"
        out = os.path.join(assets_dir, name)
        img = master.resize((size, size), Image.LANCZOS)
        img.save(out, "PNG", optimize=True)
        print(f"wrote {os.path.relpath(out, project_root)} ({size}x{size})")

    total = len(TARGETS) + len(TARGETSIZE_VARIANTS)
    print(f"\n[OK] {total} MSIX assets generated in {assets_dir}")


if __name__ == "__main__":
    main()
