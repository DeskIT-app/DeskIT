"""What the window may ask of the Python side — and nothing else.

`CALLS` is the allowlist webdesk.py's dispatcher checks before it calls
anything here, so the page cannot reach a name that is not on this list;
the object stays FLAT (no attribute of an attribute), because the
dispatcher that pywebview ships getattr's any dotted path it is given.

Six names, and five of them read. The one that writes is `take`, and it
writes outside the repo (export.py). `tick` writes the master's own
state and nothing else — it is here because the box is his hand, and a
click is the only thing that may move it (MASTER.md §6.5).

The screens that ask git, gh or the account are slow (0.3-3 s), so what
a screen answered is kept until the window asks for it again with
`refresh` — the Refresh button in the bar. The cache is per screen and
holds rows, not files.
"""
from __future__ import annotations

import time
from pathlib import Path

from . import export as export_mod
from .root import Root
from .sources import (SCREENS, home as home_src, reports as reports_src,
                      rows as screen_rows)
from .store import Store

FRESH_S = 90.0          # how long a screen's rows stand before they are read again


class Api:
    CALLS = ("rows", "tick", "preview", "take", "open_folder", "ping")

    def __init__(self, root: Root, store: Store, *, home: Path | None = None,
                 net: bool = True) -> None:
        self._root = root
        self._store = store
        self._home = home
        self._net = net
        self._cache: dict[str, tuple[float, list]] = {}
        self._by_id: dict[str, object] = {}

    # ---- the one read the window makes ----

    def rows(self, screen: str, refresh: bool = False) -> dict:
        screen = str(screen)
        if screen not in SCREENS:
            return {"ok": False, "error": f"no such screen: {screen}"}
        pulled = self._pull_reports() if (screen == "reports" and refresh
                                          and self._net) else None
        rows = self._rows(screen, refresh)
        if pulled is not None and not pulled.get("ok"):
            rows = [reports_src.pull_failed(str(pulled.get("why") or "")), *rows]
        self._store.decorate(rows)
        out = {"ok": True, "screen": screen, "read_at": time.strftime("%H:%M"),
               "rows": [r.to_dict() for r in rows]}
        if screen == "home":
            out["counts"] = dict(home_src.home_counts)
        return out

    def _pull_reports(self) -> dict:
        """Refresh on the Reports screen asks dev\\inbox.py to fetch what
        people sent. It runs before the rows are read, so what arrived is
        on the screen in the same press, and the cache is dropped for it."""
        answer = reports_src.pull(self._root)
        self._cache.pop("reports", None)
        return answer

    def _rows(self, screen: str, refresh: bool) -> list:
        hit = self._cache.get(screen)
        if hit and not refresh and (time.monotonic() - hit[0]) < FRESH_S:
            return hit[1]
        rows = screen_rows(screen, self._root, net=self._net)
        self._cache[screen] = (time.monotonic(), rows)
        for row in rows:
            self._by_id[row.id] = row
        return rows

    # ---- his hand ----

    def tick(self, id: str, on: bool) -> dict:
        """The one mark in the app. Nothing else in this file calls it."""
        state = self._store.tick(str(id), bool(on))
        return {"ok": True, "id": id, "ticked": state}

    # ---- the one verb ----

    def preview(self, id: str) -> dict:
        """What the sheet shows before he presses: the folder that WOULD
        be written and the files that would be in it. Writes nothing."""
        row = self._find(str(id))
        if row is None:
            return {"ok": False, "error": "that row is not on any screen now"}
        files = [{"name": _name(e), "word": e.word, "kind": e.kind}
                 for e in row.evidence if e.path and Path(e.path).is_file()]
        folder = export_mod.folder_for(row, self._home)
        return {"ok": True, "id": row.id, "title": row.title,
                "under": row.under, "folder": str(folder),
                "files": [{"name": "report.md", "word": "the row, word for word",
                           "kind": "document"}] + files}

    def take(self, id: str, open: bool = True) -> dict:
        row = self._find(str(id))
        if row is None:
            return {"ok": False, "error": "that row is not on any screen now"}
        done = export_mod.take_to_a_chat(row, self._root, self._store,
                                         home=self._home, open_folder=bool(open))
        done["ok"] = True
        done.pop("document", None)          # the window does not need the text
        return done

    def open_folder(self, path: str) -> dict:
        """Only a folder an export wrote — never any path the page names."""
        import os
        want = Path(str(path)).resolve()
        home = (self._home or export_mod.DEFAULT_HOME).resolve()
        try:
            want.relative_to(home)
        except ValueError:
            return {"ok": False, "error": "not an export folder"}
        if not want.is_dir():
            return {"ok": False, "error": "that folder is not there"}
        os.startfile(str(want))                          # noqa: S606
        return {"ok": True}

    def ping(self) -> dict:
        return {"ok": True, "version": self._root.version()}

    # ---- pieces ----

    def _find(self, row_id: str):
        row = self._by_id.get(row_id)
        if row is not None:
            return row
        screen = {"report": "reports", "tests": "tests", "code": "code",
                  "server": "server", "data": "data"}.get(row_id.split(":", 1)[0])
        if screen is None:
            return None
        for candidate in self._rows(screen, refresh=False):
            if candidate.id == row_id:
                return candidate
        return None


def _name(evidence) -> str:
    plain = {"picture": "shot", "recording": "dictation",
             "transcript": "transcript"}.get(evidence.kind)
    suffix = Path(evidence.path).suffix if evidence.path else ""
    return f"{plain}{suffix}" if plain else Path(evidence.path).name
