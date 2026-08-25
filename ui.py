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

ICON = {
    "overview": "\ue80f", "history": "\ue81c", "keys": "\ue765",
    "settings": "\ue713", "mic": "\ue720", "play": "\ue768",
    "pause": "\ue769", "stop": "\ue71a", "copy": "\ue8c8",
    "search": "\ue721", "globe": "\ue774", "link": "\ue71b",
    "translate": "\ue8c1", "punctuate": "\ue8bd", "learned": "\ue90f",
    "error": "\uea39", "discarded": "\ue74d", "file": "\ue8a5",
    "page": "\ue7c3", "folder": "\ue8b7", "engine": "\ue9d9",
    "version": "\ue895",
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
    image = Image.new("RGB", (max(1, w * s), max(1, h * s)), bg)
    ImageDraw.Draw(image).rounded_rectangle(
        (0, 0, w * s - 1, h * s - 1), radius=radius * s, fill=fill,
        outline=border, width=s if border else 0)
    return image.resize((max(1, w), max(1, h)), Image.LANCZOS)


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


def icon_bitmap(path, size: int, bg: str) -> ImageTk.PhotoImage | None:
    """The app icon, with its corners rounded to match everything else."""
    key = ("app-icon", str(path), size, bg)
    if key not in _cache:
        try:
            art = Image.open(path).convert("RGB").resize(
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
                 h: int = 36, radius: int = 10, bg: str = CARD,
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
                                               font=(ICONS, 11),
                                               fill=self._colour)
        self._label = self.create_text(w / 2 + offset, h / 2 + 1, text=text,
                                       font=(UI, 10), fill=self._colour)
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
            return "#ffffff"
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
                                          self._radius, "#151a23",
                                          self._bg, "#1e2531"))
        colour = self._colour if on else FAINT
        self.itemconfig(self._label, fill=colour)
        if self._icon_item is not None:
            self.itemconfig(self._icon_item, fill=colour)


class Chip(tk.Canvas):
    """A pill that is either on or off: the history filters, and the pairs
    of words the vocabulary learned."""

    def __init__(self, parent, text: str, command=None, *, bg: str = PANE,
                 active: bool = False, font_size: int = 9):
        width = 26 + _text_width(text, font_size)
        super().__init__(parent, width=width, height=30, bg=bg,
                         highlightthickness=0, bd=0,
                         cursor="hand2" if command else "arrow")
        self._on = rounded(width, 30, 15, ACCENT_SOFT, bg, "#2f4d80")
        self._off = rounded(width, 30, 15, "#151b26", bg, "#222a36")
        self._hover = rounded(width, 30, 15, "#1b2230", bg, "#2c3648")
        self._active = active
        self._image = self.create_image(0, 0, anchor="nw", image=self._off)
        self._text = self.create_text(width / 2, 16, text=text,
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


class Switch(tk.Canvas):
    """A toggle. A Checkbutton with a tick in a square box is the single
    most dated thing that was on the old window."""

    def __init__(self, parent, value: bool = False, command=None,
                 bg: str = CARD):
        super().__init__(parent, width=42, height=24, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._on = rounded(42, 24, 12, ACCENT, bg)
        self._off = rounded(42, 24, 12, "#2a3242", bg)
        self._image = self.create_image(0, 0, anchor="nw", image=self._off)
        self._knob = self.create_oval(4, 4, 20, 20, fill=FG, width=0)
        self._value = value
        self._command = command
        self.bind("<Button-1>", lambda _e: self.toggle())
        self.set(value)

    def set(self, on: bool) -> None:
        """Move the knob without telling anyone — for repainting from a
        status poll, which must not look like the user clicked it."""
        self._value = bool(on)
        self.itemconfig(self._image, image=self._on if on else self._off)
        self.coords(self._knob, *((22, 4, 38, 20) if on else (4, 4, 20, 20)))

    def get(self) -> bool:
        return self._value

    def toggle(self) -> None:
        self.set(not self._value)
        if self._command:
            self._command(self._value)


class KeyCap(tk.Canvas):
    """What a hotkey should look like: a key. The old window showed them
    as grey rectangles identical to every other button, which is why
    "Right Ctrl" and "Start" were the same object to the eye."""

    def __init__(self, parent, text: str, command=None, *, bg: str = CARD,
                 w: int = 122, h: int = 34):
        super().__init__(parent, width=w, height=h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._idle = rounded(w, h, 9, "#1c2331", bg, "#303a4c")
        self._hover = rounded(w, h, 9, "#243044", bg, ACCENT)
        self._image = self.create_image(0, 0, anchor="nw", image=self._idle)
        self._label = self.create_text(w / 2, h / 2, text="", font=(UI, 10))
        self.set(text)
        self.bind("<Enter>",
                  lambda _e: self.itemconfig(self._image, image=self._hover))
        self.bind("<Leave>",
                  lambda _e: self.itemconfig(self._image, image=self._idle))
        if command:
            self.bind("<Button-1>", lambda _e: command())

    def set(self, text: str) -> None:
        off = text.lower() in ("", "off")
        self.itemconfig(self._label, text=text or "off",
                        font=(UI, 10) if off else (UI, 10, "bold"),
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
                               image=rounded(4, length, 2, "#2b3444",
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


def pill(canvas, x: int, y: int, text: str, bg: str, *, size: int = 9,
         fill: str = "#151b26", border: str = "#222a36",
         colour: str = DIM) -> int:
    """A chip drawn straight onto a canvas, right-aligned at `x`.

    The widget version above is a Canvas of its own, which is the right
    trade for six filter buttons and the wrong one for four hundred word
    pairs in a scrolling list — see the note on Scroller rows.
    """
    width = 26 + text_width(text, UI, size)
    canvas.create_image(x - width, y, anchor="nw",
                        image=rounded(width, 30, 15, fill, bg, border))
    canvas.create_text(x - width / 2, y + 15, text=text, font=(UI, size),
                       fill=colour)
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
              bg: str, size: int = 9) -> int:
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
                                  colour=DIM, bg="#151b26")
    right_img, _h, _l = draw_text(correct, pt=size, width=None, max_lines=1,
                                  colour=FG, bg="#151b26")
    gap, pad = 24, 13
    a, b = wrong_img.width(), right_img.width()
    width = pad * 2 + a + b + gap
    canvas.create_image(x - width, y, anchor="nw",
                        image=rounded(width, 30, 15, "#151b26", bg,
                                      "#222a36"))
    start = x - width
    first, second = (wrong_img, right_img) if not rtl else (right_img,
                                                            wrong_img)
    canvas.create_image(start + pad, y + 15, anchor="w", image=first)
    canvas.create_image(x - pad, y + 15, anchor="e", image=second)
    arrow = "←" if rtl else "→"
    canvas.create_text(start + pad + first.width() + gap / 2, y + 15,
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
