"""Shared Gemini plumbing: the REST client, 429 parsing and model rotation.

The free tier counts generate_content requests PER MODEL PER DAY (measured
2026-08-12: gemini-2.5-flash allows 20). Transcription and translation both
spend from those same buckets, so they share one rotation policy here
rather than each growing its own drifting copy.

The rotation state (cooldown/strikes dicts) stays on the caller, not in
this module: each feature keeps its own view of which models are spent, and
the caller remains trivially testable by handing in plain dicts.
"""
from __future__ import annotations

import logging
import re
import time

from transcribers.base import RateLimitError, TranscriptionError

log = logging.getLogger("app")

# A model that returned "per day" quota exhausted will not recover in
# seconds. Re-probe occasionally anyway so the midnight reset is picked up
# without restarting the app.
PER_DAY_COOLDOWN_S = 30 * 60
MAX_COOLDOWN_S = 60 * 60


def parse_429(e) -> tuple[float, bool, int | None]:
    """(retry_after_seconds, is_per_day, limit) from a 429 body.

    `e` is an APIError (below): `message` is Google's error.message and
    `details` the parsed JSON body. The structured RetryInfo is not always
    populated, so both are read out of the message as a fallback.
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


def thinking_style(model: str, cache: dict[str, str]) -> str:
    """Which "stop thinking" knob this model accepts.

    Neither transcription nor translation needs reasoning, and thinking
    costs seconds of latency — but the two families reject each other's
    knob with a 400, so the wrong guess breaks the model entirely. Measured
    2026-08-12: the 2.5 family takes thinking_budget=0; the Gemini 3
    "-latest" aliases take thinking_level="low" and 400 on thinking_budget.
    """
    if model in cache:
        return cache[model]
    style = "budget" if model.startswith("gemini-2.5") else "level"
    cache[model] = style
    return style


def rotate(models: list[str], cooldown: dict[str, float],
           strikes: dict[str, int], attempt, what: str = "request") -> str:
    """Run `attempt(model)` against the first model that is not resting.

    A model that answers 429 is rested and the next one is tried, which
    turns a hard stop after 20 requests into a much longer runway at no
    cost. Raises RateLimitError only once EVERY model is spent, so callers
    can treat that as "the cloud is done for today" and fall back locally.
    """
    now = time.monotonic()
    soonest = None
    tried = False
    for model in models:
        resting = cooldown.get(model, 0.0)
        if resting > now:
            soonest = resting if soonest is None else min(soonest, resting)
            continue
        tried = True
        try:
            return attempt(model)
        except APIError as e:
            code = getattr(e, "code", None)
            if code != 429:
                raise TranscriptionError(
                    f"Gemini API error {code} on {model}: "
                    f"{getattr(e, 'message', e)}") from e
            retry_after, per_day, limit = parse_429(e)
            strikes[model] = strikes.get(model, 0) + 1
            if per_day:
                wait = PER_DAY_COOLDOWN_S
            else:
                # Back off harder each time a model keeps refusing, so a
                # spent bucket is not hammered every single request.
                wait = max(retry_after, 5.0) * (2 ** (strikes[model] - 1))
            wait = min(wait, MAX_COOLDOWN_S)
            cooldown[model] = time.monotonic() + wait
            log.warning(
                "%s out of quota%s — resting it %.0f min, trying next model",
                model,
                f" (free-tier cap {limit}/day)" if limit and per_day else "",
                wait / 60)
            soonest = (cooldown[model] if soonest is None
                       else min(soonest, cooldown[model]))
            continue
        except TranscriptionError:
            raise                   # already a clean message; don't rewrap
        except Exception as e:      # timeouts, DNS, ...
            raise TranscriptionError(
                f"Gemini {what} failed on {model}: {e}") from e

    wait_s = max(0.0, (soonest or 0.0) - time.monotonic())
    raise RateLimitError(
        f"all {len(models)} Gemini models are out of free-tier quota "
        f"(retry in ~{wait_s / 60:.0f} min)"
        + ("" if tried else " — all still resting from earlier 429s"),
        retry_after=wait_s, per_day=True)


# ------------------------------------------------ the REST client (5.6)
#
# What the google-genai SDK used to do, done by hand over net.request with
# secret="gemini": one POST per generateContent, the key in x-goog-api-key
# (net.py attaches it by name; nothing here ever sees the value), the base
# URL net.GEMINI_BASE_URL and nothing else. The SDK read GOOGLE_API_KEY
# from the environment on its own, hid its transport from the chokepoint
# and weighed 50 MB in the wheelhouse; this is ~100 lines and one row in
# network.log per call (D12, D19).

#: Google's cap on a request whose parts are inline (base64 in the JSON):
#: 20 MB in all. 16 kHz mono 16-bit is ~32 KB a second and base64 adds a
#: third, so a single dictation fits up to roughly seven minutes.
INLINE_CAP_BYTES = 20 * 1024 * 1024


class APIError(Exception):
    """A non-2xx answer from generativelanguage.googleapis.com: the status
    code, Google's `error.message`, and the parsed body under `details`
    (`{"error": {"details": [...]}}`) — the shape parse_429 reads."""

    def __init__(self, code: int, message: str, details: dict | None = None,
                 model: str = ""):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or {}
        self.model = model


def text_part(text: str) -> dict:
    return {"text": str(text)}


def blob_part(data: bytes, mime_type: str) -> dict:
    """An inline part: audio or an image, base64 in the JSON."""
    import base64
    return {"inlineData": {"mimeType": mime_type,
                           "data": base64.b64encode(data).decode("ascii")}}


def inline_size(data: bytes) -> int:
    """What `data` weighs once it is base64 inside the request."""
    return (len(data) + 2) // 3 * 4


def thinking_config(model: str, cache: dict[str, str]) -> dict | None:
    """The `thinkingConfig` this model accepts, or None once a 400 taught
    us it takes neither knob ("none" in the cache)."""
    style = thinking_style(model, cache)
    if style == "budget":
        return {"thinkingBudget": 0}
    if style == "level":
        return {"thinkingLevel": "low"}
    return None


def text_of(response: dict) -> str | None:
    """The answer's text — every text part of the first candidate joined —
    or None when there is no candidate with content."""
    try:
        parts = response["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return None
    texts = [p["text"] for p in parts if isinstance(p, dict) and "text" in p]
    return "".join(texts) if texts else None


def finish_reason(response: dict) -> str:
    try:
        return str(response["candidates"][0].get("finishReason") or "")
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""


def _error_from(status: int, body: bytes, model: str) -> APIError:
    import json
    try:
        details = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        details = {}
    err = details.get("error") if isinstance(details, dict) else None
    message = (str(err.get("message")) if isinstance(err, dict) and err.get("message")
               else body.decode("utf-8", "replace")[:300] or f"HTTP {status}")
    return APIError(status, message, details if isinstance(details, dict) else {},
                    model)


class Client:
    """generateContent and the model catalog, for one purpose and timeout.

    `purpose` is the word net.py logs for every call this client makes
    (transcribe, translate, ask-screen, ...); the secret is always the
    Gemini key by NAME. Construction touches nothing; the constructors
    that build one have already passed the consent gate and checked the
    key exists (apikey.find_api_key)."""

    def __init__(self, purpose: str, timeout_s: float):
        self.purpose = purpose
        self.timeout_s = float(timeout_s)

    def generate(self, model: str, contents: list[dict], *,
                 system: str | None = None, temperature: float | None = None,
                 thinking: dict[str, str] | None = None) -> dict:
        """One POST models/<model>:generateContent. `contents` is a list of
        turns (`{"role": "user"|"model", "parts": [...]}`); a list of bare
        parts is taken as one user turn. The thinking knob comes from
        `thinking` (the caller's per-model cache): a 400 with the knob
        set retries once without it and remembers "none" for the model —
        an unknown future model must not be lost over a knob."""
        if contents and isinstance(contents[0], dict) and "parts" not in contents[0]:
            contents = [{"role": "user", "parts": list(contents)}]
        payload: dict = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        gen: dict = {}
        if temperature is not None:
            gen["temperature"] = temperature
        knob = thinking_config(model, thinking) if thinking is not None else None
        if knob:
            gen["thinkingConfig"] = knob
        if gen:
            payload["generationConfig"] = gen
        try:
            return self._post(model, payload)
        except APIError as e:
            if e.code == 400 and knob and thinking is not None \
                    and thinking.get(model) != "none":
                log.info("%s rejected the thinking setting — retrying "
                         "without it (slower, still correct)", model)
                thinking[model] = "none"
                gen.pop("thinkingConfig", None)
                if not gen:
                    payload.pop("generationConfig", None)
                return self._post(model, payload)
            raise

    def _post(self, model: str, payload: dict) -> dict:
        import json

        import net

        url = f"{net.GEMINI_BASE_URL}v1beta/models/{model}:generateContent"
        status, _headers, body = net.post_json(
            url, self.purpose, payload, secret="gemini",
            timeout_s=self.timeout_s)
        if status != 200:
            raise _error_from(status, body, model)
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError as e:
            raise APIError(status, f"not JSON: {e}", {}, model) from None

    def list_models(self) -> list[str]:
        """GET models: every id the key can see, without the `models/`
        prefix — the key test and the drift oracle (5.7)."""
        import json

        import net

        status, _headers, body = net.request(
            "GET", f"{net.GEMINI_BASE_URL}v1beta/models?pageSize=200",
            "catalog", secret="gemini", timeout_s=self.timeout_s)
        if status != 200:
            raise _error_from(status, body, "")
        data = json.loads(body.decode("utf-8"))
        names = []
        for m in data.get("models", []):
            name = str(m.get("name", ""))
            names.append(name[7:] if name.startswith("models/") else name)
        return names
