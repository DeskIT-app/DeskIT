"""A card's face, drawn by Pillow: the shadow, the surface, the rim.

boot.Card._plate_image and hint.draw paint the same thing in Skia — six
offset round-rects of decaying alpha for a shadow, a face a hair lighter
at the top than the bottom, a LINE hairline round it and a specular
hairline along 60% of the top edge. This is that recipe for the painters
that cannot assume Skia (a fresh install has none: the skin pack is a
download), so the card a stranger sees on first launch is the card the
owner sees, and not a Tk frame.

Everything here is drawn ONCE per card and kept; a frame is composed on
top of the plate. The shadow is a real Gaussian blur rather than the
stacked round-rects, because Pillow's blur is one C pass over a small
image and the stacking was a Skia-side economy.
"""
from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .palette import BG, CARD, FG, LINE, rgb

SHADOW = 26               # px of room a card leaves around itself
SHADOW_A = 118            # the shadow's core alpha
SHADOW_BLUR = 9.0         # px
SHADOW_DROP = 5           # px, downward
FACE_A = 252              # boot.py's; the hint card uses less and shows frost
SPEC_A = 46               # the specular hairline's peak alpha


def rounded(size, box, radius: float, fill=255) -> Image.Image:
    """An L mask of one rounded rectangle."""
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=fill)
    return mask


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

    shape = rounded((W, H), box, radius)
    if backdrop is not None:
        frost = backdrop.convert("RGBA").resize((W, H))
        frost.putalpha(ImageChops.multiply(frost.getchannel("A"), shape))
        img = Image.alpha_composite(img, frost)

    # the face: CARD at the top down to BG at the bottom — a surface lit
    # from above, which is what makes a dark card read as lit rather than
    # printed
    top, bottom = rgb(CARD), rgb(BG)
    grad = Image.linear_gradient("L").resize((W, H))
    face = Image.new("RGBA", (W, H), top + (255,))
    face.paste(Image.new("RGBA", (W, H), bottom + (255,)), (0, 0), grad)
    face.putalpha(shape.point(lambda v: v * face_alpha // 255))
    img = Image.alpha_composite(img, face)

    rim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle(box, radius=radius,
                                          outline=rgb(LINE) + (190,), width=1)
    img = Image.alpha_composite(img, rim)

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


__all__ = ["plate", "rounded", "text_layer", "SHADOW"]
