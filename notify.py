"""A door for other programs to knock on: a cue, a card, and reminders.

The problem this solves is small and daily. Claude Code finishes a long
turn in a window that is not in front, and its own "finished"
notification never reaches the owner on this machine — so the work sits
done and unread until he happens to look. This app already owns the two
things a notification needs here: a sound path that goes through the
mixer (cues.py) and a window that can appear over anything without
taking the keyboard (overlay.HintCard and its kin). So it takes the job.

WHY HTTP. The app already listens on 127.0.0.1:[server] port for the
phone (server.py), token-gated, fronted by `tailscale serve` — so a
`POST /notify` is reachable from a hook on this machine and from the
phone over the same link, with the same secret, and no second transport
to keep alive. Claude Code's Stop and Notification hooks run
notify_hook.py, which is the whole client: read the event, post it,
exit 0. The named pipe (control.py) was the alternative and it does not
reach the phone.

WHY REMINDERS. A single cue is missed as often as it is heard — the
owner is in another room, or on the phone, or the mixer is quiet — and
a card that takes itself down after thirty seconds is gone before he
turns round. So while anything is unread the engine plays the cue and
puts the card back up every `remind_every_s`, `remind_times` times, and
then waits quietly in the dashboard's Notify screen. Dismissal (a click,
Esc over the card, or the dismiss key) marks everything seen and stops
the reminders; the card timing out on its own does NOT — that is what
the reminders are for.

WHY COALESCING. Claude fires Stop and then Notification a moment apart
for the same turn, and two cues 400 ms apart sound like an error pair.
A second arrival from the SAME source inside `coalesce_s` updates the
card (it always shows the newest, with an unread badge) and is stored
and logged like any other; only the second cue is dropped. Reminders
are never coalesced.

WHAT IS NEVER INTERPRETED. Title and body arrive from another program
and are drawn as text: coerced to str, control characters stripped,
whitespace tidied, cut to 80 / 400 characters. Nothing in them is
parsed, formatted, executed or fed to a model. `clean()` is the whole
of that policy and the first test in the suite pins it.

Two records are kept beside the app: notify.log (one line per arrival,
reminder and dismissal, awake.log's shape) and notify.json (the last
100 items, review.json's shape, read-only for the dashboard).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("app")

LOG_NAME = "notify.log"        # beside the app, awake.log's shape
STORE_NAME = "notify.json"     # beside the app, review.json's shape
KINDS = ("done", "input", "error", "info")
TITLE_MAX, BODY_MAX, SOURCE_MAX, PROJECT_MAX, SESSION_MAX = 80, 400, 40, 60, 64
KEEP = 100
SOURCES = {"claude-code": "Claude Code", "claude": "Claude", "phone": "Phone",
           "dashboard": "Dashboard", "test": "Test", "cli": "Command line"}
DEFAULT_TITLE = {"done": "Finished", "input": "Needs your input",
                 "error": "Something went wrong", "info": "Notification"}

_FIELDS = ("source", "kind", "title", "body", "project", "session")
_MAX = {"source": SOURCE_MAX, "title": TITLE_MAX, "body": BODY_MAX,
        "project": PROJECT_MAX, "session": SESSION_MAX}
# C0 controls minus tab and newline (carriage returns are folded into
# newlines first). A bell or an escape sequence in a title is at best a
# terminal's idea of formatting and at worst a way to talk to one.
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def label_for(source: str) -> str:
    """What the card and the dashboard call a source. Unknown ones are
    shown as they came — a program that names itself gets its name."""
    return SOURCES.get(source, source)


def _text(value) -> str:
    if isinstance(value, (str, int, float)):
        return str(value)
    return ""


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 1] + "…"


def clean(payload) -> dict:
    """The one gate every notification passes through, whoever sent it.

    Unknown keys are dropped, every field is coerced to text, control
    characters go, whitespace is tidied (collapsed outright for the
    one-line fields; only runs of blank lines for the body), and each is
    cut to its maximum with a trailing ellipsis. Nothing here is parsed
    or formatted — the output is six strings that will be DRAWN.
    """
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    out: dict[str, str] = {}
    for name in _FIELDS:
        text = _text(payload.get(name))
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = _CONTROLS.sub("", text)
        if name == "body":
            lines = [ln.rstrip() for ln in text.split("\n")]
            text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        else:
            text = " ".join(text.split())
        out[name] = text
    out["source"] = _cut(out["source"].lower(), SOURCE_MAX) or "unknown"
    kind = out["kind"].lower()
    out["kind"] = kind if kind in KINDS else "info"
    for name in ("title", "body", "project", "session"):
        out[name] = _cut(out[name], _MAX[name])
    if not out["title"]:
        out["title"] = DEFAULT_TITLE[out["kind"]]
    return out


# ---------------------------------------------------------------------------
# the store: the last hundred, on disk, read by the dashboard
# ---------------------------------------------------------------------------

class Store:
    """notify.json — review.Store's shape without the lock file.

    The app is the only writer: the dashboard reads the file and asks
    for dismissals through the control channel, so an in-process RLock
    is the whole of the locking. Every write lands through a temporary
    file and one rename, so a reader never sees half a file, and a file
    that will not parse is treated as empty rather than fatal — a broken
    store must cost old notifications, not dictation."""

    def __init__(self, path: Path, keep: int = KEEP) -> None:
        self.path = Path(path)
        self.keep = int(keep)
        self._lock = threading.RLock()

    # ---- the file ----

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            return {"version": 1, "items": []}
        except Exception as e:            # noqa: BLE001
            log.warning("%s unreadable (%s) — starting empty",
                        self.path.name, e)
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

    # ---- writes ----

    def add(self, fields: dict) -> dict:
        """Store one cleaned notification. The id is one past the largest
        on file (from 1), the timestamp is local time to the second, and
        the oldest go once the file holds more than `keep`."""
        with self._lock:
            data = self._load()
            items = data["items"]
            next_id = max((int(i.get("id", 0)) for i in items), default=0) + 1
            item = {"id": next_id,
                    "at": datetime.now().isoformat(timespec="seconds")}
            item.update({k: str(fields.get(k, "")) for k in _FIELDS})
            item["seen"] = False
            items.append(item)
            if len(items) > self.keep:
                del items[:len(items) - self.keep]
            self._save(data)
            return dict(item)

    def mark_seen(self, ids=None) -> int:
        """Mark these ids (None = every item) seen; how many changed.
        The file is written only when something did."""
        with self._lock:
            data = self._load()
            wanted = None if ids is None else {int(i) for i in ids}
            changed = 0
            for item in data["items"]:
                if item.get("seen"):
                    continue
                if wanted is not None and int(item.get("id", 0)) not in wanted:
                    continue
                item["seen"] = True
                changed += 1
            if changed:
                self._save(data)
            return changed

    # ---- reads ----

    def items(self) -> list[dict]:
        """Oldest first, copies."""
        with self._lock:
            return [dict(i) for i in self._load()["items"]]

    def recent(self, n: int = 30) -> list[dict]:
        """Newest first."""
        items = self.items()
        items.reverse()
        return items[:max(0, int(n))]

    def last(self) -> dict | None:
        items = self.items()
        return items[-1] if items else None

    def unread(self) -> int:
        return sum(1 for i in self.items() if not i.get("seen"))

    def stamp(self) -> tuple | None:
        """(size, mtime_ns) or None — the dashboard's change detector,
        without reading the file."""
        try:
            st = self.path.stat()
        except OSError:
            return None
        return (st.st_size, st.st_mtime_ns)


# ---------------------------------------------------------------------------
# the card's surface, and the inert card
# ---------------------------------------------------------------------------

class NullCard:
    """The card when there is none: [notify] enabled = false, or the
    overlay module without a NotifyCard. Every method is a no-op so the
    engine never has to ask which it holds."""

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def show(self, item: dict) -> None:
        pass

    def hide(self) -> None:
        pass

    def visible(self) -> bool:
        return False

    def hovering(self) -> bool:
        return False

    def on_key(self, vk: int) -> bool:
        return False


# ---------------------------------------------------------------------------
# the engine
# ---------------------------------------------------------------------------

def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Engine:
    """One process's notifications: receive, cue, card, remind, dismiss.

    All entry points are cheap and thread-safe. `receive` runs on an
    HTTP request thread and returns in milliseconds (one small JSON
    write, an async cue, a queue put); `dismiss` runs on a thread main.py
    spawns for it, never on the keyboard hook or the card's Tk thread;
    the reminders are a daemon thread of their own, one per arrival,
    with a generation counter so an old one can never fire after a newer
    arrival or a dismissal has replaced it.
    """

    def __init__(self, app_dir, cfg=None, *, cue=None, card=None,
                 clock=time.monotonic, store_path=None,
                 log_path=None) -> None:
        self.app_dir = Path(app_dir)
        self.enabled = bool(getattr(cfg, "enabled", True))
        self.cue_on = bool(getattr(cfg, "cue", True))
        self.card_seconds = int(getattr(cfg, "card_seconds", 30))
        self.remind_every_s = float(getattr(cfg, "remind_every_s", 120))
        self.remind_times = int(getattr(cfg, "remind_times", 2))
        self.coalesce_s = float(getattr(cfg, "coalesce_s", 5))
        self._cue = cue if cue is not None else (lambda kind: None)
        self.card = card if card is not None else NullCard()
        self._clock = clock
        self.store = Store(Path(store_path) if store_path
                           else self.app_dir / STORE_NAME)
        self.log_path = (Path(log_path) if log_path
                         else self.app_dir / LOG_NAME)
        self._lock = threading.RLock()
        # source -> clock() of the last cue played for it (coalescing)
        self._cue_at: dict[str, float] = {}
        self._gen = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_gen = -1
        self._fired = 0

    # -- in --

    def receive(self, payload) -> dict:
        """One notification in. ValueError from clean() propagates — the
        server turns it into a 400; everything else is answered here."""
        fields = clean(payload)
        source, kind = fields["source"], fields["kind"]
        if not self.enabled:
            self._log(f"RECEIVED from {source} ({kind}) | title "
                      f"{fields['title']!r} | refused: off")
            return {"ok": False, "error": "notifications are off "
                                          "([notify] enabled = false)"}
        with self._lock:
            item = self.store.add(fields)
            unread = self.store.unread()
            self._log(f"RECEIVED #{item['id']} from {source} ({kind}) | "
                      f"project {item['project']} | title {item['title']!r}"
                      f" | {len(item['body'])} chars | unread {unread}")
            log.info("notify: received #%d from %s (%s): %r [%s] | unread %d",
                     item["id"], source, kind, item["title"],
                     item["project"], unread)
            now = self._clock()
            coalesced = now - self._cue_at.get(source, -1e9) < self.coalesce_s
            if self.cue_on and not coalesced:
                self._cue("notify")
                self._cue_at[source] = now
            # The card always follows the newest, coalesced or not: the
            # badge says how many are waiting behind it.
            self.card.show(dict(item, unread=unread, label=label_for(source)))
            self._arm()
        return {"ok": True, "id": item["id"], "unread": unread,
                "coalesced": coalesced}

    def test(self, *, source: str = "test") -> dict:
        return self.receive({
            "source": source, "kind": "done", "title": "A test notification",
            "body": "הכרטיס עובד — Hebrew and English both render. Click "
                    "it, press Esc over it, or tap the dismiss key.",
            "project": "dashboard"})

    # -- out --

    def dismiss(self, *, by: str = "key") -> dict:
        """Everything seen, the reminders cancelled, the card down."""
        with self._lock:
            n = self.store.mark_seen()
            self._gen += 1
            self._stop.set()
            try:
                self.card.hide()
            except Exception:             # noqa: BLE001
                pass
            self._log(f"DISMISSED by {by} | {n} marked seen")
            log.info("notify: dismissed by %s | %d marked seen", by, n)
            return self.state()

    def state(self) -> dict:
        """What the dashboard draws and status() carries down the pipe:
        counts and the last item's metadata, NEVER a body — status is
        polled several times a second."""
        with self._lock:
            items = self.store.items()
            last = items[-1] if items else None
            thread = self._thread
            reminding = bool(thread is not None and thread.is_alive()
                             and self._thread_gen == self._gen
                             and not self._stop.is_set()
                             and self._fired < self.remind_times)
            return {
                "enabled": self.enabled,
                "unread": sum(1 for i in items if not i.get("seen")),
                "total": len(items),
                "reminding": reminding,
                "reminders_left": (max(0, self.remind_times - self._fired)
                                   if reminding else 0),
                "card_up": self._card_up(),
                "last": None if last is None else {
                    "id": last.get("id"), "at": last.get("at"),
                    "source": last.get("source", ""),
                    "label": label_for(last.get("source", "")),
                    "kind": last.get("kind", "info"),
                    "title": last.get("title", ""),
                    "project": last.get("project", ""),
                    "seen": bool(last.get("seen"))},
            }

    def recent(self, n: int = 30) -> list[dict]:
        """Bodies included — for the control channel, on request."""
        return self.store.recent(n)

    def start(self) -> None:
        log.info("notify: %s | store %s | reminders %s",
                 "on" if self.enabled else "off ([notify] enabled = false)",
                 self.store.path.name,
                 (f"every {self.remind_every_s:g} s x {self.remind_times}"
                  if self.remind_every_s > 0 and self.remind_times > 0
                  else "off"))

    def stop(self) -> None:
        """Cancel the reminder thread and wait for it, briefly. The card
        is main's to stop — it owns the window."""
        with self._lock:
            self._gen += 1
            self._stop.set()
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(1.0)

    # -- reminders --

    def _arm(self) -> None:
        """Start a fresh reminder thread for the newest arrival and retire
        the old one: the generation moves on and its own stop event is
        set, so whichever check it wakes into, it leaves."""
        with self._lock:
            if self.remind_every_s <= 0 or self.remind_times <= 0:
                return
            self._gen += 1
            self._stop.set()
            stop = threading.Event()
            self._stop = stop
            self._fired = 0
            self._thread_gen = self._gen
            self._thread = threading.Thread(
                target=self._remind, args=(self._gen, stop), daemon=True,
                name="notify-remind")
            self._thread.start()

    def _remind(self, gen: int, stop: threading.Event) -> None:
        for i in range(self.remind_times):
            if stop.wait(self.remind_every_s):
                return
            with self._lock:
                if gen != self._gen or stop.is_set() \
                        or self.store.unread() == 0:
                    return
                last = self.store.last()
                unread = self.store.unread()
                if self.cue_on:
                    self._cue("notify")
                if last is not None:
                    self.card.show(dict(
                        last, unread=unread,
                        label=label_for(last.get("source", ""))))
                self._fired = i + 1
                self._log(f"REMINDED {i + 1}/{self.remind_times} | "
                          f"unread {unread}")
                log.info("notify: reminded %d/%d | unread %d", i + 1,
                         self.remind_times, unread)

    # -- plumbing --

    def _card_up(self) -> bool:
        try:
            return bool(self.card.visible())
        except Exception:                 # noqa: BLE001
            return False

    def _log(self, line: str) -> None:
        try:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{_stamp()} | {line}\n")
        except OSError:
            pass
