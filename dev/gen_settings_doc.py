"""The guide's generated pages (DISTRIBUTION_PLAN.md 14.6): the Settings
chapter from defaults.toml, the retention sentence from the same file,
and the app's string tables as JSON — so the guide quotes the wizard,
the consent cards and the key-field sentence verbatim instead of
retyping them.

    python dev/gen_settings_doc.py            write docs/en/settings.md,
                                              docs/he/settings.md,
                                              docs/strings/*
    python dev/gen_settings_doc.py --check    exit 1 when the committed
                                              files differ (release.yml)

The English page is generated in the Settings place's own order:
settings.TABS / TAB_SECTIONS / groups_for(), the way dashboard.py walks
them — so the document's order is the screen's order. Keys the Keys
place owns (the hotkeys) are listed on their own table, state keys
(positions, devices, the port — D2) do not appear because they are not
settings, and DEVELOPER-only sections do not appear because
settings.read() drops them for a stranger. The Hebrew page comes from
docs/strings/settings.he.json (key -> Hebrew sentence, the owner's, D34
chapter 16); a key without a Hebrew sentence falls back to English and
is listed at the end of the run so the gap is visible.

Owner-side, never shipped (dev/ is export-ignored).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

import config as config_mod  # noqa: E402
import hardware  # noqa: E402
import settings as settings_mod  # noqa: E402

DOCS = REPO / "docs"
STRINGS = DOCS / "strings"
DEFAULTS = REPO / "defaults.toml"

HEADER_EN = """---
title: Settings
---

# Settings

Every setting, in the words the Settings page uses, in the order the
page shows them. Generated from `defaults.toml` by `dev/gen_settings_doc.py`
— never edited by hand, so it cannot drift from the file. What you
change lands in `settings.toml` inside your DeskIT folder; the file
beside the app keeps the defaults and the help for every key.

"""

HEADER_HE = """---
title: הגדרות
---

# הגדרות

כל הגדרה, במילים שדף ההגדרות משתמש בהן, בסדר שבו הדף מציג אותן. הדף
נוצר מהקובץ `defaults.toml` על ידי `dev/gen_settings_doc.py` — לא נערך
ביד, ולכן לא יכול לסטות מהקובץ. מה שתשנה נשמר ב־`settings.toml` בתוך
תיקיית דסק-איט שלך; הקובץ שליד האפליקציה שומר את ברירות המחדל ואת
ההסבר לכל מפתח.

"""


def _default_text(value) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "(empty)"
    if value == "":
        return "(empty)"
    return f"`{value}`"


def _choices(row: settings_mod.Friendly, setting) -> str:
    if row.names:
        return " / ".join(name for _value, name in row.names)
    if setting.choices:
        return " / ".join(setting.choices)
    return {"bool": "on / off", "int": "a number", "float": "a number",
            "str": "text", "list": "a list"}.get(setting.kind, "")


def _tier_notes() -> dict[str, str]:
    """`local.device: cpu on the cpu tier, cuda on the gpu tiers` — one
    note per key chapter 6's tier table overrides."""
    notes: dict[str, dict[str, object]] = {}
    for tier, keys in hardware.DERIVED.items():
        for key, value in keys.items():
            notes.setdefault(key, {})[tier] = value
    out = {}
    for key, per_tier in notes.items():
        out[key] = "; ".join(f"{tier}: {_default_text(v)}" for tier, v in per_tier.items())
    return out


def _hotkey_paths() -> set[str]:
    import dashboard  # noqa: WPS433 — the Keys place's own list
    return dashboard._keys_screen_paths()


def _rows_for_tab(name: str, sections, skip) -> list[tuple[str, list[tuple]]]:
    """[(group title, [(setting, friendly), ...])] the way the tab draws."""
    out = []
    for group in settings_mod.groups_for(name, sections, skip):
        pairs = []
        for row in group.rows:
            s = settings_mod.find(sections, row.path)
            if s is None or config_mod.is_state_key(s.path):
                continue
            pairs.append((s, row))
        if pairs:
            out.append((group.title, pairs))
    return out


def _table(pairs, he: dict | None, gaps: list[str], notes: dict[str, str],
           hebrew: bool) -> list[str]:
    lines = []
    if hebrew:
        lines.append("| מפתח | מה זה | ברירת מחדל | אפשרויות |")
    else:
        lines.append("| key | what it does | default | choices |")
    lines.append("|---|---|---|---|")
    for s, row in pairs:
        sentence = row.help or ""
        label = row.label
        if hebrew:
            translated = (he or {}).get(s.path)
            if translated:
                label, sentence = translated.get("label", label), translated.get("help", sentence)
            else:
                gaps.append(s.path)
        note = notes.get(s.path)
        if note:
            sentence = f"{sentence} (per tier — {note})" if sentence else f"per tier — {note}"
        lines.append(f"| `{s.path}` — {label} | {sentence} | {_default_text(s.value)} "
                     f"| {_choices(row, s)} |")
    return lines


def settings_page(hebrew: bool, he: dict | None = None,
                  gaps: list[str] | None = None) -> str:
    """The whole page. `gaps` collects the keys the Hebrew map lacks."""
    gaps = [] if gaps is None else gaps
    sections = settings_mod.read(DEFAULTS, developer=False)
    skip = _hotkey_paths()
    notes = _tier_notes()
    parts = [HEADER_HE if hebrew else HEADER_EN]
    for tab in settings_mod.tab_names(sections, skip):
        parts.append(f"## {tab}\n")
        for title, pairs in _rows_for_tab(tab, sections, skip):
            sentence = ""
            plain = settings_mod.section_words(pairs[0][0].section, "")
            if plain.label.upper() == title:
                sentence = plain.help
            if title:
                parts.append(f"### {title.title() if title.isupper() else title}\n")
            if sentence:
                parts.append(sentence + "\n")
            parts.extend(_table(pairs, he, gaps, notes, hebrew))
            parts.append("")
    # the hotkeys, which the Keys place draws
    parts.append("## Keys\n" if not hebrew else "## Keys — המקשים\n")
    parts.append("These are the keyboard keys DeskIT listens to; the Keys place "
                 "shows them lit on a drawn keyboard and rebinds them.\n"
                 if not hebrew else
                 "אלה המקשים שדסק-איט מאזין להם; מקום Keys מציג אותם על מקלדת "
                 "מצוירת ומאפשר לשנות אותם.\n")
    keypairs = []
    for path in sorted(skip):
        s = settings_mod.find(sections, path)
        if s is not None:
            keypairs.append((s, settings_mod.words_for(s)))
    parts.extend(_table(keypairs, he, gaps, notes, hebrew))
    parts.append("")
    return "\n".join(parts).rstrip("\n") + "\n"


def retention_sentence() -> str:
    """Chapter 4.9's sentence, from the file's own numbers."""
    cfg = config_mod.load(DEFAULTS)
    audio = cfg.vocab.keep_audio
    days = cfg.history.keep_days
    lookups = getattr(cfg.lookup, "cache_entries", 0)
    audio_words = f"the last {audio} recordings" if audio else "none kept"
    days_words = f"{days} days" if days else "off"
    lookup_words = (f"the last {lookups} answers, on this PC" if lookups
                    else "not kept")
    return (f"Audio: {audio_words} · History: {days_words} · Learned words: until "
            f"you forget one · Reports: on this PC until you delete them · "
            f"Lookups: {lookup_words} · The speech model: until you delete it · "
            f"Nothing on any server unless you pressed Send.")


def string_tables() -> dict[str, dict]:
    """The app's own words, for the guide to quote."""
    import consent_card
    import firstrun
    wizard = {k: (list(v) if isinstance(v, tuple) else v)
              for k, v in firstrun.WORDS.items()}
    cards = {kind: consent_card.card_for(kind) for kind in consent_card.TEXTS}
    import secretstore
    keys = {name: secretstore.storage_sentence(name) for name in secretstore.KEY_HOSTS}
    return {"wizard": wizard, "consent": cards, "keys": keys}


def outputs() -> dict[Path, str]:
    he_map: dict = {}
    he_path = STRINGS / "settings.he.json"
    if he_path.exists():
        he_map = json.loads(he_path.read_text("utf-8"))
    gaps: list[str] = []
    out = {
        DOCS / "en" / "settings.md": settings_page(False),
        DOCS / "he" / "settings.md": settings_page(True, he_map, gaps),
        STRINGS / "retention.md": retention_sentence() + "\n",
    }
    for name, table in string_tables().items():
        out[STRINGS / f"{name}.json"] = json.dumps(table, ensure_ascii=False, indent=2) + "\n"
    out[STRINGS / "settings.he.gaps.txt"] = (
        "# keys with no Hebrew sentence in settings.he.json — the English one is shown\n"
        + "".join(f"{k}\n" for k in gaps))
    return out


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale = []
    for path, text in outputs().items():
        current = path.read_text("utf-8") if path.exists() else None
        if current != text:
            stale.append(path)
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="\n")
    if check:
        for path in stale:
            print(f"stale: {path.relative_to(REPO)}")
        return 1 if stale else 0
    for path in stale:
        print(f"wrote {path.relative_to(REPO)}")
    gaps = (STRINGS / "settings.he.gaps.txt").read_text("utf-8").splitlines()[1:]
    if gaps:
        print(f"{len(gaps)} key(s) without a Hebrew sentence — docs/strings/settings.he.gaps.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
