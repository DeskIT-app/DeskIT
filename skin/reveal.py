"""The release, rebuilt for the graphics card: light leaving the app.

WHY THIS FILE REPLACED burst.py's ROLE, IN THE OWNER'S OWN WORDS. The first
release was a detonation at the centre of the screen lasting 880 ms, and
what he said about it was: "it appears for half a second, you can barely
see it... and then suddenly it vanishes and there is some explosion that
appears for half a second." Two separate failures, and only one of them was
about beauty.

  IT WAS TOO FAST. The shock front crossed 2560 px in about 300 ms. That
  is faster than a person can follow, so the whole thing registered as a
  blink. This one takes 1.3 s to cross the screen and 2.4 s to finish. The
  research is clear that a reveal must stay under a second to feel snappy;
  the research is about UI transitions that happen dozens of times a day.
  This happens when you start the app. It is allowed to be a moment.

  IT CAME FROM NOWHERE. A blast at the centre of the screen has no cause.
  Here the light leaves the CARD - it is the energy the waveform spent the
  whole load gathering - so it sweeps out of the bottom-right corner and
  across everything. Origin in a corner also means the wavefront is a huge
  arc travelling diagonally rather than a ring you watch from outside,
  which is both more legible and more like light actually spilling.

WHAT MADE IT POSSIBLE. Everything here - a 200 px-wide soft wavefront, a
screen-filling bloom, blurred rays - is a large blended area, and on the
CPU rasteriser a large blended area costs 64 ns a pixel, which is 238 ms
for one full-screen fill. All of it was unaffordable and burst.py is built
around that fact. On the GPU the same fill is 0.07 ms and a 60 px Gaussian
blur is 0.09 ms. This file assumes the GPU and boot.py falls back to
burst.py without one.

WHAT IS UNCHANGED, because these were never the problem: exactly one
flash, capped at 0.42 alpha and preceded by a dip so it reads bright
without being glare; nothing periodic anywhere near 3-55 Hz; every element
seeded per boot so the fifth time is not a replay of the first; the whole
thing a function of one clock, so a dropped frame changes no timing.
"""
from __future__ import annotations

import math
import random
import struct

from . import ease
from .palette import argb

# ------------------------------------------------------------- the clock
# In milliseconds from the instant the waveform lets go. The card spends
# GATHER_MS before this collecting itself, so the whole moment - wind-up
# through settle - is about 2.8 s.
# t = 0 IS THE IMPACT. Everything before it belongs to the card's wind-up,
# which runs for GATHER_MS and is why these numbers are negative: the dim
# creeps in under the whole charge so the screen is already quiet when the
# hit lands.
T_DIP = (-1150, -180)      # the screen holds its breath, under the charge
T_FLASH = (0, 120)         # THE flash. One. Cut into, never ramped.
T_HOLD = 110               # HITSTOP: the aftermath, frozen, so the eye
#                            can catch up before anything moves
T_FRONT = (T_HOLD, 1050)   # the wavefront crossing the screen
T_TRAIL = (T_HOLD + 90, 1220)
T_BLOOM = (0, 1120)        # the light in the room
T_AURORA = (0, 1200)       # the colour flowing through it
T_RAYS = (0, 560)          # light through the gap, from the origin
T_MOTES = (T_HOLD, 1330)
T_SETTLE = (900, 1300)     # everything leaves
T_LAND = (520, 1360)       # ...into the status dot, which is
#                            where the app lives afterwards
T_END = 1360

# The front does not start at nothing. At the impact it is CUT to already
# being this far out, so the first frame of the payoff is a shape big
# enough to read rather than a dot. This is the single biggest legibility
# win in the whole sequence.
FRONT_R0 = 0.17            # of reach

FLASH_PEAK = 0.42          # never a white screen: glare is not brightness
DIP_PEAK = 0.19            # and never a black one either. A
#                            15-20% global dim frames the reveal
#                            as a performance without hiding the
#                            desktop under it.

N_RAYS = 9
N_MOTES = 38

# The light, core outward. Warm at the heart and cool at the edge, because
# that is what hot things do, and because a single hue reads as a UI
# element lit from inside rather than as light.
#
# Retuned for LAMPLIGHT, and the shape did not change — only where the warm
# half lands. The middle of the ramp is now the lamp's own gold instead of
# a pale blue, so what opens over the desktop is the same light the icon,
# the dot and the primary button are painted with. The blue did not go
# away: it moved to the edge, which is exactly where it is in the mark.
# The DEEPEST stops stay blue-black because a warm shadow reads as haze.
# The seven stops are used as a BRIGHTNESS ramp as well as a hue one —
# `_front` reads them inner-to-edge and every gradient below assumes each
# stop is dimmer than the one before it — so the retune keeps the relative
# luminance order (1.00 / .90 / .68 / .55 / .51 / .02) and moves only the
# hue. Getting that wrong turns a shockwave inside out.
CORE = (255, 255, 255)
HOT = (255, 240, 206)            # incandescent — palette.LIGHT_HOT
WARM = (250, 206, 128)           # the lamp, opened up
MID = (240, 186, 92)             # ACCENT_TEXT: the lamp at its own weight
COOL = (143, 192, 240)           # palette.COOL — the corona at the rim
DEEP = (24, 38, 60)              # night beyond it
DIM = (3, 6, 14)


# ---------------------------------------------------------------- aurora
# A domain-warped fractal-noise field, masked to a soft disc around the
# origin. This is the layer that makes the reveal look like LIGHT rather
# than like a lighting diagram: everything else here is radially symmetric,
# and radial symmetry alone reads as a graphic. The noise breaks it up and
# carries the colour.
#
# Domain warping is Inigo Quilez's construction: evaluate fbm, use the
# result as an offset into another fbm, twice. Two warps is where it starts
# looking like smoke and stops looking like clouds. Five octaves is enough
# at this scale; a sixth costs the same and shows up as grain.
#
# It is one full-screen shader pass, which on the GPU is about a tenth of a
# millisecond and on the CPU rasteriser would be several hundred. This is
# the GPU path only, which is why boot.py keeps burst.py for the other one.
AURORA_SRC = """
uniform float2 uSize;
uniform float2 uOrigin;
uniform float  uTime;
uniform float  uRadius;
uniform float  uGain;

float hash(float2 p){ return fract(sin(dot(p, float2(127.1, 311.7))) * 43758.5453); }
float noise(float2 p){
    float2 i = floor(p), f = fract(p);
    float2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + float2(1,0)), u.x),
               mix(hash(i + float2(0,1)), hash(i + float2(1,1)), u.x), u.y);
}
float fbm(float2 p){
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 5; i++){ v += a * noise(p); p *= 2.03; a *= 0.5; }
    return v;
}
half4 main(float2 xy){
    float d = distance(xy, uOrigin) / max(uRadius, 1.0);
    float mask = 1.0 - smoothstep(0.05, 1.0, d);
    if (mask <= 0.002) { return half4(0.0); }

    float2 uv = xy / uSize.y;                 // square aspect, so the
    float2 p  = uv * 0.82;                    // noise is not stretched
    float2 q = float2(fbm(p + uTime * 0.055),
                      fbm(p + float2(4.7, 2.3) + uTime * 0.071));
    float2 r = float2(fbm(p + 1.35 * q + float2(1.7, 9.2) + uTime * 0.048),
                      fbm(p + 1.35 * q + float2(8.3, 2.8) - uTime * 0.061));
    float f = fbm(p + 1.35 * r);

    // warm heart, cool body, one violet note. Never a full spectrum:
    // a rainbow reads as a toy, three hues read as light.
    half3 warm   = half3(1.00, 0.86, 0.62);
    half3 cool   = half3(0.30, 0.58, 1.00);
    half3 violet = half3(0.62, 0.46, 1.00);
    half3 col = mix(cool, violet, half(clamp(r.x * 1.5, 0.0, 1.0)));
    col = mix(col, warm, half(clamp((1.0 - d) * 1.25, 0.0, 1.0)));

    float body = smoothstep(0.30, 0.86, f);
    float a = body * mask * uGain;
    return half4(col * half(a), half(a));
}
"""

_aurora_effect = None


def _aurora_shader():
    """Compile once. A RuntimeEffect is immutable and shareable; only the
    uniforms change per frame."""
    global _aurora_effect
    if _aurora_effect is None:
        import skia
        _aurora_effect = skia.RuntimeEffect.MakeForShader(AURORA_SRC)
        if _aurora_effect is None:
            raise RuntimeError("the aurora shader would not compile")
    return _aurora_effect


class Reveal:
    """One release. Build it, then draw(canvas, t) until it returns False."""

    def __init__(self, width: int, height: int, origin, seed=None,
                 landing=None) -> None:
        self.w, self.h = float(width), float(height)
        self.ox, self.oy = float(origin[0]), float(origin[1])
        rng = random.Random(seed)
        self.rng = rng
        # where the status dot sits, in this layer's coordinates. boot.py
        # works it out from `[dot] corner` and the work area through
        # skin/dot.place (boot._landing) and hands it in; built bare, the
        # dot's default corner is assumed - bottom-right, a little in
        # from the edge, the taskbar not accounted for.
        self.landing = (tuple(float(v) for v in landing) if landing
                        else (self.w - 27.0, self.h - 23.0))

        # how far the front must go to leave the screen entirely
        corners = ((0, 0), (self.w, 0), (0, self.h), (self.w, self.h))
        self.reach = max(math.hypot(self.ox - cx, self.oy - cy)
                         for cx, cy in corners) * 1.04
        self.scale = self.h / 1440.0

        # rays fan AWAY from the corner the light came from, not all round:
        # light spilling out of something has a direction
        away = math.atan2(self.h * 0.5 - self.oy, self.w * 0.5 - self.ox)
        self.rays = [(away + rng.uniform(-1.15, 1.15),
                      0.45 + 0.55 * rng.random() ** 1.6,
                      rng.random(), rng.uniform(0, 120))
                     for _ in range(N_RAYS)]
        self.motes = [(away + rng.uniform(-1.5, 1.5),
                       0.20 + 0.80 * rng.random(),
                       rng.random(), rng.uniform(0, 520))
                      for _ in range(N_MOTES)]

    # ---------------------------------------------------------- the sky
    def _sky(self, canvas, skia, t):
        """The dip and the flash, composited by hand and written once.

        Two full-screen layers over a surface that was just cleared, so
        SrcOver is algebraically Src and one kSrc write does both. On the
        GPU this is 0.07 ms either way; the arithmetic is kept because it
        is also what makes the CPU fallback possible, and because the two
        paths should differ in what they can afford, not in what they mean.
        """
        dip = ease.smoothstep(ease.seg(t, *T_DIP)) \
            * (1 - ease.seg(t, 0, 420))
        flash = 0.0
        k = ease.seg(t, *T_FLASH)
        if 0 < k < 1:
            flash = FLASH_PEAK * (1 - k) ** 2.2
        if dip < 0.004 and flash < 0.004:
            return
        da = dip * DIP_PEAK
        out_a = da + flash - da * flash
        if out_a <= 0.002:
            return
        mix = [(DIM[i] * da * (1 - flash) + HOT[i] * flash) / out_a
               for i in range(3)]
        canvas.drawRect(skia.Rect.MakeWH(self.w, self.h), skia.Paint(
            BlendMode=skia.BlendMode.kSrc,
            Color=argb(255 * out_a, [min(255, c) for c in mix])))

    # ------------------------------------------------------- the front
    def _front(self, canvas, skia, t, span, lead):
        """The wavefront. Thick, soft, and slow enough to watch.

        A shell of conserved light still thins as it grows - that part of
        the physics survives from the old design - but where the old one
        was a 50 px hard-edged hoop this is a 200 px band with a real
        Gaussian blur on it, which is the difference between a diagram of
        a shockwave and light arriving.
        """
        k = ease.seg(t, *span)
        # THE CUT. Before its span opens, the front is drawn FROZEN at its
        # starting radius rather than not drawn at all. That is what makes
        # the hitstop show the aftermath: the impact frame gives way to a
        # composition that is already formed - the arc already out at
        # FRONT_R0, the bloom already lit - held dead still for 110 ms, and
        # only then does anything move. Starting the expansion from a point
        # spends the first tenth of the payoff on shapes too small to read.
        if t < 0 or k >= 1:
            return
        if lead:
            r = self.reach * (FRONT_R0 + (1 - FRONT_R0)
                              * ease.out_quart(k))
            wide = (215 * self.scale) * (1 - k * 0.72)
            alpha = 205 * (1 - k) ** 1.4
            blur = 34 * self.scale + 46 * self.scale * k
            inner, outer, edge = COOL, MID, CORE
        else:
            r = self.reach * 0.80 * (FRONT_R0 * 0.7 + (1 - FRONT_R0 * 0.7)
                                     * ease.out_cubic(k))
            wide = (330 * self.scale) * (1 - k * 0.6)
            alpha = 108 * (1 - k) ** 1.3
            blur = 60 * self.scale + 70 * self.scale * k
            inner, outer, edge = DEEP, COOL, MID
        if alpha < 1.2 or r < 4:
            return
        top = r + wide * 0.5
        canvas.drawCircle(self.ox, self.oy, r, skia.Paint(
            AntiAlias=True, Dither=True,
            Style=skia.Paint.kStroke_Style, StrokeWidth=wide,
            BlendMode=skia.BlendMode.kPlus,
            MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle,
                                                max(1.0, blur)),
            Shader=skia.GradientShader.MakeRadial(
                center=(self.ox, self.oy), radius=max(2.0, top),
                colors=[argb(0, DEEP),
                        argb(alpha * 0.30, inner),
                        argb(alpha * 0.85, outer),
                        argb(alpha, edge),
                        argb(0, DEEP)],
                positions=[0.0,
                           max(0.02, (r - wide * 0.5) / top),
                           max(0.05, (r - wide * 0.16) / top),
                           min(0.985, (r + wide * 0.12) / top),
                           1.0])))

    # -------------------------------------------------------- the bloom
    def _bloom(self, canvas, skia, t):
        """The light in the room.

        The single thing the CPU path could never have. It is a screen-
        filling soft gradient that swells behind the front and recedes -
        the part that makes the moment feel like illumination rather than
        like a graphic, and the reason the whole 2.4 s does not feel empty
        once the front has passed.
        """
        k = ease.seg(t, *T_BLOOM)
        if k <= 0 or k >= 1:
            return
        swell = math.sin(math.pi * min(1.0, k ** 0.34)) ** 1.05
        if swell < 0.008:
            return
        r = self.reach * (0.46 + 0.72 * ease.out_quart(k))
        canvas.drawCircle(self.ox, self.oy, r, skia.Paint(
            Dither=True, BlendMode=skia.BlendMode.kPlus,
            MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle,
                                                90 * self.scale),
            Shader=skia.GradientShader.MakeRadial(
                center=(self.ox, self.oy), radius=max(4.0, r),
                colors=[argb(168 * swell, WARM), argb(116 * swell, MID),
                        argb(56 * swell, COOL), argb(0, DEEP)],
                positions=[0.0, 0.28, 0.60, 1.0])))

    # --------------------------------------------------------- the rays
    def _rays(self, canvas, skia, t):
        """Light through a gap. Wide, soft, blurred wedges leaving the
        origin - nothing like the hard little spikes of the old burst,
        which read as a sun icon the moment the flash was over."""
        for angle, long, jitter, stagger in self.rays:
            k = ease.seg(t, T_RAYS[0] + stagger, T_RAYS[1] + stagger)
            if k <= 0 or k >= 1:
                continue
            reach = self.reach * (0.42 + 0.55 * long) * ease.out_quart(k)
            spread = (0.055 + 0.075 * jitter) * (1 + 0.8 * k)
            alpha = 80 * (1 - k) ** 1.7 * (0.5 + 0.5 * jitter)
            if alpha < 1.5 or reach < 10:
                continue
            path = skia.Path()
            path.moveTo(self.ox, self.oy)
            for step in range(9):
                a = angle - spread + (2 * spread) * step / 8.0
                path.lineTo(self.ox + math.cos(a) * reach,
                            self.oy + math.sin(a) * reach)
            path.close()
            canvas.drawPath(path, skia.Paint(
                AntiAlias=True, BlendMode=skia.BlendMode.kPlus,
                MaskFilter=skia.MaskFilter.MakeBlur(
                    skia.kNormal_BlurStyle, 40 * self.scale),
                Shader=skia.GradientShader.MakeRadial(
                    center=(self.ox, self.oy), radius=max(4.0, reach),
                    colors=[argb(alpha, HOT), argb(alpha * 0.45, MID),
                            argb(0, COOL)],
                    positions=[0.0, 0.45, 1.0])))

    # -------------------------------------------------------- the motes
    def _motes(self, canvas, skia, t):
        """Slow drifting points of light. Not sparks.

        The old burst threw 64 hard streaks with drag and gravity, which
        is the vocabulary of an impact. This is the vocabulary of dust in
        a sunbeam: few, soft, slow, and they outlive everything else so
        the screen empties gradually instead of switching off.
        """
        for angle, speed, jitter, stagger in self.motes:
            start = T_MOTES[0] + stagger
            k = ease.seg(t, start, T_MOTES[1])
            if k <= 0 or k >= 1:
                continue
            travel = self.reach * 0.55 * speed * ease.out_cubic(k)
            drift = math.sin((t + stagger * 7) / 620.0 + jitter * 6.28)
            x = self.ox + math.cos(angle) * travel + drift * 26 * self.scale
            y = self.oy + math.sin(angle) * travel - drift * 14 * self.scale
            # in the last beat they are recollected, so nothing is left
            # scattered when the light arrives at the dot
            home = ease.out_cubic(ease.seg(t, T_LAND[0] + 120,
                                           T_LAND[1] - 120))
            if home > 0:
                x += (self.landing[0] - x) * home
                y += (self.landing[1] - y) * home
            rad = (2.6 + 5.0 * jitter) * self.scale * (1 - 0.45 * k)
            alpha = 130 * math.sin(math.pi * k) ** 0.85 * (0.4 + 0.6 * jitter)
            if alpha < 2 or rad < 0.4:
                continue
            canvas.drawCircle(x, y, rad * 3.0, skia.Paint(
                BlendMode=skia.BlendMode.kPlus,
                MaskFilter=skia.MaskFilter.MakeBlur(
                    skia.kNormal_BlurStyle, rad * 1.6),
                Color=argb(alpha, HOT if jitter > 0.6 else MID)))

    def _aurora(self, canvas, skia, t):
        """The colour. Flowing noise, masked to a disc around the origin.

        Drawn UNDER the fronts and over the bloom, so the fronts read as
        edges of the same body of light rather than as separate rings
        travelling through it.
        """
        k = ease.seg(t, *T_AURORA)
        if k <= 0 or k >= 1:
            return
        gain = math.sin(math.pi * min(1.0, k ** 0.30)) ** 1.0
        if gain < 0.01:
            return
        try:
            effect = _aurora_shader()
        except Exception:
            return
        radius = self.reach * (0.50 + 0.70 * ease.out_quart(k))
        # skia.Data does not copy, so the packed bytes must be kept alive
        # until makeShader has read them. Binding it to a local is enough,
        # and passing struct.pack(...) inline is not.
        payload = struct.pack(
            "ffffff", float(self.w), float(self.h),
            float(self.ox), float(self.oy),
            float(t / 1000.0), float(radius))
        data = skia.Data.MakeWithCopy(payload + struct.pack("f", 0.46 * gain))
        shader = effect.makeShader(data)
        canvas.drawRect(skia.Rect.MakeWH(self.w, self.h), skia.Paint(
            Shader=shader, BlendMode=skia.BlendMode.kPlus, Dither=True))

    # --------------------------------------------------------- the seed
    def _heart(self, canvas, skia, t):
        """What is left where the card was: a small warm glow that is the
        last thing to go. The reveal ENDS somewhere rather than merely
        stopping, and it ends at the app."""
        k = ease.seg(t, 0, T_END)
        if k <= 0 or k >= 1:
            return
        fade = (1 - ease.smoothstep(ease.seg(t, *T_SETTLE)))
        pulse = 1.0 - 0.85 * ease.out_quart(ease.seg(t, 0, 900))
        a = fade * (0.16 + 0.62 * pulse)
        if a < 0.01:
            return
        r = (130 + 420 * ease.out_quart(ease.seg(t, 0, 620))) * self.scale
        canvas.drawCircle(self.ox, self.oy, r, skia.Paint(
            Dither=True, BlendMode=skia.BlendMode.kPlus,
            MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle,
                                                60 * self.scale),
            Shader=skia.GradientShader.MakeRadial(
                center=(self.ox, self.oy), radius=max(4.0, r),
                colors=[argb(150 * a, CORE), argb(112 * a, HOT),
                        argb(46 * a, MID), argb(0, DEEP)],
                positions=[0.0, 0.16, 0.48, 1.0])))

    def _landing(self, canvas, skia, t):
        """Where the light goes when it is done: into the status dot.

        The reveal used to end by fading out, and a uniform fade to zero
        has no event structure at all - it reads as "it vanished", which is
        the difference between an ending and a stop. So the last beat
        CONVERGES rather than disperses: a thread of light gathers to the
        corner where the little always-on dot lives (`self.landing` -
        bottom-right since 2026-09-07, wherever `[dot] corner` says), and
        finishes with one small pulse there.

        That is not decoration. The dot is the app's resting state - the
        one thing that stays on screen for the rest of the session - so the
        reveal does not end so much as arrive at it. The corner card is
        gone, the wave has passed, and what is left is the thing that will
        still be there in six hours.
        """
        k = ease.seg(t, *T_LAND)
        if k <= 0:
            return
        ex, ey = self.landing
        # the gather: a soft mass pulled in from the room toward the dot
        pull = ease.out_cubic(k)
        r = max(8.0, (self.reach * 0.40) * (1.0 - 0.965 * pull))
        a = math.sin(math.pi * min(1.0, k * 1.02)) ** 0.9
        if a > 0.008:
            canvas.drawCircle(ex, ey, r, skia.Paint(
                Dither=True, BlendMode=skia.BlendMode.kPlus,
                MaskFilter=skia.MaskFilter.MakeBlur(
                    skia.kNormal_BlurStyle, max(2.0, 40 * self.scale)),
                Shader=skia.GradientShader.MakeRadial(
                    center=(ex, ey), radius=max(4.0, r),
                    colors=[argb(205 * a, HOT), argb(120 * a, MID),
                            argb(0, DEEP)],
                    positions=[0.0, 0.42, 1.0])))
        # and the arrival: one small bright pulse, right at the end
        hit = ease.seg(t, T_LAND[1] - 320, T_LAND[1])
        if hit > 0:
            glow = math.sin(math.pi * hit) ** 0.7
            rad = (22 + 96 * ease.out_quart(hit)) * self.scale
            canvas.drawCircle(ex, ey, rad, skia.Paint(
                BlendMode=skia.BlendMode.kPlus,
                MaskFilter=skia.MaskFilter.MakeBlur(
                    skia.kNormal_BlurStyle, max(2.0, 14 * self.scale)),
                Shader=skia.GradientShader.MakeRadial(
                    center=(ex, ey), radius=max(2.0, rad),
                    colors=[argb(255 * glow, CORE), argb(190 * glow, HOT),
                            argb(40 * glow, MID), argb(0, COOL)],
                    positions=[0.0, 0.22, 0.55, 1.0])))
            # one thin ring leaving the dot, so the arrival has an
            # edge and does not read as a smudge
            ring = 34 * self.scale + 150 * self.scale * ease.out_quart(hit)
            canvas.drawCircle(ex, ey, ring, skia.Paint(
                AntiAlias=True, Style=skia.Paint.kStroke_Style,
                StrokeWidth=max(1.0, 7.0 * self.scale * (1 - hit)),
                BlendMode=skia.BlendMode.kPlus,
                MaskFilter=skia.MaskFilter.MakeBlur(
                    skia.kNormal_BlurStyle, max(1.0, 9 * self.scale)),
                Color=argb(190 * (1 - hit) ** 1.4, HOT)))

    # ---------------------------------------------------------- compose
    def draw(self, canvas, t: float) -> bool:
        import skia

        canvas.clear(0x00000000)
        if t > T_END:
            return False
        # everything after the settle is scaled down together, so the
        # ending is one gesture rather than six things stopping
        canvas.save()
        self._sky(canvas, skia, t)
        self._bloom(canvas, skia, t)
        self._aurora(canvas, skia, t)
        self._rays(canvas, skia, t)
        self._front(canvas, skia, t, T_TRAIL, lead=False)
        self._front(canvas, skia, t, T_FRONT, lead=True)
        self._motes(canvas, skia, t)
        self._heart(canvas, skia, t)
        self._landing(canvas, skia, t)
        canvas.restore()
        return True


__all__ = ["Reveal", "T_END", "T_DIP"]
