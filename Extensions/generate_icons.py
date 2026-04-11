"""
Generates simple PNG icons for the extension.
Run once: python generate_icons.py
"""
from PIL import Image, ImageDraw
import os

os.makedirs("icons", exist_ok=True)

def make_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background circle
    margin = size // 8
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(124, 106, 247, 255),
    )

    # Magnifying glass
    cx, cy = size // 2, size // 2 - size // 12
    r = size // 4
    stroke = max(1, size // 16)

    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        outline=(255, 255, 255, 230),
        width=stroke,
    )

    # Handle
    handle_start = int(cx + r * 0.7), int(cy + r * 0.7)
    handle_end   = int(cx + r * 1.6), int(cy + r * 1.6)
    draw.line([handle_start, handle_end], fill=(255, 255, 255, 230), width=stroke)

    img.save(f"icons/icon{size}.png")
    print(f"Generated icons/icon{size}.png")

for s in [16, 48, 128]:
    make_icon(s)

print("Done — icons generated in icons/ folder")
