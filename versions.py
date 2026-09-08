"""Which branch this copy of the app is running on.

THERE USED TO BE TWO VERSIONS AND A BUTTON TO FLIP BETWEEN THEM. They
were kept as git branches of this very folder — `classic`, the app with
the repair pass run locally on gemma3:12b at about five seconds a
dictation, and `fast`, the same app with that pass sent to Groq's free
API first at about half a second. Switching was a `git checkout` of the
folder you are standing in, which is why this module was as careful as it
was: it saved the live config.toml bytes and wrote them back over the
checkout, refused to move while anything else was dirty, and stopped the
running instance before flipping so the Python on disk and the Python in
memory could never disagree.

All of that is gone, on the owner's word on 2026-09-08: "Remove all the
buttons for switching version. I want only to be on this version that is
already running." By then `classic` had not existed on this machine for
a fortnight, so the switcher's whole remaining offer was a trip
BACKWARDS — `fast` sat behind the branch he was actually running, and
pressing the button would have quietly undone days of work. A door with
nothing good behind it is not a feature.

What survives is the one question the rest of the app still asks: which
branch is this? `problems.py` stamps it on every report he files, and the
dashboard prints it under "The app" and along the foot of the home
screen. That is a read, it never changes anything, and it is all this
module does now.

The history, if the two versions are ever wanted again, is in git: the
switcher and its window were removed in the commit that carries this
docstring, and `AGENTS.md` records why.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

# Git is a console program and this app runs under pythonw, which has no
# console: without CREATE_NO_WINDOW every spawned git ALLOCATES ONE
# (conhost.exe) — a visible flicker and hundreds of milliseconds each, on
# whatever thread asked. Measured as the reason the settings screen froze
# solid the first time it read this.
_CREATE_NO_WINDOW = 0x08000000

# The answer cannot change while the app runs — a branch flip was the only
# thing that ever moved it, and that is what has just been removed. So it
# is asked once and remembered, because every ask was a process spawn.
_cache: dict = {}


def current_branch() -> str:
    """The branch name, or "(unknown)" — never raising, because a missing
    git must not blank a settings card or lose somebody's report."""
    if "branch" not in _cache:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=APP_DIR,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=15,
                creationflags=_CREATE_NO_WINDOW)
            out = proc.stdout.strip() if proc.returncode == 0 else ""
        except (OSError, ValueError, subprocess.SubprocessError):
            out = ""
        _cache["branch"] = out or "(unknown)"
    return str(_cache["branch"])
