"""Every line of config.toml, as data a screen can draw.

The Settings screen used to be three rows typed by hand — engine, mic,
vocabulary — and one switch, in front of a file with a hundred and thirty
settings in it. The owner's rule for its replacement, in his words: show
all of them, so that a setting one person uses and another does not never
quietly drops off. So nothing on that screen is typed by hand any more.
The file IS the list: every assignment in it becomes a row, the comment
around it becomes the row's help, and an `a | b | c` at the front of that
comment becomes the row's choices. A setting added to config.toml is on
the screen the moment the file is saved, and there is no second list to
forget to update. The one thing typed by hand is the words — TABS, at
the bottom of this file: which lines get a plain label, a sentence and
a menu with names on it. They name lines the file has (a test checks),
and everything they do not name is still on the screen, on the tab that
owns its section (TAB_SECTIONS), said with the plain words at the
bottom of this file rather than the file's own — and each line is drawn
exactly once, which a test holds.

TWO PARSERS, ON PURPOSE. tomllib reads the values — it is the parser the
app itself trusts, and a value read any other way could disagree with the
one the app runs on. The line scan below reads only what tomllib throws
away: which line a key sits on, and the comments around it. The two are
reconciled by key, and tests.py asserts that every key tomllib found is
one the scan found too — so a line the scan misreads is a red test and
not a setting that silently vanished from the screen.

WHAT IS ON TOP, AND WHAT IS BEHIND ONE LINE. The owner, 2026-09-07:
"I would reduce some of the settings. There are things there that I just
don't need." Nothing may be deleted — his other rule, from 2026-09-01, is
"show all of them" — so every card shows its COMMON lines and folds the
rest behind one quiet line at its foot ("7 more in this section") that
opens them in place. `common()` decides, off the file rather than off a
list of paths: a line a tab names by hand is common, and so is a line
that is a CHOICE — a switch, or a menu; everything else is a
MEASUREMENT — a number, a length of time, a model name, a folder — and
folds. `fold()` is the split, and it refuses to fold fewer than
FOLD_MIN lines, because one hidden row costs more room than it saves.

WHAT COUNTS AS A COMMENT, HERE. The file has three kinds and all three
are read. The block right under a `[section]` header describes the
section. An unindented block directly above a key, with no blank line
between, introduces that key. And the comment after the value, plus every
INDENTED comment line that follows it, is the key's own — that is how the
file lines its comments up. A bare `#` is a paragraph break. The block
at the very top of the file, before any key, is the general section's:
it introduces the file, not `hotkey`.

Writing is not done here. That is config.set_values, the line editor that
keeps every one of these comments — a TOML round-trip would delete the
measurements the file is made of.
"""
from __future__ import annotations

import dataclasses
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_HEADER = re.compile(r"^\[([A-Za-z_][\w.-]*)\]\s*(#.*)?$")
_ASSIGN = re.compile(r"^([A-Za-z_][\w-]*)\s*=\s*(.*)$")
# "gemini | local | fake" at the very front of a key's comment is a menu.
_CHOICES = re.compile(r"^\s*((?:[\w./+-]+\s*\|\s*)+[\w./+-]+)")


@dataclass(frozen=True)
class Setting:
    section: str           # "" for the top of the file
    key: str
    value: object          # as tomllib read it
    kind: str              # bool | int | float | str | list
    help: str              # paragraphs joined with "\n"
    choices: tuple[str, ...]
    line: int              # 1-based, in config.toml

    @property
    def path(self) -> str:
        """The dotted name config.set_values writes to."""
        return f"{self.section}.{self.key}" if self.section else self.key

    @property
    def editable(self) -> bool:
        """A list is edited in the file — the line editor writes scalars —
        and so is a Hebrew string: Tk has no bidi caret (see ui.py), and a
        field that reverses what you type is worse than no field. A
        consent gate is edited by nobody: it opens through its card and
        closes with Withdraw (config.CONSENT_KEYS, D7)."""
        if self.kind == "list" or self.consent:
            return False
        return not (self.kind == "str" and is_rtl(str(self.value)))

    @property
    def consent(self) -> bool:
        """One of the six [privacy] gates — drawn read-only with the date
        it was granted, never as a switch."""
        return self.section == "privacy" and self.key in CONSENT_GATES


#: The six gates of [privacy] (privacy.KINDS, spelled here so this module
#: keeps importing nothing but the standard library).
CONSENT_GATES: frozenset[str] = frozenset({
    "cloud_text", "cloud_audio", "cloud_screenshots",
    "account", "report_upload", "settings_sync",
})


@dataclass(frozen=True)
class Section:
    name: str
    help: str
    settings: tuple[Setting, ...]
    line: int

    @property
    def title(self) -> str:
        return self.name or "general"


def kind_of(value) -> str:
    if isinstance(value, bool):          # before int: a bool IS an int
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, (list, tuple)):
        return "list"
    return "str"


def is_rtl(text: str) -> bool:
    """Decided by the first letter, the way a bidi layout decides it."""
    for ch in text:
        if "֐" <= ch <= "ࣿ":
            return True
        if ch.isalpha():
            return False
    return False


def _comment_at(rest: str) -> int | None:
    """Index of the '#' that starts a trailing comment, ignoring any '#'
    inside a quoted value. None if the line has no comment. The same
    rule config.set_values reads the file by."""
    quote = ""
    i = 0
    while i < len(rest):
        char = rest[i]
        if quote:
            if char == "\\" and quote == '"':
                i += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#":
            return i
        i += 1
    return None


def _bare(line: str) -> str:
    text = line.strip()
    return text[1:].strip() if text.startswith("#") else text


def _join(lines: list[str]) -> str:
    """Comment lines to text: a run joins with spaces, a bare '#' breaks
    the paragraph."""
    out: list[str] = []
    para: list[str] = []
    for raw in lines:
        text = _bare(raw)
        if not text:
            if para:
                out.append(" ".join(para))
                para = []
            continue
        para.append(text)
    if para:
        out.append(" ".join(para))
    return "\n".join(out)


def _choices(trailing: str) -> tuple[tuple[str, ...], str]:
    """(the menu, the comment with the menu taken off the front).

    The chips show the choices, so the help does not have to repeat
    "gemini | local | fake" before saying anything; what follows the menu
    — after its full stop or dash — is the help."""
    text = _bare(trailing) if trailing else ""
    match = _CHOICES.match(text) if text else None
    if not match:
        return (), text
    # "gemini | ollama." — the sentence's full stop is not part of a name.
    choices = tuple(part.strip().rstrip(".,;:")
                    for part in match.group(1).split("|"))
    rest = text[match.end():].lstrip(" .,;:—–-")
    return choices, rest


def read(path: Path | str, overrides: dict | None = None) -> list[Section]:
    """The file, section by section, in the order it is written.

    `overrides` is the person's layer (config.read_settings plus
    config.read_state, dotted keys): a setting whose path is in it shows
    THAT value, the help and the choices still come from the file. This
    is how the page shows what the app actually runs on while the file
    it is generated from stays the untouched defaults.toml (D2)."""
    sections = _read(path)
    if not overrides:
        return sections
    out: list[Section] = []
    for section in sections:
        rows = tuple(
            dataclasses.replace(s, value=overrides[s.path])
            if s.path in overrides else s
            for s in section.settings)
        out.append(dataclasses.replace(section, settings=rows))
    return out


def _read(path: Path | str) -> list[Section]:
    raw = Path(path).read_text("utf-8")
    data = tomllib.loads(raw)
    lines = raw.splitlines()

    sections: list[Section] = []
    name, sec_line = "", 1
    sec_help: list[str] = []
    settings: list[Setting] = []
    intro: list[str] = []          # unindented block above the next key
    pending: dict | None = None    # the last key, still taking its comments
    in_header = True               # the top of the file introduces "general"
    in_list = False                # inside a multi-line [ ... ]

    def value_of(key: str, number: int):
        table = data[name] if name else data
        if not isinstance(table, dict) or key not in table:
            raise ValueError(f"{Path(path).name} line {number}: {key!r} is not a "
                             f"key tomllib found under [{name}]")
        return table[key]

    def flush() -> None:
        nonlocal pending
        if pending is None:
            return
        value = pending["value"]
        kind = kind_of(value)
        choices, trailing = (_choices(pending["trailing"]) if kind == "str"
                             else ((), _bare(pending["trailing"])))
        own = ([trailing] if trailing else []) + pending["cont"]
        settings.append(Setting(
            section=name, key=pending["key"], value=value, kind=kind,
            help=_join(pending["intro"] + own), choices=choices,
            line=pending["line"]))
        pending = None

    def close_section() -> None:
        flush()
        sections.append(Section(name, _join(sec_help), tuple(settings),
                                sec_line))

    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if in_list:
            if stripped.startswith("]"):
                in_list = False
            continue
        header = _HEADER.match(stripped)
        if header:
            close_section()
            name, sec_line = header.group(1), number
            sec_help, settings, intro = [], [], []
            in_header = True
            continue
        if not stripped:
            # A blank line ends whatever block was being collected.
            flush()
            in_header = False
            intro = []
            continue
        if stripped.startswith("#"):
            if in_header:
                sec_help.append(line)
            elif pending is not None and line[:1].isspace():
                pending["cont"].append(line)
            else:
                flush()
                intro.append(line)
            continue
        match = _ASSIGN.match(stripped)
        if not match:
            flush()
            intro = []
            continue
        flush()
        in_header = False
        key, rest = match.group(1), match.group(2)
        at = _comment_at(rest)
        code = rest if at is None else rest[:at]
        trailing = "" if at is None else rest[at:].rstrip()
        if code.strip().startswith("[") and "]" not in code:
            in_list = True
        pending = {"key": key, "line": number, "value": value_of(key, number),
                   "trailing": trailing, "intro": intro, "cont": []}
        intro = []
    close_section()
    return sections


def flatten(sections: list[Section]) -> list[Setting]:
    return [s for section in sections for s in section.settings]


def find(sections: list[Section], path: str) -> Setting | None:
    for setting in flatten(sections):
        if setting.path == path:
            return setting
    return None


def matches(setting: Setting, query: str) -> bool:
    """The search box: a word in what the SCREEN says — the plain title,
    the plain sentence, the plain name of its section — or a word in what
    the FILE says, its dotted name and its comment.

    Both, because the two audiences are the same person on different
    days: "the card while I hold the key" one day and `hint.after_ms` the
    next, and neither should come back empty."""
    query = (query or "").strip().lower()
    if not query:
        return True
    words = words_for(setting)
    hay = " ".join((setting.path, setting.help, words.label, words.help,
                    section_words(setting.section).label)).lower()
    return all(word in hay for word in query.split())


# --------------------------------------------------------------- the words
#
# What the Settings screen SAYS for the lines most people touch. This is
# the one hand-written thing about that screen — a tab, a group, a plain
# label, one short sentence, and for a menu what each value is called —
# and it decides only what is said FIRST, and how. Every path here has to
# exist in the file (tests.py checks), and every line of the file that is
# not here is still on the screen, on the tab that owns its section,
# with the plain words below as its title and help. Nothing can be
# dropped; it can only be said by hand or said by its section.
#
# The owner's brief, 2026-09-01, after the first version showed him all
# hundred and forty lines at once: tabs across the top, plain words, a
# menu he can pick from wherever a value names a model, and "just set the
# things I do not need to change" — which is what General is for.


@dataclass(frozen=True)
class Friendly:
    path: str
    label: str
    help: str = ""
    # value -> what to call it on the menu. () = the file's own choices,
    # or a field when the file has none.
    names: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Group:
    title: str
    rows: tuple[Friendly, ...]


@dataclass(frozen=True)
class Tab:
    name: str
    groups: tuple[Group, ...]


GENERAL = "General"
APP = "The app"           # the blocks that used to be screens, and [awake]
ADVANCED = "Advanced"     # only ever drawn for a section no tab owns

_ENGINES = (("local", "On this computer"),
            ("gemini", "In the cloud (Gemini)"),
            ("fake", "Fake, for testing"))
_REPAIR = (("always", "Always"),
           ("known", "Only taught words"),
           ("never", "Never"))
_PUNCTUATORS = (("groq", "Groq — fast, free tier"),
                ("gemini", "Gemini"),
                ("ollama", "Ollama, on this computer"))
_CORNERS = (("top-right", "Top right"), ("top-left", "Top left"),
            ("bottom-right", "Bottom right"), ("bottom-left", "Bottom left"))
# The two corners the status dot may sit in, and the cards' menu with
# "beside the dot" in front of the four — what `corner = "dot"` says.
_DOT_CORNERS = (("bottom-right", "Bottom right"), ("top-right", "Top right"))
_CARD_CORNERS = (("dot", "Beside the dot"),) + _CORNERS
_SPEAK = (("off", "Never"), ("button", "With a button"), ("auto", "Always"))
_AFTER_SHOT = (("toast", "Show a small card"), ("editor", "Open the editor"),
               ("nothing", "Nothing"))
_QUALITY = (("small", "Small file"), ("balanced", "Balanced"),
            ("sharp", "Sharp"))
_MIC_TOO = (("off", "No"), ("mic", "Yes"))
# The file writes six edges for a card and five for the recording clock;
# the menus say them the way a person would point at them.
_EDGES = (("right", "Middle of the right edge"),
          ("left", "Middle of the left edge"),
          ("top-right", "Top right"), ("top-left", "Top left"),
          ("bottom-right", "Bottom right"), ("bottom-left", "Bottom left"))
_CLOCK_CORNERS = _CORNERS + (("off", "Do not show it at all"),)
_ANCHOR = (("bottom", "Grow upward"), ("top", "Grow downward"))
_INTERRUPT = (("all", "Every message"),
              ("input", "Only what needs you"),
              ("none", "Never interrupt"))
_WATCH = (("off", "Never look"), ("cowork", "Only from Cowork"),
          ("all", "All of them"))
_RUNS_ON = (("auto", "Decide for itself"), ("cuda", "The graphics card"),
            ("cpu", "The processor"))
_LOOK_UP_FIRST = (("ollama", "On this computer"),
                  ("gemini", "Google's model"))
_REPAIR_FIRST = (("groq", "Groq — fast, free tier"),
                 ("cerebras", "Cerebras"),
                 ("ollama", "On this computer"))
_ASK_FIRST = (("ollama", "On this computer"),
              ("groq", "Groq — fast, free tier"),
              ("gemini", "Google's model"))

PUNCTUATE_AUTO = Friendly(
    "punctuate.auto", "Punctuate every dictation",
    "Commas, full stops and question marks go in on the way to the cursor, "
    "which costs about a second each time.")
HINT_ENABLED = Friendly(
    "hint.enabled", "Show the key card while a key is held",
    "A card that says what the other keys do, once the key has been held "
    "for a moment.")
AUTO_PAUSE = Friendly(
    "auto_pause_fullscreen", "Pause by itself while a game fills the screen",
    "While a game or a presentation owns the whole screen, the dictation "
    "key is left to it, and comes back when it lets go.")
MARKER = Friendly(
    "feedback.enabled", "Mark the cursor with … while it listens",
    "The marker turns into your words when they arrive.")
REPAIR = Friendly(
    "polish.when", "Fix misheard words with a model",
    "Always, only when the sentence holds a word you have corrected "
    "before, or never.", _REPAIR)
ENGINE = Friendly(
    "backend", "Where your speech is turned into words",
    "On this computer is faster and better at Hebrew, and nothing leaves "
    "the machine.", _ENGINES)
MICROPHONE = Friendly(
    "audio.device", "Microphone", "Which microphone it listens to.")
AUTO_LANGUAGE = Friendly(
    "auto_language", "Notice when a sentence is English",
    "The app decides for each recording; off, everything you say is taken "
    "as Hebrew.")
DOT = Friendly(
    "indicator", "The little dot in the corner",
    "Blue means it is listening, red means it is recording, amber means it "
    "is writing your words down. Click it and the panel opens beside it.")
DOT_CORNER = Friendly(
    "dot.corner", "Which corner the dot sits in",
    "A corner of the main screen above the taskbar — or press Move the dot "
    "and put it anywhere you like. The panel and the key card open beside "
    "it wherever it ends up.", _DOT_CORNERS)
LEARNED = Friendly(
    "vocab.enabled", "Use the words it has learned",
    "Corrections you taught it with the correction key are applied to "
    "new dictations.")
REPORT = Friendly(
    "problems.enabled", "Report a problem with one line",
    "The report key opens a box; the app attaches the dictation, the "
    "recording and the settings itself.")

# ONE LINE, ONE PLACE. The owner, 2026-09-07, on tabs that repeated a
# setting and a last tab that repeated them all: "if there is
# 'Everything' then it is already somewhere else, so I do not need it" —
# and, on the sentences with controls inside them, "make normal settings,
# no need to be clever". So: a path is named by exactly ONE tab (a test
# holds it), General is the dozen things a person actually changes, the
# groups below are the lines worth a menu with names on it, and every
# other line of the file is drawn on the tab that owns its SECTION — see
# TAB_SECTIONS and groups_for — as a plain title, one sentence and its
# control, the same row a hand-written line gets.
TABS: tuple[Tab, ...] = (
    Tab(GENERAL, (
        Group("", (ENGINE, MICROPHONE, AUTO_LANGUAGE, PUNCTUATE_AUTO, REPAIR,
                   LEARNED, MARKER, HINT_ENABLED, AUTO_PAUSE, DOT,
                   DOT_CORNER, REPORT)),
    )),
    Tab("Dictation", (
        Group("RECORDING", (
            Friendly("min_seconds", "Shortest hold that counts, in seconds",
                     "Anything shorter is treated as an accidental tap and "
                     "thrown away."),
            Friendly("max_seconds",
                     "Longest recording while you hold, in seconds",
                     "Past this it stops on its own, drops the recording "
                     "and beeps."),
            Friendly("latch_max_seconds",
                     "Longest recording once it is locked on, in seconds",
                     "Zero means no limit at all."),
        )),
        Group("PASTING", (
            Friendly("feedback.placeholder", "The marker itself",
                     "The characters it leaves at the cursor while it "
                     "works."),
            Friendly("paste_chord", "Paste with",
                     "The keys the app presses to put your words at the "
                     "cursor; some terminals want a different pair."),
            Friendly("restore_delay_ms",
                     "Wait before your old clipboard comes back, in "
                     "milliseconds",
                     "The app borrows the clipboard to paste, then puts "
                     "back whatever was on it."),
        )),
        Group("WHEN THE CLOUD RUNS OUT", (
            Friendly("fallback_to_local",
                     "Use this computer when the cloud has nothing left",
                     "A free cloud service only answers so many times a "
                     "day; when it stops, the model here does the work."),
        )),
        Group("FIXING WORDS", (
            Friendly("polish.max_wait_s",
                     "Longest your paste may be held up, in seconds",
                     "Past this the dictation is pasted exactly as it came "
                     "and the answer is thrown away."),
            Friendly("study.enabled", "Keep learning while you are away",
                     "After a quiet spell it listens again to what you sent "
                     "and learns from what it got wrong. Nothing leaves the "
                     "machine."),
            Friendly("study.idle_minutes",
                     "Minutes of quiet before it starts",
                     "It steps aside the moment you press a key, so a "
                     "dictation never waits for it."),
        )),
        Group("AT STARTUP", (
            Friendly("splash", "Show a small window while the models load",
                     "Without it, clicking the shortcut looks like it did "
                     "nothing."),
            Friendly("setup.done", "Skip the first-run walkthrough",
                     "The walkthrough runs once per copy of the app; this "
                     "is the switch that turns it off by hand."),
        )),
    )),
    Tab("Text", (
        Group("PUNCTUATION", (
            Friendly("punctuate.prefer", "Which service punctuates first",
                     "The other two are tried underneath when it has "
                     "nothing left for today.", _PUNCTUATORS),
            Friendly("punctuate.max_wait_s",
                     "Longest wait for punctuation, in seconds",
                     "Past this the dictation is pasted exactly as it "
                     "came."),
            Friendly("punctuate.nikud", "Add vowel points as well",
                     "The Hebrew vowel marks go in along with the "
                     "punctuation."),
        )),
        Group("TRANSLATING", (
            Friendly("translate.target", "Translate into",
                     "The language the translate key writes in."),
        )),
        Group("LOOKING UP", (
            Friendly("lookup.both_ways", "Answer Hebrew selections too",
                     "Off, only an English selection gets an answer."),
        )),
    )),
    Tab("Screen", (
        Group("ASK ABOUT THE SCREEN", (
            Friendly("visual_qa.enabled", "Ask about the screen",
                     "Hold the key, drag a box, ask; the answer comes back "
                     "on a card."),
            Friendly("visual_qa.speak", "Read the answer aloud",
                     "Whether the card offers to say the answer, says every "
                     "answer as it lands, or never speaks.", _SPEAK),
            Friendly("visual_qa.echo_to_field",
                     "Type what you asked into the field you were in",
                     "Once the card closes, so the question becomes part of "
                     "what you were writing."),
            Friendly("visual_qa.auto_send",
                     "Send a spoken question the moment you let go",
                     "Otherwise you press Enter, which leaves room to edit "
                     "what you asked first."),
        )),
        Group("SCREENSHOTS", (
            Friendly("capture.enabled", "Screenshots and screen recording",
                     "Off, both keys stop working and nothing is taken."),
            Friendly("capture.after_shot", "After a screenshot",
                     "What happens the moment you let go: a small card, the "
                     "editor, or nothing at all.", _AFTER_SHOT),
            Friendly("capture.copy_to_clipboard",
                     "Put the picture on the clipboard",
                     "It is there the moment you let go of the mouse."),
            Friendly("capture.always_save", "Always save the file as well",
                     "Off, the picture is on the clipboard and nowhere else "
                     "until you press Save."),
            Friendly("capture.folder", "Where pictures are saved",
                     "Screenshots and webcam photos both land here. A plain "
                     "name means a folder beside the app."),
        )),
        Group("RECORDING", (
            Friendly("capture.quality", "Quality",
                     "How much detail a recording keeps, against how large "
                     "the file is.", _QUALITY),
            Friendly("capture.fps", "Frames per second",
                     "How many pictures a second a recording takes."),
            Friendly("capture.audio", "Record the microphone too",
                     "Off to start with: a recorder that quietly opens the "
                     "microphone is a surprise.", _MIC_TOO),
            Friendly("capture.cursor", "Show the pointer",
                     "The mouse pointer is painted in, so it is clear what "
                     "is being pointed at."),
            Friendly("capture.max_minutes",
                     "Stop recording after, in minutes",
                     "A backstop for a key tapped by accident. Zero means "
                     "never stop by itself."),
        )),
        Group("CAMERA", (
            Friendly("camera.enabled", "Take a photo with the webcam",
                     "Off, the key does nothing and the camera is never "
                     "opened."),
            Friendly("camera.mirror", "Mirror the picture",
                     "Off, because writing held up to a webcam reads "
                     "backwards mirrored."),
            Friendly("camera.timer", "Countdown before the shot, in seconds",
                     "The letter t changes it while the camera window is "
                     "open."),
            Friendly("camera.size", "Picture size",
                     "How big a picture the camera is asked for."),
            Friendly("camera.edit_after_shot", "Open the photo in the editor",
                     "Right where the preview was, so you can crop it or "
                     "draw on it."),
        )),
    )),
    Tab("Cards", (
        Group("THE KEY CARD", (
            Friendly("hint.after_ms",
                     "Show it after holding for, in milliseconds",
                     "A quick dictation is over before the card appears."),
            Friendly("hint.corner", "Which corner it starts in",
                     "Where the card appears before you have dragged it "
                     "somewhere else; beside the dot means the dot's own "
                     "corner, next to it.", _CARD_CORNERS),
            Friendly("hint.scale", "How big the card is drawn",
                     "The minus and plus on the card itself change this "
                     "and remember it."),
        )),
    )),
    Tab("Privacy", (
        Group("WHAT MAY LEAVE THIS PC", (
            Friendly("privacy.cloud_text", "Text to the cloud",
                     "What you dictated or selected may go to Groq or "
                     "Google under your own key, for the repair pass, "
                     "punctuation, translation, lookup and the second "
                     "reading. Opens only through its card, the first time "
                     "a feature needs it."),
            Friendly("privacy.cloud_audio", "Recordings to the cloud",
                     "What you said, as audio, may go to Google or Groq "
                     "for transcription. Opens only through its card."),
            Friendly("privacy.cloud_screenshots", "Screen pictures to the cloud",
                     "The part of the screen you asked about may go to "
                     "Groq or Google. Opens only through its card."),
            Friendly("privacy.account", "An anonymous account",
                     "For problem reports you choose to send. Opens only "
                     "through its card."),
            Friendly("privacy.report_upload", "Sending problem reports",
                     "Only what the preview showed. Opens only through its "
                     "card."),
            Friendly("privacy.settings_sync", "Syncing settings",
                     "Not built yet."),
        )),
        Group("SWITCHES", (
            Friendly("privacy.update_check", "Look for a newer version weekly",
                     "One request to GitHub, carrying no identifier."),
            Friendly("privacy.offline", "Offline mode",
                     "Refuse every connection except this computer's own — "
                     "Ollama, the phone, the hook — whatever the gates "
                     "above say. Dictation keeps working."),
        )),
    )),
    Tab("Phone", (
        Group("DICTATING FROM THE PHONE", (
            Friendly("server.enabled", "Dictate from the phone",
                     "The phone keyboard sends its recordings here, over "
                     "your own private network."),
            Friendly("server.port", "Port number",
                     "The phone has to be pointed at the same number."),
        )),
    )),
    Tab(APP, ()),
)

# WHICH SECTIONS OF THE FILE EACH TAB OWNS. Every line of those sections
# that no tab names by hand is drawn on that tab, one group per section
# in the file's own order, titled with the section's plain words. "" is
# the top of the file. A section no tab owns lands on ADVANCED — so a
# section added to config.toml is on the screen the moment the file is
# saved — and the test that every line is drawn exactly once is what
# keeps this table and TABS from disagreeing.
TAB_SECTIONS: dict[str, tuple[str, ...]] = {
    # [dot] IS ON GENERAL AND NOWHERE ELSE, since 2026-09-08. The owner
    # went looking for it there and found half of it: "in the settings,
    # I'm going to General and then 'which corner the dot sits' — there
    # is only bottom right or top right. So please solve the problem that
    # I cannot move the dot." The corner was named by hand on General
    # (TABS, DOT_CORNER) and the section was owned by Cards, so "Move the
    # dot" — the button that is the ONLY way to set `dot.x` and `dot.y` —
    # was drawn on a page he never opened. Owning the section here puts
    # the two lines the button writes on the same page as the button, and
    # takes the dot out of Cards entirely, which is correct: the dot is
    # not a card, it is the app's one permanent mark on the screen.
    GENERAL: ("dot",),
    "Dictation": ("", "audio", "feedback", "polish", "vocab", "study",
                  "history",
                  "local", "review", "setup"),
    "Text": ("punctuate", "translate", "lookup", "gemini"),
    "Screen": ("visual_qa", "capture", "camera"),
    "Cards": ("hint", "notify", "problems", "shelf"),
    "Phone": ("server",),
    # [privacy] has its own page (D18-4): the six gates, read-only with
    # the date they were granted, and the two switches.
    "Privacy": ("privacy",),
    # [tests] IS ON "The app" beside [awake], because they are the same
    # kind of thing: what the app does to the machine while nobody is
    # asking it to do anything. Holding the computer awake and checking
    # itself at three in the morning both belong on the page about the
    # app rather than about dictation.
    APP: ("awake", "tests"),
}


def tab_named(name: str) -> Tab | None:
    for tab in TABS:
        if tab.name == name:
            return tab
    return None


def friendly_paths() -> list[str]:
    """Every path a tab names by hand, tab by tab — each of them once."""
    return [row.path for tab in TABS for group in tab.groups
            for row in group.rows]


def owned_sections(name: str, sections) -> tuple[str, ...]:
    """The sections a tab draws the rest of. ADVANCED owns whatever no
    tab does, so nothing in the file can fall through the floor."""
    if name == ADVANCED:
        taken = {s for names in TAB_SECTIONS.values() for s in names}
        return tuple(sec.name for sec in sections if sec.name not in taken)
    return TAB_SECTIONS.get(name, ())


def groups_for(name: str, sections, skip=()) -> list[Group]:
    """What a tab draws, in order: the groups written for it by hand,
    then every remaining line of the sections it owns, one group per
    section in the file's own order, said with `words_for`. `skip` is
    what another screen draws — the keys, on the Keys place."""
    out: list[Group] = []
    tab = tab_named(name)
    if tab is not None:
        out.extend(tab.groups)
    leave = set(skip) | set(friendly_paths())
    owned = owned_sections(name, sections)
    for section in sections:
        if section.name not in owned:
            continue
        rows = tuple(words_for(s) for s in section.settings
                     if s.path not in leave)
        if rows:
            title = section_words(section.name, section.help).label
            out.append(Group(title.upper(), rows))
    return out


def tab_names(sections, skip=()) -> list[str]:
    """The tabs in the order the bar shows them. ADVANCED appears only
    when a section no tab owns has a line to draw, and then before
    APP, which is always last."""
    names = [tab.name for tab in TABS]
    if groups_for(ADVANCED, sections, skip):
        names.insert(names.index(APP), ADVANCED)
    return names


# ------------------------------------------------------------- the fold
#
# The owner asked twice, and the two asks pull opposite ways. 2026-09-01:
# "show all of them", so that a setting one person uses and another does
# not never quietly drops off. 2026-09-07, looking at the result:
# "I would reduce some of the settings. There are things there that I
# just don't need, so maybe make it a bit smaller." Nothing is deleted
# and nothing is hidden; the second screenful is folded into one line.

# One line behind a fold costs a whole row to say "1 more in this
# section" and gives nothing back, so a card with fewer than this many
# lines to hide simply shows them.
FOLD_MIN = 2

_NAMED: frozenset | None = None


def named_by_hand() -> frozenset:
    """Every path TABS names, as a set. Computed once: friendly_paths()
    walks every group of every tab and `common` is asked per row."""
    global _NAMED
    if _NAMED is None:
        _NAMED = frozenset(friendly_paths())
    return _NAMED


def common(setting) -> bool:
    """Is this line on the face of its card, or behind the card's one
    quiet line?

    THE RULE, and it is read off the file rather than off a list of a
    hundred and ninety-nine paths:

      * a line one of the TABS names by hand is common. That table IS
        the owner's own shortlist — General is nothing but that table —
        and a line he wrote a sentence for by hand is not one to hide;
      * a line that is a CHOICE is common: a switch (`kind == "bool"`),
        or a menu — an `a | b | c` at the front of its comment, or the
        names the words give it;
      * everything else is a MEASUREMENT, and folds: a number, a length
        of time, a threshold, a model name, a folder, a list.

    The reasoning, so the rule can be argued with rather than guessed
    at. A choice is a thing a person can answer without knowing what the
    app does with it — yes or no, this or that — and answering it is one
    click. A measurement is a number you need a reason to change, and
    every one in this file already carries, in its comment, the
    measurement that chose it; the owner's word for that page was "I do
    not need to know all of this". And because it is COMPUTED, a setting
    added to config.toml lands on the right side of the fold the moment
    the file is saved, with no second list to remember.
    """
    if setting.path in named_by_hand():
        return True
    if setting.kind == "bool":
        return True
    row = WORDS.get(setting.path)
    if row is not None and row.names:
        return True
    return bool(setting.choices)


def fold(pairs):
    """One card's rows, split in two: what it shows, and what waits
    behind its quiet line.

    `pairs` is what the screen draws — (Friendly, Setting) — and every
    pair comes back in one list or the other, never in neither and never
    in both. That is the promise the "reachable exactly once" test
    stands on.
    """
    pairs = list(pairs)
    rest = [pair for pair in pairs if not common(pair[1])]
    if len(rest) < FOLD_MIN:
        return pairs, []
    return [pair for pair in pairs if common(pair[1])], rest


# ------------------------------------------------- the words for the rest
#
# The owner, looking at "Everything" on 2026-09-07: "it is impossible to
# understand what each setting is — there are underscores that mean
# nothing and lots of unclear words." He was reading the file's own
# names and the file's own comments, and both are written for whoever
# maintains the app: `latch_max_seconds`, and a comment that answers it
# with a word error rate and a date.
#
# So the words below finish the job TABS started, for every line and
# every section rather than the fifty most-touched: they are what the
# tab that owns a section says for each of its remaining lines. The
# rule for each
# one: a title a person understands without knowing the code, and one
# sentence saying what changes when they change it. No underscores, no
# identifiers, no acronyms, units spelled out, and never a measurement
# or a date — the file keeps those, and the search still finds a line
# by them (`matches` reads the file's own words as well as these).
#
# The Friendly objects above win over the ones below for the lines they
# name, so a line says one thing wherever it is looked up. A test holds
# this table to naming every key and every section the file has, so a
# setting added to config.toml cannot arrive without words.

_MORE: tuple[Friendly, ...] = (
    # -- the top of the file: the keys, and what every dictation goes
    #    through. The keys themselves are rebound on the Keys screen;
    #    the words are here so the search and the file both have them.
    Friendly("hotkey", "The dictation key",
             "Hold it, speak, and let go: your words land where the "
             "cursor is."),
    Friendly("english_hotkey", "The English-only key",
             "A second key that declares the recording English before you "
             "speak, instead of letting the app work it out."),
    Friendly("latch_hotkey", "The lock-on key",
             "Tap it while still holding the dictation key and the "
             "recording stays on after you let go."),
    Friendly("translate_hotkey", "The translate key",
             "Tap it to turn the words already at the cursor into another "
             "language."),
    Friendly("punctuate_hotkey", "The punctuation key",
             "Tap it to put commas and full stops into the words already "
             "at the cursor, without changing any of them."),
    Friendly("correct_hotkey", "The teach-a-word key",
             "Fix a word where it landed, tap this, and it learns the "
             "correction for next time."),
    Friendly("lookup_hotkey", "The look-up key",
             "Select a word, tap this, and a small box says what it means "
             "without changing anything on screen."),
    Friendly("pause_hotkey", "The pause key",
             "Tap it and every key here goes quiet; tap it again and they "
             "all come back."),
    # -- [dot]
    Friendly("dot.x", "Where you last dragged the dot, across",
             "Set by the Move the dot button above, not by hand. Counted "
             "from the left edge of the screen."),
    Friendly("dot.y", "Where you last dragged the dot, down",
             "Set by the Move the dot button above, not by hand. Counted "
             "from the top edge of the screen."),
    # -- [hint]
    Friendly("hint.x", "Where you last dragged the card, across",
             "Counted from the left edge of the screen."),
    Friendly("hint.y", "Where you last dragged the card, down",
             "Counted from the top edge of the screen."),
    # -- [audio]
    Friendly("audio.sample_rate", "How finely the sound is recorded",
             "The speech model was trained for one setting, so this is "
             "best left where it is."),
    # -- [feedback]
    Friendly("feedback.retry_seconds",
             "How long it keeps trying to paste, in seconds",
             "If the window will not take the words it keeps trying this "
             "long, then saves them for later instead of losing them."),
    # -- [translate]
    Friendly("translate.max_chars", "Most letters it will translate at once",
             "Above this the key refuses, on the assumption a select-all "
             "caught a whole document."),
    Friendly("translate.ollama_model", "The model on this computer",
             "The one it falls back to when the cloud has nothing left "
             "for today."),
    Friendly("translate.ollama_url", "Where that model answers",
             "The address the model on this computer is reached at."),
    Friendly("translate.timeout_s",
             "How long to wait for the cloud, in seconds",
             "Past this it gives up and tries the next service."),
    Friendly("translate.ollama_timeout_s",
             "How long to wait for this computer, in seconds",
             "A model that has not been used for a while has to be loaded "
             "first, which is slow."),
    Friendly("translate.settle_ms",
             "How long the other window gets to hand the text over, in "
             "milliseconds",
             "The app copies what you selected; this is the pause it "
             "allows for the copy to arrive."),
    # -- [punctuate]
    Friendly("punctuate.max_chars", "Most letters it will punctuate at once",
             "With nothing selected the key takes the whole field, so "
             "this is the ceiling on it."),
    Friendly("punctuate.groq_model", "Which model to ask on Groq",
             "Empty means use the same one the repair pass uses."),
    Friendly("punctuate.ollama_model",
             "Which model on this computer to ask",
             "Empty means use the same one the translate key uses."),
    # -- [lookup]
    Friendly("lookup.hebrew_share",
             "How much Hebrew makes a selection Hebrew",
             "At or above this share of Hebrew words the answer comes "
             "back in English; below it, in Hebrew."),
    Friendly("lookup.max_chars", "Most letters it will look up at once",
             "Above this the key refuses rather than spending a long time "
             "on it."),
    Friendly("lookup.prefer", "Which service answers first",
             "The model on this computer goes first here, so a key you "
             "tap while reading never spends the cloud's daily turns.",
             _LOOK_UP_FIRST),
    Friendly("lookup.model", "Which model writes the meaning",
             "The one on this computer that answers a look-up."),
    Friendly("lookup.cold_to_gemini",
             "Ask the cloud while the local model wakes up",
             "A model that has not been used in a while takes a long time "
             "to load, so the first look-up goes out instead."),
    Friendly("lookup.keep_alive", "How long the model stays ready",
             "Written as a length of time. Longer keeps look-ups instant "
             "and holds on to graphics memory."),
    Friendly("lookup.strip_niqqud",
             "Take Hebrew vowel marks out of the answer",
             "The model sometimes writes a whole line in vowel points, "
             "which is harder to read than plain Hebrew."),
    Friendly("lookup.dwell_ms", "How long the box waits before closing",
             "Nothing reads this any more: the box waits for you to close "
             "it, and never takes itself away."),
    Friendly("lookup.max_width", "How wide the box opens, in pixels",
             "You can still drag it wider by either bottom corner."),
    Friendly("lookup.max_height", "How tall the box opens, in pixels",
             "A longer answer shrinks its letters to fit before anything "
             "is cut off."),
    Friendly("lookup.cache_entries", "How many answers it remembers",
             "Looking the same word up again is instant and costs "
             "nothing."),
    Friendly("lookup.skip_consoles", "Refuse inside terminal windows",
             "The copy this key makes would otherwise interrupt whatever "
             "is running there."),
    # -- [visual_qa]
    Friendly("visual_qa.visual_qa_hotkey", "The ask-the-screen key",
             "Tap it and the screen dims so you can drag a box over what "
             "you want to ask about."),
    Friendly("visual_qa.prefer", "Which model answers first",
             "The others are tried underneath it, when sending pictures "
             "out is allowed at all.", _ASK_FIRST),
    Friendly("visual_qa.ollama_model",
             "Which model on this computer answers",
             "It has to be one that can look at pictures as well as "
             "read."),
    Friendly("visual_qa.groq_model", "Which model to ask on Groq",
             "Used only when sending pictures out is allowed."),
    Friendly("visual_qa.gemini_fallback", "Try Google's model as well",
             "Only when sending pictures out is allowed, and only after "
             "the others."),
    Friendly("visual_qa.max_side_px",
             "Biggest the picture is sent at, in pixels",
             "The long side is shrunk to this before it goes; larger buys "
             "no more detail, only waiting."),
    Friendly("visual_qa.num_predict", "Longest answer it may write",
             "Counted in pieces of words. It is what stops a rambling "
             "model filling the card."),
    Friendly("visual_qa.voice", "Which voice reads the answer",
             "One of the Hebrew voices Windows has installed."),
    Friendly("visual_qa.window_alpha", "How solid the card looks",
             "Lower lets more of the screen behind it show through; the "
             "writing stays sharp either way."),
    Friendly("visual_qa.warmup", "Wake the model when the app starts",
             "One throwaway question at startup, so the first real one "
             "does not keep you waiting."),
    Friendly("visual_qa.ollama_timeout_s",
             "How long to wait for this computer, in seconds",
             "Generous on purpose, because a model that has to load "
             "itself first is slow."),
    Friendly("visual_qa.cloud_timeout_s",
             "How long to wait for a cloud answer, in seconds",
             "Past this the next service should have the work instead."),
    # -- [capture]
    Friendly("capture.capture_hotkey", "The screenshot key",
             "Tap it and the screen freezes so you can drag a box, or "
             "hold Shift and lasso a shape."),
    Friendly("capture.record_hotkey", "The screen recording key",
             "Tap to start recording a part of the screen, tap again to "
             "stop."),
    Friendly("capture.clip_folder", "Where recordings are saved",
             "Empty means the same folder as the pictures."),
    Friendly("capture.toast_corner",
             "Which corner the card after a screenshot appears in",
             "The small card holding what you just took, with the editor "
             "one click away on it.", _CORNERS),
    Friendly("capture.toast_seconds",
             "How long that card waits for you, in seconds",
             "The clock stops while the pointer is on the card."),
    Friendly("capture.toast_stack", "How many such cards may be up at once",
             "Take another picture while one is up and a second card "
             "joins it, each with its own clock."),
    Friendly("capture.toast_in_shots", "Let a screenshot see those cards",
             "So you can take a picture of one and show it to somebody. "
             "Off hides them from every picture and recording."),
    Friendly("capture.copy_clip_path",
             "Put a finished recording on the clipboard as a file",
             "So it pastes into a chat or a folder the way a copied file "
             "does."),
    Friendly("capture.timer_corner",
             "Which corner the recording clock sits in",
             "The little red dot and clock while a recording runs. It is "
             "hidden from the recording itself.", _CLOCK_CORNERS),
    Friendly("capture.announce", "Say when a recording has started",
             "A short banner before it shrinks to the clock, because not "
             "knowing whether it is running is the usual worry."),
    # -- [camera]
    Friendly("camera.camera_hotkey", "The webcam key",
             "Tap it and a window opens with the live picture and a "
             "shutter under it."),
    Friendly("camera.device", "Which camera",
             "Part of its name is enough. Empty means the first real "
             "camera Windows lists, skipping the pretend ones."),
    Friendly("camera.fps", "Frames per second asked of the camera",
             "A camera that cannot manage it simply sends fewer."),
    Friendly("camera.folder", "Where photos are saved",
             "The same folder the screenshots go to, so all the pictures "
             "are in one place."),
    Friendly("camera.copy_to_clipboard", "Put the photo on the clipboard",
             "It is there the moment the shutter fires."),
    # -- [awake]
    Friendly("awake.hold", "Hold the computer awake",
             "While the app is running the machine will not fall asleep "
             "on its own timer. The screens may still go dark."),
    Friendly("awake.enabled", "The screens key works",
             "Off, the key does nothing; the button in this window still "
             "turns the screens off."),
    Friendly("awake.screens_hotkey", "The screens key",
             "Tap it and the screens go dark and stay dark; tap it again "
             "and they come back. Nothing is locked."),
    Friendly("awake.screens_off_again_s",
             "Put the screens out again after, in seconds",
             "The mouse moving after you press the key wakes them "
             "straight back up, so it does it once more."),
    Friendly("awake.keep_screens_off_s",
             "Keep putting them out for, in seconds",
             "While the screens are meant to be off, anything that lights "
             "them is undone this long after the last touch."),
    Friendly("awake.vitals_minutes",
             "Write a health line every so many minutes",
             "While the screens are off, a note in the log of what the "
             "machine is carrying. Zero writes none."),
    Friendly("awake.pin_timeouts", "Also change Windows' own sleep settings",
             "The old settings are put back when the app closes, or at "
             "the next start if it did not get the chance."),
    # -- [notify]
    Friendly("notify.enabled", "Take messages from other programs",
             "Off, the door is shut: nothing is shown, stored or played."),
    Friendly("notify.cue", "Play a sound when one arrives",
             "Off, the card appears in silence."),
    Friendly("notify.card_seconds", "How long a card stays, in seconds",
             "Zero means it waits until you dismiss it, however long that "
             "takes."),
    Friendly("notify.stack_max", "How many cards may be on screen at once",
             "The rest wait in this window, counted on the bottom card."),
    Friendly("notify.remind_every_s",
             "Show an unread card again after, in seconds",
             "Zero never reminds you: the card waits quietly instead."),
    Friendly("notify.remind_times", "How many reminders each message gets",
             "After that it stops asking and waits for you in this "
             "window."),
    Friendly("notify.coalesce_s",
             "Treat a quick second message as the same one, in seconds",
             "A repeat from the same program updates the card instead of "
             "ringing all over again."),
    Friendly("notify.interrupt", "Which messages may pull you away",
             "Everything, only what is actually waiting on you, or "
             "nothing at all.", _INTERRUPT),
    Friendly("notify.quiet_s",
             "Hold a finish until that program goes quiet, in seconds",
             "Zero shows it the moment it lands. Anything waiting on you "
             "is never held back either way."),
    Friendly("notify.watch", "Also catch the Claude app's own messages",
             "Some of its work has no way to knock on this door, so the "
             "app watches for its pop-ups instead.", _WATCH),
    Friendly("notify.corner", "Where a card appears",
             "Before you have dragged it somewhere else.", _EDGES),
    Friendly("notify.anchor", "Which edge of the pile stays put",
             "A longer message can grow upward from the bottom or "
             "downward from the top.", _ANCHOR),
    Friendly("notify.x", "Where you last dragged a card, across",
             "Counted from the left edge of the screen."),
    Friendly("notify.y", "Where you last dragged a card, down",
             "Counted from the top edge of the screen, at whichever edge "
             "of the pile stays put."),
    Friendly("notify.scale", "How big the cards are drawn",
             "The same size for every card in the pile."),
    Friendly("notify.dismiss_hotkey", "The dismiss-everything key",
             "Tap it and every card goes away and is marked as seen, "
             "wherever the mouse happens to be."),
    # -- [problems]
    Friendly("problems.report_hotkey", "The report key",
             "Tap it and a box opens over whatever is in front, wherever "
             "the mouse is."),
    Friendly("problems.shot", "Attach a picture of the screen",
             "The screen as it looked when you pressed the key. It stays "
             "on this computer."),
    Friendly("problems.keep_audio", "Keep the recording it is about",
             "So the sound outlives the short list of recent recordings "
             "and can still settle what was really said."),
    Friendly("problems.keep_resolved", "How many answered reports to keep",
             "Ones nobody has answered yet are never thrown away, "
             "whatever this says."),
    Friendly("problems.x",
             "Where you last dragged the report box, across",
             "Counted from the left edge of the screen."),
    Friendly("problems.y", "Where you last dragged the report box, down",
             "Counted from the top edge of the screen."),
    Friendly("problems.card_x",
             "Where you last dragged this window's report box, across",
             "The box opened from this window keeps its own place, so it "
             "never flies off the window it belongs to."),
    Friendly("problems.card_y",
             "Where you last dragged this window's report box, down",
             "Counted from the top edge of the screen."),
    # -- [shelf]
    Friendly("shelf.enabled", "The panel beside the dot works",
             "Off, the key does nothing. Every card, every sound and this "
             "window go on as before."),
    Friendly("shelf.shelf_hotkey", "The panel key",
             "Tap it to open the panel beside the dot; tap it again, or "
             "press Escape, to close it."),
    Friendly("shelf.rows", "How many waiting things it lists",
             "The rest become one line that opens this window instead."),
    Friendly("shelf.corner", "Which corner it opens in",
             "Before you have dragged it somewhere else. Beside the dot "
             "means the dot's own corner, where it opens above the dot "
             "rather than covering it.", _CARD_CORNERS),
    Friendly("shelf.x", "Where you last dragged the panel, across",
             "Counted from the left edge of the screen."),
    Friendly("shelf.y", "Where you last dragged the panel, down",
             "Counted from the top edge of the screen."),
    Friendly("shelf.scale", "How big the panel is drawn",
             "The whole panel, text and buttons together."),
    Friendly("shelf.hush_notifications",
             "Hide the message cards while the panel is open",
             "The same messages are already listed on the panel. Nothing "
             "is marked as seen and no reminder is lost."),
    # -- [server]
    Friendly("server.host", "Which address it answers on",
             "Empty means your own private network, so nothing on the "
             "house network can reach it."),
    # -- [vocab]
    Friendly("vocab.max_terms", "How many learned words it may use at once",
             "A longer list is not a better one: too many and the model "
             "starts saying them when you did not."),
    Friendly("vocab.replace_after_hits",
             "How many corrections before a word is fixed by itself",
             "One correction could be a slip of the hand, so it waits for "
             "the same fix to happen again."),
    Friendly("vocab.hebrew_after_hits",
             "The same, for a correction that is all Hebrew",
             "A real Hebrew word handed to the model makes it say that "
             "word unbidden, so Hebrew has to prove itself more."),
    Friendly("vocab.keep_audio", "How many recent recordings to keep",
             "Keeping the sound is what lets a correction be checked "
             "against what was really said. Zero keeps none."),
    Friendly("vocab.terms", "The words you seeded by hand",
             "Your own names and terms. Anything you correct with the "
             "correction key is added on its own."),
    # -- [study]
    Friendly("study.max_clip_seconds",
             "Longest recording it will study, in seconds",
             "Listening again to a very long recording buys little extra "
             "evidence for the time it takes."),
    Friendly("study.llm_per_day",
             "How many recordings a model may judge each day",
             "Past this the rest simply wait for tomorrow."),
    Friendly("study.corpus_keep", "How many checked recordings to keep",
             "Kept here as material for teaching the model your own voice "
             "one day. Zero keeps none."),
    Friendly("study.read_sentences", "How many sentences a day to read to it",
             "The bar on the Read aloud tab — about fifteen seconds of "
             "your time each. It never stops you reading past it."),
    Friendly("study.read_goal_hours",
             "How much of your voice teaching it needs, in hours",
             "The other bar: what a fine-tune on your own speech wants. "
             "Two to three hours is the usual number."),
    # -- [polish]
    Friendly("polish.min_chars", "Shortest text worth fixing, in letters",
             "Below this there is no sentence to reason from, which is "
             "where a model starts inventing."),
    Friendly("polish.prefer", "Which service fixes the words first",
             "The others follow underneath, so a service that is down "
             "costs you speed and never the repair.", _REPAIR_FIRST),
    Friendly("polish.groq_model", "Which model to ask on Groq",
             "The one the repair pass sends your text to when Groq goes "
             "first."),
    Friendly("polish.groq_timeout_s",
             "How long to wait for Groq, in seconds",
             "Past this something is wrong and the next service should "
             "have the work."),
    Friendly("polish.cerebras_model", "Which model to ask on Cerebras",
             "Only worth setting if you still have turns left there."),
    Friendly("polish.cerebras_timeout_s",
             "How long to wait for Cerebras, in seconds",
             "Past this the next service should have the work."),
    Friendly("polish.ollama_model", "Which model on this computer",
             "The one that fixes the words when no cloud service can. "
             "Empty means reuse the translate key's model."),
    Friendly("polish.warm_up", "Wake the model when the app starts",
             "One throwaway request, so the first dictation of the day "
             "does not wait for it. It holds graphics memory all the "
             "while."),
    # -- [gemini]
    Friendly("gemini.models", "Which models to try, in order",
             "Each one has its own small daily allowance, so a list of "
             "them lasts longer than any single name."),
    Friendly("gemini.timeout_s", "How long to wait, in seconds",
             "Past this it gives up and something else is asked."),
    # -- [local]
    Friendly("local.model", "Which speech model",
             "The Hebrew one this app was built around."),
    Friendly("local.language", "Which language it expects",
             "It has to stay Hebrew: this model cannot work the language "
             "out for itself."),
    Friendly("local.device", "What it runs on",
             "The graphics card is far faster; it falls back to the "
             "processor where there is none.", _RUNS_ON),
    Friendly("local.cleanup", "Take out the ums and the false starts",
             "The sounds you make while thinking, and a phrase you began "
             "again, are dropped."),
    Friendly("local.extra_fillers", "Your own ums to drop",
             "Only add words you never mean literally, or real speech "
             "will go with them."),
    Friendly("local.initial_prompt", "The sentence that sets the scene",
             "It tells the model to expect Hebrew with English technical "
             "words in it, so it stops dropping the English half."),
    Friendly("local.english_model", "The model for English-only speech",
             "The Hebrew one writes short English sentences out in Hebrew "
             "letters, so confident English goes here instead."),
    Friendly("local.english_threshold",
             "How sure it must be before calling something English",
             "High on purpose: Hebrew sent to the English model is far "
             "worse than one English word in Hebrew letters."),
    Friendly("local.guard_hallucinations",
             "Stop it inventing words you never said",
             "The model keeps writing past the end of real speech and "
             "fills the gap; this makes it fussier about what it keeps."),
    Friendly("local.beam_size", "How many readings it weighs at once",
             "Fewer is faster and a little less accurate. Do not change "
             "it on a hunch — replay your recordings both ways."),
    Friendly("local.drop_trailing_boilerplate",
             "Drop stock phrases stuck to the end",
             "Never in the middle, where they are almost certainly really "
             "yours."),
    Friendly("local.extra_boilerplate", "Your own stock phrases to drop",
             "Whole phrases only: one common word here would delete real "
             "speech."),
    Friendly("local.rolling", "Transcribe while you are still talking",
             "The recording is decoded in stretches as you speak, so "
             "letting go waits only for the last few seconds. Nothing "
             "shows early."),
    Friendly("local.rolling_window_s",
             "How many seconds a stretch waits for, before it is decoded",
             "Shorter means more is done by the time you let go; longer "
             "means each stretch is read with more of its own context. "
             "Below 20 it was measured to cost words."),
    # -- [review]
    Friendly("review.enabled", "Read every dictation a second time",
             "Off, there are no cards and no proposals, and the quiet "
             "learning while you are away goes on instead."),
    Friendly("review.card_seconds", "How long the card stays, in seconds",
             "The bar under the title is that clock, and it stops while "
             "the mouse is on the card. Zero shows no card at all."),
    Friendly("review.corner", "Where the card appears",
             "Before you have dragged it somewhere else.", _EDGES),
    Friendly("review.x", "Where you last dragged the card, across",
             "Counted from the left edge of the screen."),
    Friendly("review.y", "Where you last dragged the card, down",
             "Counted from the top edge of the screen."),
    Friendly("review.scale", "How big the card is drawn",
             "The whole card, text and buttons together."),
    Friendly("review.max_changes", "The most words one reading may offer",
             "A reading that wants more than this is a rewrite rather "
             "than a repair, and is dropped."),
    Friendly("review.witness", "How many extra readings must agree",
             "The recording is read several more ways; a word is only "
             "offered when this many of them heard it."),
    Friendly("review.accept_key", "The key that says yes",
             "It only counts while the mouse is over the card; anywhere "
             "else it types as usual."),
    Friendly("review.reject_key", "The key that says no",
             "Also only while the mouse is over the card."),
    Friendly("review.later_key", "The key that closes the card for now",
             "Nothing is decided: the proposal waits for you in this "
             "window."),
    Friendly("review.edit_key", "The key that opens the pencil",
             "A small box asks what the word should have been, and Enter "
             "accepts the card with that word."),
    Friendly("review.fix_in_field",
             "Also fix the words where they landed",
             "If that window is still in front and still holds exactly "
             "what was pasted. Off, saying yes only teaches."),
    Friendly("review.max_clip_seconds",
             "Longest recording it will read again, in seconds",
             "Reading a very long recording several more ways holds the "
             "model up for little gain."),
    Friendly("review.llm_per_day",
             "How many readings a model may judge each day",
             "Past this the reading still runs, and can only offer the "
             "invented endings it finds on its own."),
    Friendly("review.local_model",
             "Ask the model on this computer when the cloud refuses",
             "Off, because the proposals it made on its own were wrong "
             "more often than they were right."),
    # -- the nightly self-check. Two lines, and the second one is the
    #    only place on the screen that says what happens if he walks
    #    away from the card, which is the decision the whole feature
    #    turns on.
    Friendly("tests.nightly", "Check itself at night",
             "At five to three in the morning a card asks whether to run "
             "the app's own checks, and then it runs them."),
    Friendly("tests.wait_seconds",
             "How long that card waits for you, in seconds",
             "Say no and nothing happens; say nothing at all and it runs "
             "anyway, because that is safer than guessing you are here."),
    # -- [privacy]: the six gates and the two switches. The gates are
    #    read-only here (Setting.consent); their words are on the Privacy
    #    tab too, said once in each place.
    Friendly("privacy.cloud_text", "Text to the cloud",
             "What you dictated or selected may go to Groq or Google under "
             "your own key. Opens only through its card."),
    Friendly("privacy.cloud_audio", "Recordings to the cloud",
             "What you said, as audio, may go to Google or Groq. Opens only "
             "through its card."),
    Friendly("privacy.cloud_screenshots", "Screen pictures to the cloud",
             "The part of the screen you asked about may go to Groq or "
             "Google. Opens only through its card."),
    Friendly("privacy.account", "An anonymous account",
             "For problem reports you choose to send. Opens only through "
             "its card."),
    Friendly("privacy.report_upload", "Sending problem reports",
             "Only what the preview showed. Opens only through its card."),
    Friendly("privacy.settings_sync", "Syncing settings",
             "Not built yet."),
    Friendly("privacy.update_check", "Look for a newer version weekly",
             "One request to GitHub, carrying no identifier."),
    Friendly("privacy.offline", "Offline mode",
             "Refuse every connection except this computer's own, whatever "
             "the gates say. Dictation keeps working."),
    Friendly("history.keep_days", "How long what you said is kept, in days",
             "The Recent view and the clipboard-recovery path read it; "
             "older lines are dropped. 0 keeps no history at all."),
)

# Every section of the file, said the way the owner would point at it.
SECTION_WORDS: dict[str, Friendly] = {
    row.path: row for row in (
        Friendly("", "The basics",
                 "The keys you hold and tap, and the choices every "
                 "dictation goes through on its way to the cursor."),
        Friendly("dot", "The dot in the corner",
                 "The little always-on dot that says the app is running "
                 "and what it is doing; click it and the panel opens."),
        Friendly("hint", "The card while a key is held",
                 "The little card that appears if you keep the dictation "
                 "key down, saying what the other keys will do."),
        Friendly("setup", "The first-run walkthrough",
                 "The short walkthrough that picks a microphone and has "
                 "you say one sentence, the first time the app runs."),
        Friendly("audio", "The microphone",
                 "Which microphone it listens to, and how finely it "
                 "records what it hears."),
        Friendly("feedback", "The marker at the cursor",
                 "The few characters it drops where you are typing, so "
                 "you can see it heard you while it works."),
        Friendly("translate", "Turning text into another language",
                 "The key that rewrites what is at the cursor in another "
                 "language, and the services it asks to do it."),
        Friendly("punctuate", "Commas and full stops",
                 "Putting punctuation into text that was dictated without "
                 "any, without changing a single word of it."),
        Friendly("lookup", "The look-up box",
                 "The small box that says what a selected word means, and "
                 "never touches anything on screen."),
        Friendly("visual_qa", "Ask the screen",
                 "Drag a box over anything on screen, ask a question about "
                 "it, and the answer comes back on a card."),
        Friendly("capture", "Screenshots and screen recordings",
                 "Drag a box to copy a picture of the screen, or record it "
                 "to a film. None of it leaves this computer."),
        Friendly("camera", "The webcam photo",
                 "A picture from the webcam, into the same folder and the "
                 "same editor as a screenshot."),
        Friendly("awake", "Keeping the computer awake",
                 "The app holds the machine awake while it runs, and one "
                 "key puts the screens out without locking anything."),
        Friendly("notify", "Messages from other programs",
                 "A door other programs knock on: a card appears at the "
                 "edge of the screen and reminds you until you answer."),
        Friendly("problems", "Telling it something went wrong",
                 "One typed line, and the app attaches the rest itself: "
                 "the dictation, the recording and the settings."),
        Friendly("shelf", "The panel beside the dot",
                 "One key opens a small panel next to the dot with "
                 "everything waiting for you; the same key closes it."),
        Friendly("server", "The phone",
                 "Dictate from your phone and let this computer do the "
                 "listening, so you keep the Hebrew model."),
        Friendly("vocab", "Words it has learned",
                 "Names and terms the speech model never heard, handed to "
                 "it before it listens so it gets them right first time."),
        Friendly("study", "Learning while you are away",
                 "After a quiet spell it listens again to what you sent "
                 "and learns from what it got wrong."),
        Friendly("polish", "Fixing misheard words",
                 "A model reads the sentence and puts back a word that was "
                 "misheard. It may fix words; it may never write new ones."),
        Friendly("gemini", "Google's models",
                 "The cloud service several keys fall back on, and how "
                 "long they are willing to wait for it."),
        Friendly("local", "The speech model on this computer",
                 "The model that turns your voice into words with nothing "
                 "leaving this computer."),
        Friendly("review", "The second reading",
                 "The moment a dictation lands, the recording is read "
                 "again and a card offers back any word it doubts."),
        Friendly("tests", "Checking itself at night",
                 "Once a night, while nobody is here, the app runs its "
                 "own checks — including the ones that need the screen."),
        Friendly("privacy", "What may leave this PC",
                 "Six gates that open only through their consent cards, "
                 "and two switches: the weekly update check and offline "
                 "mode."),
        Friendly("history", "What you said, kept",
                 "How long the record of your dictations stays on this "
                 "PC for the Recent view."),
    )
}

WORDS: dict[str, Friendly] = {row.path: row for row in _MORE}
for _tab in TABS:                       # the tabs win: one wording, twice
    for _group in _tab.groups:
        for _row in _group.rows:
            WORDS[_row.path] = _row
del _tab, _group, _row


def _first_sentence(text: str) -> str:
    """The opening sentence of a comment, for a line with no words yet."""
    head = (text or "").replace("\n", " ").strip()
    stop = head.find(". ")
    if stop > 0:
        head = head[:stop + 1]
    return head[:200].strip()


def words_for(setting) -> Friendly:
    """What the screen SAYS for one line: a plain title, one sentence,
    and the names for its menu where it has one.

    Takes a Setting or a path. A line with nothing written for it falls
    back to its own name with the underscores opened out and the first
    sentence of its comment — legible, but not plain, which is why the
    test holds the table to naming every line the file has."""
    path = setting if isinstance(setting, str) else setting.path
    row = WORDS.get(path)
    if row is not None:
        return row
    key = path.rsplit(".", 1)[-1].replace("_", " ").strip()
    label = (key[:1].upper() + key[1:]) if key else path
    help_text = "" if isinstance(setting, str) else _first_sentence(
        setting.help)
    return Friendly(path, label, help_text)


def section_words(name: str, help_text: str = "") -> Friendly:
    """The same, for a `[section]` header. `name` is "" for the top of
    the file."""
    row = SECTION_WORDS.get(name or "")
    if row is not None:
        return row
    plain = (name or "general").replace("_", " ").strip()
    return Friendly(name or "", plain[:1].upper() + plain[1:],
                    _first_sentence(help_text))
