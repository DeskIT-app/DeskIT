"""The Data screen: the training data, and the distance to every ceiling
that would delete some of it.

This screen exists because of one evening: the audit of 2026-09-23 found
``study.Corpus._trim`` deleting clips past ``[study] corpus_keep`` with
no owner check — 230 clips on this PC, 41 of them gold, 25-50 arriving a
day. A number nobody looks at is how that happens, so the number is a
row here, with its ceiling beside it.

The guard landed the same day (``if paths.OWNER_DATA: return``). The row
says which of the two worlds this checkout is in, and it reads the guard
out of ``study.py`` rather than assuming it: a screen that watches a
ceiling must not be the last thing to hear the ceiling moved.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import when as W
from ..root import Root, read_json
from ..rows import Row, line

KINDS = ("OK", "POLISHED", "LEARNED", "STUDIED", "REVIEW", "TRANSLATED",
         "PUNCTUATED", "LOOKED", "FAILED")


def rows(root: Root) -> list[Row]:
    out = []
    corpus = _corpus(root)
    keep = int(root.setting("study", "corpus_keep", 400) or 0)
    guarded = _trim_is_guarded(root)
    mine = (root.dir / ".git").exists()

    if keep > 0 and not (guarded and mine):
        left = keep - corpus["clips"]
        out.append(Row(
            id="data:trim",
            screen="data",
            title=f"{max(0, left)} clips from the trim that deletes gold ones",
            under=line(f"study.Corpus._trim keeps {keep}",
                       "no owner check in study.py" if not guarded else
                       "this copy is not the owner's checkout",
                       f"{corpus['gold']} gold clips are in the line"),
            tone="warn", glyph="warn",
            at=W.stamp_now(),
            facts={"Clips now": corpus["clips"], "Ceiling": keep,
                   "Gold clips": corpus["gold"],
                   "Guard in study.py": "yes" if guarded else "NO",
                   "Deletes oldest first": "silver before gold"},
            came_from=[str(root.corpus), str(root.dir / "study.py")],
        ))

    out.append(Row(
        id="data:corpus",
        screen="data", title="Corpus clips", under="what the study pass kept",
        fig=str(corpus["clips"]),
        fig_small=(f"of {keep} before the trim" if keep else "no ceiling"),
        pct=_pct(corpus["clips"], keep),
        meter_tone=_tone(corpus["clips"], keep),
        tone="q", glyph="stack", at=W.stamp_now(),
        facts={"Clips": corpus["clips"], "Gold": corpus["gold"],
               "Silver": corpus["silver"],
               "Minutes of voice": corpus["minutes"],
               "Oldest kept": corpus["first"], "Newest kept": corpus["last"],
               "Ceiling": keep or "none",
               "The trim runs here": "no (the owner's checkout)" if (guarded and mine) else "yes"},
        came_from=[str(root.corpus)],
    ))
    out.append(Row(
        id="data:gold",
        screen="data", title="Gold clips",
        under="text you corrected by hand — it cannot be made again",
        fig=str(corpus["gold"]), fig_small=f"of {corpus['clips']} clips",
        tone="q", glyph="star", at=W.stamp_now(),
        facts={"Gold clips": corpus["gold"],
               "Minutes of gold": corpus["gold_minutes"],
               "What makes a clip gold": "the text was corrected by a person "
                                         "(the correction key, or an approval in the second reading)",
               "What makes it silver": "every decode agreed on the text by itself",
               "Never admitted": "a guess"},
        came_from=[str(root.corpus)],
    ))
    out.append(Row(
        id="data:voice",
        screen="data", title="Hours of your voice", under="in the corpus",
        fig=_hours(corpus["seconds"]), fig_small=f"{corpus['clips']} clips",
        tone="q", glyph="mic", at=W.stamp_now(),
        facts={"Seconds": round(corpus["seconds"], 1),
               "Average clip": f"{corpus['seconds'] / corpus['clips']:.1f} s"
                               if corpus["clips"] else "0"},
        came_from=[str(root.corpus)],
    ))

    read = _clips(root.read_aloud)
    out.append(Row(
        id="data:read",
        screen="data", title="Read aloud", under="the sentences you read",
        fig=str(read["clips"]),
        fig_small=f"{read['minutes']} min" if read["clips"] else "none kept",
        tone="q", glyph="doc", at=W.stamp_now(),
        facts={"Clips": read["clips"], "Minutes": read["minutes"],
               "Folder": str(root.read_aloud),
               "Note": "a reset on 2026-09-17 removed 72 of these (29.6 minutes) "
                       "— they cannot be re-recorded"},
        came_from=[str(root.read_aloud)],
    ))

    recent = len(list(root.recent.glob("*.wav"))) if root.recent.is_dir() else 0
    ring = int(root.setting("vocab", "keep_audio", 50) or 0)
    out.append(Row(
        id="data:recent",
        screen="data", title="Recent recordings",
        under="the ring a report pins its audio from",
        fig=str(recent), fig_small=f"of {ring}" if ring else "",
        pct=_pct(recent, ring), meter_tone="ok",
        tone="q", glyph="mic", at=W.stamp_now(),
        facts={"Recordings": recent, "Ring": ring,
               "What it is for": "a correction, and a report, can be tied to the audio that produced it"},
        came_from=[str(root.recent)],
    ))

    log = _transcripts(root)
    out.append(Row(
        id="data:transcripts",
        screen="data", title="transcripts.log",
        under=line(f"{log['lines']:,} lines", "never pruned on this PC"),
        fig=log["size"], fig_small="the words themselves",
        tone="q", glyph="doc", at=W.stamp_now(),
        facts={"Lines": log["lines"], "Size": log["size"],
               "First line": log["first"], "Last line": log["last"],
               **{f"Lines · {k}": v for k, v in log["kinds"].items()}},
        came_from=[str(root.transcripts)],
    ))

    vocab = _vocab(root)
    out.append(Row(
        id="data:vocab",
        screen="data", title="Vocabulary",
        under="words it has learned to hear your way",
        fig=str(vocab["words"]),
        fig_small=f"{vocab['by_hand']} taught by hand",
        tone="q", glyph="doc", at=W.stamp_now(),
        facts={"Words": vocab["words"], "Taught by hand": vocab["by_hand"],
               "Newest": vocab["newest"]},
        came_from=[str(root.vocab)],
    ))
    return out


# ---------------------------------------------------------------- reading

def _corpus(root: Root) -> dict:
    out = {"clips": 0, "gold": 0, "silver": 0, "seconds": 0.0,
           "gold_seconds": 0.0, "first": "", "last": ""}
    if not root.corpus.is_dir():
        return {**out, "minutes": 0.0, "gold_minutes": 0.0}
    stamps = []
    for side in sorted(root.corpus.glob("*.json")):
        data = read_json(side, {}) or {}
        tier = str(data.get("tier") or "")
        seconds = float(data.get("seconds") or 0)
        out["clips"] += 1
        out["seconds"] += seconds
        if tier == "gold":
            out["gold"] += 1
            out["gold_seconds"] += seconds
        else:
            out["silver"] += 1
        if data.get("kept"):
            stamps.append(str(data["kept"]))
    stamps.sort()
    out["first"] = stamps[0] if stamps else ""
    out["last"] = stamps[-1] if stamps else ""
    out["minutes"] = round(out["seconds"] / 60, 1)
    out["gold_minutes"] = round(out["gold_seconds"] / 60, 1)
    return out


def _clips(folder: Path) -> dict:
    if not folder.is_dir():
        return {"clips": 0, "minutes": 0.0}
    wavs = list(folder.glob("*.wav"))
    seconds = 0.0
    for wav in wavs:
        data = read_json(wav.with_suffix(".json"), {}) or {}
        seconds += float(data.get("seconds") or 0)
    return {"clips": len(wavs), "minutes": round(seconds / 60, 1)}


def _transcripts(root: Root) -> dict:
    out = {"lines": 0, "size": "0 B", "kinds": {}, "first": "", "last": ""}
    if not root.transcripts.is_file():
        return out
    out["size"] = _size(root.transcripts.stat().st_size)
    kinds = {}
    first = last = ""
    try:
        with root.transcripts.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                out["lines"] += 1
                first = first or raw[:19]
                last = raw[:19]
                bits = raw.split(" | ")
                if len(bits) > 1:
                    word = bits[1].strip()
                    if word in KINDS:
                        kinds[word] = kinds.get(word, 0) + 1
    except OSError:
        return out
    out["kinds"] = dict(sorted(kinds.items(), key=lambda kv: -kv[1]))
    out["first"], out["last"] = first.strip(), last.strip()
    return out


def _vocab(root: Root) -> dict:
    data = read_json(root.vocab, {}) or {}
    pairs = data.get("corrections")
    pairs = [p for p in pairs if isinstance(p, dict)] if isinstance(pairs, list) else []
    by_hand = sum(1 for p in pairs if p.get("by") == "hand" or p.get("hand"))
    newest = ""
    if pairs:
        newest = max((str(p.get("last") or "") for p in pairs), default="")
    return {"words": len(pairs), "by_hand": by_hand, "newest": newest}


def _trim_is_guarded(root: Root) -> bool:
    """Does study.py's trim still refuse to run on the owner's data?

    Read out of the file, not assumed: this row's whole job is to notice
    when that changes.
    """
    try:
        src = (root.dir / "study.py").read_text("utf-8", errors="replace")
    except OSError:
        return False
    head = src.split("def _trim", 1)
    if len(head) < 2:
        return False
    body = head[1].split("\n    def ", 1)[0]
    return "OWNER_DATA" in body


# ---------------------------------------------------------------- numbers

def _pct(now: int, ceiling: int) -> int | None:
    if not ceiling:
        return None
    return max(0, min(100, round(now * 100 / ceiling)))


def _tone(now: int, ceiling: int) -> str:
    pct = _pct(now, ceiling)
    if pct is None:
        return ""
    return "bad" if pct >= 90 else "warn" if pct >= 50 else ""


def _hours(seconds: float) -> str:
    if seconds < 3600:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def _size(n: int) -> str:
    for unit, step in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= step:
            return f"{n / step:.1f} {unit}"
    return f"{n} B"


def _dumps(value) -> str:      # kept for the CLI's --json of a raw number
    return json.dumps(value, ensure_ascii=False)
