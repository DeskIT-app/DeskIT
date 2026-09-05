"""Push-to-talk microphone capture.

One persistent input stream for the app's lifetime — opening a WASAPI stream
per utterance is slow enough to clip the first word. Frames are only buffered
while an utterance is active; otherwise audio is discarded on arrival.
"""
from __future__ import annotations

import io
import logging
import math
import threading
import wave
from typing import Callable

import numpy as np
import sounddevice as sd

log = logging.getLogger("app")

IDLE = "idle"
ACTIVE = "active"
OVERFLOWED = "overflowed"


def wasapi_auto_convert():
    """WASAPI's own sample-rate converter, or None where there is none.

    Windows-only, and only on a WASAPI endpoint — see Recorder._open,
    which is why this answers with None rather than raising.
    """
    try:
        return sd.WasapiSettings(auto_convert=True)
    except Exception:
        return None


def frames_to_wav(chunks: list[np.ndarray], sample_rate: int) -> bytes:
    """int16 mono chunks -> WAV file bytes."""
    pcm = b"".join(c.tobytes() for c in chunks)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # int16
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class Recorder:
    def __init__(self, sample_rate: int, device: int | str | None,
                 max_seconds: float, on_overflow: Callable[[], None]):
        self._on_overflow = on_overflow
        self._lock = threading.Lock()
        self._state = IDLE
        self._chunks: list[np.ndarray] = []
        # Chunk ranges the finished utterance must NOT contain. Filled by
        # exclude_since when a question spoken to the ask card is marked
        # as not part of what is being written — see end().
        self._excluded: list[tuple[int, int]] = []
        # Chunk ranges that were spoken to the ask card and ARE part of
        # this utterance. Kept apart from the audio so end_pieces can cut
        # the utterance at them — see note_question.
        self._questions: list[tuple[int, int]] = []
        self._samples = 0
        # The loudest sample in the last callback, 0..1. One np.abs().max()
        # on a buffer that is already in cache - microseconds - and it is
        # what lets the ask card draw a wave that is actually YOUR voice
        # rather than a decorative animation pretending to be.
        self._level = 0.0
        try:
            self._stream = self._open(device, sample_rate)
        except (sd.PortAudioError, ValueError) as e:
            if device is None:
                raise
            # The chosen microphone cannot be opened. Usually it is not
            # even a microphone any more: `[audio] device` may hold a bare
            # INDEX, and indices shift whenever a device appears or
            # disappears — a Bluetooth headset connecting is enough. On
            # 2026-09-05 index 27 was the Arctis mic at 15:14 and
            # "Speakers (Realtek HD Audio output), 0 in, 8 out" by 15:36,
            # so every start failed with "Invalid number of channels" and
            # the app would not come up at all.
            #
            # A third hand does not down tools because a plug moved. Take
            # the system default input and say so — dictation into the
            # wrong-but-working microphone is recoverable in a way that a
            # dictation app that will not start is not.
            log.warning("microphone %r cannot be opened (%s) — using the "
                        "system default input instead; set [audio] device "
                        "in config.toml (see --list-devices)",
                        device, str(e).splitlines()[0])
            self._stream = self._open(None, sample_rate)
        self.sample_rate = int(self._stream.samplerate)
        if self.sample_rate != sample_rate:
            # Said out loud, because the one time this happened quietly it
            # cost a day: a microphone that forced its own rate used to
            # switch language detection off without a word, and English
            # dictation came back as invented Hebrew. See
            # local_whisper._decode_pcm, which no longer cares — this line
            # is so the NEXT thing that only works at 16 kHz is found in
            # the log rather than in the transcripts.
            log.warning("the microphone refused %d Hz — recording at its "
                        "own %d Hz instead", sample_rate, self.sample_rate)
        self._default_max_samples = float(max_seconds * self.sample_rate)
        self._max_samples = self._default_max_samples

    def _open(self, device, sample_rate: int):
        """One input stream on `device`, at `sample_rate` if it can be had.

        Three rungs, because a driver is allowed to refuse a rate:

        1. plain, which almost every microphone accepts;
        2. WASAPI's own converter. The Arctis 7 Chat headset refuses
           16 kHz shared-mode capture and takes it with auto_convert on —
           measured 2026-09-05 on the live endpoint, -9997 without it,
           16000.0 Hz with. The resampling then happens inside the Windows
           audio engine, which costs this process nothing;
        3. whatever rate the device wants. Correct — every consumer
           resamples — but the file is three times the size and the
           language detector loses its fast path, so it is the last rung
           rather than the first fallback it used to be.

        Passing WasapiSettings to a non-WASAPI endpoint raises rather than
        being ignored, which is why rung 2 is inside the ladder and not
        folded into rung 1.
        """
        rungs = [dict(samplerate=sample_rate)]
        wasapi = wasapi_auto_convert()
        if wasapi is not None:
            rungs.append(dict(samplerate=sample_rate, extra_settings=wasapi))
        rungs.append(dict(samplerate=None))
        last: Exception | None = None
        for rung in rungs:
            try:
                return sd.InputStream(channels=1, dtype="int16",
                                      device=device,
                                      callback=self._callback, **rung)
            except sd.PortAudioError as e:
                last = e
        raise last                      # never None: the list is not empty

    def start_stream(self) -> None:
        self._stream.start()

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass

    def meter(self) -> tuple[float, bool]:
        """(loudest sample of the last buffer 0..1, still recording?).

        Safe from any thread and never blocks: both reads are of a single
        attribute, and a torn read of a float that is redrawn sixteen
        times a second is not worth a lock.
        """
        return self._level, self._state == ACTIVE

    def device_label(self) -> str:
        try:
            info = sd.query_devices(self._stream.device)
            return f"{info['name']} @ {self.sample_rate} Hz"
        except Exception:
            return f"input device @ {self.sample_rate} Hz"

    # -- utterance lifecycle (called from the hook thread) --

    def begin(self) -> None:
        with self._lock:
            self._chunks = []
            self._excluded = []
            self._questions = []
            self._samples = 0
            self._max_samples = self._default_max_samples  # undo any lift
            self._state = ACTIVE

    def set_cap(self, seconds: float | None) -> None:
        """Change the runaway cap for the recording in progress. None or 0
        removes it — used when the user latches the key down, where the cap
        no longer protects against anything (there is no key-up to swallow)
        and would only truncate a long deliberate dictation."""
        with self._lock:
            self._max_samples = (math.inf if not seconds
                                 else float(seconds * self.sample_rate))

    def mark(self) -> int:
        """A cursor into the utterance in progress, for slice_since().

        The chunk list is append-only while ACTIVE — the callback only
        ever appends, and nothing removes — so its length is a stable
        cursor: the chunks before it never move and never change.
        """
        with self._lock:
            return len(self._chunks) if self._state == ACTIVE else 0

    def note_question(self, mark: int) -> None:
        """Everything since `mark` was said to the ask card, and stays.

        The audio is NOT touched — this only records where the question
        was, so end_pieces can hand the transcriber the stretches on
        either side of it and the caller can drop back the text it already
        has.

        WHY THAT IS WORTH THE TROUBLE. Whisper's VAD drops a short
        utterance that sits alone between two long silences, and a
        question asked in the middle of a locked dictation is exactly that
        shape: you stop talking, drag a rectangle, say one thing, read the
        answer, carry on. Measured on a real recording, 2026-08-31: the
        owner said "four" to the card, and it was in the file, and in the
        transcript of that slice on its own, and ABSENT from the
        transcript of the whole 35 s recording (vad_filter=False put it
        back, at a cost to everything else). Transcribing around it and
        splicing is the fix that cannot lose it.
        """
        with self._lock:
            if self._state == ACTIVE and len(self._chunks) > mark:
                self._questions.append((mark, len(self._chunks)))

    def exclude_since(self, mark: int) -> None:
        """Leave everything captured since `mark` OUT of this utterance.

        The other half of slice_since. A question spoken into the ask card
        is part of the recording whether anybody likes it or not — the
        microphone does not have two channels — so "do not put this in
        what I am writing" cannot mean "do not record it". It means the
        finished utterance is assembled without those frames, which is
        what end() does with this list.

        Recorded as a RANGE rather than by deleting: the callback is
        appending to the same list from the PortAudio thread, and the
        cursors handed out by mark() have to keep pointing at the same
        audio they pointed at when they were taken.
        """
        with self._lock:
            if self._state == ACTIVE and len(self._chunks) > mark:
                self._excluded.append((mark, len(self._chunks)))

    def slice_since(self, mark: int) -> tuple[bytes | None, float]:
        """The audio captured since `mark` — WITHOUT ending the utterance.

        The one thing this must not do is disturb the recording, and it
        does not: it copies a slice of the list and mutates nothing. The
        frames stay in the buffer, so the same speech is BOTH the question
        the ask card is being handed AND part of the sentence still being
        dictated underneath it.

        That is the whole feature. Talk into a field, ask the screen
        something in the middle, keep talking — and when the latch is
        finally tapped, one continuous transcript lands, with the words
        you said to the card sitting in it where you said them, as though
        there had been no interruption at all.
        """
        with self._lock:
            if self._state != ACTIVE:
                return None, 0.0
            chunks = self._chunks[mark:]
        if not chunks:
            return None, 0.0
        samples = sum(len(c) for c in chunks)
        return (frames_to_wav(chunks, self.sample_rate),
                samples / self.sample_rate)

    def abort(self) -> None:
        with self._lock:
            self._chunks = []
            self._excluded = []
            self._questions = []
            self._samples = 0
            self._state = IDLE

    def _finish(self) -> tuple[list[list], float]:
        """Take the utterance -> ([[was_a_question, chunks], ...], seconds).

        The one place the buffer is handed over and cleared. Excluded
        ranges are dropped here; noted questions become pieces of their
        own, in order, so what comes back is the recording split exactly
        where the ask card interrupted it.
        """
        with self._lock:
            state = self._state
            chunks = self._chunks
            excluded = self._excluded
            questions = self._questions
            samples = self._samples
            self._state = IDLE
            self._chunks = []
            self._excluded = []
            self._questions = []
            self._samples = 0
        if state != ACTIVE or not chunks:
            return [], samples / self.sample_rate
        # Questions the owner asked the screen and said were none of this
        # sentence's business. Dropped whole chunks, so what is left still
        # joins seamlessly.
        drop: set[int] = set()
        for begin_at, stop_at in excluded:
            drop.update(range(begin_at, stop_at))
        asked: set[int] = set()
        for begin_at, stop_at in questions:
            asked.update(range(begin_at, stop_at))
        pieces: list[list] = []
        for index, chunk in enumerate(chunks):
            if index in drop:
                continue
            to_card = index in asked
            if pieces and pieces[-1][0] == to_card:
                pieces[-1][1].append(chunk)
            else:
                pieces.append([to_card, [chunk]])
        kept = sum(len(c) for _q, part in pieces for c in part)
        return pieces, kept / self.sample_rate

    def end(self) -> tuple[bytes | None, float]:
        """Finish the utterance -> (wav_bytes, seconds).

        wav_bytes is None when the recording overflowed max_seconds (already
        discarded) or nothing was captured.
        """
        pieces, seconds = self._finish()
        if not pieces:
            return None, seconds
        chunks = [c for _q, part in pieces for c in part]
        return frames_to_wav(chunks, self.sample_rate), seconds

    def end_pieces(self) -> tuple[bytes | None,
                                  list[tuple[bool, bytes]], float]:
        """end(), and the same utterance CUT AT THE QUESTIONS.

        -> (the whole thing as one wav, [(was_a_question, wav), ...],
        seconds). Both, because the caller wants the whole file for the
        spool and the pieces for the transcript. A recording nobody asked
        anything during comes back as a single piece, and the caller can
        treat it exactly as it always did.
        """
        pieces, seconds = self._finish()
        if not pieces:
            return None, [], seconds
        chunks = [c for _q, part in pieces for c in part]
        return (frames_to_wav(chunks, self.sample_rate),
                [(bool(q), frames_to_wav(part, self.sample_rate))
                 for q, part in pieces],
                seconds)

    # -- PortAudio callback thread: keep it tiny --

    def _callback(self, indata, frames, time_info, status) -> None:
        notify = None
        with self._lock:
            if self._state == ACTIVE:
                self._chunks.append(indata.copy())
                self._samples += len(indata)
                self._level = float(np.abs(indata).max()) / 32768.0
                if self._samples >= self._max_samples:
                    # Runaway recording (e.g. key-up swallowed by an elevated
                    # window): drop the buffer, remember the duration.
                    self._state = OVERFLOWED
                    self._chunks = []
                    notify = self._on_overflow
        if notify is not None:
            notify()
