"""The second-reading card, on glass.

overlay.ReviewCard owns the thread, the queue, the clock and the verdicts;
this owns the picture, exactly as skin\\hint.py does for the hint card —
the same window (a Glass with a hit test, so the buttons are real and the
rest of the card drags), the same face recipe, the same cropped-text
path. Two things it does that the hint card does not:

* **It animates.** The bar under the title is the card's clock, and a
  clock has to move. The loop repaints ten times a second while a card is
  up — one content image composited over a face that was painted once —
  and nothing at all while none is. The hint card is static because it
  sits on screen while two Whisper models want the GPU; this one sits on
  screen AFTER the decodes are done, and a 400x200 layer at 10 fps is not
  a cost anyone can measure.

* **The clock stops under the pointer.** The moment the mouse is on the
  card the deadline moves with the time, so a card someone is reading
  cannot vanish on them mid-sentence — the same rule capture.py's corner
  card has for its own clock. Off the card, it runs on.

Nothing here decides anything. A button press or a key becomes
`card.pressed(name)`; the clock running out becomes `card.timed_out()`;
what those MEAN is overlay.ReviewCard's business and main.py's.
"""
from __future__ import annotations

import logging
import queue
import time

import review_card as rc
from .glass import Glass, primary_screen, virtual_screen
from .palette import BG, CARD, LINE, FG, argb

_log = logging.getLogger("app")

SHADOW = rc.SHADOW
RADIUS = rc.RADIUS
FACE_A = 202              # the face's alpha — skin\hint.py's glass weight
BLUR = 11
TICK_S = 0.03             # the loop; a click must feel immediate
REPAINT_S = 0.1           # the clock: ten frames a second is smooth enough


def _to_skia(img):
    import skia
    return skia.Image.frombytes(img.convert("RGBA").tobytes(), img.size,
                                skia.kRGBA_8888_ColorType)


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
        _log.debug("skin: no frost behind the review card", exc_info=True)
        return None


def face(canvas, width: int, height: int, scale: float, backdrop=None) -> None:
    """The glass under the words: shadow, frost, face, rim, hairline.
    skin\\hint.py's recipe, at the same offsets, so the two cards read as
    one family."""
    import skia
    s = rc.clamp_scale(scale)
    x0 = y0 = SHADOW
    rect = skia.Rect.MakeXYWH(x0, y0, width, height)
    radius = RADIUS * s
    rrect = skia.RRect.MakeRectXY(rect, radius, radius)
    for i in range(6, 0, -1):
        grow = i * 3.4
        a = 17 * (0.62 ** (6 - i))
        canvas.drawRRect(
            skia.RRect.MakeRectXY(
                skia.Rect.MakeXYWH(rect.left() - grow,
                                   rect.top() - grow * 0.35 + 5,
                                   rect.width() + grow * 2,
                                   rect.height() + grow * 1.5),
                radius + grow, radius + grow),
            skia.Paint(AntiAlias=True, Color=argb(a, (0, 0, 0))))
    if backdrop is not None:
        canvas.save()
        canvas.clipRRect(rrect, doAntiAlias=True)
        canvas.drawImage(_to_skia(backdrop), 0, 0)
        canvas.restore()
    canvas.drawRRect(rrect, skia.Paint(
        AntiAlias=True, Dither=True,
        Shader=skia.GradientShader.MakeLinear(
            points=[(x0, y0), (x0, y0 + height)],
            colors=[argb(FACE_A, CARD), argb(FACE_A + 14, BG)],
            positions=[0.0, 1.0])))
    canvas.drawRRect(rrect, skia.Paint(
        AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.0,
        Color=argb(180, LINE)))
    canvas.drawLine(
        x0 + width * 0.20, y0 + 0.5, x0 + width * 0.80, y0 + 0.5,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style,
                   StrokeWidth=1.0,
                   Shader=skia.GradientShader.MakeLinear(
                       points=[(x0 + width * 0.20, y0),
                               (x0 + width * 0.80, y0)],
                       colors=[argb(0, FG), argb(64, FG), argb(0, FG)],
                       positions=[0.0, 0.5, 1.0])))


def run(card) -> None:
    """The body of overlay.ReviewCard's thread, with the picture swapped.

    The queue, `_alive`, `_closing` and the `_DONE` sentinel stay where
    overlay.py put them. The window is built when a card arrives and
    destroyed when it goes, like the hint card's: its height depends on
    how many rows the proposal has."""
    import overlay

    glass = None
    shown = None                   # the card dict on screen
    frost = None
    hover = None
    cache: dict = {}
    deadline = None
    last_tick = time.monotonic()
    last_paint = 0.0
    dirty = False
    card._alive.set()

    def take_down():
        nonlocal glass, shown, frost, hover, deadline
        if glass is not None:
            glass.close()
            glass = None
        shown = None
        frost = None
        hover = None
        deadline = None
        card.rect = None
        cache.clear()

    def on_hit(x, y):
        nonlocal hover, dirty
        if shown is None:
            return rc.HTTRANSPARENT
        code, what = rc.hit_test(shown, card.scale, x, y)
        want = what if code == rc.HTCLIENT else None
        if want != hover:
            hover = want
            dirty = True
        return code

    def on_move():
        if glass is None:
            return
        x, y = glass.where()
        card.placed(x + SHADOW, y + SHADOW)
        card.rect = (x + SHADOW, y + SHADOW,
                     x + glass.width - SHADOW, y + glass.height - SHADOW)

    def on_click(x, y):
        if shown is None:
            return
        _code, what = rc.hit_test(shown, card.scale, x, y)
        if what in (rc.ACCEPT, rc.REJECT, rc.LATER):
            card.pressed(what)

    def paint(progress: float):
        nonlocal last_paint, dirty
        if glass is None or shown is None:
            return
        canvas = glass.canvas
        canvas.clear(0x00000000)
        w, h = rc.measure(shown, card.scale)
        face(canvas, w, h, card.scale, frost)
        content = rc.compose(shown, card.scale, progress, hover, cache)
        canvas.drawImage(_to_skia(content), SHADOW, SHADOW)
        glass.flush()
        last_paint = time.monotonic()
        dirty = False

    def put_up(item):
        nonlocal glass, shown, frost, deadline, hover
        take_down()
        s = rc.clamp_scale(card.scale)
        width, height = rc.measure(item, s)
        win_w, win_h = width + SHADOW * 2, height + SHADOW * 2
        x, y = card.origin(win_w, win_h, primary_screen(), SHADOW,
                           virtual_screen())
        frost = _frost(x, y, win_w, win_h)
        glass = Glass(x, y, win_w, win_h, hit=on_hit, moved=on_move,
                      clicked=on_click)
        shown = item
        hover = None
        paint(1.0)
        glass.show()
        glass.raise_()
        card.rect = (x + SHADOW, y + SHADOW, x + width + SHADOW,
                     y + height + SHADOW)
        deadline = (time.monotonic() + float(item.get("seconds") or 0)
                    if float(item.get("seconds") or 0) > 0 else None)

    try:
        while not card._closing.is_set():
            try:
                while True:
                    item = card._q.get_nowait()
                    if item is overlay._DONE:
                        card._closing.set()
                        break
                    if item is None:
                        take_down()
                    else:
                        put_up(item)
            except queue.Empty:
                pass
            if card._closing.is_set():
                break
            now = time.monotonic()
            dt, last_tick = now - last_tick, now
            if shown is not None and glass is not None:
                seconds = float(shown.get("seconds") or 0)
                progress = 1.0
                if deadline is not None:
                    if card.hovering():
                        deadline += dt          # reading: the clock waits
                    left = deadline - now
                    if left <= 0:
                        card.timed_out()
                        take_down()
                        time.sleep(TICK_S)
                        continue
                    progress = left / seconds if seconds > 0 else 1.0
                if dirty or now - last_paint >= REPAINT_S:
                    paint(progress)
                glass.pump()
            time.sleep(TICK_S)
    except Exception:
        _log.info("skin review card stopped early", exc_info=True)
    finally:
        take_down()
        card._closing.set()


__all__ = ["face", "run"]
