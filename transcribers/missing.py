"""The backend that stands in while the Hebrew model is not on disk.

An installed copy whose person said "Not now" to the download, or lost
the connection halfway, still has to START: the translate key, the
lookup, the phone and the dashboard need no model, and an app that
shows a message box and quits over a file it can fetch later is the
failure DISTRIBUTION_PLAN.md 6.9 names. So get_transcriber() hands main
this instead of raising, and every dictation meets the same typed
ModelMissing the loader raised — main keeps the recording in pending\\
(a later --drain turns it into text once the model exists) and says
why on the card, without the retry loop it would give a cloud error.

It also watches for the model: the Home row's [Download] runs the step
in a process of its own, and the next dictation after `.complete`
appears builds the real backend right here (the ~25 s the splash
usually spends, said in the log) and hands everything to it from then
on — no restart. What the real backend has and this one does not
(study_decode, decode_window) stays off until the next start; main asks
with hasattr and dictation itself is whole.
"""
from __future__ import annotations

import inspect
import logging

from .base import ModelMissing

log = logging.getLogger("app")


class MissingModelTranscriber:
    def __init__(self, error: ModelMissing, build=None):
        self.error = error
        self._build = build
        self._real = None

    @property
    def name(self) -> str:
        return self._real.name if self._real is not None else "missing"

    def _upgrade(self):
        """The real backend, once the model is verified on disk."""
        if self._real is not None or self._build is None:
            return self._real
        import models
        if not models.ready(self.error.repo):
            return None
        log.info("the Hebrew model is on disk now — loading it (this takes "
                 "a while, once)")
        self._real = self._build()
        return self._real

    def transcribe(self, wav_bytes: bytes, language: str | None = None) -> str:
        real = self._upgrade()
        if real is None:
            raise ModelMissing(self.error.repo, self.error.state, str(self.error))
        try:
            takes_language = "language" in inspect.signature(real.transcribe).parameters
        except (TypeError, ValueError):
            takes_language = False
        return real.transcribe(wav_bytes, language) if takes_language else real.transcribe(wav_bytes)

    def __getattr__(self, item: str):
        real = self.__dict__.get("_real")
        if real is not None:
            return getattr(real, item)
        raise AttributeError(item)
