"""Walk the first-run wizard as a brand-new person — on the owner's screen,
on purpose, touching nothing of his.

On the Dev copy `main.py --setup` cannot show him most of the wizard: he
signs in with his own account, the account already holds settings, and
the wizard does what he asked for on 2026-09-20 — "Open DeskIT", every
other page skipped. So a change to those pages (the Store walk's lane 4,
2026-10-03: the "screen" page, the say page's question) had no way to be
tried by hand. This opens the REAL firstrun.Wizard with every road out
of it stubbed:

- a scratch DESKIT_HOME, deleted on exit: settings, state, consent and
  the sync folder all land there, never in the checkout;
- no account: the account page lets you past with Next (sb.REQUIRED off),
  and the Google button refuses instead of opening the browser;
- the downloads are pretend (a few seconds each), the speech model is a
  stand-in that "loads" in a second and answers every recording with the
  same sentence — the microphone is real, the transcript is not;
- a Groq key pasted on Extras is held in memory and always "works";
- Connect Claude Code, Start with Windows and the hardware probe write
  nothing.

The folders on the screen page are this PC's real Pictures and Videos
(nothing is created there unless a screenshot is saved later by the app
itself).

    .venv\\Scripts\\python.exe dev\\walk_wizard.py
"""
from __future__ import annotations

import dataclasses
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

#: What the stand-in model hears, whatever was said.
STAND_IN = "זה משפט לדוגמה: בסיור הזה המודל האמיתי לא נטען"


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="deskit-wizard-walk-"))
    os.environ["DESKIT_HOME"] = str(home)
    import paths
    paths.SETTINGS_FILE = home / "settings.toml"
    paths.STATE_FILE = home / "state.json"
    paths.CONSENT_FILE = home / "consent.json"
    paths.SECRETS_DIR = home / "secrets"
    paths.SYNC_DIR = home / "sync"
    import autostart
    import config as config_mod
    import firstrun
    import hardware
    import notify_hook
    import sb
    import secretstore
    import steps
    import transcribers

    sb.REQUIRED = False
    sb.user = lambda: None

    def no_browser(*_a, **_k):
        raise RuntimeError("not in the walk — press Next to go past the account page")
    sb.sign_in_google = no_browser
    notify_hook.hook_state = lambda *a, **k: ("none", None)
    notify_hook.install_hook = lambda *a, **k: None
    notify_hook.uninstall_hook = lambda *a, **k: None
    autostart.apply = lambda *a, **k: None
    keys: dict[str, str] = {}
    secretstore.get = lambda name, *a, **k: keys.get(name)
    secretstore.set = lambda name, value, *a, **k: keys.__setitem__(name, value)
    secretstore.delete = lambda name, *a, **k: keys.pop(name, None)

    def any_key_works():
        time.sleep(0.5)
        return 1
    firstrun.key_probe = any_key_works

    facts = {"tier": "gpu", "vram_mb": 16311, "cuda_devices": 1, "driver_ok": True}
    hardware.run_at_start = lambda *a, **k: dict(facts)

    class StandIn:
        timing = {"load_s": 1.0}

        def transcribe(self, wav, language=None):
            time.sleep(0.4)
            return STAND_IN

    def load(_cfg):
        time.sleep(1.0)
        return StandIn()
    transcribers.get_transcriber = load

    class Thing:
        def __init__(self, name, size):
            self.name, self.bytes, self.repo = name, size, name

    class Paused(Exception):
        reason = "cancelled"          # what steps.StepRun reads as Pause

    def stepper(kind, thing):
        def work(progress, cancel, stage):
            for i in range(10):
                if cancel.is_set():
                    raise Paused("paused")
                progress((i + 1) * thing.bytes // 10, thing.bytes)
                time.sleep(0.3)
        names = {"model": "Hebrew model", "pack": "NVIDIA libraries",
                 "detector": "English detector", "recording": "PyAV (FFmpeg)"}
        return steps.Step(title=names[kind], body=names[kind],
                          size_line=f"{steps.human(thing.bytes)} (pretend — nothing is downloaded)",
                          total=thing.bytes, work=work, name=names[kind])

    offers = {"portable": False, "model": Thing("m", 1_620_000_000),
              "pack": Thing("gpu", 1_370_000_000), "detector": Thing("e", 1_600_000_000),
              "recording": Thing("av", 27_556_236), "tier": "gpu"}
    cfg = dataclasses.replace(config_mod.load(ROOT / "defaults.toml"),
                              setup=config_mod.SetupConfig(done=False))
    try:
        result = firstrun.run(cfg, facts=facts, offers=offers, stepper=stepper)
        print("walked to the end" if result else "closed before Start",
              "— nothing of yours was written")
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
