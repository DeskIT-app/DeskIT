"""The installer's pictures, in B+: the sky behind every page, the mark and
the name on it, and the mark again in the header.

Inno Setup 6.7 draws `WizardBackImageFile` behind every wizard page, shows
`WizardImageFile` down the side of the Welcome and Finished pages and
`WizardSmallImageFile` in the header of every other page, and picks, from
a comma-separated list, the file whose size best fits the screen's DPI.
The sizes below are the ones its documentation lists.

The sky is the desk's own (look.sky, bplus.css `.sky`): the night with its
fields of light. The side picture is drawn on NOTHING — a PNG with its own
alpha — so the sky runs on behind it without a seam: measured on the
hidden desktop 2026-10-24, a side picture with a sky of its own met the
page's sky at a visible edge, a transparent one did not. The mark is
icon.png, the locked logo (dev\\make_logo.py), as it is.

Generated at build time (release.yml, before ISCC) and by
packaging/build_local.ps1 — never committed: megabytes of pictures for a
drawing of a few lines.

    python dev/make_wizard_images.py --out packaging/wizard --version 1.1.0
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import look  # noqa: E402  (B+'s pieces; Pillow and numpy, no Tk)

#: the page's background, per Inno's list: 100 % ... 250 % (497:360)
BACK_SIZES = [(596, 432), (796, 576), (994, 720), (1193, 864), (1272, 922),
              (1471, 1066), (1630, 1148)]
#: (width, height) of the side picture: 100 %, 125 %, 150 %, 175 %, 200 %
SIDE_SIZES = [(164, 314), (192, 386), (246, 459), (273, 556), (328, 604)]
SMALL_SIZES = [55, 64, 83, 92, 110, 119, 138]


def back(width: int, height: int) -> Image.Image:
    """The sky behind the pages: the desk's four fields of light."""
    return look.sky((width, height))


def side(width: int, height: int, version: str, icon: Image.Image) -> Image.Image:
    """The mark, the name, a fading rule, what it is, the version — on
    nothing, so the sky behind the page shows through."""
    k = height / 314                                   # everything scales with the 100 % panel
    im = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    tile = icon.resize((round(84 * k), round(84 * k)), Image.LANCZOS)
    im.alpha_composite(tile, ((width - tile.width) // 2, round(56 * k)))
    cache: dict = {}
    name = look.text(cache, "DeskIT", 21 * k, "ink", 420)
    im.alpha_composite(name, ((width - name.width) // 2, round(163 * k)))
    look.fade_rule(im, width / 2 - 18 * k, width / 2 + 18 * k, round(196 * k), a=90)
    for i, line in enumerate(("Hebrew dictation", "for Windows")):
        words = look.text(cache, line, 9.4 * k, "muted", 400)
        im.alpha_composite(words, ((width - words.width) // 2, round((208 + 17 * i) * k)))
    ver = look.text(cache, version, 8.6 * k, "faint", 400)
    im.alpha_composite(ver, ((width - ver.width) // 2, height - round(24 * k)))
    return im


def small(size: int, icon: Image.Image) -> Image.Image:
    """The mark in the header of the inner pages, its corners clear."""
    return icon.resize((size, size), Image.LANCZOS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "packaging" / "wizard")
    ap.add_argument("--version", default=(ROOT / "VERSION").read_text("utf-8").strip())
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    icon = Image.open(ROOT / "icon.png").convert("RGBA")
    names = []
    for w, h in BACK_SIZES:
        p = a.out / f"back-{h}.png"
        back(w, h).save(p, "PNG")
        names.append(p.name)
    for w, h in SIDE_SIZES:
        p = a.out / f"side-{h}.png"
        side(w, h, a.version, icon).save(p, "PNG")
        names.append(p.name)
    for s in SMALL_SIZES:
        p = a.out / f"small-{s}.png"
        small(s, icon).save(p, "PNG")
        names.append(p.name)
    print(f"{len(names)} pictures in {a.out}: " + ", ".join(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
