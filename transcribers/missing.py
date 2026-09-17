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
"""
from __future__ import annotations

from .base import ModelMissing


class MissingModelTranscriber:
    name = "missing"

    def __init__(self, error: ModelMissing):
        self.error = error

    def transcribe(self, wav_bytes: bytes, language: str | None = None) -> str:
        raise ModelMissing(self.error.repo, self.error.state, str(self.error))
