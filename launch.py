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
import time
from pathlib import Path

import paths

APP_DIR = Path(__file__).resolve().parent

#: spawn.log (paths.SPAWN_LOG) is cut back to its tail past this size:
#: a launch row is one line and a traceback a few hundred bytes, and a
#: file nobody rotates must not grow for the life of an install.
SPAWN_LOG_MAX = 200_000
SPAWN_LOG_KEEP = 50_000

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

    The installed layout first (python\ beside app\, DISTRIBUTION_PLAN.md
    10.2), then the project's own venv: the shortcuts point at it, it is
    the one with faster-whisper in it, and whichever interpreter happens
    to be running this code may well not be it.
    """
    candidates = [
        APP_DIR.parent / "python" / "pythonw.exe",
        APP_DIR / ".venv" / "Scripts" / "pythonw.exe",
        Path(sys.executable).with_name("pythonw.exe"),
        Path(sys.executable),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return sys.executable


def _spawn_log(args: list[str]):
    """An append handle on paths.SPAWN_LOG, one dated row for this launch
    already in it, for the child to inherit as its stderr — or None when
    the file cannot be had, in which case the launch goes on with stderr
    in DEVNULL as it always did: a log that cannot be written must not
    cost the desk. The row names the script and its flags, so a
    traceback under it says which child died."""
    try:
        path = paths.SPAWN_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.stat().st_size > SPAWN_LOG_MAX:
                path.write_bytes(path.read_bytes()[-SPAWN_LOG_KEEP:])
        except OSError:
            pass
        fh = open(path, "ab")
        fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                 f"{' '.join(args)}\n".encode("utf-8", "replace"))
        fh.flush()
        return fh
    except OSError:
        return None


def spawn(args: list[str]) -> bool:
    """Launch and forget. False if it could not be started at all.

    stderr goes to spawn.log, not DEVNULL: a child that dies before it
    has a window — dashboard.py on the 1.1.0 install, dead on `import
    config` under the isolated interpreter — used to leave nothing at
    all, and "Open the desk" simply did nothing. Now the traceback is
    under the launch row in paths.SPAWN_LOG."""
    sink = _spawn_log(args)
    try:
        subprocess.Popen([pythonw(), *args], cwd=str(APP_DIR),
                         creationflags=_DETACHED, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=sink if sink is not None else subprocess.DEVNULL)
        return True
    except OSError:
        return False
    finally:
        if sink is not None:
            sink.close()


def start_app(config_path: str | None = None, model: bool | None = None) -> bool:
    """The app as its own process, with no window of its own (main.py
    --quiet: the desk that calls this is the window). model=None lets
    [local] load_at_start decide — on by default (the owner, 2026-09-20);
    False starts it without the speech model (--no-model), and Start in
    the desk loads it; every key that needs no model works either way."""
    args = [str(APP_DIR / "main.py"), "--quiet"]
    if config_path:
        args += ["--config", config_path]
    if model is False:
        args.append("--no-model")
    return spawn(args)


def open_dashboard() -> bool:
    return spawn([str(APP_DIR / "dashboard.py")])


def run_step(flag: str, name: str | None = None) -> bool:
    """A download step (models.py, packs.py) as its own process — the
    dashboard cannot host a second Tk root, and the app is already
    running: `main.py --download-model` or `--install-pack <name>`."""
    args = [str(APP_DIR / "main.py"), flag]
    if name:
        args.append(name)
    return spawn(args)


def dashboard_command() -> list[str]:
    """How the window is opened again by something that is not this
    process — the taskbar pin's relaunch property, Restart. In the
    checkout it is wscript + Dashboard.vbs, the launcher the shortcut
    and the pin have always run; an installed copy has no .vbs and
    runs the entry with --dashboard (10.2)."""
    vbs = APP_DIR / "Dashboard.vbs"
    if paths.DEVELOPER and vbs.exists():
        wscript = str(Path(os.environ.get("SystemRoot", r"C:\Windows"))
                      / "System32" / "wscript.exe")
        return [wscript, str(vbs)]
    return [pythonw(), str(APP_DIR / "deskit.pyw"), "--dashboard"]


def open_path(path: Path) -> bool:
    """Show a file or folder in whatever Windows uses for it — the log
    buttons. os.startfile is the shell's own "double-click this"."""
    try:
        os.startfile(str(path))      # noqa: S606  (Windows-only by design)
        return True
    except OSError:
        return False
