"""Backend A: Gemini API. Transcription + cleanup in one request.

The key lives in the secret store (secretstore.py, through apikey.py)
and this module never sees its value: gemini_pool.Client speaks REST
through net.py, which attaches the key by NAME to the one host it
belongs to and writes a row in network.log per call (D12, plan 5.6).

Free-tier quota is counted PER MODEL (measured: gemini-2.5-flash allows 20
generate_content requests per day), so this backend is given a list of
models and rotates to the next one as each hits its cap. That turns a hard
stop after 20 dictations into a much longer runway at no cost.
"""
from __future__ import annotations

import logging
import time

import gemini_pool
import privacy
from apikey import MISSING_KEY_MESSAGE, find_api_key
from gemini_pool import MAX_COOLDOWN_S, PER_DAY_COOLDOWN_S
from gemini_pool import parse_429 as _parse_429

from .base import TooLongForCloud, TranscriptionError

log = logging.getLogger("app")

__all__ = ["GeminiTranscriber", "ConsentRequired", "_parse_429",
           "PER_DAY_COOLDOWN_S", "MAX_COOLDOWN_S"]


class ConsentRequired(TranscriptionError, privacy.ConsentRequired):
    """The cloud_audio gate is shut: the recording may not leave until
    the person says so on the card. A TranscriptionError, so the start-up
    path falls to the local backend the way it does for a missing key."""

    def __init__(self, kind: str, why: str):
        privacy.ConsentRequired.__init__(self, kind, why)

_SYSTEM_PROMPT = """\
You are a transcription engine for Hebrew speech. The user dictates text \
that will be inserted at their cursor, usually prose or instructions for a \
coding assistant.

Rules:
- Output ONLY the final transcript. No preamble, no explanation, no \
markdown, no quotation marks around it.
- The speech is Hebrew, possibly with embedded English technical terms. \
Transcribe Hebrew as Hebrew. NEVER translate to another language.
- Keep English words and technical terms (e.g. "commit", "branch", tool or \
file names) in Latin script exactly as spoken; do not transliterate them \
into Hebrew letters.
- Remove filler words and hesitations (e.g. אה, אמ, \
אממ, and כאילו when used as filler).
- Punctuate properly.
- When the speaker corrects themselves, keep only the corrected version: \
"בשלוש, לא, בארבע" \
becomes "בארבע".
- Write numbers as digits.
- Output a single paragraph with no line breaks, unless the speaker clearly \
dictates separate paragraphs or a list.
- If the audio contains no intelligible speech, output nothing at all.
"""


class GeminiTranscriber:
    name = "gemini"

    def __init__(self, models: list[str] | str, timeout_s: int):
        try:
            privacy.require("cloud_audio")
        except privacy.ConsentRequired as e:
            raise ConsentRequired(e.kind, e.why) from None
        api_key, self.key_source = find_api_key()
        if not api_key:
            raise TranscriptionError(MISSING_KEY_MESSAGE)
        del api_key                       # net.py attaches it by name
        self._models = [models] if isinstance(models, str) else list(models)
        if not self._models:
            raise TranscriptionError("no gemini models configured")
        # model -> monotonic deadline before which it is known-exhausted
        self._cooldown: dict[str, float] = {}
        self._strikes: dict[str, int] = {}
        self._thinking: dict[str, str] = {}   # model -> budget|level|none
        self._client = gemini_pool.Client("transcribe", timeout_s)

    @property
    def model(self) -> str:
        """The model the next request would use (first one off cooldown)."""
        now = time.monotonic()
        for m in self._models:
            if self._cooldown.get(m, 0.0) <= now:
                return m
        return self._models[0]

    def _one(self, model: str, wav_bytes: bytes,
             language: str | None = None) -> str:
        # Measured before anything is sent (plan 5.6): over the cap the
        # request would be refused anyway, and the local model is right
        # here. Never spooled for a later cloud attempt.
        if gemini_pool.inline_size(wav_bytes) + 4096 > gemini_pool.INLINE_CAP_BYTES:
            raise TooLongForCloud(
                f"{len(wav_bytes) / 1_048_576:.1f} MB of audio is too long for "
                "the cloud pass — decoded on this PC")
        instruction = "Transcribe this recording following the system rules."
        if language == "en":
            # The system prompt is written for Hebrew; the user pressed the
            # English key, so say so explicitly rather than let it "correct"
            # English into Hebrew.
            instruction = ("Transcribe this recording. The speech is "
                           "ENGLISH — output English text only, never "
                           "Hebrew. Follow the other system rules "
                           "(no preamble, remove fillers, punctuate).")
        contents = [
            gemini_pool.blob_part(wav_bytes, "audio/wav"),
            gemini_pool.text_part(instruction),
        ]
        # The thinking knob's 400 rescue lives in Client.generate: an
        # unknown future model that rejects both knobs is retried
        # without one and remembered, rather than lost.
        response = self._client.generate(
            model, contents, system=_SYSTEM_PROMPT, temperature=0.2,
            thinking=self._thinking)
        text = gemini_pool.text_of(response)
        if text is not None:
            return text.strip()

        reason = gemini_pool.finish_reason(response)
        # The system prompt tells the model to emit nothing when it hears no
        # intelligible speech, so "finished normally, no text" is silence —
        # not a failure. Retrying or spooling it would be pointless.
        if reason.endswith("STOP"):
            return ""
        raise TranscriptionError(
            f"Gemini returned no text (finish_reason={reason or '?'})")

    def transcribe(self, wav_bytes: bytes,
                   language: str | None = None) -> str:
        def attempt(model: str) -> str:
            text = self._one(model, wav_bytes, language)
            self._strikes[model] = 0
            return text

        return gemini_pool.rotate(self._models, self._cooldown, self._strikes,
                                  attempt)

    def check(self) -> str:
        """One tiny text-only request to validate key + model + quota."""
        response = self._client.generate(
            self.model, [gemini_pool.text_part("Reply with exactly: OK")])
        return (gemini_pool.text_of(response) or "").strip()
