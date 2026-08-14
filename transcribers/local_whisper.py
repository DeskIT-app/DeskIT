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
- It also HALLUCINATES A TAIL: the decoder runs past the end of real
  speech and keeps producing fluent text from its training distribution.
  Because this fine-tune was trained on Knesset protocols, what comes out
  is parliamentary — observed live 2026-08-12, a dictation about adding
  cities to an app ended "...אדוני היושב-ראש, חברי הכנסת". Two defences,
  neither of which changes good transcriptions (measured): tightened
  decoder guards, and a tail-only filter for that boilerplate. Silence
  alone does NOT trigger it — that was tested and ruled out; VAD strips
  silence and clicks and the output is empty.
- The first construction downloads ~1.6 GB into the Hugging Face cache; the
  app therefore builds this lazily, only when it is actually needed.
"""
from __future__ import annotations

import logging
import math
import re
import os
import struct
import sys
import wave
from io import BytesIO
from pathlib import Path

import cleanup as cleanup_mod

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


def _decode_pcm(wav_bytes: bytes):
    """WAV bytes -> mono float32 at 16 kHz, which is what detect_language
    wants. Returns None if the clip is not the shape the recorder produces,
    so detection is simply skipped rather than raising."""
    try:
        import numpy as np
        with wave.open(BytesIO(wav_bytes), "rb") as w:
            if w.getsampwidth() != 2 or w.getframerate() != 16000:
                return None
            data = np.frombuffer(w.readframes(w.getnframes()),
                                 dtype=np.int16)
            if w.getnchannels() == 2:
                data = data.reshape(-1, 2).mean(axis=1)
        return (data.astype("float32") / 32768.0)
    except Exception:
        return None


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

    def _load(self, model_name: str):
        """Second model, loaded lazily and sharing the device we settled on."""
        from faster_whisper import WhisperModel
        compute = "float16" if self.device == "cuda" else "int8"
        log.info("loading English model %s on %s...", model_name, self.device)
        return WhisperModel(model_name, device=self.device,
                            compute_type=compute)

    def _pick_language(self, audio) -> str:
        """Detect the language, but bias hard towards Hebrew.

        Two measured facts drive this (2026-08-12):

        1. The ivrit fine-tune CANNOT detect language — it answers
           "he" with probability 1.00 for everything, including pure
           English. So detection must run on the general model, never on
           the Hebrew one.
        2. The general model, left to decide freely, mangles very short
           Hebrew: 3 of 15 one-second clips came back Portuguese, Russian
           and Dutch. Every such failure was low-confidence (0.16-0.73)
           while correct Hebrew sat at 0.84-1.00, and English was 1.00.

        Hence: English only when the general model is confident, Hebrew for
        everything else. Hebrew is what gets spoken here almost always, and
        a transliterated English word is a far smaller loss than a Hebrew
        sentence rendered as Russian.
        """
        detector = self._english
        if detector is None:
            return self._language
        try:
            lang, prob, _ = detector.detect_language(audio=audio,
                                                     vad_filter=True)
        except Exception as e:
            log.debug("language detection failed (%s) — using Hebrew", e)
            return self._language
        if lang == "en" and prob >= self._english_threshold:
            log.info("detected English (%.2f) — using the general model",
                     prob)
            return "en"
        if lang != self._language:
            log.info("detected %s (%.2f) — below the bar, using %s", lang,
                     prob, self._language)
        return self._language

    def __init__(self, model: str, language: str, device: str = "auto",
                 cleanup: bool = True, extra_fillers: tuple = (),
                 english_model: str = "", english_threshold: float = 0.8,
                 initial_prompt: str = "", guard_hallucinations: bool = True,
                 boilerplate: tuple = cleanup_mod.PARLIAMENTARY_BOILERPLATE,
                 hotwords=None):
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
        # Whisper transcribes but does not tidy; Gemini's prompt does both.
        # Without this, moving to the local backend visibly regresses the
        # output on real dictation (fillers, restarted sentences).
        self._cleanup = cleanup
        self._fillers = cleanup_mod.DEFAULT_FILLERS + tuple(extra_fillers)
        # The Hebrew fine-tune transliterates short pure-English utterances
        # ("Should it work?" -> "שיידי וורק"). A general model handles those
        # perfectly, so English is routed to one when clearly detected.
        self._english_model_name = english_model
        self._english_threshold = english_threshold
        self._english = None
        # Without this the decoder drops the English half of a mixed
        # sentence outright; with it, both halves survive and Hebrew-only
        # accuracy improves too (10.8% -> 9.6% WER, measured).
        self._initial_prompt = initial_prompt or None
        # The learned vocabulary (vocab.py), and the reason it is a CALLABLE
        # rather than a string: it changes every time the user corrects
        # something, and this object outlives any one dictation.
        #
        # It is a separate parameter from initial_prompt because the two
        # reach different parts of the audio. Measured 2026-08-14 by spying
        # on WhisperModel.get_prompt over 125 s of real speech: with
        # condition_on_previous_text=False (set below), initial_prompt is
        # dropped after the FIRST 30-second window — it survived in 1 of 5
        # windows — while hotwords is re-injected per window and survived in
        # 6 of 6. Long dictations are exactly where names garble worst, so
        # the vocabulary has to travel by the mechanism that gets there.
        # They coexist: the prompt becomes " HOTWORDS INITIAL_PROMPT".
        self._hotwords = hotwords
        self._boilerplate = tuple(boilerplate)
        self.last_removed: list[str] = []
        # Whisper's own hallucination guards. The defaults are permissive
        # (no_speech 0.6 / logprob -1.0 / compression 2.4) and let a
        # low-confidence trailing segment through; these tighten all three
        # and turn on the purpose-built one, which needs word timestamps.
        # Measured 2026-08-12 against the current settings: byte-identical
        # output on good audio, ~8% slower (≈0.1 s on a 40 s dictation).
        self._guards = dict(
            no_speech_threshold=0.4,
            log_prob_threshold=-0.7,
            compression_ratio_threshold=2.0,
            word_timestamps=True,
            hallucination_silence_threshold=2.0,
            # Against token loops: a vocalised hesitation became 222 ה's,
            # and everything SPOKEN AFTER it was eaten (2026-08-13, twice).
            # Measured byte-identical on clean audio; the loop itself
            # could not be reproduced synthetically, so this is the
            # standard knob for the mechanism, not a proven cure.
            repetition_penalty=1.15,
        ) if guard_hallucinations else {}

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

        # Loaded eagerly, not on demand: it is the language DETECTOR for
        # every utterance, not just a backup transcriber, so a lazy load
        # would make the first dictation after login pay for it.
        if self._english_model_name:
            try:
                self._english = self._load(self._english_model_name)
            except Exception as e:
                log.warning("English model unavailable (%s) — Hebrew only; "
                            "short English phrases may be transliterated", e)
                self._english = None

    def _current_hotwords(self) -> str | None:
        """Resolve the vocabulary for this one request.

        Never fatal: a broken vocabulary must cost accuracy, not dictation.
        faster-whisper ignores hotwords when `prefix` is set (it is not
        here) and truncates the string at 223 tokens.
        """
        source = self._hotwords
        if source is None:
            return None
        try:
            text = source() if callable(source) else str(source)
        except Exception as e:
            log.warning("could not build the hotword list (%s) — "
                        "transcribing without it", e)
            return None
        return text.strip() or None

    def transcribe(self, wav_bytes: bytes,
                   language: str | None = None) -> str:
        """`language` is the caller's explicit choice (a dedicated hotkey).
        It always wins — detection only runs when nothing was specified."""
        try:
            model, chosen = self._model, self._language
            if language == "en" and self._english is not None:
                model, chosen = self._english, "en"
            elif language in (None, "") and self._english is not None:
                audio = _decode_pcm(wav_bytes)
                if audio is not None and self._pick_language(audio) == "en":
                    model, chosen = self._english, "en"
            elif language:
                chosen = language

            segments, _info = model.transcribe(
                BytesIO(wav_bytes),
                language=chosen,     # never None: see _pick_language
                vad_filter=True,
                beam_size=5,
                condition_on_previous_text=False,
                # The Hebrew prompt would only confuse the English model.
                initial_prompt=None if chosen == "en"
                else self._initial_prompt,
                # Hotwords go to BOTH models, unlike initial_prompt. That
                # one is a Hebrew sentence and means nothing to a general
                # English model; this is a list of names ("Expo Go", "EAS"),
                # and an English utterance is if anything the MORE likely
                # place for them to be spoken.
                hotwords=self._current_hotwords(),
                **self._guards,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
        except Exception as e:
            raise TranscriptionError(f"local transcription failed: {e}") from e

        self.last_removed = []
        # A long letter-run means the decoder looped — and while it loops,
        # the audio keeps advancing, so words spoken during and after it
        # are usually GONE, not garbled. Cleanup below deletes the run;
        # nothing can restore the words. The least bad thing is to say so
        # immediately instead of letting the loss be discovered in reading.
        self.last_warning = None
        loop = re.search(r"([א-ת])\1{11,}", text)
        if loop:
            self.last_warning = ("the model looped mid-recording — words "
                                 "around it may be lost; re-dictate that part")
            log.warning("decoder loop: %d×%s — words spoken during/after "
                        "it are likely missing", len(loop.group(0)),
                        loop.group(1))
        if text.strip(" .,!?").lower() in _HALLUCINATED_SILENCE:
            return ""        # treated as "no speech", same as Gemini
        if self._boilerplate:
            text, removed = cleanup_mod.strip_trailing_boilerplate(
                text, self._boilerplate)
            if removed:
                self.last_removed = removed
                log.warning("dropped hallucinated tail (never spoken, comes "
                            "from the fine-tune's Knesset training data): %s",
                            " | ".join(removed))
        if self._cleanup:
            text = cleanup_mod.clean(text, self._fillers)
        return text
