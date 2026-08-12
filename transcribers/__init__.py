"""Pluggable transcription backends behind one interface."""
from __future__ import annotations

from .base import RateLimitError, Transcriber, TranscriptionError

__all__ = ["Transcriber", "TranscriptionError", "RateLimitError",
           "get_transcriber"]


def get_transcriber(cfg) -> Transcriber:
    """Build the backend selected in config. Imports lazily so the fake
    backend works without google-genai and the local stub without
    faster-whisper."""
    if cfg.backend == "gemini":
        from .gemini import GeminiTranscriber
        return GeminiTranscriber(list(cfg.gemini.models), cfg.gemini.timeout_s)
    if cfg.backend == "fake":
        from .fake import FakeTranscriber
        return FakeTranscriber()
    if cfg.backend == "local":
        from .local_whisper import LocalWhisperTranscriber
        return LocalWhisperTranscriber(cfg.local.model, cfg.local.language,
                                       cfg.local.device, cfg.local.cleanup,
                                       cfg.local.extra_fillers,
                                       cfg.local.english_model,
                                       cfg.local.english_threshold)
    raise ValueError(f"unknown backend: {cfg.backend!r}")
