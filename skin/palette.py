"""B+ — a deep night, glass on it, and one soft iris light.

Since 2026-10-23 this is the look of everything outside the desk too. The
desk window moved to a web page in the look the owner approved on
2026-09-23 ("B+", web\\src\\bplus.css: the deep night ground, panes of
frosted glass with a rim the light catches top-left, 22-24 px corners,
ONE iris-violet accent, Rubik, soft fades); every other window keeps its
technology — Skia glass, Pillow painters, Tk — and takes these colours.
LAMPLIGHT (warm graphite and a gold lamp, 2026-09-07) is what this file
was until then; its numbers are in git.

Read the numbers, not the adjectives. Every value below was measured with
the WCAG formula and CIE L*, and the ladder is the first thing to check:

    ground  #0B0D19  L*  3.9
    pane    #121527  L*  7.3   (+3.4)
    card    #1A1E35  L* 12.0   (+4.7)
    card-hi #242944  L* 17.4   (+5.4)
    line    #30365A  L* 23.7   (+6.3)
    line-hi #454C78  L* 33.5   (+9.8, and it is a border, not a surface)

The hue is the ground's: navy at about 232 degrees, the same night the
desk's floor is (#080A14), lifted one step so a flat Tk window still reads
as night rather than as black.

Contrast, measured (ratio against ground, then card, then card-hover):

    text        #EFEDF7  16.69 : 1  14.15  12.28     AAA everywhere
    dim         #C0C3D8  11.09       9.40   8.16     the second voice
    muted       #A4A9C2   8.32       7.05   6.12     times, eyebrows, facts
    faint       #70758E   4.26       3.61   3.13     RULES AND LABELS ONLY
    accent      #A597FF   7.80       6.61   5.74     iris
    accent-text #C2B9FF  10.75       9.12   7.91
    success     #5FDBA6  11.21       9.50   8.25
    danger      #FF6E7E   7.17       6.08   5.27
    cool        #4DB8FF   8.86       7.51   6.52     the listening lamp
    warning     #FFB84D  11.25       9.54   8.28     starting, working

    accent-on   #140F33 on the iris fill      7.39 : 1 (9.22 at its top)
    text        #EFEDF7 on accent-soft        9.38 : 1

MUTED is new with B+ and is the desk's --ink-3: the third voice every
time, eyebrow and fact is drawn in. It passes AA everywhere; FAINT stays
below 4.5 on purpose and is only ever a hairline label or a rule.

THE GLASS ON THE DESKTOP. A card here does not sit on the desk's floor; it
sits on whatever wallpaper or page is behind it, so its face is denser
than the desk's sheet (.84 there): GLASS_TOP / GLASS_BOT at GLASS_A_TOP /
GLASS_A_BOT. Measured worst case, a white page behind: the face's top
composites to #393E5A, where MUTED is 4.49 and DIM 5.99 — the lightest
surface words meet outside the desk.

Three rules the values alone cannot carry, and every surface has to:

1. **The accent never fills a surface, a card border or the bar.** It is
   the one soft light: the primary action on a surface, the focus ring,
   the proposal a second reading makes. Two iris buttons lit on one
   surface is the bug, not the taste question.
2. **The four lamps mean four things** — listening blue, recording red,
   working amber, idle grey with no light — on the status dot, on the
   shelf's head, on the key card's bead and on the desk's chip alike.
3. **Warning is NOT the accent any more.** LAMPLIGHT made them one colour
   ("your attention is wanted" and "the primary action" were the same
   sentence). B+ separates them: AMBER is the working lamp and a
   needs-you mark; iris is the action.

The five dot states are the desk's four lamps. The status dot is a 38 px
layered window sitting on the user's WALLPAPER, so its colours are
checked against #1A1A1A, the darkest ground it has to survive: listening
7.97, recording 5.84, locked 7.89, working 10.12, paused 5.65. Every pair
separates by light (dL* >= 8) or by hue, except recording/locked, which
are one hue by design — the 0.16 Hz breath is what separates them — and
paused, which separates from the rest by casting NO LIGHT at all.
"""
from __future__ import annotations

# ---------------------------------------------------------------- surfaces
BG = "#0b0d19"          # L*  3.9  the window, the card ground
PANE = "#121527"        # L*  7.3  a field, a strip, a secondary face
CARD = "#1a1e35"        # L* 12.0  a lifted face
CARD_HI = "#242944"     # L* 17.4  a face under the pointer
LINE = "#30365a"        # L* 23.7  hairline border
LINE_HI = "#454c78"     # L* 33.5  a border being interacted with
FOCUS = "#a597ff"       # the focus ring IS the accent — 7.80:1 on bg

# ------------------------------------------------------------------- text
FG = "#efedf7"          # 16.69:1 on bg — faintly lavender, never pure white
DIM = "#c0c3d8"         # 11.09:1 — help lines, context words
MUTED = "#a4a9c2"       # 8.32:1 — times, eyebrows, facts (the desk's ink-3)
FAINT = "#70758e"       # 4.26:1 — rules and micro-labels, never prose

# ----------------------------------------------------------------- accent
ACCENT = "#a597ff"      # iris: the proposal's edge, the lit button's body
ACCENT_HI = "#b9aeff"   # the lit button's top — 9.22:1 under ACCENT_ON
ACCENT_DOWN = "#9486ee"  # the lit button's foot, and pressed
ACCENT_SOFT = "#393961"  # L* 25.7 — iris at 22% on CARD: a proposal's pill
ACCENT_TEXT = "#c2b9ff"  # iris at TEXT weight — 9.12:1 on the card
ACCENT_ON = "#140f33"   # text ON the iris fill — 7.39:1

# -------------------------------------------------------------- semantics
GREEN = "#5fdba6"       # 9.50:1 on card — finished, fine, awake
AMBER = "#ffb84d"       # 9.54:1 — working, and worth a look
RED = "#ff6e7e"         # 6.08:1 — a problem; the misheard word's edge
RED_SOFT = "#482e44"    # the red at 20% on CARD — the pill under a misheard word
TEAL = "#5ed0c4"        # 8.82:1 — a history badge, not a state
VIOLET = "#d4a8f0"      # 8.32:1 — a history badge, and awake-while-dark

# The two the window palette does not own: the dot's red, which has to
# carry on a wallpaper, and the listening lamp, which is also the link.
RECORDING = "#ff5d6e"   # L* 61.8 — the dot while it is capturing
COOL = "#4db8ff"        # 7.51:1 on card — the listening lamp, links

# ------------------------------------------------------- derived surfaces
EDGE = "#1f2340"        # a secondary button — L* 14.8, between card and hi
EDGE_HI = "#2a3050"     # L* 20.8
EDGE_DOWN = "#161a2e"   # L*  9.8
STROKE = LINE

# The eight the dashboard used to spell out inline, kept on the ladder.
RULE = "#171a2e"        # a hairline on the ground: one step over PANE
ACCENT_EDGE = "#595490"  # the border of a selected row: iris at 45% on CARD
SIDE_IDLE = "#0f1222"    # an unselected row on the ground
SIDE_CARD = PANE         # the state card at the foot of a column
QUOTE_BG = CARD          # the quoted transcript — CARD exactly
QUOTE_EDGE = LINE
TILE_EDGE = "#525a88"    # a row under the pointer, just over LINE_HI
CHIP_BG = "#20243f"      # the square behind a row icon

# ------------------------------------------- the thirteen widget shades
BTN_OFF = "#171a2e"      # a disabled button: RULE — flat, one step over bg
BTN_OFF_EDGE = "#22263f"
CHIP_ON_EDGE = "#595490"  # a chip that is on: ACCENT_SOFT with a lit edge
CHIP_OFF = "#161a2e"      # a chip, a pill, a pair pill at rest: EDGE_DOWN
CHIP_OFF_EDGE = "#2a3050"  # EDGE_HI
CHIP_HOVER = "#1f2340"     # EDGE
CHIP_HOVER_EDGE = "#454c78"  # LINE_HI
TRACK_OFF = "#454c78"      # the switch's track when off — LINE_HI, so the
#                            knob (FG) reads as ON A TRACK rather than as a
#                            dot floating on the card
KEY_BG = "#1b2036"       # a key cap: the desk's --cap
KEY_EDGE = "#3a4068"
KEY_HI = "#252b47"       # a key cap under the pointer
THUMB = "#454c78"        # the scroller's thumb — LINE_HI

# The accent pre-composited over BG at four weights. Baked as flat fills
# because a blur to suggest a glow costs a frame; these cost nothing.
GLOW_05 = "#131424"
GLOW_10 = "#1a1b30"
GLOW_16 = "#24233e"
GLOW_24 = "#302e50"

# ------------------------------------------------------------- the glass
# A card on the desktop: the face, its frost light, its rim. The desk's
# own tokens (bplus.css) at the desktop's density — see the docstring for
# why denser. Alphas are 0..255.
GLASS_TOP = "#232948"    # the face at its top — lit from above
GLASS_BOT = "#191d33"    # and at its foot
GLASS_A_TOP = 230        # .90: MUTED 4.49 over a white page, the worst case
GLASS_A_BOT = 238        # .93
GLASS_FLAT = "#1e233e"   # the same face with nothing behind it (Tk, opaque)
FROST_A = 15             # .06: the face's own light, a pool at its top-left
RIM_HI_A = 66            # .26 white: the rim where the light hits it
RIM_MID_A = 20           # .08
RIM_LO_A = 6             # .025: far from the light
RIM_FOOT = (160, 150, 255)   # the rim at the bottom-right: light coming back
RIM_FOOT_A = 26          # .10
INNER_HI_A = 18          # .07 white: the inner line just under the top edge
QUIET_TOP_A = 26         # .10 white: a quiet button, top
QUIET_BOT_A = 14         # .055: and foot
QUIET_RIM_A = 26         # .10: its rim
QUIET_HI_A = 41          # .16: its top edge
DISC_A = 18              # .07 white: a round control's face (the X)
SLIP_A = 12              # .045 white: a row's own pane inside a card
WELL = (6, 8, 18)        # the writing well inside a sheet
WELL_A = 107             # .42
IRIS_GLOW = (135, 115, 255)  # the pool of light under the lit button
IRIS_GLOW_A = 128        # .50 — below it, never a ring
SPEC_A = 61              # .24 white: the lit button's top edge

# ---------------------------------------------------------- the four lamps
# The status lamp's four meanings (bplus.css --lamp-*), and the hot centre
# a lit lamp has. The dot, the shelf's head, the key card's bead and the
# move map's beads all draw them.
LAMP_LISTEN = COOL
LAMP_REC = RECORDING
LAMP_WRITE = AMBER
LAMP_IDLE = "#8a93a8"    # paused, model off: grey, and no light
LAMP_CORE = "#c9ecff"    # the listening lamp's hot centre

# ------------------------------------------------------------- the light
# The value ramp the release is built from, core outward. LAMPLIGHT's ran
# warm (white, incandescent, gold, a cool rim); B+'s is the desk's own
# light: white, a lavender white, the iris at text weight, the listening
# blue at the corona, night at the rim. Luminance falls stop by stop
# (Y 1.00 / .79 / .53 / .43 / .01), which is the order burst.py and
# reveal.py read them in. Never a saturated red anywhere: R/(R+G+B) >= 0.8
# is the single highest seizure-risk colour; the warmest stop here is the
# white core, at 0.33.
LIGHT_CORE = (255, 255, 255)
LIGHT_HOT = (231, 227, 255)      # #E7E3FF — a lavender white
LIGHT_MID = (194, 185, 255)      # ACCENT_TEXT: the iris at its own weight
LIGHT_ACCENT = (77, 184, 255)    # COOL: the corona — the listening lamp
LIGHT_DEEP = (12, 16, 34)        # #0C1022 — night at the rim


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
    "RED": RED, "RED_SOFT": RED_SOFT, "AMBER": AMBER, "GREEN": GREEN, "VIOLET": VIOLET,
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
# and casts it round itself as a glow. Measured against #1A1A1A:
# 7.97 / 5.84 / 7.89 / 10.12 / 5.65.
DOT_STATES = {
    "ready":     (LAMP_LISTEN, "#0f2438", False),   # listening — the blue lamp
    "recording": (LAMP_REC, "#3a1219", False),      # capturing now
    "locked":    ("#ff8d99", "#3a1219", True),      # latched, breathing
    "busy":      (LAMP_WRITE, "#33260f", False),    # working on what was said
    "paused":    (LAMP_IDLE, "#1e2130", False),     # idle, and see NO_HALO
}

# Paused is the ONE state with no halo. It is the only neutral in the set,
# and a grey glow on the wallpaper is a smudge rather than a light — so the
# state reads by the light's ABSENCE, which no colourblindness and no
# wallpaper can take away. Everything else casts its colour round itself.
NO_HALO = frozenset({"paused"})
