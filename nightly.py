"""The whole test suite, once a night, with one question first.

Sixteen of the suite's tests need the REAL screen and the REAL mouse
(`tests_quiet.NEEDS_SCREEN`): the ask card grabs the display and the drag
tests move the pointer. House rule 8 says that while the owner is at the
machine the command is `tests_quiet.py --no-screen`, which skips those
sixteen outright — and he is at the machine every day, so they had not
run for days. This is the hour when nobody is: 02:55, the whole suite,
the sixteen included.

WHY THE TASK SCHEDULER AND NOT A TIMER INSIDE THE APP. A timer in
main.py would be less to install and it would be wrong: on the night
DeskIT had crashed there would be no test run, and that is exactly the
night you would want one. So the trigger lives outside the thing it is
testing — nightly_tests.ps1, started by a Windows scheduled task, which
calls this module. The app may be running or not; neither must break the
other.

THE QUESTION, AND THE DEFAULT THAT MATTERS. At 02:55 a card asks whether
to run, with Yes and No. If nobody answers within five minutes it RUNS.
Running is the default, not skipping.

The obvious alternative was an idle check -- do not run if he touched the
computer recently -- and he rejected it in these words:

    "מישהו יקום באמצע הלילה לשתות והבקבוק ייפול לי על המקלדת ואז היא
     תחשוב שאני כאן"

-- someone gets up in the night for a drink, the bottle falls on the
keyboard, and the machine decides he is present. Anyone moving in the
night looks like him being there, and an idle check would silently
cancel the run. A question that defaults to RUNNING cannot be defeated
that way: the worst an accident can do is answer "yes" to something that
was going to happen anyway.

THE MONITORS ARE NOT WOKEN, AND THAT IS ON PURPOSE. His screens are
usually off at that hour -- he blanks them with the screens key and they
blank themselves after five minutes -- and showing a window does not
power a monitor back on. That is fine: if he is awake he sees the card,
and if he is asleep he does not and it runs, which is what he asked for.
The screen tests do not need the monitors either. Measured 2026-09-08
with the screens off via the screens key for 31 seconds (app.log:
`screens off (key)` 20:15:31 -> `screens on (key)` 20:16:02): a probe
sampling `ImageGrab.grab()` every two seconds took 16 samples inside that
blackout and every one came back a real 2560x1440 picture with a full
brightness range of 0..255 -- no exception, and never an all-black frame.
So there is no wake-the-monitors step in this file, and there must not
be one: a nightly run that turns his screens on at three in the morning
is a worse bug than any test it could catch.

WHAT COMES OUT OF IT -- AND HE DOES NOT WANT A REPORT EVERY MORNING.

  * A CLEAN run files NOTHING. No card, no document, no row. He should
    not wake up to a receipt.
  * A run with real failures files ONE report into the problems store,
    so it appears on the Problems place like a report he filed himself
    -- and so the Saturday routine (.claude\\commands\\weekly-reports.md)
    picks it up and rules on it like any other problem. That was his
    idea, and it is why the text below is written the way §1 of that
    command reads reports: what failed, what the evidence is, and where
    it is.
  * KNOWN_FLAKES is the honest exception. One test fails on nearly every
    run of this machine for reasons that have nothing to do with the
    code, and a report every single morning is a report he stops
    reading. It is named here, with the reason, and a run whose only
    failures are named here files nothing -- but the run.log still says
    it failed, because a filter nobody can see is a lie.
  * A run HE STOPPED is recorded as stopped, never as a failure. His
    words, and obviously right: pressing Stop is not a bug.

THE CONTRACT WITH THE DASHBOARD, WHICH IS THE ONE THING TWO PROCESSES
SHARE. Everything lives in problems\\nightly\\ (gitignored with the rest
of problems\\):

  run.log        what every run did, appended, one previous generation
                 kept -- the same shape problems\\weekly\\run.log has.
  run.lock       AN OS-HELD BYTE LOCK, taken for the whole of one
                 invocation -- the question and the suite together. It
                 is what stops two runs overlapping, and it CANNOT WEDGE
                 THE FEATURE: Windows drops the lock when the process
                 ends however it ended -- cleanly, on an exception, on a
                 kill, on a power cut -- so there is no such thing as a
                 stale lock here and no override is needed. The file is
                 left behind on purpose; the lock is the handle, never
                 the file's existence. weekly_review.ps1 settled on the
                 same thing for the same reason.
  running.json   THE MARKER THE DASHBOARD POLLS: written the moment the
                 suite starts and deleted the moment it ends, so the
                 Stop button exists exactly while there is a run to
                 stop. It is not trusted on its own -- `running()` also
                 asks whether the lock is held, which is the liveness
                 test the file cannot do, so a marker left behind by a
                 killed run does not put a dead button in his bar
                 forever.
  stop           what the dashboard's Stop button writes. The runner
                 clears it before the suite starts, watches for it every
                 second while the suite runs, and kills the run when it
                 appears. A file rather than a pipe because the app may
                 not be running at all, and the dashboard talks to a
                 process that is not it.
  <stamp>.txt    the transcript of one run, which the report points at.

Nothing here may raise into the UI. No scheduled task, no [tests]
section, no problems store, no run.log that will not open -- every one of
those is a quieter night, not a traceback.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("app")

# Under problems\, beside problems\weekly\ -- the whole folder is
# gitignored, which is right: a transcript of this machine's test run is
# this machine's business.
FOLDER_NAME = "nightly"
PARENT_NAME = "problems"

LOG_NAME = "run.log"
LOCK_NAME = "run.lock"
MARKER_NAME = "running.json"
STOP_NAME = "stop"

# One previous generation, the way app.log / app.log.1 and
# problems\weekly\run.log already do it.
LOG_MAX_BYTES = 512 * 1024

# Transcripts kept, newest first. Two weeks of nights is enough to read a
# failure that was fixed and came back, and each one is about 60 KB.
KEEP_TRANSCRIPTS = 14

# How long the card waits before it answers itself, and what it answers.
# The default is in config.toml as well ([tests] wait_seconds); this is
# what the code falls back on when there is no config to read.
ASK_SECONDS = 300.0

# What one run came to. `flaky` is a run whose ONLY failures are in
# KNOWN_FLAKES: it failed, it is written down as having failed, and it
# files nothing.
CLEAN, FAILED, FLAKY, STOPPED = "clean", "failed", "flaky", "stopped"
SKIPPED, BUSY, OFF = "skipped", "busy", "off"

# Tests that fail on this machine for reasons that are not the code's.
#
# A NAMED, DOCUMENTED EXCEPTION AND NOT A SILENT FILTER. The owner's
# reason for wanting one at all: a false alarm every single morning is a
# report he stops reading, and then the real one goes past him too. So
# the rule is narrow -- a run files nothing only when EVERY failure it
# had is named here -- and the run.log still says exactly what failed,
# named, whether or not a report was filed.
#
# test_the_process_list_sees_the_processes_it_cannot_open compares the
# sum of every process's private memory against what Windows says the
# machine is using, and the two are measured a moment apart on a live
# machine, so a process that starts or exits between the two readings
# moves the number. Baseline 2026-09-08 on this machine, one
# `tests_quiet.py --no-screen` run of 711 tests: it is the only failure,
# "per-process sum 235564 vs machine total 244414".
KNOWN_FLAKES = {
    "test_the_process_list_sees_the_processes_it_cannot_open":
        "the per-process memory sum is read a moment after the machine "
        "total, so anything that starts or exits in between moves it",
}

# What goes on the card. Kept here rather than in the window function so
# the words can be read, and tested, without a screen.
CARD_TITLE = "Run the whole test suite now?"
CARD_BODY = ("It takes a few minutes and it uses the screen and the "
             "mouse — including the sixteen tests that can only run when "
             "nobody is here.")
CARD_YES = "Yes, run it"
CARD_NO = "No, not tonight"
# The line under the buttons, which is the whole point of the card: it
# says what happens if he walks away, and what happens is that it runs.
CARD_DEFAULT = "No answer in {mins} minute{s} and it runs anyway."

# Where a report says it came from, and what kind it is. `broken` is
# problems.KINDS' word for "something is broken", which a red test is.
REPORT_WHERE = "Nightly tests"
REPORT_KIND = "broken"
REPORT_BY = "nightly"

# How many failing test names the report spells out before it starts
# counting. problems.TEXT_MAX cuts a report at 600 characters with an
# ellipsis, and a truncated test name is a name nobody can run -- so the
# cut happens here, at a whole name, and the rest are counted.
REPORT_NAMES = 8

# tests_quiet.py's own last word: "N FAILED: a, b, c" or "all tests
# passed (quietly)". It is what to read rather than counting FAIL lines,
# because tests_quiet re-runs a hidden failure in the open and only it
# knows which of the two results counted.
_SUMMARY = re.compile(r"^\d+ FAILED: (.+)$", re.M)
_PASSED = re.compile(r"^all tests passed", re.M)
_FAIL_LINE = re.compile(r"^  FAIL  (test_\w+)", re.M)

_STAMP = "%Y%m%d-%H%M%S"


# ---------------------------------------------------------------------------
# where everything lives
# ---------------------------------------------------------------------------

def folder(app_dir) -> Path:
    """problems\\nightly\\ under the app, made if it is not there."""
    path = Path(app_dir) / PARENT_NAME / FOLDER_NAME
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:                  # noqa: BLE001
        log.info("nightly: could not make %s (%s)", path, e)
    return path


def _path(app_dir, name: str) -> Path:
    return Path(app_dir) / PARENT_NAME / FOLDER_NAME / name


def note(app_dir, text: str) -> None:
    """One line into run.log. Never raises: a log we cannot write must
    not take the run down."""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n"
    try:
        path = folder(app_dir) / LOG_NAME
        try:
            if path.stat().st_size >= LOG_MAX_BYTES:
                os.replace(path, path.with_name(LOG_NAME + ".1"))
        except OSError:
            pass
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# the lock, the marker and the stop file -- the contract at the top
# ---------------------------------------------------------------------------

def _locked_by_somebody(path: Path) -> bool:
    """Is another process holding the byte lock on `path`?

    Asked by TRYING to take it and giving it straight back. That is the
    only honest liveness test on Windows: the lock exists for exactly as
    long as its owner's handle does, so this answers "is a run alive"
    rather than "was there a run once", which is what a pid file or a
    plain marker answers.
    """
    fd = None
    try:
        import msvcrt
        fd = os.open(path, os.O_RDWR | os.O_CREAT)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return True
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return False
    except Exception:                     # noqa: BLE001 — no msvcrt, no file
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


@contextmanager
def hold(app_dir):
    """The whole of one invocation, question and suite together.

    Yields True when this process has the run to itself and False when
    another one is already at it -- the caller does nothing at all in
    that case. See the contract at the top of the file for why a handle
    and not a pid.
    """
    path = _path(app_dir, LOCK_NAME)
    folder(app_dir)
    fd = None
    held = False
    try:
        import msvcrt
        fd = os.open(path, os.O_RDWR | os.O_CREAT)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            held = True
        except OSError:
            held = False
    except Exception:                     # noqa: BLE001
        # No msvcrt at all (not Windows, or a stripped build). One run at
        # a time is then the scheduler's IgnoreNew and nothing else,
        # which is what the weekly review lived on for a week.
        held = True
    try:
        yield held
    finally:
        if fd is not None:
            if held:
                try:
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except Exception:         # noqa: BLE001
                    pass
            try:
                os.close(fd)
            except OSError:
                pass


def mark_running(app_dir, started: float | None = None) -> None:
    """Say that the SUITE is going -- which is not the same as the lock,
    which is held through the five minutes of asking as well."""
    row = {"pid": os.getpid(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "started": float(started if started is not None else time.time())}
    try:
        _path(app_dir, MARKER_NAME).write_text(
            json.dumps(row, ensure_ascii=False), "utf-8")
    except OSError as e:                  # noqa: BLE001
        log.info("nightly: could not write the marker (%s)", e)


def clear_running(app_dir) -> None:
    try:
        os.remove(_path(app_dir, MARKER_NAME))
    except OSError:
        pass


def running(app_dir) -> bool:
    """Is a nightly suite going right now? The dashboard's question, and
    the only thing it has to ask to know whether to draw Stop.

    BOTH halves are needed. The marker alone would survive a killed run
    and leave a button that stops nothing in his bar for ever; the lock
    alone is held through the five minutes of asking, when there is
    nothing to stop yet.
    """
    try:
        if not _path(app_dir, MARKER_NAME).exists():
            return False
    except OSError:
        return False
    return _locked_by_somebody(_path(app_dir, LOCK_NAME))


def ask_stop(app_dir) -> bool:
    """End the run that is going. What the dashboard's Stop button does;
    True if the ask was written down."""
    try:
        folder(app_dir)
        _path(app_dir, STOP_NAME).write_text(
            time.strftime("%Y-%m-%d %H:%M:%S"), "utf-8")
        return True
    except OSError as e:                  # noqa: BLE001
        log.info("nightly: could not ask the run to stop (%s)", e)
        return False


def stop_asked(app_dir) -> bool:
    try:
        return _path(app_dir, STOP_NAME).exists()
    except OSError:
        return False


def clear_stop(app_dir) -> None:
    try:
        os.remove(_path(app_dir, STOP_NAME))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# reading what the suite said
# ---------------------------------------------------------------------------

def failures(transcript: str) -> list[str]:
    """The tests that failed, as tests_quiet.py counted them.

    Its own summary line is the authority, not the FAIL lines: a test
    that fails on the hidden desktop is re-run in the open, and only
    tests_quiet knows which of the two results is the verdict. The FAIL
    lines are the fallback for a run that died before it could print a
    summary at all.
    """
    text = transcript or ""
    match = None
    for match in _SUMMARY.finditer(text):
        pass                              # the LAST one is the verdict
    if match is not None:
        return [name.strip() for name in match.group(1).split(",")
                if name.strip()]
    if _PASSED.search(text):
        return []
    seen: list[str] = []
    for name in _FAIL_LINE.findall(text):
        if name not in seen:
            seen.append(name)
    return seen


def real_failures(names) -> list[str]:
    """What is left once the machine's known flakes are set aside."""
    return [name for name in names if name not in KNOWN_FLAKES]


def verdict(*, transcript: str = "", code: int | None = 0,
            stopped: bool = False) -> dict:
    """What one run came to, as the one dict everything downstream reads.

    A STOP IS NOT A FAILURE, and it is checked first for that reason. He
    said so in as many words, and the arithmetic agrees: a suite killed
    in the middle has failures that only mean it was killed.
    """
    if stopped:
        return {"result": STOPPED, "failed": [], "real": [], "code": code}
    failed = failures(transcript)
    real = real_failures(failed)
    if real:
        result = FAILED
    elif failed:
        result = FLAKY
    elif code not in (0, None):
        # It never printed a verdict and it did not exit 0 -- a crash, an
        # import error, a machine that went down mid-run. That is a real
        # failure with no test name on it, and it is worth a report.
        result = FAILED
    else:
        result = CLEAN
    return {"result": result, "failed": failed, "real": real, "code": code}


# ---------------------------------------------------------------------------
# the one report a bad night files
# ---------------------------------------------------------------------------

def report_text(got: dict, *, transcript_path: str = "", seconds: float = 0.0,
                total: int | None = None, when: str = "") -> str:
    """The report's body, in the shape the Saturday routine reads.

    ENGLISH, and that is a decision rather than a slip. Every noun in it
    is an English identifier -- test names, a path, a command he pastes
    -- and a Hebrew sentence wrapped around them is exactly the mixed
    line that comes out of a bidi layout scrambled (notify_card.py has
    the same rule and the same reason). His own reports stay his own
    words; this one is the machine's, and it says so at the end.

    §1 of weekly-reports.md rules on a report from its evidence, so the
    evidence is what this is: which tests, how many, where the whole
    transcript is, and the one command that reproduces it.
    """
    names = list(got.get("real") or got.get("failed") or [])
    when = when or time.strftime("%Y-%m-%d %H:%M")
    head = f"The nightly test run failed on {when}."
    if names:
        count = (f"{len(names)} of {total} tests failed"
                 if total else f"{len(names)} test(s) failed")
        shown = names[:REPORT_NAMES]
        rest = len(names) - len(shown)
        lines = [head, "", count + ":"]
        lines += [f"  {name}" for name in shown]
        if rest > 0:
            lines.append(f"  …and {rest} more, in the transcript.")
        lines += ["",
                  f"Run one: .venv\\Scripts\\python.exe tests.py {shown[0]}"]
    else:
        lines = [head, "",
                 f"The suite printed no verdict and exited "
                 f"{got.get('code')} — it did not finish."]
    if transcript_path:
        lines.append(f"The whole run: {transcript_path}")
    if seconds:
        lines.append(f"It took {seconds:.0f}s.")
    lines += ["",
              "Filed by nightly.py, not by Yoav — nobody was at the "
              "keyboard. The suite ran whole, the sixteen screen tests "
              "included."]
    return "\n".join(lines)


def file_report(app_dir, got: dict, *, cfg=None, transcript_path: str = "",
                seconds: float = 0.0, total: int | None = None) -> dict | None:
    """One report into problems.json, and problems.md rewritten so the
    weekly read sees it. None when nothing should be filed, or when the
    store could not be reached -- which is a quieter night, not a
    traceback.
    """
    if got.get("result") != FAILED:
        return None
    try:
        import problems
    except Exception as e:                # noqa: BLE001
        log.info("nightly: no problems store to file into (%s)", e)
        return None
    try:
        app_dir = Path(app_dir)
        store = problems.Store(app_dir / problems.STORE_NAME)
        item = store.add({
            "where": REPORT_WHERE,
            "kind": REPORT_KIND,
            "by": REPORT_BY,
            "text": report_text(got, transcript_path=transcript_path,
                                seconds=seconds, total=total),
            "env": problems.env(cfg),
        })
    except Exception as e:                # noqa: BLE001
        log.warning("nightly: could not file the report (%s)", e)
        return None
    try:
        problems.digest(store, app_dir / problems.DIGEST_NAME)
    except Exception as e:                # noqa: BLE001
        log.info("nightly: report filed, digest not rewritten (%s)", e)
    return item


# ---------------------------------------------------------------------------
# the card
# ---------------------------------------------------------------------------

def default_line(seconds: float) -> str:
    """The sentence under the buttons. Whole minutes, because "runs in
    287 seconds" is a countdown and this is a promise."""
    mins = max(1, int(round(float(seconds) / 60.0)))
    return CARD_DEFAULT.format(mins=mins,
                               s="" if mins == 1 else "s")


def ask_on_screen(seconds: float = ASK_SECONDS, *, app_dir=None) -> bool:
    """Put the card up and answer the question. True means run.

    IT RETURNS ONLY AFTER THE WINDOW IS GONE. He asked for that
    specifically -- no leftover card sitting there while the suite moves
    the real mouse -- so the window is destroyed before the answer is
    handed back, and `run()` calls this strictly before it starts
    anything.

    A machine that cannot open a window at all answers True: no card is
    no answer, and no answer means run.
    """
    try:
        import tkinter as tk

        import ui
    except Exception as e:                # noqa: BLE001
        log.info("nightly: no card (%s) — running, which is the default", e)
        return True
    answer = [True]                       # no answer means run
    try:
        root = tk.Tk()
    except Exception as e:                # noqa: BLE001
        log.info("nightly: no screen for the card (%s) — running", e)
        return True
    try:
        root.title("DeskIT — nightly tests")
        root.configure(bg=ui.BG)
        root.resizable(False, False)
        w, h = 460, 224
        try:
            x = (root.winfo_screenwidth() - w) // 2
            y = (root.winfo_screenheight() - h) // 3
            root.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:                 # noqa: BLE001
            root.geometry(f"{w}x{h}")
        # It is above whatever is in front, because at three in the
        # morning nothing else is asking him anything -- but it does NOT
        # take the keyboard focus away, and it does not wake the screens.
        try:
            root.attributes("-topmost", True)
        except Exception:                 # noqa: BLE001
            pass

        def close(run_it: bool) -> None:
            answer[0] = bool(run_it)
            try:
                root.quit()
            except Exception:             # noqa: BLE001
                pass

        tk.Label(root, text=CARD_TITLE, bg=ui.BG, fg=ui.FG,
                 font=(ui.DISPLAY, 15, "bold"), anchor="w",
                 justify="left").place(x=24, y=26)
        tk.Label(root, text=CARD_BODY, bg=ui.BG, fg=ui.DIM,
                 font=(ui.UI, 10), anchor="w", justify="left",
                 wraplength=w - 48).place(x=24, y=60)
        tk.Label(root, text=default_line(seconds), bg=ui.BG, fg=ui.FAINT,
                 font=(ui.UI, 9), anchor="w",
                 justify="left").place(x=24, y=h - 40)
        ui.Button(root, CARD_YES, lambda: close(True), w=150, h=34,
                  bg=ui.BG, primary=True).place(x=24, y=h - 96)
        ui.Button(root, CARD_NO, lambda: close(False), w=150, h=34,
                  bg=ui.BG, quiet=True).place(x=186, y=h - 96)
        # THE X IS NOT A NO. Closing the card is "go away", not "do not
        # run tonight" — and the one thing this card must never do is
        # turn a shrug into a skipped night. Only the button that says
        # No is a no.
        root.protocol("WM_DELETE_WINDOW", lambda: close(True))
        # The clock. Closing the card by running out of time is the same
        # code path as pressing Yes, which is the point: the default is
        # not a special case.
        root.after(max(1, int(float(seconds) * 1000)), lambda: close(True))
        root.mainloop()
    except Exception as e:                # noqa: BLE001
        log.info("nightly: the card fell over (%s) — running", e)
        answer[0] = True
    finally:
        try:
            root.destroy()
        except Exception:                 # noqa: BLE001
            pass
    return bool(answer[0])


# ---------------------------------------------------------------------------
# running the suite
# ---------------------------------------------------------------------------

def _python(app_dir) -> str:
    """The repo's own interpreter, never a system python. sys.executable
    when this module was started by it, which is the normal case."""
    here = Path(app_dir) / ".venv" / "Scripts" / "python.exe"
    if here.exists():
        return str(here)
    return sys.executable


def _kill(proc) -> None:
    """The whole tree, not just the parent. tests_quiet starts its half
    of the suite through CreateProcessW on a desktop of its own, so
    terminating the process we launched would leave that child running
    the tests with nobody watching it."""
    try:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW",
                                             0))
    except Exception:                     # noqa: BLE001
        pass
    try:
        proc.kill()
    except Exception:                     # noqa: BLE001
        pass


def run_suite(app_dir, transcript: Path, *, poll: float = 1.0) -> tuple:
    """The whole suite, the sixteen included. (exit code, was it stopped).

    `tests_quiet.py` WITHOUT --no-screen, which is the whole point of the
    hour: it runs everything it can on the hidden desktop and the sixteen
    that need the real screen and the real mouse in the open, at the end,
    for about fifteen seconds. NOT plain `tests.py`, which would put the
    whole suite's windows on his screen for minutes instead of fifteen
    seconds -- house rule 8 is still the rule at three in the morning,
    and the sixteen are the only part of it that has to be broken.

    The stop file is watched once a second while it runs. That is the
    dashboard's button; see the contract at the top.
    """
    app_dir = Path(app_dir)
    clear_stop(app_dir)
    stopped = False
    try:
        handle = open(transcript, "w", encoding="utf-8", errors="replace")
    except OSError as e:                  # noqa: BLE001
        note(app_dir, f"could not open the transcript {transcript} ({e})")
        return -1, False
    try:
        proc = subprocess.Popen(
            [_python(app_dir), "tests_quiet.py"], cwd=str(app_dir),
            stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:                # noqa: BLE001
        handle.close()
        note(app_dir, f"could not start the suite ({e})")
        return -1, False
    try:
        while proc.poll() is None:
            if stop_asked(app_dir):
                stopped = True
                note(app_dir, "Stop was pressed — ending the run")
                _kill(proc)
                break
            time.sleep(poll)
        proc.wait(timeout=30)
    except Exception as e:                # noqa: BLE001
        note(app_dir, f"the run came apart ({e})")
    finally:
        try:
            handle.close()
        except OSError:
            pass
        clear_stop(app_dir)
    return int(proc.returncode if proc.returncode is not None else -1), stopped


def _trim_transcripts(app_dir) -> None:
    try:
        kept = sorted(folder(app_dir).glob("*-tests.txt"))
        for old in kept[:-KEEP_TRANSCRIPTS]:
            try:
                os.remove(old)
            except OSError:
                pass
    except OSError:
        pass


def _wanted(app_dir) -> tuple:
    """(is the nightly run on, how long the card waits), read out of
    config.toml and never allowed to fail. A config that will not load is
    the shipped answer -- on, five minutes -- because the night this file
    cannot read a setting is not the night to stop testing."""
    try:
        import config
        cfg = config.load(Path(app_dir) / "defaults.toml")
        return bool(cfg.tests.nightly), float(cfg.tests.wait_seconds), cfg
    except Exception as e:                # noqa: BLE001
        log.info("nightly: could not read [tests] (%s) — using the "
                 "shipped answer", e)
        return True, ASK_SECONDS, None


def total_tests(app_dir) -> int | None:
    """How many tests the suite has, for the one line of the report that
    says "3 of 711". None when it cannot be counted, and then the report
    simply does not say it."""
    try:
        text = (Path(app_dir) / "tests.py").read_text("utf-8",
                                                      errors="replace")
        return len(re.findall(r"^def (test_\w+)", text, re.M))
    except OSError:
        return None


def run(app_dir, *, ask=None, launch=None, cfg=None, enabled=None,
        wait=None) -> dict:
    """One night, start to finish. The dict is what happened, and it is
    what the tests read.

    `ask` and `launch` are here so every decision in this function can be
    tested without a screen and without waiting three hundred seconds:
    the ORDER (ask, then run, and never the other way round), the
    default, the refusal, the flake, the stop, the overlap. The clock is
    not the thing worth testing; the decisions are.
    """
    app_dir = Path(app_dir)
    if enabled is None or wait is None:
        on, seconds, loaded = _wanted(app_dir)
        enabled = on if enabled is None else enabled
        wait = seconds if wait is None else wait
        cfg = cfg if cfg is not None else loaded
    if not enabled:
        note(app_dir, "[tests] nightly is off — nothing ran")
        return {"result": OFF, "failed": [], "real": [], "report": None}
    with hold(app_dir) as mine:
        if not mine:
            note(app_dir, "another run holds the lock — nothing to do")
            return {"result": BUSY, "failed": [], "real": [], "report": None}
        ask = ask or ask_on_screen
        # THE CARD IS ANSWERED AND GONE BEFORE ANYTHING STARTS. Both
        # halves matter: `ask` returns only after its window is
        # destroyed, and the marker below -- the thing the dashboard's
        # Stop button hangs off -- is written after it, so the button and
        # the card can never be on screen together.
        note(app_dir, f"asking (it runs by itself in {wait:.0f}s)")
        try:
            go = bool(ask(wait))
        except Exception as e:            # noqa: BLE001
            note(app_dir, f"the card failed ({e}) — running, which is the "
                          f"default")
            go = True
        if not go:
            note(app_dir, "he said no — nothing ran, and nothing was filed")
            return {"result": SKIPPED, "failed": [], "real": [],
                    "report": None}

        stamp = time.strftime(_STAMP)
        transcript = folder(app_dir) / f"{stamp}-tests.txt"
        started = time.time()
        mark_running(app_dir, started)
        note(app_dir, "running the whole suite, the sixteen included")
        launch = launch or run_suite
        try:
            code, stopped = launch(app_dir, transcript)
        except Exception as e:            # noqa: BLE001
            # A run that could not even be started is a real failure with
            # no test name on it, and it goes down the same road: the
            # verdict below reads code -1 with no verdict printed, and he
            # gets one report saying the suite did not finish.
            note(app_dir, f"the run came apart before it could finish ({e})")
            code, stopped = -1, False
        finally:
            # THE MARKER GOES WHATEVER HAPPENED. It is what puts Stop in
            # his bar, and a button for a run that is over is worse than
            # no button at all.
            clear_running(app_dir)
        seconds = time.time() - started
        try:
            text = transcript.read_text("utf-8", errors="replace")
        except OSError:
            text = ""
        got = verdict(transcript=text, code=code, stopped=stopped)
        got["seconds"] = seconds
        got["transcript"] = str(transcript)

        if got["result"] == STOPPED:
            note(app_dir, f"STOPPED after {seconds:.0f}s — not a failure, "
                          f"and nothing was filed")
        elif got["result"] == CLEAN:
            note(app_dir, f"clean in {seconds:.0f}s — nothing filed, which "
                          f"is the point")
        elif got["result"] == FLAKY:
            note(app_dir,
                 f"failed in {seconds:.0f}s, and every failure is a known "
                 f"flake, so no report was filed: "
                 f"{', '.join(got['failed'])}")
        else:
            note(app_dir, f"FAILED in {seconds:.0f}s: "
                          f"{', '.join(got['real']) or f'exit {code}'}")

        item = file_report(app_dir, got, cfg=cfg,
                           transcript_path=_relative(app_dir, transcript),
                           seconds=seconds, total=total_tests(app_dir))
        got["report"] = item.get("id") if item else None
        if item:
            note(app_dir, f"filed report {item.get('id')} — it will be on "
                          f"the Problems place, and Saturday will read it")
        _trim_transcripts(app_dir)
        return got


def _relative(app_dir, path: Path) -> str:
    """How the report writes a path down: relative to the repo root, the
    way problems.py writes `problems/<id>.jpg`, so it survives the app
    being moved."""
    try:
        return str(Path(path).relative_to(Path(app_dir))).replace("\\", "/")
    except ValueError:
        return str(path)


def main(argv=None) -> int:
    """The scheduled task's entry point, through nightly_tests.ps1.

    Exit 0 whatever happened, for weekly_review.ps1's reason: Task
    Scheduler's history stays clean and he learns about a bad night from
    the Problems place rather than from a red icon in a window he never
    opens.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--now", action="store_true",
                        help="skip the question and run the suite")
    parser.add_argument("--wait", type=float, default=None,
                        help="seconds the card waits (default: the setting)")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                     # noqa: BLE001 — not a console
        pass
    app_dir = Path(__file__).resolve().parent
    try:
        got = run(app_dir, wait=args.wait,
                  ask=(lambda _s: True) if args.now else None)
    except Exception as e:                # noqa: BLE001
        # Nothing above here is allowed to end the night with a traceback
        # on a console nobody is looking at. It goes in the log, which is
        # the one place a bad night is meant to be read from.
        note(app_dir, f"the nightly run threw ({type(e).__name__}: {e})")
        got = {"result": FAILED, "failed": [], "real": [], "report": None}
    print(json.dumps({k: v for k, v in got.items() if k != "seconds"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
