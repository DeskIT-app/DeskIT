"""The control window: start it, pause it, stop it, read it back, rebind it.

Before this there were two shortcuts on the desktop — one that started the
app and one that stopped it — and nothing that could tell you which of
those had last happened. The status dot says "running", but only once
running; during the ~25 s of loading two Whisper models there is a splash
and after a stop there is nothing at all, and "is it on?" was answered by
holding the hotkey and seeing whether anything came out.

Three things follow from that, and they are still the whole design:

1. It is a SEPARATE PROCESS. Half its job is starting the app, so it has to
   exist while the app does not. It talks to the running instance over the
   named pipe in control.py, and reads config.toml directly when there is
   no instance to ask.
2. It never blocks its own event loop. Every request goes to a worker
   thread and comes back through a queue, because a pipe call against a
   busy app can take a second and a window that stops repainting while it
   waits is a window that looks crashed.
3. PAUSE is the reason it exists at all. Stopping the app to keep Right
   Ctrl out of a game costs ~25 s of reloading models to undo. Pausing
   costs nothing in either direction: the keys go inert, everything stays
   in VRAM, and resuming is instant.

WHAT CHANGED, AND THE TWO MEASUREMENTS BEHIND IT. This file used to say
Tk 8.6 had "no bidi support whatsoever", and everything followed from
that: the window was English-only, and the last dictation was shown as
"4.2 s -> 96 chars" with a Copy button rather than as the sentence
itself. The truth turned out to have two layers, both measured on
2026-08-20 and both subtler than the old claim:

1. THE FONT. "Segoe UI Variable" holds no Hebrew glyphs at all
   (GetGlyphIndicesW says so), and the per-word font fallback that papers
   over it breaks bidi run segmentation: every Hebrew word rendered
   LETTER-REVERSED — "בדקתי" drawn as "יתבדק" — which looks exactly like
   a transcription bug. ui.pick_face() exists so no face without measured
   Hebrew coverage can ever carry a transcript again.

2. THE BASE DIRECTION. With a Hebrew-capable face, Tk shapes each run
   correctly but hands ExtTextOutW an LTR paragraph, so the RUNS of a
   mixed line come out in the wrong order — the two Hebrew halves of
   "…יהיה sick אתה יודע…" swapped around the English word. Directional
   control characters (RLM, RLE) change nothing; Tk strips them. So
   transcripts are not Labels: ui.draw_text renders them with
   DrawTextW + DT_RTLREADING — the exact call popup.py has proven — into
   bitmaps, and tests.py holds a pixel-correlation test against that
   reference. Pure-Hebrew lines are a single run, which is why the first
   probes ("האם זה עובד?") looked right and nearly hid layer 2.

The CHROME stays English on purpose: a label is one direction by
construction, and Tk is still the wrong tool for a sentence it cannot be
told the direction of. `ui.is_rtl` aligns each drawn transcript the way
its first strong character will lay it out.

The look — rounded cards, the top bar, the switches — is all in ui.py; the
palette is unchanged from the first version of this window.
"""
from __future__ import annotations

import ctypes
import gc
import math
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

import _tkinter

APP_DIR = Path(__file__).resolve().parent

# Started BY PATH by an installed copy (launch.open_dashboard →
# `python\pythonw.exe app\dashboard.py`), whose python311._pth isolates
# sys.path to its four lines — the script's own folder is not one of
# them, so `import config` below found nothing and "Open the desk" did
# nothing (1.1.0, stderr in DEVNULL). The same guard as main.py's.
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import config as config_mod
import control
import history
import hotkey as hotkey_mod
import keycaps as keyboard_mod
import launch
import net
import awake as awake_mod
import hardware as hardware_mod
import models as models_mod
import packs as packs_mod
import settings as settings_mod
import singleton
import summary
import ui
import updates
import version
import widgets

import paths
DEFAULTS_PATH = paths.DEFAULTS_FILE
ICON_PATH = APP_DIR / "icon.ico"
ICON_PNG = APP_DIR / "icon.png"

# Any string, as long as it is OURS and stays put. Windows groups taskbar
# buttons and picks their icon by this; without one the window inherits
# pythonw.exe's identity, which is why the taskbar showed a generic file
# icon rather than the app's. Inside the Store package the window takes
# the package's own id: an id the package does not declare would be a
# taskbar button no Start tile owns, and a pin that launches nothing.
APP_ID = paths.APP_ID if paths.PACKAGED else paths.APP_ID + ".Dashboard"

W, H = 1160, 720         # fixed, which is what lets every bitmap be cached
SIDE = 0                 # the rail is gone; the places are along the top
TOP = 56                 # the bar: the mark, six places, the state, and
                         # whichever buttons the state allows
PAD = 24
CW = W - PAD * 2         # 1112 — the usable width of a screen

# THE RIGHT END OF THE BAR, in pixels. Stop used to sit 8 px from Pause
# and arm itself to make up for it; the arming is gone and these numbers
# are part of what took its place — see _paint_bar_buttons. BAR_GAP is
# ordinary spacing between two things that belong together; BAR_KEEP is
# the empty bar between Stop and the button next to it, and it is the one
# number here that is not taste.
BAR_RUN_W = 104          # Pause / Resume / Start — the key he presses all
                         # day, and the only one that is in every state
BAR_STOP_W = 84
BAR_GAP = 8              # was 12 until the seventh place (Network) needed the room
BAR_KEEP = 24

# activity -> (dot colour, the word for it). The colours are asked of
# `ui` when the chip is painted, not here, so a repainted palette lands
# without this table being edited; the WORDS are the five states the dot
# has, in the same spelling the dot's own tooltip uses.
LOOKS = {
    "stopped":   ("FAINT", "Off"),
    "starting":  ("AMBER", "Starting"),
    "ready":     ("COOL", "Listening"),
    "recording": ("RECORDING", "Recording"),
    "locked":    ("RECORDING", "Locked on"),
    "busy":      ("AMBER", "Transcribing"),
    "paused":    ("DIM", "Paused"),
    # The process up, the model not (main.py unload_model, 2026-09-18):
    # every key that needs no model works; the hold keys say so.
    "off":       ("DIM", "Model off"),
    "loading":   ("AMBER", "Loading"),
}

POLL_MS = 800
# How long this window stays hidden waiting for the dot to be dragged
# before it comes back whether or not anything happened. The APP gives up
# first — the framed move ends on Done, Enter, Esc or overlay.DOT_FRAME_S
# (180 s), and its next status says so, which is what normally ends the
# wait — so this is only the backstop for an app that stops answering
# mid-drag. A window that hid itself and never came back is a worse bug
# than a drag that had to be asked for twice. Longer than the app's own
# deadline on purpose: shorter, and the desk would come back over a
# light that is still up.
DOT_WAIT_S = 210.0
# THE PILE IS AS TALL AS ITS ROWS. It was a fixed 286 px card with a
# scroller inside it and "+N more", and the owner's photograph of it
# on 2026-09-07 was rows in the middle of an empty card: the card grew
# for "+N more" and the scroller inside it did not. On a home that
# scrolls as ONE page a card that scrolls inside it is a mistake twice
# over, so the card holds every row up to PILE_CAP and the page does
# the scrolling.
PILE_CAP = 3             # the most the HOME will ever hold. It is a
                         # summary: the newest three, then one line
                         # saying what else waits and where to read it
SAID_PAGE = 25           # rows a press of Show more adds on the Said
                         # place. A hundred at once was, in his words,
                         # "a lot to scroll and it is a nightmare"
PILE_ROW_H = 72
NET_ROW_H = 22           # one line of the Network table: a 9 pt
                         # Rubik box is 25 px in a Label, 22 as a
                         # canvas text item with no padding
PILE_Y = 100             # where the page starts, under the title
PAGE_H = H - TOP - PILE_Y - 62      # down to the footer rule

# THE DOORS ARE A BAND, AND THE BAND IS ALWAYS THERE. They were one thin
# 26 px line of counts that drew only the kinds with something waiting,
# so on a quiet desk it drew NOTHING — and the home was a headline, three
# one-line rows of the day, and 300 px of bare ground under them with the
# footer rule sitting on nothing. His words on 2026-09-07: "the home
# screen looks very empty and not good". A count that exists only when it
# is not zero cannot hold a page together. So every other place is on
# the band, always, each with what it is holding at this moment,
# them still the door it was — a count with nowhere to go is a count
# nobody can act on.
#
# The band is also where the page's slack goes, which is what stops the
# hole coming back somewhere else. Measured on this window (the page is
# 502 px and the day's block is 161): three pile rows leave the band its
# minimum and the page fills exactly, two leave it 142, none leave it the
# maximum and 141 px of ground that _settle_page spends putting the day's
# lines on the footer rule. Past DOOR_MAX_H a tile stops being a door and
# starts being a poster, which is why the leftover is ground and not more
# tile.
DOOR_MIN_H = 69          # the number and the line under it, and the pad.
                         # A FLOOR AND NOT THE ANSWER: what the band may
                         # never be shorter than. _paint_doors asks the
                         # tiles what they actually need in the font that
                         # is loaded and raises this if they need more,
                         # because a Card body is a create_window with a
                         # height and a band a pixel short cuts the words
                         # in half without saying so.
DOOR_MAX_H = 200
DOOR_NOTE_GAP = 5        # between the count's line and the third line
DOOR_GAP = 12            # between the tiles, and the least ground under
                         # the band
DOOR_PAD = 12
CAPTURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
# The Said half of the home is a list and a panel side by side. The list keeps the
# width a sentence needs; the panel takes what is left.
SAID_W = CW - 320

# THE CORRECTIONS PLACE HAS TWO TABS. Words (Waiting until 2026-09-21)
# is the whole list of what it has learned — every pair, searchable,
# each one editable and removable, a pair typed in by hand, and the
# switch that turns the lot off — with the second reading's proposals
# ABOVE the list while any wait, pushing it down. The owner, looking
# at a panel that showed the last six on the right: "a full list that
# anyone can see; a way to add by hand, because the transcriber writes
# the same wrong thing every time and the app never proposes it; the
# search; and the switch". Read aloud was the second tab here
# until 2026-10-01: one of his own sentences on a card, read
# into the dictation key with this window in front. It was the
# owner's corpus tool, never a user's, so it left the desk with
# the rest of his surface (MASTER.md §8); reading.py is still
# in the tree, and the chip comes back in one commit.
CORR_TABS = (("words", "Words"),)
WORD_ROW_H = 44          # one learned pair in the Words list
WORD_EDIT_H = 64         # the card a pair is typed or changed on
WORD_FIELD_W = 300       # each of its two fields


def corr_tabs() -> tuple:
    """The Corrections tabs this copy shows. Read aloud was his
    own corpus tool (reading.py) and left the desk on
    2026-10-01; the module is still in the tree, so putting
    its chip back is one commit.
    """
    return CORR_TABS
CORR_CHIPS_Y = 62
CORR_HEAD_Y = 110        # the "N proposals" line, under the chips
CORR_PAGE_Y = 140

# The Keys place, top to bottom. THE BOARD IS THE FULL-SIZE ONE since
# 2026-09-07 — 22.5 cap units wide against the tenkeyless 18.25, because
# that is the keyboard on his desk — and in a window fixed at 1160 wide
# the cap is what has to give. The room left over for the board is
# CW - KEY_PANEL_W - KEY_BOARD_GAP = 792 px, which keyboard.unit_for
# turns into a 34 px cap and a 781x239 board; the panel then takes the
# 311 px that are really left. Measured 2026-09-07, which is why the
# unit is asked for rather than typed: at the old 40 the board alone is
# 916 wide and leaves the panel 176, against the 208 one row of it needs
# and the 295 the widest line in the panel would want if it did not wrap
# (the Ctrl+Alt+M cap and "Dismiss the notification" beside it — it
# wraps, see _paint_rebind). The legend ends at 98 and the board starts
# at 100, so nothing
# overlaps anything; the foot is the one faint line about the safe keys,
# placed UP from the bottom edge (see _screen_keys).
KEY_PANEL_W = 300        # the least the panel beside the board may have
KEY_BOARD_GAP = 20       # between the board and that panel
KEY_BOARD_MAX_H = 247    # 487 of room under the legend, less 240 of rows
KEY_UNIT = keyboard_mod.unit_for(CW - KEY_PANEL_W - KEY_BOARD_GAP,
                                 KEY_BOARD_MAX_H)          # 34
KEY_COLUMNS = 3          # the rows are as wide as the board, not the place
KEY_LEGEND_Y = 58        # the five swatches; two lines each, ending at 98
KEY_BOARD_Y = 100
KEY_FOOT_GAP = 22        # ground under the last line, so it is not flush
KEY_FOOT_LINE = 17       # one line of the 8 pt foot, measured
KEY_ROW_H = 40           # a 30 px cap at y 4, or the cap and a note under it
SOUND_COLUMNS = 4

#: What each cue is FOR, in the words of the thing that plays it. The
#: list itself is cues.CUES, whose keys are code names — "noop",
#: "latch", "repaired" — and a Play button beside a code name tells a
#: person nothing (2026-09-22, the owner on names that come from the
#: code rather than from what a person sees). A cue with no line here
#: falls back to its key, and a test names that as a gap.
SOUND_WORDS: dict[str, str] = {
    "ready": "Ready to dictate",
    "start": "Recording started",
    "stop": "Recording ended",
    "latch": "The key locked on",
    "error": "Something went wrong",
    "bye": "The app stopped",
    "translating": "Translating",
    "translated": "Translation in place",
    "punctuating": "Punctuating",
    "punctuated": "Punctuation in place",
    "looking": "Looking a word up",
    "looked": "The answer is here",
    "repaired": "A word was fixed for you",
    "noop": "Nothing to do",
    "paused": "The keys are paused",
    "resumed": "The keys are back",
    "shot": "Screenshot taken",
    "recording": "Screen recording started",
    "recorded": "Screen recording saved",
    "notify": "A message arrived",
}
KEY_LEGEND = (
    ("held", "down the whole time it works", "hold"),
    ("tapped", "fires and still reaches the app underneath", "tap"),
    ("chord", "the modifier lit softly, the key fully", "chord"),
    ("only sometimes", "Esc, while a recording is running", "sometimes"),
    ("unlit", "the app never sees it", None),
)
HISTORY_ROWS = 100       # what "the last hundred" means, in one place
SEARCH_MS = 160          # how long typing has to stop before the list moves

# history.KINDS names a colour; ui.py owns what the colour is.
COLOURS = {"accent": ui.ACCENT, "teal": ui.TEAL, "violet": ui.VIOLET,
           "green": ui.GREEN, "amber": ui.AMBER, "red": ui.RED,
           "faint": ui.FAINT}

# FOUR PLACES, not nine rows. Ten days of use said the window sees 2.1
# actions a day and all twenty-one of them were the same four things:
# clearing review verdicts that had piled up, dismissing everything at
# once, turning the screens off, and rebinding a key. Nine equal rows
# with a 190-line Settings screen behind one of them is a filing cabinet
# for a drawer. It went to three places for an evening — Home, Keys,
# Settings, with everything on the home — and he read that home and
# said: "Home should be a summary, and then maybe add more tabs. Home
# is a summary of everything, and to get more information, I don't need
# everything on my home screen." So the home says WHAT is waiting and
# what happened today, in as few lines as it can, and each kind of
# thing has a place of its own to be read in full:
#
#   Home         a summary, and nothing that needs scrolling
#   Corrections  every word it has learned — the whole list, a search,
#                a pair typed in by hand, the switch — with the second
#                reading's proposals above the list while any wait
#                (his: "the vocabulary and all the corrections it does
#                automatically"; 2026-09-21: "a full list anyone can
#                see"). Read aloud, his own corpus tool, left
#                the desk on 2026-10-01; reading.py stays in
#                the tree
#   Said         transcripts.log read back, with the search
#   Keys         every binding, lit on a drawn keyboard
#   Settings     config.toml, on tabs
#
# And one screen that is NOT on the bar:
#   Network      every request this app made, newest first, from
#                network.log — the window of the key-privacy proof
#                (D12): during plain dictation the table stays empty.
#                It was the seventh place from PR 21 to 2026-09-18, when
#                he said "as a user I don't understand why I need it";
#                it is reached from Settings > Privacy (EVERY CONNECTION)
#                now, the bar lights Settings while it is up, and the
#                proof is where the keys and the account already are.
#
# Overview is gone: its state line is in the top bar now, on every place.
NAV = (("home", "Home"), ("corrections", "Corrections"),
       ("said", "Said"),
       ("keys", "Keys"), ("settings", "Settings"))

#: Every screen `_show` can draw: the six places and the one behind
#: Settings > Privacy. What a test that walks every screen walks.
SCREENS = tuple(name for _key, name in NAV) + ("Network",)

# A place takes its glyph from ui.ICON[key] where there is one. Home,
# Corrections and Said are new words for old screens, and ui.py
# is not this wave's file, so they borrow the glyphs those
# screens had — HERE, rather than the one table that names the places
# having to call them "overview" and "review". A key with no glyph and
# no entry here is still a KeyError the first time the bar is built,
# which is the point.
NAV_GLYPH = {"home": "overview", "corrections": "review",
             "said": "history"}

# The Awake screen probes the machine (powercfg, PowerShell — a few
# seconds) the moment it opens. Off for the tests, which open every
# screen and have no morning to worry about.
AWAKE_AUTO_CHECK = True

# Which keys belong together on the Keys screen. HOTKEY_FIELDS is still
# the one place a new key has to be added: anything not named here lands
# in the last group rather than vanishing.
KEY_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Recording", ("hotkey", "english_hotkey", "latch_hotkey")),
    ("What to do with the text", ("translate_hotkey", "punctuate_hotkey",
                                  "correct_hotkey", "lookup_hotkey",
                                  "visual_qa_hotkey")),
    ("What to do with the screen", ("capture_hotkey", "record_hotkey",
                                    "camera_hotkey")),
    ("The app itself", ("pause_hotkey", "screens_hotkey", "dismiss_hotkey",
                        "report_hotkey", "shelf_hotkey")),
)

# What a key MEANS, where its label is not enough: (three words for the
# row under the board, one sentence for the panel beside it). Only the
# pause key has one, and it earned it — "Pause / resume" read to the
# owner as quitting, and his words on 2026-09-07 were "I use insert to
# pause the model, not shut it down, just pause". This is the place
# saying that back to him. A field with no entry here shows nothing
# extra, which is every other key.
KEY_NOTES: dict[str, tuple[str, str]] = {
    "pause_hotkey": (
        "a pause, not a stop",
        "A pause, not a stop. Nothing is unloaded — the models stay on "
        "the card and coming back is instant — and this is the one key "
        "that still works while paused."),
}

# Keys that live INSIDE a config section, and the dotted path set_values
# must write them to. The same lines are in main.py, and the comment
# there says why they are not shared: both files are byte-identical on the
# classic branch, and config.py -- where this would naturally live -- is
# allowed to differ between the two.
NESTED_HOTKEYS = {
    "visual_qa_hotkey": "visual_qa.visual_qa_hotkey",
    "capture_hotkey": "capture.capture_hotkey",
    "record_hotkey": "capture.record_hotkey",
    "camera_hotkey": "camera.camera_hotkey",
    "screens_hotkey": "awake.screens_hotkey",
    "dismiss_hotkey": "notify.dismiss_hotkey",
    "report_hotkey": "problems.report_hotkey",
    "shelf_hotkey": "shelf.shelf_hotkey",
}

# The right-hand column of a settings row: a switch, a menu, or a field.
CONTROL_W = 236
ENTRY_W = 150
#: The folder settings get a picker beside their field (the owner,
#: 2026-09-19 evening: "it opens my whole computer and I mark where I
#: want" — he could not find where recordings go, nor type a path).
FOLDER_SETTINGS = frozenset({"capture.folder", "capture.clip_folder"})
BROWSE_W = 92
# A field is drawn as a ui.Field — a rounded Pillow face with the Entry
# flat inside it — at exactly the height ui.Dropdown is, because the two
# alternate down the same column and a field one pixel shorter than the
# menu above it reads as a mistake. The owner, 2026-09-07: "the boxes are
# square in everything that is not in General, and it is not pretty."
ENTRY_H = 30
# One quiet line under a block: the Overview's "nothing ahead" note.
FOLD_H = 26
# What a line of text really occupies on a settings card. Rubik's 8 pt
# linespace is 17 and its 10 pt is 20 — measured on the hidden desktop
# 2026-09-07, against the 15 the Segoe-era rows were drawn for. The rows
# with one block of text under them got away with 15 on their tail
# padding; a row that can also carry the file's own name and comment
# does not, and the first draft ran the comment into the next title.
LINE = 17                    # one line of the small face
TITLE_H = 22                 # a row's own name, and the air under it
# DROP_ROOM is what ui.Dropdown keeps for its own padding and caret glyph
# — its label is drawn at x 12 and its ▾ at w - 12, and it clamps to
# w - 40 — so a name cut to CONTROL_W - 46 is one the menu will never
# cut a second time, silently, at its own edge.
DROP_ROOM = 46
# A one-line field, and the strip the settings tabs live in. Rubik's line
# box is ~20% taller than the Segoe one these were drawn for: a 9 pt line
# needs 25 px and both search cards had an 18 px body, so the placeholder
# and the caret lost their descenders behind the card's edge; the tab
# strip was 36 for a 36 px chip plus 3 px of air, so every tab was
# squashed to 30. Both measured on the hidden desktop, 2026-09-07.
FIELD_H = 48                                 # 26 of body inside an 11 pad
TAB_BAR_H = max(ui.PILL_H + 6, FIELD_H)      # the tabs, or the field
SAID_HEAD_H = 22 + FIELD_H + 10 + ui.PILL_H + 4   # eyebrow, field, chips

# "Dictate (hold)" is one string in config.py because that is all the old
# window needed. Here the how is its own column.
HOW = re.compile(r"^(.*?)\s*\((hold|tap)\)\s*$")


def pretty_key(name: str) -> str:
    """'right ctrl' -> 'Right Ctrl'; '' -> 'off'."""
    return name.title() if name else "off"


def cap_title(cap_id: str) -> str:
    """What a cap is called in a sentence on the Keys place: 'num5' ->
    'NUMPAD 5', 'pgup' -> 'PAGE UP', 'q' -> 'Q'.

    The name comes from keycaps.name_for, which is the name the app
    would BIND it by — so the sentence and the config file cannot drift
    apart. The punctuation caps have no such name and keep their id.
    """
    return (keyboard_mod.name_for(cap_id) or cap_id).upper()


def human_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


# Three things want an answer, not 3. A number in a sentence that is
# about how much is left to do reads as data; the word reads as a
# sentence, which is what the title line is. Past six the digit is
# honestly better — "seventeen things" is a wall.
_COUNT_WORDS = ("No", "One", "Two", "Three", "Four", "Five", "Six")


def _minutes(seconds: float) -> str:
    """29.6 min, or 2.4 h once it is hours — the voice tally."""
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 60:.1f} min"


def _hours(seconds: float) -> str:
    return f"{seconds / 3600:g} h"


def _clock(seconds: float) -> str:
    """4:12 — today's reading, as a clock reads."""
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _count_word(n: int) -> str:
    return _COUNT_WORDS[n] if 0 <= n < len(_COUNT_WORDS) else str(n)


def _first_words(text: str, most: int) -> str:
    """The first `most` words of a run, marked when there are more.

    A dropped ending can be two dozen words and the chip that shows it is
    one line high — review_card.snippet already shortens the same run the
    same way for the card, and the two surfaces of one feature should not
    disagree about what they show.
    """
    words = str(text or "").split()
    if len(words) <= most:
        return " ".join(words)
    return " ".join(words[:most]) + " …"


def _words_learned() -> int | None:
    """How many corrections the vocabulary holds, or None if there is no
    file. The COUNT only — the words themselves are his."""
    import json
    try:
        with (paths.VOCAB_FILE).open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    entries = data.get("corrections") if isinstance(data, dict) else None
    return len(entries) if isinstance(entries, list) else None


def split_label(label: str) -> tuple[str, str]:
    match = HOW.match(label)
    return (match.group(1), match.group(2)) if match else (label, "")


def ago(at_iso: str, now: float | None = None) -> str:
    """"just now", "3 min ago", "2 h ago", "yesterday", "3 Sep" — how old
    a notification is, for the hero line. `at` is notify.py's local ISO
    stamp (2026-09-03T14:22:05); anything else reads as ''."""
    try:
        then = time.mktime(time.strptime(str(at_iso)[:19],
                                         "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return ""
    gap = (time.time() if now is None else now) - then
    if gap < 60:
        return "just now"
    if gap < 3600:
        return f"{int(gap // 60)} min ago"
    if gap < 86400:
        return f"{int(gap // 3600)} h ago"
    if gap < 2 * 86400:
        return "yesterday"
    return time.strftime("%d %b", time.localtime(then)).lstrip("0")


def _claim_taskbar_identity() -> None:
    """Tell Windows this window is its own app, before one exists.

    Must run BEFORE the first window is created — the identity is read when
    the taskbar button is made, and setting it afterwards changes nothing.
    Without it the button belongs to pythonw.exe and shows pythonw's icon,
    which reads as "some script is running", not as this program.
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass          # older Windows: the icon is still set below


def _set_window_icon(root) -> bool:
    """Hang the real icon on the window, both sizes.

    WM_SETICON rather than Tk's iconbitmap(): measured on this machine,
    iconbitmap(default=...) left WM_GETICON returning 0 for both ICON_BIG
    and ICON_SMALL, and the taskbar went on showing the host interpreter's
    generic icon. This asks Windows directly and is verifiable.

    Both sizes are loaded on purpose — they come from different frames of
    the .ico, and letting Windows scale the 32 px one down to 16 produces
    exactly the mush the small cut of the artwork exists to avoid.
    """
    IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x0010, 0x0080
    ICON_SMALL, ICON_BIG = 0, 1
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = user32.GetParent(int(root.winfo_id())) or int(root.winfo_id())
        ok = False
        for which, size in ((ICON_BIG, 32), (ICON_SMALL, 16)):
            handle = user32.LoadImageW(None, str(ICON_PATH), IMAGE_ICON,
                                       size, size, LR_LOADFROMFILE)
            if handle:
                user32.SendMessageW(hwnd, WM_SETICON, which, handle)
                ok = True
        return ok
    except Exception as e:
        _log_icon_problem(e)
        return False


def _set_taskbar_relaunch(root) -> bool:
    """Teach the taskbar what pinning this window should MEAN.

    SetCurrentProcessExplicitAppUserModelID gives the running window its
    own taskbar button — but a PIN is a different animal: Windows builds
    it from the process executable, and this process is pythonw.exe. So
    the pinned tile came up with Python's icon, said "Python" in its
    menu, and clicking it would have opened a bare interpreter.

    The fix is three per-window properties (IPropertyStore on the HWND):
    the relaunch COMMAND (wscript + Dashboard.vbs — the same launcher the
    desktop shortcut uses, and its second-instance logic means a click on
    the pin fronts the window that exists), the relaunch NAME, and the
    relaunch ICON. Set before the window is long-lived, because the shell
    reads them when the pin is created.

    comtypes rather than raw vtable ctypes: it is already a dependency
    (pycaw brings it in), and a hand-rolled IUnknown is the kind of code
    that works until the day it corrupts a stack.

    Not inside the Store package: there the window carries the package's
    own id, and a pin of it is the package's tile, which launches
    DeskIT.exe — a relaunch command naming the versioned python\\ under
    WindowsApps would go stale with the next update.
    """
    if paths.PACKAGED:
        return False
    try:
        from ctypes import POINTER, wintypes

        import comtypes
        from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

        class PROPERTYKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

        class PROPVARIANT(ctypes.Structure):
            # Only the VT_LPWSTR shape of the union — all this ever holds.
            _fields_ = [("vt", wintypes.USHORT),
                        ("r1", wintypes.USHORT), ("r2", wintypes.USHORT),
                        ("r3", wintypes.USHORT),
                        ("pwszVal", wintypes.LPWSTR),
                        ("pad", ctypes.c_void_p)]

        class IPropertyStore(IUnknown):
            _iid_ = GUID("{886d8eeb-8cf2-4446-8d02-cdba1dbdcf99}")
            _methods_ = [
                COMMETHOD([], HRESULT, "GetCount",
                          (["out"], POINTER(wintypes.DWORD), "count")),
                COMMETHOD([], HRESULT, "GetAt",
                          (["in"], wintypes.DWORD, "index"),
                          (["out"], POINTER(PROPERTYKEY), "key")),
                COMMETHOD([], HRESULT, "GetValue",
                          (["in"], POINTER(PROPERTYKEY), "key"),
                          (["out"], POINTER(PROPVARIANT), "value")),
                COMMETHOD([], HRESULT, "SetValue",
                          (["in"], POINTER(PROPERTYKEY), "key"),
                          (["in"], POINTER(PROPVARIANT), "value")),
                COMMETHOD([], HRESULT, "Commit"),
            ]

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(int(root.winfo_id()))
        store = POINTER(IPropertyStore)()
        hr = ctypes.windll.shell32.SHGetPropertyStoreForWindow(
            hwnd, ctypes.byref(IPropertyStore._iid_), ctypes.byref(store))
        if hr != 0:
            return False
        fmtid = GUID("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")
        command = " ".join(f'"{part}"' for part in launch.dashboard_command())
        values = (
            (5, APP_ID),                                        # ...ID
            (2, command),                                       # ...Command
            (4, "DeskIT"),                    # ...DisplayName
            (3, f"{ICON_PATH},0"),                      # ...IconResource
        )
        VT_LPWSTR = 31
        for pid, text in values:
            key = PROPERTYKEY(fmtid, pid)
            value = PROPVARIANT()
            value.vt = VT_LPWSTR
            value.pwszVal = text
            store.SetValue(key, value)
        store.Commit()
        return True
    except Exception as e:
        import logging
        logging.getLogger("app").debug("relaunch properties not set: %r", e)
        return False


def _dark_caption(root) -> None:
    """Paint the title bar the colour of the window.

    A pale strip above a dark window is the loudest thing left saying
    "this is a script with a window round it". Three DWM attributes:
    immersive dark mode (20), the caption colour (35) and the caption text
    colour (36), the last two Windows 11 22000+. They are COLORREF, i.e.
    0x00BBGGRR — the bytes are the reverse of the hex in the palette.
    """
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(int(root.winfo_id()))
        for attribute, value in ((20, 1), (35, 0x17100D), (36, 0xF4ECE8)):
            payload = ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(payload), 4)
    except Exception:
        pass          # Windows 10, or an older build: the window still works


def _round_frameless(win, border: str | None = None) -> None:
    """Take the corners off a window that has no frame to round them.

    A card on a frameless Toplevel has a problem the framed one does not:
    ui.rounded draws the rounded face against a BACKGROUND COLOUR — there
    is no per-pixel alpha anywhere in Tk — so with no window behind it to
    be the background, the four corners come out as four little squares
    of ui.BG sitting on top of whatever is really there.

    Measured 2026-09-04, three ways out, 10x crops of each in the
    scratchpad. Chroma key (`-transparentcolor`) does cut a true hole,
    but overlay.py already says why it is not the answer: it keys one
    exact colour and antialiases nothing, so the curve comes out as
    stairs with a fringe of the key colour. Doing nothing leaves the
    squares. DWM (attribute 33, DWMWA_WINDOW_CORNER_PREFERENCE = 2)
    clips the WINDOW ITSELF and antialiases the clip against the real
    desktop, and it does that to a WS_POPUP window, which is what
    overrideredirect makes. So the card is painted flat to its own edges
    and Windows rounds it. Attribute 34 is the hairline around that clip,
    the only thing left saying where the card ends on a pale background.

    The radius is Windows', ~8 px, not the 12-14 the cards inside the
    window use — a small honest difference, and the alternative is a
    corner that lies about what is behind it. Windows 10 has neither
    attribute and silently keeps both: a square card, which is still the
    card alone and not a card in a box.
    """
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(int(win.winfo_id())) \
            or int(win.winfo_id())
        pref = ctypes.c_int(2)                       # 2 = round
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(pref), 4)
        if border:
            # COLORREF, 0x00BBGGRR — the bytes reverse, same as the
            # caption colours above.
            r, g, b = (int(border[i:i + 2], 16) for i in (1, 3, 5))
            colour = ctypes.c_int((b << 16) | (g << 8) | r)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 34, ctypes.byref(colour), 4)
    except Exception:
        pass          # older Windows: a square card, and nothing else lost


# The report field's shape, and problem_card owns every number in it.
# The hotkey card paints its well from these and the box in this window
# places a widget by them; they are ONE field on two surfaces, and two
# copies of the numbers would disagree by the first tweak. The fallbacks
# are that module's own values, so a tree without it still gets the field
# the owner approved rather than the "slop and strict" one he did not.
try:
    import problem_card as _pc
except Exception:                         # noqa: BLE001 — feature absent
    _pc = None

FIELD_FONT = getattr(_pc, "FIELD_FONT", ("Rubik", 12))
FIELD_FONT_LINE = getattr(_pc, "FIELD_FONT_LINE", 18)
FIELD_LINE_H = getattr(_pc, "FIELD_LINE_H", 22)
FIELD_LINES_MIN = getattr(_pc, "FIELD_LINES_MIN", 3)
FIELD_LINES_MAX = getattr(_pc, "FIELD_LINES_MAX", 8)
FIELD_PAD_X = getattr(_pc, "FIELD_PAD_X", 12)
FIELD_RADIUS = getattr(_pc, "FIELD_RADIUS", 9)
FIELD_PAD_Y = getattr(_pc, "FIELD_PAD_Y", 9)
REPORT_HINT = getattr(_pc, "HINT",
                      "The screen you are on, the last dictation and the "
                      "settings behind it are attached for you.")
REPORT_KEYS = getattr(_pc, "KEYS", "Enter sends  ·  Shift+Enter for a "
                                   "new line  ·  Esc cancels")
# The copy that travels (plan 7.6, screen 7): the checkbox, the strip's
# words and the two labels the primary button switches between, all
# problem_card's, for the reason the block above gives.
REPORT_KEYS_SEND = getattr(_pc, "KEYS_SEND", "Enter continues  ·  Shift+Enter "
                                             "for a new line  ·  Esc cancels")
REPORT_KEEP = getattr(_pc, "SEND_LABEL", "Keep on this PC")
REPORT_PREVIEW = getattr(_pc, "PREVIEW_LABEL", "Preview")
REPORT_SEND_TOGGLE = getattr(_pc, "SEND_TOGGLE_LABEL", "Send to the developer")
REPORT_STRIP = getattr(_pc, "STRIP_EYEBROW", "WHAT LEAVES THIS PC")
REPORT_ATTACH = tuple(getattr(_pc, "ATTACH_ORDER",
                              ("shot", "recording", "transcript", "settings")))
REPORT_ATTACH_WORDS = dict(getattr(_pc, "ATTACH_WORDS", {}))
REPORT_NONE = getattr(_pc, "NONE_WORD", "none")


def _size_word(n) -> str:
    return _pc.size_word(n) if _pc is not None else str(n)


def _display_lines(widget) -> int:
    """How many lines a tk.Text is actually SHOWING.

    Asked of the widget rather than guessed from the length of the
    string: it is the widget that wrapped it, and the field is drawn to
    this number. `count` answers with a one-tuple on some Tk builds and a
    bare int on others, so both are unwrapped; a build with neither says
    one line, and the field then simply does not grow — which is the
    behaviour it had yesterday, not a traceback.
    """
    try:
        got = widget.count("1.0", "end", "displaylines")
    except Exception:                     # noqa: BLE001
        return 1
    if isinstance(got, (tuple, list)):
        got = got[0] if got else 1
    return max(1, int(got or 1))


def _problems_enabled() -> bool:
    """Is his own bug list switched on? [problems] enabled, read here.

    config.toml promises that false "unregisters the key, takes the
    Report button away and writes nothing", and the first two of those
    are this window's half of the promise. Read the way the rest of the
    startup path reads a section: getattr for the section and then for
    the field, because a Config can be missing [problems] altogether —
    an older config.toml, or one this branch has never written — and the
    dashboard has to open either way. A missing section reads as what the
    shipped file carries, which is on; a config that will not load at all
    says nothing about what he wants, so it changes nothing here.
    """
    try:
        pcfg = getattr(config_mod.load_layered(), "problems", None)
    except Exception:                     # noqa: BLE001 — never fatal here
        return True
    return bool(getattr(pcfg, "enabled", True))


def _relaunch_dashboard() -> bool:
    """Open a fresh copy of this window, the way the taskbar pin does:
    wscript + Dashboard.vbs, the launcher the shortcut and the pin both
    run (_set_taskbar_relaunch teaches the pin that exact command).

    Detached, as launch.spawn detaches the app: this process is on its
    way out and the child must not go with it. It is called from main()
    AFTER the instance mutex is released — see main for why the order
    is the whole trick.
    """
    import subprocess

    try:
        subprocess.Popen(launch.dashboard_command(),
                         cwd=str(APP_DIR), creationflags=launch._DETACHED,
                         close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError as e:
        import logging
        logging.getLogger("app").info(
            "relaunch: the window could not be opened again (%s)", e)
        return False


def _wrap(widths, limit: int, gap: int = 6,
          step: int = 36) -> list[tuple[int, int]]:
    """Where each pill in a row of them goes, wrapping when the line is
    full — the same arithmetic whether the strip is being measured or
    placed, which is why it is a function and not a loop in two places.
    """
    spots, x, y = [], 0, 0
    for width in widths:
        if x and x + width > limit:
            x, y = 0, y + step
        spots.append((x, y))
        x += width + gap
    return spots


class _Column:
    """A frame inside the page that the row builders treat like a
    Scroller: `.inner` to pack into, `clear()`, `bind_wheel()` so the
    page scrolls from a row too, and a `to_top()` that does nothing —
    the page decides where it is, and a list redrawn under the reader
    must not yank the page back to the top."""

    def __init__(self, inner, page) -> None:
        self.inner, self.page = inner, page

    def clear(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()

    def bind_wheel(self, widget) -> None:
        self.page.bind_wheel(widget)

    def to_top(self) -> None:
        pass


def _keys_screen_paths() -> set[str]:
    """The config.toml paths the Keys screen owns. The Settings screen
    leaves those to it — one place to rebind a key — and a test holds the
    two screens to covering the file between them."""
    return {NESTED_HOTKEYS.get(field, field)
            for field, _label in config_mod.HOTKEY_FIELDS}


def _dot_states() -> dict:
    """`skin.palette.DOT_STATES` if the skin is here, else {}.

    The corner dot and this window are the same lamp seen twice, and the
    one table that measured the five states is the skin's. Asked for at
    call time and never at import: deleting `skin\\` is the supported way
    back to a plain window (SKIN.md), and this must not be the import
    that makes that fail."""
    try:
        from skin import palette as skin_palette
    except Exception:                     # noqa: BLE001 — no skin folder
        return {}
    return getattr(skin_palette, "DOT_STATES", {}) or {}


def _look_colours(activity: str) -> tuple[str, str]:
    """(colour, word) for a state.

    The colour comes from the DOT's OWN table first — the five states in
    `skin.palette.DOT_STATES`, which is where they were measured against
    the dot's dark backplate — so the chip in the bar and the dot in the
    corner can never disagree about what "transcribing" looks like. That
    matters for one state in particular: the lamp at full is `#f5c043`
    and `AMBER` is `#e3a63c`, and reading the second would have made the
    two lamps two colours.

    Without a skin folder it falls back to `ui`, resolved at the moment
    it is asked for; a palette with neither COOL nor RECORDING falls back
    again, so this window opens on a checkout whose ui.py predates them.
    """
    name, word = LOOKS.get(activity, LOOKS["ready"])
    measured = _dot_states().get(activity)
    if measured:
        return measured[0], word
    fallback = {"COOL": "ACCENT", "RECORDING": "RED"}.get(name, "DIM")
    colour = getattr(ui, name, None) or getattr(ui, fallback, ui.DIM)
    return colour, word


def _has_halo(activity: str) -> bool:
    """Whether this state's lamp carries a glow.

    Paused has none — that is the whole way "off" is told apart from
    "quiet" at a glance, and it is `skin.palette.NO_HALO`'s rule. Off and
    starting-blind are the same kind of nothing, so they are here too."""
    if activity in ("paused", "stopped", "off"):
        return False
    try:
        from skin import palette as skin_palette
    except Exception:                     # noqa: BLE001 — no skin folder
        return True
    return activity not in getattr(skin_palette, "NO_HALO", frozenset())


def _quiet_button(*args, **kwargs):
    """ui.Button, quiet — as a plain function so it can stand where
    widgets.gold_button stands."""
    return ui.Button(*args, quiet=True, **kwargs)


def _shown(value) -> str:
    """A value as the field shows it, and as config.set_values will read
    it back: repr for a float so 6.0 stays 6.0, str for the rest."""
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _parse(raw: str, kind: str):
    """What was typed, as the kind the file holds. An int field refuses a
    fraction rather than rounding it: config.py would int() it silently,
    and 400.5 becoming 400 without a word is the kind of edit nobody can
    later explain."""
    raw = raw.strip()
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    return raw


def _log_icon_problem(error) -> None:
    # Nothing here is worth failing a window over, but a silently missing
    # icon is indistinguishable from one that was never asked for.
    import logging
    logging.getLogger("app").debug("could not set the window icon: %r", error)


class Dashboard:
    def __init__(self) -> None:
        _claim_taskbar_identity()
        # A PhotoImage belongs to the interpreter that made it, and the
        # test suite builds more than one Dashboard in a process.
        ui.forget_images()
        self.root = tk.Tk()
        # The checkout says so in its title (D30, the owner's ask of
        # 2026-09-18: the dev copy is marked, the installed one is not).
        self.root.title(f"DeskIT {paths.DEV_TAG}".strip())
        # `default=` so the key-capture dialog inherits it too, rather than
        # opening with the plain Tk feather next to a branded parent. It is
        # not enough on its own — see _set_window_icon below, called once
        # the window is realised.
        try:
            self.root.iconbitmap(default=str(ICON_PATH))
        except Exception:
            pass      # icon.ico missing or unreadable: not worth failing over
        self.root.geometry(f"{W}x{H}")
        self.root.configure(bg=ui.BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        self.status: dict = {}
        self.running = False
        self.closing = False
        # The branch this folder is on, for the Overview meta line and the
        # Version screen — read once at import by version.py (git only in
        # the checkout, "" on an installed copy), so no thread and no
        # spawn here; the version number comes from the same module.
        self.branch = version.BRANCH
        # Latched, not re-derived, because the pause taken by the key
        # dialog has to be undone from wherever that dialog's life ends —
        # including a route that never runs its own close handler.
        self._paused_for_capture = False
        self._events: queue.Queue = queue.Queue()
        self._busy_until = 0.0     # ignore polls right after a command, so a
                                   # stale status cannot flicker the buttons
                                   # back for one frame
        self.screen = "Home"
        self.parts: dict = {}      # the widgets of whichever screen is up
        self.log: list[history.Event] = []
        self._log_stamp: tuple[int, float] = (0, 0.0)
        self._filter: str | None = None
        self._query = ""
        # The Corrections place: which tab is up, the search
        # box, and the pair being typed.
        self._corr_tab = "words"
        self._words_query = ""          # the Words list's search box
        self._words_search_after = None
        self._words_editing = None      # None, "" (a new pair) or a heard form
        self._toast = None
        self._toast_after = None
        self._pump_after = None
        self._search_after = None
        self._settings_query = ""
        self._settings_after = None
        self._settings_tab = settings_mod.GENERAL
        self._settings_searching = False
        # The settings cards still to be built, one per tick — see
        # _fill_settings — and the tick that will build the next.
        self._settings_left: list = []
        self._settings_tick = None
        # THIS WINDOW HAS HIDDEN ITSELF SO HE CAN DRAG THE DOT, and this
        # is when to stop waiting for it. 0.0 = not waiting. A deadline
        # rather than a flag, because the thing that ends the wait is in
        # ANOTHER PROCESS: if the app stops answering mid-drag there has
        # to be something that still puts this window back.
        self._dot_waiting = 0.0
        # Q1 (2026-09-18): the signed-out landing is up — the places are
        # off the bar and the sheet holds one card. See _landing.
        self._landing_up = False
        self._rows_after = None
        self._rows_left: list = []
        # How wide a drawn row is on the place that is up. The Said list
        # shares its place with the vocabulary panel, so it is narrower
        # than the sheet; every other list is the full width.
        self._row_w = CW
        self._slide_after = None
        # The frame of the arrival that _slide_after will show while that
        # is an arrival on the cover (None for the old slide, or nothing
        # pending) — what a switch or a tab asked for mid-arrival folds
        # into (_hold_for) instead of photographing a third picture.
        self._arrival_next = None
        # The picture of the pane a switch holds over it (_show), built in
        # _build once the pane exists; a switch in progress; and the place
        # asked for while it was, with its `then` — (name, then) (_show).
        self._hold = None
        self._switching = False
        self._show_next = None
        self._breath_after = None
        self._stats_shown = False   # the count-up runs once per screen visit
        self._activity = "stopped"  # what the breathing loop reads
        self._toast_text = ""
        self._keep: list = []      # PhotoImages Tk will not keep for us
        # ONCE, and before _build: the sidebar is built one time and this
        # switch decides how many rows are in it. Re-reading it later
        # would only mean a window whose nav disagreed with its own
        # geometry halfway down.
        self._problems_on = _problems_enabled()
        # Where he last dragged the report card to, or None for "it has
        # never been dragged, put it over the middle of this window". Held
        # on the dashboard rather than in the box, because the box is
        # built and destroyed per report and the whole point is that the
        # next one opens where he left the last one. It is forgotten when
        # this window closes: remembering across restarts is a line in
        # config.toml, which is another file.
        self._report_at = None
        # The Preview (plan 7.6): which report's is open, and which rows
        # already had theirs opened by this window — once each.
        self._preview_open = ""
        self._preview_top = None          # the Toplevel while one is up
        self._previewed: set[str] = set()
        # Nothing sets this any more: Restart left with the git
        # card (MASTER.md §8). run() and _close still read it.
        self._relaunch = False
        # Which of the Home place's two views is up: the calm home, or
        # the whole backlog behind it.
        self._waiting_view = "home"
        # Which binding the key dialog is listening for, or None. The
        # panel beside the keyboard reads it, so the board says "press
        # the key you want" at the same moment the dialog does.
        self._capturing = None
        self._cap_selected = None

        self._build()
        # After _build: LoadImage/WM_SETICON need a realised window, and on
        # an unrealised one they report success and do nothing.
        self.root.update_idletasks()
        _set_window_icon(self.root)
        _set_taskbar_relaunch(self.root)
        _dark_caption(self.root)
        self._refresh(None)
        threading.Thread(target=self._poller, daemon=True,
                         name="dashboard-poll").start()
        # Someone double-clicked the shortcut again. That launch cannot
        # open a second window (see main), so it pokes this one instead.
        self._show_signal = singleton.Signal(singleton.DASHBOARD_SHOW)
        threading.Thread(target=self._watch_for_reopen, daemon=True,
                         name="dashboard-reopen").start()
        self._pump_after = self.root.after(80, self._pump)
        self._breathe()

    def _watch_for_reopen(self) -> None:
        while not self.closing:
            # A timeout, not an infinite wait: this thread has to notice
            # the window closing rather than sit on the handle forever.
            if self._show_signal.wait(400):
                self._events.put(self._raise_window)

    def _raise_window(self) -> None:
        """Bring this window back from wherever it went — minimised, or
        buried under a full-screen browser."""
        try:
            self.root.deiconify()
            self.root.lift()
            # Topmost briefly and then not: lift() alone loses to whatever
            # currently owns the foreground, and staying topmost would make
            # it a nuisance that sits over everything.
            self.root.attributes("-topmost", True)
            self.root.after(300,
                            lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except Exception:
            pass
        self._preview_if_waiting()

    def _preview_if_waiting(self) -> None:
        """A report the hotkey card marked for its Preview (plan 7.6,
        screen 7: "from the hotkey card it opens the dashboard
        with the preview"): the app is another process, so the row
        is the message — this window looks for one when it comes
        up and whenever the show signal brings it forward, and
        opens the Preview on the newest such row over whatever
        place is up. Once per row: a preview he closed without
        answering stays a report with its toggles as he left them,
        not a window that keeps coming back."""
        module, store = self._problems(), self._problems_store()
        if module is None or store is None or not hasattr(module, "awaiting_preview"):
            return
        if self._landing_up:
            return
        try:
            item = module.awaiting_preview(store)
        except Exception:                 # noqa: BLE001
            return
        if not item:
            return
        ident = str(item.get("id", ""))
        if not ident or ident in self._previewed:
            return
        self._previewed.add(ident)
        self.root.after(150, lambda: self._report_preview(ident))

    # ------------------------------------------------------------- chrome

    def _build(self) -> None:
        self._topbar()
        self.pane = tk.Frame(self.root, bg=ui.BG, width=W, height=H - TOP)
        self.pane.place(x=0, y=TOP)
        self.pane.pack_propagate(False)
        # Screens are built onto a SHEET inside the pane, not onto the pane
        # itself, so a new screen can slide into place — the pane stays
        # put, the sheet moves. The toast lives on the pane and does not.
        self.sheet = tk.Frame(self.pane, bg=ui.BG, width=W, height=H - TOP)
        self.sheet.place(x=0, y=0)
        self.sheet.pack_propagate(False)
        # The cover a switch holds over the pane (_show). Its window and
        # its two pictures go with the pane — a test's window is destroyed
        # without _close — and the binding holds the hold, not self,
        # because _bury empties self.
        hold = self._hold = widgets.PaintHold(self.pane, ui.BG)
        self.pane.bind("<Destroy>", lambda _e, h=hold: h.close())
        self._show("Home")
        # No account on this PC: the landing from the first frame, not
        # after the first poll's flash of Home (Q1). The poll re-decides
        # from the app's own word the moment it answers.
        if self._locked_now(None):
            self._landing(True)
        # A report the hotkey card left waiting for its Preview
        # opens over Home, once the first frame is up.
        self.root.after(600, self._preview_if_waiting)

    def _topbar(self) -> None:
        """The mark, the five places, the state, and whichever buttons the
        state allows — one 56 px strip.

        THE RAIL IS GONE, and the reason is arithmetic as much as taste.
        A 212 px rail took 18% of the window to say four words, and the
        nine rows in it were a menu of screens that saw two actions a day
        between them. Along the top the same four words cost 56 px of
        height, the content gets the whole width, and the state — the one
        thing that was worth keeping visible on every screen — sits at the
        right of the bar where it is read as a sentence rather than as a
        card in a corner.

        THE RIGHT END IS BUILT HERE AND PLACED SOMEWHERE ELSE. The state
        and the buttons are one group, and `_paint_bar_buttons` lays that
        whole group out from the right edge every time the state changes,
        because which buttons exist depends on the state — his rule, and
        the reason for it, are written out there. A position written down
        in two places is a button that ends up in two places.
        """
        bar = tk.Frame(self.root, bg=ui.BG, width=W, height=TOP)
        bar.place(x=0, y=0)
        bar.pack_propagate(False)
        self.bar = bar
        # THE MARK ALONE. The wordmark used to sit beside it and it cost
        # 90 px of a bar that now carries six places, the state and three
        # buttons — and the window's own title bar says DeskIT one line
        # above it. Measured 2026-09-07: with the word, the places ran
        # under the state chip.
        badge = ui.icon_bitmap(ICON_PNG, 26, ui.BG)
        if badge is not None:
            self._keep.append(badge)
            tk.Label(bar, image=badge, bg=ui.BG).place(x=PAD, y=15)
        if paths.DEV_TAG:
            # "DEV" under the mark, inside the mark's own 32 px — the
            # places start at PAD + 32 and the bar is measured to the
            # pixel (the comment below), so the tag takes no width.
            tk.Label(bar, text="DEV", bg=ui.BG, fg=ui.AMBER,
                     font=(ui.MEDIUM, 6)).place(x=PAD + 13, y=43, anchor="n")

        self.nav = widgets.Tabs(bar, [name for _key, name in NAV], bg=ui.BG,
                                selected="Home", command=self._nav_go, gap=10)
        # The bar is measured rather than guessed: the places start
        # after the mark and have to end before the state chip in EVERY
        # state. 24 + 26 mark + 6 air = 56; the seven words of 2026-09-17
        # ended at 544 at gap 10, and the six since Network left the bar
        # end sooner. Since every word keeps its BOLD width (widgets.Tabs,
        # 2026-09-22) the six end at 488 whichever is lit, against a chip
        # edge of 544 measured on the hidden desktop in the widest state
        # the bar then had — "Transcribing" with Stop tests up. That
        # button left on 2026-10-01 (MASTER.md §8), so the chip can only
        # start FURTHER right from now on and 56 px is a floor. Three
        # tests hold it (tests.py twice, tests_ops.py).
        self.nav.place(x=PAD + 32, y=17)

        # The state chip and the buttons are placed from the RIGHT edge, so
        # a longer word ("Transcribing") grows leftwards into empty bar
        # rather than pushing a button off the window.
        # STOP IS IN THE BAR because he asked for it there ("I don't have
        # a button to shut down the model, I only have a button to pause
        # it"), and it does the same thing Settings › About's Quit does,
        # in one press.
        self.parts["stop_bar"] = ui.Button(
            bar, "Stop", self._stop, w=BAR_STOP_W, h=32, bg=ui.BG,
            quiet=True)
        self.parts["run"] = ui.Button(bar, "Pause", self._toggle_pause,
                                      w=BAR_RUN_W, h=32, bg=ui.BG,
                                      quiet=True)
        # SCREENS OFF is in the bar, on every place. It was a small gold
        # link in the home's footer and the owner could not find it
        # (2026-09-07: "it would have been good to understand where it
        # was"); a button beside Pause is where a thing pressed every
        # evening belongs. Its width is measured once and kept, so that
        # "Screens on" does not shuffle its neighbours when the screens
        # go dark.
        self._screens_w = widgets.button_width("Screens off", icon=True)
        self.parts["bar_screens"] = ui.Button(
            bar, "Screens off", lambda: self._screens("toggle"),
            w=self._screens_w, h=32, bg=ui.BG, quiet=True,
            icon=ui.ICON["awake"])
        chip = widgets.StateChip(bar, bg=ui.BG, size=15)
        self.parts["chip"] = chip
        # The three names the rest of the window has always used for the
        # state, kept: _refresh writes the word and the uptime through
        # them, and nine tests read them.
        self.parts["lamp"] = chip.lamp
        self.parts["state"] = chip.word
        self.parts["uptime"] = chip.meta
        self._paint_bar_buttons()
        # The dictation-key hint used to live under the wordmark in the
        # rail. It is one line of chrome that repeated what the Keys
        # place says in full, so it is now the bar's tooltip-of-record:
        # built, never placed, and read by _refresh and by the tests.
        self.parts["hint"] = tk.Label(bar, text="", bg=ui.BG, fg=ui.FAINT,
                                      font=(ui.UI, 8))
        widgets.rule(self.root, W, bg=ui.BG, colour=ui.RULE, x=0, y=TOP - 1)

    def _nav_hover(self, name: str, over: bool) -> None:
        self.nav._hover(name, over)

    def _paint_nav(self, paint: bool = True) -> None:
        # Network is behind Settings > Privacy, so Settings is the word
        # that lights while it is up — and the way back. The landing has
        # no word: the places are off the bar while it is up. `paint`
        # False sets the word and leaves the pixels to nav.paint() — the
        # arrival's first frame (_reveal).
        self.nav.select("Settings" if self.screen == "Network"
                        else None if self.screen == "Landing" else self.screen,
                        paint=paint)

    def _nav_go(self, name: str) -> None:
        """A click on a place in the bar. On the place that is already up
        it does NOTHING: it used to tear the screen down, build it again
        and slide it in — a blank pane and a rebuild for a click that
        asked for what was already there. The guard is here and not in
        _show, which rebuilds the place that is up ON PURPOSE for the
        Corrections chips and the report's Preview. Network lights
        Settings, and Settings is the way back from it, so a click on
        Settings there is a switch like any other."""
        if name == self.screen:
            return
        self._show(name)

    def _show(self, name: str, then=None) -> None:
        """Swap screens. Everything the old one registered goes with it, so
        _refresh has to ask for a widget rather than assume one.

        `then` runs once the new screen is built, under the same cover,
        before it is painted and photographed: for a door that lands on a
        place AND changes something there (the pile's [Type the recovery
        key] opens the lock card's field). Done after _show came back,
        that change is a second rebuild inside the first one's arrival.

        THE OLD SCREEN STAYS ON THE GLASS UNTIL THE NEW ONE IS FINISHED
        (2026-09-22). His clip of 1.0.3: a switch painted a blank pane,
        then a half-built one, then the whole one, all while it slid,
        and the lit word in the bar moved first. So a picture of the
        pane is laid over it (widgets.PaintHold, a window of its own —
        its docstring says why it cannot be a widget), the new screen is
        built with the sheet off the window as before, put back and
        painted in full underneath the picture (_settle), and only then
        does the bar's word change and the new screen arrive — its own
        finished picture, sliding the same six frames the sheet used
        to. Measured on the hidden desktop with a sampler photographing
        the window every 8 ms: before, 1-7 distinct blank or half-built
        frames per change of place and the bar's word 16-80 ms ahead of
        the page; after, none, and the word in the same 8 ms as the page
        — the old screen, then the new one sliding in whole. The price
        is the paint moving in front of the reveal (AGENTS.md, the trap
        on paint holding, has the numbers).

        THE SHEET IS STILL OFF THE WINDOW while the old screen is torn
        down and the new one built. Built in the open, every
        `update_idletasks()` a builder needs for its arithmetic
        (_settle_page, _paint_doors, the scrollers) also PAINTED the
        half-built page — Home showed seven of those frames per switch
        on 2026-09-19. Unmapped, the same calls lay out and paint
        nothing, and Home's switch went from 0.34 s to 0.22 s of frozen
        window because the paints were most of it. The floor under that
        is Tk's own: one OS window per widget, 1-2 ms each on this PC to
        create — 92 of them on Keys.

        A window that is not on the screen (withdrawn for the dot, not
        mapped yet, GitHub's runner) gets no cover and switches the way
        it did before: the sheet unmapped for the build, then the slide.
        """
        if self._landing_up and name != "Landing":
            # Nothing but the landing until a sign-in: not a door on
            # Home, not a link in a note, not a stale `after`.
            return
        if self._switching:
            # A click or a poll that arrived while the last switch was
            # still being painted under its cover (_settle takes window
            # events): the newest wish, once that one is on the screen.
            self._show_next = (name, then)
            return
        self.screen = name
        self._stop_rows()
        held, _step = self._hold_for()
        self._switching = True
        try:
            self.sheet.place_forget()
            try:
                for child in self.sheet.winfo_children():
                    child.destroy()
                keep = {k: self.parts[k] for k in
                        ("hint", "lamp", "state", "uptime", "chip", "run",
                         "bar_screens", "stop_bar", "tests_stop")
                        if k in self.parts}
                self.parts = keep
                self._hide_toast()
                {"Home": self._screen_home,
                 "Corrections": self._screen_corrections,
                 "Said": self._screen_said,
                 "Keys": self._screen_keys,
                 "Settings": self._screen_settings,
                 "Network": self._screen_network,
                 "Landing": self._screen_landing}[name]()
                self._refresh(self.status or None)
                # The first screenful of Settings' cards, before the
                # reveal; the rest one per tick below the fold.
                self._settings_first_view()
                if then is not None:
                    then()
            except BaseException:
                # A builder that died must not leave a blank window behind,
                # nor a picture of the old one standing over a window that
                # no longer holds it: whatever it managed to draw goes back
                # on, in place, and the cover comes off.
                self._show_next = None
                self.sheet.place(x=0, y=0)
                self._paint_nav()
                if self._hold is not None:
                    self._hold.lift()
                raise
            if held:
                self._reveal()
            else:
                self._paint_nav()
                self._slide_in()
        finally:
            self._switching = False
        if self.closing:
            # The X was pressed while the new screen settled (_settle
            # takes window events): the window is gone, and so may be
            # everything this method would touch next.
            return
        # Even when it names the place that is up: a Corrections chip
        # pressed mid-switch changed _corr_tab and asked for Corrections.
        wish, self._show_next = self._show_next, None
        if wish is not None:
            self._show(*wish)

    #: The arrival: how far below its place the new screen is on each
    #: frame, 18 ms apart — a cubic ease-out baked into a table, because
    #: computing an easing curve for six integers is showing off.
    SLIDE = (16, 10, 6, 3, 1, 0)
    SLIDE_MS = 18
    #: How many rounds of window events and idle work _settle may take.
    #: Measured 2026-09-22 on the hidden desktop: on every screen one
    #: round had events to handle and the second found none — two
    #: rounds, 12-40 ms, Keys 82-105 ms (its 90-odd first maps).
    SETTLE_PASSES = 6

    def _settle(self) -> int:
        """Map and paint the new screen in full, under the cover.

        A packed or placed child is only mapped once its container is,
        and then at idle, one level at a time; each newly mapped window
        is an Expose event on Tk's queue, and a widget paints when its
        Expose is handled and the idle work after it runs. So: the idle
        work, then every WINDOW event that is waiting, and again, until
        a round finds none. Window events only — not the timers, so no
        poll, no breath and no `after` of the old screen runs in the
        middle of a switch; a click that lands here is a window event and
        runs, and if it asks for another place _show keeps it for after
        (`_switching`). Returns the rounds it took.

        The X is a window event too. Pressed here, it runs _close in the
        middle of the loop — the root destroyed, and a window no mainloop
        owns buried (_bury empties this object) — so the loop stops the
        moment `closing` is set and touches nothing after it, and every
        caller asks `closing` before going on. (No local holds the
        interpreter across the loop, either: one that did would keep a
        buried window's Tcl alive past _bury's collect, for some other
        thread's collector to free — the Tcl_AsyncDelete abort.)
        """
        rounds = 0
        for rounds in range(1, self.SETTLE_PASSES + 1):
            self.root.update_idletasks()
            handled = 0
            while handled < 5000 and self.root.tk.dooneevent(
                    _tkinter.WINDOW_EVENTS | _tkinter.DONT_WAIT):
                handled += 1
                if self.closing:
                    return rounds
            if not handled:
                break
        self.root.update_idletasks()
        return rounds

    def _reveal(self, step: int = 0) -> None:
        """The new screen, finished under the cover, arrives: the sheet
        back at its place, everything painted, and the cover showing the
        new screen's own picture as it slides up — then gone, with the
        same pixels underneath it. `step` is the frame to go on from when
        this finishes an arrival that a tab interrupted (_held).

        THE FIRST FRAME, AND THE BAR'S WORD WITH IT, IS THE LOOP'S NEXT
        TURN (`after(0)`), not this call's. Shown here, it was on the
        glass for whatever the same callback did next: _show and then
        _settings_go — the pile's recovery-key door did exactly that —
        held the place as built, 16 px low, for the ~85 ms the tab took
        to build, then snapped it up and swapped the tab in: Home, then
        General, then Privacy, when only the last was asked for (review
        of 2026-09-22). Deferred, the cover still shows the old screen
        when the next rebuild starts, and that one folds into this
        arrival (_hold_for). The word is SET here — `nav.selected` names
        the place the moment _show returns — and painted with the frame,
        so it cannot lead the page either."""
        try:
            self.sheet.place(x=0, y=0)
            self._settle()
            if self.closing:
                return
            taken = self._hold.take()
            self._paint_nav(paint=False)
        except BaseException:
            if not self.closing:
                self._paint_nav()
                self._hold.lift()
            raise
        if not taken:
            self._paint_nav()
            self._hold.lift()
            return
        self._arrival_next = step
        self._slide_after = self.root.after(0, lambda: self._arrive(step))

    def _arrive(self, step: int) -> None:
        """One frame of the arrival, on the cover. Nothing Tk draws: the
        real screen is finished and at its place underneath. The first
        frame brings the bar's word: painted before the photograph, the
        census caught one 8 ms sample of the new word over the old page."""
        self._slide_after = None
        self._arrival_next = None
        if self.closing:
            return
        hold = self._hold
        if not step:
            self.nav.paint()
            self.nav.update_idletasks()
        offset = self.SLIDE[step] if step < len(self.SLIDE) else 0
        if hold is None or not hold.up or not offset or not hold.show(offset):
            if hold is not None:
                hold.lift()
            return
        self._arrival_next = step + 1
        self._slide_after = self.root.after(
            self.SLIDE_MS, lambda: self._arrive(step + 1))

    def _cancel_slide(self) -> None:
        """The pending frame of the arrival or of the old slide, gone —
        and nothing else done about it (_end_slide finishes one)."""
        if self._slide_after is not None:
            try:
                self.root.after_cancel(self._slide_after)
            except Exception:
                pass
        self._slide_after = None
        self._arrival_next = None

    def _end_slide(self) -> None:
        """Whatever is still moving, finished NOW. The old slide ends
        where it belongs, at y 0: cancelled mid-way, the sheet stayed
        16 px low for as long as the screen was up (the review of
        2026-09-22 caught it on the path a window with no cover takes, a
        Settings tab asked for inside the slide). An arrival with no
        cover left to show it paints the bar's word it was carrying."""
        pending, step = self._slide_after, self._arrival_next
        self._cancel_slide()
        if pending is None:
            return
        if step is None:
            self.sheet.place(x=0, y=0)
            return
        if not step:
            self.nav.paint()
        if self._hold is not None:
            self._hold.lift()

    def _hold_for(self) -> tuple[bool, int | None]:
        """Cover the pane for a switch or an in-place rebuild. Returns
        (covered, the frame of an arrival this interrupts, or None).

        MID-ARRIVAL THE COVER STAYS AS IT IS. It is up, and it shows
        exactly what is on the glass: the old screen while the first
        frame is still to come, or the arriving one a few pixels low.
        Photographing the pane there — what this did until the review of
        2026-09-22 — laid the FINISHED new screen over it at y 0: a jump
        up, and, for a rebuild asked for in the same callback as the
        switch, a picture of a place or a tab the person had not asked
        for. So the pending frame is cancelled, nothing is photographed,
        and the caller rebuilds under what is already there and goes on
        with the arrival from its picture (_reveal). Otherwise whatever
        is pending is finished (the old slide at y 0) and the pane is
        photographed as it stands."""
        hold, step = self._hold, self._arrival_next
        if step is not None and hold is not None and hold.up:
            self._cancel_slide()
            return True, step
        self._end_slide()
        return (hold.cover() if hold is not None else False), None

    def _held(self, rebuild) -> None:
        """An in-place rebuild of part of a screen — a Settings tab, the
        search opening or closing — under the same cover, lifted once
        everything it drew is painted. No slide: the place did not
        change. Asked for while a place is still arriving, it is part of
        that arrival: built under the cover as it stands, and the
        arrival goes on with the finished picture (_hold_for)."""
        if self._switching:
            rebuild()
            return
        held, step = self._hold_for()
        self._switching = True
        try:
            try:
                rebuild()
                self._settings_first_view()
            except BaseException:
                if not self.closing:
                    self._paint_nav()
                    if held:
                        self._hold.lift()
                raise
            if step is not None:
                self._reveal(step)
            elif held:
                self._settle()
                if not self.closing:
                    self._hold.lift()
        finally:
            self._switching = False
        if self.closing:
            return
        wish, self._show_next = self._show_next, None
        if wish is not None:
            self._show(*wish)

    def _slide_in(self, step: int = 0) -> None:
        """The new screen eases up into place — six frames, ~100 ms.

        Movement, not decoration: the slide is what says "this is a new
        page" when the palette is identical from screen to screen. The
        offsets are a cubic ease-out baked into a table, because computing
        an easing curve for six integers is showing off.
        """
        if self.closing:
            # No animation while the window is going away — but the sheet
            # still has to END where it belongs. Stopping mid-slide left
            # it 10 to 16 px low, which nobody sees in a window that is
            # closing and which was in EVERY screenshot taken of one:
            # the last line of the Keys place looked clipped by the
            # window's edge for a week, and it was this.
            self.sheet.place(x=0, y=0)
            self._slide_after = None
            return
        offsets = (16, 10, 6, 3, 1, 0)
        self.sheet.place(x=0, y=offsets[step])
        if step + 1 < len(offsets):
            self._slide_after = self.root.after(
                18, lambda: self._slide_in(step + 1))
        else:
            self._slide_after = None

    def _title(self, text: str, right: str = "") -> None:
        tk.Label(self.sheet, text=text, bg=ui.BG, fg=ui.FG,
                 font=(ui.DISPLAY, 17, "bold")).place(x=PAD, y=20)
        if right:
            tk.Label(self.sheet, text=right, bg=ui.BG, fg=ui.FAINT,
                     font=(ui.UI, 9)).place(x=PAD + CW, y=28, anchor="ne")

    # -------------------------------------------------------------- toast

    def _note(self, text: str) -> None:
        """Say one thing, at the bottom, and take it away again.

        The old window had a permanent line for this in the "last" card,
        which meant a message from twenty minutes ago sitting there
        looking current. A note is about something that just happened, so
        it behaves like one.
        """
        if not text or text == self._toast_text:
            return
        self._toast_text = text
        if self._toast_after is not None:
            try:
                self.root.after_cancel(self._toast_after)
            except Exception:
                pass
        if self._toast is not None:
            self._toast.destroy()
        wrapped, lines = ui.clamp(text, ui.UI, 9, CW - 60, 2)
        card = ui.Card(self.pane, CW, 30 + lines * 18, radius=12,
                       bg=ui.BG, fill=ui.QUOTE_BG, border=ui.QUOTE_EDGE,
                       pad=12)
        tk.Label(card.body, text=wrapped, bg=ui.QUOTE_BG, fg=ui.FG,
                 font=(ui.UI, 9), justify="left", anchor="w").place(x=0, y=0)
        self._toast = card
        self._toast_slide(card, 0)
        self._toast_after = self.root.after(9000, self._hide_toast)

    def _toast_slide(self, card, step: int) -> None:
        """Up from under the window edge, the same six-frame ease the
        screens use — so a note ARRIVES rather than pops. The identity
        check comes BEFORE the place(): a screen swap destroys the toast,
        and one frame of this was still in flight when it did."""
        if self.closing or card is not self._toast:
            return
        offsets = (44, 26, 14, 6, 2, 0)
        card.place(x=PAD, y=H - TOP - 16 + offsets[step], anchor="sw")
        if step + 1 < len(offsets):
            self.root.after(18, lambda: self._toast_slide(card, step + 1))

    def _hide_toast(self) -> None:
        self._toast_after = None
        self._toast_text = ""
        if self._toast is not None:
            try:
                self._toast.destroy()
            except Exception:
                pass
            self._toast = None

    # ------------------------------------------------------------ waiting

    def _screen_home(self) -> None:
        """A summary, and nothing that needs scrolling.

        THE OWNER'S FOURTH ANSWER, and the shortest. The first rebuild put
        six panels here and he said "too overwhelming"; the second split
        it in two places and he said they should be one desk; the third
        put the whole desk on one scrolling page and he read it and said
        "Home should be a summary… to get more information, I don't need
        everything on my home screen". So this place answers three
        questions and stops: what wants me, what else is waiting and
        where, and what happened today. Everything it names is a place.

        ONE GOLD BUTTON PER SURFACE. Only Yes on a second reading is the
        lamp; every other button here is quiet.
        """
        p = self.parts
        self._row_w = CW
        p["waiting_head"] = tk.Label(self.sheet, text="", bg=ui.BG,
                                     fg=ui.FG, font=(ui.DISPLAY, 21, "bold"))
        p["waiting_head"].place(x=PAD, y=24)
        p["waiting_sub"] = tk.Label(self.sheet, text="", bg=ui.BG,
                                    fg=ui.DIM, font=(ui.UI, 10))
        p["waiting_sub"].place(x=PAD + 2, y=64)

        # Dismiss all, and the key that does the same thing without this
        # window being open. Placed and unplaced by _fill_waiting: a
        # button for a column that is not there is a dead control.
        p["dismiss_all"] = tk.Label(self.sheet, text="Dismiss all", bg=ui.BG,
                                    fg=ui.DIM, font=(ui.UI, 10),
                                    cursor="hand2")
        p["dismiss_all"].bind("<Button-1>",
                              lambda _e: self._notify("dismiss"))
        p["dismiss_all"].bind("<Enter>",
                              lambda _e: p["dismiss_all"].config(fg=ui.FG))
        p["dismiss_all"].bind("<Leave>",
                              lambda _e: p["dismiss_all"].config(fg=ui.DIM))
        p["dismiss_key"] = ui.KeyCap(self.sheet, "Ctrl+Alt+M", bg=ui.BG,
                                     w=96, h=26)

        # Reporting a problem is noticed while looking at the thing that
        # is wrong, so the button is here, and it says its key —
        # all five reports in ten days were filed from the key.
        if self._problems_on:
            p["report_button"] = ui.Button(
                self.sheet, "Report a problem", self._report, h=30,
                w=widgets.button_width("Report a problem", icon=True),
                bg=ui.BG, quiet=True, icon=ui.ICON["error"])
            p["report_button"].place(x=PAD + CW, y=20, anchor="ne")

        # THE PAGE. A summary fits without scrolling — the fullest it
        # ever gets is three rows of pile, the band of doors at its
        # smallest and the day's three lines, and _settle_page sizes the
        # band so that comes to exactly the 502 px the page has — but it
        # is in a Scroller all the same, so a row that grows (a second
        # reading with two changes, a long report) is reachable rather
        # than clipped.
        page = ui.Scroller(self.sheet, CW + 10, PAGE_H, bg=ui.BG)
        page.place(x=PAD, y=PILE_Y)
        p["page"] = page

        p["pile_card"] = ui.Card(page.inner, CW, 60, fill=ui.CARD, bg=ui.BG,
                                 pad=14)
        p["pile_list"] = _Column(p["pile_card"].body, page)
        p["held_line"] = tk.Label(page.inner, text="", bg=ui.BG,
                                  fg=ui.FAINT, font=(ui.UI, 9),
                                  justify="left", anchor="w")

        # WHERE EVERYTHING IS. The band of doors, under the pile because
        # the pile is what the headline is about and this is the answer
        # to "and what else". Always drawn and always the full width —
        # see the note over DOOR_MIN_H for why that is the whole point.
        p["elsewhere"] = tk.Frame(page.inner, bg=ui.BG, width=CW,
                                  height=DOOR_MIN_H)
        p["elsewhere"].pack(anchor="w")
        p["elsewhere"].pack_propagate(False)

        # The ground between the band and the day. A widget and not a
        # pady, because its height is COMPUTED: whatever the page has
        # left over goes in here, which is what lands the day's three
        # lines on the footer rule instead of leaving the rule with
        # nothing above it. _settle_page owns it.
        p["ground"] = tk.Frame(page.inner, bg=ui.BG, width=CW,
                               height=DOOR_GAP)
        p["ground"].pack(anchor="w")
        p["ground"].pack_propagate(False)

        p["rest_eyebrow"] = tk.Label(
            page.inner, text="T H E   R E S T   O F   T H E   D A Y"
                             "   ·   O N E   L I N E   E A C H",
            bg=ui.BG, fg=ui.FAINT, font=(ui.MEDIUM, 8))
        p["rest_eyebrow"].pack(anchor="w", padx=2, pady=(0, 6))
        p["rest"] = tk.Frame(page.inner, bg=ui.BG, width=CW, height=132)
        p["rest"].pack(anchor="w")
        p["rest"].pack_propagate(False)
        page.bind_wheel(page.inner)

        # The bottom strip: four facts that are true whichever place is
        # open, under a rule, so they read as a footer and not as a fifth
        # thing to do. Fixed under the page, never scrolled away.
        widgets.rule(self.sheet, CW, bg=ui.BG, colour=ui.RULE, x=PAD,
                     y=H - TOP - 54)
        widgets.icon(self.sheet, "awake", bg=ui.BG, colour=ui.FAINT,
                     size=13).place(x=PAD + 2, y=H - TOP - 40)
        p["strip_awake"] = tk.Label(self.sheet, text="", bg=ui.BG, fg=ui.DIM,
                                    font=(ui.UI, 10), anchor="w")
        p["strip_awake"].place(x=PAD + 26, y=H - TOP - 39)
        p["strip_facts"] = tk.Label(self.sheet, text="", bg=ui.BG,
                                    fg=ui.FAINT, font=(ui.UI, 9), anchor="e")
        p["strip_facts"].place(x=PAD + CW - 100, y=H - TOP - 38,
                               anchor="ne")

        self._pile_stamp = None
        self._waiting_view = "home"
        self._fill_waiting()

    def _make_door(self, tile, place: str) -> None:
        """Turn a tile into the door to a place: all of it clicks, all of
        it lights, and everything drawn on it does what the tile does.

        The home is made of these — a count is only useful if the thing
        it counts can be reached. It is the WHOLE tile and not the word
        on it because a 212 px card with one live line somewhere in the
        middle of it is a card that looks pressable and mostly is not;
        and it is every child as well as the card, because a Label drawn
        over a Canvas takes the click that was meant for the Canvas.
        """
        def everything(widget):
            yield widget
            for child in widget.winfo_children():
                yield from everything(child)

        def paint(fill: str):
            def done(_event=None):
                if not tile.winfo_exists():
                    return
                # tile.fill and not a private: Card.resize() repaints
                # from it, so the band growing under the pointer keeps
                # the colour the pointer put there.
                tile.fill = fill
                tile.face(ui.rounded(tile.w, tile.h, 14, fill, ui.BG,
                                     ui.LINE))
                for widget in everything(tile.body):
                    try:
                        widget.configure(bg=fill)
                    except tk.TclError:
                        pass              # an icon, a rule, anything
            return done

        for widget in everything(tile):
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", lambda _e: self._show(place))
            widget.bind("<Enter>", paint(ui.CHIP_HOVER))
            widget.bind("<Leave>", paint(ui.CARD))

    def _screen_said(self) -> None:
        """transcripts.log read back: the search, the six filters, and the
        rows — twenty-five at a time.

        "All the last few, I want them so it's not like a lot of them. I
        want you to make a Show more option so it doesn't show all of
        them because it's a lot to scroll and it's a nightmare."
        (2026-09-07.) So the list opens on SAID_PAGE rows and grows by
        that much per press, rather than putting a hundred rows in front
        of him and asking him to find the one he wants.
        """
        self._title("Said", f"the last {HISTORY_ROWS} of what you said")
        p = self.parts
        self._row_w = SAID_W
        self._said_shown = SAID_PAGE
        # 46 and not 40: a 9 pt line in Rubik has a 25 px box (measured
        # 2026-09-07) and this card's body was 18, so the placeholder and
        # the caret both lost their descenders behind the card's own edge.
        search = ui.Card(self.sheet, SAID_W, FIELD_H, radius=11, pad=11,
                         bg=ui.BG)
        search.place(x=PAD, y=64)
        tk.Label(search.body, text=ui.ICON["search"], bg=ui.CARD,
                 fg=ui.FAINT, font=(ui.ICONS, 10)).place(x=0, y=2)
        entry = tk.Entry(search.body, bg=ui.CARD, fg=ui.FG, bd=0,
                         highlightthickness=0, font=(ui.UI, 10),
                         insertbackground=ui.ACCENT)
        entry.place(x=26, y=0, width=SAID_W - 90, height=FIELD_H - 22)
        entry.insert(0, self._query)
        entry.bind("<KeyRelease>", lambda _e: self._search_soon(entry.get()))
        p["search"] = entry
        p["placeholder"] = tk.Label(search.body,
                                    text="Search everything you have said…",
                                    bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 9))
        if not self._query:
            p["placeholder"].place(x=26, y=0)
        entry.bind("<FocusIn>", lambda _e: p["placeholder"].place_forget())

        chips = tk.Frame(self.sheet, bg=ui.BG)
        chips.place(x=PAD, y=118)
        p["chips"] = {}
        for name, kind in history.FILTERS:
            chip = ui.Chip(chips, name, lambda k=kind: self._filter_to(k),
                           active=(kind == self._filter), bg=ui.BG)
            chip.pack(side="left", padx=(0, 6))
            p["chips"][kind] = chip

        page = ui.Scroller(self.sheet, SAID_W + 10, 442, bg=ui.BG)
        page.place(x=PAD, y=160)
        p["page"] = page
        rows = tk.Frame(page.inner, bg=ui.BG)
        rows.pack(anchor="w")
        p["list"] = _Column(rows, page)
        p["empty"] = tk.Label(page.inner, text="", bg=ui.BG, fg=ui.FAINT,
                              font=(ui.UI, 10))
        p["more"] = tk.Label(page.inner, text="", bg=ui.BG,
                             fg=ui.ACCENT_TEXT, font=(ui.UI, 10),
                             cursor="hand2")
        p["more"].bind("<Button-1>", lambda _e: self._said_more())

        tk.Label(self.sheet, text="Everything older is still in "
                                 "transcripts.log, untouched.",
                 bg=ui.BG, fg=ui.FAINT, font=(ui.UI, 8)).place(x=PAD, y=624)
        wide = widgets.button_width("Open transcripts.log", icon=True)
        ui.Button(self.sheet, "Open transcripts.log",
                  lambda: launch.open_path(history.LOG), w=wide, h=30,
                  quiet=True, bg=ui.BG,
                  icon=ui.ICON["file"]).place(x=PAD + SAID_W - wide, y=616)

        self._vocab_panel()
        self._fill_history()

    def _said_more(self) -> None:
        """Another SAID_PAGE rows, drawn under the ones already there."""
        self._said_shown = getattr(self, "_said_shown", SAID_PAGE) + SAID_PAGE
        self._fill_history(keep_place=True)

    def _paint_bar_buttons(self) -> None:
        """The right end of the bar — the state, and the buttons the state
        allows.

        HIS RULE, and it is the whole of this method (2026-09-07): "when
        the model is off, only one button — Start. And when the model is
        on, two buttons — Pause and Stop... And Pause and Stop should not
        appear when the model is already off." So there is ONE question
        here — is there an app there at all — and every button in the bar
        answers it together. Screens off used to answer a second question
        of its own (it appeared only once the models had finished
        loading, about 25 seconds after the other two), which is a third
        button coming and going on its own schedule in a bar he had just
        told us was saying too much.

        "Is there an app there" is `self.status`, not `self.running`: the
        control channel answers "starting" from its first second, and
        through those 25 seconds Stop is exactly the button somebody
        wants. Pause and Screens off are there too and the app refuses
        them out loud — "still starting up, try again in a moment" — the
        way it always has.

        THE SAFETY IS THE LAYOUT NOW, not a second press. Stopping
        unloads the models and starting again costs him about 25 seconds,
        and there is no undo, which is why Stop used to arm itself: the
        first press only turned the word into "Stop again" and the second
        one quit. He read that word, did not know what it was for, and
        asked twice to have it gone. Three things replace it, and none of
        them is a confirmation:

        - Pause keeps the right edge of the bar in EVERY state. Start,
          Resume and Pause are one button and one place, so the key he
          presses all day never moves under his hand — and Stop never
          appears where his finger already was.
        - Stop is at the far end of the group, with the whole Screens off
          button and BAR_KEEP of empty bar between them: 168 px from
          Pause, where it used to be 8.
        - Stop is not there at all while there is nothing to stop.

        STOP TESTS USED TO BE HERE — in the bar for exactly as long
        as a nightly run had something to stop, with the uptime
        stepping aside for its 108 px. It left with the rest of the
        owner's surface on 2026-10-01 (MASTER.md §8), so the chip
        keeps its meta in every state and three buttons is the most.
        """
        chip = self.parts.get("chip")
        run = self.parts.get("run")
        stop = self.parts.get("stop_bar")
        screens = self.parts.get("bar_screens")
        if not all(w is not None and w.winfo_exists()
                   for w in (chip, run, stop, screens)):
            return
        # ONE BUTTON, THREE WORDS. Start, Resume and Pause are never
        # available at the same moment, so three buttons would be two
        # lies — and it is the same key in the same pixels either way.
        model = self.status.get("model") or "on"
        run.configure_text("Start" if not self.status or model == "off" else
                           "Loading…" if model in ("loading", "unloading") else
                           "Resume" if self.status.get("paused")
                           else "Pause")
        # `awake` only ever comes back from a running app, so the word is
        # "Screens off" through a startup whatever the screens are doing.
        awake = (self.status.get("awake") or {}) if self.running else {}
        screens.configure_text("Screens on" if awake.get("dark")
                               else "Screens off")
        # Right to left off the window's edge, so that a longer state word
        # grows into empty bar instead of pushing a button off the screen.
        x = W - PAD
        run.place(x=x, y=12, anchor="ne")
        x -= BAR_RUN_W + BAR_GAP
        # HIS RULE AGAIN with the model off and the process up: one
        # button, Start. Stop has nothing left to unload, and Screens off
        # goes with it so the bar reads the same way it does with nothing
        # running — the key still works, and Settings > General has it.
        if self.status and model not in ("off", "unloading"):
            screens.place(x=x, y=12, anchor="ne")
            x -= self._screens_w + BAR_KEEP
            stop.place(x=x, y=12, anchor="ne")
            x -= BAR_STOP_W + BAR_GAP
        else:
            screens.place_forget()
            stop.place_forget()
        chip.show_meta(True)
        chip.place(x=x, y=TOP // 2, anchor="e")

    def _screen_corrections(self) -> None:
        """What it has learned, what the second reading proposes, and
        what he reads to it.

        His words, 2026-09-07: "all the corrections and stuff, I would
        like them to be in tabs… and something with the vocabulary and
        all the corrections it does automatically". And 2026-09-21,
        after seeing another app's dictionary page: the whole list, a
        search, a switch, a way to add a pair by hand, and the proposals
        pushed to the top of the same list rather than beside it.

        The proposal rows are the pile's rows, with the pile's two
        answers, so a correction reads the same here as it does on the
        home. The learned rows are drawn straight onto a canvas each —
        the way the Said list draws its pills — because a list of forty
        Canvases is fine and a list of forty Frames of Canvases is not.
        """
        self._title("Corrections", "the words it learned, and what the "
                                   "second reading proposes")
        p = self.parts
        self._row_w = CW
        # ONE TAB IS NO TABS. The strip is drawn only while there is
        # something to choose between: with Read aloud gone (2026-10-01,
        # MASTER.md §8) a lone "Words" chip over a list of words is a
        # control that chooses nothing — it was the first thing visible
        # in the photograph of the place that evening. corr_tabs() is
        # still the table, so a second tab brings the strip back.
        p["corr_chips"] = {}
        if len(corr_tabs()) > 1:
            chips = tk.Frame(self.sheet, bg=ui.BG)
            chips.place(x=PAD, y=CORR_CHIPS_Y)
            for key, name in corr_tabs():
                chip = ui.Chip(chips, name,
                               lambda k=key: self._corr_tab_to(k),
                               active=(key == self._corr_tab), bg=ui.BG)
                chip.pack(side="left", padx=(0, 6))
                p["corr_chips"][key] = chip
        self._words_editing = None

        # the tools, right of the chips: search · Use them · Teach a word
        tools = tk.Frame(self.sheet, bg=ui.BG)
        tools.place(x=PAD + CW, y=CORR_CHIPS_Y, anchor="ne")
        p["words_tools"] = tools
        p["words_teach"] = None
        self._words_teach_button(lit=False)
        use = tk.Frame(tools, bg=ui.BG)
        use.pack(side="right", padx=(0, 18))
        p["words_use"] = ui.Switch(use, self._words_enabled(),
                                   command=self._words_use, bg=ui.BG)
        p["words_use"].pack(side="left")
        tk.Label(use, text="Use them", bg=ui.BG, fg=ui.DIM,
                 font=(ui.UI, 10)).pack(side="left", padx=(8, 0))
        box = ui.Field(tools, self._words_query, w=260, h=36, radius=11,
                       bg=ui.BG, justify="left", icon=ui.ICON["search"],
                       pad=12, pt=10, placeholder="find a word")
        box.pack(side="right", padx=(0, 18))
        box.bind_entry("<KeyRelease>",
                       lambda _e: self._words_search_soon(box.get()))
        box.bind_entry("<Escape>", lambda _e: (box.set(""),
                                               self._words_search("")))
        p["words_search"] = box

        p["corr_head"] = tk.Label(self.sheet, text="", bg=ui.BG, fg=ui.DIM,
                                  font=(ui.UI, 10))
        p["corr_head"].place(x=PAD, y=CORR_HEAD_Y)
        page = ui.Scroller(self.sheet, CW + 10, H - TOP - CORR_PAGE_Y - 44,
                           bg=ui.BG)
        page.place(x=PAD, y=CORR_PAGE_Y)
        p["page"] = page
        p["corr_list"] = _Column(page.inner, page)
        p["corr_empty"] = tk.Label(self.sheet, text="", bg=ui.BG,
                                   fg=ui.FAINT, font=(ui.UI, 10),
                                   wraplength=CW - 40, justify="left")

        # the foot: the teach key, and how the words are used
        keys = self.status.get("keys") or self._read_keys()
        teach = pretty_key(keys.get("correct_hotkey", ""))
        foot = tk.Frame(self.sheet, bg=ui.BG)
        foot.place(x=PAD, y=H - TOP - 30, anchor="w")
        if teach:
            ui.KeyCap(foot, teach, bg=ui.BG,
                      w=max(56, 26 + ui.text_width(teach, ui.UI, 10)),
                      h=26).pack(side="left")
        try:
            cap = config_mod.load_layered().vocab.max_terms
        except Exception:                 # noqa: BLE001 — unreadable config
            cap = None
        p["vocab_hot"] = tk.Label(
            foot, bg=ui.BG, fg=ui.FAINT, font=(ui.UI, 8),
            text=("teaches it a word from what it just wrote  ·  " if teach
                  else "")
            + ("the best of them go into the decoder's prompt before it "
               f"listens — {cap} at a time" if cap else
               "the best of them go into the decoder's prompt before it "
               "listens")
            + "  ·  a word corrected twice is fixed on every dictation")
        p["vocab_hot"].pack(side="left", padx=(10 if teach else 0, 0))
        self._corr_stamp = None
        self._fill_corrections()

    def _corr_tab_to(self, key: str) -> None:
        if key == self._corr_tab:
            return
        self._corr_tab = key
        self._show("Corrections")

    def _poll_corrections(self) -> None:
        """Once a second from _refresh, and only two stat()s unless a
        file moved — a verdict given at a card, a word learned from a
        correction, or another PC's word arriving through the account
        are the usual reasons one did."""
        if "corr_list" not in self.parts:
            return
        if self._words_editing is not None:
            return          # never rebuild the list under his typing
        if self._corr_stat() != getattr(self, "_corr_stamp", None):
            self._fill_corrections()

    def _corr_stat(self):
        return (self._review_stat(), self._vocab_stat())

    @staticmethod
    def _vocab_stat():
        try:
            st = os.stat(paths.VOCAB_FILE)
            return (st.st_size, st.st_mtime_ns)
        except OSError:
            return None

    def _fill_corrections(self) -> None:
        """The Words tab's one column: the proposals that wait, then the
        editor if one is open, then every learned pair that matches the
        search — newest first."""
        if "corr_list" not in self.parts:
            return
        self._corr_stamp = self._corr_stat()
        p = self.parts
        # ONE GOLD BUTTON PER SURFACE, the same rule the pile keeps: four
        # lit Yes buttons down a list are four primary actions, which is
        # none. Only the newest is the lamp; every later Yes answers the
        # same way, quietly. Teach a word is gold too, so while a proposal
        # waits the button steps down — the proposal is the thing to
        # answer.
        items = self._waiting_review()
        lit = False
        for row in items:
            buttons = []
            for label, tone, act in row.get("buttons", ()):
                if tone == "gold":
                    tone = "quiet" if lit else "gold"
                    lit = True
                buttons.append((label, tone, act))
            row["buttons"] = buttons
        self._words_teach_button(lit=lit)
        entries, hot = self._words_entries()
        query = self._words_query.strip().lower()
        shown = [c for c in entries
                 if not query or query in c["heard"].lower()
                 or query in c["meant"].lower()]
        try:
            ready_at = config_mod.load_layered().vocab.replace_after_hits
        except Exception:                 # noqa: BLE001 — unreadable config
            ready_at = 2
        ready = sum(1 for c in entries if int(c.get("hits", 1)) >= ready_at)
        if query:
            head = (f"{len(shown)} of {len(entries)} word"
                    f"{'' if len(entries) == 1 else 's'} match "
                    f"\u201c{self._words_query.strip()}\u201d")
        elif entries:
            head = (f"{len(entries)} word{'' if len(entries) == 1 else 's'} "
                    f"it has learned to hear your way  ·  {len(hot)} in the "
                    f"decoder's prompt  ·  {ready} fixed on every dictation")
        else:
            head = "Nothing learned yet."
        p["corr_head"].config(text=head)

        column = p["corr_list"]
        column.clear()
        p["corr_empty"].place_forget()
        p["word_rows"] = {}
        for gone in ("words_heard", "words_meant", "words_save"):
            p.pop(gone, None)             # the editor, if one was up

        def eyebrow(text: str) -> None:
            lab = tk.Label(column.inner, text=text, bg=ui.BG, fg=ui.FAINT,
                           font=(ui.MEDIUM, 8))
            lab.pack(anchor="w", pady=(4, 8))
            column.bind_wheel(lab)

        if items:
            eyebrow(f"W A I T I N G   O N   Y O U  \u00b7  {len(items)}")
            for spec in items:
                card = ui.Card(column.inner, CW, PILE_ROW_H + 20,
                               fill=ui.CARD, bg=ui.BG, pad=10)
                card.pack(anchor="w", pady=(0, 8))
                row = widgets.PileRow(
                    card.body, CW - 20, bg=ui.CARD,
                    mark=spec.get("mark", ""),
                    mark_colour=spec.get("mark_colour"),
                    eyebrow=spec.get("eyebrow", ""),
                    eyebrow_right=spec.get("eyebrow_right", True),
                    text=spec.get("text", ""), runs=spec.get("runs"),
                    note=spec.get("note", ""),
                    buttons=spec.get("buttons", ()),
                    height=PILE_ROW_H)
                row.pack(fill="x")
                column.bind_wheel(card)
                column.bind_wheel(row)
                column.bind_wheel(row.canvas)
            line = widgets.rule(column.inner, CW - 10, bg=ui.BG,
                                colour=ui.LINE)
            line.pack(fill="x", pady=(6, 12))
            column.bind_wheel(line)

        eyebrow("L E A R N E D")
        if self._words_editing == "":
            self._words_editor(column, None)
        elif self._words_editing and not any(
                c["heard"].lower() == self._words_editing.lower() for c in shown):
            # the row he is editing is not in the search's answer (or is
            # gone from the file): the editor stays, at the top
            held = next((c for c in entries if c["heard"].lower()
                         == self._words_editing.lower()), None)
            if held is not None:
                self._words_editor(column, held)
            else:
                self._words_editing = None
        if not entries:
            p["corr_empty"].config(
                text="Say Yes to a second reading, press the teach key on a "
                     "word it got wrong, or teach it one here — the pairs "
                     "it learns are listed here, newest first.")
            p["corr_empty"].place(x=PAD, y=CORR_PAGE_Y + (
                (len(items) * (PILE_ROW_H + 28) + 56) if items else 0) + 40)
        elif not shown:
            p["corr_empty"].config(
                text=f"No learned word has \u201c{self._words_query.strip()}"
                     "\u201d in it.")
            p["corr_empty"].place(x=PAD, y=CORR_PAGE_Y + (
                (len(items) * (PILE_ROW_H + 28) + 56) if items else 0) + 40)
        for entry in shown:
            if (self._words_editing and self._words_editing.lower()
                    == entry["heard"].lower()):
                self._words_editor(column, entry)
                continue
            self._word_row(column, entry, hot, ready_at)

    # ------------------------------------------------------ the Words list

    def _words_teach_button(self, lit: bool) -> None:
        """[+ Teach a word], gold while nothing waits — the one primary
        action on the page — and quiet while a proposal holds the gold.
        Rebuilt only when that flips: a ui.Button bakes its faces."""
        p = self.parts
        tools = p.get("words_tools")
        if tools is None:
            return
        old = p.get("words_teach")
        if old is not None and getattr(old, "_lit", None) == (not lit):
            return
        if old is not None:
            old.destroy()
        wide = widgets.button_width("Teach a word", icon=True)
        if lit:
            button = ui.Button(tools, "Teach a word",
                               lambda: self._words_edit(""), w=wide, h=36,
                               quiet=True, bg=ui.BG, icon="")
        else:
            button = widgets.gold_button(tools, "Teach a word",
                                         lambda: self._words_edit(""),
                                         w=wide, h=36, bg=ui.BG,
                                         icon="")
        button._lit = not lit
        # first in the pack list = the rightmost of the side="right" row
        packed = [c for c in tools.winfo_children()
                  if c is not button and c.winfo_manager() == "pack"]
        if packed:
            button.pack(side="right", before=packed[0])
        else:
            button.pack(side="right")
        p["words_teach"] = button

    @staticmethod
    def _words_enabled() -> bool:
        try:
            return bool(config_mod.load_layered().vocab.enabled)
        except Exception:                 # noqa: BLE001 — unreadable config
            return True

    def _words_entries(self) -> tuple[list, set]:
        """Every learned pair, newest first, and the lowercased meant forms
        that are in the decoder's prompt right now — ranked the way the
        app ranks them (the same Vocab, the same config), off the file,
        which is the record."""
        import vocab as vocab_mod
        try:
            vcfg = config_mod.load_layered().vocab
            v = vocab_mod.Vocab(
                paths.VOCAB_FILE, seed_terms=vcfg.terms,
                max_terms=vcfg.max_terms,
                replace_after_hits=vcfg.replace_after_hits,
                hebrew_after_hits=getattr(vcfg, "hebrew_after_hits", 3))
        except Exception:                 # noqa: BLE001 — unreadable config
            v = vocab_mod.Vocab(paths.VOCAB_FILE)
        entries = [c for c in v.corrections
                   if str(c.get("heard") or "").strip()
                   and str(c.get("meant") or "").strip()]
        entries.sort(key=lambda c: str(c.get("last") or ""), reverse=True)
        try:
            hot = {t.lower() for t in v.terms()}
        except Exception:                 # noqa: BLE001
            hot = set()
        return entries, hot

    @staticmethod
    def _word_meta(entry: dict, ready_at: int) -> str:
        """One plain line about a pair: how it is used, and when it was
        last taught. No counters a person has to decode."""
        hits = int(entry.get("hits", 1) or 0)
        if hits >= ready_at:
            state = f"fixed on every dictation  \u00b7  \u00d7{hits}"
        elif hits >= 1:
            state = ("corrected once \u2014 fixed after the "
                     f"{'second' if ready_at == 2 else _count_word(ready_at).lower() + 'th'} time")
        else:
            state = "its own guess"
        when = ago(str(entry.get("last") or "").replace(" ", "T", 1))
        return state + (f"  \u00b7  {when}" if when else "")

    def _word_row(self, column, entry: dict, hot: set, ready_at: int) -> None:
        """One learned pair: the pair pill, the meta line, the prompt
        mark, and — under the pointer — the pencil and the cross."""
        p = self.parts
        heard, meant = entry["heard"], entry["meant"]
        row = tk.Canvas(column.inner, width=CW, height=WORD_ROW_H, bg=ui.BG,
                        highlightthickness=0, bd=0)
        row.pack(anchor="w")
        column.bind_wheel(row)
        pw, ph = ui.pair_size(heard, meant)
        ui.pair_pill(row, pw, (WORD_ROW_H - ph) // 2, heard, meant, ui.BG)
        row.create_text(pw + 16, WORD_ROW_H / 2, anchor="w",
                        text=self._word_meta(entry, ready_at), fill=ui.FAINT,
                        font=(ui.UI, 9), tags="meta")
        if meant.strip().lower() in hot:
            row.create_oval(CW - 210, WORD_ROW_H / 2 - 3, CW - 204,
                            WORD_ROW_H / 2 + 3, fill=ui.ACCENT, width=0,
                            tags="hot")
            row.create_text(CW - 196, WORD_ROW_H / 2, anchor="w",
                            text="in the prompt", fill=ui.DIM,
                            font=(ui.UI, 9), tags="hot")
        pen = row.create_text(CW - 56, WORD_ROW_H / 2, text="\ue70f",
                              fill=ui.BG, font=(ui.ICONS, 11), tags="pen")
        cross = row.create_text(CW - 22, WORD_ROW_H / 2, text="\ue74d",
                                fill=ui.BG, font=(ui.ICONS, 11), tags="cross")
        # the pointer lights the two, and the two act
        row.bind("<Enter>", lambda _e, r=row: (
            r.itemconfig("pen", fill=ui.DIM), r.itemconfig("cross", fill=ui.DIM)))
        row.bind("<Leave>", lambda _e, r=row: (
            r.itemconfig("pen", fill=ui.BG), r.itemconfig("cross", fill=ui.BG)))
        for tag, colour in (("pen", ui.FG), ("cross", ui.RED)):
            row.tag_bind(tag, "<Enter>",
                         lambda _e, r=row, t=tag, c=colour: r.itemconfig(t, fill=c))
            row.tag_bind(tag, "<Leave>",
                         lambda _e, r=row, t=tag: r.itemconfig(t, fill=ui.DIM))
        row.tag_bind("pen", "<Button-1>",
                     lambda _e, h=heard: self._words_edit(h))
        row.tag_bind("cross", "<Button-1>",
                     lambda _e, h=heard: self._words_forget(h))
        for item in (pen, cross):
            row.tag_bind(item, "<Enter>", lambda _e, r=row: r.config(cursor="hand2"), add="+")
            row.tag_bind(item, "<Leave>", lambda _e, r=row: r.config(cursor=""), add="+")
        line = widgets.rule(column.inner, CW - 10, bg=ui.BG, colour=ui.RULE)
        line.pack(fill="x")
        column.bind_wheel(line)
        p["word_rows"][heard] = row

    def _words_editor(self, column, entry: dict | None) -> None:
        """The card a pair is typed on — in the list, where the row is
        (or at its top for a new one): what it hears, an arrow, what you
        mean, Save and Cancel. Enter saves, Escape cancels."""
        p = self.parts
        card = ui.Card(column.inner, CW, WORD_EDIT_H, fill=ui.CARD, bg=ui.BG,
                       pad=12)
        card.pack(anchor="w", pady=(0, 10))
        column.bind_wheel(card)
        b = card.body
        heard = ui.Field(b, entry["heard"] if entry else "", w=WORD_FIELD_W,
                         h=36, radius=10, bg=ui.CARD,
                         placeholder="what it hears")
        heard.place(x=0, y=2)
        tk.Label(b, text="\u27f6", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 14)).place(x=WORD_FIELD_W + 18, y=6)
        meant = ui.Field(b, entry["meant"] if entry else "", w=WORD_FIELD_W,
                         h=36, radius=10, bg=ui.CARD,
                         placeholder="what you mean")
        meant.place(x=WORD_FIELD_W + 52, y=2)
        tk.Label(b, text="A word you type here is fixed on every dictation "
                         "from now on.", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=2 * WORD_FIELD_W + 70, y=12)
        p["words_save"] = widgets.gold_button(
            b, "Save", lambda: self._words_save(heard.get(), meant.get()),
            w=80, h=34, bg=ui.CARD)
        p["words_save"].place(x=CW - 24, y=3, anchor="ne")
        ui.Button(b, "Cancel", self._words_cancel, w=80, h=34, quiet=True,
                  bg=ui.CARD).place(x=CW - 112, y=3, anchor="ne")
        for field in (heard, meant):
            field.bind_entry("<Return>", lambda _e: self._words_save(
                heard.get(), meant.get()))
            field.bind_entry("<Escape>", lambda _e: self._words_cancel())
        p["words_heard"], p["words_meant"] = heard, meant
        (meant if entry else heard).take_focus()

    def _words_edit(self, heard: str) -> None:
        """Open the editor — for a new pair ("") or the named one."""
        if "corr_list" not in self.parts:
            return
        self._words_editing = heard
        self._fill_corrections()
        if not heard:
            try:
                self.parts["page"].to_top()
            except Exception:             # noqa: BLE001 — no such method
                pass

    def _words_cancel(self) -> None:
        self._words_editing = None
        self._fill_corrections()

    def _words_save(self, heard: str, meant: str) -> None:
        heard, meant = " ".join(heard.split()), " ".join(meant.split())
        if not heard or not meant:
            self._note("both words are needed")
            return
        if heard.lower() == meant.lower():
            self._note("the two words are the same")
            return
        was = self._words_editing
        if was:
            self._vocab_change("edit", heard=was, new_heard=heard, meant=meant)
        else:
            self._vocab_change("learn", heard=heard, meant=meant)
        self._words_editing = None
        self._fill_corrections()

    def _words_forget(self, heard: str) -> None:
        self._vocab_change("forget", heard=heard)
        self._fill_corrections()

    def _vocab_change(self, do: str, **args) -> None:
        """One of the three doors, through the running app — it owns
        vocab.json while it runs, and its save would overwrite ours —
        and straight into the file when nothing is running, which the
        app reads at its next start. The note says what happened."""
        if self.running:
            self._ask("vocab", then=lambda r: self._vocab_answered(r, do),
                      do=do, **args)
            return
        import vocab as vocab_mod
        try:
            vcfg = config_mod.load_layered().vocab
            v = vocab_mod.Vocab(paths.VOCAB_FILE,
                                replace_after_hits=vcfg.replace_after_hits)
        except Exception:                 # noqa: BLE001 — unreadable config
            v = vocab_mod.Vocab(paths.VOCAB_FILE)
        try:
            if do == "learn":
                v.learn_by_hand(args["heard"], args["meant"])
                what = "learned"
            elif do == "edit":
                v.edit(args["heard"], args["new_heard"], args["meant"])
                what = "changed"
            else:
                what = "forgotten" if v.forget(args["heard"]) else "not in the list"
        except KeyError:
            what = "not in the list"
        except ValueError as e:
            what = str(e)
        self._note(f"{what} — {len(v)} words (the app reads them when it "
                   "starts)")

    def _vocab_answered(self, reply: dict | None, do: str) -> None:
        if reply is None:
            # it stopped between the poll and the click: the file path
            self._note("dictation stopped — try again")
        elif not reply.get("ok"):
            self._note(reply.get("error", "that did not work"))
        else:
            self._note(reply.get("message") or do)
        self._corr_stamp = None       # the next poll redraws off the file

    def _words_use(self, on: bool) -> None:
        """The switch: vocab.enabled — the same line Settings > Repair
        shows, written the same way. Off, the app neither repairs a
        dictation with the list nor puts its words in the decoder's
        prompt; the list itself stays."""
        if self.running:
            self._ask("option", then=lambda r: self._announce(
                r, settings_mod.saved_sentence("vocab.enabled", bool(on))),
                name="vocab.enabled", value=bool(on))
            return
        try:
            config_mod.save({"vocab.enabled": bool(on)})
        except Exception as e:            # noqa: BLE001
            self._note(str(e))
            self.parts["words_use"].set(not on)
            return
        self._note(settings_mod.saved_sentence("vocab.enabled", bool(on),
                                               live=False))

    def _words_search_soon(self, text: str) -> None:
        if self._words_search_after is not None:
            try:
                self.root.after_cancel(self._words_search_after)
            except Exception:             # noqa: BLE001
                pass
        self._words_search_after = self.root.after(
            SEARCH_MS, lambda: self._words_search(text))

    def _words_search(self, text: str) -> None:
        self._words_search_after = None
        if text == self._words_query:
            return
        self._words_query = text
        self._fill_corrections()

    def _poll_waiting(self) -> None:
        """Once a second from _refresh. Six stores, one stamp
        each, and a redraw only when one of them moved — a
        notification arriving, a verdict given at a card, a
        consent whose words changed. Reading six stat()s costs
        nothing; rebuilding the rows every second would not."""
        if "pile_list" not in self.parts:
            return
        stamp = (self._notify_stat(), self._review_stat(),
                 self._hardware_stat(), self._lock_stat(),
                 self._consent_stat())
        if stamp != getattr(self, "_pile_stamp", None):
            self._fill_waiting()
        self._paint_rest()

    # -- the pile

    def _waiting_items(self) -> list[dict]:
        """Everything that wants an answer, newest first, as row specs.

        Each source is guarded on its own: a store that is absent, off or
        unreadable contributes nothing and the others still draw.
        """
        items: list[dict] = []
        items += self._waiting_consent()
        items += self._waiting_lock()
        items += self._waiting_update()
        items += self._waiting_hardware()
        items += self._waiting_notify()
        items += self._waiting_review()
        items.sort(key=lambda row: row.get("at", 0.0), reverse=True)
        # ONE GOLD BUTTON PER SURFACE, across the whole pile and not per
        # row: with three proposals waiting, three lit Yes buttons are three
        # primary actions, which is none. The newest keeps the lamp; every
        # later Yes is drawn quiet and still answers the same way.
        lit = False
        for row in items:
            buttons = []
            for label, tone, act in row.get("buttons", ()):
                if tone == "gold":
                    tone = "quiet" if lit else "gold"
                    lit = True
                buttons.append((label, tone, act))
            row["buttons"] = buttons
        return items

    # -- what the machine wants: the model, the GPU pack, a changed tier

    def _hardware_words(self) -> tuple[str, str, str]:
        """(the model's state, the GPU pack's standing, the tier change
        note) — three words, each guarded, read once a second."""
        try:
            model = models_mod.state(config_mod.load_layered().local.model)
        except Exception:                 # noqa: BLE001
            model = "unknown"
        try:
            pack = packs_mod.standing("gpu")
        except Exception:                 # noqa: BLE001
            pack = "unknown"
        try:
            changed = str(hardware_mod.recorded().get("tier_changed") or "")
        except Exception:                 # noqa: BLE001
            changed = ""
        return model, pack, changed

    def _hardware_stat(self):
        return self._hardware_words()

    def _waiting_update(self) -> list[dict]:
        """Chapter 9 screen 11 (D21) as a pile row, not a card of its own:
        when the weekly check found a newer release, one row on Home —
        the version, the size, the date — with the one button the row
        on Settings > General carries (Download and install, or the
        winget one-liner; no notes link and no Skip since 2026-09-21,
        the owner: "only download — everyone on the same version").
        Nothing on the Store channel, while the check is off, or
        Offline."""
        try:
            s = updates.status()
        except Exception:                 # noqa: BLE001
            return []
        rel = s.get("available")
        if rel is None or s.get("mode") in ("store", "off", "offline"):
            return []
        mb = rel.size / 1_048_576
        when = f", {rel.published[:10]}" if rel.published else ""
        buttons: list = []
        if self._too_old_for(rel):
            return [{
                "at": time.time(), "kind": "update", "mark": "version",
                "mark_colour": ui.AMBER, "eyebrow": "A newer version",
                "eyebrow_right": False,
                "text": f"DeskIT {rel.version} is available, but this copy's settings are "
                        f"too old to go straight to it — install the intermediate version "
                        f"the release notes name first.",
                "note": "Your data folder is untouched either way.",
                "buttons": [("Release notes", "gold", lambda r=rel: self._open_url(r.notes_url))],
            }]
        if s.get("winget_command"):
            buttons.append(("Copy the winget command", "gold",
                            lambda c=s["winget_command"]: self._copy_text(c)))
        elif not paths.DEVELOPER:
            buttons.append(("Download and install", "gold",
                            lambda r=rel: self._update_install(r)))
        return [{
            "at": time.time(), "kind": "update", "mark": "version",
            "mark_colour": ui.ACCENT, "eyebrow": "A newer version",
            "eyebrow_right": False,
            "text": f"DeskIT {rel.version} is available ({mb:.0f} MB{when}) — "
                    f"you have {s.get('running', '')}.",
            "note": "Downloaded from GitHub and checked against its SHA-256 before "
                    "the installer runs; your data folder is untouched.",
            "buttons": buttons,
        }]

    def _waiting_hardware(self) -> list[dict]:
        """The rows of chapter 9's screen 10 and 6.9, on the pile rather
        than a card of their own: Home is a summary (the owner, three
        times), and a model that is not there, a card that will not
        run, or a tier that changed are exactly "what wants me". Each
        row's button runs the step in a process of its own — this
        window cannot host a second Tk root — and the app picks the
        model up at the next dictation (transcribers.missing). Nothing
        here in the checkout or a portable copy but the tier note."""
        model, pack, changed = self._hardware_words()
        rows: list[dict] = []
        now = time.time()
        if not paths.PORTABLE and model in ("absent", "incomplete", "stale"):
            size = ""
            try:
                e = models_mod.entry(config_mod.load_layered().local.model)
                size = f" ({models_mod.human(e.bytes)})" if e else ""
            except Exception:             # noqa: BLE001
                pass
            said = {"absent": f"The Hebrew model is not on this PC yet{size} — "
                              "dictation waits for it.",
                    "incomplete": "The Hebrew model's download did not finish — "
                                  "it continues from where it stopped.",
                    "stale": "The Hebrew model on this PC is from an older "
                             "release — download the new one."}[model]
            rows.append({
                "at": now, "kind": "hardware", "mark": "engine",
                "mark_colour": ui.AMBER, "eyebrow": "This computer",
                "eyebrow_right": False, "text": said,
                "note": "Downloaded once, from huggingface.co, into the app's folder.",
                "buttons": [("Download" if model == "absent" else "Continue", "gold",
                             lambda: self._hardware_step("--download-model"))],
            })
        if not paths.PORTABLE and pack.startswith("failed:"):
            rows.append({
                "at": now, "kind": "hardware", "mark": "alert",
                "mark_colour": ui.RED, "eyebrow": "This computer",
                "eyebrow_right": False,
                "text": "Your NVIDIA card was found but GPU speed could not "
                        f"start ({pack[7:]}).",
                "note": "Dictation works on the processor meanwhile.",
                "buttons": [("Retry", "quiet", self._hardware_retry),
                            ("Reinstall", "quiet",
                             lambda: self._hardware_step("--install-pack", "gpu")),
                            ("Remove the pack", "quiet", self._hardware_remove)],
            })
        if changed:
            rows.append({
                "at": now, "kind": "hardware", "mark": "engine",
                "mark_colour": ui.ACCENT, "eyebrow": "This computer",
                "eyebrow_right": False,
                "text": f"Your hardware changed: DeskIT now runs {changed}.",
                "note": "The speed settings for this tier were applied; "
                        "yours were left alone.",
                "buttons": [("OK", "quiet", self._hardware_seen)],
            })
        return rows

    def _hardware_step(self, flag: str, name: str | None = None) -> None:
        if launch.run_step(flag, name):
            self._note("the download window is opening…")
        else:
            self._note("could not start the download window")

    def _hardware_retry(self) -> None:
        packs_mod.clear_failure("gpu")
        self._note("GPU speed will be tried again at the next start")
        self._fill_waiting()

    def _hardware_remove(self) -> None:
        packs_mod.remove("gpu")
        self._note("faster dictation is off — Settings > Dictation offers it again")
        self._fill_waiting()

    def _hardware_seen(self) -> None:
        hardware_mod.clear_change()
        self._fill_waiting()

    @staticmethod
    def _stamp_of(text: str, fmt: str) -> float:
        try:
            return time.mktime(time.strptime(str(text)[:19], fmt))
        except (ValueError, TypeError, OverflowError):
            return 0.0

    def _waiting_notify(self) -> list[dict]:
        try:
            store = self._notify_store()
            unread = [i for i in (store.recent(30) if store else [])
                      if not i.get("seen")]
        except Exception:                 # noqa: BLE001 — a broken file
            return []
        rows = []
        for item in unread:
            ident = item.get("id")
            who = str(item.get("label") or item.get("source") or "")
            when = ago(str(item.get("at", "")))
            buttons = [("Go there", "quiet",
                        lambda i=ident: self._notify_one("open", i)),
                       ("✕", "close",
                        lambda i=ident: self._notify_one("dismiss", i))]
            room = self._row_room(buttons)
            # The title is what the row is; the body's first sentence is
            # what it is ABOUT, and the note band was empty. Both are cut
            # at a sentence boundary rather than at the pixel the row ran
            # out of, so neither ends mid-word.
            rows.append({
                "at": self._stamp_of(item.get("at", ""), "%Y-%m-%dT%H:%M:%S"),
                "kind": "notify", "mark": "notify",
                "mark_colour": {"done": ui.GREEN, "input": ui.ACCENT,
                                "error": ui.RED}.get(
                    str(item.get("kind") or "info"),
                    getattr(ui, "COOL", ui.ACCENT_TEXT)),
                "eyebrow": "   ·   ".join(b for b in (who, when) if b),
                "eyebrow_right": False,
                "text": summary.one_line(item.get("title") or "", room,
                                         self._measure).text,
                "note": summary.one_line(item.get("body") or "", room,
                                         self._measure).text,
                "buttons": buttons,
            })
        return rows

    def _waiting_review(self) -> list[dict]:
        """A proposal, said as WHAT CHANGED.

        The row used to draw the whole PROPOSED SENTENCE with the new
        word on a pill, the reason in 9 pt under it, and an ellipsis
        wherever the width ran out — so the one thing that has to be on
        it, which word became which, was the one thing that was not. The
        owner, looking at exactly this on 2026-09-07: "It's really hard
        for me to understand the corrections that appear on the home
        screen... I don't understand what's written here, the
        corrections."

        So the change leads the row, drawn by `ui.pair_pill` — the same
        chip the vocabulary panel has always used for a learned
        correction, which is where he already reads a pair — and the
        sentence it happened in follows it, cut at SENTENCE boundaries
        (his own suggestion: "display the sentence from point to point").
        The reason stays in the note. A proposal with more than one
        change shows the first pair and SAYS there are more rather than
        drawing three pairs into a 72 px row.
        """
        try:
            pending = self._review_store().pending()
        except Exception:                 # noqa: BLE001
            return []
        rows = []
        for item in pending:
            sid = str(item.get("id", ""))
            buttons = [("Yes", "gold",
                        lambda s=sid: self._review_decide(s, "accepted")),
                       ("No", "quiet",
                        lambda s=sid: self._review_decide(s, "rejected"))]
            said = self._change_bands(item, self._row_room(buttons))
            rows.append({
                "at": self._stamp_of(item.get("when", ""),
                                     "%Y-%m-%d %H:%M:%S"),
                "kind": "review", "mark": "check", "mark_colour": ui.GREEN,
                "eyebrow": said["eyebrow"],
                "runs": said["runs"],
                "text": said["text"],
                "note": said["note"],
                "buttons": buttons,
            })
        return rows

    def _change_bands(self, item: dict, room: int) -> dict:
        """One proposal as the three bands of a row: how much changed,
        the change itself in its sentence, and why.

        `room` is the pixels the words will really have (widgets.
        row_text_room), and the context is cut to what is left after the
        pair has taken its width — measured with `ui.pair_size`, not
        guessed, because a pair of long Hebrew words is twice the chip a
        pair of short ones is.
        """
        changes = [c for c in (item.get("changes") or [])
                   if isinstance(c, dict)]
        heard_text = " ".join(str(item.get("text") or "").split())
        proposed = " ".join(str(item.get("proposed") or "").split()) \
            or heard_text
        if not changes:
            return {"eyebrow": "Second reading", "runs": None, "note": "",
                    "text": summary.one_line(proposed, room,
                                             self._measure).text}
        first = changes[0]
        heard = " ".join(str(first.get("before") or "").split())
        meant = " ".join(str(first.get("after") or "").split())
        count = (f"{_count_word(len(changes)).lower()} word"
                 f"{'' if len(changes) == 1 else 's'}")
        why = " ".join(str(first.get("why") or "").split())

        if not meant or str(first.get("kind")) == "drop":
            # An ending nobody else heard. Nothing BECAME anything, so
            # there is no pair to draw: the words that would go are the
            # chip, in the danger colour, and the sentence they came out
            # of is what places them.
            more = len(changes) - 1
            note = "   ·   ".join(b for b in (
                why, f"and {_count_word(more).lower()} more change"
                     f"{'' if more == 1 else 's'}" if more else "") if b)
            goes = _first_words(heard, 5)
            chip = self._measure(goes) + 18 + 7
            where = self._sentence_around(heard_text, goes.split(" …")[0])
            return {
                "eyebrow": f"Second reading   ·   {count} to delete",
                "runs": [(goes, ui.RED, ui.CHIP_OFF),
                         (summary.one_line(where, max(80, room - chip),
                                           self._measure).text,
                          ui.DIM, None)],
                "text": where, "note": note}

        # EVERY CHANGE IN ITS PLACE (2026-09-21). The row used to lead
        # with one Pair chip and the proposed sentence after it, which
        # left him guessing where in the sentence the mistake had been —
        # "maybe I meant that". Now the sentence is cut around the
        # changes and each one is drawn where it sits, the way Track
        # Changes draws it: the heard word on a red pill, an arrow, the
        # proposal on the gold one with a tick (widgets.Change, the same
        # figure as the card beside the dot). The contexts give way
        # first — a word at a time from the far ends, then from the
        # middles — and a change that still does not fit is counted in
        # the note rather than drawn over the buttons.
        runs, shown, where = self._change_runs(heard_text, changes, room)
        left_out = len(changes) - shown
        note = "   ·   ".join(b for b in (
            why, f"and {_count_word(left_out).lower()} more change"
                 f"{'' if left_out == 1 else 's'} in the sentence"
            if left_out else "") if b)
        return {
            "eyebrow": f"Second reading   ·   {count} changed",
            "runs": runs, "text": where, "note": note}

    @staticmethod
    def _change_runs(text: str, changes: list, room: int
                     ) -> tuple[list, int, str]:
        """The pieces of a proposal row — contexts and Changes in
        sentence order — trimmed to `room` pixels. Returns (runs, how
        many changes are drawn, the sentence the row shows).

        Positions come from each change's `span` into vocab.words(text)
        when it has one (review.py writes it) and from the heard words'
        first occurrence when it does not (an older row, a test's bare
        dict). A change the text does not hold at all is drawn at the
        end, after the words, rather than lost.
        """
        import vocab as vocab_mod
        measure = Dashboard._measure
        flat = " ".join(str(text or "").split())
        # the tokens review.py's spans count (no punctuation), and the
        # same tokens as they READ — each with the marks that follow it,
        # so a context keeps its comma and a sentence its full stop
        starts = [m.start() for m in vocab_mod._WORD.finditer(flat)]
        tw = vocab_mod.words(flat)
        raw = [flat[s:(starts[k + 1] if k + 1 < len(starts) else len(flat))].strip()
               for k, s in enumerate(starts)]
        placed: list = []                 # (i1, i2, heard, meant)
        low = [w.lower() for w in tw]
        for c in changes:
            heard = " ".join(str(c.get("before") or "").split())
            meant = " ".join(str(c.get("after") or "").split())
            if not heard or not meant or str(c.get("kind")) == "drop":
                continue
            span = c.get("span")
            i1 = i2 = None
            if isinstance(span, (list, tuple)) and len(span) == 2:
                try:
                    i1, i2 = int(span[0]), int(span[1])
                except (TypeError, ValueError):
                    i1 = i2 = None
                if i1 is not None and not (0 <= i1 < i2 <= len(tw)):
                    i1 = i2 = None
            if i1 is None:
                hw = [w.lower() for w in vocab_mod.words(heard)]
                for k in range(len(low) - len(hw) + 1):
                    if hw and low[k:k + len(hw)] == hw:
                        i1, i2 = k, k + len(hw)
                        break
            if i1 is None:
                i1 = i2 = len(tw)         # not in the text: after the words
            placed.append((i1, i2, heard, meant))
        placed.sort(key=lambda t: t[0])
        # non-overlapping, in order
        kept: list = []
        end = 0
        for i1, i2, heard, meant in placed:
            if i1 < end:
                continue
            kept.append((i1, i2, heard, meant))
            end = max(end, i2)
        if not kept:
            where = summary.first_sentence(text)
            return ([(summary.one_line(where, room, measure).text,
                      ui.DIM, None)], 0, where)

        def measure_change(heard: str, meant: str) -> int:
            try:
                return widgets.change_size(heard, meant, 12)[0]
            except Exception:             # noqa: BLE001 — no window yet
                return measure(heard) + measure(meant) + 70

        gap = 7

        def stop(word: str) -> bool:
            return bool(word) and word[-1] in summary.STOPS

        while kept:
            # the contexts between and around the kept changes — the
            # outer two cut at the sentence's own ends ("from point to
            # point", his rule of 2026-09-07), never a neighbouring
            # sentence's words
            head = raw[:kept[0][0]]
            for k in range(len(head) - 1, -1, -1):
                if stop(head[k]):
                    head = head[k + 1:]
                    break
            tail = raw[kept[-1][1]:]
            for k, word in enumerate(tail):
                if stop(word):
                    tail = tail[:k + 1]
                    break
            ctx = [head]
            for a, b in zip(kept, kept[1:]):
                ctx.append(raw[a[1]:b[0]])
            ctx.append(tail)
            cut = [False] * len(ctx)      # trimmed at its far end / middle
            fixed = sum(measure_change(h, m) for _a, _b, h, m in kept)
            fixed += gap * (2 * len(kept))

            def width_of() -> int:
                total = fixed
                for words_, was_cut in zip(ctx, cut):
                    if words_:
                        total += measure(" ".join(words_)
                                         + (" …" if was_cut else ""))
                return total

            # the outer contexts first, a word at a time from the far
            # ends, the longer first; then the inner ones from their
            # middles
            while width_of() > room:
                outer = [(len(ctx[0]), 0), (len(ctx[-1]), len(ctx) - 1)]
                outer = [o for o in outer if o[0] > 0]
                if outer:
                    n, k = max(outer)
                    if k == 0:
                        ctx[0] = ctx[0][1:]
                    else:
                        ctx[-1] = ctx[-1][:-1]
                    cut[k] = True
                    continue
                inner = [(len(ctx[k]), k) for k in range(1, len(ctx) - 1)
                         if len(ctx[k]) > 0]
                if not inner:
                    break
                n, k = max(inner)
                mid = len(ctx[k]) // 2
                ctx[k] = ctx[k][:mid] + ctx[k][mid + 1:]
                cut[k] = True
            if width_of() <= room or len(kept) == 1:
                break
            kept.pop()                    # the last change goes to the note
        runs: list = []
        for k, (i1, i2, heard, meant) in enumerate(kept):
            words_ = ctx[k]
            if words_:
                piece = " ".join(words_)
                if cut[k]:
                    piece = ("… " + piece) if k == 0 else (piece + " …")
                runs.append((piece, ui.DIM, None))
            runs.append((widgets.Change(heard, meant), None, None))
        tail = ctx[-1]
        if tail:
            runs.append((" ".join(tail) + (" …" if cut[-1] else ""),
                         ui.DIM, None))
        where = " ".join(raw[max(0, kept[0][0] - 8):kept[-1][1] + 8])
        return runs, len(kept), where

    @staticmethod
    def _measure(text: str) -> int:
        """A row's words, in pixels — the face and the size a PileRow
        draws its body at.

        Tk's measurement and DrawTextW's agree here to the pixel: the
        same Hebrew line came back 161 px wide from `ui.text_width` at
        12 pt and 161 px wide from `ui.draw_text`, measured 2026-09-07.
        That agreement is what lets a cut be decided while the spec is
        built, one screen away from anything that can render. Without a
        window there is nothing to ask, and 6 px a character (Hebrew at
        12 pt is 5.9, Latin 7.6) is a cut that is roughly right rather
        than a traceback in the middle of a repaint.
        """
        try:
            return ui.text_width(str(text), ui.TEXT, 12)
        except Exception:                 # noqa: BLE001 — no window yet
            return len(str(text)) * 6

    @staticmethod
    def _row_room(buttons) -> int:
        """The pixels a pile row's words will really get, given what is
        going to be drawn to the right of them."""
        return widgets.row_text_room(CW - 28, buttons)

    @staticmethod
    def _sentence_around(text: str, word: str) -> str:
        """The one sentence of `text` that holds `word`.

        "Maybe display the sentence from point to point or something like
        that" — his own words for the fix, and a far better rule than a
        character count: what he reads is a whole sentence or a whole
        clause, never the front half of a word. A word that is not in
        the text verbatim (a dropped tail is not in the proposal, and a
        repair can change the spacing around what it touched) falls back
        to the first sentence, which still beats the first 90
        characters.
        """
        for piece in summary.sentences(text):
            if word and word in piece:
                return piece
        return summary.first_sentence(text)

    def _fill_waiting(self) -> None:
        if "pile_list" not in self.parts:
            return
        self._pile_stamp = (self._notify_stat(), self._review_stat(),
                            self._hardware_stat(), self._lock_stat(),
                            self._consent_stat())
        p = self.parts
        items = self._waiting_items()
        count = len(items)
        p["waiting_head"].config(
            text="Nothing is waiting." if not count else
            f"{_count_word(count)} thing{'' if count == 1 else 's'} "
            f"want{'s' if count == 1 else ''} an answer.")
        # THE SUBLINE HAS TO AGREE WITH THE HEADLINE. It said "Nothing
        # else on the desk needs you right now" whatever was waiting, so
        # the page could read "Six things want an answer." over "Nothing
        # else needs you right now" — two sentences that cannot both be
        # true, in the two biggest lines on the screen. Now it says the
        # one thing the headline leaves open: whether what he can see is
        # all of it.
        #
        # It COUNTS what did not fit rather than saying where it went,
        # and that is deliberate. Three of the four kinds have a place
        # of their own on the band below; unread notifications do not —
        # their place IS this page — and on this machine they are the
        # commonest overflow of the four (87 of the last 100 cards were
        # per-turn finishes). A sentence that sent him to a door that is
        # not there would be wrong most of the times it was read.
        extra = count - PILE_CAP
        p["waiting_sub"].config(
            text="Nothing else on the desk needs you right now."
            if not count else
            "It is here, and nothing else needs you right now."
            if count == 1 else
            "They are all here, and nothing else needs you right now."
            if count <= PILE_CAP else
            f"The newest {_count_word(PILE_CAP).lower()} are here, and "
            f"{_count_word(extra).lower()} more "
            f"{'is' if extra == 1 else 'are'} waiting.")

        shown = items[:PILE_CAP]
        column = p["pile_list"]
        column.clear()
        card = p["pile_card"]
        if not items:
            card.pack_forget()
        else:
            # As tall as its rows: the hairlines between them, and one
            # line for what did not fit.
            card.resize(28 + len(shown) * PILE_ROW_H + (len(shown) - 1))
            if not card.winfo_manager():
                # Straight under the headline, because the pile is what
                # the headline is ABOUT. It used to be packed under the
                # line of counts, which put a count of the things above
                # the things themselves. The held line, when there is
                # one, belongs between the card and the band, so the
                # card goes before whichever of the two is there.
                held = p["held_line"]
                card.pack(anchor="w", pady=(0, 14),
                          before=held if held.winfo_manager()
                          else p["elsewhere"])
            for index, spec in enumerate(shown):
                if index:
                    widgets.rule(column.inner, CW - 28, bg=ui.CARD,
                                 colour=ui.LINE).pack(fill="x")
                row = widgets.PileRow(
                    column.inner, CW - 28, bg=ui.CARD,
                    mark=spec.get("mark", ""),
                    mark_colour=spec.get("mark_colour"),
                    eyebrow=spec.get("eyebrow", ""),
                    eyebrow_right=spec.get("eyebrow_right", True),
                    text=spec.get("text", ""), runs=spec.get("runs"),
                    note=spec.get("note", ""),
                    buttons=spec.get("buttons", ()),
                    height=PILE_ROW_H)
                row.pack(fill="x")
                column.bind_wheel(row)
                column.bind_wheel(row.canvas)
            column.bind_wheel(card)
        self._paint_doors(items)

        # Dismiss all belongs to the notifications and to nothing else.
        unread = sum(1 for i in items if i["kind"] == "notify")
        if unread:
            p["dismiss_key"].place(x=PAD + CW, y=60, anchor="ne")
            p["dismiss_all"].place(x=PAD + CW - 108, y=64, anchor="ne")
        else:
            p["dismiss_all"].place_forget()
            p["dismiss_key"].place_forget()

        self._paint_held()
        self._paint_rest()
        self._settle_page()

    def _settle_page(self) -> None:
        """Give the page's slack to the band, and put the day's lines on
        the footer rule.

        The hole this fixes was a page packed from the top of a 502 px
        box: with nothing waiting there were 300 px of nothing under the
        last line and a footer rule with an empty page over it. Two
        anchors fix that — the band grows into the room the pile is not
        using, and whatever is STILL left becomes the ground above the
        day, so the day always ends where the page ends.

        Measured and not arithmetic, because arithmetic here is a
        promise about font metrics that this repo has already broken
        once (see button_width): the page is packed, asked how tall it
        came out, and told the difference.
        """
        p = self.parts
        page, band, ground = (p.get("page"), p.get("elsewhere"),
                              p.get("ground"))
        if page is None or band is None or ground is None:
            return
        if not band.winfo_exists() or not ground.winfo_exists():
            return
        floor = getattr(self, "_door_floor", DOOR_MIN_H)
        band.configure(height=floor)
        self._size_doors(floor)
        ground.configure(height=DOOR_GAP)
        page.inner.update_idletasks()
        slack = PAGE_H - page.inner.winfo_reqheight()
        grow = max(0, min(slack, DOOR_MAX_H - floor))
        if grow:
            band.configure(height=floor + grow)
            self._size_doors(floor + grow)
            page.inner.update_idletasks()
            slack = PAGE_H - page.inner.winfo_reqheight()
        ground.configure(height=DOOR_GAP + max(0, slack))

    def _size_doors(self, height: int) -> None:
        """The tiles are as tall as the band. Their words sit on the
        middle line whatever that height is, so a tall tile has ground
        under it rather than a heading hanging off its top edge, and the
        third line — the one that says what the place is for — is only
        drawn when the band is tall enough to hold all of it. _door_full
        is that height, measured off the labels themselves: a note half
        drawn is worse than no note, because a Card body clips without
        telling anyone."""
        full = getattr(self, "_door_full", 0)
        for tile, _block, note in getattr(self, "_door_tiles", ()):
            if not tile.winfo_exists():
                continue
            tile.resize(height)
            if height >= full and not note.winfo_manager():
                note.pack(anchor="w", pady=(DOOR_NOTE_GAP, 0))
            elif height < full and note.winfo_manager():
                note.pack_forget()

    def _door_counts(self, items: list[dict]) -> list[tuple]:
        """The six places, each as (place, glyph, number, what the
        number is, what the place is for). The line after the number
        is ONE word where it can be: six tiles across the band leave
        ~174 px each, and "corrections waiting" was cut through the
        letters the day the sixth door came.

        Every number here is the number of ROWS the place will show him
        when he gets there, which is the only kind of count worth
        putting on a door: Corrections is what the second reading
        is proposing, Said is today's dictations, and Keys and
        Settings are as long as their own lists. Unread messages
        are deliberately not here: their place IS this page, and
        a door back to the page you are standing on is not a door.
        """
        today = time.strftime("%Y-%m-%d")
        said = sum(1 for e in self.log
                   if e.kind == "dictation"
                   and e.when.strftime("%Y-%m-%d") == today)
        learned = _words_learned()
        proposals = sum(1 for i in items if i["kind"] == "review")
        return [
            ("Corrections", "review", proposals, "corrections",
             "and the words it has learned from the ones you said yes to"
             if learned is None else
             f"and the {learned} words it has learned from them"),
            ("Said", "history", said, "said today",
             "the last hundred of them, with the search over them"),
            ("Keys", "keys", len(config_mod.HOTKEY_FIELDS), "keys",
             "every one of them lit on a drawn keyboard"),
            ("Settings", "settings", len(settings_mod.TABS),
             "settings tabs",
             "every setting, in the words the file's own comments use"),
        ]

    def _paint_doors(self, items: list[dict]) -> None:
        """The band under the pile: every other place, what each of them
        is holding right now, and the way in.

        It was one thin line that named only the kinds with something
        waiting — see the note over DOOR_MIN_H for the page that left
        behind. The rule it always had is the rule it still has: a count
        with nowhere to go is a count nobody can act on, so the whole
        tile is the door, not just the word on it.
        """
        frame = self.parts.get("elsewhere")
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children():
            child.destroy()
        self._door_tiles: list[tuple] = []
        doors = self._door_counts(items)
        # The band fills the row exactly. The remainder of the division
        # is handed out a pixel at a time to the tiles on the left rather
        # than left as a gap at the right edge, where it would read as
        # the band having come up short.
        room = CW - DOOR_GAP * (len(doors) - 1)
        width, over = divmod(room, len(doors))
        x = 0
        for index, (place, glyph, number, line, note_text) in \
                enumerate(doors):
            tile_w = width + (1 if index < over else 0)
            tile = ui.Card(frame, tile_w, DOOR_MIN_H, fill=ui.CARD,
                           bg=ui.BG, pad=DOOR_PAD)
            tile.place(x=x, y=0)
            x += tile_w + DOOR_GAP

            # The words ride on a frame of their own, placed on the
            # middle line, so a band that has grown into an empty page
            # has ground above and below its tiles instead of five
            # headings hanging from their top edges.
            #
            # THE NUMBER AND ITS WORDS ARE ONE LINE, not two. Stacked,
            # Rubik wants 43 px for the number and 26 for the line under
            # it, and 69 + the padding is 24 px more than the band has
            # when the pile is full — a tile that could only fit by
            # cutting "corrections waiting" through the letters. Side by
            # side they cost the 43 the number costs anyway, and "5
            # corrections waiting" reads as the sentence it is.
            block = tk.Frame(tile.body, bg=ui.CARD)
            block.place(x=0, rely=0.5, anchor="w")
            head = tk.Frame(block, bg=ui.CARD)
            head.pack(anchor="w")
            # The glyph LEADS the line, the way the mark leads a row of
            # the pile. It was in the tile's top corner, which is fine
            # on a short tile and marooned on a tall one — the band is
            # 200 px when nothing is waiting, and an icon three lines
            # above the words it belongs to is an icon about nothing.
            widgets.icon(head, glyph, bg=ui.CARD,
                         colour=ui.ACCENT if number else ui.FAINT,
                         size=12).pack(side="left", padx=(0, 9))
            tk.Label(head, text=str(number), bg=ui.CARD,
                     fg=ui.FG if number else ui.FAINT,
                     font=(ui.DISPLAY, 18, "bold")).pack(side="left")
            # anchor "s" and 5 px of ground: it sits on the number's
            # baseline rather than at the top of the taller line.
            tk.Label(head, text=line, bg=ui.CARD, fg=ui.DIM,
                     font=(ui.UI, 10), anchor="w").pack(side="left",
                                                        anchor="s",
                                                        padx=(7, 0),
                                                        pady=(0, 5))
            note = tk.Label(block, text=note_text, bg=ui.CARD, fg=ui.FAINT,
                            font=(ui.UI, 9), anchor="w", justify="left",
                            wraplength=tile_w - 2 * DOOR_PAD)
            self._door_tiles.append((tile, block, note))
            self._make_door(tile, place)

        # HOW SHORT THE BAND MAY GET IS ASKED, NOT TYPED. A Card CLIPS —
        # its body is a create_window with a height on it — so a band one
        # pixel too short cuts "corrections waiting" through the middle
        # of the letters and says nothing about it, and every one of
        # these numbers is a font's answer rather than ours: Rubik 18
        # bold is 43 px tall here and Rubik 10 is 26, at a tk scaling of
        # 1.33 that is this machine's and not the next one's. So the two
        # heights that matter are measured. DOOR_MIN_H is only the least
        # the band should ever LOOK like; if a font change pushes the
        # floor past it, the page gains a few pixels of scroll, which is
        # the right way round — reachable, not cut.
        frame.update_idletasks()
        words_h = max((b.winfo_reqheight()
                       for _t, b, _n in self._door_tiles), default=0)
        # reqheight answers for a widget nothing has packed yet, which is
        # what lets the third line be measured before it is ever shown.
        note_h = max((n.winfo_reqheight()
                      for _t, _b, n in self._door_tiles), default=0)
        self._door_floor = max(DOOR_MIN_H, words_h + 2 * DOOR_PAD)
        self._door_full = words_h + DOOR_NOTE_GAP + note_h + 2 * DOOR_PAD

    def _paint_held(self) -> None:
        """The one faint line under the card: what has arrived and is
        NOT on the screen.

        A finish is held until the session that sent it has been quiet
        for [notify] quiet_s seconds \u2014 so it is unread, it is real, and
        there is no card for it anywhere. Without this line the count in
        the title and the column in the corner disagree, and neither says
        why.
        """
        line = self.parts.get("held_line")
        if line is None or not line.winfo_exists():
            return
        info = (self.status.get("notify") or {}) if self.running else {}
        try:
            held = int(info.get("held") or 0)
        except (TypeError, ValueError):
            held = 0
        band = self.parts.get("elsewhere")
        if held:
            line.config(text=f"{held} finish{'es' if held > 1 else ''} "
                             "held until the session that sent them goes "
                             "quiet. They will arrive here, not on your "
                             "screen.")
            # Between the card and the band of doors: it is a footnote to
            # the pile, so it goes under the pile and not under the page.
            if not line.winfo_manager() and band is not None:
                line.pack(anchor="w", padx=2, pady=(0, 10), before=band)
        else:
            line.config(text="")
            line.pack_forget()

    def _notify_one(self, do: str, ident) -> None:
        """Go there / × on one notification.

        Through the running app when there is one — only it can raise the
        window that sent the thing, and only it owns the card column. With
        nothing running the × still has to work, because the list is the
        file and the file is readable either way; "Go there" cannot, and
        says so rather than doing nothing.
        """
        if self.running:
            self._busy_until = time.monotonic() + 1
            self._ask("notify", then=lambda r: self._notify_answered(r, do),
                      do=do, id=ident)
            return
        if do == "open":
            self._note("nothing is running — start it to reach what sent "
                       "that")
            return
        try:
            store = self._notify_store()
            if store is not None and ident is not None:
                store.mark_seen([ident])
        except Exception as e:            # noqa: BLE001
            self._note(f"could not mark that seen: {e}")
        self._fill_waiting()

    # -- the rest of the day

    def _paint_rest(self) -> None:
        """Three lines that report and do not ask: what he last said,
        what he last took a picture of, what he last looked up. A line
        whose store is not there is not drawn — an empty row that says
        "nothing yet" every day is a row that has stopped being read."""
        p = self.parts
        frame = p.get("rest")
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children():
            child.destroy()
        self._rest_keep: list = []
        today = time.strftime("%Y-%m-%d")
        lines = []

        said = next((e for e in self.log if e.kind == "dictation"), None)
        count = sum(1 for e in self.log
                    if e.kind == "dictation"
                    and e.when.strftime("%Y-%m-%d") == today)
        if said is not None:
            lines.append(("Said", said.when.strftime("%H:%M"),
                          said.text or "", f"{count} today",
                          ui.is_rtl(said.text or ""),
                          lambda: self._show("Said")))
        else:
            # The one sentence a first run has to say. Kept as its own
            # part because a test reads it: an empty history that says
            # nothing at all reads as a broken screen.
            p["last_text"] = tk.Label(frame, text="Nothing dictated yet.",
                                      bg=ui.BG, fg=ui.FAINT,
                                      font=(ui.UI, 10), anchor="w")
            p["last_text"].place(x=0, y=10)

        took = self._last_capture()
        if took is not None:
            path, when, day_count = took
            lines.append(("Took", time.strftime("%H:%M", time.localtime(when)),
                          f"{path.name}  ·  in {path.parent.name}\\",
                          f"{day_count} today", False,
                          lambda d=path.parent: launch.open_path(d)))

        looked = next((e for e in self.log if e.kind == "lookup"), None)
        if looked is not None:
            lines.append(("Looked up", looked.when.strftime("%H:%M"),
                          looked.text or looked.source or "", "",
                          ui.is_rtl(looked.text or ""),
                          lambda: self._show("Said")))

        y = 0
        for label, when, text, meta, rtl, command in lines:
            row = widgets.quiet_row(frame, CW, bg=ui.BG, label=label,
                                    when=when, text=text, meta=meta, rtl=rtl,
                                    command=command,
                                    keep=self._rest_keep)
            row.place(x=0, y=y)
            y += 43

        self._paint_strip()

    def _last_capture(self):
        """(path, mtime, how many today) of the newest picture, or None.

        Read off the disk rather than out of a store, because there is no
        store: a screenshot is a file in [capture] folder and that is all
        it has ever been. 7.4 of them a day, and until tonight nothing in
        this window knew they existed.
        """
        try:
            cfg = config_mod.load_layered()
            folder = Path(getattr(cfg.capture, "folder", "") or "")
        except Exception:                 # noqa: BLE001
            return None
        if not folder or not folder.is_dir():
            return None
        try:
            shots = [f for f in folder.iterdir()
                     if f.is_file() and f.suffix.lower() in CAPTURE_SUFFIXES]
        except OSError:
            return None
        if not shots:
            return None
        shots.sort(key=lambda f: f.stat().st_mtime)
        newest = shots[-1]
        midnight = time.mktime(time.strptime(time.strftime("%Y-%m-%d"),
                                             "%Y-%m-%d"))
        today = sum(1 for f in shots if f.stat().st_mtime >= midnight)
        return newest, newest.stat().st_mtime, today

    def _paint_strip(self) -> None:
        p = self.parts
        if "strip_awake" not in p or not p["strip_awake"].winfo_exists():
            return
        awake = (self.status.get("awake") or {}) if self.running else {}
        dark = bool(awake.get("dark"))
        if not self.running:
            sentence = ("Nothing is running, so nothing is holding the "
                        "machine awake.")
        elif dark:
            since = awake.get("since") or awake.get("hold_since")
            when = (time.strftime("%H:%M", time.localtime(since))
                    if since else "")
            sentence = (f"The screens are off since {when}. The machine "
                        "stays awake." if when else
                        "The screens are off. The machine stays awake.")
        elif awake.get("held"):
            sentence = "The machine stays awake while this runs."
        else:
            sentence = "The machine sleeps on its own timer."
        model = (self.status or {}).get("model") or "on"
        if self.running and model != "on":
            sentence = ("The model is off — every key that needs no model works; "
                        "Start loads it again." if model == "off" else
                        "The model is loading — about 25 seconds.")
        p["strip_awake"].config(text=sentence)
        p["strip_awake"].update_idletasks()

        bits = []
        phone = (self.status or {}).get("phone")
        bits.append("phone live" if phone else "phone off")
        bits.append(f"DeskIT {paths.DEV_TAG} {version.VERSION}".replace("  ", " "))
        if getattr(self, "branch", ""):
            bits.append(f"running {self.branch}")
        learned = _words_learned()
        if learned is not None:
            bits.append(f"{learned} words learned")
        p["strip_facts"].config(text="   ·   ".join(bits))

    def _vocab_panel(self, parent=None) -> None:
        """What saying things has taught it: the count, the last pairs it
        learned, and the key that teaches it one on purpose.

        The pairs are drawn with ui.pair_pill — the same widget the
        review card and the learned rows use — so a correction looks the
        same wherever it is shown, and the arrow points LEFT when the
        words are Hebrew, which pair_pill already knows how to do.
        """
        p = self.parts
        width = CW - SAID_W - 20
        card = ui.Card(parent if parent is not None else self.sheet,
                       width, 508, fill=ui.CARD, bg=ui.BG, pad=16)
        if parent is not None:
            card.pack(anchor="n")
        else:
            card.place(x=PAD + SAID_W + 20, y=64)
        body, inner = card.body, width - 32
        tk.Label(body, text="V O C A B U L A R Y", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)
        learned = _words_learned()
        p["vocab_count"] = tk.Label(
            body, text="—" if learned is None else str(learned), bg=ui.CARD,
            fg=ui.FG, font=(ui.DISPLAY, 24, "bold"))
        p["vocab_count"].place(x=0, y=20)
        tk.Label(body, text="words it has learned to hear your way",
                 bg=ui.CARD, fg=ui.DIM, font=(ui.UI, 9), wraplength=inner,
                 justify="left").place(x=0, y=60)

        keys = self.status.get("keys") or self._read_keys()
        teach = pretty_key(keys.get("correct_hotkey", ""))
        row = tk.Frame(body, bg=ui.CARD)
        row.place(x=0, y=92)
        ui.KeyCap(row, teach, bg=ui.CARD,
                  w=max(56, 26 + ui.text_width(teach, ui.UI, 10)),
                  h=28).pack(side="left")
        tk.Label(row, text="teach it a word", bg=ui.CARD, fg=ui.DIM,
                 font=(ui.UI, 9)).pack(side="left", padx=(10, 0))

        widgets.rule(body, inner, bg=ui.CARD, colour=ui.LINE, x=0, y=136)
        tk.Label(body, text="L A T E L Y", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=150)
        pairs = tk.Canvas(body, width=inner, height=250, bg=ui.CARD,
                          highlightthickness=0, bd=0)
        pairs.place(x=0, y=172)
        p["vocab_pairs"] = pairs
        # THE STEP IS THE PILL'S OWN HEIGHT, asked for rather than
        # written down. It was 30 px and `ui.PILL_H` is 36, so every row
        # was drawn 6 px into the one above it — the overlap the owner
        # reported on 2026-09-07 — and a taller pair (a Hebrew word set
        # larger than the pill) would have made it worse. Whatever fits
        # in the panel is what is asked for, so nothing is drawn past the
        # bottom of the canvas either.
        y, gap, room = 0, 6, 250
        for wrong, right in self._recent_pairs(
                max(1, (room + gap) // (ui.PILL_H + gap))):
            _wide, tall = ui.pair_size(wrong, right)
            if y + tall > room:
                break
            ui.pair_pill(pairs, inner, y, wrong, right, ui.CARD)
            y += tall + gap
        if not y:
            pairs.create_text(0, 6, anchor="nw", font=(ui.UI, 9),
                              fill=ui.FAINT,
                              text="Nothing learned yet — say Yes to a "
                                   "second reading, or press the teach key "
                                   "on a word it got wrong.")

        try:
            cap = config_mod.load_layered().vocab.max_terms
        except Exception:                 # noqa: BLE001 — unreadable config
            cap = None
        p["vocab_hot"] = tk.Label(
            body, bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8), wraplength=inner,
            justify="left",
            text=("The best of them go into the decoder's prompt before it "
                  f"listens — {cap} at a time." if cap
                  else "The best of them go into the decoder's prompt "
                       "before it listens."))
        p["vocab_hot"].place(x=0, y=436)

    def _recent_pairs(self, limit: int) -> list:
        """The last corrections, newest first — out of the log if it has
        learned rows in it, and out of vocab.json when it does not (the
        file is the record; the log only holds the last hundred lines)."""
        out: list = []
        for event in self.log:
            if event.kind == "learned":
                for pair in (event.pairs or []):
                    if not (isinstance(pair, (tuple, list))
                            and len(pair) == 2):
                        continue      # a malformed log line is skipped
                    out.append((str(pair[0]), str(pair[1])))
                    if len(out) >= limit:
                        return out
        if out:
            return out
        import json
        try:
            with (paths.VOCAB_FILE).open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return out
        entries = data.get("corrections") if isinstance(data, dict) else []
        for entry in reversed(entries or []):
            if not isinstance(entry, dict):
                continue
            heard = str(entry.get("heard") or "")
            meant = str(entry.get("meant") or "")
            if heard and meant:
                out.append((heard, meant))
            if len(out) >= limit:
                break
        return out

    def _filter_to(self, kind: str | None) -> None:
        self._filter = kind
        self._said_shown = SAID_PAGE
        for key, chip in self.parts["chips"].items():
            chip.set(key == kind)
        self._fill_history()

    def _search_soon(self, text: str) -> None:
        """Wait for the typing to stop. Rebuilding a hundred rows between
        two letters is how a search box comes to feel broken."""
        if self._search_after is not None:
            try:
                self.root.after_cancel(self._search_after)
            except Exception:
                pass
        self._search_after = self.root.after(SEARCH_MS,
                                             lambda: self._search(text))

    def _search(self, text: str) -> None:
        self._search_after = None
        if text == self._query:
            return
        self._query = text
        self._said_shown = SAID_PAGE
        if text:
            self.parts["placeholder"].place_forget()
        elif self.parts["search"] is not self.root.focus_get():
            self.parts["placeholder"].place(x=26, y=1)
        self._fill_history()

    def _fill_history(self, keep_place: bool = False) -> None:
        """Draw the first screenful now and the rest in the background.

        A hundred rows is about four hundred milliseconds of measuring and
        drawing, and six of them are visible. Doing all of it before
        letting go of the event loop is a filter chip that takes half a
        second to look pressed; doing a screenful and then chunks of
        twenty-five between frames is one that answers immediately.

        AND IT DRAWS `_said_shown` OF THEM, not all of them. "It's a lot
        to scroll and it's a nightmare" — so the list opens on SAID_PAGE
        rows and Show more adds another SAID_PAGE, and a press of it does
        not throw the reader back to the top (`keep_place`).
        """
        if "list" not in self.parts:
            return
        self._stop_rows()
        scroller = self.parts["list"]
        scroller.clear()
        found = history.filtered(self.log, self._filter, self._query)
        limit = getattr(self, "_said_shown", SAID_PAGE)
        shown = found[:limit]
        self.parts["empty"].pack_forget()
        if not found:
            # Its own process: ask the file, not history.enabled (which
            # only the app's start-up sets).
            try:
                off = config_mod.load_layered().history.keep_days <= 0
            except Exception:
                off = False
            self.parts["empty"].config(
                text="History is off (Settings > Privacy > Kept on this "
                     "PC)." if off and not self.log
                else "Nothing here yet." if not self.log
                else "Nothing matches that.")
            self.parts["empty"].pack(anchor="w", padx=8, pady=(24, 24))
        more = self.parts.get("more")
        if more is not None:
            left = len(found) - len(shown)
            if left > 0:
                more.config(text=f"Show {min(left, SAID_PAGE)} more   ·   "
                                 f"{left} older still here")
                more.pack(anchor="w", padx=8, pady=(10, 18))
            else:
                more.pack_forget()
        self._rows_left = list(shown)
        self._draw_rows(8)
        if not keep_place:
            scroller.to_top()

    def _draw_rows(self, count: int) -> None:
        if "list" not in self.parts or self.closing:
            return
        chunk, self._rows_left = self._rows_left[:count], self._rows_left[count:]
        for event in chunk:
            self._history_row(self.parts["list"], event)
        more = self.parts.get("more")
        if more is not None and more.winfo_manager():
            more.pack_forget()
            more.pack(anchor="w", padx=8, pady=(10, 18))
        if self._rows_left:
            self._rows_after = self.root.after(16, lambda: self._draw_rows(25))
        else:
            self._rows_after = None

    def _stop_rows(self) -> None:
        self._rows_left = []
        self._settings_left = []
        for name in ("_rows_after", "_settings_tick"):
            pending = getattr(self, name)
            if pending is not None:
                try:
                    self.root.after_cancel(pending)
                except Exception:
                    pass
                setattr(self, name, None)

    def _history_row(self, scroller: ui.Scroller, event: history.Event) -> None:
        """One event, one canvas — drawn, not built out of widgets.

        A row the obvious way is a rounded card holding six Labels, and a
        hundred of those is seven hundred widgets: rebuilding the list on
        every keystroke in the search box took two seconds, which is not a
        search box, it is a freeze. Drawn as canvas items the same hundred
        rows cost about a tenth of that. It also fixes the highlight for
        free — a Label sitting on a Canvas swallows the <Enter> the Canvas
        was waiting for, so hovering had to be bound to every child.

        The time and the badge are on the LEFT and the text is flush
        RIGHT, which is not a concession to Hebrew: it is the only
        arrangement where a right-to-left sentence and a left-to-right one
        both start at a predictable edge and the column of times stays a
        column.
        """
        raw = event.text or event.note or ""
        row_w = getattr(self, "_row_w", CW)
        left, edge = 106, row_w - 14
        width = edge - left
        pairs = event.pairs if event.kind == "learned" else []

        photo = None
        if pairs:
            height = 78
        else:
            # DrawTextW, not create_text: Tk lays the runs of a mixed
            # Hebrew/English line out backwards. Same engine as the
            # lookup box; cached in ui by the text itself.
            photo, text_h, _lines = ui.draw_text(
                raw, pt=11, width=width, max_lines=2,
                colour=ui.DIM if event.kind == "discarded" else ui.FG,
                bg=ui.CARD)
            height = 46 + text_h

        row = tk.Canvas(scroller.inner, width=row_w, height=height,
                        bg=ui.BG, highlightthickness=0, bd=0,
                        cursor="hand2")
        row.pack(pady=(0, 8))
        idle = ui.rounded(row_w, height, 12, ui.CARD, ui.BG, ui.LINE)
        hot = ui.rounded(row_w, height, 12, ui.CARD_HI, ui.BG, ui.TILE_EDGE)
        face = row.create_image(0, 0, anchor="nw", image=idle)
        colour = COLOURS[event.colour]

        row.create_text(14, 15, text=event.when.strftime("%H:%M"),
                        anchor="nw", font=(ui.UI, 10, "bold"), fill=ui.FG)
        row.create_text(14, 34, text=event.when.strftime("%d %b"),
                        anchor="nw", font=(ui.UI, 8), fill=ui.FAINT)
        row.create_image(66, 14, anchor="nw",
                         image=ui.rounded(28, 28, 9, ui.CHIP_BG, ui.CARD))
        row.create_text(80, 28, text=ui.ICON[event.icon],
                        font=(ui.ICONS, 11), fill=colour)

        if pairs:
            # The two words, not the two sentences they came out of.
            x = edge
            for wrong, correct in pairs[:4]:
                x -= ui.pair_pill(row, x, 14, wrong, correct, ui.CARD) + 6
        elif photo is not None:
            row.create_image(left, 13, anchor="nw", image=photo)

        meta = f"{event.label}   ·   {event.meta()}" if event.meta()             else event.label
        row.create_text(left, height - 29, text=meta, anchor="nw",
                        font=(ui.UI, 8), fill=ui.FAINT)
        row.create_text(edge, height - 30, text=ui.ICON["copy"], anchor="ne",
                        font=(ui.ICONS, 10), fill=ui.FAINT)

        text = event.text or event.source
        row.bind("<Enter>", lambda _e: row.itemconfig(face, image=hot))
        row.bind("<Leave>", lambda _e: row.itemconfig(face, image=idle))
        row.bind("<Button-1>", lambda _e, t=text: self._copy(t))
        scroller.bind_wheel(row)

    # ------------------------------------------------------------- review

    def _review_store(self):
        """review.json, read straight off the disk — this window has to
        list and decide proposals while nothing is running, the same
        reason History reads transcripts.log itself."""
        import review as review_mod
        return review_mod.Store(paths.REVIEW_FILE)

    def _review_stat(self):
        try:
            st = os.stat(paths.REVIEW_FILE)
            return (st.st_size, st.st_mtime_ns)
        except OSError:
            return None

    # The Review SCREEN is gone. A proposal is one of the four things
    # that can be waiting, and it is now a row in the Waiting pile
    # (_waiting_review) with the same Yes / No and the same store call
    # underneath. What is left here is the store, the change detector and
    # the verdict — the parts that were never about a screen.

    def _review_decide(self, sid: str, verdict: str) -> None:
        """Yes or No on a row. Written to review.json here — the app
        learns it at its next idle tick, or now if it is listening."""
        try:
            item = self._review_store().decide(sid, verdict, by="dashboard")
        except Exception as e:            # noqa: BLE001
            self._note(f"could not save that: {e}")
            return
        if item is None:
            self._note("that one was already decided")
        else:
            self._note("accepted — the app will learn it"
                       if verdict == "accepted" else "rejected")
            self._ask("review_absorb")
        self._fill_waiting()

    # ----------------------------------------------------------- problems

    def _problems(self):
        """problems.py, or None if it is not here.

        Imported on every call the way review is — sys.modules makes the
        second one free — and guarded on top of that, because the button
        and the screen are the only things in this window that depend on
        the module existing and the window has to open without it.
        """
        try:
            import problems as problems_mod
        except Exception:                 # noqa: BLE001 — feature absent
            return None
        return problems_mod

    def _problems_store(self):
        """problems.json, read straight off the disk — the same reason
        Review reads review.json: this window lists and answers reports
        while nothing is running. The store is cross-process safe (a lock
        file and one rename), so the app filing a report while this
        writes a resolution costs neither of them anything."""
        module = self._problems()
        if module is None:
            return None
        try:
            return module.Store(paths.DATA_DIR / module.STORE_NAME)
        except Exception:                 # noqa: BLE001
            return None

    # ------------------------------------------------- reporting one back

    def _last_dictation(self, kind: str) -> dict | None:
        """The recording a report is probably about, for problems.record.

        The status pipe carries only when-and-how-many-characters for the
        last dictation — main.py says why, and it is a good reason — so
        the evidence has to come off the disk instead, and the newest wav
        in recent\\ IS the one he just complained about.

        Only for "wrong" and "slow", because record() COPIES the clip out
        of the ring into problems\\ so it survives eviction, and an idea
        about the layout of this screen has no business pinning a
        megabyte of audio to itself.
        """
        if kind not in ("wrong", "slow"):
            return None
        try:
            wavs = sorted(paths.RECENT_DIR.glob("*.wav"),
                          key=lambda p: p.stat().st_mtime)
        except OSError:
            return None
        return {"wav": str(wavs[-1])} if wavs else None

    @staticmethod
    def _report_shot(pcfg) -> bytes | None:
        """The screen as it is now, as JPEG bytes.

        main._problem_shot's recipe and its reasons, on this side of the
        pipe: BYTES rather than a file, because problems.pin_shot writes
        what it is handed and a report he cancels should leave nothing
        behind; PIL and visual_qa imported here, because a dashboard that
        never files a report should never pay the seconds they cost a
        cold process. A report with no picture is still a report, so
        everything in here is allowed to fail quietly.
        """
        try:
            import visual_qa as visual_qa_mod
            from PIL import ImageGrab
            image = ImageGrab.grab(all_screens=True).convert("RGB")
            return visual_qa_mod.encode_jpeg(
                image, int(getattr(pcfg, "max_side_px", 0) or 1344))
        except Exception as e:            # noqa: BLE001
            import logging
            logging.getLogger("app").debug(
                "could not photograph the screen for a report: %r", e)
            return None

    @staticmethod
    def _shot_photo(module, jpeg: bytes | None):
        """The attached screenshot as something Tk will draw, or None.

        problems.thumb does the scaling — one place decides how big a
        thumbnail is, and it is the module that owns THUMB_MAX — but it
        takes a PATH and what the box has is bytes it has not filed yet.
        So the bytes go to a temp file for exactly as long as the call
        takes and are unlinked in the same breath: nothing about a report
        he may still cancel belongs in problems\\, next to the ones he
        sent.

        tk.PhotoImage takes PNG bytes directly (measured: raw bytes,
        no base64) which is the whole reason thumb() returns PNG.
        """
        if not jpeg:
            return None
        import tempfile
        fd, name = tempfile.mkstemp(prefix="report-shot-", suffix=".jpg")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(jpeg)
            png = module.thumb(paths.DATA_DIR, name)
        except Exception:                 # noqa: BLE001 — no picture, no row
            png = None
        finally:
            try:
                os.unlink(name)
            except OSError:
                pass
        if not png:
            return None
        try:
            return tk.PhotoImage(data=png)
        except tk.TclError:
            return None

    def _report(self) -> None:
        """Say what is wrong, from wherever you are.

        One line is all that is asked for; problems.record attaches the
        rest — the settings that explain a bad dictation, the branch, the
        recording itself. `where` is self.screen and is NOT a field he
        fills in, because the tab he is looking at answers "where" every
        single time and asking would be asking him to type what the
        window already knows.

        THE CARD IS THE WINDOW. It was a Toplevel with a title bar and a
        strip of ui.BG around the card until 2026-09-04, when the owner
        looked at it and asked for the card and nothing else — so it is
        `overrideredirect`, the way overlay.WordPrompt and ui.Dropdown
        are, sized to the card exactly, with Windows rounding the corners
        (_round_frameless says how, and what that costs). What the frame
        used to provide has to come from somewhere else now: Escape and
        Return for the two answers, since there is no X to click, and a
        click anywhere outside the card for "never mind", which is the
        gesture a floating card asks for. The `done` latch still runs the
        exit once from whichever of the six ways out fires, and the
        centring is still manual off the main window because Tk has no
        notion of "over the parent".
        """
        # The switch first, because it is what he asked for rather than
        # what happens to be installed. With it off there is no button to
        # press, so this is the door being tried from somewhere else, and
        # the answer is still no.
        if not self._problems_on:
            self._note("[problems] enabled is false — nothing is being "
                       "reported or written")
            return
        module = self._problems()
        if module is None:
            self._note("problems.py is not here — reporting is off")
            return
        kinds = tuple(getattr(module, "KINDS", ("wrong",))) or ("wrong",)
        where = self.screen

        # THE SCREEN FIRST, before there is a box to photograph. Same
        # order and same reason as main._problem_ask: a report about what
        # is on the screen wants the screen, not the question.
        try:
            cfg = config_mod.load_layered()
            pcfg = getattr(cfg, "problems", None)
        except Exception:                 # noqa: BLE001 — a picture is a bonus
            cfg = pcfg = None
        jpeg = self._report_shot(pcfg) if getattr(pcfg, "shot", True) else None
        shot = self._shot_photo(module, jpeg)

        card_w = 420
        inner = card_w - 44
        limit = int(getattr(module, "TEXT_MAX", 600) or 600)
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)        # no title bar: this IS the card
        top.title("Report a problem")     # for the taskbar, and for tests
        top.configure(bg=ui.CARD)
        top.resizable(False, False)
        top.transient(self.root)
        try:
            # Topmost because a grabbed window nobody can see reads as an
            # app that has hung: if he clicks another window the card has
            # to stay where he can answer it.
            top.attributes("-topmost", True)
        except tk.TclError:
            pass

        # Measured before anything is placed, because the card is exactly
        # as tall as what is in it and these are the parts whose height is
        # not arithmetic: the chips (ui.Chip is as wide as its own word,
        # and KINDS — five of them since "other" — is the only list of the
        # words, so a sixth kind wraps onto a second line instead of off
        # the side of the card) and the two wrapped sentences at the top.
        # A scratch frame that is thrown away: a Chip cannot be
        # reparented, and rebuilding five of them costs nothing
        # (ui.rounded caches every face).
        scratch = tk.Frame(top)
        widths = [ui.Chip(scratch, name, bg=ui.CARD).winfo_reqwidth()
                  for name in kinds]
        heads = [tk.Label(scratch, text=words, font=(ui.UI, 8),
                          justify="left", wraplength=inner)
                 for words in (REPORT_HINT, REPORT_KEYS)]
        scratch.update_idletasks()
        hint_h, keys_h = (label.winfo_reqheight() for label in heads)
        scratch.destroy()
        spots = _wrap(widths, inner)
        chips_h = (spots[-1][1] + 30) if spots else 0

        # THE BODY IS A FRAME, and the field is what made it one. The card
        # GROWS as he types, and a ui.Card is a canvas sized once with a
        # body window sized once inside it — growing that means rebuilding
        # both, per keystroke. Nothing is lost by dropping it: the face
        # has been flat since the window frame came off (fill and
        # background the same colour, no border, because the rounding is
        # the window's job — see _round_frameless), so all the Card was
        # drawing here was a rectangle of ui.CARD, which is what the
        # window itself already is. relwidth/relheight with a negative
        # addend keeps the 22 px pad on all four sides at every height.
        body = tk.Frame(top, bg=ui.CARD)
        body.place(x=22, y=22, relwidth=1.0, relheight=1.0,
                   width=-44, height=-44)
        tk.Label(body, text=f"ON {where.upper()}", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=0, y=0)
        tk.Label(body, text="What is wrong?", bg=ui.CARD, fg=ui.FG,
                 font=(ui.DISPLAY, 14, "bold")).place(x=0, y=16)
        # problem_card's words rather than this file's, and it owns them
        # for the same reason it owns the metrics: two surfaces of one
        # feature that phrase it differently read as two features. The
        # hint used to open with "One line." and this field is
        # deliberately not one line any more, so the keys line under it
        # says what replaced that clause — ON THE CARD, because Enter
        # sends, and a box that did not say so would swallow the first
        # report he tried to start a second paragraph in.
        tk.Label(body, text=REPORT_HINT, bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8), justify="left",
                 wraplength=inner).place(x=0, y=44)
        y_keys = 44 + hint_h + 7
        keys_line = tk.Label(body, text=REPORT_KEYS, bg=ui.CARD, fg=ui.FAINT,
                             font=(ui.UI, 8), justify="left",
                             wraplength=inner)
        keys_line.place(x=0, y=y_keys)
        y_field = y_keys + keys_h + 12

        # A tk.Text, not a tk.Entry. The owner's words for the Entry were
        # "very slop and strict", and he was right: one 30 px line with
        # the sentence jammed against the border, for a field whose real
        # limit is problems.TEXT_MAX — six hundred characters. So it is
        # the field the hotkey card grew, on this surface: wrapping, three
        # lines tall, growing to eight, FIELD_PAD_X/Y of interior room,
        # and spacing3 so one display line is FIELD_LINE_H exactly and the
        # two boxes have one line height between them.
        #
        # THE EDGE IS A PICTURE, and the widget sits inside it. Tk
        # widgets are rectangles, and a hard-cornered box among rounded
        # chips, rounded buttons and a rounded card is a good half of the
        # "strict" he was objecting to — so the well is a bitmap at
        # FIELD_RADIUS (the hotkey card's own radius, painted the same
        # way) and the Text is inset WELL_INSET inside it, where a square
        # corner still falls within the arc: at radius 9 the arc passes
        # 2.6 px from the corner, so 3 px in is inside the curve and no
        # nub of the field pokes out of it. Accent while it has the
        # caret, hairline when it has not — what Tk's highlightcolor did
        # for the Entry, done by hand now that the edge is painted.
        #
        # MEASURED, and the reason the echo below is still mandatory: a
        # tk.Text scrambles a mixed Hebrew/English line EXACTLY the way
        # the Entry did. Growing the field was a change of widget and a
        # change of widget is a change of bidi, so it was checked rather
        # than hoped for — the same finding overlay.ProblemCard reports.
        WELL_INSET = 3
        well = tk.Label(body, bg=ui.CARD, bd=0, highlightthickness=0)
        field = tk.Text(body, bg=ui.EDGE, fg=ui.FG,
                        insertbackground=ui.ACCENT,
                        selectbackground=ui.ACCENT_SOFT,
                        selectforeground=ui.FG, bd=0, highlightthickness=0,
                        wrap="word", undo=True, font=FIELD_FONT,
                        spacing3=max(0, FIELD_LINE_H - FIELD_FONT_LINE),
                        insertwidth=2, padx=FIELD_PAD_X - WELL_INSET,
                        pady=FIELD_PAD_Y - WELL_INSET)
        field.tag_configure("rtl", justify="right")

        # …and this is what the field cannot do, whichever widget it is.
        # It is the only place in this window where TK lays out a sentence
        # instead of ui.draw_text, and a MIXED line comes out of it with
        # its runs in the wrong order — measured here 2026-09-04: typing
        # "הכפתור של Settings לא עובד אחרי restart" DRAWS as "של הכפתור
        # Settings אחרי עובד לא restart". Every character is right and the
        # report is stored right; only the drawing lies, which is exactly
        # layer 2 of this file's docstring. So the line is echoed
        # underneath through DrawTextW, the renderer that gets it right,
        # and he can read back what he actually typed before he sends it.
        echo = tk.Label(body, bg=ui.CARD, anchor="e")

        # Chips, not a dropdown: five values, one of them always on, and
        # the whole set worth seeing at once — the same call the History
        # filters and the Settings tabs make. Placed at the spots measured
        # above rather than packed in a strip, because a wrapped line is a
        # second row and pack has no idea where that is.
        picked = {"kind": kinds[0]}
        chips: dict[str, ui.Chip] = {}

        def pick(name: str) -> None:
            picked["kind"] = name
            for key, chip in chips.items():
                chip.set(key == name)
            # the strip's sizes follow the kind (the recording rides only
            # with wrong and slow); the switches stay as he left them
            sending["sizes"] = sizes_for(name)
            paint_strip()

        for name in kinds:
            chips[name] = ui.Chip(body, name, lambda n=name: pick(n),
                                  bg=ui.CARD, active=(name == kinds[0]))

        # THE PICTURE THAT IS GOING WITH IT. He asked to see the
        # screenshot before he sends the report, which is the only way to
        # know it caught the thing he is reporting — and, when [problems]
        # shot is off or the grab failed, to see that there is no picture
        # rather than assume there is one.
        keep: list = []
        picture = caption = None
        if shot is not None:
            keep.append(shot)
            picture = tk.Label(body, image=shot, bg=ui.CARD, bd=0,
                               highlightthickness=1,
                               highlightbackground=ui.STROKE)
            caption = tk.Label(body, text="The screen as it was a moment "
                                          "before this box opened. It goes "
                                          "with the report.",
                               bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8),
                               justify="left", anchor="nw",
                               wraplength=max(80, inner - shot.width() - 26))

        # THE COPY THAT TRAVELS (plan 7.6, screen 7; problem_card paints
        # the same rows on the hotkey card). One switch — "Send to the
        # developer", off — and, only while it is on, the strip under
        # it: what would leave this PC, each piece with its size and
        # its own switch. The switch asks the report_upload consent card
        # first when the gate is shut; that card is beside the dot, in
        # the app's process, so it is asked over the pipe and the poll
        # below flips the switch when [Turn on] has been pressed.
        sending = {"on": False, "await": False,
                   "attach": (module.attach_defaults(kinds[0])
                              if hasattr(module, "attach_defaults") else {}),
                   "sizes": {}}

        def sizes_for(kind: str) -> dict:
            """What each toggle weighs for this kind — the recording only
            rides with "wrong" and "slow" (_last_dictation), so the strip
            says "none" for an idea."""
            try:
                return module.sizes_before_filing(
                    jpeg=jpeg, last=self._last_dictation(kind), cfg=cfg,
                    app_dir=paths.DATA_DIR)
            except Exception:             # noqa: BLE001 — a size is a bonus
                return {}

        sending["sizes"] = sizes_for(kinds[0])
        send_switch = ui.Switch(body, False, command=lambda v: toggle_send(v),
                                bg=ui.CARD)
        send_label = tk.Label(body, text=REPORT_SEND_TOGGLE, bg=ui.CARD,
                              fg=ui.DIM, font=(ui.UI, 10), cursor="hand2")
        send_label.bind("<Button-1>", lambda _e: send_switch.toggle())
        strip_head = tk.Label(body, text=REPORT_STRIP, bg=ui.CARD,
                              fg=ui.FAINT, font=(ui.MEDIUM, 8))
        strip: dict[str, tuple] = {}
        for name in REPORT_ATTACH:
            switch = ui.Switch(body, False,
                               command=lambda v, n=name: toggle_attach(n, v),
                               bg=ui.CARD)
            label = tk.Label(body, text="", bg=ui.CARD, fg=ui.DIM,
                             font=(ui.UI, 9), cursor="hand2")
            label.bind("<Button-1>", lambda _e, s=switch: s.toggle())
            strip[name] = (switch, label)

        def paint_strip() -> None:
            sizes = sending["sizes"]
            for name, (switch, label) in strip.items():
                have = int(sizes.get(name) or 0) > 0
                on = have and bool(sending["attach"].get(name))
                switch.set(on)
                label.configure(
                    text=f"{REPORT_ATTACH_WORDS.get(name, name)}  ·  "
                         f"{_size_word(sizes.get(name)) if have else REPORT_NONE}",
                    fg=ui.FAINT if not have else ui.FG if on else ui.DIM)
            send_label.configure(fg=ui.FG if sending["on"] else ui.DIM)
            keys_line.configure(text=REPORT_KEYS_SEND if sending["on"]
                                else REPORT_KEYS)

        def toggle_attach(name: str, value: bool) -> None:
            if int(sending["sizes"].get(name) or 0) <= 0:
                strip[name][0].set(False)
                return
            sending["attach"][name] = bool(value)
            paint_strip()

        def toggle_send(value: bool) -> None:
            if value and not self._upload_allowed():
                send_switch.set(False)
                sending["await"] = True
                self._ask("consent", then=consent_asked, kind="report_upload")
                return
            sending["on"] = bool(value)
            paint_strip()
            relayout()

        def consent_asked(reply: dict | None) -> None:
            if done["value"]:
                return
            if reply is None:
                self._note("start the app first — the consent card is "
                           "beside the dot")
                sending["await"] = False
            elif reply.get("asked"):
                self._note("the consent card is beside the dot — press "
                           "Turn on, and the switch here turns on with it")
            elif reply.get("allowed"):
                sending["await"] = False
                send_switch.set(True)
                toggle_send(True)
            else:
                self._note(reply.get("error") or "the upload consent is off")
                sending["await"] = False

        actions = tk.Frame(body, bg=ui.CARD)
        done = {"value": False}
        state = {"typed": None, "lines": FIELD_LINES_MIN, "echo_h": 0,
                 "focused": True}

        def finish(text: str | None) -> None:
            if done["value"]:
                return
            done["value"] = True
            # THE PICTURES GO BEFORE THE WINDOW DOES. A PhotoImage
            # finalised after its interpreter has gone calls into a dead
            # Tcl from whichever thread the collector is on, which is the
            # "Tcl_AsyncDelete: async handler deleted by the wrong thread"
            # abort overlay.ProblemCard had to learn on its SECOND card.
            # This box shares the dashboard's interpreter and its thread,
            # so it is not the same exposure — but dropping them here
            # costs one line and means nothing this box builds can outlive
            # it, however many times it is opened and closed.
            try:
                echo.config(image="")
                echo.image = None
                if picture is not None:
                    picture.image = None
            except Exception:
                pass
            keep.clear()
            try:
                top.grab_release()
                top.destroy()
            except Exception:
                pass
            if text is not None:
                self._file_report(module, where, picked["kind"], text, jpeg,
                                  send=sending["on"],
                                  attach=dict(sending["attach"]))

        # Two primaries, one shown: the word follows the switch (Keep on
        # this PC / Preview) and ui.Button is as wide as it was built,
        # so each is built for its own word.
        keep_button = ui.Button(actions, REPORT_KEEP,
                                lambda: finish(field.get("1.0", "end-1c")),
                                w=widgets.button_width(REPORT_KEEP, icon=True,
                                                       least=104),
                                primary=True, icon=ui.ICON["error"])
        preview_button = ui.Button(actions, REPORT_PREVIEW,
                                   lambda: finish(field.get("1.0", "end-1c")),
                                   w=widgets.button_width(REPORT_PREVIEW,
                                                          icon=True, least=104),
                                   primary=True, icon=ui.ICON["error"])
        keep_button.pack(side="left", padx=(0, 8))
        cancel_button = ui.Button(actions, "Cancel", lambda: finish(None),
                                  w=96, quiet=True)
        cancel_button.pack(side="left")

        # WHAT IS NOT A HANDLE. His words were "the upper side or
        # everything beside the buttons and the text box, so I can move
        # it", so the whole card drags except the things you press: the
        # field (which has to keep its own mouse text selection), the five
        # chips and the two buttons. The well is in here with the field
        # rather than with the chrome — it is the 3 px ring around the
        # text, and a press one pixel wide of the sentence he is aiming at
        # should not move the card out from under him.
        controls = {field, well, keep_button, preview_button, cancel_button,
                    send_switch, send_label}
        controls.update(chips.values())
        for switch, label in strip.values():
            controls.update((switch, label))
        # The cursor says which is which before he presses anything: the
        # move cross over everything that drags, and each control keeps
        # the cursor it sets for itself (hand2 on the chips and the
        # buttons, the I-beam asked for explicitly here because a Text
        # inheriting the cross would look like a handle).
        top.configure(cursor="fleur")
        body.configure(cursor="fleur")
        field.configure(cursor="xterm")

        # Where the card is, once. It GROWS DOWNWARD from here: x and y
        # are left alone by every repaint, so the corner he started
        # reading at does not move under him while he types. Manual,
        # because Tk has no notion of "over the parent" — and HIS if he
        # has ever dragged one, which beats the middle of the dashboard by
        # definition: he moved it there on purpose.
        if self._report_at is not None:
            at = {"x": self._report_at[0], "y": self._report_at[1]}
        else:
            at = {"x": max(0, self.root.winfo_rootx()
                           + (self.root.winfo_width() - card_w) // 2),
                  "y": max(0, self.root.winfo_rooty() + 170)}

        def relayout() -> None:
            """Place everything from the field down, and size the window.

            One function for it because five things move together: the
            field's height is a line count, and the echo, the chips, the
            screenshot and the buttons all sit under it. The only thing
            allowed to override the fixed origin is the bottom of the
            screen — holding y there would mean hiding the two buttons,
            which is worse than moving the card.
            """
            field_h = state["lines"] * FIELD_LINE_H + 2 * FIELD_PAD_Y
            face = ui.rounded(inner, field_h, FIELD_RADIUS, ui.EDGE, ui.CARD,
                              ui.ACCENT if state["focused"] else ui.STROKE)
            well.config(image=face)
            well.image = face          # the Label is the only reference
            well.place(x=0, y=y_field, width=inner, height=field_h)
            field.place(x=WELL_INSET, y=y_field + WELL_INSET,
                        width=inner - 2 * WELL_INSET,
                        height=field_h - 2 * WELL_INSET)
            y = y_field + field_h + 8
            echo_h = state["echo_h"]
            echo.place(x=0, y=y, width=inner, height=max(1, echo_h))
            y += echo_h + (6 if echo_h else 0) + 14
            for name, (cx, cy) in zip(kinds, spots):
                chips[name].place(x=cx, y=y + cy)
            y += chips_h
            if picture is not None:
                y += 12
                picture.place(x=0, y=y)
                caption.place(x=shot.width() + 16, y=y + 2)
                y += shot.height() + 2
            # The switch, then the strip under its label while it is on
            # — problem_card's CHECK_GAP / ROW_H / STRIP_INDENT, so the
            # two surfaces measure the same.
            y += 14
            send_switch.place(x=0, y=y + 2)
            send_label.place(x=56, y=y + 4)
            y += 30
            if sending["on"]:
                y += 8
                strip_head.place(x=56, y=y)
                y += 18
                for name in REPORT_ATTACH:
                    switch, label = strip[name]
                    switch.place(x=56, y=y + 2)
                    label.place(x=112, y=y + 5)
                    y += 30
                if not preview_button.winfo_ismapped():
                    keep_button.pack_forget()
                    preview_button.pack(side="left", padx=(0, 8),
                                        before=cancel_button)
            else:
                strip_head.place_forget()
                for switch, label in strip.values():
                    switch.place_forget()
                    label.place_forget()
                if not keep_button.winfo_ismapped():
                    preview_button.pack_forget()
                    keep_button.pack(side="left", padx=(0, 8),
                                     before=cancel_button)
            y += 16
            actions.place(x=inner, y=y, anchor="ne")
            height = y + 36 + 44
            spot_y = at["y"]
            room = top.winfo_screenheight() - 8
            if spot_y + height > room:
                spot_y = max(0, room - height)
            top.geometry(f"{card_w}x{height}+{at['x']}+{spot_y}")

        def pump() -> None:
            """Read the field on a timer, not on a key.

            The line does not always arrive from the keyboard. THE BOX CAN
            BE DICTATED INTO — the app is another process, so injector
            pastes into it and a Tk grab does not stop that (measured) —
            and it can be pasted into, undone and redone. A tk.Text has no
            textvariable to trace, and the write trace this box used to
            run caught the keys and nothing else. One poll catches every
            route, which is what the hotkey card does with the same field
            for the same reason.
            """
            if done["value"]:
                return
            try:
                if sending["await"] and self._upload_allowed():
                    # [Turn on] was pressed on the card beside the dot:
                    # the switch he flipped flips, nothing else to press.
                    sending["await"] = False
                    send_switch.set(True)
                    toggle_send(True)
                typed = field.get("1.0", "end-1c")
                if len(typed) > limit:
                    # problems.clean would cut it silently on the way to
                    # disk; better he watches the field stop taking words
                    # than find the tail missing in a report he can no
                    # longer edit.
                    field.delete("1.0+%dc" % limit, "end")
                    typed = field.get("1.0", "end-1c")
                # Re-applied on every pass: a tag does not extend itself
                # over text inserted after it, so a right-aligned field
                # would start going left again at the next word.
                field.tag_add("rtl", "1.0", "end")
                lines = min(FIELD_LINES_MAX,
                            max(FIELD_LINES_MIN, _display_lines(field)))
                if (typed, lines) != (state["typed"], state["lines"]):
                    if typed != state["typed"]:
                        stripped = typed.strip()
                        if stripped:
                            photo, echo_h, _l = ui.draw_text(
                                stripped, pt=10, width=inner,
                                max_lines=FIELD_LINES_MAX, colour=ui.DIM,
                                bg=ui.CARD)
                            echo.config(image=photo)
                            echo.image = photo   # the Label is the only ref
                            state["echo_h"] = echo_h
                        else:
                            echo.config(image="")
                            echo.image = None
                            state["echo_h"] = 0
                    state["typed"], state["lines"] = typed, lines
                    relayout()
                top.after(60, pump)
            except Exception:
                return            # the box went out from under the poll

        def send(_event=None) -> str:
            finish(field.get("1.0", "end-1c"))
            return "break"

        def cancel(_event=None) -> str:
            finish(None)
            return "break"

        def newline(_event=None) -> str:
            """Shift+Enter is the new line and Enter is Send — which is
            why the card says so. Once the field is more than one line the
            two cannot both be Enter, and a report is a sentence he wants
            sent rather than a document he is composing. Bound explicitly
            rather than left to Tk's class binding: the <Return> binding
            fires for a shifted Return too unless something more specific
            claims it.
            """
            field.insert("insert", "\n")
            return "break"

        def select_all(_event=None) -> str:
            """Ctrl+A selects the whole report, which a tk.Text does NOT
            do on its own — its Ctrl+A is Tk's emacs inheritance,
            beginning-of-line. The one-line Entry hid that by being too
            small for it to matter; you cleared that with Backspace. A
            field big enough to hold a paragraph is one he will want to
            replace in a single gesture."""
            field.tag_add("sel", "1.0", "end-1c")
            field.mark_set("insert", "end-1c")
            return "break"

        # Three pixels of slop before a press becomes a drag. A click is
        # a press, a small wobble and a release — without a threshold
        # every click on the title would nudge the card a pixel or two,
        # and the card must sit still for a click that was not a move.
        DRAG_SLOP = 3
        drag = {"on": False, "moved": False, "dx": 0, "dy": 0,
                "rx": 0, "ry": 0}

        def on_control(widget) -> bool:
            """Is the press on one of the things that is not a handle?

            Walked up to the card, because a press lands on the DEEPEST
            widget under the pointer and a ui.Button or a ui.Chip is a
            canvas with items in it, not a leaf — anything inside a
            control is the control.
            """
            while widget is not None and widget is not top:
                if widget in controls:
                    return True
                widget = getattr(widget, "master", None)
            return False

        def pressed(event) -> None:
            """One handler, three answers — and it has to be one handler,
            because a Tk grab sends every press in the application here.

            Measured 2026-09-04: under grab_set() a press on the dashboard
            is not discarded and does not reach the dashboard, it is
            REPORTED TO THE GRAB WINDOW, with the widget set to this
            Toplevel and coordinates relative to it, which for a point
            outside the card is a negative or over-long number. So the
            screen rectangle sorts outside from inside, and the widget
            sorts out what is inside:

              outside the card         cancel — this is what the X in the
                                       title bar used to be
              inside, on a control     hands off: the field keeps its own
                                       text selection, the chips and the
                                       buttons keep their own clicks
              inside, on anything else the card is being dragged

            A drag can never be read as a cancel and a cancel can never
            start a drag, because both are decided by where the press
            LANDED and not by where the pointer ends up: dragging the card
            until the pointer is off it does not cancel, and a press
            outside cannot arm the drag. The rectangle is asked of the
            window rather than held in a variable, because the card
            changes height as he types and moves when he drags it.

            ui.Dropdown's <FocusOut> is not the mechanism for the cancel,
            for the same reason the grab explains: a click on the
            dashboard never takes the focus off this window, so FocusOut
            does not fire for the case that matters. Nor is losing the
            focus to ANOTHER APP a cancel — he may well be going to
            reproduce the thing he is reporting, and coming back to a box
            he has to retype would be worse than no box at all.
            """
            x0, y0 = top.winfo_rootx(), top.winfo_rooty()
            if not (x0 <= event.x_root < x0 + top.winfo_width()
                    and y0 <= event.y_root < y0 + top.winfo_height()):
                finish(None)
                return
            # WHICH widget, asked of the screen rather than of the
            # event. `event.widget` is normally the deepest widget under
            # the pointer, but when the grab is what delivered the press
            # it is this Toplevel and says nothing about what he pressed
            # on — measured 2026-09-04, the same press on the title
            # reported the Label once and the Toplevel once, depending on
            # whether the application was already the active one.
            # winfo_containing reads it off the coordinates, so a press
            # on a chip while the dashboard is in the background is still
            # a press on a chip and not a grab of the margin.
            hit = event.widget
            if hit is top:
                hit = top.winfo_containing(event.x_root, event.y_root) or top
            if on_control(hit):
                return
            drag.update({"on": True, "moved": False,
                         "dx": event.x_root - x0, "dy": event.y_root - y0,
                         "rx": event.x_root, "ry": event.y_root})

        def dragging(event) -> None:
            """Move the window under the pointer. No frame to drag by —
            he has none because it was taken away, which is why he asked
            for this — so it is geometry(), the way overlay.ReviewCard
            moves its own card: the offset from the press is held and the
            corner is put wherever that offset says."""
            if not drag["on"]:
                return
            if not drag["moved"]:
                if (abs(event.x_root - drag["rx"]) < DRAG_SLOP
                        and abs(event.y_root - drag["ry"]) < DRAG_SLOP):
                    return
                drag["moved"] = True
            x, y = event.x_root - drag["dx"], event.y_root - drag["dy"]
            top.geometry(f"+{x}+{y}")
            # `at` FOLLOWS THE DRAG, because relayout re-applies it and
            # anything can call relayout while the pointer is down — the
            # border lighting down when the focus leaves the field is one
            # repaint, and a stale `at` in the middle of a drag would put
            # the card back where the drag started.
            at["x"], at["y"] = x, y

        def dropped(event=None) -> None:
            """WHERE HE PUT IT is where it grows from now.

            `at` is what relayout re-applies on every change, so without
            this line the next word he typed would snap the card back to
            the middle of the dashboard. It is also remembered on the
            dashboard, so the next report opens where he left this one —
            the notify stack and the review card both remember where they
            were dragged to, and a card that forgets is one he has to move
            again every single time.
            """
            if not drag["on"]:
                return
            drag["on"] = False
            if not drag["moved"]:
                return
            # The release carries a position of its own, and it is the
            # last word: a quick flick ends with the button up before the
            # final move has been reported (measured with synthetic input,
            # where Windows coalesces the moves — the card stopped a step
            # short of the pointer), so the drop is applied from the event
            # that ended it rather than from wherever the last motion got
            # to.
            if event is not None:
                dragging(event)
            at["x"], at["y"] = top.winfo_rootx(), top.winfo_rooty()
            self._report_at = (at["x"], at["y"])

        def gone(event) -> None:
            """A grab outlives the window that set it, and a stranded one
            leaves the dashboard taking no clicks at all — so the window
            dying by any route it did not ask for still runs the exit.
            `is top` because <Destroy> reaches this binding for every
            child widget too, and the latch makes finish's own destroy
            free."""
            if event.widget is top:
                finish(None)

        def lit(on: bool):
            """The border follows the caret, and it is wired rather than
            painted on: the box stays up while he goes off to another
            window to reproduce what he is reporting (see `outside`), and
            a field glowing as if it were taking keys while the keys are
            going somewhere else is the one lie on this card that would
            cost him a sentence."""
            def handler(_event=None) -> None:
                if state["focused"] != on and not done["value"]:
                    state["focused"] = on
                    relayout()
            return handler

        field.bind("<FocusIn>", lit(True))
        field.bind("<FocusOut>", lit(False))
        field.bind("<Return>", send)
        field.bind("<KP_Enter>", send)
        field.bind("<Shift-Return>", newline)
        field.bind("<Shift-KP_Enter>", newline)
        field.bind("<Control-a>", select_all)
        field.bind("<Control-A>", select_all)
        field.bind("<Escape>", cancel)
        top.bind("<Button-1>", pressed)
        # Motion and release on the window as well: Tk keeps sending both
        # to whatever took the press, so a drag begun on the title goes on
        # being reported here even when the pointer has left the card
        # entirely. It is the same property that keeps a drag from
        # pressing a chip it happens to end on — the release goes to the
        # widget that took the press, so a chip the pointer merely
        # finishes over never sees one.
        top.bind("<B1-Motion>", dragging)
        top.bind("<ButtonRelease-1>", dropped)
        # On the window as well as the field: with no frame the keyboard
        # is the only way out that is always there, and it must not
        # depend on which of the card's widgets has the focus.
        top.bind("<Return>", send)
        top.bind("<Escape>", cancel)
        top.protocol("WM_DELETE_WINDOW", lambda: finish(None))
        top.bind("<Destroy>", gone)

        paint_strip()
        relayout()
        top.update_idletasks()
        # After the geometry and after update_idletasks: the attribute
        # goes to a real hwnd, and DwmSetWindowAttribute on an unrealised
        # window is the same silent no-op that put the status dot on the
        # close button (overlay.py says so where it learned it).
        _round_frameless(top, ui.STROKE)
        # AND THEN LIFT IT, which a framed Toplevel never needed.
        # Measured 2026-09-04: the card came up mapped, viewable,
        # -topmost, holding the grab, and behind the dashboard — every
        # window flag right and not one pixel of it on the screen. Tk
        # rebuilds the wrapper window when overrideredirect is set, and
        # the rebuilt one lands wherever the z-order happens to put it;
        # -topmost asked for before that gets rebuilt away with it. So
        # both are asserted again HERE, on the window that is finally
        # going to be shown.
        try:
            top.attributes("-topmost", True)
        except tk.TclError:
            pass
        top.lift()
        top.grab_set()
        top.focus_force()
        field.focus_set()
        pump()

    def _file_report(self, module, where: str, kind: str, text: str,
                     jpeg: bytes | None = None, *, send: bool = False,
                     attach: dict | None = None) -> None:
        """Hand the line to problems.record, which collects the rest.

        clean()'s ValueError is the one exception that module raises on
        purpose — an empty line — and it is a sentence to say back, not
        something to log. Everything else in there is already swallowed,
        so filing a report can cost him the report and never the window.

        `send` (plan 7.6): the report is filed here exactly as without
        it; the tick marks the row PREVIEW with the four toggles and
        opens the Preview, where Send is what makes the copy.
        """
        try:
            cfg = config_mod.load_layered()
        except Exception:                 # noqa: BLE001 — env is a bonus
            cfg = None
        try:
            item = module.record(paths.DATA_DIR, {"where": where, "kind": kind,
                                           "text": text},
                                 cfg=cfg, last=self._last_dictation(kind),
                                 jpeg=jpeg)
        except ValueError:
            self._note("nothing was typed — say what is wrong and send it "
                       "again")
            return
        except Exception as e:            # noqa: BLE001
            self._note(f"could not file that: {e}")
            return
        if send and hasattr(module, "mark_preview"):
            module.mark_preview(self._problems_store(), item.get("id", ""),
                                attach)
        said = ("the preview says what leaves this PC" if send
                else "it stays on this PC")
        self._note(f"filed as {item.get('id', '')} — {said}")
        if send:
            self._report_preview(str(item.get("id", "")))

    def _upload_allowed(self) -> bool:
        """Is the report_upload gate open, as this process sees it — the
        [privacy] section from the layered config once, then the consent
        file on every ask (privacy.rows re-reads it when it changed, so
        [Turn on] beside the dot is seen here without a restart)."""
        try:
            import privacy
            if not getattr(self, "_privacy_configured", False):
                privacy.configure(config_mod.load_layered())
                self._privacy_configured = True
            return bool(privacy.allowed("report_upload"))
        except Exception:                 # noqa: BLE001
            return False

    def _report_preview(self, ident: str) -> None:
        """Screen 7's Preview: each ticked file, then the exact row that
        would be posted, then [Send] and [Keep on this PC] — the whole
        of what leaves, and nothing leaves before it was shown.

        The row is the message: the card (this window's box or the
        hotkey's, another process) marked the report PREVIEW with the
        toggles as he left them, and this window builds the payload from
        the stored row (problems.payload), so what is shown is what the
        outbox gets. Read-only by design — changing it means going back
        to the card and filing again.

        The JSON is drawn through DrawTextW line by line (visual_qa
        .text_pil, single-line, no whitespace folding) and not typed
        into a tk.Text: a mixed Hebrew/English line in a Text draws its
        runs in the wrong order (measured 2026-09-04), and a preview
        that scrambles the sentence he is about to send is not a
        preview.
        """
        module = self._problems()
        store = self._problems_store()
        if module is None or store is None:
            return
        # ONE PREVIEW AT A TIME. Two doors open this window: the box's
        # own [Preview] and the look-round (_preview_if_waiting — 600 ms
        # after the first frame, and on every show signal) that opens
        # the newest PREVIEW row for the hotkey card. On a slow machine
        # the look-round fired after the box had filed its row and opened
        # its preview, and a second window for the same report came up
        # under the first; [Keep] closed one and the other stood there
        # (GitHub's runner, 2026-09-21, twice). Whatever door asks, a
        # preview that is already up is brought forward, never doubled,
        # and the look-round's once-per-row memory learns this one too.
        self._previewed.add(ident)
        open_top = self._preview_top
        if open_top is not None:
            try:
                alive = bool(open_top.winfo_exists())
            except Exception:             # noqa: BLE001 — a dead Tcl path
                alive = False
            if alive:
                try:
                    open_top.lift()
                    open_top.focus_force()
                except Exception:         # noqa: BLE001
                    pass
                return
            self._preview_top = None
        item = store.get(ident)
        if not item:
            self._note("that report is not on the list any more")
            return
        attach = item.get("attach") if isinstance(item.get("attach"), dict) \
            else module.attach_defaults(str(item.get("kind") or ""))
        try:
            row, files = module.payload(item, attach, app_dir=paths.DATA_DIR)
        except Exception as e:            # noqa: BLE001
            self._note(f"could not build the preview: {e}")
            return
        text = module.preview_text(row)

        top = tk.Toplevel(self.root)
        top.title("Preview — what leaves this PC")
        top.configure(bg=ui.BG)
        top.resizable(False, False)
        top.transient(self.root)
        _dark_caption(top)
        card_w, pad = 560, 22
        inner = card_w - 2 * pad
        done = {"value": False}
        keep: list = []

        def finish(sent: bool | None) -> None:
            """Send, keep here, or close (Esc, the X): closing is keeping,
            because the report is already on this PC and a preview he
            walked away from must not turn into an upload."""
            if done["value"]:
                return
            done["value"] = True
            keep.clear()
            if self._preview_top is top:
                self._preview_top = None
                self._preview_open = ""
            try:
                top.grab_release()
                top.destroy()
            except Exception:
                pass
            if sent:
                target = module.queue(store, store.get(ident) or item, attach,
                                      app_dir=paths.DATA_DIR)
                if target is None:
                    self._note("could not queue the report — it stays on "
                               "this PC; try Preview & send again")
                else:
                    self._note(f"{ident}: queued — it goes up when the "
                               "app is next online")
                    self._ask("account", do="nudge")
            else:
                module.keep_local(store, ident)
                self._note(f"{ident} stays on this PC")

        body = tk.Frame(top, bg=ui.BG)
        body.pack(fill="both", expand=True, padx=20, pady=(18, 20))
        tk.Label(body, text="WHAT LEAVES THIS PC", bg=ui.BG, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).pack(anchor="w", padx=2)
        tk.Label(body, text="This is everything that leaves your PC. "
                            "Nothing else.", bg=ui.BG, fg=ui.FG,
                 font=(ui.DISPLAY, 14, "bold")).pack(anchor="w", pady=(2, 10))

        # The files first — they are what a person worries about — then
        # the row. Each ticked attachment: the picture small, the
        # recording as a name, its size and Play, the sidecar as a name
        # and size. Then the JSON, one image per line so indentation
        # survives, all in a scroller sized to the screen and never
        # taller than 420.
        scroller = ui.Scroller(body, card_w + 16, 160, bg=ui.BG)
        from PIL import Image, ImageTk
        import visual_qa as visual_qa_mod
        tk.Label(scroller.inner, text="FILES" if files else "NO FILES — THE ROW BELOW IS ALL",
                 bg=ui.BG, fg=ui.FAINT, font=(ui.MEDIUM, 8)).pack(anchor="w", padx=2,
                                                                  pady=(0, 4))
        for entry in files:
            name, path = str(entry.get("name")), str(entry.get("path"))
            size = _size_word(entry.get("bytes"))
            if name.endswith(".jpg"):
                photo = self._shot_photo(module, Path(path).read_bytes()
                                         if Path(path).is_file() else None)
                if photo is not None:
                    keep.append(photo)
                    tk.Label(scroller.inner, image=photo, bg=ui.BG, bd=0,
                             highlightthickness=1,
                             highlightbackground=ui.STROKE).pack(anchor="w",
                                                                 pady=(0, 4))
            line = tk.Frame(scroller.inner, bg=ui.BG)
            line.pack(anchor="w", fill="x", pady=(0, 4))
            tk.Label(line, text=f"{name}  ·  {size}", bg=ui.BG, fg=ui.DIM,
                     font=(ui.UI, 9)).pack(side="left")
            if name.endswith(".wav"):
                ui.Button(line, "Play", lambda p=path: self._play_wav(p),
                          w=widgets.button_width("Play", least=58), h=24,
                          quiet=True).pack(side="left", padx=(10, 0))
        tk.Label(scroller.inner, text="THE ROW", bg=ui.BG, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).pack(anchor="w", padx=2, pady=(10, 4))
        lines = text.splitlines() or [" "]
        json_card = ui.Card(scroller.inner, card_w, 2 * pad + 2, bg=ui.BG,
                            pad=pad)
        y = 0
        ground = tuple(int(ui.CARD.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        ink = tuple(int(ui.FG.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        # Courier New, not Consolas: a monospace face that carries
        # Hebrew glyphs itself, so the sentence in "text" is not drawn
        # by a fallback face at another size.
        for line in lines:
            glyphs = visual_qa_mod.text_pil(line or " ", inner, pt=9.5,
                                            face="Courier New", colour=ink,
                                            rtl=False, single=True)
            flat = Image.new("RGB", glyphs.size, ground)
            flat.paste(glyphs, (0, 0), glyphs)
            photo = ImageTk.PhotoImage(flat, master=top)
            keep.append(photo)
            tk.Label(json_card.body, image=photo, bg=ui.CARD, bd=0).place(x=0, y=y)
            y += glyphs.height
        json_card.resize(y + 2 * pad)
        json_card.pack(anchor="w")
        scroller.inner.update_idletasks()
        need = scroller.inner.winfo_reqheight()
        room = max(160, min(420, top.winfo_screenheight() - 360))
        scroller.resize(min(need, room))
        scroller.pack(anchor="w")

        actions = tk.Frame(body, bg=ui.BG)
        actions.pack(anchor="e", pady=(14, 0))
        send_w = widgets.button_width("Send", icon=True, least=104)
        ui.Button(actions, "Send", lambda: finish(True), w=send_w,
                  primary=True, icon=ui.ICON["error"]).pack(side="left",
                                                            padx=(0, 8))
        ui.Button(actions, REPORT_KEEP, lambda: finish(False),
                  w=widgets.button_width(REPORT_KEEP, least=96),
                  quiet=True).pack(side="left")
        top.bind("<Escape>", lambda _e: finish(None))
        top.protocol("WM_DELETE_WINDOW", lambda: finish(None))
        top.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width()
                                       - top.winfo_width()) // 2
        yy = self.root.winfo_rooty() + 120
        top.geometry(f"+{max(0, x)}+{max(0, yy)}")
        top.lift()
        top.grab_set()
        top.focus_force()
        self._preview_open = ident
        self._preview_top = top

    @staticmethod
    def _play_wav(path: str) -> None:
        """The recording behind a report, once, through winsound — the
        one thing on the Preview that is not a picture of bytes."""
        try:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:                 # noqa: BLE001
            pass

    # --------------------------------------------------------------- keys

    # -------------------------------------------------------------- awake

    def _awake_block(self, scroller) -> None:
        """The machine held awake, and the screens off on a key — awake.py.

        Three cards. The hero says whether the hold is standing — it goes
        up when the app starts and stays until it exits, whatever the
        screens are doing — and carries the one switch, which is about
        the SCREENS: off and kept off, or back. A strip under it has
        "screens off again" (for after something lit them) and the check;
        and the check's answer fills the rest — every reason the spec
        lists for a machine that is awake and still unreachable, as a row
        each, with what to do about it.

        The switch lives in the RUNNING APP: the hold is per process, and
        the process that has to stay awake is the one with the hotkey in
        it, not this window, which is usually closed. So with nothing
        running the switch is disabled and the hint says why. The check
        does not need the app — it reads the machine — so it works either
        way, and runs by itself when the screen opens.
        """
        p = self.parts
        holder = tk.Frame(scroller.inner, bg=ui.BG, width=CW, height=548)
        holder.pack(anchor="w", pady=(0, 14))
        holder.pack_propagate(False)
        tk.Label(holder, text="A W A K E", bg=ui.BG, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=2, y=0)
        hero = ui.Card(holder, CW, 148, pad=18, bg=ui.BG)
        hero.place(x=0, y=18)
        body, inner = hero.body, CW - 36
        p["awake_bar"] = tk.Label(body, bg=ui.CARD)
        p["awake_bar"].place(x=-4, y=0)
        p["awake_glyph"] = tk.Label(body, text=ui.ICON["awake"],
                                    bg=ui.CARD, fg=ui.FAINT,
                                    font=(ui.ICONS, 22))
        p["awake_glyph"].place(x=6, y=2)
        p["awake_state"] = tk.Label(body, text="", bg=ui.CARD, fg=ui.FG,
                                    font=(ui.DISPLAY, 19, "bold"))
        p["awake_state"].place(x=56, y=1)
        p["awake_meta"] = tk.Label(body, text="", bg=ui.CARD, fg=ui.DIM,
                                   font=(ui.UI, 9), anchor="w")
        p["awake_meta"].place(x=57, y=44)
        p["awake_hint"] = tk.Label(body, text="", bg=ui.CARD, fg=ui.FAINT,
                                   font=(ui.UI, 8), justify="left",
                                   anchor="w")
        p["awake_hint"].place(x=57, y=68)
        p["awake_toggle"] = ui.Button(body, "Screens off",
                                      lambda: self._screens("toggle"), w=164,
                                      primary=True, icon=ui.ICON["awake"])
        p["awake_toggle"].place(x=inner, y=0, anchor="ne")

        strip = ui.Card(holder, CW, 76, pad=18, bg=ui.BG)
        strip.place(x=0, y=178)
        wide = widgets.button_width("Screens off again", icon=True)
        p["awake_screen"] = ui.Button(strip.body, "Screens off again",
                                      lambda: self._screens("again"), w=wide,
                                      icon=ui.ICON["power"])
        p["awake_screen"].place(x=0, y=2)
        p["awake_check"] = ui.Button(
            strip.body, "Check status", self._awake_check, quiet=True,
            w=widgets.button_width("Check status", icon=True),
            icon=ui.ICON["check"])
        p["awake_check"].place(x=wide + 12, y=2)
        p["awake_checked"] = tk.Label(strip.body, text="", bg=ui.CARD,
                                      fg=ui.FAINT, font=(ui.UI, 8),
                                      anchor="e")
        p["awake_checked"].place(x=CW - 36, y=12, anchor="ne")

        card = ui.Card(holder, CW, 282, pad=18, bg=ui.BG)
        card.place(x=0, y=266)
        tk.Label(card.body, text="WILL IT STILL BE THERE WHEN YOU ARE AWAY",
                 bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8)).place(x=0, y=0)
        p["awake_rows"] = tk.Frame(card.body, bg=ui.CARD, width=CW - 36,
                                   height=226)
        p["awake_rows"].place(x=0, y=22)
        p["awake_rows"].pack_propagate(False)
        self._awake_shape = None
        self._paint_awake_rows()
        scroller.bind_wheel(holder)
        scroller.bind_wheel(hero)
        scroller.bind_wheel(strip)
        scroller.bind_wheel(card)
        self._paint_awake()
        if AWAKE_AUTO_CHECK and getattr(self, "_awake_probe", None) is None:
            self.root.after(150, self._awake_check)

    def _paint_awake(self) -> None:
        p = self.parts
        if "awake_state" not in p:
            return
        awake = (self.status.get("awake") or {}) if self.running else {}
        holding = bool(awake.get("holding"))
        held = bool(awake.get("held"))
        dark = bool(awake.get("dark"))
        colour = (ui.VIOLET if dark and held else
                  ui.GREEN if held else
                  ui.RED if holding else
                  ui.DIM if self.running else ui.FAINT)
        p["awake_bar"].config(image=ui.rounded(4, 112, 2, colour, ui.CARD))
        p["awake_glyph"].config(fg=ui.VIOLET if dark else ui.FAINT)
        if not self.running:
            state = "NOT RUNNING"
            meta = "the machine sleeps on its own timer"
            hint = ("The hold lives in the running app — the process that "
                    "keeps the machine awake is the one with the hotkey in "
                    "it — so start dictation first.")
        elif holding and not held:
            state = "NOT HOLDING"
            meta = "the app asked and Windows refused"
            hint = ("The app asked Windows to stay awake and the hold is "
                    "not standing. Stop and start the app, and check.")
        elif not holding:
            state = "NOT HELD"
            meta = "[awake] hold = false — it sleeps on its own timer"
            hint = ("Turn hold on in Settings and restart the app, and the "
                    "machine stays awake for as long as it runs.")
        else:
            since = awake.get("hold_since")
            when = (time.strftime("%H:%M", time.localtime(since))
                    if since else "?")
            bits = [f"held since {when}",
                    human_time(awake.get("hold_seconds", 0))]
            if awake.get("pinned"):
                bits.append("sleep timers pinned")
            if dark:
                state = "SCREENS OFF"
                bits.append("screens off for "
                            + human_time(awake.get("seconds", 0)))
                keep = awake.get("keep_screens_off_s") or 0
                if keep:
                    hint = ("The machine is awake and the screens are off. "
                            "Anything that lights them is put out again "
                            f"{keep:g} s after the last touch; Screens off "
                            "again does it now. Screens on brings them back.")
                else:
                    hint = ("The machine is awake and the screens are off. "
                            "The mouse lights them — Screens off again puts "
                            "them out. Screens on brings them back.")
            else:
                state = "AWAKE"
                hint = ("The machine will not sleep while this app runs, "
                        "whatever the screens do. One press: the screens go "
                        "dark and stay dark, nothing is locked, and the "
                        "phone can drive it through Claude.")
            meta = "   ·   ".join(bits)
        p["awake_state"].config(text=state)
        p["awake_meta"].config(text=ui.clamp(meta, ui.UI, 9,
                                             CW - 36 - 57 - 172, 1)[0])
        p["awake_hint"].config(text=ui.clamp(hint, ui.UI, 8,
                                             CW - 36 - 57, 2)[0])
        p["awake_toggle"].configure_text("Screens on" if dark
                                         else "Screens off")
        p["awake_toggle"].enable(self.running)
        p["awake_screen"].enable(self.running)
        shape = (holding, held, awake.get("pinned"))
        if shape != getattr(self, "_awake_shape", None):
            self._awake_shape = shape
            self._paint_awake_rows()

    def _paint_awake_rows(self) -> None:
        frame = self.parts.get("awake_rows")
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children():
            child.destroy()
        result = getattr(self, "_awake_probe", None)
        width = CW - 36
        if result is None:
            tk.Label(frame, bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 9),
                     wraplength=width, justify="left",
                     text="Check status reads what is holding the machine "
                          "awake, the sleep timer, whether Windows may "
                          "power the network card down, Windows Update's "
                          "active hours and whether Claude is running — "
                          "so that a machine that would not have stayed "
                          "reachable is found out now, not from the phone."
                     ).pack(anchor="w")
            return
        awake = (self.status.get("awake") or {}) if self.running else {}
        tones = {"good": ui.GREEN, "warn": ui.AMBER, "bad": ui.RED,
                 "dim": ui.FAINT}
        for label, sentence, tone in awake_mod.verdict(awake, result):
            row = tk.Frame(frame, bg=ui.CARD)
            row.pack(anchor="w", fill="x", pady=(0, 5))
            dot = tk.Label(row, bg=ui.CARD,
                           image=ui.rounded(8, 8, 4, tones.get(tone, ui.FAINT),
                                            ui.CARD))
            dot.pack(side="left", anchor="n", pady=(5, 0))
            tk.Label(row, text=label, bg=ui.CARD, fg=ui.FG,
                     font=(ui.UI, 9, "bold"), width=19, anchor="nw",
                     justify="left").pack(side="left", anchor="n",
                                          padx=(8, 4))
            tk.Label(row, text=sentence, bg=ui.CARD, fg=ui.DIM,
                     font=(ui.UI, 8), wraplength=width - 190,
                     justify="left", anchor="w").pack(side="left",
                                                      anchor="n", fill="x")

    def _screens(self, do: str) -> None:
        """off / on / toggle / again, through the running app."""
        self._busy_until = time.monotonic() + 1
        self._ask("screens", then=lambda r: self._screens_answered(r, do),
                  do=do)

    def _screens_answered(self, reply: dict | None, do: str) -> None:
        if do == "again":
            self._announce(reply, "screens off again")
            return
        state = (reply or {}).get("awake") or {}
        self._announce(reply, "screens off — they stay off until you tap "
                              "again" if state.get("dark")
                       else "screens on")

    def _awake_check(self) -> None:
        """The probe, on a worker: two or three seconds of powercfg and
        PowerShell that must not stall the window."""
        if getattr(self, "_awake_probing", False) or self.closing:
            return
        self._awake_probing = True
        label = self.parts.get("awake_checked")
        if label is not None and label.winfo_exists():
            label.config(text="checking…")

        def work() -> None:
            try:
                result = awake_mod.probe()
            except Exception as e:            # noqa: BLE001
                result = {"error": str(e)}
            self._events.put(lambda: self._awake_checked(result))
        threading.Thread(target=work, daemon=True, name="awake-probe").start()

    def _awake_checked(self, result: dict) -> None:
        self._awake_probing = False
        self._awake_probe = result
        label = self.parts.get("awake_checked")
        if label is not None and label.winfo_exists():
            label.config(text=f"checked {time.strftime('%H:%M:%S')}")
        self._paint_awake_rows()

    # ------------------------------------------------------------- notify

    def _notify_store(self):
        """notify.json, read straight off the disk — the list has to show
        what arrived while nothing is running, the same reason Review
        reads review.json itself. The import is lazy and guarded: this
        window is built identically on a checkout without notify.py, and
        the screen has to draw there too (an empty list, not a traceback).
        """
        try:
            import notify as notify_mod
        except Exception:                 # noqa: BLE001 — no notify.py here
            return None
        return notify_mod.Store(paths.NOTIFY_FILE)

    def _notify_stat(self):
        try:
            st = os.stat(paths.NOTIFY_FILE)
            return (st.st_size, st.st_mtime_ns)
        except OSError:
            return None

    # The Notify SCREEN is gone too, and for the same reason: an unread
    # notification is a thing waiting for an answer, so it is a row in
    # the Waiting pile (_waiting_notify) rather than a hero, a strip and
    # a list of its own. Dismiss all kept its place beside the title;
    # "Send a test" moved to Settings > Messages & sounds, with the cues
    # it is a test OF.

    def _notify(self, do: str) -> None:
        """dismiss / test, through the running app."""
        self._busy_until = time.monotonic() + 1
        self._ask("notify", then=lambda r: self._notify_answered(r, do),
                  do=do)

    def _notify_answered(self, reply: dict | None, do: str) -> None:
        self._announce(reply, {"dismiss": "all marked seen",
                               "test": "test notification sent"}.get(do, do))
        # The reply carries the new state; take it now rather than one
        # poll later, so Dismiss all is seen to do something at once. The
        # pile is then refilled from the file, which a dismissal or a
        # test has always just moved.
        if reply and reply.get("ok") and isinstance(reply.get("notify"),
                                                    dict):
            self.status["notify"] = reply["notify"]
        self._fill_waiting()

    def _notify_open_log(self) -> None:
        path = paths.NOTIFY_LOG
        if not path.exists():
            self._note("no notify.log yet — nothing has arrived")
        elif not launch.open_path(path):
            self._note(f"could not open {path.name}")

    # ------------------------------------------------------------ network

    def _requests_today(self) -> int:
        today = time.strftime("%Y-%m-%d")
        try:
            return sum(1 for r in net.read_log() if r.when.startswith(today)
                       and r.host != "127.0.0.1")
        except Exception:                 # noqa: BLE001
            return 0

    def _screen_network(self) -> None:
        """The Network screen (D12's window, chapter 9 screen 6; off the
        bar since 2026-09-18, opened from EVERY CONNECTION on Settings >
        Privacy — see NAV): every
        outbound request, newest first, read from network.log — the
        record the app and this window share, since they are two
        processes. A host filter, the loopback toggle (the phone and the
        hook knock on 127.0.0.1 and would drown the rest), the file's
        own button, and the sentence that is the point: during plain
        dictation this table stays empty."""
        self._title("Network", "every request, newest first · network.log")
        p = self.parts
        self._net_host = getattr(self, "_net_host", "All")
        self._net_loopback = getattr(self, "_net_loopback", False)
        p["net_chips"] = tk.Frame(self.sheet, bg=ui.BG)
        p["net_chips"].place(x=PAD, y=64)
        p["net_banner"] = tk.Label(self.sheet, text="", bg=ui.BG, fg=ui.AMBER,
                                   font=(ui.UI, 10), anchor="w")
        p["net_banner"].place(x=PAD, y=100)
        page = ui.Scroller(self.sheet, CW + 10, 470, bg=ui.BG)
        page.place(x=PAD, y=126)
        p["net_page"] = page
        # ONE canvas, not a Label per cell. The table was a Frame of
        # Labels, seven a row, four hundred rows: 2,800 widgets, measured
        # at 3 s to build and 5 s to rebuild on the hidden desktop
        # (2026-09-18, the owner's 493-row log) — and it rebuilt on EVERY
        # write to network.log, which during dictation is every few
        # seconds (polish, review, the phone's knock). The window sat
        # "Not responding" more than it answered, which he reported as
        # a crash. Text items on a canvas draw the same rows in tens of
        # milliseconds.
        p["net_rows"] = tk.Canvas(page.inner, bg=ui.BG, highlightthickness=0,
                                  bd=0, width=self.NET_W, height=NET_ROW_H)
        p["net_rows"].pack(anchor="w")
        page.bind_wheel(page.inner)
        foot = tk.Frame(self.sheet, bg=ui.BG)
        foot.place(x=PAD, y=606)
        p["net_line"] = tk.Label(foot, text="", bg=ui.BG, fg=ui.FAINT,
                                 font=(ui.UI, 9), anchor="w")
        p["net_line"].pack(side="left")
        ui.Button(foot, "Back to Privacy", lambda: self._show("Settings"),
                  bg=ui.BG, quiet=True, w=130).pack(side="left", padx=(16, 0))
        ui.Button(foot, "Open network.log", self._net_open_log, bg=ui.BG,
                  quiet=True, w=150).pack(side="left", padx=(8, 0))
        loop = ui.Button(foot, "Show loopback (phone)", lambda: self._net_toggle_loopback(),
                         bg=ui.BG, quiet=True, w=196)
        loop.pack(side="left", padx=(8, 0))
        p["net_loop"] = loop
        self._net_stamp = None
        self._net_painted = None
        self._paint_network()

    # Pixels, and they add up to CW. The widest values each column has
    # held (measured 2026-09-18, 9 pt): a Supabase host 215, a consent
    # "cloud_text@groq-…+gemini-…" 295, a secret "supabase_session"
    # 108. A value wider than its column is cut with an ellipsis rather
    # than run into the next one — the Labels used to clip silently.
    NET_COLS = ((150, "when"), (240, "host"), (110, "purpose"), (110, "bytes"),
                (60, "result"), (130, "secret"), (312, "consent"))
    NET_W = sum(width for width, _name in NET_COLS)
    #: The newest this many rows are painted; the file keeps the rest.
    NET_ROWS_MAX = 400

    def _net_filtered(self, rows: list) -> list:
        out = []
        for r in rows:
            if r.host == "127.0.0.1" and not self._net_loopback:
                continue
            if self._net_host != "All" and r.host != self._net_host:
                continue
            out.append(r)
        return out

    def _paint_network(self) -> None:
        """Every poll: the table again when the file changed, the chips
        for the hosts seen, the banner while Offline mode is on."""
        p = self.parts
        holder = p.get("net_rows")
        if holder is None or not holder.winfo_exists():
            return
        try:
            stamp = paths.NETWORK_LOG.stat().st_mtime_ns
        except OSError:
            stamp = None
        key = (stamp, self._net_host, self._net_loopback)
        if key == getattr(self, "_net_stamp", None):
            return
        self._net_stamp = key
        rows = net.read_log()
        hosts = sorted({r.host for r in rows if r.host != "127.0.0.1"})
        chips = p["net_chips"]
        for child in chips.winfo_children():
            child.destroy()
        for name in ["All"] + hosts:
            ui.Chip(chips, name, lambda n=name: self._net_pick(n),
                    active=(name == self._net_host), bg=ui.BG
                    ).pack(side="left", padx=(0, 6))
        offline = False
        try:
            import privacy
            offline = bool(privacy.offline()) or bool(
                getattr(getattr(self.cfg, "privacy", None), "offline", False))
        except Exception:                 # noqa: BLE001
            pass
        p["net_banner"].configure(
            text="Offline mode: every host but 127.0.0.1 is refused." if offline else "")
        shown = self._net_filtered(rows)
        line = f"{len(shown)} of {len(rows)} rows" if rows else "no request yet"
        if len(shown) > self.NET_ROWS_MAX:
            line += f", the newest {self.NET_ROWS_MAX} painted"
        p["net_line"].configure(text=line)
        # A write the filter hides — the phone's knock on 127.0.0.1 while
        # loopback is off, which is most writes — changes the file and
        # not the table. The count line above moved; the rows need not.
        painted = (len(shown), shown[-1] if shown else None,
                   self._net_host, self._net_loopback)
        if painted == getattr(self, "_net_painted", None):
            return
        self._net_painted = painted
        holder.delete("all")
        x, y = 0, 0
        for width, name in self.NET_COLS:
            holder.create_text(x, y, text=name.upper(), anchor="nw",
                               fill=ui.FAINT, font=(ui.UI, 8, "bold"))
            x += width
        y += NET_ROW_H
        # Fitting measures text through Tcl; the same host, purpose and
        # consent come up hundreds of times, so each is measured once.
        fitted: dict[tuple[str, int], str] = {}

        def fit(value: str, width: int) -> str:
            key = (value, width)
            if key not in fitted:
                fitted[key] = widgets.fit(value, ui.UI, 9, width - 10)
            return fitted[key]

        for r in reversed(shown[-self.NET_ROWS_MAX:]):
            values = (r.when, r.host, r.purpose, f"{r.up} ↑ {r.down} ↓",
                      str(r.status), r.secret, r.consent)
            x = 0
            for (width, name), value in zip(self.NET_COLS, values):
                colour = ui.FG
                if name == "result" and not str(value).startswith("2"):
                    colour = ui.AMBER
                holder.create_text(x, y, text=fit(value, width), anchor="nw",
                                   fill=colour, font=(ui.UI, 9), tags=(name,))
                x += width
            y += NET_ROW_H
        p["net_loop"].configure_text("Hide loopback" if self._net_loopback
                                     else "Show loopback (phone)")
        if not shown:
            holder.create_text(0, y + 12, anchor="nw", fill=ui.DIM,
                               font=(ui.UI, 10), tags=("empty",),
                               text="During plain dictation this table stays "
                                    "empty — that is the proof.")
            y += NET_ROW_H + 24
        # The canvas is the page's only child, so its height is the
        # page's scroll range.
        holder.configure(height=max(y, NET_ROW_H))

    def _net_cells(self, column: str | None = None) -> list[str]:
        """The texts in the table, top to bottom — one column of it, or
        every cell in reading order. What a test reads instead of a
        widget tree."""
        holder = self.parts.get("net_rows")
        if holder is None:
            return []
        items = holder.find_withtag(column) if column else holder.find_all()
        return [holder.itemcget(i, "text") for i in items]

    def _net_pick(self, host: str) -> None:
        self._net_host = host
        self._paint_network()

    def _net_toggle_loopback(self) -> None:
        self._net_loopback = not self._net_loopback
        self._paint_network()

    def _net_open_log(self) -> None:
        path = paths.NETWORK_LOG
        if not path.exists():
            self._note("no network.log yet — nothing has gone out")
        elif not launch.open_path(path):
            self._note(f"could not open {path.name}")

    def _screen_keys(self) -> None:
        """Every binding, lit on the board it lives on.

        The old screen was fifteen rows of "Translate (tap)   [F8]" in a
        scrolling column — a lookup table for a thing that is already
        spatial. He does not remember that translate is F8, he remembers
        where his finger goes; and the question this screen actually has
        to answer, "which keys has this app taken from me", was fifteen
        separate readings.

        So: the board, with the bound caps lit and the Hebrew legends
        beside the Latin ones, because those are what his fingers type.
        Held, tapped, chord and only-sometimes are drawn differently
        (keyboard._skin), the modifier of a chord is lit softly under the
        key that carries it, and Esc — which cancels a recording and is
        watched rather than registered — has a broken edge, because it is
        the one key here that is only sometimes the app's.

        Clicking a cap opens the same key-capture dialog the rows always
        did; the rows are still here, under the board, three to a line,
        and they are what the tests walk.
        """
        self._title("Keys", "press a key, or click one on the board, to see "
                            "what it does — then change it")
        p = self.parts
        p["caps"] = {}
        self._cap_selected = None

        keys = self.status.get("keys") or self._read_keys()
        try:
            lit, unmapped = keyboard_mod.bindings(keys)
        except Exception as e:            # noqa: BLE001 — never a blank screen
            lit, unmapped = {}, []
            self._note(f"could not read the bindings: {e}")

        self._key_legend(y=KEY_LEGEND_Y)

        board = keyboard_mod.Board(self.sheet, lit, u=KEY_UNIT,
                                   bg=ui.BG, command=self._cap_clicked)
        board.place(x=PAD, y=KEY_BOARD_Y)
        p["board"] = board

        # A REAL KEY PRESS answers the question the board asks. Bound on
        # the window rather than the board: the press lands wherever
        # the focus is, and it propagates up to the toplevel from any
        # widget. _key_pressed checks the place is still Keys, so the
        # binding can outlive the screen without doing anything.
        self.root.bind("<KeyPress>", self._key_pressed)

        # THE ROWS ARE STILL HERE, and they are not a fallback. A cap is
        # 34 px of picture with a one-word caption on it; the row says the
        # whole sentence config.py registered ("Report a problem (tap)"),
        # and the test that walks HOTKEY_FIELDS walks these.
        # THE ONE FAINT LINE AT THE BOTTOM IS MEASURED AND PLACED FIRST,
        # upwards from the window's own edge, and the list is then given
        # the room that is left.
        #
        # It used to be the other way round — the list at a fixed height
        # and the line at a fixed y — and the two only agreed while the
        # line was one line long. It is not always one line: a binding on
        # a key this board cannot draw prepends a sentence to it, and at
        # two lines the fixed y put the second one past the bottom edge.
        # Measured 2026-09-07: it ended at y 643 of the sheet's 664 in
        # the ordinary case and at 666 — off the window — in the other.
        missing = ", ".join(f"{f} = {r!r}" for f, r in unmapped)
        safe = ("Anything not lit is untouched by this app. The keys it "
                "cannot take at all — the punctuation caps, ` - = [ ] \\ "
                "; ' , . / — have no code Windows can bind, which is why "
                "they are the safe ones.")
        if missing:
            safe = f"Bound to a key this board does not draw: {missing}. " \
                   + safe
        said, lines = ui.clamp(safe, ui.UI, 8, CW, 3)
        safe_y = H - TOP - KEY_FOOT_GAP - lines * KEY_FOOT_LINE
        tk.Label(self.sheet, text=said, bg=ui.BG, fg=ui.FAINT,
                 font=(ui.UI, 8), justify="left").place(x=PAD, y=safe_y)

        # THE PANEL IS THE RIGHT-HAND COLUMN, not a card as tall as the
        # board. It has to hold 289 px on a cap carrying two bindings
        # (F8 is translate bare and look up with ctrl) — measured on the
        # hidden desktop 2026-09-07 — and a card the board's height is
        # 207 at this unit and was 246 at the old one. Both are short,
        # and the way Tk is short is silent: the packer does not clip a
        # slave that does not fit, it never maps it, so the second
        # binding's button and the line telling you to pick which one
        # you meant were simply absent. It runs from the board's top to
        # the foot line now — 509 px, 477 of body — and the rows below
        # the board take the board's width instead of the window's.
        panel_x = PAD + board.size[0] + KEY_BOARD_GAP
        panel_w = max(KEY_PANEL_W, PAD + CW - panel_x)
        panel_h = max(board.size[1], safe_y - 16 - KEY_BOARD_Y)
        panel = ui.Card(self.sheet, panel_w, panel_h, fill=ui.CARD,
                        bg=ui.BG, pad=16)
        panel.place(x=panel_x, y=KEY_BOARD_Y)
        p["rebind_panel"] = panel
        p["rebind_body"] = panel.body
        p["rebind_w"] = panel_w - 32
        self._paint_rebind()

        top = KEY_BOARD_Y + board.size[1] + 22
        rows_w = board.size[0]
        p["keys_list"] = ui.Scroller(self.sheet, rows_w + 10,
                                     max(60, safe_y - top - 16), bg=ui.BG)
        p["keys_list"].place(x=PAD, y=top)
        self._key_rows(p["keys_list"], lit, width=rows_w)

    def _key_legend(self, y: int) -> None:
        """The five ways a cap can look, said once."""
        colours = keyboard_mod.palette()
        x = PAD
        for title, note, state in KEY_LEGEND:
            face, edge, _ink, dashed = keyboard_mod._skin(state, False,
                                                          colours)
            swatch = tk.Canvas(self.sheet, width=18, height=18, bg=ui.BG,
                               highlightthickness=0, bd=0)
            swatch.place(x=x, y=y + 2)
            swatch.create_rectangle(1, 1, 17, 17, fill=face,
                                    outline=colours["lit_edge"] if dashed
                                    else edge,
                                    dash=(3, 3) if dashed else None)
            tk.Label(self.sheet, text=title, bg=ui.BG, fg=ui.FG,
                     font=(ui.UI, 9, "bold")).place(x=x + 26, y=y)
            tk.Label(self.sheet, text=note, bg=ui.BG, fg=ui.FAINT,
                     font=(ui.UI, 8)).place(x=x + 26, y=y + 17)
            x += 30 + max(ui.text_width(title, ui.UI, 9),
                          ui.text_width(note, ui.UI, 8)) + 26

    def _key_rows(self, scroller: ui.Scroller, lit: dict,
                  width: int = CW) -> None:
        """Every binding, KEY_COLUMNS to a line, each with the cap that
        opens the rebind dialog for it.

        `width` is the room the rows have, which is the BOARD's width
        since the panel became the place's right-hand column: 781 px,
        three columns of 253, against the 208 the longest of them needs
        (the Ctrl+Alt+R cap and "Report a problem" beside it).
        """
        p = self.parts
        keys = self.status.get("keys") or self._read_keys()
        grid = tk.Frame(scroller.inner, bg=ui.BG)
        grid.pack(anchor="w")
        column_w = (width - 20) // KEY_COLUMNS
        for index, (field, label) in enumerate(config_mod.HOTKEY_FIELDS):
            what, how = split_label(label)
            shown = pretty_key(keys.get(field, ""))
            said = KEY_NOTES.get(field)
            note = (said[0] if said else
                    how or ("chord" if "+" in str(keys.get(field, ""))
                            else ""))
            # A CELL IS AS WIDE AS ITS CONTENT WHEN ITS CONTENT IS WIDER
            # THAN THE COLUMN. The cell has a fixed width and propagation
            # off — it has to, since everything in it is `place`d and a
            # frame of placed children asks for 1x1 — so anything past
            # that width is simply cut. Measured 2026-09-07, with the
            # rows narrowed to the board: fifteen of the sixteen fit 253,
            # and "Ctrl+Alt+M  Dismiss the notification" is 259. grid
            # gives a column its widest cell, so one wide cell widens its
            # own column and nothing else; the whole grid then asks for
            # 765 of the 781 the board is wide.
            cap_w = max(74, 34 + ui.text_width(shown, ui.UI, 10))
            # + 6: a tk.Label asks for its text plus one of padx and two
            # of border on each side. Measured, because leaving it out is
            # exactly six pixels of the last word, on the one row that
            # needed the room.
            cell_w = max(column_w, cap_w + 12 + 6 + max(
                ui.text_width(what, ui.UI, 10),
                ui.text_width(note, ui.UI, 8) if note else 0))
            cell = tk.Frame(grid, bg=ui.BG, width=cell_w, height=KEY_ROW_H)
            cell.grid(row=index // KEY_COLUMNS, column=index % KEY_COLUMNS,
                      sticky="w")
            cell.pack_propagate(False)
            cell.grid_propagate(False)
            cap = ui.KeyCap(cell, shown,
                            lambda f=field, la=label: self._capture(f, la),
                            bg=ui.BG, w=cap_w, h=30)
            cap.place(x=0, y=4)
            p["caps"][field] = cap
            tk.Label(cell, text=what, bg=ui.BG, fg=ui.FG,
                     font=(ui.UI, 10)).place(x=cap_w + 12, y=4)
            if note:
                tk.Label(cell, text=note, bg=ui.BG, fg=ui.FAINT,
                         font=(ui.UI, 8)).place(x=cap_w + 12, y=22)
        scroller.bind_wheel(grid)

    def _key_pressed(self, event) -> None:
        """A key pressed for real while the Keys place is up: the cap
        under the finger lights and the panel says what it does, or
        that the app never takes it. The owner, 2026-09-07: "if I press
        R, for example, it would tell me what it does."

        Not while the key dialog is listening — that press belongs to
        the dialog, and changing the selection under it would rebind
        the wrong key — and never on another place, where a key press
        is typing."""
        if self.screen != "Keys" or getattr(self, "_capturing", None):
            return
        if self.parts.get("board") is None:
            return
        try:
            vk = int(getattr(event, "keycode", 0) or 0)
        except (TypeError, ValueError):
            return
        cap = keyboard_mod.cap_for_vk(vk)
        if cap is not None:
            self._cap_clicked(cap)

    def _cap_clicked(self, cap_id: str | None) -> None:
        """A cap on the board. Which binding is that, and can it be
        changed here?

        A cap with exactly one binding on it goes straight to the rebind
        dialog. A cap with two (F8 is translate bare and look up with
        ctrl) cannot: the panel names both and the row below is how you
        pick which one to change — guessing would rebind the wrong one
        half the time.
        """
        self._cap_selected = cap_id
        board = self.parts.get("board")
        if board is not None:
            board.pick(cap_id)
        self._paint_rebind()

    def _paint_rebind(self) -> None:
        """The panel beside the board: what the selected cap does now,
        and the way to change it."""
        p = self.parts
        body = p.get("rebind_body")
        if body is None or not body.winfo_exists():
            return
        for child in body.winfo_children():
            child.destroy()
        width = p.get("rebind_w", 240)
        # WRAPLENGTH IS THE TEXT, NOT THE WIDGET. A tk.Label asks for six
        # pixels more than the line it wraps to — one of padx and two of
        # border on each side — so `wraplength=width` inside a body
        # exactly `width` wide is a widget 6 px too big for it, and a
        # packed child too big for its parent is cut, not shrunk.
        # Measured 2026-09-07: 281 px of a 279 px panel.
        wrap = width - 6
        tk.Label(body, text="T H I S   K E Y", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).pack(anchor="w")

        keys = self.status.get("keys") or self._read_keys()
        labels = dict(config_mod.HOTKEY_FIELDS)
        cap_id = self._cap_selected
        # `in caps_for`, not `== cap_for`: the keypad's Enter is VK_RETURN
        # exactly like the main one, so a binding on `enter` belongs to
        # both caps and the board lights both.
        on_it = [(field, raw) for field, raw in keys.items()
                 if field in labels and raw
                 and cap_id in keyboard_mod.caps_for(raw)] if cap_id else []

        # WHILE IT IS LISTENING, THE PANEL IS ABOUT THAT AND NOTHING
        # ELSE. The card used to be packed after everything, and on a cap
        # carrying TWO bindings (F8 is translate bare and look up with
        # ctrl) the panel's fixed height was already full — so the one
        # thing that says "the app is waiting for you to press a key" was
        # the one thing clipped out of it (photographed 2026-09-07). It
        # goes first now, and the bindings it is NOT listening for step
        # aside: offering to change the other one mid-capture is an
        # offer that cannot be taken.
        if getattr(self, "_capturing", None):
            self._listening_card(body, min(width, 240))
            on_it = [pair for pair in on_it if pair[0] == self._capturing]
            if not on_it:
                return

        if cap_id is None:
            tk.Label(body, bg=ui.CARD, fg=ui.DIM, font=(ui.UI, 10),
                     wraplength=wrap, justify="left",
                     text="Press a key, or click one on the board, to see "
                          "what it does — and to change it."
                     ).pack(anchor="w", pady=(14, 0))
        elif not on_it:
            name = cap_title(cap_id)
            tk.Label(body, text=name, bg=ui.CARD, fg=ui.FG,
                     font=(ui.DISPLAY, 15, "bold")).pack(anchor="w",
                                                         pady=(12, 0))
            tk.Label(body, bg=ui.CARD, fg=ui.DIM, font=(ui.UI, 9),
                     wraplength=wrap, justify="left",
                     text=f"{name} is yours — the app never "
                          "takes it. Pick a binding below and press "
                          "this key when it asks."
                     ).pack(anchor="w", pady=(6, 0))
        else:
            for field, raw in on_it:
                head = tk.Frame(body, bg=ui.CARD)
                head.pack(anchor="w", pady=(12, 0), fill="x")
                shown = pretty_key(raw)
                cap_w = max(58, 34 + ui.text_width(shown, ui.UI, 10))
                ui.KeyCap(head, shown, bg=ui.CARD, w=cap_w,
                          h=32).pack(side="left")
                words = tk.Frame(head, bg=ui.CARD)
                words.pack(side="left", padx=(12, 0))
                what, how = split_label(labels[field])
                # IT WRAPS. The cap and the name beside it are 295 px for
                # "Ctrl+Alt+M  Dismiss the notification" and the panel's
                # body is 279 — measured 2026-09-07 — and a packed label
                # wider than its parent is not shrunk, it is cut at the
                # parent's edge. A wraplength turns a name too long for
                # the column into two lines instead of half a word.
                tk.Label(words, text=what, bg=ui.CARD, fg=ui.FG,
                         font=(ui.UI, 11, "bold"), justify="left",
                         wraplength=max(80, wrap - cap_w - 12)
                         ).pack(anchor="w")
                tk.Label(words, bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 9),
                         text=f"{how or 'tap'}   ·   "
                              f"{'chord' if '+' in raw else 'bare key'}"
                         ).pack(anchor="w")
                said = KEY_NOTES.get(field) if not self._capturing else None
                if said:
                    tk.Label(body, text=said[1], bg=ui.CARD, fg=ui.DIM,
                             font=(ui.UI, 9), wraplength=wrap,
                             justify="left").pack(anchor="w", pady=(8, 0))
                # ONE gold thing on a surface. With two bindings on one
                # cap neither of them is "the" action, so both go quiet
                # and the line under them says to pick — and while the
                # app is already listening the lit card is the gold
                # thing, so the button that opened it steps back.
                make = (widgets.gold_button
                        if len(on_it) == 1 and not self._capturing
                        else _quiet_button)
                make(body, "Change this key",
                     lambda f=field, la=labels[field]: self._capture(f, la),
                     bg=ui.CARD, w=min(width, 178), h=32).pack(anchor="w",
                                                               pady=(10, 0))
            if len(on_it) > 1:
                tk.Label(body, bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8),
                         wraplength=wrap, justify="left",
                         text="Two bindings on this key — the bare one and "
                              "the one with a modifier. Change whichever "
                              "you meant."
                         ).pack(anchor="w", pady=(10, 0))
        if cap_id in keyboard_mod.KEYPAD_NUMLOCK:
            # The one thing a picture of a keypad cannot say for itself.
            tk.Label(body, bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8),
                     wraplength=wrap, justify="left",
                     text="On the keypad, and Windows only sends it while "
                          "Num Lock is ON. With Num Lock off the same cap "
                          "sends the navigation key printed beside the "
                          "digit."
                     ).pack(anchor="w", pady=(10, 0))

    def _listening_card(self, body, width: int) -> None:
        """The panel's own copy of what the key dialog is saying: the
        board says "press the key you want" at the same moment it does."""
        labels = dict(config_mod.HOTKEY_FIELDS)
        what = split_label(labels.get(self._capturing, ""))[0]
        face = getattr(ui, "ACCENT_SOFT", ui.CARD_HI)
        lit = ui.Card(body, width, 72, fill=face, bg=ui.CARD,
                      border=ui.ACCENT, pad=10)
        lit.pack(anchor="w", pady=(12, 2))
        tk.Label(lit.body, text="press the key you want", bg=face,
                 fg=getattr(ui, "ACCENT_TEXT", ui.ACCENT),
                 font=(ui.UI, 11, "bold")).pack()
        tk.Label(lit.body, text=f"listening for {what.lower()}  |",
                 bg=face, fg=ui.DIM, font=(ui.UI, 9)).pack()

    def _paint_keys(self) -> None:
        caps = self.parts.get("caps")
        if not caps:
            return
        keys = self.status.get("keys") or self._read_keys()
        for field, cap in caps.items():
            if cap.winfo_exists():
                cap.set(pretty_key(keys.get(field, "")))
        board = self.parts.get("board")
        if board is not None and board.winfo_exists():
            try:
                lit, _unmapped = keyboard_mod.bindings(keys)
            except Exception:             # noqa: BLE001
                return
            board.relight(lit)

    # ----------------------------------------------------------- settings

    def _screen_settings(self) -> None:
        """The forty-odd lines of defaults.toml a person changes, on
        eight tabs, each said in plain words.

        settings.py reads the file for the values, the choices and the
        help; settings.TABS says which lines are drawn at all, with what
        label, what sentence and what names on the menu — and every
        other line of the file is a measurement the developer edits in
        the file (the owner, 2026-09-18: "I am the user; you are the
        developer"). LAYOUT below says what each tab draws and in what
        order, cards and rows together: General is this computer and
        this screen, Dictation is the words, Screen is the pictures,
        Messages & sounds is what other programs say here, and Account,
        Privacy and About are their own pages (2026-09-22, the owner:
        "either put them all in General, or make more tabs at the top").
        A test holds every drawn line to being named by exactly one
        tab.

        Writes go through config.set_values, the line editor that keeps
        the comments, and through the running app when there is one, so
        config.toml has one writer at a time and the app can take the
        change live where it knows how (main.set_option).
        """
        self._title("Settings", "written to settings.toml — only what you changed")
        self._row_w = CW
        p = self.parts
        try:
            sections = settings_mod.read(
                DEFAULTS_PATH,
                overrides=config_mod.read_settings(paths.SETTINGS_FILE)
                | config_mod.read_state(paths.STATE_FILE))
        except Exception as e:
            card = ui.Card(self.sheet, CW, 96, pad=18, bg=ui.BG)
            card.place(x=PAD, y=64)
            tk.Label(card.body, text="SETTINGS UNAVAILABLE", bg=ui.CARD,
                     fg=ui.FAINT, font=(ui.UI, 8)).place(x=0, y=0)
            tk.Label(card.body, text=str(e)[:300], bg=ui.CARD, fg=ui.DIM,
                     font=(ui.UI, 9), wraplength=CW - 72,
                     justify="left").place(x=0, y=24)
            return
        p["sections"] = sections
        p["rows"] = {}       # path -> [(control kind, widget), ...]
        p["values"] = {}     # path -> what the file holds now
        self._settings_searching = False
        self._settings_query = ""
        # TALL ENOUGH FOR WHAT IS IN IT. ui.Chip is ui.PILL_H (36) and
        # the strip was 36 with 3 px of air above and below each chip, so
        # every tab was squashed to 30; the search field that replaces
        # them had an 18 px body for a 25 px line. Both measured
        # 2026-09-07.
        bar = tk.Frame(self.sheet, bg=ui.BG, width=CW, height=TAB_BAR_H)
        bar.place(x=PAD, y=64)
        bar.pack_propagate(False)
        p["settings_bar"] = bar
        p["settings_list"] = ui.Scroller(self.sheet, CW + 10,
                                         H - TOP - 118 - 20, bg=ui.BG)
        p["settings_list"].place(x=PAD, y=118)
        self._settings_bar()
        self._fill_settings()

    def _settings_bar(self) -> None:
        """The tabs and the magnifier — or, while searching, the field and
        the cross that brings the tabs back."""
        p = self.parts
        bar = p.get("settings_bar")
        if bar is None:
            return
        for child in bar.winfo_children():
            child.destroy()
        if self._settings_searching:
            # The same rounded box the rows use, at the width of the tab
            # strip it replaces. It used to be a ui.Card with a bare Entry
            # placed on it, which is the square-box complaint again, in
            # the one place the eye lands first.
            box = ui.Field(bar, self._settings_query, w=CW, h=FIELD_H,
                           radius=11, bg=ui.BG, justify="left",
                           icon=ui.ICON["search"], pad=14, right=30,
                           placeholder="a word from a setting's name, its "
                                       "sentence or the file's own comment "
                                       "— Esc brings the tabs back")
            box.pack()
            box.bind_entry("<KeyRelease>",
                           lambda _e: self._settings_search_soon(box.get()))
            box.bind_entry("<Escape>",
                           lambda _e: self._settings_close_search())
            p["settings_search"] = box
            cross = box.create_text(CW - 16, FIELD_H / 2, text="✕",
                                    anchor="e", fill=ui.DIM,
                                    font=(ui.UI, 10), tags="cross")
            box.tag_bind("cross", "<Button-1>",
                         lambda _e: self._settings_close_search())
            box.tag_bind("cross", "<Enter>",
                         lambda _e: box.itemconfig(cross, fill=ui.FG))
            box.tag_bind("cross", "<Leave>",
                         lambda _e: box.itemconfig(cross, fill=ui.DIM))
            box.take_focus()
            return
        p["settings_tabs"] = {}
        for name in settings_mod.tab_names():
            chip = ui.Chip(bar, name, lambda n=name: self._settings_go(n),
                           active=(name == self._settings_tab), bg=ui.BG)
            chip.pack(side="left", padx=(0, 6), pady=3)
            p["settings_tabs"][name] = chip
        glass = tk.Label(bar, text=ui.ICON["search"], bg=ui.BG, fg=ui.DIM,
                         font=(ui.ICONS, 12), cursor="hand2")
        glass.pack(side="right", padx=(0, 10))
        glass.bind("<Button-1>", lambda _e: self._settings_open_search())
        glass.bind("<Enter>", lambda _e: glass.configure(fg=ui.FG))
        glass.bind("<Leave>", lambda _e: glass.configure(fg=ui.DIM))
        p["settings_glass"] = glass

    def _settings_go(self, name: str) -> None:
        """Another tab. The values cache stays, so a switch flipped on
        Common is already flipped where the same line is drawn again.

        Under the cover (_held): the lit chip and the tab's first
        screenful of cards change in one step. Before, the list was
        cleared and the cards built one per 16 ms tick in the open — the
        census counted 3-7 half-built frames per tab over 50-80 ms."""
        def rebuild() -> None:
            self._settings_tab = name
            for tab_name, chip in (self.parts.get("settings_tabs")
                                   or {}).items():
                chip.set(tab_name == name)
            self._fill_settings()
        self._held(rebuild)

    def _settings_open_search(self) -> None:
        def rebuild() -> None:
            self._settings_searching = True
            self._settings_query = ""
            self._settings_bar()
            self._fill_settings()
        self._held(rebuild)

    def _settings_close_search(self) -> None:
        def rebuild() -> None:
            self._settings_searching = False
            self._settings_query = ""
            self._settings_bar()
            self._fill_settings()
        self._held(rebuild)

    def _settings_first_view(self) -> None:
        """Build the queued Settings cards until the list's first
        screenful is full — before a reveal, so the tab arrives with its
        viewport finished. The rest stay one per tick, below the fold."""
        scroller = self.parts.get("settings_list")
        if scroller is None or not self._settings_left:
            return
        try:
            view = int(scroller.canvas.cget("height"))
        except Exception:                 # noqa: BLE001
            return
        while self._settings_left:
            scroller.inner.update_idletasks()
            if scroller.inner.winfo_reqheight() >= view:
                break
            self._settings_left.pop(0)()

    def _fill_settings(self) -> None:
        """The cards for the tab that is up — or, while searching, every
        drawn line that matches, tab by tab.

        The first card is built here and the rest one per tick, the way
        the History screen draws its rows: seventeen cards of real
        widgets cost ~1 s on this machine (measured 2026-09-01, after the
        text had already been moved off widgets and onto the canvas), and
        a window that does nothing for a second after a click reads as a
        window that did not hear it. Switching screens mid-build cancels
        the rest — _stop_rows clears the queue.
        """
        p = self.parts
        scroller = p.get("settings_list")
        # The raw switch redraws on the next idle turn, by which time the
        # screen may have been left — its scroller is then a destroyed
        # widget still sitting in `parts`.
        if scroller is None or not scroller.winfo_exists():
            return
        self._stop_rows()
        scroller.clear()
        p["rows"] = {}
        sections = p["sections"]
        builders: list = []
        if self._settings_searching:
            # What it finds is what the tabs draw, one card per tab,
            # titled with the tab's name so the answer says where the
            # line lives. The dot's corner is drawn by its block on
            # General, so a search draws it as a plain row.
            query = self._settings_query
            for name in settings_mod.tab_names():
                pairs = [(row, s) for group in settings_mod.groups_for(name)
                         for row in group.rows
                         if (s := settings_mod.find(sections, row.path))
                         is not None
                         and settings_mod.matches(s, query)]
                if pairs:
                    builders.append(lambda t=name.upper(), pr=pairs:
                                    self._friendly_card(scroller, t, pr))
        else:
            # A TAB IS AN ORDERED PAGE, not blocks-then-rows. LAYOUT
            # names what the tab draws in the order it draws it: a name
            # in capitals is one of settings.TABS' groups, anything else
            # is a card (_settings_block). That is what lets the updates
            # card sit between "This computer" and Awake on General
            # rather than above both of them.
            name = self._settings_tab
            groups = {g.title: g for g in settings_mod.groups_for(name)}
            for entry in self.LAYOUT.get(name, ()):
                if not entry.isupper():
                    builders.append(lambda e=entry:
                                    self._settings_block(e, scroller))
                    continue
                group = groups.get(entry)
                if group is None:
                    continue
                pairs = [(row, s) for row in group.rows
                         if (s := settings_mod.find(sections, row.path))
                         is not None
                         and s.path not in self._block_paths(name)]
                if pairs:
                    builders.append(lambda g=group, pr=pairs:
                                    self._friendly_card(scroller, g.title,
                                                        pr))
        if not builders:
            card = ui.Card(scroller.inner, CW, 60, pad=18, bg=ui.BG)
            card.pack(anchor="w", pady=(0, 14))
            tk.Label(card.body, text=f"no setting matches "
                                     f"{self._settings_query!r}",
                     bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 9)).place(x=0, y=2)
            return
        self._settings_left = builders
        self._draw_settings()
        scroller.to_top()

    # WHAT EACH TAB DRAWS, IN ORDER. A name in capitals is a group of
    # settings.TABS, drawn as a card of rows; anything else is a card
    # of its own, built by _settings_block. Eight tabs since 2026-09-22
    # (the owner: "it is really hard to understand where each thing is
    # … either put them all in General, or make more tabs at the top"):
    # General is this computer and this screen, Dictation is the words,
    # and About is the end of the road — see the table in settings.py
    # for what fifty other apps do with the same list.
    LAYOUT: dict[str, tuple[str, ...]] = {
        settings_mod.GENERAL: ("dot", "ON THE SCREEN", "THIS COMPUTER",
                               "WHERE FILES ARE SAVED", "updates", "awake"),
        settings_mod.DICTATION: ("WHERE YOUR SPEECH BECOMES WORDS", "model",
                                 "WHEN YOU DICTATE", "WORDS IT LEARNS",
                                 "THE TRANSLATE KEY"),
        settings_mod.SCREEN: ("recording", "SCREENSHOTS AND RECORDINGS",
                              "snip", "THE CAMERA", "ASK ABOUT THE SCREEN",
                              "voice"),
        settings_mod.MESSAGES: ("MESSAGES FROM OTHER PROGRAMS", "claude",
                                "sounds"),
        settings_mod.PHONE: ("phone", "DICTATING FROM THE PHONE"),
        settings_mod.ACCOUNT: ("account", "WHAT THE ACCOUNT MAY DO", "lock"),
        settings_mod.PRIVACY: ("keys", "WHAT MAY LEAVE THIS PC",
                               "connections", "said_file", "KEPT ON THIS PC"),
        settings_mod.ABOUT: ("version", "about", "files"),
    }

    # What a block ABOVE the rows already draws for itself, per tab, so
    # the rows below it do not draw it a second time. The one rule of
    # this screen is that every line of config.toml is reachable exactly
    # once, and a block is another way of drawing a line, not an
    # exception to it: `dot.corner` is a real settings row with a real
    # menu, registered in parts["rows"] like any other — it is simply
    # drawn beside the button that goes with it instead of ten rows above
    # it, and `privacy.update_check` sits on the updates card the same
    # way. `_keys_screen_paths` is the same idea for another SCREEN.
    BLOCK_PATHS: dict[str, frozenset] = {
        settings_mod.GENERAL: frozenset({"dot.corner",
                                         "privacy.update_check"}),
    }

    def _settings_block(self, key: str, scroller) -> None:
        """One card of a tab, by the name LAYOUT gives it. The three
        that do not take the scroller alone are spelled out; the rest
        are `_<key>_block`."""
        if key == "snip":
            self._snip_block(scroller, self.parts["sections"])
        elif key == "voice":
            if hardware_mod.no_voice():
                self._voice_block(scroller)
        elif key == "about":
            self._about_card(scroller)
        elif key == "files":
            self._files_card(scroller)
        else:
            getattr(self, f"_{key}_block")(scroller)

    def _block_paths(self, tab: str) -> frozenset:
        return self.BLOCK_PATHS.get(tab, frozenset())

    def _draw_settings(self) -> None:
        """One card per tick, until the queue is empty."""
        self._settings_tick = None
        if self.closing or "settings_list" not in self.parts \
                or not self._settings_left:
            return
        build = self._settings_left.pop(0)
        build()
        if self._settings_left:
            self._settings_tick = self.root.after(16, self._draw_settings)

    def _finish_settings(self) -> None:
        """Build whatever is still queued, now. For a test, or anything
        else that wants the whole screen rather than the first frame."""
        while self._settings_left:
            self._settings_left.pop(0)()
        if self._settings_tick is not None:
            try:
                self.root.after_cancel(self._settings_tick)
            except Exception:
                pass
            self._settings_tick = None

    # -- the cards

    def _new_card(self, scroller, height: int, before=None):
        """A card drawn as canvas ITEMS rather than widgets.

        A hundred and forty rows of two or three Labels each is four
        hundred widgets, and Tk on Windows spent 2.2 s creating them —
        measured 2026-09-01, and it made the screen feel broken. A text
        item on the card's own canvas costs one Tcl call and no window.
        Only the controls are real widgets, put on the canvas with
        create_window, so the count is one per row rather than three.
        """
        card = tk.Canvas(scroller.inner, width=CW, height=height, bg=ui.BG,
                         highlightthickness=0, bd=0)
        card.create_image(0, 0, anchor="nw",
                          image=ui.rounded(CW, height, 14, ui.CARD, ui.BG,
                                           ui.LINE))
        # `before` is how a fold opens IN PLACE: a Canvas cannot grow with
        # rows already drawn on it, so the card is drawn again, taller,
        # and packed in front of whatever followed the old one.
        if before is None:
            card.pack(anchor="w", pady=(0, 14))
        else:
            card.pack(anchor="w", pady=(0, 14), before=before)
        return card

    def _friendly_help(self, row) -> tuple[str, int]:
        if not row.help:
            return "", 0
        return ui.clamp(row.help, ui.UI, 8, CW - 36 - CONTROL_W - 12, 2)

    def _friendly_card(self, scroller, title: str, pairs, *,
                       before=None) -> None:
        """One group's card: a plain title, and under it every row the
        tab names — a label, one sentence, and its control."""
        pairs = list(pairs)
        heights = [22 + self._friendly_help(row)[1] * 15 + 8
                   for row, _setting in pairs]
        y = 18 if title else 8
        card = self._new_card(scroller, y + 18 * bool(title) + sum(heights)
                              + (6 if title else 10), before=before)
        if title:
            card.create_text(18, y, text=title, anchor="nw", fill=ui.FAINT,
                             font=(ui.UI, 8))
            y += 18
        for (row, setting), height in zip(pairs, heights):
            card.create_text(18, y, text=row.label, anchor="nw", fill=ui.FG,
                             font=(ui.UI, 10))
            text, lines = self._friendly_help(row)
            if lines:
                card.create_text(18, y + 21, text=text, anchor="nw",
                                 fill=ui.FAINT, font=(ui.UI, 8))
            self._control(card, y, setting, self._menu_for(row, setting))
            y += height
        scroller.bind_wheel(card)


    def _microphones(self) -> list:
        """(what the file writes, a name) for every input device, the way
        the first-run setup lists them. Asked once per visit.

        The value is firstrun.device_key — the microphone's NAME and host
        API, never its index. The rows read exactly as they did; what
        changed on 2026-09-05 is what lands in config.toml, after an index
        written by this menu stopped pointing at a microphone at all and
        the app would not start.
        """
        p = self.parts
        if "mics" not in p:
            try:
                import firstrun
                devices = firstrun._devices()
            except Exception:
                devices = []
            p["mics"] = ([("", "System default")]
                         + [(key, f"{name} — {api}")
                            for key, name, api, _index in devices])
        return list(p["mics"])

    def _menu_for(self, row, setting) -> list:
        """(value, label) for a row's menu: the microphones on this
        machine for the microphone, the names the words give it, or the
        file's own choices. [] = a field."""
        if setting.path == "audio.device":
            mics = self._microphones()
            if len(mics) > 1:
                # A config still holding a bare index would match no row
                # and the menu would show a number where a microphone
                # belongs. Translate it once, so the row the file means is
                # the row that reads as chosen.
                values = self.parts.setdefault("values", {})
                held = str(values.setdefault(setting.path,
                                             setting.value) or "")
                if held.isdigit():
                    import firstrun
                    for key, _name, _api, index in firstrun._devices():
                        if str(index) == held:
                            values[setting.path] = key
                            break
                return mics
        names = list(row.names) if row is not None and row.names \
            else [(c, c) for c in setting.choices]
        # 6.7: no Ollama on this PC, no "On this computer" on the menu —
        # unless it is the value the file holds, which a menu must be
        # able to show. The checkout keeps every entry.
        if hardware_mod.ollama_absent():
            held = str(self.parts.get("values", {}).get(setting.path, setting.value))
            names = [(v, n) for v, n in names if v != "ollama" or held == "ollama"]
        return names

    def _control(self, card, y: int, setting, options) -> None:
        """The one control a line calls for, on the right of its row. A
        list, and a Hebrew string, get a button to the file instead — the
        line editor writes scalars, and Tk cannot edit Hebrew (ui.py)."""
        p = self.parts
        right = CW - 18
        value = p["values"].setdefault(setting.path, setting.value)
        if getattr(setting, "consent", False):
            # A gate: never a switch. What it shows is the consent row —
            # granted when, for which words — and the one button that may
            # close it. It opens only through its card (D7).
            self._draw_consent_row(card, setting, right, y)
        elif setting.kind == "bool":
            switch = ui.Switch(card, bool(value),
                               command=lambda v, s=setting:
                               self._apply_setting(s, v), bg=ui.CARD)
            card.create_window(right, y + 1, window=switch, anchor="ne")
            self._register_row(setting, "switch", switch)
        elif not setting.editable:
            button = ui.Button(card, "In the file",
                               lambda: launch.open_path(paths.SETTINGS_FILE),
                               w=widgets.button_width("In the file",
                                                      icon=True),
                               h=30, quiet=True,
                               icon=ui.ICON["settings"])
            card.create_window(right, y - 2, window=button, anchor="ne")
            self._register_row(setting, "file", button)
        elif options:
            # A name wider than the menu is CUT, with an ellipsis, rather
            # than cut silently at the menu's edge: a Windows device name
            # is 390 px and the box is not (measured 2026-09-07).
            pt = getattr(ui, "PT_BODY", 12)
            options = [(v, widgets.fit(str(n), ui.UI, pt,
                                       CONTROL_W - DROP_ROOM))
                       for v, n in options]
            menu = ui.Dropdown(card, options, value,
                               command=lambda v, s=setting:
                               self._apply_setting(s, v),
                               bg=ui.CARD, w=CONTROL_W)
            card.create_window(right, y - 2, window=menu, anchor="ne")
            self._register_row(setting, "dropdown", menu)
        else:
            # ui.Field, not a bare tk.Entry: an Entry is a hard rectangle
            # with a one-pixel highlight, and it was the only square thing
            # left in a window of rounded faces. ui.Field says the rest,
            # including why its disabled colours are set.
            # A folder gets a picker too: the field for the path as it
            # stands, [Browse…] for the dialog that walks the disk.
            folder = setting.path in FOLDER_SETTINGS
            x = right
            if folder:
                browse = ui.Button(card, "Browse…",
                                   lambda s=setting: self._browse_folder(s),
                                   w=BROWSE_W, h=ENTRY_H, quiet=True, bg=ui.CARD)
                card.create_window(right, y - 1, window=browse, anchor="ne")
                self.parts.setdefault("browse", {})[setting.path] = browse
                x = right - BROWSE_W - 8
            field = ui.Field(card, _shown(value),
                             w=ENTRY_W + (60 if folder else 0), h=ENTRY_H,
                             bg=ui.CARD)
            card.create_window(x, y - 1, window=field, anchor="ne")
            field.bind_entry("<Return>", lambda _e, s=setting, f=field:
                             self._entry_done(s, f))
            field.bind_entry("<FocusOut>", lambda _e, s=setting, f=field:
                             self._entry_done(s, f))
            self._register_row(setting, "entry", field)

    def _register_row(self, setting, kind: str, widget) -> None:
        self.parts["rows"].setdefault(setting.path, []).append((kind, widget))

    def _draw_consent_row(self, card, setting, right: int, y: int) -> None:
        """One of the [privacy] gates: what the consent file says —
        open since when, for which words, stale, or never granted — and
        a Withdraw button while it is open. No switch: it opens only
        through its card, the first time a feature needs it (D7). The
        two syncs have no first use of their own — the sign-in and the
        wizard's switch grant them — so a shut sync row carries [Turn
        on], which asks the running app for that card (the Account
        card's "Sync now" did this for both until 2026-09-20)."""
        import privacy

        kind = setting.key
        try:
            row = next(s for s in privacy.status() if s["kind"] == kind)
        except Exception:
            row = {"open": False, "stale": False, "when": "", "gate": False}
        if row["open"]:
            when = str(row.get("when", ""))[:10]
            text, colour = f"On since {when}", ui.FG
        elif row.get("stale"):
            text, colour = "Its words changed — Home asks again", ui.FAINT
        elif row.get("when"):
            text, colour = "Off", ui.FAINT
        else:
            text, colour = "Off — its card opens on first use", ui.FAINT
        x = right
        if row["open"]:
            button = ui.Button(card, "Withdraw",
                               lambda k=kind, s=setting: self._withdraw(k, s),
                               w=widgets.button_width("Withdraw"), h=30,
                               quiet=True)
            card.create_window(right, y - 2, window=button, anchor="ne")
            x = right - widgets.button_width("Withdraw") - 12
        elif kind in privacy.SYNC_KINDS:
            button = ui.Button(card, "Turn on",
                               lambda k=kind: self._account_do("sync", "asking", kind=k),
                               w=widgets.button_width("Turn on"), h=30,
                               quiet=True)
            card.create_window(right, y - 2, window=button, anchor="ne")
            x = right - widgets.button_width("Turn on") - 12
        elif row.get("stale"):
            # The same yes Home's row gives (_consent_do), here too.
            button = ui.Button(card, "Turn on",
                               lambda k=kind, s=setting: self._turn_on(k, s),
                               w=widgets.button_width("Turn on"), h=30,
                               quiet=True)
            card.create_window(right, y - 2, window=button, anchor="ne")
            x = right - widgets.button_width("Turn on") - 12
        # The text is the row's one control — registered so the page
        # counts it like any other line (one widget per line, a test
        # holds), and so a repaint can find it.
        item = card.create_text(x, y + 13, text=text, anchor="e",
                                font=(ui.UI, 10), fill=colour)
        self._register_row(setting, "consent", (card, item))

    def _turn_on(self, kind: str, setting) -> None:
        """Settings > Privacy > Turn on on a row whose words changed: the
        yes Home's row gives (_consent_do), then this page redrawn."""
        self._consent_do(kind, True)
        self.parts["values"][setting.path] = True
        self._note(f"{kind}: on — from the next press")
        self._draw_settings()

    def _withdraw(self, kind: str, setting) -> None:
        """Settings > Privacy > Withdraw. privacy.withdraw writes the
        consent file and mirrors the key; the running app notices the
        row is gone on its next gate check (privacy.rows) and net.py
        refuses the next request either way — no pipe message needed."""
        import privacy

        try:
            privacy.withdraw(kind)
        except Exception as e:
            self._note(str(e))
            return
        self.parts["values"][setting.path] = False
        self._note(f"{kind}: withdrawn — the local path answers from the "
                   f"next press; the card will ask again when a feature "
                   f"needs the cloud")
        self._draw_settings()

    # ------------------------------------------------------------- about

    PAGES_URL = paths.PAGES_URL
    ISSUES_URL = "https://github.com/DeskIT-app/DeskIT/issues/new/choose"
    MODEL_CARD_URL = "https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ct2"

    @staticmethod
    def built_with_llama() -> bool:
        """13.5: while any shipped default names a Llama model, the line
        "Built with Llama" is on the About card — the conservative
        reading of the Llama licence (D24)."""
        try:
            return any("llama" in str(v).lower()
                       for v in config_mod.defaults_flat().values())
        except Exception:                 # noqa: BLE001
            return False

    def _about_rows(self) -> list[tuple[str, object]]:
        """The papers, each a button: the files ship beside the app; the
        two Pages documents open locally in a checkout and on the web
        otherwise; the notices file is made by the build, so a checkout
        says so instead of opening nothing."""
        app = paths.APP_DIR

        def opener(name: str, missing: str):
            path = app / name
            return lambda: (launch.open_path(path) if path.exists()
                            else self._note(missing))

        def page(name: str):
            local = app / "docs" / f"{name}.md"
            return lambda: (launch.open_path(local) if local.exists()
                            else self._open_url(f"{self.PAGES_URL}/{name}"))

        return [
            ("Licence", opener("LICENSE", "LICENSE is not beside the app")),
            ("Trademark", opener("TRADEMARK.md", "TRADEMARK.md is not beside the app")),
            ("Third-party notices", opener("THIRD-PARTY-NOTICES.txt",
                                           "the notices file is written by the build; "
                                           "a checkout has dev/notices-extra.txt")),
            ("Network", opener("NETWORK.md", "NETWORK.md is not beside the app")),
            ("Privacy policy", page("privacy")),
            ("Terms", page("terms")),
            ("Report a security issue", opener("SECURITY.md", "SECURITY.md is not beside the app")),
            ("Report on GitHub", lambda: self._open_url(self.ISSUES_URL)),
            ("Copy diagnostics", self._copy_diagnostics),
        ]

    def _copy_diagnostics(self) -> None:
        import problems as problems_mod
        try:
            block = problems_mod.diagnose()
        except Exception as e:            # noqa: BLE001
            self._note(f"diagnostics failed ({e})")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(block)
        self._note("diagnostics copied — no transcripts, no keys; read it before sending")

    def _about_card(self, scroller) -> None:
        """About (chapter 9 screen 14, 13.2-13.5): the licence line, the
        model the app transcribes with, "Built with Llama" while a
        default names one, and a button for every paper."""
        rows = self._about_rows()
        # The buttons are laid out FIRST — a row breaks by width, not by
        # a count — and the card is as tall as the last of them needs.
        # It used to be 92 + a guessed row count, which put the second
        # row's lower third behind the card's edge ("swallowed", the
        # owner, 2026-09-18).
        per_row, row_h, button_h = 5, 36, 28
        places: list[tuple[int, int]] = []
        x = y = 0
        for index, (label, _command) in enumerate(rows):
            if index and index % per_row == 0:
                x, y = 0, y + row_h
            w = widgets.button_width(label)
            if x + w > CW - 36:
                x, y = 0, y + row_h
            places.append((x, 72 + y))
            x += w + 8
        height = 36 + (places[-1][1] + button_h + 8 if places else 72)
        card = ui.Card(scroller.inner, CW, height, bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="A B O U T", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)
        tk.Label(body, text=f"DeskIT {version.VERSION} · Apache License 2.0 · "
                            "Copyright 2026 Yoav Shimron",
                 bg=ui.CARD, fg=ui.FG, font=(ui.UI, 10)).place(x=0, y=22)
        # The licence line carries the version as well: this card can be
        # read on its own in a photograph of a report.
        line = ("Transcribes Hebrew with ivrit.ai's whisper-large-v3-turbo "
                "(Apache-2.0)" + (" · Built with Llama" if self.built_with_llama() else ""))
        model = tk.Label(body, text=line, bg=ui.CARD, fg=ui.DIM, font=(ui.UI, 9),
                         cursor="hand2")
        model.place(x=0, y=46)
        model.bind("<Button-1>", lambda _e: self._open_url(self.MODEL_CARD_URL))
        self.parts["about_line"] = line
        self.parts["about_buttons"] = [label for label, _c in rows]
        for (label, command), (x, y) in zip(rows, places):
            ui.Button(body, label, command, h=button_h,
                      w=widgets.button_width(label), quiet=True,
                      bg=ui.CARD).place(x=x, y=y)
        scroller.bind_wheel(card)

    def _files_card(self, scroller) -> None:
        # Named for what they ARE, not what they are called on disk — the
        # filename is the small print. "What is transcripts.log" was a
        # question this screen used to make the owner ask.
        # Everything you said left this card on 2026-09-22 for Settings >
        # Privacy, where the line that says how long it is kept already
        # was: a file and the setting that governs it belong together.
        openers = (
            ("page", "The app's diary",
             "app.log — what it did and why, for when something looks off",
             paths.APP_LOG),
            ("settings", "Your settings",
             "settings.toml — only what you changed; the help for every "
             "knob is in defaults.toml beside the app",
             paths.SETTINGS_FILE),
            ("folder", "The app's folder",
             str(paths.DATA_DIR),
             paths.DATA_DIR),
        )
        files = ui.Card(scroller.inner, CW, 60 + len(openers) * 44, pad=18,
                        bg=ui.BG)
        files.pack(anchor="w", pady=(0, 14))
        tk.Label(files.body, text="FILES", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=0, y=0)
        row = 24
        for glyph, name, hint, path in openers:
            tk.Label(files.body, text=ui.ICON[glyph], bg=ui.CARD, fg=ui.DIM,
                     font=(ui.ICONS, 11)).place(x=0, y=row + 7)
            tk.Label(files.body, text=name, bg=ui.CARD, fg=ui.FG,
                     font=(ui.UI, 10)).place(x=26, y=row + 2)
            tk.Label(files.body, text=hint, bg=ui.CARD, fg=ui.FAINT,
                     font=(ui.UI, 8)).place(x=26, y=row + 21)
            ui.Button(files.body, "Open",
                      lambda target=path: launch.open_path(target),
                      w=76, h=30, quiet=True).place(x=CW - 36 - 76,
                                                    y=row + 3)
            row += 44
        scroller.bind_wheel(files)

    @staticmethod
    def _cut_field(entry) -> None:
        """Show a too-long value cut, with an ellipsis. A no-op for every
        field whose value fits, which is all of them but one."""
        cut = getattr(entry, "_cut_to", 0)
        if not cut:
            return
        entry = getattr(entry, "entry", entry)     # a ui.Field's own Entry
        try:
            if entry.focus_get() is entry:
                return                    # the caret is in it: say it all
            whole = entry.get()
            said = widgets.fit(whole, ui.UI, 11, cut)
            if said != whole:
                entry.delete(0, "end")
                entry.insert(0, said)
        except tk.TclError:
            pass

    def _whole_field(self, entry, setting) -> None:
        """The caret arrived: put the value back as the file holds it."""
        if not getattr(entry, "_cut_to", 0):
            return
        entry = getattr(entry, "entry", entry)     # a ui.Field's own Entry
        try:
            values = self.parts.get("values") or {}
            whole = _shown(values.get(setting.path, setting.value))
            if entry.get() != whole:
                entry.delete(0, "end")
                entry.insert(0, whole)
        except tk.TclError:
            pass

    # -- the three blocks that used to be screens

    def _dot_block(self, scroller) -> None:
        """Where the status dot sits: the two corners, and the button
        that puts it anywhere else. ONE CARD, on General.

        THE OWNER'S ASK, 2026-09-07, verbatim: "the dot — I want it to be
        movable, and without needing to open and close the app. Like, put
        a marker, like a button, and then I press 'set' and then the desk
        disappears and I drag the dot wherever I want it, whenever I want
        it, wherever I want it — and without needing to open and close
        the app."

        So: Move the dot HIDES THIS WINDOW (that is "the desk
        disappears"), the disc becomes draggable in the running app, and
        this window comes back by itself the moment the drag ends — or
        when the app says it has stopped waiting, which is what happens
        if he presses the button and then changes his mind. Nothing
        restarts and nothing has to be typed into config.toml.

        AND HE COULD NOT FIND IT. 2026-09-08, having used it: "I cannot
        move the dot. Like, in the settings, I'm going to General and
        then 'which corner the dot sits' — there is only bottom right or
        top right. So please solve the problem that I cannot move the
        dot, and put like two default places, the top right and the
        bottom right, AND a button to set it wherever I want it." The
        card was on Cards and the corner menu was on General, so he
        opened the page the dot's corner was on and the button was on
        another one. That is what this card is now: his two default
        places and the button that beats them, in one row, on the page he
        opened. The menu is the real `dot.corner` settings row — the same
        widget, the same write, registered in parts["rows"] like every
        other line — so "drawn exactly once" still holds; see
        BLOCK_PATHS.

        The buttons need the RUNNING app: the dot is a window that
        process owns, and there is nothing to drag when it is not there.
        Disabled and said plainly, the way the awake block says the same
        thing about its own switch. The MENU does not: a corner written
        to config.toml with nothing running is honoured the next time it
        starts, which is what every other settings row on this screen
        does.
        """
        # 186 and not 172: ui.Card's body is `h - 2 * pad`, so the row of
        # controls at y=110 needs 142 px of body, and the sentence above
        # it has to be able to wrap onto a second line without landing on
        # the word "Corner". Measured against ui.Card's own arithmetic
        # rather than eyeballed, because this card is built on a hidden
        # desktop where nobody can see it come out short — a test walks
        # every part of it against the body it is on.
        card = ui.Card(scroller.inner, CW, 186, bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="T H E   D O T", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)
        self.parts["dot_where"] = tk.Label(
            body, text="", bg=ui.CARD, fg=ui.FG, font=(ui.DISPLAY, 15,
                                                       "bold"))
        self.parts["dot_where"].place(x=0, y=22)
        self.parts["dot_hint"] = tk.Label(
            body, text="", bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8),
            wraplength=CW - 72, justify="left", anchor="w")
        self.parts["dot_hint"].place(x=0, y=52)
        # The corner FIRST and the button beside it, in that order,
        # because that is the order he said them in: "two default places
        # ... AND a button to set it wherever I want it".
        at = 0
        setting = settings_mod.find(self.parts.get("sections") or [],
                                    "dot.corner")
        if setting is not None:
            tk.Label(body, text="Corner", bg=ui.CARD, fg=ui.FAINT,
                     font=(ui.UI, 8)).place(x=0, y=92)
            row = settings_mod.words_for(setting)
            value = self.parts["values"].setdefault(setting.path,
                                                    setting.value)
            menu = ui.Dropdown(body, self._menu_for(row, setting), value,
                               command=lambda v, s=setting:
                               self._apply_setting(s, v),
                               bg=ui.CARD, w=CONTROL_W)
            menu.place(x=0, y=110)
            self._register_row(setting, "dropdown", menu)
            self.parts["dot_corner"] = menu
            at = CONTROL_W + 12
        wide = widgets.button_width("Move the dot")
        self.parts["dot_move"] = ui.Button(body, "Move the dot",
                                           self._move_dot, w=wide, h=32,
                                           primary=True)
        self.parts["dot_move"].place(x=at, y=110)
        home = widgets.button_width("Back to the corner")
        self.parts["dot_home"] = ui.Button(body, "Back to the corner",
                                           self._dot_to_corner, w=home,
                                           h=32, quiet=True)
        self.parts["dot_home"].place(x=at + wide + 12, y=110)
        scroller.bind_wheel(card)
        self._paint_dot()

    def _paint_dot(self) -> None:
        """Say where the dot is now, and which of the two buttons is
        worth pressing. Called when the card is built and on every status
        poll while the Settings screen is up.

        The corner MENU is never disabled here — a corner written with
        nothing running is honoured at the next start, like every other
        line on this screen — and it is repainted by _paint_settings,
        which is what repaints every settings row.
        """
        p = self.parts
        if "dot_where" not in p or not p["dot_where"].winfo_exists():
            return
        info = (self.status.get("dot") or {}) if self.running else {}
        moved = bool(info.get("dragged"))
        if not self.running:
            where = "NOT RUNNING"
            said = ("The dot is a window the running app owns, so there is "
                    "nothing to drag while it is stopped. The corner is "
                    "saved either way; start dictation and the button "
                    "moves it anywhere you like.")
        elif info.get("moving"):
            where = "WAITING FOR YOU"
            said = ("Drag the disc where you want it and let go. If you "
                    "leave it, it gives up on its own and the dot goes "
                    "back to being a button.")
        elif moved:
            where = f"at {info.get('x')}, {info.get('y')}"
            said = ("Where you dropped it, and the panel opens beside it "
                    "there. Move the dot picks it up again; Back to the "
                    "corner sends it home to the "
                    f"{info.get('corner', 'bottom-right')} of your main "
                    "screen.")
        else:
            where = f"in the {info.get('corner', 'bottom-right')} corner"
            said = ("Pick either corner, or press Move the dot: this "
                    "window steps out of the way and waits for you to "
                    "drag the disc — anywhere, on any screen. Let go and "
                    "it stays there, the panel opens beside it, and it "
                    "is remembered.")
        p["dot_where"].config(text=where,
                              fg=ui.FG if self.running else ui.FAINT)
        p["dot_hint"].config(text=said)
        for name, on in (("dot_move", self.running),
                         ("dot_home", self.running and moved)):
            button = p.get(name)
            if button is not None and button.winfo_exists():
                button.enable(bool(on))

    def _move_dot(self) -> None:
        """Ask the running app to make the disc draggable. The window
        hides itself only once the app has said yes, so a refusal never
        costs him a window that vanished for nothing."""
        if not self.running:
            self._note("start dictation first — the dot belongs to the "
                       "running app")
            return
        self._ask("dot", then=self._dot_moving, do="move")

    def _dot_moving(self, reply: dict | None) -> None:
        if reply is None or not reply.get("ok"):
            self._announce(reply, "the dot would not move")
            return
        # The deadline is the app's own patience plus a little: the app
        # gives up first and its next status says so, and this is only
        # the backstop for an app that stops answering mid-drag.
        self._dot_waiting = time.monotonic() + DOT_WAIT_S
        try:
            self.root.withdraw()
        except Exception:
            self._dot_waiting = 0.0

    def _dot_to_corner(self) -> None:
        self._ask("dot", then=lambda r: self._announce(
            r, "the dot is back in its corner"), do="corner")

    def _show_tour(self) -> None:
        """Ask the running app for the tour (D36). It lives beside the
        dot, which belongs to the app — nothing to show while it is off."""
        if not self.running:
            self._note("start dictation first — the tour is shown beside "
                       "the running app's dot")
            return
        self._ask("tour", then=lambda r: self._announce(
            r, "the tour is beside the dot"))

    def _dot_returns(self) -> None:
        """Put this window back when the drag is over — or when the wait
        has been going on longer than anyone meant it to.

        Called from every status poll while `_dot_waiting` stands. The
        app stopping is the same answer as the app saying it is no longer
        waiting: either way there is nothing left to drag, and a control
        window that stayed hidden would be the worse bug of the two.
        """
        info = (self.status.get("dot") or {}) if self.running else {}
        if info.get("moving") and time.monotonic() < self._dot_waiting:
            return
        self._dot_waiting = 0.0
        self._raise_window()
        if info.get("dragged"):
            self._note(f"the dot is at {info.get('x')}, {info.get('y')} "
                       "now, and it stays there")
        else:
            self._note("the dot did not move")

    def _phone_block(self, scroller) -> None:
        """The endpoint the Android keyboard talks to. 39 dictations and
        228 notification relays came through it in ten days, announced at
        every startup, with no screen of its own until now."""
        card = ui.Card(scroller.inner, CW, 132, bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="T H E   P H O N E", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)
        url = (self.status or {}).get("phone", "")
        self.parts["phone_url"] = tk.Label(
            body, text=url or "DeskIT is not running, or the switch below "
                              "is off",
            bg=ui.CARD, fg=ui.FG if url else ui.DIM,
            font=(ui.UI, 12 if url else 10))
        self.parts["phone_url"].place(x=0, y=24)
        tk.Label(body, bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8),
                 wraplength=CW - 200, justify="left",
                 text="Put the DeskIT keyboard on your phone, give it this "
                      "address once, and the phone dictates into this "
                      "computer over your own private network. It is also "
                      "how a message from another program reaches this "
                      "desk."
                 ).place(x=0, y=54)
        ui.Button(body, "Copy link", self._copy_phone, h=32, quiet=True,
                  w=widgets.button_width("Copy link", icon=True),
                  icon=ui.ICON["link"]).place(x=CW - 36, y=20, anchor="ne")
        scroller.bind_wheel(card)

    # --------------------------------------------------- your cloud keys

    KEY_PROVIDERS = (("groq", "Groq", "https://console.groq.com",
                      "recommended first: one key unlocks the repair pass, punctuation, "
                      "lookup and, without an NVIDIA card, cloud transcription"),
                     ("gemini", "Gemini", "https://aistudio.google.com",
                      "for translation and ask-the-screen"))

    def _keys_block(self, scroller) -> None:
        """YOUR CLOUD KEYS on Settings > Privacy (chapter 9 screen 3, D10-
        D12): a row per provider — a masked field that takes a paste and
        never shows the value again, [Save and test] (the key into
        Windows Credential Manager through secretstore, then one
        `key-test` call through net.py that lists the provider's models),
        [Remove] — and under each the fixed storage sentence the guide
        quotes. The gates on the rows below open only through their
        cards; a key is what lets a card's [Turn on] mean anything."""
        import secretstore
        present = {}
        try:
            present = secretstore.present()
        except Exception:                 # noqa: BLE001
            pass
        # Each provider is as tall as its storage sentence wraps to —
        # two lines of the small face at this width — plus the row above
        # it; a flat 132 per provider left the last sentence's second
        # line behind the card's edge ("swallowed", the owner, 2026-09-18).
        sentences = {name: ui.clamp(secretstore.storage_sentence(name),
                                    ui.UI, 8, CW - 40, 3)
                     for name, _l, _u, _w in self.KEY_PROVIDERS}
        heights = {name: 82 + lines * LINE + 14
                   for name, (_text, lines) in sentences.items()}
        card = ui.Card(scroller.inner, CW, 36 + 24 + sum(heights.values()),
                       bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="Y O U R   C L O U D   K E Y S", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)
        self.parts["key_fields"] = {}
        self.parts["key_lines"] = {}
        y = 24
        for name, label, url, why in self.KEY_PROVIDERS:
            tk.Label(body, text=label, bg=ui.CARD, fg=ui.FG,
                     font=(ui.UI, 11, "bold")).place(x=0, y=y)
            link = tk.Label(body, text="Get a free key", bg=ui.CARD, fg=ui.ACCENT_TEXT,
                            font=(ui.UI, 9, "underline"), cursor="hand2")
            link.place(x=80, y=y + 2)
            link.bind("<Button-1>", lambda _e, u=url: self._open_url(u))
            tk.Label(body, text=why, bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8),
                     wraplength=CW - 360, justify="left").place(x=190, y=y + 2)
            field = ui.Field(body, "", w=320, h=30, justify="left",
                             placeholder="paste the key here", bg=ui.CARD, pt=10)
            field.entry.configure(show="•")
            field.place(x=0, y=y + 28)
            self.parts["key_fields"][name] = field
            x = 332
            for text, command in (("Save and test", lambda n=name: self._key_save(n)),
                                  ("Remove", lambda n=name: self._key_remove(n))):
                w = widgets.button_width(text)
                ui.Button(body, text, command, h=30, w=w, quiet=True,
                          bg=ui.CARD).place(x=x, y=y + 28)
                x += w + 8
            stored = name in present
            line = tk.Label(body, text=(f"Stored in {present[name]}" if stored
                                        else "no key"),
                            bg=ui.CARD, fg=ui.FG if stored else ui.FAINT,
                            font=(ui.UI, 9), anchor="w")
            line.place(x=0, y=y + 64)
            self.parts["key_lines"][name] = line
            tk.Label(body, text=sentences[name][0], bg=ui.CARD,
                     fg=ui.FAINT, font=(ui.UI, 8),
                     justify="left").place(x=0, y=y + 82)
            y += heights[name]
        scroller.bind_wheel(card)

    # ------------------------------------------- every connection (D12's window)

    def _connections_block(self, scroller) -> None:
        """EVERY CONNECTION on Settings > Privacy: the door to the Network
        screen since it left the bar (2026-09-18, "as a user I don't
        understand why I need it"). One line — today's requests, and the
        sentence that is the proof — and two buttons: the screen, the
        file. The count follows network.log on every poll
        (_paint_connections), only re-read when the file moved."""
        card = ui.Card(scroller.inner, CW, 118, bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="E V E R Y   C O N N E C T I O N", bg=ui.CARD,
                 fg=ui.FAINT, font=(ui.MEDIUM, 8)).place(x=0, y=0)
        line = tk.Label(body, text="", bg=ui.CARD, fg=ui.FG, font=(ui.UI, 10),
                        wraplength=CW - 60, justify="left", anchor="w")
        line.place(x=0, y=22)
        x = 0
        for text, command in (("Open the Network screen",
                               lambda: self._show("Network")),
                              ("Open the log file", self._net_open_log)):
            w = widgets.button_width(text)
            ui.Button(body, text, command, h=30, w=w, quiet=True,
                      bg=ui.CARD).place(x=x, y=52)
            x += w + 8
        self.parts["connections_line"] = line
        self._connections_seen = None
        self._paint_connections()
        scroller.bind_wheel(card)

    def _paint_connections(self) -> None:
        line = self.parts.get("connections_line")
        if line is None or not line.winfo_exists():
            return
        try:
            stamp = paths.NETWORK_LOG.stat().st_mtime_ns
        except OSError:
            stamp = None
        if stamp == getattr(self, "_connections_seen", None):
            return
        self._connections_seen = stamp
        today = self._requests_today()
        line.configure(text=(
            f"{today} request{'s' if today != 1 else ''} today, every one "
            "of them with its host, purpose and consent on the Network "
            "screen — during plain dictation the table stays empty."))

    # ------------------------------------------------ the account (screen 16)

    def _account_block(self, scroller) -> None:
        """ACCOUNT on Settings > Privacy (chapter 9 screen 16, D17, D31):
        who is signed in, when the last sync ran, and the buttons — Sign
        in with Google, an anonymous account, Sign out, Delete
        my account. Every press is a command to the RUNNING app over the
        pipe: this window is another process, and only the app holds the
        session (8.6). The line and the buttons follow status()["account"]
        on every poll (_paint_account), so a sign-in finishing in the
        browser shows up here without a click. Delete asks first, the way
        the Problems ✕ does — the question grows out of the card, and the
        answer sits at the far end from the button that raised it."""
        # 36 above the strip for the two text lines, 30 for the buttons,
        # 18 of pad each side: the first build was 132 and cut the buttons
        # in half (his screenshot, 2026-09-18).
        card = ui.Card(scroller.inner, CW, 168, bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="A C C O U N T", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)
        line = tk.Label(body, text="", bg=ui.CARD, fg=ui.FG, font=(ui.UI, 10),
                        wraplength=CW - 60, justify="left", anchor="w")
        line.place(x=0, y=22)
        sub = tk.Label(body, text="", bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8),
                       wraplength=CW - 60, justify="left", anchor="w")
        sub.place(x=0, y=48)
        strip = tk.Frame(body, bg=ui.CARD, height=32, width=CW - 40)
        strip.place(x=0, y=96)
        self.parts["account_line"] = line
        self.parts["account_sub"] = sub
        self.parts["account_strip"] = strip
        self._account_seen = None
        self._account_asking = False
        self._paint_account(force=True)
        scroller.bind_wheel(card)

    def _paint_account(self, force: bool = False) -> None:
        p = self.parts
        line, sub, strip = (p.get("account_line"), p.get("account_sub"),
                            p.get("account_strip"))
        if line is None or not line.winfo_exists():
            return
        info = (self.status.get("account") or {}) if self.running else None
        key = (repr(sorted(info.items())) if info is not None else "off",
               self._account_asking)
        if not force and key == getattr(self, "_account_seen", None):
            return
        self._account_seen = key
        buttons: list[tuple[str, object]] = []
        colour = ui.FG
        said_sub = ""
        if info is None:
            said = "start dictation first — the account lives in the running app"
            colour = ui.FAINT
        elif not info.get("configured"):
            said = "no account server in this build"
            colour = ui.FAINT
        elif info.get("busy") == "waiting for the browser":
            said = "waiting for Google's sign-in page in your browser…"
            said_sub = "come back here when it says you are signed in"
        elif info.get("signed_in"):
            if info.get("email") and info.get("name"):
                said = f"Signed in with Google as {info['name']} ({info['email']})"
            elif info.get("email"):
                said = f"Signed in with Google as {info['email']}"
            else:
                ident = str(info.get("user_id") or "")
                said = f"Anonymous account · id {ident[:8]}…{ident[-4:]}" if ident \
                    else "Anonymous account"
            bits = [f"this PC: {info.get('device_name') or '?'}",
                    str(info.get("region") or "Frankfurt (Supabase)")]
            if info.get("last_sync"):
                bits.append(f"last sync {str(info['last_sync'])[11:16]} UTC")
            if info.get("live"):
                # the account's channel is open: a change on another PC
                # of this account arrives within the second (sb._live_once)
                bits.append("live")
            if info.get("waiting"):
                n = int(info["waiting"])
                bits.append(f"{n} report{'s' if n != 1 else ''} waiting to send")
            said_sub = " · ".join(bits)
            if info.get("last_error"):
                said_sub = f"{info['last_error']}  ·  {said_sub}"
            if self._account_asking:
                said = "Delete your account on the server? Your reports, synced words, " \
                       "settings and history go with it. Your data on this PC stays."
                colour = ui.AMBER
                buttons = [("Keep it", self._account_keep),
                           ("Delete", lambda: self._account_do("delete", "deleting"))]
            else:
                # No "Sync now" since 2026-09-20 (the owner, the day the
                # live channel landed: "if it syncs all the time there is
                # no need for a Sync now button"). A withdrawn sync comes
                # back through its own row's [Turn on] below.
                buttons = []
                if info.get("anonymous"):
                    buttons.append(("Sign in with Google",
                                    lambda: self._account_do("google", "opening the browser")))
                buttons += [("Sign out", lambda: self._account_do("signout", "signing out")),
                            ("Delete my account", self._account_ask)]
        else:
            said = "none — sign in to keep your learned words, settings and history " \
                   "on every PC you use"
            said_sub = (info.get("last_error") or
                        "Google through Supabase's own sign-in page; nothing about you "
                        "is stored until you press it. Each sync then asks its own card.")
            buttons = [("Sign in with Google",
                        lambda: self._account_do("google", "opening the browser")),
                       ("Anonymous account",
                        lambda: self._account_do("anonymous", "creating an anonymous account"))]
        line.configure(text=said, fg=colour)
        if sub is not None and sub.winfo_exists():
            sub.configure(text=said_sub)
        if strip is None or not strip.winfo_exists():
            return
        for child in strip.winfo_children():
            child.destroy()
        x = 0
        for label, command in buttons:
            w = widgets.button_width(label)
            ui.Button(strip, label, command, h=30, w=w, quiet=True, bg=ui.CARD
                      ).place(x=x, y=0)
            x += w + 8

    # ------------------------------------------------- the lock (2026-09-21)

    def _lock_info(self) -> dict:
        """status()["account"]["lock"] of the running app, or {}."""
        if not self.running:
            return {}
        return dict(((self.status.get("account") or {}).get("lock") or {}))

    def _lock_stat(self):
        """What the pile watches: the lock's state, the requests, and the
        card's own mode (a recovery key just made is a row until Done)."""
        lock = self._lock_info()
        return (repr(sorted(lock.items(), key=lambda kv: kv[0])),
                getattr(self, "_lock_mode", ""), bool(getattr(self, "_lock_fresh", "")))

    # -- a consent whose words changed: asked again HERE, on Home

    def _consent_stale(self) -> list[str]:
        """The kinds privacy.stale() names, less the ones he said Not
        now to in this desk (asked again at its next opening, the way
        the card used to be until the next start)."""
        try:
            import privacy
            if not getattr(self, "_privacy_configured", False):
                privacy.configure(config_mod.load_layered())
                self._privacy_configured = True
            stale = privacy.stale()
        except Exception:                 # noqa: BLE001
            return []
        later = getattr(self, "_consent_later", set())
        return [k for k in stale if k not in later]

    def _consent_stat(self):
        return tuple(self._consent_stale())

    def _waiting_consent(self) -> list[dict]:
        """A consent given under OLDER words, on the pile (the owner,
        2026-09-21 afternoon, meeting the consent card at start: "I
        really don't like these messages that appear on the screen...
        I want every message inside the app" — the third time: the card
        mid-dictation on 2026-09-19, the approve card beside the dot
        that morning). The card's words are the row's words, said in
        one line each; Turn on is privacy.grant, the same row the card
        wrote; Not now keeps the row down until the desk opens again.
        Until he answers, the feature the words cover runs local — the
        repair pass to Ollama, the one-line card as the old card — and
        this row is the one place that says so."""
        import consent_card as cc

        rows: list[dict] = []
        now = time.time()
        for kind in self._consent_stale():
            words = cc.TEXTS.get(kind) or {}
            blocks = dict(words.get("blocks") or ())
            what = str(blocks.get(cc.WHAT, "")).rstrip(".")
            # The receiver alone ("Groq and/or Google"), not the list of
            # features after the dash: a note is one line.
            whom = str(blocks.get(cc.WHOM, "")).split(" — ")[0].rstrip(".")
            off = str(blocks.get(cc.OFF, "")).rstrip(".")
            changed = str(words.get("changed") or "")
            rows.append({
                "at": now + 3, "kind": "consent", "mark": "globe",
                "mark_colour": ui.AMBER,
                "eyebrow": f"{words.get('title', kind)}   ·   the words changed",
                "eyebrow_right": False,
                "text": f"Say yes again? {changed}" if changed
                        else f"Say yes again? What leaves: {what}.",
                "note": f"To {whom}, on your own key. Off again: {off}.",
                "buttons": [("Turn on", "gold",
                             lambda k=kind: self._consent_do(k, True)),
                            ("Not now", "quiet",
                             lambda k=kind: self._consent_do(k, False))],
            })
        return rows

    def _consent_do(self, kind: str, yes: bool) -> None:
        """Turn on writes the row (privacy.grant: the consent file and
        the settings mirror — the running app sees the file's mtime on
        its next gate check, no pipe message needed); Not now keeps the
        row off this desk until it opens again."""
        import privacy

        if yes:
            try:
                privacy.grant(kind)
            except Exception as e:        # noqa: BLE001
                logging.getLogger("app").warning(
                    "could not record the consent for %s: %s", kind, e)
                return
        else:
            later = getattr(self, "_consent_later", None)
            if later is None:
                later = self._consent_later = set()
            later.add(kind)
        self._fill_waiting()

    def _waiting_lock(self) -> list[dict]:
        """The lock on the pile (the owner, 2026-09-21, meeting the
        approve card beside the dot: "not outside DeskIT — inside, on
        Home"): another PC asking to join, with its code and Approve /
        Not now; this PC waiting for its other PC, with the code it
        shows; a fresh recovery key, until Done; and — while the account
        has none — the one thing worth doing before a PC is lost."""
        lock = self._lock_info()
        if not lock or not (self.status.get("account") or {}).get("signed_in"):
            return []
        now = time.time()
        rows: list[dict] = []
        if getattr(self, "_lock_mode", "") == "shown" and getattr(self, "_lock_fresh", ""):
            rows.append({
                "at": now + 2, "kind": "lock", "mark": "keys", "mark_colour": ui.AMBER,
                "eyebrow": "Your recovery key", "eyebrow_right": False,
                "text": f"{self._lock_fresh}  —  keep it somewhere safe, it is shown once",
                "note": "With it, a PC with no other PC of yours at hand can open your "
                        "account. Making a new one replaces it.",
                "buttons": [("Copy", "gold", self._lock_copy), ("Done", "quiet", self._lock_done)],
            })
        rows += self._lock_changed_rows(lock, now)
        for ask in lock.get("pending") or []:
            name = ask.get("name") or "Another PC"
            if ask.get("twins"):
                # two open requests from one PC: one of them is somebody
                # else's copy (the audit's A74) — nothing to approve
                rows.append({
                    "at": now + 1, "kind": "lock", "mark": "keys", "mark_colour": ui.RED,
                    "eyebrow": "Your account", "eyebrow_right": False,
                    "text": f"Two requests say they are {name} — neither can be approved",
                    "note": f"One of them is not your PC. On {name}, sign out and sign in again to "
                            "ask afresh. Nobody of yours asking right now? Sign out in Settings > "
                            "Account — it signs out every PC and anyone else in your account.",
                    "buttons": [("Not now", "quiet",
                                 lambda i=ask.get("id"): self._lock_do("decline", "declined", kind=i))],
                })
                continue
            rows.append({
                "at": now + 1, "kind": "lock", "mark": "keys", "mark_colour": ui.AMBER,
                "eyebrow": "Your account", "eyebrow_right": False,
                "text": f"{name} asks to join your account — its screen must show "
                        f"{ask.get('code') or '?'}",
                "note": "Approve only if the code is exactly that. It then gets your account's "
                        "key: your cloud keys and what you said open there too, and the key "
                        "crosses sealed — the server cannot read it.",
                "buttons": [("Approve", "gold",
                             lambda i=ask.get("id"): self._lock_do("approve", "approving", kind=i)),
                            ("Not now", "quiet",
                             lambda i=ask.get("id"): self._lock_do("decline", "declined", kind=i))],
            })
        if lock.get("state") == "waiting":
            rows.append({
                "at": now, "kind": "lock", "mark": "keys", "mark_colour": ui.AMBER,
                "eyebrow": "Your account", "eyebrow_right": False,
                "text": f"Waiting for your other PC to approve this one — Home there "
                        f"must show {lock.get('code') or '…'}",
                "note": "Open the desk on your other PC and press Approve. Until then this PC "
                        "has your words and settings; what you said and your cloud keys stay "
                        "locked. No other PC at hand? Type the recovery key DeskIT made for you.",
                "buttons": [("Type the recovery key", "quiet", self._lock_go_type)],
            })
        elif lock.get("state") == "have" and lock.get("recovery") is False \
                and getattr(self, "_lock_mode", "") != "shown":
            rows.append({
                "at": 0.0, "kind": "lock", "mark": "keys", "mark_colour": ui.ACCENT,
                "eyebrow": "Your account", "eyebrow_right": False,
                "text": "Make a recovery key — so a new PC of yours can open your account "
                        "when this one is gone",
                "note": "DeskIT makes it (24 characters) and shows it once; you keep it. What "
                        "you said and your cloud keys are locked with a key only your PCs "
                        "hold — without another PC or the recovery key, a new PC cannot open them.",
                "buttons": [("Make a recovery key", "gold", self._lock_new_recovery)],
            })
        return rows

    def _lock_changed_rows(self, lock: dict, now: float) -> list[dict]:
        """The account's lock changed somewhere else (2026-09-23, the
        audit's A15): this PC kept its key, what was said and the cloud
        keys stopped syncing both ways, and the row asks — a row on
        Home, never a card that asks by itself (the owner's rule). Signal
        does the same when a contact's safety number changes: a notice in
        the conversation, nothing trusted silently. [It was me] asks to
        join the new lock (the old key is set aside, not deleted); [It
        wasn't me] keeps everything as it is and then offers the way
        out: Sign out (every session, a stolen one too) and Put my lock
        back."""
        ch = lock.get("changed") or {}
        if lock.get("state") != "changed":
            return []
        if not ch.get("refused"):
            return [{
                "at": now + 3, "kind": "lock", "mark": "keys", "mark_colour": ui.RED,
                "eyebrow": "Your account", "eyebrow_right": False,
                "text": "The lock of your account changed — not on this PC. Was it you?",
                "note": "Until you answer, what you said and your cloud keys stop syncing, both "
                        "ways; this PC keeps its key. It was you: this PC asks to join the new "
                        "lock — approve it from your other PC or type the recovery key. It "
                        "wasn't: nothing here changes.",
                "buttons": [("It wasn't me", "gold",
                             lambda: self._lock_do("lock_answer", "kept", kind="no")),
                            ("It was me", "quiet",
                             lambda: self._lock_do("lock_answer", "asked", kind="yes"))],
            }]
        buttons = [("Sign out", "quiet", self._lock_go_account)]
        if ch.get("mine"):                 # a key here to put back (not one set aside already)
            buttons.insert(0, ("Put my lock back", "gold",
                               lambda: self._lock_do("lock_restore", "put back")))
        return [{
            "at": now + 3, "kind": "lock", "mark": "keys", "mark_colour": ui.RED,
            "eyebrow": "Your account", "eyebrow_right": False,
            "text": "Not you — this PC kept its key. What you said and your keys stay paused",
            "note": "Sign out in Settings > Account: it signs out every PC of yours and anyone "
                    "else in your account. Sign in again here, then put your lock back — "
                    "syncing starts again under this PC's key.",
            "buttons": buttons,
        }]

    def _lock_go_account(self) -> None:
        """The changed-lock row's [Sign out]: Settings > Account, where
        Sign out is — one press away, never pressed for him."""
        self._show("Settings")
        self._settings_go("Account")
        self._finish_settings()

    def _lock_go_type(self) -> None:
        """The pile's [Type the recovery key]: the lock card with its
        field open and focused — one press, and the caret is in the field.

        ONE switch, to the tab the card is on. It was _show("Settings"),
        then _settings_go("Privacy"): two rebuilds in one press, and the
        person saw Home, then the General tab for the ~85 ms the second
        one took, then Privacy (review of 2026-09-22) — which, since the
        eight tabs, is not where the lock is at all (LAYOUT: Account), so
        the field it opened did not exist. The tab is set before the
        switch, and the rest of the tab and the open field are built
        under the switch's own cover (`then`)."""
        self._settings_tab = settings_mod.ACCOUNT

        def then() -> None:
            self._finish_settings()
            self._lock_type()
        self._show("Settings", then=then)

    def _lock_banner(self, lock: dict) -> None:
        """One line at the top of every screen while the lock needs the
        person (the owner, 2026-09-21: "something on every screen, up
        top"): another PC asking, with Approve / Not now; this PC waiting,
        with its code. On the pane, above the sheet, like the toast —
        gone the moment nothing waits."""
        # kept on self, not in parts: _show() replaces the parts dict on
        # every screen switch, and the banner lives on the pane across them
        pending = (lock.get("pending") or []) if self.running else []
        waiting = self.running and lock.get("state") == "waiting"
        changed = self.running and lock.get("state") == "changed" \
            and not (lock.get("changed") or {}).get("refused")
        if self.screen == "Home":
            pending, waiting, changed = [], False, False     # Home carries the same as a row
        if changed:
            text = "The lock of your account changed — not on this PC. Answer on Home."
            buttons = [("Home", lambda: self._show("Home"))]
            key = ("changed", (lock.get("changed") or {}).get("server"))
        elif pending and pending[0].get("twins"):
            ask = pending[0]
            text = (f"Two requests say they are {ask.get('name') or 'another PC'} — "
                    f"neither can be approved. See Home.")
            buttons = [("Home", lambda: self._show("Home"))]
            key = ("twins", ask.get("id"))
        elif pending:
            ask = pending[0]
            text = (f"{ask.get('name') or 'Another PC'} asks to join your account — "
                    f"its screen must show  {ask.get('code') or '?'}")
            buttons = [("Approve", lambda i=ask.get("id"): self._lock_do("approve", "approving", kind=i)),
                       ("Not now", lambda i=ask.get("id"): self._lock_do("decline", "declined", kind=i))]
            key = ("pending", ask.get("id"), ask.get("code"))
        elif waiting:
            text = (f"Waiting for your other PC to approve this one — Home there must "
                    f"show  {lock.get('code') or '…'}")
            buttons = []
            key = ("waiting", lock.get("code"))
        else:
            text, buttons, key = "", [], None
        if key == getattr(self, "_lock_banner_key", None):
            shown = getattr(self, "_lock_banner_card", None)
            if shown is not None and shown.winfo_exists():
                tk.Misc.tkraise(shown)       # a screen just slid in under it (a Card is a Canvas: its own lift wants a tag)
            return
        self._lock_banner_key = key
        old = getattr(self, "_lock_banner_card", None)
        self._lock_banner_card = None
        if old is not None and old.winfo_exists():
            old.destroy()
        if key is None:
            return
        card = ui.Card(self.pane, CW, 46, radius=12, bg=ui.BG, fill=ui.QUOTE_BG,
                       border=ui.AMBER, pad=10)
        tk.Label(card.body, text=text, bg=ui.QUOTE_BG, fg=ui.FG, font=(ui.UI, 10),
                 anchor="w").place(x=4, y=3)
        x = CW - 20
        for label, command in reversed(buttons):
            w = widgets.button_width(label)
            x -= w
            ui.Button(card.body, label, command, h=26, w=w, quiet=True, bg=ui.QUOTE_BG
                      ).place(x=x, y=0)
            x -= 8
        card.place(x=PAD, y=6)
        tk.Misc.tkraise(card)
        self._lock_banner_card = card

    def _lock_block(self, scroller) -> None:
        """THE LOCK under the account card: one key per account, held by
        its own PCs, never by the server (vault.py, sb.py's lock). The
        card says where this PC stands — it holds the key; it waits for
        another PC to approve it and shows the code that PC must see;
        another PC asks to join and this one can approve it — and
        carries the recovery key: made here once, shown once, typed on a
        PC that has no other PC at hand. Every press is a command to the
        running app over the pipe, like the account's."""
        # 22 for the line, 32 for a code, 34 for the sub, 30 for the
        # recovery field when it is up, 32 for the buttons, 18 of pad
        # each side: the typing state is the tallest and sets the card
        card = ui.Card(scroller.inner, CW, 226, bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="T H E   L O C K", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)
        line = tk.Label(body, text="", bg=ui.CARD, fg=ui.FG, font=(ui.UI, 10),
                        wraplength=CW - 60, justify="left", anchor="w")
        line.place(x=0, y=22)
        code = tk.Label(body, text="", bg=ui.CARD, fg=ui.FG, font=(ui.MEDIUM, 18), anchor="w")
        code.place(x=0, y=48)
        sub = tk.Label(body, text="", bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8),
                       wraplength=CW - 60, justify="left", anchor="w")
        sub.place(x=0, y=80)
        field = ui.Field(body, w=CW - 60 - 110, h=30, bg=ui.CARD, justify="left", pt=9)
        strip = tk.Frame(body, bg=ui.CARD, height=32, width=CW - 40)
        strip.place(x=0, y=118)
        self.parts["lock_line"] = line
        self.parts["lock_code"] = code
        self.parts["lock_sub"] = sub
        self.parts["lock_field"] = field
        self.parts["lock_strip"] = strip
        self._lock_seen = None
        self._lock_mode = ""           # "" | "typing" (the recovery field is up) | "shown" (a fresh recovery key)
        self._lock_fresh = ""          # the recovery key just made, until Done
        self._paint_lock(force=True)
        scroller.bind_wheel(card)

    def _lock_tick(self) -> None:
        """Every poll, on every screen: the banner, and a note the moment
        a request lands (the card on Home says the rest)."""
        lock = self._lock_info()
        try:
            self._lock_banner(lock)
        except Exception:                                    # noqa: BLE001
            import logging
            logging.getLogger("app").warning("the lock banner did not paint", exc_info=True)
        ids = {str(a.get("id")) for a in (lock.get("pending") or []) if not a.get("twins")}
        fresh = ids - getattr(self, "_lock_noted", set())
        self._lock_noted = ids
        if fresh and self.screen != "Home":
            ask = next(a for a in lock["pending"] if str(a.get("id")) in fresh)
            self._note(f"{ask.get('name') or 'Another PC'} asks to join your account — "
                       f"Approve at the top, or on Home")

    def _paint_lock(self, force: bool = False) -> None:
        p = self.parts
        info = ((self.status.get("account") or {}) if self.running else None)
        lock = (info or {}).get("lock") or {}
        line, code, sub, field, strip = (p.get("lock_line"), p.get("lock_code"), p.get("lock_sub"),
                                         p.get("lock_field"), p.get("lock_strip"))
        if line is None or not line.winfo_exists():
            return
        key = (repr(sorted(lock.items(), key=lambda kv: kv[0])) if info is not None else "off",
               bool(info and info.get("signed_in")), self._lock_mode)
        if not force and key == getattr(self, "_lock_seen", None):
            return
        self._lock_seen = key
        buttons: list[tuple[str, object]] = []
        colour, said_code, said_sub, typing = ui.FG, "", "", False
        if info is None or not info.get("configured"):
            said = "start dictation first — the lock lives in the running app"
            colour = ui.FAINT
        elif not info.get("signed_in"):
            said = "sign in first — the lock is your account's"
            colour = ui.FAINT
        elif self._lock_mode == "shown":
            said = "Your recovery key. Keep it somewhere safe — it is shown once."
            said_code = self._lock_fresh
            said_sub = ("With it, a PC with no other PC of yours at hand can open your "
                        "account. Making a new one replaces it.")
            colour = ui.AMBER
            buttons = [("Copy", self._lock_copy), ("Done", self._lock_done)]
        elif lock.get("state") == "changed":
            ch = lock.get("changed") or {}
            colour = ui.RED
            if not ch.get("refused"):
                said = "The lock of your account changed — not on this PC. Was it you?"
                said_sub = ("This PC keeps its key; what you said and your cloud keys stop "
                            "syncing until you answer. It was you: this PC asks to join the new "
                            "lock. It wasn't: nothing here changes.")
                buttons = [("It wasn't me", lambda: self._lock_do("lock_answer", "kept", kind="no")),
                           ("It was me", lambda: self._lock_do("lock_answer", "asked", kind="yes"))]
            else:
                said = "Not you — this PC kept its key; what you said and your keys stay paused."
                said_sub = ("Sign out above: it signs out every PC of yours and anyone else in "
                            "your account. Sign in again, then put your lock back.")
                buttons = ([("Put my lock back", lambda: self._lock_do("lock_restore", "put back"))]
                           if ch.get("mine") else [])
            if ch.get("server"):
                said_sub += f"  ·  on the server: lock {ch['server']}, here: lock {ch.get('mine') or '—'}"
        elif lock.get("pending") and lock["pending"][0].get("twins"):
            ask = lock["pending"][0]
            said = (f"Two requests say they are {ask.get('name') or 'another PC'} — "
                    "neither can be approved.")
            said_sub = (f"One of them is not your PC. On {ask.get('name') or 'that PC'}, sign out "
                        "and sign in again to ask afresh.")
            colour = ui.RED
            buttons = [("Not now", lambda i=ask.get("id"): self._lock_do("decline", "declined", kind=i))]
        elif lock.get("pending"):
            ask = lock["pending"][0]
            said = f"{ask.get('name') or 'Another PC'} signed in to your account and asks to join."
            said_code = str(ask.get("code") or "")
            said_sub = ("Its screen shows a code — approve only if it is exactly this one. "
                        "It then gets your account's key: your cloud keys and what you "
                        "said open there too.")
            buttons = [("Approve", lambda i=ask.get("id"): self._lock_do("approve", "approving", kind=i)),
                       ("Not now", lambda i=ask.get("id"): self._lock_do("decline", "declined", kind=i))]
        elif lock.get("state") == "waiting":
            said = "Waiting for your other PC to approve this one."
            said_code = str(lock.get("code") or "")
            typing = self._lock_mode == "typing"
            if typing:
                said_sub = "Your recovery key — 24 letters and digits in six groups:"
                buttons = [("Open", self._lock_recover), ("Cancel", self._lock_done)]
            else:
                said_sub = ("Open the desk on your other PC: Home there shows this code — press "
                            "Approve. Until then this PC has your words and settings; "
                            "what you said and your cloud keys stay locked.")
                buttons = [("Type the recovery key", self._lock_type)]
            if lock.get("error"):
                said_sub = f"{lock['error']}  ·  {said_sub}"
        elif lock.get("state") == "have":
            said = "This PC holds your account's key."
            bits = ["what you said and your cloud keys leave this PC locked",
                    "the server cannot read them"]
            if lock.get("id"):
                bits.append(f"lock {lock['id']}")
            if lock.get("recovery"):
                bits.append("recovery key: made")
            elif lock.get("recovery") is False:
                bits.append("no recovery key yet")
            said_sub = " · ".join(bits)
            buttons = [("Replace the recovery key" if lock.get("recovery") else "Make a recovery key",
                        self._lock_new_recovery)]
        else:
            said = "Looking at the lock…"
            said_sub = lock.get("error") or "the next sync says where this PC stands"
            colour = ui.FAINT
        line.configure(text=said, fg=colour)
        if code is not None and code.winfo_exists():
            code.configure(text=said_code)
        if sub is not None and sub.winfo_exists():
            sub.configure(text=said_sub)
            sub.place(y=80 if said_code else 48)
        if field is not None and field.winfo_exists():
            if typing:
                field.place(x=0, y=100)
            else:
                field.place_forget()
        if strip is None or not strip.winfo_exists():
            return
        strip.place(y=138 if typing else (118 if said_code else 96))
        for child in strip.winfo_children():
            child.destroy()
        x = 0
        for label, command in buttons:
            w = widgets.button_width(label)
            ui.Button(strip, label, command, h=30, w=w, quiet=True, bg=ui.CARD
                      ).place(x=x, y=0)
            x += w + 8

    def _lock_do(self, do: str, said: str, **args) -> None:
        if not self.running:
            self._note("start dictation first — the lock lives in the running app")
            return
        self._busy_until = time.monotonic() + 2
        self._ask("account", then=lambda r: self._announce(r, said), do=do, **args)

    def _lock_type(self) -> None:
        self._lock_mode = "typing"
        self._paint_lock(force=True)
        field = self.parts.get("lock_field")
        if field is not None and field.winfo_exists():
            field.entry.focus_set()

    def _lock_recover(self) -> None:
        """[Open] beside the typed recovery key: the value goes to the
        app over the pipe and nowhere else; the field is emptied."""
        field = self.parts.get("lock_field")
        typed = field.get().strip() if field is not None else ""
        if field is not None:
            field.set("")
        if not typed:
            self._note("type the recovery key first")
            return
        self._lock_mode = ""
        self._paint_lock(force=True)
        self._lock_do("recover", "opened", kind=typed)
        del typed

    def _lock_new_recovery(self) -> None:
        """[Make / Replace the recovery key]: the app makes it (half a
        second) and answers with it once; this card shows it until Done."""
        if not self.running:
            self._note("start dictation first — the lock lives in the running app")
            return
        self._busy_until = time.monotonic() + 2

        def shown(reply) -> None:
            if not reply or not reply.get("ok") or not reply.get("recovery"):
                self._announce(reply, "that did not work")
                return
            self._lock_fresh = str(reply["recovery"])
            self._lock_mode = "shown"
            self._paint_lock(force=True)
            self._note("your recovery key is on the card — copy it somewhere safe")
        self._ask("account", then=shown, do="recovery_new")

    def _lock_copy(self) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._lock_fresh)
            self._note("copied — paste it somewhere safe, then press Done")
        except Exception:                                    # noqa: BLE001
            self._note("could not reach the clipboard — write it down")

    def _lock_done(self) -> None:
        self._lock_fresh = ""
        self._lock_mode = ""
        self._paint_lock(force=True)

    def _account_ask(self) -> None:
        self._account_asking = True
        self._paint_account(force=True)

    def _account_keep(self) -> None:
        self._account_asking = False
        self._paint_account(force=True)

    def _account_do(self, do: str, said: str, **args) -> None:
        self._account_asking = False
        if not self.running:
            self._note("start dictation first — the account lives in the running app")
            return
        self._busy_until = time.monotonic() + 1
        self._ask("account", then=lambda r: self._announce(r, said), do=do, **args)

    def _key_say(self, name: str, text: str, colour: str | None = None) -> None:
        line = self.parts.get("key_lines", {}).get(name)
        if line is not None and line.winfo_exists():
            line.configure(text=text, fg=colour or ui.FG)

    def _key_save(self, name: str) -> None:
        """The pasted value into the store — never into a file — then
        the test; the field is emptied either way, so the value is on
        screen for exactly as long as it takes to press the button."""
        import secretstore
        field = self.parts.get("key_fields", {}).get(name)
        value = field.get().strip() if field is not None else ""
        if field is not None:
            field.set("")
        if not value:
            self._key_test(name)
            return
        try:
            secretstore.set(name, value)
        except Exception as e:                                # noqa: BLE001
            self._key_say(name, f"could not store the key: {e}", ui.RED)
            return
        del value
        self._key_say(name, f"Stored in Windows Credential Manager as "
                            f"{secretstore.target(name)} — testing…", ui.DIM)
        self._key_test(name)
        if self.running:
            # the account's other PCs get it too, sealed (sb._sync_vault)
            self._ask("account", do="nudge", kind="vault")

    def _key_test(self, name: str) -> None:
        """One `key-test` call through net.py, on a thread: the
        provider's model list under the stored key. The key value never
        touches this method — net.py attaches it by name."""
        import secretstore
        if name not in secretstore.present():
            self._key_say(name, "no key", ui.FAINT)
            return

        results: dict = self.__dict__.setdefault("_key_results", {})
        results.pop(name, None)

        def work() -> None:
            try:
                count = self._key_probe(name)
                results[name] = (f"Works · {count} models visible · stored as "
                                 f"{secretstore.target(name)}", ui.GREEN)
            except Exception as e:                            # noqa: BLE001
                results[name] = (f"stored, but the provider said: {str(e)[:160]}", ui.AMBER)
        threading.Thread(target=work, daemon=True, name="key-test").start()
        # Polled from the Tk side rather than root.after from the thread:
        # a Tk call from another thread needs the main loop, which a test
        # driving update() does not run.
        self.root.after(100, lambda: self._key_poll(name))

    def _key_poll(self, name: str) -> None:
        if self.closing:
            return
        said = self.__dict__.get("_key_results", {}).pop(name, None)
        if said is None:
            self.root.after(100, lambda: self._key_poll(name))
            return
        self._key_say(name, *said)

    @staticmethod
    def _key_probe(name: str) -> int:
        """How many models the key can see — the one allowed call."""
        import json as json_mod

        import net
        if name == "groq":
            status, _h, body = net.request(
                "GET", "https://api.groq.com/openai/v1/models", "key-test",
                secret="groq", timeout_s=20)
        else:
            status, _h, body = net.request(
                "GET", f"{net.GEMINI_BASE_URL}v1beta/models?pageSize=200", "key-test",
                secret="gemini", timeout_s=20)
        if status != 200:
            detail = body.decode("utf-8", "replace")[:200]
            raise RuntimeError(f"HTTP {status}: {detail}")
        data = json_mod.loads(body.decode("utf-8"))
        items = data.get("data") if name == "groq" else data.get("models")
        return len(items or [])

    def _key_remove(self, name: str) -> None:
        import secretstore
        try:
            had = secretstore.delete(name)
        except Exception as e:                                # noqa: BLE001
            self._key_say(name, f"could not remove the key: {e}", ui.RED)
            return
        self._key_say(name, "no key" if had else "no key to remove", ui.FAINT)
        self._note(f"{name}: the key is gone from Windows Credential Manager"
                   if had else f"{name}: there was no key")

    # ------------------------------------------------ the two D33 switches

    def _claude_block(self, scroller) -> None:
        """Connect Claude Code on Settings > Messages & sounds (D15, D33):
        switch the wizard's extras page asked once — two hook lines in
        ~/.claude/settings.json, written and removed through notify_hook.

        One settings.json serves every DeskIT copy on the PC, so the
        switch says WHOSE lines are there (notify_hook.hook_state): on
        for this copy's; off with an amber line when another copy holds
        the door (the owner, 2026-09-22 — the installed copy's switch
        stood on while the lines named the checkout, and its cards went
        to the wrong port); and a flip then asks in the card, the way
        Delete my account does, before the other copy is disconnected.
        The switch-and-sentence shape is _switch_card's, drawn here by
        hand because the sentence and the two buttons change."""
        card = ui.Card(scroller.inner, CW, 36 + 46 + 3 * LINE + 6,
                       bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="C L A U D E   C O D E", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)
        switch = ui.Switch(body, False, self._claude_flip, bg=ui.CARD)
        switch.place(x=0, y=26)
        tk.Label(body, text="Connect Claude Code", bg=ui.CARD, fg=ui.FG,
                 font=(ui.UI, 10)).place(x=60, y=24)
        line = tk.Label(body, text="", bg=ui.CARD, fg=ui.FAINT,
                        font=(ui.UI, 8), justify="left")
        line.place(x=60, y=46)
        strip = tk.Frame(body, bg=ui.CARD, height=30, width=CW - 100)
        self.parts["claude_switch"] = switch
        self.parts["claude_card"] = card
        self.parts["claude_line"] = line
        self.parts["claude_strip"] = strip
        self._claude_asking = False
        self._claude_state = "none"
        self._claude_other = None
        self._paint_claude()
        scroller.bind_wheel(card)

    def _paint_claude(self) -> None:
        """The card as the file stands: the switch, one sentence, and —
        while it asks — the two answers under the sentence, the card
        grown to hold them (ui.Card.resize, the home pile's way)."""
        import notify_hook
        p = self.parts
        card, switch, line, strip = (p.get("claude_card"), p.get("claude_switch"),
                                     p.get("claude_line"), p.get("claude_strip"))
        if line is None or not line.winfo_exists():
            return
        state, other = "none", None
        try:
            state, other = notify_hook.hook_state(
                script=str(APP_DIR / "notify_hook.py"))
        except Exception:                 # noqa: BLE001
            pass
        self._claude_state, self._claude_other = state, other
        if state != "other":
            self._claude_asking = False   # nothing left to take over
        colour = ui.FAINT
        buttons: list[tuple[str, object]] = []
        on = state == "mine"
        if self._claude_asking:
            said = (f"Disconnect the other DeskIT copy ({other}) and connect "
                    "this one? Claude Code's cards stop there and start here.")
            colour = ui.AMBER
            buttons = [("Keep it", self._claude_keep),
                       ("Yes, connect this one", self._claude_take)]
        elif state == "other":
            said = (f"Claude Code is connected to another DeskIT copy "
                    f"({other}). Turn this on to move it here.")
            colour = ui.AMBER
        elif state == "mine":
            said = ("Connected: two hook lines in ~/.claude/settings.json "
                    "name this copy — when Claude Code finishes or asks, "
                    "DeskIT shows a card and plays a cue. Off removes the lines.")
        else:
            said = ("Two hook lines in ~/.claude/settings.json: when Claude "
                    "Code finishes or asks, DeskIT shows a card and plays a "
                    "cue. Off removes the lines.")
        switch.set(on)
        text, lines = ui.clamp(said, ui.UI, 8, CW - 100, 3)
        line.configure(text=text, fg=colour)
        for child in strip.winfo_children():
            child.destroy()
        height = 36 + 46 + lines * LINE + 6
        if buttons:
            strip.place(x=60, y=46 + lines * LINE + 8)
            x = 0
            for label, command in buttons:
                w = widgets.button_width(label)
                ui.Button(strip, label, command, h=30, w=w, quiet=True,
                          bg=ui.CARD).place(x=x, y=0)
                x += w + 8
            height += 30 + 8
        else:
            strip.place_forget()
        card.resize(height)

    def _claude_keep(self) -> None:
        self._claude_asking = False
        self._paint_claude()

    def _claude_take(self) -> None:
        """Yes: the other copy's lines go, this copy's are written — one
        install_hook, which sweeps every DeskIT entry before it adds."""
        self._claude_asking = False
        other = self._claude_other
        try:
            self._claude_connect()
            self._note(f"Claude Code connected — the other copy ({other}) "
                       "is disconnected")
        except Exception as e:                                # noqa: BLE001
            self._note(f"could not write the hook: {e}")
        self._paint_claude()

    def _claude_connect(self) -> None:
        import launch
        import notify_hook
        notify_hook.install_hook(notify_hook.DEFAULT_SETTINGS,
                                 python=launch.pythonw(),
                                 script=str(APP_DIR / "notify_hook.py"))
        config_mod.save({"notify.enabled": True})

    def _switch_card(self, scroller, title: str, on: bool, command,
                     label: str, help_text: str):
        """One switch with its sentence, on a card tall enough for the
        sentence: the small face is LINE px a line, the sentence starts
        46 px down the body, and the card used to be 92 px flat — which
        put the first line's descenders behind the card's edge and the
        second line nowhere at all (the owner, 2026-09-18, pointing at
        the Snipping-Tool key and Connect Claude Code: "it is swallowed").
        The words are wrapped by measuring, the way the settings rows
        are, so the height and the text agree before either is drawn."""
        text, lines = ui.clamp(help_text, ui.UI, 8, CW - 100, 3)
        card = ui.Card(scroller.inner, CW, 36 + 46 + lines * LINE + 6,
                       bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text=title, bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)
        switch = ui.Switch(body, on, command, bg=ui.CARD)
        switch.place(x=0, y=26)
        tk.Label(body, text=label, bg=ui.CARD, fg=ui.FG,
                 font=(ui.UI, 10)).place(x=60, y=24)
        tk.Label(body, text=text, bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8),
                 justify="left").place(x=60, y=46)
        scroller.bind_wheel(card)
        return switch

    def _claude_flip(self, on: bool) -> None:
        """The switch: on writes this copy's lines, off removes them —
        unless another copy holds the door, when on only ASKS (the knob
        goes back until the answer) and off touches nothing, since
        uninstall_hook sweeps every copy's lines and the other copy's
        are not this switch's to remove."""
        import notify_hook
        if self._claude_state == "other":
            self._claude_asking = bool(on)
            self._paint_claude()
            return
        try:
            if on:
                self._claude_connect()
                self._note("Claude Code connected — the hook lines are in "
                           "~/.claude/settings.json")
            else:
                notify_hook.uninstall_hook(notify_hook.DEFAULT_SETTINGS)
                self._note("Claude Code disconnected — the hook lines are gone")
        except Exception as e:                                # noqa: BLE001
            self._note(f"could not write the hook: {e}")
        self._paint_claude()

    def _recording_block(self, scroller) -> None:
        """The Recording pack on Settings > Screen (13.4, D24): PyAV with
        its FFmpeg — screen recording, the camera, non-WAV uploads. The
        installer never carries it (a GPL FFmpeg build); the person's
        own download from PyPI through the pack's step window, the
        licence on the card. The checkout has it in its venv.

        AND IT SAYS WHAT IT IS FOR, NOT WHAT IT IS MADE OF. The owner,
        2026-09-22, reading this card: "here I am looking now at
        Recording, PyAV FFmpeg is installed — I don't think anyone has
        the faintest idea what that is". So the line names the two keys
        it unlocks and how large the download is; the library and its
        licence are the small print under it, and only while there is
        something to press. Every capture app that ever showed this line
        does the same — "Models library", "language files", "476 MB" —
        and ShareX, which used to show an FFmpeg path with a Download
        button, now bundles it and shows nothing at all."""
        buttons: list = []
        small = ""
        if paths.PORTABLE:
            said = "Screen recording and the webcam are ready."
        else:
            state = packs_mod.state("recording")
            rp = packs_mod.pack("recording")
            size = f" ({packs_mod.human(rp.bytes)})" if rp else ""
            if state == "ok":
                said = "Screen recording and the webcam are ready."
                buttons.append(("Remove it",
                                lambda: self._pack_remove("recording")))
            elif state == "stale":
                said = ("Screen recording and the webcam work, and there is "
                        f"a newer download for them{size}.")
                small = ("A free video toolkit (FFmpeg) that the installer "
                         "cannot carry, because of its licence.")
                buttons.append((f"Update{size}",
                                lambda: self._hardware_step("--install-pack", "recording")))
            else:
                said = ("Screen recording and the webcam need one extra "
                        f"download{size}. Dictation, screenshots and asking "
                        "about the screen all work without it.")
                small = ("It is a free video toolkit (FFmpeg) that the "
                         "installer cannot carry, because of its licence.")
                buttons.append((f"Download{size}",
                                lambda: self._hardware_step("--install-pack", "recording")))
        self.parts["recording_line"] = said
        # The sentence stops short of the buttons instead of running
        # under them, and the card is as tall as the sentence wraps to:
        # on an installed copy without the pack it is two lines beside a
        # 270 px button, and a 96 px card cut the second line's tail.
        taken = sum(widgets.button_width(label) + 8 for label, _c in buttons)
        text, lines = ui.clamp(said, ui.UI, 10, CW - 36 - taken - 12, 3)
        note, note_lines = ui.clamp(small, ui.UI, 8, CW - 36 - taken - 12, 2) \
            if small else ("", 0)
        card = ui.Card(scroller.inner, CW,
                       36 + 22 + lines * 20 + note_lines * LINE + 8,
                       bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="S C R E E N   R E C O R D I N G", bg=ui.CARD,
                 fg=ui.FAINT, font=(ui.MEDIUM, 8)).place(x=0, y=0)
        tk.Label(body, text=text, bg=ui.CARD, fg=ui.FG, font=(ui.UI, 10),
                 justify="left").place(x=0, y=22)
        if note_lines:
            tk.Label(body, text=note, bg=ui.CARD, fg=ui.FAINT,
                     font=(ui.UI, 8), justify="left").place(
                x=0, y=22 + lines * 20 + 2)
        x = CW - 36
        for label, command in buttons:
            w = widgets.button_width(label)
            ui.Button(body, label, command, h=30, w=w, quiet=True, bg=ui.CARD
                      ).place(x=x, y=20, anchor="ne")
            x -= w + 8
        scroller.bind_wheel(card)

    def _pack_remove(self, name: str) -> None:
        packs_mod.remove(name)
        self._note(f"the {name} pack was removed")
        self._draw_settings()

    SNIP_KEY, PLAIN_SNIP_KEY = "win+shift+s", "ctrl+f11"

    def _snip_block(self, scroller, sections) -> None:
        """The Snipping-Tool key on Settings > Screen (chapter 9 screen 13,
        D25, D33): the switch the wizard asked once — on, DeskIT's
        screenshot key is Win+Shift+S and Windows' own Snipping Tool
        stops answering it while DeskIT runs; off, the key is Ctrl+F11.
        Written like any other key — capture_hotkey through _apply_key —
        so the running app rebinds live and a collision is refused."""
        setting = settings_mod.find(sections, "capture.capture_hotkey")
        if setting is None:
            return
        current = str(self.parts["values"].get(setting.path, setting.value)).strip().lower()
        self.parts["snip_switch"] = self._switch_card(
            scroller, "T H E   S N I P P I N G - T O O L   K E Y",
            current == self.SNIP_KEY,
            lambda v, s=setting: self._snip_flip(s, v),
            "Take over Win+Shift+S for DeskIT's screenshot key",
            "Windows' own Snipping Tool stops answering that shortcut "
            "while DeskIT runs; off, the screenshot key is Ctrl+F11. "
            "Any other key: the Keys place.")

    def _snip_flip(self, setting, on: bool) -> None:
        """The same road as the Keys place: validated against the other
        keys, live through the app's `rebind` when it runs."""
        value = self.SNIP_KEY if on else self.PLAIN_SNIP_KEY
        self.parts["values"][setting.path] = value
        self._apply_key("capture_hotkey", value)

    def _model_block(self, scroller) -> None:
        """The speech model and the card that runs it, on Settings >
        Dictation, right under the line that chooses where speech
        becomes words (plan 6.4-6.5, 6.9). In the checkout both are the
        venv's own and the lines say so with no buttons; on an installed
        copy every button runs the step in a process of its own
        (launch.run_step) or removes a folder, and the row says what
        happens next.

        It sat on "The app" as THIS PC until 2026-09-22, under a line of
        hardware — "gpu (NVIDIA card, 16 GB, driver 596.49 · 12 cores)"
        — which is a fact about the machine and not a decision. The
        hardware line is on About now, and what is left here is the two
        things a person can do something about: the model that turns
        speech into words, and whether the graphics card does the work.
        Every local-model app that was read puts the download beside the
        engine it feeds, and none of them on an About page."""
        lines, buttons = self._model_lines()
        # As tall as what is on it: two lines and, in a checkout, no
        # buttons at all — a flat height left a hand's width of empty
        # card under them.
        card = ui.Card(scroller.inner, CW,
                       36 + 26 + 40 * len(lines) + (34 if buttons else 0),
                       bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="T H E   S P E E C H   M O D E L", bg=ui.CARD,
                 fg=ui.FAINT, font=(ui.MEDIUM, 8)).place(x=0, y=0)
        self.parts["model_lines"] = [t for _n, t in lines]
        self.parts["model_buttons"] = [label for label, _c in buttons]
        y = 26
        for name, text in lines:
            tk.Label(body, text=name, bg=ui.CARD, fg=ui.DIM,
                     font=(ui.UI, 9)).place(x=0, y=y)
            tk.Label(body, text=text, bg=ui.CARD, fg=ui.FG, font=(ui.UI, 10),
                     wraplength=CW - 60, justify="left").place(x=140, y=y - 1)
            y += 40
        x = 0
        for label, command in buttons:
            w = widgets.button_width(label)
            ui.Button(body, label, command, h=28, w=w, quiet=True,
                      bg=ui.CARD).place(x=x, y=y + 6)
            x += w + 8
        scroller.bind_wheel(card)

    def _voice_block(self, scroller) -> None:
        """6.8, on an installed copy with no he-IL voice: the sentence,
        and the button that opens the Windows page where one is added.
        The Speak row below stays; the probe has set it off in the
        machine layer until a voice turns up."""
        card = ui.Card(scroller.inner, CW, 96, bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="N O   H E B R E W   V O I C E", bg=ui.CARD,
                 fg=ui.AMBER, font=(ui.MEDIUM, 8)).place(x=0, y=0)
        tk.Label(body, text=hardware_mod.NO_VOICE, bg=ui.CARD, fg=ui.FG,
                 font=(ui.UI, 10), wraplength=CW - 220, justify="left").place(x=0, y=22)
        self.parts["voice_block"] = card
        ui.Button(body, "Open Speech settings", self._open_speech_settings, h=30,
                  quiet=True, w=widgets.button_width("Open Speech settings")
                  ).place(x=CW - 36, y=20, anchor="ne")
        scroller.bind_wheel(card)

    def _open_speech_settings(self) -> None:
        try:
            os.startfile("ms-settings:speech")
        except OSError as e:
            self._note(f"could not open the Speech settings ({e})")

    def _model_lines(self) -> tuple[list, list]:
        """The two lines of the card and the buttons under them.

        Plain words on both (2026-09-22): the model is "the Hebrew
        model", named by what it does and how large it is — the repo
        name is on About, with the licence it belongs to — and the GPU
        pack is "faster dictation", which is the only thing about it a
        person can judge."""
        model, pack, _changed = self._hardware_words()
        lines: list[tuple[str, str]] = []
        buttons: list = []
        try:
            repo = config_mod.load_layered().local.model
        except Exception:                 # noqa: BLE001
            repo = ""
        if paths.PORTABLE:
            lines.append(("The Hebrew model", "ready — this checkout's own"))
            lines.append(("Faster dictation",
                          "on — the work runs on your NVIDIA card"
                          if pack == "venv" else
                          "off — dictation runs on the processor"))
            return lines, buttons
        e = models_mod.entry(repo)
        size = f" ({models_mod.human(e.bytes)})" if e else ""
        model_said = {
            "ready": f"ready{size}",
            "absent": f"not downloaded yet{size}",
            "incomplete": "the download did not finish — continue it",
            "stale": "there is a newer one to download",
            "unknown": "this copy asks for a model nobody knows",
        }[model]
        lines.append(("The Hebrew model", model_said))
        if model == "ready":
            buttons.append(("Delete and re-download the model", self._speed_redownload))
            buttons.append(("Delete the model", self._speed_delete_model))
        elif model != "unknown":
            buttons.append(("Download the model" if model == "absent" else "Continue the download",
                            lambda: self._hardware_step("--download-model")))
        facts = hardware_mod.recorded()
        has_card = int(facts.get("cuda_devices") or 0) >= 1
        gp = packs_mod.pack("gpu")
        psize = f" ({packs_mod.human(gp.bytes)})" if gp else ""
        if pack.startswith("failed:"):
            pack_said = f"it will not start on this PC ({pack[7:]}) — dictation runs on the processor"
            buttons.append(("Try it again", self._hardware_retry))
            buttons.append((f"Download it again{psize}",
                            lambda: self._hardware_step("--install-pack", "gpu")))
            buttons.append(("Turn off faster dictation", self._hardware_remove))
        elif pack == "ok":
            pack_said = "on — the work runs on your NVIDIA card"
            buttons.append(("Turn off faster dictation", self._hardware_remove))
        elif pack == "stale":
            pack_said = "on, and there is a newer download for it"
            buttons.append((f"Update faster dictation{psize}",
                            lambda: self._hardware_step("--install-pack", "gpu")))
            buttons.append(("Turn off faster dictation", self._hardware_remove))
        elif not has_card:
            pack_said = "no NVIDIA card in this PC — dictation runs on the processor"
        elif not facts.get("driver_ok", True):
            pack_said = "your NVIDIA driver is too old for it — update it, then come back"
        else:
            pack_said = f"off — it needs one extra download{psize}"
            buttons.append((f"Turn on faster dictation{psize}",
                            lambda: self._hardware_step("--install-pack", "gpu")))
        lines.append(("Faster dictation", pack_said))
        return lines, buttons

    def _speed_redownload(self) -> None:
        try:
            models_mod.remove(config_mod.load_layered().local.model)
        except Exception as e:            # noqa: BLE001
            self._note(str(e))
            return
        self._hardware_step("--download-model")

    def _speed_delete_model(self) -> None:
        try:
            gone = models_mod.remove(config_mod.load_layered().local.model)
        except Exception as e:            # noqa: BLE001
            self._note(str(e))
            return
        self._note("the model was deleted — dictation waits until it is downloaded again"
                   if gone else "there was no model folder to delete")
        if self.screen == "Settings":
            self._show("Settings")

    def _version_block(self, scroller) -> None:
        """Which code is running, what this PC is, and the two doors
        that belong to the app itself: Quit, and the tour again.
        Settings > About.

        It was the top half of THE APP until 2026-09-22, on a card that
        also held the update check, twenty sounds and a test
        notification — four unrelated things under a title that said
        nothing ("The app"). The updates went to General, where a person
        looks for them; the sounds went to the messages they belong to;
        and what is left here is the plain fact of which code is
        running, because that is the line he needs when he files a
        report against it.

        ONE VERSION, AND NOTHING HERE THAT CHANGES IT. There were two —
        classic and fast — and a row of "Switch to ..." buttons sat on
        this card to flip between them. He closed it on 2026-09-08: "I
        want only to be on this version that is already running." By
        then the second version had stopped existing on this machine
        anyway, so the only trip the button still offered was one
        backwards, into code older than what he was looking at.
        """
        card = ui.Card(scroller.inner, CW, 146, bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="D E S K I T", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)
        tk.Label(body, text="DeskIT", bg=ui.CARD,
                 fg=getattr(ui, "ACCENT_TEXT", ui.ACCENT),
                 font=(ui.DISPLAY, 17, "bold")).place(x=0, y=20)
        tk.Label(body, text=f"version {version.VERSION}" + (
                     f" - branch '{self.branch}' - running now"
                     if self.branch else ""),
                 bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=0, y=50)
        # THIS PC, as a fact and not a decision: it was the first line
        # of the model card until the model card became a place to press
        # things. Nobody sets their own number of cores.
        tk.Label(body, text=hardware_mod.machine_line(), bg=ui.CARD,
                 fg=ui.DIM, font=(ui.UI, 9), wraplength=CW - 260,
                 justify="left").place(x=0, y=74)

        # THE SAME DOOR AS THE BAR'S STOP, in one press, and it is here
        # as well because this is where the 25 seconds are written down —
        # the line under it says what stopping costs before anybody finds
        # out. Stop lived only here for one evening, until he said "I
        # don't have a button to shut down the model, I only have a
        # button to pause it".
        stop = ui.Button(body, "Quit DeskIT", self._quit, h=32,
                         w=widgets.button_width("Quit DeskIT", icon=True),
                         quiet=True, icon=ui.ICON["stop"])
        stop.place(x=CW - 36, y=20, anchor="ne")
        self.parts["stop"] = stop
        tk.Label(body, text="the whole app, keys included — the bar's Stop "
                            "only unloads the model",
                 bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8)).place(
            x=CW - 36, y=56, anchor="ne")
        # The tour again (D36): the four cards beside the dot that the
        # first start showed. Down the control pipe — the dot and the
        # card live in the running app.
        ui.Button(body, "Show the tour", self._show_tour, h=32, quiet=True,
                  w=widgets.button_width("Show the tour")).place(
            x=CW - 36, y=76, anchor="ne")
        scroller.bind_wheel(card)

    def _updates_block(self, scroller) -> None:
        """UPDATES on Settings > General (plan 11.4-11.5): what the last
        weekly look found, a Check now that ignores the cadence, and —
        only when a newer version exists — Download and install. Nothing
        downloads before that button; the checkout's row checks but never
        installs. The weekly switch is the real `privacy.update_check`
        settings row, drawn here beside the line it governs the way
        `dot.corner` is drawn beside Move the dot (BLOCK_PATHS).

        On General since 2026-09-22, his own list of what belongs there
        — and the mainstream one too: Windows, macOS, PowerToys, Zoom,
        Krisp and Signal all keep "check for updates" on the first page,
        not behind a page called About.
        """
        setting = settings_mod.find(self.parts.get("sections") or [],
                                    "privacy.update_check")
        tall = 36 + 26 + (44 if setting is not None else 0) + 36
        card = ui.Card(scroller.inner, CW, tall, bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="U P D A T E S", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)
        line = tk.Label(body, text=updates.status_line(), bg=ui.CARD,
                        fg=ui.FG, font=(ui.UI, 10), anchor="w",
                        wraplength=CW - 60, justify="left")
        line.place(x=0, y=22)
        self.parts["updates_line"] = line
        buttons = self._update_buttons()
        self.parts["updates_buttons"] = [label for label, _c in buttons]
        x = CW - 36
        for label, command in buttons:
            w = widgets.button_width(label)
            ui.Button(body, label, command, h=30, w=w, quiet=True,
                      bg=ui.CARD).place(x=x, y=18, anchor="ne")
            x -= w + 8
        if setting is not None:
            y = 56
            row = settings_mod.words_for(setting)
            tk.Label(body, text=row.label, bg=ui.CARD, fg=ui.FG,
                     font=(ui.UI, 10)).place(x=0, y=y)
            text, _lines = ui.clamp(row.help, ui.UI, 8,
                                    CW - 36 - CONTROL_W - 12, 2)
            tk.Label(body, text=text, bg=ui.CARD, fg=ui.FAINT,
                     font=(ui.UI, 8), justify="left").place(x=0, y=y + 21)
            value = self.parts["values"].setdefault(setting.path,
                                                    setting.value)
            switch = ui.Switch(body, bool(value),
                               lambda v, s=setting: self._apply_setting(s, v),
                               bg=ui.CARD)
            switch.place(x=CW - 36, y=y + 2, anchor="ne")
            self._register_row(setting, "switch", switch)
        scroller.bind_wheel(card)

    def _sounds_block(self, scroller) -> None:
        """Every cue the app makes, each with a Play button and the name
        of the thing it is FOR, plus the one button that puts a real
        card on the screen. Settings > Messages & sounds.

        THE SOUNDS ARE HERE BECAUSE HE COULD NOT TELL THEM APART. That is
        a filed complaint, and the answer to it is not a louder cue, it
        is a Play button next to the name of the thing the cue is for.
        They sat on "The app" until 2026-09-22; every app that was read
        keeps its sounds on the page of the messages they announce.
        """
        try:
            import cues as cues_mod
        except Exception:                 # noqa: BLE001 — no cues here
            cues_mod = None
        kinds = list(getattr(cues_mod, "CUES", {})) if cues_mod else []
        sound_rows = (len(kinds) + SOUND_COLUMNS - 1) // SOUND_COLUMNS
        card = ui.Card(scroller.inner, CW,
                       72 + (sound_rows * 30 + 8 if kinds else 0),
                       bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="E V E R Y   S O U N D   I T   M A K E S",
                 bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)
        ui.Button(body, "Send a test notification",
                  lambda: self._notify("test"), h=32, quiet=True,
                  w=widgets.button_width("Send a test notification",
                                         icon=True),
                  icon=ui.ICON["notify"]).place(x=CW - 36, y=0, anchor="ne")
        if kinds:
            column = (CW - 36) // SOUND_COLUMNS
            for index, kind in enumerate(kinds):
                cx = (index % SOUND_COLUMNS) * column
                cy = 44 + (index // SOUND_COLUMNS) * 30
                ui.Button(body, "▶", lambda k=kind: self._play_cue(k),
                          w=30, h=24, quiet=True, bg=ui.CARD).place(x=cx,
                                                                    y=cy)
                tk.Label(body, text=SOUND_WORDS.get(kind, kind), bg=ui.CARD,
                         fg=ui.DIM, font=(ui.UI, 9)).place(x=cx + 38,
                                                           y=cy + 4)
        scroller.bind_wheel(card)

    def _said_file_block(self, scroller) -> None:
        """WHAT YOU SAID on Settings > Privacy, right above the line that
        says how long it is kept: the file itself, one button away. It
        was a row on the FILES card two tabs away from its own setting
        (2026-09-22)."""
        card = ui.Card(scroller.inner, CW, 104, bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="W H A T   Y O U   S A I D", bg=ui.CARD,
                 fg=ui.FAINT, font=(ui.MEDIUM, 8)).place(x=0, y=0)
        tk.Label(body, text="Every dictation, translation and lookup, on "
                            "this PC only, in a file you can open and "
                            "delete yourself.",
                 bg=ui.CARD, fg=ui.FG, font=(ui.UI, 10),
                 wraplength=CW - 240, justify="left").place(x=0, y=22)
        ui.Button(body, "Open the file",
                  lambda: launch.open_path(paths.TRANSCRIPTS_LOG), h=30,
                  quiet=True, w=widgets.button_width("Open the file")
                  ).place(x=CW - 36, y=20, anchor="ne")
        scroller.bind_wheel(card)
    # ------------------------------------------------------------ updates

    def _update_buttons(self) -> list:
        """Check now always (the checkout too — it pulls, but it can look);
        with a newer version known, the one way to it: Download and
        install (the winget one-liner on that channel; nothing in the
        checkout). Release notes and Skip this version went on
        2026-09-21, the owner's first update: "only download — I want
        everyone on the same version; we are not at the stage of letting
        people choose". The one release that cannot be installed
        straight (11.10, too old) keeps its notes link: that is the door
        to the intermediate version, not a choice."""
        s = updates.status()
        rows = [("Check now", self._update_check)]
        rel = s["available"]
        if rel is None or s["mode"] in ("store", "off", "offline"):
            return rows
        if self._too_old_for(rel):
            rows.append(("Release notes", lambda r=rel: self._open_url(r.notes_url)))
            return rows
        if s["winget_command"]:
            rows.append(("Copy the winget command",
                         lambda c=s["winget_command"]: self._copy_text(c)))
        elif not paths.DEVELOPER:
            rows.append(("Download and install",
                         lambda r=rel: self._update_install(r)))
        return rows

    @staticmethod
    def _too_old_for(release) -> bool:
        """11.10: a release whose min_config_version is above this copy's
        files is not offered as a download — the notes say which
        intermediate version to install first."""
        try:
            import migrations
            return migrations.too_old_for(release.min_config_version)
        except Exception:                 # noqa: BLE001
            return False

    def _copy_text(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._note(f"copied: {text}")

    def _open_url(self, url: str) -> None:
        import webbrowser
        if url.startswith(("https://github.com/", "https://deskit-app.github.io/",
                           "https://huggingface.co/")):
            webbrowser.open(url)

    def _updates_say(self, text: str) -> None:
        """On the Tk thread: the row's line, and the buttons redrawn
        with the place when a version turned up."""
        line = self.parts.get("updates_line")
        if line is not None and line.winfo_exists():
            line.configure(text=text)
        self._note(text)

    def _update_check(self) -> None:
        self._updates_say("checking GitHub for a newer version…")
        drawn = list(self.parts.get("updates_buttons") or [])

        def work() -> None:
            try:
                updates.check(force=True)
            except Exception as e:                       # noqa: BLE001
                self._events.put(lambda: self._updates_say(f"the check failed ({e})"))
                return
            self._events.put(lambda: self._updates_say(updates.status_line()))
            # The buttons are drawn with the card, not with the line: a
            # check that changed the answer either way — a version turned
            # up, or the one on the card is gone (the owner's Check now
            # after his first update, 2026-09-21: "up to date", and
            # Download and install still under it) — redraws the screen.
            if self.screen == "Settings" and \
                    [label for label, _c in self._update_buttons()] != drawn:
                self._events.put(lambda: self._show("Settings"))
        threading.Thread(target=work, daemon=True, name="update-check").start()

    def _update_install(self, release) -> None:
        """Download, verify, start the installer, and ask the app to
        leave — plan 11.5. This window closes with it; Restart Manager
        would close it anyway."""
        self._updates_say(f"downloading DeskIT {release.version}…")

        def progress(done: int, total: int) -> None:
            pct = int(done * 100 / total) if total else 0
            self._events.put(lambda: self._updates_say(
                f"downloading DeskIT {release.version}… {pct}%"))

        def work() -> None:
            try:
                path = updates.download(release, on_progress=progress)
                self._events.put(lambda: self._updates_say(
                    "Installing… DeskIT will close and reopen"))
                updates.install(path, release, quit_app=singleton.request_quit)
            except Exception as e:                       # noqa: BLE001
                self._events.put(lambda: self._updates_say(str(e)))
                return
            self._events.put(lambda: self.root.after(1500, self.root.destroy))
        threading.Thread(target=work, daemon=True, name="update-install").start()

    def _play_cue(self, kind: str) -> None:
        """One sound, from THIS process. The app has its own cue player
        and asking it over the pipe would mean the sound only worked
        while it ran — and the reason this block exists is that he could
        not tell them apart, which is a question you ask sitting here."""
        try:
            import cues as cues_mod
            cues_mod.play(kind)
        except Exception as e:            # noqa: BLE001
            self._note(f"could not play that: {e}")

    # -- changing one

    def _browse_folder(self, setting) -> None:
        """Windows' own folder dialog for a folder setting, opened where
        the setting points now; the choice goes to the file through the
        same road a typed path takes."""
        from tkinter import filedialog
        current = self.parts["values"].get(setting.path, setting.value)
        try:
            start = paths.resolve_folder(str(current or "captures"))
        except Exception:                                    # noqa: BLE001
            start = paths.DATA_DIR
        chosen = filedialog.askdirectory(parent=self.root, title=settings_mod.label_for(setting.path),
                                         initialdir=str(start), mustexist=False)
        if not chosen:
            return
        chosen = str(Path(chosen))
        for kind, widget in self.parts.get("rows", {}).get(setting.path, []):
            if kind == "entry":
                widget.set(chosen)
                self._entry_done(setting, widget)
                return
        self._apply_setting(setting, chosen)

    def _entry_done(self, setting, entry) -> None:
        """Return, or the focus leaving: what is in the field goes to the
        file if it parses as the kind the file holds and differs from
        what is there."""
        try:
            raw = entry.get()
        except tk.TclError:
            return                        # the screen went away under it
        current = self.parts["values"].get(setting.path, setting.value)
        try:
            value = _parse(raw, setting.kind)
        except ValueError:
            self._paint_setting(setting.path, current)
            self._note(f'"{settings_mod.label_for(setting.path)}": '
                       f"{raw.strip()!r} is not "
                       f"a{'n' if setting.kind == 'int' else ''} "
                       f"{setting.kind}")
            return
        if value == current and type(value) is type(current):
            return
        self._apply_setting(setting, value)

    def _apply_setting(self, setting, value) -> None:
        """Through the running app when there is one — it writes the line
        and takes the change live where it can — and straight into the
        file otherwise."""
        if self.running:
            self._ask("option",
                      then=lambda r, s=setting, v=value:
                      self._setting_answered(s, v, r),
                      name=setting.path, value=value)
            return
        self._write_setting(setting, value)

    def _write_setting(self, setting, value) -> None:
        try:
            config_mod.save({setting.path: value})
        except Exception as e:
            self._paint_setting(setting.path, self.parts["values"].get(
                setting.path, setting.value))
            self._note(str(e))
            return
        if setting.path == "setup.autostart":
            # the Run value is this session's to write; with the app
            # stopped nobody else will (main.py re-asserts it at start)
            import autostart
            autostart.apply(bool(value))
        self.parts["values"][setting.path] = value
        self._paint_setting(setting.path, value)
        self._note(settings_mod.saved_sentence(setting.path, value,
                                               live=False))

    def _setting_answered(self, setting, value, reply) -> None:
        if reply is None:           # it stopped between the poll and the click
            self._write_setting(setting, value)
            return
        if not reply.get("ok"):
            self._paint_setting(setting.path, self.parts["values"].get(
                setting.path, setting.value))
            self._note(reply.get("error", "that did not work"))
            return
        self.parts["values"][setting.path] = value
        self._paint_setting(setting.path, value)
        self._note(reply.get("message")
                   or settings_mod.saved_sentence(setting.path, value))

    def _paint_setting(self, path: str, value) -> None:
        """Every control that shows `path` set to `value`, without any of
        them telling anyone."""
        for kind, widget in self.parts.get("rows", {}).get(path, []):
            try:
                if kind == "switch":
                    widget.set(bool(value))
                elif kind == "dropdown":
                    widget.set(value)
                elif kind == "entry":
                    # widget.set, not delete/insert: a ui.Field is a
                    # Canvas, and Canvas.delete/insert are about canvas
                    # ITEMS. `set` says it without telling anyone, the
                    # way ui.Dropdown.set does.
                    widget.set(_shown(value))
                    # A field that is showing its value cut goes back to
                    # cut, or the repaint would put 390 px of device name
                    # into a 264 px box again.
                    self._cut_field(widget)
            except tk.TclError:
                pass

    def _paint_settings(self) -> None:
        """The one value the running app can change on its own: the
        fullscreen auto-pause, which its status reports — and the dot
        card, which is not a value in the file at all but a picture of
        where the dot is right now.

        The dot card is painted BEFORE the "is there a status" guard: an
        app that has just stopped answering sends an empty status, and
        that is exactly the change the card most needs to hear about.
        """
        p = self.parts
        self._paint_dot()
        self._paint_account()
        self._paint_lock()
        self._paint_connections()
        if "rows" not in p or not self.status:
            return
        auto = self.status.get("auto_pause_fullscreen")
        if auto is None:
            return
        if p["values"].get("auto_pause_fullscreen") != bool(auto):
            p["values"]["auto_pause_fullscreen"] = bool(auto)
            self._paint_setting("auto_pause_fullscreen", bool(auto))

    def _settings_search_soon(self, text: str) -> None:
        if self._settings_after is not None:
            try:
                self.root.after_cancel(self._settings_after)
            except Exception:
                pass
        self._settings_after = self.root.after(
            SEARCH_MS, lambda: self._settings_search(text))

    def _settings_search(self, text: str) -> None:
        self._settings_after = None
        if not self._settings_searching or text == self._settings_query:
            return
        self._settings_query = text
        # ui.Field shows and hides its own placeholder on every keystroke
        # and on the focus moving; there is nothing to place by hand.
        self._fill_settings()

    # ------------------------------------------------- talking to the app

    def _poller(self) -> None:
        """One thread, one question, forever. Never touches a widget."""
        silent_since = None
        while not self.closing:
            reply = control.send("status", timeout_ms=1200)
            if reply is None and singleton.is_running():
                # The mutex is held but nothing answered. Usually that is
                # the gap between "the process exists" and "the control
                # channel is up", i.e. most of a startup — but it is also
                # what an instance launched BEFORE this window existed
                # looks like, and that one will never start answering. How
                # long it has been silent is what tells them apart.
                if silent_since is None:
                    silent_since = time.monotonic()
                reply = {"ok": True, "stage": "starting",
                         "activity": "starting",
                         "silent_s": time.monotonic() - silent_since}
            else:
                silent_since = None
            # The log is re-read only when it changed. Parsing it costs
            # about ten milliseconds; stat()ing it costs nothing, and most
            # polls happen with nobody dictating.
            stamp = history.stamp()
            # The window may have been closed and BURIED while send() was
            # out: _bury clears __dict__ and leaves only `closing` and
            # `_events` behind (see its docstring), so anything else read
            # from self past this point must first ask whether there is
            # still a self to read. Found the day the control pipe got its
            # per-copy name: with nothing listening, send() returns at
            # once instead of after a round trip, and this thread reached
            # `_log_stamp` a few microseconds after it was gone.
            if self.closing:
                return
            if stamp != getattr(self, "_log_stamp", stamp):
                self._log_stamp = stamp
                events = history.load(HISTORY_ROWS)
                self._events.put(lambda e=events: self._log_arrived(e))
            self._events.put(lambda r=reply: self._refresh(r))
            time.sleep(POLL_MS / 1000)

    def _log_arrived(self, events: list[history.Event]) -> None:
        self.log = events
        if self.screen == "Said":
            self._fill_history()
        elif self.screen == "Home":
            self._paint_rest()

    def _pump(self) -> None:
        """Everything that touches a widget runs here, on the Tk thread."""
        while True:
            try:
                self._events.get_nowait()()
            except queue.Empty:
                break
            except Exception:
                pass
        if not self.closing:
            self._pump_after = self.root.after(80, self._pump)

    def _ask(self, command: str, then=None, **args) -> None:
        """Send a command off-thread; hand the reply back on the Tk thread."""
        def work() -> None:
            reply = control.send(command, timeout_ms=4000, **args)
            if then is not None:
                self._events.put(lambda r=reply: then(r))
        threading.Thread(target=work, daemon=True).start()

    def _announce(self, reply: dict | None, fallback: str) -> None:
        if reply is None:
            self._note("dictation is not running")
        elif not reply.get("ok"):
            self._note(reply.get("error", "that did not work"))
        else:
            self._note(reply.get("message") or fallback)

    # ------------------------------------------------------------ buttons

    def _start(self) -> None:
        if singleton.is_running():
            self._note("it is already running")
            return
        self._note("starting — the model takes about 25 seconds to load")
        self._busy_until = time.monotonic() + 2
        if not launch.start_app():
            self._note("could not launch main.py — see app.log")

    def _stop(self) -> None:
        """The bar's Stop: the MODEL goes, the app stays (2026-09-18).

        "I don't have a button to shut down the model, I only have a
        button to pause it" (2026-09-07) — and, a week on, "many things
        don't need the model: screenshot, screen recording and a few
        more, and they don't work when the model is off". So Stop is
        exactly the first sentence now: the speech model and the
        microphone stream unload (main.py unload_model), the process,
        the hook, the dot and every feature that needs no model stay up,
        and Start loads the model again in ~25 s. Quitting the process
        is Settings > About > Quit DeskIT (_quit), or the shelf.

        ONE press, still: it used to take two from the bar, the first
        turning the word into "Stop again"; he read that word, could not
        tell what it was for, and said so twice. See _paint_bar_buttons.

        NEVER THE PROCESS, a start-up included. The first version quit
        during a start-up (the pipe refuses everything but quit then,
        and that used to be what Stop meant there) — and the first thing
        he did with it was press Stop at "Starting" to try the new
        unload, which killed the app, so no key worked and he reported
        Win+Shift+S dead (2026-09-18 22:19). Now the ask goes down the
        pipe whatever the stage: the app answers "still starting up —
        try again in a moment" until it is listening, and the note says
        so. A start he did not mean is Quit DeskIT's job.
        """
        self._busy_until = time.monotonic() + 1.5
        self._ask("unload", then=lambda r: self._announce(
            r, "unloading the model — every key that needs no model keeps "
               "working"))

    def _quit(self) -> None:
        """The whole process, in ONE press: Settings > About > Quit
        DeskIT. The named event, not the pipe: this has to work even if
        the control channel never came up, and during a start-up — the
        one place a quit is wanted before the models finish loading."""
        self._busy_until = time.monotonic() + 1.5
        if singleton.request_quit():
            self._note("quitting — the next start loads the model again, "
                       "about 25 seconds")
        else:
            self._note("nothing to stop")

    def _toggle_pause(self) -> None:
        """The button that is in the bar in every state. Start when
        nothing is running, Resume when it is paused, Pause when it is
        listening — three words on one key, because they are never
        available at the same time and three buttons would be two lies."""
        if not self.status:
            self._start()
            return
        model = self.status.get("model") or "on"
        if model in ("loading", "unloading"):
            self._note("the model is on its way — a moment")
            return
        self._busy_until = time.monotonic() + 1
        if model == "off":
            # the process is up with no model: Start loads it, ~25 s
            self._ask("load", then=lambda r: self._announce(
                r, "loading the model — about 25 seconds"))
            return
        self._ask("toggle", then=lambda r: self._announce(
            r, "paused" if (r or {}).get("paused") else "listening again"))

    def _copy(self, text: str) -> None:
        """The clipboard, from here rather than from the app: what is on
        screen came out of the log, and the log is readable with nothing
        running."""
        if not text:
            self._note("there is no text on that one")
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._note(f"copied {len(text)} characters")
        except Exception as e:
            self._note(str(e))

    def _copy_last(self) -> None:
        last = next((e for e in self.log if e.kind == "dictation"), None)
        if last and last.text:
            self._copy(last.text)
            return
        # Nothing in the log to copy: ask the app for whatever it is
        # holding, which is the only copy that exists if the write failed.
        self._ask("copy_last", then=lambda r: self._announce(r, "copied"))

    def _copy_phone(self) -> None:
        url = (self.status or {}).get("phone", "")
        if not url:
            self._note("no phone link — [server] enabled = false, or it is "
                       "not running")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self._note("phone link copied to the clipboard")

    # ------------------------------------------------------ rebinding keys

    def _capture(self, field: str, label: str) -> None:
        """Ask for a key by listening for one.

        The running app is PAUSED for the duration. Its hook is global, so
        without this, pressing Right Ctrl to bind it would start a
        recording, and pressing F9 would translate whatever happened to be
        selected in another window — the act of choosing a key would fire
        the key.
        """
        if self.running and not bool(self.status.get("paused")):
            # The reply is CHECKED. A pause that quietly failed would leave
            # the global hook live behind this dialog, so the key being
            # rebound fires for real: press the dictation key and a
            # recording starts, press the translate key and it rewrites
            # whatever is selected in the window underneath.
            reply = control.send("pause", timeout_ms=1500)
            if not (reply and reply.get("ok")):
                self._note("could not pause it to listen for a key — try "
                           "again in a moment")
                return
            self._paused_for_capture = True

        self._capturing = field
        self._paint_rebind()
        top = tk.Toplevel(self.root)
        top.title("Press a key")
        top.configure(bg=ui.BG)
        top.resizable(False, False)
        top.transient(self.root)
        top.geometry("380x232")
        _dark_caption(top)
        card = ui.Card(top, 340, 196, bg=ui.BG, pad=22)
        card.place(x=20, y=18)
        tk.Label(card.body, text=split_label(label)[0].upper(), bg=ui.CARD,
                 fg=ui.FAINT, font=(ui.UI, 8)).place(x=148, y=0,
                                                     anchor="n")
        prompt = tk.Label(card.body, text="Press the key you want",
                          bg=ui.CARD, fg=ui.FG, font=(ui.DISPLAY, 14, "bold"))
        prompt.place(x=148, y=22, anchor="n")
        tk.Label(card.body, text="Esc cancels.", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=148, y=52, anchor="n")
        done = {"value": False}

        def finish(key: str | None) -> None:
            if done["value"]:
                return
            done["value"] = True
            try:
                top.grab_release()
                top.destroy()
            except Exception:
                pass
            self._capturing = None
            self._paint_rebind()
            self._resume_after_capture()
            if key is not None:
                self._apply_key(field, key)

        # A chord arrives as TWO key events and the modifier comes first.
        # Binding whatever arrived first is what this used to do, and with
        # chords in the config it became dangerous rather than merely
        # wrong: reaching for ctrl+f6 bound "left ctrl", which
        # check_hotkeys accepts as a perfectly good bare key, and every
        # Ctrl+C the owner pressed afterwards would have fired the action.
        # So a modifier now only WAITS — and is bound on its release, if
        # nothing else was pressed while it was down, because binding a
        # bare modifier is still how the dictation key itself is set.
        # `name` is resolved on the PRESS and carried to the release, not
        # asked for again there. Which SIDE a modifier is on is answered
        # by GetAsyncKeyState (hotkey.side_down), and by the time the key
        # comes up nothing is down to read — asked on the release, every
        # bare modifier came back "left ctrl". `hotkey` ships as "right
        # ctrl", so that is the one binding this dialog exists to set.
        pending = {"mod": None, "name": None}

        def on_key(event) -> str:
            if event.keysym == "Escape":
                finish(None)
                return "break"
            name = hotkey_mod.binding_name_from_event(event.keysym,
                                                      event.keycode)
            if hotkey_mod.is_modifier_key(event.keycode):
                pending["mod"], pending["name"] = event.keycode, name
                prompt.config(text="…and now the key")
                return "break"
            pending["mod"] = None       # it became half of a chord
            if not name:
                prompt.config(text="Not a key this can use — try another")
                return "break"
            finish(name)
            return "break"

        def on_release(event) -> str:
            """A modifier let go with nothing pressed while it was down is
            the modifier itself — `hotkey = "right ctrl"` is set this way.

            event.state is not consulted anywhere here: it describes the
            moment BEFORE the event and carries no side at all, and the
            side is the whole point (right ctrl dictates, left ctrl does
            not).
            """
            if pending["mod"] != event.keycode:
                return "break"
            name = pending["name"]
            pending["mod"], pending["name"] = None, None
            if name:
                finish(name)
            return "break"

        row = tk.Frame(card.body, bg=ui.CARD)
        row.place(x=148, y=104, anchor="n")
        if field != "hotkey":       # the dictation key cannot be turned off
            ui.Button(row, "Turn this key off", lambda: finish(""),
                      w=150).pack(side="left", padx=(0, 8))
        ui.Button(row, "Cancel", lambda: finish(None), w=96,
                  quiet=True).pack(side="left")

        top.bind("<KeyPress>", on_key)
        top.bind("<KeyRelease>", on_release)
        top.protocol("WM_DELETE_WINDOW", lambda: finish(None))
        top.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width()
                                       - top.winfo_width()) // 2
        y = self.root.winfo_rooty() + 180
        top.geometry(f"+{max(0, x)}+{max(0, y)}")
        top.grab_set()
        top.focus_force()

    def _resume_after_capture(self) -> None:
        """Undo the pause the key dialog took — exactly once, from wherever
        that dialog's life happens to end.

        Not a try/finally inside _capture, because the way this goes wrong
        does not pass through _capture at all: closing the MAIN window
        destroys the dialog as a child, and Tk tears a Toplevel down
        without running its WM_DELETE_WINDOW handler. The app would be left
        paused with no window anywhere saying so — Right Ctrl dead, and the
        last line in app.log a pause from twenty minutes earlier.
        """
        if not self._paused_for_capture:
            return
        self._paused_for_capture = False
        control.send("resume", timeout_ms=1500)

    def _apply_key(self, field: str, key: str) -> None:
        """Live if it is running, straight to config.toml if it is not.

        Both paths validate first — a key that collides with another one is
        refused with a sentence, not written down and discovered at the
        next launch.
        """
        if self.running:
            self._ask("rebind", then=lambda r: self._announce(
                r, config_mod.rebound_sentence(field, key)),
                field=field, key=key)
            return
        try:
            current = config_mod.load_layered()
            # with_field, not a bare replace: most keys live at the top
            # level, but some (visual_qa_hotkey, and both capture keys)
            # are nested in their section, and replace() cannot assign
            # through that. One helper, both this window and main.rebind.
            config_mod.check_hotkeys(config_mod.with_field(current, field,
                                                           key))
            write_key = NESTED_HOTKEYS.get(field, field)
            config_mod.save({write_key: key})
            self._note(config_mod.rebound_sentence(field, key))
            self._refresh(None)
        except Exception as e:
            self._note(str(e))

    # ------------------------------------------------------------ painting

    def _read_keys(self) -> dict:
        """The keys as they are on disk — what to show when nothing is
        running to ask."""
        try:
            cfg = config_mod.load_layered()
        except Exception:
            return {}
        keys = {name: getattr(cfg, name)
                for name, _label in config_mod.HOTKEY_FIELDS}
        keys["_auto"] = cfg.auto_pause_fullscreen
        return keys

    def _look(self) -> tuple[str, str]:
        status = self.status
        stage = status.get("stage", "")
        starting = bool(status) and stage == "starting"
        deaf = starting and status.get("silent_s", 0) > 45
        model = status.get("model") or "on"
        activity = ("ready" if deaf else
                    "starting" if starting else
                    "stopped" if not status else
                    "off" if model == "off" else
                    "loading" if model in ("loading", "unloading") else
                    status.get("activity") or "ready")
        # Remembered for the breathing loop, which runs between polls and
        # has no status of its own to derive it from.
        self._activity = activity
        return _look_colours(activity)

    def _breathe(self) -> None:
        """The status lamp, breathing.

        Ninety milliseconds a frame, and the glow is quantised inside
        ui.lamp, so a whole breath is a dozen cached bitmaps being swapped
        onto two Labels — no drawing happens per frame. `_glow` says how
        bright this frame is and `_paint_chip` puts it on; both are used
        by `_refresh` too, so the colour never waits for a breath.
        """
        if self.closing:
            return
        colour, _word = _look_colours(self._activity)
        self._paint_chip(colour)
        self._breath_after = self.root.after(90, self._breathe)

    def _glow(self) -> float:
        """How bright the lamp's halo is this frame.

        The rhythm carries the meaning: quick and bright while RECORDING
        (the state that costs something if missed), slower while
        transcribing, a long calm swell while merely listening. Paused
        and off get ZERO — no halo at all, which is the spec's one hard
        rule about the dot and the way "inert" is told from "quiet" at a
        glance."""
        if not _has_halo(self._activity):
            return 0.0
        rhythm = {"recording": (1.2, 0.30, 0.85), "locked": (1.2, 0.30, 0.85),
                  "busy": (1.9, 0.28, 0.68), "ready": (3.6, 0.34, 0.54)}
        beat = rhythm.get(self._activity)
        if beat is None:
            return 0.45
        period, low, high = beat
        wave = 0.5 + 0.5 * math.sin(time.monotonic() * 2 * math.pi / period)
        return low + (high - low) * wave

    def _paint_chip(self, colour: str) -> None:
        """The lamp, the word and the uptime onto the chip in the bar."""
        try:
            chip = self.parts.get("chip")
            if chip is not None and chip.winfo_exists():
                chip.set(colour, self.parts["state"].cget("text"),
                         self.parts["uptime"].cget("text"), self._glow())
        except tk.TclError:
            pass                      # a screen swap mid-frame: skip one

    def _explain(self) -> str:
        """The sentence under the state word — what it means and what to do
        about it, which is the whole reason this window exists."""
        status = self.status
        stage = status.get("stage", "")
        starting = bool(status) and stage == "starting"
        if not status:
            return ("Not running. Start it and the keys come alive; the "
                    "first start loads two Whisper models onto the GPU and "
                    "takes about 25 seconds.")
        if starting and status.get("silent_s", 0) > 45:
            return ("Running, but not answering this window — it was "
                    "started before the dashboard existed. Stop and start "
                    "it to get pause and the key changes.")
        if starting:
            return status.get("note") or "loading the models…"
        if status.get("paused"):
            return ("Keys are inert — the models are still loaded, so "
                    "resuming is instant.")
        if (status.get("awake") or {}).get("dark"):
            return ("The screens are off and the machine stays awake. The "
                    "Awake screen, or the screens key, brings them back.")
        if status.get("note"):
            return status["note"]
        keys = status.get("keys") or self._read_keys()
        dictate = pretty_key(keys.get("hotkey", ""))
        latch = pretty_key(keys.get("latch_hotkey", ""))
        line = f"Hold {dictate} and speak — release, and the text lands at "               f"your cursor."
        if latch != "off":
            line += f" Tap {latch} while holding to lock the recording on."
        return line

    def _refresh(self, reply: dict | None) -> None:
        if self.closing:
            return
        if time.monotonic() < self._busy_until and reply is not None:
            # A command was just sent. Its effect has not necessarily
            # reached the app yet, and repainting from a pre-command status
            # would flip the buttons back for one frame.
            return
        self.status = reply or {}
        stage = self.status.get("stage", "")
        self.running = bool(reply) and stage == "running"
        # Before anything is drawn: this window may not be on screen at
        # all — it hid itself so he could drag the dot — and deciding
        # whether to come back is the first thing a fresh status is for.
        if self._dot_waiting:
            self._dot_returns()
        # And whether there is a desk to draw at all (Q1): no account on
        # this PC while one is required is the landing, whatever screen
        # was up; a session arriving — through the app, or through this
        # window's own sign-in when the app is not running — takes it
        # down again and opens on Home.
        locked = self._locked_now(reply)
        if locked != self._landing_up:
            self._landing(locked)

        colour, word = self._look()
        self.parts["state"].config(text=word)
        uptime = self.status.get("uptime_s")
        self.parts["uptime"].config(
            text=f"up {human_time(uptime)}" if uptime else "not running")
        # THE LAMP IS PAINTED HERE, not only by the breathing loop. It
        # used to be _breathe's alone, and _breathe returns at once while
        # `closing` is set — so a window built for a screenshot, or any
        # frame between the first _refresh and the first breath, showed a
        # grey dot beside the word "Listening". A state and its colour
        # have to arrive together.
        self._paint_chip(colour)
        keys = self.status.get("keys") or self._read_keys()
        dictate = pretty_key(keys.get("hotkey", ""))
        self.parts["hint"].config(text=f"hold {dictate}" if dictate != "off"
                                  else "no dictation key set")

        # Which buttons the bar holds and what each of them says are ONE
        # decision — the word on the run key is the only thing that tells
        # Start's state from Pause's — so both live in one method.
        self._paint_bar_buttons()
        self._lock_tick()
        {"Home": self._poll_waiting,
         "Corrections": self._poll_corrections,
         "Said": lambda: None,
         "Keys": self._paint_keys,
         "Settings": self._paint_settings,
         "Network": self._paint_network,
         "Landing": self._paint_landing}[self.screen]()

    # --------------------------------------------- the signed-out landing (Q1)

    LANDING_SENTENCE = ("Hebrew dictation for Windows that stays on your PC. Hold a "
                        "key, speak, let go — the Hebrew lands at the cursor, in any "
                        "window.")
    # 2026-09-23: this said "Your keys never travel there. Every sync
    # stays off until you turn it on yourself, on its own card" — and the
    # button under it runs privacy.sign_in_grants, which turns both syncs
    # on. The words the wizard's account page says, said here too.
    LANDING_STORED = ("What is stored: an account id and the e-mail of the Google "
                      "account you choose; this PC's name, the app's version and "
                      "Windows'. The server is DeskIT's own (Supabase, Frankfurt). "
                      "Only your voice never leaves this PC: your learned words and "
                      "settings are kept in your account, and so are what you said "
                      "and your cloud keys, locked with a key only your own PCs hold. "
                      "Settings > Privacy > Withdraw turns this off.")

    def _locked_now(self, reply: dict | None) -> bool:
        """Is there an account on this PC? The app's word when it
        answers (status()["locked"] — it holds the session); sb.py's own
        when it does not, since the session blob is this user's, not
        the app's, and the landing must not depend on the model being
        loaded to know whether anyone is signed in."""
        if reply:
            return bool(reply.get("locked"))
        try:
            import sb
            return bool(sb.REQUIRED and sb.configured() and not sb.signed_in())
        except Exception:                                    # noqa: BLE001
            return False

    def _landing(self, up: bool) -> None:
        """The owner's rule (2026-09-18, after the first live sign-out):
        "when I sign out I want to drop to a page that shows nothing —
        not Home, Corrections, Problems, Said, Keys, Settings — just a
        landing screen with a sentence about the app and a sign-in
        button, and only that until I sign in." So the places leave the
        bar, the sheet is one card, and the way in is the one button the
        wizard's own page has. The state chip and the run buttons stay:
        they are the app's, not the desk's, and Stop still has to work."""
        self._landing_up = up
        if up:
            self.nav.place_forget()
            self._show("Landing")
        else:
            self.nav.place(x=PAD + 32, y=17)
            self._show("Home")

    def _screen_landing(self) -> None:
        p = self.parts
        card_w, card_h = 640, 372
        card = ui.Card(self.sheet, card_w, card_h, bg=ui.BG, pad=36, radius=18)
        card.place(x=(W - card_w) // 2, y=(H - TOP - card_h) // 2 - 20)
        body = card.body
        inner = card_w - 72
        mark = ui.icon_bitmap(ICON_PNG, 56, ui.CARD)
        if mark is not None:
            self._keep.append(mark)
            tk.Label(body, image=mark, bg=ui.CARD).place(x=0, y=0)
        tk.Label(body, text=f"DeskIT {paths.DEV_TAG}".strip(), bg=ui.CARD, fg=ui.FG,
                 font=(ui.DISPLAY, 22, "bold")).place(x=70, y=8)
        tk.Label(body, text=self.LANDING_SENTENCE, bg=ui.CARD, fg=ui.FG,
                 font=(ui.UI, 11), wraplength=inner, justify="left",
                 anchor="w").place(x=0, y=76)
        tk.Label(body, text="Sign in once; this PC remembers you until you sign out.",
                 bg=ui.CARD, fg=ui.DIM, font=(ui.UI, 10), wraplength=inner,
                 justify="left", anchor="w").place(x=0, y=134)
        button = ui.Button(body, "Sign in with Google", self._landing_sign_in,
                           bg=ui.CARD, primary=True, w=210, h=38)
        button.place(x=0, y=170)
        p["landing_button"] = button
        p["landing_line"] = tk.Label(body, text="", bg=ui.CARD, fg=ui.DIM,
                                     font=(ui.UI, 10), wraplength=inner,
                                     justify="left", anchor="w")
        p["landing_line"].place(x=0, y=220)
        tk.Label(body, text=self.LANDING_STORED, bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8), wraplength=inner, justify="left",
                 anchor="w").place(x=0, y=250)
        self._landing_seen = None
        self._paint_landing()

    def _paint_landing(self) -> None:
        """Every poll: the line under the button follows the app's
        account status — the browser wait, the last error — and says
        nothing when the app is not running, since then the sign-in is
        this window's own (_landing_sign_in) and it writes the line."""
        line = self.parts.get("landing_line")
        if line is None or not line.winfo_exists():
            return
        info = self.status.get("account") if self.status else None
        if info is None:
            return                          # the window's own words stand
        if info.get("busy") == "waiting for the browser":
            said, colour = ("Waiting for Google's sign-in page in your browser…",
                            ui.DIM)
        elif info.get("last_error"):
            said, colour = f"Not signed in: {info['last_error']}"[:200], ui.AMBER
        else:
            said, colour = "", ui.DIM
        if (said, colour) != getattr(self, "_landing_seen", None):
            self._landing_seen = (said, colour)
            line.configure(text=said, fg=colour)

    def _landing_sign_in(self) -> None:
        """[Sign in with Google] on the landing. Through the running app
        when there is one (it holds the session and unlocks itself); in
        this process when there is none — the wizard's own way: the
        consent row first, this card being the card, then the browser
        and the loopback listener (sb.sign_in_google). Either way the
        next poll sees the session and takes the landing down."""
        line = self.parts.get("landing_line")
        if self.status:
            self._busy_until = time.monotonic() + 1
            self._ask("account", then=lambda r: self._announce(r, "opening the browser"),
                      do="google")
            return
        if getattr(self, "_landing_signing", False):
            return
        self._landing_signing = True
        if line is not None:
            line.configure(text="Waiting for Google's sign-in page in your browser…",
                           fg=ui.DIM)

        def work() -> None:
            try:
                import privacy
                import sb
                privacy.sign_in_grants()      # the account, and the sync it promises
                who = sb.sign_in_google()
                self._events.put(lambda: self._landing_done(who, None))
            except Exception as e:                             # noqa: BLE001
                self._events.put(lambda e=e: self._landing_done(None, str(e)))

        threading.Thread(target=work, daemon=True, name="landing-signin").start()

    def _landing_done(self, who: dict | None, error: str | None) -> None:
        self._landing_signing = False
        line = self.parts.get("landing_line")
        if line is None or not line.winfo_exists():
            return
        if error:
            line.configure(text=f"Not signed in: {error}"[:200], fg=ui.AMBER)
        else:
            line.configure(text=(f"Signed in as {who.get('email')}" if who and who.get("email")
                                 else "Signed in"), fg=ui.GREEN)
        # the poll takes the landing down on its next tick; no waiting
        self._refresh(None if not self.status else self.status)

    # ------------------------------------------------------------ shutdown

    def _close(self) -> None:
        # THE X CLOSES EVERYTHING. Until 2026-09-19 this window was a remote
        # control and its X left the app running — the owner walked a fresh
        # copy, closed the desk, and the screenshot key still answered:
        # "make sure the X closes completely everything it runs in the
        # background". So the desk's X is Quit DeskIT (the same named
        # event as Settings > About > Quit) — only for the desk a person
        # opened (`_looping`: the entry point's run), never for a window a
        # test or a picture built, and never on Restart, whose new copy is
        # already on its way. It must not leave the app PAUSED either,
        # which is what closing it on top of an open key dialog used to do.
        self.closing = True
        if getattr(self, "_looping", False) and not getattr(self, "_relaunch", False):
            try:
                singleton.request_quit()
            except Exception:                            # noqa: BLE001
                pass
        self._resume_after_capture()
        for pending in (self._pump_after, self._toast_after,
                        self._search_after, self._rows_after,
                        self._slide_after, self._breath_after):
            try:
                if pending is not None:
                    self.root.after_cancel(pending)
            except Exception:
                pass
        if getattr(self, "_hold", None) is not None:
            self._hold.close()
        try:
            self.root.destroy()
        except Exception:
            pass
        # A window that was never given a mainloop - every one the test
        # suite builds - has no run() to bury it, so it does it here.
        if not getattr(self, "_looping", False):
            self._bury()

    def _bury(self) -> None:
        """Delete the Tcl interpreter HERE, on the thread that built it.

        destroy() does not delete it; the interpreter goes when the tkapp
        is deallocated. A Tk widget tree is cyclic, so refcounting never
        does that - the generational collector does, on whichever thread
        trips the allocation threshold, and Tcl aborts the process when
        that is not the creating thread. visual_qa.py lost the whole app
        to this three times in one evening.

        This window was SAVED by an accident until now: ui._cache and
        ui._FONTS are module globals holding PhotoImages and Fonts, each
        of which holds the tkapp, so the interpreter was PINNED rather
        than garbage - and pinned is safe. But the next Dashboard's
        __init__ calls ui.forget_images(), which drops that pin while
        this window's cycle is still uncollected. From that instant the
        old interpreter is reachable only through a cycle, and whichever
        thread next runs a full collection executes Tcl_DeleteInterp.
        Reproduced: exit code 3, Tcl_AsyncDelete, no traceback.

        Clearing __dict__ rather than naming attributes is deliberate.
        This window has dozens of widget attributes and any list of them
        would rot the first time someone added a screen; what matters is
        only that NOTHING here still points at the tree when the collect
        runs.
        """
        try:
            ui.forget_images()
        except Exception:
            pass
        # Three survivors, and only three. The poller and the reopen
        # watcher are daemon threads that notice they should stop by
        # reading self.closing, and they post into self._events on their
        # way out; take those away and they die on an AttributeError
        # instead of ending. And _relaunch is Restart's one word to
        # main(), read after this window is gone. Neither a bool nor an
        # empty queue holds a widget, so the tree is still unreachable
        # and the collect below still frees the interpreter.
        keep = {"closing": True, "_events": queue.Queue(), "_looping": False,
                "_relaunch": bool(getattr(self, "_relaunch", False))}
        self.__dict__.clear()
        self.__dict__.update(keep)
        gc.collect()

    def run(self) -> bool:
        """The window, until it closes. True when it closed because
        Restart asked for a new copy of it — main() acts on that only
        once the instance mutex is released, which is why the answer is
        returned rather than acted on here."""
        self._looping = True
        try:
            self.root.mainloop()
        finally:
            self._looping = False
            self._bury()
        return bool(self.__dict__.get("_relaunch"))


def bring_up_the_keys() -> bool:
    """Nothing running when the desk opens: the app comes up behind the
    window (launch.start_app → main.py --quiet), the model with it
    unless Settings > General says not to ([local] load_at_start; the
    owner, 2026-09-20: "no problem with the model loading by itself —
    make that the default, with a way off in Settings"; until then the
    desk started it without the model and Start loaded it). Every key
    that needs no model works from the moment the window is on screen
    either way. Here, in the entry point, and not in Dashboard.__init__:
    a window built for a test or a picture must never spawn a process."""
    try:
        if singleton.is_running():
            return False
        return bool(launch.start_app())
    except Exception:                                    # noqa: BLE001
        return False


def main() -> int:
    """One window, however many times the shortcut is clicked.

    A .vbs behind a shortcut has no notion of "already open", so every
    double-click used to start another Python process and put another
    identical window on screen — each polling the same app, each able to
    change the same keys. Nothing broke, but the thing looked broken.

    A second launch signals the first and exits, so clicking the icon
    behaves the way clicking a taskbar button does: it brings the window
    you already have to the front.

    And that is exactly why Restart's new copy is opened HERE, after the
    mutex is released, and not by the window before it closes: a copy
    started while this process still held the mutex would be that
    second launch — it would poke a window that is on its way out and
    exit, and he would be left with no dashboard at all.
    """
    try:
        lock = singleton.InstanceLock(singleton.DASHBOARD_MUTEX)
    except singleton.AlreadyRunning:
        singleton.signal(singleton.DASHBOARD_SHOW)
        return 0
    try:
        bring_up_the_keys()
        again = Dashboard().run()
    finally:
        lock.release()
    if again:
        _relaunch_dashboard()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
