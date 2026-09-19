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
paints itself with the code it always had. The suite passes with the
folder deleted — that is asserted, not hoped for. Check it the way
everything here is checked — `.venv\Scripts\python.exe tests_quiet.py --no-screen`
— so that proving the look can be thrown away does not throw a single
window onto his screen.

If you also want the dependency gone: `pip uninstall skia-python` and drop
the last stanza of `requirements.txt`.

## What it touches outside itself

Five files, one guarded hook each, all in FRONT of code that was not
otherwise edited:

| file | hook | what falls back |
|---|---|---|
| `overlay.py` | `Splash._run`, `StatusDot._run` | the original Tk splash and dot |
| `ui.py` | one `repaint(globals())` at the end of the palette block | the original hex literals, which are still there |
| `visual_qa.py` | `_pump_wave` | the original `create_oval` rings |
| `shelf.py` | `skin.shelf_run(card)` in `ShelfCard._build_and_loop` | `shelf_card.flat()` in a plain Tk window with square corners, every button still working |
| `dashboard.py` | none — it reads `ui`'s names, and so do `widgets.py`, `keycaps.py` and `prose.py`, at call time rather than at import | whatever `ui.py`'s own literals say |

`ui.py` is the only interesting one. `from ui import CARD` binds the value
at import time, so the repaint has to happen while `ui.py` is still
executing — which is where the hook sits. `visual_qa.py` reads its palette
out of `ui.py`, so the ask card is recoloured without a hook of its own.

**Every shade the window draws now has a name.** `UI_NAMES` went from 30
to **47**: three the skin had and `ui.py` did not (`LINE_HI`, `FOCUS`,
`ACCENT_ON`, which `repaint` had therefore been silently skipping), two
the direction needs (`COOL`, `RECORDING`), and twelve that `ui.py` used
to spell out as hex INSIDE its own widget constructors — below the
`# --- SKIN` marker, where `repaint` could never reach them. A test now
fails on any `"#rrggbb"` below that marker. Each new name was also added
to `ui.py`'s pre-marker block at an OLD-palette value, so deleting
`skin\` still gives back a coherent COBALT window rather than a
half-repainted one.

**`fonts.py` is not part of the revert, and should not be.** The look
needs Rubik actually loaded — measured 2026-09-06, it was not: a fresh
process asking GDI for "Rubik" got Arial back, so `ui.pick_face` returned
Segoe UI and every surface in this document had been drawn in the
fallback face. `fonts.load()` calls `AddFontResourceExW(path, FR_PRIVATE,
0)` for every file in `fonts\`, at the import of `ui.py` (before
`pick_face`) and of `visual_qa.py`. It is four calls, under 3 ms,
idempotent, and it never raises. Deleting `skin\` does not undo it,
because the typeface was never the skin's choice — `ui.pick_face`'s
preference list has asked for Rubik all along; this is only the call that
makes the answer true.

## What is in the folder

| file | job |
|---|---|
| `palette.py` | LAMPLIGHT: the elevation ladder, the contrast table, the light ramp, `UI_NAMES` (47), `DOT_STATES` as `(fill, ring, pulses)` and `NO_HALO` |
| `ease.py` | the curves, as one-line canonical formulas |
| `gl.py` | an OpenGL context, so Skia can use the graphics card |
| `glass.py` | a click-through, never-focusable layered window Skia paints on — or, since 2026-09-19, that `present()` hands a Pillow picture to, so a copy WITHOUT skia (every fresh install: skia is the skin pack) still gets per-pixel alpha |
| `mark.py` | the mark drawn small by Pillow, on make_icon.py's 64-unit grid: the CARD tile with its drop shadow and hairline rim, the desk, the lamp and its glow. `Mark(tile, box, cut)` bakes the static half once; `frame()` is three pastes. The dot at 28 px, the boot card's badge at 44 |
| `boot.py` | the corner card, the waveform, and the thread that drives both |
| `reveal.py` | the release, on the GPU |
| `burst.py` | the release, for machines with no GPU |
| `dot.py` | the status dot: THE MARK, since 2026-09-19 — a 28 px tile in the 38 px box, and the lamp is the state. Five states, the lamp's glow on the tile gated on `NO_HALO` — paused is the one that casts no light, checked on the rendered pixel 3 px out from the lamp rather than on the colour table, because the rule is about DRAWING — and, since 2026-09-07, a BUTTON: `Dot.hit` answers HTCLIENT on the tile and HTTRANSPARENT on the shadow and the corners, `place()` puts it in a corner of the work area (`[dot] corner`, bottom-right by default) while `spot()` prefers wherever it was dragged to (`[dot] x/y`), the tile answers HTCAPTION instead while `move()` is armed so Windows drags it, and the shadow is zeroed on the window's border so nothing reaches the edge. Painted by `mark.py`, so it needs no skia |
| `shelf.py` | the glass under the panel beside the dot (`face()` + `run()`): `notify.py`'s recipe with the shelf's geometry and `hint.py`'s shadow put back. Nothing animates, so `run()` caches the composed picture on `(card, hover, scale)` and re-blits it — composing a full panel is 41 ms and the tick is one second |
| `hint.py` | the key card while a key is held; its `DOTS` are derived from `DOT_STATES`, so the card and the corner dot cannot disagree |
| `notify.py`, `review.py` | the glass under the notification column and the second-reading card |
| `wave.py` | the microphone rings in the ask card |
| `preview.py` | `python -m skin.preview burst\|card\|all` |
| `record.py` | `python -m skin.record out.mp4` — film it over the real desktop |

## The design

### LAMPLIGHT — one lamp on a dark desk

The palette was COBALT (`#11151b` ground, `#1d6dd4` accent). Since
2026-09-07 it is **LAMPLIGHT**: the app is the light, not the furniture.

The argument for it is not taste, it is coherence. It is the only palette
the owner has ever said he liked, and **the logo he loves is already
painted in it** — a dark tile, a light desk, a gold lamp. Choosing this
makes the app become its mark instead of the mark being an outlier on its
own screen. The risk is his own sentence from round 1, when a warm
graphite and gold restyle came back as *"it just looks like the colours
changed"*: this direction only works if the shapes change too, which is
why it shipped with the rail gone, the keyboard drawn and the shelf built
rather than on its own.

**The surface ladder.** Neighbours step 3–5 L\* apart; closer than that
and two surfaces read as one, which is the fault this file's palette was
written to fix in the first place.

| token | hex | L\* | step |
|---|---|---|---|
| `GROUND` | `#14110C` | 5.2 | — |
| `PANE` | `#1C1813` | 8.5 | +3.3 |
| `CARD` | `#24201A` | 12.5 | +4.0 |
| `CARD_HI` | `#2E2921` | 16.9 | +4.4 |
| `LINE` | `#3A342A` | 22.0 | +5.1 |
| `LINE_HI` | `#4E4737` | 30.4 | +8.4 |

**The text, against the two surfaces it actually lands on.** Body text is
≥ 4.50 everywhere it can go; `FAINT` is the one shade allowed to fail it,
and it is bounded from both sides — 3.0 ≤ x < 4.5 — because a
well-meaning lift would turn it into a second body colour.

| token | hex | on ground | on card |
|---|---|---|---|
| `FG` | `#F1ECE2` | 15.99 | 13.76 |
| `DIM` | `#B2A896` | 8.01 | 6.89 |
| `ACCENT_TEXT` | `#F0BA5C` | 10.66 | 9.17 |
| `GREEN` | `#63C88C` | 9.12 | 7.84 |
| `ACCENT` / warning | `#E3A63C` | 8.77 | 7.55 |
| `RED` | `#F1867A` | 7.56 | 6.50 |
| `FAINT` | `#7E7564` | 4.14 | 3.56 — labels and rules only, never prose |

**On a gold fill the label is `ACCENT_ON` (`#1A1409`), at 8.52 : 1.** `FG`
on gold is **1.8 : 1** and simply vanishes. That mattered immediately:
the accept button of the review card, the Send of the problem and answer
cards and the picked option's badge digit were all drawing white on the
accent, and the blue palette had been hiding it — white on the old accent
was 4.10 : 1, already failing AA, and the same code on gold is
unreadable. All four now use `ACCENT_ON`. There was **no contrast test**
before this; there is one now, and it asserts every number in the two
tables above.

**Where the accent is spent, and where it may never go.** The lamp dot,
the ONE primary action on a surface, the focus ring (`FOCUS == ACCENT`),
and the selected place's edge. **It never fills a surface, a card border
or the rail, and no surface ever has two gold things lit at once.**
`COOL` (`#8FC0F0`) is the listening dot and links, and nothing else.
`AMBER == ACCENT`, deliberately: in this app "your attention is wanted
here" and "this is the primary action" are the same message. The cost of
that is worth writing down — a surface that ever needs a *needs-you*
badge **and** a primary button has no second attention colour. The rule
holds today because the review card and the notify card never both need
it, and it will bite the day it stops holding.

**The five dot states.** The dot is a layered window sitting on the
user's wallpaper — since 2026-09-19 the mark itself (`mark.py`): a
`CARD` tile that carries its own ground, with a drop shadow to lift it
off a light wallpaper and a hairline rim to find its edge on a dark one
— and the lamp on the tile is the state, checked against `CARD`
(L\* 12.5) rather than against whatever is behind the window:

| state | hex | on the tile | L\* |
|---|---|---|---|
| listening | `#8FC0F0` | 8.46 | 76.0 |
| recording | `#FF5B4E` | 5.29 | 61.0 |
| locked | `#FF8A7E` | 7.09 | 70.1 |
| transcribing | `#F5C043` | 9.64 | 80.5 |
| paused | `#6F6F6F` | 3.22 | 46.8 |

Why a tile at all: the owner walked a fresh install on 2026-09-19 and his
screenshot showed the dot in the top-right of a bright sky wallpaper as
"a thin ring", nearly invisible. A disc of light is only ever as visible
as the contrast between its colour and the wallpaper, and listening is
sky blue. What he was looking at was in fact the Tk fallback — a fresh
install has no skia (it is the skin pack, a 10.9 MB download nobody
makes) — which is why `mark.py` is Pillow and `glass.present()` exists:
the dot is now the same picture with the pack and without it.

Every pair separates by light (ΔL\* ≥ 8) or by hue (Δhue ≥ 40) — ΔL\* is
what a colour-blind eye keeps, Δhue is what it may lose — and all ten
pairs pass. The one exception is **recording against locked**, which is
one colour by design: they are 9.1 L\* and 1.2° apart, and what actually
separates them is the 0.16 Hz breath the dot has always had.

**Paused is the one state with no light on the tile**, and that is the
rule, not a detail: `paused` is a neutral grey with no warmth in it at
all, and listening is a cool blue at nearly the same distance from
transcribing (ΔL\* 4.5) — so the glow's *presence* is what tells "off"
from "on", rather than hue alone. `palette.NO_HALO = frozenset({"paused"})`
and `skin\dot.py` gates on it. The test checks the rendered pixel 3 px
out from the lamp — the bare tile for paused, exactly; tinted for every
lit state — not the colour table, because the rule is about drawing.

**Everything ends inside the window, and that was a bug until
2026-09-07.** The old halo ran to CORE × 2.6 = 26 px in a 38 px box,
which left alpha 27 at every edge midpoint (0 at the corners) — a faint
tinted square on any wallpaper or title bar, and the owner's words for
it were "the dot looks like a square". The mark's shadow is the soft
thing now: blurred at 4× and reduced with a box filter (no ringing), and
the border row and column zeroed outright. A test walks the whole border
of every state and asks for zero, and asks that the tile be solid at
13 px from the centre. BOX stays 38 because two tests identify the dot
by its size.

**The dot is a button, and only the tile is.** It moved from the
top-right corner to the bottom-right of the work area that same night —
above the taskbar, a corner nothing else lives in — which is what made a
button possible at all: in the top-right it sat on the close button of
every maximised window and had to be click-through as a whole. Now
`Dot.hit` answers HTCLIENT on the tile (its rounded-off corners
included in "not") and HTTRANSPARENT everywhere else (the shadow, the
window's corners), `glass.Glass` is built without WS_EX_TRANSPARENT and
asks it per pixel, and a click on the tile calls
`overlay.StatusDot.on_click` — main.py's `_tap_shelf`, the same toggle
as ctrl+alt+d. Two clicks inside 300 ms are one click, so a double-click
is not an open and a close. The reveal's landing follows the dot
(`boot._landing` asks `dot.spot`), and so do the shelf and the key card
(`HintCard.origin`, `DOT_ROOM`, measured against the work area).

**And the same tile is the drag handle.** `overlay.StatusDot.move()`
arms move mode for a few seconds — the dashboard's "Move the dot" sends
it down the control pipe while the app runs — and while it is armed
`Dot.hit` answers **HTCAPTION** on the tile instead of HTCLIENT, so
Windows itself runs the drag exactly as it does for the notify column
and the shelf. That message split is what makes one press unable to be
both gestures: a caption press arrives as WM_NCLBUTTONDOWN and the
shelf's toggle is on WM_LBUTTONDOWN. Everything off the tile still
answers HTTRANSPARENT in move mode — the shadow never takes a click away
from the window underneath, armed or not — so the thing that LIGHTS UP
to say "drag me" is the tile's own rim, drawn bright (`mark.RIM_MOVING_A`)
and twice as wide, and not anything outside it: what glows has to be
what can be pressed. The drop is read off the handle with
`glass.where()`, clamped so the whole 38 px square stays on the virtual
desktop, and written to `[dot] x/y`.

**The mark.** A dalet drawn as a desk: a tabletop with one leg hanging
from its right end, the top's edge just past the leg, the lamp-dot above
the left of the top, and — at 48 px and up only — two light arcs to the
dot's right. Tile `CARD` with a `rgba(255,255,255,.08)` rim and a radius
of 15/64; letter `FG`; dot and arcs `ACCENT`, with a glow fading .55→0
out to r 14 drawn UNDER the desk. Two variants: a **lit tile** (gold
tile, ground-coloured desk) for a selected state, and **one-colour**
(`DIM`) for the taskbar and for disabled. The wordmark is "DeskIT" in
Rubik 700 with the "IT" in `ACCENT_TEXT`. `make_icon.py` draws it on the
design's own 64-unit grid at 4× and downsamples with LANCZOS; the arcs
are solved from their SVG arc commands rather than eyeballed, which is
what puts both of them exactly on the lamp's own centreline. Two cuts:
`full ≥ 48` with the glow and the arcs, `small < 48` with neither —
16 px cannot hold what 256 px can, and below 48 the glow is a smudge, so
`ui._icon_art` takes the small frame out of `icon.ico` rather than
downsampling the full cut.

**The type.** Rubik, at last actually loaded (see `fonts.py` above), in
two weights: through GDI only 400 and 700 are real. Every size is the
Segoe-era number **+2 px**, because Rubik draws Hebrew ~13% smaller at
the same nominal size (93% of nominal against Segoe's 107% at 15 px), and
every row is +20% for its taller line box. Emphasis comes from size and
from `ACCENT_TEXT`, never from a Medium that does not exist.

| name | pt | px | what |
|---|---|---|---|
| `PT_TITLE` | 20 | 27 | the one big line on a screen |
| `PT_HERO` | 15 | 20 | a state, or a number that is the point of a tile |
| `PT_WORDS` | 13 | 17 | **his own words** |
| `PT_BODY` | 12 | 16 | body, buttons, every ordinary line |
| `PT_LABEL` | 10 | 13 | a Hebrew label, a meta line |
| `PT_CAPS` | 9 | 12 | Latin small caps, an eyebrow |

Rows followed: `PILL_H` 36 (was 30), `BTN_H` 40 (36), `CAP_H` 40 (34),
`SWITCH_W/H` 46/26 (42/24), `ROW_H` 44 (36). No letter-spacing on a
Hebrew run, ever. And a Latin run inside an RTL line reorders — `2.1 s ·
local` comes out as `s · local 2.1` — so a meta line that mixes Hebrew
with numbers or filenames is drawn as separate runs and never as one
string.

### Five decisions worth disagreeing with

1. **The hint card's key chips are key caps, not accent chips.** In gold,
   fifteen accent chips turned a legend into fifteen primary actions
   competing for one glance. They take `ui.KeyCap`'s face now, in both
   painters (`skin\hint.py` and `overlay.py`'s Tk fallback), and the only
   lit thing on that card is the state bead.
2. **The review card's clock bar stays gold beside the gold accept
   button.** Strictly that is two gold things on one surface. It is a
   rule and not a control, and desaturating it loses the "this is about
   to go away" signal — so it is flagged here rather than hidden.
3. **`capture.INKS` is deliberately NOT on the palette.** Those four are
   drawn on somebody else's screenshot and need to be foreign to the
   picture rather than native to the app. The red went one step brighter
   (`#e83e30`) so a mark still reads when the capture is OF this app's
   own gold chrome, and `MARK` stayed the vivid `#ffd640` for the same
   reason: under LAMPLIGHT the chrome is warm, so the pencil has to
   separate by being brighter and more saturated than any gold the app
   draws (Y .70 against .44).
4. **`popup.PRESSED` is `#d9483c`, not the palette's `RED`.** It is a
   FILL with the ✕ drawn over it: `FG` on the palette red is 2.1 : 1 and
   on this one 3.61 : 1, which is what a graphic needs. The text-weight
   message ("the clipboard is busy") moved to a new `DANGER_TEXT` at
   7.56 : 1.
5. **`glass_plate`'s tint is the gold taken down to the blue's own
   luminance** (Y .272 against .269), so the plate is the same weight over
   a screenshot as it always was; the three glass inks were matched the
   same way (.88/.53/.33 against .91/.52/.35).

Two more, in files that read the table rather than write it.
`skin\reveal.py`'s seven-stop ramp was retuned with its **luminance order
preserved** (1.00/.90/.68/.55/.51/.02) because `_front` reads the stops
inner-to-edge and assumes each is dimmer than the last. And `shelf_card`
reads its colours from `skin.palette` **by name**, with one fallback
table holding the LAMPLIGHT literals for the case where `skin\` is
deleted — against the palette as it stands nothing falls back; its
`recording` and `locked` come out of `DOT_STATES` when they are there, so
the shelf's own dot and the corner dot can never disagree.

### The boot moment

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

**The two paths do not have the same ladder, and only the Skia one is
free.** Because `boot._rubik` clones the axis, a glass card can use a
genuine Medium. The Tk/GDI path cannot: measured 2026-09-06 with all four
files privately loaded, `("Rubik", 500)`, `Rubik Medium` and
`Rubik SemiBold` all resolve to the 400 outlines (advance 104 px for
`מבנה חדש` at 24 px, against 108 for 700), so `ui.MEDIUM` is a real
family name that draws at regular weight. Emphasis in the window comes
from size and from `ACCENT_TEXT`; emphasis on a glass card may come from
a weight.

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
  dot — bottom-right of the work area since 2026-09-07, wherever `[dot]
  corner` says, or wherever `[dot] x/y` says it was dragged to; the one
  thing that stays on screen for the rest of the session — rather than
  fading to nothing. A uniform fade to zero has no
  event structure and reads as "it vanished".
- **Seeded per boot**, so the fifth time is not a replay of the first.
