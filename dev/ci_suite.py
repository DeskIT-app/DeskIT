"""The product suite as the CI runs it: one full run, then ONE second try,
in a fresh process, for what failed.

    python dev/ci_suite.py [--script tests.py]

Why (counted 2026-09-23 over the last 100 runs of the tests workflow): 14
failed, and nearly every one on a DIFFERENT test - a frame budget of an
animation (101 ms on the runner), a notification reminder read before it
was written, the live channel "within the second", the screens-off timer,
a thread waited for 2 s. Each was fixed where it failed and the next run
failed somewhere else, because the cause is the shared hosted VM, not one
test: every test that waits on time can lose that race there. Each red run
was an e-mail to the owner, who read "fixed" after every one of them.

So the class is handled here, the way large suites handle it (a flaky test
is retried in isolation and REPORTED, never silently passed): a test that
fails and then passes on its second try in a fresh process is a timing
failure of the runner, and it becomes a visible warning on the run
("Flaky on the CI runner"), not a failure. A real regression fails both
times and the run stays red. More than MAX_RETRY failures at once is a
real break, and no second try is made. A suite process that dies before
its verdict line (the Tcl_AsyncDelete abort) gets one more full run. The
owner's nightly run on his own machine (tests_quiet.py) has no second try:
there a flaky test still files its report.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_RETRY = 5
ALL_PASSED = "all tests passed"
PASS = re.compile(r"^  PASS  (\S+)", re.M)
FAILED = re.compile(r"^(\d+) FAILED: (.+)$")


def run(cmd: list[str]) -> tuple[str, int]:
    """Run, echoing every line to this log as it comes; the text and code."""
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    lines = []
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        lines.append(line)
    return "".join(lines), proc.wait()


def verdict(text: str) -> tuple[str, list[str]]:
    """("passed", []), ("failed", names) or ("died", []) - read off the
    suite's LAST line, which is the only one a finished run always writes."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    last = lines[-1] if lines else ""
    if last == ALL_PASSED:
        return "passed", []
    found = FAILED.match(last)
    if found:
        return "failed", [n.strip() for n in found.group(2).split(",") if n.strip()]
    return "died", []


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", default="tests.py")
    args = parser.parse_args(argv)
    base = [sys.executable, "-u", args.script, "--no-screen"]

    text, code = run(base)
    kind, names = verdict(text)
    if kind == "passed" and code == 0:
        return 0

    if kind == "failed":
        if len(names) > MAX_RETRY:
            print(f"::error title=Suite failed::{len(names)} tests failed at "
                  f"once - a real break, not the runner; no second try")
            return 1
        print(f"\n---- a second try, in a fresh process, for the {len(names)} "
              f"test(s) that failed ----", flush=True)
        again, _code = run(base + names)
        passed = set(PASS.findall(again))
        twice = [n for n in names if n not in passed]
        for name in names:
            if name not in twice:
                print(f"::warning title=Flaky on the CI runner::{name} failed, "
                      f"then passed on a second try in a fresh process")
        if twice:
            print(f"::error title=Failed twice::{', '.join(twice)}")
            return 1
        return 0

    print("\n---- the suite process died before its verdict; one more full "
          "run ----", flush=True)
    again, code = run(base)
    kind, names = verdict(again)
    if kind == "passed" and code == 0:
        print("::warning title=Suite died once on the CI runner::the first "
              "full run stopped before its verdict; the second passed")
        return 0
    print(f"::error title=Suite failed::the second full run ended "
          f"'{kind}' {', '.join(names)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
