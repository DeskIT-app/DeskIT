"""Backend A: Gemini API. Transcription + cleanup in one request.

Reads the key from the environment or a local .env file (see apikey.py).
Never hardcoded.

Free-tier quota is counted PER MODEL (measured: gemini-2.5-flash allows 20
generate_content requests per day), so this backend is given a list of
models and rotates to the next one as each hits its cap. That turns a hard
stop after 20 dictations into a much longer runway at no cost.
"""
from __future__ import annotations

import logging
import re
import time

from google import genai
from google.genai import errors, types

from apikey import MISSING_KEY_MESSAGE, find_api_key

from .base import RateLimitError, TranscriptionError

log = logging.getLogger("app")

# A model that returned "per day" quota exhausted will not recover in
# seconds. Re-probe occasionally anyway so the midnight reset is picked up
# without restarting the app.
PER_DAY_COOLDOWN_S = 30 * 60
MAX_COOLDOWN_S = 60 * 60

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


def _parse_429(e: errors.APIError) -> tuple[float, bool, int | None]:
    """(retry_after_seconds, is_per_day, limit) from a 429 body.

    The SDK surfaces the message text reliably; the structured RetryInfo is
    not always populated, so both are read out of the message as a fallback.
    """
    message = str(getattr(e, "message", "") or e)
    retry_after, per_day, limit = 0.0, False, None

    m = re.search(r"retry in ([0-9.]+)s", message, re.I)
    if m:
        retry_after = float(m.group(1))
    m = re.search(r"limit: (\d+)", message)
    if m:
        limit = int(m.group(1))
    if re.search(r"per\s*day", message, re.I):
        per_day = True

    for detail in (getattr(e, "details", None) or {}).get(
            "error", {}).get("details", []) if isinstance(
                getattr(e, "details", None), dict) else []:
        kind = detail.get("@type", "")
        if kind.endswith("RetryInfo"):
            m = re.match(r"([0-9.]+)s", str(detail.get("retryDelay", "")))
            if m:
                retry_after = float(m.group(1))
        elif kind.endswith("QuotaFailure"):
            for v in detail.get("violations", []):
                if "PerDay" in str(v.get("quotaId", "")):
                    per_day = True
                if v.get("quotaValue"):
                    limit = int(v["quotaValue"])
    return retry_after, per_day, limit


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
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout_s * 1000))

    @property
    def model(self) -> str:
        """The model the next request would use (first one off cooldown)."""
        now = time.monotonic()
        for m in self._models:
            if self._cooldown.get(m, 0.0) <= now:
                return m
        return self._models[0]

    def _thinking_style(self, model: str) -> str:
        """Which "stop thinking" knob this model accepts.

        Transcription needs no reasoning, and thinking costs seconds of
        latency — but the two families reject each other's knob with a 400,
        so the wrong guess breaks the model entirely. Measured 2026-08-12:
        2.5-family takes thinking_budget=0; the Gemini 3 "-latest" aliases
        take thinking_level="low" and 400 on thinking_budget.
        """
        if model in self._thinking:
            return self._thinking[model]
        style = "budget" if model.startswith("gemini-2.5") else "level"
        self._thinking[model] = style
        return style

    def _config(self, model: str) -> types.GenerateContentConfig:
        cfg = types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.2,
        )
        style = self._thinking_style(model)
        if style == "budget":
            cfg.thinking_config = types.ThinkingConfig(thinking_budget=0)
        elif style == "level":
            cfg.thinking_config = types.ThinkingConfig(thinking_level="low")
        return cfg

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
        now = time.monotonic()
        soonest = None
        tried = False
        for model in self._models:
            resting = self._cooldown.get(model, 0.0)
            if resting > now:
                soonest = resting if soonest is None else min(soonest, resting)
                continue
            tried = True
            try:
                text = self._one(model, wav_bytes, language)
            except errors.APIError as e:
                code = getattr(e, "code", None)
                if code != 429:
                    raise TranscriptionError(
                        f"Gemini API error {code} on {model}: "
                        f"{getattr(e, 'message', e)}") from e
                retry_after, per_day, limit = _parse_429(e)
                self._strikes[model] = self._strikes.get(model, 0) + 1
                if per_day:
                    wait = PER_DAY_COOLDOWN_S
                else:
                    # Back off harder each time a model keeps refusing, so a
                    # spent bucket is not hammered every single dictation.
                    wait = max(retry_after, 5.0) * (
                        2 ** (self._strikes[model] - 1))
                wait = min(wait, MAX_COOLDOWN_S)
                self._cooldown[model] = time.monotonic() + wait
                log.warning(
                    "%s out of quota%s — resting it %.0f min, trying next "
                    "model", model,
                    f" (free-tier cap {limit}/day)" if limit and per_day
                    else "", wait / 60)
                soonest = (self._cooldown[model] if soonest is None
                           else min(soonest, self._cooldown[model]))
                continue
            except TranscriptionError:
                raise                   # already a clean message; don't rewrap
            except Exception as e:      # timeouts, DNS, ...
                raise TranscriptionError(
                    f"Gemini request failed on {model}: {e}") from e
            self._strikes[model] = 0
            return text

        wait_s = max(0.0, (soonest or 0.0) - time.monotonic())
        raise RateLimitError(
            f"all {len(self._models)} Gemini models are out of free-tier "
            f"quota (retry in ~{wait_s / 60:.0f} min)"
            + ("" if tried else " — all still resting from earlier 429s"),
            retry_after=wait_s, per_day=True)

    def check(self) -> str:
        """One tiny text-only request to validate key + model + quota."""
        response = self._client.models.generate_content(
            model=self.model, contents="Reply with exactly: OK")
        return (response.text or "").strip()
