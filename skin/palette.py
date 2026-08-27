"""COBALT — the same blue this app has always been, brought into focus.

This is deliberately not a new identity. The lookup box (popup.py) and the
capture windows carry their own copies of the old palette as COLORREFs and
are not touched by the reskin, so a hue flip would have left the app half
recoloured, which is worse than either state. What was wrong with the old
palette was not its hue. It was measurable:

    bg #0d1017 L*4.68 and pane #10131a L*5.88 are 1.2 L* apart, which is
        below the threshold where two surfaces read as two surfaces
    accent #2d6cdf as text is 3.92:1 — FAILS WCAG AA
    white on that accent is 4.10:1 — FAILS AA, so every filled button in
        the dashboard was already illegible by the standard
    danger #e0352b is 4.27:1 — FAILS AA
    amber #e0a32b at 8.56:1 was the one semantic colour already right

So: same family, correct spacing, and every pair checked rather than
eyeballed. The elevation ladder is L* 6.6 / 10.2 / 13.7 / 18.4 / 24.3 /
31.0 — adjacent surfaces 3.5-4.7 apart, which is the band where a card
reads as lifted off its pane without anything looking milky.

Contrast, measured (ratio against bg, then against the highest surface):

    text    #e8ebf3   15.35 : 1  /  11.56 : 1     AAA everywhere
    dim     #a3abbc    7.94 : 1  /   5.98 : 1     AAA to s1, AA through s3
    faint   #747d8d    4.41 : 1  /   3.32 : 1     non-text only, by design
    accent-text #8fbeff 9.57 : 1 /   7.21 : 1     AAA on all four surfaces
    white on accent #1d6dd4        5.01 : 1       AA — the old one failed

FAINT is under 4.5 on purpose and is only ever used for hairline labels
and rules, never for anything a person has to read. The three semantics
(success/warning/danger) are all AA or better on every surface.

The industry band for dim text is 6-9:1 — Linear's muted is 6.13, GitHub's
6.15, Radix slate-11 is 9.06. 7.94 sits in the middle of that on purpose.
"""
from __future__ import annotations

# ---------------------------------------------------------------- surfaces
BG = "#11151b"          # L* 6.64  the window, the sidebar, the card ground
PANE = "#181c23"        # L* 10.15 a content pane on the window
CARD = "#1f232d"        # L* 13.73 a card face
CARD_HI = "#282d38"     # L* 18.42 a card face under the pointer
LINE = "#343a45"        # L* 24.28 hairline border
LINE_HI = "#434957"     # L* 30.99 a border that is being interacted with
FOCUS = "#646e7f"       # 3.56:1 on bg — a focus ring you can actually see

# ------------------------------------------------------------------- text
FG = "#e8ebf3"          # 15.35:1 on bg
DIM = "#a3abbc"         # 7.94:1
FAINT = "#747d8d"       # 4.41:1 — rules and micro-labels, never prose

# ----------------------------------------------------------------- accent
ACCENT = "#1d6dd4"      # white on it is 5.01:1, which finally passes AA
ACCENT_HI = "#3482eb"   # hover, and solid chips on a card (see the note)
ACCENT_DOWN = "#175bb4"
ACCENT_SOFT = "#122b4e"  # the accent at card weight, for selected states
ACCENT_TEXT = "#8fbeff"  # the accent at TEXT weight — 9.57:1, AAA
ACCENT_ON = "#ffffff"

# -------------------------------------------------------------- semantics
GREEN = "#67c986"       # 8.96:1 on bg
AMBER = "#f0b758"       # 10.13:1
RED = "#f87a7d"         # 7.04:1 — the old #e0352b was 4.27 and failed
TEAL = "#51c5d2"
VIOLET = "#c89ef7"

# ------------------------------------------------------- derived surfaces
EDGE = "#242932"        # a secondary button
EDGE_HI = "#2e3440"
EDGE_DOWN = "#1c212a"
STROKE = "#343a45"

# The eight the dashboard used to spell out inline, moved onto the ladder.
# Each one is now a step that exists in the ramp above rather than a shade
# picked to look right next to whatever it happened to sit beside.
RULE = "#1e232c"        # sidebar hairline: one step over PANE
ACCENT_EDGE = "#1e4176"  # the border of a selected row: over ACCENT_SOFT
SIDE_IDLE = "#1a1f27"   # an unselected sidebar row
SIDE_CARD = "#181c23"   # the sidebar's state card — PANE exactly
QUOTE_BG = "#1f232d"    # the quoted transcript — CARD exactly
QUOTE_EDGE = "#343a45"  # LINE
TILE_EDGE = "#3c434f"   # a row under the pointer, just over LINE_HI
CHIP_BG = "#212630"     # the square behind a row icon

# The accent pre-composited over BG at four weights. Baked as flat fills
# because a blur to suggest a glow costs a frame; these cost nothing.
GLOW_05 = "#121924"
GLOW_10 = "#121e2e"
GLOW_16 = "#132339"
GLOW_24 = "#142a47"

# ------------------------------------------------------------- the light
# The value ramp the burst is built from, core outward. Five stops, warm
# at the core and cool at the edge, because that is what hot things do and
# because a ramp that stays one hue reads as a UI element lit from inside
# rather than as light. Never a saturated red anywhere: R/(R+G+B) >= 0.8 is
# the single highest seizure-risk colour and every guideline gives it its
# own stricter threshold.
LIGHT_CORE = (255, 255, 255)
LIGHT_HOT = (255, 244, 214)      # #FFF4D6 — the classic incandescent stop
LIGHT_MID = (143, 190, 255)
LIGHT_ACCENT = (52, 130, 235)
LIGHT_DEEP = (18, 43, 78)


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
# nobody looked at.
UI_NAMES = {
    "BG": BG, "PANE": PANE, "CARD": CARD, "CARD_HI": CARD_HI, "LINE": LINE,
    "FG": FG, "DIM": DIM, "FAINT": FAINT,
    "ACCENT": ACCENT, "ACCENT_HI": ACCENT_HI, "ACCENT_DOWN": ACCENT_DOWN,
    "ACCENT_SOFT": ACCENT_SOFT, "ACCENT_TEXT": ACCENT_TEXT,
    "RED": RED, "AMBER": AMBER, "GREEN": GREEN, "VIOLET": VIOLET,
    "TEAL": TEAL, "EDGE": EDGE, "EDGE_HI": EDGE_HI, "EDGE_DOWN": EDGE_DOWN,
    "STROKE": STROKE,
    "RULE": RULE, "ACCENT_EDGE": ACCENT_EDGE, "SIDE_IDLE": SIDE_IDLE,
    "SIDE_CARD": SIDE_CARD, "QUOTE_BG": QUOTE_BG, "QUOTE_EDGE": QUOTE_EDGE,
    "TILE_EDGE": TILE_EDGE, "CHIP_BG": CHIP_BG,
}

# overlay.STATES is (fill, ring, pulses) and a test asserts that shape, so
# the dot's colours are given here in the same form rather than as a new
# structure the test would not recognise.
DOT_STATES = {
    "ready":     (ACCENT_HI, "#12233d", False),
    "recording": (RED, "#3b1416", False),
    "locked":    (RED, "#3b1416", True),
    "busy":      (AMBER, "#332404", False),
    "paused":    (FAINT, "#1b2029", False),
}
