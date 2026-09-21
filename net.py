"""The one door out: every HTTP request the app makes leaves through here.

Until 2026-09-17 five modules opened their own sockets — ``urllib`` in
translate.py, visual_qa.py, lookup.py and notify_hook.py, ``httpx`` inside
the google-genai SDK (gone since the REST port, gemini_pool.Client) — and
the only way to know what the app talked to
was to read all of them. DISTRIBUTION_PLAN.md chapter 5.4 and decision
D12 ask for one chokepoint a stranger can read in ten minutes; this is
it. The rules, each of which a test in tests.py holds:

1. This is the only module in the product tree that imports a transport
   (``urllib.request``, ``http.client``, ``httpx``, ``socket``, ``ssl``).
   ``test_only_net_imports_transport`` is the grep.
2. ``ALLOWED_HOSTS`` is a frozen constant near the top of this file. A URL
   whose host is not in it (or under ``ALLOWED_SUFFIXES`` — Hugging
   Face's two domains, for the model CDN whose hostname moves) raises
   ``EgressRefused`` BEFORE any socket is opened, and the refusal is
   itself a row in the log, so the person sees what tried to leave.
   Loopback is the one host allowed in offline mode.
3. A secret is passed by NAME (``groq``, ``gemini``, ``phone_token``),
   never by value: this module resolves it through secretstore.py and
   attaches it in the header that provider expects, and only to the host
   that provider owns (``SECRET_HOSTS``). A caller may hand over its own
   bearer only for 127.0.0.1 — the phone token to our own listener.
4. A key never rides in a URL. Any query parameter named like one
   (``key``, ``token``, ...) is refused on every host.
5. After every call — answered, failed or refused — one row goes to the
   in-memory table (``rows()``, for the Dashboard's Network window) and
   to ``paths.NETWORK_LOG``: time, host, purpose, bytes up, bytes down,
   HTTP status or error class, secret NAME or ``-``, consent or ``-``.
   Never a body, never a header value, never a URL query string. The
   file rotates at 1 MB, three copies kept.

``purpose`` is one word from ``PURPOSES``: what feature asked. It is what
the Network window shows beside the host, and what the privacy gates of
chapter 5 (PR 5) will consult.

The one long-lived connection — the account's live channel, a websocket
(``websocket()`` below, 2026-09-20) — leaves through the same door
under the same five rules: admitted like a request, the publishable key
attached here, the session token injected by name into the one message
that carries it, and two rows in the table (opened, closed).

Gemini speaks REST through here too (gemini_pool.Client, plan 5.6): the
google-genai SDK, which owned its own httpx client and read the key from
the environment on its own, is gone, and with it the transport this
module used to build for it.
"""
from __future__ import annotations

import http.client
import logging
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque, namedtuple

import paths

log = logging.getLogger("app")

# ------------------------------------------------------------ the allowlist

LOOPBACK = "127.0.0.1"

#: Every host the app may open a connection to (DISTRIBUTION_PLAN.md 5.5;
#: the same table becomes NETWORK.md). Frozen: a feature that needs a new
#: host edits this constant, in a commit a reader can find.
ALLOWED_HOSTS: frozenset[str] = frozenset({
    LOOPBACK,                              # Ollama, the phone listener, the hook
    "generativelanguage.googleapis.com",   # Gemini
    "api.groq.com",                        # Groq
    "huggingface.co",                      # the Hebrew model download (D13)
    "cdn-lfs.huggingface.co",
    "cas-bridge.xethub.hf.co",
    "pypi.org",                            # GPU / Recording / Skin packs (ch. 6)
    "files.pythonhosted.org",
    "api.github.com",                      # update check + installer (ch. 11)
    "github.com",
    "objects.githubusercontent.com",
    # Where a release asset's download actually lands since 2026: the
    # first real check (v1.1.0, 2026-09-19) was refused here. Both names
    # are GitHub's, one per generation of its asset store.
    "release-assets.githubusercontent.com",
})

#: Hugging Face's download hosts, by DOMAIN: the Hub answers a model
#: file with a redirect to a CDN whose hostname changes by region and by
#: year — `cdn-lfs.huggingface.co`, `cas-bridge.xethub.hf.co`, and on
#: 2026-09-17 `us.aws.cdn.hf.co` — and every one of them sits under a
#: domain Hugging Face owns. A name-by-name list would refuse the next
#: rename and leave every new user without a model; a redirect off these
#: two domains is refused exactly as before. Nothing else gets a suffix.
ALLOWED_SUFFIXES: tuple[str, ...] = (".huggingface.co", ".hf.co")

#: ``<ref>.supabase.co`` — the one project of the optional account,
#: set by ``sb.configure`` from sb.py's two constants (chapter 8.7) and
#: refused until then. A suffix rule would admit any project, so it is a
#: value, and ``SECRET_HOSTS`` names it by this tag so one constant
#: changes. ``SUPABASE_KEY`` is the PUBLISHABLE key, public by design
#: (it is in the repo and in every install): this module attaches it as
#: the ``apikey`` header on every request to that host, because a caller
#: may not set that header itself (``_SECRET_HEADERS``) and the key is
#: not a secret to look up by name.
SUPABASE_HOST: str | None = None
SUPABASE_KEY: str | None = None
_SUPABASE = "<supabase>"


def configure_supabase(host: str | None, publishable_key: str | None) -> None:
    """Admit the project host and remember its publishable key. Only
    sb.py calls this, with its module constants; a test calls it with a
    fixture and puts it back."""
    global SUPABASE_HOST, SUPABASE_KEY
    host = (host or "").strip().lower() or None
    if host is not None and not host.endswith(".supabase.co"):
        raise ValueError(f"{host!r} is not a Supabase project host")
    key = (publishable_key or "").strip() or None
    if key is not None and not key.startswith("sb_publishable_"):
        raise ValueError("the Supabase key net.py attaches must be the "
                         "publishable one (sb_publishable_...)")
    SUPABASE_HOST, SUPABASE_KEY = host, key

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/"

#: Why a request is made — the closed vocabulary of 5.4, plus ``reading``
#: (the read-aloud writer, reading.py), ``notify`` (the Claude Code
#: hook's knock on our own listener) and ``summary`` (the one sentence
#: a "Claude finished" card carries instead of the message's first
#: lines, notify.Summary, 2026-09-21), which the plan's list predates.
PURPOSES: frozenset[str] = frozenset({
    "polish", "punctuate", "translate", "lookup", "review", "study",
    "reading", "ask-screen", "transcribe", "key-test", "catalog", "ollama",
    "notify", "summary", "model-download", "pack-install", "update-check",
    "update-download", "account", "report", "sync", "history",
})

#: secret name -> (the one host it may go to, header, how it is written).
#: A ``groq`` key can never be sent to Google, a ``gemini`` key never to
#: Groq, and neither ever to Supabase — by construction, not by review.
SECRET_HOSTS: dict[str, tuple[str | None, str, str]] = {
    "groq": ("api.groq.com", "Authorization", "Bearer {}"),
    "gemini": ("generativelanguage.googleapis.com", "x-goog-api-key", "{}"),
    "supabase_session": (_SUPABASE, "Authorization", "Bearer {}"),
    "phone_token": (LOOPBACK, "Authorization", "Bearer {}"),
}

#: Query parameter names a secret is sometimes smuggled in. Refused on
#: every host; the Google key rides in ``x-goog-api-key`` (5.6).
QUERY_NEVER: frozenset[str] = frozenset({
    "key", "api_key", "apikey", "token", "access_token",
})

#: Headers only this module may set on a remote host. The phone token to
#: our own listener is the one bearer a caller may hand over itself.
_SECRET_HEADERS: frozenset[str] = frozenset({
    "authorization", "x-goog-api-key", "x-api-key", "apikey",
})

#: A named User-Agent, and this is not cosmetic: Cloudflare in front of
#: some providers answers Python's default (Python-urllib/3.x) with 403
#: error 1010 "banned based on your browser's signature" — measured live
#: against api.cerebras.ai 2026-08-22. Any named client passes.
USER_AGENT = "deskit/1.0"

#: ``privacy.offline`` (5.9): everything but loopback is refused. Set by
#: ``privacy.configure`` from the settings; a module flag here so the
#: refusal is the transport's, not a feature's.
offline = False

#: The log rotates at this size; ``.1`` ``.2`` ``.3`` are kept.
LOG_MAX_BYTES = 1_000_000
LOG_KEEP = 3

DEFAULT_TIMEOUT_S = 30.0


# -------------------------------------------------------------- exceptions

class EgressRefused(Exception):
    """The request was not made: the host, the scheme, a key-shaped
    query parameter or offline mode. ``host`` and ``reason`` say why."""

    def __init__(self, host: str, reason: str, purpose: str = "-"):
        super().__init__(f"refused {purpose} -> {host}: {reason}")
        self.host, self.reason, self.purpose = host, reason, purpose


class DownloadError(Exception):
    """``download()`` did not finish. ``reason`` is one word for the
    code — offline, cancelled, refused, http, short, verify — and
    str(e) is the line for the log. The part file is kept for every
    reason but verify."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class Cancelled(DownloadError):
    def __init__(self):
        super().__init__("cancelled", "the download was paused")


class NetError(Exception):
    """The request was attempted and did not get an HTTP answer: no
    route, refused connection, timeout, TLS failure. ``reason`` is the
    one-line cause; the row in the log carries its class name."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class SecretMissing(NetError):
    """A request named a secret nothing holds. A feature that checked
    presence at construction meets this only if the key was deleted
    since — from Control Panel, say — and falls through like any error."""

    def __init__(self, name: str):
        super().__init__(f"no {name} key is stored")
        self.name = name


# ------------------------------------------------------------- the table

Row = namedtuple("Row", "when host purpose up down status secret consent")

#: The process's own history, newest last — what Dashboard > Network
#: paints. Bounded so a long-running copy never grows without limit.
ROWS: deque[Row] = deque(maxlen=1000)
_LOCK = threading.Lock()


def rows() -> list[Row]:
    """A snapshot of the in-memory table, oldest first."""
    with _LOCK:
        return list(ROWS)


def format_row(row: Row) -> str:
    """One line of network.log — the same eight fields, pipe-separated."""
    return " | ".join(str(f) for f in row)


def parse_row(line: str) -> Row | None:
    """A line of network.log back into a Row; None for a line that is
    not one (a torn tail, a blank)."""
    parts = [p.strip() for p in line.rstrip("\n").split(" | ")]
    if len(parts) != 8:
        return None
    try:
        return Row(parts[0], parts[1], parts[2], int(parts[3]), int(parts[4]),
                   parts[5], parts[6], parts[7])
    except ValueError:
        return None


def read_log(path=None, limit: int = 2000) -> list[Row]:
    """The rows of network.log (and its rotations, oldest first), the
    LAST `limit` of them — what Dashboard > Network paints. The dashboard
    is its own process, so the file is the record the app and it share;
    a missing file is an empty table."""
    path = paths.NETWORK_LOG if path is None else path
    out: list[Row] = []
    names = [path.with_name(f"{path.name}.{i}") for i in range(LOG_KEEP, 0, -1)] + [path]
    for name in names:
        try:
            with name.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    row = parse_row(line)
                    if row is not None:
                        out.append(row)
        except OSError:
            continue
    return out[-limit:]


def _rotate(path) -> None:
    """``network.log`` -> ``.1`` -> ``.2`` -> ``.3``; the oldest falls off.
    Another process (the hook) holding the file for a millisecond makes
    the rename fail — then this row simply lands in the big file and the
    next one tries again."""
    for i in range(LOG_KEEP, 0, -1):
        older = path.with_name(f"{path.name}.{i}")
        newer = path if i == 1 else path.with_name(f"{path.name}.{i - 1}")
        if newer.exists():
            older.unlink(missing_ok=True)
            newer.rename(older)


def _record(host: str, purpose: str, up: int, down: int, status,
            secret: str | None, consent: str | None) -> Row:
    """Append one row to the table and the file. Never raises: a log that
    cannot be written must not cost the reply it describes."""
    row = Row(time.strftime("%Y-%m-%d %H:%M:%S"), host, purpose, int(up),
              int(down), status, secret or "-", consent or "-")
    with _LOCK:
        ROWS.append(row)
        try:
            path = paths.NETWORK_LOG
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                if path.stat().st_size >= LOG_MAX_BYTES:
                    _rotate(path)
            except OSError:
                pass
            # path.open, not open(): this module's open() is the request.
            with path.open("a", encoding="utf-8") as fh:
                fh.write(format_row(row) + "\n")
        except Exception:                                    # noqa: BLE001
            log.debug("network.log row not written", exc_info=True)
    return row


# --------------------------------------------------------------- admission

def _host_allowed(host: str) -> bool:
    return (host in ALLOWED_HOSTS
            or host.endswith(ALLOWED_SUFFIXES)
            or (SUPABASE_HOST is not None and host == SUPABASE_HOST))


def _admit(url: str, purpose: str, secret: str | None,
           headers: dict | None, *, sdk: bool = False) -> tuple[str, str | None]:
    """Every check that happens BEFORE a socket exists. Returns the host
    and the consent that authorised the call (``kind@text_version``, or
    None for a purpose that needs none); raises ``EgressRefused`` (after
    writing the refused row) or ``ValueError`` for a caller's programming
    error."""
    if purpose not in PURPOSES:
        raise ValueError(f"unknown network purpose {purpose!r}")
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()

    def refuse(reason: str):
        _record(host or "?", purpose, 0, 0, "refused", secret, None)
        raise EgressRefused(host or "?", reason, purpose)

    if not host:
        refuse("no host in the URL")
    if not _host_allowed(host):
        refuse("host is not in net.ALLOWED_HOSTS")
    if offline and host != LOOPBACK:
        refuse("offline mode is on")
    # The scheme is admitted, not merely compared to https: the loopback
    # exemption below (Ollama speaks plain http) skipped the check entirely
    # for 127.0.0.1, so a `file://127.0.0.1/C:/...` URL passed admission and
    # urllib's own FileHandler read a local file through the one door meant
    # only for the network. Only http(s) may ever be opened here — file:,
    # ftp:, data: and the rest are refused on every host, loopback included.
    if parts.scheme not in ("https", "http"):
        refuse(f"{parts.scheme or 'no'} scheme is not http(s)")
    if parts.scheme != "https" and host != LOOPBACK:
        refuse(f"{parts.scheme or 'no'} scheme; only https leaves this PC")
    # The gate for the purpose (5.1): asked here for EVERY remote call,
    # not only at construction, so a consent withdrawn from the dashboard
    # — another process — stops the next request without a restart.
    consent = None
    if host != LOOPBACK:
        import privacy

        kind = privacy.kind_for(purpose)
        if kind is not None:
            try:
                consent = privacy.require(kind)
            except privacy.ConsentRequired as e:
                refuse(f"no consent for {kind}: {e.why}")
    for name, _value in urllib.parse.parse_qsl(parts.query,
                                               keep_blank_values=True):
        if name.lower() in QUERY_NEVER:
            refuse(f"query parameter {name!r} looks like a key")
    if secret is not None:
        if secret not in SECRET_HOSTS:
            raise ValueError(f"unknown secret name {secret!r}")
        allowed_host = SECRET_HOSTS[secret][0]
        if allowed_host == _SUPABASE:
            allowed_host = SUPABASE_HOST
        if allowed_host is None or host != allowed_host:
            refuse(f"the {secret} secret may only go to "
                   f"{allowed_host or 'a host not yet configured'}")
    if not sdk and host != LOOPBACK:
        for key in headers or {}:
            if key.lower() in _SECRET_HEADERS:
                refuse(f"caller-supplied {key} header; pass secret=<name>")
    return host, consent


def _resolve(secret: str) -> str:
    """The stored value for a secret NAME — looked up here, attached
    here, and forgotten with the request."""
    import secretstore

    try:
        if secret in secretstore.CRED_NAMES:
            value, _source = secretstore.find_key(secret)
        else:
            value = secretstore.get(secret)
    except Exception as e:                                   # noqa: BLE001
        raise SecretMissing(secret) from e
    if secret == "supabase_session" and value:
        # The blob is the whole session (chapter 8.6: access token,
        # refresh token, expiry, the user); what rides in the header is
        # its access token and nothing else.
        import json

        try:
            value = str(json.loads(value).get("access_token") or "")
        except (ValueError, AttributeError):
            value = ""
    if not value:
        raise SecretMissing(secret)
    return value


# ------------------------------------------------------------ the transport

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx is returned as a status, never followed: a redirect is how
    an allowlisted host could send a request somewhere unlisted."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _connect(method: str, url: str, headers: dict, body: bytes | None,
             timeout_s: float):
    """Open the socket. The one seam a test replaces: it returns the raw
    response (an ``HTTPError`` counts — a status is an answer) or raises
    ``NetError`` for everything that never got one."""
    req = urllib.request.Request(url, data=body, headers=headers,
                                 method=method.upper())
    try:
        return _OPENER.open(req, timeout=timeout_s)
    except urllib.error.HTTPError as e:
        return e
    except urllib.error.URLError as e:
        reason = e.reason
        raise NetError(str(reason)) from (
            reason if isinstance(reason, BaseException) else e)
    except (OSError, http.client.HTTPException, socket.timeout) as e:
        raise NetError(str(e) or type(e).__name__) from e


class Response:
    """What ``open()`` hands back: status, headers, and the body either
    whole (``read()``) or a line at a time (iteration), the way Ollama's
    streaming callers already consume it. Counting bytes as they pass is
    what lets the row say how much came down; the row is written when
    the response is closed, which the ``with`` does — or a watchdog
    thread does early, and either way exactly once."""

    def __init__(self, raw, host: str, purpose: str, up: int,
                 secret: str | None, consent: str | None):
        self._raw = raw
        self.status = int(getattr(raw, "status", None)
                          or getattr(raw, "code", 0) or 0)
        self.headers = getattr(raw, "headers", None) or {}
        self._host, self._purpose, self._up = host, purpose, up
        self._secret, self._consent = secret, consent
        self._down = 0
        self._closed = False
        self._close_lock = threading.Lock()

    def read(self) -> bytes:
        data = self._raw.read()
        self._down += len(data)
        return data

    def text(self) -> str:
        return self.read().decode("utf-8", "replace")

    def __iter__(self):
        for line in self._raw:
            self._down += len(line)
            yield line

    def chunks(self, size: int = 1 << 18):
        """The body in pieces of `size` bytes — a download that reports
        progress and hashes as it goes (updates.py), counted like read()."""
        while True:
            chunk = self._raw.read(size)
            if not chunk:
                return
            self._down += len(chunk)
            yield chunk

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._raw.close()
        except Exception:                                    # noqa: BLE001
            pass
        _record(self._host, self._purpose, self._up, self._down,
                self.status, self._secret, self._consent)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def open(method: str, url: str, purpose: str, *, secret: str | None = None,  # noqa: A001
         headers: dict | None = None, body: bytes | None = None,
         timeout_s: float = DEFAULT_TIMEOUT_S,
         consent: str | None = None) -> Response:
    """Admit, attach, connect. Use as ``with net.open(...) as r:`` when
    the body is streamed; ``request()`` below for the whole thing.

    Raises ``EgressRefused`` before connecting, ``SecretMissing`` when
    ``secret`` names an empty store, ``NetError`` when the connection
    fails. An HTTP error status is NOT an exception: it comes back as
    ``r.status`` with the provider's body readable, because a 429 or a
    404 is an answer the caller parses.
    """
    host, granted = _admit(url, purpose, secret, headers)
    consent = consent or granted
    hdrs = {str(k): str(v) for k, v in (headers or {}).items()}
    hdrs.setdefault("User-Agent", USER_AGENT)
    if SUPABASE_HOST is not None and host == SUPABASE_HOST and SUPABASE_KEY:
        # The publishable key, on every request to the one project host
        # and nowhere else; it names the project, it opens nothing (every
        # table's anon grant is revoked, supabase/migrations/0001_init.sql).
        hdrs["apikey"] = SUPABASE_KEY
    if secret is not None:
        _host, header, shape = SECRET_HOSTS[secret]
        hdrs[header] = shape.format(_resolve(secret))
    up = len(body) if body else 0
    try:
        raw = _connect(method, url, hdrs, body, timeout_s)
    except NetError as e:
        cause = e.__cause__
        _record(host, purpose, up, 0,
                type(cause).__name__ if cause is not None else "NetError",
                secret, consent)
        raise
    return Response(raw, host, purpose, up, secret, consent)


def request(method: str, url: str, purpose: str, *,
            secret: str | None = None, headers: dict | None = None,
            body: bytes | None = None, timeout_s: float = DEFAULT_TIMEOUT_S,
            consent: str | None = None) -> tuple[int, object, bytes]:
    """The whole exchange: ``(status, headers, body_bytes)``."""
    with open(method, url, purpose, secret=secret, headers=headers,
              body=body, timeout_s=timeout_s, consent=consent) as r:
        data = r.read()
        return r.status, r.headers, data


def post_json(url: str, purpose: str, payload: dict, *,
              secret: str | None = None, headers: dict | None = None,
              timeout_s: float = DEFAULT_TIMEOUT_S,
              consent: str | None = None) -> tuple[int, object, bytes]:
    """``request("POST", ...)`` with a JSON body — what every chat
    endpoint the app talks to takes."""
    import json

    hdrs = {"Content-Type": "application/json", **(headers or {})}
    return request("POST", url, purpose, secret=secret, headers=hdrs,
                   body=json.dumps(payload).encode("utf-8"),
                   timeout_s=timeout_s, consent=consent)


# -------------------------------------------------------------- websocket
# One long-lived connection, for the account's live channel (sb.py, the
# owner's ask of 2026-09-20: "I sync and within two seconds it is on the
# other PC"): Supabase Realtime is a websocket, and a websocket is a
# socket, so it is opened HERE and nowhere else (rule 1). The same
# admission as a request (rule 2: the host, the scheme, offline, the
# gate for the purpose), the publishable key attached here (rule 3), the
# session token injected here by NAME into the one message the protocol
# wants it in, and two rows in the table (rule 5): one when the
# connection opens (status 101) and one when it closes, with the bytes
# that went each way. RFC 6455 client side is a hundred lines of
# stdlib; a websocket package would be a transport of its own.

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WS_MAX_FRAME = 4 * 1024 * 1024


def _ws_connect(host: str, port: int, timeout_s: float):
    """The TLS socket, connected — the one seam a test replaces with a
    socket of its own (the fake server sits on the other end)."""
    import ssl

    raw = socket.create_connection((host, port), timeout=timeout_s)
    try:
        return ssl.create_default_context().wrap_socket(raw, server_hostname=host)
    except Exception:
        raw.close()
        raise


def _ws_frame(opcode: int, data: bytes) -> bytes:
    """One masked client frame (the RFC's rule: every client frame is
    masked, with a fresh mask)."""
    import os
    import struct

    head = bytes([0x80 | opcode])
    n = len(data)
    if n < 126:
        head += bytes([0x80 | n])
    elif n < 65536:
        head += bytes([0x80 | 126]) + struct.pack("!H", n)
    else:
        head += bytes([0x80 | 127]) + struct.pack("!Q", n)
    mask = os.urandom(4)
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data))


class Socket:
    """An open websocket. ``send_text`` and ``recv_text`` carry whole
    text messages; a ping from the server is answered here; ``close``
    sends the close frame, closes the socket and writes the row."""

    def __init__(self, sock, host: str, purpose: str, consent: str | None):
        self._sock = sock
        self.host = host
        self.purpose = purpose
        self.consent = consent
        self.up = 0
        self.down = 0
        self._buf = b""
        self._parts: list[bytes] = []
        self._closed = False
        self._send_lock = threading.Lock()

    # -- out
    def _send(self, opcode: int, data: bytes) -> None:
        frame = _ws_frame(opcode, data)
        with self._send_lock:
            if self._closed:
                raise NetError("the websocket is closed")
            try:
                self._sock.sendall(frame)
            except OSError as e:
                raise NetError(str(e) or type(e).__name__) from e
            self.up += len(frame)

    def send_text(self, text: str, *, secret: str | None = None,
                  placeholder: str = "{secret}") -> None:
        """Send one text message. With ``secret``, the stored value of
        that NAME replaces ``placeholder`` in the text here, on the way
        out — the caller never holds it — and only when the secret's
        one host is this socket's host (rule 3, as for a header)."""
        if secret is not None:
            if secret not in SECRET_HOSTS:
                raise ValueError(f"unknown secret name {secret!r}")
            allowed = SECRET_HOSTS[secret][0]
            if allowed == _SUPABASE:
                allowed = SUPABASE_HOST
            if allowed is None or self.host != allowed:
                raise EgressRefused(self.host, f"the {secret} secret may only go to "
                                    f"{allowed or 'a host not yet configured'}", self.purpose)
            text = text.replace(placeholder, _resolve(secret))
        self._send(0x1, text.encode("utf-8"))

    # -- in
    def _read_more(self, timeout_s: float) -> bool:
        """More bytes into the buffer; False on a timeout."""
        self._sock.settimeout(timeout_s)
        try:
            chunk = self._sock.recv(65536)
        except socket.timeout:
            return False
        except OSError as e:
            raise NetError(str(e) or type(e).__name__) from e
        if not chunk:
            raise NetError("the server closed the websocket")
        self._buf += chunk
        self.down += len(chunk)
        return True

    def _frame(self):
        """One complete frame off the buffer as (fin, opcode, payload),
        or None when the buffer holds less than a frame."""
        import struct

        buf = self._buf
        if len(buf) < 2:
            return None
        fin = bool(buf[0] & 0x80)
        opcode = buf[0] & 0x0F
        masked = bool(buf[1] & 0x80)
        n = buf[1] & 0x7F
        pos = 2
        if n == 126:
            if len(buf) < 4:
                return None
            n = struct.unpack("!H", buf[2:4])[0]
            pos = 4
        elif n == 127:
            if len(buf) < 10:
                return None
            n = struct.unpack("!Q", buf[2:10])[0]
            pos = 10
        if n > WS_MAX_FRAME:
            raise NetError(f"a websocket frame of {n} bytes")
        if masked:
            pos += 4                        # a server never masks; tolerated
        if len(buf) < pos + n:
            return None
        payload = buf[pos:pos + n]
        if masked:
            mask = buf[pos - 4:pos]
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._buf = buf[pos + n:]
        return fin, opcode, payload

    def recv_text(self, timeout_s: float) -> str | None:
        """The next text message, or None when ``timeout_s`` passes
        without one. Pings are answered, a close frame raises
        ``NetError`` after the socket is closed."""
        deadline = time.monotonic() + timeout_s
        while True:
            frame = self._frame()
            if frame is None:
                left = deadline - time.monotonic()
                if left <= 0 or not self._read_more(max(left, 0.01)):
                    return None
                continue
            fin, opcode, payload = frame
            if opcode == 0x8:                                # close
                self.close("closed by the server")
                raise NetError("the server closed the websocket")
            if opcode == 0x9:                                # ping
                self._send(0xA, payload)
                continue
            if opcode == 0xA:                                # pong
                continue
            if opcode in (0x1, 0x2, 0x0):
                self._parts.append(payload)
                if not fin:
                    continue
                whole = b"".join(self._parts)
                self._parts = []
                if opcode == 0x2:
                    continue                                 # binary: not spoken here
                return whole.decode("utf-8", errors="replace")

    def close(self, status: str = "closed") -> None:
        """Best-effort close frame, the socket shut, the row written —
        once, whichever side asked first."""
        with self._send_lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._sock.sendall(_ws_frame(0x8, b"\x03\xe8"))
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
        _record(self.host, self.purpose, self.up, self.down, status, None, self.consent)

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False


def websocket(url: str, purpose: str, *, headers: dict | None = None,
              timeout_s: float = DEFAULT_TIMEOUT_S) -> Socket:
    """Admit, attach, connect, upgrade: an open ``Socket`` for a
    ``wss://`` URL, or ``EgressRefused`` / ``NetError`` — the same
    answers as ``open()``. Only ``wss``: a websocket that is not TLS
    does not leave this PC."""
    import base64
    import hashlib
    import os

    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "wss":
        _record((parts.hostname or "?").lower(), purpose, 0, 0, "refused", None, None)
        raise EgressRefused((parts.hostname or "?").lower(),
                            f"{parts.scheme or 'no'} scheme; a websocket leaves only as wss",
                            purpose)
    host, consent = _admit(urllib.parse.urlunsplit(("https",) + tuple(parts[1:])),
                           purpose, None, headers)
    port = parts.port or 443
    hdrs = {str(k): str(v) for k, v in (headers or {}).items()}
    hdrs.setdefault("User-Agent", USER_AGENT)
    if SUPABASE_HOST is not None and host == SUPABASE_HOST and SUPABASE_KEY:
        hdrs["apikey"] = SUPABASE_KEY
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    lines = [f"GET {target} HTTP/1.1", f"Host: {host}", "Upgrade: websocket",
             "Connection: Upgrade", f"Sec-WebSocket-Key: {key}",
             "Sec-WebSocket-Version: 13"]
    lines += [f"{k}: {v}" for k, v in hdrs.items()]
    request_bytes = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")
    try:
        sock = _ws_connect(host, port, timeout_s)
    except OSError as e:
        _record(host, purpose, 0, 0, type(e).__name__, None, consent)
        raise NetError(str(e) or type(e).__name__) from e
    try:
        sock.sendall(request_bytes)
        sock.settimeout(timeout_s)
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(4096)
            if not chunk:
                raise NetError("the server hung up during the websocket handshake")
            head += chunk
            if len(head) > 65536:
                raise NetError("a websocket handshake answer over 64 KB")
        head, _, rest = head.partition(b"\r\n\r\n")
        status_line, *header_lines = head.decode("latin-1").split("\r\n")
        status = int(status_line.split(" ", 2)[1]) if len(status_line.split(" ")) > 1 else 0
        if status != 101:
            _record(host, purpose, len(request_bytes), len(head), status, None, consent)
            sock.close()
            raise NetError(f"the websocket was refused: HTTP {status}")
        got = {k.strip().lower(): v.strip() for k, _, v in
               (line.partition(":") for line in header_lines)}
        want = base64.b64encode(hashlib.sha1((key + WS_GUID).encode("ascii")).digest()).decode("ascii")
        if got.get("sec-websocket-accept") != want:
            _record(host, purpose, len(request_bytes), len(head), "bad-accept", None, consent)
            sock.close()
            raise NetError("the websocket handshake did not check out")
    except (OSError, socket.timeout) as e:
        sock.close()
        _record(host, purpose, len(request_bytes), 0, type(e).__name__, None, consent)
        raise NetError(str(e) or type(e).__name__) from e
    ws = Socket(sock, host, purpose, consent)
    ws.up = len(request_bytes)
    ws.down = len(head) + 4
    ws._buf = rest
    _record(host, purpose, ws.up, ws.down, 101, None, consent)
    return ws


# --------------------------------------------------------------- download

DOWNLOAD_CHUNK = 256 * 1024
DOWNLOAD_HOPS = 4
DOWNLOAD_TIMEOUT_S = 60.0
PART = ".part"


def _human(n: int) -> str:
    n = int(n)
    if n >= 1_000_000_000:
        return f"{n / 1e9:.2f} GB"
    if n >= 1_000_000:
        return f"{n / 1e6:.0f} MB"
    if n >= 1_000:
        return f"{n / 1e3:.1f} kB"
    return f"{n} B"


def download(url: str, dest, purpose: str, *, size: int | None = None,
             sha256: str | None = None, progress=None, cancel=None,
             base: int = 0, total: int | None = None):
    """A file to ``dest``, resumed from where the last attempt left it.

    The bytes go to ``<dest>.part``; a second attempt asks for the rest
    with a Range header (a 206 continues, a 200 to a ranged ask means
    the server never heard of resuming and the file starts over); every
    redirect — absolute or relative — is followed by hand, so each hop
    meets the allowlist above and is a row of its own. The part survives
    every failure but a hash that does not match, which is deleted and
    said: nothing half-right is left behind with the right name.

    ``progress(done, total)`` gets bytes as they land — ``base`` is what
    earlier files of a set add, ``total`` the set's whole size, both
    defaulting to this one file. ``cancel`` is a threading.Event; set,
    the next chunk raises ``Cancelled`` (a DownloadError) and the part
    stays. Raises ``DownloadError`` for everything else; returns
    ``dest``. The models and the packs come down this way (chapter 6).
    """
    import hashlib
    import urllib.parse

    from pathlib import Path as _Path
    dest = _Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + PART)
    have = part.stat().st_size if part.exists() else 0
    if size is not None and have >= size:
        part.unlink()
        have = 0
    whole = total if total is not None else (size or 0)
    headers = {"Range": f"bytes={have}-"} if have else {}
    name = dest.name
    for _hop in range(DOWNLOAD_HOPS):
        try:
            r = open("GET", url, purpose, headers=headers, timeout_s=DOWNLOAD_TIMEOUT_S)
        except EgressRefused as err:
            raise DownloadError("refused", str(err)) from err
        except NetError as err:
            host = urllib.parse.urlsplit(url).hostname
            raise DownloadError("offline", f"no connection to {host}: {err}") from err
        with r:
            if r.status in (301, 302, 303, 307, 308):
                where = str(r.headers.get("Location") or "")
                if not where:
                    raise DownloadError("http", f"{name}: a redirect with no Location")
                url = urllib.parse.urljoin(url, where)
                continue
            if r.status == 200:
                mode, have = "wb", 0          # the whole file, asked or not
            elif r.status == 206:
                mode = "ab"
            else:
                host = urllib.parse.urlsplit(url).hostname
                raise DownloadError("http", f"{name}: HTTP {r.status} from {host}")
            try:
                with part.open(mode) as f:
                    for chunk in r.chunks(DOWNLOAD_CHUNK):
                        if cancel is not None and cancel.is_set():
                            raise Cancelled()
                        f.write(chunk)
                        have += len(chunk)
                        if progress is not None:
                            progress(base + (min(have, size) if size else have),
                                     whole if whole else have)
            except DownloadError:
                raise
            except Exception as err:                        # noqa: BLE001
                # the stream broke under us: the part stays, the next
                # attempt asks for the rest
                raise DownloadError("offline", f"{name}: the connection dropped after "
                                    f"{_human(have)} ({err})") from err
            break
    else:
        raise DownloadError("http", f"{name}: too many redirects")
    if size is not None and have != size:
        raise DownloadError("short", f"{name}: {_human(have)} of {_human(size)} arrived")
    if sha256 is not None:
        digest = hashlib.sha256()
        with part.open("rb") as f:
            while True:
                block = f.read(1 << 20)
                if not block:
                    break
                digest.update(block)
        got = digest.hexdigest()
        if got != sha256.lower():
            part.unlink(missing_ok=True)
            log.warning("download: %s did not match its checksum and was discarded "
                        "(got %s, expected %s)", name, got, sha256)
            raise DownloadError("verify", f"{name}: the download did not match its "
                                "checksum and was discarded; try again")
    part.replace(dest)
    return dest
