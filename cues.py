"""Audible cues.

winsound.Beep goes through the legacy console-beep path, which on this
machine executes without error and produces nothing audible. PlaySound
with a real WAV goes through the normal audio mixer to the default output
device instead — the same path Spotify or a browser uses, so it is
audible, respects the volume mixer, and can be routed per-app in Windows
settings.

winsound cannot play asynchronously from memory ("Cannot play
asynchronously from memory"), so the cues are generated once as small WAV
files next to the app and then played by filename with SND_ASYNC — which
returns immediately and never delays the recording.
"""
from __future__ import annotations

import array
import hashlib
import math
import wave
from pathlib import Path

import paths

CUE_DIR = paths.CUES_DIR
SAMPLE_RATE = 44100
VOLUME = 0.5

# PITCH IS THE SECOND AXIS NOW, NOT THE FIRST. Measured 2026-09-05 on the
# table below: of the 13 two-note cues, NINE were the same gesture — a
# perfect fifth — and three more a fourth, so twelve of thirteen differed
# only in absolute pitch. Two of the six single notes sat inside a
# semitone of their neighbour (noop 494 / punctuating 523 = 0.99
# semitones; looking 622 / stop 660 = 1.03). Naming an interval you cannot
# hear in isolation is not naming anything, and the owner's report was
# exactly that: "it's very hard for me to know what the sound referred
# to".
#
# So the family a cue belongs to is carried by its CHARACTER — how the
# sound is made — and the pitches below are left alone deliberately, as a
# secondary hint for cues you already know apart. See CHARACTERS.
#
# kind -> [(frequency Hz, milliseconds), ...]
CUES: dict[str, list[tuple[int, int]]] = {
    "ready": [(587, 90), (880, 130)],    # app is listening
    "start": [(880, 110)],               # recording
    "stop": [(660, 110)],                # captured, transcribing
    "error": [(330, 130), (262, 190)],   # something failed
    # Locked on — you can let go. Deliberately the "start" note plus one
    # above it: the recording did not restart, it grew a lock.
    "latch": [(880, 70), (1319, 110)],
    "bye": [(880, 90), (587, 130)],      # app stopped
    # Translation is silent work on text already on screen, so it gets its
    # own pair — otherwise a press is indistinguishable from a recording.
    "translating": [(740, 90)],          # grabbed the text, asking the model
    "translated": [(740, 80), (988, 120)],  # replaced in place
    # Punctuation is the same shape of work on the same text, so it gets the
    # same shape of cue a fourth lower: a press that went to the wrong one of
    # the two keys should be obvious by ear, without being a new language.
    "punctuating": [(523, 90)],
    "punctuated": [(523, 80), (784, 120)],
    # Looking a word up is the same shape of work again — grab the text,
    # ask the model, come back — so it gets the same shape of cue a third
    # time, on a note BETWEEN the other two (523 · 622 · 740). Three keys
    # that feel identical under the finger need to be three sounds you can
    # tell apart without thinking, and the ear places a pitch inside a pair
    # it already knows far more reliably than it identifies one in
    # isolation. The rise is a fourth, like "translated": nothing was
    # changed on screen, so the second note says "here it is", not "done".
    "looking": [(622, 90)],
    "looked": [(622, 80), (831, 120)],
    # Pause is usually pressed with a game on screen and the dot hidden
    # behind it, so the cue is the whole confirmation. Two notes, falling
    # to stop and rising to start, so which one happened is obvious
    # without looking — the key is a toggle and both presses feel the same
    # under the finger.
    "paused": [(660, 90), (440, 140)],
    "resumed": [(440, 90), (660, 140)],
    # "I heard you, and there was nothing to do." Deliberately ONE short
    # neutral note and not the error pair: the correction key lands here
    # whenever the text it wants is not on screen any more, which is a
    # normal thing to happen and not a failure worth two falling tones.
    "noop": [(494, 85)],
    # The opposite of "noop", and it needs its own sound BECAUSE it is the
    # opposite: the context pass just rewrote text that is already on
    # screen, without being asked. It starts on the neutral note and rises,
    # like every other "it landed" cue here — recognisably related to the
    # note you know, and unmistakably not it.
    "repaired": [(494, 80), (740, 110)],
    # THE SCREEN KEYS. A capture is a different KIND of act from every cue
    # above it: nothing was heard, nothing was rewritten, a thing now
    # exists. So it gets a shape of its own rather than a fourth pitch in
    # the grab-ask-return family -- a short rise like a shutter, high
    # enough to be unmistakable over whatever was playing.
    "shot": [(1047, 55), (1397, 85)],
    # A recording is the one thing in this app with a DURATION you can
    # forget about, so its two cues are deliberately opposite and
    # deliberately not subtle: rising to start, falling to stop, a fifth
    # apart, the shape every recording light in the world already has.
    "recording": [(784, 90), (1175, 130)],
    "recorded": [(1175, 90), (784, 140)],
    # Something ARRIVED: nothing was heard, nothing rewritten, a message
    # is waiting (notify.py) — three short rising notes, its own shape,
    # because every pair above means "you did a thing" and this is the
    # one cue that plays when you did nothing. Replayed by every reminder
    # rather than given a second shape: it is the same message, unread.
    "notify": [(784, 70), (988, 70), (1319, 150)],
}

# kind -> character. THE FAMILY IS THE SOUND, NOT THE PITCH.
#
# Six ways of making a note, chosen so that the cues which used to be
# confusable are now made differently rather than tuned differently. The
# three keys that feel identical under the finger — translate, punctuate,
# look up — are the clearest case, and they get the owner's own three
# examples: "one short and sharp, one rolling, one muffled".
#
# DEFAULT IS "sine", so a kind added later without a character here still
# renders exactly as the whole table used to.
CHARACTERS: dict[str, str] = {
    # The recording lifecycle — the one thing here with a DURATION you can
    # forget about. Struck, like a recording light, and the only family
    # that rings.
    "start": "bell",
    "stop": "bell",
    "latch": "bell",
    "recording": "bell",
    "recorded": "bell",
    # Translate: rolling. The note wavers, the way a phrase being turned
    # over does.
    "translating": "roll",
    "translated": "roll",
    # Punctuate: short and sharp. A dot is a tick, not a tone.
    "punctuating": "sharp",
    "punctuated": "sharp",
    # Look up: muffled. Soft edges on both ends — a question asked
    # quietly, and it must not be mistaken for the tick next to it.
    "looking": "soft",
    "looked": "soft",
    # The app waking and going away. Hollow and unhurried: it happens
    # twice a day and should sound like neither work nor an alarm.
    "ready": "hollow",
    "bye": "hollow",
    # Pause and resume share that hollow character for the same reason —
    # they are the app's state, not your work — and stay a falling and a
    # rising fifth so the direction still says which way it went.
    "paused": "hollow",
    "resumed": "hollow",
    # "Heard you, nothing to do", and its opposite. Glassy and bright, so
    # a key that landed on nothing is never mistaken for one that worked.
    "noop": "glass",
    "repaired": "glass",
    # Something ARRIVED. Glass as well — nothing was done by you — and its
    # three rising notes already give it a shape no other cue has.
    "notify": "glass",
    # The screen keys. Not a tone at all: a burst of air, like a shutter.
    # A shutter envelope on the shortest, highest pair in the table came
    # out rough — his word, and he heard it every screenshot for an hour
    # on 2026-09-05. `air` gives a 12% attack and a 55% release, which on
    # a 55 ms note at 1047 Hz leaves almost no steady tone at all: what
    # reaches the ear is the shape, not the pitch. The plain envelope has
    # the note back. The capture cue is still unmistakable without a
    # character of its own — it is the only rising pair up at C6/F6, and
    # nothing else in the table goes near it.
    "shot": "sine",
    # Failure keeps the plain falling tone. It is the one cue that was
    # already unlike everything else (the only -4 semitone move in the
    # table) and the one you least want redesigned into something clever.
    "error": "sine",
}


def _partials(character: str) -> list[tuple[float, float]]:
    """(harmonic multiple, amplitude) pairs that make up the timbre.

    Amplitudes are normalised by their own sum in _tone, so adding a
    partial changes the COLOUR and never the loudness.
    """
    return {
        # Odd harmonics, strong: bright and buzzy, reads as an edge.
        "sharp": [(1.0, 1.0), (3.0, 0.42), (5.0, 0.22), (7.0, 0.11)],
        # Odd harmonics only, weak: the woody, stopped-pipe sound.
        "hollow": [(1.0, 1.0), (3.0, 0.28), (5.0, 0.09)],
        # Octaves: no odd partials at all, so it rings clean and high.
        "glass": [(1.0, 1.0), (2.0, 0.5), (4.0, 0.22), (8.0, 0.08)],
        # Inharmonic partials are what makes a struck bar sound struck;
        # 2.76 and 5.40 are the classic tubular-bell ratios.
        "bell": [(1.0, 1.0), (2.76, 0.55), (5.40, 0.22)],
        # Fundamental plus a whisper of second: darker than a pure sine
        # without becoming another colour.
        "soft": [(1.0, 1.0), (2.0, 0.12)],
        "roll": [(1.0, 1.0), (2.0, 0.18)],
    }.get(character, [(1.0, 1.0)])


def _envelope(character: str, i: int, count: int) -> float:
    """Amplitude at sample `i` of `count`. Never longer than the note.

    EVERY character must fill exactly `count` samples and start and end at
    zero. The duration of a cue is its own contract — test_cue_files_are_
    valid_wavs checks the WAV against sum(ms) to within 20 ms — so a
    character earns its shape inside the note it was given, never by
    ringing on past it.
    """
    if count <= 1:
        return 0.0
    fade = max(1, int(SAMPLE_RATE * 0.006))     # ~6 ms, kills the click
    tail = max(1, int(SAMPLE_RATE * 0.004))     # the close, for all of them
    close = min(1.0, (count - i) / tail)
    if character in ("bell", "glass"):
        # Struck: there at once, then decaying. The close is what keeps
        # the truncation from clicking when the decay has not finished.
        attack = min(1.0, i / max(1, int(SAMPLE_RATE * 0.0015)))
        return attack * math.exp(-3.2 * i / count) * close
    if character == "sharp":
        # A tick: immediate, flat, gone.
        return min(1.0, i / max(1, int(SAMPLE_RATE * 0.001))) * close
    if character in ("soft", "hollow"):
        # Muffled: eased in over a third of the note and eased out over
        # the rest, so it has no edge at either end.
        rise = max(1, int(count * 0.34))
        shape = min(1.0, i / rise, (count - i) / max(1, int(count * 0.5)))
        return shape * shape * close          # squared = gentler still
    if character == "air":
        # A shutter: a fast swell and an immediate stop.
        return min(1.0, i / max(1, int(count * 0.12))) \
            * min(1.0, (count - i) / max(1, int(count * 0.55)))
    return min(1.0, i / fade, (count - i) / fade)


def _tone(freq: int, ms: int, character: str, phase: int) -> array.array:
    """One note. `phase` only seeds the noise, so "air" is reproducible.

    ensure_files writes these to disk once and every later run compares
    against what is there, so two runs of the same table must produce
    byte-identical WAVs — which rules out random.random().
    """
    samples = array.array("h")
    count = int(SAMPLE_RATE * ms / 1000)
    partials = _partials(character)
    weight = sum(a for _m, a in partials)
    # A cheap deterministic PRNG (a 32-bit LCG) for the "air" character.
    seed = (freq * 2654435761 + ms * 40503 + phase * 97) & 0xFFFFFFFF
    for i in range(count):
        env = _envelope(character, i, count)
        if character == "air":
            seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
            value = (seed / 0x3FFFFFFF) - 1.0
            # Two poles of the fundamental keep it a shutter and not a
            # hiss: noise alone has no pitch to place it against.
            value = 0.7 * value + 0.3 * math.sin(
                2 * math.pi * freq * i / SAMPLE_RATE)
        else:
            value = sum(
                amp * math.sin(2 * math.pi * freq * mult * i / SAMPLE_RATE)
                for mult, amp in partials) / weight
            if character == "roll":
                # Rolling: a 24 Hz tremolo, deep enough to hear as motion
                # rather than as a rough tone.
                value *= 0.62 + 0.38 * math.sin(
                    2 * math.pi * 24.0 * i / SAMPLE_RATE)
        samples.append(int(max(-32767.0,
                               min(32767.0,
                                   32767 * VOLUME * env * value))))
    return samples


def _render(segments: list[tuple[int, int]],
            character: str = "sine") -> bytes:
    samples = array.array("h")
    for phase, (freq, ms) in enumerate(segments):
        samples.extend(_tone(freq, ms, character, phase))
    return samples.tobytes()


def _write(path: Path, segments: list[tuple[int, int]],
           character: str = "sine") -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(_render(segments, character))


def _recipe() -> str:
    """A short fingerprint of everything that decides what the WAVs sound
    like — the notes, the characters, the rate and the volume."""
    parts = [str(SAMPLE_RATE), str(VOLUME)]
    for kind in sorted(CUES):
        parts.append(f"{kind}:{CHARACTERS.get(kind, 'sine')}:"
                     + ",".join(f"{f}/{ms}" for f, ms in CUES[kind]))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def ensure_files(force: bool = False) -> dict[str, Path]:
    """Generate the cue WAVs if missing. Returns kind -> path.

    THE STAMP IS WHY A CHANGE HERE IS AUDIBLE. These files are written
    once and then kept, so before the stamp existed, editing CUES or
    CHARACTERS changed nothing at all for anyone who had already run the
    app — main.py calls this without `force`, found 20 files present, and
    played the old ones for ever. The recipe hash makes a rewritten table
    reach the speakers on the next start, and only then.
    """
    CUE_DIR.mkdir(exist_ok=True)
    stamp = CUE_DIR / ".recipe"
    recipe = _recipe()
    try:
        stale = stamp.read_text(encoding="utf-8").strip() != recipe
    except OSError:
        stale = True
    force = force or stale
    paths = {}
    for kind, segments in CUES.items():
        path = CUE_DIR / f"{kind}.wav"
        if force or not path.exists():
            _write(path, segments, CHARACTERS.get(kind, "sine"))
        paths[kind] = path
    if stale:
        try:
            stamp.write_text(recipe, encoding="utf-8")
        except OSError:
            pass        # a read-only install still gets its sounds
    return paths


_paths: dict[str, Path] = {}


def play(kind: str) -> None:
    """Fire-and-forget cue; never raises, never blocks the caller."""
    global _paths
    import winsound
    try:
        if not _paths:
            _paths = ensure_files()
        path = _paths.get(kind)
        if path is None:
            return
        winsound.PlaySound(str(path), winsound.SND_FILENAME
                           | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        try:  # last resort: the legacy path, better than silence
            winsound.Beep(880, 100)
        except Exception:
            pass
