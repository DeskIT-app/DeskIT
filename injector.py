"""Clipboard-based text injection into the focused window.

Always clipboard + paste chord, never per-character typing — Hebrew is RTL
and per-character injection breaks in terminals. The synthetic chord is
injected input (LLKHF_INJECTED), so the hotkey state machine ignores it by
design — it cannot abort a recording.

read_selection() is the other direction, and the one thing in here that
writes nothing back: it copies what is selected, reads it, and puts the
user's clipboard back byte for byte. It exists because the lookup key must
be able to run against a web page, a PDF or a read-only field where every
one of the moves above would be either impossible or destructive.

Two kinds of write live in here and they must never be confused, which is
what set_text() and _put_text() are for: one is a copy made FOR the user
and meant to survive, the other is this module loading the clipboard on
its way to a paste chord. Every save-and-restore pair below stands down
rather than putting the old contents back over the first kind — see
claim_mark().
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time

import win32clipboard
import win32con

from hotkey import send_chord, send_key_times

log = logging.getLogger("app")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

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


# ONE CLIPBOARD, AND EVERY THREAD IN THIS PROCESS THAT WANTS IT.
#
# It lives here rather than on main.App because the borrowers are not all
# main's: capture.py writes a screenshot from `capture-shot`, the lookup
# box copies from `lookup-copy`, the ask card has a copy button, and none
# of them has ever heard of App._cursor_lock. That lock's own comment
# claims "every stretch of code that sends keystrokes or borrows the
# clipboard takes this", and it was true of the four threads it named and
# of nothing else.
#
# It did not matter much while the screenshot key was dead for as long as
# anyone was speaking. It matters now: a screenshot taken mid-dictation
# lands its CF_DIB in the ~350 ms between this app staging a transcript
# and the target app asynchronously reading it, and the user gets the
# picture pasted into their document instead of their sentence — with the
# placeholder already backspaced away and the transcript surviving only in
# transcripts.log.
#
# MEASURED 2026-08-30, 40 pastes against capture.copy_image firing 4 ms
# into each one: without this lock the clipboard held the image rather
# than the transcript at read time in 39 of 40; with it, 0 of 40. That is
# not a rare race, it is what happens.
#
# A retry loop cannot stand in for this and never could. Measured and
# written up in popup.py: OpenClipboard does NOT serialise two threads of
# the SAME process — the second one is handed a success it cannot honour,
# because the handle belongs to the task and not to the caller — so
# _open_clipboard's retry never even fires, and the next call raises
# Windows error 1418 instead. 21 writes of 300 failed that way under a
# competitor writing every 4 ms (tests.py, 2026-08-20).
#
# Reentrant because the public calls nest: inject() holds it across
# snapshot -> paste -> restore, and every one of those takes it again.
_board_lock = threading.RLock()


def board_held():
    """Own the clipboard for a whole operation. A context manager.

    For code OUTSIDE this module that writes the clipboard without going
    through set_text — capture.py's copy_image and copy_file, which speak
    CF_DIB and CF_HDROP that this module has no opinion about. They keep
    their own win32clipboard calls; all they take from here is the queue.

    IT WAITS, and there is deliberately no timeout to pass. One was
    offered and taken out again: a `with` body runs whether or not
    __enter__ handed back a lock, so "give up rather than block" written
    that way does not give up — it proceeds UNLOCKED, which is the one
    outcome this whole mechanism exists to prevent, and does it silently.
    A caller that genuinely must not block can take `_board_lock` itself
    and check. Nobody does: the operations this serialises are a few
    hundred milliseconds at their longest, and a screenshot that reaches
    the clipboard 300 ms late is a screenshot that reached the clipboard.
    """
    return _board_lock


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


def _close_clipboard() -> None:
    """CloseClipboard, and never the reason a caller hears about.

    In a `finally` over a body that is already raising, an exception out of
    here REPLACES the one being raised — and the failure this pairs with is
    exactly the one where it happens: 1418 is "this thread does not have a
    clipboard open", so the close fails for the same reason the write did,
    and the ClipboardBusyError the callers are written to catch would be
    swapped for a bare pywintypes.error on its way out. Swallowed, and only
    here: every other close in this module is inside a `try` whose body
    succeeded.
    """
    try:
        win32clipboard.CloseClipboard()
    except Exception:
        pass


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
    with _board_lock:
        return _snapshot_locked()


def _snapshot_locked() -> tuple[str, str | None]:
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


# Every copy this app has made FOR the user, counted. Guarded by a lock
# because the counter is now bumped from threads that hold none of main's
# locks: the lookup box copies on a thread of its own, so that a clipboard
# held by another app cannot freeze the window the user is reading.
_claim_lock = threading.Lock()
_claims = 0


def claim_mark() -> int:
    """Take this when you take a snapshot; hand it to restore() as
    `since`. It is how a restore asks "did the user copy something while
    I was away?" and stands down if the answer is yes.

    A COPY is set_text(): the lookup box's copy button, the dashboard's
    copy-last, a translation left behind because focus moved. Those are
    put there for the user to keep. _put_text() is the other kind — this
    module loading the clipboard on its way to a paste chord — and it
    claims nothing, because the restore that follows it is the whole
    point of it.

    Without this the two are indistinguishable once they are on the
    clipboard, and every save-and-restore pair in the app is a window in
    which a copy can land: the translate key's pair is open for as long
    as the model takes to answer. Measured 2026-08-20, a copy taken from
    the lookup box during a translation was destroyed 5/5 by the restore
    at the end of it, and 5/5 by the one inside read_selection.
    """
    with _claim_lock:
        return _claims


def _claimed_since(mark: int | None) -> bool:
    """Has the user copied something since `mark` was taken? None means
    the caller did not ask, and nothing stands down."""
    return mark is not None and claim_mark() != mark


def _put_text(text: str) -> None:
    """The write itself, claiming nothing. For text this module is only
    passing through the clipboard on its way somewhere else."""
    with _board_lock:
        _open_clipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
        except Exception as e:
            # Windows 1418 and its neighbours come out of pywin32 as a bare
            # error, and every `except ClipboardBusyError` in the app was
            # blind to them — one such escape from show_placeholder used to
            # leave _handle before the audio had been spooled, losing the
            # recording as well as the paste. Now that the whole process
            # queues here they should not happen at all; if one still does,
            # it arrives as the exception the callers already handle.
            raise ClipboardBusyError(f"could not write the clipboard: {e}")
        finally:
            _close_clipboard()


def set_text(text: str) -> None:
    """Put text on the clipboard for the user to keep, and claim it: a
    restore that was in flight around this will now leave it alone. See
    claim_mark() for what that protects and what it measured.

    THE CLAIM IS TAKEN FIRST, and the order is the whole point of it. A
    restore decides on two readings — the sequence number moved, and the
    claim did not — so a claim taken AFTERWARDS leaves a window in which
    it sees exactly the state that means "somebody else's copy, put mine
    back", and destroys the copy this function exists to protect.

    That window is not the microseconds it looks like, because the
    sequence number moves at _put_text's EmptyClipboard and the claim
    cannot follow until its CloseClipboard has returned — so the gap is
    the whole clipboard write, which the clipboard viewers on this
    machine make a slow one. Measured 2026-08-20, 200 writes: median
    30.7 ms open, worst 46.8 ms, against a restore that polls every
    20 ms. Taking _restore_if_touched's own decision at the instant the
    sequence moved: 298 of 300 races would have clobbered the copy
    writing first, 0 of 300 claiming first.

    The rollback is what keeps claiming first from being its own bug: a
    claim that no write ever landed behind would silence a restore that
    should have run. _put_text raises on EmptyClipboard, its first call,
    so the usual failure writes nothing and moves nothing — but it can
    also fail with the clipboard already emptied, and that one MUST be
    restored over rather than stood down on.

    THE BOARD IS TAKEN AROUND BOTH, and it has to be taken FIRST. "Claim
    then write" is only safe while the two are microseconds apart; queue
    the write behind another operation and the claim is visible for as
    long as that operation lasts, with nothing on the clipboard to go with
    it. read_selection would see the bump, conclude the user had copied
    something mid-capture, re-baseline and throw away the answer to its
    own chord — for a copy that had not happened yet. Owning the board
    across the pair closes the gap the other way round: nobody can observe
    the claim, because nobody can look. Measured 2026-08-30 by asking
    _claimed_since while holding the board with a set_text queued behind
    it: 0 of 30 saw a claim whose write had not landed.
    """
    global _claims
    with _board_lock:
        with _claim_lock:
            _claims += 1
        try:
            _put_text(text)
        except BaseException:
            with _claim_lock:
                _claims -= 1
            raise


def clear() -> None:
    """Empty the clipboard. Used as a probe: after this, anything on the
    clipboard demonstrably came from the copy we just sent."""
    with _board_lock:
        _open_clipboard()
        try:
            win32clipboard.EmptyClipboard()
        except Exception as e:
            raise ClipboardBusyError(f"could not empty the clipboard: {e}")
        finally:
            _close_clipboard()


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

    _put_text and not set_text: this text is on its way to a paste chord
    and the caller means to take it back off again, so claiming the
    clipboard here would make every paste stand its own restore down.

    THE WHOLE SPAN IS OWNED, not just the write. The sleep at the end is
    not politeness, it is the target app reading the clipboard on its own
    schedule — so from the write to the end of that wait, whatever is on
    the clipboard is what the user is about to get. A screenshot landing
    in that window (43 ms to encode, then two SetClipboardData calls, on a
    thread of capture.py's own) does not corrupt the paste, it BECOMES the
    paste: the picture arrives in the document where the sentence should
    have been, and by then the placeholder has already been backspaced
    away. That collision was unreachable while the screenshot key was dead
    during a dictation. It is one keystroke away now.
    """
    with _board_lock:
        _put_text(text)
        time.sleep(SETTLE_SECONDS)
        send_chord(paste_chord)
        # The target app reads the clipboard asynchronously after the chord
        # arrives; restoring too early would paste the OLD content.
        time.sleep(max(restore_delay_ms, 0) / 1000)


def restore(state: tuple[str, str | None], what: str = "transcript",
            *, since: int | None = None) -> str:
    """Put back what snapshot() saved. Returns a short status string.

    `since` is claim_mark() as it was when the snapshot was taken. Given
    one, a copy the user made in the meantime wins and this puts nothing
    back: they asked for that copy, and they did not ask for whatever was
    on the clipboard before the key they pressed. Omitted, the restore is
    unconditional — which is right only for a caller with nothing of the
    user's to lose.
    """
    if _claimed_since(since):
        log.info("not restoring your clipboard: something was copied "
                 "while the %s was being prepared, and that copy is the "
                 "one you asked for", what)
        return "a copy was taken meanwhile; clipboard left as it is"
    kind, old_text = state
    if kind == "text":
        _put_text(old_text or "")
        return "old clipboard restored"
    if kind == "empty":
        return f"clipboard was empty before; {what} left on it"
    return ("previous clipboard content was not text (image/files?) — "
            f"cannot restore it; {what} left on the clipboard")


def inject(text: str, paste_chord: str, restore_delay_ms: int) -> str:
    """Save clipboard -> set transcript -> paste -> restore. Returns a short
    status string for the console.

    All four steps under one owner. Split across separate acquisitions the
    snapshot could be of somebody else's write and the restore could put
    it back over a copy the user had since made — and `since=mark` only
    protects against the copies this app CLAIMS, which a screenshot's raw
    CF_DIB is not.

    AND A PICTURE COMES BACK NOW, not just text. `restore()` can only put
    text back; for anything else it says so and leaves the transcript
    where the user's content was. That was a fair v0 trade while the only
    way to have an image on the clipboard was to have put it there some
    time ago — and it stopped being one the moment the screenshot key
    started working mid-dictation, because "take a screenshot while you
    talk" then ends with the transcript pasting over the screenshot you
    just took. The machinery already existed for the lookup key
    (snapshot_all / restore_all, which is what keeps that key from
    disturbing anything at all); this reaches for it exactly when the
    text-only path would have given up.
    """
    with _board_lock:
        state = snapshot()
        blobs = None
        if state[0] == "other":
            try:
                blobs = snapshot_all()
            except ClipboardBusyError:
                blobs = None        # fall through to the old answer
        mark = claim_mark()
        paste_text(text, paste_chord, restore_delay_ms)
        # `blobs` empty means the formats on there are not ones this module
        # knows how to put back (RESTORABLE_FORMATS) — and restore_all([])
        # would EMPTY the clipboard, which is worse than the honest "cannot
        # restore it" the text path already answers with.
        if blobs and not _claimed_since(mark):
            if restore_all(blobs):
                return "old clipboard restored"
            return ("what was on your clipboard could not be put back; "
                    "the transcript is on it")
        return restore(state, since=mark)


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

    Owned end to end, because the whole method is an inference from an
    empty clipboard: empty it, copy, and believe what appears. Anything
    else in this process writing inside that window is read as the answer
    to our own chord — and for translate and punctuate the answer is what
    gets PASTED OVER the user's selection. A screenshot arriving here does
    not read as text at all, so the probe reports "nothing was selected",
    the select-all fallback fires, and the whole field is translated in
    place of the phrase that was meant.
    """
    with _board_lock:
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


# -------------------------------------------------------------------------
# Reading a selection without changing anything
#
# Everything above puts text INTO a window and is allowed to disturb it:
# F9 and F7 select, copy, erase and paste over their own result, so a
# clipboard emptied as a probe and a field left fully selected both cost
# nothing — the paste lands on top a moment later.
#
# A key that only shows you an answer has none of that cover. Whatever it
# disturbs, stays disturbed. So this half of the module empties nothing,
# selects nothing, and puts every format it found back exactly as it was.
# -------------------------------------------------------------------------

# Formats worth putting back. CF_BITMAP and CF_DIBV5 are deliberately not
# in the list: Windows synthesises both from CF_DIB, and restoring CF_DIB
# alone brought the whole trio back (measured 2026-08-19, formats before
# [CF_DIB, CF_BITMAP, CF_DIBV5], formats after identical). Anything else —
# HTML Format, RTF, an app's private tokens — is lost until the user's next
# real copy; see the README's note on what "read-only" does and does not
# promise.
RESTORABLE_FORMATS = (win32con.CF_UNICODETEXT, win32con.CF_DIB,
                      win32con.CF_HDROP)

# Windows Terminal turns a Ctrl+C sent with nothing selected into a REAL
# SIGINT for whatever is running in the tab — reproduced 5/5 on
# 2026-08-19, and ctrl+shift+c interrupts as well, so there is no safe
# chord to substitute. A dictation key is not allowed to kill somebody's
# build, so consoles are refused before anything is sent.
#
# NOT covered, and known: VS Code's integrated terminal reports
# Chrome_WidgetWin_1 like the rest of Electron, so it is indistinguishable
# from an editor pane here and a Ctrl+C there probably reaches the shell.
CONSOLE_CLASSES = frozenset({
    "CASCADIA_HOSTING_WINDOW_CLASS",   # Windows Terminal
    "ConsoleWindowClass",              # conhost — cmd, PowerShell, ssh
    "PseudoConsoleWindow",             # ConPTY's own hidden host window
})

GMEM_MOVEABLE = 0x0002

user32.GetClipboardSequenceNumber.restype = ctypes.c_uint
user32.GetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [ctypes.c_uint]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                 ctypes.c_int]
# c_void_p for the HWND, like every other window call declared here: a
# bare Python int defaults to c_int and a 64-bit handle would be silently
# truncated, which reads as "that window belongs to somebody else".
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,
                                            ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
kernel32.GetCurrentProcessId.restype = ctypes.c_ulong
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
kernel32.GlobalFree.restype = ctypes.c_void_p
kernel32.GlobalFree.argtypes = [ctypes.c_void_p]


def window_class(hwnd: int) -> str:
    """Win32 class name of a window, or "" if it has none."""
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    if not user32.GetClassNameW(hwnd, buf, 256):
        return ""
    return buf.value


def is_console_window(hwnd: int) -> bool:
    """True for a window it is not safe to send a copy chord at."""
    return window_class(hwnd) in CONSOLE_CLASSES


def is_our_window(hwnd: int) -> bool:
    """Does this window belong to THIS process?

    Asked of a paste target, because a transcript can never be meant for
    one of our own windows. Once the screenshot and ask-the-screen keys
    could be pressed mid-dictation, the window in front at the moment the
    hotkey is released is quite often our own fullscreen overlay, and
    aiming a paste at it would send the sentence nowhere — worse, it would
    send the placeholder marker there too and then refuse to take it back
    down, because the focus test would pass.

    By PROCESS ID rather than by class name: the class names are Tk's, so
    a list of them would also match any other Tk app the owner happens to
    be running, and a dictation into a Tk text editor must still paste.
    Returns False on any failure — "not ours" is the answer that leaves
    the old behaviour in place.
    """
    if not hwnd:
        return False
    try:
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return bool(pid.value) and pid.value == kernel32.GetCurrentProcessId()
    except Exception:
        return False


def clipboard_sequence() -> int:
    """A counter Windows bumps on every clipboard write.

    This is what makes the pre-clear in grab() unnecessary here. The number
    moves on every copy even when the copied bytes are byte-identical to
    what is already on the clipboard (measured 5/5, same Notepad selection
    copied five times), so "did the copy produce anything" can be answered
    without emptying the clipboard first — and a press with nothing
    selected then never writes to the clipboard at all.
    """
    return int(user32.GetClipboardSequenceNumber())


def _read_format(fmt: int) -> bytes | None:
    """Raw bytes of one clipboard format. The clipboard must be open.

    Raw, and not win32clipboard.GetClipboardData(), because pywin32 hands
    back a different Python type per format — str for CF_UNICODETEXT, bytes
    for CF_DIB, and a TUPLE OF FILENAMES for CF_HDROP, which
    SetClipboardData then refuses to take back. Measured: snapshot and
    restore through the typed accessors left the clipboard with formats []
    and the user's copied files gone.

    Returns None when the handle cannot be read — a delayed-render owner
    that declines to produce its data — which is a format to skip, not an
    error to raise.
    """
    handle = user32.GetClipboardData(fmt)
    if not handle:
        return None
    address = kernel32.GlobalLock(handle)
    if not address:
        return None
    try:
        return ctypes.string_at(address, kernel32.GlobalSize(handle))
    finally:
        kernel32.GlobalUnlock(handle)


def _alloc_block(blob: bytes) -> int:
    """A moveable global block holding `blob`, ready for SetClipboardData.

    Split out of _write_format so restore_all() can allocate EVERY block
    BEFORE it empties the clipboard: emptying first and then discovering
    there is no memory for the replacement destroys the user's content
    outright, which is the one way this read-only key could ever lose data.
    Fault-injected 2026-08-19: with the write made to fail, the clipboard
    came back empty and the failure was reported as "the clipboard was
    locked" — the wrong problem entirely.
    """
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(blob))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    address = kernel32.GlobalLock(handle)
    if not address:
        kernel32.GlobalFree(handle)
        raise ctypes.WinError(ctypes.get_last_error())
    ctypes.memmove(address, blob, len(blob))
    kernel32.GlobalUnlock(handle)
    return handle


def _write_format(fmt: int, blob: bytes) -> None:
    """Put raw bytes back. The clipboard must be open and emptied.

    The block is allocated here rather than left to pywin32 because
    SetClipboardData(fmt, bytes) allocates one byte more than it is given:
    the same string snapshotted and restored came back 38 bytes, then 39,
    growing by one on every round trip (measured 2026-08-19). Allocating it
    here makes the restore byte-exact, which is the whole promise.

    Windows owns the handle the moment SetClipboardData succeeds, so it is
    freed only on the paths where it did not.
    """
    handle = _alloc_block(blob)
    if not user32.SetClipboardData(fmt, handle):
        kernel32.GlobalFree(handle)
        raise ctypes.WinError(ctypes.get_last_error())


def snapshot_all() -> list[tuple[int, bytes]]:
    """Every restorable clipboard format, as raw bytes.

    Unlike snapshot(), which reports a kind and can only put text back,
    this keeps an image or a set of copied files intact across the capture.
    Raises ClipboardBusyError if the clipboard cannot be opened — and
    because that happens before anything is sent, the caller can give up
    with nothing disturbed.
    """
    _open_clipboard()
    try:
        saved: list[tuple[int, bytes]] = []
        for fmt in RESTORABLE_FORMATS:
            if not win32clipboard.IsClipboardFormatAvailable(fmt):
                continue
            blob = _read_format(fmt)
            if blob:
                saved.append((fmt, blob))
        return saved
    finally:
        win32clipboard.CloseClipboard()


def restore_all(saved: list[tuple[int, bytes]], retries: int = 40,
                delay_s: float = 0.05) -> bool:
    """Put back what snapshot_all() saved. True if it went back.

    The retry budget is deliberately larger than _open_clipboard()'s
    default: this call is the one that owes the user their own clipboard,
    and a clipboard manager holding it for 2.5 s after every change was
    enough to lose the lot when the budget was half a second.
    """
    try:
        _open_clipboard(retries=retries, delay_s=delay_s)
    except ClipboardBusyError:
        return False
    try:
        # Allocate first, empty second. EmptyClipboard() is the point of no
        # return — after it the user's content is gone whether or not the
        # replacement can be written — so everything that can fail on
        # memory happens while the old contents are still there. A failure
        # here leaves the clipboard exactly as it was found.
        blocks: list[tuple[int, int]] = []
        try:
            for fmt, blob in saved:
                blocks.append((fmt, _alloc_block(blob)))
        except OSError as e:
            for _fmt, handle in blocks:
                kernel32.GlobalFree(handle)
            log.error("could not build the clipboard restore (%s) — leaving "
                      "the clipboard exactly as it was", e)
            return False

        win32clipboard.EmptyClipboard()
        ok = True
        for fmt, handle in blocks:
            if not user32.SetClipboardData(fmt, handle):
                kernel32.GlobalFree(handle)
                ok = False
                log.error("could not put clipboard format %d back: %s", fmt,
                          ctypes.WinError(ctypes.get_last_error()))
        return ok
    finally:
        win32clipboard.CloseClipboard()


def _restore_if_touched(saved: list[tuple[int, bytes]], seq0: int,
                        late_sweep_ms: int,
                        since: int | None = None) -> bool:
    """Put the clipboard back, but only if the copy actually landed —
    and only if the user has not taken a copy of their own since.

    Three jobs in one check. If the sequence number never moved, nothing
    was written and there is nothing to put back — so a press with nothing
    selected leaves the clipboard untouched rather than emptied and
    rewritten.

    And if it has not moved yet, wait a little longer before concluding
    that. An app whose copy arrives after the timeout used to land its text
    on the clipboard AFTER the restore, leaving the user holding the
    captured selection instead of their own content (verified destroyed 2/2
    against an app answering at 300 ms with a 250 ms budget). The sweep
    catches that straggler and restores over it.

    The third is `since`, and it is why the sweep cannot simply believe
    the sequence number: the lookup box is on screen while this runs and
    its copy button moves the sequence exactly as a straggler does. See
    claim_mark(). A stand-down is reported as success, because the
    clipboard is holding what the user asked it to hold — the caller's
    False means "your own content is gone", and it is not.
    """
    deadline = time.perf_counter() + max(late_sweep_ms, 0) / 1000
    while clipboard_sequence() == seq0:
        if time.perf_counter() >= deadline:
            return True
        time.sleep(0.02)
    if _claimed_since(since):
        log.info("not restoring your clipboard: you copied something "
                 "while that selection was being read, and that copy is "
                 "the one you asked for")
        return True
    if restore_all(saved):
        return True
    log.error("the clipboard could not be reopened to put your own content "
              "back — it currently holds the text that was just captured; "
              "close whatever is holding the clipboard (a clipboard "
              "manager is the usual culprit) and copy something again")
    return False


def read_selection(copy_chord: str, *, timeout_ms: int = 600,
                   poll_ms: int = 2, settle_ms: int = 15,
                   late_sweep_ms: int = 1500, skip_consoles: bool = True,
                   hwnd: int = 0) -> tuple[str, str]:
    """Copy what is selected and put the clipboard back. Never selects.

    Returns (text, reason); reason is "ok", "nothing-selected", "console"
    or "clipboard-locked". "" ALWAYS means nothing was selected.

    "Puts the clipboard back" has one exception, and it is the only thing
    allowed to outrank the user's own content: a copy the user themselves
    made while this was running. claim_mark() says why.

    WHY THIS IS NOT A FLAG ON grab()
    grab() falls back to select-all when the copy comes up empty, and for
    F9 and F7 that is the right answer: they paste their result over the
    selection a moment later, so a field left fully selected is a field
    about to be overwritten on purpose. This key never pastes. The same
    fallback would leave the user's whole field selected with their next
    keystroke about to wipe it — and would not even be looking up what they
    meant: measured, that select-all grabs 188 chars of a web page, 1781
    chars of an Electron conversation and 11914 chars of terminal
    scrollback. So there is no fallback here at all, and an empty answer is
    reported as one.

    Nothing is emptied first either. clipboard_sequence() tells the two
    cases apart without a probe, which is what makes a mistaken press
    completely free: no copy, no write, no clipboard history entry.

    The wait is a poll, not a sleep. translate.py's flat settle costs 172
    ms on every grab; watching the sequence number answers in a median of
    3.0 ms, which puts a whole capture — snapshot, chord, poll, settle and
    restore — at a measured median of 20 ms from Notepad, 20 ms from a
    read-only Win32 EDIT and 20-24 ms from a Chrome page (2026-08-19).

    timeout_ms is 600 and not 250 because the cost of guessing wrong is
    asymmetric: an app that answers late has its copy land after the
    restore, and the user's clipboard is then holding the captured
    selection for good. Measured against an app made to answer at a fixed
    delay, 300 ms and 500 ms both come back "ok"; 900 ms gives up as
    "nothing-selected" and the sweep below puts the clipboard back.

    A press that finds nothing selected costs up to timeout_ms +
    late_sweep_ms — 2.1 s measured — because the straggler being watched
    for cannot be ruled out any sooner. Pass late_sweep_ms=0 if that delay
    is ever felt more than the tail it protects against.

    hwnd is the window the chord is meant for; 0 means whatever is in the
    foreground now, which is where SendInput will deliver it regardless.
    """
    # BOTH the window the caller meant and the one that has focus right
    # now. They can differ by minutes: the key press is remembered on the
    # hook thread and the capture then waits for the cursor lock, which the
    # translate worker can hold for as long as its model takes. SendInput
    # delivers to whatever is focused at the moment it fires, so testing
    # only the remembered window would send a real interrupt into a
    # terminal the user alt-tabbed to in the meantime.
    live = foreground_window()
    target = hwnd or live
    if skip_consoles:
        for candidate in (target, live):
            if is_console_window(candidate):
                log.info("not sending a copy chord at %s (%s): a console "
                         "turns it into an interrupt for whatever is "
                         "running there", candidate, window_class(candidate))
                return "", "console"

    # OWNED FROM THE SAVE TO THE RESTORE, like every other operation in
    # this module that is an inference from what the clipboard does. This
    # one is a READER and so cannot paste the wrong thing — but its restore
    # puts every saved format back, and a screenshot copied by another
    # thread of this process while it runs would be wiped by that restore
    # with nothing anywhere to say so. Worst case it is held for
    # timeout_ms + late_sweep_ms, and only on a press that found nothing
    # selected.
    with _board_lock:
        try:
            saved = snapshot_all()
        except ClipboardBusyError:
            return "", "clipboard-locked"

        # Taken with the snapshot and not later: the box from the LAST press
        # is still on screen while this one runs, and a copy taken off it
        # belongs to the user, not to this capture. See claim_mark().
        mark = claim_mark()
        seq0 = clipboard_sequence()
        text = ""
        reason = "nothing-selected"
        try:
            send_chord(copy_chord)
            deadline = time.perf_counter() + timeout_ms / 1000
            # The loop's own baseline, moved on by a copy that was not ours.
            # `mark` itself is left alone: the restore in the finally reads it
            # to decide whether to stand down, and that decision is about the
            # whole call, not about one bump.
            claimed = mark
            while time.perf_counter() < deadline:
                if clipboard_sequence() != seq0:
                    time.sleep(settle_ms / 1000)   # let every format land
                    if _claimed_since(claimed):
                        # A copy the USER took, off a box that was already on
                        # screen — its copy button, or ctrl+C on a selection
                        # in it. It moved the sequence, but it is not an
                        # answer to the chord this function just sent, and
                        # reading it as one hands the app its own text back.
                        # For the lookup key that is a box quoting itself; for
                        # translate and punctuate it is worse, because those
                        # PASTE what they read over whatever the user had
                        # selected. Re-baseline and keep waiting — the copy
                        # this call asked for may still be on its way.
                        claimed = claim_mark()
                        seq0 = clipboard_sequence()
                        continue
                    text = get_text()
                    reason = "ok" if text.strip() else "nothing-selected"
                    break
                time.sleep(poll_ms / 1000)
        except ClipboardBusyError:
            text, reason = "", "clipboard-locked"
        finally:
            # In a finally, and not after the loop, because anything raising
            # between the copy and the restore leaves the user's clipboard
            # holding the captured selection: verified destroyed 3/3 without
            # this, survived 2/2 with it.
            if not _restore_if_touched(saved, seq0, late_sweep_ms, mark):
                text, reason = "", "clipboard-locked"

        if not text.strip():
            text = ""
        return text, reason


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
