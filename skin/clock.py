"""A clock a stalled frame cannot skip past.

THE BUG THIS EXISTS FOR, AND HOW IT LOOKED FROM OUTSIDE. The reveal is
written as a pure function of one clock — every element asks "where am I
at t milliseconds" — so a dropped frame changes no timing and the effect
looks identical at 30 fps and at 240. That is the right design, and it has
one hole: it only holds while the frames keep coming.

Take the time straight from `perf_counter()` and one long frame moves the
animation clock by the whole length of the stall. If that stall is longer
than what is left, the next frame computes a t past the end, the driver
loop sees "finished", and the moment is ABANDONED rather than finished.

That is not hypothetical. It was reported as "it doesn't look like the
video", and a frame-by-frame read of the screen recording showed exactly
one frame of the reveal — the flash — and then the desktop back to normal.
Reproduced deliberately: a single 2.0 s stall injected at t=3 ms drew the
whole 1.1 s wind-up and then stopped dead at the flash. The trigger on the
real machine was almost certainly the screen recorder starting to encode,
which is both the heaviest moment for the GPU and, by bad luck, the
heaviest frame of the effect.

THE FIX. Advance by at most MAX_STEP per frame. A stall then costs the
animation a little slow-motion instead of its entire ending, which for a
2.5 s one-shot is unambiguously the better trade. Nothing else about the
"pure function of t" design changes.

MAX_STEP is 90 ms: longer than any frame this actually takes (the reveal
medians 6.7 ms and its worst frame measured 68 ms), short enough that a
real freeze cannot swallow a beat. Beats here are 110-890 ms, so even a
run of clamped frames distorts the shape rather than losing it.
"""
from __future__ import annotations

import time

MAX_STEP_MS = 90.0


class Clock:
    """Milliseconds since start, clamped so a stall cannot skip ahead."""

    def __init__(self, start_ms: float = 0.0,
                 max_step_ms: float = MAX_STEP_MS) -> None:
        self.t = float(start_ms)
        self.max_step = float(max_step_ms)
        self.stalls = 0
        self._last = time.perf_counter()

    def tick(self) -> float:
        now = time.perf_counter()
        step = (now - self._last) * 1000.0
        self._last = now
        if step > self.max_step:
            self.stalls += 1
            step = self.max_step
        self.t += step
        return self.t


def absorb(last: float, max_step_ms: float = MAX_STEP_MS):
    """The same clamp, for code that already keeps its own wall-clock marks.

    Returns (now, shift) where `shift` is how far every stored start time
    should be pushed forward so that this frame's step is at most
    `max_step_ms`. boot.run keeps two of those — the card's own clock and
    its release instant — and shifting both is what keeps the card and the
    release on one timeline through a stall.
    """
    now = time.perf_counter()
    step = now - last
    shift = step - max_step_ms / 1000.0
    return now, (shift if shift > 0 else 0.0)
