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
        rows, now = [], time.time()
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
            "buttons": [{"label": "Add a key", "tone": "primary", "act": "old", "arg": "Settings"},
                        {"label": "Not now", "tone": "quiet", "act": "keys.later", "arg": when}],
        }]

    def _update_rows(self) -> list[dict]:
        try:
            import updates
            s = updates.status()
        except Exception:                 # noqa: BLE001
            return []
        rel = s.get("available")
        if rel is None or s.get("mode") in ("store", "off", "offline"):
            return []
        when = f", {rel.published[:10]}" if rel.published else ""
        return [{
            "id": "update", "kind": "update", "at": time.time(), "tone": "q", "glyph": "up",
            "title": "A newer version", "meta": "",
            "text": f"DeskIT {rel.version} is available ({rel.size / 1_048_576:.0f} MB{when}) "
                    f"— you have {s.get('running', '')}.",
            "rtl": False,
            "note": "The old desk downloads it, checked against its SHA-256; "
                    "your data folder is untouched.",
            "buttons": [] if paths.DEVELOPER else
                       [{"label": "Open the old desk", "tone": "quiet", "act": "old",
                         "arg": "Home"}],
        }]

    def _hardware_rows(self) -> list[dict]:
        rows, now = [], time.time()
        dl = self.status.get("downloads") if self.running else None
        if dl and dl.get("state") in ("running", "waiting"):
            pct = int(round(float(dl.get("fraction") or 0) * 100))
            rows.append({
                "id": "downloads", "kind": "hardware", "at": now, "tone": "q", "glyph": "chip",
                "title": "This computer", "meta": "",
                "text": (f"Downloading app parts — {pct}%" if not dl.get("offline")
                         else "Downloading app parts — waiting for the connection"),
                "rtl": False, "note": "Once, in the background — nothing to press.",
                "buttons": []})
        try:
            import hardware as hardware_mod
            changed = str(hardware_mod.recorded().get("tier_changed") or "")
        except Exception:                 # noqa: BLE001
            changed = ""
        if changed:
            rows.append({
                "id": "tier", "kind": "hardware", "at": now, "tone": "q", "glyph": "chip",
                "title": "This computer", "meta": "",
                "text": f"Your hardware changed: DeskIT now runs {changed}.",
                "rtl": False,
                "note": "The speed settings for this tier were applied; yours were left alone.",
                "buttons": [{"label": "OK", "tone": "quiet", "act": "hardware.seen"}]})
        if not paths.PORTABLE:
            # The model and the GPU pack: their buttons start a step in a
            # process of its own, which the Tk desk does — sent there.
            try:
                import models as models_mod
                import packs as packs_mod
                model = models_mod.state(config_mod.load_layered().local.model)
                pack = packs_mod.standing("gpu")
            except Exception:             # noqa: BLE001
                model, pack = "unknown", "unknown"
            if (model in ("absent", "incomplete", "stale")
                    and not (dl and "model" in (dl.get("parts") or {}))):
                rows.append({
                    "id": "model", "kind": "hardware", "at": now, "tone": "warn",
                    "glyph": "chip", "title": "This computer", "meta": "",
                    "text": "The Hebrew model is not ready on this PC — dictation waits for it.",
                    "rtl": False, "note": "",
                    "buttons": [{"label": "Open the old desk", "tone": "quiet",
                                 "act": "old", "arg": "Home"}]})
            if pack.startswith("failed:"):
                rows.append({
                    "id": "pack", "kind": "hardware", "at": now, "tone": "bad",
                    "glyph": "chip", "title": "This computer", "meta": "",
                    "text": f"Your NVIDIA card was found but GPU speed could not start "
                            f"({pack[7:]}).",
                    "rtl": False, "note": "Dictation works on the processor meanwhile.",
                    "buttons": [{"label": "Open the old desk", "tone": "quiet",
                                 "act": "old", "arg": "Home"}]})
        return rows

    def _lock_rows(self) -> list[dict]:
        """The account's lock asks something (another PC, a changed lock,
        a recovery key to make). Its answers — codes, a recovery key typed
        in — live in the Tk desk for now; the row says what and sends
        him there."""
        if not self.running:
            return []
        account = self.status.get("account") or {}
        lock = dict(account.get("lock") or {})
        if not lock or not account.get("signed_in"):
            return []
        text = ""
        if lock.get("state") == "changed":
            text = "The lock of your account changed — not on this PC. Was it you?"
        elif lock.get("pending"):
            names = ", ".join(str(a.get("name") or "Another PC") for a in lock["pending"])
            text = f"{names} asks to join your account."
        elif lock.get("state") == "waiting":
            text = f"Waiting for your other PC to approve this one — Home there must " \
                   f"show {lock.get('code') or '…'}."
        elif lock.get("state") == "have" and lock.get("recovery") is False:
            text = "Make a recovery key — so a new PC of yours can open your account."
        if not text:
            return []
        return [{"id": "lock", "kind": "lock", "at": time.time() + 1, "tone": "warn",
                 "glyph": "lock", "title": "Your account", "meta": "", "text": text,
                 "rtl": False, "note": "",
                 "buttons": [{"label": "Open the old desk", "tone": "quiet",
                              "act": "old", "arg": "Home"}]}]

    def pile(self) -> list[dict]:
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

    def home(self) -> dict:
        with self._lock:
            self._poll()
            return self._home()

    def _home(self) -> dict:
        items = self.pile()
        head, sub = self._head(items)
        keys = self._keys()
        return {
            "ok": True,
            "locked": bool(self.status.get("locked")),
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

    def _do(self, do: str, arg) -> str:
        if do == "notify.dismiss":
            if not self.running:
                try:
                    import notify as notify_mod
                    notify_mod.Store(paths.NOTIFY_FILE).mark_seen([arg])
                except Exception as e:    # noqa: BLE001
                    return f"could not mark that seen: {e}"
                return ""
            # the row goes with the press, not with the app's answer
            self._gone.add(arg)
            reply = self._ask("notify", do="dismiss", id=arg)
            if reply is None or not reply.get("ok"):
                self._gone.discard(arg)
                return self._said(reply, "")
            return ""
        if do == "notify.open":
            if not self.running:
                return "nothing is running — start it to reach what sent that"
            return self._said(self._ask("notify", do="open", id=arg), "")
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
                    return f"could not mark them seen: {e}"
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
                return f"could not save that: {e}"
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
            try:
                import privacy
                privacy.grant(str(arg))
            except Exception as e:        # noqa: BLE001
                log.warning("could not record the consent for %s: %s", arg, e)
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
        if do == "hardware.seen":
            try:
                import hardware as hardware_mod
                hardware_mod.clear_change()
            except Exception:             # noqa: BLE001
                pass
            return ""
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


def _on_form(form) -> None:
    _dark_caption(form)
    _client_size(form)


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
               hidden: bool = False, storage=None) -> int:
    """Open the desk and block until it closes (webdesk.run's codes: 0 ran,
    2 no WebView2, 3 no pages). `storage`: the browser's folder, when not
    paths.WEBVIEW_DIR — which the owner's own desk holds while it is open,
    and a second browser on it fails with 0x800700AA."""
    import webdesk
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:                     # noqa: BLE001
        pass
    handle: dict = {}
    stop = threading.Event()
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

    threading.Thread(target=grab, daemon=True, name="webdesk-grab").start()
    try:
        return webdesk.run(route=route, title=f"DeskIT {paths.DEV_TAG}".strip(),
                           api=api or Api(), width=CLIENT_W + 16, height=CLIENT_H + 39,
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
                desk.js(f"window.location.hash = '#/{place.lower()}'")
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
        code = run_window(route=route)
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
