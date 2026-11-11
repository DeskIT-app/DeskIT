"""The cloud backup on the emulator (PHONE_LINK_PLAN.md stage 2b), flow by flow, and
the pictures of its real screens.

    <venv python> dev\\android\\flow_backup.py [name ...]

Build first, for the fake account AND the fake provider:
gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791 -PdeskitCloud=http://10.0.2.2:18793

What is real: the whole keyboard and app, its Keystore and its seals; vault.py, sb.py,
sync.py and history.py opening what the phone wrote; phone.py's door and server.py's
routes for the PC (flow_door.Pc). What is fake: the account (fake_pc.FakeAccount) and
Groq and Gemini (fake_cloud.FakeCloud), on loopback. Every key here is made fresh for
the run, looks like a key and opens nothing; the flows check that none of them reaches
the phone's log or any file it wrote. Pictures go to DESKIT_EMU_OUT, named as in the
report, without the prototype's.

An emulator's mobile data reaches the host, where a phone's 5G never reaches a PC at
home, so "the PC can't be reached" is the PC's door down, as in flow_door.
"""
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flow_door as fd                            # noqa: E402  (sets DESKIT_HOME and DESKIT_SUITE)

import history as history_mod                     # noqa: E402
import sb                                         # noqa: E402
import sync                                       # noqa: E402

import drive                                      # noqa: E402
import fake_cloud                                 # noqa: E402

fa = fd.fa
check, until = fd.check, fd.until
PKG = drive.PKG

#: This run's keys: fresh, the providers' shapes, worth nothing anywhere.
KEY = "gsk_" + secrets.token_hex(24)
WRONG = "gsk_" + secrets.token_hex(24)
GEMINI = "AIza" + secrets.token_hex(18)
#: What the fake provider hears: Hebrew, as his are.
HEARD = "אני בדרך הביתה, אגיע בעוד עשר דקות"
FROM_CLOUD = r"from the cloud \(Groq\)"


def cloud_up(groq: str = KEY, gemini: str = GEMINI) -> fake_cloud.FakeCloud:
    c = fake_cloud.FakeCloud().start()
    c.key, c.gemini_key, c.text = groq, gemini, HEARD
    return c


def backup() -> str:
    """The backup as the phone has it: the switch, the yes, the key it would use."""
    return fa.told("--es", "backup", "read")


def button() -> str:
    m = re.search(r"button=(\S*)", fd.status())
    return (m.group(1) if m else "").replace("_", " ")


def key_row(acct, name: str):
    """The account's row for ``name`` as a PC's import_keys opens it: None for no row,
    and a word for one that does not open, which is a removal written wrong."""
    try:
        return acct.key_row(name)
    except Exception as e:                                   # noqa: BLE001
        return f"does not open: {type(e).__name__}"


def link_backup(acct):
    """The phone's own row, opened as a PC opens it: its cloud switch."""
    rows = acct.phones()
    return acct.open_link(rows[0]).get("cloud_backup") if rows else None


def done_once() -> None:
    """The one-time screen, as a person meets it after the join: Done."""
    drive.wait("^When your PC can't be reached$", 25)
    drive.tap("^Done$", 10)
    assert until(lambda: "active=true" in backup(), 10), backup()


def everything_written() -> bytes:
    """Every file the app wrote, as bytes: its own folders, run-as."""
    return drive.adb("exec-out", "run-as", PKG, "sh", "-c", "find . -type f -exec cat {} +",
                     check=False, text=False, timeout=120)


def is_clean(*keys: str) -> None:
    log = fa.log_so_far()
    files = everything_written()
    check("no key reached the phone's log", not any(k in log for k in keys),
          next((k[:6] for k in keys if k in log), ""))
    check("no key reached a file the phone wrote, in the clear",
          not any(k.encode() in files for k in keys))


def tap_switch(label: str) -> None:
    """The Switch beside [label], at the row's far end: Android 8 names a switch by
    its own text ("ON") and not by its description, so it is found by its label's row."""
    hits = [n for n in drive.nodes() if n["text"] == label]
    assert hits, f"{label!r} is not on screen"
    m = re.search(r"(\d+)x(\d+)", drive.shell("wm", "size"))
    width = int(m.group(1)) if m else 1080
    drive.shell("input", "tap", int(width * 0.86), hits[0]["y"])


def keyboard_down() -> None:
    """The keyboard down, if it is up: a swipe that starts on it scrolls nothing."""
    if "mInputShown=true" in drive.shell("dumpsys", "input_method", check=False):
        fa.back()
        time.sleep(0.8)


def type_key(value: str) -> None:
    """The way a person pastes a key: into the field, then the keyboard down."""
    drive.shell("input", "text", value)
    keyboard_down()


def found(pc) -> None:
    """At home, the PC known: the phone has found its door, as it has once it has
    dictated there. The test PC's door moves port when it comes up a second time, and a
    first knock at a port that moved is a re-read of the rows, longer than the second."""
    assert until(lambda: "nobody" not in fd.ask("reach"), 45), "the phone never found the PC"


def keys_on_top() -> None:
    """The keys card at the top of Settings, for its picture."""
    n = drive.seek("^Your cloud keys$")
    assert n is not None, "no keys card"
    drive.shell("input", "swipe", 500, n["y"], 500, 330, 700)
    time.sleep(1)


def home_afresh() -> None:
    """Home brought up so that it looks again: a Home already in front keeps the line
    it drew, and the PC may have gone since."""
    drive.shell("input", "keyevent", "3")
    time.sleep(1)
    drive.home()


def away(pc) -> None:
    """Away from home: the PC's door down and the phone off the Wi-Fi."""
    pc.down()
    fd.wifi(False)


def home_again() -> None:
    fd.wifi(True)
    if fa.sdk() >= fd.WIFI_ONLY:
        fd.settled()


def opened(acct, row: dict) -> dict | None:
    """A history row as a PC of the account opens it (sb._open_history), as Postgres
    hands the stamp back: without its trailing zeros."""
    pulled = dict(row, ts=re.sub(r"0+(\+00:00)$", r"\1", row["ts"]).replace(".+", "+"))
    return sb._open_history(acct.key, acct.uid, pulled)


# ------------------------------------------------------------------ the flows

def flow_lands():
    """The PC can't be reached, a key is in the account: the one-time screen, its yes,
    and a dictation the cloud carries, its line saying so, its recording gone, its text
    on to the PCs sealed and marked."""
    acct = fa.fresh(backup=None)
    cloud = cloud_up()
    try:
        acct.put_key("groq", KEY)                # a key a PC put in the account
        fd.real_join(acct)
        drive.wait("^When your PC can't be reached$", 25)
        time.sleep(1.5)                          # the keys read on its way up
        check("the one-time screen: the switch on, the plain line, the price, Done",
              until(lambda: all(fa_text in fd.in_field() for fa_text in (
                  "Use the cloud", "If your PC can't be reached, your recording goes to Groq with "
                  "your own key. You can turn this off here or in Settings.",
                  "Groq hears the recording, and its words are less accurate than your PC's.",
                  "Done")), 10), fd.in_field()[:400])
        check("with a key, it does not ask for one", "Add a key" not in fd.in_field())
        drive.shot("b1_once_backup_on")
        check("before Done the backup is not on", "active=false" in backup(), backup())
        done_once()
        prefs = drive.as_app("cat", "shared_prefs/backup.xml", check=False)
        check("Done records the yes: the words and their version, on the phone",
              "phone-cloud-audio-en-2026-11-11" in prefs and "If your PC can" in prefs, prefs[:300])
        check("the phone's row says the switch is on, for the PCs",
              until(lambda: link_backup(acct) is True, 30), str(link_backup(acct)))

        pc = acct._door_pc
        away(pc)
        fd.field()
        cloud.delay = 2.5
        fd.hold_and_say()
        check("on its way, the line says the cloud",
              fd.says(r"Transcribing in the cloud", 15), fd.status())
        drive.shot("c1_keyboard_sending_to_cloud")
        check("the cloud's text lands in the field", until(lambda: HEARD in fd.in_field(), 30),
              fd.in_field()[:200])
        check("and the line says it came from the cloud", fd.says(FROM_CLOUD, 10), fd.status())
        drive.shot("c2_keyboard_landed_from_cloud")
        check("the recording is gone from the phone", until(fd.spool_empty, 10), fd.spooled())
        asked = cloud.asked("transcriptions")
        check("the provider was asked once, with the key from the account",
              len(asked) == 1 and asked[0]["key_ok"], str(len(asked)))
        check("as deskit-android, with the model, Hebrew, and a WAV",
              asked and asked[0]["agent"].startswith("deskit-android/") and asked[0]["wav"]
              and asked[0]["fields"].get("model") == "whisper-large-v3-turbo"
              and asked[0]["fields"].get("language") == "he", str(asked[0] if asked else ""))

        check("the text went on to the account's history, one row",
              until(lambda: len(acct.history()) == 1, 20), str(len(acct.history())))
        row = acct.history()[0]
        check("in the clear: no words", HEARD not in str(row) and row["engine"] == "groq"
              and row["kind"] == "dictation", str({k: row[k] for k in ("engine", "kind")}))
        inside = opened(acct, row)
        check("a PC opens it, under the stamp as the server hands it back, marked phone-cloud",
              inside is not None and inside["text"] == HEARD and inside["source"] == sync.CLOUD_SOURCE,
              str(inside and inside.get("source")))
        line = sync.remote_line(inside or {}, "Dana's phone")
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "history.log"
            log.write_text(line + "\n", "utf-8")
            event = history_mod._events_in(log)[0]
        check("and the PC's Said page shows it from the phone and from the cloud",
              event.cloud and "from Dana's phone" in event.note and event.text == HEARD, line)
        check("the PCs were told to look", any("history" in (e.get("stores") or [])
                                               for e in acct.events("changed")))

        fa.back()                                # the keyboard down
        fa.back()                                # and the field gone
        home_afresh()
        check("Home, the PC away: what still works, and the cloud's line in What you said",
              until(lambda: "You can still dictate. It goes to Groq with your key." in fd.in_field()
                    and "from the cloud" in fd.in_field(), 25), fd.in_field()[:400])
        drive.shot("e1_home_no_wifi_with_key")
        is_clean(KEY)
    finally:
        home_again()
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


def flow_pc_first():
    """The PC answers: its text lands and the cloud is never asked, the switch on and a
    key in the account all the same."""
    acct = fa.fresh(backup="on")
    cloud = cloud_up()
    try:
        acct.put_key("groq", KEY)
        fd.real_join(acct)
        found(acct._door_pc)
        fd.field()
        fd.hold_and_say()
        check("the PC's text lands", until(lambda: fd.SENTENCE in fd.in_field(), 25), fd.in_field()[:200])
        time.sleep(2)
        check("and the cloud was never asked", cloud.asked() == [], str(cloud.asked()))
        check("the line names the PC's engine, not the cloud", "from the cloud" not in fd.status(),
              fd.status())
        check("no text row: the PC has it already", acct.history() == [])
    finally:
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


def flow_silent_pc():
    """A PC that answered the knock and then went silent: after the silence the same
    recording goes to the key, the cloud's text lands, and the PC's, when it comes, is
    dropped: text never lands twice."""
    acct = fa.fresh(backup="on")
    cloud = cloud_up()
    try:
        acct.put_key("groq", KEY)
        fd.real_join(acct)
        pc = acct._door_pc
        found(pc)
        fd.field()
        pc.hold.clear()                          # the PC takes it, and says nothing
        t0 = time.time()
        fd.hold_and_say()
        check("the PC had the recording", until(pc.arrived.is_set, 15))
        check("after its silence, the cloud's text lands", until(lambda: HEARD in fd.in_field(), 40),
              fd.in_field()[:200])
        took = time.time() - t0
        check("not before the silence was up", took >= 10, f"{took:.1f} s")
        pc.hold.set()                            # the PC answers now, late
        time.sleep(6)
        text = fd.in_field()
        check("the PC's late text never lands: one text, once",
              fd.SENTENCE not in text and text.count(HEARD) == 1, text[:200])
        check("asked once", len(cloud.asked("transcriptions")) == 1)
    finally:
        acct._door_pc.hold.set()
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


def flow_switch_off():
    """The switch off in Settings: the phone's row says so, and the PC away is today's
    waiting row, the cloud never asked."""
    acct = fa.fresh(backup="on")
    cloud = cloud_up()
    try:
        acct.put_key("groq", KEY)
        fd.real_join(acct)
        fa.to_settings()
        drive.seek("^Use the cloud$")
        tap_switch("Use the cloud")
        check("the switch off: the backup is off", until(lambda: "active=false" in backup(), 10), backup())
        check("and the phone's row tells the PCs", until(lambda: link_backup(acct) is False, 30),
              str(link_backup(acct)))
        fa.back()
        pc = acct._door_pc
        away(pc)
        home_afresh()
        check("Home, the switch off: today's words", until(
            lambda: "Tap to try again." in fd.in_field(), 25), fd.in_field()[:300])
        drive.shot("e0_home_no_wifi_switch_off")
        fd.field()
        fd.hold_and_say()
        check("the recording waits, as today: the Wi-Fi's words and Send again",
              until(lambda: fd.row_is(fd.NO_WIFI) and button() == "Send again", 25), fd.status())
        time.sleep(2)
        check("the cloud was never asked", cloud.asked() == [], str(cloud.asked()))
        fd.drop_waiting()
    finally:
        home_again()
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


def flow_no_key():
    """No key in the account: the one-time screen says so; away from home the waiting
    row offers Add a key where Send again stands, only while there is no road; a key
    added in Settings sends it."""
    acct = fa.fresh(backup=None)
    cloud = cloud_up()
    try:
        fd.real_join(acct)
        drive.wait("^When your PC can't be reached$", 25)
        check("no key: the one-time screen says so, and offers one",
              until(lambda: "Your account has no cloud key yet, so nothing is sent." in fd.in_field()
                    and "Add a key" in fd.in_field(), 10), fd.in_field()[:300])
        drive.shot("b2_once_backup_on_no_key")
        done_once()
        pc = acct._door_pc
        away(pc)
        home_afresh()
        check("Home, the PC away and no key: the way to one",
              until(lambda: "Add a cloud key, and you can dictate from anywhere." in fd.in_field()
                    and "Add a key" in fd.in_field(), 25), fd.in_field()[:300])
        drive.shot("e2_home_no_wifi_no_key")
        fd.field()
        fd.hold_and_say()
        check("off the Wi-Fi, no key: the Wi-Fi's words, and Add a key where Send again stands",
              until(lambda: fd.row_is(fd.NO_WIFI) and button() == "Add a key", 25), fd.status())
        drive.shot("d2_keyboard_no_key_button")
        check("the recording waits", "waiting=1" in fd.spooled(), fd.spooled())
        fd.wifi(True)
        check("a Wi-Fi back: Send again comes back", until(lambda: button() == "Send again", 20),
              fd.status())
        fd.wifi(False)
        check("and goes again with it", until(lambda: button() == "Add a key", 20), fd.status())
        fd.tap_key("sendKey")
        check("Add a key opens Settings at the keys", until(lambda: drive.find("^Your cloud keys$")
                                                            is not None, 15))
        field = drive.seek("^Paste your Groq key$")
        drive.shell("input", "tap", field["x"], field["y"])
        type_key(KEY)
        drive.tap_scrolling("^Save and test$")
        check("the key is tested and saved", until(lambda: drive.find("Key works") is not None, 25))
        fa.back()
        fd.field()
        check("with a key, the row offers Send again", until(lambda: button() == "Send again", 20),
              fd.status())
        fd.send_again()
        check("and Send again carries it through the cloud", until(lambda: HEARD in fd.in_field(), 30),
              fd.in_field()[:200])
        check("nothing waits", until(fd.spool_empty, 10), fd.spooled())
        is_clean(KEY)
    finally:
        home_again()
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


def flow_keys():
    """The keys on the phone, both ways through the account: a key the provider refuses
    never reaches the account; one it takes does, sealed as vault.py seals one, the PCs
    told; a key a PC put there is on the phone; Change keeps the old one until a new one
    passes; Remove asks, then writes the empty key a PC reads as a removal."""
    acct = fa.fresh(backup="on")
    cloud = cloud_up()
    try:
        fd.real_join(acct)
        fa.to_settings()
        check("Settings: the switch and the keys, no key yet",
              drive.seek("^Your cloud keys$") is not None and drive.seek("^Paste your Groq key$") is not None)
        drive.swipe_down()
        drive.seek("^When your PC can't be reached$")
        n = drive.find("^When your PC can't be reached$")
        drive.shell("input", "swipe", 500, n["y"], 500, 330, 700)
        time.sleep(1)
        drive.shot("a2_settings_no_key")
        field = drive.seek("^Paste your Groq key$")
        drive.shell("input", "tap", field["x"], field["y"])
        type_key(WRONG)
        drive.tap_scrolling("^Save and test$")
        check("a key the provider refuses: said so", until(
            lambda: drive.find("Groq didn't accept this key") is not None, 20))
        check("and it never reaches the account", key_row(acct, "groq") is None)

        field = drive.seek("^Paste your Groq key$")
        drive.shell("input", "tap", field["x"], field["y"])
        type_key(KEY)
        drive.tap_scrolling("^Save and test$")
        check("a key the provider takes: Key works", until(lambda: drive.find("Key works") is not None, 25))
        check("in the account, sealed as vault.py seals it: what import_keys opens",
              key_row(acct, "groq") == {"v": KEY})
        check("and the PCs told: changed, vault",
              any("vault" in (e.get("stores") or []) for e in acct.events("changed")))

        acct.put_key("gemini", GEMINI)           # a key a PC put there
        fa.back()
        fa.to_settings()
        drive.seek("^Gemini$")
        check("a PC's key is on the phone: dots and Saved, no field to paste into",
              until(lambda: drive.find("^Paste your Gemini key$") is None
                    and "Saved in your account, locked." in fd.in_field(), 20), fd.in_field()[:500])
        check("and the phone holds both", "keys=groq,gemini" in backup(), backup())
        keys_on_top()
        drive.shot("a1_settings_keys")
        drive.tap_scrolling("^Change$")
        check("Change: the field open, the old key kept meanwhile",
              until(lambda: drive.find("The saved key keeps working") is not None, 10)
              and key_row(acct, "groq") == {"v": KEY})
        keys_on_top()
        drive.shot("a3_settings_change_key")
        drive.tap_scrolling("^Cancel$")
        drive.tap_scrolling("^Remove$")
        check("Remove asks first, in the row", until(
            lambda: drive.find("^Remove your Groq key\\?$") is not None, 10))
        keys_on_top()
        drive.shot("a4_settings_remove_key")
        hits = [n for n in drive.nodes() if n["text"] == "Remove"]
        drive.shell("input", "tap", hits[0]["x"], hits[0]["y"])
        check("removed: the empty key a PC reads as a removal",
              until(lambda: key_row(acct, "groq") == {"v": ""}, 15), str(key_row(acct, "groq") is not None))
        check("and the field is back", until(lambda: drive.find("^Paste your Groq key$") is not None, 10))
        check("Gemini stays", key_row(acct, "gemini") == {"v": GEMINI})
        is_clean(KEY, WRONG, GEMINI)
    finally:
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


def flow_gemini_only():
    """Only a Gemini key: Gemini carries it, and the line names it."""
    acct = fa.fresh(backup="on")
    cloud = cloud_up()
    try:
        acct.put_key("gemini", GEMINI)
        fd.real_join(acct)
        fa.to_settings()                         # the keys read
        fa.back()
        away(acct._door_pc)
        fd.field()
        fd.hold_and_say()
        check("Gemini's text lands", until(lambda: HEARD in fd.in_field(), 40), fd.in_field()[:200])
        check("the line says Gemini", fd.says(r"from the cloud \(Gemini\)", 10), fd.status())
        asked = cloud.asked("generateContent")
        check("asked with the key, a WAV in it", asked and asked[0]["key_ok"] and asked[0]["wav"],
              str(asked[:1]))
        check("Groq never", cloud.asked("transcriptions") == [])
        is_clean(GEMINI)
    finally:
        home_again()
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


def flow_history_off():
    """A PC that does not keep what was said: the cloud's text lands, and no row is
    written into the account for nobody to read."""
    acct = fa.fresh(backup="on")
    cloud = cloud_up()
    try:
        acct.put_key("groq", KEY)
        fd.real_join(acct)
        pc = acct._door_pc
        pc.write(port=pc.door.port, history_sync=False)
        fa.to_settings()                         # the account's rows read again
        fa.back()
        check("the phone knows no PC keeps it", until(lambda: "keep=false" in backup(), 15), backup())
        away(pc)
        fd.field()
        fd.hold_and_say()
        check("the cloud's text lands", until(lambda: HEARD in fd.in_field(), 40), fd.in_field()[:200])
        time.sleep(4)
        check("and no text row was written", acct.history() == [], str(len(acct.history())))
    finally:
        home_again()
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


FLOWS = {name[5:]: fn for name, fn in list(globals().items()) if name.startswith("flow_")}


def built_for_the_fake_cloud(apk: Path) -> bool:
    tools = sorted((drive.SDK / "build-tools").glob("*/aapt2.exe"))
    out = subprocess.run([str(tools[-1]), "dump", "resources", str(apk)], capture_output=True,
                         encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    lines = out.stdout.splitlines()
    for i, line in enumerate(lines):
        if "string/cloud_server" in line:
            return "10.0.2.2" in "".join(lines[i:i + 3])
    return False


def main() -> None:
    apk = fd.APK
    if not fa.built_for_the_fake(apk) or not built_for_the_fake_cloud(apk):
        sys.exit("build for the fakes: gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791 "
                 "-PdeskitCloud=http://10.0.2.2:18793")
    drive.adb("install", "-r", "-g", apk, timeout=300)
    drive.adb("logcat", "-G", "8M", check=False)
    if fa.sdk() >= fd.WIFI_ONLY:
        fd.settled()
    names = sys.argv[1:] or list(FLOWS)
    try:
        for name in names:
            print(f"--- {name}", flush=True)
            fa.log_forget()
            try:
                FLOWS[name]()
            except (AssertionError, subprocess.TimeoutExpired) as e:
                check(f"{name} ran to its end", False, str(e)[:500])
                drive.shot(f"failed_backup_{name}")
            except Exception as e:                           # noqa: BLE001
                check(f"{name} ran to its end", False, f"{type(e).__name__}: {str(e)[:400]}")
                drive.shot(f"failed_backup_{name}")
    finally:
        shutil.rmtree(fd.HOME, ignore_errors=True)
    print(f"{fa._passed} passed, {fa._failed} failed", flush=True)
    sys.exit(1 if fa._failed else 0)


if __name__ == "__main__":
    main()
