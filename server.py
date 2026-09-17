"""Phone -> this PC transcription endpoint, plus a mobile page to drive it.

The point is to dictate from the phone WITHOUT giving up the thing that
makes the desktop app good: the ivrit-ai fine-tune on the GPU (10.8% WER,
0.38 s, no quota). So the phone records and this machine transcribes.

It runs as a thread inside the running app and borrows the transcriber
that is already loaded. A separate process would load the same two models
again — about 3.2 GB of VRAM and ~25 s of startup for no benefit.

Reachability is Tailscale's job, not ours. The socket binds to LOOPBACK
and `tailscale serve` fronts it: no port forwarding, no public IP, and
nothing listening on any interface a stranger could reach — not even the
home LAN. Tailscale terminates TLS with a real certificate, which is not a
nicety: phone browsers refuse the microphone without one (see below). A
bearer token sits behind all that, because a private network is a wall,
not a lock.

Binding loopback rather than the Tailscale address is load-bearing:
`tailscale serve` proxies to localhost, so a server bound only to
100.x.y.z is invisible to it.

Two things about browsers on phones that shape the page below:

- getUserMedia (microphone) and navigator.clipboard BOTH require a secure
  context. Plain http://100.x.y.z is not one, so the page is useless over
  bare HTTP no matter how well it works on a laptop. `tailscale serve`
  fronts it with a real certificate; see the README.
- A long press on a button raises the text-selection/callout UI, which
  fights a hold-to-talk control. Hence touch-action/user-select are off
  and pointer events (not touch events) drive it.
"""
from __future__ import annotations

import json
import logging
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import paths

log = logging.getLogger("app")

# tailscale.exe is a CONSOLE program and this app runs under pythonw,
# which has no console: without this flag every spawn ALLOCATES ONE, and
# on Windows 11 that is a WINDOWS TERMINAL window (class
# CASCADIA_HOSTING_WINDOW_CLASS), not the conhost the older comments in
# this repo describe — which is why it reads as a terminal flashing open
# and shut rather than a flicker. Probed under a parent with no console
# anywhere in its chain: seven top-level windows created without this
# flag, none with it, and tailscale still answers.
#
# HOW LONG IT WAS UP is the command's own runtime, about 110 ms warm —
# which is exactly the "it appears for a split second" this was reported
# as. An earlier note here said 0.7-2.1 s, read off the gap in app.log
# between "phone endpoint on ..." and the URL line. That gap is
# tailscale's cold start, NOT the window: it fell to ~110 ms on its own,
# on boots that still predate this flag. The window is the finding; the
# gap never measured it.
#
# Same reason and same constant as versions._CREATE_NO_WINDOW and
# awake.CREATE_NO_WINDOW; the rule is in AGENTS.md.
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

APP_DIR = Path(__file__).resolve().parent
TOKEN_FILE = paths.PHONE_TOKEN
APK = (APP_DIR / "android" / "app" / "build" / "outputs" / "apk"
       / "debug" / "app-debug.apk")
APK_GRADLE = APP_DIR / "android" / "app" / "build.gradle.kts"


def apk_version() -> str:
    """versionName from the build file, for the download filename.

    Serving every build as "DeskIT.apk" means the new one lands
    next to the old one in Downloads under the same name — and tapping the
    stale copy reinstalls the previous version, which looks exactly like an
    update that refused to apply. A version in the name makes the two
    impossible to confuse.
    """
    try:
        import re
        m = re.search(r'versionName\s*=\s*"([^"]+)"',
                      APK_GRADLE.read_text("utf-8"))
        return m.group(1) if m else "0"
    except OSError:
        return "0"

# Bodies are speech, not uploads. A minute of Opus is ~100 KB; this is a
# sanity bound so a stray POST cannot buffer a gigabyte into memory.
MAX_BODY = 32 * 1024 * 1024


def load_token() -> str:
    """Read the shared secret, generating it on first run.

    Generated rather than configured because a token the user has to
    invent is a token that ends up being "1234" — and this one is never
    typed by hand anyway: it travels in the URL the log prints.
    """
    try:
        token = TOKEN_FILE.read_text("utf-8").strip()
        if token:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token, "utf-8")
    log.info("generated a new phone token in %s", TOKEN_FILE.name)
    return token


def _tailscale_exe() -> str | None:
    """The Windows installer does not put tailscale.exe on PATH."""
    import shutil
    found = shutil.which("tailscale")
    if found:
        return found
    for guess in (r"C:\Program Files\Tailscale\tailscale.exe",
                  r"C:\Program Files (x86)\Tailscale\tailscale.exe"):
        if Path(guess).exists():
            return guess
    return None


def run_utf8(cmd: list[str], timeout: float = 10) -> str | None:
    """Run a command and return its stdout as text, or None on any failure.

    `encoding` is the entire point. subprocess's text=True decodes with the
    LOCALE code page, which on this machine is cp1255 (Hebrew) — so any
    tool that emits UTF-8 blows up with UnicodeDecodeError inside
    subprocess's reader thread and hands back stdout=None. That exception
    is a ValueError, so a broad `except` swallows it and the caller
    concludes the tool is missing or the service is down. Cost real
    debugging time: the app reported Tailscale as offline while it was up.

    `creationflags` is the second point: see _CREATE_NO_WINDOW above.
    """
    try:
        out = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                             errors="replace", timeout=timeout, check=False,
                             creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("command %r failed: %r", cmd[:1], e)
        return None
    return out.stdout


def tailscale_name() -> str | None:
    """This machine's MagicDNS name, which is the host `tailscale serve`
    publishes it under. None when Tailscale is not up — used only to print
    a URL, never to decide what to bind."""
    exe = _tailscale_exe()
    if not exe:
        return None
    raw = run_utf8([exe, "status", "--json"])
    try:
        self_node = json.loads(raw or "{}").get("Self") or {}
    except ValueError:
        return None
    return (self_node.get("DNSName") or "").strip(". ") or None


def to_wav(raw: bytes) -> tuple[bytes, float]:
    """Whatever the phone recorded (webm/opus, ogg, m4a, wav) -> (16 kHz
    mono WAV, seconds). That is what the transcriber and its language
    detector expect. PyAV ships with faster-whisper: no ffmpeg needed."""
    import numpy as np
    from faster_whisper.audio import decode_audio

    from recorder import frames_to_wav

    audio = decode_audio(BytesIO(raw), sampling_rate=16000)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    return frames_to_wav([pcm], 16000), len(pcm) / 16000.0


class _Handler(BaseHTTPRequestHandler):
    server_version = "DeskIT"

    # -- plumbing --

    def log_message(self, fmt, *args):        # keep it out of stderr
        log.debug("http %s", fmt % args)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass                              # phone walked away mid-reply

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def _authorised(self) -> bool:
        want = self.server.token
        got = self.headers.get("Authorization", "")
        if got.startswith("Bearer "):
            got = got[7:]
        return secrets.compare_digest(got, want)

    # -- routes --

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/":
            self._send(200, PAGE.encode("utf-8"),
                       "text/html; charset=utf-8")
        elif path == "/app.apk":
            # Sideloading over the same private link the app will use:
            # no cable, no USB debugging, no third-party file transfer.
            # Unauthenticated on purpose — it is reachable only from the
            # tailnet, and the APK deliberately ships no token.
            if not APK.exists():
                self._json(404, {"error": "no APK built yet"})
                return
            self.send_response(200)
            self.send_header("Content-Type",
                             "application/vnd.android.package-archive")
            self.send_header("Content-Length", str(APK.stat().st_size))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="DeskIT-{apk_version()}.apk"')
            # Without this the browser happily re-serves the previous
            # build from cache, and a rebuilt app looks like one that
            # silently refused to update.
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("ETag", f'"{APK.stat().st_mtime_ns}"')
            self.end_headers()
            try:
                self.wfile.write(APK.read_bytes())
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif path == "/health":
            self._json(200, {"ok": True,
                             "backend": self.server.backend_name(),
                             "apk": apk_version() if APK.exists() else None})
        elif path == "/review":
            self._do_review_pending()
        else:
            self._json(404, {"error": "not found"})

    def handle_one_request(self) -> None:
        # BaseHTTPRequestHandler prints tracebacks to stderr, which pythonw
        # throws away — so a crash in here reached the phone as a bare 502
        # with no trace of why anywhere. Log it.
        try:
            super().handle_one_request()
        except Exception:
            log.exception("phone request handler crashed")
            raise

    # route -> handler name. A table rather than a chain of `if route ==`,
    # because the chain was already carrying its own bugs by the third
    # entry: the allow-list and the dispatch were two separate lists that
    # had to agree, and the 401 below named /transcribe whatever had
    # actually been called.
    POST_ROUTES = {
        "/transcribe": "_do_transcribe",
        "/translate": "_do_translate",
        "/punctuate": "_do_punctuate",
        "/notify": "_do_notify",
        "/review/decide": "_do_review_decide",
        "/lookup": "_do_lookup",
    }

    def do_POST(self) -> None:
        route = self.path.split("?", 1)[0].rstrip("/")
        handler = self.POST_ROUTES.get(route)
        if handler is None:
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
        getattr(self, handler)(self.rfile.read(length))

    def _text_body(self, raw: bytes) -> dict | None:
        """The JSON body of a text route, or None once an error is sent."""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"error": "expected JSON with a text field"})
            return None
        if not isinstance(payload, dict):
            self._json(400, {"error": "expected JSON with a text field"})
            return None
        return payload

    def _do_transcribe(self, raw: bytes) -> None:
        try:
            wav, seconds = to_wav(raw)
        except Exception as e:
            log.warning("phone sent audio we could not decode: %s", e)
            self._json(400, {"error": f"could not decode the audio: {e}"})
            return
        try:
            result = self.server.transcribe(wav)
        except Exception as e:
            log.warning("phone transcription failed: %s", e)
            self._json(503, {"error": str(e)})
            return
        # (text, backend) or (text, backend, warning) — the warning came
        # later and the test fakes still return pairs.
        text, backend = result[0], result[1]
        warning = result[2] if len(result) > 2 else None
        log.info("phone: %.1f s -> %d chars via %s", seconds, len(text),
                 backend)
        payload = {"text": text, "seconds": round(seconds, 2),
                   "backend": backend}
        if warning:
            payload["warning"] = warning
        self._json(200, payload)

    def _do_translate(self, raw: bytes) -> None:
        """Same job as the desktop's F9 key, for text already typed on the
        phone: hand back the English of whatever is in the field."""
        if self.server.translate is None:
            self._json(503, {"error": "translation is not available"})
            return
        payload = self._text_body(raw)
        if payload is None:
            return
        text = payload.get("text", "")
        if not isinstance(text, str) or not text.strip():
            self._json(400, {"error": "nothing to translate"})
            return
        # The desktop guard applies here too: a phone field can hold a
        # whole document, and translating one is never what was meant.
        if len(text) > self.server.max_chars:
            self._json(400, {"error": f"too long "
                                      f"({len(text)} chars) to translate"})
            return
        # REFUSE RATHER THAN SPEND, which the desktop already does and the
        # phone did not: "text with no Hebrew in it is skipped rather than
        # spending a request". Without this, tapping the key on a field
        # that is already English burns one of the ~80 free Gemini requests
        # a day AND overwrites the whole field with the model's rewording
        # of English that needed nothing done to it.
        import translate as translate_mod
        if not translate_mod.needs_translation(text):
            self._json(400, {"error": "no Hebrew in it — nothing to translate"})
            return
        try:
            out, backend = self.server.translate(text)
        except Exception as e:
            log.warning("phone translation failed: %s", e)
            self._json(503, {"error": str(e)})
            return
        log.info("phone: translated %d chars via %s", len(text), backend)
        self._json(200, {"text": out, "backend": backend})

    def _do_punctuate(self, raw: bytes) -> None:
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
        if self.server.punctuate is None:
            self._json(503, {"error": "punctuation is not available"})
            return
        payload = self._text_body(raw)
        if payload is None:
            return
        text = payload.get("text", "")
        if not isinstance(text, str) or not text.strip():
            self._json(400, {"error": "nothing to punctuate"})
            return
        if len(text) > self.server.max_chars:
            self._json(400, {"error": f"too long "
                                      f"({len(text)} chars) to punctuate"})
            return
        import punctuate as punctuate_mod
        if not punctuate_mod.needs_punctuation(text):
            self._json(400, {"error": "no words to punctuate"})
            return
        # Nikud is deliberately NOT a per-request field. The prompt is built
        # from cfg.punctuate.nikud through a callable the backends read at
        # request time, so a per-call override would race the desktop key
        # rather than override it. It stays one setting for both.
        try:
            out, backend = self.server.punctuate(text)
        except punctuate_mod.UnsafeReply as e:
            # Told apart from every other failure on purpose, exactly as
            # the desktop key does it. "It could not be reached" sends
            # someone to check Ollama; this means the model answered and
            # rewrote their words, and the app threw that away — which is
            # the guard working, not breaking.
            log.error("phone punctuation discarded: %s. Text untouched.", e)
            self._json(409, {"error": f"left it alone — the model rewrote "
                                      f"your words ({e})", "unsafe": True})
            return
        except Exception as e:
            log.warning("phone punctuation failed: %s", e)
            self._json(503, {"error": str(e)})
            return
        log.info("phone: punctuated %d chars via %s", len(text), backend)
        self._json(200, {"text": out, "backend": backend,
                         "changed": out != text})

    def _do_notify(self, raw: bytes) -> None:
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
        if self.server.notify is None:
            self._json(503, {"error": "notifications are not available"})
            return
        payload = self._text_body(raw)
        if payload is None:
            return
        try:
            result = self.server.notify(payload)
        except ValueError as e:
            self._json(400, {"error": str(e)})
            return
        except Exception as e:
            log.warning("notify failed: %s", e)
            self._json(503, {"error": str(e)})
            return
        if isinstance(result, dict) and result.get("ok") is False:
            self._json(503, result)
            return
        if not isinstance(result, dict):
            result = {"ok": True}
        log.info("phone: notification #%s from %s", result.get("id"),
                 payload.get("source", "?"))
        self._json(200, result)


    # ---- the second reading, read and answered from the phone ----

    def _do_review_pending(self) -> None:
        """GET /review: every proposal still waiting for a verdict.

        The one GET that needs the token: a proposal quotes what was
        said. Each item carries the sentence, the proposed sentence, the
        changes, a `snippets` list shaped by review.snippet() so the phone
        paints the same three parts the desktop card does, and `source`
        — "phone" or "desktop" — which is what the phone rings on. The
        list is ALL pending proposals, not only the phone's: the phone is
        also the way to answer a desk proposal from the sofa.
        """
        if not self._authorised():
            self._json(401, {"error": "bad token"})
            return
        if self.server.review_pending is None:
            self._json(503, {"error": "the second reading is not available"})
            return
        try:
            items = self.server.review_pending()
        except Exception as e:            # noqa: BLE001 — the store, not us
            log.warning("phone asked for the review queue and it failed: %s",
                        e)
            self._json(503, {"error": str(e)})
            return
        self._json(200, {"items": [_review_item(i) for i in items]})

    def _do_review_decide(self, raw: bytes) -> None:
        """POST /review/decide {id, verdict}: the phone's Keep or No.

        The verdict is written to the store as `by="phone"`, and the
        app's review engine learns it on its next wake exactly as it
        learns a decision the dashboard took — one path for every
        answer, whoever gave it. 404 when the proposal is no longer
        pending: answered elsewhere, or never existed.
        """
        if self.server.review_decide is None:
            self._json(503, {"error": "the second reading is not available"})
            return
        payload = self._text_body(raw)
        if payload is None:
            return
        sid = str(payload.get("id") or "").strip()
        verdict = str(payload.get("verdict") or "").strip()
        if not sid or verdict not in ("accepted", "rejected"):
            self._json(400, {"error": "expected an id and a verdict of "
                                      "accepted or rejected"})
            return
        try:
            item = self.server.review_decide(sid, verdict)
        except Exception as e:            # noqa: BLE001
            log.warning("phone verdict on %s failed: %s", sid, e)
            self._json(503, {"error": str(e)})
            return
        if item is None:
            self._json(404, {"error": "no pending proposal with that id"})
            return
        log.info("phone: review %s %s", sid, verdict)
        self._json(200, {"ok": True, "id": sid, "status": item.get("status")})

    def _do_lookup(self, raw: bytes) -> None:
        """POST /lookup {text}: the phone twin of the desktop's F8 key.

        Read-only by construction — the phone shows the answer in a box
        of its own and never writes it anywhere. The far end classifies
        the selection first (direction, word or phrase) with the same
        rules as the desk; a selection with nothing to look up — empty,
        too long, already in both scripts — is a 400 with the reason,
        so the phone can say so instead of showing an empty box.
        """
        if self.server.lookup is None:
            self._json(503, {"error": "lookup is not available"})
            return
        payload = self._text_body(raw)
        if payload is None:
            return
        text = payload.get("text", "")
        if not isinstance(text, str) or not text.strip():
            self._json(400, {"error": "nothing to look up"})
            return
        try:
            answer, target, backend, seconds = self.server.lookup(text)
        except ValueError as e:
            # classify() said no: the reason, verbatim, for the box.
            self._json(400, {"error": str(e)})
            return
        except Exception as e:            # noqa: BLE001 — every backend
            log.warning("phone lookup failed: %s", e)
            self._json(503, {"error": str(e)})
            return
        self._json(200, {"text": answer, "target": target,
                         "backend": backend, "seconds": round(seconds, 2)})


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


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, token, transcribe, backend_name, translate=None,
                 max_chars=5000, punctuate=None, notify=None,
                 review_pending=None, review_decide=None, lookup=None):
        super().__init__(addr, _Handler)
        self.token = token
        self.transcribe = transcribe
        self.backend_name = backend_name
        self.translate = translate
        self.punctuate = punctuate
        self.notify = notify
        self.review_pending = review_pending
        self.review_decide = review_decide
        self.lookup = lookup
        self.max_chars = max_chars


class PhoneServer:
    """Owns the socket and the thread. Never fatal: if it cannot start,
    the desktop hotkey must keep working regardless."""

    def __init__(self, cfg, transcribe, backend_name, translate=None,
                 punctuate=None, notify=None, review_pending=None,
                 review_decide=None, lookup=None):
        self.cfg = cfg
        self._transcribe = transcribe
        self._backend_name = backend_name
        self._translate = translate
        self._punctuate = punctuate
        self._notify = notify
        # The second reading's queue and its verdicts, and the F8 lookup,
        # for the phone (2026-09-13). All optional: a caller without them
        # gets a 503 on those routes and everything else unchanged.
        self._review_pending = review_pending
        self._review_decide = review_decide
        self._lookup = lookup
        self._srv: _Server | None = None
        self._thread: threading.Thread | None = None
        self.url: str | None = None

    def start(self) -> None:
        port = self.cfg.server.port
        host = self.cfg.server.host.strip() or "127.0.0.1"
        token = load_token()
        self._srv = _Server((host, port), token, self._transcribe,
                            self._backend_name, self._translate,
                            self.cfg.translate.max_chars, self._punctuate,
                            notify=self._notify,
                            review_pending=self._review_pending,
                            review_decide=self._review_decide,
                            lookup=self._lookup)
        self._thread = threading.Thread(target=self._srv.serve_forever,
                                        daemon=True, name="phone-server")
        self._thread.start()
        log.info("phone endpoint on %s:%d", host, port)
        name = tailscale_name()
        if name:
            self.url = f"https://{name}/#t={token}"
            log.info("open this on the phone: %s", self.url)
            log.info("(needs `tailscale serve --bg %d` once — without it "
                     "there is no certificate, and the phone browser will "
                     "refuse the microphone)", port)
        else:
            self.url = f"http://{host}:{port}/#t={token}"
            log.warning("tailscale is not up — the phone cannot reach this. "
                        "Log in to Tailscale, then restart. Local URL: %s",
                        self.url)

    def stop(self) -> None:
        if self._srv is not None:
            self._srv.shutdown()
            self._srv.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


PAGE = r"""<!doctype html>
<html lang="he" dir="rtl">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,
      maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>הכתבה</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100dvh; display: flex; flex-direction: column;
         align-items: center; justify-content: center; gap: 22px;
         background: #14110c; color: #f1ece2; font: 17px/1.5 system-ui,
         -apple-system, "Segoe UI", Roboto, sans-serif;
         padding: 24px calc(24px + env(safe-area-inset-right))
                  calc(24px + env(safe-area-inset-bottom))
                  calc(24px + env(safe-area-inset-left)); }
  #mic { width: 190px; height: 190px; border-radius: 50%; border: none;
         background: #e3a63c; color: #1a1409; font-size: 20px;
         font-weight: 600;
         box-shadow: 0 10px 34px rgba(227,166,60,.34);
         transition: transform .12s, background .12s, box-shadow .12s;
         /* a long press must not raise selection or the callout menu */
         touch-action: none; user-select: none; -webkit-user-select: none;
         -webkit-touch-callout: none; }
  #mic:disabled { background: #332d24; color: #7e7564; box-shadow: none; }
  #mic.rec { background: #ff5b4e; color: #1a1409; transform: scale(1.07);
             box-shadow: 0 0 0 14px rgba(255,91,78,.20); }
  #status { min-height: 1.5em; color: #b2a896; text-align: center; }
  #out { width: min(560px, 100%); min-height: 8.5em; padding: 14px 16px;
         border-radius: 14px; border: 1px solid #3a342a; background: #1c1813;
         color: #f1ece2; font: inherit; resize: vertical; }
  #out:focus { outline: 2px solid #e3a63c; outline-offset: 1px; }
  #copy { padding: 12px 22px; border-radius: 11px;
          border: 1px solid #4e473780;
          background: #24201a; color: #f1ece2; font: inherit; }
  .hint { color: #7e7564; font-size: 14px; text-align: center; }
</style>

<button id="mic">החזק ודבר</button>
<div id="status">מוכן</div>
<textarea id="out" placeholder="הטקסט יופיע כאן" dir="auto"></textarea>
<button id="copy">העתק</button>
<div class="hint">מחזיקים, מדברים, משחררים. הטקסט מועתק אוטומטית.</div>
<a class="hint" href="app.apk" style="color:#8fc0f0" id="apk">התקן את אפליקציית המקלדת (APK)</a>

<script>
const mic = document.getElementById('mic');
const out = document.getElementById('out');
const statusEl = document.getElementById('status');

// The token arrives once in the URL hash, then lives in localStorage so
// the page can be bookmarked without the secret sitting in the address bar.
let token = localStorage.getItem('dictationToken') || '';
const fromHash = new URLSearchParams(location.hash.slice(1)).get('t');
if (fromHash) {
  token = fromHash;
  localStorage.setItem('dictationToken', token);
  history.replaceState(null, '', location.pathname);
}
if (!token) say('חסר טוקן — פתח את הכתובת המלאה מהלוג של המחשב', true);

function say(msg, bad) {
  statusEl.textContent = msg;
  statusEl.style.color = bad ? '#f1867a' : '#b2a896';
}

let recorder = null, chunks = [], stream = null, startedAt = 0;

async function getStream() {
  if (stream && stream.active) return stream;
  // Not a secure context => getUserMedia is undefined, and the failure is
  // otherwise a silent no-op that looks like a broken microphone.
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new Error('הדפדפן חוסם מיקרופון בעמוד שאינו https');
  }
  stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
  });
  return stream;
}

async function start() {
  if (recorder || !token) return;
  try {
    const s = await getStream();
    chunks = [];
    recorder = new MediaRecorder(s);
    recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    recorder.start();
    startedAt = Date.now();
    mic.classList.add('rec');
    mic.textContent = 'מקליט…';
    say('מדבר…');
  } catch (e) {
    recorder = null;
    say(e.message || String(e), true);
  }
}

async function stop() {
  if (!recorder) return;
  const r = recorder, held = Date.now() - startedAt;
  recorder = null;
  mic.classList.remove('rec');
  mic.textContent = 'החזק ודבר';
  const done = new Promise(res => { r.onstop = res; });
  r.stop();
  await done;
  if (held < 300) { say('קצר מדי'); return; }   // matches min_seconds
  const blob = new Blob(chunks, { type: r.mimeType || 'audio/webm' });
  say('מתמלל…');
  mic.disabled = true;
  try {
    const res = await fetch('transcribe', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token,
                 'Content-Type': blob.type || 'application/octet-stream' },
      body: blob
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || ('שגיאה ' + res.status));
    const text = (data.text || '').trim();
    if (!text) { say('לא נשמע דיבור'); return; }
    out.value = out.value ? out.value + ' ' + text : text;
    say(`${data.seconds}s · ${data.backend}`);
    copy(true);
  } catch (e) {
    say(e.message || String(e), true);
  } finally {
    mic.disabled = false;
  }
}

async function copy(quiet) {
  if (!out.value) return;
  try {
    await navigator.clipboard.writeText(out.value);
    if (!quiet) say('הועתק');
  } catch {
    // Clipboard API needs a secure context too; select the text so a
    // long-press copy still works instead of failing silently.
    out.select();
    if (!quiet) say('בחר והעתק ידנית', true);
  }
}

mic.addEventListener('pointerdown', e => { e.preventDefault(); start(); });
for (const ev of ['pointerup', 'pointercancel', 'pointerleave']) {
  mic.addEventListener(ev, e => { e.preventDefault(); stop(); });
}
mic.addEventListener('contextmenu', e => e.preventDefault());
document.getElementById('copy').addEventListener('click', () => copy(false));

// Name the version on the link, so you can see what you are about to
// install without installing it first.
fetch('health').then(r => r.json()).then(d => {
  if (d.apk) document.getElementById('apk').textContent =
    `התקן את אפליקציית המקלדת · v${d.apk}`;
}).catch(() => {});
</script>
</html>
"""
