"""The status dot: a windowless app's only proof that it is running.

WHERE IT SITS, AND WHY THAT CHANGED. Until 2026-09-07 it lived in the
top-right corner and this docstring called that "not a design choice to
revisit", because that corner is the close button of every maximised
window and a dot that could take a click there would eat the X. The
owner revisited it that night: the dot now sits in the BOTTOM-RIGHT
corner of the primary monitor's work area — above the taskbar, the same
8 x 4 px margins as before — and `[dot] corner` says so (top-right is
still allowed; the shelf and the key card follow whichever it is).
Bottom-right is a corner nothing lives in: no close button, no window
chrome, only wallpaper or the edge of a document, which is exactly what
lets the next paragraph be true.

AND IT NO LONGER HAS TO SIT IN A CORNER AT ALL. `[dot] x/y` is where the
owner dragged it to and it beats `corner`; -100000 in both is "never
dragged". `spot()` is that rule and `place()` is still the corner half of
it, so boot.py's landing light and this window keep asking the same
function where the dot is. His words, 2026-09-07: "the dot — I want it to
be movable, and without needing to open and close the app... I press
'set' and then the desk disappears and I drag the dot wherever I want
it". Nothing here is read once any more: Settings' "Move the dot" goes
down the control pipe to the RUNNING app, which arms
overlay.StatusDot.move(), and the next frame this loop draws has the disc
answering HTCAPTION.

THE DISC IS A BUTTON; THE GLOW IS NOT. A click on the disc — the CORE
circle plus about 2 px, `HIT_R` — opens the shelf, exactly what
ctrl+alt+d does (main.App._tap_shelf: it reads one flag and starts a
thread, so it is safe to call from this window's own thread), and a
second click closes it. Every other pixel of the window — the halo, the
containing ring, the empty corners — answers HTTRANSPARENT, so the click
falls through to whatever is underneath as if the light were painted on
the glass. skin\\glass.Glass does the work: given `hit=` it is created
WITHOUT WS_EX_TRANSPARENT and asks `Dot.hit` per pixel. overlay.StatusDot
carries the callback as `on_click`; with none set the window keeps the
old style and the mouse never sees it at all.

THE DRAG IS THE BUTTON'S OTHER ANSWER, AND THE TWO CAN NEVER BOTH FIRE.
In move mode the same disc answers HTCAPTION instead of HTCLIENT, which
means Windows itself runs the drag (its own modal move loop, the notify
column's and the shelf's road) and — the part that matters — the press
arrives as WM_NCLBUTTONDOWN and NEVER as WM_LBUTTONDOWN, so `clicked` is
not merely ignored during a drag, it is never called. That is why there
is no travelled-far-enough test guarding the shelf here the way there is
on the notify card: the two gestures are on different messages. The GLOW
IS STILL NOT A BUTTON in move mode either — every pixel outside HIT_R
answers HTTRANSPARENT in both modes, so nothing underneath ever loses a
click to the light, which is the rule the top-right corner taught us.

THE HALO REACHES ZERO INSIDE THE WINDOW. It used to be a radial gradient
of radius CORE * 2.6 = 26 px in a 38 px box, which put alpha 27 on each
edge midpoint (0 at the corners): a faint tinted SQUARE, visible on any
wallpaper or title bar, that the owner read as "the dot looks like a
square". Measured 2026-09-07, all four lit states, 27/27/27/27. Now the
gradient ends at `HALO_R` = BOX / 2 - 1 = 18 px, its inner stop moved
out to keep the light where it was (alpha 27 at 14 px from the centre
against 42 before, measured), and a test asserts alpha 0 along the whole
border of every state. BOX stays 38: two tests identify the dot by its
size.

What the dot is MADE OF is the other half of the story. The old dot was
a Tk oval on a chroma-keyed window: a 1-bit key with no antialiasing, so
a 13 px circle had visibly stepped edges and could not have a halo,
because every halo pixel is a partly transparent pixel and a chroma key
has no such thing. On a layered surface with real per-pixel alpha it can
be a disc with light around it, which is what makes RECORDING catchable
out of the corner of an eye rather than only when looked at directly.

The state names and the (fill, ring, pulses) shape of overlay.STATES are
untouched — tests assert both, and main.py's _set_state speaks that
vocabulary from the keyboard hook.

NOTHING HERE FLICKERS. The locked breath is 0.16 Hz and the busy sweep is
a rotation, not a blink. The photosensitivity guidance prohibits anything
periodic between 3 and 55 Hz, and a status indicator sits on screen for
hours, which is exactly the case the rule is about.
"""
from __future__ import annotations

import logging
import math
import queue
import time

from . import ease
from .glass import (Glass, HTCAPTION, HTCLIENT, HTTRANSPARENT,
                    virtual_screen, work_area)
from .palette import DOT_STATES, NO_HALO, argb, rgb

_log = logging.getLogger("app")

# 38, not "whatever looks right": two tests find this window by its size.
# One accepts 10 < side < 60, the other identifies the dot as the window
# at most 40 px wide (that is how it tells the dot from the splash). A
# 46 px dot passed the first and silently failed the second.
BOX = 38                  # window; the disc is a fraction of it
CORE = 10.0               # the disc's diameter, in px
MARGIN_X, MARGIN_Y = 8, 4
FRAME_S = 1.0 / 45.0      # a status light does not need 90 fps
# Every glow must be alpha 0 STRICTLY inside the window, or the window's
# rectangle shows as a tinted square. The halo's gradient ends here — one
# pixel short of the edge — and a test walks the whole border.
HALO_R = BOX / 2.0 - 1.0
# The button: the disc and about two pixels of forgiveness around it.
# Never the ring (CORE * 0.5 + 3) and never the halo — those let the
# mouse through.
HIT_R = CORE / 2.0 + 2.0
# Two clicks closer together than this are one click. A double-click is
# the mouse's auto-repeat, and _tap_shelf is a toggle: without this a
# double-clicker would see the shelf open and close in one gesture.
CLICK_GAP_S = 0.3
CORNERS = ("bottom-right", "top-right")
DEFAULT_CORNER = "bottom-right"
# "never dragged: use the corner". overlay.HINT_UNSET and
# config.HINT_UNSET are the same number and a test holds the three
# together — it has to be one no desktop can reach, because the monitor
# to the left of the primary starts at x = -1920 here.
UNSET = -100000
# How thick the containing ring is drawn while the dot is waiting to be
# dragged. The ring is at CORE * 0.5 + 3 = 8 px and this widens it to
# either side, so the outermost lit pixel is about 9 px from the centre —
# well inside HALO_R, because everything on this window still has to
# reach alpha 0 before the border or the dot shows as a square again.
MOVE_W = 2.2


def place(corner: str, work: tuple[int, int, int, int]
          ) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the dot's window in `corner` of the work area
    `work` = (x, y, w, h). Pure arithmetic: boot.py's release lands its
    light here and the cards keep out of this square, so one function
    answers for all of them and a test can check it without a screen."""
    wx, wy, ww, wh = work
    x = wx + ww - BOX - MARGIN_X
    if str(corner) == "top-right":
        return x, wy + MARGIN_Y, BOX, BOX
    return x, wy + wh - BOX - MARGIN_Y, BOX, BOX


def spot(corner: str, work: tuple[int, int, int, int],
         x: int = UNSET, y: int = UNSET,
         bounds: tuple[int, int, int, int] | None = None
         ) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the dot's window: where it was DRAGGED to, or
    `place(corner, work)` when it never was.

    `place` is still the corner half of this and is what boot.py asks for
    a landing that has no saved position to consider; this is the whole
    rule. The arithmetic itself is overlay.dot_spot, which the Tk
    fallback uses with its own smaller box — one rule, two pictures, so a
    dot dropped on the glass path is honoured with skin\\ deleted too.

    `bounds` is the whole virtual desktop, and a dropped position is
    clamped against it: the entire 38 px square has to stay reachable,
    because unlike a card there is no part of a dot you can grab if the
    rest is off screen.
    """
    import overlay              # deferred: overlay imports this package
    ax, ay = overlay.dot_spot(corner, work, (BOX, BOX),
                              (MARGIN_X, MARGIN_Y), x, y, bounds)
    return ax, ay, BOX, BOX


class Dot:
    def __init__(self, corner: str = DEFAULT_CORNER,
                 x: int = UNSET, y: int = UNSET) -> None:
        import skia
        self._skia = skia
        self.corner = corner if corner in CORNERS else DEFAULT_CORNER
        # Where it was dragged to, and whether it is waiting to be
        # dragged again. `run` keeps both in step with the StatusDot;
        # nothing here decides either.
        self.x, self.y = int(x), int(y)
        self.moving = False
        self.state = "ready"
        self._shown = "ready"
        self._blend = 1.0     # 0..1 across a state change, for a cross-fade
        self._from = "ready"

    def set(self, name: str) -> None:
        if name != self.state:
            self._from = self._shown
            self.state = name
            self._blend = 0.0

    def placement(self) -> tuple[int, int, int, int]:
        """Where he dropped it, or the corner of the PRIMARY monitor's
        WORK AREA — above the taskbar, never under it. Clamped against
        the whole virtual desktop, so a dot left on a monitor that has
        been unplugged comes back on one that has not."""
        return spot(self.corner, work_area(), self.x, self.y,
                    virtual_screen())

    def hit(self, x: float, y: float) -> int:
        """WM_NCHITTEST for one window-relative pixel: the disc, and
        HTTRANSPARENT everywhere else — including the halo and the
        containing ring, which is what keeps everything but the button
        click-through, in both modes.

        The disc's answer is the one thing that changes. HTCLIENT is the
        button; HTCAPTION, while it is waiting to be moved, hands the
        press to Windows' own move loop — and a press that becomes
        WM_NCLBUTTONDOWN can never also arrive as the WM_LBUTTONDOWN
        that opens the shelf, which is the whole of "a drag must not fire
        the click".
        """
        c = BOX / 2.0
        if math.hypot(float(x) - c, float(y) - c) <= HIT_R:
            return HTCAPTION if self.moving else HTCLIENT
        return HTTRANSPARENT

    def draw(self, canvas, clock_ms: float,
             alarm_fill: str | None = None) -> None:
        skia = self._skia
        canvas.clear(0x00000000)
        cx = cy = BOX / 2.0

        self._blend = min(1.0, self._blend + 0.10)
        if self._blend >= 1.0:
            self._shown = self.state
        fill_a, ring_a, pulse_a = DOT_STATES.get(self._from,
                                                 DOT_STATES["ready"])
        fill_b, ring_b, pulse_b = DOT_STATES.get(self.state,
                                                 DOT_STATES["ready"])
        k = ease.smoothstep(self._blend)
        fill = tuple(int(a + (b - a) * k)
                     for a, b in zip(rgb(fill_a), rgb(fill_b)))
        pulses = pulse_b if k > 0.5 else pulse_a
        if alarm_fill is not None:
            # The dead-microphone alarm (overlay.StatusDot.alarm): the
            # blink is decided by the StatusDot's clock and handed in as
            # a colour, so this painter and the Tk one blink alike. It
            # overrides the state's fill and its breath — the alarm is
            # the one thing the dot has to say right now.
            fill, pulses = rgb(alarm_fill), False

        # A slow breath, so a recording you walked away from still reads as
        # live rather than as a frozen red dot. 0.16 Hz: nowhere near the
        # 3-55 Hz band, and slow enough to be ignorable while typing.
        glow = 1.0
        if pulses:
            glow = 0.62 + 0.38 * (0.5 + 0.5 * math.cos(clock_ms / 1000.0))

        # THE HALO — the whole reason this is a layered window, and the
        # whole reason PAUSED is legible. Every lit state glows; paused is
        # the one neutral in the set and it gets nothing, so the state
        # reads by the halo's ABSENCE. A grey halo on a dark wallpaper is
        # a smudge rather than a light, and hue alone would leave paused
        # and listening a colourblind viewer's coin toss. The halo fades
        # across a state change with everything else, so switching INTO
        # paused dims out rather than snapping off.
        halo = (0.0 if self.state in NO_HALO else 1.0) * k
        halo += (0.0 if self._from in NO_HALO else 1.0) * (1.0 - k)
        if halo > 0.004:
            # HALO_R, not CORE * 2.6: the gradient has to reach alpha 0
            # inside the window (see the module docstring — the square).
            # The inner stop sits at 0.62 of it, 11.2 px, roughly where
            # the old 0.45 of 26 px put it, so the light around the disc
            # is the same light and only its tail is shorter.
            canvas.drawCircle(cx, cy, HALO_R, skia.Paint(
                BlendMode=skia.BlendMode.kPlus, Dither=True,
                Shader=skia.GradientShader.MakeRadial(
                    center=(cx, cy), radius=HALO_R,
                    colors=[argb(150 * glow * halo, fill),
                            argb(52 * glow * halo, fill),
                            argb(0, fill)],
                    positions=[0.0, 0.62, 1.0])))

        # A hairline containing ring, so the dot has an edge against a
        # white window as well as against a dark one — and, while it is
        # waiting to be dragged, that same ring drawn white and twice as
        # thick. The control window has hidden itself by then ("the desk
        # disappears"), so the dot is the ONLY thing on screen that can
        # say the next press will move it rather than open the shelf, and
        # that move mode has not run out yet. It is the ring and not a
        # wider halo on purpose: what lights up has to be what you can
        # actually grab, and what you can grab is HIT_R — a bright circle
        # further out would be an invitation to press somewhere that
        # answers HTTRANSPARENT and does nothing.
        canvas.drawCircle(cx, cy, CORE * 0.5 + 3.0, skia.Paint(
            AntiAlias=True, Style=skia.Paint.kStroke_Style,
            StrokeWidth=MOVE_W if self.moving else 1.0,
            Color=argb(225 if self.moving else 58, (255, 255, 255))))

        if self.state == "busy":
            # a sweep, not a blink: transcribing is work in progress and a
            # rotation says that without ever changing luminance
            start = (clock_ms / 3.6) % 360.0
            box = skia.Rect.MakeLTRB(cx - CORE * 1.35, cy - CORE * 1.35,
                                     cx + CORE * 1.35, cy + CORE * 1.35)
            canvas.drawArc(box, start, 96, False, skia.Paint(
                AntiAlias=True, Style=skia.Paint.kStroke_Style,
                StrokeWidth=2.0, StrokeCap=skia.Paint.kRound_Cap,
                Color=argb(210, fill)))

        canvas.drawCircle(cx, cy, CORE * 0.5, skia.Paint(
            AntiAlias=True, Color=argb(255, fill)))
        # a specular highlight, up and left, the way a lit bead has one
        canvas.drawCircle(cx - CORE * 0.16, cy - CORE * 0.18, CORE * 0.20,
                          skia.Paint(AntiAlias=True,
                                     BlendMode=skia.BlendMode.kPlus,
                                     Color=argb(120, (255, 255, 255))))


def run(status_dot) -> None:
    """The body of overlay.StatusDot's thread, with the picture swapped.

    Same contract as the splash: the queue, _alive, _closing and the _DONE
    sentinel all stay exactly where overlay.py put them. What is read off
    the StatusDot: `corner` and `x, y` (where), `on_click` (what a click
    on the disc does — None, and the window is the old click-through
    layer with no hit test at all), `moving()` (whether the next press
    drags it instead) and `_replace` (somebody moved it from elsewhere).
    What is written back: `rect`, so the shelf knows which square not to
    close for, and `placed()` on a drop.
    """
    import overlay

    dot = Dot(getattr(status_dot, "corner", DEFAULT_CORNER),
              x=getattr(status_dot, "x", UNSET),
              y=getattr(status_dot, "y", UNSET))
    on_click = getattr(status_dot, "on_click", None)
    last_click = [0.0]

    def clicked(_x, _y) -> None:
        """WM_LBUTTONDOWN on an HTCLIENT pixel — by construction the
        disc, since everything else answered HTTRANSPARENT and never got
        the message, and by construction NOT while it is being moved,
        since the disc answers HTCAPTION then and this message is never
        sent at all. Fired on this thread; the callback only toggles.

        The move-mode line is belt as well as braces: Windows will not
        send this for an HTCAPTION pixel, but SendMessage from anywhere
        else on the machine will, and a dot that opened the shelf in the
        middle of being dragged would be a puzzle nobody could reproduce.
        """
        if status_dot.moving():
            return
        now = time.monotonic()
        if now - last_click[0] < CLICK_GAP_S:
            return
        last_click[0] = now
        try:
            on_click()
        except Exception:
            _log.info("the dot's click could not open the shelf",
                      exc_info=True)

    placed_at = [0, 0]
    alarming = [False]

    def dropped() -> None:
        """The press on the disc was let go, and Windows' move loop has
        finished. Fires for a real drag AND for a press that never moved,
        because DefWindowProc enters that loop either way — and move mode
        ends on both, since he asked for ONE move and leaving the disc
        armed would leave it unable to open the shelf.

        IT DOES NOT ASK WHETHER MOVE MODE IS STILL ON, and that is
        deliberate. This message can only exist because the disc answered
        HTCAPTION, which only happens in move mode — so getting here IS
        the proof. Asking again would throw away a drag that started at
        second 44 of a 45-second deadline and finished after it, which is
        the one drag most likely to be a real one.

        The position is read back off the handle rather than remembered:
        the drag was Windows moving the window and not us. Travelled less
        than overlay.DOT_CLICK_PX and it is a press he thought better of,
        so nothing is written. It is clamped BEFORE it is saved, so what
        goes into config.toml is where the dot actually ends up rather
        than a number the next launch would quietly correct.

        One release can arrive as BOTH WM_EXITSIZEMOVE and
        WM_NCLBUTTONUP, so this can run twice — and needs no latch of its
        own, because `StatusDot.placed` refuses an unchanged position and
        the second call is one.
        """
        status_dot.rest()
        dot.moving = False
        x, y = glass.where()
        if abs(x - placed_at[0]) + abs(y - placed_at[1]) \
                < overlay.DOT_CLICK_PX:
            return
        at_x, at_y, _w, _h = spot(dot.corner, work_area(), x, y,
                                  virtual_screen())
        status_dot.placed(at_x, at_y)
        _log.info("the dot was dropped at %d, %d", at_x, at_y)

    if on_click is not None:
        glass = Glass(*dot.placement(), hit=dot.hit, clicked=clicked,
                      moved=dropped)
    else:
        glass = Glass(*dot.placement())
    hidden = bool(getattr(status_dot, "hidden", False))
    if hidden:                          # a start without the model
        status_dot.rect = None
    else:
        glass.show()
        status_dot.rect = (glass.x, glass.y,
                           glass.x + glass.width, glass.y + glass.height)
    placed_at[0], placed_at[1] = glass.x, glass.y
    status_dot._alive.set()
    start = time.perf_counter()
    try:
        while not status_dot._closing.is_set():
            try:
                while True:
                    item = status_dot._q.get_nowait()
                    if item is overlay._DONE:
                        status_dot._closing.set()
                        break
                    if item is overlay._HIDE:
                        hidden = True
                        glass.hide()
                        status_dot.rect = None
                        continue
                    if item is overlay._SHOW:
                        hidden = False
                        at_x, at_y, _w, _h = dot.placement()
                        glass.move(at_x, at_y)
                        placed_at[0], placed_at[1] = at_x, at_y
                        glass.show()
                        status_dot.rect = (at_x, at_y, at_x + BOX, at_y + BOX)
                        continue
                    dot.set(item)
            except queue.Empty:
                pass
            if status_dot._closing.is_set():
                break
            if hidden:
                # nothing to draw; the window's messages still turn over
                glass.pump()
                time.sleep(FRAME_S)
                continue
            # Move mode is a DEADLINE the StatusDot keeps, so this only
            # reads it — which is what makes it expire on its own if he
            # presses the button and then walks away.
            dot.moving = status_dot.moving()
            if status_dot._replace.is_set():
                # A drop that had to be clamped, or "Back to the corner"
                # from the dashboard. UpdateLayeredWindow moves the
                # window by the destination point it is handed, so the
                # move costs nothing beyond the frame we were painting.
                status_dot._replace.clear()
                # The CORNER as well as the position, since 2026-09-08:
                # picking the other corner from Settings is live now
                # (main.App._dot_power), and this painter keeps its own
                # copy of it — left unread, a dot that had never been
                # dragged would not move at all.
                want = str(getattr(status_dot, "corner", dot.corner))
                dot.corner = want if want in CORNERS else dot.corner
                dot.x = int(getattr(status_dot, "x", UNSET))
                dot.y = int(getattr(status_dot, "y", UNSET))
                at_x, at_y, _w, _h = dot.placement()
                glass.move(at_x, at_y)
                placed_at[0], placed_at[1] = at_x, at_y
                status_dot.rect = (at_x, at_y, at_x + BOX, at_y + BOX)
            # The dead-microphone alarm travels the window toward the
            # middle of the work area and blinks; the frame the alarm
            # ends, the window goes back to where it rests (`alarming`
            # remembers that there was one to put back).
            alarm_fill = None
            if status_dot.alarming() is not None or alarming[0]:
                rest_x, rest_y, _w, _h = dot.placement()
                at, alarm_fill = status_dot.alarm_frame(
                    (rest_x, rest_y), BOX, work_area())
                glass.move(at[0], at[1])
                status_dot.rect = (at[0], at[1], at[0] + BOX, at[1] + BOX)
            alarming[0] = alarm_fill is not None
            dot.draw(glass.canvas, (time.perf_counter() - start) * 1000.0,
                     alarm_fill)
            glass.flush()
            glass.pump()
            time.sleep(FRAME_S)
    except Exception:
        _log.info("skin status dot stopped early", exc_info=True)
    finally:
        status_dot.rect = None          # nothing on screen to spare
        status_dot.rest()
        glass.close()
        status_dot._closing.set()


__all__ = ["Dot", "run", "place", "spot", "BOX", "CORE", "HALO_R", "HIT_R",
           "MOVE_W", "UNSET", "CORNERS", "DEFAULT_CORNER"]
