"""What follows a person from one PC to the next, and what never leaves.

DISTRIBUTION_PLAN.md decision D31: a signed-in user sees the same
vocabulary, settings and history on every PC. Local-first — the files in
DATA_DIR stay the working copy, so dictation never waits on the network;
this module turns them into rows and rows back into files, and sb.py
carries the rows. Nothing here opens a socket, reads a key or takes a
``Config`` object: every function works on the flat dicts the files
already are, so a key field cannot be reached by accident (chapter 8.7).

Three stores, three shapes:

``settings.toml`` -> ``settings_sync`` (one jsonb blob).
    The override set minus every MACHINE-BOUND key — the [privacy] gates
    (a consent is a row in THIS PC's consent.json), the phone endpoint,
    the audio and camera devices, the hardware tier and the local
    model, every hotkey, every folder, every corner and position, the
    Ollama models this machine happens to have. ``syncable()`` is the
    rule and ``test_sync_serializer_drops_sync_false`` holds it. Last
    writer wins by the server's ``updated_at``.

``vocab.json`` -> ``vocab_sync`` (one row per learned correction).
    Merged as a union keyed by what was heard: the higher ``hits`` wins,
    the newer ``meant`` wins a tie. A word forgotten here since the last
    sync (in the snapshot ``cursor.json`` keeps, gone from the file) is
    pushed as a tombstone, and a tombstone pulled from another PC
    removes the word here.

``transcripts.log`` -> ``history`` (one row per event, append-only).
    Pushed from where the cursor left off; what other PCs said is pulled
    into ``sync\\history.log`` as REMOTE lines that history.py folds into
    the Said page with the other machine's name on the row.

The cursors — what was last pushed and pulled — live in ``sync\\cursor.json``
under DATA_DIR, never in settings.toml (they are this PC's alone).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import paths

log = logging.getLogger("app")

# --------------------------------------------------------------- settings

#: Whole sections that describe THIS machine, not the person.
LOCAL_SECTIONS: frozenset[str] = frozenset({
    "privacy", "server", "audio", "hardware", "setup", "updates", "notify",
    "awake", "account", "sync", "tests", "local",
})
#: Top-level keys that are the machine's.
LOCAL_KEYS: frozenset[str] = frozenset({"backend", "paste_chord"})
#: A key whose last segment ends with one of these stays home: the
#: bindings, the devices, the folders, the corners, the Ollama models.
LOCAL_SUFFIXES: tuple[str, ...] = ("hotkey", "chord", "device", "folder",
                                   "_dir", "corner", "url", "ollama_model",
                                   "local_model")
#: ...and whose last segment IS one of these: positions, the port, paths.
LOCAL_LAST: frozenset[str] = frozenset({"x", "y", "scale", "port", "host",
                                        "path", "dir", "file"})

#: The blob's cap, the migration's CHECK (64 KB).
SETTINGS_MAX_BYTES = 65536


def syncable(key: str) -> bool:
    """May this settings key leave the PC? False for everything that
    names a device, a folder, a key binding, a position, a port, the
    hardware tier or a consent."""
    key = str(key).strip()
    if not key:
        return False
    section, _, rest = key.partition(".")
    if not rest:                                   # a top-level key
        return key not in LOCAL_KEYS and not key.endswith(LOCAL_SUFFIXES)
    if section in LOCAL_SECTIONS:
        return False
    last = rest.rsplit(".", 1)[-1]
    if last in LOCAL_LAST or last.endswith(LOCAL_SUFFIXES):
        return False
    return True


def settings_payload(overrides: dict[str, object]) -> dict[str, object]:
    """The part of the override set that may travel, as one flat dict."""
    out = {k: v for k, v in overrides.items() if syncable(k)}
    if len(json.dumps(out, ensure_ascii=False).encode("utf-8")) > SETTINGS_MAX_BYTES:
        raise ValueError("the settings blob is over 64 KB — that is not a "
                         "settings file, it is something else")
    return out


def merge_settings(local: dict[str, object], remote: dict[str, object]) -> dict[str, object]:
    """The override set this PC should hold after a pull: its own
    machine-bound keys, and the other PC's syncable ones IN PLACE of its
    own (last writer wins on the whole blob, so a key the other PC reset
    to its default disappears here too)."""
    kept = {k: v for k, v in local.items() if not syncable(k)}
    kept.update({k: v for k, v in remote.items() if syncable(k)})
    return kept


# ------------------------------------------------------------------ vocab

_STAMP = "%Y-%m-%d %H:%M:%S"


def _iso(local_stamp: str | None) -> str | None:
    """vocab.json's 'YYYY-mm-dd HH:MM:SS' (local time) -> ISO 8601 UTC."""
    if not local_stamp:
        return None
    try:
        when = datetime.strptime(str(local_stamp), _STAMP)
    except ValueError:
        return None
    return when.astimezone(timezone.utc).isoformat(timespec="seconds")


def _local_stamp(iso: str | None) -> str:
    """The way back: an ISO timestamp -> vocab.json's local stamp."""
    if not iso:
        return time.strftime(_STAMP)
    try:
        when = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return time.strftime(_STAMP)
    return when.astimezone().strftime(_STAMP)


def vocab_rows(corrections: list[dict], snapshot: dict | None = None) -> list[dict]:
    """Every learned correction as a row, plus a tombstone for each word
    the snapshot remembers and the file no longer holds (forgotten here
    since the last sync). ``vocab_changed`` picks what to push."""
    rows: list[dict] = []
    seen: set[str] = set()
    for entry in corrections:
        heard = str(entry.get("heard") or "").strip()
        meant = str(entry.get("meant") or "").strip()
        hits = int(entry.get("hits", 1) or 0)
        # hits == 0 is study.py's own inference (learn_auto): a machine's
        # guess stays on that machine; a person's correction travels.
        if not heard or not meant or hits <= 0:
            continue
        key = heard.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "heard": heard[:200],
            "meant": meant[:200],
            "hits": min(hits, 1_000_000),
            "last_used": _iso(entry.get("last")),
            "deleted": False,
        })
    for key in (snapshot or {}):
        if key.lower() not in seen:
            rows.append({"heard": key[:200], "meant": "", "hits": 0,
                         "last_used": None, "deleted": True})
    return rows


def merge_vocab(corrections: list[dict], remote: list[dict]) -> tuple[list[dict], int]:
    """The local list after the other PCs' rows are folded in, and how
    many entries changed. A remote tombstone removes the word; a remote
    row with more hits wins; equal hits, the newer ``last_used`` wins
    ``meant``; a word this PC never heard of is added. Auto-learned
    fields (study.py's ``auto_hits``, ``auto_srcs``, ``glossary_only``)
    are this machine's evidence and are kept as they are."""
    by_key: dict[str, dict] = {}
    for entry in corrections:
        by_key.setdefault(str(entry.get("heard") or "").strip().lower(), entry)
    changed = 0
    out = list(corrections)
    for row in remote:
        heard = str(row.get("heard") or "").strip()
        if not heard:
            continue
        key = heard.lower()
        mine = by_key.get(key)
        if row.get("deleted"):
            if mine is not None:
                out = [e for e in out if e is not mine]
                by_key.pop(key, None)
                changed += 1
            continue
        meant = str(row.get("meant") or "").strip()
        if not meant:
            continue
        hits = int(row.get("hits") or 0)
        stamp = _local_stamp(row.get("last_used"))
        if mine is None:
            entry = {"heard": heard, "meant": meant, "hits": hits, "last": stamp}
            out.append(entry)
            by_key[key] = entry
            changed += 1
            continue
        my_hits = int(mine.get("hits", 1) or 0)
        newer = bool(row.get("last_used")) and stamp > str(mine.get("last") or "")
        if hits > my_hits:
            mine["hits"] = hits
            mine["meant"] = meant
            mine["last"] = max(stamp, str(mine.get("last") or ""))
            changed += 1
        elif hits == my_hits and newer and meant != mine.get("meant"):
            mine["meant"] = meant
            mine["last"] = stamp
            changed += 1
    return out, changed


def vocab_snapshot(corrections: list[dict]) -> dict[str, dict]:
    """What the file holds right now, keyed by the heard form — the
    memory that turns a later absence into a tombstone and an unchanged
    row into nothing to push."""
    out: dict[str, dict] = {}
    for e in corrections:
        heard = str(e.get("heard") or "").strip()
        hits = int(e.get("hits", 1) or 0)
        if heard and str(e.get("meant") or "").strip() and hits > 0:
            out[heard] = {"hits": hits, "meant": str(e.get("meant") or "").strip()}
    return out


def vocab_changed(rows: list[dict], snapshot: dict | None) -> list[dict]:
    """The rows worth pushing: new since the snapshot, changed since it,
    or a tombstone. With no snapshot (the first sync) every row goes."""
    if not snapshot:
        return [r for r in rows if not r.get("deleted")]
    out: list[dict] = []
    for row in rows:
        if row.get("deleted"):
            out.append(row)
            continue
        was = snapshot.get(row["heard"])
        if was is None or int(was.get("hits", -1)) != row["hits"]                 or str(was.get("meant") or "") != row["meant"]:
            out.append(row)
    return out


# ---------------------------------------------------------------- history

#: The event kinds that travel (history.KINDS minus errors and discards,
#: which are this machine's noise).
HISTORY_KINDS: tuple[str, ...] = ("dictation", "translate", "punctuate",
                                  "lookup", "learned")
HISTORY_BATCH = 500
TEXT_MAX = 4000


def history_rows(events, device_id: str, after: str | None) -> list[dict]:
    """The rows this PC pushes: every event newer than ``after`` (an ISO
    stamp, or None for all of them), oldest first, at most one batch.

    A row is keyed on the server by (device, ts, kind), so two events
    of one kind must never share a ``ts``. The log's milliseconds are
    kept, and an event stamped like the one before it (two second-
    reading verdicts accepted in one press land in the same
    millisecond) is moved one millisecond later — deterministically,
    from the file's order, so a re-push after a lost cursor lands on
    the same rows. Until 2026-09-20 the stamp was whole seconds and
    every batch with such a pair was refused as a whole ("ON CONFLICT
    DO UPDATE command cannot affect row a second time"): the owner's
    Dev copy pushed nothing for two days.
    """
    rows: list[dict] = []
    since = _parse_iso(after)
    last: dict[str, datetime] = {}                     # kind -> the ts just used
    for ev in sorted(events, key=lambda e: e.when):
        if ev.kind not in HISTORY_KINDS or not (ev.text or "").strip():
            continue
        when = ev.when.astimezone(timezone.utc).replace(
            microsecond=ev.when.microsecond // 1000 * 1000)
        prev = last.get(ev.kind)
        if prev is not None and when <= prev:
            when = prev + timedelta(milliseconds=1)
        last[ev.kind] = when
        if since is not None and when <= since:
            continue
        rows.append({
            "device_id": device_id,
            "ts": when.isoformat(timespec="milliseconds"),
            "kind": ev.kind,
            "text": str(ev.text)[:TEXT_MAX],
            "raw": (str(ev.source)[:TEXT_MAX] if ev.source and ev.source != ev.text
                    else None),
            "engine": str(ev.engine or "")[:32],
            "seconds": (float(ev.seconds) if ev.seconds is not None else None),
        })
        if len(rows) >= HISTORY_BATCH:
            break
    return rows


def _parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when


def remote_line(row: dict, device_name: str) -> str:
    """One row of another PC as a transcripts.log line history.py reads:
    ``<local stamp> | REMOTE | <kind> | <device> | <engine> | <seconds>s | <text>``,
    the text's newlines kept (a continuation line is the format's own).
    A learned row's text is written ``<raw> || <text>`` — what was shown
    and what it was fixed to, the CORRECTED line's shape — so the pair
    reaches the Corrections page's Lately list on this PC too."""
    when = _parse_iso(row.get("ts")) or datetime.now(timezone.utc)
    local = when.astimezone()
    stamp = local.strftime("%Y-%m-%d %H:%M:%S") + f",{local.microsecond // 1000:03d}"
    kind = str(row.get("kind") or "dictation")
    device = re.sub(r"\s*\|\s*", " ", str(device_name or "another PC")).strip()[:40]
    engine = re.sub(r"\s*\|\s*", " ", str(row.get("engine") or "")).strip()
    seconds = row.get("seconds")
    secs = f"{float(seconds):.1f}s" if seconds is not None else ""
    text = str(row.get("text") or "")
    if kind == "learned" and row.get("raw") and " || " not in text:
        text = f"{row['raw']} || {text}"
    return f"{stamp} | REMOTE | {kind} | {device} | {engine} | {secs} | {text}"


# ---------------------------------------------------------------- cursors

def cursor_path() -> Path:
    return paths.SYNC_DIR / "cursor.json"


def remote_history_path() -> Path:
    return paths.SYNC_DIR / "history.log"


def read_cursor() -> dict:
    try:
        data = json.loads(cursor_path().read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_cursor(cursor: dict) -> None:
    path = cursor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".json.{os.getpid()}.new")
    tmp.write_text(json.dumps(cursor, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   "utf-8")
    os.replace(tmp, path)


def append_remote_history(lines: list[str]) -> int:
    """The pulled rows onto sync\\history.log; how many were written."""
    if not lines:
        return 0
    path = remote_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")
    return len(lines)


def forget_all() -> list[str]:
    """Sign-out / delete-account: the cursors and the other PCs' lines
    go; this PC's own files are untouched. Returns what was removed."""
    gone: list[str] = []
    for path in (cursor_path(), remote_history_path()):
        try:
            path.unlink()
            gone.append(path.name)
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("sync: could not remove %s (%s)", path.name, e)
    return gone


__all__ = [
    "syncable", "settings_payload", "merge_settings",
    "vocab_rows", "merge_vocab", "vocab_snapshot", "vocab_changed",
    "history_rows", "remote_line", "HISTORY_KINDS", "HISTORY_BATCH",
    "read_cursor", "write_cursor", "append_remote_history", "forget_all",
    "cursor_path", "remote_history_path",
]
