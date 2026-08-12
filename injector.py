"""Clipboard-based text injection into the focused window.

Always clipboard + paste chord, never per-character typing — Hebrew is RTL
and per-character injection breaks in terminals. The synthetic chord is
injected input (LLKHF_INJECTED), so the hotkey state machine ignores it by
design — it cannot abort a recording.
"""
from __future__ import annotations

import ctypes
import time

import win32clipboard
import win32con

from hotkey import send_chord, send_key_times

user32 = ctypes.WinDLL("user32", use_last_error=True)

# Small pause between setting the clipboard and sending the paste chord.
SETTLE_SECONDS = 0.05


class ClipboardBusyError(Exception):
    pass


class FocusChangedError(Exception):
    """The window that received the placeholder is no longer focused, so the
    erase-and-replace would corrupt whatever the user moved to."""


def foreground_window() -> int:
    """HWND of the focused window, or 0. Used to prove the placeholder is
    still where we put it before sending backspaces at it."""
    try:
        return int(user32.GetForegroundWindow())
    except Exception:
        return 0


def erase_units(text: str) -> int:
    """How many backspaces erase `text`.

    Backspace deletes one UTF-16 code unit, so anything outside the BMP
    (emoji) needs two. Counting in code units keeps the placeholder erasable
    whatever it is set to.
    """
    return len(text.encode("utf-16-le")) // 2


def _open_clipboard(retries: int = 10, delay_s: float = 0.05) -> None:
    for _ in range(retries):
        try:
            win32clipboard.OpenClipboard()
            return
        except Exception:
            time.sleep(delay_s)
    raise ClipboardBusyError(
        "clipboard is locked by another application (retried %d times)"
        % retries)


def snapshot() -> tuple[str, str | None]:
    """('empty'|'text'|'other', text) for the current clipboard contents."""
    _open_clipboard()
    try:
        if win32clipboard.CountClipboardFormats() == 0:
            return ("empty", None)
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return ("text",
                    win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT))
        return ("other", None)  # image, files, ... — v0 cannot restore these
    finally:
        win32clipboard.CloseClipboard()


def set_text(text: str) -> None:
    _open_clipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def inject(text: str, paste_chord: str, restore_delay_ms: int) -> str:
    """Save clipboard -> set transcript -> paste -> restore. Returns a short
    status string for the console."""
    state = snapshot()
    set_text(text)
    time.sleep(SETTLE_SECONDS)
    send_chord(paste_chord)
    # The target app reads the clipboard asynchronously after the chord
    # arrives; restoring too early would paste the OLD content.
    time.sleep(max(restore_delay_ms, 0) / 1000)
    kind, old_text = state
    if kind == "text":
        set_text(old_text or "")
        return "old clipboard restored"
    if kind == "empty":
        return "clipboard was empty before; transcript left on it"
    return ("previous clipboard content was not text (image/files?) — "
            "cannot restore it; transcript left on the clipboard")


def show_placeholder(text: str, paste_chord: str,
                     restore_delay_ms: int) -> int:
    """Drop a visible 'working on it' marker at the cursor and return the
    HWND it landed in.

    The marker reserves the spot: however long transcription takes, the
    transcript replaces this exact text in this exact window, so a slow
    request cannot scatter output into whatever the user did next.
    """
    inject(text, paste_chord, restore_delay_ms)
    return foreground_window()


def replace_placeholder(placeholder: str, text: str, paste_chord: str,
                        restore_delay_ms: int, hwnd: int) -> str:
    """Erase the placeholder and paste the transcript in its place.

    Raises FocusChangedError if the user moved to another window — the
    caller then falls back to leaving the text on the clipboard rather than
    firing backspaces into an unrelated app.
    """
    if hwnd and foreground_window() != hwnd:
        raise FocusChangedError(
            "focus moved away from the window holding the placeholder")
    send_key_times("backspace", erase_units(placeholder))
    time.sleep(SETTLE_SECONDS)
    return inject(text, paste_chord, restore_delay_ms)


def clear_placeholder(placeholder: str, hwnd: int) -> bool:
    """Erase the placeholder with nothing to put back (failed for good).
    Returns False if focus moved and it was left in place."""
    if hwnd and foreground_window() != hwnd:
        return False
    send_key_times("backspace", erase_units(placeholder))
    return True
