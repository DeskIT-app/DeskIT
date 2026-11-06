"""What the keyboard talks to, faked for the emulator, on loopback: what it
reaches as http://10.0.2.2:<port>. No real server, no real account, nothing of
the owner's: every key here is made fresh and dies with the process.

    python fake_pc.py             the PC's phone server, real server.py with
                                  fake hooks, on 8790
    python fake_pc.py --account   the account alone, on 8791

``FakeAccount`` is the account: enough of Supabase for everything a phone does
(the sign-in with its PKCE, refresh, REST on the four tables, forget_device,
the broadcast), checking what the real migrations check, so a wrong column or
a bad shape fails here as it would there. And it is a PC of that account: it
holds the account key and answers with the REAL vault.py, so a join on the
emulator is a join against the real formats. flow_account.py drives it.
Build the app for it with `gradle assembleDebug -PdeskitAccount=http://10.0.2.2:8791`.

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


class Refuse(Exception):
    """What the database would say: a status and a body."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class _Door(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, status: int, obj=None, *, html: str | None = None,
              location: str | None = None):
        body = b"" if obj is None and html is None else \
            (html.encode("utf-8") if html is not None else json.dumps(obj).encode("utf-8"))
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html is not None
                         else "application/json")
        self.send_header("Content-Length", str(len(body)))
        # One request per connection: a browser or a client holding a
        # keep-alive socket would otherwise go on talking to the fake of the
        # flow before, whose thread is still serving it.
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _go(self, method: str):
        account = self.server.account
        if account is None:                     # stopped: as good as no server
            self.close_connection = True
            self.connection.close()
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            self._send(400, {"message": "not JSON"})
            return
        try:
            account.route(self, method, body)
        except Refuse as e:
            log.info("refused %s %s: %s", method, self.path.split("?")[0], e.message)
            self._send(e.status, {"code": e.code, "message": e.message})

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


_LISTENERS: dict[int, _Server] = {}


class FakeAccount:
    """One account, one server, one PC of it. Everything in memory."""

    def __init__(self, port: int = 8791, email: str = "you@example.com", name: str = "Dana Levi"):
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
        self.calls: list[tuple[str, str]] = []
        self.broadcasts: list[dict] = []
        self.tables: dict[str, list[dict]] = {t: [] for t in COLUMNS}
        # the PC of this account
        self.pc_id = str(uuid.uuid4())
        self.pc_name = "HOME-PC"
        self.key = os.urandom(32)
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
        if self._server is not None:
            self._server.account = None
            self._server = None

    # ---- the PC ----

    def pc_link(self) -> dict:
        return {"v": 1, "kind": "pc", "cert": hashlib.sha256(b"fake pc cert").hexdigest(),
                "addrs": ["192.168.1.20"], "port": 8766, "proto": 1, "words_sync": True}

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
        return {"access_token": session["access"], "refresh_token": session["refresh"],
                "token_type": "bearer", "expires_in": 3600,
                "expires_at": int(time.time()) + 3600,
                "user": {"id": self.uid, "email": self.email, "is_anonymous": False,
                         "created_at": now_iso(),
                         "user_metadata": {"full_name": self.name}}}

    def _new_session(self) -> dict:
        sid = str(uuid.uuid4())
        session = {"id": sid, "access": self._token(sid), "refresh": uuid.uuid4().hex,
                   "used": [], "expired": False}
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
                token = str(body.get("refresh_token") or "")
                with self.mutex:
                    s = next((x for x in self.sessions.values() if x["refresh"] == token), None)
                    if s is None or self.refuse_refresh:
                        raise Refuse(400, "refresh_token_not_found",
                                     "Invalid Refresh Token: Refresh Token Not Found")
                    s["access"] = self._token(s["id"])
                    s["refresh"] = uuid.uuid4().hex
                    s["expired"] = False
                    h._send(200, self._session_json(s["id"], s))
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
                if table == "vault":
                    row.setdefault("updated_at", now_iso())
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
        target = str((body or {}).get("target") or "")
        if not UUID_RE.match(target):
            raise Refuse(400, "22P02", "target is not a uuid")
        with self.mutex:
            row = next((r for r in self.tables["devices"]
                        if r["id"] == target and r["user_id"] == self.uid), None)
            if row is not None:
                self.tables["devices"] = [r for r in self.tables["devices"] if r["id"] != target]
                sid = row.get("session_id")
                if sid:
                    self.sessions.pop(sid, None)
        h._send(204)

    def route(self, h, method: str, body):
        split = urllib.parse.urlsplit(h.path)
        path = split.path
        pairs = urllib.parse.parse_qsl(split.query, keep_blank_values=True)
        with self.mutex:
            self.calls.append((method, path))
        log.info("%s %s", method, path)
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
                with self.mutex:
                    self.broadcasts.append({"event": m.get("event"), **(m.get("payload") or {})})
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
