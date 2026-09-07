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

Everything geometric is a function of the card dict and the scale, so
tests check the layout without a screen; `regions()` is what both the
painter and the hit test read, which is what keeps the × pressed where
it is drawn.
"""
from __future__ import annotations

import time
from datetime import datetime

from PIL import Image, ImageDraw

# Win32 hit-test answers, spelled out so this module needs no skin import.
HTTRANSPARENT, HTCLIENT, HTCAPTION = -1, 1, 2

CARD_W = 360
SHADOW = 26               # room a glass window would leave around the card
PAD = 16
RADIUS = 20
BODY_LINES = 4
SCALE_MIN, SCALE_MAX = 0.6, 1.4

DISMISS, DRAG = "dismiss", "drag"

# One colour per kind: the bar across the top, the label and the badge.
# LAMPLIGHT semantics: done is the success green, input is the ACCENT
# (in this app "your attention is wanted" and "the primary action" are
# the same sentence, so they are the same colour on purpose), error is
# the danger red and info is COOL — the one cool point in a warm world.
KIND_COLOUR = {"done": (99, 200, 140), "input": (227, 166, 60),
               "error": (241, 134, 122), "info": (143, 192, 240)}
FOOTER = "Esc / click to dismiss"

# Row heights at scale 1.0. Chrome rows are fixed so the card's height is
# arithmetic; only the body's is measured, because only the body wraps.
BAR_H = 4                 # the kind's colour bar, and the clock
HEAD_H = 26               # the ×, the label and the time share this row
TITLE_H = 22
PROJECT_H = 16
FOOTER_H = 14
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
# skin folder deleted. Tuples, because Pillow wants them.
INK = (241, 236, 226)        # FG      13.76:1 on the card
INK_DIM = (178, 168, 150)    # DIM      6.89:1
INK_FAINT = (126, 117, 100)  # FAINT    3.56:1 — labels and rules
LINE = (58, 52, 42)          # LINE
CARD = (36, 32, 26)          # CARD

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
    key = (text, round(pt, 2), colour, weight, rtl, single, width)
    img = cache.get(key)
    if img is not None:
        return img
    img = _painter()(text or " ", max(20, int(width)), pt=pt, colour=colour,
                     weight=weight, rtl=rtl, single=single)
    if single:
        box = img.getchannel("A").getbbox()
        img = img.crop(box) if box else img
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

def measure(card: dict, scale: float = 1.0) -> tuple[int, int]:
    """The card's size at `scale`. Arithmetic, except for the body's
    height, which is the one thing only the text layout knows."""
    s = clamp_scale(scale)
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
    h += ROW * s + FOOTER_H * s
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
    pad = PAD * s
    box = CROSS * s
    return {DISMISS: (x0 + pad, y0 + pad, x0 + pad + box, y0 + pad + box),
            DRAG: (x0, y0, x0 + width, y0 + height)}


def _in(box, x, y) -> bool:
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def hit_test(card: dict, scale: float, x: int, y: int):
    """(HT code, what) for a point in window coordinates: the × is a
    client hit, the rest of the card drags, the shadow margin is not
    ours at all."""
    boxes = regions(card, scale)
    if _in(boxes[DISMISS], x, y):
        return HTCLIENT, DISMISS
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

def stack_layout(cards, scale: float = 1.0) -> list:
    """One (x, y, w, h) per card, WINDOW-relative, in the order given.

    `x` is SHADOW for every card and `y` accumulates the previous card's
    own height plus GAP, so a column of cards that measure differently
    still has exactly one gap between each pair. The widths are equal in
    practice — every card is CARD_W at the same scale — and nothing here
    assumes it: `stack_measure` takes the widest.
    """
    s = clamp_scale(scale)
    gap = int(round(GAP * s))
    places = []
    y = SHADOW
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
    bottom = max(y + h for _x, y, _w, h in places)
    return int(width + 2 * SHADOW), int(bottom + SHADOW)


def stack_hit_test(cards, scale: float, x: int, y: int):
    """(HT code, (index, what) or None) for a point in window coordinates.

    A GAP IS DESKTOP. Between two cards there is nothing of ours — the
    pixels are transparent, the click belongs to whatever is underneath,
    and answering HTCAPTION there would let a 10 px stripe of air drag the
    whole column. Same for the shadow margin, for the same reason the
    single card has always handed it back: this thing sits over the right
    edge of the screen, where the close button of a maximised window is.
    """
    s = clamp_scale(scale)
    pad = PAD * s
    box = CROSS * s
    for index, (cx, cy, width, height) in enumerate(stack_layout(cards, s)):
        if not (cx <= x <= cx + width and cy <= y <= cy + height):
            continue
        if _in((cx + pad, cy + pad, cx + pad + box, cy + pad + box), x, y):
            return HTCLIENT, (index, DISMISS)
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

    # -- the kind's colour bar, between the corner curves
    bar_h = max(2, int(round(BAR_H * s)))
    bar = _rr((width - 2 * RADIUS * s, bar_h), bar_h / 2,
              fill=colour + (255,))
    img.alpha_composite(bar, (int(RADIUS * s), 0))

    # -- head row: the ×, the label, the time, the badge
    y = pad
    box = CROSS * s
    cross = _cross(cache, box, INK if hover == DISMISS else INK_FAINT)
    img.alpha_composite(cross, (int(pad), int(y)))
    x_right = right
    badge = card.get("badge") or ""
    if badge:
        b = _text(cache, badge, 8.5 * s, colour=CARD, weight=700, rtl=False)
        pw = b.width + 12 * s
        ph = max(18 * s, b.height + 6 * s)
        pill = _rr((pw, ph), ph / 2, fill=colour + (255,))
        img.alpha_composite(pill, (int(right - pw), int(y + (box - ph) / 2)))
        img.alpha_composite(b, (int(right - pw + (pw - b.width) / 2),
                                int(y + (box - b.height) / 2)))
        x_right = right - pw - 8 * s
    when = card.get("when") or ""
    if when:
        w_img = _text(cache, when, 8.5 * s, colour=INK_FAINT)
        img.alpha_composite(w_img, (int(x_right - w_img.width),
                                    int(y + (box - w_img.height) / 2)))
        x_right -= w_img.width + 8 * s
    label = card.get("label") or ""
    if label:
        lx = pad + box + 8 * s
        l_img = _fit_line(_text(cache, label, 9.0 * s, colour=colour,
                                weight=700), x_right - lx, _is_rtl(label))
        img.alpha_composite(l_img, (int(lx), int(y + (box - l_img.height)
                                                 / 2)))
    y += HEAD_H * s + ROW * s

    # -- title
    title = card.get("title") or ""
    rtl_t = _is_rtl(title)
    t_img = _fit_line(_text(cache, title, 12.0 * s, weight=600), inner,
                      rtl_t)
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
        glyph = _folder(cache, PROJECT_H * s * 0.9, INK_FAINT)
        rtl_p = _is_rtl(project)
        p_img = _fit_line(_text(cache, project, 8.5 * s, colour=INK_FAINT),
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
        track = _rr((inner, bar_h), bar_h / 2, fill=LINE + (140,))
        img.alpha_composite(track, (int(pad), int(y)))
        left_w = int(round(inner * max(0.0, min(1.0, float(progress)))))
        if left_w > 0:
            fill = _rr((left_w, bar_h), bar_h / 2, fill=colour + (255,))
            img.alpha_composite(fill, (int(right - left_w), int(y)))
        y += BAR_H * s

    # -- footer
    y += ROW * s
    f_img = _text(cache, card.get("footer") or FOOTER, 8.0 * s,
                  colour=INK_FAINT)
    img.alpha_composite(f_img, (int(pad), int(y + (FOOTER_H * s
                                                   - f_img.height) / 2)))
    y += FOOTER_H * s

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
        m_img = _text(cache, f"+{more} earlier", 8.0 * s, colour=INK_FAINT,
                      rtl=False)
        img.alpha_composite(m_img, (int(pad), int(y + (MORE_H * s
                                                       - m_img.height) / 2)))
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
        blank = Image.new("RGBA", (width, height), CARD + (255,))
        blank.alpha_composite(_rr((width, height), RADIUS * s, fill=None,
                                  outline=LINE + (255,), width=1))
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
    for index, (x, y, _w, _h) in enumerate(stack_layout(cards, s)):
        what = hover[1] if (hover and hover[0] == index) else None
        img.alpha_composite(flat(cards[index], s, progress, what, cache),
                            (int(x), int(y)))
    return img


__all__ = ["ago", "card_for", "measure", "regions", "hit_test", "compose",
           "flat", "stack_layout", "stack_measure", "stack_hit_test",
           "stack_flat", "clamp_scale", "CARD_W", "SHADOW", "PAD", "RADIUS",
           "BODY_LINES", "SCALE_MIN", "SCALE_MAX", "HTTRANSPARENT",
           "HTCLIENT", "HTCAPTION", "DISMISS", "DRAG", "KIND_COLOUR",
           "FOOTER", "GAP", "ROW", "STACK_MAX", "MORE_H"]
