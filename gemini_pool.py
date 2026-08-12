"""Shared Gemini plumbing: 429 parsing and model rotation.

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


def apply_thinking(cfg, model: str, cache: dict[str, str]):
    """Attach the thinking knob this model accepts to a config object."""
    from google.genai import types

    style = thinking_style(model, cache)
    if style == "budget":
        cfg.thinking_config = types.ThinkingConfig(thinking_budget=0)
    elif style == "level":
        cfg.thinking_config = types.ThinkingConfig(thinking_level="low")
    return cfg


def rotate(models: list[str], cooldown: dict[str, float],
           strikes: dict[str, int], attempt, what: str = "request") -> str:
    """Run `attempt(model)` against the first model that is not resting.

    A model that answers 429 is rested and the next one is tried, which
    turns a hard stop after 20 requests into a much longer runway at no
    cost. Raises RateLimitError only once EVERY model is spent, so callers
    can treat that as "the cloud is done for today" and fall back locally.
    """
    from google.genai import errors

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
        except errors.APIError as e:
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
