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
        self.face_item = self.create_image(
            0, 0, anchor="nw", image=rounded(w, h, radius, fill, bg, border))
        self.body = tk.Frame(self, bg=fill)
        self.create_window(pad, pad, anchor="nw", window=self.body,
                           width=w - 2 * pad, height=h - 2 * pad)

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


class Scroller(tk.Frame):
    """A scrolling column with a thin thumb beside it.

    Not `ttk.Scrollbar`: on Windows that is a native, light-grey, 17 px
    wide control with arrow buttons at both ends, and dropping one down
    the side of this window undoes the whole exercise.
    """

    def __init__(self, parent, w: int, h: int, bg: str = PANE):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, width=w, height=h, bg=bg,
                                highlightthickness=0, bd=0)
        self.canvas.pack(side="left")
        self.rail = tk.Canvas(self, width=6, height=h, bg=bg,
                              highlightthickness=0, bd=0)
        self.rail.pack(side="right", fill="y")
        self._height = h
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.canvas.create_window(0, 0, anchor="nw", window=self.inner,
                                  width=w)
        self.inner.bind("<Configure>", self._resized)
        for widget in (self.canvas, self.inner):
            widget.bind("<MouseWheel>", self._wheel)

    def _resized(self, _event=None) -> None:
        self.canvas.config(scrollregion=self.canvas.bbox("all"))
        # yview only tells the truth once Tk has done the geometry, which
        # happens after this event rather than during it.
        self.after_idle(self._paint_thumb)

    def _paint_thumb(self) -> None:
        try:
            first, last = self.canvas.yview()
        except tk.TclError:
            return
        self.rail.delete("thumb")
        if last - first >= 0.999:
            return                       # everything fits: no thumb at all
        length = max(36, int((last - first) * self._height))
        self.rail.create_image(1, int(first * self._height), anchor="nw",
                               tags="thumb",
                               image=rounded(4, length, 2, THUMB,
                                             self.rail["bg"]))

    def _wheel(self, event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 60), "units")
        self._paint_thumb()

    def bind_wheel(self, widget) -> None:
        """The wheel has to be bound to every child: a Canvas does not see
        an event that landed on a Label sitting on top of it."""
        widget.bind("<MouseWheel>", self._wheel)
        for child in widget.winfo_children():
            self.bind_wheel(child)

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


def pair_pill(canvas, x: int, y: int, wrong: str, correct: str,
              bg: str, size: int = PT_LABEL) -> int:
    """One correction — what was heard, what it should have been.

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
    gap, pad = 24, 13
    a, b = wrong_img.width(), right_img.width()
    width = pad * 2 + a + b + gap
    canvas.create_image(x - width, y, anchor="nw",
                        image=rounded(width, PILL_H, PILL_H // 2,
                                      CHIP_OFF, bg, CHIP_OFF_EDGE))
    start, mid = x - width, y + PILL_H / 2
    first, second = (wrong_img, right_img) if not rtl else (right_img,
                                                            wrong_img)
    canvas.create_image(start + pad, mid, anchor="w", image=first)
    canvas.create_image(x - pad, mid, anchor="e", image=second)
    arrow = "←" if rtl else "→"
    canvas.create_text(start + pad + first.width() + gap / 2, mid,
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
