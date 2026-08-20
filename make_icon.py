"""Draws icon.ico — the Desktop icon for the dashboard.

Run it only to regenerate the icon:  .venv\\Scripts\\python.exe make_icon.py
Needs Pillow, which is not in requirements.txt: nothing the app does at
runtime depends on this, and the .ico it produces is committed.

The design, and why:

- An ALEF, large, as the whole icon. Not a microphone: a microphone says
  "this records audio", which is true of a dozen things on any machine,
  and it says nothing about the one property that makes this app what it
  is. The letter says "Hebrew" before you have finished looking at it.
- A five-bar waveform underneath, so the letter reads as speech rather
  than as a font sample.
- The gradient runs from the app's own accent blue (#2d6cdf, the status
  dot and the dashboard's primary button) into violet, so the icon and
  the window it opens look like the same product.

A microphone-with-alef version was drawn first and lost on the only test
that matters: legibility at 24 px, which is the size you actually see all
day in the taskbar. There the mic capsule and the letter inside it merge
into one grey lozenge, while a letter that IS the icon stays sharp — a
single shape has no interior detail to lose.

Everything is drawn at 4x and downsampled with LANCZOS — Pillow has no
antialiased shape drawing, and rounded corners at 16 px are unforgiving.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

APP_DIR = Path(__file__).resolve().parent
SIZES = (16, 24, 32, 48, 64, 128, 256)
SUPER = 4                      # supersampling factor
S = 256 * SUPER

TOP_LEFT = (0x36, 0x7a, 0xf0)      # accent blue, lifted a little
BOTTOM_RIGHT = (0x7b, 0x2f, 0xe0)  # violet
GLOW = (0x5c, 0xd2, 0xff)          # the cool edge light


def gradient(size: int) -> Image.Image:
    """A diagonal blue -> violet ramp, with a soft cool glow top-left."""
    base = Image.new("RGB", (size, size))
    pixels = base.load()
    for y in range(size):
        for x in range(size):
            t = (x / size * 0.55) + (y / size * 0.45)
            pixels[x, y] = tuple(
                round(a + (b - a) * t)
                for a, b in zip(TOP_LEFT, BOTTOM_RIGHT))
    # A radial lift in the top-left corner keeps the flat ramp from
    # reading as a swatch.
    glow = Image.new("RGB", (size, size), GLOW)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse(
        (-size * 0.45, -size * 0.55, size * 0.72, size * 0.62), fill=90)
    return Image.composite(glow, base, mask.filter(_blur(size * 0.08)))


def _blur(radius: float):
    from PIL import ImageFilter
    return ImageFilter.GaussianBlur(max(1, radius))


def rounded_mask(size: int, radius_ratio: float = 0.235) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=size * radius_ratio, fill=255)
    return mask


def hebrew_font(px: int) -> ImageFont.FreeTypeFont:
    for name in ("segoeuib.ttf", "arialbd.ttf", "david.ttf"):
        try:
            font = ImageFont.truetype(f"C:/Windows/Fonts/{name}", px)
            if font.getbbox("א")[2] > 0:      # it actually has the glyph
                return font
        except OSError:
            continue
    raise SystemExit("no installed font has a Hebrew alef")


def alef_mask(size: int, height: float, centre: float) -> Image.Image:
    """The letter, centred on its INK rather than on its font metrics.

    Hebrew glyphs sit low in the em box, so placing one by the box leaves
    it visibly high on the tile — the kind of half-pixel wrongness that has
    no name but makes an icon look homemade.
    """
    mask = Image.new("L", (size, size), 0)
    font = hebrew_font(int(size * height))
    left, top, right, bottom = font.getbbox("א")
    ImageDraw.Draw(mask).text(
        (size * 0.5 - (right + left) / 2,
         size * centre - (bottom + top) / 2), "א", font=font, fill=255)
    return mask


def waveform_mask(size: int) -> Image.Image:
    """Five rounded bars, tallest in the middle, under the letter.

    They are what stops the icon reading as a font sample: the letter says
    which language, the bars say it is being spoken. Dropped below 48 px,
    where they are a one-pixel grey smudge that only muddies the tile.
    """
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    bar_w, gap = size * 0.045, size * 0.036
    heights = (0.055, 0.105, 0.150, 0.105, 0.055)
    total = len(heights) * bar_w + (len(heights) - 1) * gap
    x, base = size * 0.5 - total / 2, size * 0.795
    for h in heights:
        half = size * h / 2
        draw.rounded_rectangle((x, base - half, x + bar_w, base + half),
                               radius=bar_w / 2, fill=255)
        x += bar_w + gap
    return mask


def build(level: str = "full") -> Image.Image:
    """Two cuts of one artwork, because each is tuned to a pixel budget.

      full (>=48 px) — the letter, with the waveform beneath it.
      small (<48)    — the letter alone, grown into the room the bars leave
                       and lifted back to the centre. At 24 px the bars are
                       one grey row that reads as damage, not as sound.
    """
    detailed = level == "full"
    card = gradient(S)
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(card, (0, 0), rounded_mask(S))

    # A hairline top edge: the light source is above, and without it the
    # rounded square reads as a sticker rather than a surface.
    edge = Image.new("L", (S, S), 0)
    ImageDraw.Draw(edge).rounded_rectangle(
        (0, 0, S - 1, S - 1), radius=S * 0.235,
        outline=70, width=int(S * 0.008))
    icon.paste(Image.new("RGB", (S, S), (255, 255, 255)), (0, 0),
               edge.filter(_blur(S * 0.004)))

    white = Image.new("RGB", (S, S), (255, 255, 255))
    if detailed:
        icon.paste(white, (0, 0), alef_mask(S, height=0.50, centre=0.435))
        icon.paste(white, (0, 0), waveform_mask(S))
    else:
        icon.paste(white, (0, 0), alef_mask(S, height=0.60, centre=0.505))
    return icon


def main() -> int:
    cuts = {name: build(name) for name in ("full", "small")}
    frames = [cuts["full" if n >= 48 else "small"].resize((n, n),
                                                          Image.LANCZOS)
              for n in SIZES]
    out = APP_DIR / "icon.ico"
    frames[-1].save(out, format="ICO",
                    sizes=[(n, n) for n in SIZES], append_images=frames[:-1])
    print(f"wrote {out} ({', '.join(f'{n}x{n}' for n in SIZES)})")
    preview = APP_DIR / "icon.png"
    cuts["full"].resize((256, 256), Image.LANCZOS).save(preview)
    print(f"wrote {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
