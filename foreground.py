"""Back to the app after the browser: its window in front, and a card.

THE MOMENT THIS IS FOR. "Sign in with Google" hands the person to the
system browser (sb.sign_in_google): Google's page, Supabase's redirect,
and then the app's own loopback page saying the sign-in is done. At
that moment the BROWSER has the foreground and the app — the first-run
wizard, or the dashboard — is somewhere behind it, and the person has
to go and find it. The owner's report of 2026-09-19: a bare page, and
he had to look for the window himself.

Two answers, both best-effort, neither allowed to fail a sign-in that
has already succeeded:

  bring_back()      the app's top-level window in front of the browser
  signed_in_card()  the app's own notification card — "Signed in as
                    <e-mail> / Back to DeskIT" — which a click brings the
                    window forward from, for when Windows refused the
                    first answer or the person had already looked away

WHICH WINDOW. Everything of the app's that has a title bar is a Tk
toplevel (window class ``TkTopLevel``): the wizard (firstrun.py, titled
"DeskIT"), the dashboard (dashboard.py, "DeskIT" plus the dev tag). The
things that must NOT come forward are also windows: the status dot and
every card are ``TkTopLevel`` too but override-redirect and titled "tk",
the glass cards are ``DeskITSkinGlass`` tool windows with no title at
all — and the BROWSER TAB is titled "DeskIT" as well, because that is
what the loopback page calls itself. So the finder wants all three:
visible, class ``TkTopLevel``, not a tool window, and a title carrying
``title_part``. Among several, the calling process's own window comes
first (the wizard runs inside the app's process — the sign-in was
started from it), then a window of the same install (the dashboard is
a second process of the same python), then any other.

WHY THREE TRIES. SetForegroundWindow is allowed to decline: Windows
grants it to the process that owns the foreground, was started by it,
or is answering input — and a thread waiting on a loopback socket is
none of those while the browser is in front. So: ask; then attach this
thread's input queue to the foreground window's thread (which makes
this process the one "answering input" for a moment) and ask again;
then minimise and restore the window, which the shell activates as a
window the person just un-minimised. Each try is WATCHED — the
foreground reads as 0 for a few frames during the handover, so a
single immediate read is not an answer (notify.raise_window measured
this). When all three fail, FlashWindowEx lights the taskbar button and
the answer is an honest False: the card is the other half.

Stdlib and ctypes only, private ``ctypes.WinDLL`` handles (never
``ctypes.windll``, whose function objects are process-global — see
AGENTS.md and capture.py's OverflowError), nothing imported from Tk,
and the card goes through the door every card already comes through:
``POST /notify`` on the app's own server (server.py, notify_hook.post),
which is nothing at all when the app is not running — the wizard signs
in before the server is up, and there the window itself is the answer.

sb.py calls both after the code is exchanged; the wizard's Account
page calls them again after its own sign-in (``import foreground`` in a
try/except: a copy without this file loses the courtesy, not the
sign-in). Names and signatures are the contract:

    bring_back(title_part: str = "DeskIT") -> bool
    signed_in_card(email: str) -> None
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from pathlib import Path

log = logging.getLogger("app")

#: The window class of every titled window the app owns (Tk's).
TK_CLASS = "TkTopLevel"
#: How long a foreground handover may take before a try is called failed.
SETTLE_S = 0.5
POLL_S = 0.02
#: What the card says. The e-mail is the title's; the body is the way back.
CARD_BODY = "Back to DeskIT"
CARD_SOURCE = "dashboard"      # the label notify.py already knows — the
                               # click lands on the dashboard's window
EMAIL_MAX = 60

SW_MINIMIZE = 6
SW_RESTORE = 9
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
FLASHW_ALL = 0x00000003
FLASHW_TIMERNOFG = 0x0000000C
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_HANDLES = None


class _FLASHWINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_void_p),
                ("dwFlags", ctypes.c_ulong), ("uCount", ctypes.c_uint),
                ("dwTimeout", ctypes.c_ulong)]


_ENUM_PROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


def _handles():
    """PRIVATE user32/kernel32 wrappers, built once. A HWND is c_void_p:
    a 64-bit handle does not fit the c_int ctypes assumes."""
    global _HANDLES
    if _HANDLES is None:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        for name in ("IsWindow", "IsWindowVisible", "IsIconic",
                     "SetForegroundWindow", "BringWindowToTop"):
            fn = getattr(u32, name)
            fn.argtypes = [ctypes.c_void_p]
            fn.restype = ctypes.c_int
        u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u32.ShowWindow.restype = ctypes.c_int
        u32.GetForegroundWindow.argtypes = []
        u32.GetForegroundWindow.restype = ctypes.c_void_p
        u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,
                                                 ctypes.POINTER(ctypes.c_ulong)]
        u32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        u32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong,
                                          ctypes.c_int]
        u32.AttachThreadInput.restype = ctypes.c_int
        u32.EnumWindows.argtypes = [_ENUM_PROC, ctypes.c_void_p]
        u32.EnumWindows.restype = ctypes.c_int
        u32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        u32.GetWindowTextLengthW.restype = ctypes.c_int
        u32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                       ctypes.c_int]
        u32.GetWindowTextW.restype = ctypes.c_int
        u32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                      ctypes.c_int]
        u32.GetClassNameW.restype = ctypes.c_int
        u32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u32.GetWindowLongW.restype = ctypes.c_long
        u32.FlashWindowEx.argtypes = [ctypes.POINTER(_FLASHWINFO)]
        u32.FlashWindowEx.restype = ctypes.c_int
        k32.GetCurrentThreadId.argtypes = []
        k32.GetCurrentThreadId.restype = ctypes.c_ulong
        k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.QueryFullProcessImageNameW.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ulong)]
        k32.QueryFullProcessImageNameW.restype = ctypes.c_int
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.restype = ctypes.c_int
        _HANDLES = (u32, k32)
    return _HANDLES


# ------------------------------------------------------------ the window

def _text(u32, hwnd: int) -> str:
    n = int(u32.GetWindowTextLengthW(hwnd))
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class(u32, hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(64)
    u32.GetClassNameW(hwnd, buf, 64)
    return buf.value


def _exe_of(k32, pid: int) -> str:
    """The executable's path of a process, or "" when it cannot be asked."""
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not handle:
        return ""
    try:
        size = ctypes.c_ulong(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        k32.CloseHandle(handle)


def _rank(k32, pid: int, mine: int, my_dir: str) -> int:
    """0 this process, 1 the same install's python, 2 anyone else."""
    if pid == mine:
        return 0
    if my_dir:
        try:
            exe = _exe_of(k32, pid)
            if exe and os.path.normcase(str(Path(exe).resolve().parent)) == my_dir:
                return 1
        except Exception:                                    # noqa: BLE001
            pass
    return 2


def candidates(title_part: str = "DeskIT") -> list[tuple[int, str]]:
    """Every visible ``TkTopLevel`` window that is not a tool window and
    whose title carries ``title_part`` (case-insensitive), as (hwnd,
    title), best first: this process's own, then the same install's,
    then the rest. Empty for an empty ``title_part`` — a blank would
    match every Tk window on the desktop — and on any error."""
    want = str(title_part or "").strip().lower()
    if not want:
        return []
    try:
        u32, k32 = _handles()
    except Exception:                                        # noqa: BLE001
        return []
    mine = os.getpid()
    try:
        my_dir = os.path.normcase(str(Path(sys.executable).resolve().parent))
    except Exception:                                        # noqa: BLE001
        my_dir = ""
    found: list[tuple[int, int, str]] = []

    @_ENUM_PROC
    def collect(hwnd, _param):
        try:
            if not u32.IsWindowVisible(hwnd):
                return 1
            if _class(u32, hwnd) != TK_CLASS:
                return 1
            if int(u32.GetWindowLongW(hwnd, GWL_EXSTYLE)) & WS_EX_TOOLWINDOW:
                return 1
            title = _text(u32, hwnd).strip()
            if want not in title.lower():
                return 1
            pid = ctypes.c_ulong()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found.append((_rank(k32, int(pid.value), mine, my_dir), int(hwnd), title))
        except Exception:                                    # noqa: BLE001
            pass
        return 1

    try:
        u32.EnumWindows(collect, None)
    except Exception:                                        # noqa: BLE001
        return []
    found.sort(key=lambda item: item[0])
    return [(hwnd, title) for _rank_, hwnd, title in found]


def find_window(title_part: str = "DeskIT") -> int:
    """The app's top-level window — the wizard's or the dashboard's — or
    0 when there is none on this desktop."""
    try:
        hits = candidates(title_part)
    except Exception:                                        # noqa: BLE001
        return 0
    return hits[0][0] if hits else 0


# ---------------------------------------------------------- the foreground

def _is_front(u32, hwnd: int, seconds: float) -> bool:
    """Is ``hwnd`` the foreground window, allowing ``seconds`` for it to
    become so? The handover reads 0 while in flight, so poll."""
    end = time.monotonic() + max(0.0, float(seconds))
    while True:
        if int(u32.GetForegroundWindow() or 0) == hwnd:
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(POLL_S)


def _flash(u32, hwnd: int) -> None:
    """The taskbar button lit until the window comes to the front — the
    consolation when Windows kept the foreground where it was."""
    info = _FLASHWINFO()
    info.cbSize = ctypes.sizeof(_FLASHWINFO)
    info.hwnd = hwnd
    info.dwFlags = FLASHW_ALL | FLASHW_TIMERNOFG
    info.uCount = 0
    info.dwTimeout = 0
    u32.FlashWindowEx(ctypes.byref(info))


def raise_window(hwnd: int) -> bool:
    """Bring one window to the front; True only if it got there. Never
    raises. The three tries the module docstring describes, then the
    flash."""
    try:
        hwnd = int(hwnd or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    if hwnd <= 0:
        return False
    try:
        u32, k32 = _handles()
        if not u32.IsWindow(hwnd):
            return False
        # 1. ask
        if u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, SW_RESTORE)
        u32.SetForegroundWindow(hwnd)
        if _is_front(u32, hwnd, SETTLE_S):
            return True
        # 2. be the one answering input for a moment, and ask again
        front = int(u32.GetForegroundWindow() or 0)
        mine = int(k32.GetCurrentThreadId())
        theirs = int(u32.GetWindowThreadProcessId(front, None)) if front else 0
        if theirs and theirs != mine and u32.AttachThreadInput(mine, theirs, 1):
            try:
                u32.BringWindowToTop(hwnd)
                u32.SetForegroundWindow(hwnd)
            finally:
                u32.AttachThreadInput(mine, theirs, 0)
            if _is_front(u32, hwnd, SETTLE_S):
                return True
        # 3. a window the person just un-minimised is one the shell activates
        u32.ShowWindow(hwnd, SW_MINIMIZE)
        u32.ShowWindow(hwnd, SW_RESTORE)
        u32.SetForegroundWindow(hwnd)
        if _is_front(u32, hwnd, SETTLE_S):
            return True
        # 4. the taskbar button, lit
        _flash(u32, hwnd)
        log.info("foreground: Windows kept the foreground — window %d flashed", hwnd)
        return False
    except Exception:                                        # noqa: BLE001
        log.debug("foreground: could not raise window %s", hwnd, exc_info=True)
        return False


def bring_back(title_part: str = "DeskIT") -> bool:
    """The app's window (the wizard or the dashboard) in front of whatever
    has the foreground — the browser, after a sign-in. True only when it
    is the foreground window afterwards; False with no such window on
    this desktop, when Windows declined every try (the taskbar button
    flashes instead), and on any error. Never raises."""
    try:
        hwnd = find_window(title_part)
        if not hwnd:
            log.info("foreground: no %r window to bring back", title_part)
            return False
        return raise_window(hwnd)
    except Exception:                                        # noqa: BLE001
        log.debug("foreground: bring_back failed", exc_info=True)
        return False


# --------------------------------------------------------------- the card

def card_payload(email: str, hwnd: int = 0) -> dict:
    """What the notify door is handed: the fields notify.clean() admits.
    The e-mail is drawn, never parsed (clean() strips controls and cuts
    the title at 80); ``hwnd`` is the window a click raises."""
    who = " ".join(str(email or "").split())
    if len(who) > EMAIL_MAX:
        who = who[:EMAIL_MAX - 1] + "…"
    return {"source": CARD_SOURCE, "kind": "done",
            "title": f"Signed in as {who}" if who else "Signed in",
            "body": CARD_BODY, "app": "DeskIT", "hwnd": int(hwnd or 0)}


def signed_in_card(email: str) -> None:
    """The app's own card, through the app's own door: ``POST /notify``
    on the running app (notify_hook.post, the same call Claude Code's
    Stop hook makes), carrying the app window's handle so a click on the
    card raises it (notify.Engine.open -> raise_window). A no-op — not an
    error — whenever the app is not there to answer: no phone token in
    the store (the wizard signs in before the server exists; a fresh
    install has no token yet), no server on the port, a refusal. Never
    raises."""
    try:
        import notify_hook
        token = notify_hook.read_token()
        if not token:
            log.info("foreground: no app to card the sign-in on")
            return
        payload = card_payload(email, find_window())
        sent = notify_hook.post(payload, notify_hook.server_url(), token,
                                timeout=2.0)
        log.info("foreground: signed-in card %s", "posted" if sent else "not taken")
    except Exception:                                        # noqa: BLE001
        log.debug("foreground: signed_in_card failed", exc_info=True)
