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
#: How long the browser may take to come back with a code.
SIGNIN_TIMEOUT_S = 180
#: The worker: first sync this long after start, then every CADENCE.
FIRST_DELAY_S = 30.0
CADENCE_S = 15 * 60.0
#: A nudge (a dictation just ended) waits this long for the next one.
NUDGE_SETTLE_S = 5.0
#: The device row is refreshed at most this often.
DEVICE_SEEN_EVERY_S = 24 * 3600.0
TIMEOUT_S = 20.0


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
    session = {
        "access_token": str(data.get("access_token") or ""),
        "refresh_token": str(data.get("refresh_token") or ""),
        "expires_at": float(expires_at),
        "user": {
            "id": str(user.get("id") or ""),
            "is_anonymous": bool(user.get("is_anonymous", not user.get("email"))),
            "email": str(user.get("email") or ""),
            "created_at": str(user.get("created_at") or ""),
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
    """``{"id", "is_anonymous", "email", "created_at"}`` or None."""
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


def sign_out() -> None:
    """Sign out everywhere (the refresh tokens are revoked server-side),
    then forget the session and the cursors here. The local files stay."""
    session = _load_session()
    if session is not None and configured():
        try:
            _auth("logout", {}, query="scope=global", bearer=True)
        except Exception as e:                               # noqa: BLE001
            log.info("account: the sign-out did not reach the server (%s) — "
                     "signed out here", e)
    _clear_session()
    sync.forget_all()
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


def _sync_settings(cursor: dict) -> str:
    """Pull or push the settings blob (last writer wins). Returns one
    word for the log: pulled, pushed, same."""
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
    if local_changed or not remote:
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


def _sync_vocab(cursor: dict, vocab) -> str:
    """Pull the other PCs' rows into the live vocabulary, push what
    changed here. ``vocab`` is the app's Vocab (or None to skip)."""
    if vocab is None:
        return "skipped"
    since = str(cursor.get("vocab_pulled_at") or "")
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
        cursor["vocab_pulled_at"] = str(rows[-1].get("updated_at") or since)
    with vocab._write_lock:
        corrections = [dict(c) for c in vocab.corrections]
    to_push = sync.vocab_changed(sync.vocab_rows(corrections, snapshot), snapshot)
    pushed = 0
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
    cursor["vocab_snapshot"] = sync.vocab_snapshot(corrections)
    return f"pulled {pulled}, pushed {pushed}"


def _sync_history(cursor: dict) -> str:
    """This PC's events up, the other PCs' events down (D31)."""
    import history
    mine = device_id()
    uid = _fresh()["user"]["id"]
    # down
    names: dict[str, str] = {}
    status, rows = _rest("GET", "devices", purpose="history", query="select=id,name")
    if status == 200 and isinstance(rows, list):
        names = {str(r.get("id")): str(r.get("name") or "") for r in rows}
    pulled = 0
    for _round in range(10):
        since = str(cursor.get("history_pulled_at") or "")
        query = ("select=device_id,ts,kind,text,raw,engine,seconds,updated_at"
                 "&order=updated_at.asc&limit=500&device_id=neq." + mine)
        if since:
            query += "&updated_at=gt." + urllib.parse.quote(since)
        status, rows = _rest("GET", "history", purpose="history", query=query)
        if status != 200 or not isinstance(rows, list):
            raise AccountError(f"history: {_server_said(status, rows)}")
        if not rows:
            break
        lines = [sync.remote_line(r, names.get(str(r.get("device_id")), ""))
                 for r in rows]
        pulled += sync.append_remote_history(lines)
        cursor["history_pulled_at"] = str(rows[-1].get("updated_at") or since)
        sync.write_cursor(cursor)
        if len(rows) < 500:
            break
    # up
    events = history.all_events()
    pushed = 0
    for _round in range(10):
        batch = sync.history_rows(events, mine, cursor.get("history_pushed_ts"))
        if not batch:
            break
        for row in batch:
            row["user_id"] = uid
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
    return f"pulled {pulled}, pushed {pushed}"


def sync_now(vocab=None, reason: str = "") -> dict:
    """One pass over everything the gates allow. Never raises: each
    store's outcome (or its error) is a word in the returned dict and
    a line in the log; ``last_sync``/``last_error`` feed the Account
    row. Nothing happens without a session or with every gate shut."""
    out: dict[str, str] = {}
    if not configured() or not signed_in():
        return out
    words = privacy.allowed("settings_sync")
    said = privacy.allowed("history_sync")
    if not words and not said:
        return out
    with _lock:
        _status["busy"] = "syncing"
    try:
        cursor = sync.read_cursor()
        try:
            ensure_profile()
        except (AccountError, net.EgressRefused, net.NetError) as e:
            out["profile"] = f"error: {e}"
        stores = []
        if words:
            stores += [("settings", lambda: _sync_settings(cursor)),
                       ("vocab", lambda: _sync_vocab(cursor, vocab))]
        if said:
            stores.append(("history", lambda: _sync_history(cursor)))
        for name, fn in stores:
            try:
                out[name] = fn()
            except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
                out[name] = f"error: {e}"
            if not signed_in():
                # the account went away under us (a second 401): the
                # cursors were dropped with it and must not come back
                break
            sync.write_cursor(cursor)
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


def start_worker(vocab=None, on_sent=None) -> threading.Thread | None:
    """The app's background pass: FIRST_DELAY_S after start, then every
    CADENCE_S, and NUDGE_SETTLE_S after a nudge (a dictation ended, a
    consent opened, the person pressed Sync now). Does nothing without
    a configured project."""
    global _worker
    if not configured() or (_worker is not None and _worker.is_alive()):
        return _worker

    def loop() -> None:
        _wake.wait(FIRST_DELAY_S)
        while True:
            _wake.clear()
            try:
                if signed_in():
                    sync_now(vocab, reason="worker")
                    drain_outbox(on_sent)
            except Exception:                                # noqa: BLE001
                log.debug("account worker tripped", exc_info=True)
            if _wake.wait(CADENCE_S):
                time.sleep(NUDGE_SETTLE_S)

    _worker = threading.Thread(target=loop, daemon=True, name="account-sync")
    _worker.start()
    return _worker


def nudge() -> None:
    """Something changed (a dictation, a learned word): sync soon."""
    _wake.set()


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
        "created_at": (who or {}).get("created_at", ""),
        "device_name": device_name(),
        "busy": _status.get("busy", ""),
        "last_error": _status.get("last_error", ""),
        "last_sync": _status.get("last_sync", ""),
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
    "sign_out", "delete_account", "sync_now", "drain_outbox", "queued",
    "start_worker", "nudge", "status", "forget_cache", "REPORT_COLUMNS",
    "REQUIRED", "SIGNED_OUT_HOOKS",
]
