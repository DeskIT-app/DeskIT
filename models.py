"""The Hebrew model on disk: downloaded once, with consent, verified,
never bundled (DISTRIBUTION_PLAN.md 6.4, D13).

Until 2026-09-17 the model arrived as a side effect. The first
`WhisperModel(...)` pulled 1.6 GB into the person's global Hugging Face
cache behind a static splash line — no size, no bar, no consent, and a
connection that dropped left a snapshot the next start tried to load,
which is every competitor's top issue (research/competitors). On an
installed copy the transcriber now only LOADS; this module is the one
thing that fetches, and what it fetches is written down.

`models.lock`, beside the code and shipped with it, names each repo the
app may download: the pinned commit, every file with its size and
SHA-256, the licence. The owner writes it (`python models.py --lock`)
from the Hub's own metadata and the files; everyone else reads it. A
revision that changes is a new lock in a new release, never a quiet
re-download, and a repo that is not in it is not downloaded at all.

The download is `net.download()`, file by file — not huggingface_hub's
`snapshot_download`, for one measured reason: hub 1.27 writes every
file to a temp name unique to the process and deletes it on any failure
(`_download_to_tmp_and_move`, its PR #4228), so a 1.6 GB file that
dropped at 90% started from zero at the next attempt, and the
"resumable" D13 promised was not there to lean on. net.download() keeps
`<name>.part`, asks the CDN for the rest with a Range header on the
next attempt (checked live: `206 Partial Content` from the Hub's CDN,
2026-09-17), follows the Hub's redirect by hand so every hop meets the
allowlist and leaves a row in network.log under `model-download`, and
never sends a token — the app has none and the repos need none.

When every file is down, every file is hashed against the lock, and
only then `.complete` is written with the revision inside. `source()`
refuses a folder without it and raises the typed ModelMissing the
loader and main.py understand: no partial snapshot is ever handed to
WhisperModel. `offer()` is the step itself — a steps.StepWindow: the
size and the folder before anything is fetched, [Download] / [Not now],
a bar, [Pause] — the one the wizard of chapter 9 will host.

`env()` is what an installed copy sets before faster_whisper (and with
it huggingface_hub) is imported: HF_HOME under DATA_DIR\\cache\\hf so
the library never writes into the person's global cache, no implicit
token, no telemetry, and HF_HUB_OFFLINE=1 for the whole process — the
loader is given a folder, so nothing of the Hub's is ever needed
online. Portable and developer copies (D4) are untouched: the hub name
goes to WhisperModel as it always did and the global cache serves it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import net
import paths
import steps
from steps import human
from transcribers.base import ModelMissing

log = logging.getLogger("app")

PURPOSE = "model-download"
HUB = "https://huggingface.co"
#: What faster-whisper loads from a model folder (its own allow list);
#: the lock names exactly these, so nothing else is ever fetched.
WANTED = ("config.json", "preprocessor_config.json", "model.bin",
          "tokenizer.json", "vocabulary.json", "vocabulary.txt")
COMPLETE = ".complete"
#: What an installed copy tells huggingface_hub before it is imported.
HUB_ENV: dict[str, str] = {
    "HF_HUB_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
}
_HASH_CHUNK = 1 << 20
STATES = ("ready", "absent", "incomplete", "stale", "unknown", "cache")

#: net.download()'s errors, by the names this module's callers know.
DownloadError = net.DownloadError
Cancelled = net.Cancelled


class VerifyError(DownloadError):
    """A file that did not match the lock: deleted and named."""

    def __init__(self, files: tuple[str, ...]):
        super().__init__("verify", "the download did not match its checksum "
                         f"and was discarded ({', '.join(files)}); try again")
        self.files = files


# ---------------------------------------------------------------- the lock

@dataclass(frozen=True)
class Entry:
    repo: str
    revision: str
    #: name -> (size, sha256), in the lock's order
    files: dict[str, tuple[int, str]] = field(default_factory=dict)
    license: str = ""

    @property
    def bytes(self) -> int:
        return sum(size for size, _sha in self.files.values())

    @property
    def folder(self) -> Path:
        return folder_for(self.repo)

    def url(self, name: str) -> str:
        return f"{HUB}/{self.repo}/resolve/{self.revision}/{name}"


def folder_for(repo: str) -> Path:
    """`models\\ivrit-ai--whisper-large-v3-turbo-ct2`: the Hub's own
    `--` for the slash, one folder per repo, readable in Explorer."""
    return paths.MODELS_DIR / repo.replace("/", "--")


def read_lock(path: Path | None = None) -> dict[str, Entry]:
    """Every entry of models.lock by repo id. A missing or unreadable lock
    is an empty dict — the callers then say "not in models.lock", which
    is the truth and names the file."""
    path = paths.MODELS_LOCK if path is None else path
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as e:
        log.warning("models.lock could not be read (%s)", e)
        return {}
    out: dict[str, Entry] = {}
    for repo, raw in (data.get("models") or {}).items():
        try:
            files = {name: (int(f["size"]), str(f["sha256"]).lower())
                     for name, f in raw["files"].items()}
            out[repo] = Entry(repo, str(raw["revision"]), files,
                              str(raw.get("license") or ""))
        except (KeyError, TypeError, ValueError) as e:
            log.warning("models.lock: the entry for %s is malformed (%s)", repo, e)
    return out


def entry(repo: str, path: Path | None = None) -> Entry | None:
    return read_lock(path).get(repo)


def write_lock(entries: list[Entry], path: Path | None = None) -> Path:
    path = paths.MODELS_LOCK if path is None else path
    data = {
        "_": "The models an installed copy may download (models.py, plan 6.4): "
             "repo, pinned commit, each file's size and SHA-256. Written by "
             "`python models.py --lock`, never by hand.",
        "models": {
            e.repo: {
                "revision": e.revision,
                "license": e.license,
                "bytes": e.bytes,
                "files": {name: {"size": size, "sha256": sha}
                          for name, (size, sha) in e.files.items()},
            }
            for e in entries
        },
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def size_line(e: Entry) -> str:
    """The sentence the step shows BEFORE anything is fetched."""
    return f"{human(e.bytes)} from huggingface.co into {paths.short(e.folder)}"


# --------------------------------------------------------------- the state

def _complete_revision(folder: Path) -> str | None:
    try:
        return str(json.loads((folder / COMPLETE).read_text("utf-8")).get("revision") or "")
    except (OSError, ValueError):
        return None


def state(repo: str, path: Path | None = None) -> str:
    """One of STATES: `ready` (every file verified, revision matches the
    lock), `absent` (nothing on disk), `incomplete` (files but no
    `.complete` — a download that did not finish), `stale` (complete,
    but the lock has moved to another revision), `unknown` (not in the
    lock at all); `cache` on a portable or developer copy, whose model
    is the global Hugging Face cache's and never this module's."""
    if paths.PORTABLE:
        return "cache"
    e = entry(repo, path)
    if e is None:
        return "unknown"
    folder = e.folder
    if not folder.is_dir() or not any(folder.iterdir()):
        return "absent"
    done = _complete_revision(folder)
    if done is None:
        return "incomplete"
    return "ready" if done == e.revision else "stale"


def ready(repo: str, path: Path | None = None) -> bool:
    return state(repo, path) == "ready"


_WHY = {
    "unknown": "{repo} is not in models.lock — DeskIT downloads only the models it ships a lock for",
    "absent": "the Hebrew model is not downloaded yet ({size} from huggingface.co)",
    "incomplete": "the Hebrew model's download did not finish — start DeskIT again to continue it",
    "stale": "the Hebrew model on disk is from an older release — start DeskIT again to update it",
}


def require(repo: str, path: Path | None = None) -> Path:
    """The verified folder, or ModelMissing with the state and a
    sentence. Never a folder without `.complete`."""
    word = state(repo, path)
    if word == "ready":
        return folder_for(repo)
    e = entry(repo, path)
    why = _WHY[word].format(repo=repo, size=human(e.bytes) if e else "?")
    raise ModelMissing(repo, word, why)


def source(repo: str) -> str:
    """What WhisperModel is given for `repo`: the hub name on a portable
    or developer copy (D4 — the global cache, as always), a folder the
    person named themselves, or on an installed copy the verified folder
    — never the name, so the library can only load and never fetch."""
    if paths.PORTABLE or Path(repo).is_dir():
        return repo
    return str(require(repo))


def env() -> dict[str, str]:
    """HUB_ENV plus HF_HOME under the data folder, into this process —
    on an installed copy only, and before faster_whisper is imported
    (huggingface_hub reads these once, at import). Returns what it set;
    {} on a portable or developer copy, where nothing changes."""
    if paths.PORTABLE:
        return {}
    values = dict(HUB_ENV)
    values["HF_HOME"] = str(paths.CACHE_DIR / "hf")
    os.environ.update(values)
    return values


def remove(repo: str) -> bool:
    """The whole folder, parts and all — "Delete the model" on Your data
    and the first half of "Delete and re-download" (6.4)."""
    import shutil

    folder = folder_for(repo)
    if not folder.exists():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return not folder.exists()


# ------------------------------------------------------------ the download

def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify(e: Entry) -> list[str]:
    """The names of the lock's files that are missing, the wrong size
    or the wrong hash — [] when the folder is exactly the lock."""
    bad: list[str] = []
    for name, (size, sha) in e.files.items():
        path = e.folder / name
        try:
            if path.stat().st_size != size or sha256_of(path) != sha:
                bad.append(name)
        except OSError:
            bad.append(name)
    return bad


def _mark_complete(e: Entry) -> None:
    (e.folder / COMPLETE).write_text(json.dumps({
        "repo": e.repo, "revision": e.revision,
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, indent=2) + "\n", encoding="utf-8")


def download(e: Entry, *, progress=None, cancel=None, stage=None) -> Path:
    """Every file of the lock's entry into its folder, resumed where a
    part was left, hashed against the lock, then `.complete`. `progress`
    gets (bytes_done, bytes_total) as they land, `stage` a word
    ("downloading", "verifying"), `cancel` is a threading.Event that
    pauses — the part stays. Raises DownloadError; a file that fails its
    hash is deleted and named, and `.complete` is not written."""
    e.folder.mkdir(parents=True, exist_ok=True)
    (e.folder / COMPLETE).unlink(missing_ok=True)
    total = e.bytes
    base = 0
    if stage is not None:
        stage("downloading")
    for name, (size, _sha) in e.files.items():
        dest = e.folder / name
        if not (dest.exists() and dest.stat().st_size == size):
            net.download(e.url(name), dest, PURPOSE, size=size, progress=progress,
                         cancel=cancel, base=base, total=total)
        base += size
        if progress is not None:
            progress(base, total)
    if stage is not None:
        stage("verifying")
    bad = verify(e)
    if bad:
        for name in bad:
            (e.folder / name).unlink(missing_ok=True)
        log.warning("models: %s did not match models.lock and was deleted: %s",
                    e.repo, ", ".join(bad))
        raise VerifyError(tuple(bad))
    _mark_complete(e)
    log.info("models: %s %s verified in %s", e.repo, e.revision[:12], e.folder)
    return e.folder


# ---------------------------------------------------------------- the step

#: The paragraphs, Hebrew, drawn through ui.draw_text (chapter 9.1).
TEXT = {
    "title": "הורדת המודל העברי",
    "body": ("דסק-איט מתמלל על המחשב הזה, בלי ענן, עם מודל עברי שיורד פעם אחת. "
             "ההורדה היא {size} מהאתר huggingface.co לתיקייה של דסק-איט. "
             "אפשר לעצור באמצע: בפעם הבאה ההורדה תימשך מאותה נקודה."),
    "offline": ("אין חיבור לאינטרנט. דסק-איט צריך להוריד את המודל פעם אחת — "
                "נשאל שוב בהפעלה הבאה, וההורדה תימשך מאותה נקודה."),
    "done": "המודל הורד ונבדק.",
    "name": "Hebrew model",
}

#: The English detector (6.6): the same step with its own words — the
#: wizard offers it on the gpu tier, Settings > The app afterwards.
DETECTOR_TEXT = {
    "title": "זיהוי אנגלית אוטומטי",
    "body": ("מודל שני, כללי, שמזהה כשדיברת אנגלית ומתמלל אותה כמו שהיא. "
             "עוד {size} להורדה ובזיכרון הכרטיס; בלעדיו משפט באנגלית "
             "יוצא בתעתיק עברי. אפשר להוסיף או להסיר אותו אחר כך "
             "בהגדרות > מהירות."),
    "offline": TEXT["offline"],
    "done": "מזהה האנגלית הורד ונבדק.",
    "name": "English detector",
}


def step(e: Entry, downloader=None, words: dict | None = None) -> steps.Step:
    """The model's step: what steps.StepWindow shows and runs. `words`
    picks the detector's sentences for the second repo."""
    words = words or TEXT
    work = downloader or download
    return steps.Step(
        title=words["title"], body=words["body"].format(size=human(e.bytes)),
        size_line=size_line(e), total=e.bytes,
        work=lambda **kw: work(e, **kw),
        said={"offline": words["offline"], "done": words["done"]},
        name=words.get("name", ""),
    )


class Offer(steps.StepWindow):
    """The model's step as a window (steps.StepWindow with models.step)."""

    def __init__(self, e: Entry, downloader=None):
        super().__init__(step(e, downloader))


def wanted(cfg) -> bool:
    """Does this start need the step? An installed copy whose backend is
    the local model and whose model is not ready. Portable and developer
    copies never see it."""
    return (not paths.PORTABLE and cfg.backend == "local"
            and state(cfg.local.model) != "ready")


def offer(repo: str, downloader=None) -> str:
    """The step for `repo`. `done` when the model is verified on disk at
    the end, `later` otherwise; a repo the lock does not know is logged
    and `later`. Never raises: a step that can stop the app from
    starting is worse than no step."""
    e = entry(repo)
    if e is None:
        log.warning("models: %s is not in models.lock — nothing to offer", repo)
        return "later"
    return steps.show(step(e, downloader))


# ------------------------------------------------------------- the owner

def lock_entry(repo: str, revision: str | None = None) -> Entry:
    """The owner's half: the Hub's metadata for `repo` at `revision`
    (main when None). An LFS file's SHA-256 is what the Hub records for
    it; a small file (a few MB at most) is fetched through
    huggingface_hub into the owner's cache and hashed here. The
    revision written is the commit's full sha, never a branch name."""
    from huggingface_hub import HfApi, hf_hub_download

    info = HfApi().model_info(repo, revision=revision, files_metadata=True)
    files: dict[str, tuple[int, str]] = {}
    for sibling in sorted(info.siblings or [], key=lambda s: s.rfilename):
        name = sibling.rfilename
        if name not in WANTED:
            continue
        if sibling.lfs is not None:
            files[name] = (int(sibling.lfs.size or sibling.size or 0), str(sibling.lfs.sha256).lower())
        else:
            local = Path(hf_hub_download(repo, name, revision=info.sha))
            files[name] = (local.stat().st_size, sha256_of(local))
    licence = ""
    try:
        licence = str((info.card_data or {}).get("license") or "")
    except Exception:                                        # noqa: BLE001
        pass
    return Entry(repo, str(info.sha), files, licence)


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="DeskIT's model lock and model folder.")
    parser.add_argument("--lock", nargs="*", metavar="REPO",
                        help="write models.lock from the Hub's metadata for these "
                             "repos (default: the two in defaults.toml)")
    parser.add_argument("--verify", metavar="REPO", help="hash the folder against the lock")
    parser.add_argument("--state", metavar="REPO", help="print the state word")
    args = parser.parse_args(argv)
    if args.lock is not None:
        repos = args.lock
        if not repos:
            import config as config_mod
            cfg = config_mod.load_layered()
            repos = [r for r in (cfg.local.model, cfg.local.english_model) if r]
        entries = [lock_entry(r) for r in repos]
        path = write_lock(entries)
        for e in entries:
            print(f"{e.repo} @ {e.revision[:12]}: {len(e.files)} files, {human(e.bytes)}, {e.license or '?'}")
        print(f"wrote {path}")
        return 0
    if args.verify:
        e = entry(args.verify)
        if e is None:
            print(f"{args.verify} is not in models.lock")
            return 2
        bad = verify(e)
        print("ok" if not bad else "bad: " + ", ".join(bad))
        return 1 if bad else 0
    if args.state:
        print(state(args.state))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main(sys.argv[1:]))
