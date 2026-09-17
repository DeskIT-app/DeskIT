"""Backend A: Gemini API. Transcription + cleanup in one request.

The key comes from the secret store (secretstore.py, through apikey.py);
the SDK's HTTP client rides net.py's transport with the base URL pinned,
so the one host it can reach is the allowlisted one and every call is a
row in network.log (D12; the REST port of plan 5.6 retires the SDK).

Free-tier quota is counted PER MODEL (measured: gemini-2.5-flash allows 20
generate_content requests per day), so this backend is given a list of
models and rotates to the next one as each hits its cap. That turns a hard
stop after 20 dictations into a much longer runway at no cost.
"""
from __future__ import annotations

import logging
import time

from google import genai
from google.genai import errors, types

import gemini_pool
import net
from apikey import MISSING_KEY_MESSAGE, find_api_key
from gemini_pool import MAX_COOLDOWN_S, PER_DAY_COOLDOWN_S
from gemini_pool import parse_429 as _parse_429

from .base import TranscriptionError

log = logging.getLogger("app")

__all__ = ["GeminiTranscriber", "_parse_429", "PER_DAY_COOLDOWN_S",
           "MAX_COOLDOWN_S"]

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
        api_key, self.key_source = find_api_key()
        if not api_key:
            raise TranscriptionError(MISSING_KEY_MESSAGE)
        self._models = [models] if isinstance(models, str) else list(models)
        if not self._models:
            raise TranscriptionError("no gemini models configured")
        # model -> monotonic deadline before which it is known-exhausted
        self._cooldown: dict[str, float] = {}
        self._strikes: dict[str, int] = {}
        self._thinking: dict[str, str] = {}   # model -> budget|level|none
        self._client = genai.Client(
            api_key=api_key, vertexai=False,
            http_options=net.genai_http_options("transcribe", timeout_s))

    @property
    def model(self) -> str:
        """The model the next request would use (first one off cooldown)."""
        now = time.monotonic()
        for m in self._models:
            if self._cooldown.get(m, 0.0) <= now:
                return m
        return self._models[0]

    def _config(self, model: str) -> types.GenerateContentConfig:
        cfg = types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.2,
        )
        return gemini_pool.apply_thinking(cfg, model, self._thinking)

    def _one(self, model: str, wav_bytes: bytes,
             language: str | None = None) -> str:
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
            types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
            instruction,
        ]
        try:
            response = self._client.models.generate_content(
                model=model, contents=contents, config=self._config(model))
        except errors.APIError as e:
            # An unknown future model may reject both knobs. Rather than lose
            # the model, drop the thinking config for it from now on.
            if getattr(e, "code", None) == 400 and \
                    self._thinking.get(model) != "none":
                log.info("%s rejected the thinking setting — retrying "
                         "without it (slower, still correct)", model)
                self._thinking[model] = "none"
                response = self._client.models.generate_content(
                    model=model, contents=contents,
                    config=self._config(model))
            else:
                raise
        try:
            text = response.text
        except Exception:
            text = None
        if text is not None:
            return text.strip()

        reason = ""
        try:
            if response.candidates:
                reason = str(response.candidates[0].finish_reason)
        except Exception:
            pass
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
        response = self._client.models.generate_content(
            model=self.model, contents="Reply with exactly: OK")
        return (response.text or "").strip()
