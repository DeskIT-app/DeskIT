"""The stranger's first run, from this checkout.

The checkout can never be a stranger's copy on its own: `.git` beside
main.py makes it DeskIT Dev — the model is the global cache's, the keys
come from .env, the wizard never shows, the owner-only surfaces are
there. That is the gap the owner named on 2026-09-19 ("gaps between
the two versions"): every first-run bug was found on the installed
copy and fixed blind in the checkout.

This starts the checkout's CODE as an INSTALLED copy — paths.STRANGER:
`DESKIT_STRANGER=1` with a `DESKIT_HOME` of its own — so it looks for
the model under that home and offers the download, reads no .env and
no bare key name (the store is `DeskIT.test/`), hides the developer
surfaces, keeps its own kernel names (`.test`) beside DeskIT Dev's and
the release's, writes its Start-with-Windows switch to a Run key
Windows never reads and its Connect-Claude-Code switch to a settings
file of its own. What it does NOT fake: the microphone, the hardware
probe, the downloads, the account page (the real Supabase project),
the hotkeys — the copy takes the same keys as the dev copy, so the
two both answer while both run.

    python dev\\stranger.py            a fresh person, the downloads kept
    python dev\\stranger.py --all      the whole home gone: the true first
                                      run (about 4.6 GB on a GPU box)
    python dev\\stranger.py --keep     as it stands, only the wizard
                                      forgotten — every page again
    python dev\\stranger.py --run      as it stands, nothing forgotten: the
                                      copy's ordinary start (what
                                      dev\\stranger.vbs and the desktop
                                      shortcut "DeskIT" do)
    python dev\\stranger.py --reset-only  the reset without the start
    python dev\\stranger.py --stop     ask the running stranger copy to quit
    python dev\\stranger.py --shots D  the proof, on the hidden desktop:
                                      the first window photographed to D

The home is %LOCALAPPDATA%\\DeskIT-dev\\stranger unless --home says
otherwise; never %LOCALAPPDATA%\\DeskIT, the installed copy's, and never
the checkout's own folder.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import winreg
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

DEFAULT_HOME = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) \
    / "DeskIT-dev" / "stranger"

#: What a reset keeps unless --all: the downloads, which are the same for
#: every stranger and cost gigabytes.
DOWNLOADS = ("models", "packs", "cache")

#: The owner's shell answers these; the stranger's does not.
OWNER_VARS = ("DESKIT_PORTABLE", "GROQ_API_KEY", "GEMINI_API_KEY",
              "DESKIT_GROQ_API_KEY", "DESKIT_GEMINI_API_KEY")

STRANGER_RUN_KEY = r"Software\DeskIT.test\Run"


def environment(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in OWNER_VARS}
    env["DESKIT_HOME"] = str(home)
    env["DESKIT_STRANGER"] = "1"
    return env


def refuse_bad_home(home: Path) -> None:
    """Never the installed copy's folder, never the checkout."""
    local = Path(os.environ.get("LOCALAPPDATA", "")) if os.environ.get("LOCALAPPDATA") else None
    forbidden = [ROOT.resolve()] + ([(local / "DeskIT").resolve()] if local else [])
    h = home.resolve()
    for bad in forbidden:
        if h == bad or bad in h.parents:
            sys.exit(f"refusing {home}: that is {bad}, someone's real folder")


def reset(home: Path, mode: str) -> list[str]:
    """Empty the home the way `mode` says; the lines to print."""
    done: list[str] = []
    if mode == "all":
        if home.exists():
            shutil.rmtree(home)
            done.append(f"removed {home} (the downloads too)")
    elif mode == "fresh":
        kept = []
        for child in list(home.iterdir()) if home.exists() else []:
            if child.name in DOWNLOADS:
                kept.append(child.name)
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        if home.exists():
            done.append(f"emptied {home}" + (f", kept {', '.join(kept)}" if kept else ""))
    elif mode == "keep":
        state = home / "state.json"
        if state.exists():
            import json
            try:
                data = json.loads(state.read_text("utf-8"))
            except ValueError:
                data = {}
            if data.pop("setup.done", None) is not None:
                state.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
                done.append("setup.done forgotten; everything else as it stands")
        marker = home / ".setup-done"
        if marker.exists():
            marker.unlink()
    if mode in ("all", "fresh"):
        # The stranger's key store and Run key live outside the folder.
        import secretstore
        for name in secretstore.CRED_NAMES:
            try:
                if secretstore.delete(name):
                    done.append(f"removed the stranger's {secretstore.target(name)}")
            except Exception as e:                            # noqa: BLE001
                done.append(f"could not remove {name}: {e}")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STRANGER_RUN_KEY, 0,
                                winreg.KEY_ALL_ACCESS) as key:
                winreg.DeleteValue(key, "DeskIT")
            done.append(f"removed HKCU\\{STRANGER_RUN_KEY}\\DeskIT")
        except FileNotFoundError:
            pass
    home.mkdir(parents=True, exist_ok=True)
    return done


def pythonw() -> str:
    for name in ("pythonw.exe", "python.exe"):
        p = ROOT / ".venv" / "Scripts" / name
        if p.exists():
            return str(p)
    return sys.executable


def start(home: Path, env: dict[str, str]) -> int:
    """The entry an installed copy runs, detached, its stderr in the
    home's spawn.log; the pid."""
    logs = home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    sink = (logs / "spawn.log").open("ab")
    sink.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} dev\\stranger.py deskit.pyw\n".encode())
    proc = subprocess.Popen([pythonw(), str(ROOT / "deskit.pyw")], cwd=str(ROOT), env=env,
                            creationflags=0x00000008 | 0x00000200, close_fds=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=sink)
    return proc.pid


def stop(home: Path, env: dict[str, str]) -> int:
    out = subprocess.run([sys.executable, str(ROOT / "main.py"), "--stop"], cwd=str(ROOT),
                         env=env, capture_output=True, encoding="utf-8", errors="replace",
                         timeout=60)
    print((out.stdout + out.stderr).strip() or f"exit {out.returncode}")
    return out.returncode


def shots(home: Path, env: dict[str, str], out: Path) -> int:
    """On the hidden desktop: start the copy the way `start` does, wait
    for its first window, print it to PNG twice (as it opens, and three
    seconds later), then end the process. The log's first lines follow,
    so the proof reads without opening anything."""
    import ctypes
    from ctypes import wintypes as w
    import tests_quiet as q
    from shot_desk import _shot
    out.mkdir(parents=True, exist_ok=True)
    logs = home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.CreateDesktopW.restype = w.HANDLE
    hdesk = user32.CreateDesktopW(q.DESKTOP, None, None, 0, q.GENERIC_ALL, None)
    if not hdesk:
        raise ctypes.WinError(ctypes.get_last_error())
    # EnumWindows and PrintWindow see the desktop THIS thread is on; a
    # thread without windows of its own may move there.
    if not user32.SetThreadDesktop(hdesk):
        raise ctypes.WinError(ctypes.get_last_error())
    block = "".join(f"{k}={v}\0" for k, v in sorted(env.items())) + "\0"
    code = 1
    try:
        si = q.STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = q.DESKTOP
        pi = q.PROCESS_INFORMATION()
        line = ctypes.create_unicode_buffer(f'"{pythonw()}" "{ROOT / "deskit.pyw"}"')
        envbuf = ctypes.create_unicode_buffer(block, len(block))
        kernel32.CreateProcessW.argtypes = [
            w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD,
            ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(q.STARTUPINFOW),
            ctypes.POINTER(q.PROCESS_INFORMATION)]
        ok = kernel32.CreateProcessW(None, line, None, None, False,
                                     q.CREATE_NO_WINDOW | 0x00000400,   # CREATE_UNICODE_ENVIRONMENT
                                     envbuf, str(ROOT), ctypes.byref(si), ctypes.byref(pi))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        pid = int(pi.dwProcessId)
        print(f"started pid {pid} on the hidden desktop")

        def windows() -> list[tuple[int, int, str]]:
            """(hwnd, pid, title) of every visible window on the desktop
            — the desktop is ours, so they are all the copy's. Not by
            pid: the venv's pythonw.exe is a launcher whose child is the
            interpreter that owns the window."""
            seen: list[tuple[int, int, str]] = []

            @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
            def each(h, _):
                if user32.IsWindowVisible(h):
                    owner = w.DWORD()
                    user32.GetWindowThreadProcessId(h, ctypes.byref(owner))
                    n = user32.GetWindowTextLengthW(h)
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(h, buf, n + 1)
                    seen.append((int(h), int(owner.value), buf.value))
                return True
            user32.EnumDesktopWindows(hdesk, each, 0)
            return seen

        hwnd, owner = 0, 0
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and not hwnd:
            time.sleep(0.5)
            for h, p, title in windows():
                if "DeskIT" in title:
                    hwnd, owner = h, p
                    break
            alive = w.DWORD()
            kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(alive))
            if alive.value != 259:                                 # STILL_ACTIVE
                print(f"the copy ended with {alive.value} before a window")
                break
        if hwnd:
            time.sleep(1.0)
            _shot(hwnd, out / "01-first-window.png")
            time.sleep(3.0)
            _shot(hwnd, out / "02-three-seconds-later.png")
            print(f"wrote {out / '01-first-window.png'} and 02-three-seconds-later.png")
            code = 0
        else:
            print(f"no window named DeskIT; the desktop holds {windows()}")
        for victim in {pid, owner} - {0}:
            handle = kernel32.OpenProcess(0x0001, False, victim)         # PROCESS_TERMINATE
            if handle:
                kernel32.TerminateProcess(handle, 0)
                kernel32.CloseHandle(handle)
        kernel32.CloseHandle(pi.hThread)
        kernel32.CloseHandle(pi.hProcess)
    finally:
        user32.CloseDesktop(hdesk)
    log = logs / "app.log"
    if log.exists():
        lines = log.read_text("utf-8", errors="replace").splitlines()
        print("app.log:")
        for line in lines[:12]:
            print("  " + line)
    spawn = logs / "spawn.log"
    if spawn.exists() and spawn.stat().st_size:
        tail = spawn.read_text("utf-8", errors="replace").strip().splitlines()[-8:]
        print("spawn.log tail:")
        for line in tail:
            print("  " + line)
    return code


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--home", type=Path, default=DEFAULT_HOME)
    how = ap.add_mutually_exclusive_group()
    how.add_argument("--all", action="store_true", help="the downloads too")
    how.add_argument("--keep", action="store_true", help="only forget setup.done")
    how.add_argument("--run", action="store_true", help="forget nothing: the ordinary start")
    how.add_argument("--stop", action="store_true", help="quit the running stranger copy")
    ap.add_argument("--reset-only", action="store_true", help="the reset, and no start")
    ap.add_argument("--shots", type=Path, metavar="DIR",
                    help="the proof on the hidden desktop: photograph the first window into DIR")
    a = ap.parse_args(argv)
    home = a.home.resolve()
    refuse_bad_home(home)
    env = environment(home)
    if a.stop:
        return stop(home, env)
    # This process sees the stranger's store too (the reset deletes the
    # stranger's key, never the owner's DeskIT/ entry).
    os.environ.update({k: env[k] for k in ("DESKIT_HOME", "DESKIT_STRANGER")})
    if not a.run:
        for line in reset(home, "all" if a.all else "keep" if a.keep else "fresh"):
            print(line)
    if a.reset_only:
        return 0
    if a.shots:
        return shots(home, env, a.shots.resolve())
    pid = start(home, env)
    print(f"the stranger's copy is up: pid {pid}, home {home}")
    print("no .env, no key, no model until the wizard downloads one; the kernel names"
          " carry .test, the phone port is 8758")
    print("its hotkeys are the dev copy's hotkeys: both answer while both run")
    print(f"to end it: python dev\\stranger.py --stop" + (f" --home \"{home}\"" if home != DEFAULT_HOME.resolve() else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
