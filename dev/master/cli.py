"""The master app without a window — every screen, the export and the
tick, from a terminal.

The window comes next; this is what makes the whole app provable without
one, and it is what the tests drive.

    python -m dev.master.cli reports
    python -m dev.master.cli data --root C:\\...\\DeskIT
    python -m dev.master.cli tests --no-net
    python -m dev.master.cli export report:mine:20260923-211403 --home %TEMP%\\out
    python -m dev.master.cli tick data:corpus   /   --off

Hebrew in a Windows console needs PYTHONIOENCODING=utf-8; without it the
rows still print, with question marks where the words were.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):                      # run by path, not by -m
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "dev.master"

from . import export as export_mod                 # noqa: E402
from .root import Root                             # noqa: E402
from .sources import SCREENS, rows as screen_rows  # noqa: E402
from .store import Store                           # noqa: E402


def _root(args) -> Root:
    return Root(Path(args.root).resolve()) if args.root else Root.here()


def _store(root: Root, args) -> Store:
    return Store(Path(args.state) if args.state else root.master_state)


def _all_rows(root: Root, store: Store, net: bool) -> list:
    out = []
    for name in SCREENS:
        if name == "home":
            continue
        out += screen_rows(name, root, net=net, store=store)
    return out


def _find(root: Root, store: Store, row_id: str, net: bool):
    for row in _all_rows(root, store, net):
        if row.id == row_id:
            return row
    return None


def _print(rows_: list, as_json: bool) -> None:
    if as_json:
        print(json.dumps([r.to_dict() for r in rows_], ensure_ascii=False, indent=2))
        return
    for row in rows_:
        box = "[x]" if row.ticked else "[ ]"
        when = f"{row.when} {row.when_small}".strip()
        head = f"{box} {when:<16} {row.title}"
        print(head[:150])
        bits = [row.under]
        if row.fig:
            bits.append(f"{row.fig} {row.fig_small}".strip())
        if row.evidence:
            bits.append(" ".join(f"<{e.word}>" for e in row.evidence))
        if row.took:
            bits.append(f"taken to a chat {row.took}")
        line = "    " + "  \u00b7  ".join(b for b in bits if b)
        if line.strip():
            print(line[:150])
        print(f"    id {row.id}")
    print(f"\n{len(rows_)} rows")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="the DeskIT master app, without its window")
    ap.add_argument("what", help="a screen (" + ", ".join(SCREENS) + "), or export / tick / state")
    ap.add_argument("row", nargs="?", help="the row id, for export and tick")
    ap.add_argument("--root", help="the DeskIT checkout to read (default: this one)")
    ap.add_argument("--state", help="where the master keeps its ticks (default: dev/master/state)")
    ap.add_argument("--home", help="where an export lands (default: Desktop\\...\\DeskIT-exports)")
    ap.add_argument("--no-net", action="store_true", help="do not ask GitHub or the server")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--off", action="store_true", help="tick: take the mark off")
    ap.add_argument("--open", action="store_true", help="export: open the folder in Explorer")
    args = ap.parse_args(argv)

    root = _root(args)
    store = _store(root, args)
    net = not args.no_net

    if args.what in SCREENS:
        _print(screen_rows(args.what, root, net=net, store=store), args.json)
        return 0

    if args.what == "state":
        print(json.dumps(store.counts(), indent=2))
        return 0

    if args.what in ("export", "tick"):
        if not args.row:
            print(f"{args.what}: which row? give its id", file=sys.stderr)
            return 2
        if args.what == "tick":
            on = store.tick(args.row, not args.off)
            print(f"{'ticked' if on else 'cleared'} {args.row}")
            return 0
        row = _find(root, store, args.row, net)
        if row is None:
            print(f"no row with id {args.row}", file=sys.stderr)
            return 1
        done = export_mod.take_to_a_chat(
            row, root, store, home=Path(args.home) if args.home else None,
            open_folder=args.open)
        print(done["folder"])
        for f in done["files"]:
            print("  " + f["name"] + ("  (" + f["failed"] + ")" if f.get("failed") else ""))
        print(f"  report.md  ({len(done['document']):,} characters"
              + (", on the clipboard" if done["copied"] else "") + ")")
        return 0

    print(f"no such screen or command: {args.what}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
