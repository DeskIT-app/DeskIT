"""The pictures of what the door lane puts on a screen, taken off the real app on the
emulator with the real door behind it: Home, the keyboard's status line and what
waits on it, the notification.

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

        # A dictation nobody answered: why, Send again, the X.
        pc.down()
        fd.hold_and_say()
        fa.until(lambda: fd.row_is(fd.NO_ANSWER), 25)
        time.sleep(0.5)
        drive.shot("keyboard_unreached")

        # A press on its way, held at the PC, and the second no it comes back with,
        # which is the PC's reason as it is now, not the first one's.
        fd.back_up(pc)
        pc.hold.clear()
        pc.arrived.clear()
        fd.send_again()
        pc.arrived.wait(20)
        time.sleep(0.5)
        drive.shot("keyboard_sending")
        pc.fail = fd.pc_words()["MODEL_OFF_WORDS"]
        pc.hold.set()
        fa.until(lambda: fd.row_is("The model is off on your PC"), 25)
        time.sleep(0.5)
        drive.shot("keyboard_second_no")
        pc.fail = None

        # Two, and the keyboard opened later on a new field.
        pc.down()
        fd.hold_and_say()
        fa.until(lambda: fd.row_is("2 not sent · " + fd.NO_ANSWER), 25)
        time.sleep(0.5)
        drive.shot("keyboard_two_waiting")
        fa.back()
        fa.back()
        time.sleep(1)
        fd.field()
        fa.until(lambda: fd.row()["send"], 15)
        time.sleep(1)
        drive.shot("keyboard_opened_later")

        # A 320dp phone, and text one size up.
        try:
            for name, density, scale in (("320dp", "540", "1.0"), ("larger_text", "reset", "1.3"),
                                         ("320dp_larger_text", "540", "1.3")):
                drive.shell("wm", "density", density)
                drive.shell("settings", "put", "system", "font_scale", scale)
                time.sleep(3)
                fa.until(lambda: fd.row()["send"], 20)
                time.sleep(1)
                drive.shot(f"keyboard_{name}")
        finally:
            drive.shell("wm", "density", "reset", check=False)
            drive.shell("settings", "put", "system", "font_scale", "1.0", check=False)

        fa.back()
        fa.back()
        drive.kill()
        drive.home()
        drive.wait("^Can't reach the PC$", 30)
        time.sleep(0.5)
        drive.shot("home_unreached")

        # An answer in time, with the keyboard put away: the notification.
        fa.back()
        fd.field()
        fd.drop_waiting()
        fd.back_up(pc)
        pc.hold.clear()
        pc.arrived.clear()
        fd.hold_and_say()
        pc.arrived.wait(15)
        drive.shell("input", "keyevent", "4")
        drive.shell("input", "keyevent", "4")
        time.sleep(1.5)
        pc.hold.set()
        fa.until(lambda: HEBREW in drive.notifications(), 25)
        shade("said_notification")
        print("pictures in", OUT)
    finally:
        acct._door_pc.down()
        acct.stop()


if __name__ == "__main__":
    main()
