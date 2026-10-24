"""B+ in Pillow: the pieces every card outside the desk is built from.

The desk is a web page since 2026-10-23 and draws B+ with CSS
(web\\src\\bplus.css). Everything else — the shelf, the notification
column, the second reading, the key card, the report box, the consent
card, the tour, the move frame — is a picture Pillow paints, and this is
the one place those pictures get B+'s parts from, so a button on the
shelf and a button on the review card are the same button: a pane of
frost with a rim the light catches top-left, a pill of soft iris light
for the one primary action, a round control for the X, a lamp with its
rings, a disc of coloured light for a mark, a key cap, a switch, the two
pills a second reading draws, and Rubik at the weights B+ asks for.

Each function is the matching rule in bplus.css / desk.css read into
Pillow, and says which. None of them is a decision: the colours come from
skin\\palette.py BY NAME (`INK`), and the literal beside each name is what
the card draws with when skin\\ has been deleted — the same B+ values,
spelled out, because the palette is the app's and not the skin pack's
(SKIN.md, 2026-09-19). Nothing here imports Tk, and nothing module-level
holds anything but numbers, fonts and Pillow images (AGENTS.md: no Tk
object may live in a module global).

TWO THINGS PILLOW GETS WRONG, and how every piece here handles them:

* It antialiases nothing. Every shape is drawn at SS x and reduced with a
  box filter, so a curve has 16 levels of coverage and an edge that is
  empty at SS x is exactly 0 at 1 x.
* `ImageDraw`'s fill REPLACES pixels. Every translucent piece is its own
  RGBA layer, alpha-composited onto the target (AGENTS.md's punched hole).

THE TEXT. Latin runs are drawn by FreeType from fonts\\Rubik.ttf with its
weight axis pinned — 400 for words, 460 for labels and buttons, 500 for
the one strong word — at 4 x and reduced, the key card's recipe
(skin\\hint.py, 2026-10-01: GDI gives a glyph edge 14 levels of coverage at
these sizes, FreeType 85-159). A run with Hebrew in it goes through
visual_qa.text_pil, the one bidi path in this repo that was checked glyph
by glyph; B+ draws Hebrew at 400, which is a weight GDI really has.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

SS = 4

# ---------------------------------------------------------------- the inks
# name -> (the name in skin\palette.py, the B+ literal when skin\ is gone)
_SOURCE = {
    "ink": ("FG", "#efedf7"),
    "dim": ("DIM", "#c0c3d8"),
    "muted": ("MUTED", "#a4a9c2"),
    "faint": ("FAINT", "#70758e"),
    "line": ("LINE", "#30365a"),
    "card": ("CARD", "#1a1e35"),
    "glass_top": ("GLASS_TOP", "#232948"),
    "glass_bot": ("GLASS_BOT", "#191d33"),
    "glass_flat": ("GLASS_FLAT", "#1e233e"),
    "iris": ("ACCENT", "#a597ff"),
    "iris_hi": ("ACCENT_HI", "#b9aeff"),
    "iris_lo": ("ACCENT_DOWN", "#9486ee"),
    "iris_on": ("ACCENT_ON", "#140f33"),
    "iris_text": ("ACCENT_TEXT", "#c2b9ff"),
    "iris_soft": ("ACCENT_SOFT", "#393961"),
    "ok": ("GREEN", "#5fdba6"),
    "warn": ("AMBER", "#ffb84d"),
    "bad": ("RED", "#ff6e7e"),
    "bad_soft": ("RED_SOFT", "#482e44"),
    "cool": ("COOL", "#4db8ff"),
    "rec": ("RECORDING", "#ff5d6e"),
    "idle": ("LAMP_IDLE", "#8a93a8"),
    "core": ("LAMP_CORE", "#c9ecff"),
    "teal": ("TEAL", "#5ed0c4"),
    "violet": ("VIOLET", "#d4a8f0"),
    "cap": ("KEY_BG", "#1b2036"),
}
# The two the palette has no name for: the words ON the misheard pill and
# ON the proposal (bplus.css --bad-ink, --prop-ink).
_FIXED = {"bad_ink": "#ffbcc4", "prop_ink": "#ded8ff", "white": "#ffffff",
          "black": "#000000", "sw_on": "#8286ad", "sw_ring": "#7f86a6",
          "sw_off": "#141a2a", "knob_off": "#a2a8c0"}
# 0..255 alphas, the same way
_ALPHA = {
    "glass_top": ("GLASS_A_TOP", 230), "glass_bot": ("GLASS_A_BOT", 238),
    "frost": ("FROST_A", 15), "rim_hi": ("RIM_HI_A", 66),
    "rim_mid": ("RIM_MID_A", 20), "rim_lo": ("RIM_LO_A", 6),
    "rim_foot": ("RIM_FOOT_A", 26), "inner_hi": ("INNER_HI_A", 18),
    "quiet_top": ("QUIET_TOP_A", 26), "quiet_bot": ("QUIET_BOT_A", 14),
    "quiet_rim": ("QUIET_RIM_A", 26), "quiet_hi": ("QUIET_HI_A", 41),
    "disc": ("DISC_A", 18), "slip": ("SLIP_A", 12), "well": ("WELL_A", 107),
    "iris_glow": ("IRIS_GLOW_A", 128), "spec": ("SPEC_A", 61),
}


def _hex(value: str) -> tuple[int, int, int]:
    value = str(value).lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _load():
    try:
        from skin import palette as pal
    except Exception:                                   # noqa: BLE001
        pal = None
    ink = {}
    for name, (attr, default) in _SOURCE.items():
        got = getattr(pal, attr, None) if pal is not None else None
        ink[name] = _hex(got if isinstance(got, str) and got.startswith("#")
                         else default)
    for name, value in _FIXED.items():
        ink[name] = _hex(value)
    foot = getattr(pal, "RIM_FOOT", None) if pal is not None else None
    ink["rim_foot"] = tuple(foot) if foot else (160, 150, 255)
    glow = getattr(pal, "IRIS_GLOW", None) if pal is not None else None
    ink["iris_glow"] = tuple(glow) if glow else (135, 115, 255)
    well = getattr(pal, "WELL", None) if pal is not None else None
    ink["well"] = tuple(well) if well else (6, 8, 18)
    alpha = {}
    for name, (attr, default) in _ALPHA.items():
        got = getattr(pal, attr, None) if pal is not None else None
        alpha[name] = int(got) if isinstance(got, int) else default
    return ink, alpha


INK, ALPHA = _load()


def c(name, a: int = 255) -> tuple[int, int, int, int]:
    """An ink by name (or an (r, g, b)) with an alpha, for Pillow."""
    rgb = INK[name] if isinstance(name, str) else tuple(name)[:3]
    return tuple(rgb) + (max(0, min(255, int(a))),)


# ---------------------------------------------------------------- masks
def rounded(size, box, radius: float) -> Image.Image:
    """An antialiased L mask of one rounded rectangle in a `size` image.
    `box` is (x0, y0, x1, y1) with x1/y1 EXCLUSIVE — a 20 px wide box is
    (0, 0, 20, h) — and may be fractional."""
    W, H = int(size[0]), int(size[1])
    big = Image.new("L", (max(1, W * SS), max(1, H * SS)), 0)
    x0, y0, x1, y1 = box
    if x1 - x0 < 1.0 / SS or y1 - y0 < 1.0 / SS:
        return big.reduce(SS)           # nothing to draw — and Pillow raises
    r = max(0.0, min(float(radius), (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    ImageDraw.Draw(big).rounded_rectangle(
        (x0 * SS, y0 * SS, x1 * SS - 1, y1 * SS - 1), radius=r * SS, fill=255)
    return big.reduce(SS)


def circle(size, cx: float, cy: float, r: float) -> Image.Image:
    W, H = int(size[0]), int(size[1])
    big = Image.new("L", (max(1, W * SS), max(1, H * SS)), 0)
    ImageDraw.Draw(big).ellipse(((cx - r) * SS, (cy - r) * SS,
                                 (cx + r) * SS - 1, (cy + r) * SS - 1),
                                fill=255)
    return big.reduce(SS)


def flat(size, colour, mask) -> Image.Image:
    """One colour cut to a mask (the mask's value times the colour's
    alpha), as a layer to composite."""
    rgb, a = tuple(colour[:3]), (colour[3] if len(colour) > 3 else 255)
    layer = Image.new("RGBA", (int(size[0]), int(size[1])), rgb + (0,))
    layer.putalpha(mask if a >= 255 else mask.point(lambda v: v * a // 255))
    return layer


def _scale(mask, a: int) -> Image.Image:
    return mask.point(lambda v: v * a // 255)


def erode(mask, px: float) -> Image.Image:
    """`mask` shrunk by `px`: a 3 x 3 minimum, once per pixel. At 1 x and
    on the antialiased mask, so the band it leaves keeps the edge's own
    coverage. (At 2 x with shifted copies this was 80 ms of a panel's
    face; a rank filter of the whole width at once is size-squared.)

    The mask is given an empty border first: a rank filter repeats the
    image's edge pixel, so a shape that runs to the edge of its picture —
    every card's face does — would never be eaten from that side."""
    n = max(1, int(round(px)))
    out = ImageOps.expand(mask, border=n, fill=0)
    for _ in range(n):
        out = out.filter(ImageFilter.MinFilter(3))
    return out.crop((n, n, n + mask.width, n + mask.height))


def ring_of(mask, width: float = 1.0) -> Image.Image:
    """The inner `width` px band of a shape's mask — where a rim is drawn."""
    return ImageChops.subtract(mask, erode(mask, width))


def _numpy():
    import numpy as np
    return np


def _field(size, t_of, stops) -> Image.Image:
    """An RGBA picture whose colour at every pixel is `stops` read at
    t_of(xs, ys) — the parameter of a gradient at those pixel centres.

    A gradient is smooth, so a picture bigger than a key cap is computed
    on a grid a quarter its size and scaled up with BILINEAR: the same
    colours to within a level, at a sixteenth of the numpy work (a
    panel's face went from 250 ms to under 40, measured 2026-10-23)."""
    np = _numpy()
    W, H = int(size[0]), int(size[1])
    k = 4 if W * H > 40000 else 1
    gw, gh = max(2, -(-W // k)), max(2, -(-H // k))
    ys, xs = np.mgrid[0:gh, 0:gw].astype(np.float32)
    xs = (xs + 0.5) * (W / gw)
    ys = (ys + 0.5) * (H / gh)
    t = np.clip(t_of(xs, ys), 0.0, 1.0)
    ts = np.array([s[0] for s in stops], np.float32)
    out = np.zeros((gh, gw, 4), np.float32)
    for ch in range(4):
        vals = np.array([float(s[1][ch]) for s in stops], np.float32)
        out[..., ch] = np.interp(t, ts, vals)
    img = Image.fromarray(out.round().astype(np.uint8), "RGBA")
    return img if (gw, gh) == (W, H) else img.resize((W, H), Image.BILINEAR)


def gradient_along(size, angle_deg: float, stops, box=None) -> Image.Image:
    """A CSS linear-gradient(<angle>deg, stops...) over `box` (the whole
    image by default) as an RGBA image. `stops` are (t, (r, g, b, a))."""
    W, H = int(size[0]), int(size[1])
    x0, y0, x1, y1 = box or (0, 0, W, H)
    w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
    a = math.radians(angle_deg)
    dx, dy = math.sin(a), -math.cos(a)          # CSS: 0deg points up
    half = (abs(w * dx) + abs(h * dy)) / 2.0     # the gradient line's length / 2
    cx, cy = x0 + w / 2, y0 + h / 2
    return _field((W, H), lambda xs, ys: ((xs - cx) * dx + (ys - cy) * dy)
                  / (2 * half) + 0.5, stops)


def radial(size, cx: float, cy: float, rx: float, ry: float, stops
           ) -> Image.Image:
    """A radial gradient (an ellipse rx by ry round (cx, cy)) as RGBA."""
    np = _numpy()
    rx, ry = max(rx, 1e-3), max(ry, 1e-3)
    return _field(size, lambda xs, ys: np.sqrt(((xs - cx) / rx) ** 2
                                               + ((ys - cy) / ry) ** 2),
                  stops)


def _cut(layer, mask) -> Image.Image:
    """`layer` with its alpha multiplied by `mask`."""
    out = layer.copy()
    out.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    return out


# ---------------------------------------------------------------- glass
def rim(mask, box=None, strength: float = 1.0) -> Image.Image:
    """The frosted rim (bplus.css `.glass::before`): a 1 px band inside the
    shape, white where the light hits it top-left (.26), fading through .08
    and .025, and a little violet light coming back at the bottom-right
    (.10). 155 degrees, the way the desk draws every pane."""
    k = max(0.0, float(strength))
    stops = [(0.00, (255, 255, 255, ALPHA["rim_hi"] * k)),
             (0.22, (255, 255, 255, ALPHA["rim_mid"] * k)),
             (0.55, (255, 255, 255, ALPHA["rim_lo"] * k)),
             (1.00, INK["rim_foot"] + (ALPHA["rim_foot"] * k,))]
    return _cut(gradient_along(mask.size, 155, stops, box), ring_of(mask))


def glass(mask, box=None, frost=None, opaque: bool = False,
          light: float = 1.0, dense_edge: float = 0.0) -> Image.Image:
    """A pane of B+ glass in the shape of `mask`: the frost (a blurred
    picture of what is behind, already the mask's size) under a navy face
    lit from above, the face's own light pooled at its top-left, the inner
    top light, and the rim. `opaque` is the same face with nothing behind
    it — a Tk window, which has no per-pixel alpha to see through.

    bplus.css: `.glass` + `--glass-sheet` + `--frost-2` + `--inner-hi`, at
    the desktop's density (palette.GLASS_A_*).

    `dense_edge` is for a face over the compositor's live blur, whose own
    window can only be rounded at Windows' 8 px: that window is inset
    under the face so its corners hide inside this curve, and the band
    round the edge — where the desktop behind is NOT blurred — is drawn
    nearly opaque (.97), easing to the face's own density `dense_edge` px
    in, so the seam is under ninety-seven per cent of night."""
    W, H = mask.size
    x0, y0, x1, y1 = box or mask.getbbox() or (0, 0, W, H)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if frost is not None and not opaque:
        out.alpha_composite(_cut(frost.convert("RGBA"), mask))
    top_a = 255 if opaque else ALPHA["glass_top"]
    bot_a = 255 if opaque else ALPHA["glass_bot"]
    face = gradient_along((W, H), 180, [
        (0.0, INK["glass_top"] + (top_a,)),
        (1.0, INK["glass_bot"] + (bot_a,))], (x0, y0, x1, y1))
    if dense_edge > 0 and not opaque:
        inner = erode(mask, dense_edge)
        inner = inner.filter(ImageFilter.GaussianBlur(dense_edge / 2.0))
        alpha = face.getchannel("A")
        np = _numpy()
        a = np.asarray(alpha, np.float32)
        k = np.asarray(inner, np.float32) / 255.0
        a = 247.0 * (1.0 - k) + a * k
        face.putalpha(Image.fromarray(a.round().astype(np.uint8), "L"))
    out.alpha_composite(_cut(face, mask))
    if light > 0:
        pool = radial((W, H), x0 + (x1 - x0) * 0.12, y0,
                      (x1 - x0) * 0.75, (y1 - y0) * 0.9,
                      [(0.0, (255, 255, 255, ALPHA["frost"] * light)),
                       (1.0, (255, 255, 255, 0))])
        out.alpha_composite(_cut(pool, mask))
    # the inner top light: one pixel row, just under the rim
    shifted = ImageChops.offset(mask, 0, 1)
    shifted.paste(0, (0, 0, W, 1))
    top = ImageChops.subtract(shifted, ImageChops.offset(shifted, 0, 1))
    top = ImageChops.multiply(top, ring_of(mask, 2.0))
    out.alpha_composite(flat((W, H), c("white", ALPHA["inner_hi"]), top))
    out.alpha_composite(rim(mask, (x0, y0, x1, y1)))
    return out


def plate(width: int, height: int, radius: float, inset: int,
          frost=None, shadow: bool = True, opaque: bool = False
          ) -> Image.Image:
    """A whole card's face with `inset` px of room round it: the glass, and
    under it — when asked — B+'s long soft shadow (`0 26px 48px -30px`
    and `0 2px 8px -3px`), which reaches only downward and never past the
    room the window leaves."""
    W, H = width + inset * 2, height + inset * 2
    box = (inset, inset, inset + width, inset + height)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if shadow and inset > 0:
        long = rounded((W, H), (inset + 12, inset + 12, inset + width - 12,
                                inset + height + min(inset - 6, 14)), radius)
        long = long.filter(ImageFilter.GaussianBlur(min(12.0, inset / 2.2)))
        img.alpha_composite(flat((W, H), (2, 3, 12, 150), long))
        near = rounded((W, H), (inset + 2, inset + 3, inset + width - 2,
                                inset + height + 2), radius)
        near = near.filter(ImageFilter.GaussianBlur(3.0))
        img.alpha_composite(flat((W, H), (2, 3, 12, 90), near))
        # nothing reaches the window's border: alpha 0 on every edge
        alpha = img.getchannel("A")
        ImageDraw.Draw(alpha).rectangle((0, 0, W - 1, H - 1), outline=0)
        img.putalpha(alpha)
    mask = rounded((W, H), box, radius)
    face = glass(mask, box, frost.resize((W, H)) if frost is not None
                 and frost.size != (W, H) else frost, opaque=opaque)
    img.alpha_composite(face)
    return img


# ---------------------------------------------------------------- controls
def _quiet_abs(img, box, radius: float | None = None, hover: bool = False,
          down: bool = False) -> None:
    """A quiet button (bplus.css `.btn`): a pill of frost — white .10 at
    its top to .055 at its foot — its top edge lit (.16), a 1 px rim (.10).
    Drawn INTO `img` at `box`; `hover` lifts the frost a step."""
    x0, y0, x1, y1 = box
    r = (y1 - y0) / 2.0 if radius is None else radius
    k = 1.5 if hover else 1.0
    if down:
        k = 0.8
    W, H = img.size
    mask = rounded((W, H), box, r)
    body = gradient_along((W, H), 180, [
        (0.0, (255, 255, 255, ALPHA["quiet_top"] * k)),
        (1.0, (255, 255, 255, ALPHA["quiet_bot"] * k))], box)
    img.alpha_composite(_cut(body, mask))
    band = ring_of(mask)
    img.alpha_composite(flat((W, H), c("white", ALPHA["quiet_rim"]), band))
    top = ImageChops.multiply(band, _top_half(W, H, y0, y1))
    img.alpha_composite(flat((W, H), c("white", ALPHA["quiet_hi"]
                                       - ALPHA["quiet_rim"]), top))


def _top_half(W, H, y0, y1) -> Image.Image:
    """An L ramp that is 255 at y0 and 0 by the box's middle — so a rim
    lights only where the light hits it."""
    np = _numpy()
    ys = np.arange(H, dtype=np.float32)[:, None] + 0.5
    mid = y0 + (y1 - y0) * 0.45
    v = np.clip((mid - ys) / max(1.0, mid - y0), 0.0, 1.0) * 255
    return Image.fromarray(np.repeat(v, W, axis=1).astype(np.uint8), "L")


def _primary_abs(img, box, hover: bool = False, glow: bool = True) -> None:
    """The lit button (bplus.css `.btn.primary`): iris light from its top
    (ACCENT_HI) through ACCENT to its foot (ACCENT_DOWN), a bright top
    edge, a darker lower lip, a 1 px halo, and a soft pool of the same
    light BELOW it — never a ring round it, which is the neon the owner
    called AI slop."""
    x0, y0, x1, y1 = box
    W, H = img.size
    h = y1 - y0
    if glow:
        # bplus.css `0 10px 22px -12px` on a 34 px button, as shares of the
        # button's height so the pool keeps its shape at every scale (in
        # fixed pixels it vanished — and raised — at 0.6)
        pool = rounded((W, H), (x0 + h * 0.35, y0 + h * 0.65, x1 - h * 0.35,
                                y1 + h * 0.12), h / 2)
        pool = pool.filter(ImageFilter.GaussianBlur(max(1.0, h * 0.2)))
        img.alpha_composite(flat((W, H), INK["iris_glow"]
                                 + (ALPHA["iris_glow"],), pool))
    halo = rounded((W, H), (x0 - 1, y0 - 1, x1 + 1, y1 + 1), h / 2 + 1)
    img.alpha_composite(flat((W, H), c("iris", 77), halo))
    mask = rounded((W, H), box, h / 2)
    lift = 1.06 if hover else 1.0
    body = gradient_along((W, H), 180, [
        (0.00, tuple(min(255, v * lift) for v in INK["iris_hi"]) + (255,)),
        (0.55, tuple(min(255, v * lift) for v in INK["iris"]) + (255,)),
        (1.00, tuple(min(255, v * lift) for v in INK["iris_lo"]) + (255,))],
        box)
    img.alpha_composite(_cut(body, mask))
    band = ring_of(mask)
    img.alpha_composite(flat((W, H), c("white", ALPHA["spec"]),
                             ImageChops.multiply(band,
                                                 _top_half(W, H, y0, y1))))
    foot = ImageChops.multiply(band, _bottom(W, H, y0, y1))
    img.alpha_composite(flat((W, H), (40, 20, 120, 72), foot))


def _bottom(W, H, y0, y1) -> Image.Image:
    np = _numpy()
    ys = np.arange(H, dtype=np.float32)[:, None] + 0.5
    mid = y0 + (y1 - y0) * 0.6
    v = np.clip((ys - mid) / max(1.0, y1 - mid), 0.0, 1.0) * 255
    return Image.fromarray(np.repeat(v, W, axis=1).astype(np.uint8), "L")


def _bubble_abs(img, box) -> None:
    """The chosen one of a set (bplus.css `.bubble`, the desk's selected
    place): a pill of glass, bright at its top (.16), thin in the middle
    (.06), catching light again at its foot (.09), a pool of violet light
    in its foot (.34), its top rim the brightest line on it (.34) and a
    lavender rim coming back underneath (.22)."""
    W, H = img.size
    x0, y0, x1, y1 = box
    h = y1 - y0
    mask = rounded((W, H), box, h / 2)
    body = gradient_along((W, H), 180, [
        (0.00, (255, 255, 255, 41)), (0.55, (255, 255, 255, 15)),
        (1.00, (255, 255, 255, 23))], box)
    img.alpha_composite(_cut(body, mask))
    pool = radial((W, H), (x0 + x1) / 2, y1 + h * 0.2, (x1 - x0) * 0.6,
                  h * 0.7, [(0.0, (175, 160, 255, 87)),
                            (1.0, (175, 160, 255, 0))])
    img.alpha_composite(_cut(pool, mask))
    band = ring_of(mask)
    img.alpha_composite(flat((W, H), c("white", 26), band))
    img.alpha_composite(flat((W, H), c("white", 61), ImageChops.multiply(
        band, _top_half(W, H, y0, y1))))
    img.alpha_composite(flat((W, H), (195, 185, 255, 56), ImageChops.multiply(
        band, _bottom(W, H, y0, y1))))


def _disc_abs(img, cx: float, cy: float, r: float, hover: bool = False) -> None:
    """A round control — the X (desk.css `.acts .x`): a disc of white at
    .07, a step brighter under the pointer."""
    W, H = img.size
    a = ALPHA["quiet_top"] if hover else ALPHA["disc"]
    img.alpha_composite(flat((W, H), c("white", a), circle((W, H), cx, cy, r)))


def _slip_abs(img, box, radius: float, lit: bool = False) -> None:
    """A row's own pane inside a card (desk.css `.slip`): a breath of
    frost from the top-left and a rim."""
    W, H = img.size
    x0, y0, x1, y1 = box
    mask = rounded((W, H), box, radius)
    a = ALPHA["slip"] * (2 if lit else 1)
    body = gradient_along((W, H), 140, [
        (0.00, (255, 255, 255, a + ALPHA["frost"])),
        (0.42, (255, 255, 255, a)),
        (1.00, (255, 255, 255, a))], box)
    img.alpha_composite(_cut(body, mask))
    img.alpha_composite(rim(mask, box, 0.8))


def _lamp_abs(img, cx: float, cy: float, colour: str, r: float = 4.0,
         rings: bool = True, glow: float = 1.0) -> None:
    """A status lamp (bplus.css `.lamp`): a bead of light — the listening
    one with a hot centre — two soft rings round it (.16 at +3 px, .06 at
    +6 px) and its light spilling out. `colour` is an INK name; "idle"
    casts no light at all."""
    W, H = img.size
    col = INK[colour] if isinstance(colour, str) else tuple(colour)[:3]
    lit = colour != "idle" and col != INK["idle"]
    if lit and glow > 0:
        spill = circle((W, H), cx, cy, r + 5).filter(
            ImageFilter.GaussianBlur(r + 2))
        img.alpha_composite(flat((W, H), col + (int(110 * glow),), spill))
    if lit and rings:
        img.alpha_composite(flat((W, H), col + (14,),
                                 circle((W, H), cx, cy, r + 6)))
        img.alpha_composite(flat((W, H), col + (28,),
                                 circle((W, H), cx, cy, r + 3)))
    bead = circle((W, H), cx, cy, r)
    if col == INK["cool"]:
        core = radial((W, H), cx - r * 0.2, cy - r * 0.24, r * 1.2, r * 1.2,
                      [(0.0, INK["core"] + (255,)), (0.62, col + (255,)),
                       (1.0, col + (255,))])
        img.alpha_composite(_cut(core, bead))
    else:
        img.alpha_composite(flat((W, H), col + (255,), bead))


def _mark_abs(img, cx: float, cy: float, r: float, colour: str) -> None:
    """A mark (bplus.css `.mk`): a disc of coloured light, lit from inside
    — the colour at .22 near its top fading to .05, a 1 px ring at .28 and
    a soft glow (.45) — on which the caller draws a glyph in the colour."""
    W, H = img.size
    col = INK[colour]
    glow = circle((W, H), cx, cy + 1, r - 4).filter(ImageFilter.GaussianBlur(
        max(2.0, r * 0.45)))
    img.alpha_composite(flat((W, H), col + (70,), glow))
    face = circle((W, H), cx, cy, r)
    tint = radial((W, H), cx, cy - r * 0.4, r * 1.5, r * 1.5,
                  [(0.0, col + (56,)), (0.75, col + (13,)), (1.0, col + (10,))])
    img.alpha_composite(_cut(tint, face))
    img.alpha_composite(flat((W, H), col + (72,), ring_of(face)))


def _keycap_abs(img, box, hover: bool = False) -> None:
    """A key cap (bplus.css `.cap`): KEY_BG, radius 7, its foot in shadow
    (inset 0 -2px black .40), its top edge lit (.16), a rim (.10)."""
    W, H = img.size
    x0, y0, x1, y1 = box
    mask = rounded((W, H), box, min(7.0, (y1 - y0) / 3.0))
    cap = INK["cap"] if not hover else tuple(min(255, v + 10)
                                             for v in INK["cap"])
    img.alpha_composite(flat((W, H), cap + (255,), mask))
    lip = ImageChops.subtract(mask, ImageChops.offset(mask, 0, 2))
    lip = ImageChops.multiply(lip, _bottom(W, H, y0, y1))
    img.alpha_composite(flat((W, H), (0, 0, 0, 102), lip))
    band = ring_of(mask)
    img.alpha_composite(flat((W, H), c("white", ALPHA["quiet_rim"]), band))
    img.alpha_composite(flat((W, H), c("white", ALPHA["quiet_hi"]
                                       - ALPHA["quiet_rim"]),
                             ImageChops.multiply(band,
                                                 _top_half(W, H, y0, y1))))


def _switch_abs(img, x: float, y: float, on: bool, s: float = 1.0,
           hover: bool = False) -> tuple[float, float]:
    """A switch (bplus.css --sw-*): on is a soft lavender-grey track with a
    white knob — it carries no accent; off is a hollow ring with a grey
    knob. Returns its (width, height)."""
    W, H = img.size
    w, h = 40 * s, 22 * s
    box = (x, y, x + w, y + h)
    mask = rounded((W, H), box, h / 2)
    if on:
        img.alpha_composite(flat((W, H), c("sw_on", 255), mask))
        knob = circle((W, H), x + w - h / 2, y + h / 2, h / 2 - 3 * s)
        img.alpha_composite(flat((W, H), c("white"), knob))
    else:
        img.alpha_composite(flat((W, H), c("sw_off"), mask))
        img.alpha_composite(flat((W, H), c("sw_ring"), ring_of(mask, 1.4 * s)))
        knob = circle((W, H), x + h / 2, y + h / 2, h / 2 - 5 * s)
        img.alpha_composite(flat((W, H), c("knob_off"), knob))
    if hover:
        img.alpha_composite(flat((W, H), c("white", 22), mask))
    return w, h


def _pill_abs(img, box, kind: str) -> None:
    """The two pills a second reading draws (desk.css `.pill`): "heard",
    the misheard word, on a red tint with a red edge; "prop", the
    proposal, on an iris tint with an iris edge and a lit top."""
    W, H = img.size
    x0, y0, x1, y1 = box
    mask = rounded((W, H), box, (y1 - y0) / 2)
    band = ring_of(mask)
    if kind == "heard":
        img.alpha_composite(flat((W, H), c("bad_soft"), mask))
        img.alpha_composite(flat((W, H), c("bad", 158), band))
    else:
        img.alpha_composite(flat((W, H), c("iris_soft"), mask))
        img.alpha_composite(flat((W, H), c("iris", 178), band))
        img.alpha_composite(flat((W, H), c("white", 41), ImageChops.multiply(
            band, _top_half(W, H, y0, y1))))


def _well_abs(img, box, radius: float, focus: bool = False) -> None:
    """The writing well inside a sheet (the report sheet's field): darker
    than the sheet (.42 night), its own faint rim, an iris rim when it
    has the caret."""
    W, H = img.size
    mask = rounded((W, H), box, radius)
    img.alpha_composite(flat((W, H), INK["well"] + (ALPHA["well"],), mask))
    if focus:
        img.alpha_composite(flat((W, H), c("iris", 120), ring_of(mask)))
    else:
        img.alpha_composite(flat((W, H), c("white", 16), ring_of(mask)))


# ---------------------------------------------------------------- patches
# Every piece above draws in the coordinates of the image it is given; a
# card is 400 x 700 and a button is 90 x 34, so each piece is drawn on a
# patch the size of its own box (plus the room its glow needs) and that
# patch is composited once. Compositing "over" is associative, so the
# picture is the same pixel for pixel; it is 20-40 x less work, which is
# the difference between a hover that repaints at once and one that lags.
def _on_patch(img, box, margin, draw) -> None:
    x0, y0, x1, y1 = box
    ox = max(0, int(math.floor(x0 - margin)))
    oy = max(0, int(math.floor(y0 - margin)))
    ex = min(img.width, int(math.ceil(x1 + margin)))
    ey = min(img.height, int(math.ceil(y1 + margin)))
    if ex <= ox or ey <= oy:
        return
    local = Image.new("RGBA", (ex - ox, ey - oy), (0, 0, 0, 0))
    draw(local, ox, oy)
    img.alpha_composite(local, (ox, oy))


def _shift(box, ox, oy):
    return (box[0] - ox, box[1] - oy, box[2] - ox, box[3] - oy)


def quiet(img, box, radius=None, hover=False, down=False) -> None:
    _on_patch(img, box, 2, lambda L, ox, oy: _quiet_abs(
        L, _shift(box, ox, oy), radius, hover, down))


def primary(img, box, hover=False, glow=True) -> None:
    _on_patch(img, box, 24 if glow else 3, lambda L, ox, oy: _primary_abs(
        L, _shift(box, ox, oy), hover, glow))


def bubble(img, box) -> None:
    _on_patch(img, box, 2, lambda L, ox, oy: _bubble_abs(
        L, _shift(box, ox, oy)))


def disc(img, cx, cy, r, hover=False) -> None:
    box = (cx - r, cy - r, cx + r, cy + r)
    _on_patch(img, box, 2, lambda L, ox, oy: _disc_abs(
        L, cx - ox, cy - oy, r, hover))


def slip(img, box, radius, lit=False) -> None:
    _on_patch(img, box, 2, lambda L, ox, oy: _slip_abs(
        L, _shift(box, ox, oy), radius, lit))


def lamp(img, cx, cy, colour, r=4.0, rings=True, glow=1.0) -> None:
    box = (cx - r, cy - r, cx + r, cy + r)
    _on_patch(img, box, r + 16, lambda L, ox, oy: _lamp_abs(
        L, cx - ox, cy - oy, colour, r, rings, glow))


def mark(img, cx, cy, r, colour) -> None:
    box = (cx - r, cy - r, cx + r, cy + r)
    _on_patch(img, box, r + 4, lambda L, ox, oy: _mark_abs(
        L, cx - ox, cy - oy, r, colour))


def keycap(img, box, hover=False) -> None:
    _on_patch(img, box, 2, lambda L, ox, oy: _keycap_abs(
        L, _shift(box, ox, oy), hover))


def switch(img, x, y, on, s=1.0, hover=False):
    box = (x, y, x + 40 * s, y + 22 * s)
    _on_patch(img, box, 2, lambda L, ox, oy: _switch_abs(
        L, x - ox, y - oy, on, s, hover))
    return 40 * s, 22 * s


def pill(img, box, kind) -> None:
    _on_patch(img, box, 2, lambda L, ox, oy: _pill_abs(
        L, _shift(box, ox, oy), kind))


def well(img, box, radius, focus=False) -> None:
    _on_patch(img, box, 2, lambda L, ox, oy: _well_abs(
        L, _shift(box, ox, oy), radius, focus))


def fade_rule(img, x0: float, x1: float, y: float, a: int = 31) -> None:
    """A hairline that fades out at both ends (bplus.css `.fade-rule`)."""
    W, H = img.size
    stops = [(0.0, INK["line"] + (0,)), (0.12, (170, 175, 220, a)),
             (0.88, (170, 175, 220, a)), (1.0, INK["line"] + (0,))]
    band = gradient_along((max(1, int(x1 - x0)), 1), 90, stops)
    img.alpha_composite(band, (int(round(x0)), int(round(y))))


# ---------------------------------------------------------------- glyphs
def glyph(kind: str, size: float, colour, weight: float = 1.6
          ) -> Image.Image:
    """A small line glyph, drawn at SS x and reduced: x, chevron, bell,
    pencil, check, moon, warn, folder, send, arrow-l, arrow-r, pause,
    play, stop, copy. `colour` is an INK name or an RGBA."""
    n = max(4, int(round(size)))
    m = n * SS
    img = Image.new("RGBA", (m, m), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = c(colour) if isinstance(colour, str) else tuple(colour)
    lw = max(1, int(round(weight * SS * n / 16)))

    def P(x, y):
        return (x * m, y * m)
    if kind == "x":
        d.line([P(.28, .28), P(.72, .72)], fill=col, width=lw)
        d.line([P(.72, .28), P(.28, .72)], fill=col, width=lw)
    elif kind == "chevron":
        d.line([P(.40, .24), P(.66, .50), P(.40, .76)], fill=col, width=lw,
               joint="curve")
    elif kind == "check":
        d.line([P(.22, .52), P(.42, .72), P(.80, .30)], fill=col, width=lw,
               joint="curve")
    elif kind == "arrow-l":
        d.line([P(.82, .50), P(.20, .50)], fill=col, width=lw)
        d.line([P(.42, .28), P(.20, .50), P(.42, .72)], fill=col, width=lw,
               joint="curve")
    elif kind == "arrow-r":
        d.line([P(.18, .50), P(.80, .50)], fill=col, width=lw)
        d.line([P(.58, .28), P(.80, .50), P(.58, .72)], fill=col, width=lw,
               joint="curve")
    elif kind == "bell":
        d.arc((P(.24, .18) + P(.76, .70)), 180, 360, fill=col, width=lw)
        d.line([P(.24, .44), P(.24, .64), P(.16, .74), P(.84, .74),
                P(.76, .64), P(.76, .44)], fill=col, width=lw, joint="curve")
        d.arc((P(.40, .70) + P(.60, .90)), 0, 180, fill=col, width=lw)
    elif kind == "pencil":
        d.line([P(.22, .78), P(.30, .58), P(.66, .22), P(.78, .34),
                P(.42, .70), P(.22, .78)], fill=col, width=lw, joint="curve")
        d.line([P(.58, .30), P(.70, .42)], fill=col, width=lw)
    elif kind == "warn":
        d.line([P(.50, .16), P(.88, .82), P(.12, .82), P(.50, .16)], fill=col,
               width=lw, joint="curve")
        d.line([P(.50, .40), P(.50, .60)], fill=col, width=lw)
        d.ellipse(P(.46, .68) + P(.54, .76), fill=col)
    elif kind == "moon":
        disc_l = Image.new("L", (m, m), 0)
        dd = ImageDraw.Draw(disc_l)
        dd.ellipse(P(.16, .16) + P(.84, .84), fill=255)
        dd.ellipse(P(.36, .04) + P(1.06, .74), fill=0)
        img.paste(Image.new("RGBA", (m, m), col), (0, 0), disc_l)
    elif kind == "folder":
        d.rounded_rectangle(P(.08, .28) + P(.92, .84), m * .10, outline=col,
                            width=lw)
        d.line([P(.08, .30), P(.12, .18), P(.42, .18), P(.50, .28)],
               fill=col, width=lw, joint="curve")
    elif kind == "send":
        d.line([P(.16, .20), P(.86, .50), P(.16, .80), P(.28, .50),
                P(.16, .20)], fill=col, width=lw, joint="curve")
        d.line([P(.28, .50), P(.56, .50)], fill=col, width=lw)
    elif kind == "pause":
        d.rounded_rectangle(P(.30, .24) + P(.42, .76), lw, fill=col)
        d.rounded_rectangle(P(.58, .24) + P(.70, .76), lw, fill=col)
    elif kind == "play":
        d.polygon([P(.34, .22), P(.34, .78), P(.76, .50)], fill=col)
    elif kind == "stop":
        d.rounded_rectangle(P(.28, .28) + P(.72, .72), lw * 1.2, outline=col,
                            width=lw)
    elif kind == "copy":
        d.rounded_rectangle(P(.18, .12) + P(.62, .66), m * .08, outline=col,
                            width=lw)
        d.rounded_rectangle(P(.36, .32) + P(.82, .88), m * .08, outline=col,
                            width=lw)
    return img.resize((n, n), Image.LANCZOS)


# ---------------------------------------------------------------- text
W_BODY, W_LABEL, W_STRONG = 400, 460, 500
_FONTS: dict = {}


def _rubik() -> Path:
    try:
        from fonts import FONT_DIR
    except Exception:                                   # noqa: BLE001
        FONT_DIR = Path(__file__).resolve().parent / "fonts"
    return Path(FONT_DIR) / "Rubik.ttf"


def _segoe(weight: int) -> Path:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    name = "seguisb.ttf" if weight >= W_STRONG else "segoeui.ttf"
    path = Path(windir) / "Fonts" / name
    return path if path.is_file() else Path(windir) / "Fonts" / "segoeui.ttf"


def _font(px: float, weight: int, fallback: bool = False):
    key = (round(px, 3), int(weight), fallback)
    font = _FONTS.get(key)
    if font is None:
        if fallback:
            font = ImageFont.truetype(str(_segoe(weight)), px,
                                      layout_engine=ImageFont.Layout.BASIC)
        else:
            font = ImageFont.truetype(str(_rubik()), px,
                                      layout_engine=ImageFont.Layout.BASIC)
            try:
                font.set_variation_by_axes([int(weight)])
            except Exception:                           # noqa: BLE001
                pass
        if len(_FONTS) > 64:
            _FONTS.clear()
        _FONTS[key] = font
    return font


_GAPS: dict = {}


def _rubik_lacks(ch: str) -> bool:
    hit = _GAPS.get(ch)
    if hit is None:
        font = _font(16, W_BODY)

        def sig(x):
            m = font.getmask(x)
            return m.size, bytes(m)
        hit = ch.strip() != "" and sig(ch) == sig("\U000FFFFD")
        _GAPS[ch] = hit
    return hit


def is_rtl(text: str) -> bool:
    """Decided by the first strong letter — every card's rule."""
    for ch in text or "":
        if "\u0590" <= ch <= "\u08ff":
            return True
        if ch.isalpha():
            return False
    return False


def has_hebrew(text: str) -> bool:
    return any("\u0590" <= ch <= "\u08ff" for ch in text or "")


def text(cache: dict, words: str, pt: float, colour="ink",
         weight: int = W_BODY, rtl: bool | None = None,
         width: int = 1400) -> Image.Image:
    """One line as an RGBA image cropped to its ink, in `colour` (an INK
    name or an RGB). Latin by FreeType at its real weight; anything with a
    Hebrew letter through visual_qa.text_pil (GDI, DT_RTLREADING), which
    takes the run's own direction from `rtl` or its first strong letter."""
    rgb = INK[colour] if isinstance(colour, str) else tuple(colour)[:3]
    key = ("t", words, round(pt, 2), rgb, int(weight), rtl, width)
    got = cache.get(key)
    if got is not None:
        return got
    words = words or " "
    if has_hebrew(words):
        from visual_qa import text_pil
        img = text_pil(words, max(20, int(width)), pt=pt, colour=rgb,
                       weight=400 if weight < 650 else 700,
                       rtl=is_rtl(words) if rtl is None else rtl,
                       single=True)
        box = img.getchannel("A").getbbox()
        img = img.crop(box) if box else img
    else:
        img = _freetype(words, pt, rgb, weight)
    cache[key] = img
    return img


def _freetype(words: str, pt: float, rgb, weight: int) -> Image.Image:
    px = float(pt) * 96 / 72
    fallback = any(_rubik_lacks(ch) for ch in words)
    font = _font(px * SS, weight, fallback)
    ascent, descent = font.getmetrics()
    left, _t, right, _b = font.getbbox(words, anchor="ls")
    pad = 2 * SS
    w = int(math.ceil(right - min(0, left))) + 2 * pad
    h = ascent + descent + 2 * pad
    w, h = w + (-w) % SS, h + (-h) % SS
    big = Image.new("L", (max(SS, w), h), 0)
    ImageDraw.Draw(big).text((pad - min(0, left), ascent + pad), words,
                             font=font, fill=255, anchor="ls")
    mask = big.reduce(SS)
    box = mask.getbbox()
    mask = mask.crop(box) if box else Image.new("L", (1, 1), 0)
    out = Image.new("RGBA", mask.size, tuple(rgb) + (0,))
    out.putalpha(mask)
    return out


def text_line(cache: dict, words: str, pt: float, colour="ink",
              weight: int = W_BODY) -> tuple[Image.Image, float]:
    """A LATIN line with its baseline kept: (image, baseline y in it) — so
    two runs at different sizes sit on one line rather than each centred
    on its own box. Hebrew is not routed here."""
    rgb = INK[colour] if isinstance(colour, str) else tuple(colour)[:3]
    key = ("tl", words, round(pt, 2), rgb, int(weight))
    got = cache.get(key)
    if got is not None:
        return got
    px = float(pt) * 96 / 72
    font = _font(px * SS, weight, any(_rubik_lacks(ch) for ch in words))
    ascent, descent = font.getmetrics()
    left, _t, right, _b = font.getbbox(words or " ", anchor="ls")
    pad = 2 * SS
    w = int(math.ceil(right - min(0, left))) + 2 * pad
    h = ascent + descent + 2 * pad
    w, h = w + (-w) % SS, h + (-h) % SS
    big = Image.new("L", (max(SS, w), h), 0)
    ImageDraw.Draw(big).text((pad - min(0, left), ascent + pad), words or " ",
                             font=font, fill=255, anchor="ls")
    mask = big.reduce(SS)
    box = mask.getbbox() or (0, 0, 1, mask.height)
    mask = mask.crop((box[0], 0, box[2], mask.height))
    out = Image.new("RGBA", mask.size, tuple(rgb) + (0,))
    out.putalpha(mask)
    got = (out, (ascent + pad) / SS)
    cache[key] = got
    return got


def cap_height(pt: float, weight: int = W_BODY) -> float:
    """Rubik's capital height at `pt`, in pixels. A row whose words should
    look centred on `cy` puts its baseline at cy + cap_height / 2 — the
    capitals and the x-height sit on the middle, and a descender ("ago")
    hangs below it instead of lifting the whole word (the polish pass,
    2026-10-23: "5 min ago" sat 2 px above "Claude Code", each centred on
    its own cropped box)."""
    font = _font(float(pt) * 96 / 72 * SS, weight)
    return -font.getbbox("H", anchor="ls")[1] / SS


def x_height(pt: float, weight: int = W_BODY) -> float:
    """Rubik's x-height at `pt`, in pixels: where a lamp before a word
    belongs (base = cy + x_height / 2), so "Listening" and "Paused" sit
    on the same line beside it whatever their descenders."""
    font = _font(float(pt) * 96 / 72 * SS, weight)
    return -font.getbbox("x", anchor="ls")[1] / SS


def row_line(cache: dict, words: str, pt: float, colour, weight: int,
             cy: float, ref_pt: float | None = None, by: str = "cap"):
    """(image, top) for one line centred on a row at `cy` BY ITS BASELINE:
    the capitals (`by="cap"`, a word in a pill) or the x-height (`by="x"`,
    a word beside a lamp) on the middle, measured at `ref_pt` so two sizes
    on one row share a baseline. Hebrew is centred on its box — GDI's
    picture carries no baseline."""
    if has_hebrew(words):
        im = text(cache, words, pt, colour, weight)
        return im, cy - im.height / 2
    im, b = text_line(cache, words, pt, colour, weight)
    mid = (x_height if by == "x" else cap_height)(ref_pt or pt, weight)
    return im, cy + mid / 2 - b


def on_baseline(img: Image.Image, cache: dict, words: str, pt: float,
                x: float, base: float, colour="ink", weight: int = W_BODY,
                avail: float | None = None, right: bool = False) -> float:
    """Draw one Latin line onto `img` with its baseline at `base`, from `x`
    (or ending at `x` when `right`), cut to `avail` if given. Returns its
    width. Hebrew goes through text() and is centred on the baseline's
    row instead — GDI's box carries no baseline to keep."""
    if has_hebrew(words):
        line = text(cache, words, pt, colour, weight)
        top = base - cap_height(pt) / 2 - line.height / 2
    else:
        line, b = text_line(cache, words, pt, colour, weight)
        top = base - b
    if avail is not None and line.width > avail:
        keep = max(1, int(avail))
        line = line.crop((line.width - keep, 0, line.width, line.height)) \
            if is_rtl(words) else line.crop((0, 0, keep, line.height))
    left = x - line.width if right else x
    img.alpha_composite(line, (max(0, int(round(left))),
                               max(0, int(round(top)))))
    return line.width


__all__ = ["INK", "ALPHA", "c", "rounded", "circle", "flat", "ring_of",
           "glass", "plate", "rim", "quiet", "primary", "disc", "slip",
           "lamp", "mark", "keycap", "switch", "pill", "well", "fade_rule",
           "glyph", "text", "text_line", "cap_height", "x_height",
           "row_line", "on_baseline",
           "is_rtl", "has_hebrew", "W_BODY", "W_LABEL", "W_STRONG"]
