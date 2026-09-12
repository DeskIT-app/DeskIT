"""Cowork's notices, taken off Windows' own notification store.

WHAT THIS IS FOR. The notify door (notify.py) waits for somebody to
knock. Claude Code knocks through notify_hook.py, out of a Stop hook in
~/.claude/settings.json — a file on THIS machine, which is the whole
reason that half works. Cowork has no such file: its sessions run in
Anthropic's cloud and the desktop app is only their window, so there is
nothing here to hook and nothing to install. What the app does do is
raise a Windows toast — "IDF selection test prep | Claude is waiting for
your input" — which lives a few seconds in the corner of the screen and
after that only in the Action Center, and that is exactly the
notification the owner asked for a card instead of.

So this module asks the app for nothing. It reads the toasts Windows has
already written down and hands the ones worth a card to the same engine,
in the same shape a POST /notify arrives in.

WHERE THE TOASTS ARE (measured 2026-09-04). Every toast raised on this
machine lands in one SQLite file:

    %LOCALAPPDATA%\\Microsoft\\Windows\\Notifications\\wpndatabase.db

`Notification` (Id, HandlerId, Tag, Group, Payload, ArrivalTime) joined
to `NotificationHandler` (RecordId, PrimaryId); the app is
`Claude_pzs8sxrjxfjjc!Claude` and the payload is the toast's own XML,
title and body as two <text> nodes. The row is there IMMEDIATELY: a
probe toast raised at 17:21:49.356 was row 958683 with an ArrivalTime of
17:21:49.371 — 15 ms — so `poll_s` below is the whole of the delay
between the toast and the card.

WHERE THE REST OF THE WAIT GOES, AND WHY THE POLL IS A QUARTER SECOND
(measured 2026-09-04, after the owner asked whether the card could come
sooner). It can, by about a second and a half, and by nothing more.

He reported "two minutes" between Cowork's answer and the card. That is
not what happened. Two sessions were rebuilt from their own server event
streams out of the app's HTTP cache, one of them end to end: sandbox
allocated 17:48:07.322, his message 17:48:13.049, the last words of the
answer 17:48:18.508, the turn's result and Stop hook 17:48:19.700 — and
the Windows toast at 17:48:28.818. Nine seconds, not two minutes; that
whole session lived 12.4 s. Across eight idle toasts on three days the
gap from the server's turn-end event to the toast is 6.3, 6.3, 6.4, 6.4,
8.9, 8.9, 9.1, 9.4 s. The "two minutes" was time since an EARLIER pane's
answer, on a screen holding three Claude Code sessions and a
create-test-delete loop of throwaway Cowork ones.

Those nine seconds are a DELIBERATE HOLD, and not the desktop app's. The
toast is built by the claude.ai WEB page — `cowork-${trigger}-${id}` is
where the tag comes from, which is why it is not in the app's bundle
anywhere — and the page holds it on a timer (10,000 ms on the fast path
in force here; 35,000 ms if a server-side flag flips, with no local
warning) before calling the app's IPC; the app forwards it with no
debounce and no queue. So the app is not late, it is waiting on purpose,
and nothing here is told sooner: a sweep of 21,827 files under both of
the app's data folders found ZERO writes between the turn ending and the
toast, no Claude process holds a listening port, the VM service pipe
refuses callers outside the app's own package, and the window's
accessibility tree is DOWNSTREAM — on the one turn end caught by three
clocks at once the toast beat the window by 0.5 to 1.3 s. Those nine
seconds are reachable only by holding claude.ai's private session stream
with the app's OAuth token: the owner's conversations and borrowed
credentials, for nine seconds. Not a trade this app makes.

What was left was ours: the poll. At 0.25 s, 240 checks over 60 s cost
159 ms of CPU altogether — 0.26% of one core — because `changed()` is
three stat calls and only a real write pays the 33 ms copy (one poll in
240 over that minute). The card now trails the toast by ~0.1 s on
average instead of up to 2 s, and the honest total is about ten seconds,
nine of which belong to somebody else.

THE FILE'S OWN mtime IS A LIE. It read 14:59 while rows were arriving at
17:21, because the writes are in the write-ahead log beside it. So
`changed()` stats all three parts, and `read()` copies all three (2 MB,
~10 ms) rather than open the live file the notification service is
holding.

WHAT THE TAGS MEAN — 23 Claude rows over four days, and the app's own
bundle agrees:

    cowork-idle-cse_…       Cowork: "Claude is waiting for your input"
    cowork-awaiting-cse_…   Cowork: "Claude needs your input to continue"
    cu-lock-cse_…           Cowork: done using your computer
    idle-local_<uuid>       a Claude Code session in the app went idle
    ask-question-<uuid>     a Claude Code session is asking something
    scheduled-local_<uuid>  a SCHEDULED Claude Code session finished a turn
                            ("Scheduled task completed" / the task's name;
                            group is the literal "Notifications", not the
                            session — the session is only in the tag)

`Group` carries the session for the Code ones (`session-local_<uuid>`)
and the literal "Notifications" for Cowork's — and for the scheduled one,
which is why `scheduled-` is read from the tag like Cowork's ids are. That `local_<uuid>` is the
app's OWN session id — the thing `claude://resume?session=` wants, which
notify_hook.session_link has to dig out of the app's store and which is
written on the notification here for free — so a Code card from this
route can still open the session that sent it. A Cowork one cannot: its
id is a `cse_…`, and both links the app advertises for those are gated
off on Anthropic's side (the measurements are in notify_hook.py). That
card raises the window and leaves the last step to the owner.

AND CHAT ANNOUNCES NOTHING. Not "we could not find it": the desktop
app's notification service knows two products, `ccd` and `cowork`, and
three kinds, idle / permission_request / ask_user_question (its own
bundle, grepped 2026-09-04; four days of this database say the same). A
chat reply that finishes is not told to Windows, to a hook, or to
anything else on this machine — so there is nothing here for this module
or any other to hear. If that ever changes it needs no code: an
unrecognised Claude toast is still shown, as `claude` / `info`.

WHY IT DOES NOT DOUBLE UP. The app only toasts a session you are NOT
looking at (`isUserViewingSession`, same bundle), and Claude Code's Stop
hook has already put a card up for every finished turn. So `[notify]
watch = "cowork"` — the default — ignores the `idle-`, `ask-question-`
and `scheduled-` tags and takes everything else; "all" takes those too,
which is worth it only with the hook uninstalled; "off" never opens the
file.

THE SCHEDULED ONE WAS THE CARD THAT NEVER CAME DOWN. Measured in
notify.log on 2026-09-12: nineteen "Scheduled task completed" cards, each
landing within a second of the hook's own "Claude finished" for the same
turn of the weekly-review session, and every one of the nineteen
dismissed by hand — because its tag was not in PREFIXES, `session_of`
found no session, and a card with no session is one the arrival watch
(notify.py) can never take down. That is the report of 2026-09-04
("the notify message … is not disappearing when I'm opening … the thing
that is notified") still happening a week after arrival was built: the
hook's card came down when he reached the session, and its twin stayed.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

log = logging.getLogger("app")

DB = (Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows"
      / "Notifications" / "wpndatabase.db")
PARTS = ("", "-wal", "-shm")   # the database, its write-ahead log, its index
WORK = "hd-notify-watch.db"    # the copy we read, in the temp folder
POLL_S = 0.25                  # a quarter second, and it costs nothing —
                               # see WHERE THE REST OF THE WAIT GOES, below
BATCH = 20                     # rows handed on per pass; a flood of toasts is
                               # the app's problem, not a reason to fill the
                               # column with fifty cards at once
MODES = ("off", "cowork", "all")
APP = "Claude_pzs8sxrjxfjjc!Claude"   # this machine's; matched loosely below,
                                      # because the middle is a signing hash

# tag prefix -> the kind of card it makes. Longest first: "cowork-idle-"
# must not be read as "idle-". Anything else Claude raises is `info`.
PREFIXES = (("cowork-awaiting-", "input"),
            ("cowork-idle-", "input"),
            ("ask-question-", "input"),
            ("cu-lock-", "info"),
            ("scheduled-", "done"),
            ("idle-", "done"))
GROUP = "session-"             # ...<the app's own session id>
CODE = "local_"                # a session the desktop app owns
CLOUD = "cse_"                 # a Cowork session, which lives in the cloud
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                  r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def is_claude(primary_id) -> bool:
    """Is this handler the Claude desktop app? `Claude_<hash>!Claude`.
    The hash is the publisher's and would survive a reinstall, but not a
    change of signing identity — so the shape is matched, not the string."""
    name = str(primary_id or "")
    return name.startswith("Claude_") and name.endswith("!Claude")


def texts(payload) -> list[str]:
    """The <text> nodes of a toast, whitespace tidied, in order: title
    first, body second. [] for anything that will not parse — a payload
    is written by another program and this one may not raise over it."""
    raw = payload
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8", "replace")
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        root = ET.fromstring(raw)
    except Exception:                     # noqa: BLE001
        return []
    return [" ".join((node.text or "").split()) for node in root.iter("text")]


def session_of(tag, group) -> str:
    """Which session a toast is about: `local_<uuid>` for a Claude Code
    session in the app, `cse_…` for a Cowork one, "" when it says
    nothing. The Group is asked first because it is the app's own field
    for exactly this; the tag is where Cowork's id lives."""
    name = str(group or "")
    if name.startswith(GROUP):
        return name[len(GROUP):]
    tag = str(tag or "")
    for prefix, _kind in PREFIXES:
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return ""


def source_of(tag, session) -> str:
    """Who the card is from, in notify.SOURCES' words. The session id
    decides — `local_` is one of the app's Claude Code sessions, `cse_`
    is Cowork — and the tag decides for the ones that name no session
    (`cu-lock-` is Cowork's computer-use lock)."""
    if session.startswith(CODE):
        return "claude-code"
    if session.startswith(CLOUD) or str(tag or "").startswith("cowork"):
        return "cowork"
    if str(tag or "").startswith("cu-lock-"):
        return "cowork"
    return "claude"               # something new from the app: still shown


def link_of(session) -> str:
    """`claude://resume?session=<uuid>` for a session the desktop app
    owns, "" for a Cowork one — see the module docstring for why that
    door is bolted, and notify_hook.session_link for the measurements."""
    if not session.startswith(CODE):
        return ""
    uuid = session[len(CODE):]
    return f"claude://resume?session={uuid}" if UUID.match(uuid) else ""


def payload_from_toast(tag, group, payload, window=None) -> dict | None:
    """The /notify body for one toast, or None when it says nothing a
    card could show (no title, no body — the app raises those to update
    a toast already on screen).

    `window` is the (hwnd, title) a click will raise; left None it is
    `claude_window()` — a parameter only so a test can say what the
    answer is instead of taking whatever is on the desktop.
    """
    said = [t for t in texts(payload) if t]
    if not said:
        return None
    kind = "info"
    for prefix, that in PREFIXES:
        if str(tag or "").startswith(prefix):
            kind = that
            break
    session = session_of(tag, group)
    hwnd, app = claude_window() if window is None else window
    return {"source": source_of(tag, session), "kind": kind,
            "title": said[0], "body": " ".join(said[1:]),
            "project": "", "session": session,
            "hwnd": int(hwnd), "app": str(app), "link": link_of(session)}


# ---------------------------------------------------------------------------
# the app's window
# ---------------------------------------------------------------------------
# notify_hook.py can walk UP from itself to find the window that sent a
# notification, because Claude Code runs it as a child. Nothing here is a
# child of anything: the toast was written by a service and read off a
# file minutes later, so the window has to be FOUND. Every visible,
# titled, top-level window is asked which process owns it and that
# process is asked for its image name; `claude.exe` is the app. Its
# helper processes carry the same name and own no such window, so the
# first hit is the one window the app has (43779834 on this machine —
# and one window is all it has, which is why a Cowork card can raise it
# but cannot land on the session).

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
EXE = "claude.exe"
NAME_MAX = 32768


def _exe_of(k32, pid: int) -> str:
    """The image name of one process, lowercased, or "". Opened with
    QUERY_LIMITED_INFORMATION, which a same-user process grants without
    any privilege at all."""
    handle = None
    try:
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
        if not handle:
            return ""
        size = ctypes.c_ulong(NAME_MAX)
        buf = ctypes.create_unicode_buffer(NAME_MAX)
        if not k32.QueryFullProcessImageNameW(handle, 0, buf,
                                              ctypes.byref(size)):
            return ""
        return Path(buf.value).name.lower()
    except Exception:                     # noqa: BLE001
        return ""
    finally:
        if handle:
            try:
                k32.CloseHandle(handle)
            except Exception:             # noqa: BLE001
                pass


def claude_window() -> tuple[int, str]:
    """(hwnd, title) of the Claude desktop app's window, or (0, "").

    Never raises: a machine that answers none of this simply sends a
    notification whose card cannot be clicked open, which is what a
    notification without an `hwnd` has always meant.

    The handles get restypes because a 64-bit HANDLE does not fit the
    c_int ctypes assumes — and they are set on PRIVATE ctypes.WinDLL
    objects, never on ctypes.windll, which is process-global and shared
    with every other module here (AGENTS.md).
    """
    found: list = []
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int,
                                    ctypes.c_ulong]
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.QueryFullProcessImageNameW.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ulong)]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        proto = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                                   ctypes.c_void_p)
        u32.EnumWindows.argtypes = [proto, ctypes.c_void_p]
        u32.GetWindowThreadProcessId.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        u32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        u32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        u32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                       ctypes.c_int]

        @proto
        def collect(hwnd, _param):
            if found:
                return 0                  # stop the walk at the first hit
            try:
                if not u32.IsWindowVisible(hwnd):
                    return 1
                length = int(u32.GetWindowTextLengthW(hwnd))
                if length <= 0:
                    return 1
                buf = ctypes.create_unicode_buffer(length + 1)
                u32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if not title:
                    return 1
                owner = ctypes.c_ulong()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if _exe_of(k32, owner.value) == EXE:
                    found.append((int(hwnd), title))
                    return 0
            except Exception:             # noqa: BLE001
                pass
            return 1

        u32.EnumWindows(collect, None)
    except Exception:                     # noqa: BLE001
        return 0, ""
    return found[0] if found else (0, "")


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------

class Store:
    """Windows' notification database, read through a copy.

    `path` and `work` are parameters so a test can hand over a database
    it built itself; left alone they are the machine's and a file in the
    temp folder. Nothing here writes to the real one.
    """

    def __init__(self, path=None, work=None) -> None:
        self.path = Path(path) if path is not None else DB
        self.work = (Path(work) if work is not None
                     else Path(tempfile.gettempdir()) / WORK)
        self._seen: tuple | None = None

    def _stat(self) -> tuple:
        out = []
        for part in PARTS:
            try:
                info = os.stat(f"{self.path}{part}")
                out.append((info.st_size, info.st_mtime_ns))
            except OSError:
                out.append(None)
        return tuple(out)

    def changed(self) -> bool:
        """Has anything been written since the last look? All three parts,
        because the database's own mtime stands still for hours while the
        write-ahead log beside it takes every row."""
        now = self._stat()
        if now == self._seen:
            return False
        self._seen = now
        return True

    def _copy(self):
        """A connection to a fresh copy, or None. The log and the index
        come too — without them sqlite reads the file as it was at the
        last checkpoint, which is to say hours ago."""
        try:
            shutil.copyfile(self.path, self.work)
        except OSError:
            return None
        for part in PARTS[1:]:
            try:
                shutil.copyfile(f"{self.path}{part}", f"{self.work}{part}")
            except OSError:
                try:
                    os.remove(f"{self.work}{part}")
                except OSError:
                    pass
        try:
            return sqlite3.connect(self.work)
        except sqlite3.Error:
            return None

    def read(self, after: int, limit: int = BATCH) -> tuple[list, int]:
        """(Claude's toasts with an Id above `after`, oldest first; the
        highest Id in the table.) Each row is (id, tag, group, payload).

        The watermark that comes back is the WHOLE table's, not Claude's:
        it moves past everybody else's notifications too, so a quiet
        evening of Teams messages is not re-read four times a second.

        There is no LIMIT in the query and there must not be: the
        watermark jumps to the end of the table, so a row left unread by
        a limit would be a row lost. The table is a few dozen rows —
        Windows prunes it to what the Action Center holds — and what is
        read here is only what arrived since the last pass, so the trim
        to `limit` happens after the read, keeping the NEWEST: more
        toasts than a column can hold at once means the oldest are the
        ones nobody will read.

        ([], after) on any failure — a torn copy of a live database is a
        pass that finds nothing, never an exception and never a
        watermark past a row it did not read.
        """
        con = self._copy()
        if con is None:
            return [], after
        rows: list = []
        top = after
        try:
            cur = con.cursor()
            cur.execute("select max(Id) from Notification")
            got = cur.fetchone()
            if got and got[0] is not None:
                top = max(after, int(got[0]))
            cur.execute(
                'select n.Id, n.Tag, n."Group", n.Payload, h.PrimaryId '
                "from Notification n join NotificationHandler h "
                "on h.RecordId = n.HandlerId where n.Id > ? "
                "order by n.Id", (int(after),))
            for ident, tag, group, payload, who in cur.fetchall():
                if is_claude(who):
                    rows.append((int(ident), tag, group, payload))
        except (sqlite3.Error, ValueError, TypeError):
            log.debug("notify watch: could not read the notification "
                      "store", exc_info=True)
            return [], after
        finally:
            try:
                con.close()
            except sqlite3.Error:
                pass
        if limit > 0 and len(rows) > limit:
            rows = rows[-limit:]
        return rows, top

    def latest(self) -> int:
        """The highest Id in the table, or 0 — where a watcher starts, so
        that a restart does not replay every toast of the last four days."""
        con = self._copy()
        if con is None:
            return 0
        try:
            cur = con.cursor()
            cur.execute("select max(Id) from Notification")
            got = cur.fetchone()
            return int(got[0]) if got and got[0] is not None else 0
        except (sqlite3.Error, ValueError, TypeError):
            return 0
        finally:
            try:
                con.close()
            except sqlite3.Error:
                pass


# ---------------------------------------------------------------------------
# the watcher
# ---------------------------------------------------------------------------

class Watcher:
    """The poll loop: new Claude toasts become notifications.

    `sink` is one callable taking the payload — main.py hands over the
    same one the /notify route uses, so a toast and a POST arrive at the
    engine by the same road and are stored, cued, coalesced and reminded
    about identically.

    `mode` is [notify] watch: "off" | "cowork" | "all". Everything is
    cheap and nothing raises: a bad database, a locked file, a sink that
    throws — all of it is a line in app.log and a pass that found
    nothing.
    """

    def __init__(self, sink, mode: str = "cowork", *, store=None,
                 poll_s: float = POLL_S, window=None) -> None:
        self.sink = sink
        self.mode = str(mode or "off").strip().lower()
        if self.mode not in MODES:
            self.mode = "cowork"
        self.store = store if store is not None else Store()
        self.poll_s = float(poll_s)
        self._window = window          # a test's answer for claude_window()
        self._after: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- what belongs to the owner --

    def wanted(self, tag) -> bool:
        """Does this toast get a card? "cowork" — the default — drops
        the desktop app's Claude Code sessions, because notify_hook.py
        has already carded every one of their turns and two cards for
        one turn is worse than none. A scheduled session's turn is one of
        those — its toast just wears a different tag (module docstring)."""
        if self.mode == "all":
            return True
        if self.mode != "cowork":
            return False
        tag = str(tag or "")
        return not (tag.startswith("idle-") or tag.startswith("ask-question-")
                    or tag.startswith("scheduled-"))

    # -- one pass --

    def once(self) -> int:
        """One look at the store; how many notifications were handed on.

        The FIRST call only takes the watermark: everything already in
        the database happened before the app started and the owner has
        either seen it or stopped caring.
        """
        if self.mode == "off":
            return 0
        if self._after is None:
            self._after = self.store.latest()
            log.info("notify watch: watching the desktop app's own "
                     "notifications (%s), from #%d", self.mode, self._after)
            return 0
        if not self.store.changed():
            return 0
        rows, top = self.store.read(self._after)
        self._after = max(self._after, top)
        sent = 0
        for ident, tag, group, payload in rows:
            if not self.wanted(tag):
                log.debug("notify watch: #%d %r is Claude Code's, and the "
                          "hook has it", ident, tag)
                continue
            body = payload_from_toast(tag, group, payload, self._window)
            if body is None:
                continue
            try:
                self.sink(body)
                sent += 1
            except Exception:             # noqa: BLE001
                log.warning("notify watch: could not pass on #%d (%r)",
                            ident, tag, exc_info=True)
        return sent

    # -- the thread --

    def start(self) -> None:
        if self.mode == "off" or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="notify-watch")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.once()
            except Exception:             # noqa: BLE001
                log.warning("notify watch: the pass failed", exc_info=True)
            self._stop.wait(self.poll_s)

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.poll_s + 1)
