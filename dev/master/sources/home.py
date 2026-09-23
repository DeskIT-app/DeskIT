"""Home: what wants his eye today, and nothing else.

Every line here is a row another screen already built — the same id, so a
tick he makes on Home is the same tick on the screen it came from, and an
export from either is one line in the ledger.

**Only the newest of a thing.** Four nights that failed a week ago are
not four things to look at today: the nights are read newest first and
exactly one of them reaches Home. The same for the CI (the newest run of
a branch) and for a release (only a draft still waiting).
"""
from __future__ import annotations

from . import code as code_src
from . import data as data_src
from . import reports as reports_src
from . import server as server_src
from . import tests as tests_src

PILE = 7                    # the rows the pictures show before the list scrolls
RANK = {"bad": 0, "warn": 1, "iris": 2, "ok": 3, "q": 3}

#: what the column beside the pile says. Filled by rows(); the window
#: reads it right after asking for Home.
home_counts: dict = {}


def rows(root, *, net: bool = True) -> list:
    picked: list = []
    counts: dict = {}

    reports = reports_src.rows(root)
    open_ones = [r for r in reports if "closed" not in r.under and "fixed" not in r.under]
    counts["reports"] = {"n": len(open_ones), "word": "open"}
    picked += open_ones[:3]

    tests = tests_src.rows(root, net=net)
    nights = [r for r in tests if r.id.startswith("tests:night")
              or r.id.startswith("tests:clean")]
    ci = [r for r in tests if r.id.startswith("tests:ci")]
    counts["tests"] = _tests_count(nights)
    picked += nights[:1]                       # the newest night, whatever it says
    picked += [r for r in ci if r.tone != "ok"][:2]

    code = code_src.rows(root, net=net)
    branches = [r for r in code if r.id.startswith("code:branch")]
    counts["code"] = {"n": len(branches), "word": "branches"}
    picked += [r for r in branches if r.tone == "warn"][:2]
    picked += [r for r in code if r.id.startswith("code:release") and r.tone == "warn"][:1]

    data = data_src.rows(root)
    counts["data"] = _data_count(data)
    picked += [r for r in data if r.tone == "warn"][:1]
    picked += [r for r in data
               if (r.pct or 0) >= 80 and r.meter_tone not in ("", "ok")][:1]

    if net:
        server = server_src.rows(root, net=net)
        counts["server"] = _server_count(server)
        picked += [r for r in server if r.tone == "warn"][:1]

    seen, out = set(), []
    for row in picked:
        if row.id in seen:
            continue
        seen.add(row.id)
        out.append(row)
    out.sort(key=lambda r: (RANK.get(r.tone, 3), -_key(r.at)))
    home_counts.clear()
    home_counts.update(counts)
    return out[:PILE]


def _key(at: str) -> float:
    digits = "".join(ch for ch in str(at) if ch.isdigit())
    return float(digits[:14] or 0)


def _tests_count(nights: list) -> dict:
    if not nights:
        return {"n": 0, "word": "nights"}
    newest = nights[0]
    if newest.tone == "bad":
        return {"n": newest.facts.get("Real failures", "").count(",") + 1,
                "word": "failed last night"}
    run = next((r for r in nights if r.id.startswith("tests:clean")), None)
    nights_clean = (run.facts.get("Nights", 1) + 1) if run is not None else 1
    return {"n": nights_clean, "word": "clean nights"}


def _data_count(rows_: list) -> dict:
    corpus = next((r for r in rows_ if r.id == "data:corpus"), None)
    if corpus is None:
        return {"n": 0, "word": "clips"}
    return {"n": corpus.fig, "word": corpus.fig_small}


def _server_count(rows_: list) -> dict:
    if any(r.id == "server:offline" for r in rows_):
        return {"n": "—", "word": "not read"}
    rows_n = [r for r in rows_ if r.id.startswith("server:") and r.fig.replace(",", "").isdigit()]
    total = sum(int(r.fig.replace(",", "")) for r in rows_n)
    return {"n": f"{total:,}", "word": "rows in all"}
