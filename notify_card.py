"""What the notification card says, and how it is drawn.

Split the way the second-reading card is split (review_card.py /
overlay.ReviewCard / skin\\review.py): this half owns the WORDS and the
PICTURE — pure Python plus Pillow, no Tk, no window — and
overlay.NotifyCard owns the thread, the queue, the clock and the
dismissal. There is no glass presenter yet; the flat Tk card paints the
same image this module composes, so when one arrives it inherits the
whole layout for free.

WHAT IT SAYS. A 4 px bar in the colour of the KIND (done, input, error,
info) across the top; a head row with who sent it (the source's label)
and how long ago; the title; the body, wrapped; the project it came
from, behind a folder glyph; a thin clock that empties while the card
waits to take itself down, drawn ONLY when the card carries a non-zero
`seconds` (since 2026-09-04 it usually does not — a notification stays
until it is dismissed); a footer saying how to dismiss it; a faint
"+N earlier" line when the card carries `more`, which the engine puts on
the last card of a column it had to cut; and, when
more than one is unread, a badge with the count. Nothing in a
notification is interpreted: title and body arrive already cut to
length by notify.clean and are DRAWN, never parsed.

EVERY STRING IS ITS OWN IMAGE. Tk has no bidi and DrawTextW does — but
only per string, and it lays a whole string out in ONE direction, decided
by the reading order it is told. A title in Hebrew and a label in Latin
share a card here, and the body can be either or both. So each string
goes through visual_qa.text_pil on its own, with `rtl` decided per
string by its first strong letter, and the chrome (label, time,
project, footer, badge) is never concatenated with the title or the
body: "Claude Code · כותרת" as one string is exactly the mixed line
that comes out scrambled. Two images sidestep the question.

THE BODY IS CUT BY LINES, NOT BY CHARACTERS. A 400-character body in
Hebrew and one in English wrap to very different heights, and a
character count cannot know where a line breaks — DrawTextW does. So the
body is wrapped to the card's inner width first and then cropped to
BODY_LINES lines, with an ellipsis painted onto the last one, which
keeps the card the same height whatever language it arrived in and
never splits a word in the middle.

THEY STACK, AND THE COLUMN IS ONE WINDOW (2026-09-04). Every unread
notification is on screen at once, newest at the top, oldest at the
bottom — the owner's ask, and capture.py's toast deck is the reference
for how it should behave. `stack_layout` / `stack_measure` /
`stack_hit_test` / `stack_flat` are the column's versions of the four
single-card functions below them, and each of them is written in terms of
the single-card one, so a card in a column measures, draws and takes a
click exactly as it does alone. `measure`, `regions`, `hit_test`,
`compose` and `flat` are untouched and still mean one card.

A PINNED CARD (2026-10-07, the "Screens off" card — awake.py's screens
mode). A card dict may carry `pinned: True` and `button: "<text>"`, and
`pinned_card()` builds the one the screens mode puts up. It differs from
every other card in three places and nowhere else: it has NO ×, because
nobody may close it — a moon stands where the × would be; its footer row
is BUTTON_H tall and carries the footer text on the left and one filled
pill on the right; and the pill, not the card, is the only thing that
answers a click (`BUTTON`). The rest of it still drags the column.

Everything geometric is a function of the card dict and the scale, so
tests check the layout without a screen; `regions()` is what both the
painter and the hit test read, which is what keeps the × pressed where
it is drawn.
"""
from __future__ import annotations

import time
from datetime import datetime

from PIL import Image, ImageDraw

import look

# Win32 hit-test answers, spelled out so this module needs no skin import.
HTTRANSPARENT, HTCLIENT, HTCAPTION = -1, 1, 2

CARD_W = 360
SHADOW = 26               # room a glass window would leave around the card
PAD = 16
RADIUS = 22               # B+'s corner (20 under LAMPLIGHT)
BODY_LINES = 4
SCALE_MIN, SCALE_MAX = 0.6, 1.4

DISMISS, DRAG, BUTTON, CLEAR = "dismiss", "drag", "button", "clear"

# THE CLEAR-ALL PILL (2026-10-18). His words: "a button for Clear All so
# I don't have to close them one by one". It is its own small piece of
# glass ABOVE the newest card, on the left, in the same column as every
# card's × — the side the eye already goes to to close something — and it
# is there only while two or more notifications are unread (a lone card
# has its own ×, and a pill that clears one card is a second × in a worse
# place). It means what Esc over the column and the dismiss key have
# always meant: `pressed("dismiss", None)`, every unread one seen, the
# ones the column had no room for included. Fixed size, so the hit test
# stays arithmetic.
CLEAR_W = 128
CLEAR_H = 26
CLEAR_TEXT = "Clear all"

# The id of the pinned screens card — overlay.NotifyCard and main.py agree
# on it, and a notification can never carry it (notify ids are numbers).
PIN_ID = "awake:screens"

# One colour per kind: the lamp before the sender's name, and the clock.
# B+ semantics (2026-10-23): done is the success green, input is AMBER —
# worth a look, and no longer the accent, which is the action's colour
# now — error is the danger red and info the listening blue.
KIND_COLOUR = {"done": (95, 219, 166), "input": (255, 184, 77),
               "error": (255, 110, 126), "info": (77, 184, 255)}
FOOTER = "Esc / click to dismiss"

# Row heights at scale 1.0. Chrome rows are fixed so the card's height is
# arithmetic; only the body's is measured, because only the body wraps.
BAR_H = 4                 # the kind's colour bar, and the clock
HEAD_H = 26               # the ×, the label and the time share this row
TITLE_H = 22
PROJECT_H = 16
FOOTER_H = 14
BUTTON_H = 24             # a pinned card's footer row: it holds the pill
BUTTON_W = 92             # the pill's width. Fixed, not measured, so a hit
                          # test stays arithmetic and the pill does not
                          # change size with the font
MORE_H = 14               # the "+N earlier" line, only on the last card
ROW = 8                   # between rows INSIDE one card. This was called
                          # GAP until 2026-09-04, when GAP became the air
                          # BETWEEN cards (below) — the two are different
                          # numbers and sharing a name was an accident
                          # waiting for a stack
CROSS = 26                # the dismiss box, PAD in from the top-left

# THE COLUMN. Copied from capture.py's toast stack (TOAST_GAP,
# TOAST_STACK_MAX, stack_fits/stack_at/stack_layout, capture.py:306-560),
# which is the owner's own reference for how a stack behaves — deliberately
# COPIED and not imported, the way NESTED_HOTKEYS is duplicated between
# main.py and dashboard.py: capture.py drags in Pillow, Tk canvases and a
# video encoder, and overlay.py is on the startup path. The arithmetic is
# eight lines; the import would be the whole editor.
GAP = 10                  # between stacked cards — capture.TOAST_GAP's value
STACK_MAX = 8             # the ceiling [notify] stack_max is validated
                          # against — capture.TOAST_STACK_MAX's value, and
                          # the same shape of number: the preference
                          # defaults well under it

# skin\palette.py's values, spelled out: this module is reached with the
# skin folder deleted. Tuples, because Pillow wants them. B+ since
# 2026-10-23; the glass, the buttons and the lamp come from look.py.
INK = (239, 237, 247)        # FG      14.15:1 on the card
INK_DIM = (192, 195, 216)    # DIM      9.40:1
INK_MUTED = (164, 169, 194)  # MUTED    7.05:1 — times, the project, footers
INK_FAINT = (112, 117, 142)  # FAINT    3.61:1 — labels and rules
LINE = (48, 54, 90)          # LINE
CARD = (26, 30, 53)          # CARD

ELLIPSIS = "…"


def clamp_scale(scale: float) -> float:
    return max(SCALE_MIN, min(SCALE_MAX, round(float(scale), 3)))


def _is_rtl(text: str) -> bool:
    """Decided by the first strong letter, the way a bidi layout decides
    it (settings.is_rtl's rule, kept local so this module imports
    nothing that builds Tk styles)."""
    for ch in text:
        if "֐" <= ch <= "ࣿ":
            return True
        if ch.isalpha():
            return False
    return False


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------

def ago(at_iso: str, now: float | None = None) -> str:
    """How long ago an ISO timestamp was, in the words a person uses.

    "just now" under a minute, then minutes, then hours, "yesterday"
    for the day before, and a bare day-and-month beyond that. `now` is
    an epoch float for tests; unparsable input is an empty string rather
    than an exception, because this is chrome on a card and never a
    reason not to show it.
    """
    try:
        at = datetime.fromisoformat(str(at_iso)).timestamp()
    except Exception:
        return ""
    stamp = time.time() if now is None else float(now)
    diff = stamp - at
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{int(diff // 60)} min ago"
    if diff < 86400:
        return f"{int(diff // 3600)} h ago"
    if diff < 2 * 86400:
        return "yesterday"
    when = datetime.fromtimestamp(at)
    return f"{when.day} {when.strftime('%b')}"


def card_for(item: dict, *, seconds: float, unread: int = 1,
             scale: float = 1.0) -> dict:
    """The whole card as data: what overlay.NotifyCard queues and every
    painter consumes. `seconds` is how long the clock runs (0 = until
    dismissed); `unread` is how many are waiting, and becomes the badge
    once it is more than this one."""
    kind = str(item.get("kind") or "info")
    if kind not in KIND_COLOUR:
        kind = "info"
    at = str(item.get("at") or "")
    n = int(unread)
    try:
        more = max(0, int(item.get("more") or 0))
    except (TypeError, ValueError):
        more = 0                       # chrome on a card is never a reason
    return {"id": item.get("id"),      # not to show it — see ago()
            "source": str(item.get("source") or ""),
            "label": str(item.get("label") or item.get("source") or ""),
            "kind": kind, "colour": KIND_COLOUR[kind],
            "title": str(item.get("title") or ""),
            "body": str(item.get("body") or ""),
            "project": str(item.get("project") or ""),
            "at": at, "when": ago(at), "unread": n,
            "seconds": float(seconds), "footer": FOOTER,
            "badge": f"{n}" if n > 1 else "",
            # Carried through, never computed here: the engine is the only
            # thing that knows how many unread items the column left in the
            # store, and it puts the number on the LAST card it hands over.
            "more": more}


def pinned_card(*, since: float, keep_s: int, key: str = "",
                button: str = "Screens on") -> dict:
    """The "Screens off" card as data (overlay.NotifyCard.pin takes it).

    `since` is the epoch second the mode started — drawn as a clock time,
    not a running counter, so the card never has to repaint while it
    waits; `keep_s` is `[awake] keep_screens_off_s` (0 = the screens stay
    lit until the monitors' own timer); `key` is the bound screens key,
    already pretty-printed ("Ctrl+Alt+N"), or "" when none is bound — the
    footer then names the desk's Awake screen instead."""
    keep = max(0, int(keep_s))
    if keep > 0:
        body = ("The PC is awake and working. Touch it and the screens "
                f"light up, then go dark again {keep} s after you stop.")
    else:
        body = ("The PC is awake and working. Touch it and the screens "
                "light up and stay lit until the monitors' own timer.")
    footer = (f"{key} brings them back" if key
              else "The desk's Awake screen brings them back")
    card = card_for({"id": PIN_ID, "kind": "info", "label": "SCREENS OFF",
                     "title": "Screens off is on", "body": body},
                    seconds=0)
    card.update({"pinned": True, "button": str(button), "footer": footer,
                 "when": "since " + datetime.fromtimestamp(float(since))
                 .strftime("%H:%M")})
    return card


def is_pinned(card: dict) -> bool:
    return bool(card.get("pinned"))


# ---------------------------------------------------------------------------
# the picture: text
# ---------------------------------------------------------------------------

_text_pil = None


def _painter():
    global _text_pil
    if _text_pil is None:
        # Deferred: importing visual_qa pulls in the whole ask card, and
        # this module is first reached when a notification arrives.
        from visual_qa import text_pil
        _text_pil = text_pil
    return _text_pil


def _text(cache: dict, text: str, pt: float, colour=INK, weight: int = 400,
          rtl: bool | None = None, single: bool = True, width: int = 1400):
    """One string as an RGBA image — review_card's recipe, with two
    additions: `rtl` defaults to the string's own first strong letter,
    and `single=False` wraps to `width` (the body) and is returned
    uncropped so its alignment inside that width survives. A single line
    is cropped to its glyphs. The cache is the presenter's, never
    module-level: the images belong to the card that is up."""
    if rtl is None:
        rtl = _is_rtl(text)
    if single:
        # B+ (2026-10-23): a single line is look.text's — Latin by FreeType
        # at Rubik's real weight, anything with Hebrew through text_pil
        return look.text(cache, text, pt, colour, weight, rtl, width)
    key = (text, round(pt, 2), colour, weight, rtl, single, width)
    img = cache.get(key)
    if img is not None:
        return img
    img = _painter()(text or " ", max(20, int(width)), pt=pt, colour=colour,
                     weight=weight, rtl=rtl, single=single)
    cache[key] = img
    return img


# Line metrics per point size, and line counts per (body, pt, width) —
# integers only, so a module-level cache is harmless. They make
# measure() (and so every hover's hit test) arithmetic after the first
# render of a body.
_LINE_H: dict = {}
_METRICS: dict = {}


def _line_metrics(pt: float) -> tuple[int, int]:
    """(height of one line's image, line spacing) at `pt`, measured off
    DrawTextW itself rather than guessed from the point size."""
    key = round(pt, 2)
    got = _LINE_H.get(key)
    if got is None:
        paint = _painter()
        one = paint("Ag", 200, pt=pt, rtl=False, single=True).height
        two = paint("Ag\nAg", 200, pt=pt, rtl=False, single=False).height
        got = (one, max(1, two - one))
        _LINE_H[key] = got
    return got


def _body(cache: dict, text: str, pt: float, width: int):
    """The body as one wrapped image, cut to BODY_LINES with an ellipsis
    on the last line when there was more. Returns (image, lines shown,
    height of that many lines)."""
    one, step = _line_metrics(pt)
    key = ("body", text, round(pt, 2), width)
    got = cache.get(key)
    if got is not None:
        return got
    rtl = _is_rtl(text)
    block = _text(cache, text, pt, colour=INK, rtl=rtl, single=False,
                  width=width)
    n = max(1, 1 + int(round((block.height - one) / step)))
    _METRICS[(text, round(pt, 2), width)] = n
    if len(_METRICS) > 256:
        _METRICS.clear()
    shown = min(n, BODY_LINES)
    height = (one - 2) + (shown - 1) * step
    if n > BODY_LINES:
        block = block.crop((0, 0, block.width, height + 2)).copy()
        y0 = (shown - 1) * step
        strip = block.crop((0, y0, block.width, block.height))
        bb = strip.getchannel("A").getbbox()
        ell = _text(cache, ELLIPSIS, pt, colour=INK_DIM, rtl=False)
        gap = 4
        if rtl:
            x = (bb[0] - gap - ell.width) if bb else block.width - ell.width
            x = max(0, x)
        else:
            x = (bb[2] + gap) if bb else 0
            x = min(x, block.width - ell.width)
        # clear what the ellipsis stands in for, then paint it
        block.paste((0, 0, 0, 0), (x, y0, x + ell.width + gap, block.height))
        ey = y0 + max(0, (one - 2) - ell.height - 2)
        block.alpha_composite(ell, (int(x), int(ey)))
    got = (block, shown, height)
    cache[key] = got
    return got


def _body_height(text: str, pt: float, width: int) -> int:
    """How tall the body will be, without keeping its picture."""
    one, step = _line_metrics(pt)
    n = _METRICS.get((text, round(pt, 2), width))
    if n is None:
        _, shown, height = _body({}, text, pt, width)
        return height
    return (one - 2) + (min(n, BODY_LINES) - 1) * step


# ---------------------------------------------------------------------------
# the geometry
# ---------------------------------------------------------------------------

def _above_footer(card: dict, s: float) -> tuple[int, float]:
    """(the card's width, the y where the row BEFORE the footer ends)."""
    width = int(round(CARD_W * s))
    inner = int(width - 2 * PAD * s)
    h = PAD * s + HEAD_H * s + ROW * s + TITLE_H * s
    body = card.get("body") or ""
    if body:
        h += 4 * s + _body_height(body, 10.0 * s, inner)
    if card.get("project"):
        h += ROW * s + PROJECT_H * s
    if float(card.get("seconds") or 0) > 0:
        h += ROW * s + BAR_H * s
    return width, h


def _footer_h(card: dict) -> int:
    return BUTTON_H if is_pinned(card) else FOOTER_H


def measure(card: dict, scale: float = 1.0) -> tuple[int, int]:
    """The card's size at `scale`. Arithmetic, except for the body's
    height, which is the one thing only the text layout knows."""
    s = clamp_scale(scale)
    width, h = _above_footer(card, s)
    h += ROW * s + _footer_h(card) * s
    if int(card.get("more") or 0) > 0:
        h += 2 * s + MORE_H * s
    h += PAD * s
    return width, int(round(h))


def regions(card: dict, scale: float = 1.0) -> dict:
    """The rectangles that take the mouse, window-relative (the window is
    the card plus SHADOW on every side). The × is a client hit; the whole
    card is the handle you drag it by."""
    s = clamp_scale(scale)
    width, height = measure(card, s)
    x0 = y0 = SHADOW
    return {**_chrome_boxes(card, s, width, x0, y0),
            DRAG: (x0, y0, x0 + width, y0 + height)}


def _chrome_boxes(card: dict, s: float, width: int, x0: float,
                  y0: float) -> dict:
    """The client-hit boxes of ONE card whose top-left is (x0, y0): the ×
    on an ordinary card, the pill on a pinned one — never both."""
    pad = PAD * s
    if is_pinned(card):
        top = y0 + _above_footer(card, s)[1] + ROW * s
        bw, bh = BUTTON_W * s, BUTTON_H * s
        return {BUTTON: (x0 + width - pad - bw, top,
                         x0 + width - pad, top + bh)}
    box = CROSS * s
    return {DISMISS: (x0 + pad, y0 + pad, x0 + pad + box, y0 + pad + box)}


def _in(box, x, y) -> bool:
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def hit_test(card: dict, scale: float, x: int, y: int):
    """(HT code, what) for a point in window coordinates: the × is a
    client hit, the rest of the card drags, the shadow margin is not
    ours at all."""
    boxes = regions(card, scale)
    for what in (DISMISS, BUTTON):
        if what in boxes and _in(boxes[what], x, y):
            return HTCLIENT, what
    if _in(boxes[DRAG], x, y):
        return HTCAPTION, DRAG
    return HTTRANSPARENT, None


# ---------------------------------------------------------------------------
# the geometry of a COLUMN
#
# capture.py's stack arithmetic, copied (see GAP above for why it is copied
# and not imported) and turned inside out in one place: capture stacks
# cards of ONE size into a corner of the screen, so it can answer with an
# (x, y) per card; here the cards are different heights and they live in
# ONE window, so the answer is (x, y, w, h) per card, window-relative, and
# the window's own placement is overlay.NotifyCard.origin's business.
#
# NEWEST FIRST — index 0 is the top of the column, which is the opposite of
# capture.stack_at's "oldest at the top". Asked for on 2026-09-04: "the
# first one will be at the upper side and the oldest one will be on the
# down side". The bottom edge is what the window keeps still, so the pile
# grows away from the newest card and the one you just read never moves.
# ---------------------------------------------------------------------------

def clear_count(cards) -> int:
    """How many notifications a Clear all would see: the column's own
    cards or the engine's unread count, whichever is larger — the column
    is cut at `[notify] stack_max` and every card carries the whole
    count. The pinned card is never one of them."""
    notes = [c for c in cards if not is_pinned(c)]
    if not notes:
        return 0
    try:
        unread = int(notes[0].get("unread") or 0)
    except (TypeError, ValueError):
        unread = 0
    return max(len(notes), unread)


def clear_box(cards, scale: float = 1.0):
    """The Clear-all pill, WINDOW-relative (x0, y0, x1, y1), or None while
    fewer than two notifications are unread. It takes the top of the
    window, so the cards start under it; the bottom edge — the one the
    window is anchored by — does not move when it comes and goes."""
    if clear_count(cards) < 2:
        return None
    s = clamp_scale(scale)
    return (SHADOW, SHADOW, SHADOW + int(round(CLEAR_W * s)),
            SHADOW + int(round(CLEAR_H * s)))


def stack_layout(cards, scale: float = 1.0) -> list:
    """One (x, y, w, h) per card, WINDOW-relative, in the order given.

    `x` is SHADOW for every card and `y` accumulates the previous card's
    own height plus GAP, so a column of cards that measure differently
    still has exactly one gap between each pair. The widths are equal in
    practice — every card is CARD_W at the same scale — and nothing here
    assumes it: `stack_measure` takes the widest. With the Clear-all pill
    up (`clear_box`), the first card starts one GAP under it.
    """
    s = clamp_scale(scale)
    gap = int(round(GAP * s))
    places = []
    y = SHADOW
    pill = clear_box(cards, s)
    if pill is not None:
        y = pill[3] + gap
    for card in cards:
        width, height = measure(card, s)
        places.append((SHADOW, int(y), int(width), int(height)))
        y += height + gap
    return places


def stack_measure(cards, scale: float = 1.0) -> tuple[int, int]:
    """The WINDOW the column needs: the layout's bounding box with SHADOW
    on every side, which is the same margin one card's window has."""
    places = stack_layout(cards, scale)
    if not places:
        return 2 * SHADOW, 2 * SHADOW
    width = max(w for _x, _y, w, _h in places)
    pill = clear_box(cards, scale)
    if pill is not None:
        width = max(width, pill[2] - pill[0])
    bottom = max(y + h for _x, y, _w, h in places)
    return int(width + 2 * SHADOW), int(bottom + SHADOW)


def stack_shapes(cards, scale: float = 1.0) -> list:
    """Every piece of glass in the window as (x, y, w, h, radius): the
    Clear-all pill first when it is up (a capsule, radius h/2), then one
    rounded card per entry of `stack_layout`. What the painter draws a
    face on and what skin\\notify.py puts one blur window under each of —
    one list, so the two cannot disagree about where the glass is. (The
    radius is this module's; over the live blur the presenter draws the
    compositor's own instead, see skin\\glass.DWM_RADIUS.)"""
    s = clamp_scale(scale)
    shapes = []
    pill = clear_box(cards, s)
    if pill is not None:
        x0, y0, x1, y1 = pill
        shapes.append((x0, y0, x1 - x0, y1 - y0, (y1 - y0) / 2))
    for x, y, w, h in stack_layout(cards, s):
        shapes.append((x, y, w, h, RADIUS * s))
    return shapes


def stack_hit_test(cards, scale: float, x: int, y: int):
    """(HT code, (index, what) or None) for a point in window coordinates.

    A GAP IS DESKTOP. Between two cards there is nothing of ours — the
    pixels are transparent, the click belongs to whatever is underneath,
    and answering HTCAPTION there would let a 10 px stripe of air drag the
    whole column. Same for the shadow margin, for the same reason the
    single card has always handed it back: this thing sits over the right
    edge of the screen, where the close button of a maximised window is.

    The Clear-all pill answers HTCLIENT with index None — it belongs to no
    one card — and `(None, CLEAR)` is what a presenter turns into
    `pressed("dismiss", None)`.
    """
    s = clamp_scale(scale)
    pill = clear_box(cards, s)
    if pill is not None and _in(pill, x, y):
        return HTCLIENT, (None, CLEAR)
    for index, (cx, cy, width, height) in enumerate(stack_layout(cards, s)):
        if not (cx <= x <= cx + width and cy <= y <= cy + height):
            continue
        for what, box in _chrome_boxes(cards[index], s, width, cx,
                                       cy).items():
            if _in(box, x, y):
                return HTCLIENT, (index, what)
        return HTCAPTION, (index, DRAG)
    return HTTRANSPARENT, None


# ---------------------------------------------------------------------------
# the picture: shapes
# ---------------------------------------------------------------------------

def _rr(size, radius: float, fill=None, outline=None, width: float = 1.0,
        scale: int = 4):
    """An antialiased rounded rectangle layer, drawn big and shrunk."""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    big = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, w * scale - 1, h * scale - 1),
                        radius=max(1, int(radius * scale)),
                        fill=fill, outline=outline,
                        width=max(1, int(round(width * scale))))
    return big.resize((w, h), Image.LANCZOS)


def _cross(cache: dict, size: float, colour):
    """The dismiss ×, drawn at 4x and shrunk: Pillow antialiases
    nothing, and a 2 px diagonal at 1x is a staircase."""
    key = ("cross", int(size), colour)
    img = cache.get(key)
    if img is not None:
        return img
    n = max(1, int(size))
    k = 4
    big = Image.new("RGBA", (n * k, n * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    a, b = n * k * 0.32, n * k * 0.68
    lw = max(1, int(round(1.6 * k * n / 26)))
    d.line([(a, a), (b, b)], fill=tuple(colour) + (255,), width=lw)
    d.line([(b, a), (a, b)], fill=tuple(colour) + (255,), width=lw)
    img = big.resize((n, n), Image.LANCZOS)
    cache[key] = img
    return img


def _moon(cache: dict, size: float, colour):
    """A crescent — what stands where a pinned card's × would be: the
    screens are asleep, and this is not a thing to close. A disc with a
    second disc bitten out of it, at 4x and shrunk."""
    key = ("moon", int(size), colour)
    img = cache.get(key)
    if img is not None:
        return img
    n = max(1, int(size))
    k = 4
    m = n * k
    big = Image.new("RGBA", (m, m), (0, 0, 0, 0))
    ImageDraw.Draw(big).ellipse((m * .22, m * .20, m * .80, m * .78),
                                fill=tuple(colour) + (255,))
    bite = Image.new("L", (m, m), 0)
    ImageDraw.Draw(bite).ellipse((m * .40, m * .08, m * .98, m * .66),
                                 fill=255)
    alpha = big.getchannel("A")
    alpha.paste(0, mask=bite)
    big.putalpha(alpha)
    img = big.resize((n, n), Image.LANCZOS)
    cache[key] = img
    return img


def _folder(cache: dict, size: float, colour):
    """A small folder: a tab and a body, in outline."""
    key = ("folder", int(size), colour)
    img = cache.get(key)
    if img is not None:
        return img
    n = max(1, int(size))
    k = 4
    big = Image.new("RGBA", (n * k, n * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    c = tuple(colour) + (255,)
    lw = max(1, int(round(1.3 * k * n / 14)))
    m = n * k
    d.rounded_rectangle((m * .08, m * .28, m * .92, m * .84), m * .10,
                        outline=c, width=lw)
    d.line([(m * .08, m * .30), (m * .12, m * .18), (m * .42, m * .18),
            (m * .50, m * .28)], fill=c, width=lw, joint="curve")
    img = big.resize((n, n), Image.LANCZOS)
    cache[key] = img
    return img


def _fit_line(img, avail: float, rtl: bool):
    """A single-line image cut to `avail`, keeping the end that is read
    first: the right of a Hebrew line, the left of a Latin one."""
    if img.width <= avail:
        return img
    w = max(1, int(avail))
    return img.crop((img.width - w, 0, img.width, img.height)) if rtl \
        else img.crop((0, 0, w, img.height))


# ---------------------------------------------------------------------------
# the picture
# ---------------------------------------------------------------------------

def compose(card: dict, scale: float = 1.0, progress: float = 1.0,
            hover: str | None = None, cache: dict | None = None):
    """The card's CONTENT as one RGBA image the size of measure(): bar,
    head, title, body, project, clock, footer, badge and the × — on a
    transparent ground. The face (glass or flat) is the presenter's.

    `progress` is the clock, 1.0 full to 0.0 spent; `hover` names what
    is under the pointer ("dismiss" brightens the ×)."""
    cache = cache if cache is not None else {}
    s = clamp_scale(scale)
    width, height = measure(card, s)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    colour = tuple(card.get("colour") or KIND_COLOUR["info"])
    pad = PAD * s
    right = width - pad
    inner = int(width - 2 * pad)

    bar_h = max(2, int(round(BAR_H * s)))

    # -- head row: the ×, the sender's lamp and name, the time, the count.
    # B+ (2026-10-23): no bar of colour across the top any more — the
    # kind is the LAMP before the sender's name, the desk's own mark for
    # a state, and the × is the desk's round control.
    y = pad
    box = CROSS * s
    cx, cy = pad + box / 2, y + box / 2
    if is_pinned(card):
        moon = look.glyph("moon", box * 0.62, "dim")
        img.alpha_composite(moon, (int(cx - moon.width / 2),
                                   int(cy - moon.height / 2)))
    else:
        lit = hover == DISMISS
        look.disc(img, cx, cy, box / 2, hover=lit)
        cross = look.glyph("x", box * 0.62, "ink" if lit else "dim", 1.5)
        img.alpha_composite(cross, (int(cx - cross.width / 2),
                                    int(cy - cross.height / 2)))
    x_right = right
    badge = card.get("badge") or ""
    if badge:
        b = _text(cache, badge, 8.5 * s, "ink", look.W_STRONG)
        ph = 18 * s
        pw = max(ph, b.width + 14 * s)
        look.quiet(img, (right - pw, cy - ph / 2, right, cy + ph / 2))
        img.alpha_composite(b, (int(right - pw + (pw - b.width) / 2),
                                int(cy - b.height / 2)))
        x_right = right - pw - 8 * s
    when = card.get("when") or ""
    if when:
        w_img = _text(cache, when, 8.5 * s, INK_MUTED)
        img.alpha_composite(w_img, (int(x_right - w_img.width),
                                    int(cy - w_img.height / 2)))
        x_right -= w_img.width + 8 * s
    label = card.get("label") or ""
    lx = pad + box + 10 * s
    look.lamp(img, lx + 3.5 * s, cy, colour, r=3.5 * s, rings=True)
    if label:
        lx += 15 * s
        l_img = _fit_line(_text(cache, label, 9.0 * s, INK_DIM,
                                    look.W_LABEL), x_right - lx,
                          _is_rtl(label))
        img.alpha_composite(l_img, (int(lx), int(cy - l_img.height / 2)))
    y += HEAD_H * s + ROW * s

    # -- title
    title = card.get("title") or ""
    rtl_t = _is_rtl(title)
    t_img = _fit_line(_text(cache, title, 12.0 * s, "ink",
                                look.W_STRONG), inner, rtl_t)
    tx = (right - t_img.width) if rtl_t else pad
    img.alpha_composite(t_img, (int(tx), int(y + (TITLE_H * s - t_img.height)
                                             / 2)))
    y += TITLE_H * s

    # -- body, wrapped and cut by lines
    body = card.get("body") or ""
    if body:
        y += 4 * s
        block, _shown, b_h = _body(cache, body, 10.0 * s, inner)
        img.alpha_composite(block, (int(pad), int(y)))
        y += b_h

    # -- project, behind a folder
    project = card.get("project") or ""
    if project:
        y += ROW * s
        glyph = look.glyph("folder", PROJECT_H * s * 0.9, INK_MUTED + (255,),
                           1.3)
        rtl_p = _is_rtl(project)
        p_img = _fit_line(_text(cache, project, 8.5 * s, INK_MUTED),
                          inner - glyph.width - 6 * s, rtl_p)
        gy = int(y + (PROJECT_H * s - glyph.height) / 2)
        ty = int(y + (PROJECT_H * s - p_img.height) / 2)
        if rtl_p:
            img.alpha_composite(glyph, (int(right - glyph.width), gy))
            img.alpha_composite(p_img, (int(right - glyph.width - 6 * s
                                            - p_img.width), ty))
        else:
            img.alpha_composite(glyph, (int(pad), gy))
            img.alpha_composite(p_img, (int(pad + glyph.width + 6 * s), ty))
        y += PROJECT_H * s

    # -- the clock: a bar that empties towards the left
    if float(card.get("seconds") or 0) > 0:
        y += ROW * s
        track = _rr((inner, bar_h), bar_h / 2, fill=(255, 255, 255, 20))
        img.alpha_composite(track, (int(pad), int(y)))
        left_w = int(round(inner * max(0.0, min(1.0, float(progress)))))
        if left_w > 0:
            fill = _rr((left_w, bar_h), bar_h / 2, fill=colour + (220,))
            img.alpha_composite(fill, (int(right - left_w), int(y)))
        y += BAR_H * s

    # -- footer
    y += ROW * s
    foot = card.get("footer") or FOOTER
    f_avail = inner - ((BUTTON_W + 10) * s if is_pinned(card) else 0)
    f_img = _fit_line(_text(cache, foot, 8.0 * s, INK_MUTED),
                      f_avail, _is_rtl(foot))
    row_h = _footer_h(card) * s
    img.alpha_composite(f_img, (int(pad), int(y + (row_h - f_img.height)
                                              / 2)))
    if is_pinned(card):
        # The card's one action, so the one lit thing on it: B+'s soft
        # iris pill (look.primary), its light pooled UNDER it.
        bw, bh = int(BUTTON_W * s), int(BUTTON_H * s)
        lit = hover == BUTTON
        look.primary(img, (right - bw, y, right, y + bh), hover=lit,
                     glow=False)
        t = _text(cache, card.get("button") or "", 8.5 * s, "iris_on",
                      look.W_STRONG)
        img.alpha_composite(t, (int(right - bw + (bw - t.width) / 2),
                                int(y + (bh - t.height) / 2)))
    y += row_h

    # -- "+N earlier": what the column could not fit.
    #
    # The engine puts `more` on the LAST card of the column and on no
    # other, because that is the end of the pile and the only place a
    # count of what is underneath means anything. This module does not
    # decide it — it draws whatever the card carries — which is what lets
    # a test hand a "more" to the wrong card and see it drawn there.
    more = int(card.get("more") or 0)
    if more > 0:
        y += 2 * s
        m_img = _text(cache, f"+{more} earlier", 8.0 * s, INK_MUTED)
        img.alpha_composite(m_img, (int(pad), int(y + (MORE_H * s
                                                       - m_img.height) / 2)))
    return img


def compose_clear(cards, scale: float = 1.0, hover: bool = False,
                  cache: dict | None = None):
    """The Clear-all pill's CONTENT on a transparent ground, the size of
    `clear_box` — a ×, the words, and how many it will clear, faint, at
    the far end — or None while there is no pill. The face is the
    presenter's, exactly as with compose()."""
    cache = cache if cache is not None else {}
    s = clamp_scale(scale)
    pill = clear_box(cards, s)
    if pill is None:
        return None
    w, h = pill[2] - pill[0], pill[3] - pill[1]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ink = INK if hover else INK_DIM
    glyph = look.glyph("x", h * 0.62, ink + (255,), 1.5)
    x = 9 * s
    img.alpha_composite(glyph, (int(x), int((h - glyph.height) / 2)))
    x += glyph.width + 4 * s
    words = _text(cache, CLEAR_TEXT, 8.5 * s, ink, look.W_LABEL)
    img.alpha_composite(words, (int(x), int((h - words.height) / 2)))
    count = _text(cache, f"{clear_count(cards)}", 8.5 * s, INK_MUTED,
                      look.W_LABEL)
    cx = w - 12 * s - count.width
    if cx >= x + words.width + 6 * s:
        img.alpha_composite(count, (int(cx), int((h - count.height) / 2)))
    return img


def flat(card: dict, scale: float = 1.0, progress: float = 1.0,
         hover: str | None = None, cache: dict | None = None):
    """The card on a solid face — what the Tk fallback shows: a rounded
    card in the fallback palette, the same content on top, no shadow, no
    glass. Opaque on CARD."""
    cache = cache if cache is not None else {}
    s = clamp_scale(scale)
    width, height = measure(card, s)
    # The face is the same every frame and its rounded outline is drawn
    # at 4x; the clock repaints ten times a second, so it is kept.
    key = ("face", width, height, s)
    blank = cache.get(key)
    if blank is None:
        # B+'s glass with nothing behind it — Tk has no per-pixel alpha to
        # see through — so the same face, rim and light, opaque, on a
        # rectangle of the same night: the window's own corners are square
        # (the deal the skin folder is built on) and this says so.
        mask = look.rounded((width, height), (0, 0, width, height),
                            RADIUS * s)
        blank = Image.new("RGBA", (width, height),
                          look.INK["glass_flat"] + (255,))
        blank.alpha_composite(look.glass(mask, (0, 0, width, height),
                                         opaque=True))
        cache[key] = blank
    face = blank.copy()
    face.alpha_composite(compose(card, s, progress, hover, cache))
    return face


def stack_flat(cards, scale: float = 1.0, hover=None,
               cache: dict | None = None, progress: float = 1.0):
    """The whole column on solid faces — what the Tk fallback shows.

    stack_measure()'s size, with each card painted by flat() at the offset
    stack_layout gives it, and TRANSPARENT everywhere else: the gaps and
    the shadow margin are holes in the picture, which is the same answer
    stack_hit_test gives the mouse. Tk cannot show a hole, so the fallback
    window's own CARD_BG shows through there and the column looks like one
    slab with seams — that is the fallback being ugly and working, which
    is the deal the whole skin folder is built on (skin\\notify.py paints
    the same layout on real per-pixel alpha).

    `hover` is `(index, what)` or None, so brightening the × on the card
    under the pointer touches only that card.
    """
    cache = cache if cache is not None else {}
    s = clamp_scale(scale)
    width, height = stack_measure(cards, s)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pill = clear_box(cards, s)
    if pill is not None:
        pw, ph = pill[2] - pill[0], pill[3] - pill[1]
        face = look.glass(look.rounded((pw, ph), (0, 0, pw, ph), ph / 2),
                          (0, 0, pw, ph), opaque=True)
        face.alpha_composite(compose_clear(cards, s,
                                           hover == (None, CLEAR), cache))
        img.alpha_composite(face, (pill[0], pill[1]))
    for index, (x, y, _w, _h) in enumerate(stack_layout(cards, s)):
        what = hover[1] if (hover and hover[0] == index) else None
        img.alpha_composite(flat(cards[index], s, progress, what, cache),
                            (int(x), int(y)))
    return img


__all__ = ["ago", "card_for", "measure", "regions", "hit_test", "compose",
           "flat", "stack_layout", "stack_measure", "stack_hit_test",
           "stack_flat", "stack_shapes", "clear_box",
           "clear_count", "compose_clear", "CLEAR", "CLEAR_W", "CLEAR_H",
           "clamp_scale", "pinned_card", "is_pinned", "BUTTON",
           "BUTTON_H", "BUTTON_W", "PIN_ID", "FOOTER_H",
           "CARD_W", "SHADOW", "PAD", "RADIUS",
           "BODY_LINES", "SCALE_MIN", "SCALE_MAX", "HTTRANSPARENT",
           "HTCLIENT", "HTCAPTION", "DISMISS", "DRAG", "KIND_COLOUR",
           "FOOTER", "GAP", "ROW", "STACK_MAX", "MORE_H"]
