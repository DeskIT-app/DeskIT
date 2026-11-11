"""PROTOTYPE pictures, stage 2b of PHONE_LINK_PLAN.md: the cloud backup's screens and
the keyboard's line, off the real widgets on the emulator (ProtoBackupActivity and
ProbeReceiver's `proto:` hook, debug builds only). Nothing of it is the product's.

    <venv python> dev\\android\\proto_backup_shots.py OUT_DIR [--narrow]

--narrow takes them again at 320 dp with larger text, and puts the phone back after.
Nothing opens on the owner's screen: the emulator has no window.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drive  # noqa: E402

SCREENS = ["keys", "keys_none", "keys_change", "keys_remove", "welcome", "welcome_nokey",
           "home_today", "home_cloud", "home_nokey"]
BOARD = ["busy", "cloud", "nokey", "nokey_key"]


def told(what: str) -> str:
    drive.adb("logcat", "-c", check=False)
    drive.shell("am", "broadcast", "-n", f"{drive.PKG}/.ProbeReceiver", "--es", "ime", what)
    time.sleep(0.6)
    out = drive.adb("logcat", "-d", "-s", "DeskIT", check=False)
    return "\n".join(line for line in out.splitlines() if "probe:" in line)


def keyboard_up() -> None:
    ime = f"{drive.PKG}/.DictationIme"
    drive.shell("settings", "put", "secure", "show_ime_with_hard_keyboard", "1")
    drive.shell("pm", "grant", drive.PKG, "android.permission.RECORD_AUDIO", check=False)
    drive.shell("ime", "enable", ime, check=False)
    drive.shell("ime", "set", ime, check=False)
    for attempt in range(2):
        # never -S: the keyboard lives in the same package, and a force-stop puts
        # the phone back on its other keyboard
        drive.shell("ime", "set", ime, check=False)
        # a new field each time: what the last picture put in it goes with the old one
        drive.shell("am", "start", "-W", "--activity-clear-task", "-n", f"{drive.PKG}/.FieldProbe")
        end = time.time() + 15
        while time.time() < end:
            if "pill=" in told("where"):
                # past the keyboard's own first line, which goes back after three seconds
                time.sleep(3.5)
                return
            time.sleep(0.8)
        print("no keyboard yet, once more")    # Android's dead binding after an install
    raise SystemExit("the keyboard never came up")


def take(out: Path, prefix: str = "", board_only: bool = False) -> None:
    out.mkdir(parents=True, exist_ok=True)
    drive.OUT = out
    for name in ([] if board_only else SCREENS):
        # Home and the keyboard are away from home: the phone on mobile data, no Wi-Fi
        wifi(not name.startswith("home"))
        drive.shell("am", "start", "-W", "-S", "-n", f"{drive.PKG}/.ProtoBackupActivity",
                    "--es", "screen", name)
        time.sleep(1.0)
        print(drive.shot(prefix + name))
        if prefix and not name.startswith("home"):
            # the rest of a page a small phone scrolls (the narrow screen is 720x1280)
            drive.shell("input", "swipe", 360, 1100, 360, 200, 400)
            time.sleep(0.8)
            print(drive.shot(prefix + name + "_lower"))
    wifi(False)
    try:
        for name in BOARD:
            keyboard_up()
            # twice: the keyboard's own knock at open can answer after the first, and
            # off the Wi-Fi it takes a few seconds to say nobody is there
            told("proto:" + name)
            time.sleep(4)
            print(told("proto:" + name))
            time.sleep(0.5)
            print(drive.shot(prefix + "keyboard_" + name))
    finally:
        wifi(True)


def wifi(on: bool) -> None:
    drive.shell("svc", "wifi", "enable" if on else "disable", check=False)
    time.sleep(2.5)


def main() -> None:
    out = Path(sys.argv[1])
    if "--narrow" not in sys.argv:
        take(out, board_only="--board" in sys.argv)
        return
    drive.shell("wm", "size", "720x1280")
    drive.shell("wm", "density", "360")
    drive.shell("settings", "put", "system", "font_scale", "1.3")
    try:
        time.sleep(1.5)
        take(out, "narrow_", board_only="--board" in sys.argv)
    finally:
        drive.shell("settings", "put", "system", "font_scale", "1.0")
        drive.shell("wm", "density", "reset")
        drive.shell("wm", "size", "reset")


if __name__ == "__main__":
    main()
