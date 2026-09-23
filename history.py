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

import contextlib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import paths

APP_DIR = Path(__file__).resolve().parent
LOG = paths.TRANSCRIPTS_LOG

# "2026-08-20 20:55:13,139 | OK | ..."  — the ",139" is milliseconds. No
# row shows them, but the event keeps them: they are what tells two
# second-reading verdicts accepted in the same second apart when the
# account sync keys a row by its time (sync.history_rows, 2026-09-20).
STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d{3}) \| (.*)$")

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
        when = when.replace(microsecond=int(match.group(2)) * 1000)
        out.append((when, match.group(3).split(" | ")))
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

        elif head == "REMOTE":
            # REMOTE | kind | device | engine | 3.1s | text — what another
            # PC of the same account said, pulled by sb.py into
            # sync\history.log (sync.remote_line, D31). The row shows the
            # machine's name where a phone row says "from the phone". A
            # learned row's text is "shown || fixed", the CORRECTED
            # line's own shape, so the pair reaches the Corrections
            # page's Lately list from the other PC too (2026-09-20).
            kind = parts[1].strip().lower() if len(parts) > 1 else ""
            if kind not in KINDS:
                continue
            text = _tail(parts, 5)
            source, pairs, note = "", [], ""
            if kind == "learned" and " || " in text:
                source, _, text = text.partition(" || ")
                pairs = changed_words(source, text)
                note = "1 word" if len(pairs) == 1 else f"{len(pairs)} words"
            where = (f"from {parts[2].strip()}" if len(parts) > 2 and parts[2].strip()
                     else "from another PC")
            events.append(Event(
                when, kind, text=text, source=source, pairs=pairs,
                engine=parts[3].strip() if len(parts) > 3 else "",
                seconds=_seconds(parts[4]) if len(parts) > 4 else None,
                note=f"{note}   ·   {where}" if note else where))

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


#: Set by apply(): False when [history] keep_days = 0, so the Recent
#: view can say why it is empty rather than "nothing yet".
enabled: bool = True

#: Why the checkout's own data is never pruned: its transcripts,
#: recordings and read-aloud pairs are the owner's training data
#: (paths.OWNER_DATA, AGENTS.md).
DEVELOPER_KEEPS_EVERYTHING = "the checkout keeps every line (training data)"


def apply(cfg, transcript_logger=None) -> str:
    """Take [history] keep_days at start: 0 detaches the transcripts
    handler (nothing is written, the Recent view says so); N prunes lines
    older than N days from the log and its rotated siblings, except in
    a developer copy. Returns one line for app.log."""
    import logging

    global enabled
    days = int(getattr(getattr(cfg, "history", None), "keep_days", 30))
    logger = transcript_logger or logging.getLogger("transcripts")
    if days <= 0:
        enabled = False
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:                                # noqa: BLE001
                pass
        return "history is off ([history] keep_days = 0): nothing is written"
    enabled = True
    if paths.OWNER_DATA:
        return (f"history: keep_days = {days} is not applied — "
                f"{DEVELOPER_KEEPS_EVERYTHING}")
    with _released(logger):
        dropped, removed = prune(days)
    return (f"history: kept {days} days ({dropped} older line(s) dropped, "
            f"{removed} old file(s) removed)")


@contextlib.contextmanager
def _released(logger):
    """The transcripts handler lets go of the log for the length of a
    prune, and takes it back after.

    main.setup_logging opens transcripts.log (RotatingFileHandler, no
    delay) long before the config — and so keep_days — is read, and
    Python opens a file without FILE_SHARE_DELETE, so os.replace onto
    the open log fails on Windows. It failed on EVERY installed copy:
    the old lines stayed, a second copy of the text sat beside it in
    transcripts.log.tmp, and app.log said they had been dropped (audit
    2026-09-23, A8; probed in a scratch home with a real handler open:
    (1, 0) reported, the line still there). The handler's own lock is
    held throughout, so a line written from another thread waits for the
    prune instead of reopening the file under it; a stream that will not
    reopen stays None, and FileHandler.emit opens it on the next line."""
    held = [h for h in list(getattr(logger, "handlers", ()))
            if isinstance(h, logging.FileHandler)
            and os.path.normcase(h.baseFilename)
            == os.path.normcase(os.path.abspath(LOG))]
    for handler in held:
        handler.acquire()
    try:
        for handler in held:
            stream, handler.stream = handler.stream, None
            if stream is not None:
                try:
                    stream.flush()
                    stream.close()
                except (OSError, ValueError):
                    pass
        yield
    finally:
        for handler in held:
            try:
                if handler.stream is None:
                    handler.stream = handler._open()
            except OSError:
                pass
            finally:
                handler.release()


def prune(days: int, now: datetime | None = None) -> tuple[int, int]:
    """Drop lines older than `days` from the log, atomically, and delete
    rotated siblings whose newest line is older than that. Returns
    (lines dropped, files removed). Never raises for a missing file.

    A line is counted only once the file it was in no longer holds it:
    the count is what app.log reports as done, and it used to be
    counted before a replace that could fail. A replace that fails
    takes its .tmp with it — that file is a second copy of the text."""
    now = now or datetime.now()
    cutoff = now.timestamp() - days * 86400
    dropped = removed = 0
    for path in files():
        try:
            lines = path.read_text("utf-8", errors="replace").splitlines(keepends=True)
        except OSError:
            continue
        kept = []
        for line in lines:
            match = STAMP.match(line)
            if match:
                try:
                    when = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
                except ValueError:
                    when = None
                if when is not None and when < cutoff:
                    continue
            kept.append(line)
        if len(kept) == len(lines):
            continue
        if path != LOG and not any(STAMP.match(l) for l in kept):
            try:
                path.unlink()
                removed += 1
                dropped += len(lines) - len(kept)
            except OSError:
                pass
            continue
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_text("".join(kept), "utf-8")
            os.replace(tmp, path)
            dropped += len(lines) - len(kept)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
    return dropped, removed


def remote_files() -> list[Path]:
    """What the other PCs of the account said (sync\history.log, written
    by sb.py) — one file, present only for a signed-in user who turned
    the history sync on."""
    path = paths.SYNC_DIR / "history.log"
    return [path] if path.exists() else []


def all_events() -> list[Event]:
    """Every event of this PC's own log and its rotations, oldest first
    — what the account sync pushes (sb.py, D31). The other PCs' lines
    are not in it: they came from the server and do not go back."""
    return [ev for path in reversed(files()) for ev in _events_in(path)]


def load(limit: int = 100) -> list[Event]:
    """The most recent `limit` events, newest first.

    Files are read newest first and stopped as soon as there are enough,
    so the usual case touches one file. The cost of that: an `-IN` at the
    end of one file whose `-OUT` landed in the next loses the text that
    went in. The alternative is reading four megabytes to show fifty rows.
    The other PCs' lines are read whole and merged by time: they are the
    one file whose newest row may be older than this PC's oldest.
    """
    events: list[Event] = []
    for path in files():
        events = _events_in(path) + events
        if len(events) >= limit:
            break
    remote = [ev for path in remote_files() for ev in _events_in(path)]
    if remote:
        events = sorted(events + remote, key=lambda e: e.when)
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


def stamp() -> tuple:
    """Size and mtime of the live log AND of the other PCs' pulled file,
    to notice either changed without reading it. Called from the status
    poller every 800 ms. The pulled file is in it since 2026-09-20: a
    row that arrived from the other PC used to wait on the desk until
    this PC's own next dictation touched transcripts.log."""
    out: list = []
    for path in (LOG, paths.SYNC_DIR / "history.log"):
        try:
            info = path.stat()
            out += [info.st_size, info.st_mtime]
        except OSError:
            out += [0, 0.0]
    return tuple(out)
