"""The rest of the app, photographed from the emulator: Home, Settings, the second
reading, the lookup box and the keyboard, on made-up data.

    python app_shots.py OUT_DIR

The phone is really joined to the fake account and really talks to a small fake
PC on 8790, so these are the app's own screens and not a mock-up of them. Nothing
opens on the owner's screen.
"""
import http.server
import json
import socketserver
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drive                                     # noqa: E402
import fake_pc                                   # noqa: E402
import flow_account as flow                      # noqa: E402

PROPOSAL = {
    "id": "20261106-150000-0031", "when": "2026-11-06 15:00:00", "seconds": 3.1,
    "text": "אוכלים מטוס בערב ואחרי זה הולכים לישון",
    "proposed": "אוכלים מנטוס בערב ואחרי זה הולכים לישון",
    "changes": [{"before": "מטוס", "after": "מנטוס", "kind": "replace", "why": "מנטוס, לא מטוס"}],
    "status": "pending", "source": "phone",
}
SAID = [[1793984400000, "ניפגש מחר בבוקר ליד המשרד, אני מביא את המסמכים"],
        [1793980800000, "Please send the report by five."]]


class FakePc(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send({"ok": True, "version": "1.0.6"})
        elif self.path.startswith("/review"):
            self._send({"items": [PROPOSAL]})
        else:
            self._send({"pc": "1.0.6", "ime_min": 0, "ime_latest": 0})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._send({"text": "שביר: נשבר בקלות", "target": "Hebrew", "backend": "fake"})


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def write_prefs() -> None:
    """Point the old road at the fake PC and leave two lines in What you said."""
    said = json.dumps(SAID, ensure_ascii=True).replace("&", "&amp;").replace('"', "&quot;")
    xml = ("<?xml version='1.0' encoding='utf-8' standalone='yes' ?><map>"
           '<string name="url">http://10.0.2.2:8790</string>'
           '<string name="token">made-up</string>'
           f'<string name="said">{said}</string></map>')
    drive.kill()
    drive.as_app("mkdir", "-p", "shared_prefs")
    (Path(drive.OUT) / "dictation.xml").write_text(xml, "utf-8")
    drive.adb("push", Path(drive.OUT) / "dictation.xml", "/data/local/tmp/dictation.xml")
    drive.shell("chmod", "644", "/data/local/tmp/dictation.xml")
    drive.shell("run-as", drive.PKG, "cp", "/data/local/tmp/dictation.xml",
                "shared_prefs/dictation.xml")


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    drive.OUT = out
    pc = Server(("127.0.0.1", 8790), FakePc)
    threading.Thread(target=pc.serve_forever, daemon=True).start()
    acct = flow.fresh()
    try:
        flow.join(acct)
        acct.pc_asks("NEW-PC")
        write_prefs()
        # clearing the app took the keyboard off; a person's would be on
        ime = f"{drive.PKG}/.DictationIme"
        drive.shell("ime", "enable", ime, check=False)
        drive.shell("ime", "set", ime, check=False)
        drive.shell("pm", "grant", drive.PKG, "android.permission.RECORD_AUDIO", check=False)
        drive.shell("pm", "grant", drive.PKG, "android.permission.POST_NOTIFICATIONS", check=False)
        drive.home()
        drive.wait("Connected", 20)
        time.sleep(2)
        print(drive.shot("app_home"))
        drive.tap("אוכלים", 10)
        drive.wait("Keep", 15)
        time.sleep(0.8)
        print(drive.shot("app_review"))
        drive.shell("input", "keyevent", "4")
        time.sleep(0.8)
        flow.to_settings()
        drive.wait("NEW-PC asks to join", 20)
        drive.wait("HOME-PC", 10)
        time.sleep(1)
        print(drive.shot("app_settings"))
        drive.swipe_up()
        time.sleep(0.6)
        print(drive.shot("app_settings2"))
        drive.tap_scrolling("^Other ways$")
        time.sleep(1)
        drive.swipe_up()
        time.sleep(0.6)
        drive.tap("10.0.2.2", 10)                # the address field: up comes the keyboard
        time.sleep(2.5)
        print(drive.shot("app_keyboard"))
        drive.shell("input", "keyevent", "4")
        time.sleep(0.5)
        drive.shell("am", "start", "-W", "-n", f"{drive.PKG}/.LookupActivity",
                    "-a", "android.intent.action.PROCESS_TEXT", "-t", "text/plain",
                    "--es", "android.intent.extra.PROCESS_TEXT", "fragile")
        drive.wait("Copy", 15)
        time.sleep(1.2)
        print(drive.shot("app_lookup"))
    finally:
        acct.stop()
        pc.shutdown()


if __name__ == "__main__":
    main()
