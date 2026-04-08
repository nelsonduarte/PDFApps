"""Generate the Open Graph preview image (1200x630) for pdf-apps.com."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

W, H = 1200, 630
OUT = Path(__file__).resolve().parent.parent / "docs" / "og-image.png"

BG_TOP = (15, 18, 28)
BG_BOTTOM = (28, 32, 48)
ACCENT = (46, 160, 87)         # PDFApps green
ACCENT_2 = (34, 197, 94)       # green-500 highlight
TEXT = (240, 242, 248)
MUTED = (160, 168, 192)
CARD = (24, 28, 42)
CARD_BORDER = (55, 60, 80)


def vertical_gradient(size, top, bottom):
    img = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(img)
    for y in range(size[1]):
        t = y / size[1]
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        draw.line([(0, y), (size[0], y)], fill=(r, g, b))
    return img


def load_font(size, bold=False):
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM)

    # Decorative blurred blobs (simple radial via concentric ellipses)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for i, (cx, cy, color) in enumerate([
        (160, 120, ACCENT + (40,)),
        (1050, 540, ACCENT_2 + (35,)),
    ]):
        for r in range(280, 0, -20):
            alpha = max(0, color[3] - (280 - r) // 4)
            od.ellipse(
                (cx - r, cy - r, cx + r, cy + r),
                fill=color[:3] + (alpha,),
            )
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # App logo (real icon)
    logo_path = Path(__file__).resolve().parent.parent / "docs" / "icon.png"
    badge_x, badge_y, badge_size = 80, 80, 112
    logo = Image.open(logo_path).convert("RGBA").resize((badge_size, badge_size), Image.LANCZOS)
    img_rgba = img.convert("RGBA")
    img_rgba.alpha_composite(logo, (badge_x, badge_y))
    img = img_rgba.convert("RGB")
    draw = ImageDraw.Draw(img)

    # Brand name next to logo
    brand_font = load_font(60, bold=True)
    draw.text((badge_x + badge_size + 26, badge_y + 24), "PDFApps", fill=TEXT, font=brand_font)

    # Headline
    headline_font = load_font(76, bold=True)
    sub_font = load_font(34)
    draw.text((80, 240), "The PDF editor that", fill=TEXT, font=headline_font)
    draw.text((80, 322), "respects your privacy.", fill=TEXT, font=headline_font)

    # Subtitle
    draw.text(
        (80, 430),
        "13 tools  ·  Offline  ·  Free forever  ·  Open source",
        fill=MUTED,
        font=sub_font,
    )

    # Bottom strip with platforms + URL
    strip_y = 540
    pill_font = load_font(26, bold=True)
    pills = ["Windows", "macOS", "Linux"]
    x = 80
    for label in pills:
        bbox = draw.textbbox((0, 0), label, font=pill_font)
        pw = bbox[2] - bbox[0] + 36
        ph = 48
        draw.rounded_rectangle(
            (x, strip_y, x + pw, strip_y + ph),
            radius=24,
            fill=CARD,
            outline=CARD_BORDER,
            width=2,
        )
        draw.text((x + 18, strip_y + 8), label, fill=TEXT, font=pill_font)
        x += pw + 16

    url_font = load_font(30, bold=True)
    url = "pdf-apps.com"
    bbox = draw.textbbox((0, 0), url, font=url_font)
    draw.text(
        (W - 80 - (bbox[2] - bbox[0]), strip_y + 10),
        url,
        fill=ACCENT,
        font=url_font,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
