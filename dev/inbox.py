"""The owner's inbox: strangers' problem reports, pulled from the project
into `problems\\inbox\\<user_id>\\`, in the shape `problems.json` rows have
(DISTRIBUTION_PLAN.md 7.7, 8.10; D15, D16, D33).

This runs on the owner's machine and nowhere else. It is in `dev/`, so
the build manifest keeps it out of every installed copy, and it takes the
project's SECRET key from one place — the `DESKIT_SUPABASE_SECRET`
variable in the owner's own user environment (hand-work 1.2). Never from
a file, never from the repo, never printed. The publishable key the app
ships cannot read another person's rows (RLS, 8.3); this key can, which
is exactly why it lives here and not in the product.

WHAT IT READS, AND ONLY THAT. The columns 7.7 lists: id, user_id,
created_at, updated_at, app_version, os_build, tier, kind, place, text,
env, status, attachments, and dictation_raw / dictation_final — which
are non-null only when the person ticked "Transcript text" on the card.
A storage object is downloaded only when the row's `attachments` names
it, which is the list of what the person ticked; nothing else in the
bucket is listed or touched. No e-mail: anonymous accounts have none
and linked ones live in `auth.users`, which this script never selects.
Nothing is ever written to the project. (D33(b): there is no reply
channel — a person learns a report was fixed by using the app after an
update — so there is no `reply` command here.)

THE LAYOUT IS THE ROUTINE'S. Each report becomes
`problems\\inbox\\<user_id>\\<report_id>.json` with the keys a local
report has — id, at, where, kind, text, status, resolved, by,
dictation{}, shot, env{} — plus `user_id` and `server{}` (the columns as
they came), and its files beside it under the bucket's own names
(shot.jpg, dictation.wav, sidecar.json), so the Saturday routine
(`.claude/commands/weekly-reports.md`) reads the inbox with the same
eyes it reads `problems.json`, one more glob. `fetch.log` in
`problems\\inbox\\` records every row and every object fetched and
every local file a tombstone removed, so the owner's own egress is
auditable line by line.

TOMBSTONES. A report that is gone server-side — the person deleted it,
or ran Delete my account — is gone here on the next pull: the json and
the files beside it. A `<user_id>` folder with no rows left server-side
goes whole. `index.md` beside `fetch.log` is rewritten from what is on
disk after every pull, so nothing the routine reads can quote a report
that no longer exists — and the routine's own archive
(`problems\\weekly\\*.md`) is cut too: it wraps every stranger's report
it quotes in `<!-- inbox <report_id> -->` … `<!-- /inbox <report_id> -->`
(weekly-reports.md §6), and the tombstone replaces that block with one
comment line. A document that names the id outside such a block is
reported in fetch.log for the owner's hand, never edited blind.

    .venv\\Scripts\\python.exe dev\\inbox.py pull [--dry-run] [--status open]
    .venv\\Scripts\\python.exe dev\\inbox.py status
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys

import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import paths  # noqa: E402

log = logging.getLogger("inbox")

SECRET_VAR = "DESKIT_SUPABASE_SECRET"
URL_VAR = "DESKIT_SUPABASE_URL"
#: The consented columns (7.7). Nothing else is ever selected.
COLUMNS = ("id", "user_id", "created_at", "updated_at", "app_version",
           "os_build", "tier", "kind", "place", "text", "env", "status",
           "attachments", "dictation_raw", "dictation_final")
#: The bucket's file names (8.4) and where each lands on the local row.
FILES = {"shot.jpg": "shot", "dictation.wav": "wav", "sidecar.json": "sidecar"}
INBOX_NAME = "inbox"
FETCH_LOG = "fetch.log"
INDEX = "index.md"
PAGE = 500
TIMEOUT_S = 30.0
#: The routine's archive folder beside the inbox (problems\weekly\), and
#: the two comment lines it wraps a stranger's report in when it archives
#: one (weekly-reports.md §6) — so a tombstone can cut the quoted report
#: out again (7.7: "the archive documents must not quote deleted reports
#: after that run"). The block becomes one line that quotes nothing.
WEEKLY_NAME = "weekly"
BLOCK_START = "<!-- inbox {rid} -->"
BLOCK_END = "<!-- /inbox {rid} -->"
BLOCK_GONE = "<!-- inbox {rid}: deleted by its sender on {day} -->"


class InboxError(Exception):
    pass


# ------------------------------------------------------------ the project

def project_url() -> str:
    """The project's URL: DESKIT_SUPABASE_URL when set, else the ref the
    app ships (sb.PROJECT_REF) — one project, one place it is named."""
    url = os.environ.get(URL_VAR, "").strip().rstrip("/")
    if url:
        return url
    try:
        import sb
        ref = str(getattr(sb, "PROJECT_REF", "") or "").strip()
    except Exception:                                        # noqa: BLE001
        ref = ""
    if not ref:
        raise InboxError(f"no project: set {URL_VAR} or sb.PROJECT_REF")
    return f"https://{ref}.supabase.co"


def secret() -> str:
    """The secret key, from the owner's environment and nowhere else."""
    value = os.environ.get(SECRET_VAR, "").strip()
    if not value:
        raise InboxError(f"{SECRET_VAR} is not set in this environment — "
                         "it lives in the owner's user variables, never in "
                         "a file (hand-work 1.2)")
    if not value.startswith("sb_secret_"):
        raise InboxError(f"{SECRET_VAR} does not look like the project's "
                         "secret key (sb_secret_...)")
    return value


class Project:
    """The two calls this script makes: rows out of a table, an object
    out of the bucket. urllib, not net.py — net.py is the PRODUCT's one
    door and admits only the app's own purposes and keys; this is the
    owner's tool, and its audit trail is fetch.log."""

    def __init__(self, url: str, key: str, opener=None) -> None:
        self.url = url.rstrip("/")
        self._key = key
        self._open = opener or urllib.request.urlopen

    def _headers(self) -> dict:
        return {"apikey": self._key, "Authorization": f"Bearer {self._key}",
                "User-Agent": "DeskIT-inbox/1"}

    def rows(self, status: str | None = None) -> list[dict]:
        """Every report row (or those of one status), oldest first,
        paged so a busy month does not come back in one body."""
        out: list[dict] = []
        start = 0
        while True:
            query = {"select": ",".join(COLUMNS), "order": "created_at.asc",
                     "limit": str(PAGE), "offset": str(start)}
            if status:
                query["status"] = f"eq.{status}"
            url = f"{self.url}/rest/v1/problem_reports?{urllib.parse.urlencode(query)}"
            req = urllib.request.Request(url, headers=self._headers())
            with self._open(req, timeout=TIMEOUT_S) as r:
                page = json.loads(r.read().decode("utf-8") or "[]")
            if not isinstance(page, list):
                raise InboxError(f"the project answered with {type(page).__name__}")
            out.extend(x for x in page if isinstance(x, dict))
            if len(page) < PAGE:
                return out
            start += PAGE

    def object(self, path: str) -> bytes:
        """One object out of the private bucket, by its full path."""
        quoted = "/".join(urllib.parse.quote(p) for p in path.split("/"))
        url = f"{self.url}/storage/v1/object/reports/{quoted}"
        req = urllib.request.Request(url, headers=self._headers())
        with self._open(req, timeout=TIMEOUT_S) as r:
            return r.read()


# ------------------------------------------------------------- the inbox

def inbox_dir(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else paths.PROBLEMS_DIR) / INBOX_NAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log_line(box: Path, text: str) -> None:
    try:
        box.mkdir(parents=True, exist_ok=True)
        with (box / FETCH_LOG).open("a", encoding="utf-8") as fh:
            fh.write(f"{_now()}  {text}\n")
    except OSError:
        pass


def _safe(name: str) -> str:
    """A uuid as a folder or file name: the characters a uuid has and
    nothing that walks out of the inbox."""
    keep = "".join(c for c in str(name) if c.isalnum() or c == "-")
    if not keep or keep != str(name):
        raise InboxError(f"refusing an id that is not a plain uuid: {name!r}")
    return keep


def scrub_archive(rid: str, root: Path | None = None) -> list[str]:
    """Cut the marked block of a deleted report out of every document in
    problems\\weekly\\ (the block becomes one comment line that quotes
    nothing) and return the documents that STILL name the id outside a
    marked block — those the owner scrubs by hand; this script edits
    nothing it cannot recognise."""
    weekly = (Path(root) if root is not None else paths.PROBLEMS_DIR) / WEEKLY_NAME
    left: list[str] = []
    try:
        docs = sorted(weekly.glob("*.md"))
    except OSError:
        return left
    start, end = BLOCK_START.format(rid=rid), BLOCK_END.format(rid=rid)
    gone = BLOCK_GONE.format(rid=rid, day=_now()[:10])
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
        if out != text:
            try:
                doc.write_bytes(out.encode("utf-8"))
            except OSError:
                left.append(doc.name)
                continue
        if rid in out.replace(gone, ""):
            left.append(doc.name)
    return left


def _forget(box: Path, uid: str, rid: str, root: Path | None) -> None:
    """The archive's half of a tombstone, logged; a document the cut could
    not clean is named for the owner's hand."""
    for doc in scrub_archive(rid, root):
        _log_line(box, f"warning {WEEKLY_NAME}/{doc} still names {uid}/{rid} outside a "
                       f"marked block - scrub it by hand")


def local_row(row: dict) -> dict:
    """A server row in the shape problems.json rows have, so the routine
    reads both with one pair of eyes. `dictation` carries raw/final only
    when the person ticked Transcript (the columns are null otherwise);
    `shot` and `dictation.wav` are filled in by the pull once the files
    are down."""
    dictation: dict = {}
    if row.get("dictation_raw"):
        dictation["raw"] = str(row["dictation_raw"])
    if row.get("dictation_final"):
        dictation["final"] = str(row["dictation_final"])
    server = {k: row.get(k) for k in COLUMNS if k in row
              and k not in ("dictation_raw", "dictation_final")}
    return {
        "id": str(row.get("id", "")),
        "at": str(row.get("created_at", "")),
        "where": str(row.get("place") or ""),
        "kind": str(row.get("kind") or "other"),
        "text": str(row.get("text") or ""),
        "status": str(row.get("status") or "open"),
        "resolved": None,
        "by": "",
        "dictation": dictation,
        "shot": "",
        "env": row.get("env") if isinstance(row.get("env"), dict) else {},
        "user_id": str(row.get("user_id", "")),
        "server": server,
    }


def pull(project: Project, *, root: Path | None = None, status: str | None = None,
         dry_run: bool = False) -> dict:
    """The pull: rows in, ticked files beside them, tombstones out, the
    index rewritten. Returns counts. Never prints a row."""
    box = inbox_dir(root)
    rows = project.rows(status)
    counts = {"rows": len(rows), "new": 0, "files": 0, "removed": 0,
              "folders_removed": 0}
    seen: dict[str, set[str]] = {}
    if dry_run:
        for row in rows:
            seen.setdefault(str(row.get("user_id")), set()).add(str(row.get("id")))
        counts["users"] = len(seen)
        return counts
    for row in rows:
        uid, rid = _safe(row.get("user_id", "")), _safe(row.get("id", ""))
        seen.setdefault(uid, set()).add(rid)
        folder = box / uid
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{rid}.json"
        item = local_row(row)
        fresh = not target.exists()
        if not fresh:
            try:
                old = json.loads(target.read_text("utf-8"))
                if old.get("server", {}).get("updated_at") == item["server"].get("updated_at"):
                    item = old                    # nothing moved server-side
            except (OSError, ValueError):
                pass
        wanted = [str(a) for a in (row.get("attachments") or []) if isinstance(a, str)]
        for path in wanted:
            name = path.rsplit("/", 1)[-1]
            if name not in FILES or not path.startswith(f"{uid}/{rid}/"):
                _log_line(box, f"skipped {uid}/{rid} object outside the row's own folder: {path}")
                continue
            dst = folder / f"{rid}.{name}"
            if dst.exists():
                continue
            try:
                data = project.object(path)
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
                _log_line(box, f"could not fetch {path}: {e}")
                continue
            dst.write_bytes(data)
            counts["files"] += 1
            _log_line(box, f"fetched object {path} -> {dst.name} ({len(data)} bytes)")
            slot = FILES[name]
            if slot == "shot":
                # relative to DATA_DIR, the way a local row's shot is, so
                # problems.shot_path(store, item) resolves it unchanged
                item["shot"] = f"{paths.PROBLEMS_DIR.name}/{INBOX_NAME}/{uid}/{dst.name}"
            elif slot == "wav":
                item.setdefault("dictation", {})["wav"] = str(dst)
            elif slot == "sidecar":
                try:
                    side = json.loads(data.decode("utf-8"))
                    if isinstance(side, dict):
                        for key in ("seconds", "backend", "language", "words"):
                            if key in side:
                                item.setdefault("dictation", {})[key] = side[key]
                except ValueError:
                    pass
        target.write_text(json.dumps(item, ensure_ascii=False, indent=2), "utf-8")
        if fresh:
            counts["new"] += 1
            _log_line(box, f"fetched row {uid}/{rid} ({item['kind']}, {len(wanted)} object(s) listed)")
    # tombstones: what is here and not there — the files, and the block
    # the routine's archive quoted the report in (scrub_archive)
    if box.exists():
        for folder in sorted(p for p in box.iterdir() if p.is_dir()):
            uid = folder.name
            if uid not in seen:
                rids = sorted({e.name.split(".", 1)[0] for e in folder.glob("*.json")
                               if not e.name.endswith(".sidecar.json")})
                shutil.rmtree(folder, ignore_errors=True)
                counts["folders_removed"] += 1
                _log_line(box, f"removed folder {uid}: no rows left server-side")
                for rid in rids:
                    _forget(box, uid, rid, root)
                continue
            for entry in sorted(folder.glob("*.json")):
                rid = entry.name.split(".", 1)[0]
                if entry.name.endswith(".sidecar.json"):
                    continue
                if rid not in seen[uid]:
                    for gone in folder.glob(f"{rid}.*"):
                        try:
                            gone.unlink()
                        except OSError:
                            pass
                    counts["removed"] += 1
                    _log_line(box, f"removed {uid}/{rid}: the report is gone server-side")
                    _forget(box, uid, rid, root)
    counts["users"] = len(seen)
    write_index(root)
    return counts


def rows_on_disk(root: Path | None = None) -> list[dict]:
    """Every inbox row as stored, newest first — the routine's second
    glob, in one call."""
    box = inbox_dir(root)
    out: list[dict] = []
    if not box.exists():
        return out
    for folder in box.iterdir():
        if not folder.is_dir():
            continue
        for entry in folder.glob("*.json"):
            if entry.name.endswith(".sidecar.json"):
                continue
            try:
                item = json.loads(entry.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(item, dict):
                out.append(item)
    out.sort(key=lambda i: str(i.get("at", "")), reverse=True)
    return out


def write_index(root: Path | None = None) -> Path | None:
    """index.md: one line per report on disk, from the disk — so it can
    never name a report a tombstone removed."""
    box = inbox_dir(root)
    rows = rows_on_disk(root)
    if not box.exists():
        return None
    lines = [f"# Inbox — {len(rows)} report(s), rewritten {_now()}", ""]
    for item in rows:
        files = ", ".join(n for n in ("shot", "wav") if
                          (item.get("shot") if n == "shot" else (item.get("dictation") or {}).get("wav")))
        lines.append(f"- `{item.get('user_id', '')[:8]}/{item.get('id', '')}` · "
                     f"{item.get('at', '')[:16]} · {item.get('kind', '')} · "
                     f"{item.get('where', '') or '?'} · {item.get('status', '')}"
                     + (f" · files: {files}" if files else ""))
    path = box / INDEX
    path.write_text("\n".join(lines) + "\n", "utf-8")
    return path


def status(root: Path | None = None) -> dict:
    rows = rows_on_disk(root)
    return {"reports": len(rows), "users": len({r.get("user_id") for r in rows}),
            "open": sum(1 for r in rows if r.get("status") == "open"),
            "inbox": str(inbox_dir(root))}


# --------------------------------------------------------------- the CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull", help="fetch consented rows and files into problems\\inbox\\")
    p.add_argument("--status", default=None, help="only rows of this status (open, fixed, closed)")
    p.add_argument("--dry-run", action="store_true", help="count what would be pulled; write nothing")
    sub.add_parser("status", help="what is in the inbox on this disk")
    args = parser.parse_args(argv)
    if args.cmd == "status":
        print(json.dumps(status(), indent=2))
        return 0
    try:
        project = Project(project_url(), secret())
        counts = pull(project, status=args.status, dry_run=args.dry_run)
    except InboxError as e:
        print(f"inbox: {e}")
        return 2
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"inbox: the project did not answer ({e})")
        return 1
    # counts only — a row on stdout would land in the routine's run.log
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
