"""The desk as a web page: React in WebView2 (webdesk.py's shell), the
same five places as the Tk desk, built one at a time.

WHY (2026-10-23). After a day of cutting the Tk desk down — places kept
built, every in-place redraw under a cover, no slide — a switch back to a
place was still 150-255 ms and the owner's verdict on the result was
"everything feels laggy; you press something and the whole app seems to
reload before it shows what you pressed". Tk is one OS window per widget
and has no animation engine; the master app (dev\\master, the same shell)
switches a screen in 3.5-16 ms and slides its bar's bubble in 0.26 s of
CSS. So the desk moves onto that foundation, place by place, in the
order decided on 2026-09-22: Home, Corrections, Said, Keys, Settings.

WHAT IS HERE. Home only (`BUILT`). The other four are on the bar and say
so, with one button that opens the Tk desk at that place (`dashboard.py
--tk --place X`): the web desk takes a mutex of its own, so the two can
stand side by side while the move is under way. `[desk] web` in
defaults.toml opens this instead of the Tk desk, in the checkout only
(dashboard.main); the release keeps Tk until all five are here — never a
half-moved window in a release (the owner, 2026-09-22). Each of the four
has a module of its own (`PLACES_MOD`: desk_corrections.py, desk_said.py,
desk_keys.py, desk_settings.py) and a page of its own (web/src/places/),
reached through `Api.place` — so five sessions can build the five places
at once without editing one file (web/README.md says who owns what).

THE MODEL IS PYTHON, THE PICTURE IS THE PAGE. `Model.home()` answers one
question — everything Home shows, as plain data — read from the same
sources the Tk desk reads (the app's status over the pipe, review.json,
notify.json, transcripts.log, the capture folder) with the same words;
`Model.act()` does what a button asks and answers with Home again, so a
press repaints from the truth at once rather than one poll later. The
page polls `home` every 800 ms, the Tk desk's own cadence. No pixel
measuring here: a line that does not fit is cut by the page's CSS, at the
sentence's far end, which is what the Tk desk's measured trimming
approximated in the first place.

Nothing of pywebview is imported at the top (the product suite imports
every module, and CI has no pywebview); `run_window` imports webdesk.

    .venv\\Scripts\\pythonw.exe deskweb.py                 # the window
    .venv\\Scripts\\python.exe deskweb.py --shot x.png     # photographed, hidden
"""
from __future__ import annotations

import ctypes
import logging
import re
import sys
import threading
import time
from pathlib import Path

# The installed interpreter runs under python311._pth, which does not put
# a script's own folder on sys.path (see main.py): the guard every script
# started by path carries, before its first import of ours.
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import config as config_mod  # noqa: E402
import control  # noqa: E402
import history  # noqa: E402
import launch  # noqa: E402
import paths  # noqa: E402
import singleton  # noqa: E402
import summary  # noqa: E402
import version  # noqa: E402

log = logging.getLogger("app")

#: The bar's places, in the Tk desk's order (dashboard.NAV).
PLACES = ("Home", "Corrections", "Said", "Keys", "Settings")
#: The places this desk draws itself. The rest open the Tk desk.
BUILT = ("Home",)
#: The most Home holds (dashboard.PILE_CAP).
PILE_CAP = 3
#: The page is drawn for this client area (the Tk desk's W, H).
CLIENT_W, CLIENT_H = 1160, 720

#: A mutex of its own and not the Tk desk's: "open it in the old desk"
#: starts dashboard.py --tk beside this window, and with one name that
#: launch would only poke this window to the front and exit.
WEBDESK_MUTEX = paths.kernel_name(r"Local\DeskIT.webdesk")
WEBDESK_SHOW = paths.kernel_name(r"Local\DeskIT.webdesk.show")
#: The Tk desk's taskbar identity: the two desks are one app's window.
APP_ID = paths.APP_ID if paths.PACKAGED else paths.APP_ID + ".Dashboard"

#: What the page may call (webdesk's dispatcher checks this list).
CALLS = ("home", "act", "place", "ping")

#: The places drawn by modules of their own, each built by a session of its
#: own in parallel (web/README.md): the page's place call reaches them by
#: these names. Home is drawn by the Model below.
PLACES_MOD = {"corrections": "desk_corrections", "said": "desk_said",
              "keys": "desk_keys", "settings": "desk_settings"}
#: What a place call may do: read the place, or press one of its buttons.
PLACE_OPS = ("read", "act")

#: activity -> (the lamp, the word) — dashboard.LOOKS, said as the four
#: lamps B+ draws (bplus.css .lamp.listen / rec / write / idle).
LOOKS = {
    "stopped":   ("idle", "Off"),
    "starting":  ("write", "Starting"),
    "ready":     ("listen", "Listening"),
    "recording": ("rec", "Recording"),
    "locked":    ("rec", "Locked on"),
    "busy":      ("write", "Transcribing"),
    "paused":    ("idle", "Paused"),
    "off":       ("idle", "Model off"),
    "loading":   ("write", "Loading"),
}

_COUNT_WORDS = ("No", "One", "Two", "Three", "Four", "Five", "Six")
_HEBREW = re.compile(r"[֐-׿]")
#: How many words a context keeps before and after the changes. The one
#: BEFORE is short on purpose: the page cuts a line at its far end, so a
#: long lead-in would push the change itself out of sight — the very
#: thing the row exists to show (the first picture, 2026-10-23, had a
#: proposal with fourteen words in front of it and no change visible).
#: The one after is generous; CSS cuts the rest.
_HEAD_WORDS = 6
_CONTEXT_WORDS = 14
#: A context BETWEEN two changes keeps this many words, middle cut.
_BETWEEN_WORDS = 8
CAPTURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".mp4")

#: The report sheet (Home's Report a problem). Where the report was made
#: from: Home is the only door on this desk. A Send waits this long for
#: the app's worker to carry the copy up before it says "on its way".
REPORT_WHERE = "Home"
REPORT_SEND_WAIT_S = 12.0
#: What the screenshot is shown as on the preview (problems.THUMB_MAX).
REPORT_THUMB_PX = 220
#: The plain words for each piece of the copy that travels — the Tk
#: Preview's file names (problems._FILE_NAMES) said as what they are.
REPORT_PIECES = {"shot.jpg": "Your screen from a moment ago",
                 "dictation.wav": "What you said — the sound",
                 "sidecar.json": "What you said — the words"}
#: The landing's words: dashboard.Dashboard.LANDING_SENTENCE / _STORED.
LANDING_SENTENCE = ("Hebrew dictation for Windows that stays on your PC. Hold a key, "
                    "speak, let go — the Hebrew lands at the cursor, in any window.")
LANDING_STORED = ("What is stored: an account id and the e-mail of the Google account "
                  "you choose; this PC's name, the app's version and Windows'. The server "
                  "is DeskIT's own (Supabase, Frankfurt). Only your voice never leaves this "
                  "PC: your learned words and settings are kept in your account, and so are "
                  "what you said and your cloud keys, locked with a key only your own PCs "
                  "hold. Settings > Privacy > Withdraw turns this off.")
LANDING_WAITING = "Waiting for Google's sign-in page in your browser…"
#: A recovery key as a person types it: Crockford letters and digits in
#: six groups, with or without the dashes and spaces between them.
_RECOVERY_SHAPE = re.compile(r"[0-9A-Za-z][0-9A-Za-z\- ]{14,62}[0-9A-Za-z]")
#: Where a release's notes may open (dashboard._open_url).
_URL_PREFIXES = ("https://github.com/", "https://deskit-app.github.io/",
                 "https://huggingface.co/")


# ------------------------------------------------------------- the words


def count_word(n: int) -> str:
    """"Three things", not "3 things" (dashboard._count_word)."""
    return _COUNT_WORDS[n] if 0 <= n < len(_COUNT_WORDS) else str(n)


def is_rtl(text: str) -> bool:
    return bool(_HEBREW.search(str(text or "")))


def pretty_key(name: str) -> str:
    """'right ctrl' -> 'Right Ctrl'; '' -> 'off' (dashboard.pretty_key)."""
    return name.title() if name else "off"


def key_caps(name: str) -> list[str]:
    """'ctrl+alt+m' -> ['Ctrl', 'Alt', 'M'] — the caps a key is drawn as."""
    return [part.strip().title() for part in str(name or "").split("+") if part.strip()]


def human_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


def stamp_of(text: str, fmt: str) -> float:
    try:
        return time.mktime(time.strptime(str(text)[:19], fmt))
    except (ValueError, TypeError, OverflowError):
        return 0.0


def ago(then: float, now: float | None = None) -> str:
    """"just now", "3 min ago", "2 h ago", "yesterday", "3 Sep"."""
    if not then:
        return ""
    gap = (time.time() if now is None else now) - then
    if gap < 60:
        return "just now"
    if gap < 3600:
        return f"{int(gap // 60)} min ago"
    if gap < 86400:
        return f"{int(gap // 3600)} h ago"
    if gap < 2 * 86400:
        return "yesterday"
    return time.strftime("%d %b", time.localtime(then)).lstrip("0")


def words_learned() -> int | None:
    """How many corrections the vocabulary holds — the count only."""
    import json
    try:
        with paths.VOCAB_FILE.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    entries = data.get("corrections") if isinstance(data, dict) else None
    return len(entries) if isinstance(entries, list) else None


def first_words(text: str, most: int) -> str:
    words = str(text or "").split()
    return " ".join(words) if len(words) <= most else " ".join(words[:most]) + " …"


def change_segments(text: str, changes: list) -> tuple[list[dict], int]:
    """A proposal as what the row draws, in sentence order: contexts and
    changes — {"t": "ctx", "s": ...} and {"t": "chg", "heard", "meant"} —
    with every change in its place (dashboard._change_runs, the figure
    the owner asked for on 2026-09-21). The contexts stop at the
    sentence's own ends ("from point to point", his rule of 2026-09-07)
    and at _CONTEXT_WORDS; the page's CSS cuts whatever still does not
    fit. Returns (segments, how many changes are drawn)."""
    import vocab as vocab_mod
    flat = " ".join(str(text or "").split())
    starts = [m.start() for m in vocab_mod._WORD.finditer(flat)]
    tw = vocab_mod.words(flat)
    raw = [flat[s:(starts[k + 1] if k + 1 < len(starts) else len(flat))].strip()
           for k, s in enumerate(starts)]
    low = [w.lower() for w in tw]
    placed: list = []
    for c in changes:
        heard = " ".join(str(c.get("before") or "").split())
        meant = " ".join(str(c.get("after") or "").split())
        if not heard or not meant or str(c.get("kind")) == "drop":
            continue
        span, i1, i2 = c.get("span"), None, None
        if isinstance(span, (list, tuple)) and len(span) == 2:
            try:
                i1, i2 = int(span[0]), int(span[1])
            except (TypeError, ValueError):
                i1 = i2 = None
            if i1 is not None and not (0 <= i1 < i2 <= len(tw)):
                i1 = i2 = None
        if i1 is None:
            hw = [w.lower() for w in vocab_mod.words(heard)]
            for k in range(len(low) - len(hw) + 1):
                if hw and low[k:k + len(hw)] == hw:
                    i1, i2 = k, k + len(hw)
                    break
        if i1 is None:
            i1 = i2 = len(tw)
        placed.append((i1, i2, heard, meant))
    placed.sort(key=lambda t: t[0])
    kept, end = [], 0
    for i1, i2, heard, meant in placed:
        if i1 >= end:
            kept.append((i1, i2, heard, meant))
            end = max(end, i2)
    if not kept:
        return [{"t": "ctx", "s": summary.first_sentence(text)}], 0

    def stop(word: str) -> bool:
        return bool(word) and word[-1] in summary.STOPS

    head = raw[:kept[0][0]]
    for k in range(len(head) - 1, -1, -1):
        if stop(head[k]):
            head = head[k + 1:]
            break
    tail = raw[kept[-1][1]:]
    for k, word in enumerate(tail):
        if stop(word):
            tail = tail[:k + 1]
            break
    segs: list[dict] = []
    if head:
        cut = len(head) > _HEAD_WORDS
        piece = " ".join(head[-_HEAD_WORDS:])
        segs.append({"t": "ctx", "s": ("… " + piece) if cut else piece})
    for n, (i1, i2, heard, meant) in enumerate(kept):
        if n:
            between = raw[kept[n - 1][1]:i1]
            if len(between) > _BETWEEN_WORDS:
                half = _BETWEEN_WORDS // 2
                between = between[:half] + ["…"] + between[-half:]
            if between:
                segs.append({"t": "ctx", "s": " ".join(between)})
        segs.append({"t": "chg", "heard": heard, "meant": meant})
    if tail:
        cut = len(tail) > _CONTEXT_WORDS
        piece = " ".join(tail[:_CONTEXT_WORDS])
        segs.append({"t": "ctx", "s": (piece + " …") if cut else piece})
    return segs, len(kept)


def _without_phone(reply):
    """status() carries the phone link and its token; the page never
    needs them and a page is not where a secret goes (webdesk.py)."""
    if isinstance(reply, dict):
        reply = dict(reply)
        reply.pop("phone", None)
    return reply


def copy_text(text: str, secret: bool = False) -> bool:
    """Put text on the clipboard from this window's process (the Tk desk's
    clipboard_append). A secret — the recovery key — is marked for
    Windows to keep out of the clipboard history and the cloud clipboard
    (the three formats Microsoft documents for password managers), which
    the Tk desk never did."""
    try:
        import win32clipboard
        import win32con
    except Exception:                     # noqa: BLE001
        return False
    for _ in range(10):
        try:
            win32clipboard.OpenClipboard()
            break
        except Exception:                 # noqa: BLE001 — another program has it
            time.sleep(0.03)
    else:
        return False
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, str(text))
        if secret:
            for name, value in (("ExcludeClipboardContentFromMonitorProcessing", b"\0"),
                                ("CanIncludeInClipboardHistory", b"\0\0\0\0"),
                                ("CanUploadToCloudClipboard", b"\0\0\0\0")):
                win32clipboard.SetClipboardData(
                    win32clipboard.RegisterClipboardFormat(name), value)
        return True
    except Exception:                     # noqa: BLE001
        return False
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:                 # noqa: BLE001
            pass


def _words_of(e: Exception) -> str:
    """What a failure may say on the page: the words of an error this app
    writes for the person (sb.AccountError, updates.UpdateError), the
    type of anything else — never a path or a traceback."""
    for module, name in (("sb", "AccountError"), ("updates", "UpdateError")):
        cls = getattr(sys.modules.get(module), name, None)
        if cls is not None and isinstance(e, cls):
            return str(e)[:200]
    return type(e).__name__


# ------------------------------------------------------------- the model


class Model:
    """Home, as data, and what its buttons do. One per window; the
    page's calls arrive on threads of their own, so every public method
    holds the lock."""

    def __init__(self, send=None) -> None:
        self._send = send or control.send
        self._lock = threading.RLock()
        self.status: dict = {}
        self.running = False
        self.phone_live = False
        self._silent_since: float | None = None
        self._busy_until = 0.0
        self._log: list = []
        self._log_stamp = None
        self._capture_seen = None
        #: notification ids a ✕ here took off, until the file agrees
        self._gone: set = set()
        #: consents he said Not now to, and the last key-less press he
        #: waved away — this window's memory, as in the Tk desk
        self._consent_later: set = set()
        self._needs_key_later = 0.0
        #: a store's rows, kept until its file (or the minute, which the
        #: "3 min ago" words move with) changes: the proposals were 5.6 ms
        #: of a 13 ms poll, read and tokenised again every 800 ms
        self._kept: dict[str, tuple] = {}
        #: the report sheet while it is up (report.open .. report.close):
        #: the screen as it was a moment before, in memory only
        self._report: dict | None = None
        #: the account lock's answers on Home: the recovery key just made
        #: (memory only, never logged, until Done), the field for typing
        #: one, and "Sign out of every PC?" asked on the changed-lock row
        self._lock_fresh = ""
        self._lock_typing = False
        self._lock_asking = False
        #: Download and install, under way: the words the row says
        self._update_line = ""
        #: the landing's own sign-in, with nothing running: its line
        self._landing_line: tuple[str, str] = ("", "")
        self._signing = False
        #: sb.py's word on the session when the app does not answer, and
        #: when it was asked (a DPAPI read; not every 800 ms)
        self._signed_out_seen = (0.0, False)

    def _cached(self, name: str, path: Path, build) -> list[dict]:
        try:
            st = path.stat()
            stamp = (st.st_size, st.st_mtime_ns)
        except OSError:
            stamp = None
        key = (stamp, int(time.time() // 60), frozenset(self._gone))
        kept = self._kept.get(name)
        if kept is not None and kept[0] == key:
            return kept[1]
        rows = build()
        self._kept[name] = (key, rows)
        return rows

    # -- reading

    def _poll(self) -> None:
        reply = self._send("status", timeout_ms=1200)
        if reply is None and singleton.is_running():
            if self._silent_since is None:
                self._silent_since = time.monotonic()
            reply = {"ok": True, "stage": "starting", "activity": "starting",
                     "silent_s": time.monotonic() - self._silent_since}
        else:
            self._silent_since = None
        if time.monotonic() >= self._busy_until or reply is None:
            # Within a second of a press the app may not have caught up,
            # and a status from before the press would flip the button
            # back for one frame (dashboard._refresh).
            self.phone_live = bool((reply or {}).get("phone"))
            self.status = _without_phone(reply or {})
            self.running = bool(reply) and self.status.get("stage") == "running"
        stamp = history.stamp()
        if stamp != self._log_stamp:
            self._log_stamp = stamp
            try:
                self._log = history.load(100)
            except Exception:             # noqa: BLE001 — a log being rotated
                pass

    def _keys(self) -> dict:
        keys = self.status.get("keys")
        if keys:
            return keys
        try:
            cfg = config_mod.load_layered()
        except Exception:                 # noqa: BLE001
            return {}
        return {name: getattr(cfg, name) for name, _label in config_mod.HOTKEY_FIELDS}

    def _activity(self) -> str:
        s = self.status
        starting = bool(s) and s.get("stage") == "starting"
        model = s.get("model") or "on"
        return ("ready" if starting and s.get("silent_s", 0) > 45 else
                "starting" if starting else
                "stopped" if not s else
                "off" if model == "off" else
                "loading" if model in ("loading", "unloading") else
                s.get("activity") or "ready")

    def _bar(self) -> dict:
        s = self.status
        activity = self._activity()
        lamp, word = LOOKS.get(activity, LOOKS["ready"])
        model = s.get("model") or "on"
        uptime = s.get("uptime_s")
        awake = (s.get("awake") or {}) if self.running else {}
        run = ("Start" if not s or model == "off" else
               "Loading…" if model in ("loading", "unloading") else
               "Resume" if s.get("paused") else "Pause")
        return {
            "lamp": lamp, "word": word,
            "meta": f"up {human_time(uptime)}" if uptime else "not running",
            "run": run,
            # Stop only while there is a model to stop; Screens off with
            # it (dashboard._paint_bar_buttons, his rule of 2026-09-07)
            "stop": bool(s) and model not in ("off", "unloading"),
            "screens": "Screens on" if awake.get("dark") else "Screens off",
            "dev": "DEV" if paths.DEVELOPER else "",
        }

    # -- the pile

    def _notify_rows(self) -> list[dict]:
        return self._cached("notify", paths.NOTIFY_FILE, self._read_notify)

    def _review_rows(self) -> list[dict]:
        return self._cached("review", paths.REVIEW_FILE, self._read_review)

    def _read_notify(self) -> list[dict]:
        try:
            import notify as notify_mod
            store = notify_mod.Store(paths.NOTIFY_FILE)
            unread = [i for i in store.recent(30) if not i.get("seen")]
        except Exception:                 # noqa: BLE001 — absent or broken
            return []
        if self._gone:
            self._gone &= {i.get("id") for i in unread}
            unread = [i for i in unread if i.get("id") not in self._gone]
        rows = []
        for item in unread:
            ident = item.get("id")
            at = stamp_of(item.get("at", ""), "%Y-%m-%dT%H:%M:%S")
            who = str(item.get("label") or item.get("source") or "")
            body = " ".join(str(item.get("body") or "").split())[:600]
            title = " ".join(str(item.get("title") or "").split())[:200]
            rows.append({
                "id": f"notify:{ident}", "kind": "notify", "at": at,
                "source": str(item.get("source") or ""),
                "tone": {"done": "ok", "input": "q", "error": "bad"}.get(
                    str(item.get("kind") or "info"), "q"),
                "glyph": "bell",
                "title": title or who or "A message",
                "meta": "  ·  ".join(b for b in (who if title else "", ago(at)) if b),
                "text": body or title, "rtl": is_rtl(body or title),
                "buttons": [{"label": "Go there", "tone": "quiet",
                             "act": "notify.open", "arg": ident},
                            {"label": "✕", "tone": "close",
                             "act": "notify.dismiss", "arg": ident}],
            })
        return rows

    def _read_review(self) -> list[dict]:
        try:
            import review as review_mod
            pending = review_mod.Store(paths.REVIEW_FILE).pending()
        except Exception:                 # noqa: BLE001
            return []
        rows = []
        for item in pending:
            sid = str(item.get("id", ""))
            at = stamp_of(item.get("when", ""), "%Y-%m-%d %H:%M:%S")
            changes = [c for c in (item.get("changes") or []) if isinstance(c, dict)]
            heard_text = " ".join(str(item.get("text") or "").split())
            proposed = " ".join(str(item.get("proposed") or "").split()) or heard_text
            row = {"id": f"review:{sid}", "kind": "review", "at": at,
                   "tone": "q", "glyph": "edit", "title": "Second reading",
                   "rtl": is_rtl(heard_text or proposed),
                   "buttons": [{"label": "Yes", "tone": "primary",
                                "act": "review.accepted", "arg": sid},
                               {"label": "No", "tone": "quiet",
                                "act": "review.rejected", "arg": sid}]}
            count = (f"{count_word(len(changes)).lower()} word"
                     f"{'' if len(changes) == 1 else 's'}")
            first = changes[0] if changes else {}
            why = " ".join(str(first.get("why") or "").split())
            if not changes:
                row.update(meta=ago(at), text=summary.first_sentence(proposed))
            elif not str(first.get("after") or "").strip() or str(first.get("kind")) == "drop":
                goes = first_words(" ".join(str(first.get("before") or "").split()), 5)
                where = self._sentence_around(heard_text, goes.split(" …")[0])
                row.update(meta=f"{count} to delete  ·  {ago(at)}",
                           segs=[{"t": "drop", "s": goes}, {"t": "ctx", "s": where}],
                           text=where, note=why)
            else:
                segs, shown = change_segments(heard_text, changes)
                left = len(changes) - shown
                row.update(meta=f"{count} changed  ·  {ago(at)}", segs=segs,
                           text=heard_text,
                           note="  ·  ".join(b for b in (
                               why, f"and {count_word(left).lower()} more change"
                                    f"{'' if left == 1 else 's'} in the sentence"
                               if left else "") if b))
            rows.append(row)
        return rows

    @staticmethod
    def _sentence_around(text: str, word: str) -> str:
        for piece in summary.sentences(text):
            if word and word in piece:
                return piece
        return summary.first_sentence(text)

    def _consent_rows(self) -> list[dict]:
        try:
            import consent_card as cc
            import privacy
            privacy.configure(config_mod.load_layered())
            stale = [k for k in privacy.stale() if k not in self._consent_later]
        except Exception:                 # noqa: BLE001
            return []
        rows, now = [], self._stamp()
        for kind in stale:
            words = cc.TEXTS.get(kind) or {}
            blocks = dict(words.get("blocks") or ())
            what = str(blocks.get(cc.WHAT, "")).rstrip(".")
            whom = str(blocks.get(cc.WHOM, "")).split(" — ")[0].rstrip(".")
            off = str(blocks.get(cc.OFF, "")).rstrip(".")
            changed = str(words.get("changed") or "")
            rows.append({
                "id": f"consent:{kind}", "kind": "consent", "at": now + 3,
                "tone": "warn", "glyph": "globe",
                "title": str(words.get("title", kind)), "meta": "the words changed",
                "text": f"Say yes again? {changed}" if changed
                        else f"Say yes again? What leaves: {what}.",
                "rtl": False, "note": f"To {whom}, on your own key. Off again: {off}.",
                "buttons": [{"label": "Turn on", "tone": "primary",
                             "act": "consent.on", "arg": kind},
                            {"label": "Not now", "tone": "quiet",
                             "act": "consent.later", "arg": kind}],
            })
        return rows

    def _needs_key_rows(self) -> list[dict]:
        words = {"translate": ("Translate", "translate_hotkey"),
                 "punctuate": ("Punctuate", "punctuate_hotkey")}
        needs = (self.status.get("needs_key") or {}) if self.running else {}
        pressed = {f: float(t) for f, t in needs.items()
                   if f in words and float(t) > self._needs_key_later}
        if not pressed:
            return []
        keys = self._keys()
        named = []
        for feature in ("translate", "punctuate"):
            if feature in pressed:
                word, field = words[feature]
                binding = str(keys.get(field) or "")
                named.append(f"{word} ({pretty_key(binding)})" if binding else word)
        when = max(pressed.values())
        return [{
            "id": "keys", "kind": "keys", "at": when, "tone": "warn", "glyph": "key",
            "title": "Your cloud keys", "meta": ago(when),
            "text": f"{' and '.join(named)} {'needs' if len(named) == 1 else 'need'} "
                    "a free cloud key — Gemini or Groq",
            "rtl": False,
            "note": (f"Pressed at {time.strftime('%H:%M', time.localtime(when))}; your text "
                     "was left as it was. A key takes a minute, with no credit card."),
            # Add a key is a way in, not a press: Settings > Privacy in
            # this window (dashboard._needs_key_go), where YOUR CLOUD KEYS is
            "buttons": [{"label": "Add a key", "tone": "primary", "act": "",
                         "go": "settings/privacy"},
                        {"label": "Not now", "tone": "quiet", "act": "keys.later", "arg": when}],
        }]

    def _update_release(self):
        """(updates.status(), the release it offers) — or (None, None)
        when there is nothing to offer: no newer version, the Store
        channel, the check off, offline (dashboard._waiting_update)."""
        try:
            import updates
            s = updates.status()
        except Exception:                 # noqa: BLE001
            return None, None
        rel = s.get("available")
        if rel is None or s.get("mode") in ("store", "off", "offline"):
            return None, None
        return s, rel

    @staticmethod
    def _too_old_for(release) -> bool:
        """11.10: this copy's files are too old for the release
        (dashboard._too_old_for)."""
        try:
            import migrations
            return bool(migrations.too_old_for(release.min_config_version))
        except Exception:                 # noqa: BLE001
            return False

    def _update_rows(self) -> list[dict]:
        """dashboard._waiting_update, with its buttons: Download and
        install (never in the checkout, which pulls), or the winget
        one-liner on that channel, or — for the one release this copy
        cannot go straight to — its notes."""
        s, rel = self._update_release()
        if rel is None:
            return []
        row = {"id": "update", "kind": "update", "at": self._stamp(), "tone": "q",
               "glyph": "up", "title": "A newer version", "meta": "", "rtl": False}
        if self._too_old_for(rel):
            row.update(tone="warn",
                       text=f"DeskIT {rel.version} is available, but this copy's settings are "
                            f"too old to go straight to it — install the intermediate version "
                            f"the release notes name first.",
                       note="Your data folder is untouched either way.",
                       buttons=[{"label": "Release notes", "tone": "primary",
                                 "act": "update.notes"}])
            return [row]
        when = f", {rel.published[:10]}" if rel.published else ""
        buttons: list[dict] = []
        if self._update_line:
            pass                          # under way: the line says how far
        elif s.get("winget_command"):
            buttons.append({"label": "Copy the winget command", "tone": "primary",
                            "act": "update.winget"})
        elif not paths.DEVELOPER:
            buttons.append({"label": "Download and install", "tone": "primary",
                            "act": "update.install"})
        row.update(text=f"DeskIT {rel.version} is available ({rel.size / 1_048_576:.0f} MB"
                        f"{when}) — you have {s.get('running', '')}.",
                   note=self._update_line or self._update_failed
                        or "Downloaded from GitHub and checked against its SHA-256 before the "
                           "installer runs; your data folder is untouched.",
                   buttons=buttons)
        return [row]

    def _hardware_rows(self) -> list[dict]:
        """dashboard._waiting_hardware, with its buttons: each step runs
        in a process of its own (launch.run_step — `main.py
        --download-model` or `--install-pack gpu`), as the Tk desk's do."""
        rows, now = [], self._stamp()
        dl = self.status.get("downloads") if self.running else None
        downloading = False
        if dl and dl.get("state") in ("running", "waiting"):
            parts = dl.get("parts") or {}
            downloading = "model" in parts
            pct = int(round(float(dl.get("fraction") or 0) * 100))
            rows.append({
                "id": "downloads", "kind": "hardware", "at": now, "tone": "q", "glyph": "chip",
                "title": "This computer", "meta": "",
                "text": (f"Downloading app parts — {pct}%" if not dl.get("offline")
                         else "Downloading app parts — waiting for the connection"),
                "rtl": False,
                "note": ("Once, in the background. Dictation starts the moment the "
                         "Hebrew model lands." if parts.get("model") not in (None, "done")
                         else "Once, in the background — nothing to press."),
                "buttons": []})
        try:
            import hardware as hardware_mod
            changed = str(hardware_mod.recorded().get("tier_changed") or "")
        except Exception:                 # noqa: BLE001
            changed = ""
        if not paths.PORTABLE:
            try:
                import models as models_mod
                model_name = config_mod.load_layered().local.model
                model = models_mod.state(model_name)
            except Exception:             # noqa: BLE001
                models_mod, model_name, model = None, "", "unknown"
            try:
                import packs as packs_mod
                pack = packs_mod.standing("gpu")
            except Exception:             # noqa: BLE001
                pack = "unknown"
            if model in ("absent", "incomplete", "stale") and not downloading:
                size = ""
                try:
                    e = models_mod.entry(model_name)
                    size = f" ({models_mod.human(e.bytes)})" if e else ""
                except Exception:         # noqa: BLE001
                    pass
                said = {"absent": f"The Hebrew model is not on this PC yet{size} — "
                                  "dictation waits for it.",
                        "incomplete": "The Hebrew model's download did not finish — "
                                      "it continues from where it stopped.",
                        "stale": "The Hebrew model on this PC is from an older "
                                 "release — download the new one."}[model]
                rows.append({
                    "id": "model", "kind": "hardware", "at": now, "tone": "warn",
                    "glyph": "chip", "title": "This computer", "meta": "", "text": said,
                    "rtl": False,
                    "note": "Downloaded once, from huggingface.co, into the app's folder.",
                    "buttons": [{"label": "Download" if model == "absent" else "Continue",
                                 "tone": "primary", "act": "hardware.model"}]})
            if pack.startswith("failed:"):
                rows.append({
                    "id": "pack", "kind": "hardware", "at": now, "tone": "bad",
                    "glyph": "chip", "title": "This computer", "meta": "",
                    "text": f"Your NVIDIA card was found but GPU speed could not start "
                            f"({pack[7:]}).",
                    "rtl": False, "note": "Dictation works on the processor meanwhile.",
                    "buttons": [{"label": "Retry", "tone": "quiet", "act": "hardware.retry"},
                                {"label": "Reinstall", "tone": "quiet",
                                 "act": "hardware.reinstall"},
                                {"label": "Remove the pack", "tone": "quiet",
                                 "act": "hardware.remove"}]})
        if changed:
            rows.append({
                "id": "tier", "kind": "hardware", "at": now, "tone": "q", "glyph": "chip",
                "title": "This computer", "meta": "",
                "text": f"Your hardware changed: DeskIT now runs {changed}.",
                "rtl": False,
                "note": "The speed settings for this tier were applied; yours were left alone.",
                "buttons": [{"label": "OK", "tone": "quiet", "act": "hardware.seen"}]})
        return rows

    def _lock_info(self) -> dict:
        """The account's lock as the app reports it, or {} when nothing
        is running or nobody is signed in (dashboard._waiting_lock)."""
        if not self.running:
            return {}
        account = self.status.get("account") or {}
        if not account.get("signed_in"):
            return {}
        return dict(account.get("lock") or {})

    def _lock_rows(self) -> list[dict]:
        """dashboard._waiting_lock and _lock_changed_rows, with their
        answers on the rows (the owner, 2026-09-21: "not outside DeskIT —
        inside, on Home"): another PC asking to join, with its code and
        Approve / Not now; this PC waiting for its other PC, with the
        code — and the recovery key typed into the row; a fresh recovery
        key, shown once, until Done; the changed lock's It wasn't me / It
        was me; and while the account has none, Make a recovery key."""
        lock = self._lock_info()
        if not lock:
            self._lock_typing = self._lock_asking = False
            return []
        now = self._stamp()
        rows: list[dict] = []

        def row(ident: str, at: float, tone: str, text: str, note: str,
                buttons: list[dict], title: str = "Your account", **extra) -> dict:
            return {"id": ident, "kind": "lock", "at": at, "tone": tone, "glyph": "key",
                    "title": title, "meta": "", "text": text, "rtl": False, "note": note,
                    "buttons": buttons, **extra}

        if self._lock_fresh:
            rows.append(row(
                "lock:fresh", now + 2, "warn", "keep it somewhere safe, it is shown once",
                "With it, a PC with no other PC of yours at hand can open your account. "
                "Making a new one replaces it.",
                [{"label": "Copy", "tone": "primary", "act": "lock.copy"},
                 {"label": "Done", "tone": "quiet", "act": "lock.done"}],
                title="Your recovery key", code=self._lock_fresh))
        rows += self._lock_changed_rows(lock, now, row)
        for ask in lock.get("pending") or []:
            ident = str(ask.get("id") or "")
            name = str(ask.get("name") or "Another PC")
            if ask.get("twins"):
                # two open requests from one PC: one of them is somebody
                # else's copy (the audit's A74) — nothing to approve
                rows.append(row(
                    f"lock:ask:{ident}", now + 1, "bad",
                    f"Two requests say they are {name} — neither can be approved",
                    f"One of them is not your PC. On {name}, sign out and sign in again to "
                    "ask afresh. Nobody of yours asking right now? Settings > Account > "
                    "Sign out of every PC — it ends every session of your account, "
                    "anyone else's too.",
                    [{"label": "Not now", "tone": "quiet", "act": "lock.decline",
                      "arg": ident}]))
                continue
            rows.append(row(
                f"lock:ask:{ident}", now + 1, "warn",
                f"{name} asks to join your account — its screen must show "
                f"{ask.get('code') or '?'}",
                "Approve only if the code is exactly that. It then gets your account's key: "
                "your cloud keys and what you said open there too, and the key crosses "
                "sealed — the server cannot read it.",
                [{"label": "Approve", "tone": "primary", "act": "lock.approve", "arg": ident},
                 {"label": "Not now", "tone": "quiet", "act": "lock.decline", "arg": ident}]))
        if lock.get("state") == "waiting":
            note = ("Open the desk on your other PC and press Approve. Until then this PC has "
                    "your words and settings; what you said and your cloud keys stay locked. "
                    "No other PC at hand? Type the recovery key DeskIT made for you.")
            if lock.get("error"):
                note = f"{lock['error']}  ·  {note}"
            if self._lock_typing:
                rows.append(row(
                    "lock:waiting", now, "warn",
                    f"Waiting for your other PC to approve this one — Home there must show "
                    f"{lock.get('code') or '…'}",
                    "Your recovery key — 24 letters and digits in six groups:",
                    [{"label": "Open", "tone": "primary", "act": "lock.recover"},
                     {"label": "Cancel", "tone": "quiet", "act": "lock.cancel"}],
                    field="recovery"))
            else:
                rows.append(row(
                    "lock:waiting", now, "warn",
                    f"Waiting for your other PC to approve this one — Home there must show "
                    f"{lock.get('code') or '…'}", note,
                    [{"label": "Type the recovery key", "tone": "quiet", "act": "lock.type"}]))
        else:
            self._lock_typing = False
            if lock.get("state") == "have" and lock.get("recovery") is False \
                    and not self._lock_fresh:
                rows.append(row(
                    "lock:recovery", 0.0, "q",
                    "Make a recovery key — so a new PC of yours can open your account when "
                    "this one is gone",
                    "DeskIT makes it (24 characters) and shows it once; you keep it. What you "
                    "said and your cloud keys are locked with a key only your PCs hold — "
                    "without another PC or the recovery key, a new PC cannot open them.",
                    [{"label": "Make a recovery key", "tone": "primary",
                      "act": "lock.recovery_new"}]))
        return rows

    def _lock_changed_rows(self, lock: dict, now: float, row) -> list[dict]:
        """dashboard._lock_changed_rows: the account's lock changed
        somewhere else. [It was me] asks to join the new lock; [It wasn't
        me] keeps everything and then offers the way out — Put my lock
        back, and Sign out of every PC, asked here in the row (the Tk
        desk asks it on Settings > Account) and never pressed for him."""
        if lock.get("state") != "changed":
            self._lock_asking = False
            return []
        ch = lock.get("changed") or {}
        if not ch.get("refused"):
            self._lock_asking = False
            return [row(
                "lock:changed", now + 3, "bad",
                "The lock of your account changed — not on this PC. Was it you?",
                "Until you answer, what you said and your cloud keys stop syncing, both ways; "
                "this PC keeps its key. It was you: this PC asks to join the new lock — "
                "approve it from your other PC or type the recovery key. It wasn't: nothing "
                "here changes.",
                [{"label": "It wasn't me", "tone": "primary", "act": "lock.answer", "arg": "no"},
                 {"label": "It was me", "tone": "quiet", "act": "lock.answer", "arg": "yes"}])]
        if self._lock_asking:
            return [row(
                "lock:changed", now + 3, "bad",
                "Sign out of every PC? Each one, this one too, stops dictating until you "
                "sign in on it again.",
                "It ends every session of your account, anyone else's too. Sign in again "
                "here, then put your lock back.",
                [{"label": "Sign out of every PC", "tone": "primary",
                  "act": "lock.signout_all"},
                 {"label": "Stay signed in", "tone": "quiet", "act": "lock.signout_keep"}])]
        buttons = [{"label": "Sign out of every PC", "tone": "quiet", "act": "lock.signout_ask"}]
        if ch.get("mine"):                # a key here to put back
            buttons.insert(0, {"label": "Put my lock back", "tone": "primary",
                               "act": "lock.restore"})
        return [row(
            "lock:changed", now + 3, "bad",
            "Not you — this PC kept its key. What you said and your keys stay paused",
            "Sign out of every PC ends every session of your account, anyone else's too. "
            "Sign in again here, then put your lock back — syncing starts again under this "
            "PC's key.", buttons)]

    def _stamp(self) -> float:
        """The one "now" of this read of the pile. Rows that are about
        the present (a consent, the lock, the update, this computer) are
        stamped with it, so two of them tie the same way on every poll —
        each stamping its own time.time() swapped the update row and the
        model row between reads whenever the clock did or did not move
        between them (probed 2026-10-24)."""
        return self._now or time.time()

    _now = 0.0

    def pile(self) -> list[dict]:
        self._now = time.time()
        items: list[dict] = []
        for part in (self._consent_rows, self._lock_rows, self._update_rows,
                     self._needs_key_rows, self._hardware_rows, self._notify_rows,
                     self._review_rows):
            try:
                # copies: the lit button is decided below, per pile, and a
                # kept row must not carry one pile's decision into the next
                items += [{**row, "buttons": [dict(b) for b in row.get("buttons", ())]}
                          for row in part()]
            except Exception as e:        # noqa: BLE001 — one source, not the page
                log.warning("web desk: %s failed: %s", part.__name__, type(e).__name__)
        if any(r["kind"] == "lock" for r in items):
            # the app's own knock for the same question is the lock row's
            items = [r for r in items
                     if not (r["kind"] == "notify" and r.get("source") == "account")]
        items.sort(key=lambda r: r.get("at", 0.0), reverse=True)
        # ONE LIT BUTTON ACROSS THE PILE: the newest keeps it, every later
        # primary is drawn quiet and still answers the same way
        lit = False
        for row in items:
            for b in row.get("buttons", ()):
                if b["tone"] == "primary":
                    if lit:
                        b["tone"] = "quiet"
                    lit = True
        return items

    # -- the rest of Home

    def _last_capture(self):
        try:
            folder = Path(getattr(config_mod.load_layered().capture, "folder", "") or "")
        except Exception:                 # noqa: BLE001
            return None
        if not folder or not folder.is_dir():
            return None
        try:
            seen = (str(folder), folder.stat().st_mtime_ns, time.strftime("%Y-%m-%d"))
        except OSError:
            return None
        if self._capture_seen is not None and self._capture_seen[0] == seen:
            return self._capture_seen[1]
        try:
            shots = [f for f in folder.iterdir()
                     if f.is_file() and f.suffix.lower() in CAPTURE_SUFFIXES]
        except OSError:
            return None
        found = None
        if shots:
            stamps = {f: f.stat().st_mtime for f in shots}
            newest = max(shots, key=stamps.__getitem__)
            midnight = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
            found = (newest, stamps[newest], sum(1 for f in shots if stamps[f] >= midnight))
        self._capture_seen = (seen, found)
        return found

    def _said_today(self) -> int:
        today = time.strftime("%Y-%m-%d")
        return sum(1 for e in self._log
                   if e.kind == "dictation" and e.when.strftime("%Y-%m-%d") == today)

    def _rest(self) -> list[dict]:
        lines = []
        said = next((e for e in self._log if e.kind == "dictation"), None)
        if said is not None:
            lines.append({"label": "Said", "when": said.when.strftime("%H:%M"),
                          "text": said.text or "", "rtl": is_rtl(said.text),
                          "meta": f"{self._said_today()} today", "go": "Said"})
        took = self._last_capture()
        if took is not None:
            path, when, day = took
            lines.append({"label": "Took", "when": time.strftime("%H:%M", time.localtime(when)),
                          "text": f"{path.name}  ·  in {path.parent.name}\\", "rtl": False,
                          "meta": f"{day} today", "act": "open.capture"})
        looked = next((e for e in self._log if e.kind == "lookup"), None)
        if looked is not None:
            text = looked.text or looked.source or ""
            lines.append({"label": "Looked up", "when": looked.when.strftime("%H:%M"),
                          "text": text, "rtl": is_rtl(text), "meta": "—", "go": "Said"})
        return lines

    def _doors(self, items: list[dict]) -> list[dict]:
        import settings as settings_mod
        learned = words_learned()
        proposals = sum(1 for i in items if i["kind"] == "review")
        tail = ("the words it has learned" if learned is None
                else f"the {learned} words learned so far")
        return [
            {"place": "Corrections", "glyph": "edit", "n": proposals, "w": "corrections",
             "note": (f"waiting for a yes or no, and {tail}" if proposals
                      else f"nothing to look at, and {tail}")},
            {"place": "Said", "glyph": "history", "n": self._said_today(), "w": "said today",
             "note": "the last hundred of them, with the search over them"},
            {"place": "Keys", "glyph": "keyboard", "n": len(config_mod.HOTKEY_FIELDS),
             "w": "keys", "note": "every one of them lit on a drawn keyboard"},
            {"place": "Settings", "glyph": "settings", "n": len(settings_mod.TABS),
             "w": "settings tabs", "note": "everything you can change, in plain words"},
        ]

    def _strip(self) -> dict:
        awake = (self.status.get("awake") or {}) if self.running else {}
        if not self.running:
            sentence = "Nothing is running, so nothing is holding the machine awake."
        elif awake.get("dark"):
            since = awake.get("since") or awake.get("hold_since")
            sentence = (f"The screens are off since "
                        f"{time.strftime('%H:%M', time.localtime(since))}. The machine "
                        "stays awake." if since else
                        "The screens are off. The machine stays awake.")
        elif awake.get("held"):
            sentence = "The machine stays awake while this runs."
        else:
            sentence = "The machine sleeps on its own timer."
        model = self.status.get("model") or "on"
        if self.running and model != "on":
            sentence = ("The model is off — every key that needs no model works; "
                        "Start loads it again." if model == "off" else
                        "The model is loading — about 25 seconds.")
        facts = [f"DeskIT {paths.DEV_TAG} {version.VERSION}".replace("  ", " ")]
        if version.BRANCH:
            facts.append(f"running {version.BRANCH}")
        learned = words_learned()
        if learned is not None:
            facts.append(f"{learned} words learned")
        return {"awake": sentence, "phone": self.phone_live, "facts": facts}

    def _head(self, items: list[dict]) -> tuple[str, str]:
        count = len(items)
        head = ("Nothing is waiting." if not count else
                f"{count_word(count)} thing{'' if count == 1 else 's'} "
                f"want{'s' if count == 1 else ''} an answer.")
        extra = count - PILE_CAP
        sub = ("Nothing else on the desk needs you right now." if not count else
               "It is here, and nothing else needs you right now." if count == 1 else
               "They are all here, and nothing else needs you right now."
               if count <= PILE_CAP else
               f"The newest {count_word(PILE_CAP).lower()} are here, and "
               f"{count_word(extra).lower()} more {'is' if extra == 1 else 'are'} waiting.")
        return head, sub

    def _held(self) -> str:
        info = (self.status.get("notify") or {}) if self.running else {}
        try:
            held = int(info.get("held") or 0)
        except (TypeError, ValueError):
            held = 0
        return (f"{held} finish{'es' if held > 1 else ''} held until the session that "
                "sent them goes quiet. They will arrive here, not on your screen."
                if held else "")

    # -- the report sheet (dashboard._report, _file_report, _report_preview)

    @staticmethod
    def _problems_cfg():
        try:
            cfg = config_mod.load_layered()
        except Exception:                 # noqa: BLE001
            return None, None
        return cfg, getattr(cfg, "problems", None)

    @staticmethod
    def _last_dictation() -> tuple[dict | None, float]:
        """The recording a report is probably about — the newest wav in
        recent\\ (dashboard._last_dictation: the status pipe carries only
        when-and-how-long, so the evidence comes off the disk) — and when
        it was made."""
        try:
            wavs = [(p.stat().st_mtime, p) for p in paths.RECENT_DIR.glob("*.wav")]
        except OSError:
            return None, 0.0
        if not wavs:
            return None, 0.0
        when, newest = max(wavs)
        return {"wav": str(newest)}, when

    def _report_open(self) -> str:
        """Report a problem: THE SCREEN FIRST, before there is a sheet to
        photograph (dashboard._report, main._problem_ask) — the press
        lands here before the page draws the sheet, so the picture is
        the desk and whatever is around it as they were. Grabbed now,
        encoded to JPEG on a thread of its own (350 ms of LANCZOS at
        4480x1440, which the sheet need not wait for); kept in this
        process's memory and written nowhere unless the report is sent."""
        cfg, pcfg = self._problems_cfg()
        if pcfg is not None and not getattr(pcfg, "enabled", True):
            return "[problems] enabled is false — nothing is being reported or written"
        image = None
        if getattr(pcfg, "shot", True):
            try:
                from PIL import ImageGrab
                image = ImageGrab.grab(all_screens=True).convert("RGB")
            except Exception as e:        # noqa: BLE001 — a report with no picture is a report
                log.debug("could not photograph the screen for a report: %s", type(e).__name__)
        last, made = self._last_dictation()
        report = {"stage": "write", "image": image, "jpeg": None, "last": last,
                  "made": made, "item": "", "since": 0.0, "done": None, "preview": None,
                  "max_side": int(getattr(pcfg, "max_side_px", 0) or 1344)}
        if image is not None:
            def encode() -> None:
                try:
                    import visual_qa as visual_qa_mod
                    report["jpeg"] = visual_qa_mod.encode_jpeg(image, report["max_side"])
                except Exception as e:    # noqa: BLE001
                    log.debug("could not encode the report's picture: %s", type(e).__name__)
            report["encoder"] = threading.Thread(target=encode, daemon=True,
                                                 name="report-shot")
            report["encoder"].start()
        self._report = report
        return ""

    def _report_jpeg(self) -> bytes | None:
        report = self._report or {}
        encoder = report.get("encoder")
        if encoder is not None:
            encoder.join(5)
        return report.get("jpeg")

    def _report_when(self) -> str:
        made = (self._report or {}).get("made") or 0.0
        if not made:
            return ""
        same_day = time.strftime("%Y-%m-%d", time.localtime(made)) == time.strftime("%Y-%m-%d")
        return time.strftime("%H:%M" if same_day else "%d %b, %H:%M",
                             time.localtime(made)).lstrip("0")

    def _report_attach(self, attach: bool) -> dict:
        """The single switch as problems.ATTACH's four toggles: the
        recording, its words and the picture go together or not at all;
        the settings snapshot (model names and switches, never a key —
        problems.env's whitelist) always, as attach_defaults has it."""
        report = self._report or {}
        return {"shot": bool(attach and report.get("image") is not None),
                "recording": bool(attach and report.get("last")),
                "transcript": bool(attach and report.get("last")),
                "settings": True}

    def _report_view(self) -> dict | None:
        """What the page draws of the sheet — words and flags, never the
        picture's bytes (its thumbnail rides only with a preview)."""
        report = self._report
        if report is None:
            return None
        if report["stage"] == "sending":
            self._report_settle()
        has_shot = report.get("image") is not None
        has_said = bool(report.get("last"))
        when = self._report_when()
        if has_said and has_shot:
            label = "Attach my last dictation and a picture of the screen"
            on = (f"Sends what you said at {when} (words and sound) and your screen from "
                  "a moment ago.")
        elif has_said:
            label, on = "Attach my last dictation", \
                f"Sends what you said at {when} (words and sound)."
        elif has_shot:
            label, on = "Attach a picture of the screen", "Sends your screen from a moment ago."
        else:
            label = on = ""
        import problems
        view = {"stage": report["stage"], "attach": label, "on": on,
                "off": "Sends only what you typed, with this copy's version and settings.",
                "limit": int(problems.TEXT_MAX), "done": report.get("done"),
                "preview": report.get("preview")}
        if report["stage"] == "consent":
            import consent_card as cc
            card = cc.card_for("report_upload")
            blocks = dict(cc.TEXTS["report_upload"].get("blocks") or ())
            view["consent"] = {
                "title": card.get("title") or cc.TEXTS["report_upload"]["title"],
                "lines": [{"k": k, "v": str(blocks[k])}
                          for k in (cc.WHAT, cc.WHOM, cc.ACCOUNT, cc.OFF) if blocks.get(k)]}
        return view

    def _report_item(self, text: str, attach: bool) -> dict:
        """The report as it would be stored, for a preview made before
        anything is filed (problems.sizes_before_filing's own idea)."""
        import problems
        cfg, _pcfg = self._problems_cfg()
        report = self._report or {}
        last = report.get("last") if attach else None
        item = {"kind": "wrong" if attach else "other", "where": REPORT_WHERE,
                "text": str(text), "shot": "", "dictation": {}, "env": {}}
        try:
            item["dictation"] = problems.dictation(last, paths.DATA_DIR)
            item["env"] = problems.env(cfg)
        except Exception:                 # noqa: BLE001
            pass
        return item

    def _report_preview(self, text: str, attach: bool) -> dict:
        """dashboard._report_preview, before filing: each piece that
        would leave with its size, and the exact row (problems.payload,
        through the redactor), so what is shown is what the outbox would
        carry. Read-only: the sheet's own text and switch are what
        change it."""
        import problems
        import problem_card
        toggles = self._report_attach(attach)
        row, files = problems.payload(self._report_item(text, attach), toggles,
                                      app_dir=paths.DATA_DIR)
        jpeg = self._report_jpeg() if toggles["shot"] else None
        pieces = []
        if jpeg:
            files = [{"name": "shot.jpg", "bytes": len(jpeg)}] + files
            row["attachments"] = ["shot.jpg"] + list(row.get("attachments") or [])
        text_row = problems.preview_text(row)
        pieces.append({"what": "What you typed, with this copy's version and settings",
                       "size": problem_card.size_word(len(text_row.encode("utf-8")))})
        for f in files:
            pieces.append({"what": REPORT_PIECES.get(str(f.get("name")), str(f.get("name"))),
                           "size": problem_card.size_word(int(f.get("bytes") or 0))})
        thumb = ""
        image = (self._report or {}).get("image")
        if toggles["shot"] and image is not None:
            try:
                import base64
                import io
                small = image.copy()
                small.thumbnail((REPORT_THUMB_PX, REPORT_THUMB_PX))
                buf = io.BytesIO()
                small.save(buf, "PNG")
                thumb = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            except Exception:             # noqa: BLE001 — a thumbnail is a bonus
                thumb = ""
        return {"pieces": pieces, "row": text_row, "thumb": thumb}

    def _report_send(self, arg) -> str:
        """[Send]: the report is FILED here first, always, exactly as the
        Tk desk files it (problems.record — the context, the pinned wav
        and picture, the settings), and then the copy that travels: into
        the outbox at once when the report_upload gate is open, or — when
        it is shut — the sheet asks, with the gate's own card words and
        the pieces that would leave (never a card beside the dot: his
        rule, no floating cards for questions)."""
        import problems
        report = self._report
        if report is None or report["stage"] != "write":
            return "the report box is not open"
        if not isinstance(arg, dict) or set(arg) - {"text", "attach"}:
            return "that report could not be read"
        text, attach = arg.get("text"), arg.get("attach")
        if not isinstance(text, str) or not isinstance(attach, bool) \
                or len(text) > 4 * problems.TEXT_MAX:
            return "that report could not be read"
        toggles = self._report_attach(attach)
        cfg, _pcfg = self._problems_cfg()
        jpeg = self._report_jpeg() if toggles["shot"] else None
        allowed = self._upload_allowed()
        preview = None
        if not allowed:
            # the card's own words say "only what the report's preview
            # showed": the pieces go on the question, made while the
            # picture is still in hand
            try:
                preview = self._report_preview(text, attach)
            except Exception as e:        # noqa: BLE001
                log.warning("web desk: report preview failed: %s", type(e).__name__)
        try:
            item = problems.record(paths.DATA_DIR,
                                   {"where": REPORT_WHERE, "kind": "wrong" if attach else "other",
                                    "text": text},
                                   cfg=cfg, last=report.get("last") if attach else None,
                                   jpeg=jpeg)
        except ValueError:
            return "nothing was typed — say what is wrong and send it again"
        except Exception as e:            # noqa: BLE001
            log.warning("web desk: could not file a report: %s", type(e).__name__)
            return f"could not file that ({type(e).__name__})"
        # filed: the picture's bytes are on disk now, or were not asked for
        report.update(image=None, jpeg=None, preview=preview, item=str(item.get("id", "")),
                      toggles=toggles)
        if allowed:
            return self._report_queue()
        store = problems.Store(paths.DATA_DIR / problems.STORE_NAME)
        problems.mark_preview(store, report["item"], toggles)
        report["stage"] = "consent"
        return ""

    @staticmethod
    def _upload_allowed() -> bool:
        try:
            import privacy
            privacy.configure(config_mod.load_layered())
            return bool(privacy.allowed("report_upload"))
        except Exception:                 # noqa: BLE001
            return False

    def _report_queue(self) -> str:
        """The copy that travels into problems\\outbox\\ (problems.queue)
        and the app's worker told to carry it up now (account nudge)."""
        import problems
        report = self._report
        store = problems.Store(paths.DATA_DIR / problems.STORE_NAME)
        item = store.get(report["item"])
        if not item or problems.queue(store, item, report.get("toggles") or {},
                                      app_dir=paths.DATA_DIR) is None:
            report.update(stage="done", done={
                "tone": "bad", "text": "Could not queue the report — it stays on this PC."})
            return ""
        report.update(stage="sending", since=time.monotonic(), preview=None,
                      done={"tone": "q", "text": "Sending…"})
        if self.running:
            self._send("account", timeout_ms=1500, do="nudge")
        return ""

    def _report_settle(self) -> None:
        """While the copy is on its way: read the outbox's verdict back
        (problems.sync_outbox — the app's worker removes a payload it
        sent, writes .failed beside one the server refused) and say it
        the moment it is known, or that it waits for the connection."""
        import problems
        report = self._report
        try:
            store = problems.Store(paths.DATA_DIR / problems.STORE_NAME)
            problems.sync_outbox(store, app_dir=paths.DATA_DIR)
            state = str((store.get(report["item"]) or {}).get("sent") or "")
        except Exception:                 # noqa: BLE001
            state = ""
        if state == problems.SENT:
            done = {"tone": "ok", "text": "Thanks — it reached the developer."}
        elif state == problems.FAILED:
            done = {"tone": "bad", "text": "It could not be sent — it stays on this PC."}
        elif time.monotonic() - report["since"] > REPORT_SEND_WAIT_S or not self.running:
            done = {"tone": "ok", "text": "Thanks — it goes to the developer as soon as "
                                          "DeskIT is online."}
        else:
            return
        report.update(stage="done", done=done)

    def _report_do(self, do: str, arg) -> str:
        report = self._report
        if do == "report.open":
            return self._report_open()
        if do in ("report.cancel", "report.close"):
            # Cancel drops the picture unseen; Close is after the answer
            self._report = None
            return ""
        if report is None:
            return "the report box is not open"
        if do == "report.preview":
            if report["stage"] not in ("write", "consent") or not isinstance(arg, dict) \
                    or set(arg) - {"text", "attach"} \
                    or not isinstance(arg.get("text", ""), str) \
                    or len(arg.get("text", "")) > 2400 \
                    or not isinstance(arg.get("attach", False), bool):
                return "that preview could not be made"
            if report["stage"] == "consent":
                return ""                 # the consent step shows its own pieces
            try:
                report["preview"] = self._report_preview(arg.get("text", ""),
                                                         arg.get("attach", False))
            except Exception as e:        # noqa: BLE001
                log.warning("web desk: report preview failed: %s", type(e).__name__)
                return f"could not build the preview ({type(e).__name__})"
            return ""
        if do == "report.send":
            return self._report_send(arg)
        if do in ("report.consent", "report.keep"):
            if report["stage"] != "consent":
                return "nothing is waiting for that answer"
            import problems
            if do == "report.keep":
                store = problems.Store(paths.DATA_DIR / problems.STORE_NAME)
                problems.keep_local(store, report["item"])
                report.update(stage="done", preview=None, done={
                    "tone": "ok", "text": "Kept on this PC — nothing was sent."})
                return ""
            # [Turn on] under the card's own words: the gate this sheet
            # asked about and no other, at the words it showed
            try:
                import consent_card as cc
                import privacy
                privacy.grant("report_upload", cc.card_for("report_upload")["text_version"])
            except Exception as e:        # noqa: BLE001
                log.warning("could not record the consent for report_upload: %s",
                            type(e).__name__)
                return "could not record that"
            return self._report_queue()
        return f"{do!r} is not a desk action"

    # -- the account lock's answers (dashboard._lock_do and its neighbours)

    @staticmethod
    def _offered(rows) -> set:
        """The acts the buttons of these rows carry right now."""
        return {b.get("act") for r in rows() for b in r.get("buttons", ())}

    def _lock_do(self, do: str, arg) -> str:
        lock = self._lock_info()
        if not self.running or not lock:
            return "start dictation first — the lock lives in the running app"
        # the page names the button; it answers only while its row offers
        # it (Put my lock back, Sign out of every PC, a recovery key...)
        if do not in ("lock.approve", "lock.decline") and do not in self._offered(self._lock_rows):
            return "that is not on Home right now"
        if do == "lock.copy":
            return ("copied — paste it somewhere safe, then press Done"
                    if copy_text(self._lock_fresh, secret=True)
                    else "could not reach the clipboard — write it down")
        if do == "lock.done":
            self._lock_fresh = ""
            return ""
        if do in ("lock.type", "lock.cancel"):
            self._lock_typing = do == "lock.type"
            return ""
        if do in ("lock.signout_ask", "lock.signout_keep"):
            self._lock_asking = do == "lock.signout_ask"
            return ""
        if do in ("lock.approve", "lock.decline"):
            # the page names the request: only one the app reported, by id
            asks = {str(a.get("id")): a for a in (lock.get("pending") or []) if a.get("id")}
            ident = arg if isinstance(arg, str) else ""
            if ident not in asks or (do == "lock.approve" and asks[ident].get("twins")):
                return "that request is not here any more"
            verb = do.split(".", 1)[1]
            return self._said(self._ask("account", do=verb, kind=ident),
                              "approving" if verb == "approve" else "declined")
        if do == "lock.recover":
            # the typed key goes to the app over the pipe and nowhere
            # else: never a note, never a log line, never kept here
            typed = " ".join(arg.split()) if isinstance(arg, str) else ""
            if not typed:
                return "type the recovery key first"
            if lock.get("state") != "waiting" or not _RECOVERY_SHAPE.fullmatch(typed):
                del typed
                return "that is not a recovery key — 24 letters and digits in six groups"
            self._lock_typing = False
            reply = self._ask("account", do="recover", kind=typed)
            del typed
            return self._said(reply, "opened")
        if do == "lock.answer":
            if arg not in ("yes", "no") or lock.get("state") != "changed":
                return "that question is not waiting"
            return self._said(self._ask("account", do="lock_answer", kind=arg),
                              "asked" if arg == "yes" else "kept")
        if do == "lock.restore":
            return self._said(self._ask("account", do="lock_restore"), "put back")
        if do == "lock.signout_all":
            if not self._lock_asking:
                return "that question is not waiting"
            self._lock_asking = False
            return self._said(self._ask("account", do="signout_all"),
                              "signing out of every PC")
        if do == "lock.recovery_new":
            # the one answer that carries a secret: shown once, kept in
            # this window's memory until Done
            reply = self._ask("account", do="recovery_new")
            if not reply or not reply.get("ok") or not reply.get("recovery"):
                return self._said(reply, "that did not work")
            self._lock_fresh = str(reply["recovery"])
            return "your recovery key is shown once — copy it somewhere safe"
        return f"{do!r} is not a desk action"

    # -- the sign-in landing (dashboard._landing, _screen_landing)

    def _signed_out(self) -> bool:
        """With the app silent: is there no account on this PC? sb.py's
        own word (dashboard._locked_now) — the session blob is this
        user's — asked at most every three seconds."""
        at, said = self._signed_out_seen
        if time.monotonic() - at < 3.0:
            return said
        try:
            import sb
            said = bool(sb.REQUIRED and sb.configured() and not sb.signed_in())
        except Exception:                 # noqa: BLE001
            said = False
        self._signed_out_seen = (time.monotonic(), said)
        return said

    def _landing(self) -> dict:
        """The line under Sign in with Google: the app's account status
        (the browser wait, the last error) when it runs — the window's
        own sign-in's when it does not (dashboard._paint_landing)."""
        line, tone = self._landing_line
        info = self.status.get("account") if self.status else None
        if info is not None:
            if info.get("busy") == "waiting for the browser":
                line, tone = LANDING_WAITING, "q"
            elif info.get("last_error"):
                said = str(info["last_error"])
                try:
                    import sb
                    gone = (sb.GONE_ELSEWHERE, sb.GONE_WORDS)
                except Exception:         # noqa: BLE001
                    gone = ()
                line = said[:200] if said in gone else f"Not signed in: {said}"[:200]
                tone = "warn"
        return {"title": f"DeskIT {paths.DEV_TAG}".strip(), "sentence": LANDING_SENTENCE,
                "stored": LANDING_STORED, "line": line, "tone": tone}

    def _landing_sign_in(self) -> str:
        """[Sign in with Google] (dashboard._landing_sign_in): through
        the running app when there is one — it holds the session and
        unlocks itself; in this window's process when there is none, the
        wizard's own way (the consent rows, then the browser and the
        loopback listener). Either way the next poll sees the session."""
        locked = bool(self.status.get("locked")) if self.status else self._signed_out()
        if not locked:
            return "this PC is signed in already"
        if self.status:
            self._busy_until = time.monotonic() + 1
            return self._said(self._ask("account", do="google"), "opening the browser")
        if self._signing:
            return ""
        self._signing = True
        self._landing_line = (LANDING_WAITING, "q")

        def work() -> None:
            try:
                import privacy
                import sb
                privacy.sign_in_grants()      # the account, and the sync it promises
                who = sb.sign_in_google()
                with self._lock:
                    self._landing_line = (f"Signed in as {who.get('email')}"
                                          if who and who.get("email") else "Signed in", "ok")
            except Exception as e:            # noqa: BLE001
                with self._lock:
                    self._landing_line = (f"Not signed in: {_words_of(e)}"[:200], "warn")
            finally:
                with self._lock:
                    self._signing = False
                    self._signed_out_seen = (0.0, False)
        threading.Thread(target=work, daemon=True, name="landing-signin").start()
        return ""

    # -- the update's own buttons (dashboard._update_install and friends)

    def _update_do(self, do: str) -> str:
        s, rel = self._update_release()
        if rel is None:
            return "there is no newer version to get"
        if do not in self._offered(self._update_rows):
            if self._update_line:
                return ""                 # under way: the row says how far
            return "this copy does not install releases" if do == "update.install" \
                else "that is not on Home right now"
        if do == "update.notes":
            url = str(getattr(rel, "notes_url", "") or "")
            if not url.startswith(_URL_PREFIXES):
                return "the release notes are not on a page this desk opens"
            import webbrowser
            webbrowser.open(url)
            return ""
        if do == "update.winget":
            command = str(s.get("winget_command") or "")
            if not command:
                return "this copy did not come from winget"
            return f"copied: {command}" if copy_text(command) else "could not reach the clipboard"
        if do == "update.install":
            if paths.DEVELOPER or s.get("winget_command") or self._too_old_for(rel):
                return "this copy does not install releases"
            if self._update_line:
                return ""
            self._update_line = f"downloading DeskIT {rel.version}…"
            self._update_failed = ""

            def work() -> None:
                import updates

                def progress(done: int, total: int) -> None:
                    pct = int(done * 100 / total) if total else 0
                    with self._lock:
                        self._update_line = f"downloading DeskIT {rel.version}… {pct}%"
                try:
                    path = updates.download(rel, on_progress=progress)
                    with self._lock:
                        self._update_line = "Installing… DeskIT will close and reopen"
                    updates.install(path, rel, quit_app=singleton.request_quit)
                except Exception as e:    # noqa: BLE001
                    with self._lock:
                        self._update_line = ""
                        self._update_failed = _words_of(e)
                    log.warning("web desk: the update did not install: %s", type(e).__name__)
                    return
                # the installer closes every window anyway (Restart Manager)
                time.sleep(1.5)
                close = self.close_window
                if close is not None:
                    close()
            threading.Thread(target=work, daemon=True, name="update-install").start()
            return f"downloading DeskIT {rel.version}…"
        return f"{do!r} is not a desk action"

    #: set by run_window: closes this desk's window (after an install)
    close_window = None
    _update_failed = ""

    def home(self) -> dict:
        with self._lock:
            self._poll()
            return self._home()

    def _home(self) -> dict:
        items = self.pile()
        head, sub = self._head(items)
        keys = self._keys()
        # the app's word when it answers; sb.py's own when it does not
        locked = bool(self.status.get("locked")) if self.status else self._signed_out()
        _cfg, pcfg = self._problems_cfg()
        return {
            "ok": True,
            "locked": locked,
            "landing": self._landing() if locked else None,
            "report": self._report_view(),
            "report_on": bool(getattr(pcfg, "enabled", True)),
            "bar": self._bar(),
            "head": head, "sub": sub,
            "pile": items[:PILE_CAP],
            "unread": sum(1 for i in items if i["kind"] == "notify"),
            "dismiss_key": key_caps(keys.get("dismiss_hotkey", "")),
            "hold_key": pretty_key(str(keys.get("hotkey", ""))),
            "held": self._held(),
            "doors": self._doors(items),
            "rest": self._rest(),
            "strip": self._strip(),
            "places": list(PLACES), "built": list(BUILT),
        }

    # -- doing

    def act(self, do: str, arg=None) -> dict:
        """One button. Answers {"ok", "note", "home"}: the note is the
        line the page shows for a moment, and home is the page again,
        read after the press."""
        with self._lock:
            if self._log_stamp is None:   # a press before the first read
                self._poll()
            note = self._do(str(do), arg)
            # whatever the press wrote is read again, whatever its stat says
            self._kept.clear()
            home = self._home()
            return {"ok": True, "note": note or "", "home": home}

    def _ask(self, command: str, **args):
        self._busy_until = time.monotonic() + 1
        reply = self._send(command, timeout_ms=4000, **args)
        # the reply is the state after the press: take it now
        if isinstance(reply, dict) and reply.get("ok"):
            fresh = self._send("status", timeout_ms=1200)
            if isinstance(fresh, dict):
                self.phone_live = bool(fresh.get("phone"))
                self.status = _without_phone(fresh)
                self.running = self.status.get("stage") == "running"
        return reply

    @staticmethod
    def _said(reply, done: str) -> str:
        if reply is None:
            return "dictation is not running"
        if not reply.get("ok"):
            return str(reply.get("error") or "that did not work")
        return str(reply.get("message") or done)

    @staticmethod
    def _notify_id(arg) -> int | None:
        """A notification's id as the page sent it: a whole number, or
        nothing. The app reads an id that will not survive int() as NO id,
        and no id means every card (main.py's `notify` verb) — so a
        malformed one from the page would turn "this one" into "all of
        them", and must never reach the pipe."""
        if isinstance(arg, bool):
            return None
        if isinstance(arg, int):
            return arg
        if isinstance(arg, str) and arg.strip().isdigit() and len(arg) < 20:
            return int(arg)
        return None

    def _do(self, do: str, arg) -> str:
        if do in ("notify.dismiss", "notify.open"):
            ident = self._notify_id(arg)
            if ident is None:
                return "that message is not here"
        if do == "notify.dismiss":
            if not self.running:
                try:
                    import notify as notify_mod
                    notify_mod.Store(paths.NOTIFY_FILE).mark_seen([ident])
                except Exception as e:    # noqa: BLE001
                    return f"could not mark that seen ({type(e).__name__})"
                return ""
            # the row goes with the press, not with the app's answer
            self._gone.add(ident)
            reply = self._ask("notify", do="dismiss", id=ident)
            if reply is None or not reply.get("ok"):
                self._gone.discard(ident)
                return self._said(reply, "")
            return ""
        if do == "notify.open":
            if not self.running:
                return "nothing is running — start it to reach what sent that"
            return self._said(self._ask("notify", do="open", id=ident), "")
        if do == "notify.dismiss_all":
            try:
                import notify as notify_mod
                self._gone |= {i.get("id") for i in
                               notify_mod.Store(paths.NOTIFY_FILE).recent(30)
                               if not i.get("seen")}
            except Exception:             # noqa: BLE001
                pass
            if not self.running:
                try:
                    import notify as notify_mod
                    notify_mod.Store(paths.NOTIFY_FILE).mark_seen()
                except Exception as e:    # noqa: BLE001
                    return f"could not mark them seen ({type(e).__name__})"
                return "all marked seen"
            reply = self._ask("notify", do="dismiss")
            if reply is None or not reply.get("ok"):
                self._gone.clear()
            return self._said(reply, "all marked seen")
        if do in ("review.accepted", "review.rejected"):
            verdict = do.split(".", 1)[1]
            try:
                import review as review_mod
                item = review_mod.Store(paths.REVIEW_FILE).decide(str(arg), verdict,
                                                                  by="dashboard")
            except Exception as e:        # noqa: BLE001
                return f"could not save that ({type(e).__name__})"
            if item is None:
                return "that one was already decided"
            self._send("review_absorb", timeout_ms=1500)
            return "accepted — the app will learn it" if verdict == "accepted" else "rejected"
        if do == "run":
            return self._run()
        if do == "stop":
            return self._said(self._ask("unload"),
                              "unloading the model — every key that needs no model "
                              "keeps working")
        if do == "screens":
            reply = self._ask("screens", do="toggle")
            dark = ((reply or {}).get("awake") or {}).get("dark")
            return self._said(reply, "screens off — they stay off until you tap again"
                              if dark else "screens on")
        if do == "consent.on":
            # The kind comes from the page: only a gate this desk is asking
            # about again (its words changed, not waved away) may be granted
            # here — the Tk desk binds it from its own row. privacy.grant
            # takes any known kind, and a gate opens only through its card.
            try:
                import privacy
                privacy.configure(config_mod.load_layered())
                waiting = [k for k in privacy.stale() if k not in self._consent_later]
            except Exception as e:        # noqa: BLE001
                log.warning("could not read the consents: %s", type(e).__name__)
                return "could not record that"
            kind = arg if isinstance(arg, str) else ""
            if kind not in waiting:
                return "that consent is not waiting for an answer"
            try:
                privacy.grant(kind)
            except Exception as e:        # noqa: BLE001
                log.warning("could not record the consent for %s: %s", kind,
                            type(e).__name__)
                return "could not record that"
            return "turned on"
        if do == "consent.later":
            self._consent_later.add(str(arg))
            return ""
        if do == "keys.later":
            try:
                self._needs_key_later = float(arg)
            except (TypeError, ValueError):
                pass
            return ""
        if do.startswith("hardware.") and do not in self._offered(self._hardware_rows):
            # the page names the button; it works only while its row is
            # up — Remove the pack deletes 1.4 GB of a pack that runs
            return "that is not on Home right now"
        if do == "hardware.seen":
            try:
                import hardware as hardware_mod
                hardware_mod.clear_change()
            except Exception:             # noqa: BLE001
                pass
            return ""
        if do in ("hardware.model", "hardware.reinstall"):
            # a step in a process of its own — this window cannot host
            # the step's Tk root (dashboard._hardware_step)
            flag, name = (("--download-model", None) if do == "hardware.model"
                          else ("--install-pack", "gpu"))
            return ("the download window is opening…" if launch.run_step(flag, name)
                    else "could not start the download window")
        if do in ("hardware.retry", "hardware.remove"):
            try:
                import packs as packs_mod
                if do == "hardware.retry":
                    packs_mod.clear_failure("gpu")
                    return "GPU speed will be tried again at the next start"
                packs_mod.remove("gpu")
                # turned off by hand: the background downloads never fetch it again
                packs_mod.decline("gpu")
            except Exception as e:        # noqa: BLE001
                return f"could not do that ({type(e).__name__})"
            return "faster dictation is off — Settings > Dictation offers it again"
        if do in ("report.open", "report.cancel", "report.close", "report.preview",
                  "report.send", "report.consent", "report.keep"):
            return self._report_do(do, arg)
        if do in ("lock.copy", "lock.done", "lock.type", "lock.cancel", "lock.approve",
                  "lock.decline", "lock.recover", "lock.answer", "lock.restore",
                  "lock.signout_ask", "lock.signout_keep", "lock.signout_all",
                  "lock.recovery_new"):
            return self._lock_do(do, arg)
        if do in ("update.notes", "update.winget", "update.install"):
            return self._update_do(do)
        if do == "landing.signin":
            return self._landing_sign_in()
        if do == "open.capture":
            took = self._last_capture()
            if took is None or not launch.open_path(took[0].parent):
                return "could not open the folder"
            return ""
        if do == "old":
            return "the old desk is opening…" if open_old_desk(str(arg or "Home")) \
                else "could not open the old desk"
        return f"{do!r} is not a desk action"

    def _run(self) -> str:
        """Start, Resume, Pause — one button, three words
        (dashboard._toggle_pause)."""
        if not self.status:
            if singleton.is_running():
                return "it is already running"
            self._busy_until = time.monotonic() + 2
            return ("starting — the model takes about 25 seconds to load"
                    if launch.start_app() else "could not launch main.py — see app.log")
        model = self.status.get("model") or "on"
        if model in ("loading", "unloading"):
            return "the model is on its way — a moment"
        if model == "off":
            return self._said(self._ask("load"), "loading the model — about 25 seconds")
        reply = self._ask("toggle")
        return self._said(reply, "paused" if (reply or {}).get("paused") else "listening again")


def open_old_desk(place: str = "Home") -> bool:
    """The Tk desk, beside this one, at a place this desk does not draw
    yet. Its own mutex: if it is already open it comes to the front."""
    args = [str(APP_DIR / "dashboard.py"), "--tk"]
    if place in PLACES and place != "Home":
        args += ["--place", place]
    return launch.spawn(args)


# --------------------------------------------------------------- the Api


class Api:
    """What the page may ask — flat, the four names in CALLS and nothing
    else public (webdesk's dispatcher getattr's the name it is given)."""

    CALLS = CALLS

    def __init__(self, model: Model | None = None) -> None:
        self._model = model or Model()
        #: one Place per window and per place, built on its first call
        self._places: dict = {}
        self._places_lock = threading.Lock()

    def home(self):
        return self._model.home()

    def act(self, do: str, arg=None):
        return self._model.act(do, arg)

    def place(self, name: str, op: str = "read", args=None):
        """One call to a place's module (PLACES_MOD): "read" is
        Place.read(**args), "act" is Place.act(do, arg) with args {do,
        arg}. Anything else is refused in words, and a place that raises
        answers {ok: False, error: <the exception's type>} — never a
        traceback to the page, and never more than the type in app.log."""
        name, op = str(name or ""), str(op or "")
        if name not in PLACES_MOD:
            return {"ok": False, "error": f"{name[:40]!r} is not a desk place"}
        if op not in PLACE_OPS:
            return {"ok": False, "error": f"{op[:40]!r} is not a place call"}
        args = {} if args is None else args
        if not isinstance(args, dict):
            return {"ok": False, "error": "a place call's args are a dict"}
        if op == "act" and (not isinstance(args.get("do"), str) or set(args) - {"do", "arg"}):
            return {"ok": False, "error": "a place's act takes do and arg"}
        try:
            place = self._place(name)
            if op == "read":
                return place.read(**args)
            return place.act(args["do"], args.get("arg"))
        except Exception as e:            # noqa: BLE001 — the page gets words, not a traceback
            log.warning("web desk: %s %s failed: %s", name, op, type(e).__name__)
            return {"ok": False, "error": type(e).__name__}

    def _place(self, name: str):
        """The place's module, imported on its first call, and its one
        Place for this window — handed the Model's pipe function, so a
        test's or a probe's stubbed pipe is the place's pipe too."""
        import importlib
        with self._places_lock:
            place = self._places.get(name)
            if place is None:
                module = importlib.import_module(PLACES_MOD[name])
                place = self._places[name] = module.Place(self._model._send)
            return place

    def ping(self):
        return {"ok": True}


# ------------------------------------------------------------ the window


def ready() -> bool:
    """Whether this PC can open the web desk: pages built, WebView2 and
    .NET there (webdesk.precheck, registry only), pywebview importable."""
    import importlib.util
    try:
        if not (paths.WEB_DIST / "index.html").is_file():
            return False
        if importlib.util.find_spec("webview") is None:
            return False
        import webdesk
        return webdesk.precheck().ok
    except Exception:                     # noqa: BLE001
        return False


def wanted() -> bool:
    """`[desk] web` asks for this desk — honoured in the checkout only,
    and only where it can open."""
    if not paths.DEVELOPER:
        return False
    try:
        if not config_mod.load_layered().desk.web:
            return False
    except Exception:                     # noqa: BLE001
        return False
    return ready()


def _dark_caption(form) -> None:
    """The title bar the colour of the page (dashboard._dark_caption,
    in B+'s ground and ink): immersive dark mode, the caption colour,
    the caption text — COLORREF, so the bytes are the hex reversed."""
    try:
        hwnd = int(form.Handle.ToInt64())
        for attribute, value in ((20, 1), (35, 0x140A08), (36, 0xF7EDEF)):
            payload = ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute,
                                                       ctypes.byref(payload), 4)
    except Exception:                     # noqa: BLE001 — Windows 10: a pale bar
        pass


def _client_size(form) -> None:
    """The page is drawn for CLIENT_W x CLIENT_H: the window is sized by
    its client area, whatever this PC's frame and scale add round it."""
    try:
        from System.Drawing import Size
        scale = form.DeviceDpi / 96.0
        form.ClientSize = Size(int(CLIENT_W * scale), int(CLIENT_H * scale))
    except Exception:                     # noqa: BLE001
        pass


def _set_taskbar_relaunch(hwnd: int) -> bool:
    """What pinning this window should MEAN (dashboard._set_taskbar_relaunch,
    the same four properties on the form's own hwnd): the process is
    pythonw.exe, so without them a pin comes up with Python's icon, says
    "Python" and opens a bare interpreter. The relaunch command is the
    desk's own launcher (launch.dashboard_command), which opens this
    window when [desk] web asks for it and the Tk desk otherwise. Set
    before the window is shown: the shell reads them when the pin is
    made. Not inside the Store package, whose tile is the package's."""
    if paths.PACKAGED or not hwnd:
        return False
    try:
        from ctypes import POINTER, wintypes

        from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

        class PROPERTYKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

        class PROPVARIANT(ctypes.Structure):
            # only the VT_LPWSTR shape of the union — all this ever holds
            _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.USHORT),
                        ("r2", wintypes.USHORT), ("r3", wintypes.USHORT),
                        ("pwszVal", wintypes.LPWSTR), ("pad", ctypes.c_void_p)]

        class IPropertyStore(IUnknown):
            _iid_ = GUID("{886d8eeb-8cf2-4446-8d02-cdba1dbdcf99}")
            _methods_ = [
                COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(wintypes.DWORD), "count")),
                COMMETHOD([], HRESULT, "GetAt", (["in"], wintypes.DWORD, "index"),
                          (["out"], POINTER(PROPERTYKEY), "key")),
                COMMETHOD([], HRESULT, "GetValue", (["in"], POINTER(PROPERTYKEY), "key"),
                          (["out"], POINTER(PROPVARIANT), "value")),
                COMMETHOD([], HRESULT, "SetValue", (["in"], POINTER(PROPERTYKEY), "key"),
                          (["in"], POINTER(PROPVARIANT), "value")),
                COMMETHOD([], HRESULT, "Commit"),
            ]

        store = POINTER(IPropertyStore)()
        if ctypes.windll.shell32.SHGetPropertyStoreForWindow(
                ctypes.c_void_p(hwnd), ctypes.byref(IPropertyStore._iid_),
                ctypes.byref(store)) != 0:
            return False
        fmtid = GUID("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")
        command = " ".join(f'"{part}"' for part in launch.dashboard_command())
        for pid, text in ((5, APP_ID),                              # ...ID
                          (2, command),                             # ...RelaunchCommand
                          (4, "DeskIT"),                            # ...RelaunchDisplayName
                          (3, f"{paths.ICON_ICO},0")):              # ...RelaunchIcon
            value = PROPVARIANT()
            value.vt, value.pwszVal = 31, text                      # VT_LPWSTR
            store.SetValue(PROPERTYKEY(fmtid, pid), value)
        store.Commit()
        return True
    except Exception as e:                # noqa: BLE001
        log.debug("relaunch properties not set: %s", type(e).__name__)
        return False


def _on_form(form) -> None:
    _dark_caption(form)
    _client_size(form)
    try:
        _set_taskbar_relaunch(int(form.Handle.ToInt64()))
    except Exception:                     # noqa: BLE001
        pass


def _watch_show(desk_handle: dict, stop: threading.Event) -> None:
    """A second launch pokes WEBDESK_SHOW: the window comes to the front."""
    sig = singleton.Signal(WEBDESK_SHOW)
    user32 = ctypes.WinDLL("user32")
    try:
        while not stop.is_set():
            if not sig.wait(400):
                continue
            desk = desk_handle.get("desk")
            if desk is None or desk.edge is None:
                continue
            try:
                hwnd = desk.hwnd()
                user32.ShowWindow(hwnd, 9)            # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
            except Exception:             # noqa: BLE001
                pass
    finally:
        sig.close()


def run_window(*, api: Api | None = None, route: str = "", on_ready=None,
               hidden: bool = False, storage=None, watch_show: bool = False) -> int:
    """Open the desk and block until it closes (webdesk.run's codes: 0 ran,
    2 no WebView2, 3 no pages). `storage`: the browser's folder, when not
    paths.WEBVIEW_DIR — which the owner's own desk holds while it is open,
    and a second browser on it fails with 0x800700AA. `watch_show`: come
    to the front when a second launch pokes WEBDESK_SHOW — only for the
    window that holds the mutex (main): the event is auto-reset and its
    name is the checkout's in a worktree too, so a shot or a probe that
    waited on it could swallow the poke meant for his own desk."""
    import webdesk
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:                     # noqa: BLE001
        pass
    handle: dict = {}
    stop = threading.Event()
    if watch_show:
        threading.Thread(target=_watch_show, args=(handle, stop), daemon=True,
                         name="webdesk-show").start()

    def ready_then(desk):
        handle["desk"] = desk
        if on_ready is not None:
            on_ready(desk)

    def grab():
        # webdesk.run builds its Desk before it blocks; hand it to the
        # show watcher as soon as it exists
        while not stop.is_set():
            desk = getattr(webdesk.run, "last", None)
            if desk is not None:
                handle["desk"] = desk
                return
            time.sleep(0.05)

    if watch_show:
        threading.Thread(target=grab, daemon=True, name="webdesk-grab").start()
    api = api or Api()

    def close_window() -> None:
        desk = getattr(webdesk.run, "last", None)
        if desk is not None:
            try:
                desk.close()
            except Exception:             # noqa: BLE001
                pass
    api._model.close_window = close_window
    try:
        return webdesk.run(route=route, title=f"DeskIT {paths.DEV_TAG}".strip(),
                           api=api, width=CLIENT_W + 16, height=CLIENT_H + 39,
                           icon=paths.ICON_ICO if paths.ICON_ICO.is_file() else None,
                           on_form=_on_form, resizable=False, hidden=hidden,
                           storage=storage,
                           on_ready=ready_then if on_ready is not None else None)
    finally:
        stop.set()


def bring_up_the_keys() -> bool:
    """Nothing running when the desk opens: the app comes up behind it,
    as dashboard.bring_up_the_keys does for the Tk desk."""
    try:
        if singleton.is_running():
            return False
        return bool(launch.start_app())
    except Exception:                     # noqa: BLE001
        return False


def _shot(path: str, place: str):
    """on_ready for --shot: wait for Home's first answer, photograph the
    page, print one JSON line, close."""
    def on_ready(desk):
        import json
        note: dict = {}
        try:
            if place and place != "Home":
                desk.js("window.location.hash = " + json.dumps("#/" + place.lower()))
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if desk.js("document.body.dataset.read === '1'") is True:
                    break
                time.sleep(0.1)
            desk.wait_ready(10)
            time.sleep(0.4)
            note["client"] = desk.js("[document.documentElement.clientWidth, "
                                     "document.documentElement.clientHeight]")
            note["capture"] = desk.capture(path)
        except Exception as e:            # noqa: BLE001
            note["error"] = f"{type(e).__name__}: {e}"
        note.update(errors=desk.errors, dropped=desk.dropped, blocked=desk.blocked)
        print(json.dumps(note, ensure_ascii=False, default=str)[:2000])
    return on_ready


def main(argv=None) -> int:
    """The web desk, once. A second launch brings the first to the front.
    Returns webdesk.run's code, so dashboard.main can fall back to Tk."""
    import argparse
    parser = argparse.ArgumentParser(description="DeskIT's desk as a web page.")
    parser.add_argument("--shot", help="photograph the page into this PNG, hidden, and close")
    parser.add_argument("--place", default="Home", help="open on this place")
    ns = parser.parse_args(argv)
    route = "" if ns.place == "Home" else ns.place.lower()
    if ns.shot:
        # A photograph is not the desk: no mutex — a worktree's name is the
        # checkout's, so with his desk open the shot would only raise HIS
        # window — and a browser folder of its own, which his desk holds.
        import shutil
        import tempfile
        storage = tempfile.mkdtemp(prefix="DeskIT-shot-")
        try:
            return run_window(route=route, on_ready=_shot(ns.shot, ns.place),
                              storage=storage)
        finally:
            # the browser's processes let go of the folder a moment after
            # the window has closed
            for _ in range(50):
                shutil.rmtree(storage, ignore_errors=True)
                if not Path(storage).exists():
                    break
                time.sleep(0.1)
    try:
        lock = singleton.InstanceLock(WEBDESK_MUTEX)
    except singleton.AlreadyRunning:
        singleton.signal(WEBDESK_SHOW)
        return 0
    try:
        bring_up_the_keys()
        code = run_window(route=route, watch_show=True)
        if code == 0:
            # THE X CLOSES EVERYTHING — his rule of 2026-09-19, and the Tk
            # desk's (_close): the window a person opened, closed, is
            # Quit DeskIT. Not when it could not open (2, 3): then the
            # Tk desk opens in its place and the app must stay.
            singleton.request_quit()
        return code
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
