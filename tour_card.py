"""What the first-run tour says, and how a stop is drawn (D36).

THE TOUR IS THE GUIDE. The owner, 2026-09-18: the user's guide must be
minimal, and "not text — more like a square with an arrow, on the first
start, before you use it, with a skip". So the guide is four small cards
on the live desktop, right after the wizard's last page: a callout
beside the status dot with a beak pointing at it, one sentence each,
[Next] and [Skip]. The site under docs/ stays as the reference nobody
has to read. In ENGLISH since 2026-09-19 evening, the wizard's language
— he walked a fresh copy and "the guide is still in Hebrew" was the
one gap left; RTL below follows the words, so a Hebrew table would lay
itself out again from the right.

Split the way consent_card.py is split: this half owns the WORDS, the
GEOMETRY and the PICTURE — pure Python plus Pillow, no Tk, no window —
and overlay.TourCard owns the thread, the queue, the placement beside
the dot and the three answers. The words live here as data a test can
read; ``card_for`` hands a stop out with the key's name filled in,
because which key is the hold key is the person's setting, not ours.

THE BEAK. A stop that points at something carries a triangle on the
edge of the card that faces it — the "arrow" he asked for. Where the
beak goes is the presenter's to decide (it knows where the dot is and
where the card landed); ``frame`` says how much room the window needs
for it and ``flat`` paints it. The window is chroma-keyed around the
card so the beak stands out of a rectangle; the key colour is the
presenter's, passed in.

Everything geometric is a function of the card dict and the scale;
``regions()`` is what both the painter and the hit test read, which is
what keeps a button drawn where it is pressed.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

import review_card as rc
from review_card import (ACCENT, ACCENT_HI, ACCENT_ON, CARD, EDGE, EDGE_HI,
                         HTCAPTION, HTCLIENT, HTTRANSPARENT, INK, INK_DIM,
                         INK_FAINT, LINE, _rr, _text, clamp_scale)

NEXT, SKIP, DONE, DRAG = "next", "skip", "done", "drag"
LABELS = {NEXT: "Next", SKIP: "Skip", DONE: "Done"}
SIDES = ("top", "bottom", "left", "right")     # which edge the beak is on

CARD_W = 340
RADIUS = 18
PAD = 16
TITLE_PT = 12.5
BODY_PT = 10.0
STEP_PT = 8.0
BTN_H = 30
BTN_GAP = 8
BTN_W = {NEXT: 84, SKIP: 76, DONE: 104}        # at 1.0
TAIL = 14                                      # the beak's length
TAIL_W = 26                                    # its base
KEY_H = 40                                     # the keycap picture
KEY_PAD = 16

# The words. `tail` is whether the card points at the thing it names;
# `picture` names what is drawn between the title and the body. The
# last stop has one button; every other stop has two.
STOPS = (
    {"kind": "dot", "tail": True, "picture": None,
     "title": "This is the dot",
     "body": ("Its colour says what is happening: blue — listening. "
              "Red — recording. Gold — working on what you said.")},
    {"kind": "key", "tail": False, "picture": "key",
     "title": "The key",
     "body": ("Hold, talk, let go — and the text is pasted where your "
              "cursor stands, in any program.")},
    {"kind": "shelf", "tail": True, "picture": None,
     "title": "A click on the dot",
     "body": ("Opens a small shelf: what is waiting for you, the last "
              "sentence you said, and a door to the desk — settings, "
              "history, reporting a problem.")},
    {"kind": "done", "tail": False, "picture": None,
     "title": "That is it",
     "body": ("You can see this tour again from Settings > The app. "
              "Enjoy.")},
)

#: The words' direction: Hebrew lays out from the right, English from
#: the left. Decided from the table, so the layout follows the words.
RTL: bool = any("\u0590" <= ch <= "\u05FF" for stop in STOPS for ch in stop["title"] + stop["body"])


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------

def card_for(index: int, key: str = "") -> dict:
    """Stop `index` as data: what overlay.TourCard queues and every
    painter consumes. `key` is the hold key's pretty name for the
    picture on the key stop."""
    stop = STOPS[index]
    last = index == len(STOPS) - 1
    return {"index": index, "count": len(STOPS), "kind": stop["kind"],
            "title": stop["title"], "body": stop["body"],
            "tail": bool(stop["tail"]), "picture": stop["picture"],
            "key": key, "buttons": (DONE,) if last else (NEXT, SKIP)}


# ---------------------------------------------------------------------------
# the layout — measured by rendering, which is why every function here
# takes the cache
# ---------------------------------------------------------------------------

def _body(cache: dict, text: str, pt: float, width: int, colour=INK):
    """A wrapped paragraph, right-to-left, cropped to its glyphs — the
    consent card's recipe."""
    key = ("block", text, round(pt, 2), width, colour)
    img = cache.get(key)
    if img is None:
        from visual_qa import text_pil
        img = text_pil(text, max(40, int(width)), pt=pt, colour=colour,
                       rtl=RTL, single=False)
        box = img.getchannel("A").getbbox()
        if box:
            img = img.crop((0, box[1], img.width, box[3]))
        cache[key] = img
    return img


def _keycap(cache: dict, name: str, s: float):
    """One key, drawn as a cap: a rounded face with a darker lip under
    it and the key's name across it. The picture on the key stop."""
    key = ("keycap", name, round(s, 3))
    img = cache.get(key)
    if img is None:
        label = _text(cache, name or "?", 11.0 * s, colour=INK, weight=600,
                      rtl=False)
        h = int(round(KEY_H * s))
        w = max(int(round(64 * s)), label.width + int(round(2 * KEY_PAD * s)))
        lip = max(2, int(round(3 * s)))
        img = Image.new("RGBA", (w, h + lip), (0, 0, 0, 0))
        img.alpha_composite(_rr((w, h), 8 * s, fill=LINE + (255,)), (0, lip))
        img.alpha_composite(_rr((w, h), 8 * s, fill=EDGE_HI + (255,),
                                outline=LINE + (255,), width=1), (0, 0))
        img.alpha_composite(label, (int((w - label.width) / 2),
                                    int((h - label.height) / 2)))
        cache[key] = img
    return img


def layout(card: dict, scale: float = 1.0, cache: dict | None = None) -> dict:
    """Where everything goes at `scale`: the rendered pieces and their
    y positions, and the CARD's size (the beak is the frame's). One
    walk, shared by measure, regions and compose."""
    cache = cache if cache is not None else {}
    s = clamp_scale(scale)
    width = int(round(CARD_W * s))
    pad = PAD * s
    inner = int(width - 2 * pad)
    y = pad
    step = _text(cache, f"{card['index'] + 1} / {card['count']}",
                 STEP_PT * s, colour=INK_FAINT, weight=600, rtl=False)
    title = _text(cache, card["title"], TITLE_PT * s, weight=600, rtl=RTL)
    items = [("step", step, y), ("title", title, y)]
    y += max(title.height, step.height) + 8 * s
    if card["picture"] == "key":
        cap = _keycap(cache, card["key"], s)
        items.append(("key", cap, y))
        y += cap.height + 10 * s
    body = _body(cache, card["body"], BODY_PT * s, inner)
    items.append(("body", body, y))
    y += body.height + 14 * s
    buttons_y = y
    y += BTN_H * s + pad
    return {"scale": s, "width": width, "height": int(round(y)),
            "items": items, "buttons_y": buttons_y, "pad": pad}


def measure(card: dict, scale: float = 1.0,
            cache: dict | None = None) -> tuple[int, int]:
    """The card alone, without the beak."""
    lay = layout(card, scale, cache)
    return lay["width"], lay["height"]


def frame(card: dict, scale: float = 1.0, side: str | None = None,
          cache: dict | None = None) -> tuple[int, int, int, int]:
    """The WINDOW: (width, height, card_x, card_y) — the card plus the
    beak's room on `side`, and where the card sits inside. None is a
    card with no beak, which is the card exactly."""
    w, h = measure(card, scale, cache)
    if side is None or not card["tail"]:
        return w, h, 0, 0
    t = int(round(TAIL * clamp_scale(scale)))
    if side == "top":
        return w, h + t, 0, t
    if side == "bottom":
        return w, h + t, 0, 0
    if side == "left":
        return w + t, h, t, 0
    if side == "right":
        return w + t, h, 0, 0
    raise ValueError(f"not a side: {side!r}")


def clamp_tail(card: dict, scale: float, side: str, at: float,
               cache: dict | None = None) -> int:
    """The beak's position along `side` (pixels from that edge's start,
    on the card), kept off the rounded corners."""
    w, h = measure(card, scale, cache)
    s = clamp_scale(scale)
    span = w if side in ("top", "bottom") else h
    edge = RADIUS * s + TAIL_W * s / 2
    return int(round(max(edge, min(span - edge, at))))


def regions(card: dict, scale: float = 1.0, cache: dict | None = None,
            side: str | None = None) -> dict:
    """The rectangles that take the mouse, window-relative. Buttons
    right to left along the bottom; the rest of the card is the handle
    you drag it by; the beak and the chroma around it belong to nobody."""
    lay = layout(card, scale, cache)
    s, width, height = lay["scale"], lay["width"], lay["height"]
    _fw, _fh, x0, y0 = frame(card, s, side, cache)
    pad = lay["pad"]
    y_top = y0 + lay["buttons_y"]
    y1 = y_top + BTN_H * s
    x = x0 + width - pad
    out = {}
    for name in card["buttons"]:
        bw = BTN_W[name] * s
        out[name] = (x - bw, y_top, x, y1)
        x -= bw + BTN_GAP * s
    out[DRAG] = (x0, y0, x0 + width, y0 + height)
    return out


def hit_test(card: dict, scale: float, x: int, y: int,
             cache: dict | None = None, side: str | None = None):
    boxes = regions(card, scale, cache, side)
    for name in card["buttons"]:
        if rc._in(boxes[name], x, y):
            return HTCLIENT, name
    if rc._in(boxes[DRAG], x, y):
        return HTCAPTION, DRAG
    return HTTRANSPARENT, None


# ---------------------------------------------------------------------------
# the picture
# ---------------------------------------------------------------------------

def compose(card: dict, scale: float = 1.0, hover: str | None = None,
            cache: dict | None = None):
    """The card's CONTENT as one RGBA image the size of measure(), on a
    transparent ground."""
    cache = cache if cache is not None else {}
    lay = layout(card, scale, cache)
    s, width, height = lay["scale"], lay["width"], lay["height"]
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    right = width - lay["pad"]
    left = lay["pad"]
    # The words' edge and the counter's: right and left for Hebrew, the
    # mirror for English. The buttons stay at the right in both — the
    # way on is the rightmost thing, as on the wizard's foot.
    for kind, piece, y in lay["items"]:
        if kind == "step":
            x = left if RTL else right - piece.width
            img.alpha_composite(piece, (int(x), int(y + 2 * s)))
        else:
            x = right - piece.width if RTL else left
            img.alpha_composite(piece, (int(x), int(y)))
    boxes = regions(card, s, cache)
    for name in card["buttons"]:
        bx0, by0, bx1, by1 = boxes[name]
        hot = hover == name
        if name in (NEXT, DONE):
            face = _rr((bx1 - bx0, by1 - by0), 9 * s,
                       fill=(ACCENT_HI if hot else ACCENT) + (255,))
            colour = ACCENT_ON
        else:
            face = _rr((bx1 - bx0, by1 - by0), 9 * s,
                       fill=(EDGE_HI if hot else EDGE) + (255,),
                       outline=LINE + (255,))
            colour = INK
        img.alpha_composite(face, (int(bx0), int(by0)))
        lab = _text(cache, LABELS[name], 9.5 * s, colour=colour, weight=600, rtl=RTL)
        img.alpha_composite(lab, (int((bx0 + bx1) / 2 - lab.width / 2),
                                  int((by0 + by1) / 2 - lab.height / 2)))
    return img


def flat(card: dict, scale: float = 1.0, hover: str | None = None,
         cache: dict | None = None, side: str | None = None,
         at: int | None = None, chroma=(11, 12, 13)):
    """The card on a solid face inside its frame: a rounded card in the
    fallback palette, the content on top, the beak on `side` at `at`
    (pixels along that edge, from clamp_tail), and the chroma colour
    everywhere else — the window keys that colour out, so the beak
    stands proud of the rectangle. RGB, because the key is a colour."""
    cache = cache if cache is not None else {}
    s = clamp_scale(scale)
    w, h = measure(card, s, cache)
    fw, fh, cx, cy = frame(card, s, side, cache)
    img = Image.new("RGBA", (fw, fh), tuple(chroma) + (255,))
    beak = side if (side is not None and card["tail"]) else None
    if beak is not None:
        t = fw - w if beak in ("left", "right") else fh - h
        half = TAIL_W * s / 2
        p = clamp_tail(card, s, beak, at if at is not None else 0, cache)
        if beak == "bottom":
            tri = [(cx + p - half, cy + h - 1), (cx + p + half, cy + h - 1),
                   (cx + p, cy + h + t - 1)]
        elif beak == "top":
            tri = [(cx + p - half, cy), (cx + p + half, cy), (cx + p, 0)]
        elif beak == "right":
            tri = [(cx + w - 1, cy + p - half), (cx + w - 1, cy + p + half),
                   (cx + w + t - 1, cy + p)]
        else:
            tri = [(cx, cy + p - half), (cx, cy + p + half), (0, cy + p)]
        big = Image.new("RGBA", (fw * 4, fh * 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        d.polygon([(x * 4, y * 4) for x, y in tri], fill=CARD + (255,),
                  outline=LINE + (255,), width=4)
        img.alpha_composite(big.resize((fw, fh), Image.LANCZOS))
    # A rounded face on a clear ground, so the corners key out too.
    face = _rr((w, h), RADIUS * s, fill=CARD + (255,),
               outline=LINE + (255,), width=1)
    face.alpha_composite(compose(card, s, hover, cache))
    if beak is not None:
        # The card's outline runs across the beak's base; the beak's own
        # fill, laid over it, opens the base so the two read as one shape.
        t = fw - w if beak in ("left", "right") else fh - h
        half = TAIL_W * s / 2 - 1
        p = clamp_tail(card, s, beak, at if at is not None else 0, cache)
        d = ImageDraw.Draw(face)
        if beak == "bottom":
            d.line([(p - half, h - 1), (p + half, h - 1)], fill=CARD + (255,))
        elif beak == "top":
            d.line([(p - half, 0), (p + half, 0)], fill=CARD + (255,))
        elif beak == "right":
            d.line([(w - 1, p - half), (w - 1, p + half)], fill=CARD + (255,))
        else:
            d.line([(0, p - half), (0, p + half)], fill=CARD + (255,))
    img.alpha_composite(face, (cx, cy))
    return img.convert("RGB")


__all__ = ["STOPS", "card_for", "layout", "measure", "frame", "clamp_tail",
           "regions", "hit_test", "compose", "flat", "NEXT", "SKIP", "DONE",
           "DRAG", "LABELS", "SIDES", "TAIL", "TAIL_W", "CARD_W"]
