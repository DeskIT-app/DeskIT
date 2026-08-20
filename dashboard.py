"""The control window: start it, pause it, stop it, and change its keys.

Before this there were two shortcuts on the desktop — one that started the
app and one that stopped it — and nothing that could tell you which of
those had last happened. The status dot says "running", but only once
running; during the ~25 s of loading two Whisper models there is a splash
and after a stop there is nothing at all, and "is it on?" was answered by
holding the hotkey and seeing whether anything came out.

Three things follow from that, and they are the whole design:

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

EVERYTHING HERE IS IN ENGLISH ON PURPOSE. Tk 8.6 has no bidi support
whatsoever — a label holding Hebrew renders in visual order, i.e.
backwards, and mixed Hebrew/English comes out scrambled. That is also why
the last dictation is shown as "4.2 s -> 96 chars" with a button to copy
the text rather than as the text itself: a preview here would be worse
than useless, it would be wrong in a way that looks like a transcription
bug.
"""
from __future__ import annotations

import ctypes
import queue
import threading
import time
import tkinter as tk
from pathlib import Path

import config as config_mod
import control
import hotkey as hotkey_mod
import launch
import singleton

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.toml"
ICON_PATH = APP_DIR / "icon.ico"

# Any string, as long as it is OURS and stays put. Windows groups taskbar
# buttons and picks their icon by this; without one the window inherits
# pythonw.exe's identity, which is why the taskbar showed a generic file
# icon rather than the app's.
APP_ID = "Yoav.HebrewDictation.Dashboard"

BG = "#10131a"
CARD = "#161b25"
FG = "#e8ecf4"
DIM = "#8b97ad"
FAINT = "#5d6779"
ACCENT = "#2d6cdf"
LINE = "#232a36"

# activity -> (dot colour, the word for it)
LOOKS = {
    "stopped":   ("#5d6779", "STOPPED"),
    "starting":  ("#e0a32b", "STARTING"),
    "ready":     ("#2d6cdf", "RUNNING"),
    "recording": ("#e0352b", "RECORDING"),
    "locked":    ("#e0352b", "LOCKED ON"),
    "busy":      ("#e0a32b", "TRANSCRIBING"),
    "paused":    ("#8b97ad", "PAUSED"),
}

POLL_MS = 800


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


def _log_icon_problem(error) -> None:
    # Nothing here is worth failing a window over, but a silently missing
    # icon is indistinguishable from one that was never asked for.
    import logging
    logging.getLogger("app").debug("could not set the window icon: %r", error)


class Dashboard:
    def __init__(self) -> None:
        _claim_taskbar_identity()
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
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        self.status: dict = {}
        self.running = False
        self.closing = False
        # Latched, not re-derived, because the pause taken by the key
        # dialog has to be undone from wherever that dialog's life ends —
        # including a route that never runs its own close handler.
        self._paused_for_capture = False
        self._events: queue.Queue = queue.Queue()
        self._busy_until = 0.0     # ignore polls right after a command, so a
                                   # stale status cannot flicker the buttons
                                   # back for one frame
        self._build()
        # After _build: LoadImage/WM_SETICON need a realised window, and on
        # an unrealised one they report success and do nothing.
        self.root.update_idletasks()
        _set_window_icon(self.root)
        self._refresh(None)
        threading.Thread(target=self._poller, daemon=True,
                         name="dashboard-poll").start()
        # Someone double-clicked the shortcut again. That launch cannot
        # open a second window (see main), so it pokes this one instead.
        self._show_signal = singleton.Signal(singleton.DASHBOARD_SHOW)
        threading.Thread(target=self._watch_for_reopen, daemon=True,
                         name="dashboard-reopen").start()
        self.root.after(80, self._pump)

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

    # ---------------------------------------------------------- the window

    def _card(self, parent, title: str | None = None) -> tk.Frame:
        frame = tk.Frame(parent, bg=CARD, highlightbackground=LINE,
                         highlightthickness=1)
        frame.pack(fill="x", padx=14, pady=(0, 10))
        if title:
            tk.Label(frame, text=title.upper(), bg=CARD, fg=FAINT,
                     font=("Segoe UI Semibold", 8), anchor="w").pack(
                         fill="x", padx=14, pady=(10, 0))
        return frame

    def _button(self, parent, text, command, primary=False, width=10):
        return tk.Button(
            parent, text=text, command=command, width=width,
            bg=ACCENT if primary else "#222a38",
            fg="#ffffff" if primary else FG,
            activebackground="#3a7ce8" if primary else "#2c3444",
            activeforeground="#ffffff", relief="flat",
            font=("Segoe UI", 9), bd=0, highlightthickness=0,
            cursor="hand2", padx=6, pady=5, disabledforeground=FAINT)

    @staticmethod
    def _enable(button: tk.Button, enabled: bool, primary: bool = False):
        """Tk greys the LABEL of a disabled button and leaves its background
        alone, so a disabled Start button keeps the accent colour and goes
        on looking like the thing to click."""
        button.config(state="normal" if enabled else "disabled",
                      bg=((ACCENT if primary else "#222a38") if enabled
                          else "#1a202b"))

    def _build(self) -> None:
        root = self.root

        # -- state line: the answer to "is it on", in one glance --
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=14, pady=(14, 10))
        self.lamp = tk.Canvas(head, width=14, height=14, bg=BG,
                              highlightthickness=0)
        self.lamp.pack(side="left", pady=(3, 0))
        self.lamp_dot = self.lamp.create_oval(1, 1, 13, 13, width=0)
        self.state_label = tk.Label(head, text="", bg=BG, fg=FG,
                                    font=("Segoe UI Semibold", 13))
        self.state_label.pack(side="left", padx=(8, 0))
        self.uptime_label = tk.Label(head, text="", bg=BG, fg=FAINT,
                                     font=("Segoe UI", 9))
        self.uptime_label.pack(side="right", pady=(4, 0))

        self.sub_label = tk.Label(root, text="", bg=BG, fg=DIM, anchor="w",
                                  justify="left", wraplength=430,
                                  font=("Segoe UI", 9))
        self.sub_label.pack(fill="x", padx=14, pady=(0, 12))

        # -- the three buttons this window exists for --
        buttons = tk.Frame(root, bg=BG)
        buttons.pack(fill="x", padx=14, pady=(0, 12))
        self.start_button = self._button(buttons, "Start", self._start,
                                         primary=True, width=12)
        self.start_button.pack(side="left")
        self.pause_button = self._button(buttons, "Pause", self._toggle_pause,
                                         width=12)
        self.pause_button.pack(side="left", padx=8)
        self.stop_button = self._button(buttons, "Stop", self._stop, width=12)
        self.stop_button.pack(side="left")

        # -- keys --
        keys = self._card(root, "keys")
        tk.Label(keys, text="Click a key to press a new one for it. The app "
                            "is paused while it listens, so the key you press "
                            "cannot set anything off.",
                 bg=CARD, fg=FAINT, font=("Segoe UI", 8), anchor="w",
                 justify="left", wraplength=400).pack(fill="x", padx=14,
                                                      pady=(4, 8))
        self.key_buttons: dict[str, tk.Button] = {}
        for field, label in config_mod.HOTKEY_FIELDS:
            row = tk.Frame(keys, bg=CARD)
            row.pack(fill="x", padx=14, pady=2)
            tk.Label(row, text=label, bg=CARD, fg=DIM, anchor="w",
                     font=("Segoe UI", 9), width=24).pack(side="left")
            button = self._button(row, "…",
                                  lambda f=field, la=label: self._capture(f, la),
                                  width=14)
            button.pack(side="right")
            self.key_buttons[field] = button
        tk.Frame(keys, bg=CARD, height=8).pack()

        self.auto_pause = tk.BooleanVar(value=False)
        self.auto_check = tk.Checkbutton(
            keys, text="Pause by itself while a game is fullscreen",
            variable=self.auto_pause, command=self._toggle_auto,
            bg=CARD, fg=DIM, selectcolor=CARD, activebackground=CARD,
            activeforeground=FG, font=("Segoe UI", 9), anchor="w",
            highlightthickness=0, bd=0, cursor="hand2")
        self.auto_check.pack(fill="x", padx=10, pady=(0, 10))

        # -- today --
        today = self._card(root, "today")
        self.stats_label = tk.Label(today, text="", bg=CARD, fg=FG,
                                    anchor="w", justify="left",
                                    font=("Segoe UI", 9))
        self.stats_label.pack(fill="x", padx=14, pady=(6, 4))
        self.vocab_label = tk.Label(today, text="", bg=CARD, fg=DIM,
                                    anchor="w", justify="left",
                                    wraplength=400, font=("Segoe UI", 9))
        self.vocab_label.pack(fill="x", padx=14, pady=(0, 10))

        # -- the last thing that happened, and the way to the evidence --
        last = self._card(root, "last")
        self.note_label = tk.Label(last, text="", bg=CARD, fg=FG, anchor="w",
                                   justify="left", wraplength=400,
                                   font=("Segoe UI", 9))
        self.note_label.pack(fill="x", padx=14, pady=(6, 8))
        row = tk.Frame(last, bg=CARD)
        row.pack(fill="x", padx=10, pady=(0, 10))
        self.copy_button = self._button(row, "Copy last text",
                                        self._copy_last, width=14)
        self.copy_button.pack(side="left", padx=(4, 6))
        self._button(row, "transcripts.log",
                     lambda: launch.open_path(APP_DIR / "transcripts.log"),
                     width=14).pack(side="left", padx=(0, 6))
        self._button(row, "app.log",
                     lambda: launch.open_path(APP_DIR / "app.log"),
                     width=10).pack(side="left")

        self.phone_row = tk.Frame(root, bg=BG)
        self.phone_row.pack(fill="x", padx=14, pady=(0, 14))
        self.phone_button = self._button(self.phone_row, "Copy phone link",
                                         self._copy_phone, width=16)
        self.phone_button.pack(side="left")
        self.phone_label = tk.Label(self.phone_row, text="", bg=BG, fg=FAINT,
                                    font=("Segoe UI", 8), anchor="w")
        self.phone_label.pack(side="left", padx=8)

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
            self._events.put(lambda r=reply: self._refresh(r))
            time.sleep(POLL_MS / 1000)

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
            self.root.after(80, self._pump)

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

    def _note(self, text: str) -> None:
        self.note_label.config(text=text)

    # ------------------------------------------------------------ buttons

    def _start(self) -> None:
        if singleton.is_running():
            self._note("it is already running")
            return
        self._note("starting — the models take about 25 seconds to load")
        self._busy_until = time.monotonic() + 2
        self.state_label.config(text="STARTING")
        self.lamp.itemconfig(self.lamp_dot, fill=LOOKS["starting"][0])
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

    def _toggle_auto(self) -> None:
        value = bool(self.auto_pause.get())
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
            self.auto_pause.set(not value)
            self._note(str(e))

    def _copy_last(self) -> None:
        self._ask("copy_last",
                  then=lambda r: self._announce(r, "copied"))

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
        top.configure(bg=BG)
        top.resizable(False, False)
        top.transient(self.root)
        tk.Label(top, text=label, bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).pack(padx=28, pady=(20, 2))
        prompt = tk.Label(top, text="Press the key you want", bg=BG, fg=FG,
                          font=("Segoe UI Semibold", 13))
        prompt.pack(padx=28, pady=(0, 4))
        tk.Label(top, text="Esc cancels.", bg=BG, fg=FAINT,
                 font=("Segoe UI", 8)).pack(padx=28, pady=(0, 12))
        row = tk.Frame(top, bg=BG)
        row.pack(padx=20, pady=(0, 18))
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

        if field != "hotkey":       # the dictation key cannot be turned off
            self._button(row, "Turn this key off",
                         lambda: finish(""), width=18).pack(side="left")
        self._button(row, "Cancel", lambda: finish(None),
                     width=10).pack(side="left", padx=(8, 0))

        top.bind("<KeyPress>", on_key)
        top.bind("<KeyRelease>", on_release)
        top.protocol("WM_DELETE_WINDOW", lambda: finish(None))
        top.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width()
                                       - top.winfo_width()) // 2
        y = self.root.winfo_rooty() + 140
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
        starting = bool(reply) and stage == "starting"
        paused = bool(self.status.get("paused"))

        # Silent for longer than a startup takes: it is up, it is just not
        # one that can be driven from here.
        deaf = starting and self.status.get("silent_s", 0) > 45

        activity = ("ready" if deaf else
                    "starting" if starting else
                    "stopped" if not reply else
                    self.status.get("activity") or "ready")
        colour, word = LOOKS.get(activity, LOOKS["ready"])
        self.lamp.itemconfig(self.lamp_dot, fill=colour)
        self.state_label.config(text=word)
        uptime = self.status.get("uptime_s")
        self.uptime_label.config(
            text=f"up {human_time(uptime)}" if uptime else "")

        if not reply:
            self.sub_label.config(
                text="Not running. Start it and the keys below come alive; "
                     "the first start loads two Whisper models onto the GPU "
                     "and takes about 25 seconds.")
        elif deaf:
            self.sub_label.config(
                text="Running, but not answering this window — it was "
                     "started before the dashboard existed. Stop and start "
                     "it to get pause and the key changes. Dictation itself "
                     "is fine; the keys below are read from config.toml.")
        elif starting:
            self.sub_label.config(text=self.status.get("note")
                                  or "loading the models…")
        else:
            backend = self.status.get("backend", "?")
            mic = self.status.get("mic", "?")
            self.sub_label.config(
                text=("Keys are inert — the models are still loaded, so "
                      f"resuming is instant.  ·  {backend}"
                      if paused else f"{backend}  ·  {mic}"))

        self._enable(self.start_button, not reply, primary=True)
        self._enable(self.stop_button, bool(reply))
        self._enable(self.pause_button, self.running)
        self.pause_button.config(text="Resume" if paused else "Pause")
        self._enable(self.copy_button, self.running)

        keys = self.status.get("keys") or self._read_keys()
        for field, _label in config_mod.HOTKEY_FIELDS:
            self.key_buttons[field].config(text=pretty_key(keys.get(field, "")))
        auto = self.status.get("auto_pause_fullscreen",
                               keys.get("_auto", False))
        self.auto_pause.set(bool(auto))

        stats = self.status.get("stats") or {}
        count = stats.get("dictations", 0)
        if count:
            average = stats.get("latency", 0.0) / count
            self.stats_label.config(
                text=f"{count} dictations · "
                     f"{stats.get('seconds', 0) / 60:.1f} min spoken · "
                     f"{stats.get('chars', 0)} chars · {average:.1f} s each")
        else:
            self.stats_label.config(
                text="nothing dictated yet today" if reply else "")
        vocab = self.status.get("vocab") or {}
        bits = []
        if vocab:
            bits.append(f"{vocab.get('corrections', 0)} learned "
                        f"({vocab.get('automatic', 0)} repaired "
                        f"automatically) · {vocab.get('hotwords', 0)} "
                        f"hotwords")
        if stats.get("translations"):
            bits.append(f"{stats['translations']} translated")
        if stats.get("punctuations"):
            bits.append(f"{stats['punctuations']} punctuated")
        if stats.get("lookups"):
            bits.append(f"{stats['lookups']} looked up")
        if stats.get("failures"):
            bits.append(f"{stats['failures']} failed")
        if self.status.get("pending"):
            bits.append(f"{self.status['pending']} waiting in pending\\ "
                        f"(main.py --drain)")
        self.vocab_label.config(text="\n".join(bits))

        note = self.status.get("note")
        if note and not starting:
            self._note(note)

        url = self.status.get("phone", "")
        self.phone_label.config(text="phone endpoint is live" if url else "")
        self.phone_button.config(state="normal" if url else "disabled")

    # ------------------------------------------------------------ shutdown

    def _close(self) -> None:
        # Closing this window must never stop dictation — it is a remote
        # control, not the app. It must not leave it PAUSED either, which
        # is what closing it on top of an open key dialog used to do.
        self.closing = True
        self._resume_after_capture()
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
