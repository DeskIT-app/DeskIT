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
       ("keys", "Keys"), ("version", "Version"), ("settings", "Settings"))

# Which keys belong together on the Keys screen. HOTKEY_FIELDS is still
# the one place a new key has to be added: anything not named here lands
# in the last group rather than vanishing.
KEY_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Recording", ("hotkey", "english_hotkey", "latch_hotkey")),
    ("What to do with the text", ("translate_hotkey", "punctuate_hotkey",
                                  "correct_hotkey", "lookup_hotkey")),
    ("The app itself", ("pause_hotkey",)),
)

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


def _mic_from_config(cfg) -> str:
    """What the microphone is set to, for when there is no running app to
    ask what it actually opened."""
    device = getattr(getattr(cfg, "audio", None), "device", None)
    if device is None or device == "":
        return "system default"
    return f"device {device}" if isinstance(device, int) else str(device)


def _words_on_disk() -> int:
    """The vocabulary without loading the vocabulary: the file is the
    record, and this window has no business opening the real store."""
    import json
    try:
        data = json.loads((APP_DIR / "vocab.json").read_text("utf-8"))
        return len(data.get("corrections") or [])
    except Exception:
        return 0


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
        # The branch this folder is on, cached ONCE: the Overview meta line
        # and the Version screen read this rather than shelling out to git
        # on every 800 ms poll. Refreshed after a successful switch.
        try:
            import versions as versions_mod
            self.branch = versions_mod.current_branch()
        except Exception:
            self.branch = "?"
        # Latched, not re-derived, because the pause taken by the key
        # dialog has to be undone from wherever that dialog's life ends —
        # including a route that never runs its own close handler.
        self._paused_for_capture = False
        self._events: queue.Queue = queue.Queue()
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
        tk.Frame(self.root, bg="#1a202b", width=1, height=H).place(x=SIDE - 1,
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
            faces = (ui.rounded(188, 42, 11, ui.ACCENT_SOFT, ui.BG, "#2b3f66"),
                     ui.rounded(188, 42, 11, ui.BG, ui.BG),
                     ui.rounded(188, 42, 11, "#141922", ui.BG))
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

        card = ui.Card(bar, 188, 78, bg=ui.BG, fill="#131822", radius=12,
                       pad=14)
        card.place(x=12, y=H - 102)
        self.parts["lamp"] = tk.Label(card.body, bg="#131822")
        self.parts["lamp"].place(x=-4, y=6)
        self.parts["state"] = tk.Label(card.body, text="", bg="#131822",
                                       fg=ui.FG, font=(ui.UI, 10, "bold"))
        self.parts["state"].place(x=26, y=4)
        self.parts["uptime"] = tk.Label(card.body, text="", bg="#131822",
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
                       fill="#1b2231", border="#2c3648", pad=12)
        tk.Label(card.body, text=wrapped, bg="#1b2231", fg=ui.FG,
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
        tile_hot = ui.rounded(161, 86, 14, ui.CARD_HI, ui.PANE, "#2f3a4d")
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
        if self._rows_after is not None:
            try:
                self.root.after_cancel(self._rows_after)
            except Exception:
                pass
            self._rows_after = None

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
        hot = ui.rounded(CW, height, 12, ui.CARD_HI, ui.PANE, "#2f3a4d")
        face = row.create_image(0, 0, anchor="nw", image=idle)
        colour = COLOURS[event.colour]

        row.create_text(14, 15, text=event.when.strftime("%H:%M"),
                        anchor="nw", font=(ui.UI, 10, "bold"), fill=ui.FG)
        row.create_text(14, 34, text=event.when.strftime("%d %b"),
                        anchor="nw", font=(ui.UI, 8), fill=ui.FAINT)
        row.create_image(66, 14, anchor="nw",
                         image=ui.rounded(28, 28, 9, "#1c2432", ui.CARD))
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

    # --------------------------------------------------------------- keys

    def _screen_keys(self) -> None:
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

        y = 64
        for title, fields in groups:
            if not fields:
                continue
            card = ui.Card(self.sheet, CW, 60 + len(fields) * 46, pad=18)
            card.place(x=PAD, y=y)
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
            y += 60 + len(fields) * 46 + 14

    def _paint_keys(self) -> None:
        caps = self.parts.get("caps")
        if not caps:
            return
        keys = self.status.get("keys") or self._read_keys()
        for field, cap in caps.items():
            cap.set(pretty_key(keys.get(field, "")))

    # ----------------------------------------------------------- settings

    def _screen_settings(self) -> None:
        self._title("Settings", "written straight into config.toml")
        p = self.parts

        rows = (("engine", "Transcription engine", "engine",
                 "local is Whisper on this GPU, gemini is the cloud"),
                ("mic", "Microphone", "mic",
                 "set by index in config.toml — names get truncated"),
                ("learned", "Vocabulary", "vocab",
                 "words it has been taught, fed to the next transcription"))
        card = ui.Card(self.sheet, CW, 62 + len(rows) * 52, pad=18)
        card.place(x=PAD, y=64)
        tk.Label(card.body, text="WHAT IT IS USING", bg=ui.CARD,
                 fg=ui.FAINT, font=(ui.UI, 8)).place(x=0, y=0)
        row = 26
        for glyph, label, key, hint in rows:
            tk.Label(card.body, text=ui.ICON[glyph], bg=ui.CARD, fg=ui.DIM,
                     font=(ui.ICONS, 11)).place(x=0, y=row + 6)
            tk.Label(card.body, text=label, bg=ui.CARD, fg=ui.FG,
                     font=(ui.UI, 10)).place(x=26, y=row + 2)
            tk.Label(card.body, text=hint, bg=ui.CARD, fg=ui.FAINT,
                     font=(ui.UI, 8)).place(x=26, y=row + 22)
            p[f"set_{key}"] = tk.Label(card.body, text="—", bg=ui.CARD,
                                       fg=ui.ACCENT_TEXT, font=(ui.UI, 10))
            p[f"set_{key}"].place(x=CW - 36, y=row + 4, anchor="ne")
            row += 52

        y = 64 + 62 + len(rows) * 52 + 14
        behaviour = ui.Card(self.sheet, CW, 98, pad=18)
        behaviour.place(x=PAD, y=y)
        tk.Label(behaviour.body, text="BEHAVIOUR", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=0, y=0)
        tk.Label(behaviour.body,
                 text="Pause by itself while a game is fullscreen",
                 bg=ui.CARD, fg=ui.FG, font=(ui.UI, 10)).place(x=0, y=26)
        tk.Label(behaviour.body,
                 text="the dictation key belongs to the game while it is in "
                      "front — it only ever un-pauses its own pause",
                 bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8)).place(x=0, y=46)
        p["auto"] = ui.Switch(behaviour.body, command=self._toggle_auto)
        p["auto"].place(x=CW - 36 - 42, y=28)

        y += 112
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
        files = ui.Card(self.sheet, CW, 60 + len(openers) * 44, pad=18)
        files.place(x=PAD, y=y)
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

    def _paint_settings(self) -> None:
        p = self.parts
        if "set_engine" not in p:
            return
        status = self.status
        cfg = None
        if not status:
            try:
                cfg = config_mod.load(CONFIG_PATH)
            except Exception:
                cfg = None
        p["set_engine"].config(text=status.get("backend")
                               or (getattr(cfg, "backend", "") if cfg else "")
                               or "—")
        p["set_mic"].config(text=status.get("mic") or _mic_from_config(cfg))
        vocab = status.get("vocab") or {}
        p["set_vocab"].config(text=f"{vocab['corrections']} words" if vocab
                              else f"{_words_on_disk()} words")
        auto = status.get("auto_pause_fullscreen")
        if auto is None:
            auto = self._read_keys().get("_auto", False)
        p["auto"].set(bool(auto))

    # ------------------------------------------------------------- version

    def _screen_version(self) -> None:
        """Which whole-app version is running, and the one-click way to
        change it. Versions are git branches of this very folder;
        versions.py owns the mechanics (stop the instance, carry
        config.toml across untouched, flip the branch, restart). This
        screen is its face."""
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
        now = ui.Card(self.sheet, CW, 122, pad=18)
        now.place(x=PAD, y=64)
        tk.Label(now.body, text="RUNNING NOW", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=0, y=0)
        tk.Label(now.body, text=info["label"], bg=ui.CARD,
                 fg=ui.ACCENT_TEXT,
                 font=(ui.DISPLAY, 19, "bold")).place(x=0, y=16)
        tk.Label(now.body, text=f"branch '{here}'", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=0, y=48)
        tk.Label(now.body, text=info["desc"], bg=ui.CARD, fg=ui.DIM,
                 font=(ui.UI, 8), wraplength=CW - 36,
                 justify="left").place(x=0, y=66)

        others = [n for n in known if n != here]
        row_h = 58
        card_h = 62 + len(others) * row_h + 62
        card = ui.Card(self.sheet, CW, card_h, pad=18)
        card.place(x=PAD, y=198)
        tk.Label(card.body, text="SWITCH TO", bg=ui.CARD, fg=ui.FAINT,
                 font=(ui.UI, 8)).place(x=0, y=0)
        row = 26
        for name in others:
            oinfo = registry.get(name, {"label": name, "desc": ""})
            tk.Label(card.body, text=ui.ICON["version"], bg=ui.CARD,
                     fg=ui.ACCENT, font=(ui.ICONS, 11)).place(x=0, y=row + 7)
            tk.Label(card.body, text=f"{oinfo['label']}  ({name})",
                     bg=ui.CARD, fg=ui.FG,
                     font=(ui.UI, 10)).place(x=26, y=row + 1)
            tk.Label(card.body, text=oinfo["desc"], bg=ui.CARD, fg=ui.FAINT,
                     font=(ui.UI, 8), wraplength=CW - 210,
                     justify="left").place(x=26, y=row + 21)
            btn = ui.Button(card.body, "Use this",
                            lambda t=name: self._use_version(t),
                            w=96, h=32, quiet=True, icon=ui.ICON["play"])
            btn.place(x=CW - 36 - 96, y=row + 6)
            p[f"use_{name}"] = btn
            row += row_h
        if not others:
            tk.Label(card.body, text="no other version exists on this "
                                     "machine — see versions.py",
                     bg=ui.CARD, fg=ui.FAINT,
                     font=(ui.UI, 9)).place(x=0, y=row)

        p["ver_status"] = tk.Label(card.body, text="", bg=ui.CARD,
                                   fg=ui.AMBER, font=(ui.UI, 8),
                                   wraplength=CW - 36, justify="left")
        p["ver_status"].place(x=0, y=row + 6)
        tk.Label(card.body,
                 text="switching stops the app, flips the folder and starts "
                      "it again (~25 s of model loading). your settings come "
                      "across untouched; a switch refuses while any file "
                      "other than config.toml has uncommitted changes.",
                 bg=ui.CARD, fg=ui.FAINT, font=(ui.UI, 8),
                 wraplength=CW - 36, justify="left").place(x=0, y=row + 28)

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

    def _toggle_auto(self, value: bool) -> None:
        if self.running:
            self._ask("option",
                      then=lambda r: self._announce(r, "saved"),
                      name="auto_pause_fullscreen", value=value)
            return
        try:
            config_mod.set_values(CONFIG_PATH,
                                  {"auto_pause_fullscreen": value})
            self._note("saved — it applies the next time it starts")
        except Exception as e:
            if "auto" in self.parts:
                self.parts["auto"].set(not value)
            self._note(str(e))

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
            import dataclasses
            current = config_mod.load(CONFIG_PATH)
            config_mod.check_hotkeys(dataclasses.replace(current,
                                                         **{field: key}))
            config_mod.set_values(CONFIG_PATH, {field: key})
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
                image=ui.lamp(26, colour, "#131822", glow))
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

    def run(self) -> None:
        self.root.mainloop()


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
