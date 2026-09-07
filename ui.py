"""Rounded, anti-aliased surfaces for a toolkit that has neither.

Tk 8.6 cannot round a corner and cannot anti-alias one. It can show an
image, though, and Pillow — already a dependency, `make_icon.py` uses it —
can draw a rounded rectangle at four times the size and shrink it down.
So every card, pill, button and switch in the dashboard is a Canvas
holding one pre-rendered bitmap with ordinary Tk widgets placed on top of
it, the widget's own background set to the same flat colour as the middle
of that bitmap. The seam is invisible because there is nothing to see: the
label really is sitting on a solid `#161b25`, and the only rounded part is
the 14 px at each corner.

Two consequences worth knowing before changing anything here:

1. **Every size is cached.** `rounded()` is keyed on its arguments, so a
   hundred history rows of the same width and height share one bitmap and
   one decode. Asking for a hundred slightly different heights would not.
2. **A PhotoImage belongs to the interpreter that made it.** The cache is
   module-level, so a second `Tk()` in the same process (the test suite
   does this) must clear it first, or it hands out images the new
   interpreter has never heard of and Tk raises "image doesn't exist".

The palette is the old dashboard's, unchanged — the same greys, the same
blue. Only the geometry and the spacing moved.
"""
from __future__ import annotations

import math

import ctypes
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageTk

# ---------------------------------------------------------------- palette
BG          = "#0d1017"   # the window, and the sidebar on it
PANE        = "#10131a"   # the content pane      (the old window colour)
CARD        = "#161b25"   # a card face           (kept)
CARD_HI     = "#1b2130"   # a card face under the pointer
LINE        = "#232a36"   # hairline border       (kept)
FG          = "#e8ecf4"   # text                  (kept)
DIM         = "#8b97ad"   # secondary text        (kept)
FAINT       = "#5d6779"   # tertiary text         (kept)
ACCENT      = "#2d6cdf"   # (kept)
ACCENT_HI   = "#3d7cef"
ACCENT_DOWN = "#2559bd"
ACCENT_SOFT = "#1a2740"   # the accent at card weight, for selected states
ACCENT_TEXT = "#8fb2f5"   # the accent at text weight, which #2d6cdf is not
RED         = "#e0352b"   # (kept)
AMBER       = "#e0a32b"   # (kept)
GREEN       = "#33b877"
VIOLET      = "#8b6cf0"
TEAL        = "#2bb8c4"
EDGE        = "#1e2634"   # a secondary button
EDGE_HI     = "#273040"
EDGE_DOWN   = "#1a212d"
STROKE      = "#2a3242"

# The eight colours dashboard.py used to spell out inline. Their values
# here are exactly the literals it had, so nothing about the window
# changes by naming them — but a palette can now reach them, and a shade
# that lives in one place can no longer drift from the ramp it belongs to.
RULE        = "#1a202b"   # the hairline between the sidebar and the pane
ACCENT_EDGE = "#2b3f66"   # the border of a selected sidebar row
SIDE_IDLE   = "#141922"   # a sidebar row that is not selected
SIDE_CARD   = "#131822"   # the state card at the foot of the sidebar
QUOTE_BG    = "#1b2231"   # the quoted-transcript panel
QUOTE_EDGE  = "#2c3648"
TILE_EDGE   = "#2f3a4d"   # a tile or row under the pointer
CHIP_BG     = "#1c2432"   # the small square behind a row's icon

# Five names skin\palette.py already had and this module did not, so
# `repaint` was silently skipping them — it only writes over names that
# already exist here. Their values are the old palette's, like everything
# above: this whole block is the app with skin\ deleted.
LINE_HI     = "#2b3444"   # a border that is being interacted with
FOCUS       = "#5d6779"   # a focus ring, where the accent is not it
ACCENT_ON   = "#ffffff"   # text ON the accent fill
COOL        = "#8fb2f5"   # informational: a link, the listening dot
RECORDING   = "#e0352b"   # the dot while it is capturing

# The thirteen shades this file used to spell out INSIDE its own widget
# constructors — the disabled button, the chip's three faces, the switch's
# off track, the key cap, the scroller's thumb, the two pills. Every one of
# them was invisible to a repalette, so the filter chips and every key cap
# stayed on the old colours while the rest of the window changed. The
# literals are unchanged; only their address is.
BTN_OFF         = "#151a23"   # a disabled button's face
BTN_OFF_EDGE    = "#1e2531"
CHIP_ON_EDGE    = "#2f4d80"   # a chip that is on — ACCENT_SOFT plus an edge
CHIP_OFF        = "#151b26"   # a chip, a pill and a pair pill at rest
CHIP_OFF_EDGE   = "#222a36"
CHIP_HOVER      = "#1b2230"
CHIP_HOVER_EDGE = "#2c3648"
TRACK_OFF       = "#2a3242"   # the switch's track when it is off
KEY_BG          = "#1c2331"   # a key cap
KEY_EDGE        = "#303a4c"
KEY_HI          = "#243044"   # a key cap under the pointer
THUMB           = "#2b3444"   # the scroller's thumb

# --- SKIN -----------------------------------------------------------------
# One hook, and it has to be HERE rather than anywhere later: `from ui
# import CARD` binds the VALUE at import time, so a repaint that ran after
# this module finished executing would leave every already-imported name on
# the old colour. visual_qa.py reads these attributes at its own import and
# gets whatever this leaves behind, which is how the ask card is recoloured
# without a line of its own.
#
# Delete skin\ and the import fails, the except swallows it, and the
# palette above is what the app uses — which is exactly what it used before
# any of this existed.
try:
    import skin as _skin
    _skin.repaint(globals())
except Exception:
    pass
# --------------------------------------------------------------------------

def _gdi_face(name: str) -> tuple[bool, bool]:
    """(exists, holds Hebrew) for a font family, asked of GDI itself.

    Both halves are load-bearing. CreateFontW never fails — ask for a face
    that is not installed and it quietly hands back a default — so
    existence is checked by reading the face name back with GetTextFaceW.
    And Hebrew coverage is checked with GetGlyphIndicesW because the
    absence of it is invisible until it is on screen: "Segoe UI Variable"
    has no Hebrew at all, the per-word font fallback that papers over that
    BREAKS BIDI REORDERING, and every Hebrew word came out letter-reversed
    ("בדקתי" drawn as "יתבדק"). Measured 2026-08-20; the probe and the
    screenshots are the reason the transcript font is picked this way.
    """
    gdi, user = ctypes.windll.gdi32, ctypes.windll.user32
    hdc = user.GetDC(0)
    font = gdi.CreateFontW(-24, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 0, 0, name)
    old = gdi.SelectObject(hdc, font)
    try:
        face = ctypes.create_unicode_buffer(64)
        gdi.GetTextFaceW(hdc, 64, face)
        exists = face.value.lower() == name.lower()
        indices = (ctypes.c_ushort * 3)()
        GGI_MARK_NONEXISTING_GLYPHS = 1
        gdi.GetGlyphIndicesW(hdc, "אבש", 3, indices,
                             GGI_MARK_NONEXISTING_GLYPHS)
        hebrew = all(i != 0xFFFF for i in indices)
        return exists, hebrew
    finally:
        gdi.SelectObject(hdc, old)
        gdi.DeleteObject(font)
        user.ReleaseDC(0, hdc)


def pick_face(candidates: list[str], hebrew: bool = True) -> str:
    """The first candidate that is installed (and can spell Hebrew, when
    the text it will carry needs it). Segoe UI is the floor: always
    present, full Hebrew, proven to reorder correctly."""
    for name in candidates:
        found, covers = _gdi_face(name)
        if found and (covers or not hebrew):
            return name
    return "Segoe UI"


# FIRST, hand GDI the fonts, and only then ask it what it has. Being
# registered under HKCU is a promise to the next logon, not an answer to
# CreateFontW in this process — measured 2026-09-06, a machine with all
# four Rubik files installed and past a reboot still gave Arial back for
# the family "Rubik", and the whole app had been drawing in Segoe UI
# without a word about it. fonts.load() is idempotent, private to this
# process, and never raises; see fonts.py for the whole argument.
try:
    import fonts as _fonts
    _fonts.load()
except Exception:
    pass

# Rubik first — a face designed for Hebrew and Latin together, installed
# per-user by the dashboard's setup (see README). Every fallback ends at
# Segoe UI, which ships with Windows and holds full Hebrew. NEVER put a
# "Segoe UI Variable" cut here: no Hebrew glyphs, and the fallback
# scrambles words (see _gdi_face).
DISPLAY = pick_face(["Rubik"])                  # headings, numbers, the state
TEXT    = pick_face(["Rubik"])                  # transcripts
UI      = pick_face(["Rubik"])                  # buttons, labels, meta
MEDIUM  = pick_face(["Rubik Medium"], hebrew=False)   # small caps headers
# The icon font that ships with Windows 11. Every glyph used in the
# dashboard is listed in ICON below rather than inline, so a tofu box has
# one place to be fixed.
ICONS   = "Segoe Fluent Icons"

# ------------------------------------------------------------- type scale
#
# THE SIZES ARE POINTS AND THE DESIGN IS IN PIXELS, so every entry below
# carries both. Tk and `draw_text(pt=...)` take points; `_px()` turns one
# into the other at this process's DPI, which is 96 here, so px = pt * 4/3.
#
# Why they all moved up. Rubik draws Hebrew about 13% SMALLER than Segoe UI
# at the same nominal size — measured through this file's own DrawTextW
# path, letter height 14 px against Segoe's 16 at a nominal 15 — because
# Hebrew has no ascenders or descenders and its whole legibility budget is
# how much of the em it uses. Swapping the face without touching the sizes
# makes the app smaller and harder to read, which is not what a redesign
# should feel like. Every size is therefore **+2 px on the Segoe-era
# number**, rounded to the nearest whole point because that is the only
# granularity Tk offers down here.
#
# And Rubik's LINE BOX is 15% taller than Segoe's at the same size (23 px
# against 20 at a nominal 15), so a row built to the old height crops the
# descender of a ק. The row heights below are +20% on the old ones, which
# absorbs both the taller box and the bigger type.
PT_TITLE = 20      # 26.7 px — the one big line on a screen
PT_HERO  = 15      # 20 px   — a state, a number that is the point of a tile
PT_WORDS = 13      # 17.3 px — HIS OWN WORDS: a transcript, a proposal
PT_BODY  = 12      # 16 px   — body, buttons, every ordinary UI line
PT_LABEL = 10      # 13.3 px — a Hebrew label, a meta line
PT_CAPS  = 9       # 12 px   — LATIN SMALL CAPS, an eyebrow, a micro-label

# Row heights, +20% on what they were, and the radii that keep a pill a
# pill. A name rather than a literal because widgets.py and the window both
# have to land on the same rhythm.
PILL_H   = 36      # a chip, a pill, a pair pill      (was 30)
BTN_H    = 40      # a button                         (was 36)
CAP_H    = 40      # a key cap                        (was 34)
SWITCH_W, SWITCH_H = 46, 26                          # (was 42, 24)
ROW_H    = 44      # one line in a list               (was 36)

ICON = {
    "overview": "\ue80f", "history": "\ue81c", "keys": "\ue765",
    "settings": "\ue713", "mic": "\ue720", "play": "\ue768",
    "pause": "\ue769", "stop": "\ue71a", "copy": "\ue8c8",
    "search": "\ue721", "globe": "\ue774", "link": "\ue71b",
    "translate": "\ue8c1", "punctuate": "\ue8bd", "learned": "\ue90f",
    "error": "\uea39", "discarded": "\ue74d", "file": "\ue8a5",
    "page": "\ue7c3", "folder": "\ue8b7", "engine": "\ue9d9",
    "version": "\ue895", "review": "\ue8fb",
    "awake": "\ue708", "power": "\ue7e8", "check": "\ue73e",
    "notify": "\uea8f",     # the bell (Ringer). \ue7e7, the codepoint the
                            # plan named, renders as a message box here \u2014
                            # rendered side by side 2026-09-04 to check
}

_cache: dict = {}
_FONTS: dict = {}
_CLAMPS: dict = {}


def forget_images() -> None:
    """Drop every cached bitmap and font.

    Only a second `Tk()` in one process needs this — see the note at the
    top of the file. A `tkinter.font.Font` belongs to its interpreter the
    same way a PhotoImage does, and measuring with a dead one raises
    "application has been destroyed" rather than returning a width.
    """
    _cache.clear()
    _FONTS.clear()
    _CLAMPS.clear()


def rounded_pil(w: int, h: int, radius: int, fill: str, bg: str,
                border: str | None = None) -> Image.Image:
    """One rounded rectangle as a PIL image: the drawing, and nothing else.

    Drawn at 4x and resized with LANCZOS. Pillow's `rounded_rectangle` has
    no anti-aliasing of its own, and a hard-edged 14 px corner on a dark
    background is more obviously wrong than a square one.

    Split out of rounded() for callers that are not this interpreter.
    visual_qa.py stands up a fresh Tk on its own thread for every press,
    and a PhotoImage — cached or not — belongs to the interpreter that
    made it, so the shape it needs is this one: pixels it can wrap with a
    master of its own. Anything drawing inside the dashboard wants
    rounded() instead, cache and all.
    """
    s = 4
    w, h = max(1, w), max(1, h)
    # A big face — a card the height of a screen — is drawn from a SMALL
    # one. Everything that needs anti-aliasing is in the corners; the
    # straight runs between them downsample to one uniform column or row,
    # so a tile holding the four corners and a slice of each edge, cut and
    # stretched, is the same picture pixel for pixel. Measured 2026-09-01:
    # the settings screen's eighteen 680 px faces cost 0.96 s drawn whole
    # at 4x and LANCZOS'd, which was most of the wait for that screen.
    corner = radius + 2
    tile = 2 * corner + 2
    if w > tile + 8 and h > tile + 8:
        small = rounded_pil(tile, tile, radius, fill, bg, border)
        image = Image.new("RGB", (w, h), fill)
        c = corner
        for box, at in (((0, 0, c, c), (0, 0)),
                        ((tile - c, 0, tile, c), (w - c, 0)),
                        ((0, tile - c, c, tile), (0, h - c)),
                        ((tile - c, tile - c, tile, tile), (w - c, h - c))):
            image.paste(small.crop(box), at)
        top = small.crop((c, 0, c + 1, c)).resize((w - 2 * c, c))
        bottom = small.crop((c, tile - c, c + 1, tile)).resize((w - 2 * c, c))
        left = small.crop((0, c, c, c + 1)).resize((c, h - 2 * c))
        right = small.crop((tile - c, c, tile, c + 1)).resize((c, h - 2 * c))
        image.paste(top, (c, 0))
        image.paste(bottom, (c, h - c))
        image.paste(left, (0, c))
        image.paste(right, (w - c, c))
        return image
    image = Image.new("RGB", (w * s, h * s), bg)
    ImageDraw.Draw(image).rounded_rectangle(
        (0, 0, w * s - 1, h * s - 1), radius=radius * s, fill=fill,
        outline=border, width=s if border else 0)
    return image.resize((w, h), Image.LANCZOS)


def rounded(w: int, h: int, radius: int, fill: str, bg: str,
            border: str | None = None) -> ImageTk.PhotoImage:
    """rounded_pil(), cached and wrapped for THIS interpreter's Tk."""
    key = ("rect", w, h, radius, fill, bg, border)
    if key not in _cache:
        _cache[key] = ImageTk.PhotoImage(
            rounded_pil(w, h, radius, fill, bg, border))
    return _cache[key]


def lamp(size: int, colour: str, bg: str,
         glow: float = 0.45) -> ImageTk.PhotoImage:
    """The status dot, with a halo around it.

    The old dot was a 12 px flat circle drawn with `create_oval`, which is
    both aliased and quiet. This one is the same circle with a blurred
    copy of itself underneath, so RECORDING red is visible out of the
    corner of an eye rather than only when looked at.

    `glow` is how bright the halo is (0..1) — the breathing animation
    cycles it. It is quantised before it becomes a cache key, so a breath
    is a dozen shared bitmaps, not a new image per frame. The halo circle
    stops at 78% of the bitmap and the blur at 11%, measured so the fade
    reaches the background INSIDE the image — the first version bled past
    the edge and was clipped into a visible square.
    """
    glow = max(0.0, min(1.0, round(glow * 20) / 20))
    key = ("lamp", size, colour, bg, glow)
    if key not in _cache:
        s = 4
        px = size * s
        halo = Image.new("RGB", (px, px), bg)
        ImageDraw.Draw(halo).ellipse((px * .22, px * .22, px * .78, px * .78),
                                     fill=colour)
        image = Image.blend(Image.new("RGB", (px, px), bg),
                            halo.filter(ImageFilter.GaussianBlur(px * .11)),
                            glow)
        centre, r = px / 2, px * 0.21
        ImageDraw.Draw(image).ellipse(
            (centre - r, centre - r, centre + r, centre + r), fill=colour)
        _cache[key] = ImageTk.PhotoImage(
            image.resize((size, size), Image.LANCZOS))
    return _cache[key]


def _icon_art(path, size: int):
    """The right CUT of the mark for the size being asked for.

    icon.png is the FULL cut — the lamp with its glow and both arcs — and
    below 48 px those are a smudge and two grey pixels; that is the whole
    reason make_icon.py draws two cuts in the first place. The .ico beside
    it already holds the small cut at 16/24/32, so a small badge takes its
    frame from there and only the big ones read the .png. Pillow selects an
    ICO frame by assigning `size` before the pixels are loaded.
    """
    if size < 48:
        ico = Path(path).with_suffix(".ico")
        try:
            art = Image.open(ico)
            for frame in sorted(art.ico.sizes()):
                if frame[0] >= size:
                    art.size = frame
                    break
            return art.convert("RGB")
        except Exception:
            pass                            # no .ico: the .png still works
    return Image.open(path).convert("RGB")


def icon_bitmap(path, size: int, bg: str) -> ImageTk.PhotoImage | None:
    """The app icon, with its corners rounded to match everything else."""
    key = ("app-icon", str(path), size, bg)
    if key not in _cache:
        try:
            art = _icon_art(path, size).resize(
                (size * 4, size * 4), Image.LANCZOS)
        except Exception:
            return None                    # icon.png missing: skip the badge
        mask = Image.new("L", art.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, art.size[0] - 1, art.size[1] - 1), radius=size, fill=255)
        out = Image.new("RGB", art.size, bg)
        out.paste(art, (0, 0), mask)
        _cache[key] = ImageTk.PhotoImage(
            out.resize((size, size), Image.LANCZOS))
    return _cache[key]


class Card(tk.Canvas):
    """A rounded panel with a frame inside it to put widgets in.

    `body` is an ordinary Frame, so everything packs and places into it
    the way it always did. Its background is the card's fill, which is why
    labels on it need `bg=CARD` and not the window colour.
    """

    def __init__(self, parent, w: int, h: int, *, radius: int = 14,
                 fill: str = CARD, bg: str = PANE, border: str | None = LINE,
                 pad: int = 16):
        super().__init__(parent, width=w, height=h, bg=bg,
                         highlightthickness=0, bd=0)
        self.w, self.h, self.fill = w, h, fill
        self._radius, self._ground, self._border, self._pad = \
            radius, bg, border, pad
        self.face_item = self.create_image(
            0, 0, anchor="nw", image=rounded(w, h, radius, fill, bg, border))
        self.body = tk.Frame(self, bg=fill)
        self._body_item = self.create_window(
            pad, pad, anchor="nw", window=self.body,
            width=w - 2 * pad, height=h - 2 * pad)

    def resize(self, h: int) -> None:
        """A new height: the face is redrawn and the body follows. A
        card as tall as its rows (the home's pile) changes height every
        time a row arrives or is answered."""
        h = max(2 * self._pad + 1, int(h))
        self.h = h
        self.configure(height=h)
        self.face(rounded(self.w, h, self._radius, self.fill, self._ground,
                          self._border))
        self.itemconfig(self._body_item, height=h - 2 * self._pad)

    def face(self, image) -> None:
        """Swap the background bitmap — how a row lights up under the
        pointer without rebuilding anything on top of it."""
        self.itemconfig(self.face_item, image=image)


class Button(tk.Canvas):
    """A pill with three cached faces: idle, hovered, pressed.

    Not a `tk.Button` with a flat relief, which is what the old window
    used: that has square corners, no hover state, and greys only its
    LABEL when disabled — so a disabled Start button kept the accent
    colour and went on looking like the thing to click.
    """

    def __init__(self, parent, text: str, command=None, *, w: int = 116,
                 h: int = BTN_H, radius: int = 10, bg: str = CARD,
                 primary: bool = False, quiet: bool = False,
                 icon: str | None = None, fg: str | None = None):
        super().__init__(parent, width=w, height=h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        # NOT self._w / self._h: tkinter keeps the widget's own Tcl
        # path name in Misc._w, and overwriting it points every later
        # call at a command named "104".
        self._bg, self._width, self._height = bg, w, h
        self._radius = radius
        self._command = command
        self._enabled = True
        self._dip = 0
        self._icon_item = None
        self._primary = primary
        self._quiet = quiet
        self._fg = fg
        self._faces = self._build_faces(primary, quiet)
        self._colour = self._face_colour(primary, quiet, fg)
        self._image = self.create_image(0, 0, anchor="nw",
                                        image=self._faces[0])
        # The icon sits to the left of the label, and both are centred as
        # one block: measuring the label is what keeps a two-word button
        # from putting its icon on top of its own text.
        offset = 0
        if icon:
            offset = 9
            self._icon_item = self.create_text(0, h / 2, text=icon,
                                               font=(ICONS, PT_BODY),
                                               fill=self._colour)
        self._label = self.create_text(w / 2 + offset, h / 2 + 1, text=text,
                                       font=(UI, PT_BODY),
                                       fill=self._colour)
        if icon:
            self.update_idletasks()
            left = self.bbox(self._label)[0]
            self.coords(self._icon_item, left - 12, h / 2)
        self.bind("<Enter>", lambda _e: self._show(1))
        self.bind("<Leave>", lambda _e: self._show(0))
        self.bind("<Button-1>", lambda _e: self._show(2))
        self.bind("<ButtonRelease-1>", self._released)

    def _build_faces(self, primary: bool, quiet: bool) -> list:
        if primary:
            fills = (ACCENT, ACCENT_HI, ACCENT_DOWN)
            border = None
        else:
            # A quiet button is the same shape at rest as a loud one, just
            # emptier. Without the outline it reads as a line of text that
            # happens to have an icon, and nothing says it can be clicked.
            fills = ((self._bg, EDGE, EDGE_DOWN) if quiet
                     else (EDGE, EDGE_HI, EDGE_DOWN))
            border = STROKE
        return [rounded(self._width, self._height, self._radius, fill,
                        self._bg, border) for fill in fills]

    @staticmethod
    def _face_colour(primary: bool, quiet: bool, fg: str | None) -> str:
        if primary:
            return ACCENT_ON
        return fg or (DIM if quiet else FG)

    def _show(self, index: int) -> None:
        if not self._enabled:
            return
        self.itemconfig(self._image, image=self._faces[index])
        # The label dips one pixel while the button is down — the whole
        # difference between "the colour changed" and "I pressed it".
        dip = 1 if index == 2 else 0
        if dip != self._dip:
            for item in (self._label, self._icon_item):
                if item is not None:
                    self.move(item, 0, dip - self._dip)
            self._dip = dip

    def _released(self, _event) -> None:
        self._show(1)
        if self._enabled and self._command:
            self._command()

    def configure_text(self, text: str) -> None:
        self.itemconfig(self._label, text=text)

    def enable(self, on: bool) -> None:
        """Disabled means the whole pill goes flat, not just its label."""
        self._enabled = on
        self.config(cursor="hand2" if on else "arrow")
        if on:
            self.itemconfig(self._image, image=self._faces[0])
        else:
            self.itemconfig(self._image,
                            image=rounded(self._width, self._height,
                                          self._radius, BTN_OFF,
                                          self._bg, BTN_OFF_EDGE))
        colour = self._colour if on else FAINT
        self.itemconfig(self._label, fill=colour)
        if self._icon_item is not None:
            self.itemconfig(self._icon_item, fill=colour)


class Chip(tk.Canvas):
    """A pill that is either on or off: the history filters, and the pairs
    of words the vocabulary learned."""

    def __init__(self, parent, text: str, command=None, *, bg: str = PANE,
                 active: bool = False, font_size: int = PT_LABEL):
        width = 26 + _text_width(text, font_size)
        super().__init__(parent, width=width, height=PILL_H, bg=bg,
                         highlightthickness=0, bd=0,
                         cursor="hand2" if command else "arrow")
        self._on = rounded(width, PILL_H, PILL_H // 2, ACCENT_SOFT, bg,
                           CHIP_ON_EDGE)
        self._off = rounded(width, PILL_H, PILL_H // 2, CHIP_OFF, bg,
                            CHIP_OFF_EDGE)
        self._hover = rounded(width, PILL_H, PILL_H // 2, CHIP_HOVER,
                              bg, CHIP_HOVER_EDGE)
        self._active = active
        self._image = self.create_image(0, 0, anchor="nw", image=self._off)
        self._text = self.create_text(width / 2, PILL_H / 2 + 1,
                                      text=text,
                                      font=(UI, font_size), fill=DIM)
        if command:
            self.bind("<Button-1>", lambda _e: command())
            self.bind("<Enter>", lambda _e: self._flip(True))
            self.bind("<Leave>", lambda _e: self._flip(False))
        self.set(active)

    def _flip(self, over: bool) -> None:
        if not self._active:
            self.itemconfig(self._image,
                            image=self._hover if over else self._off)

    def set(self, on: bool) -> None:
        self._active = bool(on)
        self.itemconfig(self._image, image=self._on if on else self._off)
        self.itemconfig(self._text, fill=ACCENT_TEXT if on else DIM)


def _knob_box(on: bool) -> tuple[float, float, float, float]:
    """The switch's knob, derived from the track rather than typed in.

    It used to be four literals per side, which meant the track could not
    grow without the knob sliding off the end of it.
    """
    inset = 4
    d = SWITCH_H - inset * 2
    x = SWITCH_W - inset - d if on else inset
    return (x, inset, x + d, inset + d)


class Switch(tk.Canvas):
    """A toggle. A Checkbutton with a tick in a square box is the single
    most dated thing that was on the old window."""

    def __init__(self, parent, value: bool = False, command=None,
                 bg: str = CARD):
        super().__init__(parent, width=SWITCH_W, height=SWITCH_H, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._on = rounded(SWITCH_W, SWITCH_H, SWITCH_H // 2, ACCENT, bg)
        self._off = rounded(SWITCH_W, SWITCH_H, SWITCH_H // 2, TRACK_OFF,
                            bg)
        self._image = self.create_image(0, 0, anchor="nw", image=self._off)
        self._knob = self.create_oval(*_knob_box(False), fill=FG, width=0)
        self._value = value
        self._command = command
        self.bind("<Button-1>", lambda _e: self.toggle())
        self.set(value)

    def set(self, on: bool) -> None:
        """Move the knob without telling anyone — for repainting from a
        status poll, which must not look like the user clicked it."""
        self._value = bool(on)
        self.itemconfig(self._image, image=self._on if on else self._off)
        self.coords(self._knob, *_knob_box(on))

    def get(self) -> bool:
        return self._value

    def toggle(self) -> None:
        self.set(not self._value)
        if self._command:
            self._command(self._value)


class Dropdown(tk.Canvas):
    """A closed menu: the current choice on a pill, the choices under it
    when clicked.

    The list is a borderless Toplevel in this palette, not a
    ttk.Combobox — that is a native light-grey control with a white
    list, and one of those on this window undoes the whole exercise. It
    closes on a pick, on Escape, and when the focus goes anywhere else.
    """

    def __init__(self, parent, options, value, command=None, *,
                 bg: str = CARD, w: int = 236, h: int = 30):
        super().__init__(parent, width=w, height=h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        # NOT self._options and NOT self._w / self._h: tkinter's Misc keeps
        # its option parser and the widget's own Tcl path name under those
        # names, and shadowing either breaks every later call.
        self._choices = [(v, str(label)) for v, label in options]
        self._command = command
        self._width, self._height = w, h
        self._idle = rounded(w, h, 9, EDGE, bg, STROKE)
        self._hover = rounded(w, h, 9, EDGE_HI, bg, ACCENT)
        self._image = self.create_image(0, 0, anchor="nw", image=self._idle)
        self._label = self.create_text(12, h / 2 + 1, text="", anchor="w",
                                       font=(UI, PT_BODY), fill=FG)
        self.create_text(w - 12, h / 2, text="▾", anchor="e",
                         font=(UI, PT_BODY), fill=DIM)
        self._popup = None
        self._value = None
        self.set(value)
        self.bind("<Enter>", lambda _e: self.itemconfig(self._image,
                                                        image=self._hover))
        self.bind("<Leave>", lambda _e: self.itemconfig(self._image,
                                                        image=self._idle))
        self.bind("<Button-1>", lambda _e: self.open())

    def label_for(self, value) -> str:
        for candidate, label in self._choices:
            if candidate == value:
                return label
        return str(value)

    def set(self, value) -> None:
        """Show `value` without telling anyone — for a repaint."""
        self._value = value
        text, _lines = clamp(self.label_for(value), UI, PT_BODY,
                             self._width - 40, 1)
        self.itemconfig(self._label, text=text)

    def get(self):
        return self._value

    def open(self) -> None:
        if self._popup is not None:
            self.close()
            return
        top = tk.Toplevel(self)
        top.overrideredirect(True)
        try:
            top.attributes("-topmost", True)
        except tk.TclError:
            pass
        top.configure(bg=STROKE)
        inner = tk.Frame(top, bg=CARD)
        inner.pack(padx=1, pady=1, fill="both")
        for value, label in self._choices:
            row = tk.Label(inner, text=label, bg=CARD,
                           fg=ACCENT_TEXT if value == self._value else FG,
                           font=(UI, PT_BODY), anchor="w", padx=12, pady=6,
                           cursor="hand2")
            row.pack(fill="x")
            row.bind("<Enter>", lambda _e, r=row: r.configure(bg=CARD_HI))
            row.bind("<Leave>", lambda _e, r=row: r.configure(bg=CARD))
            row.bind("<Button-1>", lambda _e, v=value: self._pick(v))
        top.update_idletasks()
        width = max(self._width, inner.winfo_reqwidth() + 2)
        height = inner.winfo_reqheight() + 2
        x, y = self.winfo_rootx(), self.winfo_rooty() + self._height + 2
        top.geometry(f"{width}x{height}+{x}+{y}")
        top.bind("<Escape>", lambda _e: self.close())
        top.bind("<FocusOut>", lambda _e: self.close())
        self._popup = top
        top.focus_force()

    def _pick(self, value) -> None:
        self.close()
        if value == self._value:
            return
        self.set(value)
        if self._command:
            self._command(value)

    def close(self) -> None:
        popup, self._popup = self._popup, None
        if popup is not None:
            try:
                popup.destroy()
            except tk.TclError:
                pass


class Field(tk.Canvas):
    """One line of type in this palette: a rounded face with a borderless
    Entry sitting flat on the middle of it.

    A bare `tk.Entry` is a hard rectangle with a one-pixel highlight, and
    beside a Switch, a Dropdown and a Button — every one of them a cached
    Pillow face with a 9 px radius — it is the only square thing left in
    the window. The owner said so of the settings tabs on 2026-09-07:
    "the boxes are square in everything that is not in General, and it is
    not pretty". So a field is built the way those three are: three faces
    cached by `rounded`, swapped on hover and on focus, and no widget
    border anywhere.

    ONLY THE BORDER DIFFERS BETWEEN THE THREE FACES. The Entry paints its
    own rectangle in `EDGE` and knows nothing about the face under it, so
    a hover state that changed the FILL would show as a rectangle of the
    old colour exactly where the Entry sits — the very shape this class
    exists to hide. Hover and focus move the outline: STROKE, LINE_HI,
    ACCENT.

    `disabledbackground` and `readonlybackground` are set next to `bg`
    because `bg` is only the NORMAL state: Tk repaints a disabled Entry in
    the PLATFORM's colours, so a dark field goes white the instant it is
    disabled. This app has paid for that once already (AGENTS.md), on the
    ask card, and it was found in a screenshot because nothing asserts
    colour.

    The pointer is asked for with `winfo_containing` rather than read off
    the event, because an embedded Entry is a window of its own: moving
    the mouse from the face onto the Entry raises Leave on the canvas, and
    a face swapped on that alone flickers under a stationary hand.
    """

    def __init__(self, parent, value: str = "", *, w: int = 150,
                 h: int = 30, radius: int = 9, bg: str = CARD,
                 justify: str = "right", icon: str | None = None,
                 placeholder: str = "", pt: int = PT_BODY, pad: int = 11,
                 right: int = 0, command=None):
        super().__init__(parent, width=w, height=h, bg=bg,
                         highlightthickness=0, bd=0)
        # NOT self._w / self._h: tkinter keeps the widget's own Tcl path
        # name in Misc._w (ui.Button says the same, and for the same bug).
        self._width, self._height = w, h
        self._faces = [rounded(w, h, radius, EDGE, bg, edge)
                       for edge in (STROKE, LINE_HI, ACCENT)]
        self._image = self.create_image(0, 0, anchor="nw",
                                        image=self._faces[0])
        self._focused = False
        self._over = False
        self._command = command
        left = pad
        if icon:
            self.create_text(pad, h / 2, text=icon, anchor="w",
                             font=(ICONS, pt), fill=FAINT)
            left = pad + 22
        inner = max(24, w - left - pad - right)
        self.entry = tk.Entry(
            self, bg=EDGE, fg=FG, bd=0, highlightthickness=0,
            font=(UI, pt), justify=justify, insertbackground=ACCENT,
            selectbackground=ACCENT_SOFT, selectforeground=FG,
            disabledbackground=EDGE, disabledforeground=FAINT,
            readonlybackground=EDGE)
        self.entry.insert(0, str(value))
        self.create_window(left, h / 2 + 1, window=self.entry, anchor="w",
                           width=inner, height=min(h - 8, 4 * pt // 3 + 10))
        self._hint = None
        if placeholder:
            self._hint = self.create_text(left + 2, h / 2 + 1, anchor="w",
                                          text=placeholder, fill=FAINT,
                                          font=(UI, PT_LABEL))
        self._show_hint()
        for widget in (self, self.entry):
            widget.bind("<Enter>", self._entered, add="+")
            widget.bind("<Leave>", self._left, add="+")
        self.entry.bind("<FocusIn>", self._took, add="+")
        self.entry.bind("<FocusOut>", self._gave, add="+")
        self.entry.bind("<KeyRelease>", self._typed, add="+")
        # A click anywhere on the face is a click in the field.
        self.bind("<Button-1>", lambda _e: self.entry.focus_set())

    # -- the face

    def _paint(self) -> None:
        index = 2 if self._focused else (1 if self._over else 0)
        self.itemconfig(self._image, image=self._faces[index])

    def _entered(self, _event=None) -> None:
        self._over = True
        self._paint()

    def _left(self, _event=None) -> None:
        try:
            under = self.winfo_containing(self.winfo_pointerx(),
                                          self.winfo_pointery())
        except tk.TclError:
            under = None
        if under in (self, self.entry):
            return
        self._over = False
        self._paint()

    def _took(self, _event=None) -> None:
        self._focused = True
        self._paint()
        self._show_hint()

    def _gave(self, _event=None) -> None:
        self._focused = False
        self._paint()
        self._show_hint()

    def _typed(self, _event=None) -> None:
        self._show_hint()
        if self._command:
            self._command(self.get())

    def _show_hint(self) -> None:
        if self._hint is None:
            return
        blank = not self.entry.get() and not self._focused
        self.itemconfigure(self._hint,
                           state="normal" if blank else "hidden")

    # -- the value. `set` never tells anyone, the way Dropdown.set does
    #    not: it is what a repaint calls.

    def get(self) -> str:
        return self.entry.get()

    def set(self, value) -> None:
        self.entry.delete(0, "end")
        self.entry.insert(0, "" if value is None else str(value))
        self._show_hint()

    def take_focus(self) -> None:
        self.entry.focus_set()

    def bind_entry(self, sequence: str, func) -> None:
        """Bind on the Entry rather than the canvas — Return and FocusOut
        happen to the widget that has the keyboard, not to its face."""
        self.entry.bind(sequence, func, add="+")


class KeyCap(tk.Canvas):
    """What a hotkey should look like: a key. The old window showed them
    as grey rectangles identical to every other button, which is why
    "Right Ctrl" and "Start" were the same object to the eye."""

    def __init__(self, parent, text: str, command=None, *, bg: str = CARD,
                 w: int = 122, h: int = CAP_H):
        super().__init__(parent, width=w, height=h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._idle = rounded(w, h, 9, KEY_BG, bg, KEY_EDGE)
        self._hover = rounded(w, h, 9, KEY_HI, bg, ACCENT)
        self._image = self.create_image(0, 0, anchor="nw", image=self._idle)
        self._label = self.create_text(w / 2, h / 2, text="",
                                       font=(UI, PT_BODY))
        self.set(text)
        self.bind("<Enter>",
                  lambda _e: self.itemconfig(self._image, image=self._hover))
        self.bind("<Leave>",
                  lambda _e: self.itemconfig(self._image, image=self._idle))
        if command:
            self.bind("<Button-1>", lambda _e: command())

    def set(self, text: str) -> None:
        """The binding on the cap, at the largest size that FITS it.

        A cap is placed on a grid and its width is the caller's; the label
        is a binding whose length nobody chooses ("Win+Shift+S" is four
        times "F8"). Type went up 2 px across the app when the face became
        Rubik, and a label that overruns its cap does not clip — a Canvas
        text item just draws past the bitmap and lands on whatever is
        beside it. So the size steps down until the string is inside the
        cap, which is the same trick `clamp()` plays for a paragraph.
        """
        off = text.lower() in ("", "off")
        shown = text or "off"
        size = PT_BODY
        room = self.winfo_reqwidth() - 16
        while size > PT_CAPS - 2 and _text_width(shown, size) > room:
            size -= 1
        self.itemconfig(self._label, text=shown,
                        font=(UI, size) if off else (UI, size, "bold"),
                        fill=FAINT if off else FG)


SCROLL_STEP = 16          # one wheel unit, in pixels
SCROLL_UNITS = 3          # units per notch: 48 px, about one row

RAIL_PAINT = 6            # the rail the thumb is DRAWN on
RAIL_HIT = 14             # ...and the width a hand may grab it by
THUMB_W = 4               # the thumb itself, unchanged
THUMB_MIN = 36            # the shortest it is allowed to get
GUTTER = 10               # the strip of itself the canvas keeps clear to
                          # the right of everything packed into it. Every
                          # screen already left it — each one asks for a
                          # page ten pixels wider than its own rows — and
                          # since 2026-09-07 the canvas holds the content
                          # to it instead of trusting whoever calls
TOP_DISC = GUTTER * 2     # the "back to the top" button: half of it on
                          # that strip and half on the rail, which between
                          # them are the only 20 px of a page with no
                          # content in them — the thumb shares the rail
                          # and stops above it, see TOP_FOOT
TOP_INSET = 8             # its air — under it, and between it and the
                          # lowest the thumb may come
TOP_FOOT = TOP_DISC + TOP_INSET * 2   # what the rail gives up to it


def _wheel_to_the_pointer(event):
    """ONE wheel binding for the whole interpreter, routed by the pointer.

    The wheel used to reach a Scroller only where `bind_wheel` had walked,
    and it walks ONCE, at build time. Everything drawn afterwards was a
    dead zone: the owner's report on 2026-09-07 was the three "rest of the
    day" rows, which `dashboard._paint_rest` destroys and rebuilds every
    time the log changes, so their bindings were gone the first time a
    dictation landed. The same held for every row of the pile, the Said
    list and the vocabulary panel between a rebuild and the next call.

    `bind_all` fixes that and brings its own problem: the "all" bindtag is
    one per INTERPRETER, and two Scrollers on one screen cannot each own
    it. So the binding is installed once, on the ROOT (a binding
    registered against a Scroller dies with that Scroller and takes the
    whole interpreter's wheel with it), it is this module-level function
    so it holds no Tk object of its own, and it decides who scrolls by
    asking the SCREEN which widget is under the pointer and walking up
    from there. The innermost Scroller wins, which is also the right
    answer for one nested inside another.

    Ordering makes the old per-widget bindings harmless rather than
    doubling them: a widget binding runs first and `_wheel` returns
    "break", so the "all" tag never sees the event. `bind_wheel` is
    therefore still a real thing to call — it just stopped being the only
    way the wheel arrives.
    """
    widget = getattr(event, "widget", None)
    if not isinstance(widget, tk.Misc):
        return None
    target = None
    try:
        path = widget.tk.call("winfo", "containing",
                              event.x_root, event.y_root)
        if path:
            target = widget.nametowidget(path)
    except Exception:                     # noqa: BLE001 — off our windows
        target = None
    if target is None:
        target = widget
    for _step in range(64):               # a cycle here would be a hang
        if isinstance(target, Scroller):
            return target._wheel(event)
        target = getattr(target, "master", None)
        if target is None:
            return None
    return None


def _arrow_disc(size: int, fill: str, bg: str, border: str,
                ink: str) -> ImageTk.PhotoImage:
    """The round "back to the top" button, drawn at 4x and shrunk.

    Pillow anti-aliases nothing and Tk anti-aliases less, so the arrow is
    drawn four times over and resized with LANCZOS like every other shape
    in this file. It is a bar with an arrow under it — the ⤒ shape and not
    a bare ↑ — because a lone up arrow in a page that scrolls reads as
    "up a bit", and this one goes all the way home.

    `bg` fills the corners the circle does not, and THAT IS WHY THE
    BUTTON DOES NOT FLOAT OVER THE ROWS ANY MORE. A Tk widget is an
    opaque rectangle, forever (AGENTS.md): the eleven per cent of this
    tile the circle leaves over is painted `bg` and there is no way to
    make it see-through. Parked over a row — a rounded #24201a face on
    the #14110c ground — those corners are seven L* darker than what is
    behind them and you see a square with a circle on it, which is what
    the owner reported on 2026-09-07: "you can see it's a bit cut,
    because you made it like a circle but also square." Counted off the
    bitmap the same day, at the 28 px it was then: 84 of its 784 pixels
    were still the ground colour. So `bg` has to be the
    truth, and the button now sits in the one column of a page where the
    ground really is the ground — see `Scroller._show_top`.
    """
    key = ("top-disc", size, fill, bg, border, ink)
    if key not in _cache:
        s = 4
        px = size * s
        image = Image.new("RGB", (px, px), bg)
        draw = ImageDraw.Draw(image)
        draw.ellipse((0, 0, px - 1, px - 1), fill=fill, outline=border,
                     width=s)
        stroke = max(s, round(px * 0.055))
        cx = px / 2
        bar, tip, barb, foot = px * 0.31, px * 0.40, px * 0.55, px * 0.71
        wing = px * 0.15
        draw.line((cx - wing, bar, cx + wing, bar), fill=ink, width=stroke)
        draw.line((cx, tip, cx, foot), fill=ink, width=stroke)
        draw.line(((cx - wing, barb), (cx, tip), (cx + wing, barb)),
                  fill=ink, width=stroke, joint="curve")
        _cache[key] = ImageTk.PhotoImage(image.resize((size, size),
                                                      Image.LANCZOS))
    return _cache[key]


class Scroller(tk.Frame):
    """A scrolling column with a thin thumb beside it.

    Not `ttk.Scrollbar`: on Windows that is a native, light-grey, 17 px
    wide control with arrow buttons at both ends, and dropping one down
    the side of this window undoes the whole exercise.

    IT SCROLLS IN PIXELS. A Canvas with no `yscrollincrement` moves a
    tenth of its own height per unit, and the wheel handler sent two
    units a notch: a fifth of the screen per click, which is what the
    owner called "laggy and ugly" on 2026-09-07 — the content did not
    glide, it jumped. Now a notch is SCROLL_UNITS x SCROLL_STEP px,
    about one row, and a high-resolution wheel that sends smaller
    deltas still moves at least one unit rather than rounding to none.

    Three things the owner asked for the same evening, after using it:

    1. **The wheel works over every pixel**, whatever is drawn there and
       whenever it was drawn — see `_wheel_to_the_pointer`.
    2. **The thumb is a handle.** It was a picture: press it and nothing
       happened at all ("if I hold it, it doesn't help ... you can only
       use the scroll wheel"). It is now dragged, the rail above and
       below it pages, and it lights under the pointer. The rail is
       RAIL_HIT px wide to be grabbable and the thumb is still painted
       THUMB_W px wide at the same place on it, so nothing moved on
       screen: the extra width is hit area to the RIGHT of the paint,
       past where the thumb has always been.
    3. **A way home.** Once the view has left the top a small disc
       appears at the FOOT OF THE RAIL and takes it back. Not floating in
       a corner of the page: an opaque tile floating over rows is the
       square the owner photographed on 2026-09-07, and no corner of a
       scrolling page is free of rows. The disc is instead parked in the
       one column that is nothing but ground on all six places — the
       GUTTER the canvas keeps to the right of the content, plus the
       inner half of the rail — where its own corners are the page's own
       colour and there is no square left to see. The rail gives up
       TOP_FOOT px at its bottom for it, the way a Windows scrollbar's
       thumb stops above the arrow button at its end.
    """

    def __init__(self, parent, w: int, h: int, bg: str = PANE):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, width=w, height=h, bg=bg,
                                highlightthickness=0, bd=0,
                                yscrollincrement=SCROLL_STEP)
        self.canvas.pack(side="left")
        self.rail = tk.Canvas(self, width=RAIL_HIT, height=h, bg=bg,
                              highlightthickness=0, bd=0)
        self.rail.pack(side="right", fill="y")
        self._width = int(w)             # fixed at build time; only h moves
        self._height = h
        self._thumb = (0, 0)             # (top, length) of what is painted
        self._grab = None                # (pressed at, first, fraction)
        self._hot = False
        self.inner = tk.Frame(self.canvas, bg=bg)
        # `w - GUTTER`, so the strip the way home parks in belongs to the
        # canvas and not to whatever was packed in here. Every dashboard
        # screen already asked for a page ten pixels wider than its rows
        # and left the strip alone by hand; the first-run wizard's device
        # rows are `fill="x"` and did not, and they now stop where the
        # others do. Nothing moved on the screens that were already
        # right: the ten pixels were the frame's own background before
        # and are the canvas's own background now, and both are `bg`.
        self.canvas.create_window(0, 0, anchor="nw", window=self.inner,
                                  width=w - GUTTER)
        self.inner.bind("<Configure>", self._resized)
        for widget in (self.canvas, self.inner):
            widget.bind("<MouseWheel>", self._wheel)

        self.rail.bind("<Button-1>", self._rail_press)
        self.rail.bind("<B1-Motion>", self._rail_drag)
        self.rail.bind("<ButtonRelease-1>", self._rail_release)
        self.rail.bind("<Motion>", self._rail_hover)
        self.rail.bind("<Leave>", self._rail_left)
        self.rail.bind("<MouseWheel>", self._wheel)

        # The way home. Built now and shown only once the view has left
        # the top, so it costs one cached bitmap and never a rebuild.
        self.top_button = tk.Canvas(self, width=TOP_DISC, height=TOP_DISC,
                                    bg=bg, highlightthickness=0, bd=0,
                                    cursor="hand2")
        self._top_face = self.top_button.create_image(
            0, 0, anchor="nw", image=self._disc(False))
        self.top_button.bind("<Button-1>", lambda _e: self.to_top())
        self.top_button.bind("<Enter>", lambda _e: self._light_disc(True))
        self.top_button.bind("<Leave>", lambda _e: self._light_disc(False))
        self.top_button.bind("<MouseWheel>", self._wheel)
        self._catch_the_wheel()

    # ------------------------------------------------------------ the wheel

    def _catch_the_wheel(self) -> None:
        """Install the interpreter's one wheel binding, once.

        On the ROOT and not on `self`: `bind_all` registers its Tcl
        command against the widget it was called on and `destroy()`
        deletes that widget's commands, so a binding installed by a
        Scroller stops working — for every Scroller — the moment the
        dashboard rebuilds the screen it was on.
        """
        root = self._root()
        if getattr(root, "_deskit_wheel", False):
            return
        root.bind_all("<MouseWheel>", _wheel_to_the_pointer)
        root._deskit_wheel = True

    def _wheel(self, event) -> str:
        delta = getattr(event, "delta", 0) or 0
        if not delta:
            return "break"
        units = -delta * SCROLL_UNITS / 120.0
        units = int(math.copysign(max(1, round(abs(units))), units))
        try:
            self.canvas.yview_scroll(units, "units")
            self._paint_thumb()
        except tk.TclError:
            pass                          # the page went away under us
        # "break", so a widget that `bind_wheel` reached does not then
        # hand the same notch to the interpreter-wide binding as well.
        # It has to be RETURNED, and that means nothing above may raise:
        # a handler that dies returns None, the Tcl `if {... == "break"}`
        # tkinter wraps it in never fires, and the notch is delivered a
        # second time to the "all" tag. 48 px became 96.
        return "break"

    def bind_wheel(self, widget) -> None:
        """Bind the wheel to a widget and everything under it.

        Since `_wheel_to_the_pointer` this is no longer what makes the
        page scroll — it is a shortcut that saves the dispatcher a
        `winfo containing` — and it is kept because four files call it
        and because a widget binding is the only way to be sure a nested
        scrolling widget (a tk.Text) does not scroll itself AND the page
        on one notch.
        """
        widget.bind("<MouseWheel>", self._wheel)
        for child in widget.winfo_children():
            self.bind_wheel(child)

    # ------------------------------------------------------------- the rail

    def _resized(self, _event=None) -> None:
        self.canvas.config(scrollregion=self.canvas.bbox("all"))
        # yview only tells the truth once Tk has done the geometry, which
        # happens after this event rather than during it.
        self.after_idle(self._paint_thumb)

    def _rail_room(self) -> int:
        """How much of the rail the thumb may use.

        The viewport, less the foot the way home is parked in. Reserved
        ALWAYS and not only while the disc is on screen: the disc appears
        after one notch of the wheel, and a thumb whose scale changed at
        that moment would jump under a hand that was about to grab it.
        Giving it up for good costs the bottom TOP_FOOT px of travel and
        is what a native Windows scrollbar does for the arrow button at
        its end.
        """
        return max(THUMB_MIN, self._height - TOP_FOOT)

    def _paint_thumb(self) -> None:
        try:
            first, last = self.canvas.yview()
        except tk.TclError:
            return
        self.rail.delete("thumb")
        if last - first >= 0.999:
            self._thumb = (0, 0)         # everything fits: no thumb at all
            self._show_top(False)
            return
        room = self._rail_room()
        length = max(THUMB_MIN, int((last - first) * room))
        # Clamped, because `length` has a floor and `first * room` does
        # not: a very long page put the last few pixels of its thumb past
        # the bottom of its own rail, which is also where a drag would
        # have run out of room.
        top = max(0, min(int(first * room), room - length))
        self._thumb = (top, length)
        lit = self._hot or self._grab is not None
        # Centred in RAIL_PAINT and not in RAIL_HIT: the extra width is
        # hit area, and it was added to the RIGHT of the paint so that
        # nothing on screen moved when the rail grew.
        self.rail.create_image((RAIL_PAINT - THUMB_W) // 2, top,
                               anchor="nw", tags="thumb",
                               image=rounded(THUMB_W, length, THUMB_W // 2,
                                             FAINT if lit else THUMB,
                                             self.rail["bg"]))
        self._show_top(first > 0.001)

    def _on_thumb(self, y: int) -> bool:
        top, length = self._thumb
        return bool(length) and top <= y < top + length

    def _rail_press(self, event) -> str:
        top, length = self._thumb
        if not length:
            return "break"               # nothing to scroll: nothing to do
        if self._on_thumb(event.y):
            first, last = self.canvas.yview()
            self._grab = (event.y, first, last - first)
        else:
            # Above or below the thumb: a page, in whole wheel units so
            # the answer does not depend on how Tk reads "pages" when a
            # yscrollincrement is set.
            page = max(1, int(self._height * 0.9) // SCROLL_STEP)
            self.canvas.yview_scroll(-page if event.y < top else page,
                                     "units")
        self._paint_thumb()
        return "break"

    def _rail_drag(self, event) -> str:
        if self._grab is None:
            return "break"
        pressed, first, fraction = self._grab
        top, length = self._thumb
        span = max(1, self._rail_room() - length)
        room = max(0.0, 1.0 - fraction)
        where = first + (event.y - pressed) / span * room
        self.canvas.yview_moveto(max(0.0, min(room, where)))
        self._paint_thumb()
        return "break"

    def _rail_release(self, _event=None) -> str:
        self._grab = None
        self._paint_thumb()
        return "break"

    def _rail_hover(self, event) -> None:
        hot = self._on_thumb(event.y)
        if hot != self._hot:
            self._hot = hot
            self._paint_thumb()

    def _rail_left(self, _event=None) -> None:
        if self._hot:
            self._hot = False
            self._paint_thumb()

    # --------------------------------------------------------- the way home

    def _disc(self, lit: bool) -> ImageTk.PhotoImage:
        ground = self["bg"]
        if lit:
            return _arrow_disc(TOP_DISC, EDGE_HI, ground, TILE_EDGE, FG)
        return _arrow_disc(TOP_DISC, CARD_HI, ground, STROKE, DIM)

    def _light_disc(self, lit: bool) -> None:
        try:
            self.top_button.itemconfig(self._top_face, image=self._disc(lit))
        except tk.TclError:
            pass

    def _show_top(self, on: bool) -> None:
        button = getattr(self, "top_button", None)
        if button is None or not button.winfo_exists():
            return
        if on:
            # THE FOOT OF THE RAIL, and not a corner of the page. Its
            # right edge is GUTTER px into the rail and its left edge is
            # GUTTER px short of the canvas, so the whole tile lies on
            # the strip the canvas keeps clear plus the empty half of the
            # rail. Measured on the built window, 2026-09-07: it lands at
            # sheet x1136..1156 on Home, Problems and Settings, x816..836
            # on Said and Corrections, x805..825 on Keys — and on all six
            # it is clear of everything the page drew, of the panel that
            # stands beside Said, Corrections and Keys (which begins at
            # the pixel the disc ends on), and of the footer under the
            # page, which is outside it entirely. That answers both
            # of the day's complaints at once — nothing behind it but
            # ground, so no square; and it is 568 px to the right of the
            # "Show 25 more · 75 older still here" it used to sit on top
            # of at the bottom of Said.
            #
            # Placed every time rather than once: `resize()` moves the
            # bottom edge it hangs off.
            button.place(x=self._width + GUTTER,
                         y=self._height - TOP_INSET, anchor="se")
            # `tk.Misc.tkraise(button)` and not `button.tkraise()`:
            # tkinter's Canvas rebinds BOTH `lift` and `tkraise` to
            # `tag_raise`, which wants an item id and raises TclError
            # without one. And an exception in a <MouseWheel> handler is
            # not just noise, it is a notch that scrolls TWICE — tkinter
            # turns "break" into a Tcl break only when the callback
            # RETURNS it, so a handler that dies never stops the
            # interpreter-wide binding from running after it. Measured on
            # the probe: 96 px a notch instead of 48.
            tk.Misc.tkraise(button)
        elif button.winfo_manager():
            button.place_forget()

    def top_showing(self) -> bool:
        """Is the way home on screen? For the tests, and for a caller
        that wants to know whether the page has been left."""
        button = getattr(self, "top_button", None)
        return bool(button is not None and button.winfo_exists()
                    and button.winfo_manager())

    # ------------------------------------------------------------- the rest

    def resize(self, h: int) -> None:
        """A new height for the viewport. The canvas and the rail were
        sized once at construction, and a frame grown around them by
        `place` centred the old viewport in the new room — rows in the
        middle of an empty card, photographed 2026-09-07."""
        self._height = int(h)
        self.canvas.configure(height=self._height)
        self.rail.configure(height=self._height)
        self.after_idle(self._paint_thumb)

    def to_top(self) -> None:
        self.canvas.yview_moveto(0)
        self._paint_thumb()

    def clear(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()


# ------------------------------------------------------------------ text


def _font(family: str, size: int):
    import tkinter.font as tkfont
    key = (family, size)
    if key not in _FONTS:
        _FONTS[key] = tkfont.Font(family=family, size=size)
    return _FONTS[key]


def _text_width(text: str, size: int) -> int:
    try:
        return _font(UI, size).measure(text)
    except Exception:
        return len(text) * 7


def text_width(text: str, family: str, size: int) -> int:
    return _font(family, size).measure(text)


def pill(canvas, x: int, y: int, text: str, bg: str, *,
         size: int = PT_LABEL, fill: str = CHIP_OFF,
         border: str = CHIP_OFF_EDGE, colour: str = DIM) -> int:
    """A chip drawn straight onto a canvas, right-aligned at `x`.

    The widget version above is a Canvas of its own, which is the right
    trade for six filter buttons and the wrong one for four hundred word
    pairs in a scrolling list — see the note on Scroller rows.
    """
    width = 26 + text_width(text, UI, size)
    canvas.create_image(x - width, y, anchor="nw",
                        image=rounded(width, PILL_H, PILL_H // 2, fill,
                                      bg, border))
    canvas.create_text(x - width / 2, y + PILL_H / 2, text=text,
                       font=(UI, size), fill=colour)
    return width


# --------------------------------------------------- text drawn by Windows
#
# Tk hands a string to ExtTextOutW with an LTR base direction and no way
# to say otherwise. Hebrew WORDS come out right (the glyph runs are
# shaped correctly) but the RUNS of a mixed line are laid out backwards:
# "תתפרע... יהיה sick אתה יודע" rendered with its two Hebrew halves
# swapped around the "sick". Measured against DrawTextW+DT_RTLREADING on
# 2026-08-20 (rtl_reference.png), and directional control characters
# (RLM, RLE) change nothing — Tk strips them. So a transcript is not a
# Label: it is drawn by DrawTextW itself — the exact call popup.py has
# already proven on this machine — into a bitmap, and the bitmap goes on
# screen. Wrapping (DT_WORDBREAK) and the trailing … (DT_END_ELLIPSIS)
# come from the same call, which is why there is no clamp() here.

DT_WORDBREAK, DT_CALCRECT = 0x0010, 0x0400
DT_RIGHT, DT_RTLREADING = 0x0002, 0x00020000
DT_NOPREFIX, DT_END_ELLIPSIS, DT_EDITCONTROL = 0x0800, 0x8000, 0x2000


def _colorref(colour: str) -> int:
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return r | (g << 8) | (b << 16)


def _px(pt: int) -> int:
    """Points to pixels at this process's DPI, the same conversion Tk
    makes — so a drawn paragraph and a Label agree on type size."""
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    hdc = user.GetDC(0)
    dpi = gdi.GetDeviceCaps(hdc, 90)          # LOGPIXELSY
    user.ReleaseDC(0, hdc)
    return max(1, round(pt * dpi / 72))


def draw_text(text: str, *, pt: int, width: int | None, max_lines: int,
              colour: str, bg: str, family: str | None = None,
              rtl: bool | None = None):
    """A paragraph rendered by Windows' own bidi, as a PhotoImage.

    Returns (photo, height, lines). Cached on every argument — the
    history list re-renders on every filter keystroke and the texts
    barely change.
    """
    family = family or TEXT
    if rtl is None:
        rtl = is_rtl(text)
    text = " ".join(text.split()) or " "
    key = ("dtext", text, pt, width, max_lines, colour, bg, family, rtl)
    if key in _cache:
        return _cache[key]

    import ctypes.wintypes as w
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    px = _px(pt)
    base = DT_NOPREFIX | DT_WORDBREAK | (DT_RTLREADING | DT_RIGHT if rtl
                                         else 0)
    CLEARTYPE_QUALITY = 5
    hdc_screen = user.GetDC(0)
    hdc = gdi.CreateCompatibleDC(hdc_screen)
    font = gdi.CreateFontW(-px, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0,
                           CLEARTYPE_QUALITY, 0, family)
    old_font = gdi.SelectObject(hdc, font)
    try:
        # One line's height, then the block's, then the cap.
        probe = w.RECT(0, 0, width or 4000, 0)
        user.DrawTextW(hdc, "אAg", -1, ctypes.byref(probe),
                       DT_CALCRECT | DT_NOPREFIX)
        line_h = max(1, probe.bottom)
        rect = w.RECT(0, 0, width or 4000, 0)
        user.DrawTextW(hdc, text, -1, ctypes.byref(rect), DT_CALCRECT | base)
        if not width:
            # Natural width: a single word for a pill, sized by the text.
            width = max(1, rect.right)
        lines = max(1, min(max_lines, round(rect.bottom / line_h)))
        height = lines * line_h
        clipped = rect.bottom > height + 2
        flags = base | ((DT_END_ELLIPSIS | DT_EDITCONTROL) if clipped else 0)

        bmp = gdi.CreateCompatibleBitmap(hdc_screen, width, height)
        old_bmp = gdi.SelectObject(hdc, bmp)
        paint = w.RECT(0, 0, width, height)
        brush = gdi.CreateSolidBrush(_colorref(bg))
        user.FillRect(hdc, ctypes.byref(paint), brush)
        gdi.DeleteObject(brush)
        gdi.SetTextColor(hdc, _colorref(colour))
        gdi.SetBkMode(hdc, 1)                                # TRANSPARENT
        user.DrawTextW(hdc, text, -1, ctypes.byref(paint), flags)

        class Header(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("w", w.LONG), ("h", w.LONG),
                        ("planes", w.WORD), ("bits", w.WORD),
                        ("comp", w.DWORD), ("imgsize", w.DWORD),
                        ("xppm", w.LONG), ("yppm", w.LONG),
                        ("used", w.DWORD), ("important", w.DWORD)]
        info = Header(ctypes.sizeof(Header), width, -height, 1, 32,
                      0, 0, 0, 0, 0, 0)
        raw = ctypes.create_string_buffer(width * height * 4)
        gdi.GetDIBits(hdc, bmp, 0, height, raw, ctypes.byref(info), 0)
        gdi.SelectObject(hdc, old_bmp)
        gdi.DeleteObject(bmp)
        image = Image.frombuffer("RGBA", (width, height), raw.raw, "raw",
                                 "BGRA", 0, 1).convert("RGB")
    finally:
        gdi.SelectObject(hdc, old_font)
        gdi.DeleteObject(font)
        gdi.DeleteDC(hdc)
        user.ReleaseDC(0, hdc_screen)

    result = (ImageTk.PhotoImage(image), height, lines)
    _cache[key] = result
    return result


PAIR_GAP, PAIR_PAD = 24, 13


def pair_size(wrong: str, correct: str, size: int = PT_LABEL,
              height: int | None = None) -> tuple[int, int]:
    """How wide and how TALL one correction pill is, before it is drawn.

    The height used to be assumed rather than asked for, and the
    assumption was wrong on the one screen that lays these out in a
    column: the vocabulary panel stepped 30 px a row because 30 was the
    number in the design, and PILL_H is 36. So every pair was drawn 6 px
    into the one above it — the overlap the owner reported on
    2026-09-07. A caller that stacks pills asks here now, and steps by
    what it is told.

    The words are their own bitmaps and they can be taller than the pill
    they sit in (draw_text is 20 px at pt 10 and 24 at pt 12 on this
    machine), and they are centred on the pill's middle — so the pill
    grows to hold them instead of letting them hang out of both ends. An
    explicit `height` is honoured as given: a row with three bands to
    fit knows better than this function does how much it can spare, and
    it picks `size` small enough for the words to fit inside it.
    """
    wrong_img, wrong_h, _l = draw_text(wrong, pt=size, width=None,
                                       max_lines=1, colour=DIM, bg=CHIP_OFF)
    right_img, right_h, _l = draw_text(correct, pt=size, width=None,
                                       max_lines=1, colour=FG, bg=CHIP_OFF)
    width = (PAIR_PAD * 2 + wrong_img.width() + right_img.width()
             + PAIR_GAP)
    return width, (height or max(PILL_H, wrong_h, right_h))


def pair_pill(canvas, x: int, y: int, wrong: str, correct: str,
              bg: str, size: int = PT_LABEL,
              height: int | None = None) -> int:
    """One correction — what was heard, what it should have been.

    Drawn right-aligned at `x`, downwards from `y`, and it stays inside
    `x - width .. x` by `y .. y + height`: `pair_size` is what both this
    and its callers measure with, so a column of them cannot overlap.
    Returns the width, which is what a caller laying a line out needs;
    the height comes from `pair_size`.

    Both words are DrawTextW bitmaps (a corrected word is often mixed,
    "ה-user", and a mixed word split into runs comes out of Tk backwards
    — same disease as the paragraphs, same cure). The arrow is drawn
    separately and pointed HERE: photographed as one string, an RTL line
    gave U+2192 unmirrored, aiming at the word it came from. The wrong
    word always sits where reading starts and the arrow points away
    from it.
    """
    rtl = is_rtl(wrong) or is_rtl(correct)
    wrong_img, _h, _l = draw_text(wrong, pt=size, width=None, max_lines=1,
                                  colour=DIM, bg=CHIP_OFF)
    right_img, _h, _l = draw_text(correct, pt=size, width=None,
                                  max_lines=1, colour=FG, bg=CHIP_OFF)
    width, tall = pair_size(wrong, correct, size, height)
    canvas.create_image(x - width, y, anchor="nw",
                        image=rounded(width, tall, tall // 2,
                                      CHIP_OFF, bg, CHIP_OFF_EDGE))
    start, mid = x - width, y + tall / 2
    first, second = (wrong_img, right_img) if not rtl else (right_img,
                                                            wrong_img)
    canvas.create_image(start + PAIR_PAD, mid, anchor="w", image=first)
    canvas.create_image(x - PAIR_PAD, mid, anchor="e", image=second)
    arrow = "←" if rtl else "→"
    canvas.create_text(start + PAIR_PAD + first.width() + PAIR_GAP / 2, mid,
                       text=arrow, font=(UI, size + 1), fill=FAINT)
    return width


def clamp(text: str, family: str, size: int, width: int,
          lines: int) -> tuple[str, int]:
    """Wrap by measuring, stop after `lines`, and say how many were used.

    Tk's own `wraplength` will happily turn a paragraph into six lines
    inside a box built for two, and the sixth lands on top of whatever is
    under it. Wrapping here means a row's height and its text agree before
    either is drawn.

    Two things stop this from being the slowest thing in the window, both
    measured on a hundred history rows: a word-at-a-time greedy wrap costs
    one Tcl round trip per word, which came to 420 ms for the list — so
    the break is ESTIMATED from the width of the whole run and then
    corrected, four or five measurements a line instead of eighty. And the
    answers are remembered, because filtering and searching re-wrap the
    same sentences over and over.
    """
    key = (text, family, size, width, lines)
    if key in _CLAMPS:
        return _CLAMPS[key]
    measure = _font(family, size).measure
    # Only the first few lines can ever be shown, and measuring a whole
    # dictated paragraph to draw two lines of it is most of the cost.
    # Forty words a line is more than fits at any width used here.
    every = text.split()
    words = every[:max(24, lines * 40)]
    out: list[str] = []
    index = 0
    while index < len(words) and len(out) < lines:
        rest = " ".join(words[index:])
        span = measure(rest)
        if span <= width:
            out.append(rest)
            index = len(words)
            break
        # Where the break roughly is, from how much of the run fits.
        guess = max(1, int(len(rest) * width / span))
        count, used = 0, 0
        for word in words[index:]:
            step = len(word) + (1 if count else 0)
            if used + step > guess and count:
                break
            used += step
            count += 1
        while count > 1 and measure(" ".join(words[index:index + count])) > width:
            count -= 1
        while (index + count < len(words)
               and measure(" ".join(words[index:index + count + 1])) <= width):
            count += 1
        line = " ".join(words[index:index + count])
        while count == 1 and line and measure(line) > width:
            line = line[:-1]        # one word wider than the box
        out.append(line)
        index += count
    result: tuple[str, int]
    if not out:
        result = ("", 1)
    else:
        if index < len(words) or len(words) < len(every):
            while out[-1] and measure(out[-1] + " …") > width:
                out[-1] = out[-1][:-1]
            out[-1] += " …"
        result = ("\n".join(out), len(out))
    if len(_CLAMPS) > 4000:
        _CLAMPS.clear()
    _CLAMPS[key] = result
    return result


def is_rtl(text: str) -> bool:
    """Whether to align a line right, decided the way Windows decides
    which way to lay it out: by the first strong character in it.

    Tk has no way to force a paragraph direction, so guessing differently
    from the renderer would align a line one way and lay it out the other.
    """
    for ch in text:
        if 0x0590 <= ord(ch) <= 0x06FF:
            return True
        if ch.isalpha():
            return False
    return False
