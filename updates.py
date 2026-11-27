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

The feed is SIGNED since 2026-11-27 (update_sig.py has the why and the
format): beside it in the release, `latest.json.sig`, an ECDSA P-256
signature over the file's exact bytes, made on the owner's PC with a key
that never touches GitHub (`dev\\sign_release.py --sign`), checked here
against the public half pinned in update_key.py. A feed whose signature
is missing, malformed or wrong is still news — Home's row says the
version is out — but `Release.checked` stays False: it is never
downloaded or installed, and the row says this update could not be
checked and to download it from the website (UNCHECKED_WORDS). If the
key is ever lost, that row is what every copy shows from then on: the
known recovery is the website, and there is nothing else to it.

The download is the installer itself, into DATA_DIR\\tmp\\...part, its
SHA-256 compared with the feed's before the file gets its name back; a
mismatch is deleted and said, never run. Installing is the same
per-user installer the person already ran once, started detached with
11.6's switches after settings.toml is copied to settings.toml.bak; the
app then leaves through its own quit path so the hook, the pipe and the
phone server are free before Restart Manager wants them. Nothing here
writes under APP_DIR: the app downloads, verifies, starts Inno, exits.

Channels: `github` (this module), `winget` (the check runs, the answer
is the one-liner `winget upgrade`: winget installs from its own manifest
and its own SHA-256, so the signature decides nothing there), `store`
(no check at all — the Store updates). The checkout never installs an
update: it pulls.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import re
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
import update_sig
import version

log = logging.getLogger("app")

#: The repository the feed lives in — the public one of D28.
REPO = "DeskIT-app/DeskIT"
API = f"https://api.github.com/repos/{REPO}/releases"
#: The only installer URL a feed may name: one of THIS repository's
#: release assets, the shape release.yml writes (`…/releases/download/
#: v<version>/DeskIT-Setup-<version>.exe`). Until 2026-11-10 any
#: `https://github.com/….exe` passed, so a feed could send every copy to
#: another repository's release (security-local 3, the sceptic's
#: addition). Each segment starts with a letter or a digit, so "." and
#: ".." are not segments, and there is no query, fragment, port or
#: escape for GitHub to read differently. Since 2026-11-27 the feed is
#: also signed (update_sig.py), so even this shape is only believed from
#: a feed whose signature verified.
ASSET_URL = re.compile(r"^https://github\.com/" + re.escape(REPO)
                       + r"/releases/download/[A-Za-z0-9][A-Za-z0-9._+-]{0,99}"
                       r"/[A-Za-z0-9][A-Za-z0-9._+-]{0,199}\.exe\Z")
WINGET_ID = "YoavShimron.DeskIT"
WINGET_COMMAND = f"winget upgrade {WINGET_ID}"
CADENCE_S = 7 * 24 * 3600
#: The first look after a start: late enough that a fresh install is
#: dictating first, early enough to be the same day.
FIRST_DELAY_S = 10 * 60
FEED_NAME = "latest.json"
#: The signature beside it (update_sig.py), uploaded by the owner's
#: `dev\sign_release.py --sign` before he publishes the draft.
SIG_NAME = FEED_NAME + ".sig"
#: Where a person gets a release whose feed did not verify: the site,
#: whose Download button is the latest release's installer.
WEBSITE = paths.PAGES_URL + "/"
#: What every surface says about a release whose feed did not verify —
#: Home's row, the Settings line, a press of an install that is not
#: offered. Plain words (the owner: one plain line per thing).
UNCHECKED_WORDS = ("This update could not be checked, so DeskIT will not install it. "
                   "Download it from the website instead.")
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
    #: True only when the feed's signature verified against the key this
    #: build pins (from_feed). Never read from a file: parse() leaves it
    #: False whatever the feed says, and the cache keeps the feed and its
    #: signature and checks them again on the way back in.
    checked: bool = False
    #: latest.json's exact text as fetched, and latest.json.sig's ("" when
    #: the release had none) — what the cache keeps.
    feed: str = ""
    sig: str = ""

    @classmethod
    def from_feed(cls, body: bytes, sig: bytes | None) -> "Release":
        """The feed as fetched, parsed, and checked against the pinned key.
        A signature that is missing, malformed or wrong does not refuse
        the feed — the version is still news, and Home says so — but the
        release comes back with `checked` False, which download() and
        install() refuse."""
        rel = cls.parse(json.loads(body.decode("utf-8")))
        return dataclasses.replace(rel, checked=not cls.unverified(body, sig),
                                   feed=body.decode("utf-8"),
                                   sig=(sig or b"").decode("ascii", "replace"))

    @staticmethod
    def unverified(body: bytes, sig: bytes | None) -> str:
        """Why the feed's signature does not verify, or "" when it does."""
        try:
            update_sig.verify(body, sig)
        except update_sig.FeedSignatureError as e:
            return str(e) or "it does not verify"
        return ""

    @classmethod
    def parse(cls, data: dict) -> "Release":
        """The feed's schema (11.3), refused loudly when a field is off:
        a wrong file must never become a download. What it returns is
        never `checked`: only from_feed can say that."""
        if not isinstance(data, dict):
            raise ValueError("latest.json is not an object")
        v = str(data.get("version", "")).strip()
        version.parse(v)
        url = str(data.get("url", "")).strip()
        if not ASSET_URL.match(url):
            raise ValueError(f"latest.json url is not one of this repository's "
                             f"release assets: {url!r}")
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
            # the feed and its signature, not the parsed fields: what comes
            # back is checked again (available), so the file cannot say
            # "checked" on its own
            path.write_text(json.dumps({"feed": release.feed, "sig": release.sig}),
                            "utf-8")
    except OSError as e:
        log.debug("updates: cache not written (%s)", e)


def available() -> Release | None:
    """The newer release the last check found, if any — from this
    process's memory or the cache file, never from the network. A cached
    release that is not newer than the copy running now is the one the
    copy before the update found — the file outlives the installer —
    and is dropped rather than shown (the owner's first update, 1.0.0
    -> 1.0.1, 2026-09-21: "1.0.1 is available — you have 1.0.1").
    The cache holds the feed and its signature and both are checked
    again here (measured 2026-11-27: 0.49 ms a read with the check,
    0.17 ms before it; the desk asks every 800 ms); a cache from a build before signed feeds —
    the parsed fields, no "feed" — is dropped, not shown as unchecked:
    the next look writes the new kind."""
    if "release" in _last:
        return _last["release"]
    path = _cache_path()
    if path and path.exists():
        try:
            kept = json.loads(path.read_text("utf-8"))
            if not isinstance(kept, dict) or not isinstance(kept.get("feed"), str) \
                    or not kept["feed"]:
                _remember(None)
                return None
            rel = Release.from_feed(kept["feed"].encode("utf-8"),
                                    str(kept.get("sig") or "").encode("ascii", "replace") or None)
        except (OSError, ValueError, TypeError):
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


def _feed_url(channel: str) -> tuple[str, str] | None:
    """The `latest.json` asset of the release the channel points at and
    the `latest.json.sig` beside it ("" when the release has none — a
    feed that is then never `checked`), or None when there is no feed (a
    repository before its first tag)."""
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
    found = {str(a.get("name")): str(a.get("browser_download_url") or "")
             for a in release.get("assets") or [] if isinstance(a, dict)}
    if not found.get(FEED_NAME):
        return None
    return found[FEED_NAME], found.get(SIG_NAME, "")


def _fetch(url: str, name: str) -> bytes:
    """One file of the release: github.com redirects release assets to
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
            raise UpdateError(f"HTTP {status} fetching {name}")
        return body
    raise UpdateError(f"too many redirects fetching {name}")


def _fetch_feed(url: str, sig_url: str = "") -> Release:
    """The feed and its signature, the feed checked against the pinned
    key over the exact bytes that came off the wire. A release with no
    signature file gives an unchecked release; a signature file the
    release lists that will not come down fails the look quietly, like
    the feed itself — a slow GitHub is no reason to tell anybody that
    an update could not be checked."""
    body = _fetch(url, FEED_NAME)
    sig = _fetch(sig_url, SIG_NAME) if sig_url else None
    return Release.from_feed(body, sig)


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
        urls = _feed_url(settings.channel)
        release = _fetch_feed(*urls) if urls else None
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
    if not release.checked:
        # once a look, only for a version that would have been offered
        log.warning("updates: the feed for DeskIT %s did not verify (%s); it is "
                    "shown and never installed", release.version,
                    Release.unverified(release.feed.encode("utf-8"),
                                       release.sig.encode("ascii", "replace") or None))
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
    if rel is not None and not rel.checked and not s["winget_command"]:
        return (f"DeskIT {rel.version} is out, but this update could not be checked — "
                f"download it from the website")
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
    nothing is executed. A release whose feed did not verify is refused
    before a byte is asked for: its SHA-256 is only the release's word."""
    if not release.checked:
        raise UpdateError(UNCHECKED_WORDS)
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
    if not release.checked:
        raise UpdateError(UNCHECKED_WORDS)
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
                # an unchecked one is a row on Home, never a message that
                # sends the person looking for it: the feed is the only
                # thing that names it, and nothing vouches for the feed
                if release is not None and release.checked and say is not None:
                    say(f"DeskIT {release.version} is available — open the "
                        f"dashboard to install it")
            except Exception:                            # noqa: BLE001
                log.debug("updates: the worker tripped", exc_info=True)
            time.sleep(CADENCE_S)

    t = threading.Thread(target=loop, daemon=True, name="updates")
    t.start()
    return t
