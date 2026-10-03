"""The Store package's logos, at every name and size Windows asks a
packaged app for — DISTRIBUTION_PLAN.md 10.7.

    StoreLogo            Properties/Logo: 50 px at 100 %
    Square44x44Logo      the app list; and, as the targetsize files, the
                         taskbar, Alt+Tab, Task View and Start
    Square150x150Logo    the Start tile; the mark at two thirds of the
                         square, as Windows' own tiles leave room round theirs
    DeskIT.ico           the desktop shortcut's icon (AppxManifest.xml's
                         desktop7:Shortcut) — the app's own icon.ico

Drawn by dev\\make_logo.py, the one source of the mark: once at 2048 px
and resized down with LANCZOS to each size, which is exactly how it draws
icon.ico's frames — so the Store copy's taskbar button and the website
copy's are the same picture at every size the two share.

THE BLUE SQUARE (the Store walk, 2026-10-03, item 2). Until 1.0.7 the
package carried three plain files drawn from icon.png — which still held
the old dalet mark — and Windows put the 44 px one, shrunk, on a "plate",
a square of the accent colour, on the taskbar: the old mark on a blue
square in his screenshot, while the listing, uploaded by hand, showed
Corner. A packaged app's taskbar and Alt+Tab icon is
`Square44x44Logo.targetsize-N_altform-unplated.png`
(`_altform-lightunplated` under the light taskbar), and names with
qualifiers like these are found only through a resources.pri — so
build_msix.ps1 now indexes this folder with makepri (priconfig.xml beside
this file). Microsoft Learn: "Construct your Windows app's icon" (the
complete list of sizes) and "Generating MSIX package components" (the
unplated names and makepri).

The tile is opaque and carries its own ground, so the same pixels serve
the dark and the light taskbar and the manifest's BackgroundColor stays
transparent: nothing is plated. The plain names stay as well — the
manifest names them, and they are the candidates with no qualifier.

    python packaging/store/assets.py --out <package root>\\assets
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]

#: base name -> (side at 100 %, the mark's share of the canvas)
LOGOS = {
    "StoreLogo": (50, 1.0),
    "Square44x44Logo": (44, 1.0),
    "Square150x150Logo": (150, 2 / 3),
}
#: the scales: Microsoft's minimum (100, 200, 400) and the two between
SCALES = (100, 125, 150, 200, 400)
#: the app-list icon's target sizes: the complete list Microsoft gives
TARGET_SIZES = (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 256)
#: unplated, for the dark shell and for the light one
ALTFORMS = ("altform-unplated", "altform-lightunplated")
#: the desktop shortcut's icon, as AppxManifest.xml names it under assets\
SHORTCUT_ICON = "DeskIT.ico"


def make_logo():
    """dev\\make_logo.py, loaded by its path — the one drawing of the mark
    (and no change to sys.path, so nothing in dev\\ can shadow a module
    of the app's in whoever imported this)."""
    spec = importlib.util.spec_from_file_location(
        "deskit_make_logo", ROOT / "dev" / "make_logo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def side_at(side: int, scale: int) -> int:
    """A side at a scale, rounded half up the way Microsoft's tables do:
    150 at 125 % is 188, 50 at 125 % is 63."""
    return int(side * scale / 100 + 0.5)


def names() -> dict[str, tuple[int, float]]:
    """Every picture this writes: file name -> (canvas side, the mark's
    share of it)."""
    out: dict[str, tuple[int, float]] = {}
    for base, (side, share) in LOGOS.items():
        out[f"{base}.png"] = (side, share)
        for scale in SCALES:
            out[f"{base}.scale-{scale}.png"] = (side_at(side, scale), share)
    for size in TARGET_SIZES:
        for form in ALTFORMS:
            out[f"Square44x44Logo.targetsize-{size}_{form}.png"] = (size, 1.0)
    return out


def draw(out: Path) -> list[Path]:
    """Write every logo and the shortcut's icon into `out`; the paths."""
    out.mkdir(parents=True, exist_ok=True)
    logo = make_logo()
    master = logo.tile(logo.BIG, master=False, with_word=False)
    written = []
    for name, (side, share) in names().items():
        inner = side if share >= 1 else round(side * share)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        offset = (side - inner) // 2
        canvas.alpha_composite(master.resize((inner, inner), Image.LANCZOS),
                               (offset, offset))
        path = out / name
        canvas.save(path, "PNG", optimize=True)
        written.append(path)
    icon = out / SHORTCUT_ICON
    shutil.copyfile(ROOT / "icon.ico", icon)
    written.append(icon)
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
