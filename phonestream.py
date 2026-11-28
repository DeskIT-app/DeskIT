"""A phone dictation decoded while it is still being spoken (PHONE_LINK_PLAN.md
stage 2, the owner's choice of 2026-11-27).

Until stage 2 the keyboard sent the whole recording after the release and
this PC decoded the whole of it then, so a minute spoken was a minute's
decode waited for. The desk solved the same thing with rolling.py: decode
the settled stretches while the key is held, and only the tail at the
release. This module gives that machinery a phone instead of a microphone.

TWO ROADS, ONE SESSION. The phone door's ``/stream`` (server.py) and the
relay's streamed pieces (relay.py) both feed a `Session`: PCM in as it
arrives, the answer at the end. The answer is exactly the one ``/transcribe``
gives for the same recording (server.Routes._answer), through the desk's own
path: rolling.Roller over a `PhoneStream`, then main.App._transcribe_for_phone
with the roller, which finishes through ``transcribe_with_head``: the same
trim, repair, ``recent\\``, second reading and English decision on the whole
recording.

WHAT IT MUST NOT DO is answer early or answer twice. Nothing is said to the
phone until the end of the stream has come and checked (its byte count and
SHA-256), and the text then is the whole transcript, once. A stream that
breaks, is cancelled or does not check is dropped: the phone keeps its
recording until a text lands, and sends it whole on the same road
(PHONE_LINK_PLAN.md stage 2, "no new way to lose words").

THE CHUNKS ARE THE DESK'S. rolling.Roller measures a chunk's loudness with
``abs(chunk).max()`` and cuts between whole chunks. Handed raw bytes, that
reads as silence with no error, every window is skipped and the speed-up
quietly vanishes; handed the phone's own 128 ms reads, a cut can land only on
their edges. So what arrives is int16, re-sliced to the 10 ms chunks the
desk's recorder hands it (``CHUNK_S``), whatever size the road delivered.

Nothing here reads a socket or a key, and nothing is logged of what was said.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from typing import Callable

import numpy as np

log = logging.getLogger("app")

#: What a phone records and every road carries: 16 kHz mono 16-bit.
RATE = 16000
#: The desk recorder's chunk: PortAudio's WASAPI block on this PC.
CHUNK_S = 0.010
#: The longest recording a phone makes (Recorder.MAX_SECONDS, 300 s), in
#: bytes, and a little room: past it a stream is not one a phone sends.
MAX_PCM = 310 * RATE * 2


class TooLong(Exception):
    """More audio than a phone ever records."""


class PhoneStream:
    """What rolling.Roller reads (``chunks_since``, ``sample_rate``), fed from
    a phone instead of a microphone. ``feed`` takes whatever the road
    delivered, any size, a sample split between two feeds included."""

    def __init__(self, rate: int = RATE) -> None:
        self.sample_rate = int(rate)
        self._per = max(1, int(round(self.sample_rate * CHUNK_S)))
        self._lock = threading.Lock()
        self._chunks: list[np.ndarray] = []
        self._rest = np.zeros(0, dtype=np.int16)    # under one chunk, waiting
        self._odd = b""                             # half a sample, waiting
        self._pcm = bytearray()
        self._ended = False

    def feed(self, pcm: bytes) -> None:
        """More of the recording, in order."""
        if not pcm:
            return
        with self._lock:
            if self._ended:
                return
            if len(self._pcm) + len(pcm) > MAX_PCM:
                raise TooLong(f"{len(self._pcm) + len(pcm)} bytes of audio")
            self._pcm += pcm
            data = self._odd + bytes(pcm)
            cut = len(data) - (len(data) % 2)
            self._odd = data[cut:]
            samples = np.frombuffer(data[:cut], dtype="<i2").astype(np.int16)
            if self._rest.size:
                samples = np.concatenate((self._rest, samples))
            whole = samples.size - (samples.size % self._per)
            for i in range(0, whole, self._per):
                self._chunks.append(samples[i:i + self._per])
            self._rest = samples[whole:]

    def end(self) -> None:
        """No more: the roller is done reading, and the buffer is the answer's."""
        with self._lock:
            self._ended = True

    def chunks_since(self, mark: int) -> list:
        """The chunks since ``mark``, as the desk recorder hands them: the
        list copied under the lock, the arrays shared (nothing writes them),
        and [] once the stream has ended."""
        with self._lock:
            if self._ended:
                return []
            return self._chunks[mark:]

    @property
    def size(self) -> int:
        """Bytes of PCM so far."""
        with self._lock:
            return len(self._pcm)

    @property
    def seconds(self) -> float:
        return self.size / 2.0 / self.sample_rate

    def pcm(self) -> bytes:
        with self._lock:
            return bytes(self._pcm)

    def digest(self) -> str:
        """SHA-256 of the PCM so far, as the phone's end names it."""
        return hashlib.sha256(self.pcm()).hexdigest()

    def wav(self) -> bytes:
        """The recording so far as the WAV the phone would have sent."""
        from recorder import frames_to_wav
        pcm = self.pcm()
        samples = np.frombuffer(pcm[:len(pcm) - len(pcm) % 2], dtype="<i2").astype(np.int16)
        return frames_to_wav([samples], self.sample_rate)


class Session:
    """One phone dictation arriving while it is spoken, from its first byte to
    its one answer.

    ``begin(stream)`` starts the rolling transcriber over the stream (main.App
    ._stream_roller), or answers None when there is to be none (rolling off,
    the model off or not this kind, the app locked): the answer then is the
    whole decode, exactly as ``/transcribe``'s. ``answer(wav, rolled)`` is that
    route's answer for the finished recording (server.Routes._answer).
    """

    def __init__(self, begin: Callable[[PhoneStream], object],
                 answer: Callable[[bytes, object], tuple[int, dict]],
                 rate: int = RATE) -> None:
        self.stream = PhoneStream(rate)
        self._answer = answer
        self._lock = threading.Lock()
        self._over = False
        self._roller = None
        try:
            self._roller = begin(self.stream)
        except Exception:                                    # noqa: BLE001
            log.exception("could not start the rolling transcriber for a phone "
                          "stream — it is decoded whole at the end")

    @property
    def rolling(self) -> bool:
        return self._roller is not None

    def feed(self, pcm: bytes) -> None:
        if not self._over:
            self.stream.feed(pcm)

    def checks(self, size: int, sha256: str) -> bool:
        """The end names what was sent: is that what came?"""
        return size == self.stream.size and sha256 == self.stream.digest()

    def finish(self, wav: bytes | None = None) -> tuple[int, dict]:
        """The answer, once: the stream's own recording (the door), or ``wav``,
        the whole that the end checked (the relay)."""
        with self._lock:
            if self._over:
                return 409, {"error": "this stream was answered already"}
            self._over = True
        roller = self._roller
        if roller is not None:
            roller.close()
        recording = wav if wav is not None else self.stream.wav()
        self.stream.end()
        return self._answer(recording, roller)

    def cancel(self) -> None:
        """The phone said stop, or the stream broke: nothing is answered, and
        the rolling transcriber's work is dropped."""
        with self._lock:
            if self._over:
                return
            self._over = True
        roller = self._roller
        if roller is not None:
            roller.invalidate()
        self.stream.end()
