"""Phone -> this PC transcription endpoint: what the DeskIT keyboard talks to.

The point is to dictate from the phone WITHOUT giving up the thing that
makes the desktop app good: the ivrit-ai fine-tune on the GPU (10.8% WER,
0.38 s, no quota). So the phone records and this machine transcribes.

It runs as a thread inside the running app and borrows the transcriber
that is already loaded. A separate process would load the same two models
again — about 3.2 GB of VRAM and ~25 s of startup for no benefit.

TWO DOORS, EACH WITH ONE JOB, one set of routes behind them (`Routes`,
PHONE_LINK_PLAN.md §6.4), so `/translate` and the rest exist once and
each door has a table of what it answers.

The LOOPBACK door, `PhoneServer`: 127.0.0.1, plain HTTP, the bearer token.
It is this PC's own: the Claude hook's `/notify`, and `tailscale serve`
until the phone plan's stage 6. It runs while the phone switch is on OR the
hook is connected, so a stranger's hook does not post into nothing, and with
the switch off it answers the hook and nothing else (`HOOK_ROUTES`). Binding
loopback is load-bearing: `tailscale serve` proxies to localhost, and any
other address would put a token-guarded, un-throttled socket in front of
the house.

The PHONE door, `PhoneDoor`: every interface, TLS, a client certificate the
account lists. net.serve_tls opens it, because net.py alone may use ssl
and socket (the one `import socket` here is the loopback listener's
exclusive-bind option), and it has checked the peer before a
line of http.server runs: no unauthenticated byte ever reaches this file.
There is no bearer on it and no `/notify`; the phone has never called that
route. It opens only once the account has a phone, the switch is on, this
PC gave its one yes and the person's yes to the account stands
(main.App._doors).

The client is the Android keyboard (android/), and only that. There used
to be a Hebrew web page at `/` that drove the same routes from a phone
browser, and an `/app.apk` route that served the debug build out of the
source tree; both retired on 2026-09-19 (12.11): the page was the reason
Tailscale's certificate was mandatory (getUserMedia wants a secure
context), and an end user has no Gradle to build an APK from — the
keyboard is a release asset on GitHub, later Play. Anything asking for
either is a 404 now.

One GET is open without the token on the loopback door — `/health`, which
says `{ok, version}` and nothing else (which engine is loaded is not for
whoever can reach the port). `/api/version` (12.9), the keyboard-build
facts, wants the bearer like every other route, and `/review` always did.

A BUSY PORT FALLS THROUGH, PORT_TRIES of them, and lands in state.json.
Nothing else in the app knows a port by heart: notify_hook reads the state
file, and a phone reads its `link` row.
"""
from __future__ import annotations

import errno
import json
import logging
import os
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import paths

log = logging.getLogger("app")

APP_DIR = Path(__file__).resolve().parent
#: Where the token lived until 2026-09-17, a plaintext file beside the
#: code. load_token() carries one it finds there into the secret store
#: once and deletes it; nothing writes it any more (D3).
TOKEN_FILE = paths.PHONE_TOKEN

#: The oldest keyboard build this PC still speaks with, as a version
#: (12.9): raised when a route the phone uses changes shape, so an old
#: keyboard is told to update instead of failing in the middle of a
#: sentence. 1.1.0 is the first build that reads /health as {ok, version}
#: and asks /api/version at all — everything before it was the owner's
#: own com.yoav.dictation, which never left his phone.
IME_MIN = "1.1.0"


def pc_version() -> str:
    """The VERSION file's line, or "0" when it cannot be read — the
    phone's `/health` and `/api/version` must answer either way."""
    try:
        import version
        return version.VERSION
    except Exception:                          # noqa: BLE001
        return "0"


def ime_code(text: str) -> int:
    """A version as the keyboard's versionCode: MAJOR*10000 + MINOR*100
    + PATCH, the one line android/app/build.gradle.kts computes from the
    same VERSION file (12.9) — kept here in the same words so the PC and
    the build cannot disagree about what 1.1.0 is."""
    import version
    major, minor, patch, _beta = version.parse(text)
    return major * 10000 + minor * 100 + patch


def api_version() -> dict:
    """What `GET /api/version` answers (12.9): the PC's version, the
    oldest keyboard build it accepts and the newest it knows of (as
    versionCodes), and where to get the newest. This build's own values:
    the newest keyboard is the one built from the same VERSION and lives
    at the release's asset (12.8's name), the Play page is "" until Play
    is live, and the APK's digest is "" until the update feed carries it
    (11.3 gains apk_url / apk_sha256 / ime_version_code / play_url with
    the release that ships a keyboard; the last successful check will
    overlay these then)."""
    import updates
    v = pc_version()
    try:
        latest = ime_code(v)
    except ValueError:                         # an unreadable VERSION
        latest = 0
    least = ime_code(IME_MIN)
    if latest and least > latest:              # never ask for more than exists
        least = latest
    return {"pc": v, "ime_min": least, "ime_latest": latest,
            "apk_url": f"https://github.com/{updates.REPO}/releases/download/v{v}/DeskIT-{v}.apk",
            "apk_sha256": "", "play_url": ""}

# Bodies are speech, not uploads. A minute of Opus is ~100 KB; this is a
# sanity bound so a stray POST cannot buffer a gigabyte into memory.
MAX_BODY = 32 * 1024 * 1024


def load_token() -> str:
    """Read the shared secret, generating it on first run.

    Generated rather than configured because a token the user has to
    invent is a token that ends up being "1234" — and this one is never
    typed by hand anyway: it travels in the URL the log prints.

    It lives in the secret store (``secrets\phone_token.bin``, DPAPI,
    this Windows account only). A ``server_token.txt`` left by an older
    version is read ONCE, stored, and deleted — the same token, so the
    phone that bookmarked it keeps working.
    """
    import secretstore
    try:
        token = secretstore.get("phone_token")
    except secretstore.SecretError as e:
        log.warning("phone token: %s — generating a new one", e)
        token = None
    if token:
        return token
    legacy = None
    try:
        legacy = TOKEN_FILE.read_text("utf-8").strip() or None
    except OSError:
        pass
    token = legacy or secrets.token_urlsafe(24)
    secretstore.set("phone_token", token)
    if legacy and secretstore.get("phone_token") == legacy:
        try:
            TOKEN_FILE.unlink()
            log.info("moved the phone token from %s into %s (DPAPI)",
                     TOKEN_FILE.name, secretstore.blob_path("phone_token").name)
        except OSError as e:
            log.warning("phone token copied into the secret store but %s "
                        "could not be deleted: %s", TOKEN_FILE.name, e)
    elif not legacy:
        log.info("generated a new phone token in %s",
                 secretstore.blob_path("phone_token").name)
    return token


def to_wav(raw: bytes) -> tuple[bytes, float]:
    """Whatever the phone posted -> (16 kHz mono WAV, seconds), what the
    transcriber and its language detector expect. The keyboard posts
    16 kHz WAV, which pcm.py reads with the standard library; another
    container (the retired web page's webm/opus) needs PyAV, which the
    installed copy has only with the Recording pack — pcm.NotWav then
    carries the sentence and the route answers 415 (13.4, D24)."""
    import numpy as np

    import pcm
    from recorder import frames_to_wav

    audio = pcm.to_float32(raw, 16000)
    samples = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    return frames_to_wav([samples], 16000), len(samples) / 16000.0


#: route -> the method of Routes that answers it, one table per door: a
#: route that is not in a door's table does not exist there. A table rather
#: than a chain of `if route ==`, because the chain was already carrying its
#: own bugs by the third entry: the allow-list and the dispatch were two
#: separate lists that had to agree, and the 401 named /transcribe whatever
#: had actually been called.
LOOPBACK_ROUTES: dict[str, str] = {
    "/health": "_do_health",
    "/api/version": "_do_version",
    "/review": "_do_review_pending",
    "/transcribe": "_do_transcribe",
    "/translate": "_do_translate",
    "/punctuate": "_do_punctuate",
    "/notify": "_do_notify",
    "/review/decide": "_do_review_decide",
    "/lookup": "_do_lookup",
}
#: The phone door's: everything but /notify, which the keyboard has never
#: called and which puts a card on his screen.
PHONE_ROUTES: dict[str, str] = {r: n for r, n in LOOPBACK_ROUTES.items() if r != "/notify"}
#: The loopback door's with the phone switch off: it stands then only for
#: Claude's hook, and everything else that comes to it, the old road through
#: `tailscale serve` included, finds nothing.
HOOK_ROUTES: dict[str, str] = {r: LOOPBACK_ROUTES[r] for r in ("/health", "/notify")}
#: The routes that take no body.
GET_ROUTES: frozenset[str] = frozenset({"/health", "/api/version", "/review"})
#: The one route open without the bearer on the loopback door.
OPEN_ROUTES: frozenset[str] = frozenset({"/health"})


class _Answer(Exception):
    """A route's answer from the middle of it: a body that was not JSON."""

    def __init__(self, status: int, payload: dict) -> None:
        super().__init__(status)
        self.status, self.payload = status, payload


def _text_body(raw: bytes) -> dict:
    """The JSON body of a text route, or the 400 that says it is not."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise _Answer(400, {"error": "expected JSON with a text field"}) from None
    if not isinstance(payload, dict):
        raise _Answer(400, {"error": "expected JSON with a text field"})
    return payload


class Routes:
    """Every route, once. ``handle(route, body, phone)`` answers ``(status,
    payload)``: nothing here reads a socket, so the two HTTP doors call it
    and the phone's direct road can too (§6.4). ``phone`` is who came in,
    `net.Peer`, or None on the loopback door. Each callable is optional: a
    caller without one gets a 503 on its route and everything else
    unchanged."""

    def __init__(self, transcribe, translate=None, *, punctuate=None, notify=None,
                 review_pending=None, review_decide=None, lookup=None,
                 max_chars: int = 5000, review_scope: str = "phone") -> None:
        self.transcribe = transcribe
        self.translate = translate
        self.punctuate = punctuate
        self.notify = notify
        self.review_pending = review_pending
        self.review_decide = review_decide
        self.lookup = lookup
        self.max_chars = max_chars
        self.review_scope = review_scope

    def handle(self, route: str, body: bytes = b"", phone=None) -> tuple[int, dict]:
        name = (LOOPBACK_ROUTES if phone is None else PHONE_ROUTES).get(route)
        if name is None:
            return 404, {"error": "not found"}
        try:
            return getattr(self, name)(body, phone)
        except _Answer as answer:
            return answer.status, answer.payload

    def _do_health(self, raw: bytes, phone) -> tuple[int, dict]:
        """Up, and which DeskIT — nothing more to whoever can reach the
        port (12.3): the engine's name rides on each transcript."""
        return 200, {"ok": True, "version": pc_version()}

    def _do_version(self, raw: bytes, phone) -> tuple[int, dict]:
        """The keyboard-build facts (12.9)."""
        return 200, api_version()

    def _do_transcribe(self, raw: bytes, phone) -> tuple[int, dict]:
        try:
            wav, seconds = to_wav(raw)
        except Exception as e:
            log.warning("phone sent audio we could not decode: %s", e)
            return 400, {"error": f"could not decode the audio: {e}"}
        try:
            result = self.transcribe(wav)
        except Exception as e:
            log.warning("phone transcription failed: %s", e)
            return 503, {"error": str(e)}
        # (text, backend) or (text, backend, warning) — the warning came
        # later and the test fakes still return pairs.
        text, backend = result[0], result[1]
        warning = result[2] if len(result) > 2 else None
        log.info("phone: %.1f s -> %d chars via %s", seconds, len(text),
                 backend)
        if phone is not None:
            import phone as phone_mod

            phone_mod.saw(phone.fingerprint, dictated=True)
        payload = {"text": text, "seconds": round(seconds, 2),
                   "backend": backend}
        if warning:
            payload["warning"] = warning
        return 200, payload

    def _do_translate(self, raw: bytes, phone) -> tuple[int, dict]:
        """Same job as the desktop's F9 key, for text already typed on the
        phone: hand back the English of whatever is in the field."""
        if self.translate is None:
            return 503, {"error": "translation is not available"}
        payload = _text_body(raw)
        text = payload.get("text", "")
        if not isinstance(text, str) or not text.strip():
            return 400, {"error": "nothing to translate"}
        # The desktop guard applies here too: a phone field can hold a
        # whole document, and translating one is never what was meant.
        if len(text) > self.max_chars:
            return 400, {"error": f"too long "
                                  f"({len(text)} chars) to translate"}
        # REFUSE RATHER THAN SPEND, which the desktop already does and the
        # phone did not: "text with no Hebrew in it is skipped rather than
        # spending a request". Without this, tapping the key on a field
        # that is already English burns one of the ~80 free Gemini requests
        # a day AND overwrites the whole field with the model's rewording
        # of English that needed nothing done to it.
        import translate as translate_mod
        if not translate_mod.needs_translation(text):
            return 400, {"error": "no Hebrew in it — nothing to translate"}
        try:
            out, backend = self.translate(text)
        except Exception as e:
            log.warning("phone translation failed: %s", e)
            return 503, {"error": str(e)}
        log.info("phone: translated %d chars via %s", len(text), backend)
        return 200, {"text": out, "backend": backend}

    def _do_punctuate(self, raw: bytes, phone) -> tuple[int, dict]:
        """The phone twin of the desktop's F2 key.

        This is the one the phone needs most after dictation itself: the
        local Hebrew model returns a run of words with barely a comma in
        it, [polish] is forbidden from adding any, and on a phone there is
        no practical way to put them in by hand.

        The words are guaranteed untouched — punctuate.py strips every
        non-letter from the reply AND from the input and demands they be
        identical — so the only interesting failure is the one where the
        model rewrote something. That comes back as 409 rather than 503,
        deliberately: the phone shows either verbatim, but the status code
        is what tells "your text is fine, the reply was thrown away" apart
        from "the backend is down", in app.log and to anything else reading
        this endpoint later.
        """
        if self.punctuate is None:
            return 503, {"error": "punctuation is not available"}
        payload = _text_body(raw)
        text = payload.get("text", "")
        if not isinstance(text, str) or not text.strip():
            return 400, {"error": "nothing to punctuate"}
        if len(text) > self.max_chars:
            return 400, {"error": f"too long "
                                  f"({len(text)} chars) to punctuate"}
        import punctuate as punctuate_mod
        if not punctuate_mod.needs_punctuation(text):
            return 400, {"error": "no words to punctuate"}
        # Nikud is deliberately NOT a per-request field. The prompt is built
        # from cfg.punctuate.nikud through a callable the backends read at
        # request time, so a per-call override would race the desktop key
        # rather than override it. It stays one setting for both.
        try:
            out, backend = self.punctuate(text)
        except punctuate_mod.UnsafeReply as e:
            # Told apart from every other failure on purpose, exactly as
            # the desktop key does it. "It could not be reached" sends
            # someone to check Ollama; this means the model answered and
            # rewrote their words, and the app threw that away — which is
            # the guard working, not breaking.
            # The phone's reply names the word; app.log does not (D8).
            log.error("phone punctuation discarded: %s. Text untouched.",
                      getattr(e, "logged", "the words changed"))
            return 409, {"error": f"left it alone — the model rewrote "
                                  f"your words ({e})", "unsafe": True}
        except Exception as e:
            log.warning("phone punctuation failed: %s", e)
            return 503, {"error": str(e)}
        log.info("phone: punctuated %d chars via %s", len(text), backend)
        return 200, {"text": out, "backend": backend,
                     "changed": out != text}

    def _do_notify(self, raw: bytes, phone) -> tuple[int, dict]:
        """A notification from another program (notify.py).

        The body is a JSON object with any of source / kind / title /
        body / project / session, all optional — the engine's clean()
        decides what each becomes, and this handler decides nothing
        about the content. It only sorts the answers: 503 when the app
        was built without the engine or the engine refused ([notify]
        enabled = false), 400 when the body was not an object, 200 with
        the engine's reply otherwise. The callable runs on this request
        thread and is written to return in milliseconds; there is no
        per-request timeout to hide behind.
        """
        if self.notify is None:
            return 503, {"error": "notifications are not available"}
        payload = _text_body(raw)
        try:
            result = self.notify(payload)
        except ValueError as e:
            return 400, {"error": str(e)}
        except Exception as e:
            log.warning("notify failed: %s", e)
            return 503, {"error": str(e)}
        if isinstance(result, dict) and result.get("ok") is False:
            return 503, result
        if not isinstance(result, dict):
            result = {"ok": True}
        log.info("phone: notification #%s from %s", result.get("id"),
                 payload.get("source", "?"))
        return 200, result


    # ---- the second reading, read and answered from the phone ----

    def _do_review_pending(self, raw: bytes, phone) -> tuple[int, dict]:
        """GET /review: the proposals still waiting for a verdict.

        A proposal quotes what was said. Each item carries the sentence,
        the proposed sentence, the changes, a `snippets` list shaped by
        review.snippet() so the phone paints the same three parts the
        desktop card does, and `source` — "phone" or "desktop".

        ONLY THE PHONE'S OWN PROPOSALS, as D22 asked: what was said at the
        desk stays at the desk. `[server] review_scope = "all"` is the
        developer line that answers every one, which his own Dev sets to
        keep answering desk proposals from the sofa.
        """
        if self.review_pending is None:
            return 503, {"error": "the second reading is not available"}
        try:
            items = self.review_pending()
        except Exception as e:            # noqa: BLE001 — the store, not us
            log.warning("phone asked for the review queue and it failed: %s",
                        e)
            return 503, {"error": str(e)}
        if self.review_scope != "all":
            items = [i for i in items if str(i.get("source") or "desktop") == "phone"]
        return 200, {"items": [_review_item(i) for i in items]}

    def _do_review_decide(self, raw: bytes, phone) -> tuple[int, dict]:
        """POST /review/decide {id, verdict}: the phone's Keep or No.

        The verdict is written to the store as `by="phone"`, and the
        app's review engine learns it on its next wake exactly as it
        learns a decision the dashboard took — one path for every
        answer, whoever gave it. 404 when the proposal is no longer
        pending: answered elsewhere, or never existed.
        """
        if self.review_decide is None:
            return 503, {"error": "the second reading is not available"}
        payload = _text_body(raw)
        sid = str(payload.get("id") or "").strip()
        verdict = str(payload.get("verdict") or "").strip()
        if not sid or verdict not in ("accepted", "rejected"):
            return 400, {"error": "expected an id and a verdict of "
                                  "accepted or rejected"}
        try:
            item = self.review_decide(sid, verdict)
        except Exception as e:            # noqa: BLE001
            log.warning("phone verdict on %s failed: %s", sid, e)
            return 503, {"error": str(e)}
        if item is None:
            return 404, {"error": "no pending proposal with that id"}
        log.info("phone: review %s %s", sid, verdict)
        return 200, {"ok": True, "id": sid, "status": item.get("status")}

    def _do_lookup(self, raw: bytes, phone) -> tuple[int, dict]:
        """POST /lookup {text}: the phone twin of the desktop's F8 key.

        Read-only by construction — the phone shows the answer in a box
        of its own and never writes it anywhere. The far end classifies
        the selection first (direction, word or phrase) with the same
        rules as the desk; a selection with nothing to look up — empty,
        too long, already in both scripts — is a 400 with the reason,
        so the phone can say so instead of showing an empty box.
        """
        if self.lookup is None:
            return 503, {"error": "lookup is not available"}
        payload = _text_body(raw)
        text = payload.get("text", "")
        if not isinstance(text, str) or not text.strip():
            return 400, {"error": "nothing to look up"}
        try:
            answer, target, backend, seconds = self.lookup(text)
        except ValueError as e:
            # classify() said no: the reason, verbatim, for the box.
            return 400, {"error": str(e)}
        except Exception as e:            # noqa: BLE001 — every backend
            log.warning("phone lookup failed: %s", e)
            return 503, {"error": str(e)}
        return 200, {"text": answer, "target": target,
                     "backend": backend, "seconds": round(seconds, 2)}



class _Handler(BaseHTTPRequestHandler):
    """One request on the loopback door: the bearer, the body, the table,
    and the answer written. Everything else is Routes'."""

    server_version = "DeskIT"
    # A peer that opens a socket and then sends nothing must not hold a
    # handler thread forever (a slowloris on the loopback/tailnet). With a
    # timeout the request socket gives up and the thread is freed.
    timeout = 30
    #: Who came in: nobody the handshake proved, on this door.
    phone = None

    # -- plumbing --

    def log_message(self, fmt, *args):        # keep it out of stderr
        log.debug("http %s", fmt % args)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        try:
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass                              # phone walked away mid-reply

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def _authorised(self) -> bool:
        want = self.server.token
        got = self.headers.get("Authorization", "")
        if got.startswith("Bearer "):
            got = got[7:]
        # Compare as bytes, not str: secrets.compare_digest raises
        # TypeError on a str carrying any code point >= 0x80, so a header
        # with one non-ASCII byte used to crash the handler (a traceback,
        # no 401) instead of simply failing the check. UTF-8 bytes keep it
        # constant-time and make a bad header an ordinary "wrong token".
        return secrets.compare_digest(got.encode("utf-8", "ignore"),
                                      want.encode("utf-8"))

    def _route(self) -> str:
        return self.path.split("?", 1)[0].rstrip("/") or "/"

    def _answers(self) -> dict[str, str]:
        """What this door answers, as things stand now."""
        return LOOPBACK_ROUTES if self.server.switch() else HOOK_ROUTES

    # -- routes --

    def do_GET(self) -> None:
        route = self._route()
        if route not in self._answers() or route not in GET_ROUTES:
            # `/` (the retired web page) and `/app.apk` land here too.
            self._json(404, {"error": "not found"})
            return
        if route not in OPEN_ROUTES and not self._authorised():
            self._json(401, {"error": "bad token"})
            return
        self._json(*self.server.routes.handle(route, b"", self.phone))

    def handle_one_request(self) -> None:
        # BaseHTTPRequestHandler prints tracebacks to stderr, which pythonw
        # throws away — so a crash in here reached the phone as a bare 502
        # with no trace of why anywhere. Log it.
        try:
            super().handle_one_request()
        except Exception:
            log.exception("phone request handler crashed")
            raise

    def do_POST(self) -> None:
        route = self._route()
        if route not in self._answers() or route in GET_ROUTES:
            self._json(404, {"error": "not found"})
            return
        if not self._authorised():
            log.warning("rejected an unauthorised %s from %s", route,
                        self.client_address[0])
            self._json(401, {"error": "bad token"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if not 0 < length <= MAX_BODY:
            self._json(400, {"error": f"body must be 1..{MAX_BODY} bytes"})
            return
        self._json(*self.server.routes.handle(route, self.rfile.read(length), self.phone))


class _PhoneHandler(_Handler):
    """One request on the phone door. The handshake proved the certificate
    before this class saw a byte, so the proof is the connection and there
    is no bearer to ask for; net.Door checks the leaf against the list."""

    def __init__(self, request, client_address, server, peer) -> None:
        self.phone = peer
        super().__init__(request, client_address, server)

    def _answers(self) -> dict[str, str]:
        return PHONE_ROUTES

    def _authorised(self) -> bool:
        return True


def _review_item(item: dict) -> dict:
    """One pending proposal as the phone wants it: the fields it paints,
    and the three-part snippet per change, computed here so the phone
    needs no copy of review.words()."""
    import review as review_mod
    text = str(item.get("text") or "")
    changes = list(item.get("changes") or [])
    snippets = []
    for change in changes:
        try:
            snippets.append(review_mod.snippet(text, change))
        except Exception:                 # noqa: BLE001 — a malformed span
            snippets.append({"right": "", "left": "",
                             "word": str(change.get("after", "")),
                             "was": str(change.get("before", "")),
                             "kind": str(change.get("kind", "replace")),
                             "why": str(change.get("why", "")),
                             "support": 0, "rtl": review_mod.is_rtl(text)})
    return {"id": str(item.get("id") or ""),
            "when": str(item.get("when") or ""),
            "seconds": item.get("seconds", 0),
            "text": text,
            "proposed": str(item.get("proposed") or ""),
            "source": str(item.get("source") or "desktop"),
            "changes": [{"before": str(c.get("before", "")),
                         "after": str(c.get("after", "")),
                         "kind": str(c.get("kind", "replace")),
                         "why": str(c.get("why", ""))} for c in changes],
            "snippets": snippets}


#: How many ports a busy door tries, its own first.
PORT_TRIES = 20
#: WSAEADDRINUSE, and WSAEACCES, which is what Windows answers on a port
#: another program holds exclusively or that Hyper-V reserved.
_BUSY_WINERRORS = (10048, 10013)

#: A process the suite started (tests.py sets it before its first import,
#: and every child inherits it, AGENTS.md) never asks for a door's real
#: port: 8756 is his running app's, and a test that got there first would
#: send his app and the hook somewhere else. And it never binds beyond
#: loopback, because that is what raises Windows' firewall dialog on his
#: screen.
_SUITE = os.environ.get("DESKIT_SUITE", "").strip() == "1"
_REAL_PORTS = (8756, 8766)
_SUITE_SHIFT = 20000

#: Every interface: a phone comes in on whichever network the PC is on, and
#: its row names the private addresses. A rule on Public means the door also
#: stands on a cafe's Wi-Fi, which is what the client certificate is for.
PHONE_BIND = "127.0.0.1" if _SUITE else "0.0.0.0"


def _asked(port: int) -> int:
    return port + _SUITE_SHIFT if _SUITE and port in _REAL_PORTS else port


def _busy(error: OSError) -> bool:
    return (getattr(error, "winerror", None) in _BUSY_WINERRORS
            or error.errno in (errno.EADDRINUSE, errno.EACCES))


def _first_free(open_at, first: int):
    """``(open_at(port), port)`` on the first of PORT_TRIES ports that is
    not taken. Anything but a busy port goes up to the caller."""
    for port in range(first, first + PORT_TRIES):
        try:
            return open_at(port), port
        except OSError as e:
            if not _busy(e) or port == first + PORT_TRIES - 1:
                raise
    raise OSError(errno.EADDRINUSE, "no port to try")    # PORT_TRIES of nothing


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # NOT allow_reuse_address. On Windows SO_REUSEADDR lets a DIFFERENT
    # process — a different user's — bind this very 127.0.0.1:port and take
    # over the socket, and the token the notify hook (and the phone) send
    # here is a Bearer header that the squatter would then read straight off
    # the wire. SO_EXCLUSIVEADDRUSE is Microsoft's answer to exactly that:
    # the port is ours alone while we hold it, and if something already
    # holds it we refuse to start rather than share it. server_bind sets it
    # before binding; on a platform without the flag this is a plain bind.
    allow_reuse_address = False

    def server_bind(self):
        flag = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if flag is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, flag, 1)
        super().server_bind()

    def __init__(self, addr, token, routes: Routes, switch):
        super().__init__(addr, _Handler)
        self.token = token
        self.routes = routes
        #: Is the phone switch on? Asked per request: the door stays up for
        #: the hook when it goes off, and nothing restarts.
        self.switch = switch


class PhoneServer:
    """The loopback door: it owns the socket and the thread, and the routes
    both doors answer with. Never fatal: if it cannot start, the desktop
    hotkey must keep working regardless."""

    def __init__(self, cfg, transcribe, backend_name, translate=None,
                 punctuate=None, notify=None, review_pending=None,
                 review_decide=None, lookup=None):
        self.cfg = cfg
        self._backend_name = backend_name
        # The second reading's queue and its verdicts, and the F8 lookup,
        # for the phone (2026-09-13).
        self.routes = Routes(transcribe, translate, punctuate=punctuate,
                             notify=notify, review_pending=review_pending,
                             review_decide=review_decide, lookup=lookup,
                             max_chars=cfg.translate.max_chars,
                             review_scope=cfg.server.review_scope)
        self._srv: _Server | None = None
        self._thread: threading.Thread | None = None
        #: The port it holds, None while it is shut.
        self.port: int | None = None

    @property
    def running(self) -> bool:
        return self._srv is not None

    def start(self, first: int | None = None) -> None:
        """Open the door on ``first`` (the setting's port when left unsaid)
        or the next free one. A second start is nothing."""
        if self.running:
            return
        host = self.cfg.server.host.strip() or "127.0.0.1"
        # Loopback only, whatever the setting says. Binding a non-loopback
        # interface (0.0.0.0, a LAN address) would put a token-guarded,
        # un-throttled socket in front of the whole house network; that
        # is what the phone door's handshake is for. An unexpected host is
        # refused and we fall back to loopback with a line in the log,
        # rather than silently exposing the surface. `server.host`'s help
        # text already says empty is the private choice; this makes the
        # code enforce it.
        if host.lower() not in ("127.0.0.1", "localhost", "::1"):
            log.warning("server.host=%r would bind a non-loopback interface; "
                        "the loopback door stays on this PC. Binding "
                        "127.0.0.1 instead.", host)
            host = "127.0.0.1"
        token = load_token()
        self.routes.review_scope = self.cfg.server.review_scope
        asked = _asked(self.cfg.server.port if first is None else first)
        self._srv, self.port = _first_free(
            lambda port: _Server((host, port), token, self.routes,
                                 lambda: self.cfg.server.enabled), asked)
        self._thread = threading.Thread(target=self._srv.serve_forever,
                                        daemon=True, name="phone-server")
        self._thread.start()
        log.info("phone endpoint on %s:%d", host, self.port)
        if self.port != asked:
            # another copy got here first. In the checkout that is the
            # Stranger or the released app, and `tailscale serve` and the
            # phone now reach THAT copy, under a token that is not this one's.
            (log.warning if paths.DEVELOPER else log.info)(
                "THE LOOPBACK DOOR MOVED: port %d is taken, so this copy is on %d, and "
                "whatever still points at %d reaches the other copy", asked, self.port, asked)

    def stop(self) -> None:
        srv, thread = self._srv, self._thread
        self._srv = self._thread = self.port = None
        if srv is not None:
            srv.shutdown()
            srv.server_close()
        if thread is not None:
            thread.join(timeout=2)


class PhoneDoor:
    """The phone door: net.Door and the requests that come through it. The
    list of who may come in is phone.anchors()'s to say; this only holds it
    open, on whichever port it could have."""

    def __init__(self, cfg, routes: Routes) -> None:
        self.cfg = cfg
        self.routes = routes
        self._door = None
        self._list: dict = {}
        #: The certificate the door was opened with.
        self._cert = ""

    @property
    def running(self) -> bool:
        return self._door is not None

    @property
    def port(self) -> int | None:
        return self._door.port if self._door is not None else None

    def _serve(self, sock, address, peer) -> None:
        import phone as phone_mod

        phone_mod.saw(peer.fingerprint)
        _PhoneHandler(sock, address, self, peer)

    def _open(self, anchors: dict, first: int):
        import net
        import phone as phone_mod

        return _first_free(
            lambda port: net.serve_tls(PHONE_BIND, port, chain=phone_mod.key_path(),
                                       passphrase=phone_mod.PASS_NAME, anchors=anchors,
                                       handler=self._serve),
            first)[0]

    def _same_key(self) -> bool:
        """Is the key on disk the one this door opened with? A read that
        fails says yes: it is no reason to close a door that works."""
        import phone as phone_mod
        import secretstore

        try:
            return phone_mod.identity() == self._cert
        except (OSError, ValueError, secretstore.SecretError) as e:
            log.info("phone door: its key was not read (%s)", type(e).__name__)
            return True

    def start(self, anchors: dict) -> int:
        """Open it for ``anchors``; the port it got. An open door takes the
        list, and reopens under the key on disk if that is another one: a
        door shows the certificate it was opened with, and a phone pins what
        the row says.

        A key that will not open (the file came back from a backup, say) is
        a new identity and one more try, and the next `link` row carries the
        new certificate. A key that could not be read just now is neither:
        the door stays as it is and the next pass tries again."""
        import net
        import phone as phone_mod
        import secretstore

        names = {mark: phone.get("name") for mark, phone in anchors.items()}
        if self._door is not None and names != self._list:
            try:
                self._door.admit(anchors)
                self._list = names
            except net.DoorUnread as e:
                log.warning("phone door: %s; the list stands, the next pass tries again", e)
            except net.DoorError as e:
                log.warning("phone door: %s; it opens again", e)
                self.stop()
        if self._door is not None and not self._same_key():
            log.info("phone door: the key changed; it opens again")
            self.stop()
        if self._door is not None:
            return self._door.port
        first = _asked(self.cfg.server.phone_port)
        try:
            cert = phone_mod.identity()
            door = self._open(anchors, first)
        except net.DoorUnread:
            raise
        except (net.DoorError, ValueError, secretstore.SecretError) as e:
            log.warning("phone door: the key will not do (%s); a new identity for this PC",
                        type(e).__name__)
            cert = phone_mod.rotate()
            door = self._open(anchors, first)
        self._door, self._cert, self._list = door, cert, names
        log.info("phone door open on port %d for %d phone(s)", door.port, len(anchors))
        return door.port

    def stop(self) -> None:
        door, self._door = self._door, None
        self._list = {}
        self._cert = ""
        if door is not None:
            door.stop()
            log.info("phone door closed")
