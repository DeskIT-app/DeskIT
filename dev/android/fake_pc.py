"""What the keyboard talks to, faked for the emulator, on loopback: what it
reaches as http://10.0.2.2:<port>. No real server, no real account, nothing of
the owner's: every key here is made fresh and dies with the process.

    python fake_pc.py             the PC's phone server, real server.py with
                                  fake hooks, on 8790
    python fake_pc.py --account   the account alone, on 18791

``FakeAccount`` is the account: enough of Supabase for everything a phone does
(the sign-in with its PKCE, refresh, REST on the four tables, forget_device,
the broadcast), checking what the real migrations check, so a wrong column or
a bad shape fails here as it would there. And it is a PC of that account: it
holds the account key and answers with the REAL vault.py, so a join on the
emulator is a join against the real formats. flow_account.py drives it.
Build the app for it with `gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791`.

Writes what it was told to fake_pc.log, never a key.
"""
import base64
import hashlib
import http.server
import inspect
import json
import logging
import os
import re
import socketserver
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("DESKIT_SUITE", "1")      # the test slots, never a real one
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if os.environ.get("DESKIT_VAULT_FROM"):          # another lane's vault.py, before it is merged
    sys.path.insert(0, os.environ["DESKIT_VAULT_FROM"])
import redact                                    # noqa: E402
import vault                                     # noqa: E402

HERE = Path(__file__).resolve().parent
logging.basicConfig(filename=Path(os.environ.get("DESKIT_EMU_OUT", HERE)) / "fake_pc.log", level=logging.INFO,
                    format="%(asctime)s %(message)s", encoding="utf-8")
log = logging.getLogger("fake")

PUBLISHABLE_KEY = "sb_publishable_p3pBXir64azVPAS1wtQoVg_mgi5ZOCt"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
#: 0004's check on `pairings.code`.
CODE_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{8}$")
AAD_DEVICE = getattr(vault, "AAD_DEVICE", "device/{uid}/{device_id}")

#: Every column of the four tables a phone touches, so that a name the real
#: server does not have is refused here too (PostgREST's PGRST204).
COLUMNS = {
    "profiles": {"user_id", "lock_id", "app_version_last_seen", "is_anonymous", "created_at"},
    "devices": {"id", "user_id", "name", "platform", "app_version", "tier", "created_at",
                "last_seen", "link", "session_id"},
    "pairings": {"id", "user_id", "device_id", "device_name", "code", "applicant", "handed",
                 "created_at", "expires_at", "approved_at"},
    "vault": {"user_id", "name", "cipher", "updated_at"},
    # stage 2b: the text of a dictation the cloud carried, as a PC's own rows are
    "history": {"user_id", "device_id", "ts", "kind", "cipher", "engine", "seconds", "updated_at"},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def takes_the_lock() -> bool:
    """Has this vault.py the code of §12, with the lock in it?"""
    return "lock_id" in inspect.signature(vault.pairing_code).parameters


def pairing_code(uid: str, pairing_id: str, public: str, lock_id: str) -> str:
    """The code as PHONE_LINK_PLAN §12 gives it: vault.pairing_code once the
    phone-account lane has landed, its text by hand until then."""
    if takes_the_lock():
        return vault.pairing_code(uid, pairing_id, public, lock_id)
    label = b"deskit pairing code v2"
    point = vault._unb64("p1", public)
    material = b"\0".join((label, uid.encode(), pairing_id.encode(), point, lock_id.encode()))
    digest = hashlib.pbkdf2_hmac("sha256", material, label, vault.CODE_ROUNDS, dklen=32)
    bits = int.from_bytes(digest[:8], "big") >> (64 - 50)
    flat = "".join(vault.ALPHABET[(bits >> (5 * (9 - i))) & 31] for i in range(10))
    return flat[:5] + "-" + flat[5:]


def looks_like_key(text: str) -> bool:
    """0001's looks_like_key(): its patterns are redact.PATTERNS verbatim, and a
    product test holds them to each other."""
    return any(pattern.search(text) for _, pattern in redact.PATTERNS)


class Stop:
    """One request caught at the server's door. [caught] when it arrives; with
    [hold] it waits there for go(), as a server holding a poll open does.
    [cut]: the socket goes instead of a reply, and [land] says whether the
    request was carried out first, a reply lost, or not at all. [answer] is
    (status, text, type): somebody else answers, a gateway in front of the
    server, and the server hears nothing of it."""

    def __init__(self, method: str, table: str, hold: bool, cut: bool, land: bool, answer=None):
        self.method, self.table = method, table
        self.hold, self.cut, self.land = hold, cut, land
        self.answer = answer
        self.caught = threading.Event()
        self.released = threading.Event()

    def go(self):
        self.released.set()


class Refuse(Exception):
    """What the database would say: a status and a body."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class _Door(http.server.BaseHTTPRequestHandler):
    # As a real server does: connections stay open, and an idle one is dropped
    # without a word. A phone holding it in its pool finds out at its next
    # request, and that is the case the app has to get through.
    protocol_version = "HTTP/1.1"
    timeout = 2.0
    #: a Stop said this request's reply never arrives
    cut = False

    def log_message(self, *a):
        pass

    def _send(self, status: int, obj=None, *, html: str | None = None,
              location: str | None = None):
        if self.cut:
            return
        body = b"" if obj is None and html is None else \
            (html.encode("utf-8") if html is not None else json.dumps(obj).encode("utf-8"))
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html is not None
                         else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _page(self, status: int, text: str, kind: str):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _go(self, method: str):
        account = self.server.account
        if account is None:                     # stopped: as good as no server
            self.close_connection = True
            self.connection.close()
            return
        if method == "GET" and self.headers.get("Upgrade", "").lower() == "websocket" \
                and self.path.startswith("/realtime/v1/websocket"):
            # Realtime: the account's own topic, the relay's channel (stage 3)
            self.close_connection = True
            account.websocket(self)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw and not self.path.startswith("/transcribe") else None
        except ValueError:
            self._send(400, {"message": "not JSON"})
            return
        try:
            account.route(self, method, body)
        except Refuse as e:
            log.info("refused %s %s: %s", method, self.path.split("?")[0], e.message)
            # supabase/auth's shape with no version header, and PostgREST's
            self._send(e.status, {"code": e.status, "error_code": e.code, "msg": e.message}
                       if self.path.startswith("/auth/") else {"code": e.code, "message": e.message})
        if self.cut:
            self.close_connection = True
            self.connection.close()

    def do_GET(self):
        self._go("GET")

    def do_POST(self):
        self._go("POST")

    def do_PATCH(self):
        self._go("PATCH")

    def do_DELETE(self):
        self._go("DELETE")


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class _Sock:
    """The server's end of one websocket: frames in (masked, as RFC 6455 has every
    client's), frames out (unmasked), and what Phoenix's join said."""

    def __init__(self, conn, rfile):
        self.conn, self.rfile = conn, rfile
        self.lock = threading.Lock()
        self.topic: str | None = None
        self.session: dict | None = None
        self.echo = False
        self.ack = False
        self.closed = False

    def _exactly(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            chunk = self.rfile.read(n - len(out))
            if not chunk:
                raise OSError("the client went")
            out += chunk
        return out

    def read(self) -> tuple[int, bytes]:
        parts, first = b"", None
        while True:
            h = self._exactly(2)
            fin, op = h[0] & 0x80, h[0] & 0x0F
            n = h[1] & 0x7F
            if n == 126:
                n = int.from_bytes(self._exactly(2), "big")
            elif n == 127:
                n = int.from_bytes(self._exactly(8), "big")
            if not h[1] & 0x80:
                raise ValueError("a client frame arrived unmasked")
            mask = self._exactly(4)
            raw = self._exactly(n)
            # XOR as one big integer: a byte loop is 50 ms a piece, which is not the server's
            data = (int.from_bytes(raw, "big") ^ int.from_bytes((mask * (n // 4 + 1))[:n], "big")
                    ).to_bytes(n, "big") if n else b""
            if op >= 0x8:
                return op, data
            first = op if first is None else first
            parts += data
            if fin:
                return first, parts

    def write(self, op: int, data: bytes) -> None:
        n = len(data)
        head = bytes([0x80 | op])
        if n < 126:
            head += bytes([n])
        elif n < 65536:
            head += bytes([126]) + n.to_bytes(2, "big")
        else:
            head += bytes([127]) + n.to_bytes(8, "big")
        with self.lock:
            if self.closed:
                raise OSError("closed")
            self.conn.sendall(head + data)

    def reply(self, ref, topic, status: str, response: dict) -> None:
        self.write(0x1, json.dumps({"event": "phx_reply", "topic": topic, "ref": ref,
                                    "payload": {"status": status, "response": response}}).encode())

    def close(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
        try:
            self.conn.sendall(bytes([0x88, 2, 0x03, 0xE8]))
        except OSError:
            pass
        try:
            self.conn.close()
        except OSError:
            pass


_LISTENERS: dict[int, _Server] = {}


class FakeAccount:
    """One account, one server, one PC of it. Everything in memory."""

    def __init__(self, port: int = 18791, email: str = "you@example.com", name: str = "Dana Levi"):
        self.port = port
        self.email = email
        self.name = name
        self.uid = str(uuid.uuid4())
        self.mutex = threading.RLock()
        #: code -> (challenge, session name) of a sign-in under way
        self.codes: dict[str, str] = {}
        self.authorized: list[dict] = []
        self.sessions: dict[str, dict] = {}         # session id -> the session
        #: how the next refresh is answered, for the test that wants a refusal
        self.refuse_refresh = False
        #: tokens that say their hour is nearly up, so that every call refreshes
        self.short_tokens = False
        #: refreshes that presented a token behind the active one
        self.behind = 0
        #: session ids alive on the server under another account
        self.others: set[str] = set()
        self.calls: list[tuple[str, str]] = []
        self.stops: list[Stop] = []
        self.broadcasts: list[dict] = []
        self.tables: dict[str, list[dict]] = {t: [] for t in COLUMNS}
        # the old road beside the account: a pasted address and token
        self.door_token = uuid.uuid4().hex
        #: what the second reading holds for this phone
        self.proposals: list[dict] = []
        # the PC of this account
        self.pc_id = str(uuid.uuid4())
        self.pc_name = "HOME-PC"
        self.key = os.urandom(32)
        #: Realtime's sockets, each joined to the account's topic or not yet
        self.sockets: list[_Sock] = []
        #: what the relay cost: messages as Supabase counts them (sent, and once per
        #: socket that received), the bytes pushed to clients, the largest message
        self.realtime = {"sent": 0, "received": 0, "egress": 0, "largest": 0, "refused": 0}
        #: True: the websocket is refused, as if the channel could not be reached
        self.realtime_off = False
        self.tables["profiles"].append({
            "user_id": self.uid, "lock_id": vault.fingerprint(self.key),
            "app_version_last_seen": "1.0.6", "is_anonymous": False, "created_at": now_iso()})
        self.write_pc_row()
        self._server = None

    # ---- running ----

    def start(self):
        """One listener per port for the life of the process, and each new
        account takes it over. A browser keeps idle sockets open, so a server
        stopped between two flows would go on answering on them."""
        server = _LISTENERS.get(self.port)
        if server is None:
            server = _LISTENERS[self.port] = _Server(("127.0.0.1", self.port), _Door)
            threading.Thread(target=server.serve_forever, daemon=True).start()
        server.account = self
        self._server = server
        log.info("the fake account is up on %s", self.port)
        return self

    def stop(self):
        """Nobody home: every request is refused the way a dead server's would be."""
        for caught in self.stops:
            caught.go()
        if self._server is not None:
            self._server.account = None
            self._server = None
        with self.mutex:
            socks, self.sockets = list(self.sockets), []
        for s in socks:
            s.close()

    # ---- Realtime: the account's private topic, over a websocket ----

    #: Supabase Free's broadcast cap (its limits page, 2026-11-11).
    PAYLOAD_MAX = 256_000

    def websocket(self, h):
        """One Realtime socket, as Supabase's answers it: Phoenix's join with the
        session's token on the private topic `realtime:user:<uid>`, heartbeats, and
        broadcasts fanned out to every other socket joined to it (to the sender too
        with `self: true`), acknowledged with `ack: true`, refused over the cap."""
        if h.headers.get("apikey") != PUBLISHABLE_KEY:
            h._send(401, {"message": "No API key found in request"})
            return
        if self.realtime_off:
            # the channel unreachable from here, as on a network that lets nothing through
            h._send(503, {"message": "Realtime is not answering"})
            return
        key = h.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
                                               .encode()).digest()).decode()
        h.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                       f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").encode())
        h.wfile.flush()
        h.connection.settimeout(None)
        sock = _Sock(h.connection, h.rfile)
        with self.mutex:
            self.sockets.append(sock)
        log.info("realtime: a socket opened")
        try:
            self._serve_ws(sock)
        except (OSError, ValueError) as e:
            log.info("realtime: a socket went (%s)", type(e).__name__)
        finally:
            with self.mutex:
                if sock in self.sockets:
                    self.sockets.remove(sock)
            sock.close()

    def _serve_ws(self, sock: "_Sock"):
        topic_ok = f"realtime:user:{self.uid}"
        while True:
            op, data = sock.read()
            if op == 0x8:
                return
            if op == 0x9:
                sock.write(0xA, data)
                continue
            if op != 0x1:
                continue
            msg = json.loads(data.decode("utf-8"))
            topic, event, ref = msg.get("topic"), msg.get("event"), msg.get("ref")
            payload = msg.get("payload") or {}
            if event == "heartbeat":
                sock.reply(ref, "phoenix", "ok", {})
            elif event == "phx_join":
                config = payload.get("config") or {}
                s = self.session_of(str(payload.get("access_token") or ""))
                if topic != topic_ok or config.get("private") is not True or s is None or s["expired"]:
                    with self.mutex:
                        self.realtime["refused"] += 1
                    sock.reply(ref, topic, "error", {"reason": "Unauthorized: You do not have permissions "
                                                               "to read from this Channel topic"})
                    continue
                broadcast = config.get("broadcast") or {}
                sock.topic, sock.session = topic, s
                sock.echo, sock.ack = bool(broadcast.get("self")), bool(broadcast.get("ack"))
                sock.reply(ref, topic, "ok", {"postgres_changes": []})
                log.info("realtime: joined")
            elif event == "access_token":
                s = self.session_of(str(payload.get("access_token") or ""))
                if s is not None:
                    sock.session = s
            elif event == "broadcast":
                if sock.topic != topic or sock.session is None or sock.session["expired"]:
                    sock.reply(ref, topic, "error", {"reason": "not joined"})
                    continue
                if len(data) > self.PAYLOAD_MAX:
                    with self.mutex:
                        self.realtime["refused"] += 1
                    sock.reply(ref, topic, "error", {"reason": "Payload too large"})
                    continue
                inner = payload.get("payload") or {}
                self._fanout(topic, str(payload.get("event") or ""), inner, sender=sock)
                if sock.ack:
                    sock.reply(ref, topic, "ok", {})

    def _fanout(self, topic: str, event: str, inner: dict, sender=None):
        """One broadcast to every socket joined to [topic], and what it cost."""
        text = json.dumps({"event": "broadcast", "topic": topic, "ref": None,
                           "payload": {"type": "broadcast", "event": event, "payload": inner}})
        with self.mutex:
            self.broadcasts.append({"event": event, **inner})
            to = [s for s in self.sockets if s.topic == topic and (s is not sender or s.echo)]
            self.realtime["sent"] += 1
            self.realtime["received"] += len(to)
            self.realtime["egress"] += len(text) * len(to)
            self.realtime["largest"] = max(self.realtime["largest"], len(text))
        for s in to:
            try:
                s.write(0x1, text.encode("utf-8"))
            except OSError:
                pass

    def stop_at(self, method: str, table: str, *, hold: bool = True, cut: bool = False,
                land: bool = True, answer=None) -> Stop:
        """The next such request stops at the door: Stop says what happens to it."""
        stop = Stop(method, table, hold, cut, land, answer)
        with self.mutex:
            self.stops.append(stop)
        return stop

    def _stopped(self, h, method: str, path: str) -> bool:
        """True when the request ends here."""
        with self.mutex:
            stop = next((s for s in self.stops if s.method == method and not s.caught.is_set()
                         and path.endswith("/" + s.table)), None)
            if stop is not None:
                stop.caught.set()
        if stop is None:
            return False
        if stop.hold:
            stop.released.wait(18)              # the phone gives up at 20
        if stop.answer is not None:
            h._page(*stop.answer)
            return True
        h.cut = stop.cut
        return stop.cut and not stop.land

    # ---- the PC ----

    def pc_link(self) -> dict:
        return {"v": 1, "kind": "pc", "cert": hashlib.sha256(b"fake pc cert").hexdigest(),
                "addrs": ["192.168.1.20"], "port": 8766, "proto": 1, "words_sync": True,
                "history_sync": True}

    # ---- the cloud keys and what was said (stage 2b) ----

    def put_key(self, name: str, value: str):
        """A key as a PC puts one in the account: vault.export_keys' own seal."""
        sealed = vault.seal_json(self.key, {"v": value}, vault.AAD_VAULT.format(uid=self.uid, name=name))
        with self.mutex:
            self.tables["vault"] = [r for r in self.tables["vault"] if r["name"] != name]
            self.tables["vault"].append({"user_id": self.uid, "name": name, "cipher": sealed,
                                         "updated_at": now_iso()})

    def key_row(self, name: str):
        """What the account's row for ``name`` opens to, as a PC's import_keys opens
        it, or None for no row. A test reads this; nothing logs it."""
        with self.mutex:
            row = next((r for r in self.tables["vault"] if r["name"] == name), None)
        if row is None:
            return None
        return vault.open_json(self.key, row["cipher"], vault.AAD_VAULT.format(uid=self.uid, name=name))

    def history(self) -> list[dict]:
        with self.mutex:
            return [dict(r) for r in self.tables["history"]]

    def write_pc_row(self, *, device: str | None = None, name: str | None = None,
                     link: dict | None = None):
        """A PC's row, sealed the way phone.py seals one."""
        device = device or self.pc_id
        sealed = vault.seal_json(self.key, link or self.pc_link(),
                                 AAD_DEVICE.format(uid=self.uid, device_id=device))
        row = {"id": device, "user_id": self.uid, "name": name or self.pc_name,
               "platform": "windows-10.0.26200", "app_version": "1.0.6", "tier": "gpu",
               "created_at": now_iso(), "last_seen": now_iso(), "link": sealed,
               "session_id": None}
        with self.mutex:
            self.tables["devices"] = [r for r in self.tables["devices"] if r["id"] != device]
            self.tables["devices"].append(row)
        return row

    def requests(self) -> list[dict]:
        """The open requests to join."""
        with self.mutex:
            return [dict(r) for r in self.tables["pairings"] if not r.get("handed")]

    def request_of(self, device: str) -> dict | None:
        rows = [r for r in self.requests() if r["device_id"] == device]
        return rows[-1] if rows else None

    def code_of(self, row: dict, lock_id: str | None = None) -> str:
        """The code this PC's Home would show for a request."""
        return pairing_code(self.uid, row["id"], row["applicant"],
                            lock_id or vault.fingerprint(self.key))

    def approve(self, pid: str, key: bytes | None = None):
        """[Approve] on this PC: the real hand_over, on the row."""
        with self.mutex:
            row = next(r for r in self.tables["pairings"] if r["id"] == pid)
            row["handed"] = vault.hand_over(key or self.key, row["applicant"],
                                            vault.AAD_PAIRING.format(uid=self.uid, pairing_id=pid))
            row["approved_at"] = now_iso()
        log.info("the PC approved a request")

    def decline(self, pid: str):
        with self.mutex:
            self.tables["pairings"] = [r for r in self.tables["pairings"] if r["id"] != pid]

    def pc_asks(self, name: str = "NEW-PC", device: str | None = None) -> dict:
        """Another PC asks to join: the real applicant half, the row as
        sb._request_pairing writes it."""
        pid = str(uuid.uuid4())
        device = device or str(uuid.uuid4())
        public = vault.applicant(pid)
        lock_id = vault.fingerprint(self.key)
        code = pairing_code(self.uid, pid, public, lock_id)
        row = {"id": pid, "user_id": self.uid, "device_id": device, "device_name": name,
               "code": vault.code_hint(code), "applicant": public, "handed": None,
               "created_at": now_iso(),
               "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
               "approved_at": None}
        with self.mutex:
            self.tables["pairings"].append(row)
        return dict(row, full_code=code)

    def pc_takes(self, pid: str) -> bytes:
        """The asking PC opens what the phone handed over: the real take."""
        with self.mutex:
            row = next(r for r in self.tables["pairings"] if r["id"] == pid)
        return vault.take(pid, row["handed"], vault.AAD_PAIRING.format(uid=self.uid, pairing_id=pid))

    def change_lock(self, key: bytes | None = None) -> bytes:
        """The account's lock moves: a new key at the PC and on the profile."""
        self.key = key or os.urandom(32)
        with self.mutex:
            self.tables["profiles"][0]["lock_id"] = vault.fingerprint(self.key)
        return self.key

    def row_of(self, device: str) -> dict | None:
        with self.mutex:
            return next((dict(r) for r in self.tables["devices"] if r["id"] == device), None)

    def phones(self) -> list[dict]:
        with self.mutex:
            return [dict(r) for r in self.tables["devices"]
                    if str(r.get("platform")).startswith("android")]

    def open_link(self, row: dict) -> dict:
        """A device's row as a PC opens it: the real open_json. A row that
        does not open is an error here, and ignored by a real PC."""
        return vault.open_json(self.key, row["link"],
                               AAD_DEVICE.format(uid=self.uid, device_id=row["id"]))

    def forgotten(self) -> list[dict]:
        """The `forgotten` row, opened with the real vault."""
        with self.mutex:
            row = next((r for r in self.tables["vault"] if r["name"] == "forgotten"), None)
        if row is None:
            return []
        inside = vault.open_json(self.key, row["cipher"],
                                 vault.AAD_VAULT.format(uid=self.uid, name="forgotten"))
        return inside["v"]

    def write_forgotten(self, entries: list[dict]):
        """The account's list as a PC writes it."""
        cipher = vault.seal_json(self.key, {"v": entries},
                                 vault.AAD_VAULT.format(uid=self.uid, name="forgotten"))
        with self.mutex:
            self.tables["vault"] = [r for r in self.tables["vault"] if r["name"] != "forgotten"]
            self.tables["vault"].append({"user_id": self.uid, "name": "forgotten",
                                         "cipher": cipher, "updated_at": now_iso()})

    def end_session(self, sid: str):
        """What 0006 makes effective at once."""
        with self.mutex:
            self.sessions.pop(sid, None)

    def end_every_session(self):
        with self.mutex:
            self.sessions.clear()

    def expire_tokens(self):
        """Every access token's hour is up. The refresh token still works."""
        with self.mutex:
            for s in self.sessions.values():
                s["expired"] = True

    def events(self, name: str) -> list[dict]:
        with self.mutex:
            return [dict(b) for b in self.broadcasts if b["event"] == name]

    # ---- auth ----

    def _token(self, sid: str) -> str:
        def b64(d: dict) -> str:
            return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
        return ".".join((b64({"alg": "none"}),
                         b64({"sub": self.uid, "session_id": sid, "exp": int(time.time()) + 3600,
                              "n": uuid.uuid4().hex}),
                         "not-signed"))

    def _session_json(self, sid: str, session: dict) -> dict:
        hour = 5 if self.short_tokens else 3600
        return {"access_token": session["access"], "refresh_token": session["refresh"],
                "token_type": "bearer", "expires_in": hour,
                "expires_at": int(time.time()) + hour,
                "user": {"id": self.uid, "email": self.email, "is_anonymous": False,
                         "created_at": now_iso(),
                         "user_metadata": {"full_name": self.name}}}

    def _new_session(self) -> dict:
        sid = str(uuid.uuid4())
        session = {"id": sid, "access": self._token(sid), "refresh": uuid.uuid4().hex,
                   "parent": "", "older": set(), "refreshed": time.time(), "expired": False}
        self.sessions[sid] = session
        return self._session_json(sid, session)

    def session_of(self, token: str) -> dict | None:
        with self.mutex:
            for s in self.sessions.values():
                if s["access"] == token:
                    return s
        return None

    def _bearer(self, h) -> dict:
        said = h.headers.get("Authorization", "")
        s = self.session_of(said[7:]) if said.startswith("Bearer ") else None
        if s is None or s["expired"]:
            raise Refuse(401, "PT401", "this session was signed out")
        return s

    def _auth(self, h, method: str, path: str, query: dict, body):
        if path == "authorize" and method == "GET":
            code = uuid.uuid4().hex
            back = query.get("redirect_to", "")
            challenge = query.get("code_challenge", "")
            if query.get("provider") != "google" or query.get("code_challenge_method") != "s256" \
                    or not challenge or back != "deskit://auth":
                raise Refuse(400, "bad_request", "not the request sb.sign_in_google makes")
            with self.mutex:
                self.codes[code] = challenge
                self.authorized.append({"code": code, "challenge": challenge})
            target = f"{back}?code={code}"
            h._send(200, html=f'<html><body style="font-size:48px"><a id="go" href="{target}">'
                              f"Continue as {self.email}</a></body></html>")
            return
        if path == "token" and method == "POST":
            grant = query.get("grant_type")
            if grant == "pkce":
                with self.mutex:
                    challenge = self.codes.pop(str(body.get("auth_code")), None)
                verifier = str(body.get("code_verifier") or "")
                made = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                if challenge is None or made.rstrip(b"=").decode() != challenge:
                    raise Refuse(400, "validation_failed", "invalid flow state, no valid flow state found")
                with self.mutex:
                    h._send(200, self._new_session())
                return
            if grant == "refresh_token":
                self._refresh(h, str(body.get("refresh_token") or ""))
                return
        if path == "logout" and method == "POST":
            s = self._bearer(h)
            scope = query.get("scope", "global")
            with self.mutex:
                if scope == "local":
                    self.sessions.pop(s["id"], None)
                elif scope == "others":
                    self.sessions = {s["id"]: s}
                else:
                    self.sessions.clear()
            h._send(204)
            return
        raise Refuse(404, "not_found", f"no such auth call: {method} {path}")

    def _refresh(self, h, token: str):
        """As supabase/auth's RefreshTokenGrant does it. The active token rotates.
        One behind it is a reply that never reached the client, at any age, and
        answers the active token. Further behind is the same within ten seconds of
        the last refresh; after that it is reuse, and the session ends."""
        with self.mutex:
            s = next((x for x in self.sessions.values() if token == x["refresh"]
                      or token == x["parent"] or token in x["older"]), None)
            if s is None or self.refuse_refresh:
                raise Refuse(400, "refresh_token_not_found",
                             "Invalid Refresh Token: Refresh Token Not Found")
            if token == s["refresh"]:
                if s["parent"]:
                    s["older"].add(s["parent"])
                s["parent"] = token
                s["refresh"] = uuid.uuid4().hex
                s["refreshed"] = time.time()
            else:
                self.behind += 1
                if token != s["parent"] and time.time() - s["refreshed"] >= 10:
                    self.sessions.pop(s["id"], None)
                    raise Refuse(400, "refresh_token_already_used",
                                 "Invalid Refresh Token: Already Used")
            s["access"] = self._token(s["id"])
            s["expired"] = False
            h._send(200, self._session_json(s["id"], s))

    # ---- the tables ----

    @staticmethod
    def _matches(row: dict, filters: list[tuple[str, str, str]]) -> bool:
        for col, op, value in filters:
            have = row.get(col)
            if op == "eq" and str("" if have is None else have) != value:
                return False
            if op == "is" and value == "null" and have is not None:
                return False
        return True

    @staticmethod
    def _filters(table: str, pairs: list[tuple[str, str]]):
        filters, select, order, limit, on_conflict = [], None, None, None, None
        for k, v in pairs:
            if k == "select":
                select = v.split(",")
                bad = [c for c in select if c not in COLUMNS[table]]
                if bad:
                    raise Refuse(400, "42703", f"column {table}.{bad[0]} does not exist")
            elif k == "order":
                order = v.split(".")[0]
            elif k == "limit":
                limit = int(v)
            elif k == "on_conflict":
                on_conflict = v.split(",")
            else:
                if k not in COLUMNS[table]:
                    raise Refuse(400, "42703", f"column {table}.{k} does not exist")
                op, _, value = v.partition(".")
                if op not in ("eq", "is"):
                    raise Refuse(400, "PGRST100", f"the fake does not know the operator {op}")
                filters.append((k, op, value))
        return filters, select, order, limit, on_conflict

    @staticmethod
    def _check(table: str, row: dict):
        """What the migrations check on a row that is about to be written."""
        bad = [c for c in row if c not in COLUMNS[table]]
        if bad:
            raise Refuse(400, "PGRST204", f"Could not find the '{bad[0]}' column of '{table}'")
        def refuse(what: str):
            raise Refuse(400, "23514", f"new row for {table} violates a check: {what}")
        if table == "pairings":
            if not UUID_RE.match(str(row.get("id"))):
                raise Refuse(400, "22P02", "the id is not a uuid")
            if not UUID_RE.match(str(row.get("device_id"))):
                raise Refuse(400, "22P02", "the device id is not a uuid")
            if len(str(row.get("device_name") or "")) > 40:
                refuse("device_name is past 40 characters")
            if not CODE_RE.match(str(row.get("code"))):
                refuse("code is not eight characters of the alphabet")
            if looks_like_key(str(row.get("device_name") or "")):
                refuse("device_name looks like a key")
            if not vault.is_sealed(str(row.get("applicant"))):
                refuse("applicant is not sealed")
            if row.get("handed") is not None and not vault.is_sealed(str(row["handed"])):
                refuse("handed is not sealed")
        if table == "devices":
            if not UUID_RE.match(str(row.get("id"))):
                raise Refuse(400, "22P02", "the id is not a uuid")
            if len(str(row.get("name") or "")) > 40:
                refuse("name is past 40 characters")
            if len(str(row.get("platform") or "")) > 32:
                refuse("platform is past 32 characters")
            if len(str(row.get("app_version") or "")) > 32:
                refuse("app_version is past 32 characters")
            for column in ("name", "platform", "app_version"):
                if looks_like_key(str(row.get(column) or "")):
                    refuse(f"{column} looks like a key")
            if str(row.get("tier") or "") not in ("", "gpu", "gpu_small", "cpu", "cloud"):
                refuse("tier")
            if row.get("link") is not None and not vault.is_sealed(str(row["link"])):
                refuse("link is not sealed")
            sid = row.get("session_id")
            if sid is not None and not UUID_RE.match(str(sid)):
                raise Refuse(400, "22P02", "session_id is not a uuid")
        if table == "vault":
            if not re.fullmatch(r"[a-z][a-z_]{0,31}", str(row.get("name"))):
                refuse("name")
            if not vault.is_sealed(str(row.get("cipher"))):
                refuse("cipher is not sealed")
        if table == "history":
            if not UUID_RE.match(str(row.get("device_id"))):
                raise Refuse(400, "22P02", "the device id is not a uuid")
            if str(row.get("kind")) not in ("dictation", "translate", "punctuate", "lookup", "learned"):
                refuse("kind")
            engine = str(row.get("engine") or "")
            if len(engine) > 32 or looks_like_key(engine):
                refuse("engine")
            if row.get("seconds") is not None and not 0 <= float(row["seconds"]) <= 36000:
                refuse("seconds")
            if not vault.is_sealed(str(row.get("cipher"))):
                refuse("cipher is not sealed")
            try:
                datetime.fromisoformat(str(row.get("ts")))
            except ValueError:
                raise Refuse(400, "22007", "ts is not a timestamp")

    def _table(self, h, method: str, table: str, pairs, body, session: dict):
        filters, select, order, limit, on_conflict = self._filters(table, pairs)
        uid = self.uid
        prefer = h.headers.get("Prefer", "")
        with self.mutex:
            mine = [r for r in self.tables[table] if r.get("user_id") == uid]
            hit = [r for r in mine if self._matches(r, filters)]
            if method == "GET":
                rows = sorted(hit, key=lambda r: str(r.get(order) or "")) if order else hit
                rows = rows[:limit] if limit else rows
                h._send(200, [{k: r.get(k) for k in (select or r)} for r in rows])
                return
            if method == "POST":
                row = dict(body or {})
                if row.get("user_id") != uid:
                    raise Refuse(403, "42501", f"new row violates row-level security for {table}")
                if "created_at" in COLUMNS[table]:
                    row.setdefault("created_at", now_iso())
                if table == "pairings":
                    row.setdefault("expires_at",
                                   (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat())
                    row.setdefault("handed", None)
                    row.setdefault("approved_at", None)
                if table in ("vault", "history"):
                    row["updated_at"] = now_iso()
                self._check(table, row)
                keys = on_conflict or (["id"] if "id" in COLUMNS[table] else [])
                same = next((r for r in self.tables[table]
                             if keys and all(r.get(k) == row.get(k) for k in keys)), None)
                if same is not None:
                    if same.get("user_id") != uid:
                        raise Refuse(403, "42501", f"row-level security on {table}")
                    if "resolution=merge-duplicates" not in prefer:
                        raise Refuse(409, "23505", f"duplicate key on {table}")
                    same.update(row)
                else:
                    self.tables[table].append(row)
                h._send(201)
                return
            if method == "PATCH":
                changes = dict(body or {})
                if table == "pairings" and set(changes) - {"handed", "approved_at"}:
                    raise Refuse(400, "P0001", "pairings: only handed and approved_at may change after insert")
                for r in hit:
                    probe = dict(r, **changes)
                    self._check(table, probe)
                    r.update(changes)
                h._send(200 if "return=representation" in prefer else 204,
                        [dict(r) for r in hit] if "return=representation" in prefer else None)
                return
            if method == "DELETE":
                gone = {id(r) for r in hit}
                self.tables[table] = [r for r in self.tables[table] if id(r) not in gone]
                h._send(204)
                return
        raise Refuse(405, "PGRST117", f"{method} on {table}")

    def _forget(self, h, body, session: dict):
        """0007's forget_device, a JSON boolean: true when no session of that row is
        left, ended here or already over; false when there was no row, the row named
        none, or it named one that is not this account's."""
        target = str((body or {}).get("target") or "")
        if not UUID_RE.match(target):
            raise Refuse(400, "22P02", "target is not a uuid")
        ended = False
        with self.mutex:
            row = next((r for r in self.tables["devices"]
                        if r["id"] == target and r["user_id"] == self.uid), None)
            if row is not None:
                self.tables["devices"] = [r for r in self.tables["devices"] if r["id"] != target]
                sid = row.get("session_id")
                if sid:
                    ended = self.sessions.pop(sid, None) is not None or sid not in self.others
        h._send(200, ended)

    def _pc_door(self, h, path: str):
        """The PC's old door, as far as Home asks it on the way up."""
        if path == "/health":
            h._send(200, {"ok": True, "version": "1.0.6"})
            return
        if h.headers.get("Authorization") != f"Bearer {self.door_token}":
            raise Refuse(401, "no_token", "not this PC's token")
        if path == "/api/version":
            h._send(200, {"pc": "1.0.6", "ime_min": 0, "ime_latest": 0})
            return
        if path == "/transcribe":
            h._send(200, {"text": "words", "backend": "fake", "seconds": 0.1})
            return
        h._send(200, {"items": list(self.proposals)})

    def route(self, h, method: str, body):
        split = urllib.parse.urlsplit(h.path)
        path = split.path
        pairs = urllib.parse.parse_qsl(split.query, keep_blank_values=True)
        with self.mutex:
            self.calls.append((method, path))
        log.info("%s %s", method, path)
        if self._stopped(h, method, path):
            return
        if path in ("/health", "/api/version", "/review", "/transcribe"):
            self._pc_door(h, path)
            return
        if path.startswith("/auth/v1/"):
            # the browser's GET carries no apikey; the app's calls do
            if method != "GET" and h.headers.get("apikey") != PUBLISHABLE_KEY:
                raise Refuse(401, "no_api_key", "No API key found in request")
            self._auth(h, method, path[len("/auth/v1/"):], dict(pairs), body)
            return
        if h.headers.get("apikey") != PUBLISHABLE_KEY:
            raise Refuse(401, "no_api_key", "No API key found in request")
        session = self._bearer(h)
        if path == "/realtime/v1/api/broadcast":
            for m in (body or {}).get("messages") or []:
                if m.get("topic") != f"user:{self.uid}" or m.get("private") is not True:
                    raise Refuse(403, "42501", "not this account's topic")
                # every socket joined to the topic hears it, as Realtime's own
                self._fanout(f"realtime:{m.get('topic')}", str(m.get("event") or ""),
                             m.get("payload") or {})
                log.info("broadcast %s", m.get("event"))
            h._send(202, {})
            return
        if path == "/rest/v1/rpc/forget_device":
            self._forget(h, body, session)
            return
        table = path[len("/rest/v1/"):] if path.startswith("/rest/v1/") else ""
        if table not in COLUMNS:
            raise Refuse(404, "42P01", f"no such table: {table}")
        self._table(h, method, table, pairs, body, session)


# ------------------------------------------------------------ the PC's door

def phone_server():
    """The real phone server with fake hooks, on 127.0.0.1:8790: what the
    emulator reaches as http://10.0.2.2:8790. Transcribes to a fixed Hebrew
    sentence, holds one pending proposal from the phone, answers lookups."""
    import dataclasses
    import config as config_mod
    import server as server_mod

    cfg = config_mod.load_layered()
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
    return srv


if __name__ == "__main__":
    if "--account" in sys.argv:
        acct = FakeAccount()
        acct.start()
        print(f"the fake account on 127.0.0.1:{acct.port}, signed in as {acct.email}", flush=True)
        srv = None
    else:
        srv = phone_server()
        print("up", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        if srv is not None:
            srv.stop()
