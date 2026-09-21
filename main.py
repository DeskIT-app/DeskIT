"""Hebrew push-to-talk dictation for Windows.

Hold the hotkey (default: Right Ctrl), speak Hebrew, release — the cleaned
transcript is pasted into whatever window has focus. See README.md and
dev/README-dev.md.

Normally launched by double-clicking "DeskIT.vbs", which runs it
windowless via pythonw.exe. With no console there is no Ctrl+C, so a second
launch is refused (single-instance mutex) and "Stop DeskIT.vbs" (i.e.
--stop) asks the running instance to exit.

Flags:
  --fake          use the fake backend (no API key, no speech needed)
  --check         validate the Gemini key/model with one tiny request, exit
  --list-devices  print audio input devices, exit
  --stop          tell a running instance to quit, exit
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import dataclasses
import inspect
import logging
import logging.handlers
import math
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

# The installed interpreter runs under python311._pth, which isolates
# sys.path to the four lines in that file: the script's own folder is
# NOT added, so `python\python.exe app\main.py --verify` — the door the
# guide names (04-privacy check 5) — found no `paths` (v1.1.0 build,
# run 35400078650). deskit.pyw does the same insert for the launchers.
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import paths
import config as config_mod
import control
import privacy
import cues
import firstrun
import hint as hint_mod
import injector
import awake as awake_mod
import models as models_mod
import notify as notify_mod
import notify_watch as notify_watch_mod
import popup as popup_mod
import problems as problems_mod
import reading as reading_mod
import server as server_mod
import singleton
import overlay as overlay_mod
import vocab as vocab_mod
from config import ConfigError
import hotkey as hotkey_mod
from hotkey import (HookThread, PTTStateMachine, parse_binding,
                    parse_chord, vk_for)
from launch import open_dashboard
from recorder import Recorder, SILENT_AFTER_S, SILENT_PEAK
from spool import Spool
from transcribers import RateLimitError, TranscriptionError, get_transcriber
from transcribers.base import ModelMissing, TooLongForCloud

log = logging.getLogger("app")
transcript_log = logging.getLogger("transcripts")

# pythonw.exe (the windowless launcher) gives the process no stdout at all.
HAS_CONSOLE = sys.stdout is not None

# Any string, as long as it is OURS and stays put. It is the same shape as
# the one dashboard.py carries and deliberately NOT the same value: the
# dashboard is the control window, this is the app itself, and one identity
# across both would let the shell fold them into a single taskbar button
# whose relaunch command opens whichever of the two it saw first.
APP_ID = paths.APP_ID


def claim_app_identity() -> None:
    """Say who this process is, before it puts anything on screen.

    Without it the process inherits pythonw.exe's identity: Windows groups
    whatever it shows under the interpreter and hands it pythonw's generic
    icon, which reads as "some script is running" rather than as this
    program. dashboard.py has claimed an identity since it first had a
    window (_claim_taskbar_identity there); the background app never has,
    and the background app is the half of DeskIT that is ALWAYS up.

    It has to happen before the first window exists, because the identity
    is read when the taskbar button is made and setting it afterwards
    changes nothing. That is why it is called here at the top of main()
    and not from overlay.py, which does not run until there is already
    something to show — and why it is not conditional on which mode the
    arguments ask for: --lookup puts a popup on screen too.

    What this does NOT do is repaint Task Manager's process list. That
    column draws the EXECUTABLE's icon, and the executable is pythonw.exe
    until the day this ships as an .exe of its own. Measured 2026-09-07:
    pythonw.exe's FileDescription is the literal string "Python", which is
    the name that list prints beside it.
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception as e:
        # Older Windows, or no shell at all: nothing here is worth
        # refusing to start over, but a silent miss is indistinguishable
        # from never having asked.
        log.debug("could not claim the app identity: %r", e)

# Keys that live INSIDE a config section, and where set_values must write
# them. config.toml keeps one spelling of each key, so the dotted path is
# section plus the key's own name — which is not always the dataclass field
# name ([visual_qa] holds `visual_qa_hotkey`, loaded into `hotkey`).
#
# Spelled out here rather than imported from config.py, and dashboard.py
# keeps its own copy of the same four lines, because BOTH of those files
# are byte-identical on the classic branch while config.py is allowed to
# differ: a constant read out of config.py would be a shared file
# depending on something only one branch defines. Four lines of duplication
# is the cheaper of the two mistakes, and the entries for keys a branch
# does not have are simply never looked up.
NESTED_HOTKEYS = {
    "visual_qa_hotkey": "visual_qa.visual_qa_hotkey",
    "capture_hotkey": "capture.capture_hotkey",
    "record_hotkey": "capture.record_hotkey",
    "camera_hotkey": "camera.camera_hotkey",
    "screens_hotkey": "awake.screens_hotkey",
    "dismiss_hotkey": "notify.dismiss_hotkey",
    "report_hotkey": "problems.report_hotkey",
    "shelf_hotkey": "shelf.shelf_hotkey",
}

# What the dashboard may change while the app runs and have it FELT
# without a restart (App.set_option): the sections whose values are read
# at the moment they matter, each with the lazily built worker that has to
# be thrown away for the change to reach it — a worker holds the Config it
# was built with — and the top-level keys the paste reads on every
# dictation. Everything else is still written, through the same validated
# line edit, and answered with "applies the next time it starts".
LIVE_SECTIONS = {"punctuate": "_punctuator", "translate": "_translator",
                 "polish": "_polisher", "feedback": None, "vocab": None,
                 "hint": None, "review": None, "shelf": None,
                 # "dot" since 2026-09-08. The corner used to be read once
                 # at startup, so the menu wrote a line and nothing on
                 # screen moved — and that menu now sits on the same card
                 # as "Move the dot" and "Back to the corner", which both
                 # act at once. A control beside two honest ones has to be
                 # honest too. See App._dot_power.
                 "dot": None,
                 # [privacy] since 2026-09-17: `offline` is a veto net.py
                 # reads per request, so the switch acts the moment it is
                 # written; the six gates are not written here at all
                 # (config.save refuses them — privacy.py owns them).
                 "privacy": None}
LIVE_TOP_LEVEL = ("auto_pause_fullscreen", "paste_chord", "restore_delay_ms")

# THE WEEKLY ROUTINE'S QUESTION, and the three numbers that decide when it
# gets on his screen (questions.py + overlay.AnswerCard).
#
# Nobody presses a key for this card. The question is written by a headless
# process — the Saturday review, which fires at 04:00 and retries hourly —
# so the app has to NOTICE one rather than be told about one, and it has to
# notice it without being a cost: questions.Store.stamp() is one os.stat of
# a small json and no read at all, which is why 20 s is affordable. It is
# also the right number from the other end. The question can be minutes old
# before it matters, so nothing is lost by waiting; but a Saturday can ask
# three questions, and after he answers one the next has to follow while he
# is still in the mood to answer it. Twenty seconds is "the app noticed";
# five minutes would be "the app forgot".
QUESTION_POLL_S = 20.0

# How still the machine has to have been before a card takes the
# foreground. The card is a WordPrompt underneath — it TAKES THE KEYBOARD —
# and this is an unsolicited window, so the bar is higher than for anything
# else in this file: see _questions_quiet for the whole gate. Twenty seconds
# of no key-down anywhere on the machine is a real pause in what he was
# doing, and it is short enough that the card still feels like an answer to
# the question rather than a letter that arrived next week.
QUESTION_SETTLE_S = 20.0

# Escape records nothing and the question stays pending, so it comes back —
# but not in twenty seconds. A card that reappears while he is still moving
# his hand away from it is a card he cannot get rid of, and the point of
# Escape is "not now".
QUESTION_REASK_S = 300.0

# The flag that runs a console program with its console never shown —
# awake.py and visual_qa.py both spawn powershell with it. NOT combined
# with DETACHED_PROCESS: the two decide the same thing and are documented
# as incompatible (see launch.py, which needs the other one).
CREATE_NO_WINDOW = 0x08000000

# Fewer words than this and the auto punctuation pass stands down. A one-
# or two-word dictation is an answer — "כן", "ארבע" — the decoder already
# closes those with a mark of its own, and the round trip would cost more
# than the utterance took to say.
AUTO_PUNCTUATE_MIN_WORDS = 3

# The feature keys that ask for PIXELS. Named as a set because the one
# question anybody asks of them is "is this action in it" — see
# App._tap_allowed, which is where the reason lives. The four that are NOT
# here (translate, punctuate, correct, lookup) are the ones that read or
# rewrite the text at the cursor, and the cursor is a shared resource
# during a dictation.
# The screens key rides with them: it touches the monitor and never the
# cursor, so it is as true mid-sentence as a screenshot is.
# And the notification-dismiss key: it touches no cursor and no clipboard
# (a JSON write on a thread and a card taken down), and a card that
# arrives mid-sentence must be dismissible mid-sentence.
# The report key is deliberately NOT in here. Every other text key is
# refused mid-hold because there is no selection to act on; this one is
# refused because there is no HAND — it opens a box you type a sentence
# into, and one of the two is on the dictation hotkey. Latched it is
# allowed, like the rest of them, and latching is exactly the state in
# which typing a report while the microphone runs makes sense.
# The shelf key is in here too: the panel reads nothing at the cursor and
# writes nothing anywhere, so it is as true mid-sentence as a screenshot
# is — and "what is waiting" is a fair question to ask while talking.
_SCREEN_ACTIONS = frozenset({"visual_qa", "capture", "record", "photo",
                             "screens", "notify_dismiss", "shelf"})

# How old the last dictation may be before a report stops blaming it.
# Five minutes covers "that came out wrong, let me say why" — the press
# that follows a bad transcript by the time it takes to read it — and
# stops the transcript from this morning being filed as the evidence for
# a problem with something else entirely. A stale clip in a report is
# worse than no clip: a week later it still reads as evidence.
PROBLEM_LAST_MAX_S = 300.0

# What the dot should say for a machine state, when a worker has finished
# with something and is deciding what to put back. Only two states are
# named because only two mean "still listening": everything else — idle,
# paused, whatever comes next — is the plain running dot. It exists
# because a question asked from inside the ask card is transcribed while
# the LOCKED recording underneath keeps going, and the dot turning blue
# there would announce a stop that never happened.
_DOT_FOR = {hotkey_mod.LATCHED: "locked",
            hotkey_mod.RECORDING: "recording"}


def report_fatal(message: str) -> None:
    """Startup failures must be visible even with no console — otherwise
    double-clicking the shortcut just silently does nothing."""
    log.error("%s", message)
    if not HAS_CONSOLE:
        ctypes.windll.user32.MessageBoxW(
            None, message, "DeskIT — cannot start", 0x10)


class SplashLog(logging.Handler):
    """Mirrors the app's own log lines onto the splash.

    Attached to the "app" logger rather than the root one on purpose: the
    startup is full of huggingface HTTP chatter and faster-whisper
    internals, and none of that answers "did my click do anything".
    """

    def __init__(self, splash) -> None:
        super().__init__(level=logging.INFO)
        self._splash = splash

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
        except Exception:
            return
        # Long lines (the phone URL with its token) would reflow the box.
        self._splash.status(text if len(text) <= 110 else text[:107] + "…")


def beep(kind: str) -> None:
    """Fire-and-forget cue (see cues.py — plays through the audio mixer,
    not the inaudible legacy beep path)."""
    cues.play(kind)


def language_label(language: str | None, shout: bool = False) -> str:
    """What to call a recording in the log. None = nothing was declared and
    the model will decide (Config.auto_language)."""
    if language == "en":
        return "ENGLISH" if shout else "English"
    if language == "he":
        return "Hebrew"
    return "Hebrew or English"


def cursor_point() -> tuple[int, int] | None:
    """Where the mouse is, in screen pixels. None if it cannot be read.

    This is the lookup box's anchor, and it is read on the OS hook thread
    the instant the key goes down — which is the whole reason it is one
    syscall and nothing else. A selection is made by dragging the mouse
    across it, so the cursor is left sitting at the end of what was
    selected: that is where the user is looking, and it is the only
    cheaply-available fact that says so. Read later, on the worker, it
    would be wherever the hand had drifted to in the meantime.

    Measured 2026-08-19 on this machine: 1.2 us a call, against the
    0.35 us the same callback already spends on foreground_window(). The
    hook thread's budget is "do not block Windows", and this does not
    come close to touching it.

    None rather than a raise, because the box falls back to the corner it
    used before an anchor existed. An anchor is an improvement on that,
    never a precondition for showing an answer.
    """
    try:
        pt = ctypes.wintypes.POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return int(pt.x), int(pt.y)
    except Exception:
        log.debug("could not read the cursor position", exc_info=True)
    return None


def _questions_mod():
    """questions.py, the Saturday routine's store — the owner's
    (DISTRIBUTION_PLAN.md D15). It is not in the product build, so it
    is imported only where the store is actually on (`[questions]
    enabled = true`, off by default) and never at start: a copy
    without the file must still dictate.
    test_product_suite_imports_no_dev_modules holds the line."""
    import questions
    return questions


class App:
    # Class-level defaults for the visual-QA and capture slots on purpose:
    # the test suite builds half-initialised Apps by hand (no __init__),
    # and _popup_key/_handle must degrade to "feature absent", not crash.
    _vqa = None
    _vqa_vk = None
    _capture = None
    _capture_vk = None
    _record_vk = None
    _camera_vk = None

    def _save(self, updates: dict) -> None:
        """Write a changed setting where this copy keeps its settings.

        Started with --config, the file given is the whole configuration
        and the line editor writes into it (tests, a portable one-file
        run). Started plainly, the app runs on the three layers and the
        change goes to settings.toml or state.json — config.save decides
        which (chapter 3.4, D2)."""
        if self.config_path is None:
            config_mod.save(updates)
        else:
            config_mod.set_values(self.config_path, updates)

    def _reload(self) -> config_mod.Config:
        """The configuration as the files say it is NOW."""
        if self.config_path is None:
            return config_mod.load_layered()
        return config_mod.load(self.config_path)

    def __init__(self, cfg: config_mod.Config,
                 config_path: Path | None = None, model: bool = True):
        self.cfg = cfg
        # model=False: the process without the speech model — what the
        # desk starts when it opens and nothing is running (2026-09-18,
        # his rule: "even if I did not start the model but only opened
        # the desk, every feature that does not need the model works").
        # The hook, the dot, the cards and every tap key come up in a
        # couple of seconds; Start loads the model (load_model).
        self._model_wanted = bool(model)
        # Where a key change is written back to: the one file --config
        # named, or None for the three layers (see _save). Carried rather
        # than recomputed so --config keeps pointing at the file it was
        # given.
        self.config_path = Path(config_path) if config_path else None
        self._stopping = threading.Event()
        self._watcher: threading.Thread | None = None
        parse_chord(cfg.paste_chord)  # fail fast on a bad chord name
        # The str|None is the language the key declared, None meaning it
        # declared nothing — see App.bindings and Config.auto_language.
        # The bool is where the finished text goes, decided at the press
        # and carried rather than re-asked: see _on_start.
        self.queue: queue.Queue[
            tuple[bytes, float, int, str | None, bool]] = queue.Queue()
        # Built BEFORE the transcriber: the local backend takes the hotword
        # callable at construction, and a vocabulary that arrived afterwards
        # would silently do nothing until the next restart.
        self.vocab = vocab_mod.Vocab(
            paths.VOCAB_FILE, seed_terms=cfg.vocab.terms,
            max_terms=cfg.vocab.max_terms,
            replace_after_hits=cfg.vocab.replace_after_hits,
            hebrew_after_hits=getattr(cfg.vocab, "hebrew_after_hits", 3))
        hotwords = self.vocab.hotwords if cfg.vocab.enabled else None
        if self._model_wanted:
            # fail fast: no key. english_later: usable the moment the
            # Hebrew model is ready; the English detector lands on its
            # own thread a few seconds after the ready cue (measured
            # 2026-09-19: 4.8-6.6 s of the splash were its load).
            self.transcriber = get_transcriber(cfg, hotwords,
                                               english_later=True)
        else:
            from transcribers.off import OffTranscriber
            self.transcriber = OffTranscriber(self.MODEL_OFF_WORDS)
        self._hotwords = hotwords
        self._polisher = None        # built on first use (see _polish)
        # The last thing pasted, and what the backend actually returned.
        # The correction key edits the FORMER: it is what the user saw, so
        # it is what their edit is a diff against.
        self._last: dict | None = None
        self._last_lock = threading.Lock()
        self.spool = Spool(paths.PENDING_DIR)
        # A ring of recent recordings, kept so a correction can be tied to
        # the audio that produced it. Without this the app can only be told
        # that a word is wrong, never SHOWN — and no vocabulary change can
        # ever be measured, only assumed. See --benchmark.
        self.recent = (Spool(paths.RECENT_DIR, keep=cfg.vocab.keep_audio)
                       if cfg.vocab.keep_audio > 0 else None)
        # His own bug list (problems.py). Next to `recent` because that is
        # where the evidence comes from: a report pins the clip out of the
        # ring so the audio behind it outlives the fifty that follow.
        # getattr, like every other optional section: a Config without
        # [problems] leaves this None, and every use of it is guarded.
        pcfg = getattr(cfg, "problems", None)
        self.problems = (problems_mod.Store(paths.PROBLEMS_FILE)
                         if pcfg is not None and pcfg.enabled else None)
        # Read this to me (reading.py): the sentence the dashboard has
        # put up, and what came back for it. Its folder sits BESIDE the
        # corpus, not in it, so [study] corpus_keep can never trim away
        # what he sat down to read.
        self.reading = reading_mod.Reading(paths.READ_DIR)
        # The OTHER direction of the same conversation (questions.py). The
        # bug list is what he tells the app; this is what the weekly
        # routine asks him back when a report cannot be explained from the
        # evidence it has — three concrete options and a fourth he types
        # into, put on his screen here and answered here, never in a chat.
        #
        # getattr for the section, like every optional one. What is
        # different is the DEFAULT when there is no [questions] section at
        # all: on, which is the opposite of the line above it. The routine
        # writes questions.json whether or not this Config has grown a
        # section for it, and a pending question nobody is ever shown is
        # worse than no feature — it leaves the routine waiting forever on
        # an answer he was never asked for. An explicit `enabled = false`
        # still turns the whole thing off and leaves the file alone.
        # OFF unless a [questions] section explicitly turns it on, which is
        # the opposite of what the comment above argues -- and the argument
        # died with the design it was written for. The weekly review is a
        # Claude Code local scheduled task now, and every run is a real
        # session with a live composer in the sidebar, so it asks him there
        # with AskUserQuestion and reads his answer in the same breath. It
        # still writes each question into the store, but only as a record
        # that survives him closing the session -- not as a queue anything
        # serves. A card offering a question he has already answered in the
        # session would be the worse half of both designs, and an item that
        # stays PENDING because he answered somewhere else would sit in the
        # dashboard forever. So the card stays built, tested and 83 ms of
        # import (measured), and does not run. `[questions] enabled = true`
        # brings it back whole if the asking ever moves back into the app.
        qcfg = getattr(cfg, "questions", None)
        self.questions = (
            _questions_mod().Store(paths.QUESTIONS_FILE)
            if qcfg is not None and getattr(qcfg, "enabled", False) else None)
        # (size, mtime_ns) as of the last look. questions.Store.stamp()
        # exists for exactly this — notice a headless write without reading
        # the file — and the empty tuple means "never looked", so the FIRST
        # poll always reads: a question written while the app was down is
        # still a question waiting on him.
        self._q_stamp: tuple = ()
        self._q_pending: list[dict] = []
        # id -> the monotonic time before which it must not be offered
        # again. Escape puts a question in here; nothing else does.
        self._q_hushed: dict[str, float] = {}
        # The last real key-down anywhere on this machine, written by the
        # keyboard hook (see _popup_key) and read by _questions_quiet. It
        # is seeded to NOW rather than to zero because the app is launched
        # by hand: a card must not open in the first twenty seconds because
        # the process happened to start with the field empty.
        self._q_last_key = time.monotonic()
        self._answer_card = None     # built on the first question
        self._q_no_card = False      # ...unless the overlay has no class
        self._local = None       # lazily built local fallback, if enabled
        self.recorder = Recorder(cfg.audio.sample_rate, cfg.audio.device,
                                 cfg.max_seconds, self._on_overflow)
        # A dead microphone ten seconds into a dictation, and the
        # all-clear when sound arrives — both from the PortAudio callback,
        # both handed to the dot (see _on_silent). recorder.SILENT_PEAK.
        self.recorder.on_silent = self._on_silent
        self.recorder.on_sound = self._on_sound
        # The cap in force right now: max_seconds while held, lifted by a
        # latch. Kept here purely so the log lines name the real number.
        self._cap = cfg.max_seconds
        self._latched = False
        # When the recording that is running started, for the one line on
        # the shelf that says how long it has been going. One monotonic()
        # written on the hook thread beside `_cap` and read nowhere hot;
        # 0.0 means nothing has been recorded yet this run.
        self._rec_at = 0.0
        if cfg.translate_hotkey or cfg.punctuate_hotkey or cfg.lookup_hotkey:
            parse_chord(cfg.translate.copy_chord)        # fail fast, as above
        if cfg.translate_hotkey or cfg.punctuate_hotkey:
            # Only those two ever select. The lookup key deliberately has no
            # select-all fallback — it never pastes over what it grabbed, so
            # a field left fully selected would be a field the user's next
            # keystroke wipes (injector.read_selection says it at length).
            parse_chord(cfg.translate.select_all_chord)
        # Built whether or not the lookup key is bound: that key can be
        # turned on from the dashboard while the app runs, and a box that
        # only existed if the key had been set at startup would make the
        # rebind do nothing until a restart. A hidden window and an idle
        # message loop cost nothing to keep.
        self.popup = popup_mod.Popup(max_width=cfg.lookup.max_width,
                                     max_height=cfg.lookup.max_height)
        # Ask-the-screen, same logic: built lazily but always AVAILABLE,
        # because its key moves through rebind() like every other one.
        # Constructing the controller imports stdlib only; Pillow and Tk
        # wait for the first press or the background warm-up.
        self._vqa = None
        # Screenshots and screen recordings, the same bargain: two keys
        # that move through rebind() like every other one, and a
        # controller that imports Pillow, Tk and the video encoder only
        # once one of them is actually pressed.
        self._capture = None
        hotkeys, taps, latch_vk, pause_vk = self.bindings(cfg)
        self._lookup_vk = self._vk_of(taps, "lookup")
        self._vqa_vk = self._vk_of(taps, "visual_qa")
        self._capture_vk = self._vk_of(taps, "capture")
        self._record_vk = self._vk_of(taps, "record")
        self._camera_vk = self._vk_of(taps, "photo")
        self.machine = PTTStateMachine(
            hotkeys,
            on_start=self._on_start, on_stop=self._on_stop,
            on_abort=self._on_abort,
            taps=taps, on_tap=self._on_tap,
            latch_vk=latch_vk, on_latch=self._on_latch,
            pause_vk=pause_vk, on_pause=self._on_pause,
            on_key_down=self._popup_key,
            tap_allowed=self._tap_allowed,
            cancel_guard=self._esc_is_claimed,
            ask_open=self._ask_card_open,
            on_ask_start=self._on_ask_start,
            on_ask_stop=self._on_ask_stop,
            on_refused=self._on_dictation_refused)
        self.hook = HookThread(self.machine)
        # The model's own state: "on", "off", "loading", "unloading".
        # Stop in the desk unloads the model and the microphone stream
        # and nothing else (load_model / unload_model); the hook, the
        # dot, the cards and every feature that needs no model keep
        # running, and the hold keys are refused with MODEL_OFF_WORDS.
        self._model_state = "on" if self._model_wanted else "off"
        self._refused_at = 0.0
        if not self._model_wanted:
            self.machine.set_dictation_off(True)
        # awake.py: the machine held awake for as long as this runs (the
        # hold goes up in start()), and the screens off on a key. Built
        # whether or not the key is bound — the dashboard's button goes
        # through the control channel and needs the engine either way.
        self.awake = awake_mod.Engine(paths.DATA_DIR, getattr(cfg, "awake", None),
                                      state_path=paths.AWAKE_STATE,
                                      log_path=paths.AWAKE_LOG)
        # What the dot is showing, kept here so the dashboard can report the
        # same thing in words. Every set_state goes through _set_state.
        self._activity = "ready"
        # Both decided at the press and read again at the release — see
        # _on_start. Seeded here only so that a release with no matching
        # press (there should be none; the state machine sees to that)
        # cannot raise inside the keyboard hook, where an exception is a
        # dropped hook and a frozen keyboard.
        self._to_card = False
        self._to_prompt = False
        self._to_read = False
        self._start_hwnd = 0
        # [visual_qa] echo_to_field. What was dictated INTO the ask card,
        # kept until the card closes and the field it belongs to is in
        # front again — see _on_card_closed for why it cannot be pasted
        # any earlier. _field_hwnd is the last window a dictation was
        # actually AIMED at, which is not _start_hwnd once the card is up:
        # the card is in front then, and _start_hwnd is 0 for our own
        # windows by design.
        # Where in the LOCKED recording the question being spoken to the
        # ask card began. The recording is never ended for it — see
        # _on_ask_stop.
        self._ask_mark = 0
        # The rolling transcriber for the recording in progress (rolling.py):
        # made at the press, handed to the worker at the release, None in
        # between recordings. It decodes the recording in stretches while
        # the key is held so that the release waits only for the tail.
        self._roller = None
        # What was said to the card during THIS recording, in order, as
        # transcribed at the moment it was said. The splice puts these
        # back where they belong — see _transcribe_pieces.
        self._question_texts: list[str] = []
        self._echo_lines: list[str] = []
        self._field_hwnd = 0
        self._echo_lock = threading.Lock()
        self._started_at = time.monotonic()
        # Asked once. status() is polled by the dashboard several times a
        # second and device_label() goes out to PortAudio to enumerate
        # devices — not something to do on every frame of a window.
        self._mic_label = self.recorder.device_label()
        self._note = ""             # the last thing worth saying out loud
        self._auto_paused = False   # paused BY the fullscreen watcher, so
                                    # only it may un-pause it again
        self._stats_lock = threading.Lock()
        self._stats = self._fresh_stats()
        # Repeated identical cues, suppressed. See _cue_once: the
        # correction key can fail several times in a row for one reason,
        # and a row of error tones says "something is badly wrong" when the
        # truth is "that text is not on screen any more".
        self._cue_lock = threading.Lock()
        self._cue_last: dict[tuple[str, str], float] = {}
        self.worker = threading.Thread(target=self._worker, daemon=True,
                                       name="transcribe-worker")
        # The keys that act on text ALREADY on screen — translate and
        # punctuate — share one queue and one thread. Two reasons, and both
        # matter:
        #   - they are independent of dictation, so they must not wait behind
        #     a 40 s transcription retry (or make one wait behind it);
        #   - they must not run at the same time as EACH OTHER. Both work by
        #     copying the selection out and pasting a replacement back, and
        #     this machine has exactly one clipboard and one focused window.
        #     Serialising them is not a limitation, it is the only correct
        #     thing to do with a shared resource.
        self.text_queue: queue.Queue[tuple[str, int]] = queue.Queue()
        self._translator = None
        self._punctuator = None
        self._text_busy = threading.Event()
        self.text_worker = threading.Thread(
            target=self._text_key_worker, daemon=True, name="text-worker")
        # The correction box blocks for as long as the user takes to type,
        # which is unbounded. It gets its own thread so a box left open over
        # lunch cannot hold up a dictation or a translation.
        self.correct_queue: queue.Queue[dict] = queue.Queue()
        self._correcting = threading.Event()
        self.correct_worker = threading.Thread(
            target=self._correct_worker, daemon=True, name="correct-worker")
        # The lookup key gets its own queue and its own thread rather than
        # joining text_queue, and the reason is the same one that put those
        # two together: what must not overlap is the CLIPBOARD. A lookup
        # borrows it for a measured 20 ms and then wants 1-3 s of model
        # time it owes nobody — sharing the text queue would make a
        # translation wait out a lookup's model call for nothing, and make
        # a lookup wait out a translation's. So it queues separately and
        # takes _cursor_lock around its capture only (see _lookup).
        # (window, anchor): where the text is, and where on screen the
        # user was pointing when they asked. Both are read on the hook
        # thread, because both are only true at the moment of the press.
        self.lookup_queue: queue.Queue[
            tuple[int, tuple[int, int] | None]] = queue.Queue()
        self._looking_up = threading.Event()
        self._lookup_engine = None
        self.lookup_worker = threading.Thread(
            target=self._lookup_worker, daemon=True, name="lookup-worker")
        # One Whisper model, several threads that want it (the desktop
        # worker, and every phone request).
        self._model_lock = threading.Lock()
        # THE CURSOR, wanted by four threads: the dictation worker, the
        # translate/punctuate worker, the correction worker and the control
        # thread. They could previously only collide by bad luck of timing
        # and mostly did not, which is not the same as being safe — a
        # translate that grabs the field while a transcript is being pasted
        # into it corrupts both.
        #
        # It used to say "and one clipboard" as well, and that half was
        # never true: capture.py writes a screenshot from a thread of its
        # own, the lookup box copies from another, and neither has ever
        # heard of this lock. The clipboard is now serialised where its
        # borrowers actually are — injector._board_lock, which every module
        # that touches the clipboard goes through. This one is about the
        # CARET: who may send keystrokes at the focused window.
        self._cursor_lock = threading.Lock()
        # The only thing on screen once loading is done: a dot that says
        # the app is alive, and what it is doing. Its corner ([dot]
        # corner, bottom-right of the work area since 2026-09-07) is the
        # one every card beside it is placed against — getattr, so a
        # config.py without [dot] (classic) gets the default.
        #
        # THE CORNER IS STILL READ ONCE; WHERE THE DOT SITS IS NOT. `[dot]
        # x/y` is where it was dragged to, and the dashboard's "Move the
        # dot" arms another drag down the control pipe while the app runs
        # — which is the whole of the owner's complaint on 2026-09-07,
        # "without needing to open and close the app".
        #
        # AND SINCE 2026-09-08 THE CARDS BESIDE IT GO WITH IT. "I want it
        # to be able to move where the dot is", said of the panel the dot
        # opens, so a card whose file said `corner = "dot"` is handed
        # `_dot_beside` and opens beside the dot wherever it actually is;
        # a card that named a corner of its own keeps that corner. The
        # corner is still what both use until the dot has been dragged.
        dcfg = getattr(cfg, "dot", None)
        self._dot_corner = str(getattr(dcfg, "corner", "bottom-right"))
        self.dot = (overlay_mod.StatusDot(
            corner=self._dot_corner,
            x=getattr(dcfg, "x", overlay_mod.HINT_UNSET),
            y=getattr(dcfg, "y", overlay_mod.HINT_UNSET),
            on_change=self._save_dot)
            if cfg.indicator else overlay_mod.StatusDot.off())
        # No dot at all while there is no model (a start without one:
        # the flag is read at the painter's first frame, so nothing
        # flashes). dev/user_sim.py caught this line sitting 140 lines
        # too early, before the dot existed — every --no-model start
        # would have died in __init__.
        self.dot.hidden = not self._model_wanted
        # THE DISC IS A BUTTON. A click on it does exactly what ctrl+alt+d
        # does — _tap_shelf reads one flag and starts a thread, which is
        # the whole reason it may be called from the dot's own thread.
        # The glow around the disc stays click-through (skin\dot.Dot.hit).
        self.dot.on_click = self._tap_shelf
        # And, for the press someone hesitated on, a card naming what the
        # keys will do. Off by config, and off by construction the rest of
        # the time: nothing is on screen until a key has been held for
        # hint.after_ms, which an ordinary dictation never reaches.
        self.hint = (overlay_mod.HintCard(
            cfg.hint.after_ms, cfg.hint.corner, x=cfg.hint.x, y=cfg.hint.y,
            scale=cfg.hint.scale, on_change=self._save_hint,
            dot_corner=self._dot_corner,
            dot_at=self._dot_beside
            if getattr(cfg.hint, "follow_dot", True) else None)
            if cfg.hint.enabled else overlay_mod.HintCard.off())
        # And the second reading's card (review.py): one proposal, three
        # buttons, a clock. Off by config, and off by construction until a
        # reading has something to say — see _review_show. Built like the
        # hint card: getattr, so a config.py without [review] (classic)
        # gets the inert one.
        rcfg = getattr(cfg, "review", None)
        self.review_card = (overlay_mod.ReviewCard(
            rcfg.corner, x=rcfg.x, y=rcfg.y, scale=rcfg.scale,
            on_change=self._save_review_card,
            on_verdict=self._review_verdict, seconds=rcfg.card_seconds,
            keys={"accept": rcfg.accept_key, "reject": rcfg.reject_key,
                  "later": rcfg.later_key,
                  "edit": getattr(rcfg, "edit_key", "e")},
            on_edit=self._review_edit)
            if rcfg is not None and rcfg.enabled and rcfg.card_seconds > 0
            else overlay_mod.ReviewCard.off())
        # The consent card (consent_card.py, privacy.py): asks ONCE per
        # kind, on the first key press that needs a cloud pass while its
        # gate is shut, and never from a warm-up. Built like the others,
        # off when Tk is missing; privacy.py is handed its `show`.
        self.consent_card = overlay_mod.ConsentCard(
            on_answer=self._consent_answered)
        privacy.set_asker(self.consent_card.show)
        # The tour (tour_card.py, D36): the guide itself — four callouts
        # beside the dot after the wizard, once, and again from Settings
        # > The app. Handed the dot's rect whether or not it was dragged:
        # this card points AT the dot, so the corner rule would put it
        # beside nothing. The key's name is the picture on stop 2.
        self.tour_card = overlay_mod.TourCard(
            dot_at=lambda: getattr(self.dot, "rect", None),
            key=hint_mod.pretty(cfg.hotkey), on_end=self._tour_ended)
        # The notification card and its engine (notify.py). The card class
        # is looked up rather than named: it lands with the card package,
        # and until then — or on a branch without it — the engine gets the
        # inert card and everything else (route, store, log, key) works.
        ncfg = getattr(cfg, "notify", None)
        card_cls = getattr(overlay_mod, "NotifyCard", None)
        if card_cls is not None and ncfg is not None and ncfg.enabled:
            fields = dict(
                x=ncfg.x, y=ncfg.y, scale=ncfg.scale,
                on_change=self._save_notify_card,
                on_dismiss=self._notify_dismissed,
                on_open=self._notify_opened,
                seconds=ncfg.card_seconds,
                anchor=getattr(ncfg, "anchor", "bottom"))
            # `anchor` lands with the card package (2026-09-04) — which
            # edge stays put as the column grows. A card class from
            # before it takes no such argument, so it is OFFERED and
            # withdrawn if the signature has no room for it, rather than
            # assumed the way `seconds` can be.
            try:
                takes = inspect.signature(card_cls).parameters
            except (TypeError, ValueError):
                takes = {}
            if takes and "anchor" not in takes:
                fields.pop("anchor")
                log.info("notify card: this overlay takes no anchor — the "
                         "column will grow downward")
            self.notify_card = card_cls(ncfg.corner, **fields)
        else:
            self.notify_card = notify_mod.NullCard()
        self.notify = notify_mod.Engine(paths.DATA_DIR, ncfg, cue=beep,
                                        card=self.notify_card,
                                        store_path=paths.NOTIFY_FILE,
                                        log_path=paths.NOTIFY_LOG)
        # The half of Claude that cannot knock (notify_watch.py). A Cowork
        # session runs in Anthropic's cloud, so there is no hook on this
        # machine to install for it — but the desktop app raises a Windows
        # toast when one wants him, and Windows writes every toast down.
        # The sink is the /notify route's own callable, so a toast and a
        # POST reach the engine by the same road and are stored, cued and
        # reminded about identically. Off with the whole door.
        self.notify_watch = notify_watch_mod.Watcher(
            self._notify_from_outside,
            getattr(ncfg, "watch", "cowork")
            if ncfg is not None and ncfg.enabled else "off")
        # The pencil's box: one line, takes the keyboard, on purpose.
        self._word_prompt = overlay_mod.WordPrompt()
        # The report card (problem_card.py, painted; overlay.ProblemCard,
        # shown). Its OWN object and never the pencil's: the two windows
        # ask different questions with different signatures, and a report
        # opening must not be able to close a word box he is in the middle
        # of. Looked up rather than named, the way NotifyCard is — the
        # class lands with the card package, and until then the key says
        # so instead of raising.
        #
        # Built with where it was last dragged to and a callback to write
        # the next drag down, which is the hint/review/notify shape. x and
        # y through getattr: they land with the config half of this
        # feature, and HINT_UNSET is the "never moved" sentinel every
        # other card here uses — a number no desktop can reach, because a
        # monitor left of the primary has genuinely negative coordinates
        # and -1 would throw a real position away.
        card_cls = getattr(overlay_mod, "ProblemCard", None)
        unset = getattr(config_mod, "HINT_UNSET", -100000)
        self._problem_card = None if card_cls is None else card_cls(
            x=int(getattr(pcfg, "x", unset) if pcfg is not None else unset),
            y=int(getattr(pcfg, "y", unset) if pcfg is not None else unset),
            on_change=self._save_problem_card,
            # "Send to the developer" is behind the report_upload gate
            # (D7, plan 7.6): the box asks its consent card first.
            allowed=lambda: privacy.allowed("report_upload"),
            consent=lambda: privacy.request("report_upload"))
        # THE SHELF (shelf.py + shelf_card.py + skin\shelf.py): the panel
        # beside the dot that one key opens, listing everything waiting
        # for an answer with its own two answers on every row.
        #
        # Imported HERE and not at the top of the file, in a try/except,
        # for the reason every optional card in this app is looked up
        # rather than named: the module lands with its own half of the
        # feature, `classic`'s Config has no [shelf] section at all, and a
        # missing painter must cost one log line rather than a process
        # that will not start. It also keeps Pillow out of the import
        # graph of an app started with [shelf] enabled = false.
        self.shelf = None
        scfg = getattr(cfg, "shelf", None)
        if scfg is not None and scfg.enabled:
            try:
                import shelf as shelf_mod
                self.shelf = shelf_mod.ShelfCard(
                    corner=scfg.corner, x=scfg.x, y=scfg.y, scale=scfg.scale,
                    rows=getattr(scfg, "rows", 5),
                    on_change=self._save_shelf_card,
                    on_press=self._shelf_pressed,
                    on_refresh=self._shelf_refresh,
                    on_away=self._shelf_close,
                    spare=self._dot_squares,
                    dot_corner=self._dot_corner,
                    dot_at=self._dot_beside
                    if getattr(scfg, "follow_dot", True) else None)
            except Exception:                    # noqa: BLE001
                log.info("the shelf would not build — its key will say so "
                         "and nothing else changes", exc_info=True)
                self.shelf = None
        # Armed by the first press of Stop on the panel and cleared by
        # anything else, so the second press is the one that quits. Read
        # and written only from the shelf's own callbacks.
        self._shelf_stop_armed = False
        # The four store stamps the panel was last built from. The
        # refresh compares these before it reads anything at all — see
        # _shelf_refresh.
        self._shelf_stamp: tuple = ()
        self._review = None
        # The decoder's per-word confidence for the LAST live transcription,
        # read under the model lock in _transcribe and written into the
        # recording's sidecar for the second reading.
        self._last_words: list = []
        # And the stretches the LAST live transcription was joined from
        # (rolling.py), [] when it was decoded whole — for the repair pass
        # to skip the ones already repaired while the key was held.
        self._last_windows: list = []
        self.phone: server_mod.PhoneServer | None = None
        if cfg.server.enabled:
            self.phone = server_mod.PhoneServer(
                cfg, self._transcribe_for_phone,
                lambda: self.transcriber.name,
                self._translate_for_phone,
                self._punctuate_for_phone,
                self._notify_from_outside,
                review_pending=self._review_pending_for_phone,
                review_decide=self._review_decide_for_phone,
                lookup=self._lookup_for_phone)

    @property
    def vqa(self):
        """The ask-the-screen controller, built on first touch."""
        vqa = getattr(self, "_vqa", None)
        if vqa is None:
            import visual_qa as visual_qa_mod
            # A callable, not the object: keys move through rebind() and
            # every use should read what config.toml says NOW.
            #
            # `recording_now` is the card's answer to "may I read this
            # out?". It has to come from here because main.py owns the
            # recorder, and it has to exist at all because the card can now
            # be opened in the MIDDLE of a dictation aimed at somewhere
            # else — the one case where the card has not been told the
            # microphone is live and would happily speak into it.
            vqa = visual_qa_mod.Controller(
                lambda: self.cfg, recording_now=self._recording_now,
                on_closed=self._on_card_closed)
            self._vqa = vqa
        return vqa

    @property
    def capture(self):
        """The screenshot / screen-recording controller, built on first
        touch.

        The ask card is handed in as a CALLABLE rather than as an object.
        The editor's Ask button needs it, [visual_qa] may be switched off
        entirely, and building one here would drag Tk and a vision chain
        into a press that only wanted a png.

        `hush_overlays` is handed in for a different reason: capture.py
        must not import overlay.py. main.py is the only thing that holds
        both, so main.py is where the wire goes. See _hush_overlays.
        """
        controller = getattr(self, "_capture", None)
        if controller is None:
            import capture as capture_mod
            controller = capture_mod.Controller(
                lambda: self.cfg, ask_provider=self._ask_card,
                hush_overlays=self._hush_overlays)
            self._capture = controller
        return controller

    def _hush_overlays(self, on: bool) -> None:
        """Take our topmost cards off the live screen for the length of a
        screenshot selection, and put them back.

        THIS IS THE HALF THAT KEEPS DROPPING WDA_EXCLUDEFROMCAPTURE FROM
        BECOMING A BUG. Those cards used to carry the flag, so they were
        absent from the frozen desktop the selector paints itself with and
        could never be in the way. Since 2026-09-04 they are in the
        picture — which is what the owner asked for — and the thing that
        keeps them out of the DRAG is the order: capture's `_shot_flow`
        freezes the desktop, calls this one line later, and only then maps
        the selector. A card already up is underneath the selector because
        the selector mapped last; a card that ARRIVES mid-drag is the real
        race, and hushed cards refuse to map at all.

        Each card owns its own Tk interpreter on its own thread, so
        `hush()`/`unhush()` do nothing but set an Event — no Tk object is
        touched from here, which is the rule in AGENTS.md that costs a
        day every time it is broken. Cheap enough for the keyboard hook.
        """
        for name in ("notify_card", "review_card", "consent_card", "hint",
                     "shelf", "tour_card"):
            card = getattr(self, name, None)
            if card is None:
                continue
            try:
                card.hush() if on else card.unhush()
            except Exception:
                log.debug("could not %s %s", "hush" if on else "unhush",
                          name, exc_info=True)

    def _ask_card(self):
        """The ask-the-screen controller, or None when it is switched off."""
        vqa_cfg = getattr(self.cfg, "visual_qa", None)
        if vqa_cfg is None or not vqa_cfg.enabled:
            return None
        return self.vqa

    @staticmethod
    def bindings(cfg: config_mod.Config):
        """config -> (hold hotkeys, tap keys, latch vk, pause vk).

        One place, because it is needed twice — at construction and again
        every time a key is moved — and two copies of it would drift the
        first time a key was added.

        Only the taps go through parse_binding, and that asymmetry is the
        point: a tap is a key you strike, so "ctrl+f8" is a sentence the
        state machine can watch for. The other three are not struck. The
        hold hotkey is held down for as long as you speak, the latch is a
        toggle and the pause key another — a modifier in front of any of
        them describes a moment, not a duration, so vk_for stays there and
        config.check_hotkeys refuses the chord before it ever reaches
        here.
        """
        # None means "no language declared — let the transcriber decide",
        # which is exactly what the backends already read an unset language
        # as. An English key, when there is one, still declares itself.
        hotkeys = {vk_for(cfg.hotkey): None if cfg.auto_language else "he"}
        if cfg.english_hotkey:
            hotkeys[vk_for(cfg.english_hotkey)] = "en"
        taps = {}
        if cfg.translate_hotkey:
            taps[parse_binding(cfg.translate_hotkey)] = "translate"
        if cfg.punctuate_hotkey:
            taps[parse_binding(cfg.punctuate_hotkey)] = "punctuate"
        if cfg.correct_hotkey:
            taps[parse_binding(cfg.correct_hotkey)] = "correct"
        if cfg.lookup_hotkey:
            taps[parse_binding(cfg.lookup_hotkey)] = "lookup"
        # The kill switch is [visual_qa] enabled = false: no key, no tap,
        # nothing anywhere in the state machine. getattr, not an attribute
        # read: classic's Config has no visual_qa section at all, and this
        # one file is byte-identical on both branches (the shared-half
        # test enforces it) — on classic this line registers nothing.
        vqa = getattr(cfg, "visual_qa", None)
        if vqa is not None and vqa.enabled and vqa.hotkey:
            taps[parse_binding(vqa.hotkey)] = "visual_qa"
        # Same getattr, same reason: [capture] does not exist on classic's
        # Config and this file is byte-identical on both branches. There
        # these two lines register nothing at all.
        cap = getattr(cfg, "capture", None)
        if cap is not None and cap.enabled:
            if cap.hotkey:
                taps[parse_binding(cap.hotkey)] = "capture"
            if cap.record_hotkey:
                taps[parse_binding(cap.record_hotkey)] = "record"
        # And the lens, on the same terms and for the same reason: getattr
        # because classic's Config has no [camera] section, and this file
        # is byte-identical on both branches.
        cam = getattr(cfg, "camera", None)
        if cam is not None and cam.enabled and cam.hotkey:
            taps[parse_binding(cam.hotkey)] = "photo"
        # The screens key, on the same terms: [awake] enabled = false
        # unregisters it, and the dashboard's button still works.
        awake = getattr(cfg, "awake", None)
        if awake is not None and awake.enabled and awake.hotkey:
            taps[parse_binding(awake.hotkey)] = "screens"
        # The dismiss key, on the same terms again: [notify] enabled =
        # false unregisters it, and a click on the card still works.
        ncfg = getattr(cfg, "notify", None)
        if ncfg is not None and ncfg.enabled and ncfg.hotkey:
            taps[parse_binding(ncfg.hotkey)] = "notify_dismiss"
        # The report key, on the same terms: [problems] enabled = false
        # unregisters it and the dashboard's own form still files one.
        # `hotkey` through getattr as well, not just the section — the key
        # is landing with the config half of this feature and a Config
        # built before it has the section without the field.
        pcfg = getattr(cfg, "problems", None)
        if pcfg is not None and pcfg.enabled and getattr(pcfg, "hotkey", ""):
            taps[parse_binding(pcfg.hotkey)] = "problem_report"
        # The shelf key, on the same terms: [shelf] enabled = false
        # unregisters it and there is then no way to open the panel at
        # all, which is what that line is for. getattr on both the
        # section and the field, because this file is byte-identical on
        # the classic branch and that Config has neither.
        scfg = getattr(cfg, "shelf", None)
        if scfg is not None and scfg.enabled and getattr(scfg, "hotkey", ""):
            taps[parse_binding(scfg.hotkey)] = "shelf"
        return (hotkeys, taps,
                vk_for(cfg.latch_hotkey) if cfg.latch_hotkey else None,
                vk_for(cfg.pause_hotkey) if cfg.pause_hotkey else None)

    @staticmethod
    def _vk_of(taps: dict, action: str) -> int | None:
        """Which key a tap action is on right now, read back out of the map
        bindings() just built — so there is still one place that decides
        it, and moving a key from the dashboard cannot leave a stale copy
        of the answer behind.

        The TRIGGER, not the whole binding, because the one caller
        (_popup_key) is handed a raw vk by the hook and has nothing to
        compare a chord against. That is the right answer for it anyway:
        the question there is "did the key that asks the question just go
        down", and ctrl+F8 puts F8 down exactly as bare F8 does. A plain
        int key is still accepted so that a caller which never learned
        about chords — tests.py binds taps={VK_F9: ...} — keeps working.
        """
        return next((getattr(key, "trigger", key)
                     for key, name in taps.items() if name == action), None)

    def _copy_text(self, text: str) -> None:
        """Put text on the clipboard from a thread of its own, and say so
        if it fails. The dashboard has already been told the copy was
        made, so a failure has to reach the user somewhere — the log and
        the dashboard's own note line are where every other clipboard
        failure in this app is reported."""
        try:
            injector.set_text(text)
        except Exception as e:
            beep("error")
            self._say(f"could not copy the last dictation: {e}")
            log.warning("could not copy the last dictation: %s", e)

    def _recording_now(self) -> bool:
        """Is the microphone capturing this instant?

        Asked by the ask card before it reads an answer aloud. The
        recorder's own meter, whose second value is exactly this question
        and which is documented as safe from any thread — two attribute
        reads, no lock, never blocks.
        """
        try:
            return bool(self.recorder.meter()[1])
        except Exception:
            return False

    def _ask_card_open(self) -> bool:
        """Is the ask card on screen? Asked by the state machine to decide
        what the dictation hotkey MEANS right now.

        Off the already-built controller and never through the `vqa`
        property: this runs inside the keyboard hook, where building one
        would import Tk and Pillow and drop the hook.
        """
        vqa = getattr(self, "_vqa", None)
        return bool(vqa is not None and vqa.sink_active)

    def _on_ask_start(self, language: str | None = "he") -> None:
        """The hotkey went down with the ask card up and a dictation
        LOCKED. Remember where in that recording the question starts.

        Runs inside the keyboard hook: one call and one assignment.
        """
        self._ask_mark = self.recorder.mark()
        # A question is about to be cut out of, or noted in, the recording
        # the rolling transcriber is reading: its windows no longer line
        # up with what end_pieces will hand over. The whole recording
        # goes the old way — cut at the questions and spliced.
        roller = getattr(self, "_roller", None)
        if roller is not None:
            roller.invalidate()
        vqa = getattr(self, "_vqa", None)
        if vqa is not None:
            vqa.notify_recording(level=self.recorder.meter)

    def _on_ask_stop(self, language: str | None = "he") -> None:
        """The question is finished. Hand the card a COPY of it.

        THE RECORDING IS NOT ENDED. slice_since reads the frames and
        mutates nothing, so the words just spoken are both the question
        the card is about to answer AND part of the sentence still being
        dictated underneath. When the latch is finally tapped, all of it —
        before the card, into the card, after the card — lands as one
        continuous paste, which is the whole point.

        The dot is deliberately NOT moved to amber here: the locked
        recording never stopped, and a dot that said "transcribing" would
        be describing something that is not happening to it.
        """
        mark, self._ask_mark = self._ask_mark, 0
        wav, seconds = self.recorder.slice_since(mark)
        vqa = getattr(self, "_vqa", None)
        if vqa is not None and not vqa.echoing:
            # The switch in the card's title strip, and the only thing it
            # CAN mean here. The question is already inside the recording
            # — one microphone, no second channel — so "keep this out of
            # what I am writing" has to be done by leaving those frames
            # out of the utterance when it is finally assembled.
            self.recorder.exclude_since(mark)
            log.info("that question stays in the card — it will not be in "
                     "the dictation when it lands")
        else:
            # It stays in the dictation, and the dictation is cut here so
            # this stretch is never handed to Whisper twice — the text
            # transcribed NOW, on its own, is the one that survives. See
            # recorder.note_question for why that matters.
            self.recorder.note_question(mark)
        if not wav:
            log.info("nothing was said to the card — the dictation "
                     "underneath is still running")
            return
        # to_card=True routes it into the card and never to the cursor.
        # sliced=True says it is already inside a recording that will be
        # pasted later, so it must not ALSO be echoed; in_stream says that
        # recording is going to keep it, so its text is worth remembering
        # for the splice.
        in_stream = bool(vqa is not None and vqa.echoing)
        self.queue.put((wav, seconds, 0, language, True,
                        {"sliced": True, "in_stream": in_stream}))

    def _on_card_closed(self) -> None:
        """The ask card is gone: give the field back what was said to it.

        A question dictated INTO the card went to the card and nowhere
        else, which is right when the card is the whole errand. It is
        wrong when the card was opened in the MIDDLE of writing to
        somebody — the usual way it gets opened — because then those
        sentences are also part of what was being written, and the owner
        finds them only in transcripts.log, which is not where he was
        typing. [visual_qa] echo_to_field is that repair.

        WHY IT WAITS FOR THE CLOSE. The card holds the foreground for as
        long as it is up, so there is no such thing as pasting into the
        field "at the same time": the text would land in the card itself,
        or tear the foreground off it in the middle of a question. The
        close is the first moment the field is reachable again.

        Runs on the visual-qa thread, after that thread has buried the
        card (see visual_qa.Controller._closed). It is handed nothing and
        reads nothing off the window, deliberately — a reference kept past
        that burial is the Tcl_AsyncDelete abort in AGENTS.md.
        """
        with self._echo_lock:
            lines, hwnd = self._echo_lines, self._field_hwnd
            self._echo_lines = []
        if not lines:
            return
        # One paste, not one per question: they were consecutive sentences
        # in the same breath as far as the field is concerned.
        text = " ".join(lines)
        # The foreground does not come back the instant the card is
        # destroyed — Windows hands it on when it is ready. A second is
        # far longer than that takes, and still short enough that somebody
        # who deliberately clicked elsewhere is not left waiting.
        deadline = time.monotonic() + 1.0
        while hwnd and time.monotonic() < deadline:
            if injector.foreground_window() == hwnd:
                break
            time.sleep(0.03)
        try:
            with self._cursor_lock:
                if hwnd and injector.foreground_window() == hwnd:
                    injector.inject(text, self.cfg.paste_chord,
                                    self.cfg.restore_delay_ms)
                    log.info("what you asked the screen is back in the "
                             "field you were writing in (%d chars)",
                             len(text))
                    return
                # Focus went somewhere the owner chose. The clipboard is
                # where every other homeless transcript in this module
                # goes, and it says so out loud rather than dropping it.
                injector.set_text(text)
                beep("stop")
                log.warning("the field you were writing in is not in front "
                            "any more — what you asked the screen is on "
                            "your clipboard, press %s to paste it (%d chars)",
                            self.cfg.paste_chord, len(text))
        except Exception as e:
            log.warning("could not hand the field back what you asked the "
                        "screen (%s) — it is in transcripts.log", e)

    def _tap_allowed(self, action: str, state: str) -> bool:
        """May this feature key fire while a dictation is running?

        The keyboard splits in two, and the split is about what a key
        TOUCHES rather than about how important it is.

        The four SCREEN keys — ask-the-screen, screenshot, screen
        recording, camera — take pixels. At the moment of the press they
        want no hands, no caret and no clipboard, so they are exactly as
        true mid-sentence as they are at rest. That is the whole of what
        the owner asked for: keep talking and ask about the screen at the
        same time.

        The four TEXT keys — translate, punctuate, correct, lookup — read
        or rewrite whatever is selected AT THE CURSOR, and the cursor is
        where the transcript now being recorded is about to land.

        - LATCHED they are allowed, and this is not a concession. Latching
          exists so the hands are free; `_cursor_lock` already serialises
          every one of those workers against the paste (see its comment),
          and each already refuses itself with a cue while one of its own
          kind is in flight. Refusing here would be inventing a
          restriction the machine does not actually have.
        - HELD they are not. One hand is pinned to Right Ctrl, so there is
          no selection to act on and nothing for them to do; a key
          arriving in that state is far more likely to be a slip than a
          request. It is refused OUT LOUD, because the alternative — a key
          that silently does nothing — is what "the button disappeared"
          felt like in the first place.

        Runs on the keyboard hook thread. Two set lookups and a cue that
        is already used from here by every _tap_* method.
        """
        if state != hotkey_mod.RECORDING or action in _SCREEN_ACTIONS:
            return True
        self._cue_once("noop", f"held-{action}")
        log.info("'%s' needs the text at the cursor, and the cursor is "
                 "where this dictation is going — let go of the key, or "
                 "latch it, and press it again", action)
        return False

    def _esc_is_claimed(self) -> bool:
        """Is Escape spoken for by something already on screen?

        Asked by the state machine, and only about a LOCKED recording,
        where Esc means "throw the last few minutes of speech away". The
        surfaces this app can now put up mid-dictation — the region
        selector, the capture overlay, the clip bar, the camera, the ask
        card — are all dismissed with Esc too, and one keystroke must not
        do both.

        THE QUESTION IS WHO HAS THE FOREGROUND, not who is busy. Asking
        the controllers was the obvious first answer and it was wrong in
        both directions, measured: `capture.busy` stays set through the
        post-shot toast (5 s) and the clip toast (7 s of encode, copy and
        card), and neither of those reads Escape or takes focus — so for
        twelve seconds after a screenshot, Esc silently stopped being the
        way out of a locked recording, with nothing consuming it and
        nothing logged. Focus is the honest question: a key goes to the
        window that has it, and every overlay here that reads Escape is
        one that took the foreground to do it. Two syscalls, no
        bookkeeping to get out of step, and it is right for windows that
        do not exist yet.

        The lookup box is the exception it always was — it never takes
        focus, which is what lets it appear over a web page — so it is
        asked separately. In practice `_popup_key` has already swallowed
        that Esc before this is reached; the check is here so the box does
        not depend on which of its two doors answers first.

        Runs on the hook thread, so nothing here may build anything or
        block: no controller is touched at all now, and the popup is a
        plain window-visibility read.
        """
        try:
            if injector.is_our_window(injector.foreground_window()):
                return True
        except Exception:
            pass
        try:
            return bool(self.popup.visible())
        except Exception:
            return False

    def _popup_key(self, vk: int) -> bool:
        """Every key-down on this machine, offered to the lookup box.

        The box never takes focus, so it never receives WM_KEYDOWN and the
        hook is the only thing in the process that can see a keystroke —
        see PTTStateMachine. True swallows the key, and the box asks for
        two of them: Esc, which closes it, and Ctrl+C, which copies the
        selection in it. Everything else passes through untouched — a box
        that closed on any keystroke meant you could not press Shift while
        reading an answer, and the owner read that as the box vanishing at
        random.

        WHICH keys those are is deliberately not decided here. popup.py
        owns that, because the conditions are its own: whether anything is
        selected, whether the window in front is still the one the
        selection was made in, whether that window is a console. This
        function's whole job is to keep the pipe open, and the one thing
        it does decide is the exception below.

        The lookup key is still kept away from the box, and the reason has
        changed. It used to be that a press had two jobs — close the box
        here, open a lookup there — and would have spent itself on the
        first. Now that press only ever means "look this up", so this is
        one integer comparison defending an invariant that main.py is the
        module responsible for: the key that asks the question must reach
        the code that answers it, whatever popup.py decides to swallow
        next. It is also the one collision to avoid when rebinding —
        bind lookup to C and popup.py never sees the Ctrl+C it would
        otherwise take, because this returns first.
        """
        # HIS HANDS, in one assignment, before anything else can go wrong.
        # This is the only place in the process that sees a real key-down
        # (see above: the boxes never take focus, so the hook is the only
        # witness), and it is therefore the only way the unsolicited
        # question card can know he is at the keyboard at all — the app can
        # sit perfectly idle while he writes an email in another window,
        # and that is exactly the moment not to jump in front of it. One
        # monotonic() and one store: no lock, no call that can raise, and
        # nothing that can be slow. This is the keyboard hook, where an
        # exception is a dropped hook and a frozen keyboard, and where 300
        # ms of work unhooks the app silently.
        self._q_last_key = time.monotonic()
        # The second reading's card first: its three keys are claimed only
        # while a card is up AND the pointer is on it (overlay.ReviewCard),
        # so this is a rect test and never eats a letter being typed.
        try:
            if self.review_card.on_key(vk):
                return True
        except Exception:
            pass
        # The notification card next, on the same terms: Esc, and only
        # while it is up with the pointer on it (overlay.NotifyCard).
        try:
            card = getattr(self, "notify_card", None)
            if card is not None and card.on_key(vk):
                return True
        except Exception:
            pass
        # The shelf last of the three, and with NO pointer gate — the one
        # deliberate difference. The two above arrive uninvited, so eating
        # a keystroke away from them would eat a letter somebody was
        # typing; the shelf was opened half a second ago by a deliberate
        # press, and while it is up Esc means "close it". Ordering it
        # after them keeps their more specific claim first. Returning True
        # here ends the event before the state machine's cancel_guard, so
        # this Esc can never also throw away a locked recording.
        try:
            card = getattr(self, "shelf", None)
            if card is not None and card.on_key(vk):
                return True
        except Exception:
            pass
        if self._lookup_vk is not None and vk == self._lookup_vk:
            return False
        if self._vqa_vk is not None and vk == self._vqa_vk:
            return False
        if self._capture_vk is not None and vk == self._capture_vk:
            return False
        if self._record_vk is not None and vk == self._record_vk:
            return False
        if self._camera_vk is not None and vk == self._camera_vk:
            return False
        return self.popup.on_key(vk)

    # ---- state the dashboard reads, and the cues it should not repeat ----

    @staticmethod
    def _fresh_stats() -> dict:
        return {"day": time.strftime("%Y-%m-%d"), "dictations": 0,
                "seconds": 0.0, "chars": 0, "latency": 0.0, "failures": 0,
                "translations": 0, "punctuations": 0, "learned": 0,
                "lookups": 0}

    def _bump(self, **deltas) -> None:
        """Counters for the dashboard. Rolled over at midnight rather than
        kept forever: "18 dictations today" answers a question someone
        actually has, and a total since install answers none."""
        with self._stats_lock:
            today = time.strftime("%Y-%m-%d")
            if self._stats["day"] != today:
                self._stats = self._fresh_stats()
            for name, amount in deltas.items():
                self._stats[name] = self._stats.get(name, 0) + amount

    def _learning_quiet(self) -> bool:
        """Is RIGHT NOW a moment the study engine may borrow the GPU?

        Ready and idle only: not recording, not transcribing, not paused
        (paused usually means a game owns this GPU), nothing queued and no
        text key mid-flight. The engine re-asks before every decode.

        The screen features are in the list now, and a screen RECORDING is
        the one that made it necessary: it encodes video for as long as it
        runs, and a study decode starting underneath it drops frames in a
        file the user cannot re-take. An ask card counts too — it is a
        vision model on the same card, and it is the feature most likely to
        be open while the app otherwise looks idle.

        Read through the already-built slots and never through the `vqa` /
        `capture` properties: those IMPORT their modules on first touch,
        and the study thread asking a question must not be what drags Tk
        and a video encoder into the process.
        """
        for name in ("_capture", "_vqa"):
            controller = getattr(self, name, None)
            if controller is None:
                continue
            try:
                if controller.busy or getattr(controller, "recording", False):
                    return False
            except Exception:
                return False
        return (self._activity == "ready"
                and self.queue.empty()
                and not self._text_busy.is_set()
                and not self._correcting.is_set()
                and not self._looking_up.is_set())

    def _learning_fingerprint(self) -> tuple:
        """Changes whenever the user does anything the stats can see.
        The study engine waits for this to sit still for [study]
        idle_minutes — a cheap read, polled every few seconds."""
        with self._stats_lock:
            counts = tuple(sorted(self._stats.items()))
        return (self._activity, counts)

    def _set_state(self, state: str) -> None:
        """What the dot shows, and what the dashboard reports in words.

        A LIVE RECORDING OUTRANKS "ready" AND "busy". `_activity` is one
        string written by several threads, and once feature keys can be
        pressed mid-dictation the transcription worker's closing
        `_set_state("ready")` — for the PREVIOUS dictation, or for a
        screen question asked over this one — lands on top of a recording
        that is still running and reports it as finished. The dot goes
        green while the microphone is live, which is the one lie this
        indicator must never tell, and `_learning_quiet` reads the same
        field to decide the GPU is free.

        Only those two are held back. "paused" and "locked" and
        "recording" are all statements about the recording itself and are
        allowed to overwrite each other in any order.
        """
        if state in ("ready", "busy") \
                and self.machine.state != hotkey_mod.IDLE:
            return
        # With the model off there is NO dot — his rule (2026-09-18): "no
        # dot in the corner if the model is not working" — however a
        # pause ends or a worker finishes. The word stays "paused" for
        # the dashboard's sake; the window is withdrawn (StatusDot.hide),
        # not grey.
        if getattr(self, "_model_state", "on") == "off":
            self._activity = "paused"
            self.dot.hide()
            return
        self._activity = state
        self.dot.set_state(state)
        # ONE PANEL OWNS THE DOT'S CORNER. Both cards default to it
        # ([dot] corner) and the shelf key is in _SCREEN_ACTIONS, so both
        # can be wanted at once; the one he asked for wins, and the hint
        # card comes back the moment the shelf closes (see _shelf_close).
        shelf = getattr(self, "shelf", None)
        up = False
        try:
            up = shelf is not None and shelf.visible()
        except Exception:                        # noqa: BLE001
            up = False
        if not up:
            # The card rides the same state, so it can never disagree with
            # the dot about whether a recording is live — including the
            # early return above, which is exactly the case where "ready"
            # is a lie.
            self.hint.show(self._hint_card(state))
        else:
            # A recording starting or stopping is the one thing on the
            # panel that must not wait for the refresh tick. ON A THREAD:
            # this method runs inside the keyboard hook (_on_start calls
            # it), and rebuilding the card reads four JSON stores — 2.3 ms
            # measured, and still not something to do in the 300 ms
            # Windows allows a hook before it unhooks the app silently.
            self._shelf_push()

    def _save_hint(self, fields: dict) -> None:
        """Write what the owner did to the card back into config.toml.

        Called from the overlay thread when a drag ends, a size button is
        pressed or the box is ticked. Everything goes through
        `config.set_values`, which is a line-wise edit that keeps the
        comments — a TOML round-trip here would delete the measurements
        the file is made of.

        The live Config is replaced too, so the dashboard and a later
        rebind read the same numbers this just saved rather than the ones
        the app started with.
        """
        self.cfg = dataclasses.replace(
            self.cfg, hint=dataclasses.replace(self.cfg.hint, **fields))
        self._save(
                              {f"hint.{k}": v for k, v in fields.items()})
        log.info("hint card: %s",
                 ", ".join(f"{k}={v}" for k, v in fields.items()))

    def _save_dot(self, fields: dict) -> None:
        """The status dot's twin of _save_hint: where it was dropped,
        written into [dot] through the same comment-keeping line edit.

        Called from the dot's own thread, the moment Windows' move loop
        lets go — and from the control thread for "Back to the corner",
        which writes the sentinel back into both lines. `x` and `y` are
        always written as a PAIR, because config.load refuses half a
        position, and they always are: the only caller is
        overlay.StatusDot._changed, which sends both.

        The guard is _save_problem_card's, for its reason: a config.py
        without x and y on DotConfig would make dataclasses.replace raise
        on a field the dataclass has not got, and a drag that cannot be
        remembered should still work for the rest of the run.
        """
        dcfg = getattr(self.cfg, "dot", None)
        known = {f.name for f in dataclasses.fields(dcfg)} if dcfg else set()
        missing = sorted(set(fields) - known)
        if missing:
            log.info("the dot: [dot] has no %s to save a drag in yet — it "
                     "stays where you put it for this run only",
                     ", ".join(missing))
            return
        self.cfg = dataclasses.replace(
            self.cfg, dot=dataclasses.replace(dcfg, **fields))
        self._save(
                              {f"dot.{k}": v for k, v in fields.items()})
        log.info("the dot: %s", ", ".join(f"{k}={v}" for k, v in
                                          fields.items()))

    def _save_review_card(self, fields: dict) -> None:
        """The review card's twin of _save_hint: where it was dragged to,
        written into [review] through the same comment-keeping line edit."""
        self.cfg = dataclasses.replace(
            self.cfg, review=dataclasses.replace(self.cfg.review, **fields))
        self._save(
                              {f"review.{k}": v for k, v in fields.items()})
        log.info("review card: %s",
                 ", ".join(f"{k}={v}" for k, v in fields.items()))

    # ---- notifications (notify.py) ----

    def _save_notify_card(self, fields: dict) -> None:
        """The notification card's twin of _save_review_card: where it
        was dragged to, written into [notify] through the same
        comment-keeping line edit."""
        self.cfg = dataclasses.replace(
            self.cfg, notify=dataclasses.replace(self.cfg.notify, **fields))
        self._save(
                              {f"notify.{k}": v for k, v in fields.items()})
        log.info("notify card: %s",
                 ", ".join(f"{k}={v}" for k, v in fields.items()))

    # ---- the bug list (problems.py) ----

    def _save_problem_card(self, fields: dict) -> None:
        """The report card's twin of _save_review_card: where it was
        dragged to, written into [problems] through the same
        comment-keeping line edit.

        One line more than its siblings, and it earns it. The other three
        sections have had x and y since before they were draggable; this
        one is having them added, and until that lands `dataclasses.replace`
        would raise TypeError on a field the dataclass has not got. The
        card's own instance keeps the position for the rest of the run
        either way, so what is lost meanwhile is the restart and not the
        drag. Negative values are written as they come: the card clamps
        against the whole virtual desktop, which starts at x = -1920 here.
        """
        pcfg = getattr(self.cfg, "problems", None)
        known = {f.name for f in dataclasses.fields(pcfg)} if pcfg else set()
        missing = sorted(set(fields) - known)
        if missing:
            log.info("report card: [problems] has no %s to save a drag in "
                     "yet — it stays put for this run only",
                     ", ".join(missing))
            return
        self.cfg = dataclasses.replace(
            self.cfg, problems=dataclasses.replace(pcfg, **fields))
        self._save(
                              {f"problems.{k}": v for k, v in fields.items()})
        log.info("report card: %s",
                 ", ".join(f"{k}={v}" for k, v in fields.items()))

    def _notify_dismissed(self, item_id=None) -> None:
        """The × on a card, or Esc over the column. The callback arrives
        on the card's Tk thread, and the engine's dismiss is a JSON write
        — so it goes to a thread of its own, and the card's pump is never
        made to wait on the disk.

        `item_id` is the card that was pressed, or None for the whole
        column (Esc, and every caller that predates the stack). It rides
        straight through to the engine, which decides what one id and no
        id each mean."""
        def work() -> None:
            engine = getattr(self, "notify", None)
            if engine is not None:
                engine.dismiss(item_id, by="card")
                self._say("notification dismissed" if item_id is not None
                          else "notifications dismissed")
        threading.Thread(target=work, daemon=True,
                         name="notify-dismiss").start()

    def _notify_opened(self, item_id=None) -> None:
        """A click anywhere on a card except its × (2026-09-04): go to
        whoever sent that one. Same thread rule as the dismissal above
        and for the same two reasons — the callback arrives on the
        card's own thread, and open() both writes notify.json and calls
        into user32; neither belongs in the painter's pump."""
        def work() -> None:
            engine = getattr(self, "notify", None)
            if engine is not None:
                engine.open(item_id, by="card")
                self._say("opening what sent it")
        threading.Thread(target=work, daemon=True,
                         name="notify-open").start()

    def _notify_from_outside(self, payload) -> dict:
        """The /notify route's callable: from an HTTP request thread,
        answered in milliseconds. ValueError (not an object) becomes the
        route's 400; anything else its 503."""
        engine = getattr(self, "notify", None)
        if engine is None:
            raise RuntimeError("notifications are off")
        return engine.receive(payload)

    # ---- the second reading (review.py) ----

    def _review_submit(self, kept, hwnd: int) -> None:
        """Hand a pasted recording to the second reading. From the
        transcribe worker, after the paste; only enqueues."""
        engine = getattr(self, "_review", None)
        if engine is None or kept is None:
            return
        try:
            engine.submit(kept, hwnd=hwnd,
                          card=self.cfg.review.card_seconds > 0)
        except Exception:
            log.exception("could not hand the recording to the second "
                          "reading")

    def _review_show(self, suggestion: dict) -> None:
        """A reading with something to say — the card goes up. From the
        review thread; the card only enqueues."""
        self.review_card.show(suggestion)

    def _review_verdict(self, sid: str, verdict: str) -> None:
        """A button on the card, or one of its keys. From the painter's
        thread or the hook's — so this only enqueues; the learning runs
        on the review thread."""
        engine = getattr(self, "_review", None)
        if engine is not None:
            engine.decide(sid, verdict, by="card")

    def _review_edit(self, sid: str, row: int, rect) -> None:
        """The pencil on the card: a box asks what the word should be.
        Enter accepts the proposal with that word — learned, and fixed in
        the field if it still holds the text — and Escape leaves it
        pending. From the card's thread; the box runs on its own."""
        engine = getattr(self, "_review", None)
        if engine is None:
            return
        item = engine.store.get(sid)
        changes = (item or {}).get("changes") or []
        if not item or row >= len(changes):
            return
        change = changes[row]
        initial = change.get("after") or change.get("before") or ""

        def done(text) -> None:
            if text is None:
                return                    # Escape: it stays a question
            engine.decide(sid, "accepted", by="pencil", edits={row: text})

        self._word_prompt.ask(initial, rect, done)

    def _review_fix(self, item: dict) -> None:
        """An accepted proposal, applied where the text was pasted — if
        it still is.

        The punctuation key's read-and-paste, with one more condition:
        the field must still contain the pasted text EXACTLY, because
        what gets pasted back is the field with that one substring
        swapped. A field that was edited since, a different window in
        front, a selection, or a document-sized field all mean "taught,
        not fixed" — the vocabulary learned the pair either way, and a
        card must never be the thing that rewrote a paragraph.

        On the review thread. The grab selects the whole field, so on
        every early exit after it the field is pasted back as it was —
        the selection would otherwise sit there waiting for the next
        keystroke to replace everything.
        """
        rcfg = self.cfg.review
        if not rcfg.fix_in_field:
            return
        hwnd = int(item.get("hwnd") or 0)
        pasted = (item.get("text") or "").strip()
        proposed = (item.get("proposed") or "").strip()
        if not hwnd or not pasted or not proposed or pasted == proposed:
            return
        if injector.foreground_window() != hwnd:
            log.info("review: the window the text went to is not in "
                     "front — taught, not fixed")
            return
        tcfg = self.cfg.translate
        if not self._cursor_lock.acquire(timeout=2.0):
            log.info("review: something else is working at the cursor — "
                     "taught, not fixed")
            return
        try:
            state = injector.snapshot()
            kept = injector.claim_mark()
            try:
                field, had_selection = injector.grab(
                    tcfg.copy_chord, tcfg.select_all_chord,
                    tcfg.settle_ms / 1000)
                usable = (not had_selection and field
                          and len(field) <= tcfg.max_chars
                          and pasted in field
                          and injector.foreground_window() == hwnd)
                if not usable:
                    if not had_selection and field:
                        injector.paste_text(field, self.cfg.paste_chord,
                                            self.cfg.restore_delay_ms)
                    log.info("review: the field no longer holds the pasted "
                             "text as it was — taught, not fixed")
                    return
                fixed = field.replace(pasted, proposed, 1)
                injector.paste_text(fixed, self.cfg.paste_chord,
                                    self.cfg.restore_delay_ms)
                transcript_log.info("REVIEW | fixed | %s || %s", pasted,
                                    proposed)
                log.info("review: fixed the text in the field: %s", proposed)
            finally:
                try:
                    injector.restore(state, "the fixed text", since=kept)
                except injector.ClipboardBusyError as e:
                    log.warning("could not restore your clipboard: %s", e)
        except injector.ClipboardBusyError as e:
            log.warning("review: could not read the field (%s) — taught, "
                        "not fixed", e)
        finally:
            self._cursor_lock.release()

    def _hint_card(self, state: str) -> dict | None:
        """The card for a dot state, or None for the states with no card.

        Rebuilt on every transition rather than cached because a rebind
        through the dashboard changes the keys under it, and the whole
        point of building it from the live Config is that it cannot go
        stale. Two dict comprehensions on the keyboard hook thread.
        """
        which = {"recording": hint_mod.HOLD, "locked": hint_mod.LATCHED}
        if state not in which:
            return None
        try:
            return hint_mod.card_for(self.cfg, which[state], _SCREEN_ACTIONS)
        except Exception:
            log.debug("could not build the hint card", exc_info=True)
            return None

    def _cue_once(self, kind: str, reason: str, every: float = 4.0) -> None:
        """Play a cue unless the same one just played for the same reason.

        The correction key is why this exists. Every one of its failure
        paths beeped, and the failures come in runs — the text it wants is
        not on screen, so pressing again cannot help, and pressing again is
        exactly what a person does when a key seems not to have worked.
        Measured in app.log on 2026-08-14: nine presses in five seconds,
        nine error cues, which is heard as one long fault rather than as
        nine identical answers to the same question.
        """
        now = time.monotonic()
        with self._cue_lock:
            if now - self._cue_last.get((kind, reason), -1e9) < every:
                return
            self._cue_last[(kind, reason)] = now
        beep(kind)

    def _say(self, message: str) -> None:
        """The one-line reason the dashboard shows. Logged too — this is a
        windowless app, and the log is the only other place it could go."""
        self._note = f"{time.strftime('%H:%M')}  {message}"

    def status(self) -> dict:
        """Everything the dashboard draws, in one reply.

        One command rather than several because it is polled: five round
        trips a second down a pipe to render one window would be silly, and
        a status assembled from five separate answers can show a paused app
        that is also recording.
        """
        with self._stats_lock:
            stats = dict(self._stats)
        with self._last_lock:
            last = dict(self._last) if self._last else None
        vocab_ready = sum(1 for c in self.vocab.corrections
                          if int(c.get("hits", 1))
                          >= self.cfg.vocab.replace_after_hits)
        return {
            "ok": True,
            "stage": "running",
            "paused": self.machine.paused,
            "auto_paused": self._auto_paused,
            "activity": "paused" if self.machine.paused else self._activity,
            "uptime_s": round(time.monotonic() - self._started_at, 1),
            "backend": self.transcriber.name,
            "model": self._model_state,
            "mic": self._mic_label,
            "keys": {name: getattr(self.cfg, name)
                     for name, _label in config_mod.HOTKEY_FIELDS},
            "auto_pause_fullscreen": self.cfg.auto_pause_fullscreen,
            "stats": stats,
            "note": self._note,
            # Deliberately NOT the transcript itself, and this outlived
            # the reason first given for it ("the dashboard cannot render
            # Hebrew anyway") — the dashboard now draws transcripts with
            # DrawTextW, exactly so it can (see dashboard.py's docstring
            # for the two measurements behind that). The remaining reason
            # is the better one: a latched hour-long dictation embedded
            # here would push every status poll past the pipe's message
            # buffer, and there is no reason to put what someone said
            # down a pipe several times a second. The dashboard shows the
            # sentence by reading transcripts.log, which it can do with
            # nothing running.
            "last": None if not last else {
                "when": last.get("when", ""),
                "chars": len(last.get("final", "")),
            },
            "vocab": {"corrections": len(self.vocab),
                      "automatic": vocab_ready,
                      "hotwords": (len(self.vocab.terms())
                                   if self.cfg.vocab.enabled else 0)},
            "pending": len(self.spool.pending()),
            "phone": (self.phone.url or "") if self.phone else "",
            # The sentence the Read aloud tab has up, and what came back
            # for it — text only, and short: one sentence each way.
            "read": self.reading.state(),
            # Where the dot is and whether it is waiting to be dragged.
            # The dashboard hides itself for a move and has to know when
            # the move is over; this poll is how it finds out, which is
            # also what puts the window back if the move times out
            # instead of ending in a drop.
            "dot": (self.dot.state()
                    if hasattr(getattr(self, "dot", None), "state")
                    else {"corner": "bottom-right", "dragged": False,
                          "moving": False}),
            # getattr: the test suite builds half-initialised Apps.
            "awake": (self.awake.state()
                      if getattr(self, "awake", None) is not None
                      else {"holding": False, "dark": False}),
            # Counts and the last title only — never a body; see
            # notify.Engine.state.
            "notify": (self.notify.state()
                       if getattr(self, "notify", None) is not None
                       else {"enabled": False, "unread": 0, "total": 0,
                             "reminding": False, "reminders_left": 0,
                             "card_up": False, "last": None}),
            # The account (sb.py, chapter 8 / screen 16): who is signed
            # in, whether a sign-in is waiting on the browser, the last
            # sync and its error — ids and words, never a token.
            "account": self._account_status(),
            "locked": self.locked(),
        }

    @staticmethod
    def _account_status() -> dict:
        try:
            import sb
            return sb.status()
        except Exception:                                    # noqa: BLE001
            log.debug("account status tripped", exc_info=True)
            return {"configured": False, "signed_in": False}

    # ---- pause ----

    def _on_pause(self, paused: bool) -> None:
        """Runs on the hook thread (pause key) or the control thread (the
        dashboard). Cheap on purpose: nothing is loaded or unloaded, which
        is the entire point of pausing rather than quitting."""
        if getattr(self, "_locking", False):
            # the lock taking hold: the box goes, the dot shows paused,
            # and the sign-in sentence is said by _lock, not this
            self.popup.hide()
            self._set_state("paused")
            return
        if not paused and self.locked():
            # the pause key, while locked: back to locked, and say why
            self._lock()
            return
        if not paused:
            self._auto_paused = False
        if paused:
            # Nothing takes this box down on its own any more — that is
            # the point of it — so pausing has to. This key exists so the
            # owner can start a game, and the fullscreen watcher calls it
            # for him; an always-on-top box left sitting over that game
            # would be exactly the intrusion pausing was asked to stop.
            self.popup.hide()
        self._set_state("paused" if paused else "ready")
        beep("paused" if paused else "resumed")
        if paused:
            self._say("paused — the keys do nothing until you resume")
            log.info("PAUSED — '%s' and the other keys are inert; the models "
                     "stay loaded, so resuming is instant%s", self.cfg.hotkey,
                     f". Tap '{self.cfg.pause_hotkey}' to resume"
                     if self.cfg.pause_hotkey else "")
        else:
            self._say("listening again")
            log.info("resumed — hold '%s' and speak", self.cfg.hotkey)

    def set_paused(self, paused: bool, auto: bool = False) -> bool:
        if not paused and self.locked():
            # the lock is not a pause: nothing resumes it but a sign-in
            self._say(self.LOCK_WORDS)
            return False
        changed = self.machine.set_paused(paused)
        if paused and changed:
            self._auto_paused = auto
        return changed

    # ---- the account lock (the owner's rule: no account, no dictation)

    LOCK_WORDS = ("sign in to use DeskIT — open the desk and press "
                  "Sign in with Google")

    def locked(self) -> bool:
        """No account on this PC while one is required (sb.REQUIRED and a
        configured project): every key stays inert and the phone is
        refused until a sign-in. One sign-in is remembered — the session
        blob — until Sign out, so the lock is met once per PC."""
        try:
            import sb
            return bool(sb.REQUIRED and sb.configured() and not sb.signed_in())
        except Exception:                                    # noqa: BLE001
            return False

    def _lock(self) -> None:
        """Hold the state machine paused, silently: no pause cue, no
        "paused" sentence — the sentence is the sign-in one. Re-asserted
        whenever something tries to resume (the pause key, the
        dashboard) and when the session goes away under the app."""
        self._locking = True
        try:
            self.machine.set_paused(True)
        finally:
            self._locking = False
        self._lock_held = True
        self._set_state("paused")
        self._say(self.LOCK_WORDS)
        log.info("locked: no account on this PC — %s", self.LOCK_WORDS)

    def _unlock(self) -> None:
        """A sign-in landed: the keys come back, with the resume words."""
        if getattr(self, "_lock_held", False) and not self.locked():
            self._lock_held = False
            self.machine.set_paused(False)

    def _watch_fullscreen(self) -> None:
        """Pause while a game owns the screen; resume when it lets go.

        SHQueryUserNotificationState is the question Windows already
        answers for its own notifications — "would showing something on top
        of this be rude" — which is exactly the question being asked here,
        and it needs no window enumeration or per-game special cases.

        Acts on the EDGE, not the level: it pauses when the screen is taken
        and then keeps quiet, rather than re-pausing every two seconds for
        as long as the game is up. Level-triggered, it would undo a manual
        resume within one tick — so tapping the pause key to dictate into
        game chat would give a resume cue, a two-second window, and then a
        pause cue and dead keys, with the recording in flight thrown away.
        Dictating inside a fullscreen game is precisely what the pause key
        exists to make possible.

        Only ever undoes ITS OWN pause, for the mirror-image reason: a
        manual pause during a game must survive alt-tabbing out of it.
        """
        QUNS_BUSY, QUNS_D3D_FULLSCREEN, QUNS_PRESENTATION = 2, 3, 4
        shell32 = ctypes.windll.shell32
        was_busy = False
        while not self._stopping.wait(2.0):
            # Checked every round rather than at start-up: the setting has
            # a checkbox in the dashboard, and a thread that only read it
            # once would go on pausing games after it was turned off.
            if not self.cfg.auto_pause_fullscreen:
                was_busy = False        # re-arm if it is switched back on
                continue
            try:
                state = ctypes.c_int(0)
                if shell32.SHQueryUserNotificationState(ctypes.byref(state)):
                    continue        # non-zero HRESULT: leave things alone
                busy = state.value in (QUNS_BUSY, QUNS_D3D_FULLSCREEN,
                                       QUNS_PRESENTATION)
            except Exception as e:
                log.info("fullscreen watch stopped (%s)", e)
                return
            if busy and not was_busy and not self.machine.paused:
                log.info("a fullscreen app took the screen — pausing")
                self.set_paused(True, auto=True)
            elif not busy and self._auto_paused:
                log.info("the fullscreen app let go — resuming")
                self.set_paused(False)
            was_busy = busy

    # ---- changing the keys while it runs ----

    def rebind(self, field: str, key: str) -> str:
        """Move one key, live. Returns a sentence for the dashboard.

        Applied to the running hook FIRST and written to config.toml
        second. Both have to happen — a change that only reaches the
        running process is undone by the next restart, and one that only
        reaches the file does nothing until then — and this order means a
        key the state machine rejects never gets written down.
        """
        valid = {name for name, _label in config_mod.HOTKEY_FIELDS}
        if field not in valid:
            raise ValueError(f"{field!r} is not a key setting "
                             f"({', '.join(sorted(valid))})")
        key = (key or "").strip().lower()
        if key:
            # parse_binding, not vk_for: a chord typed into the dashboard
            # is a name vk_for cannot read, and it would be rejected here
            # as a bad key before check_hotkeys ever got to say whether it
            # was allowed on THIS field. Which fields may take a chord is
            # check_hotkeys' decision, and this line must not pre-empt it.
            parse_binding(key)               # ValueError on a bad name
        new = config_mod.with_field(self.cfg, field, key)
        config_mod.check_hotkeys(new)        # ConfigError on a collision
        if field == "hotkey" and not key:
            raise ValueError("the dictation key cannot be turned off")

        hotkeys, taps, latch_vk, pause_vk = self.bindings(new)
        self.machine.rebind(hotkeys, taps=taps, latch_vk=latch_vk,
                            pause_vk=pause_vk)
        self._lookup_vk = self._vk_of(taps, "lookup")   # _popup_key reads it
        self._vqa_vk = self._vk_of(taps, "visual_qa")
        self._capture_vk = self._vk_of(taps, "capture")
        self._record_vk = self._vk_of(taps, "record")
        self._camera_vk = self._vk_of(taps, "photo")
        self.cfg = new
        # Nested settings are written under their section name; the file
        # keeps one spelling of each key and so does this call. The TOML
        # key is visual_qa_hotkey (config.toml's own naming), the dataclass
        # field it loads into is hotkey.
        write_key = NESTED_HOTKEYS.get(field, field)
        self._save( {write_key: key})
        message = (f"{field} is now '{key}'" if key
                   else f"{field} is off")
        self._say(message)
        log.info("%s (saved to %s)", message, self.config_path.name)
        return message

    def set_option(self, name: str, value) -> str:
        """A setting changed from the dashboard while the app runs.

        WRITTEN FIRST, and the running app then reads it back from the
        file rather than trusting the argument: config.set_values parses
        and validates the whole file before it swaps it in, so a value the
        app cannot read never reaches the disk, and the parse that will
        run at the next start is the one that decides what runs now.

        Only the settings in LIVE_SECTIONS / LIVE_TOP_LEVEL are then taken
        into the running Config — they are the ones read at the moment
        they matter, or held by a worker cheap enough to rebuild. The
        rest is still written, through this one path so config.toml has
        one writer, and the reply says it applies at the next start —
        which is the truth, rather than a control that lies about having
        done something.
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("no setting was named")
        self._save( {name: value})
        fresh = self._reload()
        section, _, key = name.rpartition(".")
        if name == "auto_pause_fullscreen":
            return self._set_auto_pause(fresh.auto_pause_fullscreen)
        if name == "setup.autostart":
            import autostart
            on = fresh.setup.autostart
            self.cfg = dataclasses.replace(self.cfg, setup=fresh.setup)
            autostart.apply(on)
            message = ("Windows will start DeskIT when you sign in" if on
                       else "DeskIT no longer starts with Windows")
            if paths.DEVELOPER:
                message = "setup.autostart saved — the checkout starts from its own shortcut"
            self._say(message)
            log.info("%s", message)
            return message
        live = False
        if not section and name in LIVE_TOP_LEVEL:
            self.cfg = dataclasses.replace(self.cfg,
                                           **{name: getattr(fresh, name)})
            live = True
        elif section in LIVE_SECTIONS and hasattr(fresh, section) \
                and hasattr(self.cfg, section):
            self.cfg = dataclasses.replace(
                self.cfg, **{section: getattr(fresh, section)})
            worker = LIVE_SECTIONS[section]
            if worker:
                # Built with the old Config; the next use builds it again.
                setattr(self, worker, None)
            if section == "hint":
                self._hint_power(fresh.hint)
            if section == "shelf":
                self._shelf_power(getattr(fresh, "shelf", None))
            if section == "dot":
                self._dot_power(fresh)
            if section == "privacy":
                privacy.configure(fresh)
            live = True
        message = (f"{name} saved" if live
                   else f"{name} saved — it applies the next time it starts")
        self._say(message)
        log.info("%s", message)
        return message

    def _tour_ended(self, reason: str) -> None:
        """[סיימתי] or [דלג] on the tour card, on the card's thread: one
        line into state.json so the next start does not show it again.
        A skip counts — a tour that comes back after being waved away is
        the nag the owner's "with a skip" rules out."""
        try:
            self._save({"setup.tour": True})
        except Exception as e:                               # noqa: BLE001
            log.warning("could not record the tour as seen: %s", e)
        log.info("the tour: %s", reason)

    def tour_due(self) -> bool:
        """Show the tour at this start? Once per copy, and only after the
        wizard has run — a copy started with --fake or with the wizard
        skipped by hand has no dot to point at, and no setting to read."""
        setup = getattr(self.cfg, "setup", None)
        return bool(setup is not None and getattr(setup, "done", False)
                    and not getattr(setup, "tour", False)
                    and getattr(self.cfg, "indicator", True))

    def _consent_answered(self, kind: str, answer: str) -> None:
        """A button on the consent card, on the card's thread. [Turn on]
        writes the row (privacy.grant: two small files) and the next
        press uses the cloud; [Not now] keeps the local path and the
        card down until the next start."""
        import consent_card as cc
        if answer == cc.TURN_ON:
            try:
                privacy.grant(kind)
            except Exception as e:                           # noqa: BLE001
                log.warning("could not record the consent for %s: %s",
                            kind, e)
                return
            self._say(f"{kind}: on — from the next press")
        else:
            privacy.not_now(kind)

    def _set_auto_pause(self, value: bool) -> str:
        """The one option with a side effect beyond the Config: the
        fullscreen watcher thread, started on demand and never left
        holding a pause it can no longer undo."""
        self.cfg = dataclasses.replace(self.cfg, auto_pause_fullscreen=value)
        if value and (self._watcher is None or not self._watcher.is_alive()):
            self._watcher = threading.Thread(target=self._watch_fullscreen,
                                             daemon=True, name="fullscreen")
            self._watcher.start()
        if not value and self._auto_paused:
            self.set_paused(False)           # do not strand it paused
        message = ("auto-pause in fullscreen apps is on" if value
                   else "auto-pause in fullscreen apps is off")
        self._say(message)
        log.info("%s", message)
        return message

    def start(self) -> None:
        # The stream runs from here to stop() whatever the model does: a
        # stopped WASAPI stream refused to start again on his headset
        # (AUDCLNT_E_UNSUPPORTED_FORMAT, 2026-09-18 22:36, after the
        # first live unload → load), and a running one costs nothing
        # while nobody records.
        self.recorder.start_stream()
        # The hold first: [awake] hold = true means the machine never
        # sleeps while this app runs, whatever the screens are doing. A
        # refusal is logged and shown on the Awake screen, never fatal.
        if getattr(self, "awake", None) is not None and self.awake.hold_wanted:
            held = self.awake.hold(by="start")
            if held.get("ok") is False:
                log.warning("%s", held.get("error"))
        self.worker.start()
        self.text_worker.start()
        self.correct_worker.start()
        self.lookup_worker.start()
        self.hook.start()
        self.dot.start()
        self.hint.start()
        self.review_card.start()
        self.consent_card.start()
        self.tour_card.start()
        self.notify_card.start()
        # backend = "gemini" with the cloud_audio gate shut fell to the
        # local model at start (transcribers.get_transcriber): that is a
        # choice the person made in Settings, so the card asks now.
        if self.cfg.backend == "gemini" and \
                getattr(self.transcriber, "name", "") != "gemini":
            with privacy.pressed():
                try:
                    privacy.require("cloud_audio")
                except privacy.ConsentRequired:
                    pass
        # The shelf's thread, up before the key is ever pressed: the
        # panel is built when it opens, but the presenter has to be
        # waiting for it. Off with [shelf] enabled = false, in which case
        # there is no object here at all.
        if getattr(self, "shelf", None) is not None:
            self.shelf.start()
        self.notify.start()
        self.notify_watch.start()
        # The weekly routine's question, WATCHED FOR rather than pushed:
        # it is written by a headless process, possibly overnight, so
        # there is nothing on this machine to tell the app about it. Off
        # with the store, and after the hotkey is live either way — the
        # first look happens a whole poll from now, so this can never be
        # what delays dictation coming up.
        if getattr(self, "questions", None) is not None:
            self._q_watcher = threading.Thread(
                target=self._watch_questions, daemon=True, name="questions")
            self._q_watcher.start()
            log.info("questions: watching %s every %.0f s; a card goes up "
                     "after %.0f s of stillness and waits %.0f min if he "
                     "escapes it", _questions_mod().STORE_NAME,
                     QUESTION_POLL_S, QUESTION_SETTLE_S,
                     QUESTION_REASK_S / 60.0)
        # The weekly look at GitHub Releases (updates.py, plan 11.4): ten
        # minutes after this start, then weekly; a newer version is one
        # line on the card and a row on the dashboard, never a download.
        import updates as updates_mod
        updates_mod.start_worker(say=self._say)
        self._start_account()
        if self.locked():
            self._lock()
        elif self._model_state == "off":
            # no dot from the first frame: alive, not listening
            self._set_state("paused")
            log.info("up without the model — every key that needs no model "
                     "works; Start loads it")
        said = updates_mod.after_update()
        if said:
            self._say(said)
            log.info("%s", said)
        if self.cfg.auto_pause_fullscreen:
            self._watcher = threading.Thread(target=self._watch_fullscreen,
                                             daemon=True, name="fullscreen")
            self._watcher.start()
        if self.cfg.polish.when != "never" and self.cfg.polish.warm_up:
            # In the background and after the hotkey is live: dictation must
            # not wait on a language model it may never need, but the model
            # must not be cold the first time it IS needed.
            threading.Thread(target=self._warm_polish, daemon=True,
                             name="polish-warmup").start()
        vqa_cfg = getattr(self.cfg, "visual_qa", None)
        if vqa_cfg is not None and vqa_cfg.enabled and vqa_cfg.warmup:
            # Same bargain, vision edition: the projector behind gemma3's
            # image input costs 22.6 s on the FIRST image of a session
            # (measured 2026-08-25) and ~0.4 s warm, so one dummy-image,
            # num_predict=1 call goes out in the background now.
            threading.Thread(target=self.vqa.warm, daemon=True,
                             name="vqa-warmup").start()
        # And the IMPORTS themselves, off the hook thread, which is a
        # different problem from either warm-up above and now a sharper
        # one. `self.capture` and `self.vqa` build on first touch, and
        # every one of those touches is a keyboard callback: measured
        # 2026-08-30, importing capture.py costs 163-174 ms of the 300 ms
        # Windows allows a low-level hook before it silently unhooks it —
        # and an unhooked app is one where every key on the machine has
        # stopped answering, with nothing in the log.
        #
        # It has always been that close. What changed is that these keys
        # can now be pressed DURING a dictation, where losing the hook
        # also means losing the key-up that ends the recording, which then
        # runs to max_seconds and is discarded. One thread at startup
        # costs nothing and takes the whole risk off the table.
        threading.Thread(target=self._warm_feature_keys, daemon=True,
                         name="feature-warmup").start()
        if self.phone is not None:
            try:
                self.phone.start()
            except Exception as e:      # a busy port must not kill dictation
                log.warning("phone endpoint could not start (%s) — the "
                            "hotkey is unaffected", e)
                self.phone = None
        self._start_learning()

    def _start_learning(self) -> None:
        """The second reading and the study pass — the two engines that
        hold the model besides the dictation itself. One method because
        load_model builds them again after unload_model tore them down:
        an engine left alive across an unload keeps its reference to the
        model, and the memory never comes back.

        The second learning channel (study.py): revisit recordings the
        user already sent, when the machine is idle, and learn from what
        the live pass got wrong. Built like skin/: a getattr and a
        guarded import, so on a version whose config.py has no [study]
        section — classic — this whole block is four cheap no-ops and
        main.py stays byte-identical on both branches.
        """
        self._study = None
        self._review = None
        # The second reading (review.py) comes first and, while it is on,
        # instead of the study pass: the same three decodes serve both,
        # shown as a card rather than learned in silence. Same guarded
        # shape as the study block under it, for the same reason.
        rcfg = getattr(self.cfg, "review", None)
        if rcfg is not None and rcfg.enabled and self.recent is not None \
                and hasattr(self.transcriber, "study_decode"):
            try:
                import review as review_mod
                self._review = review_mod.Engine(
                    self.cfg, self.transcriber, self.vocab, self.recent,
                    review_mod.Store(paths.REVIEW_FILE),
                    model_lock=self._model_lock,
                    quiet=self._learning_quiet, app_dir=paths.DATA_DIR,
                    on_suggest=self._review_show,
                    on_accept=self._review_fix,
                    # The local repair as a proposal (polish.py, `when =
                    # "cloud"`): the reading runs it on a dictation the
                    # cloud did not repair before the paste. Under
                    # "always" it already ran there; under "known" and
                    # "never" it is not wanted behind the paste either.
                    repair=(self._local_repair
                            if self.cfg.polish.when == "cloud" else None))
                self._review.start()
            except Exception as e:      # noqa: BLE001 — optional feature
                log.info("second reading unavailable (%s)", e)
        scfg = getattr(self.cfg, "study", None)
        if self._review is None and scfg is not None and scfg.enabled \
                and self.recent is not None \
                and hasattr(self.transcriber, "study_decode"):
            try:
                import study as study_mod
                self._study = study_mod.Engine(
                    self.cfg, self.transcriber, self.vocab, self.recent,
                    model_lock=self._model_lock,
                    quiet=self._learning_quiet,
                    fingerprint=self._learning_fingerprint,
                    app_dir=paths.DATA_DIR)
                self._study.start()
            except Exception as e:      # noqa: BLE001 — optional feature
                log.info("study engine unavailable (%s)", e)

    def _stop_learning(self) -> None:
        for name in ("_study", "_review"):
            engine = getattr(self, name, None)
            if engine is not None:
                try:
                    engine.stop()
                except Exception:                            # noqa: BLE001
                    log.debug("%s did not stop cleanly", name, exc_info=True)
                setattr(self, name, None)

    # ---- the model, off and on (the owner's ask of 2026-09-18)

    MODEL_OFF_WORDS = ("the model is off — press Start in the desk to load it "
                       "(about 25 seconds); every other key works")

    def unload_model(self) -> dict:
        """Stop, as the desk means it: the speech model goes, the process
        stays (the microphone stream too — see start()). "Many things don't need the model —
        screenshot, screen recording and a few more — and they don't work
        when the model is off; make those that don't need the model work
        without it." So the hook, the dot, the cards, the phone's other
        doors, the shelf, translate, lookup and the screen keys all keep
        running; only the hold keys are refused (hotkey.set_dictation_off)
        and the phone's /transcribe says why. The work is on a thread —
        this is a pipe handler, and dropping a model can take a moment."""
        if self._model_state in ("off", "unloading"):
            return {"ok": False, "error": "the model is already off"}
        if self._model_state == "loading":
            return {"ok": False, "error": "the model is still loading — a moment"}
        if self.machine.state != hotkey_mod.IDLE:
            return {"ok": False, "error": "not while the microphone is live — "
                                          "finish the dictation first"}
        self._model_state = "unloading"
        threading.Thread(target=self._unload_work, daemon=True,
                         name="model-unload").start()
        return {"ok": True, "message": "unloading the model — every key that needs "
                                       "no model keeps working"}

    def _unload_work(self) -> None:
        import gc
        from transcribers.off import OffTranscriber
        self.machine.set_dictation_off(True)
        self._stop_learning()
        with self._model_lock:
            old, self.transcriber = self.transcriber, OffTranscriber(self.MODEL_OFF_WORDS)
            self._local = None
        # An English detector still loading on its thread (english_later)
        # is told its result is not wanted; the thread holds the object
        # until it lands, the memory goes with it.
        closer = getattr(old, "close", None)
        if callable(closer):
            closer()
        del old
        gc.collect()
        self._model_state = "off"
        self._set_state("paused")          # no dot: alive, not listening
        self._say("model off — Start loads it again; every other key works")
        log.info("model unloaded — the keys that need no model keep working")

    def load_model(self) -> dict:
        """Start, with the process already up: the model back (about 25 s,
        narrated by the same splash a process start shows), the learning
        engines, the hold keys."""
        if self._model_state == "on":
            return {"ok": False, "error": "the model is loaded"}
        if self._model_state == "loading":
            return {"ok": True, "message": "still loading"}
        if self._model_state == "unloading":
            return {"ok": False, "error": "the model is still unloading — a moment"}
        self._model_state = "loading"
        self._set_state("busy")
        threading.Thread(target=self._load_work, daemon=True,
                         name="model-load").start()
        return {"ok": True, "message": "loading the model — about 25 seconds"}

    def _load_work(self) -> None:
        # The splash a process start shows — "the animation that the
        # model is loading", his words when Start in the desk loaded it
        # in silence (22:37) — narrating the same log lines, landing in
        # the dot with the ready cue. Never in the way of the load: a
        # splash that cannot be built is skipped, not a failed load.
        splash, splash_log = None, None
        try:
            if getattr(self.cfg, "splash", True):
                splash = overlay_mod.Splash()
                _dot = getattr(self.cfg, "dot", None)
                splash.dot_corner = str(getattr(_dot, "corner", "bottom-right"))
                splash.dot_x = int(getattr(_dot, "x", overlay_mod.HINT_UNSET))
                splash.dot_y = int(getattr(_dot, "y", overlay_mod.HINT_UNSET))
                splash.start()
                splash_log = SplashLog(splash)
                log.addHandler(splash_log)
                splash.status("loading the transcription model…")
        except Exception:                                    # noqa: BLE001
            log.debug("no splash for this load", exc_info=True)
            splash = None
        self._say("loading the model…")
        try:
            fresh = get_transcriber(self.cfg, self._hotwords,
                                    english_later=True)
        except Exception as e:                               # noqa: BLE001
            self._model_state = "off"
            self._set_state("paused")
            self._say(f"the model did not load: {str(e).splitlines()[0][:120]}")
            log.exception("the model did not load")
            self._splash_done(splash, splash_log, "the model did not load", None)
            return
        with self._model_lock:
            self.transcriber = fresh
        self._start_learning()
        self._model_state = "on"
        self.machine.set_dictation_off(False)
        self.dot.show()                   # before the splash lands in it
        self._set_state("ready")
        self._say("listening again")
        log.info("model loaded again — hold '%s' and speak", self.cfg.hotkey)
        ready = f"ready — hold {str(self.cfg.hotkey).title()} and speak"
        self._splash_done(splash, splash_log, ready, on_land=lambda: beep("ready"))

    @staticmethod
    def _splash_done(splash, splash_log, text: str, on_land) -> None:
        if splash_log is not None:
            log.removeHandler(splash_log)
        if splash is None:
            return
        try:
            splash.finish(text, on_land=on_land)
        except Exception:                                    # noqa: BLE001
            log.debug("the splash did not finish cleanly", exc_info=True)

    def _on_dictation_refused(self) -> None:
        """A hold key while the model is off: the sentence, once per
        press and not per auto-repeat (the hook fires this on every
        key-down Windows repeats while the key is held)."""
        now = time.monotonic()
        if now - self._refused_at < 2.0:
            return
        self._refused_at = now
        self._say(self.MODEL_OFF_WORDS)

    def stop(self) -> None:
        self._stopping.set()      # ends the fullscreen and question waits
        # The hold first: it is the one thing here that changed the
        # MACHINE (the wake hold, a pinned sleep timer), and the rest of
        # this method cannot fail in a way that should leave that in place.
        if getattr(self, "awake", None) is not None:
            self.awake.release()
        self._stop_learning()
        self.dot.stop()
        self.hint.stop()
        self.review_card.stop()
        if getattr(self, "consent_card", None) is not None:
            self.consent_card.stop()
        if getattr(self, "tour_card", None) is not None:
            self.tour_card.stop()
        if getattr(self, "shelf", None) is not None:
            self.shelf.stop()
        # The watcher first — it feeds the engine, and an arrival during
        # the shutdown would arm reminders nobody is left to answer.
        if getattr(self, "notify_watch", None) is not None:
            self.notify_watch.stop()
        # The reminder thread next, then the card it would have shown.
        if getattr(self, "notify", None) is not None:
            self.notify.stop()
        if getattr(self, "notify_card", None) is not None:
            self.notify_card.stop()
        # Its own thread and its own window, and the window is destroyed
        # rather than hidden. That matters more than it did: the box waits
        # to be closed now, so quitting with one on screen must take it
        # with it — a box outliving the app that drew it would be a piece
        # of screen furniture with nothing left alive to close it.
        self.popup.stop()
        if self._vqa is not None:
            self._vqa.stop()
        # The SLOT, not the property: stop() must never be the call that
        # first imports Pillow, Tk and a video encoder.
        if self._capture is not None:
            self._capture.stop()
        if self.phone is not None:
            self.phone.stop()
        self.hook.stop()
        self.recorder.close()

    def control_command(self, command: str, args: dict) -> dict:
        """One dashboard request -> one reply. Runs on the control thread.

        Everything here is either a read or a flag flip: nothing waits on a
        model, a network call or the clipboard, because the dashboard polls
        this and a handler that blocked would render a working app as a
        frozen one.
        """
        try:
            if command == "status":
                return self.status()
            if command in ("pause", "resume", "toggle"):
                want = (command == "pause" if command != "toggle"
                        else not self.machine.paused)
                if not want and self.locked():
                    return {"ok": False, "paused": True, "error": self.LOCK_WORDS}
                self.set_paused(want)
                return {"ok": True, "paused": self.machine.paused}
            if command == "rebind":
                return {"ok": True,
                        "message": self.rebind(str(args.get("field", "")),
                                               str(args.get("key", "")))}
            if command == "option":
                return {"ok": True,
                        "message": self.set_option(str(args.get("name", "")),
                                                   args.get("value"))}
            if command == "copy_last":
                with self._last_lock:
                    text = (self._last or {}).get("final", "")
                if not text:
                    return {"ok": False, "error": "nothing dictated yet"}
                # ON A THREAD, to keep the promise this method's docstring
                # makes. The clipboard is a queue shared with the whole
                # process now (injector._board_lock) and the longest thing
                # on it — a lookup that found nothing selected — holds it
                # for up to 2.1 s. Waiting that out HERE would stall the
                # poll the dashboard uses to decide the app is alive, and
                # a running app would be drawn as a dead one.
                threading.Thread(
                    target=self._copy_text, args=(text,), daemon=True,
                    name="copy-last").start()
                return {"ok": True, "message": f"{len(text)} chars copied"}
            if command == "review_absorb":
                # The dashboard decided a proposal straight in review.json;
                # learn it now rather than at the engine's next idle tick.
                # On a thread: the learning writes vocab.json.
                engine = getattr(self, "_review", None)
                if engine is None:
                    return {"ok": False, "error": "the second reading is off"}
                threading.Thread(target=engine.absorb_decisions, daemon=True,
                                 name="review-absorb").start()
                return {"ok": True}
            if command == "read":
                # arm | disarm | keep | drop — the dashboard's Read aloud
                # tab (reading.py). All of it is a flag flip or a file
                # move, so it answers within the poll's patience.
                do = str(args.get("do", "")).strip().lower()
                ident = str(args.get("id", "") or "")
                if do == "arm":
                    return {"ok": True, "read": self.reading.arm(
                        ident, str(args.get("text", "") or ""),
                        int(args.get("hwnd") or 0))}
                if do == "disarm":
                    self.reading.disarm()
                    return {"ok": True, "read": self.reading.state()}
                if do == "keep":
                    wav = self.reading.keep(ident)
                    if wav is None:
                        return {"ok": False, "error": "nothing to keep for "
                                                      "that sentence",
                                "read": self.reading.state()}
                    return {"ok": True, "kept": wav.name,
                            "read": self.reading.state()}
                if do == "drop":
                    self.reading.drop(ident, skipped=bool(args.get("skip")))
                    return {"ok": True, "read": self.reading.state()}
                if do == "forget":
                    # A kept reading he takes back, by the name keep()
                    # answered with.
                    ok = self.reading.forget(str(args.get("name", "") or ""))
                    return ({"ok": True} if ok else
                            {"ok": False, "error": "nothing to take back"})
                return {"ok": False, "error": f"unknown read action {do!r}"}
            if command == "screens":
                # off | on | toggle | again. The engine's switches are a
                # thread start and a log line — the broadcasts and the
                # probe go to threads of their own — so this answers
                # within the poll's patience. The hold is not touched:
                # it stands for as long as the app runs.
                do = str(args.get("do", "toggle")).strip().lower()
                if do == "again":
                    self.awake.blank()
                    return {"ok": True, "message": "screens off again",
                            "awake": self.awake.state()}
                if do == "off":
                    state = self.awake.darken(by="dashboard")
                elif do == "on":
                    state = self.awake.lighten(by="dashboard")
                elif do == "toggle":
                    state = self.awake.toggle(by="dashboard")
                else:
                    return {"ok": False, "error": f"unknown screens action "
                                                  f"{do!r}"}
                self._say("screens off — the machine stays awake; tap "
                          "again to bring them back" if state.get("dark")
                          else "screens on")
                return {"ok": True, "awake": state}
            if command == "notify":
                # dismiss | open | test | recent. dismiss is one JSON
                # write and a queue put; open is that plus one
                # SetForegroundWindow; test is receive() on this thread
                # (the same write, an async cue); recent reads the file
                # once. All inside the poll's patience, and the reply
                # carries the fresh state so the Notify screen repaints
                # at once.
                engine = getattr(self, "notify", None)
                if engine is None:
                    return {"ok": False, "error": "notifications are off"}
                do = str(args.get("do", "")).strip().lower()
                # An optional "id" names ONE card of the column; without
                # it both actions still mean the whole of it, which is
                # what Dismiss all has always meant. Anything that will
                # not survive int() is no id rather than an error — the
                # engine reads it the same way.
                try:
                    ident = int(args["id"]) if args.get("id") is not None \
                        else None
                except (TypeError, ValueError):
                    ident = None
                if do == "dismiss":
                    state = engine.dismiss(ident, by="dashboard")
                    self._say("notification dismissed" if ident is not None
                              else "notifications dismissed")
                    return {"ok": True, "notify": state}
                if do == "open":
                    # What a click on a card does, from the dashboard:
                    # raise whoever sent it (the newest, with no id) and
                    # mark it seen.
                    state = engine.open(ident, by="dashboard")
                    self._say("opening what sent it")
                    return {"ok": True, "notify": state}
                if do == "test":
                    reply = engine.test(source="test")
                    if not reply.get("ok"):
                        return {"ok": False, "error": reply.get("error", "")}
                    self._say("test notification sent")
                    return {"ok": True, "message": "a test notification is "
                                                   "on its way",
                            "id": reply.get("id"), "notify": engine.state()}
                if do == "recent":
                    try:
                        n = int(args.get("n", 30))
                    except (TypeError, ValueError):
                        n = 30
                    return {"ok": True,
                            "items": engine.recent(max(1, min(100, n)))}
                return {"ok": False, "error": f"unknown notify action "
                                              f"{do!r}"}
            if command == "dot":
                # move | corner. The road the owner asked for on
                # 2026-09-07: "I press 'set' and then the desk
                # disappears and I drag the dot wherever I want it —
                # and without needing to open and close the app". This
                # is the "without": the dashboard is a separate process
                # and the dot lives in this one, so "become draggable"
                # has to travel, and it travels the same pipe every
                # other live command does.
                #
                # Both answers are one float or two ints written on this
                # thread — nothing waits, nothing paints, and the dot's
                # own painter picks the change up on its next frame,
                # which is 22 ms away. The reply carries the fresh state
                # so the dashboard knows at once whether to hide itself.
                do = str(args.get("do", "move")).strip().lower()
                if do == "move":
                    if not self.dot.move():
                        return {"ok": False,
                                "error": "there is no dot to move "
                                         "(indicator = false)"}
                    self._say("drag the dot where you want it")
                    log.info("the dot: waiting to be dragged")
                    return {"ok": True, "dot": self.dot.state(),
                            "message": "drag the dot where you want it"}
                if do == "corner":
                    self.dot.to_corner()
                    self._say("the dot is back in its corner")
                    return {"ok": True, "dot": self.dot.state(),
                            "message": "the dot is back in its corner"}
                return {"ok": False, "error": f"unknown dot action {do!r}"}
            if command == "account":
                return self._account_command(str(args.get("do", "status")).strip().lower(),
                                             kind=str(args.get("kind") or ""))
            if command == "tour":
                # Show the tour again (Settings > The app, D36): the
                # same four cards the first start showed, from the top.
                # Enqueued only; the card's thread paints it.
                card = getattr(self, "tour_card", None)
                if card is None or card._thread is None:
                    return {"ok": False, "error": "there is no tour card "
                                                  "on this copy"}
                card.show(0)
                self._say("the tour, from the top")
                return {"ok": True, "message": "the tour is beside the dot"}
            if command == "consent":
                # The desk asks for a gate it cannot open itself — the
                # consent card lives beside the dot, in this process.
                # "Send to the developer" on the desk's report box is
                # the caller (plan 7.6); privacy.request opens the card
                # inside a press or not and says whether it did.
                kind = str(args.get("kind", "")).strip()
                try:
                    asked = privacy.request(kind)
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
                if asked:
                    return {"ok": True, "asked": True,
                            "message": "the consent card is beside the dot"}
                return {"ok": True, "asked": False,
                        "allowed": privacy.allowed(kind)}
            if command == "quit":
                singleton.request_quit()
                return {"ok": True}
            if command == "unload":
                return self.unload_model()
            if command == "load":
                return self.load_model()
            return {"ok": False, "error": f"unknown command {command!r}"}
        except (ValueError, ConfigError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            log.exception("control command %r failed", command)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def _account_command(self, do: str, kind: str = "") -> dict:
        """Settings > Privacy > Account (screen 16), over the pipe: the
        dashboard is another process and only THIS one holds the
        session (8.6). Nothing here waits on the network — a sign-in
        opens the browser and waits on a thread of its own, a sync is a
        nudge to the worker — so the poll never sees a frozen app; the
        outcome lands in status()["account"] (busy / last_error) and
        in the log. A shut gate opens its card first, like a key press
        would (D7), and the person presses the button again after
        [Turn on]."""
        import sb
        if do == "status":
            return {"ok": True, "account": sb.status()}
        if not sb.configured():
            return {"ok": False, "error": "the account server is not configured in this build"}
        if do in ("google", "anonymous"):
            if not privacy.allowed("account"):
                asked = privacy.request("account")
                return {"ok": False, "error": ("the account card is beside the dot — press "
                                               "Turn on, then Sign in again" if asked else
                                               "the account consent is off — Settings > "
                                               "Privacy, or main.py --consent account")}
            if sb.status().get("busy"):
                return {"ok": False, "error": "a sign-in is already waiting for the browser"}

            def work() -> None:
                try:
                    who = sb.sign_in_google() if do == "google" else sb.sign_in_anonymous()
                    self._say("signed in" + (f" as {who.get('email')}" if who.get("email")
                                             else " (anonymous account)"))
                    self._unlock()
                    sb.nudge()
                except Exception as e:                       # noqa: BLE001
                    sb._status["last_error"] = str(e)[:200]
                    log.info("account: sign-in did not finish (%s)", e)

            threading.Thread(target=work, daemon=True, name="account-signin").start()
            return {"ok": True, "message": ("the browser opens Google's sign-in; come back "
                                            "here when it says done" if do == "google"
                                            else "creating an anonymous account")}
        if do == "signout":
            threading.Thread(target=lambda: self._account_try(sb.sign_out, "signed out"),
                             daemon=True, name="account-signout").start()
            return {"ok": True, "message": "signing out"}
        if do == "delete":
            if not sb.signed_in():
                return {"ok": False, "error": "no account on this PC"}
            threading.Thread(target=lambda: self._account_try(
                sb.delete_account, "the account is deleted — nothing of yours is left on the server"),
                daemon=True, name="account-delete").start()
            return {"ok": True, "message": "deleting the account on the server"}
        if do == "sync":
            # The desk's [Turn on] beside a shut sync row (one kind), or
            # the old Sync now (both): a shut gate gets its card, and the
            # worker runs — the card opening nudges it too (privacy.on_change)
            if not sb.signed_in():
                return {"ok": False, "error": "sign in first"}
            kinds = (kind,) if kind in privacy.SYNC_KINDS else privacy.SYNC_KINDS
            for kind in kinds:
                if not privacy.allowed(kind):
                    privacy.request(kind)
            sb.nudge()
            return {"ok": True, "message": "syncing"}
        if do == "nudge":
            # The desk queued a report (or pressed Send now): the worker
            # drains the outbox soon; no card, no consent asked here —
            # a shut report_upload gate simply leaves it queued (8.8).
            sb.nudge()
            return {"ok": True, "message": "sending soon",
                    "signed_in": sb.signed_in()}
        return {"ok": False, "error": f"unknown account action {do!r}"}

    @staticmethod
    def _report_sent(rid: str) -> None:
        """sb.py's on_sent, on the worker's thread: the Problems row whose
        copy just went up says "sent" (problems.mark_sent)."""
        try:
            problems_mod.mark_sent(problems_mod.Store(paths.PROBLEMS_FILE), rid)
        except Exception:                                    # noqa: BLE001
            log.info("problems: report %s was sent but its row could not "
                     "be marked", rid, exc_info=True)

    @staticmethod
    def _nudge_sync(*stores: str) -> None:
        """Something just landed — a dictation in transcripts.log
        (``history``), a learned word in vocab.json (``vocab``): the
        account worker pushes that store within the second and tells
        the account's other copies (sb.nudge is a flag, never a call on
        this thread). No store named means everything."""
        try:
            import sb
            for store in stores or (None,):
                sb.nudge(store)
        except Exception:                                    # noqa: BLE001
            pass

    def _account_try(self, fn, said: str) -> None:
        import sb
        try:
            fn()
            self._say(said)
        except Exception as e:                               # noqa: BLE001
            sb._status["last_error"] = str(e)[:200]
            log.info("account: %s", e)

    def _start_account(self) -> None:
        """The sync worker (sb.start_worker): nothing without a configured
        project or a session; a consent card opening one of the two
        syncs nudges it, and so does every dictation (D31: push after
        each dictation, pull on a timer)."""
        try:
            import sb
            if not sb.configured():
                return
            sb.start_worker(vocab=self.vocab, on_sent=self._report_sent)
            for kind in ("settings_sync", "history_sync", "report_upload"):
                privacy.on_change(kind, sb.nudge)
            # the session going away — a second 401, Sign out, Delete my
            # account — locks the keys again, from whichever thread saw it
            if self._lock not in sb.SIGNED_OUT_HOOKS:
                sb.SIGNED_OUT_HOOKS.append(self._lock)
        except Exception:                                    # noqa: BLE001
            log.warning("the account worker did not start", exc_info=True)

    def _transcribe_for_phone(self, wav: bytes) -> tuple[str, str, str | None]:
        """No language is passed: the phone has no per-language key, so it
        goes through the same Hebrew/English detection the desktop uses
        when nothing was specified.

        Logged to transcripts.log like every desktop dictation. Without
        this, "the transcript from my phone looked wrong" has no evidence
        behind it at all — the raw text existed only on the phone.

        THE LEARNED VOCABULARY APPLIES HERE TOO, and most of it for free:
        the phone only records — this machine transcribes, with the very
        same transcriber object the hotwords callable was handed to. So a
        word taught with F8 on the desktop stops being misheard on the
        phone from the next dictation, with nothing to implement on the
        Android side at all. The repair pass is run explicitly below so the
        two paths cannot drift into giving different answers for the same
        audio.
        """
        # getattr: a test hands this method a bare namespace as self
        locked = getattr(self, "locked", None)
        if locked is not None and locked():
            raise RuntimeError(self.LOCK_WORDS)
        if getattr(self, "_model_state", "on") != "on":
            raise RuntimeError(self.MODEL_OFF_WORDS)
        started = time.monotonic()
        text, backend = self._transcribe(wav, language=None)
        transcript_log.info("OK | PHONE | %s | %.1fs latency | %s",
                            backend, time.monotonic() - started, text)
        raw = text.strip()
        # Same blocking pass the desktop runs, under the same ceiling: both
        # have somebody waiting on the other end of it — and the same
        # split: the cloud side here, the local model on the reading.
        receipt: dict = {}
        text = self._improve(raw, receipt=receipt) if raw else text
        # A decoder loop means words are LOST, not garbled — surface that
        # on the phone right away instead of letting reading discover it.
        warning = None
        for b in (self.transcriber, self._local or None):
            found = getattr(b, "last_warning", None)
            if found:
                warning = found
                break
        # Kept in recent\ like a desk dictation, and handed to the second
        # reading — WITHOUT the desktop card (card=False): the person who
        # said this is holding a phone, and the phone asks GET /review
        # for its own proposals and rings on them. Until 2026-09-13 a
        # phone clip was transcribed and forgotten, so the reading never
        # saw it. Never in front of the reply: a full disk is a log line.
        if raw and self.recent is not None:
            try:
                # 16 kHz mono 16-bit, the shape to_wav() always hands
                # over: 32 000 bytes a second after the 44-byte header.
                kept = self.recent.save(
                    wav, max(0.0, (len(wav) - 44) / 32000.0), "",
                    extra={"text": text.strip(), "raw": raw,
                           "backend": backend, "language": "auto",
                           "words": list(getattr(self, "_last_words", [])
                                         or []),
                           "source": "phone",
                           "repair": receipt.get("by") or ""})
                engine = getattr(self, "_review", None)
                if engine is not None:
                    engine.submit(kept, hwnd=0, card=False)
            except Exception as e:        # noqa: BLE001
                log.info("could not keep the phone recording for the "
                         "second reading: %s", e)
        return text, backend, warning

    # ---- the second reading and the lookup, from the phone ----

    def _review_store(self):
        """The proposals on disk. The engine's own store while it runs;
        otherwise the same file opened here, the way the dashboard opens
        it — a phone answering while the reading is off must still land."""
        engine = getattr(self, "_review", None)
        if engine is not None:
            return engine.store
        import review as review_mod
        return review_mod.Store(paths.REVIEW_FILE)

    def _review_pending_for_phone(self) -> list:
        """GET /review: every proposal still waiting, newest last."""
        return list(self._review_store().pending())

    def _review_decide_for_phone(self, sid: str, verdict: str):
        """POST /review/decide: written straight to the store as the
        dashboard does, by="phone"; the engine's next wake learns it
        (absorb_decisions, every few seconds) — one learning path for
        every verdict. None when nothing pending has that id."""
        item = self._review_store().decide(sid, verdict, by="phone")
        if item is not None:
            transcript_log.info("REVIEW | %s | phone | %s", verdict,
                                item.get("proposed", ""))
        return item

    def _lookup_for_phone(self, text: str) -> tuple[str, str, str, float]:
        """POST /lookup: the F8 engine, for a selection made on the phone.
        (answer, target, backend, seconds). ValueError when there is
        nothing to look up — the reason classify() gave — so the server
        can answer 400 with it. Same lazily built engine as the key."""
        import lookup as lookup_mod
        lcfg = self.cfg.lookup
        what = lookup_mod.classify(text, lcfg.max_chars, lcfg.both_ways,
                                   lcfg.hebrew_share)
        if not what.ok:
            raise ValueError(f"nothing to look up ({what.reason})")
        transcript_log.info("LOOKUP-IN  | phone | %s | %s", what.mode, text)
        if self._lookup_engine is None:
            self._lookup_engine = lookup_mod.Engine(self.cfg)
        answer = self._lookup_engine.look_up(text, what)
        if answer is None or not answer.text.strip():
            raise TranscriptionError("the lookup answered with nothing")
        transcript_log.info("LOOKUP-OUT | %.1fs | %s | %s", answer.seconds,
                            answer.backend, answer.text)
        return answer.text, answer.target, answer.backend, answer.seconds

    def _translate_for_phone(self, text: str) -> tuple[str, str]:
        """The same Gemini-then-Ollama translator the F9 key uses. Shares
        the instance, so the phone does not pay Ollama's 76 s cold start
        again on its own copy.

        Logged like the desktop key, and the reason matters MORE here: this
        replaces the WHOLE field, there is no Ctrl+Z on a phone, and the
        keyboard deliberately never touches the clipboard. Without the IN
        line, a translation that comes back wrong has taken the original out
        of every store in the system.

        "phone" goes in the slot the desktop fills with "the selection" or
        "the field": history.py reads that position as the source and the
        text as everything after it, so these rows fold in the dashboard
        exactly like desktop ones, with no change to the parser.
        """
        import translate as translate_mod
        if self._translator is None:
            self._translator = translate_mod.Translator(self.cfg)
        transcript_log.info("TRANSLATE-IN  | phone | %s", text)
        started = time.monotonic()
        out, backend = self._translator.translate(text)
        transcript_log.info("TRANSLATE-OUT | %.1fs | %s | %s",
                            time.monotonic() - started, backend, out)
        return out, backend

    def _punctuate_for_phone(self, text: str) -> tuple[str, str]:
        """The phone twin of the F2 key, on the very same Punctuator.

        This is the one the phone needs most after dictation itself: the
        local Hebrew model returns a run of words with barely a comma in it,
        [polish] is forbidden from adding any, and on a phone there is no
        practical way to put them in by hand.

        punctuate.UnsafeReply is allowed to propagate rather than being
        turned into a generic failure here: server.py answers it with a 409
        and the phone leaves the field alone. A caller that could not tell
        "the guard fired and your text is fine" from "the backend is down"
        would put the wrong sentence in front of the one person able to act
        on either.
        """
        transcript_log.info("PUNCTUATE-IN  | phone | %s", text)
        started = time.monotonic()
        out, backend = self._punctuation().punctuate(text)
        transcript_log.info("PUNCTUATE-OUT | %.1fs | %s | %s",
                            time.monotonic() - started, backend, out)
        return out, backend

    def _punctuation(self):
        """The one Punctuator. The key, the phone and the auto pass share
        it, and set_option throws it away when [punctuate] changes so the
        next press builds one from the new Config."""
        if self._punctuator is None:
            import punctuate as punctuate_mod
            self._punctuator = punctuate_mod.Punctuator(self.cfg)
        return self._punctuator

    def _auto_punctuate(self, text: str) -> str:
        """Punctuation on the way to the cursor, when the box is ticked.

        Between the repair pass and the paste, so it works on the final
        words, and bounded by punctuate.max_wait_s because the "..."
        marker is up the whole time it runs. Never raises, and every
        failure has the same shape: the transcript lands as it came. The
        guard is punctuate.is_safe, letter for letter — a reply that
        changed a word is thrown away, not pasted, exactly as the key
        does it.
        """
        pcfg = getattr(self.cfg, "punctuate", None)
        if pcfg is None or not getattr(pcfg, "auto", False):
            return text
        import punctuate as punctuate_mod
        if not punctuate_mod.needs_punctuation(text):
            return text
        if len(text.split()) < AUTO_PUNCTUATE_MIN_WORDS:
            return text
        if len(text) > pcfg.max_chars:
            log.info("not punctuating %d chars on the way to the cursor "
                     "(punctuate.max_chars = %d)", len(text), pcfg.max_chars)
            return text
        started = time.monotonic()
        try:
            fixed, backend = self._punctuation().punctuate(
                text, max_wait_s=getattr(pcfg, "max_wait_s", 6.0))
        except punctuate_mod.UnsafeReply as e:
            log.warning("auto punctuation REJECTED — %s. The transcript "
                        "lands as it came.", e)
            return text
        except TimeoutError as e:
            log.warning("auto punctuation gave up waiting (%s) — the "
                        "transcript lands as it came. Raise "
                        "punctuate.max_wait_s, or switch auto off.", e)
            return text
        except Exception as e:
            log.warning("auto punctuation failed (%s) — the transcript "
                        "lands as it came", e)
            return text
        if fixed.strip() == text.strip():
            return text
        transcript_log.info("PUNCTUATED | %.1fs | %s | %s",
                            time.monotonic() - started, backend, fixed)
        log.info("punctuated on the way to the cursor (%s, %.1f s)",
                 backend, time.monotonic() - started)
        return fixed

    def _hint_power(self, hcfg) -> None:
        """Rebuild the card from a changed [hint] — switched on or off,
        moved, resized or given a new delay from the dashboard.

        On its own thread: the old card's thread is joined and the new
        one's is waited for, and this is called from the control pipe,
        which has to answer at once. The card's own "don't show this
        again" box does not come through here — it only writes the line,
        and the card it was ticked on stops showing itself.
        """
        def swap() -> None:
            old = self.hint
            new = (overlay_mod.HintCard(
                hcfg.after_ms, hcfg.corner, x=hcfg.x, y=hcfg.y,
                scale=hcfg.scale, on_change=self._save_hint,
                dot_corner=self._dot_corner,
                dot_at=self._dot_beside
                if getattr(hcfg, "follow_dot", True) else None)
                if hcfg.enabled else overlay_mod.HintCard.off())
            old.stop()
            self.hint = new
            new.start()
        threading.Thread(target=swap, daemon=True, name="hint-swap").start()

    # ---- hook-thread callbacks: keep them fast ----

    def _on_start(self, language: str | None = "he") -> None:
        self.recorder.begin()   # also restores the cap a latch may have lifted
        self._question_texts = []
        self._cap, self._latched = self.cfg.max_seconds, False
        self._rec_at = time.monotonic()
        self._set_state("recording")
        # An ask-the-screen card that is reading an answer aloud stops the
        # moment you start talking over it — that is what makes the thing
        # feel like a conversation rather than a form. Read off the
        # ALREADY-BUILT controller and never through the self.vqa property:
        # this runs inside the keyboard hook, and classic has no visual_qa
        # module to import even if something asked it to.
        vqa = getattr(self, "_vqa", None)
        # WHERE THIS DICTATION IS GOING IS DECIDED HERE, at the press, and
        # is not asked again when the transcript comes back.
        #
        # It used to be read at transcription time, which was safe only
        # while the ask card could not possibly open in between — and it
        # cannot, if the key that opens it is dead for as long as anyone is
        # speaking. That is exactly what changed. Ask about the screen in
        # the middle of dictating a paragraph and the paragraph would be
        # swallowed into the card's question box instead of landing in the
        # document it was aimed at, with nothing on screen to explain why.
        #
        # The rule is the one a person would state: if the card was up when
        # you started talking, you were talking to the card. If it was not,
        # you were talking to your document, and a card opening while you
        # speak does not change who you were addressing.
        self._to_card = bool(vqa is not None and vqa.sink_active)
        # And the report card, on exactly the same rule and for a harder
        # reason: it is one of OUR OWN windows, so a transcript aimed at
        # it can never be pasted. injector.is_our_window refuses a paste
        # into this process by design (injector.py:549 — the placeholder
        # would go in and the focus test would then pass, so it could
        # never be taken back out), which is why the box has to be FILLED
        # rather than pasted into, the way the ask card is.
        #
        # Never both: one dictation has one destination, and the card is
        # given precedence because it is the older claim and the one
        # `diverting` at the far end is computed from. In practice they
        # cannot both be up — each takes the keyboard when it opens.
        # getattr for the same reason `_vqa` is read that way three lines
        # up: this runs inside the keyboard hook, where an AttributeError
        # is a dropped hook and a frozen keyboard, and a half-built App
        # (the tests build several) must still be able to start a
        # recording. No box means nowhere to divert to, which is False.
        # THE REPORT CARD ONLY, not the pencil's word box: both are
        # WordPrompts and both take the keyboard, but the pencil is asking
        # what one word should have been and a paragraph dictated at it is
        # not an answer to that. The report card is the one window here
        # that wants a sentence.
        box = getattr(self, "_problem_card", None)
        self._to_prompt = bool(not self._to_card
                               and box is not None and box.open())
        # And for the same reason, the window is remembered NOW as well as
        # at the release. Our own overlays take the foreground, so a
        # dictation that ends over a capture overlay would otherwise be
        # aimed at that overlay. See _on_stop.
        #
        # FILTERED HERE TOO, and it has to be: the clip bar of a screen
        # recording takes the foreground when Tk realises it and never
        # gives it back, so it is perfectly possible to press the hotkey
        # while one of ours is already in front. An unfiltered fallback
        # would then be a second of our own windows, both tests in _handle
        # would pass against it, and the marker and the transcript would
        # both be fired into it and logged as a success. 0 means "nowhere
        # known", which _handle answers with the clipboard.
        start = injector.foreground_window()
        self._start_hwnd = 0 if injector.is_our_window(start) else start
        # THE READING, on the same rule again: a sentence is armed on the
        # dashboard's Read aloud tab AND the dashboard is the window in
        # front, so he is reading the card, not dictating into it. The
        # dashboard is another process, which is why it is not one of
        # "ours" above and why the test is the window it armed with.
        # Decided here and never re-asked: the sentence he is reading is
        # the one that was up when he began. getattr, like the box: the
        # tests build half an App and still start recordings.
        reading = getattr(self, "reading", None)
        self._to_read = bool(not self._to_card and not self._to_prompt
                             and reading is not None and reading.takes(start))
        # The last window that was somebody ELSE'S. Sticky on purpose: it
        # is what the ask card interrupted, and the card being in front is
        # exactly when _start_hwnd stops being able to tell us.
        if self._start_hwnd:
            self._field_hwnd = self._start_hwnd
        if self._to_card:
            # The meter rides along so the card can draw the wave from the
            # real microphone. A bound method of the recorder, not the
            # recorder: the card is given a way to READ a level and no way
            # to touch anything else.
            vqa.notify_recording(level=self.recorder.meter)
        # After the routing above: a dictation bound for the ask card,
        # the report card or the reading card is never repaired, so its
        # stretches are not sent to the repair pass either.
        self._roller = self._start_roller(
            polish=not (self._to_card or self._to_prompt or self._to_read))
        beep("start")
        log.info("recording %s... (release to transcribe%s)",
                 language_label(language, shout=True),
                 f", tap '{self.cfg.latch_hotkey}' to lock it on"
                 if self.cfg.latch_hotkey else "")

    def _start_roller(self, polish: bool = True):
        """The rolling transcriber for the recording just begun, or None.

        Only for the local backend, and only when [local] rolling says
        so: the cloud backends take a file, and the fake one is timing
        nothing. Built here, on the hook thread, because that is where
        the recording begins — but only a Thread.start(); the reading and
        the decoding happen on its own thread (rolling.py).

        `polish`: also send each decoded stretch through the repair pass
        (_polish_window) while the key is still held, so the release
        repairs only what came after it.
        """
        local = getattr(self.cfg, "local", None)
        if local is None or not getattr(local, "rolling", False):
            return None
        backend = getattr(self, "transcriber", None)
        if not hasattr(backend, "decode_window"):
            return None
        try:
            import rolling as rolling_mod
            from recorder import frames_to_wav

            def decode(wav: bytes, lead_s: float, keep_s: float):
                # The one choke point every decode passes through, the
                # phone endpoint's included (see _transcribe).
                with self._model_lock:
                    window = backend.decode_window(wav, lead_s, keep_s)
                if polish and window.text:
                    threading.Thread(target=self._polish_window,
                                     args=(window, backend), daemon=True,
                                     name="rolling-polish").start()
                return window

            roller = rolling_mod.Roller(
                self.recorder.chunks_since, self.recorder.sample_rate,
                decode, local.rolling_window_s, frames_to_wav,
                overlap=bool(getattr(backend, "can_overlap", False)))
            roller.start()
            return roller
        except Exception:
            log.exception("could not start the rolling transcriber — this "
                          "recording is decoded whole at the end")
            return None

    def _on_stop(self, language: str | None = "he") -> None:
        # The rolling transcriber first, so its next look at the buffer
        # finds it ended; the worker collects what it finished (_handle).
        roller, self._roller = getattr(self, "_roller", None), None
        if roller is not None:
            roller.close()
        # end_pieces, not end: a recording the ask card interrupted comes
        # back cut at the questions, so the worker can transcribe what
        # surrounds them and splice the questions back in. Nothing asked
        # means one piece and the old path exactly.
        wav, pieces, seconds = self.recorder.end_pieces()
        self._set_state("busy")
        self.dot.alarm(False)          # whatever it was doing, it is over
        if wav is None:
            # overflowed at the cap — beep already fired at cap time
            log.info("discarded: hit the %.0f s cap", self._cap)
            transcript_log.info("DISCARDED | %.1fs | hit the %.0f s cap",
                                seconds, self._cap)
            self._set_state("ready")
            return
        if seconds < self.cfg.min_seconds:
            log.info("discarded: %.2f s hold is under min_seconds=%.2f "
                     "(accidental tap?)", seconds, self.cfg.min_seconds)
            self._set_state("ready")
            return
        beep("stop")
        # Remember WHERE the user was speaking. Everything slow (placeholder
        # paste, transcription) happens on the worker: this callback runs
        # inside the OS keyboard hook, and blocking here would make Windows
        # drop the hook and freeze input.
        #
        # The window at the RELEASE, unless one of ours is in front of it.
        # The release is normally the better of the two moments — a person
        # who alt-tabs mid-sentence means the window they ended in — but a
        # screenshot overlay or an ask card opened while they spoke is not
        # a window they alt-tabbed to and is not a place a transcript can
        # go. In that one case the window they were in when they STARTED
        # is the only honest answer.
        hwnd = injector.foreground_window()
        if hwnd and injector.is_our_window(hwnd):
            hwnd = self._start_hwnd
        # The report card rides in the EXTRA DICT, not as a seventh element:
        # the worker unpacks item[:5] and splats item[5], so `sliced` and
        # `in_stream` already travel this way and every caller and test
        # that builds a five- or six-tuple keeps working untouched.
        extra = {"pieces": pieces} if len(pieces) > 1 else {}
        if self._to_prompt:
            extra["to_prompt"] = True
        if self._to_read:
            # The SENTENCE'S id, not a flag: by the time the worker has
            # the transcript the dashboard may have moved on, and a
            # reading filed under the next card would be a wrong label
            # in the one set that must have none.
            extra["to_read"] = self.reading.armed_id
        if self.recorder.silent():
            # Nothing above recorder.SILENT_PEAK from start to end: a
            # dead microphone, not a dictation. The worker still runs it
            # — the alarm never stops a recording — but keeps it out of
            # recent\, so the labelled set and the Recordings tab do not
            # fill with silence (report 20260910-190110).
            extra["silent"] = True
            log.warning("the whole recording was silent (peak %.4f) — it "
                        "will not be kept in recent\\", self.recorder.peak())
        done = ""
        if roller is not None and len(pieces) <= 1:
            extra["rolled"] = roller
            if roller.done_s > 0:
                done = f"; {roller.done_s:.1f} s already done"
        self.queue.put((wav, seconds, hwnd, language, self._to_card, extra))
        log.info("captured %.1f s of %s -> transcribing (%s%s)...", seconds,
                 language_label(language),
                 self.transcriber.name, done)

    def _on_latch(self) -> None:
        # Lift the cap first, then beep: the cue is fire-and-forget but the
        # ordering keeps the guarantee honest if it ever stops being.
        self.recorder.set_cap(self.cfg.latch_max_seconds or None)
        self._cap = self.cfg.latch_max_seconds or math.inf
        self._latched = True
        self._set_state("locked")
        beep("latch")
        log.info("locked — let go of '%s' and talk as long as you want; "
                 "tap '%s' again to transcribe, esc to discard%s",
                 self.cfg.hotkey, self.cfg.latch_hotkey,
                 "" if not self.cfg.latch_max_seconds
                 else f" (cap {self.cfg.latch_max_seconds:.0f} s)")

    def _on_abort(self, reason: str) -> None:
        self._set_state("ready")
        self.dot.alarm(False)
        roller, self._roller = getattr(self, "_roller", None), None
        if roller is not None:
            roller.invalidate()
        self.recorder.abort()
        log.info("aborted, nothing recorded — %s", reason)

    def _on_tap(self, action: str) -> None:
        if action == "correct":
            self._tap_correct()
            return
        if action == "lookup":
            self._tap_lookup()
            return
        if action == "visual_qa":
            self._tap_visual_qa()
            return
        if action == "capture":
            self._tap_capture()
            return
        if action == "record":
            self._tap_record()
            return
        if action == "photo":
            self._tap_photo()
            return
        if action == "screens":
            self._tap_screens()
            return
        if action == "notify_dismiss":
            self._tap_notify_dismiss()
            return
        if action == "problem_report":
            self._tap_problem()
            return
        if action == "shelf":
            self._tap_shelf()
            return
        if action not in ("translate", "punctuate"):
            return
        # Remember WHERE the text is before anything slow happens, for the
        # same reason _on_stop does: this runs inside the OS keyboard hook.
        #
        # One flag for both keys, not one each: they take turns at the
        # clipboard and the selection, so "punctuate while a translation is
        # in flight" has to be refused for exactly the reason a second
        # translation does.
        if self._text_busy.is_set():
            log.info("still working on the text at the cursor — ignoring the "
                     "'%s' press", action)
            return
        self._text_busy.set()
        self.text_queue.put((action, injector.foreground_window()))

    def _tap_correct(self) -> None:
        """Learn from the correction the user has already made on screen.

        Runs inside the keyboard hook, so it does nothing but check state
        and enqueue — the grab sends keystrokes and waits for the focused
        app to answer, and blocking here would make Windows drop the hook
        and freeze every key on the machine.
        """
        if self._correcting.is_set():
            log.info("still reading the last correction — ignoring the "
                     "extra press")
            return
        with self._last_lock:
            last = dict(self._last) if self._last else None
        if not last:
            self._cue_once("noop", "nothing-yet")
            self._say("nothing to teach yet — dictate something first")
            log.info("nothing to correct yet — dictate something first")
            return
        self._correcting.set()
        self.correct_queue.put((last, injector.foreground_window()))

    def _tap_lookup(self) -> None:
        """Look up what is selected, without touching it.

        Runs inside the keyboard hook like every other tap, so it does
        nothing but check state and read two numbers: the capture sends a
        chord and waits for the focused app to answer it, and blocking
        here would make Windows drop the hook and freeze every key on the
        machine.

        A press while a box is already open asks a NEW question, and does
        not close the old one. That is a reversal. It was right while the
        box dismissed itself — the key that opened it was the obvious key
        to shut it — but the box now stays up until it is closed on
        purpose, and under that rule the toggle turned the commonest use
        of this key into a no-op: select a second word, tap, and all that
        happens is the first answer disappearing. The box has a button of
        its own for closing, and Esc; this key is for asking.
        """
        if self._looking_up.is_set():
            # Genuinely in flight, which is a different thing from "a box
            # is on screen": one clipboard, one selection, one answer
            # being written. The box being up is no longer a reason to
            # refuse anything.
            self._cue_once("noop", "lookup-busy")
            log.info("still looking that one up — ignoring the extra press")
            return
        self._looking_up.set()
        # Both facts are only true at the moment of the press. The window
        # is remembered for the same reason _on_stop remembers it, and is
        # used to say so in the log; the cursor is remembered because it
        # is where the answer has to appear — see cursor_point, and see
        # _lookup for the caret it is measured against.
        self.lookup_queue.put((injector.foreground_window(), cursor_point()))

    def _tap_visual_qa(self) -> None:
        """Start the select-a-region-and-ask flow.

        Runs inside the keyboard hook like every other tap: check one
        flag, spawn a thread, return. Everything slow (the fullscreen
        overlay, the grab, the model) happens on the controller's own
        thread, and blocking here would make Windows drop the hook and
        freeze every key on the machine.
        """
        if self.vqa.busy:
            # A card is already open: the press means "ask about something
            # ELSE", not "do nothing". It re-runs the selector and points
            # the same card at the new pixels; only a press while the
            # selector itself is on screen has nothing to do.
            if self.vqa.reselect():
                log.info("select the new part of the screen to ask about")
                return
            self._cue_once("noop", "vqa-busy")
            log.info("the screen selector is already up — ignoring the "
                     "extra press")
            return
        if self.vqa.begin_selection():
            log.info("select the part of the screen to ask about — esc or "
                     "a click cancels")

    def _tap_capture(self) -> None:
        """Take a screenshot: freeze, select, save, copy, offer the editor.

        Runs inside the keyboard hook like every other tap, so it checks
        one flag, spawns a thread and returns. Everything slow -- the
        grab, the overlay, the PNG, the clipboard -- happens on the
        capture controller's own thread; blocking here would make Windows
        drop the hook and freeze every key on the machine.
        """
        if self.capture.busy:
            self._cue_once("noop", "capture-busy")
            log.info("the capture overlay is already up - ignoring the "
                     "extra press")
            return
        if self.capture.begin_shot():
            log.info("drag the part of the screen to capture - shift-drag "
                     "to lasso a shape, enter for this screen, esc cancels")

    def _tap_record(self) -> None:
        """Start a screen recording, or stop the one that is running.

        A TOGGLE, which is why this reads `recording` before `busy`: the
        second press of the key is how a recording ENDS, and refusing it
        as "busy" would leave the only way out on a bar that is sitting on
        top of the thing being recorded.
        """
        if self.capture.recording:
            self.capture.toggle_clip()
            log.info("stopping the recording")
            return
        if self.capture.busy:
            self._cue_once("noop", "capture-busy")
            log.info("the capture overlay is already up - ignoring the "
                     "extra press")
            return
        if self.capture.toggle_clip():
            log.info("drag the area to record - enter for this screen, "
                     "esc cancels")

    def _tap_photo(self) -> None:
        """Open the camera and offer the shutter.

        Runs inside the keyboard hook like every other tap, so it checks
        one flag, spawns a thread and returns. Opening a webcam takes the
        better part of a second (measured 654-829 ms to the first frame)
        and blocking here for that long would make Windows drop the hook
        and freeze every key on the machine.
        """
        if self.capture.busy:
            self._cue_once("noop", "capture-busy")
            log.info("the capture overlay is already up - ignoring the "
                     "extra press")
            return
        if self.capture.begin_photo():
            log.info("opening the camera - space or the shutter takes the "
                     "picture, t sets a timer, m mirrors it, esc closes")

    def _tap_screens(self) -> None:
        """The screens off, or back, from the key. On a thread, like every
        tap: the engine's own work is small, but nothing that may spawn a
        process runs inside the keyboard hook's 300 ms."""
        def work() -> None:
            state = self.awake.toggle(by="key")
            if state.get("dark"):
                self._say("screens off — the machine stays awake; tap "
                          "again to bring them back")
            else:
                self._say("screens on")
        threading.Thread(target=work, daemon=True, name="screens-key").start()

    def _tap_notify_dismiss(self) -> None:
        """The notification card down and everything marked seen, from
        the key. On a thread, like every tap: the engine's dismiss writes
        notify.json, and nothing that touches the disk runs inside the
        keyboard hook's 300 ms."""
        def work() -> None:
            engine = getattr(self, "notify", None)
            if engine is not None:
                engine.dismiss(by="key")
                self._say("notifications dismissed")
        threading.Thread(target=work, daemon=True, name="notify-key").start()

    # ---- the shelf (shelf.py + shelf_card.py) ----

    # Which of a row's answers takes the screen somewhere else. Those
    # close the panel, because something has replaced it; everything else
    # ANSWERS what is on the panel, and answering the first of five
    # things waiting must not make him press the key again for the second
    # — the whole point of putting two buttons on every row is that the
    # pile can be emptied where it stands. One set, so the rule is
    # readable and reversible.
    _SHELF_LEAVES = frozenset({"notify.open", "problem.open",
                               "question.answer"})

    def _tap_shelf(self) -> None:
        """The panel beside the dot: open it, or close the one that is up.

        ONE PRESS, ONE TOGGLE. `PTTStateMachine._take_tap` holds the vk
        until the key comes up, so Windows' auto-repeat cannot fire this
        twice, and this method itself only reads one flag and starts a
        thread: building the card reads four small JSON stores (2.3 ms
        measured), and nothing that touches the disk runs inside the
        keyboard hook's 300 ms.

        It never opens on hover and never on its own. That is the owner's
        rule for this panel, and it is what makes a panel this tall
        acceptable beside a 13 px dot.
        """
        card = getattr(self, "shelf", None)
        if card is None:
            self._cue_once("noop", "shelf-off")
            log.info("the shelf is off ([shelf] enabled = false) — there is "
                     "nothing for this key to open")
            return
        try:
            if card.visible():
                self._shelf_close()
                return
        except Exception:                        # noqa: BLE001
            return
        threading.Thread(target=self._shelf_open, daemon=True,
                         name="shelf-open").start()

    def _shelf_open(self) -> None:
        """Build the panel and put it up. On a thread of its own."""
        card = getattr(self, "shelf", None)
        if card is None:
            return
        try:
            self._shelf_stop_armed = False
            fresh = self._shelf_card(force=True)
            if fresh is None:
                return
            # ONE PILE IN ONE CORNER. The hint card defaults to the same
            # corner and the shelf key works mid-dictation, so both can be
            # wanted at once; and the notification column is showing the
            # same items this panel now lists, with the same two answers.
            # hush() sets an Event and returns — no Tk, no queue — so it
            # is safe from anywhere, nothing is marked seen and no
            # reminder is spent.
            self.hint.show(None)
            scfg = getattr(self.cfg, "shelf", None)
            if getattr(scfg, "hush_notifications", True):
                column = getattr(self, "notify_card", None)
                if column is not None:
                    column.hush()
            card.show(fresh)
            log.info("shelf: open — %d waiting", int(fresh.get("waiting", 0)))
        except Exception:                        # noqa: BLE001
            log.exception("the shelf would not open — dictation is "
                          "unaffected")

    def _dot_squares(self) -> list:
        """The screen rectangles a press may land on without closing the
        shelf — which is the status dot's window and nothing else.

        The dot is a TOGGLE, so a press on it is already a close: letting
        the shelf's watch on the mouse see that press as "away" would
        close the panel and let the dot's own handler open it again in
        the same gesture. The rect comes from whichever painter is
        drawing the dot and is None while there is no dot on screen.
        """
        rect = getattr(getattr(self, "dot", None), "rect", None)
        return [rect] if rect is not None else []

    def _dot_power(self, fresh) -> None:
        """`[dot]` changed from the dashboard — take it live.

        The corner was read once, at startup, so picking the other one
        from Settings wrote a line and nothing on screen moved until the
        app was restarted. That was survivable while the menu was alone
        on a page; since 2026-09-08 it stands beside "Move the dot" and
        "Back to the corner" on one card (dashboard._dot_block), and both
        of those act in the same second. A menu that quietly deferred
        next to them would read as the same bug he reported: "I cannot
        move the dot."

        So it goes down the road the drop and "Back to the corner"
        already use: the fields are written and `_replace` is set, and
        whichever painter is running picks it up on its next frame — 22
        ms away, nothing restarts. x and y come with it, because they are
        editable rows on the same page and a number typed there should
        move the dot for the same reason the button does.

        The cards beside the dot are told too. They are built once and
        hold the dot's corner to keep out of its square; left alone they
        would go on avoiding a corner the dot has left, and a card that
        follows the dot (`corner = "dot"`) would still open in the old
        one. Rebuilding them is not needed and would cost their windows.
        """
        dcfg = getattr(fresh, "dot", None)
        dot = getattr(self, "dot", None)
        if dcfg is None or dot is None:
            return
        corner = str(getattr(dcfg, "corner", self._dot_corner))
        self._dot_corner = corner
        dot.corner = corner
        dot.x = int(getattr(dcfg, "x", dot.x))
        dot.y = int(getattr(dcfg, "y", dot.y))
        dot._replace.set()
        for card in (getattr(self, "hint", None),
                     getattr(self, "shelf", None)):
            if card is None:
                continue
            card._dot_corner = corner
            if getattr(card, "_dot_at", None) is not None:
                # It FOLLOWS the dot, so its own corner is the dot's —
                # config.load resolved the word "dot" against the corner
                # that was in the file a moment ago, and that is the one
                # this card is still holding.
                card._corner = corner
        log.info("the dot: corner=%s, x=%s, y=%s", corner, dot.x, dot.y)

    def _dot_beside(self):
        """The dot's own square for a card that opens BESIDE it — but
        only once he has DRAGGED the dot out of its corner.

        The owner, 2026-09-08: "I want it to be able to move where the
        dot is." Handed to the cards whose file says `corner = "dot"`
        (overlay.HintCard.dot_at), and called on every paint, because the
        dot can be dragged at any moment and the cards are built once at
        startup.

        None while the dot is still in its corner, and that is not
        laziness: the corner rule is what every card and every test has
        always used there, it puts the panel against the screen's edge
        rather than eighteen pixels off it, and there is nothing to
        improve about a dot that has not moved. None as well with no dot
        at all (`indicator = false`) — then there is nothing to open
        beside.
        """
        dot = getattr(self, "dot", None)
        if dot is None:
            return None
        try:
            if not dot.dragged():
                return None
        except Exception:                        # noqa: BLE001
            return None
        return getattr(dot, "rect", None)

    def _shelf_close(self) -> None:
        """Down, and the corner given back to whoever else wants it.

        The fifth door leads here too. The key, Esc, the X on the head
        band, a second click on the dot and now a press anywhere outside
        the panel all end in this one method, because closing the shelf
        is more than hiding a window: the notification column comes back,
        the key card comes back and Stop is disarmed.

        Safe from the hook thread, from the control thread and from the
        shelf's own watcher: every call in here only sets an Event or
        puts something on a queue.
        """
        card = getattr(self, "shelf", None)
        if card is not None:
            card.hide()
        self._shelf_stop_armed = False
        try:
            column = getattr(self, "notify_card", None)
            if column is not None:
                column.unhush()
        except Exception:                        # noqa: BLE001
            log.debug("could not bring the notification column back",
                      exc_info=True)
        try:
            self.hint.show(self._hint_card(self._activity))
        except Exception:                        # noqa: BLE001
            log.debug("could not put the hint card back", exc_info=True)

    def _shelf_push(self) -> None:
        """Rebuild the panel and show it, on a thread. Called from places
        that run inside the keyboard hook (_set_state) and from the
        buttons that change something the panel is showing."""
        card = getattr(self, "shelf", None)
        if card is None:
            return

        def work() -> None:
            try:
                if not card.visible():
                    return
                fresh = self._shelf_card(force=True)
                if fresh is not None and card.visible():
                    card.show(fresh)
            except Exception:                    # noqa: BLE001
                log.debug("could not refresh the shelf", exc_info=True)
        threading.Thread(target=work, daemon=True, name="shelf-push").start()

    def _shelf_stamps(self) -> tuple:
        """What tells the panel that something it is showing has moved,
        WITHOUT reading anything: (size, mtime_ns) per store.

        Three of the four stores already answer this question for the
        dashboard's change detector; the second reading's has no `stamp`,
        so its own path is stat'd here in the same shape. A refresh that
        finds these unchanged reads no JSON at all.
        """
        out = []
        for owner, attr in ((getattr(self, "notify", None), "store"),
                            (getattr(self, "_review", None), "store"),
                            (self, "problems"), (self, "questions")):
            store = getattr(owner, attr, None) if owner is not None else None
            stamp = None
            if store is not None:
                try:
                    reader = getattr(store, "stamp", None)
                    if callable(reader):
                        stamp = reader()
                    else:
                        st = store.path.stat()
                        stamp = (st.st_size, st.st_mtime_ns)
                except Exception:                # noqa: BLE001
                    stamp = None
            out.append(stamp)
        return tuple(out)

    def _shelf_state(self) -> dict:
        """The head of the panel: which dot, how long up, and the clause
        after it. Three attribute reads and a subtraction."""
        machine = getattr(self, "machine", None)
        mode = _DOT_FOR.get(getattr(machine, "state", None))
        if mode is None:
            if getattr(machine, "paused", False):
                mode = "paused"
            else:
                mode = "busy" if self._activity == "busy" else "listening"
        note = ""
        if mode in ("recording", "locked") and self._rec_at:
            live = max(0.0, time.monotonic() - self._rec_at)
            note = f"recording {int(live) // 60}:{int(live) % 60:02d}"
        else:
            with self._stats_lock:
                said = int(self._stats.get("dictations", 0))
            note = f"{said} today" if said else ""
        return {"mode": mode,
                "uptime_s": time.monotonic() - self._started_at,
                "stop_armed": bool(self._shelf_stop_armed),
                "note": note}

    def _shelf_pile(self) -> list:
        """Everything waiting for an answer, from all four stores, newest
        first, as one list.

        ONE LIST AND ONE ORDER, which is the notification column's order
        ("the first one will be at the upper side and the oldest one will
        be on the down side"). The cost of one rule for four sources is
        that a burst of notifications can push a question that has waited
        since Saturday past the cap into "+N more"; the alternative is
        two rules, and this one is three lines to change if he minds.

        Every store is read through getattr and every read is wrapped: a
        store that is off, missing or unreadable costs its own rows and
        nothing else. `self.questions` is None on this machine today
        ([questions] is not in config.toml), which is exactly the case
        this shape is for.

        The verb on an answer names the SOURCE as well as the act
        ("notify.dismiss"), because ids from four stores share one list
        and _shelf_pressed must know which store an id belongs to.
        shelf_card hands the verb back untouched and decides nothing.
        """
        rows: list[dict] = []
        engine = getattr(self, "notify", None)
        if engine is not None:
            try:
                for item in engine.live():
                    rows.append({
                        "kind": str(item.get("kind") or "info"),
                        "id": item.get("id"),
                        "text": str(item.get("title")
                                    or item.get("label") or ""),
                        "at": str(item.get("at") or ""),
                        "pill": "",
                        "answers": [("notify.open", "Open"),
                                    ("notify.dismiss", "Dismiss")]})
            except Exception:                    # noqa: BLE001
                log.debug("shelf: could not read the notifications",
                          exc_info=True)
        review = getattr(self, "_review", None)
        if review is not None:
            try:
                import review as review_mod
                for item in review.store.pending():
                    changes = item.get("changes") or []
                    piece = (review_mod.snippet(item.get("text") or "",
                                                changes[0])
                             if changes else {})
                    rows.append({
                        "kind": "review",
                        "id": item.get("id"),
                        "text": str(piece.get("right")
                                    or item.get("text") or ""),
                        "at": str(item.get("when") or ""),
                        "pill": str(piece.get("word") or ""),
                        "answers": [("review.accept", "Keep"),
                                    ("review.reject", "No")]})
            except Exception:                    # noqa: BLE001
                log.debug("shelf: could not read the second reading",
                          exc_info=True)
        store = getattr(self, "problems", None)
        if store is not None:
            try:
                for item in store.items(problems_mod.OPEN):
                    rows.append({
                        "kind": "problem",
                        "id": item.get("id"),
                        "text": str(item.get("text") or ""),
                        "at": str(item.get("at") or ""),
                        "pill": "",
                        "answers": [("problem.open", "Open"),
                                    ("problem.close", "Close")]})
            except Exception:                    # noqa: BLE001
                log.debug("shelf: could not read the problems", exc_info=True)
        store = getattr(self, "questions", None)
        if store is not None:
            try:
                for item in store.items(_questions_mod().PENDING):
                    rows.append({
                        "kind": "question",
                        "id": item.get("id"),
                        "text": str(item.get("question")
                                    or item.get("text") or ""),
                        "at": str(item.get("at") or ""),
                        "pill": "",
                        "answers": [("question.answer", "Answer"),
                                    ("question.later", "Later")]})
            except Exception:                    # noqa: BLE001
                log.debug("shelf: could not read the questions",
                          exc_info=True)
        rows.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
        return rows

    def _shelf_card(self, force: bool = False) -> dict | None:
        """The whole panel as data, or None when nothing has moved.

        `force` skips the change detector, which is what opening the
        panel and a state change both want. Otherwise the four stamps are
        compared FIRST and no JSON is read at all when they agree — the
        refresh runs once a second for as long as the panel is up, and
        the usual answer to "has anything changed" is no.
        """
        card = getattr(self, "shelf", None)
        if card is None:
            return None
        stamps = self._shelf_stamps()
        state = self._shelf_state()
        if not force and stamps == self._shelf_stamp:
            return None
        self._shelf_stamp = stamps
        try:
            import shelf_card as shelf_card_mod
        except Exception:                        # noqa: BLE001
            log.debug("shelf: no painter", exc_info=True)
            return None
        with self._last_lock:
            last = dict(self._last) if self._last else None
        dark = False
        try:
            awake = getattr(self, "awake", None)
            dark = bool(awake.state().get("dark")) if awake is not None \
                else False
        except Exception:                        # noqa: BLE001
            dark = False
        return shelf_card_mod.card_for(
            state, self._shelf_pile(),
            {"text": (last or {}).get("final", ""),
             "at": (last or {}).get("when", "")},
            dark, max_rows=card.rows)

    def _shelf_refresh(self) -> dict | None:
        """The panel's own once-a-second question, answered on its
        refresher thread (shelf.ShelfCard._refresh_loop).

        None means "nothing you are showing has changed", and that is the
        usual answer: the stores are compared by stamp before anything is
        read, and the only thing that moves on its own is the uptime line,
        which changes once a minute.
        """
        card = getattr(self, "shelf", None)
        if card is None or not card.visible():
            return None
        shown = card.current() or {}
        fresh = self._shelf_card()
        if fresh is not None:
            return fresh
        # Nothing in the stores moved. Rebuild only if the head would
        # actually read differently — a repaint a second of an identical
        # picture is the one thing this panel promised not to do.
        state = self._shelf_state()
        try:
            import shelf_card as shelf_card_mod
            words = shelf_card_mod.uptime_words(state["uptime_s"])
        except Exception:                        # noqa: BLE001
            return None
        same = (state["mode"] == shown.get("mode")
                and state["stop_armed"] == shown.get("stop_armed")
                and " · ".join(p for p in (words, state["note"]) if p)
                == (shown.get("uptime") or ""))
        return None if same else self._shelf_card(force=True)

    def _shelf_pressed(self, what) -> None:
        """A click on the panel, already resolved by shelf_card.action_at.

        ARRIVES ON THE PAINTER'S THREAD, so every branch below either
        enqueues, flips a flag, or starts a thread — the rule
        _notify_dismissed's docstring states and the reason the panel's
        pump can never be made to wait on a disk or the clipboard.
        """
        try:
            if not what:
                return
            if what[0] == "row":
                self._shelf_row(str(what[2]), what[3])
            elif what[0] == "chrome":
                self._shelf_chrome(str(what[1]))
        except Exception:                        # noqa: BLE001
            log.exception("the shelf could not act on %r — dictation is "
                          "unaffected", what)

    def _shelf_row(self, do: str, ident) -> None:
        """One of a row's two answers. Every one of these is a method the
        cards already call: the panel is a second door onto the same
        answers, never a second implementation of them."""
        source, _, verb = do.partition(".")
        if source == "notify":
            if verb == "open":
                self._notify_opened(ident)
            else:
                self._notify_dismissed(ident)
        elif source == "review":
            self._review_verdict(str(ident),
                                 "accepted" if verb == "accept"
                                 else "rejected")
        elif source == "problem":
            if verb == "open":
                open_dashboard()
            else:
                threading.Thread(target=self._shelf_problem_close,
                                 args=(str(ident),), daemon=True,
                                 name="shelf-problem").start()
        elif source == "question":
            if verb == "answer":
                threading.Thread(target=self._shelf_question, daemon=True,
                                 args=(str(ident),),
                                 name="shelf-question").start()
            else:
                self._q_hushed[str(ident)] = (time.monotonic()
                                              + QUESTION_REASK_S)
                log.info("questions: %s waved away from the shelf — back in "
                         "about %.0f min", ident, QUESTION_REASK_S / 60.0)
        else:
            return
        if do in self._SHELF_LEAVES:
            self._shelf_close()
        else:
            self._shelf_push()

    def _shelf_problem_close(self, ident: str) -> None:
        """Answered, and problems.md rewritten. Own thread: the store
        takes a cross-process lock and the digest is written from scratch
        every time — the same two steps the dashboard's own Close does
        (dashboard._write_digest), and forgetting the second one leaves
        the file the weekly routine reads a week out of date."""
        store = getattr(self, "problems", None)
        if store is None:
            return
        try:
            store.resolve(ident, problems_mod.CLOSED, by="shelf")
            problems_mod.digest(store, paths.PROBLEMS_FILE.with_name(problems_mod.DIGEST_NAME))
            self._say("report closed")
        except Exception:                        # noqa: BLE001
            log.exception("shelf: could not close %s", ident)

    def _shelf_question(self, ident: str) -> None:
        """The real question card, on the real question. The shelf never
        tries to BE that card — it has two to five options and a text box
        — it just stops standing in front of it."""
        store = getattr(self, "questions", None)
        if store is None:
            return
        item = store.get(ident)
        card = self._answer_box()
        if item is None or card is None:
            return
        self._question_show(card, item)

    def _shelf_chrome(self, name: str) -> None:
        """The panel's own buttons. Pause and Screens change something the
        panel is SHOWING, so they refresh it in place; the two doors
        replace it, so they close it."""
        try:
            import shelf_card as shelf_card_mod
        except Exception:                        # noqa: BLE001
            return
        card = getattr(self, "shelf", None)
        if name == shelf_card_mod.CLOSE:
            # The X on the head band: the same door the key, Esc and a
            # second click on the dot all go through.
            self._shelf_close()
            return
        if name == shelf_card_mod.PAUSE:
            self.set_paused(not self.machine.paused)
            self._shelf_push()
            return
        if name == shelf_card_mod.STOP:
            self._shelf_stop(card)
            return
        if name == shelf_card_mod.COPY:
            with self._last_lock:
                text = (self._last or {}).get("final", "")
            if not text:
                self._cue_once("noop", "shelf-copy")
                self._say("nothing dictated yet")
                return
            # ON A THREAD, and this is not caution: injector._board_lock
            # is shared with the whole process and the longest thing on it
            # holds it for 2.1 s (control_command's copy_last says the
            # same). The panel's pump may not wait on that.
            threading.Thread(target=self._copy_text, args=(text,),
                             daemon=True, name="shelf-copy").start()
            self._say(f"{len(text)} chars copied")
            self._shelf_close()
            return
        if name == shelf_card_mod.SCREENS:
            threading.Thread(target=self._shelf_screens, daemon=True,
                             name="shelf-screens").start()
            return
        if name in (shelf_card_mod.DOOR, shelf_card_mod.MORE):
            open_dashboard()
            self._shelf_close()

    def _shelf_screens(self) -> None:
        """The screens off or back, then the row says which. Own thread:
        the engine may spawn a process."""
        try:
            state = self.awake.toggle(by="shelf")
            self._say("screens off — the machine stays awake" if
                      state.get("dark") else "screens on")
        except Exception:                        # noqa: BLE001
            log.exception("shelf: the screens would not switch")
        self._shelf_push()

    def _shelf_stop(self, card) -> None:
        """Quitting, armed. The first press turns the word into a
        question and the second one quits, because there is no undo for a
        quit and this panel opens with one keystroke.

        THE DASHBOARD'S STOP NO LONGER ARMS and this one still does, on
        purpose. The bar's arming went on 2026-09-07 because he read
        "Stop again" and could not tell what it was for; what replaced it
        there is geometry — Stop moved 168 px away from the button he
        presses all day and is not drawn at all while there is nothing to
        stop. That fix has nowhere to go here. The head band is three
        plates 8 px apart (`shelf_card.regions`: CLOSE, then STOP, then
        PAUSE), so this Stop is one slip from Pause AND one slip from the
        X that closes the panel, on an overlay that opens on a keystroke
        in the corner of the screen. Its word is also legible in a way
        the bar's was not: it turns into "Stop?" and goes red, rather
        than adding a word. If he asks for this one too, take the arming
        out — but move the button first.

        REFUSED WHILE A RECORDING IS RUNNING, out loud. The rectangle
        stays claimed either way: a button that disappears leaves a hole
        that answers HTTRANSPARENT, and in this corner the pixel
        underneath is the close button of every maximised window — the
        trap the status dot paid for once already.
        """
        shown = (card.current() if card is not None else None) or {}
        if not shown.get("stop_ok", True):
            self._cue_once("noop", "shelf-stop")
            self._say("not while the microphone is live — finish the "
                      "dictation first")
            log.info("shelf: Stop refused, a recording is running")
            return
        if not self._shelf_stop_armed:
            self._shelf_stop_armed = True
            self._say("press Stop again to quit")
            self._shelf_push()
            return
        log.info("shelf: Stop pressed twice — quitting")
        self._shelf_close()
        threading.Thread(target=singleton.request_quit, daemon=True,
                         name="shelf-stop").start()

    def _save_shelf_card(self, fields: dict) -> None:
        """Where the panel was dragged to, written into [shelf] through
        the same comment-keeping line edit every other card uses."""
        scfg = getattr(self.cfg, "shelf", None)
        if scfg is None:
            return
        self.cfg = dataclasses.replace(
            self.cfg, shelf=dataclasses.replace(scfg, **fields))
        self._save(
                              {f"shelf.{k}": v for k, v in fields.items()})
        log.info("shelf: %s", ", ".join(f"{k}={v}" for k, v in fields.items()))

    def _shelf_power(self, scfg) -> None:
        """Rebuild the panel from a changed [shelf] — switched on or off,
        moved, resized, or given a different `rows` from the dashboard.

        _hint_power's shape and for its reason: the old card's thread is
        joined and the new one's waited for, and this is called from the
        control pipe, which has to answer at once.
        """
        def swap() -> None:
            old = getattr(self, "shelf", None)
            new = None
            if scfg is not None and scfg.enabled:
                try:
                    import shelf as shelf_mod
                    new = shelf_mod.ShelfCard(
                        corner=scfg.corner, x=scfg.x, y=scfg.y,
                        scale=scfg.scale, rows=getattr(scfg, "rows", 5),
                        on_change=self._save_shelf_card,
                        on_press=self._shelf_pressed,
                        on_refresh=self._shelf_refresh,
                        on_away=self._shelf_close,
                        spare=self._dot_squares,
                        dot_corner=getattr(self, "_dot_corner",
                                           "bottom-right"),
                        dot_at=self._dot_beside
                        if getattr(scfg, "follow_dot", True) else None)
                except Exception:                # noqa: BLE001
                    log.info("the shelf would not rebuild", exc_info=True)
                    new = None
            if old is not None:
                old.stop()
            self.shelf = new
            if new is not None:
                new.start()
        threading.Thread(target=swap, daemon=True, name="shelf-swap").start()

    def _tap_problem(self) -> None:
        """One key, one line, and the app attaches the rest of the report.

        On a thread, like every tap: the grab alone is 47-57 ms and the
        JPEG another 60 (visual_qa.py measured both), and nothing that
        slow may run inside the keyboard hook's 300 ms — a stall there
        does not slow this feature down, it drops every keystroke on the
        machine.

        The card is checked HERE rather than left for ask() to drop the
        second press, because a screen grab taken for a card that will not
        open is a tenth of a second spent on nothing.
        """
        # Both by getattr and both `is None`, never truthiness: this runs
        # inside the keyboard hook, where an AttributeError is a dropped
        # hook and a frozen keyboard, and a Store that happens to be empty
        # must not read as "the feature is off".
        card = getattr(self, "_problem_card", None)
        if getattr(self, "problems", None) is None:
            return
        if card is None:
            log.info("problems: this overlay has no report card — the key "
                     "does nothing until it lands")
            return
        if card.open():
            log.info("problems: the card is already up — ignoring the press")
            return
        threading.Thread(target=self._problem_ask, daemon=True,
                         name="problem-key").start()

    def _problem_ask(self) -> None:
        """The screen, then the card, then the report. Own thread.

        Order matters and is the reason this is one method: the grab has
        to happen before the card exists, or the report is a photograph
        of the question instead of the problem. The bytes go STRAIGHT to
        the card — it shows them as its thumbnail — and the same bytes go
        to record() if he sends, so one grab serves both and nothing
        reaches the disk for a card he escapes.
        """
        pcfg = getattr(self.cfg, "problems", None)
        jpeg = (self._problem_shot(pcfg)
                if getattr(pcfg, "shot", True) else None)
        last = self._problem_last()
        # What the key can honestly say the report is ABOUT: a fresh
        # dictation is attached and named as the place, and with none this
        # is about the app rather than about a transcript. One value for
        # two jobs — the card draws it as its eyebrow ("ON DICTATION")
        # and problems.record files it as `where`.
        where = "dictation" if last else "anywhere"

        def done(text, kind="") -> None:
            # Escape and Cancel both answer None, and an empty card
            # answers "" — all of them mean he changed his mind, and none
            # is worth a file on disk. Stripped again even though the card
            # already does: this is the gate that keeps a blank line out
            # of record()'s ValueError, and it should not depend on which
            # window called it.
            if (text or "").strip():
                sending = getattr(self._problem_card, "last", None) or {}
                self._problem_file(text, where, last, jpeg, kind,
                                   send=bool(sending.get("send")),
                                   attach=sending.get("attach"))

        # The strip's sizes: what the JPEG, the last recording and the
        # settings weigh, before any of it is filed.
        try:
            sizes = problems_mod.sizes_before_filing(
                jpeg=jpeg, last=last, cfg=self.cfg, app_dir=paths.DATA_DIR)
        except Exception:                 # noqa: BLE001 — a size is a bonus
            sizes = None

        # `kinds` deliberately not passed: problem_card.card_for reads
        # problems.KINDS itself when it is not told, so the chips on this
        # card and the ones the dashboard offers cannot drift apart.
        if not self._problem_card.ask(where, done, shot=jpeg, sizes=sizes):
            log.info("problems: the card was taken between the press and "
                     "the grab — nothing filed")

    def _problem_shot(self, pcfg) -> bytes | None:
        """The screen as it was at the press, as JPEG bytes.

        Bytes, not a file: problems.pin_shot writes what it is handed, so
        nothing here needs a temp file and a failed report leaves no
        litter. PIL and visual_qa are imported lazily because most runs
        of this app never photograph anything and both cost real seconds
        on a cold process.
        """
        try:
            from PIL import ImageGrab
            import visual_qa as visual_qa_mod
            started = time.monotonic()
            image = ImageGrab.grab(all_screens=True).convert("RGB")
            jpeg = visual_qa_mod.encode_jpeg(
                image, int(getattr(pcfg, "max_side_px", 0) or 1344))
            log.debug("problems: froze %dx%d into %d KB in %.0f ms",
                      image.width, image.height, len(jpeg) // 1024,
                      (time.monotonic() - started) * 1000)
            return jpeg
        except Exception:
            # A report with no picture is still a report, and this is the
            # only piece of one that needs an imaging library at all.
            log.info("problems: could not photograph the screen",
                     exc_info=True)
            return None

    def _problem_last(self) -> dict | None:
        """The dictation this report should blame, or None.

        Read under the lock, like every other reader of `_last` (see
        _correct). AGE IS THE WHOLE OF THIS METHOD — see
        PROBLEM_LAST_MAX_S for why a stale clip is worse than no clip. An
        unreadable stamp attaches the dictation anyway: that is a bug in
        how it was written down, not evidence that it is old.
        """
        with self._last_lock:
            last = dict(self._last) if self._last else None
        if not last:
            return None
        try:
            when = time.mktime(time.strptime(last.get("when") or "",
                                             "%Y-%m-%d %H:%M:%S"))
        except (ValueError, OverflowError):
            return last
        return last if time.time() - when <= PROBLEM_LAST_MAX_S else None

    def _deliver_to_prompt(self, text: str) -> bool:
        """Put a finished transcription into the report card's field.

        visual_qa.deliver_transcript's contract exactly, including the
        return: False means the card is not there to take it any more (or
        cannot), and the caller should treat the words as a dictation that
        lost its destination — it is in transcripts.log either way.

        FILLED, NOT SUBMITTED, and that distinction is the whole method.
        `answer()` is what ENTER does — it sets the result and closes the
        card — so using it here would file the report the instant the
        transcription came back, with him never having seen the sentence.
        The card exists so he can read what was heard (its echo line
        draws the bidi properly, which the field cannot), fix a word and
        press Enter himself; a decoder that mishears one word must not
        turn into a bug report that says the wrong thing.
        """
        card = getattr(self, "_problem_card", None)
        if card is None or not card.open():
            log.info("problems: the report card closed before the "
                     "transcription landed")
            return False
        # Asked of the object rather than assumed of the class, so an
        # overlay whose card cannot be dictated into says so and the
        # caller falls back to the clipboard instead of losing the words.
        fill = getattr(card, "fill", None)
        if fill is None:
            log.warning("problems: this overlay's report card cannot be "
                        "filled by voice — it has no fill()")
            return False
        try:
            return fill(text) is not False
        except Exception:
            log.exception("problems: could not put the dictation into the "
                          "report card")
            return False

    def _problem_file(self, text: str, where: str, last, jpeg,
                      kind: str = "", *, send: bool = False,
                      attach: dict | None = None) -> None:
        """Write the report. From the card's own thread, after it is gone.

        No success cue: the card disappearing is the confirmation, and
        every sound in cues.py already means something else — a new note
        for this would be a fifth member of a family the ear has to tell
        apart mid-sentence, bought for a key pressed twice a week.

        `kind` is the chip he pressed, passed straight through rather
        than defaulted here: problems.clean admits it against KINDS and
        falls back to the first one, so an empty string from a card that
        never offered chips still files as the default and a fifth kind
        added to problems.KINDS needs no change on this side.

        `send` is "Send to the developer" (plan 7.6, screen 7). The
        report is filed here exactly as without it; what the tick adds
        is a mark on the row — PREVIEW, with the four toggles — and the
        dashboard opened on Problems, where the Preview shows the whole
        of what would leave and Send there is what makes the copy. The
        dashboard is another process, so the row is the message: it
        looks for a report awaiting its preview when it comes up.

        record() only raises ValueError, and only for an empty line that
        `done` has already refused; the broad except is here because this
        thread has nothing left to protect and a report lost quietly is
        still better than a traceback out of a UI callback.
        """
        try:
            item = problems_mod.record(paths.DATA_DIR,
                                       {"text": text, "where": where,
                                        "kind": kind},
                                       cfg=self.cfg, last=last, jpeg=jpeg)
        except Exception as e:
            beep("error")
            self._say(f"could not file that problem: {e}")
            log.exception("problems: could not file the report")
            return
        if send:
            try:
                store = problems_mod.Store(paths.PROBLEMS_FILE)
                problems_mod.mark_preview(store, item["id"], attach)
                # A second launch of the desk signals the first and
                # exits (dashboard.main), so this is right either way.
                open_dashboard()
                self._say(f"problem {item['id']} noted — the preview of "
                          "what would be sent is on the Problems screen")
            except Exception:                 # noqa: BLE001
                log.info("problems: %s is filed; the preview could not be "
                         "opened", item["id"], exc_info=True)
                self._say(f"problem {item['id']} noted — open Problems on "
                          "the desk to preview and send it")
        else:
            self._say(f"problem {item['id']} noted — {item['text'][:60]}")
        log.info("problems: %s filed from the key, %s%s%s", item["id"],
                 "with the last dictation" if last else "with no dictation",
                 ", with a screenshot" if item.get("shot") else "",
                 ", awaiting its preview" if send else "")

    # ---- the weekly routine's question (questions.py) ----
    #
    # The report key's mirror image, and every difference between the two
    # comes from one fact: NOBODY PRESSES A KEY FOR THIS ONE. The report
    # card opens because he asked for it, at a moment he chose, with his
    # hands already on the keyboard. This card opens because a headless
    # process wrote a question into questions.json — on a Saturday at
    # 04:00, quite possibly while he was asleep — and the app has to both
    # notice it and pick the moment. So there are two mechanisms here that
    # the report side has no need of at all: a poll (questions.Store.stamp,
    # which is why it exists) and a gate (_questions_quiet, which is the
    # strictest in this file).
    #
    # Nothing below may raise into anything that matters. The watch is its
    # own daemon thread, the store write and the wake are a thread of their
    # own off the card's pump, and the one line that runs inside the
    # keyboard hook is an assignment (see _popup_key). A broken question
    # card must cost the card and never the dictation.

    def _save_answer_card(self, fields: dict) -> None:
        """The question card's twin of _save_problem_card: where it was
        dragged to, written into [questions] through the same
        comment-keeping line edit.

        Guarded the same way and for the same reason, only more so — this
        section may not exist AT ALL yet, not merely be missing two
        fields, so a `dataclasses.replace` would raise on the section
        before it raised on the field. What is lost while that is true is
        the restart and never the drag: the card's own instance keeps the
        position for the rest of the run either way.
        """
        qcfg = getattr(self.cfg, "questions", None)
        if qcfg is None or not dataclasses.is_dataclass(qcfg):
            log.info("question card: there is no [questions] section to "
                     "save a drag in yet — it stays put for this run only")
            return
        known = {f.name for f in dataclasses.fields(qcfg)}
        missing = sorted(set(fields) - known)
        if missing:
            log.info("question card: [questions] has no %s to save a drag "
                     "in yet — it stays put for this run only",
                     ", ".join(missing))
            return
        self.cfg = dataclasses.replace(
            self.cfg, questions=dataclasses.replace(qcfg, **fields))
        self._save(
                              {f"questions.{k}": v for k, v in fields.items()})
        log.info("question card: %s",
                 ", ".join(f"{k}={v}" for k, v in fields.items()))

    def _questions_quiet(self, now: float) -> bool:
        """May a question card take the foreground RIGHT NOW?

        `_learning_quiet` is most of the answer already and is reused
        rather than re-derived: ready and idle, not recording, not
        transcribing, not paused, nothing queued, no text key in flight
        and neither screen feature busy. Paused matters more here than it
        does there — paused usually means a game or a presentation owns
        the screen, and a window that takes the foreground over one costs
        him the thing he was doing, not just some GPU time.

        Two things are added to it.

        The first is the other windows in this process that TAKE THE
        KEYBOARD: the pencil's word box, the report card, the ask card and
        a question card already up. The AnswerCard comes down the
        WordPrompt side of overlay's tree exactly as ProblemCard does, so
        a second one opening over the first would pull the caret out of a
        box he is in the middle of typing into.

        The second is HIS HANDS, and it is the one signal that is not
        about this app at all. `_q_last_key` is written by the keyboard
        hook on every real key-down anywhere on the machine, so a still
        app with a busy keyboard — he is answering mail, the app has
        nothing to do — reads as busy here, which is right. It also covers
        the gap between two polls twenty seconds apart: a whole dictation
        can start and finish in there, and its hotkey press went through
        the hook like every other key.

        What it cannot see is the mouse, and that is accepted rather than
        fixed: a mouse hook is a second low-level hook on the machine for
        a card that can afford to arrive five minutes late.
        """
        if now - self._q_last_key < QUESTION_SETTLE_S:
            return False
        for name in ("_word_prompt", "_problem_card", "_answer_card"):
            box = getattr(self, name, None)
            if box is None:
                continue
            try:
                if box.open():
                    return False
            except Exception:            # noqa: BLE001
                return False             # a box we cannot ask about is a no
        if self._ask_card_open():
            return False
        return self._learning_quiet()

    def _answer_box(self):
        """The question card, built on first need, or None.

        Looked up rather than named — `getattr(overlay_mod, "AnswerCard")`
        — for the reason the report card is looked up: the class lands with
        answer_card.py's other half, and until it does this feature has to
        say so once and leave the questions in the dashboard, not take the
        app down at startup.

        Built HERE and not in __init__ so that a class whose signature has
        moved costs one log line on the watch thread instead of a process
        that will not start. Never on the hook thread either way: building
        it imports Tk.
        """
        card = getattr(self, "_answer_card", None)
        if card is not None or self._q_no_card:
            return card
        card_cls = getattr(overlay_mod, "AnswerCard", None)
        if card_cls is None:
            self._q_no_card = True
            log.info("questions: this overlay has no question card — the "
                     "%d question(s) wait in the dashboard until it lands",
                     len(self._q_pending))
            return None
        qcfg = getattr(self.cfg, "questions", None)
        unset = getattr(config_mod, "HINT_UNSET", -100000)
        try:
            # Where it was last dragged to and where to write the next
            # drag, which is the hint/review/notify/report shape and the
            # one this card's own `placed` asks for by name. x and y
            # through getattr because they land with the config half of
            # this feature: HINT_UNSET is the "never moved" sentinel, a
            # number no desktop can reach, because a monitor left of the
            # primary has genuinely negative coordinates and -1 would
            # throw a real position away.
            card = card_cls(
                x=int(getattr(qcfg, "x", unset) if qcfg is not None
                      else unset),
                y=int(getattr(qcfg, "y", unset) if qcfg is not None
                      else unset),
                on_change=self._save_answer_card)
        except Exception:                # noqa: BLE001
            self._q_no_card = True
            log.exception("questions: the question card would not build — "
                          "the questions wait in the dashboard")
            return None
        self._answer_card = card
        return card

    def _watch_questions(self) -> None:
        """Notice a new pending question, and put it up when it is safe.

        Its own daemon thread, ended by the same `_stopping` event the
        fullscreen watcher waits on. Everything inside is wrapped: this
        thread may log a bad week, and may not end one.
        """
        while not self._stopping.wait(QUESTION_POLL_S):
            try:
                self._questions_tick()
            except Exception:            # noqa: BLE001
                log.exception("questions: the question watch stumbled — "
                              "dictation is unaffected")

    def _questions_tick(self) -> None:
        """One look at the store, and at most one card."""
        store = getattr(self, "questions", None)
        if store is None:
            return
        stamp = store.stamp()
        if stamp != self._q_stamp:
            # The file changed (or this is the first look): re-read it
            # once. OLDEST FIRST — `items` hands them back newest first,
            # and a question that has been waiting since last Saturday
            # goes before one written this morning.
            self._q_stamp = stamp
            self._q_pending = list(
                reversed(store.items(_questions_mod().PENDING)))
            log.info("questions: %d waiting on him", len(self._q_pending))
        if not self._q_pending:
            return
        now = time.monotonic()
        item = next((row for row in self._q_pending
                     if self._q_hushed.get(str(row.get("id") or ""), 0.0)
                     <= now), None)
        if item is None or not self._questions_quiet(now):
            return
        card = self._answer_box()
        if card is None:
            return
        self._question_show(card, item)

    def _question_show(self, card, item: dict) -> None:
        """Open the card on one question. From the watch thread.

        Nothing is taken off `_q_pending` here. What keeps the next poll
        from opening a second card is `_questions_quiet` asking the card
        whether it is up (and `ask` itself refusing a second one), and
        what takes the question off the list afterwards is the store: an
        answer changes the stamp, the next tick re-reads, and an answered
        question is no longer PENDING. An ESCAPED one has to stay on the
        list, because it is still pending and still his to answer.
        """
        ident = str(item.get("id") or "")

        def done(choice=None, text="") -> None:
            """The card's answer, on the card's own Tk thread.

            (None, "") is Escape, and it records NOTHING — the store is
            not touched, the question stays PENDING and it comes back.
            Hushed for QUESTION_REASK_S first: "not now" that returns in
            twenty seconds is not "not now".

            Anything real goes to a thread of its own, which is
            _notify_dismissed's rule and for the same two reasons — the
            store takes a cross-process lock and the wake starts a
            process, and neither belongs in a painter's pump.
            """
            try:
                if choice is None and not str(text or "").strip():
                    self._q_hushed[ident] = (time.monotonic()
                                             + QUESTION_REASK_S)
                    log.info("questions: %s waved away — back in about "
                             "%.0f min", ident, QUESTION_REASK_S / 60.0)
                    return
                threading.Thread(
                    target=self._question_answered,
                    args=(ident, choice, str(text or "")), daemon=True,
                    name="question-answer").start()
            except Exception:            # noqa: BLE001
                log.exception("questions: the answer to %s could not be "
                              "handed on", ident)

        try:
            opened = bool(card.ask(item, done, focus=True))
        except Exception:                # noqa: BLE001
            # A signature that has moved under us, or a card that will not
            # draw. One question is worth one log line and no more: the
            # class is marked absent so the watch stops trying every
            # twenty seconds, and the dashboard still has the question.
            self._q_no_card = True
            self._answer_card = None
            log.exception("questions: the question card would not open — "
                          "the questions wait in the dashboard")
            return
        if not opened:
            log.info("questions: a card is already up — %s waits", ident)
            return
        log.info("questions: asked him %s on screen (%d option(s), about "
                 "%s)", ident, len(item.get("options") or ()),
                 item.get("report_id") or "nothing in particular")
        self._say("a question from the weekly review is on screen")

    def _question_answered(self, ident: str, choice, text: str) -> None:
        """His answer: written down, then the routine woken. Own thread.

        The order is not negotiable. The routine reads the store to find
        out what it may build, so waking it before the answer is on disk
        would wake it to nothing — and it would then write today's `.done`
        stamp over a run that did no work.
        """
        store = getattr(self, "questions", None)
        if store is None:
            return
        try:
            ok = store.answer(ident, choice=choice, text=text, by="card")
        except Exception:                # noqa: BLE001
            # questions.answer swallows its own OSErrors, so this is the
            # unexpected kind. Never fatal: a lost answer is a question he
            # gets asked again.
            log.exception("questions: could not record the answer to %s",
                          ident)
            return
        if not ok:
            # False is a real outcome and has three causes, and the one
            # that matters is the third: the dashboard may have answered
            # this same question in the other window while this card was
            # up. A decision he has already made must not be overwritten,
            # and must not fire a second build.
            log.info("questions: %s was not recorded — nothing answered, or "
                     "it was already answered elsewhere", ident)
            self._say("that question was already answered elsewhere")
            self._q_hushed[ident] = time.monotonic() + QUESTION_REASK_S
            return
        log.info("questions: %s answered from the card (option %s%s)",
                 ident, "none" if choice is None else choice,
                 ", with text" if text.strip() else "")
        self._say("answer saved — the weekly review is starting on it")
        self._q_hushed.pop(ident, None)
        self._wake_review(ident)

    def _wake_review(self, ident: str) -> None:
        """THE MOMENT HE ANSWERS, THE ROUTINE WAKES AND WRITES THE CODE.

        `weekly_review.ps1 -Answered`: the same script the Saturday task
        runs, with the switch that ignores today's `.done` stamp, because
        a new answer is new work even though this morning's scan finished.
        The script's own lock is what keeps this from starting a second
        review on top of a running one — that is its job, not ours, and it
        is why this can be fire-and-forget.

        And fire-and-forget it is: a review is minutes of work, and this
        is a thread inside a dictation app. Nothing waits on it, nothing
        reads its output (it has a log), and its console never appears —
        CREATE_NO_WINDOW, the flag awake.py and visual_qa.py already spawn
        powershell with, because a window flashing on his screen every
        time he answers a question is its own bug report.
        """
        script = APP_DIR / "weekly_review.ps1"
        if not script.is_file():
            log.warning("questions: %s is missing — %s is answered and "
                        "waiting, and the next Saturday run will build it",
                        script.name, ident)
            return
        args = ["powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(script),
                "-Answered"]
        try:
            subprocess.Popen(args, cwd=str(APP_DIR),
                             creationflags=CREATE_NO_WINDOW, close_fds=True,
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception:                # noqa: BLE001
            # The answer is safely on disk either way, which is the half
            # that cannot be redone. A wake that failed costs him a wait,
            # not a decision.
            log.exception("questions: could not wake the weekly review for "
                          "%s — it will be built on the next run", ident)
            return
        log.info("questions: woke the weekly review for %s "
                 "(weekly_review.ps1 -Answered)", ident)

    def _on_overflow(self) -> None:  # PortAudio callback thread
        beep("error")
        log.warning("recording passed the %.0f s cap — discarding. %s",
                    self._cap,
                    "Tap the latch key to clear it."
                    if self._latched else "Release the key.")

    def _on_silent(self) -> None:  # PortAudio callback thread
        """Ten seconds in and the microphone has heard nothing above
        recorder.SILENT_PEAK: a headset on mute, or unplugged. The dot
        blinks red and slides to the middle of the screen — where he is
        looking — and the recording goes on; the alarm is information,
        not a decision (report 20260910-190110, in his words: "רק שתתריע
        לי על זה שאני אדע"). Once per recording; the recorder sees to
        that. Nothing here blocks: alarm() writes one float."""
        self.dot.alarm(True)
        log.warning("no sound for %.0f s into this recording (peak %.4f "
                    "< %.2f) — is the microphone muted or unplugged?",
                    SILENT_AFTER_S, self.recorder.peak(), SILENT_PEAK)

    def _on_sound(self) -> None:  # PortAudio callback thread
        """Sound arrived after the alarm: the dot goes back to its corner.
        Once per recording, like the alarm it answers."""
        self.dot.alarm(False)
        log.info("sound arrived — the microphone is live after all")

    # ---- worker thread ----

    def _local_backend(self):
        """Build the local backend on first need. Returns None when it is
        unavailable (not installed, or still the stub) — the caller then
        reports the original cloud error rather than a confusing one."""
        if self._local is not None:
            return self._local or None
        if not self.cfg.fallback_to_local or self.cfg.backend == "local":
            self._local = False
            return None
        try:
            from transcribers import local_kwargs
            from transcribers.local_whisper import LocalWhisperTranscriber
            log.info("cloud quota spent — loading the local model (first "
                     "run downloads it; this takes a while)...")
            self._local = LocalWhisperTranscriber(
                **local_kwargs(self.cfg, self._hotwords))
            log.info("local backend ready — dictation continues offline")
        except Exception as e:
            log.warning("no local fallback available: %s", e)
            self._local = False
            return None
        return self._local

    @staticmethod
    def _call(backend, wav: bytes, language: str | None) -> str:
        """Pass the chosen language through when the backend supports it.

        The signature is inspected rather than catching TypeError, so a
        genuine TypeError raised *inside* a backend is not silently retried
        as if the backend simply lacked the parameter.
        """
        try:
            takes_language = "language" in inspect.signature(
                backend.transcribe).parameters
        except (TypeError, ValueError):
            takes_language = False
        if takes_language:
            return backend.transcribe(wav, language=language)
        return backend.transcribe(wav)

    def _transcribe_pieces(self, pieces: list,
                           language: str | None = None) -> tuple[str, str]:
        """A recording the ask card interrupted, as one continuous text.

        The stretches AROUND each question go to Whisper. The questions
        themselves do not: they were transcribed the moment they were
        spoken, alone, and that is the only transcript of them that can be
        relied on. Whisper's VAD drops a short utterance stranded between
        two long silences, and a question asked mid-dictation is exactly
        that shape — measured 2026-08-31 on a real 35 s recording, where
        "four" was in the audio, correct in its own slice, and simply
        missing from the transcript of the whole file.

        If the remembered text is not there after all (nothing was heard,
        or the card was closed before it landed) the piece is transcribed
        like any other rather than dropped. Losing audio is worse than
        transcribing it twice.
        """
        asked = list(self._question_texts)
        self._question_texts = []
        out: list[str] = []
        backend = ""
        for was_question, part in pieces:
            said = asked.pop(0).strip() if (was_question and asked) else ""
            if not said:
                said, used = self._transcribe(part, language)
                backend = used or backend
                said = said.strip()
            if said:
                out.append(said)
        return " ".join(out), backend or "local"

    def _transcribe(self, wav: bytes,
                    language: str | None = None,
                    head=None) -> tuple[str, str]:
        """Cloud first; local only once every cloud model is out of quota.

        Serialised: the phone endpoint runs on its own threads and would
        otherwise hit the same Whisper model as the desktop worker at the
        same moment. This is the one choke point both paths pass through.

        `head` is what the rolling transcriber finished while the key was
        held (rolling.Head): the backend that made it decodes only the
        tail after it. Any other backend — the cloud, or the local
        fallback under it — was not there and gets the whole recording.
        """
        with self._model_lock:
            try:
                if head is not None and hasattr(self.transcriber,
                                                "transcribe_with_head"):
                    text = self.transcriber.transcribe_with_head(
                        wav, head, language=language)
                else:
                    text = self._call(self.transcriber, wav, language)
                self._last_words = list(
                    getattr(self.transcriber, "last_words", None) or [])
                # The windows this text was joined from (rolling), [] for
                # a whole decode — read HERE, off the backend that ran,
                # so a stale list from an earlier dictation is never
                # mistaken for this one's.
                self._last_windows = list(
                    getattr(self.transcriber, "last_windows", None) or [])
                return text, self.transcriber.name
            except (RateLimitError, TooLongForCloud) as e:
                local = self._local_backend()
                if local is None:
                    raise
                if isinstance(e, TooLongForCloud):
                    # never sent (plan 5.6): the card says why the
                    # cloud pass did not happen this once
                    self._say(str(e))
                    log.info("%s", e)
                text = self._call(local, wav, language)
                self._last_words = list(
                    getattr(local, "last_words", None) or [])
                self._last_windows = []
                return text, local.name

    def _worker(self) -> None:
        while True:
            item = self.queue.get()
            wav, seconds, hwnd, language, to_card = item[:5]
            # Anything the ask card needs said about this recording, as
            # keywords. Five-field items — and every test that builds one
            # — mean the ordinary thing.
            extra = (item[5] if len(item) > 5 and isinstance(item[5], dict)
                     else {})
            try:
                self._handle(wav, seconds, hwnd, language, to_card, **extra)
            except Exception:
                beep("error")
                log.exception("unexpected failure handling a recording")
            finally:
                # Back to plain "running" however it went — a dot stuck on
                # amber would report a hang that isn't happening.
                #
                # UNLESS a dictation is still live underneath, which is
                # what a question asked from inside the ask card leaves
                # behind: that recording was never ended, so a dot turning
                # blue here would be announcing a stop that did not
                # happen. The owner reads that dot to know whether it is
                # still listening.
                self._set_state(_DOT_FOR.get(self.machine.state, "ready"))

    # ---- correction worker ----

    def _correct_worker(self) -> None:
        while True:
            last, hwnd = self.correct_queue.get()
            try:
                with self._cursor_lock:
                    self._correct(last, hwnd)
            except Exception:
                beep("error")
                log.exception("unexpected failure reading a correction")
            finally:
                self._correcting.clear()

    def _correct(self, last: dict, hwnd: int = 0) -> None:
        """Read the corrected text off the screen and learn from it.

        There is no edit box, and that is deliberate. The first version put
        the transcript in a Tk window to be fixed there, and Tk 8.6 has no
        bidi support at all: mixed Hebrew and English came out visually
        scrambled and the caret jumped around as it was typed into. The user
        is ALREADY fixing the text in the app it was pasted into — Chrome,
        Claude Code, anything with real bidi — so the correction exists on
        screen before this key is ever pressed. Reading it beats asking for
        it again in a worse editor.

        The diff is against the text the user SAW, not the raw backend
        output: if the repair pass already fixed something, re-learning it
        would inflate its hit count for a mistake that no longer happens.

        Most presses of this key legitimately learn NOTHING — the text has
        already been sent, or it was right the first time — so the three
        "nothing to do" answers below are not errors and must not sound
        like one. See _cue_once for what that cost before.
        """
        # Re-read rather than trusting the snapshot _tap_correct took on the
        # hook thread. Between that press and this worker getting the cursor
        # lock, a deferred context-pass repair may have landed and changed
        # the text on screen. Diffing the SCREEN (repaired) against a
        # snapshot from BEFORE the repair would learn the model's own edit
        # as though the user had typed it — and that pair goes straight into
        # the glossary the repair pass reads, and into Whisper's hotwords.
        # Matched on 'raw', which a repair never touches (it rewrites only
        # 'final'), so this adopts the repaired text for the SAME dictation
        # and declines to adopt a different one that arrived meanwhile.
        with self._last_lock:
            current = dict(self._last) if self._last else {}
        if current and current.get("raw") == last.get("raw"):
            last = current
        shown = last.get("final", "")
        tcfg = self.cfg.translate
        state = injector.snapshot()
        kept = injector.claim_mark()
        try:
            grabbed, _had_selection = injector.grab(
                tcfg.copy_chord, tcfg.select_all_chord, tcfg.settle_ms / 1000)
        except injector.ClipboardBusyError as e:
            self._cue_once("error", "clipboard")
            self._say("could not read the screen — the clipboard was locked")
            log.error("could not read the corrected text: %s", e)
            return
        finally:
            # grab() deliberately leaves what it copied on the clipboard; the
            # user never asked for that, so put theirs back either way.
            # Unless they copied something themselves in the meantime —
            # the lookup box is on screen with a copy button on it while
            # every other key still works. injector.claim_mark() says why.
            try:
                injector.restore(state, "clipboard", since=kept)
            except injector.ClipboardBusyError as e:
                log.warning("could not restore your clipboard: %s", e)

        if len(grabbed) > tcfg.max_chars:
            self._cue_once("error", "too-much")
            self._say(f"{len(grabbed)} chars is too much to search — select "
                      f"just the sentence you fixed")
            log.warning("refusing to search %d chars for the last transcript "
                        "(max_chars=%d) — select just the corrected text and "
                        "press the key again", len(grabbed), tcfg.max_chars)
            return

        fixed, ratio = vocab_mod.locate(shown, grabbed)
        if ratio < vocab_mod.MIN_MATCH:
            # Told apart because they need different things done about
            # them, and because "best match 0%" is a number, not a reason.
            if not grabbed.strip():
                why = ("there is no text where the cursor is — click into "
                       "the box holding what you dictated")
            elif ratio <= 0.01:
                why = ("what you dictated is not on screen any more — if "
                       "you already sent it, there is nothing left to read")
            else:
                why = (f"only {ratio:.0%} of it is still there (needs "
                       f"{vocab_mod.MIN_MATCH:.0%}) — select the corrected "
                       f"sentence and press again")
            self._cue_once("noop", "not-found")
            self._say(f"nothing learned: {why}")
            log.info("could not find the last transcript where the cursor is "
                     "(best match %.0f%%, need %.0f%%) — %s",
                     ratio * 100, vocab_mod.MIN_MATCH * 100, why)
            return
        if fixed.strip() == shown.strip():
            self._cue_once("noop", "unchanged")
            self._say("read it — the text is unchanged, so there is nothing "
                      "to learn")
            log.info("the text on screen is unchanged — nothing to learn")
            return

        # Diffed against the SCREEN, but filtered against the DECODER.
        # `shown` is post-apply, post-polish; where either of them rewrote a
        # word, the diff describes their edit and not a mishearing, and
        # learning it teaches the app that its own output is a Whisper
        # error. study.py has had this guard since it was written; the
        # human path did not, and on 2026-08-28 it learned "make -> commit"
        # off a bad rule's own rewrite. See vocab.heard_by_decoder.
        proposed = vocab_mod.diff_corrections(shown, fixed)
        pairs = self.vocab.learn_from_edit(shown, fixed,
                                           heard_in=last.get("raw", ""))
        refiled = len(proposed) - len(pairs)
        if refiled:
            log.info("ignored %d proposed pair(s) the decoder never said — "
                     "they are this app's own rewrite being handed back to "
                     "it: %s", refiled,
                     " | ".join(f"{h} -> {m}" for h, m in proposed
                                if (h, m) not in pairs))
        transcript_log.info("CORRECTED | %s || %s", shown, fixed)
        self._nudge_sync("vocab", "history")
        # What is on screen is now what the app believes it produced.
        # Without this, a second press of the key diffs the SAME edit
        # again and counts it as a second, independent correction — which
        # is how one real fix reaches replace_after_hits = 2 on its own and
        # starts rewriting that word automatically. Observed in app.log on
        # 2026-08-14: "memory הרווסטר -> anthropic-skills memory-harvester"
        # learned at 21:13:44 and re-learned at 21:14:29 from one edit.
        with self._last_lock:
            # Only if _last is still the dictation this correction was read
            # for. _handle publishes a new record under _last_lock alone and
            # only then waits on _cursor_lock, so a dictation that finished
            # during the grab above can already have replaced it — and
            # writing this correction into THAT record would attach one
            # utterance's fix to another one's audio. Matched on 'raw',
            # which neither a correction nor a repair rewrites.
            if (self._last is not None
                    and self._last.get("raw") == last.get("raw")):
                self._last["final"] = fixed.strip()
        # Tie the truth to the audio. This is what turns "it got this wrong"
        # into a test case: --benchmark replays these and reports whether a
        # vocabulary change actually helped, instead of leaving it to
        # impressions.
        wav = last.get("wav")
        if wav and self.recent is not None:
            from spool import SpooledItem
            try:
                self.recent.update(SpooledItem(Path(wav)),
                                   corrected=fixed.strip())
            except Exception as e:
                log.info("could not attach the correction to its audio: %s", e)
        if not pairs and refiled:
            # Everything the diff proposed was this app's own rewrite. The
            # edit is real and is in the log; what it does NOT contain is a
            # mishearing, so there is nothing for the vocabulary to key on.
            self._say("saved your edit — it undid a repair rather than "
                      "correcting what was heard, so no word swaps")
            log.info("correction saved to the log, but every pair in it was "
                     "the app's own repair being undone — nothing learned")
        elif not pairs:
            # The edit was an insertion or a rewrite, not a substitution:
            # real, but it teaches no "when you hear X, write Y" rule.
            # Saying so is better than a silent success the user then
            # expects to have changed something.
            self._say("saved your edit, but it taught no word swaps "
                      "(insertions have no misheard form to key on)")
            log.info("correction saved to the log, but it taught no word "
                     "swaps (only substitutions of up to %d words are "
                     "learned — an insertion has no misheard form to key "
                     "on)", vocab_mod.MAX_SPAN_WORDS)
        else:
            # app.log keeps the COUNT (D8: it never quotes text or a
            # learned pair); the pairs go to transcripts.log as LEARNED.
            log.info("learned %d correction(s)", len(pairs))
            for heard, meant in pairs:
                transcript_log.info("LEARNED | %s || %s", heard, meant)
            ready = sum(1 for c in self.vocab.corrections
                        if int(c.get("hits", 1))
                        >= self.cfg.vocab.replace_after_hits)
            self._say(f"learned {len(pairs)}: "
                      + " | ".join(f"{h} -> {m}" for h, m in pairs))
            self._bump(learned=len(pairs))
            log.info("vocabulary now %d entries (%d repaired automatically, "
                     "the rest are hotwords only until corrected %d times)",
                     len(self.vocab), ready,
                     self.cfg.vocab.replace_after_hits)
        beep("translated")

    # ---- the keys that act on text already on screen ----

    def _text_key_worker(self) -> None:
        while True:
            action, hwnd = self.text_queue.get()
            try:
                # Held across the whole grab-model-replace, not just the
                # keystrokes: these borrow the clipboard for the duration,
                # and a deferred context-pass repair landing in the middle
                # would restore a clipboard this is still using.
                with self._cursor_lock, privacy.pressed():
                    if action == "punctuate":
                        self._punctuate(hwnd)
                    else:
                        self._translate(hwnd)
            except Exception:
                beep("error")
                log.exception("unexpected failure while %sing", action)
            finally:
                self._text_busy.clear()

    def _translate(self, hwnd: int) -> None:
        """Replace the selection — or the whole field — with its English.

        The clipboard is saved once around the whole thing and restored on
        every exit path, including the failures: grabbing the text is what
        overwrites it, so an early return without a restore would leave the
        user's own clipboard silently destroyed.

        That pair is open for as long as the model takes to answer, and
        the lookup box can be read and copied from throughout it, so the
        mark taken here is what stops the restore from destroying a copy
        the user made in the middle — injector.claim_mark().
        """
        import translate as translate_mod

        tcfg = self.cfg.translate
        state = injector.snapshot()
        kept = injector.claim_mark()
        keep_clipboard = False
        try:
            text, had_selection = injector.grab(tcfg.copy_chord,
                                                tcfg.select_all_chord,
                                                tcfg.settle_ms / 1000)
        except injector.ClipboardBusyError as e:
            self._cue_once("error", "translate-clipboard")
            self._say("could not read the text to translate — the clipboard "
                      "was locked")
            log.error("could not read the text to translate: %s", e)
            return

        try:
            # The same three shapes as the correction key, and the same rule:
            # "there was nothing to do" is not a fault and must not sound
            # like one, nor repeat while the answer stays the same.
            what = "the selection" if had_selection else "the whole field"
            if not text.strip():
                self._cue_once("noop", "translate-empty")
                self._say(f"nothing to translate — {what} is empty")
                log.info("nothing to translate — %s is empty", what)
                return
            if len(text) > tcfg.max_chars:
                self._cue_once("error", "translate-too-much")
                self._say(f"{len(text)} chars is too much to translate — "
                          f"select the part you want")
                log.warning(
                    "refusing to translate %d chars from %s (max_chars=%d) "
                    "— that looks like a whole document, not a message. "
                    "Select the part you want and press the key again.",
                    len(text), what, tcfg.max_chars)
                return
            if not translate_mod.needs_translation(text, tcfg.target):
                self._cue_once("noop", "translate-not-hebrew")
                self._say(f"no Hebrew in {what} — already {tcfg.target}")
                log.info("no Hebrew in %s — already %s, leaving it alone",
                         what, tcfg.target)
                return

            beep("translating")
            log.info("translating %d chars from %s to %s...", len(text),
                     what, tcfg.target)
            # The original goes to the log BEFORE it is replaced on screen:
            # this file is the recovery path if the paste goes wrong.
            transcript_log.info("TRANSLATE-IN  | %s | %s", what, text)

            started = time.monotonic()
            if self._translator is None:
                self._translator = translate_mod.Translator(self.cfg)
            try:
                english, backend = self._translator.translate(text)
            except TranscriptionError as e:
                beep("error")
                log.error("translation failed: %s — your text is untouched",
                          e)
                return
            latency = time.monotonic() - started
            transcript_log.info("TRANSLATE-OUT | %.1fs | %s | %s", latency,
                                backend, english)

            if hwnd and injector.foreground_window() != hwnd:
                # The selection belongs to a window that is no longer
                # focused. Pasting now would overwrite whatever the user
                # switched to.
                injector.set_text(english)
                keep_clipboard = True   # restoring would take it back away
                beep("stop")
                log.warning("you moved to another window — the translation "
                            "is on your clipboard, press %s to paste it: %s",
                            self.cfg.paste_chord, english)
                return

            injector.paste_text(english, self.cfg.paste_chord,
                                self.cfg.restore_delay_ms)
            beep("translated")
            self._bump(translations=1)
            self._say(f"translated {len(text)} chars to {tcfg.target} in "
                      f"{latency:.1f} s via {backend}")
            log.info("translated %d chars in %.1f s via %s: %s", len(english),
                     latency, backend, english)
        except injector.ClipboardBusyError as e:
            beep("error")
            log.error("paste failed: %s — the translation is in "
                      "transcripts.log", e)
        finally:
            if not keep_clipboard:
                try:
                    injector.restore(state, "translation", since=kept)
                except injector.ClipboardBusyError as e:
                    log.warning("could not restore your clipboard: %s", e)

    def _punctuate(self, hwnd: int) -> None:
        """Put the punctuation into the selection — or the whole field.

        Deliberately the same shape as _translate, down to the clipboard
        being saved once around the whole thing and restored on every exit
        path: grabbing the text is what overwrites it, so an early return
        without a restore would silently destroy the user's own clipboard.

        What is NOT the same is the guarantee. A translation cannot be
        checked against its input by definition; a punctuation pass can, and
        punctuate.py does — the reply is compared to the text letter by
        letter with all punctuation removed, and anything that changed a
        word is thrown away instead of pasted. That is why this key is safe
        to press on a paragraph you are about to send.
        """
        import punctuate as punctuate_mod

        pcfg = self.cfg.punctuate
        # The grab mechanics live in [translate]: which chords, and how long
        # the focused app is given to answer them. They describe this
        # machine, not the job, so both text keys read the same ones.
        tcfg = self.cfg.translate
        state = injector.snapshot()
        kept = injector.claim_mark()      # as in _translate, and for the same
        keep_clipboard = False            # reason: see injector.claim_mark()
        try:
            text, had_selection = injector.grab(tcfg.copy_chord,
                                                tcfg.select_all_chord,
                                                tcfg.settle_ms / 1000)
        except injector.ClipboardBusyError as e:
            self._cue_once("error", "punctuate-clipboard")
            self._say("could not read the text to punctuate — the clipboard "
                      "was locked")
            log.error("could not read the text to punctuate: %s", e)
            return

        try:
            # The same three shapes as the other two keys, and the same
            # rule: "there was nothing to do" is not a fault, must not sound
            # like one, and must not repeat while the answer stays the same.
            what = "the selection" if had_selection else "the whole field"
            if not text.strip():
                self._cue_once("noop", "punctuate-empty")
                self._say(f"nothing to punctuate — {what} is empty")
                log.info("nothing to punctuate — %s is empty", what)
                return
            if len(text) > pcfg.max_chars:
                self._cue_once("error", "punctuate-too-much")
                self._say(f"{len(text)} chars is too much to punctuate — "
                          f"select the part you want")
                log.warning(
                    "refusing to punctuate %d chars from %s (max_chars=%d) "
                    "— that looks like a whole document, not a message. "
                    "Select the part you want and press the key again.",
                    len(text), what, pcfg.max_chars)
                return
            if not punctuate_mod.needs_punctuation(text):
                self._cue_once("noop", "punctuate-no-words")
                self._say(f"no words in {what} — nothing to punctuate")
                log.info("no words in %s — nothing to punctuate", what)
                return

            beep("punctuating")
            log.info("punctuating %d chars from %s%s...", len(text), what,
                     " (with nikud)" if pcfg.nikud else "")
            # The original goes to the log BEFORE it is replaced on screen:
            # this file is the recovery path if the paste goes wrong.
            transcript_log.info("PUNCTUATE-IN  | %s | %s", what, text)

            started = time.monotonic()
            try:
                fixed, backend = self._punctuation().punctuate(text)
            except punctuate_mod.UnsafeReply as e:
                # Told apart from every other failure on purpose. "It could
                # not be reached" sends someone to check Ollama; this means
                # the model answered and rewrote their words, and the app
                # threw that away — which is the guard working, not breaking.
                self._cue_once("error", "punctuate-unsafe")
                self._say(f"left it alone — the model rewrote your words "
                          f"instead of punctuating them ({e})")
                log.error("punctuation discarded: %s. Your text is untouched.",
                          e)
                return
            except TranscriptionError as e:
                beep("error")
                self._say(f"could not punctuate: {e}")
                log.error("punctuation failed: %s — your text is untouched", e)
                return
            latency = time.monotonic() - started
            transcript_log.info("PUNCTUATE-OUT | %.1fs | %s | %s", latency,
                                backend, fixed)

            if fixed.strip() == text.strip():
                self._cue_once("noop", "punctuate-unchanged")
                self._say(f"{what} is already punctuated — nothing changed")
                log.info("%s came back unchanged — it is already punctuated",
                         what)
                return

            if hwnd and injector.foreground_window() != hwnd:
                # The selection belongs to a window that is no longer
                # focused. Pasting now would overwrite whatever the user
                # switched to.
                injector.set_text(fixed)
                keep_clipboard = True   # restoring would take it back away
                beep("stop")
                log.warning("you moved to another window — the punctuated "
                            "text is on your clipboard, press %s to paste "
                            "it (%d chars)", self.cfg.paste_chord, len(fixed))
                return

            injector.paste_text(fixed, self.cfg.paste_chord,
                                self.cfg.restore_delay_ms)
            beep("punctuated")
            self._bump(punctuations=1)
            self._say(f"punctuated {len(text)} chars in {latency:.1f} s "
                      f"via {backend}")
            log.info("punctuated %d chars -> %d in %.1f s via %s", len(text),
                     len(fixed), latency, backend)
        except injector.ClipboardBusyError as e:
            beep("error")
            log.error("paste failed: %s — the punctuated text is in "
                      "transcripts.log", e)
        finally:
            if not keep_clipboard:
                try:
                    injector.restore(state, "punctuated text", since=kept)
                except injector.ClipboardBusyError as e:
                    log.warning("could not restore your clipboard: %s", e)

    # ---- the key that reads instead of writing ----

    def _lookup_worker(self) -> None:
        while True:
            hwnd, anchor = self.lookup_queue.get()
            try:
                # No _cursor_lock here, unlike the other two workers: this
                # one takes it around its capture and gives it straight
                # back (see _lookup). Holding it across the model call
                # would block a dictation paste for seconds to protect a
                # clipboard nobody is using any more.
                with privacy.pressed():
                    self._lookup(hwnd, anchor)
            except Exception:
                # Take the box down with it. Only TranscriptionError is
                # caught inside _lookup and turned into a line the box can
                # show; anything else would leave "…" on screen claiming to
                # be thinking while the error cue said otherwise — and now
                # that nothing dismisses the box on its own, it would go on
                # claiming it for as long as the app runs.
                try:
                    self.popup.hide()
                except Exception:
                    pass
                self._cue_once("error", "lookup-crash")
                log.exception("unexpected failure looking something up")
            finally:
                self._looking_up.clear()

    def _lookup(self, hwnd: int,
                anchor: tuple[int, int] | None = None) -> None:
        """Say what the selection means, and change nothing at all.

        `anchor` is where the mouse was when the key went down, read on
        the hook thread by cursor_point(). It defaults to None so the CLI
        probe and the tests can ask for a lookup without inventing a place
        for it; the box then falls back to the corner of the screen, which
        is where it always used to appear.

        The same shape as _translate — capture, guards, cue, transcript
        log, model — with the paste replaced by a box on screen. Three
        things are deliberately different, and all three come from the key
        being read-only:

          - the cursor lock is held around the CAPTURE ONLY. _translate
            holds it for the whole 1-3 s because it is going to paste at
            the end and the cursor has to still be where it found it; this
            borrows the clipboard for a measured 20 ms and then owes the
            machine nothing;
          - there is no snapshot/restore pair. injector.read_selection
            saves and restores every clipboard format itself, in a finally,
            because a read-only key that destroyed your clipboard would be
            a contradiction;
          - focus moving away is not a failure. There is nothing to paste
            into the wrong window, so the answer is shown anyway and the
            move is logged rather than enforced.
        """
        import lookup as lookup_mod

        lcfg = self.cfg.lookup
        # The capture mechanics live in [translate], as they do for the
        # punctuate key: which chord, and where Ollama is. They describe
        # this machine, not the job.
        tcfg = self.cfg.translate
        with self._cursor_lock:
            text, reason = injector.read_selection(
                tcfg.copy_chord, skip_consoles=lcfg.skip_consoles, hwnd=hwnd)

        def refuse(cue: str, why: str, said: str) -> None:
            """Nothing to look up — say so, and clear the box first.

            The box has to come down, and that is new. Every refusal below
            returns without putting anything in it, and a tap no longer
            closes an open box: it asks a fresh question. So the answer to
            the LAST question would be left standing as the answer to this
            one, with a cue playing over it that says otherwise. An empty
            screen is the honest report: the key was pressed, there was
            nothing to look up, and so there is nothing to see.
            """
            self.popup.hide()
            self._cue_once(cue, why)
            self._say(said)

        if reason == "console":
            refuse("noop", "lookup-console",
                   "nothing looked up — a console turns the copy into an "
                   "interrupt")
            log.info("not looking anything up in a '%s' window: the copy "
                     "chord becomes a real Ctrl+C there and would interrupt "
                     "whatever is running in it. Set skip_consoles = false "
                     "under [lookup] in the settings to try it anyway.",
                     injector.window_class(hwnd) or "console")
            return
        if reason == "clipboard-locked":
            refuse("error", "lookup-clipboard",
                   "could not read the selection — the clipboard was locked")
            log.error("could not read the selection to look up: another app "
                      "was holding the clipboard. Nothing was sent and your "
                      "own clipboard is untouched — try again in a moment.")
            return

        what = lookup_mod.classify(text, lcfg.max_chars, lcfg.both_ways,
                                   lcfg.hebrew_share)
        if not what.ok:
            # Four different nothings, told apart on purpose: "that is 6100
            # characters", "that is a URL", "that is already Hebrew" and
            # "you did not select anything" are four different answers, and
            # a key that played one note for all of them would teach
            # nothing. None of them is a fault, so none of them sounds like
            # one — see _cue_once.
            if what.reason == "nothing-selected":
                refuse("noop", "lookup-no-selection",
                       "nothing selected — select a word and tap again")
                log.info("nothing selected to look up. This key never "
                         "selects for you: an empty selection is an empty "
                         "answer, not the whole page.")
            elif what.reason == "too-much":
                refuse("noop", "lookup-too-much",
                       f"{len(text)} chars is too much to look up — select "
                       f"the part you want")
                log.info("refusing to look up %d chars (lookup.max_chars="
                         "%d) — nothing was sent anywhere. Select the part "
                         "you want, or use '%s' to translate the whole "
                         "thing in place.", len(text), lcfg.max_chars,
                         self.cfg.translate_hotkey or "the translate key")
            elif what.reason == "already-target":
                refuse("noop", "lookup-already-target",
                       "that is already the target language — see "
                       "lookup.both_ways")
                log.info("that selection is already the target language and "
                         "both_ways is off — set both_ways = true under "
                         "[lookup] in the settings to have Hebrew come back "
                         "as English.")
            else:
                refuse("noop", "lookup-nothing-to-translate",
                       "nothing to translate in that selection")
                log.info("nothing to translate in that selection (a URL, a "
                         "path or no words at all): %d chars", len(text))
            return

        rtl = what.target == "Hebrew"
        # The box's direction is fixed when it opens, and a Hebrew line in
        # a left-to-right box comes out backwards — popup.py measured that
        # in pixels. So everything the app itself puts in the box has to be
        # written in the language that lookup was asked for, including the
        # two lines that are not the answer.
        failed = ("לא הצלחתי לתרגם — הדגם לא ענה" if rtl
                  else "could not look that up — the model did not answer")

        def status(note: str) -> None:
            self.popup.update(note if rtl else "loading the local model…")

        # Long selections reach the local model in parts (lookup.
        # translate_chunked); between parts the box says which one is
        # being translated, because minutes of model time with a silent
        # box is exactly the "it didn't translate" this used to be read
        # as. Written in the answer's language, like everything else the
        # app puts in it — a Hebrew line in an LTR box comes out
        # backwards (popup.py measured that in pixels).
        def progress(i: int, n: int) -> None:
            note = (f"מתרגם חלק {i} מתוך {n}…"
                    if rtl else f"translating part {i} of {n}…")
            self.popup.update(note)
            log.info("lookup part %d of %d...", i, n)

        # Repainted on a newline, or after 80 ms, and never per token.
        # lookup.py hands over every token the local model writes and the
        # box relays out and RESIZES on each one, so the rate matters:
        # measured against real Ollama on 2026-08-19, a one-word answer is
        # 39 tokens 24 ms apart and a longer one 54. Painted per token
        # that is a box changing size forty times in a second, which reads
        # as jitter and not as speed. Through this it is 12 and 15 paints,
        # about one every 94 ms, and each one is the box gaining a line.
        #
        # A newline jumps the queue rather than waiting out the 80 ms,
        # because a completed line is the thing worth showing — that is
        # what makes the shortest gaps in the measurement 31 ms, and those
        # are the box growing, which is the one motion it should have.
        painted_at, painted_len = 0.0, 0

        def chunk(so_far: str) -> None:
            nonlocal painted_at, painted_len
            now = time.monotonic()
            if "\n" not in so_far[painted_len:] and now - painted_at < 0.08:
                return
            painted_at, painted_len = now, len(so_far)
            self.popup.update(so_far)

        beep("looking")
        # The box goes up BEFORE the model is asked, holding an ellipsis:
        # the answer is 1-3 s warm and 25 s cold, and a key that shows
        # nothing for that long has already been pressed again.
        #
        # Anchored where the user was pointing, and never on top of it.
        # The caret is preferred over the mouse where there is one, because
        # it is the exact end of the selection rather than wherever the
        # hand came to rest; popup.caret_anchor answers None for anything
        # built on Chromium, which is most of what this key is used in, so
        # the mouse point is the case that carries the feature and the
        # caret is the improvement on it.
        #
        # dwell_ms is deliberately 0 and no longer reads lookup.dwell_ms.
        # A box that took itself away was the owner's complaint — he could
        # not tell a timer from a bug — so this one waits to be closed, by
        # its own button or by Esc. update() re-places from this same
        # anchor, so the answer replacing the ellipsis grows the box away
        # from his text instead of moving it out from under his eyes.
        # `term` is what the title bar says. The box is handed an answer
        # and never sees the question, so the word has to travel with it:
        # the box outlives the selection it was opened over, and once it
        # has been dragged aside, or the highlight has gone, the bar is
        # the only thing on screen still saying which word this is about.
        # It goes up with the "…", so it is readable while the model is
        # still thinking.
        #
        # Cut, because this is a caption and not the selection. Only 45
        # Hebrew characters fit in the bar at the default lookup.max_width
        # and the label is painted with DT_END_ELLIPSIS on EVERY repaint,
        # including the one behind a selection being dragged: measured
        # 2026-08-20, a 5000-char term — which lookup.max_chars still
        # allows — costs 7.3 ms a paint against 0.6 ms for a whole
        # repaint of the box. 120 is far past anything the bar can show,
        # so the ellipsis and not this cut is what the eye ever sees.
        self.popup.show("…", rtl=rtl, dwell_ms=0,
                        anchor=popup_mod.caret_anchor(hwnd) or anchor,
                        term=text[:120])
        log.info("looking up %d chars (%s -> %s)...", len(text), what.mode,
                 what.target)
        # In the log before it is on screen, like every other key here.
        # The box no longer closes on a keystroke, so this is less of a
        # rescue than it was — but an answer the owner shut and then
        # wanted back is still only readable from this file.
        transcript_log.info("LOOKUP-IN  | %s | %s", what.mode, text)

        if self._lookup_engine is None:
            # Built on the first press, like the translator and the
            # punctuator: constructing it looks for an API key and opens
            # the answer cache, and an owner who never touches this key
            # should pay for neither.
            self._lookup_engine = lookup_mod.Engine(self.cfg)
        try:
            answer = self._lookup_engine.look_up(text, what,
                                                 on_status=status,
                                                 on_chunk=chunk,
                                                 on_progress=progress)
        except TranscriptionError as e:
            self._cue_once("error", "lookup-backend")
            self.popup.update(failed)
            self._say(f"could not look that up: {e}")
            log.error("lookup failed: %s — nothing was written anywhere and "
                      "your text is untouched", e)
            return

        if not answer.text.strip():
            # The box drops an empty string by design, which would leave the
            # "…" up while the cue said the answer had landed. Both backends
            # raise on an empty reply, so this is the corner where one
            # answers with nothing but formatting.
            self._cue_once("error", "lookup-backend")
            self.popup.update(failed)
            log.error("%s answered with nothing usable — your text is "
                      "untouched", answer.backend)
            return

        transcript_log.info("LOOKUP-OUT | %.1fs | %s | %s", answer.seconds,
                            answer.backend, answer.text)
        self.popup.update(answer.text)
        beep("looked")
        self._bump(lookups=1)
        if answer.warming:
            log.warning("the local model was not loaded, so that one went "
                        "to the cloud — it is warming up now and the next "
                        "lookup stays local")
        if hwnd and injector.foreground_window() != hwnd:
            log.info("you moved to another window while that was looking up "
                     "— the box is on screen anyway, because there was "
                     "never anything to paste")
        self._say(f"looked up {len(text)} chars -> {answer.target} in "
                  f"{answer.seconds:.1f} s via {answer.backend}")
        log.info("looked up %d chars in %.1f s via %s (%s -> %s): %d chars "
                 "back", len(text), answer.seconds, answer.backend,
                 answer.mode, answer.target, len(answer.text))

    def _improve(self, text: str, wait: bool = True,
                 max_wait_s: float | None = None,
                 receipt: dict | None = None) -> str:
        """What was learned, applied: repair pass then context pass.

        Both are strictly optional and neither may raise. This sits between
        a person's speech and their cursor, so anything that goes wrong here
        must degrade to "the transcript as the backend produced it" rather
        than to no transcript at all.

        `wait=False` runs only the vocabulary repair — instant, offline, a
        dictionary lookup — and skips the LLM pass entirely. `receipt`,
        when given, comes back with "by": the backend that answered the
        context pass, or None (see _context_pass).
        """
        if self.cfg.vocab.enabled:
            try:
                text, applied = self.vocab.apply(text)
                if applied:
                    log.info("repaired %d learned mishearing(s): %s",
                             len(applied), " | ".join(applied))
            except Exception:
                log.exception("the vocabulary repair pass failed — using the "
                              "transcript as it came out of the backend")

        if not wait:
            return text          # the caller will run the context pass after
        return self._context_pass(text, max_wait_s, receipt)

    def _polish_window(self, window, backend) -> None:
        """The repair pass on ONE stretch of a recording still in
        progress, on a thread of its own (see _start_roller).

        Its own thread, and not the rolling transcriber's, so that a slow
        answer never holds the release: the worker takes whatever this
        has finished and repairs the rest itself (_improve_rolled). The
        stretch goes in as the whole recording would have — the same
        filler cleanup first, then the vocabulary and the context pass.
        Never raises: an unrepaired stretch is repaired at the release.
        """
        try:
            text = backend.clean_text(window.text)
            if text:
                receipt: dict = {}
                polished = self._improve(text, wait=True, receipt=receipt)
                window.polished_by = receipt.get("by")
                window.polished = polished
        except Exception:
            log.exception("a stretch could not be repaired while you spoke "
                          "— the release will repair it")

    def _improve_rolled(self, cleaned: str, head,
                        receipt: dict | None = None) -> str:
        """_improve, minus the stretches already repaired while he spoke.

        The leading run of windows whose repair has landed is taken as it
        is; everything after it — a window whose answer is still on its
        way, and the tail — goes through the pass together, exactly as
        the whole recording used to. Measured 2026-09-13 in app.log: the
        pass on a 106 s dictation (997 chars) took 2.0 s; on its last
        stretch alone it is the 0.7 s a short dictation pays.

        `receipt["by"]` says which backend repaired any of it — the
        stretches while he spoke or the rest now — or None.
        """
        windows = list(getattr(self, "_last_windows", None) or [])
        done: list = []
        if head is not None:
            for window in windows:
                if window.polished is None:
                    break
                done.append(window)
        if not done:
            return self._improve(cleaned, wait=True, receipt=receipt)
        rest_raw = " ".join(w.text for w in windows[len(done):]
                            if w.text).strip()
        rest = ""
        rest_receipt: dict = {}
        if rest_raw:
            cleaner = getattr(self.transcriber, "clean_text", None)
            rest = cleaner(rest_raw) if cleaner else rest_raw
            rest = self._improve(rest, wait=True, receipt=rest_receipt)
        log.info("context pass: %d stretch(es) were repaired while you "
                 "spoke — %d chars went now", len(done), len(rest_raw))
        if receipt is not None:
            receipt["by"] = (rest_receipt.get("by")
                             or next((w.polished_by for w in done
                                      if getattr(w, "polished_by", None)),
                                     None))
        parts = [w.polished for w in done if w.polished]
        if rest:
            parts.append(rest)
        return " ".join(parts).strip()

    def _context_pass(self, text: str, max_wait_s: float | None = None,
                      receipt: dict | None = None) -> str:
        """The LLM repair, run to completion. Returns the text either way.

        Never raises: this is optional work sitting near a person's words,
        and the failure mode has to be "the transcript as the backend
        produced it", never "no transcript".

        Only the backends that may hold the paste are asked
        (Polisher.before_paste_kinds — under the default `when =
        "cloud"` the cloud ones; the local model proposes after the
        paste instead, _local_repair). `receipt["by"]` is the backend
        that answered, or None.
        """
        if receipt is not None:
            receipt["by"] = None
        polisher = self._polish()
        if polisher is None:
            return text
        try:
            kinds = polisher.before_paste_kinds()
            if kinds == () or not polisher.should_run(text):
                return text
            started = time.monotonic()
            log.info("checking the transcript against %d learned "
                     "confusion(s)...", len(self.vocab))
            with privacy.pressed():
                polished, by = polisher.polish(text, max_wait_s, kinds=kinds)
            if receipt is not None:
                receipt["by"] = by
            if by:
                transcript_log.info("POLISHED | %.1fs | %s | %s",
                                    time.monotonic() - started, by, polished)
                log.info("context pass (%s, %.1f s) changed the text", by,
                         time.monotonic() - started)
                return polished
        except Exception:
            log.exception("the context pass failed — using the transcript "
                          "as it came out of the backend")
        return text

    def _local_repair(self, text: str) -> str | None:
        """The local model's reading of a pasted dictation, for the second
        reading's card (review.py) — the repair that used to hold the
        paste 5-7 s, behind it since 2026-09-19 (`when = "cloud"`). The
        repaired text, or None when the model did not answer or had
        nothing to say. From the review thread; nobody is waiting, so
        the wait is the local model's own timeout, not polish.max_wait_s.
        Never raises."""
        polisher = self._polish()
        if polisher is None:
            return None
        try:
            if not polisher.should_run(text):
                return None
            limit = float(getattr(self.cfg.translate, "ollama_timeout_s",
                                  0) or 0) or None
            polished, by = polisher.polish(text, limit, kinds=("local",))
            if not by or polished.strip() == text.strip():
                return None
            transcript_log.info("REPAIR-CARD | %s | %s", by, polished)
            return polished
        except Exception:
            log.exception("the local repair failed — no proposal from it")
            return None

    def _warm_feature_keys(self) -> None:
        """Touch the lazily-built controllers once, on a thread that is
        allowed to be slow, so no keyboard callback ever pays for their
        import. Only the ones this config actually binds a key to — an
        app with [visual_qa] enabled = false must not import a vision
        chain because a warm-up was not told about the kill switch.
        """
        cap = getattr(self.cfg, "capture", None)
        cam = getattr(self.cfg, "camera", None)
        wants_capture = (
            (cap is not None and getattr(cap, "enabled", False))
            or (cam is not None and getattr(cam, "enabled", False)))
        vqa_cfg = getattr(self.cfg, "visual_qa", None)
        for wanted, name in ((wants_capture, "capture"),
                             (vqa_cfg is not None and vqa_cfg.enabled,
                              "vqa")):
            if not wanted:
                continue
            try:
                getattr(self, name)
            except Exception as e:
                # Not fatal: the key still works, it just pays the import
                # on the hook thread the way it always did.
                log.info("could not warm the %s key (%s)", name, e)

    def _warm_polish(self) -> None:
        try:
            polisher = self._polish()
            if polisher is not None:
                polisher.warm()
        except Exception as e:
            log.info("context-pass warm-up skipped (%s)", e)

    def _polish(self):
        """Built on first need: importing it is cheap, but constructing the
        backends is not, and `when = "never"` must cost nothing at all."""
        if self.cfg.polish.when == "never":
            return None
        if self._polisher is None:
            import polish as polish_mod
            self._polisher = polish_mod.Polisher(self.cfg, self.vocab)
        return self._polisher

    def _handle(self, wav: bytes, seconds: float, hwnd: int,
                language: str | None = None,
                to_card: bool | None = None,
                sliced: bool = False, in_stream: bool = False,
                pieces: list | None = None,
                to_prompt: bool = False, silent: bool = False,
                rolled=None, to_read: str | None = None) -> None:
        fb = self.cfg.feedback
        placeholder = fb.placeholder
        shown = False
        # A screen question owns the next dictation: no marker in the app
        # underneath, because nothing will ever be pasted over it.
        #
        # `to_card` is that decision, made when the hotkey went DOWN and
        # carried here on the queue — see _on_start for why it can no
        # longer be re-asked at this end. None means nobody decided, which
        # today is only a caller reaching straight in (the tests do), and
        # then the old question is still the best one available.
        vqa_cfg = getattr(self.cfg, "visual_qa", None)
        diverting = (vqa_cfg is not None and vqa_cfg.enabled
                     and (self.vqa.sink_active if to_card is None
                          else to_card))
        # `to_prompt` joins `diverting` here: nothing will ever be pasted
        # into the window underneath, so a marker put there is a marker
        # nobody comes back for. It is normally moot — the box has the
        # foreground at the press, so _on_start already filtered hwnd to
        # 0 — but only normally, and a stray "..." left in his editor is
        # exactly the kind of litter this branch exists to avoid.
        if fb.enabled and hwnd and not diverting and not to_prompt \
                and not to_read:
            # BOUNDED, unlike the paste below, and the focus test is INSIDE
            # the lock rather than in front of it. A translate or punctuate
            # holds this lock across its whole model call (up to
            # translate.ollama_timeout_s = 150 s); waiting that out would
            # park the worker before transcription had even started, for a
            # marker that is only cosmetic. And show_placeholder pastes
            # wherever focus is when it finally runs, so a check made before
            # the wait would be a check of the wrong moment.
            if self._cursor_lock.acquire(timeout=1.0):
                try:
                    if injector.foreground_window() == hwnd:
                        injector.show_placeholder(placeholder,
                                                  self.cfg.paste_chord,
                                                  self.cfg.restore_delay_ms)
                        shown = True
                except injector.ClipboardBusyError as e:
                    log.warning("could not show the placeholder: %s", e)
                finally:
                    self._cursor_lock.release()
            else:
                log.info("something else is working at the cursor — "
                         "transcribing without the marker")

        started = time.monotonic()
        deadline = started + fb.retry_seconds
        item = None          # set once the audio is safely on disk
        last_error = ""
        attempt = 0
        text = backend = None
        no_model = False     # the model is not on disk: said as such
        # What the rolling transcriber finished while the key was held.
        # finish() waits for the decode it is in the middle of, if any —
        # bounded, and inside the latency that is measured, because it
        # IS part of the wait. None means the whole recording is decoded
        # here exactly as it always was.
        head = rolled.finish() if rolled is not None else None
        if head is not None:
            log.info("rolling: %d window(s) covering %.1f of %.1f s were "
                     "decoded while you spoke (%.1f s of decoder time) — "
                     "only the tail is left", len(head.windows), head.end_s,
                     seconds, rolled.busy_s)

        while True:
            attempt += 1
            try:
                if pieces and len(pieces) > 1:
                    text, backend = self._transcribe_pieces(pieces,
                                                            language)
                else:
                    text, backend = self._transcribe(wav, language, head)
                break
            except TranscriptionError as e:
                last_error = str(e)
                no_model = isinstance(e, ModelMissing)
                # Save the audio BEFORE deciding whether to retry, so a
                # crash or a quit between attempts still cannot lose it.
                if item is None:
                    item = self.spool.save(wav, seconds, last_error)
                    log.error("%s — audio saved to %s", e,
                              item.wav_path.name)
                else:
                    item.bump(last_error)
                    log.error("retry %d failed: %s", attempt, e)
                wait = getattr(e, "retry_after", 0.0) or 3.0
                left = deadline - time.monotonic()
                if left <= 0 or wait > left:
                    break
                time.sleep(min(wait, left))
            except Exception as e:
                last_error = f"unexpected: {e}"
                if item is None:
                    item = self.spool.save(wav, seconds, last_error)
                log.exception("unexpected transcription failure")
                break

        latency = time.monotonic() - started

        if text is None:
            # Nothing to paste. Take the marker back down so the user is not
            # left with a stray "..." in their document.
            if shown:
                with self._cursor_lock:
                    injector.clear_placeholder(placeholder, hwnd)
            beep("error")
            self._bump(failures=1)
            if no_model:
                self._say("the Hebrew model is not downloaded yet — the "
                          "recording is kept; start DeskIT again to "
                          "download it")
            else:
                self._say(f"gave up after {latency:.0f} s — the audio is "
                          f"kept in pending\\, run --drain later")
            transcript_log.info("ERROR | %.1fs | %s | %s | kept: %s", seconds,
                                self.transcriber.name, last_error,
                                item.wav_path.name if item else "NOT SAVED")
            log.error("gave up after %.0f s — the recording is kept in "
                      "pending\\, run --drain to turn it into text later",
                      latency)
            return

        # Raw backend return goes to the log BEFORE any guard decides not to
        # paste it — this file is the recovery path.
        transcript_log.info("OK | %.1fs | %s | %.1fs latency | %s",
                            seconds, backend, latency, text)
        self._nudge_sync("history")
        cleaned = text.strip()
        if not cleaned:
            if shown:
                with self._cursor_lock:
                    injector.clear_placeholder(placeholder, hwnd)
            log.info("empty transcript (no speech heard) — not pasting")
            if item:
                item.discard()
            if to_read:
                # The card is waiting for an answer, and "nothing came
                # back" is one.
                self.reading.heard(to_read, wav, seconds, "")
            return

        # THE ASK-THE-SCREEN DIVERSION. While the visual-QA window is up,
        # a dictation is a QUESTION, not a paste: the transcript goes into
        # that window's entry and nothing may leak into the app underneath
        # — no placeholder, no repair pass, no clipboard. The vocabulary
        # swap still applies (instant, offline); the context pass does
        # NOT — a vision model is robust to one misheard word, and the
        # question path stays free, fast and quota-neutral by design.
        if diverting:
            if shown:
                # The marker was pasted before the window opened; it is
                # not where the answer is going any more.
                with self._cursor_lock:
                    injector.clear_placeholder(placeholder, hwnd)
            try:
                cleaned, _applied = self.vocab.apply(cleaned)
            except Exception:
                log.exception("the vocabulary repair failed on a screen "
                              "question — using the raw transcript")
            if item:
                item.discard()
            if not self.vqa.deliver_transcript(cleaned):
                # THE CARD IS GONE, so put the words somewhere the user can
                # reach them. Deciding the destination at the press is what
                # makes this reachable: a question asked at a card that is
                # then closed mid-sentence used to fall back to pasting at
                # the cursor, because the far end re-read sink_active and
                # found it False. That fallback was itself the bug (it is
                # how a dictation aimed at a document ended up in a card),
                # but the answer to it is not "drop the speech" — the
                # clipboard is where every other homeless transcript in
                # this module goes.
                try:
                    with self._cursor_lock:
                        injector.set_text(cleaned)
                    beep("stop")
                    log.warning("the screen-question window closed before "
                                "the transcription landed — it is on your "
                                "clipboard, press %s to paste it (%d chars)",
                                self.cfg.paste_chord, len(cleaned))
                except Exception as e:
                    log.warning("the screen-question window vanished before "
                                "the transcription landed, and the "
                                "clipboard would not take it (%s) — text is "
                                "in transcripts.log only", e)
            elif in_stream:
                # This question is INSIDE a recording that will be pasted
                # in full later, and this is the only transcript of it
                # that can be trusted — see _transcribe_pieces. Kept, not
                # echoed: echoing it as well would say it twice.
                self._question_texts.append(cleaned)
            elif (getattr(vqa_cfg, "echo_to_field", False)
                    and not sliced and self.vqa.echoing):
                # KEPT, not pasted. The card owns the foreground while it
                # is up, so this is the one thing that cannot happen now.
                # See _on_card_closed.
                #
                # `echoing` is the switch in the card's title strip, asked
                # HERE and not at the close, so it means "was the second
                # destination on when I said this" rather than "was it on
                # when I shut the card". Turning it off is how you ask the
                # screen something that has no business in what you are
                # writing, and it must not un-send what you already said.
                with self._echo_lock:
                    self._echo_lines.append(cleaned)
            return

        # THE REPORT-BOX DIVERSION, the ask card's rule applied to the one
        # other window of ours that takes the keyboard: while the box from
        # the ctrl+alt+r tap is up, a dictation is the REPORT, not a paste.
        # It goes into that box's field and nothing leaks past it.
        #
        # Decided at the press like the card's (see _on_start), and for the
        # same reason: he opens the box, then holds the dictation key and
        # says what went wrong, and the answer to "who was I talking to"
        # must not change while he is still talking.
        #
        # The vocabulary swap applies and the context pass does NOT — the
        # same trade the question path makes. This is a note to himself
        # about a bug; a misheard word in it costs nothing, and a model
        # round trip to tidy a sentence he is about to read and can edit
        # in the field would be paid for nothing.
        #
        # `_last` is deliberately never touched: a report is not a
        # dictation. Letting one land there would give the correct key a
        # bug report to learn from, and would make the NEXT report attach
        # this one as the transcript it is complaining about.
        if to_prompt:
            try:
                cleaned, _applied = self.vocab.apply(cleaned)
            except Exception:
                log.exception("the vocabulary repair failed on a dictated "
                              "problem report — using the raw transcript")
            if item:
                item.discard()
            if not self._deliver_to_prompt(cleaned):
                # THE BOX IS GONE, or cannot be filled — the words still
                # have to go somewhere he can reach, and the clipboard is
                # where every other homeless transcript in this module
                # goes. The same fallback the card path takes, for the
                # same reason: dropping speech is never the answer.
                try:
                    with self._cursor_lock:
                        injector.set_text(cleaned)
                    beep("stop")
                    self._say("the report card did not take that — it is on "
                              "your clipboard")
                    log.warning("problems: the report card did not take the "
                                "dictation — it is on your clipboard, press "
                                "%s to paste it (%d chars)",
                                self.cfg.paste_chord, len(cleaned))
                except Exception as e:
                    beep("error")
                    log.warning("problems: the report card did not take the "
                                "dictation and the clipboard would not "
                                "either (%s) — text is in transcripts.log "
                                "only", e)
            return

        # THE READING DIVERSION, the third window of ours that takes a
        # dictation — except that this one is not a window of ours at
        # all but the dashboard's Read aloud card, and the dictation is
        # not text going anywhere: it is AUDIO, filed under the words on
        # the card (reading.py says why that is the point). The
        # transcript is filed beside it and asked one thing, whether
        # anything came back at all; so the vocabulary swap applies —
        # instant, offline, the same as the other two diversions — and
        # the context pass does not. It did for an hour, when the
        # transcript was still a verdict; a verdict nobody is asked for
        # is not worth a model call a sentence. `_last` is never
        # touched, for the box's reason: a reading is not a dictation.
        if to_read:
            cleaned = self._improve(cleaned, wait=False)
            if item:
                item.discard()
            state = self.reading.heard(to_read, wav, seconds, cleaned)
            if state is None:
                log.info("reading: the card had moved on before the "
                         "transcript came back — nothing kept")
            elif state["heard"]:
                self._say(state["heard"]["verdict"])
            return

        # THE CONTEXT PASS, AND WHICH SIDE OF THE PASTE IT SITS ON.
        #
        # It ran in front of the paste, for every backend, and that was
        # the one decision this module was arranged around: it had been
        # moved behind the paste once — paste instantly, rewrite the text
        # on screen a few seconds later — and moved back because a
        # sentence that may still rewrite itself is a sentence you cannot
        # send. The placeholder was the contract: "..." = not final, text
        # = done and it will not move again.
        #
        # The owner's decision of 2026-09-19 keeps that contract and
        # splits the pass by who answers (polish.py, `when = "cloud"`,
        # the default): a CLOUD backend (~0.3 s) still repairs here, in
        # front of the paste; the LOCAL model no longer holds it — the
        # text lands at once and the model's reading follows as a
        # PROPOSAL on the second reading's card (_local_repair, handed to
        # review.Engine), which touches nothing on screen until he says
        # yes. Why: measured on the installed copy that day, a stranger
        # — no Groq key — waited 5-7 s before every paste for the local
        # model, and 2 s with no Ollama at all (Windows takes that long
        # to refuse a local port). `when = "always"` is the old way.
        # `receipt["by"]` says who repaired it here, so the reading does
        # not run the pass twice for one dictation. Minus whatever the
        # rolling transcriber's stretches already had repaired while the
        # key was held (_improve_rolled).
        #
        # TIMED APART from the decode, because it is where the seconds
        # go: 2026-09-19 on the installed copy, a 12 s dictation decoded
        # in 0.6 s and the paste landed 8.5 s after the release — 7.1 s
        # of local repair between them — while this line said "0.6 s
        # round trip" and the log read as if the paste had been fast.
        repair_started = time.monotonic()
        receipt: dict = {}
        cleaned = self._improve_rolled(cleaned, head, receipt)
        # And the punctuation, if the box is ticked — after the repair, so
        # it works on the final words; punctuate.max_wait_s bounds it.
        cleaned = self._auto_punctuate(cleaned)
        repair_s = time.monotonic() - repair_started
        kept = None
        # The decoder's per-word confidence belongs to ONE decode; a
        # recording transcribed in pieces has several, so it carries none.
        words = ([] if (pieces and len(pieces) > 1)
                 else list(getattr(self, "_last_words", []) or []))
        # A silent recording (a dead microphone, see _on_stop) is not
        # kept: recent\ is the labelled set every measurement in this repo
        # is made against, and a wav with nobody in it is not a label.
        if self.recent is not None and not silent:
            try:
                kept = self.recent.save(
                    wav, seconds, "",
                    extra={"text": cleaned, "raw": text.strip(),
                           "backend": backend, "language": language or "auto",
                           "words": words,
                           # who repaired it before the paste ("" = nobody):
                           # the second reading's local repair runs only
                           # for a dictation nobody has repaired
                           "repair": receipt.get("by") or ""})
            except OSError as e:
                log.info("could not keep this recording for later "
                         "measurement: %s", e)
        # Remembered before the paste, not after: a transcript that landed
        # on the clipboard because focus moved is still one worth teaching
        # the app about.
        with self._last_lock:
            self._last = {"raw": text.strip(), "final": cleaned,
                          "when": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "wav": str(kept.wav_path) if kept else ""}

        try:
            with self._cursor_lock:
                if shown:
                    status = injector.replace_placeholder(
                        placeholder, cleaned, self.cfg.paste_chord,
                        self.cfg.restore_delay_ms, hwnd)
                elif not hwnd:
                    # NOBODY KNOWS where this belongs. Reachable since the
                    # release-time window stopped being trusted when it is
                    # one of ours: the fallback is the window at the press,
                    # and that is 0 if the foreground could not be read
                    # then either. Pasting on "0" means pasting into
                    # whatever has focus NOW, which in this situation is
                    # most likely the overlay that caused the question —
                    # so it goes to the clipboard with an explanation
                    # instead, the same answer as a focus change.
                    raise injector.FocusChangedError(
                        "there is no window to paste into")
                elif injector.foreground_window() != hwnd:
                    # No placeholder because focus had already moved when
                    # the worker picked this up. Pasting now would drop the
                    # text into a window the user never dictated into.
                    raise injector.FocusChangedError(
                        "focus moved before the transcript was ready")
                else:
                    status = injector.inject(cleaned, self.cfg.paste_chord,
                                             self.cfg.restore_delay_ms)
        except injector.FocusChangedError:
            # Do NOT fire backspaces into whatever the user switched to.
            with self._cursor_lock:
                injector.set_text(cleaned)
            beep("stop")
            log.warning("you moved to another window — the transcript is on "
                        "your clipboard, press %s to paste it (%d chars)",
                        self.cfg.paste_chord, len(cleaned))
            if item:
                item.discard()
            return
        except injector.ClipboardBusyError as e:
            beep("error")
            log.error("paste failed: %s — the text is in transcripts.log", e)
            return

        if item:                      # transcribed at last: audio no longer
            item.discard()            # needed, drop it from the spool
        self._bump(dictations=1, seconds=seconds, chars=len(cleaned),
                   latency=latency)
        # The number a person feels is release-to-paste, and the two
        # halves are what say whether the decoder or the repair pass was
        # slow. `latency` (the decode) stays the stat and the transcripts
        # line, as it always was.
        to_paste = time.monotonic() - started
        self._say(f"{seconds:.1f} s spoken -> {len(cleaned)} chars in "
                  f"{to_paste:.1f} s via {backend}"
                  + (f" ({latency:.1f} s decode + {repair_s:.1f} s repair)"
                     if repair_s >= 0.05 else ""))
        log.info("pasted %d chars (%.1f s to the paste via %s: %.1f s "
                 "decode, %.1f s repair; %s)",
                 len(cleaned), to_paste, backend, latency, repair_s, status)
        # AFTER the paste, never before: the reading is slower than the
        # text and must not be what the text waits for.
        self._review_submit(kept, hwnd)


def _load_config(explicit: str | None) -> config_mod.Config:
    """--config names one file as the whole configuration; without it the
    app runs on the three layers (defaults.toml, settings.toml,
    state.json — config.py, "the three layers")."""
    if explicit:
        return config_mod.load(Path(explicit))
    return config_mod.load_layered()


def setup_logging() -> None:
    handlers: list[logging.Handler] = []
    if HAS_CONSOLE:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("%(asctime)s  %(message)s",
                                               "%H:%M:%S"))
        handlers.append(console)
    # Always mirror the status log to a file: when launched windowless this
    # is the only place errors can be read.
    app_file = logging.handlers.RotatingFileHandler(
        paths.APP_LOG, maxBytes=500_000, backupCount=2,
        encoding="utf-8")
    app_file.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | "
                                            "%(message)s"))
    handlers.append(app_file)
    logging.basicConfig(level=logging.INFO, handlers=handlers)
    file_handler = logging.handlers.RotatingFileHandler(
        paths.TRANSCRIPTS_LOG, maxBytes=1_000_000, backupCount=3,
        encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    transcript_log.addHandler(file_handler)
    transcript_log.propagate = False  # transcripts.log only


def drain(cfg: config_mod.Config) -> int:
    """Turn recordings kept in pending\\ into text.

    These are utterances the backend refused at the time (almost always the
    free-tier daily cap). The audio was never thrown away, so this recovers
    the speech once quota is back.
    """
    spool = Spool(paths.PENDING_DIR)
    items = spool.pending()
    if not items:
        print("Nothing pending — no recordings were lost.")
        return 0
    print(f"{len(items)} recording(s) waiting. Transcribing oldest first...\n")
    transcriber = get_transcriber(cfg)
    recovered = failed = 0
    for item in items:
        label = f"{item.wav_path.name} ({item.seconds:.1f}s)"
        try:
            text = transcriber.transcribe(item.read()).strip()
        except TranscriptionError as e:
            print(f"  [still failing] {label}: {e}")
            item.bump(str(e))
            failed += 1
            continue
        transcript_log.info("DRAINED | %.1fs | %s | %s", item.seconds,
                            transcriber.name, text)
        print(f"  [recovered]     {label}:\n      {text}\n")
        item.discard()
        recovered += 1
    print(f"\n{recovered} recovered, {failed} still waiting.")
    if recovered:
        print("Recovered text is also appended to transcripts.log.")
    if failed:
        print("Still-failing recordings are kept — run --drain again later.")
    return 0


def word_error_rate(truth: str, guess: str) -> tuple[int, int]:
    """(edits, reference words). Standard Levenshtein over word tokens."""
    a, b = vocab_mod.words(truth), vocab_mod.words(guess)
    a = [w.lower() for w in a]
    b = [w.lower() for w in b]
    prev = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        cur = [i]
        for j, wb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (wa != wb)))
        prev = cur
    return prev[-1], len(a)


def benchmark(cfg: config_mod.Config) -> int:
    """Replay every corrected recording with the vocabulary on and off.

    This is the whole reason recent\\ exists. "It feels better since I added
    those words" is not evidence, and the vocabulary is the kind of feature
    that is very easy to believe in and very hard to notice failing. Every
    recording the user has corrected is a labelled test case: the audio, and
    what it should have said.

    One model, transcribed twice — building two would double the VRAM for
    nothing, since the only difference is a prompt.
    """
    recent = Spool(paths.RECENT_DIR)
    cases = [i for i in recent.pending() if i.meta.get("corrected")]
    if not cases:
        print("No corrected recordings yet, so there is nothing to measure.")
        print(f"Dictate, then tap '{cfg.correct_hotkey}' and fix what it got")
        print("wrong. Each correction becomes a test case here.")
        if cfg.vocab.keep_audio <= 0:
            print("\nNote: [vocab] keep_audio = 0, so no audio is being "
                  "kept — corrections can never be replayed.")
        return 0

    v = vocab_mod.Vocab(paths.VOCAB_FILE, seed_terms=cfg.vocab.terms,
                        max_terms=cfg.vocab.max_terms,
                        replace_after_hits=cfg.vocab.replace_after_hits,
                        hebrew_after_hits=cfg.vocab.hebrew_after_hits)
    on = {"enabled": False}
    from transcribers import local_kwargs
    from transcribers.local_whisper import LocalWhisperTranscriber

    print(f"{len(cases)} corrected recording(s). Loading the model...")
    t = LocalWhisperTranscriber(
        **local_kwargs(cfg, lambda: v.hotwords() if on["enabled"] else ""))

    totals = {False: [0, 0], True: [0, 0]}
    for item in cases:
        truth = item.meta["corrected"]
        audio = item.read()
        line = {}
        for flag in (False, True):
            on["enabled"] = flag
            guess = t.transcribe(audio)
            if flag:                       # the repair pass runs in real use
                guess, _ = v.apply(guess)
            edits, words = word_error_rate(truth, guess)
            totals[flag][0] += edits
            totals[flag][1] += words
            line[flag] = (edits, words, guess)
        before = line[False][0] / max(1, line[False][1])
        after = line[True][0] / max(1, line[True][1])
        flag = "  " if abs(after - before) < 1e-9 else \
               ("->" if after < before else "!!")
        print(f"\n{flag} {item.wav_path.name}  ({item.seconds:.1f}s)  "
              f"WER {before:.1%} -> {after:.1%}")
        if after != before:
            print(f"     off: {line[False][2]}")
            print(f"     on : {line[True][2]}")
            print(f"     want: {truth}")

    off_wer = totals[False][0] / max(1, totals[False][1])
    on_wer = totals[True][0] / max(1, totals[True][1])
    print(f"\n{'=' * 60}")
    print(f"vocabulary OFF: {off_wer:.2%} WER over {totals[False][1]} words")
    print(f"vocabulary ON : {on_wer:.2%} WER over {totals[True][1]} words")
    if on_wer < off_wer:
        print(f"\n{(off_wer - on_wer) / off_wer:.0%} relative improvement.")
    elif on_wer > off_wer:
        print("\nThe vocabulary made it WORSE on this set. Likely causes: a "
              "term seeded that you rarely say (Whisper emits prompted words "
              "unbidden), or too many terms — try lowering max_terms.")
    else:
        print("\nNo difference on this set.")
    print("\nNote: these are the recordings you chose to correct, so they "
          "are the hard ones by construction — not a sample of normal "
          "dictation.")
    return 0


def show_vocab(cfg: config_mod.Config) -> int:
    """What the app has learned, and what it does with it.

    The store is JSON and could just be opened, but the two questions worth
    answering — "is this term actually reaching the decoder" and "why is
    that garble still not being repaired" — are about the derived hotword
    list and the hit threshold, neither of which is visible in the file.
    """
    v = vocab_mod.Vocab(paths.VOCAB_FILE, seed_terms=cfg.vocab.terms,
                        max_terms=cfg.vocab.max_terms,
                        replace_after_hits=cfg.vocab.replace_after_hits,
                        hebrew_after_hits=cfg.vocab.hebrew_after_hits)
    print(f"{v.path}\n")
    if not v.corrections:
        print("Nothing learned yet. Dictate something, then tap "
              f"'{cfg.correct_hotkey}' and fix what it misheard.\n")
    else:
        print(f"{len(v.corrections)} learned correction(s) "
              f"(repaired automatically at {cfg.vocab.replace_after_hits}+ "
              f"hits):")
        for c in sorted(v.corrections, key=lambda c: -int(c.get("hits", 1))):
            hits = int(c.get("hits", 1))
            mark = "auto" if hits >= cfg.vocab.replace_after_hits else "    "
            print(f"  [{mark}] {hits}x  {c.get('heard','')}  ->  {c['meant']}"
                  f"   ({c.get('last','?')})")
        print()
    if cfg.vocab.terms:
        print(f"{len(cfg.vocab.terms)} seed term(s) from the settings "
              f"[vocab] terms\n")
    hot = v.hotwords()
    if not cfg.vocab.enabled:
        print("[vocab] enabled = false — NONE of this reaches the decoder.")
    elif not hot:
        print("No hotwords: nothing seeded and nothing learned.")
    else:
        print(f"Hotwords fed to every decoder window "
              f"({len(v.terms())} terms, capped at max_terms="
              f"{cfg.vocab.max_terms}):\n  {hot}")
        print(f"\n  ({len(hot)} characters. faster-whisper truncates this at "
              f"{vocab_mod.HOTWORD_TOKEN_LIMIT} tokens, and Hebrew costs "
              f"several tokens a word — lower max_terms if you approach it.)")
    return 0


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _adopt_downloads() -> int:
    """The installer's last step (DeskIT.iss, 10.4, 2026-09-19): it
    downloaded the model files and the packs' wheels itself, with the
    person's tick and the licences shown, and put them where models.py
    and packs.py keep theirs. Nothing has hashed the files or run pip.
    This does both, for every entry of the two locks that is on disk,
    with no window and no network — models.adopt() / packs.adopt()
    fetch nothing when every file is already its size — and prints one
    line per item. Always exit 0: an item that is partial or failed is
    left to the wizard's computer page, which offers exactly what is
    still missing; the installer must never fail over a download."""
    import packs as packs_mod

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                    # noqa: BLE001
        pass
    for repo, e in sorted(models_mod.read_lock().items()):
        if not e.folder.is_dir():
            continue
        try:
            word = models_mod.adopt(e)
        except Exception as err:                         # noqa: BLE001
            word = f"failed:{err}"
        log.info("adopt: model %s -> %s", repo, word)
        print(f"model {repo}: {word}")
    for name, p in sorted(packs_mod.read_lock().items()):
        if not p.wheels_dir.is_dir() and packs_mod.state(name) != "ok":
            continue
        try:
            word = packs_mod.adopt(p)
        except Exception as err:                         # noqa: BLE001
            word = f"failed:{err}"
        log.info("adopt: pack %s -> %s", name, word)
        print(f"pack {name}: {word}")
    return 0


def main() -> int:
    # Before argparse, because every mode below can end up showing a
    # window — the splash, a lookup popup, the setup wizard, a fatal
    # message box — and the identity is only read once, when the first
    # one is made.
    claim_app_identity()
    parser = argparse.ArgumentParser(
        description="Hebrew push-to-talk dictation (hold hotkey, speak, "
                    "release).")
    parser.add_argument("--config", default=None,
                        help="one file as the whole configuration (the "
                             "app itself runs on defaults.toml + "
                             "settings.toml + state.json)")
    parser.add_argument("--migrate", nargs="?", const="", metavar="OLD",
                        help="carry a pre-2026-09-17 config.toml (or an old "
                             "checkout folder) into the per-user files")
    parser.add_argument("--reset-data", action="store_true",
                        help="delete everything learned and recorded; keep "
                             "the settings (needs --yes)")
    parser.add_argument("--yes", action="store_true",
                        help="confirm --reset-data")
    parser.add_argument("--everything", action="store_true",
                        help="with --reset-data: the settings, the keys, the "
                             "models — the whole data folder, the Start-with-"
                             "Windows entry and the Claude Code hook lines; what "
                             "the uninstaller's Delete runs (plan D9)")
    parser.add_argument("--keys", action="store_true",
                        help="which cloud keys are stored and where (never "
                             "the values)")
    parser.add_argument("--set-key", metavar="NAME",
                        help="store a Groq or Gemini key in Windows "
                             "Credential Manager (prompts; NAME = groq | "
                             "gemini)")
    parser.add_argument("--delete-key", metavar="NAME",
                        help="remove that key from Windows Credential Manager")
    parser.add_argument("--consents", action="store_true",
                        help="which cloud gates are open, since when, and "
                             "which card each needs")
    parser.add_argument("--consent", metavar="KIND",
                        help="open a cloud gate from the terminal, as the "
                             "card's [Turn on] would (KIND = cloud_text | "
                             "cloud_audio | cloud_screenshots | ...)")
    parser.add_argument("--withdraw", metavar="KIND",
                        help="close a cloud gate; the local path answers "
                             "from the next press")
    parser.add_argument("--fake", action="store_true",
                        help="use the fake backend (no API, no mic quality "
                             "needed)")
    parser.add_argument("--check", action="store_true",
                        help="validate Gemini key + model with one tiny "
                             "request, then exit")
    parser.add_argument("--list-devices", action="store_true",
                        help="list audio input devices, then exit")
    parser.add_argument("--stop", action="store_true",
                        help="ask a running instance to quit, then exit")
    parser.add_argument("--quiet", action="store_true",
                        help="no window of its own: Windows' logon start (the Run "
                             "value), the relaunch after an update and the desk "
                             "that is already open pass it; a double-click on the "
                             "shortcut does not, and opens the desk")
    parser.add_argument("--no-model", action="store_true",
                        help="start without the speech model (the desk does this "
                             "when it opens); Start in the desk loads it")
    parser.add_argument("--test-sound", action="store_true",
                        help="play every audio cue once, then exit")
    parser.add_argument("--translate", metavar="TEXT",
                        help="translate TEXT and print it, then exit — "
                             "checks the translate backends without "
                             "touching the keyboard or clipboard")
    parser.add_argument("--punctuate", metavar="TEXT",
                        help="punctuate TEXT and print it, then exit — "
                             "checks the punctuation backends (and the "
                             "safety check that guards them) without "
                             "touching the keyboard or clipboard")
    parser.add_argument("--lookup", metavar="TEXT",
                        help="look TEXT up and print the answer, then exit "
                             "— which way round it went, which backend "
                             "answered and how long it took, without the "
                             "keyboard, the clipboard or the box. Safe to "
                             "run while dictation is running.")
    parser.add_argument("--setup", action="store_true",
                        help="run the first-run wizard again: pick a "
                             "microphone, watch the meter move, say one "
                             "sentence and read it back. It runs on its "
                             "own the first time; this is how to see it "
                             "afterwards")
    parser.add_argument("--download-model", action="store_true",
                        help="show the model download step on its own "
                             "(an installed copy shows it at start while "
                             "the Hebrew model is not on disk) and exit")
    parser.add_argument("--diagnose", action="store_true",
                        help="print one block for a bug report — version, "
                             "tier, the model's and the pack's standing, "
                             "the last 50 lines of app.log through the "
                             "redactor; no transcripts, no keys — and put "
                             "it on the clipboard")
    parser.add_argument("--verify", action="store_true",
                        help="recompute MANIFEST.sha256 over the installed "
                             "python\\ and app\\ and print every file that "
                             "differs from the build's (D12 lock 5); exit "
                             "1 on any difference")
    parser.add_argument("--install-pack", metavar="NAME",
                        help="show a pack's install step on its own (gpu "
                             "or skin; an installed copy with an NVIDIA "
                             "card offers gpu at start) and exit")
    parser.add_argument("--adopt-downloads", action="store_true",
                        help="finish what the installer downloaded: hash "
                             "the model files it put under models\ and "
                             "mark them complete, pip-install the packs "
                             "whose wheels it left under packs\ — no "
                             "window, no network — and exit 0 (the "
                             "installer's last step, 10.4)")
    parser.add_argument("--benchmark", action="store_true",
                        help="replay every recording you have corrected, "
                             "with the learned vocabulary on and off, and "
                             "report the word error rate of each")
    parser.add_argument("--study", action="store_true",
                        help="study every recording in recent\\ that was "
                             "never corrected: re-decode it several ways, "
                             "adjudicate, and report what the live pass "
                             "got wrong (see study.py)")
    parser.add_argument("--review", action="store_true",
                        help="run the second reading over every recording a "
                             "human has labelled and score its proposals "
                             "against the truth (see review.py)")
    parser.add_argument("--vocab", action="store_true",
                        help="print what the app has learned (vocab.json) "
                             "and the hotword list it builds, then exit")
    parser.add_argument("--drain", action="store_true",
                        help="transcribe recordings kept in pending\\ "
                             "(saved when the backend was down), print them, "
                             "then exit")
    parser.add_argument("--dashboard", action="store_true",
                        help="open the control window (start/pause/stop and "
                             "the keys), then exit")
    args = parser.parse_args()
    # The two housekeeping commands run before a single log handler
    # opens a file: --reset-data has to be able to delete app.log.
    if args.migrate is not None:
        import migrate as migrate_mod
        return migrate_mod.migrate(Path(args.migrate) if args.migrate else None)
    if args.reset_data:
        import migrate as migrate_mod
        return migrate_mod.reset_data(yes=args.yes, everything=args.everything)
    if args.verify:
        # The tree's own check, before any config or data folder is
        # touched: the build wrote MANIFEST.sha256 beside python\ and
        # app\, so the install root is APP_DIR's parent. A checkout has
        # no manifest and says so — it is not a build.
        import manifest
        code, text = manifest.report(paths.APP_DIR.parent)
        print(text)
        return code
    if args.keys or args.set_key or args.delete_key:
        import secretstore
        if args.set_key:
            return secretstore.cli_set(args.set_key.lower())
        if args.delete_key:
            return secretstore.cli_delete(args.delete_key.lower())
        return secretstore.cli_list()
    if args.consents or args.consent or args.withdraw:
        try:
            privacy.configure(_load_config(args.config))
        except ConfigError as e:
            print(f"settings would not load: {e}")
            return 1
        if args.consent:
            return privacy.cli_grant(args.consent.lower())
        if args.withdraw:
            return privacy.cli_withdraw(args.withdraw.lower())
        return privacy.cli_list()
    paths.ensure()
    setup_logging()
    # An installed copy tells huggingface_hub where its home is and that
    # it is offline BEFORE anything imports it (models.py): the loader
    # is given a folder, so the library never needs the network, and
    # nothing lands in the person's global cache.
    models_mod.env()

    if args.adopt_downloads:
        return _adopt_downloads()

    if args.dashboard:
        import dashboard
        return dashboard.main()

    # The per-user files brought forward (11.10): every migration step
    # above the files' config_version, before anything reads them; a
    # step that fails leaves them as they were and says so once.
    if not args.fake and not args.config:
        try:
            import migrations
            problem = migrations.apply()
            if problem:
                log.warning("%s", problem)
        except Exception:                     # noqa: BLE001
            log.warning("the migrations could not run", exc_info=True)

    if args.diagnose:
        block = problems_mod.diagnose()
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                 # noqa: BLE001
            pass
        print(block)
        try:
            injector.set_text(block)
            print("\n(copied to the clipboard)")
        except Exception:                 # noqa: BLE001
            pass
        return 0

    if args.test_sound:
        cues.ensure_files(force=True)
        # Every cue there is, not a hand-written list: the last two added
        # (pause and resume) were exactly the ones a list would have missed,
        # and they are the ones you most need to recognise by ear.
        for kind in cues.CUES:
            print(f"playing '{kind}' cue...")
            cues.play(kind)
            time.sleep(1.2)
        print(f"\nHeard nothing? These play through the DEFAULT playback "
              f"device.\nWAV files: {cues.CUE_DIR}\nCheck Settings > System "
              f"> Sound > Volume mixer while this runs.")
        return 0

    if args.stop:
        if singleton.request_quit():
            log.info("stop signal sent to the running instance")
        else:
            log.info("nothing to stop — dictation is not running")
        return 0

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        print('\nPick it in the first-run wizard (main.py --setup) or write '
              'audio.device = "<name>" into settings.toml')
        return 0

    try:
        cfg = _load_config(args.config)
    except ConfigError as e:
        # report_fatal, not a bare log line: launched windowless there is
        # nowhere for this to be seen, and a config.toml can now be edited
        # from the dashboard — so "it stopped starting" has to say why.
        report_fatal(str(e))
        return 1
    if args.fake:
        cfg = dataclasses.replace(cfg, backend="fake")
    # The gates (privacy.py): what [privacy] says, before anything that
    # could build a cloud client. net.py learns `offline` from this too.
    privacy.configure(cfg)
    # Start with Windows: the Run value says what state.json says, every
    # start, so an install that moved never leaves a stale entry (10.2).
    import autostart
    autostart.sync(cfg)
    # Restart Manager relaunches the app after an update with THIS
    # command (plan 11.6); an installed copy registers, the checkout
    # does not.
    if not paths.DEVELOPER:
        try:
            import ctypes as _ct
            _ct.windll.kernel32.RegisterApplicationRestart(
                f'"{paths.APP_DIR / "deskit.pyw"}" --quiet', 0)
        except Exception:                     # noqa: BLE001
            log.debug("RegisterApplicationRestart failed", exc_info=True)
    if paths.CHANNEL_NOTE:
        log.warning("%s", paths.CHANNEL_NOTE)
    # [history] keep_days: prune, or detach the transcripts handler.
    import history as history_mod
    log.info("%s", history_mod.apply(cfg, transcript_log))

    # The first-run wizard, BEFORE any model is loaded. Two reasons for
    # the position: a wizard that appears after 25 s of nothing has
    # already lost the argument it exists to win, and the microphone it
    # writes has to be the one the Recorder is then opened on.
    # What this computer can do (hardware.py, plan 6.2): the facts into
    # state.json and the tier's derived defaults into the machine layer,
    # BEFORE any model loads — the config is read again when it wrote.
    facts = None
    if not args.fake and not args.config:
        import hardware as hardware_mod
        try:
            facts = hardware_mod.run_at_start()
            cfg = _load_config(args.config)
        except Exception:                     # noqa: BLE001
            log.warning("the hardware probe failed; running as before",
                        exc_info=True)
    # The Hebrew model (models.py, plan 6.4): an installed copy downloads
    # it here, once, with the size on the screen and [Not now] — never as
    # a side effect of loading. Declined or offline, the app still
    # starts: every key that needs no model works, a dictation says why,
    # the recording is kept. When the WIZARD is due it hosts this step
    # and the pack's as pages of its own (chapter 9.2), so the two
    # standalone windows are for a set-up copy whose model went missing.
    wizard_due = args.setup or (firstrun.needed(cfg) and not args.fake)
    # The model with the app — [local] load_at_start, on by default —
    # unless this start said --no-model (the tests, a hand start).
    no_model = args.no_model or not bool(getattr(cfg.local, "load_at_start", True))
    if args.download_model or (not args.fake and not wizard_due
                               and not no_model
                               and models_mod.wanted(cfg)):
        outcome = models_mod.offer(cfg.local.model)
        log.info("model download step: %s", outcome)
        if args.download_model:
            return 0 if outcome == "done" else 1
    # The GPU pack (packs.py, plan 6.5): an NVIDIA card without NVIDIA's
    # libraries is a cpu tier, so the same step, once, right after the
    # model — [Not now] is written down and the start stops asking.
    # Installed, the probe runs again so the tier and its defaults are
    # the card's before any model loads.
    import packs as packs_mod
    # PyAV, when the Recording pack brought it (13.4): its site goes on
    # sys.path now, before faster_whisper's `import av` at the model's
    # construction, so the vendor stub hands over instead of answering.
    packs_mod.activate("recording")
    if args.install_pack or (not args.fake and not wizard_due
                             and packs_mod.wanted(cfg, facts)):
        outcome = packs_mod.offer(args.install_pack or "gpu")
        log.info("pack step (%s): %s", args.install_pack or "gpu", outcome)
        if args.install_pack:
            return 0 if outcome == "done" else 1
        if outcome == "done":
            import hardware as hardware_mod
            try:
                facts = hardware_mod.run_at_start()
                cfg = _load_config(args.config)
            except Exception:                 # noqa: BLE001
                log.warning("the hardware probe failed after the pack",
                            exc_info=True)
    open_desk = False
    if wizard_due:
        outcome = firstrun.run(cfg, Path(args.config) if args.config else None,
                               facts=facts)
        if outcome or outcome.installed_pack:
            cfg = _load_config(args.config)   # it wrote the device / the tier
        if outcome.installed_pack:
            facts = None
            try:
                import hardware as hardware_mod
                facts = hardware_mod.recorded()
            except Exception:                 # noqa: BLE001
                pass
        open_desk = bool(outcome.open_desk)
        if getattr(outcome, "closed", False):
            # The X on the wizard: the person left, and nothing starts
            # behind their back — no model, no dot, no keys. The next
            # start shows the wizard again (setup.done was not written).
            log.info("the wizard was closed; nothing started")
            return 0
        if args.setup:
            if open_desk:
                open_dashboard()
            return 0

    # Whatever Tk the pre-start windows made — the wizard, the model and
    # pack steps — dies here, on this thread, before a decode thread's
    # allocation can trigger the collection that buries a PhotoImage from
    # the wrong thread and aborts the process (firstrun.run says why).
    import gc
    gc.collect()

    if args.check:
        try:
            from transcribers.gemini import GeminiTranscriber
            t = GeminiTranscriber(cfg.gemini.model, cfg.gemini.timeout_s)
            print(f"key source: {t.key_source}")
            print(f"checking key + model '{cfg.gemini.model}' with one tiny "
                  "request...")
            reply = t.check()
            print(f"API reply: {reply!r} — key and model look good.")
            return 0
        except TranscriptionError as e:
            print(f"check FAILED: {e}")
            return 1

    if args.translate:
        import translate as translate_mod
        if not translate_mod.needs_translation(args.translate,
                                               cfg.translate.target):
            print(f"no Hebrew in that text — already "
                  f"{cfg.translate.target}, nothing to do.")
            return 0
        started = time.monotonic()
        try:
            text, backend = translate_mod.Translator(cfg).translate(
                args.translate)
        except TranscriptionError as e:
            print(f"translation FAILED: {e}")
            return 1
        print(f"[{backend}, {time.monotonic() - started:.1f}s] {text}")
        return 0

    if args.punctuate:
        import punctuate as punctuate_mod
        if not punctuate_mod.needs_punctuation(args.punctuate):
            print("no words in that text — nothing to punctuate.")
            return 0
        started = time.monotonic()
        try:
            text, backend = punctuate_mod.Punctuator(cfg).punctuate(
                args.punctuate)
        except punctuate_mod.UnsafeReply as e:
            # Its own exit path: this is the guard doing its job, not the
            # backends failing, and the difference is the whole point of
            # being able to run it from a console.
            print(f"punctuation DISCARDED — {e}")
            return 1
        except TranscriptionError as e:
            print(f"punctuation FAILED: {e}")
            return 1
        print(f"[{backend}, {time.monotonic() - started:.1f}s] {text}")
        return 0

    # `is not None`, and not a truth test like the two probes above: an
    # empty --lookup "" would otherwise fall through to the singleton lock
    # and start the whole app — global hook, two Whisper models — when what
    # was asked for was a probe.
    if args.lookup is not None:
        import lookup as lookup_mod
        # Classified first and printed as a refusal, not as an error: the
        # key spends nothing on a URL or on 6000 characters, and running
        # this is how you check that without watching a box appear.
        what = lookup_mod.classify(args.lookup, cfg.lookup.max_chars,
                                   cfg.lookup.both_ways,
                                   cfg.lookup.hebrew_share)
        if not what.ok:
            print(f"nothing to look up — {what.reason}.")
            return 0
        try:
            answer = lookup_mod.Engine(cfg).look_up(args.lookup, what)
        except TranscriptionError as e:
            print(f"lookup FAILED: {e}")
            return 1
        print(f"[{answer.backend}, {answer.mode} -> {answer.target}, "
              f"{answer.seconds:.1f}s] {answer.text}")
        if answer.warming:
            print(f"({cfg.lookup.model} was not loaded — that one went to "
                  f"the cloud and the local model is warming up now)")
        return 0

    if args.vocab:
        return show_vocab(cfg)

    if (args.benchmark or args.study or args.review) and not paths.DEVELOPER:
        # The owner's tools (D15): the benchmark, the study pass over the
        # corpus and the review run belong to the checkout, and an
        # installed copy has no corpus for them to work on.
        print("that command is for the developer's checkout only.")
        return 2

    if args.benchmark:
        return benchmark(cfg)

    if args.study:
        try:
            import study as study_mod
        except ImportError:
            # There is one version now (2026-09-08), so this can no
            # longer be answered with "switch to the other one" — the
            # module is simply absent from the folder.
            print("study.py is not in this folder, so there is no study "
                  "engine to run.")
            return 2
        if getattr(cfg, "study", None) is None:
            print("the settings have no [study] section.")
            return 2
        return study_mod.study_all(cfg, paths.DATA_DIR)

    if args.review:
        try:
            import review as review_mod
        except ImportError:
            print("review.py is not in this folder, so there is no "
                  "second reading to run.")
            return 2
        if getattr(cfg, "review", None) is None:
            print("the settings have no [review] section.")
            return 2
        return review_mod.review_all(cfg, paths.DATA_DIR)

    if args.drain:
        return drain(cfg)

    try:
        lock = singleton.InstanceLock()
    except singleton.AlreadyRunning:
        # It is already up, so the click was almost certainly "let me see
        # it" rather than "start a second one". Show the dashboard instead
        # of a modal complaint — and keep the complaint for the case where
        # even that will not open.
        if not open_dashboard():
            report_fatal(
                "DeskIT is already running (only one instance may "
                "run — two would paste every transcript twice), and the "
                "dashboard could not be opened.")
            return 1
        return 0

    # Created HERE, the moment the mutex is held — NOT after the models
    # load. request_quit() is OpenEventW, which fails outright when the
    # event does not exist yet, so an event that only appeared ~25 s later
    # would make every Stop in that window a silent no-op: the dashboard
    # would say "nothing to stop" (it enables the button as soon as the
    # mutex says an instance exists) and the app would come up behind it
    # anyway, hook live. Same hole for "Stop DeskIT.vbs".
    quit_signal = singleton.QuitSignal()

    # Loading two Whisper models onto the GPU takes ~25 s during which a
    # windowless app looks like a shortcut that did nothing. Every log line
    # the app writes becomes a status update, so the splash narrates the
    # real startup instead of just spinning.
    splash = overlay_mod.Splash() if cfg.splash else overlay_mod.Splash.off()
    # The release's last beat lands its light IN the status dot, so the
    # splash has to know where the dot will be (skin\boot.py) — the
    # corner, and, since the dot can be dragged out of its corner,
    # where it was dropped. Sending only the corner is how the light
    # would end up arriving in an empty one.
    _dot = getattr(cfg, "dot", None)
    splash.dot_corner = str(getattr(_dot, "corner", "bottom-right"))
    splash.dot_x = int(getattr(_dot, "x", overlay_mod.HINT_UNSET))
    splash.dot_y = int(getattr(_dot, "y", overlay_mod.HINT_UNSET))
    splash.start()
    splash_log = SplashLog(splash)
    log.addHandler(splash_log)

    # The dashboard has to be able to see this instance BEFORE it is
    # usable, not just after: the ~25 s of model loading is exactly when
    # someone is looking at the window wondering whether their click did
    # anything. So the control channel opens first, answering "starting"
    # with the same line the splash is showing, and is handed the App the
    # moment there is one.
    stage: dict = {"stage": "starting", "line": "starting…", "app": None}

    class StageLog(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                stage["line"] = record.getMessage()
            except Exception:
                pass

    stage_log = StageLog(level=logging.INFO)
    log.addHandler(stage_log)

    def on_command(command: str, command_args: dict) -> dict:
        app = stage["app"]
        if app is not None:
            return app.control_command(command, command_args)
        if command == "quit":
            singleton.request_quit()
            return {"ok": True}
        if command == "status":
            return {"ok": True, "stage": stage["stage"], "note": stage["line"],
                    "paused": False, "activity": "starting"}
        return {"ok": False, "error": "still starting up — try again in a "
                                      "moment"}

    channel = control.ControlServer(on_command)
    channel.start()

    def fail(message: str) -> int:
        log.removeHandler(splash_log)
        log.removeHandler(stage_log)
        splash.finish(linger_ms=0)
        channel.stop()
        report_fatal(message)
        return 1

    # An awake_state.json from a session that died holding (Task Manager,
    # a crash, a power cut): the hold went with the process, but a pinned
    # sleep timer did not. Put it back before anything else, so a bad
    # exit cannot become a permanent setting.
    leftover = awake_mod.recover(paths.DATA_DIR, log_path=paths.AWAKE_LOG)
    if leftover:
        log.warning("%s", leftover)
    try:
        splash.status("starting…" if no_model else
                      "loading the transcription model…")
        app = App(cfg, config_path=Path(args.config) if args.config else None,
                  model=not no_model)
    except TranscriptionError as e:   # missing key, stub backend, ...
        return fail(str(e))
    except (ValueError, ConfigError) as e:   # unknown hotkey/chord name
        return fail(f"bad key name in the settings: {e}")
    except Exception as e:            # no input device, PortAudio errors
        return fail(f"could not start audio capture: {e}\n\nCheck Settings "
                    "> Privacy & security > Microphone, and the microphone "
                    "chosen in the wizard (main.py --setup).")

    if quit_signal.is_set():
        # Stop was pressed while the models were loading. Bringing the
        # global hook up now — for the fraction of a second before the wait
        # below returns — would put live hotkeys on a machine whose owner
        # has already said they want them gone.
        log.info("stop was requested during startup — not installing the "
                 "hotkey")
        splash.finish(linger_ms=0)
        log.removeHandler(splash_log)
        log.removeHandler(stage_log)
        channel.stop()
        quit_signal.close()
        lock.release()
        return 0
    try:
        app.start()
    except OSError as e:
        return fail(str(e))
    stage["app"] = app
    stage["stage"] = "running"
    # A plain launch — the shortcut, DeskIT.vbs, nothing on the line — is
    # a person who wants to see the app (the owner on his installed
    # copy, 2026-09-20: "the first double-click lights the model, the
    # second opens the app"); the desk opens with it, the app behind.
    # Windows' logon start and the desk's own start (--quiet), the
    # tests' --fake and every other flag open no window.
    if open_desk or not sys.argv[1:]:
        # [Open the desk] on the wizard's last page, or the plain
        # launch: the dashboard, now that there is an app for it to
        # talk to.
        open_dashboard()
    if not args.fake and app.tour_due():
        # The tour (D36): the guide itself, four cards beside the dot,
        # on the first start after the wizard. The dot is up (app.start
        # mapped it) and the card only enqueues.
        log.info("the tour: first start, showing it beside the dot")
        app.tour_card.show(0)
    log.info("ready — hold '%s' for %s%s, release to paste. %s",
             cfg.hotkey,
             "Hebrew or English" if cfg.auto_language else "Hebrew",
             f", '{cfg.english_hotkey}' for English" if cfg.english_hotkey
             else "",
             "Ctrl+C here to quit." if HAS_CONSOLE
             else 'Double-click "Stop DeskIT.vbs" to quit.')
    if cfg.latch_hotkey:
        log.info("long dictation: while holding '%s', tap '%s' to lock the "
                 "recording on — then let go and talk %s. Tap '%s' again to "
                 "transcribe, esc to discard.",
                 cfg.hotkey, cfg.latch_hotkey,
                 "with no time limit" if not cfg.latch_max_seconds
                 else f"for up to {cfg.latch_max_seconds:.0f} s",
                 cfg.latch_hotkey)
    if cfg.translate_hotkey:
        log.info("tap '%s' to turn the selection — or the whole field when "
                 "nothing is selected — into %s", cfg.translate_hotkey,
                 cfg.translate.target)
    if cfg.punctuate_hotkey:
        log.info("tap '%s' to punctuate the selection — or the whole field "
                 "when nothing is selected%s. The words cannot change: a "
                 "reply that altered one is discarded, not pasted.",
                 cfg.punctuate_hotkey,
                 " (and add nikud)" if cfg.punctuate.nikud else "")
    if cfg.correct_hotkey:
        log.info("tap '%s' to fix the last transcript — what you change "
                 "there is what it learns (%d correction(s) so far, "
                 "%d hotword(s) active)", cfg.correct_hotkey,
                 len(app.vocab),
                 len(app.vocab.terms()) if cfg.vocab.enabled else 0)
    if cfg.lookup_hotkey:
        log.info("tap '%s' to look the selection up — the answer appears in "
                 "a small box beside what you selected and nothing on "
                 "screen is touched, so it works on a web page or a PDF "
                 "too%s. It stays until you close it: click the x in its "
                 "corner, or press Esc. Tapping '%s' again looks up "
                 "whatever is selected now.", cfg.lookup_hotkey,
                 "" if cfg.lookup.both_ways
                 else "; Hebrew only, see lookup.both_ways",
                 cfg.lookup_hotkey)
    vqa_cfg = getattr(cfg, "visual_qa", None)
    if vqa_cfg is not None and vqa_cfg.enabled and vqa_cfg.hotkey:
        log.info("tap '%s' to select part of the screen and ASK about it — "
                 "drag a rectangle, then hold '%s' to speak your question "
                 "(or type it). Answers locally via %s%s; screenshots are "
                 "never written to disk%s.",
                 vqa_cfg.hotkey, cfg.hotkey,
                 vqa_cfg.ollama_model,
                 ", cloud upload OFF" if not privacy.allowed("cloud_screenshots")
                 else f", then {vqa_cfg.groq_model} (upload is ON)",
                 "" if vqa_cfg.speak == "off"
                 else f"; speak = '{vqa_cfg.speak}'")
    cap_cfg = getattr(cfg, "capture", None)
    if cap_cfg is not None and cap_cfg.enabled and cap_cfg.hotkey:
        # getattr throughout: this file is byte-identical on both branches
        # and classic's Config has no [capture] section at all, so nothing
        # here may assume a field exists.
        after = {
            "toast": "A small card then appears in the %s for a few "
                     "seconds - click it to crop, draw, blur out anything "
                     "private or hand it to the ask key, ignore it and it "
                     "goes away. The key is NOT dead while it is up: press "
                     "it again and a second card joins the first, oldest at "
                     "the top and newest at the bottom, %s of them at a "
                     "time, each on its own clock"
                     % (getattr(cap_cfg, "toast_corner", "corner"),
                        getattr(cap_cfg, "toast_stack", 4)),
            "editor": "A toolbar then opens on it for cropping, drawing, "
                      "blurring out anything private, or handing it to "
                      "the ask key",
        }.get(getattr(cap_cfg, "after_shot", "editor"),
              "Nothing else happens - it is a pure grab-and-go")
        log.info("tap %r to CAPTURE part of the screen - drag a box or "
                 "shift-drag a shape, and it is on the clipboard before "
                 "you let go. %s%s%s", cap_cfg.hotkey, after,
                 "" if getattr(cap_cfg, "always_save", True) else
                 (". It is NOT written to %s unless you ask for it - press "
                  "Save on the card or in the editor" % cap_cfg.folder),
                 "" if not cap_cfg.record_hotkey else
                 (". Tap %r to RECORD a region to mp4 instead, and again "
                  "to stop%s") % (cap_cfg.record_hotkey,
                                  " (with the microphone)"
                                  if cap_cfg.audio == "mic" else ""))
    cam_cfg = getattr(cfg, "camera", None)
    if cam_cfg is not None and cam_cfg.enabled and cam_cfg.hotkey:
        log.info("tap %r for a PHOTO from the camera - a live preview with "
                 "a shutter, and the picture lands on the clipboard and in "
                 "%s the moment you take it%s. The camera is closed again "
                 "the instant the shutter fires%s", cam_cfg.hotkey,
                 cam_cfg.folder,
                 "" if not cam_cfg.edit_after_shot else
                 ", then opens in the same editor a screenshot does",
                 "" if not cam_cfg.device else
                 f" (asking for a camera matching {cam_cfg.device!r})")
    if cfg.pause_hotkey:
        log.info("tap '%s' to pause every key above without unloading "
                 "anything (for games), and again to resume%s",
                 cfg.pause_hotkey,
                 "; fullscreen apps pause it automatically"
                 if cfg.auto_pause_fullscreen else "")
    awake_cfg = getattr(cfg, "awake", None)
    if awake_cfg is not None and awake_cfg.hold:
        log.info("the machine is held awake for as long as this runs "
                 "([awake] hold); the screens go dark on their own timer")
    if awake_cfg is not None and awake_cfg.enabled and awake_cfg.hotkey:
        log.info("tap %r for SCREENS OFF - they go dark and stay dark while "
                 "the machine stays awake for the phone; tap again to bring "
                 "them back. The dashboard's Awake screen has the same "
                 "switch and a check that says whether the hold is "
                 "standing", awake_cfg.hotkey)
    ncfg = getattr(cfg, "notify", None)
    if ncfg is not None and ncfg.enabled:
        log.info("notifications: POST /notify on the phone endpoint (the "
                 "phone token) plays a cue and puts a card up%s; "
                 "Claude Code is wired through notify_hook.py%s",
                 f"; tap {ncfg.hotkey!r} to dismiss" if ncfg.hotkey else "",
                 ", and Cowork through the desktop app's own Windows "
                 "notifications ([notify] watch = "
                 f"{getattr(ncfg, 'watch', 'cowork')!r}, notify_watch.py)"
                 if getattr(ncfg, "watch", "off") != "off" else "")
    log.info("mic: %s | backend: %s | transcripts: %s",
             app.recorder.device_label(), cfg.backend,
             paths.TRANSCRIPTS_LOG)
    key_source = getattr(app.transcriber, "key_source", None)
    if key_source:
        log.info("api key from: %s", key_source)
    if not is_elevated():
        log.info("note: running non-elevated — dictation into run-as-admin "
                 "windows will not work (see README)")
    waiting = app.spool.pending()
    if waiting:
        log.warning("%d recording(s) from earlier could not be transcribed "
                    "and are waiting in pending\\ — run "
                    'main.py --drain to turn them into text', len(waiting))
    log.removeHandler(splash_log)
    # THE CUE BELONGS TO THE PICTURE, NOT TO THIS LINE. `beep("ready")`
    # used to be called here, one statement earlier — and finish() only
    # SCHEDULES the release, so the sound arrived 3.63 s before the light
    # it is the sound of: you heard "ready", waited, and then watched the
    # star fire and gather into the corner dot. Handing the cue to
    # finish() lets the skin fire it on the frame the light actually
    # reaches the dot. See overlay.Splash.land and skin.boot._land_ms.
    # ...and the WAVs are made HERE, not there. cues.play() calls
    # ensure_files() on the first cue of the process, which is this one —
    # a mkdir and a stat per cue normally, but a per-sample Python loop
    # synthesising every file when cues\ has been wiped. That is hundreds
    # of milliseconds, and it would be spent on the single frame the skin
    # goes to some length not to stall (skin/boot.py, clock.absorb).
    cues.ensure_files()
    splash.finish(f"ready — hold {cfg.hotkey.title()} and speak",
                  on_land=lambda: beep("ready"))
    try:
        quit_signal.wait()   # released by --stop; Ctrl+C also lands here
        log.info("stop requested")
    except KeyboardInterrupt:
        log.info("interrupted")
    finally:
        beep("bye")
        channel.stop()
        log.removeHandler(stage_log)
        app.stop()
        quit_signal.close()
        lock.release()
        time.sleep(0.35)     # let the shutdown cue finish playing
    log.info("bye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
