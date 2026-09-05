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
owner is in another room, or on the phone, or the mixer is quiet. So
while anything is unread the engine plays the cue and puts the card
back up every `remind_every_s`, `remind_times` times, and then waits
quietly in the dashboard's Notify screen. Dismissal (the ×, Esc over
the card, or the dismiss key) marks everything seen and stops the
reminders; a card timing out on its own does NOT — that is what the
reminders are for, and since 2026-09-04 it does not happen at all
unless `card_seconds` is put back above 0.

WHY A STACK, AND WHY NOTHING TIMES OUT (2026-09-04). The card used to
show the newest notification and a badge counting the rest, and take
itself down after thirty seconds. Both were wrong for the way the owner
works: the ones behind the badge were unreachable until he opened the
dashboard, and the one on screen was gone before he turned round. So
`live()` is now the whole unread column — newest first, capped at
`stack_max`, the last one carrying `"more": N` when there are more
behind it — and every entry point ends by showing that column rather
than one item. `dismiss(id)` and `open(id)` name one card of it; with no
id they still mean everything, which is what the key, the dashboard and
Esc have always meant. The column goes down only when nothing is left
unread.

WHY A CLICK GOES THERE INSTEAD (2026-09-04). Being told Claude has
finished is not the point; getting back to Claude is. So a click
anywhere on the card except the × is `open()`: it raises the window the
notification came from — which the sender names in `hwnd`/`app`, see
notify_hook.owner_window — and then dismisses exactly as before, because
arriving at the work is having read the notice. The × keeps the old
meaning, and so does Esc: close it, stay where you are.

AND WHY THE WINDOW IS ONLY HALF OF IT (2026-09-04). One Claude window
holds every session, so raising it arrives at whichever one the app was
last showing — not the one that finished. A sender may therefore also
name the SESSION, as a `claude://…` link (notify_hook.session_link
works out what to send and, in a long comment, why that particular
link); `open()` hands it to the shell before it raises the window,
which is the app's own front door and needs nothing of this app. A
notification without a link, or a shell that will not take it, is the
old behaviour and not an error: the window still comes forward and
notify.log says what happened.

AND THE ROAD IN THAT IS NOT A KNOCK (2026-09-04). Cowork has no hook to
install: its sessions run in Anthropic's cloud and there is no file on
this machine to write one into. But the desktop app already raises a
Windows toast for them, so notify_watch.py reads those off Windows' own
notification store and calls `receive` with the fields a POST would have
carried — same store, same cue, same reminders, same column. `[notify]
watch` is the switch; that module's docstring holds the measurements and
the reason Claude Chat is not on the list: it announces nothing, to
anything, anywhere on this machine.

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

import inspect
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
APP_MAX = 80                   # the sender's window title, as a label only
KEEP = 100
STACK_MAX = 5                  # cards on screen at once when the config
                               # says nothing; [notify] stack_max is the
                               # real number and config.py bounds it
SOURCES = {"claude-code": "Claude Code", "cowork": "Cowork",
           "claude": "Claude", "phone": "Phone",
           "dashboard": "Dashboard", "test": "Test", "cli": "Command line"}
DEFAULT_TITLE = {"done": "Finished", "input": "Needs your input",
                 "error": "Something went wrong", "info": "Notification"}

# WHICH ARRIVALS MAY PULL THE OWNER OUT OF WHAT HE IS DOING.
# A card is cheap: it appears at the edge of the screen and waits there
# for as long as it takes. The cue and the reminders are not — they are a
# sound, and the same sound again two minutes later, and they are worth
# paying only for a notification that is WAITING ON HIM.
#
# Counted on this machine 2026-09-05, the last hundred stored: 87 were
# `claude-code/done`, one for every turn a session ended, and every one
# of them rang and came back twice; 5 were `input`, all of them a
# permission. So a finish is not news by itself. `input` and `error` keep
# the bell, `done` and `info` land quietly, and [notify] interrupt says
# which — "all" is how this door worked before.
LOUD = ("input", "error")
INTERRUPTS = ("all", "input", "none")

_FIELDS = ("source", "kind", "title", "body", "project", "session", "app")
_MAX = {"source": SOURCE_MAX, "title": TITLE_MAX, "body": BODY_MAX,
        "project": PROJECT_MAX, "session": SESSION_MAX, "app": APP_MAX}
# C0 controls minus tab and newline (carriage returns are folded into
# newlines first). A bell or an escape sequence in a title is at best a
# terminal's idea of formatting and at worst a way to talk to one.
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# THE ONE THING IN A NOTIFICATION THAT IS NOT DRAWN. `link` is handed to
# the SHELL when the card is clicked, so it is not cleaned, it is
# ADMITTED: one scheme, one alphabet, one length. `claude://…` opens
# whatever Windows has registered for it — the desktop app — and
# everything else is not a link here and reads as none: no file:, no
# http:, no path, no space, no quote, no backslash, no percent escape.
_LINK = re.compile(r"^claude://[A-Za-z0-9_\-./?=&:]{1,180}$")


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


def _window(value) -> int:
    """A sender's HWND, or 0. Anything that will not survive `int()` — a
    string, a dict, None — and anything negative is 0, which reads
    downstream as "there is no window to raise" rather than as an error.
    A handle is never dereferenced here; raise_window asks Windows
    whether it is still a window before it does anything with it."""
    try:
        hwnd = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return hwnd if hwnd > 0 else 0


def _link(value) -> str:
    """A sender's `claude://…` link, or "". Anything that is not a
    string, or that the whitelist above does not recognise, is "" —
    which reads downstream as "no session to go to" and costs the click
    nothing but the window it was always going to raise."""
    text = (value if isinstance(value, str) else "").strip()
    # Stripped at the ends and nowhere else. Whitespace INSIDE a link is
    # not tidied the way a title's is: a link that arrived with a space
    # in it is not a link this app can vouch for, and closing the gap
    # would be repairing a stranger's string into something executable.
    return text if _LINK.match(text) else ""


def _ident(value) -> int | None:
    """One notification's id, or None meaning "all" / "the newest".

    Ids start at 1, so anything that will not survive `int()` — and
    anything at or below zero — reads as None rather than as an error.
    A press that arrives without a usable id means the whole column,
    which is what the dismiss key and Esc have always meant.
    """
    try:
        ident = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return ident if ident > 0 else None


def clean(payload) -> dict:
    """The one gate every notification passes through, whoever sent it.

    Unknown keys are dropped, every field is coerced to text, control
    characters go, whitespace is tidied (collapsed outright for the
    one-line fields; only runs of blank lines for the body), and each is
    cut to its maximum with a trailing ellipsis. Nothing here is parsed
    or formatted — the output is seven strings that will be DRAWN, plus
    one integer (`hwnd`) that is only ever handed back to Windows and
    one string (`link`) that is only ever handed back to the shell, and
    only when the whitelist above recognises it.
    """
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    out: dict = {}
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
    for name in ("title", "body", "project", "session", "app"):
        out[name] = _cut(out[name], _MAX[name])
    if not out["title"]:
        out["title"] = DEFAULT_TITLE[out["kind"]]
    out["hwnd"] = _window(payload.get("hwnd"))
    out["link"] = _link(payload.get("link"))
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
            # The two fields that are not drawn: the sender's window, so
            # a click on the card can raise it, and its session link, so
            # the click can land in the right place inside it. Both put
            # through their gate again rather than trusted — this method
            # takes a plain dict from whoever calls it, and an int and a
            # whitelisted link are the only things json.dump and
            # Engine.open will accept without asking questions.
            item["hwnd"] = _window(fields.get("hwnd"))
            item["link"] = _link(fields.get("link"))
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
# knowing he has ARRIVED at the session a card came from
# ---------------------------------------------------------------------------
#
# The third way to clear a card, in his words (answered 2026-09-05):
# "I want the card to disappear if only his card when I'm entering only
# his session, not if I enter to Claude so all the Claude disappear —
# when I'm entering the same specific session the same specific card
# will disappear." Session resolution, not window resolution, and never
# the stack.
#
# HOW HE IS SEEN TO ARRIVE, and why it is not UI Automation. The first
# attempt at this (2026-09-04) went at the window: UIA exposes Claude's
# sessions as panes carrying a TITLE, the card carries an ID, and no key
# joined them — and a session that is not tiled has no pane at all. Both
# halves dissolve one level down. The desktop app writes a file per
# session under
#   %APPDATA%\Claude\claude-code-sessions\<account>\<org>\local_<uuid>.json
# — the same store notify_hook.session_link already walks for the link —
# and each one carries `cliSessionId` (what a hook's card stores in
# `session`), `sessionId` (`local_…`, what a watch's card stores), and
# `lastFocusedAt`, milliseconds, which is the app saying WHICH SESSION HE
# IS LOOKING AT. No window is consulted, so a session with no pane is
# answered as easily as one with.
#
# Measured against the live store 2026-09-05, 96 cards naming a session:
# 74 joined, by either id. The 22 that did not are 18 sessions old enough
# to have aged out of the app's store and 4 Cowork `cse_…` ones, which
# live in the cloud and have no local file at all — Cowork cards can
# never dismiss themselves this way, the same limitation that stops them
# being opened.
#
# WHY IT CANNOT EAT A CARD HE NEVER SAW. Two guards. The focus stamp must
# be LATER than the card's own `at`, so being in a session already does
# nothing — only arriving after it spoke counts. And the app only toasts
# a session he is not looking at (`isUserViewingSession`, quoted in
# notify_watch.py), so a card does not arrive for the session on screen
# in the first place.

SESSIONS = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code-sessions"
ARRIVAL_POLL_S = 2.0           # how often the store is asked, while cards
                               # with a session are on screen and only then
ARRIVAL_SCAN_MAX = 60          # session files read in one pass; the store
                               # grows for ever and the newest are the ones
                               # a live card can belong to


def focus_times(root=None) -> dict[str, float]:
    """Every session the desktop app knows: id -> `lastFocusedAt`, ms.

    Keyed under BOTH names a card can carry — the CLI id a Stop hook is
    given (`cliSessionId`, and the `priorCliSessionIds` of a session that
    has been resumed) and the app's own `local_…` id a watched toast
    carries — so a caller matches on the one it has without knowing which
    kind it is.

    Newest file first, and it stops at ARRIVAL_SCAN_MAX: this runs on a
    timer and the store is unbounded. Never raises. A store that is not
    there, a file being rewritten under us, a machine where APPDATA says
    nothing — all of them are "no opinion", which reads downstream as
    "he has not arrived" and costs a card nothing.
    """
    base = Path(root) if root else SESSIONS
    try:
        files = sorted(base.glob("*/*/local_*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return {}
    out: dict[str, float] = {}
    for path in files[:ARRIVAL_SCAN_MAX]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue                      # mid-write, or not ours to read
        if not isinstance(data, dict):
            continue
        try:
            when = float(data.get("lastFocusedAt") or 0)
        except (TypeError, ValueError):
            continue
        if when <= 0:
            continue
        names = [data.get("cliSessionId"), data.get("sessionId")]
        prior = data.get("priorCliSessionIds")
        if isinstance(prior, list):
            names.extend(prior)
        for name in names:
            key = str(name or "")
            # The newest file wins a shared id: a resumed session names
            # its predecessor, and the live one is the one he is in.
            if key and key not in out:
                out[key] = when
    return out


def arrived(item, focus) -> bool:
    """Has he gone to the session this card came from, since it arrived?

    `focus` is focus_times()'s map. False for a card with no session, a
    session the store has never heard of, and an unreadable timestamp —
    every uncertainty answers "no", because the cost of a wrong yes is a
    notification he never saw and the cost of a wrong no is a card he
    dismisses by hand, as he does today.
    """
    session = str((item or {}).get("session", "") or "")
    when = focus.get(session)
    if not session or not when:
        return False
    try:
        at = datetime.fromisoformat(str(item.get("at", ""))).timestamp()
    except (TypeError, ValueError):
        return False
    return (when / 1000.0) > at


# ---------------------------------------------------------------------------
# going to the session the notification came from
# ---------------------------------------------------------------------------

def open_link(link) -> bool:
    """Hand one `claude://…` link to the shell. True if the shell took it.

    `os.startfile` is the shell's own double-click — launch.open_path
    uses it for the log buttons — and for a URL it runs whatever is
    registered for the scheme. What comes back is whether the SHELL
    accepted it, not whether the app went anywhere: the handler runs in
    the other process and answers nobody here. A link the whitelist does
    not recognise never reaches the shell at all; it is put through
    `_link` again here rather than trusted, because this function is
    reachable from the store and the whitelist is the whole of the
    safety.
    """
    link = _link(link)
    if not link:
        return False
    try:
        os.startfile(link)            # noqa: S606 (Windows-only by design)
        return True
    except OSError:
        log.info("notify: could not open %s", link, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# raising the window the notification came from
# ---------------------------------------------------------------------------

SW_RESTORE = 9
# THE FOREGROUND HANDOVER IS ASYNCHRONOUS, AND READING IT BACK ON THE NEXT
# LINE READS A LIE. Measured 2026-09-04 from a plain background python
# process, target the Claude window, Chrome in front:
#   SetForegroundWindow -> 1
#   GetForegroundWindow immediately -> 0 ('')        <- in flight, nobody
#   GetForegroundWindow +500 ms      -> 43779834 ('Claude')
# So the first version of this function declared failure on a raise that
# had worked, and then ran the AttachThreadInput dance over the top of it.
# The check waits instead: poll until the target IS the foreground, or
# until SETTLE_S has gone. A 0 in between is the transition, not a no.
SETTLE_S = 0.5
POLL_S = 0.02
_HANDLES = None


def _handles():
    """PRIVATE user32/kernel32 wrappers, built once and cached.

    `ctypes.windll.user32` is a process-global cached object shared by
    five files here, and declaring argtypes on it changes them FOR EVERY
    MODULE — that is the OverflowError capture.py paid for (AGENTS.md).
    `ctypes.WinDLL(...)` builds a new wrapper with its own function
    cache, so the restypes below are ours alone. A HWND is c_void_p
    because a 64-bit handle does not fit the c_int ctypes assumes.
    """
    global _HANDLES
    if _HANDLES is None:
        import ctypes
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        for name in ("IsWindow", "IsIconic", "SetForegroundWindow"):
            fn = getattr(u32, name)
            fn.argtypes = [ctypes.c_void_p]
            fn.restype = ctypes.c_int
        u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u32.ShowWindow.restype = ctypes.c_int
        u32.GetForegroundWindow.argtypes = []
        u32.GetForegroundWindow.restype = ctypes.c_void_p
        u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,
                                                 ctypes.c_void_p]
        u32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        u32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong,
                                          ctypes.c_int]
        u32.AttachThreadInput.restype = ctypes.c_int
        k32.GetCurrentThreadId.argtypes = []
        k32.GetCurrentThreadId.restype = ctypes.c_ulong
        _HANDLES = (u32, k32)
    return _HANDLES


def _is_front(u32, hwnd: int, seconds: float) -> bool:
    """Is `hwnd` the foreground window, allowing `seconds` for it to
    become so? See SETTLE_S: the handover takes a few frames and reads 0
    while it is in flight, so one immediate read is not an answer."""
    end = time.monotonic() + max(0.0, float(seconds))
    while True:
        if int(u32.GetForegroundWindow() or 0) == hwnd:
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(POLL_S)


def raise_window(hwnd) -> bool:
    """Bring one window to the front. True only if it actually got there.

    Restore it if it was minimised, ask for the foreground, and then
    WATCH the foreground until it is the window or SETTLE_S has passed —
    because SetForegroundWindow is allowed to decline. Windows grants it
    to a process that already owns the foreground, was started by the one
    that does, or is answering input; a background thread of this app is
    none of those on paper. When the wait runs out, it falls back once to
    the AttachThreadInput dance — attach to the thread that currently
    owns the foreground, which makes our input queue theirs for a moment,
    ask again, detach — and watches once more. What comes back is the
    honest answer; nothing here reports success it has not seen.

    A handle that is no longer a window is False and not an error: the
    program that sent the notification is allowed to have exited, and
    Engine.open treats that as "nothing to raise", not as a failure.

    Costs nothing when it works (the poll exits on the first frame the
    handover lands) and at most SETTLE_S twice when it does not — which
    is why it runs on main.py's "notify-open" thread and never on the
    card's pump.
    """
    hwnd = _window(hwnd)
    if not hwnd:
        return False
    try:
        u32, k32 = _handles()
    except Exception:                     # noqa: BLE001
        return False
    try:
        if not u32.IsWindow(hwnd):
            return False
        if u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, SW_RESTORE)
        u32.SetForegroundWindow(hwnd)
        if _is_front(u32, hwnd, SETTLE_S):
            return True
        front = int(u32.GetForegroundWindow() or 0)
        mine = int(k32.GetCurrentThreadId())
        theirs = int(u32.GetWindowThreadProcessId(front, None)) if front else 0
        if theirs and theirs != mine and u32.AttachThreadInput(mine, theirs, 1):
            try:
                u32.SetForegroundWindow(hwnd)
            finally:
                u32.AttachThreadInput(mine, theirs, 0)
        return _is_front(u32, hwnd, SETTLE_S)
    except Exception:                     # noqa: BLE001
        log.info("notify: could not raise window %d", hwnd, exc_info=True)
        return False


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

    def show(self, items) -> None:
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
        self.card_seconds = int(getattr(cfg, "card_seconds", 0))
        self.stack_max = max(1, int(getattr(cfg, "stack_max", STACK_MAX)))
        self.remind_every_s = float(getattr(cfg, "remind_every_s", 120))
        self.remind_times = int(getattr(cfg, "remind_times", 2))
        self.coalesce_s = float(getattr(cfg, "coalesce_s", 5))
        interrupt = str(getattr(cfg, "interrupt", "input") or "").lower()
        self.interrupt = interrupt if interrupt in INTERRUPTS else "input"
        self.quiet_s = float(getattr(cfg, "quiet_s", 0))
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
        # session -> {"id", "timer"} for a finish still waiting for the
        # session that sent it to go quiet. One slot per session, so two
        # sessions working at once never hold each other's cards back.
        self._held: dict[str, dict] = {}
        self._gen = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_gen = -1
        self._fired = 0
        # The third way a card goes down: he arrives at its session. On
        # unless [notify] dismiss_on_arrival says otherwise, and one
        # thread for the whole column, not one per card — it ends by
        # itself the moment nothing unread names a session.
        self.arrive_on = bool(getattr(cfg, "dismiss_on_arrival", True))
        self._watch_stop: threading.Event | None = None
        self._watch_thread: threading.Thread | None = None

    # -- in --

    def receive(self, payload, *, urgent: bool = False) -> dict:
        """One notification in. ValueError from clean() propagates — the
        server turns it into a 400; everything else is answered here.

        `urgent` is the dashboard's Send-a-test and nothing else: the
        owner pressing a button to hear the cue and see the card, so it
        is never held and always rings, whatever [notify] interrupt and
        quiet_s say about a finish that arrives on its own."""
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
            # Whatever this is, the session that sent it has spoken
            # again, so its older finish is describing a moment that has
            # passed and is retired here rather than shown.
            self._supersede(item)
            # A card that names a session can now be taken down by him
            # walking into that session, so the watcher runs from here
            # until nothing unread names one. Armed before the hold, not
            # after: a held finish is still a card that will be shown.
            self._watch_arm()
            if not urgent and self._hold(item):
                # A finish waits for its session to go quiet. Nothing is
                # played and nothing is armed; the column is redrawn
                # because the supersede above may have taken a card out
                # of it. The timer does the rest, or the next arrival
                # does, whichever comes first.
                self._present()
                return {"ok": True, "id": item["id"],
                        "unread": self.store.unread(), "coalesced": False,
                        "held": True}
            coalesced = self._raise(item, urgent=urgent)
        return {"ok": True, "id": item["id"], "unread": unread,
                "coalesced": coalesced, "held": False}

    def test(self, *, source: str = "test") -> dict:
        return self.receive({
            "source": source, "kind": "done", "title": "A test notification",
            "body": "הכרטיס עובד — Hebrew and English both render. Click "
                    "it, press Esc over it, or tap the dismiss key.",
            "project": "dashboard"}, urgent=True)

    # -- who may pull him out, and when --

    def _may_interrupt(self, kind: str) -> bool:
        """May a notification of this kind play the cue and keep coming
        back? [notify] interrupt decides: "all" is everything, as it was;
        "input" is the ones waiting on him (a permission, a question, an
        idle session) and the ones that went wrong; "none" never rings."""
        if self.interrupt == "all":
            return True
        if self.interrupt == "none":
            return False
        return str(kind) in LOUD

    def _loud_unread(self) -> int:
        """How many unread notifications may pull him out — held ones do
        not count, because they are not on the screen to be answered."""
        waiting = {h["id"] for h in self._held.values()}
        return sum(1 for i in self.store.items()
                   if not i.get("seen")
                   and int(i.get("id", 0)) not in waiting
                   and self._may_interrupt(str(i.get("kind", "info"))))

    def _key(self, item) -> str:
        """Which session an item belongs to, for holding and superseding.

        The session id when there is one — that is the whole point, since
        two Claude sessions running at once must not retire each other's
        cards. A sender that names no session falls back to its source,
        marked so it can never collide with a real session id."""
        return str(item.get("session", "")) or f"~{item.get('source', '')}"

    def _supersede(self, item) -> None:
        """This session's older finish is no longer news.

        The session that sent this arrival has spoken again, so a "Claude
        finished" from it that is STILL UNREAD is describing a moment
        that has passed: it is marked seen without ever having been read.
        One session, one finish, the newest. A held one is dropped the
        same way, timer and all. Everything another session sent is left
        exactly where it is."""
        session = self._key(item)
        held = self._held.pop(session, None)
        if held is not None:
            held["timer"].cancel()
        ident = int(item.get("id", 0))
        stale = [int(i.get("id", 0)) for i in self.store.items()
                 if not i.get("seen") and i.get("kind") == "done"
                 and int(i.get("id", 0)) != ident
                 and self._key(i) == session]
        if stale:
            self.store.mark_seen(stale)
            names = " ".join(f"#{s}" for s in stale)
            self._log(f"SUPERSEDED {names} by #{ident} | same session")
            log.info("notify: superseded %s by #%d — same session",
                     names, ident)

    def _hold(self, item) -> bool:
        """A finish waits for its session to go quiet. Held?

        THE REASON THIS EXISTS. Claude Code fires its Stop hook at the
        end of EVERY turn, and a turn that ends "now I will do X" is not
        a finish anybody needs to be told about — but it looks exactly
        like one from here. So a `done` is not shown when it lands: it is
        held for `quiet_s`, and if its session speaks again inside that
        window the held one is retired unseen (see `_supersede`) and the
        new one takes the slot. Only a session that has been quiet for
        `quiet_s` puts a card up, which is as close as this door can get
        to "tell me when you are actually finished".

        `quiet_s = 0` holds nothing and every finish lands at once —
        how this worked before 2026-09-05, and the shipped value again
        since that afternoon: under 60 the day's log showed 28 finishes
        held and 26 of them up exactly 60 s late, none earlier, and the
        owner wants the card the moment Claude stops. The hold stays
        here for whoever sets the key back. Only `done` is ever held:
        a permission, a question or an error is wanted NOW, and holding
        one would be the opposite of the point.
        """
        if self.quiet_s <= 0 or str(item.get("kind", "")) != "done":
            return False
        session = self._key(item)
        ident = int(item["id"])
        timer = threading.Timer(self.quiet_s, self._quiet, args=(session,
                                                                 ident))
        timer.daemon = True
        timer.name = "notify-quiet"
        self._held[session] = {"id": ident, "timer": timer}
        self._log(f"HELD #{ident} | waiting {self.quiet_s:g} s for "
                  f"{session or 'an unnamed sender'} to go quiet")
        log.info("notify: holding #%d for %g s — waiting for %s to go quiet",
                 ident, self.quiet_s, session or "an unnamed sender")
        timer.start()
        return True

    def _quiet(self, session: str, ident: int) -> None:
        """`quiet_s` gone by with nothing more from that session: the
        finish it was holding becomes a card after all. Runs on the
        timer's own thread, and takes the lock like every other way in.

        Four things can have happened while it slept, and all four end
        here quietly: the slot was taken by a newer arrival, the slot was
        emptied, the item was dismissed, the store dropped it."""
        with self._lock:
            held = self._held.get(session)
            if held is None or held["id"] != ident:
                return
            del self._held[session]
            item = self._item(ident)
            if item is None or item.get("seen"):
                return
            self._log(f"QUIET #{ident} | {session or 'an unnamed sender'} "
                      f"stayed quiet, the card is up")
            log.info("notify: #%d shown — its session stayed quiet", ident)
            self._raise(item)

    def _raise(self, item, *, urgent: bool = False) -> bool:
        """Put one arrival on the screen: the cue, the column, the
        reminders. Returns whether the cue was coalesced away.

        The cue and the reminders are only for a kind that MAY interrupt
        (or a test the owner asked for) — everything else gets the column
        and nothing more, which is the whole of the quiet. The column
        always follows the newest, cued or not: the new card goes on TOP
        of the ones still unread behind it. The lock is held by every
        caller."""
        kind = str(item.get("kind", "info"))
        source = str(item.get("source", ""))
        now = self._clock()
        coalesced = now - self._cue_at.get(source, -1e9) < self.coalesce_s
        loud = urgent or self._may_interrupt(kind)
        if self.cue_on and loud and not coalesced:
            self._cue("notify")
            self._cue_at[source] = now
        self._present()
        if loud:
            self._arm()
        return coalesced

    # -- the column --

    def live(self) -> list[dict]:
        """What belongs on screen right now: every unread notification,
        NEWEST FIRST, at most `stack_max` of them.

        Each entry is the stored item plus the two things the painter
        cannot work out for itself — `label` (who sent it, in words) and
        `unread` (how many there are altogether). When the store holds
        more unread than the column shows, the LAST entry also carries
        `"more": N`, and the painter puts one faint "+N earlier" line
        under it: the column has a ceiling, and the owner should be able
        to see that it does.

        An empty list means nothing is unread, which is the one thing
        that takes the card down. A finish still being HELD is unread and
        is deliberately not here: it is in the store and in the
        dashboard's history, but it has not earned the screen yet.
        """
        with self._lock:
            waiting = {h["id"] for h in self._held.values()}
            items = [i for i in self.store.items()
                     if not i.get("seen")
                     and int(i.get("id", 0)) not in waiting]
        items.reverse()
        unread = len(items)
        shown = [dict(i, unread=unread, label=label_for(i.get("source", "")))
                 for i in items[:self.stack_max]]
        if shown and unread > len(shown):
            shown[-1] = dict(shown[-1], more=unread - len(shown))
        return shown

    # -- out --

    def dismiss(self, item_id=None, *, by: str = "key") -> dict:
        """Seen. One card with an id, everything without one.

        No id is what the dismiss key, Esc over the card and the
        dashboard's Dismiss all have always meant, and it keeps meaning
        it: everything seen, the reminders cancelled, the column down.
        An id is the × on ONE card of the column (2026-09-04): only that
        item is marked seen and the rest of the column is shown again,
        so the others do not blink out with it.
        """
        with self._lock:
            ident = _ident(item_id)
            n = self.store.mark_seen(None if ident is None else [ident])
            left = self._present()
            if not left:
                # Nothing unread: the reminders have nothing to remind
                # about, whether this was one card or all of them.
                self._gen += 1
                self._stop.set()
            named = "" if ident is None else f" #{ident}"
            self._log(f"DISMISSED{named} by {by} | {n} marked seen")
            log.info("notify: dismissed%s by %s | %d marked seen", named, by, n)
            return self.state()

    def open(self, item_id=None, *, by: str = "card") -> dict:
        """Go to whoever sent a notification, and dismiss it.

        This is what a click anywhere on a card except its × means
        (asked for 2026-09-04): the owner is not saying "seen", he is
        saying "take me there". So the item's `link` is handed to the
        shell — for a Claude Code notification that is the session's own
        `claude://` link, worked out by notify_hook.session_link — and
        then the item's `hwnd` is raised — the Claude window, named by
        notify_hook.owner_window's walk up the parent processes — and
        then everything dismiss() does happens anyway, because arriving
        at the work IS having read the notification.

        THE LINK GOES FIRST because it is the slow half: it spawns a
        process, which talks to the app, which navigates. The raise is
        instant, so starting the journey and then bringing the window
        forward puts the two together; the other order would show the
        window still on the last session for as long as the trip takes.

        With an id it is one card of the column: that item's window,
        that item marked seen, the rest of the column still up. Without
        one it is the newest item's window and the old whole-hearted
        dismissal, which is what the dashboard's Open button and a card
        that is alone on screen both mean.

        A window that has since closed, one Windows will not bring
        forward, a notification that named no session, or a shell that
        would not take the link, is not an error and does not cost the
        dismissal: it is logged as what it was and the card still goes
        down.
        """
        with self._lock:
            ident = _ident(item_id)
            target = self._item(ident)
            hwnd = _window((target or {}).get("hwnd"))
            link = _link((target or {}).get("link"))
            app = str((target or {}).get("app", "") or "")
            name = f"#{target['id']}" if target else "#-"
            if link:
                went = bool(open_link(link))
                to = " | to the session" if went else \
                    " | but the session would not open"
            else:
                went, to = False, ""
            if hwnd:
                raised = bool(raise_window(hwnd))
                note = "" if raised else " | but it would not come forward"
                self._log(f"OPENED {name} -> {app or 'a window'} "
                          f"({hwnd}){note}{to}")
                log.info("notify: opened %s by %s -> %r (%d)%s%s", name, by,
                         app, hwnd, "" if raised else " — not raised",
                         f" — {link}" if went else "")
            else:
                self._log(f"OPENED {name} | no window to raise{to}")
                log.info("notify: opened %s by %s | no window to raise%s",
                         name, by, f" — {link}" if went else "")
            return self.dismiss(ident, by=by)

    def _item(self, item_id=None) -> dict | None:
        """The item with this id, or the newest when there is no id. An
        id nothing answers to is None — a card the store no longer holds
        is not an error, it is a click that arrived late."""
        if item_id is None:
            return self.store.last()
        for item in self.store.items():
            if int(item.get("id", 0)) == int(item_id):
                return item
        return None

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
                # Unread but deliberately not on screen: a finish still
                # waiting for its session to go quiet. Counted apart so
                # the dashboard can say so instead of showing an unread
                # number with no card to go with it.
                "held": len(self._held),
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
        log.info("notify: %s | store %s | reminders %s | interrupt %s | "
                 "a finish waits %s",
                 "on" if self.enabled else "off ([notify] enabled = false)",
                 self.store.path.name,
                 (f"every {self.remind_every_s:g} s x {self.remind_times}"
                  if self.remind_every_s > 0 and self.remind_times > 0
                  else "off"),
                 self.interrupt,
                 (f"{self.quiet_s:g} s for its session to go quiet"
                  if self.quiet_s > 0 else "for nothing"))

    def stop(self) -> None:
        """Cancel the reminder thread and wait for it, briefly. The card
        is main's to stop — it owns the window."""
        with self._lock:
            for held in self._held.values():
                held["timer"].cancel()
            self._held.clear()
            self._gen += 1
            self._stop.set()
            if self._watch_stop is not None:
                self._watch_stop.set()
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
                # The reminders exist for what is WAITING ON HIM. A
                # finish that landed quietly must not keep ringing on
                # its own account, so the count that stops this thread
                # is the loud one, not the whole unread pile.
                if gen != self._gen or stop.is_set() \
                        or self._loud_unread() == 0:
                    return
                unread = self.store.unread()
                if self.cue_on:
                    self._cue("notify")
                self._present()
                self._fired = i + 1
                self._log(f"REMINDED {i + 1}/{self.remind_times} | "
                          f"unread {unread}")
                log.info("notify: reminded %d/%d | unread %d", i + 1,
                         self.remind_times, unread)

    # -- he arrived --

    def _watch_arm(self) -> None:
        """Make sure the arrival watcher is running. One thread for the
        whole column: it asks about every unread card that names a
        session, so a second one would only ask the same question
        twice."""
        if not self.arrive_on:
            return
        thread = self._watch_thread
        if thread is not None and thread.is_alive():
            return
        stop = threading.Event()
        self._watch_stop = stop
        self._watch_thread = threading.Thread(
            target=self._watch, args=(stop,), daemon=True,
            name="notify-arrival")
        self._watch_thread.start()

    def _watch(self, stop: threading.Event) -> None:
        """Take down each card whose session he has walked into.

        One card at a time, by id, through the same dismiss() the × goes
        through — so the rest of the column stays up, which is the whole
        of what he asked for. `by="arrival"` rather than "card" so
        notify.log can be counted: a dismissal he never touched is a
        different event from one he did, and if this ever eats something
        it should be visible in the log without a debugger.

        The store is read OUTSIDE the lock: it is file IO on a timer and
        the engine's lock is held by arrivals and by the card. Ends by
        itself when nothing unread names a session, so an idle machine
        pays nothing.
        """
        while not stop.wait(ARRIVAL_POLL_S):
            with self._lock:
                waiting = [dict(i) for i in self.store.items()
                           if not i.get("seen")
                           and str(i.get("session", "") or "")]
            if not waiting:
                return
            focus = focus_times()
            for item in waiting:
                if stop.is_set():
                    return
                if arrived(item, focus):
                    self.dismiss(int(item.get("id", 0)), by="arrival")

    # -- plumbing --

    def _present(self) -> list[dict]:
        """Put the live column on screen, or take the card down when
        there is nothing left in it. Returns what it showed, so a caller
        can ask "is anything still unread?" without a second read of the
        store. Never raises: a card that cannot paint must not cost the
        dismissal, the HTTP reply or the reminder that called this."""
        items = self.live()
        try:
            if items:
                self._show(items)
            else:
                self.card.hide()
        except Exception:                 # noqa: BLE001
            log.info("notify: the card would not take the column",
                     exc_info=True)
        return items

    def _show(self, items: list[dict]) -> None:
        """`card.show(items)` — the whole column, newest first.

        TOLERANCE, AND IT IS MEANT TO GO. The card that takes a LIST
        lands with the card package (overlay.NotifyCard, 2026-09-04);
        until it does, and on any branch without it, `show` still takes
        one item dict. Rather than guess from an exception raised deep
        inside a painter, ask the method what it calls its first
        argument: the old one names it `item`, the new one `items`. A
        single-item card is shown the NEWEST of the column, which is
        exactly what it did before there was a column. Delete this
        method's fork — not the method — once both halves have landed.
        """
        show = self.card.show
        try:
            first = next(iter(inspect.signature(show).parameters), "")
        except (TypeError, ValueError):   # a builtin, a C callable, a mock
            first = ""
        if first == "item":
            show(dict(items[0]))
        else:
            show(items)

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
