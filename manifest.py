"""MANIFEST.sha256 — every file the build put on the disk, and a way to
check they are still the same (DISTRIBUTION_PLAN.md 10.2, 10.3 step 7,
D12 lock 5).

The build (`.github/workflows/release.yml`) writes it over the staged
tree with `python manifest.py write stage`; it ships beside `python\`
and `app\`, and `deskit --verify` (chapter 5 §5.9; `main.py`) reads it
back through `report()` and names every file that changed, went missing
or appeared. One line per file:

    <sha256>  <size>  <path>

sorted by path, the path relative to the tree with forward slashes, the
manifest itself never listed. Standard library only, so the reader runs
inside the shipped tree with nothing installed.

    python manifest.py write <tree> [--out FILE]   # tree/MANIFEST.sha256
    python manifest.py verify <tree> [--manifest FILE]   # exit 1 on a diff
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

NAME = "MANIFEST.sha256"
#: The folders a manifest covers (10.2); anything else beside them
#: (CHANNEL, the uninstaller, the manifest itself) is not listed.
COVERED = ("python", "app")
#: The interpreter's bytecode caches are not files of the build: Python
#: writes them beside every module it imports, on the runner's smoke
#: import and on the person's first start alike, and validates each one
#: against its source's size and mtime before trusting it. Listed, every
#: installed copy would fail its own verify after one run (dry run #6).
SKIPPED_DIRS = ("__pycache__",)
_CHUNK = 1 << 20


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def build(tree: Path, covered=COVERED) -> list[tuple[str, int, str]]:
    """`(sha256, size, relative path)` for every file under the covered
    folders of `tree`, sorted by path."""
    tree = Path(tree)
    rows = []
    for top in covered:
        base = tree / top
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and not any(part in SKIPPED_DIRS for part in path.relative_to(base).parts):
                rel = path.relative_to(tree).as_posix()
                rows.append((sha256_of(path), path.stat().st_size, rel))
    rows.sort(key=lambda r: r[2])
    return rows


def format_rows(rows) -> str:
    return "".join(f"{sha}  {size}  {rel}\n" for sha, size, rel in rows)


def write(tree: Path, out: Path | None = None, covered=COVERED) -> Path:
    tree = Path(tree)
    out = Path(out) if out else tree / NAME
    out.write_text(format_rows(build(tree, covered)), "utf-8", newline="\n")
    return out


def read(path: Path) -> list[tuple[str, int, str]]:
    rows = []
    for n, line in enumerate(Path(path).read_text("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split("  ", 2)
        if len(parts) != 3 or len(parts[0]) != 64 or not parts[1].isdigit():
            raise ValueError(f"{path}:{n}: not a manifest line: {line!r}")
        rows.append((parts[0], int(parts[1]), parts[2]))
    return rows


def verify(tree: Path, manifest: Path | None = None, covered=COVERED) -> list[str]:
    """What differs between the manifest and the tree: one line per file,
    `changed: app/main.py`, `missing: ...`, `extra: ...`. Empty means the
    tree is the build's, byte for byte."""
    tree = Path(tree)
    expected = {rel: (sha, size) for sha, size, rel in
                read(manifest or tree / NAME)}
    actual = {rel: (sha, size) for sha, size, rel in build(tree, covered)}
    problems = []
    for rel in sorted(set(expected) | set(actual)):
        if rel not in actual:
            problems.append(f"missing: {rel}")
        elif rel not in expected:
            problems.append(f"extra: {rel}")
        elif expected[rel] != actual[rel]:
            problems.append(f"changed: {rel}")
    return problems


#: `deskit --verify` on a checkout: there is no manifest, and saying so
#: is not a failure of the tree.
NOT_A_BUILD = 2


def report(root: Path) -> tuple[int, str]:
    """What `deskit --verify` prints and exits with, for an install root
    (the folder that holds `python\\`, `app\\` and the manifest): the
    differences one per line, then the sentence the guide promises —
    "All N files match the manifest" — or the count of differences.
    Exit 0 clean, 1 on any difference, NOT_A_BUILD without a manifest."""
    root = Path(root)
    if not (root / NAME).exists():
        return NOT_A_BUILD, (f"no {NAME} in {root} — this copy is not an "
                             "installed build")
    differences = verify(root)
    listed = len(read(root / NAME))
    tail = (f"All {listed:,} files match the manifest" if not differences
            else f"{len(differences)} difference(s) in {listed:,} files")
    return (1 if differences else 0), "\n".join([*differences, tail])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="write tree/MANIFEST.sha256")
    w.add_argument("tree")
    w.add_argument("--out")
    v = sub.add_parser("verify", help="compare the tree with its manifest")
    v.add_argument("tree")
    v.add_argument("--manifest")
    args = parser.parse_args(argv)
    if args.cmd == "write":
        out = write(Path(args.tree), Path(args.out) if args.out else None)
        print(f"{out}: {len(read(out))} files")
        return 0
    problems = verify(Path(args.tree),
                      Path(args.manifest) if args.manifest else None)
    for line in problems:
        print(line)
    print("verified" if not problems else f"{len(problems)} difference(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
