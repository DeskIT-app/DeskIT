"""Draw the master app's icon: the locked mark, the night ground, the word.

The mark is "Corner" (chosen 2026-09-23): one rounded corner cut flat at
both ends, with the dot at the exact centre of its curve. The ground is
the master's own night indigo, so the icon is a sibling of DeskIT's and
never mistaken for it at 32 px — the app's is graphite with a gold lamp.

**The word is drawn only where it can be read.** "MASTER" at 32 px is
four grey pixels, so the small sizes carry the mark alone and the large
ones carry the word under it; Windows picks the size it needs out of the
same .ico. Everything is drawn at 1024 and resized down with LANCZOS,
which is how every other drawn thing in this repo gets its edges.

    .venv\\Scripts\\python.exe dev\\master\\make_icon.py [--preview out.png]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
ICO = HERE / "master.ico"

#: skin/palette.py's night, and the bar's own mark tile
TOP = (42, 49, 96)          # #2a3160
BOT = (20, 26, 44)          # #141a2c
RIM = (160, 165, 215, 70)
INK = (239, 237, 247, 255)  # --ink
LAMP = (201, 192, 255, 255)  # --mark-lamp
WORD = (194, 185, 255, 255)  # --iris-text

BIG = 1024
WITH_WORD = 64              # sizes below this get the mark alone
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _ground(size: int) -> Image.Image:
    """The rounded tile, lit from the top."""
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGBA", (1, size))
    for y in range(size):
        k = y / max(1, size - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * k) for a, b in zip(TOP, BOT)) + (255,))
    grad = grad.resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1),
                                           radius=round(size * 14 / 64), fill=255)
    tile.paste(grad, (0, 0), mask)
    edge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(
        (size * 0.012, size * 0.012, size - size * 0.012, size - size * 0.012),
        radius=round(size * 13 / 64), outline=RIM, width=max(1, round(size / 220)))
    return Image.alpha_composite(tile, edge)


def _mark(size: int, scale: float, lift: float) -> Image.Image:
    """The Corner: M10 14 H30 A20 20 0 0 1 50 34 V54, stroke 8, in 64 units."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    u = size / 64 * scale                       # one unit of the mark's own grid
    dx = (size - 64 * u) / 2
    dy = (size - 64 * u) / 2 - lift * size

    def at(x, y):
        return (dx + x * u, dy + y * u)

    w = round(8 * u)
    d.line([at(10, 14), at(30, 14)], fill=INK, width=w)          # the flat top
    box = [*at(10, 14), *at(50, 54)]                             # the arc's square
    d.arc(box, start=270, end=360, fill=INK, width=w)            # the turn
    d.line([at(50, 34), at(50, 54)], fill=INK, width=w)          # the flat side
    r = 10 * u
    cx, cy = at(30, 34)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=LAMP)       # the light
    return layer


def _word(size: int, text: str = "MASTER") -> Image.Image:
    """The word, letter-spaced, under the mark."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    font = _face(round(size * 0.108))
    gap = round(size * 0.022)
    widths = [_w(font, ch) for ch in text]
    total = sum(widths) + gap * (len(text) - 1)
    x = (size - total) / 2
    y = size * 0.735
    d = ImageDraw.Draw(layer)
    for ch, w in zip(text, widths):
        d.text((x, y), ch, font=font, fill=WORD)
        x += w + gap
    return layer


def _face(px: int) -> ImageFont.FreeTypeFont:
    """Rubik at its heavy end. The four files in fonts\\ are ONE variable
    font (AGENTS): asking for RubikBold.ttf and expecting Bold gets
    Light, so the weight axis is pinned here."""
    font = ImageFont.truetype(str(REPO / "fonts" / "Rubik.ttf"), px)
    try:
        font.set_variation_by_axes([700])
    except Exception:                            # noqa: BLE001 — a static build is fine too
        pass
    return font


def _w(font, ch: str) -> int:
    box = font.getbbox(ch)
    return box[2] - box[0] + round(font.size * 0.08)


def draw(size: int, word: bool) -> Image.Image:
    big = _ground(BIG)
    big = Image.alpha_composite(big, _mark(BIG, 0.80 if word else 0.94,
                                           0.085 if word else 0.0))
    if word:
        big = Image.alpha_composite(big, _word(BIG))
    return big.resize((size, size), Image.LANCZOS)


def build(path: Path = ICO) -> Path:
    frames = [draw(n, word=n >= WITH_WORD) for n in SIZES]
    frames[-1].save(path, format="ICO", sizes=[(n, n) for n in SIZES],
                    append_images=frames[:-1])
    return path


def preview(path: Path) -> Path:
    """Every size on one strip, each on the grey a desktop shows it on."""
    pad, back = 18, (58, 58, 62, 255)
    shown = [(n, draw(n, word=n >= WITH_WORD)) for n in SIZES]
    width = sum(n for n, _ in shown) + pad * (len(shown) + 1)
    sheet = Image.new("RGBA", (width, 256 + pad * 2), back)
    x = pad
    for n, im in shown:
        sheet.paste(im, (x, pad + (256 - n) // 2), im)
        x += n + pad
    sheet.save(path)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="draw dev\\master\\master.ico")
    ap.add_argument("--preview", help="also write a strip of every size here")
    ns = ap.parse_args()
    print(build())
    if ns.preview:
        print(preview(Path(ns.preview)))
