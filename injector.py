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


def _format_count() -> int:
    """0 for an empty clipboard.

    win32clipboard raises on a 0 return here — the API reports "no formats"
    and failure with the same value, and pywin32 reads it as failure. An
    empty clipboard is a normal state (the selection probe in grab()
    creates one deliberately), so the exception is translated back into the
    count it actually means.
    """
    try:
        return win32clipboard.CountClipboardFormats()
    except Exception:
        return 0


def snapshot() -> tuple[str, str | None]:
    """('empty'|'text'|'other', text) for the current clipboard contents."""
    _open_clipboard()
    try:
        if _format_count() == 0:
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


def clear() -> None:
    """Empty the clipboard. Used as a probe: after this, anything on the
    clipboard demonstrably came from the copy we just sent."""
    _open_clipboard()
    try:
        win32clipboard.EmptyClipboard()
    finally:
        win32clipboard.CloseClipboard()


def get_text() -> str:
    """Clipboard text, or "" when it holds nothing or holds a non-text
    format."""
    kind, text = snapshot()
    return text if kind == "text" and text else ""


def paste_text(text: str, paste_chord: str, restore_delay_ms: int) -> None:
    """Put text on the clipboard and send the paste chord.

    No save/restore of its own — the caller owns that. Split out of
    inject() because the translate path has to snapshot the clipboard once
    around the whole grab-then-replace: by paste time the clipboard already
    holds the text that was grabbed, so restoring from here would put the
    user's Hebrew back instead of what they had before.
    """
    set_text(text)
    time.sleep(SETTLE_SECONDS)
    send_chord(paste_chord)
    # The target app reads the clipboard asynchronously after the chord
    # arrives; restoring too early would paste the OLD content.
    time.sleep(max(restore_delay_ms, 0) / 1000)


def restore(state: tuple[str, str | None], what: str = "transcript") -> str:
    """Put back what snapshot() saved. Returns a short status string."""
    kind, old_text = state
    if kind == "text":
        set_text(old_text or "")
        return "old clipboard restored"
    if kind == "empty":
        return f"clipboard was empty before; {what} left on it"
    return ("previous clipboard content was not text (image/files?) — "
            f"cannot restore it; {what} left on the clipboard")


def inject(text: str, paste_chord: str, restore_delay_ms: int) -> str:
    """Save clipboard -> set transcript -> paste -> restore. Returns a short
    status string for the console."""
    state = snapshot()
    paste_text(text, paste_chord, restore_delay_ms)
    return restore(state)


def grab(copy_chord: str, select_all_chord: str,
         settle_s: float) -> tuple[str, bool]:
    """Copy what is selected; if nothing is, select the whole field first.

    Returns (text, had_selection). The clipboard is emptied first so that
    "the copy produced nothing" is distinguishable from "the copy produced
    what was already on the clipboard" — without that probe there is no way
    to tell an empty selection from a lucky match.

    The caller must snapshot() the clipboard before calling this and
    restore() it afterwards: this deliberately leaves the grabbed text on
    the clipboard so a failure further down still leaves the user holding
    their own words.

    Known corner: a few editors (VS Code) copy the CURRENT LINE when
    nothing is selected, which reads here as had_selection=True. Pasting
    then inserts rather than replaces, so the line ends up duplicated and
    needs one Ctrl+Z. Chat-style inputs — the actual use case — copy
    nothing on an empty selection and are unaffected.
    """
    clear()
    time.sleep(SETTLE_SECONDS)
    send_chord(copy_chord)
    time.sleep(settle_s)
    text = get_text()
    if text.strip():
        return text, True

    send_chord(select_all_chord)
    time.sleep(SETTLE_SECONDS)
    send_chord(copy_chord)
    time.sleep(settle_s)
    return get_text(), False


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
