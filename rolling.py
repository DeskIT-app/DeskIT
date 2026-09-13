"""Transcribe a dictation while it is still being spoken.

The wait after the key is released used to be the decode of the WHOLE
recording: 4.3 s for a 162 s dictation, 2.7 s for 82 s (app.log,
2026-09-13). Whisper is not slow — a 5060 Ti runs it at ~40x real time —
the audio is just all handed over at once, at the end. This module hands
it over as it comes.

While the key is held, a thread watches the buffer and, each time enough
audio has settled behind a pause, decodes that stretch on the same model,
with the same prompt, hotwords, beam and guards as the whole recording
would get (LocalWhisperTranscriber.decode_window). When the key goes up,
only the tail — whatever came after the last pause the thread had
already used, at most one stretch — is still to be decoded, and that is
about a second whatever the length of the dictation (measured below:
a 95 s clip 4.9 s -> 1.05 s, 80 s 3.7 -> 1.3, 70 s 2.05 -> 0.9).

WHAT IT MUST NOT DO is put anything on screen early. The rule in
[polish] stands: "..." means not finished, text means finished and will
not change. The windows are joined in the worker after the tail is
decoded and the transcript lands once, whole, as it always has.

WHERE TO CUT is the only real decision here, and it is made on the
audio, not the clock:

- at a PAUSE — a run of quiet chunks at least PAUSE_S long — so no word
  is ever split between two decodes;
- only once that pause is LAG_S behind the microphone, so a breath that
  turns out to be mid-word is not mistaken for the end of one;
- the LATEST such pause, so windows come out as long as the config
  allows (window_s) rather than as short as the speech permits;
- never past MAX_WINDOW_S without a cut: faster-whisper would break the
  audio at 30 s itself, and a quiet chunk chosen here beats a hard edge
  chosen there.

HOW LONG A WINDOW MUST BE was measured, not chosen (2026-09-13, the 69
gold clips in corpus\\, 2,881 labelled words, the roller simulated over
each clip as it would have arrived, the same model and settings as the
whole decode it was scored against):

    whole recording, as before                    7.53% WER
    25 s windows                                  9.44%
    20 s windows                                 11.0-11.9%
     8 s windows                                 13.92%

and the CONTROL, which is what makes those numbers readable — the whole
recording decoded exactly as before with only its framing nudged:

    0.35 s of silence put in front of it          9.16%
    1.0 s of silence in front of it              10.62%
    the first 0.3 s dropped                      11.21%

The labels were made by correcting this model's own whole decode, so
they carry its every coin-flip: change nothing but the framing and a
third of the clips move. Anything inside that band is the same decode
in a different frame; 25 s windows are inside it (and on one 80 s clip
recovered a sentence the whole decode had lost), 20 s sits at its edge,
8 s is well outside — short windows really do read worse. Whisper's own
chunking is 30 s, and a 25-28 s window cut in a pause is the same
chunk it would have made. So the default is 25, the release waits for
at most the last stretch — about a second — and a dictation shorter
than a stretch is decoded exactly as it always was. The wish for "no
minimum" was tried and is what the 8 s row says.

"Quiet" is RELATIVE. The owner's microphone peaks at 0.03-0.06 on many
recordings and at 0.3 on others (measured over recent\\, 2026-09-13),
while the floor between words sits at 0.0000-0.0009 on all of them, so
a fixed threshold would either miss the quiet sessions' pauses or call
their speech silence. A chunk is quiet when its peak is under RATIO of
the loud level of the pending audio, with FLOOR as the least that can
ever count.

The recorder is read, never written: chunks_since() copies references
out from under its lock and the buffer it hands to end() is untouched.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

log = logging.getLogger("app")

PAUSE_S = 0.5          # a run of quiet this long is somewhere to cut
LAG_S = 0.8            # ...once it is this far behind the microphone
MAX_WINDOW_S = 28.0    # cut somewhere quiet before Whisper's own 30 s edge
FLOOR = 0.003          # quieter than this is quiet whatever the loud level
RATIO = 0.08           # quiet = under this fraction of the loud level
POLL_S = 0.2           # how often the thread looks at the buffer
MIN_TAIL_S = 2.0       # a tail shorter than this is decoded with the
                       # window before it, not alone
# Each window is decoded with its neighbours' audio around it and trimmed
# back by word times (LocalWhisperTranscriber.decode_window): LEAD_S of
# the previous window before it, up to EXT_S of what came after — which
# exists, because a cut is at least LAG_S behind the microphone. Bare
# cuts were measured to cost words at the edges (2026-09-13, gold clips):
# a window ending on a breath grew a "תודה", the next lost its soft first
# words to VAD's onset. With the context the decoder sees what the whole
# recording would have shown it at that point.
LEAD_S = 1.0
EXT_S = 0.8


@dataclass
class Window:
    """One settled stretch, decoded. Times are seconds into the recording."""
    start_s: float
    end_s: float
    text: str
    words: list = field(default_factory=list)      # (word, start, end, p)
    removed: list = field(default_factory=list)    # boilerplate dropped
    warning: str | None = None
    # The stretch after the repair pass (main.App._polish_window), set by
    # a thread of its own while the key is still held; None until then,
    # and for ever when the pass was skipped. At the release only the
    # leading run of repaired windows is trusted — the rest, tail
    # included, goes through the pass together, as the whole recording
    # used to.
    polished: str | None = None


@dataclass
class Head:
    """What the thread had finished when the key went up: the windows in
    order, and how far into the recording the last one reaches."""
    windows: list[Window]
    end_s: float


def loud_level(peaks: Sequence[float]) -> float:
    """The level speech reaches in this stretch — the 95th percentile of
    the chunk peaks, so a single click does not set it."""
    if not peaks:
        return 0.0
    ranked = sorted(peaks)
    return ranked[min(len(ranked) - 1, int(len(ranked) * 0.95))]


def quiet_threshold(peaks: Sequence[float]) -> float:
    """Under this, a chunk is quiet — relative to the loud level, never
    under FLOOR."""
    return max(FLOOR, RATIO * loud_level(peaks))


def cut_at(peaks: Sequence[float], sizes: Sequence[int], rate: int,
           window_s: float, *, pause_s: float = PAUSE_S,
           lag_s: float = LAG_S,
           max_window_s: float = MAX_WINDOW_S) -> int | None:
    """Where the pending audio can be cut, as a chunk index, or None.

    `peaks` and `sizes` describe the chunks captured since the last cut,
    oldest first: the loudest sample of each (0..1) and its length in
    samples. The answer is the index of the first chunk that stays
    pending; chunks before it make the window.

    Pure, so a test can drive it with numbers.
    """
    total = sum(sizes)
    if total < window_s * rate:
        return None
    threshold = quiet_threshold(peaks)
    latest = total - lag_s * rate          # nothing newer than this counts
    need = pause_s * rate
    starts: list[int] = []
    pos = 0
    for n in sizes:
        starts.append(pos)
        pos += n
    # Walk back from the newest chunk measuring runs of quiet. The first
    # run long enough is the LATEST usable pause. The cut goes through its
    # middle so both windows keep a little of the silence — VAD trims it,
    # and a hard edge on a breath is what makes the decoder invent.
    i = len(peaks) - 1
    while i >= 0:
        if peaks[i] >= threshold:
            i -= 1
            continue
        run_end = min(starts[i] + sizes[i], latest)
        j = i
        while j > 0 and peaks[j - 1] < threshold:
            j -= 1
        run_start = starts[j]
        if run_end - run_start >= need:
            middle = (run_start + run_end) / 2
            k = j
            while k + 1 < len(sizes) and starts[k + 1] <= middle:
                k += 1
            # A window shorter than half the target is worth waiting on
            # — a later pause makes a longer one — unless the pending
            # audio is about to hit Whisper's own edge anyway.
            if starts[k] < window_s * rate / 2 and total < max_window_s * rate:
                return None
            return k if k > 0 else None
        i = j - 1
    if total >= max_window_s * rate:
        # No pause at all in nearly half a minute: the quietest chunk of
        # the last five seconds that is still LAG_S behind the microphone.
        quietest, best = None, None
        for i in range(len(peaks) - 1, 0, -1):
            if starts[i] > latest:
                continue
            if starts[i] < total - 5.0 * rate:
                break
            if best is None or peaks[i] < best:
                quietest, best = i, peaks[i]
        return quietest
    return None


class Roller:
    """One per recording. Started when the key goes down, closed when it
    goes up, finished by the worker that transcribes the tail.

    `chunks_since(mark)` is the recorder's; `decode(wav_bytes, lead_s,
    keep_s)` is the backend's decode_window; both are called only from
    this thread. `overlap` off means bare windows — for a backend that
    cannot time its words and so cannot trim.
    """

    def __init__(self, chunks_since: Callable[[int], list], rate: int,
                 decode: Callable[[bytes, float, float], Window],
                 window_s: float, to_wav: Callable[[list, int], bytes],
                 overlap: bool = True) -> None:
        self._chunks_since = chunks_since
        self._rate = max(1, int(rate))
        self._decode = decode
        self._window_s = max(1.0, float(window_s))
        self._to_wav = to_wav
        self._overlap = overlap
        self._cursor = 0            # first chunk not yet in a window
        self._offset = 0            # samples before the cursor
        self._peaks: list[float] = []   # of chunks[cursor:], as seen so far
        self._sizes: list[int] = []
        self._lead: list = []       # the last LEAD_S of the previous window
        self.windows: list[Window] = []
        self.decodes = 0
        self.busy_s = 0.0           # decoder time spent while recording
        self._stop = threading.Event()
        self._invalid = False
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="rolling-transcribe")

    # -- from the hook thread: one call each, nothing that can block --

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        """The key went up. The thread finishes any decode it is in and
        stops; finish() collects the result."""
        self._stop.set()

    def invalidate(self) -> None:
        """The recording is no longer the plain thing this was reading —
        the ask card took a slice out of it, or a decode failed. Whatever
        was done is dropped and the whole recording goes the old way."""
        self._invalid = True
        self._stop.set()

    @property
    def done_s(self) -> float:
        """How far into the recording the finished windows reach."""
        return self._offset / self._rate

    # -- from the worker --

    def finish(self, timeout: float = 10.0) -> Head | None:
        """Wait for the thread and hand over what it did. None when there
        is nothing usable: no window finished, or the result was
        invalidated — either way the caller decodes the whole recording
        exactly as before this module existed."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)
            if self._thread.is_alive():
                log.warning("the rolling transcriber did not stop in %.0f s "
                            "— decoding the whole recording instead",
                            timeout)
                self._invalid = True
        if self._invalid or not self.windows:
            return None
        return Head(list(self.windows), self.done_s)

    # -- the thread --

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                time.sleep(POLL_S)
                if self._stop.is_set():
                    break
                self._step()
        except Exception:
            log.exception("the rolling transcriber failed — the whole "
                          "recording will be decoded at the end instead")
            self._invalid = True

    def _step(self) -> None:
        chunks = self._chunks_since(self._cursor)
        if not chunks:
            return
        for chunk in chunks[len(self._peaks):]:
            self._peaks.append(_peak(chunk))
            self._sizes.append(len(chunk))
        cut = cut_at(self._peaks, self._sizes, self._rate, self._window_s)
        if not cut:
            return
        window = chunks[:cut]
        samples = sum(self._sizes[:cut])
        start_s = self._offset / self._rate
        end_s = (self._offset + samples) / self._rate
        spoken = max(self._peaks[:cut]) >= quiet_threshold(self._peaks)
        lead, lead_s = self._lead, _seconds(self._lead, self._rate)
        after = chunks[cut:_count_up_to(chunks, cut, EXT_S * self._rate)] \
            if self._overlap else []
        self._lead = _last_seconds(window, self._rate, LEAD_S) \
            if self._overlap else []
        self._cursor += cut
        self._offset += samples
        del self._peaks[:cut]
        del self._sizes[:cut]
        if not spoken:
            # Nothing but room in it — the lead-in before he began, or a
            # long think. Whisper's VAD would return nothing for it; skip
            # the decode and let the tail start after it.
            log.debug("rolling: %.1f-%.1f s is silence, skipped", start_s,
                      end_s)
            return
        began = time.monotonic()
        decoded = self._decode(self._to_wav(lead + window + after,
                                            self._rate),
                               lead_s, samples / self._rate)
        self.busy_s += time.monotonic() - began
        self.decodes += 1
        decoded.start_s, decoded.end_s = start_s, end_s
        self.windows.append(decoded)
        log.debug("rolling: %.1f-%.1f s decoded in %.2f s (%d words)",
                  start_s, end_s, time.monotonic() - began,
                  len(decoded.text.split()))


def _seconds(chunks: Sequence, rate: int) -> float:
    return sum(len(c) for c in chunks) / float(rate)


def _last_seconds(chunks: Sequence, rate: int, seconds: float) -> list:
    """The trailing chunks that make up `seconds`, whole chunks only."""
    want = seconds * rate
    kept: list = []
    have = 0
    for chunk in reversed(chunks):
        if have >= want:
            break
        kept.append(chunk)
        have += len(chunk)
    kept.reverse()
    return kept


def _count_up_to(chunks: Sequence, start: int, samples: float) -> int:
    """The index just past the chunks from `start` that make up
    `samples`, whole chunks only."""
    have = 0
    index = start
    while index < len(chunks) and have < samples:
        have += len(chunks[index])
        index += 1
    return index


def _peak(chunk) -> float:
    """Loudest sample of an int16 chunk, 0..1."""
    try:
        return float(abs(chunk).max()) / 32768.0
    except (ValueError, TypeError, AttributeError):
        return 0.0
