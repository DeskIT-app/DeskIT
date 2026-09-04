"""The notification card, on glass — and the square corner it removes.

THE DEFECT THIS FILE EXISTS TO FIX. The notify card shipped with a hook
(`skin.notify_run`) that always declined, so it was the only card in the
app with no glass presenter: overlay.NotifyCard._build_and_loop put it up
in a plain Tk window whose background is an opaque `CARD_BG` rectangle,
and `notify_card.flat()` filled that whole rectangle opaque and then drew
a ROUNDED OUTLINE inside it. The result is exactly what the owner
reported — "the corner is curved but there is something in the background
that makes them sharp". The curve was real; so was the square it was
painted on.

WHY THE FLAT TK CARD CANNOT ROUND ITS OWN CORNERS. It is not a missing
line of code, it is the toolkit:

  * Tk has no per-pixel alpha. A toplevel is opaque or, with
    `-alpha`, uniformly translucent — there is no channel in which the
    four corner pixels could be 0 and the middle 255.

  * `-transparentcolor` is a CHROMA KEY, not a mask. It punches out
    pixels that exactly equal one colour, so a corner Pillow antialiased
    into eight intermediate shades keeps seven of them: the card gets a
    fringe of the key colour instead of a hole. skin\\glass.py's header
    has the measurement — Tk antialiases nothing (0 intermediate shades
    in a 400x400 grab) and PIL antialiases everything, so a keyed window
    is either stair-cased or fringed, and there is no third setting.

So the corner cannot be cut where the picture is made. It has to be cut
where the picture is COMPOSITED, which on Windows means
UpdateLayeredWindow — skin\\glass.py — and that is what every other card
here (splash, dot, hint, review) already uses.

WHAT THIS FILE IS. skin\\review.py with the notify card's geometry: the
same Glass window with a hit test, the same shadow/frost/face/rim/hairline
recipe at the same offsets so the cards read as one family, and the same
ten-frames-a-second repaint because this card, like the review card, has a
clock bar that has to move. The CONTENT is not redrawn here at all —
`notify_card.compose()` already returns the whole card on a TRANSPARENT
ground, sized `notify_card.measure()`, precisely so a presenter can
composite it over a face of its own. `notify_card.flat()` is deliberately
NOT used on this path: flat() is the Tk fallback's opaque face, and
painting it here would put the square back.

DELETING skin\\ BRINGS THE SQUARE CORNERS BACK, ON PURPOSE. That is the
folder's whole promise (see skin\\__init__.py): the hook goes to None, the
Tk fallback in overlay.NotifyCard runs untouched, and the card is uglier
and completely functional. Nothing in overlay.py or notify_card.py was
changed to make this work.

Nothing here decides anything. A click becomes `card.pressed("dismiss")`,
a drag becomes `card.placed(x, y)`, the clock running out becomes
`card.timed_out()` — what those MEAN is overlay.NotifyCard's business and
notify.py's.
"""
from __future__ import annotations

import logging
import queue
import time

import notify_card as nc
from .glass import Glass, primary_screen, virtual_screen
from .palette import BG, CARD, LINE, FG, argb

_log = logging.getLogger("app")

SHADOW = nc.SHADOW        # the room the window leaves round the card
RADIUS = nc.RADIUS
FACE_A = 202              # the face's alpha — skin\hint.py's glass weight
BLUR = 11
TICK_S = 0.03             # the loop; a click must feel immediate
REPAINT_S = 0.1           # the clock: ten frames a second is smooth enough
CLICK_PX = 4              # a release that travelled less is a click, not a
                          # drag — overlay.NotifyCard._build_and_loop's rule
                          # and its constant, so the two paths agree on what
                          # a nudged mouse means


def _to_skia(img):
    import skia
    return skia.Image.frombytes(img.convert("RGBA").tobytes(), img.size,
                                skia.kRGBA_8888_ColorType)


def _frost(x: int, y: int, width: int, height: int):
    """What is behind the card, blurred. None if it cannot be had.

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
        _log.debug("skin: no frost behind the notify card", exc_info=True)
        return None


def _hide_from_capture(hwnd) -> bool:
    """Keep this one window out of every screen capture on this machine.

    overlay.NotifyCard promises it ("it stays out of every screenshot")
    and its Tk path keeps the promise with `_hide_from_capture(root)`; the
    glass path has to keep it too, or turning the skin on would quietly
    start burning notifications into the owner's screenshots. This is the
    only skin window that asks for it — the others are decoration the
    owner chose to look at, this one arrives uninvited.

    WDA_EXCLUDEFROMCAPTURE, the same flag overlay.py and capture.py use,
    measured there at 3600/3600 magenta pixels before the call and 0/3600
    after it. A PRIVATE ctypes.WinDLL, like every handle in skin\\glass.py:
    `ctypes.windll.user32` is one process-wide cached object and a restype
    set on it changes it for every other file in the repo.
    """
    WDA_EXCLUDEFROMCAPTURE = 0x00000011
    try:
        import ctypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p,
                                                    ctypes.c_uint]
        return bool(user32.SetWindowDisplayAffinity(
            ctypes.c_void_p(int(hwnd)), WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        # Not fatal and not worth a warning: a card in the corner of a
        # screenshot is a blemish, and the alternative to it is no card.
        _log.debug("skin: notify card not excluded from capture",
                   exc_info=True)
        return False


def face(canvas, width: int, height: int, scale: float, backdrop=None) -> None:
    """The glass under the words: frost, face, rim, hairline — no shadow.

    skin\\review.py's recipe at the same offsets and the same alphas, on
    purpose — the review card and the notify card are the same object to
    the eye, one asked for and one arriving, and a second glass recipe
    would make them read as two apps. The one deliberate difference is
    the drop shadow, which this card does not have: see below.

    `width`/`height` are the CARD's, not the window's: the window is
    SHADOW bigger on every side and everything below is drawn at
    (SHADOW, SHADOW), a margin that is now empty. Every corner is
    an antialiased RRect on a canvas the caller cleared to 0x00000000, so
    the pixels outside the curve keep alpha 0 all the way to
    UpdateLayeredWindow — which is the entire fix. Nothing here ever draws
    a plain Rect; one would put the square straight back.
    """
    import skia
    s = nc.clamp_scale(scale)
    x0 = y0 = SHADOW
    rect = skia.Rect.MakeXYWH(x0, y0, width, height)
    radius = RADIUS * s
    rrect = skia.RRect.MakeRectXY(rect, radius, radius)
    # NO DROP SHADOW, BY REQUEST (2026-09-04). This used to be six offset
    # round-rects with geometrically decaying alpha — boot.py's recipe,
    # drawn outside the face in the SHADOW margin — and the owner asked for
    # it gone: "I want without, only like the box, the message. Without the
    # shadow that it's outside the box." So the only thing this window
    # paints outside the curve now is nothing at all.
    #
    # The SHADOW margin itself STAYS, empty. It is transparent, the hit
    # test already hands it back to the desktop, and it is load-bearing
    # arithmetic everywhere else: notify_card.measure() sizes the window by
    # it, regions()/hit_test() are expressed in it, origin() subtracts it so
    # a dragged card is saved by the CARD's top-left rather than the
    # window's, and the position in [notify] x/y was written under that
    # rule. Reclaiming the 26 px would move a card the owner has already
    # placed, to buy back pixels nobody can see.
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


def run(card) -> None:
    """The body of overlay.NotifyCard's thread, with the picture swapped.

    The queue, `_alive`, `_closing` and the `_DONE` sentinel stay exactly
    where overlay.py put them, and every decision still belongs to
    overlay.NotifyCard: this only paints and reports. The window is built
    when a card arrives and destroyed when it goes, like the review card's,
    because its height depends on how many lines the body wrapped to.

    THE FOREGROUND. overlay.NotifyCard's Tk path reads `_foreground()`
    before it shows the window and hands the keyboard back with
    `_give_focus_back()` afterwards, because "Tk takes the foreground the
    moment it REALISES a window, and WS_EX_NOACTIVATE does not stop it"
    (AGENTS.md, measured 2026-08-26). There is nothing to give back here
    and so nothing to do: a Glass is a plain CreateWindowExW popup carrying
    WS_EX_NOACTIVATE and shown with SW_SHOWNOACTIVATE, so it never takes
    the foreground in the first place — no window between the two states,
    which is strictly better than taking it and returning it. skin\\hint.py
    and skin\\review.py are silent on this for the same reason.
    """
    import overlay

    glass = None
    shown = None                   # the card dict on screen
    frost = None
    hover = None
    cache: dict = {}
    deadline = None
    placed_at = (0, 0)             # where we last KNOW the window was put
    dismissing = False             # a click was already turned into a press
    last_tick = time.monotonic()
    last_paint = 0.0
    dirty = False
    card._alive.set()

    def take_down():
        nonlocal glass, shown, frost, hover, deadline, dismissing
        if glass is not None:
            glass.close()
            glass = None
        shown = None
        frost = None
        hover = None
        deadline = None
        dismissing = False
        card.rect = None           # hovering() reads this; None means gone
        cache.clear()

    def on_hit(x, y):
        """Every pixel of the window, in window coordinates.

        notify_card.hit_test answers HTCLIENT for the × box, HTCAPTION for
        the rest of the card (so Windows itself does the drag) and
        HTTRANSPARENT for the SHADOW margin — which is what keeps a click
        aimed at the close button of a maximised window underneath landing
        on that close button. The card sits mid-height on the right edge,
        which is where scrollbars live, so this is not a hypothetical.

        It doubles as the hover tracker: WM_NCHITTEST arrives on every
        mouse move over the window, so brightening the × costs nothing
        extra. Leaving the card always crosses the shadow margin, so hover
        is cleared without needing a WM_MOUSELEAVE.
        """
        nonlocal hover, dirty
        if shown is None:
            return nc.HTTRANSPARENT
        code, what = nc.hit_test(shown, card.scale, x, y)
        want = what if code == nc.HTCLIENT else None
        if want != hover:
            hover = want
            dirty = True
        return code

    def on_move():
        """A press on the card's HTCAPTION area was let go.

        Windows sends this for a real drag AND for a click that never
        moved, because DefWindowProc enters its modal move loop on the
        first WM_NCLBUTTONDOWN either way — so this one callback has to
        tell the two apart, exactly as the Tk path's on_release does:
        travelled less than CLICK_PX, it is the dismissal; travelled more,
        it is where the owner wants the card from now on.

        The position is read back off the handle rather than remembered,
        because a drag by HTCAPTION is Windows moving the window and not
        us. SHADOW is added before it is reported: `placed` wants the
        corner the owner can SEE, and saving the window's corner instead is
        the bug that made every hint-card drag near the top of the screen
        snap back.

        `dismissing` is the latch. WM_EXITSIZEMOVE and WM_NCLBUTTONUP can
        both arrive for one release, and firing `pressed("dismiss")` twice
        would mark a second, unseen notification as read.
        """
        nonlocal placed_at, dismissing
        if glass is None or shown is None:
            return
        x, y = glass.where()
        if abs(x - placed_at[0]) + abs(y - placed_at[1]) < CLICK_PX:
            if dismissing:
                return
            dismissing = True
            card.pressed("dismiss")
            return
        placed_at = (x, y)
        card.placed(x + SHADOW, y + SHADOW)
        card.rect = (x + SHADOW, y + SHADOW,
                     x + glass.width - SHADOW, y + glass.height - SHADOW)

    def on_click(x, y):
        """A left click on an HTCLIENT pixel — which is only ever the ×.

        The rest of the card is HTCAPTION and never reaches WM_LBUTTONDOWN
        at all; its click arrives through on_move above. Both roads lead to
        `pressed("dismiss")`, because a click anywhere on this card is the
        dismissal and the × is only the hint.
        """
        nonlocal dismissing
        if shown is None or dismissing:
            return
        code, what = nc.hit_test(shown, card.scale, x, y)
        if code == nc.HTCLIENT and what:
            dismissing = True
            card.pressed(what)

    def paint(progress: float):
        """One frame: the face painted fresh, the content composited on it.

        `canvas.clear(0x00000000)` is what makes the corners a hole rather
        than black — the DIB behind a layered window is premultiplied BGRA
        and UpdateLayeredWindow reads its alpha per pixel, so anything the
        face's RRect does not cover simply is not there.
        """
        nonlocal last_paint, dirty
        if glass is None or shown is None:
            return
        canvas = glass.canvas
        canvas.clear(0x00000000)
        w, h = nc.measure(shown, card.scale)
        face(canvas, w, h, card.scale, frost)
        # compose(), never flat(): flat() is the Tk fallback's OPAQUE face
        # with the same content on top, and drawing it here would paint a
        # solid CARD rectangle over the rounded glass — the exact defect
        # this module exists to remove.
        content = nc.compose(shown, card.scale, progress, hover, cache)
        canvas.drawImage(_to_skia(content), SHADOW, SHADOW)
        glass.flush()
        last_paint = time.monotonic()
        dirty = False

    def put_up(item):
        nonlocal glass, shown, frost, deadline, hover, placed_at, dismissing
        take_down()
        s = nc.clamp_scale(card.scale)
        width, height = nc.measure(item, s)
        win_w, win_h = width + SHADOW * 2, height + SHADOW * 2
        # primary for the corners, the whole desktop for a saved position:
        # a card left on a second screen belongs on that second screen.
        # `inset=SHADOW` is how NotifyCard.origin knows the window is
        # bigger than the card, so mid-height on the right edge is the
        # CARD's right edge and not the shadow's.
        x, y = card.origin(win_w, win_h, primary_screen(), SHADOW,
                           virtual_screen())
        frost = _frost(x, y, win_w, win_h)
        glass = Glass(x, y, win_w, win_h, hit=on_hit, moved=on_move,
                      clicked=on_click)
        _hide_from_capture(glass.hwnd)
        shown = item
        hover = None
        placed_at = (x, y)
        dismissing = False
        # Painted BEFORE it is shown, so the card is never on screen for
        # even one frame as an empty layer.
        paint(1.0)
        glass.show()
        glass.raise_()
        card.rect = (x + SHADOW, y + SHADOW, x + width + SHADOW,
                     y + height + SHADOW)
        seconds = float(item.get("seconds") or 0)
        deadline = (time.monotonic() + seconds) if seconds > 0 else None

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
                    # The clock stops under the pointer, so a card somebody
                    # is reading cannot vanish mid-sentence. `hovering()` is
                    # a rect and a cursor position, no window handle, which
                    # is why it is cheap enough to ask every tick.
                    if card.hovering():
                        deadline += dt
                    left = deadline - now
                    if left <= 0:
                        # Running out is NOT a dismissal: timed_out() leaves
                        # the item unread and notify.py's reminders bring it
                        # back. Only a click, or Esc over the card, marks it
                        # seen.
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
        _log.info("skin notify card stopped early", exc_info=True)
    finally:
        take_down()
        card._closing.set()


__all__ = ["face", "run"]
