"""A prototype of "DeskIT is on this PC twice" — photographed, never wired.

The owner's rule of 2026-10-04: the website's, winget's and the Store's
DeskIT are one app, never two on one PC (onecopy.py says what two copies
share, measured). Anything on screen gets a picture and his OK first, so
this draws the window the app would open at start when onecopy.other_copy()
finds the other one — from fake facts, in a scratch DESKIT_HOME — and
prints it to PNGs with the PrintWindow the installer's pictures use
(shot_installer._shot). Nothing is detected, uninstalled or opened.

    python dev/proto_one_copy.py --out <folder>          (on the hidden desktop)
    python dev/proto_one_copy.py --out <folder> --hidden (wraps itself there)

Three pictures: the window as the Store copy opens it (it found the
website copy), as the website copy opens it (it found the Store copy), and
the website copy waiting for Windows to remove DeskIT App after "Keep
this one" on its own card.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

W = 640
PAD = 28
INNER = W - 2 * PAD

WORDS = {
    "title": "DeskIT is on this PC twice",
    "why": ("Once from the website and once from the Microsoft Store. One PC "
            "keeps one DeskIT: two would share some settings and the cloud "
            "keys, and only one can run at a time. Choose the one to keep."),
    "keep": "Keep this one",
    "this": "This one",
    "quit": "Quit",
    "foot": "DeskIT starts once one is left.",
    "store.facts": "{version}  ·  updated by the Microsoft Store",
    "website.facts": "{version}  ·  {folder}",
    # what happens to the OTHER one, said under the card that keeps this one
    "store.keep.from_store": ("Uninstalls the website copy. Its settings, "
                              "history and model stay on this PC."),
    "store.keep.from_website": ("Uninstalls this copy and opens DeskIT App. "
                                "Settings, history and the model stay on this PC."),
    "website.keep.from_store": ("Opens Windows Settings at DeskIT App, where you "
                                "press Uninstall. What it kept only on this PC "
                                "goes with it; synced words and settings come "
                                "back from your account."),
    "website.keep.from_website": ("Opens Windows Settings at DeskIT App, where you "
                                  "press Uninstall. What it kept only on this PC "
                                  "goes with it; synced words and settings come "
                                  "back from your account."),
    "waiting.title": "Waiting for Windows to remove DeskIT App",
    "waiting.line": ("In Settings, press Uninstall under DeskIT App. "
                     "DeskIT starts by itself once it is gone."),
    "waiting.again": "Open Settings again",
}


def _silence() -> None:
    """No sound from a driver (AGENTS.md rule 8): before any app import."""
    import winsound
    winsound.PlaySound = lambda *a, **k: None
    winsound.Beep = lambda *a, **k: None
    import tkinter as tk
    tk.Misc.bell = lambda *a, **k: None


def _hidden(out: Path) -> int:
    import tests_quiet
    line = f'"{sys.executable}" -B "{Path(__file__)}" --out "{out}"'
    return tests_quiet.run_hidden(line, ROOT)


class Window:
    """The window: the mark and the name, a title, one paragraph, a card per
    copy with its own Keep button, Quit at the foot. One gold button — the
    recommended keep — and the other plain (LAMPLIGHT rule 1)."""

    def __init__(self, ui, firstrun, here: str, copies: dict, recommended: str):
        import tkinter as tk
        self.tk, self.ui, self.firstrun = tk, ui, firstrun
        self.root = tk.Tk()
        self.root.title("DeskIT")
        self.root.configure(bg=ui.BG)
        self.root.resizable(False, False)
        try:
            self.root.iconbitmap(default=str(ROOT / "icon.ico"))
        except tk.TclError:
            pass
        self.body = tk.Frame(self.root, bg=ui.BG)
        self.body.pack(fill="both", expand=True, padx=PAD, pady=(PAD, 0))
        self.foot = tk.Frame(self.root, bg=ui.BG)
        self.foot.pack(side="bottom", fill="x", padx=PAD, pady=(18, PAD))
        self.here, self.copies, self.recommended = here, copies, recommended

    def _head(self, title: str, line: str) -> None:
        tk, ui = self.tk, self.ui
        row = tk.Frame(self.body, bg=ui.BG)
        row.pack(fill="x")
        mark = ui.icon_bitmap(ROOT / "icon.png", 20, ui.BG)
        if mark is not None:
            badge = tk.Label(row, image=mark, bg=ui.BG)
            badge.photo = mark
            badge.pack(side="left", padx=(0, 8))
        tk.Label(row, text="DeskIT", bg=ui.BG, fg=ui.DIM,
                 font=(ui.MEDIUM, 9)).pack(side="left")
        tk.Label(self.body, text=title, bg=ui.BG, fg=ui.FG,
                 font=(ui.DISPLAY, 18), anchor="w").pack(fill="x", pady=(16, 6))
        tk.Label(self.body, text=line, bg=ui.BG, fg=ui.DIM, font=(ui.UI, 10),
                 anchor="w", justify="left", wraplength=INNER
                 ).pack(fill="x", pady=(0, 18))

    def _card(self, kind: str) -> None:
        tk, ui = self.tk, self.ui
        copy = self.copies[kind]
        card = ui.Card(self.body, INNER, 41, bg=ui.BG, pad=18)
        card.pack(fill="x", pady=(0, 12))
        top = tk.Frame(card.body, bg=ui.CARD)
        top.pack(fill="x")
        words = tk.Frame(top, bg=ui.CARD)
        words.pack(side="left", fill="x", expand=True)
        name = tk.Frame(words, bg=ui.CARD)
        name.pack(fill="x")
        tk.Label(name, text=copy["name"], bg=ui.CARD, fg=ui.FG,
                 font=(ui.UI, 12), anchor="w").pack(side="left")
        if kind == self.here:
            # DIM, not the accent: the gold Keep is this surface's one lamp
            tk.Label(name, text=WORDS["this"], bg=ui.CARD, fg=ui.DIM,
                     font=(ui.UI, 9)).pack(side="left", padx=(10, 0))
        tk.Label(words, text=WORDS[f"{kind}.facts"].format(**copy), bg=ui.CARD,
                 fg=ui.FAINT, font=(ui.UI, 9), anchor="w").pack(fill="x", pady=(2, 0))
        ui.Button(top, WORDS["keep"], None, bg=ui.CARD, w=140,
                  primary=(kind == self.recommended)).pack(side="right", anchor="n")
        tk.Label(card.body, text=WORDS[f"{kind}.keep.from_{self.here}"], bg=ui.CARD,
                 fg=ui.DIM, font=(ui.UI, 9), anchor="w", justify="left",
                 wraplength=INNER - 40).pack(fill="x", pady=(12, 0))
        card.body.update_idletasks()
        card.resize(card.body.winfo_reqheight() + 36)

    def choose(self) -> None:
        tk, ui = self.tk, self.ui
        self._head(WORDS["title"], WORDS["why"])
        for kind in (self.recommended, *[k for k in self.copies if k != self.recommended]):
            self._card(kind)
        ui.Button(self.foot, WORDS["quit"], None, bg=ui.BG, quiet=True,
                  w=96).pack(side="right")
        tk.Label(self.foot, text=WORDS["foot"], bg=ui.BG, fg=ui.FAINT,
                 font=(ui.UI, 9), anchor="w").pack(side="left")
        self._show()

    def waiting(self) -> None:
        tk, ui = self.tk, self.ui
        self._head(WORDS["waiting.title"], WORDS["waiting.line"])
        bar = tk.Canvas(self.body, width=INNER, height=4, bg=ui.BG,
                        highlightthickness=0, bd=0)
        bar.pack(fill="x", pady=(0, 8))
        bar.create_rectangle(0, 0, INNER, 4, fill=ui.LINE, outline="")
        bar.create_rectangle(INNER * 0.30, 0, INNER * 0.52, 4, fill=ui.ACCENT, outline="")
        ui.Button(self.foot, WORDS["quit"], None, bg=ui.BG, quiet=True,
                  w=96).pack(side="right")
        ui.Button(self.foot, WORDS["waiting.again"], None, bg=ui.BG,
                  w=190).pack(side="right", padx=(0, 10))
        self._show()

    def _show(self) -> None:
        self.root.update_idletasks()
        h = self.root.winfo_reqheight()
        self.root.geometry(f"{W}x{h}+200+120")
        self.firstrun._caption(self.root)
        self.root.update()


def _pictures(out: Path) -> list[Path]:
    home = Path(tempfile.mkdtemp(prefix="deskit-onecopy-proto-"))
    os.environ["DESKIT_HOME"] = str(home)
    _silence()
    import ui
    import firstrun
    from shot_installer import _shot
    import ctypes
    firstrun._lamplight()
    copies = {
        "store": {"name": "DeskIT App, from the Microsoft Store", "version": "1.0.6"},
        "website": {"name": "DeskIT, from the website", "version": "1.0.7",
                    "folder": r"%LOCALAPPDATA%\Programs\DeskIT"},
    }
    shots = []
    for name, here, mode in (("from-store", "store", "choose"),
                             ("from-website", "website", "choose"),
                             ("website-waiting", "website", "waiting")):
        ui.forget_images()
        win = Window(ui, firstrun, here, copies, recommended="store")
        getattr(win, mode)()
        time.sleep(0.6)
        win.root.update()
        hwnd = ctypes.windll.user32.GetParent(int(win.root.winfo_id()))
        path = out / f"one-copy-{name}.png"
        _shot(hwnd, path)
        shots.append(path)
        win.root.destroy()
    return shots


def _dialog_of(pid_hint: int) -> int:
    """The task dialog Setup put up: the only #32770 window on the hidden
    desktop (Inno's wizard runs in a CHILD process, so not by pid)."""
    import ctypes
    from ctypes import wintypes as w
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def each(hwnd, _):
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, cls, 64)
        if u.IsWindowVisible(hwnd) and cls.value == "#32770":
            found.append(hwnd)
        return True
    u.EnumWindows(each, 0)
    return found[0] if found else 0


def _installer(exe: Path, out: Path) -> list[Path]:
    """Photograph dev/proto_one_copy_setup.iss's two dialogs, English and
    Hebrew. Setup is ended by PID once photographed — it installs
    nothing, and a task dialog with only custom buttons takes no WM_CLOSE."""
    import ctypes
    import subprocess
    from ctypes import wintypes as w
    from shot_installer import _shot
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    shots = []
    for name, extra in (("installer-en", []), ("installer-he", ["/LANG=hebrew"]),
                        ("installer-wait-en", ["/SHOW=wait"]),
                        ("installer-wait-he", ["/SHOW=wait", "/LANG=hebrew"])):
        p = subprocess.Popen([str(exe), *extra])
        hwnd = 0
        for _ in range(200):
            hwnd = _dialog_of(p.pid)
            if hwnd:
                break
            time.sleep(0.1)
        if not hwnd:
            p.kill()
            print(f"{name}: no dialog")
            continue
        time.sleep(1.0)
        path = out / f"one-copy-{name}.png"
        _shot(hwnd, path)
        # PrintWindow hands back a right-to-left window's pixels mirrored
        # (WS_EX_LAYOUTRTL, the Hebrew dialog): flipped back, it is what
        # the screen shows
        if u.GetWindowLongW(hwnd, -20) & 0x00400000:
            from PIL import Image, ImageOps
            ImageOps.mirror(Image.open(path)).save(path)
        shots.append(path)
        owner = w.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        handle = k.OpenProcess(0x0001, False, owner.value)      # PROCESS_TERMINATE
        if handle:
            k.TerminateProcess(handle, 0)
            k.CloseHandle(handle)
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    return shots


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--hidden", action="store_true")
    parser.add_argument("--installer", help="the compiled proto_one_copy_setup.iss")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.hidden:
        if args.installer:
            import tests_quiet
            line = (f'"{sys.executable}" -B "{Path(__file__)}" --out "{out}" '
                    f'--installer "{Path(args.installer).resolve()}"')
            return tests_quiet.run_hidden(line, ROOT)
        return _hidden(out)
    if args.installer:
        paths_out = _installer(Path(args.installer), out)
    else:
        paths_out = _pictures(out)
    for path in paths_out:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
