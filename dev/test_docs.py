"""The guide's tests (DISTRIBUTION_PLAN.md chapter 14, "Tests to add"):
the two language trees are complete, every picture a page names is a
file, the privacy chapter carries plan 5.10's six checks word for word,
the key-field sentence is the app's own, the generated pages are fresh,
no page speaks the owner's words, and every screen name a page uses is
one the app draws. File checks only, no Tk — the product CI runs this
file on every push (ci.yml) and dev/tests_ops.py runs it at night.

    .venv\\Scripts\\python.exe dev\\test_docs.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
sys.path.insert(0, str(REPO))

CHAPTERS = [f"{i:02d}-{name}.md" for i, name in enumerate(
    ("install", "first-run", "dictating", "privacy", "cloud", "phone", "screen",
     "your-data", "reporting", "faq"), start=1)]
PAGES = CHAPTERS + ["quickstart.md", "settings.md"]
FAILURES: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
        print(f"  PASS  {name}")
    except AssertionError as e:
        FAILURES.append(name)
        print(f"  FAIL  {name}: {e}")
    except Exception as e:                                   # noqa: BLE001
        FAILURES.append(name)
        print(f"  FAIL  {name}: unexpected {type(e).__name__}: {e}")


def _pages(lang: str) -> dict[str, str]:
    return {name: (DOCS / lang / name).read_text("utf-8") for name in PAGES
            if (DOCS / lang / name).exists()}


def test_guide_tree_complete():
    """Both trees hold the ten chapters, quickstart.md and settings.md;
    privacy.md, terms.md, index.md and _config.yml are at the root;
    every page starts with front matter and a language switch."""
    for lang in ("he", "en"):
        missing = [n for n in PAGES if not (DOCS / lang / n).exists()]
        assert not missing, f"docs/{lang}: missing {missing}"
        for name, text in _pages(lang).items():
            assert text.startswith("---\ntitle:"), f"{lang}/{name}: no front matter"
            other = "en" if lang == "he" else "he"
            assert f"../{other}/{name[:-3]}" in text or name == "settings.md", \
                f"{lang}/{name}: no link to the {other} page"
    for name in ("privacy.md", "terms.md", "index.md", "_config.yml"):
        assert (DOCS / name).exists(), f"docs/{name} missing"


def test_screenshots_exist():
    """Every ../img/<name>.png a page references is a file; the folder
    holds nothing a page does not reference (an orphan is a retake that
    nobody linked)."""
    referenced = set()
    for lang in ("he", "en"):
        for name, text in _pages(lang).items():
            for m in re.finditer(r"\]\(\.\./img/([^)]+)\)", text):
                referenced.add(m.group(1))
                assert (DOCS / "img" / m.group(1)).exists(), \
                    f"{lang}/{name} names docs/img/{m.group(1)}, which does not exist"
    on_disk = {p.name for p in (DOCS / "img").glob("*.png")}
    assert on_disk <= referenced, f"pictures no page names: {sorted(on_disk - referenced)}"


def _normal(text: str) -> str:
    text = re.sub(r",?\s*`research/[^`]*`\s*\w*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def test_privacy_chapter_matches_plan():
    """docs/en/04-privacy.md's six numbered checks equal chapter 5 §5.10's
    after whitespace normalisation (the plan's internal `research/…`
    citations aside); the closing paragraph's three sentences are there."""
    plan = (REPO / "DISTRIBUTION_PLAN.md").read_text("utf-8")
    section = plan.split("## 5.10 How a sceptic verifies each lock")[1].split("## Acceptance")[0]
    page = (DOCS / "en" / "04-privacy.md").read_text("utf-8")
    want = [_normal(m.group(0)) for m in re.finditer(r"^\d\. \*\*.*$", section, re.M)]
    have = [_normal(m.group(0)) for m in re.finditer(r"^\d\. \*\*.*$", page, re.M)]
    assert len(want) == 6 and have == want, "\n".join(
        f"{i + 1}: {'ok' if a == b else 'DIFFERS'}" for i, (a, b) in enumerate(zip(want, have)))
    for phrase in ("only the published migration", "not byte-reproducible",
                   "readable by malware running as"):
        assert phrase in page, phrase


def test_key_field_sentence_quoted():
    """The storage sentence quoted in 04-privacy.md and 05-cloud.md (both
    languages) equals docs/strings/keys.json's, which the generator
    exported from secretstore.storage_sentence — the string the Privacy
    tab draws."""
    import secretstore
    keys = json.loads((DOCS / "strings" / "keys.json").read_text("utf-8"))
    assert keys["groq"] == secretstore.storage_sentence("groq")
    for lang in ("en", "he"):
        for name in ("04-privacy.md", "05-cloud.md"):
            text = (DOCS / lang / name).read_text("utf-8")
            assert f"> {keys['groq']}" in text, f"{lang}/{name} does not quote the sentence"


def test_settings_doc_fresh():
    """dev/gen_settings_doc.py --check: the committed docs/en/settings.md,
    docs/he/settings.md and docs/strings/* are what the generator writes
    for this defaults.toml; every key of the file appears once on the
    English page, no state key and no DEVELOPER section appears."""
    out = subprocess.run([sys.executable, str(REPO / "dev" / "gen_settings_doc.py"), "--check"],
                         capture_output=True, encoding="utf-8", errors="replace", cwd=str(REPO))
    assert out.returncode == 0, f"stale generated pages:\n{out.stdout}{out.stderr}"
    import config as config_mod
    import settings as settings_mod
    page = (DOCS / "en" / "settings.md").read_text("utf-8")
    sections = settings_mod.read(REPO / "defaults.toml", developer=False)
    for section in sections:
        for s in section.settings:
            n = page.count(f"| `{s.path}` —")
            if config_mod.is_state_key(s.path):
                assert n == 0, f"state key {s.path} on the settings page"
            else:
                assert n == 1, f"{s.path} appears {n} times"
    for name in settings_mod.DEVELOPER_SECTIONS:
        assert f"`{name}." not in page, f"developer section {name} on the page"


def test_settings_doc_hebrew_gaps_listed():
    """A key with no Hebrew sentence in settings.he.json falls back to
    English on the Hebrew page and is listed in settings.he.gaps.txt."""
    gaps = (DOCS / "strings" / "settings.he.gaps.txt").read_text("utf-8").splitlines()[1:]
    he_map = {}
    he_path = DOCS / "strings" / "settings.he.json"
    if he_path.exists():
        he_map = json.loads(he_path.read_text("utf-8"))
    en = (DOCS / "en" / "settings.md").read_text("utf-8")
    he = (DOCS / "he" / "settings.md").read_text("utf-8")
    for key in gaps:
        assert key not in he_map, f"{key} listed as a gap but translated"
        row_en = next(l for l in en.splitlines() if l.startswith(f"| `{key}` —"))
        row_he = next(l for l in he.splitlines() if l.startswith(f"| `{key}` —"))
        assert row_en.split("|")[2] == row_he.split("|")[2], f"{key}: the fallback differs"


def test_retention_sentence_matches_defaults():
    """docs/strings/retention.md is the generator's sentence for this
    defaults.toml, and 08-your-data.md quotes it in both languages."""
    sys.path.insert(0, str(REPO / "dev"))
    import gen_settings_doc
    sentence = gen_settings_doc.retention_sentence()
    assert (DOCS / "strings" / "retention.md").read_text("utf-8").strip() == sentence
    for lang in ("en", "he"):
        assert f"> {sentence}" in (DOCS / lang / "08-your-data.md").read_text("utf-8"), lang


def test_faq_has_no_owner_words():
    """No guide page speaks of Push, Undo, nightly tests, the Saturday
    routine, branches, problems.md or .env — the owner's machinery
    (D15) never reaches a reader."""
    bad = ("Push", "Undo", "nightly", "Saturday", "branch", "problems.md", ".env")
    for lang in ("he", "en"):
        for name, text in _pages(lang).items():
            if name == "settings.md":
                # generated from the file: a default value may hold any
                # word (local.initial_prompt names git's), the prose may not
                text = "\n".join(l for l in text.splitlines() if not l.startswith("| `"))
            for word in bad:
                assert word not in text, f"{lang}/{name} says {word!r}"


def test_guide_uses_screen_names():
    """Every "Settings > X" and "Dashboard > X" a page names is a tab or a
    place the app draws (settings.TABS, dashboard.NAV), and the block
    titles named in capitals are ones the tabs carry — so a renamed
    screen fails the docs build."""
    import settings as settings_mod
    src = (REPO / "dashboard.py").read_text("utf-8")
    nav = re.findall(r'\("([a-z]+)", "([A-Za-z]+)"\)', src.split("NAV = (")[1].split(")\n")[0])
    places = {label for _key, label in nav}
    tabs = {tab.name for tab in settings_mod.TABS} | {settings_mod.ADVANCED}
    blocks = {"YOUR CLOUD KEYS", "WHAT MAY LEAVE THIS PC", "SWITCHES"}
    for lang in ("he", "en"):
        for name, text in _pages(lang).items():
            # Windows' own Settings pages the guide sends people to
            windows = {"Apps", "Privacy & security", "System", "Languages & input"}
            known = sorted(tabs | windows, key=len, reverse=True)
            pattern = "Settings > (" + "|".join(re.escape(k) for k in known) + r"|[A-Z][A-Za-z]+)"
            for m in re.finditer(pattern, text):
                tab = m.group(1)
                assert tab in known, \
                    f"{lang}/{name}: Settings > {tab} is not a tab ({sorted(tabs)})"
            for m in re.finditer(r"Dashboard > ([A-Z][A-Za-z]+)", text):
                assert m.group(1) in places, f"{lang}/{name}: Dashboard > {m.group(1)}"
            for m in re.finditer(r"\*\*([A-Z]{4,}(?: [A-Z]+)+)\*\*", text):
                assert m.group(1) in blocks, f"{lang}/{name}: block {m.group(1)!r}"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    picks = [a for a in sys.argv[1:] if not a.startswith("-")]
    if picks:
        tests = [(n, f) for n, f in tests if any(p in n for p in picks)]
    print(f"running {len(tests)} tests", flush=True)
    for test_name, fn in tests:
        check(test_name, fn)
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        sys.exit(1)
    print("\nall tests passed")
