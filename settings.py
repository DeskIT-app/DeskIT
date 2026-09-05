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
and everything they do not name is still on the screen, under
"Everything", with the file's own comment as its help.

TWO PARSERS, ON PURPOSE. tomllib reads the values — it is the parser the
app itself trusts, and a value read any other way could disagree with the
one the app runs on. The line scan below reads only what tomllib throws
away: which line a key sits on, and the comments around it. The two are
reconciled by key, and tests.py asserts that every key tomllib found is
one the scan found too — so a line the scan misreads is a red test and
not a setting that silently vanished from the screen.

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
        field that reverses what you type is worse than no field."""
        if self.kind == "list":
            return False
        return not (self.kind == "str" and is_rtl(str(self.value)))


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


def read(path: Path | str) -> list[Section]:
    """The file, section by section, in the order it is written."""
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
            raise ValueError(f"config.toml line {number}: {key!r} is not a "
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
    """The search box: a word in the name, the section or the help."""
    query = (query or "").strip().lower()
    if not query:
        return True
    hay = f"{setting.path} {setting.help}".lower()
    return all(word in hay for word in query.split())


# --------------------------------------------------------------- the words
#
# What the Settings screen SAYS for the lines most people touch. This is
# the one hand-written thing about that screen — a tab, a group, a plain
# label, one short sentence, and for a menu what each value is called —
# and it decides only what is said FIRST, and how. Every path here has to
# exist in the file (tests.py checks), and every line of the file that is
# not here is still on the screen, under "Everything", with the comment
# from the file as its help. Nothing can be dropped; it can only be said
# plainly or said in full.
#
# The owner's brief, 2026-09-01, after the first version showed him all
# hundred and forty lines at once: tabs across the top, plain words, a
# menu he can pick from wherever a value names a model, and "just set the
# things I do not need to change" — which is what "Everything" is for.


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


EVERYTHING = "Everything"

_ENGINES = (("local", "On this computer (Whisper)"),
            ("gemini", "In the cloud (Gemini)"),
            ("fake", "Fake, for testing"))
_REPAIR = (("always", "Always"),
           ("known", "Only words it has been taught"),
           ("never", "Never"))
_PUNCTUATORS = (("groq", "Groq — fast, free tier"),
                ("gemini", "Gemini"),
                ("ollama", "Ollama, on this computer"))
_CORNERS = (("top-right", "Top right"), ("top-left", "Top left"),
            ("bottom-right", "Bottom right"), ("bottom-left", "Bottom left"))
_SPEAK = (("off", "Never"), ("button", "With a button"), ("auto", "Always"))
_AFTER_SHOT = (("toast", "Show a small card"), ("editor", "Open the editor"),
               ("nothing", "Nothing"))
_QUALITY = (("small", "Small file"), ("balanced", "Balanced"),
            ("sharp", "Sharp"))
_MIC_TOO = (("off", "No"), ("mic", "Yes"))

PUNCTUATE_AUTO = Friendly(
    "punctuate.auto", "Punctuate every dictation",
    "Commas, full stops and question marks go in on the way to the cursor. "
    "About a second more per dictation.")
HINT_ENABLED = Friendly(
    "hint.enabled", "Show the key card while a key is held",
    "A card that says what the other keys do, once the key has been held "
    "for a moment.")
AUTO_PAUSE = Friendly(
    "auto_pause_fullscreen", "Pause by itself while a game is fullscreen",
    "The dictation key belongs to the game while it is in front.")
MARKER = Friendly(
    "feedback.enabled", "Mark the cursor with … while it transcribes",
    "The marker turns into your words when they arrive.")
REPAIR = Friendly(
    "polish.when", "Fix misheard words with a model",
    "Runs after every dictation, usually well under a second.", _REPAIR)
ENGINE = Friendly(
    "backend", "Transcription engine",
    "On this computer is faster and better at Hebrew, and nothing leaves "
    "the machine.", _ENGINES)
MICROPHONE = Friendly(
    "audio.device", "Microphone", "Which one it listens to.")
AUTO_LANGUAGE = Friendly(
    "auto_language", "Notice when a sentence is English",
    "Off = everything is treated as Hebrew.")
DOT = Friendly(
    "indicator", "The status dot in the corner",
    "Blue = running, red = recording, amber = transcribing.")
LEARNED = Friendly(
    "vocab.enabled", "Use the words it has learned",
    "Corrections you taught it with the correction key are applied to "
    "new dictations.")
REPORT = Friendly(
    "problems.enabled", "Report a problem with one line",
    "The report key opens a box; the app attaches the dictation, the "
    "recording and the settings itself.")

TABS: tuple[Tab, ...] = (
    Tab("Common", (
        Group("", (PUNCTUATE_AUTO, HINT_ENABLED, AUTO_PAUSE, MARKER, REPAIR,
                   ENGINE, MICROPHONE, AUTO_LANGUAGE, DOT, LEARNED,
                   REPORT)),
    )),
    Tab("Dictation", (
        Group("ENGINE", (
            ENGINE, MICROPHONE, AUTO_LANGUAGE,
            Friendly("fallback_to_local",
                     "Fall back to this computer when the cloud is out of "
                     "quota"),
        )),
        Group("RECORDING", (
            Friendly("min_seconds", "Shortest hold that counts (seconds)",
                     "Anything shorter is treated as an accidental tap."),
            Friendly("max_seconds",
                     "Longest recording while holding (seconds)",
                     "Past this it stops with an error beep."),
            Friendly("latch_max_seconds",
                     "Longest recording when locked on (seconds)",
                     "0 = no limit."),
            AUTO_PAUSE,
        )),
        Group("PASTING", (
            MARKER,
            Friendly("feedback.placeholder", "The marker itself"),
            Friendly("paste_chord", "Paste with",
                     "Some terminals want shift+insert instead of ctrl+v."),
            Friendly("restore_delay_ms",
                     "Wait before the old clipboard comes back (ms)"),
        )),
        Group("FIXING WORDS", (
            REPAIR,
            Friendly("polish.max_wait_s", "Longest wait for the fix (seconds)",
                     "Past this the dictation is pasted as it came."),
            LEARNED,
            Friendly("study.enabled", "Keep learning while you are away",
                     "After a quiet spell it listens again to what you sent "
                     "and learns from what it got wrong. Nothing leaves the "
                     "machine."),
            Friendly("study.idle_minutes",
                     "Minutes of quiet before it starts"),
        )),
        Group("AT STARTUP", (
            Friendly("splash", "Show a small window while the models load",
                     "Without it, clicking the shortcut looks like it did "
                     "nothing."),
            DOT,
            Friendly("setup.done", "Skip the first-run setup",
                     "The setup runs once per copy; this is the manual off "
                     "switch."),
        )),
    )),
    Tab("Text", (
        Group("PUNCTUATION", (
            PUNCTUATE_AUTO,
            Friendly("punctuate.prefer", "Which service punctuates",
                     "Whichever goes first, the other two are tried when it "
                     "is out of quota.", _PUNCTUATORS),
            Friendly("punctuate.max_wait_s",
                     "Longest wait for punctuation (seconds)",
                     "Past this the dictation is pasted as it came."),
            Friendly("punctuate.nikud", "Add vowel points as well"),
        )),
        Group("TRANSLATING", (
            Friendly("translate.target", "Translate into"),
        )),
        Group("LOOKING UP", (
            Friendly("lookup.both_ways", "Answer Hebrew selections too",
                     "Off = only an English selection gets an answer."),
        )),
    )),
    Tab("Card", (
        Group("THE KEY CARD", (
            HINT_ENABLED,
            Friendly("hint.after_ms", "Show it after holding for (ms)",
                     "A quick dictation never sees it."),
            Friendly("hint.corner", "Where it appears",
                     "Before you have dragged it anywhere.", _CORNERS),
            Friendly("hint.scale", "Size", "1 = as designed; 0.6 to 1.4."),
        )),
    )),
    Tab("Screen", (
        Group("ASK ABOUT THE SCREEN", (
            Friendly("visual_qa.enabled", "Ask about the screen",
                     "Hold the key, drag a box, ask; the answer comes back "
                     "on a card."),
            Friendly("visual_qa.speak", "Read the answer aloud", "", _SPEAK),
            Friendly("visual_qa.allow_screenshot_upload",
                     "Allow the screenshot to go to the cloud",
                     "Off = only the model on this computer ever sees your "
                     "screen."),
            Friendly("visual_qa.echo_to_field",
                     "Type what you asked into the field you were in",
                     "Once the card closes."),
            Friendly("visual_qa.auto_send",
                     "Send a spoken question the moment you let go"),
        )),
        Group("SCREENSHOTS", (
            Friendly("capture.enabled", "Screenshots and screen recording",
                     "Off unregisters both keys."),
            Friendly("capture.after_shot", "After a screenshot", "",
                     _AFTER_SHOT),
            Friendly("capture.copy_to_clipboard",
                     "Put the picture on the clipboard"),
            Friendly("capture.always_save", "Always save the file as well",
                     "Off = it is on the clipboard and nowhere else until "
                     "you press Save."),
            Friendly("capture.folder", "Save into",
                     "Relative to the app's folder."),
        )),
        Group("RECORDING", (
            Friendly("capture.quality", "Quality", "", _QUALITY),
            Friendly("capture.fps", "Frames per second"),
            Friendly("capture.audio", "Record the microphone too", "",
                     _MIC_TOO),
            Friendly("capture.cursor", "Show the pointer"),
            Friendly("capture.max_minutes", "Stop after (minutes)",
                     "A backstop for a key tapped by accident. 0 = never."),
        )),
        Group("CAMERA", (
            Friendly("camera.enabled", "Camera photo"),
            Friendly("camera.mirror", "Mirror the picture",
                     "Off, because writing held up to a webcam reads "
                     "backwards mirrored."),
            Friendly("camera.timer", "Countdown before the shot (seconds)",
                     "0, 3 or 10."),
            Friendly("camera.size", "Picture size"),
            Friendly("camera.edit_after_shot", "Open the photo in the editor"),
        )),
    )),
    Tab("Phone", (
        Group("DICTATING FROM THE PHONE", (
            Friendly("server.enabled", "Dictate from the phone",
                     "The Android keyboard sends its recordings here, over "
                     "Tailscale."),
            Friendly("server.port", "Port"),
        )),
    )),
)


def tab_named(name: str) -> Tab | None:
    for tab in TABS:
        if tab.name == name:
            return tab
    return None


def friendly_paths() -> list[str]:
    """Every path the words name, tab by tab (a path may be on two tabs)."""
    return [row.path for tab in TABS for group in tab.groups
            for row in group.rows]
