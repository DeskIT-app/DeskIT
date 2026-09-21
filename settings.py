"""Every line of defaults.toml, as data a screen can draw — and the
short list of lines the screen does draw.

The file is read whole: every assignment in it becomes a Setting, the
comment around it becomes the Setting's help, and an `a | b | c` at the
front of that comment becomes its choices. The Settings screen draws
only what TABS, at the bottom of this file, names: a plain label, one
sentence and a menu with names on it, for the forty-odd lines a person
changes. Every path TABS names is one the file has (a test checks), a
path is named by exactly one tab, and every other line of the file is a
measurement — a threshold, a length of time, a model name, a count —
that the developer edits in defaults.toml and the screen never shows.

That is the owner's rule of 2026-09-18, and it replaced two older ones.
2026-09-01: "show all of them", so nothing quietly drops off — which put
two hundred lines on the screen. 2026-09-07: "I would reduce some of the
settings", which folded the measurements behind a "7 more in this
section" line. 2026-09-18, looking at what was left: "a huge number of
settings a simple user never needs; 90% were never used. Things like
'how many corrections before a word fixes itself' are things I change in
development, not decisions a user should make." And, asked whether his
own copy should keep them: "I am the user; you are the developer." So
the fold went, the section-by-section drawing of the rest went, and
the screen is the list below.

TWO PARSERS, ON PURPOSE. tomllib reads the values — it is the parser the
app itself trusts, and a value read any other way could disagree with the
one the app runs on. The line scan below reads only what tomllib throws
away: which line a key sits on, and the comments around it. The two are
reconciled by key, and tests.py asserts that every key tomllib found is
one the scan found too — so a line the scan misreads is a red test and
not a setting that silently vanished.

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
        """One of the seven [privacy] gates — drawn read-only with the date
        it was granted, never as a switch."""
        return self.section == "privacy" and self.key in CONSENT_GATES


#: The seven gates of [privacy] (privacy.KINDS, spelled here so this module
#: keeps importing nothing but the standard library).
CONSENT_GATES: frozenset[str] = frozenset({
    "cloud_text", "cloud_audio", "cloud_screenshots",
    "account", "report_upload", "settings_sync", "history_sync",
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
    the plain sentence — or a word in what the FILE says, its dotted
    name and its comment.

    Both, because the two audiences are the same person on different
    days: "the card while I hold the key" one day and `hint.after_ms` the
    next, and neither should come back empty."""
    query = (query or "").strip().lower()
    if not query:
        return True
    words = words_for(setting)
    hay = " ".join((setting.path, setting.help, words.label,
                    words.help)).lower()
    return all(word in hay for word in query.split())


# --------------------------------------------------------------- the words
#
# What the Settings screen draws, and what it says. This is the whole of
# it: a tab, a group, a plain label, one short sentence, and for a menu
# what each value is called. Every path here has to exist in the file
# (tests.py checks), every line of the file that is not here is one the
# screen never draws, and a path is named by exactly ONE tab.
#
# The owner's brief, 2026-09-01, after the first version showed him all
# hundred and forty lines at once: tabs across the top, plain words, a
# menu he can pick from wherever a value names a model, and "just set the
# things I do not need to change". 2026-09-18, on the two hundred: the
# measurements are the developer's, and the screen is for the person.


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

_ENGINES = (("local", "On this computer"),
            ("gemini", "In Google's cloud"))
_REPAIR = (("cloud", "Before the paste with a key, as a card without one"),
           ("always", "Always before the paste"),
           ("known", "Only taught words"),
           ("never", "Never"))
_DOT_CORNERS = (("bottom-right", "Bottom right"), ("top-right", "Top right"))
_SPEAK = (("off", "Never"), ("button", "With a button"), ("auto", "Always"))
_AFTER_SHOT = (("toast", "Show a small card"), ("editor", "Open the editor"),
               ("nothing", "Nothing"))
_QUALITY = (("small", "Small file"), ("balanced", "Balanced"),
            ("sharp", "Sharp"))
_MIC_TOO = (("off", "No"), ("mic", "Yes"))
_INTERRUPT = (("all", "Every message"),
              ("input", "Only what needs you"),
              ("none", "None"))

DOT_CORNER = Friendly(
    "dot.corner", "Which corner the dot sits in",
    "A corner of the main screen above the taskbar — or press Move the dot "
    "and put it anywhere you like. The panel and the key card open beside "
    "it wherever it ends up.", _DOT_CORNERS)

# ONE LINE, ONE PLACE. The owner, 2026-09-07, on tabs that repeated a
# setting and a last tab that repeated them all: "if there is
# 'Everything' then it is already somewhere else, so I do not need it" —
# and, on the sentences with controls inside them, "make normal settings,
# no need to be clever". And 2026-09-18, on a screen of two hundred
# lines: "a huge number of settings a simple user never needs; things
# like 'how many corrections before a word fixes itself' are things I
# change in development, not decisions a user should make." So: General
# is what a person changes about dictation and the screen, Screen is
# the pictures, Phone and Privacy are their own pages, and The app is
# the machine. Everything else in defaults.toml is a measurement the
# developer edits in the file, and the screen never draws it.
TABS: tuple[Tab, ...] = (
    Tab(GENERAL, (
        Group("", (
            Friendly("backend", "Where your speech is turned into words",
                     "On this computer is faster and better at Hebrew, and "
                     "nothing leaves the machine.", _ENGINES),
            Friendly("audio.device", "Microphone",
                     "Which microphone it listens to."),
            Friendly("auto_language", "Also understand English",
                     "The app decides for each recording; off, everything "
                     "you say is taken as Hebrew."),
            Friendly("punctuate.auto", "Punctuate every dictation",
                     "Commas, full stops and question marks go in on the "
                     "way to the cursor, which costs about a second each "
                     "time."),
            Friendly("punctuate.nikud", "Add vowel points as well",
                     "The Hebrew vowel marks go in along with the "
                     "punctuation."),
            Friendly("polish.when", "Fix misheard words with a model",
                     "With a cloud key the fix goes in before the text is "
                     "pasted (a third of a second); without one the model "
                     "on this PC takes 5-7 s, so the text is pasted at "
                     "once and its fix arrives as a card you can accept. "
                     "Or always before the paste, only for words you have "
                     "corrected before, or never.", _REPAIR),
            Friendly("vocab.enabled", "Use the words it has learned",
                     "Corrections you taught it with the correction key "
                     "are applied to new dictations."),
            Friendly("local.cleanup", "Take out the ums and the false starts",
                     "The sounds you make while thinking, and a phrase you "
                     "began again, are dropped."),
            Friendly("review.enabled", "Suggest a better word after a dictation",
                     "A small card offers the word it thinks you meant; "
                     "yes teaches it, no is remembered. Off, it learns "
                     "quietly instead."),
            Friendly("study.enabled", "Keep learning while the computer is idle",
                     "After a few quiet minutes it listens again to what "
                     "you dictated and learns from what it got wrong. "
                     "Nothing leaves this PC."),
            Friendly("translate.target", "Translate into",
                     "The language the translate key writes in."),
        )),
        Group("ON THE SCREEN", (
            Friendly("indicator", "Show the dot in the corner",
                     "Blue means it is listening, red means it is "
                     "recording, amber means it is writing your words "
                     "down. Click it and the panel opens beside it."),
            DOT_CORNER,
            Friendly("feedback.enabled", "Mark the cursor with … while it listens",
                     "The marker turns into your words when they arrive."),
            Friendly("hint.enabled", "Show the key card while a key is held",
                     "A card that says what the other keys do, once the "
                     "key has been held for a moment."),
            Friendly("auto_pause_fullscreen",
                     "Pause by itself while a game fills the screen",
                     "While a game or a presentation owns the whole "
                     "screen, the dictation key is left to it, and comes "
                     "back when it lets go."),
        )),
        Group("MESSAGES FROM OTHER PROGRAMS", (
            Friendly("notify.enabled", "Show messages from other programs",
                     "Off, nothing is shown, stored or played."),
            Friendly("notify.cue", "Play a sound when one arrives",
                     "Off, the card appears in silence."),
            Friendly("notify.interrupt", "Which messages pop up",
                     "Every one, only what is waiting on you, or none; "
                     "the rest wait quietly on the panel beside the dot.",
                     _INTERRUPT),
            Friendly("notify.summarize", "Say a finished message in one line",
                     "When Claude finishes, the card carries one plain "
                     "sentence about its message instead of the first "
                     "lines — written by Groq, with the cloud-text switch "
                     "on and a Groq key. Off, or without either, the card "
                     "shows the message's first lines."),
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
        )),
        Group("SCREENSHOTS AND RECORDINGS", (
            Friendly("capture.enabled", "Screenshots and screen recording",
                     "Off, both keys stop working and nothing is taken."),
            Friendly("capture.after_shot", "After a screenshot",
                     "What happens the moment you let go: a small card, the "
                     "editor, or nothing at all.", _AFTER_SHOT),
            Friendly("capture.always_save", "Always save the file as well",
                     "Off, the picture is on the clipboard and nowhere else "
                     "until you press Save."),
            Friendly("capture.folder", "Where pictures are saved",
                     "Screenshots and webcam photos both land here. A plain "
                     "name means a folder beside the app."),
            Friendly("capture.clip_folder", "Where recordings are saved",
                     "Empty means the same folder as the pictures."),
            Friendly("capture.quality", "Recording quality",
                     "How much detail a recording keeps, against how large "
                     "the file is.", _QUALITY),
            Friendly("capture.audio", "Record the microphone too",
                     "Off to start with: a recorder that quietly opens the "
                     "microphone is a surprise.", _MIC_TOO),
        )),
        Group("CAMERA", (
            Friendly("camera.enabled", "Take a photo with the webcam",
                     "Off, the key does nothing and the camera is never "
                     "opened."),
            Friendly("camera.device", "Which camera",
                     "Part of its name is enough. Empty means the first "
                     "real camera Windows lists."),
            Friendly("camera.mirror", "Mirror the picture",
                     "Off, because writing held up to a webcam reads "
                     "backwards mirrored."),
        )),
    )),
    Tab("Phone", (
        Group("DICTATING FROM THE PHONE", (
            Friendly("server.enabled", "Dictate from the phone",
                     "The phone keyboard sends its recordings here, over "
                     "your own private network."),
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
            Friendly("privacy.account", "An account",
                     "Anonymous, or your Google sign-in: for problem "
                     "reports you choose to send and for the two syncs. "
                     "Opens only through its card."),
            Friendly("privacy.report_upload", "Sending problem reports",
                     "Only what the preview showed. Opens only through its "
                     "card."),
            Friendly("privacy.settings_sync", "Syncing settings and words",
                     "Your changed settings, learned words and cloud keys "
                     "follow you to every PC you sign into — the keys "
                     "locked with your account's own key; never hotkeys, "
                     "devices, folders or positions. Comes with the "
                     "sign-in and the wizard's one sync switch; Withdraw "
                     "turns it off, Turn on here asks again."),
            Friendly("privacy.history_sync", "Syncing what you said",
                     "The Said page is the same on every PC you sign "
                     "into. Locked before it leaves with a key only your "
                     "own PCs hold: the server cannot read it (The lock, "
                     "below). Comes with the sign-in and the wizard's one "
                     "sync switch, like the settings; Withdraw turns it "
                     "off on its own, Turn on here asks again."),
        )),
        Group("SWITCHES", (
            Friendly("privacy.update_check", "Look for a newer version weekly",
                     "One request to GitHub, carrying no identifier."),
            Friendly("privacy.offline", "Offline mode",
                     "Nothing leaves this computer. Dictation keeps "
                     "working; cloud fixes, translation and updates "
                     "pause."),
        )),
        Group("KEPT ON THIS PC", (
            Friendly("history.keep_days",
                     "How long what you said is kept, in days",
                     "The Said page reads it; older lines are dropped. 0 "
                     "keeps no history at all."),
        )),
    )),
    Tab(APP, (
        Group("THIS COMPUTER", (
            Friendly("local.load_at_start", "Load the speech model when DeskIT starts",
                     "Off, DeskIT starts without it — every key that needs "
                     "no model works at once, and Start on the desk loads "
                     "it when you want to dictate."),
            Friendly("setup.autostart", "Start with Windows",
                     "Windows starts DeskIT when you sign in. Off, you "
                     "open it from the Start menu."),
            Friendly("awake.hold", "Hold the computer awake",
                     "While the app is running the machine will not fall "
                     "asleep on its own timer. The screens may still go "
                     "dark."),
        )),
    )),
)


def tab_named(name: str) -> Tab | None:
    for tab in TABS:
        if tab.name == name:
            return tab
    return None


def friendly_paths() -> list[str]:
    """Every path a tab names, tab by tab — each of them once."""
    return [row.path for tab in TABS for group in tab.groups
            for row in group.rows]


def label_for(path: str) -> str:
    """The friendly label a row shows for `path`, or the path itself
    when no tab draws it — a dialog's title, a message."""
    for tab in TABS:
        for group in tab.groups:
            for row in group.rows:
                if row.path == path:
                    return row.label
    return path


def groups_for(name: str) -> tuple[Group, ...]:
    """What a tab draws, in order. The rows are the tab's own; a tab
    that draws only blocks (a screen that used to be its own) has no
    groups at all."""
    tab = tab_named(name)
    return () if tab is None else tab.groups


def tab_names() -> list[str]:
    """The tabs in the order the bar shows them: General first, The app
    always last."""
    return [tab.name for tab in TABS]


WORDS: dict[str, Friendly] = {}
for _tab in TABS:
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

    Takes a Setting or a path. A line the tabs do not name — the screen
    never draws one, but the search box and the write confirmation may
    be handed any path — falls back to its own name with the underscores
    opened out and the first sentence of its comment."""
    path = setting if isinstance(setting, str) else setting.path
    row = WORDS.get(path)
    if row is not None:
        return row
    key = path.rsplit(".", 1)[-1].replace("_", " ").strip()
    label = (key[:1].upper() + key[1:]) if key else path
    help_text = "" if isinstance(setting, str) else _first_sentence(
        setting.help)
    return Friendly(path, label, help_text)
