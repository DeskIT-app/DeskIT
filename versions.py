"""Switch the whole app between whole versions, with one double-click.

There are two, kept as git branches of this very folder:

  classic — the app exactly as it was the day this file was added. Frozen:
            the REPAIR PASS is what is frozen, and nothing else. Fixes and
            shared features land here too (see below), or the two versions
            would drift into two different programs.
  fast    — the same app with the context pass sent to Groq's free API
            first (~0.3-0.6 s instead of ~5 s), falling back to the same
            local Ollama model classic uses; Whisper gains tuning knobs.
            It was Cerebras until 2026-08-22, when their free tier was
            measured dead (HTTP 402 on every model); the setting to go
            back is kept, the default is not.

WHAT ACTUALLY DIFFERS, AND WHAT MUST NOT
----------------------------------------
Only the repair pass and its settings: polish.py, translate.py, the
[polish] backend fields and [local] beam_size in config.py, and the tests
covering them. EVERYTHING ELSE IS THE SAME FILE ON BOTH BRANCHES —
popup.py, lookup.py, main.py, this module, config.toml — and additive
work on those gets mirrored across rather than committed to one side.

That is not tidiness. Switching is a `git checkout` of this very folder,
so a file that exists on one branch and not the other DISAPPEARS when you
switch, and a shared feature committed to fast alone is a feature the user
loses by pressing a button labelled "use classic". The owner's rule, in
his words: both versions must stay "the same application, with the same
history and the same hot words".

Switching must never be able to lose anything, so the rules are strict:

- Your settings survive. config.toml is TRACKED by git, which means a bare
  `git checkout` would replace it with the other branch's copy. It never
  gets the chance: the live bytes are saved in memory, the working tree is
  cleaned, the branch is flipped, and the bytes are written straight back.
  Both branches commit byte-identical config.toml for ever, so there is
  nothing to merge and nothing that can conflict — your hotkeys, your
  vocabulary seeds, all of it, identical under either version. (.env,
  vocab.json, transcripts.log, recent\\ are gitignored: untouched by any
  checkout, shared by both versions automatically.)
- A dirty tree stops the switch. If anything OTHER than config.toml has
  uncommitted edits, the switch refuses and says so, rather than guessing
  whether to keep or drop someone's work.
- A running instance is stopped first and restarted after, because the
  Python on disk and the Python in memory should never disagree. Stopping
  mid-recording loses that recording (the same trade pressing Stop has
  always had); a recording already in the spool survives and drains.

Run with no arguments for the window (`Versions.vbs` points here), or from
a console:

    versions.py list
    versions.py current
    versions.py switch fast
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PYTHONW = APP_DIR / ".venv" / "Scripts" / "pythonw.exe"

# The two names a human can pick, in the order the window lists them. Any
# OTHER branch you may be standing on (master, latch-key) still switches
# OUT fine — the registry only decides what is OFFERED.
VERSIONS: dict[str, dict[str, str]] = {
    "classic": {
        "label": "Classic",
        "desc": ("Proven behavior, nothing in the cloud. Local Whisper "
                 "and the gemma3:12b repair pass, ~5 s per dictation. "
                 "Every other feature is the same as Fast: same box, "
                 "same history, same hot words."),
    },
    "fast": {
        "label": "Fast",
        "desc": ("The same app with the repair pass sent to Groq's free "
                 "API first, ~0.3-0.6 s instead of ~5 s, falling back to "
                 "the exact Classic path when it cannot. Sends your "
                 "TRANSCRIPT TEXT to Groq — never your audio. Needs "
                 "GROQ_API_KEY in .env; without one it simply runs "
                 "Classic-slow. Also adds [local] beam_size."),
    },
}

STOP_WAIT_S = 20.0        # how long to wait for a running instance to exit

# Git is a console program and this tool usually runs under pythonw, which
# has none: without CREATE_NO_WINDOW every spawned git ALLOCATES A NEW
# CONSOLE (conhost.exe) — visible flicker and hundreds of ms each, all on
# the caller's thread. Measured as the reason the dashboard's Version
# screen froze it solid.
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Branches change only through switch(), which clears these. Between
# switches the answers cannot change, and re-asking git for them was what
# made every click pay the spawn tax above.
_cache: dict = {}


class SwitchError(Exception):
    """A switch refused or failed halfway. str(e) is user-facing."""


def _git(*args: str) -> str:
    """One git command, raising SwitchError with its stderr on failure."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=APP_DIR, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
            creationflags=_CREATE_NO_WINDOW)
    except FileNotFoundError:
        raise SwitchError(
            "git was not found on PATH — the versions system needs it to "
            "flip branches. Install git (git-scm.com) and try again.")
    except subprocess.TimeoutExpired:
        raise SwitchError(f"git {' '.join(args)} timed out")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SwitchError(f"git {' '.join(args)} failed:\n{detail}")
    return proc.stdout


def current_branch() -> str:
    if "branch" not in _cache:
        out = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
        _cache["branch"] = out or "(unknown)"
    return str(_cache["branch"])


def _exists(name: str) -> bool:
    try:
        _git("show-ref", "--verify", "--quiet", f"refs/heads/{name}")
        return True
    except SwitchError:
        return False


def known_versions() -> list[str]:
    """The registry entries that actually exist as local branches.

    Cached: every caller asks for the same two names, each ask was a git
    spawn, and the answer only changes through switch() — which drops the
    cache on its way out.
    """
    if "known" not in _cache:
        _cache["known"] = [name for name in VERSIONS if _exists(name)]
    return list(_cache["known"])


def _assert_switchable() -> None:
    """Refuse unless config.toml is the ONLY dirty tracked path.

    Everything else dirty means somebody's uncommitted work is in this
    folder, and flipping branches would mix two halves of it. Refusing is
    the honest move; the message says what to do.
    """
    out = _git("status", "--porcelain")
    offenders: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if path == "config.toml":
            continue
        offenders.append(path)
    if offenders:
        raise SwitchError(
            "these files have uncommitted changes, so switching versions "
            "now could mix work from two versions:\n  "
            + "\n  ".join(offenders)
            + "\nCommit or discard them first, then switch.")


def _stop_running_instance() -> bool:
    """Ask the app to quit and wait. True if one had been running.

    The dashboard is deliberately NOT stopped: it is a separate process
    whose job is surviving the app going down, and it reconnects on its
    own once the new instance comes up.
    """
    import singleton

    if not singleton.is_running():
        return False
    if not singleton.request_quit():
        # The mutex said running but the event would not open: a stale
        # handle from an unclean shutdown. Nothing will answer a stop, and
        # equally nothing is listening to the mic — proceed, the new
        # launch's InstanceLock is what really arbitrates.
        return True
    deadline = time.monotonic() + STOP_WAIT_S
    while time.monotonic() < deadline:
        if not singleton.is_running():
            return True
        time.sleep(0.25)
    raise SwitchError(
        f"a running instance did not exit within {STOP_WAIT_S:.0f} s — "
        "nothing was changed. Stop it manually (Stop Dictation) and try "
        "again.")


def _start_instance() -> None:
    """Launch the app the way 'Hebrew Dictation.vbs' does."""
    import subprocess as sp

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(sp, "DETACHED_PROCESS", 0x00000008) | \
            getattr(sp, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    sp.Popen([str(PYTHONW), str(APP_DIR / "main.py")], cwd=str(APP_DIR),
             stdout=sp.DEVNULL, stderr=sp.DEVNULL,
             creationflags=creationflags)


def switch(target: str) -> None:
    """Flip the folder to another version. Raises SwitchError."""
    here = current_branch()
    if target == here:
        raise SwitchError(f"already on {target!r} — nothing to do")
    if not _exists(target):
        raise SwitchError(f"no version named {target!r}. Known: "
                          f"{', '.join(known_versions())}")
    _assert_switchable()

    config_path = APP_DIR / "config.toml"
    saved: bytes | None = None
    if config_path.exists():
        saved = config_path.read_bytes()

    was_running = _stop_running_instance()

    try:
        if saved is not None:
            _git("checkout", "--", "config.toml")
        _git("checkout", target)
    finally:
        # On ANY failure path the live settings go back where they were.
        if saved is not None:
            config_path.write_bytes(saved)

    print(f"switched {here!r} -> {target!r}")
    # The branch facts this module cached no longer hold. Clear BEFORE the
    # restart so the first question any window asks afterwards re-asks git.
    _cache.clear()
    if was_running:
        _start_instance()
        print("the app was running — restarted it on the new version "
              "(~25 s to load the models)")


# ------------------------------------------------------------------- CLI

def cmd_list() -> None:
    here = current_branch()
    print(f"current version: {here}")
    for name in known_versions():
        mark = " <-- current" if name == here else ""
        print(f"\n  {VERSIONS[name]['label']} ({name}){mark}")
        print(f"    {VERSIONS[name]['desc']}")


def main(argv: list[str]) -> int:
    argv = [a for a in argv if a not in ("-h", "--help")] or argv
    if argv and argv[0] == "list":
        cmd_list()
        return 0
    if argv and argv[0] == "current":
        print(current_branch())
        return 0
    if len(argv) >= 2 and argv[0] == "switch":
        try:
            switch(argv[1])
        except SwitchError as e:
            print(f"NOT switched: {e}", file=sys.stderr)
            return 1
        return 0
    if argv and argv[0] == "--gui":
        return _gui()
    print(__doc__)
    return 2


# ------------------------------------------------------------------ GUI

def _gui() -> int:
    """A small chooser window. Plain Tk on purpose: this must open even if
    half the app's own UI stack is the thing that broke."""
    import tkinter as tk

    try:
        from ui import pick_face
        face = pick_face()
    except Exception:
        face = "Segoe UI"

    names = known_versions()
    if not names:
        names = [current_branch()]

    root = tk.Tk()
    root.title("Hebrew Dictation — versions")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.configure(bg="#1e1f22")

    chosen = tk.StringVar(value=current_branch())
    status = tk.StringVar(value="")

    pad = dict(bg="#1e1f22", fg="#e8e6e3")

    tk.Label(root, text="Which version should run?", font=(face, 13, "bold"),
             **pad).pack(anchor="w", padx=18, pady=(16, 8))

    for name in names:
        info = VERSIONS.get(name, {"label": name, "desc": ""})
        row = tk.Frame(root, bg="#26272b", bd=0)
        row.pack(fill="x", padx=14, pady=4)
        tk.Radiobutton(row, text=f"{info['label']}  ({name})",
                       variable=chosen, value=name, bg="#26272b",
                       fg="#e8e6e3", selectcolor="#1e1f22",
                       activebackground="#26272b", activeforeground="#fff",
                       highlightthickness=0, font=(face, 11),
                       anchor="w").pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(row, text=info["desc"], wraplength=430, justify="left",
                 bg="#26272b", fg="#9a9891", font=(face, 9)).pack(
            fill="x", padx=26, pady=(0, 8))

    def apply() -> None:
        target = chosen.get()
        status.set(f"switching to {target}…")
        root.update()
        try:
            switch(target)
        except SwitchError as e:
            status.set(f"NOT switched — {e}")
            return
        status.set(f"done. now on {target}.")
        root.after(1200, root.destroy)

    bar = tk.Frame(root, bg="#1e1f22")
    bar.pack(fill="x", padx=18, pady=(12, 6))
    tk.Button(bar, text="Switch", command=apply, font=(face, 11),
              bg="#4c8bf5", fg="white", relief="flat", padx=18,
              cursor="hand2").pack(side="left")
    tk.Button(bar, text="Close", command=root.destroy, font=(face, 11),
              bg="#33343a", fg="#e8e6e3", relief="flat", padx=14,
              cursor="hand2").pack(side="right")
    tk.Label(root, textvariable=status, wraplength=450, justify="left",
             bg="#1e1f22", fg="#ffd479", font=(face, 9)).pack(
        fill="x", padx=18, pady=(0, 14))

    root.eval("tk::PlaceWindow . center")
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
