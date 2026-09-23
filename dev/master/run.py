"""Running git and gh without a console flashing on his screen.

AGENTS: every subprocess under pythonw needs CREATE_NO_WINDOW (0x08000000)
or each spawn freezes the UI thread and blinks a console — it froze the
dashboard once already. The master's window will be a WebView2 one, under
pythonw, so the same rule holds here.

Nothing in this file writes anything anywhere: the only commands the
master runs are the reading ones, and the caller names them.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
TIMEOUT_S = 25


class Failed(Exception):
    """The command was not there, said no, or took too long. A screen
    turns this into a row that says so — never into an empty list that
    looks like good news."""


def out(args: list[str], cwd: Path, timeout: int = TIMEOUT_S) -> str:
    try:
        done = subprocess.run(
            args, cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=CREATE_NO_WINDOW)
    except FileNotFoundError as e:
        raise Failed(f"{args[0]} is not on this PC") from e
    except subprocess.TimeoutExpired as e:
        raise Failed(f"{args[0]} took longer than {timeout} s") from e
    if done.returncode != 0:
        first = (done.stderr or done.stdout or "").strip().splitlines()
        raise Failed(f"{' '.join(args[:2])} said no: "
                     f"{first[0] if first else done.returncode}")
    return done.stdout


def lines(args: list[str], cwd: Path, timeout: int = TIMEOUT_S) -> list[str]:
    return [ln for ln in out(args, cwd, timeout).splitlines() if ln.strip()]
