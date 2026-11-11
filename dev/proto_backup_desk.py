"""PROTOTYPE, stage 2b of PHONE_LINK_PLAN.md: the desk's Settings > Phone with the phone's
cloud-backup switch read from the phone, for the owner's yes. Nothing of it is the
product's: the card is added to the page from here, over a faked running app.

    <venv python> dev\\proto_backup_desk.py OUT.png key|nokey

Run it through tests_quiet.run_hidden: the window is born on a hidden desktop. It runs
as a stranger's copy under a scratch home of its own (DESKIT_HOME, DESKIT_STRANGER,
DESKIT_SUITE), so nothing of the owner's (his settings, his keys, his account, his
running app's pipe) is read or touched, and it makes no sound.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
OUT, WHICH = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "key")
os.environ["DESKIT_HOME"] = tempfile.mkdtemp(prefix="deskit-proto-backup-")
os.environ["DESKIT_STRANGER"] = "1"
os.environ["DESKIT_SUITE"] = "1"
sys.path.insert(0, str(HERE))

import winsound  # noqa: E402

winsound.PlaySound = lambda *a, **k: None
winsound.Beep = lambda *a, **k: None

import control  # noqa: E402

NOW = time.time()
PHONE = {"id": "p1", "name": "Dana's phone", "dictated": NOW - 3600, "reached": NOW - 3600,
         # the proposal: the phone's switch, as the phone writes it into its sealed `link` row
         "backup": {"on": True}}
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
import settings as settings_mod  # noqa: E402

#: Does the account hold a cloud key? On the real desk: keyrow.stored, by name.
HAVE_KEY = WHICH != "nokey"


def _card_backup(self, sections):
    """PROPOSAL: one line per phone that has said where its switch stands."""
    phones = [d for d in desk_settings.phone_info(self.status).get("phones") or []
              if isinstance(d.get("backup"), dict)]
    if not phones:
        return None
    d = phones[0]
    name = str(d.get("name") or "your phone")
    if not d["backup"].get("on"):
        return {"kind": "line", "line": f"Cloud backup on {name}: off",
                "small": "Its recordings wait for this PC. You turn it on and off on the "
                         "phone, in Settings.", "buttons": []}
    if HAVE_KEY:
        return {"kind": "line", "ready": True, "line": f"Cloud backup on {name}: on",
                "small": "If it can't reach this PC, it sends the recording to Groq with "
                         "your key. You turn it on and off on the phone, in Settings.", "buttons": []}
    return {"kind": "line", "tone": "warn", "line": f"Cloud backup on {name}: on, but no key",
            "small": "Your account has no cloud key yet, so the phone waits for this PC.",
            "buttons": [{"label": "Add a key", "go": "privacy", "primary": True}]}


desk_settings.Place._card_backup = _card_backup
desk_settings.BLOCK_TITLES["backup"] = ("When the phone can't reach this PC", "globe")
desk_settings.LAYOUT[settings_mod.PHONE] = ("THE PHONE", "devices", "backup", "keyboard", "trouble")

import deskweb  # noqa: E402

sys.exit(deskweb.main(["--shot", OUT, "--place", "Settings/phone"]))
