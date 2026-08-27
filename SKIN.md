# SKIN.md — the look, and how to throw it away

Everything this app looks like now lives in one folder, `skin\`. That is
not tidiness; it is the requirement. The whole design was built so that you
can delete it and get the old app back, exactly, with no migration and no
half state.

## Getting rid of it

```
set HD_SKIN=0
```
for one run — the app starts on its original Tk overlays and the original
palette.

```
skin\__init__.py  ->  ENABLED = False
```
for good, keeping the code around in case you want it back.

```
rmdir /s /q skin
```
gone. Every hook is `try: import skin / except: skin = None`, so removing
the folder makes those imports fail, every hook falls through, and the app
paints itself with the code it always had. `tests.py` passes with the
folder deleted — that is asserted, not hoped for.

If you also want the dependency gone: `pip uninstall skia-python` and drop
the last stanza of `requirements.txt`.

## What it touches outside itself

Four files, one guarded hook each, all in FRONT of code that was not
otherwise edited:

| file | hook | what falls back |
|---|---|---|
| `overlay.py` | `Splash._run`, `StatusDot._run` | the original Tk splash and dot |
| `ui.py` | one `repaint(globals())` at the end of the palette block | the original hex literals, which are still there |
| `visual_qa.py` | `_pump_wave` | the original `create_oval` rings |
| `dashboard.py` | none — it gained named constants instead of 13 inline hexes | the constants carry the OLD values in `ui.py` |

`ui.py` is the only interesting one. `from ui import CARD` binds the value
at import time, so the repaint has to happen while `ui.py` is still
executing — which is where the hook sits. `visual_qa.py` reads its palette
out of `ui.py`, so the ask card is recoloured without a hook of its own.

## What is in the folder

| file | job |
|---|---|
| `palette.py` | COBALT: the elevation ladder, the contrast table, the light ramp |
| `ease.py` | the curves, as one-line canonical formulas |
| `gl.py` | an OpenGL context, so Skia can use the graphics card |
| `glass.py` | a click-through, never-focusable layered window Skia paints on |
| `boot.py` | the corner card, the waveform, and the thread that drives both |
| `reveal.py` | the release, on the GPU |
| `burst.py` | the release, for machines with no GPU |
| `dot.py` | the status dot |
| `wave.py` | the microphone rings in the ask card |
| `preview.py` | `python -m skin.preview burst\|card\|all` |
| `record.py` | `python -m skin.record out.mp4` — film it over the real desktop |

## The design

**The card** holds a waveform. It grows from a near-flat line into a full
voice as each model loads, glowing, with a gradient running along its
length. It replaced a single thin line pulled down in the middle, which was
meant to read as a drawn bowstring and instead read as "some thread, I did
not even understand it". The lesson is not that the metaphor was wrong — it
is that a metaphor needing explanation has already failed. Everyone has
seen sound drawn as a waveform, and this is an app you talk to.

**The moment** is 2690 ms and is mostly wind-up:

| | ms | what |
|---|---|---|
| SUMMONS | 0–280 | a core arrives in the card, abruptly |
| CHARGE | 280–1150 | the waveform contracts into it, accelerating |
| BREATH | 1150–1330 | absolute stillness, 3% scale pulse only |
| IMPACT | 1330 | one flash, cut into |
| HITSTOP | 1330–1440 | the aftermath, already formed, frozen |
| EXPANSION | 1440–2380 | the front crosses the screen |
| LANDING | 1850–2690 | the light converges into the status dot |

That is 49% build, 5% payoff, 46% decay. The shape matters more than the
length: the first attempt was 880 ms (all payoff, no build) and the second
was 420 ms of wind-up followed by 2400 ms of aftermath. Both were rejected.
A card 24° off screen centre costs a gaze about 300 ms just to reach, so a
wind-up shorter than that is one nobody sees begin.

Two details carry more than their weight. The impact **cuts** to a
composition that is already formed — the front already out at
`FRONT_R0` — because starting an expansion from a point spends the first
tenth of the payoff on shapes too small to read. And the 110 ms **hitstop**
after it is what lets the eye catch up.

## The measurements the design is built on

**Skia's CPU rasteriser blends at 64 ns a pixel.** Perfectly linear,
unchanged by colour type, alpha type or colour space, and about twenty
times slower than a naive scalar loop has any right to be. At 2560×1440
that makes one full-screen translucent fill 238 ms, so every soft, large,
lovely thing was unaffordable and `burst.py` is bent around avoiding them.

**The same work on the GPU is 3400× faster.** Through `skin\gl.py`, on this
machine's RTX 5060 Ti:

| | CPU | GPU |
|---|---|---|
| full-screen 42% alpha fill | 238 ms | 0.07 ms |
| full-screen radial gradient | ~200 ms | 0.07 ms |
| that gradient + a 60 px Gaussian blur | unusable | 0.09 ms |
| readPixels 2560×1440 | — | 4.33 ms |

The card is drawn on the CPU anyway, deliberately: building the GL context
costs ~270 ms and pushed the splash's appearance from 79 ms to 250, which
is the one thing a splash may not do. It is 98k pixels and takes 0.9 ms
there. The GPU is acquired later on the same thread, for the release's
full-screen layer, by which point the models have been loading for a
second and nobody is waiting.

The readback is the entire price and it is one fixed 4.3 ms. A complete
reveal frame — bloom, aurora shader, two soft fronts, rays, motes — plus
the readback is about 10 ms, so it runs at ~100 fps with room to spare.

**Redrawing what never changes is where the time goes.** The card's
six-layer shadow was 24.49 ms of a 28.98 ms frame, ninety times a second,
for the twenty-five seconds two Whisper models are loading. Baked once into
an image and drawn with a paint alpha, the whole card frame is 0.90 ms.

**Tk antialiases nothing.** A 400×400 grab of Tk canvas primitives held
exactly two distinct colours. That is why the first release looked
pixelated, and why nothing here is drawn with canvas items.

## Traps worth writing down

**The four Rubik files are one variable font.** `Rubik.ttf`,
`RubikMedium.ttf`, `RubikSemiBold.ttf` and `RubikBold.ttf` in `fonts\` all
report `fontStyle().weight() == 300` and identical advance widths. Asking
for the Medium file and expecting Medium gets Light, which is what the
first card shipped as. `boot._rubik` pins the `wght` axis with `makeClone`;
verified 300/400/500/700 measuring 79.30/80.98/82.96/84.96 px.

**Skia builds its raster pipeline lazily.** The first frame containing the
bolt cost 83 ms — one stutter, landing exactly on the frame the effect is
judged by. `boot._warm` runs the whole timeline once during the load, into
a surface that is never flushed.

**A runtime shader needs its WHOLE uniform block.** Supplying 8 bytes for a
`float2 + float` gives every uniform zero, silently — no error, just a
black frame. Pack all of it, declared order, `float2` first.

**`reveal.py` renders differently on the CPU rasteriser** — 38% of a frame
pure white against 2.4% on the GPU. It is never drawn there (`boot.py`
picks `burst.py` without a GPU), and its tests skip when there is no
context rather than testing a path the app never takes.

## The rules the release obeys

- **One flash.** WCAG 2.3.1 exempts content with at most three general
  flashes per second regardless of area; a full-screen effect is far past
  the 0.006 sr area limit, so one impulse is the only safe design. Nothing
  here is periodic anywhere in the 3–55 Hz band. A test measures the
  rendered pixels and fails if more than one frame blows out.
- **Peak alpha 0.42, never white**, over a 19% dim that creeps in under the
  whole charge. Brightness with no dark reference is glare.
- **Under three seconds**, so it stays inside the 2–3 s "subjective
  present" and is remembered as one gesture.
- **Reduced motion is honoured** — `SPI_GETCLIENTAREAANIMATION`. With
  animation effects off in Windows the card simply goes and nothing fires.
- **It ends somewhere.** The last beat gathers the light into the status
  dot in the top-right — the one thing that stays on screen for the rest of
  the session — rather than fading to nothing. A uniform fade to zero has
  no event structure and reads as "it vanished".
- **Seeded per boot**, so the fifth time is not a replay of the first.
