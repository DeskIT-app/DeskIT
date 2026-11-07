"""The account on the emulator, flow by flow, driven by what is on screen, against
the fake account of fake_pc.py and the REAL vault.py behind it.

    python dev\\android\\flow_account.py [name ...]

Build for it first: gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791
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


def browser_opens(acct: fake_pc.FakeAccount, seen: int) -> bool:
    """The page is asked for. A phone with two browsers and no default asks
    which one first: a person picks, and so does this."""
    end = time.time() + 30
    while time.time() < end:
        if len(acct.authorized) > seen:
            # Android 8's Chrome reloads its last tab as it comes to the front,
            # an earlier flow's page and an earlier sign-in's challenge, and then
            # opens ours. The newest asking is ours, so let them both arrive.
            time.sleep(2)
            return True
        choice = drive.find("^Chrome$")
        if choice is not None:
            drive.shell("input", "tap", choice["x"], choice["y"])
            time.sleep(0.6)
            once = drive.find("(?i)^always$")
            if once is not None:
                drive.shell("input", "tap", once["x"], once["y"])
        time.sleep(0.5)
    return False


def sign_in(acct: fake_pc.FakeAccount, *, from_home: bool = True) -> None:
    """The real request, the real browser opening, the same way back."""
    seen = len(acct.authorized)
    if from_home:
        to_account_page()
    drive.wait("^Sign in$", 15)
    drive.tap(STEP_SIGN_IN, 10)
    assert browser_opens(acct, seen), "the browser never asked the account"
    code = acct.authorized[-1]["code"]
    # no -W: this page finishes itself, and Android 8 would wait on it for ever
    drive.shell("am", "start", "-a", "android.intent.action.VIEW",
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


def sdk() -> int:
    return int(drive.shell("getprop", "ro.build.version.sdk").strip())


def on_screen() -> str:
    """The code being shown, or ""."""
    n = drive.find(CODE)
    return n["text"] if n else ""


# ---- what a person leaves on a phone, and watching it go ----

# One word each: adb's shell splits on spaces.
SAID = "what-she-said"
HEARD = "what-it-heard"
MEANT = "what-she-meant"
NOT_LINKED = "^Not connected yet$"
HINT = "^https://"                               # what an empty address field shows


_log_kept: list[str] = []


def log_so_far() -> str:
    """Everything the log has said since [log_forget], probes or no probes."""
    return "".join(_log_kept) + drive.logcat()


def log_forget() -> None:
    _log_kept.clear()
    drive.logcat_clear()


def told(*args, wait: float = 15) -> str:
    """One word to the debug probe, and the line it answers with."""
    _log_kept.append(drive.logcat())
    drive.logcat_clear()
    # The foreground queue: the background one is serial, and a network change or a new
    # PIN sends it system broadcasts that hold a probe for the whole of adb's patience.
    drive.shell("am", "broadcast", "--receiver-foreground", "-n", f"{PKG}/.ProbeReceiver", *args,
                timeout=150)
    end = time.time() + wait
    while time.time() < end:
        for line in drive.logcat().splitlines():
            if "probe:" in line:
                return line.split("probe:", 1)[1].strip()
        time.sleep(0.3)
    raise AssertionError(f"the probe never answered {args}")


def clip() -> str:
    """The label on the clipboard, read by a window with the focus."""
    drive.logcat_clear()
    drive.shell("am", "start", "-n", f"{PKG}/.ClipProbe")
    end = time.time() + 15
    while time.time() < end:
        for line in drive.logcat().splitlines():
            if "probe:" in line:
                return line.split("probe:", 1)[1].strip()
        time.sleep(0.3)
    raise AssertionError("the clipboard probe never answered")


def on_disk() -> str:
    return drive.as_app("cat", "shared_prefs/dictation.xml", check=False)


def recording(name: str = "a.wav") -> None:
    drive.as_app("mkdir", "-p", "files/spool")
    drive.as_app("touch", f"files/spool/{name}")


def recordings() -> str:
    return drive.as_app("ls", "files/spool", check=False)


def plant(acct: fake_pc.FakeAccount) -> None:
    told("--es", "say", SAID, "--es", "url", f"http://10.0.2.2:{acct.port}",
         "--es", "token", acct.door_token)


def propose(acct: fake_pc.FakeAccount) -> None:
    """One proposal of the second reading, waiting on the PC for this phone."""
    drive.shell("pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS", check=False)
    acct.proposals = [{
        "id": "20261106-120000-0001", "when": "2026-11-06 12:00:00", "text": HEARD,
        "proposed": MEANT, "source": "phone", "status": "pending",
        "changes": [{"before": HEARD, "after": MEANT, "kind": "replace", "why": "the sentence"}],
    }]


def leave_traces(acct: fake_pc.FakeAccount) -> None:
    """A person's ordinary day: a sentence in Said and copied from there, the PC's
    line pasted, and a proposal from the second reading on Home and on the shade."""
    propose(acct)
    plant(acct)
    told("--es", "link", "plant")                # where the PCs are, as a door leaves it
    drive.kill()                                 # Home asks the PC as it opens
    drive.home()
    drive.wait(MEANT, 20)
    drive.tap_scrolling(SAID)
    time.sleep(0.6)
    assert SAID in on_disk() and acct.door_token in on_disk(), "the traces did not land"
    assert until(lambda: MEANT in drive.notifications(), 15), "no proposal on the shade"
    assert "clip=DeskIT" in clip(), "the sentence was not copied"


def no_traces(acct: fake_pc.FakeAccount, road: str) -> None:
    kept = on_disk()
    check(f"{road}: Said is off the disk", SAID not in kept, kept[:300])
    check(f"{road}: so is the PC's address and token",
          acct.door_token not in kept and f":{acct.port}" not in kept, kept[:300])
    check(f"{road}: no sentence on the shade",
          until(lambda: MEANT not in drive.notifications(), 10))
    on = clip()
    check(f"{road}: none on the clipboard", "clip=DeskIT" not in on, on)
    held = sealed_files()
    check(f"{road}: nothing says where the PC is", "link_routes.bin" not in held
          and "device_rows.bin" not in held, held)


def nothing_on_home(road: str, state: str = NOT_LINKED) -> None:
    """Home, which a person sees first. The caller has brought it up. [state] is
    what Home says of the PC: a phone in an account whose PC has a door it cannot
    reach from here says so."""
    drive.wait(state, 20)
    check(f"{road}: Home shows nothing that was said",
          drive.find(SAID) is None and drive.find(MEANT) is None, drive.screen()[:300])


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
        drive.shell("am", "start", "-a", "android.intent.action.VIEW",
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


def flow_forget_older_copy():
    """Forget takes a device's row and the session the row names, and the server says
    whether one was ended. Where none was, that device goes on working, and whoever
    pressed Forget has to hear it, in the PC's own sentence. One case each."""
    words = "off your list but still signed in"

    def forget(name: str) -> None:
        """The Forget on that device's row, and then the one in its question."""
        def nearest(y: int) -> dict:
            return min((n for n in drive.nodes() if n["text"] == "Forget"), key=lambda n: abs(n["y"] - y))
        to_settings()
        target = nearest(drive.wait(f"^{name}$", 20)["y"])
        drive.shell("input", "tap", target["x"], target["y"])
        drive.wait(f"^Forget {name}\\?$", 10)
        target = nearest(drive.wait("^Keep it$", 10)["y"])
        drive.shell("input", "tap", target["x"], target["y"])

    def row(device: str, name: str, sid) -> None:
        # each its own certificate: Forget bans a certificate too
        acct.write_pc_row(device=device, name=name, link=dict(
            acct.pc_link(), cert=hashlib.sha256(name.encode()).hexdigest()))
        with acct.mutex:
            next(r for r in acct.tables["devices"] if r["id"] == device)["session_id"] = sid

    acct = fresh()
    try:
        join(acct)
        other = "11111111-1111-4111-8111-111111111111"
        acct.others.add(other)
        for name, device, sid in (("OLD-PC", "71111111-7777-4777-8777-777777777777", None),
                                  ("THEIRS-PC", "72222222-7777-4777-8777-777777777777", other)):
            row(device, name, sid)
            forget(name)
            check(f"{name}: its row goes", until(lambda: acct.row_of(device) is None, 15))
            drive.gone(f"^{name}$", 15)
            drive.wait(words, 15)
            check(f"{name}: and the phone says it is still signed in", True)
            check(f"{name}: on the account's list all the same",
                  any(e.get("device") == device for e in acct.forgotten()))
            back()
        to_settings()
        drive.wait("HOME-PC", 20)
        check("the sentence does not outlive the page", drive.find(words) is None, drive.screen()[:300])
        back()

        with acct.mutex:
            before = set(acct.sessions)
            acct._new_session()
            live = (set(acct.sessions) - before).pop()
        for name, device, sid in (("LIVE-PC", "73333333-7777-4777-8777-777777777777", live),
                                  ("OVER-PC", "74444444-7777-4777-8777-777777777777",
                                   "22222222-2222-4222-8222-222222222222")):
            row(device, name, sid)
            forget(name)
            check(f"{name}: its row goes", until(lambda: acct.row_of(device) is None, 15))
            drive.gone(f"^{name}$", 15)
            drive.wait("HOME-PC", 10)
            time.sleep(1)
            check(f"{name}: and nothing more is said", drive.find(words) is None, drive.screen()[:300])
            back()
        check("the session a row named is ended", live not in acct.sessions)
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
        leave_traces(acct)
        recording()
        drive.die()                              # first, so that no look of Home's is out
        check("what is on the shade outlives the process", MEANT in drive.notifications())
        acct.write_forgotten([{"device": row["id"], "cert": fp, "at": fake_pc.now_iso()}])
        with acct.mutex:
            acct.tables["devices"] = [r for r in acct.tables["devices"] if r["id"] != row["id"]]
        acct.end_every_session()
        drive.home()
        drive.wait(STEP_SIGN_IN, 20)
        nothing_on_home("forgotten, and the phone has only heard its session ended")
        no_traces(acct, "forgotten, and the phone has only heard its session ended")
        drive.tap(STEP_SIGN_IN, 10)
        drive.wait("Signed out from another device", 20)
        check("a refused refresh signs it out and says so", True)
        files = sealed_files()
        check("the session ending alone leaves the device as it was", "account_key.bin" in files, files)
        check("and the recordings", "a.wav" in recordings())
        sign_in(acct, from_home=False)
        drive.wait(CODE, 30)
        drive.wait("This phone was removed", 5)
        check("it says it was removed", True)
        files = sealed_files()
        check("it wiped the key", "account_key.bin" not in files, files)
        check("and the recordings", "a.wav" not in recordings())
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


def flow_forgotten_awake():
    """The list names this phone while its session still stands: the road the
    phone hears about itself, and everything goes at that look."""
    acct = fresh()
    try:
        row = join(acct)
        link = acct.open_link(row)
        fp = hashlib.sha256(base64.b64decode(link["cert"])).hexdigest()
        leave_traces(acct)
        recording()
        drive.die()
        acct.write_forgotten([{"device": row["id"], "cert": fp, "at": fake_pc.now_iso()}])
        drive.home()
        drive.wait("^Approve this phone$", 25)
        nothing_on_home("found itself on the list")
        no_traces(acct, "found itself on the list")
        check("the recordings go with the key", "a.wav" not in recordings())
        check("and the key is gone", "account_key.bin" not in sealed_files())
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
        leave_traces(acct)
        recording("a.wav")
        recording("b.wav")
        to_settings()
        drive.wait("^Sign out$", 20)
        drive.tap_scrolling("^Sign out$")
        drive.wait("2 recordings that haven't reached your PC will be deleted", 10)
        check("the recordings are named first", True)
        drive.tap("^Stay signed in$")
        drive.gone("2 recordings", 10)
        check("Stay signed in changes nothing", acct.row_of(row["id"]) is not None)
        check("and takes nothing that was said", SAID in on_disk())
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
        check("the recordings are gone", "a.wav" not in recordings())
        no_traces(acct, "signed out")
        drive.tap_scrolling("^Other ways$")
        drive.swipe_up()
        drive.wait(HINT, 10)
        check("the fields no longer hold the PC's line", drive.find(acct.door_token) is None)
        back()                                   # the same Home that sat under Settings
        nothing_on_home("signed out")
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
        leave_traces(acct)
        recording()
        drive.die()
        acct.end_every_session()
        to_account_page_or_sign_in()
        drive.wait("Signed out from another device", 20)
        no_traces(acct, "the session ended from elsewhere")
        check("the recordings wait for the same account", "a.wav" in recordings())
        sign_in(acct, from_home=False)
        drive.wait("This phone is ready", 30)
        check("the same account back needs no second Approve", not acct.requests())
        check("and finds its recordings", "a.wav" in recordings())
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
        check("the browser opens on the account's page", browser_opens(acct, 0))
        time.sleep(1.5)
        n = drive.find("^No thanks$")            # Chrome's own first-run question
        if n is not None:
            drive.shell("input", "tap", n["x"], n["y"])
            time.sleep(1)
        drive.shot("browser_page")
        link = drive.find("Continue as")         # where a browser lets it be read
        drive.shell("input", "tap", link["x"] if link else 300, link["y"] if link else 370)
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
        leave_traces(acct)
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
        drive.die()
        drive.home()
        nothing_on_home("the screen lock taken away")
        no_traces(acct, "the screen lock taken away")
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
        if int(drive.shell("getprop", "ro.build.version.sdk").strip()) < 28:
            return

        # the way out: leave and come back, and every key is made under the lock
        drive.tap_scrolling("^Sign out$")
        drive.wait("^Sign out of this phone\\?$", 10)
        drive.tap_scrolling("^Sign out$")
        check("signed out", until(lambda: not acct.sessions, 15))
        back()
        to_account_page()
        sign_in(acct, from_home=False)
        drive.wait(CODE, 30)
        same_code()
        acct.approve(acct.requests()[-1]["id"])
        drive.wait("This phone is ready", 25)
        lock_screen()
        time.sleep(2)
        now = probe()
        print("      back in, locked:", now, flush=True)
        check("after leaving and coming back, a locked phone opens nothing", "sealed=notnow" in now, now)
        check("and signs nothing", "signs=refused" in now, now)
        unlock(pin)
    finally:
        drive.shell("locksettings", "clear", "--old", pin, check=False)
        acct.stop()


def flow_another_account():
    """The wrong Google account, noticed on the code screen. Then a second person
    on a phone the first left by no press at all: nothing of the first reaches them."""
    acct = fresh()
    second = fake_pc.FakeAccount(email="someone@else.example", name="Noa Bar")
    try:
        leave_traces(acct)
        sign_in(acct)
        drive.wait(CODE, 30)
        check("the screen names the account it is on", drive.find(acct.email) is not None)
        first = acct.requests()[0]
        drive.tap("^Use another account$", 10)
        drive.wait("^Sign in$", 20)
        check("the request goes", until(lambda: not acct.requests(), 10))
        check("the session goes", until(lambda: not acct.sessions, 10))
        no_traces(acct, "another account")
        sign_in(acct, from_home=False)
        drive.wait(CODE, 30)
        check("the next sign-in asks afresh", acct.requests()[0]["id"] != first["id"])

        # all the way in, and out by a road nobody pressed here
        same_code()
        acct.approve(acct.requests()[-1]["id"])
        drive.wait("This phone is ready", 20)
        drive.tap("^Done$")
        assert until(lambda: bool(acct.phones()), 10)
        left = acct.phones()[0]["id"]
        leave_traces(acct)
        recording()
        drive.die()
        acct.end_every_session()
        to_account_page_or_sign_in()
        drive.wait("Signed out from another device", 20)
        check("the recordings wait for their own account", "a.wav" in recordings())
        # the old road is still open to whoever has the line, signed in or not
        plant(acct)
        check("a line pasted after that is on the phone", SAID in on_disk())

        acct.stop()
        second.start()
        sign_in(second, from_home=False)
        drive.wait(CODE, 30)
        no_traces(acct, "a second account")
        check("the first account's recordings do not reach the second's PC",
              "a.wav" not in recordings())
        req = second.requests()[-1]
        check("it is a new device", req["device_id"] != left)
        same_code()
        second.approve(req["id"])
        drive.wait("This phone is ready", 25)
        drive.tap("^Done$")
        # In: its PC has a door, at an address no emulator reaches.
        nothing_on_home("a second account", "^Can't reach the PC$")
    finally:
        acct.stop()
        second.stop()


def flow_clipboard_later():
    """Android 10 and up tell only a window what is on the clipboard. A wipe with
    none of ours in front cannot look, and the process may die before one comes."""
    acct = fresh()
    try:
        leave_traces(acct)
        drive.shell("input", "keyevent", "3")
        time.sleep(1)
        told("--es", "wipe", "1")
        drive.die()
        check("the wipe itself needed no window", SAID not in on_disk())
        drive.home()
        drive.wait(NOT_LINKED, 20)
        on = clip()
        check("the clipboard is seen to at the next focus", "clip=DeskIT" not in on, on)
    finally:
        acct.stop()


def flow_keyboard():
    """What only a running keyboard holds: a transcript waiting for a field, the
    last recording, and a dictation still on its way back from the PC."""
    ime = f"{PKG}/.DictationIme"
    acct = fresh()
    try:
        drive.shell("settings", "put", "secure", "show_ime_with_hard_keyboard", "1")
        join(acct)
        plant(acct)
        drive.kill()                             # Android gives up on a stopped keyboard
        drive.shell("ime", "enable", ime, check=False)
        drive.shell("ime", "set", ime, check=False)
        to_settings()
        drive.tap_scrolling("^Other ways$")
        drive.tap_scrolling(r"10\.0\.2\.2")       # the keyboard comes up for this field
        assert until(lambda: "pending" in told("--es", "ime", "read"), 15), "no keyboard came up"

        told("--es", "ime", "now")
        check("a dictation that comes back in time reaches Said",
              until(lambda: "landed-words" in on_disk(), 5), on_disk()[:300])
        back()                                   # the keyboard away, and the field in view
        check("and its field", drive.seek("landed-words") is not None, drive.screen()[:400])
        held = told("--es", "ime", "plant")
        check("the keyboard holds a transcript and a recording",
              "pending=true" in held and "wav=true" in held, held)

        for _ in range(3):
            drive.swipe_down()
        drive.tap_scrolling("^Sign out$")
        drive.wait("^Sign out of this phone\\?$", 10)
        drive.tap_scrolling("^Sign out$")
        check("signed out", until(lambda: not acct.sessions, 15))
        time.sleep(1)

        drive.tap_scrolling(HINT)                # the emptied field
        time.sleep(1.5)
        now = told("--es", "ime", "read")
        check("what it held is gone once it is seen again",
              "pending=false" in now and "wav=false" in now, now)
        now = told("--es", "ime", "late")
        check("a dictation that comes back after that lands nowhere",
              "said=0" in now and "late-words" not in on_disk(), now)
        back()                                   # the keyboard away
        check("nor in the field, which is empty",
              drive.seek(HINT) is not None and drive.find("late-words") is None, drive.screen()[:400])
    finally:
        drive.shell("ime", "reset", check=False)
        acct.stop()


LEFT = 'name="leaving" value="true"'


def lock_prefs() -> str:
    return drive.as_app("cat", "shared_prefs/lock.xml", check=False)


def wiped() -> bool:
    """What Sign out takes that the account's calls need first."""
    files = sealed_files().split()
    return not [f for f in ("account_key.bin", "session.bin", "device_rows.bin") if f in files]


def press_sign_out(acct: fake_pc.FakeAccount, table: str = "pairings"):
    """Both presses of Sign out, on a phone with something to lose; its first call
    to the account waits at the server's door."""
    leave_traces(acct)
    recording()
    to_settings()
    drive.wait("^Sign out$", 20)
    drive.tap_scrolling("^Sign out$")
    drive.wait("^Sign out of this phone\\?$", 10)
    held = acct.stop_at("DELETE", table)
    drive.tap_scrolling("^Sign out$")
    assert held.caught.wait(15), "Sign out never reached the account"
    return held


def flow_leave_replayed_locked():
    """Sign out was cut short, and the look that finishes it is caught by the phone
    locking under its refresh. It waits for the phone, it does not crash."""
    pin = "1234"
    strict = sdk() >= 28
    acct = fresh()
    try:
        acct.short_tokens = True                 # every look finds the hour is up
        drive.shell("locksettings", "set-pin", pin)
        time.sleep(1)
        row = join(acct)
        held = press_sign_out(acct)
        drive.die()
        held.go()
        held = acct.stop_at("POST", "token")
        drive.home()
        assert held.caught.wait(20), "no refresh came"
        pid = drive.pid()
        drive.logcat_clear()
        lock_screen()
        time.sleep(2)
        held.go()
        time.sleep(3)
        check("a Sign out replayed under a phone that locks kills nothing",
              drive.pid() == pid and "FATAL" not in drive.crashes(), drive.crashes()[:500])
        if strict:
            check("it waits, with the mark standing", LEFT in lock_prefs(), lock_prefs()[:300])
            check("and the key still on the phone", "account_key.bin" in sealed_files())
        unlock(pin)
        drive.home()
        check("unlocked, the next look finishes it", until(wiped, 25), sealed_files())
        check("and the account hears of it", until(
            lambda: acct.row_of(row["id"]) is None and not acct.sessions, 15))
        check("the mark is gone", until(lambda: LEFT not in lock_prefs(), 10))
    finally:
        drive.shell("locksettings", "clear", "--old", pin, check=False)
        acct.stop()


def flow_leave_disk_refuses():
    """Use another account on a phone that never got a device id, with the disk
    refusing every write. Leaving must not need one."""
    acct = fresh()
    try:
        with acct.mutex:
            acct.tables["profiles"][0]["lock_id"] = ""
        sign_in(acct)
        drive.wait("Open DeskIT on your PC", 20)
        drive.as_app("mkdir", "-p", "no_backup/sealed/device_id.bin.tmp/x")
        pid = drive.pid()
        drive.logcat_clear()
        drive.tap("^Use another account$", 10)
        drive.wait("^Sign in$", 20)
        check("leaving needs no write", drive.pid() == pid and "FATAL" not in drive.crashes(),
              drive.crashes()[:500])
        check("its session ended", until(lambda: not acct.sessions, 10))
        check("the phone is out", "session.bin" not in sealed_files(), sealed_files())
        check("and nothing is owed", LEFT not in lock_prefs(), lock_prefs()[:300])
    finally:
        drive.as_app("rm", "-rf", "no_backup/sealed/device_id.bin.tmp", check=False)
        acct.stop()


def flow_leave_behind_a_poll():
    """The two doors that wait: Use another account with a poll out, and Sign out
    with a look holding the Lock. On bad Wi-Fi that wait is 40 s a call, with Signing
    out on screen, and the app can be swiped away in it."""
    acct = fresh()
    try:
        leave_traces(acct)
        recording()
        sign_in(acct)
        drive.wait(CODE, 30)
        held = acct.stop_at("GET", "profiles")
        assert held.caught.wait(10), "no poll came"
        drive.tap("^Use another account$", 8)
        drive.wait("Signing out", 8)
        check("behind a poll: the press writes itself down", LEFT in lock_prefs(), lock_prefs()[:300])
        kept = on_disk()
        check("behind a poll: the words go at the press", SAID not in kept, kept[:300])
        check("behind a poll: and the recordings", "a.wav" not in recordings())
        drive.die()
        held.go()
        drive.home()
        check("behind a poll: killed there, the next look finishes it", until(wiped, 25), sealed_files())
        check("behind a poll: and the account hears", until(lambda: not acct.sessions, 15))
    finally:
        acct.stop()
    acct = fresh()
    try:
        row = join(acct)
        leave_traces(acct)
        recording()
        to_settings()
        drive.wait("^Sign out$", 20)
        held = acct.stop_at("GET", "profiles")
        drive.shell("input", "keyevent", "3")
        time.sleep(1)
        drive.shell("am", "start", "-n", f"{PKG}/.HomeActivity")   # Settings, back in front: a look
        assert held.caught.wait(15), "no look came"
        drive.wait("^Sign out$", 10)
        drive.tap_scrolling("^Sign out$")
        drive.wait("^Sign out of this phone\\?$", 10)
        drive.tap_scrolling("^Sign out$")
        drive.wait("Signing out", 8)
        check("behind a look: the press writes itself down", LEFT in lock_prefs(), lock_prefs()[:300])
        kept = on_disk()
        check("behind a look: the words go at the press", SAID not in kept, kept[:300])
        check("behind a look: and the recordings", "a.wav" not in recordings())
        drive.die()
        held.go()
        drive.home()
        check("behind a look: the next look finishes it", until(wiped, 25), sealed_files())
        check("behind a look: and the account hears", until(
            lambda: acct.row_of(row["id"]) is None and not acct.sessions, 15))
    finally:
        acct.stop()


def flow_refresh_not_refused():
    """A refresh answered by anything but the auth server's own refusal of the token
    says nothing about the session, and nothing of the person's may go on it."""
    cloudflare = (403, "<html><title>Just a moment...</title></html>", "text/html")
    rotated = (401, '{"message":"Invalid API key","hint":"Double check your key."}',
               "application/json")
    from_the_future = (400, '{"code":400,"error_code":"validation_failed",'
                            '"msg":"Invalid Refresh Token: Not Issued By This Server"}', "application/json")
    acct = fresh()
    try:
        join(acct)
        leave_traces(acct)
        for road, answer in (("a gateway's page", cloudflare), ("a rotated publishable key", rotated),
                             ("a refusal that ends nothing", from_the_future)):
            drive.die()
            acct.expire_tokens()
            page = acct.stop_at("POST", "token", hold=False, answer=answer)
            drive.home()
            assert page.caught.wait(20), f"{road}: no refresh came"
            time.sleep(2)
            kept = on_disk()
            check(f"{road}: what was said stays", SAID in kept and acct.door_token in kept, kept[:300])
            check(f"{road}: so does the session", "session.bin" in sealed_files(), sealed_files())
        drive.die()
        to_settings()
        drive.wait("HOME-PC", 25)
        check("with the server back, nothing happened", SAID in on_disk() and bool(acct.sessions))
        back()

        # the same for the table's door: a good refresh, then a gateway's page again
        drive.die()
        acct.expire_tokens()
        first = acct.stop_at("GET", "profiles", hold=False, answer=(401, "<html>", "text/html"))
        second = acct.stop_at("GET", "profiles", hold=False, answer=(401, "<html>", "text/html"))
        drive.home()
        assert first.caught.wait(20) and second.caught.wait(20), "no second 401"
        time.sleep(2)
        check("two pages at the table's door end nothing", SAID in on_disk(), on_disk()[:300])
        check("and the session stays", "session.bin" in sealed_files(), sealed_files())

        # and the server's own refusals still end it, in either shape
        for road, answer in (("session_expired", (400, '{"code":400,"error_code":"session_expired",'
                                                       '"msg":"Invalid Refresh Token: Session Expired"}',
                                                  "application/json")),
                             ("an older server's words", (400, '{"error":"invalid_grant","error_description":'
                                                               '"Invalid Refresh Token: Refresh Token Not Found"}',
                                                          "application/json"))):
            drive.die()
            acct.expire_tokens()
            page = acct.stop_at("POST", "token", hold=False, answer=answer)
            drive.home()
            assert page.caught.wait(20), f"{road}: no refresh came"
            check(f"{road}: ends the session and takes the words", until(
                lambda: SAID not in on_disk() and "session.bin" not in sealed_files(), 15), on_disk()[:300])
            drive.die()
            to_account_page_or_sign_in()
            sign_in(acct, from_home=False)
            drive.wait("This phone is ready", 30)
            drive.tap("^Done$")
            plant(acct)
    finally:
        acct.stop()


def flow_posted_under_lock():
    """The phone locks under the POST: the row is there and what says so cannot be
    sealed. The PC still hears, and its Not now is still read as one."""
    pin = "1234"
    acct = fresh()
    try:
        drive.shell("locksettings", "set-pin", pin)
        time.sleep(1)
        held = acct.stop_at("POST", "pairings")
        sign_in(acct)
        assert held.caught.wait(30), "no POST came"
        lock_screen()
        time.sleep(2)
        held.go()
        check("the PC is told all the same", until(lambda: bool(acct.events("pairing")), 10))
        unlock(pin)
        code = drive.wait(CODE, 25)["text"]
        reqs = acct.requests()
        check("and the same request is on screen", len(reqs) == 1 and code == acct.code_of(reqs[0]))
        time.sleep(4)                            # a poll sees the row and writes it down
        acct.decline(reqs[0]["id"])
        drive.wait("Your PC said Not now", 15)
        time.sleep(4)
        check("a later Not now is read as one", not acct.requests())
    finally:
        drive.shell("locksettings", "clear", "--old", pin, check=False)
        acct.stop()


def flow_lock_removed_running():
    """He takes the screen lock away and goes back to the app, whose process never
    died. The session in its memory says nothing about what can still open."""
    if sdk() < 28:
        print("      no key to lose before Android 9", flush=True)
        return
    pin = "1234"
    acct = fresh()
    try:
        drive.shell("locksettings", "set-pin", pin)
        time.sleep(1)
        join(acct)
        leave_traces(acct)
        pid = drive.pid()
        drive.shell("input", "keyevent", "3")
        time.sleep(1)
        drive.shell("locksettings", "clear", "--old", pin)
        time.sleep(1.5)
        drive.home()
        check("the process is the same one", drive.pid() == pid)
        drive.wait(STEP_SIGN_IN, 20)
        nothing_on_home("the screen lock taken away, the app running")
        no_traces(acct, "the screen lock taken away, the app running")
        check("and it does not ask to join with a session it has lost", not acct.requests())
    finally:
        drive.shell("locksettings", "clear", "--old", pin, check=False)
        acct.stop()


def flow_another_account_killed():
    """A second person signs in and the process dies as their session is stored: a
    pipe where the sealed file goes holds it at that very moment. Whose phone this
    was must not be forgotten there, with the first one's recordings still on it."""
    pipe = "no_backup/sealed/session.bin.tmp"
    acct = fresh()
    second = fake_pc.FakeAccount(email="someone@else.example", name="Noa Bar")
    try:
        join(acct)
        leave_traces(acct)
        recording()
        drive.die()
        acct.end_every_session()
        to_account_page_or_sign_in()
        drive.wait("Signed out from another device", 20)
        check("the recordings wait for their own account", "a.wav" in recordings())
        acct.stop()
        second.start()
        drive.tap(STEP_SIGN_IN, 10)
        assert browser_opens(second, 0), "the browser never asked the account"
        drive.as_app("toybox", "mkfifo", pipe)   # Android 8 has no bare mkfifo
        drive.shell("am", "start", "-a", "android.intent.action.VIEW",
                    "-d", f"deskit://auth?code={second.authorized[-1]['code']}")
        check("the exchange is done", until(lambda: bool(second.sessions), 20))
        time.sleep(1.5)
        drive.die()
        drive.as_app("rm", "-f", pipe)
        drive.home()                             # the sign-in page, as it was left
        seen = len(second.authorized)
        drive.tap(STEP_SIGN_IN, 20)
        assert browser_opens(second, seen), "the browser never asked the account"
        drive.shell("am", "start", "-a", "android.intent.action.VIEW",
                    "-d", f"deskit://auth?code={second.authorized[-1]['code']}")
        drive.wait(CODE, 30)
        check("the first account's recordings do not reach the second's PC",
              "a.wav" not in recordings(), recordings())
        no_traces(acct, "a second account, killed as it arrived")
    finally:
        drive.as_app("rm", "-f", pipe, check=False)
        acct.stop()
        second.stop()


def flow_locked_no_refresh():
    """A locked phone spends no token it could not keep. And the old road, which
    needs no session, goes on dictating through the lock screen."""
    pin = "1234"
    acct = fresh()
    try:
        drive.shell("locksettings", "set-pin", pin)
        time.sleep(1)
        join(acct)
        plant(acct)
        lock_screen()
        time.sleep(2)
        now = told("--es", "dictate", "1")
        check("locked, a dictation on the old road goes through", "dictated=true" in now, now)
        acct.expire_tokens()
        seen = len(acct.calls)
        now = told("--es", "rest", "1")
        if sdk() >= 28:
            check("locked, a call that needs a refresh is told to wait", "rest=notnow" in now, now)
            check("and no token was spent", ("POST", "/auth/v1/token") not in acct.calls[seen:])
        unlock(pin)
        to_settings()
        drive.wait("HOME-PC", 25)
        check("unlocked, it refreshes and carries on", ("POST", "/auth/v1/token") in acct.calls[seen:])
        check("having never presented a spent token", acct.behind == 0, str(acct.behind))
    finally:
        drive.shell("locksettings", "clear", "--old", pin, check=False)
        acct.stop()


def flow_words_go_midway():
    """Two things a wipe can catch on their way to the screen: a proposal's page
    already open, and a poll still out to the PC."""
    acct = fresh()
    try:
        leave_traces(acct)
        drive.tap(MEANT)
        drive.wait("^Keep$", 15)
        drive.shell("input", "keyevent", "3")
        time.sleep(1)
        told("--es", "wipe", "1")
        # The page comes back in front. No -W: it finishes itself, and Android 8
        # would wait on it for ever.
        drive.shell("am", "start", "-n", f"{PKG}/.HomeActivity")
        check("a proposal's page closes when it is seen again",
              until(lambda: drive.find("^Keep$") is None, 10), drive.screen()[:300])
        nothing_on_home("a page open as the words went")
    finally:
        acct.stop()
    acct = fresh()
    try:
        join(acct)
        propose(acct)
        plant(acct)
        drive.die()
        acct.end_every_session()
        # A joined phone asks its PCs' doors before the pasted line, and that takes
        # seconds when no door answers. Home's own look at the account would find the
        # session over in that time and take the words before any poll went: held,
        # it lets the poll out first.
        look = acct.stop_at("GET", "profiles")
        held = acct.stop_at("GET", "review")
        drive.home()
        assert held.caught.wait(20), "no poll came"
        look.go()
        check("the words go with the poll still out", until(lambda: SAID not in on_disk(), 15),
              on_disk()[:300])
        held.go()
        time.sleep(3)
        check("what it brings back rings nothing", MEANT not in drive.notifications())
        nothing_on_home("a poll out as the words went")
    finally:
        acct.stop()


def flow_same_code_gone():
    """A press belongs to the code it was made on. The server holds a poll open, he
    presses, and it lets the poll go naming a lock of its own: what comes out of
    that is a new request with a new code, which he has compared with nothing."""
    acct = fresh()
    try:
        own = os.urandom(32)
        sign_in(acct)
        honest = drive.wait(CODE, 30)["text"]
        first = acct.requests()[0]
        check("the code on screen is the honest one", honest == acct.code_of(first))
        held = acct.stop_at("GET", "profiles")
        assert held.caught.wait(10), "no poll came"
        drive.tap("^Same code$", 8)
        drive.wait("Press Approve on your PC", 8)
        check("the press waits behind the poll, and the screen answers it at once", True)
        lie = vault.fingerprint(own)
        with acct.mutex:
            acct.tables["profiles"][0]["lock_id"] = lie
        held.go()
        check("a press on a code that has gone ends with the new code on screen",
              until(lambda: on_screen() not in ("", honest), 20), drive.screen()[:300])
        new = on_screen()
        req = acct.requests()[-1]
        check("the old request went", first["id"] not in [r["id"] for r in acct.requests()])
        check("the new one is for the server's lock", new == acct.code_of(req, lie))
        check("and waits for a press of its own", until(
            lambda: drive.find("^Same code$") is not None, 10), drive.screen()[:300])
        acct.approve(req["id"], key=own)
        time.sleep(7)                            # two polls of the page
        check("what the server wrote under its own key is not kept",
              "account_key.bin" not in sealed_files(), sealed_files())
        check("and no row is written", not acct.phones())
    finally:
        acct.stop()


def flow_refused_way_out():
    """It wasn't me, and the PC did as the screen said: the lock stays what it
    is, and the screen must not be a room with no door."""
    acct = fresh()
    try:
        row = join(acct)
        acct.change_lock()
        to_account_page()
        drive.wait("Your account's lock changed", 20)
        drive.tap("^It wasn't me$")
        drive.wait("Paused on this phone", 15)
        acct.end_every_session()                 # Sign out of every PC
        drive.kill()
        to_account_page_or_sign_in()
        drive.wait("Signed out from another device", 20)
        sign_in(acct, from_home=False)
        drive.wait("Paused on this phone", 25)
        check("signed in again, the refusal stands", True)
        check("the screen says whose account this is", drive.find(acct.email) is not None)
        drive.tap("^Use another account$", 10)
        drive.wait("^Sign in$", 20)
        check("and there is a way off it", True)
        check("which leaves as any Sign out does", until(
            lambda: "account_key.bin" not in sealed_files(), 10), sealed_files())
        check("its session ended", until(lambda: not acct.sessions, 10))
        sign_in(acct, from_home=False)
        code = drive.wait(CODE, 30)["text"]
        req = acct.requests()[-1]
        check("the next sign-in asks to join the lock as it stands", code == acct.code_of(req))
        check("as a new device", req["device_id"] != row["id"])
    finally:
        acct.stop()


def settled(acct: fake_pc.FakeAccount, road: str) -> None:
    """No PC said anything, so the phone must not say one did."""
    drive.wait(CODE, 30)
    time.sleep(7)                                # two polls: a false Not now lands here
    check(f"{road}: no Your PC said Not now", drive.find("Your PC said Not now") is None,
          drive.screen()[:300])
    reqs = acct.requests()
    check(f"{road}: one request, and its code on screen",
          len(reqs) == 1 and on_screen() == acct.code_of(reqs[0]), f"{len(reqs)} {on_screen()}")


def flow_lost_post():
    """The request's row never landed, or the reply never came, or the process
    died under it. The private half is sealed before the row exists, so each of
    these leaves a request with no row, and that used to read as a PC's Not now."""
    acct = fresh()
    try:
        cut = acct.stop_at("POST", "pairings", hold=False, cut=True, land=False)
        sign_in(acct)
        check("the first POST goes nowhere", cut.caught.wait(30))
        settled(acct, "a row that never landed")
    finally:
        acct.stop()
    acct = fresh()
    try:
        cut = acct.stop_at("POST", "pairings", hold=False, cut=True, land=True)
        sign_in(acct)
        check("the first POST lands and its reply is lost", cut.caught.wait(30))
        settled(acct, "a reply that never came")
    finally:
        acct.stop()
    acct = fresh()
    try:
        held = acct.stop_at("POST", "pairings", cut=True, land=False)
        sign_in(acct)
        assert held.caught.wait(30), "no POST came"
        drive.die()
        held.go()
        drive.home()                             # the page comes back as it was left
        settled(acct, "a process killed under the POST")
    finally:
        acct.stop()
    acct = fresh()
    try:
        held = acct.stop_at("POST", "pairings", cut=True, land=False)
        sign_in(acct)
        assert held.caught.wait(30), "no POST came"
        drive.die()
        held.go()
        acct.stop()                              # and the network went with it
        drive.home()
        drive.wait("Can't reach your account", 20)
        check("killed under the POST and reopened offline: no code that no PC has",
              on_screen() == "", drive.screen()[:300])
        acct.start()
        settled(acct, "the same, back online")
    finally:
        acct.stop()


def flow_key_shaped_name():
    """A phone's name is whatever its owner typed, and the server refuses one that
    looks like a key. It must stop neither the request nor the device's row."""
    name = "Ring Bearer S24"
    was = drive.shell("settings", "get", "global", "device_name").strip()
    acct = fresh()
    try:
        check("the server refuses this name", fake_pc.looks_like_key(name))
        drive.shell("settings", "put", "global", "device_name", f"'{name}'")
        check("the phone goes by it", name in drive.shell("settings", "get", "global", "device_name"))
        row = join(acct)
        check("it joins, and its row is there under the plain name", row["name"] == "Android phone",
              row["name"])
        to_settings()
        drive.wait("HOME-PC", 20)
        check("and nothing is said about it", drive.find("HTTP") is None, drive.screen()[:300])
    finally:
        if was and was != "null":
            drive.shell("settings", "put", "global", "device_name", f"'{was}'")
        else:
            drive.shell("settings", "delete", "global", "device_name")
        acct.stop()


def flow_locked_poll():
    """The phone locks while a poll is out and the poll fails. What it reaches for
    next is sealed, and an exception there is on a plain thread, in a catch: the
    whole process, keyboard included."""
    pin = "1234"
    acct = fresh()
    try:
        drive.shell("locksettings", "set-pin", pin)
        time.sleep(1)
        sign_in(acct)
        code = drive.wait(CODE, 30)["text"]
        pid = drive.pid()
        drive.logcat_clear()
        held = acct.stop_at("GET", "profiles", cut=True, land=False)
        assert held.caught.wait(10), "no poll came"
        lock_screen()
        time.sleep(2)
        held.go()
        time.sleep(3)
        check("a poll failing on a locked phone kills nothing",
              drive.pid() == pid and "FATAL" not in drive.crashes(), drive.crashes()[:500])
        unlock(pin)
        check("unlocked, the same code is on screen", until(lambda: on_screen() == code, 20),
              drive.screen()[:300])
    finally:
        drive.shell("locksettings", "clear", "--old", pin, check=False)
        acct.stop()


def flow_disk_refuses():
    """A sealed file that will not read or will not write: a full phone, in
    everything but the size. It is an answer, not a crash, and a token the server
    has spent must not depend on the disk being able to take the next one."""
    sealed = "no_backup/sealed"
    acct = fresh()
    try:
        join(acct)
        drive.die()
        drive.as_app("mv", f"{sealed}/session.bin", f"{sealed}/session.keep")
        drive.as_app("mkdir", f"{sealed}/session.bin")
        drive.logcat_clear()
        drive.home()
        time.sleep(3)
        check("a file that will not read kills nothing",
              drive.pid() != "" and "FATAL" not in drive.crashes(), drive.crashes()[:500])
        drive.die()
        drive.as_app("rmdir", f"{sealed}/session.bin")
        drive.as_app("mv", f"{sealed}/session.keep", f"{sealed}/session.bin")
        to_settings()
        drive.wait("HOME-PC", 20)
        check("and nothing was lost", "account_key.bin" in sealed_files())

        drive.as_app("mkdir", "-p", f"{sealed}/session.bin.tmp/x")
        back()
        # two refreshes, the sealed copy falling two behind: past the ten seconds
        # that ends a session on the real server, and it is what `unsealed` is for
        acct.expire_tokens()
        drive.logcat_clear()
        to_settings()
        drive.wait("HOME-PC", 20)
        back()
        acct.expire_tokens()
        to_settings()
        drive.wait("HOME-PC", 20)
        check("two refreshes with the disk refusing go on from memory",
              "FATAL" not in drive.crashes(), drive.crashes()[:500])
        time.sleep(11)
        drive.as_app("rm", "-rf", f"{sealed}/session.bin.tmp")
        back()
        to_settings()
        drive.wait("HOME-PC", 20)
        behind = acct.behind
        drive.die()
        acct.expire_tokens()
        to_settings()
        drive.wait("HOME-PC", 25)
        check("and the newest token reaches the disk once it can", acct.behind == behind,
              f"{behind} then {acct.behind}")
    finally:
        acct.stop()


def flow_sign_out_killed():
    """Sign out takes as long as the network does and the process can die in any
    of it. What needs no call goes before the first one. The rest is written down
    as owed, and the next look finishes it, with the account or without it."""
    acct = fresh()
    try:
        row = join(acct)
        held = press_sign_out(acct)
        drive.wait("Signing out", 8)
        check("the press is answered on screen while the account is asked", True)
        check("the button is gone", drive.find("^Sign out$") is None, drive.screen()[:300])
        kept = on_disk()
        check("the words go before the first call comes back", SAID not in kept, kept[:300])
        check("and the recordings", "a.wav" not in recordings())
        check("what the calls need is still here", "session.bin" in sealed_files())
        drive.die()
        held.go()
        check("killed under the calls, the phone is not out yet", not wiped(), sealed_files())
        drive.home()
        check("the next look finishes the leave", until(wiped, 20), sealed_files())
        check("the account hears of it", until(
            lambda: acct.row_of(row["id"]) is None and not acct.sessions, 15))
        check("the phone is on the list", any(e.get("device") == row["id"] for e in acct.forgotten()))
        drive.wait(STEP_SIGN_IN, 20)
        check("and Home says sign in", True)
        check("nothing is owed any more", until(lambda: LEFT not in lock_prefs(), 10))
        no_traces(acct, "a Sign out finished by the next look")
    finally:
        acct.stop()
    acct = fresh()
    try:
        join(acct)
        held = press_sign_out(acct)
        drive.die()
        acct.stop()                              # and the Wi-Fi went with it
        to_account_page()
        check("with no account to tell, it finishes all the same", until(wiped, 20), sealed_files())
        drive.wait("forget this phone", 20)
        check("and says what is left to do", True)
    finally:
        acct.stop()


def flow_locked_refresh():
    """A refresh spends the old token on the server. If the phone locks under it,
    the new one cannot be sealed, and it must not be dropped."""
    pin = "1234"
    acct = fresh()
    try:
        drive.shell("locksettings", "set-pin", pin)
        time.sleep(1)
        join(acct)
        acct.expire_tokens()
        held = acct.stop_at("POST", "token")
        to_settings()
        assert held.caught.wait(20), "no refresh came"
        lock_screen()
        time.sleep(2)
        held.go()
        time.sleep(3)
        unlock(pin)
        drive.wait("HOME-PC", 25)
        check("the phone locking under a refresh loses nothing", bool(acct.sessions))
        check("it goes on with the new token", acct.behind == 0, str(acct.behind))
        drive.die()
        acct.expire_tokens()
        to_settings()
        drive.wait("HOME-PC", 25)
        check("which was sealed once it could be", acct.behind == 0, str(acct.behind))
    finally:
        drive.shell("locksettings", "clear", "--old", pin, check=False)
        acct.stop()


def flow_auth_door():
    """The way back from the browser is exported, so anything on the phone can
    knock on it with anything, and any web page can open its address."""
    words = "Call-555-0100-now"
    acct = fresh()
    try:
        to_account_page()
        drive.wait("^Sign in$", 15)
        pid = drive.pid()
        drive.logcat_clear()
        drive.shell("am", "start", "-n", f"{PKG}/.AuthActivity", "-d", "mailto:a@example.com",
                    check=False)
        time.sleep(2.5)
        check("an address that is not hierarchical kills nothing",
              drive.pid() == pid and "FATAL" not in drive.crashes(), drive.crashes()[:500])
        for road, uri in (("another scheme", f"https://example.com/?error_description={words}"),
                          ("another host", f"deskit://evil?error_description={words}")):
            drive.shell("am", "start", "-n", f"{PKG}/.AuthActivity", "-d", f"'{uri}'", check=False)
            time.sleep(2)
            check(f"{road} is not read", drive.find(words) is None and drive.pid() == pid,
                  drive.screen()[:300])
        for road, uri in (("a web link's words", f"deskit://auth?error_description={words}"),
                          ("a web link's fragment", f"deskit://auth#error_description={words}")):
            drive.shell("am", "start", "-a", "android.intent.action.VIEW", "-d", f"'{uri}'")
            drive.wait("Google did not sign you in", 15)
            time.sleep(1.5)
            check(f"{road} never reach the screen", drive.find(words) is None, drive.screen()[:300])
    finally:
        acct.stop()


def flow_device_transfer():
    """Android 12 up ignores allowBackup="false" when one phone hands itself to the
    next. Its own LocalTransport, told it is such a transfer, shows what travels."""
    if sdk() < 31:
        print("      no such transfer before Android 12: allowBackup is the whole answer", flush=True)
        return
    stored = f"/data/data/com.android.localtransport/files/1/_full/{PKG}"
    transports = drive.shell("bmgr", "list", "transports", check=False)
    current = next((t.split()[1] for t in transports.splitlines() if t.strip().startswith("*")), "")
    acct = fresh()
    try:
        drive.adb("root", check=False)
        time.sleep(3)
        drive.adb("wait-for-device")
        drive.shell("bmgr", "enable", "true")
        drive.shell("bmgr", "transport", "com.android.localtransport/.LocalTransport")
        drive.shell("settings", "put", "secure", "backup_local_transport_parameters",
                    "'is_device_transfer=true,is_encrypted=true'")
        plant(acct)
        drive.shell("rm", "-f", stored, check=False)
        said = drive.shell("bmgr", "backupnow", PKG, timeout=120, check=False)
        check("the transfer ran", "Backup finished" in said, said)
        time.sleep(1)
        raw = subprocess.run([str(drive.ADB), "exec-out", "cat", stored], capture_output=True,
                             timeout=60, creationflags=subprocess.CREATE_NO_WINDOW).stdout
        check("what was said does not travel", SAID.encode() not in raw)
        check("nor the PC's token", acct.door_token.encode() not in raw)
        check("nor any file of this app", b"apps/" not in raw, raw[:200].decode("latin-1"))
    finally:
        drive.shell("settings", "delete", "secure", "backup_local_transport_parameters", check=False)
        if current:
            drive.shell("bmgr", "transport", current, check=False)
        drive.shell("bmgr", "enable", "false", check=False)
        drive.adb("unroot", check=False)
        time.sleep(3)
        drive.adb("wait-for-device")
        acct.stop()


def flow_list_never_shrinks():
    """The list is the server's to serve, and a device this phone was told to
    forget stays out whatever the list says next."""
    office = "77777777-7777-4777-8777-777777777777"
    acct = fresh()
    try:
        join(acct)
        acct.write_pc_row(device=office, name="OFFICE-PC")
        to_settings()
        drive.wait("OFFICE-PC", 20)
        back()
        acct.write_forgotten([{"device": office, "cert": "", "at": fake_pc.now_iso()}])
        to_settings()
        drive.wait("HOME-PC", 20)
        check("a device on the list is off the page", drive.find("OFFICE-PC") is None)
        back()
        for road, doing in (("an entry dropped from the row", lambda: acct.write_forgotten([])),
                            ("a row that no longer opens", lambda: _garble(acct))):
            doing()
            seen = len(acct.calls)
            to_settings()
            drive.wait("HOME-PC", 20)
            check(f"{road}: the phone read it", ("GET", "/rest/v1/vault") in acct.calls[seen:])
            check(f"{road}: the device stays out", drive.find("OFFICE-PC") is None, drive.screen()[:300])
            back()
    finally:
        acct.stop()


def _garble(acct: fake_pc.FakeAccount) -> None:
    cipher = vault.seal_json(bytes(32), {"v": []}, "vault/x/forgotten")
    with acct.mutex:
        next(r for r in acct.tables["vault"] if r["name"] == "forgotten")["cipher"] = cipher


def flow_client_key_locked():
    """A locked phone fails an unlocked-only key exactly as a phone that has none
    does, and the key made instead is the key for good. So none is made."""
    pin = "1234"
    acct = fresh()
    try:
        drive.shell("locksettings", "set-pin", pin)
        time.sleep(1)
        sign_in(acct)
        drive.wait(CODE, 30)
        req = acct.requests()[0]
        same_code()
        held = acct.stop_at("DELETE", "pairings")
        acct.approve(req["id"])
        assert held.caught.wait(15), "the answer was never taken"
        pid = drive.pid()
        drive.logcat_clear()
        lock_screen()
        time.sleep(2)
        held.go()
        time.sleep(3)
        check("the phone locking as its client key is due kills nothing",
              drive.pid() == pid and "FATAL" not in drive.crashes(), drive.crashes()[:500])
        check("and writes no row without a key", not acct.phones())
        unlock(pin)
        check("unlocked, the join finishes", until(lambda: bool(acct.phones()), 25))
        lock_screen()
        time.sleep(2)
        now = probe()
        print("      locked:  ", now, flush=True)
        if sdk() >= 28:
            check("the key that was made is the unlocked-only one", "signs=refused" in now, now)
        unlock(pin)
    finally:
        drive.shell("locksettings", "clear", "--old", pin, check=False)
        acct.stop()


def flow_answer_offline():
    """He answers the lock's question with no network. The answer has not been
    taken, and the screen must say so and not simply ask again."""
    acct = fresh()
    try:
        join(acct)
        acct.change_lock()
        to_account_page()
        drive.wait("Your account's lock changed", 20)
        acct.stop()
        drive.tap("^It was me$")
        drive.wait("Can't reach your account", 15)
        check("an answer that could not be taken says so", True)
        time.sleep(4)
        check("and goes on saying so", drive.find("Can't reach your account") is not None
              and drive.find("^Try again$") is not None, drive.screen()[:300])
        check("nothing moved", "account_key.bin" in sealed_files())
        acct.start()
        drive.tap("^Try again$")
        drive.wait("Your account's lock changed", 15)
        drive.tap("^It was me$")
        drive.wait(CODE, 30)
        check("with the account back, the answer counts", "account_key_aside.bin" in sealed_files())
    finally:
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
                 "gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791")
    drive.adb("install", "-r", "-g", apk, timeout=300)
    names = sys.argv[1:] or list(FLOWS)
    print("vault's code takes the lock:", fake_pc.takes_the_lock(), flush=True)
    for name in names:
        print(f"--- {name}", flush=True)
        try:
            FLOWS[name]()
        except (AssertionError, subprocess.TimeoutExpired) as e:
            check(f"{name} ran to its end", False, str(e)[:500])
            drive.shot(f"failed_{name}")
    print(f"{_passed} passed, {_failed} failed", flush=True)
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
