"""Where the app's files live: the code in one place, a person's data in another.

Until 2026-09-17 every store the app owns — the vocabulary it learned, the
recordings it kept, the transcript history, the bug list, the phone token,
the API keys — sat BESIDE THE CODE, because the only copy of the app was
the owner's own checkout and that folder was both the program and the
person. That cannot survive a second user: an installed program lives in
a folder it may not write to, two Windows accounts on one PC would share
one history, and an update that replaces the program folder would take
the vocabulary with it. DISTRIBUTION_PLAN.md chapters 1-4 hold the whole
argument; decisions D1, D4, D5 and D30 are what this module implements.

So there are two roots, resolved ONCE at import, and every module that
used to build a store path from its own ``Path(__file__)`` asks here
instead:

``APP_DIR``
    The folder holding ``main.py``: code, ``fonts\\``, ``skin\\``, the
    icon, and ``defaults.toml`` — the tracked configuration document.
    Read-only once installed. A person's own changes go to
    ``settings.toml`` and ``state.json`` in ``DATA_DIR`` (config.py,
    "the three layers"); ``LEGACY_CONFIG`` is only where ``--migrate``
    looks for a pre-2026-09-17 ``config.toml``.

``DATA_DIR``
    Everything personal. ``%LOCALAPPDATA%\\DeskIT`` for an installed copy
    — one folder to find, one folder to delete, and it never roams to a
    company server the way ``%APPDATA%`` would.

PORTABLE MODE IS THE OWNER'S MACHINE, UNCHANGED. If any of these holds —
``DESKIT_PORTABLE=1`` in the environment, a ``portable.txt`` beside
``main.py``, or a ``.git`` beside ``main.py`` — then ``DATA_DIR`` IS
``APP_DIR`` and every named path below resolves to exactly the file it
resolved to before this module existed: ``recent\\`` stays ``recent\\``,
``transcripts.log`` stays in the folder, ``.env`` keeps supplying keys.
Nothing moves on its own; ``deskit --migrate`` (chapter 3.8, a later
commit) is the only thing that ever carries data across, and only when
asked. The checkout is also "DeskIT Dev" (D30): the same code with a
``dev`` mark on its kernel names, so the released copy and this one can
be installed side by side.

The installed layout groups the stores so a person can read the folder:
``audio\\`` for the recordings, ``logs\\`` for the logs, ``phone\\`` for the
pairing, ``secrets\\`` for DPAPI blobs, ``cache\\`` and ``tmp\\`` for what
may be deleted at any time. The portable layout keeps the flat names.
Both are listed side by side in ``_LAYOUTS`` below, which is the one place
the difference lives.

``DESKIT_HOME`` is the test hatch: it points ``DATA_DIR`` at a folder of
the tester's choosing with the INSTALLED layout, so the product suite can
exercise that layout without touching anyone's real data folder.

Nothing here creates a folder at import. ``ensure()`` does, and ``main.py``
calls it before the first log line, so ``app.log`` never meets a folder
that is not there.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

#: The checkout. ``.git`` is a folder in a normal clone and a FILE in a git
#: worktree; ``exists()`` answers both, ``is_dir()`` would not.
DEVELOPER: bool = (APP_DIR / ".git").exists()

#: Today's layout, beside the code. DEVELOPER implies PORTABLE (D4); the
#: reverse is not true — a copy run from a USB stick is portable without
#: any owner-only surface.
PORTABLE: bool = (
    os.environ.get("DESKIT_PORTABLE", "").strip() == "1"
    or (APP_DIR / "portable.txt").exists()
    or DEVELOPER
)

_HOME_OVERRIDE = os.environ.get("DESKIT_HOME", "").strip()

if _HOME_OVERRIDE:
    DATA_DIR = Path(_HOME_OVERRIDE).expanduser().resolve()
    _LAYOUT = "installed"
elif PORTABLE:
    DATA_DIR = APP_DIR
    _LAYOUT = "portable"
else:
    _local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    DATA_DIR = Path(_local) / "DeskIT"
    _LAYOUT = "installed"

#: Whether the flat beside-the-code names are in use. Read by the few
#: places that must know (the migrate command, the Files card).
FLAT: bool = _LAYOUT == "portable"

#: The checkout's OWN data, beside its code: the owner's transcripts,
#: recordings and read-aloud pairs — training data for the Hebrew model,
#: never pruned and never reset (migrate.TRAINING_DATA, history.apply).
#: False under DESKIT_HOME, so a test's scratch folder is ordinary data.
OWNER_DATA: bool = DEVELOPER and FLAT

# name -> (portable relative path, installed relative path), both under
# DATA_DIR. The left column is what the app wrote before 2026-09-17, so
# the owner's checkout keeps every file where it is (D4).
_LAYOUTS: dict[str, tuple[str, str]] = {
    "LEGACY_CONFIG":   ("config.toml",        "config.toml"),
    "SETTINGS_FILE":   ("settings.toml",      "settings.toml"),
    "STATE_FILE":      ("state.json",         "state.json"),
    "CONSENT_FILE":    ("consent.json",       "consent.json"),
    "SETUP_MARKER":    (".setup-done",        ".setup-done"),
    "VOCAB_FILE":      ("vocab.json",         "vocab.json"),
    "REVIEW_FILE":     ("review.json",        "review.json"),
    "PROBLEMS_FILE":   ("problems.json",      "problems.json"),
    "PROBLEMS_DIR":    ("problems",           "problems"),
    "OUTBOX_DIR":      ("problems/outbox",    "problems/outbox"),
    "QUESTIONS_FILE":  ("questions.json",     "questions.json"),
    "NOTIFY_FILE":     ("notify.json",        "notify.json"),
    "LOOKUP_CACHE":    ("lookup_cache.json",  "lookup_cache.json"),
    "AWAKE_STATE":     ("awake_state.json",   "awake_state.json"),
    "LOGS_DIR":        ("",                   "logs"),
    "APP_LOG":         ("app.log",            "logs/app.log"),
    "TRANSCRIPTS_LOG": ("transcripts.log",    "logs/transcripts.log"),
    "NOTIFY_LOG":      ("notify.log",         "logs/notify.log"),
    "AWAKE_LOG":       ("awake.log",          "logs/awake.log"),
    "NETWORK_LOG":     ("network.log",        "logs/network.log"),
    "RECENT_DIR":      ("recent",             "audio/recent"),
    "PENDING_DIR":     ("pending",            "audio/pending"),
    "CORPUS_DIR":      ("corpus",             "corpus"),
    "READ_DIR":        ("corpus/read",        "corpus/read"),
    "MODELS_DIR":      ("models",             "models"),
    "PACKS_DIR":       ("packs",              "packs"),
    "PHONE_DIR":       ("",                   "phone"),
    "PHONE_TOKEN":     ("server_token.txt",   "phone/server_token.txt"),
    "SECRETS_DIR":     ("secrets",            "secrets"),
    "CACHE_DIR":       ("cache",              "cache"),
    "CUES_DIR":        ("cues",               "cache/cues"),
    "TMP_DIR":         ("tmp",                "tmp"),
}

_col = 0 if FLAT else 1


def _rel(name: str) -> Path:
    parts = _LAYOUTS[name][_col]
    return DATA_DIR / parts if parts else DATA_DIR


LEGACY_CONFIG = _rel("LEGACY_CONFIG")
SETTINGS_FILE = _rel("SETTINGS_FILE")
STATE_FILE = _rel("STATE_FILE")
CONSENT_FILE = _rel("CONSENT_FILE")
SETUP_MARKER = _rel("SETUP_MARKER")
VOCAB_FILE = _rel("VOCAB_FILE")
REVIEW_FILE = _rel("REVIEW_FILE")
PROBLEMS_FILE = _rel("PROBLEMS_FILE")
PROBLEMS_DIR = _rel("PROBLEMS_DIR")
OUTBOX_DIR = _rel("OUTBOX_DIR")
QUESTIONS_FILE = _rel("QUESTIONS_FILE")
NOTIFY_FILE = _rel("NOTIFY_FILE")
LOOKUP_CACHE = _rel("LOOKUP_CACHE")
AWAKE_STATE = _rel("AWAKE_STATE")
LOGS_DIR = _rel("LOGS_DIR")
APP_LOG = _rel("APP_LOG")
TRANSCRIPTS_LOG = _rel("TRANSCRIPTS_LOG")
NOTIFY_LOG = _rel("NOTIFY_LOG")
AWAKE_LOG = _rel("AWAKE_LOG")
NETWORK_LOG = _rel("NETWORK_LOG")
RECENT_DIR = _rel("RECENT_DIR")
PENDING_DIR = _rel("PENDING_DIR")
CORPUS_DIR = _rel("CORPUS_DIR")
READ_DIR = _rel("READ_DIR")
MODELS_DIR = _rel("MODELS_DIR")
PACKS_DIR = _rel("PACKS_DIR")
PHONE_DIR = _rel("PHONE_DIR")
PHONE_TOKEN = _rel("PHONE_TOKEN")
SECRETS_DIR = _rel("SECRETS_DIR")
CACHE_DIR = _rel("CACHE_DIR")
CUES_DIR = _rel("CUES_DIR")
TMP_DIR = _rel("TMP_DIR")

#: The tracked configuration document: every key with its measurement
#: comments, the source the Settings page is generated from, and the
#: bottom layer of config.load_layered(). The app never writes it.
DEFAULTS_FILE = APP_DIR / "defaults.toml"
#: One line, SemVer, the number every screen and report prints;
#: the build copies it beside the code (chapter 11). version.py reads it.
VERSION_FILE = APP_DIR / "VERSION"

#: Read-only assets that stay with the code in every layout.
FONTS_DIR = APP_DIR / "fonts"
SKIN_DIR = APP_DIR / "skin"
ICON_ICO = APP_DIR / "icon.ico"
ICON_PNG = APP_DIR / "icon.png"

# ---- D30: the checkout is "DeskIT Dev" and never collides with the release

#: The suffix that keeps the checkout's kernel objects apart from the
#: installed copy's: ``""`` for a release, ``".dev"`` for DeskIT Dev.
DEV_SUFFIX: str = ".dev" if DEVELOPER else ""

#: What the window titles, the dot tooltip and the dashboard bar append.
DEV_TAG: str = "Dev" if DEVELOPER else ""

#: The port the phone endpoint tries first; the release keeps the number
#: the phone app has always known, the checkout sits one above it.
DEFAULT_PORT: int = 8757 if DEVELOPER else 8756

#: AppUserModelID for the taskbar: neutral (D5), and distinct for Dev.
APP_ID: str = "DeskIT.Dev" if DEVELOPER else "DeskIT.App"

# ---- the channel this copy came through (chapter 10 §10.4, chapter 11)

CHANNELS = ("github", "winget", "store")
#: One word, written by the installer beside python\ and app\ (never
#: inside app\, which the archive fills): github, winget or store.
CHANNEL_FILE = APP_DIR.parent / "CHANNEL"


def read_channel(path: Path | None = None) -> tuple[str, str]:
    """`(channel, note)`: the word in the file, or github with a note
    saying why — a missing file is the checkout or a hand-made tree, an
    unknown word is a broken install. Never raises."""
    path = CHANNEL_FILE if path is None else path
    try:
        word = path.read_text("utf-8").strip().lower()
    except FileNotFoundError:
        return "github", ""
    except OSError as e:
        return "github", f"CHANNEL unreadable ({e}); assuming github"
    if word in CHANNELS:
        return word, ""
    return "github", f"CHANNEL says {word!r}, not one of {CHANNELS}; assuming github"


CHANNEL, CHANNEL_NOTE = read_channel()


def kernel_name(base: str) -> str:
    """``Local\\DeskIT.instance`` → ``Local\\DeskIT.dev.instance`` for Dev.

    The insertion point is after the app's own name, so the family of
    names stays sortable and the release's names are untouched.
    """
    if not DEV_SUFFIX:
        return base
    head, sep, tail = base.partition("DeskIT")
    if not sep:
        return base + DEV_SUFFIX
    return f"{head}{sep}{DEV_SUFFIX}{tail}"


# ---- folders

#: The data sub-folders that must exist before the app writes anything.
#: In the flat (portable) layout only the three folders the app ALREADY
#: made for itself before this module existed — a checkout must not grow
#: new untracked folders just because paths.py knows their names (D4).
_ENSURE_INSTALLED = ("LOGS_DIR", "RECENT_DIR", "PENDING_DIR", "PROBLEMS_DIR",
                     "CACHE_DIR", "TMP_DIR")
_ENSURE_FLAT = ("RECENT_DIR", "PENDING_DIR", "PROBLEMS_DIR")


def ensure() -> Path:
    """Create ``DATA_DIR`` and the sub-folders the app writes into at start.

    Idempotent and cheap; never raises for a folder that already exists.
    Returns ``DATA_DIR`` so a caller can log it in one line.
    """
    for name in (_ENSURE_FLAT if FLAT else _ENSURE_INSTALLED):
        _rel(name).mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def resolve_folder(folder: str | os.PathLike) -> Path:
    """A user-typed folder: absolute stays; relative is under ``DATA_DIR``.

    Used for ``[capture] folder`` and friends. Relative to the DATA folder
    and not the working directory, because the app is launched from a
    shortcut, a .vbs and a scheduled task, and all three have different
    ideas about the working directory. In portable mode ``DATA_DIR`` is the
    code folder, which is exactly what those settings meant before.
    """
    path = Path(folder).expanduser()
    if not path.is_absolute():
        path = DATA_DIR / path
    return path


def describe() -> str:
    """One line for a log or the Files card."""
    mode = "portable" if FLAT else "installed"
    if DEVELOPER:
        mode = "developer (DeskIT Dev)"
    return f"{mode}: code {APP_DIR}, data {DATA_DIR}"
