"""Draws icon.ico and icon.png — the mark, at every size it is seen at.

Run it only to regenerate the icon:  .venv\\Scripts\\python.exe make_icon.py
Needs Pillow, which is not in requirements.txt: nothing the app does at
runtime depends on this, and the .ico it produces is committed.

THE MARK, and why:

- **A dalet drawn as a desk.** ד is a tabletop with one leg hanging from
  its right end and the top's edge running just past the leg — which is
  also a desk seen from the side. It is the D of DeskIT, and it says
  Hebrew before you have finished looking at it. The letter that was here
  before was an alef: the right idea, the wrong letter, because an alef is
  a symmetrical X and a dalet is a piece of furniture.
- **The dot is the lamp.** It sits above the left of the tabletop and it is
  the status dot the owner sees in the corner of the screen all day: gold
  when it listens, red when it records. The icon and the dot are the same
  object, so the taskbar and the top-right corner say the same thing.
- **Two arcs to its right** turn the lamp into something that also HEARS.
  They are the only detail in the drawing, and they are the first thing
  dropped when the pixel budget runs out.

Two cuts, because each is tuned to a budget — the alef version taught this
and it is still true:

    full (>= 48 px)  the desk, the lamp, its glow and both arcs
    small (< 48)     the desk and the lamp alone. At 24 px an arc is one
                     grey pixel that reads as damage, not as sound, and a
                     glow is a smudge that eats the letter's edge.

Everything is drawn on the SAME 64-unit grid the design was cut on, at 4x
and downsampled with LANCZOS — Pillow antialiases nothing, and rounded
corners at 16 px are unforgiving.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

APP_DIR = Path(__file__).resolve().parent
SIZES = (16, 24, 32, 48, 64, 128, 256)
SUPER = 4                      # supersampling factor
S = 256 * SUPER
GRID = 64.0                    # the design's own units
K = S / GRID                   # one design unit, in supersampled pixels

# LAMPLIGHT, spelled out: this script must run with nothing imported but
# Pillow. skin\palette.py is the source — CARD, FG, ACCENT, and for the
# two variants BG and DIM.
TILE = (0x24, 0x20, 0x1a)      # palette.CARD
LETTER = (0xf1, 0xec, 0xe2)    # palette.FG
LAMP = (0xe3, 0xa6, 0x3c)      # palette.ACCENT
GROUND = (0x14, 0x11, 0x0c)    # palette.BG
QUIET = (0xb2, 0xa8, 0x96)     # palette.DIM

RADIUS = 15 / 64               # the tile's corner, as a fraction of it
RIM_A = 0.08                   # the hairline lift on the top edge


def u(value: float) -> float:
    """A design unit in supersampled pixels."""
    return value * K


def rounded_mask(size: int, radius_ratio: float = RADIUS) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=size * radius_ratio, fill=255)
    return mask


def desk_mask() -> Image.Image:
    """The dalet, as two rounded rectangles that share an edge.

    The path this comes from is
        M14 28H51a2 2 0 0 1 2 2v8h-3v13a2 2 0 0 1-2 2h-6a2 2 0 0 1-2-2V38
        H12v-8a2 2 0 0 1 2-2Z
    which is a top spanning x 12..53 at y 28..38, rounded at its two upper
    corners, and a leg at x 40..50 hanging from y 38 to 53, rounded at its
    two lower ones. Drawn as two rounded rectangles that overlap by a unit
    rather than as one outline, because Pillow has no path support and two
    rectangles with the same fill leave no seam.
    """
    mask = Image.new("L", (S, S), 0)
    draw = ImageDraw.Draw(mask)
    # The top. `corners=` keeps the round on the two the path rounds; the
    # underside stays square so the leg can grow straight out of it.
    draw.rounded_rectangle((u(12), u(28), u(53), u(38)), radius=u(2),
                           fill=255, corners=(True, True, False, False))
    # The leg, overlapping the top by one unit so the join cannot show.
    draw.rounded_rectangle((u(40), u(37), u(50), u(53)), radius=u(2),
                           fill=255, corners=(False, False, True, True))
    return mask


def lamp_mask() -> Image.Image:
    """The dot: circle cx=22 cy=19 r=6."""
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse(
        (u(22 - 6), u(19 - 6), u(22 + 6), u(19 + 6)), fill=255)
    return mask


def glow_mask(peak: float = 0.55, reach: float = 14.0) -> Image.Image:
    """The lamp's halo: a radial ramp from `peak` at the centre to 0.

    An SVG radial gradient is linear in radius, so this is too — drawn as
    concentric discs from the outside in, each one overwriting the last, at
    a step small enough (one supersampled pixel per stop) that the ramp is
    a ramp and not a staircase. One short blur takes the last of the
    quantisation out before the LANCZOS pass.
    """
    mask = Image.new("L", (S, S), 0)
    draw = ImageDraw.Draw(mask)
    cx, cy, outer = u(22), u(19), u(reach)
    steps = int(outer)
    for i in range(steps):
        r = outer * (1 - i / steps)
        alpha = round(255 * peak * (i / steps))
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=alpha)
    return mask.filter(ImageFilter.GaussianBlur(u(0.4)))


def arc_mask(start_xy, end_xy, radius: float, width: float,
             alpha: float) -> Image.Image:
    """One of the two sound arcs, from its SVG arc command.

    Both are `a R R 0 0 1` — a circular arc, small sweep, clockwise —
    between two points on the same vertical, so the centre sits on the
    perpendicular bisector at
        cx = x - sqrt(R^2 - (dy/2)^2),  cy = midpoint
    and the half-angle either side of horizontal is asin((dy/2) / R).
    Solving it here rather than eyeballing an angle is what keeps the two
    arcs concentric with the lamp: both come out centred on y = 19.
    """
    import math
    (x0, y0), (_x1, y1) = start_xy, end_xy
    half = (y1 - y0) / 2.0
    cx = x0 - math.sqrt(max(0.0, radius * radius - half * half))
    cy = y0 + half
    sweep = math.degrees(math.asin(max(-1.0, min(1.0, half / radius))))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).arc(
        (u(cx - radius), u(cy - radius), u(cx + radius), u(cy + radius)),
        start=-sweep, end=sweep, fill=round(255 * alpha),
        width=max(1, round(u(width))))
    return mask


def build(level: str = "full", variant: str = "primary") -> Image.Image:
    """One cut of the mark.

    `variant` is which of the three faces to draw:
        primary    the dark tile, a light desk and a gold lamp
        lit        a gold tile, the desk in the ground colour, a light lamp
                   — a selected state, and what a lit rail row would carry
        one-colour everything in DIM, for a disabled control
    """
    detailed = level == "full"
    if variant == "lit":
        tile, letter, lamp = LAMP, GROUND, LETTER
    elif variant == "one-colour":
        tile, letter, lamp = (0, 0, 0, 0), QUIET, QUIET
    else:
        tile, letter, lamp = TILE, LETTER, LAMP

    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    if variant != "one-colour":
        icon.paste(Image.new("RGB", (S, S), tile), (0, 0), rounded_mask(S))
        # A hairline top edge: the light source is above, and without it
        # the rounded square reads as a sticker rather than a surface.
        rim = Image.new("L", (S, S), 0)
        ImageDraw.Draw(rim).rounded_rectangle(
            (0, 0, S - 1, S - 1), radius=S * RADIUS,
            outline=round(255 * RIM_A), width=max(1, round(u(1))))
        icon.paste(Image.new("RGB", (S, S), (255, 255, 255)), (0, 0),
                   rim.filter(ImageFilter.GaussianBlur(u(0.25))))

    if detailed and variant != "one-colour":
        # The glow goes UNDER the desk, so the lamp lights the tile and
        # not the tabletop it is standing on.
        icon.paste(Image.new("RGB", (S, S), lamp), (0, 0), glow_mask())

    icon.paste(Image.new("RGB", (S, S), letter), (0, 0), desk_mask())
    icon.paste(Image.new("RGB", (S, S), lamp), (0, 0), lamp_mask())

    if detailed:
        for (start, end, radius, width, alpha) in (
                ((33, 12.5), (33, 25.5), 9.0, 2.4, 0.55),
                ((37, 9.0), (37, 29.0), 13.5, 2.4, 0.28)):
            icon.paste(Image.new("RGB", (S, S), lamp), (0, 0),
                       arc_mask(start, end, radius, width, alpha))
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
