"""Config loading and validation (config.toml, stdlib tomllib).

Writing it back is here too, and it is a line editor rather than a TOML
serialiser on purpose: config.toml is two thirds comments, and most of
those comments are measurements that cost hours to obtain. A round trip
through a TOML writer would silently delete every one of them the first
time the dashboard changed a hotkey.
"""
from __future__ import annotations

import os
import re
import tomllib
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

VALID_BACKENDS = ("gemini", "local", "fake")

# What Ollama accepts for keep_alive: a Go duration ("30m", "8h", "1h30m")
# or a bare number of seconds, either of them negative to mean "hold it
# until Ollama stops". Written down here because the only other place that
# knows is Ollama, and it says so with an HTTP 400.
_DURATION = re.compile(r"-?(?:\d+(?:\.\d+)?(?:ns|us|µs|ms|s|m|h))+|"
                       r"-?\d+")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class AudioConfig:
    sample_rate: int = 16000
    device: int | str | None = None  # None = system default input device


@dataclass(frozen=True)
class GeminiConfig:
    # Free-tier quota is counted per model, so a list is a longer runway:
    # each entry is tried in order and rested when it reports its cap.
    models: tuple[str, ...] = ("gemini-2.5-flash", "gemini-flash-latest",
                               "gemini-2.5-flash-lite",
                               "gemini-flash-lite-latest")
    timeout_s: int = 30

    @property
    def model(self) -> str:
        return self.models[0]


@dataclass(frozen=True)
class FeedbackConfig:
    """The at-the-cursor progress marker.

    Pasted the moment the key is released and replaced by the transcript
    when it arrives, so the text lands where the user was speaking even if
    the request takes 30 seconds or has to be retried.
    """
    placeholder: str = "..."
    enabled: bool = True
    # How long the worker keeps retrying at the cursor before giving up and
    # leaving the recording in the spool for --drain.
    retry_seconds: float = 45.0


@dataclass(frozen=True)
class HintConfig:
    """The card that appears while the dictation key is held.

    It exists for one complaint: mid-dictation the other keys used to do
    nothing at all, silently, and a key that does nothing silently is
    indistinguishable from a key that is broken. The card names what a
    release, the latch arrow and Escape will do, and lists the feature
    keys with the ones that are REFUSED right now greyed out and given a
    reason — an answer instead of a shrug.

    `after_ms` is why this is not clutter. A two-second dictation never
    sees it; the card is for the press you hesitated on, which is exactly
    when someone has forgotten what the keys do.
    """
    enabled: bool = True
    after_ms: int = 400
    corner: str = "top-right"
    # Where it was last dragged to, and how big it was last made. Written
    # by the card itself, which is why they are settings and not state in
    # a side file — everything else the card knows lives here, and a
    # second store would be a second place to look when it comes back in
    # the wrong place.
    #
    # HINT_UNSET, not -1, and that is a bug this already had: a monitor to
    # the LEFT of the primary has genuinely negative screen coordinates
    # (measured on this machine: the virtual desktop starts at x = -1920),
    # so every card dragged onto it saved a negative x that -1's rule then
    # discarded. The sentinel has to be a number no desktop can reach.
    x: int = -100000
    y: int = -100000
    scale: float = 1.0


HINT_CORNERS = ("top-right", "top-left", "bottom-right", "bottom-left")
HINT_SCALE_MIN, HINT_SCALE_MAX = 0.6, 1.4
HINT_UNSET = -100000


@dataclass(frozen=True)
class SetupConfig:
    """Switch the first-run wizard off by hand.

    NOT the record of whether it has run — that is `.setup-done`, a
    gitignored file beside config.toml (see firstrun.MARKER). This file is
    tracked, so whatever is committed here is what a fresh download gets:
    true would mean nobody ever saw the wizard, false would re-run it on
    every install that updated, and there is no third value that means
    "this particular copy, yes; that one, no". A fact about one
    installation belongs in a file that installations do not share.

    It stays here as an override because a setting someone can find and
    flip beats a dotfile they have to be told about.
    """
    done: bool = False


@dataclass(frozen=True)
class LocalConfig:
    model: str = "ivrit-ai/whisper-large-v3-turbo-ct2"
    language: str = "he"  # pinned — the ivrit-ai fine-tune broke autodetect
    device: str = "auto"  # auto | cuda | cpu — auto tries the GPU first
    # Whisper transcribes only; Gemini also cleans. Without this, the local
    # backend regresses output quality on real (hesitant) dictation.
    cleanup: bool = True
    extra_fillers: tuple[str, ...] = ()
    # Biases the decoder towards Hebrew-with-English-terms, which is how
    # this gets used. Measured 2026-08-12: Hebrew WER 10.8% -> 9.6%, and
    # mixed utterances stopped losing their English half entirely.
    initial_prompt: str = ("שיחה בעברית עם מונחים טכניים באנגלית כמו "
                           "commit, branch, pull request, merge, deploy, "
                           "terminal, repo, bug, feature.")
    # The Hebrew fine-tune transliterates short pure-English utterances.
    # Confident English is routed to a general model instead. "" disables.
    english_model: str = "deepdml/faster-whisper-large-v3-turbo-ct2"
    # Deliberately high: misdetected short Hebrew is far worse than a
    # transliterated English word, and every misdetection measured was
    # low-confidence while correct Hebrew sat at 0.91-0.99.
    english_threshold: float = 0.8
    # Tighten Whisper's own hallucination guards. The library defaults let
    # a low-confidence trailing segment through; measured 2026-08-12, these
    # cost nothing on good audio (identical text, ~8% slower).
    guard_hallucinations: bool = True
    # Beam width for the decoder. 5 is what this always ran; lower (try 2)
    # transcribes faster on exactly the short clips dictation produces, at
    # a small accuracy cost — measure both ways with --benchmark before
    # keeping a change. 1 = greedy.
    beam_size: int = 5
    # Drop parliamentary boilerplate stuck to the END of a transcript. The
    # ivrit-ai fine-tune is trained on Knesset protocols and appends them
    # when the decoder runs past the end of real speech.
    drop_trailing_boilerplate: bool = True
    # Your own phrases to treat the same way, e.g. a jingle the model keeps
    # tacking on. Whole phrases only — single common words strip real speech.
    extra_boilerplate: tuple[str, ...] = ()


@dataclass(frozen=True)
class TranslateConfig:
    """The tap-to-translate key: turns text already at the cursor into
    English, in place."""
    target: str = "English"
    # A guard, not a preference. The key selects the whole field when
    # nothing is selected, and in a document editor "the whole field" is
    # the entire document — refusing above this keeps a stray press from
    # replacing a file's worth of text.
    max_chars: int = 5000
    ollama_model: str = "llama3.1:8b"
    ollama_url: str = "http://127.0.0.1:11434"
    timeout_s: int = 30
    # Deliberately much larger than timeout_s. Ollama loads the model into
    # VRAM on the first request after it goes idle: measured 2026-08-12,
    # 76 s cold for llama3.1:8b against 2.5 s warm. At 30 s the fallback
    # would time out exactly when it is first needed.
    ollama_timeout_s: int = 150
    copy_chord: str = "ctrl+c"
    select_all_chord: str = "ctrl+a"
    # How long the focused app is given to answer a copy. Chromium inputs
    # answer in well under 50 ms; this is slack for a busy machine.
    settle_ms: int = 120


@dataclass(frozen=True)
class PunctuateConfig:
    """The tap-to-punctuate key: puts the commas, full stops and question
    marks into text already at the cursor — see punctuate.py.

    Whisper transcribes sounds, not sentences, and the local Hebrew
    fine-tune produces almost no punctuation at all. The grab mechanics
    (which chords, how long the focused app is given to answer) are
    deliberately NOT repeated here: they belong to the app and the machine,
    not to the job, so this key reads them from [translate].
    """
    # The same guard as translate.max_chars and for the same reason: with
    # nothing selected the key takes the whole field, which in a document
    # editor is the whole document.
    max_chars: int = 5000
    # Groq first (see punctuate.py). Measured 2026-09-01 on 12 real
    # dictations: it kept every word 10 times, in 0.5-1.5 s (median 0.8) —
    # gemini's quality at ~1,000 requests/day instead of gemini's
    # 20/day/model, which is the bucket translation also draws on. The
    # other two follow whichever goes first, so a spent quota costs one
    # fallback and not the key.
    prefer: str = "groq"
    # "" = reuse polish.groq_model — or, where the Config has no [polish]
    # fields at all (classic's), the model polish.py was measured on.
    groq_model: str = ""
    # "" = reuse translate.ollama_model.
    ollama_model: str = ""
    # Punctuate every dictation on its way to the cursor, so the key is
    # never needed. Off by default: it is about a second more before the
    # text lands (the measurement above), and the owner chose to pay that
    # only by ticking a box — one switch, no warning.
    auto: bool = False
    # How long the auto pass may hold the paste before the transcript goes
    # in as it came. The key has no deadline: nothing is waiting on it.
    max_wait_s: float = 6.0
    # Also add Hebrew vowel points, not only punctuation. Off by default:
    # it is a much bigger change to the text, and the same safety check
    # covers it either way (nikud are combining marks, so they vanish from
    # the letters-only comparison exactly like a comma does).
    nikud: bool = False


@dataclass(frozen=True)
class LookupConfig:
    """The key that reads instead of writing — see lookup.py and popup.py.

    Select a word or a sentence anywhere, tap the key, and a small box
    appears with the translation. It never types, never pastes and never
    changes anything on screen, which is the whole point: it works on a
    web page, a PDF, a chat window — every place F9 and F7 have nothing
    they are allowed to write to.

    It has exactly one way of changing anything, and it is the one you
    ask for: the copy buttons in the box, and the Ctrl+C behind them.
    That copy is meant to outlive whatever else the app is doing —
    injector.claim_mark() is what stops the other keys putting your old
    clipboard back over it.

    Like [punctuate], the grab mechanics are deliberately NOT repeated
    here. The copy chord and the Ollama endpoint belong to the machine and
    are read from [translate]; what is here is the job.
    """
    # Which way to translate is decided per selection, by counting WORDS
    # and not letters: "תעשה commit לפני ה-merge" is 9 Hebrew letters
    # against 11 Latin ones, so a letter count calls that sentence
    # English. Hebrew is written without vowels, which makes words the
    # only fair unit. Ties go to Hebrew-as-target.
    hebrew_share: float = 0.34
    # Both directions, or Hebrew only.
    both_ways: bool = True
    # Over this the key refuses and spends nothing. WAS 5000, which the
    # owner kept hitting with select-all ("it didn't translate") — now
    # the local model is fed in ~3800-char parts (see lookup._LOCAL_CHUNK),
    # so a long page translates in visible stages instead of being
    # refused. Still a ceiling: 20000 chars is minutes locally, and past
    # the Ollama runner's context window even chunks would degrade.
    max_chars: int = 20000
    # The OPPOSITE of [translate] and [punctuate], deliberately. The free
    # Gemini tier is 20 requests per model per day and those two keys
    # already spend 34/39/17/18 of them on a working day; a key tapped
    # while READING would take the rest of the pool and break the two keys
    # whose local fallback is the weak one.
    prefer: str = "ollama"
    # "" = reuse translate.ollama_model. Its own knob because this key
    # wants the model [polish] already keeps resident, not the fallback:
    # measured, qwen2.5:7b answered "brittle" with '?");'.
    model: str = "gemma3:12b"
    # A cold Ollama is 22-25 s to the first token. Rather than make you
    # watch that, a cold model sends this one lookup to the cloud and
    # warms the local one in the background.
    cold_to_gemini: bool = True
    # How long Ollama holds the model after a lookup. Its own default is
    # five minutes, which a reading session outlasts: measured
    # 2026-08-19, a lookup nine minutes after the last dictation paid
    # 23.19 s. This is SHARED — keep_alive belongs to the loaded runner,
    # so what this key sends [polish] then inherits. "" sends nothing.
    keep_alive: str = "30m"
    # gemma3:12b sometimes answers in vowel-pointed Hebrew (3 runs in 12,
    # input-specific, and a prompt rule does not fix it). The box is for
    # reading a meaning off, not for learning to pronounce it.
    strip_niqqud: bool = True
    # Dead: main.py passes popup.show a literal 0 and never reads this.
    # The box waits to be closed, by the x in its corner or by Esc. Kept
    # so an existing config.toml still loads, and validated below so a
    # negative one is still refused rather than silently ignored.
    dwell_ms: int = 12000
    # Pixels. Both cap what the box OPENS at: measure() is unbounded and
    # a 22-sentence paragraph made a 896 px tall window — taller than some
    # work areas. Past the caps the face shrinks first (19 px down to an
    # 11 px floor) and only then is overflow trimmed with an ellipsis.
    max_width: int = 460
    max_height: int = 520
    # Answers are stable and lookups repeat, which is the whole point of
    # the key, so they are kept in lookup_cache.json next to vocab.json.
    # Measured 134 bytes an entry. 0 keeps none.
    cache_entries: int = 500
    # Windows Terminal turns the copy into a real Ctrl+C for whatever is
    # running there when nothing is selected — reproduced 5 times out of
    # 5. With this on, the key refuses in console windows rather than
    # killing your build.
    skip_consoles: bool = True


@dataclass(frozen=True)
class VisualQAConfig:
    """Ask-the-screen: drag a rectangle, ask about it by voice or keyboard
    — see visual_qa.py.

    LOCAL-FIRST BY DEFAULT, and stricter than every other feature here:
    `allow_screenshot_upload = false` does not merely prefer the local
    model, it makes the cloud builders UNCONSTRUCTABLE — a screenshot can
    hold mail, banking, anything on screen, so it is treated as strictly
    more sensitive than transcript text (which [polish] may already send).
    The gate is enforced in the backend-chain builder, not at request time,
    and there is a test asserting the chain is cloud-free while it is off.
    """
    # false unregisters the hotkey entirely — the kill switch.
    enabled: bool = True
    # Named so nobody can misread it. false (the default) makes the cloud
    # vision backends unconstructable — see the class docstring above.
    allow_screenshot_upload: bool = False
    hotkey: str = "ctrl+f10"
    # Which backend asks first; the others follow underneath it, ollama
    # always among them. Cloud names only matter while the upload gate
    # above is true.
    prefer: str = "ollama"
    # The repair model this app already keeps resident IS a vision model
    # (gemma3:12b reports capabilities ['completion', 'vision']) — no new
    # pull, no new VRAM residency.
    ollama_model: str = "gemma3:12b"
    groq_model: str = "qwen/qwen3.6-27b"
    # Include the shared Gemini pool after Groq when uploading is allowed.
    gemini_fallback: bool = True
    max_side_px: int = 1344
    num_predict: int = 400
    speak: str = "button"
    voice: str = "Microsoft Asaf"
    # A spoken question sends itself the moment the transcript lands, and
    # speaking again over an answer supersedes it — the conversation is
    # meant to run by voice alone. false restores speak-then-Enter.
    auto_send: bool = True
    # What you dictate INTO the card is a question, and until now that was
    # ALL it was: it went to the card and nowhere else, which is right
    # until the card is something you opened in the middle of writing.
    # true also pastes it into the field you were dictating into before
    # the card opened — ONCE THE CARD CLOSES, never while it is up: the
    # card holds the foreground, so pasting from under it would either
    # steal focus mid-sentence or land in the card itself.
    echo_to_field: bool = True
    # The floating card's opacity. Below ~0.85 ClearType over a
    # translucent surface stops being crisp (popup.py's measurement);
    # the card goes fully opaque while the pointer is over it anyway.
    window_alpha: float = 0.93
    warmup: bool = True
    ollama_timeout_s: int = 120
    cloud_timeout_s: int = 30


@dataclass(frozen=True)
class CaptureConfig:
    """Screenshots and screen recordings — see capture.py.

    THE ONE THING TO GET RIGHT ABOUT THIS SECTION: unlike [visual_qa],
    whose screenshot lives in memory and is never written down, this
    feature's whole job is to write pictures of your screen to disk. So
    `folder` is treated the way transcripts.log is — it sits beside the
    app, it is gitignored, and nothing in capture.py uploads anything
    anywhere. The only route from a capture to a model is the editor's Ask
    button, which hands the pixels to visual_qa and obeys
    `visual_qa.allow_screenshot_upload` like every other question.

    The microphone is off by default. A screen recorder that quietly opens
    the mic is a surprise, and this app's rule is that audio does not
    travel; `audio = "mic"` is the owner choosing otherwise, on purpose.
    """
    # false unregisters BOTH keys entirely — the kill switch.
    enabled: bool = True
    # Tap: freeze the screen, drag or lasso, and the picture is on the
    # clipboard and on disk before the mouse comes back up.
    hotkey: str = "ctrl+f11"
    # Tap: pick a region and record it. Tap again to stop.
    record_hotkey: str = "ctrl+f12"
    # Relative names are relative to the APP folder, not to whatever
    # directory the process was started from — this app is launched from a
    # .vbs, a shortcut and a scheduled task, and all three disagree.
    folder: str = "captures"
    # Win+Shift+S's promise: the capture is pasteable immediately. false
    # still writes the file.
    copy_to_clipboard: bool = True
    # toast | editor | nothing. What happens AFTER the drag.
    #
    # "toast" is the default and the reason this field replaced a bool: an
    # editor that opens over the whole screen after every capture makes
    # the common case — drag, paste, carry on — pay for the rare one, and
    # the common case is nine captures in ten. A small card in a corner
    # for a few seconds offers the editor instead of imposing it.
    after_shot: str = "toast"
    # Which corner that card appears in. Same four as timer_corner, and
    # deliberately its own setting: the recording pill and the capture
    # card can want different corners on the same desk.
    toast_corner: str = "bottom-right"
    # How long it waits before giving up on you. The clock pauses while
    # the pointer is on the card.
    toast_seconds: int = 5
    # Write EVERY capture to `folder`, or only the ones you ask to keep.
    #
    # false is the default, and it is the one setting here that gives up
    # something real: the picture is on the clipboard and nowhere else
    # until Save is pressed, so copying something else inside those few
    # seconds loses it. The trade is a folder that holds the captures you
    # meant to keep instead of every rectangle you ever dragged — and the
    # folder is the most sensitive thing in this repo, so a smaller one is
    # worth something on its own. true restores the old promise exactly.
    always_save: bool = False
    # A finished clip goes on the clipboard as a FILE (CF_HDROP), so it can
    # be pasted into a chat or a folder the way Explorer's Copy does.
    copy_clip_path: bool = True
    # 30 was measured achievable at 720p and 1080p with zero dropped
    # frames; a 1440p region falls to ~28 because the GRAB costs 32 ms,
    # and the clip is still real-time because every frame is stamped with
    # a wall clock rather than a frame number.
    fps: int = 30
    # small | balanced | sharp — crf 30 / 26 / 20. Screen content is flat
    # colour and sharp edges, which h264 likes: these are several steps
    # softer than the same names would mean for camera video.
    quality: str = "balanced"
    # BitBlt does not include the pointer (the compositor draws it over
    # everything, not into the screen bitmap), so it is painted in. A
    # recording without one is a recording where nobody can tell what is
    # being pointed at.
    cursor: bool = True
    # off | mic. Default off, see the class docstring. The clip bar has a
    # mute switch for a recording that HAS a track: an mp4 declares its
    # streams when the container opens, so a track cannot be added later.
    audio: str = "off"
    # A backstop, not a budget: a key tapped by accident should not fill
    # the disk overnight. 0 = no cap.
    max_minutes: int = 30
    # Which corner the recording indicator sits in, or "off" for none. A
    # corner rather than "beside the region": an indicator that moves when
    # the region does is an obstruction, and a corner is somewhere you can
    # learn to glance at.
    timer_corner: str = "bottom-right"
    # Say "Recording started" for a couple of seconds before shrinking to
    # the pill. The failure mode of a screen recorder is not knowing
    # whether it is running, and this is the cheapest possible answer.
    announce: bool = True


@dataclass(frozen=True)
class CameraConfig:
    """The webcam key — the other half of capture.py.

    A KEY THAT OPENS THE LENS IS A DIFFERENT PROMISE FROM ONE THAT READS
    THE SCREEN, which is why this is its own section and not three more
    lines in [capture]. A screenshot is of pixels the owner is already
    looking at. A photograph is of the room. So: nothing opens the camera
    but this key, the light comes on only while the window is up, the
    device is released the instant the shutter fires rather than when the
    editor closes, and `enabled = false` unregisters the key entirely.

    Where the picture GOES is the same story [capture] tells: `folder`,
    beside the app and gitignored, and no upload path anywhere in the
    module. The only route from a photo to a model is the editor's Ask
    button, which is visual_qa's own gate.

    MEASURED ON THIS MACHINE, 2026-08-26, on an eMeet C960:
        open -> first frame       654-829 ms
        delivered                 25 fps at 1280x720 mjpeg
        one frame to the window    5.4 ms
        listing the devices      147 ms
    """
    # false unregisters the key entirely — the kill switch.
    enabled: bool = True
    hotkey: str = "ctrl+f6"
    # Which camera, matched as a case-insensitive SUBSTRING of the name
    # Windows knows it by ("eMeet" is enough). Empty = the first device
    # DirectShow lists that is not a virtual camera — OBS, Teams and
    # NVIDIA Broadcast all install one and they sort ahead of the real
    # webcam as often as not.
    device: str = ""
    # What to ask the camera for. MJPEG is requested at this size; a
    # camera that has no MJPEG pin gets asked again for whatever it has
    # (measured: this one offers 1080p30 as mjpeg and 1080p5 as raw, and
    # dshow takes the raw one unless it is told otherwise).
    size: str = "1280x720"
    fps: int = 30
    # Mirror the picture — BOTH the preview and the file, or neither. Off
    # by default because the commonest thing anyone holds up to a webcam
    # has writing on it. "m" flips it while the window is open.
    mirror: bool = False
    # 0, 3 or 10 seconds of self-timer. "t" cycles it while the window is
    # open; this is only what it starts at.
    timer: int = 0
    # Same folder as the screen captures by default: one place to look for
    # pictures. The files are named "photo ..." rather than "shot ...".
    folder: str = "captures"
    copy_to_clipboard: bool = True
    # After the shutter, the photo opens in the SAME editor a screenshot
    # does — crop, draw, arrow, blur, Ask — laid on the screen exactly
    # where the preview was. false makes the key a pure "take it and get
    # out of my way"; the file and the clipboard are identical either way.
    edit_after_shot: bool = True


@dataclass(frozen=True)
class NightConfig:
    """Night mode — see night.py: the screen off, the machine awake, so
    the phone can drive it through Claude until morning.

    One key and a dashboard screen. The key toggles; the screen has the
    same switch, "screen off again" for after the mouse lit it, and a
    check that says whether the machine will still be there at seven.
    `enabled = false` unregisters the key; the dashboard's button keeps
    working, because the engine is built either way.
    """
    enabled: bool = True
    hotkey: str = "ctrl+alt+n"
    # Also pin the sleep/hibernate idle timers to "never" while night
    # mode is on and put the old numbers back on the way out — or at
    # the next start, from night_state.json, if the app died with it on.
    # Off: SetThreadExecutionState already covers classic S3 sleep (what
    # this machine does), and a pinned timer is a second thing to
    # restore.
    pin_timeouts: bool = False
    # The screen is put out again this many seconds after the first
    # time, because the mouse movement that follows the click lights it
    # straight back up. 0 = once only.
    screen_off_again_s: int = 3


@dataclass(frozen=True)
class VocabConfig:
    """The learned vocabulary — see vocab.py.

    `terms` is the hand-written seed: your own stack, the names the model
    has no way of knowing. It is kept in config.toml (and therefore in git)
    rather than in vocab.json, which holds what was learned from your
    speech and is gitignored for the same reason transcripts.log is.
    """
    enabled: bool = True
    terms: tuple[str, ...] = ()
    # Well under faster-whisper's 223-token hotword ceiling: Hebrew costs
    # several tokens a word, and over-prompting Whisper makes it emit the
    # prompted words unbidden. A long list is not a better list.
    max_terms: int = 40
    # How many independent corrections of the same garble before it is
    # repaired automatically. 1 would let a slip in the edit box start
    # rewriting a word you really say.
    replace_after_hits: int = 2
    # How many corrections a HEBREW pair needs before its corrected form
    # is fed to the decoder as a hotword; a Latin term gets in at once.
    # Measured 2026-09-02: nine one-hit Hebrew phrases in the prompt
    # turned a 2.8 s clip of five words into 29 (vocab.py, _ranked).
    hebrew_after_hits: int = 3
    # How many recent recordings to keep, so a correction can be tied to the
    # audio that produced it. 0 = keep none.
    #
    # PRIVACY: this is raw audio of what you dictated, on this disk, in
    # recent\. It is gitignored, capped, and the oldest is dropped as new
    # ones arrive. Set to 0 if that trade is not worth it — everything else
    # here still works, you just lose the ability to MEASURE whether a
    # vocabulary change helped (--benchmark) rather than assume it did.
    keep_audio: int = 50


@dataclass(frozen=True)
class PolishConfig:
    """The context pass — see polish.py.

    `when`:
      never   — off.
      known   — only when the transcript contains something you have
                corrected before. Keeps most dictations fast and misses
                most repairs; the setting to reach for if the wait bites.
      always  — every dictation. THE DEFAULT: it adds ~5 s to every paste
                and earns it, catching the mishearings that have never been
                corrected before, which is most of them (17.9% -> 13.9% WER
                on the corrected clips, 3 better and 0 worse).
    """
    when: str = "always"
    # Below this a "sentence" is a phrase with no context to reason from,
    # which is precisely where a model starts inventing one.
    min_chars: int = 20
    # "" = reuse translate.ollama_model. A separate knob because repairing
    # Hebrew wants a stronger model than translating does, and you may not
    # want to pay for that on every dictation.
    #
    # Measured 2026-08-17 on the 11 recordings in recent\ that carry a
    # `corrected` field — real dictations with the intended words known,
    # because the user typed them:
    #     raw transcript       14.2% WER
    #     gemma3:12b           10.9% / 10.7% on two runs, 4-5 better, 0 worse
    #     qwen2.5-coder:14b    13.8%   4 better, 2 worse
    #     llama3.1:8b          16.0%   3 better, 3 WORSE, 5 rejected
    #     aya-expanse:8b       15.7%   0 better, 2 worse, 9 rejected
    #     dictalm2.0-instruct  14.2%   0 better, all 11 rejected
    # The Hebrew-native model was the obvious bet and it lost: it does not
    # hold the output format, and one reply came back 158 words long against
    # a 2-word transcript. General ability at following a narrow instruction
    # beat Hebrew specialisation. llama3.1:8b — what this defaulted to
    # before — makes the transcript WORSE than leaving it alone.
    ollama_model: str = "gemma3:12b"
    # Which backend repairs first, and which waits as the fallback.
    #
    #   "groq"     — Groq's free API (console.groq.com, no credit card,
    #                thousands of requests a day). Sub-second repairs.
    #                Needs GROQ_API_KEY in .env; without one it is skipped
    #                automatically and this setting costs nothing. THE
    #                DEFAULT because it is the only cloud free tier that
    #                actually exists as of Aug 2026 — Cerebras, the first
    #                choice here, went paid-only ($1,500+/month tiers,
    #                measured live on a fresh account).
    #   "cerebras" — kept working for whoever holds quota there. Paid now.
    #   "ollama"   — exactly classic: local gemma3:12b, no cloud ever.
    #
    # Gemini is deliberately not on this list, here or anywhere in this
    # pass — see polish.py for why that rule survived the rewrite.
    prefer: str = "groq"
    # Which Groq model to ask. openai/gpt-oss-120b is the strongest on
    # their free catalog (measured 2026-08-22; llama-3.3 is no longer
    # offered) and, with reasoning_effort=low set by the translator,
    # answers a repaired sentence in ~0.3 s. The letter-for-letter safety
    # check (_is_safe) covers any of them, so a weaker model wastes a
    # request rather than your words.
    groq_model: str = "openai/gpt-oss-120b"
    # Separate knob per provider: a warm Groq answer lands in well under
    # 2 s, so past this something is wrong and the fallback should have
    # the work instead.
    groq_timeout_s: int = 20
    # Which Cerebras model to ask. Only relevant while quota exists there;
    # kept so returning to it later means editing config.toml, not code.
    cerebras_model: str = "gpt-oss-120b"
    # Separate from translate.timeout_s because it is a different provider:
    # warm answers land in well under 2 s, so past this something is wrong
    # and the fallback should have the work instead.
    cerebras_timeout_s: int = 20
    # HOW LONG THE PASTE MAY BE HELD UP. This pass sits between the words
    # leaving your mouth and the text reaching your cursor: past this, the
    # unrepaired transcript is pasted and the reply is thrown away when it
    # eventually arrives.
    #
    # 10 s, not 6: gemma3:12b averages 4.7-5.5 s and peaks at 6.2 s, so 6
    # would time out on exactly the long dictations that need it most. It is
    # deliberately NOT generous beyond that — every second here is a second
    # of staring at "..." — and it also caps the damage from a cold Ollama
    # (76 s on the first request after it idles, measured 2026-08-12).
    max_wait_s: float = 10.0
    # Send one throwaway request at startup so the ~5 GB is already in VRAM
    # before a dictation needs it (76 s cold vs 2.5 s warm). Costs the VRAM
    # for the whole session; set false if you would rather pay the wait.
    warm_up: bool = True


@dataclass(frozen=True)
class StudyConfig:
    """The second learning channel — see study.py. FAST VERSION ONLY:
    classic's config.py does not read this section, and main.py (shared)
    only builds the engine when cfg carries it."""
    enabled: bool = True
    # How long the app must be visibly idle (no dictation, no key work)
    # before a recording is studied. The pass steps aside again the moment
    # anything happens, so this is about not warming the GPU while the
    # user is mid-thought, not about safety.
    idle_minutes: float = 3.0
    # Clips longer than this are skipped: three extra decodes of a very
    # long recording hold the model lock in chunks for little extra
    # evidence — the garbles repeat in the first two minutes anyway.
    max_clip_seconds: float = 120.0
    # LLM adjudications per day. Spends the polish pass's Groq bucket
    # (~1,000/day), so this is generous headroom, not a tight budget;
    # past it the acoustic consensus vote still runs.
    llm_per_day: int = 60
    # Verified (audio, text) pairs kept in corpus\ as future fine-tuning
    # data. ~1 MB per 30 s clip; 400 is roughly 3-4 hours of speech.
    # 0 keeps none.
    corpus_keep: int = 400


@dataclass(frozen=True)
class ReviewConfig:
    """The second reading — see review.py. FAST VERSION ONLY, like
    [study], which it stands in for while enabled: the same three extra
    decodes serve both, shown as a card instead of learned in silence."""
    enabled: bool = True
    # How long the card stays up before the proposal is left to the
    # dashboard's Review screen. 0 = never a card; the list only.
    card_seconds: float = 20.0
    corner: str = "right"
    # Where it was last dragged to and how big it was made. The card
    # writes these itself, exactly as [hint] does — same sentinel, same
    # reason (a monitor to the left has real negative coordinates).
    x: int = -100000
    y: int = -100000
    scale: float = 1.0
    # The most changes one reading may propose; more is a rewrite.
    max_changes: int = 4
    # A replacement needs this many witnesses: other decodes of the same
    # audio that heard the new words — or the pair is one the owner
    # taught. With one, the weak general model's own mishearing counted
    # as a witness (review.validate); 0 lets the model guess.
    witness: int = 2
    # Ask the local repair model when Groq refuses. Off: measured
    # 2026-09-02, it answered one clip and both proposals were wrong.
    local_model: bool = False
    # The keys that answer the card while the mouse is over it.
    accept_key: str = "v"
    reject_key: str = "x"
    later_key: str = "l"
    edit_key: str = "e"
    # Accepting also corrects the text in the field it was pasted into,
    # when that window is still in front and still holds it verbatim.
    fix_in_field: bool = True
    max_clip_seconds: float = 120.0
    # Language-model readings a day, from the polish pass's Groq bucket.
    llm_per_day: int = 200


REVIEW_CORNERS = HINT_CORNERS + ("right", "left")


@dataclass(frozen=True)
class ServerConfig:
    """The phone endpoint: dictate from the phone, transcribe on this GPU.

    Off by default — it opens a socket, and that should be a decision.
    """
    enabled: bool = False
    # "" = 127.0.0.1. Loopback is not a limitation, it is the design:
    # `tailscale serve` proxies to localhost and terminates TLS, so nothing
    # listens where a stranger — or the home LAN — could reach it, and the
    # phone still gets the certificate its browser demands for microphone
    # access. Binding the Tailscale address instead would make the server
    # invisible to `tailscale serve`.
    host: str = ""
    port: int = 8756


@dataclass(frozen=True)
class Config:
    hotkey: str = "right ctrl"
    # A dedicated key that declares "this one is English". Redundant once
    # auto_language is on, and kept for the case where a key is wanted
    # anyway. "" = off. Avoid alt (menu activation on release) and shift
    # (FilterKeys at 8 s).
    english_hotkey: str = "f9"
    # One key, both languages: the recording is no longer labelled Hebrew
    # before the model has heard it — the model decides per utterance.
    #
    # This replaces an earlier judgement made on one bad number ("English
    # 0.57" on a Hebrew sentence). Measured 2026-08-20 over the 50 real
    # recordings in recent\: the detector routed 8 of them to the English
    # model and every one WAS English — 6 strictly better ("מקמיני" ->
    # "Mac mini", "מי?" -> "Me.", "לייק איי." -> "Like I"), 2 identical —
    # and not one Hebrew recording crossed the 0.8 bar. The pass costs a
    # median 0.18 s per dictation (p90 0.26 s).
    #
    # False pins the key to Hebrew again, which is what it meant before.
    auto_language: bool = True
    # Tapped (not held) to translate the selection — or the whole field
    # when nothing is selected — into English. "" = off.
    translate_hotkey: str = ""
    # Tapped to put the punctuation into the selection — or the whole
    # field when nothing is selected — in place. Whisper transcribes
    # sounds, not sentences, so dictated text arrives with almost none.
    # "" = off.
    punctuate_hotkey: str = ""
    # Tapped WHILE holding the hotkey: locks the recording on, so the
    # hotkey can be released and a long dictation does not mean a long
    # hold. Must be reachable by the hand already on the hotkey, and is
    # swallowed while it acts as the latch — so a key with a job of its own
    # ("left") is fine. "" = off.
    latch_hotkey: str = "left"
    # Tapped to open the correction box on the last transcript. Editing it
    # teaches the vocabulary (see vocab.py) — this is the only way anything
    # is ever learned, because the app cannot see you fix the text inside
    # whatever window you pasted into. "" = off.
    correct_hotkey: str = "f8"
    # Tapped to READ instead of to write: whatever is selected comes back
    # translated in a small box, and nothing on screen changes. On by
    # default because it cannot damage anything it is pressed over — the
    # one key here with no way to be sorry you pressed it. "" = off.
    lookup_hotkey: str = "f6"
    # Tapped to make every key above inert without unloading anything —
    # for playing a game without Right Ctrl starting recordings. Quitting
    # would do the same, and costs ~25 s of reloading two Whisper models
    # onto the GPU to undo; this costs nothing either way. It is the one
    # key that still works while paused. "" = off.
    pause_hotkey: str = ""
    # Pause automatically while a game or a presentation owns the screen,
    # and resume when it lets go. Off by default and deliberately so: it
    # is the only thing here that stops dictation working without anyone
    # asking it to, and "why did my hotkey stop responding" is a much
    # worse half-hour than pressing the pause key yourself.
    auto_pause_fullscreen: bool = False
    backend: str = "gemini"
    paste_chord: str = "ctrl+v"
    restore_delay_ms: int = 300
    min_seconds: float = 0.3
    max_seconds: float = 120.0
    # The cap once latched. 0 = none: max_seconds guards against a key-up
    # the OS swallowed, and a latched recording has no key-up to lose.
    latch_max_seconds: float = 0.0
    audio: AudioConfig = field(default_factory=AudioConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    local: LocalConfig = field(default_factory=LocalConfig)
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    hint: HintConfig = field(default_factory=HintConfig)
    setup: SetupConfig = field(default_factory=SetupConfig)
    translate: TranslateConfig = field(default_factory=TranslateConfig)
    punctuate: PunctuateConfig = field(default_factory=PunctuateConfig)
    lookup: LookupConfig = field(default_factory=LookupConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    study: StudyConfig = field(default_factory=StudyConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)
    vocab: VocabConfig = field(default_factory=VocabConfig)
    polish: PolishConfig = field(default_factory=PolishConfig)
    visual_qa: VisualQAConfig = field(default_factory=VisualQAConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    night: NightConfig = field(default_factory=NightConfig)

    @property
    def capture_hotkey(self) -> str:
        """The screenshot key, read out of [capture].

        Same shape and same reasons as visual_qa_hotkey below: the section
        owns its keys and its kill switch together, so there is one place
        the value lives.
        """
        return self.capture.hotkey

    @property
    def record_hotkey(self) -> str:
        """The screen-recording key, read out of [capture]."""
        return self.capture.record_hotkey

    @property
    def camera_hotkey(self) -> str:
        """The webcam key, read out of [camera]."""
        return self.camera.hotkey

    @property
    def night_hotkey(self) -> str:
        """The night-mode toggle, read out of [night]."""
        return self.night.hotkey

    @property
    def visual_qa_hotkey(self) -> str:
        """The ask-the-screen key, read out of [visual_qa].

        A property and not a field on purpose: the section is the one
        place the key lives, and a second copy of the value would drift
        the first time one of them was written. Everything that reads keys
        generically (check_hotkeys, status(), the dashboard rows) goes
        through getattr and is served by this; the two places that WRITE
        (main.rebind, dashboard._apply_key) go through with_field() below,
        because dataclasses.replace cannot assign to a property.
        """
        return self.visual_qa.hotkey
    # Fall back to the local backend when every cloud model is out of quota.
    fallback_to_local: bool = True
    # Show a small startup window while the models load. Without it a
    # windowless app is indistinguishable from a shortcut that did nothing
    # for the ~25 s it takes, and the natural response is to click again.
    splash: bool = True
    # A small always-on-top dot in the top-right corner: the app is
    # running, and what it is doing. Click-through, because that corner is
    # the close button of every maximised window.
    indicator: bool = True


# The key fields, in the order the dashboard lists them, with the label it
# shows. Everything that has to enumerate the keys — validation, the
# rebind command, the dashboard rows — reads this instead of repeating the
# list, so adding a key later cannot leave one of them behind.
HOTKEY_FIELDS: tuple[tuple[str, str], ...] = (
    ("hotkey", "Dictate (hold)"),
    ("english_hotkey", "Dictate English (hold)"),
    ("latch_hotkey", "Lock the recording on"),
    ("translate_hotkey", "Translate (tap)"),
    ("punctuate_hotkey", "Punctuate (tap)"),
    ("correct_hotkey", "Teach it a word (tap)"),
    ("lookup_hotkey", "Look up (tap)"),
    ("visual_qa_hotkey", "Ask the screen (tap)"),
    ("capture_hotkey", "Screenshot (tap)"),
    ("record_hotkey", "Record the screen (tap)"),
    ("camera_hotkey", "Photo from the camera (tap)"),
    ("pause_hotkey", "Pause / resume"),
    ("night_hotkey", "Night mode (tap)"),
)


# The keys that may carry modifiers ("ctrl+f6"). Only the taps: they are
# pressed and released in an instant, which is the only thing a chord can
# describe. A chord on the hold hotkey would mean keeping ctrl down for
# the length of a dictation (which changes what a click and the scroll
# wheel do in the browser underneath); the latch is pressed mid-recording
# and swallowed, so a chord there means swallowing two keys; and the pause
# key is the one that has to work when everything else is confusing.
CHORD_FIELDS: frozenset[str] = frozenset((
    "translate_hotkey", "punctuate_hotkey", "correct_hotkey",
    "lookup_hotkey", "visual_qa_hotkey", "capture_hotkey", "record_hotkey",
    "camera_hotkey", "night_hotkey",
))


def with_field(cfg: "Config", name: str, value) -> "Config":
    """A copy of `cfg` with one setting changed, nested ones included.

    The generic rebind paths (main.rebind, dashboard._apply_key) used to
    spell this dataclasses.replace(cfg, **{name: value}), which cannot
    assign to the visual_qa_hotkey property. One helper, both callers,
    and a new nested field later means editing this and nothing else.
    """
    if name == "capture_hotkey":
        return dataclasses.replace(
            cfg, capture=dataclasses.replace(cfg.capture,
                                             hotkey=str(value)))
    if name == "record_hotkey":
        return dataclasses.replace(
            cfg, capture=dataclasses.replace(cfg.capture,
                                             record_hotkey=str(value)))
    if name == "camera_hotkey":
        return dataclasses.replace(
            cfg, camera=dataclasses.replace(cfg.camera, hotkey=str(value)))
    if name == "night_hotkey":
        return dataclasses.replace(
            cfg, night=dataclasses.replace(cfg.night, hotkey=str(value)))
    if name == "visual_qa_hotkey":
        return dataclasses.replace(
            cfg, visual_qa=dataclasses.replace(cfg.visual_qa,
                                               hotkey=str(value)))
    return dataclasses.replace(cfg, **{name: value})


def check_hotkeys(cfg: "Config") -> None:
    """Every key rule in one place: the names are real, and no two mean the
    same thing. Raises ConfigError.

    Split out of load() because it is now needed twice. The dashboard can
    change a key while the app is not running, which means writing
    config.toml with nothing loaded to check it — and a config.toml that
    only fails at the next launch is one that fails windowless, with a
    message box, at the moment the user wanted to dictate.
    """
    # Local imports: keeps config.py importable on its own.
    from hotkey import binding_name, parse_binding

    if not cfg.hotkey:
        raise ConfigError("hotkey must not be empty")
    seen: dict[str, str] = {}
    bindings: dict[str, tuple] = {}     # field -> hotkey.Binding
    for field_name, _label in HOTKEY_FIELDS:
        key = getattr(cfg, field_name)
        if not key:
            continue
        try:
            bound = parse_binding(key)
        except ValueError as e:
            raise ConfigError(f"{field_name}: {e}") from e
        if bound.mods and field_name not in CHORD_FIELDS:
            raise ConfigError(
                f"{field_name} cannot take modifiers ({key!r}) — it is "
                f"held, latched or toggled rather than tapped, and a chord "
                f"means something different for each. Only "
                f"{', '.join(sorted(CHORD_FIELDS))} take chords")
        # Compared canonicalised, not as written: "ctrl+f6" and "f6+ctrl"
        # are one binding, and the duplicate test is the only thing
        # standing between the two spellings and two settings on one key.
        name = binding_name(bound)
        if name in seen:
            raise ConfigError(
                f"{field_name} must differ from {seen[name]} (both are "
                f"{name!r}) — one key cannot mean two things")
        seen[name] = field_name
        bindings[field_name] = bound
    # A tap whose TRIGGER is one of these could never fire, whatever
    # modifiers it asks for: the state machine tests them first (pause in
    # every state, the holds before the taps), so the tap branch is never
    # reached. Refused here rather than at the next launch, where the
    # symptom is a key that does nothing and says nothing.
    for field_name in sorted(CHORD_FIELDS):
        bound = bindings.get(field_name)
        if bound is None:
            continue
        for owner in ("hotkey", "english_hotkey", "pause_hotkey"):
            other = bindings.get(owner)
            if other is not None and other.trigger == bound.trigger:
                raise ConfigError(
                    f"{field_name} is on the same key as {owner} "
                    f"({binding_name(other)!r}), which is checked first — "
                    f"one key cannot mean two things")
    # esc is checked on the TRIGGER, so that "ctrl+esc" cannot slip past
    # (and ctrl+esc opens the Start menu, which is its own reason).
    for field_name in ("latch_hotkey", "pause_hotkey"):
        bound = bindings.get(field_name)
        if bound is not None and bound.trigger == 0x1B:
            raise ConfigError(f"{field_name} cannot be 'esc' — esc discards "
                              f"a locked recording")
    # The tap keys were never checked for this, which mattered the moment
    # one of them opened a window: bound to esc, the lookup key would be
    # excluded from the box's own dismissal rule (a key cannot both open a
    # box and close it) while still discarding a locked recording.
    for field_name in sorted(CHORD_FIELDS):
        bound = bindings.get(field_name)
        if bound is not None and bound.trigger == 0x1B:
            raise ConfigError(f"{field_name} cannot be 'esc' — esc discards "
                              f"a locked recording and closes the lookup box")


def _parse_device(raw: str) -> int | str | None:
    raw = raw.strip()
    if not raw:
        return None
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw  # sounddevice matches name substrings


def load(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Bad TOML in {path}: {e}") from e

    audio = data.get("audio", {})
    gemini = data.get("gemini", {})
    local = data.get("local", {})
    feedback = data.get("feedback", {})
    hint = data.get("hint", {})
    setup = data.get("setup", {})
    translate = data.get("translate", {})
    punctuate = data.get("punctuate", {})
    lookup = data.get("lookup", {})
    server = data.get("server", {})
    vocab = data.get("vocab", {})
    polish = data.get("polish", {})
    visual_qa = data.get("visual_qa", {})
    study = data.get("study", {})
    review = data.get("review", {})
    capture = data.get("capture", {})
    camera = data.get("camera", {})
    night = data.get("night", {})

    # models = [...] is the current form; model = "..." is still honoured so
    # an older config.toml keeps working.
    if gemini.get("models"):
        models = tuple(str(m).strip() for m in gemini["models"]
                       if str(m).strip())
    elif gemini.get("model"):
        models = (str(gemini["model"]).strip(),)
    else:
        models = GeminiConfig.models

    cfg = Config(
        hotkey=str(data.get("hotkey", Config.hotkey)).strip().lower(),
        english_hotkey=str(data.get("english_hotkey",
                                    Config.english_hotkey)).strip().lower(),
        translate_hotkey=str(data.get(
            "translate_hotkey", Config.translate_hotkey)).strip().lower(),
        punctuate_hotkey=str(data.get(
            "punctuate_hotkey", Config.punctuate_hotkey)).strip().lower(),
        latch_hotkey=str(data.get("latch_hotkey",
                                  Config.latch_hotkey)).strip().lower(),
        correct_hotkey=str(data.get("correct_hotkey",
                                    Config.correct_hotkey)).strip().lower(),
        lookup_hotkey=str(data.get("lookup_hotkey",
                                   Config.lookup_hotkey)).strip().lower(),
        pause_hotkey=str(data.get("pause_hotkey",
                                  Config.pause_hotkey)).strip().lower(),
        auto_language=bool(data.get("auto_language", Config.auto_language)),
        auto_pause_fullscreen=bool(data.get(
            "auto_pause_fullscreen", Config.auto_pause_fullscreen)),
        backend=str(data.get("backend", Config.backend)).strip().lower(),
        paste_chord=str(data.get("paste_chord", Config.paste_chord)).strip().lower(),
        restore_delay_ms=int(data.get("restore_delay_ms", Config.restore_delay_ms)),
        min_seconds=float(data.get("min_seconds", Config.min_seconds)),
        max_seconds=float(data.get("max_seconds", Config.max_seconds)),
        latch_max_seconds=float(data.get("latch_max_seconds",
                                         Config.latch_max_seconds)),
        audio=AudioConfig(
            sample_rate=int(audio.get("sample_rate", AudioConfig.sample_rate)),
            device=_parse_device(str(audio.get("device", ""))),
        ),
        gemini=GeminiConfig(
            models=models,
            timeout_s=int(gemini.get("timeout_s", GeminiConfig.timeout_s)),
        ),
        local=LocalConfig(
            model=str(local.get("model", LocalConfig.model)).strip(),
            language=str(local.get("language", LocalConfig.language)).strip(),
            device=str(local.get("device", LocalConfig.device)).strip().lower(),
            cleanup=bool(local.get("cleanup", LocalConfig.cleanup)),
            extra_fillers=tuple(str(f).strip()
                                for f in local.get("extra_fillers", ())
                                if str(f).strip()),
            initial_prompt=str(local.get("initial_prompt",
                                         LocalConfig.initial_prompt)),
            english_model=str(local.get("english_model",
                                        LocalConfig.english_model)).strip(),
            english_threshold=float(local.get(
                "english_threshold", LocalConfig.english_threshold)),
            guard_hallucinations=bool(local.get(
                "guard_hallucinations", LocalConfig.guard_hallucinations)),
            beam_size=int(local.get("beam_size", LocalConfig.beam_size)),
            drop_trailing_boilerplate=bool(local.get(
                "drop_trailing_boilerplate",
                LocalConfig.drop_trailing_boilerplate)),
            extra_boilerplate=tuple(str(p).strip()
                                    for p in local.get("extra_boilerplate", ())
                                    if str(p).strip()),
        ),
        feedback=FeedbackConfig(
            placeholder=str(feedback.get("placeholder",
                                         FeedbackConfig.placeholder)),
            enabled=bool(feedback.get("enabled", FeedbackConfig.enabled)),
            retry_seconds=float(feedback.get(
                "retry_seconds", FeedbackConfig.retry_seconds)),
        ),
        hint=HintConfig(
            enabled=bool(hint.get("enabled", HintConfig.enabled)),
            after_ms=int(hint.get("after_ms", HintConfig.after_ms)),
            corner=str(hint.get("corner", HintConfig.corner)).strip().lower(),
            x=int(hint.get("x", HintConfig.x)),
            y=int(hint.get("y", HintConfig.y)),
            scale=float(hint.get("scale", HintConfig.scale)),
        ),
        setup=SetupConfig(
            done=bool(setup.get("done", SetupConfig.done)),
        ),
        translate=TranslateConfig(
            target=str(translate.get("target",
                                     TranslateConfig.target)).strip(),
            max_chars=int(translate.get("max_chars",
                                        TranslateConfig.max_chars)),
            ollama_model=str(translate.get(
                "ollama_model", TranslateConfig.ollama_model)).strip(),
            ollama_url=str(translate.get(
                "ollama_url", TranslateConfig.ollama_url)).strip(),
            timeout_s=int(translate.get("timeout_s",
                                        TranslateConfig.timeout_s)),
            ollama_timeout_s=int(translate.get(
                "ollama_timeout_s", TranslateConfig.ollama_timeout_s)),
            copy_chord=str(translate.get(
                "copy_chord", TranslateConfig.copy_chord)).strip().lower(),
            select_all_chord=str(translate.get(
                "select_all_chord",
                TranslateConfig.select_all_chord)).strip().lower(),
            settle_ms=int(translate.get("settle_ms",
                                        TranslateConfig.settle_ms)),
        ),
        punctuate=PunctuateConfig(
            max_chars=int(punctuate.get("max_chars",
                                        PunctuateConfig.max_chars)),
            prefer=str(punctuate.get(
                "prefer", PunctuateConfig.prefer)).strip().lower(),
            groq_model=str(punctuate.get(
                "groq_model", PunctuateConfig.groq_model)).strip(),
            ollama_model=str(punctuate.get(
                "ollama_model", PunctuateConfig.ollama_model)).strip(),
            auto=bool(punctuate.get("auto", PunctuateConfig.auto)),
            max_wait_s=float(punctuate.get("max_wait_s",
                                           PunctuateConfig.max_wait_s)),
            nikud=bool(punctuate.get("nikud", PunctuateConfig.nikud)),
        ),
        lookup=LookupConfig(
            hebrew_share=float(lookup.get("hebrew_share",
                                          LookupConfig.hebrew_share)),
            both_ways=bool(lookup.get("both_ways",
                                      LookupConfig.both_ways)),
            max_chars=int(lookup.get("max_chars", LookupConfig.max_chars)),
            prefer=str(lookup.get(
                "prefer", LookupConfig.prefer)).strip().lower(),
            model=str(lookup.get("model", LookupConfig.model)).strip(),
            cold_to_gemini=bool(lookup.get("cold_to_gemini",
                                           LookupConfig.cold_to_gemini)),
            keep_alive=str(lookup.get("keep_alive",
                                      LookupConfig.keep_alive)).strip(),
            strip_niqqud=bool(lookup.get("strip_niqqud",
                                         LookupConfig.strip_niqqud)),
            dwell_ms=int(lookup.get("dwell_ms", LookupConfig.dwell_ms)),
            max_width=int(lookup.get("max_width", LookupConfig.max_width)),
            max_height=int(lookup.get("max_height",
                                      LookupConfig.max_height)),
            cache_entries=int(lookup.get("cache_entries",
                                         LookupConfig.cache_entries)),
            skip_consoles=bool(lookup.get("skip_consoles",
                                          LookupConfig.skip_consoles)),
        ),
        study=StudyConfig(
            enabled=bool(study.get("enabled", StudyConfig.enabled)),
            idle_minutes=float(study.get("idle_minutes",
                                         StudyConfig.idle_minutes)),
            max_clip_seconds=float(study.get("max_clip_seconds",
                                             StudyConfig.max_clip_seconds)),
            llm_per_day=int(study.get("llm_per_day",
                                      StudyConfig.llm_per_day)),
            corpus_keep=int(study.get("corpus_keep",
                                      StudyConfig.corpus_keep)),
        ),
        review=ReviewConfig(
            enabled=bool(review.get("enabled", ReviewConfig.enabled)),
            card_seconds=float(review.get("card_seconds",
                                          ReviewConfig.card_seconds)),
            corner=str(review.get("corner",
                                  ReviewConfig.corner)).strip().lower(),
            x=int(review.get("x", ReviewConfig.x)),
            y=int(review.get("y", ReviewConfig.y)),
            scale=float(review.get("scale", ReviewConfig.scale)),
            max_changes=int(review.get("max_changes",
                                       ReviewConfig.max_changes)),
            witness=int(review.get("witness", ReviewConfig.witness)),
            local_model=bool(review.get("local_model",
                                        ReviewConfig.local_model)),
            accept_key=str(review.get(
                "accept_key", ReviewConfig.accept_key)).strip().lower(),
            reject_key=str(review.get(
                "reject_key", ReviewConfig.reject_key)).strip().lower(),
            later_key=str(review.get(
                "later_key", ReviewConfig.later_key)).strip().lower(),
            edit_key=str(review.get(
                "edit_key", ReviewConfig.edit_key)).strip().lower(),
            fix_in_field=bool(review.get("fix_in_field",
                                         ReviewConfig.fix_in_field)),
            max_clip_seconds=float(review.get(
                "max_clip_seconds", ReviewConfig.max_clip_seconds)),
            llm_per_day=int(review.get("llm_per_day",
                                       ReviewConfig.llm_per_day)),
        ),
        server=ServerConfig(
            enabled=bool(server.get("enabled", ServerConfig.enabled)),
            host=str(server.get("host", ServerConfig.host)).strip(),
            port=int(server.get("port", ServerConfig.port)),
        ),
        vocab=VocabConfig(
            enabled=bool(vocab.get("enabled", VocabConfig.enabled)),
            terms=tuple(str(t).strip() for t in vocab.get("terms", ())
                        if str(t).strip()),
            max_terms=int(vocab.get("max_terms", VocabConfig.max_terms)),
            replace_after_hits=int(vocab.get(
                "replace_after_hits", VocabConfig.replace_after_hits)),
            hebrew_after_hits=int(vocab.get(
                "hebrew_after_hits", VocabConfig.hebrew_after_hits)),
            keep_audio=int(vocab.get("keep_audio", VocabConfig.keep_audio)),
        ),
        polish=PolishConfig(
            when=str(polish.get("when", PolishConfig.when)).strip().lower(),
            min_chars=int(polish.get("min_chars", PolishConfig.min_chars)),
            ollama_model=str(polish.get(
                "ollama_model", PolishConfig.ollama_model)).strip(),
            prefer=str(polish.get(
                "prefer", PolishConfig.prefer)).strip().lower(),
            groq_model=str(polish.get(
                "groq_model", PolishConfig.groq_model)).strip(),
            groq_timeout_s=int(polish.get(
                "groq_timeout_s", PolishConfig.groq_timeout_s)),
            cerebras_model=str(polish.get(
                "cerebras_model", PolishConfig.cerebras_model)).strip(),
            cerebras_timeout_s=int(polish.get(
                "cerebras_timeout_s", PolishConfig.cerebras_timeout_s)),
            max_wait_s=float(polish.get("max_wait_s",
                                        PolishConfig.max_wait_s)),
            warm_up=bool(polish.get("warm_up", PolishConfig.warm_up)),
        ),
        visual_qa=VisualQAConfig(
            enabled=bool(visual_qa.get("enabled",
                                       VisualQAConfig.enabled)),
            allow_screenshot_upload=bool(visual_qa.get(
                "allow_screenshot_upload",
                VisualQAConfig.allow_screenshot_upload)),
            hotkey=str(visual_qa.get(
                "visual_qa_hotkey",
                VisualQAConfig.hotkey)).strip().lower(),
            prefer=str(visual_qa.get(
                "prefer", VisualQAConfig.prefer)).strip().lower(),
            ollama_model=str(visual_qa.get(
                "ollama_model", VisualQAConfig.ollama_model)).strip(),
            groq_model=str(visual_qa.get(
                "groq_model", VisualQAConfig.groq_model)).strip(),
            gemini_fallback=bool(visual_qa.get(
                "gemini_fallback", VisualQAConfig.gemini_fallback)),
            max_side_px=int(visual_qa.get(
                "max_side_px", VisualQAConfig.max_side_px)),
            num_predict=int(visual_qa.get(
                "num_predict", VisualQAConfig.num_predict)),
            speak=str(visual_qa.get("speak",
                                    VisualQAConfig.speak)).strip().lower(),
            voice=str(visual_qa.get("voice",
                                    VisualQAConfig.voice)).strip(),
            auto_send=bool(visual_qa.get("auto_send",
                                         VisualQAConfig.auto_send)),
            echo_to_field=bool(visual_qa.get(
                "echo_to_field", VisualQAConfig.echo_to_field)),
            window_alpha=float(visual_qa.get(
                "window_alpha", VisualQAConfig.window_alpha)),
            warmup=bool(visual_qa.get("warmup",
                                      VisualQAConfig.warmup)),
            ollama_timeout_s=int(visual_qa.get(
                "ollama_timeout_s", VisualQAConfig.ollama_timeout_s)),
            cloud_timeout_s=int(visual_qa.get(
                "cloud_timeout_s", VisualQAConfig.cloud_timeout_s)),
        ),
        capture=CaptureConfig(
            enabled=bool(capture.get("enabled", CaptureConfig.enabled)),
            hotkey=str(capture.get(
                "capture_hotkey", CaptureConfig.hotkey)).strip().lower(),
            record_hotkey=str(capture.get(
                "record_hotkey",
                CaptureConfig.record_hotkey)).strip().lower(),
            folder=str(capture.get("folder", CaptureConfig.folder)).strip(),
            copy_to_clipboard=bool(capture.get(
                "copy_to_clipboard", CaptureConfig.copy_to_clipboard)),
            after_shot=str(capture.get(
                "after_shot", CaptureConfig.after_shot)).strip().lower(),
            toast_corner=str(capture.get(
                "toast_corner",
                CaptureConfig.toast_corner)).strip().lower(),
            toast_seconds=int(capture.get(
                "toast_seconds", CaptureConfig.toast_seconds)),
            always_save=bool(capture.get(
                "always_save", CaptureConfig.always_save)),
            copy_clip_path=bool(capture.get(
                "copy_clip_path", CaptureConfig.copy_clip_path)),
            fps=int(capture.get("fps", CaptureConfig.fps)),
            quality=str(capture.get(
                "quality", CaptureConfig.quality)).strip().lower(),
            cursor=bool(capture.get("cursor", CaptureConfig.cursor)),
            audio=str(capture.get(
                "audio", CaptureConfig.audio)).strip().lower(),
            max_minutes=int(capture.get("max_minutes",
                                        CaptureConfig.max_minutes)),
            timer_corner=str(capture.get(
                "timer_corner",
                CaptureConfig.timer_corner)).strip().lower(),
            announce=bool(capture.get("announce", CaptureConfig.announce)),
        ),
        camera=CameraConfig(
            enabled=bool(camera.get("enabled", CameraConfig.enabled)),
            hotkey=str(camera.get(
                "camera_hotkey", CameraConfig.hotkey)).strip().lower(),
            device=str(camera.get("device", CameraConfig.device)).strip(),
            size=str(camera.get("size", CameraConfig.size)).strip().lower(),
            fps=int(camera.get("fps", CameraConfig.fps)),
            mirror=bool(camera.get("mirror", CameraConfig.mirror)),
            timer=int(camera.get("timer", CameraConfig.timer)),
            folder=str(camera.get("folder", CameraConfig.folder)).strip(),
            copy_to_clipboard=bool(camera.get(
                "copy_to_clipboard", CameraConfig.copy_to_clipboard)),
            edit_after_shot=bool(camera.get(
                "edit_after_shot", CameraConfig.edit_after_shot)),
        ),
        night=NightConfig(
            enabled=bool(night.get("enabled", NightConfig.enabled)),
            hotkey=str(night.get(
                "night_hotkey", NightConfig.hotkey)).strip().lower(),
            pin_timeouts=bool(night.get("pin_timeouts",
                                        NightConfig.pin_timeouts)),
            screen_off_again_s=int(night.get(
                "screen_off_again_s", NightConfig.screen_off_again_s)),
        ),
        fallback_to_local=bool(data.get("fallback_to_local",
                                        Config.fallback_to_local)),
        splash=bool(data.get("splash", Config.splash)),
        indicator=bool(data.get("indicator", Config.indicator)),
    )

    if cfg.backend not in VALID_BACKENDS:
        raise ConfigError(f"backend must be one of {VALID_BACKENDS}, got {cfg.backend!r}")
    check_hotkeys(cfg)
    if not 0 <= cfg.night.screen_off_again_s <= 60:
        raise ConfigError("night.screen_off_again_s must be 0-60 "
                          "seconds")
    if cfg.translate_hotkey:
        if cfg.translate.max_chars <= 0:
            raise ConfigError("translate.max_chars must be positive")
        if not cfg.translate.target:
            raise ConfigError("translate.target must name a language")
    if ((cfg.punctuate_hotkey or cfg.punctuate.auto)
            and cfg.punctuate.max_chars <= 0):
        raise ConfigError("punctuate.max_chars must be positive")
    if cfg.punctuate.prefer not in ("groq", "gemini", "ollama"):
        raise ConfigError('punctuate.prefer must be "groq", "gemini" or '
                          f'"ollama", got {cfg.punctuate.prefer!r}')
    if cfg.punctuate.max_wait_s <= 0:
        raise ConfigError("punctuate.max_wait_s must be positive — it is "
                          "how long a dictation waits for its punctuation")
    # All three text keys read the grab mechanics out of [translate] — the
    # chords and the settle time belong to the machine, not to the job —
    # so this is checked whenever ANY of them is bound.
    if cfg.translate_hotkey or cfg.punctuate_hotkey or cfg.lookup_hotkey:
        if cfg.translate.settle_ms < 0:
            raise ConfigError("translate.settle_ms must be >= 0")
    # The Ollama fallback is shared by only two of them: the lookup key
    # brings its own model (see below), because it is Ollama-FIRST rather
    # than Ollama-when-the-quota-is-gone.
    if cfg.translate_hotkey or cfg.punctuate_hotkey:
        if not cfg.translate.ollama_model:
            raise ConfigError("translate.ollama_model must not be empty (it "
                              "is the fallback when Gemini quota is spent, "
                              "for translating and for punctuating)")
    # The lookup key reads [translate] as well — the copy chord and the
    # Ollama endpoint — but not settle_ms (it polls the clipboard sequence
    # number instead of sleeping through a fixed wait) and not
    # ollama_model, because looking a word up wants the model [polish]
    # already keeps resident rather than the fallback. What it cannot do
    # without is a model in one of the two places.
    if cfg.lookup_hotkey:
        if cfg.lookup.max_chars <= 0:
            raise ConfigError("lookup.max_chars must be positive")
        if not (cfg.lookup.model or cfg.translate.ollama_model):
            raise ConfigError("lookup.model must name an Ollama model (or "
                              "translate.ollama_model must, which lookup "
                              "falls back to) — the lookup key has nothing "
                              "to ask otherwise")
    if cfg.lookup.prefer not in ("ollama", "gemini"):
        raise ConfigError('lookup.prefer must be "ollama" or "gemini", got '
                          f"{cfg.lookup.prefer!r}")
    if not (0.0 <= cfg.lookup.hebrew_share <= 1.0):
        raise ConfigError("lookup.hebrew_share must be between 0 and 1 — it "
                          "is the share of HEBREW WORDS at or above which a "
                          "selection is translated into English, got "
                          f"{cfg.lookup.hebrew_share!r}")
    if cfg.lookup.dwell_ms < 0:
        raise ConfigError("lookup.dwell_ms must be >= 0 (and nothing reads "
                          "it any more: the box waits for its close button "
                          "or for Esc)")
    if cfg.lookup.max_width < 160 or cfg.lookup.max_height < 64:
        raise ConfigError("lookup.max_width must be >= 160 and "
                          "lookup.max_height >= 64 — a box smaller than that "
                          "cannot hold one word even at the smallest face, "
                          "and every answer would come back as an ellipsis")
    if cfg.lookup.cache_entries < 0:
        raise ConfigError("lookup.cache_entries must be >= 0 (0 remembers "
                          "nothing between presses)")
    if cfg.lookup.keep_alive and not _DURATION.fullmatch(
            cfg.lookup.keep_alive):
        # Checked here because Ollama rejects a malformed one with an HTTP
        # 400 and this key SURVIVES that: it would quietly fall through to
        # Gemini on every press and spend the pool it exists to protect.
        # Loud at startup beats slow and cloudy forever.
        raise ConfigError(
            'lookup.keep_alive must be a duration like "30m", "8h" or '
            '"90s" (a plain number is seconds, "-1" holds the model until '
            'Ollama stops, "" leaves it to Ollama), got '
            f"{cfg.lookup.keep_alive!r}")
    if cfg.polish.when not in ("never", "known", "always"):
        raise ConfigError('polish.when must be "never", "known" or "always", '
                          f"got {cfg.polish.when!r}")
    if cfg.polish.prefer not in ("groq", "cerebras", "ollama"):
        raise ConfigError('polish.prefer must be "groq", "cerebras" or '
                          f'"ollama", got {cfg.polish.prefer!r}')
    if cfg.polish.groq_timeout_s <= 0:
        raise ConfigError("polish.groq_timeout_s must be positive")
    if not cfg.polish.groq_model and cfg.polish.prefer == "groq":
        raise ConfigError(
            "polish.groq_model must not be empty while "
            'polish.prefer = "groq" (name a model, or set prefer to '
            '"ollama" to stay local instead)')
    if cfg.polish.cerebras_timeout_s <= 0:
        raise ConfigError("polish.cerebras_timeout_s must be positive")
    if not cfg.polish.cerebras_model and cfg.polish.prefer == "cerebras":
        raise ConfigError(
            "polish.cerebras_model must not be empty while "
            'polish.prefer = "cerebras" (name a model, or set prefer to '
            '"ollama" to stay local instead)')
    if cfg.local.beam_size < 1:
        raise ConfigError("local.beam_size must be >= 1 (1 is greedy; this "
                          "app shipped at 5)")
    if cfg.polish.min_chars < 0:
        raise ConfigError("polish.min_chars must be >= 0")
    if cfg.polish.max_wait_s <= 0:
        raise ConfigError(
            "polish.max_wait_s must be > 0 — it is the longest the paste may "
            'be delayed by the context pass. Use polish.when = "never" to '
            "turn the pass off instead")
    if cfg.visual_qa.prefer not in ("ollama", "groq", "gemini"):
        raise ConfigError('visual_qa.prefer must be "ollama", "groq" or '
                          f'"gemini", got {cfg.visual_qa.prefer!r}')
    if cfg.visual_qa.speak not in ("off", "button", "auto"):
        raise ConfigError('visual_qa.speak must be "off", "button" or '
                          f'"auto", got {cfg.visual_qa.speak!r}')
    if not 128 <= cfg.visual_qa.max_side_px <= 4096:
        raise ConfigError("visual_qa.max_side_px must be between 128 and "
                          "4096 — below 128 a screenshot stops carrying "
                          "readable text, above 4096 it is a raw screen")
    if cfg.visual_qa.num_predict < 64:
        raise ConfigError("visual_qa.num_predict must be >= 64 — answers "
                          "shorter than that are cut mid-sentence, and the "
                          "cap exists to bound a rambling model, not the "
                          "honest ones")
    if cfg.visual_qa.ollama_timeout_s <= 0 \
            or cfg.visual_qa.cloud_timeout_s <= 0:
        raise ConfigError("visual_qa timeouts must be positive")
    if not 0.30 <= cfg.visual_qa.window_alpha <= 1.0:
        raise ConfigError("visual_qa.window_alpha must be between 0.30 and "
                          "1.0 — under a third the answer stops being "
                          "readable against whatever is behind it")
    if cfg.capture.quality not in ("small", "balanced", "sharp"):
        raise ConfigError('capture.quality must be "small", "balanced" or '
                          f'"sharp", got {cfg.capture.quality!r}')
    if cfg.capture.audio not in ("off", "mic"):
        raise ConfigError('capture.audio must be "off" or "mic", got '
                          f"{cfg.capture.audio!r} — a screen recording only "
                          "opens the microphone when you say so")
    if not 5 <= cfg.capture.fps <= 60:
        raise ConfigError("capture.fps must be between 5 and 60 — under 5 a "
                          "recording is a slideshow, and over 60 the GRAB "
                          "cannot keep up on this machine anyway (measured "
                          "32 ms a frame at 1440p, which is 31 fps of "
                          "ceiling)")
    if cfg.capture.max_minutes < 0:
        raise ConfigError("capture.max_minutes must be >= 0 (0 = no cap)")
    if cfg.capture.timer_corner not in ("top-left", "top-right",
                                        "bottom-left", "bottom-right",
                                        "off"):
        raise ConfigError('capture.timer_corner must be "top-left", '
                          '"top-right", "bottom-left", "bottom-right" or '
                          f'"off", got {cfg.capture.timer_corner!r}')
    if not cfg.capture.folder:
        raise ConfigError("capture.folder cannot be empty — that is where "
                          "your screenshots go")
    if cfg.capture.after_shot not in ("toast", "editor", "nothing"):
        raise ConfigError('capture.after_shot must be "toast", "editor" or '
                          f'"nothing", got {cfg.capture.after_shot!r}')
    if cfg.capture.toast_corner not in ("top-left", "top-right",
                                        "bottom-left", "bottom-right"):
        raise ConfigError('capture.toast_corner must be a corner — '
                          '"top-left", "top-right", "bottom-left" or '
                          f'"bottom-right", got {cfg.capture.toast_corner!r}'
                          '. Use after_shot = "nothing" for no card at all')
    if not 1 <= cfg.capture.toast_seconds <= 60:
        raise ConfigError("capture.toast_seconds must be between 1 and 60 — "
                          "under a second nobody can reach it, and past a "
                          "minute it is not a notification any more")
    if cfg.camera.timer not in (0, 3, 10):
        raise ConfigError("camera.timer must be 0, 3 or 10 seconds, got "
                          f"{cfg.camera.timer} — the key cycles through "
                          "those three and starts on this one")
    if not 1 <= cfg.camera.fps <= 60:
        raise ConfigError("camera.fps must be between 1 and 60 — it is what "
                          "the camera is ASKED for, and a webcam that "
                          "cannot manage it simply sends fewer")
    if not cfg.camera.folder:
        raise ConfigError("camera.folder cannot be empty — that is where "
                          "your photos go")
    if "x" not in cfg.camera.size or not all(
            part.strip().isdigit() for part in cfg.camera.size.split("x", 1)):
        raise ConfigError('camera.size must look like "1280x720", got '
                          f"{cfg.camera.size!r}")
    if cfg.vocab.max_terms < 0:
        raise ConfigError("vocab.max_terms must be >= 0 (0 disables hotwords)")
    if cfg.vocab.keep_audio < 0:
        raise ConfigError("vocab.keep_audio must be >= 0 (0 keeps none)")
    if cfg.vocab.replace_after_hits < 1:
        raise ConfigError(
            "vocab.replace_after_hits must be >= 1 — a garble is only "
            "repaired after it has been corrected that many times, and 0 "
            "would mean repairing one it has never been corrected for")
    if not (0 < cfg.min_seconds < cfg.max_seconds <= 3600):
        raise ConfigError("need 0 < min_seconds < max_seconds <= 3600")
    if cfg.latch_max_seconds < 0:
        raise ConfigError("latch_max_seconds must be >= 0 (0 = no cap)")
    if 0 < cfg.latch_max_seconds <= cfg.min_seconds:
        raise ConfigError("latch_max_seconds must be 0 (no cap) or longer "
                          "than min_seconds")
    if cfg.restore_delay_ms < 0:
        raise ConfigError("restore_delay_ms must be >= 0")
    if cfg.server.enabled and not (0 < cfg.server.port < 65536):
        raise ConfigError(f"server.port is out of range: {cfg.server.port}")
    if cfg.audio.sample_rate <= 0:
        raise ConfigError("audio.sample_rate must be positive")
    if not cfg.gemini.models:
        raise ConfigError("gemini.models must list at least one model")
    if cfg.feedback.enabled and not cfg.feedback.placeholder:
        raise ConfigError("feedback.placeholder must not be empty when "
                          "feedback.enabled is true (nothing to erase)")
    if cfg.feedback.retry_seconds < 0:
        raise ConfigError("feedback.retry_seconds must be >= 0")
    if cfg.hint.after_ms < 0:
        raise ConfigError("hint.after_ms must be >= 0")
    if cfg.hint.corner not in HINT_CORNERS:
        raise ConfigError(f"hint.corner must be one of {HINT_CORNERS}, "
                          f"got {cfg.hint.corner!r}")
    if not (HINT_SCALE_MIN <= cfg.hint.scale <= HINT_SCALE_MAX):
        raise ConfigError(
            f"hint.scale must be between {HINT_SCALE_MIN} and "
            f"{HINT_SCALE_MAX}, got {cfg.hint.scale!r}")
    if cfg.review.corner not in REVIEW_CORNERS:
        raise ConfigError(f"review.corner must be one of {REVIEW_CORNERS}, "
                          f"got {cfg.review.corner!r}")
    if not (HINT_SCALE_MIN <= cfg.review.scale <= HINT_SCALE_MAX):
        raise ConfigError(
            f"review.scale must be between {HINT_SCALE_MIN} and "
            f"{HINT_SCALE_MAX}, got {cfg.review.scale!r}")
    if cfg.review.card_seconds < 0:
        raise ConfigError("review.card_seconds must be >= 0")
    if cfg.review.max_changes < 1:
        raise ConfigError("review.max_changes must be >= 1")
    if not (0 <= cfg.review.witness <= 3):
        raise ConfigError("review.witness must be between 0 and 3 (there "
                          "are three extra decodes)")
    for name in ("accept_key", "reject_key", "later_key", "edit_key"):
        if not getattr(cfg.review, name):
            raise ConfigError(f"review.{name} must name a key")
    if cfg.local.device not in ("auto", "cuda", "cpu"):
        raise ConfigError('local.device must be "auto", "cuda" or "cpu", '
                          f"got {cfg.local.device!r}")
    if not cfg.local.language:
        raise ConfigError("local.language must be pinned (the ivrit-ai "
                          "fine-tune's language autodetect is unreliable)")
    if not (0.0 < cfg.local.english_threshold <= 1.0):
        raise ConfigError("local.english_threshold must be in (0, 1]")
    return cfg


# ------------------------------------------------------- writing it back

_ASSIGNMENT = r"^(\s*)({key})(\s*)=(\s*)(.*)$"


def _format(value: object) -> str:
    if isinstance(value, bool):          # before int: bool IS an int
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _comment_at(rest: str) -> int | None:
    """Index of the '#' that starts a trailing comment, ignoring any '#'
    inside a quoted value. None if the line has no comment."""
    quote = ""
    i = 0
    while i < len(rest):
        char = rest[i]
        if quote:
            if char == "\\" and quote == '"':
                i += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#":
            return i
        i += 1
    return None


def _section_span(lines: list[str], section: str) -> tuple[int, int]:
    """(start, end) line indexes of the assignments inside [section].

    start is the line AFTER the header, end the line BEFORE the next
    header (or EOF). A missing section is a ConfigError: silently editing
    nothing would report success while changing no file.
    """
    header = f"[{section}]"
    for index, line in enumerate(lines):
        if line.strip() != header:
            continue
        lo = index + 1
        hi = len(lines)
        for probe in range(lo, len(lines)):
            stripped = lines[probe].lstrip()
            if stripped.startswith("["):
                hi = probe
                break
        return lo, hi
    raise ConfigError(f"no [{section}] section in config.toml")


def set_values(path: Path, updates: dict[str, object]) -> None:
    """Change settings in place, keeping every comment.

    Top-level keys are matched in the top-level block only. A dotted name
    ("visual_qa.hotkey") is matched inside the [section] it names — the
    same comment-preserving line edit, scoped to that one table, so a key
    name that repeats across sections (`enabled`, `model`, `hotkey`) can
    never be rewritten by accident.

    The result is parsed and fully validated BEFORE it replaces the real
    file, and swapped in with one atomic rename. A config.toml this app
    cannot read is a config.toml that turns the next launch into a message
    box, and it must not be possible to get there by clicking a key in a
    dashboard.
    """
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    raw = path.read_text("utf-8")
    lines = raw.splitlines(keepends=True)
    eol = "\r\n" if raw.count("\r\n") else "\n"

    limit = len(lines)
    for index, line in enumerate(lines):
        if line.lstrip().startswith("["):
            limit = index
            break

    for key, value in updates.items():
        formatted = _format(value)
        section = None
        bare = key
        if "." in key:
            section, _, bare = key.partition(".")
        if section is None:
            lo, hi = 0, limit
        else:
            lo, hi = _section_span(lines, section)
        pattern = re.compile(_ASSIGNMENT.format(key=re.escape(bare)))
        for index in range(lo, hi):
            body = lines[index].rstrip("\r\n")
            match = pattern.match(body)
            if not match:
                continue
            indent, name, before, after, rest = match.groups()
            at = _comment_at(rest)
            if at is None:
                pad, comment = "", ""
            else:
                code, comment = rest[:at], rest[at:]
                # Keep the gap that lined the comment up, but never let the
                # value and the '#' end up welded together.
                pad = code[len(code.rstrip()):] or " "
            tail = lines[index][len(body):]
            lines[index] = (f"{indent}{name}{before}={after}"
                            f"{formatted}{pad}{comment}{tail}")
            break
        else:
            if section is not None:
                raise ConfigError(
                    f"no {bare!r} under [{section}] to write — the "
                    "line editor only changes keys that are already there")
            # Not there at all (an older config.toml). Put it with the
            # other top-level settings, not after them: below the last
            # assignment is still above whatever comment block introduces
            # the first [table].
            last = 0
            for index in range(limit):
                if re.match(r"^\s*[A-Za-z_][\w-]*\s*=", lines[index]):
                    last = index + 1
            lines.insert(last, f"{key} = {formatted}{eol}")
            limit += 1

    text = "".join(lines)
    # Per-process staging name. With one shared "config.toml.new", two
    # writers DESTROY the file: the cleanup path below deletes the temp by
    # name, and DeleteFileW marks it delete-on-close — so if the other
    # process is renaming that same file onto config.toml at that moment,
    # the pending delete follows it through the rename and takes the real
    # config with it. Reproduced 4 runs out of 4; afterwards nothing loads
    # and the app will not start. Two writers is not exotic: every launch
    # while an instance is running opens another dashboard, and each one
    # writes this file.
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.new")
    tmp.write_text(text, "utf-8")
    try:
        load(tmp)
    except ConfigError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise ConfigError(f"the edited config would not load: {e}") from e
    os.replace(tmp, path)
