"""Hebrew push-to-talk dictation for Windows.

Hold the hotkey (default: Right Ctrl), speak Hebrew, release — the cleaned
transcript is pasted into whatever window has focus. See README.md.

Normally launched by double-clicking "Hebrew Dictation.vbs", which runs it
windowless via pythonw.exe. With no console there is no Ctrl+C, so a second
launch is refused (single-instance mutex) and "Stop Dictation.vbs" (i.e.
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
import sys
import threading
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

import config as config_mod
import control
import cues
import firstrun
import hint as hint_mod
import injector
import awake as awake_mod
import notify as notify_mod
import popup as popup_mod
import server as server_mod
import singleton
import overlay as overlay_mod
import vocab as vocab_mod
from config import ConfigError
import hotkey as hotkey_mod
from hotkey import (HookThread, PTTStateMachine, parse_binding,
                    parse_chord, vk_for)
from launch import open_dashboard
from recorder import Recorder
from spool import Spool
from transcribers import RateLimitError, TranscriptionError, get_transcriber

log = logging.getLogger("app")
transcript_log = logging.getLogger("transcripts")

# pythonw.exe (the windowless launcher) gives the process no stdout at all.
HAS_CONSOLE = sys.stdout is not None

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
                 "hint": None, "review": None}
LIVE_TOP_LEVEL = ("auto_pause_fullscreen", "paste_chord", "restore_delay_ms")

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
_SCREEN_ACTIONS = frozenset({"visual_qa", "capture", "record", "photo",
                             "screens", "notify_dismiss"})

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
            None, message, "Hebrew Dictation — cannot start", 0x10)


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

    def __init__(self, cfg: config_mod.Config,
                 config_path: Path | None = None):
        self.cfg = cfg
        # Where a key change is written back to. Carried rather than
        # recomputed so --config keeps pointing at the file it was given.
        self.config_path = Path(config_path or (APP_DIR / "config.toml"))
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
            APP_DIR / "vocab.json", seed_terms=cfg.vocab.terms,
            max_terms=cfg.vocab.max_terms,
            replace_after_hits=cfg.vocab.replace_after_hits,
            hebrew_after_hits=getattr(cfg.vocab, "hebrew_after_hits", 3))
        hotwords = self.vocab.hotwords if cfg.vocab.enabled else None
        self.transcriber = get_transcriber(cfg, hotwords)  # fail fast: no key
        self._hotwords = hotwords
        self._polisher = None        # built on first use (see _polish)
        # The last thing pasted, and what the backend actually returned.
        # The correction key edits the FORMER: it is what the user saw, so
        # it is what their edit is a diff against.
        self._last: dict | None = None
        self._last_lock = threading.Lock()
        self.spool = Spool(APP_DIR / "pending")
        # A ring of recent recordings, kept so a correction can be tied to
        # the audio that produced it. Without this the app can only be told
        # that a word is wrong, never SHOWN — and no vocabulary change can
        # ever be measured, only assumed. See --benchmark.
        self.recent = (Spool(APP_DIR / "recent", keep=cfg.vocab.keep_audio)
                       if cfg.vocab.keep_audio > 0 else None)
        self._local = None       # lazily built local fallback, if enabled
        self.recorder = Recorder(cfg.audio.sample_rate, cfg.audio.device,
                                 cfg.max_seconds, self._on_overflow)
        # The cap in force right now: max_seconds while held, lifted by a
        # latch. Kept here purely so the log lines name the real number.
        self._cap = cfg.max_seconds
        self._latched = False
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
            on_ask_stop=self._on_ask_stop)
        self.hook = HookThread(self.machine)
        # awake.py: the machine held awake for as long as this runs (the
        # hold goes up in start()), and the screens off on a key. Built
        # whether or not the key is bound — the dashboard's button goes
        # through the control channel and needs the engine either way.
        self.awake = awake_mod.Engine(APP_DIR, getattr(cfg, "awake", None))
        # What the dot is showing, kept here so the dashboard can report the
        # same thing in words. Every set_state goes through _set_state.
        self._activity = "ready"
        # Both decided at the press and read again at the release — see
        # _on_start. Seeded here only so that a release with no matching
        # press (there should be none; the state machine sees to that)
        # cannot raise inside the keyboard hook, where an exception is a
        # dropped hook and a frozen keyboard.
        self._to_card = False
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
        # the app is alive, and what it is doing.
        self.dot = (overlay_mod.StatusDot() if cfg.indicator
                    else overlay_mod.StatusDot.off())
        # And, for the press someone hesitated on, a card naming what the
        # keys will do. Off by config, and off by construction the rest of
        # the time: nothing is on screen until a key has been held for
        # hint.after_ms, which an ordinary dictation never reaches.
        self.hint = (overlay_mod.HintCard(
            cfg.hint.after_ms, cfg.hint.corner, x=cfg.hint.x, y=cfg.hint.y,
            scale=cfg.hint.scale, on_change=self._save_hint)
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
        # The notification card and its engine (notify.py). The card class
        # is looked up rather than named: it lands with the card package,
        # and until then — or on a branch without it — the engine gets the
        # inert card and everything else (route, store, log, key) works.
        ncfg = getattr(cfg, "notify", None)
        card_cls = getattr(overlay_mod, "NotifyCard", None)
        self.notify_card = (card_cls(
            ncfg.corner, x=ncfg.x, y=ncfg.y, scale=ncfg.scale,
            on_change=self._save_notify_card,
            on_dismiss=self._notify_dismissed,
            seconds=ncfg.card_seconds)
            if card_cls is not None and ncfg is not None and ncfg.enabled
            else notify_mod.NullCard())
        self.notify = notify_mod.Engine(APP_DIR, ncfg, cue=beep,
                                        card=self.notify_card)
        # The pencil's box: one line, takes the keyboard, on purpose.
        self._word_prompt = overlay_mod.WordPrompt()
        self._review = None
        # The decoder's per-word confidence for the LAST live transcription,
        # read under the model lock in _transcribe and written into the
        # recording's sidecar for the second reading.
        self._last_words: list = []
        self.phone: server_mod.PhoneServer | None = None
        if cfg.server.enabled:
            self.phone = server_mod.PhoneServer(
                cfg, self._transcribe_for_phone,
                lambda: self.transcriber.name,
                self._translate_for_phone,
                self._punctuate_for_phone,
                self._notify_from_outside)

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
        """
        controller = getattr(self, "_capture", None)
        if controller is None:
            import capture as capture_mod
            controller = capture_mod.Controller(lambda: self.cfg,
                                                ask_provider=self._ask_card)
            self._capture = controller
        return controller

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
                             "field you were writing in (%d chars): %s",
                             len(text), text)
                    return
                # Focus went somewhere the owner chose. The clipboard is
                # where every other homeless transcript in this module
                # goes, and it says so out loud rather than dropping it.
                injector.set_text(text)
                beep("stop")
                log.warning("the field you were writing in is not in front "
                            "any more — what you asked the screen is on "
                            "your clipboard, press %s to paste it: %s",
                            self.cfg.paste_chord, text)
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
        self._activity = state
        self.dot.set_state(state)
        # The card rides the same state, so it can never disagree with the
        # dot about whether a recording is live — including the early
        # return above, which is exactly the case where "ready" is a lie.
        self.hint.show(self._hint_card(state))

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
        config_mod.set_values(self.config_path,
                              {f"hint.{k}": v for k, v in fields.items()})
        log.info("hint card: %s",
                 ", ".join(f"{k}={v}" for k, v in fields.items()))

    def _save_review_card(self, fields: dict) -> None:
        """The review card's twin of _save_hint: where it was dragged to,
        written into [review] through the same comment-keeping line edit."""
        self.cfg = dataclasses.replace(
            self.cfg, review=dataclasses.replace(self.cfg.review, **fields))
        config_mod.set_values(self.config_path,
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
        config_mod.set_values(self.config_path,
                              {f"notify.{k}": v for k, v in fields.items()})
        log.info("notify card: %s",
                 ", ".join(f"{k}={v}" for k, v in fields.items()))

    def _notify_dismissed(self) -> None:
        """A click on the card, or Esc over it. The callback arrives on
        the card's Tk thread, and the engine's dismiss is a JSON write —
        so it goes to a thread of its own, and the card's pump is never
        made to wait on the disk."""
        def work() -> None:
            engine = getattr(self, "notify", None)
            if engine is not None:
                engine.dismiss(by="card")
                self._say("notifications dismissed")
        threading.Thread(target=work, daemon=True,
                         name="notify-dismiss").start()

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
        }

    # ---- pause ----

    def _on_pause(self, paused: bool) -> None:
        """Runs on the hook thread (pause key) or the control thread (the
        dashboard). Cheap on purpose: nothing is loaded or unloaded, which
        is the entire point of pausing rather than quitting."""
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
        changed = self.machine.set_paused(paused)
        if paused and changed:
            self._auto_paused = auto
        return changed

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
        config_mod.set_values(self.config_path, {write_key: key})
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
        config_mod.set_values(self.config_path, {name: value})
        fresh = config_mod.load(self.config_path)
        section, _, key = name.rpartition(".")
        if name == "auto_pause_fullscreen":
            return self._set_auto_pause(fresh.auto_pause_fullscreen)
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
            live = True
        message = (f"{name} saved" if live
                   else f"{name} saved — it applies the next time it starts")
        self._say(message)
        log.info("%s", message)
        return message

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
        self.notify_card.start()
        self.notify.start()
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
        # The second learning channel (study.py): revisit recordings the
        # user already sent, when the machine is idle, and learn from what
        # the live pass got wrong. Built like skin/: a getattr and a
        # guarded import, so on a version whose config.py has no [study]
        # section — classic — this whole block is four cheap no-ops and
        # main.py stays byte-identical on both branches.
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
                    review_mod.Store(APP_DIR / review_mod.STORE_NAME),
                    model_lock=self._model_lock,
                    quiet=self._learning_quiet, app_dir=APP_DIR,
                    on_suggest=self._review_show,
                    on_accept=self._review_fix)
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
                    app_dir=APP_DIR)
                self._study.start()
            except Exception as e:      # noqa: BLE001 — optional feature
                log.info("study engine unavailable (%s)", e)

    def stop(self) -> None:
        self._stopping.set()      # ends the fullscreen watcher's wait()
        # The hold first: it is the one thing here that changed the
        # MACHINE (the wake hold, a pinned sleep timer), and the rest of
        # this method cannot fail in a way that should leave that in place.
        if getattr(self, "awake", None) is not None:
            self.awake.release()
        if getattr(self, "_study", None) is not None:
            self._study.stop()
        if getattr(self, "_review", None) is not None:
            self._review.stop()
        self.dot.stop()
        self.hint.stop()
        self.review_card.stop()
        # The reminder thread first, then the card it would have shown.
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
                # dismiss | test | recent. dismiss is one JSON write and
                # a queue put; test is receive() on this thread (the same
                # write, an async cue); recent reads the file once. All
                # inside the poll's patience, and the reply carries the
                # fresh state so the Notify screen repaints at once.
                engine = getattr(self, "notify", None)
                if engine is None:
                    return {"ok": False, "error": "notifications are off"}
                do = str(args.get("do", "")).strip().lower()
                if do == "dismiss":
                    state = engine.dismiss(by="dashboard")
                    self._say("notifications dismissed")
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
            if command == "quit":
                singleton.request_quit()
                return {"ok": True}
            return {"ok": False, "error": f"unknown command {command!r}"}
        except (ValueError, ConfigError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            log.exception("control command %r failed", command)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

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
        started = time.monotonic()
        text, backend = self._transcribe(wav, language=None)
        transcript_log.info("OK | PHONE | %s | %.1fs latency | %s",
                            backend, time.monotonic() - started, text)
        # Same blocking pass the desktop runs, under the same ceiling: both
        # have somebody waiting on the other end of it.
        text = self._improve(text.strip()) if text.strip() else text
        # A decoder loop means words are LOST, not garbled — surface that
        # on the phone right away instead of letting reading discover it.
        warning = None
        for b in (self.transcriber, self._local or None):
            found = getattr(b, "last_warning", None)
            if found:
                warning = found
                break
        return text, backend, warning

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
                scale=hcfg.scale, on_change=self._save_hint)
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
        beep("start")
        log.info("recording %s... (release to transcribe%s)",
                 language_label(language, shout=True),
                 f", tap '{self.cfg.latch_hotkey}' to lock it on"
                 if self.cfg.latch_hotkey else "")

    def _on_stop(self, language: str | None = "he") -> None:
        # end_pieces, not end: a recording the ask card interrupted comes
        # back cut at the questions, so the worker can transcribe what
        # surrounds them and splice the questions back in. Nothing asked
        # means one piece and the old path exactly.
        wav, pieces, seconds = self.recorder.end_pieces()
        self._set_state("busy")
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
        self.queue.put((wav, seconds, hwnd, language, self._to_card,
                        {"pieces": pieces} if len(pieces) > 1 else {}))
        log.info("captured %.1f s of %s -> transcribing (%s)...", seconds,
                 language_label(language),
                 self.transcriber.name)

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

    def _on_overflow(self) -> None:  # PortAudio callback thread
        beep("error")
        log.warning("recording passed the %.0f s cap — discarding. %s",
                    self._cap,
                    "Tap the latch key to clear it."
                    if self._latched else "Release the key.")

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
                    language: str | None = None) -> tuple[str, str]:
        """Cloud first; local only once every cloud model is out of quota.

        Serialised: the phone endpoint runs on its own threads and would
        otherwise hit the same Whisper model as the desktop worker at the
        same moment. This is the one choke point both paths pass through.

        """
        with self._model_lock:
            try:
                text = self._call(self.transcriber, wav, language)
                self._last_words = list(
                    getattr(self.transcriber, "last_words", None) or [])
                return text, self.transcriber.name
            except RateLimitError:
                local = self._local_backend()
                if local is None:
                    raise
                text = self._call(local, wav, language)
                self._last_words = list(
                    getattr(local, "last_words", None) or [])
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
            log.info("learned %d correction(s): %s", len(pairs),
                     " | ".join(f"{h} -> {m}" for h, m in pairs))
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
                with self._cursor_lock:
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
                            "it: %s", self.cfg.paste_chord, fixed)
                return

            injector.paste_text(fixed, self.cfg.paste_chord,
                                self.cfg.restore_delay_ms)
            beep("punctuated")
            self._bump(punctuations=1)
            self._say(f"punctuated {len(text)} chars in {latency:.1f} s "
                      f"via {backend}")
            log.info("punctuated %d chars in %.1f s via %s: %s", len(text),
                     latency, backend, fixed)
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
                     "under [lookup] in config.toml to try it anyway.",
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
                         "[lookup] in config.toml to have Hebrew come back "
                         "as English.")
            else:
                refuse("noop", "lookup-nothing-to-translate",
                       "nothing to translate in that selection")
                log.info("nothing to translate in that selection (a URL, a "
                         "path or no words at all): %.40s", text)
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
        log.info("looked up %d chars in %.1f s via %s (%s -> %s): %s",
                 len(text), answer.seconds, answer.backend, answer.mode,
                 answer.target, answer.text)

    def _improve(self, text: str, wait: bool = True,
                 max_wait_s: float | None = None) -> str:
        """What was learned, applied: repair pass then context pass.

        Both are strictly optional and neither may raise. This sits between
        a person's speech and their cursor, so anything that goes wrong here
        must degrade to "the transcript as the backend produced it" rather
        than to no transcript at all.

        `wait=False` runs only the vocabulary repair — instant, offline, a
        dictionary lookup — and skips the LLM pass entirely.
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
        return self._context_pass(text, max_wait_s)

    def _context_pass(self, text: str,
                      max_wait_s: float | None = None) -> str:
        """The LLM repair, run to completion. Returns the text either way.

        Never raises: this is optional work sitting near a person's words,
        and the failure mode has to be "the transcript as the backend
        produced it", never "no transcript".
        """
        polisher = self._polish()
        if polisher is None:
            return text
        try:
            if not polisher.should_run(text):
                return text
            started = time.monotonic()
            log.info("checking the transcript against %d learned "
                     "confusion(s)...", len(self.vocab))
            polished, by = polisher.polish(text, max_wait_s)
            if by:
                transcript_log.info("POLISHED | %.1fs | %s | %s",
                                    time.monotonic() - started, by, polished)
                log.info("context pass (%s, %.1f s) changed: %s", by,
                         time.monotonic() - started, polished)
                return polished
        except Exception:
            log.exception("the context pass failed — using the transcript "
                          "as it came out of the backend")
        return text

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
                pieces: list | None = None) -> None:
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
        if fb.enabled and hwnd and not diverting:
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

        while True:
            attempt += 1
            try:
                if pieces and len(pieces) > 1:
                    text, backend = self._transcribe_pieces(pieces,
                                                            language)
                else:
                    text, backend = self._transcribe(wav, language)
                break
            except TranscriptionError as e:
                last_error = str(e)
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
            self._say(f"gave up after {latency:.0f} s — the audio is kept in "
                      f"pending\\, run --drain later")
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
        cleaned = text.strip()
        if not cleaned:
            if shown:
                with self._cursor_lock:
                    injector.clear_placeholder(placeholder, hwnd)
            log.info("empty transcript (no speech heard) — not pasting")
            if item:
                item.discard()
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
                                "clipboard, press %s to paste it: %s",
                                self.cfg.paste_chord, cleaned)
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

        # IN FRONT OF THE PASTE, on purpose, and this is the one decision
        # the whole module is arranged around.
        #
        # It was moved BEHIND the paste for a while: paste instantly, repair
        # the text on screen a few seconds later. That is measurably faster
        # to first text and it was rejected for a reason no benchmark shows
        # — the user could no longer tell when the text was FINISHED. A
        # sentence that may still rewrite itself in three seconds is a
        # sentence you cannot send, so the saved seconds were spent waiting
        # anyway, just without knowing what you were waiting for.
        #
        # So the placeholder is the contract: while "..." is on screen
        # nothing is final, and when the text appears it is done and will
        # not move again. polish.max_wait_s bounds how long that can take.
        cleaned = self._improve(cleaned, wait=True)
        # And the punctuation, if the box is ticked — after the repair, so
        # it works on the final words; punctuate.max_wait_s bounds it.
        cleaned = self._auto_punctuate(cleaned)
        kept = None
        # The decoder's per-word confidence belongs to ONE decode; a
        # recording transcribed in pieces has several, so it carries none.
        words = ([] if (pieces and len(pieces) > 1)
                 else list(getattr(self, "_last_words", []) or []))
        if self.recent is not None:
            try:
                kept = self.recent.save(
                    wav, seconds, "",
                    extra={"text": cleaned, "raw": text.strip(),
                           "backend": backend, "language": language or "auto",
                           "words": words})
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
                        "your clipboard, press %s to paste it: %s",
                        self.cfg.paste_chord, cleaned)
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
        self._say(f"{seconds:.1f} s spoken -> {len(cleaned)} chars in "
                  f"{latency:.1f} s via {backend}")
        log.info("pasted %d chars (%.1f s round trip via %s; %s): %s",
                 len(cleaned), latency, backend, status, cleaned)
        # AFTER the paste, never before: the reading is slower than the
        # text and must not be what the text waits for.
        self._review_submit(kept, hwnd)


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
        APP_DIR / "app.log", maxBytes=500_000, backupCount=2,
        encoding="utf-8")
    app_file.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | "
                                            "%(message)s"))
    handlers.append(app_file)
    logging.basicConfig(level=logging.INFO, handlers=handlers)
    file_handler = logging.handlers.RotatingFileHandler(
        APP_DIR / "transcripts.log", maxBytes=1_000_000, backupCount=3,
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
    spool = Spool(APP_DIR / "pending")
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
    recent = Spool(APP_DIR / "recent")
    cases = [i for i in recent.pending() if i.meta.get("corrected")]
    if not cases:
        print("No corrected recordings yet, so there is nothing to measure.")
        print(f"Dictate, then tap '{cfg.correct_hotkey}' and fix what it got")
        print("wrong. Each correction becomes a test case here.")
        if cfg.vocab.keep_audio <= 0:
            print("\nNote: [vocab] keep_audio = 0, so no audio is being "
                  "kept — corrections can never be replayed.")
        return 0

    v = vocab_mod.Vocab(APP_DIR / "vocab.json", seed_terms=cfg.vocab.terms,
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
    v = vocab_mod.Vocab(APP_DIR / "vocab.json", seed_terms=cfg.vocab.terms,
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
        print(f"{len(cfg.vocab.terms)} seed term(s) from config.toml "
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hebrew push-to-talk dictation (hold hotkey, speak, "
                    "release).")
    parser.add_argument("--config", default=str(APP_DIR / "config.toml"))
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
    setup_logging()

    if args.dashboard:
        import dashboard
        return dashboard.main()

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
        print('\nPut the index or a unique name substring into config.toml '
              '-> [audio] device = "..."')
        return 0

    try:
        cfg = config_mod.load(Path(args.config))
    except ConfigError as e:
        # report_fatal, not a bare log line: launched windowless there is
        # nowhere for this to be seen, and a config.toml can now be edited
        # from the dashboard — so "it stopped starting" has to say why.
        report_fatal(str(e))
        return 1
    if args.fake:
        cfg = dataclasses.replace(cfg, backend="fake")

    # The first-run wizard, BEFORE any model is loaded. Two reasons for
    # the position: a wizard that appears after 25 s of nothing has
    # already lost the argument it exists to win, and the microphone it
    # writes has to be the one the Recorder is then opened on.
    if args.setup or (firstrun.needed(cfg) and not args.fake):
        if firstrun.run(cfg, Path(args.config)):
            cfg = config_mod.load(Path(args.config))   # it wrote the device
        if args.setup:
            return 0

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

    if args.benchmark:
        return benchmark(cfg)

    if args.study:
        try:
            import study as study_mod
        except ImportError:
            print("The study engine is not part of this version — switch "
                  "to fast (Versions.vbs) to use it.")
            return 2
        if getattr(cfg, "study", None) is None:
            print("This version's config has no [study] section.")
            return 2
        return study_mod.study_all(cfg, APP_DIR)

    if args.review:
        try:
            import review as review_mod
        except ImportError:
            print("The second reading is not part of this version — switch "
                  "to fast (Versions.vbs) to use it.")
            return 2
        if getattr(cfg, "review", None) is None:
            print("This version's config has no [review] section.")
            return 2
        return review_mod.review_all(cfg, APP_DIR)

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
                "Hebrew dictation is already running (only one instance may "
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
    # anyway, hook live. Same hole for "Stop Dictation.vbs".
    quit_signal = singleton.QuitSignal()

    # Loading two Whisper models onto the GPU takes ~25 s during which a
    # windowless app looks like a shortcut that did nothing. Every log line
    # the app writes becomes a status update, so the splash narrates the
    # real startup instead of just spinning.
    splash = overlay_mod.Splash() if cfg.splash else overlay_mod.Splash.off()
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
    leftover = awake_mod.recover(APP_DIR)
    if leftover:
        log.warning("%s", leftover)
    try:
        splash.status("loading the transcription model…")
        app = App(cfg, config_path=Path(args.config))
    except TranscriptionError as e:   # missing key, stub backend, ...
        return fail(str(e))
    except (ValueError, ConfigError) as e:   # unknown hotkey/chord name
        return fail(f"bad key name in config.toml: {e}")
    except Exception as e:            # no input device, PortAudio errors
        return fail(f"could not start audio capture: {e}\n\nCheck Settings "
                    "> Privacy & security > Microphone, and the device "
                    "index in config.toml (see --list-devices).")

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
    log.info("ready — hold '%s' for %s%s, release to paste. %s",
             cfg.hotkey,
             "Hebrew or English" if cfg.auto_language else "Hebrew",
             f", '{cfg.english_hotkey}' for English" if cfg.english_hotkey
             else "",
             "Ctrl+C here to quit." if HAS_CONSOLE
             else 'Double-click "Stop Dictation.vbs" to quit.')
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
                 ", cloud upload OFF" if not vqa_cfg.allow_screenshot_upload
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
        log.info("notifications: POST /notify on the phone endpoint (token "
                 "from server_token.txt) plays a cue and puts a card up%s; "
                 "Claude Code is wired through notify_hook.py",
                 f"; tap {ncfg.hotkey!r} to dismiss" if ncfg.hotkey else "")
    log.info("mic: %s | backend: %s | transcripts: %s",
             app.recorder.device_label(), cfg.backend,
             APP_DIR / "transcripts.log")
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
    beep("ready")
    log.removeHandler(splash_log)
    splash.finish(f"ready — hold {cfg.hotkey.title()} and speak")
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
