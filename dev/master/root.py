"""Where the master reads from.

One object holds every path the six screens look at, so a test can point
the whole app at a scratch folder and nothing reaches the owner's real
stores. Nothing here opens a file for writing: the master's only writes
are its own state (``store.py``) and the folders ``export.py`` creates
outside the repo (MASTER.md rules 1 and 2).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path


def read_json(path: Path, default=None, tries: int = 3):
    """Read a JSON file the running app may be rewriting underneath us.

    The app writes ``problems.json`` under a lock this process deliberately
    does not take (taking it would mean creating and locking a file in his
    store). A torn read is therefore possible and is answered the cheap
    way: read again. Three tries, 120 ms apart, then the default.
    """
    for n in range(tries):
        try:
            return json.loads(path.read_bytes().decode("utf-8"))
        except FileNotFoundError:
            return default
        except (ValueError, OSError):
            if n == tries - 1:
                return default
            time.sleep(0.12)
    return default


@dataclass(frozen=True)
class Root:
    """A DeskIT checkout, read-only."""

    dir: Path

    @classmethod
    def here(cls) -> "Root":
        """The checkout this file lives in (dev\\master\\root.py -> ..\\..)."""
        return cls(Path(__file__).resolve().parent.parent.parent)

    # ---- the app's stores, all read-only to us ----
    @property
    def problems(self) -> Path:
        return self.dir / "problems.json"

    @property
    def problems_dir(self) -> Path:
        return self.dir / "problems"

    @property
    def inbox(self) -> Path:
        return self.problems_dir / "inbox"

    @property
    def nightly(self) -> Path:
        return self.problems_dir / "nightly"

    @property
    def corpus(self) -> Path:
        return self.dir / "corpus"

    @property
    def read_aloud(self) -> Path:
        return self.corpus / "read"

    @property
    def recent(self) -> Path:
        return self.dir / "recent"

    @property
    def transcripts(self) -> Path:
        return self.dir / "transcripts.log"

    @property
    def vocab(self) -> Path:
        return self.dir / "vocab.json"

    @property
    def state(self) -> Path:
        return self.dir / "state.json"

    @property
    def defaults(self) -> Path:
        return self.dir / "defaults.toml"

    @property
    def config(self) -> Path:
        return self.dir / "config.toml"

    # ---- the master's own corner, the only place it writes ----
    @property
    def master_state(self) -> Path:
        return self.dir / "dev" / "master" / "state"

    def version(self) -> str:
        """The VERSION file, or "?" — read as text so the master never
        imports the product's modules just to print a number."""
        try:
            return (self.dir / "VERSION").read_text("utf-8").strip() or "?"
        except OSError:
            return "?"

    def setting(self, section: str, key: str, default=None):
        """One value out of config.toml, falling back to defaults.toml.

        A plain-text read, deliberately: ``config.py`` is the product's
        own reader and it writes (it repairs and it stamps). Only the few
        numbers a screen quotes come through here.
        """
        for path in (self.config, self.defaults):
            value = _toml_value(path, section, key)
            if value is not None:
                return value
        return default


def _toml_value(path: Path, section: str, key: str):
    try:
        import tomllib
        data = tomllib.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError, ImportError):
        return None
    return (data.get(section) or {}).get(key)
