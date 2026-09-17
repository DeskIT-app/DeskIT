"""WAV bytes -> the 16 kHz mono float32 array faster-whisper takes.

DISTRIBUTION_PLAN.md 13.4 (D24): the installed copy ships no PyAV, so
nothing on the dictation path may ask faster-whisper to decode a file
— `WhisperModel.transcribe(BytesIO(wav))` goes through its
`decode_audio`, which is PyAV. Every recording this app makes is 16 kHz
mono 16-bit PCM from PortAudio (recorder.py) and the phone posts the
same, so the decoder here is the standard library's `wave` plus
numpy: channels averaged, other rates resampled by linear
interpolation (never needed for the app's own files; the phone's are
16 kHz too). Anything that is not RIFF/WAVE is handed to PyAV when a
real one is there (the Recording pack, the checkout) and refused with
one sentence when it is not.
"""
from __future__ import annotations

import io
import wave

import numpy as np

RATE = 16_000


class NotWav(ValueError):
    """The bytes are not a PCM WAV — a phone upload in another format."""


def is_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def wav_to_float32(data: bytes, rate: int = RATE) -> np.ndarray:
    """The samples as float32 in [-1, 1] at `rate`, one channel."""
    if not is_wav(data):
        raise NotWav("not a RIFF/WAVE file")
    with wave.open(io.BytesIO(data), "rb") as w:
        channels, width, src_rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        frames = w.readframes(w.getnframes())
    if width == 2:
        pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        pcm = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        pcm = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise NotWav(f"unsupported sample width {width}")
    if channels > 1:
        pcm = pcm[: len(pcm) - len(pcm) % channels].reshape(-1, channels).mean(axis=1)
    if src_rate != rate and len(pcm):
        n = int(round(len(pcm) * rate / src_rate))
        x_old = np.linspace(0.0, 1.0, num=len(pcm), endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=max(1, n), endpoint=False)
        pcm = np.interp(x_new, x_old, pcm).astype(np.float32)
    return np.ascontiguousarray(pcm, dtype=np.float32)


def to_float32(data: bytes, rate: int = RATE) -> np.ndarray:
    """WAV through wav_to_float32; anything else through PyAV's decoder
    when a real one is present (av.is_stub() is the vendor stub's word;
    the checkout's av has no such attribute and is real)."""
    if is_wav(data):
        return wav_to_float32(data, rate)
    import av
    if getattr(av, "is_stub", lambda: False)():
        raise NotWav(av.MISSING)
    from faster_whisper.audio import decode_audio
    return decode_audio(io.BytesIO(data), sampling_rate=rate)


def seconds(samples: np.ndarray, rate: int = RATE) -> float:
    return float(len(samples)) / float(rate)
