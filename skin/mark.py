"""The mark, painted small: the dark tile, the desk and the lamp.

make_icon.py draws icon.ico from a 64-unit grid — a rounded tile in CARD,
a dalet drawn as a desk in FG, and a lamp above it in the accent. This is
the same drawing, on the same grid, drawn by Pillow at the sizes the app
shows it at while it RUNS: the status dot (a 28 px tile in a 38 px
window) and the boot card's badge. The icon and the dot are the same
object, so the taskbar and the corner of the screen say the same thing.

WHY THE DOT IS A TILE NOW. Until 2026-09-19 the dot was a 10 px disc with
a halo — light with nothing behind it. The owner's screenshot of a fresh
install showed it in the top-right of a bright sky wallpaper: a thin ring,
nearly invisible. A disc of light can only ever be as visible as the
contrast between its own colour and whatever the wallpaper happens to be,
and the listening colour is sky blue. The tile is the fix: a dark surface
the app carries with it, so the lamp always sits on the same ground
wherever the window is. What still has to survive any wallpaper is the
TILE's edge, and that is done twice over — a soft drop shadow, which is
what lifts it off a light ground, and a hairline light rim, which is what
finds its edge on a dark one. Neither alone works on both.

WHY PILLOW AND NOT SKIA. skia-python is the skin pack, a 10.9 MB wheel a
fresh install does not have (packs.py) — so every stranger's copy paints
the dot and the splash with whatever this folder can do WITHOUT it. A
38 px picture costs nothing to draw on the CPU, and drawing it here once
means the skia path and the no-skia path show one dot rather than two
that drift. The static half (shadow, tile, rim, the desk's shape) is baked
once per size; a frame is three small pastes over that plate.

Everything is drawn at SUPER x and reduced with a box filter, deliberately
not LANCZOS: a box filter samples only its own 4 x 4 block, so a border
that is empty at 4 x is EXACTLY zero at 1 x. That matters because the
window is a layered window and any non-zero alpha on its border draws
the rectangle (AGENTS.md: "a glow that does not reach alpha 0 inside its
window IS the window"). LANCZOS rings, and a ring is a non-zero pixel.
"""
from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .palette import CARD, FG, rgb

SUPER = 4
GRID = 64.0
RADIUS = 15 / 64          # the tile's corner, as a fraction of its side

# The two cuts of the drawing, in the grid's own units. ICON is
# make_icon.py's geometry exactly. DOT moves the desk down and makes the
# lamp almost twice the size, because on the dot the lamp is the status
# light and it has to carry a colour at 28 px; at the icon's 6 units it
# would be a 2.6 px point.
CUTS = {
    "icon": {"lamp": (22.0, 19.0, 6.0),
             "top": (12.0, 28.0, 53.0, 38.0),
             "leg": (40.0, 37.0, 50.0, 53.0),
             "glow": 14.0},
    # 11.43 units on a 28 px tile is a 5.0 px radius: skin\dot.CORE / 2
    "dot": {"lamp": (22.0, 20.0, 11.43),
            "top": (12.0, 36.0, 53.0, 45.0),
            "leg": (40.0, 44.0, 50.0, 58.0),
            "glow": 30.0},
}

RIM_A = 74                # the hairline rim at rest, alpha out of 255
RIM_MOVING_A = 236        # while the dot is waiting to be dragged
SHADOW_A = 150            # the drop shadow's core
SHADOW_BLUR = 1.6         # px at 1 x
SHADOW_DROP = 1.5         # px at 1 x, downward
SPEC_A = 96               # the lamp's specular highlight
TOP_LIGHT = 26            # how much lighter the tile's top edge is


def _rr(draw, box, radius, fill=None, outline=None, width=1, corners=None):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline,
                           width=width, corners=corners)


class Mark:
    """One size of the mark, with its static half baked.

    `tile` is the tile's side in pixels and `box` the picture's — the room
    between them is where the shadow goes. `frame()` paints one state.
    """

    def __init__(self, tile: int, box: int, cut: str = "dot",
                 tile_rgb=None) -> None:
        self.tile, self.box = int(tile), int(box)
        self.cut = CUTS[cut]
        S = self.box * SUPER
        self._S = S
        off = (self.box - self.tile) / 2.0 * SUPER
        t = self.tile * SUPER
        self._tile_box = (off, off, off + t - 1, off + t - 1)
        self._radius = t * RADIUS
        self._tile_rgb = tuple(tile_rgb or rgb(CARD))
        # the lamp's centre and radius, at 1 x, for callers that want to
        # know where the light is (the dot's tests probe beside it)
        lx, ly, lr = self.cut["lamp"]
        self.lamp = (self.box - self.tile) / 2.0 + lx * self.tile / GRID, \
            (self.box - self.tile) / 2.0 + ly * self.tile / GRID, \
            lr * self.tile / GRID
        self._border = Image.new("L", (self.box, self.box), 255)
        ImageDraw.Draw(self._border).rectangle(
            (0, 0, self.box - 1, self.box - 1), outline=0)
        self._plate = self._bake_plate(RIM_A, 1.0)
        self._plate_moving = self._bake_plate(RIM_MOVING_A, 2.0)
        self._tile_mask = self._reduce(self._mask_tile())
        self._desk = self._reduce(self._mask_desk())
        self._lamp = self._reduce(self._mask_lamp(1.0))
        self._glow = self._reduce(ImageChops.multiply(self._mask_glow(),
                                                      self._mask_tile()))
        self._spec = self._reduce(self._mask_spec())
        self._fg = Image.new("RGBA", (self.box, self.box), rgb(FG) + (255,))
        self._white = Image.new("RGBA", (self.box, self.box),
                                (255, 255, 255, 255))

    # ----------------------------------------------------------- units
    def _u(self, value: float) -> float:
        return value * self.tile / GRID * SUPER

    def _at(self, x: float, y: float) -> tuple[float, float]:
        off = self._tile_box[0]
        return off + self._u(x), off + self._u(y)

    def _reduce(self, image):
        return image.reduce(SUPER)

    # ----------------------------------------------------------- masks
    def _mask_tile(self):
        mask = Image.new("L", (self._S, self._S), 0)
        _rr(ImageDraw.Draw(mask), self._tile_box, self._radius, fill=255)
        return mask

    def _mask_desk(self):
        mask = Image.new("L", (self._S, self._S), 0)
        draw = ImageDraw.Draw(mask)
        x0, y0 = self._at(*self.cut["top"][:2])
        x1, y1 = self._at(*self.cut["top"][2:])
        _rr(draw, (x0, y0, x1, y1), self._u(2), fill=255,
            corners=(True, True, False, False))
        x0, y0 = self._at(*self.cut["leg"][:2])
        x1, y1 = self._at(*self.cut["leg"][2:])
        _rr(draw, (x0, y0, x1, y1), self._u(2), fill=255,
            corners=(False, False, True, True))
        return mask

    def _mask_lamp(self, scale: float):
        cx, cy = self._at(*self.cut["lamp"][:2])
        r = self._u(self.cut["lamp"][2]) * scale
        mask = Image.new("L", (self._S, self._S), 0)
        ImageDraw.Draw(mask).ellipse((cx - r, cy - r, cx + r, cy + r),
                                     fill=255)
        return mask

    def _mask_glow(self):
        """A radial ramp from the lamp outward — linear in radius, drawn as
        concentric discs the way make_icon.glow_mask does, then softened."""
        cx, cy = self._at(*self.cut["lamp"][:2])
        reach = self._u(self.cut["glow"])
        mask = Image.new("L", (self._S, self._S), 0)
        draw = ImageDraw.Draw(mask)
        steps = max(8, int(reach))
        for i in range(steps):
            r = reach * (1 - i / steps)
            alpha = int(255 * 0.80 * (i / steps) ** 1.3)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=alpha)
        return mask.filter(ImageFilter.GaussianBlur(0.5 * SUPER))

    def _mask_spec(self):
        cx, cy = self._at(*self.cut["lamp"][:2])
        r = self._u(self.cut["lamp"][2])
        mask = Image.new("L", (self._S, self._S), 0)
        ImageDraw.Draw(mask).ellipse((cx - r * 0.55, cy - r * 0.62,
                                      cx - r * 0.08, cy - r * 0.15),
                                     fill=SPEC_A)
        return mask.filter(ImageFilter.GaussianBlur(0.35 * SUPER))

    # ----------------------------------------------------------- plate
    def _bake_plate(self, rim_alpha: int, rim_width: float):
        """Shadow, tile, the lit top edge and the rim: nothing here ever
        changes with the state, so it is drawn once."""
        S = self._S
        tb = self._tile_box
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        # the shadow: the tile's own shape dropped a little and blurred
        shadow = Image.new("L", (S, S), 0)
        drop = SHADOW_DROP * SUPER
        _rr(ImageDraw.Draw(shadow), (tb[0], tb[1] + drop, tb[2], tb[3] + drop),
            self._radius, fill=SHADOW_A)
        shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR * SUPER))
        img.paste(Image.new("RGBA", (S, S), (0, 0, 0, 255)), (0, 0), shadow)
        # the face
        tile_mask = self._mask_tile()
        img.paste(Image.new("RGBA", (S, S), self._tile_rgb + (255,)), (0, 0),
                  tile_mask)
        # a hair lighter at the top, the way a surface lit from above is
        grad = Image.linear_gradient("L").resize((S, S))       # 0 top .. 255
        grad = grad.point(lambda v: max(0, TOP_LIGHT - v * TOP_LIGHT // 255))
        grad = ImageChops.multiply(grad, tile_mask)
        img.paste(Image.new("RGBA", (S, S), (255, 255, 255, 255)), (0, 0),
                  grad)
        # the rim
        rim = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        _rr(ImageDraw.Draw(rim), tb, self._radius,
            outline=(255, 255, 255, rim_alpha),
            width=max(1, int(round(rim_width * SUPER))))
        img = Image.alpha_composite(img, rim)
        return self._finish(self._reduce(img))

    def _finish(self, image):
        """Alpha 0 on the whole border, whatever the blur reached."""
        image.putalpha(ImageChops.multiply(image.getchannel("A"),
                                           self._border))
        return image

    # ----------------------------------------------------------- frame
    def frame(self, lamp_rgb, glow: float = 1.0, sweep: float | None = None,
              moving: bool = False, lamp_scale: float = 1.0,
              desk: bool = True):
        """One picture of the mark: the lamp in `lamp_rgb`, its light on
        the tile at `glow` (0 = off — paused reads by that absence), an
        arc at `sweep` degrees round the lamp while transcribing, and the
        bright wide rim while the dot is waiting to be dragged."""
        img = (self._plate_moving if moving else self._plate).copy()
        colour = Image.new("RGBA", (self.box, self.box),
                           tuple(int(c) for c in lamp_rgb) + (255,))
        k = 0.0 if glow <= 0 else 1.0 if glow >= 1 else float(glow)
        if k > 0.004:
            mask = self._glow if k >= 0.999 else \
                self._glow.point(lambda v: int(v * k))
            img.paste(colour, (0, 0), mask)
        if sweep is not None:
            img.paste(colour, (0, 0), self._reduce(self._mask_sweep(sweep)))
        if desk:
            img.paste(self._fg, (0, 0), self._desk)
        lamp = self._lamp if lamp_scale == 1.0 else \
            self._reduce(self._mask_lamp(lamp_scale))
        img.paste(colour, (0, 0), lamp)
        img.paste(self._white, (0, 0), self._spec)
        return img

    def _mask_sweep(self, angle: float):
        """A short arc round the lamp: transcribing is work in progress and
        a rotation says that without ever changing luminance. It is drawn
        UNDER the desk, so the desk occludes it and it reads as light
        passing behind the tabletop rather than as a ring on top."""
        cx, cy = self._at(*self.cut["lamp"][:2])
        r = self._u(self.cut["lamp"][2]) + self._u(4.5)
        mask = Image.new("L", (self._S, self._S), 0)
        ImageDraw.Draw(mask).arc((cx - r, cy - r, cx + r, cy + r),
                                 start=angle, end=angle + 100.0, fill=215,
                                 width=max(1, int(round(1.4 * SUPER))))
        return ImageChops.multiply(mask, self._mask_tile())

    def inside(self, x: float, y: float) -> bool:
        """Is this 1 x pixel on the tile? The tile is the button."""
        if not (0 <= x < self.box and 0 <= y < self.box):
            return False
        return self._tile_mask.getpixel((int(x), int(y))) >= 128


__all__ = ["Mark", "CUTS", "SUPER", "RADIUS"]
