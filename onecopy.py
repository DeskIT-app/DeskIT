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

main.py asks `other_copy()` before `paths.ensure()` on every start of the
app; when there is one, onecopy_window.py says so and the answers below
do what the person picked. The installer asks the same question before it
installs (packaging/one_copy.iss). The owner approved the words, the
pictures and the Store copy as the gold Keep on 2026-10-04.
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


# -------------------------------------------------------------- the answers
#
# What the window's buttons do (onecopy_window.py; the owner approved the
# words and the Store copy as the gold Keep on 2026-10-04):
#
#   from the Store copy,   Keep the Store's   -> remove_website, then start
#   from the Store copy,   Keep the website's -> the hook lines go to the
#                                                website copy, Settings opens
#                                                at DeskIT App, the website
#                                                copy starts waiting for it
#                                                (start_website_waiting), quit
#   from the website copy, Keep the Store's   -> the hook lines go to the
#                                                Store copy, then
#                                                uninstall_self_then_open_store
#   from the website copy, Keep the website's -> Settings opens, the window
#                                                waits for the package to go,
#                                                then start
#
# Nothing is deleted by DeskIT itself but the website copy's program, by
# its own uninstaller, silently — and a silent Inno uninstall KEEPS the
# data (DeskIT.iss: Keep is the only answer a silent uninstall gives), so
# the Store copy goes on with it. The Store copy is removed by Windows'
# own Uninstall button, never by us.

#: A silent uninstall, data kept, no reboot, no window.
UNINSTALL_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
#: Main.py's flag: open the window already waiting for the Store copy to go.
WAITING_FLAG = "--waiting-for-store"


def command_line(argv: list[str]) -> str:
    """One Windows command line: an argument with a space (or nothing) in
    it is put in quotes as it stands — paths, and a cmd /s script whose
    own quotes cmd reads between the first and the last."""
    return " ".join(f'"{a}"' if (" " in a or not a) else a for a in argv)


def start_outside(argv: list[str]) -> bool:
    """Start a program OUTSIDE this package, through WMI (Win32_Process.
    Create, so WmiPrvSE is its parent). Measured 2026-10-04 inside the
    Store package: a plain child process's HKCU delete went to the
    package's private hive and the REAL Uninstall entry stayed — a
    website copy uninstalled by a child of the Store copy would lose its
    files and keep its entry in Installed apps — while a WMI-started one
    deleted the real key; WMI's process lands on the person's own desktop
    (WinSta0\\Default, the session's). Outside the package a detached
    Popen is the same thing and is what runs."""
    line = command_line(argv)
    if not paths.PACKAGED:
        import subprocess
        try:
            # the line as written, not list2cmdline's: cmd.exe /s reads
            # its script between the first and the last quote, and a
            # backslash-escaped quote inside it means nothing to cmd.
            # A HIDDEN console, not none (DETACHED_PROCESS): measured, a
            # cmd with no console at all ran its `ping` pauses in no time
            # and finished its wait before the entry went, and each
            # console child would get a window of its own on the screen.
            subprocess.Popen(line, close_fds=True,
                             creationflags=0x08000000)       # CREATE_NO_WINDOW
            return True
        except OSError:
            return False
    try:
        import win32com.client
        svc = win32com.client.Dispatch("WbemScripting.SWbemLocator").ConnectServer(".", r"root\cimv2")
        cls = svc.Get("Win32_Process")
        params = cls.Methods_("Create").InParameters.SpawnInstance_()
        params.Properties_.Item("CommandLine").Value = line
        result = cls.ExecMethod_("Create", params)
        return int(result.Properties_.Item("ReturnValue").Value) == 0
    except Exception:                                        # noqa: BLE001
        return False


def quit_running(wait_s: float = 15.0, *, sleep=None) -> bool:
    """Ask a running DeskIT to quit and wait for it to go. The kernel
    names are shared between the two copies (measured), so this reaches
    the website copy from inside the Store package too. True when
    nothing runs any more.

    Never from a copy with its own data (`checks_here` False): in the
    checkout, and in every test, the kernel names carry `.dev`, so the
    DeskIT this would reach is the owner's running Dev copy — a suite
    run quit it once (2026-10-04, 22:02:35) before this guard."""
    import time

    import singleton
    sleep = sleep or time.sleep
    if not checks_here():
        return True
    if not singleton.is_running():
        return True
    singleton.request_quit()
    for _ in range(int(wait_s * 4)):
        sleep(0.25)
        if not singleton.is_running():
            return True
    return False


def remove_website(copy: Copy, wait_s: float = 120.0, *, start=start_outside,
                   find=website_copy, sleep=None, quit=None) -> bool:
    """The Store copy keeps itself: the website copy's own uninstaller,
    silently (its data is KEPT), started outside the package; then wait
    for its Uninstall entry to go. True once it has."""
    import time
    sleep = sleep or time.sleep
    (quit or quit_running)(sleep=sleep)
    if not start([copy.uninstaller, *UNINSTALL_ARGS]):
        return False
    for _ in range(int(wait_s * 2)):
        sleep(0.5)
        if find() is None:
            return True
    return False


def uninstall_self_then_open_store(copy: Copy, *, key: str = "",
                                   opener: str = "") -> bool:
    """The website copy gives way to the Store copy: one detached cmd
    waits two seconds for this process to be gone, runs this copy's
    uninstaller silently (the data is kept), waits for its Uninstall
    entry to go and opens DeskIT App — which finds no other copy and
    goes on with the same data. The caller quits at once. (`key` and
    `opener` are a test's: another entry to wait for, another program
    to start at the end.)"""
    key = key or "HKCU\\" + UNINSTALL_KEY
    opener = opener or f"explorer.exe {STORE_LAUNCH}"
    script = (f'ping -n 3 127.0.0.1 >nul & "{copy.uninstaller}" {" ".join(UNINSTALL_ARGS)} & '
              f'for /l %i in (1,1,90) do (reg query "{key}" >nul 2>&1 || '
              f'(start "" {opener} & exit /b) & ping -n 2 127.0.0.1 >nul)')
    return start_outside(["cmd.exe", "/d", "/s", "/c", script])


def open_store_settings() -> bool:
    """Windows' own page for DeskIT App: Uninstall is at its foot."""
    try:
        os.startfile(STORE_SETTINGS_URI)                     # noqa: S606
        return True
    except OSError:
        return False


def start_website_waiting(copy: Copy, *, start=start_outside) -> bool:
    """The Store copy is going and the website copy is kept: start the
    website copy outside the package (a child would die with it),
    already waiting for the package to go."""
    folder = Path(copy.folder)
    return start([str(folder / "python" / "pythonw.exe"),
                  str(folder / "app" / "deskit.pyw"), WAITING_FLAG])


def move_claude_door(to: str, website: Copy, settings_path=None) -> bool:
    """When one of the two released copies holds Claude Code's hook
    lines, the copy being kept takes them, so no line is left naming a
    program that is about to be gone. `to` is "store" or "website".
    Lines naming the checkout (DeskIT Dev) or nobody's are left alone.
    True if the file changed."""
    import notify_hook
    settings_path = settings_path or notify_hook.DEFAULT_SETTINGS
    found = notify_hook.hook_script(settings_path)
    if found is None:
        return False
    store_line = notify_hook._same_file(found, notify_hook.alias_path())
    website_line = bool(website.folder) and os.path.normcase(
        os.path.normpath(found)).startswith(os.path.normcase(os.path.normpath(website.folder)) + os.sep)
    if not (store_line or website_line):
        return False
    folder = Path(website.folder)
    if to == "store":
        return notify_hook.install_hook(settings_path, python=str(folder / "python" / "pythonw.exe"),
                                        script=str(folder / "app" / "notify_hook.py"), alias=True)
    return notify_hook.install_hook(settings_path, python=str(folder / "python" / "pythonw.exe"),
                                    script=str(folder / "app" / "notify_hook.py"), alias=False)
