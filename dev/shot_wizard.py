"""Photograph every page of the first-run wizard without running it.

Runs ON the hidden desktop (tests_quiet.run_hidden wraps it, and so does
the driver below): builds firstrun.Wizard in this process against a
scratch DESKIT_HOME, shows each page in turn — the account page on its
choice, on each road and after a sign-in, the microphone page with its help shown,
the sentence page with a sample, the keys page listening for a key —
and prints the window to a PNG with the same PrintWindow the installer's
picture is taken with (shot_installer._shot). Nothing is downloaded,
written to a real home or signed in: the steps are fakes, the session
is a stub.

    python dev/shot_wizard.py --out <folder>          (on the hidden desktop)
    python dev/shot_wizard.py --out <folder> --hidden (wraps itself there)

The owner's screen never sees a window (memory: hidden desktop, every
driver and screenshot).
"""
from __future__ import annotations

import argparse
import ctypes
import dataclasses
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))


def _hidden(out: Path) -> int:
    """Run this script on the hidden desktop and wait for it."""
    import tests_quiet
    line = f'"{sys.executable}" "{Path(__file__)}" --out "{out}"'
    return tests_quiet.run_hidden(line, ROOT)


def _pages(out: Path) -> list[Path]:
    home = Path(tempfile.mkdtemp(prefix="deskit-wizard-shots-"))
    os.environ["DESKIT_HOME"] = str(home)
    import paths
    paths.SETTINGS_FILE = home / "settings.toml"
    paths.STATE_FILE = home / "state.json"
    paths.CONSENT_FILE = home / "consent.json"
    paths.SECRETS_DIR = home / "secrets"
    paths.SYNC_DIR = home / "sync"
    import config as config_mod
    import sb
    import steps
    import firstrun
    from shot_installer import _shot

    sb.REQUIRED = False
    cfg = dataclasses.replace(config_mod.load(ROOT / "defaults.toml"),
                              setup=config_mod.SetupConfig(done=False))

    class Thing:
        def __init__(self, name, size):
            self.name, self.bytes, self.repo = name, size, name

    def stepper(kind, thing):
        def work(progress, cancel, stage):
            for i in range(8):
                progress((i + 1) * thing.bytes // 8, thing.bytes)
                time.sleep(0.25)
        names = {"model": "Hebrew model", "pack": "NVIDIA libraries", "detector": "English detector",
                 "recording": "PyAV (FFmpeg)"}
        where = {"model": "huggingface.co into %LOCALAPPDATA%\\DeskIT\\models\\ivrit-ai--whisper-large-v3-turbo-ct2",
                 "pack": "pypi.org into %LOCALAPPDATA%\\DeskIT\\packs\\gpu",
                 "detector": "huggingface.co into %LOCALAPPDATA%\\DeskIT\\models\\Systran--faster-whisper-large-v3",
                 "recording": "pypi.org into %LOCALAPPDATA%\\DeskIT\\packs\\recording"}
        return steps.Step(title=kind, body=kind,
                          size_line=f"{steps.human(thing.bytes)} from {where[kind]}",
                          total=thing.bytes, work=work, name=names.get(kind, kind),
                          links=[("NVIDIA licence", "https://example.invalid")] if kind == "pack" else [])

    offers = {"portable": False, "model": Thing("m", 1_620_000_000),
              "pack": Thing("gpu", 1_370_000_000), "detector": Thing("e", 1_600_000_000),
              "recording": Thing("av", 27_556_236), "tier": "gpu"}
    facts = {"tier": "gpu", "vram_mb": 16311, "cuda_devices": 1, "driver_ok": True}

    real_user = sb.user
    sb.user = lambda: None
    w = firstrun.Wizard(cfg, facts=facts, offers=offers, stepper=stepper)
    hwnd = ctypes.windll.user32.GetParent(int(w.root.winfo_id()))
    shots: list[Path] = []

    def settle(seconds: float = 0.6) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            w.root.update()
            time.sleep(0.02)

    def shot(name: str) -> None:
        settle()
        path = out / f"{name}.png"
        _shot(hwnd, path)
        shots.append(path)
        print(f"wrote {path}")

    def show(page: str) -> None:
        w.page = firstrun.PAGES.index(page)
        w._show_page()

    try:
        show("welcome"); shot("01-welcome")
        show("account"); shot("02-account")
        w._road_to("create"); w.name_box.entry.insert(0, "Dana"); shot("02-account-create")
        w._road_to("signin"); shot("02-account-signin")
        w._road = None
        sb.user = lambda: {"email": "person@example.com", "id": "x", "is_anonymous": False,
                           "name": "Dana"}
        show("account"); shot("02-account-signed-in")
        sb.user = lambda: None
        show("mic"); shot("03-microphone")
        w._warn_silent(); shot("03-microphone-help")
        show("computer"); shot("04-computer")
        w._download(); settle(0.3); shot("04-computer-downloading")
        settle(9.5)                                # the four fakes land
        show("say"); shot("05-say")
        # the model "loaded": the button is Record from here, as it is
        # for a person after [Load the speech model]
        w._backend = object()
        w.say.configure_text(firstrun.WORDS["say.button"])
        w._on_result(firstrun.Heard(text="בדקתי את המיקרופון ושמעתי את עצמי בבירור",
                                    load_s=4.2, decode_s=0.8))
        shot("05-say-heard")
        show("keys"); shot("06-keys")
        w._rebind("punctuate_hotkey"); shot("06-keys-listening")
        w._captured(None)
        show("extras"); shot("07-extras")
        # signed in by now, as a person is: the last page carries the
        # sync row (on by default) above the two switches
        sb.user = lambda: {"email": "person@example.com", "id": "x", "is_anonymous": False}
        show("done"); shot("08-ready")
    finally:
        sb.user = real_user
        try:
            w._close()
        except Exception:                                    # noqa: BLE001
            pass
    return shots


#: The guide's eight wizard pictures (docs/README.md, chapter 2), by the
#: name each page is taken under here.
GUIDE = {"02-welcome": "01-welcome", "02-account": "02-account",
         "02-microphone": "03-microphone",
         "02-computer": "04-computer-downloading", "02-say": "05-say-heard",
         "02-keys": "06-keys", "02-extras": "07-extras", "02-done": "08-ready"}


def _guide(out: Path) -> None:
    import shutil
    for name, taken in GUIDE.items():
        shutil.copyfile(out / f"{taken}.png", ROOT / "docs" / "img" / f"{name}.png")
        print(f"guide: docs/img/{name}.png")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--hidden", action="store_true",
                    help="run on the hidden desktop (from the owner's shell)")
    ap.add_argument("--guide", action="store_true",
                    help="also refresh the guide's eight pictures in docs/img")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    if a.hidden:
        code = _hidden(a.out.resolve())
        if code == 0 and a.guide:
            _guide(a.out.resolve())
        return code
    shots = _pages(a.out)
    return 0 if shots else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
