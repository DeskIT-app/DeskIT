"""Settings said as sentences, with the controls inside the words.

A settings screen is a column of labels and a column of controls, and
the label is always a noun phrase — "Punctuate every dictation" — which
tells you what the line is called and nothing about what happens if you
change it. The same forty lines read as sentences say the whole thing:
*Punctuate every dictation [no]; when you press the punctuate key, ask
[Groq] first, wait at most [6] seconds, and [leave out] the vowel
points.* The control is the word.

Forty lines here; the other hundred and fifty are still said in full,
on Everything, which is what `tests.py` holds the two screens to
between them.

WHY A CANVAS AND NOT A `tk.Text`. Both were built and photographed side
by side (`r3/spikes/proto_c.png`). `tk.Text` + `window_create` wraps for
free and even stays read-only with its embedded controls live — but a
display line holding a 28 px control is 28 px tall and a plain one is
~18, `spacing1`/`spacing2` add to both, and the ragged rhythm that
results is not tunable. A hand-flowed Canvas is 21 ms instead of 32 and
gives a **fixed 34 px line**, which is what makes a paragraph of
controls read as a paragraph. Two things it must do that the Text did
for free, and both are one line each here: a control never straddles a
line (it is placed whole or moved down whole), and a control wider than
the column is clamped rather than hanging off the edge.

The sentences are the only thing in this file typed by hand — the same
rule `settings.py:12` states about its labels. Every `Bit` names a real
path in `config.toml`; `paths()` is what a test walks to prove it.
"""
from __future__ import annotations

import tkinter as tk

import ui

LINE_H = 34              # the fixed rhythm; the whole reason for the Canvas
PARA_GAP = 18            # between two sentences of one block
BLOCK_GAP = 26           # above a block's eyebrow
EYEBROW_H = 28


class Bit:
    """One control, inside a sentence.

    `names` overrides the choices the file offers with words a person
    reads — `settings.py` already carries those for the lines it says
    plainly, and this is the same idea one layer in.
    """

    __slots__ = ("path", "names", "width")

    def __init__(self, path: str, names=None, width: int | None = None):
        self.path = path
        self.names = names
        self.width = width


# The words. Each block is (eyebrow, [sentence, ...]) and a sentence is
# a list of strings and Bits, in reading order.
YES_NO = (("true", "yes"), ("false", "no"))

BLOCKS: tuple = (
    ("when you dictate", [
        ["Transcribe ", Bit("backend", (("local", "on this computer"),
                                        ("gemini", "in the cloud"),
                                        ("fake", "not at all — test mode"))),
         " through the ", Bit("audio.device", width=260),
         ", and ", Bit("auto_language", (("true", "notice"),
                                         ("false", "do not notice"))),
         " when a sentence is English."],
        ["A hold under ", Bit("min_seconds"),
         " seconds was an accident and is thrown away; past ",
         Bit("max_seconds"),
         " it stops on its own. Locked on, the limit is ",
         Bit("latch_max_seconds"), " seconds — 0 is none."],
        ["Show the key card while a key is held ",
         Bit("hint.enabled", YES_NO), " — after ", Bit("hint.after_ms"),
         " ms, ", Bit("hint.corner"), ", at ", Bit("hint.scale"), "×."],
    ]),
    ("after it lands", [
        ["Fix misheard words ", Bit("polish.when",
                                    (("never", "never"),
                                     ("known", "only the taught ones"),
                                     ("always", "always"))),
         ", and keep learning while you are away ",
         Bit("study.enabled", YES_NO), " after ", Bit("study.idle_minutes"),
         " minutes of quiet."],
        ["Punctuate every dictation ", Bit("punctuate.auto", YES_NO),
         "; when you press the punctuate key, ask ",
         Bit("punctuate.prefer", (("groq", "Groq — fast, free tier"),
                                  ("gemini", "Gemini"),
                                  ("ollama", "Ollama, on this computer"))),
         " first, wait at most ", Bit("punctuate.max_wait_s"),
         " seconds, and ", Bit("punctuate.nikud", (("true", "add"),
                                                   ("false", "leave out"))),
         " the vowel points."],
        ["Mark the cursor with ", Bit("feedback.placeholder"),
         " while it transcribes ", Bit("feedback.enabled", YES_NO),
         ", paste with ", Bit("paste_chord"), ", and translate into ",
         Bit("translate.target"), "."],
    ]),
    ("on the desk", [
        ["Ask about the screen ", Bit("visual_qa.enabled", YES_NO),
         ", read the answer aloud ",
         Bit("visual_qa.speak", (("off", "never"), ("button", "on a button"),
                                 ("auto", "always"))),
         ", and let a screenshot leave this computer ",
         Bit("visual_qa.allow_screenshot_upload", YES_NO), "."],
        ["After a screenshot, ",
         Bit("capture.after_shot", (("toast", "show a small card"),
                                    ("editor", "open the editor"),
                                    ("nothing", "do nothing"))),
         " and put the picture on the clipboard ",
         Bit("capture.copy_to_clipboard", YES_NO), "; save the file every "
         "time ", Bit("capture.always_save", YES_NO), "."],
        ["Record at ", Bit("capture.fps"), " frames a second, ",
         Bit("capture.quality", (("small", "small"),
                                 ("balanced", "balanced"),
                                 ("sharp", "sharp"))),
         ", with the microphone ", Bit("capture.audio", (("off", "off"),
                                                         ("mic", "on"))),
         ", and stop after ", Bit("capture.max_minutes"), " minutes."],
        ["The camera waits ", Bit("camera.timer"), " seconds, is ",
         Bit("camera.mirror", (("true", "mirrored"),
                               ("false", "not mirrored"))),
         ", and opens the photo in the editor ",
         Bit("camera.edit_after_shot", YES_NO), "."],
        ["Keep the dot in the corner ", Bit("indicator", YES_NO),
         ", and let the report key attach the evidence itself ",
         Bit("problems.shot", YES_NO), "."],
    ]),
    ("the phone", [
        ["Dictate from the phone ", Bit("server.enabled", YES_NO),
         " on port ", Bit("server.port"),
         " — over Tailscale; the link is under The app, below."],
        ["A finish rings ", Bit("notify.enabled", YES_NO), ", with a sound ",
         Bit("notify.cue", YES_NO), ", and waits ", Bit("notify.quiet_s"),
         " seconds for the session that sent it to go quiet first."],
    ]),
)


def paths() -> list[str]:
    """Every config.toml line these sentences say. What a test walks."""
    out = []
    for _eyebrow, sentences in BLOCKS:
        for sentence in sentences:
            for piece in sentence:
                if isinstance(piece, Bit):
                    out.append(piece.path)
    return out


def matches(query: str) -> set[str]:
    """The blocks whose words or paths hold `query` — so the search
    field can jump to the sentence rather than only to Everything."""
    query = (query or "").strip().lower()
    if not query:
        return set()
    hit = set()
    for eyebrow, sentences in BLOCKS:
        for sentence in sentences:
            words = "".join(p if isinstance(p, str) else p.path
                            for p in sentence).lower()
            if query in words or query in eyebrow.lower():
                hit.add(eyebrow)
    return hit


# ------------------------------------------------------------- the flow

class Flow:
    """A paragraph laid out by hand on a Canvas.

    Words are measured with `ui.text_width` and placed at a fixed line
    height; a widget is measured with `winfo_reqwidth` and moved down
    whole when it does not fit. `height` is what the caller sizes the
    canvas to afterwards — nothing here can know it up front, which is
    the one thing a `tk.Text` did better.
    """

    def __init__(self, canvas, width: int, *, bg: str,
                 line_h: int = LINE_H, size: int = 11, y: int = 0):
        self.canvas = canvas
        self.width = width
        self.bg = bg
        self.line_h = line_h
        self.size = size
        self.x = 0
        self.y = y
        self.space = ui.text_width(" ", ui.UI, size)
        self.widgets: list = []

    # -- pen

    def newline(self) -> None:
        self.x = 0
        self.y += self.line_h

    def gap(self, pixels: int) -> None:
        if self.x:
            self.newline()
        self.y += pixels

    @property
    def height(self) -> int:
        return self.y + (self.line_h if self.x else 0)

    # -- content

    def eyebrow(self, text: str) -> None:
        self.gap(0)
        self.canvas.create_text(0, self.y + 8, text=text, anchor="nw",
                                font=(ui.MEDIUM, 9),
                                fill=getattr(ui, "ACCENT_TEXT", ui.AMBER))
        self.y += EYEBROW_H
        self.x = 0

    def words(self, text: str, *, colour: str | None = None) -> None:
        """One run of words, with EXACTLY the spaces the run is written
        with.

        The pen used to add a space after every word and another for
        every empty fragment `split(" ")` leaves at the ends, and the
        control below added one more of its own — so "Transcribe " came
        out with two spaces before its menu and "; when you press" with
        one before its semicolon. Photographed 2026-09-07 and visible in
        every sentence on the screen.

        The rule now: a space is the SEPARATOR between two fragments, so
        n fragments put n-1 spaces down, and a run written with a
        leading or trailing space says so with an empty fragment there.
        The sentences in BLOCKS carry all their own spacing that way,
        which is why `control` adds none.
        """
        for index, word in enumerate(text.split(" ")):
            if index:
                self.x += self.space
            if not word:
                continue
            width = ui.text_width(word, ui.UI, self.size)
            if self.x and self.x + width > self.width:
                self.newline()
            self.canvas.create_text(self.x, self.y + self.line_h / 2,
                                    text=word, anchor="w",
                                    font=(ui.UI, self.size),
                                    fill=colour or ui.FG)
            self.x += width

    def control(self, widget) -> None:
        widget.update_idletasks()
        width = min(widget.winfo_reqwidth(), self.width)
        if self.x and self.x + width > self.width:
            self.newline()
        self.canvas.create_window(self.x, self.y + self.line_h / 2,
                                  anchor="w", window=widget, width=width)
        self.widgets.append(widget)
        # No trailing space: the words that follow carry their own, and
        # a comma or a "×" that is written hard against the control is
        # meant to be drawn hard against it.
        self.x += width


def flow_block(canvas, width: int, eyebrow: str, sentences, *, bg: str,
               make, y: int = 0, size: int = 11) -> int:
    """One block — the eyebrow and its sentences — onto `canvas`.

    `make(bit)` builds the control for a Bit and returns the widget, or
    None when the path is not in this config.toml (an older file, or a
    branch without the section): the sentence then says the words and
    quietly leaves the control out, rather than refusing to draw.
    """
    pen = Flow(canvas, width, bg=bg, y=y, size=size)
    pen.eyebrow(eyebrow)
    for index, sentence in enumerate(sentences):
        if index:
            pen.gap(PARA_GAP)
        for piece in sentence:
            if isinstance(piece, str):
                pen.words(piece)
            else:
                widget = make(piece)
                if widget is not None:
                    pen.control(widget)
    return pen.height
