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
from .glass import Glass, HTCLIENT, HTTRANSPARENT, work_area
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


class Dot:
    def __init__(self, corner: str = DEFAULT_CORNER) -> None:
        import skia
        self._skia = skia
        self.corner = corner if corner in CORNERS else DEFAULT_CORNER
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
        """The corner of the PRIMARY monitor's WORK AREA — above the
        taskbar, never under it."""
        return place(self.corner, work_area())

    def hit(self, x: float, y: float) -> int:
        """WM_NCHITTEST for one window-relative pixel: HTCLIENT on the
        disc, HTTRANSPARENT everywhere else — including the halo and the
        containing ring, which is what keeps everything but the button
        click-through."""
        c = BOX / 2.0
        if math.hypot(float(x) - c, float(y) - c) <= HIT_R:
            return HTCLIENT
        return HTTRANSPARENT

    def draw(self, canvas, clock_ms: float) -> None:
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

        # a hairline containing ring, so the dot has an edge against a
        # white window as well as against a dark one
        canvas.drawCircle(cx, cy, CORE * 0.5 + 3.0, skia.Paint(
            AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.0,
            Color=argb(58, (255, 255, 255))))

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
    sentinel all stay exactly where overlay.py put them. Two things are
    read off the StatusDot and nothing else: `corner` (where), and
    `on_click` (what a click on the disc does — None, and the window is
    the old click-through layer with no hit test at all).
    """
    import overlay

    dot = Dot(getattr(status_dot, "corner", DEFAULT_CORNER))
    on_click = getattr(status_dot, "on_click", None)
    last_click = [0.0]

    def clicked(_x, _y) -> None:
        """WM_LBUTTONDOWN on an HTCLIENT pixel — by construction the
        disc, since everything else answered HTTRANSPARENT and never got
        the message. Fired on this thread; the callback only toggles."""
        now = time.monotonic()
        if now - last_click[0] < CLICK_GAP_S:
            return
        last_click[0] = now
        try:
            on_click()
        except Exception:
            _log.info("the dot's click could not open the shelf",
                      exc_info=True)

    if on_click is not None:
        glass = Glass(*dot.placement(), hit=dot.hit, clicked=clicked)
    else:
        glass = Glass(*dot.placement())
    glass.show()
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
                    dot.set(item)
            except queue.Empty:
                pass
            if status_dot._closing.is_set():
                break
            dot.draw(glass.canvas, (time.perf_counter() - start) * 1000.0)
            glass.flush()
            glass.pump()
            time.sleep(FRAME_S)
    except Exception:
        _log.info("skin status dot stopped early", exc_info=True)
    finally:
        glass.close()
        status_dot._closing.set()


__all__ = ["Dot", "run", "place", "BOX", "CORE", "HALO_R", "HIT_R",
           "CORNERS", "DEFAULT_CORNER"]
