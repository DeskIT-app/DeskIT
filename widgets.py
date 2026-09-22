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
  navigation was a rail of nine rows, built inline. Each word keeps its
  bold width, lit or not, so lighting one moves nothing (2026-09-22).
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

And one found missing later (2026-09-22): `PaintHold`, the photograph
of the pane a change of place holds over it while the new screen is
built and painted underneath, so the old screen stays on the glass
until the new one is finished.
"""
from __future__ import annotations

import tkinter as tk
from typing import NamedTuple

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

    EVERY WORD'S ROOM IS ITS BOLD WIDTH, kept whether it is lit or not.
    The one you are on is bold, and bold is wider: each holder used to
    be packed at its label's natural width, so selecting a place grew
    that word by a few pixels and pushed every word to its right along
    the bar — the sideways jump in the owner's clip of 1.0.3, on every
    change of place. The holder is now fixed at what the label asks for
    in bold, measured once off the label itself before anything is
    mapped, and the word is centred in it; the underline spans the
    holder, which is the bold word's width, as it always was.
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
                             font=(ui.UI, 11, "bold"), cursor="hand2")
            # A Label computes its geometry when it is configured, so the
            # two requests are real numbers here, before any mapping.
            wide, tall = label.winfo_reqwidth(), label.winfo_reqheight()
            label.configure(font=(ui.UI, 11))
            wide = max(wide, label.winfo_reqwidth())
            tall = max(tall, label.winfo_reqheight())
            # pady (0, 7) under the word and the 2 px underline: the same
            # height the holder used to take from its children.
            holder.configure(width=wide, height=tall + 7 + 2)
            holder.pack_propagate(False)
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

    def show_meta(self, on: bool) -> None:
        """The uptime, or nothing at all where it was.

        FORGOTTEN, not blanked. A label with no text still costs its own
        padding, and the caller asking for this is asking for the WIDTH
        back rather than for an empty space: measured 2026-09-08 on the
        top bar, blanking the text left the chip 8 px too wide to fit
        beside the places and forgetting the label gave back 17 more,
        which was the whole difference. Packed last, which is where it
        was, so turning it back on puts it back where it was.
        """
        if bool(on) == bool(self.meta.winfo_manager()):
            return
        if on:
            self.meta.pack(side="left", padx=(11, 0))
        else:
            self.meta.pack_forget()


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

class Pair(NamedTuple):
    """One correction as a PIECE of a line: what was heard, what is
    proposed instead.

    A line piece is normally a string. This is the one thing that is not,
    and it exists because the second-reading row had to be redesigned
    around the change rather than around the sentence. The owner, looking
    at the old row on 2026-09-07: "It's really hard for me to understand
    the corrections that appear on the home screen... I don't understand
    what's written here." The row drew the whole proposed sentence with
    the new word on a pill and the reason in 9 pt underneath, so the one
    thing he needed — WHICH WORD BECAME WHICH — was the one thing not on
    it. `ui.pair_pill` has drawn exactly that, for learned corrections,
    since the vocabulary panel was built; putting it inside a line means
    the row can say the change and then place it in its sentence.
    """

    heard: str
    meant: str


class Change(NamedTuple):
    """One proposed change, said the way Track Changes says it: what was
    heard on a red-edged pill, an arrow, and what is proposed on the gold
    one with a tick in it — IN ITS PLACE in the sentence.

    The Pair above says "which word became which" as a chip beside the
    sentence. The owner, 2026-09-21, on the row drawn that way: "it is
    really hard to understand where the mistake was — maybe I meant
    that"; and on a line through the heard word: "hard to read what it
    wants to fix — posh, I could also have said it is a U". So the heard
    word is whole and readable on its own pill, the arrow points at the
    proposal, and the tick says which of the two stays. The arrow points
    the way the line READS (a Hebrew row: heard on the right, arrow
    left, proposal on the left; an English row the mirror), and the tick
    sits at the proposal's leading edge, right after the arrow, in both.
    """

    heard: str
    meant: str


ARROW_RTL, ARROW_LTR, TICK = "\u2190", "\u2192", "\u2713"
CHANGE_PAD = 8          # inside a change's pills
CHANGE_GAP = 6          # pill · arrow · pill


def change_size(heard: str, meant: str, pt: int) -> tuple[int, int]:
    """How wide and how tall one Change is before it is drawn — the two
    pills, the arrow and the tick, measured with the bitmaps that will
    draw them (ui.draw_text is cached, so this costs the render once)."""
    widths, tall = 0, 0
    for text, is_pill in ((heard, True), (ARROW_LTR, False),
                          (TICK, False), (meant, True)):
        photo, height, _ = ui.draw_text(text, pt=pt, width=None, max_lines=1,
                                        colour=ui.FG, bg=ui.CARD,
                                        family=ui.TEXT)
        widths += photo.width() + (CHANGE_PAD * 2 if is_pill else 0)
        tall = max(tall, height + (6 if is_pill else 0))
    # the tick shares the proposal's pill (its pad is counted once) and
    # each of the three joints is a gap
    return widths + CHANGE_GAP * 3, tall


def _piece(piece) -> tuple:
    """(text, colour, pill) out of whatever a caller passed, so a short
    tuple is a missing pill and not a traceback in the middle of a
    repaint."""
    parts = tuple(piece) + (None, None, None)
    return parts[0], parts[1], parts[2]


def run_is_rtl(pieces) -> bool:
    """Which way a line built out of pieces reads.

    The same question `ui.is_rtl` answers for a string, asked of the
    strings in a line — and, when a line is nothing but a pair, of the
    two words in it. Guessing differently from the way the pieces are
    laid out is how a sentence ends up right-aligned and left-to-right at
    the same time.
    """
    words = " ".join(str(t) for t, _c, _p in map(_piece, pieces or ())
                     if isinstance(t, str))
    if not words.strip():
        words = " ".join(w for t, _c, _p in map(_piece, pieces or ())
                         if isinstance(t, (Pair, Change))
                         for w in (t.heard, t.meant))
    return ui.is_rtl(words)


def rtl_run(canvas, edge_x: int, y: int, pieces, bg: str, *,
            pt: int = 12, gap: int = 7, pill_pad: int = 9,
            radius: int = 6, keep=None, rtl: bool = True,
            band: int | None = None, pair_pt: int | None = None,
            pair_h: int | None = None) -> int:
    """A line laid out of SEVERAL bitmaps, so one word inside it can
    sit on a pill and one piece of it can be a correction pair.

    `pieces` is (text, colour, pill-or-None) in READING order — the
    piece read FIRST first — where `text` is a string or a `Pair`.
    `edge_x` is the right edge for a Hebrew line and the left edge for a
    Latin one (`rtl=`), and the return value is the width used either
    way.

    THE CAVEAT, and it is the whole reason this is not one draw_text
    call: the order BETWEEN segments is mine, not Windows'. Only split a
    line at a point where each fragment is one direction; a fragment
    that mixes Hebrew and Latin still goes through `ui.draw_text` whole,
    which is what puts its runs in the right order.

    `band` is the height of the strip the line sits in. Every piece is
    centred in it, which is what lets a 25 px pair pill and a 24 px text
    bitmap share a line without either of them hanging out of the row
    that owns it — a Canvas item is not clipped, it is simply drawn over
    whatever is under it. Without a band the line is as tall as its
    tallest piece and everything sits at `y`, which is what it always
    did.
    """
    # A pair's words are set two points under the sentence they sit in:
    # the pill has to fit the band with the text, and the pair is read as
    # a chip rather than as part of the line.
    pair_size_pt = pair_pt if pair_pt else pt - 2
    # (kind, what to draw, pill fill, width, the box it needs, its ink height)
    laid: list = []
    for piece in pieces or ():
        text, colour, pill = _piece(piece)
        if isinstance(text, Pair):
            if not (text.heard or text.meant):
                continue
            width, tall = ui.pair_size(text.heard, text.meant, pair_size_pt,
                                       pair_h)
            laid.append(("pair", text, None, width, tall, tall))
            continue
        if isinstance(text, Change):
            if not (text.heard and text.meant):
                continue
            width, tall = change_size(text.heard, text.meant, pt)
            laid.append(("change", text, None, width, tall, tall))
            continue
        if not text:
            continue
        face = pill or bg
        photo, height, _lines = ui.draw_text(str(text), pt=pt, width=None,
                                             max_lines=1, colour=colour,
                                             bg=face, family=ui.TEXT)
        if keep is not None:
            keep.append(photo)
        laid.append(("pill" if pill else "text", photo, pill,
                     photo.width() + (pill_pad * 2 if pill else 0),
                     height + (6 if pill else 0), height))
    if not laid:
        return 0
    room = band or max(box for _k, _o, _f, _w, box, _h in laid)

    x = edge_x
    for kind, thing, fill, width, box, inner in laid:
        box = min(box, room)
        box_y = y + max(0, (room - box) // 2)
        left = x if not rtl else x - width
        if kind == "pair":
            ui.pair_pill(canvas, left + width, box_y, thing.heard,
                         thing.meant, bg, size=pair_size_pt, height=box)
        elif kind == "change":
            _draw_change(canvas, left, box_y, width, box, thing, bg, pt,
                         rtl, keep)
        elif kind == "pill":
            canvas.create_image(left, box_y, anchor="nw",
                                image=ui.rounded(width, box, radius, fill,
                                                 bg))
            canvas.create_image(left + pill_pad,
                                box_y + max(0, (box - inner) // 2),
                                anchor="nw", image=thing)
        else:
            canvas.create_image(left, box_y + max(0, (box - inner) // 2),
                                anchor="nw", image=thing)
        x += (width + gap) * (-1 if rtl else 1)
    return abs(x - edge_x) - gap


def _draw_change(canvas, left: int, top: int, width: int, box: int,
                 change: Change, bg: str, pt: int, rtl: bool,
                 keep=None) -> None:
    """The three parts of a Change, in reading order across
    `left .. left + width`: the heard pill, the arrow, the proposal pill
    with its tick. `rtl` is the LINE's direction (the caller's), which is
    what decides which end is first and which way the arrow points — not
    the words' own script, so a Latin term in a Hebrew sentence sits
    where the Hebrew reader meets it, and the arrow still points on.

    Every item is tagged so a test (or a hover) can find the parts:
    ``change-heard``, ``change-arrow``, ``change-tick``, ``change-meant``.
    """
    def bitmap(text, colour, face):
        photo, height, _ = ui.draw_text(text, pt=pt, width=None, max_lines=1,
                                        colour=colour, bg=face,
                                        family=ui.TEXT)
        if keep is not None:
            keep.append(photo)
        return photo, height

    heard, heard_h = bitmap(change.heard, ui.RED, ui.RED_SOFT)
    arrow, _arrow_h = bitmap(ARROW_RTL if rtl else ARROW_LTR, ui.ACCENT, bg)
    tick, tick_h = bitmap(TICK, ui.ACCENT_TEXT, ui.ACCENT_SOFT)
    meant, meant_h = bitmap(change.meant, ui.FG, ui.ACCENT_SOFT)
    pill_h = min(box, max(heard_h, meant_h, tick_h) + 6)
    mid = top + box // 2

    # (width, painter) in reading order
    def pill(photo, fill, edge, tag, lead=None):
        inner = photo.width() + (lead.width() + CHANGE_GAP if lead else 0)
        w = inner + CHANGE_PAD * 2

        def paint(x):
            face = ui.rounded(w, pill_h, 8, fill, bg, edge)
            if keep is not None:
                keep.append(face)
            canvas.create_image(x, mid, anchor="w", image=face, tags=tag)
            # inside the pill: the lead (the tick) first in reading order
            parts = ([(lead, "change-tick")] if lead else []) + [(photo, tag)]
            if rtl:
                cx = x + w - CHANGE_PAD           # the right edge, inwards
                for img, t in parts:
                    canvas.create_image(cx, mid, anchor="e", image=img,
                                        tags=t)
                    cx -= img.width() + CHANGE_GAP
            else:
                cx = x + CHANGE_PAD
                for img, t in parts:
                    canvas.create_image(cx, mid, anchor="w", image=img,
                                        tags=t)
                    cx += img.width() + CHANGE_GAP
        return w, paint

    def glyph(photo, tag):
        def paint(x):
            canvas.create_image(x, mid, anchor="w", image=photo, tags=tag)
        return photo.width(), paint

    order = [pill(heard, ui.RED_SOFT, ui.RED, "change-heard"),
             glyph(arrow, "change-arrow"),
             pill(meant, ui.ACCENT_SOFT, ui.CHIP_ON_EDGE, "change-meant",
                  lead=tick)]
    # laid from the reading start: the right end of the box for RTL
    x = left + width if rtl else left
    for w, paint in order:
        if rtl:
            x -= w
            paint(x)
            x -= CHANGE_GAP
        else:
            paint(x)
            x += w + CHANGE_GAP


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


def row_text_room(width: int, buttons=()) -> int:
    """How much room a PileRow's words will really get, worked out BEFORE
    the row is built.

    PileRow measures its own buttons — it builds them, asks the frame how
    wide it came out and gives the text the rest — which is exact and is
    also far too late for the thing that needs the number. A row's words
    are now cut at a SENTENCE boundary (summary.py), and where that cut
    falls depends on the width; the cut is made where the spec is built,
    which is one screen away from any Tk widget. So this repeats
    PileRow's arithmetic from the same two constants, and takes 12 px of
    slack off the end: an estimate that comes out slightly narrow costs a
    few characters, and one that comes out wide would put a DrawTextW
    ellipsis on a sentence this whole exercise exists to deliver whole.
    """
    right = 0
    for entry in buttons or ():
        label, kind = (tuple(entry) + (None, None))[:2]
        try:
            right += (ui.text_width("\u2715", ui.UI, 11) + 14
                      if kind == "close"
                      else button_width(str(label), least=62) + 8)
        except Exception:             # noqa: BLE001 — no window yet
            # Every measurement in here is a question for Tk, and a spec
            # can be built before there is anything to ask (a test, a
            # first paint). Measured 2026-09-07, the pile's buttons are
            # 70 px of row for Yes and No, 79 for Fixed and Close, 95 for
            # Answer, 102 for Go there and 30 for the ✕ — so the guess
            # is the WIDEST of them. An estimate that comes out too wide
            # is the one that clips, and this is the branch that cannot
            # check.
            right += 30 if kind == "close" else 102
    return max(40, width - right - PileRow.BUTTON_GAP - PileRow.MARK_W - 12)


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

    # The three bands, as numbers rather than as arithmetic buried in the
    # constructor, because row_text_room repeats two of them and a
    # duplicated constant is a constant that drifts.
    MARK_W = 40          # the glyph's column at the reading-end edge
    BUTTON_GAP = 22      # air between the words and the first button
    EYEBROW_MID = 11     # a 9 pt line centred here: about 3..19
    BAND_TOP = 21        # where the words start under an eyebrow
    BARE_TOP = 6         # ...and where they start without one
    FOOT = 4             # the last pixel any band may use
    NOTE_PT = 9
    NOTE_GAP = 3
    LEAST_BAND = 20      # under this the note is dropped, not drawn

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
        stop = width - right.winfo_reqwidth() - self.BUTTON_GAP

        edge = max(40, stop - self.MARK_W)
        canvas = tk.Canvas(self, width=edge, height=height,
                           bg=bg, highlightthickness=0, bd=0)
        canvas.place(x=self.MARK_W, y=0)
        self.canvas = canvas

        # THE THREE BANDS ARE MEASURED FROM THE ROW, not counted up from
        # the top. A Canvas item does not clip: the note used to be
        # drawn at body + 30, which on a 72 px row put its bitmap at
        # 66..85 and simply lost it — the "why" of every second reading
        # was being rendered off the bottom of the row that owned it
        # (measured 2026-09-07). So the note is placed UP from the bottom
        # edge, the eyebrow down from the top, and what is left over —
        # the BAND — is handed to the words, which are then fitted to it
        # rather than assumed to fit. Measured on this machine, 2026-09-07:
        # a 9 pt drawn line is 19 px and a 12 pt one is 24, so a 72 px row
        # with all three bands leaves the words 25 px, which is why the
        # type steps down and the pair pill is capped instead of both
        # being written as constants that happen to work at one height.
        top = self.BAND_TOP if eyebrow else self.BARE_TOP
        foot = height - self.FOOT
        note_photo = None
        floor = foot
        if note:
            # Drawn at its NATURAL width and anchored, not drawn into a
            # box as wide as the row: a bitmap that wide carries the line
            # at whichever end its own direction puts it, so a Hebrew
            # reason landed under the right edge and an English one
            # ("and one more change   ·   ...") under the left, on rows
            # that were otherwise identical. The note is meta about the
            # row, so it belongs on the same edge as the eyebrow, which
            # is the other piece of meta — whatever language it is in.
            # `fit` is what keeps a long one inside the row, since a
            # natural-width bitmap has nothing to be clipped by.
            note_photo, note_h, _lines = ui.draw_text(
                fit(note, ui.TEXT, self.NOTE_PT, edge - 2),
                pt=self.NOTE_PT, width=None, max_lines=1,
                colour=ui.FAINT, bg=bg)
            note_y = foot - note_h
            if note_y - self.NOTE_GAP - top >= self.LEAST_BAND:
                floor = note_y - self.NOTE_GAP
            else:
                # A row too short to hold all three bands DROPS the note
                # rather than drawing it past its own bottom edge: outside
                # a canvas it is not clipped, it is invisible, and an
                # invisible line that the layout still believes in is the
                # bug this replaced.
                note_photo = None
        band = max(1, floor - top)
        self.band = band

        if eyebrow:
            canvas.create_text(edge if eyebrow_right else 0,
                               self.EYEBROW_MID, text=eyebrow,
                               anchor="e" if eyebrow_right else "w",
                               font=(ui.UI, 9), fill=ui.FAINT)
        if runs:
            pt = 12 if band >= 26 else (11 if band >= 24 else 10)
            rtl = run_is_rtl(runs)
            rtl_run(canvas, edge if rtl else 0, top, runs, bg, pt=pt,
                    band=band, rtl=rtl, pair_pt=pt - 2,
                    pair_h=min(band, ui.PILL_H), keep=self._keep)
        elif text:
            photo, drawn = self._fitted(text, edge, band,
                                        2 if note_photo is None else 1, bg)
            self._keep.append(photo)
            canvas.create_image(
                edge if ui.is_rtl(text) else 0,
                top + (0 if note_photo is not None
                       else max(0, (band - drawn) // 2)),
                anchor="ne" if ui.is_rtl(text) else "nw", image=photo)
        if note_photo is not None:
            self._keep.append(note_photo)
            canvas.create_image(edge if eyebrow_right else 0,
                                foot - note_photo.height(),
                                anchor="ne" if eyebrow_right else "nw",
                                image=note_photo)

    @staticmethod
    def _fitted(text: str, edge: int, band: int, most: int, bg: str):
        """The words, drawn at the largest size and the most lines that
        fit inside `band`.

        draw_text is cached on every argument, so asking it twice for the
        same string costs one render and one dictionary lookup — which is
        what makes trying a size and backing off cheaper than working the
        line height out in advance and being wrong about it.
        """
        photo = drawn = None
        for pt in (12, 11, 10, 9, 8):
            for lines in range(most, 0, -1):
                photo, drawn, _l = ui.draw_text(text, pt=pt, width=edge,
                                                max_lines=lines,
                                                colour=ui.FG, bg=bg)
                if drawn <= band:
                    return photo, drawn
        return photo, drawn


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
            # fit(), not clamp(): a single word wider than the room
            # takes clamp's other branch, which shaves characters and
            # says nothing about it.
            row.create_text(200, height / 2,
                            text=fit(text, ui.UI, 11, room), anchor="w",
                            font=(ui.UI, 11), fill=ui.DIM)
    if command is not None:
        row.bind("<Button-1>", lambda _e: command())
    return row


# -------------------------------------------------------- paint holding

# The Win32 half of PaintHold, declared on first use and on PRIVATE
# handles: ctypes.windll is process-global, and a restype declared on it
# changes that function for every module in the process (capture.py
# paid for that once — AGENTS.md). Nothing is declared at import.
_API = None


def _win32():
    global _API
    if _API is not None:
        return _API
    import ctypes
    import ctypes.wintypes as wt
    from types import SimpleNamespace

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    vp, num, unum = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint
    for lib, table in (
            (user32, (("GetDC", vp, [vp]),
                      ("ReleaseDC", num, [vp, vp]),
                      ("GetAncestor", vp, [vp, unum]),
                      ("GetWindow", vp, [vp, unum]),
                      ("ClientToScreen", wt.BOOL, [vp, vp]),
                      ("GetClientRect", wt.BOOL, [vp, vp]),
                      ("IsWindowVisible", wt.BOOL, [vp]),
                      ("IsIconic", wt.BOOL, [vp]),
                      ("GetWindowLongPtrW", ctypes.c_ssize_t, [vp, num]),
                      ("CreateWindowExW", vp, [wt.DWORD, wt.LPCWSTR,
                                               wt.LPCWSTR, wt.DWORD, num,
                                               num, num, num, vp, vp, vp,
                                               vp]),
                      ("DestroyWindow", wt.BOOL, [vp]),
                      ("ShowWindow", wt.BOOL, [vp, num]),
                      ("SetWindowPos", wt.BOOL, [vp, vp, num, num, num,
                                                 num, unum]),
                      ("UpdateLayeredWindow", wt.BOOL,
                       [vp, vp, vp, vp, vp, vp, wt.DWORD, vp, wt.DWORD]),
                      ("FillRect", num, [vp, vp, vp]))),
            (gdi32, (("CreateCompatibleDC", vp, [vp]),
                     ("CreateDIBSection", vp, [vp, vp, unum,
                                               ctypes.POINTER(vp), vp,
                                               wt.DWORD]),
                     ("SelectObject", vp, [vp, vp]),
                     ("DeleteObject", wt.BOOL, [vp]),
                     ("DeleteDC", wt.BOOL, [vp]),
                     ("BitBlt", wt.BOOL, [vp, num, num, num, num, vp, num,
                                          num, wt.DWORD]),
                     ("CreateSolidBrush", vp, [wt.DWORD]),
                     ("GdiFlush", wt.BOOL, [])))):
        for fname, res, args in table:
            fn = getattr(lib, fname)
            fn.restype, fn.argtypes = res, args

    class Header(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG),
                    ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    _API = SimpleNamespace(user32=user32, gdi32=gdi32, ctypes=ctypes,
                           wt=wt, Header=Header)
    return _API


class PaintHold:
    """A picture of a widget, held over it while it is rebuilt underneath.

    What browsers call paint holding: the old page stays on the screen
    until the new one is ready, and then the new one is there in one
    step. The desk used to build a screen and let the eye watch it
    happen — a blank pane, then a half-built one, then the whole one,
    all while it slid (the owner's clip of 1.0.3, 2026-09-22).

    THE COVER IS A WINDOW OF ITS OWN, NOT A WIDGET ON THE PANE. Under the
    compositor every top-level window paints into a surface of its own,
    and a window lying over another does not stop that one painting —
    so the new screen draws itself completely, in the desk's own
    surface, while the picture of the old one lies on top. A Tk child
    laid over the pane could not do that: children share their window's
    surface and clip one another, so everything under a child cover
    stays unpainted until the cover goes, and the new screen then paints
    in the open, which is the very thing this is for. Measured both ways
    on 2026-09-22 with a sampler photographing the window every 8 ms: a
    Label cover left 0-9 half-built frames per switch (Settings 7-9),
    this window none on any switch — AGENTS.md's trap on paint holding.

    It is a layered popup of the system's "Static" class, owned by the
    desk's frame so that it always sits just above it and never above
    anyone else, never activating (WS_EX_NOACTIVATE, SWP_NOACTIVATE) and
    click-through (WS_EX_TRANSPARENT): a click during a switch lands on
    the new screen underneath, which is where the one after the switch
    would have landed anyway. Its pixels are handed over whole with
    UpdateLayeredWindow, so it has nothing to paint and no message to
    wait for.

    Everything here answers False or does nothing when it cannot — a
    window that is not on the screen, a Windows that refuses — and the
    caller then builds the way it did before this existed.
    """

    GA_ROOT = 2
    GW_HWNDPREV = 3
    SRCCOPY = 0x00CC0020
    ULW_OPAQUE = 0x00000004
    SW_HIDE = 0
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER = 0x0001, 0x0002, 0x0004
    SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0010, 0x0040
    SWP_NOOWNERZORDER = 0x0200
    WS_POPUP = 0x80000000
    WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
    WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = 0x08000000, 0x00000080
    WS_EX_TOPMOST, GWL_EXSTYLE = 0x00000008, -20

    def __init__(self, widget, bg: str) -> None:
        self.widget = widget
        self._bg = bg
        self.hwnd = None          # the cover window, once one was needed
        self._owner = None
        self.up = False           # the cover is on the screen
        self._size = (0, 0)
        self._at = (0, 0)
        # [0] what the cover shows, [1] the new screen's picture: each a
        # (memory DC, DIB section, the bitmap it replaced, its bits)
        self._buffers: list = []

    # -- where the widget is

    def _where(self):
        """(hwnd, owner, x, y, w, h) of the widget on the screen, or None
        when it is not there to be seen — withdrawn, minimised, not yet
        mapped, or a desktop that never maps it (GitHub's runner)."""
        try:
            if not self.widget.winfo_viewable():
                return None
            hwnd = int(self.widget.winfo_id())
        except tk.TclError:
            return None
        api = _win32()
        owner = api.user32.GetAncestor(hwnd, self.GA_ROOT)
        if not owner or api.user32.IsIconic(owner) \
                or not api.user32.IsWindowVisible(owner):
            return None
        rect = api.wt.RECT()
        point = api.wt.POINT(0, 0)
        if not api.user32.GetClientRect(hwnd, api.ctypes.byref(rect)) \
                or not api.user32.ClientToScreen(hwnd,
                                                 api.ctypes.byref(point)):
            return None
        if rect.right <= 0 or rect.bottom <= 0:
            return None
        return hwnd, owner, point.x, point.y, rect.right, rect.bottom

    def _ready(self, width: int, height: int) -> bool:
        if self._size == (width, height) and len(self._buffers) == 2:
            return True
        self._free()
        api = _win32()
        head = api.Header()
        head.biSize = api.ctypes.sizeof(head)
        head.biWidth, head.biHeight = width, -height      # top-down rows
        head.biPlanes, head.biBitCount = 1, 32
        for _ in range(2):
            dc = api.gdi32.CreateCompatibleDC(None)
            bits = api.ctypes.c_void_p()
            dib = api.gdi32.CreateDIBSection(dc, api.ctypes.byref(head), 0,
                                             api.ctypes.byref(bits), None, 0)
            if not dc or not dib:
                if dib:
                    api.gdi32.DeleteObject(dib)
                if dc:
                    api.gdi32.DeleteDC(dc)
                self._free()
                return False
            old = api.gdi32.SelectObject(dc, dib)
            self._buffers.append((dc, dib, old, bits))
        self._size = (width, height)
        return True

    def _grab(self, hwnd, index: int) -> bool:
        """The widget's own surface, as it stands, into buffer `index`.
        Read from the window's DC, which the compositor keeps whole even
        where another window lies over it — 1-2 ms at the pane's size."""
        api = _win32()
        width, height = self._size
        api.gdi32.GdiFlush()      # this thread's queued drawing, landed
        dc = api.user32.GetDC(hwnd)
        if not dc:
            return False
        try:
            return bool(api.gdi32.BitBlt(self._buffers[index][0], 0, 0,
                                         width, height, dc, 0, 0,
                                         self.SRCCOPY))
        finally:
            api.user32.ReleaseDC(hwnd, dc)

    def _present(self) -> bool:
        api = _win32()
        point = api.wt.POINT(*self._at)
        size = api.wt.SIZE(*self._size)
        origin = api.wt.POINT(0, 0)
        return bool(api.user32.UpdateLayeredWindow(
            self.hwnd, None, api.ctypes.byref(point), api.ctypes.byref(size),
            self._buffers[0][0], api.ctypes.byref(origin), 0, None,
            self.ULW_OPAQUE))

    # -- the three moves

    def cover(self) -> bool:
        """Photograph the widget as it stands and lay the picture exactly
        over it. False when that cannot be done — and then nothing is
        left up, not even a cover still standing from the last switch."""
        if not self._cover():
            self.lift()
            return False
        return True

    def _cover(self) -> bool:
        try:
            where = self._where()
            if where is None:
                return False
            hwnd, owner, x, y, width, height = where
            if not self._ready(width, height) or not self._grab(hwnd, 0):
                return False
            api = _win32()
            if self.hwnd is not None and self._owner != owner:
                self._destroy_window()
            if self.hwnd is None:
                self.hwnd = api.user32.CreateWindowExW(
                    self.WS_EX_LAYERED | self.WS_EX_TRANSPARENT
                    | self.WS_EX_NOACTIVATE | self.WS_EX_TOOLWINDOW,
                    "Static", "", self.WS_POPUP, x, y, width, height,
                    owner, None, None, None)
                if not self.hwnd:
                    self.hwnd = None
                    return False
                self._owner = owner
            self._at = (x, y)
            if not self._present():
                self.lift()
                return False
            # Just above the desk's own frame in the z-order: never above
            # a window that was above the desk, whichever app it is. A
            # topmost one just above it (the status dot) means the desk
            # leads the ordinary windows, and the top of those is right.
            above = api.user32.GetWindow(owner, self.GW_HWNDPREV)
            if above and api.user32.GetWindowLongPtrW(
                    above, self.GWL_EXSTYLE) & self.WS_EX_TOPMOST:
                above = None
            flags = (self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE
                     | self.SWP_SHOWWINDOW | self.SWP_NOOWNERZORDER)
            if above == self.hwnd:
                flags |= self.SWP_NOZORDER
            api.user32.SetWindowPos(self.hwnd, above or None, 0, 0, 0, 0,
                                    flags)
            self.up = True
            return True
        except Exception:                 # noqa: BLE001 — never fatal
            self.lift()
            return False

    def take(self) -> bool:
        """Photograph the widget again, under the cover: the finished new
        screen, which the arrival frames are cut from."""
        if not self.up:
            return False
        try:
            where = self._where()
            if where is None or (where[4], where[5]) != self._size:
                return False
            return self._grab(where[0], 1)
        except Exception:                 # noqa: BLE001
            return False

    def show(self, offset: int) -> bool:
        """The new picture on the cover, `offset` px low, the ground
        above it: one frame of the new screen arriving. A frame is two
        GDI copies and one UpdateLayeredWindow — nothing Tk draws."""
        if not self.up:
            return False
        try:
            api = _win32()
            width, height = self._size
            offset = max(0, min(int(offset), height))
            front, new = self._buffers[0][0], self._buffers[1][0]
            if offset:
                colour = _rgb(self._bg)
                brush = api.gdi32.CreateSolidBrush(
                    colour[0] | (colour[1] << 8) | (colour[2] << 16))
                try:
                    band = api.wt.RECT(0, 0, width, offset)
                    api.user32.FillRect(front, api.ctypes.byref(band), brush)
                finally:
                    api.gdi32.DeleteObject(brush)
            api.gdi32.BitBlt(front, 0, offset, width, height - offset, new,
                             0, 0, self.SRCCOPY)
            return self._present()
        except Exception:                 # noqa: BLE001
            return False

    def lift(self) -> None:
        """Take the cover away. What lies under it is what it showed."""
        self.up = False
        if self.hwnd is not None:
            try:
                _win32().user32.ShowWindow(self.hwnd, self.SW_HIDE)
            except Exception:             # noqa: BLE001
                pass

    # -- for a test, or a measurement

    def picture(self, index: int = 0):
        """(width, height, BGRA bytes) of buffer `index` — what the cover
        shows, or the new screen's picture — or None."""
        if len(self._buffers) != 2:
            return None
        width, height = self._size
        bits = self._buffers[index][3]
        return width, height, _win32().ctypes.string_at(bits.value,
                                                        width * height * 4)

    def surface(self):
        """(width, height, BGRA bytes) of the widget's own surface right
        now, under the cover or not — or None."""
        try:
            where = self._where()
            if where is None or not self._ready(where[4], where[5]):
                return None
            # buffer 1 is scratch outside a switch; inside one it is the
            # picture of the new screen, which is what the surface holds
            return self.picture(1) if self._grab(where[0], 1) else None
        except Exception:                 # noqa: BLE001
            return None

    # -- the end

    def _destroy_window(self) -> None:
        if self.hwnd is not None:
            try:
                _win32().user32.DestroyWindow(self.hwnd)
            except Exception:             # noqa: BLE001
                pass
        self.hwnd = None
        self._owner = None
        self.up = False

    def _free(self) -> None:
        if not self._buffers:
            return
        api = _win32()
        for dc, dib, old, _bits in self._buffers:
            try:
                api.gdi32.SelectObject(dc, old)
                api.gdi32.DeleteObject(dib)
                api.gdi32.DeleteDC(dc)
            except Exception:             # noqa: BLE001
                pass
        self._buffers = []
        self._size = (0, 0)

    def close(self) -> None:
        """The window and the two pictures, released; safe twice."""
        self._destroy_window()
        self._free()
