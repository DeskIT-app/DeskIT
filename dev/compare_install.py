"""Is the installed app the repo at a given commit, byte for byte?

`main.py --verify` proves the installed tree matches the manifest the
build wrote (10.3 step 7). This is the other half of the proof, from the
developer's side: every file under the installed `app\\` hashed against
`git archive <ref>` of this checkout, the exact command release.yml step 6
runs. Identical means a stranger's copy and the developer's are one tree.

    .venv\\Scripts\\python.exe dev\\compare_install.py             # v<VERSION> tag vs the default install
    .venv\\Scripts\\python.exe dev\\compare_install.py --ref HEAD --app dist\\stage

Exit 0 when nothing differs. The build adds one file the archive lacks,
THIRD-PARTY-NOTICES.txt (step 6b), and that one is reported as expected.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED = {"THIRD-PARTY-NOTICES.txt"}       # written by the build, not in git


def archive(ref: str) -> dict[str, str]:
    data = subprocess.run(["git", "archive", "--format=zip", ref], cwd=ROOT,
                          check=True, capture_output=True).stdout
    out: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            out[info.filename.replace("\\", "/")] = hashlib.sha256(z.read(info)).hexdigest()
    return out


def installed(app: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(app):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(app).as_posix()
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    local = os.environ.get("LOCALAPPDATA", "")
    ap.add_argument("--app", type=Path,
                    default=Path(local) / "Programs" / "DeskIT" if local else None,
                    help=r"the install root (holds app\ and python\); default %LOCALAPPDATA%\Programs\DeskIT")
    ap.add_argument("--ref", default=None,
                    help="the git ref to compare against; default v<VERSION> from the install's own VERSION file")
    a = ap.parse_args()
    app_dir = a.app / "app"
    if not app_dir.is_dir():
        print(f"no app\\ under {a.app}", file=sys.stderr)
        return 2
    ref = a.ref or "v" + (app_dir / "VERSION").read_text(encoding="utf-8").strip()

    want = archive(ref)
    have = installed(app_dir)
    only_archive = sorted(set(want) - set(have))
    only_install = sorted(set(have) - set(want))
    differ = sorted(p for p in set(want) & set(have) if want[p] != have[p])
    expected_extra = [p for p in only_install if p in GENERATED]
    only_install = [p for p in only_install if p not in GENERATED]

    print(f"installed app\\: {len(have)} files   git archive {ref}: {len(want)} files")
    for label, rows in (("only in the archive", only_archive),
                        ("only in the install", only_install),
                        ("different bytes", differ)):
        if rows:
            print(f"{label} ({len(rows)}):")
            for p in rows:
                print("   ", p)
    if expected_extra:
        print("build-generated, expected:", ", ".join(expected_extra))
    if only_archive or only_install or differ:
        print("NOT identical")
        return 1
    print(f"Identical: every file under app\\ is {ref}, byte for byte")
    return 0


if __name__ == "__main__":
    sys.exit(main())
