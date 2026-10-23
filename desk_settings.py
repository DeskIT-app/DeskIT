"""Settings on the web desk — a STUB, until the Settings session builds
it.

WHAT IT BECOMES. The lines a person changes, on eight tabs: what the Tk
desk draws in Dashboard._screen_settings and Dashboard._settings_go —
settings.TABS names every drawn line with its plain words,
Dashboard.LAYOUT says what each tab draws and in what order, and every
write goes through config.set_values (the line editor that keeps the
comments) or the running app (main.set_option), never a TOML round trip.
Privacy carries blocks of their own (Dashboard._keys_block — the cloud
keys — and Dashboard._said_file_block). A tab is the route's sub:
#/settings/privacy.
Same sources, same words: the page only draws what this answers.

HOW IT IS REACHED. deskweb.Api.place("settings", op, args) is the one
caller (deskweb.PLACES_MOD). The module is imported on the first call, and one
Place is built per window with the window's pipe function (`send`,
control.send's signature: send(verb, timeout_ms=..., **args) -> dict |
None) — a test's or a probe's stubbed pipe arrives the same way. Op
"read" is Place.read(**args); op "act" is Place.act(do, arg). Calls come
on threads of their own: hold a lock, as deskweb.Model does. Answer a
dict with "ok"; {"ok": False, "error": words} is a refusal the page
shows, and an exception reaches the page as its type name only.

WHO OWNS IT. The Settings session: this file,
web/src/places/settings.tsx and settings.css, and the Settings section
of tests.py (web/README.md).
"""
from __future__ import annotations


class Place:
    """Settings, as data, and what its buttons do. One per window."""

    def __init__(self, send) -> None:
        self._send = send

    def read(self, **args) -> dict:
        return {"ok": True, "built": False}

    def act(self, do: str, arg=None) -> dict:
        return {"ok": False,
                "error": f"{str(do)[:40]!r} is not a Settings action yet"}
