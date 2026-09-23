"""Put text on the clipboard, with no Tk and no product module.

Two traps this file is written around, both already paid for in this
repo. ``ctypes.windll.user32`` is a process-global cached object, so
declaring argtypes on it changes them for every module in the process
(capture.py's OverflowError, 2026-08-25) — hence private ``WinDLL``
handles here. And a Tk interpreter built to borrow its clipboard would
have to be buried by the thread that made it (the Tcl_AsyncDelete
aborts) — so there is no Tk in the master's export path at all.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GMEM_MOVEABLE = 0x0002
CF_UNICODETEXT = 13

_user32.OpenClipboard.argtypes = [wintypes.HWND]
_user32.OpenClipboard.restype = wintypes.BOOL
_user32.EmptyClipboard.restype = wintypes.BOOL
_user32.CloseClipboard.restype = wintypes.BOOL
_user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
_user32.SetClipboardData.restype = wintypes.HANDLE
_kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
_kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]


def put(text: str) -> bool:
    """True when the text is on the clipboard. Never raises: a failed
    copy must not lose the folder that was just written."""
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    if not _user32.OpenClipboard(None):
        return False
    handle = None
    try:
        if not _user32.EmptyClipboard():
            return False
        handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False
        where = _kernel32.GlobalLock(handle)
        if not where:
            return False
        ctypes.memmove(where, data, size)
        _kernel32.GlobalUnlock(handle)
        if not _user32.SetClipboardData(CF_UNICODETEXT, handle):
            return False
        handle = None          # the clipboard owns it now
        return True
    except OSError:
        return False
    finally:
        if handle:
            _kernel32.GlobalFree(handle)
        _user32.CloseClipboard()
