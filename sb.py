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

The account pass (2026-11-06, PHONE_LINK_PLAN.md stage 1): a phone
becomes a device of the account, and a person with both syncs off has to
be reachable all the same. So what needs only the ``account`` gate runs
on its own, ahead of the syncs (``account_pass``): the profile, the
lock, the requests to join, the devices' rows; no store moves in it. The
socket is held under the purpose ``account`` by every signed-in copy,
whatever its syncs say, and the events that are no store's go out under
that purpose too. A device of the account is a row of ``devices`` with a
sealed ``link`` (``devices``, ``write_link``); ``forget_device`` ends one,
and the ``forgotten`` row and a local list that never shrinks keep it out.

The lock (the owner, 2026-09-21: the cloud keys and the text of what
he said locked before they leave, so the same account opens them on
every PC of his and the server cannot): vault.py holds the key and does
the sealing; this module only moves what it produces. The account pass
and every sync start with ``_ensure_lock``: the first PC of an account
makes the key and writes its fingerprint on the profile; a PC without
the key asks to join (``_request_pairing`` — a row in ``pairings`` with
its public key; the ten-character code it shows is computed from that
key and the lock it read) and waits for a device that has it to approve
(``approve_pairing`` — the code computed again from the key it wraps to
and the lock this device holds, the key wrapped to that public key,
never in the clear), and for its own person to say the two codes are the
same (``same_code``: it opens nothing before that, or a dishonest server
could write the answer itself, under a lock it named), or for the person
to type the recovery key
(``recover``). ``history.cipher`` and the ``vault`` rows (the cloud
keys, one per name) are sealed under the account key and opened only
here; ``ts``, ``kind`` and ``engine`` stay readable for the ordering.
Until the key is here those two stores say "waiting for the lock" and
their cursors do not move; the words and settings sync as before.
A PC that holds a key never gives it up because the profile names
another lock (2026-09-23, the audit's A15): the lock is "changed", those
two stores say "paused — the lock changed" in both directions, and Home
asks the person whether it was him (``lock_answer``, ``restore_lock``).

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

from config import LAST_ACCOUNT, SOMEBODY
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
#: ...and this often while the live socket has been joined since the last
#: whole pass: every change on another device then came as a broadcast and
#: the pass only confirms it. Counted 2026-11-09/10 in his network.log: an
#: idle hour was 36 rows to the account server, 4 passes of 8 (account 4,
#: sync 3, history 1) and the socket's hourly reconnect, 4. A socket that
#: dropped and came back may have missed a broadcast in the gap, so the
#: pace is CADENCE_S again until the next whole pass (``_pace``).
CADENCE_LIVE_S = 60 * 60.0
#: The worker sleeps in steps this long, so a socket that drops in the
#: middle of an hour's wait puts it back on CADENCE_S within a minute. No
#: request: a look at two numbers.
PACE_CHECK_S = 60.0
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
#: Called with the account's key (bytes) at the end of every account pass
#: and on a ``changed: devices`` broadcast, once the lock says ``have``:
#: phone.py reads the devices' rows and opens them there. The worker and
#: the live thread both run these, so a hook does not wait on a person.
ACCOUNT_HOOKS: list = []
#: Called (no arguments) when this PC found itself on the account's
#: forgotten list, right after its key moved aside and its device id
#: changed: whatever named the old device goes now (phone.py's
#: certificate: the list never lets the old one back). A forgotten PC
#: may still hold a session, so SIGNED_OUT_HOOKS do not cover this.
FORGOTTEN_HOOKS: list = []


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
    # the record before the session: a crash between the two leaves a record
    # and no session, and the next sign-in of anybody reads that correctly.
    # One lock over both: a pass in flight must see the old session with
    # the old cursor or the new one with none (``_write_cursor``)
    with _lock:
        try:
            _take_over(session["user"]["id"])
        except Exception as e:                               # noqa: BLE001
            log.warning("account: the stores did not change hands at the sign-in (%s) — "
                        "the first sync does it", e)
        secretstore.set(SESSION_NAME, json.dumps(session))
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
            # "Refresh Token Not Found" is the session deleted on the
            # server — Sign out of every PC, or the account deleted.
            said = _server_said(status, data if isinstance(data, bytes) else b"")
            _account_gone(f"the session could not be refreshed ({said})",
                          words=GONE_ELSEWHERE if "not found" in said.lower() else GONE_WORDS)
        raise AccountError(f"the session could not be refreshed ({status})")
    return _store_session(data)


def _fresh(margin: float | None = None) -> dict:
    """The session, refreshed first when its hour is (nearly) over — when
    no more than ``margin`` seconds of it are left, REFRESH_MARGIN_S unless
    said (the live channel asks a heartbeat earlier)."""
    with _lock:
        session = _load_session()
        if session is None:
            raise AccountError("not signed in")
        if float(session.get("expires_at") or 0) - time.time() <= (
                REFRESH_MARGIN_S if margin is None else margin):
            session = _refresh()
        return session


#: What the sign-in card says under its button when this PC's session
#: ended somewhere else. Plain words; the server's own reason goes to
#: app.log. Until 2026-10-03 the card showed the server's line itself —
#: "the session could not be refreshed (HTTP 400: Invalid Refresh Token:
#: Refresh Token Not Found)" — and it said nothing to a person.
GONE_ELSEWHERE = "Signed out from another device."
GONE_WORDS = "This PC was signed out."
#: Sign out of every PC when it did not happen. Nothing is signed out then,
#: this PC included: it is the one that can try again.
SAY_YES_FIRST = ("Your other devices are still signed in. Say yes to the account's new "
                 "words on Home first, then press Sign out of every PC again.")
NO_ROAD_THERE = ("Your other devices are still signed in, because this PC could not reach "
                 "your account. Try Sign out of every PC again when it is online.")
#: ... and when this PC's own session turned out to be dead on the way, which
#: was the one road to the others: this PC is signed out, they may not be.
SESSION_WENT = ("This PC's session had already ended, so your other devices may still be "
                "signed in. Sign in again, then press Sign out of every PC.")
#: A state.json that will not read (``_state``), as a person reads it: every
#: sync stops until it does, and a start replaces a damaged one
#: (migrations.apply, config.state_to_write).
STATE_WORDS = ("A file DeskIT keeps on this PC will not read, so your account is paused here. "
               "Restarting DeskIT puts that right.")
#: Forget, when a session of that device is left (``forget_device``).
OLDER_COPY_WORDS = ("That device is off your list but still signed in: it is an older copy of "
                    "DeskIT, or one that has not said yes yet. To end it, press Sign out of "
                    "every PC.")


def _account_gone(why: str, *, words: str = GONE_WORDS) -> None:
    """A second 401, or a dead refresh token: drop the session and the
    cursors; the next sign-in starts clean. Never a dialog: ``why`` goes
    to the log, ``words`` to the sign-in card."""
    log.warning("account: %s — signed out on this PC", why)
    _keep_what_went_up()
    _clear_session()
    sync.forget_all()
    _forget_lock_state()
    _status["last_error"] = words
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

def _state() -> dict:
    """state.json, or AccountError: {} would say nothing was ever written,
    and a device id, a floor or a record of whose the stores are would then
    be gone for this pass on the strength of one bad read
    (config.read_state_strict)."""
    import config
    try:
        return config.read_state_strict(paths.STATE_FILE)
    except config.StateUnreadable as e:
        log.info("account: %s", e)
        raise AccountError(STATE_WORDS) from e


def _state_mended() -> dict:
    """state.json for ``_take_over``, which is about to write it. A damaged
    file is replaced here (a save does it, config.state_to_write), by one
    that says somebody was here. Left for the next save it would fail the
    door at the sign-in of the very person it matters for, and that person's
    session would then read as the one that was here all along: what another
    account queued would go out as theirs. One that would not open raises."""
    import config
    try:
        return _state()
    except AccountError:
        try:
            config.save({})
        except config.StateUnreadable as e:
            raise AccountError(STATE_WORDS) from e
        return _state()


def _per_account(name: str) -> dict:
    """One of the maps state.json keeps by the account's uid."""
    data = _state().get(name)
    return dict(data) if isinstance(data, dict) else {}


#: Where each account's history stood when it signed out, and under which
#: lock (``_keep_what_went_up``).
PUSHED = "account.history_pushed"
#: What each other account has to leave where it is (``_take_over``;
#: LAST_ACCOUNT, beside it, says whose the stores are). SOMEBODY is what
#: that says with no account to name: not an id, and not nobody.
HELD_BACK = "sync.held_back"
#: What ``vault.digest_keys`` hashes under at the door. No account's key,
#: because the new account's may not be on this PC yet; these are hashes of
#: long random keys, only ever compared with each other.
KEYS_LEFT = b"what another account left in this slot"


def _end_of_log() -> str:
    """A stamp nothing said so far is past: the newest row the log would
    make or this moment, whichever is later. The moment because what was
    asked before it is stamped with the asking once the answer lands
    (a translation's ``-IN`` and ``-OUT``), and because a log that will not
    read must not leave the floor where it was."""
    import history
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    try:
        return _later(now, sync.history_floor(history.all_events())) or now
    except (OSError, ValueError) as e:
        log.info("account: the log's end was not read (%s)", e)
        return now


def _words_here() -> list[dict]:
    """vocab.json as it stands, or its last good copy: from a file that will
    not read that is what the app loads (Vocab.load), and would go on to send."""
    import vocab
    for path in (paths.VOCAB_FILE, paths.VOCAB_FILE.with_name(paths.VOCAB_FILE.name + ".bak")):
        try:
            found = vocab._read_store(path).get("corrections")
        except (OSError, ValueError):
            continue
        return [c for c in found or [] if isinstance(c, dict)]
    return []


def _what_is_here() -> dict:
    """What would go up as the new account's, as marks (sync.py)."""
    import config
    digests, present = vault.digest_keys(KEYS_LEFT)
    return {"vocab": sorted({sync.word_mark(c) for c in _words_here()}),
            "settings": sync.setting_marks(config.read_settings(paths.SETTINGS_FILE)),
            "keys": {name: digests[name] for name in present}}


def _take_over(uid: str) -> None:
    """One account's stores are never another's. transcripts.log, vocab.json,
    settings.toml and the cloud keys' slot are one of each on a PC and name
    no owner, and every sign-out takes the cursors, so to a second account
    all of it was new: its first sync sealed everything the first had said
    into its own account, with the first's words, its names (``vocab.terms``)
    and its cloud keys, and the first, back again, took the second's the same
    way. A family PC, or one person with a work account and a private one.

    This is the line between them, at every sign-in and at the head of every
    sync. The first account a PC ever has takes what is here, because it is
    that person's, said before they signed in. The same account back loses
    nothing. A different one starts past everything: its history floor goes
    to the end of the log, and what the other stores hold is marked, to stay
    on this PC until the person changes it or the account turns out to hold
    it too (``_sync_settings``, ``_sync_vocab``, ``_sync_vault``). What was
    said and learned stays readable here, on the Said page and in dictation:
    this is only about what leaves. The cost, in the direction a mistake
    should fall: what an account said offline and had not pushed when
    another took over stays on this PC, and whoever moves to a new account
    takes nothing along with them. A report queued by the account that left
    waits for it (``_reports_wait``).

    All of it goes down in one write, in state.json, where neither a sign-out
    nor ``sync.forget_all`` reaches it, and last: what can raise is worked out
    before anything moves, and a crash after the cursors and the reports went
    finds the same door next time. A damaged state.json is replaced on the
    way in, and reads as somebody else's (``_state_mended``). Raises when it
    would not open, because {} would look like a first account, and
    ``sync_now`` and ``drain_outbox`` then move nothing."""
    if not uid:
        return
    import config
    with _lock:
        state = _state_mended()
        last = str(state.get(LAST_ACCOUNT) or "")
        if last == uid:
            return
        here = ((_load_session() or {}).get("user") or {}).get("id")
        before = last or str(here or "") or (SOMEBODY if state.get("account.device_id") else "")
        updates: dict = {LAST_ACCOUNT: uid}
        if before and before != uid:
            log.info("account: another account on this PC — what is here stays here")
            floors = _per_account("account.history_floor")
            updates["account.history_floor"] = {**floors, uid: _later(floors.get(uid), _end_of_log())}
            updates[HELD_BACK] = {**_per_account(HELD_BACK), uid: _what_is_here()}
            sync.forget_all()
            # a record lost with its file names nobody to wait for, and with
            # this session still here what is queued is its own: moved under
            # that word nothing would ever bring it back
            if not (before == SOMEBODY and here == uid):
                _reports_wait(before, uid)
        config.save(updates)


def _reports_folder(uid: str):
    """Where ``uid``'s reports wait. By a mark and not by the id: the id is
    the server's word, and this is a path."""
    return paths.OUTBOX_DIR / paths.OUTBOX_WAITING / sync.mark(uid)


def _move_reports(source, target) -> None:
    try:
        entries = [e for e in source.iterdir() if e.name != paths.OUTBOX_WAITING]
    except OSError:
        return                                               # nothing waits
    for entry in entries:
        try:
            target.mkdir(parents=True, exist_ok=True)
            os.replace(entry, target / entry.name)
        except OSError as e:
            log.warning("report: %s did not move (%s)", entry.name, e)


def _reports_wait(old: str, new: str) -> None:
    """A report goes out under whoever is signed in when the outbox drains
    (``_send_report``), and it carries that person's last dictation and a
    picture of their screen: one queued offline by one account went out as
    another's, whose session can read the row. So the outbox moves aside
    with the account that left, and what the new account left comes back,
    at the very paths its files were named by. A report that will not move
    is a log line. ``queued()`` and ``drain_outbox`` read the top of the
    outbox alone, so what waits is neither counted nor sent, and
    ``problems.sync_outbox`` knows the folder, so it does not read as sent."""
    _move_reports(paths.OUTBOX_DIR, _reports_folder(old))
    mine = _reports_folder(new)
    _move_reports(mine, paths.OUTBOX_DIR)
    for folder in (mine, paths.OUTBOX_DIR / paths.OUTBOX_WAITING):
        try:
            folder.rmdir()
        except OSError:
            pass                       # another account's are still in it


def _keep_what_went_up() -> None:
    """Where this PC's history stands on the account, kept past a sign-out.
    ``sync.forget_all`` takes the cursors, so the same account back pushed
    every line again, the server's trigger stamped each row new, and every
    other device appended them all a second time: one sign-out doubled this
    PC's lines on the others, and Sign out of every PC every pair of copies.
    Kept with the lock it went up under and not as a floor, because a floor
    says what must never go up, and a lock that changed meanwhile means
    these rows must, under the new key (``_cursor_follows_lock``). Never
    stops a sign-out."""
    try:
        who = user()
        cursor = sync.read_cursor()
        pushed = cursor.get("history_pushed_ts")
        if who and pushed:
            import config
            config.save({PUSHED: {**_per_account(PUSHED),
                                  who["id"]: {"ts": pushed, "lock": str(cursor.get("lock") or "")}}})
    except Exception as e:                                   # noqa: BLE001
        log.info("account: where the history stands was not kept (%s)", e)


def _write_cursor(cursor: dict, uid: str) -> None:
    """The cursor back on disk, only while the account it was read under is
    still the one here. A pass in flight across a sign-in would otherwise
    put the last account's cursor back after ``_take_over`` wiped it, and
    the new account's first pass would take it for its own. Under the lock
    the door and the session's write share."""
    with _lock:
        if (user() or {}).get("id") == uid:
            sync.write_cursor(cursor)


def _held_back(uid: str, store: str):
    """What ``uid`` leaves where it is in one store: marks, or for the
    cloud keys {name: hash}. Empty for an account that took nothing over."""
    record = _per_account(HELD_BACK).get(uid)
    return (record.get(store) if isinstance(record, dict) else None) or ()


def _let_go(uid: str, store: str, marks) -> None:
    """These turned out to be the account's own: from here on they sync."""
    import config
    held = _per_account(HELD_BACK)
    record = dict(held.get(uid) or {})
    left = [m for m in record.get(store) or () if m not in marks]
    if left:
        record[store] = left
    else:
        record.pop(store, None)
    if record:
        held[uid] = record
    else:
        held.pop(uid, None)
    config.save({HELD_BACK: held or None})


def _keys_left_here(uid: str) -> set[str]:
    """The cloud keys in this slot that are still what was here when this
    account took over. A key pasted since hashes to something else and is
    this account's, and so is one the account itself sent down."""
    held = dict(_held_back(uid, "keys"))
    if not held:
        return set()
    digests, present = vault.digest_keys(KEYS_LEFT)
    return {name for name in present if held.get(name) == digests[name]}


def device_id() -> str:
    """This PC's id in the account signed in here: one per account, minted
    once into state.json and kept, so going from A to B and back to A finds
    A's own row again. ``devices.id`` is unique across accounts, so under
    another account the old id would be refused, and a phone would find no
    PC. A new one comes only when the account forgot the old (``_leave``).
    Never minted over a state file that will not read, which may hold the
    real one: AccountError then (``_state``), and the next pass looks again."""
    import config
    session = _load_session()
    uid = str(((session or {}).get("user") or {}).get("id") or "")
    with _lock:
        state = _state()
        ids = state.get("account.device_ids")
        ids = dict(ids) if isinstance(ids, dict) else {}
        current = str(state.get("account.device_id") or "")
        ident = str(ids.get(uid) or "") if uid else current
        if not ident and current not in ids.values():
            ident = current                  # the id this copy already had
        if ident and ident == current and (not uid or ids.get(uid) == ident):
            return ident
        if not ident:
            ident = str(uuid.uuid4())
        updates: dict = {"account.device_id": ident}
        if uid:
            updates["account.device_ids"] = {**ids, uid: ident}
        if ident != current:
            updates.update({"account.device_seen_at": None, "account.device_session": None})
        config.save(updates)
        return ident


def _new_device_id(uid: str, **also) -> str:
    """Another id for this PC under ``uid``, in place of the one it had."""
    import config
    ident = str(uuid.uuid4())
    config.save({"account.device_id": ident,
                 "account.device_ids": {**_per_account("account.device_ids"), uid: ident},
                 "account.device_seen_at": None, "account.device_session": None, **also})
    return ident


def device_name() -> str:
    import config
    state = config.read_state(paths.STATE_FILE)
    name = str(state.get("account.device_name") or "").strip()
    if not name:
        name = (platform.node() or "this PC").strip()
    return name[:40]


def copy_name() -> str:
    """Which DeskIT this is, in a person's words: the Store's, the
    website's, winget's, or the owner's checkout."""
    if paths.DEVELOPER:
        return "DeskIT Dev"
    if paths.PACKAGED or paths.CHANNEL == "store":
        return "DeskIT App (Store)"
    if paths.CHANNEL == "winget":
        return "DeskIT (winget)"
    return "DeskIT (website)"


def request_name() -> str:
    """The name a request to join carries: the PC's, and which copy on
    it is asking. Two copies on one PC were both "YOAV" on the other's
    Home (the Store walk, 2026-10-03: the Store copy asking the Dev, side
    by side); "YOAV · DeskIT App (Store)" says which one to expect. The
    column holds 40 characters, so the PC's name gives way, not the copy."""
    copy = copy_name()
    room = 40 - len(copy) - 3
    return f"{device_name()[:room].rstrip()} · {copy}"


#: The marks that move text around them. A request's name comes from the
#: asking device and is drawn beside the code a person compares.
_BIDI_MARKS = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")


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


def _session_id(session: dict) -> str:
    """The ``session_id`` claim of this copy's access token (0006): the
    session Forget ends. "" for a token that carries none. Read and never
    checked: the server checks a token, this only says what goes on the
    row, and the id opens nothing by itself."""
    try:
        body = str(session.get("access_token") or "").split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (IndexError, ValueError, TypeError):
        return ""
    sid = str(claims.get("session_id") or "") if isinstance(claims, dict) else ""
    return sid if _UUID.fullmatch(sid) else ""


def ensure_profile(force: bool = False) -> None:
    """The profile row and this PC's device row, upserted after a
    sign-in and then at most once a day (8.2), and as soon as the session
    under the row is another one: its ``session_id`` is what Forget ends
    (migration 0007). A PC on the account's forgotten list leaves before
    it writes (``_forgotten_pass``), so what is written is a new device's
    row and the forgotten one stays gone. An id whose row is another
    account's (row-level security, 42501: a copy from before ``device_id``
    kept one per account, or a state file put back from elsewhere) gives
    way to a new one, once, or a phone would find no PC."""
    session = _fresh()
    uid = session["user"]["id"]
    import config
    device_id()                      # under this account, before anything reads the state
    state = config.read_state(paths.STATE_FILE)
    seen = float(state.get("account.device_seen_at") or 0)
    sid = _session_id(session)
    moved = bool(sid) and sid != state.get("account.device_session")
    if not force and not moved and time.time() - seen < DEVICE_SEEN_EVERY_S:
        return
    status, data = _rest("POST", "profiles", purpose="account",
                         query="on_conflict=user_id",
                         payload={"user_id": uid, "app_version_last_seen": _app_version(),
                                  "is_anonymous": bool(session["user"]["is_anonymous"])},
                         prefer="resolution=merge-duplicates,return=minimal")
    if status not in (200, 201, 204):
        raise AccountError(f"the profile row was refused ({_server_said(status, data)})")
    _forgotten_pass(uid)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row = {"id": device_id(), "user_id": uid, "name": device_name(),
           "platform": _platform(), "app_version": _app_version(), "tier": _tier(),
           "last_seen": now}
    if sid:
        row["session_id"] = sid
    status, data = _rest("POST", "devices", purpose="account", query="on_conflict=id",
                         payload=row, prefer="resolution=merge-duplicates,return=minimal")
    if status == 403 and isinstance(data, bytes) and b"42501" in data:
        log.info("account: this PC's device id belongs to another account — it takes a new one")
        row["id"] = _new_device_id(uid)
        status, data = _rest("POST", "devices", purpose="account", query="on_conflict=id",
                             payload=row, prefer="resolution=merge-duplicates,return=minimal")
    if status not in (200, 201, 204):
        raise AccountError(f"the device row was refused ({_server_said(status, data)})")
    config.save({"account.device_seen_at": time.time(), "account.device_session": sid or None})


# ---------------------------------------------------------------- sign-in

def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(48)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# THE PAGE THE BROWSER LANDS ON. It is the last thing the person sees
# before the app, and until 2026-09-19 it was a bare white page in Hebrew
# — "you can close this tab" — over which he had to go and find the
# window himself. It is the app's own surface now: B+ since 2026-10-23,
# LAMPLIGHT before (skin\palette.py — ground #0B0D19, card #1A1E35, text
# #EFEDF7, dim #C0C3D8, the iris #A597FF only as the focus ring), the
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
    "body{background:#0b0d19 radial-gradient(60% 45% at 50% 0%,#1a1b30 0%,#0b0d19 70%);"
    "color:#efedf7;font-family:system-ui,'Segoe UI',Rubik,Arial,sans-serif;"
    "display:flex;align-items:center;justify-content:center;box-sizing:border-box;"
    "padding:24px 16px;-webkit-font-smoothing:antialiased}"
    "main{background:#1a1e35;border:1px solid #30365a;border-radius:22px;"
    "padding:40px 36px 34px;max-width:420px;width:100%;text-align:center;"
    "box-shadow:0 24px 60px rgba(0,0,0,.45)}"
    ".mark{width:72px;height:72px;display:block;margin:0 auto 22px;border-radius:17px}"
    "h1{font-size:22px;font-weight:600;line-height:1.3;margin:0 0 10px;letter-spacing:-.01em}"
    "p{color:#c0c3d8;font-size:15px;line-height:1.55;margin:0 0 26px}"
    "p.why{color:#efedf7;background:#121527;border:1px solid #30365a;border-radius:14px;"
    "padding:10px 14px;font-size:14px;word-break:break-word}"
    "button{font:inherit;font-size:15px;font-weight:500;color:#efedf7;background:#242944;"
    "border:1px solid #454c78;border-radius:999px;padding:11px 26px;cursor:pointer}"
    "button:hover{background:#2a3050;border-color:#525a88}"
    "button:active{background:#161a2e}"
    "button:focus-visible{outline:2px solid #a597ff;outline-offset:2px}"
    "small{display:block;margin-top:20px;color:#a4a9c2;font-size:12px}"
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


def _clear_other_links() -> None:
    """Sign out of every PC, the part about the doors: every other
    device's ``link`` goes first. A door checks a certificate and not a
    session, so ending the sessions alone would leave a phone's door open,
    and this is Home's answer to a stranger. A device that signs in again
    writes its row back, unless it is on the forgotten list. Never stops
    the sign-out: a failure here is a log line, and the sessions end
    whatever it said."""
    try:
        status, data = _rest("PATCH", "devices", purpose="account",
                             query=f"id=neq.{urllib.parse.quote(device_id())}",
                             payload={"link": None}, prefer="return=minimal")
        if status not in (200, 204):
            log.info("account: the other devices' rows were not cleared (%s)",
                     _server_said(status, data))
    except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
        log.info("account: the other devices' rows were not cleared (%s)", e)


def _end_the_others() -> None:
    """Sign out of every PC, the part about the OTHER PCs: their rows lose
    their ``link`` (``_clear_other_links``), their sessions
    end on the server (scope=others — this one is kept for one more
    call), then one broadcast on the account's channel, ``signed_out``,
    makes every copy that is listening ask the server about its own
    session at once (``_live_once``); a refused refresh is
    ``_account_gone``, the lock, within the second. Without it a copy
    went on for the rest of its access token's hour: measured 2026-10-03,
    the Dev worked 58 minutes past "Sign out of every PC" and approved
    two requests to join. The order is the point: the broadcast goes
    after the sessions are gone, so no copy can refresh in between, and
    under this PC's own session, which the server's check (migration
    0006) still lets through. A copy that is not listening — offline,
    or not ours — meets that check on its next request."""
    _fresh()
    _clear_other_links()
    status, data = _auth("logout", {}, query="scope=others", bearer=True)
    if status not in (200, 204):
        raise AccountError(_server_said(status, data if isinstance(data, bytes) else b""))
    _broadcast(event="signed_out")


def sign_out(everywhere: bool = True) -> None:
    """Sign out everywhere (the refresh tokens are revoked server-side),
    then forget the session and the cursors here. The local files stay.
    ``everywhere=False`` is this PC's session only, the person's other
    PCs keep theirs: the wizard's "Not you?" and, since the Store walk of
    2026-10-03, the desk's own Sign out. The desk's Sign out of every PC
    is the one caller of the default. That one raises AccountError, with
    the words for the person and nothing signed out, when it could not end
    the others: it is what the changed lock's "It wasn't me" points to, and
    saying it had done so would leave a stranger in. Nothing is signed out
    then, unless this PC's session was dead already, which SESSION_WENT
    says. This PC's own sign-out goes through whatever the server said,
    because the session is forgotten here either way."""
    session = _load_session()
    if session is not None and configured():
        # every PC: the others first and told (_end_the_others), then
        # this one; if that road fails, the old one — all at once
        scope = "local"
        if everywhere:
            if not privacy.allowed("account"):
                raise AccountError(NO_ROAD_THERE if net.offline else SAY_YES_FIRST)
            try:
                _end_the_others()
            except Exception as e:                           # noqa: BLE001
                log.info("account: the other PCs were not signed out one by one (%s) — "
                         "all at once instead", e)
                scope = "global"
        try:
            # a session that turned out dead on the way has already gone
            if signed_in():
                status, _said = _auth("logout", {}, query=f"scope={scope}", bearer=True)
                if scope == "global" and status not in (200, 204):
                    raise AccountError(f"HTTP {status}")
        except Exception as e:                               # noqa: BLE001
            if scope == "global":
                log.info("account: every PC was not signed out (%s)", e)
                raise AccountError(NO_ROAD_THERE) from e
            log.info("account: the sign-out did not reach the server (%s) — "
                     "signed out here", e)
        if scope == "global" and not signed_in():
            # _account_gone did the rest of this function on the way, and
            # nothing asked the server to end anybody
            log.info("account: this PC's session ended first — every PC was not signed out")
            raise AccountError(SESSION_WENT)
    _keep_what_went_up()
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
    account keys in state.json, the cursors and the outbox (8.5). The
    files stay, so LAST_ACCOUNT stays too, as a word and no longer an id:
    what this account left here must not become the next account's.

    The purge has to be WHOLE before ``delete_me`` (audit A16, 2026-11-09):
    once the auth user is gone nobody can reach reports/<uid>/ any more —
    the delete policy is the uid's own and no sweep exists — and until then
    a failed purge was a log line while the desk said "nothing of yours is
    left on the server". So a purge that failed, or a folder that still
    lists something after it, stops here with ``STORAGE_LEFT_WORDS``: the
    account stays, signed in, and the same button tries again."""
    session = _fresh()
    uid = session["user"]["id"]
    try:
        _purge_storage(uid)
        left = _stored_files(uid)
    except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
        log.info("account: the storage purge before delete_me failed (%s)", e)
        raise AccountError(STORAGE_LEFT_WORDS.format(n="some")) from e
    if left:
        log.info("account: %d report file(s) still listed after the purge", len(left))
        raise AccountError(STORAGE_LEFT_WORDS.format(n=len(left)))
    status, data = _rest("POST", "rpc/delete_me", purpose="account", payload={})
    if status not in (200, 204):
        raise AccountError(f"the server refused the deletion ({_server_said(status, data)})")
    _clear_session()
    sync.forget_all()
    vault.forget(uid)             # the key and every key of this account set aside
    _forget_lock_state()
    try:
        listed = _forgotten_file(uid)
        listed.unlink(missing_ok=True)
        for kept in listed.parent.glob(f"{listed.name}.broken-*"):
            kept.unlink(missing_ok=True)
    except OSError as e:
        log.info("account: the list of forgotten devices stayed (%s)", e)
    import config
    try:
        maps = {name: {k: v for k, v in _per_account(name).items() if k != uid} or None
                for name in ("account.device_ids", "account.past_devices", "account.history_floor",
                             PUSHED, HELD_BACK)}
    except AccountError:
        maps = {}                 # the account is gone; the save sets the file aside
    config.save({"account.device_id": None, "account.device_seen_at": None,
                 "account.device_name": None, "account.device_session": None,
                 LAST_ACCOUNT: SOMEBODY, **maps})
    _clear_outbox(uid)
    _status["last_error"] = ""
    log.info("account: deleted on the server and forgotten here")
    _signed_out()


#: What Delete my account says when the report files would not all go
#: (``delete_account``): plain words, under 200 characters (the desk cuts
#: last_error there), and the way on is the button itself.
STORAGE_LEFT_WORDS = ("Your account was not deleted: {n} report file(s) on the server could "
                      "not be removed. Nothing else changed. Press Delete my account again.")
#: The page one list call asks for, and the most names one delete call is
#: sent: the 1000 the list always asked for. A folder past it is read, and
#: removed, a page at a time (the live limits were not read from here).
STORAGE_PAGE = 1000


def _list_objects(prefix: str) -> list[str]:
    """The names under one folder of the bucket (relative to it), every
    page of them. A refusal RAISES: until 2026-11-10 it was an empty list,
    and an empty list is what "nothing is left" looks like."""
    names: list[str] = []
    offset = 0
    while True:
        status, raw = _storage("POST", "object/list/reports", purpose="account",
                               payload={"prefix": prefix, "limit": STORAGE_PAGE, "offset": offset})
        items = _json(status, raw) if status == 200 else None
        if not isinstance(items, list):
            raise AccountError(f"the report files could not be listed ({_server_said(status, raw)})")
        names += [str(item.get("name")) for item in items
                  if isinstance(item, dict) and item.get("name")]
        if len(items) < STORAGE_PAGE:
            return names
        offset += len(items)


def _stored_files(uid: str) -> list[str]:
    """Every object under reports/<uid>/ — they sit one folder down,
    <uid>/<report_id>/<file> — as the full names a delete takes."""
    return [f"{uid}/{folder}/{name}"
            for folder in _list_objects(uid)
            for name in _list_objects(f"{uid}/{folder}")]


def _purge_storage(uid: str) -> int:
    """Every object under reports/<uid>/, removed by this client, which
    holds the delete policy, a page at a time. How many went; a delete
    the server refused raises (its status went unread until 2026-11-10)."""
    files = _stored_files(uid)
    for start in range(0, len(files), STORAGE_PAGE):
        status, raw = _storage("DELETE", "object/reports", purpose="account",
                               payload={"prefixes": files[start:start + STORAGE_PAGE]})
        if status not in (200, 204):
            raise AccountError(f"the report files could not be removed ({_server_said(status, raw)})")
    return len(files)


def _clear_outbox(uid: str) -> None:
    """This account's reports, wherever they are: the ones another account
    left waiting are that account's (``_reports_wait``)."""
    try:
        for entry in paths.OUTBOX_DIR.iterdir():
            if entry.name != paths.OUTBOX_WAITING:
                _drop(entry)
    except OSError:
        pass
    _drop(_reports_folder(uid))


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
    pass: only what the other PC just wrote comes down. What another
    account left in the file stays out of the blob (``_take_over``: the
    names in ``vocab.terms`` are in it) until a pull makes the file this
    account's, and with nothing else to say no blob goes up at all: an
    empty one would empty the settings of this account's next PC."""
    import config
    overrides = config.read_settings(paths.SETTINGS_FILE)
    uid = _fresh()["user"]["id"]
    left = set(_held_back(uid, "settings"))
    payload = {k: v for k, v in sync.settings_payload(overrides).items()
               if sync.mark(k, v) not in left}
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
        if left:
            _let_go(uid, "settings", left)
        return "pulled"
    if left and not payload and not remote:
        return "same"
    if push and (local_changed or not remote):
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
    ``push=False`` is a live pass, the pull alone. A pair another account
    left in the file (``_take_over``) is not this account's to send or to
    forget: it stays out of the rows and out of the snapshot, so its heard
    form cannot leave as a tombstone either, until the account turns out
    to hold that very pair."""
    if vocab is None:
        return "skipped"
    uid = _fresh()["user"]["id"]
    left = set(_held_back(uid, "vocab"))
    # A word list that could not be read at start (vocab.Vocab.broken)
    # tells the account nothing: every word it lacks would go out as a
    # tombstone and come off every PC. It pulls the whole list back
    # down instead, from the start of time (audit 2026-09-23, A7).
    broken = bool(getattr(vocab, "broken", None))
    since = "" if broken else str(cursor.get("vocab_pulled_at") or "")
    rows = _rows_after("vocab_sync", word="vocabulary", purpose="sync",
                       select="heard,meant,hits,last_used,deleted,updated_at",
                       ties="heard.asc", since=since, page=VOCAB_PAGE)
    pulled = 0
    snapshot = dict(cursor.get("vocab_snapshot") or {})
    if rows:
        with vocab._write_lock:
            merged, pulled = sync.merge_vocab(vocab.corrections, rows)
            if pulled:
                vocab.corrections[:] = merged
                vocab.save()
            theirs = left & {sync.word_mark(r) for r in rows if not r.get("deleted")}
            left -= theirs
            # what just came down counts as seen: it is not pushed back
            for entry in vocab.corrections:
                heard = str(entry.get("heard") or "").strip()
                if sync.word_mark(entry) in left:
                    continue          # another meaning under the same heard form
                if any(str(r.get("heard") or "").strip().lower() == heard.lower() for r in rows):
                    snapshot[heard] = {"hits": int(entry.get("hits", 1) or 0),
                                       "meant": str(entry.get("meant") or "").strip()}
            # ...and a tombstone that came down is not echoed back up as
            # one of this PC's own (nor counted by the guard below)
            gone = {str(r.get("heard") or "").strip().lower() for r in rows if r.get("deleted")}
            for key in [k for k in snapshot if k.strip().lower() in gone]:
                snapshot.pop(key, None)
        if theirs:
            _let_go(uid, "vocab", theirs)
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
        corrections = [dict(c) for c in vocab.corrections if sync.word_mark(c) not in left]
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


#: One page of a pull (``_rows_after``). No larger than the most rows the
#: server answers with (1,000 by Supabase's default): a page asked for past
#: that never comes back full, and a page that is not full is taken for the
#: last, so the rest of a stamp would go on being skipped.
HISTORY_PAGE = 500
VOCAB_PAGE = 1000


def _rows_after(table: str, *, word: str, purpose: str, select: str, ties: str, since: str,
                page: int, where: str = "") -> list:
    """A page of ``table`` newer than ``since``, oldest first, and with it
    every other row of the page's last stamp. A push is one statement and
    the server's trigger stamps its whole batch alike, so a page can end in
    the middle of a stamp, and the next page asks for what is later than
    that stamp: the rest of the batch was skipped for good, on every other
    device, with nothing to show for it. ``ties`` orders rows of one stamp,
    in both queries, so the offset means the same in each."""
    query = f"select={select}&order=updated_at.asc,{ties}&limit={page}{where}"
    if since:
        query += "&updated_at=gt." + urllib.parse.quote(since)
    status, rows = _rest("GET", table, purpose=purpose, query=query)
    if status != 200 or not isinstance(rows, list):
        raise AccountError(f"{word}: {_server_said(status, rows)}")
    if len(rows) < page:
        return rows
    last = str(rows[-1].get("updated_at") or "")
    seen = sum(1 for r in rows if str(r.get("updated_at") or "") == last)
    while True:
        status, more = _rest("GET", table, purpose=purpose,
                             query=f"select={select}&order={ties}&limit={page}&offset={seen}{where}"
                                   f"&updated_at=eq.{urllib.parse.quote(last)}")
        if status != 200 or not isinstance(more, list):
            raise AccountError(f"{word}: {_server_said(status, more)}")
        rows = rows + more
        if len(more) < page:
            return rows
        seen += len(more)


_device_names: dict = {"at": 0.0, "names": {}, "phone": False}


def _devices_known() -> bool:
    at = _device_names["at"]
    return bool(at) and time.monotonic() - at < DEVICE_NAMES_TTL_S


def _know_devices(rows: list) -> None:
    gone = forgotten()
    _device_names.update(at=time.monotonic(),
                         names={str(r.get("id")): str(r.get("name") or "") for r in rows},
                         phone=any(_is_phone(r) and str(r.get("id")) not in gone for r in rows))


def _names() -> dict[str, str]:
    """The other devices' names, from the devices table, believed for
    DEVICE_NAMES_TTL_S so a live pull is one request, not two. Under the
    purpose ``account``: a device's name is no store's, and under
    ``history`` this line was refused with that gate shut, which dropped
    the socket of a copy with only the words sync on (found 2026-11-06,
    ``notes\\phone-link-probes\\names_probe.py``)."""
    if _devices_known() and _device_names["names"]:
        return dict(_device_names["names"])
    status, rows = _rest("GET", "devices", purpose="account", query="select=id,name,platform")
    if status == 200 and isinstance(rows, list):
        _know_devices(rows)
    return dict(_device_names["names"])


def _history_aad(uid: str, row: dict) -> str:
    """The associated data a history row is sealed under — its own key
    on the server, with the stamp in one canonical form, because
    Postgres hands a ``ts`` back without its trailing zeros."""
    when = sync._parse_iso(str(row.get("ts") or ""))
    ts = when.astimezone(timezone.utc).isoformat(timespec="milliseconds") if when else str(row.get("ts") or "")
    return vault.AAD_HISTORY.format(uid=uid, device_id=str(row.get("device_id") or ""),
                                    ts=ts, kind=str(row.get("kind") or ""))


def _fit_history(text: str, raw):
    """``text`` and ``raw`` as much as fits one sealed value
    (vault.PLAIN_MAX, 5,672 bytes): whole when they fit, which is every
    row but one of the owner's 1,486 on 2026-10-23; else ``raw`` is
    dropped — the other PC reads a row's raw only for a learned pair
    (sync.remote_line), a few words that never come near the cap — and
    then, past about 2,800 Hebrew characters, the text keeps its head.
    The whole text stays in this PC's transcripts.log either way."""
    if vault.fits_json({"text": text, "raw": raw}):
        return text, raw
    keep, most = 0, len(text)                       # the longest head that fits
    while keep < most:
        mid = (keep + most + 1) // 2
        if vault.fits_json({"text": text[:mid], "raw": None}):
            keep = mid
        else:
            most = mid - 1
    return text[:keep], None


def _seal_history(key: bytes, uid: str, row: dict) -> dict:
    """The row as it leaves: ``text`` and ``raw`` gone, ``cipher`` in
    their place — always within the server's is_sealed() cap, because
    one row it refuses refuses the batch, and the cursor waits on that
    batch for good (2026-10-20 to 10-23: one long lookup held every
    later row back)."""
    text, raw = _fit_history(row.pop("text", ""), row.pop("raw", None))
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
        return _lock_wait_word()
    # down
    names = _names()
    past = _past_devices()
    pulled = unopened = 0
    for _round in range(10):
        since = str(cursor.get("history_pulled_at") or "")
        rows = _rows_after("history", word="history", purpose="history",
                           select="device_id,ts,kind,cipher,engine,seconds,updated_at",
                           ties="device_id.asc,ts.asc,kind.asc", since=since,
                           page=HISTORY_PAGE, where="&device_id=neq." + mine)
        if not rows:
            break
        lines = []
        for r in rows:
            if str(r.get("device_id")) in past:
                continue                 # what this PC said before it was forgotten
            opened = _open_history(key, uid, r)
            if opened is None:
                unopened += 1
                continue
            lines.append(sync.remote_line(opened, names.get(str(r.get("device_id")), "")))
        pulled += sync.append_remote_history(lines)
        cursor["history_pulled_at"] = str(rows[-1].get("updated_at") or since)
        _write_cursor(cursor, uid)
        if len(rows) < HISTORY_PAGE:
            break
    # up
    events = history.all_events() if push else []
    floor = _per_account("account.history_floor").get(uid)
    pushed = 0
    for _round in range(10):
        batch = sync.history_rows(events, mine, _later(cursor.get("history_pushed_ts"), floor))
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
        _write_cursor(cursor, uid)
        if len(batch) < sync.HISTORY_BATCH:
            break
    word = f"pulled {pulled}, pushed {pushed}"
    return word + (f", {unopened} not opened" if unopened else "")


#: The keys' cursor as it was before each slot kept its own record —
#: carried into this slot's record on the first pass (``_slot_record``).
_VAULT_FLAT: tuple[str, ...] = ("vault_pulled_at", "vault_pushed", "vault_digest")


def _slot_record(cursor: dict, key: bytes) -> dict:
    """This slot's record of what it synced. The first pass after the
    slots were split finds the folder's old single record instead and
    carries it over: it describes the keys this copy synced from
    ``DeskIT/``, and migrations step 6 copied those very keys into the
    slot at start, so the two agree and a key changed here since is
    pushed. A name the old record knew that the slot does not hold (the
    copy failed, or the person emptied it) is forgotten instead of being
    read as a removal, and the account's rows come down again from the
    start, which fills it."""
    slots: dict = cursor.setdefault("vault_slots", {})
    flat = {k: cursor.pop(k) for k in _VAULT_FLAT if k in cursor}
    if secretstore.TARGET_PREFIX in slots:
        return dict(slots[secretstore.TARGET_PREFIX])
    if not flat:
        return {}
    record = {"pulled_at": str(flat.get("vault_pulled_at") or ""),
              "pushed": dict(flat.get("vault_pushed") or {}),
              "digest": dict(flat.get("vault_digest") or {})}
    _digests, present = vault.digest_keys(key)
    gone = [n for n in record["digest"] if n not in present]
    for name in gone:
        record["digest"].pop(name, None)
        record["pushed"].pop(name, None)
    if gone:
        record["pulled_at"] = ""
    return record


def _sync_vault(cursor: dict, push: bool = True) -> str:
    """The cloud keys, one sealed row per name, under the words-and-
    settings gate (a key is a setting). Down: a row newer than the
    cursor that is not what this PC pushed goes into Credential Manager
    through vault.import_keys — this module never holds the value. Up:
    a name whose keyed digest moved since the last pass is exported
    sealed; a name that is empty here and was never synced is NOT
    pushed (a fresh PC must not wipe the account's keys), an emptied
    one is (a key removed here is removed everywhere). Last writer wins
    per name. ``push=False`` is the live pull.

    The cursor's half for the keys is the SLOT's, not the folder's: one
    record per Credential Manager prefix (``vault_slots``). Until
    2026-10-04 it was one record and every copy shared ``DeskIT/``; when
    each copy got a prefix of its own (secretstore.TARGET_PREFIX), the old
    record is carried into the slot's once (``_slot_record``): dropping it
    made the first pass a fresh PC's, and the owner's Dev copy, whose key
    he replaced in the minute between the update and that pass, had the
    account's dead key pulled over the new one (2026-10-04 19:56:04,
    "vault pulled 1, pushed 0", 0.4 s after the provider accepted the new key);
    and keeping it as it was would have read a slot that is new and empty
    as "the person removed the key here" and pushed the removal to every
    PC. A slot with no record at all is a fresh PC's: everything the
    account holds comes down, and only a name the account has never had
    goes up. Two programs that share one data folder under different
    prefixes keep a record each. A slot with no record may also hold what
    another account left in it, which is no name of this one's to send
    (``_take_over``): that was the second road by which a foreign key got
    into an account, after the one of 2026-10-03 in AGENTS.md."""
    uid = _fresh()["user"]["id"]
    key = _lock_key(uid)
    if key is None:
        return _lock_wait_word()
    slots: dict = cursor.setdefault("vault_slots", {})
    mine: dict = _slot_record(cursor, key)
    pushed_ciphers: dict = dict(mine.get("pushed") or {})
    known: dict = dict(mine.get("digest") or {})
    # down
    since = str(mine.get("pulled_at") or "")
    query = "select=name,cipher,updated_at&order=updated_at.asc"
    if since:
        query += "&updated_at=gt." + urllib.parse.quote(since)
    status, rows = _rest("GET", "vault", purpose="sync", query=query)
    if status != 200 or not isinstance(rows, list):
        raise AccountError(f"keys: {_server_said(status, rows)}")
    # the keys and nothing else: the table holds the forgotten list too
    # (_write_forgotten), which is no slot's and has no digest
    incoming = {str(r.get("name")): str(r.get("cipher") or "") for r in rows
                if str(r.get("name")) in secretstore.CRED_NAMES and r.get("cipher")
                and str(r.get("cipher")) != pushed_ciphers.get(str(r.get("name")))}
    changed = vault.import_keys(key, uid, incoming) if incoming else []
    if rows:
        mine["pulled_at"] = str(rows[-1].get("updated_at") or since)
    if changed or incoming:
        digests, _present = vault.digest_keys(key)
        for name in incoming:
            known[name] = digests.get(name, "")
        mine["digest"] = known
        for name in incoming:
            pushed_ciphers.pop(name, None)
        mine["pushed"] = pushed_ciphers
    slots[secretstore.TARGET_PREFIX] = mine
    # up
    pushed = 0
    if push:
        digests, present = vault.digest_keys(key)
        stays = _keys_left_here(uid)
        to_push = [n for n, d in digests.items()
                   if known.get(n) != d and (n in present or n in known) and n not in stays]
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
                mine["pulled_at"] = max([mine.get("pulled_at") or ""] + stamps)
            pushed_ciphers.update(sealed)
            mine["pushed"] = pushed_ciphers
            for n in to_push:
                known[n] = digests[n]
            mine["digest"] = known
            slots[secretstore.TARGET_PREFIX] = mine
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
               extra: dict | None = None, purpose: str = "account") -> None:
    """Tell the account's other copies which stores just changed: one
    POST on the private topic, carrying the store names and this
    device's id and nothing else. The lock's two events ride the same
    topic — ``pairing`` (a PC asks to join: its request id, code and
    name) and ``paired`` (a PC approved: the request id) — and carry
    nothing a stranger could use: the code is compared on two screens,
    the key crosses wrapped inside the table. ``signed_out`` (Sign out of
    every PC, ``_end_the_others``) carries the device id alone and only
    makes the others ask the server, and ``changed`` naming ``devices``
    says a device wrote its row or forgot one. A failure is a debug line
    — the 15-minute pass delivers the rows all the same.

    ``purpose`` is the gate the POST goes out under: ``account`` for
    everything that is no store's, so a person with both syncs off can be
    reached and can answer; a store's own gate for a store's push."""
    try:
        uid = _fresh()["user"]["id"]
        payload = {"device": device_id(), **(extra or {})}
        if stores:
            payload["stores"] = sorted(stores)
        status, _h, body = net.post_json(
            f"{base_url()}/realtime/v1/api/broadcast", purpose,
            {"messages": [{"topic": LIVE_TOPIC.format(uid=uid), "event": event,
                           "private": True, "payload": payload}]},
            secret=SESSION_NAME, timeout_s=TIMEOUT_S)
        if status not in (200, 202):
            log.debug("live: the broadcast was answered %s (%s)", status, _server_said(status, body))
    except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
        log.debug("live: no broadcast (%s)", e)


def sync_now(vocab=None, reason: str = "", only=None, push: bool = True,
             after_pass: bool = False) -> dict:
    """One pass over everything the gates allow — or, with ``only``, over
    those stores alone (a nudge names the store that changed; a live
    broadcast names the store the other PC changed, and ``push=False``
    then makes it a pull). Never raises: each store's outcome (or its
    error) is a word in the returned dict and a line in the log;
    ``last_sync``/``last_error`` feed the Account row. Nothing happens
    without a session or with every gate shut. Every push ends with a
    broadcast naming what was pushed. One pass at a time: the worker
    and the live thread share the cursor file. ``after_pass``: the
    account pass ran a moment ago, so the profile and the lock are not
    looked at twice; the pass takes the key this one seals with from
    what that one found."""
    out: dict[str, str] = {}
    if not configured() or not signed_in() or not privacy.allowed("account"):
        # the account gate is under the two syncs: with it shut (stale, or
        # withdrawn) their own gates still open, the words and settings went
        # on syncing for the rest of the token's hour, and then every
        # dictation left a refused row in network.log
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
            # a session this PC's record has not met (a copy from before
            # the record, a sign-in whose door tripped) stops here and not
            # at a push; if it cannot be told, nothing below runs
            uid = str((user() or {}).get("id") or "")
            _take_over(uid)
            cursor = sync.read_cursor()
            if not after_pass:
                try:
                    ensure_profile()
                except (AccountError, net.EgressRefused, net.NetError) as e:
                    out["profile"] = f"error: {e}"
            # the lock first: the key this pass seals and opens with,
            # made here on the account's first PC, asked for on the next
            try:
                key = _lock_key(uid) if after_pass else _ensure_lock(uid)
                if key is not None:
                    _cursor_follows_lock(cursor, key, uid)
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
                _write_cursor(cursor, uid)
            if changed and signed_in():
                # each store went up under its own gate, so a push of
                # history alone must not be sent under the other one
                _broadcast(changed, purpose="history" if changed == ["history"] else "sync")
            errors = [f"{k}: {v[7:]}" for k, v in out.items() if v.startswith("error: ")]
            # the account went away under this pass: _account_gone has
            # said why in plain words, and the stores' errors are its
            # echo — the log's, not the sign-in card's
            gone = not signed_in()
            if errors:
                if not gone:
                    _status["last_error"] = "; ".join(errors)[:200]
                log.info("sync%s: %s", f" ({reason})" if reason else "", "; ".join(errors))
            else:
                if not gone:
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
    if not configured() or not signed_in() or not privacy.allowed("account") \
            or not privacy.allowed("report_upload"):
        return out
    try:
        # through the door first, as sync_now is: with both syncs off nothing
        # else asks, and a report goes out as whoever is signed in
        _take_over(str((user() or {}).get("id") or ""))
    except Exception as e:                                   # noqa: BLE001
        log.info("report: the outbox waits (%s)", e)
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


def _worker_pass(vocab, on_sent, only) -> None:
    """One turn of the worker. A pass over everything (``only`` None) starts
    with the account pass, which needs no sync and is what reaches a person
    with both syncs off; sync_now then takes what that pass found, so a PC
    waiting to be approved looks at its request once a turn and not twice.
    A nudge names its stores and is those stores alone: a dictation must
    not cost the requests of an account pass. Only the app has a worker, so
    this is also where a leaving noticed in the desk or the wizard is
    finished (``settle_left``). ``only == ()`` is a look at the lock and
    nothing else (``_plan_turn``). A state.json that will not read does not
    end the turn: it was a debug line and a worker that stopped without a
    word. The person's status says so and the turn goes on, because
    whatever needs the file refuses by itself."""
    try:
        settle_left()
    except AccountError as e:
        _status["last_error"] = str(e)[:200]
    else:
        if _status.get("last_error") == STATE_WORDS:
            _status["last_error"] = ""
        if _lock_state.get("error") == STATE_WORDS:
            _lock_state["error"] = ""
    if not signed_in():
        return
    if not only:
        account_pass(reason="worker")
    if only == ():
        return
    sync_now(vocab, reason="nudge" if only else "worker", only=only, after_pass=only is None)
    drain_outbox(on_sent)


def _pace(plan: dict, live_since: float | None) -> float:
    """How often the whole pass comes: CADENCE_LIVE_S while the live socket
    that is up now joined before the last whole pass (``live_since``, the
    join's time.monotonic(), None with no socket), CADENCE_S otherwise — no
    socket, or one that came back after that pass, whose gap may have
    swallowed a broadcast. The next whole pass closes the gap."""
    full = plan.get("full")
    if live_since is not None and full is not None and live_since <= full:
        return CADENCE_LIVE_S
    return CADENCE_S


def _live_since() -> float | None:
    """When the socket that is up now joined, or None (``_pace``)."""
    return _live_state.get("joined") if _live_state.get("on") else None


def _plan_turn(plan: dict, named: set, now: float, waiting: bool,
               live_since: float | None = None):
    """What one turn of the worker does, from what woke it: None a pass over
    everything, a list those stores, ``()`` a look at the lock alone. The
    15-minute pass was only ever the wait running out, and every nudge
    restarts the wait, so a person dictating more often than that never got
    one, and that pass is the account pass now: no forgotten list, no
    request to join, no hooks. So it comes due by the clock, whatever woke
    the worker — the clock of ``_pace``. A PC waiting to be approved wakes
    every few seconds, and a wake like that looks at its request and no
    more: the settings and the words each turn were half its requests."""
    if "*" in named or now - plan.get("full", float("-inf")) >= _pace(plan, live_since):
        plan["full"] = now
        return None
    if named:
        return sorted(named)
    if waiting:
        return ()
    plan["full"] = now
    return None


def _plan_wait(plan: dict, now: float, waiting: bool,
               live_since: float | None = None) -> float:
    """How long the worker sleeps after a turn: ``_pace``. Waiting to be
    approved it looks every few seconds for the life of the first request,
    which is a person walking to their other device; after that it is one
    who has walked away, and one copy left waiting was 2,880 requests an
    hour on a free tier. The ``paired`` event still answers at once, and a
    press here starts the quick looks again."""
    if not waiting:
        plan.pop("asked", None)
        return _pace(plan, live_since)
    since = plan.setdefault("asked", now)
    return PAIRING_POLL_S if now - since < PAIRING_TTL_S else CADENCE_S


def start_worker(vocab=None, on_sent=None) -> threading.Thread | None:
    """The app's background pass: FIRST_DELAY_S after start, then every
    CADENCE_S (CADENCE_LIVE_S while the live socket holds, ``_pace``), and
    NUDGE_SETTLE_S after a nudge (a dictation ended, a
    consent opened, the person pressed Sync now) — over the stores the
    nudges named, or everything; a pass over everything starts with the
    account pass, which needs no sync. Starts the live thread beside it.
    Does nothing without a configured project."""
    global _worker, _live
    if not configured() or (_worker is not None and _worker.is_alive()):
        return _worker
    # no network, and before anything can end the session: a copy from
    # before the record that is signed in here says so now, or a session
    # that dies first leaves its own account looking like somebody else
    try:
        _take_over((user() or {}).get("id", ""))
    except Exception as e:                                   # noqa: BLE001
        log.info("account: the record of this PC's account was not written (%s)", e)

    def _settings_stamp():
        try:
            return paths.SETTINGS_FILE.stat().st_mtime_ns
        except OSError:
            return None

    def loop() -> None:
        _wake.wait(FIRST_DELAY_S)
        seen = _settings_stamp()
        plan: dict = {}
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
            only = _plan_turn(plan, named, time.monotonic(),
                              _lock_state.get("state") == "waiting", _live_since())
            try:
                _worker_pass(vocab, on_sent, only)
            except Exception:                                # noqa: BLE001
                log.debug("account worker tripped", exc_info=True)
            # the wait is asked again every PACE_CHECK_S: the socket's
            # state moves the pace, and an hour's wait must not outlive
            # the socket it was measured for
            ended = time.monotonic()
            while True:
                now = time.monotonic()
                left = _plan_wait(plan, now, _lock_state.get("state") == "waiting",
                                  _live_since()) - (now - ended)
                if left <= 0:
                    break
                if _wake.wait(min(left, PACE_CHECK_S)):
                    time.sleep(NUDGE_SETTLE_S)
                    with _lock:
                        pressed = not _pending   # Same code, not a dictation
                    if pressed:
                        plan.pop("asked", None)
                    break

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
_live_state: dict = {"on": False, "error": "", "asked": False}


def _ask_about_this_session(why: str) -> None:
    """Ask the server about this copy's session NOW, not at the worker's
    next pass: a refused refresh is ``_account_gone`` and the lock. Two
    doors call it — another PC's ``signed_out`` on the live channel, and
    a refused join (since migration 0006 the channel refuses a session
    that has ended: measured 2026-10-03, a copy reopened after Sign out
    of every PC was refused at 4 s and still waited for its first pass,
    30 s after the start, to lock)."""
    log.info("live: %s — asking the server about this session", why)
    try:
        with _lock:
            _refresh()
    except AccountError as e:
        log.info("live: %s", e)


def _live_purpose() -> str | None:
    """The purpose the socket is opened under: ``account`` for any
    signed-in copy, whatever its syncs say, because a device asking to
    join and a device forgotten are news to a copy with both syncs off
    too (PHONE_LINK_PLAN.md stage 1). The socket carries nothing personal.
    None when the account gate is shut."""
    return "account" if privacy.allowed("account") else None


def _held() -> bool:
    """Did this try's socket stay up? A join that was answered says nothing:
    a socket that joins and drops at once would be a new one every 5 s for
    ever. One heartbeat's time is a socket that worked."""
    joined = _live_state.get("joined")
    return joined is not None and time.monotonic() - joined >= LIVE_HEARTBEAT_S


def _live_loop(vocab) -> None:
    """Hold the socket for as long as the account and its gate are
    there; reconnect with LIVE_RETRY_S between tries; never raise."""
    tries = 0
    _live_state["asked"] = False
    while not _live_stop.is_set():
        _live_state["joined"] = None
        try:
            if not (configured() and signed_in()) or _live_purpose() is None or net.offline:
                _live_state["on"] = False
                if _live_stop.wait(15.0):
                    return
                continue
            _live_once(vocab)
            tries = 0
        except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
            # a socket that held and dropped is a laptop's lid, not a
            # refusal: it starts the ladder again, or five minutes was
            # every reconnect after a few nights' sleep
            tries = 0 if _held() else tries + 1
            why = str(e)[:200]
            (log.info if why != _live_state["error"] else log.debug)("live: %s", why)
            _live_state.update(on=False, error=why)
        except Exception:                                    # noqa: BLE001
            tries = 0 if _held() else tries + 1
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
            if not _live_state.get("asked"):
                # once per run of refusals: a channel refused for any
                # other reason must not cost a refresh at every retry
                _live_state["asked"] = True
                _ask_about_this_session("the live channel refused the join")
            raise AccountError(f"the live channel refused the join: {said}")
        _live_state.update(on=True, error="", asked=False, joined=time.monotonic())
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
                # The channel closes the moment the token it holds runs out,
                # and _fresh's 10 s margin falls between two heartbeats 25 s
                # apart: app.log 2026-11-07..10 has the channel dropped
                # (phx_close) 57 times in 61 joins, each 3,600 s after its
                # join, then a new socket 6 s later — 4 requests an hour and
                # a gap no broadcast reaches. So the token is renewed one
                # heartbeat early, and sent below.
                fresh = _fresh(LIVE_HEARTBEAT_S + REFRESH_MARGIN_S)
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
                    account_pass(reason="paired")
                    sync_now(vocab, reason="paired", after_pass=True)
                continue
            if inner.get("event") == "signed_out":
                # another PC signed every PC out (_end_the_others): ask
                # the server about this session now, not at the end of
                # its token's hour. The event only makes this copy look;
                # a refused refresh is _account_gone and the lock, and
                # the loop's next turn closes the socket.
                _ask_about_this_session("another PC signed every PC out")
                continue
            if inner.get("event") != "changed":
                continue
            named = list(what.get("stores") or [])
            if "devices" in named:
                # a device wrote its row or forgot one: the rows are read
                # again and the hooks run, and a PC that waited for a
                # phone to exist may ask to join now
                log.info("live: the account's devices changed")
                _device_names["at"] = 0.0
                account_pass(reason="live")
                if _lock_state.get("state") == "waiting":
                    _wake.set()
            stores = [s for s in named if s in STORES]
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
                     "pending": [], "recovery": None, "error": "", "changed": None}
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
                           recovery=None, error="", changed=None)
    _device_names.update(at=0.0, names={}, phone=False)
    _seen_pairings.clear()


def _lock_key(uid: str) -> bytes | None:
    """The key a store may seal with: this PC's, once ``_ensure_lock``
    said it is the account's."""
    return vault.key(uid) if _lock_state.get("state") == "have" else None


def _lock_wait_word() -> str:
    """What a sealed store says when it may not move: waiting for an
    approval, or paused because the lock changed somewhere else."""
    if _lock_state.get("state") == "changed":
        return "paused — the lock changed"
    return "waiting for the lock"


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
    approved or the recovery key is typed. The account's lock is not the
    one this PC holds: this PC keeps its key and the lock is "changed" —
    None, both sealed stores paused, until the person answers on Home
    (2026-09-23: the server never decides which key a PC trusts). A PC
    with both syncs off makes a lock and holds one all the same, unseen,
    and asks to join only once the account has a phone or the person
    asked (``_may_ask``): nobody who turned the syncs off should find a
    "Waiting" row on Home for something they never wanted. Every outcome
    is a log line and status()["lock"]."""
    key = vault.key(uid)
    fp = vault.fingerprint(key) if key else ""
    st = _lock_state
    if key is not None and st.get("state") == "have" and st.get("lock_id") == fp \
            and time.monotonic() - st["at"] < LOCK_TTL_S:
        return key
    remote = _profile_lock_id(uid)
    if remote is None:
        ensure_profile(force=True)
        key = vault.key(uid)             # the row said this PC was forgotten
        fp = vault.fingerprint(key) if key else ""
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
        _set_lock(state="have", lock_id=fp, pairing=None, changed=None)
        if vault.refused(uid):
            vault.refuse(uid, "")        # the lock is this PC's again
        if first:
            _recovery_known()
        return key
    if key is not None:
        # NOT dropped (it was, until 2026-09-23: one write of the
        # profile made every PC delete its key and take the next one
        # handed to it — the audit's A15). The server does not get to
        # say which key this PC trusts; the person does, on Home.
        return _lock_changed(uid, fp, remote)
    was = vault.confirmed(uid)
    if was is not None and was != remote:
        # this PC set its key aside for the lock the person confirmed,
        # and the server now names yet another one: asked again
        return _lock_changed(uid, "", remote)
    req = st.get("pairing")
    if was is None and not (req and req["expires"] > time.time()) and not _may_ask():
        if req:
            vault.drop(req["id"])
        _set_lock(state="", lock_id="", pairing=None, changed=None)
        return None
    return _request_pairing(uid, remote)


def _lock_changed(uid: str, mine: str, remote: str) -> None:
    """The profile names a lock this PC does not hold (``mine`` is this
    PC's own fingerprint, "" when it set its key aside already). Nothing
    is dropped and nothing is taken: the state is "changed", the sealed
    stores pause both ways, and Home asks whether it was him. A lock he
    already said was not his stays refused across restarts."""
    was = _lock_state.get("changed") or {}
    if was.get("server") != remote:
        log.warning("lock: the account's lock on the server (%s) is not the one this PC "
                    "holds (%s) — this PC keeps its key; what you said and your keys are "
                    "paused until you answer on Home", remote, mine or "set aside")
    req = _lock_state.get("pairing")
    if req:
        vault.drop(req["id"])
    refused = bool(mine) and vault.refused(uid) == remote
    # pending=[]: a PC that does not trust the account's lock approves nobody
    _set_lock(state="changed", lock_id=mine, pairing=None, pending=[],
              changed={"server": remote, "mine": mine, "refused": refused})
    return None


def _cursor_follows_lock(cursor: dict, key: bytes, uid: str) -> None:
    """A lock the cursor has not seen — the first pass under one, or a
    key that changed: what was said and the keys sync again from the
    start (the rows on the server are sealed under the new key, the
    other PCs' lines on this PC came under the old one). The first pass
    after a sign-out is one of those, and under the same lock what went
    up then is still up (``_keep_what_went_up``). Only then: a cursor with
    a lock on it is a lock that moved in session, and one that came back
    to the lock of that sign-out finds these rows re-sealed under the lock
    between, where only going up again can open them."""
    fp = vault.fingerprint(key)
    had = cursor.get("lock")
    if had == fp:
        return
    if had:
        log.info("lock: the account's key changed — what was said syncs again from the start")
    for name in ("history_pulled_at", "history_pushed_ts", "vault_slots") + _VAULT_FLAT:
        cursor.pop(name, None)
    sync.forget_remote()
    cursor["lock"] = fp
    kept = _per_account(PUSHED).get(uid)
    if not had and isinstance(kept, dict) and kept.get("lock") == fp and kept.get("ts"):
        cursor["history_pushed_ts"] = kept["ts"]
    _write_cursor(cursor, uid)


def _request_pairing(uid: str, remote: str) -> bytes | None:
    """This PC's open request to join, made if there is none, looked at
    if there is: approved means the key is taken out of what the other PC
    handed over and kept here — only when its fingerprint is the lock the
    profile named when this PC asked AND names now, and, on a PC that set
    a key aside, the lock the person confirmed.

    A request whose time ran out is made again as the SAME request: the
    id, the key and the code stay, in a new row, because `pairings_guard`
    freezes `expires_at`. Every device knocks once per id
    (``_seen_pairings``), so a new id every fifteen minutes was a card and
    a cue on all of them for as long as a copy was left waiting, the card
    went on naming the old code, and the code here changed under whoever
    was comparing it. Home's rows stay true on both sides: this PC is
    asking, under the code it shows. Not now takes the row away for the
    rest of the request's time (at the next look it was back in five
    seconds, with a card), and an answer handed over before the press stays
    where it is, whatever the time says."""
    st = _lock_state
    req = st.get("pairing")
    now = time.time()
    if req is not None and req.get("lock_id", remote) != remote:
        # the lock moved while this PC waited: this request asked for
        # another one — dropped, and asked afresh for the lock named now
        log.info("lock: the account's lock moved while this PC waited — asking again")
        vault.drop(req["id"])
        req = None
    handed = False
    if req is not None:
        status, rows = _rest("GET", "pairings", purpose="account",
                             query=f"select=handed,approved_at&id=eq.{req['id']}")
        if status != 200 or not isinstance(rows, list):
            raise AccountError(f"lock: {_server_said(status, rows)}")
        handed = bool(rows and rows[0].get("handed"))
        if handed and req.get("same"):
            # both sides press: without this one a dishonest server writes
            # `handed` itself, with no other device at all, under a lock it
            # named. Whatever is there stays unopened until the person here
            # has said the two codes are the same, before or after the Approve
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
                was = vault.confirmed(uid)
                if not remote or fp != remote or (was is not None and fp != was):
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
    new = req is None
    if new or (not handed and req["expires"] <= now):
        # this PC's earlier requests go first — the wizard's, say, whose
        # private half died with its process — so the other PC's card
        # never shows a code this PC no longer does
        try:
            _rest("DELETE", "pairings", purpose="account",
                  query=f"device_id=eq.{urllib.parse.quote(device_id())}")
        except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
            log.debug("lock: the old requests were not swept (%s)", e)
        if new:
            pid = str(uuid.uuid4())
            public = vault.applicant(pid)
            # the code is the key's own and the lock's (vault.pairing_code):
            # the other device computes it from the same public key and the
            # key it holds, never from a column
            req = {"id": pid, "public": public, "lock_id": remote,
                   "code": vault.pairing_code(uid, pid, public, remote)}
        status, data = _rest("POST", "pairings", purpose="account",
                             payload={"id": req["id"], "user_id": uid, "device_id": device_id(),
                                      "device_name": request_name(),
                                      "code": vault.code_hint(req["code"]),
                                      "applicant": req["public"]},
                             prefer="return=minimal")
        if status not in (200, 201, 204):
            if new:
                vault.drop(req["id"])
            raise AccountError(f"lock: the request to join was refused ({_server_said(status, data)})")
        req["expires"] = now + PAIRING_TTL_S
        log.info("lock: another PC holds the account's key — this PC %s to join (code %s)",
                 "asks" if new else "goes on asking", req["code"])
        _set_lock(state="waiting", lock_id=remote, pairing=req)
        # not a knock on a request that was seen: it puts the row back on Home
        _broadcast(event="pairing", extra={"id": req["id"], "code": req["code"], "name": request_name()})
    else:
        _set_lock(state="waiting", lock_id=remote, pairing=req)
    return None


def same_code(code: str) -> None:
    """[Same code] on the screen that shows the code: the joining side's
    half of the join, as in Bluetooth pairing. The code binds the lock, and
    that is worth something only if this device waits for its own person:
    until this press it neither opens nor keeps what it was handed. It may
    come before or after the Approve; what was handed is taken at the next
    look (``_request_pairing``). ``code`` is the one the screen showed: a
    request made afresh meanwhile has another, and is not answered by a
    press on the old one."""
    with _lock:
        req = _lock_state.get("pairing")
        if not req:
            raise AccountError("this PC is not waiting to join")
        if str(code or "").strip() != req["code"]:
            raise AccountError("the code changed — look at it again")
        req["same"] = True
    log.info("lock: Same code was pressed on this PC")
    _run_lock_hooks()
    _wake.set()


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
                uid = _fresh()["user"]["id"]
                key = _ensure_lock(uid)
                if key is not None:
                    _cursor_follows_lock(sync.read_cursor(), key, uid)
    except (AccountError, net.EgressRefused, net.NetError, vault.VaultError, OSError) as e:
        with _lock:
            _lock_state["error"] = str(e)[:200]
        log.info("lock: %s", e)
    return lock_status()


def pending_pairings() -> list[dict]:
    """The other PCs of this account waiting to be approved by this one
    — read off the table, each new one handed to PAIRING_HOOKS once.
    Nothing without the key: a PC that does not hold it cannot hand it
    over. The code each carries is COMPUTED here from the request's own
    public key and the fingerprint of the key this PC holds
    (vault.pairing_code) — neither the ``code`` column nor the profile's
    lock is read — so a twin request with another key shows another code,
    and so does a server that named the asking device another lock. Two open
    requests from one PC are one entry with ``twins`` and no code:
    neither can be approved (the audit's A74 — a copied twin used to
    collapse into the newest row and carry the real one's code)."""
    if not (configured() and signed_in()):
        return []
    uid = _fresh()["user"]["id"]
    key = vault.key(uid)
    if key is None or _lock_state.get("state") == "changed":
        return []
    lock_id = vault.fingerprint(key)
    status, rows = _rest("GET", "pairings", purpose="account",
                         query="select=id,device_id,device_name,applicant,created_at,expires_at"
                               "&handed=is.null&order=created_at.asc")
    if status != 200 or not isinstance(rows, list):
        raise AccountError(f"lock: {_server_said(status, rows)}")
    now = datetime.now(timezone.utc)
    asking: dict[str, list[dict]] = {}           # the open requests, by asking PC
    for r in rows:
        if str(r.get("device_id") or "") == device_id():
            continue
        until = sync._parse_iso(str(r.get("expires_at") or ""))
        if until is not None and until <= now:
            continue
        asking.setdefault(str(r.get("device_id") or r.get("id")), []).append(r)
    out: list[dict] = []
    for reqs in asking.values():
        r = reqs[-1]
        asker = _BIDI_MARKS.sub("", str(r.get("device_name") or ""))
        entry = {"id": str(r.get("id") or ""), "name": asker or "another device",
                 "code": "", "created_at": str(r.get("created_at") or ""),
                 "device": str(r.get("device_id") or "")}
        if len(reqs) > 1:
            entry["twins"] = len(reqs)
            if entry["id"] not in _seen_pairings:
                log.warning("lock: %d open requests to join say they are the same PC — "
                            "none of them can be approved", len(reqs))
        else:
            try:
                entry["code"] = vault.pairing_code(uid, entry["id"], str(r.get("applicant") or ""),
                                                   lock_id)
            except vault.VaultError as e:
                log.info("lock: a request to join without a usable public key — skipped (%s)", e)
                continue
        out.append(entry)
    with _lock:
        was = [r["id"] for r in _lock_state.get("pending") or []]
        _lock_state["pending"] = out
        fresh = [r for r in out if r["id"] not in _seen_pairings]
        _seen_pairings.update(r["id"] for r in fresh)
    fresh = [r for r in fresh if not r.get("twins")]   # no knock for a request nobody can approve
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
    crosses, and it crosses sealed. Returns the other PC's name. Only
    the request the person was SHOWN: its code, computed again from the
    public key read now, must be the code on Home (a row deleted and
    written again under the same id with another key is refused), and a
    PC with two open requests gets neither."""
    uid = _fresh()["user"]["id"]
    key = vault.key(uid)
    if key is None or _lock_state.get("state") == "changed":
        raise AccountError("this PC does not hold the account's key")
    pid = str(pairing_id or "").strip()
    status, rows = _rest("GET", "pairings", purpose="account",
                         query="select=applicant,device_id,device_name,handed,expires_at"
                               f"&id=eq.{urllib.parse.quote(pid)}")
    if status != 200 or not isinstance(rows, list):
        raise AccountError(f"lock: {_server_said(status, rows)}")
    if not rows:
        raise AccountError("that request is gone")
    row = rows[0]
    name = str(row.get("device_name") or "") or "another device"
    until = sync._parse_iso(str(row.get("expires_at") or ""))
    if until is not None and until <= datetime.now(timezone.utc):
        raise AccountError(f"{name}'s request expired — it asks again on its own")
    shown = next((r for r in _lock_state.get("pending") or [] if r.get("id") == pid), None)
    if shown is None or shown.get("twins") or not shown.get("code"):
        raise AccountError("that is not the request Home shows — look at Home again")
    if not row.get("handed"):
        try:
            code = vault.pairing_code(uid, pid, str(row.get("applicant") or ""),
                                      vault.fingerprint(key))
        except vault.VaultError as e:
            raise AccountError(f"{name}'s request carries no usable key") from e
        if code != shown["code"]:
            log.warning("lock: a request to join changed after it was shown — not approved")
            raise AccountError(f"{name}'s request changed after Home showed it — not approved")
        status, same = _rest("GET", "pairings", purpose="account",
                             query="select=id,expires_at&handed=is.null&device_id=eq."
                                   + urllib.parse.quote(str(row.get("device_id") or "")))
        if status != 200 or not isinstance(same, list):
            raise AccountError(f"lock: {_server_said(status, same)}")
        now = datetime.now(timezone.utc)
        until_of = (sync._parse_iso(str(r.get("expires_at") or "")) for r in same)
        open_ = [u for u in until_of if u is None or u > now]
        if len(open_) > 1:
            log.warning("lock: %d open requests say they are the same PC — none approved", len(open_))
            raise AccountError(f"two requests say they are {name} — neither is approved")
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
    """[Not now] on this PC: the request goes, and the other PC asks again
    when the request's time is up, with no knock (``_request_pairing``)."""
    pid = str(pairing_id or "").strip()
    _rest("DELETE", "pairings", purpose="account", query=f"id=eq.{urllib.parse.quote(pid)}")
    with _lock:
        _lock_state["pending"] = [r for r in _lock_state.get("pending") or [] if r["id"] != pid]
    log.info("lock: a request to join was declined on this PC")
    _run_lock_hooks()


def lock_answer(yes: bool) -> str:
    """Home's answer to "the lock of your account changed — was it you?".

    [It was me]: this PC's key is MOVED ASIDE (vault.set_aside — kept,
    never deleted) with the lock he confirmed written beside it, and
    this PC asks to join that lock the usual way — another PC of his
    approves it, or he types the recovery key; a key handed over for any
    other lock is not taken. Returns "asked".
    [It wasn't me]: nothing moves. The key stays, the sealed stores stay
    paused both ways, and the refusal is written beside the key so a
    restart does not ask again; Home then points to Sign out of every PC
    (every session of the account, a stolen one too) and offers
    ``restore_lock``. Returns "kept"."""
    uid = _fresh()["user"]["id"]
    with _sync_lock:
        ch = dict(_lock_state.get("changed") or {})
        if _lock_state.get("state") != "changed" or not ch.get("server"):
            raise AccountError("the lock has not changed — there is nothing to answer")
        remote = _profile_lock_id(uid) or ""
        if remote != ch["server"]:
            _ensure_lock(uid)
            raise AccountError("the lock changed again — look at Home once more")
        if not yes:
            vault.refuse(uid, remote)
            _set_lock(state="changed", changed=dict(ch, refused=True))
            log.warning("lock: the change of lock was refused on this PC — the key stays and "
                        "what you said and your keys stay paused")
            return "kept"
        moved = vault.set_aside(uid, remote)
        log.info("lock: the change of lock was confirmed on this PC — %s; this PC asks to "
                 "join the new lock (%s)", "its key is set aside" if moved else "no key here",
                 remote)
        with _lock:
            _lock_state.update(state="", lock_id="", changed=None)
        _ensure_lock(uid)
    _wake.set()
    return "asked"


def restore_lock() -> str:
    """[Put my lock back], offered after [It wasn't me]: this PC's own
    fingerprint written over the one the server was given — only while
    the profile still names the lock he refused, so a later change is
    never overwritten unseen. The key never moved; the stores resume
    under it. Returns this PC's fingerprint."""
    uid = _fresh()["user"]["id"]
    with _sync_lock:
        key = vault.key(uid)
        ch = dict(_lock_state.get("changed") or {})
        if key is None or _lock_state.get("state") != "changed" or not ch.get("refused"):
            raise AccountError("there is no lock of this PC to put back")
        fp = vault.fingerprint(key)
        status, rows = _rest("PATCH", "profiles", purpose="account",
                             query=f"user_id=eq.{urllib.parse.quote(uid)}"
                                   f"&lock_id=eq.{urllib.parse.quote(ch['server'])}",
                             payload={"lock_id": fp}, prefer="return=representation")
        if status not in (200, 201, 204):
            raise AccountError(f"lock: the fingerprint was refused ({_server_said(status, rows)})")
        if not (isinstance(rows, list) and rows):
            _ensure_lock(uid)
            raise AccountError("the lock changed again — look at Home once more")
        vault.refuse(uid, "")
        _set_lock(state="have", lock_id=fp, pairing=None, changed=None)
        log.warning("lock: this PC put its own lock back on the account (%s)", fp)
    _wake.set()
    return fp


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
    if _lock_state.get("state") == "changed":
        raise AccountError("the lock changed — answer the question on Home first")
    uid = _fresh()["user"]["id"]
    status, rows = _rest("GET", "recovery", purpose="account", query="select=wrapped&limit=1")
    if status != 200 or not isinstance(rows, list):
        raise AccountError(f"lock: {_server_said(status, rows)}")
    if not rows:
        raise AccountError("this account has no recovery key — approve this PC from another device of yours")
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
    what it shows, ``same`` whether its person pressed Same code),
    ``changed`` (the account's lock is not the one this
    PC holds — ``changed`` says ``server`` and ``mine``, eight hex each,
    and ``refused`` once he said it was not him), or empty (no account,
    or not looked at yet); ``pending`` the other PCs waiting on this
    one (``twins`` on one that asked twice: nothing to approve);
    ``recovery`` whether the account holds a recovery key (None until
    asked); ``quiet`` while the lock is held unseen, both syncs off and
    no phone in the account, when Home does not ask for a recovery key."""
    st = _lock_state
    req = st.get("pairing")
    ch = st.get("changed") or None
    return {"state": str(st.get("state") or ""), "id": str(st.get("lock_id") or "")[:8],
            "code": str(req["code"]) if req else "",
            "same": bool(req and req.get("same")),
            "pending": [dict(r) for r in (st.get("pending") or [])],
            "recovery": st.get("recovery"), "error": str(st.get("error") or ""),
            "quiet": not _syncs_on() and not _device_names.get("phone"),
            "changed": ({"server": str(ch.get("server") or "")[:8], "mine": str(ch.get("mine") or "")[:8],
                         "refused": bool(ch.get("refused"))} if ch else None)}


# ------------------------------------------------------------ the devices
#
# A device of the account is a row of ``devices``: a PC or a phone, each
# writing only its own (PHONE_LINK_PLAN.md chapters 4.2 and 12). What the
# devices need of each other is the row's ``link``, sealed under the
# account key by phone.py: this module moves it and never reads it. A row
# that does not open is ignored over there, so the server cannot add a
# device; and a row that opens is not enough either, because a forgotten
# device still holds the key and the server could put its row back. So
# whoever presses Forget adds it to the ``forgotten`` row of ``vault``, and
# every PC keeps the union in a local file that never shrinks.

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _is_phone(row: dict) -> bool:
    where = str(row.get("platform") or "")
    return where.startswith("android-") or where == "web"


def _syncs_on() -> bool:
    return privacy.allowed("settings_sync") or privacy.allowed("history_sync")


def _has_phone() -> bool:
    """Does the account have a phone that was not forgotten? The devices
    table, believed for DEVICE_NAMES_TTL_S like the names beside it."""
    if not _devices_known():
        _names()
    return bool(_device_names.get("phone"))


def _may_ask() -> bool:
    """May a PC with no key ask to join? With a sync on it has something
    to wait for. With both off, only once the account has a phone: there
    the join is what lets the phone reach this PC. A device that was
    forgotten, or a person who pressed It was me, has asked already
    (``vault.confirmed``) and does not come through here."""
    return _syncs_on() or _has_phone()


def devices() -> list[dict]:
    """Every row of the account, with ``link`` as stored — sealed, and
    None on a device that has written none. Raises AccountError when the
    server answers anything else (a net error goes through as it is)."""
    status, rows = _rest("GET", "devices", purpose="account",
                         query="select=id,name,platform,app_version,tier,created_at,last_seen,link")
    if status != 200 or not isinstance(rows, list):
        raise AccountError(f"devices: {_server_said(status, rows)}")
    _know_devices(rows)
    return rows


def write_link(sealed: str) -> None:
    """This device's row, ``link`` in it, then the broadcast. ``sealed`` is
    vault.seal_json under vault.AAD_DEVICE and this module does not open
    it. A device on the forgotten list writes nothing."""
    text = str(sealed or "")
    if not vault.is_sealed(text):
        raise AccountError("a device's link must be sealed")
    uid = _fresh()["user"]["id"]
    mine = device_id()
    if mine in forgotten():
        raise AccountError("this device was forgotten")
    if _left():
        raise AccountError("this device left the account and still has its old certificate")
    status, data = _rest("POST", "devices", purpose="account", query="on_conflict=id",
                         payload={"id": mine, "user_id": uid, "name": device_name(),
                                  "platform": _platform(), "link": text},
                         prefer="resolution=merge-duplicates,return=minimal")
    if status not in (200, 201, 204):
        raise AccountError(f"the device row was refused ({_server_said(status, data)})")
    _broadcast(["devices"])


def _forgotten_file(uid: str):
    """One file per account: Delete my account takes its own and no
    other's."""
    return paths.SECRETS_DIR / f"forgotten-{uid}.json"


def _forgotten_rows(rows) -> list[dict]:
    """A list of forgotten devices as it is kept, whoever wrote it: one
    entry per device and certificate, ``device``, ``cert`` and ``at``. By
    the pair and not the device alone: a device that came back under the
    same id with another certificate and was forgotten again has two, and
    the door has to know both."""
    out: dict[tuple[str, str], dict] = {}
    for r in rows if isinstance(rows, list) else []:
        device = str(r.get("device") or "") if isinstance(r, dict) else ""
        if device:
            cert = str(r.get("cert") or "")
            out.setdefault((device, cert), {"device": device, "cert": cert,
                                            "at": str(r.get("at") or "")})
    return list(out.values())


def _read_forgotten(uid: str) -> list[dict] | None:
    """The local list; None when the file could not be opened this moment,
    which is not the same as empty: nothing may be written over it. A file
    that opened and is not a list will never read, and left in place it
    meant an empty answer and nothing ever repairing it, with the door
    open to every device on it. It is set aside, and the next account pass
    writes the account's list in its place (``_keep_forgotten``), soon."""
    path = _forgotten_file(uid)
    try:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a list of devices")
    except FileNotFoundError:
        return []
    except ValueError as e:
        log.warning("account: the list of forgotten devices is damaged and is set aside (%s)", e)
        try:
            os.replace(path, path.with_name(f"{path.name}.broken-{time.strftime('%Y%m%d-%H%M%S')}"))
        except OSError as moved:
            log.warning("account: the damaged list stayed where it is (%s)", moved)
            return None
        nudge()
        return []
    except OSError as e:
        log.warning("account: the list of forgotten devices could not be read (%s)", e)
        return None
    return _forgotten_rows(data.get("v"))


def _keep_forgotten(uid: str, rows: list[dict]) -> list[dict]:
    """``rows`` added to the account's local list, which only ever grows: it
    is what keeps a device out when the server restores a row or drops the
    account's list. Returns the whole list."""
    with _lock:
        have = _read_forgotten(uid)
        if have is None:
            return _forgotten_rows(rows)
        union = _forgotten_rows(have + rows)
        if len(union) > len(have):
            path = _forgotten_file(uid)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(f".json.{os.getpid()}.new")
                tmp.write_text(json.dumps({"v": union}, ensure_ascii=False, indent=2) + "\n",
                               "utf-8")
                os.replace(tmp, path)
            except OSError as e:
                log.warning("account: the list of forgotten devices could not be written (%s)", e)
        return union


def forgotten() -> set[str]:
    """Device ids and certificate fingerprints that stay out of the account
    signed in here: the local list, which holds the account's as of the
    last account pass, so this answers with no network and a door opens
    from it after a restart with the internet down. Nothing with nobody
    signed in: with no account there is nobody to let in."""
    out: set[str] = set()
    who = user()
    for row in (_read_forgotten(who["id"]) if who else None) or []:
        out.add(row["device"])
        if row["cert"]:
            out.add(row["cert"])
    return out


def _past_devices() -> set[str]:
    """The ids this PC had before the account forgot it, so what it said
    under them does not come back to it as another device's lines."""
    who = user()
    past = _per_account("account.past_devices").get((who or {}).get("id"))
    return {str(p) for p in past} if isinstance(past, list) else set()


def _later(a: str | None, b: str | None) -> str | None:
    """The later of two stamps, either of which may be missing."""
    stamps = [s for s in (a, b) if s]
    if not stamps:
        return None
    return max(stamps, key=lambda s: sync._parse_iso(s) or datetime.min.replace(tzinfo=timezone.utc))


def _history_floor(uid: str) -> str | None:
    """Where this PC's history stands as it leaves: what it pushed, or, with
    the cursor gone (the 401 that told it wiped them), everything it has.
    Those rows are on the account under the old id, and under the new one
    they would be new rows, every line doubled on every device. Kept in
    state.json, because ``sync.forget_all`` takes the cursors at every
    sign-out, and in the very sequence a Forget sets off."""
    import history
    pushed = sync.read_cursor().get("history_pushed_ts")
    if not pushed:
        try:
            pushed = sync.history_floor(history.all_events())
        except (OSError, ValueError) as e:
            log.info("account: this PC's history was not read as it left (%s)", e)
    return _later(pushed, _per_account("account.history_floor").get(uid))


def _account_forgotten(uid: str, key: bytes) -> list[dict]:
    """The account's ``forgotten`` row, opened; [] when there is none or it
    does not open. The server cannot add a name to it, and taking the row
    away gives nothing back: this PC keeps its own list."""
    status, rows = _rest("GET", "vault", purpose="account",
                         query=f"select=cipher&name=eq.{vault.FORGOTTEN_NAME}")
    if status != 200 or not isinstance(rows, list):
        raise AccountError(f"devices: {_server_said(status, rows)}")
    if not rows:
        return []
    try:
        inside = vault.open_json(key, str(rows[0].get("cipher") or ""),
                                 vault.AAD_VAULT.format(uid=uid, name=vault.FORGOTTEN_NAME))
    except vault.VaultError as e:
        log.info("account: the list of forgotten devices did not open (%s)", e)
        return []
    return _forgotten_rows(inside.get("v") if isinstance(inside, dict) else None)


def _write_forgotten(uid: str, key: bytes, rows: list[dict], theirs: list[dict]) -> None:
    """The union back on the account, when it holds something the row does
    not. One row under is_sealed()'s cap, about 40 devices: past that the
    oldest give way on the row, and stay on every PC that saw them."""
    kept = list(rows)
    while kept and not vault.fits_json({"v": kept}):
        kept.pop(0)
    if not ({(r["device"], r["cert"]) for r in kept}
            - {(r["device"], r["cert"]) for r in theirs}):
        return
    try:
        cipher = vault.seal_json(key, {"v": kept},
                                 vault.AAD_VAULT.format(uid=uid, name=vault.FORGOTTEN_NAME))
    except vault.VaultError as e:
        raise AccountError(f"the list of forgotten devices was not sealed ({e})") from e
    status, data = _rest("POST", "vault", purpose="account", query="on_conflict=user_id,name",
                         payload={"user_id": uid, "name": vault.FORGOTTEN_NAME, "cipher": cipher},
                         prefer="resolution=merge-duplicates,return=minimal")
    if status not in (200, 201, 204):
        raise AccountError(f"the list of forgotten devices was refused ({_server_said(status, data)})")


def _forgotten_pass(uid: str) -> bool:
    """The account's list against this PC's, both ways, and whether this
    PC is on it: at every account pass, and before this PC writes its row.
    Nothing without the key that opens it, and nothing while the lock is
    changed: the row would not open under a key the account does not name.
    It is written back only under a key the profile named: a sign-in reads
    before the lock is looked at, and a key the account moved on from would
    otherwise seal this PC's list over the account's. True when this PC
    found itself on the list and left. A PC with no key may be one that
    started to leave and stopped: its own list says so, and it finishes,
    or it would go on under the forgotten id, and write that row back."""
    key = vault.key(uid)
    if key is None or _lock_state.get("state") == "changed":
        mine = device_id()
        if any(r["device"] == mine for r in _read_forgotten(uid) or []):
            _leave(uid, mine, key)
            return True
        return False
    theirs = _account_forgotten(uid, key)
    union = _keep_forgotten(uid, theirs)
    if _lock_state.get("state") == "have" and _lock_state.get("lock_id") == vault.fingerprint(key):
        _write_forgotten(uid, key, union, theirs)
    mine = device_id()
    if any(r["device"] == mine for r in union):
        _leave(uid, mine, key)
        return True
    return False


def _leave(uid: str, old: str, key: bytes | None) -> None:
    """This PC is on the account's forgotten list: its key moves aside,
    its row is never written again, and it asks to join as a new device,
    under a new id and, through FORGOTTEN_HOOKS, a new certificate, because
    the list never lets the old ones back. The lock it will take a key for
    is the one it held, by the key's own fingerprint and never the server's
    column, and the key is kept, so nothing it could read before is lost if
    the same key comes back to it. What it already said stays under the old
    id (``_history_floor``). ``account.left`` is what finishes this in the
    app when a desk or the wizard noticed it (``settle_left``). ``key`` is
    None when an earlier try stopped after the key had gone: the state
    written below is what that try left undone."""
    log.warning("account: this PC was forgotten on another device — its key is set aside "
                "and it asks to join again as a new device")
    floor = _history_floor(uid)
    past = _per_account("account.past_devices")
    try:
        if key is not None:
            vault.set_aside(uid, vault.fingerprint(key), why="this PC was forgotten")
    except vault.VaultError as e:
        raise AccountError(f"this PC was forgotten and its key could not be set aside ({e})") from e
    also: dict = {"account.left": old,
                  "account.past_devices": {**past, uid: sorted(_past_devices() | {old})}}
    if floor:
        also["account.history_floor"] = {**_per_account("account.history_floor"), uid: floor}
    _new_device_id(uid, **also)
    _device_names.update(at=0.0, names={}, phone=False)
    _set_lock(state="", lock_id="", pairing=None, pending=[], changed=None)
    settle_left()


def _left() -> bool:
    return bool(_state().get("account.left"))


def settle_left() -> bool:
    """Finish a leaving (``_leave``): FORGOTTEN_HOOKS run, and the mark in
    state.json goes only once they all have. The process that notices may
    be the desk or the wizard, where nothing is registered, so the mark
    stays for the app, whose worker comes through here on every turn; a hook
    that trips leaves it for the next. Until then ``write_link`` refuses: a
    row under the new id must not carry the certificate the list names.
    True when nothing is left to do."""
    if not _left():
        return True
    hooks = list(FORGOTTEN_HOOKS)
    if not hooks:
        return False
    for hook in hooks:
        try:
            hook()
        except Exception:                                    # noqa: BLE001
            log.info("a forgotten hook tripped — it runs again at the next turn", exc_info=True)
            return False
    import config
    config.save({"account.left": None})
    return True


def _mine() -> str:
    """This device's id, for the one function with a parameter of that
    name."""
    return device_id()


def forget_device(device_id: str, cert: str) -> bool:
    """Forget, from this device: the target goes on the account's list and
    on this PC's first, so a failure further on leaves it forgotten and
    never the other way round; then the row and its session go on the
    server (``forget_device()``, migration 0007, effective at once through
    0006); then the others are told. ``cert`` is the SHA-256 of the
    device's certificate, "" for a device that never wrote one. A PC does
    not forget itself: that is Sign out. True when no session of that device
    is left, ended here or already over: a PC that signed out keeps its row.
    False is a device that never said which session it runs on, an older
    copy or one with its account gate shut, or one that named a session not
    this account's: it is off the list of devices and goes on working
    until Sign out of every PC, and whoever pressed Forget has to be told,
    in OLDER_COPY_WORDS."""
    target = str(device_id or "").strip()
    if not _UUID.fullmatch(target):
        raise AccountError("that is not a device of this account")
    if target == _mine():
        raise AccountError("this is the device you are on — sign out instead")
    uid = _fresh()["user"]["id"]
    with _sync_lock:
        key = vault.key(uid)
        if key is None or _lock_state.get("state") != "have":
            raise AccountError("this PC does not hold the account's key")
        theirs = _account_forgotten(uid, key)
        union = _keep_forgotten(uid, theirs + [{"device": target, "cert": str(cert or ""),
                                                "at": _now_iso()}])
        _write_forgotten(uid, key, union, theirs)
        status, data = _rest("POST", "rpc/forget_device", purpose="account",
                             payload={"target": target})
        if status not in (200, 204):
            raise AccountError(f"the server refused to forget it ({_server_said(status, data)})")
        ended = data is True
        _device_names["at"] = 0.0
    log.info("account: a device was forgotten on this PC%s", "" if ended else ", and it stays signed in")
    if not ended:
        _status["last_error"] = OLDER_COPY_WORDS
    _broadcast(["devices"])
    _run_account_hooks(key)
    return ended


def _run_account_hooks(key: bytes) -> None:
    for hook in list(ACCOUNT_HOOKS):
        try:
            hook(key)
        except Exception:                                    # noqa: BLE001
            log.debug("an account hook tripped", exc_info=True)


def account_pass(reason: str = "") -> dict:
    """What a signed-in copy does whatever its syncs say, with the
    ``account`` gate alone: the lock, the forgotten list, the profile, the
    requests to join, the devices' rows (ACCOUNT_HOOKS). No store moves.
    Until 2026-11-06 all of this lived in ``sync_now``, which returns at
    once with both syncs off, so a person who turned them off could not be
    reached at all. The lock comes first because the list is written back
    only under a key the profile named, and the list before the profile
    because a forgotten PC must not write its row. Never raises: each
    step's trouble is a word in the returned dict and a line in the log,
    and the next pass tries again."""
    out: dict[str, str] = {}
    if not configured() or not signed_in() or not privacy.allowed("account"):
        return out
    with _sync_lock:
        try:
            uid = _fresh()["user"]["id"]
            if vault.key(uid) is None:
                # before the lock: a leaving that stopped half way must
                # not ask to join under the id the account forgot
                _forgotten_pass(uid)
            _ensure_lock(uid)
            if _forgotten_pass(uid):
                _ensure_lock(uid)
            out["lock"] = str(_lock_state.get("state") or "not asked")
        except (AccountError, net.EgressRefused, net.NetError, vault.VaultError, OSError) as e:
            out["lock"] = f"error: {e}"
            _lock_state["error"] = str(e)[:200]
        if signed_in():
            try:
                ensure_profile()
            except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
                out["profile"] = f"error: {e}"
    key = None
    try:
        if signed_in():
            key = _lock_key(_fresh()["user"]["id"])
        if key is not None:
            out["requests"] = str(len(pending_pairings()))
        if signed_in() and not _syncs_on():
            _has_phone()                 # what Home's recovery row waits for
    except (AccountError, net.EgressRefused, net.NetError, OSError) as e:
        out["requests"] = f"error: {e}"
    if key is not None and signed_in():
        _run_account_hooks(key)
    errors = [f"{k}: {v[7:]}" for k, v in out.items() if v.startswith("error: ")]
    if errors:
        log.info("account pass%s: %s", f" ({reason})" if reason else "", "; ".join(errors))
    return out


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
    "device_name", "copy_name", "request_name", "ensure_profile", "sign_in_google", "sign_in_anonymous",
    "set_name", "sign_out", "delete_account", "sync_now", "drain_outbox", "queued",
    "start_worker", "nudge", "status", "forget_cache", "REPORT_COLUMNS",
    "REQUIRED", "SIGNED_OUT_HOOKS", "LIVE_ENABLED", "STORES", "stop_live",
    "PAIRING_HOOKS", "LOCK_HOOKS", "lock_status", "poll_lock", "pending_pairings",
    "approve_pairing", "decline_pairing", "make_recovery", "recover",
    "lock_answer", "restore_lock", "same_code", "account_pass", "ACCOUNT_HOOKS",
    "FORGOTTEN_HOOKS", "settle_left", "devices", "write_link", "forget_device", "forgotten",
]
