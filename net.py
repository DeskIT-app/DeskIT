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
   whose host is not in it raises ``EgressRefused`` BEFORE any socket is
   opened, and the refusal is itself a row in the log, so the person sees
   what tried to leave. Loopback is the one host allowed in offline mode.
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
})

#: ``<ref>.supabase.co`` — set in phase 3 with the project ref; refused
#: until then. A suffix rule would admit any project, so it is a value,
#: and ``SECRET_HOSTS`` names it by this tag so one constant changes.
SUPABASE_HOST: str | None = None
_SUPABASE = "<supabase>"

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/"

#: Why a request is made — the closed vocabulary of 5.4, plus ``reading``
#: (the read-aloud writer, reading.py) and ``notify`` (the Claude Code
#: hook's knock on our own listener), which the plan's list predates.
PURPOSES: frozenset[str] = frozenset({
    "polish", "punctuate", "translate", "lookup", "review", "study",
    "reading", "ask-screen", "transcribe", "key-test", "catalog", "ollama",
    "notify", "model-download", "pack-install", "update-check",
    "update-download", "account", "report", "sync",
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
    return host in ALLOWED_HOSTS or (SUPABASE_HOST is not None
                                     and host == SUPABASE_HOST)


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
