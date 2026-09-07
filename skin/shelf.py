"""The shelf, on glass.

skin\\notify.py with the shelf's geometry, and deliberately nothing else:
the same Glass window with a hit test, the same shadow / frost / face /
rim / hairline recipe at the same offsets and the same alphas, and the
same rule about what is NOT redrawn here. `shelf_card.compose()` already
returns the whole panel on a TRANSPARENT ground, sized
`shelf_card.measure()`, precisely so a presenter can composite it over a
face of its own; `shelf_card.flat()` is the Tk fallback's OPAQUE face and
is never used on this path — painting it here would put a square corner
back under the curve, which is the defect skin\\notify.py exists to
remove.

THE ONE DELIBERATE DIFFERENCE FROM skin\\notify.py IS THE SHADOW, AND IT
COMES BACK. The notify column's drop shadow was removed on 2026-09-04 at
the owner's request — "I want without, only like the box, the message.
Without the shadow that it's outside the box" — and that was about a card
that ARRIVES: an uninvited thing should sit flat and quiet. The shelf is
the opposite case. It is asked for, it is the only thing on screen for as
long as it is up, and it has to read as lifted off whatever it opened
over. So skin\\hint.py's shadow is used: six offset round-rects with
geometrically decaying alpha rather than a MaskFilter blur, because a
blur is a separate rasterise-and-convolve and stacked hard shapes are
indistinguishable from one at this radius.

IT IS PAINTED WHEN SOMETHING CHANGED AND NEVER OTHERWISE. Nothing on this
panel animates. The uptime line is the only thing that moves at all, and
it moves once a minute; the hover changes on a mouse move. So the loop
repaints on a dirty flag and on a one-second uptime tick, and spends the
rest of its time asleep — which matters, because the panel can be open
while a Whisper model wants the GPU.

WHAT IT NEVER DOES: decide. A click on a row's answer becomes
`shelf.pressed(<region name>)`; a click on Pause becomes
`shelf.pressed("pause")`; a drag becomes `shelf.placed(x, y)`. What those
MEAN is shelf.ShelfCard's business and main.py's.

Reached through `skin.shelf_run(card)` — named with the `_run` suffix for
the reason skin\\__init__.paint_wave spells out at length: a hook called
`shelf` would rebind itself to this module on its first call and raise
"'module' object is not callable" on its second.
"""
from __future__ import annotations

import logging
import queue
import time

import shelf_card as sc

_log = logging.getLogger("app")

SHADOW = sc.SHADOW        # the room the window leaves round the card
RADIUS = sc.RADIUS
FACE_A = 202              # the face's alpha — skin\hint.py's glass weight
BLUR = 11                 # px, the frost behind it
TICK_S = 0.02             # the loop; a click must feel immediate
UPTIME_S = 1.0            # how often the one line that changes is redrawn
CLICK_PX = 4              # a release that travelled less is a click, not a
                          # drag — overlay.NotifyCard's rule and its number


def _to_skia(img):
    import skia
    return skia.Image.frombytes(img.convert("RGBA").tobytes(), img.size,
                                skia.kRGBA_8888_ColorType)


def _frost(x: int, y: int, width: int, height: int):
    """What is behind the panel, blurred. None if it cannot be had.

    Grabbed BEFORE the window exists, which is the only moment the answer
    is the desktop rather than ourselves.
    """
    try:
        from PIL import ImageGrab, ImageFilter
        shot = ImageGrab.grab(bbox=(x, y, x + width, y + height),
                              all_screens=True)
        if shot.size != (width, height):
            shot = shot.resize((width, height))
        return shot.convert("RGBA").filter(ImageFilter.GaussianBlur(BLUR))
    except Exception:
        _log.debug("skin: no frost behind the shelf", exc_info=True)
        return None


def face(canvas, width: int, height: int, scale: float, backdrop=None,
         x0: int = SHADOW, y0: int = SHADOW, shadow: bool = True) -> None:
    """The glass under the words: shadow, frost, face, rim, hairline.

    skin\\notify.py's `face` with the shadow put back (see the module
    docstring). Every corner is an antialiased RRect on a canvas the
    caller cleared to 0x00000000, so the pixels outside the curve keep
    alpha 0 all the way to UpdateLayeredWindow — which is the entire
    reason this window exists rather than a Tk one. Nothing here ever
    draws a plain Rect; one would put the square straight back.
    """
    import skia

    from .palette import BG, CARD, LINE, FG, argb

    s = sc.clamp_scale(scale)
    rect = skia.Rect.MakeXYWH(x0, y0, width, height)
    radius = RADIUS * s
    rrect = skia.RRect.MakeRectXY(rect, radius, radius)

    if shadow:
        # boot.py's recipe and skin\hint.py's numbers, drawn OUTSIDE the
        # face in the SHADOW margin.
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

    # The frost, clipped to the rounded face with doAntiAlias=True. Without
    # that flag the clip is a hard 1-bit mask and the blurred desktop would
    # stair-case out to the corner of the image — a square edge again, made
    # of the backdrop this time instead of the face.
    if backdrop is not None:
        canvas.save()
        canvas.clipRRect(rrect, doAntiAlias=True)
        canvas.drawImage(_to_skia(backdrop), 0, 0)
        canvas.restore()

    # The face: a hair lighter at the top the way a surface lit from above
    # actually is, and translucent (FACE_A of 255) so the frost behind it
    # still reads as the desktop rather than as a texture.
    canvas.drawRRect(rrect, skia.Paint(
        AntiAlias=True, Dither=True,
        Shader=skia.GradientShader.MakeLinear(
            points=[(x0, y0), (x0, y0 + height)],
            colors=[argb(FACE_A, CARD), argb(FACE_A + 14, BG)],
            positions=[0.0, 1.0])))
    canvas.drawRRect(rrect, skia.Paint(
        AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.0,
        Color=argb(180, LINE)))
    # A specular hairline on the top edge only, 60% of the width, fading at
    # both ends — the cheapest thing that says "glass". It stops well short
    # of the corners so it never fights the curve.
    canvas.drawLine(
        x0 + width * 0.20, y0 + 0.5, x0 + width * 0.80, y0 + 0.5,
        skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style,
                   StrokeWidth=1.0,
                   Shader=skia.GradientShader.MakeLinear(
                       points=[(x0 + width * 0.20, y0),
                               (x0 + width * 0.80, y0)],
                       colors=[argb(0, FG), argb(64, FG), argb(0, FG)],
                       positions=[0.0, 0.5, 1.0])))


def run(shelf) -> None:
    """The body of shelf.ShelfCard's thread, with the picture swapped.

    The queue, `_alive`, `_closing` and the `_DONE` sentinel stay exactly
    where overlay.py put them, and every decision still belongs to
    shelf.ShelfCard: this only paints and reports. The window is built
    when the panel opens and destroyed when it closes, like the review
    card's and the notify column's, because its height depends on how many
    rows are in the pile and on the scale.

    THE FOREGROUND. There is nothing to take and nothing to give back: a
    Glass is a plain CreateWindowExW popup carrying WS_EX_NOACTIVATE and
    shown with SW_SHOWNOACTIVATE, so it never takes the foreground in the
    first place. That is exactly why the key that closes this panel cannot
    arrive as WM_KEYDOWN and has to come off the global hook — see
    main.App._popup_key.
    """
    import overlay

    from .glass import Glass, primary_screen, virtual_screen, work_area

    glass = None
    shown = None                   # the card dict on screen, or None
    frost = None
    hover = None
    cache: dict = {}
    placed_at = (0, 0)
    pressing = False               # a click was already turned into a press
    dirty = False
    hushed = False
    last_paint = 0.0
    # The composed content, and what it was composed FOR. Measured on this
    # machine: shelf_card.compose() is 41 ms for a full pile with a warm
    # text cache, so composing it on every tick of a one-second loop would
    # be 4% of a core for as long as the panel is up — and this panel can
    # be up while two Whisper models want the machine. The card dict is a
    # new object on every push, so identity is the whole test.
    #
    # THE CARD ITSELF IS HELD IN THE KEY, not its id(). A freed dict's
    # address is handed straight back out by CPython's allocator, so an
    # id-only key would match a card that no longer exists and leave last
    # minute's picture on the screen. Holding the object costs one
    # reference and makes `is` mean what it looks like it means.
    picture = None
    picture_for = None             # (card, hover, scale)
    shelf._alive.set()

    def take_down():
        nonlocal glass, shown, frost, hover, pressing, picture, picture_for
        if glass is not None:
            glass.close()
            glass = None
        shown = None
        frost = None
        hover = None
        pressing = False
        picture = picture_for = None
        shelf.rect = None          # hovering() reads this; None means gone
        cache.clear()

    def on_hit(x, y):
        """Every pixel of the window, in window coordinates.

        HTCLIENT for a button or an answer (the X on the head band is
        one), HTCAPTION for the head strip (so Windows itself does the
        drag) and HTTRANSPARENT for everything else INCLUDING THE SHADOW
        MARGIN — which is what keeps a click aimed at whatever is
        underneath landing there. This panel opened in the top-right
        corner until 2026-09-07, where the close button of every
        maximised window is, so it was never a hypothetical; it opens
        above the dot in the bottom-right now and the rule is kept.

        It doubles as the hover tracker: WM_NCHITTEST arrives on every
        mouse move over the window, and leaving the panel always crosses
        the shadow margin, so the hover clears without a WM_MOUSELEAVE.
        """
        nonlocal hover, dirty
        if shown is None:
            return sc.HTTRANSPARENT
        code, what = sc.hit_test(shown, shelf.scale, x, y, cache)
        want = what if code == sc.HTCLIENT else None
        if want != hover:
            hover, dirty = want, True
        return code

    def on_move():
        """A press on the head strip was let go — a drag, or a click that
        never moved. overlay.NotifyCard.on_move's rule and its constant:
        travelled less than CLICK_PX and it is a click on the head, which
        this panel treats as nothing at all (the head is a handle, not a
        button); travelled more and it is where the owner wants it."""
        nonlocal placed_at
        if glass is None or shown is None:
            return
        x, y = glass.where()
        if abs(x - placed_at[0]) + abs(y - placed_at[1]) < CLICK_PX:
            return
        placed_at = (x, y)
        shelf.placed(x + SHADOW, y + SHADOW)
        shelf.rect = (x + SHADOW, y + SHADOW,
                      x + glass.width - SHADOW, y + glass.height - SHADOW)

    def on_click(x, y):
        """A left click on an HTCLIENT pixel — a button or one of a row's
        two answers. The name goes out untouched; `shelf_card.action_at`
        resolves it against the card, and shelf.ShelfCard decides."""
        nonlocal pressing
        if shown is None or pressing:
            return
        code, what = sc.hit_test(shown, shelf.scale, x, y, cache)
        if code != sc.HTCLIENT or what is None:
            return
        pressing = True
        try:
            shelf.pressed(what)
        finally:
            pressing = False

    def paint():
        nonlocal last_paint, dirty, picture, picture_for
        if glass is None or shown is None:
            return
        want = (shown, hover, shelf.scale)
        if picture is None or picture_for is None \
                or picture_for[0] is not shown \
                or picture_for[1:] != want[1:]:
            picture, picture_for = sc.compose(shown, shelf.scale, hover,
                                              cache), want
        canvas = glass.canvas
        canvas.clear(0x00000000)
        width, height = sc.measure(shown, shelf.scale)
        face(canvas, width, height, shelf.scale, frost, SHADOW, SHADOW)
        canvas.drawImage(_to_skia(picture), SHADOW, SHADOW)
        glass.flush()
        last_paint = time.monotonic()
        dirty = False

    def put_up(item):
        nonlocal glass, shown, frost, placed_at, hover, pressing
        s = sc.clamp_scale(shelf.scale)
        width, height = sc.measure(item, s)
        win_w, win_h = width + SHADOW * 2, height + SHADOW * 2
        if glass is not None and (glass.width, glass.height) != (win_w,
                                                                 win_h):
            # the pile changed height under him: a new window, same place
            take_down()
        shown, hover, pressing = item, hover if glass is not None else None, \
            False
        if hushed:
            # SOMEBODY IS DRAGGING A SELECTION. The card is held, not
            # lost: `set_hushed` puts it up again the moment the screen is
            # his. Mapping now would put a topmost window over the
            # screenshot selector and eat the drag — overlay.HintCard.hush
            # has the whole story.
            return
        if glass is None:
            # primary for the corner, the whole desktop for a saved
            # position: a panel left on a second screen belongs there.
            # The work area so that "beside the dot" is measured from the
            # edge the dot is measured from — above the taskbar.
            x, y = shelf.origin(win_w, win_h, primary_screen(), SHADOW,
                                virtual_screen(), work_area())
            frost = _frost(x, y, win_w, win_h)
            glass = Glass(x, y, win_w, win_h, hit=on_hit, moved=on_move,
                          clicked=on_click)
            placed_at = (x, y)
            paint()                # painted before it is shown, so the
            glass.show()           # panel is never an empty layer
            glass.raise_()
            shelf.rect = (x + SHADOW, y + SHADOW, x + width + SHADOW,
                          y + height + SHADOW)
        else:
            paint()

    def set_hushed(on: bool):
        """Obey `shelf._hushed`, on this thread and nowhere else.

        The caller — capture's screenshot flow, from the keyboard hook —
        only set an Event. Every window call is here, because Glass is as
        thread-bound as Tk is. The card dict itself is kept, so unhushing
        puts the same panel back rather than an empty one.
        """
        nonlocal hushed, glass, frost, hover, pressing
        if on == hushed:
            return
        hushed = on
        if on:
            if glass is not None:
                glass.close()
                glass = None
            frost = None
            hover = None
            pressing = False
            shelf.rect = None
        elif shown is not None:
            put_up(shown)

    try:
        while not shelf._closing.is_set():
            try:
                while True:
                    item = shelf._q.get_nowait()
                    if item is overlay._DONE:
                        shelf._closing.set()
                        break
                    if item is None:
                        take_down()
                    else:
                        put_up(item)
            except queue.Empty:
                pass
            if shelf._closing.is_set():
                break
            set_hushed(shelf._hushed.is_set())
            now = time.monotonic()
            # Nothing on this panel animates. The hover changes on a mouse
            # move and the uptime line arrives as a new card once a minute
            # (main.App._shelf_refresh), so a repaint is a dirty flag plus
            # a slow tick — never a frame loop, because this can be open
            # while two Whisper models want the machine. The slow tick
            # recomposes nothing when nothing changed; it re-blits the
            # picture already in hand, which is what keeps the layer
            # honest across a display change.
            if glass is not None and (dirty or now - last_paint >= UPTIME_S):
                paint()
            if glass is not None:
                glass.pump()
            time.sleep(TICK_S)
    except Exception:
        _log.info("skin shelf stopped early", exc_info=True)
    finally:
        take_down()
        shelf._closing.set()


__all__ = ["face", "run"]
