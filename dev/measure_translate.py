"""Does Groq keep English technical terms the way Gemini does? (item 12)

translate.py puts Gemini first because "it keeps embedded English technical
terms in Latin script". Before Groq can be the Translate key's fallback —
so that one Groq key covers translation too — that claim is measured on
both providers with the same fixed set: Hebrew sentences of the kind the
owner dictates to a coding assistant, each with the English terms that
must come out in Latin letters.

Two kinds of term are counted, separately:
  kept   — written in Latin in the input (config.toml, useEffect): must
           appear in the output EXACTLY, case included.
  named  — spelled in Hebrew letters in the input, the way the decoder
           writes an English word it has not learned (ברנץ', פוש): the
           English word must appear, any case.

A term is a hit when it is in the output; a sentence is clean when every
one of its terms is. One request per sentence per provider; nothing is
stored but the counts and the outputs this prints.

    .venv\\Scripts\\python.exe dev\\measure_translate.py [--only groq,gemini]

Uses the keys in Credential Manager (DeskIT/groq, DeskIT/gemini) and the
cloud_text gate is treated as open FOR THIS PROCESS ONLY (privacy.require
is replaced in memory; consent.json is never written). Gemini's free tier
is 20 requests a day per model: one run spends 16 of them.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import privacy                          # noqa: E402

privacy.require = lambda kind: f"{kind}@measure"   # this process only

import config as config_mod             # noqa: E402
import translate                        # noqa: E402

# (hebrew, kept-in-Latin terms, English words for Hebrew-spelled terms)
SET: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("תפתח את config.toml ותשנה את timeout_s לשלושים",
     ("config.toml", "timeout_s"), ()),
    ("ה-useEffect רץ פעמיים בגלל StrictMode, תסביר למה",
     ("useEffect", "StrictMode"), ()),
    ("תעשה git rebase על main ואל תעשה פוש עדיין",
     ("git rebase", "main"), ("push",)),
    ("יש באג ב-dashboard.py בשורה 7134, הכפתור Sign out לא עובד",
     ("dashboard.py", "7134", "Sign out"), ()),
    ("תריץ את tests_quiet.py עם --no-screen ותגיד לי מה נכשל",
     ("tests_quiet.py", "--no-screen"), ()),
    ("תוסיף endpoint חדש ב-FastAPI שמחזיר JSON עם רשימת המשתמשים",
     ("FastAPI", "JSON"), ("endpoint",)),
    ("הבראנץ' של cloud-keys צריך merge מ-wizard-polish לפני שנוגעים ב-KEY_ROWS",
     ("cloud-keys", "wizard-polish", "KEY_ROWS"), ("branch", "merge")),
    ("תבדוק למה ה-API של Groq מחזיר 429 אחרי עשר בקשות",
     ("API", "Groq", "429"), ()),
    ("תעשה קומיט עם הודעה ברורה ותדחוף לגיטהאב",
     (), ("commit", "GitHub")),
    ("המודל של Whisper נטען ב-CUDA אבל ה-VRAM מתמלא",
     ("Whisper", "CUDA", "VRAM"), ()),
    ("תכתוב טסט שבודק ש-find_key לא מחזיר את הערך עצמו",
     ("find_key",), ("test",)),
    ("בפול ריקווסט תוסיף צילום מסך של הדשבורד",
     (), ("pull request", "dashboard")),
    ("למה הדוקר קונטיינר לא עולה אחרי שעשיתי docker compose up",
     ("docker compose up",), ("container",)),
    ("תחליף את ה-Label ב-Canvas כי ל-Tk אין bidi",
     ("Label", "Canvas", "Tk", "bidi"), ()),
    ("שלח לי את ה-PR לריוויו ותתייג את Yoav",
     ("PR", "Yoav"), ("review",)),
    ("ה-deploy ל-Vercel נכשל כי חסר משתנה סביבה SUPABASE_URL",
     ("Vercel", "SUPABASE_URL"), ("deploy",)),
]


def score(out: str, kept, named) -> tuple[int, int, list[str]]:
    hits, missed = 0, []
    low = out.lower()
    for t in kept:
        if t in out:
            hits += 1
        else:
            missed.append(t)
    for t in named:
        if t.lower() in low:
            hits += 1
        else:
            missed.append(t)
    return hits, len(kept) + len(named), missed


def run(name: str, backend) -> dict:
    total_hits = total_terms = clean = 0
    hebrew_left = failures = 0
    ms: list[float] = []
    for he, kept, named in SET:
        t0 = time.perf_counter()
        try:
            out = backend.translate(he)
        except Exception as e:                       # one row, keep going
            failures += 1
            print(f"  [{name}] FAILED: {e}")
            continue
        ms.append((time.perf_counter() - t0) * 1000)
        hits, n, missed = score(out, kept, named)
        total_hits += hits
        total_terms += n
        clean += not missed
        hebrew_left += bool(translate.HEBREW.search(out))
        mark = "ok " if not missed else "MISS " + ", ".join(missed)
        print(f"  [{name}] {ms[-1]:5.0f} ms  {mark}\n      {out}")
    ms.sort()
    return {"name": name, "hits": total_hits, "terms": total_terms,
            "clean": clean, "n": len(SET) - failures, "failed": failures,
            "hebrew_left": hebrew_left,
            "p50": ms[len(ms) // 2] if ms else 0, "max": ms[-1] if ms else 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="gemini,groq")
    ap.add_argument("--gemini-models", default="",
                    help="comma list; default [gemini] models")
    args = ap.parse_args()
    want = set(args.only.split(","))
    cfg = config_mod.load_layered()
    t = cfg.translate
    backends = []
    if "gemini" in want:
        backends.append(("gemini", translate.GeminiTranslator(
            [m for m in args.gemini_models.split(",") if m]
            or list(cfg.gemini.models), t.timeout_s, t.target)))
    if "groq" in want:
        backends.append(("groq", translate.GroqTranslator(
            cfg.polish.groq_model, t.timeout_s, t.target)))
    rows = [run(n, b) for n, b in backends]
    print("\nprovider     terms kept   clean sentences   Hebrew left   "
          "failed   p50 ms   max ms")
    for r in rows:
        print(f"{r['name']:<12} {r['hits']:>3}/{r['terms']:<3}      "
              f"{r['clean']:>3}/{r['n']:<3}            {r['hebrew_left']:>3}"
              f"          {r['failed']:>3}   {r['p50']:6.0f}   {r['max']:6.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
