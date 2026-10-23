"""Said on the web desk — a STUB, until the Said session builds it.

WHAT IT BECOMES. transcripts.log read back: what the Tk desk draws in
Dashboard._screen_said — the search, the filters, SAID_PAGE rows at a
time behind a Show more (Dashboard._said_more), and the other PCs' REMOTE
rows as "from <device>". history.py is the reader both use.
Same sources, same words: the page only draws what this answers.

HOW IT IS REACHED. deskweb.Api.place("said", op, args) is the one caller
(deskweb.PLACES_MOD). The module is imported on the first call, and one
Place is built per window with the window's pipe function (`send`,
control.send's signature: send(verb, timeout_ms=..., **args) -> dict |
None) — a test's or a probe's stubbed pipe arrives the same way. Op
"read" is Place.read(**args); op "act" is Place.act(do, arg). Calls come
on threads of their own: hold a lock, as deskweb.Model does. Answer a
dict with "ok"; {"ok": False, "error": words} is a refusal the page
shows, and an exception reaches the page as its type name only.

WHO OWNS IT. The Said session: this file, web/src/places/said.tsx and
said.css, and the Said section of tests.py (web/README.md).
"""
from __future__ import annotations


class Place:
    """Said, as data, and what its buttons do. One per window."""

    def __init__(self, send) -> None:
        self._send = send

    def read(self, **args) -> dict:
        return {"ok": True, "built": False}

    def act(self, do: str, arg=None) -> dict:
        return {"ok": False,
                "error": f"{str(do)[:40]!r} is not a Said action yet"}
