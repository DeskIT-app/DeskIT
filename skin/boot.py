"""The corner card, and the string it is drawing back.

WHAT IT IS. A dictation app boots by pulling two Whisper models onto the
GPU, which takes 14 s warm and about 25 s cold, and under pythonw there is
no window, no taskbar entry and no console to say so. The old splash was a
box with an indeterminate bar sliding through it forever. This is the same
information with a different claim: that the wait is a wind-up.

THE STRING. One horizontal line across the card, pulled down at its middle
by a bright node, deeper as the load progresses. That is a bowstring, which
is where the idea came from — but it is also, exactly, a plucked string,
which is what sound is, which is what this app is for. It is the rare case
where the metaphor for "loading" and the metaphor for the product are the
same drawing. At "ready" it lets go, and what it fires is the release.

WHY THE PROGRESS IS REAL. It is read out of the log lines the app already
writes, matched against the milestones a boot actually passes through, so
the node's depth is tied to work that genuinely happened. Between two
milestones it creeps asymptotically toward the next one and never reaches
it: a bar that sits still is the thing people read as "hung", and a bar
that lies about being finished is worse. It cannot run backwards and it
cannot arrive early.

WHY IT IS CALM. The card is on screen for twenty seconds while its owner
is typing somewhere else. Everything that moves here moves slowly and
quietly — a 0.09 Hz breath on the string, a node that eases rather than
steps. The whole animation budget of this app is spent in one second at
the end, on purpose. Restraint here is what buys the right to be loud
there.
"""
from __future__ import annotations

import logging
import math
import os
import queue
import time

from . import clock as clock_mod
from . import ease
from .burst import Burst, T_DIP, T_END, T_FLASH
from .glass import Glass, primary_screen, wants_motion, work_area
from .palette import (ACCENT_TEXT, BG, CARD, FAINT, FG, LIGHT_ACCENT,
                      LIGHT_CORE, LIGHT_HOT, LIGHT_MID, LINE, argb, rgb)

_log = logging.getLogger("app")

# ------------------------------------------------------------- geometry
PAD = 34                  # room around the card for its shadow and glow
CARD_W, CARD_H = 396, 132
WIN_W, WIN_H = CARD_W + PAD * 2, CARD_H + PAD * 2
RADIUS = 18
MARGIN_X, MARGIN_Y = 24, 24

WAVE_INSET = 28           # card edge to where the waveform starts
WAVE_Y = 96               # the waveform's horizon inside the card
WAVE_H = 26               # its half-height at full charge
GATHER_MS = 1330.0        # the whole wind-up, and 53% of the moment.
#                           Three beats inside it, below. This is long on
#                           purpose: a gaze takes ~300 ms just to ARRIVE
#                           at a card 24 degrees off centre, so a wind-up
#                           shorter than that is one nobody sees start.
SUMMONS_MS = 280.0        # a new object appears - abrupt onset is what
#                           captures a gaze; a brightening is not
CHARGE_MS = 1150.0        # contraction, accelerating. Ends here.
#                           GATHER_MS - CHARGE_MS = 180 ms of absolute
#                           stillness before the hit: the slot machine's
#                           pre-final-reel hold, the trailer's silence.

# The waveform's colours, left to right. Cool into warm into cool, because
# one hue reads as a progress bar and a rainbow reads as a toy. These are
# the light ramp's own stops, so the card and the reveal share a source —
# and under LAMPLIGHT the warm middle is the lamp itself rather than a
# generic highlight, which is what makes the wave read as this app's light.
VOICE_A = LIGHT_ACCENT           # COOL — the edge of the light
VOICE_B = LIGHT_MID              # ACCENT_TEXT — the lamp
VOICE_C = LIGHT_HOT              # incandescent, the core
VOICE_D = LIGHT_ACCENT           # and back out to the edge

# The boot, as the app itself narrates it: (marker, progress, what to SAY).
# The markers are matched against the real log lines — taken from actual
# boots in app.log, not guessed — and the progress is what the string is
# drawn back to when one arrives.
#
# THE THIRD COLUMN EXISTS BECAUSE THE LOG IS NOT A USER INTERFACE. What the
# app writes is "local model ivrit-ai/whisper-large-v3-turbo-ct2 ready on
# cuda (float16)", which is the right line to keep in app.log and the wrong
# one to put on a card someone reads while waiting. The card says what is
# happening; the log still says exactly what happened.
#
# A line that matches nothing leaves the previous phrase up rather than
# printing itself, so no model id, no file path and no URL with a token in
# it can ever reach the card.
MILESTONES = (
    ("starting", 0.04, "Starting up"),
    ("loading the transcription model", 0.10, "Loading the speech model"),
    ("ready on cuda", 0.44, "Hebrew speech model ready"),
    ("loading english model", 0.50, "Loading the English speech model"),
    ("vision projector warm", 0.62, "Vision model ready"),
    ("phone endpoint on", 0.78, "Opening the phone connection"),
    ("repair backend is warm", 0.86, "Warming up the text repair model"),
    ("open this on the phone", 0.92, "Phone link ready"),
    ("ready —", 1.00, "Ready — hold Right Ctrl and speak"),
    ("ready -", 1.00, "Ready — hold Right Ctrl and speak"),
)

CREEP_TO = 0.72           # how far toward the NEXT milestone idling drifts
CREEP_TAU = 5200.0        # ms; the drift's own time constant


_WGHT = (ord("w") << 24) | (ord("g") << 16) | (ord("h") << 8) | ord("t")


def _rubik(weight: int, size: float):
    """Rubik at a REAL weight, out of the one file that can give one.

    fonts\\ holds four files — Rubik.ttf, RubikMedium.ttf, RubikSemiBold.ttf,
    RubikBold.ttf — and they are the SAME VARIABLE FONT with rewritten name
    tables. Measured: all four report fontStyle().weight() == 300 and return
    byte-identical advance widths, so asking Skia for "RubikMedium.ttf" and
    expecting Medium silently gets Light. The first version of this card was
    set entirely in Rubik Light and looked it.

    A variable font has to be pinned to a coordinate on its wght axis, which
    is what makeClone does here. Verified across the axis: 300 -> 400 -> 500
    -> 700 measures 79.30 -> 80.98 -> 82.96 -> 84.96 px for the same string,
    so the weight is genuinely changing rather than being asked for politely.
    """
    import skia
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "fonts", "Rubik.ttf")
    face = None
    if os.path.exists(path):
        face = skia.Typeface.MakeFromFile(path)
        if face is not None and weight != 300:
            try:
                variation = skia.FontArguments.VariationPosition
                coords = variation.Coordinates(
                    [variation.Coordinate(_WGHT, float(weight))])
                args = skia.FontArguments()
                args.setVariationDesignPosition(variation(coords))
                face = face.makeClone(args) or face
            except Exception:
                _log.debug("skin: no variable axis on Rubik", exc_info=True)
    if face is None:                       # no Rubik: Segoe UI has Hebrew
        face = skia.Typeface.MakeFromName(
            "Segoe UI", skia.FontStyle(weight, 5, skia.FontStyle.kUpright_Slant))
    font = skia.Font(face, size)
    font.setEdging(skia.Font.kAntiAlias)
    font.setSubpixel(True)
    return font


class Card:
    """The picture. Stateless about threads: the caller drives draw()."""

    def __init__(self) -> None:
        import skia
        self._skia = skia
        self.line = "starting…"
        self._floor = 0.0             # the last milestone actually reached
        self._next = 0.10             # the one after it, which creep aims at
        self._since = time.monotonic()
        self.charge = 0.0             # what is drawn, which eases toward it
        self.alpha = 0.0
        self.released_at = None
        self._seed = int(time.time() * 1000) & 0xFFFF

        # 600 for the tracked micro-label, 400 for the sentence. A weight
        # contrast of one step reads as mush; two steps reads as decided.
        self.f_label = _rubik(600, 10.0)
        self.f_status = _rubik(400, 13.5)
        self._plate = None       # the static half of the card, baked once

    # -------------------------------------------------------------- state
    def placement(self) -> tuple[int, int, int, int]:
        """Bottom-right of the work area — out of the way of whatever the
        owner is actually looking at, and above the taskbar rather than
        under it."""
        wx, wy, ww, wh = work_area()
        return (wx + ww - WIN_W - MARGIN_X + PAD // 2,
                wy + wh - WIN_H - MARGIN_Y + PAD // 2, WIN_W, WIN_H)

    def status(self, text: str) -> None:
        """Take a log line and show what it MEANS.

        Unrecognised lines move nothing and say nothing: the previous
        phrase stays up. That is deliberate — the alternative is echoing
        raw log text, and the raw log is full of model ids, cuda dtypes and
        a phone URL with an auth token in it.
        """
        low = " ".join(str(text).split()).lower()
        if not low:
            return
        for marker, value, phrase in MILESTONES:
            if marker in low:
                self.line = phrase
                if value > self._floor:
                    self._floor = value
                    self._since = time.monotonic()
                    nxt = [v for _m, v, _p in MILESTONES if v > value]
                    self._next = min(nxt) if nxt else 1.0
                return

    def advance(self, value: float) -> None:
        """Force the floor — the preview uses this; the app uses status()."""
        self._floor = max(self._floor, ease.clamp01(value))

    def target(self) -> float:
        """The floor, plus a drift toward the next milestone that never
        arrives. A progress indicator that sits perfectly still for six
        seconds is read as a hang, and one that reaches 100% before the
        work is done is read as a lie."""
        if self._floor >= 1.0:
            return 1.0
        idle = (time.monotonic() - self._since) * 1000.0
        span = (self._next - self._floor) * CREEP_TO
        return self._floor + span * (1 - math.exp(-idle / CREEP_TAU))

    def release(self) -> None:
        if self.released_at is None:
            self.released_at = time.monotonic()

    def released_ms(self) -> float:
        if self.released_at is None:
            return -1e9
        return (time.monotonic() - self.released_at) * 1000.0

    # --------------------------------------------------------------- text
    def _clamp(self, font, text, width):
        if font.measureText(text) <= width:
            return text
        ell = "…"
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.measureText(text[:mid] + ell) <= width:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + ell

    # --------------------------------------------------------------- draw
    def draw(self, canvas, clock_ms: float) -> bool:
        """Paint the card. False once the exit animation is finished."""
        skia = self._skia
        canvas.clear(0x00000000)

        rel = self.released_ms()
        # The card does not leave when it is released - it spends GATHER_MS
        # visibly collecting the waveform into its centre first, and only
        # then goes. That wind-up is the whole reason the release is
        # watchable: something happens, you see it happen, and then the
        # light leaves. The previous version cut the card at 260 ms and the
        # payoff arrived with no visible cause.
        # the card is gone the instant the light leaves, with no fade:
        # the reveal's first frame is already the aftermath
        gone = 1.0 if rel >= GATHER_MS else 0.0
        if rel >= GATHER_MS:
            return False
        appear = ease.out_cubic(ease.seg(clock_ms, 60, 420))
        self.alpha = appear * (1 - gone)
        if self.alpha <= 0.002:
            return rel < GATHER_MS

        # charge eases toward its target, so a milestone lands as a move
        # rather than a jump
        self.charge = ease.approach(self.charge, self.target(), 0.06)

        canvas.save()
        # a small rise on entry, and a recoil on release: the card is the
        # thing that let go, so it has to feel the letting go
        lift = (1 - appear) * 16
        squeeze = 1.0
        canvas.translate(WIN_W / 2, WIN_H / 2 + lift)
        canvas.scale(squeeze, squeeze)
        canvas.translate(-WIN_W / 2, -WIN_H / 2)

        x0, y0 = PAD, PAD
        rect = skia.Rect.MakeXYWH(x0, y0, CARD_W, CARD_H)
        rrect = skia.RRect.MakeRectXY(rect, RADIUS, RADIUS)

        plate = skia.Paint()
        plate.setAlpha(max(0, min(255, int(self.alpha * 255))))
        canvas.drawImage(self._plate_image(), 0, 0, skia.SamplingOptions(),
                         plate)
        self._text(canvas, skia, x0, y0, gone)
        self._voice(canvas, skia, x0, y0, clock_ms, rel)
        canvas.restore()
        return True

    def _plate_image(self):
        """The card's shadow, face, border and specular — baked once.

        NONE OF IT EVER CHANGES. The shape is fixed, the colours are fixed,
        and the only thing that varies across the card's whole life is its
        overall opacity, which a paint alpha applies to a finished image for
        free. Baking it turns a 28.98 ms frame into a 3.5 ms one.

        That is not a micro-optimisation. This card is on screen for
        fourteen to twenty-five seconds, and it is on screen precisely while
        two Whisper models are being pulled onto the GPU — the one stretch
        of this app's life when CPU is worth something. Measured before the
        bake: the six-layer shadow alone was 24.49 ms of a 28.98 ms frame,
        85% of it, redrawn ninety times a second to produce an identical
        picture every time.

        Six offset round-rects with geometrically decaying alpha rather than
        a MaskFilter blur: a blur is a separate rasterise-and-convolve, and
        stacked hard shapes are indistinguishable from one at this radius.
        """
        if self._plate is not None:
            return self._plate
        skia = self._skia
        surface = skia.Surface.MakeRasterN32Premul(WIN_W, WIN_H)
        canvas = surface.getCanvas()
        canvas.clear(0x00000000)
        x0, y0 = PAD, PAD
        rect = skia.Rect.MakeXYWH(x0, y0, CARD_W, CARD_H)
        rrect = skia.RRect.MakeRectXY(rect, RADIUS, RADIUS)
        for i in range(6, 0, -1):
            grow = i * 3.4
            a = 15 * (0.62 ** (6 - i))
            canvas.drawRRect(
                skia.RRect.MakeRectXY(
                    skia.Rect.MakeXYWH(rect.left() - grow,
                                       rect.top() - grow * 0.35 + 5,
                                       rect.width() + grow * 2,
                                       rect.height() + grow * 1.5),
                    RADIUS + grow, RADIUS + grow),
                skia.Paint(AntiAlias=True, Color=argb(a, (0, 0, 0))))
        # the face: a hair lighter at the top, the way a surface lit from
        # above actually is. A flat fill is what makes a dark UI read as
        # printed rather than lit.
        canvas.drawRRect(rrect, skia.Paint(
            AntiAlias=True, Dither=True,
            Shader=skia.GradientShader.MakeLinear(
                points=[(x0, y0), (x0, y0 + CARD_H)],
                colors=[argb(252, CARD), argb(252, BG)],
                positions=[0.0, 1.0])))
        canvas.drawRRect(rrect, skia.Paint(
            AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1.0,
            Color=argb(190, LINE)))
        # a specular hairline on the top edge only, 60% of the width and
        # fading at both ends — the cheapest thing that says "glass"
        canvas.drawLine(
            x0 + CARD_W * 0.20, y0 + 0.5, x0 + CARD_W * 0.80, y0 + 0.5,
            skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style,
                       StrokeWidth=1.0,
                       Shader=skia.GradientShader.MakeLinear(
                           points=[(x0 + CARD_W * 0.20, y0),
                                   (x0 + CARD_W * 0.80, y0)],
                           colors=[argb(0, FG), argb(46, FG), argb(0, FG)],
                           positions=[0.0, 0.5, 1.0])))
        self._plate = surface.makeImageSnapshot()
        return self._plate

    def _text(self, canvas, skia, x0, y0, gone):
        fade = self.alpha * (1 - ease.out_quad(ease.seg(gone, 0.0, 0.5)))
        label = skia.Paint(AntiAlias=True, Color=argb(255 * fade, FAINT))
        # tracked capitals, drawn a glyph at a time because Skia has no
        # letter-spacing. Wide tracking on a 10 px label is what makes a
        # micro-heading read as typography instead of as small text.
        x = x0 + WAVE_INSET
        for ch in "DESKIT":
            canvas.drawString(ch, x, y0 + 34, self.f_label, label)
            x += self.f_label.measureText(ch) + 1.5

        # the state word, right-aligned against the label
        # The chip reports the STATE, not the animation. `charge` is the
        # eased value the waveform is drawn from and it takes about a
        # second to crawl the last of the way to 1.0, so reading it here
        # left the card saying "Ready - hold Right Ctrl and speak" under a
        # chip that still said LOADING. `_floor` is the milestone that
        # actually arrived.
        ready = self._floor >= 0.999
        word = "READY" if ready else "LOADING"
        tint = ACCENT_TEXT if ready else FAINT
        width = self.f_label.measureText(word) + 1.5 * len(word)
        x = x0 + CARD_W - WAVE_INSET - width
        paint = skia.Paint(AntiAlias=True, Color=argb(255 * fade, tint))
        for ch in word:
            canvas.drawString(ch, x, y0 + 34, self.f_label, paint)
            x += self.f_label.measureText(ch) + 1.5

        line = self._clamp(self.f_status, self.line,
                           CARD_W - WAVE_INSET * 2)
        canvas.drawString(line, x0 + WAVE_INSET, y0 + 66, self.f_status,
                          skia.Paint(AntiAlias=True,
                                     Color=argb(255 * fade, FG)))

    # ------------------------------------------------------------ the voice
    def _envelope(self, u, clock_ms, charge, gather):
        """The waveform's half-height at position u in 0..1.

        Four sine partials at incommensurate frequencies, so the shape
        never visibly repeats: three harmonics of one fundamental would
        cycle back to the same picture every couple of seconds and the eye
        catches that immediately.

        `charge` is how loaded the app is, and it is the AMPLITUDE - the
        waveform grows from a near-flat line into a full voice as the
        models arrive. `gather` is the release: it pulls the whole envelope
        into the centre, which is what makes the energy look collected
        before it is thrown.
        """
        t = clock_ms / 1000.0
        if gather > 0:
            pull = 1.0 - 0.86 * gather
            u = 0.5 + (u - 0.5) / max(0.14, pull)
            if u < 0.0 or u > 1.0:
                return 0.0
            # The ribbon SHRINKS as it contracts. The first version grew
            # it by 3.4x on the way in, which made a tall diamond that
            # burst out of the card - and which said the wrong thing
            # anyway. The energy is going INTO the core, so the waveform
            # has to lose what the core gains.
            window = math.sin(math.pi * u) ** 0.62 * (1.0 - 0.72 * gather)
        else:
            window = math.sin(math.pi * ease.clamp01(u)) ** 0.62
        # SIX partials at five to thirty-one cycles across the card. The
        # first version used four at under four cycles each and the result
        # was one smooth lens - it read as a lozenge of light, not as a
        # voice. A waveform is recognised by its RATE of variation, so the
        # frequencies matter more than the amplitudes do.
        c = math.tau * u
        wave = (0.40 * math.sin(c * 5.0 + t * 0.91)
                + 0.26 * math.sin(c * 8.3 - t * 1.33)
                + 0.18 * math.sin(c * 13.1 + t * 1.87)
                + 0.11 * math.sin(c * 19.7 - t * 2.41)
                + 0.07 * math.sin(c * 26.3 + t * 3.07)
                + 0.04 * math.sin(c * 31.9 - t * 3.71))
        # never let it collapse to nothing: a flat line reads as broken,
        # and even silence has a floor on a real meter
        body = 0.20 + 0.80 * ease.out_quad(charge)
        return window * body * (0.30 + 0.70 * abs(wave))

    def _ribbon_path(self, skia, left, right, mid_y, height, clock_ms,
                     charge, gather):
        """One closed path: out along the top envelope, back along its
        mirror. A filled ribbon rather than a stroked line, because a
        stroke has one width and a voice does not."""
        steps = 88
        top, bottom = [], []
        for i in range(steps + 1):
            u = i / steps
            x = left + (right - left) * u
            a = self._envelope(u, clock_ms, charge, gather) * height
            top.append((x, mid_y - a))
            bottom.append((x, mid_y + a))
        path = skia.Path()
        path.moveTo(*top[0])
        for pt in top[1:]:
            path.lineTo(*pt)
        for pt in reversed(bottom):
            path.lineTo(*pt)
        path.close()
        return path

    def _voice(self, canvas, skia, x0, y0, clock_ms, rel):
        """The waveform: what this app is, drawn as light.

        THIS REPLACED A SINGLE THIN LINE PULLED DOWN IN THE MIDDLE, which
        was meant to read as a drawn bowstring and did not read as
        anything - "some thread, I did not even understand it, it looks
        really dumb". The lesson is not that the metaphor was wrong. It is
        that a metaphor which has to be explained has already failed. A
        waveform needs no explaining: everyone has seen sound drawn this
        way, and this is an app you talk to.

        Four layers, cheapest last: a wide soft bloom, the body of the
        ribbon under a gradient along its length, a hairline rim, and the
        horizon it sits on. On the GPU the bloom is a real Gaussian blur
        and costs nothing; on the CPU fallback the whole card is 104k
        pixels, so even there it is affordable.
        """
        left = x0 + WAVE_INSET
        right = x0 + CARD_W - WAVE_INSET
        mid_y = y0 + WAVE_Y
        charge = ease.clamp01(self.charge)

        gather, heat, lift = 0.0, charge, 1.0
        if rel >= 0:
            # THE WIND-UP, in three beats.
            #   SUMMONS   a core arrives, abruptly, and the waveform dims
            #             behind it. Nothing here has to be read; the beat
            #             exists to pay for the saccade.
            #   CHARGE    the waveform contracts into that core, on an
            #             accelerating curve, because the exact opposite of
            #             an expansion is the strongest anticipation of one.
            #   BREATH    180 ms of stillness. The subject freezes; only
            #             the core micro-scales. Holds are the last thing
            #             to cut from a sequence, never the first.
            summons = ease.out_cubic(ease.seg(rel, 0, SUMMONS_MS))
            gather = ease.in_cubic(ease.seg(rel, SUMMONS_MS, CHARGE_MS))
            gather = max(gather, 0.10 * summons)
            heat = 1.0
            # the card is CUT at the impact, not faded: a hard cut is
            # unambiguously authored, a crossfade is indistinguishable from
            # a slow computer
            lift = 1.0 if rel < GATHER_MS else 0.0
        if lift <= 0.004:
            return

        height = WAVE_H * (0.5 + 0.5 * charge) * lift
        path = self._ribbon_path(skia, left, right, mid_y, height, clock_ms,
                                 charge, gather)
        glow = (0.30 + 0.62 * heat) * self.alpha * lift

        # 1. the bloom - what stops it looking like a sticker. The radius
        # grows as the app wakes up, so "more loaded" is also "more lit".
        blur = 7.0 + 13.0 * heat + 26.0 * gather
        canvas.drawPath(path, skia.Paint(
            AntiAlias=True, BlendMode=skia.BlendMode.kPlus,
            MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, blur),
            Shader=skia.GradientShader.MakeLinear(
                points=[(left, mid_y), (right, mid_y)],
                colors=[argb(96 * glow, VOICE_A), argb(132 * glow, VOICE_B),
                        argb(112 * glow, VOICE_C), argb(88 * glow, VOICE_D)],
                positions=[0.0, 0.36, 0.68, 1.0])))

        # 2. the body. The colour travelling left to right is what makes
        # it read as one moving thing rather than a row of bumps.
        canvas.drawPath(path, skia.Paint(
            AntiAlias=True, Dither=True, BlendMode=skia.BlendMode.kPlus,
            Shader=skia.GradientShader.MakeLinear(
                points=[(left, mid_y), (right, mid_y)],
                colors=[argb(150 * glow, VOICE_A), argb(196 * glow, VOICE_B),
                        argb(172 * glow, VOICE_C), argb(142 * glow, VOICE_D)],
                positions=[0.0, 0.34, 0.66, 1.0])))

        # 3. the rim: a hairline round the silhouette, which is what makes
        # a soft shape look deliberate rather than smudged
        canvas.drawPath(path, skia.Paint(
            AntiAlias=True, Style=skia.Paint.kStroke_Style,
            StrokeWidth=1.1, BlendMode=skia.BlendMode.kPlus,
            Color=argb(120 * glow, LIGHT_CORE)))

        # 5. THE CORE - the object the whole wind-up is about.
        #
        # It ARRIVES rather than brightening. An abrupt onset of a new
        # object is what actually captures a gaze; a gradual change in the
        # luminance of something already on screen does not, which is why
        # the previous version's slowly-deepening line was never noticed
        # starting. It then grows and heats through the charge while the
        # waveform collapses into it, and holds dead still for the last
        # 180 ms with only a 3% scale pulse - the beat that makes the hit
        # land.
        if rel >= 0:
            summons = ease.out_back(ease.clamp01(rel / SUMMONS_MS), 1.5)
            charge = ease.in_cubic(ease.seg(rel, SUMMONS_MS, CHARGE_MS))
            breath = ease.seg(rel, CHARGE_MS, GATHER_MS)
            # the stillness is not stillness: the subject freezes and one
            # subordinate thing keeps moving, or the frame reads as a crash
            pulse = 1.0 + 0.03 * math.sin(breath * math.pi)
            mid_x = (left + right) * 0.5
            r = (3.2 + 12.0 * charge) * summons * pulse
            hot = (0.45 + 0.55 * charge) * self.alpha
            canvas.drawCircle(mid_x, mid_y, r * 5.2, skia.Paint(
                BlendMode=skia.BlendMode.kPlus, Dither=True,
                MaskFilter=skia.MaskFilter.MakeBlur(
                    skia.kNormal_BlurStyle, 6.0 + 16.0 * charge),
                Shader=skia.GradientShader.MakeRadial(
                    center=(mid_x, mid_y), radius=max(1.0, r * 5.2),
                    colors=[argb(225 * hot, LIGHT_HOT),
                            argb(120 * hot, VOICE_B),
                            argb(0, VOICE_A)],
                    positions=[0.0, 0.38, 1.0])))
            canvas.drawCircle(mid_x, mid_y, r, skia.Paint(
                AntiAlias=True, BlendMode=skia.BlendMode.kPlus,
                Color=argb(255 * self.alpha, LIGHT_CORE)))

        # 4. the horizon, fading at both ends, so the wave has something
        # to be a wave ON
        if gather < 0.5:
            canvas.drawLine(left, mid_y, right, mid_y, skia.Paint(
                AntiAlias=True, Style=skia.Paint.kStroke_Style,
                StrokeWidth=1.0,
                Shader=skia.GradientShader.MakeLinear(
                    points=[(left, mid_y), (right, mid_y)],
                    colors=[argb(0, LINE), argb(70 * self.alpha, LINE),
                            argb(0, LINE)],
                    positions=[0.0, 0.5, 1.0])))


# ------------------------------------------------------------------ driver
FRAME_S = 1.0 / 90.0
IDLE_FRAME_S = 1.0 / 50.0
_DONE_SENTINEL = None       # filled in by run(), from overlay's own object


def run(splash) -> None:
    """The body of overlay.Splash's thread, with the picture swapped.

    Deliberately given the Splash object rather than its parts: the queue,
    the _alive gate, the _closing Event and the (_DONE, linger_ms) protocol
    are what main.py and three tests in tests.py rely on, and none of them
    change. Only what gets painted does.
    """
    import overlay

    card = Card()
    # THE CARD IS DRAWN ON THE CPU, DELIBERATELY. Building the OpenGL
    # context costs ~270 ms, and the whole job of this window is to appear
    # the instant the shortcut is clicked - measured, it pushed the splash
    # from 50 ms to 250. The card is 98k pixels with one baked plate and a
    # small blurred ribbon, which the CPU rasteriser draws in 0.9 ms, so it
    # gains nothing from a graphics card anyway.
    #
    # The GPU is acquired later, on this same thread, when the release's
    # full-screen layer is built - by which point the models have been
    # loading for the best part of a second and nobody is waiting on us.
    glass = Glass(*card.placement(), gpu=False)
    glass.show()
    splash._alive.set()          # start() is waiting on this, with a timeout

    start = time.perf_counter()
    stall_mark = start           # for the clamp below
    finish_at = None             # monotonic deadline set by finish()
    released = False
    burst = None
    burst_glass = None
    card_closed = False
    landed = False               # the cue fires once, at land_at
    land_at = 0.0                # set when the release is armed
    motion = wants_motion()

    try:
        while not splash._closing.is_set():
            # A STALLED FRAME MAY NOT SKIP THE MOMENT. Both marks below are
            # wall-clock instants that everything downstream measures from,
            # so if one frame overran, push them BOTH forward by the excess.
            # The effect is that a hiccup costs a little slow-motion rather
            # than the whole ending — see skin/clock.py, which is there
            # because a screen recorder starting to encode ate everything
            # after the flash.
            now, shift = clock_mod.absorb(stall_mark)
            stall_mark = now
            if shift:
                start += shift
                if card.released_at is not None:
                    card.released_at += shift
                if finish_at is not None:
                    finish_at += shift
            clock = (now - start) * 1000.0

            # ---- drain whatever the app has said since the last frame
            try:
                while True:
                    item = splash._q.get_nowait()
                    if isinstance(item, tuple):        # (_DONE, linger_ms)
                        finish_at = now + max(0, item[1]) / 1000.0
                    elif item is overlay._DONE:
                        finish_at = now
                    else:
                        card.status(item)
            except queue.Empty:
                pass

            # Build the release's window EARLY — during the load, when
            # there is nothing but waiting to do. Creating a 2560x1440
            # layered window and its DIB is tens of milliseconds, and paid
            # at the moment of the release it is a visible hitch at the one
            # instant that must not have one. Measured before this: the
            # burst's window did not appear until ~300 ms after the string
            # let go. A layered window that has never been flushed draws
            # nothing, so it can sit there, shown and empty, for the whole
            # boot.
            if burst_glass is None and motion and clock > 700:
                try:
                    burst_glass = Glass(*_burst_box())
                    burst_glass.show()
                    _warm(burst_glass)
                except Exception:
                    _log.debug("skin: no burst layer", exc_info=True)
                    motion = False

            if finish_at is not None and now >= finish_at and not released:
                released = True
                card.release()
                # A FAST BOOT MUST STILL GET ITS RELEASE. The layer above
                # is built once the card has been up for 700 ms, which is
                # true of every real boot (they take 14-25 s) and false of
                # a warm cache, a test, or an app that failed early. When
                # the release arrives first, build it here instead - the
                # 270 ms is worth paying late rather than losing the moment
                # altogether, and the alternative was a silent no-op.
                if motion and burst_glass is None:
                    try:
                        burst_glass = Glass(*_burst_box())
                        burst_glass.show()
                        _warm(burst_glass)
                    except Exception:
                        _log.debug("skin: no burst layer", exc_info=True)
                        motion = False
                if motion and burst_glass is not None:
                    burst = _arm_burst(card, burst_glass)
                    land_at = _land_ms(burst)

            # THE CARD IS ONLY DRAWN WHILE IT STILL HAS A WINDOW.
            #
            # This guard is the whole bug that made the release invisible in
            # the real app while working perfectly in `python -m skin.preview`.
            # The card's window is closed the moment its wind-up ends - and
            # the loop then went straight back round and called
            # card.draw(glass.canvas, ...) on the closed window, where
            # `canvas` is None. AttributeError, on the splash thread, caught
            # by the handler at the bottom of this function, logged to
            # app.log and otherwise silent.
            #
            # The timing is what made it look like a design problem rather
            # than a crash: the flash is drawn and flushed by the burst
            # block BELOW, in the same iteration the card returns False. So
            # exactly one frame of the release reached the screen, and the
            # thread died before the second. Frame-by-frame in a screen
            # recording that reads as "the flash, and then nothing" - which
            # is precisely how it was reported.
            #
            # The preview never hit it because it drives the card and the
            # release in two separate loops.
            if not card_closed:
                alive = card.draw(glass.canvas, clock)
                glass.flush()
                glass.pump()
                if not alive:
                    card_closed = True
                    glass.close()
            else:
                alive = False

            if burst is not None:
                # t=0 for the release is the end of the card's
                # wind-up, so the release's own dip overlaps the
                # gather and the two read as one gesture
                shot_ms = card.released_ms() - GATHER_MS
                # THE SOUND IS FIRED FROM THE DRAW LOOP, from the same
                # clock the picture is drawn against, because that is the
                # only way the two can agree. Anything scheduled off a
                # timer drifts against a loop that absorbs stalls (see
                # clock_mod.absorb above) — and absorbing a stall is
                # exactly the case where a fixed delay would land the cue
                # on the wrong frame.
                if not landed and shot_ms >= land_at:
                    landed = True
                    splash.land()
                if not burst.draw(burst_glass.canvas, shot_ms):
                    burst_glass.close()
                    burst = burst_glass = None
                else:
                    burst_glass.flush()
                    burst_glass.pump()

            if released and not alive and burst is None:
                break

            # The card alone does not need 90 fps — it breathes at
            # 0.09 Hz. The release does. One loop drives both, so the
            # tick tightens at the moment it starts to matter.
            time.sleep(FRAME_S if released else IDLE_FRAME_S)
    except Exception:
        _log.info("skin boot card stopped early", exc_info=True)
    finally:
        try:
            if burst_glass is not None:
                burst_glass.close()
        except Exception:
            pass
        if not card_closed:
            glass.close()
        # BACKSTOP. Everything above can decline to happen — reduced
        # motion, no GPU layer, an exception mid-release, a stop during
        # the wind-up — and none of those are a reason for the app to go
        # ready in silence. land() has already been called on the normal
        # path and clears itself, so this is a no-op there.
        splash.land()
        splash._closing.set()


def moment_ms() -> float:
    """How long the whole thing takes, wind-up through settle.

    Derived rather than written down anywhere, because this number has
    changed three times - 880, 2820, 2690 - and each change silently broke
    a test that waited on a typed constant and then reported something
    entirely unrelated ("the skin left a window on screen", "the splash
    never closed"). Anything that needs to wait for the moment asks here.
    """
    try:
        from .reveal import T_END as reveal_end
    except Exception:
        reveal_end = 0
    return GATHER_MS + max(reveal_end, T_END)


def _warm(glass):
    """Draw the whole release once, off the clock, and throw it away.

    Skia builds its raster pipeline for a given combination of shader,
    blend mode and geometry the first time it meets one, and that lazy
    setup measured 83 ms on the first frame that had the bolt in it — one
    stutter, landing exactly on the frame the effect is judged by. Running
    the timeline through once during the load pays for all of it while
    nobody is looking. Nothing is flushed, so nothing reaches the screen.
    """
    if glass.on_gpu:
        from .reveal import Reveal, T_END as REVEAL_END
        shot = Reveal(glass.width, glass.height,
                      origin=(glass.width * 0.9, glass.height * 0.9), seed=1)
        span, start = REVEAL_END + 300, -300
    else:
        shot = Burst(glass.width, glass.height, seed=1)
        span, start = T_END + 200, -100
    for step in range(0, 26):
        shot.draw(glass.canvas, start + step * (span / 26.0))
    glass.canvas.clear(0x00000000)


def _burst_box():
    """The primary monitor. Not the 4480 px virtual desktop: "a boom on the
    screen" means the screen being looked at, and a shockwave stretched
    across three monitors has no centre to detonate at."""
    pw, ph = primary_screen()
    return 0, 0, pw, ph


def _land_ms(shot) -> float:
    """When the release's light ARRIVES in the status dot, on the same
    clock `shot.draw()` is given (t=0 is the impact).

    This is the frame the "ready" cue is fired on, so that the sound and
    the picture are one event. Before this existed the cue was played by
    main() next to splash.finish(), which is 1100 ms of linger plus
    GATHER_MS of wind-up plus the whole release ahead of the landing —
    measured at 3.63 s early.

    reveal.py CONVERGES on the dot: its arrival pulse is drawn from
    T_LAND[1] - 320 and peaks 160 ms later. The cue is fired at the START
    of that pulse, not its peak, for two reasons — PlaySound has to open
    the mixer before a sample leaves it, and "ready" is a rising PAIR
    (587 Hz for 90 ms, then 880), so firing at the pulse's first frame is
    what puts the resolving note on the pulse's brightest one.

    burst.py, the CPU fallback, has no landing at all: it disperses. The
    honest sync point there is its flash, and saying so is better than
    pretending a convergence happens.
    """
    try:
        from .reveal import Reveal, T_LAND
        if isinstance(shot, Reveal):
            return float(T_LAND[1] - 320)
    except Exception:                 # no skia, no reveal: fall through
        _log.debug("skin: no reveal timing", exc_info=True)
    return float(T_FLASH[0])


def _arm_burst(card, glass):
    """Build the release, pointed at the card the light is leaving.

    TWO RELEASES, and which one runs is decided by what the graphics card
    would give us, not by a setting. reveal.py is a 2.4 s wash of light
    built out of screen-sized Gaussian blurs, a domain-warped noise field
    and a 200 px soft wavefront - none of which is affordable on the CPU
    rasteriser, where one full-screen blended fill costs 238 ms. burst.py
    is the same moment told in hard-edged strokes and small shapes, which
    is what that budget can actually draw.

    Both start where the card is, so in both the light has a cause.
    """
    x, y, _w, _h = card.placement()
    heart = (x + WIN_W / 2, y + PAD + WAVE_Y)
    if glass.on_gpu:
        from .reveal import Reveal, T_DIP as REVEAL_DIP
        shot = Reveal(glass.width, glass.height, origin=heart,
                      seed=card._seed)
        shot.draw(glass.canvas, REVEAL_DIP[0])
    else:
        shot = Burst(glass.width, glass.height, seed=card._seed,
                     came_from=heart)
        shot.draw(glass.canvas, T_DIP[0])
    # the dip runs BEFORE t=0, and it is what makes the flash read bright
    glass.flush()
    return shot


__all__ = ["Card", "run", "T_END"]
