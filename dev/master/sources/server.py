"""The Server screen: what the account server is holding.

One row per table, counted, plus the two ceilings of the free plan that
can be measured from here. The key that can read other people's rows is
the project's SECRET key; it lives in Windows Credential Manager under
``DeskIT.dev/supabase_secret`` and this module never handles it itself —
``dev\\inbox.py`` already owns that and is imported for it, so there is
one reader of that key on this machine and not two (MASTER.md rule 5).

Read only. There is no write anywhere in this file, and the master has
no verb that could add one.

A number this screen cannot honestly measure is said to be unmeasured.
The database's size on disk and the bucket's bytes need Supabase's
management API and a token this machine does not have, so they are named
and left empty rather than guessed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .. import when as W
from ..root import Root
from ..rows import Row, line

#: the tables of supabase/migrations/*.sql, in the order a person cares
TABLES = (
    ("profiles", "accounts", "one row per person"),
    ("devices", "devices", "the PCs signed in"),
    ("history", "history rows", "every one of them sealed"),
    ("vocab_sync", "vocabulary rows", "the words, sealed"),
    ("settings_sync", "settings blobs", "one per account"),
    ("problem_reports", "reports", "what people sent"),
    ("vault", "vault rows", "the account keys, wrapped"),
    ("recovery", "recovery keys", "one per account"),
    ("pairings", "pairings", "a PC waiting to join"),
    ("deletion_requests", "deletion requests", "Delete my account"),
)

TIMEOUT_S = 12


class Unreachable(Exception):
    """No key, no project, or the network said no. Not an error the
    screen hides: it becomes the one row the screen shows."""


def rows(root: Root, *, net: bool = True) -> list[Row]:
    if not net:
        return [_offline("not asked (--no-net)")]
    try:
        url, key = _project(root)
    except Unreachable as e:
        return [_offline(str(e))]

    out: list[Row] = []
    for table, word, under in TABLES:
        try:
            n = _count(url, key, table)
        except Unreachable as e:
            out.append(_offline(str(e)))
            break
        if n is None:
            continue
        out.append(Row(
            id=f"server:{table}",
            screen="server", title=word.capitalize(), under=under,
            fig=f"{n:,}", fig_small=f"rows in {table}",
            tone="q", glyph="cloud", at=W.stamp_now(),
            facts={"Table": table, "Rows": n,
                   "Counted with": f"HEAD /rest/v1/{table}?limit=0, Prefer: count=exact",
                   "Project": url},
            came_from=[f"{url}/rest/v1/{table}"],
        ))
    out.append(Row(
        id="server:plan",
        screen="server", title="The free plan's ceilings",
        under=line("500 MB database", "1 GB storage", "50,000 accounts a month"),
        fig="—", fig_small="not measured here",
        tone="q", glyph="info", at=W.stamp_now(),
        facts={"Database size": "not measured — needs the management API token",
               "Storage bytes": "not measured — needs the management API token",
               "What is measured here": "row counts, through the REST API with the project's secret key"},
        came_from=["supabase free plan"],
    ))
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
    key = ""
    try:
        key = inbox.secret()
    except Exception:                                   # noqa: BLE001
        key = ""
    if not key:
        raise Unreachable("no secret key in Credential Manager "
                          f"({inbox.CRED_TARGET}) — run dev\\move_supabase_secret.py")
    return url, key


def _count(url: str, key: str, table: str) -> int | None:
    """PostgREST puts the count in Content-Range: 0-0/1234."""
    import urllib.error                                 # noqa: PLC0415
    import urllib.request                               # noqa: PLC0415
    # HEAD with limit=0: PostgREST answers with the count in a header and
    # no body at all. `select=id` was the first try and it 400s on every
    # table whose key is not called id (profiles, history, vault...), which
    # is how six of the ten tables silently went missing from this screen.
    req = urllib.request.Request(
        f"{url}/rest/v1/{table}?limit=0",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Prefer": "count=exact", "User-Agent": "DeskIT-master/1"},
        method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            rng = r.headers.get("Content-Range") or ""
    except urllib.error.HTTPError as e:
        if e.code in (404, 400):
            return None                 # a table this project does not have
        raise Unreachable(f"the project answered {e.code}") from e
    except OSError as e:
        raise Unreachable(f"could not reach the project ({e})") from e
    tail = rng.rsplit("/", 1)[-1].strip()
    return int(tail) if tail.isdigit() else None


def _offline(why: str) -> Row:
    return Row(
        id="server:offline", screen="server",
        title="The server was not read", under=why,
        tone="warn", glyph="warn", at=W.stamp_now(),
        facts={"Why": why,
               "The key": "Credential Manager, DeskIT.dev/supabase_secret",
               "What this screen does when it can read": "counts rows, table by table"},
        came_from=["dev\\inbox.py"],
    )
