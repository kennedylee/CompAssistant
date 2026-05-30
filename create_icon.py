"""Generates icon.ico — run once before building."""
from pathlib import Path
from PIL import Image, ImageDraw


def make_frame(size: int) -> Image.Image:
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    BG     = (13,  17,  23,  255)   # #0d1117
    ACCENT = (88, 166, 255, 255)    # #58a6ff

    # Rounded background square
    r = max(2, size // 6)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG)

    if size <= 24:
        # Simplified: two dots (eyes) + a line (mouth)
        cx, cy = size // 2, size // 2
        dot = max(1, size // 8)
        lw  = max(1, size // 12)
        draw.ellipse([cx - size//4 - dot, cy - dot, cx - size//4 + dot, cy + dot], fill=ACCENT)
        draw.ellipse([cx + size//4 - dot, cy - dot, cx + size//4 + dot, cy + dot], fill=ACCENT)
        draw.line([cx - size//4, cy + size//4, cx + size//4, cy + size//4], fill=ACCENT, width=lw)
    else:
        m  = size // 7
        lw = max(1, size // 28)

        # Head outline
        draw.rounded_rectangle(
            [m, int(m * 1.6), size - m, size - m],
            radius=max(2, size // 10), outline=ACCENT, width=lw,
        )

        # Eyes
        ey = int(size * 0.46)
        er = max(2, size // 11)
        draw.ellipse([int(size * 0.30) - er, ey - er, int(size * 0.30) + er, ey + er], fill=ACCENT)
        draw.ellipse([int(size * 0.70) - er, ey - er, int(size * 0.70) + er, ey + er], fill=ACCENT)

        # Mouth
        cx = size // 2
        mw = int(size * 0.28)
        mh = max(1, size // 22)
        my = int(size * 0.68)
        draw.rounded_rectangle([cx - mw, my - mh, cx + mw, my + mh], radius=mh, fill=ACCENT)

        # Antenna stem + ball
        draw.line([cx, int(m * 1.6), cx, m], fill=ACCENT, width=lw)
        ab = max(2, size // 16)
        draw.ellipse([cx - ab, m - ab, cx + ab, m + ab], fill=ACCENT)

    return img


sizes  = [16, 32, 48, 64, 128, 256]
frames = [make_frame(s) for s in sizes]
out    = Path(__file__).parent / "icon.ico"
frames[0].save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=frames[1:])
print(f"Created {out}")
