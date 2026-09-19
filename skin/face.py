"""A card's face, drawn by Pillow: the shadow, the surface, the rim.

boot.Card._plate_image and the skia cards paint the same thing — six
offset round-rects of decaying alpha for a shadow, a face a hair lighter
at the top than the bottom, a LINE hairline round it and a specular
hairline along 60% of the top edge. This is that recipe for the painters
that cannot assume Skia (a fresh install has none: the skin pack is a
download), so the card a stranger sees on first launch is the card the
owner sees, and not a Tk frame.

Two things Pillow gets wrong by default, and how they are handled here:

* **ImageDraw antialiases nothing.** A rounded corner drawn at 1 x is a
  staircase. Every shape is drawn at SS x into an L mask and reduced with
  a box filter, which gives 16 coverage levels per pixel — enough for a
  20 px radius to read as a curve — and, because a box filter samples only
  its own block, a mask that is empty at the edge stays exactly 0 there.

* **ImageDraw's `fill` REPLACES pixels; it does not blend.** A translucent
  rounded rectangle drawn straight onto a translucent face punches a hole
  in it (AGENTS.md). So `shape()` returns a LAYER to alpha-composite, and
  nothing here draws on the picture itself.

Everything here is drawn ONCE per card and kept; a frame is composed on
top of the plate. The shadow is a real Gaussian blur rather than the
stacked round-rects, because Pillow's blur is one C pass over a small
image and the stacking was a Skia-side economy.
"""
from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .palette import BG, CARD, FG, LINE, rgb

SS = 4                    # the supersampling every shape is drawn at
SHADOW = 26               # px of room a card leaves around itself
SHADOW_A = 118            # the shadow's core alpha
SHADOW_BLUR = 9.0         # px
SHADOW_DROP = 5           # px, downward
FACE_A = 252              # boot.py's; the hint card uses less and shows frost
SPEC_A = 46               # the specular hairline's peak alpha


def _big(box):
    """A 1 x box of inclusive pixel edges, at SS x."""
    x0, y0, x1, y1 = box
    return (x0 * SS, y0 * SS, (x1 + 1) * SS - 1, (y1 + 1) * SS - 1)


def rounded(size, box, radius: float, fill: int = 255) -> Image.Image:
    """An antialiased L mask of one rounded rectangle, `size` wide."""
    W, H = size
    big = Image.new("L", (W * SS, H * SS), 0)
    ImageDraw.Draw(big).rounded_rectangle(_big(box), radius=radius * SS,
                                          fill=fill)
    return big.reduce(SS)


def shape(size, box, radius: float, fill=None, outline=None,
          width: float = 1.0) -> Image.Image:
    """A rounded rectangle as an RGBA layer to composite — antialiased,
    and drawn at SS x over its own bounding box only, so a key cap does
    not cost a whole card's worth of pixels. `fill` and `outline` are
    (r, g, b, a)."""
    x0, y0, x1, y1 = (int(v) for v in box)
    x0, y0 = max(0, x0 - 1), max(0, y0 - 1)
    x1, y1 = min(size[0] - 1, x1 + 1), min(size[1] - 1, y1 + 1)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    if w <= 0 or h <= 0:
        return layer
    local = (box[0] - x0, box[1] - y0, box[2] - x0, box[3] - y0)
    patch = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if fill is not None:
        mask = Image.new("L", (w * SS, h * SS), 0)
        ImageDraw.Draw(mask).rounded_rectangle(_big(local), radius=radius * SS,
                                               fill=255)
        patch.alpha_composite(text_layer(
            (w, h), fill[:3], mask.reduce(SS).point(lambda v: v * fill[3] // 255)))
    if outline is not None:
        mask = Image.new("L", (w * SS, h * SS), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            _big(local), radius=radius * SS, outline=255,
            width=max(1, int(round(width * SS))))
        patch.alpha_composite(text_layer(
            (w, h), outline[:3],
            mask.reduce(SS).point(lambda v: v * outline[3] // 255)))
    layer.paste(patch, (x0, y0))
    return layer


def disc(size, cx: float, cy: float, r: float, colour) -> Image.Image:
    """An antialiased disc as an RGBA layer; `colour` is (r, g, b, a)."""
    x0, y0 = int(cx - r) - 1, int(cy - r) - 1
    w = h = int(r * 2) + 4
    mask = Image.new("L", (w * SS, h * SS), 0)
    ImageDraw.Draw(mask).ellipse(((cx - r - x0) * SS, (cy - r - y0) * SS,
                                  (cx + r - x0) * SS, (cy + r - y0) * SS),
                                 fill=255)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.paste(text_layer((w, h), colour[:3],
                           mask.reduce(SS).point(lambda v: v * colour[3] // 255)),
                (x0, y0))
    return layer


def text_layer(size, colour, alpha_mask) -> Image.Image:
    """A flat colour cut to an alpha mask, ready to composite."""
    layer = Image.new("RGBA", size, tuple(colour) + (0,))
    layer.putalpha(alpha_mask)
    return layer


def plate(width: int, height: int, radius: float, inset: int = SHADOW,
          face_alpha: int = FACE_A, backdrop=None) -> Image.Image:
    """The card's static picture, `inset` px of shadow room on each side:
    (width + 2 * inset) x (height + 2 * inset). `backdrop` is an optional
    RGBA picture of what is behind the card (blurred, for frost), cut to
    the card's shape under the face."""
    W, H = width + inset * 2, height + inset * 2
    x0 = y0 = inset
    box = (x0, y0, x0 + width - 1, y0 + height - 1)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    shadow = rounded((W, H), (x0, y0 + SHADOW_DROP, x0 + width - 1,
                              y0 + height - 1 + SHADOW_DROP), radius, SHADOW_A)
    shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    img = Image.alpha_composite(img, text_layer((W, H), (0, 0, 0), shadow))

    form = rounded((W, H), box, radius)
    if backdrop is not None:
        frost = backdrop.convert("RGBA").resize((W, H))
        frost.putalpha(ImageChops.multiply(frost.getchannel("A"), form))
        img = Image.alpha_composite(img, frost)

    # the face: CARD at the top down to BG at the bottom — a surface lit
    # from above, which is what makes a dark card read as lit rather than
    # printed
    top, bottom = rgb(CARD), rgb(BG)
    grad = Image.linear_gradient("L").resize((W, H))
    face = Image.new("RGBA", (W, H), top + (255,))
    face.paste(Image.new("RGBA", (W, H), bottom + (255,)), (0, 0), grad)
    face.putalpha(form.point(lambda v: v * face_alpha // 255))
    img = Image.alpha_composite(img, face)

    img = Image.alpha_composite(img, shape((W, H), box, radius,
                                           outline=rgb(LINE) + (190,)))

    # a specular hairline on the top edge only, 60% of the width, fading
    # at both ends — the cheapest thing that says "glass"
    spec = Image.new("L", (W, 1), 0)
    left, span = int(x0 + width * 0.20), int(width * 0.60)
    for i in range(span):
        k = 1.0 - abs(i / max(1, span - 1) - 0.5) * 2.0
        spec.putpixel((left + i, 0), int(SPEC_A * k))
    line = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    line.paste(text_layer((W, 1), rgb(FG), spec), (0, y0))
    return Image.alpha_composite(img, line)


def rule(size, x0: float, x1: float, y: float, colour) -> Image.Image:
    """A one-pixel horizontal hairline as a layer; `colour` is (r, g, b, a)."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).line((x0, y, x1, y), fill=tuple(colour), width=1)
    return layer


__all__ = ["plate", "rounded", "shape", "disc", "rule", "text_layer",
           "SHADOW"]
