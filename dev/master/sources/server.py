"""The Server screen: who is on the account server, what is kept for
them, and what is waiting for him.

**In plain words, not table names.** The first version of this screen
said "rows in vocab_sync" and "one row per person", and he read it and
asked what any of it meant (2026-09-24). A row here now says what the
number IS to a person; the table it came from and the request that
counted it are in the export's facts, where a chat wants them and the
screen does not.

The key that can read other people's rows is the project's SECRET key;
it lives in Windows Credential Manager under `DeskIT.dev/supabase_secret`
and this module never handles it itself — `dev\\inbox.py` owns it, and is
imported for it, so there is one reader of that key on this machine.

Read only. Nothing in this file writes, and the master has no verb that
could add one. It reads COUNTS and two aggregates (how many accounts
never signed in, when a computer was last seen); it never reads a
person's words, and never lists a device by name.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import when as W
from ..root import Root
from ..rows import Row, line

TIMEOUT_S = 12

#: The free plan's ceilings, for the one sentence the footer says.
PLAN = "500 MB of database, 1 GB of files, 50,000 people a month"


class Unreachable(Exception):
    """No key, no project, or the network said no. Not something the
    screen hides: it becomes the one row the screen shows."""


def rows(root: Root, *, net: bool = True) -> list[Row]:
    if not net:
        return [_offline("not asked (--no-net)")]
    try:
        url, key = _project(root)
    except Unreachable as e:
        return [_offline(str(e))]
    try:
        return _rows(url, key)
    except Unreachable as e:
        return [_offline(str(e))]


def _rows(url: str, key: str) -> list[Row]:
    people = _count(url, key, "profiles")
    anon = _count(url, key, "profiles", "is_anonymous=is.true")
    newest = _newest(url, key, "profiles", "created_at")
    devices = _count(url, key, "devices")
    seen = _newest(url, key, "devices", "last_seen")
    said = _count(url, key, "history")
    words = _count(url, key, "vocab_sync")
    settings = _count(url, key, "settings_sync")
    reports = _count(url, key, "problem_reports")
    vaults = _count(url, key, "vault")
    recovery = _count(url, key, "recovery")
    pairings = _count(url, key, "pairings")
    deletions = _count(url, key, "deletion_requests")

    def row(ident, title, under, fig, small, glyph="cloud", tone="q", **facts) -> Row:
        return Row(id=ident, screen="server", title=title, under=under,
                   fig=_n(fig), fig_small=small, tone=tone, glyph=glyph,
                   at=W.stamp_now(),
                   facts={**facts, "Project": url,
                          "How it was counted": "HEAD /rest/v1/<table>?limit=0 with "
                                                "Prefer: count=exact — the count comes back "
                                                "in a header, no rows are read"},
                   came_from=[url])

    out = [
        row("server:who:people", "People with an account",
            line(f"{anon} of them never signed in with Google" if anon else
                 "all of them signed in with Google",
                 f"newest joined {newest}" if newest else ""),
            people, "people", glyph="person",
            Table="profiles", Anonymous=anon, Newest=newest or "—"),
        row("server:who:devices", "Computers signed in",
            line("a copy of DeskIT with an account on it — yours and everybody else's",
                 f"one was seen {seen}" if seen else ""),
            devices, "computers", glyph="stack",
            Table="devices", **{"Last seen": seen or "—"}),

        row("server:kept:said", "Dictations kept for them",
            "what was said on one PC, waiting for their other PCs — sealed, "
            "the server cannot read a word",
            said, "dictations", glyph="mic", Table="history"),
        row("server:kept:words", "Words their copies learned",
            "the vocabulary that travels between a person's PCs — sealed",
            words, "words", glyph="doc", Table="vocab_sync"),
        row("server:kept:settings", "Settings kept for them",
            "one for each account, so a new PC comes up as the old one",
            settings, "accounts", glyph="doc", Table="settings_sync"),

        row("server:wait:reports", "Reports people sent",
            "they land on the Reports screen when you press Refresh there",
            reports, "reports", glyph="warn" if reports else "doc",
            tone="warn" if reports else "q", Table="problem_reports"),
        row("server:wait:pairings", "PCs waiting to join an account",
            "someone asked to add a second computer and has not been approved yet",
            pairings, "waiting", glyph="link",
            tone="warn" if pairings else "q", Table="pairings"),
        row("server:wait:locks", "Account locks made",
            line(f"{recovery} recovery key" + ("s" if recovery != 1 else ""),
                 "the key that opens a person's sealed words on a new PC"),
            vaults, "locks", glyph="star",
            Table="vault + recovery", **{"Recovery keys": recovery}),
        row("server:wait:deletions", "Accounts asked to be deleted",
            "the server removes them by itself; nothing here does",
            deletions, "asked", glyph="clock", Table="deletion_requests"),
    ]
    return out


# ---------------------------------------------------------------- the wire

def _project(root: Root) -> tuple[str, str]:
    """The project's URL and its secret key, both from dev\\inbox.py."""
    sys.path[:0] = [str(root.dir / "dev"), str(root.dir)]
    try:
        import inbox                                    # noqa: PLC0415
    except Exception as e:                              # noqa: BLE001
        raise Unreachable(f"dev\\inbox.py did not import ({e})") from e
    try:
        url = inbox.project_url()
    except Exception as e:                              # noqa: BLE001
        raise Unreachable(str(e)) from e
    try:
        key = inbox.secret()
    except Exception:                                   # noqa: BLE001
        key = ""
    if not key:
        raise Unreachable("no secret key in Credential Manager "
                          f"({inbox.CRED_TARGET}) — run dev\\move_supabase_secret.py")
    return url, key


def _headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}",
            "User-Agent": "DeskIT-master/1"}


def _count(url: str, key: str, table: str, where: str = "") -> int:
    """PostgREST puts the count in Content-Range: 0-0/1234.

    HEAD with limit=0: the count comes back in a header and no rows are
    read. `select=id` was the first try and it 400s on every table whose
    key is not called id (profiles, history, vault…), which had silently
    dropped six of the ten tables off this screen.
    """
    import urllib.error                                 # noqa: PLC0415
    import urllib.request                               # noqa: PLC0415
    query = f"limit=0{'&' + where if where else ''}"
    req = urllib.request.Request(f"{url}/rest/v1/{table}?{query}",
                                 headers={**_headers(key), "Prefer": "count=exact"},
                                 method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            rng = r.headers.get("Content-Range") or ""
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            return 0
        raise Unreachable(f"the project answered {e.code}") from e
    except OSError as e:
        raise Unreachable(f"could not reach the project ({e})") from e
    tail = rng.rsplit("/", 1)[-1].strip()
    return int(tail) if tail.isdigit() else 0


def _newest(url: str, key: str, table: str, column: str) -> str:
    """The newest stamp in one column, said as "2 hours ago" — one row,
    one column, no words of anybody's in it."""
    import urllib.error                                 # noqa: PLC0415
    import urllib.request                               # noqa: PLC0415
    req = urllib.request.Request(
        f"{url}/rest/v1/{table}?select={column}&order={column}.desc&limit=1",
        headers=_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            got = json.loads(r.read().decode("utf-8") or "[]")
    except (urllib.error.HTTPError, OSError, ValueError):
        return ""
    if not isinstance(got, list) or not got:
        return ""
    stamp = str((got[0] or {}).get(column) or "")
    ago = W.ago(stamp)
    return f"{ago} ago" if ago and ago != "just now" else (ago or "")


def _n(value) -> str:
    return f"{int(value):,}" if str(value).lstrip("-").isdigit() else str(value)


def _offline(why: str) -> Row:
    return Row(
        id="server:offline", screen="server",
        title="The server was not read", under=why,
        tone="warn", glyph="warn", at=W.stamp_now(),
        facts={"Why": why,
               "The key": "Windows Credential Manager, DeskIT.dev/supabase_secret",
               "What this screen does when it can read":
                   "counts what is on the account server, table by table"},
        came_from=["dev\\inbox.py"],
    )
