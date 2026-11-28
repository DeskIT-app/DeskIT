"""The speech model woken when the person comes back, not on their first
word ([local] warm_after_away_min).

The owner, 2026-10-20: "the first dictation after a long time always
lags a bit" — and at 15:33 that day it lagged 11.8 s, long enough that
he called it a crash and clicked, so the text went to the clipboard
instead of the field. Read off this machine's own logs:

- app.log: released 15:33:12.6, language detected 15:33:24.5, the Hebrew
  decode after it 0.4 s. The next dictation, 16 s later: 0.6 s to the
  paste. Nothing failed; the first decode paid for something.
- awake.log: the night's training run (00:30-09:00) held 15.1 of the
  card's 15.9 GB and 97-99% of the commit limit. Before it the card read
  5.7 GB with this app's models on it; after it, 2.6 GB all day, and 5.8
  GB again at 15:35. Windows had moved the models off the card to make
  room, and nothing moved them back until a dictation asked.
- Every dictation in app.log 10-09..10-20 (342): after 10 h or more
  without one, 9 first dictations, release to paste median 1.56 s
  against 1.12 s for the rest, and two of them 7.2 s (10-13 16:29) and
  12.2 s (10-20 15:33). Both times the screens had come on minutes
  before (2.5 and 14 min) — time enough to have paid it unseen.

So the cost is real, it lands on the first dictation, one decode pays
all of it, and the person's return comes first. This module decides
WHEN; App._rewarm runs the load-time warm-ups again (the same two passes
per model, local_whisper.rewarm) under the model lock.

WHEN, exactly:

- BACK: input after at least `away_s` with none (GetLastInputInfo — the
  screens key, the mouse, anything), and the model has not run in that
  time (a phone dictation while away already woke it).
- RESUMED: the pause lifted — the pause is for games, and a game is the
  other thing that pushes the model off a card. This half is the same
  mechanism, not a measurement: no game was run for it.

Never while paused, and never while the card is full: free memory under
`min_free` (nvidia-smi, asked only at the moment of deciding) means
someone else is using the card right now — the night's training, a game —
and pulling the models back would push THEM out. Deferred instead, asked
again every `retry_s`, until there is room or the model runs on its own.
Without nvidia-smi (no NVIDIA card, the processor model) it goes ahead.

Waker is the decision and nothing else — times and readings in, a reason
out, no clock, no Windows — so the tests drive it with numbers.
"""
from __future__ import annotations

GB = 1 << 30

#: How often the app looks at GetLastInputInfo: seconds. The call is a
#: read of one kernel counter; the person notices nothing either way.
POLL_S = 2.0

#: Free card memory below which a warm-up waits: bytes. This app's two
#: models came back as 3.0 GB on 2026-10-20 (2.8 -> 5.8 GB).
MIN_FREE = 3 * GB

#: How long a warm-up that found the card full waits before asking
#: again: seconds. One nvidia-smi (~150 ms) a minute.
RETRY_S = 60.0

#: A warm-up slower than this found the models pushed out: seconds.
#: Warm, the four passes took 0.51-0.52 s on the RTX (four runs on the
#: real models, 2026-10-20); pushed out, the same work took 11.8 s.
SLOW_S = 2.0


class Waker:
    """`look()` once a poll; `resumed()` when the pause lifts."""

    def __init__(self, away_s: float, *, min_free: int = MIN_FREE,
                 retry_s: float = RETRY_S):
        self.away_s = away_s
        self.min_free = min_free
        self.retry_s = retry_s
        self._away = 0.0          # the longest idle seen in this absence
        self._reason = ""         # armed: why a warm-up is owed
        self._since = 0.0         # ... counting model use from this time
        self._retry_at = 0.0

    def resumed(self, now: float) -> None:
        self._reason, self._since, self._retry_at = "after the pause", now, 0.0

    def look(self, now: float, last_input: float, model_used: float,
             paused: bool, free=None) -> str | None:
        """A reason to warm the model now, or None. `last_input` and
        `model_used` are times on the same clock as `now`; `free` is a
        callable answering the card's free bytes (None = no card to ask),
        called only when everything else says yes."""
        if self.away_s <= 0:
            return None
        idle = now - last_input if last_input else 0.0
        if idle >= self.away_s:
            self._away = max(self._away, idle)
            return None
        if self._away:
            minutes = round(self._away / 60)
            self._reason = f"back after {minutes} min away"
            self._since, self._retry_at = now - self._away, 0.0
            self._away = 0.0
        if not self._reason:
            return None
        if model_used >= self._since or paused:
            # It ran meanwhile (a phone dictation, a dictation, a
            # reading), or the pause is on and RESUMED will ask again.
            self._reason = ""
            return None
        if now < self._retry_at:
            return None
        room = free() if free is not None else None
        if room is not None and room < self.min_free:
            self._retry_at = now + self.retry_s
            return None
        reason, self._reason = self._reason, ""
        return reason
