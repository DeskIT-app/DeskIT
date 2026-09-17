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

Three pieces, because two hosts draw the same step (chapter 9.2):

- `StepRun` is the WORK — the thread, the cancel event, the queue the
  thread reports through, and the state a face is drawn from (bytes,
  stage, rate, the end word). It belongs to whoever hosts it, never to
  a widget, so the wizard can move to its next page while the model is
  still coming down and draw the same run again on a later page.
- `StepPane` is the FACE — a ui.py frame that draws one run and its
  two buttons; `refresh()` reads the run's state, and `attach()` points
  it at the next run of a queue.
- `StepWindow` is a Tk root around one pane: the standalone step the
  start shows when the wizard is not due, and the one `main.py
  --download-model` / `--install-pack` open from the dashboard.

`run()`/`show()` return `done` or `later` and never raise — a step that
could stop the app from starting is worse than no step. The window
never blocks and never touches Tk from the worker.
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
    #: A short English name for a queue's status line ("Hebrew model").
    name: str = ""


SAID = {
    "offline": ("אין חיבור לאינטרנט. נשאל שוב בהפעלה הבאה, "
                "וההורדה תימשך מאותה נקודה."),
    "failed": "ההורדה נכשלה ({why}). נשאל שוב בהפעלה הבאה.",
    "paused": "ההורדה נעצרה. בהפעלה הבאה היא תימשך מאותה נקודה.",
    "done": "הושלם ונבדק.",
}

STAGES = {"verifying": "Checking the files…", "installing": "Installing…"}

#: A run's `state`: idle (nothing pressed), running, then one end word.
STATES = ("idle", "running", "done", "paused", "offline", "failed")


class StepRun:
    """The work of one Step, and the state a face is drawn from.

    `start()` puts the work on a thread; `pump()` — called from the
    host's Tk loop — drains what the thread reported and moves the
    state; `status()` is the English status line. The run keeps its
    numbers, so a pane made later draws the right bar at once."""

    def __init__(self, step: Step):
        self.step = step
        self.state = "idle"
        self.done_bytes = 0
        self.total = int(step.total)
        self.stage = ""
        self.why = ""
        self.rate = 0.0
        self.started = False
        self._cancel = threading.Event()
        self._events: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._last = (0, time.monotonic())

    # ------------------------------------------------------------ actions
    def start(self) -> bool:
        """The primary button. False when it is already running."""
        if self._thread is not None and self._thread.is_alive():
            return False
        self.started = True
        self.state = "running"
        self.stage = ""
        self.why = ""
        self._cancel = threading.Event()
        cancel = self._cancel

        def work() -> None:
            try:
                self.step.work(progress=self._progress, cancel=cancel,
                               stage=self._stage)
                self._events.put(("done",))
            except Exception as err:                         # noqa: BLE001
                reason = getattr(err, "reason", "error")
                if reason == "error":
                    log.warning("step: the work thread tripped", exc_info=True)
                self._events.put(("failed", reason, str(err)))
        self._thread = threading.Thread(target=work, daemon=True, name="step-work")
        self._thread.start()
        return True

    def pause(self) -> None:
        """[Pause]: the thread reports `cancelled` and the part stays."""
        self._cancel.set()

    @property
    def running(self) -> bool:
        return self.state == "running"

    @property
    def ended(self) -> bool:
        return self.state in ("done", "paused", "offline", "failed")

    # ------------------------------------------------------- the thread's
    def _progress(self, done: int, total: int) -> None:
        self._events.put(("progress", done, total))

    def _stage(self, word: str) -> None:
        self._events.put(("stage", word))

    # ---------------------------------------------------------------- pump
    def pump(self) -> list[str]:
        """Apply what the thread reported. Returns the end words that
        arrived in this call ("done", "paused", ...), for a face that
        wants to say something the moment they land."""
        landed: list[str] = []
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "progress":
                self._advance(int(event[1]), int(event[2]))
            elif kind == "stage":
                self.stage = str(event[1])
            elif kind == "done":
                self.done_bytes = self.total
                self.state = "done"
                landed.append("done")
            elif kind == "failed":
                reason, self.why = event[1], event[2]
                self.state = {"cancelled": "paused", "offline": "offline"}.get(reason, "failed")
                landed.append(self.state)
                log.info("step: stopped (%s): %s", reason, self.why)
                self._thread = None
        return landed

    def _advance(self, done: int, total: int) -> None:
        self.done_bytes, self.total = done, total or self.total
        now = time.monotonic()
        last_done, last_at = self._last
        if now - last_at >= 0.5:
            rate = (done - last_done) / (now - last_at)
            self.rate = rate if not self.rate else 0.7 * self.rate + 0.3 * rate
            self._last = (done, now)

    # ---------------------------------------------------------------- words
    @property
    def fraction(self) -> float:
        return min(1.0, self.done_bytes / self.total) if self.total else 0.0

    def status(self) -> str:
        """The English line under the bar."""
        if self.state == "idle":
            return ""
        if self.state == "done":
            return f"{human(self.total)} — verified"
        if self.state == "paused":
            return "Paused"
        if self.state == "offline":
            return "No connection"
        if self.state == "failed":
            return "Failed"
        if self.stage in STAGES:
            return STAGES[self.stage]
        speed = f" — {human(int(self.rate))}/s" if self.rate > 0 else ""
        return f"{human(self.done_bytes)} of {human(self.total)} ({self.fraction * 100:.0f}%){speed}"

    def said(self) -> tuple[str, str]:
        """(Hebrew sentence, colour word) for an end state; ("", "") otherwise."""
        words = {**SAID, **self.step.said}
        if self.state == "done":
            return words["done"], "green"
        if self.state == "paused":
            return words["paused"], "dim"
        if self.state == "offline":
            return words["offline"], "amber"
        if self.state == "failed":
            return words["failed"].format(why=self.why), "red"
        return "", ""


class StepPane:
    """One run drawn on a ui.py frame: title, paragraph, size line,
    licence links, bar, status, the Hebrew note, and the two buttons.

    `secondary` is the idle label of the second button ("Not now" in the
    window; None in the wizard, whose own Next is the way on); while the
    run runs it reads Pause, after a stop it reads `closing` ("Close" in
    the window, hidden in the wizard). `on_end(word)` is told each end
    word once, after the note is drawn. `compact` drops the paragraph —
    the wizard's later pages, where the download is a bar and not the
    subject. `on_go` replaces the primary button's action (the wizard
    decides a queue before it starts anything)."""

    BAR_H = 10

    def __init__(self, parent, run: StepRun, *, width: int, bg: str | None = None,
                 secondary: str | None = "Not now", closing: str | None = "Close",
                 on_end=None, compact: bool = False, prefix: str = "",
                 on_go=None, title_pt: int = 17, body_lines: int = 5,
                 foot: bool = False):
        import tkinter as tk

        import ui

        self._tk, self._ui = tk, ui
        self.run = run
        self.width = width
        self.bg = bg or ui.BG
        self.secondary = secondary
        self.closing = closing
        self.on_end = on_end
        self.on_go = on_go
        self.compact = compact
        self.prefix = prefix
        self._told: set[str] = set()
        self._pausing = False
        self._later_shown = True
        self.frame = tk.Frame(parent, bg=self.bg)
        f = self.frame
        # The window keeps its buttons at the foot, where they always
        # were; a page keeps them under the bar, where the eye is.
        self.buttons = tk.Frame(f, bg=self.bg)
        if foot:
            self.buttons.pack(side="bottom", fill="x")
        self.title_pt = 11 if compact else title_pt
        self.body_lines = body_lines
        self.title = self._para(f, run.step.title, pt=self.title_pt, colour=ui.FG, lines=1)
        self.body = None
        self.size = None
        if not compact:
            self.body = self._para(f, run.step.body, pt=10, colour=ui.DIM,
                                   lines=body_lines, pady=(6, 10))
            self.size = tk.Label(f, text=run.step.size_line, bg=self.bg, fg=ui.FAINT,
                                 font=(ui.UI, 9), anchor="w", justify="left", wraplength=width)
            self.size.pack(fill="x")
        self.links = tk.Frame(f, bg=self.bg)
        self.links.pack(fill="x", pady=(4, 0))
        self._draw_links()
        self.bar = tk.Canvas(f, width=width, height=self.BAR_H, bg=self.bg,
                             highlightthickness=0, bd=0)
        self.bar.pack(fill="x", pady=(10 if compact else 14, 6))
        self.bar.create_rectangle(0, 0, width, self.BAR_H, fill=ui.LINE, outline="")
        self._bar_fill = self.bar.create_rectangle(0, 0, 0, self.BAR_H, fill=ui.ACCENT, outline="")
        self.status = tk.Label(f, text="", bg=self.bg, fg=ui.DIM, font=(ui.UI, 9), anchor="w")
        self.status.pack(fill="x")
        self.note = tk.Label(f, bg=self.bg, anchor="e")
        if not foot:
            self.buttons.pack(fill="x", pady=(8, 0))
        self.go = ui.Button(self.buttons, run.step.button, on_go or self.start,
                            bg=self.bg, primary=True, w=150)
        self.go.pack(side="right")
        self.later = ui.Button(self.buttons, secondary or "Pause", self.stop, bg=self.bg,
                               quiet=True, w=110)
        self.later.pack(side="right", padx=(0, 10))
        self.refresh()

    # ------------------------------------------------------------ drawing
    def _para(self, parent, text: str, *, pt: int, colour: str, lines: int,
              pady=(0, 0)):
        ui = self._ui
        photo, _h, _n = ui.draw_text(text, pt=pt, width=self.width, max_lines=lines,
                                     colour=colour, bg=self.bg, rtl=True)
        label = self._tk.Label(parent, image=photo, bg=self.bg, anchor="e")
        label.photo = photo
        label.pack(fill="x", pady=pady)
        return label

    def _repaint(self, label, text: str, *, pt: int, colour: str, lines: int) -> None:
        ui = self._ui
        photo, _h, _n = ui.draw_text(text, pt=pt, width=self.width, max_lines=lines,
                                     colour=colour, bg=self.bg, rtl=True)
        label.configure(image=photo)
        label.photo = photo

    def _draw_links(self) -> None:
        tk, ui = self._tk, self._ui
        for child in self.links.winfo_children():
            child.destroy()
        for label, url in self.run.step.links:
            link = tk.Label(self.links, text=label, bg=self.bg, fg=ui.ACCENT_TEXT,
                            font=(ui.UI, 9, "underline"), cursor="hand2")
            link.pack(side="left", padx=(0, 14))
            link.bind("<Button-1>", lambda _e, u=url: self._open(u))

    def _say(self, text: str, colour: str | None = None) -> None:
        """The Hebrew note under the status line — packed only while it
        has something to say, so an idle pane stays short."""
        ui = self._ui
        if not text:
            self.note.configure(image="")
            self.note.photo = None
            self.note.pack_forget()
            return
        photo, _h, _n = ui.draw_text(text, pt=10, width=self.width, max_lines=3,
                                     colour=colour or ui.FG, bg=self.bg, rtl=True)
        self.note.configure(image=photo)
        self.note.photo = photo
        self.note.pack(fill="x", pady=(6, 0), after=self.status)

    @staticmethod
    def _open(url: str) -> None:
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:                                    # noqa: BLE001
            log.info("could not open %s", url)

    # ------------------------------------------------------------ actions
    def start(self) -> None:
        if self.run.start():
            self.refresh()

    def stop(self) -> None:
        """The second button: Pause while running, otherwise whatever the
        host wired — `on_end("declined")` before a start, `on_end("close")`
        after a stop."""
        if self.run.running:
            self.run.pause()
            self._pausing = True
            self.later.enable(False)
            return
        if self.on_end is not None:
            self.on_end("close" if self.run.started else "declined")

    def attach(self, run: StepRun) -> None:
        """Point the pane at another run (the next of a queue) and redraw
        its words."""
        ui = self._ui
        self.run = run
        self._told = set()
        self._repaint(self.title, run.step.title, pt=self.title_pt, colour=ui.FG, lines=1)
        if self.body is not None:
            self._repaint(self.body, run.step.body, pt=10, colour=ui.DIM,
                          lines=self.body_lines)
        if self.size is not None:
            self.size.configure(text=run.step.size_line)
        self._draw_links()
        self.go.configure_text(run.step.button)
        self._say("")
        self.refresh()

    # ---------------------------------------------------------------- loop
    def refresh(self) -> None:
        """Draw the run as it is now. Cheap; the host calls it every tick."""
        ui = self._ui
        run = self.run
        try:
            self.bar.coords(self._bar_fill, 0, 0, int(self.width * run.fraction), self.BAR_H)
            self.status.configure(text=(self.prefix + run.status()) if run.status() else "")
            self.go.enable(run.state in ("idle", "paused", "offline", "failed"))
            if run.running:
                want = "Pause"
            elif run.ended:
                want, self._pausing = self.closing, False
            else:
                want = self.secondary
            if want is None:
                if self._later_shown:
                    self.later.pack_forget()
                    self._later_shown = False
            else:
                if not self._later_shown:
                    self.later.pack(side="right", padx=(0, 10))
                    self._later_shown = True
                self.later.configure_text(want)
                self.later.enable(not (run.running and self._pausing))
            if run.ended and run.state not in self._told:
                self._told.add(run.state)
                text, colour = run.said()
                self._say(text, {"green": ui.GREEN, "dim": ui.DIM, "amber": ui.AMBER,
                                 "red": ui.RED}.get(colour, ui.FG))
                if self.on_end is not None:
                    self.on_end(run.state)
        except Exception:                                    # noqa: BLE001
            log.debug("step: the pane could not draw", exc_info=True)

    def pack(self, **kw) -> None:
        self.frame.pack(**kw)

    def destroy(self) -> None:
        try:
            self.frame.destroy()
        except Exception:                                    # noqa: BLE001
            pass


class StepWindow:
    """`run()` shows the window and returns `done`, `declined` ([Not now]
    before anything started — the caller may write that down) or `later`
    (paused, offline, failed: the next start asks again). `start()` is
    the primary button, callable from a test too; `_not_now()` the
    other one."""

    W, H, PAD = 640, 400, 28

    def __init__(self, step: Step):
        import tkinter as tk

        import ui

        self._ui = ui
        self.step = step
        self.run_ = StepRun(step)
        self.outcome = "later"
        self._closing = False
        self._after = None

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
        self.pane = StepPane(self.root, self.run_, width=self.W - 2 * self.PAD,
                             on_end=self._ended, foot=True)
        self.pane.pack(fill="both", expand=True, padx=self.PAD, pady=self.PAD)
        self._after = self.root.after(100, self._poll)

    @property
    def status_text(self) -> str:
        return self.run_.status()

    # ------------------------------------------------------------ actions
    def start(self) -> None:
        self.pane.start()

    def _not_now(self) -> None:
        self.pane.stop()

    def _ended(self, word: str) -> None:
        if word == "done":
            self.root.after(700, lambda: self._finish("done"))
        elif word == "declined":
            self._finish("declined")
        elif word == "close":
            self._finish("later")

    # ---------------------------------------------------------------- loop
    def _poll(self) -> None:
        if self._closing:
            return
        try:
            self.run_.pump()
            self.pane.refresh()
        except Exception:                                    # noqa: BLE001
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
