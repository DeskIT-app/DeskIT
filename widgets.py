"""The pieces the desk window needs that ui.py does not have.

ui.py owns the palette, the rounded faces, the bidi text engine and the
seven controls the old window was built from. It is not this wave's file
— the tokens and the sizes in it are being retuned by somebody else at
the same time as this — so nothing here copies a value out of it. Every
colour is read as `ui.NAME` INSIDE a function, at the moment the widget
is built, so a repainted palette lands on the next screen that is drawn
rather than needing this module to be edited too.

Seven things, all of them found missing while the calm-desk prototype
was built against the real ui.py (r3/spikes/spikes.md §1):

* `rule` — a hairline. `ui.LINE` and `ui.RULE` are colours; nothing drew
  one.
* `Tabs` — the four places along the top. The old window's only
  navigation was a rail of nine rows, built inline.
* `StateChip` — lamp + word + a quiet number, on no face at all.
* `icon` — `ui.ICON` holds the codepoints and `ui.ICONS` the family;
  every caller wrote the `tk.Label(font=(ui.ICONS, n))` by hand.
* `PileRow` — a row with its text stopping where its buttons start.
* `rtl_run` — `ui.draw_text` renders a paragraph as ONE bitmap, so there
  is no way to put a pill behind one word inside a Hebrew sentence.
* `ToneButton` — `ui.Button` can be accent or edge and nothing else
  (`_build_faces` hardcodes them), so the design's gold Yes is
  unaskable. Asked for as a `tone=` keyword on `ui.Button` in NOTES.md;
  this subclass is what stands in until that exists, and it goes away
  the day it does.
"""
from __future__ import annotations

import tkinter as tk

import ui


# --------------------------------------------------------------- colours

def _rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return (int(colour[0:2], 16), int(colour[2:4], 16), int(colour[4:6], 16))


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb)


def mix(a: str, b: str, amount: float) -> str:
    """`amount` of b over a. Used for hover and pressed faces, so a tone
    is derived from the palette rather than being three more literals
    that would have to be retuned by hand every time it moves."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return _hex((ra + (rb - ra) * amount, ga + (gb - ga) * amount,
                 ba + (bb - ba) * amount))


def accent_tone() -> tuple[tuple[str, str, str], str]:
    """((idle, hover, pressed), ink) for THE one gold button on a surface.

    Read at call time: ACCENT is the lamp and it is being retuned. The
    hover is the accent lifted towards white, the press is it dropped
    towards the ground, and the ink is `ACCENT_ON` when the palette
    carries one — the measured dark that reads on gold — and the window
    ground when it does not yet.
    """
    accent = ui.ACCENT
    ink = getattr(ui, "ACCENT_ON", None) or ui.BG
    return (accent, mix(accent, "#ffffff", 0.18),
            mix(accent, ui.BG, 0.22)), ink


def line_colour(hot: bool = False) -> str:
    if hot:
        return getattr(ui, "LINE_HI", None) or ui.TILE_EDGE
    return ui.LINE


# ------------------------------------------------------------- fitting

def fit(text: str, family: str, size: int, width: int) -> str:
    """One line, never wider than `width`, and SAID to be cut when it is.

    `ui.clamp` is the wrapper and it marks a cut with " …" — but only
    when it ran out of WORDS. A single word wider than the box takes its
    other branch, which shaves characters off the end and says nothing:
    "balanced" came back as "balance" inside a 63 px menu and read as a
    spelling mistake rather than as a value that did not fit. Measured
    2026-09-07 on the settings sentences.

    So: clamp first (it is cached, and it handles the ordinary case),
    then check the answer and add the ellipsis ourselves if the clamp
    ate characters silently. Everything a control draws inside a
    sentence goes through this, which is what keeps a line from running
    past the box that is supposed to hold it.
    """
    text = str(text)
    if width <= 0:
        return ""
    if ui.text_width(text, family, size) <= width:
        return text
    shown = ui.clamp(text, family, size, width, 1)[0].replace("\n", " ")
    if shown.endswith("…"):
        return shown
    shown = shown.rstrip()
    while shown and ui.text_width(shown + "…", family, size) > width:
        shown = shown[:-1]
    return (shown + "…") if shown else ""


# ----------------------------------------------------------------- rules

def rule(parent, width: int, *, bg: str, colour: str | None = None,
         x: int | None = None, y: int = 0, height: int = 1, **place):
    """One hairline. A Frame, not a Canvas line: it costs no bitmap and
    it can be placed or packed like anything else."""
    line = tk.Frame(parent, width=width, height=height,
                    bg=colour or ui.RULE)
    if x is not None:
        line.place(x=x, y=y)
    elif place:
        line.pack(**place)
    else:
        line.place(x=0, y=y)
    return line


# ------------------------------------------------------------------ tabs

class Tabs(tk.Frame):
    """The four places, with a 2 px accent underline under the one you
    are on.

    Labels rather than buttons: a place is not an action, and a pill
    round each of four words is four more rectangles competing with the
    one card the screen is about. The underline is a Frame of the
    accent, which is the only thing on this bar that is allowed to be
    gold — the state button beside it is quiet on purpose.
    """

    def __init__(self, parent, names, *, bg: str | None = None,
                 selected: str | None = None, command=None, gap: int = 30):
        bg = bg or ui.BG
        super().__init__(parent, bg=bg)
        self._bg = bg
        self._command = command
        self.items: dict[str, tuple] = {}
        for name in names:
            holder = tk.Frame(self, bg=bg)
            holder.pack(side="left", padx=(0, gap))
            label = tk.Label(holder, text=name, bg=bg, fg=ui.DIM,
                             font=(ui.UI, 11), cursor="hand2")
            label.pack(pady=(0, 7))
            bar = tk.Frame(holder, height=2, bg=bg)
            bar.pack(fill="x")
            for widget in (holder, label, bar):
                widget.bind("<Button-1>", lambda _e, n=name: self._hit(n))
            label.bind("<Enter>", lambda _e, n=name: self._hover(n, True))
            label.bind("<Leave>", lambda _e, n=name: self._hover(n, False))
            self.items[name] = (label, bar)
        self.selected = None
        self.select(selected or (names[0] if names else None))

    def _hit(self, name: str) -> None:
        if self._command is not None:
            self._command(name)

    def _hover(self, name: str, over: bool) -> None:
        if name == self.selected:
            return
        label, _bar = self.items[name]
        label.configure(fg=ui.FG if over else ui.DIM)

    def select(self, name: str | None) -> None:
        self.selected = name
        for other, (label, bar) in self.items.items():
            on = other == name
            label.configure(fg=ui.FG if on else ui.DIM,
                            font=(ui.UI, 11, "bold") if on else (ui.UI, 11))
            bar.configure(bg=ui.ACCENT if on else self._bg)


# ------------------------------------------------------------ state chip

class StateChip(tk.Frame):
    """The dot in its live colour, the word for it, and the uptime.

    On no face: a card round the state would be a second rectangle on a
    bar that already carries the wordmark and four places. The lamp is
    `ui.lamp`, so it breathes with the same cached bitmaps the rest of
    the window uses.
    """

    def __init__(self, parent, *, bg: str | None = None, size: int = 15):
        bg = bg or ui.BG
        super().__init__(parent, bg=bg)
        self._bg = bg
        self._size = size
        self.lamp = tk.Label(self, bg=bg,
                             image=ui.lamp(size, ui.DIM, bg, 0.45))
        self.lamp.pack(side="left", padx=(0, 9))
        self.word = tk.Label(self, text="", bg=bg, fg=ui.FG,
                             font=(ui.UI, 11, "bold"))
        self.word.pack(side="left")
        self.meta = tk.Label(self, text="", bg=bg, fg=ui.FAINT,
                             font=(ui.UI, 10))
        self.meta.pack(side="left", padx=(11, 0))

    def set(self, colour: str, word: str, meta: str = "",
            glow: float = 0.45) -> None:
        self.lamp.configure(image=ui.lamp(self._size, colour, self._bg,
                                          glow))
        self.word.configure(text=word)
        self.meta.configure(text=meta)


# ----------------------------------------------------------------- icons

# ui.ICON has no plain alert mark: "error" is a circled cross, which is
# the wrong glyph for "you reported this". Named here rather than in
# ui.py, which is not this builder's file; asked for in NOTES.md.
EXTRA_ICON = {
    "waiting": "",     # the bell, the same one Notify used
    "said": "",        # the history clock
    "alert": "",       # a plain warning triangle
    "vocabulary": "",  # the learned mark
    "phone": "",
    "sound": "",
    "shot": "",
}


def glyph(name: str) -> str:
    return ui.ICON.get(name) or EXTRA_ICON.get(name, "")


def icon(parent, name: str, *, bg: str, colour: str | None = None,
         size: int = 13):
    return tk.Label(parent, text=glyph(name), bg=bg,
                    fg=colour or ui.DIM, font=(ui.ICONS, size))


# ------------------------------------------------------------ bidi runs

def rtl_run(canvas, right_x: int, y: int, pieces, bg: str, *,
            pt: int = 12, gap: int = 7, pill_pad: int = 9,
            radius: int = 6, keep=None) -> int:
    """A Hebrew line laid out right to left out of SEVERAL bitmaps, so
    one word inside it can sit on a pill.

    `pieces` is (text, colour, pill-or-None) in READING order — the
    rightmost fragment first. Returns the width used.

    THE CAVEAT, and it is the whole reason this is not one draw_text
    call: the order BETWEEN segments is mine, not Windows'. Only split a
    line at a point where each fragment is one direction; a fragment
    that mixes Hebrew and Latin still goes through `ui.draw_text` whole,
    which is what puts its runs in the right order.
    """
    x = right_x
    for text, colour, pill in pieces:
        if not text:
            continue
        face = pill or bg
        photo, height, _lines = ui.draw_text(text, pt=pt, width=None,
                                             max_lines=1, colour=colour,
                                             bg=face, family=ui.TEXT)
        width = photo.width()
        if keep is not None:
            keep.append(photo)
        if pill:
            canvas.create_image(x - width - pill_pad * 2, y - 3, anchor="nw",
                                image=ui.rounded(width + pill_pad * 2,
                                                 height + 6, radius, pill,
                                                 bg))
            canvas.create_image(x - width - pill_pad, y, anchor="nw",
                                image=photo)
            x -= width + pill_pad * 2 + gap
        else:
            canvas.create_image(x - width, y, anchor="nw", image=photo)
            x -= width + gap
    return right_x - x


# --------------------------------------------------------------- buttons

class ToneButton(ui.Button):
    """`ui.Button` in a colour it does not offer.

    Three fills and an ink, passed in. Everything else — the hover, the
    one-pixel dip, `enable()` — is inherited, so the gold Yes behaves
    exactly like every other button in the window.
    """

    def __init__(self, parent, text: str, command=None, *,
                 tone=None, ink: str | None = None, **kw):
        if tone is None:
            tone, default_ink = accent_tone()
            ink = ink or default_ink
        self._tone = tone
        super().__init__(parent, text, command, fg=ink or ui.FG, **kw)

    def _build_faces(self, primary: bool, quiet: bool) -> list:
        return [ui.rounded(self._width, self._height, self._radius, fill,
                           self._bg, None) for fill in self._tone]

    @staticmethod
    def _face_colour(primary: bool, quiet: bool, fg: str | None) -> str:
        return fg or ui.FG


def gold_button(parent, text: str, command=None, **kw) -> ToneButton:
    """THE one primary action on a surface. There is never a second."""
    tone, ink = accent_tone()
    return ToneButton(parent, text, command, tone=tone, ink=ink, **kw)


def button_width(text: str, *, icon: bool = False, least: int = 74) -> int:
    """How wide a `ui.Button` has to be to hold its own label.

    `ui.Button` centres its label at w/2 (+9 when it carries an icon)
    and puts the icon 12 px to its left — nothing clips, so a `w=` that
    is too small does not cut the text, it draws it over the button's
    own rounded edge and out onto the card. Rubik at the new sizes is
    wider than the Segoe these numbers were picked for, which is how
    "Send a test notification" came to end past its own border.

    30 of air for a plain button, 44 with an icon (the glyph, its 12 px
    gap and the same air on the far side), measured against ui.Button's
    own arithmetic.
    """
    return max(least, ui.text_width(str(text), ui.UI, ui.PT_BODY)
               + (44 if icon else 30))


# ------------------------------------------------------------------ rows

class PileRow(tk.Frame):
    """One thing waiting: a mark, an eyebrow, the words, and the buttons
    that answer it.

    The buttons are built and measured FIRST and the text is given what
    is left, because the other way round is a Hebrew sentence that runs
    under a Yes. Everything is drawn on one Canvas rather than built out
    of Labels: a transcript has to go through `ui.draw_text` anyway, and
    a Label on a Canvas swallows the <Enter> the Canvas is waiting for.
    """

    HEIGHT = 88

    def __init__(self, parent, width: int, *, bg: str, mark: str = "",
                 mark_colour: str | None = None, eyebrow: str = "",
                 eyebrow_right: bool = True, text: str = "",
                 runs=None, note: str = "", buttons=(),
                 height: int | None = None):
        height = height or self.HEIGHT
        super().__init__(parent, bg=bg, width=width, height=height)
        self.pack_propagate(False)
        self.place_holder = None
        self._keep: list = []
        self.buttons: dict = {}

        if mark:
            icon(self, mark, bg=bg, colour=mark_colour or ui.FAINT,
                 size=15).place(x=6, y=height // 2 - 12)

        right = tk.Frame(self, bg=bg)
        right.place(x=width, y=height // 2, anchor="e")
        for label, kind, command in reversed(list(buttons)):
            if kind == "close":
                cross = tk.Label(right, text="✕", bg=bg, fg=ui.FAINT,
                                 font=(ui.UI, 11), cursor="hand2")
                cross.pack(side="right", padx=(12, 2))
                cross.bind("<Button-1>", lambda _e, c=command: c and c())
                cross.bind("<Enter>", lambda _e, w=cross: w.config(fg=ui.FG))
                cross.bind("<Leave>",
                           lambda _e, w=cross: w.config(fg=ui.FAINT))
                self.buttons[label] = cross
                continue
            wide = button_width(label, least=62)
            if kind == "gold":
                button = gold_button(right, label, command, bg=bg, w=wide,
                                     h=32)
            else:
                button = ui.Button(right, label, command, bg=bg, quiet=True,
                                   w=wide, h=32)
            button.pack(side="right", padx=(8, 0))
            self.buttons[label] = button
        right.update_idletasks()
        stop = width - right.winfo_reqwidth() - 22

        canvas = tk.Canvas(self, width=max(40, stop - 40), height=height,
                           bg=bg, highlightthickness=0, bd=0)
        canvas.place(x=40, y=0)
        self.canvas = canvas
        edge = max(40, stop - 40)
        # THE THREE BANDS ARE MEASURED FROM THE ROW, not counted up from
        # the top. A Canvas item does not clip: the note used to be
        # drawn at body + 30, which on a 72 px row put its bitmap at
        # 66..85 and simply lost it — the "why" of every second reading
        # was being rendered off the bottom of the row that owned it
        # (measured 2026-09-07). The note is now placed UP from the
        # bottom edge, and the words above it get one line instead of
        # two when there is a note to leave room for.
        top = 8 if (eyebrow or note) else height // 2 - 10
        if eyebrow:
            canvas.create_text(edge if eyebrow_right else 0, top,
                               text=eyebrow, anchor="e" if eyebrow_right
                               else "w", font=(ui.UI, 9), fill=ui.FAINT)
        body_y = top + (18 if eyebrow else 0)
        if runs:
            rtl_run(canvas, edge, body_y, runs, bg, keep=self._keep)
        elif text:
            photo, _h, _lines = ui.draw_text(
                text, pt=12, width=edge, max_lines=1 if note else 2,
                colour=ui.FG, bg=bg)
            self._keep.append(photo)
            canvas.create_image(edge if ui.is_rtl(text) else 0, body_y,
                                anchor="ne" if ui.is_rtl(text) else "nw",
                                image=photo)
        if note:
            photo, note_h, _lines = ui.draw_text(note, pt=9, width=edge,
                                                 max_lines=1,
                                                 colour=ui.FAINT, bg=bg)
            note_y = height - note_h - 5
            # A row too short to hold all three bands DROPS the note
            # rather than drawing it past its own bottom edge: outside a
            # canvas it is not clipped, it is invisible, and an invisible
            # line that the layout still believes in is the bug this
            # replaced.
            if note_y >= body_y + 20:
                self._keep.append(photo)
                canvas.create_image(edge, note_y, anchor="ne", image=photo)


def quiet_row(parent, width: int, *, bg: str, label: str, when: str,
              text: str, meta: str, rtl: bool, command=None,
              height: int = 42, keep=None):
    """One line about something that is NOT waiting: what it was, when,
    the words, and a number at the right. The whole of "the rest of the
    day" is four of these.
    """
    row = tk.Canvas(parent, width=width, height=height, bg=bg,
                    highlightthickness=0, bd=0,
                    cursor="hand2" if command else "arrow")
    row.create_text(0, height / 2, text=label, anchor="w",
                    font=(ui.UI, 10, "bold"), fill=ui.FG)
    row.create_text(96, height / 2, text=when, anchor="w", font=(ui.UI, 10),
                    fill=ui.FAINT)
    if meta:
        row.create_text(width, height / 2, text=meta, anchor="e",
                        font=(ui.UI, 9), fill=ui.FAINT)
    meta_w = ui.text_width(meta, ui.UI, 9) + 24 if meta else 0
    room = max(80, width - 200 - meta_w)
    if text:
        if rtl:
            # Flush right, and drawn: a mixed Hebrew/Latin line laid out
            # by create_text puts its runs in the wrong order.
            photo, text_h, _l = ui.draw_text(text, pt=11, width=room,
                                             max_lines=1, colour=ui.DIM,
                                             bg=bg)
            if keep is not None:
                keep.append(photo)
            row.create_image(width - meta_w, (height - text_h) / 2,
                             anchor="ne", image=photo)
        else:
            row.create_text(200, height / 2, text=ui.clamp(
                text, ui.UI, 11, room, 1)[0], anchor="w",
                font=(ui.UI, 11), fill=ui.DIM)
    if command is not None:
        row.bind("<Button-1>", lambda _e: command())
    return row
