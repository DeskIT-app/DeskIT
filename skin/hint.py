"""The hint card, on glass.

overlay.HintCard owns the thread, the queue and the delay; this owns the
picture, and — because a picture you can drag has to know where it is —
the four things the owner can change about it: where it sits, how big it
is, closing it for this dictation, and whether it comes back at all.

WHAT IT LOOKS LIKE, SINCE 2026-09-24. A LAMPLIGHT card — face.py's plate,
the same shadow, surface and rim as the boot card — with the state bead,
the title and its one-line sub on the right of ONE head line, the X and
the two size buttons at its left, and the keys in their three groups
(hint.py names them) laid out in TWO COLUMNS: the dictation and the
screen on the right, where a Hebrew reader starts, "more" on the left.
Every key cap is one width, so each column reads as a column, and the
card is exactly as wide as its words — nothing is reserved for text that
is not there.

WHY TWO COLUMNS AND WHY THE WIDTH FOLLOWS THE WORDS. The owner's clip of
2026-09-24: "if I make it bigger it takes half the screen, and at a size
that is reasonable for the screen I cannot read it — it squeezes
everything and the letters come out pixelated and tiny". Measured on the
card as it was: ONE column of fourteen keys, 340 px wide with the labels
at 10 pt, so a third of every row was empty on the left while the height
was all rows — 652 px at 1.0, 913 at 1.4, on a 1080-line screen. He had
pressed − down to 0.6, where a label was 8 px. Two columns halve the
height (352 px at 1.0), the text is 12 pt (16 px at 1.0, 12.8 at the
smallest size, which is 0.8 now), and the empty third is gone because
the width is measured, not chosen.

THE BOX AND THE X, SINCE THE SAME DAY. The "don't show this again" row
used to turn the card off on the first click, which read as a checkbox
that cannot be checked. His words: an X at the top that closes, and a
box that only ticks — "X without the tick and it is gone for this
dictation and back on the next one; ticked, then X, and it is gone and
does not come back". A tick left on the box when the card goes away on
its own (the key let go) counts too: nobody ticks "don't show this
again" to see it next time. overlay.HintCard holds the tick and the
"closed for now"; this module draws them and reports the clicks.

AND IT IS PAINTED BY PILLOW, so a fresh install — which has no skia; that
is the skin pack — gets this card and not overlay._hint_paint's flat Tk
canvas. `paint()` is the picture; `draw()` puts it on a skia canvas for
the path that has one; `run()` hands it to the window with
glass.present(), which needs neither.

THREE THINGS THIS DOES THAT THE OTHER TWO OVERLAYS DO NOT.

* **It has text to read**, and the text is Hebrew with Latin key names in
  it. Pillow's own text has no bidi and no shaping, so every line here
  would come out backwards. Every string therefore goes through
  `visual_qa.text_pil`, which is Windows' DrawTextW + DT_RTLREADING
  rendered white-on-black so the luminance is the alpha — the one bidi
  path in this repo that was checked glyph by glyph (popup.py), and the
  same one the ask card uses.

  That function right-aligns inside the width it is HANDED and clips the
  rest, and its pixel size is `pt` scaled by the screen DPI — so a width
  guessed in points truncates every long label on a 150% display. Nothing
  here guesses: strings are rendered wide and cropped to their alpha box,
  and the card's width is the sum of those crops. They are kept
  (`_MEMO`, Pillow images only — never a Tk object at module level),
  because the hit test asks for the layout on every mouse message.

* **It redraws only when something changed.** The dot animates and the
  boot card animates; this one is a static panel that sits on screen for
  seconds *while two Whisper models want the GPU*. A frame loop here
  would be spending the one resource the dictation is waiting for.

* **It takes the mouse in five small rectangles and nowhere else.** The
  strip along the top drags it, `×` closes it, `−` and `+` resize it, the
  box at the bottom ticks, and every other pixel answers HTTRANSPARENT —
  so a click aimed at the close button of a maximised window underneath
  still lands on the close button. That is the trap the status dot paid
  for once already, and the reason this is a hit test rather than a
  plain clickable window.

WHERE IT SITS IS NOT WHERE THE DOT SITS. On the right-hand corners the
card is placed BESIDE the dot, never over or under it: the dot is the one
thing on screen that says the app is alive, and it does not move for a
panel that is only up while a key is down.
"""
from __future__ import annotations

import logging
import math
import queue
import time

from PIL import Image, ImageDraw

from .face import disc, plate, rule, shape
from .glass import (Glass, primary_screen, virtual_screen, work_area,
                    HTTRANSPARENT, HTCLIENT, HTCAPTION)
from .palette import (BG, LINE, FG, KEY_BG, KEY_EDGE, LINE_HI, DOT_STATES,
                      ACCENT, ACCENT_ON, rgb)

_log = logging.getLogger("app")

# Every length below is at scale 1.0 and multiplied by the scale; every
# text size is in points, which text_pil turns into pixels by the DPI.
RADIUS = 18
PAD = 16
HEAD_H = 34               # the head line: × − + on the left, title right
RULE_GAP = 8              # between a hairline and what is under it
GROUP_H = 22              # a group's heading and the hairline beside it
GROUP_GAP = 6             # between the last row of a group and the next
ROW_H = 28
CHIP_H = 22
CHIP_MIN_W = 50           # every key cap at least this wide: ONE column
CHIP_PAD = 10             # each side of the key's name inside its cap
LABEL_GAP = 11            # between a cap and its words
COL_GAP = 28              # between the two columns, at the least
MIN_INNER = 260           # the narrowest card, inside its padding
FOOT_H = 28               # the checkbox row
BOX = 16                  # the checkbox itself
SHADOW = 26               # room around the card for its own shadow
FACE_A = 216              # the face's alpha. boot.py uses 252; this is glass
BLUR = 11                 # px, the frost behind it
DOT_ROOM = 46             # the status dot's own corner, which is not ours
STEP = 0.1                # what one press of − or + is worth
# The card's own range sits INSIDE config.py's (0.6 .. 1.4, which the
# review and notify cards share): 0.8 is the smallest size at which a
# label is still 12.8 px. A 0.6 saved by the card before 2026-09-24 is
# brought up to 0.8 by clamp_scale, not refused.
SCALE_MIN, SCALE_MAX = 0.8, 1.4
BTN = 20                  # the ×, − and + squares
BTN_GAP = 4               # between − and +
CLOSE_GAP = 12            # between × and −, so a size press is not a close

PT_TITLE = 14.0
PT_SUB = 10.5
PT_LABEL = 12.0
PT_KEY = 10.5
PT_GROUP = 9.5
PT_FOOT = 10.5

INK = (241, 236, 226)        # FG      13.76:1 on the card
INK_DIM = (178, 168, 150)    # DIM      6.89:1
INK_FAINT = (126, 117, 100)  # FAINT    3.56:1 - labels and rules only
INK_KEY = rgb(FG)            # A KEY CHIP IS A KEY CAP, NOT A BUTTON.
#                              Fifteen chips in the accent turned this card
#                              into fifteen primary actions competing for
#                              one glance; it is a LEGEND. So the chips take
#                              ui.KeyCap's own face (KEY_BG on KEY_EDGE with
#                              the glyph in FG) and the only lit things left
#                              on the card are the state bead at the top and
#                              the box, once it is ticked.

# The state bead, taken from the dot's own table so the card and the dot in
# the corner can never disagree about what colour "recording" is.
DOTS = {name: rgb(DOT_STATES[name][0])
        for name in ("recording", "locked", "ready", "busy", "paused")}

# What a hit landed on, for the click handler. Kept as strings rather than
# rectangles on the instance so `regions()` can be tested without a window.
CLOSE, SMALLER, BIGGER, DISMISS, DRAG = (
    "close", "smaller", "bigger", "dismiss", "drag")

_text_pil = None
# Rendered strings and finished layouts, keyed by what they were made
# from. Pillow images and numbers only: nothing module-level may hold a Tk
# object (AGENTS.md), and nothing here is one.
_MEMO: dict = {}
_LAYOUTS: dict = {}
_MEMO_MAX = 600


def _text(text, pt=PT_LABEL, colour=INK, weight=400, rtl=True):
    """One line as an RGBA image, cropped to its glyphs.

    Cropping rather than trusting a width is not tidiness: see the module
    docstring — `pt` is scaled by the screen DPI, so any width picked here
    is wrong on a scaled display and the line loses its left-hand words.
    The same string at the same size is rendered once; callers only ever
    composite the image, never change it.
    """
    global _text_pil
    key = (text, round(float(pt), 3), tuple(colour), weight, rtl)
    img = _MEMO.get(key)
    if img is not None:
        return img
    if _text_pil is None:
        # Deferred, and deliberately not hoisted: importing visual_qa
        # builds Tk and pulls in the whole ask card, and this module is
        # reached for the first time in the middle of someone's dictation.
        from visual_qa import text_pil
        _text_pil = text_pil
    img = _text_pil(text or " ", 1400, pt=pt, colour=colour, weight=weight,
                    rtl=rtl, single=True)
    box = img.getchannel("A").getbbox()
    # Nothing drawn (an empty sub, a space) is one transparent pixel, not
    # the 1400 px it was rendered into — the card is as wide as its words.
    img = img.crop(box) if box else Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    if len(_MEMO) >= _MEMO_MAX:
        _MEMO.clear()
    _MEMO[key] = img
    return img


def _to_skia(img):
    import skia
    return skia.Image.frombytes(img.convert("RGBA").tobytes(), img.size,
                                skia.kRGBA_8888_ColorType)


def clamp_scale(scale: float) -> float:
    return max(SCALE_MIN, min(SCALE_MAX, round(float(scale), 3)))


def stepped(scale: float, by: float) -> float:
    """One press of − or +, from the size ON SCREEN and not the one
    saved: a 0.6 from before 2026-09-24 is drawn at 0.8, and 0.6 + 0.1
    would be a press of + that changes nothing."""
    return clamp_scale(clamp_scale(scale) + by)


def _groups(card: dict) -> list:
    """The card's groups, or — for a card built before groups existed —
    its two flat halves as two groups, so an old picture still draws."""
    groups = card.get("groups")
    if groups:
        return list(groups)
    out = []
    if card.get("rows"):
        out.append(("", card["rows"]))
    if card.get("keys"):
        out.append((card.get("section", ""), card["keys"]))
    return out


def _signature(card: dict) -> tuple:
    return (card.get("title", ""), card.get("sub", ""),
            card.get("footer", ""),
            tuple((name, tuple((k, lab, bool(on)) for k, lab, on in rows))
                  for name, rows in _groups(card)))


def _column_h(groups) -> float:
    """A column's height at scale 1.0: every group's heading and rows,
    and the gap between two groups (none after the last)."""
    if not groups:
        return 0.0
    h = sum(GROUP_H + ROW_H * len(rows) for _name, rows in groups)
    return h + GROUP_GAP * (len(groups) - 1)


def split(groups: list) -> list:
    """The groups as columns, right one first.

    One group is one column. More are cut at the group boundary that
    makes the taller column shortest, and a tie keeps more on the right,
    which is where a Hebrew reader starts. A group is never broken across
    two columns: its heading says what the rows under it are.
    """
    if len(groups) < 2:
        return [list(groups)]
    best = None
    for k in range(1, len(groups)):
        tall = max(_column_h(groups[:k]), _column_h(groups[k:]))
        if best is None or tall <= best[0]:
            best = (tall, k)
    k = best[1]
    return [list(groups[:k]), list(groups[k:])]


class _Layout:
    """Where everything goes, window-relative, for one card at one scale.

    Built once per (card, scale) and kept: the hit test asks for it on
    every mouse message over the window.
    """

    def __init__(self, card: dict, s: float) -> None:
        self.s = s
        pad = PAD * s
        groups = _groups(card)
        self.columns = split(groups)
        # ONE chip width for the whole card — the widest key plus its
        # padding, never under CHIP_MIN_W — so the caps make a column and
        # every label starts at the same edge.
        chips = [_text(key, pt=PT_KEY * s, weight=700, rtl=False).width
                 for _name, rows in groups for key, _label, _on in rows]
        self.chip_w = max([CHIP_MIN_W * s]
                          + [w + CHIP_PAD * 2 * s for w in chips])
        widths = []
        for column in self.columns:
            w = 0.0
            for name, rows in column:
                if name:
                    w = max(w, _text(name, pt=PT_GROUP * s,
                                     weight=600).width + 24 * s)
                for _key, label, _on in rows:
                    w = max(w, self.chip_w + LABEL_GAP * s
                            + _text(label, pt=PT_LABEL * s).width)
            widths.append(w)
        rows_w = sum(widths) + COL_GAP * s * (len(widths) - 1)
        title = _text(card.get("title", ""), pt=PT_TITLE * s, weight=600)
        sub = _text(card.get("sub", ""), pt=PT_SUB * s)
        buttons = (BTN * 3 + CLOSE_GAP + BTN_GAP) * s
        head_w = buttons + 18 * s + sub.width + 10 * s + title.width + 16 * s
        foot = _text(card.get("footer", ""), pt=PT_FOOT * s)
        foot_w = (BOX + 8) * s + foot.width
        inner = max(rows_w, head_w, foot_w, MIN_INNER * s)
        self.width = int(math.ceil(inner + 2 * pad))
        body = max(_column_h(c) for c in self.columns)
        self.height = int(round(
            (PAD + HEAD_H + RULE_GAP + body + RULE_GAP + FOOT_H + PAD - 4)
            * s))
        # The columns' right edges. Whatever the head or the footer asks
        # for beyond the rows goes into the gap, so the left column still
        # starts at the left padding and nothing is empty at an edge.
        x0 = SHADOW
        right = x0 + self.width - pad
        spare = inner - rows_w
        self.col_w = widths
        self.col_right = []
        edge = right
        for i, w in enumerate(widths):
            self.col_right.append(edge)
            edge -= w + COL_GAP * s + (spare if i == 0 else 0)
        self.right = right
        self.body_top = SHADOW + (PAD + HEAD_H + RULE_GAP) * s
        # the mouse's five rectangles
        y0 = SHADOW
        line_mid = y0 + pad + HEAD_H * s / 2 - 2 * s
        top = line_mid - BTN * s / 2
        close = (x0 + pad, top, x0 + pad + BTN * s, top + BTN * s)
        smaller = (close[2] + CLOSE_GAP * s, top,
                   close[2] + CLOSE_GAP * s + BTN * s, top + BTN * s)
        bigger = (smaller[2] + BTN_GAP * s, top,
                  smaller[2] + BTN_GAP * s + BTN * s, top + BTN * s)
        fy = y0 + self.height - (FOOT_H + PAD - 4) * s
        # the box and its words, not the whole row: the row is as wide as
        # two columns now, and its empty left half is the window behind
        words_left = right - (BOX + 8) * s - foot.width
        dismiss = (words_left - 6 * s, fy, right + 6, fy + FOOT_H * s - 4)
        drag = (x0, y0, x0 + self.width, y0 + (PAD + HEAD_H) * s)
        self.line_mid = line_mid
        self.foot_y = fy
        self.boxes = {CLOSE: close, SMALLER: smaller, BIGGER: bigger,
                      DISMISS: dismiss, DRAG: drag}


def _layout(card: dict, scale: float) -> _Layout:
    s = clamp_scale(scale)
    key = (_signature(card), s)
    hit = _LAYOUTS.get(key)
    if hit is None:
        hit = _Layout(card, s)
        if len(_LAYOUTS) >= 64:
            _LAYOUTS.clear()
        _LAYOUTS[key] = hit
    return hit


def measure(card: dict, scale: float = 1.0) -> tuple[int, int]:
    """The card's size, and therefore the window's: the height is
    arithmetic on the rows, the width is the words' own."""
    lay = _layout(card, scale)
    return lay.width, lay.height


def regions(card: dict, scale: float = 1.0) -> dict:
    """The five rectangles that take the mouse, window-relative.

    Returned as data so a test can check that they are inside the card,
    do not overlap, and move with the scale — none of which needs a
    window, a screen or a mouse.
    """
    return dict(_layout(card, scale).boxes)


def _in(box, x, y) -> bool:
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def hit_test(card: dict, scale: float, x: int, y: int):
    """(HT code, what was hit) for a point in window coordinates.

    Everything that is not one of the five rectangles is HTTRANSPARENT,
    which is what lets a click go through to the window underneath.
    """
    boxes = regions(card, scale)
    for name in (CLOSE, SMALLER, BIGGER, DISMISS):
        if _in(boxes[name], x, y):
            return HTCLIENT, name
    if _in(boxes[DRAG], x, y):
        return HTCAPTION, DRAG
    return HTTRANSPARENT, None


def _frost(x: int, y: int, width: int, height: int):
    """What is behind the card, blurred. None if it cannot be had."""
    try:
        from PIL import ImageGrab, ImageFilter
        shot = ImageGrab.grab(bbox=(x, y, x + width, y + height),
                              all_screens=True)
        if shot.size != (width, height):
            shot = shot.resize((width, height))
        return shot.convert("RGBA").filter(ImageFilter.GaussianBlur(BLUR))
    except Exception:
        _log.debug("skin: no frost behind the hint card", exc_info=True)
        return None


def _rrect(img, box, radius, fill=None, outline=None, width=1):
    """A rounded rectangle composited OVER the picture — antialiased, and
    a layer rather than a draw, because ImageDraw's fill replaces pixels,
    which on a translucent face punches a hole."""
    img.alpha_composite(shape(img.size, box, radius, fill, outline, width))


def _rule(img, x0, x1, y, colour):
    img.alpha_composite(rule(img.size, x0, x1, y, colour))


def _strokes(img, segments, colour, width) -> None:
    """Straight strokes with round ends, drawn 4x on their own rectangle
    and brought down with LANCZOS: Pillow antialiases nothing, and a
    glyph from the font sits wherever the font's box puts it, which in a
    20 px square is visibly off-centre."""
    ss = 4
    half = width / 2 + 2
    xs = [v for a, b, c, d in segments for v in (a, c)]
    ys = [v for a, b, c, d in segments for v in (b, d)]
    x0, y0 = int(math.floor(min(xs) - half)), int(math.floor(min(ys) - half))
    x1, y1 = int(math.ceil(max(xs) + half)), int(math.ceil(max(ys) + half))
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    big = Image.new("L", (w * ss, h * ss), 0)
    draw = ImageDraw.Draw(big)
    r = width * ss / 2
    for ax, ay, bx, by in segments:
        a = ((ax - x0) * ss, (ay - y0) * ss)
        b = ((bx - x0) * ss, (by - y0) * ss)
        draw.line((a, b), fill=255, width=max(1, int(round(width * ss))))
        for px, py in (a, b):
            draw.ellipse((px - r, py - r, px + r, py + r), fill=255)
    mask = big.resize((w, h), Image.LANCZOS)
    alpha = colour[3] if len(colour) > 3 else 255
    if alpha != 255:
        mask = mask.point(lambda v: v * alpha // 255)
    layer = Image.new("RGBA", (w, h), tuple(colour[:3]) + (0,))
    layer.putalpha(mask)
    img.alpha_composite(layer, (x0, y0))


def paint(card: dict, backdrop=None, scale: float = 1.0,
          ticked: bool = False):
    """The whole card as a Pillow RGBA picture, origin at the window's
    corner — the shadow's room included. `ticked` is the box's state,
    which lives on overlay.HintCard and not on the card's data."""
    lay = _layout(card, scale)
    s = lay.s
    pad = PAD * s
    x0 = y0 = SHADOW
    img = plate(lay.width, lay.height, RADIUS * s, SHADOW, FACE_A, backdrop)
    right = lay.right
    boxes = lay.boxes
    line = rgb(LINE)

    def put(text_img, x, yy):
        img.alpha_composite(text_img, (int(round(x)), int(round(yy))))

    # -- the head, ONE line: the state bead, the title and what it means on
    # the right; ×, − and + on the left; the whole strip is the handle.
    mid = lay.line_mid
    bead = DOTS.get(card.get("dot"), DOTS["ready"])
    bx, br = right - 5 * s, 4.5 * s
    img.alpha_composite(disc(img.size, bx, mid, br * 2.2, bead + (34,)))
    img.alpha_composite(disc(img.size, bx, mid, br, bead + (255,)))
    title = _text(card["title"], pt=PT_TITLE * s, weight=600)
    tx = right - 16 * s - title.width
    put(title, tx, mid - title.height / 2)
    sub = _text(card["sub"], pt=PT_SUB * s, colour=INK_DIM)
    put(sub, tx - 10 * s - sub.width, mid - sub.height / 2 + 1 * s)

    ink = rgb(FG) + (215,)
    for name in (CLOSE, SMALLER, BIGGER):
        bx0, by0, bx1, by1 = boxes[name]
        _rrect(img, (bx0, by0, bx1, by1), 5 * s, fill=rgb(BG) + (110,),
               outline=rgb(LINE_HI) + (150,))
        cx, cy, arm = (bx0 + bx1) / 2, (by0 + by1) / 2, 4.5 * s
        if name == CLOSE:
            lines = [(cx - arm, cy - arm, cx + arm, cy + arm),
                     (cx - arm, cy + arm, cx + arm, cy - arm)]
        elif name == SMALLER:
            lines = [(cx - arm, cy, cx + arm, cy)]
        else:
            lines = [(cx - arm, cy, cx + arm, cy), (cx, cy - arm, cx, cy + arm)]
        _strokes(img, lines, ink, 1.6 * s)

    y = y0 + (PAD + HEAD_H) * s
    _rule(img, x0 + pad, right, y, line + (150,))

    # -- the keys, in their columns: a cap at the column's right edge and
    # its words to the left of it, every cap one width.
    cw = lay.chip_w
    for column, edge, col_w in zip(lay.columns, lay.col_right, lay.col_w):
        y = lay.body_top
        left = edge - col_w
        for gi, (name, items) in enumerate(column):
            if name:
                head = _text(name, pt=PT_GROUP * s, colour=INK_FAINT,
                             weight=600)
                put(head, edge - head.width, y + 2 * s)
                _rule(img, left, edge - head.width - 8 * s,
                      y + GROUP_H * s - 8 * s, line + (90,))
            y += GROUP_H * s
            for key, label, on in items:
                chip = _text(key, pt=PT_KEY * s, weight=700, rtl=False,
                             colour=INK_KEY if on else INK_FAINT)
                top = y + (ROW_H - CHIP_H) / 2 * s
                box = (edge - cw, top, edge, top + CHIP_H * s)
                _rrect(img, box, 7 * s,
                       fill=(rgb(KEY_BG) + (190,)) if on
                       else (rgb(BG) + (120,)),
                       outline=(rgb(KEY_EDGE) + (200,)) if on
                       else (line + (110,)))
                put(chip, edge - cw / 2 - chip.width / 2,
                    top + (CHIP_H * s - chip.height) / 2)
                words = _text(label, pt=PT_LABEL * s,
                              colour=INK if on else INK_FAINT)
                put(words, edge - cw - LABEL_GAP * s - words.width,
                    top + (CHIP_H * s - words.height) / 2)
                y += ROW_H * s
            if gi < len(column) - 1:
                y += GROUP_GAP * s

    fy = lay.foot_y
    _rule(img, x0 + pad, right, fy - RULE_GAP * s + 4 * s, line + (110,))
    # the footer: the box at the right where the eye lands first in Hebrew
    # and the words to its left. Ticked, it is the second lit thing on the
    # card; the X is what makes it count.
    cy = fy + (FOOT_H * s - 4) / 2
    tick = (right - BOX * s, cy - BOX * s / 2, right, cy + BOX * s / 2)
    if ticked:
        _rrect(img, tick, 4 * s, fill=rgb(ACCENT) + (255,))
        l, t = tick[0], tick[1]
        b = BOX * s
        _strokes(img, [(l + 0.24 * b, t + 0.52 * b, l + 0.43 * b, t + 0.71 * b),
                       (l + 0.43 * b, t + 0.71 * b, l + 0.77 * b, t + 0.31 * b)],
                 rgb(ACCENT_ON) + (255,), 1.9 * s)
    else:
        _rrect(img, tick, 4 * s, fill=rgb(BG) + (120,),
               outline=rgb(LINE_HI) + (220,))
    foot = _text(card["footer"], pt=PT_FOOT * s,
                 colour=INK if ticked else INK_DIM)
    put(foot, right - (BOX + 8) * s - foot.width, cy - foot.height / 2)
    return img


def draw(canvas, card: dict, backdrop=None, scale: float = 1.0,
         ticked: bool = False) -> None:
    """Paint the whole card onto a skia `canvas`, origin at the window's
    corner: the same picture as `paint()`, for the path that has one."""
    canvas.clear(0x00000000)
    canvas.drawImage(_to_skia(paint(card, backdrop, scale, ticked)), 0, 0)


def run(hint_card) -> None:
    """The body of overlay.HintCard's thread, with the picture swapped.

    Same contract as the dot and the splash: the queue, `_alive`,
    `_closing` and the `_DONE` sentinel stay exactly where overlay.py put
    them, and the delay stays overlay.py's rule rather than being
    reimplemented here.

    The window is built when a card becomes due and destroyed when it goes
    away, because its size depends on how many keys are live, on their
    words and on the scale. That is a few milliseconds once per hesitated
    dictation, against keeping a layered window alive for a panel that is
    usually not on screen.
    """
    import overlay

    glass = None
    shown = None                   # the card currently painted
    pending = None                 # the card waiting for its delay
    due = None
    redraw = False
    hint_card._alive.set()

    def take_down():
        nonlocal glass, shown
        if glass is not None:
            glass.close()
            glass = None
        shown = None

    def on_hit(x, y):
        code, _what = hit_test(shown or pending, hint_card.scale, x, y)
        return code

    def on_move():
        """A drag ended. Windows moved the window, so read it back.

        SHADOW is added because the window's corner is not the card's:
        overlay.HintCard.placed wants what the owner can see, and saving
        the window's corner instead is the bug that made every drag near
        the top of the screen snap back.
        """
        nonlocal redraw
        if glass is None:
            return
        x, y = glass.where()
        hint_card.placed(x + SHADOW, y + SHADOW)
        redraw = False              # the picture did not change, only where

    def on_click(x, y):
        nonlocal redraw, pending, due
        _code, what = hit_test(shown or pending, hint_card.scale, x, y)
        if what == SMALLER:
            hint_card.resized(stepped(hint_card.scale, -STEP))
        elif what == BIGGER:
            hint_card.resized(stepped(hint_card.scale, STEP))
        elif what == DISMISS:
            hint_card.tick()        # ticks or unticks; never closes
        elif what == CLOSE:
            # Gone until the next dictation — or for good, if the box is
            # ticked. HintCard decides which and writes it down.
            hint_card.closed_by_hand()
            pending, due = None, None
            take_down()
            return
        redraw = True

    def put_up(card):
        nonlocal glass, shown
        s = clamp_scale(hint_card.scale)
        width, height = measure(card, s)
        win_w, win_h = width + SHADOW * 2, height + SHADOW * 2
        # primary for the corners, the whole desktop for a saved position:
        # a card left on a second screen belongs on that second screen.
        # The work area so a bottom corner is above the taskbar, where the
        # status dot is, and the card lands beside it rather than on it.
        x, y = hint_card.origin(win_w, win_h, primary_screen(), SHADOW,
                                virtual_screen(), work_area())
        if glass is not None and (glass.width, glass.height) != (win_w, win_h):
            take_down()
        if glass is None:
            # gpu=False: the picture is Pillow's and static, so a GPU
            # surface would be a readback for nothing — and a GL context
            # a copy without skia cannot build
            glass = Glass(x, y, win_w, win_h, gpu=False, hit=on_hit,
                          moved=on_move, clicked=on_click)
            glass.show()
        else:
            glass.move(x, y)
        glass.present(paint(card, _frost(x, y, win_w, win_h), s,
                            ticked=hint_card.ticked))
        glass.raise_()
        shown = card

    try:
        while not hint_card._closing.is_set():
            changed = False
            try:
                while True:
                    item = hint_card._q.get_nowait()
                    if item is overlay._DONE:
                        hint_card._closing.set()
                        break
                    if item is None:
                        # The dictation is over (or the shelf took the
                        # corner): a tick left on the box counts now.
                        hint_card.card_gone()
                        pending, due = None, None
                        take_down()
                    elif not hint_card.accepts(item):
                        continue            # closed by hand until the next
                    else:
                        if due is None and shown is None:
                            due = time.monotonic() + hint_card._after
                        pending = item
                        changed = shown is not None
            except queue.Empty:
                pass
            if hint_card._closing.is_set():
                break
            if pending is not None and (
                    (shown is None and due is not None
                     and time.monotonic() >= due) or changed or redraw):
                redraw = False
                put_up(pending)
            if glass is not None:
                glass.pump()
            # Nothing moves on this card, so the loop only has to be quick
            # enough that the delay lands on time, a click feels immediate,
            # and a release takes it down without a visible lag.
            time.sleep(0.02)
    except Exception:
        _log.info("skin hint card stopped early", exc_info=True)
    finally:
        take_down()
        hint_card._closing.set()


__all__ = ["paint", "draw", "measure", "regions", "hit_test", "clamp_scale",
           "split", "stepped", "run"]
