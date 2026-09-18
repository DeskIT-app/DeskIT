"""The backend that stands in while the model is unloaded.

Stop in the desk unloads the speech model and nothing else (main.py
unload_model, the owner's ask of 2026-09-18: "many things don't need the
model ... make those that don't need the model work without it"). Every
place that reads ``self.transcriber.name`` — status(), the phone's
/health, the log lines — keeps working against this; a dictation that
somehow reaches it (one queued in the last moment before the unload)
meets a typed TranscriptionError with the sentence the desk says.
"""
from __future__ import annotations

from .base import TranscriptionError


class OffTranscriber:
    name = "off"

    def __init__(self, words: str):
        self.words = words

    def transcribe(self, wav_bytes: bytes, language: str | None = None) -> str:
        raise TranscriptionError(self.words)
