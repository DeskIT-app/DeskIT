"""A card's face, drawn by Pillow: the shadow, the surface, the rim.

Since 2026-10-23 the pane itself is B+'s and comes from look.py (`plate`
hands over to look.plate: the desk's glass at the desktop's density, its
frosted rim and its long soft shadow); what is left here are the small
shapes the key card still draws its marks with. The point of the module
stands: the card a stranger sees on first launch, with no skia, is the
card the owner sees, and not a Tk frame.

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

from PIL import Image, ImageDraw

SS = 4                    # the supersampling every shape is drawn at
SHADOW = 26               # px of room a card leaves around itself
FACE_A = 252              # kept for callers that still pass one


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
    the card's shape under the face.

    B+ SINCE 2026-10-23: the pane is look.plate's — the desk's glass at
    the desktop's density, its frosted rim and its long soft shadow — so
    the key card and the move card sit on the pane every other card does.
    `face_alpha` is no longer read (the density is the palette's,
    GLASS_A_TOP / GLASS_A_BOT)."""
    import look
    return look.plate(int(width), int(height), radius, int(inset),
                      frost=backdrop, shadow=inset > 0)


def rule(size, x0: float, x1: float, y: float, colour) -> Image.Image:
    """A one-pixel horizontal hairline as a layer; `colour` is (r, g, b, a)."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).line((x0, y, x1, y), fill=tuple(colour), width=1)
    return layer


__all__ = ["plate", "rounded", "shape", "disc", "rule", "text_layer",
           "SHADOW"]
