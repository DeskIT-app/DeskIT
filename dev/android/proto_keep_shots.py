"""PROTOTYPE pictures: a recording kept when the keyboard closes, for the owner's yes.

    <venv python> dev\\android\\proto_keep_shots.py OUT_DIR [--cause]

Build first, as for flow_door.py: gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791

What is real: the keyboard and its views, the account (fake_pc's), the PC's door
(flow_door.Pc, the real server.py and phone.py on a test port), the waiting row, the
locked recording Continue starts, and the road a Send goes down. What is the
prototype's: the paused row itself, drawn on the live views by ProtoKeep.kt, because
no hide keeps anything yet. --cause first tries, on today's keyboard, which hides
discard a locked recording (the screen going off, the shade, Back).

Nothing opens on the owner's screen: the emulator has no window and no audio.
"""
import os
import sys
import time
from pathlib import Path

OUT = Path(sys.argv[1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
os.environ["DESKIT_EMU_OUT"] = str(OUT)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow_door as fd                           # noqa: E402

fa, drive = fd.fa, fd.drive
#: What a PC heard, in the language he speaks.
HEBREW = "אני בדרך הביתה, אגיע בעוד עשר דקות"
NOTES: dict[str, str] = {}


class LocalPc(fd.Pc):
    """The test PC, answering as his does: the line says "local", not "fake"."""

    def _transcribe(self, wav: bytes):
        text, _, warning = super()._transcribe(wav)
        return text, "local", warning


def proto(what: str) -> str:
    return fa.told("--es", "ime", "proto:" + what)


def shot(name: str) -> None:
    time.sleep(0.8)
    drive.shot(name)
    NOTES[name] = proto("measure")
    print(f"  {name}: {NOTES[name]}", flush=True)


def lock_for_real() -> None:
    """A real finger: down on the mic, up past the lock distance, and off."""
    x, y = fd.spot("pill")
    drive.shell("input", "swipe", x, y, x, y - 420, 1500)
    time.sleep(0.8)


def fresh_field() -> None:
    """The field emptied and the keyboard on it: the probe's field, started over."""
    drive.shell("am", "start", "--activity-clear-task", "-n", f"{fd.PKG}/.FieldProbe")
    assert fa.until(lambda: "pending" in fa.told("--es", "ime", "read"), 20), "no keyboard"
    assert fa.until(lambda: fd.spot("pill")[1] > 500, 15), "the keyboard is not on screen"
    time.sleep(1)


def show_again() -> None:
    """The keyboard back over the same field, as a person brings it back: a tap on the field."""
    node = drive.find("^field$") or drive.find(HEBREW)
    x, y = (node["x"], node["y"]) if node else (540, 190)
    drive.shell("input", "tap", x, y)
    assert fa.until(lambda: fd.spot("pill")[1] > 500, 15), "the keyboard did not come back"
    time.sleep(1)


def cause() -> None:
    """Which hides lose a locked recording on today's keyboard."""
    for name, hide, show in (
        ("back", lambda: fa.back(), show_again),
        ("shade", lambda: drive.shell("cmd", "statusbar", "expand-settings"),
         lambda: (drive.shell("cmd", "statusbar", "collapse"), time.sleep(1.5))),
        ("screen_off", lambda: drive.shell("input", "keyevent", "223"),
         lambda: (drive.shell("input", "keyevent", "224"), time.sleep(1),
                  drive.shell("wm", "dismiss-keyguard"), time.sleep(2), show_again())),
    ):
        fresh_field()
        lock_for_real()
        before = proto("measure")
        hide()
        time.sleep(2.5)
        show()
        time.sleep(1.5)
        after = fd.status()
        NOTES[f"cause_{name}"] = f"before: {before} || after: {after}"
        print(f"  cause {name}: {NOTES[f'cause_{name}']}", flush=True)
        shot(f"cause_{name}")
        # whatever is left of it: a tap finishes a recording still locked
        if "Locked" in proto("measure"):
            x, y = fd.spot("pill")
            drive.shell("input", "tap", x, y)
            time.sleep(3)


def retake(pc: LocalPc) -> None:
    """Two pictures a first run can miss: the line in the 3 s after the paused one lands
    with an older one waiting, and the mic's word shrunk to fit on the smallest case."""
    pc.down()
    fresh_field()
    fd.hold_and_say()
    assert fa.until(lambda: fd.row()["drop"], 30), "no waiting row"
    fd.back_up(pc)
    proto("paused:B:42:1")
    proto("send:42")
    assert fa.until(lambda: " · local" in fd.status(), 30, 0.1), "the paused one never landed"
    drive.shot("04c_sent_the_paused_one")
    fa.until(lambda: fd.row()["drop"], 10)
    time.sleep(0.5)
    shot("04d_the_older_one_is_back")
    fd.drop_waiting()
    try:
        drive.shell("wm", "density", "540")
        drive.shell("settings", "put", "system", "font_scale", "2.0")
        time.sleep(3)
        fresh_field()
        proto("paused:B:42:0:fit")
        shot("05_320dp_largest_text_B_paused_fit")
        proto("paused:B:42:1:fit")
        shot("05_320dp_largest_text_B_paused_and_waiting_fit")
    finally:
        drive.shell("wm", "density", "reset", check=False)
        drive.shell("settings", "put", "system", "font_scale", "1.0", check=False)


def main() -> None:
    drive.adb("install", "-r", "-g", fd.ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug"
              / "app-debug.apk", timeout=300)
    acct = fa.fresh()
    try:
        pc = acct._door_pc = LocalPc(acct, text=HEBREW)
        pc.up()
        fa.join(acct)
        pc.up()
        drive.kill()
        drive.home()
        drive.wait("^Connected$", 30)
        fd.field_after_install()

        if "--retake" in sys.argv:
            retake(pc)
            return
        if "--cause" in sys.argv:
            cause()

        # Today, for the record: a locked recording, the keyboard closed, and back.
        fresh_field()
        lock_for_real()
        shot("00_today_locked")
        fa.back()
        time.sleep(2)
        show_again()
        shot("00_today_discarded")

        # 1. The keyboard comes back with the recording kept: both arrangements.
        fresh_field()
        for arr in ("B", "A"):
            proto(f"paused:{arr}:42")
            shot(f"01_{arr}_paused")

        # 2. Continue: the real recorder, locked, its clock going on from 0:42.
        proto("continue:42")
        time.sleep(1.6)
        shot("02_continue_locked")
        # ...and the tap that finishes it: the whole of it down the real road.
        x, y = fd.spot("pill")
        drive.shell("input", "tap", x, y)
        fa.until(lambda: HEBREW in fd.in_field(), 30)
        time.sleep(0.5)
        shot("02b_continue_then_finished")

        # 3. Send from the paused row: the normal road, the normal line.
        fresh_field()
        proto("paused:B:42")
        proto("send:42")
        time.sleep(0.15)
        drive.shot("03a_send_transcribing")
        fa.until(lambda: HEBREW in fd.in_field(), 30)
        time.sleep(0.5)
        shot("03_after_send")

        # 4. An older recording already waiting (a real one: the PC down), then the paused one.
        pc.down()
        fresh_field()
        fd.hold_and_say()
        fa.until(lambda: fd.row()["drop"], 30)
        time.sleep(0.5)
        shot("04_waiting_today")
        for arr in ("B", "A"):
            proto(f"paused:{arr}:42:1")
            shot(f"04_{arr}_paused_and_waiting")
        # Send the paused one with the PC back: it lands, and the older one's row is back.
        fd.back_up(pc)
        proto("paused:B:42:1")
        proto("send:42")
        fa.until(lambda: HEBREW in fd.in_field(), 30)
        time.sleep(0.5)
        shot("04c_sent_the_paused_one")
        fa.until(lambda: fd.row()["drop"], 10)
        time.sleep(0.5)
        shot("04d_the_older_one_is_back")
        fd.drop_waiting()
        time.sleep(1)

        # 5-7. A 320 dp phone, the largest text, and both.
        try:
            for name, density, scale in (("320dp", "540", "1.0"), ("largest_text", "reset", "2.0"),
                                         ("320dp_largest_text", "540", "2.0")):
                drive.shell("wm", "density", density)
                drive.shell("settings", "put", "system", "font_scale", scale)
                time.sleep(3)
                fresh_field()
                for arr in ("B", "A"):
                    proto(f"paused:{arr}:42")
                    shot(f"05_{name}_{arr}_paused")
                    proto(f"paused:{arr}:42:1")
                    shot(f"05_{name}_{arr}_paused_and_waiting")
                proto("continue:42")
                time.sleep(1.6)
                shot(f"05_{name}_continue_locked")
                x, y = fd.spot("pill")
                drive.shell("input", "tap", x, y)
                fa.until(lambda: HEBREW in fd.in_field(), 30)
                time.sleep(0.5)
        finally:
            drive.shell("wm", "density", "reset", check=False)
            drive.shell("settings", "put", "system", "font_scale", "1.0", check=False)
    finally:
        try:
            acct._door_pc.down()
        except Exception:                        # noqa: BLE001
            pass
        acct.stop()
        (OUT / ("measure-retake.txt" if "--retake" in sys.argv else "measure.txt")).write_text("\n".join(f"{k}: {v}" for k, v in NOTES.items()) + "\n",
                                         "utf-8")


if __name__ == "__main__":
    main()
