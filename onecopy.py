"""One DeskIT per PC: which other released copy is installed beside this one.

The website's installer, winget (the same Inno installer) and the Microsoft
Store package are ONE app downloaded three ways — the owner's rule of
2026-10-04 — and nobody should end up with two of them on one PC. The
released app keeps its cloud keys in one Credential Manager slot,
`DeskIT/`, however it came (secretstore.prefix_for), which is only safe
while the two never coexist.

WHAT TWO COPIES SHARE, MEASURED (2026-10-04, the owner's PC, Windows 11
build 26200, the Store package 1.0.6, test names only, everything removed
after). A process started inside the Store package
(Invoke-CommandInDesktopPackage, the package's own pythonw) asked about
things an ordinary process had made outside it:

- an HKCU key and an Uninstall entry made outside: READ, values and all —
  so the Store copy sees the website copy's Uninstall entry;
- a file in a folder under the real %LOCALAPPDATA%: READ;
- an append to that file: landed on the REAL file;
- a NEW file in that real folder: landed in the REAL folder, not in the
  package's private LocalCache — further than Microsoft's page says
  ("newly created files ... are written to a private per-user, per-app
  location"). So a Store copy started on a PC where the website copy made
  `%LOCALAPPDATA%\\DeskIT` reads and writes the website copy's state.json,
  settings.toml, secrets\\supabase_session.bin, sync\\, vocab.json — the
  whole folder, both ways;
- a named mutex (`Local\\...`) held outside: SEEN — the kernel names are
  shared, so the two copies' `Local\\DeskIT.instance` is ONE mutex: only
  one of them runs at a time, and the second click opens the first one's
  desk;
- `GetPackagesByPackageFamily` from an ordinary process: finds the Store
  package for this user, 3.5 ms.

(A trap met on the way: files and keys written by the coding tools'
shells on that PC live in a layer of their own that no other process
sees — a WMI-started cmd could not see them either. The probe's "outside"
things had to be made by a process Windows started, through WMI, before
the Store copy could see them. Anyone re-running this: same.)

So each side asks about the OTHER, read-only, before it writes anything:

- the Store copy (paths.PACKAGED) asks for the Inno install: its HKCU
  Uninstall entry (AppId below, `_is1`) whose uninstaller is still on disk;
- the website/winget copy asks Windows for the Store package family.

The checkout (DeskIT Dev), the Stranger, a portable copy, a test hatch
and the suite each keep their own data and their own key slot, and are
never "the other copy" nor asked to look for one (`checks_here`).

Nothing here shows a window or removes anything: what the person is told
and what each answer does is the owner's to approve first (2026-10-04).
"""
from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path

import paths

#: packaging/store/AppxManifest.xml's identity, as Partner Center gave it.
STORE_FAMILY = "YoavShimron.DeskITApp_d0r2ms77220w6"
#: packaging/DeskIT.iss's AppId — fixed forever (Inno's upgrade key).
INNO_APP_ID = "{9DE44D29-7270-4406-B00A-E6517B5629CE}"
UNINSTALL_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
                 "\\" + INNO_APP_ID + "_is1")
#: Windows' own page for the Store copy — Uninstall is at its foot.
STORE_SETTINGS_URI = f"ms-settings:appsfeatures-app?{STORE_FAMILY}"
#: How the Store copy is started from outside it.
STORE_LAUNCH = f"shell:AppsFolder\\{STORE_FAMILY}!{paths.PACKAGE_APP}"

ERROR_SUCCESS = 0
ERROR_INSUFFICIENT_BUFFER = 122


@dataclass(frozen=True)
class Copy:
    """A released DeskIT installed for this Windows user."""
    kind: str             # "store" | "website"
    version: str          # "1.0.6"
    channel: str = ""     # the Inno copy's CHANNEL word: github | winget
    folder: str = ""      # the Inno copy's {app}
    uninstaller: str = ""  # the Inno copy's unins000.exe

    @property
    def name(self) -> str:
        """How a person tells the two apart: the Store lists this one as
        DeskIT App, the website copy is plain DeskIT."""
        if self.kind == "store":
            return "DeskIT App, from the Microsoft Store"
        if self.channel == "winget":
            return "DeskIT, installed with winget"
        return "DeskIT, from the website"


def checks_here() -> bool:
    """Whether THIS copy is a released one that must look for the other.

    Not the checkout (DeskIT Dev), the Stranger, a portable copy, a copy
    pointed at a DESKIT_HOME, nor anything the suite starts: each of
    those has its own data folder and its own key slot, so a released
    copy beside it is not a second copy of IT."""
    if paths.DEVELOPER or paths.STRANGER or paths.PORTABLE:
        return False
    if os.environ.get("DESKIT_HOME", "").strip():
        return False
    if os.environ.get("DESKIT_SUITE", "").strip():
        return False
    return True


# ---------------------------------------------------------------- the Store

def _packages(family: str) -> list[str]:
    """The full names of `family`'s packages installed for this user —
    kernel32 GetPackagesByPackageFamily, a private handle (the argtypes
    trap). [] on any failure: an unanswerable question is not a copy."""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        call = k32.GetPackagesByPackageFamily
    except (OSError, AttributeError):
        return []
    u32 = ctypes.POINTER(ctypes.c_uint32)
    call.argtypes = [ctypes.c_wchar_p, u32, ctypes.c_void_p, u32, ctypes.c_void_p]
    call.restype = ctypes.c_long
    count, length = ctypes.c_uint32(0), ctypes.c_uint32(0)
    rc = call(family, ctypes.byref(count), None, ctypes.byref(length), None)
    if rc == ERROR_SUCCESS or rc != ERROR_INSUFFICIENT_BUFFER or not count.value:
        return []
    names = (ctypes.c_wchar_p * count.value)()
    buf = ctypes.create_unicode_buffer(length.value)
    if call(family, ctypes.byref(count), names, ctypes.byref(length), buf) != ERROR_SUCCESS:
        return []
    return [names[i] for i in range(count.value) if names[i]]


def version_of(full_name: str) -> str:
    """`YoavShimron.DeskITApp_1.0.6.0_x64__d0r2ms77220w6` -> `1.0.6`: the
    Store's fourth number is always 0 (build_msix.ps1)."""
    parts = full_name.split("_")
    if len(parts) < 2:
        return ""
    numbers = parts[1].split(".")
    if len(numbers) == 4 and numbers[3] == "0":
        numbers = numbers[:3]
    return ".".join(numbers)


def store_copy(packages=_packages) -> Copy | None:
    """The Store copy, when Windows has it installed for this user."""
    names = packages(STORE_FAMILY)
    if not names:
        return None
    return Copy("store", max((version_of(n) for n in names), key=_version_key))


def _version_key(text: str) -> tuple:
    out = []
    for piece in text.split("."):
        out.append(int(piece) if piece.isdigit() else 0)
    return tuple(out)


# -------------------------------------------------------------- the website

def _uninstall_entry() -> dict | None:
    """The Inno install's Uninstall values, or None. HKCU only: the
    installer is per-user (PrivilegesRequired=lowest)."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            values = {}
            for name in ("DisplayVersion", "InstallLocation", "UninstallString"):
                try:
                    values[name] = str(winreg.QueryValueEx(key, name)[0])
                except OSError:
                    values[name] = ""
            return values
    except OSError:
        return None


def _unquote(command: str) -> str:
    """The program of an UninstallString: `"C:\\...\\unins000.exe"`."""
    command = command.strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        return command[1:end] if end > 0 else command[1:]
    return command.split(" /")[0]


def website_copy(entry=_uninstall_entry) -> Copy | None:
    """The website's or winget's copy, when its Uninstall entry is there
    AND its uninstaller is still on the disk — a folder deleted by hand
    leaves an entry that is nobody's copy."""
    values = entry()
    if not values:
        return None
    uninstaller = _unquote(values.get("UninstallString", ""))
    if not uninstaller or not Path(uninstaller).is_file():
        return None
    folder = values.get("InstallLocation", "").rstrip("\\") or str(Path(uninstaller).parent)
    channel, _note = paths.read_channel(Path(folder) / "CHANNEL")
    return Copy("website", values.get("DisplayVersion", ""), channel=channel,
                folder=folder, uninstaller=uninstaller)


# --------------------------------------------------------------- the answer

def this_copy() -> str:
    """"store" inside the package, "website" for an Inno copy."""
    return "store" if paths.PACKAGED else "website"


def other_copy() -> Copy | None:
    """The OTHER released copy installed for this Windows user, or None —
    asked of Windows and the registry, never of the data folder, so it
    is safe before anything is read or written. None everywhere
    `checks_here` says no."""
    if not checks_here():
        return None
    return website_copy() if paths.PACKAGED else store_copy()
