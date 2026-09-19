"""LAMPLIGHT — one lamp on a dark desk. The app is the light, not the desk.

The blue is gone. It was never wrong on contrast — COBALT fixed that — it
was wrong on IDENTITY: the mark the owner actually likes is a dark tile, a
white desk and a gold lamp, and a blue window around that mark made the
mark the outlier. This palette makes the app become its own icon.

Read the numbers, not the adjectives. Every value below was measured with
the WCAG formula and CIE L*, and the ladder is the first thing to check:

    ground  #14110C  L*  5.2
    pane    #1C1813  L*  8.5   (+3.3)
    card    #24201A  L* 12.5   (+4.0)
    card-hi #2E2921  L* 16.9   (+4.4)
    line    #3A342A  L* 22.0   (+5.1)
    line-hi #4E4737  L* 30.4   (+8.4, and it is a border, not a surface)

Adjacent surfaces are 3.3-4.4 L* apart, which is the band where a card
reads as lifted off its pane without anything looking milky. Closer and two
surfaces read as one — the fault this file was originally written to fix.

Contrast, measured (ratio against ground, then card, then card-hover):

    text        #F1ECE2  15.99 : 1  13.76  12.26     AAA everywhere
    dim         #B2A896   8.01       6.89   6.14     AAA to card, AA above
    faint       #7E7564   4.14       3.56   3.17     RULES AND LABELS ONLY
    accent      #E3A63C   8.77       7.55   6.72
    accent-text #F0BA5C  10.66       9.17   8.17     AAA on all four
    success     #63C88C   9.12       7.84   6.99
    danger      #F1867A   7.56       6.50   5.79
    cool        #8FC0F0   9.83       8.46   7.54
    recording   #FF5B4E   6.15       5.29   4.71

    accent-on   #1A1409 on the gold fill        8.52 : 1
    text        #F1ECE2 on accent-soft         12.39 : 1

FAINT is under 4.5 on purpose and is only ever a hairline label or a rule,
never anything a person has to read — the same discipline COBALT kept.

Three rules the values alone cannot carry, and every surface has to:

1. **The accent never fills a surface, a card border or the rail.** It is
   the lamp: the one primary action on a surface, the focus ring, the lit
   edge of the selected place. Two gold things lit at once on one surface
   is the bug, not the taste question.
2. **Blue is the listening dot and links.** `COOL` is the one cool point in
   a warm world and it keeps the blue the owner has already learned.
3. **Warning IS the accent, deliberately.** In this app "your attention is
   wanted here" and "this is the primary action" are the same sentence.
   The cost is that a surface needing a needs-you badge AND a primary
   button has no second attention colour; the day that stops holding, the
   badge gets a shape rather than a hue.

The five dot states are not drawn from this ladder. The status dot is a
38 px layered window sitting on the user's *wallpaper* — since 2026-09-19
the mark itself, a CARD tile with the lamp on it (skin\\mark.py) — so the
lamp needs lit colours against that one dark ground whatever is behind
the tile. Measured against CARD: listening 8.46, recording 5.29, locked
7.09, transcribing 9.64, paused 3.22. Every pair separates by light
(dL* >= 8) or by hue, except recording/locked, which are one colour by
design — the 0.16 Hz breath is what separates them — and paused, which
separates from listening by casting NO LIGHT on the tile at all rather
than by hue alone.
"""
from __future__ import annotations

# ---------------------------------------------------------------- surfaces
BG = "#14110c"          # L*  5.2  the window, the card ground
PANE = "#1c1813"        # L*  8.5  a field, a strip, a secondary face
CARD = "#24201a"        # L* 12.5  a lifted face
CARD_HI = "#2e2921"     # L* 16.9  a face under the pointer
LINE = "#3a342a"        # L* 22.0  hairline border
LINE_HI = "#4e4737"     # L* 30.4  a border being interacted with
FOCUS = "#e3a63c"       # the focus ring IS the accent — 8.77:1 on bg

# ------------------------------------------------------------------- text
FG = "#f1ece2"          # 15.99:1 on bg
DIM = "#b2a896"         # 8.01:1
FAINT = "#7e7564"       # 4.14:1 — rules and micro-labels, never prose

# ----------------------------------------------------------------- accent
ACCENT = "#e3a63c"      # the lamp. 8.52:1 against its own on-colour
ACCENT_HI = "#f0b854"   # hover — 10.48:1 on bg
ACCENT_DOWN = "#c68c28"  # pressed
ACCENT_SOFT = "#332711"  # L* 16.5 — a selected row's fill, text 12.39:1
ACCENT_TEXT = "#f0ba5c"  # the accent at TEXT weight — 10.66:1, AAA
ACCENT_ON = "#1a1409"   # text ON the gold fill — 8.52:1

# -------------------------------------------------------------- semantics
GREEN = "#63c88c"       # 9.12:1 — done, learned
AMBER = ACCENT          # = the accent, deliberately (see the note above)
RED = "#f1867a"         # 7.56:1 — errors and destructive
TEAL = "#7fc8c8"        # 9.86:1 — a history badge, not a state
VIOLET = "#c3a2ec"      # 8.70:1 — a history badge, and awake-while-dark

# The two the window palette does not own: the dot's red, which has to
# carry on a wallpaper, and the one cool point in a warm world.
RECORDING = "#ff5b4e"   # L* 61 — the dot while it is capturing
COOL = "#8fc0f0"        # 9.83:1 — the listening dot, links, informational

# ------------------------------------------------------- derived surfaces
EDGE = "#29241d"        # a secondary button — L* 14.5, between card and hi
EDGE_HI = "#332d24"     # L* 18.8
EDGE_DOWN = "#1f1b15"   # L* 10.0
STROKE = LINE

# The eight the dashboard used to spell out inline, kept on the ladder.
RULE = "#211d17"        # a hairline on the ground: one step over PANE
ACCENT_EDGE = "#5a431a"  # the border of a selected row: over ACCENT_SOFT
SIDE_IDLE = "#1a1610"    # an unselected row on the ground
SIDE_CARD = PANE         # the state card at the foot of a column
QUOTE_BG = CARD          # the quoted transcript — CARD exactly
QUOTE_EDGE = LINE
TILE_EDGE = "#5a5240"    # a row under the pointer, just over LINE_HI
CHIP_BG = "#292419"      # the square behind a row icon

# ------------------------------------------- the thirteen widget shades
# ui.py used to spell these out INSIDE its own widget constructors, where
# no repalette could reach them, so the filter chips and every key cap
# stayed on the old colours while the rest of the window changed. They are
# on the ladder now and `repaint` covers them.
BTN_OFF = "#211d17"      # a disabled button: RULE — flat, one step over bg
BTN_OFF_EDGE = "#2b2620"
CHIP_ON_EDGE = "#5a431a"  # a chip that is on: ACCENT_SOFT with a lit edge
CHIP_OFF = "#1f1b15"      # a chip, a pill, a pair pill at rest: EDGE_DOWN
CHIP_OFF_EDGE = "#332d24"  # EDGE_HI
CHIP_HOVER = "#29241d"     # EDGE
CHIP_HOVER_EDGE = "#4e4737"  # LINE_HI
TRACK_OFF = "#4e4737"      # the switch's track when off — LINE_HI, so the
#                            knob (FG) reads as ON A TRACK rather than as a
#                            dot floating on the card
KEY_BG = "#29241d"       # a key cap is a secondary face with a lit rim
KEY_EDGE = "#4e4737"
KEY_HI = "#332d24"       # a key cap under the pointer
THUMB = "#4e4737"        # the scroller's thumb — LINE_HI

# The accent pre-composited over BG at four weights. Baked as flat fills
# because a blur to suggest a glow costs a frame; these cost nothing.
GLOW_05 = "#1e180e"
GLOW_10 = "#292011"
GLOW_16 = "#352914"
GLOW_24 = "#463518"

# ------------------------------------------------------------- the light
# The value ramp the burst is built from, core outward. Five stops, warm at
# the core and cool at the edge, because that is what hot things do and
# because a ramp that stays one hue reads as a UI element lit from inside
# rather than as light. LAMPLIGHT keeps that shape and moves the middle of
# it onto the lamp: white, then incandescent, then the gold itself, then
# the one cool colour in the palette at the rim. Never a saturated red
# anywhere: R/(R+G+B) >= 0.8 is the single highest seizure-risk colour and
# every guideline gives it its own stricter threshold. The warmest stop
# here computes to 0.37.
LIGHT_CORE = (255, 255, 255)
LIGHT_HOT = (255, 240, 206)      # #FFF0CE — the classic incandescent stop
LIGHT_MID = (240, 186, 92)       # ACCENT_TEXT: the lamp at its own weight
LIGHT_ACCENT = (143, 192, 240)   # COOL: the corona, and the blue's new home
LIGHT_DEEP = (24, 38, 60)        # #18263C — night at the rim


def rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return (int(colour[0:2], 16), int(colour[2:4], 16), int(colour[4:6], 16))


def argb(alpha: float, colour) -> int:
    """A Skia colour from an alpha in 0..255 and either a hex string or an
    (r, g, b). Clamped, because an alpha computed from an easing curve
    that overshoots would otherwise wrap."""
    if isinstance(colour, str):
        r, g, b = rgb(colour)
    else:
        r, g, b = colour
    a = 0 if alpha < 0 else 255 if alpha > 255 else int(alpha)
    return (a << 24) | (int(r) << 16) | (int(g) << 8) | int(b)


def lerp_rgb(one, two, k: float) -> tuple[int, int, int]:
    if isinstance(one, str):
        one = rgb(one)
    if isinstance(two, str):
        two = rgb(two)
    k = 0.0 if k < 0 else 1.0 if k > 1 else k
    return tuple(int(a + (b - a) * k) for a, b in zip(one, two))


def hex_of(colour) -> str:
    if isinstance(colour, str):
        return colour
    return "#%02x%02x%02x" % tuple(int(c) for c in colour)


# What ui.py exports, and therefore what a reskin has to be able to answer
# for. Kept as an explicit map rather than "everything uppercase in this
# module" so that adding a colour here cannot silently repaint a widget
# nobody looked at. `repaint` writes ONLY over names ui.py already defines,
# so every entry below has a matching literal in ui.py's palette block —
# which is what the app falls back to when skin\ is deleted.
UI_NAMES = {
    "BG": BG, "PANE": PANE, "CARD": CARD, "CARD_HI": CARD_HI, "LINE": LINE,
    "LINE_HI": LINE_HI, "FOCUS": FOCUS,
    "FG": FG, "DIM": DIM, "FAINT": FAINT,
    "ACCENT": ACCENT, "ACCENT_HI": ACCENT_HI, "ACCENT_DOWN": ACCENT_DOWN,
    "ACCENT_SOFT": ACCENT_SOFT, "ACCENT_TEXT": ACCENT_TEXT,
    "ACCENT_ON": ACCENT_ON,
    "RED": RED, "AMBER": AMBER, "GREEN": GREEN, "VIOLET": VIOLET,
    "TEAL": TEAL, "COOL": COOL, "RECORDING": RECORDING,
    "EDGE": EDGE, "EDGE_HI": EDGE_HI, "EDGE_DOWN": EDGE_DOWN,
    "STROKE": STROKE,
    "RULE": RULE, "ACCENT_EDGE": ACCENT_EDGE, "SIDE_IDLE": SIDE_IDLE,
    "SIDE_CARD": SIDE_CARD, "QUOTE_BG": QUOTE_BG, "QUOTE_EDGE": QUOTE_EDGE,
    "TILE_EDGE": TILE_EDGE, "CHIP_BG": CHIP_BG,
    "BTN_OFF": BTN_OFF, "BTN_OFF_EDGE": BTN_OFF_EDGE,
    "CHIP_ON_EDGE": CHIP_ON_EDGE, "CHIP_OFF": CHIP_OFF,
    "CHIP_OFF_EDGE": CHIP_OFF_EDGE, "CHIP_HOVER": CHIP_HOVER,
    "CHIP_HOVER_EDGE": CHIP_HOVER_EDGE, "TRACK_OFF": TRACK_OFF,
    "KEY_BG": KEY_BG, "KEY_EDGE": KEY_EDGE, "KEY_HI": KEY_HI,
    "THUMB": THUMB,
}

# overlay.STATES is (fill, ring, pulses) and a test asserts that shape, so
# the dot's colours are given here in the same form rather than as a new
# structure the test would not recognise. `ring` is the backplate the Tk
# fallback paints under the disc; the glass dot paints `fill` as the lamp
# on the mark's CARD tile and casts it on the tile as a glow. Measured
# against CARD: 8.46 / 5.29 / 7.09 / 9.64 / 3.22.
DOT_STATES = {
    "ready":     (COOL, "#16232f", False),        # listening — the one cool
    "recording": (RECORDING, "#3a140f", False),   # capturing now
    "locked":    ("#ff8a7e", "#3a140f", True),    # latched, breathing
    "busy":      ("#f5c043", "#33260a", False),   # the lamp at full
    "paused":    ("#6f6f6f", "#1e1e1e", False),   # neutral, and see NO_HALO
}

# Paused is the ONE state with no halo. It is the only neutral in the set,
# and a grey glow on the tile is a smudge rather than a light — so the
# state reads by the light's ABSENCE, which no colourblindness and no
# wallpaper can take away. Everything else casts its colour on the tile.
NO_HALO = frozenset({"paused"})
