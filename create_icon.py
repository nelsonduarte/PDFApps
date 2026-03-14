"""Generate icon.ico for PDForge using Pillow with supersampling for crisp quality."""
from PIL import Image, ImageDraw


def create_icon(size):
    # Render at 4x and downscale for anti-aliasing quality
    S = size * 4
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded background (#1A237E dark blue)
    r = int(S * 0.18)
    draw.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=(26, 35, 126, 255))

    # Document shape (white/light)
    pad  = int(S * 0.16)
    dw   = int(S * 0.52)
    dh   = int(S * 0.64)
    dx   = (S - dw) // 2
    dy   = int(S * 0.1)
    fold = int(dw * 0.30)

    body = [
        (dx,             dy),
        (dx + dw - fold, dy),
        (dx + dw,        dy + fold),
        (dx + dw,        dy + dh),
        (dx,             dy + dh),
    ]
    draw.polygon(body, fill=(240, 244, 255, 255))

    # Folded corner (slightly darker)
    fold_tri = [
        (dx + dw - fold, dy),
        (dx + dw,        dy + fold),
        (dx + dw - fold, dy + fold),
    ]
    draw.polygon(fold_tri, fill=(180, 195, 230, 255))

    # Red "PDF" bar
    bx1 = dx
    bx2 = dx + dw
    by1 = dy + int(dh * 0.37)
    by2 = by1 + int(dh * 0.22)
    draw.rectangle([bx1, by1, bx2, by2], fill=(229, 57, 53, 255))

    # Thin text lines below bar
    lx1 = dx + int(S * 0.04)
    lx2 = dx + dw - int(S * 0.04)
    lh  = max(1, int(S * 0.025))
    for i in range(2):
        ly = by2 + int(dh * 0.12) + i * int(dh * 0.15)
        draw.rectangle([lx1, ly, lx2, ly + lh], fill=(120, 140, 180, 200))

    # Flame / forge spark (bottom-right)
    fcx = dx + dw + int(S * 0.0)
    fcy = dy + dh - int(S * 0.01)
    fr  = int(S * 0.13)
    draw.ellipse([fcx - fr, fcy - fr, fcx + fr, fcy + fr], fill=(245, 158, 11, 255))
    ir  = int(S * 0.07)
    draw.ellipse([fcx - ir, fcy - ir, fcx + ir, fcy + ir], fill=(254, 224, 64, 255))

    # Downscale with LANCZOS for crisp result
    img = img.resize((size, size), Image.LANCZOS)
    return img


sizes = [16, 32, 48, 64, 128, 256]

# Render the largest size and let Pillow resize down for ICO
# (also pre-renders each size for a combined approach)
base = create_icon(256)
base.save(
    "icon.ico",
    format="ICO",
    sizes=[(s, s) for s in sizes],
)
print("icon.ico created successfully (PDForge)")
