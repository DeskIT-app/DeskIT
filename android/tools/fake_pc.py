"""The real phone server with fake hooks, on 127.0.0.1:8790 — what the
emulator reaches as http://10.0.2.2:8790. Transcribes to a fixed Hebrew
sentence, holds one pending proposal from the phone, answers lookups.
Writes what it was told to fake_pc.log."""
import dataclasses
import os
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\shimr\Desktop\Organized\Projects\DeskIT")
import config as config_mod          # noqa: E402
import server as server_mod          # noqa: E402

HERE = Path(__file__).resolve().parent
logging.basicConfig(filename=Path(os.environ.get("DESKIT_EMU_OUT", HERE)) / "fake_pc.log", level=logging.INFO,
                    format="%(asctime)s %(message)s", encoding="utf-8")
log = logging.getLogger("fake")

cfg = config_mod.load(Path(r"C:\Users\shimr\Desktop\Organized\Projects\DeskIT\config.toml"))
cfg = dataclasses.replace(cfg, server=config_mod.ServerConfig(
    enabled=True, host="127.0.0.1", port=8790))

PENDING = [{
    "id": "20260913-150000-0031", "when": "2026-09-13 15:00:00", "seconds": 3.1,
    "text": "אוכלים מטוס בערב ואחרי זה הולכים לישון",
    "raw": "אוכלים מטוס בערב ואחרי זה הולכים לישון",
    "proposed": "אוכלים מנטוס בערב ואחרי זה הולכים לישון",
    "changes": [{"before": "מטוס", "after": "מנטוס", "kind": "replace",
                 "span": [1, 2], "why": "מנטוס, לא מטוס"}],
    "status": "pending", "source": "phone",
}, {
    "id": "20260913-150100-0044", "when": "2026-09-13 15:01:00", "seconds": 4.4,
    "text": "please send the report by five", "raw": "please send the report by five",
    "proposed": "please send the report by nine",
    "changes": [{"before": "five", "after": "nine", "kind": "replace",
                 "span": [5, 6], "why": "nine, not five"}],
    "status": "pending", "source": "desktop",
}]


def transcribe(wav):
    log.info("transcribe %d bytes", len(wav))
    return "שלום מהאמולטור, זה עובד", "fake", None


def translate(text):
    log.info("translate %r", text)
    return "Hello from the emulator, it works", "fake"


def punctuate(text):
    log.info("punctuate %r", text)
    return text + ".", "fake"


def review_pending():
    log.info("review pending asked (%d)", len(PENDING))
    return [dict(p) for p in PENDING]


def review_decide(sid, verdict):
    log.info("decide %s %s", sid, verdict)
    for p in list(PENDING):
        if p["id"] == sid:
            PENDING.remove(p)
            return dict(p, status=verdict, by="phone")
    return None


def lookup(text):
    log.info("lookup %r", text)
    if text.strip().lower() == "empty":
        raise ValueError("nothing to look up (both-scripts)")
    return "שביר — נשבר בקלות; (מטאפורית) רגיש, לא יציב", "Hebrew", "fake", 0.4


srv = server_mod.PhoneServer(cfg, transcribe, lambda: "fake", translate,
                             punctuate, None, review_pending=review_pending,
                             review_decide=review_decide, lookup=lookup)
srv.start()
log.info("fake PC up on 8790")
print("up", flush=True)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    srv.stop()
