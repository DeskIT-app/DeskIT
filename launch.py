"""Starting the app, and starting the dashboard, from each other.

Both directions exist: the dashboard's Start button launches the app, and
launching the app while it is already running opens the dashboard instead
of a modal complaint. Neither may leave a console window behind or a child
process tied to its parent — the dashboard is closed constantly and must
never take dictation down with it.

pythonw.exe, not python.exe: python.exe would flash (or keep) a console
window on every launch, which is the thing the .vbs launchers exist to
avoid in the first place.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

# DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP. Without the first the child
# inherits (or opens) a console; without the second, Ctrl+C in a
# console-run parent would be delivered to it too.
#
# No CREATE_NO_WINDOW: it is documented as incompatible with
# DETACHED_PROCESS (both decide the same thing), and it would buy nothing
# here anyway — pythonw.exe is a GUI-subsystem binary and never gets a
# console to hide.
_DETACHED = 0x00000008 | 0x00000200


def pythonw() -> str:
    """The windowless interpreter to launch children with.

    The project's own venv first: the shortcuts point at it, it is the one
    with faster-whisper in it, and whichever interpreter happens to be
    running this code may well not be it.
    """
    candidates = [
        APP_DIR / ".venv" / "Scripts" / "pythonw.exe",
        Path(sys.executable).with_name("pythonw.exe"),
        Path(sys.executable),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return sys.executable


def spawn(args: list[str]) -> bool:
    """Launch and forget. False if it could not be started at all."""
    try:
        subprocess.Popen([pythonw(), *args], cwd=str(APP_DIR),
                         creationflags=_DETACHED, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def start_app(config_path: str | None = None) -> bool:
    args = [str(APP_DIR / "main.py")]
    if config_path:
        args += ["--config", config_path]
    return spawn(args)


def open_dashboard() -> bool:
    return spawn([str(APP_DIR / "dashboard.py")])


def open_path(path: Path) -> bool:
    """Show a file or folder in whatever Windows uses for it — the log
    buttons. os.startfile is the shell's own "double-click this"."""
    try:
        os.startfile(str(path))      # noqa: S606  (Windows-only by design)
        return True
    except OSError:
        return False
