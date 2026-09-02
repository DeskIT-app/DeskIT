"""`transcripts.log`, read back as things that happened rather than lines.

The file is written for grep and for a human scrolling in Notepad: one
line per event, fields separated by pipes, newest at the bottom. Showing
it in a window wants the opposite shape — newest first, and one entry per
thing the OWNER did rather than one per thing the code logged. Three of
those differences are the whole reason this module exists:

* **A translation is two lines.** `TRANSLATE-IN` when the text goes out
  and `TRANSLATE-OUT` when the answer comes back. As two rows they read
  as two events that happened to be similar; joined, the row can show
  what went in *and* what came out. Punctuation and lookups are the same
  shape.
* **A polished dictation is two lines.** `OK` with what Whisper heard,
  then `POLISHED` with the same sentence after the language model repaired
  the misheard words. Showing both means showing the sentence twice, one
  of them wrong. The polish is folded into the dictation and marked.
* **A correction is a diff, written as prose.** `CORRECTED | before ||
  after` is two whole sentences that differ in two words. What the eye
  wants is the two words.

Nothing here writes. The log is the record; this is a reader, and a
malformed line is skipped rather than repaired.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
LOG = APP_DIR / "transcripts.log"

# "2026-08-20 20:55:13,139 | OK | ..."  — the ",139" is milliseconds, which
# nothing here shows and everything here ignores.
STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d{3} \| (.*)$")

# kind -> (what to call it, which glyph, which colour name in ui.py)
KINDS: dict[str, tuple[str, str, str]] = {
    "dictation": ("Dictation", "mic", "accent"),
    "translate": ("Translated", "translate", "teal"),
    "punctuate": ("Punctuated", "punctuate", "violet"),
    "lookup":    ("Looked up", "search", "green"),
    "learned":   ("Learned", "learned", "amber"),
    "error":     ("Failed", "error", "red"),
    "discarded": ("Discarded", "discarded", "faint"),
}

# The filter chips, in the order they appear. "All" is not a kind.
FILTERS: tuple[tuple[str, str | None], ...] = (
    ("All", None), ("Dictation", "dictation"), ("Translated", "translate"),
    ("Punctuated", "punctuate"), ("Looked up", "lookup"),
    ("Learned", "learned"), ("Failed", "error"),
)


@dataclass
class Event:
    when: datetime
    kind: str
    text: str = ""            # what came out, and what the row shows
    source: str = ""          # what went in, when the two differ
    seconds: float | None = None
    latency: float | None = None
    engine: str = ""
    note: str = ""
    pairs: list[tuple[str, str]] = field(default_factory=list)
    polished: bool = False
    phone: bool = False

    @property
    def label(self) -> str:
        return KINDS[self.kind][0]

    @property
    def icon(self) -> str:
        return KINDS[self.kind][1]

    @property
    def colour(self) -> str:
        return KINDS[self.kind][2]

    def meta(self) -> str:
        """The line under the text: how long, on what, how late."""
        bits: list[str] = []
        if self.seconds is not None:
            bits.append(f"{self.seconds:.1f} s")
        if self.engine:
            bits.append(self.engine)
        if self.latency is not None:
            bits.append(f"{self.latency:.1f} s latency")
        if self.phone:
            bits.append("from the phone")
        if self.polished:
            bits.append("polished")
        if self.note:
            bits.append(self.note)
        return "   ·   ".join(bits)

    def haystack(self) -> str:
        return f"{self.text} {self.source} {self.note} {self.engine}".lower()


def files() -> list[Path]:
    """The log and its rotated backups, newest first.

    `RotatingFileHandler(maxBytes=1_000_000, backupCount=3)`, so the whole
    history is at most four files and about four megabytes — small enough
    to read outright, which is why there is no index anywhere.
    """
    found = [LOG] if LOG.exists() else []
    found += [path for i in (1, 2, 3)
              if (path := LOG.with_name(LOG.name + f".{i}")).exists()]
    return found


def _seconds(text: str) -> float | None:
    match = re.match(r"\s*([\d.]+)\s*s\b", text)
    return float(match.group(1)) if match else None


def _records(path: Path) -> list[tuple[datetime, list[str]]]:
    """Split one file into stamped records, oldest first.

    A line that does not start with a timestamp is a continuation of the
    one before it: a dictation containing a newline is written raw, and
    treating its second line as its own record would put half a sentence
    in the list with the wrong time on it.
    """
    out: list[tuple[datetime, list[str]]] = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in raw.splitlines():
        match = STAMP.match(line)
        if not match:
            if out and line.strip():
                out[-1][1][-1] += "\n" + line
            continue
        try:
            when = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        out.append((when, match.group(2).split(" | ")))
    return out


def _tail(parts: list[str], first: int) -> str:
    """Everything from field `first` on, put back together.

    The text is joined rather than indexed because a transcript is allowed
    to contain " | " — say it out loud and Whisper will write it down —
    and splitting on it would silently drop the front of the sentence.
    """
    return " | ".join(parts[first:]).strip()


def _events_in(path: Path) -> list[Event]:
    """One file's worth, oldest first, already paired and folded."""
    events: list[Event] = []
    waiting: dict[str, tuple[datetime, str]] = {}   # family -> what went in

    for when, parts in _records(path):
        head = parts[0].strip().upper()

        if head == "OK":
            phone = len(parts) > 1 and parts[1].strip().upper() == "PHONE"
            if phone:
                # OK | PHONE | 3.1s | 0.4s latency | text
                events.append(Event(
                    when, "dictation", text=_tail(parts, 4), phone=True,
                    seconds=_seconds(parts[2]) if len(parts) > 2 else None,
                    latency=_seconds(parts[3]) if len(parts) > 3 else None))
            else:
                # OK | 4.4s | local | 0.5s latency | text
                events.append(Event(
                    when, "dictation", text=_tail(parts, 4),
                    seconds=_seconds(parts[1]) if len(parts) > 1 else None,
                    engine=parts[2].strip() if len(parts) > 2 else "",
                    latency=_seconds(parts[3]) if len(parts) > 3 else None))

        elif head == "DRAINED":
            events.append(Event(
                when, "dictation", text=_tail(parts, 3), note="recovered",
                seconds=_seconds(parts[1]) if len(parts) > 1 else None,
                engine=parts[2].strip() if len(parts) > 2 else ""))

        elif head == "POLISHED":
            # The same sentence, said better. It belongs to the dictation
            # above it, not beside it.
            for event in reversed(events):
                if event.kind == "dictation":
                    event.source = event.text
                    event.text = _tail(parts, 3)
                    event.polished = True
                    break

        elif head == "CORRECTED":
            shown, _, fixed = _tail(parts, 1).partition(" || ")
            pairs = changed_words(shown, fixed)
            events.append(Event(
                when, "learned", text=fixed or shown, source=shown,
                pairs=pairs,
                note=("1 word" if len(pairs) == 1 else f"{len(pairs)} words")
                if pairs else ""))

        elif head == "REVIEW":
            # REVIEW | accepted | before || after — a second-reading card
            # the owner said yes to (review.py). A rejection is a record,
            # not a lesson, and makes no row.
            if len(parts) > 1 and parts[1].strip().lower() == "accepted":
                before, _, after = _tail(parts, 2).partition(" || ")
                events.append(Event(
                    when, "learned", text=after or before, source=before,
                    pairs=[(before, after)] if after else [],
                    note="second reading"))

        elif head == "ERROR":
            kept = _tail(parts, 4)
            events.append(Event(
                when, "error", text=re.sub(r"^kept:\s*", "", kept),
                seconds=_seconds(parts[1]) if len(parts) > 1 else None,
                engine=parts[2].strip() if len(parts) > 2 else "",
                note=parts[3].strip() if len(parts) > 3 else ""))

        elif head == "DISCARDED":
            events.append(Event(
                when, "discarded", note=_tail(parts, 2),
                seconds=_seconds(parts[1]) if len(parts) > 1 else None))

        elif head.endswith("-IN"):
            waiting[head[:-3].lower()] = (when, _tail(parts, 2))

        elif head.endswith("-OUT"):
            family = head[:-4].lower()
            if family not in KINDS:
                continue
            started, source = waiting.pop(family, (when, ""))
            events.append(Event(
                started, family, text=_tail(parts, 3), source=source,
                seconds=_seconds(parts[1]) if len(parts) > 1 else None,
                engine=parts[2].strip() if len(parts) > 2 else ""))

    return events


def load(limit: int = 100) -> list[Event]:
    """The most recent `limit` events, newest first.

    Files are read newest first and stopped as soon as there are enough,
    so the usual case touches one file. The cost of that: an `-IN` at the
    end of one file whose `-OUT` landed in the next loses the text that
    went in. The alternative is reading four megabytes to show fifty rows.
    """
    events: list[Event] = []
    for path in files():
        events = _events_in(path) + events
        if len(events) >= limit:
            break
    events.reverse()
    return events[:limit]


def changed_words(before: str, after: str) -> list[tuple[str, str]]:
    """The words a correction changed, as pairs.

    Only when the two sentences have the same number of words, which is
    what a vocabulary correction is: a word swapped for another word.
    Anything else — a sentence rewritten, a clause dropped — has no
    word-for-word answer, and guessing one would put a pair on screen that
    the owner never made.
    """
    old, new = before.split(), after.split()
    if len(old) != len(new) or not old:
        return []
    return [(a, b) for a, b in zip(old, new) if a != b][:6]


def filtered(events: list[Event], kind: str | None,
             query: str = "") -> list[Event]:
    """What the chips and the search box leave behind."""
    query = query.strip().lower()
    out = events
    if kind:
        out = [e for e in out if e.kind == kind]
    if query:
        out = [e for e in out if query in e.haystack()]
    return out


def stamp() -> tuple[int, float]:
    """Size and mtime of the live log, to notice it changed without
    reading it. Called from the status poller every 800 ms."""
    try:
        info = LOG.stat()
        return info.st_size, info.st_mtime
    except OSError:
        return 0, 0.0
