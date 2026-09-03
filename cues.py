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
import math
import wave
from pathlib import Path

CUE_DIR = Path(__file__).resolve().parent / "cues"
SAMPLE_RATE = 44100
VOLUME = 0.5

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


def _render(segments: list[tuple[int, int]]) -> bytes:
    samples = array.array("h")
    for freq, ms in segments:
        count = int(SAMPLE_RATE * ms / 1000)
        fade = max(1, int(SAMPLE_RATE * 0.006))  # ~6 ms, kills the click
        for i in range(count):
            envelope = min(1.0, i / fade, (count - i) / fade)
            samples.append(int(32767 * VOLUME * envelope
                               * math.sin(2 * math.pi * freq * i
                                          / SAMPLE_RATE)))
    return samples.tobytes()


def _write(path: Path, segments: list[tuple[int, int]]) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(_render(segments))


def ensure_files(force: bool = False) -> dict[str, Path]:
    """Generate the cue WAVs if missing. Returns kind -> path."""
    CUE_DIR.mkdir(exist_ok=True)
    paths = {}
    for kind, segments in CUES.items():
        path = CUE_DIR / f"{kind}.wav"
        if force or not path.exists():
            _write(path, segments)
        paths[kind] = path
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
