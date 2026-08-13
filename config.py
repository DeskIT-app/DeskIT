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
    # Whisper transcribes only; Gemini also cleans. Without this, the local
    # backend regresses output quality on real (hesitant) dictation.
    cleanup: bool = True
    extra_fillers: tuple[str, ...] = ()
    # Biases the decoder towards Hebrew-with-English-terms, which is how
    # this gets used. Measured 2026-08-12: Hebrew WER 10.8% -> 9.6%, and
    # mixed utterances stopped losing their English half entirely.
    initial_prompt: str = ("שיחה בעברית עם מונחים טכניים באנגלית כמו "
                           "commit, branch, pull request, merge, deploy, "
                           "terminal, repo, bug, feature.")
    # The Hebrew fine-tune transliterates short pure-English utterances.
    # Confident English is routed to a general model instead. "" disables.
    english_model: str = "deepdml/faster-whisper-large-v3-turbo-ct2"
    # Deliberately high: misdetected short Hebrew is far worse than a
    # transliterated English word, and every misdetection measured was
    # low-confidence while correct Hebrew sat at 0.91-0.99.
    english_threshold: float = 0.8
    # Tighten Whisper's own hallucination guards. The library defaults let
    # a low-confidence trailing segment through; measured 2026-08-12, these
    # cost nothing on good audio (identical text, ~8% slower).
    guard_hallucinations: bool = True
    # Drop parliamentary boilerplate stuck to the END of a transcript. The
    # ivrit-ai fine-tune is trained on Knesset protocols and appends them
    # when the decoder runs past the end of real speech.
    drop_trailing_boilerplate: bool = True
    # Your own phrases to treat the same way, e.g. a jingle the model keeps
    # tacking on. Whole phrases only — single common words strip real speech.
    extra_boilerplate: tuple[str, ...] = ()


@dataclass(frozen=True)
class TranslateConfig:
    """The tap-to-translate key: turns text already at the cursor into
    English, in place."""
    target: str = "English"
    # A guard, not a preference. The key selects the whole field when
    # nothing is selected, and in a document editor "the whole field" is
    # the entire document — refusing above this keeps a stray press from
    # replacing a file's worth of text.
    max_chars: int = 5000
    ollama_model: str = "llama3.1:8b"
    ollama_url: str = "http://localhost:11434"
    timeout_s: int = 30
    # Deliberately much larger than timeout_s. Ollama loads the model into
    # VRAM on the first request after it goes idle: measured 2026-08-12,
    # 76 s cold for llama3.1:8b against 2.5 s warm. At 30 s the fallback
    # would time out exactly when it is first needed.
    ollama_timeout_s: int = 150
    copy_chord: str = "ctrl+c"
    select_all_chord: str = "ctrl+a"
    # How long the focused app is given to answer a copy. Chromium inputs
    # answer in well under 50 ms; this is slack for a busy machine.
    settle_ms: int = 120


@dataclass(frozen=True)
class ServerConfig:
    """The phone endpoint: dictate from the phone, transcribe on this GPU.

    Off by default — it opens a socket, and that should be a decision.
    """
    enabled: bool = False
    # "" = 127.0.0.1. Loopback is not a limitation, it is the design:
    # `tailscale serve` proxies to localhost and terminates TLS, so nothing
    # listens where a stranger — or the home LAN — could reach it, and the
    # phone still gets the certificate its browser demands for microphone
    # access. Binding the Tailscale address instead would make the server
    # invisible to `tailscale serve`.
    host: str = ""
    port: int = 8756


@dataclass(frozen=True)
class Config:
    hotkey: str = "right ctrl"
    # A dedicated key beats guessing: language detection scored a Hebrew
    # sentence as "English 0.57" on this user's real microphone. "" = off.
    # Avoid alt (menu activation on release) and shift (FilterKeys at 8 s).
    english_hotkey: str = "f9"
    # Tapped (not held) to translate the selection — or the whole field
    # when nothing is selected — into English. "" = off.
    translate_hotkey: str = ""
    # Tapped WHILE holding the hotkey: locks the recording on, so the
    # hotkey can be released and a long dictation does not mean a long
    # hold. Must be reachable by the hand already on the hotkey, and is
    # swallowed while it acts as the latch — so a key with a job of its own
    # ("left") is fine. "" = off.
    latch_hotkey: str = "left"
    backend: str = "gemini"
    paste_chord: str = "ctrl+v"
    restore_delay_ms: int = 300
    min_seconds: float = 0.3
    max_seconds: float = 120.0
    # The cap once latched. 0 = none: max_seconds guards against a key-up
    # the OS swallowed, and a latched recording has no key-up to lose.
    latch_max_seconds: float = 0.0
    audio: AudioConfig = field(default_factory=AudioConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    local: LocalConfig = field(default_factory=LocalConfig)
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    translate: TranslateConfig = field(default_factory=TranslateConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    # Fall back to the local backend when every cloud model is out of quota.
    fallback_to_local: bool = True
    # Show a small startup window while the models load. Without it a
    # windowless app is indistinguishable from a shortcut that did nothing
    # for the ~25 s it takes, and the natural response is to click again.
    splash: bool = True
    # A small always-on-top dot in the top-right corner: the app is
    # running, and what it is doing. Click-through, because that corner is
    # the close button of every maximised window.
    indicator: bool = True


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
    translate = data.get("translate", {})
    server = data.get("server", {})

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
        english_hotkey=str(data.get("english_hotkey",
                                    Config.english_hotkey)).strip().lower(),
        translate_hotkey=str(data.get(
            "translate_hotkey", Config.translate_hotkey)).strip().lower(),
        latch_hotkey=str(data.get("latch_hotkey",
                                  Config.latch_hotkey)).strip().lower(),
        backend=str(data.get("backend", Config.backend)).strip().lower(),
        paste_chord=str(data.get("paste_chord", Config.paste_chord)).strip().lower(),
        restore_delay_ms=int(data.get("restore_delay_ms", Config.restore_delay_ms)),
        min_seconds=float(data.get("min_seconds", Config.min_seconds)),
        max_seconds=float(data.get("max_seconds", Config.max_seconds)),
        latch_max_seconds=float(data.get("latch_max_seconds",
                                         Config.latch_max_seconds)),
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
            cleanup=bool(local.get("cleanup", LocalConfig.cleanup)),
            extra_fillers=tuple(str(f).strip()
                                for f in local.get("extra_fillers", ())
                                if str(f).strip()),
            initial_prompt=str(local.get("initial_prompt",
                                         LocalConfig.initial_prompt)),
            english_model=str(local.get("english_model",
                                        LocalConfig.english_model)).strip(),
            english_threshold=float(local.get(
                "english_threshold", LocalConfig.english_threshold)),
            guard_hallucinations=bool(local.get(
                "guard_hallucinations", LocalConfig.guard_hallucinations)),
            drop_trailing_boilerplate=bool(local.get(
                "drop_trailing_boilerplate",
                LocalConfig.drop_trailing_boilerplate)),
            extra_boilerplate=tuple(str(p).strip()
                                    for p in local.get("extra_boilerplate", ())
                                    if str(p).strip()),
        ),
        feedback=FeedbackConfig(
            placeholder=str(feedback.get("placeholder",
                                         FeedbackConfig.placeholder)),
            enabled=bool(feedback.get("enabled", FeedbackConfig.enabled)),
            retry_seconds=float(feedback.get(
                "retry_seconds", FeedbackConfig.retry_seconds)),
        ),
        translate=TranslateConfig(
            target=str(translate.get("target",
                                     TranslateConfig.target)).strip(),
            max_chars=int(translate.get("max_chars",
                                        TranslateConfig.max_chars)),
            ollama_model=str(translate.get(
                "ollama_model", TranslateConfig.ollama_model)).strip(),
            ollama_url=str(translate.get(
                "ollama_url", TranslateConfig.ollama_url)).strip(),
            timeout_s=int(translate.get("timeout_s",
                                        TranslateConfig.timeout_s)),
            ollama_timeout_s=int(translate.get(
                "ollama_timeout_s", TranslateConfig.ollama_timeout_s)),
            copy_chord=str(translate.get(
                "copy_chord", TranslateConfig.copy_chord)).strip().lower(),
            select_all_chord=str(translate.get(
                "select_all_chord",
                TranslateConfig.select_all_chord)).strip().lower(),
            settle_ms=int(translate.get("settle_ms",
                                        TranslateConfig.settle_ms)),
        ),
        server=ServerConfig(
            enabled=bool(server.get("enabled", ServerConfig.enabled)),
            host=str(server.get("host", ServerConfig.host)).strip(),
            port=int(server.get("port", ServerConfig.port)),
        ),
        fallback_to_local=bool(data.get("fallback_to_local",
                                        Config.fallback_to_local)),
        splash=bool(data.get("splash", Config.splash)),
        indicator=bool(data.get("indicator", Config.indicator)),
    )

    if cfg.backend not in VALID_BACKENDS:
        raise ConfigError(f"backend must be one of {VALID_BACKENDS}, got {cfg.backend!r}")
    if not cfg.hotkey:
        raise ConfigError("hotkey must not be empty")
    if cfg.english_hotkey and cfg.english_hotkey == cfg.hotkey:
        raise ConfigError("english_hotkey must differ from hotkey "
                          f"(both are {cfg.hotkey!r})")
    if cfg.translate_hotkey:
        for other, label in ((cfg.hotkey, "hotkey"),
                             (cfg.english_hotkey, "english_hotkey")):
            if other and cfg.translate_hotkey == other:
                raise ConfigError(
                    f"translate_hotkey must differ from {label} (both are "
                    f"{other!r}) — one key cannot both record and translate")
        if cfg.translate.max_chars <= 0:
            raise ConfigError("translate.max_chars must be positive")
        if cfg.translate.settle_ms < 0:
            raise ConfigError("translate.settle_ms must be >= 0")
        if not cfg.translate.target:
            raise ConfigError("translate.target must name a language")
        if not cfg.translate.ollama_model:
            raise ConfigError("translate.ollama_model must not be empty (it "
                              "is the fallback when Gemini quota is spent)")
    if cfg.latch_hotkey:
        for other, label in ((cfg.hotkey, "hotkey"),
                             (cfg.english_hotkey, "english_hotkey"),
                             (cfg.translate_hotkey, "translate_hotkey")):
            if other and cfg.latch_hotkey == other:
                raise ConfigError(
                    f"latch_hotkey must differ from {label} (both are "
                    f"{other!r}) — one key cannot mean two things")
        if cfg.latch_hotkey == "esc":
            raise ConfigError("latch_hotkey cannot be 'esc' — esc discards a "
                              "locked recording")
    if not (0 < cfg.min_seconds < cfg.max_seconds <= 3600):
        raise ConfigError("need 0 < min_seconds < max_seconds <= 3600")
    if cfg.latch_max_seconds < 0:
        raise ConfigError("latch_max_seconds must be >= 0 (0 = no cap)")
    if 0 < cfg.latch_max_seconds <= cfg.min_seconds:
        raise ConfigError("latch_max_seconds must be 0 (no cap) or longer "
                          "than min_seconds")
    if cfg.restore_delay_ms < 0:
        raise ConfigError("restore_delay_ms must be >= 0")
    if cfg.server.enabled and not (0 < cfg.server.port < 65536):
        raise ConfigError(f"server.port is out of range: {cfg.server.port}")
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
    if not (0.0 < cfg.local.english_threshold <= 1.0):
        raise ConfigError("local.english_threshold must be in (0, 1]")
    return cfg
