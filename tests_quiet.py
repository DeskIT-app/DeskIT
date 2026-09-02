"""Run the test suite with almost nothing appearing on your screen.

    .venv\\Scripts\\python.exe tests_quiet.py            # the whole suite
    .venv\\Scripts\\python.exe tests_quiet.py --out x.txt # keep the transcript

The suite stands up real windows — cards, the dashboard, overlays — and
while it runs they pop over whatever the owner is doing. Windows lets a
process be started on a SECOND desktop object of the same window station
(`CreateDesktop` + `STARTUPINFO.lpDesktop`); every window it and its
children create lands there, invisible unless someone switches to that
desktop, and the tests see an ordinary desktop with a foreground window
and a clipboard (shared across the station). Measured 2026-09-02: 524 of
540 tests pass there exactly as in the open.

The 16 that do not are the ones that need the REAL screen: the ask card
grabs the display (`ImageGrab` fails on a desktop nobody is looking at),
and the drag tests move the real mouse (SendInput goes to the desktop
that has the input, i.e. yours — which is also why they must never run
hidden: their clicks would land on your windows). Those run in the open,
after the rest, for about fifteen seconds. Same `tests.py`, same
interpreter, same exit code; only the location changes.

Python's own subprocess.STARTUPINFO does not expose lpDesktop, so the
hidden half is started through CreateProcessW directly, with cmd's
redirection to a file that is printed here at the end.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as w
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DESKTOP = "HebrewDictationTests"
GENERIC_ALL = 0x10000000
CREATE_NO_WINDOW = 0x08000000
INFINITE = 0xFFFFFFFF

# Tests that need the display or the mouse. Kept as data so the list is
# one place to edit when such a test is added; a test that fails hidden
# and is NOT here is re-run in the open to tell a real failure from a
# hidden-desktop artefact.
NEEDS_SCREEN = (
    "test_a_busy_clipboard_is_a_message_not_a_traceback",
    "test_a_closed_card_leaves_no_interpreter_for_another_thread_to_free",
    "test_a_dictated_question_asks_itself_without_a_keypress",
    "test_a_drag_with_no_button_left_in_it_lets_go",
    "test_a_lasso_sends_only_what_was_lassoed",
    "test_a_new_selection_starts_a_new_conversation",
    "test_an_arriving_answer_never_eats_what_you_typed_while_waiting",
    "test_closing_the_card_mid_answer_does_not_hand_it_to_the_ask_thread",
    "test_ctrl_c_is_swallowed_only_when_the_box_has_a_selection",
    "test_dragging_the_card_redraws_only_what_moved",
    "test_every_painted_control_is_clickable_where_it_is_painted",
    "test_no_global_keeps_a_card_interpreter_alive_past_its_thread",
    "test_talking_over_an_answer_folds_both_sentences_into_one_question",
    "test_the_card_grows_to_fit_a_long_answer_and_then_scrolls",
    "test_the_card_has_a_switch_for_where_a_question_also_goes",
    "test_the_card_is_a_borderless_pane_that_can_be_moved",
)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("lpReserved", w.LPWSTR),
                ("lpDesktop", w.LPWSTR), ("lpTitle", w.LPWSTR),
                ("dwX", w.DWORD), ("dwY", w.DWORD), ("dwXSize", w.DWORD),
                ("dwYSize", w.DWORD), ("dwXCountChars", w.DWORD),
                ("dwYCountChars", w.DWORD), ("dwFillAttribute", w.DWORD),
                ("dwFlags", w.DWORD), ("wShowWindow", w.WORD),
                ("cbReserved2", w.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", w.HANDLE), ("hStdOutput", w.HANDLE),
                ("hStdError", w.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE),
                ("dwProcessId", w.DWORD), ("dwThreadId", w.DWORD)]


def run_hidden(command: str, cwd: Path, desktop: str = DESKTOP) -> int:
    """Run `command` (a cmd.exe line) on a desktop of its own; its exit
    code. The desktop is created if it does not exist and closed after."""
    _user32.CreateDesktopW.restype = w.HANDLE
    hdesk = _user32.CreateDesktopW(desktop, None, None, 0, GENERIC_ALL, None)
    if not hdesk:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = desktop
        pi = PROCESS_INFORMATION()
        buf = ctypes.create_unicode_buffer(f'cmd.exe /c "{command}"')
        _kernel32.CreateProcessW.argtypes = [
            w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL,
            w.DWORD, ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
            ctypes.POINTER(PROCESS_INFORMATION)]
        ok = _kernel32.CreateProcessW(None, buf, None, None, False,
                                      CREATE_NO_WINDOW, None, str(cwd),
                                      ctypes.byref(si), ctypes.byref(pi))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        _kernel32.WaitForSingleObject(pi.hProcess, INFINITE)
        code = w.DWORD()
        _kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
        _kernel32.CloseHandle(pi.hThread)
        _kernel32.CloseHandle(pi.hProcess)
        return int(code.value)
    finally:
        _user32.CloseDesktop(hdesk)


_FAIL = re.compile(r"^  FAIL  (test_\w+)", re.M)


def _read(path: Path) -> str:
    try:
        return path.read_text("utf-8", errors="replace")
    except OSError:
        return ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="keep the transcript in this file")
    args = parser.parse_args(argv)
    # The transcript carries Hebrew and the odd replacement character; a
    # console in cp1255 must not be what kills the run at the last line.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                     # noqa: BLE001 — not a console
        pass
    python = Path(sys.executable)
    started = time.monotonic()
    tmp = Path(tempfile.mkdtemp(prefix="tests-quiet-"))
    hidden_out, open_out = tmp / "hidden.txt", tmp / "open.txt"

    # 1. everything that can run unseen, unseen
    skips = " ".join(f"-{name}" for name in NEEDS_SCREEN)
    run_hidden(f'"{python}" tests.py {skips} > "{hidden_out}" 2>&1', HERE)
    hidden_text = _read(hidden_out)
    hidden_failed = _FAIL.findall(hidden_text)

    # 2. the screen tests, and anything that failed hidden, in the open
    picks = list(NEEDS_SCREEN) + [n for n in hidden_failed
                                  if n not in NEEDS_SCREEN]
    open_proc = subprocess.run([str(python), "tests.py", *picks], cwd=HERE,
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
    open_text = (open_proc.stdout or "") + (open_proc.stderr or "")
    open_failed = _FAIL.findall(open_text)

    transcript = (hidden_text
                  + "\n---- in the open: the screen tests"
                  + (", and what failed hidden" if hidden_failed else "")
                  + " ----\n" + open_text)
    if args.out:                          # first: a console can still choke
        Path(args.out).write_text(transcript, "utf-8")
    sys.stdout.write(transcript)
    hidden_only = [n for n in hidden_failed if n not in open_failed]
    print(f"\n(hidden desktop {DESKTOP!r}: {len(picks)} test(s) ran in the "
          f"open; {time.monotonic() - started:.0f}s in all)")
    if hidden_only:
        print(f"passed in the open after failing hidden — they need the "
              f"screen, add them to NEEDS_SCREEN: {', '.join(hidden_only)}")
    if open_failed:
        print(f"\n{len(open_failed)} FAILED: {', '.join(open_failed)}")
        code = 1
    else:
        print("\nall tests passed (quietly)")
        code = 0
    for p in (hidden_out, open_out):
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        os.rmdir(tmp)
    except OSError:
        pass
    return code


if __name__ == "__main__":
    sys.exit(main())
