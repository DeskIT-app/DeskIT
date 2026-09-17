"""Run the test suite with almost nothing appearing on your screen.

    .venv\\Scripts\\python.exe tests_quiet.py            # the whole suite
    .venv\\Scripts\\python.exe tests_quiet.py --out x.txt # keep the transcript
    .venv\\Scripts\\python.exe tests_quiet.py --no-screen # nothing on your screen

"The suite" is two files since PR 8 (DISTRIBUTION_PLAN.md 7.5): tests.py,
the product's, which GitHub's CI also runs, and dev\\tests_ops.py, the
owner's — the nightly run, the git card, the routine's docs — which only
this checkout can run. Both go on the hidden desktop, one after the
other; the sixteen below are tests.py's.

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

**While you are at the machine, use --no-screen.** The sixteen leave
the hidden desktop by design — the ask card grabs the display, the drag
tests move the REAL mouse — so an ordinary run puts windows over what
you are doing and takes the pointer for about fifteen seconds. With
--no-screen they are skipped outright and the run is invisible; the
exit code then says nothing about them, so run the suite plainly once
before shipping. (The owner asked for this on 2026-09-07: "a lot of
things jump on my screen".)

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
DESKTOP = "DeskITTests"
GENERIC_ALL = 0x10000000
CREATE_NO_WINDOW = 0x08000000
INFINITE = 0xFFFFFFFF

# The tests that need the display or the mouse are tests.py's own list,
# NEEDS_SCREEN, kept there since PR 8 so that `tests.py --no-screen` and
# test_needs_screen_list_is_complete see the same names as this runner.
# Read with ast rather than imported: importing the suite here would pull
# in Tk, numpy and every product module before a single test ran. A test
# that fails hidden and is NOT on the list is re-run in the open to tell
# a real failure from a hidden-desktop artefact.
OPS = Path("dev") / "tests_ops.py"


def needs_screen() -> tuple[str, ...]:
    """tests.py's NEEDS_SCREEN, read off the file."""
    import ast
    tree = ast.parse((HERE / "tests.py").read_text("utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "NEEDS_SCREEN"
                for t in node.targets):
            return tuple(ast.literal_eval(node.value))
    raise LookupError("tests.py has no NEEDS_SCREEN")


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
    parser.add_argument("--no-screen", action="store_true",
                        help="skip the tests that need the real screen "
                             "or the real mouse, so nothing appears")
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
    hidden_out, ops_out, open_out = (tmp / "hidden.txt", tmp / "ops.txt",
                                     tmp / "open.txt")
    NEEDS_SCREEN = needs_screen()

    # 1. everything that can run unseen, unseen: the product suite without
    #    the sixteen, then the owner's suite (all of it — nothing there
    #    needs the screen), each in a process of its own
    run_hidden(f'"{python}" tests.py --no-screen > "{hidden_out}" 2>&1',
               HERE)
    run_hidden(f'"{python}" {OPS} > "{ops_out}" 2>&1', HERE)
    product_text, ops_text = _read(hidden_out), _read(ops_out)
    hidden_text = product_text + f"\n---- {OPS} ----\n" + ops_text
    product_failed = _FAIL.findall(product_text)
    ops_failed = _FAIL.findall(ops_text)
    hidden_failed = product_failed + ops_failed

    # 2. the screen tests, and anything that failed hidden, in the open —
    #    unless he is sitting there, in which case nothing runs in the
    #    open at all and the sixteen are simply not run. An ops test that
    #    failed hidden is re-run through its own file.
    picks = list(NEEDS_SCREEN) + [n for n in product_failed
                                  if n not in NEEDS_SCREEN]
    if args.no_screen:
        picks = []
        open_text = ""
        open_failed = list(hidden_failed)
    else:
        runs = [("tests.py", picks)]
        if ops_failed:
            runs.append((str(OPS), ops_failed))
        open_text = ""
        for script, names in runs:
            open_proc = subprocess.run([str(python), script, *names],
                                       cwd=HERE, capture_output=True,
                                       text=True, encoding="utf-8",
                                       errors="replace")
            open_text += (open_proc.stdout or "") + (open_proc.stderr or "")
        open_failed = _FAIL.findall(open_text)

    transcript = hidden_text if args.no_screen else (
        hidden_text
        + "\n---- in the open: the screen tests"
        + (", and what failed hidden" if hidden_failed else "")
        + " ----\n" + open_text)
    if args.out:                          # first: a console can still choke
        Path(args.out).write_text(transcript, "utf-8")
    sys.stdout.write(transcript)
    hidden_only = [n for n in hidden_failed if n not in open_failed]
    if args.no_screen:
        print(f"\n(hidden desktop {DESKTOP!r}: nothing ran in the open; "
              f"{len(NEEDS_SCREEN)} test(s) that need the screen or the "
              f"mouse were SKIPPED; {time.monotonic() - started:.0f}s)")
    else:
        print(f"\n(hidden desktop {DESKTOP!r}: {len(picks)} test(s) ran in "
              f"the open; {time.monotonic() - started:.0f}s in all)")
    if hidden_only:
        print(f"passed in the open after failing hidden — they need the "
              f"screen, add them to NEEDS_SCREEN: {', '.join(hidden_only)}")
    if open_failed:
        print(f"\n{len(open_failed)} FAILED: {', '.join(open_failed)}")
        code = 1
    else:
        print("\nall tests passed (quietly)")
        code = 0
    for p in (hidden_out, ops_out, open_out):
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
