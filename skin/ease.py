"""Easing, and nothing else.

Every curve here is the canonical Penner/easings.net formula, kept as a
one-line expression so a timing can be read off the call site instead of
traced through a helper. The constants are not arbitrary: 1.70158 exists
because it makes easeOutBack overshoot exactly 10%, which is the ceiling
where an overshoot still reads as "crafted" rather than as a toy.

Two rules this file exists to enforce, both from the motion research:

  * Never ease-in on a release. Ease-in delays the first movement at the
    exact moment the eye is watching hardest, so a payoff that starts
    slowly reads as a dropped frame. Charges ease IN; releases ease OUT.

  * Never bounce an alpha. Material's own token set makes every "effects"
    spring critically damped and reserves bounce for position and size.
    An opacity that overshoots has to go above 1.0 or below 0.0, and both
    of those are clamps, which look like flicker.
"""
from __future__ import annotations

import math

BACK = 1.70158          # +10.00% overshoot at t=0.580 — the canonical value


def clamp01(k: float) -> float:
    return 0.0 if k < 0.0 else 1.0 if k > 1.0 else k


def seg(t: float, start: float, end: float) -> float:
    """Where t sits inside [start, end], clamped to 0..1.

    The whole animation is written as absolute milliseconds against one
    clock, and every element asks this for its own window. That is what
    lets elements spawn on different frames and still land together —
    the single most reliable amateur tell is everything sharing one t.
    """
    if end <= start:
        return 1.0 if t >= end else 0.0
    return clamp01((t - start) / (end - start))


def out_quad(k: float) -> float:
    return 1 - (1 - k) ** 2


def out_cubic(k: float) -> float:
    return 1 - (1 - k) ** 3


def out_quart(k: float) -> float:
    return 1 - (1 - k) ** 4


def out_quint(k: float) -> float:
    return 1 - (1 - k) ** 5


def out_expo(k: float) -> float:
    """Half the travel in the first 10% of the time. The shockwave curve:
    anything gentler than cubic reads as a loading spinner."""
    return 1.0 if k >= 1 else 1 - 2 ** (-10 * k)


def in_quad(k: float) -> float:
    return k * k


def in_cubic(k: float) -> float:
    return k * k * k


def in_expo(k: float) -> float:
    return 0.0 if k <= 0 else 2 ** (10 * k - 10)


def out_back(k: float, c1: float = BACK) -> float:
    """Overshoots and settles. c1=1.2-1.8 for a boot pop; past 2.5 it is
    cartoonish (c1=3.0 overshoots 25%)."""
    return 1 + (c1 + 1) * (k - 1) ** 3 + c1 * (k - 1) ** 2


def in_back(k: float, c1: float = BACK) -> float:
    """Undershoots first: charge and release in one expression, -10.00%
    at t=0.420 with the canonical constant."""
    return (c1 + 1) * k ** 3 - c1 * k * k


def sedov(k: float) -> float:
    """r proportional to t^(2/5): the Sedov-Taylor blast solution, which
    is what a real shock front does. Slightly softer than out_expo at the
    very start and slightly stronger in the tail, and it is the curve a
    physicist would recognise."""
    return clamp01(k) ** 0.4


def smoothstep(k: float) -> float:
    k = clamp01(k)
    return k * k * (3 - 2 * k)


def mix(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


def approach(current: float, target: float, weight: float) -> float:
    """Smoothed follow, for anything chasing a value across frames.
    weight 0.01 is slow, 0.1 is brisk, 0.5 is nearly instant at 60 fps."""
    return current + (target - current) * weight


def spring(k: float, bounce: float = 0.2) -> float:
    """Apple's Spring(duration:bounce:) mapping, normalised so k is the
    fraction of the spring's own duration. bounce 0.0 is .smooth, 0.15 is
    .snappy, 0.3 is .bouncy."""
    if k <= 0:
        return 0.0
    if k >= 1:
        return 1.0
    zeta = max(0.0001, 1.0 - bounce)
    wn = 2 * math.pi
    if zeta >= 1.0:
        return 1 - math.exp(-wn * k) * (1 + wn * k)
    wd = wn * math.sqrt(1 - zeta * zeta)
    return 1 - math.exp(-zeta * wn * k) * (
        math.cos(wd * k) + (zeta * wn / wd) * math.sin(wd * k))
