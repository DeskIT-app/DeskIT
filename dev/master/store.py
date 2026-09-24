"""The master's own two facts about a row, and the only file it writes.

**The tick is his hand and nothing else.** His words, 2026-09-23:
*"תוסיף לי כזה צ'קבוקס שאני אסמן לי, ששום דבר לא יסמן אותו חוץ ממני —
שלא יהיה איזה סימון אוטומטי."* So `tick()` is called from exactly one
place, the box on the row, and no source, no export and no refresh may
call it. There is deliberately no "tick everything", no "tick when
handled", and no rule anywhere that reads a report's server status and
decides for him.

**The ledger is a fact, not a verdict.** Taking a row to a chat writes
one line here — what, when, which folder — so the row can say "taken to
a chat on Tuesday". It never ticks the box.

Both live in `dev\\master\\state\\state.json`, which is the master's own
corner: `problems.json` and every other store of the app stay untouched
(MASTER.md rule 1).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

STAMP = "%Y-%m-%d %H:%M:%S"


class Store:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.path = self.folder / "state.json"
        self._data = self._load()

    # ---- disk ----
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_bytes().decode("utf-8"))
        except (OSError, ValueError):
            data = {}
        data.setdefault("version", 1)
        data.setdefault("ticks", {})     # row id -> {"at"}
        data.setdefault("exports", {})   # row id -> [{"at", "folder"}]
        return data

    def _save(self) -> None:
        """Written whole, through a temporary file beside it: a half-written
        state.json would lose every tick he has made."""
        self.folder.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self._data, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=str(self.folder), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # ---- the tick ----
    def tick(self, row_id: str, on: bool) -> bool:
        """His hand, and only his. Returns the new state."""
        if on:
            self._data["ticks"][row_id] = {"at": time.strftime(STAMP)}
        else:
            self._data["ticks"].pop(row_id, None)
        self._save()
        return on

    def ticked(self, row_id: str) -> bool:
        return row_id in self._data["ticks"]

    # ---- the ledger ----
    def record_export(self, row_id: str, folder: Path) -> None:
        self._data["exports"].setdefault(row_id, []).append(
            {"at": time.strftime(STAMP), "folder": str(folder)})
        self._save()

    def last_export(self, row_id: str) -> dict | None:
        runs = self._data["exports"].get(row_id) or []
        return runs[-1] if runs else None

    # ---- what a screen asks for ----
    def decorate(self, rows: list) -> list:
        """Put the tick and the ledger onto rows a source just built.

        A source never knows about either, which is what keeps the rule
        above easy to hold: there is one function that can tick a row and
        it is not this one.
        """
        for row in rows:
            mark = self._data["ticks"].get(row.id)
            row.ticked = bool(mark)
            row.ticked_at = (mark or {}).get("at", "")
            last = self.last_export(row.id)
            row.took = (last or {}).get("at", "")
            row.took_folder = (last or {}).get("folder", "")
        return rows

    def counts(self) -> dict:
        return {"ticked": len(self._data["ticks"]),
                "exported": len(self._data["exports"])}
