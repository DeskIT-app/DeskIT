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
import threading
import time
import tkinter as tk
from pathlib import Path

import config as config_mod
import control
import history
import hotkey as hotkey_mod
import keyboard as keyboard_mod
import launch
import awake as awake_mod
import reading as reading_mod
import settings as settings_mod
import singleton
import summary
import ui
import widgets

APP_DIR = Path(__file__).resolve().parent
import paths
DEFAULTS_PATH = paths.DEFAULTS_FILE
ICON_PATH = APP_DIR / "icon.ico"
ICON_PNG = APP_DIR / "icon.png"

# Any string, as long as it is OURS and stays put. Windows groups taskbar
# buttons and picks their icon by this; without one the window inherits
# pythonw.exe's identity, which is why the taskbar showed a generic file
# icon rather than the app's.
APP_ID = paths.APP_ID + ".Dashboard"

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
BAR_GAP = 12
BAR_KEEP = 24
# The nightly run's own Stop, which is in the bar only while a nightly
# test run is going — see _paint_bar_buttons for what pays for it.
BAR_TESTS_W = 96

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
}

POLL_MS = 800
# How long this window stays hidden waiting for the dot to be dragged
# before it comes back whether or not anything happened. The APP gives up
# first — overlay.DOT_MOVE_S is 45 s and its next status says so, which
# is what normally ends the wait — so this is only the backstop for an
# app that stops answering mid-drag. A window that hid itself and never
# came back is a worse bug than a drag that had to be asked for twice.
DOT_WAIT_S = 75.0
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
PILE_Y = 100             # where the page starts, under the title
PAGE_H = H - TOP - PILE_Y - 62      # down to the footer rule

# THE DOORS ARE A BAND, AND THE BAND IS ALWAYS THERE. They were one thin
# 26 px line of counts that drew only the kinds with something waiting,
# so on a quiet desk it drew NOTHING — and the home was a headline, three
# one-line rows of the day, and 300 px of bare ground under them with the
# footer rule sitting on nothing. His words on 2026-09-07: "the home
# screen looks very empty and not good". A count that exists only when it
# is not zero cannot hold a page together. So all five places are on the
# band, always, each with what it is holding at this moment, and each of
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

# THE CORRECTIONS PLACE HAS TWO TABS. Waiting is what it always was —
# the second reading's proposals, with the vocabulary beside them. Read
# aloud is reading.py: one of his own sentences on a card, read into
# the dictation key with this window in front, and kept under the words
# on the card. It lives here and not as a seventh word in the bar
# because the bar has no room for one: measured 2026-09-13, seven
# places at gap 14 run under the state chip by 3 px the moment a nightly
# run puts Stop tests in the bar. The two are one place because they
# are one story — the words it learned from him, and the voice it is
# learning from him.
CORR_TABS = (("waiting", "Waiting"), ("read", "Read aloud"))


def corr_tabs() -> tuple:
    """The Corrections tabs this copy shows: Read aloud is the owner's
    corpus tool (reading.py) and is not in the product (D15, PR 7)."""
    return CORR_TABS if paths.DEVELOPER else CORR_TABS[:1]
CORR_CHIPS_Y = 62
CORR_HEAD_Y = 110        # the "N proposals" line, under the chips
CORR_PAGE_Y = 140
READ_CARD_Y = 112
READ_PAD = 24            # the sentence card's own padding
READ_ARM_EVERY_S = 3.0   # how long before an unanswered arm is sent again
READ_ARM_GRACE_S = 1.5   # how long a just-sent arm is taken on trust
READ_DIR = paths.READ_DIR
READ_TEXTS = READ_DIR / reading_mod.TEXTS   # the prose he reads, a file each
CORPUS_DIR = paths.CORPUS_DIR

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
SOUND_COLUMNS = 5
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
#   Corrections  the second reading's proposals, and the words it has
#                learned from them (his: "the vocabulary and all the
#                corrections it does automatically") — and, on a second
#                tab, Read aloud: his own sentences read to it one at a
#                time, kept as (voice, text) pairs (CORR_TABS, reading.py)
#   Problems     what he reported, the routine's questions, what is on
#                this computer and not on GitHub — everything that needs
#                more than a line
#   Said         transcripts.log read back, with the search
#   Keys         every binding, lit on a drawn keyboard
#   Settings     config.toml, on tabs
#
# Overview is gone: its state line is in the top bar now, on every place.
NAV = (("home", "Home"), ("corrections", "Corrections"),
       ("problems", "Problems"), ("said", "Said"),
       ("keys", "Keys"), ("settings", "Settings"))

# A place takes its glyph from ui.ICON[key] where there is one. Home,
# Corrections, Problems and Said are new words for old screens, and
# ui.py is not this wave's file, so they borrow the glyphs those
# screens had — HERE, rather than the one table that names the places
# having to call them "overview" and "review". A key with no glyph and
# no entry here is still a KeyError the first time the bar is built,
# which is the point.
NAV_GLYPH = {"home": "overview", "corrections": "review",
             "problems": "error", "said": "history"}

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
# A field is drawn as a ui.Field — a rounded Pillow face with the Entry
# flat inside it — at exactly the height ui.Dropdown is, because the two
# alternate down the same column and a field one pixel shorter than the
# menu above it reads as a mistake. The owner, 2026-09-07: "the boxes are
# square in everything that is not in General, and it is not pretty."
ENTRY_H = 30
# The quiet line at the foot of a folded card: "7 more in this section".
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

    The name comes from keyboard.name_for, which is the name the app
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
    """
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
        wscript = str(Path(os.environ.get("SystemRoot", r"C:\Windows"))
                      / "System32" / "wscript.exe")
        values = (
            (5, APP_ID),                                        # ...ID
            (2, f'"{wscript}" "{APP_DIR / "Dashboard.vbs"}"'),  # ...Command
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

# The question row's words, numbers and one RULE, and answer_card owns
# every one of them. The card the app pops up and the row on this screen
# are TWO SURFACES ON ONE QUESTION — he may answer either — so the moment
# they disagree about how many options there can be, what the button
# says, how tall the box is or when it is allowed to send, one of them is
# lying about the other. Read off that module rather than typed again
# here, which is the same trade the FIELD_* block above makes with
# problem_card and answer_card itself makes with both.
#
# ITS KEYS LINE IS DELIBERATELY NOT BORROWED, and that is answer_card's
# own reasoning about problem_card.KEYS applied one step further: half
# that line is about a modal — digits bound to a card that holds the
# keyboard, Esc taking that card down — and this is a row in a list with
# five other rows and no keyboard of its own. A line naming keys that do
# nothing here is how a shortcut stops being trusted. The clauses the two
# surfaces DO share are spelled out below, and tests.py is the place to
# assert they still match.
try:
    import answer_card as _ac
except Exception:                         # noqa: BLE001 — feature absent
    _ac = None

Q_OPTIONS_MAX = getattr(_ac, "OPTIONS_MAX", 5)
Q_SEND_LABEL = getattr(_ac, "SEND_LABEL", "Send")
# Two lines where the report box takes three, because answer_card lowered
# its own floor for a reason that holds here too: this box is usually one
# clause he is adding to an answer he already pressed, not a paragraph he
# is composing from nothing.
Q_FIELD_LINES_MIN = getattr(_ac, "FIELD_LINES_MIN", 2)
# THE PERMISSION SLIP, in the card's words. A box under a list of choices
# reads as the alternative to them — press a row OR write, one of the
# two — which is exactly the shape he threw out. This is the one faint
# line that says the geometry's quiet part out loud.
Q_FIELD_CAP = getattr(_ac, "FIELD_CAP",
                      "In your own words — add to a choice, or answer "
                      "instead.")


def _nightly():
    """nightly.py, the owner's nightly test run (DISTRIBUTION_PLAN.md
    D15). It is not in the product build, so it is imported here — on
    the poll that asks whether a run is going, on the Stop press — and
    never at start: a copy without the file must open this window.
    test_product_suite_imports_no_dev_modules holds the line."""
    import nightly
    return nightly


def _answerable(choice, typed: str) -> bool:
    """Whether the store would take this as an answer, which is the only
    thing that may light the Send button.

    THE RULE ITSELF IS IMPORTED, not just the numbers around it: a choice
    or words or both, and only both-empty refuses. answer_card.answerable
    is that rule and questions.Store.answer is what enforces it, so a
    button that armed where the store refuses would teach him to press
    something that does nothing, and one that stayed dark where the store
    accepts would hide an answer he had already given. The fallback is
    the same sentence in Python, for the tree where the card's module is
    not here at all.
    """
    card = {"choice": choice, "typed": typed or ""}
    if _ac is not None:
        try:
            return bool(_ac.answerable(card))
        except Exception:                 # noqa: BLE001
            pass
    return choice is not None or bool(str(typed or "").strip())


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


# The question card's own numbers. The FIELD in it is the report box's
# field — the block above owns those metrics and problem_card owns that
# block — because it is the same field doing the same job: he types or
# dictates a sentence into it and reads the echo back underneath. Only
# the room around it is this card's.
Q_INDENT = 18            # how far a question sits in under its report
Q_PAD = 14               # the card's own margin
Q_MARK = 26              # the room the pick dot takes at the left of a band
Q_BAND_MIN = 34          # an option band is at least this tall
Q_ECHO_LINES = 2         # how much of the echo stays on screen
Q_POLL_MS = 80           # how often the field is read (the card uses 60)
# The Text sits this far inside its painted well. At FIELD_RADIUS 9 the
# arc passes 2.6 px from the corner, so 3 px in is inside the curve and
# no square nub of the field pokes out of the rounding — measured for the
# report box, and the same well is painted here.
Q_WELL_INSET = 3

# ---------------------------------------------------------------------------
# git, for what is on this computer and not on GitHub
# ---------------------------------------------------------------------------
#
# Every change to this app — the Saturday routine's and any Claude
# session's — is committed straight onto `main` in this folder, and
# whoever made it NEVER pushes it. The folder always stands on `main`.
# He restarts, tries the change, and then either pushes it or throws it
# away, and each of those is a button on the Problems tab. This is the
# plumbing under the three buttons. His decision, 2026-09-12.
#
# THE OLD SHAPE, AND WHY ITS GUARD WAS WRONG. Until that day the routine
# built on a branch, weekly/<DATE>, this block listed those branches, and
# Push sent the branch up and then merged it into `main` — behind a guard
# that refused the merge if `main` held any commit GitHub lacked. The
# guard reasoned that THE ROUTINE NEVER COMMITS TO `main`, so such a
# commit had to be another session's half-finished work, and publishing
# the branch onto `main` would carry it up. True of the routine; false of
# how he actually works. To TRY a change he has to run it, the app runs
# out of this folder, and this folder stands on `main` — so the moment a
# session moved the work onto `main` so that he could try it (his need,
# and the only way to meet it), the guard saw a commit GitHub lacked and
# the button refused the very work he was trying to push. A guard that
# fires on the ordinary case is not a guard. What replaces it is simpler
# and true: everything on `main` that GitHub lacks IS the work, all of it
# his to push or to undo, and the one refusal left is the one that keeps
# `git push` from ever wanting --force (see push_main).
#
# CREATE_NO_WINDOW on every call, for the reason versions.py measured:
# git is a console program, this window runs under pythonw, and a spawn
# without the flag ALLOCATES A CONSOLE — visible flicker and hundreds of
# milliseconds, on whichever thread asked. capture.py:1683 says the same
# where it opens explorer.
# WHERE EVERYTHING GOES HOME TO. It was "fast" until 2026-09-08, and that
# name was a leftover: `fast` meant "the fast one OF THE TWO", against a
# `classic` that no longer exists. With one version the word said nothing
# true, and the owner asked for it to go - "you can also change the name
# to classic or whatever you want". "main" carries no claim about a
# repair pass, which is the point.
TRUNK = "main"
GIT_READ_S = 20                # a local read
GIT_NET_S = 180                # a push or a fetch, over his connection
_CREATE_NO_WINDOW = 0x08000000
# How many of the commits the card lists before "+N more". Eight lines
# is a week of the routine's work with room to spare; past that the
# list is not being read, it is being scrolled past.
CHANGES_SHOWN = 8
# How long Restart waits for the app to let go of its mutex before it
# gives up. The models unload in a second or two; twenty is for a paste
# or a recording that is still finishing, and past twenty the app is not
# stopping and a second copy would only be refused by the mutex anyway.
APP_QUIT_WAIT_S = 20.0
# Beside the routine's own run.log, and not beside app.log, for a reason
# that is not tidiness: problems\ is gitignored and the repo root is not,
# so a log file up there would show as an untracked path in every other
# session's `git status` — and versions._assert_switchable refuses a
# whole-app switch on exactly that.
PUSH_LOG = APP_DIR / "problems" / "weekly" / "push.log"
PUSH_LOG_MAX = 200_000


def _push_log(text: str) -> None:
    """Every git call this window makes, on the disk.

    A refusal has to be readable an hour later — a toast is gone in nine
    seconds — and the "app" logger reaches nothing in this process: the
    dashboard never calls main.setup_logging, so it has no handlers. So
    the file is the record and the logger is the bonus for whoever gives
    this process handlers later. A log that cannot be written is not a
    failure of the push.
    """
    import logging

    logging.getLogger("app").info("push: %s", text)
    try:
        PUSH_LOG.parent.mkdir(parents=True, exist_ok=True)
        if PUSH_LOG.exists() and PUSH_LOG.stat().st_size > PUSH_LOG_MAX:
            # The tail kept rather than a rotation: nothing reads this
            # file but him, and a push.log.1 in a folder he opens by hand
            # is one more thing to explain.
            kept = PUSH_LOG.read_text("utf-8", errors="replace")
            PUSH_LOG.write_text(kept[-PUSH_LOG_MAX // 2:], "utf-8")
        with PUSH_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {text}\n")
    except OSError:
        pass


def _git(*args: str, cwd=None,
         timeout: int = GIT_READ_S) -> tuple[int, str, str]:
    """One git command: (exit code, stdout, stderr).

    It never raises and it never shows a window, and BOTH STREAMS ARE
    LOGGED whatever happened — the whole point of this surface is that a
    push he cannot explain is a push he cannot trust. A missing git, a
    timeout and an OSError all come back as a code and a sentence,
    because every caller here is a button.
    """
    import subprocess

    where = str(cwd or APP_DIR)
    try:
        proc = subprocess.run(["git", *args], cwd=where, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout,
                              creationflags=_CREATE_NO_WINDOW)
        code, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        code, out, err = 127, "", "git is not on PATH"
    except subprocess.TimeoutExpired:
        code, out, err = 124, "", f"git gave no answer in {timeout} s"
    except OSError as e:
        code, out, err = 126, "", str(e)
    _push_log(f"git {' '.join(args)}"
              + ("" if where == str(APP_DIR) else f"  [in {where}]")
              + f" -> {code}"
              + (f"\n    out: {out.strip()}" if out.strip() else "")
              + (f"\n    err: {err.strip()}" if err.strip() else ""))
    return code, out, err


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


# The sentence Push and Undo both open with when the fetch fails. One
# string, because the two buttons fail the same way for the same reason
# and he should not have to learn two wordings for "no network".
_UNREACHABLE = ("GitHub could not be reached. Nothing changed. Try again "
                "in a moment.")


def local_changes() -> dict:
    """What is on this computer and not on GitHub: `origin/main..main`,
    with origin/main AS IT WAS LAST FETCHED.

    LOCAL READS ONLY, no fetch. This is asked for every time the
    Problems tab opens and after every one of its buttons (off the Tk
    thread, but still), and a fetch is somebody else's server on his
    connection — that belongs under a button, and Push and Undo both
    fetch first. The cost of reading a stale origin/main is one number
    being a little old, and the moment either button is pressed the
    fetch under it makes the number current.

    Returns {"commits": [{"sha", "subject", "when"}, ...] newest first,
    "files": [...] what those commits changed, "behind": how many
    commits GitHub has that this computer does not, "told": bool}.
    `told` is False when git could not answer — no repo, no origin/main,
    no git on PATH — and every one of those is an empty block on the
    tab, never an error: a computer with no git still has a Problems
    tab.
    """
    silent = {"commits": [], "files": [], "behind": 0, "told": False}
    code, out, _err = _git("log", "--format=%H%x09%ad%x09%s",
                           "--date=format:%Y-%m-%d %H:%M",
                           f"origin/{TRUNK}..{TRUNK}")
    if code != 0:
        return silent
    commits: list[dict] = []
    for line in out.splitlines():
        sha, _tab, rest = line.partition("\t")
        when, _tab, subject = rest.partition("\t")
        if sha.strip():
            commits.append({"sha": sha.strip()[:7],
                            "subject": subject.strip(),
                            "when": when.strip()})
    # Two dots, not three: `main` is measured against what GitHub has,
    # and what GitHub did meanwhile is the `behind` count, not a diff.
    code, out, _err = _git("diff", "--name-only", f"origin/{TRUNK}..{TRUNK}")
    files = [ln.strip() for ln in out.splitlines() if ln.strip()] \
        if code == 0 else []
    code, out, _err = _git("rev-list", "--count", f"{TRUNK}..origin/{TRUNK}")
    behind = int(out.strip()) if code == 0 and out.strip().isdigit() else 0
    return {"commits": commits, "files": files, "behind": behind,
            "told": True}


def push_main() -> dict:
    """His Push button, in order, with the reason for each step.

    1. `git fetch origin main` first, so that every check below is about
       what is on GitHub at this moment and not as of last Saturday.
       No network is a sentence and nothing else happens.
    2. Is origin/main an ancestor of main? If GitHub has a commit this
       computer lacks, a plain push would be refused as non-fast-forward
       and the only ways past that are a merge or --force. Neither is a
       button's to take: a merge is a session's job (a conflict resolved
       by a button at 4 AM is worse than a push that waits), and --force
       would throw GitHub's commit away. So it refuses, and says whom to
       ask. Nothing changed.
    3. `git push origin main`, no flags. GitHub's answer is quoted back
       to him if it says no.

    Never --force, never -f, never a merge, and the working tree is not
    touched at any step — the folder stands on `main`, and pushing a
    branch by name moves no file. Returns {"pushed": bool, "said": str};
    `said` is the sentence the card shows him.
    """
    code, _out, _err = _git("fetch", "origin", TRUNK, timeout=GIT_NET_S)
    if code != 0:
        return {"pushed": False, "said": _UNREACHABLE}
    if _git("merge-base", "--is-ancestor", f"origin/{TRUNK}", TRUNK)[0] != 0:
        return {"pushed": False,
                "said": "GitHub has changes this computer does not have "
                        "yet. Ask Claude to bring them in first, then "
                        "press Push again. Nothing changed."}
    code, out, err = _git("push", "origin", TRUNK, timeout=GIT_NET_S)
    if code != 0:
        return {"pushed": False,
                "said": f"GitHub did not take the changes "
                        f"({_first_line(err or out) or 'no reason given'}). "
                        f"Nothing changed. Press Push again."}
    return {"pushed": True,
            "said": "Sent. GitHub now has everything on this computer."}


_KEEP_REFUSED = re.compile(r"Entry '([^']+)'")


def undo_main() -> dict:
    """His Undo button: `main` goes back to what GitHub has, and the
    commits that were only here are gone.

    1. `git fetch origin main`, for the same reason Push fetches: the
       thing being gone back TO has to be GitHub's main now, not a
       remembered one.
    2. Nothing ahead is nothing to undo, said in those words rather than
       a reset that changes nothing and a sentence claiming it did.
    3. The folder has to be standing on `main` — it always is, by the
       rule at the top of this section, but `reset` moves WHATEVER HEAD
       is, and a session that left the folder on a branch would have
       that branch thrown back to origin/main by a button that said
       "main". One rev-parse buys that never happening.
    4. `git reset --keep origin/main`. --keep AND NOT --hard, and the
       difference is the whole reason this button is safe to have:
       --hard throws away every uncommitted edit in the folder, and
       config.toml is his, edited by hand and modified most of the time;
       --keep carries uncommitted edits across untouched, leaves
       untracked files (questions.json, problems.json, the logs) alone,
       and REFUSES — changing nothing — when a file with uncommitted
       edits is one the undone commits also changed, because there is
       no way to take the commit out of that file and keep his edit in
       it without a merge. That refusal comes back as a sentence naming
       the file. It is the one outcome that wants a session, so the
       sentence says so.

    The app in memory does not notice any of this: it loaded its code at
    start and runs the newer version until it is restarted, which is
    why the success sentence ends with Restart. Never --hard, never a
    clean, never a checkout of a path. Returns {"undone": bool, "said":
    str}.
    """
    code, _out, _err = _git("fetch", "origin", TRUNK, timeout=GIT_NET_S)
    if code != 0:
        return {"undone": False, "said": _UNREACHABLE}
    code, out, _err = _git("rev-list", "--count", f"origin/{TRUNK}..{TRUNK}")
    if code != 0 or not out.strip().isdigit():
        return {"undone": False,
                "said": f"Undo refused: git could not tell what is on this "
                        f"computer and not on GitHub. Nothing changed. Ask "
                        f"Claude."}
    if int(out.strip()) == 0:
        return {"undone": False,
                "said": "Nothing to undo — everything on this computer is "
                        "already on GitHub."}
    head = _git("rev-parse", "--abbrev-ref", "HEAD")[1].strip()
    if head != TRUNK:
        return {"undone": False,
                "said": f"Undo refused: this folder is standing on "
                        f"{head or 'no branch'}, not {TRUNK}. Nothing "
                        f"changed. Ask Claude."}
    code, out, err = _git("reset", "--keep", f"origin/{TRUNK}")
    if code != 0:
        names = _KEEP_REFUSED.findall(err + out)
        return {"undone": False,
                "said": f"Undo refused: {', '.join(names) or 'a file'} has "
                        f"unsaved edits and one of these changes touched "
                        f"it. Nothing changed. Ask Claude."}
    return {"undone": True,
            "said": "Undone. The changes are gone from this computer "
                    "(GitHub never had them). Restart to run the older "
                    "version again."}


def restart_app(wait_s: float = APP_QUIT_WAIT_S,
                step_s: float = 0.25) -> dict:
    """The app half of Restart: stop it if it is running, wait until it
    has really gone, start it again. Off the Tk thread — the wait is up
    to twenty seconds of polling.

    The two halves are the bar's own Stop and Start, at the level of the
    calls they make: singleton.request_quit sets the named event main.py
    waits on, and launch.start_app spawns pythonw main.py detached. What
    the bar cannot do and this can is the wait BETWEEN them: is_running
    reads the mutex, and the mutex is the last thing the app lets go of,
    so a start issued while it still answers True would be a second copy
    refused at its own door. An app that was not running is simply
    started — there is nothing to wait for.

    Returns {"ok": bool, "said": str}; `said` is empty on success,
    because a restart that worked is about to replace the window that
    would show it.
    """
    if singleton.is_running():
        if not singleton.request_quit():
            return {"ok": False,
                    "said": "The app is running but did not answer the "
                            "request to stop, so nothing was restarted. "
                            "Try Stop in the bar."}
        deadline = time.monotonic() + wait_s
        while singleton.is_running():
            if time.monotonic() >= deadline:
                return {"ok": False,
                        "said": f"The app did not stop in "
                                f"{int(wait_s)} seconds, so nothing was "
                                f"restarted. Try Stop in the bar, wait for "
                                f"the state to say stopped, then Start."}
            time.sleep(step_s)
    if not launch.start_app():
        return {"ok": False,
                "said": "The app could not be started again — see app.log. "
                        "This window was left as it is."}
    return {"ok": True, "said": ""}


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

    wscript = str(Path(os.environ.get("SystemRoot", r"C:\Windows"))
                  / "System32" / "wscript.exe")
    try:
        subprocess.Popen([wscript, str(APP_DIR / "Dashboard.vbs")],
                         cwd=str(APP_DIR), creationflags=launch._DETACHED,
                         close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError as e:
        _push_log(f"relaunch: the window could not be opened again ({e})")
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
    if activity in ("paused", "stopped"):
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
        self.root.title("DeskIT")
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
        # Version screen. Resolved OFF this thread by the warm-up below —
        # asking git synchronously here delayed the whole window opening,
        # and every click on Version paid the same tax again.
        self.branch = "?"
        # Latched, not re-derived, because the pause taken by the key
        # dialog has to be undone from wherever that dialog's life ends —
        # including a route that never runs its own close handler.
        self._paused_for_capture = False
        self._events: queue.Queue = queue.Queue()
        # The queue FIRST, and only then the thread that posts into it.
        # git can answer in well under a millisecond on a warm repo, and
        # when it did, _warm_versions reached _events before this line
        # had run: "AttributeError: 'Dashboard' object has no attribute
        # '_events'" on the warm-up thread, swallowed with the thread,
        # and the branch label silently stayed "?" for the life of the
        # window. Seen eight times in one run of the suite.
        threading.Thread(target=self._warm_branch, daemon=True,
                         name="branch-warmup").start()
        self._busy_until = 0.0     # ignore polls right after a command, so a
                                   # stale status cannot flicker the buttons
                                   # back for one frame
        self.screen = "Home"
        self.parts: dict = {}      # the widgets of whichever screen is up
        self.log: list[history.Event] = []
        self._log_stamp: tuple[int, float] = (0, 0.0)
        self._filter: str | None = None
        self._query = ""
        # The Corrections place: which tab is up, and the reading in
        # hand — see _read_column. The deck is built when the tab opens
        # and popped as he goes; the counts are this session's.
        self._corr_tab = "waiting"
        self._read_deck: list = []
        self._read_current = None
        self._read_drawn = None
        self._read_armed_at = 0.0
        self._read_busy = False
        self._read_writing = False        # a paragraph is with the model
        self._read_write_failed = False   # no backend answered this session
        self._read_counts = {"kept": 0, "skipped": 0, "again": 0}
        self._read_last = None            # (sentence, wav name) just kept
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
        self._rows_after = None
        self._rows_left: list = []
        # How wide a drawn row is on the place that is up. The Said list
        # shares its place with the vocabulary panel, so it is narrower
        # than the sheet; every other list is the full width.
        self._row_w = CW
        self._slide_after = None
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
        # ANSWERING A QUESTION, held on the window and not in the widgets.
        # The Problems list is rebuilt from scratch whenever either store
        # moves — and it moves BECAUSE he answered, or because the routine
        # wrote a question while he was reading one — so the half of an
        # answer he has already given has to survive its own row being
        # destroyed. What he typed and what he picked live here, keyed by
        # question id, and the row is drawn from them.
        self._q_typed: dict = {}
        self._q_choice: dict = {}
        self._q_fields: dict = {}   # id -> the live widgets, per redraw
        self._q_focus = None        # whose field had the caret last
        self._q_after = None        # the echo poll
        self._questions_stamp = None
        # Which report has been asked "delete this?" and has not answered
        # yet — at most one at a time, and it lives out here for the same
        # reason the half-typed answers do: _fill_problems destroys and
        # rebuilds every row a second, and a question that dies with its
        # row is a ✕ that deletes on one press after all.
        self._problem_asking = ""
        self._asking_row = None     # ...and the row it is drawn on now
        # What is on this computer and not on GitHub, as git last
        # answered. None is "nobody has asked yet", which is not the same
        # as "there is nothing".
        self._changes = None
        self._changes_scanning = False
        self._push_said: dict = {}  # what the last press did, by TRUNK
        self._pushing = None        # "push", "undo" or "restart" while
        #                             one of them is in flight
        # Restart asked for this window to come back as a new process.
        # Read by run() after the window is gone — see _restart_all.
        self._relaunch = False
        # Which of the Home place's two views is up: the calm home, or
        # the whole backlog behind it.
        self._waiting_view = "home"
        # Which binding the key dialog is listening for, or None. The
        # panel beside the keyboard reads it, so the board says "press
        # the key you want" at the same moment the dialog does.
        self._capturing = None
        self._cap_selected = None
        # Is a nightly test run going right now? Re-asked once a poll and
        # answered by a file on disk, because the run is a process this
        # window did not start and cannot see any other way — see
        # nightly.py's contract. False until the first poll says so, so
        # the bar never opens holding a button for a run that ended
        # while the window was closed.
        self._tests_running = False

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
        self._show("Home")

    def _topbar(self) -> None:
        """The mark, the six places, the state, and whichever buttons the
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

        self.nav = widgets.Tabs(bar, [name for _key, name in NAV], bg=ui.BG,
                                selected="Home", command=self._show, gap=18)
        # Six words now, so the bar is measured rather than guessed: the
        # places start after the mark and have to end before the state
        # chip. 24 + 26 mark + 14 air = 64; six words at gap 18 come to
        # 471 px, so they end at 535. The chip is furthest left in the
        # state that holds the most buttons, and its left edge there is
        # 576 — the 41 px of clearance a test holds us to.
        self.nav.place(x=PAD + 40, y=17)

        # The state chip and the buttons are placed from the RIGHT edge, so
        # a longer word ("Transcribing") grows leftwards into empty bar
        # rather than pushing a button off the window.
        # STOP IS IN THE BAR because he asked for it there ("I don't have
        # a button to shut down the model, I only have a button to pause
        # it"), and it does the same thing Settings › The app's Stop does,
        # in one press.
        self.parts["stop_bar"] = ui.Button(
            bar, "Stop", self._stop, w=BAR_STOP_W, h=32, bg=ui.BG,
            quiet=True)
        self.parts["run"] = ui.Button(bar, "Pause", self._toggle_pause,
                                      w=BAR_RUN_W, h=32, bg=ui.BG,
                                      quiet=True)
        # STOP TESTS is in the bar for exactly as long as there is a
        # nightly test run to stop, and not one poll longer — the rule
        # the Push button and Stop already follow. It answers a question
        # neither of its neighbours does: at three in the morning the
        # suite takes the real mouse for about fifteen seconds, and if
        # he is awake and using the machine he wants it to let go now.
        self.parts["tests_stop"] = ui.Button(
            bar, "Stop tests", self._stop_tests, w=BAR_TESTS_W, h=32,
            bg=ui.BG, quiet=True)
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

    def _paint_nav(self) -> None:
        self.nav.select(self.screen)

    def _show(self, name: str) -> None:
        """Swap screens. Everything the old one registered goes with it, so
        _refresh has to ask for a widget rather than assume one."""
        if (self.screen == "Corrections" and name != "Corrections"
                and self._corr_tab == "read"):
            self._read_leave()
        self.screen = name
        self._paint_nav()
        self._stop_rows()
        if self._slide_after is not None:
            try:
                self.root.after_cancel(self._slide_after)
            except Exception:
                pass
            self._slide_after = None
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
         "Problems": self._screen_problems,
         "Said": self._screen_said,
         "Keys": self._screen_keys,
         "Settings": self._screen_settings}[name]()
        self._refresh(self.status or None)
        self._slide_in()

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
        # is wrong, so the button is here as well as on the Problems
        # place, and it says its key — all five reports in ten days were
        # filed from the key.
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

        STOP TESTS ANSWERS THE SAME QUESTION ABOUT A DIFFERENT THING —
        is there a nightly test run to stop — and it is the one button
        here that does not care whether the app is up: the nightly run
        is started by a scheduled task and not by DeskIT, on purpose, so
        that the night DeskIT crashed is still a night the tests run.

        THE UPTIME STEPS ASIDE FOR IT, and that is arithmetic rather
        than taste. Measured 2026-09-08 on this machine, in the widest
        state the bar has ("Transcribing", which is the longest word the
        chip ever holds): the six places end at 523 px and the chip's
        left edge is 559, so there are 36 px of slack — and a fourth
        button costs 108 (96 for the pill, 12 for the gap). The uptime
        is worth 81 of those, which is enough: with it forgotten the
        chip starts at 532 and the places still clear it by 9 px, and by
        34 to 330 px in every other state. It is also the right thing to
        spend, not merely the only thing: how long the app has been up
        is a fact, and "Stop tests" is a control with something to do,
        which is the rule that decides whether a button is in this bar
        at all. It comes back the moment the run ends — FORGOTTEN and
        not blanked, because an empty label still costs its padding
        (widgets.StateChip.show_meta says how much).
        """
        chip = self.parts.get("chip")
        run = self.parts.get("run")
        stop = self.parts.get("stop_bar")
        screens = self.parts.get("bar_screens")
        tests = self.parts.get("tests_stop")
        if not all(w is not None and w.winfo_exists()
                   for w in (chip, run, stop, screens, tests)):
            return
        # ONE BUTTON, THREE WORDS. Start, Resume and Pause are never
        # available at the same moment, so three buttons would be two
        # lies — and it is the same key in the same pixels either way.
        run.configure_text("Start" if not self.status else
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
        if self.status:
            screens.place(x=x, y=12, anchor="ne")
            x -= self._screens_w + BAR_KEEP
            stop.place(x=x, y=12, anchor="ne")
            x -= BAR_STOP_W + BAR_GAP
        else:
            screens.place_forget()
            stop.place_forget()
        if self._tests_running:
            tests.place(x=x, y=12, anchor="ne")
            x -= BAR_TESTS_W + BAR_GAP
        else:
            tests.place_forget()
            tests.configure_text("Stop tests")
        chip.show_meta(not self._tests_running)
        chip.place(x=x, y=TOP // 2, anchor="e")

    def _screen_corrections(self) -> None:
        """What the second reading proposes, and what it has learned.

        His words: "all the corrections and stuff, I would like them to be
        in tabs… and something with the vocabulary and all the corrections
        it does automatically". They are one place because they are one
        story: the list on the left is what the app is asking about a
        dictation it has re-read, and the panel on the right is what
        saying Yes has taught it.

        The rows are the pile's rows, with the pile's two answers, so a
        correction reads the same here as it does on the home.
        """
        self._title("Corrections", "the second reading, what it learned, "
                                   "and what you read to it")
        p = self.parts
        self._row_w = SAID_W
        chips = tk.Frame(self.sheet, bg=ui.BG)
        chips.place(x=PAD, y=CORR_CHIPS_Y)
        p["corr_chips"] = {}
        for key, name in corr_tabs():
            chip = ui.Chip(chips, name, lambda k=key: self._corr_tab_to(k),
                           active=(key == self._corr_tab), bg=ui.BG)
            chip.pack(side="left", padx=(0, 6))
            p["corr_chips"][key] = chip
        if self._corr_tab == "read":
            self._read_column()
            self._voice_panel()
            return
        p["corr_head"] = tk.Label(self.sheet, text="", bg=ui.BG, fg=ui.DIM,
                                  font=(ui.UI, 10))
        p["corr_head"].place(x=PAD, y=CORR_HEAD_Y)
        page = ui.Scroller(self.sheet, SAID_W + 10, H - TOP - CORR_PAGE_Y - 24,
                           bg=ui.BG)
        page.place(x=PAD, y=CORR_PAGE_Y)
        p["page"] = page
        p["corr_list"] = _Column(page.inner, page)
        p["corr_empty"] = tk.Label(self.sheet, text="", bg=ui.BG,
                                   fg=ui.FAINT, font=(ui.UI, 10),
                                   wraplength=SAID_W - 40, justify="left")
        self._vocab_panel()
        self._corr_stamp = None
        self._fill_corrections()

    def _corr_tab_to(self, key: str) -> None:
        if key == self._corr_tab:
            return
        if self._corr_tab == "read":
            self._read_leave()
        self._corr_tab = key
        self._show("Corrections")

    def _poll_corrections(self) -> None:
        """Once a second from _refresh, and only a stat() unless the file
        moved — a verdict given at a card is the usual reason it did."""
        if self._corr_tab == "read":
            self._poll_read()
            return
        if "corr_list" not in self.parts:
            return
        if self._review_stat() != getattr(self, "_corr_stamp", None):
            self._fill_corrections()

    def _fill_corrections(self) -> None:
        if "corr_list" not in self.parts:
            return
        self._corr_stamp = self._review_stat()
        p = self.parts
        # ONE GOLD BUTTON PER SURFACE, the same rule the pile keeps: four
        # lit Yes buttons down a list are four primary actions, which is
        # none. Only the newest is the lamp; every later Yes answers the
        # same way, quietly.
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
        p["corr_head"].config(
            text="Nothing is waiting on you here." if not items else
            f"{len(items)} proposal{'' if len(items) == 1 else 's'} from "
            f"the second reading")
        column = p["corr_list"]
        column.clear()
        p["corr_empty"].place_forget()
        if not items:
            p["corr_empty"].config(
                text="When a dictation is re-read and a word looks wrong, "
                     "the proposal waits here — and on a card, for twenty "
                     "seconds, wherever you are.")
            p["corr_empty"].place(x=PAD, y=CORR_PAGE_Y + 40)
        for index, spec in enumerate(items):
            if index:
                widgets.rule(column.inner, SAID_W - 28, bg=ui.BG,
                             colour=ui.LINE).pack(fill="x", pady=6)
            card = ui.Card(column.inner, SAID_W, PILE_ROW_H + 20,
                           fill=ui.CARD, bg=ui.BG, pad=10)
            card.pack(anchor="w", pady=(0, 8))
            row = widgets.PileRow(
                card.body, SAID_W - 20, bg=ui.CARD,
                mark=spec.get("mark", ""),
                mark_colour=spec.get("mark_colour"),
                eyebrow=spec.get("eyebrow", ""),
                eyebrow_right=spec.get("eyebrow_right", True),
                text=spec.get("text", ""), runs=spec.get("runs"),
                note=spec.get("note", ""), buttons=spec.get("buttons", ()),
                height=PILE_ROW_H)
            row.pack(fill="x")
            column.bind_wheel(card)
            column.bind_wheel(row)
            column.bind_wheel(row.canvas)

    # ---------------------------------------------------------- read aloud

    def _read_column(self) -> None:
        """The Read aloud tab's left column: the sentence card, and under
        it what he has kept today. The card is drawn by _poll_read off the
        app's answer, not here — see reading.py for who owns what.

        THE DECK IS BUILT WHEN THE TAB OPENS and popped as he reads: a
        kept or skipped sentence is written to corpus\\read by the app,
        and a deck built later leaves it out on its own, so switching
        tabs and back never shows him a sentence twice.
        """
        p = self.parts
        self._read_drawn = None
        self._read_armed_at = 0.0
        self._read_busy = False
        self._read_writing = False
        self._read_current = None
        self._read_last = None
        try:
            READ_TEXTS.mkdir(parents=True, exist_ok=True)  # for the button
        except OSError:
            pass
        tk.Label(self.sheet,
                 text="Any Hebrew text dropped into corpus\\read\\texts is "
                      "read here, in order; a model writes more when it "
                      "runs dry.\nNothing is checked but that something came "
                      "back — you read the card, and the card is the label.\n"
                      "Kept readings go to corpus\\read — the audio never "
                      "leaves this machine.",
                 bg=ui.BG, fg=ui.FAINT, font=(ui.UI, 8),
                 justify="left").place(x=PAD, y=610)
        wide = widgets.button_width("Open the texts", icon=True)
        ui.Button(self.sheet, "Open the texts",
                  lambda: launch.open_path(READ_TEXTS), w=wide, h=30,
                  quiet=True, bg=ui.BG, icon=ui.ICON["folder"]).place(
            x=PAD + SAID_W, y=616, anchor="ne")
        p["read_on"] = True
        # THE LEFT ARROW KEEPS. His flow (2026-09-13, late): let go of the
        # key and the recording stands; ← keeps it and brings the next
        # sentence; holding the key again reads the same sentence over.
        # Left is the latch key, swallowed by the hook only while a
        # recording is running — after the release it reaches this
        # window like any key. Bound on the root, like the Keys place's
        # press, and taken off again when he leaves the tab.
        self.root.bind("<Left>", self._read_left)
        self._read_deck = self._read_build_deck()
        self._read_advance()

    @staticmethod
    def _read_build_deck() -> list:
        try:
            return reading_mod.deck(READ_TEXTS, paths.VOCAB_FILE,
                                    READ_DIR)
        except Exception:                 # noqa: BLE001 — a bad file
            return []

    def _read_leave(self) -> None:
        """Off the tab: the app is told there is nothing armed. Best
        effort and fire-and-forget — a sentence left armed is harmless
        anyway, since `takes` wants this window in front of it."""
        self._read_current = None
        self._read_drawn = None
        try:
            self.root.unbind("<Left>")
        except tk.TclError:
            pass
        self._ask("read", do="disarm")

    def _read_phase(self) -> tuple[str, dict | None]:
        """What the card should show, from the app's last answer.

        off — no app to listen; writing — the next paragraph is with
        the model; done — nothing left to read; arming — the app has not
        got this sentence yet; waiting — it has, and the key is up;
        listening / checking — the key is down / the decode is running;
        heard — the transcript is back, and the reading is kept on the
        next poll; nothing — it is back and empty: a dead microphone, a
        key let go too soon, and the one case he is asked to read again.
        """
        cur = self._read_current
        if not self.running:
            return "off", None
        if self._read_writing:
            return "writing", None
        if cur is None:
            return "done", None
        read = self.status.get("read") or {}
        heard = read.get("heard")
        if heard and heard.get("id") == cur.key:
            m = heard.get("match") or {}
            return ("heard" if m.get("same") or not m.get("words")
                    else "nothing"), heard
        armed = read.get("armed") or {}
        if armed.get("id") != cur.key:
            return "arming", None
        activity = self.status.get("activity")
        if activity in ("recording", "locked"):
            return "listening", None
        if activity == "busy":
            return "checking", None
        return "waiting", None

    def _read_left(self, _event=None) -> str | None:
        """← : the recording that stands is kept and the next sentence
        comes up. Nothing standing, nothing happens."""
        if not self.parts.get("read_on") or self.closing:
            return None
        if self._read_phase()[0] == "heard":
            self._read_keep()
            return "break"
        return None

    def _poll_read(self) -> None:
        """Once a poll: arm the sentence the app has not got, and redraw
        the card only when what it would say has changed. A reading that
        is back STANDS until he keeps it (←) or reads the sentence over
        — the card is the label either way, and which take is the good
        one is his to say (reading.py)."""
        if not self.parts.get("read_on") or self.closing:
            return
        phase, heard = self._read_phase()
        cur = self._read_current
        since_arm = time.monotonic() - self._read_armed_at
        if phase == "arming" and cur is not None \
                and since_arm > READ_ARM_EVERY_S:
            self._read_arm()
        if phase == "arming" and since_arm < READ_ARM_GRACE_S:
            # The arm is in flight, or answered and a poll that left
            # before it is landing now. The pipe answers in milliseconds;
            # drawing "one moment" for a poll's worth of that is a
            # flicker between every two sentences.
            phase = "waiting"
        key = (phase, cur.key if cur else None,
               heard.get("when") if heard else None)
        if key != self._read_drawn:
            self._read_drawn = key
            self._draw_read_card(phase, heard)

    def _read_hwnd(self) -> int:
        """This window's top-level HWND — the one Windows puts in the
        foreground, which is what the app compares against."""
        try:
            return int(ctypes.windll.user32.GetAncestor(
                self.root.winfo_id(), reading_mod.GA_ROOT))
        except Exception:                 # noqa: BLE001
            return 0

    def _read_arm(self) -> None:
        cur = self._read_current
        if cur is None:
            return
        self._read_armed_at = time.monotonic()
        self._ask("read", then=self._read_answered, do="arm", id=cur.key,
                  text=cur.text, hwnd=self._read_hwnd())

    def _read_answered(self, reply: dict | None) -> None:
        """Every read command answers with the app's new state; take it
        now rather than a poll later, so the card moves at once."""
        if reply and isinstance(reply.get("read"), dict):
            self.status["read"] = reply["read"]
        self._poll_read()

    def _read_keep(self) -> None:
        cur = self._read_current
        if cur is None or self._read_busy:
            return
        self._read_busy = True
        self._ask("read", then=lambda r: self._read_kept(r, cur), do="keep",
                  id=cur.key)

    def _read_kept(self, reply: dict | None, sentence) -> None:
        self._read_busy = False
        if not reply or not reply.get("ok"):
            self._announce(reply, "that did not keep")
            self._read_answered(reply)
            return
        self._read_counts["kept"] += 1
        self._read_last = (sentence, str(reply.get("kept") or ""))
        self._read_advance(reply)
        self._voice_panel()

    def _read_redo(self) -> None:
        """The reading he just made, taken back — he knows he fumbled it
        — and its sentence up again, the one that replaced it waiting
        behind it."""
        last = self._read_last
        if last is None or self._read_busy:
            return
        self._read_busy = True
        self._read_last = None
        self._ask("read", then=lambda r: self._read_redone(r, last),
                  do="forget", name=last[1])

    def _read_redone(self, reply: dict | None, last) -> None:
        self._read_busy = False
        if not reply or not reply.get("ok"):
            self._announce(reply, "that could not be taken back")
            return
        sentence, _name = last
        self._read_counts["kept"] = max(0, self._read_counts["kept"] - 1)
        self._read_counts["again"] += 1
        if self._read_current is not None:
            self._read_deck.insert(0, self._read_current)
        self._read_current = sentence
        self._read_armed_at = 0.0
        self._read_drawn = None
        self._read_answered(reply)
        self._voice_panel()

    def _read_skip(self) -> None:
        cur = self._read_current
        if cur is None or self._read_busy:
            return
        self._read_busy = True
        self._read_counts["skipped"] += 1
        self._ask("read", then=lambda r: self._read_advance(r), do="drop",
                  id=cur.key, skip=True)

    def _read_advance(self, reply: dict | None = None) -> None:
        """The next sentence of the deck; with the deck empty, a
        paragraph is asked of the model first and the deck rebuilt from
        the file it lands in. Arming is the next poll's job, and it is
        asked for now rather than in READ_ARM_EVERY_S."""
        self._read_busy = False
        deck = self._read_deck
        if not deck and not self._read_write_failed \
                and not self._read_writing:
            self._read_current = None
            # THE TOKEN names this paragraph: one landing after the tab
            # was left and opened again (which asks for one of its own)
            # is kept as a file and not allowed to swap the sentence he
            # is reading by then.
            self._read_writing = token = object()
            threading.Thread(target=self._read_write, args=(token,),
                             daemon=True, name="read-write").start()
            self._read_answered(reply)
            return
        self._read_current = deck.pop(0) if deck else None
        self._read_armed_at = 0.0
        self._read_answered(reply)

    def _read_write(self, token) -> None:
        """Off the Tk thread: one model call for one paragraph, saved as
        a file of the folder like anything he dropped there. The result
        lands through _events like a pipe reply does."""
        path = None
        try:
            cfg = config_mod.load_layered()
            found = reading_mod.Writer(cfg).write(
                seed=reading_mod.written_count(READ_TEXTS),
                names=reading_mod.names_of(paths.VOCAB_FILE))
            if found:
                path = reading_mod.save_written(READ_TEXTS, found)
        except Exception:                 # noqa: BLE001
            path = None
        self._events.put(lambda: self._read_written(path, token))

    def _read_written(self, path, token) -> None:
        if path is None:
            self._read_write_failed = True
            self._note("no model could write the next paragraph — drop a "
                       "text into corpus\\read\\texts to keep reading")
        if self._read_writing is not token:
            return                        # a paragraph the tab moved past
        self._read_writing = False
        if not self.parts.get("read_on") or self.closing:
            return
        self._read_deck = self._read_build_deck()
        self._read_advance()

    def _draw_read_card(self, phase: str, heard: dict | None) -> None:
        """The sentence card for one phase, and the kept-today list under
        it. Rebuilt whole: the card is as tall as what is in it, and the
        list starts where the card ends."""
        p = self.parts
        for key in ("read_card", "read_kept_head", "read_kept"):
            old = p.pop(key, None)
            if old is not None:
                try:
                    old.destroy()
                except tk.TclError:
                    pass
        cur = self._read_current
        inner = SAID_W - 2 * READ_PAD
        keys = self.status.get("keys") or self._read_keys()
        hold = pretty_key(keys.get("hotkey", ""))

        if phase in ("off", "done", "writing"):
            card = ui.Card(self.sheet, SAID_W, 200, radius=14, bg=ui.BG,
                           pad=READ_PAD)
            card.place(x=PAD, y=READ_CARD_Y)
            p["read_card"] = card
            if phase == "off":
                head = "Start the app first — it does the listening."
                sub = ("The models that hear you live in the app, not in "
                       "this window.")
            elif phase == "writing":
                head = "Writing the next paragraph…"
                sub = ("A model writes a few sentences round your own "
                       "names — text only, the audio goes nowhere.")
            else:
                head = "Nothing left to read."
                sub = ("Drop any Hebrew text (.txt or .md) into "
                       "corpus\\read\\texts and it is here, sentence by "
                       "sentence.")
            tk.Label(card.body, text=head, bg=ui.CARD, fg=ui.FG,
                     font=(ui.UI, 12)).place(x=inner // 2, y=70,
                                             anchor="center")
            tk.Label(card.body, text=sub, bg=ui.CARD, fg=ui.FAINT,
                     font=(ui.UI, 9)).place(x=inner // 2, y=98,
                                            anchor="center")
            self._draw_read_kept(READ_CARD_Y + 200 + 20)
            return

        # MEASURED FIRST: the card is exactly as tall as what is in it.
        photo, text_h, _l = ui.draw_text(cur.text, pt=20, width=inner,
                                         max_lines=3, colour=ui.FG,
                                         bg=ui.CARD)
        y_sentence = 32
        rule_y = y_sentence + text_h + 22
        ly = rule_y + 20
        block_h = 48 if phase in ("waiting", "nothing", "heard") else 30
        by = ly + block_h + 18
        card_h = by + 36 + 2 * READ_PAD + 4

        card = ui.Card(self.sheet, SAID_W, card_h, radius=14, bg=ui.BG,
                       pad=READ_PAD)
        card.place(x=PAD, y=READ_CARD_Y)
        p["read_card"] = card
        body = card.body

        left = len(self._read_deck)
        source = ("WRITTEN FOR YOU"
                  if cur.said.startswith(reading_mod.WRITTEN)
                  else f"FROM {cur.said.upper()}")
        eyebrow = "  ·  ".join(
            (source, f"SENTENCE {cur.index} OF {cur.count}",
             f"{left} MORE TO READ" if left else "THE LAST ONE"))
        tk.Label(body, text=eyebrow, bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, ui.PT_CAPS)).place(x=0, y=0)
        # The taught words it carries, as lit chips — the reason it is
        # near the top of the deck.
        if cur.terms:
            pills = tk.Canvas(body, width=inner // 2, height=ui.PILL_H,
                              bg=ui.CARD, highlightthickness=0, bd=0)
            pills.place(x=inner, y=-8, anchor="ne")
            x = inner // 2
            for term in cur.terms[:3]:
                x -= ui.pill(pills, x, 0, term, ui.CARD,
                             colour=ui.ACCENT_TEXT, fill=ui.ACCENT_SOFT,
                             border=ui.CHIP_ON_EDGE) + 6
                if x < 0:
                    break

        holder = tk.Label(body, image=photo, bg=ui.CARD, bd=0)
        holder.image = photo
        holder.place(x=inner, y=y_sentence, anchor="ne")
        widgets.rule(body, inner, bg=ui.CARD, colour=ui.LINE, y=rule_y)

        colour = {"listening": ui.RECORDING, "checking": ui.AMBER,
                  "heard": ui.GREEN, "nothing": ui.AMBER}.get(phase, ui.FAINT)
        lamp = ui.lamp(15, colour, ui.CARD,
                       0.0 if phase in ("waiting", "arming") else 0.45)
        lamp_label = tk.Label(body, bg=ui.CARD, image=lamp)
        lamp_label.image = lamp
        lamp_label.place(x=0, y=ly + 2)
        sub = ""
        if phase == "listening":
            line = "Listening…  let go when you finish."
        elif phase == "checking":
            line = "One moment…"
        elif phase == "heard":
            line = (f"Recorded, {float(heard.get('seconds') or 0):.1f} s.  "
                    "Press ← to keep it and move on.")
            sub = (f"Or hold {hold} and read it again — the new take "
                   "replaces this one.")
        elif phase == "nothing":
            line = "Nothing came back."
            sub = (f"Is the microphone on? Hold {hold} and read it again — "
                   "the key has to stay down until you finish.")
        elif phase == "arming":
            line = "One moment — handing the sentence to the app."
        else:
            line = (f"Hold {hold} and read it aloud.  Let go when you finish."
                    if hold != "off" else "No dictation key is set — see Keys.")
            sub = ("Let go, and the recording stands: ← keeps it and "
                   "brings the next one; the key again reads it over.")
        tk.Label(body, text=line, bg=ui.CARD, fg=ui.FG,
                 font=(ui.UI, 11)).place(x=28, y=ly)
        if sub:
            tk.Label(body, text=sub, bg=ui.CARD, fg=ui.FAINT,
                     font=(ui.UI, 9), wraplength=inner - 28,
                     justify="left").place(x=28, y=ly + 24)

        if phase == "heard":
            widgets.gold_button(body, "Keep  ←", self._read_keep, w=110,
                                h=36, bg=ui.CARD).place(x=inner, y=by,
                                                        anchor="ne")
            ui.Button(body, "Skip", self._read_skip, w=84, h=36, quiet=True,
                      bg=ui.CARD).place(x=inner - 122, y=by, anchor="ne")
        else:
            ui.Button(body, "Skip this one", self._read_skip, w=136, h=36,
                      quiet=True, bg=ui.CARD).place(x=inner, y=by,
                                                     anchor="ne")
        if self._read_last is not None:
            # The one he just read, if he knows he fumbled it: taken
            # back, and up again. Only until the next one is kept — the
            # one before that is in the folder to stay.
            wide = widgets.button_width("Redo the last one")
            ui.Button(body, "Redo the last one", self._read_redo, w=wide,
                      h=36, quiet=True, bg=ui.CARD).place(x=0, y=by)
        else:
            tk.Label(body, text="Skip a sentence you would never say.",
                     bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 9),
                     justify="left", anchor="w").place(x=0, y=by + 8)
        self._draw_read_kept(READ_CARD_Y + card_h + 20)

    def _draw_read_kept(self, y: int) -> None:
        """What he has kept today, newest first, as many as fit above the
        footer."""
        p = self.parts
        try:
            kept = reading_mod.tally(READ_DIR, CORPUS_DIR)["today"]
        except Exception:                 # noqa: BLE001
            kept = []
        room = 600 - y - 22
        if room < 28:
            return
        p["read_kept_head"] = tk.Label(self.sheet, text="K E P T   T O D A Y",
                                       bg=ui.BG, fg=ui.FAINT,
                                       font=(ui.MEDIUM, 8))
        p["read_kept_head"].place(x=PAD, y=y)
        rows = tk.Canvas(self.sheet, width=SAID_W, height=room, bg=ui.BG,
                         highlightthickness=0, bd=0)
        rows.place(x=PAD, y=y + 22)
        p["read_kept"] = rows
        if not kept:
            rows.create_text(0, 9, anchor="w", font=(ui.UI, 9), fill=ui.FAINT,
                             text="Nothing yet today.")
            return
        ry = 0
        for when, text in kept:
            if ry + 28 > room:
                break
            rows.create_text(0, ry + 9, text=when, anchor="w",
                             font=(ui.UI, 9), fill=ui.FAINT)
            rows.create_text(48, ry + 9, text=ui.ICON["check"], anchor="w",
                             font=(ui.ICONS, 9), fill=ui.GREEN)
            img, _h, _l = ui.draw_text(text, pt=10, width=SAID_W - 76,
                                       max_lines=1, colour=ui.DIM, bg=ui.BG)
            rows.create_image(SAID_W, ry + 9, anchor="e", image=img)
            ry += 28

    def _voice_panel(self) -> None:
        """The Read aloud tab's right panel, where the vocabulary sits on
        the other tab: how much of his voice is on file against what a
        fine-tune wants, today's reading against the day's bar, and the
        key to hold."""
        p = self.parts
        old = p.pop("voice_card", None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        try:
            scfg = config_mod.load_layered().study
            goal_s = max(1.0, float(scfg.read_goal_hours)) * 3600
            day_n = max(1, int(scfg.read_sentences))
        except Exception:                 # noqa: BLE001 — unreadable config
            goal_s, day_n = 3 * 3600, 20
        try:
            t = reading_mod.tally(READ_DIR, CORPUS_DIR)
        except Exception:                 # noqa: BLE001
            t = {"total_s": 0.0, "today_s": 0.0}
        width = CW - SAID_W - 20
        card = ui.Card(self.sheet, width, 508, fill=ui.CARD, bg=ui.BG, pad=16)
        card.place(x=PAD + SAID_W + 20, y=64)
        p["voice_card"] = card
        body, inner = card.body, width - 32

        def bar(y: int, done: float, whole: float) -> None:
            track = tk.Canvas(body, width=inner, height=4, bg=ui.CARD,
                              highlightthickness=0, bd=0)
            track.place(x=0, y=y)
            track.create_image(0, 0, anchor="nw",
                               image=ui.rounded(inner, 4, 2, ui.LINE,
                                                ui.CARD, None))
            lit = int(inner * min(1.0, done / whole)) if whole else 0
            if lit >= 4:
                track.create_image(0, 0, anchor="nw",
                                   image=ui.rounded(lit, 4, 2, ui.ACCENT,
                                                    ui.CARD, None))

        tk.Label(body, text="Y O U R   V O I C E", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)
        tk.Label(body, text=_minutes(t["total_s"]), bg=ui.CARD, fg=ui.FG,
                 font=(ui.DISPLAY, 24, "bold")).place(x=0, y=20)
        tk.Label(body, text="on file, in your own words — a fine-tune wants "
                            f"{_hours(goal_s)}",
                 bg=ui.CARD, fg=ui.DIM, font=(ui.UI, 9), wraplength=inner,
                 justify="left").place(x=0, y=60)
        bar(104, t["total_s"], goal_s)

        widgets.rule(body, inner, bg=ui.CARD, colour=ui.LINE, x=0, y=136)
        # HOW MANY OF HOW MANY, and how many to go — his words
        # (2026-09-14), and in sentences, which is what he counts in: a
        # reading is seconds of audio and a quarter-minute of his time.
        done = len(t.get("today") or [])
        left = max(0, day_n - done)
        tk.Label(body, text="T O D A Y", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=150)
        tk.Label(body, text=f"{done} of {day_n}", bg=ui.CARD, fg=ui.FG,
                 font=(ui.DISPLAY, 24, "bold")).place(x=0, y=170)
        tk.Label(body, text=(f"sentences today — {left} to go" if left
                             else "sentences today — done for today"),
                 bg=ui.CARD, fg=ui.DIM, font=(ui.UI, 9), wraplength=inner,
                 justify="left").place(x=0, y=210)
        bar(236, done, day_n)
        c = self._read_counts
        counts = "  ·  ".join(
            part for part in (f"{_clock(t['today_s'])} of voice",
                              f"{c['skipped']} skipped" if c["skipped"] else "",
                              f"{c['again']} read again" if c["again"] else "")
            if part)
        tk.Label(body, text=counts, bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 9)).place(x=0, y=250)

        widgets.rule(body, inner, bg=ui.CARD, colour=ui.LINE, x=0, y=286)
        keys = self.status.get("keys") or self._read_keys()
        hold = pretty_key(keys.get("hotkey", ""))
        row = tk.Frame(body, bg=ui.CARD)
        row.place(x=0, y=302)
        ui.KeyCap(row, hold, bg=ui.CARD,
                  w=max(56, 26 + ui.text_width(hold, ui.UI, 10)),
                  h=28).pack(side="left")
        tk.Label(row, text="hold it and read", bg=ui.CARD, fg=ui.DIM,
                 font=(ui.UI, 9)).pack(side="left", padx=(10, 0))
        tk.Label(body, bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8),
                 wraplength=inner, justify="left",
                 text="Only while this window is in front. Anywhere else "
                      "the key dictates as it always has.").place(x=0, y=340)
        tk.Label(body, bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8),
                 wraplength=inner, justify="left",
                 text="Every reading is a (voice, text) pair the local model "
                      "can be tuned on. Nothing is sent anywhere."
                 ).place(x=0, y=436)

    def _poll_waiting(self) -> None:
        """Once a second from _refresh. Four stores, one stamp each, and
        a redraw only when one of them moved — a notification arriving, a
        verdict given at a card, a report filed, a question asked by the
        routine. Reading four stat()s costs nothing; rebuilding six rows
        every second would cost the caret in the answer box."""
        if "pile_list" not in self.parts:
            return
        stamp = (self._notify_stat(), self._review_stat(),
                 self._problems_stat(), self._questions_stat())
        if stamp != getattr(self, "_pile_stamp", None):
            self._fill_waiting()
        self._paint_rest()

    # -- the pile

    def _waiting_items(self) -> list[dict]:
        """Everything that wants an answer, newest first, as row specs.

        Each source is guarded on its own: a store that is absent, off or
        unreadable contributes nothing and the other three still draw.
        `[questions]` in particular is missing from config.toml on this
        branch, so _questions_store returns None and the block simply is
        not there — which is what "show the section only when it exists"
        means.
        """
        items: list[dict] = []
        items += self._waiting_notify()
        items += self._waiting_review()
        items += self._waiting_problems()
        items += self._waiting_questions()
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
        more = len(changes) - 1
        # The reason first, then the count: the reason is Hebrew and the
        # count is English, and a line takes its direction from its first
        # strong letter — so this way a Hebrew row's note reads the same
        # way its words do.
        note = "   ·   ".join(b for b in (
            " ".join(str(first.get("why") or "").split()),
            f"and {_count_word(more).lower()} more change"
            f"{'' if more == 1 else 's'}" if more else "") if b)
        count = (f"{_count_word(len(changes)).lower()} word"
                 f"{'' if len(changes) == 1 else 's'}")

        if not meant or str(first.get("kind")) == "drop":
            # An ending nobody else heard. Nothing BECAME anything, so
            # there is no pair to draw: the words that would go are the
            # chip, in the danger colour, and the sentence they came out
            # of is what places them.
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

        pair = widgets.Pair(heard, meant)
        try:
            chip, _tall = ui.pair_size(heard, meant, ui.PT_LABEL)
        except Exception:                 # noqa: BLE001 — no window yet
            chip = self._measure(heard) + self._measure(meant) + 50
        where = self._sentence_around(proposed, meant)
        return {
            "eyebrow": f"Second reading   ·   {count} changed",
            "runs": [(pair, None, None),
                     (summary.one_line(where, max(80, room - chip - 16),
                                       self._measure).text, ui.DIM, None)],
            "text": where, "note": note}

    def _waiting_problems(self) -> list[dict]:
        module, store = self._problems(), self._problems_store()
        if module is None or store is None:
            return []
        try:
            open_ = store.items(module.OPEN)
        except Exception:                 # noqa: BLE001
            return []
        rows = []
        for item in open_:
            ident = str(item.get("id", ""))
            # problems.Store writes "at", in ISO. This asked for "when",
            # in the review store's format, so every report stamped 0 and
            # sorted to the bottom of the pile with no date on it.
            at = (self._stamp_of(item.get("at", ""), "%Y-%m-%dT%H:%M:%S")
                  or self._stamp_of(item.get("when", ""),
                                    "%Y-%m-%d %H:%M:%S"))
            day = (time.strftime("%d %b", time.localtime(at)).lstrip("0")
                   if at else "")
            buttons = [("Fixed", "quiet",
                        lambda i=ident: self._problem_decide(i, "fixed")),
                       ("Close", "quiet",
                        lambda i=ident: self._problem_decide(i, "closed"))]
            # ONE LINE THAT SAYS WHAT THE REPORT IS ABOUT. He types one
            # long line into the box and the row drew its first ~90
            # characters, cut mid-word: "I also don't understand the
            # report... maybe display the sentence from point to point"
            # (2026-09-07). The first SENTENCE, whole and with no
            # ellipsis on it when it is whole; the full text is untouched
            # in the store and the whole list still shows all of it.
            said = summary.one_line(
                item.get("what") or item.get("text") or item.get("note")
                or "", self._row_room(buttons), self._measure)
            rows.append({
                "at": at,
                "kind": "problem", "mark": "alert", "mark_colour": ui.RED,
                "eyebrow": f"You reported this on {day}" if day
                           else "You reported this",
                "text": said.text,
                "note": "   ·   ".join(b for b in (
                    " ".join(str(item.get("where") or "").split()),
                    "" if said.whole else "the whole list has all of it")
                    if b),
                "buttons": buttons,
            })
        return rows

    def _waiting_questions(self) -> list[dict]:
        """The routine's questions — only when the store is there.

        `[questions]` is not in config.toml on this branch at all, so
        _questions_store reads it as off and this returns [] and the
        section is simply not on the screen. When it IS there, the row
        says what was asked and Answer opens the whole list, because
        answering needs the options as bands to press and a box to
        dictate into — a surface this row is far too small to be.
        """
        if self._questions() is None:
            return []
        rows = []
        for item in self._pending_questions():
            buttons = [("Answer", "quiet", self._waiting_all)]
            asked = summary.one_line(
                item.get("question") or item.get("text") or "",
                self._row_room(buttons), self._measure)
            rows.append({
                "at": self._stamp_of(item.get("when", ""),
                                     "%Y-%m-%d %H:%M:%S"),
                "kind": "question", "mark": "review",
                "mark_colour": getattr(ui, "ACCENT_TEXT", ui.ACCENT),
                "eyebrow": "Saturday's read is waiting on an answer",
                "text": asked.text,
                "note": "" if asked.whole else "Answer has the rest of it",
                "buttons": buttons,
            })
        return rows

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
                            self._problems_stat(), self._questions_stat())
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
        """The five places, each as (place, glyph, number, what the
        number is, what the place is for).

        Every number here is the number of ROWS the place will show him
        when he gets there, which is the only kind of count worth
        putting on a door: Corrections is what the second reading is
        proposing, Problems is his reports and the routine's questions
        together (they share a place, so they share a tile), Said is
        today's dictations, and Keys and Settings are as long as their
        own lists. Unread messages are deliberately not here: their
        place IS this page, and a door back to the page you are standing
        on is not a door.
        """
        today = time.strftime("%Y-%m-%d")
        said = sum(1 for e in self.log
                   if e.kind == "dictation"
                   and e.when.strftime("%Y-%m-%d") == today)
        learned = _words_learned()
        proposals = sum(1 for i in items if i["kind"] == "review")
        trouble = sum(1 for i in items
                      if i["kind"] in ("problem", "question"))
        return [
            ("Corrections", "review", proposals, "corrections waiting",
             "and the words it has learned from the ones you said yes to"
             if learned is None else
             f"and the {learned} words it has learned from them"),
            ("Problems", "error", trouble, "problems open",
             "what you reported, and what the weekly routine asked you"
             if self._problems_on else
             "reporting is switched off — the switch is in Settings"),
            ("Said", "history", said, "said today",
             "the last hundred of them, with the search over them"),
            ("Keys", "keys", len(config_mod.HOTKEY_FIELDS), "keys to press",
             "every one of them lit on a drawn keyboard"),
            ("Settings", "settings", len(settings_mod.TABS),
             "tabs of settings",
             "every setting, in the words the file's own comments use"),
        ]

    def _paint_doors(self, items: list[dict]) -> None:
        """The band under the pile: the five places, what each of them is
        holding right now, and the way in.

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
        p["strip_awake"].config(text=sentence)
        p["strip_awake"].update_idletasks()

        bits = []
        phone = (self.status or {}).get("phone")
        bits.append("phone live" if phone else "phone off")
        if getattr(self, "branch", "") not in ("", "?"):
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
                text="History is off (Settings > Dictation > What you said, "
                     "kept)." if off and not self.log
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

    def _problems_stat(self):
        """The store's own change detector. () is "no file yet", which is
        a perfectly good state and not an error."""
        store = self._problems_store()
        if store is None:
            return ()
        try:
            return store.stamp()
        except Exception:                 # noqa: BLE001
            return ()

    # --------------------------------------------------- and the questions

    def _questions(self):
        """questions.py, or None if it is not here.

        Guarded exactly like problems.py above, and for a sharper reason:
        this module arrived with the weekly routine, so a checkout that
        predates it has no such file — and the Problems screen still has
        to open on that checkout, with the reports and without the
        questions.
        """
        try:
            import questions as questions_mod
        except Exception:                 # noqa: BLE001 — feature absent
            return None
        return questions_mod

    def _questions_store(self):
        """questions.json, read off the disk — but only when `[questions]
        enabled = true` says the app is the place he answers.

        It is off by default, and the reason is not caution. The weekly
        review is a Claude Code local scheduled task now: every run is a
        real session with a composer in the sidebar, so it asks him there
        and reads the answer in the same breath. The store still gets each
        question, as a record that outlives the session — but a record is
        not a queue. Drawing an answer surface over it would offer him a
        question he may already have answered in the session, and the item
        would stay PENDING here forever because the answer landed
        somewhere else. So this screen shows the reports and the branch
        rows, and the answering lives where the asking does.

        THREE processes can still write this file when it is on — the
        app's card, this window and the routine — which is why the store
        carries a lock file and lands every write by rename; nothing here
        has to arbitrate.
        """
        module = self._questions()
        if module is None:
            return None
        try:
            qcfg = getattr(config_mod.load_layered(), "questions", None)
        except Exception:                 # noqa: BLE001 — unreadable config
            qcfg = None                   # off, like an absent section
        if qcfg is None or not getattr(qcfg, "enabled", False):
            return None
        try:
            return module.Store(paths.DATA_DIR / module.STORE_NAME)
        except Exception:                 # noqa: BLE001
            return None

    def _questions_stat(self):
        store = self._questions_store()
        if store is None:
            return ()
        try:
            return store.stamp()
        except Exception:                 # noqa: BLE001
            return ()

    def _pending_questions(self) -> list[dict]:
        """The questions waiting on him, newest first.

        [] for no questions.py, no questions.json, and a questions.json
        that will not parse — the store already reads a broken file as
        empty, because a bad store must cost him questions and never
        dictation.
        """
        module, store = self._questions(), self._questions_store()
        if module is None or store is None or not paths.DEVELOPER:
            # The questions are the Saturday routine's, and the routine
            # runs only on the owner's checkout (D15, D33): a stranger's
            # copy has nobody to ask them.
            return []
        try:
            return store.items(module.PENDING)
        except Exception:                 # noqa: BLE001 — a broken file
            return []

    def _write_digest(self) -> None:
        """Regenerate problems.md.

        It is written from scratch every call, and it is what the weekly
        read-through actually reads — so the cheapest way to keep it true
        is to write it whenever the list is opened or answered, rather
        than remembering to.
        """
        module, store = self._problems(), self._problems_store()
        if module is None or store is None:
            return
        try:
            module.digest(store, paths.DATA_DIR / module.DIGEST_NAME)
        except Exception:                 # noqa: BLE001 — a digest that
            pass                          # did not get written is nothing

    def _open_digest(self) -> None:
        """The weekly read, in whatever opens .md files here. The name
        comes off the module rather than out of this line, so the two
        cannot drift; the fallback is for the module being absent, when
        the file will not be there either and open_path says so."""
        name = getattr(self._problems(), "DIGEST_NAME", "problems.md")
        launch.open_path(paths.DATA_DIR / name)

    def _screen_problems(self) -> None:
        """A place of its own: every report, every question the routine
        asked, every change committed here and not yet on GitHub.

        The pile on the home says WHAT is waiting in one line each; this
        is where a thing that needs more than a line gets it — a question
        with two to five answers to press and a box to dictate into, a
        report with its evidence, the changes on this computer with the
        three buttons that try, push or undo them. It was a view hiding
        behind the home until he
        asked for it as a tab: "The report problem, I would like that to
        be in tabs."

        His own bug list: what he reported, and whether it is answered.

        The shape is Review's, because the job is Review's — rows out of
        a json store, two buttons each — and the only difference is who
        asked the question. Review is the app disagreeing with itself;
        this is him disagreeing with the app.

        AND IT IS WHERE THE ROUTINE ANSWERS BACK. The weekly run reads
        these reports, builds what he has already approved and — for what
        it cannot decide — asks him a question with as many real answers
        as it honestly has, two to five, and a box that is always under
        them. A question belongs WITH THE
        REPORT IT IS ABOUT, so it is drawn under it; the branch the
        routine committed its work to gets a row of its own, with the one
        button that publishes it.
        """
        # No right-hand line on this title: the Report button is up there
        # and the two ran into each other (photographed 2026-09-07).
        self._title("Problems")
        p = self.parts
        if self._problems_on:
            p["report_button"] = ui.Button(
                self.sheet, "Report a problem", self._report, h=30,
                w=widgets.button_width("Report a problem", icon=True),
                bg=ui.BG, quiet=True, icon=ui.ICON["error"])
            p["report_button"].place(x=PAD + CW, y=20, anchor="ne")
        p["problems_head"] = tk.Label(self.sheet, text="", bg=ui.BG,
                                      fg=ui.DIM, font=(ui.UI, 10))
        p["problems_head"].place(x=PAD, y=66)
        # WHAT NEEDS HIM LEADS THE TAB. The report counts are a state of
        # the world; a pending question is the routine standing still
        # until he answers, so when there is one it takes the left of
        # this line and the counts move over. _fill_problems places both.
        p["questions_head"] = tk.Label(self.sheet, text="", bg=ui.BG,
                                       fg=ui.ACCENT_TEXT,
                                       font=(ui.MEDIUM, 10))
        p["problems_list"] = ui.Scroller(self.sheet, CW + 10, 498, bg=ui.BG)
        p["problems_list"].place(x=PAD, y=100)
        p["problems_empty"] = tk.Label(self.sheet, text="", bg=ui.BG,
                                       fg=ui.FAINT, font=(ui.UI, 10),
                                       wraplength=CW - 80, justify="center")
        tk.Label(self.sheet,
                 # ONE LINE. There is room under the list for exactly
                 # one at this width, and the second wraps off the
                 # bottom edge of the window where nobody will read it.
                 text="Report a problem is on the home as well, and on "
                      "Ctrl+Alt+R wherever you are. Reopen puts an "
                      "answered one back; ✕ throws one away, and asks "
                      "first.",
                 bg=ui.BG, fg=ui.FAINT, font=(ui.UI, 8),
                 wraplength=CW - 190, justify="left").place(x=PAD, y=620)
        if paths.DEVELOPER:
            # problems.md is the digest the Saturday routine reads; the
            # button and the file are the owner's (PR 7).
            wide = widgets.button_width("Open problems.md", icon=True)
            ui.Button(self.sheet, "Open problems.md", self._open_digest,
                      w=wide, h=30, quiet=True, bg=ui.BG,
                      icon=ui.ICON["page"]).place(x=PAD + CW - wide, y=616)
        self._problems_stamp = None
        self._questions_stamp = None
        # A "delete this?" does not survive leaving the tab and coming
        # back to it: he answered it by walking away.
        self._problem_asking = ""
        if paths.DEVELOPER:
            # Opening the tab is the cue: the weekly read wants
            # problems.md current, and this is the moment it is known to
            # be looked at.
            self._write_digest()
            # The changes are git, and git is a process spawn per
            # question — so they are asked for off this thread when the
            # tab opens, and again after each button. Never on the poll:
            # five spawns a second for a list that changes when a
            # session commits. A stranger's copy has no git at all.
            self._scan_changes()
        self._fill_problems(home=True)

    def _waiting_all(self) -> None:
        """The old door to the backlog. It is a place now."""
        self._show("Problems")

    def _poll_problems(self) -> None:
        """Once a second from _refresh: redraw only when one of the two
        files moved — a report filed from the running app or answered
        here, a question the routine asked, or an answer given on the
        card in the other window."""
        if "problems_list" not in self.parts:
            return
        if (self._problems_stat() != getattr(self, "_problems_stamp", None)
                or self._questions_stat()
                != getattr(self, "_questions_stamp", None)):
            self._fill_problems()

    def _fill_problems(self, *, home: bool = False) -> None:
        """Draw the whole list again.

        `home` only when the TAB is being opened. Every other caller —
        the poll that sees another process write the store, a Fixed, a
        Reopen, a ✕ — leaves the view exactly where he was reading,
        because this rebuilds every row from scratch and taking him back
        to the top is taking the list away from him. His words on
        2026-09-08, pressing ✕ on a report far down the page: "it makes
        the screen jump up and then I just scroll down and then press
        delete".
        """
        if "problems_list" not in self.parts:
            return
        self._problems_stamp = self._problems_stat()
        self._questions_stamp = self._questions_stat()
        module, store = self._problems(), self._problems_store()
        waiting, done, summary = [], [], {}
        if module is not None and store is not None:
            try:
                waiting = store.items(module.OPEN)
                done = [i for i in store.items()
                        if i.get("status") in module.RESOLVED][:30]
                summary = store.summary()
            except Exception:             # noqa: BLE001 — a broken file
                waiting, done, summary = [], [], {}
        qmodule = self._questions()
        asked = self._pending_questions()
        changes = (self._changes or {}) if paths.DEVELOPER else {}
        ahead = bool(changes.get("commits"))
        head = self.parts["problems_head"]
        asking = self.parts["questions_head"]
        # "fixed?" only when there is one, and between open and fixed:
        # it is the part of open that is waiting on HIM to try something,
        # not a fourth state. The line is one Label in one colour, so
        # the count is not amber here the way the tag on the row is —
        # colouring one word would mean a second label placed by
        # measuring the first, for a number that is usually zero.
        maybe = summary.get("maybe", 0)
        head.config(text=f"{summary.get('open', 0)} open   ·   "
                         + (f"{maybe} fixed?   ·   " if maybe else "")
                         + f"{summary.get('fixed', 0)} fixed   ·   "
                         f"{summary.get('closed', 0)} closed")
        head.place_forget()
        asking.place_forget()
        if asked:
            asking.config(text=f"{len(asked)} question"
                               f"{'' if len(asked) == 1 else 's'} waiting "
                               f"on you")
            asking.place(x=PAD, y=66)
            head.place(x=PAD + CW, y=68, anchor="ne")
        else:
            head.place(x=PAD, y=66)
        scroller = self.parts["problems_list"]
        # Measured BEFORE the rows go: clear() empties the page and the
        # view drops to the top with it.
        place = scroller.keep_place()
        scroller.clear()
        self._q_fields = {}
        self._asking_row = None
        empty = self.parts["problems_empty"]
        empty.place_forget()
        if module is None:
            empty.config(text="problems.py is not here, so nothing can be "
                              "reported or read back.")
            empty.place(x=PAD + CW / 2, y=300, anchor="center")
        elif not waiting and not done and not asked and not ahead:
            empty.config(text="Nothing reported yet — when something is "
                              "wrong, say so from the sidebar and the app "
                              "attaches the rest.")
            empty.place(x=PAD + CW / 2, y=300, anchor="center")
        # A QUESTION BELONGS WITH ITS REPORT, and these are the reports
        # that are about to be drawn. Anything asked about a report that
        # is not one of them — a question with no report_id at all, or
        # one about a report old enough to have fallen off the bottom of
        # the resolved list — goes in a block of its own at the TOP,
        # because a question is the routine waiting on him and there is
        # no such thing as one with nowhere to answer it.
        shown = {str(i.get("id", "")) for i in waiting + done}
        # An "are you sure" whose row is not on the screen any more — the
        # report was answered in the other window, or aged out — is not a
        # question, and it must not be waiting on the next report that
        # happens to be drawn under the pointer.
        if self._problem_asking and self._problem_asking not in shown:
            self._problem_asking = ""
        homed: dict = {}
        loose: list = []
        for item in asked:
            report_id = str(item.get("report_id") or "")
            if report_id and report_id in shown:
                homed.setdefault(report_id, []).append(item)
            else:
                loose.append(item)
        if loose:
            self._question_block(scroller, qmodule, loose,
                                 "A QUESTION, NOT ABOUT ONE REPORT")
        if changes.get("told"):
            self._changes_block(scroller, changes)
        for item in waiting:
            self._problem_row(scroller, module, item, open_=True)
            self._question_block(scroller, qmodule,
                                 homed.get(str(item.get("id", "")), []), "")
        if done:
            tk.Label(scroller.inner, text="ANSWERED", bg=ui.BG,
                     fg=ui.FAINT, font=(ui.MEDIUM, 8)).pack(
                anchor="w", pady=(8 if waiting else 0, 6))
        for item in done:
            self._problem_row(scroller, module, item, open_=False)
            self._question_block(scroller, qmodule,
                                 homed.get(str(item.get("id", "")), []), "")
        if home:
            scroller.to_top()
        else:
            scroller.go_back_to(place)
        # And if a row grew where it stands — the "are you sure" opening
        # under the last report on the page — the least scroll that puts
        # its two answers on screen. Nothing at all when they already
        # are, which is the usual case.
        if self._asking_row is not None:
            scroller.bring_into_view(self._asking_row)
        # The echo poll runs only while there is a field to read, and it
        # stops itself the moment the screen goes.
        if self._q_fields and self._q_after is None and not self.closing:
            self._q_after = self.root.after(Q_POLL_MS, self._q_pump)
        # And the caret goes back where it was. This redraw is usually
        # triggered by ANOTHER PROCESS writing the store, and it must not
        # cost him the field in the middle of dictating an answer into it.
        spec = self._q_fields.get(self._q_focus or "")
        if spec is not None:
            try:
                spec["field"].focus_set()
                spec["field"].mark_set("insert", "end-1c")
            except Exception:             # noqa: BLE001
                pass

    @staticmethod
    def _problem_evidence(got: dict) -> str:
        """The dictation a report was about, as the one line worth
        reading: what came out, and how it was decoded. Empty when the
        report was not about a dictation, which is most ideas."""
        if not got:
            return ""
        bits = []
        raw = str(got.get("raw") or "")
        final = str(got.get("final") or got.get("text") or "")
        if raw and final and raw != final:
            bits.append(f"{raw}  →  {final}")
        elif raw or final:
            bits.append(raw or final)
        facts = [str(got[k]) for k in ("backend", "language") if got.get(k)]
        if got.get("seconds") not in (None, ""):
            try:
                facts.append(f"{float(got['seconds']):.1f}s")
            except (TypeError, ValueError):
                pass
        if facts:
            bits.append(" · ".join(facts))
        return "   ·   ".join(bits)

    @staticmethod
    def _problem_hint(mark: dict) -> str:
        """The amber line under a report somebody believes is fixed: the
        mark's note, and what he does about it — "try it, then press
        Fixed". The trailer is left off when the note already says so,
        because a Hebrew note that ends in "ולחץ Fixed" followed by the
        same instruction in English is the row nagging. A mark with no
        note at all still gets the instruction, capitalised, because the
        line has to say SOMETHING about why the tag is there."""
        note = " ".join(str(mark.get("note") or "").split())
        if "fixed" in note.lower():
            return note
        return f"{note} — try it, then press Fixed" if note \
            else "Try it, then press Fixed"

    @staticmethod
    def _row_photo(module, item: dict):
        """The screenshot filed with a report, small enough for a row.

        None for the reports that have none, which is most of them — an
        idea about this screen is not a photograph — and None again for a
        shot whose file has been deleted or will not open. Neither is an
        error: problems.thumb already decided that a missing picture is a
        row without a picture, and a redraw must never depend on a jpeg.

        problems.thumb caches by (path, mtime, side), which is what makes
        this affordable at all: _fill_problems rebuilds every row from
        scratch on every poll that sees a new stamp.
        """
        try:
            png = module.thumb(paths.DATA_DIR, item)
        except Exception:                 # noqa: BLE001 — never a traceback
            return None                   #                into a redraw
        if not png:
            return None
        try:
            return tk.PhotoImage(data=png)
        except tk.TclError:
            return None

    def _problem_row(self, scroller: ui.Scroller, module, item: dict,
                     open_: bool) -> None:
        """One report, one canvas: when it was filed on the left, what
        kind it is and which screen it came from, his line, and the
        dictation behind it when there was one. Fixed / Closed while it
        is still open, the answer itself once it is not.

        Same layout rules as a review row — time and the buttons on the
        left, text flush right — because they are the same kind of row
        and looking different would only say they were not.

        A report that came with a screenshot shows it, small, in the
        right-hand corner: what he wants off this list is "which of these
        is the one I mean", and the picture of the screen answers that
        faster than the line he typed about it. The text column gives up
        that width and the row gets tall enough to hold the picture,
        which is why both are measured before the canvas exists.

        NOTHING HERE IS A ONE-WAY DOOR. An answered row carries Reopen,
        because Fixed and Closed were being pressed by accident and there
        was no way back — he found four of his own reports closed and
        said so: "open them again because I did not close them, and if I
        close something I should be able to open it again". And the ✕
        that deletes a report asks before it does: pressing it grows the
        row by one line — "Delete this report?" with Delete and Keep it
        under it — and only Delete calls the store. Both answers are on
        the LEFT of the strip, at the far end of the row from the ✕ he
        just pressed, which is the same reason Stop sits where it does on
        the bar: the safety is the layout, not a word that changes.

        AND NOBODY BUT HIM CLOSES A ROW FROM HERE. An open report that a
        routine (or a session) believes it has fixed is still an open
        row with the same Fixed and Close on it; what it gains is a
        FIXED? tag beside the kind, in amber and not in the green of the
        Fixed button, and one amber line under his text saying what to
        try. The weekly routine closed three of his reports on
        2026-09-12 because a push looked like a fix, and his answer was
        "instead of writing 'fix' it writes 'fix?' in a different colour,
        not green like now" — and asks him. Pressing Fixed on such a row
        is the answer: resolve() takes the mark off with the status.
        """
        text = str(item.get("text") or "")
        ident = str(item.get("id", ""))
        asking = bool(ident) and ident == self._problem_asking
        left, edge = 106, CW - 14
        shot = self._row_photo(module, item)
        shot_w = shot.width() + 12 if shot is not None else 0
        width = edge - left - shot_w
        colour = ui.FG if open_ else ui.DIM
        photo, text_h, _lines = ui.draw_text(text, pt=11, width=width,
                                             max_lines=3, colour=colour,
                                             bg=ui.CARD)
        heard, heard_h = None, 0
        evidence = self._problem_evidence(item.get("dictation") or {})
        if evidence:
            heard, heard_h, _l = ui.draw_text(evidence, pt=8, width=width,
                                              max_lines=2, colour=ui.FAINT,
                                              bg=ui.CARD)
        # The "fixed?" line, through draw_text like the two above it: the
        # routine writes the note in Hebrew for him, and a Label would
        # lay a mixed line out backwards. Two lines, not one — the note
        # is the sentence that tells him what to try, and an ellipsis on
        # it is the one cut this row must not make.
        mark = module.suggested(item) if open_ else None
        hint, hint_h = None, 0
        if mark is not None:
            hint, hint_h, _l = ui.draw_text(self._problem_hint(mark), pt=8,
                                            width=width, max_lines=2,
                                            colour=ui.AMBER, bg=ui.CARD)
        bottom = 32 + text_h + (heard_h + 8 if heard is not None else 0) \
            + (hint_h + 8 if hint is not None else 0)
        # 46 is a strip with buttons in it, and an answered row has them
        # now (Reopen) where it used to have one line of text. 70 is that
        # strip with the question standing above the two answers, so a
        # row asking whether it may be deleted VISIBLY grows — which is
        # the "are you sure" jumping out at him, without a second window.
        height = max(84, bottom + (70 if asking else 46))
        if shot is not None:
            height = max(height, shot.height() + 26)
        row = tk.Canvas(scroller.inner, width=CW, height=height, bg=ui.BG,
                        highlightthickness=0, bd=0)
        row.pack(pady=(0, 8))
        row.create_image(0, 0, anchor="nw", image=ui.rounded(
            CW, height, 12, ui.CARD, ui.BG,
            ui.TILE_EDGE if open_ else ui.LINE))
        if shot is not None:
            row.create_image(edge, 13, anchor="ne", image=shot)
            row.create_rectangle(edge - shot.width() - 1, 12, edge, 13
                                 + shot.height(), outline=ui.STROKE)
            # The canvas is the reference that keeps it: a PhotoImage
            # nothing in Python holds is collected, and the row then
            # draws a blank box where the picture was.
            row.shot = shot
        # "2026-09-04T13:22:01" — sliced rather than parsed, because a
        # stamp this window did not write is not worth a traceback.
        at = str(item.get("at", ""))
        row.create_text(14, 15, text=at[11:16], anchor="nw",
                        font=(ui.UI, 10, "bold"), fill=ui.FG)
        try:
            day = time.strftime("%d %b", time.strptime(at[:10], "%Y-%m-%d"))
        except ValueError:
            day = ""
        row.create_text(14, 34, text=day, anchor="nw", font=(ui.UI, 8),
                        fill=ui.FAINT)
        kind = str(item.get("kind") or "")
        where = str(item.get("where") or "")
        tagline = "  ·  ".join(p for p in (kind.upper(), where.upper())
                               if p)
        tags = row.create_text(left, 13, anchor="nw", font=(ui.MEDIUM, 8),
                               fill=ui.AMBER if open_ else ui.FAINT,
                               text=tagline)
        if mark is not None:
            # FIXED? after the kind and the surface, in their small caps
            # and their amber — ui.AMBER, the colour this window already
            # gives a note that wants his attention — and deliberately
            # not the green of the Fixed button beside it, because green
            # would say it is done. A hairline of the
            # same amber round it is what makes it read as a mark somebody
            # put on the row rather than a third tag; drawn AFTER the
            # word so the box is measured off the word at whatever DPI
            # this screen is, and sent under it.
            box = row.bbox(tags) if tagline else None
            x = box[2] + 10 if box else left
            label = row.create_text(x + 7, 13, anchor="nw",
                                    font=(ui.MEDIUM, 8), fill=ui.AMBER,
                                    text="FIXED?")
            x0, y0, x1, y1 = row.bbox(label)
            wide, tall = x1 - x0 + 12, y1 - y0 + 2
            frame = row.create_image(x, y0 - 1, anchor="nw",
                                     image=ui.rounded(wide, tall, tall // 2,
                                                      ui.CARD, ui.CARD,
                                                      ui.AMBER))
            row.tag_lower(frame, label)
        row.create_image(left, 30, anchor="nw", image=photo)
        if heard is not None:
            # Flush right of the TEXT COLUMN, not of the row: with a
            # thumbnail in the corner those are no longer the same edge,
            # and anchoring to the row's would lay a short report's
            # evidence line straight across the picture.
            row.create_image(edge - shot_w, 32 + text_h, anchor="ne",
                             image=heard)
        if hint is not None:
            # Under the evidence when there is any, flush right of the
            # same column, for the same reason.
            row.create_image(edge - shot_w, 32 + text_h
                             + (heard_h + 8 if heard is not None else 0),
                             anchor="ne", image=hint)
        if asking:
            # _fill_problems scrolls to this one if it grew off the
            # bottom edge of the page.
            self._asking_row = row
            row.create_text(14, height - 62, anchor="nw", font=(ui.UI, 9),
                            fill=ui.FG,
                            text="Delete this report? It does not come "
                                 "back. Its picture and its recording "
                                 "stay in the problems folder.")
            wide = widgets.button_width("Keep it", least=62)
            gone = ui.Button(row, "Delete", lambda i=ident:
                             self._problem_delete(i),
                             w=wide, h=26, quiet=True, fg=ui.RED)
            keep = ui.Button(row, "Keep it", self._problem_keep,
                             w=wide, h=26, quiet=True, fg=ui.FG)
            row.create_window(14, height - 38, window=gone, anchor="nw")
            row.create_window(22 + wide, height - 38, window=keep,
                              anchor="nw")
        elif open_:
            fixed = ui.Button(row, "Fixed", lambda i=ident:
                              self._problem_decide(i, module.FIXED),
                              w=58, h=26, quiet=True, fg=ui.GREEN)
            shut = ui.Button(row, "Close", lambda i=ident:
                             self._problem_decide(i, module.CLOSED),
                             w=58, h=26, quiet=True, fg=ui.FAINT)
            row.create_window(14, height - 38, window=fixed, anchor="nw")
            row.create_window(76, height - 38, window=shut, anchor="nw")
        else:
            status = str(item.get("status") or "")
            by = str(item.get("by") or "")
            wide = widgets.button_width("Reopen", least=62)
            back = ui.Button(row, "Reopen", lambda i=ident:
                             self._problem_decide(i, module.OPEN),
                             w=wide, h=26, quiet=True, fg=ui.ACCENT_TEXT)
            row.create_window(14, height - 38, window=back, anchor="nw")
            # Centred on the button beside it, not sat on the row's floor:
            # the line and the pill are one strip and they read as one.
            row.create_text(22 + wide, height - 25, anchor="w",
                            font=(ui.UI, 8),
                            fill=ui.GREEN if status == module.FIXED
                            else ui.FAINT,
                            text=status + (f"  ·  {by}" if by else ""))
        if not asking and ident:
            # The far corner of the strip, and LEFT of the picture when
            # there is one: the thumbnail owns the right edge from y13
            # down, and a ✕ under it would be a delete drawn on top of a
            # screenshot. Same label, same hover and same 11 pt as the ✕
            # on a pile row (widgets.PileRow), because it is the same
            # gesture — except that this one asks.
            cross = tk.Label(row, text="✕", bg=ui.CARD, fg=ui.FAINT,
                             font=(ui.UI, 11), cursor="hand2", padx=6)
            cross.bind("<Button-1>",
                       lambda _e, i=ident: self._problem_ask_delete(i))
            cross.bind("<Enter>", lambda _e, w=cross: w.config(fg=ui.RED))
            cross.bind("<Leave>", lambda _e, w=cross: w.config(fg=ui.FAINT))
            row.create_window(edge - shot_w, height - 25, window=cross,
                              anchor="e")
        scroller.bind_wheel(row)

    def _problem_decide(self, ident: str, status: str) -> None:
        """Fixed, Closed or Reopen on a row, written to problems.json
        here.

        `by` is why resolve() takes the argument at all: a report can be
        answered from this window or from wherever else the store grows a
        surface, and the digest says which. REOPENING CLEARS IT, because
        the field is who answered the report and a reopened one has not
        been answered — leaving "dashboard" there would put this window's
        name on a resolution it had just taken away.
        """
        store = self._problems_store()
        module = self._problems()
        if store is None or module is None:
            self._note("problems.py is not here")
            return
        back = status == module.OPEN
        try:
            saved = store.resolve(ident, status, by="" if back
                                  else "dashboard")
        except Exception as e:            # noqa: BLE001
            self._note(f"could not save that: {e}")
            return
        if not saved:
            self._note("that one is not in the list any more")
        else:
            self._note("open again — it is back on the list and on the "
                       "home" if back else f"marked {status}")
        self._write_digest()
        self._fill_problems()

    def _problem_ask_delete(self, ident: str) -> None:
        """The ✕, pressed. Nothing is deleted here — the row is asked.

        His own words for why there is a step at all: "when I'm pressing
        the X, a question mark will jump, or a message that says are you
        sure, because I don't want the reports to be deleted instantly".
        One at a time, so a second ✕ moves the question rather than
        leaving two rows open with a Delete on each.
        """
        self._problem_asking = str(ident)
        self._fill_problems()

    def _problem_keep(self) -> None:
        """Keep it: the answer that is not a delete, and the one the row
        goes back to on its own if he opens another tab."""
        self._problem_asking = ""
        self._fill_problems()

    def _problem_delete(self, ident: str) -> None:
        """Delete, pressed on a row that has already asked. The report
        leaves problems.json for good; the screenshot and the copied
        recording stay in problems\\, which is what the note says out
        loud so he is never guessing what he just did."""
        self._problem_asking = ""
        store = self._problems_store()
        if store is None:
            self._note("problems.py is not here")
            return
        try:
            gone = store.remove(ident)
        except Exception as e:            # noqa: BLE001
            self._note(f"could not delete that: {e}")
            return
        if gone is None:
            self._note("that one is not in the list any more")
        elif gone.get("shot") or gone.get("dictation"):
            self._note("deleted — its picture and its recording are still "
                       "in the problems folder")
        else:
            self._note("deleted")
        self._write_digest()
        self._fill_problems()

    # ------------------------------------------- answering the routine back

    def _question_block(self, scroller: ui.Scroller, module,
                        items: list[dict], header: str) -> None:
        """The questions that belong here, in a frame of their own.

        A FRAME rather than rows packed straight into the list, for two
        reasons. A question and the report above it read as one thing
        when they are one widget — which is the point of putting it
        there — and the list's own children stay countable: everything
        that walks `problems_list` is counting REPORTS, and a question
        is not one.
        """
        if module is None or not items:
            return
        block = tk.Frame(scroller.inner, bg=ui.BG)
        block.pack(anchor="w", fill="x", pady=(0, 0))
        if header:
            tk.Label(block, text=header, bg=ui.BG, fg=ui.ACCENT_TEXT,
                     font=(ui.MEDIUM, 8)).pack(anchor="w", pady=(0, 6))
        for item in items:
            self._question_row(block, scroller, module, item)

    def _question_row(self, parent, scroller: ui.Scroller, module,
                      item: dict) -> None:
        """One question the routine could not answer for itself: what it
        asked, EVERY answer it offered as a band to press, and a box he
        can type or dictate into that is always there.

        NO OPTION IS SPECIAL AND THE BOX IS NOT AN OPTION. There used to
        be a split right here — the last option was drawn as the box's
        label instead of as a band, because questions.py named an "open"
        option by position — and it went with the design it came from.
        Every entry in `options` is a real answer he can press, two to
        five of them, however many the question honestly has; the box
        under them belongs to no band, and no band can take it away,
        dim it or make him press something first to reach it. An item
        with no options at all is not a special case either — it is the
        box on its own, which is what the imported prose questions are.

        A PICK AND A TYPED LINE ARE ONE ANSWER. His own case for it: he
        presses "run before the backup" and then writes "actually after
        the backup, so that it doesn't fight the disk" — the band is the
        decision and the line is the condition on it. So a press does not
        clear the box, a word does not clear the band, and both go to the
        store together. answer_card.py's docstring is where that decision
        is written down and overlay.AnswerCard keeps it on the card; this
        row is the second surface keeping the same one.

        PRESSING THE LIT BAND AGAIN UN-PICKS IT, which is the card's
        gesture exactly (overlay.AnswerCard.pick — "the same gesture
        un-picks") and for the card's reason: the band that shows the
        pick is the obvious place to undo it, and a separate Clear is one
        more control on a row that already has five bands, a box and a
        button. The line under the button says so out loud, because an
        undo nobody can see is an undo nobody uses.

        EVERY SENTENCE HERE GOES THROUGH ui.draw_text, and no option is a
        ui.Chip. The options are the routine's, they will be Hebrew, and
        a MIXED Hebrew/English line laid out by Tk comes back with its
        runs in the wrong order (this file's docstring, layer 2). On a
        transcript that is ugly; on a multiple-choice answer it is him
        pressing the wrong one.
        """
        ident = str(item.get("id", ""))
        # Blanks dropped and NOTHING INVENTED to replace them, with the
        # card's own ceiling — answer_card.card_for does exactly this, and
        # for the store's reason: every band is an answer he might press,
        # so padding a short list would put a sentence on this row that
        # nothing ever said, and this window is not allowed to write
        # answers.
        options = [text for text in (str(o or "").strip()
                                     for o in (item.get("options") or ()))
                   if text][:Q_OPTIONS_MAX]
        # A pick that no longer points at an option: the store moved under
        # us, or the file was hand-edited. Forget it rather than draw a
        # dot beside nothing.
        picked = self._q_choice.get(ident)
        if picked is not None and not 0 <= picked < len(options):
            self._q_choice.pop(ident, None)
        width = CW - Q_INDENT
        inner = width - 2 * Q_PAD
        text_w = inner - Q_MARK - Q_PAD

        # MEASURED FIRST, all of it, because the card is exactly as tall
        # as what is in it and a canvas is sized once. Every draw_text
        # here is cached on its arguments, so the second call for the
        # same bitmap — one to measure, one to place — is free.
        question, q_h, _l = ui.draw_text(str(item.get("question") or ""),
                                         pt=11, width=inner, max_lines=3,
                                         colour=ui.FG, bg=ui.CARD)
        # EVERY option gets a band, and each band is as tall as its own
        # sentence needs — the loop is the whole point, the way
        # answer_card.layout's is: a fixed height either clips the long
        # one or leaves the short ones swimming, and the count is the
        # question's business.
        bands: list[dict] = []
        for index, option in enumerate(options):
            on, on_h, _l = ui.draw_text(option, pt=10, width=text_w,
                                        max_lines=2, colour=ui.FG,
                                        bg=ui.ACCENT_SOFT)
            off, off_h, _l = ui.draw_text(option, pt=10, width=text_w,
                                          max_lines=2, colour=ui.DIM,
                                          bg=ui.CARD_HI)
            band_h = max(Q_BAND_MIN, max(on_h, off_h) + 14)
            bands.append({"index": index, "on": on, "off": off,
                          "text_h": max(on_h, off_h), "h": band_h})
        # THE CAPTION IS THE CARD'S LINE NOW, not one of the options. It
        # used to be the last option's own Hebrew, because that option WAS
        # the box; with the open row gone nothing named the box, and a box
        # under a list of choices that says nothing about itself reads as
        # the choice of last resort. Skipped when there are no bands —
        # "add to a choice" with nothing above it to add to would be a
        # line about controls that are not on this row.
        caption, capt_h = None, 0
        if options:
            caption, capt_h, _l = ui.draw_text(Q_FIELD_CAP, pt=8,
                                               width=inner, max_lines=1,
                                               colour=ui.FAINT, bg=ui.CARD)
        field_h = Q_FIELD_LINES_MIN * FIELD_LINE_H + 2 * FIELD_PAD_Y
        # One line of the echo, asked of the renderer that will draw it.
        _probe, line_h, _l = ui.draw_text("Ag", pt=10, width=inner,
                                          max_lines=1, colour=ui.DIM,
                                          bg=ui.CARD)
        echo_h = line_h * Q_ECHO_LINES

        y = 32
        y_question = y
        y += q_h + 12
        for band in bands:
            band["y"] = y
            y += band["h"] + 6
        if bands:
            # The gap that separates TWO THINGS, not the six pixels that
            # join one band to the next: the box is a peer of the bands
            # now, not the last one's body. answer_card.FIELD_GAP is the
            # same 15 for the same reason.
            y += 9
        y_caption = y
        y += capt_h + (6 if caption is not None else 0)
        y_field = y
        y += field_h + 6
        y_echo = y
        y += echo_h + 10
        y_actions = y
        height = y_actions + 30 + 12

        row = tk.Canvas(parent, width=width, height=height, bg=ui.BG,
                        highlightthickness=0, bd=0)
        row.pack(anchor="w", padx=(Q_INDENT, 0), pady=(0, 8))
        # The accent edge is what says this card is not another report:
        # the reports around it are hairlined, and this one is the app
        # asking rather than him telling.
        row.create_image(0, 0, anchor="nw", image=ui.rounded(
            width, height, 12, ui.CARD, ui.BG, ui.ACCENT_EDGE))
        # The canvas is the only reference Python holds to these: a
        # PhotoImage nothing keeps is collected, and the row then draws
        # blank boxes where the sentences were.
        row.keep = [question, caption] + [b["on"] for b in bands] \
            + [b["off"] for b in bands]
        at = str(item.get("at", ""))
        try:
            day = time.strftime("%d %b", time.strptime(at[:10], "%Y-%m-%d"))
        except ValueError:
            day = ""
        row.create_text(Q_PAD, 12, anchor="nw", font=(ui.MEDIUM, 8),
                        fill=ui.ACCENT_TEXT,
                        text="  ·  ".join(p for p in
                                          ("A QUESTION FOR YOU",
                                           f"ASKED {at[11:16]} {day}".strip()
                                           if at else "") if p))
        row.create_image(Q_PAD, y_question, anchor="nw", image=question)

        field = tk.Text(row, bg=ui.EDGE, fg=ui.FG,
                        insertbackground=ui.ACCENT,
                        selectbackground=ui.ACCENT_SOFT,
                        selectforeground=ui.FG, bd=0, highlightthickness=0,
                        wrap="word", undo=True, font=FIELD_FONT,
                        spacing3=max(0, FIELD_LINE_H - FIELD_FONT_LINE),
                        insertwidth=2, padx=FIELD_PAD_X - Q_WELL_INSET,
                        pady=FIELD_PAD_Y - Q_WELL_INSET)
        field.tag_configure("rtl", justify="right")

        def paint() -> None:
            """The dots and the faces, from the one place the pick is
            kept. Called by a press and by the redraw, and by NOTHING
            ELSE any more: the poll used to repaint because typing into
            the box lit the open option's dot, and a word in the box is
            not a vote for anything now.
            """
            chosen = self._q_choice.get(ident)
            for band in bands:
                lit_up = band["index"] == chosen
                row.itemconfig(band["face"], image=band["faces"][
                    "on" if lit_up else "off"])
                row.itemconfig(band["photo"],
                               image=band["on"] if lit_up else band["off"])
                row.itemconfig(band["dot"],
                               fill=ui.ACCENT if lit_up else ui.CARD_HI,
                               outline=ui.ACCENT if lit_up else ui.STROKE)

        def arm() -> None:
            """The button lights when there is something to send, and the
            store's own rule decides that (see _answerable): a choice, or
            words, or both. Called on a press and on the poll, because
            either half can arrive first — and a dictated half arrives
            with no key event at all.
            """
            try:
                answer.enable(_answerable(self._q_choice.get(ident),
                                          self._q_typed.get(ident, "")))
            except Exception:             # noqa: BLE001 — the row went
                pass

        def pick(index: int) -> None:
            """Press a band to answer with it — and press the lit one
            again to take it back.

            IT DOES NOT SEND. The store takes an answer once and refuses
            a second one, so a mis-aimed click has to be something he can
            undo; he presses the button when he means it.

            AND IT DOES NOT TOUCH THE BOX. Whatever he has typed stays
            exactly where it is, caret and all, and goes to the store
            beside the pick — that is the whole shape of an answer here,
            and the card's `pick` says the same thing in the same words.
            """
            if not 0 <= index < len(options):
                return
            if self._q_choice.get(ident) == index:
                self._q_choice.pop(ident, None)
            else:
                self._q_choice[ident] = index
            paint()
            # The pointer is still ON the band he just un-picked — this
            # only ever arrives as a click, so it cannot be anywhere
            # else — and paint() knows nothing about the mouse. Without
            # this the band drops straight to flat under the cursor,
            # which reads as the row going dead rather than as the pick
            # coming off.
            if self._q_choice.get(ident) is None and index < len(bands):
                row.itemconfig(bands[index]["face"],
                               image=bands[index]["faces"]["over"])
            arm()

        def hover(index: int, over: bool):
            def handler(_event=None) -> None:
                band = bands[index]
                if self._q_choice.get(ident) != index:
                    row.itemconfig(band["face"], image=band["faces"][
                        "over" if over else "off"])
                row.config(cursor="hand2" if over else "")
            return handler

        for index, band in enumerate(bands):
            band["faces"] = {
                "on": ui.rounded(inner, band["h"], 10, ui.ACCENT_SOFT,
                                 ui.CARD, ui.ACCENT_EDGE),
                "off": ui.rounded(inner, band["h"], 10, ui.CARD_HI, ui.CARD,
                                  ui.LINE),
                "over": ui.rounded(inner, band["h"], 10, ui.CARD_HI, ui.CARD,
                                   ui.TILE_EDGE)}
            tag = f"opt{index}"
            band["face"] = row.create_image(Q_PAD, band["y"], anchor="nw",
                                            image=band["faces"]["off"],
                                            tags=tag)
            # THE DOT GOES WHERE THE LINE STARTS. ui.is_rtl decides that
            # the way the renderer will: a Hebrew option is read from the
            # right, so its dot is on the right and the words run back
            # towards the middle. A dot pinned to the left of a
            # right-aligned Hebrew line sits at the END of it, with the
            # gap between them reading as a missing word.
            rtl = ui.is_rtl(options[index])
            band["photo"] = row.create_image(
                Q_PAD + (Q_PAD if rtl else Q_MARK),
                band["y"] + (band["h"] - band["text_h"]) // 2, anchor="nw",
                image=band["off"], tags=tag)
            cx = Q_PAD + (inner - 15 if rtl else 15)
            cy = band["y"] + band["h"] // 2
            band["dot"] = row.create_oval(cx - 6, cy - 6, cx + 6, cy + 6,
                                          fill=ui.CARD_HI, outline=ui.STROKE,
                                          tags=tag)
            row.tag_bind(tag, "<Button-1>", lambda _e, i=index: pick(i))
            row.tag_bind(tag, "<Enter>", hover(index, True))
            row.tag_bind(tag, "<Leave>", hover(index, False))

        # THE CAPTION IS A LINE, NOT A CONTROL — no dot beside it and
        # nothing bound to it. The dot it used to carry said the box was
        # one of the choices and had to be chosen; the box is simply
        # there, so the caption's only job is to say that a sentence in it
        # may ADD to a band rather than replace one. It sits hard left
        # with the English frame, unindented, because it is this window
        # talking and not the routine.
        if caption is not None:
            row.create_image(Q_PAD, y_caption, anchor="nw", image=caption)

        # The well is a PICTURE and the widget sits inside it: a
        # hard-cornered box among rounded bands is half of the "very slop
        # and strict" he objected to on the report field, and this is
        # that field.
        well = row.create_image(Q_PAD, y_field, anchor="nw",
                                image=ui.rounded(inner, field_h,
                                                 FIELD_RADIUS, ui.EDGE,
                                                 ui.CARD, ui.STROKE))
        row.create_window(Q_PAD + Q_WELL_INSET, y_field + Q_WELL_INSET,
                          anchor="nw", window=field,
                          width=inner - 2 * Q_WELL_INSET,
                          height=field_h - 2 * Q_WELL_INSET)
        field.configure(cursor="xterm")
        typed = str(self._q_typed.get(ident, ""))
        if typed:
            field.insert("1.0", typed)
        field.tag_add("rtl", "1.0", "end")
        echo = row.create_image(Q_PAD, y_echo, anchor="nw")

        # The word on it is the CARD'S word (answer_card.SEND_LABEL), not
        # this file's: he answers the same question on whichever surface
        # is in front of him, and two buttons with two names for one act
        # is the first place a pair of surfaces starts feeling like two
        # features.
        answer = ui.Button(row, Q_SEND_LABEL,
                           lambda i=ident: self._answer_question(i),
                           w=104, h=30, primary=True, bg=ui.CARD,
                           icon=ui.ICON["check"])
        row.create_window(Q_PAD, y_actions, anchor="nw", window=answer)
        # THE UN-PICK CLAUSE IS ON THE LINE because the gesture is
        # otherwise invisible — pressing the lit band is the only way back
        # to no choice at all, and a row whose only undo is undocumented
        # is one he answers wrong once and then stops trusting. It is
        # named only when there is a band to press, the way
        # answer_card.keys_of names no digits on a question that arrived
        # with no options.
        #
        # TWO LINES, SPLIT WHERE THE CLAUSES SPLIT. Measured at 8 pt
        # beside the 104 px button: four of them do not fit across the
        # room that is left, and letting Tk wrap where the width runs out
        # put "dictation" alone on the second line, which reads as a
        # mistake rather than as a list.
        said = [c for c in ("press an answer again to un-pick" if bands
                            else "", "Enter sends") if c]
        row.create_text(Q_PAD + 116, y_actions + 15, anchor="w",
                        font=(ui.UI, 8), fill=ui.FAINT, justify="left",
                        text="  ·  ".join(said) + "\n"
                             "Shift+Enter for a new line  ·  "
                             "the box takes dictation")

        def send(_event=None) -> str:
            self._answer_question(ident)
            return "break"

        def newline(_event=None) -> str:
            """Enter sends, so the new line has to be the shifted one —
            the same split the report box made once its field was more
            than one line tall, and the line under the button says so."""
            field.insert("insert", "\n")
            return "break"

        def select_all(_event=None) -> str:
            """Ctrl+A, which a tk.Text does not do on its own — its own
            Ctrl+A is Tk's emacs inheritance, beginning-of-line."""
            field.tag_add("sel", "1.0", "end-1c")
            field.mark_set("insert", "end-1c")
            return "break"

        def lit(on: bool):
            """The edge follows the caret. Wired rather than painted,
            because the answer may arrive by dictation while he is
            looking at another window, and a field glowing as if it had
            the keys when it has not is the one lie that would cost him
            a sentence."""
            def handler(_event=None) -> None:
                if on:
                    self._q_focus = ident
                try:
                    row.itemconfig(well, image=ui.rounded(
                        inner, field_h, FIELD_RADIUS, ui.EDGE, ui.CARD,
                        ui.ACCENT if on else ui.STROKE))
                except Exception:         # noqa: BLE001 — the row went
                    pass
            return handler

        field.bind("<FocusIn>", lit(True))
        field.bind("<FocusOut>", lit(False))
        field.bind("<Return>", send)
        field.bind("<KP_Enter>", send)
        field.bind("<Shift-Return>", newline)
        field.bind("<Shift-KP_Enter>", newline)
        field.bind("<Control-a>", select_all)
        field.bind("<Control-A>", select_all)

        self._q_fields[ident] = {"field": field, "row": row, "echo": echo,
                                 "paint": paint, "arm": arm,
                                 "width": inner}
        paint()
        # The button's state is drawn from the same two halves the row was
        # drawn from, so a redraw that arrived while he had a pick or half
        # a sentence in hand does not come back with a dead button over a
        # live answer.
        arm()
        # The echo is drawn NOW as well as on the poll: after a redraw the
        # text is already in the field, so the poll sees no change and
        # would leave the band blank under a line he has typed.
        self._q_echo(self._q_fields[ident], typed)
        scroller.bind_wheel(row)

    def _q_echo(self, spec: dict, typed: str) -> None:
        """His line, drawn under the field by the renderer that gets it
        right.

        MANDATORY, NOT DECORATION. Measured on the report box with this
        exact widget: a tk.Text lays a mixed Hebrew/English line out with
        its runs in the wrong order — "הכפתור של Settings לא עובד" draws
        as something he never said — so the only place he can read back
        what the store is about to be given is this band.
        """
        row = spec["row"]
        stripped = " ".join(typed.split())
        try:
            if not stripped:
                row.itemconfig(spec["echo"], image="")
                row.echo_photo = None
                return
            photo, _h, _l = ui.draw_text(stripped, pt=10, width=spec["width"],
                                         max_lines=Q_ECHO_LINES,
                                         colour=ui.DIM, bg=ui.CARD)
            row.itemconfig(spec["echo"], image=photo)
            row.echo_photo = photo        # the canvas keeps no reference
        except Exception:                 # noqa: BLE001
            pass                          # the row went out from under it

    def _q_pump(self) -> None:
        """Read every answer field on a timer, not on a key.

        A DICTATED ANSWER ARRIVES WITH NO KEY EVENT. This window is a
        separate process, so injector.is_our_window does not refuse it
        and the paste lands in whichever field holds the caret — which is
        the whole reason he can answer here instead of in a chat. A key
        binding would see none of that, and neither would a write trace
        on a tk.Text; one poll catches typing, dictation, paste and undo
        alike, which is what the report card does with the same field for
        the same reason.
        """
        self._q_after = None
        if self.closing or "problems_list" not in self.parts:
            return                        # the screen went; so does the poll
        if not self._q_fields:
            return       # every question answered: _fill_problems will
                         # start this again when there is a field to read
        limit = int(getattr(self._questions(), "ANSWER_MAX", 600) or 600)
        for ident, spec in list(self._q_fields.items()):
            field = spec["field"]
            try:
                typed = field.get("1.0", "end-1c")
                if len(typed) > limit:
                    # The store would cut it silently on the way to disk;
                    # better he watches the field stop taking words than
                    # find the tail missing in an answer he cannot edit.
                    field.delete("1.0+%dc" % limit, "end")
                    typed = field.get("1.0", "end-1c")
                # Re-applied every pass: a tag does not extend itself over
                # text inserted after it, so a right-aligned field would
                # start going left again at the next dictated word.
                field.tag_add("rtl", "1.0", "end")
            except Exception:             # noqa: BLE001
                continue                  # that row has been destroyed
            if typed == str(self._q_typed.get(ident, "")):
                continue
            self._q_typed[ident] = typed
            # TYPING DOES NOT TOUCH THE PICK, and that is the whole change
            # from what stood here. The last option used to be the "open"
            # one, so a word in the box lit its dot and a cleared box put
            # it out — a widget voting on his behalf. Every band is a real
            # answer now: a line he types is either an answer of its own
            # or a condition on the band he pressed, and neither of those
            # is a vote for one of the bands. Nothing in the row moves
            # except the button, which arms on the first character and
            # disarms on the last backspace.
            try:
                spec["arm"]()
            except Exception:             # noqa: BLE001 — the row went
                pass
            self._q_echo(spec, typed)
        if not self.closing:
            self._q_after = self.root.after(Q_POLL_MS, self._q_pump)

    def _answer_question(self, ident: str) -> None:
        """Record HIS answer, then wake the routine.

        answer() is the only door into that store from this window and it
        hands back False rather than raising — no such question, a
        question that is no longer PENDING because the card in the other
        window answered it first, or a write that failed. All three mean
        the same thing here: the row he is looking at is stale, so it is
        redrawn rather than argued with. A decision he has already made is
        never overwritten by an older window, and the False is SAID —
        a store that refused an answer he thinks he gave must never be
        swallowed into a silent redraw.

        BOTH HALVES GO, ALWAYS. The choice and the box are read
        unconditionally and handed over together: `answer()` takes either
        or both and stores both, so an `if` in front of the text here
        would be the one bug that loses him a whole sentence without a
        trace — he presses "before the backup", writes "actually after
        it", and the second half never existed. Only both-empty is
        refused, which is why the button is dark until one of them has
        something in it.
        """
        store = self._questions_store()
        if store is None:
            self._note("questions.py is not here, so there is nothing to "
                       "answer")
            return
        text = str(self._q_typed.get(ident, ""))
        choice = self._q_choice.get(ident)
        # The button is already dark in this state, so this is the
        # keyboard's way in — Enter on an empty box with nothing pressed —
        # and it asks the same rule the button asked rather than spelling
        # the rule out a second time.
        if not _answerable(choice, text):
            self._note("press one of the answers, or say it in your own "
                       "words in the box")
            return
        try:
            saved = store.answer(ident, choice=choice, text=text,
                                 by="dashboard")
        except Exception as e:            # noqa: BLE001
            self._note(f"could not save that: {e}")
            return
        if not saved:
            self._note("that question is not waiting any more — it may have "
                       "been answered in the app while this was open")
            # AND HIS TWO HALVES ARE KEPT. The store refused this write,
            # so what he pressed and what he wrote are still the only copy
            # of them — clearing the row on the way to telling him it did
            # not save would be the refusal costing him the answer twice.
            # A question that really is answered elsewhere is not drawn by
            # the redraw below, so nothing is left on screen either way.
            self._fill_problems()
            return
        self._q_typed.pop(ident, None)
        self._q_choice.pop(ident, None)
        self._q_focus = None
        # THE ANSWER IS RECORDED BEFORE THE WAKE, and the wake cannot
        # unrecord it: the answer is the thing that matters, and a routine
        # that has to wait until Saturday to read it is a delay, not a
        # loss.
        woke = self._wake_review()
        self._note("answered — the review is starting now to build it"
                   if woke else
                   "answered — the review will pick it up on its next run")
        self._fill_problems()

    def _wake_review(self) -> bool:
        """The moment he answers, the routine goes and builds it.

        weekly_review.ps1 -Answered runs the review immediately, whatever
        the day's .done stamp says — that switch is the other half of
        this feature and it belongs to another file, so it is CHECKED FOR
        rather than assumed: a script without it is logged and skipped,
        and the answer still stands in the store for Saturday to find.

        AND NOT WITH launch's FLAGS, WHICH IS THE ONE SURPRISE HERE.
        launch.spawn cannot carry a .ps1 in the first place — it prepends
        pythonw.exe — so the flags were the only thing to borrow, and
        DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP DOES NOT WORK for
        this child. Measured under pythonw on 2026-09-05, four variants
        against a script whose only job was to write one file:

            detached | new group   -> exit 0, script never ran
            no window | new group  -> exit 0, script ran
            no window              -> exit 0, script ran
            no flags               -> exit 0, script ran

        powershell.exe is a CONSOLE binary, and with DETACHED_PROCESS it
        has no console to host itself in: it returns 0 and does nothing,
        which is the worst failure shape there is — it looks exactly like
        success. launch.py's own comment says why it does not carry
        CREATE_NO_WINDOW ("pythonw.exe is a GUI-subsystem binary and
        never gets a console to hide"), and that is precisely the
        difference: this child does. So it is CREATE_NO_WINDOW — the
        house flag for a console program under this window, the same one
        every git call above uses — plus CREATE_NEW_PROCESS_GROUP, so a
        Ctrl+C in a console-run dashboard is not delivered to the review.
        The child still outlives this window either way: a Windows
        process is not tied to its parent, and this one must not be —
        the dashboard is closed constantly.
        """
        import subprocess

        script = APP_DIR / "weekly_review.ps1"
        if not script.exists():
            _push_log("wake: no weekly_review.ps1 beside the app — the "
                      "answer is saved and Saturday will find it")
            return False
        try:
            source = script.read_text("utf-8-sig", errors="replace")
        except OSError as e:
            _push_log(f"wake: could not read weekly_review.ps1 ({e})")
            return False
        if not re.search(r"\$Answered", source, re.IGNORECASE):
            _push_log("wake: weekly_review.ps1 has no -Answered switch yet "
                      "— the answer is saved, and the next scheduled run "
                      "will read it")
            return False
        shell = Path(os.environ.get("SystemRoot", r"C:\Windows")) \
            / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        args = [str(shell) if shell.exists() else "powershell.exe",
                "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(script), "-Answered"]
        flags = _CREATE_NO_WINDOW | 0x00000200      # ...| NEW_PROCESS_GROUP
        try:
            subprocess.Popen(args, cwd=str(APP_DIR), creationflags=flags,
                             close_fds=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError as e:
            _push_log(f"wake: could not start the review ({e})")
            return False
        _push_log("wake: started weekly_review.ps1 -Answered")
        return True

    # ------------------------------------ what is here and not on GitHub

    def _scan_changes(self) -> None:
        """Ask git what is on this computer and not on GitHub, off the
        Tk thread.

        Three spawns, and a spawn is milliseconds this window may not
        spend: the Version screen froze solid asking git the same kind
        of question on the UI thread, which is the measurement in
        versions.py. The answer arrives through _events like every other
        off-thread reply. Asked when the tab opens and after each of the
        three buttons — never on the poll: five spawns a second for a
        list that changes when a session commits.
        """
        if self._changes_scanning:
            return
        self._changes_scanning = True

        def work() -> None:
            try:
                info = local_changes()
            except Exception:             # noqa: BLE001 — never a traceback
                info = {"commits": [], "files": [], "behind": 0,
                        "told": False}    #                out of a thread
            self._events.put(lambda i=info: self._changes_arrived(i))

        threading.Thread(target=work, daemon=True,
                         name="changes-scan").start()

    def _changes_arrived(self, info: dict) -> None:
        self._changes_scanning = False
        self._changes = info
        if self.screen == "Problems":
            self._fill_problems()

    def _changes_block(self, scroller: ui.Scroller, info: dict) -> None:
        """What is committed here and not on GitHub, above the reports.

        Above them because a change sitting here is work that is already
        DONE and waiting on him — and in a frame, for the reason the
        questions are in one.

        ONE CARD, OR ONE LINE. The card is drawn only while something is
        ahead of GitHub; the moment a push or an undo lands there is
        nothing to read, nothing to decide and no button worth his
        screen, so the block collapses to a faint line saying so. His
        words on 2026-09-08, after a second finished week stacked under
        the first: "if it stays here after five weeks, there will be a
        lot and it is not convenient". The line keeps Restart, quietly,
        because "nothing ahead" is also what the folder looks like after
        Claude has brought GitHub's newer changes in — and those want a
        restart to be run. The last button's sentence stays under the
        line for the same reason: "Undone… Restart to run the older
        version again" is an instruction, and it must not vanish with
        the card it was about.
        """
        block = tk.Frame(scroller.inner, bg=ui.BG)
        block.pack(anchor="w", fill="x", pady=(0, 2))
        if info.get("commits"):
            tk.Label(block, text="CHANGES ON THIS COMPUTER — TRY THEM, "
                                 "THEN PUSH",
                     bg=ui.BG, fg=ui.FAINT, font=(ui.MEDIUM, 8)).pack(
                anchor="w", pady=(0, 6))
            self._changes_row(block, scroller, info)
            return
        behind = int(info.get("behind") or 0)
        said = "Everything on this computer is on GitHub."
        if behind:
            said += (f" GitHub also has {behind} newer change"
                     f"{'' if behind == 1 else 's'} this computer does not "
                     f"have yet.")
        note = str(self._push_said.get(TRUNK, ""))
        note_img, note_h = None, 0
        if note:
            note_img, note_h, _l = ui.draw_text(note, pt=8,
                                                width=CW - 2 * Q_PAD,
                                                max_lines=3, colour=ui.AMBER,
                                                bg=ui.BG)
        height = FOLD_H + (note_h + 4 if note_img is not None else 0)
        line = tk.Canvas(block, width=CW, height=height, bg=ui.BG,
                         highlightthickness=0, bd=0)
        line.pack(anchor="w", pady=(0, 8))
        line.keep = [note_img]
        line.create_text(Q_PAD, FOLD_H / 2, text=said, anchor="w",
                         fill=ui.FAINT, font=(ui.UI, 9))
        if note_img is not None:
            line.create_image(Q_PAD, FOLD_H + 2, anchor="nw", image=note_img)
        again = ui.Button(line, "Restart", self._restart_all,
                          w=self._changes_button_w(), h=30, quiet=True,
                          bg=ui.BG, icon=ui.ICON["power"])
        line.create_window(CW - Q_PAD, FOLD_H / 2, anchor="e", window=again)
        if self._pushing is not None:
            again.enable(False)
        scroller.bind_wheel(line)

    @staticmethod
    def _changes_button_w() -> int:
        """One width for the three buttons, so they read as a set. 96 is
        what the old card's Push had; wider only if Rubik needs it for
        "Restart", which is the longest of the three words."""
        return max(96, *(widgets.button_width(word, icon=True)
                         for word in ("Restart", "Push", "Undo")))

    def _changes_row(self, parent, scroller: ui.Scroller,
                     info: dict) -> None:
        """One card, and everything he needs to decide before he presses:
        how many changes, what each one said and when, which files, and
        what the last press did.

        A button that pushes an unknown quantity is not reviewable,
        which is why the commits and the file list are on the card and
        not in a log. Three buttons in a row at the top right — the
        card's height comes from the list under them, so a column would
        have cost a tall card for one commit — with Undo set apart from
        Push by a wider gap: they are neighbours that do opposite things
        and neither asks "are you sure".
        """
        commits = list(info.get("commits") or [])
        files = [str(f) for f in (info.get("files") or [])]
        behind = int(info.get("behind") or 0)
        inner = CW - 2 * Q_PAD
        wide = self._changes_button_w()
        buttons = 3 * wide + 8 + 18
        room = inner - buttons - 12
        # One plain sentence about where the work is, in the words he
        # asked for on 2026-09-06: not "4 commits · 3 files · not on
        # GitHub yet", but what that means and what to do about it.
        n = len(commits)
        them = "it" if n == 1 else "them"
        status = (f"{n} change{'' if n == 1 else 's'} exist"
                  f"{'s' if n == 1 else ''} only on this computer. Restart "
                  f"to try {them}, then Push to send {them} to GitHub — or "
                  f"Undo to throw {them} away.")
        if behind:
            status += (f" GitHub also has {behind} newer change"
                       f"{'' if behind == 1 else 's'} this computer does "
                       f"not have yet.")
        status, status_lines = ui.clamp(status, ui.UI, 8, room, 3)
        # The commits, one per line, newest first: the date in the faint
        # face and the subject in the dim one, each subject cut to its
        # line — a subject is a sentence in this repo, and two of them
        # wrapping would push the file list off the card.
        lines: list[tuple[str, str]] = []
        for commit in commits[:CHANGES_SHOWN]:
            when = str(commit.get("when", ""))
            subject, _n = ui.clamp(str(commit.get("subject", "")), ui.UI, 9,
                                   inner - 110, 1)
            lines.append((when, subject))
        if n > CHANGES_SHOWN:
            lines.append(("", f"+{n - CHANGES_SHOWN} more"))
        listed, name_lines = "", 0
        if files:
            shown = "   ·   ".join(files[:8])
            if len(files) > 8:
                shown += f"   ·   +{len(files) - 8} more"
            listed, name_lines = ui.clamp(shown, ui.UI, 8, inner, 2)
        said = str(self._push_said.get(TRUNK, ""))
        note, note_h = None, 0
        if said:
            note, note_h, _l = ui.draw_text(said, pt=8, width=inner,
                                            max_lines=3, colour=ui.AMBER,
                                            bg=ui.CARD)
        # 31 is where the status starts, under a 10 pt title at 13; each
        # 8 pt line is 14 px and each 9 pt commit line 16.
        y = 31 + status_lines * 14 + 8
        y_commits = y
        y += len(lines) * 16 + (6 if lines else 0)
        y_files = y
        y += name_lines * 14 + (6 if name_lines else 0)
        y_note = y
        y += note_h + (6 if note is not None else 0)
        height = max(74, y + 8)

        row = tk.Canvas(parent, width=CW, height=height, bg=ui.BG,
                        highlightthickness=0, bd=0)
        row.pack(anchor="w", pady=(0, 8))
        row.create_image(0, 0, anchor="nw", image=ui.rounded(
            CW, height, 12, ui.CARD, ui.BG, ui.TILE_EDGE))
        row.keep = [note]
        row.create_text(Q_PAD, 13, anchor="nw", font=(ui.MEDIUM, 10),
                        fill=ui.FG, text="Changes on this computer")
        row.create_text(Q_PAD, 31, anchor="nw", font=(ui.UI, 8),
                        fill=ui.FAINT, justify="left", text=status)
        for index, (when, subject) in enumerate(lines):
            top = y_commits + index * 16
            if when:
                row.create_text(Q_PAD, top, anchor="nw", font=(ui.UI, 8),
                                fill=ui.FAINT, text=when)
            row.create_text(Q_PAD + (110 if when else 0), top, anchor="nw",
                            font=(ui.UI, 9), fill=ui.DIM, text=subject)
        if name_lines:
            row.create_text(Q_PAD, y_files, anchor="nw", font=(ui.UI, 8),
                            fill=ui.FAINT, justify="left", text=listed)
        if note is not None:
            row.create_image(Q_PAD, y_note, anchor="nw", image=note)
        # Right to left, so the primary one lands where the old Push did
        # and Undo is the outermost thing on the card.
        undo = ui.Button(row, "Undo", self._undo_main, w=wide, h=30,
                         quiet=True, bg=ui.CARD, icon=ui.ICON["discarded"])
        row.create_window(CW - Q_PAD, 13, anchor="ne", window=undo)
        push = ui.Button(row, "Push", self._push_main, w=wide, h=30,
                         primary=True, bg=ui.CARD, icon=ui.ICON["link"])
        row.create_window(CW - Q_PAD - wide - 18, 13, anchor="ne",
                          window=push)
        again = ui.Button(row, "Restart", self._restart_all, w=wide, h=30,
                          quiet=True, bg=ui.CARD, icon=ui.ICON["power"])
        row.create_window(CW - Q_PAD - 2 * wide - 18 - 8, 13, anchor="ne",
                          window=again)
        if self._pushing is not None:
            # One thing at a time: a second press would be racing the
            # first for the same branch, and Restart is about to take the
            # window away from under all three.
            for button in (undo, push, again):
                button.enable(False)
        scroller.bind_wheel(row)

    def _run_git_button(self, doing: str, saying: str, work) -> None:
        """Push and Undo share one shape: mark the button in flight, say
        so on the card, run the git steps off the Tk thread, and hand
        the sentence back through _events. A push is his connection and
        a fetch is somebody's server — tens of seconds in the worst
        case, none of it allowed near the event loop, exactly like the
        version switch."""
        if self._pushing is not None:
            return
        self._pushing = doing
        self._push_said[TRUNK] = saying
        self._note(f"{doing}…")

        def run() -> None:
            try:
                result = work()
            except Exception as e:        # noqa: BLE001 — a failure is a
                result = {"said": f"{doing.capitalize()} failed before it "
                                  f"started ({e}). Nothing changed."}
            self._events.put(lambda r=result: self._git_done(r))

        threading.Thread(target=run, daemon=True,
                         name=f"changes-{doing}").start()
        self._fill_problems()             # the card says it is going

    def _push_main(self) -> None:
        """His Push. What it does and why it may refuse is in push_main."""
        self._run_git_button("push", "Pushing… sending the changes to "
                                     "GitHub.", push_main)

    def _undo_main(self) -> None:
        """His Undo. What it does and why it may refuse is in undo_main."""
        self._run_git_button("undo", "Undoing… putting this computer back "
                                     "to what GitHub has.", undo_main)

    def _git_done(self, result: dict) -> None:
        self._pushing = None
        self._push_said[TRUNK] = str(result.get("said") or "")
        self._note(self._push_said[TRUNK])
        # The facts moved — GitHub has the commits now, or this folder
        # no longer does — so they are asked for again rather than
        # patched.
        self._scan_changes()
        if self.screen == "Problems":
            self._fill_problems()

    def _restart_all(self) -> None:
        """His Restart: the app, then this window, so that both run what
        is on the disk now — the changes he is about to try, or the
        older version after an Undo.

        The app half is restart_app, off the Tk thread because it waits.
        The window half cannot be done from inside the window: main()
        holds the single-instance mutex until run() returns, and a fresh
        copy started before that would meet the mutex, poke this window
        to the front and exit — leaving no dashboard at all once this
        one closed. So the window only ASKS (self._relaunch) and closes
        itself; main() releases the mutex and then opens the new copy.
        A restart that failed keeps the window and says why on the card,
        because a new window would not know the sentence.
        """
        if self._pushing is not None:
            return
        self._pushing = "restart"
        self._push_said[TRUNK] = ("Restarting — the app takes about 25 "
                                  "seconds to load.")
        self._note("restarting — the app takes about 25 seconds to load")

        def work() -> None:
            try:
                result = restart_app()
            except Exception as e:        # noqa: BLE001 — a failure is a
                result = {"ok": False,    #                sentence
                          "said": f"Restart failed before it started "
                                  f"({e}). Nothing changed."}
            self._events.put(lambda r=result: self._restart_done(r))

        threading.Thread(target=work, daemon=True,
                         name="changes-restart").start()
        self._fill_problems()             # the card says it is going

    def _restart_done(self, result: dict) -> None:
        self._pushing = None
        if result.get("ok"):
            self._relaunch = True
            self._close()
            return
        self._push_said[TRUNK] = str(result.get("said") or "")
        self._note(self._push_said[TRUNK])
        if self.screen == "Problems":
            self._fill_problems()

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
            pcfg = getattr(config_mod.load_layered(), "problems", None)
        except Exception:                 # noqa: BLE001 — a picture is a bonus
            pcfg = None
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
        tk.Label(body, text=REPORT_KEYS, bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8), justify="left",
                 wraplength=inner).place(x=0, y=y_keys)
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
                self._file_report(module, where, picked["kind"], text, jpeg)

        send_button = ui.Button(actions, "Send",
                                lambda: finish(field.get("1.0", "end-1c")),
                                w=104, primary=True, icon=ui.ICON["error"])
        send_button.pack(side="left", padx=(0, 8))
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
        controls = {field, well, send_button, cancel_button}
        controls.update(chips.values())
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
                     jpeg: bytes | None = None) -> None:
        """Hand the line to problems.record, which collects the rest.

        clean()'s ValueError is the one exception that module raises on
        purpose — an empty line — and it is a sentence to say back, not
        something to log. Everything else in there is already swallowed,
        so filing a report can cost him the report and never the window.
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
        self._note(f"filed as {item.get('id', '')} — it is on the Problems "
                   f"screen until you answer it")
        self._write_digest()
        if self.screen == "Problems":
            self._fill_problems()

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
    # "Send a test" moved to Settings > The app, next to the cue sounds
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
        """Every line of config.toml, drawn from the file itself, on
        tabs a person can find things on.

        Nothing here is typed by hand except the words: settings.py reads
        the file, settings.TABS says which lines get a plain label, a
        short sentence and a menu with names on it, and TAB_SECTIONS
        says which tab draws the rest of each section — with the plain
        words of settings.WORDS as title and help, never the file's own
        names. General is the dozen things he actually changes; The app
        holds the blocks that used to be screens. A test holds the tabs
        and the Keys screen to drawing every line of the file exactly
        once, so a setting cannot drop off and cannot be said twice.
        That is the owner's rule from both directions: "show all of
        them" (2026-09-01), then "normal settings, no need to be clever
        — if there is Everything, it is already somewhere else"
        (2026-09-07).

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
        names = settings_mod.tab_names(p["sections"], _keys_screen_paths())
        for name in names:
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
        Common is already flipped where the same line is drawn again."""
        self._settings_tab = name
        for tab_name, chip in (self.parts.get("settings_tabs") or {}).items():
            chip.set(tab_name == name)
        self._fill_settings()

    def _settings_open_search(self) -> None:
        self._settings_searching = True
        self._settings_query = ""
        self._settings_bar()
        self._fill_settings()

    def _settings_close_search(self) -> None:
        self._settings_searching = False
        self._settings_query = ""
        self._settings_bar()
        self._fill_settings()

    def _fill_settings(self) -> None:
        """The cards for the tab that is up — or, while searching, every
        line of the file that matches, section by section.

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
        elsewhere = _keys_screen_paths()
        builders: list = []
        if self._settings_searching:
            query = self._settings_query
            for section in sections:
                rows = [s for s in section.settings
                        if s.path not in elsewhere
                        and settings_mod.matches(s, query)]
                if not rows:
                    continue
                title = settings_mod.section_words(
                    section.name, section.help).label.upper()
                pairs = [(settings_mod.words_for(s), s) for s in rows]
                # A SEARCH NEVER FOLDS. What it found is the answer to
                # a question that was typed; half of it behind a line
                # saying "7 more in this section" is not an answer.
                builders.append(lambda t=title, pr=pairs:
                                self._friendly_card(scroller, t, pr,
                                                    fold=False))
        else:
            name = self._settings_tab
            # The blocks that used to be screens sit above the rows of
            # the tab they belong to: the phone's link on Phone; awake,
            # the version, the sounds and the files on The app.
            if name == settings_mod.APP:
                builders.append(lambda: self._awake_block(scroller))
                builders.append(lambda: self._app_block(scroller))
                builders.append(lambda: self._files_card(scroller))
            elif name == "Phone":
                builders.append(lambda: self._phone_block(scroller))
            elif name == settings_mod.GENERAL:
                # FIRST ON GENERAL, because that is where he went looking
                # for it: "I'm going to General and then 'which corner the
                # dot sits' — there is only bottom right or top right. So
                # please solve the problem that I cannot move the dot"
                # (2026-09-08). The corner menu and the button are one
                # card now, side by side, and Cards has no dot on it at
                # all — see settings.TAB_SECTIONS.
                builders.append(lambda: self._dot_block(scroller))
            for group in settings_mod.groups_for(name, sections, elsewhere):
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

    # What a block ABOVE the rows already draws for itself, per tab, so
    # the rows below it do not draw it a second time. The one rule of
    # this screen is that every line of config.toml is reachable exactly
    # once, and a block is another way of drawing a line, not an
    # exception to it: `dot.corner` is a real settings row with a real
    # menu, registered in parts["rows"] like any other — it is simply
    # drawn beside the button that goes with it instead of ten rows above
    # it. `_keys_screen_paths` is the same idea for another SCREEN.
    BLOCK_PATHS: dict[str, frozenset] = {
        settings_mod.GENERAL: frozenset({"dot.corner"}),
    }

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
                       fold: bool = True, open_: bool = False,
                       before=None) -> None:
        """One section's card: the lines worth a first look, and — under
        them, on one quiet line — how many more the section has.

        The split is settings.fold, and the rule it uses is settings.
        common: a line a tab names by hand, a switch or a menu is on the
        face; a number, a length of time, a model name or a folder waits
        behind the line. NOTHING IS DROPPED — the owner's two rules are
        "show all of them" (2026-09-01) and "I do not need to know all of
        this" (2026-09-07), and a fold is the only thing that is both. A
        test holds every line of config.toml to being reachable exactly
        once, folded or not.
        """
        shown, rest = (settings_mod.fold(pairs) if fold
                       else (list(pairs), []))
        drawn = shown + rest if open_ else shown
        heights = [22 + self._friendly_help(row)[1] * 15 + 8
                   for row, _setting in drawn]
        y = 18 if title else 8
        card = self._new_card(scroller, y + 18 * bool(title) + sum(heights)
                              + (FOLD_H if rest else 0)
                              + (6 if title else 10), before=before)
        if title:
            card.create_text(18, y, text=title, anchor="nw", fill=ui.FAINT,
                             font=(ui.UI, 8))
            y += 18
        for (row, setting), height in zip(drawn, heights):
            card.create_text(18, y, text=row.label, anchor="nw", fill=ui.FG,
                             font=(ui.UI, 10))
            text, lines = self._friendly_help(row)
            if lines:
                card.create_text(18, y + 21, text=text, anchor="nw",
                                 fill=ui.FAINT, font=(ui.UI, 8))
            self._control(card, y, setting, self._menu_for(row, setting))
            y += height
        if rest:
            self._fold_line(scroller, card, title, pairs, y, len(rest),
                            open_)
        scroller.bind_wheel(card)

    def _fold_line(self, scroller, card, title: str, pairs, y: int,
                   hidden: int, open_: bool) -> None:
        """The quiet line at the foot of a folded card.

        The rectangle under the words is what makes it a ROW to click on
        rather than a run of glyphs: a canvas text item is only hit where
        its ink is, and "7 more in this section" is 130 px of target in a
        1112 px card. It is painted in the card's own colour, so it is a
        hit area and nothing else.
        """
        card.create_rectangle(12, y - 3, CW - 12, y + FOLD_H - 7,
                              fill=ui.CARD, outline="", tags="fold")
        said = "Fewer" if open_ else f"{hidden} more in this section"
        card.create_text(18, y + 2, text=said, anchor="nw",
                         fill=ui.ACCENT_TEXT, font=(ui.UI, 9), tags="fold")
        # The caret is drawn at PT_LABEL, not at the size of the words
        # beside it: the ▾ Rubik gives back at 8 pt is three pixels of ink
        # and reads as a full stop (photographed on the hidden desktop,
        # 2026-09-07). It is the same glyph ui.Dropdown wears.
        card.create_text(21 + ui.text_width(said, ui.UI, 9), y + 1,
                         text="▴" if open_ else "▾", anchor="nw",
                         fill=ui.ACCENT_TEXT, font=(ui.UI, ui.PT_LABEL),
                         tags="fold")
        card.tag_bind("fold", "<Button-1>", lambda _e:
                      self._settings_fold(scroller, card, title, pairs,
                                          not open_))
        card.tag_bind("fold", "<Enter>",
                      lambda _e: card.configure(cursor="hand2"))
        card.tag_bind("fold", "<Leave>",
                      lambda _e: card.configure(cursor=""))
        # What _settings_unfold_first looks for. Only a CLOSED fold
        # carries it, so "is anything still folded" is one attribute.
        if not open_:
            card.folded_rows = lambda: self._settings_fold(
                scroller, card, title, pairs, True)

    def _settings_fold(self, scroller, card, title: str, pairs,
                       open_: bool) -> None:
        """Open, or close, one card's fold — in place.

        A card is a Canvas of a fixed height with its rows already drawn
        on it (see _new_card for why it is not widgets), so there is no
        growing it: it is drawn again at the new height and packed where
        the old one was. The rows it registered are dropped first, or the
        same path would sit in parts["rows"] twice and every repaint
        would paint it twice — which the "exactly once" test would see.
        """
        if scroller is None or not scroller.winfo_exists():
            return
        kids = list(scroller.inner.pack_slaves())
        try:
            after = kids[kids.index(card) + 1]
        except (ValueError, IndexError):
            after = None
        for _row, setting in pairs:
            self.parts.get("rows", {}).pop(setting.path, None)
        card.destroy()
        self._friendly_card(scroller, title, pairs, open_=open_,
                            before=after)

    def _settings_unfold_first(self) -> bool:
        """Open the first card on this tab that still has a fold. True if
        there was one."""
        scroller = self.parts.get("settings_list")
        if scroller is None or not scroller.winfo_exists():
            return False
        for card in scroller.inner.pack_slaves():
            opener = getattr(card, "folded_rows", None)
            if opener is not None:
                opener()
                return True
        return False

    def _settings_unfold_all(self) -> int:
        """Open every fold on the tab that is up; how many were opened.
        What the "reachable exactly once" test walks the screen with."""
        opened = 0
        while self._settings_unfold_first():
            opened += 1
            if opened > 500:              # a fold that will not open
                break
        return opened

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
        if row is not None and row.names:
            return list(row.names)
        return [(c, c) for c in setting.choices]

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
            field = ui.Field(card, _shown(value), w=ENTRY_W, h=ENTRY_H,
                             bg=ui.CARD)
            card.create_window(right, y - 1, window=field, anchor="ne")
            field.bind_entry("<Return>", lambda _e, s=setting, f=field:
                             self._entry_done(s, f))
            field.bind_entry("<FocusOut>", lambda _e, s=setting, f=field:
                             self._entry_done(s, f))
            self._register_row(setting, "entry", field)

    def _register_row(self, setting, kind: str, widget) -> None:
        self.parts["rows"].setdefault(setting.path, []).append((kind, widget))

    def _draw_consent_row(self, card, setting, right: int, y: int) -> None:
        """One of the six [privacy] gates: what the consent file says —
        open since when, for which words, stale, or never granted — and
        a Withdraw button while it is open. No switch: it opens only
        through its card, the first time a feature needs it (D7)."""
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
            text, colour = "Its card changed — it will ask again", ui.FAINT
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
        # The text is the row's one control — registered so the page
        # counts it like any other line (one widget per line, a test
        # holds), and so a repaint can find it.
        item = card.create_text(x, y + 13, text=text, anchor="e",
                                font=(ui.UI, 10), fill=colour)
        self._register_row(setting, "consent", (card, item))

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

    def _files_card(self, scroller) -> None:
        # Named for what they ARE, not what they are called on disk — the
        # filename is the small print. "What is transcripts.log" was a
        # question this screen used to make the owner ask.
        openers = (
            ("file", "Everything you said",
             "transcripts.log — every dictation, translation and lookup",
             paths.TRANSCRIPTS_LOG),
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
            body, text=url or "not running, or [server] enabled = false",
            bg=ui.CARD, fg=ui.FG if url else ui.DIM,
            font=(ui.UI, 12 if url else 10))
        self.parts["phone_url"].place(x=0, y=24)
        tk.Label(body, bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8),
                 wraplength=CW - 200, justify="left",
                 text="Open it on the phone over Tailscale and the keyboard "
                      "there dictates into this machine. The same address "
                      "takes a POST to /notify, which is how a finish "
                      "becomes a card on this desk."
                 ).place(x=0, y=54)
        ui.Button(body, "Copy link", self._copy_phone, h=32, quiet=True,
                  w=widgets.button_width("Copy link", icon=True),
                  icon=ui.ICON["link"]).place(x=CW - 36, y=20, anchor="ne")
        scroller.bind_wheel(card)

    def _app_block(self, scroller) -> None:
        """The app itself: which version is running, how to stop it, and
        the twenty sounds it makes.

        THE SOUNDS ARE HERE BECAUSE HE COULD NOT TELL THEM APART. That is
        a filed complaint, and the answer to it is not a louder cue, it
        is a Play button next to the name of the thing the cue is FOR.
        """
        try:
            import cues as cues_mod
        except Exception:                 # noqa: BLE001 — no cues here
            cues_mod = None
        kinds = list(getattr(cues_mod, "CUES", {})) if cues_mod else []
        sound_rows = (len(kinds) + SOUND_COLUMNS - 1) // SOUND_COLUMNS
        height = 150 + (30 + sound_rows * 30 if kinds else 0)
        card = ui.Card(scroller.inner, CW, height, bg=ui.BG, pad=18)
        card.pack(anchor="w", pady=(0, 14))
        body = card.body
        tk.Label(body, text="T H E   A P P", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.MEDIUM, 8)).place(x=0, y=0)

        # ONE VERSION, AND NOTHING HERE THAT CHANGES IT. There were two -
        # classic and fast - and a row of "Switch to ..." buttons sat on
        # this card to flip between them. He closed it on 2026-09-08: "I
        # want only to be on this version that is already running." By
        # then the second version had stopped existing on this machine
        # anyway, so the only trip the button still offered was one
        # backwards, into code older than what he was looking at. What is
        # left is the plain fact of which code is running, because that is
        # the line he needs when he files a report against it.
        tk.Label(body, text="DeskIT", bg=ui.CARD,
                 fg=getattr(ui, "ACCENT_TEXT", ui.ACCENT),
                 font=(ui.DISPLAY, 17, "bold")).place(x=0, y=20)
        tk.Label(body, text=f"branch '{self.branch}' - running now",
                 bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=0, y=50)

        # THE SAME DOOR AS THE BAR'S STOP, in one press, and it is here
        # as well because this is where the 25 seconds are written down —
        # the line under it says what stopping costs before anybody finds
        # out. Stop lived only here for one evening, until he said "I
        # don't have a button to shut down the model, I only have a
        # button to pause it".
        stop = ui.Button(body, "Stop the app", self._stop, h=32,
                         w=widgets.button_width("Stop the app", icon=True),
                         quiet=True, icon=ui.ICON["stop"])
        stop.place(x=CW - 36, y=20, anchor="ne")
        self.parts["stop"] = stop
        ui.Button(body, "Send a test notification",
                  lambda: self._notify("test"), h=32, quiet=True,
                  w=widgets.button_width("Send a test notification",
                                         icon=True),
                  icon=ui.ICON["notify"]).place(x=CW - 36, y=60, anchor="ne")
        tk.Label(body, text="stopping unloads the models; starting again "
                            "takes about 25 seconds",
                 bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8)).place(
            x=CW - 36, y=100, anchor="ne")

        if kinds:
            widgets.rule(body, CW - 36, bg=ui.CARD, colour=ui.LINE, x=0,
                         y=140)
            tk.Label(body, text="S O U N D S", bg=ui.CARD, fg=ui.FAINT,
                     font=(ui.MEDIUM, 8)).place(x=0, y=152)
            column = (CW - 36) // SOUND_COLUMNS
            for index, kind in enumerate(kinds):
                cx = (index % SOUND_COLUMNS) * column
                cy = 176 + (index // SOUND_COLUMNS) * 30
                ui.Button(body, "▶", lambda k=kind: self._play_cue(k),
                          w=30, h=24, quiet=True, bg=ui.CARD).place(x=cx,
                                                                    y=cy)
                tk.Label(body, text=kind, bg=ui.CARD, fg=ui.DIM,
                         font=(ui.UI, 9)).place(x=cx + 38, y=cy + 4)
        scroller.bind_wheel(card)

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
            self._note(f"{setting.path}: {raw.strip()!r} is not "
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
        self.parts["values"][setting.path] = value
        self._paint_setting(setting.path, value)
        self._note(f"{setting.path} saved — it applies the next time it "
                   "starts")

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
        self._note(reply.get("message") or f"{setting.path} saved")

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

    # ------------------------------------------------------------- version

    def _warm_branch(self) -> None:
        """Find out which branch this is, off the Tk thread.

        versions.py spawns git, and git under pythonw allocates a console
        per spawn unless suppressed — hundreds of ms each, fatal on the UI
        thread (it froze the Version screen solid). Both facts are handled
        inside versions.py now; this thread's job is only to pay even that
        smaller cost while the window is still opening, not when a tab is
        clicked. The answer lands back on the Tk thread through _events,
        like every other off-thread result.
        """
        try:
            import versions as versions_mod
            here = versions_mod.current_branch()
        except Exception:
            return
        self._events.put(lambda: setattr(self, "branch", here))

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
        self._note("starting — the models take about 25 seconds to load")
        self._busy_until = time.monotonic() + 2
        if "hero_state" in self.parts:
            self.parts["hero_state"].config(text="STARTING")
        if not launch.start_app():
            self._note("could not launch main.py — see app.log")

    def _stop(self) -> None:
        """Quitting, in ONE press — the bar's Stop and Settings › The
        app's Stop are the same door.

        It used to take two from the bar: the first press turned the word
        into "Stop again" and only the second one quit. That guarded a
        real cost — the models unload and coming back takes about 25
        seconds — but he read the word, could not tell what it was for,
        and said so twice, so what guards the cost now is where the
        button sits rather than how many times it has to be hit. See
        _paint_bar_buttons.
        """
        self._busy_until = time.monotonic() + 1.5
        # The named event, not the pipe: this has to work even if the
        # control channel never came up.
        if singleton.request_quit():
            self._note("stopping — models unload, so starting again takes "
                       "about 25 seconds")
        else:
            self._note("nothing to stop")

    def _nightly_running(self) -> bool:
        """Is the nightly test suite going right now?

        A file on disk and not the control channel, because the run is
        not the app's: a scheduled task starts it so that a crashed
        DeskIT is still a tested DeskIT, and this window has to be able
        to see a run that DeskIT knows nothing about. nightly.running
        asks two things — the marker exists AND somebody still holds the
        lock — so a run that was killed leaves no button behind.

        It never raises. A missing folder, a missing module, a disk that
        will not answer: all of those mean "no run", which is the same
        bar he has had all along.
        """
        if not paths.DEVELOPER:
            return False                  # the nightly run is the owner's
        try:
            return bool(_nightly().running(APP_DIR))
        except Exception:                 # noqa: BLE001
            return False

    def _stop_tests(self) -> None:
        """End the nightly run. One press, and no arming — there is
        nothing to be sorry about: a stopped run is written down as
        stopped and files nothing, and the next night runs as usual.

        The button stays where it is and says "Stopping…" until the run
        actually lets go, because the suite may be inside a test that
        takes a second to come out of, and a button that vanished on the
        press would leave him wondering whether it took."""
        button = self.parts.get("tests_stop")
        if _nightly().ask_stop(APP_DIR):
            if button is not None and button.winfo_exists():
                button.configure_text("Stopping…")
            self._note("stopping the nightly test run — it is recorded as "
                       "stopped, not as a failure")
        else:
            self._note("could not ask the test run to stop")

    def _toggle_pause(self) -> None:
        """The button that is in the bar in every state. Start when
        nothing is running, Resume when it is paused, Pause when it is
        listening — three words on one key, because they are never
        available at the same time and three buttons would be two lies."""
        if not self.status:
            self._start()
            return
        self._busy_until = time.monotonic() + 1
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
            self._ask("rebind", then=lambda r: self._announce(r, "saved"),
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
            self._note(f"{field} is now '{key}'" if key
                       else f"{field} is off")
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
        activity = ("ready" if deaf else
                    "starting" if starting else
                    "stopped" if not status else
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

        # Is a nightly test run going? Asked here, once a poll, and NOT
        # inside the painter: the painter is also called from a screen
        # swap and from the breathing loop, and a question that touches
        # the disk belongs on the poll that already does.
        self._tests_running = self._nightly_running()
        # Which buttons the bar holds and what each of them says are ONE
        # decision — the word on the run key is the only thing that tells
        # Start's state from Pause's — so both live in one method.
        self._paint_bar_buttons()
        {"Home": self._poll_waiting,
         "Corrections": self._poll_corrections,
         "Problems": self._poll_problems,
         "Said": lambda: None,
         "Keys": self._paint_keys,
         "Settings": self._paint_settings}[self.screen]()

    # ------------------------------------------------------------ shutdown

    def _close(self) -> None:
        # Closing this window must never stop dictation — it is a remote
        # control, not the app. It must not leave it PAUSED either, which
        # is what closing it on top of an open key dialog used to do.
        self.closing = True
        self._resume_after_capture()
        if self.screen == "Corrections" and self._corr_tab == "read":
            self._read_leave()
        for pending in (self._pump_after, self._toast_after,
                        self._search_after, self._rows_after,
                        self._slide_after, self._breath_after,
                        self._q_after):
            try:
                if pending is not None:
                    self.root.after_cancel(pending)
            except Exception:
                pass
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
        again = Dashboard().run()
    finally:
        lock.release()
    if again:
        _relaunch_dashboard()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
