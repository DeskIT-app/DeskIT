"""Pluggable transcription backends behind one interface."""
from __future__ import annotations

from .base import RateLimitError, Transcriber, TranscriptionError

__all__ = ["Transcriber", "TranscriptionError", "RateLimitError",
           "get_transcriber", "local_kwargs"]


def local_kwargs(cfg, hotwords=None) -> dict:
    """Arguments for the local backend, in one place: it is built both as
    the primary backend and as the fallback when cloud quota is spent, and
    the two must not drift apart.

    `hotwords` is a callable returning the learned vocabulary (vocab.py).
    It is threaded through here rather than read from cfg because the
    vocabulary is mutable state that outlives the config, and because
    passing None must keep giving a backend that behaves exactly as it did
    before any of this existed.
    """
    import cleanup as cleanup_mod

    boilerplate = ()
    if cfg.local.drop_trailing_boilerplate:
        boilerplate = (cleanup_mod.PARLIAMENTARY_BOILERPLATE
                       + tuple(cfg.local.extra_boilerplate))
    return dict(hotwords=hotwords,
                model=cfg.local.model,
                language=cfg.local.language,
                device=cfg.local.device,
                cleanup=cfg.local.cleanup,
                extra_fillers=cfg.local.extra_fillers,
                english_model=cfg.local.english_model,
                english_threshold=cfg.local.english_threshold,
                initial_prompt=cfg.local.initial_prompt,
                guard_hallucinations=cfg.local.guard_hallucinations,
                boilerplate=boilerplate)


def get_transcriber(cfg, hotwords=None) -> Transcriber:
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
        return LocalWhisperTranscriber(**local_kwargs(cfg, hotwords))
    raise ValueError(f"unknown backend: {cfg.backend!r}")
