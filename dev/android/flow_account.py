"""The account on the emulator, flow by flow, driven by what is on screen, against
the fake account of fake_pc.py and the REAL vault.py behind it.

    python dev\\android\\flow_account.py [name ...]

Build for it first: gradle assembleDebug -PdeskitAccount=http://10.0.2.2:8791
(a build for the real project speaks to the real project, and these flows must
never touch that: main() refuses one). emu.py boots the phone and installs it.

No flow needs a Google password: the browser really opens on the fake's page,
and the way back is the same intent a browser hands over. Each flow starts from
a cleared app, so each is a stranger's phone. The checks print as they go, exit
code 1 on any failure.

DESKIT_VAULT_FROM names a folder holding another vault.py, to hold these flows
against a lane's version before it is merged.
"""
import base64
import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drive                                     # noqa: E402
import fake_pc                                   # noqa: E402

vault = fake_pc.vault
PKG = drive.PKG
CODE = r"^[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5}$"
STEP_SIGN_IN = "^Sign in with Google$"
_passed = 0
_failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _passed, _failed
    if ok:
        _passed += 1
    else:
        _failed += 1
    print(("ok    " if ok else "FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""),
          flush=True)


def until(test, seconds: float = 20.0, every: float = 0.3) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if test():
            return True
        time.sleep(every)
    return bool(test())


def fresh() -> fake_pc.FakeAccount:
    """A stranger's phone and a new account beside it."""
    drive.clear_app()
    acct = fake_pc.FakeAccount()
    acct.start()
    return acct


def to_account_page() -> None:
    drive.home()
    # the account is the first step, whatever its words are
    drive.tap(r"^(Sign in with Google|Approve this phone|Open DeskIT on your PC"
              r"|Your account's lock changed|Your PC said Not now)$", 20)


def to_settings() -> None:
    drive.home()
    drive.tap("^Settings$", 10)
    drive.wait("^Settings$", 10)


def back() -> None:
    drive.shell("input", "keyevent", "4")


def sign_in(acct: fake_pc.FakeAccount, *, from_home: bool = True) -> None:
    """The real request, the real browser opening, the same way back."""
    seen = len(acct.authorized)
    if from_home:
        to_account_page()
    drive.wait("^Sign in$", 15)
    drive.tap(STEP_SIGN_IN, 10)
    assert until(lambda: len(acct.authorized) > seen, 20), "the browser never asked the account"
    code = acct.authorized[-1]["code"]
    drive.shell("am", "start", "-W", "-a", "android.intent.action.VIEW",
                "-d", f"deskit://auth?code={code}")


def same_code() -> None:
    """The phone's half of the join: one press on the code screen."""
    drive.tap("^Same code$", 15)
    drive.wait("Press Approve on your PC|This phone is ready", 10)


def join(acct: fake_pc.FakeAccount) -> dict:
    """Signed in, both sides pressed: the phone's row."""
    sign_in(acct)
    code = drive.wait(CODE, 30)["text"]
    req = acct.requests()[-1]
    same_code()
    acct.approve(req["id"])
    drive.wait("This phone is ready", 20)
    drive.tap("^Done$")
    assert until(lambda: bool(acct.phones()), 10)
    return dict(acct.phones()[0], code=code)


def sealed_files() -> str:
    return drive.as_app("ls", "no_backup/sealed", check=False)


# ------------------------------------------------------------------ the flows

def flow_sign_in():
    acct = fresh()
    try:
        drive.logcat_clear()
        to_account_page()
        drive.wait("^Sign in$", 10)
        check("a phone with nothing on it is asked to sign in", True)
        sign_in(acct, from_home=False)
        drive.wait(CODE, 30)
        check("the code comes back from the browser and is exchanged",
              ("POST", "/auth/v1/token") in acct.calls)
        check("the request is sb.sign_in_google's, with the chooser", len(acct.authorized) == 1)
        raw = drive.as_app("cat", "no_backup/sealed/session.bin", check=False)
        check("the session is sealed on disk", "access_token" not in raw and len(raw) > 40)
        before = len(acct.sessions)
        drive.shell("am", "start", "-W", "-a", "android.intent.action.VIEW",
                    "-d", "deskit://auth?code=made-up")
        time.sleep(1.5)
        check("a code from another app starts no session", len(acct.sessions) == before)
        log = drive.logcat()
        session = next(iter(acct.sessions.values()))
        for what, value in (("the email", acct.email), ("the access token", session["access"]),
                            ("the refresh token", session["refresh"])):
            check(f"{what} is not in the log", value not in log)
    finally:
        acct.stop()


def flow_join():
    acct = fresh()
    try:
        sign_in(acct)
        code = drive.wait(CODE, 30)["text"]
        reqs = acct.requests()
        check("one request is open", len(reqs) == 1, str(len(reqs)))
        req = reqs[0]
        check("the code on the phone is the code the PC computes with the real vault",
              code == acct.code_of(req), f"{code} against {acct.code_of(req)}")
        check("the row's code column is the code's hint", req["code"] == vault.code_hint(code))
        check("the name fits the column", 0 < len(req["device_name"]) <= 40, req["device_name"])
        pairing = acct.events("pairing")
        check("the PC is told at once", len(pairing) == 1 and pairing[0].get("id") == req["id"]
              and pairing[0].get("code") == code and pairing[0].get("device") == req["device_id"]
              and pairing[0].get("name") == req["device_name"], str(pairing))

        # He walks to the PC. Android kills the keyboard. He comes back.
        drive.kill()
        to_account_page()
        again = drive.wait(CODE, 20)["text"]
        check("killed and reopened, the same code is on screen", again == code, again)
        check("and no twin was made", [r["id"] for r in acct.requests()] == [req["id"]])
        time.sleep(4)
        check("polling makes no twin either", [r["id"] for r in acct.requests()] == [req["id"]])

        same_code()
        drive.wait("Press Approve on your PC", 15)
        drive.kill()
        acct.approve(req["id"])                  # approved while the phone was dead
        drive.home()
        check("pressed and killed, the answer opens on Home's own look", until(
            lambda: bool(acct.phones()), 25))
        check("the request's row is gone", until(
            lambda: not [r for r in acct.tables["pairings"] if r["id"] == req["id"]], 10))
        check("a phone row exists", len(acct.phones()) == 1)
        row = acct.phones()[0]
        link = acct.open_link(row)
        check("the real vault opens the phone's link row", link.get("kind") == "phone"
              and link.get("v") == 1 and link.get("proto") == 1 and link.get("backup") is True,
              str(link))
        der = base64.b64decode(link["cert"])
        check("the certificate is DER", der[:1] == b"\x30" and len(der) > 200, str(len(der)))
        check("the platform is android-<sdk>", re.fullmatch(r"android-\d+", row["platform"]) is not None)
        session = next(iter(acct.sessions.values()))
        check("the row names its session", row["session_id"] == session["id"])
        check("the device is the one that asked", row["id"] == req["device_id"])
        check("the others are told the row changed", until(
            lambda: any("devices" in (e.get("stores") or []) for e in acct.events("changed")), 10))
        raw = drive.as_app("cat", "no_backup/sealed/account_key.bin", check=False)
        check("the key is sealed on disk", '"key"' not in raw and len(raw) > 40)
    finally:
        acct.stop()


def flow_wrong_key():
    acct = fresh()
    try:
        sign_in(acct)
        code = drive.wait(CODE, 30)["text"]
        req = acct.requests()[0]
        import os
        same_code()
        acct.approve(req["id"], key=os.urandom(32))    # a key of another lock
        check("the first request is dropped", until(
            lambda: not [r for r in acct.tables["pairings"] if r["id"] == req["id"]], 20))
        check("a key of another lock is not kept",
              until(lambda: len(acct.requests()) == 1, 25) and not acct.phones())
        new = drive.wait(CODE, 25)["text"]
        check("and the phone asks again, with a new code", new != code, new)
    finally:
        acct.stop()


def flow_dishonest_server():
    """A server that names another lock to the asking device: two screens, two codes."""
    acct = fresh()
    try:
        import os
        own = os.urandom(32)
        lie = vault.fingerprint(own)
        acct.tables["profiles"][0]["lock_id"] = lie
        sign_in(acct)
        code = drive.wait(CODE, 30)["text"]
        req = acct.requests()[0]
        check("a lock the PC does not hold gives another code on the PC's Home",
              code != acct.code_of(req), code)
        check("the phone's code is the one for the lie", code == acct.code_of(req, lie))
        # `handed` is a column the server can write, and a key that matches the
        # lock it named passes every check a phone can make. The press is what
        # stands in the way: the two screens differ, so nobody presses.
        acct.approve(req["id"], key=own)
        time.sleep(7)                            # two polls of the page
        check("a forged hand-over is not kept without the press", "account_key.bin" not in sealed_files())
        check("the phone stays on the code", drive.find(CODE) is not None
              and drive.find("^Same code$") is not None)
        check("and writes no row", not acct.phones())
        drive.kill()
        to_account_page()
        drive.wait(CODE, 20)
        check("killed and reopened, nothing was taken either", "account_key.bin" not in sealed_files())
    finally:
        acct.stop()


def flow_declined():
    acct = fresh()
    try:
        sign_in(acct)
        drive.wait(CODE, 30)
        req = acct.requests()[0]
        acct.decline(req["id"])
        drive.wait("Your PC said Not now", 15)
        time.sleep(4)
        check("Not now is not answered by asking again by itself", not acct.requests())
        drive.tap("^Ask again$")
        drive.wait(CODE, 30)
        check("Ask again asks", len(acct.requests()) == 1)
    finally:
        acct.stop()


def flow_no_lock():
    acct = fresh()
    try:
        keep = acct.tables["profiles"][0]["lock_id"]
        acct.tables["profiles"][0]["lock_id"] = ""
        sign_in(acct)
        drive.wait("Open DeskIT on your PC", 20)
        check("a phone never makes a lock", acct.tables["profiles"][0]["lock_id"] == ""
              and not acct.requests())
        acct.tables["profiles"][0]["lock_id"] = keep
        code = drive.wait(CODE, 25)["text"]
        check("it carries on by itself when the PC makes one", code == acct.code_of(acct.requests()[0]))
    finally:
        acct.stop()


def flow_approve():
    acct = fresh()
    try:
        join(acct)
        ask = acct.pc_asks("NEW-PC")
        to_settings()
        drive.wait("NEW-PC asks to join", 20)
        shown = drive.wait(CODE, 20)["text"]
        check("the code on the phone is the one the asking PC shows",
              shown == ask["full_code"], f"{shown} against {ask['full_code']}")
        drive.tap("^Approve$")
        check("the key crosses, written on the request", until(
            lambda: bool(next(r for r in acct.tables["pairings"] if r["id"] == ask["id"])["handed"]), 20))
        check("the real vault opens the phone's hand-over", acct.pc_takes(ask["id"]) == acct.key)
        check("the asking PC is told", until(
            lambda: any(e.get("id") == ask["id"] for e in acct.events("paired")), 10))
        drive.gone("NEW-PC asks to join", 15)
        check("the row leaves the screen", True)

        # the checks approve_pairing makes
        ask = acct.pc_asks("OTHER-PC")
        back()
        to_settings()
        drive.wait("OTHER-PC asks to join", 20)
        drive.wait(CODE, 20)
        fake = vault.applicant("00000000-0000-0000-0000-000000000000")
        with acct.mutex:
            next(r for r in acct.tables["pairings"] if r["id"] == ask["id"])["applicant"] = fake
        drive.tap("^Approve$")
        time.sleep(4)
        row = next(r for r in acct.tables["pairings"] if r["id"] == ask["id"])
        check("a request whose key changed after it was shown is not approved", not row["handed"])

        acct.decline(ask["id"])
        twin_device = "99999999-9999-4999-8999-999999999999"
        acct.pc_asks("TWIN-PC", device=twin_device)
        acct.pc_asks("TWIN-PC", device=twin_device)
        back()
        to_settings()
        drive.wait("Two requests say they are TWIN-PC", 20)
        check("two requests from one device offer no Approve", drive.find("^Approve$") is None)
        check("and no code", drive.find(CODE) is None)
        for r in acct.requests():
            acct.decline(r["id"])

        ask = acct.pc_asks("LATER-PC")
        back()
        to_settings()
        drive.wait("LATER-PC asks to join", 20)
        drive.tap("^Not now$")
        check("Not now deletes the request", until(lambda: not acct.requests(), 15))
    finally:
        acct.stop()


def flow_forget():
    acct = fresh()
    try:
        join(acct)
        acct.write_pc_row(device="77777777-7777-4777-8777-777777777777", name="OFFICE-PC")
        # a row the server made up: sealed under nothing the account knows
        with acct.mutex:
            acct.tables["devices"].append({
                "id": "66666666-6666-4666-8666-666666666666", "user_id": acct.uid,
                "name": "SERVERS-OWN-PC", "platform": "windows-10.0", "app_version": "1",
                "tier": "", "created_at": fake_pc.now_iso(), "last_seen": fake_pc.now_iso(),
                "link": vault.seal_json(bytes(32), {"kind": "pc"}, "device/x/y"),
                "session_id": None})
        to_settings()
        drive.wait("OFFICE-PC", 20)
        check("a device the server added does not appear", drive.find("SERVERS-OWN-PC") is None)
        check("this phone is on the list, with no Forget of its own",
              drive.find("^This phone$") is not None)
        cert = acct.pc_link()["cert"]
        drive.tap("^Forget$")
        drive.wait(r"^Forget (HOME-PC|OFFICE-PC)\?$", 10)
        target = drive.find(r"^Forget (HOME-PC|OFFICE-PC)\?$")["text"]
        name = target[len("Forget "):-1]
        device = acct.pc_id if name == "HOME-PC" else "77777777-7777-4777-8777-777777777777"
        drive.tap("^Keep it$")
        drive.gone(r"^Forget (HOME-PC|OFFICE-PC)\?$", 10)
        check("Keep it keeps it", acct.row_of(device) is not None)
        drive.tap("^Forget$")
        drive.wait(r"\?$", 10)
        drive.tap("^Forget$")
        check("the row is gone", until(lambda: acct.row_of(device) is None, 15))
        got = acct.forgotten()
        check("the real vault opens the list, with its device and certificate",
              any(e.get("device") == device and e.get("cert") == cert and e.get("at") for e in got),
              str(got))
        check("the others are told", until(lambda: sum("devices" in (e.get("stores") or [])
                                                       for e in acct.events("changed")) >= 2, 10))
        drive.gone(f"^{name}$", 15)
        check("it leaves the list", True)
    finally:
        acct.stop()


def flow_forgotten():
    """Forgotten from a PC while this phone slept: it finds out, wipes, starts over."""
    acct = fresh()
    try:
        row = join(acct)
        link = acct.open_link(row)
        fp = hashlib.sha256(base64.b64decode(link["cert"])).hexdigest()
        files = sealed_files()
        check("the phone holds the key before", "account_key.bin" in files, files)
        acct.write_forgotten([{"device": row["id"], "cert": fp, "at": fake_pc.now_iso()}])
        with acct.mutex:
            acct.tables["devices"] = [r for r in acct.tables["devices"] if r["id"] != row["id"]]
        acct.end_every_session()
        drive.kill()
        to_account_page_or_sign_in()
        drive.wait("Signed out from another device", 20)
        check("a refused refresh signs it out and says so", True)
        files = sealed_files()
        check("the session ending alone wipes nothing", "account_key.bin" in files, files)
        sign_in(acct, from_home=False)
        drive.wait(CODE, 30)
        drive.wait("This phone was removed", 5)
        check("it says it was removed", True)
        files = sealed_files()
        check("it wiped the key", "account_key.bin" not in files, files)
        req = acct.requests()[0]
        check("it asks as a new device", req["device_id"] != row["id"])
        same_code()
        acct.approve(req["id"])
        drive.wait("This phone is ready", 20)
        check("a new Approve brings it back", True)
        assert until(lambda: bool(acct.phones()), 10)
        new = acct.open_link(acct.phones()[0])
        check("under a new certificate", new["cert"] != link["cert"])
    finally:
        acct.stop()


def to_account_page_or_sign_in():
    drive.home()
    drive.tap(r"^Sign in with Google$", 20)


def flow_sign_out():
    acct = fresh()
    try:
        row = join(acct)
        link = acct.open_link(row)
        fp = hashlib.sha256(base64.b64decode(link["cert"])).hexdigest()
        drive.as_app("mkdir", "-p", "files/spool")
        drive.as_app("touch", "files/spool/a.wav")
        drive.as_app("touch", "files/spool/b.wav")
        to_settings()
        drive.wait("^Sign out$", 20)
        drive.tap_scrolling("^Sign out$")
        drive.wait("2 recordings that haven't reached your PC will be deleted", 10)
        check("the recordings are named first", True)
        drive.tap("^Stay signed in$")
        drive.gone("2 recordings", 10)
        check("Stay signed in changes nothing", acct.row_of(row["id"]) is not None)
        drive.tap_scrolling("^Sign out$")
        drive.wait("2 recordings", 10)
        drive.tap_scrolling("^Sign out$")
        check("its row goes", until(lambda: acct.row_of(row["id"]) is None, 15))
        check("its session goes", until(lambda: not acct.sessions, 10))
        got = acct.forgotten()
        check("it is on the list, with its certificate", any(
            e.get("device") == row["id"] and e.get("cert") == fp for e in got), str(got))
        check("the others are told before the session ended", sum(
            "devices" in (e.get("stores") or []) for e in acct.events("changed")) >= 2)
        check("the key, the session and the rows are wiped", until(
            lambda: not [f for f in sealed_files().split() if f in
                         ("account_key.bin", "session.bin", "device_rows.bin")], 10), sealed_files())
        check("the recordings are gone", "a.wav" not in drive.as_app("ls", "files/spool", check=False))
        back()
        to_account_page()
        drive.wait("^Sign in$", 15)
        sign_in(acct, from_home=False)
        drive.wait(CODE, 30)
        check("the next sign-in is a new device", acct.requests()[0]["device_id"] != row["id"])
    finally:
        acct.stop()


def flow_lock_changed():
    acct = fresh()
    try:
        row = join(acct)
        old_key = acct.key
        acct.change_lock()
        calls = len(acct.calls)
        to_account_page()
        drive.wait("Your account's lock changed", 20)
        check("it asks, with the PC's two answers", drive.find("^It wasn't me$") is not None
              and drive.find("^It was me$") is not None)
        check("nothing sealed is read while it asks", not any(
            p.endswith(("/devices", "/vault")) for _, p in acct.calls[calls:]))
        check("its key is still here", "account_key.bin" in sealed_files())

        drive.tap("^It wasn't me$")
        drive.wait("Paused on this phone", 15)
        check("It wasn't me moves nothing", "account_key.bin" in sealed_files())
        check("and points to Sign out of every PC", drive.find("Sign out of every PC") is not None)
        drive.kill()
        to_account_page()
        drive.wait("Paused on this phone", 20)
        check("a restart does not ask again", drive.find("^It was me$") is None)

        # it was somebody else, and the PC put its lock back
        acct.change_lock(old_key)
        drive.kill()
        drive.home()
        time.sleep(3)
        to_settings()
        drive.wait("HOME-PC", 20)
        check("the lock back, the phone carries on with its key", True)

        # and now it changes for real
        acct.change_lock()
        drive.kill()
        to_account_page()
        drive.wait("Your account's lock changed", 20)
        drive.tap("^It was me$")
        code = drive.wait(CODE, 30)["text"]
        req = acct.requests()[0]
        same_code()
        check("It was me asks to join the new lock", code == acct.code_of(req))
        check("its key moved aside, not away", "account_key_aside.bin" in sealed_files())
        check("the device stays the device", req["device_id"] == row["id"])
        acct.approve(req["id"])
        drive.wait("This phone is ready", 20)
        check("the new key is taken", True)
        assert until(lambda: bool(acct.phones()), 10)
        check("its row opens under the new key", until(
            lambda: _opens(acct, acct.phones()[0]), 10))
    finally:
        acct.stop()


def _opens(acct, row) -> bool:
    try:
        acct.open_link(row)
        return True
    except vault.VaultError:
        return False


def flow_session():
    acct = fresh()
    try:
        row = join(acct)
        acct.expire_tokens()
        to_settings()
        drive.wait("HOME-PC", 20)
        check("an expired token is refreshed and nothing shows", True)
        back()
        first = acct.row_of(row["id"])["session_id"]
        acct.end_every_session()
        drive.kill()
        to_account_page_or_sign_in()
        drive.wait("Signed out from another device", 20)
        sign_in(acct, from_home=False)
        drive.wait("This phone is ready", 30)
        check("the same account back needs no second Approve", not acct.requests())
        check("under the same device", acct.phones()[0]["id"] == row["id"])
        check("its row names the new session", until(
            lambda: acct.row_of(row["id"])["session_id"] not in (None, first), 15))
    finally:
        acct.stop()


def flow_offline():
    """The account gone: what is held carries on, and nothing is thrown away."""
    acct = fresh()
    try:
        join(acct)
        acct.stop()
        to_settings()
        drive.wait("Can't reach your account", 30)
        check("no answer is a sentence, and the devices stay on screen",
              drive.find("HOME-PC") is not None)
        check("nothing was wiped", "account_key.bin" in sealed_files())
    finally:
        acct.stop()


def flow_browser_tap():
    """The way back through a real browser: a tap on a real link in Chrome, the
    thing every other flow stands in for with an intent."""
    acct = fresh()
    try:
        to_account_page()
        drive.wait("^Sign in$", 15)
        drive.tap(STEP_SIGN_IN, 10)
        check("the browser opens on the account's page", until(lambda: bool(acct.authorized), 25))
        time.sleep(1.5)
        n = drive.find("^No thanks$")            # Chrome's own first-run question
        if n is not None:
            drive.shell("input", "tap", n["x"], n["y"])
            time.sleep(1)
        drive.shot("browser_page")
        drive.shell("input", "tap", 300, 370)    # the page's one link
        time.sleep(2.5)
        drive.shot("browser_after_tap")
        n = drive.find("^(Continue|Open|Open in app|Always|Just once)$")
        if n is not None:                        # a browser that asks before leaving
            print("      the browser asked:", n["text"], flush=True)
            drive.shell("input", "tap", n["x"], n["y"])
        drive.wait(CODE, 30)
        check("a tap in the browser lands in the app and signs in", True)
    finally:
        acct.stop()


def probe() -> str:
    """What the phone can open at this moment, screen locked or not."""
    drive.logcat_clear()
    drive.shell("am", "broadcast", "-n", f"{PKG}/.ProbeReceiver")
    end = time.time() + 15
    while time.time() < end:
        for line in drive.logcat().splitlines():
            if "probe:" in line:
                return line.split("probe:", 1)[1].strip()
        time.sleep(0.4)
    raise AssertionError("the probe never answered")


def lock_screen() -> None:
    drive.shell("input", "keyevent", "26")


def unlock(pin: str) -> None:
    drive.shell("input", "keyevent", "224")      # wake
    time.sleep(0.6)
    drive.shell("input", "keyevent", "82")       # to the PIN pad
    time.sleep(0.8)
    drive.shell("input", "text", pin)
    drive.shell("input", "keyevent", "66")
    time.sleep(1.5)


def flow_locked_phone():
    """A stolen, locked phone cannot use the key: run, not assumed. And what a
    phone does when its owner takes the screen lock away afterwards."""
    pin = "1234"
    sdk = int(drive.shell("getprop", "ro.build.version.sdk").strip())
    # Android 9 is the first with unlocked-only keys: before it the phone must
    # simply work, and the plan says so ("where the phone has it").
    strict = sdk >= 28
    acct = fresh()
    try:
        drive.shell("locksettings", "set-pin", pin)
        time.sleep(1)
        join(acct)
        print("      unlocked:", probe(), flush=True)
        lock_screen()
        time.sleep(2)
        now = probe()
        print("      locked:  ", now, flush=True)
        if strict:
            check("locked, the sealed store does not open", "sealed=notnow" in now, now)
            check("locked, the client key does not sign", "signs=refused" in now, now)
        check("the phone knows it is locked, and nothing was wiped",
              "locked=true" in now and "account_key.bin" in sealed_files())
        unlock(pin)
        now = probe()
        print("      unlocked:", now, flush=True)
        check("unlocked again, it all opens", "sealed=opened" in now and "signs=signed" in now, now)
        to_settings()
        drive.wait("HOME-PC", 20)
        check("and the account carries on with nothing asked", True)

        # the owner takes the screen lock away
        back()
        drive.shell("locksettings", "clear", "--old", pin)
        time.sleep(1.5)
        now = probe()
        print("      PIN removed:", now, flush=True)
        check("with the PIN removed the phone does not call itself locked", "locked=false" in now, now)
        if not strict:
            check("with no unlocked-only key, taking the PIN away changes nothing",
                  "sealed=opened" in now, now)
            return
        check("what was sealed under the lock is gone with it, and says so as nothing",
              "sealed=none" in now, now)
        drive.kill()
        drive.home()
        # the road back: nothing to unlock, so it is a new sign-in and a new Approve
        to_account_page_or_sign_in()
        sign_in(acct, from_home=False)
        drive.wait(CODE, 30)
        req = acct.requests()[-1]
        same_code()
        acct.approve(req["id"])
        drive.wait("This phone is ready", 25)
        check("with the screen lock gone, the phone gets back in by signing in and an Approve", True)
        now = probe()
        print("      back in: ", now, flush=True)
        check("what it seals now opens", "sealed=opened" in now, now)
    finally:
        drive.shell("locksettings", "clear", "--old", pin, check=False)
        acct.stop()


def flow_pin_added_later():
    """A phone with no screen lock joins, then gets one. Keystore could not make
    an unlocked-only key, so this phone keeps working and is not protected."""
    pin = "1234"
    acct = fresh()
    try:
        join(acct)
        now = probe()
        print("      no PIN:", now, flush=True)
        check("a phone with no screen lock is not left out", "sealed=opened" in now
              and "signs=signed" in now, now)
        drive.shell("locksettings", "set-pin", pin)
        time.sleep(1)
        lock_screen()
        time.sleep(2)
        now = probe()
        print("      PIN added, locked:", now, flush=True)
        unlock(pin)
        now = probe()
        print("      PIN added, unlocked:", now, flush=True)
        check("adding a PIN later breaks nothing", "sealed=opened" in now and "signs=signed" in now, now)
        to_settings()
        drive.wait("HOME-PC", 20)
        check("and the account carries on", True)
    finally:
        drive.shell("locksettings", "clear", "--old", pin, check=False)
        acct.stop()


def flow_same_code():
    """One press on each side, in either order."""
    acct = fresh()
    try:
        sign_in(acct)
        drive.wait(CODE, 30)
        req = acct.requests()[0]
        check("the code screen has one button", drive.find("^Same code$") is not None)

        # the Approve first, the press after
        acct.approve(req["id"])
        time.sleep(7)
        check("an Approve alone is not enough", "account_key.bin" not in sealed_files())
        same_code()
        drive.wait("This phone is ready", 20)
        check("the press after the Approve takes the key", "account_key.bin" in sealed_files())
    finally:
        acct.stop()
    acct = fresh()
    try:
        sign_in(acct)
        drive.wait(CODE, 30)
        req = acct.requests()[0]

        # the press first, the Approve after, with a kill in between
        same_code()
        drive.wait("Press Approve on your PC", 15)
        drive.kill()
        to_account_page()
        drive.wait("Press Approve on your PC", 20)
        check("the press survives a killed process", drive.find("^Same code$") is None)
        acct.approve(req["id"])
        drive.wait("This phone is ready", 20)
        check("the Approve after the press takes the key", "account_key.bin" in sealed_files())
    finally:
        acct.stop()


FLOWS = {name[5:]: fn for name, fn in globals().items() if name.startswith("flow_")}


def built_for_the_fake(apk: Path) -> bool:
    """Is this APK's account server the fake's? Read out of the APK itself."""
    tools = sorted((drive.SDK / "build-tools").glob("*/aapt2.exe"))
    out = subprocess.run([str(tools[-1]), "dump", "resources", str(apk)], capture_output=True,
                         encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    lines = out.stdout.splitlines()
    for i, line in enumerate(lines):
        if "string/account_server" in line:
            return "10.0.2.2" in "".join(lines[i:i + 3])
    return False


def main() -> None:
    apk = Path(os.environ.get("DESKIT_APK")
               or Path(__file__).resolve().parents[2] / "android" / "app" / "build" / "outputs"
               / "apk" / "debug" / "app-debug.apk")
    if not built_for_the_fake(apk):
        sys.exit("this APK speaks to the real project, and no flow may: "
                 "gradle assembleDebug -PdeskitAccount=http://10.0.2.2:8791")
    drive.adb("install", "-r", "-g", apk, timeout=300)
    names = sys.argv[1:] or list(FLOWS)
    print("vault's code takes the lock:", fake_pc.takes_the_lock(), flush=True)
    for name in names:
        print(f"--- {name}", flush=True)
        try:
            FLOWS[name]()
        except AssertionError as e:
            check(f"{name} ran to its end", False, str(e)[:500])
            drive.shot(f"failed_{name}")
    print(f"{_passed} passed, {_failed} failed", flush=True)
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
