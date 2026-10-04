"""The "DeskIT is on this PC twice" window (onecopy.py finds the other copy).

Opened by main.py before anything is read or written, when a released copy
finds the other released copy installed for this Windows user: a title,
one paragraph, a card per copy with its own Keep this one — the Store
copy's gold, the one recommended (it loses nothing either way: the website
copy's uninstaller keeps its data and the Store copy goes on with it) —
and Quit. The owner approved these words and this look on 2026-10-04 from
pictures taken on the hidden desktop (dev/shot_one_copy.py takes them).

Four faces, one window:

  choose    the two cards
  removing  the Store copy keeps itself: the website copy's uninstaller
            runs (onecopy.remove_website) and DeskIT App starts after it
  waiting   the website copy keeps itself: Windows Settings is open at
            DeskIT App, and DeskIT starts by itself once it is gone
  failed    the website copy is still installed after two minutes

`run()` returns "start" (go on starting this copy) or "quit". Closing the
window is Quit: nothing starts and the next start asks again. One window
per PC: a second copy started while it is up (both had Start with
Windows) finds its mutex and quits without a word.

Built on ui.py and the wizard's palette (firstrun._lamplight), English
like the wizard.
"""
from __future__ import annotations

import ctypes
import gc
import logging
import queue
import threading
import tkinter as tk
from pathlib import Path

import onecopy
import paths

log = logging.getLogger("app")

APP_DIR = Path(__file__).resolve().parent
W = 640
PAD = 28
INNER = W - 2 * PAD
POLL_MS = 1000
LOCK_NAME = paths.kernel_name(r"Local\DeskIT.onecopy")
ERROR_ALREADY_EXISTS = 183

WORDS = {
    "title": "DeskIT is on this PC twice",
    "why": ("Once from the website and once from the Microsoft Store. One PC "
            "keeps one DeskIT: two would share some settings and the cloud "
            "keys, and only one can run at a time. Choose the one to keep."),
    "keep": "Keep this one",
    "this": "This one",
    "quit": "Quit",
    "foot": "DeskIT starts once one is left.",
    "store.facts": "{version}  ·  updated by the Microsoft Store",
    "website.facts": "{version}  ·  {folder}",
    # under each card: what its Keep does to the OTHER copy, as said from
    # the copy that shows the window
    "store.keep.from_store": ("Uninstalls the website copy. Its settings, "
                              "history and model stay on this PC."),
    "store.keep.from_website": ("Uninstalls this copy and opens DeskIT App. "
                                "Settings, history and the model stay on this PC."),
    "website.keep": ("Opens Windows Settings at DeskIT App, where you press "
                     "Uninstall. What it kept only on this PC goes with it; "
                     "synced words and settings come back from your account."),
    "removing.title": "Removing the website copy",
    "removing.line": "DeskIT App starts as soon as it is gone.",
    "waiting.title": "Waiting for Windows to remove DeskIT App",
    "waiting.line": ("In Settings, press Uninstall under DeskIT App. "
                     "DeskIT starts by itself once it is gone."),
    "waiting.again": "Open Settings again",
    "failed.title": "The website copy is still installed",
    "failed.line": ("Remove DeskIT in Windows Settings, under Apps > Installed "
                    "apps, then open DeskIT App again."),
    "failed.open": "Open Settings",
}
APPS_SETTINGS_URI = "ms-settings:appsfeatures"


class Actions:
    """What the buttons do — onecopy's, so a test can stand in for each."""
    store_copy = staticmethod(onecopy.store_copy)
    remove_website = staticmethod(onecopy.remove_website)
    uninstall_self_then_open_store = staticmethod(onecopy.uninstall_self_then_open_store)
    open_store_settings = staticmethod(onecopy.open_store_settings)
    start_website_waiting = staticmethod(onecopy.start_website_waiting)
    move_claude_door = staticmethod(onecopy.move_claude_door)
    quit_running = staticmethod(onecopy.quit_running)

    @staticmethod
    def open_uri(uri: str) -> None:
        import os
        try:
            os.startfile(uri)                                 # noqa: S606
        except OSError:
            pass


def _facts(copy: onecopy.Copy) -> dict:
    return {"version": copy.version or "?",
            "folder": paths.short(copy.folder) if copy.folder else ""}


class Window:
    """`here` is this copy's kind ("store" | "website"); `other` the copy
    onecopy found; `me` this copy as onecopy sees it (the website copy's
    own Uninstall entry — what its Keep the Store's needs; None in the
    Store copy)."""

    def __init__(self, here: str, other: onecopy.Copy, me: onecopy.Copy | None = None,
                 *, actions=None, waiting: bool = False, poll_ms: int = POLL_MS):
        import firstrun
        import ui
        self.ui, self.firstrun = ui, firstrun
        self.here, self.other, self.me = here, other, me
        self.actions = actions or Actions()
        self.poll_ms = poll_ms
        self.result = "quit"
        self.face = ""
        self.buttons: dict[str, object] = {}
        self._done: queue.Queue = queue.Queue()
        firstrun._lamplight()
        ui.forget_images()
        self.root = tk.Tk()
        self.root.title("DeskIT")
        self.root.configure(bg=ui.BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        try:
            import dashboard
            # the frame Windows draws the title bar on exists only once
            # Tk has been through its idle tasks; WM_SETICON goes to it
            self.root.update_idletasks()
            dashboard._set_window_icon(self.root)
        except Exception:                                     # noqa: BLE001
            pass                      # cosmetic: never a reason not to ask
        self.foot = tk.Frame(self.root, bg=ui.BG)
        self.foot.pack(side="bottom", fill="x", padx=PAD, pady=(18, PAD))
        self.body = tk.Frame(self.root, bg=ui.BG)
        self.body.pack(fill="both", expand=True, padx=PAD, pady=(PAD, 0))
        if waiting:
            self._waiting()
        else:
            self._choose()

    # ------------------------------------------------------------ the faces
    def _clear(self) -> None:
        self.buttons = {}
        for frame in (self.body, self.foot):
            for child in frame.winfo_children():
                child.destroy()

    def _head(self, title: str, line: str) -> None:
        ui = self.ui
        row = tk.Frame(self.body, bg=ui.BG)
        row.pack(fill="x")
        mark = ui.icon_bitmap(APP_DIR / "icon.png", 20, ui.BG)
        if mark is not None:
            badge = tk.Label(row, image=mark, bg=ui.BG)
            badge.photo = mark
            badge.pack(side="left", padx=(0, 8))
        tk.Label(row, text="DeskIT", bg=ui.BG, fg=ui.DIM,
                 font=(ui.MEDIUM, 9)).pack(side="left")
        tk.Label(self.body, text=title, bg=ui.BG, fg=ui.FG,
                 font=(ui.DISPLAY, 18), anchor="w").pack(fill="x", pady=(16, 6))
        tk.Label(self.body, text=line, bg=ui.BG, fg=ui.DIM, font=(ui.UI, 10),
                 anchor="w", justify="left", wraplength=INNER
                 ).pack(fill="x", pady=(0, 18))

    def _card(self, kind: str, copy: onecopy.Copy) -> None:
        ui = self.ui
        card = ui.Card(self.body, INNER, 41, bg=ui.BG, pad=18)
        card.pack(fill="x", pady=(0, 12))
        top = tk.Frame(card.body, bg=ui.CARD)
        top.pack(fill="x")
        words = tk.Frame(top, bg=ui.CARD)
        words.pack(side="left", fill="x", expand=True)
        name = tk.Frame(words, bg=ui.CARD)
        name.pack(fill="x")
        tk.Label(name, text=copy.name, bg=ui.CARD, fg=ui.FG,
                 font=(ui.UI, 12), anchor="w").pack(side="left")
        if kind == self.here:
            # DIM, not the accent: the gold Keep is this surface's one lamp
            tk.Label(name, text=WORDS["this"], bg=ui.CARD, fg=ui.DIM,
                     font=(ui.UI, 9)).pack(side="left", padx=(10, 0))
        facts = _facts(copy)
        # a website copy whose folder is not known says its version alone
        line = (WORDS[f"{kind}.facts"].format(**facts) if kind == "store" or facts["folder"]
                else facts["version"])
        tk.Label(words, text=line, bg=ui.CARD,
                 fg=ui.FAINT, font=(ui.UI, 9), anchor="w").pack(fill="x", pady=(2, 0))
        button = ui.Button(top, WORDS["keep"], lambda k=kind: self._keep(k), bg=ui.CARD,
                           w=140, primary=(kind == "store"))
        button.pack(side="right", anchor="n")
        self.buttons[f"keep.{kind}"] = button
        said = (WORDS[f"store.keep.from_{self.here}"] if kind == "store"
                else WORDS["website.keep"])
        tk.Label(card.body, text=said, bg=ui.CARD, fg=ui.DIM, font=(ui.UI, 9),
                 anchor="w", justify="left", wraplength=INNER - 40).pack(fill="x", pady=(12, 0))
        card.body.update_idletasks()
        card.resize(card.body.winfo_reqheight() + 36)

    def _quit_button(self) -> None:
        button = self.ui.Button(self.foot, WORDS["quit"], self._quit, bg=self.ui.BG,
                                quiet=True, w=96)
        button.pack(side="right")
        self.buttons["quit"] = button

    def _choose(self) -> None:
        ui = self.ui
        self.face = "choose"
        self._clear()
        self._head(WORDS["title"], WORDS["why"])
        store, website = ((onecopy.Copy("store", _own_version()), self.other)
                          if self.here == "store" else
                          (self.other, self.me or onecopy.Copy("website", _own_version())))
        self._card("store", store)
        self._card("website", website)
        self._quit_button()
        tk.Label(self.foot, text=WORDS["foot"], bg=ui.BG, fg=ui.FAINT,
                 font=(ui.UI, 9), anchor="w").pack(side="left")
        self._fit()

    def _bar(self) -> None:
        ui = self.ui
        bar = tk.Canvas(self.body, width=INNER, height=4, bg=ui.BG,
                        highlightthickness=0, bd=0)
        bar.pack(fill="x", pady=(0, 8))
        bar.create_rectangle(0, 0, INNER, 4, fill=ui.LINE, outline="")
        lit = bar.create_rectangle(0, 0, INNER * 0.22, 4, fill=ui.ACCENT, outline="")
        self._sweep(bar, lit, 0)

    def _sweep(self, bar, lit, at: int) -> None:
        """An indeterminate bar: the lit stretch walks across and wraps."""
        try:
            if not bar.winfo_exists():
                return
        except tk.TclError:
            return
        x = (at % 120) / 100 * INNER - INNER * 0.22
        bar.coords(lit, max(0, x), 0, min(INNER, x + INNER * 0.22), 4)
        self.root.after(30, lambda: self._sweep(bar, lit, at + 1))

    def _removing(self) -> None:
        self.face = "removing"
        self._clear()
        self._head(WORDS["removing.title"], WORDS["removing.line"])
        self._bar()
        self._fit()

    def _waiting(self) -> None:
        self.face = "waiting"
        self._clear()
        self._head(WORDS["waiting.title"], WORDS["waiting.line"])
        self._bar()
        self._quit_button()
        again = self.ui.Button(self.foot, WORDS["waiting.again"], self.actions.open_store_settings,
                               bg=self.ui.BG, w=190)
        again.pack(side="right", padx=(0, 10))
        self.buttons["again"] = again
        self._fit()
        self.root.after(self.poll_ms, self._poll_store)

    def _failed(self) -> None:
        self.face = "failed"
        self._clear()
        self._head(WORDS["failed.title"], WORDS["failed.line"])
        self._quit_button()
        open_ = self.ui.Button(self.foot, WORDS["failed.open"],
                               lambda: self.actions.open_uri(APPS_SETTINGS_URI),
                               bg=self.ui.BG, w=150)
        open_.pack(side="right", padx=(0, 10))
        self.buttons["open"] = open_
        self._fit()

    def _fit(self) -> None:
        self.root.update_idletasks()
        h = self.root.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{W}x{h}+{(sw - W) // 2}+{max(0, (sh - h) // 3)}")
        self.firstrun._caption(self.root)

    # ---------------------------------------------------------- the answers
    def _keep(self, kind: str) -> None:
        log.info("one copy: %s keeps the %s copy", self.here, kind)
        if self.here == "store" and kind == "store":
            self._removing()
            self.actions.move_claude_door("store", self.other)
            threading.Thread(target=self._remove_website, daemon=True).start()
            self.root.after(200, self._poll_removed)
        elif self.here == "store":
            self.actions.move_claude_door("website", self.other)
            self.result = "quit"
            _release_lock()           # the website copy's window takes it next
            self.actions.start_website_waiting(self.other)
            self.actions.open_store_settings()
            self._close()
        elif kind == "store":
            me = self.me
            self.actions.quit_running()
            if me is not None and me.uninstaller:
                self.actions.move_claude_door("store", me)
                self.actions.uninstall_self_then_open_store(me)
            else:
                self.actions.open_uri(APPS_SETTINGS_URI)
            self.result = "quit"
            self._close()
        else:
            if self.me is not None:
                self.actions.move_claude_door("website", self.me)
            self.actions.open_store_settings()
            self._waiting()

    def _remove_website(self) -> None:
        try:
            ok = bool(self.actions.remove_website(self.other))
        except Exception:                                     # noqa: BLE001
            log.warning("one copy: the website copy's uninstaller failed", exc_info=True)
            ok = False
        self._done.put(ok)

    def _poll_removed(self) -> None:
        try:
            ok = self._done.get_nowait()
        except queue.Empty:
            self.root.after(200, self._poll_removed)
            return
        if ok:
            self.result = "start"
            self._close()
        else:
            self._failed()

    def _poll_store(self) -> None:
        if self.face != "waiting":
            return
        try:
            gone = self.actions.store_copy() is None
        except Exception:                                     # noqa: BLE001
            gone = False
        if gone:
            self.result = "start"
            self._close()
            return
        self.root.after(self.poll_ms, self._poll_store)

    def _quit(self) -> None:
        self.result = "quit"
        self._close()

    def _close(self) -> None:
        try:
            # the bar's sweep and the polls, cancelled: an after() that
            # outlives its window prints "invalid command name" on stderr
            for pending in self.root.tk.call("after", "info"):
                self.root.after_cancel(pending)
            self.root.destroy()
        except tk.TclError:
            pass


def _own_version() -> str:
    try:
        import version
        return str(version.VERSION)
    except Exception:                                         # noqa: BLE001
        return ""


_lock_handle = None


def _take_lock() -> bool:
    """One window per PC; False when another copy's is already up."""
    global _lock_handle
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, LOCK_NAME)
    if not handle:
        return True                   # cannot tell: better asked twice than never
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        k32.CloseHandle(ctypes.c_void_p(handle))
        return False
    _lock_handle = handle
    return True


def _release_lock() -> None:
    global _lock_handle
    if _lock_handle:
        ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(_lock_handle))
        _lock_handle = None


def run(other: onecopy.Copy, *, waiting: bool = False, actions=None) -> str:
    """The window, to its end: "start" or "quit"."""
    if not _take_lock():
        log.info("one copy: another copy's window is up; this one quits")
        return "quit"
    try:
        here = onecopy.this_copy()
        me = None if here == "store" else onecopy.website_copy()
        window = Window(here, other, me, actions=actions, waiting=waiting)
        window.root.mainloop()
        result = window.result
        del window
        gc.collect()                  # Tk dies on this thread (firstrun.run says why)
        return result
    finally:
        _release_lock()
