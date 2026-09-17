"""Which DeskIT this is: one number, from one file.

`VERSION` sits beside `main.py` — one line, SemVer, no `v` — and the
build copies it unchanged into the installed tree (DISTRIBUTION_PLAN.md
chapter 11, D21). Everything that needs a number reads it from here:
the problem report's `env`, the dashboard's foot and About lines, the
consent rows in `consent.json`, the phone server's `/health`, and — on
the Android side — `build.gradle.kts`, which reads the same file and
derives `versionCode` from it, so the two apps cannot drift.

The branch is the other thing this module knows, and only in the
checkout: `BRANCH` is spawned from git when `.git` is beside `main.py`
(paths.DEVELOPER), and is "" everywhere else — an installed copy has no
`.git`, no git on PATH and no reason to start a process to find that
out. This module replaces `versions.py`, which knew only the branch; its
history (two versions and a switcher, removed 2026-09-08) is in git.

Git is a console program and the app runs under pythonw, which has no
console: without CREATE_NO_WINDOW every spawned git allocates one — a
visible flicker and hundreds of milliseconds each. That is the reason
the settings screen once froze solid reading the branch, and the reason
the answer is read once here and never again.
"""
from __future__ import annotations

import logging
import re
import subprocess

import paths

log = logging.getLogger("app")

_CREATE_NO_WINDOW = 0x08000000

#: What a VERSION line may say: MAJOR.MINOR.PATCH with an optional
#: -beta.N. The release workflow refuses a tag that does not match the
#: file, and the Android versionCode formula caps MINOR and PATCH at 99.
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")

#: What a missing or unreadable file reads as. Never raise at import: a
#: broken VERSION must not stop the app from dictating.
FALLBACK = "0.0.0"


def parse(text: str) -> tuple[int, int, int, int | None]:
    """`(major, minor, patch, beta)` for a VERSION line; beta is None for
    a release. Raises ValueError on anything else."""
    m = SEMVER.match((text or "").strip())
    if not m:
        raise ValueError(f"not a DeskIT version: {text!r}")
    major, minor, patch, beta = m.groups()
    return int(major), int(minor), int(patch), (int(beta) if beta else None)


def key(text: str) -> tuple:
    """A sort key with SemVer precedence: 1.2.0-beta.3 < 1.2.0, and
    1.2.0 < 1.10.0 (numbers, not strings)."""
    major, minor, patch, beta = parse(text)
    # a release sorts after every beta of the same numbers
    return (major, minor, patch, 1 if beta is None else 0, beta or 0)


def _read() -> str:
    try:
        text = paths.VERSION_FILE.read_text("utf-8").strip()
        parse(text)
        return text
    except FileNotFoundError:
        log.warning("no VERSION file beside main.py — reporting %s", FALLBACK)
    except (OSError, ValueError) as e:
        log.warning("VERSION file unreadable (%s) — reporting %s", e, FALLBACK)
    return FALLBACK


def _branch() -> str:
    """The checkout's branch, or "". Only a checkout asks git at all."""
    if not paths.DEVELOPER:
        return ""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=paths.APP_DIR,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=15, creationflags=_CREATE_NO_WINDOW)
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


#: The one string: "1.1.0", or "1.2.0-beta.2".
VERSION: str = _read()
#: The same, as numbers.
PARTS: tuple[int, int, int, int | None] = parse(VERSION)
IS_BETA: bool = PARTS[3] is not None
#: The git branch in the checkout; "" on every installed copy.
BRANCH: str = _branch()


def label() -> str:
    """What a screen prints: "DeskIT 1.1.0", with the branch after a dot
    in the checkout — "DeskIT 1.1.0 · main"."""
    return f"DeskIT {VERSION}" + (f" · {BRANCH}" if BRANCH else "")
