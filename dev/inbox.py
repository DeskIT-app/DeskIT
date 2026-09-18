"""The owner's inbox: the problem reports strangers chose to send, pulled
from the account server into ``problems\\inbox\\`` for the Saturday routine.

DISTRIBUTION_PLAN.md 7.7 (the contract), 8.10 (the console workflow),
D15 and D33(b). A person who ticked "Send to the developer" on a report
put one row into ``problem_reports`` and, per toggle, up to three
objects into the ``reports`` bucket (7.6, 8.4). This script is the ONLY
thing that reads them back on the owner's side, and it runs in the
checkout alone: with ``DESKIT_SUPABASE_SECRET`` from his environment —
never from a file in the repo, never in the product build — it talks
REST to the project with the secret key, which bypasses row-level
security, and writes what it fetched under ``DATA_DIR\\problems\\inbox\\``
in the shape ``problems.json`` rows have, so the routine's readers need
one more glob and nothing else.

What it reads, and what it never reads:

- ``problem_reports``, the columns in ``COLUMNS`` and no other: the
  identifiers, the timestamps, the machine facts every row carries
  (version, build, tier), the kind, the place, the text, the settings
  snapshot (a whitelist the server CHECKs, 7.8), the status, the two
  transcript columns — which are NULL unless the person ticked
  Transcript — and the list of objects the person ticked. A field the
  server hands back empty is written as ABSENT, not as "", so a reader
  sees "not consented" and cannot mistake it for "was empty".
- A storage object only when the row's ``attachments`` lists it, and
  only under the row's own ``<user_id>/<report_id>/`` prefix (the same
  rule the database enforces on insert). Audio comes down only when the
  row lists a ``.wav``.
- Never ``auth.users`` (where a linked e-mail would live), never
  ``profiles``, ``devices``, ``settings_sync``, ``vocab_sync`` or
  ``history``; the only thing known about the sender is the uuid that
  names their folder.

What it never does (D33(b)): it writes nothing back. There is no reply
command, no ``report_replies`` table, no status change from this side —
a person learns whether their report was fixed by using the app after
an update, and the owner's rule is that nothing from his side lands in
a user's account.

Tombstones (7.7): a row that is gone server-side — the person deleted
the report, or the account through ``delete_me()`` — takes the local
``<user_id>\\<report_id>.json`` and its files with it on the next run,
and a folder whose account has no rows left goes whole. The routine's
archive (``problems\\weekly\\*.md``) must not quote a deleted report
after that run: it wraps every stranger's report it archives in
``<!-- inbox <report_id> -->`` … ``<!-- /inbox <report_id> -->``
(the command file says so), and the tombstone cuts that block down to
one comment line. A file that still names the id outside such a block
is reported, not edited.

Every row and object fetched, every tombstone and every run is one line
in ``problems\\inbox\\fetch.log`` — what left the project and when, so
the owner's own egress is auditable (arch-B §7). No line quotes a
report, and nothing ever prints the key. ``index.json`` beside it is
rewritten every run: one entry per report with its path, its files and
the archive files that quote it, and no text.

Run it:

    .venv\\Scripts\\python.exe dev\\inbox.py            pull
    .venv\\Scripts\\python.exe dev\\inbox.py --dry-run  say what would change, write nothing

It refuses outside the checkout, without the secret in the environment,
or with a key that is not a secret key (the publishable one sees
nothing through RLS and would only look like an empty inbox).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import paths  # noqa: E402

#: The environment variable the secret key is read from. The name is
#: reserved in .gitignore's comment and never appears with a value in
#: the repo, a log or a report.
SECRET_ENV = "DESKIT_SUPABASE_SECRET"
#: Every secret API key of the project starts with this; the publishable
#: one starts with sb_publishable_ and is refused here on purpose.
SECRET_PREFIX = "sb_secret_"

TABLE = "problem_reports"
BUCKET = "reports"
#: The columns this script selects — 7.7's consented list, plus the two
#: it needs to do its job: ``attachments`` (what the person ticked; the
#: download decision, 7.7 "Attachments") and ``updated_at`` (which rows
#: changed since the last run). Nothing joins another table.
COLUMNS: tuple[str, ...] = (
    "id", "user_id", "created_at", "updated_at",
    "app_version", "os_build", "tier", "kind", "place", "text", "env",
    "status", "dictation_raw", "dictation_final", "attachments",
)
#: The objects a report may carry (8.4's names) and the field of the
#: local item each one lands in. Anything else listed is skipped and
#: logged, never fetched.
OBJECT_NAMES: frozenset = frozenset({"shot.jpg", "dictation.wav", "sidecar.json",
                                     "transcript.txt", "settings.json"})
#: A row's ``dictation`` carries these sidecar fields, like
#: problems.dictation() — bookkeeping keys stay in the file.
SIDECAR_KEYS = ("seconds", "backend", "language", "raw", "text", "words",
                "attempts", "last_error")
#: Rows per request; PostgREST's own ceiling is 1000.
PAGE = 500
TIMEOUT_S = 30.0
#: A uuid as the server writes it — the only thing that becomes a path.
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_BLOCK = "<!-- inbox {rid} -->"
_BLOCK_END = "<!-- /inbox {rid} -->"
_BLOCK_GONE = "<!-- inbox {rid}: deleted by its sender on {day} -->"

INBOX_DIR: Path = paths.PROBLEMS_DIR / "inbox"
WEEKLY_DIR: Path = paths.PROBLEMS_DIR / "weekly"


def project_ref() -> str:
    """The project the app itself talks to (sb.PROJECT_REF): one project,
    one place its ref is written."""
    import sb
    return sb.PROJECT_REF


class InboxError(Exception):
    """A refusal or a failed request, with a sentence and never the key."""


# ------------------------------------------------------------- the wire

def _connect(method: str, url: str, headers: dict, body: bytes | None,
             timeout_s: float) -> tuple[int, bytes]:
    """One HTTPS request; (status, body). The one function a test swaps
    for a fake. The product's chokepoint (net.py) is not used on purpose:
    this is the owner's script with the owner's key, outside the app,
    and it must not be in the window the app shows its users."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _headers(secret: str, accept: str = "application/json") -> dict:
    return {"apikey": secret, "Authorization": f"Bearer {secret}", "Accept": accept}


def _said(status: int, body: bytes) -> str:
    """The server's one-line reason, for a message that never quotes a row."""
    try:
        data = json.loads(body.decode("utf-8"))
        if isinstance(data, dict):
            for key in ("message", "error", "msg"):
                if data.get(key):
                    return f"HTTP {status}: {str(data[key])[:160]}"
    except (ValueError, UnicodeDecodeError):
        pass
    return f"HTTP {status}"


def _rest_rows(secret: str, base: str) -> list[dict]:
    """Every row of the table, the consented columns only, oldest first,
    a page at a time. Every status: the routine wants what was fixed too,
    and a tombstone is decided against the whole server set."""
    rows: list[dict] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode({
            "select": ",".join(COLUMNS),
            "order": "created_at.asc,id.asc",
            "limit": str(PAGE), "offset": str(offset)})
        url = f"{base}/rest/v1/{TABLE}?{query}"
        status, body = _connect("GET", url, _headers(secret), None, TIMEOUT_S)
        if status != 200:
            raise InboxError(f"reading {TABLE} failed ({_said(status, body)})")
        try:
            page = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise InboxError(f"reading {TABLE}: the answer was not JSON ({e})")
        if not isinstance(page, list):
            raise InboxError(f"reading {TABLE}: the answer was not a list")
        rows.extend(r for r in page if isinstance(r, dict))
        if len(page) < PAGE:
            return rows
        offset += PAGE


def _object(secret: str, base: str, path: str) -> bytes:
    url = f"{base}/storage/v1/object/{BUCKET}/{urllib.parse.quote(path)}"
    status, body = _connect("GET", url, _headers(secret, "*/*"), None, 120.0)
    if status != 200:
        raise InboxError(f"fetching {path} failed ({_said(status, body)})")
    return body


# ------------------------------------------------------------ the shape

def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _uuid(value) -> str | None:
    text = str(value or "").strip().lower()
    return text if _UUID.match(text) else None


def wanted_objects(row: dict, uid: str, rid: str) -> tuple[list[str], list[str]]:
    """(the object names this row may fetch, the entries it refuses):
    each listed path must be ``<uid>/<rid>/<name>`` with a name from
    OBJECT_NAMES — the database's own rule on insert, checked again here
    because a name becomes a path on this disk."""
    good: list[str] = []
    bad: list[str] = []
    listed = row.get("attachments")
    for entry in (listed if isinstance(listed, list) else []):
        text = str(entry or "")
        prefix = f"{uid}/{rid}/"
        name = text[len(prefix):] if text.startswith(prefix) else ""
        if name in OBJECT_NAMES and name not in good:
            good.append(name)
        else:
            bad.append(text[:120])
    return good, bad


def item_of(row: dict, uid: str, rid: str, files: dict, fetched_at: str) -> dict:
    """One inbox item in problems.json's row shape (``id, at, where,
    kind, text, status, resolved, by, dictation, shot, env``) plus what
    an inbox row has and a local one does not: ``user_id``, the machine
    facts as columns, ``updated_at``, the server's ``attachments`` list,
    ``files`` (name -> local path, relative to DATA_DIR like ``shot``
    is), ``fetched_at`` and ``source = "inbox"``. A transcript column
    the server returned NULL is absent from ``dictation``; a missing
    ``shot`` is ""; both mean "not consented", never "was empty"."""
    import redact

    status = str(row.get("status") or "open")
    item: dict = {
        "id": rid,
        "at": str(row.get("created_at") or ""),
        "where": str(row.get("place") or ""),
        "kind": str(row.get("kind") or "other"),
        "text": str(row.get("text") or ""),
        "status": status,
        "resolved": str(row.get("updated_at") or "") if status != "open" else None,
        "by": "",
        "dictation": {},
        "shot": files.get("shot.jpg", ""),
        "env": row.get("env") if isinstance(row.get("env"), dict) else {},
        "user_id": uid,
        "app_version": str(row.get("app_version") or ""),
        "os_build": str(row.get("os_build") or ""),
        "tier": str(row.get("tier") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "attachments": [str(a) for a in (row.get("attachments") or [])
                        if isinstance(a, str)],
        "files": dict(files),
        "fetched_at": fetched_at,
        "source": "inbox",
    }
    got: dict = {}
    if row.get("dictation_raw") is not None:
        got["raw"] = str(row["dictation_raw"])
    if row.get("dictation_final") is not None:
        got["final"] = str(row["dictation_final"])
    if "dictation.wav" in files:
        got["wav"] = files["dictation.wav"]
    if "sidecar.json" in files:
        for key, value in _sidecar(paths.DATA_DIR / files["sidecar.json"]).items():
            if key in SIDECAR_KEYS and key not in got:
                got[key] = value
    item["dictation"] = got
    # The redactor ran on the sender's PC and the server CHECKed the
    # columns; a third pass costs nothing and keeps the inbox clean even
    # if either ever slips.
    return redact.walk(item)


def _sidecar(path: Path) -> dict:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _rel(path: Path) -> str:
    """A local file written down the way problems.py writes ``shot``:
    relative to DATA_DIR, forward slashes."""
    try:
        return path.relative_to(paths.DATA_DIR).as_posix()
    except ValueError:
        return path.as_posix()


# --------------------------------------------------------------- the log

def _log(line: str, *, dry: bool = False) -> None:
    if dry:
        return
    try:
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        with open(INBOX_DIR / "fetch.log", "a", encoding="utf-8") as fh:
            fh.write(f"{_iso()} {line}\n")
    except OSError:
        pass


# ------------------------------------------------------------ the local set

def local_reports() -> dict[tuple[str, str], Path]:
    """(user_id, report_id) -> the json of every report on this disk.
    Only ``<uuid>\\<uuid>.json`` counts; index.json, fetch.log and a
    report's own folder are not reports."""
    out: dict[tuple[str, str], Path] = {}
    try:
        folders = [p for p in INBOX_DIR.iterdir() if p.is_dir() and _uuid(p.name)]
    except OSError:
        return out
    for folder in folders:
        for path in folder.glob("*.json"):
            rid = _uuid(path.stem)
            if rid:
                out[(folder.name.lower(), rid)] = path
    return out


def _read_item(path: Path) -> dict:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# ------------------------------------------------------------ tombstones

def _scrub_archive(rid: str, *, dry: bool = False) -> list[str]:
    """Cut the marked block of a deleted report out of every archive
    document; return the files that still name the id outside a block
    (the owner scrubs those by hand — this script edits nothing it
    cannot recognise)."""
    left: list[str] = []
    try:
        docs = sorted(WEEKLY_DIR.glob("*.md"))
    except OSError:
        return left
    start, end = _BLOCK.format(rid=rid), _BLOCK_END.format(rid=rid)
    gone = _BLOCK_GONE.format(rid=rid, day=time.strftime("%Y-%m-%d"))
    for doc in docs:
        try:
            text = doc.read_text("utf-8")
        except OSError:
            continue
        if rid not in text:
            continue
        out = text
        while True:
            a = out.find(start)
            b = out.find(end, a + len(start)) if a >= 0 else -1
            if a < 0 or b < 0:
                break
            out = out[:a] + gone + out[b + len(end):]
        if out != text and not dry:
            try:
                doc.write_bytes(out.encode("utf-8"))
            except OSError:
                left.append(_rel(doc))
                continue
        if rid in out.replace(gone, ""):
            left.append(_rel(doc))
    return left


def _tombstone(uid: str, rid: str, path: Path, *, dry: bool = False) -> None:
    folder = path.parent / rid
    if not dry:
        try:
            path.unlink()
        except OSError:
            pass
        shutil.rmtree(folder, ignore_errors=True)
    _log(f"gone {uid}/{rid}", dry=dry)
    for doc in _scrub_archive(rid, dry=dry):
        _log(f"warning {doc} still names {rid} outside a marked block - scrub it by hand",
             dry=dry)
        print(f"  {doc} still names the deleted report {rid} - scrub it by hand")


# ----------------------------------------------------------------- index

def write_index(*, dry: bool = False) -> dict:
    """index.json: one entry per report on this disk — its path, its
    files, and the archive documents that quote it (found by id) — and
    no text. Rewritten whole every run."""
    entries = []
    docs: dict[str, str] = {}
    try:
        for doc in sorted(WEEKLY_DIR.glob("*.md")):
            try:
                docs[_rel(doc)] = doc.read_text("utf-8")
            except OSError:
                pass
    except OSError:
        pass
    for (uid, rid), path in sorted(local_reports().items()):
        item = _read_item(path)
        entries.append({
            "user_id": uid, "id": rid,
            "at": str(item.get("at") or ""), "kind": str(item.get("kind") or ""),
            "status": str(item.get("status") or ""),
            "path": _rel(path),
            "files": sorted((item.get("files") or {}).values())
                     if isinstance(item.get("files"), dict) else [],
            "archived_in": [name for name, text in docs.items() if rid in text],
        })
    index = {"written": _iso(), "reports": entries}
    if not dry:
        try:
            INBOX_DIR.mkdir(parents=True, exist_ok=True)
            (INBOX_DIR / "index.json").write_bytes(
                json.dumps(index, ensure_ascii=False, indent=2).encode("utf-8"))
        except OSError:
            pass
    return index


# ------------------------------------------------------------------ pull

def pull(secret: str, *, dry: bool = False) -> dict:
    """One run: read the table, fetch what is new or changed with the
    objects each row lists, drop what the server no longer has, rewrite
    the index. Returns the counts the CLI prints. Raises InboxError on a
    refusal or a failed request — never half-writes a report: the json
    is written after its objects are on disk."""
    secret = (secret or "").strip()
    if not secret:
        raise InboxError(f"{SECRET_ENV} is not set in this environment - nothing fetched")
    if not secret.startswith(SECRET_PREFIX):
        raise InboxError(f"{SECRET_ENV} is not a secret key (it does not start with "
                         f"{SECRET_PREFIX}); the publishable key sees nothing here")
    ref = project_ref()
    if not ref:
        raise InboxError("sb.PROJECT_REF is empty - no project to read from")
    base = f"https://{ref}.supabase.co"
    counts = {"rows": 0, "new": 0, "changed": 0, "unchanged": 0, "objects": 0,
              "skipped": 0, "gone": 0}
    _log("run start" + (" (dry run)" if dry else ""), dry=dry)
    rows = _rest_rows(secret, base)
    have = local_reports()
    seen: set[tuple[str, str]] = set()
    for row in rows:
        uid, rid = _uuid(row.get("user_id")), _uuid(row.get("id"))
        if not uid or not rid:
            counts["skipped"] += 1
            _log("skipped a row whose ids are not uuids", dry=dry)
            continue
        counts["rows"] += 1
        seen.add((uid, rid))
        path = INBOX_DIR / uid / f"{rid}.json"
        old = _read_item(have[(uid, rid)]) if (uid, rid) in have else {}
        names, refused = wanted_objects(row, uid, rid)
        for entry in refused:
            counts["skipped"] += 1
            _log(f"skipped an attachment of {uid}/{rid} outside its own folder or "
                 f"not one of the five names", dry=dry)
        files: dict = {}
        folder = path.parent / rid
        for name in names:
            local = folder / name
            files[name] = _rel(local)
            if local.is_file():
                continue
            if dry:
                counts["objects"] += 1
                continue
            data = _object(secret, base, f"{uid}/{rid}/{name}")
            folder.mkdir(parents=True, exist_ok=True)
            local.write_bytes(data)
            counts["objects"] += 1
            _log(f"object {uid}/{rid}/{name} {len(data)} B", dry=dry)
        same = (old and old.get("updated_at") == str(row.get("updated_at") or "")
                and old.get("files") == files)
        if same:
            counts["unchanged"] += 1
            continue
        counts["changed" if old else "new"] += 1
        if dry:
            continue
        item = item_of(row, uid, rid, files, _iso())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(item, ensure_ascii=False, indent=2).encode("utf-8"))
        _log(f"row {uid}/{rid} status={item['status']} updated={item['updated_at']} "
             f"files={','.join(sorted(files)) or '-'}", dry=dry)
    for (uid, rid), path in sorted(have.items()):
        if (uid, rid) in seen:
            continue
        counts["gone"] += 1
        _tombstone(uid, rid, path, dry=dry)
    if not dry:
        for (uid, _rid), path in have.items():
            folder = path.parent
            try:
                if folder.is_dir() and not any(folder.iterdir()):
                    folder.rmdir()
            except OSError:
                pass
    write_index(dry=dry)
    _log("run done " + " ".join(f"{k}={v}" for k, v in counts.items()), dry=dry)
    return counts


# ------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry-run" in args
    words = [a for a in args if not a.startswith("-")]
    if words and words != ["pull"]:
        print(__doc__.split("Run it:", 1)[1].strip())
        return 2
    if not paths.DEVELOPER:
        print("the inbox is the owner's: it runs only in the checkout "
              "(no .git beside main.py here)")
        return 2
    try:
        counts = pull(os.environ.get(SECRET_ENV, ""), dry=dry)
    except InboxError as e:
        print(f"inbox: {e}")
        return 2 if "not set" in str(e) or "not a secret" in str(e) else 1
    except (OSError, urllib.error.URLError) as e:
        print(f"inbox: could not reach the project ({e})")
        return 1
    print(("would fetch " if dry else "inbox: ")
          + f"{counts['rows']} reports on the server: {counts['new']} new, "
            f"{counts['changed']} changed, {counts['unchanged']} unchanged, "
            f"{counts['objects']} files, {counts['gone']} gone, "
            f"{counts['skipped']} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
