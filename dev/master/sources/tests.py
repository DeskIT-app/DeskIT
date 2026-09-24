"""The Tests screen: last night on this PC, and the CI on GitHub.

Where the verdict lives, measured on this machine 2026-09-23. The nightly
wrapper keeps ONE log, ``problems\\nightly\\run.log``, and ends each run
with a line of its own:

    [2026-09-23 03:04:11] [out] {"result": "clean", "failed": [], "real": [],
                                 "code": 0, "transcript": "...", "report": null}

and the suite's own output is the per-night transcript beside it,
``<stamp>-tests.txt``, which ends "all tests passed (quietly)" and says
how many seconds it took. So the verdict is read from the log and the
transcript is the evidence — not the other way round, which is how the
first version of this file read eleven nights as "stopped".

``result`` is one of clean / flaky / failed / stopped. **flaky is not a
failure**: the nightly names the machine's one known flake
(``tests.KNOWN_FLAKES``), files nothing for it, and this screen says so
rather than colouring the night red.

Clean nights collapse into one row — nine of them is one fact, not nine —
and a night with real failures opens on its own, with the names in the
row and the failing output in the export.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import when as W
from ..root import Root
from ..rows import Evidence, Row, line
from ..run import Failed, out

NIGHTS_READ = 10          # how many nights are read back
RUNS = 15                 # how many CI runs gh is asked for
LOG = "run.log"


def rows(root: Root, *, net: bool = True) -> list[Row]:
    return _nights(root) + (_ci(root) if net else [])


# ---------------------------------------------------------------- the nights

def _nights(root: Root) -> list[Row]:
    if not root.nightly.is_dir():
        return []
    verdicts = _log(root.nightly / LOG)
    files = sorted(root.nightly.glob("*-tests.txt"), reverse=True)[:NIGHTS_READ]
    read = [(_verdict(path, verdicts.get(path.stem)), path) for path in files]

    out_rows: list[Row] = []
    run: list[tuple[dict, Path]] = []

    def flush() -> None:
        if len(run) >= 2:
            out_rows.append(_clean_row(run))
        else:
            out_rows.extend(_night_row(v, p) for v, p in run)
        run.clear()

    for verdict, path in read:
        if verdict["result"] in ("clean", "flaky") and out_rows:
            run.append((verdict, path))
            continue
        flush()
        out_rows.append(_night_row(verdict, path))
    flush()
    return out_rows


def _log(path: Path) -> dict[str, dict]:
    """Every [out] line of run.log, by the stem of the transcript it names.

    The seconds are on the line above it ("clean in 248s", "4 failed in
    261s"), so the last one seen before an [out] belongs to it.
    """
    out_map: dict[str, dict] = {}
    try:
        text = path.read_text("utf-8", errors="replace")
    except OSError:
        return out_map
    seconds = ""
    for line_ in text.splitlines():
        found = re.search(r"\bin (\d+)s\b", line_)
        if found and "[out]" not in line_ and "runs by itself" not in line_:
            seconds = found.group(1)
        if "[out] " not in line_:
            continue
        try:
            data = json.loads(line_.split("[out] ", 1)[1])
        except ValueError:
            continue
        stem = Path(str(data.get("transcript") or "")).stem
        if not stem:
            continue
        data["seconds"] = seconds
        data["at"] = line_[1:20]
        out_map[stem] = data
        seconds = ""
    return out_map


def _verdict(path: Path, from_log: dict | None) -> dict:
    """What the night said. The log when it is there, the transcript's own
    last lines when it is not — a run that died before writing its line
    still has a transcript, and "unknown" is an honest answer."""
    data = dict(from_log or {})
    tail = _tail(path)
    if not data:
        if "all tests passed" in tail:
            data = {"result": "clean", "failed": [], "real": [], "code": 0}
        elif "FAIL" in tail:
            data = {"result": "failed", "failed": _failed_names(path), "real": [], "code": 1}
        else:
            data = {"result": "unknown", "failed": [], "real": [], "code": None}
    data.setdefault("result", "unknown")
    data.setdefault("failed", [])
    data.setdefault("real", [])
    data["at"] = data.get("at") or _stamp(path)
    data["seconds"] = data.get("seconds") or _seconds(tail)
    data["tests"] = _count(path)
    data["path"] = str(path)
    return data


def _night_row(v: dict, path: Path) -> Row:
    failed = [str(x) for x in (v.get("failed") or [])]
    real = [str(x) for x in (v.get("real") or [])]
    result = v["result"]
    big, small = W.words(v.get("at"))

    if result == "clean":
        title = "Clean — the whole suite, the sixteen screen tests included"
        tone, glyph = "ok", "ok"
        under = line(_n(v["tests"]) + " tests" if v["tests"] else "",
                     f"{v['seconds']} s" if v["seconds"] else "",
                     "nothing filed, which is the point")
    elif result == "flaky":
        title = "Clean, but for a known flake — " + (failed[0] if failed else "?")
        tone, glyph = "ok", "ok"
        under = line(_n(v["tests"]) + " tests" if v["tests"] else "",
                     f"{v['seconds']} s" if v["seconds"] else "",
                     "the machine's own flake, nothing filed")
    elif result == "failed":
        shown = ", ".join((real or failed)[:2])
        more = len(real or failed) - 2
        title = (f"{len(real or failed)} failed — {shown}"
                 + (f" and {more} more" if more > 0 else ""))
        tone, glyph = "bad", "bad"
        under = line(_n(v["tests"]) + " tests" if v["tests"] else "",
                     f"{v['seconds']} s" if v["seconds"] else "",
                     "filed a report" if v.get("report") else "filed nothing")
    elif result == "stopped":
        title = "Stopped — the run was cut short"
        tone, glyph = "warn", "warn"
        under = line("nothing to read from it")
    else:
        title = "The night left no verdict"
        tone, glyph = "warn", "warn"
        under = line("no [out] line in run.log", "the transcript is still here")

    row = Row(
        id=f"tests:night:{path.stem}",
        screen="tests", title=title, under=under,
        tone=tone, glyph=glyph,
        when=big, when_small=small, at=W.sortable(v.get("at")),
        facts={"Result": result,
               "Failed": ", ".join(failed) or "none",
               "Real failures": ", ".join(real) or "none",
               "Known flake": ", ".join(sorted(set(failed) - set(real))) or "none",
               "Exit code": v.get("code", ""),
               "Tests": v.get("tests", ""), "Seconds": v.get("seconds", ""),
               "Filed a report": bool(v.get("report")),
               "Transcript": str(path)},
        came_from=[str(path), str(path.parent / LOG)],
    )
    row.evidence = [Evidence("transcript", "transcript", path)]
    if result in ("failed", "unknown"):
        row.body = _failing_lines(path, real or failed)
        row.body_title = "What the run printed"
        row.body_from = "machine"
    return row


def _clean_row(runs: list[tuple[dict, Path]]) -> Row:
    first, last = runs[-1][0], runs[0][0]
    secs = [int(v["seconds"]) for v, _ in runs if str(v.get("seconds")).isdigit()]
    flakes = sum(1 for v, _ in runs if v["result"] == "flaky")
    big, _ = W.words(last.get("at"))
    return Row(
        id=f"tests:clean:{_stamp_of(first)}..{_stamp_of(last)}",
        screen="tests",
        title=f"{len(runs)} clean nights",
        under=line("every one of them ran the sixteen",
                   f"{min(secs)}–{max(secs)} s" if secs else "",
                   f"{flakes} of them met the known flake" if flakes else ""),
        tone="ok", glyph="ok",
        when=big, when_small="→ " + (W.words(first.get("at"))[0] or ""),
        at=W.sortable(last.get("at")),
        facts={"Nights": len(runs), "From": first.get("at", ""), "To": last.get("at", ""),
               "Seconds": f"{min(secs)}–{max(secs)}" if secs else "",
               "Nights with the known flake": flakes,
               "Transcripts": ", ".join(str(p) for _, p in runs)},
        came_from=[str(p) for _, p in runs],
    )


# ---------------------------------------------------------------- transcripts

def _tail(path: Path, lines_: int = 40) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return "\n".join(fh.read().splitlines()[-lines_:])
    except OSError:
        return ""


def _count(path: Path) -> int:
    """How many tests ran: the PASS and FAIL lines the suite prints."""
    n = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                head = raw.strip()[:5]
                if head.startswith("PASS") or head.startswith("FAIL"):
                    n += 1
    except OSError:
        return 0
    return n


def _failed_names(path: Path) -> list[str]:
    names = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if raw.strip().startswith("FAIL"):
                    bits = raw.split()
                    if len(bits) > 1:
                        names.append(bits[1])
    except OSError:
        pass
    return names


def _failing_lines(path: Path, names: list[str]) -> str:
    """What the export carries for a bad night: each failing test once,
    with its own traceback under it.

    The first version took a window of lines around anything that said
    FAIL — including the run's own "4 FAILED: a, b, c" summary, and
    including the windows of the other failures — so the same block came
    out eight times and the document was mostly repetition (his export of
    2026-09-24). A block now starts at a FAIL line, stops at the next
    PASS / FAIL / section rule, and a name that has already been printed
    is skipped.
    """
    try:
        lines_ = path.read_text("utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    blocks: list[str] = []
    seen: set[str] = set()
    for i, line_ in enumerate(lines_):
        stripped = line_.strip()
        if not stripped.startswith("FAIL "):
            continue                       # "4 FAILED: ..." is a summary, not a failure
        name = stripped.split()[1].rstrip(":") if len(stripped.split()) > 1 else ""
        if name in seen:
            continue
        seen.add(name)
        block = [line_.rstrip()]
        for nxt in lines_[i + 1:i + 60]:
            head = nxt.strip()
            if head.startswith(("PASS ", "FAIL ", "----")) or head.startswith("running "):
                break
            block.append(nxt.rstrip())
        blocks.append("\n".join(block).rstrip())
    if names and not blocks:               # the transcript said nothing we can quote
        return "(the transcript has no line for: " + ", ".join(names) + ")"
    return "\n\n".join(blocks).strip()


def _seconds(tail: str) -> str:
    found = re.search(r"(\d+)s in all", tail) or re.search(r"\bin (\d+)s\b", tail)
    return found.group(1) if found else ""


def _stamp(path: Path) -> str:
    m = re.match(r"^(\d{8})-(\d{6})", path.stem)
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def _stamp_of(v: dict) -> str:
    return str(v.get("at") or "").replace(" ", "_")


def _n(value) -> str:
    return f"{int(value):,}" if str(value).isdigit() else str(value)


# ---------------------------------------------------------------- the CI

def _ci(root: Root) -> list[Row]:
    try:
        raw = out(["gh", "run", "list", "--limit", str(RUNS), "--json",
                   "displayTitle,headBranch,conclusion,status,createdAt,url,workflowName"],
                  root.dir)
        runs = json.loads(raw or "[]")
    except (Failed, ValueError) as e:
        return [Row(id="tests:ci:none", screen="tests",
                    title="GitHub was not read", under=str(e),
                    tone="warn", glyph="warn", at=W.stamp_now(),
                    facts={"Why": str(e), "Command": "gh run list"},
                    came_from=["gh run list"])]
    out_rows, seen = [], set()
    for run in runs:
        branch = str(run.get("headBranch") or "")
        if branch in seen:              # the newest run of each branch, and only it
            continue
        seen.add(branch)
        word = str(run.get("conclusion") or run.get("status") or "")
        tone, glyph = {"success": ("ok", "ok"), "failure": ("bad", "bad"),
                       "cancelled": ("warn", "warn")}.get(word, ("warn", "clock"))
        big, small = W.words(run.get("createdAt"))
        out_rows.append(Row(
            id=f"tests:ci:{branch}:{run.get('createdAt', '')}",
            screen="tests",
            title=f"{branch} — {'green' if word == 'success' else word}",
            under=line(run.get("workflowName"), run.get("displayTitle")),
            tone=tone, glyph=glyph,
            when=big, when_small=small, at=W.sortable(run.get("createdAt")),
            facts={"Branch": branch, "Workflow": run.get("workflowName", ""),
                   "Conclusion": word, "Started": run.get("createdAt", ""),
                   "Run": run.get("url", ""), "Commit": run.get("displayTitle", "")},
            came_from=[str(run.get("url") or "gh run list")],
        ))
    return out_rows
