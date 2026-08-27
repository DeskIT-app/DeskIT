"""The status dot: a windowless app's only proof that it is running.

It lives in the top-right corner, which on Windows is the close button of
every maximised window, so it is click-through — the click lands on the X
underneath as if the dot were painted on the glass. That was true of the
old one too and is not a design choice to revisit.

What changes is only what it is made of. The old dot was a Tk oval on a
chroma-keyed window: a 1-bit key with no antialiasing, so a 13 px circle
had visibly stepped edges and could not have a halo, because every halo
pixel is a partly transparent pixel and a chroma key has no such thing.
On a layered surface with real per-pixel alpha it can be a disc with light
around it, which is what makes RECORDING catchable out of the corner of an
eye rather than only when looked at directly.

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
from .glass import Glass, primary_screen
from .palette import DOT_STATES, argb, rgb

_log = logging.getLogger("app")

# 38, not "whatever looks right": two tests find this window by its size.
# One accepts 10 < side < 60, the other identifies the dot as the window
# at most 40 px wide (that is how it tells the dot from the splash). A
# 46 px dot passed the first and silently failed the second.
BOX = 38                  # window; the disc is a fraction of it
CORE = 10.0               # the disc's diameter, in px
MARGIN_X, MARGIN_Y = 8, 4
FRAME_S = 1.0 / 45.0      # a status light does not need 90 fps


class Dot:
    def __init__(self) -> None:
        import skia
        self._skia = skia
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
        pw, _ph = primary_screen()
        return pw - BOX - MARGIN_X, MARGIN_Y, BOX, BOX

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

        # the halo — the whole reason this is a layered window
        canvas.drawCircle(cx, cy, CORE * 2.6, skia.Paint(
            BlendMode=skia.BlendMode.kPlus, Dither=True,
            Shader=skia.GradientShader.MakeRadial(
                center=(cx, cy), radius=CORE * 2.6,
                colors=[argb(150 * glow, fill), argb(52 * glow, fill),
                        argb(0, fill)],
                positions=[0.0, 0.45, 1.0])))

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
    sentinel all stay exactly where overlay.py put them.
    """
    import overlay

    dot = Dot()
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


__all__ = ["Dot", "run"]
