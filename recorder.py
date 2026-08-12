"""Push-to-talk microphone capture.

One persistent input stream for the app's lifetime — opening a WASAPI stream
per utterance is slow enough to clip the first word. Frames are only buffered
while an utterance is active; otherwise audio is discarded on arrival.
"""
from __future__ import annotations

import io
import math
import threading
import wave
from typing import Callable

import numpy as np
import sounddevice as sd

IDLE = "idle"
ACTIVE = "active"
OVERFLOWED = "overflowed"


def frames_to_wav(chunks: list[np.ndarray], sample_rate: int) -> bytes:
    """int16 mono chunks -> WAV file bytes."""
    pcm = b"".join(c.tobytes() for c in chunks)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # int16
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class Recorder:
    def __init__(self, sample_rate: int, device: int | str | None,
                 max_seconds: float, on_overflow: Callable[[], None]):
        self._on_overflow = on_overflow
        self._lock = threading.Lock()
        self._state = IDLE
        self._chunks: list[np.ndarray] = []
        self._samples = 0
        try:
            self._stream = sd.InputStream(
                samplerate=sample_rate, channels=1, dtype="int16",
                device=device, callback=self._callback)
        except sd.PortAudioError:
            # Some drivers refuse 16 kHz shared-mode capture. Fall back to the
            # device's default rate — Gemini accepts any WAV rate, the upload
            # is just larger.
            self._stream = sd.InputStream(
                samplerate=None, channels=1, dtype="int16",
                device=device, callback=self._callback)
        self.sample_rate = int(self._stream.samplerate)
        self._default_max_samples = float(max_seconds * self.sample_rate)
        self._max_samples = self._default_max_samples

    def start_stream(self) -> None:
        self._stream.start()

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass

    def device_label(self) -> str:
        try:
            info = sd.query_devices(self._stream.device)
            return f"{info['name']} @ {self.sample_rate} Hz"
        except Exception:
            return f"input device @ {self.sample_rate} Hz"

    # -- utterance lifecycle (called from the hook thread) --

    def begin(self) -> None:
        with self._lock:
            self._chunks = []
            self._samples = 0
            self._max_samples = self._default_max_samples  # undo any lift
            self._state = ACTIVE

    def set_cap(self, seconds: float | None) -> None:
        """Change the runaway cap for the recording in progress. None or 0
        removes it — used when the user latches the key down, where the cap
        no longer protects against anything (there is no key-up to swallow)
        and would only truncate a long deliberate dictation."""
        with self._lock:
            self._max_samples = (math.inf if not seconds
                                 else float(seconds * self.sample_rate))

    def abort(self) -> None:
        with self._lock:
            self._chunks = []
            self._samples = 0
            self._state = IDLE

    def end(self) -> tuple[bytes | None, float]:
        """Finish the utterance -> (wav_bytes, seconds).

        wav_bytes is None when the recording overflowed max_seconds (already
        discarded) or nothing was captured.
        """
        with self._lock:
            state = self._state
            chunks = self._chunks
            samples = self._samples
            self._state = IDLE
            self._chunks = []
            self._samples = 0
        seconds = samples / self.sample_rate
        if state != ACTIVE or not chunks:
            return None, seconds
        return frames_to_wav(chunks, self.sample_rate), seconds

    # -- PortAudio callback thread: keep it tiny --

    def _callback(self, indata, frames, time_info, status) -> None:
        notify = None
        with self._lock:
            if self._state == ACTIVE:
                self._chunks.append(indata.copy())
                self._samples += len(indata)
                if self._samples >= self._max_samples:
                    # Runaway recording (e.g. key-up swallowed by an elevated
                    # window): drop the buffer, remember the duration.
                    self._state = OVERFLOWED
                    self._chunks = []
                    notify = self._on_overflow
        if notify is not None:
            notify()
