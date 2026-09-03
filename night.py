"""Night mode: the screen goes dark, the machine stays awake.

The reason it exists: the owner drives this computer from his phone at
night, through Claude, and every morning found it asleep. Diagnosed on
2026-09-02 with `powercfg /a` and the System event log before a line of
this was written: the machine does classic S3 standby (no Modern
Standby), `Sleep after` on AC is 30 minutes, hibernate is off, and the
restarts in the log are all the owner's own or Windows Update at ten in
the morning. So "it turned off" is the idle timer, and an idle timer is
exactly what one API call holds back.

THE MECHANISM, and what it deliberately is not:

- `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`. No
  admin, no fake mouse, no registry, and Windows drops it by itself when
  the process dies — the one failure mode a fake-input loop cannot
  promise. It is PER THREAD and lasts only while that thread lives, so
  `Hold` is a thread that makes the call and then waits on an event; a
  call-and-return would hold nothing. It is released with a second call
  carrying `ES_CONTINUOUS` alone.
- Without `ES_DISPLAY_REQUIRED`. The screen is supposed to go off — that
  is half the point — and the monitor timer is what turns it off again
  after a stray mouse nudge lights it.
- The screen is put out directly as well, so the owner does not sit
  through the five-minute monitor timer: `WM_SYSCOMMAND / SC_MONITORPOWER`
  broadcast to every top-level window. Broadcast through
  `SendMessageTimeoutW` with `SMTO_ABORTIFHUNG`, on its own thread —
  plain `SendMessage` to HWND_BROADCAST waits on every window in turn,
  and one hung window would hang whoever asked. The mouse turns the
  screen back on the instant it moves, and the click that pressed the
  button is followed by exactly that, so the command goes out twice: at
  once, and again a few seconds later ([night] screen_off_again_s).
- OPTIONALLY the sleep timers are pinned to "never" through `powercfg
  /change` (works unelevated, measured) and put back on the way out —
  [night] pin_timeouts, OFF by default because the hold above already
  covers S3 and a belt-and-braces setting is a second thing to restore.

WHAT SURVIVES A CRASH. `night_state.json` is written beside the app the
moment night mode goes on and removed when it goes off. Its one job is
the pinned timers: the execution state dies with the process and needs
no cleanup, but a `powercfg /change` outlives everything, so a leftover
file at the next start means "put those numbers back" (`recover`). The
file also records when and by whom, which is what the dashboard shows.
Every entry and exit is a line in `night.log` with a timestamp, followed
by what the probe found — so a morning that went wrong can be read.

THE TRUTH CHECK. `powercfg /requests` is the spec's way to see the hold,
and it needs an elevated prompt; this app does not run elevated. What
does work unelevated is `CallNtPowerInformation(SystemExecutionState)`,
which returns the ES_* flags currently in force system-wide — the same
fact `/requests` lists per process, without the names. `probe()` reads
both (the second only when it can) and everything else the spec lists
as a way to lose the machine overnight even though it is awake: the
network adapter's "let the computer turn this off" flag (WMI, read
only), Windows Update's active hours (registry), and whether Claude is
running (tasklist). Reading is all it does; the fixes are the owner's,
and the dashboard says which.

Windows-only by construction, like the rest of the app. Every Win32
handle here is a PRIVATE `ctypes.WinDLL` — declaring argtypes on
`ctypes.windll.user32` would change them for the other five modules
that share that cached object (see AGENTS.md, capture.py).
"""
from __future__ import annotations

import atexit
import ctypes
import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

log = logging.getLogger("app")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

HWND_BROADCAST = 0xFFFF
WM_SYSCOMMAND = 0x0112
SC_MONITORPOWER = 0xF170
MONITOR_OFF = 2
MONITOR_ON = -1
SMTO_NORMAL = 0x0000
SMTO_ABORTIFHUNG = 0x0002
SEND_TIMEOUT_MS = 2000

# CallNtPowerInformation's information level for the system-wide ES_*
# flags. Documented as SystemExecutionState = 16 in ntpoapi.h.
SYSTEM_EXECUTION_STATE = 16

CREATE_NO_WINDOW = 0x08000000     # every spawn under pythonw needs it
STATE_NAME = "night_state.json"
LOG_NAME = "night.log"

_kernel32 = None
_user32 = None
_powrprof = None


def _dlls():
    """The three private handles, built on first use so importing this
    module costs nothing and so tests that never touch Win32 do not
    either."""
    global _kernel32, _user32, _powrprof
    if _kernel32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.SetThreadExecutionState.restype = ctypes.c_uint32
        k.SetThreadExecutionState.argtypes = [ctypes.c_uint32]
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.SendMessageTimeoutW.restype = ctypes.c_ssize_t
        u.SendMessageTimeoutW.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t,
            ctypes.c_ssize_t, ctypes.c_uint, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_size_t)]
        p = ctypes.WinDLL("powrprof")
        p.CallNtPowerInformation.restype = ctypes.c_int32
        p.CallNtPowerInformation.argtypes = [
            ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.c_uint32]
        _kernel32, _user32, _powrprof = k, u, p
    return _kernel32, _user32, _powrprof


# --------------------------------------------------------------- the hold

def set_execution_state(flags: int) -> int:
    """The raw call. Returns the PREVIOUS state, or 0 when Windows
    refused — which is the only failure it reports."""
    k, _u, _p = _dlls()
    return int(k.SetThreadExecutionState(flags))


def system_execution_state() -> int | None:
    """The ES_* flags in force across the whole machine right now, from
    the kernel's own bookkeeping — what `powercfg /requests` lists, minus
    the names, and readable without admin. None if the call failed."""
    try:
        _k, _u, p = _dlls()
        state = ctypes.c_uint32(0)
        status = p.CallNtPowerInformation(SYSTEM_EXECUTION_STATE, None, 0,
                                          ctypes.byref(state),
                                          ctypes.sizeof(state))
        if status != 0:
            return None
        return int(state.value)
    except Exception:            # noqa: BLE001 — a probe, never fatal
        return None


class Hold:
    """One thread that asks Windows to stay awake and lives for as long
    as the request should.

    A thread and not a call because the state is per-thread and Windows
    forgets it when the thread ends — the spec's warning, and the bug the
    obvious one-liner has. Daemon, deliberately: the process leaving is
    the one release that needs no code (Windows drops a dead thread's
    state), and a non-daemon thread would be the one thing that could
    keep a quitting app alive with its hotkey gone.
    """

    def __init__(self, flags: int = ES_CONTINUOUS | ES_SYSTEM_REQUIRED,
                 setter: Callable[[int], int] | None = None) -> None:
        self.flags = flags
        self._setter = setter or set_execution_state
        self._release = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        # What the API answered on the way in: the previous flags, or 0
        # for a refusal. The dashboard's "held" is this being non-zero
        # AND the thread still standing.
        self.previous: int | None = None

    def start(self) -> bool:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="night-hold")
        self._thread.start()
        self._ready.wait(timeout=3)
        return bool(self.previous)

    def _run(self) -> None:
        try:
            self.previous = self._setter(self.flags)
        except Exception as e:        # noqa: BLE001
            log.warning("SetThreadExecutionState failed: %s", e)
            self.previous = 0
        finally:
            self._ready.set()
        if not self.previous:
            return
        self._release.wait()
        try:
            self._setter(ES_CONTINUOUS)
        except Exception:             # noqa: BLE001
            pass

    def stop(self) -> None:
        self._release.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    @property
    def alive(self) -> bool:
        return bool(self.previous) and self._thread is not None \
            and self._thread.is_alive() and not self._release.is_set()


# -------------------------------------------------------------- the screen

def send_monitor_power(state: int = MONITOR_OFF,
                       timeout_ms: int = SEND_TIMEOUT_MS) -> bool:
    """Broadcast SC_MONITORPOWER. True if the broadcast went out; False
    if some window sat on it past the timeout (SMTO_ABORTIFHUNG gives up
    on a hung one rather than waiting on it forever).

    Never call this from the keyboard hook or the control thread: with
    HWND_BROADCAST the timeout is PER WINDOW, and measured on this
    machine the ON broadcast took 626 ms across a busy desktop.
    """
    _k, u, _p = _dlls()
    result = ctypes.c_size_t(0)
    ok = u.SendMessageTimeoutW(HWND_BROADCAST, WM_SYSCOMMAND,
                               SC_MONITORPOWER, state,
                               SMTO_NORMAL | SMTO_ABORTIFHUNG, timeout_ms,
                               ctypes.byref(result))
    return bool(ok)


# ------------------------------------------------------------ the timers

def _run_powercfg(args: list[str], timeout: float = 15) -> tuple[int, str]:
    """powercfg, windowless. (exit code, combined output)."""
    try:
        done = subprocess.run(
            ["powercfg", *args], capture_output=True, text=True,
            timeout=timeout, creationflags=CREATE_NO_WINDOW,
            encoding="utf-8", errors="replace")
    except Exception as e:            # noqa: BLE001
        return 1, f"{type(e).__name__}: {e}"
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _ac_index(text: str) -> int | None:
    """The 'Current AC Power Setting Index: 0x...' line of a query, as an
    int. None if it is not there (a refusal, or a locale that spells the
    line differently — the hex prefix is the anchor, not the words)."""
    for line in text.splitlines():
        if "AC" in line and "0x" in line and "Index" in line:
            try:
                return int(line.split("0x")[-1].strip(), 16)
            except ValueError:
                continue
    return None


def read_timeouts(run=None) -> dict:
    """The sleep and hibernate idle timers on AC, in minutes. Missing
    keys mean powercfg would not say."""
    run = run or _run_powercfg
    out: dict = {}
    for key, alias in (("standby_ac", "STANDBYIDLE"),
                       ("hibernate_ac", "HIBERNATEIDLE")):
        code, text = run(["/query", "SCHEME_CURRENT", "SUB_SLEEP", alias])
        seconds = _ac_index(text) if code == 0 else None
        if seconds is not None:
            out[key] = round(seconds / 60)
    return out


def write_timeouts(values: dict, run=None) -> list[str]:
    """Set the AC timers (minutes; 0 = never). Returns the lines that
    failed, empty when all went through."""
    run = run or _run_powercfg
    failed = []
    for key, name in (("standby_ac", "standby-timeout-ac"),
                      ("hibernate_ac", "hibernate-timeout-ac")):
        if key not in values:
            continue
        code, text = run(["/change", name, str(int(values[key]))])
        if code != 0:
            failed.append(f"{name}: {text.strip() or code}")
    return failed


# ---------------------------------------------------------------- probes

def _powershell(script: str, timeout: float = 20) -> str | None:
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW, encoding="utf-8",
            errors="replace")
    except Exception:                 # noqa: BLE001
        return None
    return done.stdout if done.returncode == 0 else None


def adapter_power_saving() -> list[dict] | None:
    """Which physical network adapters Windows is allowed to power down
    to save energy — the "Allow the computer to turn off this device"
    box in Device Manager, read through WMI's MSPower_DeviceEnable and
    matched to the adapter by PnP id. A machine that is awake with its
    network card asleep is the commonest "it was on but I could not
    reach it". Read-only: changing it takes an elevated Device Manager.
    None when the read failed."""
    script = (
        # UTF-8 out, or PowerShell writes the bidi marks Windows puts in a
        # Hebrew-locale adapter name (U+200F, twice, before "Ethernet")
        # as "??" — measured 2026-09-02.
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        "$pm = Get-CimInstance -Namespace root\\wmi -ClassName "
        "MSPower_DeviceEnable -ErrorAction SilentlyContinue; "
        "Get-NetAdapter -Physical -ErrorAction SilentlyContinue | "
        "ForEach-Object { $a = $_; $id = $a.PnPDeviceID; "
        "$m = $pm | Where-Object { $id -and $_.InstanceName -like "
        "($id + '*') } | Select-Object -First 1; "
        "[pscustomobject]@{ name = $a.Name; up = ($a.Status -eq 'Up'); "
        "saving = $(if ($m) { [bool]$m.Enable } else { $null }) } } | "
        "ConvertTo-Json -Compress")
    out = _powershell(script)
    if not out or not out.strip():
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    if isinstance(data, dict):
        data = [data]
    return [{"name": str(d.get("name", "")).strip("\u200f\u200e? "),
             "up": bool(d.get("up")), "saving": d.get("saving")}
            for d in data if isinstance(d, dict)]


def active_hours() -> tuple[int, int] | None:
    """Windows Update's active hours (start, end) in whole hours, from
    the registry. A restart is allowed OUTSIDE them, which for the
    shipped 9→2 means anywhere between two and nine in the morning."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
                            ) as key:
            start = int(winreg.QueryValueEx(key, "ActiveHoursStart")[0])
            end = int(winreg.QueryValueEx(key, "ActiveHoursEnd")[0])
        return start, end
    except Exception:                 # noqa: BLE001
        return None


def hours_cover_night(window: tuple[int, int] | None,
                      night: tuple[int, int] = (23, 7)) -> bool | None:
    """Does the active-hours window contain the whole of `night`? Both
    are clock ranges that may wrap midnight. None when unknown."""
    if window is None:
        return None
    start, end = window
    span = (end - start) % 24
    if span == 0:
        return False

    def inside(hour: int) -> bool:
        return (hour - start) % 24 < span
    # Hour SLOTS, end exclusive on both sides: a window of 23->7 holds
    # the slots 23, 0 ... 6, which is the whole of a night of 23->7.
    n_start, n_end = night
    n_span = (n_end - n_start) % 24
    return all(inside((n_start + h) % 24) for h in range(n_span))


def process_count(image: str = "claude.exe") -> int | None:
    """How many processes of that image name are running. None if
    tasklist would not answer."""
    try:
        done = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
            capture_output=True, text=True, timeout=15,
            creationflags=CREATE_NO_WINDOW, encoding="utf-8",
            errors="replace")
    except Exception:                 # noqa: BLE001
        return None
    if done.returncode != 0:
        return None
    return sum(1 for line in done.stdout.splitlines()
               if line.lower().startswith(image.lower()))


# ------------------------------------------------------------- the vitals
#
# What the machine is carrying, in one read. Written after two mornings
# running (2026-09-02, 2026-09-03) the owner came home to a machine that
# crawled until this app was stopped — and every log on it, this app's,
# Ollama's, the System log, the task scheduler, had NOTHING between the
# last phone dictation at 11:09 and the key at 14:54. Nothing had run;
# something had grown, or Windows had paged the world out on the ~2 GB
# of RAM this machine keeps free with everything loaded (measured: 15.9
# GB, 12.3 GB in working sets, 2.4 GB of non-paged kernel pool). This is
# the log that was missing: a line every [night] vitals_minutes while
# night mode is on, and one more at the moment it goes off — the state
# the owner walked in on, before the stop that cures it.
#
# All of it is Win32 through ctypes (~30 ms, no subprocess) except the
# GPU number, which is nvidia-smi (~150 ms) and simply absent without it.

# The per-process list comes from ntdll, not from OpenProcess. Measured
# 2026-09-03, and it is the whole reason this is written twice: the
# OpenProcess version named "msedgewebview2 holds 17,654" on a machine
# where nvcontainer.exe was holding 812,918 of 984,349 — a service
# running as SYSTEM, which a non-elevated OpenProcess is simply refused,
# and therefore invisible. The processes worth naming in a leak are
# exactly the ones that cannot be opened. NtQuerySystemInformation
# answers for every process unelevated, in one call.
SYSTEM_PROCESS_INFORMATION = 5
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_uint32),
                ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64)]


class _PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_uint32),
                ("CommitTotal", ctypes.c_size_t),
                ("CommitLimit", ctypes.c_size_t),
                ("CommitPeak", ctypes.c_size_t),
                ("PhysicalTotal", ctypes.c_size_t),
                ("PhysicalAvailable", ctypes.c_size_t),
                ("SystemCache", ctypes.c_size_t),
                ("KernelTotal", ctypes.c_size_t),
                ("KernelPaged", ctypes.c_size_t),
                ("KernelNonpaged", ctypes.c_size_t),
                ("PageSize", ctypes.c_size_t),
                ("HandleCount", ctypes.c_uint32),
                ("ProcessCount", ctypes.c_uint32),
                ("ThreadCount", ctypes.c_uint32)]


class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_uint32),
                ("PageFaultCount", ctypes.c_uint32),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", ctypes.c_ushort),
                ("MaximumLength", ctypes.c_ushort),
                ("Buffer", ctypes.c_void_p)]


class _SYSTEM_PROCESS_INFORMATION(ctypes.Structure):
    """ntdll's per-process record, in ntddk's field order. Only the first
    few members are read here; the rest are declared so ctypes lays out
    the x64 padding exactly as the kernel does, and so the next member
    anyone wants is already named. Verified against Get-Process on this
    machine (handle counts and working sets agree)."""
    _fields_ = [("NextEntryOffset", ctypes.c_uint32),
                ("NumberOfThreads", ctypes.c_uint32),
                ("WorkingSetPrivateSize", ctypes.c_int64),
                ("HardFaultCount", ctypes.c_uint32),
                ("NumberOfThreadsHighWatermark", ctypes.c_uint32),
                ("CycleTime", ctypes.c_uint64),
                ("CreateTime", ctypes.c_int64),
                ("UserTime", ctypes.c_int64),
                ("KernelTime", ctypes.c_int64),
                ("ImageName", _UNICODE_STRING),
                ("BasePriority", ctypes.c_int32),
                ("UniqueProcessId", ctypes.c_void_p),
                ("InheritedFromUniqueProcessId", ctypes.c_void_p),
                ("HandleCount", ctypes.c_uint32),
                ("SessionId", ctypes.c_uint32),
                ("UniqueProcessKey", ctypes.c_size_t),
                ("PeakVirtualSize", ctypes.c_size_t),
                ("VirtualSize", ctypes.c_size_t),
                ("PageFaultCount", ctypes.c_uint32),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivatePageCount", ctypes.c_size_t)]


_vitals_kernel32 = None
_vitals_ntdll = None


def _nt():
    """A private ntdll handle for the process list."""
    global _vitals_ntdll
    if _vitals_ntdll is None:
        n = ctypes.WinDLL("ntdll")
        n.NtQuerySystemInformation.restype = ctypes.c_int32
        n.NtQuerySystemInformation.argtypes = [
            ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32)]
        _vitals_ntdll = n
    return _vitals_ntdll


def processes() -> list[tuple[str, int, int, int]]:
    """Every process as (image, working set, commit, handles). Bytes for
    the two memory numbers. Empty when ntdll refuses.

    `PagefileUsage` is the commit charge — the same number
    PROCESS_MEMORY_COUNTERS_EX calls PrivateUsage and Task Manager calls
    "Commit size", so the rows here and the self_* pair above are the
    same measurement.
    """
    nt = _nt()
    size = 1 << 20
    buf = None
    for _attempt in range(8):
        buf = ctypes.create_string_buffer(size)
        need = ctypes.c_uint32(0)
        status = nt.NtQuerySystemInformation(
            SYSTEM_PROCESS_INFORMATION, buf, size,
            ctypes.byref(need)) & 0xFFFFFFFF
        if status == STATUS_INFO_LENGTH_MISMATCH:
            # It grew between the sizing and the read: ask for what it
            # said it needs, plus room for the processes started since.
            size = max(int(need.value) + (1 << 16), size * 2)
            continue
        if status != 0:
            return []
        break
    else:
        return []
    out: list[tuple[str, int, int, int]] = []
    offset = 0
    limit = len(buf) - ctypes.sizeof(_SYSTEM_PROCESS_INFORMATION)
    while 0 <= offset <= limit:
        rec = _SYSTEM_PROCESS_INFORMATION.from_buffer(buf, offset)
        name = ""
        if rec.ImageName.Buffer and rec.ImageName.Length:
            try:
                name = ctypes.wstring_at(rec.ImageName.Buffer,
                                         rec.ImageName.Length // 2)
            except Exception:         # noqa: BLE001
                name = ""
        if name.lower().endswith(".exe"):
            name = name[:-4]
        # pid 0 and 4 have no image name; they are the kernel itself.
        out.append((name or "System", int(rec.WorkingSetSize),
                    int(rec.PagefileUsage), int(rec.HandleCount)))
        step = int(rec.NextEntryOffset)
        if step <= 0:
            break
        offset += step
    return out


def _vk():
    """A fourth private kernel32 handle, for the psapi family (K32* lives
    in kernel32 since Windows 7). Separate from _dlls() so the hold's
    argtypes and these never touch each other."""
    global _vitals_kernel32
    if _vitals_kernel32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GlobalMemoryStatusEx.restype = ctypes.c_int
        k.GlobalMemoryStatusEx.argtypes = [ctypes.c_void_p]
        k.K32GetPerformanceInfo.restype = ctypes.c_int
        k.K32GetPerformanceInfo.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.K32GetProcessMemoryInfo.restype = ctypes.c_int
        k.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                              ctypes.c_uint32]
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.GetCurrentProcess.argtypes = []
        _vitals_kernel32 = k
    return _vitals_kernel32


def gpu_memory(timeout: float = 5) -> tuple[int, int] | None:
    """(used, total) bytes on the first NVIDIA GPU, from nvidia-smi. None
    without one, or when it does not answer."""
    try:
        done = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW, encoding="utf-8",
            errors="replace")
        used, total = done.stdout.strip().splitlines()[0].split(",")
        return int(used) << 20, int(total) << 20
    except Exception:                 # noqa: BLE001
        return None


def vitals(top: int = 5, gpu: bool = True) -> dict:
    """The machine's memory right now. Bytes throughout.

    ram_total / ram_free, commit / commit_limit, nonpaged (the kernel's
    non-paged pool — where driver-pinned memory lands), processes,
    threads, handles; self_ws / self_private for this process; `top`,
    the heaviest programs by working set as (image name, working set,
    private bytes, process count), grouped by image the way Task
    Manager groups them; `handles_top`, the ONE image holding the most
    handles as (name, count); and `gpu` as (used, total) or None.

    handles_top earns its place: the 2026-09-02/03 slowdowns were a
    handle leak, and a machine-wide total alone does not say whose.
    Measured that afternoon: nvcontainer.exe holding 812,918 of the
    machine's 984,349, a Thread+Event pair per flap of a failing USB
    webcam, at ~6/s whether or not this app was running. What the total
    hides is exactly the name that ends the argument.

    Every process is counted, protected and SYSTEM ones included — see
    processes() for why that is not the obvious implementation.
    """
    k = _vk()
    out: dict = {"at": time.time()}
    ms = _MEMORYSTATUSEX()
    ms.dwLength = ctypes.sizeof(ms)
    if k.GlobalMemoryStatusEx(ctypes.byref(ms)):
        out["ram_total"] = int(ms.ullTotalPhys)
        out["ram_free"] = int(ms.ullAvailPhys)
    pi = _PERFORMANCE_INFORMATION()
    pi.cb = ctypes.sizeof(pi)
    if k.K32GetPerformanceInfo(ctypes.byref(pi), pi.cb):
        page = int(pi.PageSize) or 4096
        out["commit"] = int(pi.CommitTotal) * page
        out["commit_limit"] = int(pi.CommitLimit) * page
        out["nonpaged"] = int(pi.KernelNonpaged) * page
        out["processes"] = int(pi.ProcessCount)
        out["threads"] = int(pi.ThreadCount)
        out["handles"] = int(pi.HandleCount)
    pm = _PROCESS_MEMORY_COUNTERS_EX()
    pm.cb = ctypes.sizeof(pm)
    if k.K32GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(pm),
                                 pm.cb):
        out["self_ws"] = int(pm.WorkingSetSize)
        out["self_private"] = int(pm.PrivateUsage)

    by_name: dict[str, list[int]] = {}
    for name, ws, commit, handles in processes():
        row = by_name.setdefault(name, [0, 0, 0, 0])
        row[0] += ws
        row[1] += commit
        row[2] += 1
        row[3] += handles
    rows = [(n, ws, pv, c, hc) for n, (ws, pv, c, hc) in by_name.items()]
    out["top"] = sorted(((n, ws, pv, c) for n, ws, pv, c, _hc in rows),
                        key=lambda r: r[1], reverse=True)[:max(0, int(top))]
    out["handles_top"] = max(((n, hc) for n, _ws, _pv, _c, hc in rows),
                             key=lambda r: r[1], default=None)
    out["gpu"] = gpu_memory() if gpu else None
    return out


def _gb(n) -> str:
    x = n / (1 << 30)
    return f"{x:.2f}" if x < 1 else f"{x:.1f}"


def vitals_line(v: dict) -> str:
    """One line of night.log from vitals(): the numbers that decide
    whether the machine is still usable, then the programs holding them."""
    parts = []
    if "ram_total" in v:
        parts.append(f"RAM free {_gb(v['ram_free'])} of "
                     f"{_gb(v['ram_total'])} GB")
    if "commit" in v:
        parts.append(f"commit {_gb(v['commit'])} of "
                     f"{_gb(v['commit_limit'])} GB")
        parts.append(f"nonpaged {_gb(v['nonpaged'])} GB")
    if v.get("gpu"):
        used, total = v["gpu"]
        parts.append(f"GPU {_gb(used)} of {_gb(total)} GB")
    if "self_ws" in v:
        parts.append(f"this app {_gb(v['self_ws'])} GB in RAM, "
                     f"{_gb(v['self_private'])} GB committed")
    if v.get("top"):
        parts.append("heaviest (in RAM/committed): " + ", ".join(
            f"{name} {_gb(ws)}/{_gb(pv)} GB"
            + (f" x{count}" if count > 1 else "")
            for name, ws, pv, count in v["top"]))
    if "processes" in v:
        held = ""
        if v.get("handles_top"):
            name, count = v["handles_top"]
            held = f" ({name} holds {count})"
        parts.append(f"{v['processes']} processes, {v['threads']} threads, "
                     f"{v['handles']} handles{held}")
    return " | ".join(parts)


def is_elevated() -> bool:
    try:
        return bool(ctypes.WinDLL("shell32").IsUserAnAdmin())
    except Exception:                 # noqa: BLE001
        return False


def probe(run=None) -> dict:
    """Everything worth knowing about whether this machine will still be
    reachable in the morning. Slow — two or three seconds, most of it
    PowerShell — so never on the control thread or the hook; the
    dashboard runs it on a worker and the engine on a background thread
    after entering night mode."""
    run = run or _run_powercfg
    out: dict = {"at": time.time(), "elevated": is_elevated()}
    flags = system_execution_state()
    out["execution_state"] = flags
    out["system_required"] = None if flags is None else bool(
        flags & ES_SYSTEM_REQUIRED)
    out["display_required"] = None if flags is None else bool(
        flags & ES_DISPLAY_REQUIRED)
    code, text = run(["/requests"])
    if code == 0 and "administrator" not in text.lower():
        out["requests"] = text.strip()
    else:
        out["requests"] = None
    code, text = run(["/a"])
    out["standby"] = None
    if code == 0:
        available = text.split("not available")[0]
        if "S0 Low Power Idle" in available:
            out["standby"] = "S0"
        elif "(S3)" in available:
            out["standby"] = "S3"
        else:
            out["standby"] = "none"
    out["timeouts"] = read_timeouts(run)
    out["adapters"] = adapter_power_saving()
    out["active_hours"] = active_hours()
    out["claude"] = process_count("claude.exe")
    return out


def verdict(state: dict, probe_result: dict | None) -> list[tuple[str, str, str]]:
    """The probe as rows for a screen: (label, sentence, tone), tone being
    good | warn | bad | dim. Pure, so it can be tested without a machine
    to probe."""
    rows: list[tuple[str, str, str]] = []
    active = bool(state.get("active"))
    held = bool(state.get("held"))
    p = probe_result or {}

    sys_req = p.get("system_required")
    if active and held and sys_req:
        rows.append(("Sleep hold", "held — this app is keeping the machine "
                     "awake (SYSTEM_REQUIRED is set)", "good"))
    elif active and held and sys_req is False:
        rows.append(("Sleep hold", "this app asked, but Windows reports no "
                     "hold — do not trust tonight to it", "bad"))
    elif active and not held:
        rows.append(("Sleep hold", "night mode is on but the hold is not "
                     "standing — turn it off and on again", "bad"))
    elif sys_req:
        rows.append(("Sleep hold", "another program is holding the machine "
                     "awake right now; night mode is off", "dim"))
    elif sys_req is None:
        rows.append(("Sleep hold", "could not be read", "dim"))
    else:
        rows.append(("Sleep hold", "nothing is holding the machine awake",
                     "dim" if not active else "bad"))

    requests = p.get("requests")
    if requests:
        lines = [ln.strip() for ln in requests.splitlines() if ln.strip()]
        rows.append(("powercfg /requests", "  ·  ".join(lines)[:220], "dim"))
    elif p:
        rows.append(("powercfg /requests", "needs an administrator prompt — "
                     "the hold above is read from the kernel instead",
                     "dim"))

    timeouts = p.get("timeouts") or {}
    standby = timeouts.get("standby_ac")
    if standby is None:
        rows.append(("Sleep after (plugged in)", "unknown", "dim"))
    elif standby == 0:
        rows.append(("Sleep after (plugged in)",
                     "never" + (" — pinned by night mode"
                                if state.get("pinned") else ""), "good"))
    else:
        tone = "good" if (active and held) else "warn"
        rows.append(("Sleep after (plugged in)",
                     f"{standby} min — the timer night mode holds back",
                     tone))
    kind = p.get("standby")
    if kind == "S0":
        rows.append(("Standby type", "Modern Standby (S0) — the hold is "
                     "honoured, but check in the morning", "dim"))
    elif kind == "S3":
        rows.append(("Standby type", "classic sleep (S3) — exactly what "
                     "SYSTEM_REQUIRED prevents", "good"))
    elif kind == "none":
        rows.append(("Standby type", "this machine cannot sleep at all",
                     "good"))

    adapters = p.get("adapters")
    if adapters is None:
        if p:
            rows.append(("Network adapter", "could not be read", "dim"))
    else:
        up = [a for a in adapters if a.get("up")] or adapters
        saving = [a["name"] for a in up if a.get("saving") is True]
        if saving:
            rows.append(("Network adapter",
                         f"{', '.join(saving)}: Windows may power it down "
                         "to save energy — untick 'Allow the computer to "
                         "turn off this device' in Device Manager", "warn"))
        elif up:
            rows.append(("Network adapter",
                         f"{', '.join(a['name'] for a in up)}: keeps its "
                         "power", "good"))

    hours = p.get("active_hours")
    if hours is not None:
        start, end = hours
        covered = hours_cover_night(hours)
        rows.append(("Update active hours",
                     f"{start:02d}:00–{end:02d}:00"
                     + (" — covers the night" if covered else
                        " — Windows may restart for an update outside "
                        "them, i.e. during the night"),
                     "good" if covered else "warn"))
    elif p:
        rows.append(("Update active hours", "not set", "dim"))

    claude = p.get("claude")
    if claude is None:
        if p:
            rows.append(("Claude", "could not be checked", "dim"))
    elif claude:
        rows.append(("Claude", f"running ({claude} process"
                     f"{'' if claude == 1 else 'es'})", "good"))
    else:
        rows.append(("Claude", "not running — nothing on this machine will "
                     "answer the phone", "warn"))
    return rows


# ---------------------------------------------------------------- engine

def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Engine:
    """Night mode for one process: on, off, the screen, and the truth.

    All entry points are cheap and thread-safe. Anything slow — the
    broadcast, the probe — is handed to a thread, because the two
    callers are the keyboard hook (300 ms before Windows drops it) and
    the control thread (the dashboard's status poll waits on it).
    """

    def __init__(self, app_dir: Path, cfg=None, *,
                 hold_factory: Callable[[], Hold] = Hold,
                 sender: Callable[[int], bool] | None = None,
                 run=None, clock: Callable[[], float] = time.time,
                 vitals_fn: Callable[[], str] | None = None) -> None:
        self.app_dir = Path(app_dir)
        self.state_path = self.app_dir / STATE_NAME
        self.log_path = self.app_dir / LOG_NAME
        self.pin_timeouts = bool(getattr(cfg, "pin_timeouts", False))
        self.again_s = int(getattr(cfg, "screen_off_again_s", 3))
        self.vitals_minutes = int(getattr(cfg, "vitals_minutes", 10))
        self._hold_factory = hold_factory
        self._sender = sender or send_monitor_power
        self._run = run or _run_powercfg
        self._clock = clock
        self._vitals = vitals_fn or (lambda: vitals_line(vitals()))
        self._vitals_stop = threading.Event()
        self._lock = threading.RLock()
        self._hold: Hold | None = None
        self._since: float | None = None
        self._by = ""
        self._saved: dict | None = None
        self._screen_at: float | None = None
        self._last_probe: dict | None = None
        # The process leaving is covered twice: main()'s finally calls
        # off() through App.stop(), and this catches the exits that never
        # reach it. release() is a no-op when there is nothing to do.
        atexit.register(self.release)

    # -- state --

    @property
    def active(self) -> bool:
        return self._hold is not None

    @property
    def last_probe(self) -> dict | None:
        return self._last_probe

    def state(self) -> dict:
        """What the dashboard draws. Cheap: no I/O."""
        with self._lock:
            hold = self._hold
            since = self._since
            return {
                "active": hold is not None,
                "held": bool(hold is not None and hold.alive),
                "since": since,
                "seconds": (round(self._clock() - since) if since else 0),
                "by": self._by,
                "pinned": self._saved is not None,
                "screen_off_at": self._screen_at,
            }

    # -- switches --

    def on(self, *, by: str = "dashboard") -> dict:
        """Enter night mode. Idempotent: a second press puts the screen
        out again, which is what a second press means at 2 a.m."""
        with self._lock:
            if self._hold is not None:
                self.screen_off()
                return self.state()
            hold = self._hold_factory()
            if not hold.start():
                self._log(f"ON refused by {by}: SetThreadExecutionState "
                          "returned 0")
                log.warning("night mode: Windows refused the wake hold")
                return {"ok": False, "error": "Windows refused the wake "
                        "hold (SetThreadExecutionState returned 0)",
                        **self.state()}
            saved = None
            if self.pin_timeouts:
                saved = read_timeouts(self._run)
                failed = write_timeouts({k: 0 for k in saved}, self._run)
                if failed:
                    log.warning("night mode: could not pin the sleep "
                                "timers (%s)", "; ".join(failed))
            self._hold = hold
            self._since = self._clock()
            self._by = by
            self._saved = saved
            self._write_state()
            self._log(f"ON by {by} | previous execution state "
                      f"0x{hold.previous:08x}"
                      + (f" | timers saved {saved}, pinned to never"
                         if saved else ""))
            log.info("night mode ON (%s) — the machine stays awake, the "
                     "screen goes off; ctrl+alt+n or the dashboard turns "
                     "it off", by)
            self.screen_off()
            threading.Thread(target=self._probe_to_log, daemon=True,
                             name="night-probe").start()
            if self.vitals_minutes > 0:
                self._vitals_stop = threading.Event()
                threading.Thread(target=self._vitals_worker,
                                 args=(self._vitals_stop,), daemon=True,
                                 name="night-vitals").start()
            return self.state()

    def off(self, *, by: str = "dashboard") -> dict:
        with self._lock:
            hold = self._hold
            if hold is None:
                return self.state()
            hold.stop()
            restored = ""
            if self._saved:
                failed = write_timeouts(self._saved, self._run)
                restored = (f" | timers restored {self._saved}"
                            + (f" (FAILED: {'; '.join(failed)})"
                               if failed else ""))
            seconds = round(self._clock() - (self._since or self._clock()))
            self._hold = None
            self._since = None
            self._saved = None
            self._screen_at = None
            self._by = ""
            self._clear_state()
            self._log(f"OFF by {by} | after {seconds} s{restored}")
            log.info("night mode OFF (%s) after %d s", by, seconds)
            # The state the owner walked in on — before the stop that
            # cures it. On a thread: off() runs on the keyboard hook.
            self._vitals_stop.set()
            if self.vitals_minutes > 0:
                threading.Thread(target=self._vitals_to_log, args=("at OFF",),
                                 daemon=True, name="night-vitals").start()
            return self.state()

    def toggle(self, *, by: str = "key") -> dict:
        with self._lock:
            return self.off(by=by) if self.active else self.on(by=by)

    def release(self) -> None:
        """atexit / finally: off(), and never an exception."""
        try:
            if self.active:
                self.off(by="exit")
        except Exception:             # noqa: BLE001
            pass

    # -- the screen --

    def screen_off(self) -> None:
        """Put the screen out now, and again a few seconds later — the
        mouse movement that follows a click lights it straight back up.
        Returns at once; the broadcast runs on its own thread."""
        self._screen_at = self._clock()
        threading.Thread(target=self._screen_off_worker, daemon=True,
                         name="night-screen").start()

    def _screen_off_worker(self) -> None:
        try:
            ok = self._sender(MONITOR_OFF)
            if not ok:
                log.info("night mode: a window sat on the screen-off "
                         "broadcast past %d ms", SEND_TIMEOUT_MS)
            if self.again_s > 0:
                time.sleep(self.again_s)
                if self.active:
                    self._sender(MONITOR_OFF)
        except Exception as e:        # noqa: BLE001
            log.info("night mode: screen-off broadcast failed (%s)", e)

    # -- the record --

    def _write_state(self) -> None:
        data = {"since": self._since, "since_text": _stamp(),
                "pid": os.getpid(), "by": self._by, "saved": self._saved}
        try:
            self.state_path.write_text(json.dumps(data, indent=1), "utf-8")
        except OSError as e:
            log.warning("night mode: could not write %s (%s)",
                        self.state_path.name, e)

    def _clear_state(self) -> None:
        try:
            self.state_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("night mode: could not remove %s (%s)",
                        self.state_path.name, e)

    def _log(self, line: str) -> None:
        try:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{_stamp()} | {line}\n")
        except OSError:
            pass

    def _probe_to_log(self) -> None:
        """The spec's `powercfg /requests` in the log at every entry —
        and the rest of the probe with it, because the requests list is
        the one line that needs admin and the others do not."""
        try:
            result = probe(self._run)
        except Exception as e:        # noqa: BLE001
            self._log(f"probe failed: {e}")
            return
        self._last_probe = result
        for label, sentence, tone in verdict(self.state(), result):
            self._log(f"  {tone:4} | {label}: {sentence}")

    def _vitals_to_log(self, tag: str = "") -> None:
        try:
            line = self._vitals()
        except Exception as e:        # noqa: BLE001
            line = f"vitals failed: {e}"
        self._log(f"  vitals | {tag + ': ' if tag else ''}{line}")

    def _vitals_worker(self, stop: threading.Event) -> None:
        """A vitals line now and every [night] vitals_minutes until off()
        sets `stop` — the record of the night, read the morning after."""
        self._vitals_to_log("at ON")
        while not stop.wait(self.vitals_minutes * 60):
            self._vitals_to_log()


def recover(app_dir: Path, run=None) -> str | None:
    """At start-up: a night_state.json left by a session that died with
    night mode on. The hold died with it; the pinned timers did not.
    Puts them back, removes the file, and returns one sentence for the
    log — or None when there was nothing to do."""
    path = Path(app_dir) / STATE_NAME
    if not path.exists():
        return None
    run = run or _run_powercfg
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    saved = data.get("saved") if isinstance(data, dict) else None
    message = (f"night mode was still on when the last session ended "
               f"(since {data.get('since_text', '?')})")
    if saved:
        failed = write_timeouts(saved, run)
        message += (f" — sleep timers restored to {saved}"
                    if not failed else
                    f" — sleep timers NOT restored: {'; '.join(failed)}")
    else:
        message += " — nothing to restore, the hold died with it"
    try:
        path.unlink()
    except OSError:
        pass
    try:
        with (Path(app_dir) / LOG_NAME).open("a", encoding="utf-8") as fh:
            fh.write(f"{_stamp()} | RECOVERED | {message}\n")
    except OSError:
        pass
    return message
