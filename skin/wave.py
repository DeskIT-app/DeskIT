"""The microphone wave in the ask-the-screen card.

WHAT WAS THERE. Four `create_oval` outlines around the dot, one per recent
loudness sample, radius growing with age. The idea is right — a wave that
radiates from the thing you are talking at says WHERE the sound is going —
and it is kept. What is replaced is the drawing: Tk antialiases nothing
(measured on this machine: a 400x400 grab of canvas primitives contained
exactly two distinct colours), so every one of those circles was a
stair-cased 1 px hoop, and an outline cannot fade, because a fade needs
partial alpha and a canvas item has none.

WHY NOT SKIA HERE, WHEN EVERYTHING ELSE IN skin\ IS SKIA. The ask card is
a Tk window the owner can drag, sitting on a PIL bitmap of frozen desktop.
A layered window floating over it would have to chase it every frame and
would be wrong the moment the drag outran it. So the wave stays a canvas
item — but a canvas IMAGE, not a canvas oval, and the image is a ring
Pillow drew at 4x and shrank with LANCZOS. Tk composites an RGBA
PhotoImage against what is under it, so the ring gets real antialiasing
AND a real alpha falloff, on the toolkit that has neither.

AND WHY IT IS STILL CHEAP. AGENTS.md's rule for this card is that the
frame must never wait on its content: a repaint is tens of milliseconds
and this runs on a 15 ms tick, so the rings may not be painted into the
bitmap. They are not. Each ring is rasterised ONCE, cached on its
quantised (radius, age), and every later frame is an itemconfig and a
coords — the same cost the ovals had.

A PhotoImage belongs to the interpreter that made it, and visual_qa stands
up a fresh Tk for every press, so the cache is keyed on the interpreter
and dropped when a new one appears. Handing a stale image to a new Tk
raises "image doesn't exist", which is the bug ui.forget_images() exists
to prevent in the dashboard.
"""
from __future__ import annotations

import logging

from .palette import LIGHT_ACCENT, LIGHT_CORE, LIGHT_MID, lerp_rgb

_log = logging.getLogger("app")

RINGS = 5                 # up from 4; more than this and the rings
#                           merge into a bullseye rather than reading
#                           as separate moments travelling outward
MAX_R = 36                # px. Must not cross the chips above or the key
#                           beside it — "relatively big" was the complaint
#                           the four-ring version was already answering.
STEP = 2                  # radius quantisation, in px, for the cache key

_cache: dict = {}
_owner = None             # the interpreter the cached images belong to


def _sprite(radius: int, age: int, width: float, tint):
    """One antialiased ring as an RGBA PhotoImage, cached."""
    from PIL import Image, ImageDraw, ImageTk
    key = (radius, age)
    got = _cache.get(key)
    if got is not None:
        return got
    s = 4                                   # supersample, then LANCZOS down
    box = (radius + 3) * 2
    img = Image.new("RGBA", (box * s, box * s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # three concentric strokes with geometrically decaying alpha: a ring
    # with a soft shoulder rather than a hoop with a hard edge
    for i, (grow, mul) in enumerate(((1.9, 0.16), (1.0, 0.42), (0.0, 1.0))):
        w = max(1.0, width * (1 + grow * 1.5)) * s
        r = radius * s
        draw.ellipse((box * s / 2 - r, box * s / 2 - r,
                      box * s / 2 + r, box * s / 2 + r),
                     outline=tuple(tint) + (int(215 * mul),), width=int(w))
    img = img.resize((box, box), Image.LANCZOS)
    photo = ImageTk.PhotoImage(img)
    _cache[key] = photo
    return photo


def paint(card) -> bool:
    """Redraw the rings. True means the skin handled it.

    Given the card itself because the original method reads five of its
    attributes and writes one; taking them apart here would put the same
    five in two places, and the whole point of a hook is that the code it
    sits in front of does not change.
    """
    global _owner
    canvas = getattr(card, "canvas", None)
    if canvas is None:
        return False
    try:
        interp = canvas.tk
        if interp is not _owner:            # a new Tk: the old images are
            _cache.clear()                  # not this interpreter's to use
            _owner = interp

        for item in card._wave_items:
            canvas.delete(item)
        card._wave_items = []

        centre = card.surface.dot_centre
        levels = card._wave
        if centre is None or not levels:
            return True
        cx = centre[0] + card._cx
        cy = centre[1] + card._cy

        rings = levels[-RINGS:]
        for age, value in enumerate(reversed(rings)):
            # newest ring tight around the dot, oldest wide and faint —
            # each one is a moment of loudness travelling outward
            # 4.6 px between rings, not 3.4: at the tighter spacing the
            # strokes overlapped and the whole thing read as a target
            radius = 14 + age * 4.6 + float(value) * 5.5
            if radius > MAX_R:
                continue
            radius = int(round(radius / STEP)) * STEP
            fade = (1.0 - age / float(RINGS)) ** 1.9
            tint = lerp_rgb(LIGHT_CORE if age == 0 else LIGHT_MID,
                            LIGHT_ACCENT, 0.20 + 0.6 * (age / float(RINGS)))
            width = 1.7 * fade + 0.5
            photo = _sprite(radius, age, width, tint)
            item = canvas.create_image(cx, cy, image=photo)
            # Tk keeps no reference to a canvas image's PhotoImage, and the
            # cache is what stops it being collected mid-frame
            card._wave_items.append(item)
        for item in card._wave_items:
            canvas.tag_raise(item)
        return True
    except Exception:
        _log.debug("skin wave", exc_info=True)
        return False
