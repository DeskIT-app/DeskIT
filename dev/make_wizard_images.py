"""The installer's two pictures, drawn from icon.png and the app's Rubik.

Inno Setup shows `WizardImageFile` down the side of the Welcome and
Finished pages and `WizardSmallImageFile` in the header of every other
page, and picks, from a comma-separated list, the file whose size best
fits the screen's DPI. The sizes below are the ones its documentation
lists. BMPs are generated at build time (release.yml, before ISCC) and
by packaging/build_local.ps1 — never committed: 1.7 MB of bitmaps for a
picture that is three lines of drawing.

    python dev/make_wizard_images.py --out packaging/wizard --version 1.1.0
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"

BG = (0x14, 0x11, 0x0C)          # the wizard's warm graphite (firstrun.py)
FG = (0xEC, 0xE5, 0xD8)
DIM = (0xA8, 0x9E, 0x8C)
FAINT = (0x6F, 0x66, 0x57)
GOLD = (0xE3, 0xA6, 0x3C)

#: (width, height) per Inno's list: 100 %, 125 %, 150 %, 175 %, 200 %
SIDE_SIZES = [(164, 314), (192, 386), (246, 459), (273, 556), (328, 604)]
SMALL_SIZES = [55, 64, 83, 92, 110, 119, 138]


def side(width: int, height: int, version: str, icon: Image.Image) -> Image.Image:
    k = height / 314                                   # everything scales with the 100 % panel
    im = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(im)
    tile = icon.resize((round(84 * k), round(84 * k)), Image.LANCZOS)
    im.paste(tile, ((width - tile.width) // 2, round(56 * k)), tile)
    name = ImageFont.truetype(str(FONTS / "RubikMedium.ttf"), round(28 * k))
    small = ImageFont.truetype(str(FONTS / "Rubik.ttf"), round(12.5 * k))
    d.text((width / 2, round(172 * k)), "DeskIT", font=name, fill=FG, anchor="mm")
    d.rectangle([width / 2 - 14 * k, round(194 * k), width / 2 + 14 * k, round(194 * k) + max(1, round(1.5 * k))], fill=GOLD)
    d.text((width / 2, round(214 * k)), "Hebrew dictation", font=small, fill=DIM, anchor="mm")
    d.text((width / 2, round(231 * k)), "for Windows", font=small, fill=DIM, anchor="mm")
    d.text((width / 2, height - round(18 * k)), version, font=small, fill=FAINT, anchor="mm")
    return im


def small(size: int, icon: Image.Image) -> Image.Image:
    im = Image.new("RGB", (size, size), (255, 255, 255))   # the header strip is white
    tile = icon.resize((size, size), Image.LANCZOS)
    im.paste(tile, (0, 0), tile)
    return im


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "packaging" / "wizard")
    ap.add_argument("--version", default=(ROOT / "VERSION").read_text("utf-8").strip())
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    icon = Image.open(ROOT / "icon.png").convert("RGBA")
    names = []
    for w, h in SIDE_SIZES:
        p = a.out / f"side-{h}.bmp"
        side(w, h, a.version, icon).save(p, "BMP")
        names.append(p.name)
    for s in SMALL_SIZES:
        p = a.out / f"small-{s}.bmp"
        small(s, icon).save(p, "BMP")
        names.append(p.name)
    print(f"{len(names)} bitmaps in {a.out}: " + ", ".join(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
