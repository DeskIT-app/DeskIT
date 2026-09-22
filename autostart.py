"""Start with Windows — the app's own switch, not the installer's
(DISTRIBUTION_PLAN.md 10.2, D20).

One value, `DeskIT`, under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion
\\Run, holding the installed launcher command — `python\\pythonw.exe
"app\\deskit.pyw"`. Settings > General > "Start with Windows" writes or
removes it (`setup.autostart`, a state.json key: a fact about this
installation, never a setting a fresh copy inherits), and the app
re-asserts it at every start, so an install that moved or was upgraded
never leaves a Run value pointing at a path that is no longer there — a
stale autostart is the bug users report first.

NEVER IN THE CHECKOUT. The owner's copy starts from his own Startup
shortcut (wscript + DeskIT.vbs); a Run value named DeskIT from here
would start the checkout a second time on every logon, or — once the
released copy is installed beside it (D30) — the wrong one. apply()
refuses while paths.DEVELOPER and says so. Tests point RUN_KEY at a
scratch key of their own and flip DEVELOPER; nothing here may touch the
real value from a test. The stranger's copy (paths.STRANGER) writes a
key of its own that Windows never reads: the switch works, the registry
changes, nothing starts at logon.
"""
from __future__ import annotations

import logging
import winreg

import launch
import paths

log = logging.getLogger("app")

RUN_KEY = (r"Software\DeskIT.test\Run" if paths.STRANGER
           else r"Software\Microsoft\Windows\CurrentVersion\Run")
VALUE = "DeskIT"


def command() -> str:
    """The line Windows runs at logon: the windowless interpreter and the
    entry beside this file, both quoted, and `--quiet` — the dot only,
    no window; a person's own double-click on the shortcut opens the
    desk as well (main.py, 2026-09-20)."""
    return f'"{launch.pythonw()}" "{paths.APP_DIR / "deskit.pyw"}" --quiet'


def current() -> str | None:
    """What the Run value says now, or None when there is none."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, kind = winreg.QueryValueEx(key, VALUE)
            return str(value) if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) else None
    except FileNotFoundError:
        return None
    except OSError as e:
        log.info("autostart: could not read the Run value (%s)", e)
        return None


def apply(on: bool) -> bool:
    """Make the Run value say `command()` (on) or not exist (off). True
    when the registry changed. Never raises; a refusal or a registry
    error is logged and answered False."""
    if paths.DEVELOPER:
        log.info("autostart: not touched — this checkout starts from its "
                 "own shortcut, not a Run value")
        return False
    want = command() if on else None
    have = current()
    if have == want:
        return False
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if want is None:
                winreg.DeleteValue(key, VALUE)
                log.info("autostart: off — the Run value is gone")
            else:
                winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, want)
                log.info("autostart: on — Windows will start DeskIT at logon")
        return True
    except OSError as e:
        log.warning("autostart: the Run value could not be %s (%s)",
                    "written" if want else "removed", e)
        return False


def sync(cfg) -> None:
    """At start: re-assert the switch. On, the value is rewritten if the
    path moved; off, a value left behind by an older install is removed.
    Nothing happens in the checkout."""
    if paths.DEVELOPER:
        return
    on = bool(getattr(getattr(cfg, "setup", None), "autostart", False))
    if on or current() is not None:
        apply(on)
