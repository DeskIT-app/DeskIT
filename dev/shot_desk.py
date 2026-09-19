"""Photograph the desk the way an installed copy opens it: by path.

"Open the desk" on the installed 1.1.0 did nothing, silently. The
installed copy runs `python\\pythonw.exe app\\dashboard.py`, and that
interpreter's python311._pth ISOLATES sys.path to its four lines — the
script's own folder is not on it, so dashboard.py died on `import
config` with its stderr in DEVNULL (launch.spawn). This script is the
proof either way: it starts dashboard.py by path with the interpreter
you name — an installed tree's python.exe, or any python with -I -P,
which is the same sys.path — waits for its window, prints the window
to a PNG with PrintWindow, closes it, and prints the child's stderr if
it died instead.

Runs ON the hidden desktop (tests_quiet.run_hidden wraps it), so the
owner's screen never sees the window. DESKIT_HOME must be set, so the
desk reads a scratch folder and never anyone's real data; and the
desk's own mutex family (paths.kernel_name) is checked first — if a
desk of this family is already open, this script says so and stops
rather than signal it to the front.

    set DESKIT_HOME=...\\scratch\\home
    python dev\\shot_desk.py <python.exe> <out.png> [-I -P ...]

Exit 0 with the PNG written; 2 when the child died before a window
(its stderr on stdout); 3 when a desk of this family is already open.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes as w
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

import paths        # noqa: E402
import singleton    # noqa: E402

from PIL import Image  # noqa: E402

u = ctypes.windll.user32
g = ctypes.windll.gdi32
k = ctypes.windll.kernel32
WM_CLOSE = 0x0010
PW_RENDERFULLCONTENT = 2
SYNCHRONIZE = 0x00100000


def _window_of(pid: int) -> int:
    """The visible top-level window of `pid` whose title names the app."""
    found = []

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def each(hwnd, _):
        owner = w.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and u.IsWindowVisible(hwnd):
            n = u.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            if "DeskIT" in buf.value:
                found.append(hwnd)
        return True
    u.EnumWindows(each, 0)
    return found[0] if found else 0


def _shot(hwnd: int, out: Path) -> None:
    r = w.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    wd, ht = r.right - r.left, r.bottom - r.top
    hdc = u.GetWindowDC(hwnd)
    mem = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, wd, ht)
    g.SelectObject(mem, bmp)
    u.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", w.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", w.WORD), ("biBitCount", w.WORD), ("biCompression", w.DWORD),
                    ("biSizeImage", w.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", w.DWORD), ("biClrImportant", w.DWORD)]
    bi = BMI(ctypes.sizeof(BMI), wd, -ht, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(wd * ht * 4)
    g.GetDIBits(mem, bmp, 0, ht, buf, ctypes.byref(bi), 0)
    Image.frombuffer("RGBA", (wd, ht), buf, "raw", "BGRA", 0, 1).convert("RGB").save(out)
    g.DeleteObject(bmp); g.DeleteDC(mem); u.ReleaseDC(hwnd, hdc)


def desk_is_open() -> bool:
    """Is a desk of THIS tree's mutex family already up (his, on the
    real desktop)? Starting another would signal it to the front."""
    handle = singleton.kernel32.OpenMutexW(SYNCHRONIZE, False, singleton.DASHBOARD_MUTEX)
    if not handle:
        return False
    singleton.kernel32.CloseHandle(handle)
    return True


def main(argv: list[str]) -> int:
    python, out = Path(argv[0]), Path(argv[1])
    flags = argv[2:]
    if not os.environ.get("DESKIT_HOME", "").strip():
        print("refusing: DESKIT_HOME is not set (the desk would read real data)")
        return 1
    if desk_is_open():
        print(f"refusing: a desk holding {singleton.DASHBOARD_MUTEX} is open already")
        return 3
    err = out.with_suffix(".stderr.txt")
    with err.open("wb") as sink:
        p = subprocess.Popen([str(python), *flags, str(REPO / "dashboard.py")],
                             cwd=str(REPO), stdin=subprocess.DEVNULL,
                             stdout=sink, stderr=sink)
        hwnd = 0
        for _ in range(400):                   # up to 40 s for the window
            if p.poll() is not None:
                break
            hwnd = _window_of(p.pid)
            if hwnd:
                break
            time.sleep(0.1)
    if not hwnd:
        if p.poll() is None:
            p.kill()
        text = err.read_text("utf-8", errors="replace")
        print(f"no desk window (exit {p.returncode}); stderr:\n{text.rstrip()}")
        return 2
    time.sleep(2.5)                            # the first paint settles
    _shot(hwnd, out)
    print(f"wrote {out}")
    u.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill()
    text = err.read_text("utf-8", errors="replace").strip()
    if text:
        print(f"stderr:\n{text}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
