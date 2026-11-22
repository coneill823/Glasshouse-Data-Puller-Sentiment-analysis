#!/usr/bin/env python3
"""Draw the Glasshouse app icon and write every size the three platforms need.

    python3 tool/make_icons.py        (from the mobile/ directory; needs Pillow)

The mark is a glasshouse reduced to its glazing bars: a pitched roof over four
panes. Change the constants below and run it again to restyle every icon at
once; nothing else needs editing.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BLUE = (47, 95, 168)        # the app's accent, #2F5FA8
WHITE = (255, 255, 255)
PALE = (211, 224, 244)      # quieter than white, for the line under the name
SUPERSAMPLE = 4             # drawn large and reduced, for smooth edges
ROOT = Path(__file__).resolve().parent.parent


def mark(draw: ImageDraw.ImageDraw, size: int, scale: float, colour) -> None:
    """The glasshouse, centred, in a square of `size` pixels."""
    unit = size / 1024 * scale
    cx, cy = size / 2, size / 2 + 6 * unit

    def at(x: float, y: float) -> tuple[float, float]:
        return cx + x * unit, cy + y * unit

    width = max(1, round(52 * unit))
    left, right, apex, eaves, base = -220, 220, -244, -52, 236
    transom = (eaves + base) / 2
    lines = [
        [at(left, base), at(left, eaves), at(0, apex), at(right, eaves), at(right, base), at(left, base)],
        [at(0, apex), at(0, base)],
        [at(left, eaves), at(right, eaves)],
        [at(left, transom), at(right, transom)],
    ]
    for points in lines:
        draw.line(points, fill=colour, width=width, joint="curve")
        for x, y in points:                     # round every corner and end
            r = width / 2
            draw.ellipse([x - r, y - r, x + r, y + r], fill=colour)


def render(size: int, *, scale: float, background=BLUE, radius: float = 0.0,
           inset: float = 0.0, alpha: bool = False) -> Image.Image:
    """One icon. `radius` and `inset` are fractions of the size."""
    big = size * SUPERSAMPLE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if background is not None:
        pad = inset * big
        draw.rounded_rectangle([pad, pad, big - pad, big - pad], radius=radius * big, fill=background)
    mark(draw, big, scale, WHITE)
    image = image.resize((size, size), Image.LANCZOS)
    return image if alpha else image.convert("RGB")


def feature_graphic() -> Image.Image:
    """The 1024 x 500 banner Google Play shows at the top of the listing."""
    k = SUPERSAMPLE
    image = Image.new("RGB", (1024 * k, 500 * k), BLUE)
    draw = ImageDraw.Draw(image)

    # The mark, drawn on its own square and laid on the left.
    side = 300 * k
    tile = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    mark(ImageDraw.Draw(tile), side, 1.75, WHITE)
    image.paste(tile, (84 * k, 100 * k), tile)

    fonts = ROOT / "assets" / "fonts"
    name = ImageFont.truetype(str(fonts / "Fraunces-Variable.ttf"), 112 * k)
    line = ImageFont.truetype(str(fonts / "PublicSans-Variable.ttf"), 33 * k)
    for font, axes in ((name, {"wght": 600, "opsz": 112}), (line, {"wght": 450})):
        try:                                # set the weight where the font allows it
            order = [a["name"] if isinstance(a["name"], str) else a["name"].decode()
                     for a in font.get_variation_axes()]
            tags = {"Weight": "wght", "Optical Size": "opsz"}
            defaults = [a["default"] for a in font.get_variation_axes()]
            font.set_variation_by_axes([axes.get(tags.get(n, ""), d)
                                        for n, d in zip(order, defaults)])
        except (OSError, AttributeError):
            pass
    draw.text((430 * k, 150 * k), "Glasshouse", font=name, fill=WHITE)
    draw.text((436 * k, 300 * k), "How your MP voted,", font=line, fill=PALE)
    draw.text((436 * k, 344 * k), "and how that matches your views.", font=line, fill=PALE)
    return image.resize((1024, 500), Image.LANCZOS)


def save(image: Image.Image, relative: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def main() -> None:
    # --- Android ---
    res = "android/app/src/main/res"
    for density, legacy, layer in [("mdpi", 48, 108), ("hdpi", 72, 162), ("xhdpi", 96, 216),
                                   ("xxhdpi", 144, 324), ("xxxhdpi", 192, 432)]:
        # Before Android 8: a finished icon with its own rounded shape.
        save(render(legacy, scale=1.0, radius=0.2, inset=0.04, alpha=True),
             f"{res}/mipmap-{density}/ic_launcher.png")
        # Android 8 and later: the mark alone. The launcher supplies the shape
        # and may crop to the middle two-thirds, so the mark stays inside that.
        save(render(layer, scale=0.74, background=None, alpha=True),
             f"{res}/mipmap-{density}/ic_launcher_foreground.png")

    # --- iOS: square, no transparency; the system rounds the corners ---
    ios = "ios/Runner/Assets.xcassets/AppIcon.appiconset"
    for points, scales in [(20, (1, 2, 3)), (29, (1, 2, 3)), (40, (1, 2, 3)), (60, (2, 3)),
                           (76, (1, 2)), (83.5, (2,)), (1024, (1,))]:
        for s in scales:
            name = f"{points:g}x{points:g}@{s}x"
            save(render(round(points * s), scale=1.12), f"{ios}/Icon-App-{name}.png")

    # --- web ---
    save(render(32, scale=1.12, radius=0.22, alpha=True), "web/favicon.png")
    for px in (192, 512):
        save(render(px, scale=1.12), f"web/icons/Icon-{px}.png")
        save(render(px, scale=0.9), f"web/icons/Icon-maskable-{px}.png")

    # --- shop windows ---
    save(render(512, scale=1.12), "store/play-icon-512.png")
    save(render(1024, scale=1.12), "store/app-store-icon-1024.png")
    save(feature_graphic(), "store/play-feature-graphic-1024x500.png")


if __name__ == "__main__":
    main()
