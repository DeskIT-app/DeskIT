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
            raise RuntimeError("The speech model is off. Start it on the PC.")
        self.heard.append(wav)
        return self.text, "fake", None

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


def hold_and_say(seconds: float = 1.6) -> None:
    """A real press, held and let go: the real recorder, with a voice the emulator
    has not got. Blocks until the finger is up."""
    x, y = spot("pill")
    finger = threading.Thread(target=lambda: drive.shell(
        "input", "swipe", x, y, x, y, int(seconds * 1000), check=False))
    finger.start()
    time.sleep(0.5)
    fa.told("--es", "ime", "loud")
    finger.join()


def said() -> str:
    return fa.on_disk()


def spooled() -> str:
    return fa.told("--es", "link", "count")


def spool_empty() -> bool:
    return "waiting=0" in spooled()


def job() -> None:
    """The system gives the background its turn: a network has come."""
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
        check("with no race: the address from last time answered",
              "the address from last time answered" in lines and "a race, won" not in lines,
              lines[-600:])
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
        pc.review = [{"id": "20261107-120000-0001", "when": "2026-11-07 12:00:00", "seconds": 1.0,
                      "text": fa.HEARD, "proposed": fa.MEANT, "source": "phone",
                      "changes": [{"before": fa.HEARD, "after": fa.MEANT, "kind": "replace",
                                   "span": [0, 1], "why": "the sentence"}]}]
        drive.shell("pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS", check=False)
        drive.kill()
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
    and it lands in Said with a notification, the field long gone."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        drive.shell("pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS", check=False)
        pc.down()
        check("a recording goes on the disk first", "kept=true" in ask("keep"))
        drive.die()
        check("the process is gone", not drive.pid())
        check("and the recording is not", until(lambda: len(fa.recordings().split()) == 1, 5),
              fa.recordings())
        pc.up()
        job()
        check("the next link sends it, with nobody in front", until(lambda: bool(pc.heard), 20))
        check("it lands in Said", until(lambda: SENTENCE in said(), 10), said()[:300])
        check("with a notification", until(lambda: SENTENCE in drive.notifications(), 10))
        check("and the spool has let it go", until(lambda: not fa.recordings().split(), 10),
              fa.recordings())

        # The same with the reply lost: the PC heard it, the phone died listening.
        pc.heard.clear()
        pc.hold.clear()
        pc.arrived.clear()
        field()
        hold_and_say()
        check("on its way to the PC", pc.arrived.wait(15))
        drive.die()
        pc.hold.set()
        check("the PC has it", until(lambda: len(pc.heard) == 1, 10))
        check("the phone does not know that, and keeps it", len(fa.recordings().split()) == 1,
              fa.recordings())
        job()
        check("so it goes again: a duplicate at the PC, and no word lost",
              until(lambda: len(pc.heard) == 2, 20))
        check("and the spool lets it go once answered", until(lambda: not fa.recordings().split(), 10))
    finally:
        acct._door_pc.hold.set()
        acct._door_pc.down()
        acct.stop()


def flow_pc_off():
    """A PC that is off: the sentence that is true, the recording kept, and the text
    when the PC comes back."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        drive.shell("pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS", check=False)
        field()
        hold_and_say()
        check("up, it lands", until(lambda: len(pc.heard) == 1, 15))
        pc.down()
        hold_and_say()
        check("the keyboard says what is true, and offers the tap",
              says(UNREACHED + ".*tap to retry"), status())
        drive.shot("door_unreached")
        check("the lamp goes grey with it", "reachable=false" in status(), status())
        check("and the recording stays", until(lambda: "waiting=1" in spooled(), 5), spooled())
        pc.up()
        tap_status()
        check("a tap sends it", until(lambda: len(pc.heard) == 2, 20))
        check("into the same field", until(lambda: in_field().count(SENTENCE) >= 2, 10), in_field()[:300])
        check("and the spool lets it go", until(spool_empty, 10), spooled())

        pc.down()
        hold_and_say()
        check("off again, the same sentence", says(UNREACHED), status())
        drive.shell("input", "keyevent", "4")    # the keyboard away
        drive.shell("input", "keyevent", "4")    # and the field with it
        time.sleep(0.5)
        check("the recording outlives its field", until(lambda: "waiting=1" in spooled(), 5), spooled())
        pc.up()
        job()
        check("it lands in Said when the PC is back", until(lambda: said().count(SENTENCE) >= 3, 20),
              said()[:300])
        check("with a notification, on the road's own words", until(
            lambda: SENTENCE in drive.notifications(), 10))
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
        check("what waited goes", until(lambda: len(pc.heard) == n + 1, 20))
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
        drive.tap("Connected|Can't reach")       # Home asks again
        check("a send out of the spool is on its way", pc.arrived.wait(20))
        fa.told("--es", "wipe", "1")
        check("the wipe took the addresses", "link_routes.bin" not in fa.sealed_files(), fa.sealed_files())
        pc.hold.set()
        time.sleep(1.5)
        check("what comes back lands nowhere: not in Said", SENTENCE not in said(), said()[:300])
        check("not on the shade", SENTENCE not in drive.notifications())
        check("and the addresses stay gone", "link_routes.bin" not in fa.sealed_files(), fa.sealed_files())
        check("a recording that went out with the wipe is still here for the same person",
              len(fa.recordings().split()) == 1, fa.recordings())

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
    """The keys that send what is in the field, on the door."""
    acct = fa.fresh()
    try:
        real_join(acct)
        field()
        drive.shell("input", "text", "shalom")
        check("something in the field", until(lambda: "shalom" in in_field(), 10), in_field()[:200])
        press("punctuate")
        check("the punctuate key goes through the door", until(lambda: "shalom." in in_field(), 15),
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
        other.down()
        out = ask("dictate")
        check("with no other PC, its own sentence comes back", "speech model is off" in out, out)
        check("and the recording stays", "refused=BUSY" in out, out)
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_spool_rules():
    """The cap and the week, on the phone's own disk."""
    acct = fa.fresh()
    try:
        real_join(acct)
        pc = acct._door_pc
        pc.down()
        now = int(time.time() * 1000)
        drive.as_app("mkdir", "-p", "files/spool")
        old = f"{now - 8 * 24 * 3600 * 1000:013d}-aaaaaaaa.wav"
        kept = f"{now - 6 * 24 * 3600 * 1000:013d}-bbbbbbbb.wav"
        for name in (old, kept):
            drive.as_app("sh", "-c", f"'head -c 40000 /dev/zero > files/spool/{name}'")
        ask("drain")
        files = fa.recordings().split()
        check("past the week it goes", old not in files, str(files))
        check("a day short of it stays", kept in files, str(files))
        for i in range(6):
            name = f"{now - (5 - i) * 3600 * 1000:013d}-cccccc0{i}.wav"
            drive.as_app("sh", "-c", f"'head -c 10000000 /dev/zero > files/spool/{name}'")
        out = ask("keep")
        files = fa.recordings().split()
        check("past 50 MB the oldest goes first, and the keeper is told", "dropped=2" in out, out)
        check("the oldest two were the two that went", kept not in files
              and not [f for f in files if f.endswith("cccccc00.wav")], str(files))
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
        ask("drain")
        check("unlocked, it goes", until(lambda: len(pc.heard) == n + 1, 20))
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
        until(lambda: not _on_mobile() and "MOBILE" in drive.shell("dumpsys", "connectivity")
              and "1 received" in drive.shell("ping", "-c", "1", "-W", "2", ADDRESS, check=False), 60)


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


FLOWS = {name[5:]: fn for name, fn in list(globals().items()) if name.startswith("flow_")}


def main() -> None:
    apk = Path(os.environ.get("DESKIT_APK")
               or ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk")
    if not fa.built_for_the_fake(apk):
        sys.exit("this APK speaks to the real project, and no flow may: "
                 "gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791")
    drive.adb("install", "-r", "-g", apk, timeout=300)
    drive.adb("logcat", "-G", "8M", check=False)
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
