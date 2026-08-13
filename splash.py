"""A startup splash, because the app is invisible while it loads.

Launched from the shortcut it runs under pythonw: no console, no window,
and about 25 seconds of loading two Whisper models onto the GPU before the
hotkey does anything. The only signal was the "ready" cue at the very end,
which is exactly when it is no longer needed — click the shortcut and
nothing happens, so you click it again.

Three things this must not do, all of which a naive splash gets wrong:

- **Steal focus.** You may well be typing when it appears. The window is
  given WS_EX_NOACTIVATE so clicks and keystrokes keep going wherever they
  were going.
- **Land in the taskbar and Alt-Tab.** WS_EX_TOOLWINDOW keeps it out of
  both; it is a status pop-up, not a program you switch to.
- **Take the app down with it.** Every entry point is wrapped: on a
  machine with no display, no Tk, or a hostile window manager, the splash
  silently does nothing and dictation still works.

Tk is not thread-safe, so everything Tk touches happens on the splash's
own thread and callers only ever put strings on a queue.
"""
from __future__ import annotations

import ctypes
import queue
import threading

# Style bits, set after Tk creates the window (Tk exposes neither).
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

BG = "#10131a"
FG = "#e8ecf4"
DIM = "#8b97ad"
ACCENT = "#2d6cdf"

_DONE = object()   # sentinel: close the window


class Splash:
    """Call start(), then status() as often as you like, then finish()."""

    def __init__(self, title: str = "Hebrew Dictation",
                 status: str = "starting…") -> None:
        self._q: queue.Queue = queue.Queue()
        self._title = title
        self._first = status
        self._thread: threading.Thread | None = None
        self._alive = threading.Event()
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
            self._build_and_loop()
        except Exception:
            pass                        # never take the app down
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

        self._no_activate(root)
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
                        # quit(), not destroy(): let mainloop return so the
                        # teardown below runs on THIS thread (see finally).
                        root.after(max(0, item[1]), root.quit)
                    else:
                        label.config(text=item)
            except queue.Empty:
                pass
            root.after(60, pump)

        animate()
        pump()
        try:
            root.mainloop()
        finally:
            # Tcl_AsyncDelete: the interpreter MUST be torn down on the
            # thread that created it. Left to Python's GC, the after()
            # callbacks keep root alive in a reference cycle that gets
            # collected on whichever thread happens to trigger a
            # collection — and freeing Tcl from the wrong thread aborts
            # the process. Observed: exit code 3 on a clean shutdown.
            import gc
            try:
                root.destroy()
            except Exception:
                pass
            animate = pump = None                       # noqa: F841
            label = bar = frame = chip = root = None    # noqa: F841
            gc.collect()

    @staticmethod
    def _no_activate(root) -> None:
        """Keep the splash from stealing focus or appearing in Alt-Tab."""
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            hwnd = int(root.winfo_id())
            # The real top-level is the parent of Tk's client window.
            parent = user32.GetParent(hwnd)
            target = parent or hwnd
            user32.GetWindowLongW.restype = ctypes.c_long
            style = user32.GetWindowLongW(target, GWL_EXSTYLE)
            user32.SetWindowLongW(target, GWL_EXSTYLE,
                                  style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            pass          # cosmetic only — a focus-stealing splash still works
