"""The pictures of what the door lane puts on a screen, taken off the real app on the
emulator with the real door behind it: Home, the keyboard's status line, the
notification. One of them, the spool's notice, is words that are NOT in the app:
they are painted onto the real keyboard by the debug probe, for his look first.

    <venv python> dev\\android\\door_shots.py <folder>

Nothing reaches the owner's screen: the emulator has no window.
"""
import os
import sys
import time
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
OUT.mkdir(parents=True, exist_ok=True)
os.environ["DESKIT_EMU_OUT"] = str(OUT)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow_door as fd                           # noqa: E402

fa, drive = fd.fa, fd.drive
#: What a PC heard, in the language he speaks.
HEBREW = "אני בדרך הביתה, אגיע בעוד עשר דקות"
#: The spool's notice, proposed: not in strings.xml until he has seen it.
NOTICE = "No room — oldest recording deleted"


def shade(name: str) -> None:
    drive.shell("cmd", "statusbar", "expand-notifications")
    time.sleep(1.5)
    drive.shot(name)
    drive.shell("cmd", "statusbar", "collapse")
    time.sleep(0.5)


def main() -> None:
    drive.adb("install", "-r", "-g", fd.ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug"
              / "app-debug.apk", timeout=300)
    acct = fa.fresh()
    try:
        # A phone with nothing on it: the keyboard says the one thing to do first.
        drive.shell("pm", "grant", fd.PKG, "android.permission.POST_NOTIFICATIONS", check=False)
        fd.field()
        time.sleep(1)
        drive.shot("keyboard_sign_in")
        fa.back()
        fa.back()

        fd.real_join(acct)
        pc = acct._door_pc
        pc.text = HEBREW
        drive.shell("pm", "grant", fd.PKG, "android.permission.POST_NOTIFICATIONS", check=False)
        drive.kill()
        drive.home()
        drive.wait("^Connected$", 25)
        time.sleep(1)
        drive.shot("home_connected")

        fd.field()
        fd.hold_and_say()
        fa.until(lambda: HEBREW in fd.in_field(), 15)
        time.sleep(0.5)
        drive.shot("keyboard_landed")

        pc.down()
        fd.hold_and_say()
        fd.says(fd.UNREACHED)
        time.sleep(0.5)
        drive.shot("keyboard_unreached")

        fa.told("--es", "ime", "say:" + NOTICE.replace(" ", "_"))
        time.sleep(0.5)
        drive.shot("PROPOSED_keyboard_notice")

        fa.back()
        fa.back()
        drive.kill()
        drive.home()
        drive.wait("^Can't reach the PC$", 30)
        time.sleep(0.5)
        drive.shot("home_unreached")

        pc.up()
        fd.job()
        fa.until(lambda: HEBREW in drive.notifications(), 25)
        shade("said_notification")
        print("pictures in", OUT)
    finally:
        acct._door_pc.down()
        acct.stop()


if __name__ == "__main__":
    main()
