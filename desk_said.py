"""Said on the web desk: transcripts.log read back, as data.

WHAT IT IS. The Tk desk's Said place (dashboard._screen_said and what
it calls): the search, the filter chips (history.FILTERS), SAID_PAGE
rows at a time behind a Show more (_said_more), the other PCs' REMOTE
rows as "from <device>", the vocabulary panel beside the list
(_vocab_panel: the count, the teach key, the last pairs it learned), a
click on a row that copies it (_copy), and "Open transcripts.log". Same
sources, same words — history.py is the reader both use, and the page
only draws what this answers.

THE LOOK MOVED A FEW WORDS, NOT THE WORDS. The approved picture
(design/2026-09-22/design/rev/lists/said.png) groups the rows by day
under one eyebrow ("Today · 47 today · 9 minutes of speech") and so
takes the date off each row; it puts a row's seconds under its time and
its marks (Polished, From the phone, from <device>, Second reading...)
on small tags. Everything else a Tk row said in its meta line — the
engine and the latency — is the tag column's second line here, under
the tags, level with the seconds: the picture left them out, and they
are the one place he sees how fast a dictation was (AGENTS rule 5).

READING. history.load(HISTORY_ROWS), again only when history.stamp()
moves — the Tk desk's poller rule: a stat costs nothing, a parse costs
tens of milliseconds. The page polls `read` every 800 ms (the Tk
desk's cadence) with what it is showing (filter, q, shown); an answer
identical to the last is drawn as nothing (kit.usePlace).

HIS WORDS. transcripts.log is his own speech: it goes into the answer
to the page and nowhere else — never a log line (app.log gets a type
name when something fails), never an error message. A copy takes the
row by its id from the log this module read, never text the page
sends; it goes on the clipboard through injector, the one writer of it
(AGENTS: "Anything new that touches the clipboard goes through
injector"), from this process, with a second try when another program
holds it. "Open transcripts.log" opens that one fixed path.

HOW IT IS REACHED. deskweb.Api.place("said", op, args) is the one caller
(deskweb.PLACES_MOD); one Place per window, built with the window's
pipe function — which Said never needs: every source is a file. Calls
come on threads of their own, so the state is behind a lock. Everything
the page sends is untrusted: `do` is allowlisted, and filter, q, shown
and a row's id are checked before they reach anything.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta

import config as config_mod
import deskweb
import history
import launch
import paths

log = logging.getLogger("app")

#: rows a press of Show more adds (dashboard.SAID_PAGE): "a hundred at
#: once was, in his words, a lot to scroll and it is a nightmare"
SAID_PAGE = 25
#: what "the last hundred" means (dashboard.HISTORY_ROWS)
HISTORY_ROWS = 100
#: the longest search the page may send; a longer one is cut, not refused
QUERY_MOST = 200
#: a row's id, as this module makes them, is never longer than this
ID_MOST = 48
#: how many pairs Lately offers; the panel shows what fits
LATELY_MOST = 7
#: how many of a learned row's pairs it draws (dashboard._history_row)
ROW_PAIRS = 4
#: the vocabulary panel's facts from the config are read again after this
CONFIG_S = 2.0
#: what the clipboard gets before a copy gives up: injector already
#: retries the open ten times 50 ms apart; this is the second round
COPY_TRIES = 2
COPY_PAUSE_S = 0.15

#: the filter keys the page sends: history.FILTERS' kinds, "" for All
FILTER_KEYS = tuple(kind or "" for _name, kind in history.FILTERS)

#: Words the Tk desk draws, kept in one place so a test can hold them.
SUB = f"the last {HISTORY_ROWS} of what you said"
PLACEHOLDER = "Search everything you have said…"
OLDER = "Everything older is still in transcripts.log, untouched."
OPEN = "Open transcripts.log"
EMPTY_OFF = "History is off (Settings > Privacy > Kept on this PC)."
EMPTY_NONE = "Nothing here yet."
EMPTY_MISS = "Nothing matches that."
NOTHING_LEARNED = ("Nothing learned yet — say Yes to a second reading, or "
                   "press the teach key on a word it got wrong.")

#: history.KINDS' colour names, as the page's kind classes
_KIND_CLASS = {"dictation": "dict", "translate": "trans", "punctuate": "punct",
               "lookup": "look", "learned": "learn", "error": "fail",
               "discarded": "gone"}


def _today() -> date:
    return datetime.now().date()


def _cap(text: str) -> str:
    """"second reading" -> "Second reading": a tag starts with a capital,
    the rest is the log's own word."""
    return text[:1].upper() + text[1:] if text else text


def _speech(seconds: float) -> str:
    """How long a day's dictations were, said the way the picture says it."""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        n = int(round(seconds))
        return f"{n} second{'' if n == 1 else 's'} of speech"
    minutes = int(round(seconds / 60))
    if minutes < 90:
        return f"{minutes} minute{'' if minutes == 1 else 's'} of speech"
    return f"{minutes // 60} h {minutes % 60:02d} min of speech"


def _day_label(day: date, today: date) -> str:
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    label = day.strftime("%d %b").lstrip("0")      # the Tk row's date, "21 Oct"
    return label if day.year == today.year else f"{label} {day.year}"


def _filter_key(value) -> str | None:
    """The page's filter as a history.FILTERS kind; None for All. A key
    that is not a filter is a ValueError (refused in words by read)."""
    if value is None or value == "":
        return None
    if isinstance(value, str) and value in FILTER_KEYS:
        return value
    raise ValueError("not a filter")


def _shown(value) -> int:
    """How many rows the page asks for: SAID_PAGE at least, every row at
    most, whole numbers only — anything else is the first page."""
    if isinstance(value, bool) or not isinstance(value, int):
        return SAID_PAGE
    return max(SAID_PAGE, min(HISTORY_ROWS, value))


class Place:
    """Said, as data, and what its buttons do. One per window."""

    def __init__(self, send) -> None:
        self._send = send                 # the window's pipe; Said reads files only
        self._lock = threading.Lock()
        self._stamp = None
        self._log: list = []
        #: row id -> its Event, for the log as last read (a copy names one)
        self._by_id: dict = {}
        self._ids: list[str] = []
        self._config_at = 0.0
        self._config: tuple = ("", None, 30)
        self._vocab_key = None
        self._vocab_pairs: list = []
        self._vocab_count: int | None = None

    # -- reading

    def _fresh_log(self) -> None:
        """history.load again, only when the log or the other PCs' file moved."""
        stamp = history.stamp()
        if stamp == self._stamp:
            return
        try:
            events = history.load(HISTORY_ROWS)
        except Exception as e:            # noqa: BLE001 — a log being rotated
            log.warning("said: the log could not be read (%s)", type(e).__name__)
            return
        self._stamp = stamp
        self._log = list(events)
        self._by_id, self._ids = {}, []
        for event in self._log:
            base = f"{event.when:%Y%m%d%H%M%S%f}-{event.kind}"
            ident, n = base, 1
            while ident in self._by_id:
                n += 1
                ident = f"{base}-{n}"
            self._by_id[ident] = event
            self._ids.append(ident)

    def _facts(self) -> tuple:
        """(the teach key, the decoder's cap, history kept days) from the
        layered config, read again every CONFIG_S — the file is the truth
        once a key is rebound (dashboard._read_keys, its fallback)."""
        now = time.monotonic()
        if now - self._config_at < CONFIG_S:
            return self._config
        try:
            cfg = config_mod.load_layered()
            self._config = (getattr(cfg, "correct_hotkey", "") or "",
                            getattr(getattr(cfg, "vocab", None), "max_terms", None),
                            getattr(getattr(cfg, "history", None), "keep_days", 30))
        except Exception:                 # noqa: BLE001 — an unreadable config
            self._config = ("", None, 30)
        self._config_at = now
        return self._config

    def _recent_pairs(self, limit: int) -> list[tuple[str, str]]:
        """The last corrections, newest first — out of the log when it has
        learned rows, out of vocab.json when it does not
        (dashboard._recent_pairs, the same order and the same fallback)."""
        out: list = []
        for event in self._log:
            if event.kind != "learned":
                continue
            for pair in (event.pairs or []):
                if not (isinstance(pair, (tuple, list)) and len(pair) == 2):
                    continue
                out.append((str(pair[0]), str(pair[1])))
                if len(out) >= limit:
                    return out
        if out:
            return out
        import json
        try:
            with paths.VOCAB_FILE.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return out
        entries = data.get("corrections") if isinstance(data, dict) else []
        for entry in reversed(entries or []):
            if not isinstance(entry, dict):
                continue
            heard = str(entry.get("heard") or "")
            meant = str(entry.get("meant") or "")
            if heard and meant:
                out.append((heard, meant))
            if len(out) >= limit:
                break
        return out

    def _vocab(self) -> dict:
        teach, cap, _days = self._facts()
        try:
            st = paths.VOCAB_FILE.stat()
            vocab_stamp = (st.st_size, st.st_mtime_ns)
        except OSError:
            vocab_stamp = None
        key = (vocab_stamp, self._stamp)
        if key != self._vocab_key:
            # vocab.json is read again only when it (or the log) moved
            self._vocab_key = key
            self._vocab_pairs = [_pair(w, r) for w, r in self._recent_pairs(LATELY_MOST)]
            self._vocab_count = deskweb.words_learned()
        learned = self._vocab_count
        return {
            "eyebrow": "Vocabulary",
            "count": "—" if learned is None else str(learned),
            "w": "words",
            "w2": "it has learned to hear your way",
            "teach": deskweb.key_caps(teach) or [deskweb.pretty_key("")],
            "teach_words": "teach it a word",
            "lately": "Lately",
            "pairs": self._vocab_pairs,
            "nothing": NOTHING_LEARNED,
            "foot": ("The best of them go into the decoder's prompt before it "
                     f"listens — {cap} at a time." if cap
                     else "The best of them go into the decoder's prompt "
                          "before it listens."),
        }

    def read(self, filter=None, q="", shown=SAID_PAGE, **extra) -> dict:  # noqa: A002 — the page's word
        """Everything the place draws, for what the page is showing."""
        if extra:
            return {"ok": False, "error": "Said reads filter, q and shown"}
        try:
            kind = _filter_key(filter)
        except ValueError:
            return {"ok": False, "error": "that is not one of the filters"}
        query = q[:QUERY_MOST] if isinstance(q, str) else ""
        limit = _shown(shown)
        with self._lock:
            self._fresh_log()
            return self._answer(kind, query, limit)

    def _answer(self, kind, query: str, limit: int) -> dict:
        events = self._log
        found = history.filtered(events, kind, query)
        rows = found[:limit]
        ident = {id(e): i for i, e in zip(self._ids, events)}
        today = _today()
        # the oldest day of a full window may have been cut by the hundred:
        # its count would be a guess, so it says none
        cut = events[-1].when.date() if len(events) >= HISTORY_ROWS else None
        said: dict = {}
        for event in events:
            if event.kind == "dictation":
                n, s = said.get(event.when.date(), (0, 0.0))
                said[event.when.date()] = (n + 1, s + (event.seconds or 0.0))
        days: list = []
        for event in rows:
            day = event.when.date()
            # a day may come round twice: a translation carries the time it
            # STARTED, so one begun before midnight can follow a dictation
            # made after it — each run of a day is a group with a key of its own
            if not days or days[-1]["date"] != day.isoformat():
                n, s = said.get(day, (0, 0.0))
                facts: list = []
                if n and day != cut:
                    facts.append(f"{n} {'today' if day == today else 'that day'}")
                    if s:
                        facts.append(_speech(s))
                days.append({"key": f"{day.isoformat()}#{len(days)}",
                             "date": day.isoformat(), "day": _day_label(day, today),
                             "facts": facts, "rows": []})
            days[-1]["rows"].append(_row(event, ident.get(id(event), "")))
        empty = ""
        if not found:
            _teach, _cap, keep_days = self._facts()
            off = isinstance(keep_days, (int, float)) and keep_days <= 0
            empty = (EMPTY_OFF if off and not events
                     else EMPTY_NONE if not events else EMPTY_MISS)
        left = len(found) - len(rows)
        more = None
        if left > 0:
            more = {"words": f"Show {min(left, SAID_PAGE)} more",
                    "left": f"{left} older still here"}
        return {
            "ok": True,
            "head": "Said",
            "sub": SUB,
            "placeholder": PLACEHOLDER,
            "filters": [{"name": name, "key": key or ""} for name, key in history.FILTERS],
            "filter": kind or "",
            "q": query,
            "shown": limit,
            "days": days,
            "more": more,
            "empty": empty,
            "vocab": self._vocab(),
            "older": OLDER,
            "open": OPEN,
        }

    # -- the buttons

    def act(self, do: str, arg=None) -> dict:
        do = str(do)
        if do == "copy":
            return self._copy(arg)
        if do == "open":
            if not launch.open_path(history.LOG):
                return {"ok": True, "note": "could not open transcripts.log"}
            return {"ok": True, "note": ""}
        return {"ok": False, "error": f"{do[:40]!r} is not a Said action"}

    def _copy(self, arg) -> dict:
        """One row's text on the clipboard (dashboard._copy): the row is
        named by its id, and its text is the log's — event.text or what
        went in — never words the page sends."""
        if not isinstance(arg, str) or not 0 < len(arg) <= ID_MOST:
            return {"ok": True, "note": "that one is not in the list", "copied": False}
        with self._lock:
            event = self._by_id.get(arg)
        if event is None:
            return {"ok": True, "note": "that one is not in the list any more",
                    "copied": False}
        text = event.text or event.source
        if not text:
            return {"ok": True, "note": "there is no text on that one", "copied": False}
        import injector
        for attempt in range(COPY_TRIES):
            try:
                injector.set_text(text)
                break
            except Exception as e:        # noqa: BLE001 — another program holds it
                if attempt + 1 < COPY_TRIES:
                    time.sleep(COPY_PAUSE_S)
                    continue
                log.warning("said: the copy did not reach the clipboard (%s)",
                            type(e).__name__)
                return {"ok": True, "note": "the clipboard is busy — try again in a moment",
                        "copied": False}
        return {"ok": True, "note": f"copied {len(text)} characters", "copied": True}


def _pair(heard: str, meant: str) -> dict:
    return {"heard": heard, "meant": meant, "rtl": deskweb.is_rtl(heard + meant)}


def _row(event, ident: str) -> dict:
    """One event as the row draws it: its time and seconds, its kind's
    disc, its tags, the engine and latency under them, and its text —
    or, for a learned row, the pairs (the two words, not the two
    sentences they came out of)."""
    tags: list = []
    if event.kind != "dictation":
        tags.append({"t": event.label})
    if event.phone:
        tags.append({"t": "From the phone", "g": "phone"})
    if event.polished:
        tags.append({"t": "Polished", "g": "pip"})
    # a discarded row's note is its text (it has no other), not a tag
    notes = "" if event.kind == "discarded" else (event.note or "")
    for bit in notes.split("   ·   "):
        bit = bit.strip()
        if not bit:
            continue
        if bit.startswith("from "):
            tags.append({"t": _cap(bit), "g": "laptop"})
        else:
            tags.append({"t": _cap(bit)})
    meta = []
    if event.engine:
        meta.append(event.engine)
    if event.latency is not None:
        meta.append(f"{event.latency:.1f} s latency")
    pairs = []
    if event.kind == "learned":
        pairs = [_pair(str(w), str(r)) for w, r in (event.pairs or [])[:ROW_PAIRS]]
    text = event.text or event.note or ""
    return {
        "id": ident,
        "kind": _KIND_CLASS.get(event.kind, "dict"),
        "glyph": event.icon,
        "label": event.label,
        "when": event.when.strftime("%H:%M"),
        "secs": f"{event.seconds:.1f} s" if event.seconds is not None else "",
        "tags": tags,
        "meta": meta,
        "text": "" if pairs else text,
        "rtl": deskweb.is_rtl(text),
        "dim": event.kind == "discarded",
        "pairs": pairs,
        "copy": bool(event.text or event.source),
    }
