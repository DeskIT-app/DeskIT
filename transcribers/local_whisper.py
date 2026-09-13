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


DETECT_RATE = 16000        # what detect_language's mel front-end expects


def _decode_pcm(wav_bytes: bytes):
    """WAV bytes -> mono float32 at 16 kHz, which is what detect_language
    wants. None only when the clip cannot be decoded at all.

    THIS USED TO RETURN None FOR ANY RATE BUT 16 kHz, and that one line
    cost a day of dictation on 2026-09-05. Switching the microphone to the
    Arctis 7 Chat headset was enough: the driver refuses 16 kHz shared-mode
    capture, so Recorder falls back to the device's own rate (recorder.py)
    and every clip recorded after 15:14 was 48 kHz. This returned None for
    all of them, transcribe() reads that as "no opinion", and the language
    stays pinned at "he" — so the Hebrew-only ivrit fine-tune was handed
    English speech and wrote fluent Hebrew nobody had said. Measured on the
    real recording: 16.8 s of "So have you finished? Please write me a
    summary in Hebrew..." shipped as "אז האם אתם עשרים? בבקשה תכניסי לי
    להגיד משהו ביברו...". Nothing anywhere said why, because a skipped
    detection was silent: the only trace was that "detected English" stops
    appearing in app.log at 15:13:40 and never comes back.

    So: resample rather than give up. The recorder's own 16 kHz mono keeps
    the plain `wave` fast path; anything else goes through PyAV, which
    ships with faster-whisper and is already what server.py does with
    whatever shape the phone recorded in.
    """
    try:
        import numpy as np
        with wave.open(BytesIO(wav_bytes), "rb") as w:
            if w.getsampwidth() == 2 and w.getframerate() == DETECT_RATE:
                data = np.frombuffer(w.readframes(w.getnframes()),
                                     dtype=np.int16)
                if w.getnchannels() == 2:
                    data = data.reshape(-1, 2).mean(axis=1)
                return (data.astype("float32") / 32768.0)
    except Exception:
        pass                    # not a WAV, or not one `wave` can open
    try:
        from faster_whisper.audio import decode_audio
        return decode_audio(BytesIO(wav_bytes), sampling_rate=DETECT_RATE)
    except Exception as e:
        log.warning("cannot read this clip for language detection (%s) — "
                    "it stays in the pinned language", e)
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

# A run this long is a decoder loop in either script — no word anywhere
# has twelve of the same letter in a row. Hebrew observed 2026-08-13 (222
# ה's); Latin on 2026-09-05, when a 73-character "Xxxxx…" came out of a
# 57 s dictation. The Hebrew-only pattern this replaces meant that one
# raised no warning at all, so the loss was found by reading.
_LOOP_RUN = re.compile(r"([א-תA-Za-z])\1{11,}")


def _looped_seconds(words) -> float:
    """How much of the recording the loop ate, from the word timings.

    A loop comes out as ONE token and the decoder does not return until it
    stops, so the gap between the end of the last real word and the end of
    that token is speech that was never written down. Measured 2026-09-05:
    'ביטחון' ended at 27.26 s, the run ended at 56.26 s, and all 29 s in
    between were gone. 0.0 when there are no timings to say.
    """
    for index, word in enumerate(words):
        if index and _LOOP_RUN.search(str(word[0] or "")):
            try:
                return max(0.0, float(word[2]) - float(words[index - 1][2]))
            except (TypeError, ValueError, IndexError):
                return 0.0
    return 0.0


# Whisper hallucinates confident text on silence; these are the stock
# phrases it emits for an empty clip.
_HALLUCINATED_SILENCE = {
    "תודה", "תודה רבה", "תודה שצפיתם", "כתוביות", "בהצלחה",
    "thank you", "thanks for watching", "you",
}


def hallucination_guards(enabled: bool) -> dict:
    """Whisper's own guards, tightened. {} when they are switched off.

    The defaults are permissive (no_speech 0.6 / logprob -1.0 / compression
    2.4) and let a low-confidence trailing segment through; these tighten
    all three and turn on the purpose-built one.

    The 2026-08-12 note here read "byte-identical output on good audio, ~8%
    slower (≈0.1 s on a 40 s dictation)". BOTH HALVES WERE WRONG, and they
    were wrong because the corpus they were measured on had no long clips
    in it. Tightening the thresholds pushes windows onto faster-whisper's
    temperature fallback ladder, which SAMPLES — so the output was not
    byte-identical, it was not even reproducible run to run, and a forced
    window costs up to 6 decodes instead of 1. See temperature below, which
    is the fix and which restores both properties.

    A module-level function rather than a literal inside __init__ so a test
    can assert on it without putting a model on the GPU. Nothing pinned it
    before, and word_timestamps in particular is easy to mistake for a
    debugging leftover: hallucination_silence_threshold does not work
    without it.
    """
    if not enabled:
        return {}
    return dict(
        no_speech_threshold=0.4,
        log_prob_threshold=-0.7,
        compression_ratio_threshold=2.0,
        # No temperature ladder. The three tightened thresholds above reject
        # far more windows than stock does, and every rejection sends that
        # window down faster-whisper's fallback ladder (0.2 ... 1.0), which
        # SAMPLES. So the same audio at the same settings did not produce
        # the same text: one 25.2 s clip gave 5 DISTINCT transcripts in 5
        # runs, scoring 4, 9, 16, 33 and 3 word edits against 64 true words.
        # That is the mechanism behind "words I said are missing" — a
        # sampled window wins the fallback and its words are gone. Pinning
        # temperature makes the decode deterministic and, because a forced
        # window costs up to 6 decodes instead of 1, much faster.
        # Measured 2026-08-28, interleaved A/B over all 50 clips in recent\
        # (2478 s of audio): 144.7 s -> 59.8 s of decode, -58.7%, RTF
        # 0.058 -> 0.024; identical text on 42/50 clips, and against the
        # study-verified reading the pinned arm was CLOSER (197 edits vs
        # 224 over 2254 words). 0 decoder loops in either arm.
        # The ladder is Whisper's standard escape from a repetition loop,
        # which this repo has been bitten by twice — repetition_penalty
        # below, collapse_char_runs and the loop warning all remain.
        temperature=[0.0],
        word_timestamps=True,
        hallucination_silence_threshold=2.0,
        # Against token loops: a vocalised hesitation became 222 ה's, and
        # everything SPOKEN AFTER it was eaten (2026-08-13, twice).
        # Measured byte-identical on clean audio; the loop itself could not
        # be reproduced synthetically, so this is the standard knob for the
        # mechanism, not a proven cure.
        repetition_penalty=1.15,
    )


class LocalWhisperTranscriber:
    name = "local"

    # Class-level default, not just an __init__ one: the test suite builds
    # instances with __new__ to reach single methods without loading a
    # model, and those must transcribe too.
    _beam_size = 5

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

        Re-measured 2026-08-20 over the 50 real recordings in recent\\, this
        time comparing what each model ACTUALLY produced rather than trusting
        the label: 8 clips crossed the 0.8 bar and all 8 were genuinely
        English (6 strictly better this way — "מקמיני" -> "Mac mini" — and 2
        identical), while every Hebrew recording stayed Hebrew. That is what
        allows the main hotkey to leave the language unset by default; see
        Config.auto_language.
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
                 hotwords=None, beam_size: int = 5):
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
        # Decoder beam width. 5 is what this always ran; [local] beam_size
        # exists so a faster width (2, or 1 = greedy) can be measured with
        # --benchmark and kept only if the WER trade is worth it.
        self._beam_size = max(1, int(beam_size))
        self.last_removed: list[str] = []
        # The decoder's own opinion of every word of the LAST live
        # transcription: (word, start, end, probability). Read by main.py
        # right after the call and kept in the recording's sidecar for
        # the second reading (review.py), which uses it to tell an
        # invented ending from a real one. Instance state like
        # last_removed, and for the same reason the study decodes never
        # touch it.
        self.last_words: list[tuple] = []
        self._guards = hallucination_guards(guard_hallucinations)

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
                self._warm_detector()
            except Exception as e:
                log.warning("English model unavailable (%s) — Hebrew only; "
                            "short English phrases may be transliterated", e)
                self._english = None

    def _warm_detector(self) -> None:
        """Pay the first-inference cost at startup, not on the first
        dictation.

        Detection is a full encoder pass, and the first one on a freshly
        loaded model costs ~2 s against ~0.18 s warm (measured 2026-08-20
        over the recordings in recent\\). With the language left unset by
        default, that first pass falls on a real dictation — so it is spent
        here instead, where the user is already waiting for the models.
        Silence is enough: nothing is read from the result.

        Both passes matter. vad_filter=True loads Silero, which is its own
        first-call cost; vad_filter=False guarantees the encoder actually
        runs, because VAD strips silence down to nothing. Never fatal — a
        warm-up that fails only means the first dictation is slow.
        """
        audio = _decode_pcm(_silence_wav())
        if audio is None or self._english is None:
            return
        for vad in (True, False):
            try:
                self._english.detect_language(audio=audio, vad_filter=vad)
            except Exception as e:
                log.debug("detector warm-up (vad=%s) skipped: %s", vad, e)

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

    def study_decode(self, wav_bytes: bytes, *, beam_size: int | None = None,
                     hotwords: str | None = None, temperature=None,
                     general: bool = False) -> str:
        """One EXTRA opinion about a recording, for the study pass
        (study.py). Same guards, same tail-boilerplate and filler cleanup
        as the live path — the candidates must live in the same text space
        as the transcript they are compared against.

        Differences from transcribe(), each deliberate:
        - no hotwords unless asked: the study wants opinions UNBIASED by
          the learned vocabulary, so a hotword the live pass emitted
          unbidden cannot confirm itself;
        - `general=True` decodes on the second resident model ([local]
          english_model, a general multilingual fine-tune) with no Hebrew
          initial_prompt and with the language DETECTED rather than pinned
          — different training data, independent errors, and an opinion
          about which language this was at all;
        - touches NO instance state (last_removed, last_warning): those
          slots belong to the live path, which may be serving a dictation
          on another thread while this runs.
        """
        model = self._model
        chosen = self._language
        if general:
            if self._english is None:
                raise TranscriptionError(
                    "no general model loaded for a second opinion")
            model = self._english
            # ...and it is allowed to disagree about the LANGUAGE, which
            # is the whole point of asking it. Pinned to Hebrew like the
            # other two plans, the second reading could not report "this
            # was English" even in principle — on 2026-09-05 an English
            # dictation shipped as invented Hebrew, all three decodes were
            # asked in Hebrew, they agreed 23% with the transcript, and
            # the reading proposed nothing. Same detector as the live
            # path, so the bar it has to clear is the measured one.
            audio = _decode_pcm(wav_bytes)
            if audio is not None:
                chosen = self._pick_language(audio)
        kwargs = dict(
            language=chosen,
            vad_filter=True,
            beam_size=(self._beam_size if beam_size is None
                       else max(1, int(beam_size))),
            condition_on_previous_text=False,
            initial_prompt=None if general else self._initial_prompt,
            hotwords=(hotwords or None),
            **self._guards,
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        try:
            segments, _info = model.transcribe(BytesIO(wav_bytes), **kwargs)
            text = " ".join(s.text.strip() for s in segments).strip()
        except Exception as e:
            raise TranscriptionError(f"study decode failed: {e}") from e
        if text.strip(" .,!?").lower() in _HALLUCINATED_SILENCE:
            return ""
        if self._boilerplate:
            text, _removed = cleanup_mod.strip_trailing_boilerplate(
                text, self._boilerplate)
        if self._cleanup:
            text = cleanup_mod.clean(text, self._fillers)
        return text

    def _choose(self, wav_bytes: bytes, language: str | None):
        """Which model and language a recording gets -> (model, code).

        `language` is the caller's explicit choice (a dedicated hotkey).
        It always wins — detection only runs when nothing was specified.
        """
        model, chosen = self._model, self._language
        if language == "en" and self._english is not None:
            model, chosen = self._english, "en"
        elif language in (None, "") and self._english is not None:
            audio = _decode_pcm(wav_bytes)
            if audio is not None and self._pick_language(audio) == "en":
                model, chosen = self._english, "en"
        elif language:
            chosen = language
        return model, chosen

    def _decode(self, model, chosen: str, wav_bytes: bytes):
        """One decode with the live settings, and the retry after a loop
        -> (segments, text). Raises whatever faster-whisper raises."""
        def decode(**over):
            kwargs = dict(
                language=chosen,     # never None: see _pick_language
                vad_filter=True,
                beam_size=self._beam_size,
                condition_on_previous_text=False,
                # The Hebrew prompt would only confuse the English
                # model.
                initial_prompt=None if chosen == "en"
                else self._initial_prompt,
                # Hotwords go to BOTH models, unlike initial_prompt.
                # That one is a Hebrew sentence and means nothing to a
                # general English model; this is a list of names
                # ("Expo Go", "EAS"), and an English utterance is if
                # anything the MORE likely place for them to be
                # spoken.
                hotwords=self._current_hotwords(),
                **self._guards,
            )
            kwargs.update(over)      # the retry overrides, one dict
            segments, _info = model.transcribe(BytesIO(wav_bytes),
                                               **kwargs)
            got = list(segments)
            return got, " ".join(s.text.strip() for s in got).strip()

        segs, text = decode()
        if _LOOP_RUN.search(text):
            # The words a loop swallows are NOT gone — this file used
            # to say they were, and it was wrong. Measured 2026-09-05
            # on the 57 s clip whose 73-character "Xxxxx…" ate 29 s:
            # every re-decode came back without the loop and WITH the
            # missing sentences (beam 1: 128 words, the ladder:
            # 114-125, the general model: 132, against 63 for the
            # looping one). One extra decode, only ever after a loop,
            # buys back half a minute of speech.
            #
            # Greedy first, ladder second, and that order is the whole
            # design. Beam search is what gets stuck; dropping to beam
            # 1 takes a different path through the same pinned
            # temperature, so it is DETERMINISTIC and it is cheaper
            # than the decode that just failed. The ladder samples —
            # three runs of it on that clip recovered 69, 114 and 124
            # words — so it stays the second rung, for the loop that
            # greedy decoding cannot shake either.
            for rung in (dict(beam_size=1),
                         dict(temperature=[0.0, 0.2, 0.4, 0.6, 0.8,
                                           1.0])):
                retry_segs, retry = decode(**rung)
                if retry and not _LOOP_RUN.search(retry):
                    log.warning("decoder loop — recovered with %s "
                                "(%d words for %d)",
                                "beam 1" if "beam_size" in rung
                                else "the temperature ladder",
                                len(retry.split()), len(text.split()))
                    segs, text = retry_segs, retry
                    break
        return segs, text

    @staticmethod
    def _words_of(segs) -> list[tuple]:
        """(word, start, end, probability) per word, times in seconds
        from the start of the clip that was decoded.

        Where an invented tail sits, every word is stamped into the last
        few ms at zero duration and p < 0.6, while the words really
        spoken are 0.89-1.00 — measured 2026-09-02 on the 2.8 s clip that
        grew 24 words. word_timestamps is already on for the silence
        guard; this only keeps what it computed.
        getattr: the test suite's segment stand-ins carry text only, and
        a decoder that could not time its words has still transcribed.
        """
        return [(w.word.strip(), round(float(w.start), 2),
                 round(float(w.end), 2),
                 round(float(w.probability), 3))
                for s in segs
                for w in (getattr(s, "words", None) or [])]

    def _settle(self, words: list, text: str):
        """The checks a decoded stretch gets before it can be trusted:
        the loop warning and cut, the stock phrases for silence, the
        boilerplate tail. -> rolling.Window with times still relative to
        the clip decoded (the caller places it)."""
        from rolling import Window
        warning = None
        # A long letter-run means the decoder looped, and while it loops
        # the audio keeps advancing — so the words spoken during it are
        # not in the text. Reaching HERE means the retry above looped too,
        # which is the only case left where they are really unrecoverable.
        # Say so immediately rather than let the loss be found in reading.
        loop = _LOOP_RUN.search(text)
        if loop:
            lost = _looped_seconds(words)
            span = f"{lost:.0f} s of " if lost else ""
            warning = (f"the model looped mid-recording — {span}"
                       "words around it are lost; re-dictate that "
                       "part")
            log.warning("decoder loop: %d×%r swallowed %s— and the retry "
                        "looped too", len(loop.group(0)),
                        loop.group(1), f"{lost:.1f} s " if lost else "")
            # Cut the run rather than paste it. collapse_char_runs would
            # leave a two-letter stub, and a stub sitting in the middle of
            # a sentence reads as a word the user said; the warning above
            # is what carries the loss, not a piece of the loop.
            text = _LOOP_RUN.sub(" ", text)
        if text.strip(" .,!?").lower() in _HALLUCINATED_SILENCE:
            return Window(0.0, 0.0, "", words, [], warning)
        removed: list[str] = []
        if self._boilerplate:
            text, removed = cleanup_mod.strip_trailing_boilerplate(
                text, self._boilerplate)
            if removed:
                log.warning("dropped hallucinated tail (never spoken, comes "
                            "from the fine-tune's Knesset training data): %s",
                            " | ".join(removed))
        return Window(0.0, 0.0, text, words, list(removed), warning)

    def transcribe(self, wav_bytes: bytes,
                   language: str | None = None) -> str:
        """`language` is the caller's explicit choice (a dedicated hotkey).
        It always wins — detection only runs when nothing was specified."""
        try:
            model, chosen = self._choose(wav_bytes, language)
            segs, text = self._decode(model, chosen, wav_bytes)
        except Exception as e:
            raise TranscriptionError(f"local transcription failed: {e}") from e
        window = self._settle(self._words_of(segs), text)
        self.last_words = window.words
        self.last_removed = window.removed
        self.last_warning = window.warning
        text = window.text
        if not text:
            return ""        # treated as "no speech", same as Gemini
        if self._cleanup:
            text = cleanup_mod.clean(text, self._fillers)
        return text

    # -- the rolling transcriber (rolling.py) --

    @property
    def can_overlap(self) -> bool:
        """Whether a window can be decoded with its neighbours' audio
        around it and trimmed back by word times — which needs the word
        timestamps the hallucination guards switch on."""
        return bool(self._guards.get("word_timestamps"))

    def decode_window(self, wav_bytes: bytes, lead_s: float = 0.0,
                      keep_s: float | None = None):
        """One settled stretch of a recording STILL IN PROGRESS, decoded
        exactly as the whole recording would be: the Hebrew model with
        the language pinned, the same prompt, hotwords, beam and guards,
        the same loop retry and the same checks after. -> rolling.Window

        WITH ITS NEIGHBOURS AROUND IT. `wav_bytes` may carry `lead_s` of
        the audio before the stretch and anything after it; only the
        words whose middle falls inside [lead_s, lead_s + keep_s) are
        kept, and their times are moved so 0 is the stretch's start.
        Measured 2026-09-13 on the gold clips: cut bare, a window that
        ended "מופיע לי" grew a "תודה" and the next one lost its soft
        first words to VAD; with a second of context either side the
        decoder sees what the whole recording would have shown it at
        that point, and the boundary falls in a pause where no word can
        be on both sides.

        Hebrew always. The English decision is made on the whole
        recording when the key goes up (transcribe_with_head), as it
        always was; a window that turns out to have been English is
        thrown away there. Touches no instance state: the last_* slots
        belong to the live path, which may be finishing the previous
        dictation on the worker while this runs.
        """
        try:
            segs, text = self._decode(self._model, self._language,
                                      wav_bytes)
        except Exception as e:
            raise TranscriptionError(f"local transcription failed: {e}") from e
        words = self._words_of(segs)
        if (lead_s or keep_s is not None) and words:
            words, text = _trim(segs, lead_s, keep_s)
        return self._settle(words, text)

    def transcribe_with_head(self, wav_bytes: bytes, head,
                             language: str | None = None) -> str:
        """The whole recording, given the windows already decoded from
        its head while it was being spoken (rolling.Head). Only the tail
        after `head.end_s` is decoded now — with LEAD_S of what came
        before it for context, trimmed back by word times like any
        window — and the text is the windows and the tail, joined,
        through the same cleanup as transcribe().

        A tail shorter than MIN_TAIL_S is not decoded alone — Whisper
        invents on very short clips — but together with the window
        before it, which is decoded again in its place.
        """
        from rolling import LEAD_S, MIN_TAIL_S
        try:
            model, chosen = self._choose(wav_bytes, language)
        except Exception as e:
            raise TranscriptionError(f"local transcription failed: {e}") from e
        if model is not self._model or chosen != self._language:
            # English, or a language the windows were not decoded in.
            # The whole recording, the old way — these are short.
            log.info("rolling: the recording is not %s — decoding it whole",
                     self._language)
            return self.transcribe(wav_bytes, language=chosen)
        total_s = _wav_seconds(wav_bytes)
        windows = list(head.windows)
        start = float(head.end_s)
        if windows and total_s - start < MIN_TAIL_S:
            start = windows.pop().start_s
        lead = min(start, LEAD_S) if self.can_overlap else 0.0
        try:
            tail = _slice_wav(wav_bytes, start - lead)
            if tail is not None and _wav_seconds(tail) - lead >= 0.05:
                last = self.decode_window(tail, lead, None)
                last.start_s, last.end_s = start, total_s
                windows.append(last)
        except Exception as e:
            raise TranscriptionError(f"local transcription failed: {e}") from e
        self.last_words = [(word, round(begin + w.start_s, 2),
                            round(end + w.start_s, 2), p)
                           for w in windows
                           for word, begin, end, p in w.words]
        self.last_removed = [r for w in windows for r in w.removed]
        self.last_warning = next((w.warning for w in windows if w.warning),
                                 None)
        text = " ".join(w.text for w in windows if w.text).strip()
        if not text:
            return ""
        if self._cleanup:
            text = cleanup_mod.clean(text, self._fillers)
        return text


def _trim(segs, lead_s: float, keep_s: float | None):
    """Keep the words whose MIDDLE lies in [lead_s, lead_s + keep_s), re-
    timed so the stretch starts at 0, and the text rebuilt from them
    -> (words, text).

    The middle, not the start: the boundary sits in a pause, so a word's
    middle is well clear of it on one side or the other, while its start
    or end may sit a few ms either way between two decodes of the same
    audio — and a word that both neighbours drop is a word lost.

    The text is the words' own strings run together, not joined with
    spaces: faster-whisper keeps each word's leading space in `word`, and
    a token it split at punctuation ("'ר" after "בפיצ") has none — so
    joining with spaces put one inside the word.
    """
    end = None if keep_s is None else lead_s + keep_s
    kept: list[tuple] = []
    raw: list[str] = []
    for s in segs:
        for w in (getattr(s, "words", None) or []):
            begin, stop = float(w.start), float(w.end)
            middle = (begin + stop) / 2
            if middle < lead_s or (end is not None and middle >= end):
                continue
            kept.append((w.word.strip(), round(begin - lead_s, 2),
                         round(stop - lead_s, 2),
                         round(float(w.probability), 3)))
            raw.append(str(w.word))
    return kept, "".join(raw).strip()


def _wav_seconds(wav_bytes: bytes) -> float:
    """Length of a WAV in seconds; 0.0 for anything `wave` cannot open."""
    try:
        with wave.open(BytesIO(wav_bytes), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return 0.0


def _slice_wav(wav_bytes: bytes, start_s: float) -> bytes | None:
    """The WAV from `start_s` to its end, as a WAV of its own. None when
    the input is not a WAV `wave` can read."""
    try:
        with wave.open(BytesIO(wav_bytes), "rb") as w:
            rate, width, channels = (w.getframerate(), w.getsampwidth(),
                                     w.getnchannels())
            first = max(0, min(w.getnframes(), int(start_s * rate)))
            w.setpos(first)
            pcm = w.readframes(w.getnframes() - first)
    except Exception:
        return None
    out = BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()
