"""A hand on the emulator: read what is on screen, press what has a name.

emu.py starts the phone; this uses it, by what a person sees and not by
coordinates, so a flow reads like what someone would do. Nothing opens on the
owner's screen: the emulator has no window and everything goes through adb.
"""
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

SDK = Path(r"C:\Users\shimr\dev-tools\android-sdk")
ADB = SDK / "platform-tools" / "adb.exe"
PKG = "io.github.deskit_app.deskit"
HERE = Path(__file__).resolve().parent
OUT = Path(os.environ.get("DESKIT_EMU_OUT", HERE))

_NO_WINDOW = subprocess.CREATE_NO_WINDOW


def adb(*args, check=True, timeout=60, text=True) -> str:
    r = subprocess.run([str(ADB), *[str(a) for a in args]], capture_output=True,
                       timeout=timeout, creationflags=_NO_WINDOW,
                       encoding="utf-8" if text else None, errors="replace" if text else None)
    if check and r.returncode != 0:
        raise SystemExit(f"adb {args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r.stdout


def shell(*args, **kw) -> str:
    return adb("shell", *args, **kw)


def as_app(*args, **kw) -> str:
    """A command as the app itself: only a debug build answers."""
    return adb("shell", "run-as", PKG, *args, **kw)


def nodes() -> list[dict]:
    """Everything on screen with a text or a description, with its middle."""
    for _ in range(4):
        shell("uiautomator", "dump", "/sdcard/screen.xml", check=False)
        raw = adb("exec-out", "cat", "/sdcard/screen.xml", check=False)
        if raw.strip().startswith("<?xml"):
            break
        time.sleep(0.4)
    else:
        return []
    out = []
    try:
        root = ET.fromstring(raw[raw.index("<?xml"):raw.rindex(">") + 1])
    except ET.ParseError:
        return []
    for n in root.iter("node"):
        text = n.get("text") or n.get("content-desc") or ""
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds") or "")
        if not (text and m):
            continue
        x0, y0, x1, y1 = (int(v) for v in m.groups())
        out.append({"text": text, "x": (x0 + x1) // 2, "y": (y0 + y1) // 2,
                    "clickable": n.get("clickable") == "true"})
    return out


def screen() -> str:
    return "\n".join(n["text"] for n in nodes())


def find(pattern: str) -> dict | None:
    rx = re.compile(pattern)
    for n in nodes():
        if rx.search(n["text"]):
            return n
    return None


def wait(pattern: str, seconds: float = 20.0) -> dict:
    """The element whose text matches, once it is there; a failed check otherwise."""
    end = time.time() + seconds
    rx = re.compile(pattern)
    last = ""
    while time.time() < end:
        got = nodes()
        for n in got:
            if rx.search(n["text"]):
                return n
        last = " | ".join(n["text"] for n in got)
        time.sleep(0.4)
    raise AssertionError(f"{pattern!r} never came on screen; it says: {last[:600]}")


def gone(pattern: str, seconds: float = 20.0) -> None:
    end = time.time() + seconds
    rx = re.compile(pattern)
    while time.time() < end:
        if not any(rx.search(n["text"]) for n in nodes()):
            return
        time.sleep(0.4)
    raise AssertionError(f"{pattern!r} is still on screen")


def tap(pattern: str, seconds: float = 20.0) -> None:
    n = wait(pattern, seconds)
    shell("input", "tap", n["x"], n["y"])


def swipe_up() -> None:
    shell("input", "swipe", 500, 1700, 500, 500, 300)


def swipe_down() -> None:
    shell("input", "swipe", 500, 500, 500, 1700, 300)


def seek(pattern: str, swipes: int = 6) -> dict | None:
    """Something further down the page, without pressing it."""
    for _ in range(swipes + 1):
        n = find(pattern)
        if n is not None:
            return n
        swipe_up()
        time.sleep(0.3)
    return None


def tap_scrolling(pattern: str, swipes: int = 6) -> None:
    """Press something further down the page."""
    for _ in range(swipes + 1):
        n = find(pattern)
        if n is not None:
            shell("input", "tap", n["x"], n["y"])
            return
        swipe_up()
        time.sleep(0.3)
    raise AssertionError(f"{pattern!r} is nowhere on the page")


def home() -> None:
    """Android, clearing away the app's last task, can take the process it has just
    started for this one with it ("Destroy timeout of remove-task", then "failed to
    attach"), and then nothing of the app ever runs and the start waits for ever.
    Only this hand stops an app twice in a second. With the process alive the
    wait is the app's own fault, and that stays a failure."""
    for _ in range(3):
        try:
            shell("am", "start", "-W", "-n", f"{PKG}/.HomeActivity", timeout=20)
            return
        except subprocess.TimeoutExpired:
            if shell("pidof", PKG, check=False).strip():
                raise
            print("      Android lost the start: once more", flush=True)
            shell("am", "force-stop", PKG)
            time.sleep(2)
    raise AssertionError("Home never started")


def kill() -> None:
    """What Android does to a keyboard while he walks to the PC: the process
    is gone, nothing is told."""
    shell("am", "force-stop", PKG)


def die() -> None:
    """The same, by the road Android takes: force-stop would also clear the
    notifications, and those are part of what has to outlive a process."""
    shell("input", "keyevent", "3")              # home: nothing of ours in front
    time.sleep(0.5)
    as_app("sh", "-c", f"'kill -9 $(pidof {PKG})'", check=False)
    time.sleep(0.5)


def clear_app() -> None:
    """A fresh install, as far as the app can tell. Keystore keys go with it."""
    shell("pm", "clear", PKG, check=False)
    time.sleep(1.5)                              # Android is still taking the last task away


def notifications() -> str:
    """Everything on the shade, in full."""
    return shell("dumpsys", "notification", "--noredact", check=False)


def shot(name: str) -> Path:
    out = OUT / f"{name}.png"
    out.write_bytes(subprocess.run([str(ADB), "exec-out", "screencap", "-p"], capture_output=True,
                                   timeout=60, creationflags=_NO_WINDOW).stdout)
    return out


def logcat_clear() -> None:
    adb("logcat", "-c", check=False)


def logcat(tag: str = "DeskIT") -> str:
    return adb("logcat", "-d", "-s", f"{tag}:*", check=False)
