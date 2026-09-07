"""The two on-screen things a windowless app needs: a startup splash, and
a status dot that says it is running.

Both exist for the same reason. Launched from the shortcut this runs under
pythonw — no console, no window, no taskbar entry — so there is nothing
anywhere on screen to tell you whether it is loading, running, or was
never started at all.

The Splash covers the ~25 s of loading two Whisper models onto the GPU.
Before it, the only signal was the "ready" cue at the very end, which is
exactly when it is no longer needed: you click the shortcut, nothing
happens, so you click it again. The StatusDot covers everything after —
a running app with no window is indistinguishable from one you never
started, or one you closed.

Three things neither may do, all of which a naive overlay gets wrong:

- **Steal focus.** You may well be typing when it appears. The window is
  given WS_EX_NOACTIVATE so clicks and keystrokes keep going wherever they
  were going.
- **Land in the taskbar and Alt-Tab.** WS_EX_TOOLWINDOW keeps it out of
  both; it is a status pop-up, not a program you switch to.
- **Take the app down with it.** Every entry point is wrapped: with no
  display, no Tk, or a hostile window manager, dictation still works. But
  the failure is LOGGED — a silently swallowed one is how a window that
  never appeared looks exactly like a window that did.

Tk is not thread-safe, so everything Tk touches happens on the overlay's
own thread and callers only ever put messages on a queue.

NEITHER OVERLAY MAY CALL mainloop() OR quit(), and that is not a style
preference — it is the fix for a bug that took a reproduction to find.
`quitMainLoop` in CPython's _tkinter is a MODULE-LEVEL GLOBAL, not a
per-interpreter flag: `quit()` sets it, and whichever mainloop looks at it
first returns and clears it. With a splash and a dot alive at once, that is
a coin toss. Measured 2026-08-14 over ten runs of the real startup
sequence, instrumented: five times the splash's quit() ended the SPLASH's
loop (correct), and five times it ended the DOT's loop instead — leaving
the dot destroyed and never shown, and the splash animating on screen
forever because nothing was ever going to stop it.

That is exactly what "the loading box never goes away and I have no dot"
looks like from outside, and why it came and went at random. So each
overlay drives its own interpreter with update() and stops on its own
Event. No shared flag, nothing to steal.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes          # NOT "as w": Splash._build_and_loop uses w
import logging                  # as a local for the window width
import math
import queue
import threading
import time

# --- SKIN -----------------------------------------------------------------
# The reskin lives entirely in skin\, and every hook that reaches it looks
# like this one: guarded, optional, and sitting in FRONT of code that is
# otherwise untouched. Delete the folder and this import fails, `skin`
# stays None, every hook falls through, and both overlays are drawn by the
# Tk code below exactly as they always were. See skin\__init__.py.
try:
    import skin
except Exception:               # missing, broken, or no skia wheel
    skin = None
# --------------------------------------------------------------------------

# Style bits, set after Tk creates the window (Tk exposes neither).
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TRANSPARENT = 0x00000020   # click-through

# LAMPLIGHT, spelled out. This module is imported before ui.py has built
# anything, so it cannot read the palette — it carries the four names the
# splash and the word prompt need. skin\palette.py is the source; these are
# PANE / FG / DIM / ACCENT from it.
BG = "#1c1813"
FG = "#f1ece2"
DIM = "#b2a896"
ACCENT = "#e3a63c"
TROUGH = "#3a342a"      # the splash bar's channel — LINE, one step over BG

_DONE = object()   # sentinel: close the window

# How often an overlay's own event loop turns over. It replaces mainloop()
# (see the module docstring); 15 ms is well under the 28 ms animation tick,
# so nothing looks slower for it.
TICK_S = 0.015

# Overlays are decoration and must never be fatal — but a swallowed
# failure is how a missing window looks exactly like a working one.
_log = logging.getLogger("app")


def _pump_until(root, closing: threading.Event) -> None:
    """Run one interpreter's event loop until asked to stop.

    Deliberately update() in a loop rather than mainloop(): see the module
    docstring. update() drains this interpreter's queue — timers, redraws,
    window messages — and touches no state shared with any other Tk in the
    process, so one overlay closing can no longer close the other.
    """
    while not closing.is_set():
        try:
            root.update()
        except Exception:
            return          # window destroyed underneath us: nothing to do
        time.sleep(TICK_S)


class Splash:
    """Call start(), then status() as often as you like, then finish()."""

    def __init__(self, title: str = "DeskIT",
                 status: str = "starting…") -> None:
        self._q: queue.Queue = queue.Queue()
        self._title = title
        self._first = status
        self._thread: threading.Thread | None = None
        self._alive = threading.Event()
        self._closing = threading.Event()
        self._enabled = True
        self._on_land = None          # set by finish(), fired once by land()
        self._land_lock = threading.Lock()
        self._landings_over = False   # the splash thread's last land() ran

    @classmethod
    def off(cls) -> "Splash":
        """A Splash that does nothing, so callers never branch on config."""
        obj = cls()
        obj._enabled = False
        return obj

    # -- caller's thread --

    def start(self) -> None:
        if not self._enabled:
            return
        try:
            import tkinter  # noqa: F401  (checked here, used on the thread)
        except Exception:
            return                      # headless or no Tk: no splash, no fuss
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="splash")
        self._thread.start()
        self._alive.wait(timeout=3)

    def status(self, text: str) -> None:
        if self._thread is not None:
            self._q.put(str(text))

    def finish(self, text: str | None = None, linger_ms: int = 1100,
               on_land=None) -> None:
        """Show a last line, then close. Non-blocking: the caller is about
        to go and wait for the quit signal, and the lingering happens on
        the splash thread.

        `on_land` fires ONCE, on the splash thread, at the instant the
        release's light arrives in the status dot — about 3.5 s after this
        call returns. It exists because the "ready" cue used to be played
        by the caller on the line above this one, which put the sound
        three and a half seconds ahead of the picture it belongs to: you
        heard the app become ready, and only then watched it happen.

        It is a parameter of finish() and not of __init__ on purpose. The
        two early-exit paths in main() (a fatal error, and stop pressed
        during the load) also call finish(), and neither of them is a
        boot that succeeded — passing the cue here means they cannot
        accidentally announce a readiness that never arrived.
        """
        # ARMING AND THE HANDOFF DECISION ARE ONE CRITICAL SECTION, and
        # the flag is `_landings_over` rather than `thread.is_alive()`.
        # is_alive() was wrong by a hair, in the way that loses the cue
        # altogether: the splash thread runs its final land() and only
        # THEN dies, so there is a window where the thread is still alive
        # (handoff looks safe) but its last land() has already been and
        # gone. Arm inside that window and nobody ever reads the queue.
        # Setting the flag under this same lock before that final land()
        # closes it — whichever side gets the lock first, exactly one of
        # them ends up firing.
        with self._land_lock:
            self._on_land = on_land
            handoff = self._thread is not None and not self._landings_over
        if not handoff:
            # No thread, or no landing left to wait for. The cue still has
            # to happen, or `splash = false` (and any machine without Tk,
            # and any boot whose splash thread died on the way) goes
            # silent — which is worse than it being early.
            self.land()
            return
        if text:
            self._q.put(text)
        self._q.put((_DONE, linger_ms))

    def land(self) -> None:
        """Fire the landing callback, at most once, and never raise.

        Called from the skin's boot loop at the landing frame, again from
        its `finally`, and again from _run()'s — so a release that was
        never armed (reduced motion, no GPU layer, a stop during the
        wind-up, a thread that died on the way) still gets its sound.
        TAKING the slot under the lock, rather than reading it and then
        clearing it, is what makes every call after the first a no-op.
        See finish() for the other half: the lock also orders the arming
        against this thread's last call, so the cue cannot be installed
        into a splash that has already stopped listening for it.

        The callback runs OUTSIDE the lock. It plays a sound, and nothing
        that holds a lock should wait on the audio device.
        """
        with self._land_lock:
            callback, self._on_land = self._on_land, None
        if callback is None:
            return
        try:
            callback()
        except Exception:
            _log.debug("splash: landing cue failed", exc_info=True)

    # -- splash thread --

    def _run(self) -> None:
        try:
            # --- SKIN: takes over the picture, not the protocol. It reads
            # the same queue, sets the same _alive, watches the same
            # _closing and honours the same (_DONE, linger_ms). False means
            # it declined, and the Tk splash below runs untouched.
            if skin is not None and skin.splash_run(self):
                return
            self._build_and_loop()
        except Exception as e:          # never take the app down...
            _log.info("splash unavailable: %r", e)   # ...but say so
        finally:
            self._alive.set()
            # LAST BACKSTOP. Whatever happened above — the skin took over
            # and finished, the skin threw, Tk threw, this thread never
            # got a picture on screen at all — this thread is now over and
            # nothing else will ever fire the cue. A no-op on the normal
            # path, where the landing frame fired it seconds ago.
            #
            # The flag goes up FIRST, under the lock, and it is what makes
            # the land() below the genuinely last one: a finish() racing
            # this line either gets the lock first (and is handed off to
            # us, and we fire it) or second (and sees the flag, and fires
            # it itself). Never both, and never neither.
            with self._land_lock:
                self._landings_over = True
            self.land()

    def _build_and_loop(self) -> None:
        import tkinter as tk

        root = tk.Tk()
        root.overrideredirect(True)     # no title bar: this is a toast
        root.attributes("-topmost", True)
        root.configure(bg=ACCENT)       # 1 px accent border via padding

        frame = tk.Frame(root, bg=BG)
        frame.pack(padx=1, pady=1, fill="both", expand=True)

        tk.Label(frame, text=self._title, bg=BG, fg=FG,
                 font=("Segoe UI Semibold", 13)).pack(
                     anchor="w", padx=20, pady=(16, 2))
        label = tk.Label(frame, text=self._first, bg=BG, fg=DIM,
                         font=("Segoe UI", 10), anchor="w", justify="left",
                         wraplength=330)
        label.pack(anchor="w", padx=20, pady=(0, 12))

        # An indeterminate bar drawn by hand: ttk.Progressbar pulls in a
        # theme engine and still needs a timer, and this is ~10 lines.
        bar_w, bar_h, chip_w = 330, 4, 96
        bar = tk.Canvas(frame, width=bar_w, height=bar_h, bg=TROUGH,
                        highlightthickness=0)
        bar.pack(padx=20, pady=(0, 18))
        chip = bar.create_rectangle(0, 0, chip_w, bar_h, fill=ACCENT,
                                    width=0)

        root.update_idletasks()
        w, h = frame.winfo_reqwidth() + 2, frame.winfo_reqheight() + 2
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        # Bottom-right, above where the taskbar usually is: out of the way
        # of whatever you are actually looking at.
        root.geometry(f"{w}x{h}+{sw - w - 28}+{sh - h - 88}")

        _no_activate(root)
        self._alive.set()

        state = {"x": -chip_w}

        def _land_and_close() -> None:
            """This splash has no release: it is a box that goes away. So
            the going-away IS the landing, and the cue goes with it rather
            than being lost on the path that has no skin."""
            self.land()
            self._closing.set()

        def animate() -> None:
            state["x"] += 9
            if state["x"] > bar_w:
                state["x"] = -chip_w
            bar.coords(chip, state["x"], 0, state["x"] + chip_w, bar_h)
            root.after(28, animate)

        def pump() -> None:
            try:
                while True:
                    item = self._q.get_nowait()
                    if isinstance(item, tuple):     # (_DONE, linger_ms)
                        # Sets OUR event; the loop below then returns so the
                        # teardown runs on THIS thread (see finally). Never
                        # root.quit() — that flag is shared with every other
                        # Tk in the process and the dot would eat it.
                        root.after(max(0, item[1]), _land_and_close)
                    else:
                        label.config(text=item)
            except queue.Empty:
                pass
            root.after(60, pump)

        animate()
        pump()
        try:
            _pump_until(root, self._closing)
        finally:
            # Tcl_AsyncDelete: the interpreter MUST be torn down on the
            # thread that created it. Left to Python's GC, the after()
            # callbacks keep root alive in a reference cycle that gets
            # collected on whichever thread happens to trigger a
            # collection — and freeing Tcl from the wrong thread aborts
            # the process. Observed: exit code 3 on a clean shutdown.
            import gc
            try:
                _forget_window(root)     # geometry first — see the docstring
                root.destroy()
            except Exception:
                pass
            animate = pump = None                       # noqa: F841
            label = bar = frame = chip = root = None    # noqa: F841
            gc.collect()


def _forget_window(root) -> None:
    """Make Windows repaint the desktop where an overlay used to be.

    Destroying a borderless always-on-top window does not reliably force the
    desktop underneath to redraw. On a STATIC desktop — no other windows, so
    nothing else ever invalidates that region — the pixels of a window that
    no longer exists can sit there indefinitely, which looks exactly like a
    window that refused to close.

    CAVEAT, and a warning about this comment's own history: "the splash
    will not go away" was blamed on that for a while, on the strength of 3
    runs in which the window was destroyed 1.21 s after finish(). The real
    cause of the reports was somewhere else entirely — a shared quit flag,
    see the module docstring — and those 3 runs were simply the half of the
    time it worked. Enumerating the process's windows would have settled it
    in one command, and eventually did: the "leftover pixels" turned out to
    be a live, visible, still-animating window.

    This is kept because the repaint hazard is real and the call is cheap.
    It is NOT evidence that a stuck overlay is a repaint problem — check
    whether the window still exists before assuming that again.

    Called with the geometry read BEFORE the window is destroyed, because
    afterwards there is nothing left to ask.
    """
    try:
        rect = ctypes.wintypes.RECT(*root_rect(root))
    except Exception:
        return
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        # NULL hwnd = the desktop. INVALIDATE|ERASE marks it dirty,
        # UPDATENOW paints it before we return rather than whenever.
        RDW_INVALIDATE, RDW_ERASE = 0x0001, 0x0004
        RDW_ALLCHILDREN, RDW_UPDATENOW = 0x0080, 0x0100
        user32.RedrawWindow(None, ctypes.byref(rect), None,
                            RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN
                            | RDW_UPDATENOW)
    except Exception as e:
        _log.debug("could not repaint behind an overlay: %r", e)


def root_rect(root) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of a Tk window, padded by a pixel so a
    1 px border never survives the repaint."""
    x, y = root.winfo_rootx(), root.winfo_rooty()
    return (x - 1, y - 1,
            x + root.winfo_width() + 1, y + root.winfo_height() + 1)


def _no_activate(root, click_through: bool = False) -> bool:
    """Keep an overlay from stealing focus or appearing in Alt-Tab.

    Module-level, not a method: both overlays need it, and hanging it off
    one of the classes is how the status dot came to die on an
    AttributeError that its own error handling then hid.
    """
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = int(root.winfo_id())
        # The real top-level is the parent of Tk's client window.
        parent = user32.GetParent(hwnd)
        target = parent or hwnd
        user32.GetWindowLongW.restype = ctypes.c_long
        extra = WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        if click_through:
            extra |= WS_EX_TRANSPARENT
        style = user32.GetWindowLongW(target, GWL_EXSTYLE)
        user32.SetWindowLongW(target, GWL_EXSTYLE, style | extra)
        # Read it back. Called before the window is realised, the write
        # lands on nothing and returns success anyway — which is how the
        # dot ended up sitting on the close button, catching clicks.
        got = user32.GetWindowLongW(target, GWL_EXSTYLE)
        if got & extra != extra:
            _log.info("overlay style did not take (wanted %#x, got %#x)",
                      extra, got & 0xffffffff)
            return False
        return True
    except Exception as e:
        _log.debug("could not restyle an overlay window: %r", e)
        return False


# NO `_hide_from_capture` IN THIS MODULE ANY MORE. It was eleven lines
# that set WDA_EXCLUDEFROMCAPTURE on an overlay window, all four of our
# windows called it, and it was deleted on 2026-09-04 at the owner's
# request. The reasoning it carried was sound as far as it went — the dot
# pulses in the corner for as long as a recording is locked on, the
# screenshot key can be pressed while one is, and nobody wants our
# indicator burned into a screenshot they are about to paste into a bug
# report.
#
# What it missed is that the flag is ABSOLUTE. A window carrying it is
# invisible to every grab on the machine, the owner's own included, so
# the notification card announcing that Claude had finished was the one
# thing on his desk he could not photograph. He pressed Win+Shift+S and
# it appeared to vanish. His ask, verbatim in spirit: the screenshot key
# should freeze the screen and take a picture of it AS IT IS, without
# anything disappearing.
#
# ORDERING REPLACES THE FLAG. capture.Controller._shot_flow grabs the
# desktop first, hushes the cards off the LIVE screen on the very next
# line, then maps the selector over the frozen image — so our windows are
# in the picture and out of the drag. The only exception left in the repo
# is capture.py's clip bar, which floats over a MOVING picture it is
# describing: a recording has no single instant to freeze, the bar would
# be in every frame of the mp4, and it cannot be cropped out afterwards.
# Still versus moving is the line, not ours versus theirs. See AGENTS.md.


def _foreground() -> int:
    """The window that has the keyboard right now, as an HWND; 0 if
    Windows will not say. Read BEFORE a notification window is shown:
    by the time it exists, the answer is that window."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        return int(user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def _give_focus_back(hwnd: int) -> None:
    """Hand the keyboard back to whatever had it before a card came up.

    TK TAKES THE FOREGROUND THE MOMENT IT REALISES A WINDOW, and
    WS_EX_NOACTIVATE does not stop it (AGENTS.md, "Tk takes the
    foreground the moment it REALISES a window"): measured with the
    window withdrawn, overrideredirect, topmost and already carrying the
    flag, the foreground was Chrome before `update_idletasks()` and
    TkTopLevel immediately after it. The flag still earns its place — a
    later click no longer activates the window — but the first grab has
    to be UNDONE, which is allowed because at that instant this process
    owns the foreground. Repainting afterwards does not take it again.
    capture.give_focus_back is the same recipe for the same reason; it
    is not imported because capture.py drags in Pillow, Tk canvases and
    a video encoder, and this module is on the startup path.

    A private WinDLL handle, like every argtype declared in this module:
    `ctypes.windll.user32` is one process-wide cached object and a
    restype set on it would change it for every other file.
    """
    if not hwnd:
        return
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetForegroundWindow(ctypes.c_void_p(int(hwnd)))
    except Exception:
        _log.debug("could not hand the foreground back", exc_info=True)


# The transparent-colour key. Any pixel painted exactly this shade is
# punched out of the window, which is what turns a square Tk window into a
# round dot. Deliberately a colour nothing else would pick.
_CHROMA = "#0b0c0d"

# The five states, as skin\palette.DOT_STATES spells them — kept here as
# literals for the same reason as the four above: this module runs before
# ui.py exists, and it is the path with skin\ deleted. Measured against
# #1A1A1A, the darkest wallpaper the dot has to survive: 9.09 / 5.68 /
# 7.62 / 10.36 / 3.46, and every pair separates by light or by hue.
STATES = {
    # state:      (fill,      ring,      pulses)
    "ready":      ("#8fc0f0", "#16232f", False),   # cool: running, listening
    "recording":  ("#ff5b4e", "#3a140f", False),   # red: capturing now
    "locked":     ("#ff8a7e", "#3a140f", True),    # red, breathing: latched
    "busy":       ("#f5c043", "#33260a", False),   # the lamp at full
    # Neutral grey: loaded and alive, but the keys are inert. Deliberately
    # still VISIBLE — a paused app that showed nothing would be
    # indistinguishable from one that was never started, which is the whole
    # problem the dot exists to solve. It is also the only state with NO
    # HALO on the glass path, so it reads by absence and not by hue alone.
    "paused":     ("#6f6f6f", "#1e1e1e", False),
}


class StatusDot:
    """A small always-on-top dot: the app is running, and what it is doing.

    Modelled on the screen-recording indicator, and click-through for the
    same reason one would be: it sits in the top-right corner, which on
    Windows is the close button of every maximised window. WS_EX_TRANSPARENT
    means the click lands on the X underneath, as if the dot were painted
    on the glass.

    Same thread rules as Splash: Tk only on the overlay thread, callers
    only ever put strings on a queue.
    """

    def __init__(self, size: int = 13, margin_x: int = 10,
                 margin_y: int = 6) -> None:
        self._q: queue.Queue = queue.Queue()
        self._size = size
        self._margin = (margin_x, margin_y)
        self._thread: threading.Thread | None = None
        self._alive = threading.Event()
        self._closing = threading.Event()
        self._enabled = True

    @classmethod
    def off(cls) -> "StatusDot":
        obj = cls()
        obj._enabled = False
        return obj

    # -- caller's thread --

    def start(self) -> None:
        if not self._enabled:
            return
        try:
            import tkinter  # noqa: F401
        except Exception:
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="status-dot")
        self._thread.start()
        self._alive.wait(timeout=3)

    def set_state(self, state: str) -> None:
        """Safe to call from the keyboard hook — it only enqueues."""
        if self._thread is not None and state in STATES:
            self._q.put(state)

    def stop(self) -> None:
        if self._thread is not None:
            self._q.put(_DONE)
            self._thread.join(timeout=2)

    # -- overlay thread --

    def _run(self) -> None:
        try:
            if skin is not None and skin.dot_run(self):   # --- SKIN
                return
            self._build_and_loop()
        except Exception as e:
            _log.info("status dot unavailable: %r", e)
        finally:
            self._alive.set()

    def _build_and_loop(self) -> None:
        import tkinter as tk

        pad = 3                                   # room for the ring
        box = self._size + pad * 2
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=_CHROMA)
        root.attributes("-transparentcolor", _CHROMA)

        canvas = tk.Canvas(root, width=box, height=box, bg=_CHROMA,
                           highlightthickness=0)
        canvas.pack()
        ring = canvas.create_oval(1, 1, box - 1, box - 1, fill="", width=2)
        dot = canvas.create_oval(pad, pad, pad + self._size, pad + self._size,
                                 width=0)

        sw = root.winfo_screenwidth()
        mx, my = self._margin
        root.geometry(f"{box}x{box}+{sw - box - mx}+{my}")
        # Realise the window first: SetWindowLongW on an unrealised Tk
        # window silently does nothing and still reports success.
        root.update_idletasks()
        _no_activate(root, click_through=True)
        # THE DOT USED TO EXCLUDE ITSELF FROM CAPTURE HERE. Removed
        # 2026-09-04 at the owner's request: he wants the screenshot key
        # to freeze the screen and photograph it AS IT IS, and a window
        # carrying WDA_EXCLUDEFROMCAPTURE is invisible to every grab on
        # the machine — his own included — so it appears to vanish the
        # instant he reaches for the key. The dot is small and it is in
        # the corner; being in a picture of the corner is not a bug.
        # What keeps it out of the way now is the ORDER in
        # capture.Controller._shot_flow, not a flag.
        self._alive.set()

        state = {"name": "ready", "phase": 0.0}

        def paint() -> None:
            fill, ring_col, pulses = STATES[state["name"]]
            if pulses:
                # A slow breath, so a recording you walked away from still
                # reads as live rather than as a frozen red dot.
                state["phase"] = (state["phase"] + 0.06) % 6.283
                k = 0.55 + 0.45 * (0.5 + 0.5 * math.cos(state["phase"]))
                fill = _mix(fill, _CHROMA, k)
            canvas.itemconfig(dot, fill=fill)
            canvas.itemconfig(ring, outline=ring_col)
            root.after(45, paint)

        def pump() -> None:
            try:
                while True:
                    item = self._q.get_nowait()
                    if item is _DONE:
                        self._closing.set()   # ours alone — never root.quit()
                        return
                    state["name"] = item
                    state["phase"] = 0.0
            except queue.Empty:
                pass
            root.after(60, pump)

        paint()
        pump()
        try:
            _pump_until(root, self._closing)
        finally:
            import gc                       # see Splash: same Tcl teardown
            try:
                _forget_window(root)        # and the same repaint rule
                root.destroy()
            except Exception:
                pass
            paint = pump = None                       # noqa: F841
            canvas = dot = ring = root = None         # noqa: F841
            gc.collect()


def _mix(colour: str, towards: str, k: float) -> str:
    """Blend two #rrggbb colours; k=1 keeps `colour`."""
    a = [int(colour[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(towards[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(
        max(0, min(255, round(x * k + y * (1 - k)))) for x, y in zip(a, b))


# "never moved". NOT -1: a monitor to the left of the primary has real
# negative screen coordinates — measured here, the virtual desktop starts
# at x = -1920 — so -1 threw away every card that was dragged onto it. The
# sentinel has to be a number no desktop can reach. Mirrors
# config.HINT_UNSET; a test asserts the two agree.
HINT_UNSET = -100000


class HintCard:
    """The card that says what the keys will do while one is held down.

    Third of the on-screen things, and the only one with something to
    READ on it. Same contract as StatusDot — its own thread, its own Tk
    interpreter, callers only ever put items on a queue — for the same
    three reasons: Tk is not thread-safe, `quit()` is a module-level
    global that would close the other overlay's loop, and an overlay that
    can take the app down is not an overlay.

    THE DELAY IS THE FEATURE. `after_ms` is not a fade-in: nothing is
    created until the key has been down that long, so an ordinary
    two-second dictation never puts a window on screen at all. The card is
    for the press someone hesitated on.

    IT USED TO BE INVISIBLE TO SCREENSHOTS, and that was the wrong
    reading of the problem. The argument was that Win+Shift+S now works
    mid-dictation, so the one moment this card is on screen is the moment
    a screenshot is most likely to be taken — true, but the fix was a
    flag that hid the card from the OWNER's grabs as well as from
    everyone else's. Removed 2026-09-04. What the card actually has to do
    is stay out of the DRAG, and it does that by being hushed off the
    live screen after the freeze, not by being absent from the picture.

    Click-through, like the dot, and for the identical hard-won reason:
    `top-right` is the close button of every maximised window. The "don't
    show this again" row is therefore drawn as a place to look, and turned
    off in the dashboard — the card cannot take a click without also
    taking the ones aimed at the X underneath it.
    """

    def __init__(self, after_ms: int = 400, corner: str = "top-right",
                 margin: int = 14, x: int = HINT_UNSET, y: int = HINT_UNSET,
                 scale: float = 1.0, on_change=None) -> None:
        self._q: queue.Queue = queue.Queue()
        self._after = max(0, int(after_ms)) / 1000.0
        self._corner = corner
        self._margin = margin
        # Where the owner dragged it to and how big they made it. -1 means
        # never moved: `corner` decides. Written from the overlay thread
        # when a drag ends or a size button is pressed, and handed to
        # `on_change` so main.py can put it in config.toml — the card is
        # the only thing that knows these, and it has to survive a restart
        # or "I moved it" lasts exactly one dictation.
        self.x, self.y = int(x), int(y)
        self.scale = float(scale)
        self._on_change = on_change
        self._thread: threading.Thread | None = None
        self._alive = threading.Event()
        self._closing = threading.Event()
        self._enabled = True
        # SET WHILE A SELECTION IS ON SCREEN, by whoever is taking the
        # screen. An Event and not a flag because it is written from the
        # keyboard hook and read from the card's own loop, and because
        # setting one touches no Tk at all — see hush().
        self._hushed = threading.Event()

    @classmethod
    def off(cls) -> "HintCard":
        obj = cls()
        obj._enabled = False
        return obj

    # -- caller's thread --

    def start(self) -> None:
        if not self._enabled:
            return
        try:
            import tkinter  # noqa: F401
        except Exception:
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="hint-card")
        self._thread.start()
        self._alive.wait(timeout=3)

    def hush(self) -> None:
        """Stay off the live screen until unhush(), and stop the clock.

        THIS IS WHAT REPLACED WDA_EXCLUDEFROMCAPTURE, and it is the whole
        reason dropping that flag on 2026-09-04 did not trade one bug for
        another. Our cards are `-topmost`. The screenshot selector maps
        AFTER them, so it is above the ones already up — but a card that
        arrives or re-shows in the middle of a drag maps above the
        SELECTOR and eats the drag, and a notification landing while the
        owner is dragging is precisely when that happens. Hushed, the
        loop takes the window down and refuses to map a new one; the item
        is not lost and its seconds are not spent, because the clock
        waits exactly the way it waits under the pointer.

        SETS AN EVENT AND RETURNS — no Tk, no queue, no wait. It is
        called from `capture.Controller.begin_shot`, which main.py runs
        inside the OS keyboard hook, and hotkey.py's budget there is
        300 ms: overrun it and Windows unhooks with nothing logged. There
        is deliberately no settle-wait like `capture.ShotCards.hush()`'s,
        because none is needed here: whatever is up when the selector
        maps is already underneath it, and the only window that could get
        ON TOP is one mapped later, which is the case this refuses.
        """
        self._hushed.set()

    def unhush(self) -> None:
        """The screen is the owner's again. Put the card back if it still
        has something to say, with the seconds it had when it went down."""
        self._hushed.clear()

    def show(self, card: dict | None) -> None:
        """Put a card up, or take it down with None.

        Safe from the keyboard hook — it only enqueues, which is the whole
        reason the drawing lives on another thread. A card that arrives
        while one is already up replaces it without the delay running
        again: hold, then latch, and the panel changes in place.
        """
        if self._thread is not None and self._enabled:
            self._q.put(card)

    # -- the overlay thread's way of reporting what the owner did --

    def placed(self, x: int, y: int) -> None:
        """Remember where a drag left it, and write it down.

        `x, y` IS THE VISIBLE CARD'S TOP-LEFT, not the window's, and the
        difference is a bug that shipped: the glass window is bigger than
        the card by the room it leaves for its own shadow, so its corner
        sits 26 px above and left of anything you can see. Saving that
        made every drag near the top of the screen store a NEGATIVE y —
        which `-1` claims as "never moved" — so the card snapped back to
        the corner, and only drags that ended more than 26 px down stuck.
        Storing what the owner can actually see keeps the sentinel out of
        reach and makes the number in config.toml one they could type.

        Clamped at zero for the same reason. A card dragged half off the
        top-left is still a card you can grab; a negative saved position
        is one the next launch throws away.

        NOT clamped to positive. A monitor to the left of the primary has
        genuinely negative screen coordinates — measured here, the virtual
        desktop starts at x = -1920 — so a card dragged onto that screen
        has a real negative x, and refusing it would drag the card back
        onto the primary every time. That is why UNSET is a number no
        desktop can reach rather than -1.

        A drag ends in more than one message, so an unchanged position is
        not written again — this is the line editor's most frequent
        caller and it rewrites config.toml every time.
        """
        x, y = int(x), int(y)
        if (x, y) == (self.x, self.y):
            return
        self.x, self.y = x, y
        self._changed(x=self.x, y=self.y)

    def resized(self, scale: float) -> None:
        self.scale = float(scale)
        self._changed(scale=round(self.scale, 3))

    def dismissed(self) -> None:
        """The box on the card was ticked: never again, and not just for
        this run — the whole point of a "don't show this again" is that it
        outlives the thing it was ticked on."""
        self._enabled = False
        self._changed(enabled=False)

    def _changed(self, **fields) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(fields)
        except Exception:
            _log.info("could not save the hint card's %s",
                      ", ".join(fields), exc_info=True)

    def stop(self) -> None:
        if self._thread is not None:
            self._q.put(_DONE)
            self._thread.join(timeout=2)

    # -- overlay thread --

    def _run(self) -> None:
        try:
            if skin is not None and skin.hint_run(self):   # --- SKIN
                return
            self._build_and_loop()
        except Exception as e:
            _log.info("hint card unavailable: %r", e)
        finally:
            self._alive.set()

    # The status dot's corner, which this never takes. The dot is the one
    # thing on screen that says the app is alive; it does not move for a
    # panel that is only up while a key is held.
    DOT_ROOM = 46

    UNSET = HINT_UNSET

    def moved(self) -> bool:
        return self.x > self.UNSET and self.y > self.UNSET

    def origin(self, width: int, height: int, screen: tuple[int, int],
               inset: int = 0, bounds: tuple[int, int, int, int] | None = None
               ) -> tuple[int, int]:
        """Where the window's top-left goes.

        `inset` is the transparent margin the picture leaves around itself
        for its own shadow, so both the glass card (which has one) and the
        Tk card (which does not) put the VISIBLE edge in the same place.

        `screen` is the PRIMARY monitor, which is where the corners are.
        `bounds` is the whole virtual desktop — every monitor — and it is
        what a saved position is clamped against, because clamping to the
        primary would walk a card off a second screen and back onto this
        one every time the app restarted.

        A saved position wins over the corner, and is still clamped: a
        card dragged onto a monitor that is no longer plugged in must not
        come back somewhere nobody can reach it.

        Pure arithmetic, so a test can check every corner and every saved
        position without a screen.
        """
        sw, sh = screen
        m = self._margin
        if self.moved():
            # Saved as the CARD's top-left (see placed); the window starts
            # `inset` above and left of it.
            vx, vy, vw, vh = bounds if bounds else (0, 0, sw, sh)
            keep = 60                      # this much must stay reachable
            card_w, card_h = width - inset * 2, height - inset * 2
            x = max(vx + keep - card_w, min(self.x, vx + vw - keep))
            y = max(vy + keep - card_h, min(self.y, vy + vh - keep))
            return int(x - inset), int(y - inset)
        # Beside the dot, not under it: on the right-hand corners the card
        # stops short of the dot's own square by DOT_ROOM.
        room = self.DOT_ROOM if self._corner == "top-right" else 0
        if self._corner.endswith("left"):
            x = m - inset
        else:
            x = sw - m - room - width + inset
        y = (m - inset if self._corner.startswith("top")
             else sh - m - height + inset)
        return int(x), int(y)

    def _build_and_loop(self) -> None:
        """The fallback picture: flat Tk, no glass.

        skin\\hint.py draws the real one on a layered window with per-pixel
        alpha. Tk cannot do that at all — `-transparentcolor` is a chroma
        key and Tk antialiases nothing — so what this paints is the same
        card with a solid face. Deleting skin\\ costs the glass and keeps
        the card, which is the rule the whole skin is built on.
        """
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()                    # nothing on screen until asked
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=CARD_BG)
        canvas = tk.Canvas(root, bg=CARD_BG, highlightthickness=0, bd=0)
        canvas.pack()
        self._alive.set()

        shown = {"card": None, "due": None, "up": False}

        def hide() -> None:
            if shown["up"]:
                root.withdraw()
                shown["up"] = False

        def draw(card: dict) -> None:
            w, h = _hint_paint(canvas, card, self.scale)
            canvas.configure(width=w, height=h)
            x, y = self.origin(w, h, (root.winfo_screenwidth(),
                                      root.winfo_screenheight()))
            root.geometry(f"{w}x{h}+{x}+{y}")
            root.deiconify()
            root.update_idletasks()
            if not shown["up"]:
                # Needs a realised window and silently succeeds on an
                # unrealised one — the bug that put the dot on the close
                # button. After deiconify, every time.
                _no_activate(root, click_through=True)
                # The `_hide_from_capture(root)` that stood here went on
                # 2026-09-04, at the owner's request: this card is not
                # allowed to disappear from his own screenshots. The
                # ordering in capture.Controller._shot_flow keeps it off
                # the live screen for the drag; see the class docstring.
            shown["up"] = True

        def pump() -> None:
            try:
                while True:
                    item = self._q.get_nowait()
                    if item is _DONE:
                        self._closing.set()
                        return
                    if item is None:
                        shown["card"] = shown["due"] = None
                        hide()
                    else:
                        # Already up: swap the picture now. Not up yet:
                        # keep the deadline that is already running rather
                        # than restarting it, so hold-then-latch does not
                        # pay the delay twice.
                        if shown["due"] is None and not shown["up"]:
                            shown["due"] = time.monotonic() + self._after
                        shown["card"] = item
                        if shown["up"]:
                            draw(item)
            except queue.Empty:
                pass
            due, card = shown["due"], shown["card"]
            if card is not None and not shown["up"] and due is not None \
                    and time.monotonic() >= due:
                draw(card)
            root.after(40, pump)

        pump()
        try:
            _pump_until(root, self._closing)
        finally:
            import gc                       # see Splash: same Tcl teardown
            try:
                _forget_window(root)
                root.destroy()
            except Exception:
                pass
            draw = pump = hide = None                 # noqa: F841
            canvas = root = None                      # noqa: F841
            gc.collect()


class WordPrompt:
    """One line, one question: what should this word be?

    The pencil on the review card. Unlike every other window in this
    module it TAKES the keyboard, on purpose — a box you type into must —
    and only because the owner just clicked for it. Own thread, own Tk
    interpreter, destroyed and collected on that thread (the same burial
    the cards get). Enter answers with the text, Escape answers None;
    either way the box is gone before `on_done` is called, so the app
    underneath has its focus back by the time anything is learned or
    pasted.
    """

    WIDTH, HEIGHT = 300, 86

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._result: dict = {"text": None}
        self._closing = threading.Event()
        self._q: queue.Queue = queue.Queue()

    def ask(self, initial: str, near, on_done, prompt: str = "מה התכוונת?",
            focus: bool = True) -> bool:
        """Open the box below `near` (a screen rect, or None). One at a
        time: a second question while one is open is dropped. `focus`
        is the keyboard grab; a test passes False and answers through
        `answer` instead of typing — a synthetic Enter aimed at a box
        that did not get the foreground lands in the owner's window."""
        if self._thread is not None and self._thread.is_alive():
            return False
        self._result = {"text": None}
        self._closing = threading.Event()
        # Fresh per question, like the other two: a transcript that landed
        # on a box already closing must not turn up inside the next one.
        self._q = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, args=(initial, near, on_done, prompt, focus),
            daemon=True, name="review-edit")
        self._thread.start()
        return True

    def answer(self, text) -> None:
        """Close the box with `text` (None = as Escape would), from any
        thread. What Enter and Escape do, reachable without a keyboard."""
        self._result["text"] = text
        self._closing.set()

    def fill(self, text: str) -> bool:
        """Put a dictated line IN the box without sending it, any thread.

        A problem report is spoken, not typed (mixed Hebrew/English in an
        Entry renders scrambled), so main.py hands the transcript here.
        False means no box is open and it should keep the text some other
        way — nothing dictated is ever dropped on the floor. Only enqueues:
        the box's own thread does the typing, which is the whole reason
        there is a queue. Deliberately not `answer`, which IS Enter — a
        report the decoder may have misheard must be read before it is
        filed."""
        if not self.open():
            return False
        self._q.put(text or "")
        return True

    def open(self) -> bool:
        return (self._thread is not None and self._thread.is_alive()
                and not self._closing.is_set())

    @staticmethod
    def _take_focus(root, entry) -> None:
        """visual_qa.take_foreground's recipe: SetForegroundWindow first
        (this process just took a click, so it may), the Alt tap only if
        that bounced — an Alt the app underneath also sees arms its menu
        bar, which is a price worth paying only when needed."""
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            hwnd = int(root.winfo_id())
            target = user32.GetParent(hwnd) or hwnd
            user32.SetForegroundWindow(target)
            root.focus_force()
            entry.focus_set()
            root.update()
            time.sleep(0.05)
            if user32.GetForegroundWindow() != target:
                user32.keybd_event(0xA4, 0, 0, 0)       # Alt down
                user32.keybd_event(0xA4, 0, 2, 0)       # Alt up
                user32.SetForegroundWindow(target)
                root.focus_force()
                entry.focus_set()
        except Exception:
            _log.debug("word prompt: could not take the keyboard",
                       exc_info=True)

    def _run(self, initial, near, on_done, prompt, focus=True) -> None:
        import gc
        import tkinter as tk
        result = self._result
        closing = self._closing
        root = entry = None
        try:
            root = tk.Tk()
            root.withdraw()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.configure(bg=CARD_BG, highlightthickness=1,
                           highlightbackground=CARD_KEY_EDGE)
            # Pure Hebrew, so a plain Label lays it out right (mixed
            # strings are the ones Tk scrambles); the word being typed
            # is one word and gets the same pass.
            tk.Label(root, text=prompt, bg=CARD_BG, fg=CARD_DIM,
                     font=("Rubik", 9)).pack(anchor="e", padx=14,
                                             pady=(10, 2))
            entry = tk.Entry(root, bg=CARD_KEY_BG, fg=CARD_FG,
                             insertbackground=CARD_FG, bd=0,
                             highlightthickness=1,
                             highlightbackground=CARD_KEY_EDGE,
                             highlightcolor=CARD_KEY_FG,
                             font=("Rubik", 13), justify="right")
            entry.pack(fill="x", padx=14, pady=(0, 12), ipady=4)
            entry.insert(0, initial or "")
            entry.select_range(0, "end")
            entry.icursor("end")

            def done(_event=None) -> None:
                result["text"] = entry.get().strip()
                closing.set()

            def cancel(_event=None) -> None:
                closing.set()

            def pump() -> None:
                """Dictated text, typed in on the box's own thread — the
                recorder's thread touching this Entry would take the
                interpreter down with it. It replaces the line (what was
                there is a draft) and pointedly does NOT set `closing`:
                filling is not filing. The owner reads what came back,
                fixes it if the decoder misheard, and presses Enter."""
                try:
                    while True:
                        text = self._q.get_nowait()
                        entry.delete(0, "end")
                        entry.insert(0, text)
                        entry.icursor("end")
                except queue.Empty:
                    pass
                except Exception:
                    return          # box gone underneath us: nothing to do
                root.after(60, pump)

            entry.bind("<Return>", done)
            entry.bind("<KP_Enter>", done)
            entry.bind("<Escape>", cancel)
            if near:
                x, y = int(near[0]), int(near[3]) + 8
            else:
                x = (root.winfo_screenwidth() - self.WIDTH) // 2
                y = (root.winfo_screenheight() - self.HEIGHT) // 2
            root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
            root.deiconify()
            root.update_idletasks()
            if focus:
                self._take_focus(root, entry)
            pump()
            _pump_until(root, closing)
        except Exception as e:
            _log.info("the word prompt could not open: %r", e)
        finally:
            try:
                if root is not None:
                    _forget_window(root)
                    root.destroy()
            except Exception:
                pass
            entry = root = None                          # noqa: F841
            gc.collect()
        try:
            on_done(result["text"])
        except Exception:
            _log.info("word prompt: could not report the answer",
                      exc_info=True)


def _round_corners(root, border=None) -> None:
    """Take the corners off a window that has no frame to round them.

    dashboard._round_frameless, on this side of the pipe, and its
    measurement is the one that matters here too: a card painted flat to
    its own edges leaves four little squares of card colour sitting on top
    of whatever is really behind it, and the three ways out were measured
    on 2026-09-04. Chroma key cuts a true hole but keys one exact colour
    and antialiases nothing, so the curve comes out as stairs. Doing
    nothing leaves the squares. DWM attribute 33
    (DWMWA_WINDOW_CORNER_PREFERENCE = 2) clips the WINDOW ITSELF and
    antialiases the clip against the real desktop, on a WS_POPUP window,
    which is what overrideredirect makes. Attribute 34 is the hairline
    around that clip, and the only thing left saying where the card ends
    on a pale background.

    Copied rather than imported, and that is the deliberate half: this
    module is reached with dashboard.py never imported at all — main.py
    runs with no window open most of the time — and importing the whole
    dashboard from an overlay to borrow twelve lines of ctypes would drag
    a Tk widget library onto a hotkey press. Windows 10 has neither
    attribute and silently keeps both: a square card, which is still the
    card alone and not a card in a box.
    """
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(int(root.winfo_id())) \
            or int(root.winfo_id())
        pref = ctypes.c_int(2)                       # 2 = round
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(pref), 4)
        if border:
            r, g, b = (int(border[i:i + 2], 16) for i in (1, 3, 5))
            colour = ctypes.c_int((b << 16) | (g << 8) | r)   # 0x00BBGGRR
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 34, ctypes.byref(colour), 4)
    except Exception as e:              # noqa: BLE001
        _log.debug("could not round a frameless window: %r", e)


# problems.TEXT_MAX, spelled out for the same reason review_card spells out
# a palette: this module is reached on a machine where reporting is off and
# problems.py may not import at all — an overlay that cannot draw a card
# because a feature module is missing is worse than a card with a number
# in it. The field stops taking words at this length, so it has to be
# readable without that import. IT IS A COPY AND COPIES DRIFT: the pair
# wants an assertion in tests.py that this equals problems.TEXT_MAX, which
# is a file this change does not own and is named in the handover.
_TEXT_MAX = 600


class ProblemCard(WordPrompt):
    """Say what is wrong, from wherever you are — the hotkey's card.

    A SUBCLASS OF WordPrompt, and that is the whole design decision.
    Everything in this module except WordPrompt is WS_EX_NOACTIVATE or
    WS_EX_TRANSPARENT on purpose (_no_activate says why: you may well be
    typing when one appears), so ReviewCard can be clicked and cannot be
    typed into, and a card that asks for a sentence has to inherit from
    the one window here that TAKES THE KEYBOARD. What it inherits is
    exactly the four things that were hard: `_take_focus`'s
    SetForegroundWindow-then-Alt recipe, `open()`, `answer()` — what Enter
    does, reachable from any thread — and `fill()`, which puts a dictated
    line in the field WITHOUT sending it.

    Growing WordPrompt itself into this card was the other route and it
    was rejected: its `_run` would have become a two-hundred-line body
    with a mode flag through the middle of it, and the plain one-line box
    is the review card's pencil — "מה התכוונת?", the thing the owner uses
    daily — which must look and behave exactly as it does today. A
    subclass leaves that path byte-for-byte untouched and provable: the
    only members overridden here are `ask` and `_run`, and the pencil
    calls neither of this class's.

    THE FACE IS A PICTURE. problem_card paints the whole card — the
    eyebrow, the question, the field's well, the bidi echo, the five
    chips, the screenshot and the two buttons — as one Pillow image, the
    way review_card paints the second-reading card, and this window shows
    it, positions a real tk.Text over the painted well, and turns a click
    or a key into an answer. Nothing here computes a coordinate:
    problem_card.regions is read by both the painter and the hit test,
    which is what keeps a chip pressed where it is drawn.

    The answer goes out through `on_done(text, kind)` on this thread,
    after the window is down — text None for Escape or Cancel, and the
    chip he picked either way.

    IT IS DRAGGED LIKE ITS SIBLINGS, and by the same rule: the whole face
    is the handle except the parts that do something. `x`, `y` and
    `on_change` are HintCard's three, spelled out here rather than
    inherited because this class comes down the WordPrompt side of the
    tree — see `placed`.
    """

    UNSET = HINT_UNSET

    def __init__(self, x: int = HINT_UNSET, y: int = HINT_UNSET,
                 on_change=None) -> None:
        super().__init__()
        # Where the owner dragged it to. HINT_UNSET — not -1 — means
        # "never moved", for the reason spelled out where that constant is
        # defined: a monitor left of the primary has genuinely negative
        # coordinates, so the sentinel has to be a number no desktop can
        # reach. Kept on the instance, so the position survives from one
        # hotkey press to the next even before it survives a restart.
        self.x, self.y = int(x), int(y)
        self._on_change = on_change

    def moved(self) -> bool:
        return self.x > self.UNSET and self.y > self.UNSET

    def placed(self, x: int, y: int) -> None:
        """Remember where a drag left it, and write it down.

        HintCard.placed, on this side of the tree, and its two hard-won
        rules hold here too. `x, y` is the VISIBLE card's top-left, which
        for this window IS the window's — there is no shadow inset to get
        wrong, because this card is not on glass. And an unchanged
        position is not written again: a drag ends in more than one
        message and every one of them would otherwise rewrite
        config.toml.

        `on_change` is handed a dict of the fields that changed, exactly
        as the hint, review and notify cards hand theirs to main.py's
        `_save_*` — so main.py's half of this is the same six lines it
        already has three times, and the keys it writes are the same
        `x`/`y` under this card's own config section.
        """
        x, y = int(x), int(y)
        if (x, y) == (self.x, self.y):
            return
        self.x, self.y = x, y
        if self._on_change is None:
            return
        try:
            self._on_change({"x": self.x, "y": self.y})
        except Exception:
            _log.info("could not save where the report card was dragged to",
                      exc_info=True)

    def ask(self, where: str, on_done, *, shot=None, kinds=None, near=None,
            focus: bool = True) -> bool:
        """Open the card. One at a time, like the base's.

        `shot` is the screen that goes with the report and takes JPEG
        BYTES, which is the shape main.py has it in: the grab happens
        before this window exists, or the report is a photograph of the
        question rather than of the problem, and the bytes are not filed
        anywhere until he presses Send — problems.pin_shot writes what it
        is handed, so a card he escapes must leave nothing on disk. A path
        is accepted too (that is what a stored report has) and None means
        no picture, which is a card without a thumbnail rather than an
        error.

        `focus` is the keyboard grab; a test passes False and answers
        through `answer` instead of typing, because a synthetic Enter
        aimed at a box that did not get the foreground lands in whatever
        window did.
        """
        if self._thread is not None and self._thread.is_alive():
            return False
        self._result = {"text": None, "kind": ""}
        self._closing = threading.Event()
        self._q = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, args=(where, on_done, shot, kinds, near, focus),
            daemon=True, name="problem-card")
        self._thread.start()
        return True

    def _run(self, where, on_done, shot=None, kinds=None, near=None,
             focus=True) -> None:
        """The card, on its own thread and its own Tk interpreter.

        Overriding `_run` rather than adding a second thread body: `ask`
        is overridden with it and is the only thing that ever names it, so
        the two cannot come apart. Inheriting the base's `_run` here would
        leave a ProblemCard able to open a plain one-line word box, which
        is a trap rather than a feature.
        """
        import gc
        import tkinter as tk

        import problem_card as pc
        from PIL import ImageTk

        result = self._result
        closing = self._closing
        # Declared before the try so the burial in `finally` can name them
        # whichever line failed — HintCard's `draw = pump = hide = None`,
        # for the same reason and with more to bury.
        root = field = canvas = paint = refresh = pump = None
        st: dict = {}
        cache: dict = {}
        try:
            card = pc.card_for(where, kinds=kinds, shot=shot)
            result["kind"] = card["kind"]
            root = tk.Tk()
            root.withdraw()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.configure(bg=pc.hex_of("CARD"))
            canvas = tk.Canvas(root, bg=pc.hex_of("CARD"),
                               highlightthickness=0, bd=0)
            canvas.place(x=0, y=0)

            # THE CARD GROWS DOWNWARD AND DOES NOT WANDER. The field grows
            # as he writes, so the card's height is not known when it is
            # placed, and the three ways to handle that are not equal.
            # Recentring on every repaint walks the whole card up the
            # screen a line at a time while he is looking at it, which is
            # the one thing a box being typed into must not do. Reserving
            # the tallest it could ever be — eight field lines and a
            # five-line echo — holds the position still but sits a
            # three-line report about 150 px above centre, which is where
            # nothing is. So it is centred ONCE for the height it opens
            # at, grows down from that top, and moves only if growing
            # down would take the buttons off the bottom of the screen:
            # the one case where staying put is worse than moving.
            screen_w = root.winfo_screenwidth()
            screen_h = root.winfo_screenheight()
            _w0, h0 = pc.measure(card, cache)
            # THE WHOLE DESKTOP, not the primary monitor, and this is
            # HintCard.origin's `bounds` argument by another route. The
            # primary is where the CENTRE is — a card with no saved
            # position opens in the middle of the screen he is looking at
            # — but it is the wrong thing to clamp against: measured on
            # this machine the virtual desktop starts at x = -1920, so a
            # card he dragged onto the left monitor has a genuinely
            # negative x, and clamping it to the primary would walk it
            # back onto the primary every single time. Falls back to the
            # primary if the metrics are not there, which is the same
            # answer ReviewCard has always given.
            try:
                m = ctypes.windll.user32.GetSystemMetrics
                bounds = (m(76), m(77), m(78), m(79))   # SM_*VIRTUALSCREEN
                if bounds[2] <= 0 or bounds[3] <= 0:
                    raise ValueError(bounds)
            except Exception:                 # noqa: BLE001
                bounds = (0, 0, screen_w, screen_h)
            if self.moved():
                # WHERE HE PUT IT LAST WINS over the middle of the screen,
                # and it is still clamped — HintCard.origin's rule and its
                # reason: a card dragged onto a monitor that is no longer
                # plugged in must not come back somewhere nobody can reach
                # it. `keep` is how much of the card has to stay on the
                # desktop to be grabbable, so a card parked half off the
                # left edge is restored half off the left edge and a card
                # saved on a screen that is gone is not.
                keep = 60
                bx, by, bw, bh = bounds
                at_x = max(bx + keep - pc.CARD_W, min(self.x, bx + bw - keep))
                at_y = max(by + keep - h0, min(self.y, by + bh - keep))
            elif near:
                at_x, at_y = int(near[0]), int(near[3]) + 8
            else:
                at_x = (screen_w - pc.CARD_W) // 2
                at_y = max(0, (screen_h - h0) // 2)

            # A tk.Text, not a tk.Entry, and the owner's words for the
            # Entry were "very slop and strict": one 30 px line with the
            # sentence jammed against the border, for a field whose real
            # limit is problems.TEXT_MAX — six hundred characters. So it
            # is a wrapping Text that starts three lines tall and grows to
            # eight, with FIELD_PAD_X/Y of interior room; spacing3 makes
            # the widget's own line height agree to the pixel with the
            # painter's FIELD_LINE_H, which it must, since the painter
            # draws the well from a line count this widget reports.
            #
            # No border and no highlight on the widget itself: the well
            # around it is painted, and a Tk border inside a painted one
            # is two edges of different curvature. Hebrew is right-aligned
            # through a tag re-applied on every change, because a tag does
            # not extend itself over text inserted after it.
            #
            # MEASURED, and the reason the echo line below exists at all:
            # a tk.Text scrambles a mixed Hebrew/English line EXACTLY the
            # way a tk.Entry does. Typing "הכפתור של Settings לא עובד אחרי
            # restart" into either one draws as "restart לא עובד אחרי
            # Settings הכפתור של" — checked in the two widgets side by
            # side on 2026-09-04, because growing the field was a change
            # of widget and a change of widget is a change of bidi. Every
            # character is right; only the drawing lies.
            field = tk.Text(root, bg=pc.hex_of("EDGE"), fg=pc.hex_of("FG"),
                            insertbackground=pc.hex_of("ACCENT"),
                            selectbackground=pc.hex_of("ACCENT_SOFT"),
                            selectforeground=pc.hex_of("FG"),
                            bd=0, highlightthickness=0, relief="flat",
                            wrap="word", undo=True, font=pc.FIELD_FONT,
                            spacing3=max(0, pc.FIELD_LINE_H
                                         - pc.FIELD_FONT_LINE),
                            insertwidth=2, padx=0, pady=0)
            field.tag_configure("rtl", justify="right")

            st.update({"typed": None, "lines": 0, "hover": None,
                       "photo": None, "size": (0, 0),
                       "x": at_x, "y": at_y,
                       "drag": None, "from": None, "travel": 0})

            def wrapped() -> int:
                """How many lines the widget is actually showing.

                Asked of the widget rather than guessed from the string
                length: it is the widget that wrapped it, and the well is
                drawn to this number. `count` returns a one-tuple in some
                Tk builds and a bare int in others, so both are unwrapped;
                problem_card.field_lines is the estimate for a build that
                has neither, and for the headless render where there is no
                widget at all.
                """
                try:
                    got = field.count("1.0", "end", "displaylines")
                except Exception:                     # noqa: BLE001
                    return pc.field_lines(st["typed"] or "")
                if isinstance(got, (tuple, list)):
                    got = got[0] if got else 1
                return max(1, int(got or 1))

            def place_field(box) -> None:
                field.place(x=pc.PAD + box[0] + pc.FIELD_PAD_X,
                            y=pc.PAD + box[1] + pc.FIELD_PAD_Y,
                            width=pc.INNER - 2 * pc.FIELD_PAD_X,
                            height=box[3] - box[1] - 2 * pc.FIELD_PAD_Y)

            def paint() -> None:
                img = pc.compose(card, cache)
                photo = ImageTk.PhotoImage(img, master=root)
                canvas.delete("all")
                canvas.configure(width=img.width, height=img.height)
                canvas.create_image(0, 0, anchor="nw", image=photo)
                st["photo"] = photo          # Tk keeps no reference
                if st["size"] != (img.width, img.height):
                    st["size"] = (img.width, img.height)
                    # Growing DOWN must not put the buttons under the
                    # bottom edge of the desktop he is on. Against
                    # `bounds` for the same reason the restore clamp is:
                    # the card may well be on the second monitor.
                    floor = bounds[1] + bounds[3] - 8
                    if st["y"] + img.height > floor:
                        st["y"] = max(bounds[1], floor - img.height)
                    root.geometry("%dx%d+%d+%d" % (img.width, img.height,
                                                   st["x"], st["y"]))
                place_field(pc.layout(card, cache)["field"])

            def refresh() -> None:
                """Repaint if anything the picture shows has changed.

                Driven from the pump below rather than from a key binding,
                and that is the point: the line does not always arrive
                from the keyboard. THE CARD CAN BE DICTATED INTO — `fill`
                puts a transcript in the field with no <KeyRelease> behind
                it at all — and it can be pasted into and undone. Reading
                the widget on a timer catches every one of them, which is
                the only way the echo underneath can be trusted to be
                showing what is really in the field.
                """
                typed = field.get("1.0", "end-1c")
                if len(typed) > _TEXT_MAX:
                    # problems.clean would cut it silently on the way to
                    # disk; better he sees the field stop taking words than
                    # discover the tail missing in a report he can no
                    # longer edit.
                    field.delete("1.0+%dc" % _TEXT_MAX, "end")
                    typed = field.get("1.0", "end-1c")
                field.tag_add("rtl", "1.0", "end")
                lines = min(pc.FIELD_LINES_MAX,
                            max(pc.FIELD_LINES_MIN, wrapped()))
                if (typed, lines) == (st["typed"], st["lines"]):
                    return
                st["typed"], st["lines"] = typed, lines
                card["typed"], card["lines"] = typed, lines
                paint()

            def send(_event=None) -> str:
                result["text"] = field.get("1.0", "end-1c").strip()
                result["kind"] = card["kind"]
                closing.set()
                return "break"

            def cancel(_event=None) -> str:
                result["text"] = None
                closing.set()
                return "break"

            def newline(_event=None) -> str:
                """Shift+Enter is the new line, Enter is Send.

                Deliberate, and stated on the card (problem_card.KEYS):
                once the field is more than one line the two cannot both
                be Enter, and a report is a sentence he wants sent rather
                than a document he is composing. Bound explicitly rather
                than left to Tk's own class binding, because the <Return>
                binding above fires for a shifted Return too unless
                something more specific claims it.
                """
                field.insert("insert", "\n")
                return "break"

            def pick(name: str) -> None:
                if name != card["kind"]:
                    card["kind"] = name
                    result["kind"] = name
                    paint()

            # A release that travelled less than this is a click, not a
            # drag. NotifyCard's own number and its own name, because it
            # is the same judgement about the same gesture — four pixels
            # is more than a hand shakes on a click and less than anyone
            # means by "move it".
            CLICK_PX = 4

            def control_at(event):
                """The control under the pointer, or None for the handle.

                None is the WHOLE ANSWER to what is draggable: the
                eyebrow, the title, the two hint lines, the margins and
                the screenshot are all card background, so the painter's
                hit test — which knows only about the chips and the two
                buttons — says None for every one of them and the press
                becomes a drag. The thumbnail needs no rule of its own for
                exactly that reason: it is a picture, not a control, and
                it never entered `regions`.

                The FIELD is named here and then never seen: a real
                tk.Text sits ON TOP of the painted well, so its presses
                go to the widget and this canvas binding is not called at
                all — which is what keeps selecting a word with the mouse
                working without a line of code, and what keeps the field
                from being a handle. It is checked anyway, because relying
                on a widget's stacking order to enforce a rule and not
                saying so is how the rule gets deleted.
                """
                name = pc.hit_test(card, event.x, event.y, cache)
                return name if name and name != pc.FIELD else None

            def on_press(event) -> None:
                """A press on a control acts NOW; anything else starts a
                drag.

                Acting on the press rather than the release is
                ReviewCard's and NotifyCard's rule, and it is what makes
                "a drag that ends over a chip must not pick it" true
                without a single line about it: a drag can only have
                begun on the background, so its release lands on nothing
                that is listening. The mirror case — a press that starts
                on a chip and then wanders — has already done its work
                and simply does not drag, which is right, because a chip
                is not a handle.
                """
                name = control_at(event)
                if name == pc.SEND:
                    send()
                elif name == pc.CANCEL:
                    cancel()
                elif name and name.startswith(pc.KIND_PREFIX):
                    pick(name[len(pc.KIND_PREFIX):])
                elif name is None:
                    st["drag"] = (event.x_root - root.winfo_x(),
                                  event.y_root - root.winfo_y())
                    st["from"] = (event.x_root, event.y_root)
                    st["travel"] = 0

            def on_motion(event) -> None:
                """One handler for both <Motion> and <B1-Motion>, because
                Tk sends the second INSTEAD of the first while a button is
                down — bind only <Motion> and the card never moves."""
                if st["drag"] is not None:
                    ox, oy = st["from"]
                    st["travel"] = max(st["travel"],
                                       abs(event.x_root - ox)
                                       + abs(event.y_root - oy))
                    if st["travel"] < CLICK_PX:
                        return            # still a click until it is not
                    dx, dy = st["drag"]
                    # st, not just the window: the card GROWS from
                    # st["x"]/st["y"] as he types, so the origin he is
                    # choosing right now has to be the one growth uses. A
                    # dictation landing mid-drag repaints, and without
                    # this the card would jump back to where it was born.
                    st["x"] = event.x_root - dx
                    st["y"] = event.y_root - dy
                    root.geometry("+%d+%d" % (st["x"], st["y"]))
                    return
                over = control_at(event)
                canvas.configure(cursor="hand2" if over else "arrow")
                if over != st["hover"]:
                    st["hover"] = card["hover"] = over
                    paint()

            def on_release(_event=None) -> None:
                """Save where it was left. A press that never travelled is
                a click on the background, and this card has nothing for
                one to mean — unlike the notification card, where it is
                "take me there" — so it is deliberately nothing at all."""
                if st["drag"] is None:
                    return
                st["drag"] = None
                if st["travel"] < CLICK_PX:
                    return
                self.placed(root.winfo_x(), root.winfo_y())

            def left(_event=None) -> None:
                if st["hover"] is not None:
                    st["hover"] = card["hover"] = None
                    paint()

            def select_all(_event=None) -> str:
                """Ctrl+A selects the whole report, which a tk.Text does
                NOT do on its own: its Ctrl+A is Tk's emacs inheritance,
                beginning-of-line. The one-line Entry hid that by being
                too small for it to matter — you cleared it with
                Backspace — and a field big enough to hold a paragraph is
                a field he will want to replace in one gesture."""
                field.tag_add("sel", "1.0", "end-1c")
                field.mark_set("insert", "end-1c")
                return "break"

            def lit(on: bool):
                """The field's border is the accent when it has the caret
                and the hairline when it has not. Wired rather than
                hardcoded on, because the card stays up while he goes off
                to another window to reproduce the thing he is reporting
                (see the Escape binding below), and a field glowing as if
                it were taking keys while the keys are going somewhere
                else is the one lie on this card that would cost him a
                sentence."""
                def handler(_event=None) -> None:
                    if card["focused"] != on:
                        card["focused"] = on
                        paint()
                return handler

            canvas.bind("<ButtonPress-1>", on_press)
            canvas.bind("<B1-Motion>", on_motion)
            canvas.bind("<Motion>", on_motion)
            canvas.bind("<ButtonRelease-1>", on_release)
            canvas.bind("<Leave>", left)
            field.bind("<FocusIn>", lit(True))
            field.bind("<FocusOut>", lit(False))
            field.bind("<Control-a>", select_all)
            field.bind("<Control-A>", select_all)
            field.bind("<Return>", send)
            field.bind("<KP_Enter>", send)
            field.bind("<Shift-Return>", newline)
            field.bind("<Shift-KP_Enter>", newline)
            field.bind("<Escape>", cancel)
            # On the window as well as the field: with no frame the
            # keyboard is the only way out that is always there, and it
            # must not depend on which of the card's widgets has the
            # focus. NOT a cancel on losing the focus to another app,
            # though, and dashboard._report's `outside` says why: he may
            # well be going off to reproduce the thing he is reporting,
            # and coming back to a box he has to retype would be worse
            # than no box at all.
            root.bind("<Escape>", cancel)
            root.bind("<Return>", send)
            root.protocol("WM_DELETE_WINDOW", cancel)

            def pump() -> None:
                """Dictated text, typed in on the card's own thread — the
                recorder's thread touching this widget would take the
                interpreter down with it. It replaces the line (what was
                there is a draft) and pointedly does NOT set `closing`:
                filling is not filing. The owner reads what came back,
                fixes it if the decoder misheard, and presses Enter. The
                echo and the field's height follow from `refresh` in the
                same turn, so a spoken report is drawn exactly like a
                typed one.
                """
                try:
                    while True:
                        text = self._q.get_nowait()
                        field.delete("1.0", "end")
                        field.insert("1.0", text)
                        field.mark_set("insert", "end")
                except queue.Empty:
                    pass
                except Exception:
                    return          # card gone underneath us: nothing to do
                try:
                    refresh()
                    root.after(60, pump)
                except Exception:
                    return

            card["typed"], card["lines"] = "", pc.FIELD_LINES_MIN
            paint()
            root.deiconify()
            root.update_idletasks()
            # After the geometry and after update_idletasks: the attribute
            # goes to a real hwnd, and DwmSetWindowAttribute on an
            # unrealised window is the same silent no-op that once put the
            # status dot on a close button.
            _round_corners(root, pc.hex_of("STROKE"))
            refresh()
            if focus:
                self._take_focus(root, field)
            pump()
            _pump_until(root, closing)
        except Exception as e:
            _log.info("the problem card could not open: %r", e)
        finally:
            try:
                if root is not None:
                    _forget_window(root)
                    root.destroy()
            except Exception:
                pass
            # THE PICTURE GOES BEFORE THE FRAME DOES, and this card had to
            # learn it where the other two never did. `st` holds the
            # ImageTk.PhotoImage the canvas was showing, and every closure
            # above holds `st`; leave them alive past root.destroy() and
            # the PhotoImage is finalised later, from whichever thread the
            # collector happens to be on, calling into a Tcl interpreter
            # that is gone. That is the "Tcl_AsyncDelete: async handler
            # deleted by the wrong thread" abort — measured 2026-09-04:
            # WordPrompt's teardown has no images in it and exits clean,
            # this one aborted the process on the SECOND card it opened
            # until these two lines were here. Clearing the dict is what
            # matters; the closures then hold nothing that talks to Tcl.
            st.clear()
            cache.clear()
            paint = refresh = pump = None                 # noqa: F841
            on_press = on_motion = on_release = None      # noqa: F841
            canvas = field = root = None                  # noqa: F841
            gc.collect()
        try:
            on_done(result["text"], result["kind"])
        except Exception:
            _log.info("problem card: could not report the answer",
                      exc_info=True)



def _desktop_bounds(screen) -> tuple[int, int, int, int]:
    """The WHOLE virtual desktop as (x, y, w, h), not the primary monitor.

    ProblemCard._run works this out inline and says why at length; the
    short version is that measured on this machine the virtual desktop
    starts at x = -1920, so a card he dragged onto the left monitor has a
    genuinely negative x and clamping it to the primary would walk it
    back every single time. Falls back to the primary if the metrics are
    not there, which is the answer every card in this module has always
    given.

    Factored out here for the SECOND modal card rather than reached into
    the first: moving ProblemCard onto it is a behaviour-preserving
    change with its own tests, and this one is not the change to make it
    in.
    """
    try:
        metric = ctypes.windll.user32.GetSystemMetrics
        bounds = (metric(76), metric(77), metric(78), metric(79))
        if bounds[2] <= 0 or bounds[3] <= 0:
            raise ValueError(bounds)          # SM_*VIRTUALSCREEN
        return bounds
    except Exception:                         # noqa: BLE001
        return (0, 0, int(screen[0]), int(screen[1]))


def _open_origin(bounds, screen, saved, size, near, keep: int = 60):
    """Where a frameless modal card opens, top-left, in screen pixels.

    Three answers in priority order, and ProblemCard._run's comments are
    the long form of all three. WHERE HE PUT IT LAST WINS, clamped so a
    card saved on a monitor that is no longer plugged in does not come
    back somewhere nobody can reach it — `keep` is how much of it has to
    stay on the desktop to be grabbable. Then `near`, for a card opened
    off a widget. Then the middle of the PRIMARY screen, which is where
    he is looking.
    """
    width, height = int(size[0]), int(size[1])
    x, y, moved = int(saved[0]), int(saved[1]), bool(saved[2])
    if moved:
        bx, by, bw, bh = bounds
        return (max(bx + keep - width, min(x, bx + bw - keep)),
                max(by + keep - height, min(y, by + bh - keep)))
    if near:
        return (int(near[0]), int(near[3]) + 8)
    return ((int(screen[0]) - width) // 2,
            max(0, (int(screen[1]) - height) // 2))


class AnswerCard(ProblemCard):
    """The one question the weekly read could not answer itself.

    THE REPORT CARD IN REVERSE, and a subclass of it for exactly the
    reasons ProblemCard is a subclass of WordPrompt. Everything else in
    this module is WS_EX_NOACTIVATE or WS_EX_TRANSPARENT on purpose
    (_no_activate says why: you may well be typing when one appears), and
    a card with a text field in it has to come down the one branch of
    this tree that TAKES THE KEYBOARD. What it inherits is the four
    things that were hard — `_take_focus`'s SetForegroundWindow-then-Alt
    recipe, `open()`, `fill()`, which puts a dictated line in the field
    WITHOUT sending it — plus the report card's `x`/`y`/`placed` drag
    memory, which is the same gesture saving the same pair of numbers
    under a section of its own.

    Only `ask`, `answer` and `_run` are overridden, and all three had to
    be: inheriting `_run` would leave an AnswerCard able to open a
    REPORT card, which is a trap rather than a feature — the same
    sentence ProblemCard._run has about the plain word box.

    THE FACE IS A PICTURE. answer_card paints the whole card — the
    eyebrow, the title, the two grey lines, the Hebrew question in its
    panel, the option rows, the field's well, the bidi echo and the two
    buttons — as one Pillow image, and this window shows it, positions a
    real tk.Text over the painted well, and turns a click or a key into
    an answer. Nothing here computes a coordinate: answer_card.regions is
    read by both the painter and the hit test, which is what keeps an
    option pressed where it is drawn.

    THE OPTIONS ARE THE PRIMARY CONTROL, so the keyboard opens ON THE
    CARD and not in the field: 1..N pick a row, where N is however many
    rows the question actually carries, Enter sends, Escape leaves. The
    digits are bound to the CANVAS and deliberately not to the toplevel —
    a Text's own class binding for "3" inserts a 3 and does not stop
    there, so a digit bound on the window would type into the field AND
    pick option three every time he wrote a number. Which is also why a
    digit does nothing while he is writing: the caret is in the field, the
    field is what got the key, and a 3 in the middle of "מתחת ל-30 אחוז"
    must be a 3.

    A PICK AND A TYPED LINE ARE ONE ANSWER, and answer_card's docstring
    is where the decision is written down. What this half owes it is that
    NOTHING IS TAKEN BACK BY SOMETHING ELSE. Typing does not clear the
    pick; picking does not clear, dim, disable or empty the field; a line
    arriving through `fill()` picks nothing at all. There is no state in
    which the field is out of play, so there is nothing here that puts it
    there and nothing that has to take it back out — the whole
    dim-and-restore mechanism this card used to carry is gone, along with
    the `dress()` that repainted the widget's own ground to match it.

    THE CARET IS NOT PART OF THE ANSWER, so a pick does not move it.
    That is his flow made cheap: pick "before the backup", keep typing
    "but only if the CPU is idle" into the field the caret never left. It
    costs the digits while he is writing, which is the right trade — one
    click on the card's background hands the keyboard back to the canvas.

    UN-PICKING IS THE SAME GESTURE AGAIN — click the lit row, or press
    its digit — and the card goes back to no choice with the field
    untouched. A separate "clear" control was the alternative and it is
    one more thing on a card that already has five rows, two buttons and
    a field; the row that shows the pick is the obvious place to undo it,
    and the keys line says so out loud because an undo nobody can see is
    an undo nobody uses.

    ESCAPE IS NOT AN ANSWER. `on_done(None, "")` is what a dismissed card
    reports, and it is what `_result` is born holding, so every path out
    of here that is not a deliberate Send says the same thing: the
    question is still pending and the routine is still waiting on it. A
    card he waves away must never turn into a recorded decision.

    THE CONTRACT. The answer goes out through `on_done(choice, text)` on
    this thread, after the window is down:

    * `choice` is the index of the lit row, or None if no row is lit.
    * `text` is whatever is in the field, stripped — ALWAYS, including
      when a row is lit. A canned pick used to report `text=""` and that
      was right when the field belonged to a row; it is now a way to
      silently drop half of what he said.
    * Both together is the ordinary case, not an edge one: `(0, "אבל רק
      אחרי הגיבוי")` is a decision with a condition on it and the
      routine is built to read both.
    * `(None, "")` is Escape and Cancel, and nothing else can produce it
      — Send refuses to fire unless `answer_card.answerable` says there
      is something to send, which is the store's own rule.
    """

    def ask(self, item, on_done, *, near=None, focus: bool = True) -> bool:
        """Open the card on `item`, a questions.py item dict. One at a
        time, like every card on this branch: a second question while one
        is open is dropped, because two modals fighting for the keyboard
        is worse than a question that waits another minute.

        `focus` is the keyboard grab; a test passes False and answers
        through `answer` instead of typing, because a synthetic Enter
        aimed at a box that did not get the foreground lands in whatever
        window did.
        """
        if self._thread is not None and self._thread.is_alive():
            return False
        self._result = {"choice": None, "text": ""}
        self._closing = threading.Event()
        self._q = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, args=(item, on_done, near, focus),
            daemon=True, name="answer-card")
        self._thread.start()
        return True

    def answer(self, choice=None, text: str = "") -> None:
        """Close the card with an answer, from any thread — what Send
        does, reachable without a keyboard. No arguments is what Escape
        does, which is the default for the same reason `_result` is born
        that way: the safe answer to "did he answer?" is no.

        The base's `answer(text)` is deliberately not what this is: an
        answer here is a CHOICE AND WORDS, either or both, and a
        one-argument door could not say the pair — which is the whole
        shape of an answer on this card.
        """
        self._result["choice"] = choice
        self._result["text"] = text or ""
        self._closing.set()

    def _run(self, item, on_done=None, near=None, focus=True) -> None:
        """The card, on its own thread and its own Tk interpreter."""
        import gc
        import tkinter as tk

        import answer_card as ac
        from PIL import ImageTk

        result = self._result
        closing = self._closing
        # Declared before the try so the burial in `finally` can name them
        # whichever line failed — HintCard's `draw = pump = hide = None`,
        # for the same reason and with more to bury.
        root = field = canvas = paint = refresh = pump = None
        st: dict = {}
        cache: dict = {}
        try:
            card = ac.card_for(item)
            root = tk.Tk()
            root.withdraw()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.configure(bg=ac.hex_of("CARD"))
            # takefocus, and it is load-bearing: the digits are bound
            # here (see the class docstring), so the canvas is what has
            # to be holding the keyboard when the card opens.
            canvas = tk.Canvas(root, bg=ac.hex_of("CARD"),
                               highlightthickness=0, bd=0, takefocus=1)
            canvas.place(x=0, y=0)

            # THE CARD GROWS DOWNWARD AND DOES NOT WANDER — the report
            # card's rule, and its comments are the long form. Centred
            # ONCE for the height it opens at, grown down from that top,
            # and moved only if growing down would take the buttons off
            # the bottom of the screen.
            screen = (root.winfo_screenwidth(), root.winfo_screenheight())
            bounds = _desktop_bounds(screen)
            _w0, h0 = ac.measure(card, cache)
            at_x, at_y = _open_origin(bounds, screen,
                                      (self.x, self.y, self.moved()),
                                      (ac.CARD_W, h0), near)

            # The same widget the report card's field is, with the same
            # metrics read out of the same module: no border and no
            # highlight (the well around it is painted, and a Tk border
            # inside a painted one is two edges of different curvature),
            # wrapping, and spacing3 set so the widget's own line height
            # agrees to the pixel with the painter's FIELD_LINE_H — which
            # it must, since the painter draws the well from a line count
            # this widget reports.
            field = tk.Text(root, bg=ac.hex_of("EDGE"), fg=ac.hex_of("FG"),
                            insertbackground=ac.hex_of("ACCENT"),
                            selectbackground=ac.hex_of("ACCENT_SOFT"),
                            selectforeground=ac.hex_of("FG"),
                            bd=0, highlightthickness=0, relief="flat",
                            wrap="word", undo=True, font=ac.FIELD_FONT,
                            spacing3=max(0, ac.FIELD_LINE_H
                                         - ac.FIELD_FONT_LINE),
                            insertwidth=2, padx=0, pady=0)
            field.tag_configure("rtl", justify="right")

            st.update({"typed": None, "lines": 0, "hover": None,
                       "photo": None, "size": (0, 0),
                       "x": at_x, "y": at_y,
                       "drag": None, "from": None, "travel": 0})

            def wrapped() -> int:
                """How many lines the widget is actually showing.

                Asked of the widget rather than guessed from the string
                length: it is the widget that wrapped it, and the well is
                drawn to this number. `count` returns a one-tuple in some
                Tk builds and a bare int in others, so both are
                unwrapped; answer_card.field_lines is the estimate for a
                build that has neither, and for the headless render where
                there is no widget at all.
                """
                try:
                    got = field.count("1.0", "end", "displaylines")
                except Exception:                     # noqa: BLE001
                    return ac.field_lines(st["typed"] or "")
                if isinstance(got, (tuple, list)):
                    got = got[0] if got else 1
                return max(1, int(got or 1))

            def place_field(box) -> None:
                field.place(x=ac.PAD + box[0] + ac.FIELD_PAD_X,
                            y=ac.PAD + box[1] + ac.FIELD_PAD_Y,
                            width=ac.INNER - 2 * ac.FIELD_PAD_X,
                            height=box[3] - box[1] - 2 * ac.FIELD_PAD_Y)

            def paint() -> None:
                img = ac.compose(card, cache)
                photo = ImageTk.PhotoImage(img, master=root)
                canvas.delete("all")
                canvas.configure(width=img.width, height=img.height)
                canvas.create_image(0, 0, anchor="nw", image=photo)
                st["photo"] = photo          # Tk keeps no reference
                if st["size"] != (img.width, img.height):
                    st["size"] = (img.width, img.height)
                    # Growing DOWN must not put the buttons under the
                    # bottom edge of the desktop he is on. Against
                    # `bounds` because the card may well be on the second
                    # monitor.
                    floor = bounds[1] + bounds[3] - 8
                    if st["y"] + img.height > floor:
                        st["y"] = max(bounds[1], floor - img.height)
                    root.geometry("%dx%d+%d+%d" % (img.width, img.height,
                                                   st["x"], st["y"]))
                place_field(ac.layout(card, cache)["field"])

            # THERE IS NO `dress()` ANY MORE, and its absence is the
            # change. It re-coloured this widget on every pick — flat
            # ground, faint ink, and a caret painted the colour of the
            # thing behind it so that a still-clickable field could look
            # like it had no caret — because the field belonged to the
            # last option and stopped being the answer when another row
            # was picked. The field belongs to nobody now, so its colours
            # are set once in the constructor above and never touched:
            # EDGE ground, FG ink, an ACCENT caret. One face, always, is
            # what "always live" means at the widget level, and a
            # function that could repaint it is a function that could
            # take it away again.

            def refresh() -> None:
                """Repaint if anything the picture shows has changed.

                Driven from the pump below rather than from a key
                binding, and that is the point: the line does not always
                arrive from the keyboard. THE CARD CAN BE DICTATED INTO —
                `fill` puts a transcript in the field with no <KeyRelease>
                behind it at all — and it can be pasted into and undone.
                Reading the widget on a timer catches every one of them,
                which is the only way the echo underneath can be trusted
                to be showing what is really in the field.
                """
                typed = field.get("1.0", "end-1c")
                if len(typed) > _TEXT_MAX:
                    # Cut here, where he can see it stop, rather than
                    # silently on the way to disk.
                    field.delete("1.0+%dc" % _TEXT_MAX, "end")
                    typed = field.get("1.0", "end-1c")
                field.tag_add("rtl", "1.0", "end")
                lines = min(ac.FIELD_LINES_MAX,
                            max(ac.FIELD_LINES_MIN, wrapped()))
                # TYPING TAKES NOTHING BACK. This is where the old card
                # dragged the pick onto its open row the moment a word
                # appeared, because words meant "none of your rows". A
                # word now means a word: the lit row stays lit, and Send
                # goes out with the pair. What still happens here is the
                # only thing that has to — `card["typed"]` is what
                # `answer_card.answerable` reads, so the button arms on
                # the first character and disarms on the last backspace
                # with no extra wiring at all.
                if (typed, lines) == (st["typed"], st["lines"]):
                    return
                st["typed"], st["lines"] = typed, lines
                card["typed"], card["lines"] = typed, lines
                paint()

            def pick(index: int) -> None:
                """Light row `index`, or put it out if it is already lit.

                THE SAME GESTURE UN-PICKS, which is the whole undo on
                this card: a click on the lit row, or its digit again,
                and the choice goes back to None. Nothing else changes —
                the field keeps its words, the caret keeps its place.

                THE CARET IS NOT MOVED, in either direction. The old
                version dragged it into the field for the open row and
                back out to the canvas for the others, because the field
                was a row's body and the focus was how the card said
                which. Now a pick is a pick: he can be halfway through a
                sentence when he presses a row, and pulling the caret out
                from under him would cost him the rest of it.
                """
                options = card.get("options") or ()
                if not 0 <= index < len(options):
                    return
                card["choice"] = None if card["choice"] == index else index
                paint()

            def digit(index: int):
                def handler(_event=None) -> str:
                    pick(index)
                    return "break"
                return handler

            def send(_event=None) -> str:
                """Send, but only if there is an answer to send.

                The store refuses one that is neither a valid choice nor
                non-empty text, so an unarmed Send here would close the
                card and report a decision nothing would accept. It
                stays up instead, with the button visibly not ready —
                answer_card.answerable is the same test the painter uses,
                so the button and the key cannot disagree.

                BOTH VALUES, ALWAYS. Whatever is in the field goes out
                with whatever row is lit, and the field is read
                unconditionally — no `if` in front of it. The old line
                sent `text=""` whenever a canned row was picked, which
                was the dimmed field's promise being kept and is now the
                one bug that would lose him a whole sentence without a
                trace: he picks "before the backup", writes "actually
                after it", presses Send, and the second half never
                existed.
                """
                if not ac.answerable(card):
                    return "break"
                result["choice"] = card["choice"]
                result["text"] = field.get("1.0", "end-1c").strip()
                closing.set()
                return "break"

            def cancel(_event=None) -> str:
                """Escape and Cancel: the question stays pending.

                Explicitly written back rather than left to whatever
                `_result` happens to hold, because this is the one thing
                on the card that must not be able to go wrong — a card he
                dismissed becoming a recorded answer would put a decision
                in the store he never made.
                """
                result["choice"], result["text"] = None, ""
                closing.set()
                return "break"

            def newline(_event=None) -> str:
                """Shift+Enter is the new line, Enter is Send. Bound
                explicitly rather than left to Tk's class binding,
                because the <Return> binding fires for a shifted Return
                too unless something more specific claims it.

                AND THIS CARD DOES NOT SAY SO ON ITS FACE, unlike the
                report card, which spends a clause of its keys line on
                it. Measured 2026-09-05 through the same renderer at
                KEYS_PT: this line already carries the digits clause, and
                adding "Shift+Enter for a new line" to it takes the block
                from 10 px to 23 — it WRAPS, at two options and at five.
                A two-line keys paragraph on a card that is already the
                tallest thing in this module is a worse trade than an
                undocumented shortcut, on a field that is usually one
                clause. answer_card.keys_of builds the line and is where
                that call belongs if it is ever revisited.
                """
                field.insert("insert", "\n")
                return "break"

            def select_all(_event=None) -> str:
                """Ctrl+A selects the whole answer, which a tk.Text does
                NOT do on its own: its Ctrl+A is Tk's emacs inheritance,
                beginning-of-line."""
                field.tag_add("sel", "1.0", "end-1c")
                field.mark_set("insert", "end-1c")
                return "break"

            def entered(_event=None) -> None:
                """The caret arrived: the field's border lights up and
                that is ALL it does.

                It used to take the open option as well — clicking into
                the field was one of the three ways of saying "none of
                your rows" — and that is exactly the coupling the owner
                threw out. Putting the caret somewhere is not answering a
                question, and a click into the field that silently
                unpicked the row he had already chosen would be the
                dim-and-take-back mechanism coming back in through the
                focus handler.
                """
                if not card["focused"]:
                    card["focused"] = True
                    paint()

            def departed(_event=None) -> None:
                """The border falls back to the hairline when the keys go
                elsewhere. Wired rather than hardcoded on, because the
                card stays up while he goes off to another window to look
                something up (see the Escape binding below), and a field
                glowing as if it were taking keys while the keys are
                going somewhere else is the one lie here that would cost
                him a sentence."""
                if card["focused"]:
                    card["focused"] = False
                    paint()

            # A release that travelled less than this is a click, not a
            # drag. NotifyCard's own number and the report card's, because
            # it is the same judgement about the same gesture.
            CLICK_PX = 4

            def control_at(event):
                """The control under the pointer, or None for the handle.

                None is the WHOLE ANSWER to what is draggable: the
                eyebrow, the title, the two grey lines, the question
                panel and the margins are all card background, so the
                painter's hit test — which knows only about the rows, the
                field and the two buttons — says None for every one of
                them and the press becomes a drag. THE QUESTION PANEL
                needs no rule of its own for exactly that reason: it is
                400 characters of text to read, not a control, and it
                never entered `regions`.

                The FIELD is named here and then never seen: a real
                tk.Text sits ON TOP of the painted well, so its presses
                go to the widget and this canvas binding is not called at
                all — which is what keeps selecting a word with the mouse
                working without a line of code. It is checked anyway,
                because relying on a widget's stacking order to enforce a
                rule and not saying so is how the rule gets deleted.
                """
                name = ac.hit_test(card, event.x, event.y, cache)
                return name if name and name != ac.FIELD else None

            def on_press(event) -> None:
                """A press on a control acts NOW; anything else starts a
                drag.

                The report card's rule and its reason: acting on the
                press is what makes "a drag that ends over an option must
                not pick it" true without a line about it — a drag can
                only have begun on the background, so its release lands
                on nothing that is listening.
                """
                name = control_at(event)
                index = ac.option_at(name)
                if name == ac.SEND:
                    send()
                elif name == ac.CANCEL:
                    cancel()
                elif index is not None:
                    pick(index)
                elif name is None:
                    # The keyboard comes back to the card, so the digits
                    # work again after a trip through the field.
                    canvas.focus_set()
                    st["drag"] = (event.x_root - root.winfo_x(),
                                  event.y_root - root.winfo_y())
                    st["from"] = (event.x_root, event.y_root)
                    st["travel"] = 0

            def on_motion(event) -> None:
                """One handler for both <Motion> and <B1-Motion>, because
                Tk sends the second INSTEAD of the first while a button is
                down — bind only <Motion> and the card never moves."""
                if st["drag"] is not None:
                    ox, oy = st["from"]
                    st["travel"] = max(st["travel"],
                                       abs(event.x_root - ox)
                                       + abs(event.y_root - oy))
                    if st["travel"] < CLICK_PX:
                        return            # still a click until it is not
                    dx, dy = st["drag"]
                    # st, not just the window: the card GROWS from
                    # st["x"]/st["y"] as the field fills, so the origin he
                    # is choosing right now has to be the one growth uses.
                    st["x"] = event.x_root - dx
                    st["y"] = event.y_root - dy
                    root.geometry("+%d+%d" % (st["x"], st["y"]))
                    return
                over = control_at(event)
                canvas.configure(cursor="hand2" if over else "arrow")
                if over != st["hover"]:
                    st["hover"] = card["hover"] = over
                    paint()

            def on_release(_event=None) -> None:
                """Save where it was left. A press that never travelled is
                a click on the background, and this card has nothing for
                one to mean."""
                if st["drag"] is None:
                    return
                st["drag"] = None
                if st["travel"] < CLICK_PX:
                    return
                self.placed(root.winfo_x(), root.winfo_y())

            def left(_event=None) -> None:
                if st["hover"] is not None:
                    st["hover"] = card["hover"] = None
                    paint()

            canvas.bind("<ButtonPress-1>", on_press)
            canvas.bind("<B1-Motion>", on_motion)
            canvas.bind("<Motion>", on_motion)
            canvas.bind("<ButtonRelease-1>", on_release)
            canvas.bind("<Leave>", left)
            # THE DIGITS GO ON THE CANVAS AND NOWHERE ELSE — the class
            # docstring says why. Only as many as there are rows, so a
            # key the card does not name never quietly does something:
            # two options bind 1 and 2, five bind 1 to 5, and
            # answer_card.keys_of prints the same range on the card off
            # the same count.
            for spot in range(len(card.get("options") or ())):
                canvas.bind("<Key-%d>" % (spot + 1), digit(spot))
                canvas.bind("<KP_%d>" % (spot + 1), digit(spot))
            canvas.bind("<Return>", send)
            canvas.bind("<KP_Enter>", send)
            field.bind("<FocusIn>", entered)
            field.bind("<FocusOut>", departed)
            field.bind("<Control-a>", select_all)
            field.bind("<Control-A>", select_all)
            field.bind("<Return>", send)
            field.bind("<KP_Enter>", send)
            field.bind("<Shift-Return>", newline)
            field.bind("<Shift-KP_Enter>", newline)
            field.bind("<Escape>", cancel)
            # On the window as well, for both keys: with no frame the
            # keyboard is the only way out that is always there, and it
            # must not depend on which of the card's widgets has the
            # focus. NOT a cancel on losing the focus to another app,
            # though — he may well be going off to check the thing the
            # question is about, and coming back to a card that closed
            # itself would mean answering it from memory next week.
            root.bind("<Escape>", cancel)
            root.bind("<Return>", send)
            root.protocol("WM_DELETE_WINDOW", cancel)

            def pump() -> None:
                """Dictated text, typed in on the card's own thread — the
                recorder's thread touching this widget would take the
                interpreter down with it. It replaces the line (what was
                there is a draft) and pointedly does NOT set `closing`:
                filling is not filing. `refresh` picks the echo and the
                field's height up behind it in the same turn, so a spoken
                answer is drawn exactly like a typed one.

                AND IT DOES NOT TOUCH THE CHOICE. A dictated line used
                to drag the pick onto the open row; a row he picked
                before he started talking now survives the transcript
                landing, which is the same rule typing follows and the
                only one that lets him say the condition out loud.
                """
                try:
                    while True:
                        text = self._q.get_nowait()
                        field.delete("1.0", "end")
                        field.insert("1.0", text)
                        field.mark_set("insert", "end")
                except queue.Empty:
                    pass
                except Exception:
                    return          # card gone underneath us: nothing to do
                try:
                    refresh()
                    root.after(60, pump)
                except Exception:
                    return

            card["typed"], card["lines"] = "", ac.FIELD_LINES_MIN
            paint()
            root.deiconify()
            root.update_idletasks()
            # After the geometry and after update_idletasks: the attribute
            # goes to a real hwnd, and DwmSetWindowAttribute on an
            # unrealised window is a silent no-op.
            _round_corners(root, ac.hex_of("STROKE"))
            refresh()
            if focus:
                # The CANVAS, not the field: the options are the primary
                # control and the digits are bound here.
                self._take_focus(root, canvas)
            pump()
            _pump_until(root, closing)
        except Exception as e:
            _log.info("the answer card could not open: %r", e)
        finally:
            try:
                if root is not None:
                    _forget_window(root)
                    root.destroy()
            except Exception:
                pass
            # THE PICTURE GOES BEFORE THE FRAME DOES. `st` holds the
            # ImageTk.PhotoImage the canvas was showing and every closure
            # above holds `st`; leave them alive past root.destroy() and
            # the PhotoImage is finalised later, from whichever thread the
            # collector happens to be on, calling into a Tcl interpreter
            # that is gone. That is the "Tcl_AsyncDelete: async handler
            # deleted by the wrong thread" abort the report card was
            # measured aborting on — its SECOND card, not its first —
            # until these lines were here. Clearing the dict is what
            # matters; the closures then hold nothing that talks to Tcl.
            st.clear()
            cache.clear()
            paint = refresh = pump = None                 # noqa: F841
            pick = digit = send = cancel = None           # noqa: F841
            entered = departed = None                     # noqa: F841
            on_press = on_motion = on_release = None      # noqa: F841
            canvas = field = root = None                  # noqa: F841
            gc.collect()
        if on_done is None:
            return
        try:
            on_done(result["choice"], result["text"])
        except Exception:
            _log.info("answer card: could not report the answer",
                      exc_info=True)


_REVIEW_BUTTONS = ("accept", "reject", "later")


class ReviewCard(HintCard):
    """The card that shows one proposal from the second reading
    (review.py) and takes the answer.

    The hint card's contract, inherited — its own thread, callers only
    ever enqueue, a Glass on the skin path and its own Tk interpreter on
    the fallback path — plus three things a card that asks a question
    needs and a card that only informs does not:

    - IT TAKES CLICKS, on three buttons and nowhere else; the rest of the
      face is the handle you drag it by. Placed mid-height on the right
      edge by default, well away from any window's close button, which
      is what lets it be solid where the hint card had to be click-
      through.
    - IT TAKES KEYS, but only while the mouse is over it. The hook offers
      every key-down to `on_key`; the three keys answer the card when the
      pointer is on it and are ordinary letters everywhere else — a card
      that ate a letter being typed into the chat beneath it would be
      worse than no card.
    - IT KEEPS TIME. The presenter runs the clock and calls `timed_out`;
      the answer to a clock running out is "nothing", and the proposal
      stays in the dashboard. `pressed("later")` is the same nothing, one
      click sooner.

    Verdicts go out through `on_verdict(id, verdict)` on whichever thread
    pressed the button — the painter's or the hook's — so that callback
    must only enqueue (main.py hands it to the review engine).
    """

    CORNERS = ("right", "left", "top-right", "top-left",
               "bottom-right", "bottom-left")

    def __init__(self, corner: str = "right", margin: int = 14,
                 x: int = HINT_UNSET, y: int = HINT_UNSET, scale: float = 1.0,
                 on_change=None, on_verdict=None, seconds: float = 20.0,
                 keys: dict | None = None, on_edit=None) -> None:
        super().__init__(after_ms=0, corner=corner, margin=margin, x=x, y=y,
                         scale=scale, on_change=on_change)
        self._on_verdict = on_verdict
        # The pencil: on_edit(id, row, rect) — the owner wants to type the
        # word himself. The card is down by the time it is called.
        self._on_edit = on_edit
        self.seconds = float(seconds)
        self._keys = {"accept": "v", "reject": "x", "later": "l",
                      "edit": "e"}
        if keys:
            self._keys.update({k: str(v).strip().lower()
                               for k, v in keys.items() if v})
        self._vks: dict | None = None
        self.rect = None          # screen rect of the visible card, or None
        self._current = None      # the suggestion id on screen
        self._state_lock = threading.Lock()

    def start(self) -> None:
        if not self._enabled:
            return
        try:
            import tkinter  # noqa: F401
        except Exception:
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="review-card")
        self._thread.start()
        self._alive.wait(timeout=3)

    # -- caller's threads --

    def key_labels(self) -> tuple:
        return tuple(self._keys[n].upper()
                     for n in _REVIEW_BUTTONS + ("edit",))

    def show(self, suggestion: dict) -> None:
        """Put a proposal up. Only enqueues, so safe from the engine
        thread. A new proposal replaces the one on screen — that one is
        still in the dashboard, undecided."""
        if self._thread is None or not self._enabled:
            return
        import review_card as rc
        card = rc.card_for(suggestion, seconds=self.seconds,
                           keys=self.key_labels())
        with self._state_lock:
            self._current = card["id"]
        self._q.put(card)

    def hide(self) -> None:
        with self._state_lock:
            self._current = None
        if self._thread is not None:
            self._q.put(None)

    def visible(self) -> bool:
        return self._current is not None

    def current(self):
        return self._current

    def hovering(self) -> bool:
        """Is the pointer on the card right now? Asked by the hook for a
        key and by the painter for the clock. Cheap: a rect and a point,
        no window handle."""
        rect = self.rect
        if rect is None or not self.visible():
            return False
        try:
            pt = ctypes.wintypes.POINT()
            ctypes.WinDLL("user32").GetCursorPos(ctypes.byref(pt))
        except Exception:
            return False
        return rect[0] <= pt.x <= rect[2] and rect[1] <= pt.y <= rect[3]

    def _vk_map(self) -> dict:
        if self._vks is None:
            vks: dict = {}
            try:
                from hotkey import vk_for
                for name in _REVIEW_BUTTONS + ("edit",):
                    try:
                        vks[int(vk_for(self._keys[name]))] = name
                    except Exception:
                        _log.info("review card: no key named %r for %s",
                                  self._keys[name], name)
            except Exception:
                pass
            self._vks = vks
        return self._vks

    def on_key(self, vk: int) -> bool:
        """A key-down from the hook. True swallows it — only for one of
        the three keys, only with a card up, only with the pointer on it."""
        if not self.visible() or not self.hovering():
            return False
        name = self._vk_map().get(int(vk))
        if name is None:
            return False
        self.pressed(name)
        return True

    def pressed(self, name: str) -> None:
        """A button, by click or key. Takes the card down and reports.
        "edit", or "edit<row>", is the pencil: the owner types the word
        himself, and that goes out through on_edit instead of a verdict."""
        pencil = name.startswith("edit")
        if not (pencil or name in _REVIEW_BUTTONS):
            return
        with self._state_lock:
            sid, self._current = self._current, None
        rect = self.rect
        if self._thread is not None:
            self._q.put(None)
        if sid is None:
            return
        if pencil:
            if self._on_edit is None:
                return
            try:
                row = int(name[4:] or 0)
            except ValueError:
                row = 0
            try:
                self._on_edit(sid, row, rect)
            except Exception:
                _log.info("review card: could not open the pencil",
                          exc_info=True)
            return
        if name == "later" or self._on_verdict is None:
            return
        try:
            self._on_verdict(sid, "accepted" if name == "accept"
                             else "rejected")
        except Exception:
            _log.info("review card: could not report a verdict",
                      exc_info=True)

    def timed_out(self) -> None:
        """The clock ran out: no verdict. The painter takes it down."""
        with self._state_lock:
            self._current = None

    # -- placement --

    def origin(self, width: int, height: int, screen: tuple,
               inset: int = 0, bounds=None) -> tuple:
        """Mid-height on the right (or left) edge by default; the four
        corners and a saved position exactly as the hint card does them."""
        if self.moved() or self._corner not in ("right", "left"):
            return super().origin(width, height, screen, inset, bounds)
        sw, sh = screen
        m = self._margin
        x = (m - inset) if self._corner == "left" \
            else (sw - m - width + inset)
        y = (sh - height) // 2
        return int(x), int(y)

    # -- overlay thread --

    def _run(self) -> None:
        try:
            if skin is not None and skin.review_run(self):   # --- SKIN
                return
            self._build_and_loop()
        except Exception as e:
            _log.info("review card unavailable: %r", e)
        finally:
            self._alive.set()

    def _build_and_loop(self) -> None:
        """The fallback: the same card on a flat face, in Tk.

        review_card.flat paints the whole thing as one image; this window
        only shows it, moves it, and turns a click or a key into
        `pressed`. Same teardown as the hint card's: destroyed on the
        thread that built it, then collected there.
        """
        import tkinter as tk
        import review_card as rc
        from PIL import ImageTk

        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=CARD_BG)
        canvas = tk.Canvas(root, bg=CARD_BG, highlightthickness=0, bd=0)
        canvas.pack()
        self._alive.set()

        st = {"card": None, "up": False, "deadline": None, "hover": None,
              "drag": None, "photo": None, "last": 0.0,
              "tick": time.monotonic(), "hushed": False}
        cache: dict = {}

        def progress() -> float:
            deadline, card = st["deadline"], st["card"]
            if deadline is None or card is None:
                return 1.0
            seconds = float(card.get("seconds") or 0)
            if seconds <= 0:
                return 1.0
            return max(0.0, (deadline - time.monotonic()) / seconds)

        def hide() -> None:
            st["card"], st["deadline"], st["hover"] = None, None, None
            self.rect = None
            cache.clear()
            if st["up"]:
                root.withdraw()
                st["up"] = False

        def paint() -> None:
            if st["card"] is None:
                return
            img = rc.flat(st["card"], self.scale, progress(), st["hover"],
                          cache)
            photo = ImageTk.PhotoImage(img, master=root)
            canvas.delete("all")
            canvas.configure(width=img.width, height=img.height)
            canvas.create_image(0, 0, anchor="nw", image=photo)
            st["photo"] = photo               # Tk keeps no reference
            st["last"] = time.monotonic()

        def put_up(card: dict) -> None:
            st["card"], st["hover"] = card, None
            cache.clear()
            seconds = float(card.get("seconds") or 0)
            st["deadline"] = ((time.monotonic() + seconds)
                              if seconds > 0 else None)
            if st["hushed"]:
                # A reading landed while a selection is on screen. Hold
                # it: the proposal is not lost and its clock is waiting,
                # but a topmost window mapped now would cover the
                # selector and eat the drag. The card below has the long
                # version of this argument.
                return
            map_card()

        def map_card() -> None:
            """Draw the held proposal and bring the window up."""
            card = st["card"]
            if card is None:
                return
            w, h = rc.measure(card, self.scale)
            x, y = self.origin(w, h, (root.winfo_screenwidth(),
                                      root.winfo_screenheight()))
            paint()
            root.geometry(f"{w}x{h}+{x}+{y}")
            self.rect = (x, y, x + w, y + h)
            root.deiconify()
            root.update_idletasks()
            if not st["up"]:
                _no_activate(root)
                # No `_hide_from_capture(root)` any more — removed
                # 2026-09-04. A proposal the owner is being asked to
                # judge is exactly the kind of thing he wants to be able
                # to photograph and show somebody; the flag made that
                # impossible. Ordering in capture._shot_flow, not flags.
            st["up"] = True

        def set_hushed(on: bool) -> None:
            """Obey `self._hushed`, on this card's own thread. The caller
            only set an Event; every Tk call is here."""
            if on == st["hushed"]:
                return
            st["hushed"] = on
            if on:
                if st["up"]:
                    root.withdraw()
                    st["up"] = False
                self.rect = None
            else:
                map_card()

        def hit(event):
            if st["card"] is None:
                return None, None
            return rc.hit_test(st["card"], self.scale,
                               event.x + rc.SHADOW, event.y + rc.SHADOW)

        def on_press(event) -> None:
            code, what = hit(event)
            if code == rc.HTCLIENT and what:
                self.pressed(what)
            elif code == rc.HTCAPTION:
                st["drag"] = (event.x_root - root.winfo_x(),
                              event.y_root - root.winfo_y())

        def on_motion(event) -> None:
            if st["drag"] is not None:
                dx, dy = st["drag"]
                root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")
                return
            code, what = hit(event)
            want = what if code == rc.HTCLIENT else None
            if want != st["hover"]:
                st["hover"] = want
                paint()

        def on_leave(_event) -> None:
            if st["hover"] is not None:
                st["hover"] = None
                paint()

        def on_release(_event) -> None:
            if st["drag"] is None:
                return
            st["drag"] = None
            x, y = root.winfo_x(), root.winfo_y()
            if st["card"] is not None:
                w, h = rc.measure(st["card"], self.scale)
                self.rect = (x, y, x + w, y + h)
            self.placed(x, y)

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_motion)
        canvas.bind("<Motion>", on_motion)
        canvas.bind("<Leave>", on_leave)
        canvas.bind("<ButtonRelease-1>", on_release)

        def pump() -> None:
            try:
                while True:
                    item = self._q.get_nowait()
                    if item is _DONE:
                        self._closing.set()
                        return
                    if item is None:
                        hide()
                    else:
                        put_up(item)
            except queue.Empty:
                pass
            # Read once a tick, AFTER the queue, so a card that arrived in
            # this same frame is already in `st` and gets held rather than
            # mapped. Thirty milliseconds is well inside the time the
            # desktop freeze takes, so the window is off the live screen
            # before the selector maps over it.
            set_hushed(self._hushed.is_set())
            now = time.monotonic()
            dt, st["tick"] = now - st["tick"], now
            if st["card"] is not None:
                if st["deadline"] is not None and (self.hovering()
                                                   or st["hushed"]):
                    # Reading it, or hushed for somebody's selection —
                    # either way the clock waits. Seconds spent while the
                    # card is off the screen are not seconds the owner
                    # had it, which is the promise capture.ShotCards
                    # already makes for the screenshot deck.
                    st["deadline"] += dt
                if st["up"]:
                    if (st["deadline"] is not None
                            and st["deadline"] - now <= 0):
                        self.timed_out()
                        hide()
                        root.after(30, pump)
                        return
                    if now - st["last"] >= 0.1:
                        paint()
            root.after(30, pump)

        pump()
        try:
            _pump_until(root, self._closing)
        finally:
            import gc                       # see Splash: same Tcl teardown
            try:
                _forget_window(root)
                root.destroy()
            except Exception:
                pass
            st.clear()
            cache.clear()
            paint = pump = hide = put_up = None          # noqa: F841
            canvas = root = None                          # noqa: F841
            gc.collect()


class NotifyCard(HintCard):
    """The card that says something ARRIVED: Claude finished, Claude is
    waiting, a program on this machine has news (notify.py).

    The hint card's contract, inherited — its own thread, callers only
    ever enqueue, `skin.notify_run` first and its own Tk interpreter on
    the fallback path — with the review card's manners for a card that
    sits mid-height on the right edge and takes the mouse:

    - IT IS A COLUMN, NOT A CARD (2026-09-04). `show()` takes the whole
      unread list, newest first, and the window holds all of them at
      once — "so each notice card will stack on top of each others and
      the first one will be at the upper side and the oldest one will be
      on the down side". ONE window, not N: one thread, one hit test, one
      placement, gaps that cannot drift. Each card in it still has its own
      × and its own click target (notify_card.stack_hit_test answers with
      an index), so a press names one specific notification.
    - IT GROWS UPWARD. The window's BOTTOM edge is the anchor, so a long
      message pushes the top of the column up instead of running off the
      bottom of the screen, and the corner the owner lined it up against
      stays where it is. See `origin`.
    - IT TAKES CLICKS, and a click has TWO meanings (2026-09-04). On the
      × it dismisses, as it always did. Anywhere else on the card it
      OPENS: `on_open` raises the window the notification came from and
      dismisses in the same breath — the owner clicking the card that
      says Claude has finished wants Claude, not an acknowledgement. The
      same press held and moved is neither; it is the drag that puts the
      card where he wants it (saved through `on_change`, like the hint
      card's). Both callbacks take the pressed card's id, or None for
      "all" (Esc, the dismiss key) — see `pressed`.
    - IT TAKES ESC, but only while the mouse is over it. The hook offers
      every key-down to `on_key`; Esc over the card dismisses it — a
      plain dismissal, never an open, because a key pressed over a card
      is not a request to go anywhere — and is an ordinary Esc
      everywhere else.
    - IT NO LONGER KEEPS TIME, by default. `seconds` is 0 now — "the card
      will not disappear" — so there is no clock bar and nothing takes
      itself down; it waits to be dismissed. The clock is not gone, it is
      unset: a non-zero `[notify] card_seconds` still runs one, it still
      waits while the pointer is on the card, and running out is still NOT
      a dismissal (`timed_out` leaves the item unread and the engine's
      reminders bring it back). Only a click, Esc over it or the dismiss
      key mark things seen — that is `on_dismiss`, fired on whichever
      thread pressed, so the callback must only hand the work to another
      thread.
    - IT IS A NOTIFICATION, not a window the owner asked for, so it
      gives the keyboard back the instant Tk takes it (`_foreground` /
      `_give_focus_back`).
    - IT CAN BE PHOTOGRAPHED, and that is a promise, not an oversight.
      This docstring used to end the line above with "and it stays out of
      every screenshot"; it did that with WDA_EXCLUDEFROMCAPTURE, and
      that flag is absolute — it hid the card from the owner's own
      screenshots too, so the card telling him Claude had finished was
      the one thing he could not send anybody. Both paths dropped the
      flag on 2026-09-04 (here and in skin\\notify.py). What keeps the
      card from eating a selection drag is ORDER, not invisibility:
      capture.Controller._shot_flow freezes the desktop and hushes the
      cards one line later, so the card is in the frozen picture and off
      the live screen before the selector maps.

    NEVER `dismissed()`: that is the hint card's "don't show this again"
    and writes `enabled = false` into config.toml. Dismissing a
    notification means "seen", not "never again".
    """

    CORNERS = ("right", "left", "top-right", "top-left",
               "bottom-right", "bottom-left")

    def __init__(self, corner: str = "right", margin: int = 14,
                 x: int = HINT_UNSET, y: int = HINT_UNSET, scale: float = 1.0,
                 on_change=None, on_dismiss=None, on_open=None,
                 seconds: float = 0.0, anchor: str = "bottom") -> None:
        super().__init__(after_ms=0, corner=corner, margin=margin, x=x, y=y,
                         scale=scale, on_change=on_change)
        self._on_dismiss = on_dismiss
        self._on_open = on_open
        # ZERO BY DEFAULT SINCE 2026-09-04: "I want you to remove the time
        # of each card, the card will not disappear". Nothing here was
        # deleted for it — a non-zero `seconds` still runs a clock, still
        # pauses under the pointer and still ends in timed_out(), because
        # config.toml can still ask for one — but a fresh card gets none.
        self.seconds = float(seconds)
        self._anchor = "top" if str(anchor) == "top" else "bottom"
        self.rect = None          # screen rect of the visible column, or None
        self._current = None      # the NEWEST item id on screen
        self._cards: list = []    # the column as drawn, newest first
        self._state_lock = threading.Lock()

    def start(self) -> None:
        if not self._enabled:
            return
        try:
            import tkinter  # noqa: F401
        except Exception:
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="notify-card")
        self._thread.start()
        self._alive.wait(timeout=3)

    # -- caller's threads --

    def show(self, items) -> None:
        """Put the whole unread COLUMN up, newest first.

        Only enqueues, so it is safe from the HTTP thread the engine
        receives on. `items` is a list of item dicts (notify.Engine.live())
        — newest at index 0, which is the top of the column. A bare dict is
        wrapped, because that is what one notification looked like before
        2026-09-04 and every caller that only ever has one should keep
        reading like it; None or an empty list takes the column down.

        What is waiting rides in each `item["unread"]` and the sender's
        name in `item["label"]` (notify.Engine fills both), so this module
        never imports notify.py. `item["more"]` is the engine's count of
        what would not fit, and it belongs on the last item.
        """
        if self._thread is None or not self._enabled:
            return
        if items is None:
            self.hide()
            return
        if isinstance(items, dict):
            items = [items]
        import notify_card as nc
        cards = []
        for item in items:
            try:
                unread = int(item.get("unread", 1) or 1)
            except (TypeError, ValueError):
                unread = 1
            cards.append(nc.card_for(item, seconds=self.seconds,
                                     unread=unread, scale=self.scale))
        if not cards:
            self.hide()
            return
        with self._state_lock:
            # The NEWEST id: `current()` is what the dashboard and the
            # dismiss key mean by "the one on screen", and the newest is
            # the one at the top of the pile.
            self._current = cards[0]["id"]
            self._cards = cards
        self._q.put(cards)

    def hide(self) -> None:
        with self._state_lock:
            self._current = None
            self._cards = []
        if self._thread is not None:
            self._q.put(None)

    def visible(self) -> bool:
        return self._current is not None

    def current(self):
        return self._current

    def hovering(self) -> bool:
        """Is the pointer on the card right now? Asked by the hook for a
        key and by the painter for the clock. Cheap: a rect and a point,
        no window handle."""
        rect = self.rect
        if rect is None or not self.visible():
            return False
        try:
            pt = ctypes.wintypes.POINT()
            ctypes.WinDLL("user32").GetCursorPos(ctypes.byref(pt))
        except Exception:
            return False
        return rect[0] <= pt.x <= rect[2] and rect[1] <= pt.y <= rect[3]

    def on_key(self, vk: int) -> bool:
        """A key-down from the hook. True swallows it — only Esc, only
        with a card up, only with the pointer on it."""
        if int(vk) != 0x1B or not self.visible() or not self.hovering():
            return False
        self.pressed("dismiss")
        return True

    def pressed(self, name: str, item_id=None) -> None:
        """The card's two answers, by click or key: take the column down
        and say which card it was, once.

        `"dismiss"` is the × and Esc — seen, stay here. `"open"` is a
        click anywhere else — go to whoever sent it, which the callback
        does by raising their window, and which counts as seen too. Both
        take the column down first and report afterwards, so a callback
        that is slow or throws cannot leave a dead card on screen, and
        what was on screen is the latch that makes one press one report.

        `item_id` IS PASSED THROUGH UNTOUCHED, None included, because the
        two mean different things to the engine and only the presser knows
        which happened: a click names the card it landed on, while Esc and
        the dismiss key name nobody — and `on_dismiss(None)` is "all of
        them", `on_open(None)` is "the newest". Substituting the newest id
        for a missing one here would quietly turn the dismiss key into a
        one-card dismissal.

        The whole column comes down on any press, whichever card was hit.
        The engine answers with `show(live())` — or `hide()` when nothing
        is left — so what goes back up is the truth about the store rather
        than this thread's guess at it.

        Neither is HintCard.dismissed() — that writes enabled=false into
        config.toml, and this is "seen", not "never again".
        """
        if name not in ("dismiss", "open"):
            return
        with self._state_lock:
            was, self._current, self._cards = self._current, None, []
        if self._thread is not None:
            self._q.put(None)
        callback = self._on_open if name == "open" else self._on_dismiss
        if was is None or callback is None:
            return
        try:
            callback(item_id)
        except Exception:
            _log.info("notify card: could not report a %s", name,
                      exc_info=True)

    def timed_out(self) -> None:
        """The clock ran out: the painter takes it down and nothing is
        marked seen — the reminders exist for exactly this.

        Only reachable with a non-zero `[notify] card_seconds`; the
        default has been 0 since 2026-09-04 and a card with no clock never
        runs out of one."""
        with self._state_lock:
            self._current = None
            self._cards = []

    # -- placement --

    def column(self, cards=None) -> tuple:
        """The size of the WINDOW the column needs, shadow included."""
        import notify_card as nc
        if cards is None:
            with self._state_lock:
                cards = list(self._cards)
        return nc.stack_measure(cards, self.scale)

    def placed(self, x: int, y: int) -> None:
        """A drag ended. Save the edge this column is ANCHORED by.

        Callers hand over the visible card's top-left, as they always have
        (skin\\notify.py adds SHADOW to the window's corner before it calls
        here). Under `anchor="bottom"` the number that has to survive a
        restart is the BOTTOM edge, because that is the one origin() holds
        still — save a top edge and the next launch would put a column of a
        different height somewhere the owner never dropped it, which is the
        whole bug this anchor exists to fix.
        """
        import notify_card as nc
        if self._anchor == "bottom":
            y = int(y) + max(0, self.column()[1] - 2 * nc.SHADOW)
        super().placed(x, y)

    def origin(self, width: int, height: int, screen: tuple,
               inset: int = 0, bounds=None) -> tuple:
        """Where the window's top-left goes — worked out in CARD
        coordinates, because every rule here is about an edge somebody can
        actually see, and turned into the window's at the last line.

        THE BOTTOM EDGE IS WHAT STAYS PUT (`anchor="bottom"`, the default
        since 2026-09-04). The owner keeps this card in the bottom-right of
        his screen, and a card that grew downward went off the bottom of
        it: "sometimes when there is a lot of text the card goes under the
        screen". So a taller column grows UPWARD — `top = anchor - height`
        — and the edge he lined the card up against never moves. With
        `anchor="top"` the old arithmetic is kept exactly, which is what a
        position saved under the old rule needs.

        A saved y IS the anchor edge under the current mode (see `placed`);
        a bottom-* corner anchors the bottom at the screen's own margin, a
        top-* corner anchors the top, and "right"/"left" stay mid-height,
        where a taller column grows both ways at once.

        AND IT NEVER RUNS OFF THE TOP. capture.stack_fits does this job by
        refusing to put up more cards than the work area can hold; here the
        column is ONE window whose card count `[notify] stack_max` already
        bounds, so what is left is the clamp: the card's top edge stays
        inside `bounds`. A card above the top of the screen is neither
        readable nor clickable, which is worse than one never offered.

        Pure arithmetic, so a test can check every corner, every anchor and
        every saved position without a screen.
        """
        sw, sh = screen
        m = self._margin
        vx, vy, vw, vh = bounds if bounds else (0, 0, sw, sh)
        card_w, card_h = width - inset * 2, height - inset * 2
        if self.moved():
            keep = 60                      # this much must stay reachable
            x = max(vx + keep - card_w, min(self.x, vx + vw - keep))
            y = (self.y - card_h) if self._anchor == "bottom" else self.y
            y = max(vy + keep - card_h, min(y, vy + vh - keep))
        else:
            x = m if self._corner.endswith("left") else sw - m - card_w
            if self._corner in ("right", "left"):
                y = (sh - card_h) // 2
            elif self._corner.startswith("top"):
                y = m
            else:
                y = sh - m - card_h
        return int(x - inset), int(max(y, vy) - inset)

    # -- overlay thread --

    def _run(self) -> None:
        try:
            if skin is not None and skin.notify_run(self):   # --- SKIN
                return
            self._build_and_loop()
        except Exception as e:
            _log.info("notify card unavailable: %r", e)
        finally:
            self._alive.set()

    def _build_and_loop(self) -> None:
        """The COLUMN on flat faces, in Tk — the fallback when skin\\ is
        gone.

        notify_card.stack_flat paints the whole column as one image; this
        window only shows it, moves it, keeps whatever clock the cards
        asked for, and turns a click, a drag or Esc into `pressed` or
        `placed`. Same teardown as the review card's: destroyed on the
        thread that built it, then collected there.

        THE WINDOW IS THE CARDS, NOT THE PICTURE. stack_flat's image
        carries the SHADOW margin a layered window needs, and Tk has no
        per-pixel alpha to spend on it, so the margin is cropped off here
        and every mouse coordinate is put back into picture space by
        adding it again. The gaps between cards show the window's own
        CARD_BG rather than the desktop, which is this fallback being
        honest about what Tk can do — skin\\notify.py paints the same
        layout where the gaps really are holes.
        """
        import tkinter as tk
        import notify_card as nc
        from PIL import ImageTk

        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=CARD_BG)
        canvas = tk.Canvas(root, bg=CARD_BG, highlightthickness=0, bd=0)
        canvas.pack()
        self._alive.set()

        st = {"cards": [], "up": False, "deadline": None, "hover": None,
              "drag": None, "from": None, "moved": 0, "press": None,
              "photo": None, "last": 0.0, "tick": time.monotonic(),
              "hushed": False}
        cache: dict = {}
        CLICK_PX = 4          # a release that travelled less is a click

        def progress() -> float:
            deadline, cards = st["deadline"], st["cards"]
            if deadline is None or not cards:
                return 1.0
            seconds = float(cards[0].get("seconds") or 0)
            if seconds <= 0:
                return 1.0
            return max(0.0, (deadline - time.monotonic()) / seconds)

        def ident(index):
            """The id of the card at `index`, or None if there is no such
            card — `pressed` reads None as "all"/"the newest", which is
            the safe answer to a click we could not attribute."""
            cards = st["cards"]
            if index is None or not 0 <= index < len(cards):
                return None
            return cards[index].get("id")

        def hide() -> None:
            st["cards"], st["deadline"], st["hover"] = [], None, None
            st["drag"], st["press"] = None, None
            self.rect = None
            cache.clear()
            if st["up"]:
                root.withdraw()
                st["up"] = False

        def paint() -> None:
            if not st["cards"]:
                return
            pad = nc.SHADOW
            whole = nc.stack_flat(st["cards"], self.scale, st["hover"],
                                  cache, progress())
            img = whole.crop((pad, pad, whole.width - pad,
                              whole.height - pad))
            photo = ImageTk.PhotoImage(img, master=root)
            canvas.delete("all")
            canvas.configure(width=img.width, height=img.height)
            canvas.create_image(0, 0, anchor="nw", image=photo)
            st["photo"] = photo               # Tk keeps no reference
            st["last"] = time.monotonic()

        def put_up(cards: list) -> None:
            st["cards"], st["hover"] = list(cards), None
            st["press"] = None
            cache.clear()
            seconds = float(cards[0].get("seconds") or 0) if cards else 0
            st["deadline"] = ((time.monotonic() + seconds)
                              if seconds > 0 else None)
            if st["hushed"]:
                # ARRIVED MID-SELECTION, which is the exact case the hush
                # exists for: a notification landing while the owner is
                # dragging a crop. The item is accepted and its clock is
                # already waiting (see pump), but nothing is mapped —
                # this window is `-topmost` and would go straight over
                # the selector and swallow the drag. `map_card` puts it
                # up the moment the screen is his again.
                return
            map_card()

        def map_card() -> None:
            """Draw the held column and bring the window up where it goes.

            `origin` is asked for the CARDS' rectangle with no inset,
            because that is exactly what this window is — the shadow
            margin was cropped off in paint(). The glass path asks the
            same question with `inset=SHADOW` and gets the same visible
            edge, which is the whole point of that parameter.
            """
            if not st["cards"]:
                return
            pad = nc.SHADOW
            win_w, win_h = nc.stack_measure(st["cards"], self.scale)
            w, h = win_w - 2 * pad, win_h - 2 * pad
            x, y = self.origin(w, h, (root.winfo_screenwidth(),
                                      root.winfo_screenheight()))
            paint()
            root.geometry(f"{w}x{h}+{x}+{y}")
            self.rect = (x, y, x + w, y + h)
            # Read BEFORE the window is shown, every time it goes from
            # withdrawn to shown: by the time it is mapped, the answer
            # is this window. See _give_focus_back.
            had = _foreground() if not st["up"] else 0
            root.deiconify()
            root.update_idletasks()
            if not st["up"]:
                # Both need a realised window, and both silently succeed
                # on an unrealised one. Click-taking, not click-through:
                # the click IS the dismissal.
                _no_activate(root)
                # THIS IS THE ONE THE OWNER COMPLAINED ABOUT. There was a
                # `_hide_from_capture(root)` on this line; it went on
                # 2026-09-04. The card that says Claude has finished is
                # the single most screenshot-worthy thing this app puts
                # on screen, and WDA_EXCLUDEFROMCAPTURE meant it was the
                # one thing that could not be photographed — press
                # Win+Shift+S and it appeared to blink out. It never did:
                # the HWND was untouched and the compositor was simply
                # leaving it out of the grab the selector paints itself
                # with. Ordering, not flags — see the class docstring.
                _give_focus_back(had)
            st["up"] = True

        def set_hushed(on: bool) -> None:
            """Obey `self._hushed`, on this card's own thread and nowhere
            else. The caller only set an Event; every Tk call is here."""
            if on == st["hushed"]:
                return
            st["hushed"] = on
            if on:
                if st["up"]:
                    root.withdraw()
                    st["up"] = False
                # No rect means `hovering()` says no and the Esc-over-the
                # card key finds nothing, which is right: a window that is
                # not on screen cannot be under the pointer.
                self.rect = None
            else:
                map_card()

        def hit(event):
            """(code, (index, what)) for a mouse event.

            The window is the cards; the picture is the cards plus the
            shadow margin. SHADOW is added back so the point is in the
            coordinates stack_hit_test and the painter share — the same
            correction the single card has always made here.
            """
            if not st["cards"]:
                return None, None
            return nc.stack_hit_test(st["cards"], self.scale,
                                     event.x + nc.SHADOW,
                                     event.y + nc.SHADOW)

        def on_press(event) -> None:
            code, where = hit(event)
            what = where[1] if where else None
            if code == nc.HTCLIENT and what == nc.DISMISS:
                # The × of ONE card, named by its own id: everything else
                # in the column stays unread.
                self.pressed("dismiss", ident(where[0]))
            elif code == nc.HTCAPTION:
                st["drag"] = (event.x_root - root.winfo_x(),
                              event.y_root - root.winfo_y())
                st["from"] = (event.x_root, event.y_root)
                st["moved"] = 0
                st["press"] = where[0] if where else None

        def on_motion(event) -> None:
            if st["drag"] is not None:
                ox, oy = st["from"]
                st["moved"] = max(st["moved"], abs(event.x_root - ox)
                                  + abs(event.y_root - oy))
                if st["moved"] < CLICK_PX:
                    return                # still a click until it is not
                dx, dy = st["drag"]
                root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")
                return
            code, where = hit(event)
            want = where if code == nc.HTCLIENT else None
            if want != st["hover"]:
                st["hover"] = want
                paint()

        def on_leave(_event) -> None:
            if st["hover"] is not None:
                st["hover"] = None
                paint()

        def on_release(_event) -> None:
            if st["drag"] is None:
                return
            st["drag"] = None
            if st["moved"] < CLICK_PX:
                # Pressed and let go where it was: a click on the card
                # away from the ×, which is "take me there" — and it is
                # the card the press LANDED on that we go to. The × got
                # its own pressed("dismiss") on the way down, in
                # on_press, and never reaches here — it is HTCLIENT, not
                # the HTCAPTION area that starts a drag.
                self.pressed("open", ident(st["press"]))
                return
            x, y = root.winfo_x(), root.winfo_y()
            if st["cards"]:
                win_w, win_h = nc.stack_measure(st["cards"], self.scale)
                pad = nc.SHADOW
                self.rect = (x, y, x + win_w - 2 * pad, y + win_h - 2 * pad)
            self.placed(x, y)

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_motion)
        canvas.bind("<Motion>", on_motion)
        canvas.bind("<Leave>", on_leave)
        canvas.bind("<ButtonRelease-1>", on_release)

        def pump() -> None:
            try:
                while True:
                    item = self._q.get_nowait()
                    if item is _DONE:
                        self._closing.set()
                        return
                    if item is None:
                        hide()
                    else:
                        put_up(item)
            except queue.Empty:
                pass
            # Read once a tick, AFTER the queue, so a card that arrived in
            # this same frame is already in `st` and gets held rather than
            # mapped. Thirty milliseconds is well inside the time the
            # desktop freeze takes, so the window is off the live screen
            # before the selector maps over it.
            set_hushed(self._hushed.is_set())
            now = time.monotonic()
            dt, st["tick"] = now - st["tick"], now
            if st["cards"]:
                if st["deadline"] is not None and (self.hovering()
                                                   or st["hushed"]):
                    # Reading it, or hushed for somebody's selection —
                    # either way the clock waits. Seconds spent while the
                    # card is off the screen are not seconds the owner
                    # had it, which is the promise capture.ShotCards
                    # already makes for the screenshot deck.
                    st["deadline"] += dt
                if st["up"]:
                    if (st["deadline"] is not None
                            and st["deadline"] - now <= 0):
                        self.timed_out()
                        hide()
                        root.after(30, pump)
                        return
                    # The repaint is the CLOCK'S. With `seconds` at 0 —
                    # the default since 2026-09-04 — nothing on the column
                    # changes between mouse events, so painting ten times
                    # a second would be ten copies of the same picture.
                    if st["deadline"] is not None and now - st["last"] >= 0.1:
                        paint()
            root.after(30, pump)

        pump()
        try:
            _pump_until(root, self._closing)
        finally:
            import gc                       # see Splash: same Tcl teardown
            try:
                _forget_window(root)
                root.destroy()
            except Exception:
                pass
            st.clear()
            cache.clear()
            paint = pump = hide = put_up = None          # noqa: F841
            canvas = root = None                          # noqa: F841
            gc.collect()


# The fallback card's palette — LAMPLIGHT, spelled out rather than
# imported: ui.py builds Tk styles at import and this module is imported
# before any of that exists. skin\ repaints its own copy and never reads
# these. A key chip is a KEY CAP and not a button: this card is a legend
# with fifteen keys on it, and fifteen accent chips would be fifteen
# primary actions competing for one glance. So the chips take ui.KeyCap's
# own face and the only lit thing on the card is the state dot.
CARD_BG = "#24201a"
CARD_LINE = "#3a342a"
CARD_FG = "#f1ece2"
CARD_DIM = "#b2a896"
CARD_FAINT = "#7e7564"
CARD_KEY_BG = "#29241d"
CARD_KEY_EDGE = "#4e4737"
CARD_KEY_FG = "#f1ece2"
CARD_DOT = {"recording": "#ff5b4e", "locked": "#ff8a7e"}

_HINT_PAD = 14
_HINT_ROW = 26
_HINT_CHIP = 19


def _hint_paint(canvas, card: dict, scale: float = 1.0) -> tuple[int, int]:
    """Draw the card onto a Tk canvas; return the size it needs.

    Two columns, never one string: a chip on the right and the label to
    its left, each its own canvas item. A single "Esc — ביטול" string is
    exactly the mixed Hebrew-and-Latin line Tk 8.6 lays out backwards
    (popup.py proved this glyph by glyph), and there is no bidi to reach
    for here. Two items sidestep the question entirely.

    `scale` is honoured but cannot be CHANGED from here: this window is
    click-through, for the same reason the dot is, and skin\\hint.py is
    where the − and + live. A size chosen there still comes back here,
    because it is saved in config.toml rather than held in a window.
    """
    s = max(0.6, min(1.4, float(scale)))
    font = ("Rubik", max(6, round(9 * s)))
    bold = ("Rubik", max(6, round(9 * s)), "bold")
    head = ("Rubik", max(7, round(11 * s)), "bold")
    canvas.delete("all")
    width = round(300 * s)
    right = width - _HINT_PAD
    y = _HINT_PAD

    canvas.create_oval(right - 9, y + 3, right - 1, y + 11, width=0,
                       fill=CARD_DOT.get(card.get("dot"), CARD_FG))
    canvas.create_text(right - 16, y + 7, text=card["title"], anchor="e",
                       fill=CARD_FG, font=head)
    canvas.create_text(right - 16, y + 25, text=card["sub"], anchor="e",
                       fill=CARD_DIM, font=("Rubik", 8))
    y += 42
    canvas.create_line(_HINT_PAD, y, right, y, fill=CARD_LINE)
    y += 8

    def rows(items):
        nonlocal y
        for key, label, on in items:
            chip_w = max(30, 7 * len(key) + 14)
            canvas.create_rectangle(
                right - chip_w, y + 2, right, y + 2 + _HINT_CHIP,
                fill=CARD_KEY_BG if on else CARD_BG,
                outline=CARD_KEY_EDGE if on else CARD_LINE)
            canvas.create_text(right - chip_w / 2, y + 2 + _HINT_CHIP / 2,
                               text=key, anchor="center", font=bold,
                               fill=CARD_KEY_FG if on else CARD_FAINT)
            canvas.create_text(right - chip_w - 9, y + 2 + _HINT_CHIP / 2,
                               text=label, anchor="e", font=font,
                               fill=CARD_FG if on else CARD_FAINT)
            y += _HINT_ROW

    rows(card["rows"])
    y += 2
    canvas.create_text(right, y + 4, text=card["section"], anchor="e",
                       fill=CARD_FAINT, font=("Rubik", 8, "bold"))
    y += 17
    rows(card["keys"])
    y += 6
    canvas.create_line(_HINT_PAD, y, right, y, fill=CARD_LINE)
    y += 10
    canvas.create_rectangle(right - 12, y, right, y + 12,
                            fill=CARD_BG, outline=CARD_LINE)
    canvas.create_text(right - 20, y + 6, text=card["footer"], anchor="e",
                       fill=CARD_DIM, font=("Rubik", 8))
    return width, y + 12 + _HINT_PAD
