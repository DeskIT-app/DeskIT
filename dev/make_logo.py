"""The DeskIT logo, drawn once, for every icon this repo needs.

The mark is **Corner**, chosen 2026-09-23: one rounded corner cut flat at
both ends, with the dot at the exact centre of its curve. In the mark's
own 64-unit grid it is the path the SVG states —

    M10 14  H30  A20 20 0 0 1 50 34  V54      stroke 8, butt caps
    circle  cx 30  cy 34  r 10

**Why this file draws the stroke as an AREA and not as three strokes.**
The first icon drew it with Pillow's `line`, `arc`, `line` — and the two
joins broke: a thick `arc` is rasterised as concentric circles whose ends
do not line up with a thick `line`'s butt cap, so each join had a notch in
it. He saw both of them at a glance and circled them (2026-09-24). The
stroke is one filled region here:

    the annulus  r 16..24  around (30, 34), kept to the quadrant x>=30, y<=34
    the flat top      x 10..30,  y 10..18
    the flat side     x 46..54,  y 34..54

and the numbers meet by construction — the annulus ends exactly at
y 10..18 where the top leg begins, and exactly at x 46..54 where the side
leg begins. There is nothing left to align, at any size.

    .venv\\Scripts\\python.exe dev\\make_logo.py            # both icons
    .venv\\Scripts\\python.exe dev\\make_logo.py --preview out.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
APP_ICO = REPO / "icon.ico"                      # the app's own icon
#: the master's icon. The NAME matters: Windows caches a desktop icon
#: by the path of the .ico, and neither ie4uinit nor deleting
#: iconcache*.db nor rebuilding the shortcut freed the large sizes
#: once "master.ico" was in that cache (2026-09-24, four rounds of
#: "it still looks broken"). A file the cache has never seen is read
#: fresh — so if this is ever redrawn and Windows keeps the old
#: picture, give it a new name here and re-point the shortcut.
MASTER_ICO = REPO / "dev" / "master" / "DeskIT-Master.ico"

#: the app's ground: LAMPLIGHT's graphite, the colour its icon has always had
APP_TOP, APP_BOT = (46, 44, 40), (22, 21, 19)
#: the master's ground: skin/palette's night, so the two are never confused
MASTER_TOP, MASTER_BOT = (42, 49, 96), (20, 26, 44)

RIM = (160, 165, 215, 70)
INK = (239, 237, 247, 255)          # --ink, the mark itself
APP_LAMP = (232, 178, 70, 255)      # the app's light: LAMPLIGHT gold
MASTER_LAMP = (201, 192, 255, 255)  # --mark-lamp, the master's lavender
WORD = (194, 185, 255, 255)         # --iris-text

BIG = 2048                          # drawn here, resized down with LANCZOS
WITH_WORD = 64                      # sizes below this get the mark alone
SIZES = (16, 24, 32, 48, 64, 128, 256)


# ----------------------------------------------------------------- the mark

def mark(size: int, *, ink=INK, lamp=MASTER_LAMP, scale: float = 1.0,
         lift: float = 0.0) -> Image.Image:
    """The Corner, as one filled area. `scale` is of the whole 64-unit
    grid; `lift` moves it up by that fraction of the canvas."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    u = size / 64 * scale
    dx = (size - 64 * u) / 2
    dy = (size - 64 * u) / 2 - lift * size

    def at(x, y):
        return (dx + x * u, dy + y * u)

    def box(x0, y0, x1, y1):
        return [*at(x0, y0), *at(x1, y1)]

    # the turn: the ring between r16 and r24 around (30, 34)…
    ring = Image.new("L", (size, size), 0)
    r = ImageDraw.Draw(ring)
    r.ellipse(box(30 - 24, 34 - 24, 30 + 24, 34 + 24), fill=255)
    r.ellipse(box(30 - 16, 34 - 16, 30 + 16, 34 + 16), fill=0)
    # …kept to the quadrant the path turns through (x >= 30, y <= 34)
    r.rectangle(box(-2, -2, 30, 66), fill=0)
    r.rectangle(box(-2, 34, 66, 66), fill=0)

    stroke = Image.new("L", (size, size), 0)
    s = ImageDraw.Draw(stroke)
    s.rectangle(box(10, 10, 30, 18), fill=255)      # the flat top
    s.rectangle(box(46, 34, 54, 54), fill=255)      # the flat side
    stroke.paste(ring, (0, 0), ring)

    layer.paste(Image.new("RGBA", (size, size), ink), (0, 0), stroke)
    cx, cy = at(30, 34)
    rr = 10 * u
    d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=lamp)
    return layer


def ground(size: int, top, bot) -> Image.Image:
    """The rounded tile, lit from the top, with a hair of a rim."""
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGBA", (1, size))
    for y in range(size):
        k = y / max(1, size - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * k) for a, b in zip(top, bot)) + (255,))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1),
                                           radius=round(size * 14 / 64), fill=255)
    tile.paste(grad.resize((size, size)), (0, 0), mask)
    edge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(
        (size * 0.012, size * 0.012, size - size * 0.012, size - size * 0.012),
        radius=round(size * 13 / 64), outline=RIM, width=max(1, round(size / 220)))
    return Image.alpha_composite(tile, edge)


def word(size: int, text: str = "MASTER", fill=WORD) -> Image.Image:
    """The word, letter-spaced, under the mark."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    font = _face(round(size * 0.108))
    gap = round(size * 0.022)
    widths = [_w(font, ch) for ch in text]
    x = (size - (sum(widths) + gap * (len(text) - 1))) / 2
    d = ImageDraw.Draw(layer)
    for ch, w in zip(text, widths):
        d.text((x, size * 0.735), ch, font=font, fill=fill)
        x += w + gap
    return layer


def _face(px: int) -> ImageFont.FreeTypeFont:
    """Rubik at its heavy end. The four files in fonts\\ are ONE variable
    font (AGENTS): asking for RubikBold.ttf and expecting Bold gets Light,
    so the weight axis is pinned."""
    font = ImageFont.truetype(str(REPO / "fonts" / "Rubik.ttf"), px)
    try:
        font.set_variation_by_axes([700])
    except Exception:                    # noqa: BLE001 — a static build is fine too
        pass
    return font


def _w(font, ch: str) -> int:
    b = font.getbbox(ch)
    return b[2] - b[0] + round(font.size * 0.08)


# ---------------------------------------------------------------- the icons

def tile(size: int, *, master: bool, with_word: bool) -> Image.Image:
    top, bot = (MASTER_TOP, MASTER_BOT) if master else (APP_TOP, APP_BOT)
    lamp = MASTER_LAMP if master else APP_LAMP
    big = ground(BIG, top, bot)
    big = Image.alpha_composite(big, mark(BIG, lamp=lamp,
                                          scale=0.80 if with_word else 0.94,
                                          lift=0.085 if with_word else 0.0))
    if with_word:
        big = Image.alpha_composite(big, word(BIG))
    return big.resize((size, size), Image.LANCZOS)


def build(path: Path, *, master: bool) -> Path:
    frames = [tile(n, master=master, with_word=master and n >= WITH_WORD)
              for n in SIZES]
    frames[-1].save(path, format="ICO", sizes=[(n, n) for n in SIZES],
                    append_images=frames[:-1])
    return path


def preview(path: Path) -> Path:
    """Both icons, every size, on the grey a desktop shows them on."""
    pad, back = 18, (58, 58, 62, 255)
    rows = [[tile(n, master=m, with_word=m and n >= WITH_WORD) for n in SIZES]
            for m in (False, True)]
    width = sum(SIZES) + pad * (len(SIZES) + 1)
    sheet = Image.new("RGBA", (width, (256 + pad) * 2 + pad), back)
    for r, row in enumerate(rows):
        x = pad
        for n, im in zip(SIZES, row):
            sheet.paste(im, (x, pad + r * (256 + pad) + (256 - n) // 2), im)
            x += n + pad
    sheet.save(path)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="draw icon.ico and dev\\master\\master.ico")
    ap.add_argument("--preview", help="also write a strip of both icons here")
    ap.add_argument("--app-only", action="store_true")
    ap.add_argument("--master-only", action="store_true")
    ns = ap.parse_args()
    if not ns.master_only:
        print(build(APP_ICO, master=False))
    if not ns.app_only:
        print(build(MASTER_ICO, master=True))
    if ns.preview:
        print(preview(Path(ns.preview)))
