"""The keyboard against the REAL door, on the emulator, flow by flow.

    <venv python> dev\\android\\flow_door.py [name ...]

Build first, exactly as for flow_account.py:
gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791

What is real here: phone.py's identity and its rows, server.py's PhoneDoor with
its routes, net.serve_tls with its handshake, vault.py's seals, and on the other
side the whole keyboard, its Keystore key among them. What is fake is the account
(fake_pc.FakeAccount) and what the PC does with the audio. Under DESKIT_SUITE the
door binds loopback on a test port, which raises no firewall dialog, and the
emulator reaches that as 10.0.2.2. Nothing of the owner's is touched: DESKIT_HOME
is a scratch folder, made here and removed at the end, and the secret store is on
the test slots.

The microphone on an emulator hears nothing, so a real hold on the real keyboard
is given its loudness by the debug probe. Everything else about it is the real
path: the press, the recorder, the release, the spool, the door.

Only the phone is driven. Windows' firewall has never been in this path: that is
M4, and a real phone is M11 and M13.
"""
import dataclasses
import http.server
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HOME = tempfile.mkdtemp(prefix="deskit-door-")
os.environ["DESKIT_HOME"] = HOME
os.environ["DESKIT_SUITE"] = "1"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as config_mod                      # noqa: E402
import net as net_mod                            # noqa: E402
import phone as phone_mod                        # noqa: E402
import server as server_mod                      # noqa: E402

import drive                                     # noqa: E402
import fake_pc                                   # noqa: E402
import flow_account as fa                        # noqa: E402

from flow_account import check, until            # noqa: E402

PKG = drive.PKG
SENTENCE = "the-door-heard-this"
UNREACHED = "Your PC isn't reachable from this network"
ADDRESS = "10.0.2.2"                             # the host, from the emulator
WIFI_ONLY = 28                                   # the two networks of a modern emulator image


class Pc:
    """A PC of the account, with its real door. ``up()`` opens it for whatever
    phones the account lists, as main.App._doors does off the kept rows."""

    def __init__(self, acct: fake_pc.FakeAccount, *, device: str | None = None,
                 name: str | None = None, text: str = SENTENCE):
        self.acct = acct
        self.device = device or acct.pc_id
        self.name = name or acct.pc_name
        self.text = text
        cfg = config_mod.load_layered()
        self.cfg = dataclasses.replace(cfg, server=dataclasses.replace(cfg.server, phone_port=8766))
        self.heard: list[bytes] = []
        self.peers: list[str] = []
        self.hold = threading.Event()
        self.hold.set()
        self.arrived = threading.Event()
        self.model_off = False
        self.asked_off = 0
        #: A sentence the PC answers every dictation with, as main.py raises its own.
        self.fail: str | None = None
        self.review: list[dict] = []
        self.decided: list[tuple[str, str]] = []
        self.routes = server_mod.Routes(
            self._transcribe, self._translate, punctuate=self._punctuate,
            review_pending=lambda: [dict(i) for i in self.review],
            review_decide=self._decide, lookup=self._lookup, review_scope="phone")
        self.door = server_mod.PhoneDoor(self.cfg, self.routes)

    # what the PC does with what comes in

    def _transcribe(self, wav: bytes):
        self.arrived.set()
        self.hold.wait(40)
        if self.model_off:
            self.asked_off += 1
            raise RuntimeError("The speech model is off. Start it on the PC.")
        if self.fail is not None:
            raise RuntimeError(self.fail)
        self.heard.append(wav)
        self.last_at = time.perf_counter()
        return (self.text(wav) if callable(self.text) else self.text), "fake", None

    def _translate(self, text: str):
        return "in-english", "fake"

    def _punctuate(self, text: str):
        return text + ".", "fake"

    def _lookup(self, text: str):
        return "looked-up", "Hebrew", "fake", 0.1

    def _decide(self, sid: str, verdict: str):
        self.decided.append((sid, verdict))
        self.review = [i for i in self.review if i["id"] != sid]
        return {"status": verdict}

    # the door

    def anchors(self) -> dict:
        """phone.anchors(), over the fake's rows: the real open, the real
        forgotten rule, the real fingerprint."""
        key = self.acct.key
        gone = {str(e.get("device")) for e in self.acct.forgotten()} | \
               {str(e.get("cert")) for e in self.acct.forgotten()}
        out = {}
        for row in phone_mod._open_rows(key, self.acct.uid, self.acct.phones(), gone):
            der = phone_mod._phone_cert(row["link"])
            if der is None:
                continue
            mark = phone_mod.fingerprint(der)
            if mark not in gone:
                out[mark] = {"device": str(row["id"]), "name": str(row.get("name") or ""), "der": der}
        return out

    def up(self) -> "Pc":
        port = self.door.start(self.anchors())
        self.write(port=port)
        return self

    def write(self, *, port: int | None = None, addrs=None, cert: str | None = None,
              words_sync: bool = True):
        self.acct.write_pc_row(device=self.device, name=self.name, link={
            "v": 1, "kind": "pc", "cert": cert or phone_mod.identity(),
            "addrs": [ADDRESS] if addrs is None else addrs,
            "port": port if port is not None else (self.door.port or 8766),
            "proto": 1, "words_sync": words_sync})

    def down(self):
        self.door.stop()


def real_join(acct: fake_pc.FakeAccount) -> dict:
    """The phone joins; the PC's row and door follow, as they do on an Approve."""
    pc = acct._door_pc = Pc(acct)
    pc.up()
    row = fa.join(acct)
    pc.up()
    return row


def field() -> None:
    """The keyboard, up on a field of nobody's in particular."""
    drive.shell("settings", "put", "secure", "show_ime_with_hard_keyboard", "1")
    drive.shell("pm", "grant", PKG, "android.permission.RECORD_AUDIO", check=False)
    ime = f"{PKG}/.DictationIme"
    drive.shell("ime", "enable", ime, check=False)
    drive.shell("ime", "set", ime, check=False)
    drive.shell("am", "start", "-n", f"{PKG}/.FieldProbe")
    assert until(lambda: "pending" in fa.told("--es", "ime", "read"), 20), "no keyboard came up"
    # A keyboard that is running is not yet a keyboard on the screen.
    assert until(lambda: spot("pill")[1] > 500, 15), "the keyboard never came on screen"


def in_field() -> str:
    return "\n".join(n["text"] for n in drive.nodes())


def spot(name: str) -> tuple[int, int]:
    """The middle of a piece of the keyboard, from the keyboard itself: uiautomator
    shows the app and not the window over it."""
    m = re.search(rf"{name}=(\d+),(\d+)", fa.told("--es", "ime", "where"))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def status() -> str:
    """The keyboard's status line, and what it believes."""
    return fa.told("--es", "ime", "status")


def says(pattern: str, seconds: float = 25) -> bool:
    return until(lambda: re.search(pattern, status()) is not None, seconds, 0.6)


def tap_status() -> None:
    x, y = spot("status")
    drive.shell("input", "tap", x, y)


#: The line's few words for a dictation nobody answered.
NO_ANSWER = "Your PC didn't answer"


def row() -> dict:
    """The keyboard's line as it stands: its words, and whether Send again and the X
    are up, and whether Send again's word is cut."""
    out = status()
    words = re.search(r"status=(.*?) reachable=", out)
    touch = re.search(r"touch=(\d+)", out)
    board = re.search(r"board=(\d+)", out)
    mic = re.search(r"mic=(\d+)", out)
    return {"status": words.group(1) if words else "", "send": "send=true" in out,
            "drop": "drop=true" in out, "cut": "cut=true" in out, "raw": out,
            "touch": int(touch.group(1)) if touch else 0, "board": int(board.group(1)) if board else 0,
            "ellipsis": "ellipsis=true" in out, "mic": int(mic.group(1)) if mic else 0}


def row_is(words: str, *, send: bool = True) -> bool:
    """The line ends in [words], with the X, and with Send again or without it."""
    r = row()
    return r["status"].endswith(words) and r["send"] == send and r["drop"]


def tap_key(name: str) -> None:
    """A real tap on one of the line's keys, where the keyboard says it is."""
    x, y = spot(name)
    drive.shell("input", "tap", x, y)


def send_again() -> None:
    tap_key("sendKey")


def drop_waiting() -> None:
    tap_key("dropKey")


def back_up(pc: "Pc") -> None:
    """The PC up again, and the phone with it: a door that comes back can land on
    another port, and the phone reads the account's rows at most every 30 s
    (Link.READ_EVERY_MS), so a press made at once can find nobody yet."""
    pc.up()
    assert until(lambda: "nobody" not in ask("reach"), 45), "the phone never found the PC again"


def private_field() -> None:
    """The keyboard up on a password field."""
    drive.shell("am", "start", "-n", f"{PKG}/.FieldProbe", "--ez", "private", "true")
    assert until(lambda: "pending" in fa.told("--es", "ime", "read"), 20), "no keyboard came up"
    assert until(lambda: "private=true" in status(), 15), "the keyboard never saw a private field"
    time.sleep(1)


def hold_and_say(seconds: float = 2.6) -> None:
    """A real press, held and let go: the real recorder, with a voice the emulator
    has not got. Blocks until the finger is up. The voice is the probe's, put on the
    recorder while the finger is down, by a bare broadcast: `am broadcast` returns
    once the receiver has run, where told() first reads and clears the log, which
    took Android 8's emulator past the end of a 1.6 s press. A voice that still came
    too late leaves the keyboard saying No sound, having sent nothing, and the press
    is made again, once."""
    for _ in range(2):
        x, y = spot("pill")
        finger = threading.Thread(target=lambda: drive.shell(
            "input", "swipe", x, y, x, y, int(seconds * 1000), check=False))
        finger.start()
        time.sleep(0.6)
        drive.shell("am", "broadcast", "--receiver-foreground", "-n", f"{PKG}/.ProbeReceiver",
                    "--es", "ime", "loud", timeout=60)
        finger.join()
        if "No sound" not in status():
            return
        print("      the probe's voice came too late: the press again", flush=True)


def said() -> str:
    return fa.on_disk()


def spooled() -> str:
    return fa.told("--es", "link", "count")


def spool_empty() -> bool:
    return "waiting=0" in spooled()


def job() -> None:
    """The system gives the sweep its turn, now: the hour of whatever waits."""
    drive.shell("cmd", "jobscheduler", "run", "-f", PKG, "1", check=False)


def ask(what: str) -> str:
    return fa.told("--es", "link", what, wait=150)


def is_clean() -> None:
    log = fa.log_so_far()
    check("nothing about an address or a key reached the log",
          ADDRESS not in log and "BEGIN" not in log)


# ------------------------------------------------------------------ the flows

def flow_first_join():
    """Sign in, both presses, and the first thing said reaches the real door with
    the real client certificate."""
    acct = fa.fresh()
    try:
        fa.log_forget()
        row = real_join(acct)
        pc = acct._door_pc
        cert = phone_mod._phone_cert(acct.open_link(row))
        mark = phone_mod.fingerprint(cert)
        check("the door lists this phone's certificate", mark in pc.anchors(), mark[:12])
        field()
        hold_and_say()
        check("a real hold reaches the real door", until(lambda: bool(pc.heard), 15))
        check("what crossed is a WAV", pc.heard[0][:4] == b"RIFF" and len(pc.heard[0]) > 16000,
              str(len(pc.heard[0]) if pc.heard else 0))
        check("the text lands in the field", until(lambda: SENTENCE in in_field(), 10),
              in_field()[:300])
        check("and in Said", until(lambda: SENTENCE in said(), 5))
        check("and the spool has let it go", until(spool_empty, 5), spooled())
        lines = fa.log_so_far()
        check("there was a race, won on a network", "link: a race, won on " in lines, lines[-600:])
        time.sleep(0.5)
        fa.log_forget()
        n = len(pc.heard)
        hold_and_say()
        check("the second one lands too", until(lambda: len(pc.heard) == n + 1, 15))
        lines = fa.log_so_far()
        check("with no race and no knock: the address from a moment ago",
              "the address from a moment ago" in lines and "a race, won" not in lines,
              lines[-600:])
        fa.log_forget()
        drive.kill()
        out = ask("dictate")
        lines = fa.log_so_far()
        check("a new process knocks on the address from last time",
              f"dictated={SENTENCE}" in out and "the address from last time answered" in lines
              and "a race, won" not in lines, lines[-600:])
        files = fa.sealed_files()
        check("what answered is sealed, under a name of its own", "link_routes.bin" in files, files)
        raw = drive.as_app("cat", "no_backup/sealed/link_routes.bin", check=False)
        check("and nothing about it reads in the clear", ADDRESS not in raw)
        is_clean()
    finally:
        pc = getattr(acct, "_door_pc", None)
        if pc:
            pc.down()
        acct.stop()


def flow_other_doors():
    """Every route the keyboard and the app use goes through the door."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        # Nothing of ours up while the proposal appears: Home, which asks again every 8 s
        # while nobody answers, could ring it and lose it to a force-stop (leave_traces).
        drive.kill()
        pc.review = [{"id": "20261107-120000-0001", "when": "2026-11-07 12:00:00", "seconds": 1.0,
                      "text": fa.HEARD, "proposed": fa.MEANT, "source": "phone",
                      "changes": [{"before": fa.HEARD, "after": fa.MEANT, "kind": "replace",
                                   "span": [0, 1], "why": "the sentence"}]}]
        drive.shell("pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS", check=False)
        drive.home()
        check("Home reads Connected for a joined phone with no pasted line",
              drive.wait("^Connected$", 25) is not None)
        check("no step says to point it anywhere", drive.find("Point it") is None)
        check("the second reading reaches Home through the door",
              drive.wait(fa.MEANT, 15) is not None)
        check("and the shade", until(lambda: fa.MEANT in drive.notifications(), 10))
        drive.tap(fa.MEANT)
        drive.wait("^Keep$", 15)
        drive.tap("^Keep$")
        check("Keep travels through the door", until(lambda: bool(pc.decided), 15), str(pc.decided))
        drive.shell("am", "start", "-a", "android.intent.action.PROCESS_TEXT", "-t", "text/plain",
                    "--es", "android.intent.extra.PROCESS_TEXT", "fragile",
                    "-n", f"{PKG}/.LookupActivity")
        check("Lookup too", drive.wait("looked-up", 15) is not None)
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_killed_between():
    """The process dies with a recording on disk and nothing sent: nothing is lost,
    nothing goes by itself, and the keyboard offers it at the next open."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        drive.shell("pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS", check=False)
        pc.down()
        check("a recording goes on the disk first", "kept=true" in ask("keep"))
        out = ask("job")
        check("and its hour's sweep is asked for, with no network to wait for",
              "job=SpoolSweep" in out and "network=0" in out, out)
        drive.die()
        check("the process is gone", not drive.pid())
        check("and the recording is not", until(lambda: len(fa.recordings().split()) == 1, 5),
              fa.recordings())
        pc.up()
        job()                                    # the sweep, a PC up and a network there
        time.sleep(3)
        check("the sweep sends nothing", not pc.heard and not pc.arrived.is_set())
        check("and inside the hour it deletes nothing", len(fa.recordings().split()) == 1,
              fa.recordings())
        drive.home()
        drive.wait("^Connected$", 25)
        time.sleep(2)
        check("Home, finding the PC, sends nothing either", not pc.heard)
        fa.back()
        field()
        check("the keyboard offers it, and says nothing it does not know",
              until(lambda: row_is("Not sent"), 15), status())
        send_again()
        check("a press sends it", until(lambda: len(pc.heard) == 1, 20))
        check("into the field the keyboard is on", until(lambda: SENTENCE in in_field(), 10),
              in_field()[:300])
        check("with no notification", SENTENCE not in drive.notifications())
        check("and the spool has let it go", until(lambda: not fa.recordings().split(), 10),
              fa.recordings())

        # The same with the reply lost: the PC heard it, the phone died listening.
        pc.heard.clear()
        pc.hold.clear()
        pc.arrived.clear()
        hold_and_say()
        check("on its way to the PC", pc.arrived.wait(15))
        drive.die()
        pc.hold.set()
        check("the PC has it", until(lambda: len(pc.heard) == 1, 10))
        check("the phone does not know that, and keeps it", len(fa.recordings().split()) == 1,
              fa.recordings())
        job()
        time.sleep(2)
        check("still nothing goes by itself", len(pc.heard) == 1)
        field()
        check("the keyboard offers it again", until(lambda: row_is("Not sent"), 15), status())
        send_again()
        check("so a press sends it again: a duplicate at the PC, and no word lost",
              until(lambda: len(pc.heard) == 2, 20))
        check("and the spool lets it go once answered", until(lambda: not fa.recordings().split(), 10))
    finally:
        acct._door_pc.hold.set()
        acct._door_pc.down()
        acct.stop()


def flow_pc_off():
    """A PC that is off: why in a few words, Send again into the field the person is
    in, a second no seen as one, and nothing that goes by itself."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        drive.shell("pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS", check=False)
        field()
        hold_and_say()
        check("up, it lands", until(lambda: len(pc.heard) == 1, 15))
        board = row()["board"]
        pc.down()
        hold_and_say()
        check("the keyboard says why in a few words, with Send again and the X",
              until(lambda: row_is(NO_ANSWER), 25), status())
        r = row()
        check("each a thumb's 48dp to the touch, and the keyboard no taller for them",
              r["touch"] >= 48 and abs(r["board"] - board) <= 1, f"touch {r['touch']} board {r['board']} was {board}")
        drive.shot("door_unreached")
        check("the lamp goes grey with it", "reachable=false" in status(), status())
        check("and the recording stays", until(lambda: "waiting=1" in spooled(), 5), spooled())

        # A second press with the PC still off: seen going, and seen coming back no.
        mic = r["mic"]
        seen = []
        send_again()
        check("a press is seen on its way", until(
            lambda: (lambda x: seen.append(x) or x["status"].startswith("Sending"))(row()), 5, 0.1),
              status())
        check("and the mic holds still under it", seen and seen[-1]["mic"] == mic,
              f"mic {seen[-1]['mic'] if seen else '?'} was {mic}")
        check("and a second no comes back as one: why, and Send again again",
              until(lambda: row_is(NO_ANSWER), 25), status())
        check("nothing reached the PC, and the recording still waits",
              len(pc.heard) == 1 and "waiting=1" in spooled(), spooled())

        back_up(pc)
        pc.hold.clear()
        pc.arrived.clear()
        send_again()
        check("a press sends it", pc.arrived.wait(20))
        time.sleep(4)                            # past the line's 3 s, with the one that waited in hand
        r = row()
        check("and the mic holds still while it is on its way", r["mic"] == mic
              and r["status"].startswith("Sending"), f"mic {r['mic']} was {mic}: {r['status']}")
        pc.hold.set()
        check("it lands", until(lambda: len(pc.heard) == 2, 20))
        check("into the same field", until(lambda: in_field().count(SENTENCE) >= 2, 10), in_field()[:300])
        check("and the spool lets it go", until(spool_empty, 10), spooled())
        check("and the line is the keyboard's own again", until(lambda: not row()["drop"], 10), status())

        # Off again, and the field gone before anybody pressed.
        pc.down()
        hold_and_say()
        check("off again, the same few words", until(lambda: row_is(NO_ANSWER), 25), status())
        drive.shell("input", "keyevent", "4")    # the keyboard away
        drive.shell("input", "keyevent", "4")    # and the field with it
        time.sleep(0.5)
        check("the recording outlives its field", until(lambda: "waiting=1" in spooled(), 5), spooled())
        back_up(pc)
        job()
        drive.home()
        check("Home says Connected", drive.wait("^Connected$", 25) is not None)
        time.sleep(2)
        check("and neither Home nor the sweep sent it: not at the PC, not in Said, not on the shade",
              len(pc.heard) == 2 and said().count(SENTENCE) == 2 and SENTENCE not in drive.notifications(),
              f"{len(pc.heard)} {said()[:200]}")
        fa.back()
        field()                                  # another field, later
        # Its words are the last try's, or none once a knock has found the PC: the knock
        # is at most once a minute, so either may be on the line here.
        check("opened later, the keyboard offers it",
              until(lambda: row_is("Not sent") or row_is(NO_ANSWER), 15), status())
        drive.shot("door_waiting_later")
        send_again()
        check("and a press puts it where the person is now", until(lambda: SENTENCE in in_field(), 15),
              in_field()[:300])
        check("with no notification", SENTENCE not in drive.notifications())
        fa.back()
        fa.back()
        drive.home()
        check("Home says Connected", drive.wait("^Connected$", 25) is not None)
        pc.down()
        back = fa.back
        back()
        drive.kill()
        drive.home()
        check("and when the PC is off, Home says that",
              drive.wait("^Can't reach the PC$", 25) is not None)
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_field_gone():
    """The text comes back and the field it was spoken into has gone: it lands in
    Said, with a notification, and the keyboard offers it to the next field."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        drive.shell("pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS", check=False)
        field()
        pc.hold.clear()
        pc.arrived.clear()
        hold_and_say()
        check("on its way to the PC", pc.arrived.wait(15))
        drive.shell("input", "keyevent", "4")    # the keyboard away
        drive.shell("input", "keyevent", "4")    # and the field with it
        time.sleep(1.5)
        pc.hold.set()
        check("it lands in Said", until(lambda: SENTENCE in said(), 15), said()[:300])
        check("with a notification", until(lambda: SENTENCE in drive.notifications(), 10))
        check("and the spool has let it go", until(spool_empty, 10), spooled())
        drive.shot("door_landed")
        field()
        check("the next field is told it can have it", says("Text ready"), status())
        check("this time the field is empty", SENTENCE not in in_field(), in_field()[:200])
        tap_status()
        check("a tap puts it there", until(lambda: SENTENCE in in_field(), 10), in_field()[:200])
    finally:
        acct._door_pc.hold.set()
        acct._door_pc.down()
        acct.stop()


def flow_wrong_pin():
    """Somebody else answers at the PC's address, the phone's own certificate on its
    list and all: it gets no byte, because the pin is in the row and not in the door.
    The recording is kept, and the PC's true row puts it right."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        out = ask("dictate")
        check("the true door takes it", f"dictated={SENTENCE}" in out, out)
        n = len(pc.heard)
        port = pc.door.port
        pc.down()
        phone_mod.rotate()                       # the same port, another certificate
        pc.cfg = dataclasses.replace(pc.cfg, server=dataclasses.replace(pc.cfg.server, phone_port=port - 20000))
        pc.door = server_mod.PhoneDoor(pc.cfg, pc.routes)
        pc.door.start(pc.anchors())
        check("that door stands on the same port, and would let this phone in", pc.door.port == port
              and len(pc.anchors()) == 1)
        pc.arrived.clear()
        drive.kill()
        drive.home()
        drive.wait("^Can't reach the PC$", 30)
        check("Home does not call that door Connected", True)
        out = ask("dictate")
        check("the keyboard's road says what is true", UNREACHED in out, out)
        check("not one byte of the recording reached it", len(pc.heard) == n and not pc.arrived.is_set())
        check("and it stays for the true door", "waiting=1" in spooled(), spooled())
        pc.write()                               # it really is the PC, with a new certificate
        drive.kill()
        drive.home()
        drive.wait("^Connected$", 30)
        check("the true row, and the phone takes the new pin", True)
        time.sleep(2)
        check("Home sends nothing of what waits", len(pc.heard) == n)
        fa.back()
        field()
        check("the keyboard offers it", until(lambda: row()["send"], 15), status())
        send_again()
        check("and a press sends it to the true door", until(lambda: len(pc.heard) == n + 1, 20))
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_forget_other_side():
    """A PC forgets this phone: the door drops it at once, the words go at its next
    question, and the recordings wait for whoever comes back."""
    acct = fa.fresh()
    try:
        row = real_join(acct)
        pc = acct._door_pc
        fa.propose(acct)
        fa.plant(acct)
        drive.kill()
        drive.home()
        drive.wait("^Connected$", 25)
        assert fa.SAID in fa.on_disk()
        cert = phone_mod.fingerprint(phone_mod._phone_cert(acct.open_link(row)))
        # Forget on the PC: the list, the row and the session, then the door.
        acct.write_forgotten([{"device": row["id"], "cert": cert, "at": fake_pc.now_iso()}])
        with acct.mutex:
            acct.tables["devices"] = [r for r in acct.tables["devices"] if r["id"] != row["id"]]
        acct.end_every_session()
        pc.up()
        check("the door has dropped this phone", cert not in pc.anchors())
        n = len(pc.heard)
        out = ask("dictate")
        print("      after the Forget:", out, flush=True)
        check("the door took nothing", len(pc.heard) == n)
        check("the session has gone, and it said nothing of the phone's lock",
              "notnow" not in out, out)
        fa.no_traces(acct, "forgotten from a PC")
        files = fa.sealed_files()
        check("and where the PC is went with the words", "link_routes.bin" not in files
              and "device_rows.bin" not in files, files)
        check("the recording waits", fa.recordings().strip() != "", fa.recordings())
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_every_road_out():
    """Each road out of the account takes what Link remembers, and a send in flight
    lands nowhere."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        drive.shell("pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS", check=False)
        drive.kill()
        drive.home()
        drive.wait("^Connected$", 25)
        check("an address is remembered", until(lambda: "link_routes.bin" in fa.sealed_files(), 5))

        # Out mid-send: the PC is holding the recording when the words go.
        pc.hold.clear()
        pc.arrived.clear()
        ask("keep")
        fa.back()
        field()
        check("the keyboard offers what waits", until(lambda: row()["send"], 15), status())
        send_again()
        check("a press sends it on its way", pc.arrived.wait(20))
        fa.told("--es", "wipe", "1")
        check("the wipe took the addresses", "link_routes.bin" not in fa.sealed_files(), fa.sealed_files())
        pc.hold.set()
        time.sleep(1.5)
        check("what comes back lands nowhere: not in Said", SENTENCE not in said(), said()[:300])
        check("not on the shade", SENTENCE not in drive.notifications())
        check("not in the field", SENTENCE not in in_field(), in_field()[:200])
        check("and the addresses stay gone", "link_routes.bin" not in fa.sealed_files(), fa.sealed_files())
        check("a recording that went out with the wipe is still here for the same person",
              len(fa.recordings().split()) == 1, fa.recordings())
        fa.back()
        fa.back()

        # Sign out: everything.
        drive.kill()
        drive.home()
        drive.wait("^Connected$|^Can't reach", 25)
        ask("reach")
        fa.to_settings()
        drive.wait("^Sign out$", 20)
        drive.tap_scrolling("^Sign out$")
        drive.wait("^Sign out of this phone\\?$", 10)
        drive.tap_scrolling("^Sign out$")
        check("signed out", until(lambda: not acct.sessions, 20))
        check("no address left", until(lambda: not [f for f in fa.sealed_files().split()
                                                    if "link" in f or "rows" in f], 10),
              fa.sealed_files())
        check("no recording left", not fa.recordings().split(), fa.recordings())
        check("the road is gone with them", "link pcs= " in ask("pcs"), ask("pcs"))
    finally:
        acct._door_pc.hold.set()
        acct._door_pc.down()
        acct.stop()


def old_door(pc: Pc):
    """The loopback door, real, with its bearer: what `tailscale serve` proxies to, and
    what the pasted line reaches here. Off the emulator it is 10.0.2.2 and plain HTTP,
    the one address network_security_config lets through that way."""
    cfg = dataclasses.replace(pc.cfg, server=dataclasses.replace(
        pc.cfg.server, enabled=True, host="127.0.0.1", port=8756))
    door = server_mod.PhoneServer(cfg, pc._transcribe, lambda: "fake", pc._translate,
                                  pc._punctuate, None, review_pending=pc.routes.review_pending,
                                  review_decide=pc._decide, lookup=pc._lookup)
    door.routes.max_chars = 5000
    door.start()
    return door


def press(key: str) -> None:
    fa.told("--es", "ime", f"key:{key}")


def flow_old_road():
    """The pasted line beside the door, and without it: every old road still works,
    against the real loopback door and its bearer."""
    acct = fa.fresh()
    pc = acct._door_pc = Pc(acct, text="heard-on-the-old-road")
    old = old_door(pc)
    try:
        fa.told("--es", "url", f"http://10.0.2.2:{old.port}", "--es", "token", server_mod.load_token())
        pc.review = [{"id": "20261107-130000-0001", "when": "2026-11-07 13:00:00", "seconds": 1.0,
                      "text": fa.HEARD, "proposed": fa.MEANT, "source": "phone",
                      "changes": [{"before": fa.HEARD, "after": fa.MEANT, "kind": "replace",
                                   "span": [0, 1], "why": "the sentence"}]}]
        drive.shell("pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS", check=False)
        drive.kill()
        drive.home()
        check("a pasted line alone is Connected, with no account at all",
              drive.wait("^Connected$", 25) is not None)
        check("the second reading comes down it", drive.wait(fa.MEANT, 15) is not None)
        out = ask("dictate")
        check("it dictates over the old road", "dictated=heard-on-the-old-road" in out, out)
        drive.tap(fa.MEANT)
        drive.wait("^Keep$", 15)
        drive.tap("^Keep$")
        check("Keep goes back up it", until(lambda: bool(pc.decided), 15), str(pc.decided))
        drive.shell("am", "start", "-a", "android.intent.action.PROCESS_TEXT", "-t", "text/plain",
                    "--es", "android.intent.extra.PROCESS_TEXT", "fragile",
                    "-n", f"{PKG}/.LookupActivity")
        check("Lookup too", drive.wait("looked-up", 15) is not None)
        fa.back()
        field()
        hold_and_say()
        check("a real hold, too", until(lambda: "heard-on-the-old-road" in in_field(), 15), in_field()[:200])
        drive.shell("input", "text", "shalom")
        press("punctuate")
        check("the punctuate key", until(lambda: "." in in_field(), 15), in_field()[:200])
        fa.told("--es", "url", f"http://10.0.2.2:{old.port}", "--es", "token", "the-wrong-token")
        out = ask("dictate")
        check("a wrong token says so, and keeps the recording", "bad token" in out and "BUSY" in out, out)
        check("in the spool", "waiting=1" in spooled(), spooled())
        fa.told("--es", "url", f"http://10.0.2.2:{old.port}", "--es", "token", server_mod.load_token())

        pc.text = SENTENCE
        fa.back()
        fa.back()
        drive.kill()
        real_join(acct)
        pc = acct._door_pc
        old.routes.transcribe = lambda wav: ("the-old-road-spoke", "fake", None)
        out = ask("dictate")
        check("joined, the door comes first", f"dictated={SENTENCE}" in out, out)
        pc.down()
        pc.write(addrs=[])
        drive.kill()
        out = ask("dictate")
        check("door down, the pasted line carries it", "dictated=the-old-road-spoke" in out, out)
    finally:
        acct._door_pc.down()
        old.stop()
        acct.stop()


def flow_keys():
    """The keys that send what is in the field, on the door. Translate takes Hebrew
    and nothing else, and adb cannot type it, so the field is dictated into."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        pc.text = "שלום עולם"
        field()
        hold_and_say()
        check("something in the field", until(lambda: pc.text in in_field(), 15), in_field()[:200])
        press("punctuate")
        check("the punctuate key goes through the door", until(lambda: pc.text + "." in in_field(), 15),
              in_field()[:200])
        press("translate")
        check("and translate", until(lambda: "in-english" in in_field(), 15), in_field()[:200])
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_no_address():
    """A PC's row with no address is a fact of a moment: the phone reads it again."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        check("the row was read, words_sync and all", "link pcs=1:true " in ask("pcs"), ask("pcs"))
        pc.down()                                # the switch goes off on the PC
        drive.kill()                             # nothing fresh in memory either
        pc.write(addrs=[], words_sync=False)
        drive.kill()
        drive.home()
        drive.wait("^Can't reach the PC$", 25)
        check("a PC with its switch off is not reachable, and says no more than that", True)
        fa.to_settings()                         # Settings reads the rows
        drive.wait("HOME-PC", 20)
        check("a row with no address is read as one", "link pcs=0:false " in ask("pcs"), ask("pcs"))
        fa.back()
        pc.up()                                  # the switch comes on: a row the phone has not read
        drive.kill()                             # a new process, and no address to try
        out = ask("reach")
        check("an empty row sends the phone back to the account, and it finds the door",
              "reach=" in out and "nobody" not in out, out)
        # No door at all, as an older DeskIT has: nothing was there to reach, and
        # Home says not connected yet, not "can't reach".
        pc.down()
        with acct.mutex:
            for row in acct.tables["devices"]:
                if row["id"] == pc.device:
                    row["link"] = None
        drive.kill()
        drive.home()
        check("no PC of the account has a door: Not connected yet",
              until(lambda: drive.find("^Not connected yet$") is not None, 30), drive.screen()[:300])
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_two_pcs():
    """Two PCs: one with its model off is passed over, and the one that answers
    gets the dictation."""
    acct = fa.fresh()
    try:
        real_join(acct)
        first = acct._door_pc
        first.model_off = True
        other = Pc(acct, device=fake_pc.uuid.uuid4().__str__(), name="OFFICE-PC", text="the-other-pc")
        other.cfg = dataclasses.replace(other.cfg, server=dataclasses.replace(other.cfg.server, phone_port=8768))
        other.up()
        drive.kill()
        ask("reach")
        fa.to_settings()
        drive.wait("OFFICE-PC", 20)
        fa.back()
        out = ask("dictate")
        check("a model that is off is passed over for the PC that can", "dictated=the-other-pc" in out, out)
        check("and is sent the recording once: it answered, so no knock and no second time",
              first.asked_off == 1, f"asked {first.asked_off} times")
        other.down()
        out = ask("dictate")
        check("with no other PC, its own sentence comes back", "speech model is off" in out, out)
        check("and the recording stays", "refused=BUSY" in out, out)
    finally:
        acct._door_pc.down()
        acct.stop()


def zeros(name: str, size: int) -> None:
    """A recording of [size] zero bytes in the app's spool: dd, because Android 8's
    head has no -c."""
    drive.as_app("sh", "-c", f"'dd if=/dev/zero of=files/spool/{name} bs={size // 10} count=10 2>/dev/null'")


def flow_spool_rules():
    """The hour and the cap, on the phone's own disk, and a sweep that only deletes."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        now = fa.phone_ms()
        minute = 60_000
        drive.as_app("mkdir", "-p", "files/spool")
        old = f"{now - 61 * minute:013d}-aaaaaaaa.wav"
        kept = f"{now - 50 * minute:013d}-bbbbbbbb.wav"
        for name in (old, kept):
            zeros(name, 40_000)
        ask("sweep")                             # the sweep asked for, and nothing pruned yet
        fa.log_forget()
        job()
        check("past its hour it goes, by the sweep", until(lambda: old not in fa.recordings(), 15)
              and until(lambda: "the sweep took 1" in fa.log_so_far(), 10), fa.recordings())
        check("ten minutes short of it stays", kept in fa.recordings().split(), fa.recordings())
        check("and the sweep sent nothing, the PC up and all", not pc.heard and not pc.arrived.is_set())
        out = ask("job")
        wait = int(re.search(r"wait=(\d+)", out).group(1)) if "wait=" in out else -1
        check("the next sweep is the next one's hour, and asks for no network",
              "job=SpoolSweep" in out and "network=0" in out and 8 * minute < wait <= 10 * minute, out)
        late = f"{now - 61 * minute:013d}-eeeeeeee.wav"
        zeros(late, 40_000)
        drive.shell("input", "keyevent", "3")    # away first: a Home already in front is not opened
        time.sleep(1)
        drive.home()
        check("Home's open takes one past its hour", until(lambda: late not in fa.recordings(), 10),
              fa.recordings())
        fa.back()
        zeros(late, 40_000)
        field()
        check("and so does the keyboard's", until(lambda: late not in fa.recordings(), 10), fa.recordings())
        fa.back()
        fa.back()
        for i in range(6):
            name = f"{now - (5 - i) * minute:013d}-cccccc0{i}.wav"
            zeros(name, 10_000_000)
        out = ask("keep")
        files = fa.recordings().split()
        check("past 50 MB the oldest goes first, as a net that says nothing on screen",
              "dropped=2" in out, out)
        check("the oldest two were the two that went", kept not in files
              and not [f for f in files if f.endswith("cccccc00.wav")], str(files))
        drive.as_app("rm", "-rf", "files/spool")
        ask("prune")
        check("with nothing on the disk, no sweep", "job=none" in ask("job"), ask("job"))
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_soft_key():
    """A phone whose Keystore will not do TLS: the software key takes over, the row
    carries it, and the real door takes it."""
    acct = fa.fresh()
    try:
        row = real_join(acct)
        pc = acct._door_pc
        before = phone_mod.fingerprint(phone_mod._phone_cert(acct.open_link(row)))
        ask("soft")
        check("a new certificate goes out in the row", until(lambda: phone_mod.fingerprint(
            phone_mod._phone_cert(acct.open_link(acct.phones()[0]))) != before, 15))
        pc.up()
        check("and the door lists it", before not in pc.anchors() and len(pc.anchors()) == 1)
        out = ask("dictate")
        check("a hand-written certificate on a software key gets in", f"dictated={SENTENCE}" in out, out)
        check("sealed by the Keystore", "client_soft.bin" in fa.sealed_files(), fa.sealed_files())
        raw = drive.as_app("cat", "no_backup/sealed/client_soft.bin", check=False)
        check("and nothing of it reads in the clear", "key" not in raw and "cert" not in raw)
        drive.kill()
        out = ask("dictate")
        check("a new process finds it", f"dictated={SENTENCE}" in out, out)
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_self_test():
    """The first thing asked of a key is a whole handshake, here, with no network."""
    acct = fa.fresh()
    try:
        fa.log_forget()
        real_join(acct)
        lines = fa.log_so_far()
        check("this phone's Keystore key does TLS, in memory", "client key: TLS holds" in lines,
              lines[-500:])
        print("     ", [ln.split("client key:")[1] for ln in lines.splitlines() if "client key:" in ln][:2],
              flush=True)
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_locked():
    """A phone that cannot open what it sealed is not signed out, and not on any road."""
    if fa.sdk() < WIFI_ONLY:
        return
    pin = "1234"
    acct = fa.fresh()
    try:
        drive.shell("locksettings", "set-pin", pin)
        time.sleep(1)
        real_join(acct)
        pc = acct._door_pc
        out = ask("dictate")
        check("unlocked, it dictates", f"dictated={SENTENCE}" in out, out)
        fa.lock_screen()
        time.sleep(2)
        n = len(pc.heard)
        out = ask("dictate")
        print("      locked:", out, flush=True)
        check("locked, it asks to be unlocked", "Unlock the phone" in out, out)
        check("the door took nothing", len(pc.heard) == n)
        check("and it is still in the account", bool(acct.sessions) and "account_key.bin" in fa.sealed_files())
        check("the recording waits", "waiting=1" in spooled(), spooled())
        fa.unlock(pin)
        time.sleep(2)
        check("unlocked, nothing goes by itself", len(pc.heard) == n)
        field()
        check("the keyboard offers it", until(lambda: row()["send"], 15), status())
        send_again()
        check("and a press sends it", until(lambda: len(pc.heard) == n + 1, 20))
        fa.back()
        fa.back()
    finally:
        drive.shell("locksettings", "clear", "--old", pin, check=False)
        acct._door_pc.down()
        acct.stop()


def flow_upgrade():
    """A screen lock comes after the keys: they become unusable under it, by
    themselves, and the door still takes this phone."""
    if fa.sdk() < WIFI_ONLY:
        return
    pin = "1234"
    acct = fa.fresh()
    try:
        row = real_join(acct)
        pc = acct._door_pc
        before = phone_mod.fingerprint(phone_mod._phone_cert(acct.open_link(row)))
        time.sleep(3)                            # Home's own look comes to its end first
        drive.shell("locksettings", "set-pin", pin)
        time.sleep(1)
        fa.lock_screen()
        time.sleep(2)
        now = fa.probe()
        check("right after the PIN nothing has moved yet", "sealed=opened" in now and "signs=signed" in now, now)
        fa.unlock(pin)
        drive.home()
        check("a look gives the phone a new client key", until(lambda: phone_mod.fingerprint(
            phone_mod._phone_cert(acct.open_link(acct.phones()[0]))) != before, 25))
        pc.up()
        out = ask("dictate")
        check("the door takes the new key", f"dictated={SENTENCE}" in out, out)
        files = drive.shell("sh", "-c", f"'run-as {PKG} ls no_backup/sealed'", check=False)
        fa.lock_screen()
        time.sleep(2)
        now = fa.probe()
        print("      locked:", now, flush=True)
        check("locked, what is sealed does not open", "sealed=notnow" in now, now)
        check("and the key does not sign", "signs=refused" in now, now)
        fa.unlock(pin)
        now = fa.probe()
        check("unlocked, all of it comes back", "sealed=opened" in now and "signs=signed" in now, now)
        check("and the session is the one it had", len(acct.sessions) == 1 and bool(files))
    finally:
        drive.shell("locksettings", "clear", "--old", pin, check=False)
        acct._door_pc.down()
        acct.stop()


class NoInternet:
    """M13's shape, on the emulator's two real networks: the Wi-Fi is up and has no
    internet, mobile data has and is the default, and mobile data cannot reach the
    PC, as it cannot at home. Android's own check is pointed at a small server here
    and refused on the Wi-Fi, so Android decides this by itself, once the radio has
    been round: nothing short of that makes it look again. An emulator's mobile data
    takes a handful of those and then stays off until a reboot, so a flow does this
    once and looks at everything inside it.

    [close] files the system's own background request for Wi-Fi, which takes
    FOREGROUND off a Wi-Fi that is not the default: `wifi_always_requested`."""
    CHECK = 18792
    NAMES = ("captive_portal_mode", "captive_portal_use_https", "captive_portal_http_url",
             "captive_portal_https_url", "captive_portal_fallback_url", "wifi_always_requested")

    def __init__(self, door_port: int):
        self.door_port = door_port

    def rules(self, verb: str) -> None:
        for line in (f"iptables {verb} OUTPUT -o wlan0 -p tcp --dport {self.CHECK} -j REJECT",
                     f"iptables {verb} OUTPUT -o eth0 -d {ADDRESS} -p tcp --dport {self.door_port} -j REJECT"):
            drive.shell(*line.split(), check=False)

    @staticmethod
    def radio() -> None:
        drive.shell("svc", "data", "disable")
        time.sleep(3)
        drive.shell("svc", "data", "enable")

    def __enter__(self):
        class Check(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", self.CHECK), Check)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        url = f"http://10.0.2.2:{self.CHECK}/generate_204"
        for name, value in zip(self.NAMES, ("1", "0", url, url, url)):
            drive.shell("settings", "put", "global", name, value)
        self.rules("-I")
        self.radio()
        return self

    def close(self) -> None:
        drive.shell("settings", "put", "global", "wifi_always_requested", "1")

    def __exit__(self, *a):
        self.rules("-D")
        for name in self.NAMES:
            drive.shell("settings", "delete", "global", name, check=False)
        self.radio()
        # A Wi-Fi that was in the background keeps a mark in netd after it comes back
        # as the default, and nothing on the phone can use it: "Network is unreachable",
        # from ping and Chrome alike. A new connection is a new network.
        drive.shell("cmd", "wifi", "set-wifi-enabled", "disabled", check=False)
        time.sleep(3)
        drive.shell("cmd", "wifi", "set-wifi-enabled", "enabled", check=False)
        self.server.shutdown()
        self.server.server_close()
        settled()


def flow_bound_wifi():
    """Android keeps the app on mobile data because the Wi-Fi has no internet, and
    the door is on that Wi-Fi: "no internet needed" holds all the same."""
    if fa.sdk() < WIFI_ONLY:
        return
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        if "uid=0" not in drive.shell("id"):
            drive.adb("root")
            time.sleep(3)
            drive.adb("wait-for-device")
        if not until(lambda: "MOBILE" in drive.shell("dumpsys", "connectivity"), 60):
            print("      the emulator's mobile data has gone: a reboot", flush=True)
            pc.down()
            acct.stop()
            reboot()
            acct = fa.fresh()
            real_join(acct)
            pc = acct._door_pc
        with NoInternet(pc.door.port) as shape:
            check("mobile data is the default, the Wi-Fi still up", until(_on_mobile, 60),
                  drive.shell("dumpsys", "connectivity")[:200])
            for closed in (False, True):
                road = "a Wi-Fi closed to apps" if closed else "a Wi-Fi nobody asked for"
                if closed:
                    shape.close()
                    check(f"{road}: Android has taken FOREGROUND off it",
                          until(lambda: "FOREGROUND" not in _wifi_caps(), 15), _wifi_caps()[:160])
                fa.log_forget()
                out = ask("dictate")
                lines = fa.log_so_far()
                print(f"      {road}:", out, flush=True)
                print("     ", [ln[33:] for ln in lines.splitlines() if "link:" in ln or "no answer" in ln],
                      flush=True)
                check(f"{road}: the door answers all the same", f"dictated={SENTENCE}" in out, out)
                check(f"{road}: on the Wi-Fi by name", "on wifi" in lines, lines[-400:])
                raw = ask(f"try:{pc.door.port}")
                print(f"      {road}, raw:", raw, flush=True)
                check(f"{road}: and on no other road", "unbound ok" not in raw, raw)
    finally:
        acct._door_pc.down()
        acct.stop()


def _wifi_caps() -> str:
    for line in drive.shell("dumpsys", "connectivity").splitlines():
        if "NetworkAgentInfo{" in line and "WIFI CONNECTED" in line:
            return line[line.find("nc{"):]
    return ""


def _wifi_default() -> bool:
    """The emulator as it boots: the Wi-Fi up and the default, mobile data beside it."""
    out = drive.shell("dumpsys", "connectivity")
    m = re.search(r"Active default network: (\d+)", out)
    agents = [ln for ln in out.splitlines() if "NetworkAgentInfo{" in ln]
    default = [ln for ln in agents if m and f"network{{{m.group(1)}}}" in ln]
    return bool(default) and "WIFI CONNECTED" in default[0] and any("MOBILE" in ln for ln in agents)


def settled() -> None:
    """Both networks back as they boot, or a reboot: a flow after this one must not
    sign in through a phone whose networks are still moving under its browser."""
    if until(lambda: _wifi_default() and "1 received" in drive.shell(
            "ping", "-c", "1", "-W", "2", ADDRESS, check=False), 60):
        return
    print("      the emulator's networks did not come back: a reboot", flush=True)
    reboot()


def reboot() -> None:
    """A fresh emulator, as emu.py leaves one: its mobile data does not always come back
    from a round of the radio, and nothing short of this brings it back."""
    drive.adb("reboot", check=False)
    time.sleep(5)
    drive.adb("wait-for-device", timeout=300)
    assert until(lambda: drive.shell("getprop", "sys.boot_completed", check=False).strip() == "1",
                 300, 3), "the emulator did not come back"
    time.sleep(8)
    drive.adb("root", check=False)
    time.sleep(3)
    drive.adb("wait-for-device", timeout=120)
    for name in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
        drive.shell("settings", "put", "global", name, "0")
    drive.shell("svc", "power", "stayon", "true")
    drive.shell("input", "keyevent", "82")
    drive.shell("settings", "put", "global", "hide_error_dialogs", "1")
    drive.adb("logcat", "-G", "8M", check=False)


def _on_mobile() -> bool:
    """Mobile data is the default and a Wi-Fi is up beside it."""
    out = drive.shell("dumpsys", "connectivity")
    m = re.search(r"Active default network: (\d+)", out)
    if not m:
        return False
    agents = [ln for ln in out.splitlines() if "NetworkAgentInfo{" in ln]
    default = [ln for ln in agents if f"network{{{m.group(1)}}}" in ln]
    return bool(default) and "MOBILE" in default[0] and any("WIFI CONNECTED" in ln for ln in agents)


def flow_timing():
    """How long a dictation takes the phone, from the recording on the disk to the
    text back: the probe's own clock. An emulator, a fake model: what this says is
    what the road costs, and nothing about a real phone's."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc

        def one() -> int:
            out = ask("dictate")
            assert f"dictated={SENTENCE}" in out, out
            return int(re.search(r"ms=(\d+)", out).group(1))

        one()
        waiting = lambda: drive.shell("ss", "-tn", "state", "close-wait", check=False).count(":" + str(pc.door.port))
        before = waiting()
        warm = sorted(one() for _ in range(10))
        after = waiting()
        print(f"      sockets the PC closed and the phone has not: {before} before ten, {after} after",
              flush=True)
        cold = []
        for _ in range(3):
            drive.kill()
            cold.append(one())
        for _ in range(5):
            print("     ", ask("parts"), flush=True)
        t_door = []
        heard = len(pc.heard)
        port = pc.door.port
        pc.down()
        t0 = time.time()
        out = ask("dictate")
        off = int(re.search(r"ms=(\d+)", out).group(1))
        print(f"      warm, the address from last time: {warm} (median {warm[len(warm) // 2]} ms)", flush=True)
        print(f"      a new process, a race each time: {cold}", flush=True)
        print(f"      the PC off, until the keyboard says so: {off} ms", flush=True)
        check("measured", UNREACHED in out and port > 0, out)
    finally:
        acct._door_pc.down()
        acct.stop()


def pc_words() -> dict:
    """The PC's own sentences as main.py and models.py write them today, read from
    the files: a change there is a change here."""
    import ast

    import models as models_mod

    words = {}
    for node in ast.walk(ast.parse((ROOT / "main.py").read_text("utf-8"))):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ("MODEL_OFF_WORDS", "ROOM_OFF_WORDS", "LOCK_WORDS")):
            words[node.targets[0].id] = ast.literal_eval(node.value)
    words["absent"] = models_mod._WHY["absent"]
    return words


class NotThePc(http.server.ThreadingHTTPServer):
    """Something at the pasted address that answers 200 with a page of its own, as a
    portal or a proxy would: not the PC's JSON."""

    def __init__(self):
        class Page(http.server.BaseHTTPRequestHandler):
            def _page(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                body = b"<html><body>Welcome to the network</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _page

            def log_message(self, *a):
                pass

        super().__init__(("127.0.0.1", 0), Page)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def stop(self):
        self.shutdown()
        self.server_close()


def flow_reasons():
    """Why, in a few words, for every kind of no a dictation can meet, on the real
    keyboard: the PC's own sentences as main.py and models.py write them, the
    phone's own words, the old road's token, an answer that is not the PC's. And
    a private field, where none of it is offered."""
    said = pc_words()
    acct = fa.fresh()
    old = page = None
    try:
        real_join(acct)
        pc = acct._door_pc
        field()
        pc.down()
        kinds = [
            ("no_answer", None, NO_ANSWER),
            ("model_off", said["MODEL_OFF_WORDS"], "The model is off on your PC"),
            ("model_for_a_game", said["ROOM_OFF_WORDS"].format(name="a game"),
             "The model is off on your PC"),
            ("pc_signed_out", said["LOCK_WORDS"], "Your PC is signed out"),
            ("pc_no_model", said["absent"].format(repo="the model", size="1.6 GB"),
             "Your PC's speech model isn't ready"),
            ("pc_error", "", "Your PC answered with error 503"),
            ("pc_own_words", "the microphone on this PC is busy", "The microphone on this PC is busy"),
        ]
        for kind, words, expect in kinds:
            if words is not None and not pc.door.port:
                back_up(pc)
            pc.fail = words
            hold_and_say()
            check(f"{kind}: {expect}", until(lambda: row_is(expect), 25), status())
            drive.shot(f"reason_{kind}")
            drop_waiting()
            check(f"{kind}: and the X deletes it", until(
                lambda: "waiting=0" in spooled() and not row()["drop"], 10), spooled())
        pc.fail = None
        check("none of it reached the PC as a dictation", not pc.heard)

        for kind, expect in (("locked", "The phone was locked"),
                             ("keystore", "The phone's secure storage didn't answer")):
            fa.told("--es", "ime", f"fail:{kind}")
            check(f"{kind}: {expect}", until(lambda: row_is(expect), 10), status())
            drive.shot(f"reason_{kind}")
            drop_waiting()

        pc.down()
        old = old_door(pc)
        fa.told("--es", "url", f"http://10.0.2.2:{old.port}", "--es", "token", "the-wrong-token")
        hold_and_say()
        check("token: Your PC refused the token", until(lambda: row_is("Your PC refused the token"), 25),
              status())
        drive.shot("reason_token")
        drop_waiting()
        page = NotThePc()
        fa.told("--es", "url", f"http://10.0.2.2:{page.server_port}", "--es", "token", "any")
        hold_and_say()
        check("not the PC: Couldn't read the answer", until(lambda: row_is("Couldn't read the answer"), 25),
              status())
        drive.shot("reason_unreadable")

        # It waits; a password field offers none of it, and the field after it does again.
        private_field()
        r = row()
        check("a private field: neither Send again nor the X, and the field's own words",
              not r["send"] and not r["drop"] and "private" in r["status"], r["raw"])
        fa.back()
        fa.back()
        field()
        check("the next field offers it again", until(lambda: row()["send"], 15), status())
        drop_waiting()
    finally:
        if old:
            old.stop()
        if page:
            page.stop()
        acct._door_pc.down()
        acct.stop()


def flow_two_waiting():
    """Two that did not arrive: the line counts them, a press sends them all, oldest
    first, each at the cursor; one that fails mid-run stops it with what is left; the
    X deletes everything that waits and sends nothing."""
    said = pc_words()
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        # The PC tells the two apart by their length: the older is the shorter.
        pc.text = lambda wav: "the-longer-one" if len(wav) > 100_000 else "the-shorter-one"
        field()
        pc.down()
        hold_and_say(2.0)
        assert until(lambda: row_is(NO_ANSWER), 25), status()
        hold_and_say(4.0)
        check("two wait, counted, with why", until(lambda: row_is("2 not sent · " + NO_ANSWER), 25), status())
        drive.shot("two_waiting")
        back_up(pc)
        send_again()
        check("a press sends them all", until(lambda: len(pc.heard) == 2, 30), str(len(pc.heard)))
        check("oldest first, each at the cursor", until(
            lambda: re.search("the-shorter-one.*the-longer-one", in_field()) is not None, 10), in_field()[:300])
        check("and nothing waits", until(spool_empty, 10), spooled())

        # The first lands, the second meets a model that went off between the two.
        pc.down()
        hold_and_say(2.0)
        assert until(lambda: row_is(NO_ANSWER), 25), status()
        hold_and_say(4.0)
        assert until(lambda: row_is("2 not sent · " + NO_ANSWER), 25), status()
        back_up(pc)

        def then_off(wav):
            pc.fail = said["MODEL_OFF_WORDS"]
            return "the-first-of-two"
        pc.text = then_off
        send_again()
        check("one that fails mid-run stops it: what is left, and why as it is now",
              until(lambda: row_is("The model is off on your PC"), 30), status())
        check("the first landed", "the-first-of-two" in in_field(), in_field()[:300])
        check("and one waits", "waiting=1" in spooled(), spooled())
        pc.fail = None

        # The X takes everything, and sends nothing.
        pc.down()
        hold_and_say()
        assert until(lambda: row_is("2 not sent · " + NO_ANSWER), 25), status()
        heard = len(pc.heard)
        drop_waiting()
        check("the X deletes everything that waits", until(lambda: spool_empty() and not row()["drop"], 10),
              spooled())
        pc.up()
        time.sleep(2)
        check("and sends nothing", len(pc.heard) == heard)
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_small_phone():
    """A 320dp phone and larger text: the words may wrap, Send again and the X are
    never cut, and the keyboard still sends."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        field()
        pc.down()
        hold_and_say()
        assert until(lambda: row_is(NO_ANSWER), 25), status()
        hold_and_say()
        assert until(lambda: row_is("2 not sent · " + NO_ANSWER), 25), status()
        for name, density, scale in (("320dp", "540", "1.0"), ("larger_text", "reset", "1.3"),
                                     ("320dp_larger_text", "540", "1.3")):
            drive.shell("wm", "density", density)
            drive.shell("settings", "put", "system", "font_scale", scale)
            time.sleep(3)
            check(f"{name}: why, Send again and the X are there, none of them cut short",
                  until(lambda: (lambda r: r["send"] and r["drop"] and not r["cut"] and not r["ellipsis"]
                                 and r["touch"] >= 48 and "not sent" in r["status"])(row()), 20), status())
            drive.shot(f"row_{name}")
        back_up(pc)
        send_again()
        check("and on the smallest, a press sends them", until(lambda: len(pc.heard) == 2, 30))
    finally:
        drive.shell("wm", "density", "reset", check=False)
        drive.shell("settings", "put", "system", "font_scale", "1.0", check=False)
        acct._door_pc.down()
        acct.stop()


FLOWS = {name[5:]: fn for name, fn in list(globals().items()) if name.startswith("flow_")}


def main() -> None:
    apk = Path(os.environ.get("DESKIT_APK")
               or ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk")
    if not fa.built_for_the_fake(apk):
        sys.exit("this APK speaks to the real project, and no flow may: "
                 "gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791")
    drive.adb("install", "-r", "-g", apk, timeout=300)
    drive.adb("logcat", "-G", "8M", check=False)
    if fa.sdk() >= WIFI_ONLY:
        settled()
    names = sys.argv[1:] or list(FLOWS)
    try:
        for name in names:
            print(f"--- {name}", flush=True)
            try:
                FLOWS[name]()
            except (AssertionError, subprocess.TimeoutExpired) as e:
                check(f"{name} ran to its end", False, str(e)[:500])
                drive.shot(f"failed_door_{name}")
    finally:
        shutil.rmtree(HOME, ignore_errors=True)
    print(f"{fa._passed} passed, {fa._failed} failed", flush=True)
    sys.exit(1 if fa._failed else 0)


if __name__ == "__main__":
    main()
