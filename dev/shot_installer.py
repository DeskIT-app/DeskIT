"""Photograph the installer's Welcome page without installing anything.

Runs ON the hidden desktop (tests_quiet.run_hidden wraps it): starts the
setup exe there, waits for its wizard window, prints it to a PNG with
PrintWindow, then closes it with WM_CLOSE and answers the "exit setup?"
question with its Yes button. The owner's screen never sees a window
(memory: hidden desktop, every driver and screenshot).

    python dev/shot_installer.py <setup.exe> <out.png> [/LANG=hebrew]
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes as w
from pathlib import Path

from PIL import Image

u = ctypes.windll.user32
g = ctypes.windll.gdi32
WM_CLOSE = 0x0010
BM_CLICK = 0x00F5
PW_RENDERFULLCONTENT = 2


def _find(title_part: str, pid: int = 0) -> int:
    found = []

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def each(hwnd, _):
        owner = w.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        # Inno's setup.exe unpacks itself and runs the wizard from a
        # CHILD process (is-XXXX\...tmp), so the pid is not the parent's;
        # on the hidden desktop the only windows are ours, so the title
        # alone identifies it.
        if u.IsWindowVisible(hwnd):
            n = u.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            if title_part in buf.value:
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


def main(argv: list[str]) -> int:
    exe, out = Path(argv[0]), Path(argv[1])
    extra = argv[2:]
    p = subprocess.Popen([str(exe), "/SUPPRESSMSGBOXES", *extra])
    hwnd = 0
    for _ in range(300):                       # up to 30 s for the wizard to appear
        hwnd = _find("DeskIT", p.pid)
        if hwnd:
            break
        time.sleep(0.1)
    if not hwnd:
        p.kill(); print("no wizard window"); return 1
    time.sleep(1.5)                            # fonts and pictures settle
    _shot(hwnd, out)
    print(f"wrote {out}")
    u.PostMessageW(hwnd, WM_CLOSE, 0, 0)       # "Exit Setup?" — answer Yes
    for _ in range(50):
        q = _find("Exit Setup", p.pid) or _find("לצאת", p.pid)
        if q:
            yes = u.FindWindowExW(q, 0, "Button", None)
            while yes:
                n = u.GetWindowTextLengthW(yes); buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(yes, buf, n + 1)
                if buf.value.strip("&").lower().startswith(("yes", "כן")):
                    u.SendMessageW(yes, BM_CLICK, 0, 0); break
                yes = u.FindWindowExW(q, yes, "Button", None)
            break
        time.sleep(0.1)
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
