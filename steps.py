"""One window for a download that asks first: the model (models.py) and
the packs (packs.py) — DISTRIBUTION_PLAN.md 6.4 and 6.5, D13, D14.

The shape every such step keeps: a Hebrew paragraph saying what and
why, the size and the folder in one plain line BEFORE any byte moves,
the licence links when the bytes are somebody else's, [Download] on the
right where the eye lands first in a Hebrew window and [Not now] beside
it; then a bar with bytes, percent and rate, [Pause] instead of [Not
now], and the window closes itself when the work is verified. Built on
ui.py like the wizard: the paragraph goes through the bitmap path
(DrawTextW + DT_RTLREADING, chapter 9.1), the chrome is English.

The work runs on a thread and talks to the window through a queue; the
window never blocks and never touches Tk from the worker. `run()`
returns `done` or `later` and never raises — a step that could stop the
app from starting is worse than no step (main.py shows these before
the wizard). The wizard of chapter 9 will host the same pieces as pages;
until then each is its own window.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger("app")


def human(n: int) -> str:
    """Decimal units, the way the Hub and PyPI print them: 1.62 GB, 312 MB."""
    n = int(n)
    if n >= 1_000_000_000:
        return f"{n / 1e9:.2f} GB"
    if n >= 1_000_000:
        return f"{n / 1e6:.0f} MB"
    if n >= 1_000:
        return f"{n / 1e3:.1f} kB"
    return f"{n} B"


@dataclass
class Step:
    """What one step says and does. `work(progress, cancel, stage)` is
    the runner: `progress(done, total)` in bytes, `stage(word)` for the
    status line ("downloading", "verifying", "installing"), `cancel` a
    threading.Event; it raises net.DownloadError (or anything) to fail."""

    title: str                       # Hebrew, one line
    body: str                        # Hebrew paragraph
    size_line: str                   # English: "1.62 GB from … into …"
    total: int                       # bytes, for the bar
    work: object                     # callable(progress=, cancel=, stage=)
    links: list[tuple[str, str]] = field(default_factory=list)   # (label, url)
    button: str = "Download"
    #: Hebrew sentences for the end states; {why} gets the reason.
    said: dict[str, str] = field(default_factory=dict)


SAID = {
    "offline": ("אין חיבור לאינטרנט. נשאל שוב בהפעלה הבאה, "
                "וההורדה תימשך מאותה נקודה."),
    "failed": "ההורדה נכשלה ({why}). נשאל שוב בהפעלה הבאה.",
    "paused": "ההורדה נעצרה. בהפעלה הבאה היא תימשך מאותה נקודה.",
    "done": "הושלם ונבדק.",
}

STAGES = {"verifying": "Checking the files…", "installing": "Installing…"}


class StepWindow:
    """`run()` shows the window and returns `done`, `declined` ([Not now]
    before anything started — the caller may write that down) or `later`
    (paused, offline, failed: the next start asks again). `start()` is
    the primary button, callable from a test too; `_not_now()` the
    other one."""

    W, H, PAD = 640, 400, 28
    BAR_H = 10

    def __init__(self, step: Step):
        import tkinter as tk

        import ui

        self._ui = ui
        self.step = step
        self.outcome = "later"
        self._cancel = threading.Event()
        self._events: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._started = False
        self._rate = 0.0
        self._last = (0, time.monotonic())
        self._closing = False
        self._after = None
        self.status_text = ""

        # A PhotoImage belongs to the interpreter that made it: this
        # window may follow the dashboard in a test process and precede
        # the wizard in the app's, so the cache is emptied on both sides.
        ui.forget_images()
        self.root = tk.Tk()
        self.root.title("DeskIT")
        self.root.configure(bg=ui.BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._not_now)
        try:
            import dashboard
            dashboard._set_window_icon(self.root)
            dashboard._dark_caption(self.root)
        except Exception:                                    # noqa: BLE001
            pass
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{max(0, (sh - self.H) // 3)}")

        body = tk.Frame(self.root, bg=ui.BG)
        body.pack(fill="both", expand=True, padx=self.PAD, pady=(self.PAD, 0))
        self._para(body, step.title, pt=17, colour=ui.FG, lines=1)
        self._para(body, step.body, pt=10, colour=ui.DIM, lines=5, pady=(6, 14))
        tk.Label(body, text=step.size_line, bg=ui.BG, fg=ui.FAINT, font=(ui.UI, 9),
                 anchor="w", justify="left", wraplength=self.W - 2 * self.PAD).pack(fill="x")
        if step.links:
            row = tk.Frame(body, bg=ui.BG)
            row.pack(fill="x", pady=(4, 0))
            for label, url in step.links:
                link = tk.Label(row, text=label, bg=ui.BG, fg=ui.ACCENT_TEXT,
                                font=(ui.UI, 9, "underline"), cursor="hand2")
                link.pack(side="left", padx=(0, 14))
                link.bind("<Button-1>", lambda _e, u=url: self._open(u))
        self.bar = tk.Canvas(body, width=self.W - 2 * self.PAD, height=self.BAR_H,
                             bg=ui.BG, highlightthickness=0, bd=0)
        self.bar.pack(fill="x", pady=(16, 6))
        self.bar.create_rectangle(0, 0, self.W - 2 * self.PAD, self.BAR_H,
                                  fill=ui.LINE, outline="")
        self._bar_fill = self.bar.create_rectangle(0, 0, 0, self.BAR_H, fill=ui.ACCENT, outline="")
        self.status = tk.Label(body, text="", bg=ui.BG, fg=ui.DIM, font=(ui.UI, 9), anchor="w")
        self.status.pack(fill="x")
        self.note = tk.Label(body, bg=ui.BG, anchor="e")
        self.note.pack(fill="x", pady=(8, 0))

        foot = tk.Frame(self.root, bg=ui.BG)
        foot.pack(fill="x", padx=self.PAD, pady=self.PAD)
        self.go = ui.Button(foot, step.button, self.start, bg=ui.BG, primary=True, w=150)
        self.go.pack(side="right")
        self.later = ui.Button(foot, "Not now", self._not_now, bg=ui.BG, quiet=True, w=110)
        self.later.pack(side="right", padx=(0, 10))
        self._after = self.root.after(100, self._poll)

    # ------------------------------------------------------------ drawing
    def _para(self, parent, text: str, *, pt: int, colour: str, lines: int,
              pady=(0, 0)):
        import tkinter as tk

        ui = self._ui
        photo, _h, _n = ui.draw_text(text, pt=pt, width=self.W - 2 * self.PAD,
                                     max_lines=lines, colour=colour, bg=ui.BG, rtl=True)
        label = tk.Label(parent, image=photo, bg=ui.BG, anchor="e")
        label.photo = photo
        label.pack(fill="x", pady=pady)
        return label

    def _say(self, text: str, colour: str | None = None) -> None:
        ui = self._ui
        photo, _h, _n = ui.draw_text(text, pt=10, width=self.W - 2 * self.PAD, max_lines=3,
                                     colour=colour or ui.FG, bg=ui.BG, rtl=True)
        self.note.configure(image=photo)
        self.note.photo = photo

    def _set_status(self, text: str) -> None:
        self.status_text = text
        self.status.configure(text=text)

    def _draw(self, done: int, total: int) -> None:
        width = self.W - 2 * self.PAD
        frac = min(1.0, done / total) if total else 0.0
        self.bar.coords(self._bar_fill, 0, 0, int(width * frac), self.BAR_H)
        now = time.monotonic()
        last_done, last_at = self._last
        if now - last_at >= 0.5:
            rate = (done - last_done) / (now - last_at)
            self._rate = rate if not self._rate else 0.7 * self._rate + 0.3 * rate
            self._last = (done, now)
        speed = f" — {human(int(self._rate))}/s" if self._rate > 0 else ""
        self._set_status(f"{human(done)} of {human(total)} ({frac * 100:.0f}%){speed}")

    @staticmethod
    def _open(url: str) -> None:
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:                                    # noqa: BLE001
            log.info("could not open %s", url)

    # ------------------------------------------------------------ actions
    def start(self) -> None:
        """The primary button: the work on a thread, the window keeps
        painting."""
        if self._thread is not None:
            return
        self._started = True
        self.go.enable(False)
        self.later.configure_text("Pause")
        self._set_status(f"0 B of {human(self.step.total)}")

        def work() -> None:
            try:
                self.step.work(progress=self._progress, cancel=self._cancel,
                               stage=self._stage)
                self._events.put(("done",))
            except Exception as err:                         # noqa: BLE001
                reason = getattr(err, "reason", "error")
                if reason == "error":
                    log.warning("step: the work thread tripped", exc_info=True)
                self._events.put(("failed", reason, str(err)))
        self._thread = threading.Thread(target=work, daemon=True, name="step-work")
        self._thread.start()

    def _not_now(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._cancel.set()            # the thread reports "cancelled"
            self.later.enable(False)
            return
        self._finish("later" if self._started else "declined")

    def _progress(self, done: int, total: int) -> None:
        self._events.put(("progress", done, total))

    def _stage(self, word: str) -> None:
        self._events.put(("stage", word))

    # ---------------------------------------------------------------- loop
    def _poll(self) -> None:
        if self._closing:
            return
        ui = self._ui
        said = {**SAID, **self.step.said}
        while not self._closing:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            try:
                kind = event[0]
                if kind == "progress":
                    self._draw(event[1], event[2])
                elif kind == "stage" and event[1] in STAGES:
                    self._set_status(STAGES[event[1]])
                elif kind == "done":
                    self._draw(self.step.total, self.step.total)
                    self._set_status(f"{human(self.step.total)} — verified")
                    self._say(said["done"], ui.GREEN)
                    self.root.after(700, lambda: self._finish("done"))
                elif kind == "failed":
                    reason, why = event[1], event[2]
                    self.later.enable(True)
                    self.later.configure_text("Close")
                    if reason == "cancelled":
                        self._set_status("Paused")
                        self._say(said["paused"], ui.DIM)
                    elif reason == "offline":
                        self._set_status("No connection")
                        self._say(said["offline"], ui.AMBER)
                    else:
                        self._set_status("Failed")
                        self._say(said["failed"].format(why=why), ui.RED)
                    log.info("step: stopped (%s): %s", reason, why)
                    self._thread = None
                    self._cancel = threading.Event()
            except Exception:                                # noqa: BLE001
                log.debug("step: the window loop tripped", exc_info=True)
        if not self._closing:
            self._after = self.root.after(100, self._poll)

    def _finish(self, outcome: str) -> None:
        if self._closing:
            return
        self._closing = True
        self.outcome = outcome
        try:
            if self._after is not None:
                self.root.after_cancel(self._after)
            self.root.destroy()
        except Exception:                                    # noqa: BLE001
            pass
        self._ui.forget_images()

    def run(self) -> str:
        self.root.mainloop()
        return self.outcome


def show(step: Step) -> str:
    """The step as a window — `done`, `declined` or `later`; `later` when
    the window cannot be made."""
    try:
        return StepWindow(step).run()
    except Exception:                                        # noqa: BLE001
        log.warning("step: the window could not run", exc_info=True)
        return "later"
