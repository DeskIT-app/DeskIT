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

    def finish(self, text: str | None = None, linger_ms: int = 1100) -> None:
        """Show a last line, then close. Non-blocking: the caller is about
        to go and wait for the quit signal, and the lingering happens on
        the splash thread."""
        if self._thread is None:
            return
        if text:
            self._q.put(text)
        self._q.put((_DONE, linger_ms))

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
                        root.after(max(0, item[1]), self._closing.set)
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


def _hide_from_capture(root) -> bool:
    """Make an overlay invisible to every screen capture on this machine.

    The dot sits in the top-right corner of the screen and pulses red for
    as long as a recording is locked on — and the screenshot key can now
    be pressed while one is. Without this, every screenshot taken while
    dictating comes back with our own indicator burned into the corner of
    it, which is a strange thing to hand somebody and an actively bad one
    to paste into a bug report.

    WDA_EXCLUDEFROMCAPTURE, the same flag capture.py's clip bar uses.
    Re-measured here on this window rather than trusted: a 60x60
    borderless magenta Tk window at +50+50, grabbed through PIL's
    ImageGrab, gave 3600/3600 magenta pixels before the call and
    0/3600 after it (2026-08-30). The desktop behind it lands in the
    frame, not a hole.

    Not imported from capture.py: this module is on the startup path and
    capture.py drags in Pillow, Tk canvases and a video encoder. Eleven
    lines is cheaper than that import, and the flag is one constant.
    """
    WDA_EXCLUDEFROMCAPTURE = 0x00000011
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = int(root.winfo_id())
        target = user32.GetParent(hwnd) or hwnd
        user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p,
                                                    ctypes.c_uint]
        return bool(user32.SetWindowDisplayAffinity(
            ctypes.c_void_p(target), WDA_EXCLUDEFROMCAPTURE))
    except Exception as e:
        # Not fatal and not worth a warning: a dot in the corner of a
        # screenshot is a blemish, and the alternative to it is no dot.
        _log.debug("could not exclude an overlay from capture: %r", e)
        return False


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
        # After the realise, for the same reason _no_activate needs it: the
        # write lands on nothing and reports success on an unrealised Tk
        # window.
        _hide_from_capture(root)
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
