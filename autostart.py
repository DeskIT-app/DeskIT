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

THE STORE COPY HAS NO RUN VALUE (DISTRIBUTION_PLAN.md 10.7). A packaged
app's HKCU writes land in the package's private hive, which Explorer
never reads, so the same switch there turns the package's startup task
on and off — `DeskITAutostart` in packaging/store/AppxManifest.xml,
which starts DeskITQuiet.exe (deskit.pyw --quiet, the Run value's own
line). Windows owns that task: nothing goes stale on an update, so it
is never re-asserted at start, and a person who turned it off in
Settings > Apps > Startup has the last word (DisabledByUser) — the app
cannot turn it back on, and says so in the log.
"""
from __future__ import annotations

import base64
import logging
import subprocess
import threading
import winreg

import launch
import paths

log = logging.getLogger("app")

RUN_KEY = (r"Software\DeskIT.test\Run" if paths.STRANGER
           else r"Software\Microsoft\Windows\CurrentVersion\Run")
VALUE = "DeskIT"

#: The package's startup task, as the manifest names it.
TASK_ID = "DeskITAutostart"
CREATE_NO_WINDOW = 0x08000000
#: How PowerShell is run; a test stands in here.
_run = subprocess.run

# Windows PowerShell 5.1 (WinRT projection; pwsh 7 has none), from inside
# the package — a child process keeps the package identity StartupTask
# needs. The AsTask dance and the type literals are visual_qa._TTS_PS's,
# for the reasons AGENTS.md's WinRT trap gives. No double quote anywhere:
# it travels as -EncodedCommand, but keep it that way.
_TASK_PS = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.ApplicationModel.StartupTask, Windows.ApplicationModel, ContentType = WindowsRuntime]
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
                   $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function AwaitOp($WinRtTask, $ResultType) {
    $netTask = $asTaskGeneric.MakeGenericMethod($ResultType).Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
$task = AwaitOp ([Windows.ApplicationModel.StartupTask]::GetAsync('TASK_ID')) ([Windows.ApplicationModel.StartupTask])
if ($want -eq 'on') {
    $state = AwaitOp ($task.RequestEnableAsync()) ([Windows.ApplicationModel.StartupTaskState])
} elseif ($want -eq 'off') {
    $task.Disable()
    $state = $task.State
} else {
    $state = $task.State
}
[Console]::Out.Write([string]$state)
""".replace("TASK_ID", TASK_ID)


def task_state(want: str = "ask", runner=None) -> str | None:
    """Ask the package's startup task to be `want` (on | off | ask) and
    answer its State word afterwards — Enabled, Disabled, DisabledByUser,
    DisabledByPolicy, EnabledByPolicy — or None when PowerShell or WinRT
    said no (outside a package: "no package identity"). About a second;
    never on a thread that answers anything."""
    if want not in ("on", "off", "ask"):
        raise ValueError(f"want is on, off or ask, not {want!r}")
    script = f"$want = '{want}'\n" + _TASK_PS
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        done = (runner or _run)(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=30,
            creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        log.info("autostart: the startup task could not be asked (%s)", e)
        return None
    word = (done.stdout or "").strip()
    if done.returncode != 0 or not word:
        log.info("autostart: the startup task answered %d (%s)",
                 done.returncode, (done.stderr or "").strip()[-200:])
        return None
    return word


def _task_apply(on: bool) -> None:
    state = task_state("on" if on else "off")
    if state is None:
        return
    if on and state == "DisabledByUser":
        log.info("autostart: Windows' Startup apps page has DeskIT off — "
                 "only the person can turn it back on there")
    else:
        log.info("autostart: the startup task is %s", state)


def _spawn(target, *args) -> None:
    """Off the caller's thread: the switch is pressed on a pipe handler
    or a Tk callback, and PowerShell takes a second. Tests call through."""
    threading.Thread(target=target, args=args, name="autostart-task",
                     daemon=True).start()


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
    error is logged and answered False. In the Store package: the
    startup task is asked, off this thread, and the answer is True —
    the request went out; what Windows made of it is in the log."""
    if paths.DEVELOPER:
        log.info("autostart: not touched — this checkout starts from its "
                 "own shortcut, not a Run value")
        return False
    if paths.PACKAGED:
        _spawn(_task_apply, bool(on))
        return True
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
    Nothing happens in the checkout, nor in the Store package, whose
    startup task Windows keeps (the docstring at the top)."""
    if paths.DEVELOPER or paths.PACKAGED:
        return
    on = bool(getattr(getattr(cfg, "setup", None), "autostart", False))
    if on or current() is not None:
        apply(on)
