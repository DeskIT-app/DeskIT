"""A question the weekly routine could not answer for itself, asked where
he already is.

The routine reads his problem reports, fixes what it can and — when a
report cannot be explained from its own evidence — writes a question and
stops. Until now that question went into a markdown file, which means the
only way to answer it was to open a chat, find the line, and type a
paragraph back. He asked for the other half: the routine formulates a
question with a few concrete options and a box he types into, the card
and the dashboard show it to him inside the app, and the moment he
confirms an answer the routine has what it needs to build. No chat,
ever. This module is that handover, and it is only a file: the routine
writes questions into it, the app writes his answer back, and the
routine reads the answer on its next wake.

TWO TO FIVE REAL OPTIONS, AND A TEXT BOX THAT IS ALWAYS THERE. Every
entry in `options` is a choice he can pick, and no position in the list
means anything — the box is not an option, it is a permanent part of the
card. That is why the count is adaptive: a question with two honest
answers gets two, and nothing has to be invented to fill a slot.

The rejected alternative is worth naming because it is what this module
did first: a last option reading "something else — I'll write it". It is
a choice that is not a choice. It cost one of the slots, it made the same
list mean two different things depending on index, and it made him click
it before he could type. Both at once is the point — he wants to pick
"run before the backup" AND add "actually after the backup, so that…",
refining a canned option instead of choosing between canned ones. An
imported item with no options at all is not a special case either; it is
a card with nothing to click and the same box underneath.

NOTHING HERE EVER WRITES AN ANSWER ON ITS OWN BEHALF. There is no API to
answer as the routine, and that omission is the point of the module. The
routine may ask, may read what he answered, and may mark what it then
built — but it has no way to manufacture the approval it is waiting for,
so a `questions.json` showing an ANSWERED item is evidence that HE
answered it. answer() is for the card and the dashboard; import_asked()
carries over answers he has already given elsewhere and records them as
his (`by="owner"`), never as anyone else's.

THE STORE REFUSES A STALE ANSWER. answer() works only on a PENDING item:
the card he is looking at may have been drawn before the dashboard
answered the same question in the other window, and the second write
must lose rather than overwrite a decision he has already made.
mark_built() likewise only moves an ANSWERED item, so nothing can be
built off a question he has not answered.

PENDING AND ANSWERED ARE NEVER TRIMMED. A pending question is one he has
not seen yet; an answered one is work the routine still owes him.
BUILT and DROPPED age out at KEEP_DONE, oldest first — problems.py trims
resolved reports and review.py trims decided proposals on the same
reasoning, and for the same reason the live half is exempt.

NOTHING HERE MAY TAKE DICTATION DOWN. The store is the shape review.py
settled on and problems.py copied — a lock file beside the json so the
app, the dashboard and the routine do not write over each other, a
per-process temp name and one rename so a reader never sees half a file,
an unparseable file read as empty — and every filesystem error is logged
and swallowed. The single deliberate exception is clean() refusing a
question with no text or an unusable option list, because that is a bug
in the caller that has to be told before a card gets drawn.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("app")

STORE_NAME = "questions.json"

# PENDING is waiting on him. ANSWERED is waiting on the routine. BUILT is
# what the routine did with his answer; DROPPED is a question that stopped
# mattering before he got to it.
PENDING, ANSWERED, BUILT, DROPPED = "pending", "answered", "built", "dropped"
STATUSES = (PENDING, ANSWERED, BUILT, DROPPED)
LIVE = (PENDING, ANSWERED)
DONE = (BUILT, DROPPED)

# However many the question actually has, between two and five. Two is
# the floor because a single option is not a choice. Five is the ceiling
# because the card is one column on a small window and a sixth row starts
# pushing the text box off the bottom. Everything in between is the
# routine's to choose: the range exists so it never has to invent an
# option to reach a fixed count.
OPTIONS_MIN, OPTIONS_MAX = 2, 5

QUESTION_MAX, ANSWER_MAX = 400, 600
OPTION_MAX = 140
REPORT_MAX = 40
BY_MAX = 40
BRANCH_MAX = 80
NOTE_MAX = 400

# Built and dropped questions kept, oldest dropped first. Pending and
# answered ones are NEVER trimmed.
KEEP_DONE = 200

# C0 controls minus tab and newline, exactly problems.clean's set: an
# escape sequence in a question is at best formatting and at worst a way
# to talk to whatever terminal ends up printing it.
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_STAMP = "%Y%m%d-%H%M%S"


# ---------------------------------------------------------------------------
# the input gate
# ---------------------------------------------------------------------------

def _text(value) -> str:
    if isinstance(value, (str, int, float)):
        return str(value)
    return ""


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 1] + "…"


def _line(value, limit: int) -> str:
    """One line: controls gone, whitespace collapsed, cut to `limit`."""
    text = _CONTROLS.sub("", _text(value).replace("\r", "\n"))
    return _cut(" ".join(text.split()), limit)


def _body(value, limit: int) -> str:
    """Several lines: controls gone, trailing space per line gone, runs of
    blank lines collapsed to one, cut to `limit`. Newlines survive because
    he may dictate two sentences into the text box."""
    text = _CONTROLS.sub("", _text(value).replace("\r\n", "\n")
                         .replace("\r", "\n"))
    lines = [ln.rstrip() for ln in text.split("\n")]
    return _cut(re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip(), limit)


def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def clean(question: str, options: list[str]) -> tuple[str, list[str]]:
    """The one gate every question passes through on its way in.

    The question becomes a single line, the options are cleaned, emptied
    of blanks and de-duplicated in place, and everything is cut to its
    maximum. Order is preserved because it is the order he reads them in,
    and for no other reason: no position is special.

    Raises ValueError for a question with no text, for fewer than
    OPTIONS_MIN surviving options and for more than OPTIONS_MAX.
    Refusing, rather than padding the short list or trimming the long
    one, is the honest move: every entry is an answer he might pick, so
    inventing a filler or dropping the tail changes the question he is
    being asked. A caller that cannot put it in two to five choices has
    to hear that from here, not have the store silently re-word it."""
    text = _line(question, QUESTION_MAX)
    if not text:
        raise ValueError("a question needs a line of text")
    if isinstance(options, (str, bytes)) or not isinstance(options,
                                                           (list, tuple)):
        raise ValueError("options must be a list of strings")
    out: list[str] = []
    for option in options:
        cleaned = _line(option, OPTION_MAX)
        if cleaned and cleaned not in out:
            out.append(cleaned)
    if len(out) < OPTIONS_MIN:
        raise ValueError(f"a question needs at least {OPTIONS_MIN} real "
                         f"options, got {len(out)}")
    if len(out) > OPTIONS_MAX:
        raise ValueError(f"a question takes at most {OPTIONS_MAX} options, "
                         f"got {len(out)}")
    return text, out


def _options(item: dict) -> list[str]:
    """The options as stored, defensively — a hand-edited file may have
    put anything in there."""
    raw = item.get("options")
    if not isinstance(raw, (list, tuple)):
        return []
    return [_text(o) for o in raw if _text(o)]


def _index(choice, options: list[str]) -> int | None:
    """The option `choice` points at, or None when it points at nothing.

    bool is refused before int because True would otherwise be option
    one, and a caller handing a checkbox state to a choice index means
    something else than that."""
    if choice is None or isinstance(choice, bool):
        return None
    try:
        idx = int(choice)
    except (TypeError, ValueError):
        return None
    return idx if 0 <= idx < len(options) else None


# ---------------------------------------------------------------------------
# the store: questions on disk, shared by the app, the dashboard and the
# routine
# ---------------------------------------------------------------------------

class Store:
    """questions.json, edited by three processes.

    A lock file beside it (msvcrt.locking on Windows) serialises the
    read-modify-write between the app, the dashboard and the headless
    weekly routine; inside one process an RLock does the same between
    threads. Every write lands through a per-process temporary file and
    one rename, so a reader never sees half a file and two writers cannot
    destroy it (the shared temp name cost config.toml the whole file, 4
    runs out of 4 — see config.py). A file that will not parse is read as
    empty rather than fatal: a broken store must cost questions, not
    dictation."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(".lock")
        self.keep = KEEP_DONE
        self._lock = threading.RLock()

    # ---- the file ----

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            return {"version": 1, "items": []}
        except Exception as e:            # noqa: BLE001
            log.warning("questions: questions.json unreadable (%s) — "
                        "starting empty", e)
            return {"version": 1, "items": []}
        items = data.get("items") if isinstance(data, dict) else None
        return {"version": 1,
                "items": [i for i in (items or []) if isinstance(i, dict)]}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       "utf-8")
        os.replace(tmp, self.path)

    @contextmanager
    def _locked(self):
        with self._lock:
            fd = None
            held = False
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT)
                try:
                    import msvcrt
                    for _ in range(100):           # up to ~5 s
                        try:
                            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                            held = True
                            break
                        except OSError:
                            time.sleep(0.05)
                except ImportError:
                    pass
                if fd is not None and not held:
                    log.info("questions: questions.json lock busy — "
                             "writing anyway")
                yield
            finally:
                if fd is not None:
                    if held:
                        try:
                            import msvcrt
                            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                        except Exception:  # noqa: BLE001
                            pass
                    os.close(fd)

    def _trim(self, data: dict) -> None:
        """Only built and dropped questions age out. A pending one is
        waiting on him and an answered one is waiting on the routine, and
        neither is ours to forget."""
        items = data["items"]
        done = [i for i in items if i.get("status") in DONE]
        if len(done) > self.keep:
            extra = len(done) - self.keep
            oldest = sorted(done, key=lambda i: str(i.get("built")
                                                    or i.get("answered")
                                                    or i.get("at") or ""))
            drop = {id(i) for i in oldest[:extra]}
            data["items"] = [i for i in items if id(i) not in drop]

    def _next_id(self, items: list[dict]) -> str:
        """A timestamp, with a -1/-2 suffix when a second already has a
        question in it — problems.py names reports the same way, and
        import_asked adds several inside one second."""
        taken = {str(i.get("id")) for i in items}
        base = time.strftime(_STAMP)
        ident, n = base, 1
        while ident in taken:
            ident = f"{base}-{n}"
            n += 1
        return ident

    # ---- reads ----

    def items(self, status: str | None = None) -> list[dict]:
        """Newest first. `status` filters to one of PENDING/ANSWERED/
        BUILT/DROPPED; None is everything."""
        with self._lock:
            rows = list(self._load()["items"])
        if status is not None:
            rows = [i for i in rows if i.get("status") == status]
        rows.sort(key=lambda i: (str(i.get("at", "")), str(i.get("id", ""))),
                  reverse=True)
        return rows

    def get(self, ident: str) -> dict | None:
        return next((i for i in self.items() if i.get("id") == ident), None)

    def for_report(self, report_id: str) -> list[dict]:
        """Every question ever asked about one report, newest first and in
        every state — what the routine reads to find out whether it has
        already asked, and what it was told."""
        want = _line(report_id, REPORT_MAX)
        return [i for i in self.items()
                if str(i.get("report_id") or "") == want]

    def summary(self) -> dict:
        """What a badge and a header say: how many in each state, how many
        answers the routine still owes a build, and how long the oldest
        unanswered question has been waiting."""
        out: dict = {PENDING: 0, ANSWERED: 0, BUILT: 0, DROPPED: 0,
                     "total": 0, "awaiting_build": 0,
                     "oldest_pending": "", "oldest_pending_id": ""}
        oldest = None
        for item in self.items():
            status = str(item.get("status") or PENDING)
            out[status] = out.get(status, 0) + 1
            out["total"] += 1
            if status == PENDING:
                at = str(item.get("at", ""))
                if oldest is None or at < str(oldest.get("at", "")):
                    oldest = item
        out["awaiting_build"] = out.get(ANSWERED, 0)
        if oldest is not None:
            out["oldest_pending"] = str(oldest.get("at", ""))
            out["oldest_pending_id"] = str(oldest.get("id", ""))
        return out

    def stamp(self) -> tuple:
        """(size, mtime_ns), or () when there is no file — the
        dashboard's change detector, without reading the file."""
        try:
            st = self.path.stat()
        except OSError:
            return ()
        return (st.st_size, st.st_mtime_ns)

    # ---- writes ----

    def ask(self, report_id: str, question: str, options: list[str]) -> dict:
        """Put one question to him and hand back what was stored.

        `report_id` is the problems.json id the question is about, or ""
        for a question about nothing in particular. Two to five options,
        every one of them a real choice — the card's text box is not one
        of them and is always there. clean() raises ValueError on an
        empty question or a bad option list, which is the only exception
        out of this module.

        Asking a question that is already PENDING for the same report,
        word for word, returns the standing item instead of a second
        card. The routine's rule is that it must not re-ask the same
        question every week, and a store that quietly enforces it is one
        less thing a caller can get wrong."""
        text, opts = clean(question, options)
        rid = _line(report_id, REPORT_MAX)
        item = {
            "id": "",
            "at": _iso(),
            "report_id": rid,
            "question": text,
            "options": opts,
            "status": PENDING,
            "choice": None,
            "text": "",
            "answered": None,
            "by": "",
            "built": None,
            "branch": "",
            "note": "",
        }
        try:
            with self._locked():
                data = self._load()
                standing = next(
                    (i for i in data["items"]
                     if i.get("status") == PENDING
                     and str(i.get("report_id") or "") == rid
                     and str(i.get("question") or "") == text), None)
                if standing is not None:
                    log.info("questions: %s is already asked about %s and "
                             "still waiting — not asking twice",
                             standing.get("id"),
                             rid or "nothing in particular")
                    return standing
                item["id"] = self._next_id(data["items"])
                data["items"].append(item)
                self._trim(data)
                self._save(data)
        except OSError as e:
            log.warning("questions: could not save a question about %s (%s)",
                        rid or "?", e)
            if not item["id"]:
                item["id"] = time.strftime(_STAMP)
        log.info("questions: asked %s about %s (%d options)", item["id"],
                 rid or "nothing in particular", len(opts))
        return item

    def answer(self, ident: str, *, choice: int | None = None,
               text: str = "", by: str = "") -> bool:
        """Record HIS answer to one question. Called by the card and by
        the dashboard, and by nothing else — there is deliberately no way
        for the routine to answer on his behalf.

        A choice, or text, or BOTH — all three are answers. A valid
        `choice` with an empty box is him picking one as it stands; no
        choice with text is none of them fitting; a valid `choice` AND
        text is the case he asked for, where he picks "before the backup"
        and then writes "actually after it, so that…". Both are kept and
        both are meant to be read: a caller that looks only at `choice`
        is throwing away the half that refines it. Both empty is the one
        rejection, and picking the last option changes nothing — it is an
        option like the others.

        False also means: no such id, or the question is no longer
        PENDING, or the file could not be written. The already-answered
        case is the important one — the card in front of him may have been
        drawn before the dashboard answered the same question, and a
        decision he has made must not be overwritten by a stale window.
        It never raises; both callers are inside a redraw or a request
        handler."""
        said = _body(text, ANSWER_MAX)
        try:
            with self._locked():
                data = self._load()
                found = next((i for i in data["items"]
                              if i.get("id") == ident), None)
                if found is None:
                    log.info("questions: no question %s to answer", ident)
                    return False
                status = str(found.get("status") or PENDING)
                if status != PENDING:
                    log.info("questions: %s is already %s — not overwriting "
                             "the answer with a stale one", ident, status)
                    return False
                opts = _options(found)
                picked = _index(choice, opts)
                if choice is not None and picked is None:
                    log.info("questions: %r is not one of the %d options on "
                             "%s", choice, len(opts), ident)
                if picked is None and not said:
                    log.info("questions: nothing answered on %s — no option "
                             "picked and nothing typed", ident)
                    return False
                found["status"] = ANSWERED
                found["choice"] = picked
                found["text"] = said
                found["answered"] = _iso()
                found["by"] = _line(by, BY_MAX)
                self._save(data)
                log.info("questions: %s answered (option %s%s)", ident,
                         "none" if picked is None else picked,
                         ", with text" if said else "")
                return True
        except OSError as e:
            log.warning("questions: could not save the answer to %s (%s)",
                        ident, e)
            return False

    def mark_built(self, ident: str, branch: str = "",
                   note: str = "") -> bool:
        """The routine's own move: what it built from an answer he gave.

        Only an ANSWERED question can be marked built, so nothing can be
        recorded as built off a question he never answered. False means
        no such id, the wrong status, or the file could not be
        written."""
        try:
            with self._locked():
                data = self._load()
                found = next((i for i in data["items"]
                              if i.get("id") == ident), None)
                if found is None:
                    log.info("questions: no question %s to mark built",
                             ident)
                    return False
                status = str(found.get("status") or PENDING)
                if status != ANSWERED:
                    log.info("questions: %s is %s, not answered — nothing to "
                             "build from it", ident, status)
                    return False
                found["status"] = BUILT
                found["built"] = _iso()
                found["branch"] = _line(branch, BRANCH_MAX)
                found["note"] = _body(note, NOTE_MAX)
                self._trim(data)
                self._save(data)
                log.info("questions: %s built on %s", ident,
                         found["branch"] or "the current branch")
                return True
        except OSError as e:
            log.warning("questions: could not mark %s built (%s)", ident, e)
            return False

    def drop(self, ident: str, why: str = "") -> bool:
        """Retire a question nobody needs answered any more — the report
        it was about got closed, or the answer arrived some other way.

        Works from PENDING and from ANSWERED. A BUILT question is
        finished and a DROPPED one already is, so both are False rather
        than rewritten; so are no such id and a failed write."""
        try:
            with self._locked():
                data = self._load()
                found = next((i for i in data["items"]
                              if i.get("id") == ident), None)
                if found is None:
                    log.info("questions: no question %s to drop", ident)
                    return False
                status = str(found.get("status") or PENDING)
                if status not in LIVE:
                    log.info("questions: %s is %s — leaving it alone", ident,
                             status)
                    return False
                found["status"] = DROPPED
                found["note"] = _body(why, NOTE_MAX)
                self._trim(data)
                self._save(data)
                log.info("questions: dropped %s (%s)", ident,
                         found["note"] or "no reason given")
                return True
        except OSError as e:
            log.warning("questions: could not drop %s (%s)", ident, e)
            return False


# ---------------------------------------------------------------------------
# the badge
# ---------------------------------------------------------------------------

def pending_count(path: Path) -> int:
    """How many questions are waiting on him, for a dot on a tab.

    Cheap and total: no lock (a reader does not need one — a write lands
    by rename), no items to build, and 0 for a missing, unreadable or
    empty store. Never raises, because this is called from a redraw."""
    try:
        data = json.loads(Path(path).read_text("utf-8"))
        items = data.get("items") if isinstance(data, dict) else None
        return sum(1 for i in (items or [])
                   if isinstance(i, dict) and i.get("status") == PENDING)
    except FileNotFoundError:
        return 0
    except Exception as e:                # noqa: BLE001
        log.info("questions: could not count the pending questions (%s)", e)
        return 0


# ---------------------------------------------------------------------------
# the one-shot carry-over from the routine's old memory
# ---------------------------------------------------------------------------
#
# Before this module the routine kept its own ledger at
# problems/weekly/asked.json:
#
#   {"version": 1,
#    "asked":    {"<report id>": {"date": ..., "question": ...}},
#    "answered": {"<report id>": {"asked": ..., "answered": ...,
#                                 "question": ..., "answer": ...,
#                                 "still_open": bool, "note": ...}}}
#
# Three real entries are in it, all three under "answered": two with
# still_open true — answered by him, approved, not built yet — and one
# with still_open false, which he closed himself after deciding NOT to
# build it. Those two answers are the reason this import exists at all:
# they are work he has already authorised, and starting the new store
# empty would either lose them or invite the routine to ask again.

def _asked_json(asked_path: Path) -> dict:
    """The old ledger, or {} — a missing or unreadable file is a first
    run, not an error."""
    try:
        data = json.loads(Path(asked_path).read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:                # noqa: BLE001
        log.warning("questions: could not read %s (%s) — nothing imported",
                    Path(asked_path).name, e)
        return {}
    return data if isinstance(data, dict) else {}


def _carried(report_id, row, status: str) -> dict:
    """One old ledger row as an item of this store's shape.

    Options are empty: these questions were asked in prose, before there
    were buttons at all, and there is nothing to reconstruct them from —
    inventing two so the item reaches OPTIONS_MIN would be putting words
    in the question's mouth. An item with no options is a card with
    nothing to click and the text box that is always there, so nothing
    breaks. His answer is carried as typed text with `by="owner"`, which
    is what it was."""
    said = _body(row.get("answer"), ANSWER_MAX)
    when = _line(row.get("answered"), 40)
    return {
        "id": "",
        "at": _line(row.get("asked") or row.get("date"), 40) or _iso(),
        "report_id": _line(report_id, REPORT_MAX),
        "question": _line(row.get("question"), QUESTION_MAX),
        "options": [],
        "status": status,
        "choice": None,
        "text": said,
        "answered": (when or _iso()) if status != PENDING else None,
        "by": "owner" if status != PENDING else "",
        "built": None,
        "branch": "",
        "note": _body(row.get("note"), NOTE_MAX),
    }


def import_asked(store: Store, asked_path: Path) -> int:
    """Carry the routine's old ledger into this store. Returns how many
    items were added.

    Safe to call on every run. An entry is recognised by its report id
    plus its question text, and an entry already in the store — in ANY
    state, BUILT included — is skipped rather than rewritten, so a second
    call adds nothing and a question the routine has already built can
    never be reopened by an import.

    How each old row lands:

    * "asked", unanswered            → PENDING, waiting on him.
    * "answered" with still_open     → ANSWERED, by="owner": his answer,
                                       preserved, so the routine builds it.
    * "answered", still_open false   → DROPPED, his answer and the note
                                       kept for the record. He closed
                                       these himself; importing them as
                                       ANSWERED would tell the routine to
                                       build something he decided against.
    * "answered" with an empty answer→ PENDING, because a stored answer
                                       nobody gave is the one thing this
                                       module must never contain.

    Never raises."""
    data = _asked_json(asked_path)
    if not data:
        return 0
    incoming: list[dict] = []
    asked = data.get("asked")
    if isinstance(asked, dict):
        for report_id, row in asked.items():
            if isinstance(row, dict):
                incoming.append(_carried(report_id, row, PENDING))
    answered = data.get("answered")
    if isinstance(answered, dict):
        for report_id, row in answered.items():
            if not isinstance(row, dict):
                continue
            if not _body(row.get("answer"), ANSWER_MAX):
                status = PENDING
            elif row.get("still_open") is False:
                status = DROPPED
            else:
                status = ANSWERED
            incoming.append(_carried(report_id, row, status))
    incoming = [i for i in incoming if i["question"]]
    if not incoming:
        return 0
    added = 0
    try:
        with store._locked():
            stored = store._load()
            seen = {(str(i.get("report_id") or ""),
                     str(i.get("question") or ""))
                    for i in stored["items"]}
            for item in incoming:
                key = (item["report_id"], item["question"])
                if key in seen:
                    continue
                item["id"] = store._next_id(stored["items"])
                stored["items"].append(item)
                seen.add(key)
                added += 1
                log.info("questions: imported %s about %s as %s", item["id"],
                         item["report_id"] or "nothing in particular",
                         item["status"])
            if added:
                store._trim(stored)
                store._save(stored)
    except OSError as e:
        log.warning("questions: could not import %s (%s)",
                    Path(asked_path).name, e)
        return 0
    if added:
        log.info("questions: imported %d question(s) from %s", added,
                 Path(asked_path).name)
    return added
