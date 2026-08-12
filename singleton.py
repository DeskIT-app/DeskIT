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

kernel32.CreateMutexW.restype = w.HANDLE
kernel32.CreateEventW.restype = w.HANDLE
kernel32.OpenEventW.restype = w.HANDLE
kernel32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]


class AlreadyRunning(Exception):
    pass


class InstanceLock:
    """Holds the mutex for this process's lifetime."""

    def __init__(self) -> None:
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
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
