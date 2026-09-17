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

The download is this module's own, through net.py — not
huggingface_hub's `snapshot_download`, for one measured reason: hub
1.27 writes every file to a temp name unique to the process and deletes
it on any failure (`_download_to_tmp_and_move`, its PR #4228), so a
1.6 GB file that dropped at 90% started from zero at the next attempt,
and the "resumable" D13 promised was not there to lean on. Here each
file goes to `<name>.part`, a second attempt asks the CDN for the rest
with a Range header (checked live: `206 Partial Content` from the Hub's
CDN, 2026-09-17), the part is kept on any failure, and the redirect the
Hub answers with is followed by hand so every hop meets net.py's
allowlist and leaves a row in network.log under `model-download`. A
token is never sent — the app has none and the repos need none.

When every file is down, every file is hashed against the lock, and
only then `.complete` is written with the revision inside. `source()`
refuses a folder without it and raises the typed ModelMissing the
loader and main.py understand: no partial snapshot is ever handed to
WhisperModel. `offer()` is the step itself — one window, the size and
the folder before anything is fetched, [Download] / [Not now], a bar,
[Pause] — the one the wizard of chapter 9 will host.

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
import queue
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import net
import paths
from transcribers.base import ModelMissing

log = logging.getLogger("app")

PURPOSE = "model-download"
HUB = "https://huggingface.co"
#: What faster-whisper loads from a model folder (its own allow list);
#: the lock names exactly these, so nothing else is ever fetched.
WANTED = ("config.json", "preprocessor_config.json", "model.bin",
          "tokenizer.json", "vocabulary.json", "vocabulary.txt")
COMPLETE = ".complete"
PART = ".part"
#: What an installed copy tells huggingface_hub before it is imported.
HUB_ENV: dict[str, str] = {
    "HF_HUB_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
}
_CHUNK = 256 * 1024
_HASH_CHUNK = 1 << 20
_MAX_HOPS = 4
_TIMEOUT_S = 60
STATES = ("ready", "absent", "incomplete", "stale", "unknown")


class DownloadError(Exception):
    """The download did not finish. `reason` is one word for the code
    (offline, cancelled, refused, http, short, verify, error); str(e)
    is the line for the log."""

    def __init__(self, reason: str, message: str, files: tuple[str, ...] = ()):
        super().__init__(message)
        self.reason, self.files = reason, files


class Cancelled(DownloadError):
    def __init__(self):
        super().__init__("cancelled", "the download was paused")


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


def human(n: int) -> str:
    """Decimal units, the way the Hub prints them: 1.62 GB, 312 MB."""
    n = int(n)
    if n >= 1_000_000_000:
        return f"{n / 1e9:.2f} GB"
    if n >= 1_000_000:
        return f"{n / 1e6:.0f} MB"
    if n >= 1_000:
        return f"{n / 1e3:.1f} kB"
    return f"{n} B"


def size_line(e: Entry) -> str:
    """The sentence the step shows BEFORE anything is fetched."""
    return f"{human(e.bytes)} from huggingface.co into {e.folder}"


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
    lock at all)."""
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


def _fetch(e: Entry, name: str, size: int, *, base: int, total: int,
           progress=None, cancel=None) -> None:
    """One file into `<name>.part`, from where the last attempt left it.
    `base` is what earlier files add to the bar. The part survives every
    failure; a server that ignores the Range (a 200 to a ranged ask)
    starts the file over."""
    part = e.folder / (name + PART)
    have = part.stat().st_size if part.exists() else 0
    if have >= size:
        part.unlink()
        have = 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    url = e.url(name)
    for _hop in range(_MAX_HOPS):
        try:
            r = net.open("GET", url, PURPOSE, headers=headers, timeout_s=_TIMEOUT_S)
        except net.EgressRefused as err:
            raise DownloadError("refused", str(err)) from err
        except net.NetError as err:
            raise DownloadError("offline", f"no connection to {urllib.parse.urlsplit(url).hostname}: {err}") from err
        with r:
            if r.status in (301, 302, 303, 307, 308):
                where = str(r.headers.get("Location") or "")
                if not where:
                    raise DownloadError("http", f"{name}: a redirect with no Location")
                url = urllib.parse.urljoin(url, where)
                continue
            if r.status == 200:
                mode, have = "wb", 0          # the whole file, asked or not
            elif r.status == 206:
                mode = "ab"
            else:
                raise DownloadError("http", f"{name}: HTTP {r.status} from {urllib.parse.urlsplit(url).hostname}")
            try:
                with part.open(mode) as f:
                    for chunk in r.chunks(_CHUNK):
                        if cancel is not None and cancel.is_set():
                            raise Cancelled()
                        f.write(chunk)
                        have += len(chunk)
                        if progress is not None:
                            progress(base + min(have, size), total)
            except DownloadError:
                raise
            except Exception as err:                        # noqa: BLE001
                # the stream broke under us: the part stays, the next
                # attempt asks for the rest
                raise DownloadError("offline", f"{name}: the connection dropped after "
                                    f"{human(have)} ({err})") from err
            break
    else:
        raise DownloadError("http", f"{name}: too many redirects")
    if have != size:
        raise DownloadError("short", f"{name}: {human(have)} of {human(size)} arrived")
    part.replace(e.folder / name)


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
            _fetch(e, name, size, base=base, total=total, progress=progress, cancel=cancel)
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
        raise DownloadError("verify", "the download did not match its checksum "
                            f"and was discarded ({', '.join(bad)}); try again",
                            tuple(bad))
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
    "failed": "ההורדה נכשלה ({why}). נשאל שוב בהפעלה הבאה.",
    "paused": "ההורדה נעצרה. בהפעלה הבאה היא תימשך מאותה נקודה.",
    "done": "המודל הורד ונבדק.",
}


class Offer:
    """The download step as a window: the size and the folder first,
    [Download] / [Not now], then a bar with bytes, percent and rate and
    [Pause]. Built on ui.py like the wizard. `run()` returns `done`,
    `later` (declined, paused, offline, failed) — never raises."""

    W, H, PAD = 640, 380, 28
    BAR_H = 10

    def __init__(self, e: Entry, downloader=None):
        import tkinter as tk

        import ui

        self._ui = ui
        self.entry = e
        self._download = downloader or download
        self.outcome = "later"
        self._cancel = threading.Event()
        self._events: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._rate = 0.0
        self._last = (0, time.monotonic())
        self._closing = False
        self._after = None
        self.status_text = ""

        # A PhotoImage belongs to the interpreter that made it: this
        # window may follow the dashboard in a test process and precede
        # the wizard in the app's, so the cache is emptied on both sides.
        ui.forget_images()
        self.root = tk.Tk()
        self.root.title("DeskIT")
        self.root.configure(bg=ui.BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._not_now)
        try:
            import dashboard
            dashboard._set_window_icon(self.root)
            dashboard._dark_caption(self.root)
        except Exception:                                    # noqa: BLE001
            pass
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{max(0, (sh - self.H) // 3)}")

        body = tk.Frame(self.root, bg=ui.BG)
        body.pack(fill="both", expand=True, padx=self.PAD, pady=(self.PAD, 0))
        self._para(body, TEXT["title"], pt=17, colour=ui.FG, lines=1)
        self._para(body, TEXT["body"].format(size=human(e.bytes)), pt=10,
                   colour=ui.DIM, lines=5, pady=(6, 14))
        tk.Label(body, text=size_line(e), bg=ui.BG, fg=ui.FAINT, font=(ui.UI, 9),
                 anchor="w", justify="left", wraplength=self.W - 2 * self.PAD).pack(fill="x")
        self.bar = tk.Canvas(body, width=self.W - 2 * self.PAD, height=self.BAR_H,
                             bg=ui.BG, highlightthickness=0, bd=0)
        self.bar.pack(fill="x", pady=(16, 6))
        self._bar_track = self.bar.create_rectangle(0, 0, self.W - 2 * self.PAD, self.BAR_H,
                                                    fill=ui.LINE, outline="")
        self._bar_fill = self.bar.create_rectangle(0, 0, 0, self.BAR_H, fill=ui.ACCENT, outline="")
        self.status = tk.Label(body, text="", bg=ui.BG, fg=ui.DIM, font=(ui.UI, 9), anchor="w")
        self.status.pack(fill="x")
        self.note = tk.Label(body, bg=ui.BG, anchor="e")
        self.note.pack(fill="x", pady=(8, 0))

        foot = tk.Frame(self.root, bg=ui.BG)
        foot.pack(fill="x", padx=self.PAD, pady=self.PAD)
        self.go = ui.Button(foot, "Download", self.start, bg=ui.BG, primary=True, w=150)
        self.go.pack(side="right")
        self.later = ui.Button(foot, "Not now", self._not_now, bg=ui.BG, quiet=True, w=110)
        self.later.pack(side="right", padx=(0, 10))
        self._after = self.root.after(100, self._poll)

    def _para(self, parent, text: str, *, pt: int, colour: str, lines: int,
              pady=(0, 0)):
        import tkinter as tk

        ui = self._ui
        photo, _h, _n = ui.draw_text(text, pt=pt, width=self.W - 2 * self.PAD,
                                     max_lines=lines, colour=colour, bg=ui.BG, rtl=True)
        label = tk.Label(parent, image=photo, bg=ui.BG, anchor="e")
        label.photo = photo
        label.pack(fill="x", pady=pady)
        return label

    def _say(self, text: str, colour: str | None = None) -> None:
        ui = self._ui
        photo, _h, _n = ui.draw_text(text, pt=10, width=self.W - 2 * self.PAD, max_lines=3,
                                     colour=colour or ui.FG, bg=ui.BG, rtl=True)
        self.note.configure(image=photo)
        self.note.photo = photo

    # ------------------------------------------------------------ actions
    def start(self) -> None:
        """[Download]: the transfer on a thread, the window keeps
        painting. Callable from a test as well as from the button."""
        if self._thread is not None:
            return
        self.go.enable(False)
        self.later.configure_text("Pause")
        self._set_status(f"0 B of {human(self.entry.bytes)}")

        def work() -> None:
            try:
                self._download(self.entry, progress=self._progress,
                               cancel=self._cancel, stage=self._stage)
                self._events.put(("done",))
            except DownloadError as err:
                self._events.put(("failed", err.reason, str(err)))
            except Exception as err:                         # noqa: BLE001
                log.warning("models: the download thread tripped", exc_info=True)
                self._events.put(("failed", "error", str(err)))
        self._thread = threading.Thread(target=work, daemon=True, name="model-download")
        self._thread.start()

    def _not_now(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._cancel.set()            # the thread reports "cancelled"
            self.later.enable(False)
            return
        self._finish("later")

    def _progress(self, done: int, total: int) -> None:
        self._events.put(("progress", done, total))

    def _stage(self, word: str) -> None:
        self._events.put(("stage", word))

    # ---------------------------------------------------------------- loop
    def _set_status(self, text: str) -> None:
        self.status_text = text
        self.status.configure(text=text)

    def _draw(self, done: int, total: int) -> None:
        width = self.W - 2 * self.PAD
        frac = min(1.0, done / total) if total else 0.0
        self.bar.coords(self._bar_fill, 0, 0, int(width * frac), self.BAR_H)
        now = time.monotonic()
        last_done, last_at = self._last
        if now - last_at >= 0.5:
            rate = (done - last_done) / (now - last_at)
            self._rate = rate if not self._rate else 0.7 * self._rate + 0.3 * rate
            self._last = (done, now)
        speed = f" — {human(int(self._rate))}/s" if self._rate > 0 else ""
        self._set_status(f"{human(done)} of {human(total)} ({frac * 100:.0f}%){speed}")

    def _poll(self) -> None:
        if self._closing:
            return
        ui = self._ui
        while not self._closing:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            try:
                kind = event[0]
                if kind == "progress":
                    self._draw(event[1], event[2])
                elif kind == "stage" and event[1] == "verifying":
                    self._set_status("Checking the files…")
                elif kind == "done":
                    self._draw(self.entry.bytes, self.entry.bytes)
                    self._set_status(f"{human(self.entry.bytes)} — verified")
                    self._say(TEXT["done"], ui.GREEN)
                    self.root.after(700, lambda: self._finish("done"))
                elif kind == "failed":
                    reason, why = event[1], event[2]
                    self.later.enable(True)
                    self.later.configure_text("Close")
                    if reason == "cancelled":
                        self._set_status("Paused")
                        self._say(TEXT["paused"], ui.DIM)
                    elif reason == "offline":
                        self._set_status("No connection")
                        self._say(TEXT["offline"], ui.AMBER)
                    else:
                        self._set_status("Failed")
                        self._say(TEXT["failed"].format(why=why), ui.RED)
                    log.info("models: the download stopped (%s): %s", reason, why)
                    self._thread = None
                    self._cancel = threading.Event()
            except Exception:                                # noqa: BLE001
                log.debug("models: the window loop tripped", exc_info=True)
        if not self._closing:
            self._after = self.root.after(100, self._poll)

    def _finish(self, outcome: str) -> None:
        if self._closing:
            return
        self._closing = True
        self.outcome = outcome
        try:
            if self._after is not None:
                self.root.after_cancel(self._after)
            self.root.destroy()
        except Exception:                                    # noqa: BLE001
            pass
        self._ui.forget_images()

    def run(self) -> str:
        self.root.mainloop()
        return self.outcome


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
    try:
        return Offer(e, downloader).run()
    except Exception:                                        # noqa: BLE001
        log.warning("models: the download window could not run", exc_info=True)
        return "later"


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
