"""Transcriber interface. Implementations must not assume a network —
they receive complete WAV bytes and return plain text."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


class TranscriptionError(Exception):
    """Transcription failed. str(e) is a console-friendly message."""


class RateLimitError(TranscriptionError):
    """Backend quota exhausted (e.g. Gemini free-tier 429).

    retry_after is the server's own RetryInfo in seconds when it supplied
    one, so callers wait exactly as long as the API asked rather than
    guessing. per_day marks the daily cap, which no amount of short waiting
    will clear.
    """

    def __init__(self, message: str, retry_after: float = 0.0,
                 per_day: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        self.per_day = per_day


class TooLongForCloud(TranscriptionError):
    """The recording would not fit Google's inline request cap, so it
    was never sent (plan 5.6): the caller decodes it here and says so
    on the card. Never spooled for a later cloud attempt."""


@runtime_checkable
class Transcriber(Protocol):
    name: str

    def transcribe(self, wav_bytes: bytes) -> str:
        """WAV audio in, plain transcript out. Empty string = no speech."""
        ...
