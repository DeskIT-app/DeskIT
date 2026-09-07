"""Hand this process its own copy of Rubik, before anything asks for it.

`install_fonts.py` copies the four files into the per-user font folder and
writes them into `HKCU\\...\\CurrentVersion\\Fonts`. That is enough for
*new* processes on a machine whose font cache has caught up — and it is
not a guarantee. Measured 2026-09-06, on a machine where all four files
were on disk, registered under HKCU and installed 17 days earlier, past a
reboot: a fresh Python process asking GDI for the family "Rubik" got
**Arial** back, so `ui.pick_face(["Rubik"])` returned "Segoe UI" and the
whole app had been drawing in the fallback face without a word about it.
The registry entry is a promise to the next logon; it is not an answer to
`CreateFontW` in *this* process.

One call fixes it, and it is the same call `install_fonts.py:74` already
makes for a different reason:

    AddFontResourceExW(path, FR_PRIVATE, 0)

FR_PRIVATE means the face is visible to this process and to nobody else —
nothing is installed, nothing is written, no `WM_FONTCHANGE` goes out to
every window on the desktop, and when the process ends the face is gone.
That is the right shape for a fix that has to be safe to run on every
start: it cannot leave the machine different from how it found it.

Three properties this module promises, because it runs on the startup
path:

1. **Idempotent.** `load()` does its work once and then returns the same
   list. GDI reference-counts a privately added file, so calling it twice
   would leak a reference per call rather than fail loudly.
2. **Never raises.** A missing folder, a corrupt file, a GDI that says no
   — every one of them is a log line and a fallback to Segoe UI, which is
   what `ui.pick_face` was written to do anyway. A typeface is not worth
   a dictation.
3. **Cheap.** Four `AddFontResourceExW` calls, measured at under 3 ms
   together on this machine; it is a file handle and a table parse.

What GDI gives back, measured the same day with all four files loaded:
only **two** weights are real. `("Rubik", 400)` and `("Rubik", 700)`
differ (advance 104 vs 108 px for `מבנה חדש` at 24 px); `("Rubik", 500)`,
`Rubik Medium` and `Rubik SemiBold` all resolve to the 400 outlines,
because the four files in `fonts\\` are cuts of one variable font and GDI
collapses their named instances. So `ui.MEDIUM` is a real family name
that draws at regular weight, and a design that needs a third step in the
ladder has to get it from size or colour, not from a weight.
"""
from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path

log = logging.getLogger("app")

APP_DIR = Path(__file__).resolve().parent
FONT_DIR = APP_DIR / "fonts"

FR_PRIVATE = 0x10          # visible to this process only
FR_NOT_ENUM = 0x20         # (not used: the face must be enumerable so that
#                             GetTextFaceW can confirm it, which is how
#                             ui._gdi_face decides a family exists at all)

_loaded: list[str] | None = None


def _user_font_dir() -> Path | None:
    """Where `install_fonts.py` puts them, if that has ever been run."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    folder = Path(local) / "Microsoft" / "Windows" / "Fonts"
    return folder if folder.is_dir() else None


def files() -> list[Path]:
    """Every font file worth handing to GDI, `fonts\\` first.

    The app's own copies win over the installed ones: they are the bytes
    this version of the app was drawn against, and a stale install can
    otherwise shadow them. Anything already covered by name is skipped, so
    a per-user install of the same four files does not double the work.
    """
    found: list[Path] = []
    seen: set[str] = set()
    for folder, pattern in ((FONT_DIR, "*.ttf"),
                            (FONT_DIR, "*.otf"),
                            (_user_font_dir(), "Rubik*.ttf")):
        if folder is None:
            continue
        try:
            for path in sorted(folder.glob(pattern)):
                key = path.name.lower()
                if key not in seen and path.is_file():
                    seen.add(key)
                    found.append(path)
        except OSError:
            continue
    return found


def load() -> list[str]:
    """Add every font in `fonts\\` to this process. Returns what took.

    Safe to call from anywhere, any number of times, on any platform: on
    something that is not Windows there is no `gdi32` and the list comes
    back empty.
    """
    global _loaded
    if _loaded is not None:
        return _loaded
    _loaded = []
    try:
        gdi = ctypes.windll.gdi32
    except Exception:                      # not Windows, or no ctypes
        log.debug("fonts: no gdi32; the app draws in whatever Tk finds")
        return _loaded
    for path in files():
        try:
            count = int(gdi.AddFontResourceExW(str(path), FR_PRIVATE, 0))
        except Exception:
            count = 0
        if count:
            _loaded.append(path.name)
        else:
            log.debug("fonts: GDI refused %s", path.name)
    if _loaded:
        log.info("fonts: %d loaded privately (%s)",
                 len(_loaded), ", ".join(_loaded))
    else:
        log.info("fonts: nothing loaded; falling back to installed faces")
    return _loaded


def loaded() -> list[str]:
    """What load() managed, without doing it — for a status line."""
    return list(_loaded or [])


def main() -> int:
    """`python -B fonts.py` — say what GDI answers, before and after.

    The probe is `ui._gdi_face`'s, spelled out here so that running this
    file does not import tkinter.
    """
    def face(name: str) -> str:
        gdi, user = ctypes.windll.gdi32, ctypes.windll.user32
        hdc = user.GetDC(0)
        font = gdi.CreateFontW(-24, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 0, 0,
                               name)
        old = gdi.SelectObject(hdc, font)
        try:
            buf = ctypes.create_unicode_buffer(64)
            gdi.GetTextFaceW(hdc, 64, buf)
            return buf.value
        finally:
            gdi.SelectObject(hdc, old)
            gdi.DeleteObject(font)
            user.ReleaseDC(0, hdc)

    asked = ("Rubik", "Rubik Medium", "Rubik SemiBold")
    print("before:", {n: face(n) for n in asked})
    print("loaded:", load())
    print("after: ", {n: face(n) for n in asked})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
