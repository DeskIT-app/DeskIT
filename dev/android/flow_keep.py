"""A recording the keyboard closed on, on the emulator, flow by flow (2026-11-12): kept at
every hide, offered as Continue / Send / X wherever the keyboard opens next, continued
whole, sent down every road, deleted, and gone at its hour.

    <venv python> dev\\android\\flow_keep.py [name ...]
    <venv python> dev\\android\\flow_keep.py --shots DIR      the real row, photographed

Build first, for the fake account AND the fake provider, as for flow_relay.py:
gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791 -PdeskitCloud=http://10.0.2.2:18793

What is real: the whole keyboard (its recorder, its hide, the paused file, the spool, its
roads), the PC's door (flow_door.Pc), the PC's relay (flow_relay.RelayPc), and the
provider's one request (fake_cloud). The emulator's microphone hears nothing, so a
recording is given its loudness by the debug probe, as every flow here does.
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flow_door as fd                            # noqa: E402  (sets DESKIT_HOME and DESKIT_SUITE)
import flow_relay as fr                           # noqa: E402
import flow_backup as fb                          # noqa: E402

import drive                                      # noqa: E402

fa = fd.fa
check, until = fd.check, fd.until
PKG = drive.PKG
SENTENCE = fd.SENTENCE
#: The paused row's words, as strings.xml has them.
PAUSED = "Recording paused"


# ------------------------------------------------------------------ helpers

def st() -> dict:
    """The keyboard as the probe reads it: the line, the keys, and the mic."""
    raw = fd.status()
    def word(name: str) -> str:
        m = re.search(rf"\b{name}=(\S*)", raw)
        return m.group(1) if m else ""
    r = fd.row()
    r.update(kept=word("kept") == "true", locked=word("locked") == "true",
             screen_on=word("screen_on") == "true",
             mic_text=re.sub(r"\s+", " ", word("mic_text").replace("_", " ")),
             mic_cut=word("mic_cut") == "true", raw=raw)
    return r


def spool() -> dict:
    out = fd.spooled()
    nums = {k: int(v) for k, v in re.findall(r"(\w+)=(-?\d+)", out)}
    return {"waiting": nums.get("waiting", -1), "all": nums.get("all", -1), "paused": nums.get("paused", -1),
            "raw": out}


def loud() -> None:
    drive.shell("am", "broadcast", "--receiver-foreground", "-n", f"{PKG}/.ProbeReceiver",
                "--es", "ime", "loud", timeout=60)


def lock(seconds: float = 3.0) -> None:
    """A real finger: down on the mic, up past the lock distance, off; then the voice the
    emulator has not got, and [seconds] of recording."""
    x, y = fd.spot("pill")
    drive.shell("input", "swipe", x, y, x, y - 420, 1200)
    assert until(lambda: st()["locked"], 10), f"the recording never locked: {fd.status()}"
    loud()
    time.sleep(max(0.0, seconds - 1.0))


def tap(name: str) -> None:
    x, y = fd.spot(name)
    drive.shell("input", "tap", x, y)


def hide() -> None:
    """The keyboard closed, as Back closes it: onFinishInputView, the road every hide takes."""
    fa.back()
    time.sleep(1.5)


def show_again() -> None:
    """The keyboard back over the field, as a person brings it back: a tap on the field."""
    node = drive.find("^field$") or drive.find(SENTENCE) or drive.find(fr.RELAYED) or drive.find(fb.HEARD)
    x, y = (node["x"], node["y"]) if node else (540, 190)
    drive.shell("input", "tap", x, y)
    assert until(lambda: fd.spot("pill")[1] > 500, 15), "the keyboard did not come back"
    time.sleep(1)


def fresh_field() -> None:
    """The field emptied and the keyboard on it, in the same process (-S would stop it)."""
    drive.shell("am", "start", "--activity-clear-task", "-n", f"{PKG}/.FieldProbe")
    assert until(lambda: "pending" in fa.told("--es", "ime", "read"), 20), "no keyboard"
    assert until(lambda: fd.spot("pill")[1] > 500, 15), "the keyboard is not on screen"
    time.sleep(1)


def offered(seconds_at_least: int = 1) -> bool:
    """The paused row is up: the line's words, Send and the X, the mic Continue and its length."""
    s = st()
    m = re.match(r"Continue (\d+):(\d\d)", s["mic_text"])
    return (s["status"].startswith(PAUSED) and s["send"] and s["drop"] and s["kept"] and m is not None
            and int(m.group(1)) * 60 + int(m.group(2)) >= seconds_at_least)


def kept_seconds() -> int:
    m = re.match(r"Continue (\d+):(\d\d)", st()["mic_text"])
    return int(m.group(1)) * 60 + int(m.group(2)) if m else -1


def window_keeps_screen_on() -> bool:
    """Android's own word on it: the keyboard's window carries KEEP_SCREEN_ON."""
    out = drive.shell("dumpsys", "window", "windows", check=False)
    blocks = re.split(r"\n  Window #", out)
    return any("InputMethod" in b.split("\n", 1)[0] and "KEEP_SCREEN_ON" in b for b in blocks)


def joined(text: str = SENTENCE):
    acct = fa.fresh()
    fd.real_join(acct)
    acct._door_pc.text = text
    return acct


def wav_seconds(wav: bytes) -> float:
    return fb.wav_seconds(len(wav))


# ------------------------------------------------------------------ the flows

def flow_hide_mid_lock():
    """A locked recording, the keyboard closed: the mic stops at once, what was said is
    kept on the disk, the row is offered when the keyboard is back, and Send lands it."""
    acct = joined()
    try:
        pc = acct._door_pc
        fd.field()
        lock(4)
        s = st()
        check("while it records, the screen is held on", s["screen_on"] and window_keeps_screen_on(), s["raw"])
        hide()
        sp = spool()
        check("the hide keeps it on the disk, about as long as it ran",
              until(lambda: spool()["paused"] >= 3, 10), str(sp))
        check("and it is not a waiting row: nothing tried to send it", spool()["waiting"] == 0, str(spool()))
        check("nothing was sent", not pc.heard)
        show_again()
        check("back: the row is offered, the mic is Continue and its length",
              until(lambda: offered(3), 10), st()["raw"])
        check("and the screen is not held on any more", not st()["screen_on"] and not window_keeps_screen_on())
        tap("sendKey")
        check("Send: the text lands in the field", until(lambda: SENTENCE in fd.in_field(), 30), fd.in_field()[:200])
        check("the PC heard it once, whole", len(pc.heard) == 1 and wav_seconds(pc.heard[0]) >= 3,
              f"{len(pc.heard)} {[wav_seconds(w) for w in pc.heard]}")
        check("the line is the normal line", fd.says(r"\d+\.\d s · fake", 10), fd.status())
        check("nothing is left on the disk", until(lambda: spool()["all"] == 0, 10), str(spool()))
        check("and the mic is the mic again", until(lambda: st()["mic_text"] == "Hold & talk", 10), st()["raw"])
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_hide_mid_hold():
    """A held recording, the finger still down, the keyboard closed under it: kept the same
    way, and the X deletes it, nothing sent."""
    acct = joined()
    try:
        pc = acct._door_pc
        fd.field()
        x, y = fd.spot("pill")
        finger = threading.Thread(target=lambda: drive.shell(
            "input", "swipe", x, y, x, y, 7000, check=False))
        finger.start()
        time.sleep(0.8)
        loud()
        time.sleep(2.5)
        hide()
        finger.join()
        check("kept, though the finger was still on the mic", until(lambda: spool()["paused"] >= 2, 10),
              str(spool()))
        show_again()
        check("offered on the way back", until(lambda: offered(2), 10), st()["raw"])
        tap("dropKey")
        check("the X deletes it at once", until(lambda: spool()["all"] == 0, 5), str(spool()))
        check("the row goes, the mic is the mic", until(lambda: not st()["drop"] and
                                                         st()["mic_text"] == "Hold & talk", 5), st()["raw"])
        check("and nothing was sent", not pc.heard)
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_screen_off():
    """The screen off in the middle of a locked recording (his one-minute loss, it seems):
    kept, and offered once the phone is unlocked."""
    acct = joined()
    try:
        fd.field()
        lock(3)
        drive.shell("input", "keyevent", "223")          # sleep
        time.sleep(3)
        drive.shell("input", "keyevent", "224")          # wake
        time.sleep(1)
        drive.shell("wm", "dismiss-keyguard")
        time.sleep(2)
        check("the screen off kept it", until(lambda: spool()["paused"] >= 2, 10), str(spool()))
        show_again()
        check("offered once the phone is back", until(lambda: offered(2), 10), st()["raw"])
        tap("dropKey")
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_continue():
    """Continue goes on from the kept length, locked; a second hide keeps the longer one;
    the finish sends the whole of it and ends the paused file."""
    acct = joined()
    try:
        pc = acct._door_pc
        fd.field()
        lock(3)
        hide()
        show_again()
        assert until(lambda: offered(3), 10), st()["raw"]
        first = kept_seconds()
        tap("pill")
        check("Continue: locked again, the clock from the kept length",
              until(lambda: st()["locked"] and re.match(r"Locked \d+:\d\d", st()["mic_text"]) is not None, 5),
              st()["raw"])
        m = re.match(r"Locked (\d+):(\d\d)", st()["mic_text"])
        check("and never from zero", m is not None and int(m.group(1)) * 60 + int(m.group(2)) >= first,
              st()["mic_text"])
        check("the screen is held on again", st()["screen_on"] and window_keeps_screen_on())
        time.sleep(3)
        hide()
        check("a second hide keeps the longer recording", until(lambda: spool()["paused"] >= first + 2, 10),
              str(spool()))
        show_again()
        assert until(lambda: offered(first + 2), 10), st()["raw"]
        whole = kept_seconds()
        tap("pill")
        assert until(lambda: st()["locked"], 5), st()["raw"]
        time.sleep(2)
        tap("pill")                                       # tap to finish
        check("the finish lands it", until(lambda: SENTENCE in fd.in_field(), 30), fd.in_field()[:200])
        check("the PC heard the whole of it, once",
              len(pc.heard) == 1 and wav_seconds(pc.heard[0]) >= whole + 1.5,
              f"{len(pc.heard)} {[round(wav_seconds(w), 1) for w in pc.heard]} vs {whole}")
        check("and the paused file went with it", until(lambda: spool()["all"] == 0, 10), str(spool()))
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_discard_continued():
    """Continue, then the discard: the whole recording goes, the part before the hide too."""
    acct = joined()
    try:
        pc = acct._door_pc
        fd.field()
        lock(3)
        hide()
        show_again()
        assert until(lambda: offered(2), 10), st()["raw"]
        tap("pill")
        assert until(lambda: st()["locked"], 5), st()["raw"]
        tap("backspace")                                  # ✕ while locked
        check("the discard takes all of it", until(lambda: spool()["all"] == 0 and not st()["kept"], 5),
              f"{spool()} {st()['raw']}")
        check("nothing was sent", not pc.heard)
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_send_waits():
    """Send with no road at all: it becomes an ordinary waiting row, and Send again lands it."""
    acct = joined()
    try:
        pc = acct._door_pc
        fd.field()
        lock(3)
        hide()
        pc.down()
        show_again()
        assert until(lambda: offered(2), 10), st()["raw"]
        tap("sendKey")
        check("nobody answered: it waits, as any recording waits",
              until(lambda: fd.row_is(fd.NO_ANSWER), 30), st()["raw"])
        check("on the disk as a waiting one, the paused slot empty",
              spool()["waiting"] == 1 and spool()["paused"] == -1, str(spool()))
        check("the mic is the mic again", st()["mic_text"] == "Hold & talk", st()["raw"])
        fd.back_up(pc)
        fd.send_again()
        check("Send again lands it", until(lambda: SENTENCE in fd.in_field(), 30), fd.in_field()[:200])
        check("nothing left", until(lambda: spool()["all"] == 0, 10), str(spool()))
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_older_waiting():
    """An older recording already waiting, then one paused: the paused one has the line
    and names the older; sent, the older one's row is back, and it was not sent."""
    acct = joined()
    try:
        pc = acct._door_pc
        pc.down()
        fd.field()
        fd.hold_and_say()
        assert until(lambda: fd.row_is(fd.NO_ANSWER), 30), st()["raw"]
        fd.back_up(pc)
        lock(3)
        hide()
        show_again()
        check("the paused one first, the older one named",
              until(lambda: st()["status"] == "Recording paused · 1 older not sent" and offered(2), 10),
              st()["raw"])
        tap("sendKey")
        check("Send lands the paused one", until(lambda: SENTENCE in fd.in_field(), 30), fd.in_field()[:200])
        check("and only it", len(pc.heard) == 1, str(len(pc.heard)))
        check("the older one's row comes back, Send again and all",
              until(lambda: fd.row()["send"] and fd.row()["drop"] and "Not sent" in fd.row()["status"], 10),
              st()["raw"])
        fd.drop_waiting()
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_private_field():
    """A password field: the row is not offered there, the mic is not Continue, and the
    recording waits for the next ordinary field."""
    acct = joined()
    try:
        fd.field()
        lock(3)
        hide()
        fd.private_field()
        s = st()
        check("not offered in a private field", not s["kept"] and not s["drop"] and s["mic_text"] == "Hold & talk",
              s["raw"])
        check("and still kept", spool()["paused"] >= 2, str(spool()))
        fresh_field()
        check("back in an ordinary field, offered", until(lambda: offered(2), 10), st()["raw"])
        tap("dropKey")
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_killed_while_paused():
    """The keyboard's process killed while hidden: the disk has it, the next keyboard offers it."""
    acct = joined()
    try:
        pc = acct._door_pc
        fd.field()
        lock(4)
        hide()
        assert until(lambda: spool()["paused"] >= 3, 10), str(spool())
        fa.back()
        drive.kill()
        time.sleep(1)
        fd.field_after_install()
        check("a new process offers it, the same length", until(lambda: offered(3), 15), st()["raw"])
        tap("sendKey")
        check("and Send lands it", until(lambda: SENTENCE in fd.in_field(), 30), fd.in_field()[:200])
        check("whole", len(pc.heard) == 1 and wav_seconds(pc.heard[0]) >= 3, str(len(pc.heard)))
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_upgrade():
    """This build installed over itself with a recording paused, as an update installs: kept."""
    acct = joined()
    try:
        pc = acct._door_pc
        fd.field()
        lock(3)
        hide()
        assert until(lambda: spool()["paused"] >= 2, 10), str(spool())
        fa.back()
        drive.adb("install", "-r", "-g", fd.APK, timeout=300)
        fd.field_after_install()
        check("after the update it is offered", until(lambda: offered(2), 20), st()["raw"])
        tap("sendKey")
        check("and Send lands it", until(lambda: SENTENCE in fd.in_field(), 30), fd.in_field()[:200])
        check("once", len(pc.heard) == 1, str(len(pc.heard)))
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_the_hour():
    """Its hour, from the pause: 61 minutes old goes, by the sweep and by the next open;
    50 minutes old is still offered. The sweep sends nothing."""
    acct = joined()
    try:
        pc = acct._door_pc
        fd.field()
        lock(3)
        hide()
        assert until(lambda: spool()["paused"] >= 2, 10), str(spool())
        fa.back()
        drive.kill()                                      # this process's copy gone: the disk alone
        now = fa.phone_ms()
        name = [n for n in fa.recordings().split() if n.startswith("paused-")][0]
        fresh = f"paused-{now - 50 * 60_000:013d}.wav"
        drive.as_app("mv", f"files/spool/{name}", f"files/spool/{fresh}")
        fd.field_after_install()
        check("fifty minutes old: still offered", until(lambda: offered(2), 15), st()["raw"])
        fa.back()
        fa.back()
        drive.kill()
        old = f"paused-{now - 61 * 60_000:013d}.wav"
        drive.as_app("mv", f"files/spool/{fresh}", f"files/spool/{old}")
        fd.ask("sweep")
        fa.log_forget()
        fd.job()
        check("past its hour the sweep takes it", until(lambda: old not in fa.recordings(), 15), fa.recordings())
        check("and the sweep sent nothing", not pc.heard)
        drive.as_app("sh", "-c", f"'dd if=/dev/zero of=files/spool/{old} bs=32044 count=3 2>/dev/null'")
        drive.kill()
        fd.field_after_install()
        check("a keyboard opening takes one past its hour too, and offers nothing",
              until(lambda: old not in fa.recordings(), 10) and not st()["kept"], fa.recordings())
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_cap_counts_whole():
    """The five-minute cap counts the whole recording: kept at 4:59, Continue reaches the
    cap within a second and sends what there is."""
    acct = joined()
    try:
        pc = acct._door_pc
        now = fa.phone_ms()
        drive.as_app("mkdir", "-p", "files/spool")
        name = f"paused-{now:013d}.wav"
        # a WAV of 4:59 of silence: its header, then 299 s of zeros
        drive.as_app("sh", "-c", f"'dd if=/dev/zero of=files/spool/{name} bs=32000 count=299 2>/dev/null; "
                                 f"dd if=/dev/zero bs=44 count=1 2>/dev/null >> files/spool/{name}'")
        fd.field()
        check("offered at 4:59", until(lambda: st()["mic_text"] == "Continue 4:59", 15), st()["raw"])
        tap("pill")
        check("Continue hits the cap within seconds, and sends what there is",
              until(lambda: "limit" in st()["status"] or SENTENCE in fd.in_field(), 15), st()["raw"])
        check("the whole of it reached the PC, five minutes", until(lambda: pc.heard, 30) and
              299 <= wav_seconds(pc.heard[0]) <= 301, str([round(wav_seconds(w), 1) for w in pc.heard]))
        check("nothing left", until(lambda: spool()["all"] == 0, 10), str(spool()))
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_send_relay():
    """Away from home, the PC there through the account: Send goes by the relay."""
    acct = fa.fresh(backup="on")
    cloud = fb.cloud_up()
    pc = None
    try:
        acct.put_key("groq", fb.KEY)
        fd.real_join(acct)
        fb.away(acct._door_pc)
        pc = fr.RelayPc(acct).up()
        fd.field()
        assert until(fr.keyboard_sees_pc, 20), fd.status()
        lock(3)
        hide()
        show_again()
        assert until(lambda: offered(2), 10), st()["raw"]
        tap("sendKey")
        check("Send away from home: the PC's text, through the account",
              until(lambda: fr.RELAYED in fd.in_field(), 40), fd.in_field()[:200])
        check("the line says so", fd.says(fr.VIA, 10), fd.status())
        check("the PC heard it whole", len(pc.heard) == 1 and wav_seconds(pc.heard[0]) >= 2, str(len(pc.heard)))
        check("the cloud was not asked", cloud.asked() == [], str(cloud.asked()))
        check("nothing left", until(lambda: spool()["all"] == 0, 10), str(spool()))
    finally:
        if pc is not None:
            pc.down()
        fb.home_again()
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


def flow_send_cloud():
    """Away from home, no PC anywhere, a key: Send goes to the cloud, the line says so."""
    acct = fa.fresh(backup="on")
    cloud = fb.cloud_up()
    try:
        acct.put_key("groq", fb.KEY)
        fd.real_join(acct)
        fb.away(acct._door_pc)
        fd.field()
        lock(3)
        hide()
        show_again()
        assert until(lambda: offered(2), 10), st()["raw"]
        tap("sendKey")
        check("Send with no PC: the cloud's text lands", until(lambda: fb.HEARD in fd.in_field(), 40),
              fd.in_field()[:200])
        check("the line says the cloud", fd.says(fb.FROM_CLOUD, 10), fd.status())
        asked = cloud.asked("transcriptions")
        check("the provider got the whole recording once",
              len(asked) == 1 and fb.wav_seconds(asked[0]["wav_bytes"]) >= 2, str(len(asked)))
        check("nothing left", until(lambda: spool()["all"] == 0, 10), str(spool()))
        fb.is_clean(fb.KEY)
    finally:
        fb.home_again()
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


def flow_small_and_large():
    """The row on a 320 dp phone with the largest text: the mic's words shrink and are never
    cut, Send and the X keep their touch."""
    acct = joined()
    try:
        fd.field()
        lock(3)
        hide()
        try:
            drive.shell("wm", "density", "540")
            drive.shell("settings", "put", "system", "font_scale", "2.0")
            time.sleep(3)
            show_again()
            s = st()
            check("320 dp, largest text: offered", until(lambda: offered(2), 10), st()["raw"])
            s = st()
            check("the mic's words whole, not cut", not s["mic_cut"] and s["mic_text"].startswith("Continue"),
                  s["raw"])
            check("Send and the X a thumb's size", s["touch"] >= 48, s["raw"])
            tap("pill")
            assert until(lambda: st()["locked"], 5), st()["raw"]
            time.sleep(1.2)
            s = st()
            check("the locked clock is never cut either", not s["mic_cut"] and re.search(r"\d:\d\d", s["mic_text"]),
                  s["raw"])
            tap("backspace")
        finally:
            drive.shell("wm", "density", "reset", check=False)
            drive.shell("settings", "put", "system", "font_scale", "1.0", check=False)
    finally:
        acct._door_pc.down()
        acct.stop()


# ------------------------------------------------------------------ the pictures

def shots(out: Path) -> None:
    """The real row, photographed: B at normal size, an older one waiting, Continue locked,
    a 320 dp phone, the largest text, and both."""
    out.mkdir(parents=True, exist_ok=True)
    drive.OUT = out
    acct = joined(text=fb.HEARD)
    try:
        pc = acct._door_pc
        fd.field()
        lock(4)
        hide()
        show_again()
        assert until(lambda: offered(3), 10), st()["raw"]
        drive.shot("k1_paused")
        tap("pill")
        assert until(lambda: st()["locked"], 5), st()["raw"]
        time.sleep(1.5)
        drive.shot("k2_continue_locked")
        tap("pill")
        assert until(lambda: fb.HEARD in fd.in_field(), 30), fd.in_field()[:200]
        time.sleep(0.4)
        drive.shot("k3_sent")
        pc.down()
        fresh_field()
        fd.hold_and_say()
        assert until(lambda: fd.row_is(fd.NO_ANSWER), 30), st()["raw"]
        drive.shot("k4_older_waiting")
        fd.back_up(pc)
        lock(4)
        hide()
        show_again()
        assert until(lambda: offered(3), 10), st()["raw"]
        drive.shot("k5_paused_and_older")
        try:
            for name, density, scale in (("320dp", "540", "1.0"), ("largest_text", "reset", "2.0"),
                                         ("320dp_largest_text", "540", "2.0")):
                drive.shell("wm", "density", density)
                drive.shell("settings", "put", "system", "font_scale", scale)
                time.sleep(3.5)
                assert until(lambda: offered(3), 10), st()["raw"]
                time.sleep(0.8)
                drive.shot(f"k6_{name}")
                print(f"  {name}: {st()['raw']}", flush=True)
            tap("pill")
            assert until(lambda: st()["locked"], 5), st()["raw"]
            time.sleep(1.5)
            drive.shot("k7_320dp_largest_text_continue_locked")
            print(f"  locked: {st()['raw']}", flush=True)
            tap("backspace")
        finally:
            drive.shell("wm", "density", "reset", check=False)
            drive.shell("settings", "put", "system", "font_scale", "1.0", check=False)
        fd.drop_waiting()
    finally:
        acct._door_pc.down()
        acct.stop()


FLOWS = {name[5:]: fn for name, fn in list(globals().items()) if name.startswith("flow_")}


def main() -> None:
    apk = fd.APK
    if not fa.built_for_the_fake(apk) or not fb.built_for_the_fake_cloud(apk):
        sys.exit("build for the fakes: gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791 "
                 "-PdeskitCloud=http://10.0.2.2:18793")
    drive.adb("install", "-r", "-g", apk, timeout=300)
    drive.adb("logcat", "-G", "8M", check=False)
    if fa.sdk() >= fd.WIFI_ONLY:
        fd.settled()
    args = sys.argv[1:]
    try:
        if args[:1] == ["--shots"]:
            shots(Path(args[1]))
            return
        for name in args or list(FLOWS):
            print(f"--- {name}", flush=True)
            fa.log_forget()
            try:
                FLOWS[name]()
            except (AssertionError, subprocess.TimeoutExpired) as e:
                check(f"{name} ran to its end", False, str(e)[:500])
                drive.shot(f"failed_keep_{name}")
            except Exception as e:                           # noqa: BLE001
                check(f"{name} ran to its end", False, f"{type(e).__name__}: {str(e)[:400]}")
                drive.shot(f"failed_keep_{name}")
    finally:
        shutil.rmtree(fd.HOME, ignore_errors=True)
    print(f"{fa._passed} passed, {fa._failed} failed", flush=True)
    sys.exit(1 if fa._failed else 0)


if __name__ == "__main__":
    main()
