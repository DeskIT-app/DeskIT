"""The Store package's three logos, drawn from icon.png (256 x 256, the
same mark as icon.ico) — DISTRIBUTION_PLAN.md 10.7.

    StoreLogo.png          50 x 50    Properties/Logo
    Square44x44Logo.png    44 x 44    the app list, the taskbar
    Square150x150Logo.png  150 x 150  the Start tile; the mark at two
                                      thirds of the square, as Windows'
                                      own tiles leave room round theirs

Plain names, no scale or targetsize qualifiers: those are resolved only
through a resources.pri, which the package does not carry. Resized with
LANCZOS from the largest picture there is, on a transparent ground (the
manifest's BackgroundColor is transparent).

    python packaging/store/assets.py --out <package root>\\assets
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "icon.png"

#: name -> (canvas side, the mark's side on it)
LOGOS = {
    "StoreLogo.png": (50, 50),
    "Square44x44Logo.png": (44, 44),
    "Square150x150Logo.png": (150, 100),
}


def draw(out: Path, source: Path = SOURCE) -> list[Path]:
    """Write every logo into `out`; the paths written."""
    out.mkdir(parents=True, exist_ok=True)
    mark = Image.open(source).convert("RGBA")
    written = []
    for name, (side, inner) in LOGOS.items():
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        small = mark.resize((inner, inner), Image.LANCZOS)
        offset = (side - inner) // 2
        canvas.alpha_composite(small, (offset, offset))
        path = out / name
        canvas.save(path, "PNG", optimize=True)
        written.append(path)
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    for path in draw(args.out):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
