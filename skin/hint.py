"""The hint card, on glass.

overlay.HintCard owns the thread, the queue and the delay; this owns the
picture, and — because a picture you can drag has to know where it is —
the things the owner can change about it: where it sits, how big it is
(down to the small card), closing it for this dictation, and whether it
comes back at all.

WHAT IT LOOKS LIKE, SINCE 2026-10-01. A LAMPLIGHT card — face.py's plate,
the same shadow, surface and rim as the boot card — read LEFT TO RIGHT and
in ENGLISH (his word: "everything in English here, and right to left, left
to right, changed accordingly"): the state bead, the title and its sub on
the left of ONE head line, the X at its right, a size grip in the
bottom-right corner like any window's, and the keys in
their three groups (hint.py names them) in TWO COLUMNS — the dictation and
the screen on the left, "Other" on the right. Every key cap is one width,
so each column reads as a column, and the card is exactly as wide as its
words.

WHY TWO COLUMNS AND WHY THE WIDTH FOLLOWS THE WORDS (2026-09-24). His clip:
"if I make it bigger it takes half the screen, and at a size that is
reasonable for the screen I cannot read it". It was ONE column of fourteen
keys, 340 px wide whatever it said (a third of every row empty), 652 px
tall at 1.0 and 913 at 1.4; at the 0.6 he had pressed it down to, a label
was 8 px. Two columns halve the height, the text is 12 pt (16 px at 1.0,
12.8 at 0.8), and nothing is reserved for words that are not there.

THE SMALL CARD AND THE CORNER (2026-10-01). He wanted it smaller still,
and smaller TEXT is the one thing that cannot be the answer — so below
the smallest size is FEWER ROWS: only the dictation's own keys (release,
lock, Esc), with "All keys" at the foot to see the rest for that one
dictation ("Fewer keys" folds it again). The size is set by dragging the
card's bottom-right corner — his second ask that day, "instead of plus and
minus, like any app's window" — and dragging it smaller than the full card
at 0.8 lands on the small card (`fit`). The card keeps `compact` in
state.json like its scale; `run()` has the drag.

THE TEXT IS FREETYPE, NOT GDI (2026-10-01). "My screen is 2K, it should
not look blurry, and the round strokes look pixelated" — measured: GDI's
ANTIALIASED_QUALITY (visual_qa.text_pil, what this card drew through)
gives a glyph edge 14 levels of coverage at these sizes; FreeType over the
same fonts\\Rubik.ttf gives 85-159. The shapes were never the problem —
face.py draws every one at 4x. GDI was here for the one thing FreeType
cannot do, Hebrew's right-to-left order; with the card in English that
reason is gone. Rubik is one VARIABLE font, so the weight is pinned on its
axis (`_font`); every string is drawn at 4x and reduced, because FreeType
hints at the size it is given and whole-pixel advances letter-spaced the
caps; a string with a character Rubik lacks is drawn in Segoe UI
(`_missing`), and an arrow key's cap is drawn as strokes (`_arrow`).

THE BOX AND THE X (2026-09-24). The "don't show this again" row used to
turn the card off on the first click, which read as a checkbox that
cannot be checked. Now the box only ticks and the X closes: unticked, gone
for this dictation and back on the next; ticked, gone and not coming back.
A tick left on the box when the card goes away on its own (the key let
go) counts too. overlay.HintCard holds the tick, "closed for now" and the
"All keys" peek; this module draws them and reports the clicks.

AND IT IS PAINTED BY PILLOW, so a fresh install — which has no skia; that
is the skin pack — gets this card and not overlay._hint_paint's flat Tk
canvas. `paint()` is the picture; `draw()` puts it on a skia canvas for
the path that has one; `run()` hands it to the window with
glass.present(), which needs neither.

* **It redraws only when something changed.** The dot animates and the
  boot card animates; this one is a static panel that sits on screen for
  seconds *while two Whisper models want the GPU*. A frame loop here
  would be spending the one resource the dictation is waiting for.

* **It takes the mouse in a few small rectangles and nowhere else.** The
  strip along the top drags it, the grip in its corner resizes it, ×
  closes it, the box at the bottom ticks, "All keys" / "Fewer keys"
  folds it, and every
  other pixel answers HTTRANSPARENT — so a click aimed at the close button
  of a maximised window underneath still lands on the close button. That
  is the trap the status dot paid for once already, and the reason this
  is a hit test rather than a plain clickable window.

WHERE IT SITS IS NOT WHERE THE DOT SITS. On the right-hand corners the
card is placed BESIDE the dot, never over or under it: the dot is the one
thing on screen that says the app is alive, and it does not move for a
panel that is only up while a key is down.
"""
from __future__ import annotations

import logging
import math
import os
import queue
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .face import disc, plate, rule, shape
from .glass import (Glass, primary_screen, virtual_screen, work_area,
                    cursor, primary_button_down,
                    HTTRANSPARENT, HTCLIENT, HTCAPTION, HTBOTTOMRIGHT)
from .palette import (BG, LINE, FG, KEY_BG, KEY_EDGE, LINE_HI, DOT_STATES,
                      ACCENT, ACCENT_ON, ACCENT_TEXT, rgb)

_log = logging.getLogger("app")

# Every length below is at scale 1.0 and multiplied by the scale; every
# text size is in points at 96 dpi, the dpi this process draws at.
RADIUS = 18
PAD = 16
HEAD_H = 34               # the head line: title left, − + and × right
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
TOGGLE_PAD = 11           # each side of "All keys" inside its pill
SHADOW = 26               # room around the card for its own shadow
FACE_A = 216              # the face's alpha. boot.py uses 252; this is glass
BLUR = 11                 # px, the frost behind it
DOT_ROOM = 46             # the status dot's own corner, which is not ours
# The card's own range sits INSIDE config.py's (0.6 .. 1.4, which the
# review and notify cards share): 0.8 is the smallest size at which a
# label is still 12.8 px. A 0.6 saved by the card before 2026-09-24 is
# drawn at 0.8, not refused. Below 0.8 is the small card (`fit`).
SCALE_MIN, SCALE_MAX = 0.8, 1.4
BTN = 20                  # the × square
GRIP = 14                 # the size grip: this square in the bottom-right
GRIP_MIN = 12             # corner, never smaller than this many pixels
RESIZE_STEP = 0.02        # a corner drag lands on a multiple of this scale
PREVIEW_HOLD_S = 0.12     # the pointer still this long: draw it sharp

PT_TITLE = 14.0
PT_SUB = 10.5
PT_LABEL = 12.0
PT_KEY = 10.5
PT_GROUP = 9.5
PT_FOOT = 10.5
W_TEXT, W_STRONG = 400, 600   # Rubik's wght axis: words, and titles/caps
TEXT_SS = 4               # text is drawn at 4x and reduced (`_text`)

INK = (241, 236, 226)        # FG      13.76:1 on the card
INK_DIM = (178, 168, 150)    # DIM      6.89:1
INK_FAINT = (126, 117, 100)  # FAINT    3.56:1 - labels and rules only
INK_KEY = rgb(FG)            # A KEY CHIP IS A KEY CAP, NOT A BUTTON.
#                              Fifteen chips in the accent turned this card
#                              into fifteen primary actions competing for
#                              one glance; it is a LEGEND. So the chips take
#                              ui.KeyCap's own face (KEY_BG on KEY_EDGE with
#                              the glyph in FG) and the only lit things left
#                              on the card are the state bead, the ticked
#                              box and the words of the fold button.

# The state bead, taken from the dot's own table so the card and the dot in
# the corner can never disagree about what colour "recording" is.
DOTS = {name: rgb(DOT_STATES[name][0])
        for name in ("recording", "locked", "ready", "busy", "paused")}

# What a hit landed on, for the click handler. Kept as strings rather than
# rectangles on the instance so `regions()` can be tested without a window.
CLOSE, DISMISS, MORE, GRIP_HIT, DRAG = (
    "close", "dismiss", "more", "grip", "drag")

# The three ways the card can be laid out. FULL: every key, nothing to
# fold. COMPACT: the small card, the dictation's rows and "All keys".
# PEEK: the small card opened for this dictation — every key, and
# "Fewer keys" to fold it again. overlay.HintCard.view says which.
FULL, COMPACT, PEEK = "full", "compact", "peek"
TOGGLE = {COMPACT: "All keys", PEEK: "Fewer keys"}

# An arrow key's cap is DRAWN, not set in type: Rubik has no arrows, and
# Segoe UI's "←" at a cap's 11 px is a dash you have to squint at (seen on
# the first English render, 2026-10-01). (dx, dy) is where it points.
ARROWS = {"←": (-1, 0), "→": (1, 0), "↑": (0, -1), "↓": (0, 1)}
ARROW_LEN = 13            # the shaft, tip to tail

# Fonts, rendered strings and finished layouts, keyed by what they were
# made from. Pillow objects and numbers only: nothing module-level may
# hold a Tk object (AGENTS.md), and nothing here is one.
_FONTS: dict = {}
_MISSING: dict = {}
_MEMO: dict = {}
_LAYOUTS: dict = {}
_MEMO_MAX = 600


def _rubik_file() -> Path:
    try:
        from fonts import FONT_DIR
    except Exception:                                   # noqa: BLE001
        FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
    return Path(FONT_DIR) / "Rubik.ttf"


def _segoe_file(weight: int) -> Path:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    name = "seguisb.ttf" if weight >= W_STRONG else "segoeui.ttf"
    path = Path(windir) / "Fonts" / name
    return path if path.is_file() else Path(windir) / "Fonts" / "segoeui.ttf"


def _font(px: float, weight: int, fallback: bool = False):
    """Rubik at `px` with its weight axis pinned — or, for a string Rubik
    cannot draw, Segoe UI. BASIC layout: the card is English, and raqm is
    not in Pillow's Windows wheels."""
    key = (round(px, 3), weight, fallback)
    font = _FONTS.get(key)
    if font is not None:
        return font
    if fallback:
        font = ImageFont.truetype(str(_segoe_file(weight)), px,
                                  layout_engine=ImageFont.Layout.BASIC)
    else:
        font = ImageFont.truetype(str(_rubik_file()), px,
                                  layout_engine=ImageFont.Layout.BASIC)
        try:
            font.set_variation_by_axes([weight])
        except Exception:                               # noqa: BLE001
            _log.debug("skin: Rubik's weight axis not set", exc_info=True)
    _FONTS[key] = font
    return font


def _missing(ch: str) -> bool:
    """Does Rubik lack this character? Its .notdef box is what FreeType
    draws for one it lacks, so the answer is a comparison of masks."""
    hit = _MISSING.get(ch)
    if hit is None:
        font = _font(16, W_TEXT)

        def sig(c):
            m = font.getmask(c)
            return m.size, bytes(m)
        hit = ch.strip() != "" and sig(ch) == sig("\U000FFFFD")
        _MISSING[ch] = hit
    return hit


class Ink:
    """One line of text as an RGBA image: as wide as its ink, as tall as
    the font's line, with its baseline and cap height kept — so every
    label in a row sits on one baseline, which glyph-cropped images did
    not ("Screenshot" and "Ctrl+F2" each centred on their own box)."""

    def __init__(self, img, base: float, cap: float) -> None:
        self.img, self.base, self.cap = img, base, cap
        self.width, self.height = img.size


def _text(text, pt=PT_LABEL, colour=INK, weight=W_TEXT) -> Ink:
    """`text` in Rubik at `pt` (96 dpi), smoothed by FreeType."""
    key = (text, round(float(pt), 3), tuple(colour), weight)
    ink = _MEMO.get(key)
    if ink is not None:
        return ink
    text = text or " "
    # Drawn at TEXT_SS x and brought down: FreeType HINTS at the size it
    # is asked for, and rounding every advance to a whole pixel made
    # "Release" and "Ctrl+Alt+N" look letter-spaced at a cap's 11 px
    # (compared side by side, 2026-10-01). At 4x the rounding is a quarter
    # of a pixel and the spacing is the font's own.
    ss = TEXT_SS
    px = float(pt) * 96 / 72
    fallback = any(_missing(c) for c in text)
    font = _font(px * ss, weight, fallback)
    ascent, descent = font.getmetrics()
    left, _t, right, _b = font.getbbox(text, anchor="ls")
    pad = 2 * ss
    w = int(math.ceil(right - min(0, left))) + 2 * pad
    h = ascent + descent + 2 * pad
    w, h = w + (-w) % ss, h + (-h) % ss
    big = Image.new("L", (max(ss, w), h), 0)
    ImageDraw.Draw(big).text((pad - min(0, left), ascent + pad), text,
                             font=font, fill=255, anchor="ls")
    mask = big.reduce(ss)
    box = mask.getbbox()
    if box:
        mask = mask.crop((box[0], 0, box[2], mask.height))
    else:
        mask = Image.new("L", (1, mask.height), 0)
    img = Image.new("RGBA", mask.size, tuple(colour[:3]) + (0,))
    img.putalpha(mask)
    cap_box = font.getbbox("H", anchor="ls")
    ink = Ink(img, (ascent + pad) / ss, -cap_box[1] / ss)
    if len(_MEMO) >= _MEMO_MAX:
        _MEMO.clear()
    _MEMO[key] = ink
    return ink


def _to_skia(img):
    import skia
    return skia.Image.frombytes(img.convert("RGBA").tobytes(), img.size,
                                skia.kRGBA_8888_ColorType)


def clamp_scale(scale: float) -> float:
    return max(SCALE_MIN, min(SCALE_MAX, round(float(scale), 3)))


def fit(card: dict, want_w: float, want_h: float) -> tuple[float, bool]:
    """The size a corner drag asks for: (scale, small card?).

    The card keeps its proportions, so the drag is read along its
    diagonal — the scale whose card is nearest (want_w, want_h) — and
    lands on a multiple of RESIZE_STEP inside 0.8 .. 1.4. Smaller than the
    full card at 0.8 is the small card, which has one size: the drag
    snaps to whichever of the two it is nearer, along the line between
    them, so the switch happens halfway and not at the first pixel."""
    fw, fh = measure(card, 1.0, FULL)
    s = (want_w * fw + want_h * fh) / float(fw * fw + fh * fh)
    if s >= SCALE_MIN:
        q = round(round(s / RESIZE_STEP) * RESIZE_STEP, 3)
        return min(SCALE_MAX, max(SCALE_MIN, q)), False
    cw, ch = measure(card, SCALE_MIN, COMPACT)
    mw, mh = measure(card, SCALE_MIN, FULL)
    dx, dy = mw - cw, mh - ch
    t = ((want_w - cw) * dx + (want_h - ch) * dy) / float(dx * dx + dy * dy
                                                         or 1)
    return SCALE_MIN, t < 0.5


def guess(card: dict, scale: float, compact: bool) -> tuple[int, int]:
    """The card's size at (scale, compact) WITHOUT laying it out — the
    full card at 1.0 times the scale, or the small card as measured. What
    a drag's preview frame is sized by: measuring a new scale renders
    every string again, which is the cost the preview is there to skip."""
    if compact:
        return measure(card, SCALE_MIN, COMPACT)
    fw, fh = measure(card, 1.0, FULL)
    return int(round(fw * scale)), int(round(fh * scale))


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


def _shown(card: dict, view: str) -> list:
    """The groups this view draws. The small card is the first group — the
    dictation's own keys — without its heading: on a card that small the
    title already says what they are."""
    groups = _groups(card)
    if view == COMPACT:
        return [("", list(groups[0][1]))] if groups else []
    return groups


def _signature(card: dict) -> tuple:
    return (card.get("title", ""), card.get("sub", ""),
            card.get("footer", ""),
            tuple((name, tuple((k, lab, bool(on)) for k, lab, on in rows))
                  for name, rows in _groups(card)))


def _column_h(groups) -> float:
    """A column's height at scale 1.0: every group's heading (a group with
    no name has none) and rows, and the gap between two groups."""
    if not groups:
        return 0.0
    h = sum((GROUP_H if name else 0) + ROW_H * len(rows)
            for name, rows in groups)
    return h + GROUP_GAP * (len(groups) - 1)


def split(groups: list) -> list:
    """The groups as columns, LEFT one first.

    One group is one column. More are cut at the group boundary that
    makes the taller column shortest, and a tie keeps more in the first
    column, which is where a reader starts. A group is never broken
    across two columns: its heading says what the rows under it are.
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
    """Where everything goes, window-relative, for one card at one scale in
    one view. Built once and kept: the hit test asks for it on every mouse
    message over the window."""

    def __init__(self, card: dict, s: float, view: str) -> None:
        self.s, self.view = s, view
        pad = PAD * s
        shown = _shown(card, view)
        self.columns = split(shown) if view != COMPACT else [shown]
        rows = [r for _name, items in shown for r in items]
        # ONE chip width for the whole card — the widest key plus its
        # padding, never under CHIP_MIN_W — so the caps make a column and
        # every label starts at the same edge.
        chips = [ARROW_LEN * s if key in ARROWS
                 else _text(key, PT_KEY * s, weight=W_STRONG).width
                 for key, _label, _on in rows]
        self.chip_w = max([CHIP_MIN_W * s]
                          + [w + CHIP_PAD * 2 * s for w in chips])
        widths = []
        for column in self.columns:
            w = 0.0
            for name, items in column:
                if name:
                    w = max(w, _text(name, PT_GROUP * s,
                                     weight=W_STRONG).width + 24 * s)
                for _key, label, _on in items:
                    w = max(w, self.chip_w + LABEL_GAP * s
                            + _text(label, PT_LABEL * s).width)
            widths.append(w)
        rows_w = sum(widths) + COL_GAP * s * (len(widths) - 1)
        title = _text(card.get("title", ""), PT_TITLE * s, weight=W_STRONG)
        sub = _text(card.get("sub", ""), PT_SUB * s)
        head_w = 16 * s + title.width + 10 * s + sub.width + 18 * s + BTN * s
        foot = _text(card.get("footer", ""), PT_FOOT * s)
        self.toggle = TOGGLE.get(view)
        toggle_w = 0.0
        if self.toggle:
            toggle_w = (_text(self.toggle, PT_FOOT * s, weight=W_STRONG).width
                        + TOGGLE_PAD * 2 * s)
        foot_w = (BOX + 8) * s + foot.width + (
            24 * s + toggle_w if self.toggle else 0)
        floor = MIN_INNER * s if view != COMPACT else 0
        inner = max(rows_w, head_w, foot_w, floor)
        self.width = int(math.ceil(inner + 2 * pad))
        body = max([_column_h(c) for c in self.columns] or [0])
        self.height = int(round(
            (PAD + HEAD_H + RULE_GAP + body + RULE_GAP + FOOT_H + PAD - 4)
            * s))
        # The columns' left edges. Whatever the head or the footer asks
        # for beyond the rows goes into the gap, so the last column still
        # ends at the right padding and nothing is empty at an edge.
        x0 = y0 = SHADOW
        left = x0 + pad
        right = x0 + self.width - pad
        spare = inner - rows_w
        self.col_w = widths
        self.col_left = []
        edge = left
        for i, w in enumerate(widths):
            self.col_left.append(edge)
            edge += w + COL_GAP * s + (spare if i == 0 else 0)
        self.left, self.right = left, right
        self.body_top = y0 + (PAD + HEAD_H + RULE_GAP) * s
        # the mouse's rectangles
        line_mid = y0 + pad + HEAD_H * s / 2 - 2 * s
        top = line_mid - BTN * s / 2
        close = (right - BTN * s, top, right, top + BTN * s)
        fy = y0 + self.height - (FOOT_H + PAD - 4) * s
        # the box and its words, not the whole row: the row is as wide as
        # the card, and the rest of it is the window behind
        dismiss = (left - 6, fy, left + (BOX + 8) * s + foot.width + 6 * s,
                   fy + FOOT_H * s - 4)
        drag = (x0, y0, x0 + self.width, y0 + (PAD + HEAD_H) * s)
        # The size grip, in the card's own bottom-right corner — inside the
        # padding, below and right of anything that takes a click (a test
        # holds that it never meets "All keys").
        g = max(GRIP_MIN, GRIP * s)
        grip = (x0 + self.width - g, y0 + self.height - g,
                x0 + self.width, y0 + self.height)
        self.boxes = {CLOSE: close, DISMISS: dismiss, GRIP_HIT: grip,
                      DRAG: drag}
        if self.toggle:
            cy = fy + (FOOT_H * s - 4) / 2
            self.boxes[MORE] = (right - toggle_w, cy - 11 * s, right,
                                cy + 11 * s)
        self.line_mid = line_mid
        self.foot_y = fy


def _layout(card: dict, scale: float, view: str = FULL) -> _Layout:
    s = clamp_scale(scale)
    key = (_signature(card), s, view)
    hit = _LAYOUTS.get(key)
    if hit is None:
        hit = _Layout(card, s, view)
        if len(_LAYOUTS) >= 64:
            _LAYOUTS.clear()
        _LAYOUTS[key] = hit
    return hit


def measure(card: dict, scale: float = 1.0,
            view: str = FULL) -> tuple[int, int]:
    """The card's size, and therefore the window's: the height is
    arithmetic on the rows, the width is the words' own."""
    lay = _layout(card, scale, view)
    return lay.width, lay.height


def regions(card: dict, scale: float = 1.0, view: str = FULL) -> dict:
    """The rectangles that take the mouse, window-relative: the drag
    strip, ×, the box, the size grip, and in the small card the fold
    button.

    Returned as data so a test can check that they are inside the card,
    do not overlap, and move with the scale — none of which needs a
    window, a screen or a mouse.
    """
    return dict(_layout(card, scale, view).boxes)


def _in(box, x, y) -> bool:
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def hit_test(card: dict, scale: float, x: int, y: int, view: str = FULL):
    """(HT code, what was hit) for a point in window coordinates.

    Everything that is not one of the rectangles is HTTRANSPARENT, which
    is what lets a click go through to the window underneath.
    """
    boxes = regions(card, scale, view)
    for name in (CLOSE, DISMISS, MORE):
        if name in boxes and _in(boxes[name], x, y):
            return HTCLIENT, name
    if _in(boxes[GRIP_HIT], x, y):
        # Windows draws the diagonal resize cursor for this answer by
        # itself; the press is skin\glass's (`gripped`), not DefWindowProc's
        return HTBOTTOMRIGHT, GRIP_HIT
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
    which on a translucent face punches a hole. The layer is the shape's
    own patch, not the whole window: twenty-odd caps each compositing a
    window-sized layer was a third of a repaint (measured 2026-10-01)."""
    x0 = max(0, int(math.floor(box[0])) - 2)
    y0 = max(0, int(math.floor(box[1])) - 2)
    x1 = min(img.width, int(math.ceil(box[2])) + 3)
    y1 = min(img.height, int(math.ceil(box[3])) + 3)
    if x1 <= x0 or y1 <= y0:
        return
    local = (box[0] - x0, box[1] - y0, box[2] - x0, box[3] - y0)
    img.alpha_composite(shape((x1 - x0, y1 - y0), local, radius, fill,
                              outline, width), (x0, y0))


def _rule(img, x0, x1, y, colour):
    """A hairline, on its own three-row patch for the same reason."""
    if x1 <= x0:
        return
    left, top = max(0, int(math.floor(x0))), max(0, int(round(y)) - 1)
    w = min(img.width, int(math.ceil(x1)) + 2) - left
    h = min(img.height, top + 3) - top
    if w <= 0 or h <= 0:
        return
    img.alpha_composite(rule((w, h), x0 - left, x1 - left, y - top, colour),
                        (left, top))


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


def _arrow(img, cx, cy, way, s, colour) -> None:
    """An arrow key's glyph: a shaft and a two-stroke head, centred on
    (cx, cy), pointing `way`."""
    dx, dy = way
    half = ARROW_LEN * s / 2
    tip = (cx + dx * half, cy + dy * half)
    tail = (cx - dx * half, cy - dy * half)
    barb = 4.5 * s
    # the head's two strokes run back from the tip at 45 degrees
    back = (-dx * barb, -dy * barb)
    side = (-dy * barb, dx * barb)
    _strokes(img, [(tail[0], tail[1], tip[0], tip[1]),
                   (tip[0], tip[1], tip[0] + back[0] + side[0],
                    tip[1] + back[1] + side[1]),
                   (tip[0], tip[1], tip[0] + back[0] - side[0],
                    tip[1] + back[1] - side[1])], colour, 1.7 * s)


def paint(card: dict, backdrop=None, scale: float = 1.0,
          ticked: bool = False, view: str = FULL):
    """The whole card as a Pillow RGBA picture, origin at the window's
    corner — the shadow's room included. `ticked` and `view` live on
    overlay.HintCard, not on the card's data."""
    lay = _layout(card, scale, view)
    s = lay.s
    pad = PAD * s
    x0 = y0 = SHADOW
    img = plate(lay.width, lay.height, RADIUS * s, SHADOW, FACE_A, backdrop)
    left, right = lay.left, lay.right
    boxes = lay.boxes
    line = rgb(LINE)

    def put(ink, x, cy):
        """`ink` with its cap height centred on `cy`, its left edge at x."""
        img.alpha_composite(ink.img, (int(round(x)),
                                      int(round(cy + ink.cap / 2 - ink.base))))

    # -- the head, ONE line: the state bead, the title and what it means on
    # the left; × on the right; the whole strip is the handle.
    mid = lay.line_mid
    bead = DOTS.get(card.get("dot"), DOTS["ready"])
    bx, br = left + 5 * s, 4.5 * s
    img.alpha_composite(disc(img.size, bx, mid, br * 2.2, bead + (34,)))
    img.alpha_composite(disc(img.size, bx, mid, br, bead + (255,)))
    title = _text(card["title"], PT_TITLE * s, weight=W_STRONG)
    put(title, left + 16 * s, mid)
    sub = _text(card["sub"], PT_SUB * s, colour=INK_DIM)
    put(sub, left + 16 * s + title.width + 10 * s, mid)

    ink = rgb(FG) + (215,)
    bx0, by0, bx1, by1 = boxes[CLOSE]
    _rrect(img, (bx0, by0, bx1, by1), 5 * s, fill=rgb(BG) + (110,),
           outline=rgb(LINE_HI) + (150,))
    cx, cy, arm = (bx0 + bx1) / 2, (by0 + by1) / 2, 4.5 * s
    _strokes(img, [(cx - arm, cy - arm, cx + arm, cy + arm),
                   (cx - arm, cy + arm, cx + arm, cy - arm)], ink, 1.6 * s)

    # -- the size grip: two short diagonals in the bottom-right corner, the
    # mark every window's corner has carried. Inside the corner's curve:
    # the outer one stops 6 px in from both edges, where the radius has
    # long since turned.
    gx, gy = x0 + lay.width - 6 * s, y0 + lay.height - 6 * s
    grip_ink = INK_DIM + (190,)
    _strokes(img, [(gx - 9 * s, gy, gx, gy - 9 * s),
                   (gx - 4.5 * s, gy, gx, gy - 4.5 * s)], grip_ink, 1.4 * s)

    y = y0 + (PAD + HEAD_H) * s
    _rule(img, x0 + pad, right, y, line + (150,))

    # -- the keys, in their columns: a cap at the column's left edge and
    # its words to the right of it, every cap one width.
    cw = lay.chip_w
    for column, edge, col_w in zip(lay.columns, lay.col_left, lay.col_w):
        y = lay.body_top
        for gi, (name, items) in enumerate(column):
            if name:
                head = _text(name, PT_GROUP * s, colour=INK_FAINT,
                             weight=W_STRONG)
                put(head, edge, y + GROUP_H * s / 2 - 2 * s)
                _rule(img, edge + head.width + 8 * s, edge + col_w,
                      y + GROUP_H * s / 2 - 2 * s, line + (90,))
                y += GROUP_H * s
            for key, label, on in items:
                top = y + (ROW_H - CHIP_H) / 2 * s
                cy = top + CHIP_H * s / 2
                box = (edge, top, edge + cw, top + CHIP_H * s)
                _rrect(img, box, 7 * s,
                       fill=(rgb(KEY_BG) + (190,)) if on
                       else (rgb(BG) + (120,)),
                       outline=(rgb(KEY_EDGE) + (200,)) if on
                       else (line + (110,)))
                if key in ARROWS:
                    _arrow(img, edge + cw / 2, cy, ARROWS[key], s,
                           (INK_KEY if on else INK_FAINT) + (255,))
                else:
                    chip = _text(key, PT_KEY * s, weight=W_STRONG,
                                 colour=INK_KEY if on else INK_FAINT)
                    put(chip, edge + cw / 2 - chip.width / 2, cy)
                words = _text(label, PT_LABEL * s,
                              colour=INK if on else INK_FAINT)
                put(words, edge + cw + LABEL_GAP * s, cy)
                y += ROW_H * s
            if gi < len(column) - 1:
                y += GROUP_GAP * s

    fy = lay.foot_y
    _rule(img, x0 + pad, right, fy - RULE_GAP * s + 4 * s, line + (110,))
    # the footer: the box at the left and its words beside it; ticked, it
    # is lit, and the X is what makes it count. The fold button, when the
    # card has one, at the right end.
    cy = fy + (FOOT_H * s - 4) / 2
    tick = (left, cy - BOX * s / 2, left + BOX * s, cy + BOX * s / 2)
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
    foot = _text(card["footer"], PT_FOOT * s,
                 colour=INK if ticked else INK_DIM)
    put(foot, left + (BOX + 8) * s, cy)
    if lay.toggle:
        tx0, ty0, tx1, ty1 = boxes[MORE]
        _rrect(img, (tx0, ty0, tx1, ty1), 6 * s, fill=rgb(BG) + (110,),
               outline=rgb(LINE_HI) + (170,))
        words = _text(lay.toggle, PT_FOOT * s, colour=rgb(ACCENT_TEXT),
                      weight=W_STRONG)
        put(words, (tx0 + tx1) / 2 - words.width / 2, cy)
    return img


def draw(canvas, card: dict, backdrop=None, scale: float = 1.0,
         ticked: bool = False, view: str = FULL) -> None:
    """Paint the whole card onto a skia `canvas`, origin at the window's
    corner: the same picture as `paint()`, for the path that has one."""
    canvas.clear(0x00000000)
    canvas.drawImage(_to_skia(paint(card, backdrop, scale, ticked, view)),
                     0, 0)


def run(hint_card) -> None:
    """The body of overlay.HintCard's thread, with the picture swapped.

    Same contract as the dot and the splash: the queue, `_alive`,
    `_closing` and the `_DONE` sentinel stay exactly where overlay.py put
    them, and the delay stays overlay.py's rule rather than being
    reimplemented here.

    The window is built when a card becomes due and destroyed when it goes
    away; while it is up, a new size is the same window resized in place
    (Glass.resize). That is a few milliseconds once per hesitated
    dictation, against keeping a layered window alive for a panel that is
    usually not on screen.

    THE CORNER DRAG (2026-10-01, his ask: "instead of plus and minus, the
    corner — drag it bigger and smaller, like any app's window"). A press
    on the grip is skin\\glass's (`gripped`, the mouse captured); until the
    button comes up the loop reads the pointer every tick, asks `fit` what
    size it is asking for and shows a PREVIEW — the last sharp picture of
    that view stretched to the size `guess` gives, a few milliseconds —
    because a real repaint at a size never drawn before is 70-280 ms
    (measured: the plate's shadow, and every string set again at the new
    size). Once the pointer has rested PREVIEW_HOLD_S the size is drawn
    sharp; at the drop it is saved (HintCard.sized), and the card's
    top-left was written where it stood when the drag began, so the card
    stays put the way a window does when its corner is dragged.
    """
    import overlay
    from PIL import Image as _Image

    glass = None
    shown = None                   # the card currently painted
    pending = None                 # the card waiting for its delay
    due = None
    redraw = False
    drag = None                    # the corner drag in progress, or None
    hint_card._alive.set()

    def view():
        return getattr(hint_card, "view", FULL)

    def take_down():
        nonlocal glass, shown
        if drag is not None:
            end_drag()             # the key let go mid-drag: keep the size
        if glass is not None:
            glass.close()
            glass = None
        shown = None

    def on_hit(x, y):
        code, _what = hit_test(shown or pending, hint_card.scale, x, y,
                               view())
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
        _code, what = hit_test(shown or pending, hint_card.scale, x, y,
                               view())
        if what == MORE:
            hint_card.more()        # the small card's "All keys" / "Fewer"
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

    def sharp(card, scale, compact):
        """The card drawn for real at (scale, compact), on the frost the
        drag grabbed once when it began."""
        v = COMPACT if compact else FULL
        s = SCALE_MIN if compact else clamp_scale(scale)
        w, h = measure(card, s, v)
        win_w, win_h = w + SHADOW * 2, h + SHADOW * 2
        frost = drag.get("frost") if drag else None
        back = None
        if frost is not None and frost.width >= win_w \
                and frost.height >= win_h:
            back = frost.crop((0, 0, win_w, win_h))
        return paint(card, back, s, ticked=hint_card.ticked, view=v)

    def show(picture):
        glass.resize(picture.width, picture.height)
        glass.move(*drag["at"])
        glass.present(picture)

    def on_grip(sx, sy):
        """A press on the size grip (the mouse is captured by now)."""
        nonlocal drag
        card = shown
        if glass is None or card is None:
            if glass is not None:
                glass.let_go()
            return
        wx, wy = glass.where()
        compact = view() == COMPACT
        s0 = SCALE_MIN if compact else clamp_scale(hint_card.scale)
        w0, h0 = measure(card, s0, view())
        # The top-left is where the card stays while its corner moves, and
        # after: written now, so the card no longer re-centres on the dot
        # with every size it passes through.
        hint_card.placed(wx + SHADOW, wy + SHADOW)
        big_w, big_h = guess(card, SCALE_MAX, False)
        drag = {
            "at": (wx, wy),
            "grab": (wx + SHADOW + w0 - sx, wy + SHADOW + h0 - sy),
            "target": (s0, compact),
            "since": time.monotonic(),
            "sharp": True,
            "pictures": {compact: picture[0]} if picture[0] else {},
            "frost": _frost(wx, wy, big_w + SHADOW * 2 + 8,
                            big_h + SHADOW * 2 + 8),
        }

    def drag_tick():
        """One look at the pointer during a corner drag."""
        card = shown
        if glass is None or card is None:
            end_drag()
            return
        if not glass.gripping or not primary_button_down():
            end_drag()              # the drop
            return
        px, py = cursor()
        wx, wy = drag["at"]
        want_w = px + drag["grab"][0] - (wx + SHADOW)
        want_h = py + drag["grab"][1] - (wy + SHADOW)
        target = fit(card, want_w, want_h)
        now = time.monotonic()
        if target != drag["target"]:
            drag["target"], drag["since"], drag["sharp"] = target, now, False
            scale, compact = target
            src = drag["pictures"].get(compact)
            if src is None:
                src = sharp(card, scale, compact)
                drag["pictures"][compact] = src
            w, h = guess(card, scale, compact)
            show(src.resize((w + SHADOW * 2, h + SHADOW * 2),
                            _Image.BILINEAR))
        elif not drag["sharp"] and now - drag["since"] >= PREVIEW_HOLD_S:
            scale, compact = target
            img = sharp(card, scale, compact)
            drag["pictures"][compact] = img
            drag["sharp"] = True
            show(img)

    def end_drag():
        """The drop: the size it reached is the card's, saved; the normal
        path draws it sharp in place on the next tick."""
        nonlocal drag, redraw
        done, drag = drag, None
        if done is None:
            return
        if glass is not None:
            glass.let_go()
        scale, compact = done["target"]
        hint_card.sized(scale, compact)
        redraw = True

    picture = [None]               # the last sharp picture put up

    def put_up(card):
        nonlocal glass, shown
        s = clamp_scale(hint_card.scale)
        width, height = measure(card, s, view())
        win_w, win_h = width + SHADOW * 2, height + SHADOW * 2
        # primary for the corners, the whole desktop for a saved position:
        # a card left on a second screen belongs on that second screen.
        # The work area so a bottom corner is above the taskbar, where the
        # status dot is, and the card lands beside it rather than on it.
        x, y = hint_card.origin(win_w, win_h, primary_screen(), SHADOW,
                                virtual_screen(), work_area())
        if glass is not None and (glass.width, glass.height) != (win_w, win_h):
            try:
                glass.resize(win_w, win_h)      # the same window, in place
            except Exception:
                _log.debug("skin: hint glass would not resize", exc_info=True)
                take_down()
        if glass is None:
            # gpu=False: the picture is Pillow's and static, so a GPU
            # surface would be a readback for nothing — and a GL context
            # a copy without skia cannot build
            glass = Glass(x, y, win_w, win_h, gpu=False, hit=on_hit,
                          moved=on_move, clicked=on_click, gripped=on_grip)
            glass.show()
        else:
            glass.move(x, y)
        img = paint(card, _frost(x, y, win_w, win_h), s,
                    ticked=hint_card.ticked, view=view())
        glass.present(img)
        glass.raise_()
        picture[0] = img
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
            if drag is not None:
                drag_tick()
            # A card that changed under a drag waits for the drop: drawing
            # it at the old size would fight the corner under the pointer.
            if drag is None and pending is not None and (
                    (shown is None and due is not None
                     and time.monotonic() >= due) or changed or redraw):
                redraw = False
                put_up(pending)
            if glass is not None:
                glass.pump()
            # Nothing moves on this card but a corner being dragged, so the
            # loop only has to be quick enough that the delay lands on time,
            # a click feels immediate, a release takes it down without a
            # visible lag — and a drag's preview keeps up with the pointer.
            time.sleep(0.012 if drag is not None else 0.02)
    except Exception:
        _log.info("skin hint card stopped early", exc_info=True)
    finally:
        take_down()
        hint_card._closing.set()


__all__ = ["paint", "draw", "measure", "regions", "hit_test", "clamp_scale",
           "split", "fit", "guess", "run", "FULL", "COMPACT", "PEEK"]
