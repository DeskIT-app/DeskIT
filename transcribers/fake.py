"""Test backend: returns canned Hebrew instantly. No API call, no speech
needed — exercises the full capture -> clipboard -> paste chain, including
mixed Hebrew/Latin RTL behavior in the target window."""
from __future__ import annotations

_TEMPLATE = ("בדיקה {n}: זהו תמלול מזויף עם מונח טכני כמו git commit, "
             "פסיק ונקודה. נקלטו {seconds:.1f} שניות של אודיו.")


class FakeTranscriber:
    name = "fake"

    def __init__(self) -> None:
        self._n = 0

    def transcribe(self, wav_bytes: bytes) -> str:
        self._n += 1
        seconds = max(len(wav_bytes) - 44, 0) / 32000  # 16 kHz * int16 mono
        return _TEMPLATE.format(n=self._n, seconds=seconds)
