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

The look — rounded cards, the sidebar, the switches — is all in ui.py; the
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
import launch
import awake as awake_mod
import settings as settings_mod
import singleton
import ui

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.toml"
ICON_PATH = APP_DIR / "icon.ico"
ICON_PNG = APP_DIR / "icon.png"

# Any string, as long as it is OURS and stays put. Windows groups taskbar
# buttons and picks their icon by this; without one the window inherits
# pythonw.exe's identity, which is why the taskbar showed a generic file
# icon rather than the app's.
APP_ID = "Yoav.HebrewDictation.Dashboard"

W, H = 940, 648          # fixed, which is what lets every bitmap be cached
SIDE = 212               # the sidebar
PAD = 24
CW = W - SIDE - PAD * 2  # 680 — the usable width of a screen

# activity -> (dot colour, the word for it)
LOOKS = {
    "stopped":   (ui.FAINT, "STOPPED"),
    "starting":  (ui.AMBER, "STARTING"),
    "ready":     (ui.ACCENT, "RUNNING"),
    "recording": (ui.RED, "RECORDING"),
    "locked":    (ui.RED, "LOCKED ON"),
    "busy":      (ui.AMBER, "TRANSCRIBING"),
    "paused":    (ui.DIM, "PAUSED"),
}

POLL_MS = 800
HISTORY_ROWS = 100       # what "the last hundred" means, in one place
SEARCH_MS = 160          # how long typing has to stop before the list moves

# history.KINDS names a colour; ui.py owns what the colour is.
COLOURS = {"accent": ui.ACCENT, "teal": ui.TEAL, "violet": ui.VIOLET,
           "green": ui.GREEN, "amber": ui.AMBER, "red": ui.RED,
           "faint": ui.FAINT}

NAV = (("overview", "Overview"), ("history", "History"),
       ("review", "Review"), ("awake", "Awake"), ("notify", "Notify"),
       ("keys", "Keys"), ("version", "Version"),
       ("problems", "Problems"), ("settings", "Settings"))

# A nav row takes its glyph from ui.ICON[key], so the key of a screen and
# the name of its glyph are normally the same word. Problems has no glyph
# of its own — ui.py is not this wave's file — so it borrows the error
# mark HERE, rather than the one table that names the screens having to
# call the screen "error". A key with no glyph and no entry here is still
# a KeyError the first time the sidebar is built, which is the point.
NAV_GLYPH = {"problems": "error"}

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
                        "report_hotkey")),
)

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
}

# The right-hand column of a settings row: a switch, a menu, or a field.
CONTROL_W = 236
ENTRY_W = 150

# "Dictate (hold)" is one string in config.py because that is all the old
# window needed. Here the how is its own column.
HOW = re.compile(r"^(.*?)\s*\((hold|tap)\)\s*$")


def pretty_key(name: str) -> str:
    """'right ctrl' -> 'Right Ctrl'; '' -> 'off'."""
    return name.title() if name else "off"


def human_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


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
        pcfg = getattr(config_mod.load(CONFIG_PATH), "problems", None)
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
# git, for the branches the weekly routine leaves behind
# ---------------------------------------------------------------------------
#
# The routine builds what he has already answered, commits it to
# weekly/<YYYY-MM-DD> and NEVER pushes: pushing is his button, and it is
# the only thing standing between an autonomous routine and a public
# mistake. This is that button's plumbing.
#
# CREATE_NO_WINDOW on every call, for the reason versions.py measured:
# git is a console program, this window runs under pythonw, and a spawn
# without the flag ALLOCATES A CONSOLE — visible flicker and hundreds of
# milliseconds, on whichever thread asked. capture.py:1683 says the same
# where it opens explorer.
TRUNK = "fast"                 # where the routine's work goes home to
WEEKLY = "weekly/"             # ...from branches named weekly/<DATE>
GIT_READ_S = 20                # a local read
GIT_NET_S = 180                # a push, over his connection
_CREATE_NO_WINDOW = 0x08000000
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


def _trunk_ref() -> str:
    """`fast` if this repo has it, `origin/fast` if only the remote does,
    "" for a repo with neither — a one-branch clone, or no git at all.
    Everything a weekly branch is measured against is measured against
    this, and "" means the row says so instead of guessing."""
    for ref in (TRUNK, f"origin/{TRUNK}"):
        code, out, _err = _git("rev-parse", "--verify", "--quiet",
                               f"{ref}^{{commit}}")
        if code == 0 and out.strip():
            return ref
    return ""


def weekly_branches() -> list[dict]:
    """Every weekly/* branch and what is on it, newest name first.

    EVERY one of them, not the newest. A Saturday he never got round to
    reviewing leaves its branch behind, and a list showing only this
    week's would quietly bury it — the routine's own gate reads the same
    list to decide whether it may build at all.

    [] for a repo with no weekly branch, no git and no repository: each
    of those is a block with nothing in it, never an error.
    """
    code, out, _err = _git("for-each-ref", "--format=%(refname:short)",
                           f"refs/heads/{WEEKLY}")
    names = [ln.strip() for ln in out.splitlines() if ln.strip()] \
        if code == 0 else []
    if not names:
        return []
    trunk = _trunk_ref()
    rows: list[dict] = []
    for name in sorted(names, reverse=True):
        row = {"branch": name, "commits": 0, "files": [], "trunk": trunk,
               "on_origin": False, "subject": ""}
        if trunk:
            code, out, _err = _git("rev-list", "--count", f"{trunk}..{name}")
            if code == 0 and out.strip().isdigit():
                row["commits"] = int(out.strip())
            # Three dots: what the branch changed since it left the
            # trunk, not what the trunk has done since. He is being
            # shown what HE is about to push.
            code, out, _err = _git("diff", "--name-only", f"{trunk}...{name}")
            if code == 0:
                row["files"] = [ln.strip() for ln in out.splitlines()
                                if ln.strip()]
        code, out, _err = _git("log", "-1", "--format=%s", name)
        if code == 0:
            row["subject"] = _first_line(out)
        code, out, _err = _git("rev-parse", "--verify", "--quiet",
                               f"refs/remotes/origin/{name}")
        row["on_origin"] = code == 0 and bool(out.strip())
        rows.append(row)
    return rows


def _foreign_on_trunk() -> tuple[bool, list[str]]:
    """(could git tell us, what is on `fast` that is not the routine's).

    `origin/fast..fast` — and every commit in it is somebody else's.
    That is not a guess and not a heuristic: THE ROUTINE NEVER COMMITS
    TO `fast`. It cuts weekly/<DATE>, commits there, goes back to the
    branch it started on and pushes nothing, by its own rule; and the
    only way one of its commits can reach the local `fast` at all is the
    fast-forward at the end of this file, which happens after origin has
    already taken the same commit — so it is never unpushed. A commit
    sitting on `fast` that GitHub has not seen was made by one of the
    other sessions that share this branch.

    Why that matters here: a weekly branch is cut FROM `fast`, so it
    carries whatever was unpushed on it, and publishing the branch onto
    `fast` would take that half-finished commit up under the routine's
    name. His rule after dbf9b55 is that a session pushes its own work
    and nothing else — this is that rule, mechanised.

    And identity cannot be the test, however much it looks like it
    should be: every commit in this repo is authored by him with a Claude
    trailer, so author, committer and trailer are identical across all of
    them. Where a commit LIVES is the only thing that separates one
    session's from another's.

    A False first value means git could not answer, and that refuses the
    merge as well: not knowing is not the same as clean.
    """
    code, out, _err = _git("log", "--format=%H%x09%s",
                           f"origin/{TRUNK}..{TRUNK}")
    if code != 0:
        return False, []
    foreign: list[str] = []
    for line in out.splitlines():
        sha, _tab, subject = line.partition("\t")
        if sha.strip():
            foreign.append(f"{sha.strip()[:7]} {subject.strip()}"[:120])
    return True, foreign


def _merge_elsewhere(branch: str) -> dict:
    """The merge `fast` needs once it has moved on, done where this
    folder cannot be hurt by it.

    `git worktree add --detach` gives the merge its own tree and its own
    index in a temp folder: this repo's working tree — which carries
    three other sessions' unfinished work most hours of the day — is
    neither read nor written. That is why there is no `git stash`, no
    `git checkout` and no `git reset` anywhere on this path, and why a
    merge that would need one of them is a merge this button refuses.

    A conflict is ABORTED and handed back. His repo, his conflict; a
    resolution invented by a button at 4 AM is the one thing worse than
    a branch that waits.
    """
    import shutil
    import tempfile

    # A worktree left behind by a process that died mid-merge would
    # refuse the next one by name; pruning first costs nothing.
    _git("worktree", "prune")
    tmp = Path(tempfile.mkdtemp(prefix="deskit-merge-"))
    work = tmp / "tree"
    code, _out, err = _git("worktree", "add", "--detach", str(work),
                           f"origin/{TRUNK}", timeout=GIT_NET_S)
    if code != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        return {"pushed": True, "merged": False,
                "said": f"{branch} is on GitHub. {TRUNK} has moved on, so "
                        f"the merge needs a scratch worktree, and one could "
                        f"not be made — {_first_line(err) or 'git refused'}."}
    try:
        code, out, err = _git("merge", "--no-edit", branch, cwd=work,
                              timeout=GIT_NET_S)
        if code != 0:
            # The names BEFORE the abort: aborting is what makes them
            # unreadable, and the names are the whole message.
            _c, clashes, _e = _git("diff", "--name-only", "--diff-filter=U",
                                   cwd=work)
            names = [ln.strip() for ln in clashes.splitlines() if ln.strip()]
            _git("merge", "--abort", cwd=work)
            return {"pushed": True, "merged": False,
                    "said": f"{branch} is on GitHub. The merge into {TRUNK} "
                            f"CONFLICTS and was aborted, not resolved"
                            + (f" — {', '.join(names[:4])}" if names
                               else f" — {_first_line(out + err)}")
                            + ". That one is yours to look at."}
        sha = _git("rev-parse", "HEAD", cwd=work)[1].strip()
        code, out, err = _git("push", "origin", f"{sha}:refs/heads/{TRUNK}",
                              timeout=GIT_NET_S)
        if code != 0:
            return {"pushed": True, "merged": False,
                    "said": f"{branch} is on GitHub. The merge into {TRUNK} "
                            f"came out clean but origin refused it — "
                            f"{_first_line(err or out)}. Nothing was forced."}
        _git("fetch", "origin", TRUNK, timeout=GIT_NET_S)
        return {"pushed": True, "merged": True,
                "said": f"{branch} is on GitHub, and {TRUNK} has it as a "
                        f"merge commit ({sha[:7]}) — {TRUNK} had moved on, "
                        f"so it took a real merge. Your local {TRUNK} is "
                        f"behind origin now; pull it when the tree is yours."}
    finally:
        # The one --force in this file, and it is on a TEMP FOLDER, not
        # on a ref: `worktree remove` refuses a tree with anything in it,
        # and a half-merged scratch tree always has. Nothing about this
        # reaches a branch, a remote or this repo's working tree.
        _git("worktree", "remove", "--force", str(work))
        shutil.rmtree(tmp, ignore_errors=True)


def push_weekly(branch: str) -> dict:
    """His Push button, in order, with the reason for each step.

    1. `git push origin <branch>` FIRST, before anything is checked. The
       routine's work has been on one disk since Saturday, and getting it
       off the machine is the half of this that must not wait for a merge
       to be safe. If the merge is then refused, the work is still on
       GitHub — which is the whole reason the branch goes first.
    2. Then `fast`: anything on it that origin has not got and the
       routine did not write is another session's work, and publishing
       the branch onto `fast` would take that with it. Refuse, and name
       the commit.
    3. A fast-forward is published as one — `git push origin
       <branch>:fast`, which touches no local branch and no file in this
       folder. Anything else is a real merge, and a real merge happens in
       a throwaway worktree (see _merge_elsewhere).

    Never --force, never -f, no conflict resolved here, and the working
    tree is never touched. ONE BUTTON: he asked whether two would be
    safer and the honest answer was no — the safety is the check, not a
    second thing for him to choose between.

    Returns {"pushed": bool, "merged": bool, "said": str}. `said` is the
    sentence the row shows him, and it says which of the three happened.
    """
    code, out, err = _git("push", "origin", branch, timeout=GIT_NET_S)
    if code != 0:
        return {"pushed": False, "merged": False,
                "said": f"{branch} did NOT go up — "
                        f"{_first_line(err or out) or 'git refused'}"}
    # origin/fast as it is NOW, not as it was last week: every check
    # below is about what is on GitHub at this moment.
    code, _out, err = _git("fetch", "origin", TRUNK, timeout=GIT_NET_S)
    if code != 0:
        return {"pushed": True, "merged": False,
                "said": f"{branch} is on GitHub. {TRUNK} was left alone: "
                        f"origin/{TRUNK} could not be read "
                        f"({_first_line(err) or 'the fetch failed'}), and a "
                        f"merge nobody can check is not one to make."}
    told, foreign = _foreign_on_trunk()
    if not told:
        return {"pushed": True, "merged": False,
                "said": f"{branch} is on GitHub. {TRUNK} was left alone: git "
                        f"could not say what is on it that origin has not, "
                        f"and not knowing is not the same as clean."}
    if foreign:
        return {"pushed": True, "merged": False,
                "said": f"{branch} is on GitHub. {TRUNK} was NOT merged: it "
                        f"carries {len(foreign)} commit(s) GitHub has not "
                        f"seen, and the routine never commits to {TRUNK} — "
                        f"so they are another session's: "
                        f"{'; '.join(foreign[:3])}. That work goes up with "
                        f"the session that wrote it, never with this "
                        f"button."}
    if _git("merge-base", "--is-ancestor", f"origin/{TRUNK}", branch)[0] != 0:
        return _merge_elsewhere(branch)
    code, out, err = _git("push", "origin", f"{branch}:{TRUNK}",
                          timeout=GIT_NET_S)
    if code != 0:
        return {"pushed": True, "merged": False,
                "said": f"{branch} is on GitHub. {TRUNK} was refused by "
                        f"origin — {_first_line(err or out)}. Nothing was "
                        f"forced."}
    # And the local branch, IF git will let us: a fetch into a ref is
    # fast-forward-only without a +, and it refuses outright to write the
    # branch a working tree is standing on. That refusal is the guard we
    # want rather than an obstacle — moving `fast` out from under this
    # tree would leave every file the routine wrote looking like an
    # uncommitted revert to whichever session next ran `git status`.
    moved = _git("fetch", ".", f"{branch}:{TRUNK}")[0] == 0
    head = _git("rev-parse", "--abbrev-ref", "HEAD")[1].strip()
    trailer = ""
    if not moved:
        trailer = (f" Your local {TRUNK} still points at the old tip: "
                   + (f"git will not move the branch this working tree is "
                      f"standing on, and the tree is not ours to touch. "
                      if head == TRUNK else
                      f"the local fast-forward was refused (push.log says "
                      f"why). ")
                   + "`git pull` when it suits you.")
    _git("fetch", "origin", TRUNK, timeout=GIT_NET_S)
    return {"pushed": True, "merged": True,
            "said": f"{branch} is on GitHub, and {TRUNK} carries it — a "
                    f"fast-forward, no merge commit." + trailer}


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


def _keys_screen_paths() -> set[str]:
    """The config.toml paths the Keys screen owns. The Settings screen
    leaves those to it — one place to rebind a key — and a test holds the
    two screens to covering the file between them."""
    return {NESTED_HOTKEYS.get(field, field)
            for field, _label in config_mod.HOTKEY_FIELDS}


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
        # A whole-app version switch in flight: while it runs, the Version
        # screen's buttons are dead and a second press must do nothing.
        self._switching = False
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
        threading.Thread(target=self._warm_versions, daemon=True,
                         name="versions-warmup").start()
        self._busy_until = 0.0     # ignore polls right after a command, so a
                                   # stale status cannot flicker the buttons
                                   # back for one frame
        self.screen = "Overview"
        self.parts: dict = {}      # the widgets of whichever screen is up
        self.log: list[history.Event] = []
        self._log_stamp: tuple[int, float] = (0, 0.0)
        self._filter: str | None = None
        self._query = ""
        self._toast = None
        self._toast_after = None
        self._pump_after = None
        self._search_after = None
        self._settings_query = ""
        self._settings_after = None
        self._settings_tab = settings_mod.TABS[0].name
        self._settings_searching = False
        # The settings cards still to be built, one per tick — see
        # _fill_settings — and the tick that will build the next.
        self._settings_left: list = []
        self._settings_tick = None
        self._rows_after = None
        self._rows_left: list = []
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
        # The routine's branches, as git last answered. None is "nobody
        # has asked yet", which is not the same as "there are none".
        self._weekly = None
        self._weekly_scanning = False
        self._push_buttons: dict = {}
        self._push_said: dict = {}  # what the last press did, per branch
        self._pushing = None        # the branch a push is in flight for

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
        self._sidebar()
        self.pane = tk.Frame(self.root, bg=ui.PANE, width=W - SIDE, height=H)
        self.pane.place(x=SIDE, y=0)
        self.pane.pack_propagate(False)
        # Screens are built onto a SHEET inside the pane, not onto the pane
        # itself, so a new screen can slide into place — the pane stays
        # put, the sheet moves. The toast lives on the pane and does not.
        self.sheet = tk.Frame(self.pane, bg=ui.PANE, width=W - SIDE,
                              height=H)
        self.sheet.place(x=0, y=0)
        self.sheet.pack_propagate(False)
        self._show("Overview")

    def _sidebar(self) -> None:
        """Identity at the top, the four screens under it, the state at the
        bottom — where it stays visible whichever screen is open."""
        bar = tk.Frame(self.root, bg=ui.BG, width=SIDE, height=H)
        bar.place(x=0, y=0)
        tk.Frame(self.root, bg=ui.RULE, width=1, height=H).place(x=SIDE - 1,
                                                                   y=0)
        badge = ui.icon_bitmap(ICON_PNG, 32, ui.BG)
        if badge is not None:
            self._keep.append(badge)
            tk.Label(bar, image=badge, bg=ui.BG).place(x=20, y=22)
        tk.Label(bar, text="DeskIT", bg=ui.BG, fg=ui.FG,
                 font=(ui.UI, 10, "bold")).place(x=62, y=23)
        self.parts["hint"] = tk.Label(bar, text="", bg=ui.BG, fg=ui.FAINT,
                                      font=(ui.UI, 8))
        self.parts["hint"].place(x=62, y=42)

        # Nine rows and the report button have to fit above the state
        # card, which is why the stride is 46 rather than the 48 eight
        # rows could afford. 86 + 46*9 = 500, the button sits at 504 and
        # the card starts at 546.
        #
        # With [problems] enabled = false there are eight rows and no
        # button, and the sidebar goes back to the 92 and 48 it had
        # before any of this: the spacing those eight rows were designed
        # with, rather than eight of them rattling around in nine rows'
        # worth of room. 92 + 48*8 = 476, and the card is still at 546.
        self.nav: dict[str, tuple] = {}
        rows = [(key, name) for key, name in NAV
                if key != "problems" or self._problems_on]
        y, stride = (86, 46) if self._problems_on else (92, 48)
        for key, name in rows:
            item = tk.Canvas(bar, width=188, height=42, bg=ui.BG,
                             highlightthickness=0, bd=0, cursor="hand2")
            item.place(x=12, y=y)
            faces = (ui.rounded(188, 42, 11, ui.ACCENT_SOFT, ui.BG, ui.ACCENT_EDGE),
                     ui.rounded(188, 42, 11, ui.BG, ui.BG),
                     ui.rounded(188, 42, 11, ui.SIDE_IDLE, ui.BG))
            face = item.create_image(0, 0, anchor="nw", image=faces[1])
            glyph = item.create_text(28, 21,
                                     text=ui.ICON[NAV_GLYPH.get(key, key)],
                                     font=(ui.ICONS, 13), fill=ui.DIM)
            label = item.create_text(50, 22, text=name, font=(ui.UI, 10),
                                     anchor="w", fill=ui.DIM)
            self.nav[name] = (item, face, glyph, label, faces)
            item.bind("<Button-1>", lambda _e, n=name: self._show(n))
            item.bind("<Enter>", lambda _e, n=name: self._nav_hover(n, True))
            item.bind("<Leave>", lambda _e, n=name: self._nav_hover(n, False))
            y += stride

        # The report button lives in the SIDEBAR, once, rather than on
        # each of the nine screens. Two reasons, and the second is the
        # real one. A bug is noticed while looking at the thing that is
        # wrong, so the way to say so has to be in the same place
        # whichever screen that is — and the eight screens place every
        # widget absolutely, with the top-right taken on Review and
        # Settings and the bottom-right taken on History, so there is no
        # one free rectangle on the sheet to put it in. The sidebar has
        # one, it survives _show destroying the sheet, and it sits under
        # the Problems row that reads the reports back.
        if self._problems_on:
            ui.Button(bar, "Report a problem", self._report, w=188, h=34,
                      bg=ui.BG, quiet=True,
                      icon=ui.ICON["error"]).place(x=12, y=y + 4)

        card = ui.Card(bar, 188, 78, bg=ui.BG, fill=ui.SIDE_CARD, radius=12,
                       pad=14)
        card.place(x=12, y=H - 102)
        self.parts["lamp"] = tk.Label(card.body, bg=ui.SIDE_CARD)
        self.parts["lamp"].place(x=-4, y=6)
        self.parts["state"] = tk.Label(card.body, text="", bg=ui.SIDE_CARD,
                                       fg=ui.FG, font=(ui.UI, 10, "bold"))
        self.parts["state"].place(x=26, y=4)
        self.parts["uptime"] = tk.Label(card.body, text="", bg=ui.SIDE_CARD,
                                        fg=ui.FAINT, font=(ui.UI, 8))
        self.parts["uptime"].place(x=26, y=24)

    def _nav_hover(self, name: str, over: bool) -> None:
        item, face, _glyph, _label, faces = self.nav[name]
        if name != self.screen:
            item.itemconfig(face, image=faces[2] if over else faces[1])

    def _paint_nav(self) -> None:
        for name, (item, face, glyph, label, faces) in self.nav.items():
            picked = name == self.screen
            item.itemconfig(face, image=faces[0] if picked else faces[1])
            item.itemconfig(glyph, fill=ui.ACCENT_TEXT if picked else ui.DIM)
            item.itemconfig(label, fill=ui.FG if picked else ui.DIM,
                            font=(ui.UI, 10, "bold") if picked
                            else (ui.UI, 10))

    def _show(self, name: str) -> None:
        """Swap screens. Everything the old one registered goes with it, so
        _refresh has to ask for a widget rather than assume one."""
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
                ("hint", "lamp", "state", "uptime") if k in self.parts}
        self.parts = keep
        self._hide_toast()
        {"Overview": self._screen_overview,
         "History": self._screen_history,
         "Review": self._screen_review,
         "Awake": self._screen_awake,
         "Notify": self._screen_notify,
         "Keys": self._screen_keys,
         "Version": self._screen_version,
         "Problems": self._screen_problems,
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
        offsets = (16, 10, 6, 3, 1, 0)
        self.sheet.place(x=0, y=offsets[step])
        if step + 1 < len(offsets) and not self.closing:
            self._slide_after = self.root.after(
                18, lambda: self._slide_in(step + 1))
        else:
            self._slide_after = None

    def _title(self, text: str, right: str = "") -> None:
        tk.Label(self.sheet, text=text, bg=ui.PANE, fg=ui.FG,
                 font=(ui.DISPLAY, 17, "bold")).place(x=PAD, y=20)
        if right:
            tk.Label(self.sheet, text=right, bg=ui.PANE, fg=ui.FAINT,
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
                       fill=ui.QUOTE_BG, border=ui.QUOTE_EDGE, pad=12)
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
        card.place(x=PAD, y=H - 16 + offsets[step], anchor="sw")
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

    # ----------------------------------------------------------- overview

    def _screen_overview(self) -> None:
        self._title("Overview")
        p = self.parts
        self._stats_shown = False

        # The geometry that cannot collide: the top row holds the state
        # word (short by construction — RUNNING, PAUSED) and the buttons,
        # nothing else; the mic line and the hint get the FULL width on
        # their own rows underneath. The first layout gave the hint 400 px
        # next to the buttons and they met in the middle.
        hero = ui.Card(self.sheet, CW, 148, pad=18)
        hero.place(x=PAD, y=68)
        body = hero.body
        inner = CW - 36
        # A slim bar in the state's colour down the left edge — the state
        # readable from the corner of an eye, before the word is.
        p["hero_bar"] = tk.Label(body, bg=ui.CARD)
        p["hero_bar"].place(x=-4, y=0)
        p["hero_lamp"] = tk.Label(body, bg=ui.CARD)
        p["hero_lamp"].place(x=8, y=-3)
        p["hero_state"] = tk.Label(body, text="", bg=ui.CARD, fg=ui.FG,
                                   font=(ui.DISPLAY, 19, "bold"))
        p["hero_state"].place(x=56, y=1)
        p["hero_meta"] = tk.Label(body, text="", bg=ui.CARD, fg=ui.DIM,
                                  font=(ui.UI, 9), anchor="w")
        p["hero_meta"].place(x=57, y=44)
        p["hero_hint"] = tk.Label(body, text="", bg=ui.CARD, fg=ui.FAINT,
                                  font=(ui.UI, 8), justify="left", anchor="w")
        p["hero_hint"].place(x=57, y=68)

        row = tk.Frame(body, bg=ui.CARD)
        row.place(x=inner, y=0, anchor="ne")
        p["start"] = ui.Button(row, "Start", self._start, w=104,
                               primary=True, icon=ui.ICON["play"])
        p["start"].pack(side="left")
        p["pause"] = ui.Button(row, "Pause", self._toggle_pause, w=100,
                               icon=ui.ICON["pause"])
        p["pause"].pack(side="left", padx=8)
        p["stop"] = ui.Button(row, "Stop", self._stop, w=96,
                              icon=ui.ICON["stop"])
        p["stop"].pack(side="left")

        titles = (("DICTATIONS", "count"), ("SPOKEN", "spoken"),
                  ("CHARACTERS", "chars"), ("AVERAGE WAIT", "wait"))
        x = PAD
        tile_hot = ui.rounded(161, 86, 14, ui.CARD_HI, ui.PANE, ui.TILE_EDGE)
        tile_idle = ui.rounded(161, 86, 14, ui.CARD, ui.PANE, ui.LINE)
        for title, key in titles:
            tile = ui.Card(self.sheet, 161, 86, pad=14)
            tile.place(x=x, y=228)
            tk.Label(tile.body, text=title, bg=ui.CARD, fg=ui.FAINT,
                     font=(ui.UI, 8)).place(x=0, y=0)
            p[f"stat_{key}"] = tk.Label(tile.body, text="—", bg=ui.CARD,
                                        fg=ui.FG, font=(ui.DISPLAY, 21,
                                                        "bold"))
            p[f"stat_{key}"].place(x=0, y=20)
            p[f"unit_{key}"] = tk.Label(tile.body, text="", bg=ui.CARD,
                                        fg=ui.DIM, font=(ui.UI, 9))
            p[f"unit_{key}"].place(x=0, y=36)
            for widget in (tile, tile.body, *tile.body.winfo_children()):
                widget.bind("<Enter>",
                            lambda _e, t=tile: t.face(tile_hot))
                widget.bind("<Leave>",
                            lambda _e, t=tile: t.face(tile_idle))
            x += 173

        card = ui.Card(self.sheet, CW, 192, pad=18)
        card.place(x=PAD, y=326)
        body, inner = card.body, CW - 36
        tk.Label(body, text=ui.ICON["mic"], bg=ui.CARD, fg=ui.ACCENT,
                 font=(ui.ICONS, 11)).place(x=0, y=1)
        tk.Label(body, text="LAST DICTATION", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=22, y=2)
        p["last_when"] = tk.Label(body, text="", bg=ui.CARD, fg=ui.DIM,
                                  font=(ui.UI, 9))
        p["last_when"].place(x=inner, y=1, anchor="ne")
        p["last_text"] = tk.Label(body, text="", bg=ui.CARD, fg=ui.FG,
                                  font=(ui.TEXT, 12))
        p["last_meta"] = tk.Label(body, text="", bg=ui.CARD, fg=ui.FAINT,
                                  font=(ui.UI, 8))
        p["last_meta"].place(x=0, y=100)
        p["copy"] = ui.Button(body, "Copy text", self._copy_last, w=112,
                              icon=ui.ICON["copy"])
        p["copy"].place(x=0, y=118)
        ui.Button(body, "Show in history", lambda: self._show("History"),
                  w=140, quiet=True, icon=ui.ICON["history"]).place(x=120,
                                                                    y=118)

        vocab = ui.Card(self.sheet, 334, 100, pad=16)
        vocab.place(x=PAD, y=530)
        tk.Label(vocab.body, text=ui.ICON["learned"], bg=ui.CARD,
                 fg=ui.AMBER, font=(ui.ICONS, 10)).place(x=0, y=1)
        tk.Label(vocab.body, text="VOCABULARY", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=20, y=2)
        p["vocab_head"] = tk.Label(vocab.body, text="—", bg=ui.CARD,
                                   fg=ui.FG, font=(ui.DISPLAY, 15, "bold"))
        p["vocab_head"].place(x=0, y=24)
        p["vocab_sub"] = tk.Label(vocab.body, text="", bg=ui.CARD, fg=ui.DIM,
                                  font=(ui.UI, 8))
        p["vocab_sub"].place(x=0, y=50)

        phone = ui.Card(self.sheet, 334, 100, pad=16)
        phone.place(x=PAD + 346, y=530)
        tk.Label(phone.body, text=ui.ICON["globe"], bg=ui.CARD, fg=ui.GREEN,
                 font=(ui.ICONS, 10)).place(x=0, y=1)
        tk.Label(phone.body, text="PHONE", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=20, y=2)
        p["phone_head"] = tk.Label(phone.body, text="—", bg=ui.CARD,
                                   fg=ui.FG, font=(ui.DISPLAY, 15, "bold"))
        p["phone_head"].place(x=0, y=24)
        p["phone_sub"] = tk.Label(phone.body, text="", bg=ui.CARD, fg=ui.DIM,
                                  font=(ui.UI, 8))
        p["phone_sub"].place(x=0, y=50)
        p["phone_copy"] = ui.Button(phone.body, "Copy link", self._copy_phone,
                                    w=100, h=32, quiet=True,
                                    icon=ui.ICON["link"])
        p["phone_copy"].place(x=202, y=26)

    def _paint_overview(self) -> None:
        p = self.parts
        if "hero_state" not in p:
            return
        status = self.status
        colour, word = self._look()
        p["hero_state"].config(text=word)
        p["hero_bar"].config(image=ui.rounded(4, 112, 2, colour, ui.CARD))

        bits = []
        # The version leads: it is the one fact on this line that changes
        # what the rest of the words mean ("local" under fast is a
        # different repair pass than "local" under classic).
        if getattr(self, "branch", "") not in ("", "?"):
            bits.append(self.branch)
        if status.get("backend"):
            bits.append(status["backend"])
        if status.get("mic"):
            bits.append(status["mic"])
        if status.get("uptime_s"):
            bits.append(f"up {human_time(status['uptime_s'])}")
        meta, _lines = ui.clamp("   ·   ".join(bits), ui.UI, 9,
                                CW - 36 - 57, 1)
        p["hero_meta"].config(text=meta)
        hint, _lines = ui.clamp(self._explain(), ui.UI, 8, CW - 36 - 57, 2)
        p["hero_hint"].config(text=hint)

        p["start"].enable(not status)
        p["stop"].enable(bool(status))
        p["pause"].enable(self.running)
        p["pause"].configure_text("Resume" if status.get("paused")
                                  else "Pause")

        stats = status.get("stats") or {}
        count = stats.get("dictations", 0)
        targets = {
            "count": (count, "{:.0f}", ""),
            "spoken": (stats.get("seconds", 0) / 60, "{:.1f}", "min"),
            "chars": (stats.get("chars", 0), "{:,.0f}", ""),
            "wait": (stats.get("latency", 0.0) / count if count else 0.0,
                     "{:.1f}", "s"),
        }
        if not status:
            for key in targets:
                p[f"stat_{key}"].config(text="—")
                self._unit(key, "")
            self._stats_shown = False
        elif not self._stats_shown:
            # The first look at this screen counts the numbers up from
            # zero — 350 ms, then they are just numbers again. Every poll
            # after this one writes them directly.
            self._stats_shown = True
            self._count_up(targets, step=0)
        else:
            for key, (value, fmt, unit) in targets.items():
                p[f"stat_{key}"].config(text=fmt.format(value))
                self._unit(key, unit)

        last = next((e for e in self.log if e.kind == "dictation"), None)
        text = last.text if last else ""
        if text:
            # Windows draws the paragraph (ui.draw_text) — Tk's own text
            # path lays mixed Hebrew/English runs out in the wrong order.
            photo, _h, _lines = ui.draw_text(text, pt=12, width=CW - 36,
                                             max_lines=3, colour=ui.FG,
                                             bg=ui.CARD)
            p["last_text"].config(image=photo, text="")
            p["last_text"].photo = photo
            p["last_text"].place(x=0, y=26, anchor="nw")
            p["last_when"].config(text=last.when.strftime("%H:%M"))
            p["last_meta"].config(text=last.meta())
        else:
            p["last_text"].config(image="",
                                  text="Nothing dictated yet — hold the "
                                       "dictation key and say something.",
                                  justify="left", anchor="w")
            p["last_text"].place(x=0, y=26, anchor="nw")
            p["last_when"].config(text="")
            p["last_meta"].config(text="")
        p["copy"].enable(bool(text))

        vocab = status.get("vocab") or {}
        if vocab:
            learned = vocab.get("corrections", 0)
            p["vocab_head"].config(
                text=f"{learned} word{'' if learned == 1 else 's'} learned")
            p["vocab_sub"].config(
                text=f"{vocab.get('automatic', 0)} repaired automatically"
                     f"   ·   {vocab.get('hotwords', 0)} hotwords")
        else:
            p["vocab_head"].config(text="—")
            p["vocab_sub"].config(text="start it to see what it has learned"
                                  if not status else "")

        url = status.get("phone", "")
        p["phone_head"].config(text="endpoint is live" if url else "off")
        p["phone_sub"].config(
            text="dictate from the phone on this network" if url
            else "[server] enabled = false, or it is not running")
        p["phone_copy"].enable(bool(url))

        pending = status.get("pending") or 0
        if pending:
            self._note(f"{pending} recording(s) waiting in pending\\ — "
                       f"run main.py --drain to get the text back")

    def _count_up(self, targets: dict, step: int) -> None:
        """The stat tiles counting to their values, eased so the last few
        frames land softly. Twelve frames at 30 ms."""
        if self.closing or "stat_count" not in self.parts:
            return
        frames = 12
        progress = 1 - (1 - step / frames) ** 3
        for key, (value, fmt, unit) in targets.items():
            self.parts[f"stat_{key}"].config(text=fmt.format(value * progress))
            self._unit(key, unit)
        if step < frames and self.screen == "Overview":
            self.root.after(30, lambda: self._count_up(targets, step + 1))

    def _unit(self, key: str, text: str) -> None:
        """Park the unit right after the number, whatever its width."""
        value = self.parts[f"stat_{key}"]
        value.update_idletasks()
        self.parts[f"unit_{key}"].config(text=text)
        self.parts[f"unit_{key}"].place(x=value.winfo_reqwidth() + 4, y=36)

    # ------------------------------------------------------------ history

    def _screen_history(self) -> None:
        self._title("History", f"the last {HISTORY_ROWS} of what you said")
        p = self.parts

        search = ui.Card(self.sheet, CW, 40, radius=11, pad=11)
        search.place(x=PAD, y=64)
        tk.Label(search.body, text=ui.ICON["search"], bg=ui.CARD,
                 fg=ui.FAINT, font=(ui.ICONS, 10)).place(x=0, y=1)
        entry = tk.Entry(search.body, bg=ui.CARD, fg=ui.FG, bd=0,
                         highlightthickness=0, font=(ui.UI, 10),
                         insertbackground=ui.ACCENT)
        entry.place(x=26, y=0, width=CW - 90, height=18)
        entry.insert(0, self._query)
        entry.bind("<KeyRelease>", lambda _e: self._search_soon(entry.get()))
        p["search"] = entry
        p["placeholder"] = tk.Label(search.body,
                                    text="Search everything you have said…",
                                    bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 9))
        if not self._query:
            p["placeholder"].place(x=26, y=1)
        entry.bind("<FocusIn>", lambda _e: p["placeholder"].place_forget())

        chips = tk.Frame(self.sheet, bg=ui.PANE)
        chips.place(x=PAD, y=114)
        p["chips"] = {}
        for name, kind in history.FILTERS:
            chip = ui.Chip(chips, name, lambda k=kind: self._filter_to(k),
                           active=(kind == self._filter))
            chip.pack(side="left", padx=(0, 6))
            p["chips"][kind] = chip

        p["list"] = ui.Scroller(self.sheet, CW + 10, 448)
        p["list"].place(x=PAD, y=156)
        p["empty"] = tk.Label(self.sheet, text="", bg=ui.PANE, fg=ui.FAINT,
                              font=(ui.UI, 10))

        tk.Label(self.sheet, text="Everything older is still in "
                                 "transcripts.log, untouched.",
                 bg=ui.PANE, fg=ui.FAINT, font=(ui.UI, 8)).place(x=PAD, y=616)
        ui.Button(self.sheet, "Open transcripts.log",
                  lambda: launch.open_path(history.LOG), w=170, h=30,
                  quiet=True, bg=ui.PANE,
                  icon=ui.ICON["file"]).place(x=PAD + CW - 170, y=608)
        self._fill_history()

    def _filter_to(self, kind: str | None) -> None:
        self._filter = kind
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
        if text:
            self.parts["placeholder"].place_forget()
        elif self.parts["search"] is not self.root.focus_get():
            self.parts["placeholder"].place(x=26, y=1)
        self._fill_history()

    def _fill_history(self) -> None:
        """Draw the first screenful now and the rest in the background.

        A hundred rows is about four hundred milliseconds of measuring and
        drawing, and six of them are visible. Doing all of it before
        letting go of the event loop is a filter chip that takes half a
        second to look pressed; doing a screenful and then chunks of
        twenty-five between frames is one that answers immediately.
        """
        if "list" not in self.parts:
            return
        self._stop_rows()
        scroller = self.parts["list"]
        scroller.clear()
        shown = history.filtered(self.log, self._filter, self._query)
        self.parts["empty"].place_forget()
        if not shown:
            self.parts["empty"].config(
                text="Nothing here yet." if not self.log
                else "Nothing matches that.")
            self.parts["empty"].place(x=PAD + CW / 2, y=320, anchor="center")
        self._rows_left = list(shown)
        self._draw_rows(8)
        scroller.to_top()

    def _draw_rows(self, count: int) -> None:
        if "list" not in self.parts or self.closing:
            return
        chunk, self._rows_left = self._rows_left[:count], self._rows_left[count:]
        for event in chunk:
            self._history_row(self.parts["list"], event)
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
        left, edge = 106, CW - 14
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

        row = tk.Canvas(scroller.inner, width=CW, height=height, bg=ui.PANE,
                        highlightthickness=0, bd=0, cursor="hand2")
        row.pack(pady=(0, 8))
        idle = ui.rounded(CW, height, 12, ui.CARD, ui.PANE, ui.LINE)
        hot = ui.rounded(CW, height, 12, ui.CARD_HI, ui.PANE, ui.TILE_EDGE)
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
        return review_mod.Store(APP_DIR / review_mod.STORE_NAME)

    def _review_stat(self):
        try:
            st = os.stat(APP_DIR / "review.json")
            return (st.st_size, st.st_mtime_ns)
        except OSError:
            return None

    def _screen_review(self) -> None:
        self._title("Review", "what the second reading proposes — you decide")
        p = self.parts
        p["review_head"] = tk.Label(self.sheet, text="", bg=ui.PANE,
                                    fg=ui.DIM, font=(ui.UI, 10))
        p["review_head"].place(x=PAD, y=66)
        p["review_list"] = ui.Scroller(self.sheet, CW + 10, 500)
        p["review_list"].place(x=PAD, y=100)
        p["review_empty"] = tk.Label(self.sheet, text="", bg=ui.PANE,
                                     fg=ui.FAINT, font=(ui.UI, 10))
        tk.Label(self.sheet,
                 text="After each dictation a card asks the same question "
                      "for a few seconds; what it got no answer to waits "
                      "here. Yes teaches the vocabulary; No is remembered.",
                 bg=ui.PANE, fg=ui.FAINT, font=(ui.UI, 8),
                 wraplength=CW, justify="left").place(x=PAD, y=606)
        self._review_stamp = None
        self._fill_review()

    def _poll_review(self) -> None:
        """Once a second from _refresh: redraw only when the file moved —
        a new proposal from the app, or a decision from its card."""
        if "review_list" not in self.parts:
            return
        if self._review_stat() != getattr(self, "_review_stamp", None):
            self._fill_review()

    def _fill_review(self) -> None:
        if "review_list" not in self.parts:
            return
        self._review_stamp = self._review_stat()
        try:
            store = self._review_store()
            pending, decided = store.pending(), store.decided(30)
            summary = store.summary()
        except Exception:                 # noqa: BLE001 — a broken file
            pending, decided = [], []
            summary = {"pending": 0, "accepted": 0, "rejected": 0}
        self.parts["review_head"].config(
            text=f"{summary.get('pending', 0)} waiting   ·   "
                 f"{summary.get('accepted', 0)} accepted   ·   "
                 f"{summary.get('rejected', 0)} rejected")
        scroller = self.parts["review_list"]
        scroller.clear()
        empty = self.parts["review_empty"]
        empty.place_forget()
        if not pending and not decided:
            empty.config(text="Nothing to review yet — dictate, and the "
                              "second reading speaks up when it disagrees.")
            empty.place(x=PAD + CW / 2, y=300, anchor="center")
        for item in pending:
            self._review_row(scroller, item, pending=True)
        if decided:
            tk.Label(scroller.inner, text="DECIDED", bg=ui.PANE,
                     fg=ui.FAINT, font=(ui.MEDIUM, 8)).pack(
                anchor="w", pady=(8 if pending else 0, 6))
        for item in decided:
            self._review_row(scroller, item, pending=False)
        scroller.to_top()

    def _review_row(self, scroller: ui.Scroller, item: dict,
                    pending: bool) -> None:
        """One proposal, one canvas — the sentence as it would read, the
        changed words as pills, the reason, and Yes / No while it is
        still a question. Same layout rules as a history row: time and
        the buttons on the left, text flush right."""
        text = item.get("proposed") or item.get("text") or ""
        changes = item.get("changes") or []
        left, edge = 106, CW - 14
        width = edge - left
        photo, text_h, _lines = ui.draw_text(
            text, pt=11, width=width, max_lines=2,
            colour=ui.FG if pending else ui.DIM, bg=ui.CARD)
        why = "   ·   ".join(c.get("why", "") for c in changes
                             if c.get("why"))
        note = None
        note_h = 0
        if why:
            note, note_h, _l = ui.draw_text(why, pt=8, width=width,
                                            max_lines=1, colour=ui.FAINT,
                                            bg=ui.CARD)
        height = 13 + text_h + (38 if changes else 0) \
            + (note_h + 6 if note is not None else 0) + 12
        height = max(height, 80)
        row = tk.Canvas(scroller.inner, width=CW, height=height, bg=ui.PANE,
                        highlightthickness=0, bd=0)
        row.pack(pady=(0, 8))
        row.create_image(0, 0, anchor="nw", image=ui.rounded(
            CW, height, 12, ui.CARD, ui.PANE,
            ui.TILE_EDGE if pending else ui.LINE))
        when = str(item.get("when", ""))
        row.create_text(14, 15, text=when[11:16], anchor="nw",
                        font=(ui.UI, 10, "bold"), fill=ui.FG)
        try:
            day = time.strftime("%d %b", time.strptime(when,
                                                       "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            day = ""
        row.create_text(14, 34, text=day, anchor="nw", font=(ui.UI, 8),
                        fill=ui.FAINT)
        row.create_image(left, 13, anchor="nw", image=photo)
        y = 13 + text_h + 8
        if changes:
            x = edge
            for change in changes[:4]:
                after = change.get("after") or "—"
                x -= ui.pair_pill(row, x, y, change.get("before", ""),
                                  after, ui.CARD) + 6
            y += 36
        if note is not None:
            row.create_image(edge, y, anchor="ne", image=note)
        if pending:
            sid = str(item.get("id", ""))
            yes = ui.Button(row, "Yes", lambda s=sid: self._review_decide(
                s, "accepted"), w=44, h=26, quiet=True, fg=ui.GREEN)
            no = ui.Button(row, "No", lambda s=sid: self._review_decide(
                s, "rejected"), w=40, h=26, quiet=True, fg=ui.RED)
            row.create_window(14, height - 38, window=yes, anchor="nw")
            row.create_window(62, height - 38, window=no, anchor="nw")
        else:
            accepted = item.get("status") == "accepted"
            by = item.get("by") or ""
            row.create_text(14, height - 26, anchor="nw", font=(ui.UI, 8),
                            fill=ui.GREEN if accepted else ui.FAINT,
                            text=("accepted" if accepted else "rejected")
                            + (f"  ·  {by}" if by else ""))
        scroller.bind_wheel(row)

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
        self._fill_review()

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
            return module.Store(APP_DIR / module.STORE_NAME)
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
        """questions.json, read off the disk. THREE processes write it —
        the app's card, this window and the headless routine — which is
        why the store carries a lock file and lands every write by
        rename; nothing here has to arbitrate."""
        module = self._questions()
        if module is None:
            return None
        try:
            return module.Store(APP_DIR / module.STORE_NAME)
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
        if module is None or store is None:
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
            module.digest(store, APP_DIR / module.DIGEST_NAME)
        except Exception:                 # noqa: BLE001 — a digest that
            pass                          # did not get written is nothing

    def _open_digest(self) -> None:
        """The weekly read, in whatever opens .md files here. The name
        comes off the module rather than out of this line, so the two
        cannot drift; the fallback is for the module being absent, when
        the file will not be there either and open_path says so."""
        name = getattr(self._problems(), "DIGEST_NAME", "problems.md")
        launch.open_path(APP_DIR / name)

    def _screen_problems(self) -> None:
        """His own bug list: what he reported, and whether it is answered.

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
        self._title("Problems", "what you reported — you decide when it is "
                                "done")
        p = self.parts
        p["problems_head"] = tk.Label(self.sheet, text="", bg=ui.PANE,
                                      fg=ui.DIM, font=(ui.UI, 10))
        p["problems_head"].place(x=PAD, y=66)
        # WHAT NEEDS HIM LEADS THE TAB. The report counts are a state of
        # the world; a pending question is the routine standing still
        # until he answers, so when there is one it takes the left of
        # this line and the counts move over. _fill_problems places both.
        p["questions_head"] = tk.Label(self.sheet, text="", bg=ui.PANE,
                                       fg=ui.ACCENT_TEXT,
                                       font=(ui.MEDIUM, 10))
        p["problems_list"] = ui.Scroller(self.sheet, CW + 10, 496)
        p["problems_list"].place(x=PAD, y=100)
        p["problems_empty"] = tk.Label(self.sheet, text="", bg=ui.PANE,
                                       fg=ui.FAINT, font=(ui.UI, 10),
                                       wraplength=CW - 80, justify="center")
        tk.Label(self.sheet,
                 text="Report a problem is in the sidebar, on every "
                      "screen. Fixed and Closed both take a report off "
                      "this list; nothing open is ever thrown away.",
                 bg=ui.PANE, fg=ui.FAINT, font=(ui.UI, 8),
                 wraplength=CW - 190, justify="left").place(x=PAD, y=612)
        ui.Button(self.sheet, "Open problems.md", self._open_digest, w=170,
                  h=30, quiet=True, bg=ui.PANE,
                  icon=ui.ICON["page"]).place(x=PAD + CW - 170, y=608)
        self._problems_stamp = None
        self._questions_stamp = None
        # Opening the tab is the cue: the weekly read wants problems.md
        # current, and this is the moment it is known to be looked at.
        self._write_digest()
        # The branches are git, and git is a process spawn per question —
        # so they are asked for off this thread when the tab opens, and
        # again after a push. Never on the poll: five spawns a second for
        # a list that changes once a week.
        self._scan_weekly()
        self._fill_problems()

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

    def _fill_problems(self) -> None:
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
        weekly = self._weekly or []
        head = self.parts["problems_head"]
        asking = self.parts["questions_head"]
        head.config(text=f"{summary.get('open', 0)} open   ·   "
                         f"{summary.get('fixed', 0)} fixed   ·   "
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
        scroller.clear()
        self._q_fields = {}
        self._push_buttons = {}
        empty = self.parts["problems_empty"]
        empty.place_forget()
        if module is None:
            empty.config(text="problems.py is not here, so nothing can be "
                              "reported or read back.")
            empty.place(x=PAD + CW / 2, y=300, anchor="center")
        elif not waiting and not done and not asked and not weekly:
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
        if weekly:
            self._weekly_block(scroller, weekly)
        for item in waiting:
            self._problem_row(scroller, module, item, open_=True)
            self._question_block(scroller, qmodule,
                                 homed.get(str(item.get("id", "")), []), "")
        if done:
            tk.Label(scroller.inner, text="ANSWERED", bg=ui.PANE,
                     fg=ui.FAINT, font=(ui.MEDIUM, 8)).pack(
                anchor="w", pady=(8 if waiting else 0, 6))
        for item in done:
            self._problem_row(scroller, module, item, open_=False)
            self._question_block(scroller, qmodule,
                                 homed.get(str(item.get("id", "")), []), "")
        scroller.to_top()
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
            png = module.thumb(APP_DIR, item)
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
        """
        text = str(item.get("text") or "")
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
        bottom = 32 + text_h + (heard_h + 8 if heard is not None else 0)
        height = max(84, bottom + (46 if open_ else 30))
        if shot is not None:
            height = max(height, shot.height() + 26)
        row = tk.Canvas(scroller.inner, width=CW, height=height, bg=ui.PANE,
                        highlightthickness=0, bd=0)
        row.pack(pady=(0, 8))
        row.create_image(0, 0, anchor="nw", image=ui.rounded(
            CW, height, 12, ui.CARD, ui.PANE,
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
        row.create_text(left, 13, anchor="nw", font=(ui.MEDIUM, 8),
                        fill=ui.AMBER if open_ else ui.FAINT,
                        text="  ·  ".join(p for p in (kind.upper(),
                                                      where.upper()) if p))
        row.create_image(left, 30, anchor="nw", image=photo)
        if heard is not None:
            # Flush right of the TEXT COLUMN, not of the row: with a
            # thumbnail in the corner those are no longer the same edge,
            # and anchoring to the row's would lay a short report's
            # evidence line straight across the picture.
            row.create_image(edge - shot_w, 32 + text_h, anchor="ne",
                             image=heard)
        if open_:
            ident = str(item.get("id", ""))
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
            row.create_text(14, height - 24, anchor="nw", font=(ui.UI, 8),
                            fill=ui.GREEN if status == module.FIXED
                            else ui.FAINT,
                            text=status + (f"  ·  {by}" if by else ""))
        scroller.bind_wheel(row)

    def _problem_decide(self, ident: str, status: str) -> None:
        """Fixed or Closed on a row, written to problems.json here.

        `by` is why resolve() takes the argument at all: a report can be
        answered from this window or from wherever else the store grows a
        surface, and the digest says which.
        """
        store = self._problems_store()
        if store is None:
            self._note("problems.py is not here")
            return
        try:
            saved = store.resolve(ident, status, by="dashboard")
        except Exception as e:            # noqa: BLE001
            self._note(f"could not save that: {e}")
            return
        self._note(f"marked {status}" if saved
                   else "that one is not in the list any more")
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
        block = tk.Frame(scroller.inner, bg=ui.PANE)
        block.pack(anchor="w", fill="x", pady=(0, 0))
        if header:
            tk.Label(block, text=header, bg=ui.PANE, fg=ui.ACCENT_TEXT,
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

        row = tk.Canvas(parent, width=width, height=height, bg=ui.PANE,
                        highlightthickness=0, bd=0)
        row.pack(anchor="w", padx=(Q_INDENT, 0), pady=(0, 8))
        # The accent edge is what says this card is not another report:
        # the reports around it are hairlined, and this one is the app
        # asking rather than him telling.
        row.create_image(0, 0, anchor="nw", image=ui.rounded(
            width, height, 12, ui.CARD, ui.PANE, ui.ACCENT_EDGE))
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

    # ------------------------------------------- the routine's own branches

    def _scan_weekly(self) -> None:
        """Ask git what the routine has left behind, off the Tk thread.

        Five spawns a branch, and a spawn is milliseconds this window may
        not spend: the Version screen froze solid asking git the same
        kind of question on the UI thread, which is the measurement in
        versions.py. The answer arrives through _events like every other
        off-thread reply.
        """
        if self._weekly_scanning:
            return
        self._weekly_scanning = True

        def work() -> None:
            try:
                rows = weekly_branches()
            except Exception:             # noqa: BLE001 — never a traceback
                rows = []                 #                out of a thread
            self._events.put(lambda r=rows: self._weekly_arrived(r))

        threading.Thread(target=work, daemon=True,
                         name="weekly-scan").start()

    def _weekly_arrived(self, rows: list[dict]) -> None:
        self._weekly_scanning = False
        self._weekly = rows
        if self.screen == "Problems":
            self._fill_problems()

    def _weekly_block(self, scroller: ui.Scroller,
                      rows: list[dict]) -> None:
        """The branches the routine committed to and never pushed.

        Above the reports, because a branch sitting here is work that is
        already DONE and that nobody has looked at — and in a frame, for
        the reason the questions are in one.
        """
        block = tk.Frame(scroller.inner, bg=ui.PANE)
        block.pack(anchor="w", fill="x", pady=(0, 2))
        tk.Label(block, text="THE ROUTINE'S WORK — READ IT, THEN PUSH",
                 bg=ui.PANE, fg=ui.FAINT, font=(ui.MEDIUM, 8)).pack(
            anchor="w", pady=(0, 6))
        for info in rows:
            self._weekly_row(block, scroller, info)

    def _weekly_row(self, parent, scroller: ui.Scroller,
                    info: dict) -> None:
        """One branch, and everything he needs to decide before he
        presses: which branch, how many commits, which files, what the
        last one said, and what the last press did.

        A button that pushes an unknown quantity is not reviewable, which
        is why the file list is on the card and not in a log.
        """
        branch = str(info.get("branch", ""))
        commits = int(info.get("commits") or 0)
        files = [str(f) for f in (info.get("files") or [])]
        inner = CW - 2 * Q_PAD
        subject, sub_h = None, 0
        if info.get("subject"):
            subject, sub_h, _l = ui.draw_text(str(info["subject"]), pt=9,
                                              width=inner - 118, max_lines=2,
                                              colour=ui.DIM, bg=ui.CARD)
        listed, name_lines = "", 0
        if files:
            shown = "   ·   ".join(files[:8])
            if len(files) > 8:
                shown += f"   ·   +{len(files) - 8} more"
            listed, name_lines = ui.clamp(shown, ui.UI, 8, inner, 2)
        said = str(self._push_said.get(branch, ""))
        note, note_h = None, 0
        if said:
            note, note_h, _l = ui.draw_text(said, pt=8, width=inner,
                                            max_lines=3, colour=ui.AMBER,
                                            bg=ui.CARD)
        # 50, not 38: the facts line is drawn at 31 in an 8 pt face, and
        # a subject starting at 38 lay straight across it.
        y = 50
        y_subject = y
        y += sub_h + (6 if subject is not None else 0)
        y_files = y
        y += name_lines * 14 + (6 if name_lines else 0)
        y_note = y
        y += note_h + (6 if note is not None else 0)
        height = max(74, y + 8)

        row = tk.Canvas(parent, width=CW, height=height, bg=ui.PANE,
                        highlightthickness=0, bd=0)
        row.pack(anchor="w", pady=(0, 8))
        row.create_image(0, 0, anchor="nw", image=ui.rounded(
            CW, height, 12, ui.CARD, ui.PANE, ui.TILE_EDGE))
        row.keep = [subject, note]
        row.create_text(Q_PAD, 13, anchor="nw", font=(ui.MEDIUM, 10),
                        fill=ui.FG, text=branch)
        facts = [f"{commits} commit" + ("" if commits == 1 else "s"),
                 f"{len(files)} file" + ("" if len(files) == 1 else "s"),
                 f"on GitHub as origin/{branch}" if info.get("on_origin")
                 else "not on GitHub yet"]
        if not info.get("trunk"):
            # Nothing to compare against, so the counts above are zeros
            # and saying so beats letting him read them as "empty".
            facts.append(f"no {TRUNK} in this repo to measure against")
        row.create_text(Q_PAD, 31, anchor="nw", font=(ui.UI, 8),
                        fill=ui.FAINT, text="   ·   ".join(facts))
        if subject is not None:
            row.create_image(Q_PAD, y_subject, anchor="nw", image=subject)
        if name_lines:
            row.create_text(Q_PAD, y_files, anchor="nw", font=(ui.UI, 8),
                            fill=ui.FAINT, justify="left", text=listed)
        if note is not None:
            row.create_image(Q_PAD, y_note, anchor="nw", image=note)
        push = ui.Button(row, "Push", lambda b=branch: self._push_branch(b),
                         w=96, h=30, primary=True, bg=ui.CARD,
                         icon=ui.ICON["link"])
        row.create_window(CW - Q_PAD, 13, anchor="ne", window=push)
        self._push_buttons[branch] = push
        if self._pushing is not None:
            # One push at a time: the second press would be racing the
            # first for the same two refs.
            push.enable(False)
        scroller.bind_wheel(row)

    def _push_branch(self, branch: str) -> None:
        """His button, entirely off the Tk thread.

        A push is his connection and a fetch is somebody's server — tens
        of seconds in the worst case, none of it allowed near the event
        loop, exactly like the version switch. What it does and why it
        may refuse is in push_weekly.
        """
        if self._pushing is not None:
            return
        self._pushing = branch
        self._push_said[branch] = (f"pushing {branch} — the branch first, so "
                                   f"the work is safe off this machine, then "
                                   f"{TRUNK} if it is clean…")
        self._note(f"pushing {branch}…")

        def work() -> None:
            try:
                result = push_weekly(branch)
            except Exception as e:        # noqa: BLE001 — a failure is a
                result = {"pushed": False, "merged": False,    # sentence,
                          "said": f"could not push {branch}: {e}"}
            self._events.put(lambda r=result: self._push_done(branch, r))

        threading.Thread(target=work, daemon=True,
                         name="weekly-push").start()
        self._fill_problems()             # the row says it is going

    def _push_done(self, branch: str, result: dict) -> None:
        self._pushing = None
        self._push_said[branch] = str(result.get("said") or "")
        self._note(self._push_said[branch])
        # The facts moved — the branch is on origin now, and `fast` may
        # have it — so they are asked for again rather than patched.
        self._scan_weekly()
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
            wavs = sorted((APP_DIR / "recent").glob("*.wav"),
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
            png = module.thumb(APP_DIR, name)
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
            pcfg = getattr(config_mod.load(CONFIG_PATH), "problems", None)
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
            cfg = config_mod.load(CONFIG_PATH)
        except Exception:                 # noqa: BLE001 — env is a bonus
            cfg = None
        try:
            item = module.record(APP_DIR, {"where": where, "kind": kind,
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

    def _screen_awake(self) -> None:
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
        self._title("Awake", "the computer never sleeps; the screens can")
        p = self.parts
        hero = ui.Card(self.sheet, CW, 148, pad=18)
        hero.place(x=PAD, y=68)
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

        strip = ui.Card(self.sheet, CW, 76, pad=18)
        strip.place(x=PAD, y=228)
        p["awake_screen"] = ui.Button(strip.body, "Screens off again",
                                      lambda: self._screens("again"), w=156,
                                      icon=ui.ICON["power"])
        p["awake_screen"].place(x=0, y=2)
        p["awake_check"] = ui.Button(strip.body, "Check status",
                                     self._awake_check, w=132, quiet=True,
                                     icon=ui.ICON["check"])
        p["awake_check"].place(x=168, y=2)
        p["awake_checked"] = tk.Label(strip.body, text="", bg=ui.CARD,
                                      fg=ui.FAINT, font=(ui.UI, 8),
                                      anchor="e")
        p["awake_checked"].place(x=CW - 36, y=12, anchor="ne")

        card = ui.Card(self.sheet, CW, 310, pad=18)
        card.place(x=PAD, y=316)
        tk.Label(card.body, text="WILL IT STILL BE THERE WHEN YOU ARE AWAY",
                 bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8)).place(x=0, y=0)
        p["awake_rows"] = tk.Frame(card.body, bg=ui.CARD, width=CW - 36,
                                   height=254)
        p["awake_rows"].place(x=0, y=22)
        p["awake_rows"].pack_propagate(False)
        self._awake_shape = None
        self._paint_awake_rows()
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
        return notify_mod.Store(APP_DIR / notify_mod.STORE_NAME)

    def _notify_stat(self):
        try:
            st = os.stat(APP_DIR / "notify.json")
            return (st.st_size, st.st_mtime_ns)
        except OSError:
            return None

    def _screen_notify(self) -> None:
        """What arrived from Claude — or anything else that knocked on
        /notify — and whether it has been seen. notify.py.

        Three cards, the Awake screen's shape. The hero is the count that
        matters (UNREAD in amber, ALL SEEN in green) with the newest one's
        source, title and age, and the one button that changes anything:
        Dismiss all, which marks everything seen and takes the whole
        column down — the × on a card answers only the card it is on.
        A strip under it sends a test notification through the running
        app and opens notify.log; the list below is the last thirty from
        notify.json, unseen ones edged brighter.

        Dismiss and Send a test go through the RUNNING APP: the card, the
        cue and the reminders live in the process with the hotkey in it,
        not in this window, so with nothing running both are disabled and
        the hint says why. The list does not need the app — it reads the
        file — so it works either way, and follows the file while the
        screen is open.
        """
        self._title("Notify", "when Claude — or anything — finishes")
        p = self.parts
        hero = ui.Card(self.sheet, CW, 148, pad=18)
        hero.place(x=PAD, y=68)
        body, inner = hero.body, CW - 36
        p["notify_bar"] = tk.Label(body, bg=ui.CARD)
        p["notify_bar"].place(x=-4, y=0)
        p["notify_glyph"] = tk.Label(body, text=ui.ICON["notify"],
                                     bg=ui.CARD, fg=ui.FAINT,
                                     font=(ui.ICONS, 22))
        p["notify_glyph"].place(x=6, y=2)
        p["notify_state"] = tk.Label(body, text="", bg=ui.CARD, fg=ui.FG,
                                     font=(ui.DISPLAY, 19, "bold"))
        p["notify_state"].place(x=56, y=1)
        p["notify_meta"] = tk.Label(body, text="", bg=ui.CARD, fg=ui.DIM,
                                    font=(ui.UI, 9), anchor="w")
        p["notify_meta"].place(x=57, y=44)
        p["notify_hint"] = tk.Label(body, text="", bg=ui.CARD, fg=ui.FAINT,
                                    font=(ui.UI, 8), justify="left",
                                    anchor="w")
        p["notify_hint"].place(x=57, y=68)
        p["notify_dismiss"] = ui.Button(body, "Dismiss all",
                                        lambda: self._notify("dismiss"),
                                        w=164, primary=True,
                                        icon=ui.ICON["check"])
        p["notify_dismiss"].place(x=inner, y=0, anchor="ne")

        strip = ui.Card(self.sheet, CW, 76, pad=18)
        strip.place(x=PAD, y=228)
        p["notify_test"] = ui.Button(strip.body, "Send a test",
                                     lambda: self._notify("test"), w=140,
                                     icon=ui.ICON["play"])
        p["notify_test"].place(x=0, y=2)
        p["notify_log"] = ui.Button(strip.body, "Open notify.log",
                                    self._notify_open_log, w=156, quiet=True,
                                    icon=ui.ICON["page"])
        p["notify_log"].place(x=152, y=2)
        p["notify_count"] = tk.Label(strip.body, text="", bg=ui.CARD,
                                     fg=ui.FAINT, font=(ui.UI, 8),
                                     anchor="e")
        p["notify_count"].place(x=CW - 36, y=12, anchor="ne")

        p["notify_list"] = ui.Scroller(self.sheet, CW + 10, 330)
        p["notify_list"].place(x=PAD, y=316)
        p["notify_empty"] = tk.Label(self.sheet, text="", bg=ui.PANE,
                                     fg=ui.FAINT, font=(ui.UI, 10))
        self._notify_stamp = None
        self._fill_notify()

    def _paint_notify(self) -> None:
        p = self.parts
        if "notify_state" not in p:
            return
        info = (self.status.get("notify") or {}) if self.running else {}
        enabled = bool(info.get("enabled"))
        try:
            unread = int(info.get("unread") or 0)
        except (TypeError, ValueError):
            unread = 0
        # A finish waiting for its session to go quiet is unread and NOT
        # on the screen (2026-09-05): counted apart, so the hero never
        # says "1 UNREAD" over an empty corner.
        try:
            held = min(unread, int(info.get("held") or 0))
        except (TypeError, ValueError):
            held = 0
        shown = unread - held
        last = info.get("last") or {}
        kind = str(last.get("kind") or "info")
        bits = [str(last.get("label") or last.get("source") or ""),
                str(last.get("title") or ""), ago(str(last.get("at", "")))]
        newest = "   ·   ".join(b for b in bits if b)
        if not self.running:
            colour, word = ui.FAINT, ui.FG
            state = "NOT RUNNING"
            meta = "the app puts the card up; start it first"
            hint = ("The cue, the card and the reminders live in the "
                    "running app — the process with the hotkey in it — so "
                    "start dictation first. The list below is the file, "
                    "and works without it.")
        elif "notify" not in self.status:
            # A running app that predates the door: its status has no
            # section at all. Not "off" — the file may well say enabled.
            colour, word = ui.DIM, ui.FG
            state = "NOT WIRED"
            meta = "the running app predates the notify door"
            hint = ("The app that is running has no /notify route and no "
                    "card. Stop it and start it again on this code.")
        elif not enabled:
            colour, word = ui.DIM, ui.FG
            state = "OFF"
            meta = "[notify] enabled = false"
            hint = ("The route answers 503 and nothing is shown, stored or "
                    "played. Turn it on in Settings and restart the app.")
        elif shown > 0:
            colour = ui.RED if kind == "error" else ui.AMBER
            word = colour
            state = f"{shown} UNREAD"
            meta = newest or "something is waiting"
            left = info.get("reminders_left") or 0
            if info.get("reminding"):
                hint = (f"Reminding: {left} more. Dismiss all marks "
                        "everything seen and takes the column down; so does "
                        "Esc over it or the dismiss key. The x on one card "
                        "answers just that one.")
            else:
                hint = ("Waiting quietly. Dismiss all marks everything seen "
                        "and takes the column down; so does Esc over it or "
                        "the dismiss key. The x on one card answers just "
                        "that one.")
            if held:
                hint = (f"{held} finish{'es' if held > 1 else ''} still "
                        "waiting for a session to go quiet. " + hint)
        elif held > 0:
            colour, word = ui.DIM, ui.FG
            state = f"{held} WAITING"
            meta = newest or "a finish, held"
            hint = ("A finish is held until the session that sent it has "
                    "been quiet for [notify] quiet_s seconds; if the session "
                    "speaks again first it is retired unseen. Nothing rings "
                    "for it.")
        else:
            colour, word = ui.GREEN, ui.FG
            state = "ALL SEEN"
            meta = newest or "nothing has arrived yet"
            hint = ("Anything that POSTs to /notify on the phone endpoint "
                    "lands here — Claude Code through its hooks, or a "
                    "program of your own. Send a test to hear the cue and "
                    "see the card; unread ones stack, newest on top.")
        p["notify_bar"].config(image=ui.rounded(4, 112, 2, colour, ui.CARD))
        p["notify_glyph"].config(fg=colour if unread and self.running
                                 else ui.FAINT)
        p["notify_state"].config(text=state, fg=word)
        p["notify_meta"].config(text=ui.clamp(meta, ui.UI, 9,
                                              CW - 36 - 57 - 172, 1)[0])
        p["notify_hint"].config(text=ui.clamp(hint, ui.UI, 8,
                                              CW - 36 - 57, 2)[0])
        p["notify_dismiss"].enable(self.running and enabled)
        p["notify_test"].enable(self.running and enabled)
        self._poll_notify()

    def _poll_notify(self) -> None:
        """Once a second from _refresh: redraw only when the file moved —
        an arrival in the app, a dismissal from its card or key."""
        if "notify_list" not in self.parts:
            return
        if self._notify_stat() != getattr(self, "_notify_stamp", None):
            self._fill_notify()

    def _fill_notify(self) -> None:
        if "notify_list" not in self.parts:
            return
        self._notify_stamp = self._notify_stat()
        items: list[dict] = []
        kept = 0
        try:
            store = self._notify_store()
            if store is not None:
                items = list(store.recent(30))
                try:
                    kept = len(store.items())
                except Exception:         # noqa: BLE001 — a store without it
                    kept = len(items)
        except Exception:                 # noqa: BLE001 — a broken file
            items, kept = [], 0
        unread = sum(1 for item in items if not item.get("seen"))
        self.parts["notify_count"].config(
            text=(f"{kept} kept   ·   {unread} unread" if kept
                  else "nothing kept yet"))
        scroller = self.parts["notify_list"]
        scroller.clear()
        empty = self.parts["notify_empty"]
        empty.place_forget()
        if not items:
            empty.config(text="Nothing has arrived yet — Send a test, or "
                              "let Claude finish something.")
            empty.place(x=PAD + CW / 2, y=460, anchor="center")
        for item in items:
            self._notify_row(scroller, item)
        scroller.to_top()

    def _notify_row(self, scroller: ui.Scroller, item: dict) -> None:
        """One notification, one canvas: time and day on the left, the
        title and the first two lines of the body flush right, and who
        sent it under them. Same layout rules as a review row — and the
        same rule about text: title, body and the source line all go
        through ui.draw_text (DrawTextW), because a title from Claude is
        Hebrew, English or both in one line, and a create_text scrambles
        the mixed case silently."""
        seen = bool(item.get("seen"))
        kind = str(item.get("kind") or "info")
        colour = {"done": ui.GREEN, "input": ui.AMBER, "error": ui.RED,
                  "info": ui.ACCENT}.get(kind, ui.ACCENT)
        left, edge = 106, CW - 14
        width = edge - left
        title = str(item.get("title") or "")
        body = str(item.get("body") or "")
        photo, text_h, _lines = ui.draw_text(
            title, pt=11, width=width, max_lines=1,
            colour=ui.FG if not seen else ui.DIM, bg=ui.CARD)
        more = None
        more_h = 0
        if body.strip():
            more, more_h, _l = ui.draw_text(body, pt=9, width=width,
                                            max_lines=2, colour=ui.FAINT,
                                            bg=ui.CARD)
        who = "   ·   ".join(
            s for s in (str(item.get("label") or item.get("source") or ""),
                        str(item.get("project") or "")) if s)
        note = None
        note_h = 0
        if who:
            note, note_h, _l = ui.draw_text(who, pt=8, width=width,
                                            max_lines=1, colour=ui.FAINT,
                                            bg=ui.CARD)
        height = 13 + text_h + (more_h + 4 if more is not None else 0) \
            + (note_h + 6 if note is not None else 0) + 12
        height = max(height, 60)
        row = tk.Canvas(scroller.inner, width=CW, height=height, bg=ui.PANE,
                        highlightthickness=0, bd=0)
        row.pack(pady=(0, 8))
        row.create_image(0, 0, anchor="nw", image=ui.rounded(
            CW, height, 12, ui.CARD, ui.PANE,
            ui.TILE_EDGE if not seen else ui.LINE))
        at = str(item.get("at", ""))
        row.create_text(14, 15, text=at[11:16], anchor="nw",
                        font=(ui.UI, 10, "bold"),
                        fill=ui.FG if not seen else ui.DIM)
        try:
            day = time.strftime("%d %b", time.strptime(at[:19],
                                                       "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            day = ""
        row.create_text(14, 34, text=day, anchor="nw", font=(ui.UI, 8),
                        fill=ui.FAINT)
        row.create_image(left - 18, 19, anchor="nw",
                         image=ui.rounded(8, 8, 4, colour, ui.CARD))
        row.create_image(left, 13, anchor="nw", image=photo)
        y = 13 + text_h + 4
        if more is not None:
            row.create_image(left, y, anchor="nw", image=more)
            y += more_h + 6
        if note is not None:
            row.create_image(edge, y, anchor="ne", image=note)
        scroller.bind_wheel(row)

    def _notify(self, do: str) -> None:
        """dismiss / test, through the running app."""
        self._busy_until = time.monotonic() + 1
        self._ask("notify", then=lambda r: self._notify_answered(r, do),
                  do=do)

    def _notify_answered(self, reply: dict | None, do: str) -> None:
        self._announce(reply, {"dismiss": "all marked seen",
                               "test": "test notification sent"}.get(do, do))
        # The reply carries the new state; paint it now rather than one
        # poll later, so Dismiss all is seen to do something at once. The
        # paint ends in _poll_notify, which refills the list if the file
        # moved — and a dismissal or a test always moves it.
        if reply and reply.get("ok") and isinstance(reply.get("notify"),
                                                    dict):
            self.status["notify"] = reply["notify"]
            self._paint_notify()
        else:
            self._fill_notify()

    def _notify_open_log(self) -> None:
        path = APP_DIR / "notify.log"
        if not path.exists():
            self._note("no notify.log yet — nothing has arrived")
        elif not launch.open_path(path):
            self._note(f"could not open {path.name}")

    def _screen_keys(self) -> None:
        """Every bindable key, in a column that scrolls.

        It scrolls because the arithmetic ran out. The window is a fixed
        940x648 (deliberately — every bitmap in it is cached against that
        size), the title takes the first 64 px, and three cards of 3, 4
        and 1 rows ended at y=640: eight pixels of headroom. Adding
        ask-the-screen made the fourth key of its group land at y=654 and
        the card below it start off the bottom of the window, where it was
        invisible with no way to reach it — which is exactly how it
        shipped, because the test only asserted the row EXISTED. A
        Scroller costs nothing while everything fits (it paints no thumb
        at all until it has to) and means the next key added is a one-line
        change again.
        """
        self._title("Keys", "click a key, then press the one you want")
        p = self.parts
        p["caps"] = {}
        named = {f for _title, fields in KEY_GROUPS for f in fields}
        labels = dict(config_mod.HOTKEY_FIELDS)
        groups = [(title, [f for f in fields if f in labels])
                  for title, fields in KEY_GROUPS]
        # Anything added to HOTKEY_FIELDS and not to KEY_GROUPS still has
        # to appear somewhere, or the one place a key is registered would
        # stop being the one place it shows up.
        extra = [f for f, _label in config_mod.HOTKEY_FIELDS
                 if f not in named]
        if extra:
            groups.append(("Other keys", extra))

        scroller = ui.Scroller(self.sheet, CW + 10, H - 64 - 24)
        scroller.place(x=PAD, y=64)
        p["keys_list"] = scroller
        for title, fields in groups:
            if not fields:
                continue
            card = ui.Card(scroller.inner, CW, 60 + len(fields) * 46,
                           pad=18)
            card.pack(anchor="w", pady=(0, 14))
            tk.Label(card.body, text=title.upper(), bg=ui.CARD, fg=ui.FAINT,
                     font=(ui.UI, 8)).place(x=0, y=0)
            row = 24
            for field in fields:
                what, how = split_label(labels[field])
                tk.Label(card.body, text=what, bg=ui.CARD, fg=ui.FG,
                         font=(ui.UI, 10)).place(x=0, y=row + 8)
                tk.Label(card.body, text=how, bg=ui.CARD, fg=ui.FAINT,
                         font=(ui.UI, 8)).place(x=CW - 36 - 162, y=row + 10)
                cap = ui.KeyCap(
                    card.body, "…",
                    lambda f=field, la=labels[field]: self._capture(f, la))
                cap.place(x=CW - 36 - 122, y=row)
                p["caps"][field] = cap
                row += 46
            scroller.bind_wheel(card)

    def _paint_keys(self) -> None:
        caps = self.parts.get("caps")
        if not caps:
            return
        keys = self.status.get("keys") or self._read_keys()
        for field, cap in caps.items():
            cap.set(pretty_key(keys.get(field, "")))

    # ----------------------------------------------------------- settings

    def _screen_settings(self) -> None:
        """Every line of config.toml, drawn from the file itself — behind
        tabs that say the common ones plainly.

        Nothing here is typed by hand except the words: settings.py reads
        the file, and settings.TABS says which lines get a plain label, a
        short sentence and a menu with names on it. Everything else is on
        the last tab, "Everything", with the comment from the file as its
        help, and the magnifier searches all of it. A test holds this
        screen and the Keys screen to covering the file between them, so
        a setting cannot drop off — it can only be said plainly or said
        in full. That is the owner's rule from both directions: "show all
        of them" the first time, "I do not need to know all of this" the
        second.

        Writes go through config.set_values, the line editor that keeps
        the comments, and through the running app when there is one, so
        config.toml has one writer at a time and the app can take the
        change live where it knows how (main.set_option).
        """
        self._title("Settings", "written back into config.toml, in place")
        p = self.parts
        try:
            sections = settings_mod.read(CONFIG_PATH)
        except Exception as e:
            card = ui.Card(self.sheet, CW, 96, pad=18)
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
        bar = tk.Frame(self.sheet, bg=ui.PANE, width=CW, height=36)
        bar.place(x=PAD, y=64)
        bar.pack_propagate(False)
        p["settings_bar"] = bar
        p["settings_list"] = ui.Scroller(self.sheet, CW + 10, H - 110 - 24)
        p["settings_list"].place(x=PAD, y=110)
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
            box = ui.Card(bar, CW, 36, radius=11, pad=9)
            box.pack()
            tk.Label(box.body, text=ui.ICON["search"], bg=ui.CARD,
                     fg=ui.FAINT, font=(ui.ICONS, 10)).place(x=0, y=1)
            entry = tk.Entry(box.body, bg=ui.CARD, fg=ui.FG, bd=0,
                             highlightthickness=0, font=(ui.UI, 10),
                             insertbackground=ui.ACCENT)
            entry.place(x=26, y=0, width=CW - 100, height=18)
            entry.insert(0, self._settings_query)
            entry.bind("<KeyRelease>",
                       lambda _e: self._settings_search_soon(entry.get()))
            entry.bind("<Escape>", lambda _e: self._settings_close_search())
            p["settings_search"] = entry
            p["settings_placeholder"] = tk.Label(
                box.body, text="a word from a setting's name or its "
                               "comment — Esc brings the tabs back",
                bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 9))
            if not self._settings_query:
                p["settings_placeholder"].place(x=26, y=1)
            entry.bind("<FocusIn>",
                       lambda _e: p["settings_placeholder"].place_forget())
            close = tk.Label(box.body, text="✕", bg=ui.CARD, fg=ui.DIM,
                             font=(ui.UI, 10), cursor="hand2")
            close.place(x=CW - 18 - 10, y=-1, anchor="ne")
            close.bind("<Button-1>", lambda _e: self._settings_close_search())
            close.bind("<Enter>", lambda _e: close.configure(fg=ui.FG))
            close.bind("<Leave>", lambda _e: close.configure(fg=ui.DIM))
            entry.focus_set()
            return
        p["settings_tabs"] = {}
        names = [tab.name for tab in settings_mod.TABS]
        names.append(settings_mod.EVERYTHING)
        for name in names:
            chip = ui.Chip(bar, name, lambda n=name: self._settings_go(n),
                           active=(name == self._settings_tab))
            chip.pack(side="left", padx=(0, 6), pady=3)
            p["settings_tabs"][name] = chip
        glass = tk.Label(bar, text=ui.ICON["search"], bg=ui.PANE, fg=ui.DIM,
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
        if scroller is None:
            return
        self._stop_rows()
        scroller.clear()
        p["rows"] = {}
        sections = p["sections"]
        elsewhere = _keys_screen_paths()
        builders: list = []
        everything = self._settings_tab == settings_mod.EVERYTHING
        if self._settings_searching or everything:
            query = self._settings_query if self._settings_searching else ""
            for section in sections:
                rows = [s for s in section.settings
                        if s.path not in elsewhere
                        and settings_mod.matches(s, query)]
                if not rows:
                    continue
                keys_here = [s for s in section.settings
                             if s.path in elsewhere]
                note = ("" if not keys_here or query else
                        f"\n{len(keys_here)} of its lines are keys — those "
                        "are on the Keys screen.")
                builders.append(lambda s=section, r=rows, n=note:
                                self._settings_card(scroller,
                                                    s.title.upper(),
                                                    s.help + n, r))
            if everything and not self._settings_searching:
                builders.append(lambda: self._files_card(scroller))
        else:
            tab = (settings_mod.tab_named(self._settings_tab)
                   or settings_mod.TABS[0])
            for group in tab.groups:
                pairs = [(row, s) for row in group.rows
                         if (s := settings_mod.find(sections, row.path))
                         is not None]
                if pairs:
                    builders.append(lambda g=group, pr=pairs:
                                    self._friendly_card(scroller, g.title,
                                                        pr))
        if not builders:
            card = ui.Card(scroller.inner, CW, 60, pad=18)
            card.pack(anchor="w", pady=(0, 14))
            tk.Label(card.body, text=f"nothing in config.toml matches "
                                     f"{self._settings_query!r}",
                     bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 9)).place(x=0, y=2)
            return
        self._settings_left = builders
        self._draw_settings()
        scroller.to_top()

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

    def _new_card(self, scroller, height: int):
        """A card drawn as canvas ITEMS rather than widgets.

        A hundred and forty rows of two or three Labels each is four
        hundred widgets, and Tk on Windows spent 2.2 s creating them —
        measured 2026-09-01, and it made the screen feel broken. A text
        item on the card's own canvas costs one Tcl call and no window.
        Only the controls are real widgets, put on the canvas with
        create_window, so the count is one per row rather than three.
        """
        card = tk.Canvas(scroller.inner, width=CW, height=height, bg=ui.PANE,
                         highlightthickness=0, bd=0)
        card.create_image(0, 0, anchor="nw",
                          image=ui.rounded(CW, height, 14, ui.CARD, ui.PANE,
                                           ui.LINE))
        card.pack(anchor="w", pady=(0, 14))
        return card

    def _friendly_help(self, row) -> tuple[str, int]:
        if not row.help:
            return "", 0
        return ui.clamp(row.help, ui.UI, 8, CW - 36 - CONTROL_W - 12, 2)

    def _friendly_card(self, scroller, title: str, pairs) -> None:
        heights = [22 + self._friendly_help(row)[1] * 15 + 8
                   for row, _setting in pairs]
        y = 18 if title else 8
        card = self._new_card(scroller, y + 18 * bool(title) + sum(heights)
                              + (6 if title else 10))
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

    def _row_help(self, setting) -> tuple[str, int]:
        text = setting.help.replace("\n", " ")
        if not text:
            return "", 0
        return ui.clamp(text, ui.UI, 8, CW - 36 - CONTROL_W - 12, 3)

    def _settings_card(self, scroller, title: str, help_text: str,
                       rows) -> None:
        """A section of the file as it is written: the key, its comment,
        and the one control its kind calls for."""
        shown, lines = ("", 0)
        if help_text:
            shown, lines = ui.clamp(help_text.replace("\n", " "), ui.UI, 8,
                                    CW - 36, 4)
        heights = [22 + self._row_help(s)[1] * 15 + 8 for s in rows]
        card = self._new_card(scroller, 28 + (lines * 15 + 8 if lines else 0)
                              + sum(heights) + 6)
        y = 18
        card.create_text(18, y, text=title, anchor="nw", fill=ui.FAINT,
                         font=(ui.UI, 8))
        y += 18
        if lines:
            card.create_text(18, y, text=shown, anchor="nw", fill=ui.DIM,
                             font=(ui.UI, 8))
            y += lines * 15 + 8
        for setting, height in zip(rows, heights):
            card.create_text(18, y, text=setting.key, anchor="nw",
                             fill=ui.FG, font=(ui.UI, 10))
            text, lines = self._row_help(setting)
            if lines:
                card.create_text(18, y + 21, text=text, anchor="nw",
                                 fill=ui.FAINT, font=(ui.UI, 8))
            self._control(card, y, setting, self._menu_for(None, setting))
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
        if setting.kind == "bool":
            switch = ui.Switch(card, bool(value),
                               command=lambda v, s=setting:
                               self._apply_setting(s, v), bg=ui.CARD)
            card.create_window(right, y + 1, window=switch, anchor="ne")
            self._register_row(setting, "switch", switch)
        elif not setting.editable:
            button = ui.Button(card, "In the file",
                               lambda: launch.open_path(CONFIG_PATH),
                               w=104, h=30, quiet=True,
                               icon=ui.ICON["settings"])
            card.create_window(right, y - 2, window=button, anchor="ne")
            self._register_row(setting, "file", button)
        elif options:
            menu = ui.Dropdown(card, options, value,
                               command=lambda v, s=setting:
                               self._apply_setting(s, v),
                               bg=ui.CARD, w=CONTROL_W)
            card.create_window(right, y - 2, window=menu, anchor="ne")
            self._register_row(setting, "dropdown", menu)
        else:
            entry = tk.Entry(card, bg=ui.EDGE, fg=ui.FG, bd=0,
                             highlightthickness=1,
                             highlightbackground=ui.STROKE,
                             highlightcolor=ui.ACCENT,
                             insertbackground=ui.ACCENT, font=(ui.UI, 10),
                             justify="right", disabledbackground=ui.EDGE,
                             readonlybackground=ui.EDGE)
            card.create_window(right, y, window=entry, anchor="ne",
                               width=ENTRY_W, height=26)
            entry.insert(0, _shown(value))
            entry.bind("<Return>", lambda _e, s=setting, w=entry:
                       self._entry_done(s, w))
            entry.bind("<FocusOut>", lambda _e, s=setting, w=entry:
                       self._entry_done(s, w))
            self._register_row(setting, "entry", entry)

    def _register_row(self, setting, kind: str, widget) -> None:
        self.parts["rows"].setdefault(setting.path, []).append((kind, widget))

    def _files_card(self, scroller) -> None:
        # Named for what they ARE, not what they are called on disk — the
        # filename is the small print. "What is transcripts.log" was a
        # question this screen used to make the owner ask.
        openers = (
            ("file", "Everything you said",
             "transcripts.log — every dictation, translation and lookup",
             APP_DIR / "transcripts.log"),
            ("page", "The app's diary",
             "app.log — what it did and why, for when something looks off",
             APP_DIR / "app.log"),
            ("settings", "The settings file",
             "config.toml — every knob, its measurements kept as comments",
             CONFIG_PATH),
            ("folder", "The app's folder",
             str(APP_DIR),
             APP_DIR),
        )
        files = ui.Card(scroller.inner, CW, 60 + len(openers) * 44, pad=18)
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
            config_mod.set_values(CONFIG_PATH, {setting.path: value})
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
                    widget.delete(0, "end")
                    widget.insert(0, _shown(value))
            except tk.TclError:
                pass

    def _paint_settings(self) -> None:
        """The one value the running app can change on its own: the
        fullscreen auto-pause, which its status reports."""
        p = self.parts
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
        placeholder = self.parts.get("settings_placeholder")
        if placeholder is not None:
            if text:
                placeholder.place_forget()
            elif self.parts.get("settings_search") is not self.root.focus_get():
                placeholder.place(x=26, y=1)
        self._fill_settings()

    # ------------------------------------------------------------- version

    def _warm_versions(self) -> None:
        """Fill the branch caches before anyone clicks Version.

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
            versions_mod.known_versions()
        except Exception:
            return
        self._events.put(lambda: setattr(self, "branch", here))

    def _screen_version(self) -> None:
        """Which whole-app version is running, and the one-click way to
        change it. Versions are git branches of this very folder;
        versions.py owns the mechanics (stop the instance, carry
        config.toml across untouched, flip the branch, restart). This
        screen is its face.

        Every card here is sized from its text. The first version placed
        a three-line description in a card built for two, and the third
        line was clipped mid-glyph by the card's own edge — which read as
        garbage, and the owner said so."""
        self._title("Version", "two whole apps in one folder")
        p = self.parts

        try:
            import versions as versions_mod
            here = self.branch if self.branch != "?" \
                else versions_mod.current_branch()
            known = versions_mod.known_versions()
            registry = versions_mod.VERSIONS
        except Exception as e:
            # No git must not blank the screen: say what is missing where
            # the version would have been.
            card = ui.Card(self.sheet, CW, 96, pad=18)
            card.place(x=PAD, y=64)
            tk.Label(card.body, text="VERSIONS UNAVAILABLE", bg=ui.CARD,
                     fg=ui.FAINT, font=(ui.UI, 8)).place(x=0, y=0)
            tk.Label(card.body, text=str(e)[:300], bg=ui.CARD, fg=ui.DIM,
                     font=(ui.UI, 9), wraplength=CW - 72,
                     justify="left").place(x=0, y=24)
            return

        info = registry.get(here, {"label": here, "desc": ""})
        desc, desc_lines = ("", 0)
        if info["desc"]:
            desc, desc_lines = ui.clamp(info["desc"], ui.UI, 8, CW - 36, 4)
        # The card's body is 36 px shorter than the card (pad=18 top and
        # bottom), and the description starts 66 px into the body.
        now_h = 36 + 66 + desc_lines * 15 + 8
        now = ui.Card(self.sheet, CW, now_h, pad=18)
        now.place(x=PAD, y=64)
        tk.Label(now.body, text="RUNNING NOW", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=0, y=0)
        tk.Label(now.body, text=info["label"], bg=ui.CARD,
                 fg=ui.ACCENT_TEXT,
                 font=(ui.DISPLAY, 19, "bold")).place(x=0, y=16)
        tk.Label(now.body, text=f"branch '{here}'", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=0, y=48)
        if desc_lines:
            tk.Label(now.body, text=desc, bg=ui.CARD, fg=ui.DIM,
                     font=(ui.UI, 8), justify="left",
                     anchor="nw").place(x=0, y=66)

        others = [n for n in known if n != here]
        blurbs = {}
        for name in others:
            oinfo = registry.get(name, {"label": name, "desc": ""})
            blurbs[name] = (ui.clamp(oinfo["desc"], ui.UI, 8, CW - 210, 3)
                            if oinfo["desc"] else ("", 0))
        footer_text = ("switching stops the app, flips the folder and starts "
                       "it again (~25 s of model loading). your settings "
                       "come across untouched; a switch refuses while any "
                       "file other than config.toml has uncommitted "
                       "changes.")
        footer, footer_lines = ui.clamp(footer_text, ui.UI, 8, CW - 36, 3)
        rows_h = sum(30 + blurbs[n][1] * 15 + 10 for n in others) or 24
        # 26 px of title, the rows, a status line, the footer, and the
        # card's own 36 px of padding around all of it.
        card_h = 36 + 26 + rows_h + 24 + footer_lines * 15 + 12
        card = ui.Card(self.sheet, CW, card_h, pad=18)
        card.place(x=PAD, y=64 + now_h + 12)
        tk.Label(card.body, text="SWITCH TO", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=0, y=0)
        row = 26
        for name in others:
            oinfo = registry.get(name, {"label": name, "desc": ""})
            blurb, lines = blurbs[name]
            tk.Label(card.body, text=ui.ICON["version"], bg=ui.CARD,
                     fg=ui.ACCENT, font=(ui.ICONS, 11)).place(x=0, y=row + 7)
            tk.Label(card.body, text=f"{oinfo['label']}  ({name})",
                     bg=ui.CARD, fg=ui.FG,
                     font=(ui.UI, 10)).place(x=26, y=row + 1)
            if lines:
                tk.Label(card.body, text=blurb, bg=ui.CARD, fg=ui.FAINT,
                         font=(ui.UI, 8), justify="left",
                         anchor="nw").place(x=26, y=row + 21)
            btn = ui.Button(card.body, "Use this",
                            lambda t=name: self._use_version(t),
                            w=96, h=32, quiet=True, icon=ui.ICON["play"])
            btn.place(x=CW - 36 - 96, y=row + 6)
            p[f"use_{name}"] = btn
            row += 30 + lines * 15 + 10
        if not others:
            tk.Label(card.body, text="no other version exists on this "
                                     "machine — see versions.py",
                     bg=ui.CARD, fg=ui.FAINT,
                     font=(ui.UI, 9)).place(x=0, y=row)
            row += 24

        p["ver_status"] = tk.Label(card.body, text="", bg=ui.CARD,
                                   fg=ui.AMBER, font=(ui.UI, 8),
                                   wraplength=CW - 36, justify="left")
        p["ver_status"].place(x=0, y=row + 4)
        tk.Label(card.body, text=footer, bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8), justify="left",
                 anchor="nw").place(x=0, y=row + 24)

    def _use_version(self, target: str) -> None:
        """Switch whole-app version, entirely off the Tk thread.

        versions.switch stops the running instance, waits for it to exit,
        flips the branch and restarts it — tens of seconds, all of it
        blocking, none of it allowed near the UI loop. The poller keeps
        asking its question throughout and watches the app vanish and come
        back on its own; completion arrives through _events like every
        other off-thread answer.
        """
        if self._switching:
            return
        try:
            import versions as versions_mod
        except Exception as e:
            self._note(f"cannot switch: {e}")
            return

        self._switching = True
        for key, widget in list(self.parts.items()):
            if key.startswith("use_"):
                widget.enable(False)
        if "ver_status" in self.parts:
            self.parts["ver_status"].config(
                text=f"switching to {target} — stopping, flipping, "
                     "restarting…")

        def work() -> None:
            error: str | None = None
            try:
                versions_mod.switch(target)
            except Exception as e:      # SwitchError, git failures, timeouts
                error = str(e)
            self._events.put(
                lambda: self._switch_done(target, error))

        threading.Thread(target=work, daemon=True,
                         name="version-switch").start()

    def _switch_done(self, target: str, error: str | None) -> None:
        self._switching = False
        if error:
            if "ver_status" in self.parts:
                self.parts["ver_status"].config(
                    text=f"NOT switched — {error}")
            for key, widget in list(self.parts.items()):
                if key.startswith("use_"):
                    widget.enable(True)
            return
        self.branch = target
        self._note(f"now running {target}")
        # Rebuild the screen rather than patching it: the running-version
        # card and the rows under it are laid out from who IS current.
        if self.screen == "Version":
            self._show("Version")

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
            if stamp != self._log_stamp:
                self._log_stamp = stamp
                events = history.load(HISTORY_ROWS)
                self._events.put(lambda e=events: self._log_arrived(e))
            self._events.put(lambda r=reply: self._refresh(r))
            time.sleep(POLL_MS / 1000)

    def _log_arrived(self, events: list[history.Event]) -> None:
        self.log = events
        if self.screen == "History":
            self._fill_history()
        elif self.screen == "Overview":
            self._paint_overview()

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
        self._busy_until = time.monotonic() + 1.5
        # The named event, not the pipe: this has to work even if the
        # control channel never came up.
        if singleton.request_quit():
            self._note("stopping — models unload, so starting again takes "
                       "about 25 seconds")
        else:
            self._note("nothing to stop")

    def _toggle_pause(self) -> None:
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
            current = config_mod.load(CONFIG_PATH)
            # with_field, not a bare replace: most keys live at the top
            # level, but some (visual_qa_hotkey, and both capture keys)
            # are nested in their section, and replace() cannot assign
            # through that. One helper, both this window and main.rebind.
            config_mod.check_hotkeys(config_mod.with_field(current, field,
                                                           key))
            write_key = NESTED_HOTKEYS.get(field, field)
            config_mod.set_values(CONFIG_PATH, {write_key: key})
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
            cfg = config_mod.load(CONFIG_PATH)
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
        return LOOKS.get(activity, LOOKS["ready"])

    def _breathe(self) -> None:
        """The status lamp, breathing.

        Ninety milliseconds a frame, and the glow is quantised inside
        ui.lamp, so a whole breath is a dozen cached bitmaps being swapped
        onto two Labels — no drawing happens per frame. The rhythm carries
        the meaning: quick and bright while RECORDING (the state that
        costs something if missed), slower while transcribing, a long calm
        swell while merely listening, and perfectly still when there is
        nothing to breathe about.
        """
        if self.closing:
            return
        colour, _word = LOOKS.get(self._activity, LOOKS["ready"])
        rhythm = {"recording": (1.2, 0.30, 0.85), "locked": (1.2, 0.30, 0.85),
                  "busy": (1.9, 0.28, 0.68), "ready": (3.6, 0.34, 0.54)}
        beat = rhythm.get(self._activity)
        if beat is None:
            glow = 0.45
        else:
            period, low, high = beat
            wave = 0.5 + 0.5 * math.sin(
                time.monotonic() * 2 * math.pi / period)
            glow = low + (high - low) * wave
        try:
            self.parts["lamp"].config(
                image=ui.lamp(26, colour, ui.SIDE_CARD, glow))
            hero = self.parts.get("hero_lamp")
            if hero is not None and hero.winfo_exists():
                hero.config(image=ui.lamp(46, colour, ui.CARD, glow))
        except tk.TclError:
            pass                      # a screen swap mid-frame: skip one
        self._breath_after = self.root.after(90, self._breathe)

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

        _colour, word = self._look()
        self.parts["state"].config(text=word)
        uptime = self.status.get("uptime_s")
        self.parts["uptime"].config(
            text=f"up {human_time(uptime)}" if uptime else "not running")
        keys = self.status.get("keys") or self._read_keys()
        dictate = pretty_key(keys.get("hotkey", ""))
        self.parts["hint"].config(text=f"hold {dictate}" if dictate != "off"
                                  else "no dictation key set")

        {"Overview": self._paint_overview, "History": lambda: None,
         "Review": self._poll_review,
         "Awake": self._paint_awake,
         "Notify": self._paint_notify,
         "Keys": self._paint_keys,
         "Version": lambda: None,
         "Problems": self._poll_problems,
         "Settings": self._paint_settings}[self.screen]()

    # ------------------------------------------------------------ shutdown

    def _close(self) -> None:
        # Closing this window must never stop dictation — it is a remote
        # control, not the app. It must not leave it PAUSED either, which
        # is what closing it on top of an open key dialog used to do.
        self.closing = True
        self._resume_after_capture()
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
        # Two survivors, and only two. The poller and the reopen watcher
        # are daemon threads that notice they should stop by reading
        # self.closing, and they post into self._events on their way out;
        # take those away and they die on an AttributeError instead of
        # ending. Neither a bool nor an empty queue holds a widget, so
        # the tree is still unreachable and the collect below still frees
        # the interpreter.
        keep = {"closing": True, "_events": queue.Queue(), "_looping": False}
        self.__dict__.clear()
        self.__dict__.update(keep)
        gc.collect()

    def run(self) -> None:
        self._looping = True
        try:
            self.root.mainloop()
        finally:
            self._looping = False
            self._bury()


def main() -> int:
    """One window, however many times the shortcut is clicked.

    A .vbs behind a shortcut has no notion of "already open", so every
    double-click used to start another Python process and put another
    identical window on screen — each polling the same app, each able to
    change the same keys. Nothing broke, but the thing looked broken.

    A second launch signals the first and exits, so clicking the icon
    behaves the way clicking a taskbar button does: it brings the window
    you already have to the front.
    """
    try:
        lock = singleton.InstanceLock(singleton.DASHBOARD_MUTEX)
    except singleton.AlreadyRunning:
        singleton.signal(singleton.DASHBOARD_SHOW)
        return 0
    try:
        Dashboard().run()
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
