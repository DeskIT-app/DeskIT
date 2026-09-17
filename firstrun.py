"""The first-run wizard: seven pages, one window, and a Back that goes back.

Runs ONCE, on a copy nobody has set up (`setup.done` in state.json, D2;
`main.py --setup` runs it again on demand). DISTRIBUTION_PLAN.md 9.2,
and `docs/distplan/research-onboarding.md` for what the comparable apps
do first and why this order is not theirs.

WHAT IT IS FOR, AND WHY IT IS THIS AND NOT A README PARAGRAPH.

Setting this app up by hand means running `main.py --list-devices`,
reading a table of PortAudio names, and putting an INDEX into a config
file. That is a reasonable thing to ask of the person who wrote it and
an impossible one to ask of anybody else, and it is not the hard part
anyway. The hard part is that when it goes wrong it goes wrong
SILENTLY: Windows' microphone privacy switch does not produce an error,
a refusal, or a dialog. It produces a stream of perfect digital
silence, the app transcribes it to nothing, and there is no way to tell
that apart from "the app is broken". A troubleshooting entry is read
after an hour of believing the program does not work.

So the wizard is built around one moment — a bar that moves when you
talk. If it moves, everything downstream is a detail. If it does not,
this says so in one sentence and opens the exact Settings page, before
the user has formed the opinion that the thing is broken.

The pages, and the ORDER is the point:

  0. Welcome — three sentences about where the voice goes, and one link
  1. Microphone — the live meter, the trap named, the fix one click away
  2. This computer — what the probe found, and the downloads this PC
     needs, asked before a byte moves: the Hebrew model (models.py),
     NVIDIA's libraries on a card that has one (packs.py), the English
     detector where there is room for it. The download keeps running
     while the wizard moves on.
  3. Say one sentence — recorded and read back through the real backend
  4. Keys — the bindings, on one screen you can leave open
  5. Optional extras — the five switches of D33, each one thing that
     leaves this PC or changes Windows: the cloud repair (its consent
     card first — privacy.py, consent_card.py), keep-awake, the weekly
     update check, the Claude Code door, the Snipping-Tool key. Drawn as
     they stand (D34: the defaults are what the owner runs) and written
     only when moved.
  6. Ready — the hotkey named, Start-with-Windows and the phone asked
     once, the desk one button away

At most four real decisions (arch-A §1 P2): the microphone (only when
more than one input exists), the downloads, the extras, and nothing
else; every page has a way through without deciding.

Built on ui.py, so it is the dashboard's window rather than a Tk
dialog: same palette, same buttons, same bidi text renderer. The chrome
(buttons, labels, the size lines) is English like the whole dashboard;
every paragraph the person READS is Hebrew and goes through the bitmap
path (chapter 9.1). Nothing here imports main.py — the wizard has to
run BEFORE the app does, and pulling in the app's imports would make
the "loading" step start before the window.
"""
from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from pathlib import Path

import config as config_mod
import paths
import steps
import ui

log = logging.getLogger("app")

APP_DIR = Path(__file__).resolve().parent
# Where "this copy has been set up" is written: `setup.done` in
# state.json (D2) — a fact about one installation, in the file that
# holds the other facts about it. The marker file is what a --config
# one-file run writes (set_values is a line editor and cannot add a
# key), and older copies that wrote it are still honoured by needed().
MARKER = paths.SETUP_MARKER

W, H = 720, 640
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

PAGES = ("welcome", "mic", "computer", "say", "keys", "extras", "done")
#: The screenshot key when the Snipping-Tool switch is on / off (screen 13).
SNIP_KEY, PLAIN_SNIP_KEY = "win+shift+s", "ctrl+f11"

#: Every sentence the wizard shows, in one place so the guide (chapter
#: 14) can quote it. `he` = a paragraph drawn through the bitmap path;
#: everything else is English chrome.
WORDS = {
    "welcome.title": "ברוכים הבאים לדסק-איט",
    "welcome.he": ("הקול שלך נשאר במחשב הזה.",
                   "המילים שאמרת נשמרות בתיקייה אחת שאפשר למחוק.",
                   "שום דבר לא נשלח לשום מקום עד שתפעיל את זה בעצמך."),
    "welcome.defaults.he": "ברירות המחדל טובות; כל דבר אפשר לשנות אחר כך בהגדרות.",
    "welcome.link": "How to check this yourself",
    "welcome.privacy": "Privacy policy",
    "mic.title": "איזה מיקרופון?",
    "mic.he": ("דבר עכשיו. הפס למטה צריך לזוז. אם הוא לא זז — "
               "המיקרופון לא מגיע לאפליקציה, וזאת כמעט תמיד הגדרה "
               "של ווינדוס ולא תקלה."),
    "mic.none": "No microphone was found.",
    "mic.talk": "Talking? The bar should move",
    "mic.heard": "Heard. You can go on",
    "mic.cannot": "Cannot open the microphone: {error}",
    "mic.quiet.he": ("הפס לא זז. ברוב המקרים ווינדוס חוסם מיקרופון "
                     "לאפליקציות שולחן עבודה."),
    "mic.blocked.he": ("ווינדוס חוסם את המיקרופון לאפליקציות שולחן עבודה "
                       "(הגדרות > פרטיות > מיקרופון). פתח את ההגדרה, "
                       "הפעל את המתג, וחזור לכאן."),
    "mic.open": "Open the Windows setting",
    "computer.title": "המחשב הזה",
    "computer.he": ("מה שחסר יורד פעם אחת. ההורדה ממשיכה ברקע כשאתה "
                    "ממשיך הלאה, ואפשר להשלים אותה גם אחר כך מדף הבית."),
    "computer.ready.he": "כל מה שהמחשב הזה צריך כבר נמצא בדיסק.",
    "computer.portable.he": ("עותק נייד: המודלים מגיעים מהמטמון של "
                             "Hugging Face, כמו תמיד."),
    "computer.cpu.he": ("בלי כרטיס אנבידיה דסק-איט עובד, רק לאט יותר. אחר כך "
                        "אפשר להוסיף מפתח חינמי של Groq לתמלול מהיר בענן "
                        "(הגדרות > פרטיות)."),
    "computer.pack": "Use the NVIDIA card",
    "computer.pack.help": "{size} of NVIDIA's CUDA libraries from PyPI · NVIDIA licence",
    "computer.detector": "Detect English automatically",
    "computer.detector.help": "{size} more, uses {size} of video memory",
    "computer.queue": "{n} of {total} · {name} · ",
    "say.title": "תגיד משפט אחד",
    "say.he": ("לחץ, דבר שלוש שניות, וקרא מה שיצא. טעינת המודל "
               "בפעם הראשונה לוקחת כמה שניות — פעם אחת, לא בכל הכתבה."),
    "say.waiting.he": "המודל עוד יורד — הפס למעלה. אפשר לדלג ולנסות מהבית.",
    "say.button": "Record 3 seconds",
    "say.recording": "Recording…",
    "say.loading": "Loading the model and transcribing…",
    "say.nothing": "Nothing was captured",
    "say.quiet": "Silence. Go back and check the bar.",
    "say.heard": "This is what it heard — took {seconds:.1f} s",
    "say.cpu.he": "זאת המהירות שאפשר לצפות לה במחשב הזה.",
    "keys.title": "המקשים",
    "keys.he": "אלה המקשים. אפשר לשנות אותם אחר כך תחת Keys בלוח המחוונים.",
    "keys.hold": "Hold and talk",
    "keys.latch": "Latch — talk without holding",
    "keys.punctuate": "Punctuate what was just pasted",
    "keys.screen": "Ask about the screen",
    "extras.title": "תוספות",
    "extras.he": ("כל שורה כאן היא דבר אחד שיוצא מהמחשב או משנה משהו "
                  "בווינדוס. שום דבר לא יוצא לענן עד שתפעיל; הכול ניתן "
                  "לשינוי אחר כך בהגדרות."),
    "extras.cloud": "Fix misheard words with a free cloud model (text only)",
    "extras.cloud.help": "Needs your own free Groq key; the text of what you said leaves this PC.",
    "extras.cloud.key": "Consent recorded — add your free Groq key under Settings > Privacy to switch it on.",
    "extras.awake": "Keep this PC awake while DeskIT runs",
    "extras.awake.help": "Stops Windows from sleeping while it runs; Settings > The app turns it off.",
    "extras.updates": "Check for updates weekly",
    "extras.updates.help": "One request to github.com, no identifier sent.",
    "extras.claude": "Connect Claude Code",
    "extras.claude.help": "Two hook lines in ~/.claude/settings.json: when Claude Code finishes or asks, DeskIT shows a card and plays a cue.",
    "extras.snip": "Take over Win+Shift+S for DeskIT's screenshot key",
    "extras.snip.help": "Windows' own Snipping Tool stops answering that shortcut while DeskIT runs; off, the key is Ctrl+F11.",
    "done.autostart": "Start with Windows",
    "done.autostart.help": "A Run entry for your user; Settings > The app turns it off.",
    "done.phone": "Dictate from your phone",
    "done.phone.help": "This PC listens for the DeskIT keyboard on your Tailscale address (Settings > Phone shows how).",
    "done.title": "דסק-איט מוכן",
    "done.he": "החזק את המקש ודבר. הטקסט נדבק במקום שבו הסמן עומד, בכל חלון.",
    "done.deferred.he": ("דסק-איט מותקן. את המודל העברי אפשר להוריד מדף "
                         "הבית כשתרצה."),
    "done.hold": "Hold",
    "done.desk": "Open the desk",
    "next": "Next", "back": "Back", "skip": "Skip", "finish": "Finish",
    "saved.error": "Could not save: {error}",
}

GUIDE_PRIVACY_CHECK = f"{paths.PAGES_URL}/he/04-privacy"      # guide chapter 4
PRIVACY_URL = f"{paths.PAGES_URL}/privacy"


def clean_name(name: str) -> str:
    """A device name a person can read.

    Windows hands PortAudio the raw registry value for some devices, and
    for Bluetooth that is an UNRESOLVED INDIRECT STRING with a driver
    path, a resource id and an embedded CRLF in it:

        Headset (@System32\\drivers\\bthhfenum.sys,#2;%1 Hands-Free%0
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
    """How a microphone is named in the settings: its RAW name, a comma
    and its host API — the exact string sounddevice builds and compares
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

    The KEY is what gets written (see device_key). The index is kept for
    the row's small print — the same microphone appears three times on a
    normal Windows box, they are not equally good, and the number is how
    a person tells two identical names apart.
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
    WASAPI first, and on this machine the device the settings already
    name is an MME one that landed ninth — so the row the owner was
    actually using was off the bottom of a list of their own microphones.
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


MIC_CONSENT_KEY = (r"Software\Microsoft\Windows\CurrentVersion"
                   r"\CapabilityAccessManager\ConsentStore\microphone")


def microphone_allowed() -> bool | None:
    """Windows' microphone privacy switch, read before the meter is even
    drawn (the way Handy asks Windows, research-onboarding copy 2).

    Two values: the switch for everything, and the one for desktop apps
    under `NonPackaged` — "Deny" on either is the trap the meter would
    otherwise take QUIET_S seconds to suspect. None when the key cannot
    be read; the meter stays the proof either way.
    """
    try:
        import winreg
    except ImportError:
        return None
    try:
        for sub in ("", r"\NonPackaged"):
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, MIC_CONSENT_KEY + sub) as key:
                value, _kind = winreg.QueryValueEx(key, "Value")
                if str(value).strip().lower() == "deny":
                    return False
        return True
    except OSError:
        return None


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
    """(text, problem). Loads the real backend — seconds cold, and said so.

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


# ------------------------------------------------------- this computer

def card_tier(facts: dict | None) -> str:
    """The tier the CARD earns once NVIDIA's libraries are there — what
    page 2 speaks of, since on a first start the pack is not installed
    yet and hardware.tier_for says cpu until it is. "" without a usable
    card."""
    facts = facts or {}
    if int(facts.get("cuda_devices") or 0) < 1:
        return ""
    if not facts.get("driver_ok", True):
        return ""
    import hardware
    vram = int(facts.get("vram_mb") or 0)
    if vram and vram < hardware.GPU_SMALL_MB:
        return ""
    if vram and vram < hardware.GPU_MB:
        return "gpu-small"
    return "gpu"


def hardware_line(facts: dict | None) -> str:
    """The top line of page 2, chapter 9.2's three sentences — for the
    card this PC has, not for the tier it runs at before the pack."""
    facts = facts or {}
    if not facts.get("tier"):
        return "This computer has not been probed yet"
    vram = int(facts.get("vram_mb") or 0)
    card = card_tier(facts)
    if card == "gpu":
        return f"NVIDIA card, {vram / 1024:.0f} GB — fast transcription"
    if card == "gpu-small":
        return f"NVIDIA card, {vram / 1024:.0f} GB — fast, smaller mode"
    if int(facts.get("cuda_devices") or 0) and not facts.get("driver_ok"):
        return ("NVIDIA card with a driver too old for CUDA 12.3 — "
                "transcription on the processor, about as long as you spoke")
    return "No NVIDIA card found — transcription will take about as long as you spoke"


def cfg_mod_english(cfg) -> str:
    """local.english_model as the defaults and settings.toml say — the
    machine layer may hold "" for the cpu tier (hardware.DERIVED)."""
    try:
        chosen = config_mod.read_settings(paths.SETTINGS_FILE)
        if "local.english_model" in chosen:
            return str(chosen["local.english_model"] or "")
        return str(config_mod.defaults_flat().get("local.english_model") or "")
    except Exception:                                      # noqa: BLE001
        return str(getattr(cfg.local, "english_model", "") or "")


def downloads_for(cfg, facts: dict | None) -> dict:
    """What page 2 offers on THIS copy: the runs it may queue, in order,
    and the two switches. Nothing on a portable copy (D4: the global
    cache, as always). Everything that is already on disk is left out,
    so `--setup` on a finished install shows an empty page."""
    out = {"portable": paths.PORTABLE, "model": None, "pack": None,
           "detector": None, "tier": (facts or {}).get("tier", "")}
    if paths.PORTABLE:
        return out
    import models
    import packs
    repo = cfg.local.model
    if cfg.backend == "local" and models.state(repo) != "ready":
        out["model"] = models.entry(repo)
    if packs.wanted(cfg, facts):
        out["pack"] = packs.pack("gpu")
    # The detector goes with the CARD, not with the tier of the moment:
    # on a first start the pack is not there yet, the tier says cpu, and
    # the cpu tier's machine layer blanks local.english_model — so the
    # name is read from the layers UNDER it (the file's default, the
    # person's settings), never from the layer the tier wrote.
    english = str(cfg_mod_english(cfg))
    if (card_tier(facts) == "gpu" and english and cfg.backend == "local"
            and models.state(english) != "ready"):
        out["detector"] = models.entry(english)
    return out


class Result:
    """What `run()` answers: truthy when the wizard ran to the end and
    wrote `setup.done`; the two side facts main.py acts on."""

    def __init__(self, saved: bool = False, open_desk: bool = False,
                 installed_pack: bool = False):
        self.saved = saved
        self.open_desk = open_desk
        self.installed_pack = installed_pack

    def __bool__(self) -> bool:
        return self.saved


class Wizard:
    """Seven pages in one window, and a Back that actually goes back.

    Not a chain of modal dialogs: every page here can fail in a way whose
    fix is on the PREVIOUS page ("no, it was the other microphone"), and
    a dialog chain you cannot walk back turns that into starting over.

    `facts` are the hardware probe's (hardware.recorded() when None);
    `offers` replaces downloads_for() in a test, `stepper(kind, entry)`
    the steps.Step a download is made from.
    """

    def __init__(self, cfg, path: Path | None = None,
                 marker: Path | None = None, *, facts: dict | None = None,
                 offers: dict | None = None, stepper=None):
        self.cfg = cfg
        self.path = path          # one-file mode (--config); None = layers
        self.marker = MARKER if marker is None else marker
        self.device = cfg.audio.device or default_device()
        self.listener = Listener(cfg.audio.sample_rate)
        self.result = Result()
        self.page = 0
        self._rows: dict[str, tk.Widget] = {}
        self._quiet_since = time.monotonic()
        self._warned = False
        self._busy = False
        self._sample = ""
        self._seconds = 0.0
        self._closing = False
        self.meter = None
        self.pane: steps.StepPane | None = None
        self._stepper = stepper or self._step_for
        if facts is None:
            try:
                import hardware
                facts = hardware.recorded()
            except Exception:                              # noqa: BLE001
                facts = {}
        self.facts = facts
        self.offers = offers if offers is not None else downloads_for(cfg, facts)
        # The downloads: built once, pressed on page 2, pumped on every
        # page after it. `queue` is the order; `active` the index.
        self.runs: dict[str, steps.StepRun] = {}
        self.queue: list[str] = []
        self.active: int = -1
        self.want = {"pack": self.offers.get("pack") is not None,
                     "detector": self.offers.get("detector") is not None}
        # The extras page shows each switch as it STANDS (D34: the
        # defaults are what the owner runs — keep-awake ships on, the
        # update check ships on, the phone and autostart off) and writes
        # only what the person changed.
        self.extras = {
            "cloud": False, "updates": True, "claude": False,
            "awake": bool(getattr(getattr(cfg, "awake", None), "hold", True)),
            "snip": str(getattr(cfg, "capture_hotkey", "")).strip().lower() == SNIP_KEY,
            "autostart": bool(getattr(cfg.setup, "autostart", False)),
            "phone": bool(getattr(getattr(cfg, "server", None), "enabled", False)),
        }
        try:
            import privacy
            self.extras["updates"] = bool(privacy.allowed("update_check"))
            self.extras["cloud"] = bool(privacy.allowed("cloud_text"))
        except Exception:                                  # noqa: BLE001
            pass
        try:
            import notify_hook
            self.extras["claude"] = notify_hook.hook_installed()
        except Exception:                                  # noqa: BLE001
            pass
        self._extras_shown = dict(self.extras)

        # A PhotoImage belongs to the interpreter that made it: the step
        # windows and the dashboard may have had a Tk of their own in
        # this process, so the cache is emptied on both sides.
        ui.forget_images()
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
        self.next = ui.Button(self.foot, WORDS["next"], self._next, bg=ui.BG,
                              primary=True, w=150)
        self.next.pack(side="right")
        self.back = ui.Button(self.foot, WORDS["back"], self._back, bg=ui.BG,
                              quiet=True, w=96)
        self.back.pack(side="right", padx=(0, 10))
        self.skip = ui.Button(self.foot, WORDS["skip"], self._skip, bg=ui.BG,
                              quiet=True, w=96)
        self.note = tk.Label(self.foot, text="", bg=ui.BG, fg=ui.FAINT,
                             font=(ui.UI, 9), anchor="w")
        self.note.pack(side="left", fill="x", expand=True)

        self._show_page()
        self.root.after(60, self._tick)

    # ---------------------------------------------------------------- frame
    def _centre(self) -> None:
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 3)}")

    def _clear(self) -> None:
        self.pane = None
        self.meter = None
        for child in self.body.winfo_children():
            child.destroy()
        self._rows = {}

    def _para(self, text: str, *, pt: int, colour: str, lines: int = 4,
              pady=(0, 0), parent=None) -> tk.Label:
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
        parent = parent or self.body
        photo, _h, _n = ui.draw_text(text, pt=pt, width=W - PAD * 2,
                                     max_lines=lines, colour=colour,
                                     bg=ui.BG, rtl=True)
        label = tk.Label(parent, image=photo, bg=ui.BG, anchor="e")
        label.photo = photo
        label.pack(fill="x", pady=pady)
        return label

    def _title(self, text: str, sub: str, lines: int = 4) -> None:
        self._para(text, pt=17, colour=ui.FG, lines=1)
        self._para(sub, pt=10, colour=ui.DIM, lines=lines, pady=(6, 16))

    def _line(self, text: str, *, colour: str | None = None, pady=(0, 0),
              parent=None, size: int = 9) -> tk.Label:
        """One English line, left-aligned like the dashboard's chrome."""
        label = tk.Label(parent or self.body, text=text, bg=ui.BG,
                         fg=colour or ui.FAINT, font=(ui.UI, size), anchor="w",
                         justify="left", wraplength=W - PAD * 2)
        label.pack(fill="x", pady=pady)
        return label

    def _link(self, text: str, url: str, parent=None) -> tk.Label:
        label = tk.Label(parent or self.body, text=text, bg=ui.BG,
                         fg=ui.ACCENT_TEXT, font=(ui.UI, 9, "underline"),
                         cursor="hand2", anchor="w")
        label.bind("<Button-1>", lambda _e, u=url: self._open(u))
        return label

    @staticmethod
    def _open(url: str) -> None:
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:                                  # noqa: BLE001
            log.info("could not open %s", url)

    def _switch_row(self, label: str, help_: str, value: bool, command,
                    parent=None) -> ui.Switch:
        """A switch, its English label and one help line — the Settings
        page's row shape, on the wizard's ground."""
        parent = parent or self.body
        row = tk.Frame(parent, bg=ui.BG)
        row.pack(fill="x", pady=(0, 8))
        switch = ui.Switch(row, value, command, bg=ui.BG)
        switch.pack(side="left", padx=(0, 12), pady=(2, 0))
        words = tk.Frame(row, bg=ui.BG)
        words.pack(side="left", fill="x", expand=True)
        tk.Label(words, text=label, bg=ui.BG, fg=ui.FG, font=(ui.UI, 10),
                 anchor="w").pack(fill="x")
        tk.Label(words, text=help_, bg=ui.BG, fg=ui.FAINT, font=(ui.UI, 8),
                 anchor="w", justify="left", wraplength=W - PAD * 2 - 80
                 ).pack(fill="x")
        return switch

    # ---------------------------------------------------------------- pages
    @property
    def name(self) -> str:
        return PAGES[self.page]

    def _show_page(self) -> None:
        self._clear()
        getattr(self, f"_page_{self.name}")()
        self.back.enable(self.page > 0)
        self.next.configure_text(WORDS["finish"] if self.name == "done"
                                 else WORDS["next"])
        if self.name == "say":
            self.skip.pack(side="right", padx=(0, 10))
        else:
            self.skip.pack_forget()
        self.note.configure(text="", fg=ui.FAINT)

    def _page_welcome(self) -> None:
        self._para(WORDS["welcome.title"], pt=17, colour=ui.FG, lines=1,
                   pady=(0, 14))
        for sentence in WORDS["welcome.he"]:
            self._para(sentence, pt=12, colour=ui.FG, lines=2, pady=(0, 8))
        self._para(WORDS["welcome.defaults.he"], pt=10, colour=ui.DIM,
                   lines=2, pady=(10, 18))
        self._link(WORDS["welcome.link"], GUIDE_PRIVACY_CHECK).pack(anchor="w")
        self._link(WORDS["welcome.privacy"], PRIVACY_URL).pack(anchor="w",
                                                                pady=(4, 0))

    def _page_mic(self) -> None:
        self._title(WORDS["mic.title"], WORDS["mic.he"])
        listing = _devices()
        if not listing:
            self._line(WORDS["mic.none"], colour=ui.RED, size=11)
            return
        # Every device, not the first few: a silent cap here is somebody
        # whose microphone is ninth concluding it is not supported.
        holder = ui.Scroller(self.body, w=W - PAD * 2 - 10, h=230, bg=ui.BG)
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
        if microphone_allowed() is False and not self._warned:
            self._warn_silent(WORDS["mic.blocked.he"])

    def _device_row(self, parent, key: str, name: str, api: str,
                    index: int) -> None:
        # `key` is the identity (what the settings store, see device_key);
        # `index` is only ever shown, because two rows can carry the same
        # name and the number is how a person tells them apart.
        chosen = key == self.device
        # Ten narrower than the page, because `ui.Scroller` keeps
        # ui.GUTTER px of its canvas clear on the right for the way home,
        # and the two lines are drawn at `width - 16`.
        width = W - PAD * 2 - 10 - ui.GUTTER
        row = tk.Canvas(parent, width=width, height=40, bd=0,
                        highlightthickness=0, cursor="hand2",
                        bg=ui.ACCENT_SOFT if chosen else ui.CARD)
        row.pack(fill="x", pady=3)
        row.create_text(width - 16, 14, text=name or f"Device {index}",
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
            self.meter_note.configure(text=WORDS["mic.talk"], fg=ui.DIM)
        else:
            self.meter_note.configure(
                text=WORDS["mic.cannot"].format(error=self.listener.error),
                fg=ui.RED)

    def _page_computer(self) -> None:
        self._title(WORDS["computer.title"], WORDS["computer.he"], lines=2)
        self._line(hardware_line(self.facts), colour=ui.FG, size=10,
                   pady=(0, 10))
        offers = self.offers
        if offers.get("portable"):
            self._para(WORDS["computer.portable.he"], pt=10, colour=ui.DIM,
                       lines=2)
            return
        if not any(offers.get(k) for k in ("model", "pack", "detector")):
            self._para(WORDS["computer.ready.he"], pt=10, colour=ui.GREEN,
                       lines=2)
            return
        self._ensure_runs()
        current = self._current_run()
        if current is not None:
            self.pane = steps.StepPane(
                self.body, current, width=W - PAD * 2, secondary=None,
                closing=None, on_end=self._run_ended, compact=False,
                prefix=self._prefix(), on_go=self._download, title_pt=12,
                body_lines=3)
            self.pane.pack(fill="x", pady=(0, 8))
        started = self.active >= 0
        if not card_tier(self.facts):
            self._para(WORDS["computer.cpu.he"], pt=10, colour=ui.DIM, lines=2,
                       pady=(0, 8))
        if offers.get("pack") is not None:
            p = offers["pack"]
            switch = self._switch_row(
                WORDS["computer.pack"],
                WORDS["computer.pack.help"].format(size=steps.human(p.bytes)),
                self.want["pack"], lambda _v=None: self._flip("pack"))
            if started:
                switch.configure(state="disabled")
        if offers.get("detector") is not None:
            e = offers["detector"]
            switch = self._switch_row(
                WORDS["computer.detector"],
                WORDS["computer.detector.help"].format(size=steps.human(e.bytes)),
                self.want["detector"], lambda _v=None: self._flip("detector"))
            if started:
                switch.configure(state="disabled")

    def _flip(self, which: str) -> None:
        if self.active >= 0:
            return                       # the queue is running; too late
        self.want[which] = not self.want[which]

    def _page_say(self) -> None:
        self._title(WORDS["say.title"], WORDS["say.he"], lines=2)
        current = self._current_run()
        if current is not None and not self._all_landed():
            self.pane = steps.StepPane(
                self.body, current, width=W - PAD * 2, secondary=None,
                closing=None, on_end=self._run_ended, compact=True,
                prefix=self._prefix(), on_go=self._download)
            self.pane.pack(fill="x", pady=(0, 12))
        if self._model_missing():
            self._para(WORDS["say.waiting.he"], pt=10, colour=ui.AMBER,
                       lines=2, pady=(0, 12))
        self.say = ui.Button(self.body, WORDS["say.button"], self._record,
                             bg=ui.BG, primary=True, w=200, h=44)
        self.say.pack(anchor="e")
        self.result_label = tk.Label(
            self.body, text=self._sample, bg=ui.CARD, fg=ui.FG,
            font=(ui.TEXT, 13), anchor="e", justify="right",
            wraplength=W - PAD * 2 - 40, padx=18, pady=14)
        self.result_label.pack(fill="x", pady=(14, 0))
        self.status = tk.Label(self.body, text="", bg=ui.BG, fg=ui.DIM,
                               font=(ui.UI, 9), anchor="e")
        self.status.pack(fill="x", pady=(10, 0))
        self._say_ready()

    def _say_ready(self) -> None:
        """The record button waits for the model: a queue still running
        means the backend would load a half-written folder or the CPU."""
        if getattr(self, "say", None) is None:
            return
        waiting = self._model_missing()
        self.say.enable(not waiting and not self._busy)
        if waiting and not self._busy:
            self.status.configure(text="", fg=ui.DIM)

    def _model_missing(self) -> bool:
        run = self.runs.get("model")
        if run is None:
            return False
        return run.state != "done" and not self.offers.get("portable")

    def _page_keys(self) -> None:
        self._title(WORDS["keys.title"], WORDS["keys.he"], lines=2)
        keys = [(WORDS["keys.hold"], self.cfg.hotkey),
                (WORDS["keys.latch"], self.cfg.latch_hotkey),
                (WORDS["keys.punctuate"], self.cfg.punctuate_hotkey),
                (WORDS["keys.screen"], getattr(
                    getattr(self.cfg, "visual_qa", None), "hotkey", ""))]
        keys = [(label, key) for label, key in keys if key]
        width = W - PAD * 2
        card = tk.Canvas(self.body, width=width, height=42 * len(keys) + 14,
                         bg=ui.CARD, bd=0, highlightthickness=0)
        card.pack(fill="x")
        y = 21
        for label, key in keys:
            card.create_text(18, y, text=label, anchor="w",
                             fill=ui.FG, font=(ui.UI, 11))
            ui.pill(card, width - 18, y - 15, _pretty(key), ui.CARD, size=9,
                    fill=ui.ACCENT_SOFT, border=ui.ACCENT_EDGE,
                    colour=ui.ACCENT_TEXT)
            y += 42

    def _page_extras(self) -> None:
        self._title(WORDS["extras.title"], WORDS["extras.he"], lines=3)
        self.switches: dict[str, ui.Switch] = {}
        rows = [("cloud", WORDS["extras.cloud"], WORDS["extras.cloud.help"]),
                ("awake", WORDS["extras.awake"], WORDS["extras.awake.help"]),
                ("updates", WORDS["extras.updates"], WORDS["extras.updates.help"]),
                ("claude", WORDS["extras.claude"], WORDS["extras.claude.help"]),
                ("snip", WORDS["extras.snip"], WORDS["extras.snip.help"])]
        for key, label, help_ in rows:
            self.switches[key] = self._switch_row(
                label, help_, self.extras[key],
                lambda _v=None, k=key: self._extra_flipped(k))

    def _extra_flipped(self, key: str) -> None:
        on = self.switches[key].get()
        if key == "cloud":
            # The gate opens only through its card (privacy.py): the
            # switch shows the answer, never the wish. Off is immediate
            # (privacy.withdraw), like the Privacy tab's button.
            if on:
                self.switches[key].set(False)
                self.extras["cloud"] = False
                self._ask_consent("cloud_text", self._cloud_answered)
            else:
                self.extras["cloud"] = False
                try:
                    import privacy
                    privacy.withdraw("cloud_text")
                except Exception:                          # noqa: BLE001
                    log.info("the cloud gate was not withdrawn", exc_info=True)
            return
        self.extras[key] = on

    def _cloud_answered(self, granted: bool) -> None:
        self.extras["cloud"] = granted
        if "cloud" in getattr(self, "switches", {}):
            try:
                self.switches["cloud"].set(granted)
            except Exception:                              # noqa: BLE001
                pass
        if granted:
            self.note.configure(text=WORDS["extras.cloud.key"], fg=ui.FAINT)

    def _ask_consent(self, kind: str, answer) -> None:
        """The consent card's own picture (consent_card.flat) in a small
        window over the wizard, its two buttons hit-tested the way the
        painted card does it — one Tk, no second thread, the same words
        and the same text_version privacy.grant records."""
        try:
            import consent_card as cc
            from PIL import ImageTk
        except Exception as e:                             # noqa: BLE001
            log.info("no consent card for the wizard: %r", e)
            answer(False)
            return
        card = cc.card_for(kind)
        cache: dict = {}
        scale = 1.0
        width, height = cc.measure(card, scale, cache)
        if height > H - 40:
            scale = max(0.7, (H - 40) / height)
            width, height = cc.measure(card, scale, cache)
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.configure(bg=ui.BG)
        top.transient(self.root)
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + (W - width) // 2
        y = self.root.winfo_rooty() + max(0, (H - height) // 2)
        top.geometry(f"{width}x{height}+{x}+{y}")
        photo = ImageTk.PhotoImage(cc.flat(card, scale, None, cache), master=top)
        face = tk.Label(top, image=photo, bd=0, bg=ui.BG, cursor="hand2")
        face.photo = photo
        face.pack()
        answered = {"done": False}

        def finish(granted: bool) -> None:
            if answered["done"]:
                return
            answered["done"] = True
            try:
                top.grab_release()
                top.destroy()
            except Exception:                              # noqa: BLE001
                pass
            if granted:
                try:
                    import privacy
                    privacy.grant(kind, card["text_version"])
                except Exception as e:                     # noqa: BLE001
                    log.warning("the wizard could not record the consent "
                                "for %s: %s", kind, e)
                    granted = False
            else:
                try:
                    import privacy
                    privacy.not_now(kind)
                except Exception:                          # noqa: BLE001
                    pass
            answer(granted)

        def click(event) -> None:
            _where, hit = cc.hit_test(card, scale, event.x + cc.SHADOW,
                                      event.y + cc.SHADOW, cache)
            if hit == cc.TURN_ON:
                finish(True)
            elif hit == cc.NOT_NOW:
                finish(False)

        face.bind("<Button-1>", click)
        top.bind("<Escape>", lambda _e: finish(False))
        top.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        try:
            top.grab_set()
            top.focus_set()
        except Exception:                                  # noqa: BLE001
            pass
        self.consent_window = top

    def _page_done(self) -> None:
        deferred = self._model_missing()
        self._title(WORDS["done.title"],
                    WORDS["done.deferred.he"] if deferred else WORDS["done.he"],
                    lines=3)
        width = W - PAD * 2
        card = tk.Canvas(self.body, width=width, height=56, bg=ui.CARD, bd=0,
                         highlightthickness=0)
        card.pack(fill="x")
        card.create_text(18, 28, text=WORDS["done.hold"], anchor="w",
                         fill=ui.FG, font=(ui.UI, 11))
        ui.pill(card, width - 18, 13, _pretty(self.cfg.hotkey), ui.CARD,
                size=10, fill=ui.ACCENT_SOFT, border=ui.ACCENT_EDGE,
                colour=ui.ACCENT_TEXT)
        self.switches = {}
        holder = tk.Frame(self.body, bg=ui.BG)
        holder.pack(fill="x", pady=(22, 0))
        for key, label, help_ in (
                ("autostart", WORDS["done.autostart"], WORDS["done.autostart.help"]),
                ("phone", WORDS["done.phone"], WORDS["done.phone.help"])):
            self.switches[key] = self._switch_row(
                label, help_, self.extras[key],
                lambda _v=None, k=key: self._extra_flipped(k), parent=holder)
        self.desk = ui.Button(self.body, WORDS["done.desk"], self._open_desk,
                              bg=ui.BG, w=160)
        self.desk.pack(anchor="e", pady=(14, 0))

    def _open_desk(self) -> None:
        self.result.open_desk = True
        self._save_extras()
        self._finish()

    # -------------------------------------------------------- the downloads
    def _step_for(self, kind: str, thing) -> steps.Step:
        import models
        import packs
        if kind == "pack":
            return packs.step(thing)
        if kind == "detector":
            return models.step(thing, words=models.DETECTOR_TEXT)
        return models.step(thing)

    def _ensure_runs(self) -> None:
        for kind in ("model", "pack", "detector"):
            thing = self.offers.get(kind)
            if thing is not None and kind not in self.runs:
                self.runs[kind] = steps.StepRun(self._stepper(kind, thing))

    def _download(self) -> None:
        """[Download] on page 2: the queue is decided by the switches
        as they stand now, then the first run starts."""
        if self.active >= 0:
            run = self._current_run()
            if run is not None and run.state in ("paused", "offline", "failed"):
                run.start()
                if self.pane is not None:
                    self.pane.refresh()
            return
        self.queue = [k for k in ("model", "pack", "detector")
                      if k in self.runs and (k == "model" or self.want.get(k))]
        if not self.queue:
            return
        self.active = 0
        self.runs[self.queue[0]].start()
        if self.pane is not None:
            self.pane.attach(self.runs[self.queue[0]])
            self.pane.prefix = self._prefix()
            self.pane.refresh()
        if self.name == "computer":
            self._show_page()             # the switches lock

    def _current_run(self) -> steps.StepRun | None:
        if self.active < 0:
            return self.runs.get("model") or next(iter(self.runs.values()), None)
        if self.active < len(self.queue):
            return self.runs[self.queue[self.active]]
        return self.runs[self.queue[-1]]

    def _prefix(self) -> str:
        if self.active < 0 or len(self.queue) < 2:
            return ""
        i = min(self.active, len(self.queue) - 1)
        name = self.runs[self.queue[i]].step.name or self.queue[i]
        return WORDS["computer.queue"].format(n=i + 1, total=len(self.queue), name=name)

    def _all_landed(self) -> bool:
        return self.active >= len(self.queue) - 1 and \
            (self._current_run() is None or self._current_run().ended)

    def _run_ended(self, word: str) -> None:
        """One run's end word, from the pane. `done` starts the next of
        the queue; anything else leaves the queue where it stopped and
        the [Download] button re-armed on the same run."""
        if word == "done":
            kind = self.queue[self.active] if 0 <= self.active < len(self.queue) else ""
            if kind == "pack":
                self._after_pack()
            if self.active + 1 < len(self.queue):
                self.active += 1
                nxt = self.runs[self.queue[self.active]]
                nxt.start()
                if self.pane is not None:
                    self.pane.prefix = self._prefix()
                    self.pane.attach(nxt)
            self._say_ready()

    def _after_pack(self) -> None:
        """NVIDIA's libraries landed: the probe runs again so the tier and
        its defaults are the card's before any model loads (6.5)."""
        self.result.installed_pack = True
        try:
            import hardware
            self.facts = hardware.run_at_start()
            if self.path is None:
                self.cfg = config_mod.load_layered()
        except Exception:                                  # noqa: BLE001
            log.warning("the hardware probe failed after the pack", exc_info=True)

    def _pump_runs(self) -> None:
        """Every tick, on every page: the threads' news into the runs,
        the pane redrawn if one is up. A run that ends while its pane is
        not on screen is picked up here too."""
        for run in self.runs.values():
            if run.state == "running":
                landed = run.pump()
                if landed and self.pane is None:
                    self._run_ended(landed[0])
        if self.pane is not None:
            self.pane.refresh()

    # ------------------------------------------------------------- the loop
    def _tick(self) -> None:
        """The meter, the downloads, and the one sentence the microphone
        page exists for."""
        if self._closing:
            return
        try:
            if self.name == "mic" and self.meter is not None:
                level = self.listener.level()
                self.meter.show(level)
                if level >= SPEECH:
                    self._quiet_since = time.monotonic()
                    if not self._warned:
                        self.meter_note.configure(text=WORDS["mic.heard"],
                                                  fg=ui.GREEN)
                elif (not self._warned
                        and self.meter.peak < SPEECH
                        and time.monotonic() - self._quiet_since > QUIET_S):
                    self._warn_silent(WORDS["mic.quiet.he"])
            self._pump_runs()
            if self.name == "say":
                self._say_ready()
        except Exception:                                  # noqa: BLE001
            log.debug("the wizard's tick tripped", exc_info=True)
        self.root.after(60, self._tick)

    def _warn_silent(self, text: str) -> None:
        """The trap, named, with the fix one click away.

        Silence is not an error anywhere in Windows' audio API — the
        stream opens, the callbacks arrive, every sample is zero — so
        nothing downstream can report it. Here is the only place it can be
        said before someone decides the app does not work.
        """
        self._warned = True
        self.meter_note.configure(text="", fg=ui.AMBER)
        self._para(text, pt=10, colour=ui.AMBER, lines=3, pady=(10, 0))
        ui.Button(self.body, WORDS["mic.open"], open_microphone_settings,
                  bg=ui.BG, w=230).pack(anchor="e", pady=(10, 0))

    def _record(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.say.enable(False)
        self.status.configure(text=WORDS["say.recording"], fg=ui.DIM)
        self.result_label.configure(text="")

        def work():
            wav, _seconds = self.listener.record(TEST_S)
            if not wav:
                return self._on_result("", WORDS["say.nothing"], 0.0)
            self._later(lambda: self.status.configure(
                text=WORDS["say.loading"], fg=ui.DIM))
            started = time.monotonic()
            text, problem = transcribe(self.cfg, wav)
            self._on_result(text, problem, time.monotonic() - started)

        threading.Thread(target=work, daemon=True, name="setup-test").start()

    def _later(self, fn) -> None:
        if not self._closing:
            try:
                self.root.after(0, fn)
            except Exception:
                pass

    def _on_result(self, text: str, problem: str, seconds: float) -> None:
        def land():
            self._busy = False
            self.say.enable(True)
            if problem:
                self.status.configure(text=problem, fg=ui.RED)
            elif not text:
                self.status.configure(text=WORDS["say.quiet"], fg=ui.AMBER)
            else:
                self._sample = text
                self._seconds = seconds
                self.result_label.configure(text=text)
                self.status.configure(
                    text=WORDS["say.heard"].format(seconds=seconds),
                    fg=ui.GREEN)
                if not card_tier(self.facts):
                    self._para(WORDS["say.cpu.he"], pt=10, colour=ui.DIM,
                               lines=2, pady=(8, 0))
                self._save_seconds(seconds)
        self._later(land)

    def _save_seconds(self, seconds: float) -> None:
        """The measured decode into the machine layer: the CPU copy on
        Home and the slowness card quote it (9.2, screen 10 and 15)."""
        if self.path is not None:
            return
        try:
            config_mod.save({"hardware.last_test_seconds": round(seconds, 2)},
                            derived=True)
        except Exception:                                  # noqa: BLE001
            log.debug("the test seconds were not written", exc_info=True)

    # ----------------------------------------------------------- navigation
    def _back(self) -> None:
        if self.page == 0:
            return
        if self.name == "mic":
            self.listener.close()
        self.page -= 1
        self._show_page()

    def _skip(self) -> None:
        if self.name == "say":
            self._advance()

    def _next(self) -> None:
        if self.name == "mic":
            self._save_device()
        if self.name in ("extras", "done"):
            self._save_extras()
        if self.name == "done":
            self._finish()
            return
        self._advance()

    def _advance(self) -> None:
        if self.name == "mic":
            self.listener.close()
        self.page += 1
        if self.name == "say":
            # the sentence page records: the stream is opened again
            self.listener.listen_to(self.device)
        elif self.page > PAGES.index("say"):
            self.listener.close()
        self._show_page()

    def _save_device(self) -> None:
        """Write the chosen microphone, by name (device_key), and nothing
        else — to state.json through config.save (it is a STATE key), or
        through set_values in one-file mode."""
        if self.device == (self.cfg.audio.device or ""):
            return
        try:
            if self.path is None:
                config_mod.save({"audio.device": self.device})
            else:
                config_mod.set_values(self.path, {"audio.device": self.device})
            log.info("setup: microphone set to %s", self.device or "the "
                     "system default")
        except Exception as e:
            log.info("setup could not save the microphone: %r", e)
            self.note.configure(text=WORDS["saved.error"].format(error=e),
                                fg=ui.RED)

    def _save_extras(self) -> None:
        """The switches of pages 5 and 6, each through its own writer and
        only when the person moved it: the awake hold, the screenshot
        key and the phone listener are settings, the update check a
        privacy switch, autostart a state key plus the Run value, the
        Claude Code door two hook lines in Claude's settings.json; the
        cloud one was written by its card already."""
        if self.path is not None:
            return
        want, shown = self.extras, self._extras_shown
        updates: dict[str, object] = {}
        if want["awake"] != shown["awake"]:
            updates["awake.hold"] = want["awake"]
        if want["snip"] != shown["snip"]:
            updates["capture.capture_hotkey"] = SNIP_KEY if want["snip"] else PLAIN_SNIP_KEY
        if want["phone"] != shown["phone"]:
            updates["server.enabled"] = want["phone"]
        if want["autostart"] != shown["autostart"]:
            updates["setup.autostart"] = want["autostart"]
        if want["updates"] != shown["updates"]:
            try:
                import privacy
                if want["updates"]:
                    privacy.grant("update_check")
                else:
                    privacy.withdraw("update_check")
            except Exception as e:                         # noqa: BLE001
                log.info("the update-check switch was not written: %r", e)
        if want["claude"] != shown["claude"]:
            try:
                import launch
                import notify_hook
                if want["claude"]:
                    notify_hook.install_hook(notify_hook.DEFAULT_SETTINGS,
                                             python=launch.pythonw(),
                                             script=str(APP_DIR / "notify_hook.py"))
                    updates["notify.enabled"] = True
                else:
                    notify_hook.uninstall_hook(notify_hook.DEFAULT_SETTINGS)
            except Exception as e:                         # noqa: BLE001
                log.info("the Claude Code door was not written: %r", e)
        try:
            if updates:
                config_mod.save(updates)
            if want["autostart"] != shown["autostart"]:
                import autostart
                autostart.apply(want["autostart"])
        except Exception as e:                             # noqa: BLE001
            log.info("the extras were not all written: %r", e)
            self.note.configure(text=WORDS["saved.error"].format(error=e),
                                fg=ui.RED)
            return
        self._extras_shown = dict(want)

    def _finish(self) -> None:
        self.result.saved = (record_done() if self.path is None
                             else mark_done(self.marker))
        self._close()

    def _close(self) -> None:
        self._closing = True
        self.listener.close()
        for run in self.runs.values():
            if run.running:
                run.pause()           # the part stays; the next start resumes
        try:
            self.root.destroy()
        except Exception:
            pass
        ui.forget_images()

    def run(self) -> Result:
        self.root.mainloop()
        return self.result


def _pretty(binding: str) -> str:
    import hint
    return hint.pretty(binding)


def needed(cfg, marker: Path | None = None) -> bool:
    """Has this copy never been set up?

    Either signal is enough to say "leave them alone": `setup.done` in
    state.json (what the wizard writes, D2 — read here through the
    config layers), or the marker file a one-file run or an older copy
    wrote.
    """
    marker = MARKER if marker is None else marker
    return not cfg.setup.done and not marker.exists()


def record_done() -> bool:
    """`setup.done = true` into state.json. False if it could not be
    written — in which case the wizard would come back, which is why the
    caller says so."""
    try:
        config_mod.save({"setup.done": True})
        return True
    except Exception as e:                                 # noqa: BLE001
        log.info("could not record the wizard as done: %r", e)
        return False


def mark_done(marker: Path | None = None) -> bool:
    """The marker file, for a --config one-file run (set_values is a line
    editor and cannot add a key). False if it could not be written."""
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


def run(cfg, path: Path | None = None,
        marker: Path | None = None, **kw) -> Result:
    """Show the wizard. Truthy if it ran to the end and saved.

    Never raises. This runs before anything else does, and a wizard that
    can stop the app from starting is worse than no wizard at all.
    """
    try:
        return Wizard(cfg, path, marker, **kw).run()
    except Exception as e:
        log.info("the setup wizard could not run: %r", e, exc_info=True)
        return Result()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(config_mod.load_layered())
