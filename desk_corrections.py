"""Corrections on the web desk — a STUB, until the Corrections session
builds it.

WHAT IT BECOMES. Every pending proposal of the second reading, with the
vocabulary beside it: what the Tk desk draws in
Dashboard._screen_corrections — the proposal rows are the Home pile's
rows with the pile's two answers (review.json, review.Store.decide), and
the Words tab (CORR_TABS) is vocab.json through the app's `vocab`
control verb (learn_by_hand, edit, forget, the Use them switch).
Same sources, same words: the page only draws what this answers.

HOW IT IS REACHED. deskweb.Api.place("corrections", op, args) is the one
caller (deskweb.PLACES_MOD). The module is imported on the first call,
and one Place is built per window with the window's pipe function
(`send`, control.send's signature: send(verb, timeout_ms=..., **args) ->
dict | None) — a test's or a probe's stubbed pipe arrives the same way.
Op "read" is Place.read(**args); op "act" is Place.act(do, arg). Calls
come on threads of their own: hold a lock, as deskweb.Model does. Answer
a dict with "ok"; {"ok": False, "error": words} is a refusal the page
shows, and an exception reaches the page as its type name only.
Everything that comes from the page (do, arg, read's args) is untrusted:
allowlist do, check every argument before it reaches a file path, a
process, a URL, a pipe verb or a consent, and answer a failure with the
exception's type, never its text.

WHO OWNS IT. The Corrections session: this file,
web/src/places/corrections.tsx and corrections.css, and the Corrections
section of tests.py (web/README.md).
"""
from __future__ import annotations


class Place:
    """Corrections, as data, and what its buttons do. One per window."""

    def __init__(self, send) -> None:
        self._send = send

    def read(self, **args) -> dict:
        return {"ok": True, "built": False}

    def act(self, do: str, arg=None) -> dict:
        return {"ok": False,
                "error": f"{str(do)[:40]!r} is not a Corrections action yet"}
