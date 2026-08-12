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
    "bye": [(880, 90), (587, 130)],      # app stopped
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
