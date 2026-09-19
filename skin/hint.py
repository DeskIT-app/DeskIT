"""The hint card, on glass.

overlay.HintCard owns the thread, the queue and the delay; this owns the
picture, and — because a picture you can drag has to know where it is —
the three things the owner can change about it: where it sits, how big it
is, and whether it comes back at all.

WHAT IT LOOKS LIKE, SINCE 2026-09-19. A LAMPLIGHT card — face.py's plate,
the same shadow, surface and rim as the boot card — with the state bead
and the title on the right, and the keys in THREE GROUPS under their own
small headings (hint.py names them: the dictation, the screen, more),
every key cap right-aligned to one column at one minimum width so the
column reads as a column, and the "don't show this again" row as a quiet
checkbox at the foot. The card before this was one flat list of every
live key with chips of a dozen widths, and the owner's verdict on it was
"this design is terrible too".

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
  here guesses: strings are rendered wide and cropped to their alpha box.

* **It redraws only when something changed.** The dot animates and the
  boot card animates; this one is a static panel that sits on screen for
  seconds *while two Whisper models want the GPU*. A frame loop here
  would be spending the one resource the dictation is waiting for.

* **It takes the mouse in four small rectangles and nowhere else.** The
  strip along the top drags it, `−` and `+` resize it, the box at the
  bottom turns it off for good, and every other pixel answers
  HTTRANSPARENT — so a click aimed at the close button of a maximised
  window underneath still lands on the close button. That is the trap the
  status dot paid for once already, and the reason this is a hit test
  rather than a plain clickable window.

WHERE IT SITS IS NOT WHERE THE DOT SITS. On the right-hand corners the
card is placed BESIDE the dot, never over or under it: the dot is the one
thing on screen that says the app is alive, and it does not move for a
panel that is only up while a key is down.
"""
from __future__ import annotations

import logging
import queue
import time

from .face import disc, plate, rule, shape
from .glass import (Glass, primary_screen, virtual_screen, work_area,
                    HTTRANSPARENT, HTCLIENT, HTCAPTION)
from .palette import (BG, LINE, FG, KEY_BG, KEY_EDGE, LINE_HI, DOT_STATES,
                      rgb)

_log = logging.getLogger("app")

CARD_W = 340
RADIUS = 20
PAD = 18
ROW_H = 30
CHIP_H = 21
CHIP_MIN_W = 46           # every key cap at least this wide: ONE column
GROUP_H = 22              # a group's heading and the hairline under it
GROUP_GAP = 6             # between the last row of a group and the next
HEAD_H = 44               # the drag strip: everything above the hairline
SHADOW = 26               # room around the card for its own shadow
FACE_A = 216              # the face's alpha. boot.py uses 252; this is glass
BLUR = 11                 # px, the frost behind it
DOT_ROOM = 46             # the status dot's own corner, which is not ours
STEP = 0.1                # what one press of − or + is worth
SCALE_MIN, SCALE_MAX = 0.6, 1.4
BTN = 18                  # the − and + squares
FOOT_H = 26               # the checkbox row

INK = (241, 236, 226)        # FG      13.76:1 on the card
INK_DIM = (178, 168, 150)    # DIM      6.89:1
INK_FAINT = (126, 117, 100)  # FAINT    3.56:1 - labels and rules only
INK_KEY = rgb(FG)            # A KEY CHIP IS A KEY CAP, NOT A BUTTON.
#                              Fifteen chips in the accent turned this card
#                              into fifteen primary actions competing for
#                              one glance; it is a LEGEND. So the chips take
#                              ui.KeyCap's own face (KEY_BG on KEY_EDGE with
#                              the glyph in FG) and the only lit thing left
#                              on the card is the state bead at the top.

# The state bead, taken from the dot's own table so the card and the dot in
# the corner can never disagree about what colour "recording" is.
DOTS = {name: rgb(DOT_STATES[name][0])
        for name in ("recording", "locked", "ready", "busy", "paused")}

# What a hit landed on, for the click handler. Kept as strings rather than
# rectangles on the instance so `regions()` can be tested without a window.
SMALLER, BIGGER, DISMISS, DRAG = "smaller", "bigger", "dismiss", "drag"

_text_pil = None


def _text(text, pt=10.5, colour=INK, weight=400, rtl=True):
    """One line as an RGBA image, cropped to its glyphs.

    Cropping rather than trusting a width is not tidiness: see the module
    docstring — `pt` is scaled by the screen DPI, so any width picked here
    is wrong on a scaled display and the line loses its left-hand words.
    """
    global _text_pil
    if _text_pil is None:
        # Deferred, and deliberately not hoisted: importing visual_qa
        # builds Tk and pulls in the whole ask card, and this module is
        # reached for the first time in the middle of someone's dictation.
        from visual_qa import text_pil
        _text_pil = text_pil
    img = _text_pil(text or " ", 1400, pt=pt, colour=colour, weight=weight,
                    rtl=rtl, single=True)
    box = img.getchannel("A").getbbox()
    return img.crop(box) if box else img


def _to_skia(img):
    import skia
    return skia.Image.frombytes(img.convert("RGBA").tobytes(), img.size,
                                skia.kRGBA_8888_ColorType)


def clamp_scale(scale: float) -> float:
    return max(SCALE_MIN, min(SCALE_MAX, round(float(scale), 3)))


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


def measure(card: dict, scale: float = 1.0) -> tuple[int, int]:
    """The card's size, and therefore the window's. Pure arithmetic."""
    s = clamp_scale(scale)
    h = PAD + HEAD_H + 8
    for _name, rows in _groups(card):
        h += GROUP_H + ROW_H * len(rows) + GROUP_GAP
    h += 8 + FOOT_H + PAD - 4
    return int(round(CARD_W * s)), int(round(h * s))


def regions(card: dict, scale: float = 1.0) -> dict:
    """The four rectangles that take the mouse, window-relative.

    Returned as data so a test can check that they are inside the card,
    do not overlap, and move with the scale — none of which needs a
    window, a screen or a mouse.
    """
    s = clamp_scale(scale)
    width, height = measure(card, s)
    x0 = y0 = SHADOW
    pad = PAD * s
    btn = BTN * s
    right = x0 + width - pad
    # the two size buttons sit at the LEFT end of the head strip, so they
    # are nowhere near the state dot and the title on the right
    smaller = (x0 + pad, y0 + pad + 2, x0 + pad + btn, y0 + pad + 2 + btn)
    bigger = (smaller[2] + 4 * s, smaller[1], smaller[2] + 4 * s + btn,
              smaller[3])
    # the footer row, at the same place it is drawn: the whole row is the
    # checkbox, the way a settings row is, not the 14 px square alone
    fy = y0 + height - (FOOT_H + PAD - 4) * s
    dismiss = (x0 + pad, fy, right + 6, fy + FOOT_H * s - 4)
    drag = (x0, y0, x0 + width, y0 + HEAD_H * s)
    return {SMALLER: smaller, BIGGER: bigger, DISMISS: dismiss, DRAG: drag}


def _in(box, x, y) -> bool:
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def hit_test(card: dict, scale: float, x: int, y: int):
    """(HT code, what was hit) for a point in window coordinates.

    Everything that is not one of the four rectangles is HTTRANSPARENT,
    which is what lets a click go through to the window underneath.
    """
    boxes = regions(card, scale)
    for name in (SMALLER, BIGGER, DISMISS):
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


def paint(card: dict, backdrop=None, scale: float = 1.0):
    """The whole card as a Pillow RGBA picture, origin at the window's
    corner — the shadow's room included."""
    s = clamp_scale(scale)
    width, height = measure(card, s)
    pad = PAD * s
    x0 = y0 = SHADOW
    img = plate(width, height, RADIUS * s, SHADOW, FACE_A, backdrop)
    right = x0 + width - pad
    y = y0 + pad
    boxes = regions(card, s)
    line = rgb(LINE)

    def put(text_img, x, yy):
        img.alpha_composite(text_img, (int(round(x)), int(round(yy))))

    # -- the head: state bead and title on the right, size buttons on the
    # left, and the whole strip is the handle you drag it by.
    bead = DOTS.get(card.get("dot"), DOTS["ready"])
    bx, by, br = right - 5 * s, y + 8 * s, 4.5 * s
    img.alpha_composite(disc(img.size, bx, by, br * 2.2, bead + (34,)))
    img.alpha_composite(disc(img.size, bx, by, br, bead + (255,)))
    title = _text(card["title"], pt=12.0 * s, weight=600)
    put(title, right - 16 * s - title.width, y + 1)
    sub = _text(card["sub"], pt=9.0 * s, colour=INK_DIM)
    put(sub, right - 16 * s - sub.width, y + 22 * s)

    for name, glyph in ((SMALLER, "−"), (BIGGER, "+")):
        bx0, by0, bx1, by1 = boxes[name]
        _rrect(img, (bx0, by0, bx1, by1), 5 * s, fill=rgb(BG) + (110,),
               outline=rgb(LINE_HI) + (150,))
        mark = _text(glyph, pt=10.0 * s, colour=INK_DIM, weight=600,
                     rtl=False)
        put(mark, (bx0 + bx1) / 2 - mark.width / 2,
            (by0 + by1) / 2 - mark.height / 2)

    y += HEAD_H * s
    _rule(img, x0 + pad, right, y, line + (150,))
    y += 8 * s

    # ONE chip width for the whole card — the widest key plus its padding,
    # never under CHIP_MIN_W — so the caps make a column and every label
    # starts at the same edge. Chips of a dozen widths were a ragged
    # list; a legend is a table.
    chips = {}
    for _name, items in _groups(card):
        for key, _label, on in items:
            chips[(key, on)] = _text(key, pt=9.0 * s, weight=700, rtl=False,
                                     colour=INK_KEY if on else INK_FAINT)
    cw = max([CHIP_MIN_W * s] + [c.width + 20 * s for c in chips.values()])

    def rows(items):
        nonlocal y
        for key, label, on in items:
            chip = chips[(key, on)]
            box = (right - cw, y + 3 * s, right, y + 3 * s + CHIP_H * s)
            _rrect(img, box, 7 * s,
                   fill=(rgb(KEY_BG) + (190,)) if on else (rgb(BG) + (120,)),
                   outline=(rgb(KEY_EDGE) + (200,)) if on
                   else (line + (110,)))
            put(chip, right - cw / 2 - chip.width / 2,
                y + 3 * s + (CHIP_H * s - chip.height) / 2)
            text = _text(label, pt=10.0 * s, colour=INK if on else INK_FAINT)
            put(text, right - cw - 11 * s - text.width,
                y + 3 * s + (CHIP_H * s - text.height) / 2)
            y += ROW_H * s

    for name, items in _groups(card):
        if name:
            head = _text(name, pt=8.5 * s, colour=INK_FAINT, weight=600)
            put(head, right - head.width, y + 2)
            _rule(img, x0 + pad, right - head.width - 8 * s,
                  y + GROUP_H * s - 5 * s, line + (90,))
        y += GROUP_H * s
        rows(items)
        y += GROUP_GAP * s

    y += 8 * s
    _rule(img, x0 + pad, right, y, line + (110,))
    # the footer: a quiet checkbox row, the box at the right where the
    # eye lands first in Hebrew and the words to its left
    fy = boxes[DISMISS][1]
    tick = (right - 14 * s, fy + 5 * s, right, fy + 5 * s + 14 * s)
    _rrect(img, tick, 4 * s, fill=rgb(BG) + (120,), outline=line + (190,))
    foot = _text(card["footer"], pt=9.0 * s, colour=INK_DIM)
    put(foot, right - 24 * s - foot.width, fy + 12 * s - foot.height / 2)
    return img


def draw(canvas, card: dict, backdrop=None, scale: float = 1.0) -> None:
    """Paint the whole card onto a skia `canvas`, origin at the window's
    corner: the same picture as `paint()`, for the path that has one."""
    canvas.clear(0x00000000)
    canvas.drawImage(_to_skia(paint(card, backdrop, scale)), 0, 0)


def run(hint_card) -> None:
    """The body of overlay.HintCard's thread, with the picture swapped.

    Same contract as the dot and the splash: the queue, `_alive`,
    `_closing` and the `_DONE` sentinel stay exactly where overlay.py put
    them, and the delay stays overlay.py's rule rather than being
    reimplemented here.

    The window is built when a card becomes due and destroyed when it goes
    away, because its height depends on how many keys are live and on the
    scale. That is a few milliseconds once per hesitated dictation,
    against keeping a layered window alive for a panel that is usually
    not on screen.
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
        nonlocal redraw
        _code, what = hit_test(shown or pending, hint_card.scale, x, y)
        if what == SMALLER:
            hint_card.resized(clamp_scale(hint_card.scale - STEP))
        elif what == BIGGER:
            hint_card.resized(clamp_scale(hint_card.scale + STEP))
        elif what == DISMISS:
            hint_card.dismissed()
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
        glass.present(paint(card, _frost(x, y, win_w, win_h), s))
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
                        pending, due = None, None
                        take_down()
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
           "run"]
