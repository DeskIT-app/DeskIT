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

BG = "#10131a"
FG = "#e8ecf4"
DIM = "#8b97ad"
ACCENT = "#2d6cdf"

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

    def __init__(self, title: str = "Hebrew Dictation",
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
        bar = tk.Canvas(frame, width=bar_w, height=bar_h, bg="#232a36",
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

STATES = {
    # state:      (fill,      ring,      pulses)
    "ready":      ("#2d6cdf", "#0d1830", False),   # blue: running, idle
    "recording":  ("#e0352b", "#3a0f0c", False),   # red: capturing now
    "locked":     ("#e0352b", "#3a0f0c", True),    # red, breathing: latched
    "busy":       ("#e0a32b", "#332304", False),   # amber: transcribing
    # Grey: loaded and alive, but the keys are inert. Deliberately still
    # VISIBLE — a paused app that showed nothing would be indistinguishable
    # from one that was never started, which is the whole problem the dot
    # exists to solve.
    "paused":     ("#8b97ad", "#1b2029", False),
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


# The fallback card's palette. These are ui.py's ORIGINAL values, spelled
# out rather than imported: ui.py builds Tk styles at import and this
# module is imported before any of that exists. skin\ repaints its own
# copy and never reads these.
CARD_BG = "#161b25"
CARD_LINE = "#232a36"
CARD_FG = "#e8ecf4"
CARD_DIM = "#8b97ad"
CARD_FAINT = "#5d6779"
CARD_KEY_BG = "#1a2740"
CARD_KEY_EDGE = "#2b3f66"
CARD_KEY_FG = "#8fb2f5"
CARD_DOT = {"recording": "#e0352b", "locked": "#e0a32b"}

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
