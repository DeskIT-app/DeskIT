"""Photograph "DeskIT is on this PC twice" — the window and the installer's dialogs.

The owner's rule of 2026-10-04: the website's, winget's and the Store's
DeskIT are one app, never two on one PC (onecopy.py). Anything on screen
gets a picture and his OK first; he approved these on 2026-10-04. This
builds onecopy_window.Window from fake facts with actions that do nothing,
in a scratch DESKIT_HOME, shows each face in turn and prints it to a PNG
with the PrintWindow the installer's pictures use (shot_installer._shot).
Nothing is detected, uninstalled or opened.

    python dev/shot_one_copy.py --out <folder>          (on the hidden desktop)
    python dev/shot_one_copy.py --out <folder> --hidden (wraps itself there)
    python dev/shot_one_copy.py --out <folder> --hidden --installer <setup.exe>

The window's faces: as the Store copy opens it (it found the website
copy), as the website copy opens it (it found the Store copy), the Store
copy removing the website copy, the website copy waiting for Windows to
remove DeskIT App, and the website copy still there after two minutes.

--installer photographs a Setup's one-copy dialogs, English and Hebrew:
dev/shot_one_copy_setup.iss compiled (it installs nothing; /SHOW=wait
shows the second dialog), or DeskIT.iss itself on a PC where the Store
copy is installed (the first dialog only). Setup is ended by PID.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))


def _silence() -> None:
    """No sound from a driver (AGENTS.md rule 8): before any app import."""
    import winsound
    winsound.PlaySound = lambda *a, **k: None
    winsound.Beep = lambda *a, **k: None
    import tkinter as tk
    tk.Misc.bell = lambda *a, **k: None


def _hidden(out: Path, extra: list[str]) -> int:
    import tests_quiet
    line = " ".join([f'"{sys.executable}"', "-B", f'"{Path(__file__)}"', "--out", f'"{out}"', *extra])
    return tests_quiet.run_hidden(line, ROOT)


class Nothing:
    """Every action a no-op; the Store copy stays installed."""

    def __getattr__(self, name):
        if name == "store_copy":
            return lambda: object()
        return lambda *a, **k: True


def _pictures(out: Path) -> list[Path]:
    home = Path(tempfile.mkdtemp(prefix="deskit-onecopy-shots-"))
    os.environ["DESKIT_HOME"] = str(home)
    _silence()
    import ctypes

    import onecopy
    import onecopy_window
    from shot_installer import _shot
    store = onecopy.Copy("store", "1.0.6")
    website = onecopy.Copy("website", "1.0.7", channel="github",
                           folder=os.path.expandvars(r"%LOCALAPPDATA%\Programs\DeskIT"),
                           uninstaller="unins000.exe")
    faces = (("from-store", "store", website, None, "_choose"),
             ("from-website", "website", store, website, "_choose"),
             ("removing", "store", website, None, "_removing"),
             ("website-waiting", "website", store, website, "_waiting"),
             ("failed", "store", website, None, "_failed"))
    shots = []
    for name, here, other, me, face in faces:
        # this copy's own version, as the card it is on shows it
        onecopy_window._own_version = (lambda v=store.version if here == "store"
                                       else website.version: v)
        window = onecopy_window.Window(here, other, me, actions=Nothing(), poll_ms=60_000)
        getattr(window, face)()
        for _ in range(8):
            window.root.update()
            time.sleep(0.08)
        hwnd = ctypes.windll.user32.GetParent(int(window.root.winfo_id()))
        path = out / f"one-copy-{name}.png"
        _shot(hwnd, path)
        shots.append(path)
        window.root.destroy()
    return shots


def _dialog() -> int:
    """The task dialog Setup put up: the only #32770 window on the hidden
    desktop (Inno's wizard runs in a CHILD process, so not by pid)."""
    import ctypes
    from ctypes import wintypes as w
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def each(hwnd, _):
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, cls, 64)
        if u.IsWindowVisible(hwnd) and cls.value == "#32770":
            found.append(hwnd)
        return True
    u.EnumWindows(each, 0)
    return found[0] if found else 0


def _installer(exe: Path, out: Path) -> list[Path]:
    """A Setup's dialogs, English and Hebrew; a task dialog with only
    custom buttons takes no WM_CLOSE, so Setup is ended by its PID."""
    import ctypes
    import subprocess
    from ctypes import wintypes as w

    from PIL import Image, ImageOps

    from shot_installer import _shot
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    shots = []
    for name, extra in (("installer-en", []), ("installer-he", ["/LANG=hebrew"]),
                        ("installer-wait-en", ["/SHOW=wait"]),
                        ("installer-wait-he", ["/SHOW=wait", "/LANG=hebrew"])):
        p = subprocess.Popen([str(exe), *extra])
        hwnd = 0
        for _ in range(200):
            hwnd = _dialog()
            if hwnd:
                break
            time.sleep(0.1)
        if not hwnd:
            p.kill()
            print(f"{name}: no dialog")
            continue
        time.sleep(1.0)
        path = out / f"one-copy-{name}.png"
        _shot(hwnd, path)
        # PrintWindow hands back a right-to-left window's pixels mirrored
        # (WS_EX_LAYOUTRTL, the Hebrew dialog): flipped back, it is what
        # the screen shows
        if u.GetWindowLongW(hwnd, -20) & 0x00400000:
            ImageOps.mirror(Image.open(path)).save(path)
        shots.append(path)
        owner = w.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        handle = k.OpenProcess(0x0001, False, owner.value)      # PROCESS_TERMINATE
        if handle:
            k.TerminateProcess(handle, 0)
            k.CloseHandle(handle)
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    return shots


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--hidden", action="store_true")
    parser.add_argument("--installer", help="a compiled Setup to photograph")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.hidden:
        extra = ["--installer", f'"{Path(args.installer).resolve()}"'] if args.installer else []
        return _hidden(out, extra)
    shots = _installer(Path(args.installer), out) if args.installer else _pictures(out)
    for path in shots:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
