"""The mark, painted small: the boot card's badge.

THE MARK IS CORNER (2026-09-23): one rounded corner cut flat at both ends,
with the lamp — a gold dot — at the exact centre of its curve.
dev\\make_logo.py draws it into every icon file (icon.ico, icon.png, the
site's icon, the Store package's logos); this module draws the same shape,
on the same 64-unit grid and at the same 94 % of it, for the one place the
app paints the mark while it RUNS: the badge on the boot card a copy
without skia gets (boot.Lite). It cannot import make_logo — the product
never imports from dev\\, which is not in the build — so it carries the
numbers itself, and test_the_boot_badge_is_the_logo_drawn_small holds the
two drawings to the same shape. Until 2026-10-03 this drew the dalet desk
that came before Corner, nine days after every icon file had moved on (the
Store walk, item 1).

THE STROKE IS ONE FILLED AREA, for the reason make_logo.py gives: a thick
arc and a thick line drawn separately meet with a notch at each join, and
he circled both (2026-09-24). Here, as there, it is the ring r 16..24
round the lamp kept to the quadrant the path turns through, plus the two
legs as rectangles whose edges are the ring's own ends — they meet by
construction, at any size.

WHY PILLOW AND NOT SKIA. The card this badge sits on is the one painted
WITHOUT skia, so the badge cannot use it either. A 54 px picture costs
nothing to draw on the CPU; the static half (shadow, tile, rim, the
corner's shape) is baked once, and a frame is three small pastes over
that plate.

Everything is drawn at SUPER x and reduced with a box filter, deliberately
not LANCZOS: a box filter samples only its own 4 x 4 block, so a border
that is empty at 4 x is EXACTLY zero at 1 x. That matters because the
card is a layered window and any non-zero alpha on its border draws the
rectangle (AGENTS.md: "a glow that does not reach alpha 0 inside its
window IS the window"). LANCZOS rings, and a ring is a non-zero pixel.
"""
from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .palette import CARD, FG, rgb

SUPER = 4
GRID = 64.0
RADIUS = 15 / 64          # the tile's corner, as a fraction of its side

# Corner on its 64-unit grid: dev\make_logo.py's numbers.
LAMP = (30.0, 34.0, 10.0)            # the dot: centre and radius
RING = (30.0, 34.0, 16.0, 24.0)      # the turn: centre, inner and outer radius
TOP = (10.0, 10.0, 30.0, 18.0)       # the flat top, x0 y0 x1 y1
SIDE = (46.0, 34.0, 54.0, 54.0)      # the flat side
SCALE = 0.94                         # the mark's share of its tile, as on the app icon
GLOW = 16.0                          # the lamp's light reaches the ring's inner edge

RIM_A = 74                # the hairline rim, alpha out of 255
SHADOW_A = 150            # the drop shadow's core
SHADOW_BLUR = 1.6         # px at 1 x
SHADOW_DROP = 1.5         # px at 1 x, downward
TOP_LIGHT = 26            # how much lighter the tile's top edge is


def _rr(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline,
                           width=width)


class Mark:
    """One size of the mark, with its static half baked.

    `tile` is the tile's side in pixels and `box` the picture's — the room
    between them is where the shadow goes. `frame()` paints one state.
    """

    def __init__(self, tile: int, box: int, tile_rgb=None) -> None:
        self.tile, self.box = int(tile), int(box)
        S = self.box * SUPER
        self._S = S
        off = (self.box - self.tile) / 2.0 * SUPER
        t = self.tile * SUPER
        self._tile_box = (off, off, off + t - 1, off + t - 1)
        self._radius = t * RADIUS
        self._tile_rgb = tuple(tile_rgb or rgb(CARD))
        self._border = Image.new("L", (self.box, self.box), 255)
        ImageDraw.Draw(self._border).rectangle(
            (0, 0, self.box - 1, self.box - 1), outline=0)
        self._plate = self._bake_plate()
        self._stroke = self._reduce(self._mask_stroke())
        self._lamp = self._reduce(self._mask_lamp())
        self._glow = self._reduce(ImageChops.multiply(self._mask_glow(),
                                                      self._mask_tile()))
        self._fg = Image.new("RGBA", (self.box, self.box), rgb(FG) + (255,))

    # ----------------------------------------------------------- units
    def _at(self, x: float, y: float) -> tuple[float, float]:
        """A grid point in supersampled pixels: the grid at SCALE of the
        tile, centred on it, the way make_logo.mark(scale=0.94) draws it."""
        unit = self.tile / GRID * SUPER
        off = self._tile_box[0]
        mid = GRID / 2
        return (off + (mid + (x - mid) * SCALE) * unit,
                off + (mid + (y - mid) * SCALE) * unit)

    def _box(self, x0: float, y0: float, x1: float, y1: float) -> list:
        return [*self._at(x0, y0), *self._at(x1, y1)]

    def _reduce(self, image):
        return image.reduce(SUPER)

    # ----------------------------------------------------------- masks
    def _mask_tile(self):
        mask = Image.new("L", (self._S, self._S), 0)
        _rr(ImageDraw.Draw(mask), self._tile_box, self._radius, fill=255)
        return mask

    def _mask_stroke(self):
        """The corner, as one area: the ring round the lamp kept to the
        quadrant the path turns through (x >= 30, y <= 34), and the two
        legs, whose edges are the ring's own ends."""
        cx, cy, inner, outer = RING
        ring = Image.new("L", (self._S, self._S), 0)
        r = ImageDraw.Draw(ring)
        r.ellipse(self._box(cx - outer, cy - outer, cx + outer, cy + outer),
                  fill=255)
        r.ellipse(self._box(cx - inner, cy - inner, cx + inner, cy + inner),
                  fill=0)
        r.rectangle(self._box(-2, -2, cx, 66), fill=0)
        r.rectangle(self._box(-2, cy, 66, 66), fill=0)
        stroke = Image.new("L", (self._S, self._S), 0)
        s = ImageDraw.Draw(stroke)
        s.rectangle(self._box(*TOP), fill=255)
        s.rectangle(self._box(*SIDE), fill=255)
        stroke.paste(ring, (0, 0), ring)
        return stroke

    def _mask_lamp(self):
        cx, cy, r = LAMP
        mask = Image.new("L", (self._S, self._S), 0)
        ImageDraw.Draw(mask).ellipse(self._box(cx - r, cy - r, cx + r, cy + r),
                                     fill=255)
        return mask

    def _mask_glow(self):
        """The lamp's light on the tile: a radial ramp out to the ring's
        inner edge — the inside of the curve is lit, the stroke on top of
        it is not — drawn as concentric discs, then softened."""
        cx, cy = self._at(*LAMP[:2])
        reach = GLOW * SCALE * self.tile / GRID * SUPER
        mask = Image.new("L", (self._S, self._S), 0)
        draw = ImageDraw.Draw(mask)
        steps = max(8, int(reach))
        for i in range(steps):
            r = reach * (1 - i / steps)
            alpha = int(255 * 0.80 * (i / steps) ** 1.3)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=alpha)
        return mask.filter(ImageFilter.GaussianBlur(0.5 * SUPER))

    # ----------------------------------------------------------- plate
    def _bake_plate(self):
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
            outline=(255, 255, 255, RIM_A), width=SUPER)
        img = Image.alpha_composite(img, rim)
        return self._finish(self._reduce(img))

    def _finish(self, image):
        """Alpha 0 on the whole border, whatever the blur reached."""
        image.putalpha(ImageChops.multiply(image.getchannel("A"),
                                           self._border))
        return image

    # ----------------------------------------------------------- frame
    def frame(self, lamp_rgb, glow: float = 1.0):
        """One picture of the mark: the lamp in `lamp_rgb`, its light
        inside the curve at `glow` (0 = none). The boot card breathes it
        while the model loads and holds it at 1 once the app is ready."""
        img = self._plate.copy()
        colour = Image.new("RGBA", (self.box, self.box),
                           tuple(int(c) for c in lamp_rgb) + (255,))
        k = 0.0 if glow <= 0 else 1.0 if glow >= 1 else float(glow)
        if k > 0.004:
            mask = self._glow if k >= 0.999 else \
                self._glow.point(lambda v: int(v * k))
            img.paste(colour, (0, 0), mask)
        img.paste(self._fg, (0, 0), self._stroke)
        img.paste(colour, (0, 0), self._lamp)
        return img


__all__ = ["Mark", "SUPER", "RADIUS", "LAMP", "RING", "TOP", "SIDE", "SCALE"]
