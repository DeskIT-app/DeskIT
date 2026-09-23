"""The Reports screen: his own reports and other people's, in one list.

His are the items of ``problems.json``. Other people's are the files
``dev\\inbox.py pull`` has already written under
``problems\\inbox\\<user_id>\\<report_id>.json`` — deliberately in the
same shape a local report has, so this reads ONE list and not two.

Nothing here writes, and nothing here decides anything is handled: a
report closed on the server is still an unticked row until his hand
ticks it (MASTER.md rule 9).
"""
from __future__ import annotations

from pathlib import Path

from .. import when as W
from ..root import Root, read_json
from ..rows import Evidence, Row, line

#: kind -> (tone, glyph). The kinds are problems.KINDS, read as text so
#: this module imports nothing of the product's.
KIND_LOOK = {
    "broken": ("bad", "bad"),
    "wrong": ("warn", "warn"),
    "slow": ("warn", "clock"),
    "idea": ("iris", "idea"),
    "other": ("q", "doc"),
}
RESOLVED = ("fixed", "closed")


def rows(root: Root) -> list[Row]:
    out = [_mine(item, root) for item in _my_items(root)]
    out += [_theirs(path, root) for path in _inbox_files(root)]
    out.sort(key=lambda r: r.at, reverse=True)
    return out


# ---------------------------------------------------------------- his own

def _my_items(root: Root) -> list[dict]:
    data = read_json(root.problems, {}) or {}
    items = data.get("items")
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _mine(item: dict, root: Root) -> Row:
    ident = str(item.get("id") or "")
    status = str(item.get("status") or "open")
    tone, glyph = KIND_LOOK.get(str(item.get("kind") or "other"), KIND_LOOK["other"])
    if status in RESOLVED:
        tone, glyph = "q", "doc"
    text = str(item.get("text") or "").strip()
    big, small = W.words(item.get("at"))
    dictation = item.get("dictation") if isinstance(item.get("dictation"), dict) else {}
    row = Row(
        id=f"report:mine:{ident}",
        screen="reports",
        title=_one_line(text) or "(no words)",
        under=line("yours", item.get("where"), item.get("kind"),
                   _version(item), status if status != "open" else ""),
        body=text,
        rtl=_is_hebrew(text),
        tone=tone, glyph=glyph,
        when=big, when_small=small, at=W.sortable(item.get("at")),
        facts=_facts(item, whose="yours"),
        came_from=[str(root.problems)],
    )
    row.evidence = _evidence(item, dictation, root, folder=root.problems_dir)
    return row


# ---------------------------------------------------------------- strangers'

def _inbox_files(root: Root) -> list[Path]:
    if not root.inbox.is_dir():
        return []
    return sorted(p for p in root.inbox.glob("*/*.json") if p.name != "index.json")


def _theirs(path: Path, root: Root) -> Row:
    item = read_json(path, {}) or {}
    who = str(item.get("user_id") or path.parent.name)[:4]
    server = item.get("server") if isinstance(item.get("server"), dict) else {}
    status = str(item.get("status") or server.get("status") or "open")
    tone, glyph = KIND_LOOK.get(str(item.get("kind") or "other"), KIND_LOOK["other"])
    if status in RESOLVED:
        tone, glyph = "q", "doc"
    text = str(item.get("text") or "").strip()
    big, small = W.words(item.get("at") or server.get("created_at"))
    dictation = item.get("dictation") if isinstance(item.get("dictation"), dict) else {}
    row = Row(
        id=f"report:{path.parent.name}:{path.stem}",
        screen="reports",
        title=_one_line(text) or "(no words)",
        under=line(f"from a user · {who}", item.get("where"), item.get("kind"),
                   _version(item), _os(item), status if status != "open" else ""),
        body=text,
        rtl=_is_hebrew(text),
        tone=tone, glyph=glyph,
        when=big, when_small=small,
        at=W.sortable(item.get("at") or server.get("created_at")),
        facts=_facts(item, whose=f"from a user ({who})"),
        came_from=[str(path)],
    )
    row.evidence = _evidence(item, dictation, root, folder=path.parent)
    return row


# ---------------------------------------------------------------- pieces

def _evidence(item: dict, dictation: dict, root: Root, folder: Path) -> list[Evidence]:
    out: list[Evidence] = []
    shot = _beside(item.get("shot"), folder, root)
    if shot is not None:
        out.append(Evidence("picture", "picture", shot))
    wav = _beside(dictation.get("wav") or dictation.get("id"), folder, root, suffix=".wav")
    if wav is not None:
        seconds = dictation.get("seconds")
        word = f"{float(seconds):.1f} s" if isinstance(seconds, (int, float)) else "recording"
        out.append(Evidence("recording", word, wav))
        side = wav.with_suffix(".json")
        if side.is_file():
            out.append(Evidence("file", "what the model heard", side))
    return out


def _beside(name, folder: Path, root: Root, suffix: str = "") -> Path | None:
    """A file a report names: absolute, beside the report, or in the
    store the report's own copy was pinned into. Missing is not an
    error — a report is allowed to have lost its evidence."""
    text = str(name or "").strip()
    if not text:
        return None
    candidates = [Path(text)]
    stem = Path(text).name
    if suffix and not stem.endswith(suffix):
        stem += suffix
    candidates += [folder / stem, root.problems_dir / stem, root.recent / stem]
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            pass
    return None


def _facts(item: dict, whose: str) -> dict:
    env = item.get("env") if isinstance(item.get("env"), dict) else {}
    dictation = item.get("dictation") if isinstance(item.get("dictation"), dict) else {}
    facts = {
        "Whose": whose,
        "When": str(item.get("at") or ""),
        "Where in the app": str(item.get("where") or ""),
        "Kind": str(item.get("kind") or ""),
        "Status": str(item.get("status") or "open"),
        "Report id": str(item.get("id") or ""),
    }
    for key, value in sorted(env.items()):
        facts[f"Their copy · {key}"] = _plain(value)
    for key in ("raw", "final", "backend", "language", "seconds", "words"):
        if dictation.get(key) not in (None, ""):
            facts[f"The dictation · {key}"] = _plain(dictation[key])
    mark = item.get("resolved") if isinstance(item.get("resolved"), dict) else {}
    for key, value in mark.items():
        facts[f"Marked fixed · {key}"] = _plain(value)
    return {k: v for k, v in facts.items() if v not in ("", None)}


def _plain(value) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _version(item: dict) -> str:
    env = item.get("env") if isinstance(item.get("env"), dict) else {}
    return str(env.get("version") or item.get("app_version") or "")


def _os(item: dict) -> str:
    env = item.get("env") if isinstance(item.get("env"), dict) else {}
    return str(env.get("os") or env.get("os_build") or item.get("os_build") or "")


def _one_line(text: str) -> str:
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return first.strip()


def _is_hebrew(text: str) -> bool:
    """The first strong letter decides, the way a line's direction is
    decided everywhere else in this repo."""
    for ch in text or "":
        if "֐" <= ch <= "׿":
            return True
        if ch.isalpha():
            return False
    return False
