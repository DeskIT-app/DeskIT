"""Claude Code's finishes, read off its own transcripts — before its Stop hook.

WHAT THIS IS FOR. A "Claude finished" card has always waited for
notify_hook.py, which Claude Code runs from a Stop hook. The owner,
2026-10-24, watching the card come up long after the answer had
stopped moving on his screen: "there is a terribly long delay between
the moment it finishes on the computer and the notification — see how
to bring it to zero, without the summary getting any worse".

WHERE THE WAIT IS (measured 2026-10-24). Not in this app: notify.log
has the request arriving and the sentence back from Groq inside
0.17-0.59 s on every finish that day. Not in the hook either: its own
run is 0.31-0.64 s (`durationMs` in the transcripts' stop_hook_summary
records). The wait is BEFORE the hook — inside Claude Code, between the
last word of the answer and the moment it starts its Stop hooks. Read
off 281 turns of the desktop app's transcripts over three days, that
gap is bimodal: 34 turns at 0.02-0.16 s, and the rest at 2-5 s
(median 3.3 s, p90 5.1 s), on every project and every effort level,
with no length or tool count that tells the two apart.

What a transcript line's own timestamp says was then checked against
the disk, live, with a probe polling every transcript every 25 ms. A
message lands WHOLE, every block of it in one write, 0.12-0.20 s after
the timestamp on its last block (45 tool-use messages, three finishes)
— and the three finishes it caught were:

    session    final line on disk   Stop hook started   lead
    90638400   18:12:19.79          18:12:19.70         -0.09 s
    0174e896   18:14:42.90          18:14:42.80         -0.10 s
    fb34773f   18:14:48.32          18:14:51.09         +2.77 s

So on a slow turn the finished answer is on disk about three seconds
before the hook is even started, and on a fast one the two are a tenth
apart — where the hook still spends a third of a second on its own run
before it knocks. Reading the file wins both: by the hook's run on a
fast turn, by the hook's run plus Claude Code's three seconds on the
usual one.

WHAT IS READ. ~/.claude/projects/<project>/<session>.jsonl — one line
per transcript entry, appended, never rewritten. A finish is ONE kind of
line: `"type": "assistant"`, `message.stop_reason == "end_turn"`, not a
sidechain, with text in it. Subagents write under `<session>/subagents/`
(and say `isSidechain`), so `*/*.jsonl` never sees them. Every other
line — a tool call, a thinking block, a result, the app's own records —
is skipped on a substring test before anything is parsed: a session
line can be megabytes of tool output.

WHAT IS SENT. Exactly what the hook would send for the same Stop:
notify_hook.payload_from_hook builds it, from the message's text, the
line's `cwd` and its `sessionId`, so the title, the 300-character body
and the `text` the one sentence is written from are the hook's own to
the byte, and the summary is the same summary. One field more:
`via = "transcript"`. When the hook then knocks with the same finish,
the engine knows it already has it (notify.Engine, "the same finish
told twice") and folds the hook's window into the card instead of
putting up a second one.

WHEN IT RUNS. Only while THIS copy holds Claude Code's door
(notify_hook.hook_state() is "mine"), asked on every finish: a copy the
owner has not connected, or the stranger's, never cards a Claude turn
it was not asked to, and switching the door off from the desk is seen
on the next finish. Its own switch is [notify] early.

WHAT IT COSTS. The files are found with os.scandir, whose entries
carry their size and time on Windows without one more call per file:
317 transcripts in 38 projects on this PC, every RESCAN_S. Only the
ones written in the last ACTIVE_S are looked at every POLL_S, one stat
each, and only bytes a file has gained since the last look are read.
A file that was asleep at a rescan keeps the offset it had, so the
lines it gains before the next one are read too, not skipped.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

log = logging.getLogger("app")

POLL_S = 0.1                   # the active files, a stat each
RESCAN_S = 2.0                 # every transcript, one scandir per project
ACTIVE_S = 900.0               # written this recently = looked at every poll
READ_MAX = 32 * 1024 * 1024    # a jump bigger than this is skipped, not read
SENT_MAX = 256                 # message ids remembered against a second read
VIA = "transcript"
_FINISH = b'"end_turn"'        # the substring a finish cannot be without


def projects_root() -> Path:
    """Where Claude Code keeps its transcripts: CLAUDE_CONFIG_DIR when it
    is set, ~/.claude everywhere else."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base) / "projects"


def finish_of(line) -> dict | None:
    """One transcript line as a finish — {"message", "session", "cwd",
    "text"} — or None for every line that is not one (module docstring,
    WHAT IS READ). Never raises."""
    if isinstance(line, str):
        line = line.encode("utf-8", "replace")
    if _FINISH not in line:
        return None
    try:
        entry = json.loads(line.decode("utf-8", "replace"))
    except ValueError:
        return None
    if not isinstance(entry, dict) or entry.get("type") != "assistant" \
            or entry.get("isSidechain") is True:
        return None
    message = entry.get("message")
    if not isinstance(message, dict) \
            or message.get("stop_reason") != "end_turn":
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    text = "\n\n".join(str(block.get("text") or "") for block in content
                       if isinstance(block, dict)
                       and block.get("type") == "text"
                       and str(block.get("text") or "").strip())
    session = str(entry.get("sessionId") or "")
    if not text.strip() or not session:
        return None
    return {"message": str(message.get("id") or entry.get("uuid") or ""),
            "session": session, "cwd": str(entry.get("cwd") or ""),
            "text": text}


def payload_of(finish: dict, window=(0, ""), link: str = "") -> dict | None:
    """The /notify body the hook would have sent for this finish, plus
    `via`. Built BY the hook's own function, so the two can never drift
    apart (module docstring, WHAT IS SENT)."""
    import notify_hook

    payload = notify_hook.payload_from_hook(
        {"hook_event_name": "Stop", "session_id": finish["session"],
         "cwd": finish["cwd"], "last_assistant_message": finish["text"]},
        window=window, link=link)
    if payload is not None:
        payload["via"] = VIA
    return payload


def _connected() -> bool:
    """Does THIS copy hold Claude Code's door? Asked per finish."""
    import notify_hook

    return notify_hook.hook_state()[0] == "mine"


def _window() -> tuple[int, str]:
    import notify_watch

    return notify_watch.claude_window()


def _link(session: str) -> str:
    import notify_hook

    return notify_hook.session_link(session)


class Tail:
    """The poll loop: a finish written to a transcript becomes a card.

    `sink` is one callable taking the payload — main.py hands over the
    /notify route's own, the way notify_watch.Watcher is fed. The three
    questions a finish needs answered from outside — is this copy
    connected, which window is Claude's, which link opens the session —
    are parameters only so a test can answer them; left None they are
    notify_hook's and notify_watch's own. Nothing raises: a file that
    vanished, a line that will not parse, a sink that throws are a line
    in app.log and a pass that found nothing.
    """

    def __init__(self, sink, enabled: bool = True, *, root=None,
                 poll_s: float = POLL_S, rescan_s: float = RESCAN_S,
                 active_s: float = ACTIVE_S, connected=None, window=None,
                 link=None, clock=time.time) -> None:
        self.sink = sink
        self.enabled = bool(enabled)
        self.root = Path(root) if root is not None else projects_root()
        self.poll_s = float(poll_s)
        self.rescan_s = float(rescan_s)
        self.active_s = float(active_s)
        self._connected = connected or _connected
        self._window = window or _window
        self._link = link or _link
        self._clock = clock
        self._offsets: dict[Path, int] = {}
        self._active: set[Path] = set()
        self._scanned_at: float | None = None
        self._sent: OrderedDict[str, None] = OrderedDict()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- the files --

    def _entries(self):
        """(path, size, mtime) for every transcript under the root."""
        try:
            projects = list(os.scandir(self.root))
        except OSError:
            return
        for project in projects:
            try:
                if not project.is_dir():
                    continue
                with os.scandir(project.path) as files:
                    for f in files:
                        if f.name.endswith(".jsonl") and f.is_file():
                            st = f.stat()
                            yield Path(f.path), st.st_size, st.st_mtime
            except OSError:
                continue

    def rescan(self) -> None:
        """Every transcript, sized. The FIRST rescan takes each file's end
        as its starting point — what was written before the app started
        has been answered or stopped mattering; a file born after it is
        read from its first byte."""
        first = self._scanned_at is None
        now = self._clock()
        seen: set[Path] = set()
        for path, size, mtime in self._entries():
            seen.add(path)
            if path not in self._offsets:
                self._offsets[path] = size if first else 0
            elif size < self._offsets[path]:
                self._offsets[path] = size    # rewritten: start again here
            if now - mtime <= self.active_s or size > self._offsets[path]:
                self._active.add(path)
            else:
                self._active.discard(path)
        for gone in set(self._offsets) - seen:
            self._offsets.pop(gone, None)
            self._active.discard(gone)
        self._scanned_at = now
        if first:
            log.info("notify tail: reading Claude Code's transcripts under "
                     "%s — %d files, %d of them active", self.root,
                     len(self._offsets), len(self._active))

    def _read(self, path: Path) -> list[bytes]:
        """The whole lines this file has gained since the last look."""
        offset = self._offsets.get(path, 0)
        try:
            size = path.stat().st_size
        except OSError:
            return []
        if size <= offset:
            if size < offset:
                self._offsets[path] = size
            return []
        if size - offset > READ_MAX:
            log.warning("notify tail: %s grew by %d bytes at once — skipped",
                        path.name, size - offset)
            self._offsets[path] = size
            return []
        try:
            with path.open("rb") as f:
                f.seek(offset)
                data = f.read(size - offset)
        except OSError:
            return []
        cut = data.rfind(b"\n")
        if cut < 0:
            return []                 # half a line: the rest is coming
        self._offsets[path] = offset + cut + 1
        return data[:cut].splitlines()

    # -- one pass --

    def once(self) -> int:
        """One look at the active files; how many finishes were handed on."""
        if not self.enabled:
            return 0
        if self._scanned_at is None \
                or self._clock() - self._scanned_at >= self.rescan_s:
            self.rescan()
        sent = 0
        for path in list(self._active):
            for line in self._read(path):
                finish = finish_of(line)
                if finish is None or not self._fresh(finish["message"]):
                    continue
                if self._hand_on(finish):
                    sent += 1
        return sent

    def _fresh(self, message: str) -> bool:
        """First time this message is seen? A message whose text came in
        two writes is still one finish."""
        if not message:
            return True
        if message in self._sent:
            return False
        self._sent[message] = None
        while len(self._sent) > SENT_MAX:
            self._sent.popitem(last=False)
        return True

    def _hand_on(self, finish: dict) -> bool:
        try:
            if not self._connected():
                log.debug("notify tail: a finish in %s, but this copy does "
                          "not hold Claude Code's door", finish["session"])
                return False
            payload = payload_of(finish, self._window(),
                                 self._link(finish["session"]))
            if payload is None:
                return False
            self.sink(payload)
            return True
        except Exception:                 # noqa: BLE001
            log.warning("notify tail: could not pass on a finish from %s",
                        finish.get("session"), exc_info=True)
            return False

    # -- the thread --

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="notify-tail")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.once()
            except Exception:             # noqa: BLE001
                log.warning("notify tail: the pass failed", exc_info=True)
            self._stop.wait(self.poll_s)

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.poll_s + 1)
