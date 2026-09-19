"""The first-run wizard: eight pages, one window, and a Back that goes back.

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
  1. Account — Sign in with Google (the owner's rule of 2026-09-18: no
     account, no dictation); the one page Next cannot pass until a
     session exists. Remembered until Sign out.
  2. Microphone — one row per physical microphone, the live meter, the
     trap named once, the fix one click away
  3. This computer — what the probe found, and the downloads this PC
     needs, asked before a byte moves: the Hebrew model (models.py),
     NVIDIA's libraries on a card that has one (packs.py), the English
     detector where there is room for it. The download keeps running
     while the wizard moves on.
  4. Say one sentence — recorded and read back through the real backend,
     the decode time on its own, the model's load time said once
  5. Keys — the bindings as chips; a click rebinds one, through the same
     path Settings > Keys writes
  6. Extras — the five switches of D33, each one thing that leaves this
     PC or changes Windows: the cloud repair (its consent card first —
     privacy.py, consent_card.py), keep-awake, the weekly update check,
     the Claude Code door, the Snipping-Tool key. Drawn as they stand
     (D34: the defaults are what the owner runs) and written only when
     moved.
  7. Ready — the hotkey named, Start-with-Windows and the phone asked
     once, and — signed in — the words-and-settings sync, ON by
     default (the owner, 2026-09-20: nobody found the gate in
     Settings; the row says what leaves and how to turn it off, and
     Start records the consent — a row nobody saw is never one); the
     desk one button away

At most four real decisions (arch-A §1 P2): the microphone (only when
more than one input exists), the downloads, the extras, and nothing
else; every page has a way through without deciding.

THE WORDS ARE ENGLISH — the owner's verdict of 2026-09-19, walking the
installed copy as a stranger: "the design must be redone here, and the
text in English". Short, plain, one primary action per page. The one
thing that stays Hebrew is what the person SAID: the sentence page's
transcript, which goes through the bitmap path (chapter 9.1).

THE LOOK IS LAMPLIGHT (skin\\palette.py): the warm graphite ground, gold
for the one primary action, the same face as the site and the
installer's pictures. ui.py takes that palette only when the skin's
skia imports, and on a first run the skin pack is not on the disk yet —
which is how the installed copy came up in the old blue. The wizard
applies the palette itself (`_lamplight`), since it is numbers and
needs no library.

Built on ui.py, so it is the dashboard's window rather than a Tk
dialog: same buttons, same switches, same bidi text renderer. Nothing
here imports main.py — the wizard has to run BEFORE the app does, and
pulling in the app's imports would make the "loading" step start
before the window.
"""
from __future__ import annotations

import dataclasses
import gc
import logging
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

# The installed interpreter runs under python311._pth, which isolates
# sys.path to the four lines in that file: the script's own folder is
# NOT added, so `python\python.exe app\firstrun.py` by path found no
# `paths`. main.py and deskit.pyw make the same insert.
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import config as config_mod
import paths
import steps
import ui

log = logging.getLogger("app")

# Where "this copy has been set up" is written: `setup.done` in
# state.json (D2) — a fact about one installation, in the file that
# holds the other facts about it. The marker file is what a --config
# one-file run writes (set_values is a line editor and cannot add a
# key), and older copies that wrote it are still honoured by needed().
MARKER = paths.SETUP_MARKER

W, H = 720, 720                     # 660 until 2026-09-19: the consent panel lives on the extras card now
PAD = 28
INNER = W - 2 * PAD                 # the width everything on a page gets
METER_W, METER_H = INNER, 12
ROW_H = 44                          # one microphone row
# How long a silent meter is allowed to stay silent before the wizard says
# something. Long enough not to nag someone who is reading the screen,
# short enough to beat the conclusion that the app is broken.
QUIET_S = 6.0
# What counts as "the bar moved". Room noise on an open mic sits well
# under this; a spoken word is far over it. Measured against the same
# Recorder.meter() the ask card draws its wave from.
SPEECH = 0.045
TEST_S = 3.0                        # how long the sample recording runs

PAGES = ("welcome", "account", "mic", "computer", "say", "keys", "extras", "done")
#: The screenshot key when the Snipping-Tool switch is on / off (screen 13).
SNIP_KEY, PLAIN_SNIP_KEY = "win+shift+s", "ctrl+f11"

#: The keys page: (config field, the label a stranger reads).
KEY_ROWS = (("hotkey", "keys.hold"), ("latch_hotkey", "keys.latch"),
            ("punctuate_hotkey", "keys.punctuate"),
            ("visual_qa_hotkey", "keys.screen"))

#: Every sentence the wizard shows, in one place so the guide (chapter
#: 14) can quote it. English throughout; only the person's own sentence
#: on the "say" page is Hebrew, and that is not a string here.
WORDS = {
    "eyebrow": "DeskIT",
    "step": "Step {n} of {total}",
    "welcome.title": "Welcome to DeskIT",
    "welcome.lines": ("Your voice stays on this computer.",
                      "What you said is kept in one folder you can delete.",
                      "Nothing is sent anywhere until you turn it on yourself."),
    "welcome.defaults": "The defaults are good. Everything can be changed later in Settings.",
    "welcome.link": "How to check this yourself",
    "welcome.privacy": "Privacy policy",
    "account.title": "Your account",
    "account.sub": "Sign in once with Google. This PC remembers you until you sign out.",
    "account.for": ("Your learned words and settings follow you to any PC you sign in on.",
                    "One Google sign-in, and this computer remembers you."),
    "account.stored": ("Stored: the account id and e-mail of the Google account you pick, "
                       "this PC's name, the app version and the Windows version — on "
                       "DeskIT's server (Supabase, Frankfurt)."),
    "account.never": ("Never stored: your voice, what you said, your keys. The last page "
                      "asks whether your learned words and settings stay in the account; "
                      "what you said is synced only if you turn that on in Settings."),
    "account.none": "This copy has no account server — you can go on.",
    "account.button": "Sign in with Google",
    "account.waiting": "Waiting for Google's sign-in page in your browser…",
    "account.signed": "Signed in as {email}",
    "account.anonymous": "Signed in (anonymous account)",
    "account.remembered": "This PC remembers you until you sign out (Settings > Account).",
    "account.failed": "Not signed in: {why}",
    "account.terms": "Terms",
    "account.continue": "Continue",
    "mic.title": "Which microphone?",
    "mic.sub": ("Say a few words. The bar below should move — if it does, "
                "everything else is a detail."),
    "mic.none": "No microphone was found.",
    "mic.default": "Windows default",
    "mic.talk": "Talking? The bar should move.",
    "mic.heard": "Heard. You can go on.",
    "mic.cannot": "Cannot open this microphone: {error}",
    "mic.help": ("Nothing moving? Windows may be blocking microphone access for desktop "
                 "apps. Open Settings > Privacy & security > Microphone and turn on both "
                 "“Microphone access” and “Let desktop apps access your "
                 "microphone”. DeskIT appears in that list only after its first "
                 "recording."),
    "mic.open": "Open Windows settings",
    "computer.title": "This computer",
    "computer.sub": ("What is missing downloads once. Next opens when the download is done; "
                     "Pause it if you must go on, and finish it later from the desk."),
    "computer.wait": "Downloading — Next opens when it is done, or press Pause.",
    "computer.ready": "Everything this computer needs is already on the disk.",
    "computer.portable": "Portable copy: the models come from the Hugging Face cache, as always.",
    "computer.cpu": ("Without an NVIDIA card DeskIT works, only slower. Later you can add a "
                     "free Groq key for fast transcription in the cloud (Settings > Privacy)."),
    "computer.pack": "Use the NVIDIA card",
    "computer.pack.help": "{size} of NVIDIA's CUDA libraries from PyPI, under NVIDIA's licence.",
    "computer.detector": "Detect English automatically",
    "computer.detector.help": "{size} more on the disk, and the same in video memory.",
    "computer.recording": "Screen recording and the camera",
    "computer.recording.help": "{size} from PyPI: PyAV with FFmpeg (a GPL build), for the record key, the photo key and the phone's audio.",
    "computer.queue": "{n} of {total} · {name} · ",
    "step.model.title": "The Hebrew model",
    "step.model.body": ("DeskIT transcribes on this computer, without the cloud, with a "
                        "Hebrew model that downloads once — {size} from huggingface.co "
                        "into DeskIT's folder. Pause any time; the next start continues "
                        "from the same point."),
    "step.pack.title": "Speed from the NVIDIA card",
    "step.pack.body": ("An NVIDIA card was found. To transcribe on it — many times faster "
                       "than on the processor — DeskIT needs NVIDIA's CUDA libraries: "
                       "{size} from PyPI, under NVIDIA's licence."),
    "step.detector.title": "English detection",
    "step.detector.body": ("A second, general model that notices when you spoke English and "
                           "transcribes it as English: {size} more on the disk and in video "
                           "memory. Without it an English sentence comes out in Hebrew letters."),
    "step.recording.title": "Screen recording and the camera",
    "step.recording.body": ("The record key, the photo key and the phone's audio need PyAV — "
                            "{size} from PyPI, with FFmpeg (a GPL build), under their own licences."),
    "step.done": "Downloaded and verified.",
    "step.offline": ("No internet connection. DeskIT asks again at the next start, and the "
                     "download continues from the same point."),
    "step.paused": "Paused. The next start continues from the same point.",
    "step.failed": "The download failed ({why}). DeskIT asks again at the next start.",
    "say.title": "Say one sentence",
    "say.sub": ("Two steps. First load the speech model — once, a few seconds. "
                "Then press Record, talk for three seconds, and read what came out."),
    "say.load": "Load the speech model",
    "say.loading_model": "Loading the speech model… a few seconds, once. Every sentence after this is fast.",
    "say.loaded_ready": "Model loaded in {seconds:.1f} s — now press Record and say a sentence.",
    "say.load_failed": "The model could not load: {error}",
    "say.waiting": "The model is still downloading — the bar above. You can skip and try from the desk.",
    "say.waiting.idle": "The model is not downloaded yet — press Download above, or skip and get it from the desk.",
    "say.waiting.stopped": "The download stopped — Download above continues it, or skip and finish it from the desk.",
    "say.placeholder": "Your sentence appears here.",
    "say.button": "Record 3 seconds",
    "say.recording": "Recording…",
    "say.loading": "Transcribing…",
    "say.nothing": "Nothing was captured.",
    "say.quiet": "Silence. Go back and check the bar.",
    "say.heard": "This is what it heard — decoded in {seconds:.1f} s",
    "say.loaded": "model loaded in {seconds:.1f} s",
    "say.cpu": "This is the speed to expect on this computer.",
    "keys.title": "Keys",
    "keys.sub": ("Click a key to change it. Everything here can be changed later "
                 "under Keys on the desk."),
    "keys.hold": "Hold and talk",
    "keys.latch": "Latch — talk without holding",
    "keys.punctuate": "Punctuate what was just pasted",
    "keys.screen": "Ask about the screen",
    "keys.press": "Press a key…",
    "keys.listening": "Press the new key or combination. Esc cancels.",
    "keys.saved": "{label}: {key}",
    "keys.refused": "Not a key this can use — try another.",
    "keys.taken": "{key} already means “{other}” — pick another key.",
    "keys.no_chord": "This key is held, not tapped, so it cannot take Ctrl, Shift or Alt — press a single key.",
    "extras.title": "Extras",
    "extras.sub": ("Each row is one thing that leaves this PC or changes Windows. Nothing "
                   "goes to the cloud until you switch it on; all of it can be changed "
                   "later in Settings."),
    "extras.cloud": "Fix misheard words with a free cloud model (text only)",
    "extras.cloud.help": "Needs your own free Groq key; the text of what you said leaves this PC.",
    "extras.cloud.key": "Paste your free Groq key — it is checked the moment you save it.",
    "extras.key.have": "A Groq key is already stored on this PC — checking it…",
    "extras.key.testing": "Checking the key with Groq…",
    "extras.key.works": "Key works — cloud repair is on.",
    "extras.key.refused": "Groq did not accept this key — check it and paste it again.",
    "extras.key.offline": "Could not reach Groq right now — the key was kept and is checked the first time the cloud is used.",
    "extras.key.notkey": "That does not look like a Groq key — keys start with gsk_ and hold only English letters and digits. Paste it again.",
    "extras.key.wait": "Turn the cloud switch off, or paste a working key.",
    "extras.key.checking": "Checking the key…",
    "extras.key.placeholder": "Paste your Groq API key here",
    "extras.key.save": "Save key",
    "extras.key.get": "No key yet? Get a free one at console.groq.com/keys — a minute, no card needed.",
    "extras.key.stored": "Stored in Windows Credential Manager — checking it with Groq…",
    "extras.key.empty": "Nothing to save — paste the key first.",
    "extras.key.failed": "Could not store the key: {error}",
    "extras.awake": "Keep this PC awake while DeskIT runs",
    "extras.awake.help": "Stops Windows from sleeping while it runs; Settings > The app turns it off.",
    "extras.updates": "Check for updates weekly",
    "extras.updates.help": "One request to github.com, no identifier sent.",
    "extras.claude": "Connect Claude Code",
    "extras.claude.help": "Two hook lines in ~/.claude/settings.json: when Claude Code finishes or asks, DeskIT shows a card.",
    "extras.snip": "Take over Win+Shift+S for DeskIT's screenshot key",
    "extras.snip.help": "Windows' own Snipping Tool stops answering that shortcut while DeskIT runs; off, the key is Ctrl+F11.",
    "done.autostart": "Start with Windows",
    "done.autostart.help": "A Run entry for your user; Settings > The app turns it off.",
    "done.phone": "Dictate from your phone",
    "done.phone.help": "This PC listens for the DeskIT keyboard on your Tailscale address (Settings > Phone shows how).",
    "done.sync": "Keep my learned words and settings in my account",
    "done.sync.help": ("On any PC you sign in on, DeskIT then hears you your way from the first "
                       "sentence: the words it learned from you and the settings you changed "
                       "follow you there. Never your voice, your keys or what you said. "
                       "Settings > Privacy > Withdraw turns it off."),
    "done.title": "DeskIT is ready",
    "done.sub": "Hold the key and talk. The text lands where your cursor is, in any window. Start opens the desk.",
    "done.deferred": ("DeskIT is installed. The Hebrew model can be downloaded from the desk "
                      "whenever you like."),
    "done.hold": "Hold",
    "next": "Next", "back": "Back", "skip": "Skip", "finish": "Start",
    "saved.error": "Could not save: {error}",
}

GUIDE_PRIVACY_CHECK = f"{paths.PAGES_URL}/en/04-privacy"      # guide chapter 4, in the wizard's language
PRIVACY_URL = f"{paths.PAGES_URL}/privacy"


# ------------------------------------------------------------ the palette

def _lamplight() -> None:
    """The app's own palette, whether or not the skin's skia is here.

    ui.py repaints itself from skin\\palette.py only when `skin.on()` —
    which needs skia-python, a PACK on an installed copy. On a first run
    the pack is not there yet, so the wizard came up in the old blue (the
    owner's screenshots, 2026-09-19) while the site and the installer
    were gold. The palette is numbers; nothing about it needs a library,
    so the wizard applies it here. HD_SKIN=0 and ENABLED = False in
    skin\\__init__.py still mean the old look, the way they do for the
    rest of the app.
    """
    if os.environ.get("HD_SKIN", "1").strip().lower() in ("0", "off", "false", "no"):
        return
    try:
        import skin
        from skin import palette
    except Exception:                                      # noqa: BLE001
        return
    if not getattr(skin, "ENABLED", True) or ui.ACCENT == palette.ACCENT:
        return
    for name, value in palette.UI_NAMES.items():
        if name in ui.__dict__:
            setattr(ui, name, value)
    ui.forget_images()
    log.info("wizard: palette applied without the skin pack")


def _colorref(colour: str) -> int:
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return r | (g << 8) | (b << 16)


def _caption(root) -> None:
    """The title bar in the window's own colours (DWM 20, 35, 36 — the
    same three dashboard._dark_caption sets, on THIS palette rather
    than the dashboard's literal)."""
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(int(root.winfo_id()))
        for attribute, value in ((20, 1), (35, _colorref(ui.BG)),
                                 (36, _colorref(ui.FG))):
            payload = ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(payload), 4)
    except Exception:                                      # noqa: BLE001
        pass                          # Windows 10: the window still works


# ---------------------------------------------------------- microphones

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


# The host APIs, best first. WASAPI gives 16 kHz shared-mode capture
# without the fallback in recorder.py and does not truncate names.
API_RANK = {"Windows WASAPI": 0, "Windows WDM-KS": 1, "MME": 2,
            "Windows DirectSound": 3}
#: MME cuts every device name at 31 characters ("Headset Microphone
#: (Arctis 7 Ch"), which is how the same microphone fails to match its
#: own WASAPI row by name.
MME_CUT = 31
#: An API's "whatever Windows calls the default" alias — not a device.
ALIASES = frozenset({"microsoft sound mapper - input",
                     "primary sound capture driver"})


def _devices() -> list[tuple[str, str, str, int]]:
    """(key, readable name, host API, index) for every input device, best
    first.

    The KEY is what gets written (see device_key). The index is kept for
    the tie-breaks below — the same microphone appears three or four
    times on a normal Windows box, and one_per_device() folds them.
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
    out.sort(key=lambda d: (API_RANK.get(d[2], 9), d[3]))
    return out


def same_device(a, b) -> bool:
    """Are two listing rows one physical microphone under two host APIs?

    The same name is the same device. An MME name that is exactly the
    truncation of a longer one is too: MME's "Headset Microphone (Arctis
    7 Ch" IS WASAPI's "Headset Microphone (Arctis 7 Chat)". Nothing
    looser — "Nothing Ear" and "Nothing ear (1" are two Bluetooth
    endpoints and stay two rows.
    """
    x, y = str(a[1]).lower(), str(b[1]).lower()
    if x == y:
        return True
    for short, long_, api in ((x, y, a[2]), (y, x, b[2])):
        if api == "MME" and len(short) >= MME_CUT and long_.startswith(short):
            return True
    return False


def one_per_device(listing, chosen: str = "") -> list:
    """The listing folded to ONE row per physical microphone.

    The owner's screen showed five rows for two microphones — MME, WASAPI
    and WDM-KS each list the same hardware — and a stranger cannot tell
    which of three identical names to click. Each group keeps one row:
    the device the settings already name (so the selected row lights up
    and Next writes nothing new), else its best API (API_RANK: WASAPI
    first), else the lowest index. DirectSound is a wrapper over the
    same devices and its rows are dropped, as are the two "default"
    aliases — unless one of those is what the settings name.
    """
    chosen = str(chosen or "")
    groups: list[list] = []
    for row in listing:
        for group in groups:
            if any(same_device(row, other) for other in group):
                group.append(row)
                break
        else:
            groups.append([row])
    out = []
    for group in groups:
        mine = [r for r in group if str(r[0]) == chosen]
        if mine:
            out.append(mine[0])
            continue
        real = [r for r in group
                if r[2] != "Windows DirectSound" and str(r[1]).lower() not in ALIASES]
        if not real:
            continue
        out.append(min(real, key=lambda r: (API_RANK.get(r[2], 9), r[3])))
    return out


def order_for(listing, chosen: str):
    """The list as the wizard shows it: whatever is already selected first.

    Pulled out of the screen so it can be tested: the sort puts WASAPI
    first, and on this machine the device the settings already name is
    an MME one that landed ninth — so the row the owner was actually
    using was off the bottom of a list of their own microphones.
    """
    chosen = str(chosen or "")
    mine = [d for d in listing if str(d[0]) == chosen]
    return mine + [d for d in listing if str(d[0]) != chosen]


def default_device(listing=None, rows=None) -> str:
    """The device the wizard starts on: whatever Windows calls the default,
    named by the ROW the wizard shows for it.

    "" would also work — recorder.py reads an empty string as the system
    default — but showing a row selected is what tells someone the list is
    a choice rather than a warning. sounddevice's default is an MME
    index; the row shown for that microphone is its best API's
    (one_per_device), so that is the key answered, and the same physical
    device lights up. "" when the default cannot be named.
    """
    try:
        import sounddevice as sd
        index = sd.default.device[0]
        if index is None or index < 0:
            return ""
        listing = _devices() if listing is None else listing
        raw = next((r for r in listing if r[3] == int(index)), None)
        if raw is None:
            return ""
        rows = one_per_device(listing) if rows is None else rows
        for row in rows:
            if same_device(row, raw):
                return row[0]
        return raw[0]
    except Exception:
        return ""


def open_microphone_settings() -> bool:
    """The Settings page for the trap, opened for them."""
    try:
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

    def __init__(self, parent, bg: str, width: int = METER_W):
        super().__init__(parent, width=width, height=METER_H + 6, bg=bg,
                         highlightthickness=0, bd=0)
        self._peak = 0.0
        self._width = width
        self._track = self.create_image(
            0, 3, anchor="nw",
            image=ui.rounded(width, METER_H, METER_H // 2, ui.EDGE, bg, ui.LINE))
        self._fill = self.create_rectangle(2, 5, 2, 1 + METER_H,
                                           fill=ui.ACCENT, width=0)
        self._mark = self.create_rectangle(0, 0, 0, 0, fill=ui.GREEN, width=0)

    def show(self, level: float) -> None:
        level = max(0.0, min(1.0, float(level)))
        # A meter drawn linearly barely moves for speech: normal talking
        # peaks around 0.1-0.3 of full scale, which is 30 px of 360. The
        # square root is not a decoration, it is what makes the thing
        # readable at the level people actually speak at.
        shown = level ** 0.5
        self.coords(self._fill, 2, 5, max(2, (self._width - 4) * shown), 1 + METER_H)
        self.itemconfig(self._fill,
                        fill=ui.GREEN if self._peak >= SPEECH else ui.ACCENT)
        if level > self._peak:
            self._peak = level
            x = (self._width - 4) * (self._peak ** 0.5)
            self.coords(self._mark, x - 1, 0, x + 1, METER_H + 6)

    @property
    def peak(self) -> float:
        return self._peak

    def forget(self) -> None:
        self._peak = 0.0
        self.coords(self._mark, 0, 0, 0, 0)
        self.coords(self._fill, 2, 5, 2, 1 + METER_H)


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


# ---------------------------------------------------------- the sentence

@dataclasses.dataclass
class Heard:
    """What the sentence page got back: the text, or why not, and the
    two times apart — the model's load (once, seconds) and the decode
    (what every later dictation costs)."""

    text: str = ""
    problem: str = ""
    load_s: float = 0.0
    decode_s: float = 0.0


#: Where a backend may report its own timing (lane B is separating load
#: from decode in the result). The first attribute found wins; the wall
#: clock around the call is the fallback.
DECODE_FIELDS = ("last_decode_s", "decode_s", "last_latency", "latency")
LOAD_FIELDS = ("last_load_s", "load_s", "model_load_s")


def _reported(backend, names) -> float | None:
    """A backend's own number for one of `names`: an attribute, or a key
    of its `last_timing` / `timing` dicts (transcribers/local_whisper.py
    keeps decode_s in last_timing and load_s in timing)."""
    for name in names:
        value = getattr(backend, name, None)
        if isinstance(value, (int, float)) and value >= 0:
            return float(value)
        for holder in ("last_timing", "timing"):
            d = getattr(backend, holder, None)
            if isinstance(d, dict) and isinstance(d.get(name), (int, float)) and d[name] >= 0:
                return float(d[name])
    return None


def transcribe(cfg, wav: bytes, timing: dict | None = None) -> tuple[str, str]:
    """(text, problem) — the older door, kept for its callers: one
    transcribe_timed() with a fresh backend; `timing`, when given, comes
    back with `load_s` and `seconds` (the sentence alone), apart."""
    heard, _backend = transcribe_timed(cfg, wav)
    if timing is not None:
        timing.update(load_s=heard.load_s, seconds=heard.decode_s)
    return heard.text, heard.problem


def transcribe_timed(cfg, wav: bytes, backend=None) -> tuple[Heard, object]:
    """(Heard, backend). Loads the real backend — seconds cold, and said
    so — and keeps it, so a second try on the page does not load again.

    The app's own `get_transcriber`, not a shortcut: the point of the step
    is to prove the pipeline the user is about to rely on, and a wizard
    that passed while the app failed would be worse than no wizard.

    `timing`, when given, comes back with `load_s` (building the backend:
    both models, their warm-ups) and `seconds` (the sentence itself,
    detection and decode) — APART, because the page used to time the
    two together and say "took 8.0 s" of a sentence that decoded in 0.5 s
    (2026-09-19, the installed copy: 7.5 s of that was the load).
    """
    load_s = 0.0
    try:
        if backend is None:
            from transcribers import get_transcriber
            started = time.monotonic()
            backend = get_transcriber(cfg)
            load_s = time.monotonic() - started
        started = time.monotonic()
        text = (backend.transcribe(wav) or "").strip()
        decode_s = time.monotonic() - started
    except Exception as e:
        log.info("wizard transcription failed: %r", e, exc_info=True)
        return Heard(problem=str(e) or e.__class__.__name__), backend
    reported = _reported(backend, DECODE_FIELDS)
    if reported is not None:
        decode_s = reported
    reported_load = _reported(backend, LOAD_FIELDS)
    if reported_load is not None and load_s:
        load_s = reported_load
    return Heard(text=text, load_s=load_s, decode_s=decode_s), backend


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
           "detector": None, "recording": None, "tier": (facts or {}).get("tier", "")}
    if paths.PORTABLE:
        return out
    import models
    import packs
    repo = cfg.local.model
    if cfg.backend == "local" and models.state(repo) != "ready":
        out["model"] = models.entry(repo)
    if packs.wanted(cfg, facts):
        out["pack"] = packs.pack("gpu")
    # The Recording pack (PyAV, 13.4): offered HERE, on by default, so
    # nobody meets "needs the Recording pack" on the record key later —
    # the owner's stranger walk, 2026-09-19 evening: "the software comes
    # with everything; nobody installs things in the middle". It stays a
    # download rather than a line in the installer because PyAV's wheel
    # bundles a GPL FFmpeg (D24) — fetched with its licences shown.
    if packs.state("recording") in ("missing", "stale"):
        out["recording"] = packs.pack("recording")
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


def english_step(kind: str, step: steps.Step, size: int) -> steps.Step:
    """The step with the wizard's English words on it. models.py and
    packs.py speak Hebrew — that is the standalone window's design — and
    the wizard's pages are English, so the copy the wizard hosts carries
    its own title, paragraph and end sentences. The work, the size line,
    the links and the button are the step's own."""
    words = WORDS
    title = words.get(f"step.{kind}.title", step.title)
    body = words.get(f"step.{kind}.body", step.body).format(size=steps.human(size))
    said = {"done": words["step.done"], "offline": words["step.offline"],
            "paused": words["step.paused"], "failed": words["step.failed"]}
    return dataclasses.replace(step, title=title, body=body, said=said)


class KeyRefused(Exception):
    """Groq answered, and the answer was no (a 4xx): the key is wrong."""


def looks_like_key(value: str) -> bool:
    """What a Groq key can be: printable ASCII with no spaces. Not a
    check of the key — Groq does that — a check that it CAN be one, so
    Hebrew or a sentence pasted by mistake is said so at once."""
    return bool(value) and value.isascii() and value.isprintable() and not any(ch.isspace() for ch in value)


def key_probe() -> int:
    """How many models the stored Groq key can see — the one `key-test`
    call, the same the desk's Privacy tab makes. KeyRefused on a 4xx
    (the key itself), any other error for the road (offline, a 5xx)."""
    import json as json_mod

    import net
    status, _headers, body = net.request(
        "GET", "https://api.groq.com/openai/v1/models", "key-test",
        secret="groq", timeout_s=20)
    if 400 <= status < 500:
        raise KeyRefused(f"HTTP {status}")
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    data = json_mod.loads(body.decode("utf-8"))
    return len(data.get("data") or [])


def _write_key(field: str) -> str:
    """The dotted settings key a hotkey field is written under — the
    dashboard's NESTED_HOTKEYS, the one table Settings > Keys writes
    through; the field itself when that table cannot be read."""
    try:
        import dashboard
        return dashboard.NESTED_HOTKEYS.get(field, field)
    except Exception:                                      # noqa: BLE001
        return field


def _label_of(field: str) -> str:
    for name, word in KEY_ROWS:
        if name == field:
            return WORDS[word]
    for name, label in config_mod.HOTKEY_FIELDS:
        if name == field:
            return label
    return field


def plain_refusal(error: str, key: str) -> str:
    """check_hotkeys' sentence, in the wizard's words: which key is
    taken by what, or why a chord is refused here — read off the error's
    text, never re-derived."""
    text = str(error)
    taken = re.search(r"must differ from (\w+)", text)
    if taken:
        return WORDS["keys.taken"].format(key=_pretty(key), other=_label_of(taken.group(1)))
    if "cannot take modifiers" in text:
        return WORDS["keys.no_chord"]
    for name, _label in config_mod.HOTKEY_FIELDS:
        text = text.replace(name, _label_of(name))
    return text


class Result:
    """What `run()` answers: truthy when the wizard ran to the end and
    wrote `setup.done`; the two side facts main.py acts on."""

    def __init__(self, saved: bool = False, open_desk: bool = False,
                 installed_pack: bool = False, signed_in: bool = False,
                 closed: bool = False):
        self.saved = saved
        self.open_desk = open_desk
        self.installed_pack = installed_pack
        self.signed_in = signed_in
        #: The X on the window: the person left. Nothing starts behind
        #: their back (the owner, 2026-09-19 evening: "I pressed the red
        #: X and the model just started out of nowhere").
        self.closed = closed

    def __bool__(self) -> bool:
        return self.saved


class Wizard:
    """Eight pages in one window, and a Back that actually goes back.

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
        self._rows: dict[str, tuple] = {}
        self._quiet_since = time.monotonic()
        self._warned = False
        self._busy = False
        self._sample = ""
        self._seconds = 0.0
        self._said_loaded = False
        self._backend = None
        self._closing = False
        self._deferred: queue.Queue = queue.Queue()   # worker threads' hand-backs, drained by the tick
        self._capturing: str | None = None
        self._pending = {"mod": None, "name": None}
        self._key_binds: tuple = ()
        self.caps: dict = {}
        self.rings: dict = {}
        self.meter = None
        self.hint = None
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
                     "detector": self.offers.get("detector") is not None,
                     "recording": self.offers.get("recording") is not None}
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
        # The last page's sync row (the owner, 2026-09-20: nobody found
        # the gate in Settings — "make it the default, on the last screen,
        # with a line that says what they are ticking and how to turn it
        # off"): drawn ON, recorded on Start only (_save_sync), so a
        # switch nobody has seen yet is never a consent. Kept apart from
        # `extras`, which is written on the extras page's Next as well.
        self.sync_wanted = True
        self._sync_shown = False
        try:
            import privacy
            self._sync_shown = bool(privacy.allowed("settings_sync"))
        except Exception:                                  # noqa: BLE001
            pass

        _lamplight()
        # A PhotoImage belongs to the interpreter that made it: the step
        # windows and the dashboard may have had a Tk of their own in
        # this process, so the cache is emptied on both sides.
        ui.forget_images()
        self.root = tk.Tk()
        self.root.title("DeskIT")
        self.root.configure(bg=ui.BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._centre()
        try:
            import dashboard
            dashboard._set_window_icon(self.root)
        except Exception:
            pass                      # cosmetic: never a reason not to run
        _caption(self.root)

        # The foot is packed FIRST, at the bottom: a page that grows (the
        # microphone help) then clips its own tail rather than pushing
        # Back and Next out of the window.
        self.foot = tk.Frame(self.root, bg=ui.BG)
        self.foot.pack(side="bottom", fill="x", padx=PAD, pady=(14, PAD))
        self.body = tk.Frame(self.root, bg=ui.BG)
        self.body.pack(fill="both", expand=True, padx=PAD, pady=(PAD, 0))
        # One primary action per page (the owner's word): the way on is
        # gold on the pages where it IS the action, and quiet where the
        # page has a louder one — Sign in, Download, Record. Two buttons
        # with one job, because a ui.Button's faces are built once.
        self.next_loud = ui.Button(self.foot, WORDS["next"], self._next, bg=ui.BG,
                                   primary=True, w=150)
        self.next_quiet = ui.Button(self.foot, WORDS["next"], self._next, bg=ui.BG,
                                    w=150)
        self._loud = True
        self.next_loud.pack(side="right")
        self.back = ui.Button(self.foot, WORDS["back"], self._back, bg=ui.BG,
                              quiet=True, w=96)
        self.back.pack(side="right", padx=(0, 10))
        self.skip = ui.Button(self.foot, WORDS["skip"], self._skip, bg=ui.BG,
                              quiet=True, w=96)
        self.note = tk.Label(self.foot, text="", bg=ui.BG, fg=ui.DIM,
                             font=(ui.UI, 9), anchor="w", justify="left",
                             wraplength=INNER - 270)
        self.note.pack(side="left", fill="x", expand=True)

        self._show_page()
        self.root.after(60, self._tick)

    # ---------------------------------------------------------------- frame
    @property
    def next(self) -> ui.Button:
        """The way-on button as it is shown now (the tests read it)."""
        return self.next_loud if self._loud else self.next_quiet

    def _foot(self, loud: bool, label: str | None = None) -> None:
        """Which twin is packed, and what it says."""
        shown, hidden = ((self.next_loud, self.next_quiet) if loud
                         else (self.next_quiet, self.next_loud))
        if loud != self._loud:
            hidden.pack_forget()
            shown.pack(side="right", before=self.back)
            self._loud = loud
        for twin in (self.next_loud, self.next_quiet):
            twin.configure_text(label or WORDS["next"])

    def _centre(self) -> None:
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 3)}")

    def _clear(self) -> None:
        self._stop_capture()
        self.pane = None
        self.meter = None
        self.hint = None
        self.say = None
        self.waiting = None
        self.list_holder = None
        self.caps = {}
        self.rings = {}
        for child in self.body.winfo_children():
            child.destroy()
        self._rows = {}

    def _head(self, title: str, sub: str = "") -> None:
        """Every page's top: the mark and the name, the step count, the
        title and one line under it."""
        row = tk.Frame(self.body, bg=ui.BG)
        row.pack(fill="x")
        mark = ui.icon_bitmap(APP_DIR / "icon.png", 20, ui.BG)
        if mark is not None:
            badge = tk.Label(row, image=mark, bg=ui.BG)
            badge.photo = mark
            badge.pack(side="left", padx=(0, 8))
        tk.Label(row, text=WORDS["eyebrow"], bg=ui.BG, fg=ui.DIM,
                 font=(ui.MEDIUM, 9)).pack(side="left")
        shown = [name for name in PAGES if not self._hidden(name)]
        tk.Label(row, text=WORDS["step"].format(n=shown.index(self.name) + 1, total=len(shown)),
                 bg=ui.BG, fg=ui.FAINT, font=(ui.UI, 9)).pack(side="right")
        tk.Label(self.body, text=title, bg=ui.BG, fg=ui.FG,
                 font=(ui.DISPLAY, 18), anchor="w").pack(fill="x", pady=(16, 2))
        if sub:
            self._line(sub, colour=ui.DIM, size=10, pady=(0, 14))

    def _para(self, text: str, *, pt: int, colour: str, lines: int = 4,
              pady=(0, 0), parent=None, bg: str | None = None) -> tk.Label:
        """A Hebrew paragraph, drawn by Windows rather than by Tk — the
        person's own sentence on the "say" page.

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
        bg = bg or ui.BG
        photo, _h, _n = ui.draw_text(text, pt=pt, width=INNER - 40,
                                     max_lines=lines, colour=colour,
                                     bg=bg, rtl=True)
        label = tk.Label(parent, image=photo, bg=bg, anchor="e")
        label.photo = photo
        label.pack(fill="x", pady=pady)
        return label

    def _line(self, text: str, *, colour: str | None = None, pady=(0, 0),
              parent=None, size: int = 10, bg: str | None = None,
              width: int | None = None, anchor: str = "w") -> tk.Label:
        """One English line or short paragraph, left-aligned."""
        label = tk.Label(parent or self.body, text=text, bg=bg or ui.BG,
                         fg=colour or ui.DIM, font=(ui.UI, size), anchor=anchor,
                         justify="left" if anchor == "w" else "center",
                         wraplength=width or INNER)
        label.pack(fill="x", pady=pady)
        return label

    def _link(self, text: str, url: str, parent=None, bg: str | None = None) -> tk.Label:
        label = tk.Label(parent or self.body, text=text, bg=bg or ui.BG,
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

    def _card(self, parent=None, pad: int = 18) -> ui.Card:
        """A lifted face to put a page's rows on; `_fit` sizes it to
        them once they are packed."""
        card = ui.Card(parent or self.body, INNER, 2 * pad + 1, bg=ui.BG, pad=pad)
        card.pad = pad
        return card

    @staticmethod
    def _fit(card: ui.Card) -> None:
        card.body.update_idletasks()
        card.resize(card.body.winfo_reqheight() + 2 * card.pad)

    def _switch_row(self, label: str, help_: str, value: bool, command,
                    parent=None, bg: str | None = None, last: bool = False) -> ui.Switch:
        """A switch, its label and one help line — the Settings page's
        row shape, on whatever face it is put on."""
        parent = parent or self.body
        bg = bg or ui.BG
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", pady=(0, 0 if last else 8))
        switch = ui.Switch(row, value, command, bg=bg)
        switch.pack(side="left", padx=(0, 14), pady=(2, 0))
        words = tk.Frame(row, bg=bg)
        words.pack(side="left", fill="x", expand=True)
        tk.Label(words, text=label, bg=bg, fg=ui.FG, font=(ui.UI, 10),
                 anchor="w").pack(fill="x")
        tk.Label(words, text=help_, bg=bg, fg=ui.DIM, font=(ui.UI, 8),
                 anchor="w", justify="left", wraplength=INNER - 110
                 ).pack(fill="x")
        return switch

    # ---------------------------------------------------------------- pages
    @property
    def name(self) -> str:
        return PAGES[self.page]

    def _show_page(self) -> None:
        self._clear()
        self.note.configure(text="", fg=ui.DIM)
        for twin in (self.next_loud, self.next_quiet):
            twin.enable(True)
        self._foot(True, WORDS["finish"] if self.name == "done" else WORDS["next"])
        getattr(self, f"_page_{self.name}")()
        self.back.enable(self.page > 0)
        if self.name == "say":
            self.skip.pack(side="right", padx=(0, 10))
        else:
            self.skip.pack_forget()

    # ---------------------------------------------------------------- welcome
    def _page_welcome(self) -> None:
        """The mark, the name, three sentences, two quiet links — the
        installer's side picture continued: dark tile, DeskIT, a gold
        rule."""
        head = tk.Frame(self.body, bg=ui.BG)
        head.pack(fill="x", pady=(22, 0))
        mark = ui.icon_bitmap(APP_DIR / "icon.png", 84, ui.BG)
        if mark is not None:
            badge = tk.Label(head, image=mark, bg=ui.BG)
            badge.photo = mark
            badge.pack()
        tk.Label(self.body, text=WORDS["welcome.title"], bg=ui.BG, fg=ui.FG,
                 font=(ui.DISPLAY, 22)).pack(pady=(18, 10))
        rule = tk.Canvas(self.body, width=28, height=2, bg=ui.ACCENT,
                         highlightthickness=0, bd=0)
        rule.pack(pady=(0, 22))
        for sentence in WORDS["welcome.lines"]:
            tk.Label(self.body, text=sentence, bg=ui.BG, fg=ui.FG,
                     font=(ui.UI, 12)).pack(pady=(0, 8))
        self._line(WORDS["welcome.defaults"], colour=ui.DIM, size=10,
                   pady=(14, 22), anchor="center")
        links = tk.Frame(self.body, bg=ui.BG)
        links.pack()
        self._link(WORDS["welcome.link"], GUIDE_PRIVACY_CHECK, parent=links
                   ).pack(side="left")
        tk.Label(links, text="·", bg=ui.BG, fg=ui.FAINT, font=(ui.UI, 9)
                 ).pack(side="left", padx=10)
        self._link(WORDS["welcome.privacy"], PRIVACY_URL, parent=links
                   ).pack(side="left")

    # ---------------------------------------------------------------- account
    def _page_account(self) -> None:
        """Sign in (chapter 9 screen 16, the owner's rule of 2026-09-18):
        the one page with no way past — Next stays off until a session
        exists — on a copy whose sb.py names a project. The page carries
        the account card's own words (what is stored, where), so the
        press is the consent (privacy.grant) and the sign-in in one; the
        browser does Google's part and comes back on the app's loopback
        listener (sb.sign_in_google). A copy without a project says so
        and lets Next through."""
        self._head(WORDS["account.title"], WORDS["account.sub"])
        self._account_state = "idle"
        try:
            import sb
            configured = sb.configured()
            signed = sb.user() if configured else None
            required = bool(sb.REQUIRED)
        except Exception:                                  # noqa: BLE001
            configured, signed, required = False, None, False
        if not configured:
            self._line(WORDS["account.none"], colour=ui.DIM, size=10)
            return
        self.account_holder = tk.Frame(self.body, bg=ui.BG)
        self.account_holder.pack(fill="x")
        if signed:
            self._account_said(signed)
        else:
            self._account_offer(required)

    def _account_offer(self, required: bool = True) -> None:
        """The card with the sign-in button: what the account is for,
        what is stored and never stored, [Sign in with Google]. The way
        on is shut while sb.REQUIRED says no account, no dictation."""
        for child in self.account_holder.winfo_children():
            child.destroy()
        card = self._card(self.account_holder, pad=20)
        card.pack(fill="x")
        f, bg = card.body, ui.CARD
        for sentence in WORDS["account.for"]:
            self._line(sentence, parent=f, bg=bg, colour=ui.FG, size=11,
                       width=INNER - 40, pady=(0, 4))
        self._line(WORDS["account.stored"], parent=f, bg=bg, colour=ui.DIM,
                   size=9, width=INNER - 40, pady=(14, 6))
        self._line(WORDS["account.never"], parent=f, bg=bg, colour=ui.DIM,
                   size=9, width=INNER - 40, pady=(0, 18))
        row = tk.Frame(f, bg=bg)
        row.pack(fill="x")
        self.signin = ui.Button(row, WORDS["account.button"], self._sign_in,
                                bg=bg, primary=True, w=210, h=44)
        self.signin.pack(side="left")
        self._link(WORDS["welcome.privacy"], PRIVACY_URL, parent=row, bg=bg
                   ).pack(side="right", padx=(14, 0))
        self._link(WORDS["account.terms"], f"{paths.PAGES_URL}/terms", parent=row,
                   bg=bg).pack(side="right")
        self.account_line = self._line("", parent=f, bg=bg, colour=ui.DIM,
                                       size=9, width=INNER - 40, pady=(12, 0))
        self._fit(card)
        self._foot(False)
        self.next.enable(not required)

    def _account_said(self, who: dict) -> None:
        """Signed in: the card becomes a check mark, the e-mail and one
        sentence; the way on is the primary again and says Continue."""
        for child in self.account_holder.winfo_children():
            child.destroy()
        card = self._card(self.account_holder, pad=20)
        card.pack(fill="x")
        f, bg = card.body, ui.CARD
        row = tk.Frame(f, bg=bg)
        row.pack(fill="x")
        tk.Label(row, text=ui.ICON["check"], bg=bg, fg=ui.GREEN,
                 font=(ui.ICONS, 16)).pack(side="left", padx=(0, 14))
        words = tk.Frame(row, bg=bg)
        words.pack(side="left", fill="x", expand=True)
        self.account_line = self._line(
            (WORDS["account.signed"].format(email=who["email"]) if who.get("email")
             else WORDS["account.anonymous"]),
            parent=words, bg=bg, colour=ui.FG, size=12, width=INNER - 90)
        self._line(WORDS["account.remembered"], parent=words, bg=bg,
                   colour=ui.DIM, size=9, width=INNER - 90, pady=(4, 0))
        self._fit(card)
        self.signin = None
        self._foot(True, WORDS["account.continue"])
        self.next.enable(True)

    def _sign_in(self) -> None:
        """[Sign in with Google]: the consent row first (this page IS the
        card), then the browser; the outcome is polled by _tick on the
        Tk thread. Idempotent while one is waiting."""
        if self._account_state == "waiting":
            return
        import privacy
        import sb
        try:
            if not privacy.allowed("account"):
                privacy.grant("account")
        except Exception as e:                             # noqa: BLE001
            self.account_line.configure(text=WORDS["account.failed"].format(why=e), fg=ui.RED)
            return
        self._account_state = "waiting"
        self._account_result: dict | None = None
        self.account_line.configure(text=WORDS["account.waiting"], fg=ui.DIM)
        self.signin.enable(False)

        def work() -> None:
            try:
                self._account_result = {"who": sb.sign_in_google()}
            except Exception as e:                         # noqa: BLE001
                self._account_result = {"error": str(e)}
        threading.Thread(target=work, daemon=True, name="wizard-signin").start()

    def _account_poll(self) -> None:
        """Called from _tick while the account page is up."""
        if getattr(self, "_account_state", "idle") != "waiting":
            return
        result = getattr(self, "_account_result", None)
        if result is None:
            return
        self._account_state = "idle"
        if result.get("who"):
            self.result.signed_in = True
            self._account_said(result["who"])
            self._came_back(result["who"])
        else:
            self.account_line.configure(
                text=WORDS["account.failed"].format(why=result.get("error", "?"))[:160],
                fg=ui.RED)
            self.signin.enable(True)

    def _came_back(self, who: dict) -> None:
        """The browser had the foreground; foreground.py (lane E) brings
        the wizard back and shows the signed-in card. Optional: a copy
        without the module still signs in."""
        try:
            import foreground
        except ImportError:
            return
        try:
            foreground.bring_back()
            foreground.signed_in_card(who.get("email") or "")
        except Exception:                                  # noqa: BLE001
            log.debug("foreground after the sign-in", exc_info=True)

    # ------------------------------------------------------------ microphone
    def _page_mic(self) -> None:
        self._head(WORDS["mic.title"], WORDS["mic.sub"])
        listing = _devices()
        if not listing:
            self._line(WORDS["mic.none"], colour=ui.RED, size=11)
            return
        rows = one_per_device(listing, self.device)
        default_key = default_device(listing, rows)
        # Every device, not the first few: a silent cap here is somebody
        # whose microphone is ninth concluding it is not supported.
        self.list_rows = len(rows)
        self.list_holder = ui.Scroller(self.body, w=INNER - 10,
                                       h=self._list_height(4), bg=ui.BG)
        self.list_holder.pack(fill="x")
        for key, name, _api, _index in order_for(rows, self.device):
            self._device_row(self.list_holder.inner, key, name, key == default_key)
        self.list_holder.bind_wheel(self.list_holder.inner)
        self.meter_note = tk.Label(self.body, text="", bg=ui.BG, fg=ui.DIM,
                                   font=(ui.UI, 10), anchor="w")
        self.meter_note.pack(fill="x", pady=(14, 6))
        self.meter = Meter(self.body, ui.BG)
        self.meter.pack(anchor="w")
        # The help, ONCE: one frame the warning is drawn into, emptied
        # before it is drawn again. It used to be appended to the page
        # on every warning, and picking a second device after the first
        # warning put the whole block on screen twice (2026-09-19).
        self.hint = tk.Frame(self.body, bg=ui.BG)
        self.hint.pack(fill="x", pady=(14, 0))
        self._listen()
        if microphone_allowed() is False and not self._warned:
            self._warn_silent()

    def _device_row(self, parent, key: str, name: str, default: bool) -> None:
        # `key` is the identity (what the settings store, see device_key).
        # Ten narrower than the page, because `ui.Scroller` keeps
        # ui.GUTTER px of its canvas clear on the right for the way home.
        width = INNER - 10 - ui.GUTTER
        row = tk.Canvas(parent, width=width, height=ROW_H, bd=0,
                        highlightthickness=0, cursor="hand2", bg=ui.BG)
        row.pack(fill="x", pady=(0, 6))
        face = row.create_image(0, 0, anchor="nw",
                                image=self._row_face(width, key == self.device))
        row.create_text(18, ROW_H / 2 + 1, text=name, anchor="w",
                        fill=ui.FG, font=(ui.UI, 11))
        if default:
            row.create_text(width - 18, ROW_H / 2 + 1, text=WORDS["mic.default"],
                            anchor="e", fill=ui.DIM, font=(ui.UI, 8))
        row.bind("<Button-1>", lambda _e, k=key: self._pick(k))
        row.bind("<Enter>", lambda _e, k=key: self._hover(k, True))
        row.bind("<Leave>", lambda _e, k=key: self._hover(k, False))
        self._rows[key] = (row, face, width)

    @staticmethod
    def _row_face(width: int, chosen: bool, hot: bool = False):
        if chosen:
            return ui.rounded(width, ROW_H, 10, ui.ACCENT_SOFT, ui.BG, ui.ACCENT_EDGE)
        if hot:
            return ui.rounded(width, ROW_H, 10, ui.CARD_HI, ui.BG, ui.LINE_HI)
        return ui.rounded(width, ROW_H, 10, ui.CARD, ui.BG, ui.LINE)

    def _hover(self, key: str, over: bool) -> None:
        row, face, width = self._rows.get(key, (None, None, 0))
        if row is not None:
            row.itemconfig(face, image=self._row_face(width, key == self.device, over))

    def _pick(self, key: str) -> None:
        if key == self.device:
            return
        self.device = key
        for other, (row, face, width) in self._rows.items():
            row.itemconfig(face, image=self._row_face(width, other == key))
        self.meter.forget()
        self._quiet_since = time.monotonic()
        self._warned = False
        self._clear_hint()
        self._listen()

    def _listen(self) -> None:
        if self.listener.listen_to(self.device):
            self.meter_note.configure(text=WORDS["mic.talk"], fg=ui.DIM)
        else:
            self.meter_note.configure(
                text=WORDS["mic.cannot"].format(error=self.listener.error),
                fg=ui.RED)

    def _list_height(self, rows: int) -> int:
        return min(rows, getattr(self, "list_rows", rows)) * (ROW_H + 6) + 4

    def _clear_hint(self) -> None:
        if self.hint is not None:
            for child in self.hint.winfo_children():
                child.destroy()
        holder = getattr(self, "list_holder", None)
        if holder is not None and self.name == "mic":
            holder.resize(self._list_height(4))

    def _warn_silent(self, text: str | None = None) -> None:
        """The trap, named, with the fix one click away.

        Silence is not an error anywhere in Windows' audio API — the
        stream opens, the callbacks arrive, every sample is zero — so
        nothing downstream can report it. Here is the only place it can be
        said before someone decides the app does not work. Drawn into the
        one hint frame, which is emptied first, so it is on screen once
        however many times it is asked for.
        """
        self._warned = True
        if self.hint is None:
            return
        self._clear_hint()
        # Room for the card: the list shows three rows instead of four
        # while the help is up (the page is 660 px tall on purpose — a
        # 720 px laptop screen with its taskbar has no more).
        holder = getattr(self, "list_holder", None)
        if holder is not None:
            holder.resize(self._list_height(3))
        card = self._card(self.hint, pad=16)
        card.pack(fill="x")
        self._line(text or WORDS["mic.help"], parent=card.body, bg=ui.CARD,
                   colour=ui.FG, size=10, width=INNER - 36, pady=(0, 12))
        ui.Button(card.body, WORDS["mic.open"], open_microphone_settings,
                  bg=ui.CARD, w=200).pack(anchor="w")
        self._fit(card)

    def hint_count(self) -> int:
        """How many help blocks the microphone page shows (a test's
        question; the answer is never more than one)."""
        if self.hint is None:
            return 0
        return len(self.hint.winfo_children())

    # --------------------------------------------------------- this computer
    def _page_computer(self) -> None:
        self._head(WORDS["computer.title"], WORDS["computer.sub"])
        self._line(hardware_line(self.facts), colour=ui.FG, size=11,
                   pady=(0, 4))
        offers = self.offers
        if offers.get("portable"):
            self._line(WORDS["computer.portable"], colour=ui.DIM, size=10)
            return
        if not any(offers.get(k) for k in ("model", "pack", "detector", "recording")):
            self._line(WORDS["computer.ready"], colour=ui.GREEN, size=11)
            return
        self._ensure_runs()
        current = self._current_run()
        started = self.active >= 0
        if current is not None:
            self.pane = steps.StepPane(
                self.body, current, width=INNER, bg=ui.BG, secondary=None,
                closing=None, on_end=self._run_ended, compact=False,
                prefix=self._prefix(), on_go=self._download, title_pt=13,
                body_lines=3)
            self.pane.pack(fill="x", pady=(0, 8))
            # [Download] is the action here until it is pressed; then the
            # bar runs by itself and the way on is the action again.
            self._foot(started)
        if not card_tier(self.facts):
            self._line(WORDS["computer.cpu"], colour=ui.DIM, size=9,
                       pady=(0, 12))
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
        if offers.get("recording") is not None:
            r = offers["recording"]
            switch = self._switch_row(
                WORDS["computer.recording"],
                WORDS["computer.recording.help"].format(size=steps.human(r.bytes)),
                self.want["recording"], lambda _v=None: self._flip("recording"))
            if started:
                switch.configure(state="disabled")

    def _flip(self, which: str) -> None:
        if self.active >= 0:
            return                       # the queue is running; too late
        self.want[which] = not self.want[which]

    # ------------------------------------------------------- say one sentence
    def _page_say(self) -> None:
        self._head(WORDS["say.title"], WORDS["say.sub"])
        current = self._current_run()
        if current is not None and not self._all_landed():
            self.pane = steps.StepPane(
                self.body, current, width=INNER, bg=ui.BG, secondary=None,
                closing=None, on_end=self._run_ended, compact=True,
                prefix=self._prefix(), on_go=self._download)
            self.pane.pack(fill="x", pady=(0, 14))
        self.waiting = None
        if self._model_missing():
            # Three ways to be without the model, three sentences: the
            # stranger who pressed Next past page 4 without Download
            # (the checkout's own walk, 2026-09-19) read "still
            # downloading" over a bar that had never moved. The tick
            # keeps the sentence with the run (_say_ready).
            self.waiting = self._line(WORDS[self._waiting_key()], colour=ui.AMBER,
                                      size=10, pady=(0, 12))
        # One primary button, two jobs in order: load the model, then
        # record. People do not read the small print (the owner, 1.1.1
        # walkthrough, 2026-09-19): a Record that silently spent five
        # seconds loading read as "transcription is slow".
        self.say = ui.Button(self.body,
                             WORDS["say.button"] if self._backend is not None
                             else WORDS["say.load"],
                             self._say_action, bg=ui.BG, primary=True, w=220, h=44)
        self.say.pack(anchor="w")
        self._foot(False)
        self.result_card = self._card(pad=18)
        self.result_card.pack(fill="x", pady=(16, 0))
        self.result_label = None
        self._show_sample(self._sample)
        self.status = tk.Label(self.body, text="", bg=ui.BG, fg=ui.DIM,
                               font=(ui.UI, 10), anchor="w", justify="left",
                               wraplength=INNER)
        self.status.pack(fill="x", pady=(10, 0))
        self.cpu_note = None
        if self._sample:
            self._say_result_line(self._seconds, 0.0)
        self._say_ready()

    def _show_sample(self, text: str) -> None:
        """The transcript on its card: Hebrew, right-aligned, through the
        bitmap path; the placeholder while there is none."""
        card = self.result_card
        for child in card.body.winfo_children():
            child.destroy()
        if text:
            self.result_label = self._para(text, pt=ui.PT_WORDS, colour=ui.FG,
                                           lines=3, parent=card.body, bg=ui.CARD)
        else:
            self.result_label = self._line(WORDS["say.placeholder"], parent=card.body,
                                           bg=ui.CARD, colour=ui.DIM, size=10,
                                           width=INNER - 36)
        self._fit(card)

    def _waiting_key(self) -> str:
        state = self.runs["model"].state
        return ("say.waiting" if state == "running"
                else "say.waiting.idle" if state == "idle"
                else "say.waiting.stopped")

    def _say_ready(self) -> None:
        """The record button waits for the model: a queue still running
        means the backend would load a half-written folder or the CPU."""
        if getattr(self, "say", None) is None:
            return
        waiting = self._model_missing()
        self.say.enable(not waiting and not self._busy)
        if waiting and not self._busy:
            self.status.configure(text="", fg=ui.DIM)
        line = getattr(self, "waiting", None)
        if line is not None:
            if not waiting:
                line.pack_forget()            # it landed while this page was up
                self.waiting = None
            elif line.cget("text") != WORDS[self._waiting_key()]:
                line.configure(text=WORDS[self._waiting_key()])

    def _computer_gate(self) -> None:
        """Next waits for the downloads of this page: the owner watched
        a stranger's Next stay live under a running bar (2026-09-19) and
        asked that nobody could leave mid-download. Paused, failed,
        offline or done: the way on opens again; the foot note says why
        it is shut while it is."""
        busy = any(run.running for run in self.runs.values())
        for twin in (self.next_loud, self.next_quiet):
            twin.enable(not busy)
        self.note.configure(text=WORDS["computer.wait"] if busy else "", fg=ui.DIM)

    def _model_missing(self) -> bool:
        run = self.runs.get("model")
        if run is None:
            return False
        return run.state != "done" and not self.offers.get("portable")

    # ------------------------------------------------------------------ keys
    def _page_keys(self) -> None:
        self._head(WORDS["keys.title"], WORDS["keys.sub"])
        card = self._card(pad=18)
        card.pack(fill="x")
        rows = list(KEY_ROWS)
        for i, (field, word) in enumerate(rows):
            row = tk.Frame(card.body, bg=ui.CARD)
            row.pack(fill="x", pady=(0, 0 if i == len(rows) - 1 else 10))
            tk.Label(row, text=WORDS[word], bg=ui.CARD, fg=ui.FG,
                     font=(ui.UI, 11), anchor="w").pack(side="left", fill="x",
                                                       expand=True)
            # The cap sits in a ring that lights gold while the wizard is
            # listening for its key — the focus ring IS the accent.
            ring = tk.Frame(row, bg=ui.CARD, highlightthickness=2,
                            highlightbackground=ui.CARD, highlightcolor=ui.CARD)
            ring.pack(side="right")
            cap = ui.KeyCap(ring, _pretty(getattr(self.cfg, field, "") or ""),
                            lambda f=field: self._rebind(f), bg=ui.CARD, w=180)
            cap.pack()
            self.caps[field] = cap
            self.rings[field] = ring
        self._fit(card)

    def _ring(self, field: str, lit: bool) -> None:
        ring = self.rings.get(field)
        if ring is not None:
            colour = ui.ACCENT if lit else ui.CARD
            ring.configure(highlightbackground=colour, highlightcolor=colour)

    def _rebind(self, field: str) -> None:
        """A chip pressed: the wizard listens for the next key. The
        dashboard's dialog does the same dance (a modifier WAITS and is
        bound on its release if nothing else came) — the events are read
        by the same hotkey.binding_name_from_event. Nothing is paused
        first: the wizard runs before the app does."""
        if self._capturing is not None or field not in self.caps:
            return
        self._capturing = field
        self._pending = {"mod": None, "name": None}
        self.caps[field].set(WORDS["keys.press"])
        self._ring(field, True)
        self.note.configure(text=WORDS["keys.listening"], fg=ui.DIM)
        self._key_binds = (self.root.bind("<KeyPress>", self._key_down, add="+"),
                           self.root.bind("<KeyRelease>", self._key_up, add="+"))
        try:
            self.root.focus_set()
        except Exception:                                  # noqa: BLE001
            pass

    def _key_down(self, event) -> str:
        import hotkey as hotkey_mod
        if self._capturing is None:
            return "break"
        if event.keysym == "Escape":
            self._captured(None)
            return "break"
        name = hotkey_mod.binding_name_from_event(event.keysym, event.keycode)
        if hotkey_mod.is_modifier_key(event.keycode):
            self._pending = {"mod": event.keycode, "name": name}
            return "break"
        self._pending["mod"] = None       # it became half of a chord
        if not name:
            self.note.configure(text=WORDS["keys.refused"], fg=ui.AMBER)
            return "break"
        self._captured(name)
        return "break"

    def _key_up(self, event) -> str:
        """A modifier let go with nothing pressed while it was down is
        the modifier itself — `hotkey = "right ctrl"` is set this way."""
        if self._capturing is None or self._pending.get("mod") != event.keycode:
            return "break"
        name = self._pending.get("name")
        self._pending = {"mod": None, "name": None}
        if name:
            self._captured(name)
        return "break"

    def _stop_capture(self) -> None:
        if self._key_binds:
            for sequence, funcid in zip(("<KeyPress>", "<KeyRelease>"), self._key_binds):
                try:
                    self.root.unbind(sequence, funcid)
                except Exception:                          # noqa: BLE001
                    pass
            self._key_binds = ()
        self._capturing = None

    def _captured(self, key: str | None) -> None:
        field = self._capturing
        self._stop_capture()
        if field is None:
            return
        self._ring(field, False)
        if key is None:
            self.caps[field].set(_pretty(getattr(self.cfg, field, "") or ""))
            self.note.configure(text="", fg=ui.DIM)
            return
        self._apply_key(field, key)

    def _apply_key(self, field: str, key: str) -> None:
        """The same path Settings > Keys takes when the app is not
        running: with_field + check_hotkeys, then config.save under the
        dashboard's NESTED_HOTKEYS name (set_values in one-file mode). A
        collision is refused with a sentence and nothing is written."""
        key = (key or "").strip().lower()
        try:
            new = config_mod.with_field(self.cfg, field, key)
            config_mod.check_hotkeys(new)
            write_key = _write_key(field)
            if self.path is None:
                config_mod.save({write_key: key})
            else:
                config_mod.set_values(self.path, {write_key: key})
        except Exception as e:                             # noqa: BLE001
            self.caps[field].set(_pretty(getattr(self.cfg, field, "") or ""))
            self.note.configure(text=plain_refusal(e, key), fg=ui.RED)
            return
        self.cfg = new
        self.caps[field].set(_pretty(key))
        self.note.configure(
            text=WORDS["keys.saved"].format(label=_label_of(field), key=_pretty(key)),
            fg=ui.GREEN)
        log.info("setup: %s is now %r", field, key)

    # ---------------------------------------------------------------- extras
    def _page_extras(self) -> None:
        self._head(WORDS["extras.title"], WORDS["extras.sub"])
        self.switches: dict[str, ui.Switch] = {}
        card = self._card(pad=18)
        card.pack(fill="x")
        rows = [("cloud", WORDS["extras.cloud"], WORDS["extras.cloud.help"]),
                ("awake", WORDS["extras.awake"], WORDS["extras.awake.help"]),
                ("updates", WORDS["extras.updates"], WORDS["extras.updates.help"]),
                ("claude", WORDS["extras.claude"], WORDS["extras.claude.help"]),
                ("snip", WORDS["extras.snip"], WORDS["extras.snip.help"])]
        self.extras_card = card
        self.cloud_slot = None
        for i, (key, label, help_) in enumerate(rows):
            self.switches[key] = self._switch_row(
                label, help_, self.extras[key],
                lambda _v=None, k=key: self._extra_flipped(k),
                parent=card.body, bg=ui.CARD, last=i == len(rows) - 1)
            if key == "cloud":
                # What the cloud row opens — the consent, then the key —
                # opens HERE, under the row, inside the card (the owner's
                # walk of 2026-09-19: not a window somewhere else, not a
                # square field under the card).
                self.cloud_slot = tk.Frame(card.body, bg=ui.CARD)
                self.cloud_slot.pack(fill="x")
        self._fit(card)
        self.key_panel = None
        self._key_state = "none"      # none | testing | ok | bad — Next waits for ok
        if self.extras.get("cloud"):
            self._show_key_panel()

    def _extra_flipped(self, key: str) -> None:
        on = self.switches[key].get()
        if key == "sync":
            self.sync_wanted = on          # written by Start, _save_sync
            return
        if key == "cloud":
            # THE SWITCH IS THE CONSENT here (the owner, 2026-09-19 evening:
            # "whoever turns it on — that is enough"): the row's own two
            # lines say what leaves and to whom, and privacy.grant records
            # the same text_version the card carries, so Settings > Privacy
            # shows the grant like any other. Off is immediate
            # (privacy.withdraw), like the Privacy tab's button.
            if on:
                granted = False
                try:
                    import consent_card as cc
                    import privacy
                    privacy.grant("cloud_text", cc.card_for("cloud_text")["text_version"])
                    granted = True
                except Exception as e:                     # noqa: BLE001
                    log.warning("the wizard could not record the cloud consent: %s", e)
                self.extras["cloud"] = granted
                if granted:
                    self._show_key_panel()
                else:
                    self.switches[key].set(False)
            else:
                self._clear_slot()
                self.extras["cloud"] = False
                try:
                    import privacy
                    privacy.withdraw("cloud_text")
                except Exception:                          # noqa: BLE001
                    log.info("the cloud gate was not withdrawn", exc_info=True)
            return
        self.extras[key] = on

    def _clear_slot(self) -> None:
        """Whatever the cloud row had opened under it, gone; the card
        shrinks back to its rows."""
        slot = getattr(self, "cloud_slot", None)
        if slot is None or not slot.winfo_exists():
            return
        for child in slot.winfo_children():
            child.destroy()
        # A frame whose last child is gone KEEPS its size (the packer only
        # propagates while it has slaves): back to the 1 px it was born.
        slot.configure(height=1)
        self.key_panel = None
        self._key_state = "none"
        self._fit(self.extras_card)

    def _show_key_panel(self) -> None:
        """The Groq key, asked for under the switch, ON the card (the
        owner, 1.1.1 walkthrough: "make it clickable, open a field for
        the key, and a line that sends people to Groq's site"; his
        stranger walk of 2026-09-19: "inside the card, under the row I
        flipped, pretty and rounded"): a masked ui.Field, Save, and the
        way to a free key for anyone who has none. The value goes to
        secretstore (Credential Manager) and nowhere else."""
        if self.name != "extras" or getattr(self, "key_panel", None) is not None:
            return
        slot = getattr(self, "cloud_slot", None)
        if slot is None or not slot.winfo_exists():
            return
        self._clear_slot()
        import secretstore
        panel = tk.Frame(slot, bg=ui.CARD)
        panel.pack(fill="x", padx=(54, 0), pady=(2, 10))    # under the words, past the switch
        self.key_panel = panel
        have = False
        try:
            have = bool(secretstore.get("groq"))
        except Exception:                                  # noqa: BLE001
            pass
        # Two lines tall from the start, whatever it says: a note that
        # grew from one line to two pushed the rows under it and the card
        # face was never re-fitted, so the last row's help was cut off
        # (his walk of the built installer, 2026-09-19 night).
        self.key_note = tk.Label(panel, text=WORDS["extras.key.have"] if have else WORDS["extras.cloud.key"],
                                 bg=ui.CARD, fg=ui.DIM, font=(ui.UI, 9), height=2,
                                 anchor="nw", justify="left", wraplength=INNER - 110)
        self.key_note.pack(fill="x")
        row = tk.Frame(panel, bg=ui.CARD)
        row.pack(fill="x", pady=(6, 0))
        self.key_box = ui.Field(row, w=INNER - 110 - 130, h=34, bg=ui.CARD, justify="left",
                                placeholder=WORDS["extras.key.placeholder"], pt=10)
        self.key_box.pack(side="left", padx=(0, 10))
        self.key_field = self.key_box.entry
        self.key_field.configure(show="\u2022")
        self.key_box.bind_entry("<Return>", lambda _e: self._save_key())
        self.key_save = ui.Button(row, WORDS["extras.key.save"], self._save_key,
                                  bg=ui.CARD, primary=True, w=120, h=34)
        self.key_save.pack(side="left")
        self._link(WORDS["extras.key.get"], "https://console.groq.com/keys",
                   parent=panel, bg=ui.CARD).pack(fill="x", pady=(6, 0))
        self._fit(self.extras_card)
        self.key_field.focus_set()
        if have:
            self._test_key()

    def _key_say(self, key: str, colour: str, **fmt) -> None:
        """One line under the row, and the card re-fitted around it —
        the note's words change height (a wrap), the face must follow."""
        self.key_note.configure(text=WORDS[key].format(**fmt), fg=colour)
        self._fit(self.extras_card)

    def _save_key(self) -> None:
        """The pasted value into the store — never into a file — the
        field emptied either way, and the key checked with Groq at once
        (the owner, 2026-09-19: "a quick check that it really exists and
        works"). Something that cannot be a key — Hebrew, a space — is
        said so in plain words and never stored: a non-ASCII value put in
        the Authorization header came back as a codec error dressed as
        "could not reach Groq" (his walk of the built installer)."""
        import secretstore
        value = self.key_field.get().strip()
        self.key_box.set("")                 # emptied either way; the placeholder returns
        if not value:
            self._key_say("extras.key.empty", ui.AMBER)
            return
        if not looks_like_key(value):
            del value
            self._key_say("extras.key.notkey", ui.RED)
            return
        try:
            secretstore.set("groq", value)
        except Exception as e:                             # noqa: BLE001
            self._key_say("extras.key.failed", ui.RED, error=e)
            return
        del value
        self._key_say("extras.key.stored", ui.DIM)
        self._test_key()

    def _test_key(self) -> None:
        """One `key-test` request through net.py on a thread — Groq's
        model list under the stored key; the value never touches this
        code, net.py attaches it by name. The answer lands through the
        queue the tick drains."""
        self._key_state = "testing"

        def work() -> None:
            try:
                count = key_probe()
            except (KeyRefused, UnicodeEncodeError) as e:
                # a 4xx, or a stored value no header can carry: not a key
                detail = str(e)               # bound now: `e` is gone once the clause ends
                self._later(lambda: self._key_tested("bad", detail))
            except Exception as e:                         # noqa: BLE001
                detail = str(e)[:120]
                self._later(lambda: self._key_tested("offline", detail))
            else:
                self._later(lambda: self._key_tested("ok", str(count)))

        threading.Thread(target=work, daemon=True, name="setup-key-test").start()

    def _key_tested(self, word: str, detail: str) -> None:
        """A refused key is taken out of the store again — "turn it off
        or paste a key" only makes sense while nothing is there."""
        if self.name != "extras" or getattr(self, "key_note", None) is None:
            return
        log.info("setup: the Groq key test said %s (%s)", word, detail)
        if word == "ok":
            self._key_state = "ok"
            self._key_say("extras.key.works", ui.GREEN)
        elif word == "bad":
            self._key_state = "bad"
            try:
                import secretstore
                secretstore.delete("groq")
            except Exception:                              # noqa: BLE001
                pass
            self._key_say("extras.key.refused", ui.RED)
        else:
            # no answer from Groq: the key stays, and so does the person
            # — the cloud pass checks it again on its first use; the
            # reason is in the log, not on the card (plain words)
            self._key_state = "ok"
            self._key_say("extras.key.offline", ui.AMBER)
        self._extras_gate()

    def _extras_gate(self) -> None:
        """Next waits while the cloud switch is on with no working key
        (the owner, 2026-09-19: "if I turned it on and put no key it must
        not let me continue — turn it off or paste a key")."""
        if self.name != "extras":
            return
        waiting = bool(self.extras.get("cloud")) and self._key_state != "ok"
        for twin in (self.next_loud, self.next_quiet):
            twin.enable(not waiting)
        text = ""
        if waiting:
            text = WORDS["extras.key.checking" if self._key_state == "testing" else "extras.key.wait"]
        if self.note.cget("text") != text:
            self.note.configure(text=text, fg=ui.DIM)

    # ----------------------------------------------------------------- ready
    def _page_done(self) -> None:
        deferred = self._model_missing()
        self._head(WORDS["done.title"],
                   WORDS["done.deferred"] if deferred else WORDS["done.sub"])
        card = self._card(pad=18)
        card.pack(fill="x")
        row = tk.Frame(card.body, bg=ui.CARD)
        row.pack(fill="x", pady=(0, 16))
        tk.Label(row, text=WORDS["done.hold"], bg=ui.CARD, fg=ui.FG,
                 font=(ui.UI, 11), anchor="w").pack(side="left", fill="x", expand=True)
        ui.KeyCap(row, _pretty(self.cfg.hotkey), bg=ui.CARD, w=180).pack(side="right")
        self.switches = {}
        # The sync row first, and only with an account to sync to: on a
        # copy without a server, or one that walked past the account
        # page (sb.REQUIRED off), there is nothing the switch could mean.
        rows = []
        if self._signed_in():
            rows.append(("sync", WORDS["done.sync"], WORDS["done.sync.help"]))
        rows += [("autostart", WORDS["done.autostart"], WORDS["done.autostart.help"]),
                 ("phone", WORDS["done.phone"], WORDS["done.phone.help"])]
        for i, (key, label, help_) in enumerate(rows):
            self.switches[key] = self._switch_row(
                label, help_,
                self.sync_wanted if key == "sync" else self.extras[key],
                lambda _v=None, k=key: self._extra_flipped(k), parent=card.body,
                bg=ui.CARD, last=i == len(rows) - 1)
        self._fit(card)

    @staticmethod
    def _signed_in() -> bool:
        """A configured project and a session: the account page's own
        test, asked again on the last page."""
        try:
            import sb
            return bool(sb.configured() and sb.user())
        except Exception:                                  # noqa: BLE001
            return False

    def _open_desk(self) -> None:
        """[Start]: the app AND the desk. Until 2026-09-19 evening the desk
        had a button of its own beside Start, and the owner pressed Start
        without it — "the model ran without the app": a dot and nothing
        to look at. One way out of the wizard, and it opens the desk."""
        self.result.open_desk = True
        self._save_sync()
        self._save_extras()
        self._finish()

    # -------------------------------------------------------- the downloads
    def _step_for(self, kind: str, thing) -> steps.Step:
        import models
        import packs
        if kind in ("pack", "recording"):
            return packs.step(thing)
        if kind == "detector":
            return models.step(thing, words=models.DETECTOR_TEXT)
        return models.step(thing)

    def _ensure_runs(self) -> None:
        for kind in ("model", "pack", "detector", "recording"):
            thing = self.offers.get(kind)
            if thing is not None and kind not in self.runs:
                step = self._stepper(kind, thing)
                size = int(getattr(thing, "bytes", 0) or step.total)
                self.runs[kind] = steps.StepRun(english_step(kind, step, size))

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
        self.queue = [k for k in ("model", "pack", "detector", "recording")
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
            if kind == "recording":
                try:
                    import packs
                    packs.activate("recording")   # the record key works from here
                except Exception:                              # noqa: BLE001
                    log.info("the Recording pack landed but was not activated", exc_info=True)
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
        """The meter, the downloads, the one sentence the microphone
        page exists for — and the sign-in's outcome on the account page."""
        if self._closing:
            return
        self._drain()
        if self.name == "account":
            self._account_poll()
        try:
            if self.name == "mic" and self.meter is not None:
                level = self.listener.level()
                self.meter.show(level)
                if level >= SPEECH:
                    self._quiet_since = time.monotonic()
                    if self.hint_count():
                        self._clear_hint()       # it moved: the help was wrong
                    self.meter_note.configure(text=WORDS["mic.heard"],
                                              fg=ui.GREEN)
                elif (not self._warned
                        and self.meter.peak < SPEECH
                        and time.monotonic() - self._quiet_since > QUIET_S):
                    self._warn_silent()
            self._pump_runs()
            if self.name == "computer":
                self._computer_gate()
            if self.name == "say":
                self._say_ready()
            if self.name == "extras":
                self._extras_gate()
        except Exception:                                  # noqa: BLE001
            log.debug("the wizard's tick tripped", exc_info=True)
        self.root.after(60, self._tick)

    def _say_action(self) -> None:
        """The button's job right now: the model first, then the sentence."""
        if self._backend is None:
            self._load_model()
        else:
            self._record()

    def _load_model(self) -> None:
        """The app's own backend, loaded on its own thread while the page
        says so; on landing the same button becomes Record."""
        if self._busy:
            return
        self._busy = True
        self.say.enable(False)
        self.status.configure(text=WORDS["say.loading_model"], fg=ui.DIM)

        def work():
            started = time.monotonic()
            try:
                from transcribers import get_transcriber
                backend = get_transcriber(self.cfg)
            except Exception as e:                        # noqa: BLE001
                log.info("wizard: the model did not load: %r", e, exc_info=True)
                return self._later(lambda: self._model_landed(None, 0.0, str(e) or e.__class__.__name__))
            load_s = time.monotonic() - started
            reported = _reported(backend, LOAD_FIELDS)
            self._later(lambda: self._model_landed(backend, reported or load_s, ""))

        threading.Thread(target=work, daemon=True, name="setup-load").start()

    def _model_landed(self, backend, load_s: float, error: str) -> None:
        self._busy = False
        if backend is not None:
            self._backend = backend
            self._said_loaded = True
        if self.name != "say" or self.say is None:
            return                # the page moved on; the model is kept
        if backend is None:
            self.status.configure(text=WORDS["say.load_failed"].format(error=error), fg=ui.RED)
            self.say.enable(True)
            return
        self.status.configure(text=WORDS["say.loaded_ready"].format(seconds=load_s), fg=ui.GREEN)
        self.say.configure_text(WORDS["say.button"])
        self._say_ready()

    def _record(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.say.enable(False)
        self.status.configure(text=WORDS["say.recording"], fg=ui.DIM)
        self._show_sample("")

        def work():
            wav, _seconds = self.listener.record(TEST_S)
            if not wav:
                return self._on_result(Heard(problem=WORDS["say.nothing"]))
            self._later(lambda: self.status.configure(
                text=WORDS["say.loading"], fg=ui.DIM))
            heard, self._backend = transcribe_timed(self.cfg, wav, self._backend)
            self._on_result(heard)

        threading.Thread(target=work, daemon=True, name="setup-test").start()

    def _later(self, fn) -> None:
        """Run `fn` on the Tk thread. A queue the tick drains, not
        root.after from the worker: Tk delivers a cross-thread after()
        only inside mainloop, so a test pumping update() never saw the
        model land (2026-09-19); the queue is delivered either way."""
        if not self._closing:
            self._deferred.put(fn)

    def _drain(self) -> None:
        while True:
            try:
                fn = self._deferred.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception:                              # noqa: BLE001
                log.debug("a deferred call in the wizard tripped", exc_info=True)

    def _on_result(self, heard: Heard) -> None:
        def land():
            self._busy = False
            if self.name != "say" or self.say is None:
                return            # the page moved on while it decoded
            self.say.enable(True)
            if heard.problem:
                self.status.configure(text=heard.problem, fg=ui.RED)
            elif not heard.text:
                self.status.configure(text=WORDS["say.quiet"], fg=ui.AMBER)
            else:
                self._sample = heard.text
                self._seconds = heard.decode_s
                self._show_sample(heard.text)
                self._say_result_line(heard.decode_s, heard.load_s)
                self._save_seconds(heard.decode_s)
        self._later(land)

    def _say_result_line(self, decode_s: float, load_s: float) -> None:
        """"decoded in 0.8 s", and "model loaded in 4.2 s" once — the
        load is paid on the first sentence of a start, never per
        dictation, and a stranger reading one number would take the
        slow first one for the app's speed."""
        line = WORDS["say.heard"].format(seconds=decode_s)
        if load_s >= 0.5 and not self._said_loaded:
            self._said_loaded = True
            line += " · " + WORDS["say.loaded"].format(seconds=load_s)
        self.status.configure(text=line, fg=ui.GREEN)
        if not card_tier(self.facts) and getattr(self, "cpu_note", None) is None:
            self.cpu_note = self._line(WORDS["say.cpu"], colour=ui.DIM, size=9,
                                       pady=(6, 0))

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
    def _hidden(self, name: str) -> bool:
        """A page with nothing on it is not shown (the owner, 2026-09-19
        evening: "I do not want the installation page"): the computer
        page when nothing is left to download — a copy whose downloads
        landed, or a portable one."""
        if name != "computer":
            return False
        offers = self.offers
        return not any(offers.get(k) for k in ("model", "pack", "detector", "recording"))

    def _back(self) -> None:
        if self.page == 0:
            return
        if self.name == "mic":
            self.listener.close()
        self.page -= 1
        while self.page > 0 and self._hidden(self.name):
            self.page -= 1
        self._show_page()

    def _skip(self) -> None:
        if self.name == "say":
            self._advance()

    def _next(self) -> None:
        if self.name == "mic":
            self._save_device()
        if self.name == "done":
            self._open_desk()
            return
        if self.name == "extras":
            self._save_extras()
        self._advance()

    def _advance(self) -> None:
        if self.name == "mic":
            self.listener.close()
        self.page += 1
        while self.page < len(PAGES) - 1 and self._hidden(self.name):
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
        """The switches of pages 6 and 7, each through its own writer and
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

    def _save_sync(self) -> None:
        """The last page's sync row, on Start: THE ROW IS THE CONSENT, as
        the cloud switch is on the extras page — the account page said
        what is stored and where, the row's own line says what follows
        the person and how to stop it — recorded with the card's
        text_version so Settings > Privacy shows the grant like any
        other; off on a later run (the gate open) withdraws it. Nothing
        when the row was not on the page: no account, nothing to sync
        to, and a consent nobody saw is not one. The sync itself is the
        app's worker, 30 s after it starts (sb.start_worker)."""
        if "sync" not in getattr(self, "switches", {}) or self.sync_wanted == self._sync_shown:
            return
        try:
            import privacy
            if self.sync_wanted:
                import consent_card as cc
                privacy.grant("settings_sync", cc.card_for("settings_sync")["text_version"])
            else:
                privacy.withdraw("settings_sync")
            self._sync_shown = self.sync_wanted
        except Exception as e:                             # noqa: BLE001
            log.warning("the wizard could not record the sync consent: %s", e)

    def _finish(self) -> None:
        self.result.saved = (record_done() if self.path is None
                             else mark_done(self.marker))
        self._close()

    def _close(self) -> None:
        if not self.result.saved:
            self.result.closed = True      # the X, not Start
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
    wizard = None
    try:
        wizard = Wizard(cfg, path, marker, **kw)
        return wizard.run()
    except Exception as e:
        log.info("the setup wizard could not run: %r", e, exc_info=True)
        return Result()
    finally:
        # Buried HERE, on the thread that owns Tcl. The wizard's widgets,
        # their PhotoImages and the consent card form reference cycles
        # that only the cyclic collector frees — and a PhotoImage whose
        # __del__ runs in a collection triggered on a DECODE thread, once
        # the app is up and its Tk is gone, aborts the whole process:
        # "Tcl_AsyncDelete: async handler deleted by the wrong thread",
        # the last line of the stranger's copy on 2026-09-19 (spawn.log),
        # 34 s into its first dictation. Two passes: finalizers make
        # garbage of their own.
        wizard = None
        gc.collect()
        gc.collect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(config_mod.load_layered())
