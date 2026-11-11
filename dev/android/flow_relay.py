"""The sealed relay on the emulator (PHONE_LINK_PLAN.md stage 3), flow by flow, and the
pictures of the keyboard's line.

    <venv python> dev\\android\\flow_relay.py [name ...]

Build first, for the fake account AND the fake provider:
gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791 -PdeskitCloud=http://10.0.2.2:18793

What is real: the whole keyboard (its socket, its seals, its ladder); and on the PC's side
sb.py's live channel (_live_loop, the lanes, send_link), relay.py, server.py's Routes with
the phone door's own /transcribe, phone.py's kept rows and anchors, vault.py and net.py,
under a scratch home (flow_door sets DESKIT_HOME and DESKIT_SUITE). What is fake: the
account (fake_pc.FakeAccount, which now speaks Realtime: Phoenix's join on the private
topic, broadcasts fanned out, the 256 KB cap) and what the PC does with the audio. net.py's
two seams are pointed at the fake on loopback (_connect for REST, _ws_connect for the
socket), and only for the fake's host: anything else is refused.

The phone is off its Wi-Fi, on mobile data, which on an emulator still reaches the host:
"the home door unreachable" is the PC's door down, as in flow_backup.
"""
import dataclasses
import http.client
import json
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flow_door as fd                            # noqa: E402  (sets DESKIT_HOME and DESKIT_SUITE)

import config as config_mod                       # noqa: E402
import net as net_mod                             # noqa: E402
import phone as phone_mod                         # noqa: E402
import privacy                                    # noqa: E402
import relay as relay_mod                         # noqa: E402
import sb                                         # noqa: E402
import secretstore                                # noqa: E402
import server as server_mod                       # noqa: E402
import vault                                      # noqa: E402

import drive                                      # noqa: E402
import fake_cloud                                 # noqa: E402
import fake_pc                                    # noqa: E402
import flow_backup as fb                          # noqa: E402

fa = fd.fa
check, until = fd.check, fd.until
PKG = drive.PKG

#: What the PC's model hears, through the account: Hebrew, as his is.
RELAYED = "שלום מהדרך, דרך החשבון"
VIA = r"\d+\.\d s · fake via your account"
REF = "fakeref"
#: What each flow measured, for the report.
TIMES: dict[str, list[float]] = {}


class _Raw:
    """What net._connect hands back: a status, headers, the body once."""

    def __init__(self, status, headers, body: bytes):
        self.status, self.headers, self._body = status, headers, body

    def read(self, n: int = -1) -> bytes:
        out, self._body = (self._body, b"") if n < 0 else (self._body[:n], self._body[n:])
        return out

    def __iter__(self):
        yield self.read()

    def close(self):
        pass


class RelayPc:
    """A PC of the fake account, the real one's way: sb.py's live channel holding the
    account's socket, relay.py on its link lane, the phone door's routes behind it.
    ``why``: what a ping is answered with (None, ready); ``on``: Also from outside home."""

    def __init__(self, acct: fake_pc.FakeAccount, text: str = RELAYED):
        self.acct, self.text = acct, text
        self.heard: list[bytes] = []
        self.why: str | None = None
        self.on = True
        self.thread: threading.Thread | None = None
        self.routes = server_mod.Routes(self._transcribe)
        self.relay = relay_mod.for_app(
            can_take=lambda: self.why, allowed=lambda: self.on,
            transcribe=lambda wav, peer: self.routes.handle("/transcribe", wav, peer))
        self._old = (net_mod._connect, net_mod._ws_connect)

    def _transcribe(self, wav: bytes):
        self.heard.append(wav)
        self.answered_at = time.perf_counter()
        return self.text, "fake", None

    # the wire, to the fake and nowhere else
    def _connect(self, method, url, headers, body, timeout_s):
        parts = urllib.parse.urlsplit(url)
        if parts.hostname != net_mod.SUPABASE_HOST:
            raise net_mod.NetError(f"the flow's PC reaches the fake only, not {parts.hostname}")
        conn = http.client.HTTPConnection("127.0.0.1", self.acct.port, timeout=timeout_s)
        try:
            conn.request(method, parts.path + (f"?{parts.query}" if parts.query else ""),
                         body=body, headers=headers)
            r = conn.getresponse()
            return _Raw(r.status, r.headers, r.read())
        except OSError as e:
            raise net_mod.NetError(str(e)) from e
        finally:
            conn.close()

    def _ws_connect(self, host, port, timeout_s):
        if host != net_mod.SUPABASE_HOST:
            raise OSError(f"the flow's PC reaches the fake only, not {host}")
        return socket.create_connection(("127.0.0.1", self.acct.port), timeout=timeout_s)

    def up(self, device: str | None = None) -> "RelayPc":
        """Signed in to the fake as the PC whose row the phone holds, the key kept, the
        phone's row read, the socket joined."""
        acct = self.acct
        sb.configure(REF, fake_pc.PUBLISHABLE_KEY)
        net_mod._connect, net_mod._ws_connect = self._connect, self._ws_connect
        session = acct._new_session()
        secretstore.set("supabase_session", json.dumps(session))
        sb.forget_cache()
        privacy.grant("account")
        device = device or acct.pc_id
        config_mod.save({"account.device_id": device, "account.device_ids": {acct.uid: device}})
        vault.keep(acct.uid, acct.key)
        assert sb.device_id() == device, sb.device_id()
        phone_mod.refresh()
        assert phone_mod.anchors(), "the phone's row did not open on the PC"
        sb.LINK_HOOKS[:] = [self.relay.heard]
        sb.LIVE_ENABLED = True
        sb._live_stop.clear()
        self.thread = threading.Thread(target=sb._live_loop, args=(None,), daemon=True, name="flow-live")
        self.thread.start()
        assert until(lambda: sb._live_state.get("on"), 15), f"the PC's socket did not join: {sb._live_state}"
        return self

    def down(self):
        sb._live_stop.set()
        if self.thread is not None:
            self.thread.join(5)
        sb.LINK_HOOKS[:] = []
        sb._live_stop.clear()
        net_mod._connect, net_mod._ws_connect = self._old


def logged(pattern: str) -> list[str]:
    """Every line of the keyboard's log so far that matches."""
    return re.findall(pattern, fa.log_so_far())


def released_ms(road: str) -> list[int]:
    """'dictation: a text N ms after the release (road)' lines."""
    return [int(x) for x in logged(rf"dictation: a text (\d+) ms after the release \({road}\)")]


def keyboard_sees_pc() -> bool:
    return "reachable=true" in fd.status()


# ------------------------------------------------------------------ the flows

def flow_lands():
    """Away from home, the PC on: the dictation is the PC's model's, through the account.
    The line says so with the recording's length, nothing waits, the cloud is not asked
    though a key is there, nothing readable crossed the account, and the PC's door saw
    the phone's own certificate."""
    acct = fa.fresh(backup="on")
    cloud = fb.cloud_up()
    pc = None
    try:
        acct.put_key("groq", fb.KEY)            # a key in the account: the relay must still come first
        fd.real_join(acct)
        fb.away(acct._door_pc)                   # the door at home down, the Wi-Fi off
        pc = RelayPc(acct).up()
        fd.field()
        check("away, the keyboard comes up finding its PC through the account",
              until(keyboard_sees_pc, 20), fd.status())
        drive.shot("r1_keyboard_away_ready")
        for i in range(3):
            fd.hold_and_say()
            check(f"dictation {i + 1}: the PC's text lands in the field",
                  until(lambda: fd.in_field().count(RELAYED) >= i + 1, 30), fd.in_field()[:200])
            check(f"dictation {i + 1}: the line says it came from the PC, through the account",
                  fd.says(VIA, 10), fd.status())
        drive.shot("r2_keyboard_landed_via_account")
        check("nothing waits on the phone", until(fd.spool_empty, 10), fd.spooled())
        check("the cloud was never asked", cloud.asked() == [], str(cloud.asked()))
        check("the PC heard three recordings, whole WAVs", len(pc.heard) == 3 and
              all(w[:4] == b"RIFF" for w in pc.heard), str(len(pc.heard)))
        spoke = fb.wav_seconds(len(pc.heard[-1])) if pc.heard else -1
        check("the line's number is how long he spoke, as on every road",
              fb.line_seconds() is not None and abs(fb.line_seconds() - spoke) <= 0.051,
              f"{fd.status()[:80]} / spoke {spoke:.2f} s")
        counts = pc.relay.counts
        check("the PC answered every ping and took every recording once",
              counts.get("took") == 3 and counts.get("answered") == 3 and counts.get("ping", 0) >= 1, str(counts))
        seen = phone_mod._read_rows().get("seen") or {}
        check("Settings > Phone's 'dictated here' moved for the phone's certificate",
              any(v.get("dictated") for v in seen.values()), str(seen)[:200])
        pieces = acct.events("link")
        clear = json.dumps(pieces, ensure_ascii=False)
        check("what crossed the account: sealed pieces only, no word of it, no WAV",
              pieces and RELAYED not in clear and "RIFF" not in clear and "UklGR" not in clear,
              f"{len(pieces)} pieces")
        check("every piece under the 256 KB cap", acct.realtime["largest"] < fake_pc.FakeAccount.PAYLOAD_MAX,
              str(acct.realtime))
        times = released_ms("relay")
        TIMES["relay"] = times
        check("the keyboard measured each one, release to text", len(times) == 3, str(times))
        print(f"      release to text through the account: {times} ms; the account counted "
              f"{acct.realtime}", flush=True)
        fb.is_clean(fb.KEY)
        log = fa.log_so_far()
        check("the keyboard's log names no device and no key", acct.pc_id not in log and acct.uid not in log)
    finally:
        if pc is not None:
            pc.down()
        fb.home_again()
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


def flow_pc_off():
    """Away from home, the PC off: nobody answers through the account, the cloud takes
    it about a second later, as stage 2b did."""
    acct = fa.fresh(backup="on")
    cloud = fb.cloud_up()
    try:
        acct.put_key("groq", fb.KEY)
        fd.real_join(acct)
        fb.away(acct._door_pc)
        fd.field()
        fd.hold_and_say()
        check("the cloud's text lands", until(lambda: fb.HEARD in fd.in_field(), 30), fd.in_field()[:200])
        check("the line says the cloud", fd.says(fb.FROM_CLOUD, 10), fd.status())
        check("the account's channel was asked and nobody was there",
              bool(logged(r"to the cloud \(groq\), the PC road \w+, the relay nobody")), fa.log_so_far()[-600:])
        TIMES["cloud, the PC off"] = released_ms("cloud")
        print(f"      release to text, the PC off: {TIMES['cloud, the PC off']} ms", flush=True)
    finally:
        fb.home_again()
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


def flow_no_key_pc_off():
    """Away, the PC off, no key: the recording waits, as it always has, and the words say
    the PC did not answer: the account was reached from this network, so the Wi-Fi is not
    why."""
    acct = fa.fresh(backup="on")
    try:
        fd.real_join(acct)
        fb.away(acct._door_pc)
        fd.field()
        fd.hold_and_say()
        check("nothing pasted, the recording waits with its words",
              until(lambda: fd.row_is(fd.NO_ANSWER), 30), fd.row()["raw"][:300])
        drive.shot("r3_keyboard_away_pc_off_waits")
        check("one recording waits", "waiting=1" in fd.spooled(), fd.spooled())
    finally:
        fb.home_again()
        acct._door_pc.down()
        acct.stop()


def flow_no_account_channel():
    """Off the Wi-Fi, and the account's channel cannot be reached either: then the Wi-Fi
    is what to fix, and the line keeps his words of 2026-11-10."""
    acct = fa.fresh(backup="off")
    try:
        fd.real_join(acct)
        acct.realtime_off = True
        fb.away(acct._door_pc)
        fd.field()
        fd.hold_and_say()
        check("nothing reached: the Wi-Fi's words, and the recording waits",
              until(lambda: fd.row_is(fd.NO_WIFI), 30), fd.row()["raw"][:300])
    finally:
        fb.home_again()
        acct._door_pc.down()
        acct.stop()


def flow_send_again():
    """A recording that waited (the PC off) goes through the account on Send again once
    the PC is back."""
    acct = fa.fresh(backup="off")
    pc = None
    try:
        fd.real_join(acct)
        fb.away(acct._door_pc)
        fd.field()
        fd.hold_and_say()
        check("the PC off: it waits", until(lambda: fd.row_is(fd.NO_ANSWER), 30), fd.row()["raw"][:300])
        pc = RelayPc(acct).up()
        fd.send_again()
        check("Send again: the PC's text, through the account",
              until(lambda: RELAYED in fd.in_field(), 30), fd.in_field()[:200])
        check("and nothing waits", until(fd.spool_empty, 10), fd.spooled())
    finally:
        if pc is not None:
            pc.down()
        fb.home_again()
        acct._door_pc.down()
        acct.stop()


def flow_model_off():
    """Away, the PC on with its model off: its own words, through the account, before the
    release is over, and the cloud is not asked although a key is there (2b's rule: a PC
    that was reached keeps the recording)."""
    acct = fa.fresh(backup="on")
    cloud = fb.cloud_up()
    pc = None
    try:
        acct.put_key("groq", fb.KEY)
        fd.real_join(acct)
        fb.away(acct._door_pc)
        pc = RelayPc(acct).up()
        import main as main_mod
        pc.why = main_mod.App.MODEL_OFF_WORDS        # the PC's own sentence, word for word
        fd.field()
        fd.hold_and_say()
        check("the PC's own words, and the recording waits",
              until(lambda: fd.row_is("The model is off on your PC"), 30), fd.row()["raw"][:300])
        check("the cloud was not asked", cloud.asked() == [], str(cloud.asked()))
        check("the PC transcribed nothing", pc.heard == [])
    finally:
        if pc is not None:
            pc.down()
        fb.home_again()
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


def flow_switch_off():
    """Away, the PC on with Also from outside home off: it answers nothing, and the cloud
    takes it."""
    acct = fa.fresh(backup="on")
    cloud = fb.cloud_up()
    pc = None
    try:
        acct.put_key("groq", fb.KEY)
        fd.real_join(acct)
        fb.away(acct._door_pc)
        pc = RelayPc(acct).up()
        pc.on = False
        fd.field()
        fd.hold_and_say()
        check("the cloud's text lands", until(lambda: fb.HEARD in fd.in_field(), 30), fd.in_field()[:200])
        check("the PC opened nothing", pc.heard == [] and pc.relay.counts.get("ping", 0) == 0, str(pc.relay.counts))
    finally:
        if pc is not None:
            pc.down()
        fb.home_again()
        acct._door_pc.down()
        acct.stop()
        cloud.stop()


def flow_forgotten():
    """A phone the account forgot: the PC opens nothing of it, though its seals are good,
    because the forgotten list is the door's own (phone.anchors)."""
    acct = fa.fresh(backup="off")
    pc = None
    try:
        fd.real_join(acct)
        fb.away(acct._door_pc)
        pc = RelayPc(acct).up()
        phone_row = acct.phones()[0]
        # Forget pressed on another device: the account's list, and this PC's own kept
        # copy of it, which only ever grows (phone._forgotten), as an account pass leaves it
        acct.write_forgotten([{"device": phone_row["id"], "cert": "", "at": fake_pc.now_iso()}])
        kept = phone_mod._read_rows()
        kept["forgotten"] = sorted(set(kept.get("forgotten") or []) | {phone_row["id"]})
        phone_mod._write_rows(kept)
        check("the PC's list leaves the phone out", phone_mod.anchors() == {}, str(phone_mod.anchors()))
        time.sleep(relay_mod.PHONES_TTL_S + 0.5)
        fd.field()
        fd.hold_and_say()
        time.sleep(4)
        check("the PC opened nothing of a forgotten phone", pc.heard == [] and pc.relay.counts.get("stranger"),
              str(pc.relay.counts))
    finally:
        if pc is not None:
            pc.down()
        fb.home_again()
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
    names = sys.argv[1:] or list(FLOWS)
    try:
        for name in names:
            print(f"--- {name}", flush=True)
            fa.log_forget()
            try:
                FLOWS[name]()
            except (AssertionError, subprocess.TimeoutExpired) as e:
                check(f"{name} ran to its end", False, str(e)[:500])
                drive.shot(f"failed_relay_{name}")
            except Exception as e:                           # noqa: BLE001
                check(f"{name} ran to its end", False, f"{type(e).__name__}: {str(e)[:400]}")
                drive.shot(f"failed_relay_{name}")
    finally:
        shutil.rmtree(fd.HOME, ignore_errors=True)
    for road, times in TIMES.items():
        if times:
            print(f"timing, {road}: {times} ms, median {statistics.median(times):.0f}", flush=True)
    print(f"{fa._passed} passed, {fa._failed} failed", flush=True)
    sys.exit(1 if fa._failed else 0)


if __name__ == "__main__":
    main()
