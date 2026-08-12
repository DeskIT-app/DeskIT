"""Backend B: local transcription with faster-whisper + the ivrit-ai
Hebrew fine-tune. No network, no quota, no per-request cost.

This exists because the cloud backend has a hard free-tier ceiling
(measured 2026-08-12: 20 requests/day/model). Rotating models stretches
that, but only a local model removes the ceiling — so this is the floor the
app falls back to when every cloud model is spent, and dictation keeps
working offline.

Notes that cost real time to discover, keep them:

- The ivrit-ai fine-tune DEGRADED Whisper's language detection. language
  must always be pinned to "he"; never let it auto-detect. The model is
  Hebrew-only — English dictation would need a different model.
- Whisper only transcribes. Gemini also cleans up (fillers, self-
  corrections, digits) via its system prompt, so local output is rawer.
  `condition_on_previous_text=False` at least stops it looping on
  repetitions, which Whisper is prone to on hesitant speech.
- The first construction downloads ~1.6 GB into the Hugging Face cache; the
  app therefore builds this lazily, only when it is actually needed.
"""
from __future__ import annotations

import logging
import math
import os
import struct
import sys
import wave
from io import BytesIO
from pathlib import Path

from .base import TranscriptionError

log = logging.getLogger("app")


def _register_cuda_dlls() -> None:
    """Make the pip-installed CUDA libraries findable.

    CTranslate2 loads cublas64_12.dll / cudnn64_9.dll through the plain
    Windows DLL search path, but pip puts them under
    site-packages/nvidia/*/bin, which is not on it. Without this the model
    loads on "cuda" quite happily and then dies on the first transcription
    with "Library cublas64_12.dll is not found".
    """
    if os.name != "nt":
        return
    roots = [Path(p) / "nvidia" for p in sys.path if p.endswith("site-packages")]
    roots.append(Path(sys.prefix) / "Lib" / "site-packages" / "nvidia")
    found: list[str] = []
    for root in roots:
        if root.is_dir():
            found += [str(d) for d in sorted(root.glob("*/bin"))]
    if not found:
        return
    # add_dll_directory only helps callers that use LoadLibraryEx with the
    # search-path flags; CTranslate2 uses plain LoadLibrary, which resolves
    # against PATH — so set both and let whichever applies win.
    for bin_dir in found:
        try:
            os.add_dll_directory(bin_dir)
        except OSError:
            pass
    os.environ["PATH"] = os.pathsep.join(
        dict.fromkeys(found + os.environ.get("PATH", "").split(os.pathsep)))
    log.debug("registered %d CUDA library dirs", len(found))


def _silence_wav(seconds: float = 0.4, rate: int = 16000) -> bytes:
    """A tiny WAV for the warm-up inference."""
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(rate * seconds))
    return buf.getvalue()

# Whisper hallucinates confident text on silence; these are the stock
# phrases it emits for an empty clip.
_HALLUCINATED_SILENCE = {
    "תודה", "תודה רבה", "תודה שצפיתם", "כתוביות", "בהצלחה",
    "thank you", "thanks for watching", "you",
}


class LocalWhisperTranscriber:
    name = "local"

    def __init__(self, model: str, language: str, device: str = "auto"):
        _register_cuda_dlls()
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise TranscriptionError(
                "the local backend needs faster-whisper: run "
                r".venv\Scripts\pip install faster-whisper") from e

        if not language:
            raise TranscriptionError(
                "local.language must be pinned (the ivrit-ai fine-tune's "
                "language autodetect is unreliable)")
        self._language = language

        attempts = ([("cuda", "float16"), ("cpu", "int8")]
                    if device == "auto" else
                    [(device, "float16" if device == "cuda" else "int8")])
        last: Exception | None = None
        for dev, compute in attempts:
            try:
                candidate = WhisperModel(model, device=dev,
                                         compute_type=compute)
                # Constructing on "cuda" succeeds even when the CUDA math
                # libraries are missing — the failure only surfaces on the
                # first real inference. Force that here, so a broken GPU
                # falls back to CPU now instead of breaking every dictation.
                list(candidate.transcribe(BytesIO(_silence_wav()),
                                          language=language)[0])
            except Exception as e:                 # no GPU, no kernels, OOM
                last = e
                log.info("local model cannot use %s (%s) — %s", dev, compute,
                         str(e).splitlines()[0][:120])
                continue
            self._model = candidate
            self.device = dev
            log.info("local model %s ready on %s (%s)", model, dev, compute)
            break
        else:
            raise TranscriptionError(
                f"could not load the local model {model!r}: {last}")

    def transcribe(self, wav_bytes: bytes) -> str:
        try:
            segments, _info = self._model.transcribe(
                BytesIO(wav_bytes),
                language=self._language,      # pinned — never autodetect
                vad_filter=True,
                beam_size=5,
                condition_on_previous_text=False,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
        except Exception as e:
            raise TranscriptionError(f"local transcription failed: {e}") from e

        if text.strip(" .,!?").lower() in _HALLUCINATED_SILENCE:
            return ""        # treated as "no speech", same as Gemini
        return text
