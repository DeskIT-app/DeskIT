"""The release: one second of light, once, when the app becomes usable.

Everything here is a function of absolute milliseconds against one clock.
Nothing accumulates between frames, so a dropped frame changes the timing
of nothing — the effect looks identical at 30 fps and at 240 fps, and a
slow frame cannot compound into a drift.

THE RULES THIS IS BUILT TO, and where each came from:

  ONE FLASH. WCAG 2.3.1 and ITU-R BT.1702 exempt content with no more than
  three general flashes per second regardless of area or brightness, so a
  single impulse is unconditionally compliant and no luminance threshold
  ever has to be computed. A full-screen effect is far past the 0.006
  steradian area limit, so this is not optional. There is exactly one
  flash here, and nothing periodic anywhere in the 3-55 Hz band.

  DARK SELLS LIGHT. A 90 ms dip before the peak costs nothing and roughly
  doubles how bright the peak reads. It is the highest-value 90 ms in the
  whole sequence.

  A SHOCKWAVE IS A SHELL OF CONSERVED INK. As the radius grows the same
  luminous energy spreads over 2*pi*r, so thickness goes as 1/r and
  brightness as 1/r^2. A ring that keeps its stroke width is a UI ripple.

  ONE RING, NOT MANY — but two SPEEDS. Evenly spaced concentric rings read
  as sonar, and at 100 ms spacing they are literally a 10 Hz flash across
  a quarter of the screen, which is a photosensitivity hazard rather than
  a taste question. What reads as a three-dimensional expanding shell is a
  fast near-white leading front plus a slower, thicker, dimmer trailing
  one: the changing gap between them is parallax.

  RAYS DIE BEFORE THE RING. A ray fan that outlives the flash stops being
  light and becomes a sun icon. They are gone by 250 ms.

  NOTHING IS EVENLY SPACED AND NOTHING IS CENTRED. Exact 360/n spacing is
  a compass rose; a perfect circle at exact screen centre reads as UI
  chrome. Angles are jittered, the origin is offset, the ring is squashed
  a little, and the seed changes per boot so the fifth time is not a
  pixel-identical replay of the first.
"""
from __future__ import annotations

import math
import random

from . import ease
from .palette import (LIGHT_ACCENT, LIGHT_CORE, LIGHT_DEEP, LIGHT_HOT,
                      LIGHT_MID, argb)

# ------------------------------------------------------------- the clock
# Beats, in milliseconds from the moment the string lets go. Total under a
# second: past that the moment stops being punctuation and becomes an
# interruption, and past five seconds it would legally owe a pause control.
T_DIP = (-90, 0)          # the anticipation dip — dark, so the peak reads
T_BOLT = (-90, 40)        # the light travelling in from the card
T_FLASH = (36, 150)       # THE flash. One. Peaks on a single frame.
T_CORE = (30, 300)        # the white-hot centre
T_RING_A = (34, 540)      # leading shock front
T_RING_B = (110, 800)      # trailing rarefaction
T_RAYS = (30, 230)        # gone before the ring, always
T_SPARK = (36, 540)
T_END = 880

FLASH_PEAK_ALPHA = 0.42   # never a full white screen: glare, not light

# HIERARCHY, which is the whole reason these numbers are what they are.
# The first pass gave the ring, the rays and the sparks the same visual
# weight — thin bright streaks, all of them — and the result read as a
# dandelion rather than a detonation. If every element is bright, nothing
# is bright. So: the ring is the hero, the core is second, the rays are a
# short wide flare around the peak, and the sparks are texture underneath.
N_RAYS = 13               # prime, and few: these are flare spikes, not
N_HERO = 3                # travellers. 23 thin ones WAS the sea urchin.
N_SPARK = 64              # past ~200 hard shapes it is static, not power

RAY_REACH = 0.17          # of rmax. They live near the core, and die there.
SPARK_REACH = 0.52        # sparks crossing the whole screen read as rain

# THE FRAME BUDGET, AS AN AREA. Blending costs ~65 ns a pixel here (see
# Burst._sky for the measurement), so "how expensive is this frame" is the
# same question as "how many pixels does it blend". 190k pixels is ~12 ms,
# which leaves room for two rings, a core, the rays and the sparks inside
# one 60 fps frame even on the three frames where all of them peak at
# once (measured: 190k put that worst frame at 52 ms, 130k at 25).
#
# Capping a ring's WIDTH by its area is not a compromise dressed up as a
# rule — it IS the conserved-shell law. A shell of fixed luminous energy
# spread over a circumference of 2*pi*r must thin as 1/r, and
# w = budget / (2*pi*r) is that law written as code. The cheap ring and the
# physically correct ring are the same ring.
MAX_BLEND_PX = 130_000.0

SPARK_TAU = 158.0         # ms; drag, from a 0.90-per-frame decay at 60 fps
SPARK_GRAVITY = 0.00042   # px/ms^2 — a quarter of confetti-normal: a
#                           detonation, not a champagne fountain


class Burst:
    """One detonation. Build it (cheap), then call draw(canvas, t)."""

    def __init__(self, width: int, height: int, seed: int | None = None,
                 origin: tuple[float, float] | None = None,
                 came_from: tuple[float, float] | None = None) -> None:
        self.w, self.h = float(width), float(height)
        rng = random.Random(seed)
        self.rng = rng

        # Offset the origin 3-8% off centre and squash the ring a little:
        # any symmetry the eye can verify is symmetry that has been wasted,
        # and a perfect centred circle reads as a dialog, not a blast.
        if origin is None:
            ox = self.w * (0.5 + rng.uniform(-0.055, 0.055))
            oy = self.h * (0.455 + rng.uniform(-0.035, 0.035))
        else:
            ox, oy = origin
        self.ox, self.oy = ox, oy
        self.squash = rng.uniform(0.945, 0.980)
        self.came_from = came_from or (self.w * 0.92, self.h * 0.90)

        # reach past the farthest corner, so the front leaves the screen
        # rather than stopping politely just inside it
        corners = ((0, 0), (self.w, 0), (0, self.h), (self.w, self.h))
        self.rmax = 1.04 * max(math.hypot(ox - cx, oy - cy)
                               for cx, cy in corners)
        self.scale = self.h / 1440.0        # every px below is at 1440p

        # ---- rays: jittered angles, squared-random lengths, a few heroes
        step = math.tau / N_RAYS
        heroes = set(rng.sample(range(N_RAYS), N_HERO))
        self.rays = []
        for i in range(N_RAYS):
            angle = i * step + rng.uniform(-step * 0.35, step * 0.35)
            length = 0.45 + 0.55 * rng.random() ** 2
            if i in heroes:
                length *= rng.uniform(2.5, 3.0)
            self.rays.append((angle, length, rng.random(),
                              rng.uniform(0.0, 42.0)))       # spawn stagger

        # ---- sparks: broad speed spread = spark burst, not firework.
        # Tight clustering would put every particle on one expanding circle
        # (a peony shell, which says "celebration"); a broad spread fills
        # the disc, which says "impact". Mixing the two reads as indecision.
        self.sparks = []
        for _ in range(N_SPARK):
            angle = rng.uniform(0, math.tau)
            speed = (self.rmax * SPARK_REACH
                     * (0.15 + 0.85 * rng.random())) / SPARK_TAU
            life = T_SPARK[1] * rng.uniform(0.55, 1.05)      # +/-40%
            self.sparks.append((angle, speed, life, rng.random(),
                                rng.uniform(0.0, 60.0)))

    # ------------------------------------------------------------ helpers
    def _ring(self, canvas, skia, t, span, lead: bool):
        """One shock front. Thickness 1/r, brightness (1-t)^2, killed at
        0.85 rather than crawling invisibly to the edge."""
        k = ease.seg(t, *span)
        if k <= 0 or k >= 0.86:
            return
        if lead:
            r = self.rmax * ease.sedov(k)
            wid = max(1.5, 52 * self.scale * (1 - k) ** 1.5)
            alpha = 242 * (1 - k) ** 2.0
            warm = ease.clamp01(k * 1.5)
            colour = tuple(int(a + (b - a) * warm)
                           for a, b in zip(LIGHT_CORE, LIGHT_HOT))
        else:
            r = self.rmax * 0.76 * ease.out_cubic(k)
            wid = max(1.5, 92 * self.scale * (1 - k) ** 1.3)
            alpha = 146 * (1 - k) ** 1.55
            colour = LIGHT_MID
        if alpha < 1.5 or r < 2:
            return
        wid = min(wid, MAX_BLEND_PX / max(1.0, 2 * math.pi * r))
        wid = max(1.2, wid)          # never sub-pixel: they shimmer and drop
        outer = r + wid * 0.5
        inner = max(0.0, r - wid * 0.5)
        # A gradient ACROSS the stroke, so the band has a bright leading
        # edge and a soft trailing one instead of being a flat hoop.
        paint = skia.Paint(
            AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=wid,
            BlendMode=skia.BlendMode.kPlus, Dither=True,
            Shader=skia.GradientShader.MakeRadial(
                center=(self.ox, self.oy), radius=max(1.0, outer),
                colors=[argb(0, LIGHT_DEEP),
                        argb(alpha * 0.16, LIGHT_ACCENT),
                        argb(alpha, colour),
                        argb(alpha * 0.42, LIGHT_MID),
                        argb(0, LIGHT_DEEP)],
                positions=[0.0,
                           min(0.97, inner / outer),
                           min(0.985, (inner + wid * 0.60) / outer),
                           min(0.995, (inner + wid * 0.85) / outer),
                           1.0]))
        canvas.save()
        canvas.translate(self.ox, self.oy)
        canvas.scale(1.0, self.squash)
        canvas.translate(-self.ox, -self.oy)
        canvas.drawCircle(self.ox, self.oy, r, paint)
        canvas.restore()

        # Chromatic aberration: a LENS artifact, so radial only, on the
        # leading edge only, and only while the front is still moving fast.
        # Uniform CA across a frame is the instant tell that it is a filter.
        if lead and t < T_RING_A[0] + 120 and wid > 2:
            off = min(3.0, r * 0.0022)
            for shift, tint, aa in ((+off, (120, 210, 255), 0.30),
                                    (-off, (255, 196, 150), 0.24)):
                canvas.drawCircle(self.ox, self.oy, r + shift, skia.Paint(
                    AntiAlias=True, Style=skia.Paint.kStroke_Style,
                    StrokeWidth=max(1.0, wid * 0.30),
                    BlendMode=skia.BlendMode.kPlus,
                    Color=argb(alpha * aa, tint)))

    def _rays(self, canvas, skia, t):
        base = self.rmax * RAY_REACH
        for angle, length, jitter, stagger in self.rays:
            k = ease.seg(t, T_RAYS[0] + stagger, T_RAYS[1] + stagger)
            if k <= 0 or k >= 1:
                continue
            # a triangle, never a line: a constant-width bar of light is a
            # laser, and the taper is what makes it read as a flare
            reach = base * length
            r0 = self.rmax * 0.02 + reach * ease.out_expo(k) * 0.55
            r1 = r0 + reach * (1 - k) ** 0.5
            half = max(1.0, 15.0 * self.scale * (1 - k) ** 0.9
                       * (0.45 + 0.85 * jitter))
            ca, sa = math.cos(angle), math.sin(angle)
            px, py = -sa * half, ca * half
            path = skia.Path()
            path.moveTo(self.ox + ca * r1, self.oy + sa * r1)
            path.lineTo(self.ox + ca * r0 + px, self.oy + sa * r0 + py)
            path.lineTo(self.ox + ca * r0 - px, self.oy + sa * r0 - py)
            path.close()
            alpha = 236 * (1 - k) ** 1.5 * (0.45 + 0.55 * jitter)
            if alpha < 2:
                continue
            canvas.drawPath(path, skia.Paint(
                AntiAlias=True, BlendMode=skia.BlendMode.kPlus,
                Shader=skia.GradientShader.MakeLinear(
                    points=[(self.ox + ca * r0, self.oy + sa * r0),
                            (self.ox + ca * r1, self.oy + sa * r1)],
                    colors=[argb(alpha, LIGHT_HOT),
                            argb(alpha * 0.5, LIGHT_MID),
                            argb(0, LIGHT_ACCENT)],
                    positions=[0.0, 0.42, 1.0])))

    def _sparks(self, canvas, skia, t):
        """Drag, not gravity, is what makes a burst feel like it hit air.

        Position is the closed form of exponential drag rather than an
        integration, so it is exact at any frame rate. Each spark is drawn
        as the SEGMENT it covered over the last ~3 frames: length then
        encodes speed for free, which is motion blur without a blur.
        """
        hot = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kPlus,
                         Style=skia.Paint.kStroke_Style, StrokeCap=skia.Paint.kRound_Cap)
        for angle, speed, life, jitter, stagger in self.sparks:
            start = T_SPARK[0] + stagger
            k = ease.seg(t, start, start + life)
            if k <= 0 or k >= 1:
                continue
            ca, sa = math.cos(angle), math.sin(angle)

            def at(ms):
                travel = speed * SPARK_TAU * (1 - math.exp(-ms / SPARK_TAU))
                return (self.ox + ca * travel,
                        self.oy + sa * travel
                        + 0.5 * SPARK_GRAVITY * ms * ms)

            age = t - start
            x, y = at(age)
            tx, ty = at(max(0.0, age - 46.0))
            # full size for the first 40% of life, then sqrt decay to a
            # 1 px dot — a spark that fades to translucent grey reads as
            # dirt, so it is cut rather than faded
            shrink = 1.0 if k < 0.4 else (1 - (k - 0.4) / 0.6) ** 0.5
            wid = max(1.0, 4.4 * self.scale * (0.35 + 0.9 * jitter) * shrink)
            alpha = 255 * (1 - k) ** 1.15
            if alpha < 3:
                continue
            hot.setStrokeWidth(wid)
            hot.setColor(argb(alpha, LIGHT_CORE if k < 0.35 else LIGHT_HOT))
            canvas.drawLine(tx, ty, x, y, hot)

    def _core(self, canvas, skia, t):
        k = ease.seg(t, *T_CORE)
        if k <= 0 or k >= 1:
            return
        # easeOutBack on the SCALE only. Never on the ring radius, and
        # never on an alpha.
        r = self.h * (0.030 + 0.165 * ease.out_back(ease.out_expo(k), 1.3))
        r = min(r, math.sqrt(MAX_BLEND_PX / math.pi))     # same budget
        a = (1 - k) ** 1.6
        if r < 2 or a < 0.01:
            return
        canvas.drawCircle(self.ox, self.oy, r, skia.Paint(
            BlendMode=skia.BlendMode.kPlus, Dither=True,
            Shader=skia.GradientShader.MakeRadial(
                center=(self.ox, self.oy), radius=r,
                colors=[argb(255 * a, LIGHT_CORE), argb(246 * a, LIGHT_HOT),
                        argb(150 * a, LIGHT_MID), argb(40 * a, LIGHT_ACCENT),
                        argb(0, LIGHT_DEEP)],
                positions=[0.0, 0.09, 0.31, 0.58, 1.0])))

    def _bolt(self, canvas, skia, t):
        """The light arriving from the card, so the blast has a cause.

        Without it the detonation is an event that happens TO the screen;
        with it, the corner card visibly threw it.
        """
        k = ease.seg(t, *T_BOLT)
        if k <= 0 or k >= 1:
            return
        e = ease.out_quint(k)
        fx, fy = self.came_from
        hx, hy = fx + (self.ox - fx) * e, fy + (self.oy - fy) * e
        tail = 0.42 * (1 - k) ** 0.4
        tx, ty = hx - (self.ox - fx) * tail, hy - (self.oy - fy) * tail
        for width, tint, mul in ((9.0, LIGHT_ACCENT, 0.30),
                                 (4.5, LIGHT_MID, 0.60),
                                 (1.8, LIGHT_CORE, 1.00)):
            canvas.drawLine(tx, ty, hx, hy, skia.Paint(
                AntiAlias=True, BlendMode=skia.BlendMode.kPlus,
                Style=skia.Paint.kStroke_Style, StrokeCap=skia.Paint.kRound_Cap,
                StrokeWidth=width * self.scale,
                Shader=skia.GradientShader.MakeLinear(
                    points=[(tx, ty), (hx, hy)],
                    colors=[argb(0, tint), argb(230 * mul, tint)],
                    positions=[0.0, 1.0])))

    def _sky(self, canvas, skia, t):
        """The dip and the flash, as ONE opaque write.

        THE MEASUREMENT THAT DICTATES THIS. On this machine, in this Skia
        build, a full-screen BLENDED fill at 2560x1440 costs 238 ms — about
        65 ns a pixel — while the same rect written with kSrc costs 1.34 ms.
        Blending is ~180x more expensive than writing, and it does not
        matter whether the paint is a colour, a gradient, SrcOver or Plus:
        drawColor at 42% alpha, drawRect at 42% alpha, and a big radial
        gradient all land between 160 and 240 ms. Opaque writes are ~1.3 ms.

        Over a surface that has just been cleared to transparent, SrcOver
        is ALGEBRAICALLY Src — there is nothing underneath to blend with —
        so the two full-screen layers can be composited in Python, where it
        is four multiplies on scalars, and written once. Same picture,
        1.4 ms instead of 425.

        This is also why there is no full-screen bloom any more. A wide
        soft glow is, by definition, a large blended area, and at 65 ns a
        pixel a 1200 px radius disc is 270 ms a frame. The look this buys
        instead — crisp light, hard falloff, no mush — is the one the
        reference frames were strongest at anyway.
        """
        dip = ease.seg(t, *T_DIP) * (1 - ease.seg(t, T_FLASH[0], 300))
        flash = 0.0
        k = ease.seg(t, *T_FLASH)
        if 0 < k < 1:
            flash = FLASH_PEAK_ALPHA * (1 - k) ** 2.4
        if dip < 0.004 and flash < 0.004:
            return
        # composite the two by hand: dark under, warm light over
        da = ease.smoothstep(dip) * (107 / 255.0)
        dr, dg, db = 3, 6, 14
        fr, fg, fb = LIGHT_HOT
        out_a = da + flash - da * flash
        if out_a <= 0.002:
            return
        red = (dr * da * (1 - flash) + fr * flash) / out_a
        green = (dg * da * (1 - flash) + fg * flash) / out_a
        blue = (db * da * (1 - flash) + fb * flash) / out_a
        canvas.drawRect(skia.Rect.MakeWH(self.w, self.h), skia.Paint(
            BlendMode=skia.BlendMode.kSrc,
            Color=argb(255 * out_a, (min(255, red), min(255, green),
                                     min(255, blue)))))

    # --------------------------------------------------------------- draw
    def draw(self, canvas, t: float) -> bool:
        """Paint the frame at t ms. Returns False once it is all over."""
        import skia

        canvas.clear(0x00000000)
        if t > T_END:
            return False

        self._sky(canvas, skia, t)       # must be first: it WRITES, not blends
        self._bolt(canvas, skia, t)
        self._ring(canvas, skia, t, T_RING_B, lead=False)
        self._rays(canvas, skia, t)
        self._ring(canvas, skia, t, T_RING_A, lead=True)
        self._sparks(canvas, skia, t)
        self._core(canvas, skia, t)      # smallest and whitest, drawn last
        return True
