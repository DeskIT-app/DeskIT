"""Updates: the weekly look at GitHub Releases, the verified download, and
the installer run again (DISTRIBUTION_PLAN.md 11.3-11.6, D21).

The feed is one file per release, `latest.json`, written by the build
(release.yml step 11) and never by hand: version, the installer's URL,
its SHA-256 and size, the smallest config_version it can migrate from,
the release page. The check is one GET to api.github.com for the latest
release (or the newest pre-release on the beta channel), then one GET for
that file — both through net.py, both rows in network.log, no identifier
of any kind (D12). Once a week, ten minutes after the start that follows
consent; "Check now" on the dashboard ignores the cadence. A version at
or below the running one is recorded and nothing is shown.

The download is the installer itself, into DATA_DIR\\tmp\\...part, its
SHA-256 compared with the feed's before the file gets its name back; a
mismatch is deleted and said, never run. Installing is the same
per-user installer the person already ran once, started detached with
11.6's switches after settings.toml is copied to settings.toml.bak; the
app then leaves through its own quit path so the hook, the pipe and the
phone server are free before Restart Manager wants them. Nothing here
writes under APP_DIR: the app downloads, verifies, starts Inno, exits.

Channels: `github` (this module), `winget` (the check runs, the answer
is the one-liner `winget upgrade`), `store` (no check at all — the
Store updates). The checkout never installs an update: it pulls.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import config as config_mod
import net
import paths
import privacy
import version

log = logging.getLogger("app")

#: The repository the feed lives in — the public one of D28.
REPO = "DeskIT-app/DeskIT"
API = f"https://api.github.com/repos/{REPO}/releases"
WINGET_ID = "YoavShimron.DeskIT"
WINGET_COMMAND = f"winget upgrade {WINGET_ID}"
CADENCE_S = 7 * 24 * 3600
#: The first look after a start: late enough that a fresh install is
#: dictating first, early enough to be the same day.
FIRST_DELAY_S = 10 * 60
FEED_NAME = "latest.json"
#: 11.6, exactly; /VERYSILENT is winget's. /RELAUNCH=1 is the script's
#: own switch ([Run] in DeskIT.iss): the app has left through its quit
#: path before Setup starts, so /RESTARTAPPLICATIONS — Restart Manager
#: reopening what it closed — has nothing of it to reopen, and the
#: owner's first update ended with no window (2026-09-21). Setup opens
#: the app itself when the files are in place.
INSTALL_SWITCHES = ("/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS",
                    "/NORESTART", "/RELAUNCH=1")
_CHUNK = 256 * 1024
_MAX_HOPS = 3


class UpdateError(Exception):
    """Something the person is told about on the card: a checksum that did
    not match, a download that broke. Never raised for a quiet failure
    of the weekly check — those are one debug line."""


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    sha256: str
    size: int
    min_config_version: int
    notes_url: str
    published: str = ""

    @classmethod
    def parse(cls, data: dict) -> "Release":
        """The feed's schema (11.3), refused loudly when a field is off:
        a wrong file must never become a download."""
        if not isinstance(data, dict):
            raise ValueError("latest.json is not an object")
        v = str(data.get("version", "")).strip()
        version.parse(v)
        url = str(data.get("url", "")).strip()
        if not url.startswith("https://github.com/") or not url.endswith(".exe"):
            raise ValueError(f"latest.json url is not a GitHub release asset: {url!r}")
        sha = str(data.get("sha256", "")).strip().lower()
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("latest.json sha256 is not 64 hex")
        size = int(data.get("size", 0))
        if size <= 0:
            raise ValueError("latest.json size is not positive")
        notes = str(data.get("notes_url", "")).strip()
        if not notes.startswith("https://github.com/"):
            raise ValueError("latest.json notes_url is not on GitHub")
        return cls(v, url, sha, size, int(data.get("min_config_version", 1) or 1),
                   notes, str(data.get("published", "") or ""))

    def newer_than(self, running: str) -> bool:
        return version.key(self.version) > version.key(running)


# ------------------------------------------------------------- the state

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _state() -> dict:
    try:
        return config_mod.read_state(paths.STATE_FILE)
    except Exception:                                    # noqa: BLE001
        return {}


def _record(**values) -> None:
    try:
        config_mod.save(values)
    except Exception as e:                               # noqa: BLE001
        log.debug("updates: state not written (%s)", e)


def _settings():
    try:
        return config_mod.load_layered().updates
    except Exception:                                    # noqa: BLE001
        return config_mod.UpdatesConfig()


def _cache_path() -> Path | None:
    """Where the last feed seen is kept for the dashboard's row: the
    cache folder when the layout has one; the checkout has none and
    keeps it in memory."""
    return paths.CACHE_DIR / FEED_NAME if paths.CACHE_DIR.is_dir() else None


_last: dict = {}


def _remember(release: Release | None) -> None:
    _last["release"] = release
    path = _cache_path()
    if path is None:
        return
    try:
        if release is None:
            if path.exists():
                path.unlink()
        else:
            path.write_text(json.dumps(release.__dict__), "utf-8")
    except OSError as e:
        log.debug("updates: cache not written (%s)", e)


def available() -> Release | None:
    """The newer release the last check found, if any — from this
    process's memory or the cache file, never from the network. A cached
    release that is not newer than the copy running now is the one the
    copy before the update found — the file outlives the installer —
    and is dropped rather than shown (the owner's first update, 1.0.0
    -> 1.0.1, 2026-09-21: "1.0.1 is available — you have 1.0.1")."""
    if "release" in _last:
        return _last["release"]
    path = _cache_path()
    if path and path.exists():
        try:
            rel = Release.parse(json.loads(path.read_text("utf-8")))
        except (OSError, ValueError):
            return None
        if not rel.newer_than(version.VERSION):
            _remember(None)
            return None
        return rel
    return None


def due(now: float | None = None) -> bool:
    """Whether a week has passed since `updates.last_check`."""
    last = str(_state().get("updates.last_check") or "")
    if not last:
        return True
    try:
        then = time.mktime(time.strptime(last, "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return True
    return (now if now is not None else time.time()) - then >= CADENCE_S


def mode() -> str:
    """Why a check would or would not run: `store`, `off`, `offline`,
    `winget` or `github`."""
    if paths.CHANNEL == "store":
        return "store"
    if not privacy.allowed("update_check"):
        return "off"
    if privacy.offline():
        return "offline"
    return "winget" if paths.CHANNEL == "winget" else "github"


# ------------------------------------------------------------- the check

def _get_json(url: str) -> object:
    status, _headers, body = net.request(
        "GET", url, "update-check",
        headers={"Accept": "application/vnd.github+json"}, timeout_s=20)
    if status != 200:
        raise UpdateError(f"HTTP {status} from {url.split('/repos/')[0]}")
    return json.loads(body.decode("utf-8"))


def _feed_url(channel: str) -> str | None:
    """The `latest.json` asset of the release the channel points at, or
    None when there is no release (a repository before its first tag)."""
    if channel == "beta":
        releases = _get_json(f"{API}?per_page=5")
        candidates = [r for r in releases if isinstance(r, dict)
                      and r.get("prerelease")] if isinstance(releases, list) else []
        release = candidates[0] if candidates else None
    else:
        try:
            release = _get_json(f"{API}/latest")
        except UpdateError as e:
            if "HTTP 404" in str(e):
                return None
            raise
    if not isinstance(release, dict):
        return None
    for asset in release.get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") == FEED_NAME:
            return str(asset.get("browser_download_url") or "")
    return None


def _fetch_feed(url: str) -> Release:
    """The feed file itself: github.com redirects release assets to
    objects.githubusercontent.com, and net.py follows nothing, so the
    hop is taken here — each host checked against the allowlist by
    net.py in its turn."""
    for _ in range(_MAX_HOPS):
        status, headers, body = net.request("GET", url, "update-check",
                                            timeout_s=20)
        if status in (301, 302, 303, 307, 308):
            url = str(headers.get("Location") or "")
            if not url:
                raise UpdateError("a redirect with no Location")
            continue
        if status != 200:
            raise UpdateError(f"HTTP {status} fetching {FEED_NAME}")
        return Release.parse(json.loads(body.decode("utf-8")))
    raise UpdateError("too many redirects fetching the feed")


def check(*, force: bool = False, now: float | None = None) -> Release | None:
    """One look. Returns the newer release when there is one; None
    otherwise. Quiet on every failure — one debug line — because the
    next try is a week away and nothing the person can do about GitHub
    being slow belongs on a card. No version is ever skipped by choice:
    every copy is offered the same, latest one (the owner, 2026-09-21:
    "everyone on the same version — we are not at the stage of letting
    people choose")."""
    m = mode()
    if m in ("store", "off", "offline"):
        return None
    if not force and not due(now):
        return available()
    settings = _settings()
    try:
        url = _feed_url(settings.channel)
        release = _fetch_feed(url) if url else None
    except (UpdateError, net.NetError, net.EgressRefused, ValueError,
            OSError) as e:
        log.debug("updates: the check did not complete (%s)", e)
        return available()
    _record(**{"updates.last_check": _now_iso(),
               "updates.latest_seen": release.version if release else ""})
    if release is None or not release.newer_than(version.VERSION):
        _remember(None)
        return None
    log.info("updates: DeskIT %s is available (running %s)", release.version,
             version.VERSION)
    _remember(release)
    return release


def status() -> dict:
    """What the dashboard's row says."""
    state = _state()
    rel = available()
    return {"mode": mode(), "last_check": str(state.get("updates.last_check") or ""),
            "latest_seen": str(state.get("updates.latest_seen") or ""),
            "available": rel, "running": version.VERSION,
            "winget_command": WINGET_COMMAND if paths.CHANNEL == "winget" else ""}


def status_line() -> str:
    s = status()
    if s["mode"] == "store":
        return "Updates come from the Microsoft Store"
    if s["mode"] == "off":
        return "The weekly check is off"
    if s["mode"] == "offline":
        return "Paused while Offline mode is on"
    rel = s["available"]
    if rel is not None:
        mb = rel.size / 1_048_576
        when = f", {rel.published[:10]}" if rel.published else ""
        return f"DeskIT {rel.version} is out ({mb:.0f} MB{when}) — you have {s['running']}"
    if s["last_check"]:
        return f"You have the newest version. Last looked {s['last_check'][:10]}."
    return "Not looked yet"


# ---------------------------------------------------------- the download

def download(release: Release, on_progress=None, cancel=None,
             dest_dir: Path | None = None) -> Path:
    """The installer into <tmp>\\DeskIT-Setup-<version>.exe.part, verified
    against the feed's SHA-256, then renamed. Progress as (done, total)
    bytes; `cancel()` true stops it and removes the part file. A checksum
    mismatch deletes the file, logs both digests and raises UpdateError —
    nothing is executed."""
    dest_dir = Path(dest_dir) if dest_dir else paths.TMP_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / f"DeskIT-Setup-{release.version}.exe"
    part = final.with_name(final.name + ".part")
    url = release.url
    digest = hashlib.sha256()
    done = 0
    try:
        for _ in range(_MAX_HOPS):
            with net.open("GET", url, "update-download", timeout_s=60) as r:
                if r.status in (301, 302, 303, 307, 308):
                    url = str(r.headers.get("Location") or "")
                    if not url:
                        raise UpdateError("a redirect with no Location")
                    continue
                if r.status != 200:
                    raise UpdateError(f"HTTP {r.status} downloading the installer")
                with part.open("wb") as f:
                    for chunk in r.chunks(_CHUNK):
                        if cancel is not None and cancel():
                            raise UpdateError("cancelled")
                        f.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        if on_progress is not None:
                            on_progress(done, release.size)
                break
        else:
            raise UpdateError("too many redirects downloading the installer")
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    got = digest.hexdigest()
    if got != release.sha256:
        try:
            part.unlink()
        except OSError:
            pass
        log.warning("updates: the download did not match its checksum and "
                    "was discarded (got %s, feed says %s)", got, release.sha256)
        raise UpdateError("The download did not match its checksum and was "
                          "discarded. Try again or download from the release "
                          "page.")
    if final.exists():
        final.unlink()
    part.rename(final)
    return final


# ------------------------------------------------------------ the install

def install_command(installer: Path, release_version: str) -> list[str]:
    """The exact argument list of 11.6. The log path carries no quotes
    of its own: Popen quotes an argument that needs it, and a quote
    written into the argument reaches Inno as a literal backslash-quote
    — `/LOG=\\"C:\\...\\setup-1.0.1.log\\"` — which Inno's own parser
    turns into the path `\\C:\\...\\setup-1.0.1.log\\` and refuses with
    "Error creating log file" before installing anything (the owner's
    first press of Download and install, 1.0.0 -> 1.0.1, 2026-09-21)."""
    log_path = paths.LOGS_DIR / f"setup-{release_version}.log"
    return [str(installer), *INSTALL_SWITCHES, f"/LOG={log_path}"]


def install(installer: Path, release: Release, quit_app=None) -> list[str]:
    """Copy settings.toml to settings.toml.bak, start the installer
    detached, then ask the app to leave through its own quit path. The
    checkout refuses: it updates with git, and an installer over it would
    be a second copy in the wrong place — and so does the stranger's copy
    of it (paths.STRANGER), whose installer would land on the real
    install. The card, the download and its checksum run as they would."""
    if paths.DEVELOPER or paths.STRANGER:
        raise UpdateError("this is the checkout — it updates with git pull")
    if not installer.exists():
        raise UpdateError("the downloaded installer is gone")
    try:
        if paths.SETTINGS_FILE.exists():
            shutil.copy2(paths.SETTINGS_FILE,
                         paths.SETTINGS_FILE.with_suffix(".toml.bak"))
    except OSError as e:
        log.warning("updates: settings.toml.bak not written (%s)", e)
    argv = install_command(installer, release.version)
    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _record(**{"updates.installed_version": version.VERSION})
    subprocess.Popen(argv, cwd=str(installer.parent),
                     creationflags=0x00000008 | 0x00000200,   # detached, own group
                     close_fds=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log.info("updates: installing DeskIT %s — the app closes now and "
             "reopens after", release.version)
    if quit_app is not None:
        quit_app()
    return argv


def after_update() -> str | None:
    """At start: the first run after an update says so once, and the
    release the copy before it found — the one just installed — is
    forgotten, so no row offers it again."""
    state = _state()
    before = str(state.get("updates.installed_version") or "")
    if not before or before == version.VERSION:
        return None
    _record(**{"updates.installed_version": version.VERSION})
    _remember(None)
    if version.key(version.VERSION) > version.key(before):
        return f"Updated to DeskIT {version.VERSION}"
    return None


# ------------------------------------------------------------- the timer

def start_worker(say=None) -> threading.Thread | None:
    """The app's weekly look: first FIRST_DELAY_S after start, then every
    CADENCE_S while it runs. Nothing in the checkout, the Store build or
    with the switch off; the dashboard's Check now is separate."""
    if paths.DEVELOPER or mode() in ("store", "off"):
        return None

    def loop() -> None:
        time.sleep(FIRST_DELAY_S)
        while True:
            try:
                release = check()
                if release is not None and say is not None:
                    say(f"DeskIT {release.version} is available — open the "
                        f"dashboard to install it")
            except Exception:                            # noqa: BLE001
                log.debug("updates: the worker tripped", exc_info=True)
            time.sleep(CADENCE_S)

    t = threading.Thread(target=loop, daemon=True, name="updates")
    t.start()
    return t
