"""Config loading and validation (config.toml, stdlib tomllib)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

VALID_BACKENDS = ("gemini", "local", "fake")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class AudioConfig:
    sample_rate: int = 16000
    device: int | str | None = None  # None = system default input device


@dataclass(frozen=True)
class GeminiConfig:
    # Free-tier quota is counted per model, so a list is a longer runway:
    # each entry is tried in order and rested when it reports its cap.
    models: tuple[str, ...] = ("gemini-2.5-flash", "gemini-flash-latest",
                               "gemini-2.5-flash-lite",
                               "gemini-flash-lite-latest")
    timeout_s: int = 30

    @property
    def model(self) -> str:
        return self.models[0]


@dataclass(frozen=True)
class FeedbackConfig:
    """The at-the-cursor progress marker.

    Pasted the moment the key is released and replaced by the transcript
    when it arrives, so the text lands where the user was speaking even if
    the request takes 30 seconds or has to be retried.
    """
    placeholder: str = "..."
    enabled: bool = True
    # How long the worker keeps retrying at the cursor before giving up and
    # leaving the recording in the spool for --drain.
    retry_seconds: float = 45.0


@dataclass(frozen=True)
class LocalConfig:
    model: str = "ivrit-ai/whisper-large-v3-turbo-ct2"
    language: str = "he"  # pinned — the ivrit-ai fine-tune broke autodetect
    device: str = "auto"  # auto | cuda | cpu — auto tries the GPU first


@dataclass(frozen=True)
class Config:
    hotkey: str = "right ctrl"
    backend: str = "gemini"
    paste_chord: str = "ctrl+v"
    restore_delay_ms: int = 300
    min_seconds: float = 0.3
    max_seconds: float = 120.0
    audio: AudioConfig = field(default_factory=AudioConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    local: LocalConfig = field(default_factory=LocalConfig)
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    # Fall back to the local backend when every cloud model is out of quota.
    fallback_to_local: bool = True


def _parse_device(raw: str) -> int | str | None:
    raw = raw.strip()
    if not raw:
        return None
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw  # sounddevice matches name substrings


def load(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Bad TOML in {path}: {e}") from e

    audio = data.get("audio", {})
    gemini = data.get("gemini", {})
    local = data.get("local", {})
    feedback = data.get("feedback", {})

    # models = [...] is the current form; model = "..." is still honoured so
    # an older config.toml keeps working.
    if gemini.get("models"):
        models = tuple(str(m).strip() for m in gemini["models"]
                       if str(m).strip())
    elif gemini.get("model"):
        models = (str(gemini["model"]).strip(),)
    else:
        models = GeminiConfig.models

    cfg = Config(
        hotkey=str(data.get("hotkey", Config.hotkey)).strip().lower(),
        backend=str(data.get("backend", Config.backend)).strip().lower(),
        paste_chord=str(data.get("paste_chord", Config.paste_chord)).strip().lower(),
        restore_delay_ms=int(data.get("restore_delay_ms", Config.restore_delay_ms)),
        min_seconds=float(data.get("min_seconds", Config.min_seconds)),
        max_seconds=float(data.get("max_seconds", Config.max_seconds)),
        audio=AudioConfig(
            sample_rate=int(audio.get("sample_rate", AudioConfig.sample_rate)),
            device=_parse_device(str(audio.get("device", ""))),
        ),
        gemini=GeminiConfig(
            models=models,
            timeout_s=int(gemini.get("timeout_s", GeminiConfig.timeout_s)),
        ),
        local=LocalConfig(
            model=str(local.get("model", LocalConfig.model)).strip(),
            language=str(local.get("language", LocalConfig.language)).strip(),
            device=str(local.get("device", LocalConfig.device)).strip().lower(),
        ),
        feedback=FeedbackConfig(
            placeholder=str(feedback.get("placeholder",
                                         FeedbackConfig.placeholder)),
            enabled=bool(feedback.get("enabled", FeedbackConfig.enabled)),
            retry_seconds=float(feedback.get(
                "retry_seconds", FeedbackConfig.retry_seconds)),
        ),
        fallback_to_local=bool(data.get("fallback_to_local",
                                        Config.fallback_to_local)),
    )

    if cfg.backend not in VALID_BACKENDS:
        raise ConfigError(f"backend must be one of {VALID_BACKENDS}, got {cfg.backend!r}")
    if not cfg.hotkey:
        raise ConfigError("hotkey must not be empty")
    if not (0 < cfg.min_seconds < cfg.max_seconds <= 3600):
        raise ConfigError("need 0 < min_seconds < max_seconds <= 3600")
    if cfg.restore_delay_ms < 0:
        raise ConfigError("restore_delay_ms must be >= 0")
    if cfg.audio.sample_rate <= 0:
        raise ConfigError("audio.sample_rate must be positive")
    if not cfg.gemini.models:
        raise ConfigError("gemini.models must list at least one model")
    if cfg.feedback.enabled and not cfg.feedback.placeholder:
        raise ConfigError("feedback.placeholder must not be empty when "
                          "feedback.enabled is true (nothing to erase)")
    if cfg.feedback.retry_seconds < 0:
        raise ConfigError("feedback.retry_seconds must be >= 0")
    if cfg.local.device not in ("auto", "cuda", "cpu"):
        raise ConfigError('local.device must be "auto", "cuda" or "cpu", '
                          f"got {cfg.local.device!r}")
    if not cfg.local.language:
        raise ConfigError("local.language must be pinned (the ivrit-ai "
                          "fine-tune's language autodetect is unreliable)")
    return cfg
