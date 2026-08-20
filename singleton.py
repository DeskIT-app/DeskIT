"""Single-instance guard + a clean way to stop a windowless instance.

Running without a console (pythonw.exe, launched from a shortcut) means
there is no Ctrl+C and no window to close. Two Win32 kernel objects solve
both problems:

- a named MUTEX makes a second launch detect the first and bail out, which
  matters because two live instances would both paste on every dictation;
- a named EVENT lets `main.py --stop` ask the running instance to quit.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
SYNCHRONIZE = 0x00100000
EVENT_MODIFY_STATE = 0x0002
INFINITE = 0xFFFFFFFF

# "Local\" = per-login-session, which is what we want: the app is per-user.
MUTEX_NAME = r"Local\HebrewDictation.instance"
QUIT_EVENT_NAME = r"Local\HebrewDictation.quit"
# The dashboard gets its own pair. It is a .vbs behind a shortcut, so
# double-clicking it twice used to open two identical windows polling the
# same app — nothing breaks, it just looks broken.
DASHBOARD_MUTEX = r"Local\HebrewDictation.dashboard"
DASHBOARD_SHOW = r"Local\HebrewDictation.dashboard.show"

kernel32.CreateMutexW.restype = w.HANDLE
kernel32.CreateEventW.restype = w.HANDLE
kernel32.OpenEventW.restype = w.HANDLE
kernel32.OpenMutexW.restype = w.HANDLE
kernel32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]


def is_running(name: str = MUTEX_NAME) -> bool:
    """Is an instance up? Asked by the dashboard, several times a minute.

    The MUTEX and not the quit event, because the mutex is taken as the
    first thing a launch does. (Both now exist from the same moment — see
    QuitSignal — but the mutex is still the thing that DEFINES "an instance
    exists", and the event is how you talk to it.)
    """
    handle = kernel32.OpenMutexW(SYNCHRONIZE, False, name)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


class Signal:
    """A named AUTO-reset event: each set() releases exactly one wait().

    Used for "you already have one of these open — show it". Auto-reset is
    the point: a manual-reset event would stay signalled and the window
    would re-raise itself forever after one click.
    """

    def __init__(self, name: str) -> None:
        self._handle = kernel32.CreateEventW(None, False, False, name)
        if not self._handle:
            raise OSError(f"CreateEvent failed: {ctypes.get_last_error()}")

    def wait(self, timeout_ms: int = INFINITE) -> bool:
        """True if it was signalled, False if the timeout expired. The
        timeout exists so the waiting thread can notice its window has
        closed instead of sitting on a handle for the process's life."""
        return kernel32.WaitForSingleObject(
            self._handle, timeout_ms) == WAIT_OBJECT_0

    def close(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None


def signal(name: str) -> bool:
    """Poke a named event someone else created. False = nobody is there."""
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False,
                                 name)
    if not handle:
        return False
    try:
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)


class AlreadyRunning(Exception):
    pass


class InstanceLock:
    """Holds the mutex for this process's lifetime."""

    def __init__(self, name: str = MUTEX_NAME) -> None:
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise OSError(f"CreateMutex failed: {ctypes.get_last_error()}")
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            raise AlreadyRunning(
                "Hebrew dictation is already running (only one instance may "
                "run — two would paste every transcript twice). Use "
                "'Stop dictation' first if you want to restart it.")
        self._handle = handle

    def release(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None


class QuitSignal:
    """Manual-reset event the running instance waits on."""

    def __init__(self) -> None:
        self._handle = kernel32.CreateEventW(None, True, False,
                                             QUIT_EVENT_NAME)
        if not self._handle:
            raise OSError(f"CreateEvent failed: {ctypes.get_last_error()}")

    def wait(self) -> None:
        """Block until someone calls request_quit() (or Ctrl+C)."""
        kernel32.WaitForSingleObject(self._handle, INFINITE)

    def is_set(self) -> bool:
        """Has a quit already been asked for? Checked once before the
        keyboard hook goes in, so a Stop pressed during the ~25 s of model
        loading does not end with live hotkeys for the moment it takes the
        wait below to notice."""
        return kernel32.WaitForSingleObject(self._handle, 0) == WAIT_OBJECT_0

    def close(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None


def request_quit() -> bool:
    """Ask a running instance to exit. False = nothing was running."""
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False,
                                 QUIT_EVENT_NAME)
    if not handle:
        return False
    try:
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)
