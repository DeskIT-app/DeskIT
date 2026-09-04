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
       ("keys", "Keys"), ("version", "Version"), ("settings", "Settings"))

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
    ("The app itself", ("pause_hotkey", "screens_hotkey", "dismiss_hotkey")),
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
            (4, "Hebrew Dictation"),                    # ...DisplayName
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
        self.root.title("Hebrew Dictation")
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
        tk.Label(bar, text="Hebrew Dictation", bg=ui.BG, fg=ui.FG,
                 font=(ui.UI, 10, "bold")).place(x=62, y=23)
        self.parts["hint"] = tk.Label(bar, text="", bg=ui.BG, fg=ui.FAINT,
                                      font=(ui.UI, 8))
        self.parts["hint"].place(x=62, y=42)

        self.nav: dict[str, tuple] = {}
        y = 92
        for key, name in NAV:
            item = tk.Canvas(bar, width=188, height=42, bg=ui.BG,
                             highlightthickness=0, bd=0, cursor="hand2")
            item.place(x=12, y=y)
            faces = (ui.rounded(188, 42, 11, ui.ACCENT_SOFT, ui.BG, ui.ACCENT_EDGE),
                     ui.rounded(188, 42, 11, ui.BG, ui.BG),
                     ui.rounded(188, 42, 11, ui.SIDE_IDLE, ui.BG))
            face = item.create_image(0, 0, anchor="nw", image=faces[1])
            glyph = item.create_text(28, 21, text=ui.ICON[key],
                                     font=(ui.ICONS, 13), fill=ui.DIM)
            label = item.create_text(50, 22, text=name, font=(ui.UI, 10),
                                     anchor="w", fill=ui.DIM)
            self.nav[name] = (item, face, glyph, label, faces)
            item.bind("<Button-1>", lambda _e, n=name: self._show(n))
            item.bind("<Enter>", lambda _e, n=name: self._nav_hover(n, True))
            item.bind("<Leave>", lambda _e, n=name: self._nav_hover(n, False))
            y += 48

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
        elif unread > 0:
            colour = ui.RED if kind == "error" else ui.AMBER
            word = colour
            state = f"{unread} UNREAD"
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
        """(index as the file writes it, a name) for every input device,
        the way the first-run setup lists them. Asked once per visit."""
        p = self.parts
        if "mics" not in p:
            try:
                import firstrun
                devices = firstrun._devices()
            except Exception:
                devices = []
            p["mics"] = ([("", "System default")]
                         + [(str(index), f"{name} — {api}")
                            for index, name, api in devices])
        return list(p["mics"])

    def _menu_for(self, row, setting) -> list:
        """(value, label) for a row's menu: the microphones on this
        machine for the microphone, the names the words give it, or the
        file's own choices. [] = a field."""
        if setting.path == "audio.device":
            mics = self._microphones()
            if len(mics) > 1:
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
                        self._slide_after, self._breath_after):
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
