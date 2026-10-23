"""Room for a game: the models step aside while another program needs
the graphics card, and come back when it is done (the owner, 2026-10-17).

He started a game with the app running and the PC ran out of memory.
Read off this machine's own logs that evening: at 18:29:15 Windows'
Resource-Exhaustion-Detector wrote "low virtual memory" and named
llama-server.exe (Ollama's gemma3:12b) at 13.6 GB of commit, this app at
6.3 GB and explorer.exe at 6.3 GB; app.log had been saying "commit 97% of
the limit" since 17:57 and 98% at 18:27; the game and the Game Bar
widgets died within the minute. Nothing rebooted: the machine ran out of
COMMIT (RAM plus page file), and on Windows what a program puts on the
graphics card is committed system memory too, so the card's contents and
the game's spill-over count against one limit. When gemma's keep-alive
ran out at 19:42 the commit fell 60.6 -> 48.8 GB and the card 15.7 -> 5.7
GB of its 16.

What each piece holds — measured the same evening in a process of its
own, the night8 Hebrew model, beam 5, three of his recordings:

    gemma3:12b in Ollama            9.2 GB of the card, ~12 GB of commit
    the Hebrew model on the card    2.2 GB of the card,  2.1 GB of commit
                                    (load 7.3 s; decode 0.30 / 0.47 / 0.53 s
                                    for 3.3 / 7.4 / 23.2 s of speech; the
                                    CUDA runtime keeps ~1.1 GB after it goes)
    the English detector            the rest of this app's 4.15 GB on the card
    the Hebrew model on the CPU     0.8 GB of commit, load 8.2 s, decode
    (int8, 12 cores)                8.95 / 9.93 / 9.64 s

So the processor is NOT a rung. Twenty to thirty times slower, with every
core busy for those ten seconds, it would stutter the very game it is
making room for and still be useless to dictate with.

THE LADDER. A rung is taken only while the one above it has not made
enough room, and every rung comes back at once when the game is gone:

    1  LOCAL    Ollama's models are unloaded and held off: net.py refuses
                every request to the local model's URL while the hold
                stands (`net.hold`), so nothing in this app can load it
                again, and every feature that asks it already falls to
                its next backend on a refusal. Dictation is untouched.
    2  ENGLISH  the English detector leaves the card. Dictation goes on in
                Hebrew; only a dictation that is English from end to end
                loses its own model.
    3  SPEECH   the Hebrew model goes too — the model is off exactly as
                the desk's Stop leaves it, and every key that needs no
                model keeps working. ONLY with `[room] keep_speech =
                false`: since 2026-10-23 the ladder stops at ENGLISH by
                default (the owner: dictation stays possible while he
                plays; the Hebrew model at int8_float16 is ~1.2 GB of the
                card with CUDA's own context).

WHEN. A competitor is a program — not this app, not Ollama, not dwm, not
another Python — holding at least `competitor_gb` of graphics memory, or
the program whose window fills its screen in the foreground holding at
least NOTE (Ladder.pick; Fortnite on 2026-10-23 held 1.96 GB in all and
never reached 2.5),
the card's own plus what spilled into system memory: Windows' "GPU
Process Memory" counters, the per-process numbers Task Manager's Details
tab shows, read through PDH in a fifth of a millisecond, unelevated, and
for games behind an anti-cheat too (no process is opened). dwm's own
reading is not memory it holds (29.9 GB on this 16 GB card, measured),
NVIDIA's overlay sits at 1.9 GB on an idle desktop, every other program
on it under 0.2 GB of either kind. Rung 1 is taken the second time a
competitor is seen in a row. Rungs 2 and 3 only while it is there AND the
machine is still short — commit at `commit_tight` of the limit, or at
least `spill_gb` of the competitor's memory pushed out to system memory
(the card was too full for it: the very spill that ran this machine out
of commit) — and only `settle_s` after the last rung, so a step's effect
can show before the next one is taken. A program that keeps within its
card budget lowers its own quality instead of spilling, and then the
ladder stays on rung 1 with dictation whole. Back: every rung, once no
competitor has been seen for `exit_s`.

Ladder is the decision and nothing else — readings in, a rung out, no
clock, no Windows — so the tests drive it with numbers. The readings are
`reading()`; what each rung DOES is main.App's (`_room_*`).
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import threading
from ctypes import wintypes
from dataclasses import dataclass

log = logging.getLogger("app")

LOCAL, ENGLISH, SPEECH = 1, 2, 3
TOP = SPEECH

#: tests.py turns this off at import: an App a test starts reads the real
#: machine, and must never be the thing that unloads the owner's Ollama.
LIVE = True

#: What each rung is called in the log and in status()["room"].
NAMES = {0: "", LOCAL: "local model", ENGLISH: "English model",
         SPEECH: "speech model"}

#: Programs that are never a competitor, lower case, without ".exe".
#: dwm's counter is not memory it holds (above); Ollama's runner is the
#: thing rung 1 removes; NVIDIA's overlay is part of the driver; a Python
#: is another copy of this app (the Stranger, the Store copy) or a
#: training script — two copies that each made room for the other would
#: both end with no model at all.
NEVER = frozenset({
    "dwm", "llama-server", "ollama", "ollama app", "ollama_llama_server",
    "nvidia overlay", "nvcontainer", "python", "pythonw", "deskit",
    "deskitquiet", "csrss", "system",
})

#: A competitor has to be seen this many polls in a row: a program that
#: flashes a big texture once is not a game sitting down for an hour.
CONFIRM = 2

#: How often a hold that stands re-checks Ollama for a model somebody
#: else loaded (another program on this PC may use it too): seconds.
RECHECK_S = 30.0

GB = 1 << 30

#: A full-screen foreground program this heavy is a game (Ladder.pick);
#: one this heavy that is neither full screen nor at competitor_gb is
#: named in the log once (main.App._room_tick). Without it a game that never reached
#: the bar left no trace: on 2026-10-23 GTA V ran 3 min 20 s (BattlEye
#: loaded 14:39:32, unloaded 14:42:52) under commit at 90% and the log
#: could not say whether the watch was alive or the game was still under
#: 2.5 GB; the same game's next run reached 2.9 GB 2 min 49 s after its
#: BattlEye loaded and the ladder stepped at once. Discord, Chrome and
#: explorer sit at 0.4-0.5 GB on this PC.
NOTE = 1 * GB


@dataclass(frozen=True)
class Competitor:
    name: str
    pid: int
    dedicated: int          # bytes on the card itself
    shared: int             # bytes it put in system memory instead

    @property
    def total(self) -> int:
        return self.dedicated + self.shared


@dataclass(frozen=True)
class Reading:
    """One look at the machine. `competitor` is the heaviest program that
    may count, or None; `commit` the fraction of the commit limit in use,
    or None when Windows would not say; `game` the program whose window
    fills its screen in the foreground, with its graphics memory, or None
    (not one of NEVER, never this app)."""
    competitor: Competitor | None
    commit: float | None
    game: Competitor | None = None


class Ladder:
    """Where the app should stand, from one reading after another.

    `rung` is where it DOES stand — the App moves it with `moved()` after
    a step has actually been taken, and a step it could not take yet (a
    dictation in progress) simply comes up again on the next reading.
    `ceiling` is how far down this episode may go: a Start pressed while
    the speech model stood aside is the person saying they want it, and
    it is not taken from them again until the game is over. `top` is how
    far down ANY episode may go: ENGLISH unless the person said otherwise
    ([room] keep_speech, the owner on 2026-10-23: dictation stays possible
    while a game runs).

    Two ways to be a game (`pick`): any program at `competitor_gb` or
    more, as before; or the program filling the screen in the foreground
    at `game_gb` or more. The second is what 2026-10-23 measured: Fortnite
    at 1.83 GB of the card + 0.13 GB shared, under 2.5, with commit at 93%
    of the limit and the ladder at rung 0 by its own rule. A full-screen
    window is what keeps the second way out of an ordinary day: no other
    program on this PC holds even 0.5 GB of the card."""

    def __init__(self, competitor_gb: float = 2.5, commit_tight: float = 0.90,
                 spill_gb: float = 1.0, settle_s: float = 15.0,
                 exit_s: float = 60.0, top: int = TOP, game_gb: float = 1.0):
        self.competitor_bytes = int(competitor_gb * GB)
        self.game_bytes = int(game_gb * GB)
        self.commit_tight = float(commit_tight)
        self.spill_bytes = int(spill_gb * GB)
        self.settle_s = float(settle_s)
        self.exit_s = float(exit_s)
        self.top = int(top)
        self.rung = 0
        self.since = 0.0
        self.ceiling = self.top
        self.seen = 0
        self.gone_since: float | None = None
        self.holder = ""

    def counts(self, c: Competitor | None) -> bool:
        return c is not None and c.total >= self.competitor_bytes

    def pick(self, r: Reading) -> Competitor | None:
        """The program this reading makes room for, or None (above)."""
        if self.counts(r.competitor):
            return r.competitor
        g = r.game
        if g is not None and g.total >= self.game_bytes:
            return g
        return None

    def short(self, r: Reading) -> bool:
        """Is the machine still short of room with the competitor there?"""
        if r.commit is not None and r.commit >= self.commit_tight:
            return True
        c = self.pick(r) or r.competitor
        return c is not None and c.shared >= self.spill_bytes

    def want(self, r: Reading, now: float) -> int:
        """The rung to stand on after this reading. At most one rung down
        per reading; all the way up at once."""
        who = self.pick(r)
        if who is not None:
            self.seen += 1
            self.gone_since = None
            self.holder = who.name
        else:
            self.seen = 0
            if self.gone_since is None:
                self.gone_since = now
        if self.rung == 0:
            return LOCAL if self.seen >= CONFIRM else 0
        if who is None:
            return 0 if now - self.gone_since >= self.exit_s else self.rung
        if (self.rung < min(self.top, self.ceiling) and self.short(r)
                and now - self.since >= self.settle_s):
            return self.rung + 1
        return self.rung

    def moved(self, rung: int, now: float) -> None:
        self.rung = rung
        self.since = now
        if rung == 0:
            self.ceiling = self.top
            self.holder = ""

    def keep_speech(self, now: float) -> None:
        """The person loaded the model while it stood aside: it stays for
        the rest of this episode (the English model may still go)."""
        if self.rung >= SPEECH:
            self.ceiling = ENGLISH
            self.moved(LOCAL, now)


# ---------------------------------------------------------------- readings
#
# Private DLL handles, never ctypes.windll.* (AGENTS.md: argtypes set on
# the shared object change them for every module in the process).

PDH_FMT_LARGE = 0x00000400
PDH_MORE_DATA = 0x800007D2
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE = ctypes.c_void_p(-1).value

_DEDICATED = r"\GPU Process Memory(*)\Dedicated Usage"
_SHARED = r"\GPU Process Memory(*)\Shared Usage"


class _PdhValue(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("pad", wintypes.DWORD),
                ("largeValue", ctypes.c_longlong)]


class _PdhItem(ctypes.Structure):
    _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _PdhValue)]


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64)]


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _Rect),
                ("rcWork", _Rect), ("dwFlags", wintypes.DWORD)]


MONITOR_DEFAULTTONULL = 0
#: The shell's own windows cover a screen too (the desktop behind every
#: window, the taskbar): never a game.
SHELL_CLASSES = frozenset({"progman", "workerw", "shell_traywnd",
                           "shell_secondarytraywnd"})

_dll_lock = threading.Lock()
_pdh = None
_k32 = None
_u32 = None


def _dlls():
    global _pdh, _k32
    with _dll_lock:
        if _pdh is None:
            p = ctypes.WinDLL("pdh")
            p.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_size_t,
                                        ctypes.POINTER(ctypes.c_void_p)]
            p.PdhAddEnglishCounterW.argtypes = [
                ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_void_p)]
            p.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
            p.PdhGetFormattedCounterArrayW.argtypes = [
                ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
            p.PdhCloseQuery.argtypes = [ctypes.c_void_p]
            for name in ("PdhOpenQueryW", "PdhAddEnglishCounterW",
                         "PdhCollectQueryData", "PdhGetFormattedCounterArrayW",
                         "PdhCloseQuery"):
                getattr(p, name).restype = ctypes.c_uint32
            k = ctypes.WinDLL("kernel32")
            k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
            k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
            k.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            k.Process32FirstW.restype = wintypes.BOOL
            k.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            k.Process32NextW.restype = wintypes.BOOL
            k.CloseHandle.argtypes = [ctypes.c_void_p]
            k.CloseHandle.restype = wintypes.BOOL
            k.GlobalMemoryStatusEx.argtypes = [ctypes.c_void_p]
            k.GlobalMemoryStatusEx.restype = wintypes.BOOL
            _pdh, _k32 = p, k
    return _pdh, _k32


def _user32():
    global _u32
    with _dll_lock:
        if _u32 is None:
            u = ctypes.WinDLL("user32")
            u.GetForegroundWindow.argtypes = []
            u.GetForegroundWindow.restype = ctypes.c_void_p
            u.GetWindowThreadProcessId.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
            u.GetWindowThreadProcessId.restype = wintypes.DWORD
            u.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Rect)]
            u.GetWindowRect.restype = wintypes.BOOL
            u.MonitorFromWindow.argtypes = [ctypes.c_void_p, wintypes.DWORD]
            u.MonitorFromWindow.restype = ctypes.c_void_p
            u.GetMonitorInfoW.argtypes = [ctypes.c_void_p,
                                          ctypes.POINTER(_MonitorInfo)]
            u.GetMonitorInfoW.restype = wintypes.BOOL
            u.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                        ctypes.c_int]
            u.GetClassNameW.restype = ctypes.c_int
            u.IsZoomed.argtypes = [ctypes.c_void_p]
            u.IsZoomed.restype = wintypes.BOOL
            _u32 = u
    return _u32


def covers(window: tuple[int, int, int, int],
           monitor: tuple[int, int, int, int]) -> bool:
    """Does a window rectangle (left, top, right, bottom) cover the whole
    of its monitor — exclusive full screen or a borderless window?"""
    return (window[0] <= monitor[0] and window[1] <= monitor[1]
            and window[2] >= monitor[2] and window[3] >= monitor[3])


def full_screen_pid() -> int | None:
    """The process whose foreground window fills its monitor, or None.
    Reads window rectangles and a pid; opens no process, so a game behind
    an anti-cheat answers like any other."""
    u = _user32()
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return None
    name = ctypes.create_unicode_buffer(64)
    u.GetClassNameW(hwnd, name, 64)
    if name.value.lower() in SHELL_CLASSES:
        return None
    if u.IsZoomed(hwnd):
        # a maximised window is an ordinary program; with the taskbar
        # hidden (or on another screen) its rectangle covers the monitor
        # too. A game's full screen or borderless window is not maximised.
        return None
    rect = _Rect()
    if not u.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    monitor = u.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONULL)
    if not monitor:
        return None
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    if not u.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    m = info.rcMonitor
    if not covers((rect.left, rect.top, rect.right, rect.bottom),
                  (m.left, m.top, m.right, m.bottom)):
        return None
    pid = wintypes.DWORD(0)
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value) or None


def _per_pid(path: str) -> dict[int, int]:
    """One PDH counter across all its instances, summed per process.
    The instance names are `pid_<n>_luid_..._phys_<i>`. A query is opened
    and closed every time, so a game started after the app is seen: the
    first read in a process costs ~0.4 s (PDH loading the counter set),
    every later one 0.1-0.2 ms (measured 2026-10-17)."""
    pdh, _k = _dlls()
    query = ctypes.c_void_p()
    if pdh.PdhOpenQueryW(None, 0, ctypes.byref(query)):
        return {}
    out: dict[int, int] = {}
    try:
        counter = ctypes.c_void_p()
        if pdh.PdhAddEnglishCounterW(query, path, 0, ctypes.byref(counter)):
            return {}
        if pdh.PdhCollectQueryData(query):
            return {}
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        status = pdh.PdhGetFormattedCounterArrayW(
            counter, PDH_FMT_LARGE, ctypes.byref(size), ctypes.byref(count), None)
        if status != PDH_MORE_DATA or not size.value:
            return {}
        buf = ctypes.create_string_buffer(size.value)
        if pdh.PdhGetFormattedCounterArrayW(counter, PDH_FMT_LARGE,
                                            ctypes.byref(size),
                                            ctypes.byref(count), buf):
            return {}
        items = ctypes.cast(buf, ctypes.POINTER(_PdhItem))
        for i in range(count.value):
            name = items[i].szName or ""
            if not name.startswith("pid_"):
                continue
            try:
                pid = int(name.split("_")[1])
            except (IndexError, ValueError):
                continue
            out[pid] = out.get(pid, 0) + max(0, int(items[i].FmtValue.largeValue))
    finally:
        pdh.PdhCloseQuery(query)
    return out


def _images() -> dict[int, str]:
    """pid -> image name, lower case, without ".exe". A snapshot opens no
    process, so a protected game is named like any other."""
    _p, k = _dlls()
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE:
        return {}
    out: dict[int, str] = {}
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.lower()
            if name.endswith(".exe"):
                name = name[:-4]
            out[int(entry.th32ProcessID)] = name
            ok = k.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k.CloseHandle(snap)
    return out


def commit() -> float | None:
    """The fraction of the commit limit in use: what ran out at 18:29."""
    _p, k = _dlls()
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not k.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    limit = int(status.ullTotalPageFile)
    if limit <= 0:
        return None
    return (limit - int(status.ullAvailPageFile)) / limit


def heaviest(dedicated: dict[int, int], shared: dict[int, int],
             images: dict[int, str], me: int) -> Competitor | None:
    """The program holding the most graphics memory that may count as a
    competitor at all — never this process, never one of NEVER."""
    best = None
    for pid in set(dedicated) | set(shared):
        name = images.get(pid, "")
        if pid == me or not name or name in NEVER:
            continue
        c = Competitor(name, pid, dedicated.get(pid, 0), shared.get(pid, 0))
        if best is None or c.total > best.total:
            best = c
    return best


def full_screen(dedicated: dict[int, int], shared: dict[int, int],
                images: dict[int, str], me: int,
                pid: int | None) -> Competitor | None:
    """The full-screen foreground program with its graphics memory, when
    it may count at all — never this process, never one of NEVER."""
    if not pid or pid == me:
        return None
    name = images.get(pid, "")
    if not name or name in NEVER:
        return None
    return Competitor(name, pid, dedicated.get(pid, 0), shared.get(pid, 0))


def reading() -> Reading:
    """One look at the machine. Never raises: a reading Windows refuses
    is a machine with nothing on the card, which moves nothing."""
    game = None
    try:
        dedicated = _per_pid(_DEDICATED)
        shared = _per_pid(_SHARED)
        images = _images()
        who = heaviest(dedicated, shared, images, os.getpid())
        try:
            game = full_screen(dedicated, shared, images, os.getpid(),
                               full_screen_pid())
        except Exception:                                # noqa: BLE001
            log.debug("room: the foreground window did not answer",
                      exc_info=True)
    except Exception:                                    # noqa: BLE001
        log.debug("room: the graphics memory counters did not answer",
                  exc_info=True)
        who = None
    try:
        used = commit()
    except Exception:                                    # noqa: BLE001
        used = None
    return Reading(who, used, game)


# ------------------------------------------------------------------ Ollama

def ollama_loaded(url: str) -> list[str]:
    """The models Ollama holds right now (GET /api/ps)."""
    import net
    status, _h, body = net.request("GET", f"{url.rstrip('/')}/api/ps", "room",
                                   timeout_s=3)
    if status != 200:
        return []
    try:
        models = json.loads(body.decode("utf-8")).get("models") or []
    except (ValueError, AttributeError):
        return []
    return [str(m.get("name") or m.get("model")) for m in models
            if m.get("name") or m.get("model")]


def ollama_unload(url: str) -> list[str]:
    """Unload every model Ollama holds (keep_alive 0 with no prompt is
    Ollama's own unload). Returns the names it asked to go. Never raises:
    an Ollama that is not running holds nothing."""
    import net
    gone: list[str] = []
    try:
        names = ollama_loaded(url)
    except Exception:                                    # noqa: BLE001
        return gone
    for name in names:
        try:
            status, _h, _b = net.post_json(f"{url.rstrip('/')}/api/generate",
                                           "room",
                                           {"model": name, "keep_alive": 0},
                                           timeout_s=15)
            if status == 200:
                gone.append(name)
        except Exception:                                # noqa: BLE001
            log.debug("room: %s did not unload", name, exc_info=True)
    return gone
