"""Pluggable transcription backends behind one interface."""
from __future__ import annotations

from .base import ModelMissing, RateLimitError, Transcriber, TranscriptionError

__all__ = ["Transcriber", "TranscriptionError", "RateLimitError",
           "ModelMissing", "get_transcriber", "local_kwargs", "configure"]


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
                beam_size=cfg.local.beam_size,
                compute_type=cfg.local.compute_type,
                cpu_threads=cfg.local.cpu_threads,
                real_length=cfg.local.real_length,
                boilerplate=boilerplate)


def configure(backend, cfg):
    """The [local] settings a local backend takes as attributes rather
    than constructor arguments (so no signature changed for them), set
    from `cfg` -> the backend. Every place that builds one from a config
    calls this — the app's builder, the fallback, review.py, study.py,
    dev\\measure.py — so `stop_empty_passes = false` reaches an A/B run
    exactly as it reaches the app."""
    if hasattr(backend, "stop_empty_passes"):
        backend.stop_empty_passes = bool(
            getattr(getattr(cfg, "local", None), "stop_empty_passes", True))
    return backend


def _local(cfg, hotwords, english_later: bool = False) -> Transcriber:
    """The local backend — or, on an installed copy whose model is not
    on disk yet (models.py), the stand-in that lets the app start and
    says so at the first dictation. The checkout never meets this: its
    model comes from the global cache as always (D4)."""
    from .local_whisper import LocalWhisperTranscriber

    def build():
        return configure(LocalWhisperTranscriber(
            **local_kwargs(cfg, hotwords), english_later=english_later), cfg)
    try:
        return build()
    except ModelMissing as e:
        import logging
        logging.getLogger("app").warning(
            "%s — starting without local transcription", e)
        from .missing import MissingModelTranscriber
        return MissingModelTranscriber(e, build)


def get_transcriber(cfg, hotwords=None, *,
                    english_later: bool = False) -> Transcriber:
    """Build the backend selected in config. Imports lazily so the fake
    backend works without faster-whisper.

    Every backend here runs on this PC. The one that did not — "gemini",
    which sent the recording to Google — was taken out on 2026-11-27
    (house rule 2: the PC never sends audio anywhere); config.build reads
    a file that still names it as "local" (config.RETIRED_BACKENDS).

    `english_later` (the live app): the local backend returns as soon
    as the Hebrew model is ready and loads the English detector on a
    thread of its own — see LocalWhisperTranscriber. The default loads
    both before returning, which is what the wizard's timed sentence,
    --benchmark and --drain want."""
    if cfg.backend == "fake":
        from .fake import FakeTranscriber
        return FakeTranscriber()
    if cfg.backend == "local":
        return _local(cfg, hotwords, english_later)
    raise ValueError(f"unknown backend: {cfg.backend!r}")
