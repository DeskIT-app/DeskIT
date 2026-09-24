"""One row shape for all six screens.

Every screen is a list, every list is rows, and every row can be taken to
a chat — so there is exactly one shape here and no screen invents a
second one. A number with a ceiling (Server, Data) is the same row with
``fig`` and ``pct`` filled in; it is drawn differently and exported
identically.

A row carries everything the document will need (``facts``, ``body``,
``evidence``, ``came_from``). Nothing is fetched again at export time:
what he saw is what he takes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: The five tones the pictures use. Anything else is a bug in a source.
TONES = ("q", "ok", "warn", "bad", "iris")


@dataclass
class Evidence:
    """A file that belongs to a row. ``word`` is what the tag says."""

    kind: str                      # picture | recording | transcript | file
    word: str
    path: Path | None = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "word": self.word,
                "path": str(self.path) if self.path else ""}


@dataclass
class Row:
    """One line on one screen."""

    id: str                        # stable across refreshes: the export ledger and the tick key on it
    screen: str
    title: str
    under: str = ""
    body: str = ""                 # the verbatim words, when the row has any
    body_title: str = "What was reported"   # the heading the document gives the body
    body_from: str = "person"      # person | machine — what the body IS, for the note beside it
    rtl: bool = False              # the title (and the body) read right to left
    tone: str = "q"
    glyph: str = "doc"
    when: str = ""                 # the big word in the time column
    when_small: str = ""
    at: str = ""                   # sortable stamp, never shown
    fig: str = ""                  # a number against a ceiling: Server and Data
    fig_small: str = ""
    pct: int | None = None
    meter_tone: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    facts: dict = field(default_factory=dict)      # label -> value, printed in the document
    came_from: list[str] = field(default_factory=list)
    #: a body that is too expensive to build for a screen nobody exports:
    #: a branch's diff is three git commands, and a list of twenty-five
    #: branches was seventy-five of them before the screen could be drawn.
    #: The export calls this; the window never sees it.
    body_fn: object | None = None
    # filled in by store.decorate(), never by a source
    ticked: bool = False
    ticked_at: str = ""
    took: str = ""                 # when it was last taken to a chat
    took_folder: str = ""

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        d.pop("body_fn", None)             # a function is not something a page is given
        return d

    def words(self) -> str:
        """The body, built now if it was left for the export to build."""
        if self.body.strip() or self.body_fn is None:
            return self.body
        try:
            self.body = str(self.body_fn() or "")
        except Exception as e:             # noqa: BLE001 — a missing body is not a lost export
            self.body = f"(this could not be read: {type(e).__name__}: {e})"
        return self.body


def line(*bits: str) -> str:
    """The second line of a row: the facts, separated the way the
    pictures separate them."""
    return " · ".join(str(b) for b in bits if b not in (None, "", []))
