"""The six screens, each one a function that returns rows.

A source READS. It never writes, never ticks a row, and never runs a
command that changes anything — the whole app's contract in one
sentence, and the reason every screen can be tested by pointing it at a
folder of fixtures.
"""
from __future__ import annotations

from . import code, data, home, reports, server, tests

#: the order of the bar
SCREENS = ("home", "reports", "tests", "code", "server", "data")

_NEEDS_NET = {"tests", "code", "server", "home"}


def rows(screen: str, root, *, net: bool = True, store=None) -> list:
    """The rows of one screen, with his ticks and the export ledger on
    them (store.decorate) when a store is given."""
    if screen not in SCREENS:
        raise KeyError(f"no such screen: {screen}")
    module = {"home": home, "reports": reports, "tests": tests,
              "code": code, "server": server, "data": data}[screen]
    out = (module.rows(root, net=net) if screen in _NEEDS_NET
           else module.rows(root))
    if store is not None:
        store.decorate(out)
    return out
