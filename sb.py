"""The account: the one server DeskIT itself runs, and everything the app
says to it.

DISTRIBUTION_PLAN.md chapter 8 (8.6 auth and the session, 8.7 this
module's contract, 8.8 the outbox), decisions D17 and D31. A Supabase
project — ``PROJECT_REF`` below, region Frankfurt, Free plan — holds one
row per account and, for people who turned the syncs on, their learned
words, their changed settings and what they said; and the problem
reports they chose to send. Its whole schema is
``supabase/migrations/0001_init.sql`` in the repo, and no table in it has
a column that could hold a key (D12 lock 3).

What this module is allowed to be (chapter 8.7, ``test_sb_imports_are_narrow``):

- It knows two public constants: the project ref and the PUBLISHABLE
  key. The key opens nothing — every table's ``anon`` grant is revoked —
  and net.py attaches it as the ``apikey`` header on this host alone.
- Every request goes through ``net.py`` with a declared purpose
  (``account``, ``sync``, ``history``, ``report``), so each appears in
  Dashboard > Network and the Offline switch refuses it. No SDK: an SDK
  owns its transport and would bypass the window (D12 lock 2).
- The session — access token, refresh token, expiry, the user — is one
  JSON blob in ``DATA_DIR\\secrets\\supabase.bin`` (DPAPI, user scope)
  under the name ``supabase_session``; net.py reads the access token
  out of it by NAME when a call says ``secret="supabase_session"``. The
  value never lands in a log or a file of any other kind.
- It never imports the modules that read a cloud key, never sees a
  ``Config`` object, and references neither provider by name.

Sign-in is Google (D31: free, no domain, no SMTP) through Supabase's
PKCE flow with a one-shot listener on 127.0.0.1 — the browser comes back
to this process with a code, the code is exchanged here, and the page
it lands on is the app's own (``signin_page``); foreground.py then
brings the app's window back in front of the browser and cards the
account — or anonymous (a report-only account, later linkable to
Google). Exactly one process holds the session: the app; the dashboard
asks it over the control pipe.

Sync (D31, sync.py holds the shapes): pull, merge, push — the learned
words as rows, the settings overrides as one blob, this PC's
transcripts.log events as rows and the other PCs' rows into
``sync\\history.log``. Each behind its own gate: ``settings_sync`` for
words and settings, ``history_sync`` for what was said.

Live (the owner, 2026-09-20: "I sync, and not two seconds pass and it
is on the other app"): every push ends with one broadcast on the
account's private Realtime topic (``user:<uid>``, a REST POST that
carries only the store names and this device's id — nothing anyone
said), and every signed-in copy holds one websocket on that topic
(``net.websocket``, one row on the Network screen while it is open)
and pulls the named store the moment a broadcast from another device
lands. Measured from this PC on the day: broadcast to arrival 0.15 to
0.30 s. The 15-minute pass stays as the net under it; the row-level
security on ``realtime.messages`` (migration 0003) is what keeps one
account's topic from another.

The lock (the owner, 2026-09-21: the cloud keys and the text of what
he said locked before they leave, so the same account opens them on
every PC of his and the server cannot): vault.py holds the key and does
the sealing; this module only moves what it produces. Every pass
starts with ``_ensure_lock``: the first PC of an account makes the key
and writes its fingerprint on the profile; a PC without the key asks
to join (``_request_pairing`` — a row in ``pairings`` with its public
key and an eight-character code it shows) and waits for a PC that has
it to approve (``approve_pairing`` — the key wrapped to that public
key, never in the clear), or for the person to type the recovery key
(``recover``). ``history.cipher`` and the ``vault`` rows (the cloud
keys, one per name) are sealed under the account key and opened only
here; ``ts``, ``kind`` and ``engine`` stay readable for the ordering.
Until the key is here those two stores say "waiting for the lock" and
their cursors do not move; the words and settings sync as before.

Failure is a log line and a later retry, never a dialog (8.8): a paused
project, no network and a 5xx all read the same. A 401 is one refresh
attempt; a second 401 means the account is gone (deleted from another
PC) and the session is dropped.
"""
from __future__ import annotations

import base64
import hashlib
import html
import http.server
import json
import logging
import os
import platform
import re
import shutil
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone

import net
import paths
import privacy
import secretstore
import sync
import vault

log = logging.getLogger("app")

# ---------------------------------------------------------- the constants

#: The project ref — the owner's Supabase project ``DeskIT``, created
#: 2026-09-18 in eu-central-1 (Frankfurt) on the Free plan (8.11 step 1).
#: Empty in a build without a project: every function then answers "not
#: configured" without touching the network.
PROJECT_REF: str = "eogvmcbwfthxedcltyrs"

#: The PUBLISHABLE key of that project (8.11 step 2). Public by design:
#: it is in this file, in every install and in the keep-alive workflow.
#: The secret key never appears anywhere in this repo.
PUBLISHABLE_KEY: str = "sb_publishable_p3pBXir64azVPAS1wtQoVg_mgi5ZOCt"

SESSION_NAME = "supabase_session"

#: The owner's rule of 2026-09-18 evening, in his words: the app is not
#: used without an account — one sign-in, remembered until Sign out.
#: main.App.locked() reads it: with a configured project and no session
#: the keys stay inert and the wizard's account page has no way past.
#: tests.py sets it False at import so half-built Apps are not locked;
#: the lock's own tests set it back.
REQUIRED: bool = True

#: Called (no arguments) when the session goes away under the app — a
#: second 401, a dead refresh token, Sign out, Delete my account — so the
#: app can lock again. main.App registers its lock here.
SIGNED_OUT_HOOKS: list = []


def _signed_out() -> None:
    for hook in list(SIGNED_OUT_HOOKS):
        try:
            hook()
        except Exception:                                    # noqa: BLE001
            log.debug("a signed-out hook tripped", exc_info=True)

#: Refresh when this little of the access token's hour is left (8.6).
REFRESH_MARGIN_S = 10
#: The longest name the account keeps — the devices table's own cap.
NAME_MAX = 40
#: How long the browser may take to come back with a code.
SIGNIN_TIMEOUT_S = 180
#: The worker: first sync this long after start, then every CADENCE.
FIRST_DELAY_S = 30.0
CADENCE_S = 15 * 60.0
#: A nudge (a dictation just ended) waits this long for the next one
#: — 5 s until 2026-09-20, when the live channel made the wait the
#: largest part of the two seconds the owner asked for.
NUDGE_SETTLE_S = 0.5
#: The live channel: off in a build without a project, and off in
#: tests.py at import (a fake project has no websocket to hold).
LIVE_ENABLED: bool = True
#: Phoenix drops a socket that is quiet for a minute; a heartbeat every
#: this often keeps it, and is when a refreshed session token is sent.
LIVE_HEARTBEAT_S = 25.0
#: After a lost or refused socket: wait this long before the next try,
#: one step further along the tuple each time, back to the start on a
#: socket that held.
LIVE_RETRY_S: tuple[float, ...] = (5.0, 15.0, 60.0, 300.0)
#: The account's own topic — ``realtime:`` in front of it on the socket,
#: bare on the REST broadcast.
LIVE_TOPIC = "user:{uid}"
#: How long the other PCs' names (the devices table) are believed
#: before they are asked for again, so a live pull is one request.
DEVICE_NAMES_TTL_S = 600.0
#: The device row is refreshed at most this often.
DEVICE_SEEN_EVERY_S = 24 * 3600.0
TIMEOUT_S = 20.0
#: The lock: a PC that holds the account's key believes it for this
#: long before it reads the profile's fingerprint again.
LOCK_TTL_S = 600.0
#: A request to join lives this long on the server (the migration's
#: default too) and is made afresh after.
PAIRING_TTL_S = 15 * 60.0
#: While this PC waits to be approved the worker looks this often
#: (the live channel's ``paired`` event makes it immediate).
PAIRING_POLL_S = 5.0
#: Called with the request dict when another PC of this account asks
#: to join and this PC holds the key — main.App puts up the card.
PAIRING_HOOKS: list = []
#: Called (no arguments) when this PC's key arrived or the lock's state
#: changed — the wizard and the desk redraw.
LOCK_HOOKS: list = []


def configure(ref: str | None = None, key: str | None = None) -> None:
    """Tell net.py the project host and the publishable key. Called at
    import with the constants; a test calls it with a fixture project."""
    global PROJECT_REF, PUBLISHABLE_KEY
    if ref is not None:
        PROJECT_REF = ref.strip()
    if key is not None:
        PUBLISHABLE_KEY = key.strip()
    net.configure_supabase(f"{PROJECT_REF}.supabase.co" if PROJECT_REF else None,
                           PUBLISHABLE_KEY or None)


def configured() -> bool:
    return bool(PROJECT_REF and PUBLISHABLE_KEY)


def base_url() -> str:
    return f"https://{PROJECT_REF}.supabase.co"


# ------------------------------------------------------------- exceptions

class AccountError(Exception):
    """Something the person should read: not configured, not signed in,
    the browser did not come back, the server refused. ``str(e)`` is the
    sentence."""


class NotAllowed(AccountError):
    """The gate for the call is shut (privacy.allowed said no) — the
    quiet answer every entry point gives before touching the network."""


# ---------------------------------------------------------------- session

_lock = threading.RLock()
_status: dict = {"busy": "", "last_error": "", "last_sync": "", "signin_url": ""}
#: The session, read from the DPAPI blob once and kept here: status()
#: is polled by the dashboard several times a second, and a
#: DPAPI unprotect per poll is not free. The app is the one process
#: that writes the blob, so the copy cannot go stale under it.
_cache: dict = {"loaded": False, "session": None}


def _load_session() -> dict | None:
    with _lock:
        if _cache["loaded"]:
            return _cache["session"]
        session = _read_session()
        _cache.update(loaded=True, session=session)
        return session


def _read_session() -> dict | None:
    try:
        raw = secretstore.get(SESSION_NAME)
    except Exception as e:                                   # noqa: BLE001
        log.warning("account: the session blob could not be read (%s)", e)
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        log.warning("account: the session blob is not JSON — dropped")
        secretstore.delete(SESSION_NAME)
        return None
    return data if isinstance(data, dict) and data.get("access_token") else None


def forget_cache() -> None:
    """Re-read the blob on the next call — a test that wrote it by hand,
    or the CLI after the app changed it."""
    with _lock:
        _cache.update(loaded=False, session=None)


def _store_session(data: dict) -> dict:
    """Keep what the server answered, with an absolute expiry: a
    ``pythonw`` that slept through hibernate must not trust a timer."""
    now = time.time()
    expires_at = data.get("expires_at")
    if not expires_at:
        expires_at = now + float(data.get("expires_in") or 3600)
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    meta = user.get("user_metadata") if isinstance(user.get("user_metadata"), dict) else {}
    session = {
        "access_token": str(data.get("access_token") or ""),
        "refresh_token": str(data.get("refresh_token") or ""),
        "expires_at": float(expires_at),
        "user": {
            "id": str(user.get("id") or ""),
            "is_anonymous": bool(user.get("is_anonymous", not user.get("email"))),
            "email": str(user.get("email") or ""),
            "created_at": str(user.get("created_at") or ""),
            # the name the person typed on the account page (set_name),
            # or the one Google gave; it rides in the auth user's
            # metadata, so a second PC has it the moment it signs in
            "name": str(meta.get("name") or meta.get("full_name") or "")[:NAME_MAX],
        },
    }
    secretstore.set(SESSION_NAME, json.dumps(session))
    with _lock:
        _cache.update(loaded=True, session=session)
    return session


def _clear_session() -> None:
    try:
        secretstore.delete(SESSION_NAME)
    except Exception:                                        # noqa: BLE001
        log.debug("account: session delete failed", exc_info=True)
    with _lock:
        _cache.update(loaded=True, session=None)


def signed_in() -> bool:
    return _load_session() is not None


def user() -> dict | None:
    """``{"id", "is_anonymous", "email", "created_at", "name"}`` or None."""
    session = _load_session()
    return dict(session["user"]) if session else None


# -------------------------------------------------------------- transport

def _json(status: int, body: bytes):
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        return None


def _server_said(status: int, body: bytes) -> str:
    """One readable line out of an error answer, for the log and the
    Account row — the server's message, never a token."""
    data = _json(status, body)
    if isinstance(data, dict):
        for key in ("msg", "message", "error_description", "error", "hint"):
            if data.get(key):
                return f"HTTP {status}: {str(data[key])[:160]}"
    text = body.decode("utf-8", "replace")[:160].strip()
    return f"HTTP {status}" + (f": {text}" if text else "")


def _auth(path: str, payload: dict | None, *, query: str = "",
          bearer: bool = False, method: str = "POST") -> tuple[int, object]:
    """One call to the auth endpoint. ``bearer`` sends the session."""
    if not configured():
        raise AccountError("the account server is not configured in this build")
    url = f"{base_url()}/auth/v1/{path}" + (f"?{query}" if query else "")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    status, _h, raw = net.request(method, url, "account",
                                  secret=SESSION_NAME if bearer else None,
                                  headers=headers, body=body, timeout_s=TIMEOUT_S)
    return status, (_json(status, raw) if status < 400 else raw)


def _refresh() -> dict:
    session = _load_session()
    if not session or not session.get("refresh_token"):
        raise AccountError("not signed in")
    status, data = _auth("token", {"refresh_token": session["refresh_token"]},
                         query="grant_type=refresh_token")
    if status != 200 or not isinstance(data, dict):
        if status in (400, 401, 403, 404):
            # The refresh token was revoked or used elsewhere: the
            # account is gone or signed out from another PC (8.8).
            _account_gone(f"the session could not be refreshed ({_server_said(status, data if isinstance(data, bytes) else b'')})")
        raise AccountError(f"the session could not be refreshed ({status})")
    return _store_session(data)


def _fresh() -> dict:
    """The session, refreshed first when its hour is (nearly) over."""
    with _lock:
        session = _load_session()
        if session is None:
            raise AccountError("not signed in")
        if float(session.get("expires_at") or 0) - time.time() <= REFRESH_MARGIN_S:
            session = _refresh()
        return session


def _account_gone(why: str) -> None:
    """A second 401, or a dead refresh token: drop the session and the
    cursors; the next sign-in starts clean. Never a dialog."""
    log.warning("account: %s — signed out on this PC", why)
    _clear_session()
    sync.forget_all()
    _forget_lock_state()
    _status["last_error"] = why
    _signed_out()


def _rest(method: str, table: str, *, purpose: str, query: str = "",
          payload=None, prefer: str = "") -> tuple[int, object]:
    """One PostgREST call under the session. A 401 is one refresh and
    one retry; a second 401 drops the session (8.8)."""
    if not configured():
        raise AccountError("the account server is not configured in this build")
    _fresh()
    url = f"{base_url()}/rest/v1/{table}" + (f"?{query}" if query else "")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    for attempt in (1, 2):
        status, _h, raw = net.request(method, url, purpose, secret=SESSION_NAME,
                                      headers=headers, body=body, timeout_s=TIMEOUT_S)
        if status != 401:
            return status, (_json(status, raw) if status < 400 else raw)
        if attempt == 1:
            with _lock:
                _refresh()
            continue
        _account_gone("the server refused the session twice")
        raise AccountError("the account is gone — sign in again")
    raise AccountError("unreachable")                        # pragma: no cover


def _storage(method: str, path: str, *, body: bytes | None = None,
             content_type: str = "", payload=None,
             purpose: str = "report") -> tuple[int, bytes]:
    if not configured():
        raise AccountError("the account server is not configured in this build")
    _fresh()
    url = f"{base_url()}/storage/v1/{path}"
    headers: dict = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif body is not None:
        headers["Content-Type"] = content_type or "application/octet-stream"
        headers["x-upsert"] = "false"
    status, _h, raw = net.request(method, url, purpose, secret=SESSION_NAME,
                                  headers=headers, body=body, timeout_s=60.0)
    return status, raw


# ----------------------------------------------------------- the profile

def device_id() -> str:
    """This PC's id in the account, minted once into state.json."""
    import config
    state = config.read_state(paths.STATE_FILE)
    ident = str(state.get("account.device_id") or "")
    if not ident:
        ident = str(uuid.uuid4())
        config.save({"account.device_id": ident})
    return ident


def device_name() -> str:
    import config
    state = config.read_state(paths.STATE_FILE)
    name = str(state.get("account.device_name") or "").strip()
    if not name:
        name = (platform.node() or "this PC").strip()
    return name[:40]


def _app_version() -> str:
    try:
        import version
        return str(version.VERSION)[:32]
    except Exception:                                        # noqa: BLE001
        return ""


def _tier() -> str:
    try:
        import hardware
        facts = hardware.recorded() or {}
        tier = str(facts.get("tier") or "")
        return tier if tier in ("gpu", "gpu_small", "cpu", "cloud") else ""
    except Exception:                                        # noqa: BLE001
        return ""


def _platform() -> str:
    try:
        import sys
        w = sys.getwindowsversion()
        return f"windows-{w.major}.{w.minor}.{w.build}"[:32]
    except Exception:                                        # noqa: BLE001
        return "windows"


def ensure_profile(force: bool = False) -> None:
    """The profile row and this PC's device row, upserted after a
    sign-in and then at most once a day (8.2)."""
    session = _fresh()
    uid = session["user"]["id"]
    import config
    state = config.read_state(paths.STATE_FILE)
    seen = float(state.get("account.device_seen_at") or 0)
    if not force and time.time() - seen < DEVICE_SEEN_EVERY_S:
        return
    status, data = _rest("POST", "profiles", purpose="account",
                         query="on_conflict=user_id",
                         payload={"user_id": uid, "app_version_last_seen": _app_version(),
                                  "is_anonymous": bool(session["user"]["is_anonymous"])},
                         prefer="resolution=merge-duplicates,return=minimal")
    if status not in (200, 201, 204):
        raise AccountError(f"the profile row was refused ({_server_said(status, data)})")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    status, data = _rest("POST", "devices", purpose="account",
                         query="on_conflict=id",
                         payload={"id": device_id(), "user_id": uid,
                                  "name": device_name(), "platform": _platform(),
                                  "app_version": _app_version(), "tier": _tier(),
                                  "last_seen": now},
                         prefer="resolution=merge-duplicates,return=minimal")
    if status not in (200, 201, 204):
        raise AccountError(f"the device row was refused ({_server_said(status, data)})")
    config.save({"account.device_seen_at": time.time()})


# ---------------------------------------------------------------- sign-in

def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(48)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# THE PAGE THE BROWSER LANDS ON. It is the last thing the person sees
# before the app, and until 2026-09-19 it was a bare white page in Hebrew
# — "you can close this tab" — over which he had to go and find the
# window himself. It is the app's own surface now: LAMPLIGHT (skin\
# palette.py — ground #14110C, card #24201A, text #F1ECE2, dim #B2A896,
# the gold #E3A63C only where the palette allows it, the focus ring), the
# mark inline from icon.png, English (the first-run flow's language, his
# decision that night), one card, one plain button. Nothing is fetched:
# no font, no script, no image from anywhere — a page on 127.0.0.1 that
# reached out would be the one network row nobody asked for. The gold
# does not fill the button: the lamp in the mark is the one lit thing on
# the surface (palette rule 1). foreground.bring_back() is what makes the
# second sentence true; the button is for the browsers that let a script
# close a tab it did not open, and the sentence is for the rest.
_PAGE_CSS = (
    ":root{color-scheme:dark}"
    "html,body{height:100%;margin:0}"
    "body{background:#14110c radial-gradient(60% 45% at 50% 0%,#292011 0%,#14110c 70%);"
    "color:#f1ece2;font-family:system-ui,'Segoe UI',Rubik,Arial,sans-serif;"
    "display:flex;align-items:center;justify-content:center;box-sizing:border-box;"
    "padding:24px 16px;-webkit-font-smoothing:antialiased}"
    "main{background:#24201a;border:1px solid #3a342a;border-radius:16px;"
    "padding:40px 36px 34px;max-width:420px;width:100%;text-align:center;"
    "box-shadow:0 24px 60px rgba(0,0,0,.45)}"
    ".mark{width:72px;height:72px;display:block;margin:0 auto 22px;border-radius:17px}"
    "h1{font-size:22px;font-weight:600;line-height:1.3;margin:0 0 10px;letter-spacing:-.01em}"
    "p{color:#b2a896;font-size:15px;line-height:1.55;margin:0 0 26px}"
    "p.why{color:#f1ece2;background:#1c1813;border:1px solid #3a342a;border-radius:10px;"
    "padding:10px 14px;font-size:14px;word-break:break-word}"
    "button{font:inherit;font-size:15px;font-weight:600;color:#f1ece2;background:#29241d;"
    "border:1px solid #4e4737;border-radius:10px;padding:11px 24px;cursor:pointer}"
    "button:hover{background:#332d24;border-color:#5a5240}"
    "button:active{background:#1f1b15}"
    "button:focus-visible{outline:2px solid #e3a63c;outline-offset:2px}"
    "small{display:block;margin-top:20px;color:#7e7564;font-size:12px}"
)
_PAGE_JS = (
    "function shut(){window.close();setTimeout(function(){"
    "var b=document.getElementById('close');"
    "if(b){b.textContent='Press Ctrl+W to close it'}},400)}"
)
_MARK_URI: str | None = None


def _mark_uri() -> str:
    """The mark for the page: icon.png — the file the taskbar shows — as
    a data: URI, read once; "" when a copy has no icon, and the page
    then simply carries no picture."""
    global _MARK_URI
    if _MARK_URI is None:
        try:
            raw = (paths.APP_DIR / "icon.png").read_bytes()
            _MARK_URI = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        except OSError:
            _MARK_URI = ""
    return _MARK_URI


def signin_page(ok: bool, why: str = "") -> str:
    """The loopback page: the signed-in card, or the one that says the
    sign-in did not finish and quotes Google's reason (escaped — it
    arrives on the query string)."""
    mark = _mark_uri()
    picture = f'<img class="mark" src="{mark}" alt="" width="72" height="72">' if mark else ""
    if ok:
        title = "Signed in to DeskIT"
        body = ("<h1>You’re signed in to DeskIT</h1>"
                "<p>DeskIT is back in front — you can close this tab.</p>")
    else:
        title = "DeskIT — the sign-in did not finish"
        reason = html.escape(" ".join(str(why or "").split())[:200] or "no code came back")
        body = ("<h1>The sign-in did not finish</h1>"
                f'<p class="why">{reason}</p>'
                "<p>Go back to DeskIT and press Sign in again.</p>")
    return ("<!doctype html><html lang=\"en\" dir=\"ltr\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{title}</title><style>{_PAGE_CSS}</style>"
            f"<script>{_PAGE_JS}</script></head><body><main>"
            f"{picture}{body}"
            "<button id=\"close\" type=\"button\" onclick=\"shut()\">Close this tab</button>"
            "<small>DeskIT · this page came from the app on this PC</small>"
            "</main></body></html>")


class _Callback(http.server.BaseHTTPRequestHandler):
    """The one-shot listener the browser comes back to: ``/cb?code=…``
    on 127.0.0.1 and a random port, alive for one request."""

    result: dict = {}

    def do_GET(self) -> None:                                # noqa: N802
        parts = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(parts.query))
        if parts.path != "/cb":
            self.send_response(404)
            self.end_headers()
            return
        if query.get("code"):
            type(self).result = {"code": query["code"]}
            page = signin_page(True)
        else:
            why = query.get("error_description") or query.get("error") or "no code"
            type(self).result = {"error": str(why)}
            page = signin_page(False, str(why))
        data = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args) -> None:                   # quiet
        pass


def _listen(timeout_s: float) -> tuple[http.server.HTTPServer, str]:
    """Bind the callback on a free loopback port; the redirect URL."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _Callback)
    server.timeout = timeout_s
    _Callback.result = {}
    return server, f"http://127.0.0.1:{server.server_port}/cb"


def _wait_for_code(server: http.server.HTTPServer, timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline and not _Callback.result:
            server.timeout = max(0.5, min(5.0, deadline - time.monotonic()))
            server.handle_request()
    finally:
        server.server_close()
    result = dict(_Callback.result)
    _Callback.result = {}
    if result.get("code"):
        return result["code"]
    if result.get("error"):
        raise AccountError(f"Google did not sign you in: {result['error']}")
    raise AccountError("the browser did not come back in time — try again")


def _exchange(code: str, verifier: str) -> dict:
    status, data = _auth("token", {"auth_code": code, "code_verifier": verifier},
                         query="grant_type=pkce")
    if status != 200 or not isinstance(data, dict) or not data.get("access_token"):
        raise AccountError(f"the sign-in code was refused ({_server_said(status, data if isinstance(data, bytes) else b'')})")
    return _store_session(data)


def sign_in_google(open_browser=None, timeout_s: float = SIGNIN_TIMEOUT_S) -> dict:
    """Sign in with Google (D31): Supabase's PKCE flow, the system
    browser, the code back on a loopback listener, exchanged here. An
    anonymous session already held is LINKED to the Google identity
    (same uid, reports and rows stay attached); otherwise a fresh
    sign-in. Returns the user dict. Raises AccountError with the
    sentence for the Account row."""
    privacy.require("account")
    if not configured():
        raise AccountError("the account server is not configured in this build")
    import webbrowser
    opener = open_browser or webbrowser.open
    verifier, challenge = _pkce()
    server, redirect = _listen(timeout_s)
    query = urllib.parse.urlencode({
        "provider": "google", "redirect_to": redirect,
        "code_challenge": challenge, "code_challenge_method": "s256",
    })
    try:
        session = _load_session()
        if session is not None and session["user"].get("is_anonymous"):
            # Link the Google identity to the anonymous account: the
            # server answers with the provider URL instead of redirecting
            # (skip_http_redirect), because the caller is not a browser.
            status, data = _auth("user/identities/authorize", None, method="GET",
                                 query=query + "&skip_http_redirect=true", bearer=True)
            if status != 200 or not isinstance(data, dict) or not data.get("url"):
                raise AccountError(f"linking was refused ({_server_said(status, data if isinstance(data, bytes) else b'')})")
            url = str(data["url"])
        else:
            url = f"{base_url()}/auth/v1/authorize?{query}"
        _status["signin_url"] = url
        _status["busy"] = "waiting for the browser"
        log.info("account: sign-in with Google started, listening on %s", redirect)
        if not opener(url):
            raise AccountError("the browser could not be opened")
        code = _wait_for_code(server, timeout_s)
        session = _exchange(code, verifier)
    finally:
        _status["busy"] = ""
        _status["signin_url"] = ""
        try:
            server.server_close()
        except Exception:                                    # noqa: BLE001
            pass
    log.info("account: signed in (%s)", "Google" if session["user"]["email"] else "anonymous")
    _back_to_the_app(session["user"].get("email", ""))
    sync.forget_all()
    try:
        ensure_profile(force=True)
    except AccountError as e:
        log.warning("account: %s", e)
    _status["last_error"] = ""
    return dict(session["user"])


def _back_to_the_app(email: str) -> None:
    """The browser has the foreground when the code comes back, and the
    person is looking at it. foreground.py brings the app's window (the
    wizard or the dashboard) in front of it and puts up the app's own
    card naming the account, with the way back on it. Both are a
    courtesy: neither may fail a sign-in that has succeeded, and a copy
    without the module simply does without."""
    try:
        import foreground
    except Exception:                                        # noqa: BLE001
        return
    for step in (lambda: foreground.bring_back(),
                 lambda: foreground.signed_in_card(email)):
        try:
            step()
        except Exception:                                    # noqa: BLE001
            log.debug("account: the way back to the app tripped", exc_info=True)


def sign_in_anonymous() -> dict:
    """A report-only account: no e-mail, no name, the uid is the only
    identifier (8.6). Linkable to Google later."""
    privacy.require("account")
    if _load_session() is not None:
        return dict(_load_session()["user"])
    status, data = _auth("signup", {"data": {}})
    if status != 200 or not isinstance(data, dict) or not data.get("access_token"):
        raise AccountError(f"the anonymous sign-in was refused ({_server_said(status, data if isinstance(data, bytes) else b'')})")
    session = _store_session(data)
    log.info("account: anonymous account created")
    sync.forget_all()
    try:
        ensure_profile(force=True)
    except AccountError as e:
        log.warning("account: %s", e)
    _status["last_error"] = ""
    return dict(session["user"])


def set_name(name: str) -> str:
    """The name typed on the wizard's account page (the owner,
    2026-09-20: "Create an account — maybe a field for the name too"):
    kept in the auth user's own metadata, not a table of ours — one
    PUT, and every PC that signs in afterwards reads it off the
    session. The redactor runs first, as on every string that leaves
    the PC; an empty name changes nothing. Returns what was kept."""
    import redact
    name = redact.redact(str(name or "").strip())[:NAME_MAX].strip()
    if not name:
        return ""
    session = _fresh()
    status, data = _auth("user", {"data": {"name": name}}, bearer=True, method="PUT")
    if status != 200:
        raise AccountError(f"the name was refused ({_server_said(status, data if isinstance(data, bytes) else b'')})")
    session = dict(session)
    session["user"] = {**session["user"], "name": name}
    secretstore.set(SESSION_NAME, json.dumps(session))
    with _lock:
        _cache.update(loaded=True, session=session)
    log.info("account: the name is kept")
    return name


def sign_out(everywhere: bool = True) -> None:
    """Sign out everywhere (the refresh tokens are revoked server-side),
    then forget the session and the cursors here. The local files stay.
    ``everywhere=False`` is the wizard's "Not you?": this PC's session
    only, the person's other PCs keep theirs."""
    session = _load_session()
    if session is not None and configured():
        try:
            _auth("logout", {}, query="scope=global" if everywhere else "scope=local",
                  bearer=True)
        except Exception as e:                               # noqa: BLE001
            log.info("account: the sign-out did not reach the server (%s) — "
                     "signed out here", e)
    _clear_session()
    sync.forget_all()
    _forget_lock_state()          # the key file stays: the same account back on this PC needs no approval
    _status["last_error"] = ""
    log.info("account: signed out")
    _signed_out()


def delete_account() -> None:
    """"Delete my account": this PC removes its own storage folder (it
    holds the delete policy), then calls ``delete_me()`` — rows, the
    auth user, every refresh token — then wipes the session, the
    account keys in state.json, the cursors and the outbox (8.5)."""
    session = _fresh()
    uid = session["user"]["id"]
    try:
        _purge_storage(uid)
    except Exception as e:                                   # noqa: BLE001
        log.info("account: storage purge before delete_me: %s", e)
    status, data = _rest("POST", "rpc/delete_me", purpose="account", payload={})
    if status not in (200, 204):
        raise AccountError(f"the server refused the deletion ({_server_said(status, data)})")
    _clear_session()
    sync.forget_all()
    vault.forget()
    _forget_lock_state()
    import config
    config.save({"account.device_id": None, "account.device_seen_at": None,
                 "account.device_name": None})
    _clear_outbox()
    _status["last_error"] = ""
    log.info("account: deleted on the server and forgotten here")
    _signed_out()


def _list_objects(prefix: str) -> list[str]:
    """The names under one folder of the bucket (relative to it)."""
    status, raw = _storage("POST", "object/list/reports", purpose="account",
                           payload={"prefix": prefix, "limit": 1000, "offset": 0})
    if status != 200:
        return []
    return [str(item.get("name")) for item in (_json(status, raw) or [])
            if isinstance(item, dict) and item.get("name")]


def _purge_storage(uid: str) -> int:
    """Every object under reports/<uid>/ — they sit one folder down,
    <uid>/<report_id>/<file> — removed by this client, which holds the
    delete policy. How many went."""
    files = [f"{uid}/{folder}/{name}"
             for folder in _list_objects(uid)
             for name in _list_objects(f"{uid}/{folder}")]
    if files:
        _storage("DELETE", "object/reports", payload={"prefixes": files}, purpose="account")
    return len(files)


def _clear_outbox() -> None:
    try:
        for entry in paths.OUTBOX_DIR.iterdir():
            _drop(entry)
    except OSError:
        pass


def _drop(entry) -> None:
    """One outbox entry gone: the payload, its .failed, or the folder of
    copies problems.queue() put beside it."""
    try:
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink()
    except OSError:
        pass


# ------------------------------------------------------------------- sync

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sync_settings(cursor: dict, push: bool = True) -> str:
    """Pull or push the settings blob (last writer wins). Returns one
    word for the log: pulled, pushed, same. ``push=False`` is a live
    pass: only what the other PC just wrote comes down."""
    import config
    overrides = config.read_settings(paths.SETTINGS_FILE)
    payload = sync.settings_payload(overrides)
    local_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False)
                                .encode("utf-8")).hexdigest()
    status, data = _rest("GET", "settings_sync", purpose="sync",
                         query="select=json,updated_at&limit=1")
    if status != 200:
        raise AccountError(f"settings: {_server_said(status, data)}")
    remote = (data or [None])[0] if isinstance(data, list) else None
    remote_at = str(remote.get("updated_at") or "") if remote else ""
    first = "settings_hash" not in cursor
    local_changed = local_hash != cursor.get("settings_hash")
    remote_changed = bool(remote) and remote_at != cursor.get("settings_updated_at")
    # A PC syncing for the first time takes what the account holds: its
    # own file is not "newer", it is merely untouched by the account yet
    # (measured 2026-09-18: the second PC's empty blob overwrote the
    # first's on its first pass when mtime decided).
    if remote_changed and (first or not local_changed or _remote_is_newer(remote_at)):
        merged = sync.merge_settings(overrides, remote.get("json") or {})
        # Validated as one whole before the real file is touched, the
        # way config.save does: a blob another PC wrote must not be
        # what stops this one from starting.
        tmp = paths.SETTINGS_FILE.with_name(paths.SETTINGS_FILE.name + ".sync")
        config.write_settings(tmp, merged)
        try:
            config.load_layered(settings=tmp)
        except Exception as e:                               # noqa: BLE001
            tmp.unlink(missing_ok=True)
            raise AccountError(f"settings: the other PC's settings would not load ({e})")
        os.replace(tmp, paths.SETTINGS_FILE)
        cursor["settings_updated_at"] = remote_at
        cursor["settings_hash"] = hashlib.sha256(
            json.dumps(sync.settings_payload(merged), sort_keys=True,
                       ensure_ascii=False).encode("utf-8")).hexdigest()
        return "pulled"
    if push and (local_changed or not remote):
        uid = _fresh()["user"]["id"]
        status, data = _rest("POST", "settings_sync", purpose="sync",
                             query="on_conflict=user_id",
                             payload={"user_id": uid, "json": payload},
                             prefer="resolution=merge-duplicates,return=representation")
        if status not in (200, 201):
            raise AccountError(f"settings: {_server_said(status, data)}")
        row = (data or [{}])[0] if isinstance(data, list) else (data or {})
        cursor["settings_updated_at"] = str(row.get("updated_at") or _now_iso())
        cursor["settings_hash"] = local_hash
        return "pushed"
    return "same"


def _remote_is_newer(remote_at: str) -> bool:
    try:
        mtime = paths.SETTINGS_FILE.stat().st_mtime
    except OSError:
        return True
    when = sync._parse_iso(remote_at)
    return when is not None and when.timestamp() >= mtime


def _sync_vocab(cursor: dict, vocab, push: bool = True) -> str:
    """Pull the other PCs' rows into the live vocabulary, push what
    changed here. ``vocab`` is the app's Vocab (or None to skip);
    ``push=False`` is a live pass, the pull alone."""
    if vocab is None:
        return "skipped"
    # A word list that could not be read at start (vocab.Vocab.broken)
    # tells the account nothing: every word it lacks would go out as a
    # tombstone and come off every PC. It pulls the whole list back
    # down instead, from the start of time (audit 2026-09-23, A7).
    broken = bool(getattr(vocab, "broken", None))
    since = "" if broken else str(cursor.get("vocab_pulled_at") or "")
    query = "select=heard,meant,hits,last_used,deleted,updated_at&order=updated_at.asc&limit=2000"
    if since:
        query += "&updated_at=gt." + urllib.parse.quote(since)
    status, rows = _rest("GET", "vocab_sync", purpose="sync", query=query)
    if status != 200 or not isinstance(rows, list):
        raise AccountError(f"vocabulary: {_server_said(status, rows)}")
    pulled = 0
    snapshot = dict(cursor.get("vocab_snapshot") or {})
    if rows:
        with vocab._write_lock:
            merged, pulled = sync.merge_vocab(vocab.corrections, rows)
            if pulled:
                vocab.corrections[:] = merged
                vocab.save()
            # what just came down counts as seen: it is not pushed back
            for entry in vocab.corrections:
                heard = str(entry.get("heard") or "").strip()
                if any(str(r.get("heard") or "").strip().lower() == heard.lower() for r in rows):
                    snapshot[heard] = {"hits": int(entry.get("hits", 1) or 0),
                                       "meant": str(entry.get("meant") or "").strip()}
            # ...and a tombstone that came down is not echoed back up as
            # one of this PC's own (nor counted by the guard below)
            gone = {str(r.get("heard") or "").strip().lower() for r in rows if r.get("deleted")}
            for key in [k for k in snapshot if k.strip().lower() in gone]:
                snapshot.pop(key, None)
        cursor["vocab_pulled_at"] = str(rows[-1].get("updated_at") or since)
    if broken:
        cursor["vocab_snapshot"] = snapshot
        mended = vocab.mend() if hasattr(vocab, "mend") else False
        log.warning("vocabulary sync: the word list could not be read at "
                    "start; %d word(s) came back from the account, nothing "
                    "was sent%s", pulled,
                    "" if mended else " (the unreadable file is still in the way)")
        return f"pulled {pulled}, pushed 0"
    with vocab._write_lock:
        corrections = [dict(c) for c in vocab.corrections]
    to_push = sync.vocab_changed(sync.vocab_rows(corrections, snapshot), snapshot) if push else []
    pushed = 0
    if not push:
        # the snapshot is not moved: what changed here since the last
        # full pass is still to push, and the next nudge pushes it
        if rows:
            cursor["vocab_snapshot"] = snapshot
        return f"pulled {pulled}, pushed 0"
    # The guard: a push that would delete MOST of what the account holds
    # from here is sent only for the words this PC was told to forget
    # (vocab.forget / a renamed edit, recorded in the file). The rest is
    # held back — not deleted anywhere — and the next pass pulls the
    # whole list again, which puts them back in this file. A damaged
    # file from an older build, a hand edit, a restore from an old copy:
    # each looks exactly like "forgot everything" to the snapshot.
    forgot = vocab.forgotten_keys() if hasattr(vocab, "forgotten_keys") else set()
    unasked = [r for r in to_push if r.get("deleted")
               and str(r.get("heard") or "").strip().lower() not in forgot]
    held = 0
    if unasked and len(unasked) * 2 > len(snapshot):
        held = len(unasked)
        to_push = [r for r in to_push if not any(r is u for u in unasked)]
        log.warning("vocabulary sync: %d of %d word(s) are missing here and "
                    "were never forgotten on this PC — not deleted from the "
                    "account; the next pass brings them back", held, len(snapshot))
    if to_push:
        uid = _fresh()["user"]["id"]
        for row in to_push:
            row["user_id"] = uid
        status, data = _rest("POST", "vocab_sync", purpose="sync",
                             query="on_conflict=user_id,heard",
                             payload=to_push,
                             prefer="resolution=merge-duplicates,return=representation")
        if status not in (200, 201):
            raise AccountError(f"vocabulary: {_server_said(status, data)}")
        pushed = len(to_push)
        stamps = [str(r.get("updated_at") or "") for r in (data or []) if isinstance(r, dict)]
        if stamps:
            cursor["vocab_pulled_at"] = max([cursor.get("vocab_pulled_at") or ""] + stamps)
        told = [r["heard"] for r in to_push if r.get("deleted")]
        if told and hasattr(vocab, "told"):
            vocab.told(told)
    cursor["vocab_snapshot"] = sync.vocab_snapshot(corrections)
    if held:
        # the held words are out of the snapshot now (never tombstoned
        # later) and a pull from the start brings them back down
        cursor["vocab_pulled_at"] = ""
        return f"pulled {pulled}, pushed {pushed}, held back {held}"
    return f"pulled {pulled}, pushed {pushed}"


_device_names: dict = {"at": 0.0, "names": {}}


def _names() -> dict[str, str]:
    """The other PCs' names, from the devices table, believed for
    DEVICE_NAMES_TTL_S so a live pull is one request, not two."""
    if time.monotonic() - _device_names["at"] < DEVICE_NAMES_TTL_S and _device_names["names"]:
        return dict(_device_names["names"])
    status, rows = _rest("GET", "devices", purpose="history", query="select=id,name")
    if status == 200 and isinstance(rows, list):
        _device_names["names"] = {str(r.get("id")): str(r.get("name") or "") for r in rows}
        _device_names["at"] = time.monotonic()
    return dict(_device_names["names"])


def _history_aad(uid: str, row: dict) -> str:
    """The associated data a history row is sealed under — its own key
    on the server, with the stamp in one canonical form, because
    Postgres hands a ``ts`` back without its trailing zeros."""
    when = sync._parse_iso(str(row.get("ts") or ""))
    ts = when.astimezone(timezone.utc).isoformat(timespec="milliseconds") if when else str(row.get("ts") or "")
    return vault.AAD_HISTORY.format(uid=uid, device_id=str(row.get("device_id") or ""),
                                    ts=ts, kind=str(row.get("kind") or ""))


def _seal_history(key: bytes, uid: str, row: dict) -> dict:
    """The row as it leaves: ``text`` and ``raw`` gone, ``cipher`` in
    their place."""
    text, raw = row.pop("text", ""), row.pop("raw", None)
    row["cipher"] = vault.seal_json(key, {"text": text, "raw": raw}, _history_aad(uid, row))
    return row


def _open_history(key: bytes, uid: str, row: dict) -> dict | None:
    """A pulled row with ``text`` and ``raw`` back in it, or None for a
    row this key does not open (logged by its stamp, never its text)."""
    try:
        inside = vault.open_json(key, str(row.get("cipher") or ""), _history_aad(uid, row))
    except vault.VaultError as e:
        log.info("history: the row of %s at %s did not open (%s)", row.get("device_id"), row.get("ts"), e)
        return None
    out = dict(row)
    out["text"] = str((inside or {}).get("text") or "")
    out["raw"] = (inside or {}).get("raw")
    return out


def _sync_history(cursor: dict, push: bool = True) -> str:
    """This PC's events up, the other PCs' events down (D31), each row
    sealed under the account key on the way up and opened on the way
    down; ``push=False`` is a live pass, the pull alone. Without the
    key on this PC nothing moves and the cursors stay: the rows wait
    for the approval."""
    import history
    mine = device_id()
    uid = _fresh()["user"]["id"]
    key = _lock_key(uid)
    if key is None:
        return "waiting for the lock"
    # down
    names = _names()
    pulled = unopened = 0
    for _round in range(10):
        since = str(cursor.get("history_pulled_at") or "")
        query = ("select=device_id,ts,kind,cipher,engine,seconds,updated_at"
                 "&order=updated_at.asc&limit=500&device_id=neq." + mine)
        if since:
            query += "&updated_at=gt." + urllib.parse.quote(since)
        status, rows = _rest("GET", "history", purpose="history", query=query)
        if status != 200 or not isinstance(rows, list):
            raise AccountError(f"history: {_server_said(status, rows)}")
        if not rows:
            break
        lines = []
        for r in rows:
            opened = _open_history(key, uid, r)
            if opened is None:
                unopened += 1
                continue
            lines.append(sync.remote_line(opened, names.get(str(r.get("device_id")), "")))
        pulled += sync.append_remote_history(lines)
        cursor["history_pulled_at"] = str(rows[-1].get("updated_at") or since)
        sync.write_cursor(cursor)
        if len(rows) < 500:
            break
    # up
    events = history.all_events() if push else []
    pushed = 0
    for _round in range(10):
        batch = sync.history_rows(events, mine, cursor.get("history_pushed_ts"))
        if not batch:
            break
        for row in batch:
            row["user_id"] = uid
            _seal_history(key, uid, row)
        status, data = _rest("POST", "history", purpose="history",
                             query="on_conflict=user_id,device_id,ts,kind",
                             payload=batch,
                             prefer="resolution=merge-duplicates,return=minimal")
        if status not in (200, 201, 204):
            raise AccountError(f"history: {_server_said(status, data)}")
        pushed += len(batch)
        cursor["history_pushed_ts"] = batch[-1]["ts"]
        sync.write_cursor(cursor)
        if len(batch) < sync.HISTORY_BATCH:
            break
    word = f"pulled {pulled}, pushed {pushed}"
    return word + (f", {unopened} not opened" if unopened else "")


def _sync_vault(cursor: dict, push: bool = True) -> str:
    """The cloud keys, one sealed row per name, under the words-and-
    settings gate (a key is a setting). Down: a row newer than the
    cursor that is not what this PC pushed goes into Credential Manager
    through vault.import_keys — this module never holds the value. Up:
    a name whose keyed digest moved since the last pass is exported
    sealed; a name that is empty here and was never synced is NOT
    pushed (a fresh PC must not wipe the account's keys), an emptied
    one is (a key removed here is removed everywhere). Last writer wins
    per name. ``push=False`` is the live pull."""
    uid = _fresh()["user"]["id"]
    key = _lock_key(uid)
    if key is None:
        return "waiting for the lock"
    pushed_ciphers: dict = dict(cursor.get("vault_pushed") or {})
    known: dict = dict(cursor.get("vault_digest") or {})
    # down
    since = str(cursor.get("vault_pulled_at") or "")
    query = "select=name,cipher,updated_at&order=updated_at.asc"
    if since:
        query += "&updated_at=gt." + urllib.parse.quote(since)
    status, rows = _rest("GET", "vault", purpose="sync", query=query)
    if status != 200 or not isinstance(rows, list):
        raise AccountError(f"keys: {_server_said(status, rows)}")
    incoming = {str(r.get("name")): str(r.get("cipher") or "") for r in rows
                if r.get("cipher") and str(r.get("cipher")) != pushed_ciphers.get(str(r.get("name")))}
    changed = vault.import_keys(key, uid, incoming) if incoming else []
    if rows:
        cursor["vault_pulled_at"] = str(rows[-1].get("updated_at") or since)
    if changed or incoming:
        digests, _present = vault.digest_keys(key)
        for name in incoming:
            known[name] = digests.get(name, "")
        cursor["vault_digest"] = known
        for name in incoming:
            pushed_ciphers.pop(name, None)
        cursor["vault_pushed"] = pushed_ciphers
    # up
    pushed = 0
    if push:
        digests, present = vault.digest_keys(key)
        to_push = [n for n, d in digests.items()
                   if known.get(n) != d and (n in present or n in known)]
        if to_push:
            sealed = vault.export_keys(key, uid, only=to_push)
            payload = [{"user_id": uid, "name": n, "cipher": c} for n, c in sealed.items()]
            status, data = _rest("POST", "vault", purpose="sync",
                                 query="on_conflict=user_id,name", payload=payload,
                                 prefer="resolution=merge-duplicates,return=representation")
            if status not in (200, 201):
                raise AccountError(f"keys: {_server_said(status, data)}")
            pushed = len(payload)
            stamps = [str(r.get("updated_at") or "") for r in (data or []) if isinstance(r, dict)]
            if stamps:
                cursor["vault_pulled_at"] = max([cursor.get("vault_pulled_at") or ""] + stamps)
            pushed_ciphers.update(sealed)
            cursor["vault_pushed"] = pushed_ciphers
            for n in to_push:
                known[n] = digests[n]
            cursor["vault_digest"] = known
    return f"pulled {len(changed)}, pushed {pushed}"


def has_synced_settings() -> bool:
    """Has this account ever pushed its settings — is this a PC joining
    an account that already has a DeskIT somewhere (the wizard's
    "welcome back", 2026-09-20)? One GET for the row's timestamp; False
    on anything but a row, so a road problem only means the ordinary
    wizard. The words and settings themselves come with sync_now."""
    try:
        if not configured() or not signed_in():
            return False
        status, data = _rest("GET", "settings_sync", purpose="sync",
                             query="select=updated_at&limit=1")
        return status == 200 and isinstance(data, list) and bool(data)
    except Exception as e:                                   # noqa: BLE001
        log.info("account: could not ask whether settings exist (%s)", e)
        return False


_sync_lock = threading.Lock()
STORES: tuple[str, ...] = ("settings", "vocab", "vault", "history")


def _pushed(name: str, word: str) -> bool:
    """Did this store's pass push anything — the log word read back."""
    if name == "settings":
        return word == "pushed"
    m = re.search(r"pushed (\d+)", word)
    return bool(m and int(m.group(1)) > 0)


def _broadcast(stores: list[str] | None = None, *, event: str = "changed",
               extra: dict | None = None) -> None:
    """Tell the account's other copies which stores just changed: one
    POST on the private topic, carrying the store names and this
    device's id and nothing else. The lock's two events ride the same
    topic — ``pairing`` (a PC asks to join: its request id, code and
    name) and ``paired`` (a PC approved: the request id) — and carry
    nothing a stranger could use: the code is compared on two screens,
    the key crosses wrapped inside the table. A failure is a debug line
    — the 15-minute pass delivers the rows all the same."""
    try:
        uid = _fresh()["user"]["id"]
        payload = {"device": device_id(), **(extra or {})}
        if stores:
            payload["stores"] = sorted(stores)
        status, _h, body = net.post_json(
            f"{base_url()}/realtime/v1/api/broadcast", "sync",
            {"messages": [{"topic": LIVE_TOPIC.format(uid=uid), "event": event,
                           "private": True, "payload": payload}]},
            secret=SESSION_NAME, timeout_s=TIMEOUT_S)
        if status not in (200, 202):
            log.debug("live: the broadcast was answered %s (%s)", status, _server_said(status, body))
    except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
        log.debug("live: no broadcast (%s)", e)


def sync_now(vocab=None, reason: str = "", only=None, push: bool = True) -> dict:
    """One pass over everything the gates allow — or, with ``only``, over
    those stores alone (a nudge names the store that changed; a live
    broadcast names the store the other PC changed, and ``push=False``
    then makes it a pull). Never raises: each store's outcome (or its
    error) is a word in the returned dict and a line in the log;
    ``last_sync``/``last_error`` feed the Account row. Nothing happens
    without a session or with every gate shut. Every push ends with a
    broadcast naming what was pushed. One pass at a time: the worker
    and the live thread share the cursor file."""
    out: dict[str, str] = {}
    if not configured() or not signed_in():
        return out
    words = privacy.allowed("settings_sync")
    said = privacy.allowed("history_sync")
    if not words and not said:
        return out
    wanted = set(STORES) if not only else {s for s in only if s in STORES}
    if not wanted:
        return out
    with _sync_lock:
        with _lock:
            _status["busy"] = "syncing"
        try:
            cursor = sync.read_cursor()
            try:
                ensure_profile()
            except (AccountError, net.EgressRefused, net.NetError) as e:
                out["profile"] = f"error: {e}"
            # the lock first: the key this pass seals and opens with,
            # made here on the account's first PC, asked for on the next
            try:
                key = _ensure_lock(_fresh()["user"]["id"])
                if key is not None:
                    _cursor_follows_lock(cursor, key)
            except (AccountError, net.EgressRefused, net.NetError, vault.VaultError, OSError) as e:
                out["lock"] = f"error: {e}"
                _lock_state["error"] = str(e)[:200]
            stores = []
            if words:
                stores += [("settings", lambda: _sync_settings(cursor, push=push)),
                           ("vocab", lambda: _sync_vocab(cursor, vocab, push=push)),
                           ("vault", lambda: _sync_vault(cursor, push=push))]
            if said:
                stores.append(("history", lambda: _sync_history(cursor, push=push)))
            stores = [(n, fn) for n, fn in stores if n in wanted]
            changed: list[str] = []
            for name, fn in stores:
                try:
                    out[name] = fn()
                    if _pushed(name, out[name]):
                        changed.append(name)
                except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
                    out[name] = f"error: {e}"
                if not signed_in():
                    # the account went away under us (a second 401): the
                    # cursors were dropped with it and must not come back
                    break
                sync.write_cursor(cursor)
            if changed and signed_in():
                _broadcast(changed)
            errors = [f"{k}: {v[7:]}" for k, v in out.items() if v.startswith("error: ")]
            if errors:
                _status["last_error"] = "; ".join(errors)[:200]
                log.info("sync%s: %s", f" ({reason})" if reason else "", "; ".join(errors))
            else:
                _status["last_error"] = ""
                _status["last_sync"] = _now_iso()
                log.info("sync%s: %s", f" ({reason})" if reason else "",
                         ", ".join(f"{k} {v}" for k, v in out.items()) or "nothing to do")
        except Exception as e:                                   # noqa: BLE001
            _status["last_error"] = str(e)[:200]
            log.warning("sync: tripped (%s)", e, exc_info=True)
        finally:
            with _lock:
                _status["busy"] = ""
    return out


# ------------------------------------------------------------ the outbox

#: What a queued report's JSON may carry into the row (8.2); anything
#: else in the file is dropped, so a future field cannot leak by accident.
REPORT_COLUMNS: tuple[str, ...] = ("id", "app_version", "os_build", "tier", "kind",
                                   "place", "text", "dictation_raw",
                                   "dictation_final", "env", "attachments")
MIMES: dict[str, str] = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                         ".json": "application/json", ".txt": "text/plain",
                         ".wav": "audio/wav"}


def queued() -> int:
    """How many reports wait in the outbox — the Account row's "N
    reports waiting"."""
    try:
        return sum(1 for p in paths.OUTBOX_DIR.glob("*.json")
                   if not p.with_suffix(".failed").exists())
    except OSError:
        return 0


def drain_outbox(on_sent=None) -> dict:
    """Upload every queued report: objects first, then the row (8.4), one
    report per unit, idempotent on the client-made id. A 4xx that is not
    auth marks the report ``.failed`` with the server's reason and stops
    retrying it (a poison report, 8.8); a 5xx or no network leaves it
    queued. Returns {report_id: "sent" | "failed: why" | "queued: why"}."""
    out: dict[str, str] = {}
    if not configured() or not signed_in() or not privacy.allowed("report_upload"):
        return out
    try:
        files = sorted(paths.OUTBOX_DIR.glob("*.json"))
    except OSError:
        return out
    for path in files:
        if path.with_suffix(".failed").exists():
            continue
        rid = path.stem
        try:
            report = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError) as e:
            out[rid] = f"failed: unreadable ({e})"
            _mark_failed(path, f"unreadable: {e}")
            continue
        try:
            out[rid] = _send_report(path, report)
        except (net.EgressRefused, net.NetError, AccountError, OSError) as e:
            out[rid] = f"queued: {e}"
            log.info("report %s: waiting to send (%s)", rid, e)
            break                              # the same wall stops them all
        if out[rid] == "sent":
            try:
                path.unlink()
            except OSError:
                pass
            _drop(path.with_suffix(""))           # the copies beside it
            if on_sent is not None:
                try:
                    on_sent(rid)
                except Exception:                            # noqa: BLE001
                    log.debug("on_sent tripped", exc_info=True)
    return out


def _mark_failed(path, why: str) -> None:
    try:
        path.with_suffix(".failed").write_text(why[:600], "utf-8")
    except OSError:
        pass


def _send_report(path, report: dict) -> str:
    uid = _fresh()["user"]["id"]
    rid = str(report.get("id") or path.stem)
    row = {k: report[k] for k in REPORT_COLUMNS if k in report}
    row["id"] = rid
    row["user_id"] = uid
    uploaded: list[str] = []
    for att in report.get("attachments") or []:
        if isinstance(att, str):
            att = {"name": os.path.basename(att), "path": att}
        name = os.path.basename(str(att.get("name") or ""))
        local = str(att.get("path") or "")
        if not name or not local:
            continue
        mime = MIMES.get(os.path.splitext(name)[1].lower())
        if mime is None:
            _mark_failed(path, f"{name}: not a kind of file a report may carry")
            return f"failed: {name}: not allowed"
        try:
            with open(local, "rb") as fh:
                data = fh.read()
        except OSError as e:
            _mark_failed(path, f"{name}: {e}")
            return f"failed: {name}: {e}"
        object_path = f"{uid}/{rid}/{name}"
        status, raw = _storage("POST", f"object/reports/{object_path}", body=data,
                               content_type=mime)
        if status in (200, 201) or (status in (400, 409) and b"exists" in raw.lower()):
            uploaded.append(object_path)
            continue
        if 400 <= status < 500 and status != 401:
            why = _server_said(status, raw)
            _mark_failed(path, f"{name}: {why}")
            return f"failed: {name}: {why}"
        raise AccountError(f"{name}: {_server_said(status, raw)}")
    row["attachments"] = uploaded
    status, data = _rest("POST", "problem_reports", purpose="report", payload=row,
                         prefer="return=minimal")
    if status in (200, 201, 204):
        log.info("report %s: sent", rid)
        return "sent"
    if status == 409:                                        # already there
        log.info("report %s: was already on the server", rid)
        return "sent"
    if 400 <= status < 500:
        why = _server_said(status, data)
        _mark_failed(path, why)
        log.info("report %s: refused, will not retry (%s)", rid, why)
        return f"failed: {why}"
    raise AccountError(_server_said(status, data))


# ----------------------------------------------------------- the worker

_wake = threading.Event()
_worker: threading.Thread | None = None
_live: threading.Thread | None = None
_pending: set[str] = set()          # the stores nudged since the last pass


def start_worker(vocab=None, on_sent=None) -> threading.Thread | None:
    """The app's background pass: FIRST_DELAY_S after start, then every
    CADENCE_S, and NUDGE_SETTLE_S after a nudge (a dictation ended, a
    consent opened, the person pressed Sync now) — over the stores the
    nudges named, or everything. Starts the live thread beside it. Does
    nothing without a configured project."""
    global _worker, _live
    if not configured() or (_worker is not None and _worker.is_alive()):
        return _worker

    def _settings_stamp():
        try:
            return paths.SETTINGS_FILE.stat().st_mtime_ns
        except OSError:
            return None

    def loop() -> None:
        _wake.wait(FIRST_DELAY_S)
        seen = _settings_stamp()
        while True:
            _wake.clear()
            with _lock:
                named = set(_pending)
                _pending.clear()
            # a setting saved on the desk (another process) since the
            # last pass rides along with whatever nudged this one
            stamp = _settings_stamp()
            if stamp != seen:
                seen = stamp
                named.add("settings")
            only = None if (not named or "*" in named) else sorted(named)
            try:
                if signed_in():
                    sync_now(vocab, reason="nudge" if only else "worker", only=only)
                    drain_outbox(on_sent)
                    if only is None and _lock_state.get("state") == "have":
                        # a PC of this account that asked to join while
                        # this app was closed, or its live channel down
                        pending_pairings()
            except Exception:                                # noqa: BLE001
                log.debug("account worker tripped", exc_info=True)
            wait = PAIRING_POLL_S if _lock_state.get("state") == "waiting" else CADENCE_S
            if _wake.wait(wait):
                time.sleep(NUDGE_SETTLE_S)

    _worker = threading.Thread(target=loop, daemon=True, name="account-sync")
    _worker.start()
    if LIVE_ENABLED and (_live is None or not _live.is_alive()):
        _live = threading.Thread(target=_live_loop, args=(vocab,), daemon=True,
                                 name="account-live")
        _live.start()
    return _worker


def nudge(store: str | None = None) -> None:
    """Something changed: sync soon — the named store (``history`` after
    a dictation, ``vocab`` after a learned word, ``settings`` after a
    save), or everything when nothing is named."""
    with _lock:
        _pending.add(store if store in STORES else "*")
    _wake.set()


# ------------------------------------------------------------- the live channel

_live_stop = threading.Event()
_live_state: dict = {"on": False, "error": ""}


def _live_purpose() -> str | None:
    """The purpose the socket is opened under — the gate that is open;
    None when neither sync is on and there is nothing to listen for."""
    if privacy.allowed("settings_sync"):
        return "sync"
    if privacy.allowed("history_sync"):
        return "history"
    return None


def _live_loop(vocab) -> None:
    """Hold the socket for as long as the account and a gate are there;
    reconnect with LIVE_RETRY_S between tries; never raise."""
    tries = 0
    while not _live_stop.is_set():
        try:
            if not (configured() and signed_in()) or _live_purpose() is None or net.offline:
                _live_state["on"] = False
                if _live_stop.wait(15.0):
                    return
                continue
            _live_once(vocab)
            tries = 0
        except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
            tries += 1
            why = str(e)[:200]
            (log.info if why != _live_state["error"] else log.debug)("live: %s", why)
            _live_state.update(on=False, error=why)
        except Exception:                                    # noqa: BLE001
            tries += 1
            log.debug("live: tripped", exc_info=True)
            _live_state["on"] = False
        if _live_stop.wait(LIVE_RETRY_S[min(tries, len(LIVE_RETRY_S) - 1)]):
            return


def _live_once(vocab) -> bool:
    """One socket: join the account's topic, answer heartbeats, pull the
    store a broadcast from another device names. Returns when the
    account, the gate or the network went away; raises when the socket
    was refused or dropped (the caller waits and tries again)."""
    purpose = _live_purpose()
    session = _fresh()
    uid = session["user"]["id"]
    token = str(session.get("access_token") or "")
    topic = "realtime:" + LIVE_TOPIC.format(uid=uid)
    ws = net.websocket(f"wss://{net.SUPABASE_HOST}/realtime/v1/websocket?vsn=1.0.0",
                       purpose, timeout_s=TIMEOUT_S)
    ref = 0

    def send(event: str, payload: dict, *, on_topic: str = topic, secret: str | None = None) -> None:
        nonlocal ref
        ref += 1
        ws.send_text(json.dumps({"topic": on_topic, "event": event, "payload": payload,
                                 "ref": str(ref)}), secret=secret)

    try:
        send("phx_join", {"config": {"broadcast": {"self": False}, "presence": {"key": ""},
                                     "postgres_changes": [], "private": True},
                          "access_token": "{secret}"}, secret=SESSION_NAME)
        reply = ws.recv_text(TIMEOUT_S)
        answer = json.loads(reply) if reply else {}
        if answer.get("event") != "phx_reply" or (answer.get("payload") or {}).get("status") != "ok":
            said = json.dumps((answer.get("payload") or {}).get("response") or answer)[:160]
            raise AccountError(f"the live channel refused the join: {said}")
        _live_state.update(on=True, error="")
        log.info("live: listening on the account's channel")
        if _lock_state.get("state") == "have":
            try:
                pending_pairings()
            except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
                log.debug("live: the pending requests were not read (%s)", e)
        beat = time.monotonic()
        while not _live_stop.is_set():
            if net.offline or _live_purpose() is None or not signed_in():
                ws.close("offline" if net.offline else "closed")
                return
            if time.monotonic() - beat >= LIVE_HEARTBEAT_S:
                beat = time.monotonic()
                send("heartbeat", {}, on_topic="phoenix")
                fresh = _fresh()
                if str(fresh.get("access_token") or "") != token:
                    token = str(fresh.get("access_token") or "")
                    send("access_token", {"access_token": "{secret}"}, secret=SESSION_NAME)
            text = ws.recv_text(1.0)
            if text is None:
                continue
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            event = msg.get("event")
            if event in ("phx_error", "phx_close"):
                raise AccountError(f"the live channel dropped ({event})")
            if event != "broadcast":
                continue
            inner = msg.get("payload") or {}
            what = inner.get("payload") or {}
            if str(what.get("device") or "") == device_id():
                continue
            if inner.get("event") == "pairing":
                # another PC of this account asks to join: its request
                # (and the card) come from the table, not from the event
                if _lock_state.get("state") == "have":
                    log.info("live: %s asks to join the account", what.get("name") or "another PC")
                    try:
                        pending_pairings()
                    except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
                        log.info("live: the request could not be read (%s)", e)
                continue
            if inner.get("event") == "paired":
                req = _lock_state.get("pairing")
                if req and str(what.get("id") or "") == req["id"]:
                    log.info("live: this PC was approved — taking the key")
                    sync_now(vocab, reason="paired")
                continue
            if inner.get("event") != "changed":
                continue
            stores = [s for s in (what.get("stores") or []) if s in STORES]
            if stores:
                log.info("live: %s changed on %s — pulling", ", ".join(stores),
                         _names().get(str(what.get("device") or ""), "another PC") or "another PC")
                sync_now(vocab, reason="live", only=stores, push=False)
        ws.close()
    except Exception:
        ws.close("dropped")
        raise
    finally:
        _live_state["on"] = False


def stop_live() -> None:
    """Tests, and the app on its way out: the live thread returns."""
    _live_stop.set()


# --------------------------------------------------------------- the lock

_lock_state: dict = {"at": 0.0, "state": "", "lock_id": "", "pairing": None,
                     "pending": [], "recovery": None, "error": ""}
_seen_pairings: set[str] = set()


def _run_lock_hooks() -> None:
    for hook in list(LOCK_HOOKS):
        try:
            hook()
        except Exception:                                    # noqa: BLE001
            log.debug("a lock hook tripped", exc_info=True)


def _set_lock(**fields) -> None:
    with _lock:
        _lock_state.update(fields)
        _lock_state["at"] = time.monotonic()
        _lock_state["error"] = ""
    _run_lock_hooks()


def _forget_lock_state() -> None:
    req = _lock_state.get("pairing")
    if req:
        vault.drop(req["id"])
    with _lock:
        _lock_state.update(at=0.0, state="", lock_id="", pairing=None, pending=[],
                           recovery=None, error="")
    _seen_pairings.clear()


def _lock_key(uid: str) -> bytes | None:
    """The key a store may seal with: this PC's, once ``_ensure_lock``
    said it is the account's."""
    return vault.key(uid) if _lock_state.get("state") == "have" else None


def _profile_lock_id(uid: str) -> str | None:
    """The account's fingerprint off the profile; None without a row."""
    status, rows = _rest("GET", "profiles", purpose="account", query="select=lock_id&limit=1")
    if status != 200 or not isinstance(rows, list):
        raise AccountError(f"lock: {_server_said(status, rows)}")
    return str(rows[0].get("lock_id") or "") if rows else None


def _claim_lock(uid: str, lock_id: str) -> bool:
    """Write the fingerprint on a profile that has none — and only on
    one that has none, so two PCs signing in at once cannot both make a
    lock: the one whose PATCH matched a row won."""
    status, rows = _rest("PATCH", "profiles", purpose="account",
                         query=f"user_id=eq.{urllib.parse.quote(uid)}&lock_id=eq.",
                         payload={"lock_id": lock_id}, prefer="return=representation")
    if status not in (200, 201, 204):
        raise AccountError(f"lock: the fingerprint was refused ({_server_said(status, rows)})")
    return isinstance(rows, list) and bool(rows)


def _ensure_lock(uid: str) -> bytes | None:
    """This PC's copy of the account's key. The account has no lock:
    this PC makes one (the first PC). This PC's key is the account's:
    done, believed for LOCK_TTL_S. Another PC made the lock: this PC's
    request to join is opened, or looked at again — None until it is
    approved or the recovery key is typed. Every outcome is a log line
    and status()["lock"]."""
    key = vault.key(uid)
    fp = vault.fingerprint(key) if key else ""
    st = _lock_state
    if key is not None and st.get("state") == "have" and st.get("lock_id") == fp \
            and time.monotonic() - st["at"] < LOCK_TTL_S:
        return key
    remote = _profile_lock_id(uid)
    if remote is None:
        ensure_profile(force=True)
        remote = _profile_lock_id(uid) or ""
    if not remote:
        made = key is None
        if made:
            key = vault.create(uid)
            fp = vault.fingerprint(key)
        if _claim_lock(uid, fp):
            log.info("lock: this PC %s the account's lock (%s)", "made" if made else "holds", fp)
            remote = fp
        else:
            remote = _profile_lock_id(uid) or ""
    if key is not None and remote == fp:
        first = st.get("state") != "have"
        _set_lock(state="have", lock_id=fp, pairing=None)
        if first:
            _recovery_known()
        return key
    if key is not None:
        log.warning("lock: this PC's key (%s) is not the account's (%s) — dropped; "
                    "the account's other PC must approve this one", fp, remote)
        vault.forget()
    return _request_pairing(uid, remote)


def _cursor_follows_lock(cursor: dict, key: bytes) -> None:
    """A lock the cursor has not seen — the first pass under one, or a
    key that changed: what was said and the keys sync again from the
    start (the rows on the server are sealed under the new key, the
    other PCs' lines on this PC came under the old one)."""
    fp = vault.fingerprint(key)
    if cursor.get("lock") == fp:
        return
    if cursor.get("lock"):
        log.info("lock: the account's key changed — what was said syncs again from the start")
    for name in ("history_pulled_at", "history_pushed_ts", "vault_pulled_at",
                 "vault_pushed", "vault_digest"):
        cursor.pop(name, None)
    sync.forget_remote()
    cursor["lock"] = fp
    sync.write_cursor(cursor)


def _request_pairing(uid: str, remote: str) -> bytes | None:
    """This PC's open request to join, made if there is none (or the
    last one expired), looked at if there is: approved means the key
    is taken out of what the other PC handed over and kept here."""
    st = _lock_state
    req = st.get("pairing")
    now = time.time()
    if req is not None and req["expires"] > now:
        status, rows = _rest("GET", "pairings", purpose="account",
                             query=f"select=handed,approved_at&id=eq.{req['id']}")
        if status != 200 or not isinstance(rows, list):
            raise AccountError(f"lock: {_server_said(status, rows)}")
        if not rows:
            # declined on the other PC, or swept: ask again
            log.info("lock: the request to join is gone — asking again")
            vault.drop(req["id"])
            req = None
        elif rows[0].get("handed"):
            aad = vault.AAD_PAIRING.format(uid=uid, pairing_id=req["id"])
            try:
                key = vault.take(req["id"], str(rows[0]["handed"]), aad)
            except vault.VaultError as e:
                log.warning("lock: what the other PC handed over did not open (%s) — asking again", e)
                _rest("DELETE", "pairings", purpose="account", query=f"id=eq.{req['id']}")
                vault.drop(req["id"])
                req = None
            else:
                fp = vault.fingerprint(key)
                if remote and fp != remote:
                    log.warning("lock: the key handed over (%s) is not the account's (%s) — asking again", fp, remote)
                    _rest("DELETE", "pairings", purpose="account", query=f"id=eq.{req['id']}")
                    req = None
                else:
                    vault.keep(uid, key)
                    _rest("DELETE", "pairings", purpose="account", query=f"id=eq.{req['id']}")
                    _set_lock(state="have", lock_id=fp, pairing=None)
                    log.info("lock: this PC was approved — the account's key is here (%s)", fp)
                    _recovery_known()
                    _wake.set()
                    return key
    if req is not None and req["expires"] <= now:
        vault.drop(req["id"])
        req = None
    if req is None:
        # this PC's earlier requests go first — the wizard's, say, whose
        # private half died with its process — so the other PC's card
        # never shows a code this PC no longer does
        try:
            _rest("DELETE", "pairings", purpose="account",
                  query=f"device_id=eq.{urllib.parse.quote(device_id())}")
        except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
            log.debug("lock: the old requests were not swept (%s)", e)
        pid = str(uuid.uuid4())
        code = vault.new_code()
        public = vault.applicant(pid)
        status, data = _rest("POST", "pairings", purpose="account",
                             payload={"id": pid, "user_id": uid, "device_id": device_id(),
                                      "device_name": device_name(),
                                      "code": code.replace("-", ""), "applicant": public},
                             prefer="return=minimal")
        if status not in (200, 201, 204):
            vault.drop(pid)
            raise AccountError(f"lock: the request to join was refused ({_server_said(status, data)})")
        req = {"id": pid, "code": code, "expires": now + PAIRING_TTL_S}
        log.info("lock: another PC holds the account's key — this PC asks to join (code %s)", code)
        _set_lock(state="waiting", lock_id=remote, pairing=req)
        _broadcast(event="pairing", extra={"id": pid, "code": code, "name": device_name()})
    else:
        _set_lock(state="waiting", lock_id=remote, pairing=req)
    return None


def _recovery_known() -> None:
    """Does the account hold a recovery wrap — one GET, remembered."""
    try:
        status, rows = _rest("GET", "recovery", purpose="account", query="select=created_at&limit=1")
        if status == 200 and isinstance(rows, list):
            with _lock:
                _lock_state["recovery"] = bool(rows)
    except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
        log.debug("lock: could not ask about the recovery key (%s)", e)


def poll_lock() -> dict:
    """The wizard's and the desk's question while this PC waits: look
    at the lock once, on the caller's thread (one or two requests), and
    say where it stands. Never raises."""
    try:
        if configured() and signed_in():
            with _sync_lock:
                key = _ensure_lock(_fresh()["user"]["id"])
                if key is not None:
                    cursor = sync.read_cursor()
                    _cursor_follows_lock(cursor, key)
    except (AccountError, net.EgressRefused, net.NetError, vault.VaultError, OSError) as e:
        with _lock:
            _lock_state["error"] = str(e)[:200]
        log.info("lock: %s", e)
    return lock_status()


def pending_pairings() -> list[dict]:
    """The other PCs of this account waiting to be approved by this one
    — read off the table, each new one handed to PAIRING_HOOKS once.
    Nothing without the key: a PC that does not hold it cannot hand it
    over."""
    if not (configured() and signed_in()):
        return []
    uid = _fresh()["user"]["id"]
    if vault.key(uid) is None:
        return []
    status, rows = _rest("GET", "pairings", purpose="account",
                         query="select=id,device_id,device_name,code,created_at,expires_at"
                               "&handed=is.null&order=created_at.asc")
    if status != 200 or not isinstance(rows, list):
        raise AccountError(f"lock: {_server_said(status, rows)}")
    now = datetime.now(timezone.utc)
    latest: dict[str, dict] = {}                 # one request per asking PC: its newest
    for r in rows:
        if str(r.get("device_id") or "") == device_id():
            continue
        until = sync._parse_iso(str(r.get("expires_at") or ""))
        if until is not None and until <= now:
            continue
        code = vault.normalize(str(r.get("code") or ""), vault.CODE_CHARS) or ""
        latest[str(r.get("device_id") or r.get("id"))] = {
            "id": str(r.get("id") or ""), "name": str(r.get("device_name") or "") or "another PC",
            "code": vault.pretty(code) if code else "", "created_at": str(r.get("created_at") or "")}
    out = list(latest.values())
    with _lock:
        was = [r["id"] for r in _lock_state.get("pending") or []]
        _lock_state["pending"] = out
        fresh = [r for r in out if r["id"] not in _seen_pairings]
        _seen_pairings.update(r["id"] for r in fresh)
    for r in fresh:
        for hook in list(PAIRING_HOOKS):
            try:
                hook(dict(r))
            except Exception:                                # noqa: BLE001
                log.debug("a pairing hook tripped", exc_info=True)
    if was and [r["id"] for r in out] != was:
        _run_lock_hooks()                    # a request went away (answered elsewhere, expired)
    return out


def approve_pairing(pairing_id: str) -> str:
    """[Approve] on this PC: the account's key wrapped to the asking
    PC's public key and written on its request — the one place the key
    crosses, and it crosses sealed. Returns the other PC's name."""
    uid = _fresh()["user"]["id"]
    key = vault.key(uid)
    if key is None:
        raise AccountError("this PC does not hold the account's key")
    pid = str(pairing_id or "").strip()
    status, rows = _rest("GET", "pairings", purpose="account",
                         query=f"select=applicant,device_name,handed,expires_at&id=eq.{urllib.parse.quote(pid)}")
    if status != 200 or not isinstance(rows, list):
        raise AccountError(f"lock: {_server_said(status, rows)}")
    if not rows:
        raise AccountError("that request is gone")
    row = rows[0]
    name = str(row.get("device_name") or "") or "another PC"
    until = sync._parse_iso(str(row.get("expires_at") or ""))
    if until is not None and until <= datetime.now(timezone.utc):
        raise AccountError(f"{name}'s request expired — it asks again on its own")
    if not row.get("handed"):
        handed = vault.hand_over(key, str(row.get("applicant") or ""),
                                 vault.AAD_PAIRING.format(uid=uid, pairing_id=pid))
        status, data = _rest("PATCH", "pairings", purpose="account",
                             query=f"id=eq.{urllib.parse.quote(pid)}",
                             payload={"handed": handed, "approved_at": _now_iso()},
                             prefer="return=minimal")
        if status not in (200, 204):
            raise AccountError(f"lock: the approval was refused ({_server_said(status, data)})")
    with _lock:
        _lock_state["pending"] = [r for r in _lock_state.get("pending") or [] if r["id"] != pid]
    _broadcast(event="paired", extra={"id": pid})
    log.info("lock: %s was approved on this PC", name)
    _run_lock_hooks()
    return name


def decline_pairing(pairing_id: str) -> None:
    """[Not now] on this PC: the request goes; the other PC asks again
    when it wants to."""
    pid = str(pairing_id or "").strip()
    _rest("DELETE", "pairings", purpose="account", query=f"id=eq.{urllib.parse.quote(pid)}")
    with _lock:
        _lock_state["pending"] = [r for r in _lock_state.get("pending") or [] if r["id"] != pid]
    log.info("lock: a request to join was declined on this PC")
    _run_lock_hooks()


def make_recovery() -> str:
    """A recovery key for the account — generated here, the account's
    key wrapped under it on the server (one row, replaced when made
    again), the string returned ONCE for the person to keep. Nothing of
    it is logged or written."""
    uid = _fresh()["user"]["id"]
    key = vault.key(uid)
    if key is None or _lock_state.get("state") != "have":
        raise AccountError("this PC does not hold the account's key yet")
    recovery = vault.new_recovery()
    wrapped = vault.wrap_recovery(key, recovery, vault.AAD_RECOVERY.format(uid=uid))
    status, data = _rest("POST", "recovery", purpose="account", query="on_conflict=user_id",
                         payload={"user_id": uid, "wrapped": wrapped, "created_at": _now_iso()},
                         prefer="resolution=merge-duplicates,return=minimal")
    if status not in (200, 201, 204):
        raise AccountError(f"the recovery key was refused ({_server_said(status, data)})")
    with _lock:
        _lock_state["recovery"] = True
    log.info("lock: a recovery key was made on this PC")
    return recovery


def recover(recovery: str) -> None:
    """The recovery key typed on a PC that waits: the account's key out
    of the wrap on the server, kept here, the open request dropped."""
    flat = vault.normalize(recovery, vault.RECOVERY_CHARS)
    if flat is None:
        raise AccountError("that is not a recovery key — 24 letters and digits in six groups")
    uid = _fresh()["user"]["id"]
    status, rows = _rest("GET", "recovery", purpose="account", query="select=wrapped&limit=1")
    if status != 200 or not isinstance(rows, list):
        raise AccountError(f"lock: {_server_said(status, rows)}")
    if not rows:
        raise AccountError("this account has no recovery key — approve this PC from your other one")
    try:
        key = vault.unwrap_recovery(str(rows[0].get("wrapped") or ""), flat,
                                    vault.AAD_RECOVERY.format(uid=uid))
    except vault.VaultError as e:
        raise AccountError(str(e)) from e
    fp = vault.fingerprint(key)
    remote = _profile_lock_id(uid) or ""
    if remote and fp != remote:
        raise AccountError("that recovery key belongs to an older lock of this account")
    req = _lock_state.get("pairing")
    if req:
        vault.drop(req["id"])
        try:
            _rest("DELETE", "pairings", purpose="account", query=f"id=eq.{req['id']}")
        except (AccountError, net.EgressRefused, net.NetError, OSError):
            pass
    vault.keep(uid, key)
    _set_lock(state="have", lock_id=fp, pairing=None, recovery=True)
    log.info("lock: the recovery key opened the account on this PC (%s)", fp)
    _wake.set()


def lock_status() -> dict:
    """What the Account card and the wizard draw: ``state`` is ``have``
    (this PC holds the key), ``waiting`` (it asked to join; ``code`` is
    what it shows), or empty (no account, or not looked at yet);
    ``pending`` the other PCs waiting on this one; ``recovery`` whether
    the account holds a recovery key (None until asked)."""
    st = _lock_state
    req = st.get("pairing")
    return {"state": str(st.get("state") or ""), "id": str(st.get("lock_id") or "")[:8],
            "code": str(req["code"]) if req else "",
            "pending": [dict(r) for r in (st.get("pending") or [])],
            "recovery": st.get("recovery"), "error": str(st.get("error") or "")}


# ------------------------------------------------------------- the status

def status() -> dict:
    """What the Account row draws (chapter 9 screen 16), in one dict."""
    who = user()
    out = {
        "configured": configured(),
        "signed_in": who is not None,
        "user_id": (who or {}).get("id", ""),
        "anonymous": bool((who or {}).get("is_anonymous", True)),
        "email": (who or {}).get("email", ""),
        "name": (who or {}).get("name", ""),
        "created_at": (who or {}).get("created_at", ""),
        "device_name": device_name(),
        "busy": _status.get("busy", ""),
        "last_error": _status.get("last_error", ""),
        "last_sync": _status.get("last_sync", ""),
        "live": bool(_live_state.get("on")),
        "lock": lock_status(),
        "waiting": queued(),
        "region": "Frankfurt (Supabase)",
        "required": bool(REQUIRED and configured()),
    }
    return out


configure()

__all__ = [
    "PROJECT_REF", "PUBLISHABLE_KEY", "configure", "configured", "base_url",
    "AccountError", "NotAllowed", "signed_in", "user", "device_id",
    "device_name", "ensure_profile", "sign_in_google", "sign_in_anonymous",
    "set_name", "sign_out", "delete_account", "sync_now", "drain_outbox", "queued",
    "start_worker", "nudge", "status", "forget_cache", "REPORT_COLUMNS",
    "REQUIRED", "SIGNED_OUT_HOOKS", "LIVE_ENABLED", "STORES", "stop_live",
    "PAIRING_HOOKS", "LOCK_HOOKS", "lock_status", "poll_lock", "pending_pairings",
    "approve_pairing", "decline_pairing", "make_recovery", "recover",
]
