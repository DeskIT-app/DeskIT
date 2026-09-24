"""The owner's half of the suite: the nightly run, the git card, the
routine's documentation. Run in the checkout only:

    .venv\\Scripts\\python.exe dev\\tests_ops.py            # all of them
    .venv\\Scripts\\python.exe dev\\tests_ops.py nightly    # a pick, as tests.py

These left tests.py in PR 8 (DISTRIBUTION_PLAN.md 7.5, D15): each one
imports nightly, drives the Push/Undo card, or reads a file the product
build never ships — AGENTS.md, nightly_tests.ps1, install_nightly_task.ps1.
Nothing about them changed on the way; the fixtures they use — check(),
_window(), the scratch-home guard at the top of tests.py —
are tests.py's own, imported below, so the two files cannot drift apart.
tests_quiet.py runs this file after tests.py on the hidden desktop; the
product CI never sees it.
"""
from __future__ import annotations

import gc
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "dev"))

import paths  # noqa: E402

import tests as _tests  # noqa: E402  (the fixtures, and the scratch home)
from tests import (  # noqa: E402
    BAR_OFF,
    BAR_ON,
    BAR_PAUSED,
    BAR_STARTING,
    _window,
    check,
    config_mod,
)


class _FakeGit:
    """A stand-in for dashboard._git: answers each command from a table
    keyed on its first words and writes down every call, so a test can
    say both what a button said and — the part that matters more — which
    git commands it ran, in which order, and which it never ran."""

    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args, cwd=None, timeout=None):
        self.calls.append(tuple(args))
        for length in range(len(args), 0, -1):
            if args[:length] in self.answers:
                answer = self.answers[args[:length]]
                return answer if isinstance(answer, tuple) else (0, answer, "")
        return 1, "", f"fake git has no answer for {' '.join(args)}"

    def ran(self, *words: str) -> list[tuple[str, ...]]:
        return [c for c in self.calls if c[:len(words)] == words]


def _with_fake_git(answers: dict):
    """dashboard._git swapped for a _FakeGit and given back."""
    import dashboard as dash

    fake = _FakeGit(answers)
    real = dash._git
    dash._git = fake

    def restore() -> None:
        dash._git = real
    return fake, restore


def test_real_key_is_discoverable() -> None:
    """The owner's own cloud key is where the app looks for it. This left
    tests.py on 2026-09-18, the day the product CI first ran: a hosted
    runner holds no key, and neither does a stranger's copy that dictates
    locally — the product suite must not demand one. The lookup itself
    is tested with fixture keys in tests.py; this is the one place that
    asks about the REAL key, and it runs in this checkout alone."""
    import apikey

    key, source = apikey.find_api_key()
    assert key, f"no API key found (source={source})"
    assert len(key) > 20, "key looks truncated"


def test_the_changes_card_lists_what_is_ahead_newest_first_and_hides_when_nothing_is(
) -> None:
    """What replaced the weekly branches on 2026-09-12: every change is
    committed onto `main` in this folder and never pushed by whoever
    made it, so the tab shows what is here and not on GitHub — one card,
    the commits newest first with their dates, the files, and three
    buttons, Restart, Push and Undo.

    And when nothing is ahead there is NO card: the block is one faint
    line, keeping only Restart, because "nothing ahead" is also what the
    folder looks like right after Claude brought GitHub's newer changes
    in — and those want a restart to be run. His words on 2026-09-08
    about the finished weeks: "if it stays here after five weeks, there
    will be a lot and it is not convenient".

    Drawn for real, offscreen, so the card's geometry is exercised: the
    three buttons are on the card, in a row at its top right, and the
    status sentence stops short of them.
    """
    import tkinter as tk

    import ui as ui_mod

    import dashboard as dash

    def canvases(board):
        """Every canvas on the list, in the order they were packed."""
        found = []
        stack = list(reversed(board.parts["problems_list"]
                              .inner.winfo_children()))
        while stack:
            widget = stack.pop()
            if isinstance(widget, tk.Canvas) and not isinstance(
                    widget, ui_mod.Button):
                found.append(widget)
            stack.extend(reversed(widget.winfo_children()))
        return found

    def texts(canvas) -> list[str]:
        return [canvas.itemcget(i, "text") for i in canvas.find_all()
                if canvas.type(i) == "text"]

    def buttons(canvas) -> dict:
        return {w.itemcget(w._label, "text"): w
                for w in canvas.winfo_children()
                if isinstance(w, ui_mod.Button)}

    with _window() as board:
        if board is None:
            return
        board.closing = True
        board._scan_changes = lambda: None      # git is not the subject
        board._write_digest = lambda: None      # nor is his problems.md
        board._show("Problems")
        board._changes = {
            "told": True, "behind": 2,
            "commits": [
                {"sha": "aaaaaaa", "when": "2026-09-12 10:30",
                 "subject": "The newest one"},
                {"sha": "bbbbbbb", "when": "2026-09-11 22:05",
                 "subject": "The one before it"},
                {"sha": "ccccccc", "when": "2026-09-11 09:00",
                 "subject": "The oldest one"},
            ],
            "files": ["dashboard.py", "tests.py"],
        }
        board._push_said[dash.TRUNK] = "The last press said this."
        board._fill_problems()
        board.root.update()
        cards = [c for c in canvases(board)
                 if "Changes on this computer" in texts(c)]
        assert len(cards) == 1, "no card for the changes, or two"
        card = cards[0]
        # A wrapped sentence is one text item with newlines in it, and a
        # break may fall anywhere in it: flattened before it is read.
        words = [" ".join(w.split()) for w in texts(card)]
        order = [words.index(s) for s in ("The newest one",
                                          "The one before it",
                                          "The oldest one")]
        assert order == sorted(order), "the commits are not newest first"
        assert "2026-09-12 10:30" in words, "a commit without its date"
        assert any("3 changes exist only on this computer" in w
                   for w in words), words
        assert any("Restart to try them, then Push" in w for w in words)
        assert any("GitHub also has 2 newer changes" in w for w in words), \
            "behind is not said"
        assert any("dashboard.py" in w and "tests.py" in w for w in words), \
            "the file list is missing"
        assert card.keep[0] is not None, "the last sentence is not drawn"
        pressable = buttons(card)
        assert set(pressable) == {"Restart", "Push", "Undo"}, set(pressable)
        assert pressable["Push"]._primary and not pressable["Undo"]._primary
        assert all(b._enabled for b in pressable.values())
        # Geometry: all three sit at the top right of the card, in a row,
        # and the status line does not run under them.
        windows = {card.itemcget(i, "window"): card.bbox(i)
                   for i in card.find_all() if card.type(i) == "window"}
        boxes = {name: windows[str(b)] for name, b in pressable.items()}
        assert all(box[1] == 13 for box in boxes.values()), boxes
        assert boxes["Restart"][2] <= boxes["Push"][0] <= boxes["Undo"][0]
        assert boxes["Undo"][2] <= dash.CW - dash.Q_PAD
        status = next(i for i in card.find_all() if card.type(i) == "text"
                      and "exist only on this computer"
                      in card.itemcget(i, "text"))
        assert card.bbox(status)[2] <= boxes["Restart"][0], \
            "the status sentence runs under the buttons"
        assert card.bbox("all")[3] <= int(card.cget("height")), \
            "the card is shorter than what is drawn on it"

        # More than eight: the ninth and after fold into "+N more".
        board._changes["commits"] = [
            {"sha": f"{n:07d}", "when": "2026-09-12 10:00",
             "subject": f"change number {n}"} for n in range(11)]
        board._fill_problems()
        board.root.update()
        card = next(c for c in canvases(board)
                    if "Changes on this computer" in texts(c))
        words = [" ".join(w.split()) for w in texts(card)]
        assert "+3 more" in words, words
        assert not any("change number 8" in w for w in words), \
            "the ninth commit is listed as well as folded"

        # While a button is in flight all three are flat.
        board._pushing = "push"
        board._fill_problems()
        board.root.update()
        card = next(c for c in canvases(board)
                    if "Changes on this computer" in texts(c))
        assert not any(b._enabled for b in buttons(card).values()), \
            "a press while one is running would race it"
        board._pushing = None

        # Nothing ahead: no card, one faint line, Restart kept, and the
        # last sentence still under it.
        board._changes = {"told": True, "behind": 1, "commits": [],
                          "files": []}
        board._fill_problems()
        board.root.update()
        every = canvases(board)
        assert not any("Changes on this computer" in texts(c)
                       for c in every), "a card with nothing on it"
        lines = [c for c in every
                 if any(w.startswith("Everything on this computer is on "
                                     "GitHub.") for w in texts(c))]
        assert len(lines) == 1, "no line saying nothing is ahead"
        assert any("GitHub also has 1 newer change " in w
                   for w in texts(lines[0])), texts(lines[0])
        assert set(buttons(lines[0])) == {"Restart"}, buttons(lines[0])
        assert lines[0].keep[0] is not None, "the last sentence went"

        # And when git could not answer at all, nothing is drawn — not
        # a card, not a line, not an error.
        board._changes = {"told": False, "behind": 0, "commits": [],
                          "files": []}
        board._fill_problems()
        board.root.update()
        assert not any("GitHub" in w for c in canvases(board)
                       for w in texts(c)), "a block for a folder with no git"


def test_local_changes_is_a_local_read_and_says_nothing_when_git_cannot(
) -> None:
    """The card is asked for on every paint of the tab, so it must never
    touch the network: no fetch, only `origin/main..main` as last
    fetched. And a folder with no git, no repo or no origin/main is an
    empty answer with told=False — a block that is not drawn, never an
    error."""
    import dashboard as dash

    fake, restore = _with_fake_git({
        ("log",): "aaaaaaa1234\t2026-09-12 10:30\tThe newest one\n"
                  "bbbbbbb5678\t2026-09-11 22:05\tThe one before it\n",
        ("diff", "--name-only"): "dashboard.py\ntests.py\n",
        ("rev-list", "--count", "main..origin/main"): "2\n",
    })
    try:
        info = dash.local_changes()
    finally:
        restore()
    assert info["told"] is True
    assert [c["sha"] for c in info["commits"]] == ["aaaaaaa", "bbbbbbb"]
    assert info["commits"][0] == {"sha": "aaaaaaa", "when": "2026-09-12 10:30",
                                  "subject": "The newest one"}
    assert info["files"] == ["dashboard.py", "tests.py"]
    assert info["behind"] == 2
    assert not fake.ran("fetch"), "a fetch on every paint of the tab"
    assert not fake.ran("push") and not fake.ran("reset")
    log = fake.ran("log")[0]
    assert log[-1] == "origin/main..main", log

    fake, restore = _with_fake_git({("log",): (128, "", "fatal: bad rev")})
    try:
        info = dash.local_changes()
    finally:
        restore()
    assert info == {"commits": [], "files": [], "behind": 0, "told": False}


def test_push_fetches_checks_the_ancestry_and_only_then_pushes_main() -> None:
    """The order IS the safety: fetch, so the check is about GitHub now;
    is origin/main an ancestor of main, because if not a plain push
    would be refused and the only ways past are a merge or --force,
    neither a button's; then `git push origin main` with no flags and
    nothing else. The old guard refused whenever `main` held a commit
    GitHub lacked, on the premise that the routine never commits to
    `main` — and the moment a session moved the work onto `main` so he
    could TRY it, that guard refused the very work he was trying to
    push (2026-09-12). Here a commit GitHub lacks IS the work."""
    import dashboard as dash

    fake, restore = _with_fake_git({
        ("fetch",): "", ("merge-base", "--is-ancestor"): "",
        ("push", "origin", "main"): "",
    })
    try:
        result = dash.push_main()
    finally:
        restore()
    assert result["pushed"] is True
    assert result["said"] == "Sent. GitHub now has everything on this " \
                             "computer.", result["said"]
    assert fake.calls == [("fetch", "origin", "main"),
                          ("merge-base", "--is-ancestor", "origin/main",
                           "main"),
                          ("push", "origin", "main")], fake.calls
    assert not any("--force" in c or "-f" in c for c in fake.calls)

    # GitHub has moved on: refused, and push is never run.
    fake, restore = _with_fake_git({
        ("fetch",): "", ("merge-base", "--is-ancestor"): (1, "", ""),
        ("push",): "",
    })
    try:
        result = dash.push_main()
    finally:
        restore()
    assert result["pushed"] is False
    assert result["said"] == ("GitHub has changes this computer does not "
                              "have yet. Ask Claude to bring them in first, "
                              "then press Push again. Nothing changed."), \
        result["said"]
    assert not fake.ran("push"), "it pushed over GitHub's newer commit"
    assert not fake.ran("merge") and not fake.ran("pull")

    # No network: one sentence, and nothing after the fetch.
    fake, restore = _with_fake_git({("fetch",): (128, "", "fatal: unable")})
    try:
        result = dash.push_main()
    finally:
        restore()
    assert result["said"] == ("GitHub could not be reached. Nothing changed. "
                              "Try again in a moment."), result["said"]
    assert fake.calls == [("fetch", "origin", "main")], fake.calls

    # GitHub said no: its first line is quoted back.
    fake, restore = _with_fake_git({
        ("fetch",): "", ("merge-base", "--is-ancestor"): "",
        ("push",): (1, "", "error: failed to push some refs\nhint: ..."),
    })
    try:
        result = dash.push_main()
    finally:
        restore()
    assert result["pushed"] is False
    assert result["said"] == ("GitHub did not take the changes (error: failed "
                              "to push some refs). Nothing changed. Press "
                              "Push again."), result["said"]


def test_undo_resets_with_keep_only_when_something_is_ahead_and_names_the_file_git_refuses(
) -> None:
    """Undo is `git reset --keep origin/main` — --keep and never --hard,
    because config.toml is his and is modified most of the time, and
    --hard would throw his edit away with the commits. --keep carries
    it across, and REFUSES when a file with uncommitted edits is one
    the undone commits changed; that refusal has to reach him with the
    file's name in it, in git's own words ("Entry 'config.toml' not
    uptodate", measured 2026-09-12), and with "Nothing changed".

    And nothing ahead is nothing to undo — said, not reset."""
    import dashboard as dash

    fake, restore = _with_fake_git({
        ("fetch",): "", ("rev-list", "--count", "origin/main..main"): "2\n",
        ("rev-parse", "--abbrev-ref", "HEAD"): "main\n",
        ("reset", "--keep", "origin/main"): "",
    })
    try:
        result = dash.undo_main()
    finally:
        restore()
    assert result["undone"] is True
    assert result["said"] == ("Undone. The changes are gone from this "
                              "computer (GitHub never had them). Restart to "
                              "run the older version again."), result["said"]
    assert fake.calls[0] == ("fetch", "origin", "main")
    assert fake.ran("reset") == [("reset", "--keep", "origin/main")], \
        fake.calls
    assert not any("--hard" in c for c in fake.calls), "--hard eats his edits"
    assert not fake.ran("checkout") and not fake.ran("clean")

    # Nothing ahead: no reset at all.
    fake, restore = _with_fake_git({
        ("fetch",): "", ("rev-list", "--count", "origin/main..main"): "0\n",
        ("reset",): "",
    })
    try:
        result = dash.undo_main()
    finally:
        restore()
    assert result["undone"] is False
    assert result["said"] == ("Nothing to undo — everything on this "
                              "computer is already on GitHub."), result["said"]
    assert not fake.ran("reset"), "a reset with nothing to undo"

    # git refused --keep: the file it named, and nothing changed.
    fake, restore = _with_fake_git({
        ("fetch",): "", ("rev-list", "--count", "origin/main..main"): "1\n",
        ("rev-parse", "--abbrev-ref", "HEAD"): "main\n",
        ("reset", "--keep", "origin/main"): (
            128, "", "error: Entry 'config.toml' not uptodate. Cannot "
                     "merge.\nfatal: Could not reset index file to revision "
                     "'origin/main'.\n"),
    })
    try:
        result = dash.undo_main()
    finally:
        restore()
    assert result["undone"] is False
    assert result["said"] == ("Undo refused: config.toml has unsaved edits "
                              "and one of these changes touched it. Nothing "
                              "changed. Ask Claude."), result["said"]

    # The folder standing on a branch that is not main: reset would move
    # THAT branch, so it is refused before it is run.
    fake, restore = _with_fake_git({
        ("fetch",): "", ("rev-list", "--count", "origin/main..main"): "1\n",
        ("rev-parse", "--abbrev-ref", "HEAD"): "fix-something\n",
        ("reset",): "",
    })
    try:
        result = dash.undo_main()
    finally:
        restore()
    assert result["undone"] is False
    assert "standing on fix-something, not main" in result["said"], \
        result["said"]
    assert not fake.ran("reset")

    # No network: the same sentence Push gives, and nothing after.
    fake, restore = _with_fake_git({("fetch",): (128, "", "fatal: unable")})
    try:
        result = dash.undo_main()
    finally:
        restore()
    assert result["said"] == ("GitHub could not be reached. Nothing changed. "
                              "Try again in a moment."), result["said"]
    assert fake.calls == [("fetch", "origin", "main")], fake.calls


def test_a_press_on_push_or_undo_runs_off_the_tk_thread_and_asks_git_again_after(
) -> None:
    """The two git buttons share one path: the card says it is going,
    every button is flat until the answer is back, the answer becomes
    the card's amber sentence, and the facts are asked for again rather
    than patched — a push moved them to GitHub, an undo took them off
    this folder."""
    import dashboard as dash

    with _window() as board:
        if board is None:
            return
        # Not closing=True here: the answer comes back on the pump, and
        # a closing window pumps once and stops.
        asked: list[str] = []
        board._scan_changes = lambda: asked.append("scan")
        board._write_digest = lambda: None
        board._show("Problems")
        asked.clear()
        real = (dash.push_main, dash.undo_main)
        threads: list[str] = []
        try:
            dash.push_main = lambda: (threads.append(
                threading.current_thread().name),
                {"pushed": True, "said": "Sent, in the test."})[1]
            board._push_main()
            assert board._pushing == "push"
            assert board._push_said[dash.TRUNK].startswith("Pushing…")
            board._undo_main()                  # a second press: ignored
            for _ in range(60):
                board.root.update()
                if board._pushing is None:
                    break
                time.sleep(0.02)
            assert board._pushing is None
            assert threads == ["changes-push"], threads
            assert board._push_said[dash.TRUNK] == "Sent, in the test."
            assert asked == ["scan"], asked

            dash.undo_main = lambda: {"undone": True, "said": "Undone, in "
                                                              "the test."}
            board._undo_main()
            assert board._pushing == "undo"
            for _ in range(60):
                board.root.update()
                if board._pushing is None:
                    break
                time.sleep(0.02)
            assert board._push_said[dash.TRUNK] == "Undone, in the test."
            assert asked == ["scan", "scan"], asked
        finally:
            dash.push_main, dash.undo_main = real


def test_the_readme_and_agents_document_notify():
    """The README section sits between Awake and the phone, every [notify]
    key has a Config reference row, and AGENTS.md's map names the three
    new files plus the two doors it never listed."""
    readme = (REPO / "dev" / "README-dev.md").read_text(encoding="utf-8")
    heading = "## Notify — when Claude (or anything) finishes (`ctrl+alt+m`)"
    assert heading in readme
    i = readme.index(heading)
    assert readme.index("## Awake, and the screens off") < i
    assert i < readme.index("## Dictating from the phone")
    table = readme[readme.index("## Config reference"):]
    for key in ("enabled", "cue", "card_seconds", "stack_max",
                "remind_every_s", "remind_times", "coalesce_s", "watch",
                "corner", "anchor", "x", "y", "scale", "dismiss_hotkey"):
        assert f"| `[notify] {key}` |" in table, key
    assert "--install-hook" in readme
    assert "irm 'http://127.0.0.1:8756/notify'" in readme
    # And the one thing the README must say out loud, because it is the
    # question anybody reading it will ask next: Chat is not in this.
    assert "Cowork" in readme and "Chat" in readme
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    what = agents[agents.index("## What this is"):agents.index("## House rules")]
    assert "notify" in what
    where = agents[agents.index("## Where things live"):]
    for name in ("notify.py", "notify_card.py", "notify_hook.py",
                 "notify_watch.py", "server.py", "control.py"):
        assert f"| `{name}` |" in where, name


def test_the_readme_and_agents_document_problems() -> None:
    """A feature nobody can find is a feature nobody uses: the README has
    a section of its own for the bug list, every [problems] key has a
    Config reference row, and AGENTS.md names problems.py on its map and
    the feature in what this program is."""
    readme = (REPO / "dev" / "README-dev.md").read_text(encoding="utf-8")
    heads = [ln for ln in readme.splitlines() if ln.startswith("## ")]
    assert any("problem" in h.lower() for h in heads), \
        "no README section for reporting a problem"
    table = readme[readme.index("## Config reference"):]
    for key in ("enabled", "report_hotkey", "shot", "keep_audio",
                "keep_resolved"):
        assert f"| `[problems] {key}` |" in table, key
    assert "problems.md" in readme, "the weekly read is never named"
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    what = agents[agents.index("## What this is"):
                  agents.index("## House rules")]
    assert "problem" in what.lower(), \
        "'What this is' does not mention the bug list"
    where = agents[agents.index("## Where things live"):]
    assert "| `problems.py` |" in where, "problems.py is not on the map"


# ---------------------------------------------------------------------------
# the nightly run of the whole suite (nightly.py)
#
# THE CLOCK IS NOT WHAT IS WORTH TESTING; THE DECISIONS ARE. Nothing below
# waits five minutes or looks at the time of day. What every one of these
# holds is a choice the owner made and would notice being reversed: that no
# answer means RUN, that "No" means skip, that the card is gone before the
# suite takes the mouse, that a clean night files nothing, that the machine's
# one known flake files nothing on its own and is still named out loud, that a
# real failure files exactly one report the Saturday routine can read, that a
# run he stopped is a stop and not a breakage, and that two runs can never
# overlap while a dead one blocks nothing.
# ---------------------------------------------------------------------------

CLEAN_RUN = ("running 711 tests\n  PASS  test_a\n\n"
             "all tests passed (quietly)\n")
FLAKE_RUN = ("running 711 tests\n"
             "  FAIL  test_the_process_list_sees_the_processes_it_cannot_open"
             ": per-process sum 235564 vs machine total 244414\n\n"
             "1 FAILED: "
             "test_the_process_list_sees_the_processes_it_cannot_open\n")
BROKEN_RUN = ("running 711 tests\n  FAIL  test_the_dot_stays_put: nope\n\n"
              "2 FAILED: test_the_dot_stays_put, "
              "test_the_process_list_sees_the_processes_it_cannot_open\n")


def _nightly_dir():
    """A repo-shaped temp folder with nothing in it but a problems store."""
    return Path(tempfile.mkdtemp(prefix="nightly-"))


def _fake_suite(text: str, code: int = 0, stopped: bool = False, seen=None):
    """A stand-in for run_suite: writes the transcript and says how it
    went, so a test can pose any night in a millisecond."""
    def launch(app_dir, transcript, **kw):
        if seen is not None:
            seen.append("ran")
        Path(transcript).write_text(text, "utf-8")
        return code, stopped
    return launch


def test_nobody_answering_the_nightly_card_means_the_tests_run() -> None:
    """THE DECISION THE WHOLE FEATURE TURNS ON. He rejected an idle check
    in these words: "מישהו יקום באמצע הלילה לשתות והבקבוק ייפול לי על
    המקלדת ואז היא תחשוב שאני כאן" — someone gets up in the night for a
    drink, the bottle lands on the keyboard, and the machine decides he
    is here. So the card runs by default, and a card that could not be
    drawn at all, or fell over while it was up, runs too: no answer is
    not a no.

    The real card is put up with a 50 ms clock rather than 300 s, because
    what is being tested is which way it falls, not how long it waits.
    """
    import shutil
    import tkinter as tk

    import nightly as nightly_mod

    tmp = _nightly_dir()
    try:
        # 1. the real thing, timing out.
        before = tk._default_root
        try:
            answer = nightly_mod.ask_on_screen(0.05)
        except Exception as e:                            # noqa: BLE001
            print(f"    (skipped the real card: no Tk — {e})")
        else:
            assert answer is True, "the card that ran out of time said no"
            # AND IT IS GONE. He asked for that specifically: no leftover
            # window while the suite is moving the real mouse.
            assert tk._default_root is before, \
                "the card left a Tk root behind it"

        # 2. a card that cannot be drawn, and a card that throws.
        seen: list = []
        got = nightly_mod.run(tmp, enabled=True, wait=1,
                              ask=lambda _s: (_ for _ in ()).throw(
                                  RuntimeError("no screen")),
                              launch=_fake_suite(CLEAN_RUN, seen=seen))
        assert seen == ["ran"], "a broken card stopped the run"
        assert got["result"] == nightly_mod.CLEAN, got
        log = (nightly_mod.folder(tmp) / nightly_mod.LOG_NAME).read_text(
            "utf-8")
        assert "which is the default" in log, log
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_saying_no_to_the_nightly_card_costs_the_night_and_nothing_else():
    """No is a real answer: nothing runs, nothing is filed, and the next
    night is untouched. It is also the ONLY thing that stops a run once
    the task has fired — which is why the card says so under the
    buttons."""
    import shutil

    import nightly as nightly_mod
    import problems as problems_mod

    tmp = _nightly_dir()
    try:
        seen: list = []
        got = nightly_mod.run(tmp, enabled=True, wait=1,
                              ask=lambda _s: False,
                              launch=_fake_suite(BROKEN_RUN, 1, seen=seen))
        assert got["result"] == nightly_mod.SKIPPED, got
        assert seen == [], "it ran the suite after he said no"
        assert got["report"] is None
        store = problems_mod.Store(tmp / problems_mod.STORE_NAME)
        assert store.items() == [], "a skipped night filed a report"
        assert nightly_mod.CARD_NO and nightly_mod.CARD_YES
        assert "runs anyway" in nightly_mod.default_line(300), \
            "the card does not say what happens if he walks away"
        assert nightly_mod.default_line(300).startswith("No answer in 5")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_nightly_card_is_gone_before_the_suite_takes_the_mouse() -> None:
    """His ask, and the two halves of keeping it.

    `ask` returns only once its window is destroyed (the test above holds
    that), and `run` writes the marker — the thing the dashboard's Stop
    button hangs off — only AFTER `ask` has returned. So the card and the
    button can never be on screen together, and no window is left over
    the suite while it is moving the real pointer.
    """
    import shutil

    import nightly as nightly_mod

    tmp = _nightly_dir()
    try:
        order: list = []

        def ask(_seconds):
            order.append("asked")
            # While he is being asked there is nothing to stop yet, so the
            # bar must not be offering to stop it.
            assert not nightly_mod.running(tmp), \
                "the Stop button was up while the card was still asking"
            return True

        def launch(app_dir, transcript, **kw):
            order.append("ran")
            assert nightly_mod.running(app_dir), \
                "the run is going and the bar has no Stop button"
            Path(transcript).write_text(CLEAN_RUN, "utf-8")
            return 0, False

        nightly_mod.run(tmp, enabled=True, wait=1, ask=ask, launch=launch)
        assert order == ["asked", "ran"], order
        assert not nightly_mod.running(tmp), \
            "the button outlived the run it belongs to"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_clean_night_files_nothing_at_all() -> None:
    """"A clean run files nothing. He should not wake up to a receipt."
    So: no report, no problems.md, nothing on the Problems place — and
    the run.log still says the night happened, because the log is the
    trace and the store is the news."""
    import shutil

    import nightly as nightly_mod
    import problems as problems_mod

    tmp = _nightly_dir()
    try:
        got = nightly_mod.run(tmp, enabled=True, wait=1,
                              ask=lambda _s: True,
                              launch=_fake_suite(CLEAN_RUN))
        assert got["result"] == nightly_mod.CLEAN, got
        assert got["report"] is None
        assert not (tmp / problems_mod.STORE_NAME).exists(), \
            "a clean night wrote to the bug list"
        assert not (tmp / problems_mod.DIGEST_NAME).exists()
        log = (nightly_mod.folder(tmp) / nightly_mod.LOG_NAME).read_text(
            "utf-8")
        assert "clean" in log and "nothing filed" in log, log
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_known_flake_alone_files_nothing_and_is_still_named() -> None:
    """A NAMED EXCEPTION, NOT A SILENT FILTER.

    test_the_process_list_sees_the_processes_it_cannot_open fails on
    nearly every run of this machine for a reason that is not the code's,
    and a false alarm every single morning is a report he stops reading.
    So a night whose ONLY failures are known flakes files nothing — and
    the run.log names every one of them anyway, because a filter nobody
    can see is a lie. Add a second, real failure and the report is filed
    after all.
    """
    import shutil

    import nightly as nightly_mod
    import problems as problems_mod

    flake = "test_the_process_list_sees_the_processes_it_cannot_open"
    assert flake in nightly_mod.KNOWN_FLAKES, \
        "the machine's one known flake is not written down"
    assert nightly_mod.KNOWN_FLAKES[flake], "a flake with no reason given"

    tmp = _nightly_dir()
    try:
        got = nightly_mod.run(tmp, enabled=True, wait=1,
                              ask=lambda _s: True,
                              launch=_fake_suite(FLAKE_RUN, 1))
        assert got["result"] == nightly_mod.FLAKY, got
        assert got["failed"] == [flake] and got["real"] == [], got
        assert got["report"] is None, "the known flake woke him up"
        store = problems_mod.Store(tmp / problems_mod.STORE_NAME)
        assert store.items() == []
        log = (nightly_mod.folder(tmp) / nightly_mod.LOG_NAME).read_text(
            "utf-8")
        assert flake in log, "the flake was hidden rather than excused"
        assert "known flake" in log, log
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_real_nightly_failure_files_one_report_saturday_can_read() -> None:
    """ONE report, in the shape .claude\\commands\\weekly-reports.md acts
    on: an OPEN item in problems.json with a kind out of problems.KINDS,
    a `where` saying which surface it came from, and a text that is
    evidence — which tests failed, the one command that re-runs one, and
    where the whole transcript is. That is his own idea: the nightly run
    files a report and the Saturday routine fixes it like any other
    problem, instead of a second pile nobody reads.

    The known flake rides along in the same run and must not be what the
    report is about."""
    import shutil

    import nightly as nightly_mod
    import problems as problems_mod

    tmp = _nightly_dir()
    try:
        got = nightly_mod.run(tmp, enabled=True, wait=1,
                              ask=lambda _s: True,
                              launch=_fake_suite(BROKEN_RUN, 1))
        assert got["result"] == nightly_mod.FAILED, got
        assert got["real"] == ["test_the_dot_stays_put"], got
        store = problems_mod.Store(tmp / problems_mod.STORE_NAME)
        open_items = store.items(problems_mod.OPEN)
        assert len(open_items) == 1, open_items
        item = open_items[0]
        assert item["id"] == got["report"]
        assert item["kind"] in problems_mod.KINDS and item["kind"] != "idea"
        assert item["where"] == nightly_mod.REPORT_WHERE
        assert item["by"] == nightly_mod.REPORT_BY
        assert item["status"] == problems_mod.OPEN, \
            "a report nobody has answered must stay open"
        text = item["text"]
        assert "test_the_dot_stays_put" in text, text
        assert "tests.py test_the_dot_stays_put" in text, \
            "no command that re-runs the failing test"
        assert "problems/nightly/" in text, "the transcript is not pointed at"
        assert "nightly.py" in text, "the report does not say who filed it"
        assert len(text) <= problems_mod.TEXT_MAX
        assert "…" not in text, \
            "the report was cut mid-word instead of counting the rest"
        assert item["env"].get("version") and item["env"].get("os_build"), \
            "no evidence about the machine"   # PR 9: version + build, no python
        # The transcript it points at is really there, and problems.md was
        # rewritten so the weekly read sees the report at all.
        assert Path(got["transcript"]).exists()
        digest = (tmp / problems_mod.DIGEST_NAME).read_text("utf-8")
        assert nightly_mod.REPORT_WHERE in digest and item["id"] in digest

        # A second bad night is a second report, not an edit of the first:
        # the routine rules on rows, and a row that changed under it is a
        # row it already read.
        nightly_mod.run(tmp, enabled=True, wait=1, ask=lambda _s: True,
                        launch=_fake_suite(BROKEN_RUN, 1))
        assert len(store.items(problems_mod.OPEN)) == 2

        # A run that never printed a verdict and did not exit 0 is a real
        # failure with no test name on it, and worth a report too.
        crashed = nightly_mod.verdict(transcript="Traceback…", code=1)
        assert crashed["result"] == nightly_mod.FAILED, crashed
        assert "did not finish" in nightly_mod.report_text(crashed)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_nightly_run_he_stopped_is_recorded_as_stopped() -> None:
    """His words, and obviously right: pressing Stop is not a bug. A
    killed suite is full of failures that only mean it was killed, so
    `stopped` is checked before any of them are read, nothing is filed,
    and the log says the word."""
    import shutil

    import nightly as nightly_mod
    import problems as problems_mod

    tmp = _nightly_dir()
    try:
        got = nightly_mod.run(
            tmp, enabled=True, wait=1, ask=lambda _s: True,
            launch=_fake_suite(BROKEN_RUN, 1, stopped=True))
        assert got["result"] == nightly_mod.STOPPED, got
        assert got["failed"] == [] and got["real"] == [], got
        assert got["report"] is None
        assert problems_mod.Store(tmp / problems_mod.STORE_NAME).items() == []
        log = (nightly_mod.folder(tmp) / nightly_mod.LOG_NAME).read_text(
            "utf-8")
        assert "STOPPED" in log and "not a failure" in log, log

        # The ask itself: a file the dashboard writes and the runner
        # clears, so a stop asked for last night cannot end tonight's run
        # a second after it starts.
        assert not nightly_mod.stop_asked(tmp)
        assert nightly_mod.ask_stop(tmp)
        assert nightly_mod.stop_asked(tmp)
        nightly_mod.clear_stop(tmp)
        assert not nightly_mod.stop_asked(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_two_nightly_runs_cannot_overlap_and_a_dead_one_blocks_nothing():
    """The lock is an OS-held handle, which buys two things at once.

    Two runs cannot overlap: the second one does not even ask, because
    asking is part of the run. And a crashed run cannot wedge every
    future night — Windows drops the handle however the process ended, so
    a leftover marker on disk with nobody holding the lock reads as "no
    run", which is also what keeps a dead button out of his bar.
    """
    import shutil

    import nightly as nightly_mod

    tmp = _nightly_dir()
    try:
        with nightly_mod.hold(tmp) as mine:
            assert mine, "could not take the lock at all"
            asked: list = []
            got = nightly_mod.run(tmp, enabled=True, wait=1,
                                  ask=lambda _s: asked.append(1) or True,
                                  launch=_fake_suite(CLEAN_RUN))
            assert got["result"] == nightly_mod.BUSY, got
            assert asked == [], "the second run put a second card up"
            assert got["report"] is None

        # THE CRASHED RUN. Its marker is still on disk and nobody holds
        # the lock: no run, no button, and tonight starts clean.
        nightly_mod.mark_running(tmp)
        assert (nightly_mod.folder(tmp) / nightly_mod.MARKER_NAME).exists()
        assert not nightly_mod.running(tmp), \
            "a killed run left a Stop button that stops nothing"
        got = nightly_mod.run(tmp, enabled=True, wait=1,
                              ask=lambda _s: True,
                              launch=_fake_suite(CLEAN_RUN))
        assert got["result"] == nightly_mod.CLEAN, got
        assert not (nightly_mod.folder(tmp) / nightly_mod.MARKER_NAME).exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_nightly_runner_really_starts_and_really_stops_a_suite() -> None:
    """The plumbing under the decisions, exercised for real — a
    `tests_quiet.py` of two lines standing in for the one that takes four
    minutes and the mouse, in a folder shaped like the repo.

    Three things that can only be checked by actually launching something:
    the transcript is what the child printed, the stop file ends the run
    within a poll, and what comes back is (exit code, stopped) with
    `stopped` true — which is what keeps a killed suite from being read
    as a broken one.
    """
    import shutil

    import nightly as nightly_mod

    tmp = _nightly_dir()
    try:
        (tmp / "tests_quiet.py").write_text(
            "print('running 711 tests')\nprint('all tests passed "
            "(quietly)')\n", "utf-8")
        out = nightly_mod.folder(tmp) / "run-one.txt"
        code, stopped = nightly_mod.run_suite(tmp, out, poll=0.05)
        assert (code, stopped) == (0, False), (code, stopped)
        assert "all tests passed" in out.read_text("utf-8")
        assert nightly_mod.verdict(transcript=out.read_text("utf-8"),
                                   code=code)["result"] \
            == nightly_mod.CLEAN

        # ...and one that would run all night. The stop file is written
        # before it starts, so the first poll finds it.
        (tmp / "tests_quiet.py").write_text(
            "import time\nprint('running 711 tests', flush=True)\n"
            "time.sleep(120)\n", "utf-8")
        out = nightly_mod.folder(tmp) / "run-two.txt"
        started = time.monotonic()
        import threading
        threading.Timer(0.2, lambda: nightly_mod.ask_stop(tmp)).start()
        code, stopped = nightly_mod.run_suite(tmp, out, poll=0.05)
        took = time.monotonic() - started
        assert stopped is True, (code, stopped)
        assert took < 30, f"the stop took {took:.0f}s to land"
        assert not nightly_mod.stop_asked(tmp), \
            "the ask was left behind to end tomorrow's run too"
        assert nightly_mod.verdict(transcript=out.read_text("utf-8"),
                                   code=code,
                                   stopped=stopped)["result"] \
            == nightly_mod.STOPPED
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_suite_that_died_mid_run_is_not_a_clean_run() -> None:
    """The worst thing a test runner can do, and it did it (2026-09-22).

    The product suite ABORTED two thirds of the way through — 680 of 945,
    twice in three runs that evening — on Tcl_AsyncDelete, which does not
    raise: it kills the interpreter where it stands. tests_quiet.py looks
    for FAIL lines, a dead run prints none, so none were found; it
    printed "all tests passed (quietly)" and exited 0. The nightly reads
    that exit code, so a night that never ran 265 of its tests would have
    filed nothing and told him it was clean.

    A run is finished only when it says so — "all tests passed", or
    "N FAILED: …" — and _died() reads that last line and nothing else. It
    names where the run stopped and why, and the exit code that follows
    it is the whole reason nightly.verdict calls the night FAILED."""
    import nightly as nightly_mod
    import tests_quiet as tq

    done = "running 945 tests\n  PASS  test_a\n  PASS  test_b\n\nall tests passed\n"
    assert tq._died(done, 0, "tests.py") == "", "a finished run is not a death"
    lost = ("running 945 tests\n  PASS  test_a\n  FAIL  test_b: no\n"
            "\n1 FAILED: test_b\n")
    assert tq._died(lost, 1, "tests.py") == "", \
        "a run that FAILED still reached its own last line"

    # the real shape: it spoke, it died, it never gave a verdict
    dead = ("running 945 tests\n  PASS  test_a\n"
            "  PASS  test_the_local_repair_no_longer_holds_the_paste\n"
            "Tcl_AsyncDelete: async handler deleted by the wrong thread\n")
    said = tq._died(dead, 3, "tests.py")
    assert said, "the run that died was read as a clean one"
    assert "test_the_local_repair_no_longer_holds_the_paste" in said, said
    assert "Tcl_AsyncDelete" in said and "never ran" in said, said
    assert "2 test(s)" in said, said
    # one that died before opening its mouth still says so, by exit code
    early = tq._died("running 945 tests\n", 1, "tests.py")
    assert "before the first test" in early and "exit code 1" in early, early

    # and what the night makes of it. The transcript is no help — the
    # ops half that ran after it ends with "all tests passed" — so the
    # EXIT CODE is the only thing standing between this and a clean night.
    whole = dead + "\n---- dev\\tests_ops.py ----\nall tests passed\n"
    assert nightly_mod.verdict(transcript=whole, code=1)["result"] \
        == nightly_mod.FAILED, "a dead run has to be a failed night"
    assert nightly_mod.verdict(transcript=whole, code=0)["result"] \
        == nightly_mod.CLEAN, \
        "this is what it looked like before: exit 0 and nobody the wiser"

    # the wiring, which no fixture can reach without four minutes and a
    # hidden desktop: the code comes back from run_hidden and gates the
    # one line that says the run was clean.
    src = (REPO / "tests_quiet.py").read_text("utf-8")
    assert "product_code = run_hidden(" in src and "ops_code = run_hidden(" in src, \
        "the exit code of a hidden run must never be thrown away again"
    assert "elif died:" in src, \
        "nothing stops a dead run from printing that all tests passed"


def test_the_nightly_setting_turns_the_whole_thing_off() -> None:
    """One line in config.toml, and the scheduled task still fires, reads
    it and goes back to sleep — no card, no run, no report. And the wait
    is bounded, because a card nobody could read in time is the same as
    no card at all."""
    import shutil

    import nightly as nightly_mod

    cfg = config_mod.load(REPO / "defaults.toml")
    assert cfg.tests.nightly is True, "the shipped config has it on"
    assert cfg.tests.wait_seconds == 300.0 \
        == nightly_mod.ASK_SECONDS, cfg.tests
    assert (config_mod.TESTS_WAIT_MIN, config_mod.TESTS_WAIT_MAX) \
        == (30.0, 3600.0)
    # Refused AT LOAD, like every other value that can be wrong here: a
    # card that has already gone by the time he walks over is the same as
    # no card at all, and the app must not start believing in one.
    room = Path(tempfile.mkdtemp(prefix="nightly-config-"))
    try:
        base = (REPO / "defaults.toml").read_text("utf-8")
        assert "wait_seconds = 300" in base
        for bad in ("5", "0", "99999"):
            path = room / "config.toml"
            path.write_text(base.replace("wait_seconds = 300",
                                         f"wait_seconds = {bad}"), "utf-8")
            try:
                config_mod.load(path)
            except config_mod.ConfigError as e:
                assert "wait_seconds" in str(e), e
            else:
                raise AssertionError(f"wait_seconds {bad} was accepted")
        path.write_text(base.replace("nightly = true", "nightly = false"),
                        "utf-8")
        assert config_mod.load(path).tests.nightly is False
    finally:
        import shutil as _shutil
        _shutil.rmtree(room, ignore_errors=True)

    tmp = _nightly_dir()
    try:
        asked: list = []
        got = nightly_mod.run(tmp, enabled=False, wait=300,
                              ask=lambda _s: asked.append(1) or True,
                              launch=_fake_suite(BROKEN_RUN, 1))
        assert got["result"] == nightly_mod.OFF, got
        assert asked == [], "it asked even though the setting is off"
        assert got["report"] is None
        lock = nightly_mod.folder(tmp) / nightly_mod.LOCK_NAME
        assert not lock.exists(), \
            "a run that is switched off still took the lock"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_bar_holds_stop_tests_only_while_a_run_is_going() -> None:
    """The rule the Push card and Stop already follow: a control exists
    only while there is something for it to do.

    It is the one button in the bar that does not care whether the app is
    running, because the nightly run is not the app's — a scheduled task
    starts it so that a crashed DeskIT is still a tested DeskIT. Pressing
    it writes the ask down where the runner will find it, and the places
    still clear the state chip in every state, which is what the uptime
    steps aside for.
    """
    import dashboard as dash
    import nightly as nightly_mod

    saved = nightly_mod.running
    try:
        nightly_mod.running = lambda *a, **k: False
        with _window() as board:
            if board is None:
                return
            for reply in (BAR_OFF, BAR_ON, BAR_STARTING):
                board._refresh(reply)
                board.root.update_idletasks()
                assert not board.parts["tests_stop"].winfo_manager(), \
                    "Stop tests is in the bar with no run to stop"
            # A run starts, and the button turns up on the next poll.
            nightly_mod.running = lambda *a, **k: True
            for reply in (BAR_OFF, BAR_ON, BAR_PAUSED, BAR_STARTING,
                          {"ok": True, "stage": "running",
                           "activity": "busy", "uptime_s": 11532}):
                board._refresh(reply)
                board.root.update_idletasks()
                tests = board.parts["tests_stop"]
                tests.update_idletasks()
                assert tests.winfo_manager(), "no Stop tests during a run"
                chip, nav = board.parts["chip"], board.nav
                chip.update_idletasks()
                nav.update_idletasks()
                assert nav.winfo_x() + nav.winfo_reqwidth() \
                    <= chip.winfo_x(), \
                    "the places run under the state chip during a run"
                assert chip.winfo_x() + chip.winfo_reqwidth() \
                    <= tests.winfo_x(), "the state runs under Stop tests"
                assert not chip.meta.winfo_manager(), \
                    "the uptime did not step aside for the button"
                for left, right in ((tests, board.parts["stop_bar"]),
                                    (board.parts["stop_bar"],
                                     board.parts["bar_screens"]),
                                    (board.parts["bar_screens"],
                                     board.parts["run"])):
                    if not (left.winfo_manager() and right.winfo_manager()):
                        continue
                    left.update_idletasks()
                    right.update_idletasks()
                    assert left.winfo_x() + left.winfo_reqwidth() \
                        <= right.winfo_x(), "two buttons in the bar overlap"

            # The press: it writes the ask where the runner reads it, and
            # says so on the button rather than vanishing.
            asked: list = []
            saved_ask = nightly_mod.ask_stop
            try:
                nightly_mod.ask_stop = lambda *a: asked.append(1) or True
                board.parts["tests_stop"]._command()
            finally:
                nightly_mod.ask_stop = saved_ask
            assert asked == [1], "Stop tests did not ask for a stop"
            word = board.parts["tests_stop"]
            assert str(word.itemcget(word._label, "text")) == "Stopping…", \
                "the button gave no sign it had taken the press"
            assert "stopped, not as a failure" in board._toast_text, \
                board._toast_text

            # ...and when the run ends, the button and its word go, and
            # the uptime comes back.
            nightly_mod.running = lambda *a, **k: False
            board._refresh(BAR_ON)
            board.root.update_idletasks()
            assert not word.winfo_manager()
            assert str(word.itemcget(word._label, "text")) == "Stop tests"
            assert board.parts["chip"].meta.winfo_manager(), \
                "the uptime never came back"
    finally:
        nightly_mod.running = saved


def test_the_nightly_scripts_say_what_they_will_do_before_they_do_it():
    """The two PowerShell files, which are the only things in this repo
    that change the MACHINE rather than the app.

    nightly_tests.ps1 is what the task runs and it is shaped like
    weekly_review.ps1 — the repo found from $PSScriptRoot rather than a
    typed path, a log outside the repo for the one message that cannot go
    in it, and exit 0 whatever happened. install_nightly_task.ps1 is read
    before it is run, so it has to SAY what it will register, and it must
    not turn on StartWhenAvailable: a test run that catches up at nine in
    the morning takes his mouse, which is the one thing this feature
    exists to avoid.
    """
    runner = (REPO / "nightly_tests.ps1").read_text(encoding="utf-8-sig")
    assert "$PSScriptRoot" in runner, "the repo path is typed rather than read"
    assert "nightly.py" in runner
    assert "--no-screen" not in runner, \
        "the nightly run must not skip the sixteen"
    assert runner.rstrip().endswith("exit 0"), \
        "a bad night must not leave a red icon in Task Scheduler"
    assert "-NoNewWindow" in runner, "a console would flash on his screen"

    setup = (REPO / "install_nightly_task.ps1").read_text(
        encoding="utf-8-sig")
    assert "Register-ScheduledTask" in setup
    assert "'02:55'" in setup, "the hour is not the one he asked for"
    assert "StartWhenAvailable = $false" in setup, \
        "a missed night would be caught up on while he is at the desk"
    assert "-NoProfile -NonInteractive -ExecutionPolicy Bypass " \
           "-WindowStyle Hidden -File" in setup, \
        "not the same six switches the weekly task uses"
    assert "LogonType Interactive" in setup, \
        "a session-0 task cannot draw the card or move the mouse"
    assert "-Remove" in setup, "no way to take it off the machine again"


def test_the_readme_and_agents_document_the_nightly_tests() -> None:
    """A routine nobody can find is a routine nobody trusts: the README
    has a section for it with every [tests] key in the Config reference,
    and AGENTS.md names nightly.py on its map."""
    readme = (REPO / "dev" / "README-dev.md").read_text(encoding="utf-8")
    heads = [ln for ln in readme.splitlines() if ln.startswith("## ")]
    assert any("night" in h.lower() for h in heads), \
        "no README section for the nightly test run"
    table = readme[readme.index("## Config reference"):]
    for key in ("nightly", "wait_seconds"):
        assert f"| `[tests] {key}` |" in table, key
    assert "nightly_tests.ps1" in readme and "install_nightly_task.ps1" \
        in readme, "the two scripts are never named"
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    where = agents[agents.index("## Where things live"):]
    assert "| `nightly.py`" in where, "nightly.py is not on the map"

def test_the_guide_holds_together():
    """dev/test_docs.py, the guide's own checks (chapter 14), as one
    test of the nightly: the trees, the pictures, the privacy chapter
    against plan 5.10, the generated pages fresh, no owner words."""
    import subprocess
    out = subprocess.run([sys.executable, str(REPO / "dev" / "test_docs.py")],
                         capture_output=True, encoding="utf-8", errors="replace",
                         cwd=str(REPO))
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-1000:]


def test_export_ignore_covers_forbidden():
    """.gitattributes decides the product tree (10.3 step 6): an archive of
    the working copy holds none of chapter 3 §3.10's forbidden paths and
    none of 7.4's dev files, and does hold the product. git check-attr
    agrees on every name, including the paths .gitignore keeps out of the
    repo altogether (they are listed so a working-copy archive is clean)."""
    import io
    import subprocess
    import zipfile

    proc = subprocess.run(["git", "archive", "--worktree-attributes",
                           "--format=zip", "HEAD"], cwd=REPO,
                          capture_output=True, check=True)
    names = zipfile.ZipFile(io.BytesIO(proc.stdout)).namelist()
    tops = {n.split("/", 1)[0] for n in names}
    forbidden_dirs = {"dev", "docs", "packaging", "android", ".github", ".claude",
                      ".agents", "problems", "recent", "pending", "corpus",
                      "captures"}
    assert not (tops & forbidden_dirs), tops & forbidden_dirs
    forbidden_files = {
        "tests.py", "tests_quiet.py", "nightly.py", "nightly_tests.ps1",
        "install_nightly_task.ps1", "weekly_review.ps1", "phase1_cutover.ps1",
        "questions.py", "answer_card.py", "make_icon.py", "audio_check.py",
        "install_fonts.py", "AGENTS.md", "DISTRIBUTION_PLAN.md",
        "PARALLEL_FEATURES_PLAN.md", "VISUAL_QA_PLAN.md", "SKIN.md",
        ".gitattributes", ".gitignore", "DeskIT.vbs", "Dashboard.vbs",
        "Stop DeskIT.vbs", "skin/preview.py", "skin/record.py"}
    leaked = forbidden_files & set(names)
    assert not leaked, leaked
    assert not [n for n in names if n.endswith(".html")], "an .html page"
    for must in ("main.py", "defaults.toml", "VERSION", "version.py", "manifest.py",
                 "deskit.pyw", "autostart.py",
                 "paths.py", "net.py", "privacy.py", "README.md", "icon.ico",
                 "skin/__init__.py", "transcribers/__init__.py", "fonts/"):
        assert must in names, f"{must} is not in the archive"
    # and the names .gitignore hides are marked too, for a working-copy tree
    ignored = ["vocab.json", "vocab.json.bak-2026", "review.json", "transcripts.log",
               "app.log.1", "problems.json", "questions.json", "consent.json",
               ".setup-done", "server_token.txt", "lookup_cache.json", ".env",
               "config.toml", "portable.txt", "network.log", "notify.json"]
    out = subprocess.run(["git", "check-attr", "export-ignore", "--", *ignored,
                          *sorted(forbidden_files)], cwd=REPO,
                         capture_output=True, encoding="utf-8", check=True).stdout
    unset = [ln for ln in out.splitlines() if not ln.endswith(": export-ignore: set")]
    assert not unset, unset



def test_the_inbox_pulls_only_what_was_ticked_and_forgets_what_was_deleted():
    """dev/inbox.py (plan 7.7, D33): the consented columns and nothing
    else are selected; an object comes down only when the row's
    attachments names it, and only from the row's own folder; each
    report lands as a problems.json-shaped row under
    inbox\\<user_id>\\ with the files beside it and the shot resolvable
    by problems.shot_path; a second pull fetches nothing twice; a row
    gone server-side takes its files with it, a user gone takes the
    folder; index.md never names a removed report; fetch.log names
    every fetch; the secret is read from the environment only and is
    nowhere on the disk afterwards; nothing is ever POSTed."""
    import io
    import json
    import shutil
    import tempfile
    import urllib.parse

    import inbox as inbox_mod
    import problems as problems_mod

    U1 = "11111111-1111-4111-8111-111111111111"
    U2 = "22222222-2222-4222-8222-222222222222"
    R1 = "aaaaaaaa-0000-4000-8000-000000000001"
    R2 = "aaaaaaaa-0000-4000-8000-000000000002"
    R3 = "aaaaaaaa-0000-4000-8000-000000000003"
    SECRET = "sb_secret_fixture_key_0123456789"
    rows = {
        R1: {"id": R1, "user_id": U1, "created_at": "2026-09-18T20:00:00+00:00",
             "updated_at": "2026-09-18T20:00:00+00:00", "app_version": "1.1.0",
             "os_build": "10.0.26200", "tier": "cpu", "kind": "wrong",
             "place": "dictation", "text": "המילה האחרונה נעלמה",
             "env": {"version": "1.1.0", "backend": "local"}, "status": "open",
             "attachments": [f"{U1}/{R1}/shot.jpg", f"{U1}/{R1}/sidecar.json",
                             f"{U1}/{R2}/shot.jpg"],       # another row's — refused
             "dictation_raw": "המילה האחרונה", "dictation_final": "המילה האחרונה נעלמה",
             "email": "nobody@example.com"},                # never asked for; ignored
        R2: {"id": R2, "user_id": U1, "created_at": "2026-09-18T21:00:00+00:00",
             "updated_at": "2026-09-18T21:00:00+00:00", "app_version": "1.1.0",
             "os_build": "10.0.26200", "tier": "gpu", "kind": "idea",
             "place": "settings", "text": "a switch for the dot", "env": {},
             "status": "open", "attachments": [], "dictation_raw": None,
             "dictation_final": None},
        R3: {"id": R3, "user_id": U2, "created_at": "2026-09-18T22:00:00+00:00",
             "updated_at": "2026-09-18T22:00:00+00:00", "app_version": "1.1.0",
             "os_build": "10.0.22631", "tier": "cpu", "kind": "broken",
             "place": "anywhere", "text": "the dot vanished", "env": {},
             "status": "open", "attachments": [f"{U2}/{R3}/dictation.wav"],
             "dictation_raw": None, "dictation_final": None},
    }
    objects = {f"{U1}/{R1}/shot.jpg": b"\xff\xd8\xff" + b"j" * 300,
               f"{U1}/{R1}/sidecar.json": json.dumps({"seconds": 2.5, "backend": "local",
                                                      "language": "he",
                                                      "words": [{"w": "x", "p": 0.9}]}).encode(),
               f"{U1}/{R2}/shot.jpg": b"\xff\xd8not-yours",
               f"{U2}/{R3}/dictation.wav": _tests.RIFF}
    calls: list[tuple[str, str, dict]] = []

    class _Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout=0):
        url = req.full_url
        calls.append((req.get_method(), url, dict(req.header_items())))
        assert req.get_method() == "GET", "the inbox wrote to the project"
        parsed = urllib.parse.urlsplit(url)
        if parsed.path == "/rest/v1/problem_reports":
            query = dict(urllib.parse.parse_qsl(parsed.query))
            assert query["select"].split(",") == list(inbox_mod.COLUMNS), query["select"]
            page = [dict(r) for r in rows.values()]
            if query.get("status", "").startswith("eq."):
                page = [r for r in page if r["status"] == query["status"][3:]]
            return _Reply(json.dumps(page).encode("utf-8"))
        if parsed.path.startswith("/storage/v1/object/reports/"):
            key = urllib.parse.unquote(parsed.path[len("/storage/v1/object/reports/"):])
            assert key in objects, key
            return _Reply(objects[key])
        raise AssertionError(url)

    tmp = Path(tempfile.mkdtemp(prefix="inbox-"))
    try:
        root = tmp / "problems"
        project = inbox_mod.Project("https://fixture.supabase.co", SECRET, opener=opener)
        dry = inbox_mod.pull(project, root=root, dry_run=True)
        assert dry == {"rows": 3, "new": 0, "files": 0, "removed": 0,
                       "folders_removed": 0, "users": 2}, dry
        assert not (root / "inbox").exists(), "a dry run wrote"
        counts = inbox_mod.pull(project, root=root)
        assert (counts["rows"], counts["new"], counts["files"], counts["users"]) == (3, 3, 3, 2), counts
        box = root / "inbox"
        one = json.loads((box / U1 / f"{R1}.json").read_text("utf-8"))
        assert one["id"] == R1 and one["user_id"] == U1 and one["kind"] == "wrong"
        assert one["where"] == "dictation" and one["text"] == "המילה האחרונה נעלמה"
        assert one["status"] == "open" and one["resolved"] is None and one["by"] == ""
        assert one["dictation"]["raw"] == "המילה האחרונה" and one["dictation"]["seconds"] == 2.5
        assert one["dictation"]["words"] and "wav" not in one["dictation"]
        assert "email" not in one and "email" not in one["server"], "an unconsented column landed"
        assert (box / U1 / f"{R1}.shot.jpg").read_bytes() == objects[f"{U1}/{R1}/shot.jpg"]
        assert (box / U1 / f"{R1}.sidecar.json").is_file()
        assert not (box / U1 / f"{R2}.shot.jpg").exists(), "another row's object came down"
        assert not any(c[1].endswith(f"{R2}/shot.jpg") for c in calls), "fetched outside the row's folder"
        # the shot resolves the way a local report's does
        store = problems_mod.Store(tmp / problems_mod.STORE_NAME)
        assert problems_mod.shot_path(store, one) == box / U1 / f"{R1}.shot.jpg"
        two = json.loads((box / U1 / f"{R2}.json").read_text("utf-8"))
        assert two["dictation"] == {} and two["shot"] == ""
        three = json.loads((box / U2 / f"{R3}.json").read_text("utf-8"))
        assert three["dictation"]["wav"] == str(box / U2 / f"{R3}.dictation.wav")
        log_text = (box / "fetch.log").read_text("utf-8")
        assert log_text.count("fetched row") == 3 and log_text.count("fetched object") == 3, log_text
        assert "outside the row's own folder" in log_text
        index = (box / "index.md").read_text("utf-8")
        assert R1 in index and R2 in index and R3 in index and "3 report(s)" in index
        assert SECRET not in log_text and SECRET not in index
        for path in box.rglob("*"):
            if path.is_file():
                assert SECRET.encode() not in path.read_bytes(), path
        # the secret went out as the two headers, on every call
        assert all(h["Apikey"] == SECRET and h["Authorization"] == f"Bearer {SECRET}"
                   for _m, _u, h in calls), calls[0]
        # a second pull: nothing fetched twice
        before = len(calls)
        again = inbox_mod.pull(project, root=root)
        assert again["new"] == 0 and again["files"] == 0, again
        assert len(calls) == before + 1, "objects were fetched again"
        # the person deleted R1, and U2 ran Delete my account
        del rows[R1]
        del rows[R3]
        gone = inbox_mod.pull(project, root=root)
        assert gone["removed"] == 1 and gone["folders_removed"] == 1, gone
        assert not (box / U1 / f"{R1}.json").exists() and not (box / U1 / f"{R1}.shot.jpg").exists()
        assert (box / U1 / f"{R2}.json").exists() and not (box / U2).exists()
        index = (box / "index.md").read_text("utf-8")
        assert R1 not in index and R3 not in index and R2 in index
        assert inbox_mod.status(root) == {"reports": 1, "users": 1, "open": 1,
                                          "inbox": str(box)}
        assert [i["id"] for i in inbox_mod.rows_on_disk(root)] == [R2]
        # only open rows, when asked
        rows[R2]["status"] = "fixed"
        assert inbox_mod.pull(project, root=root, status="open")["rows"] == 0
        # the secret: environment only, and shaped like the project's
        import os
        saved = os.environ.pop(inbox_mod.SECRET_VAR, None)
        try:
            try:
                inbox_mod.secret()
                raise AssertionError("no secret and no error")
            except inbox_mod.InboxError as e:
                assert "user variables" in str(e)
            os.environ[inbox_mod.SECRET_VAR] = "sb_publishable_not_the_secret"
            try:
                inbox_mod.secret()
                raise AssertionError("the publishable key passed as the secret")
            except inbox_mod.InboxError:
                pass
        finally:
            if saved is None:
                os.environ.pop(inbox_mod.SECRET_VAR, None)
            else:
                os.environ[inbox_mod.SECRET_VAR] = saved
        # never in the product tree: dev/ is export-ignored whole
        # (test_export_ignore_covers_forbidden archives and checks)
        assert (REPO / "dev" / "inbox.py").is_file()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_deleted_report_leaves_the_archive_too() -> None:
    """7.7 tombstones, the archive's half: the routine wraps a stranger's
    report in <!-- inbox <id> --> markers when it archives one
    (weekly-reports.md §6); when the report is gone server-side the pull
    cuts that block down to one comment that quotes nothing — in every
    document under problems\\weekly\\, for a deleted report and for every
    report of a deleted account alike; a document that names the id
    OUTSIDE a marked block is named in fetch.log and left alone; a
    report still on the server keeps its block."""
    import io
    import json
    import shutil
    import tempfile
    import urllib.parse

    import inbox as inbox_mod

    U1 = "11111111-1111-4111-8111-111111111111"
    U2 = "22222222-2222-4222-8222-222222222222"
    R1 = "aaaaaaaa-0000-4000-8000-000000000001"
    R2 = "aaaaaaaa-0000-4000-8000-000000000002"
    R3 = "aaaaaaaa-0000-4000-8000-000000000003"
    SECRET = "sb_secret_fixture_key_0123456789"

    def row(rid, uid, text):
        return {"id": rid, "user_id": uid, "created_at": "2026-09-18T20:00:00+00:00",
                "updated_at": "2026-09-18T20:00:00+00:00", "app_version": "1.1.0",
                "os_build": "10.0.26200", "tier": "cpu", "kind": "wrong", "place": "x",
                "text": text, "env": {}, "status": "open", "attachments": [],
                "dictation_raw": None, "dictation_final": None}
    rows = {R1: row(R1, U1, "המילה האחרונה נעלמה"), R2: row(R2, U1, "an idea"),
            R3: row(R3, U2, "second stranger")}

    class _Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout=0):
        parsed = urllib.parse.urlsplit(req.full_url)
        assert parsed.path == "/rest/v1/problem_reports", req.full_url
        return _Reply(json.dumps(list(rows.values())).encode("utf-8"))

    tmp = Path(tempfile.mkdtemp(prefix="inbox-archive-"))
    try:
        root = tmp / "problems"
        project = inbox_mod.Project("https://fixture.supabase.co", SECRET, opener=opener)
        inbox_mod.pull(project, root=root)
        weekly = root / "weekly"
        weekly.mkdir()
        archive = weekly / "2026-09-19-reports.md"
        archive.write_text(
            "# WEEKLY 2026-09-19 — archive\n\n"
            f"<!-- inbox {R1} -->\n### {R1}\n> המילה האחרונה נעלמה\n\nenv: local\n"
            f"<!-- /inbox {R1} -->\n\n"
            f"<!-- inbox {R2} -->\n### {R2}\n> an idea\n<!-- /inbox {R2} -->\n\n"
            f"<!-- inbox {R3} -->\n### {R3}\n> second stranger\n<!-- /inbox {R3} -->\n",
            "utf-8")
        plan = weekly / "2026-09-19-plan.md"
        plan.write_text(f"## 3. The work\n- {R3}: second stranger, still open\n", "utf-8")
        # R1 deleted by its sender; U2 ran Delete my account
        del rows[R1]
        del rows[R3]
        counts = inbox_mod.pull(project, root=root)
        assert counts["removed"] == 1 and counts["folders_removed"] == 1, counts
        text = archive.read_text("utf-8")
        for quoted in ("המילה האחרונה נעלמה", "env: local", "second stranger"):
            assert quoted not in text, text
        assert f"<!-- inbox {R1}: deleted by its sender on " in text
        assert f"<!-- inbox {R3}: deleted by its sender on " in text
        assert f"<!-- inbox {R2} -->" in text and "> an idea" in text, "a living report was cut"
        assert plan.read_text("utf-8").count(R3) == 1, "a loose mention was edited"
        log_text = (root / "inbox" / "fetch.log").read_text("utf-8")
        assert f"warning weekly/2026-09-19-plan.md still names {U2}/{R3}" in log_text, log_text
        assert not any("still names" in ln and R1 in ln for ln in log_text.splitlines()), \
            "R1 was cut cleanly and still reported"
        # nothing in the archive ever held the key
        assert SECRET not in text and SECRET not in log_text
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_routine_is_told_about_the_strangers_reports() -> None:
    """7.7 "The command file": weekly-reports.md says in its own words
    which fields of an inbox report are consented and that a missing
    one means not consented; that opening a screenshot with the Read
    tool sends it to Anthropic under the owner's account and that this
    is disclosed; that nothing is written back to a stranger (D33(b):
    no reply, no question — questions.ask is for the owner's own
    reports); that reports carry `version`, not the branch stamp; and
    how a stranger's report is archived so a tombstone can cut it out."""
    text = (REPO / ".claude" / "commands" / "weekly-reports.md").read_text("utf-8")
    for must in ("dev\\inbox.py", "problems\\inbox\\", "<!-- inbox ", "<!-- /inbox ",
                 "not consented", "Anthropic", "questions.ask", "fetch.log",
                 "DESKIT_SUPABASE_SECRET", "D33"):
        assert must in text, f"weekly-reports.md never says {must!r}"
    low = " ".join(text.lower().split())            # the file wraps at 80
    assert "do not infer" in low, "a missing field's meaning"
    assert "no reply channel" in low and "no `reply` command" in low
    assert "`version`" in text and "`python`" in text and "branch stamp" in low
    assert "report_replies" in low and "no `report_replies`" in low


def test_the_ci_gives_a_failed_test_one_second_try_and_says_so() -> None:
    """dev/ci_suite.py, the CI's suite step (2026-09-23: 14 of 100 runs red,
    nearly each on a different timing test, each an e-mail). Driven with a
    stand-in suite that keeps a count in a file: a test that fails once and
    passes on the second try is a warning and a green run; one that fails
    twice is red; a run that dies gets one more full run; more than
    MAX_RETRY failures at once gets no second try."""
    import json
    import subprocess
    import sys as sys_mod
    import tempfile

    fake = r'''
import json, sys
from pathlib import Path
state = Path(__file__).with_name("state.json")
s = json.loads(state.read_text()) if state.exists() else {"calls": 0}
s["calls"] += 1
state.write_text(json.dumps(s))
mode = Path(__file__).with_name("mode.txt").read_text().strip()
picks = [a for a in sys.argv[1:] if not a.startswith("-")]
if mode == "flaky":
    if s["calls"] == 1:
        print("  PASS  test_a"); print("  FAIL  test_b: boom"); print(); print("1 FAILED: test_b"); sys.exit(1)
    assert picks == ["test_b"], picks
    print("  PASS  test_b"); print(); print("all tests passed")
elif mode == "twice":
    print("  FAIL  test_b: boom"); print(); print("1 FAILED: test_b"); sys.exit(1)
elif mode == "died":
    if s["calls"] == 1:
        print("  PASS  test_a"); print("Tcl_AsyncDelete: async handler deleted by the wrong thread"); sys.exit(3)
    print("  PASS  test_a"); print(); print("all tests passed")
elif mode == "many":
    names = [f"test_{i}" for i in range(6)]
    print(); print(f"6 FAILED: {', '.join(names)}"); sys.exit(1)
'''
    expect = {"flaky": (0, 2, "Flaky on the CI runner::test_b"),
              "twice": (1, 2, "Failed twice::test_b"),
              "died": (0, 2, "Suite died once on the CI runner"),
              "many": (1, 1, "no second try")}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        script = Path(d) / "fake_suite.py"
        script.write_text(fake, "utf-8")
        for mode, (code, calls, said) in expect.items():
            (Path(d) / "state.json").unlink(missing_ok=True)
            (Path(d) / "mode.txt").write_text(mode, "utf-8")
            proc = subprocess.run(
                [sys_mod.executable, str(REPO / "dev" / "ci_suite.py"),
                 "--script", str(script)],
                cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                creationflags=0x08000000)
            got = json.loads((Path(d) / "state.json").read_text())["calls"]
            assert proc.returncode == code, (mode, proc.returncode, proc.stdout[-600:])
            assert got == calls, (mode, "suite ran", got, "times")
            assert said in proc.stdout, (mode, proc.stdout[-600:])
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    assert "python dev/ci_suite.py" in workflow, "the CI does not run the suite through ci_suite.py"


def test_the_inbox_is_not_in_the_product_and_its_secret_name_is_reserved() -> None:
    """The module lives in dev/ (the archive of the product tree has no
    dev/ — test_export_ignore_covers_forbidden), `inbox` is in
    tests.DEV_MODULES so no product module imports it at the top, and
    .gitignore's comment reserves the environment name so nobody writes
    it into a file beside the code (8.10)."""
    assert "inbox" in _tests.DEV_MODULES
    assert (REPO / "dev" / "inbox.py").exists()
    assert not (REPO / "inbox.py").exists(), "the inbox must not sit in the product tree"
    ignore = (REPO / ".gitignore").read_text("utf-8")
    assert "DESKIT_SUPABASE_SECRET" in ignore, ".gitignore does not reserve the name"
    for name in ("main.py", "dashboard.py", "sb.py", "problems.py"):
        src = (REPO / name).read_text("utf-8")
        assert "import inbox" not in src and "DESKIT_SUPABASE_SECRET" not in src, name


# ---------------------------------------------------------------------------
# The master app (dev\master\, MASTER.md). Six screens that READ, one verb
# that takes a row to a chat, one tick that only his hand puts on a row.
# Every test here builds its own checkout in a scratch folder: none of them
# may look at the owner's real problems.json, corpus or account.
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402

from dev.master import export as _mexport  # noqa: E402
from dev.master import sources as _msources  # noqa: E402
from dev.master.root import Root as _MRoot  # noqa: E402
from dev.master.store import Store as _MStore  # noqa: E402

_NIGHT_OUT = ('[{stamp}] {word} in {secs}s\n'
              '[{stamp}] [out] {json}\n')


def _master_root(folder: Path, *, git: bool = True, guard: bool = True) -> "_MRoot":
    """A checkout the master can read: his own report, a stranger's with
    its files, three nights, a corpus, a vocabulary and a log."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "VERSION").write_text("9.9.9\n", "utf-8")
    (folder / "defaults.toml").write_text("[study]\ncorpus_keep = 4\n"
                                          "[vocab]\nkeep_audio = 2\n", "utf-8")
    trim = "    def _trim(self) -> None:\n"
    trim += "        if paths.OWNER_DATA:\n            return\n" if guard else "        pass\n"
    (folder / "study.py").write_text("class Corpus:\n" + trim, "utf-8")
    if git:
        (folder / ".git").mkdir(exist_ok=True)

    # his own report
    (folder / "problems.json").write_text(_json.dumps({"version": 1, "items": [
        {"id": "20260923-211403", "at": "2026-09-23 21:14:03", "where": "the desk",
         "kind": "broken", "status": "open",
         "text": "הדף של ההגדרות קופץ כשאני עובר בין הלשוניות",
         "env": {"version": "1.0.4"}, "dictation": {}},
    ]}, ensure_ascii=False), "utf-8")

    # a stranger's, with a picture and a recording beside it
    box = folder / "problems" / "inbox" / "8f2ccafe"
    box.mkdir(parents=True, exist_ok=True)
    (box / "shot.jpg").write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
    (box / "dictation.wav").write_bytes(b"RIFF....WAVEfmt ")
    (box / "r1.json").write_text(_json.dumps({
        "id": "r1", "user_id": "8f2ccafe", "at": "2026-09-23 19:02:00",
        "where": "dictation", "kind": "wrong", "status": "open",
        "text": "The second button does nothing when I press it",
        "shot": "shot.jpg", "dictation": {"wav": "dictation.wav", "seconds": 4.2},
        "env": {"version": "1.0.4", "os": "Windows 11 26200"},
        "server": {"created_at": "2026-09-23T19:02:00Z"},
    }, ensure_ascii=False), "utf-8")

    # three nights: one clean, one with the machine's known flake, one failed
    nights = folder / "problems" / "nightly"
    nights.mkdir(parents=True, exist_ok=True)
    log = ""
    for stamp, word, verdict in (
            ("20260921-030003", "4 failed",
             {"result": "failed", "failed": ["test_a", "test_b"],
              "real": ["test_a", "test_b"], "code": 1, "report": "p1"}),
            ("20260922-030004", "clean",
             {"result": "clean", "failed": [], "real": [], "code": 0, "report": None}),
            ("20260923-030002", "clean",
             {"result": "clean", "failed": [], "real": [], "code": 0, "report": None})):
        transcript = nights / f"{stamp}-tests.txt"
        body = "  PASS  test_one\n  PASS  test_two\n"
        if verdict["result"] == "failed":
            body += "  FAIL  test_a: it did not\n  FAIL  test_b: nor did it\n"
        transcript.write_text(body + "\n(hidden desktop 'DeskITTests': 16 test(s) "
                                     "ran in the open; 244s in all)\n", "utf-8")
        verdict["transcript"] = str(transcript)
        pretty = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}"
        log += _NIGHT_OUT.format(stamp=pretty, word=word, secs=244,
                                 json=_json.dumps(verdict))
    (nights / "run.log").write_text(log, "utf-8")

    # the training data
    corpus = folder / "corpus"
    corpus.mkdir(exist_ok=True)
    for n, tier in enumerate(("gold", "silver", "silver")):
        (corpus / f"2026092{n}-120000-0001.wav").write_bytes(b"RIFF")
        (corpus / f"2026092{n}-120000-0001.json").write_text(_json.dumps(
            {"text": "מה שאמרתי", "tier": tier, "seconds": 4.0,
             "kept": f"2026-09-2{n} 12:00:0{n}"}, ensure_ascii=False), "utf-8")
    (folder / "recent").mkdir(exist_ok=True)
    (folder / "recent" / "x.wav").write_bytes(b"RIFF")
    (folder / "transcripts.log").write_text(
        "2026-09-23 21:14:57,185 | OK | 1.3s | local | 0.5s latency | תמשיך\n"
        "2026-09-23 21:15:57,185 | POLISHED | 2.3s | local | 0.5s | עוד משפט\n", "utf-8")
    (folder / "vocab.json").write_text(_json.dumps({"version": 1, "corrections": [
        {"heard": "ריפו", "meant": "repo", "hits": 2, "last": "2026-09-20 10:00:00"}]},
        ensure_ascii=False), "utf-8")
    return _MRoot(folder)


def _master_snapshot(folder: Path) -> dict:
    """Every file under a checkout, by its bytes — what a read must leave
    exactly as it found it."""
    out = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(folder))] = path.read_bytes()
    return out


def test_the_master_reads_his_reports_and_other_peoples_into_one_list():
    """Both kinds, newest first, with the stranger's files found beside
    the report and the Hebrew line marked as the right-to-left one."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _master_root(Path(tmp) / "checkout")
        rows = _msources.rows("reports", root)
        assert len(rows) == 2, [r.id for r in rows]
        mine, theirs = rows
        assert mine.id == "report:mine:20260923-211403" and mine.rtl, mine
        assert "yours" in mine.under and "1.0.4" in mine.under, mine.under
        assert theirs.id == "report:8f2ccafe:r1" and not theirs.rtl, theirs
        assert "from a user" in theirs.under, theirs.under
        kinds = {e.kind: e for e in theirs.evidence}
        assert set(kinds) >= {"picture", "recording"}, theirs.evidence
        assert kinds["recording"].word == "4.2 s", kinds["recording"]
        assert kinds["picture"].path.is_file() and kinds["recording"].path.is_file()
        # the words are the row's body, untouched
        assert theirs.body == "The second button does nothing when I press it"


def test_the_master_reads_a_night_from_the_run_log_and_the_transcript_is_the_evidence():
    """The verdict is the [out] line of run.log — the first version of
    this screen read the transcripts instead and called eleven good
    nights "stopped". Two clean nights in a row collapse into one row."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _master_root(Path(tmp) / "checkout")
        rows = _msources.rows("tests", root, net=False)
        assert [r.tone for r in rows][:1] == ["ok"], [(r.title, r.tone) for r in rows]
        newest = rows[0]
        assert "Clean" in newest.title and "244 s" in newest.under, newest.under
        assert newest.facts["Tests"] == 2, newest.facts
        failed = [r for r in rows if r.tone == "bad"]
        assert len(failed) == 1, [r.title for r in rows]
        assert "2 failed" in failed[0].title and "test_a" in failed[0].title
        assert "FAIL  test_a" in failed[0].body, failed[0].body
        assert failed[0].body_from == "machine", failed[0].body_from
        assert failed[0].evidence and failed[0].evidence[0].kind == "transcript"


def test_the_master_counts_the_corpus_and_warns_only_where_the_trim_can_run():
    """The numbers are counted, not guessed; and the warning row exists
    only where study.py's trim would actually delete something — never on
    the owner's own checkout, where the guard returns first."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _master_root(Path(tmp) / "his", git=True, guard=True)
        rows = {r.id: r for r in _msources.rows("data", root)}
        assert "data:trim" not in rows, "the owner's checkout never trims"
        assert rows["data:corpus"].fig == "3", rows["data:corpus"].fig
        assert rows["data:corpus"].fig_small == "of 4 before the trim"
        assert rows["data:gold"].fig == "1", rows["data:gold"].fig
        assert rows["data:vocab"].fig == "1", rows["data:vocab"].fig
        assert rows["data:transcripts"].facts["Lines"] == 2
        assert rows["data:recent"].fig == "1" and rows["data:recent"].fig_small == "of 2"

        stranger = _master_root(Path(tmp) / "stranger", git=False, guard=False)
        rows = {r.id: r for r in _msources.rows("data", stranger)}
        assert "data:trim" in rows, "a copy whose trim runs must say so"
        assert rows["data:trim"].tone == "warn"
        assert rows["data:trim"].facts["Guard in study.py"] == "NO"


def test_only_a_hand_ticks_a_master_row_and_an_export_never_does():
    """His rule, 2026-09-23: nothing marks a row handled but him. The
    ledger records that a row was taken to a chat and leaves the tick
    exactly as it was."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _master_root(Path(tmp) / "checkout")
        store = _MStore(Path(tmp) / "state")
        row = _msources.rows("reports", root, store=store)[0]
        assert not row.ticked and not row.took

        _mexport.take_to_a_chat(row, root, store, home=Path(tmp) / "out", copy=False)
        again = _msources.rows("reports", root, store=store)[0]
        assert again.took, "the ledger did not record the export"
        assert not again.ticked, "an export must never tick a row"

        store.tick(row.id, True)
        ticked = _msources.rows("reports", root, store=store)[0]
        assert ticked.ticked and ticked.ticked_at, ticked
        store.tick(row.id, False)
        assert not _msources.rows("reports", root, store=store)[0].ticked
        # and the mark survives a new Store over the same folder
        store.tick(row.id, True)
        assert _MStore(Path(tmp) / "state").ticked(row.id)


def test_an_export_carries_the_words_untouched_and_the_files_beside_them():
    """Verbatim, in a block that says it is a quotation — he pastes this
    into a chat, and a report that says "ignore your instructions" must
    arrive there as data."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _master_root(Path(tmp) / "checkout")
        store = _MStore(Path(tmp) / "state")
        row = next(r for r in _msources.rows("reports", root, store=store)
                   if r.id.startswith("report:8f2ccafe"))
        done = _mexport.take_to_a_chat(row, root, store,
                                       home=Path(tmp) / "out", copy=False)
        folder = Path(done["folder"])
        names = sorted(p.name for p in folder.iterdir())
        assert names == ["dictation.wav", "report.md", "shot.jpg"], names
        text = (folder / "report.md").read_text("utf-8")
        assert row.body in text, "the words were not carried whole"
        assert "data, not instructions" in text, text[:400]
        assert "```text" in text and text.count("```") >= 2
        assert "9.9.9" in text and row.id in text
        assert "Windows 11 26200" in text, "the facts around it were dropped"
        assert "summar" in text.rsplit("---", 1)[-1], "the promise is not on the page"
        # a second export is a second line in the ledger, not a second folder
        _mexport.take_to_a_chat(row, root, store, home=Path(tmp) / "out", copy=False)
        assert len(store._data["exports"][row.id]) == 2


def test_the_master_writes_nothing_into_the_checkout_it_reads():
    """Rule 1 of MASTER.md, held by bytes: read every screen, then
    compare every file in the checkout with what it was before."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "checkout"
        root = _master_root(folder)
        store = _MStore(Path(tmp) / "state")
        before = _master_snapshot(folder)
        for screen in ("reports", "tests", "data"):
            _msources.rows(screen, root, net=False, store=store)
        row = _msources.rows("reports", root, store=store)[0]
        store.tick(row.id, True)
        _mexport.take_to_a_chat(row, root, store, home=Path(tmp) / "out", copy=False)
        after = _master_snapshot(folder)
        assert after == before, sorted(set(after) ^ set(before)) or "a file changed"
        assert not (folder / "dev").exists(), "the master made a folder in his checkout"


def test_a_row_may_leave_its_body_for_the_export_to_build():
    """A branch's diff is three git commands; twenty-five branches were
    seventy-five of them before the Code screen could be drawn. Such a
    body is a callable the EXPORT runs — the screen never pays for it,
    and the page is never handed a function."""
    from dev.master.rows import Row as _MRow
    built = []

    def slow():
        built.append(1)
        return "the whole diff"

    row = _MRow(id="code:branch:x", screen="code", title="x", body_fn=slow)
    assert row.body == "" and "body_fn" not in row.to_dict()
    assert not built, "the screen built the body"
    with tempfile.TemporaryDirectory() as tmp:
        root = _master_root(Path(tmp) / "checkout")
        text = _mexport.document(row, root)
        assert "the whole diff" in text and len(built) == 1
        _mexport.document(row, root)
        assert len(built) == 1, "the body was built twice"


def test_a_long_body_goes_in_a_file_beside_the_document():
    """His first real export, 2026-09-24: a branch's diff was 276,000
    characters. Cutting it inside the document kept the first 12 KB of
    `git diff` — alphabetical, so .gitignore survived and no line of the
    code did. The whole thing is a file beside the document now, and the
    document keeps its head and says where the rest is."""
    from dev.master.rows import Row as _MRow
    with tempfile.TemporaryDirectory() as tmp:
        root = _master_root(Path(tmp) / "checkout")
        store = _MStore(Path(tmp) / "state")
        long = "diff --git a/x b/x\n" + ("+a line of the change\n" * 4000)
        row = _MRow(id="code:branch:x", screen="code", title="x — a big branch",
                    body=long, body_from="machine")
        done = _mexport.take_to_a_chat(row, root, store,
                                       home=Path(tmp) / "out", copy=False)
        folder = Path(done["folder"])
        assert sorted(p.name for p in folder.iterdir()) == ["change.diff", "report.md"]
        assert (folder / "change.diff").read_text("utf-8") == long, "the file is not whole"
        text = (folder / "report.md").read_text("utf-8")
        assert len(text) < len(long) / 3, "the document swallowed the whole diff"
        assert "change.diff" in text and "more characters" in text
        assert long[:500] in text, "the document lost the head of it"


def test_the_windows_bridge_answers_only_the_names_the_api_lists():
    """webdesk.py's dispatcher checks Api.CALLS, and the master's Api is
    flat: no dotted path, no attribute that is not one of those calls.
    The page cannot widen the list — `api` comes from the process that
    opened the window."""
    from dev.master import webdesk as _mwebdesk
    from dev.master.api import Api as _MApi
    with tempfile.TemporaryDirectory() as tmp:
        root = _master_root(Path(tmp) / "checkout")
        api = _MApi(root, _MStore(Path(tmp) / "state"))
        assert set(api.CALLS) == {"rows", "tick", "preview", "take",
                                  "open_folder", "ping"}, api.CALLS
        assert tuple(_mwebdesk._calls(api)) == tuple(api.CALLS)
        assert _mwebdesk._calls(None) == _mwebdesk.CALLS
        for name in api.CALLS:
            assert callable(getattr(api, name)), name
        public = {n for n in dir(api) if not n.startswith("_")}
        assert public == set(api.CALLS) | {"CALLS"}, public
        assert api.rows("nowhere")["ok"] is False
        assert api.open_folder("C:\\Windows")["ok"] is False, "any path was opened"


def test_every_master_row_has_an_id_a_screen_and_a_tone_the_window_can_draw():
    with tempfile.TemporaryDirectory() as tmp:
        root = _master_root(Path(tmp) / "checkout")
        seen = set()
        for screen in ("reports", "tests", "data"):
            for row in _msources.rows(screen, root, net=False):
                assert row.id and row.id not in seen, f"duplicate row id {row.id}"
                seen.add(row.id)
                assert row.screen == screen, (row.id, row.screen)
                assert row.tone in ("q", "ok", "warn", "bad", "iris"), row.tone
                assert row.title.strip(), row.id
                assert ":" in row.id, row.id


if __name__ == "__main__":
    if not paths.DEVELOPER:
        print("the ops suite is the owner's: it runs only in the checkout "
              "(no .git beside main.py here)")
        sys.exit(2)
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)
             and getattr(f, "__module__", None) == __name__]
    picks = [a for a in sys.argv[1:] if not a.startswith("-")]
    skips = [a[1:] for a in sys.argv[1:] if a.startswith("-") and a[1:]]
    if picks:
        tests = [(n, f) for n, f in tests if any(p in n for p in picks)]
    if skips:
        tests = [(n, f) for n, f in tests if not any(s in n for s in skips)]
    print(f"running {len(tests)} tests", flush=True)
    for test_name, fn in tests:
        check(test_name, fn)
        gc.collect()                      # the same reason tests.py gives
    if _tests.FAILURES:
        print(f"\n{len(_tests.FAILURES)} FAILED: {', '.join(_tests.FAILURES)}")
        sys.exit(1)
    print("\nall tests passed")
