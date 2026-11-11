"""Settings > Phone with the phone's cloud backup (PHONE_LINK_PLAN.md stage 2b), photographed:
the real card (desk_settings.backup_card), over a faked running app.

    <venv python> dev\\shot_phone_backup.py OUT.png key|nokey|off|said [PHONE NAME]

Run it through tests_quiet.run_hidden: the window is born on a hidden desktop. It runs as a
stranger's copy under a scratch home of its own (DESKIT_HOME, DESKIT_STRANGER, DESKIT_SUITE),
so nothing of the owner's (his settings, his keys, his account, his running app's pipe) is
read or touched, and it makes no sound. Whether the account holds a key is the one thing
faked beside the app: the card asks this PC's store, and the scratch home's is empty.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
OUT, WHICH = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "key")
#: the phone's name, as its owner typed it (his: "ה-Yoav של S26 Ultra"), for `said`
NAME = sys.argv[3] if len(sys.argv) > 3 else "Dana's phone"
os.environ["DESKIT_HOME"] = tempfile.mkdtemp(prefix="deskit-shot-backup-")
os.environ["DESKIT_STRANGER"] = "1"
os.environ["DESKIT_SUITE"] = "1"
sys.path.insert(0, str(HERE))

import winsound  # noqa: E402

winsound.PlaySound = lambda *a, **k: None
winsound.Beep = lambda *a, **k: None

import control  # noqa: E402

NOW = time.time()
# the phone's row, as phone.view() reads a keyboard of stage 2b
PHONE = {"id": "p1", "name": "Dana's phone", "cert": "c", "dictated": NOW - 3600, "reached": NOW - 3600,
         "backup": WHICH != "off"}
STATUS = {
    "ok": True, "stage": "running", "activity": "idle", "model": "on", "locked": False,
    "backend": "local", "uptime_s": 3 * 3600 + 12 * 60,
    "account": {"configured": True, "signed_in": True, "anonymous": False,
                "email": "dana.levi@example.com", "device_name": "HOME-PC"},
    "phone": {"on": True, "allowed": True, "port": 8790, "addrs": ["192.168.1.20"],
              "program": "", "error": "", "phones": [PHONE], "pcs": [], "ask": False,
              "account_off": False, "offline": False},
}
control.send = lambda cmd, timeout_ms=0, **a: STATUS if cmd == "status" else {"ok": True}

import desk_settings  # noqa: E402

desk_settings._cloud_key = lambda: "" if WHICH == "nokey" else "groq"

if WHICH == "said":
    # A phone's dictation the cloud carried, as this PC pulls it: a row sealed the way the
    # phone seals one, opened by sb, written by sync into sync\history.log, read by the
    # Said page. Beside it, one of this PC's own, for what an unmarked row looks like.
    from datetime import datetime, timedelta, timezone

    import paths
    import sb
    import sync
    import vault

    key, uid = os.urandom(32), "11111111-2222-3333-4444-555555555555"
    phone = "cccccccc-0000-0000-0000-000000000004"
    when = datetime.now(timezone.utc) - timedelta(minutes=12)
    ts = when.isoformat(timespec="milliseconds")
    sealed = vault.seal_json(key, {"text": "אני בדרך הביתה, אגיע בעוד עשר דקות", "raw": None,
                                   "source": "phone-cloud"},
                             vault.AAD_HISTORY.format(uid=uid, device_id=phone, ts=ts, kind="dictation"))
    row = sb._open_history(key, uid, {"device_id": phone, "ts": ts, "kind": "dictation",
                                      "cipher": sealed, "engine": "groq", "seconds": 3.2})
    paths.SYNC_DIR.mkdir(parents=True, exist_ok=True)
    sync.append_remote_history([sync.remote_line(row, NAME)])
    own = (when - timedelta(minutes=40)).astimezone()
    paths.TRANSCRIPTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    paths.TRANSCRIPTS_LOG.write_text(
        own.strftime("%Y-%m-%d %H:%M:%S") + ",000 | OK | 2.4s | local | 0.6s latency | "
        "תזכיר לי לקנות חלב ולחם בדרך\n", "utf-8")

import deskweb  # noqa: E402

sys.exit(deskweb.main(["--shot", OUT, "--place", "Said" if WHICH == "said" else "Settings/phone"]))
