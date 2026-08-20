"""Install the dashboard's typeface for the current user. No admin.

Rubik — designed for Hebrew and Latin together, SIL OFL (fonts/OFL.txt).
The four files in fonts\\ are static instances cut from the official
variable font (google/fonts, ofl/rubik) with the name tables rewritten
the way GDI expects: "Rubik" Regular/Bold as one family, Medium and
SemiBold as families of their own. The originals from the Google Fonts
CSS API all called themselves "Rubik Light", which is why they are not
used as-is.

Per-user, three steps, all reversible:
1. copy into  %LOCALAPPDATA%\\Microsoft\\Windows\\Fonts
2. register under HKCU\\...\\CurrentVersion\\Fonts
3. AddFontResourceW + a WM_FONTCHANGE broadcast, so nothing needs a
   log-off to see them

The dashboard survives without any of this: ui.pick_face() measures what
is installed (existence AND Hebrew coverage, via GDI) and falls back to
Segoe UI. Running this once is what upgrades it from "correct" to "the
typeface the window was designed around".
"""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
import winreg
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
SOURCE = APP_DIR / "fonts"
TARGET = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts"

# registry value name -> file. The " (TrueType)" suffix is the convention
# the font folder itself uses; without it some tools list the face twice.
FACES = {
    "Rubik (TrueType)": "Rubik.ttf",
    "Rubik Bold (TrueType)": "RubikBold.ttf",
    "Rubik Medium (TrueType)": "RubikMedium.ttf",
    "Rubik SemiBold (TrueType)": "RubikSemiBold.ttf",
}


def install() -> int:
    missing = [f for f in FACES.values() if not (SOURCE / f).exists()]
    if missing:
        print(f"fonts\\ is missing {', '.join(missing)} — nothing installed")
        return 1
    TARGET.mkdir(parents=True, exist_ok=True)
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows NT\CurrentVersion\Fonts",
        0, winreg.KEY_SET_VALUE)
    try:
        for name, filename in FACES.items():
            destination = TARGET / filename
            fresh = SOURCE / filename
            try:
                shutil.copyfile(fresh, destination)
                verb = "installed"
            except PermissionError:
                # The file is already there AND loaded — GDI holds fonts
                # it has been handed. Same bytes: nothing to do. Different
                # bytes: it can only be swapped after a log-off, so say so
                # instead of pretending.
                if destination.read_bytes() == fresh.read_bytes():
                    verb = "already installed"
                else:
                    print(f"{name}: in use with OLDER bytes — sign out "
                          f"and run this again to swap it")
                    continue
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(destination))
            ctypes.windll.gdi32.AddFontResourceW(str(destination))
            print(f"{verb}: {name}")
    finally:
        winreg.CloseKey(key)
    HWND_BROADCAST, WM_FONTCHANGE = 0xFFFF, 0x001D
    ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_FONTCHANGE,
                                             0, 0, 2, 1000, None)
    print("done — open the dashboard and it will pick Rubik up")
    return 0


if __name__ == "__main__":
    sys.exit(install())
