"""DeskIT's own home for the speech models: the `models-1` release.

The owner's idea, 2026-10-26: every model the app downloads comes from
OUR home — assets of a release of DeskIT-app/DeskIT — and not from
whoever published it first. models.lock names each file by that URL,
its size and its SHA-256 (models.py); this script is the owner's half:

    .venv\\Scripts\\python.exe dev\\models_release.py lock
        rewrite models.lock from the files on this PC (SOURCES), every
        file pointed at the release. Hashes ~5 GB; no network.
    .venv\\Scripts\\python.exe dev\\models_release.py plan      (the default)
        what the release will hold, every file on this PC checked
        against the lock — the exact assets `upload` would send. No
        network.
    .venv\\Scripts\\python.exe dev\\models_release.py upload
        MERGE DAY ONLY, on the owner's yes: `plan` first (any mismatch
        stops it), then the release made if it is not there — a
        PRE-RELEASE that is never "latest", so the updater's
        releases/latest, winget.yml and store.yml never take it for an
        app release — and every asset uploaded that is not there yet at
        its size. Then `check`.
    .venv\\Scripts\\python.exe dev\\models_release.py check [--download]
        the release as GitHub serves it against the lock: every asset
        there at its size; with --download, every model fetched the way
        an installed copy fetches it (models.download through net.py,
        into a scratch folder) and verified by its hashes.

`upload` and `check` speak to GitHub through the `gh` command, signed
in as the owner; nothing here keeps or prints a token.

Where the files are, on the owner's PC (SOURCES): the two models that
came from Hugging Face are the snapshots in his Hugging Face cache at the
commit the lock pins (`--fetch` downloads a missing one there through
huggingface_hub), and the processor's model is the training run's own
CTranslate2 folder. `--from REPO=FOLDER` points one elsewhere.

Credit travels with every copy: in the lock (`credit`), in the release's
notes (written here from the lock), and in THIRD-PARTY-NOTICES.txt
(dev\\notices-extra.txt). The licences, read 2026-10-26: ivrit.ai's model
Apache-2.0, deepdml's conversion MIT, OpenAI's Whisper MIT; the two
datasets night15 was trained on carry the ivrit.ai licence (CC BY 4.0
plus "only for training AI models or academic research", and no
deep-fakes) — a restriction on the DATA, which a trained model is not;
ivrit.ai ship their own model trained on crowd-transcribe-v5 as
Apache-2.0.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))

import hardware                        # noqa: E402
import models                          # noqa: E402

REPO = "DeskIT-app/DeskIT"
CREATE_NO_WINDOW = 0x08000000
TRAINING = Path(r"C:\Users\shimr\Desktop\Organized\Projects\DeskIT-training")


@dataclass(frozen=True)
class Source:
    revision: str
    license: str
    credit: str
    #: the Hub repository it is a copy of ("" for one of ours)
    hub: str = ""
    #: a folder holding it, for one of ours
    folder: Path | None = None


#: Every model the lock names, in the lock's order: the default model
#: first, the English detector, the processor's model.
SOURCES: dict[str, Source] = {
    "ivrit-ai/whisper-large-v3-turbo-ct2": Source(
        revision="72ad623a37947395efcc3933132353790e5a12f5",
        license="apache-2.0",
        credit=("ivrit.ai's Hebrew fine-tune of OpenAI's Whisper large-v3-turbo, "
                "converted for CTranslate2 by ivrit.ai: an unmodified copy of "
                "https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ct2 at commit "
                "72ad623a (Apache-2.0). Whisper (c) 2022 OpenAI, MIT."),
        hub="ivrit-ai/whisper-large-v3-turbo-ct2"),
    "deepdml/faster-whisper-large-v3-turbo-ct2": Source(
        revision="4df90f75321148c3a29a9e2351b7ddf8f5b115a8",
        license="mit",
        credit=("OpenAI's Whisper large-v3-turbo, converted for CTranslate2 by deepdml: "
                "an unmodified copy of https://huggingface.co/deepdml/"
                "faster-whisper-large-v3-turbo-ct2 at commit 4df90f75 (MIT). "
                "Whisper (c) 2022 OpenAI, MIT."),
        hub="deepdml/faster-whisper-large-v3-turbo-ct2"),
    hardware.CPU_MODEL: Source(
        revision="night15-2026-10-26",
        license="apache-2.0",
        credit=("ivrit.ai's whisper-large-v3-turbo (https://huggingface.co/ivrit-ai/"
                "whisper-large-v3-turbo, Apache-2.0; itself a fine-tune of OpenAI's "
                "Whisper large-v3-turbo, (c) 2022 OpenAI, MIT), MODIFIED by DeskIT "
                "(Yoav Shimron, 2026): trained further to be encoded at a recording's "
                "own length (audio-context fine-tuning, after FUTO's whisper-acft) on "
                "ivrit.ai's crowd-transcribe-v5 and knesset-committees datasets "
                "(ivrit.ai licence: CC BY 4.0 with its training-only terms, "
                "https://www.ivrit.ai/en/the-license/), then converted for "
                "CTranslate2 (float16)."),
        folder=TRAINING / "runs" / "night15" / "ct2"),
}


# ------------------------------------------------------------- the files

def hub_cache() -> Path:
    """The owner's Hugging Face cache, where his Dev's models live."""
    home = os.environ.get("HF_HOME")
    if home:
        return Path(home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def folder_of(repo: str, overrides: dict[str, Path]) -> Path:
    if repo in overrides:
        return overrides[repo]
    src = SOURCES[repo]
    if src.folder is not None:
        return src.folder
    return hub_cache() / f"models--{src.hub.replace('/', '--')}" / "snapshots" / src.revision


def fetch(repo: str) -> Path:
    """A Hub-born model's files at the pinned commit, into the owner's
    cache (huggingface_hub, signed in or not — the repositories are
    public). Only for --fetch."""
    from huggingface_hub import snapshot_download
    src = SOURCES[repo]
    return Path(snapshot_download(src.hub, revision=src.revision,
                                  allow_patterns=list(models.WANTED)))


def entry_from_folder(repo: str, folder: Path) -> models.Entry:
    """Every file faster-whisper loads (models.WANTED) in `folder`, sized
    and hashed, as an entry pointed at the release."""
    src = SOURCES[repo]
    files: dict[str, tuple[int, str]] = {}
    for name in models.WANTED:
        path = folder / name
        if path.is_file():
            files[name] = (path.stat().st_size, models.sha256_of(path))
    if "model.bin" not in files:
        raise SystemExit(f"{repo}: no model.bin in {folder}")
    e = models.Entry(repo, src.revision, files, src.license, credit=src.credit)
    return models.at_home(e, models.RELEASE)


def check_files(e: models.Entry, folder: Path) -> list[str]:
    """What is wrong with `folder` against the lock's entry: [] = every
    file there at the lock's size and hash, and every one under GitHub's
    limit."""
    bad = []
    for name, (size, sha) in e.files.items():
        path = folder / name
        if size >= models.ASSET_MAX:
            bad.append(f"{name}: {size} bytes is over GitHub's 2 GiB")
        if not path.is_file():
            bad.append(f"{name}: not in {folder}")
        elif path.stat().st_size != size:
            bad.append(f"{name}: {path.stat().st_size} bytes, the lock says {size}")
        elif models.sha256_of(path) != sha:
            bad.append(f"{name}: the SHA-256 is not the lock's")
    return bad


def release_notes(lock: dict[str, models.Entry], release: str) -> str:
    lines = [
        f"The speech models DeskIT downloads, from its own home ({release}).",
        "",
        "This is not an app release: DeskIT's installer is in the v* releases. "
        "Each file below is named in models.lock by this URL, its size and its "
        "SHA-256, and the app uses none of a model before every file of it matches.",
        "",
    ]
    for e in lock.values():
        lines += [f"### {e.repo}", "",
                  f"Revision {e.revision} · {models.human(e.bytes)} · licence {e.license}", "",
                  e.credit, ""]
    lines += ["The licences' texts: Apache-2.0 https://www.apache.org/licenses/LICENSE-2.0, "
              "MIT (OpenAI's Whisper) https://github.com/openai/whisper/blob/main/LICENSE; "
              "both are also in THIRD-PARTY-NOTICES.txt beside every DeskIT install."]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- github

def gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    done = subprocess.run(["gh", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          creationflags=CREATE_NO_WINDOW)
    if check and done.returncode != 0:
        raise SystemExit(f"gh {' '.join(args[:3])} failed: {done.stderr.strip()}")
    return done


def published(release: str) -> dict | None:
    """The release as GitHub has it ({assets: [{name, size}], isPrerelease}),
    or None when there is none."""
    done = gh("release", "view", release, "--repo", REPO,
              "--json", "assets,isPrerelease,isDraft,tagName", check=False)
    if done.returncode != 0:
        return None
    return json.loads(done.stdout)


# ------------------------------------------------------------- commands

def cmd_lock(args, overrides: dict[str, Path]) -> int:
    entries = []
    for repo in SOURCES:
        folder = folder_of(repo, overrides)
        if not folder.is_dir():
            if args.fetch and SOURCES[repo].hub:
                folder = fetch(repo)
            else:
                raise SystemExit(f"{repo}: {folder} is not here (--fetch, or --from {repo}=FOLDER)")
        e = entry_from_folder(repo, folder)
        too_big = [n for n, (size, _s) in e.files.items() if size >= models.ASSET_MAX]
        if too_big:
            raise SystemExit(f"{repo}: over GitHub's 2 GiB per asset: {too_big}")
        entries.append(e)
        print(f"{repo} @ {e.revision[:18]}: {len(e.files)} files, {models.human(e.bytes)}")
    path = models.write_lock(entries)
    print(f"wrote {path}")
    return 0


def cmd_plan(args, overrides: dict[str, Path]) -> list[tuple[Path, str]]:
    """[(local file, asset name)] — the release's whole content — or
    SystemExit naming every file that does not match the lock."""
    lock = models.read_lock()
    assets: list[tuple[Path, str]] = []
    problems: list[str] = []
    for repo, e in lock.items():
        if repo not in SOURCES:
            problems.append(f"{repo}: in models.lock and not in this script's SOURCES")
            continue
        folder = folder_of(repo, overrides)
        if not folder.is_dir() and args.fetch and SOURCES[repo].hub:
            folder = fetch(repo)
        for name in e.files:
            want = models.HOME + args.release + "/" + models.asset_name(repo, name)
            if e.url(name) != want:
                problems.append(f"{repo} {name}: the lock's URL is {e.url(name)}, "
                                f"not this release's {want}")
            assets.append((folder / name, models.asset_name(repo, name)))
        problems += [f"{repo} {p}" for p in check_files(e, folder)]
        print(f"{repo}: {len(e.files)} files, {models.human(e.bytes)} from {folder}")
    if problems:
        raise SystemExit("not ready:\n  " + "\n  ".join(problems))
    total = sum(p.stat().st_size for p, _n in assets)
    print(f"{len(assets)} assets, {models.human(total)}, every one matching models.lock")
    return assets


def cmd_upload(args, overrides: dict[str, Path]) -> int:
    assets = cmd_plan(args, overrides)
    lock = models.read_lock()
    have = published(args.release)
    if have is None:
        notes = Path(tempfile.mkdtemp(prefix="deskit-models-")) / "notes.md"
        notes.write_text(release_notes(lock, args.release), encoding="utf-8")
        gh("release", "create", args.release, "--repo", REPO, "--target", "main",
           "--title", f"Speech models ({args.release})", "--notes-file", str(notes),
           "--prerelease", "--latest=false")
        print(f"made the release {args.release} (a pre-release, never latest)")
        have = published(args.release) or {"assets": []}
    elif not have.get("isPrerelease"):
        raise SystemExit(f"{args.release} exists and is not a pre-release: winget.yml and "
                         "store.yml would take it for an app release — fix it by hand first")
    there = {a["name"]: int(a.get("size") or 0) for a in have.get("assets") or []}
    stage = Path(tempfile.mkdtemp(prefix="deskit-models-stage-"))
    try:
        for path, name in assets:
            size = path.stat().st_size
            if there.get(name) == size:
                print(f"there already: {name}")
                continue
            if name in there:
                gh("release", "delete-asset", args.release, name, "--repo", REPO, "--yes")
            # the asset takes the FILE's name, so the file is staged under it:
            # a hard link (same volume, no copy) or a copy
            staged = stage / name
            try:
                os.link(path, staged)
            except OSError:
                shutil.copy2(path, staged)
            print(f"uploading {name} ({models.human(size)})…", flush=True)
            gh("release", "upload", args.release, str(staged), "--repo", REPO)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return cmd_check(args, overrides)


def cmd_check(args, overrides: dict[str, Path]) -> int:
    lock = models.read_lock()
    have = published(args.release)
    if have is None:
        print(f"{args.release} is not published")
        return 1
    there = {a["name"]: int(a.get("size") or 0) for a in have.get("assets") or []}
    wrong = []
    for repo, e in lock.items():
        for name, (size, _sha) in e.files.items():
            asset = models.asset_name(repo, name)
            if there.get(asset) != size:
                wrong.append(f"{asset}: {there.get(asset, 'missing')} against {size}")
    if not have.get("isPrerelease"):
        wrong.append(f"{args.release} is not a pre-release")
    if wrong:
        print("the release does not match models.lock:\n  " + "\n  ".join(wrong))
        return 1
    print(f"{args.release}: every asset of models.lock there at its size")
    if not args.download:
        return 0
    import paths
    scratch = Path(tempfile.mkdtemp(prefix="deskit-models-check-"))
    try:
        paths.MODELS_DIR = scratch          # the app's own download, into scratch
        for e in lock.values():
            print(f"downloading {e.repo} as an installed copy would…", flush=True)
            models.download(e)              # raises on any file whose hash is off
            print(f"  verified ({models.human(e.bytes)})")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="DeskIT's models release (models-1).")
    parser.add_argument("command", nargs="?", default="plan",
                        choices=("lock", "plan", "upload", "check"))
    parser.add_argument("--release", default=models.RELEASE)
    parser.add_argument("--from", dest="sources", action="append", default=[],
                        metavar="REPO=FOLDER", help="where one model's files are")
    parser.add_argument("--fetch", action="store_true",
                        help="download a Hub-born model missing from the cache")
    parser.add_argument("--download", action="store_true",
                        help="check: fetch every model the way the app does")
    args = parser.parse_args(argv)
    overrides = {}
    for item in args.sources:
        repo, _, folder = item.partition("=")
        if repo not in SOURCES or not folder:
            parser.error(f"--from {item}: REPO must be one of {', '.join(SOURCES)}")
        overrides[repo] = Path(folder)
    if args.command == "lock":
        return cmd_lock(args, overrides)
    if args.command == "plan":
        cmd_plan(args, overrides)
        return 0
    if args.command == "upload":
        return cmd_upload(args, overrides)
    return cmd_check(args, overrides)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
