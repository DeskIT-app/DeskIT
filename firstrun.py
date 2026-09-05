"""The first-run wizard: pick a microphone, prove it works, say something.

Runs ONCE, on a copy nobody has set up (config.SetupConfig — a missing
[setup] section is what a fresh download looks like). `main.py --setup`
runs it again on demand.

WHAT IT IS FOR, AND WHY IT IS THIS AND NOT A README PARAGRAPH.

Setting this app up by hand means running `main.py --list-devices`, reading
a table of PortAudio names, and putting an INDEX into config.toml. That is
a reasonable thing to ask of the person who wrote it and an impossible one
to ask of anybody else, and it is not the hard part anyway. The hard part
is that when it goes wrong it goes wrong SILENTLY: Windows' microphone
privacy switch does not produce an error, a refusal, or a dialog. It
produces a stream of perfect digital silence, the app transcribes it to
nothing, and there is no way to tell that apart from "the app is broken".
That trap has its own entry in the README's troubleshooting list, which is
the wrong place for it: a troubleshooting entry is read after an hour of
believing the program does not work.

So the wizard is built around one moment — a bar that moves when you talk.
If it moves, everything downstream is a detail. If it does not, this says
so in one sentence and opens the exact Settings page, before the user has
formed the opinion that the thing is broken.

Three steps, and the ORDER is the point:

  1. the microphone, with a live meter — instant, and catches the trap
  2. one sentence, recorded and read back — the model loads here, which
     costs ~25 s the first time and is stated rather than hidden
  3. the keys, on one screen you can leave open

Built on ui.py, so it is the dashboard's window rather than a Tk dialog:
same palette, same buttons, same bidi text renderer. Nothing here imports
main.py — the wizard has to run BEFORE the app does, and pulling in the
app's imports would make the "loading" step start before the window.
"""
from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from pathlib import Path

import config as config_mod
import ui

log = logging.getLogger("app")

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.toml"
# "This copy has been set up" is not a setting, it is a fact about one
# installation, and it lives in a gitignored file for the same reason .env
# and vocab.json do.
#
# It was a line in config.toml for about an hour and could not work there.
# config.toml is TRACKED, so the committed file is the one a fresh download
# gets: `done = true` there means nobody ever sees the wizard, and
# `done = false` means every existing install re-runs it on the next pull.
# Worse, config.set_values is a LINE EDITOR — it can only change a key that
# is already in the file — so on any config.toml written before this
# existed, marking the wizard finished raised, and it would have come back
# on every launch for ever.
MARKER = APP_DIR / ".setup-done"

W, H = 720, 560
PAD = 28
METER_W, METER_H = 360, 10
# How long a silent meter is allowed to stay silent before the wizard says
# something. Long enough not to nag someone who is reading the screen,
# short enough to beat the conclusion that the app is broken.
QUIET_S = 6.0
# What counts as "the bar moved". Room noise on an open mic sits well
# under this; a spoken word is far over it. Measured against the same
# Recorder.meter() the ask card draws its wave from.
SPEECH = 0.045
TEST_S = 3.0                        # how long the sample recording runs


def clean_name(name: str) -> str:
    """A device name a person can read.

    Windows hands PortAudio the raw registry value for some devices, and
    for Bluetooth that is an UNRESOLVED INDIRECT STRING with a driver
    path, a resource id and an embedded CRLF in it:

        Headset (@System32\drivers\bthhfenum.sys,#2;%1 Hands-Free%0
        ;(Nothing Ear))

    Rendered as-is that row breaks in half and reads as a fault in this
    program. The friendly half is the last ;-separated chunk, which is
    what Windows itself would have shown after resolving it.
    """
    name = " ".join(str(name or "").split())
    if "@" in name and ";" in name:
        tail = name.rsplit(";", 1)[-1].strip(" ()")
        if tail:
            name = tail
    return name or "?"


def device_key(raw_name, api: str) -> str:
    """How a microphone is named in config.toml: its RAW name, a comma and
    its host API — the exact string sounddevice builds and compares
    against, so it resolves to that one device and no other.

    The RAW name, not the readable one: clean_name() rewrites a Bluetooth
    device's unresolved indirect string into its friendly tail, and that
    tail is not what sounddevice is matching against.

    An INDEX used to be written here, because MME truncates names — but
    the truncation is on both sides of the comparison, so it costs
    nothing, while an index costs everything. Indices shift whenever any
    device appears or disappears, and on 2026-09-05 index 27 stopped being
    this microphone and became "Speakers (Realtek HD Audio output)",
    which stopped the app from starting at all.
    """
    return f'{" ".join(str(raw_name or "").split())}, {api}'


def _devices() -> list[tuple[str, str, str, int]]:
    """(key, readable name, host API, index) for every input device, best
    first.

    The KEY is what gets written to config.toml (see device_key). The
    index is kept for the row's small print — the same microphone appears
    three times on a normal Windows box, they are not equally good, and
    the number is how a person tells two identical names apart.
    """
    try:
        import sounddevice as sd
    except Exception as e:
        log.info("no sounddevice for the wizard: %r", e)
        return []
    out = []
    try:
        apis = sd.query_hostapis()
        for index, dev in enumerate(sd.query_devices()):
            if int(dev.get("max_input_channels", 0)) <= 0:
                continue
            api = apis[dev["hostapi"]]["name"] if dev.get(
                "hostapi") is not None else ""
            raw = dev.get("name", "")
            out.append((device_key(raw, api), clean_name(raw), str(api),
                        index))
    except Exception as e:
        log.info("could not list input devices: %r", e)
        return []
    # WASAPI first: it is the one that gives 16 kHz shared-mode capture
    # without the fallback in recorder.py, and its names are not truncated.
    order = {"Windows WASAPI": 0, "Windows WDM-KS": 1, "MME": 2}
    out.sort(key=lambda d: (order.get(d[2], 3), d[3]))
    return out


def order_for(listing, chosen: str):
    """The list as the wizard shows it: whatever is already selected first.

    Pulled out of the screen so it can be tested: the sort below puts
    WASAPI first, and on this machine the device config.toml already names
    is an MME one that landed ninth — so the row the owner is actually
    using was off the bottom of a list of their own microphones.
    """
    chosen = str(chosen or "")
    mine = [d for d in listing if str(d[0]) == chosen]
    return mine + [d for d in listing if str(d[0]) != chosen]


def default_device() -> str:
    """The device the wizard starts on: whatever Windows calls the default.

    "" would also work — recorder.py reads an empty string as the system
    default — but showing a row selected is what tells someone the list is
    a choice rather than a warning.

    Answers with the same key the rows are keyed by, so the right row
    lights up; "" when the default cannot be named.
    """
    try:
        import sounddevice as sd
        index = sd.default.device[0]
        if index is None or index < 0:
            return ""
        for key, _name, _api, listed in _devices():
            if listed == int(index):
                return key
        return ""
    except Exception:
        return ""


def open_microphone_settings() -> bool:
    """The Settings page for the trap, opened for them."""
    try:
        import os
        os.startfile("ms-settings:privacy-microphone")   # noqa: S606
        return True
    except Exception as e:
        log.info("could not open the microphone settings: %r", e)
        return False


class Meter(tk.Canvas):
    """A bar that moves when you talk, and a mark at its high point.

    The mark is what makes it evidence rather than decoration: a bar that
    twitches once while you are looking away has proved nothing by the
    time you look back, and the whole screen exists to prove one thing.
    """

    def __init__(self, parent, bg: str):
        super().__init__(parent, width=METER_W, height=METER_H + 6, bg=bg,
                         highlightthickness=0, bd=0)
        self._peak = 0.0
        self._track = self.create_rectangle(
            0, 3, METER_W, 3 + METER_H, fill=ui.EDGE, width=0)
        self._fill = self.create_rectangle(0, 3, 0, 3 + METER_H,
                                           fill=ui.ACCENT, width=0)
        self._mark = self.create_rectangle(0, 0, 0, 0, fill=ui.GREEN, width=0)

    def show(self, level: float) -> None:
        level = max(0.0, min(1.0, float(level)))
        # A meter drawn linearly barely moves for speech: normal talking
        # peaks around 0.1-0.3 of full scale, which is 30 px of 360. The
        # square root is not a decoration, it is what makes the thing
        # readable at the level people actually speak at.
        shown = level ** 0.5
        self.coords(self._fill, 0, 3, METER_W * shown, 3 + METER_H)
        self.itemconfig(self._fill,
                        fill=ui.GREEN if self._peak >= SPEECH else ui.ACCENT)
        if level > self._peak:
            self._peak = level
            x = METER_W * (self._peak ** 0.5)
            self.coords(self._mark, x - 1, 0, x + 1, METER_H + 6)

    @property
    def peak(self) -> float:
        return self._peak

    def forget(self) -> None:
        self._peak = 0.0
        self.coords(self._mark, 0, 0, 0, 0)


class Listener:
    """One Recorder, opened on a device and closed when you pick another.

    Everything about the audio path is the app's own: the same Recorder
    the dictation uses, on the same sample rate, so a meter that moves
    here is a promise about the thing that runs afterwards rather than
    about a second, simpler code path that happens to work.
    """

    def __init__(self, sample_rate: int):
        self._rate = sample_rate
        self._rec = None
        self.error = ""

    def listen_to(self, device: str) -> bool:
        self.close()
        self.error = ""
        try:
            from recorder import Recorder
            self._rec = Recorder(self._rate, device or None, 600.0,
                                 lambda: None)
            self._rec.start_stream()
            return True
        except Exception as e:
            self._rec = None
            self.error = str(e) or e.__class__.__name__
            log.info("wizard could not open device %r: %r", device, e)
            return False

    def level(self) -> float:
        if self._rec is None:
            return 0.0
        try:
            return float(self._rec.meter()[0])
        except Exception:
            return 0.0

    def record(self, seconds: float):
        """Capture a sample. Returns (wav bytes, seconds) or (None, 0)."""
        if self._rec is None:
            return None, 0.0
        self._rec.begin()
        time.sleep(seconds)
        try:
            return self._rec.end()
        except Exception as e:
            log.info("wizard recording failed: %r", e)
            return None, 0.0

    def close(self) -> None:
        if self._rec is not None:
            try:
                self._rec.close()
            except Exception:
                pass
            self._rec = None


def transcribe(cfg, wav: bytes) -> tuple[str, str]:
    """(text, problem). Loads the real backend — ~25 s cold, and said so.

    The app's own `get_transcriber`, not a shortcut: the point of the step
    is to prove the pipeline the user is about to rely on, and a wizard
    that passed while the app failed would be worse than no wizard.
    """
    try:
        from transcribers import get_transcriber
        backend = get_transcriber(cfg)
        return (backend.transcribe(wav) or "").strip(), ""
    except Exception as e:
        log.info("wizard transcription failed: %r", e, exc_info=True)
        return "", str(e) or e.__class__.__name__


class Wizard:
    """Three screens in one window, and a Back that actually goes back.

    Not a chain of modal dialogs: every step here can fail in a way whose
    fix is on the PREVIOUS step ("no, it was the other microphone"), and a
    dialog chain you cannot walk back turns that into starting over.
    """

    def __init__(self, cfg, path: Path = CONFIG_PATH,
                 marker: Path | None = None):
        self.cfg = cfg
        self.path = path
        self.marker = MARKER if marker is None else marker
        self.device = cfg.audio.device or default_device()
        self.listener = Listener(cfg.audio.sample_rate)
        self.saved = False
        self.step = 0
        self._rows: dict[str, tk.Widget] = {}
        self._quiet_since = time.monotonic()
        self._warned = False
        self._busy = False
        self._sample = ""
        self._closing = False

        self.root = tk.Tk()
        self.root.title("DeskIT")
        self.root.configure(bg=ui.BG)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._centre()
        try:
            import dashboard
            dashboard._set_window_icon(self.root)
            dashboard._dark_caption(self.root)
        except Exception:
            pass                      # cosmetic: never a reason not to run

        self.body = tk.Frame(self.root, bg=ui.BG)
        self.body.pack(fill="both", expand=True, padx=PAD, pady=(PAD, 0))
        self.foot = tk.Frame(self.root, bg=ui.BG)
        self.foot.pack(fill="x", padx=PAD, pady=PAD)
        # RTL: the primary action sits on the RIGHT, where the eye lands
        # first in a Hebrew window, and Back to its left.
        self.next = ui.Button(self.foot, "", self._next, bg=ui.BG,
                              primary=True, w=150)
        self.next.pack(side="right")
        self.back = ui.Button(self.foot, "חזור", self._back, bg=ui.BG,
                              quiet=True, w=96)
        self.back.pack(side="right", padx=(0, 10))
        self.note = tk.Label(self.foot, text="", bg=ui.BG, fg=ui.FAINT,
                             font=(ui.UI, 9), anchor="w")
        self.note.pack(side="left", fill="x", expand=True)

        self._show_step()
        self.root.after(60, self._tick)

    # ---------------------------------------------------------------- frame
    def _centre(self) -> None:
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 3)}")

    def _clear(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self._rows = {}

    def _para(self, text: str, *, pt: int, colour: str, lines: int = 4,
              pady=(0, 0)) -> None:
        """A Hebrew paragraph, drawn by Windows rather than by Tk.

        Tk hands a string to ExtTextOutW with an LTR base direction and no
        way to say otherwise: Hebrew words come out shaped correctly but
        the RUNS of a mixed line are laid out backwards, and wraplength
        measures the wrong edge, so a long sentence loses its left-hand
        words. ui.draw_text is the DrawTextW + DT_RTLREADING path this
        repo already proved glyph by glyph — the same one the ask card and
        the hint card use.

        The PhotoImage is kept on the widget: Tk drops an image the moment
        nothing references it, and the label then goes blank.
        """
        photo, _h, _n = ui.draw_text(text, pt=pt, width=W - PAD * 2,
                                     max_lines=lines, colour=colour,
                                     bg=ui.BG, rtl=True)
        label = tk.Label(self.body, image=photo, bg=ui.BG, anchor="e")
        label.photo = photo
        label.pack(fill="x", pady=pady)

    def _title(self, text: str, sub: str) -> None:
        self._para(text, pt=17, colour=ui.FG, lines=1)
        self._para(sub, pt=10, colour=ui.DIM, lines=4, pady=(6, 18))

    # ---------------------------------------------------------------- steps
    def _show_step(self) -> None:
        self._clear()
        (self._step_mic, self._step_say, self._step_done)[self.step]()
        self.back.enable(self.step > 0)
        self.next.configure_text(("המשך", "המשך", "סיימתי")[self.step])

    def _step_mic(self) -> None:
        self._title("איזה מיקרופון?",
                    "דבר עכשיו. הפס למטה צריך לזוז. אם הוא לא זז — "
                    "המיקרופון לא מגיע לאפליקציה, וזאת כמעט תמיד הגדרה "
                    "של ווינדוס ולא תקלה.")
        listing = _devices()
        if not listing:
            tk.Label(self.body, text="לא נמצא אף מיקרופון.", bg=ui.BG,
                     fg=ui.RED, font=(ui.UI, 11), anchor="e").pack(fill="x")
            return
        # Every device, not the first few: a silent cap here is somebody
        # whose microphone is ninth concluding it is not supported.
        holder = ui.Scroller(self.body, w=W - PAD * 2 - 10, h=250, bg=ui.BG)
        holder.pack(fill="both", expand=True)
        for key, name, api, index in order_for(listing, self.device):
            self._device_row(holder.inner, key, name, api, index)
        holder.bind_wheel(holder.inner)
        bar = tk.Frame(self.body, bg=ui.BG)
        bar.pack(fill="x", pady=(16, 0))
        self.meter = Meter(bar, ui.BG)
        self.meter.pack(side="right")
        self.meter_note = tk.Label(bar, text="", bg=ui.BG, fg=ui.DIM,
                                   font=(ui.UI, 9), anchor="e")
        self.meter_note.pack(side="right", fill="x", expand=True,
                             padx=(0, 14))
        self._listen()

    def _device_row(self, parent, key: str, name: str, api: str,
                    index: int) -> None:
        # `key` is the identity (what config.toml stores, see device_key);
        # `index` is only ever shown, because two rows can carry the same
        # name and the number is how a person tells them apart.
        chosen = key == self.device
        width = W - PAD * 2 - 10
        row = tk.Canvas(parent, width=width, height=40, bd=0,
                        highlightthickness=0, cursor="hand2",
                        bg=ui.ACCENT_SOFT if chosen else ui.CARD)
        row.pack(fill="x", pady=3)
        row.create_text(width - 16, 14, text=name or f"מכשיר {index}",
                        anchor="e", fill=ui.FG, font=(ui.UI, 10))
        row.create_text(width - 16, 29, text=f"{api}  ·  {index}",
                        anchor="e", fill=ui.FAINT, font=(ui.UI, 8))
        row.bind("<Button-1>", lambda _e, k=key: self._pick(k))
        self._rows[key] = row

    def _pick(self, index: str) -> None:
        if index == self.device:
            return
        self.device = index
        for key, row in self._rows.items():
            row.configure(bg=ui.ACCENT_SOFT if key == index else ui.CARD)
        self.meter.forget()
        self._quiet_since = time.monotonic()
        self._warned = False
        self._listen()

    def _listen(self) -> None:
        if self.listener.listen_to(self.device):
            self.meter_note.configure(text="מדבר? הפס צריך לזוז", fg=ui.DIM)
        else:
            self.meter_note.configure(
                text=f"אי אפשר לפתוח את המיקרופון: {self.listener.error}",
                fg=ui.RED)

    def _step_say(self) -> None:
        self._title("תגיד משפט אחד",
                    "לחץ, דבר שלוש שניות, וקרא מה שיצא. בפעם הראשונה "
                    "טעינת המודל לוקחת בערך 25 שניות — פעם אחת, לא בכל "
                    "הכתבה.")
        self.say = ui.Button(self.body, "הקלט 3 שניות", self._record,
                             bg=ui.BG, primary=True, w=200, h=44)
        self.say.pack(anchor="e")
        self.result = tk.Label(
            self.body, text=self._sample, bg=ui.CARD, fg=ui.FG,
            font=(ui.TEXT, 13), anchor="e", justify="right",
            wraplength=W - PAD * 2 - 40, padx=18, pady=18)
        self.result.pack(fill="x", pady=(18, 0))
        self.status = tk.Label(self.body, text="", bg=ui.BG, fg=ui.DIM,
                               font=(ui.UI, 9), anchor="e")
        self.status.pack(fill="x", pady=(10, 0))

    def _step_done(self) -> None:
        self._title("זהו.",
                    "המיקרופון נשמר. מכאן זה עובד בכל חלון, בלי לפתוח "
                    "שום דבר.")
        keys = [("החזק ודבר", self.cfg.hotkey),
                ("נעילה — לדבר בלי להחזיק", self.cfg.latch_hotkey),
                ("פיסוק למה שהרגע נדבק", self.cfg.punctuate_hotkey),
                ("שאלה על המסך", getattr(
                    getattr(self.cfg, "visual_qa", None), "hotkey", ""))]
        keys = [(label, key) for label, key in keys if key]
        width = W - PAD * 2
        card = tk.Canvas(self.body, width=width, height=42 * len(keys) + 14,
                         bg=ui.CARD, bd=0, highlightthickness=0)
        card.pack(fill="x")
        y = 21
        for label, key in keys:
            card.create_text(width - 18, y, text=label, anchor="e",
                             fill=ui.FG, font=(ui.UI, 11))
            # right-aligned AT x, so this is the pill's right edge
            ui.pill(card, 190, y - 15, _pretty(key), ui.CARD, size=9,
                    fill=ui.ACCENT_SOFT, border=ui.ACCENT_EDGE,
                    colour=ui.ACCENT_TEXT)
            y += 42

    # ------------------------------------------------------------- the loop
    def _tick(self) -> None:
        """The meter, and the one sentence this whole screen exists for."""
        if self._closing:
            return
        if self.step == 0 and getattr(self, "meter", None) is not None:
            level = self.listener.level()
            self.meter.show(level)
            if level >= SPEECH:
                self._quiet_since = time.monotonic()
                if not self._warned:
                    self.meter_note.configure(text="נשמע. אפשר להמשיך",
                                              fg=ui.GREEN)
            elif (not self._warned
                    and self.meter.peak < SPEECH
                    and time.monotonic() - self._quiet_since > QUIET_S):
                self._warn_silent()
        self.root.after(60, self._tick)

    def _warn_silent(self) -> None:
        """The trap, named, with the fix one click away.

        Silence is not an error anywhere in Windows' audio API — the
        stream opens, the callbacks arrive, every sample is zero — so
        nothing downstream can report it. Here is the only place it can be
        said before someone decides the app does not work.
        """
        self._warned = True
        self.meter_note.configure(
            text="הפס לא זז. ברוב המקרים ווינדוס חוסם מיקרופון "
                 "לאפליקציות שולחן עבודה.", fg=ui.AMBER)
        ui.Button(self.body, "פתח את ההגדרה בווינדוס",
                  open_microphone_settings, bg=ui.BG, w=230
                  ).pack(anchor="e", pady=(12, 0))

    def _record(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.say.enable(False)
        self.status.configure(text="מקליט…", fg=ui.DIM)
        self.result.configure(text="")

        def work():
            wav, _seconds = self.listener.record(TEST_S)
            if not wav:
                return self._on_result("", "לא נקלט כלום")
            self._later(lambda: self.status.configure(
                text="טוען את המודל ומתמלל…", fg=ui.DIM))
            text, problem = transcribe(self.cfg, wav)
            self._on_result(text, problem)

        threading.Thread(target=work, daemon=True, name="setup-test").start()

    def _later(self, fn) -> None:
        if not self._closing:
            try:
                self.root.after(0, fn)
            except Exception:
                pass

    def _on_result(self, text: str, problem: str) -> None:
        def land():
            self._busy = False
            self.say.enable(True)
            if problem:
                self.status.configure(text=problem, fg=ui.RED)
            elif not text:
                self.status.configure(
                    text="שקט. חזור אחורה ובדוק את הפס.", fg=ui.AMBER)
            else:
                self._sample = text
                self.result.configure(text=text)
                self.status.configure(text="זה מה שהוא שמע.", fg=ui.GREEN)
        self._later(land)

    # ----------------------------------------------------------- navigation
    def _back(self) -> None:
        if self.step == 0:
            return
        self.step -= 1
        self._show_step()
        if self.step == 0:
            self._listen()

    def _next(self) -> None:
        if self.step == 0:
            self._save_device()
        if self.step >= 2:
            self._finish()
            return
        self.step += 1
        self.listener.close()
        self._show_step()

    def _save_device(self) -> None:
        """Write the chosen microphone, by name (device_key), and nothing
        else.

        Through config.set_values like every other writer here: a line
        edit that keeps the comments, because config.toml's comments carry
        the measurements this repo is made of.
        """
        if self.device == (self.cfg.audio.device or ""):
            return
        try:
            config_mod.set_values(self.path, {"audio.device": self.device})
            log.info("setup: microphone set to %s", self.device or "the "
                     "system default")
        except Exception as e:
            log.info("setup could not save the microphone: %r", e)
            self.note.configure(text=f"לא הצלחתי לשמור: {e}", fg=ui.RED)

    def _finish(self) -> None:
        self.saved = mark_done(self.marker)
        self._close()

    def _close(self) -> None:
        self._closing = True
        self.listener.close()
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self) -> bool:
        self.root.mainloop()
        return self.saved


def _pretty(binding: str) -> str:
    import hint
    return hint.pretty(binding)


def needed(cfg, marker: Path | None = None) -> bool:
    """Has this copy never been set up?

    Either signal is enough to say "leave them alone": the marker file
    this writes when it finishes, or `[setup] done` in config.toml, which
    exists so the wizard can be switched off by hand without hunting for a
    dotfile.
    """
    marker = MARKER if marker is None else marker
    return not cfg.setup.done and not marker.exists()


def mark_done(marker: Path | None = None) -> bool:
    """Write the marker. False if it could not be written — in which case
    the wizard would come back, which is why the caller says so."""
    marker = MARKER if marker is None else marker
    try:
        marker.write_text(
            "The first-run wizard has run on this copy.\n"
            "Delete this file (or run main.py --setup) to see it again.\n",
            encoding="utf-8")
        return True
    except Exception as e:
        log.info("could not write the setup marker: %r", e)
        return False


def run(cfg, path: Path = CONFIG_PATH,
        marker: Path | None = None) -> bool:
    """Show the wizard. True if it ran to the end and saved.

    Never raises. This runs before anything else does, and a wizard that
    can stop the app from starting is worse than no wizard at all.
    """
    try:
        return Wizard(cfg, path, marker).run()
    except Exception as e:
        log.info("the setup wizard could not run: %r", e, exc_info=True)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(config_mod.load(CONFIG_PATH))
