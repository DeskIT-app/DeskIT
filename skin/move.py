"""The move frame, on glass: a light the size of every screen, and the
Done card.

move_card.py owns the words, the geometry and the pictures; dotmove.
MoveFrame owns the thread, the queue, the deadline and the keys; this
owns the WINDOWS and nothing else. Reached through `skin.move_run(frame)`
— named with the `_run` suffix for the reason skin\\__init__.paint_wave
spells out at length.

ONE WINDOW PER MONITOR, EACH THE SIZE OF ITS MONITOR. One window over
the whole virtual desktop would be simpler and wrong: this machine's
desktop is a 4480 x 1440 rectangle made of a 2560 x 1440 screen and a
1920 x 1080 one, and the owner asked for a halo "around every connected
screen" — four edges each, not four edges of the rectangle they happen to
fit in. capture.monitors() is the list, primary first.

THE LIGHT TAKES NO CLICKS. Each light is a Glass with no hit test, which
is the old WS_EX_TRANSPARENT window the mouse never sees: the dot is
dragged across it, a click on the desktop lands on the desktop, and the
light is light. The Done card is the one window here with a hit test,
and it claims exactly its button — the words, the face and the shadow
margin all answer HTTRANSPARENT (move_card.hit_test).

UNDER THE DOT. Every window here is topmost, and among topmost windows
the newest is on top — which would put a full-screen light OVER the dot
he is about to drag. So each window is slipped under the dot's handle
(Glass.under; overlay.StatusDot.hwnd), and the dot's own painter climbs
to the top the frame a move begins (skin\\dot.py). Whichever happens
second, the dot is on top.

PILLOW, NOT SKIA, on purpose. The halo is built once (move_card.glow, ~60
ms for 2560 x 1440 here) and nothing on it animates; the fade-in is the
window's whole-picture alpha (Glass.flush's SourceConstantAlpha), which
is one UpdateLayeredWindow per tick with the DIB already filled — no
repaint, no readback. gpu=False for the same reason the hint card gives:
a static Pillow picture on a GPU surface would be a readback for nothing.
Honours the reduced-motion setting (glass.wants_motion): then there is no
fade and the light is simply there.

THE CARD'S FROST IS GRABBED FIRST, before any light exists — the card
sits at the top of the screen, inside the top band of the halo, and a
frost grabbed after the lights were up would carry a half-faded gold
smear under the glass.
"""
from __future__ import annotations

import logging
import queue
import time

import move_card as mc

from .face import plate
from .glass import (Glass, HTCLIENT, HTTRANSPARENT, virtual_screen,
                    wants_motion, work_area)

_log = logging.getLogger("app")

TICK_S = 0.02             # the loop; a click on Done must feel immediate
FADE_S = 0.28             # the light's fade-in
FACE_A = 216              # the card's face alpha — skin\hint.py's glass weight
BLUR = 11                 # px, the frost behind the card
SHADOW = mc.SHADOW
RADIUS = mc.RADIUS


def _monitors() -> list[tuple[int, int, int, int]]:
    """Every monitor as (left, top, right, bottom), primary first; the
    whole desktop as one when Windows will not say."""
    try:
        import capture
        rects = [tuple(int(v) for v in m["rect"]) for m in capture.monitors()]
        if rects:
            return rects
    except Exception:
        _log.debug("skin: could not list the monitors", exc_info=True)
    vx, vy, vw, vh = virtual_screen()
    return [(vx, vy, vx + vw, vy + vh)]


def _frost(x: int, y: int, width: int, height: int):
    """What is behind the card, blurred. None if it cannot be had."""
    try:
        from PIL import ImageFilter, ImageGrab
        shot = ImageGrab.grab(bbox=(x, y, x + width, y + height),
                              all_screens=True)
        if shot.size != (width, height):
            shot = shot.resize((width, height))
        return shot.convert("RGBA").filter(ImageFilter.GaussianBlur(BLUR))
    except Exception:
        _log.debug("skin: no frost behind the Done card", exc_info=True)
        return None


def _field_for(dot_rect) -> tuple[int, int, int, int]:
    """The work area of the monitor the dot is on — where the Done card
    goes — or the primary's when there is no dot rectangle to ask about."""
    try:
        import overlay
        if dot_rect:
            cx = (int(dot_rect[0]) + int(dot_rect[2])) // 2
            cy = (int(dot_rect[1]) + int(dot_rect[3])) // 2
            field = overlay._monitor_work(cx, cy)
            if field:
                return field
    except Exception:
        _log.debug("skin: could not find the dot's monitor", exc_info=True)
    return work_area()


def run(frame) -> None:
    """The body of dotmove.MoveFrame's thread, with the windows in it.

    The queue, `_alive`, `_closing` and the `_DONE` sentinel stay exactly
    where overlay.py put them, and every decision still belongs to
    dotmove.MoveFrame and main.py: this only paints and reports. The
    windows are built when the frame goes up and destroyed when it comes
    down, like the shelf's.
    """
    import overlay

    lights: list = []              # one Glass per monitor
    card_glass = None              # the Done card's window
    card = None                    # its card dict while it is up
    scale = 1.0
    hover = None
    dirty = False
    cache: dict = {}
    frost = None
    born = 0.0                     # when the frame went up, for the fade
    until = 0.0                    # the deadline, on the monotonic clock
    fading = False
    frame._alive.set()

    def take_down():
        nonlocal lights, card_glass, card, hover, frost, born, until, fading
        for g in lights:
            try:
                g.close()
            except Exception:
                pass
        lights = []
        if card_glass is not None:
            card_glass.close()
            card_glass = None
        card = None
        hover = None
        frost = None
        born = until = 0.0
        fading = False
        frame.rect = None
        cache.clear()

    def on_hit(x, y):
        """Every pixel of the card's window: HTCLIENT on Done, HTTRANSPARENT
        elsewhere. Doubles as the hover tracker, as the shelf's does."""
        nonlocal hover, dirty
        if card is None:
            return HTTRANSPARENT
        code, what = mc.hit_test(card, scale, x, y, cache)
        want = what if code == HTCLIENT else None
        if want != hover:
            hover, dirty = want, True
        return code

    def on_click(x, y):
        if card is None:
            return
        code, what = mc.hit_test(card, scale, x, y, cache)
        if code == HTCLIENT and what:
            frame.pressed(what)

    def paint_card():
        nonlocal dirty
        if card_glass is None or card is None:
            return
        width, height = mc.measure(card, scale, cache)
        img = plate(width, height, RADIUS * scale, SHADOW, FACE_A, frost)
        img.alpha_composite(mc.compose(card, scale, hover, cache), (SHADOW, SHADOW))
        card_glass.present(img)
        dirty = False

    def put_up(dot_rect, deadline):
        nonlocal card_glass, card, frost, born, until, fading, scale
        take_down()
        scale = mc.clamp_scale(getattr(frame, "scale", 1.0))
        under = None
        try:
            under = frame.dot_hwnd() if callable(frame.dot_hwnd) else None
        except Exception:
            under = None
        # THE CARD FIRST — its frost has to be grabbed before any light is
        # on the screen (see the module docstring).
        card = mc.card_for()
        width, height = mc.measure(card, scale, cache)
        win_w, win_h = width + SHADOW * 2, height + SHADOW * 2
        x, y = mc.where((win_w, win_h), _field_for(dot_rect), SHADOW)
        frost = _frost(x, y, win_w, win_h)
        card_glass = Glass(x, y, win_w, win_h, gpu=False, hit=on_hit,
                           clicked=on_click)
        paint_card()
        card_glass.show()
        card_glass.raise_()
        card_glass.under(under)
        frame.rect = (x + SHADOW, y + SHADOW, x + width + SHADOW,
                      y + height + SHADOW)
        # THEN THE LIGHTS, one per monitor, presented at alpha 0 and faded
        # up by the loop — or simply there, if he asked for no motion.
        fading = wants_motion()
        for left, top, right, bottom in _monitors():
            w, h = right - left, bottom - top
            if w <= 0 or h <= 0:
                continue
            try:
                g = Glass(left, top, w, h, gpu=False)
                g.present(mc.glow(w, h), alpha=0.0 if fading else 1.0)
                g.show()
                g.raise_()
                g.under(under)
                lights.append(g)
            except Exception:
                _log.info("skin: no light on the monitor at %d, %d",
                          left, top, exc_info=True)
        # the card on top of the lights, and both under the dot
        card_glass.raise_()
        card_glass.under(under)
        born = time.monotonic()
        until = float(deadline or 0.0)
        _log.info("the move frame is up: %d light(s), Done at %d, %d",
                  len(lights), x + SHADOW, y + SHADOW)

    try:
        while not frame._closing.is_set():
            try:
                while True:
                    item = frame._q.get_nowait()
                    if item is overlay._DONE:
                        frame._closing.set()
                        break
                    if item is None:
                        take_down()
                    else:
                        put_up(*item)
            except queue.Empty:
                pass
            if frame._closing.is_set():
                break
            now = time.monotonic()
            if card is not None and until and now >= until:
                # He pressed the button and walked away. The dot's own
                # deadline is the same instant; the frame reports it so
                # main.py can close the session and say so.
                take_down()
                frame.expired()
                continue
            if fading and lights:
                k = min(1.0, (now - born) / FADE_S)
                for g in lights:
                    g.flush(k)
                if k >= 1.0:
                    fading = False
            if dirty:
                paint_card()
            for g in lights:
                g.pump()
            if card_glass is not None:
                card_glass.pump()
            time.sleep(TICK_S)
    except Exception:
        _log.info("skin move frame stopped early", exc_info=True)
    finally:
        take_down()
        frame._closing.set()


__all__ = ["run"]
