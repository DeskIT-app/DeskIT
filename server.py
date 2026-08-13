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
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

log = logging.getLogger("app")

APP_DIR = Path(__file__).resolve().parent
TOKEN_FILE = APP_DIR / "server_token.txt"
APK = (APP_DIR / "android" / "app" / "build" / "outputs" / "apk"
       / "debug" / "app-debug.apk")

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
    """
    try:
        out = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                             errors="replace", timeout=timeout, check=False)
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
    server_version = "HebrewDictation"

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
            self.send_header("Content-Disposition",
                             'attachment; filename="HebrewDictation.apk"')
            self.end_headers()
            try:
                self.wfile.write(APK.read_bytes())
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif path == "/health":
            self._json(200, {"ok": True,
                             "backend": self.server.backend_name()})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0].rstrip("/") != "/transcribe":
            self._json(404, {"error": "not found"})
            return
        if not self._authorised():
            log.warning("rejected an unauthorised /transcribe from %s",
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
        raw = self.rfile.read(length)
        try:
            wav, seconds = to_wav(raw)
        except Exception as e:
            log.warning("phone sent audio we could not decode: %s", e)
            self._json(400, {"error": f"could not decode the audio: {e}"})
            return
        try:
            text, backend = self.server.transcribe(wav)
        except Exception as e:
            log.warning("phone transcription failed: %s", e)
            self._json(503, {"error": str(e)})
            return
        log.info("phone: %.1f s -> %d chars via %s", seconds, len(text),
                 backend)
        self._json(200, {"text": text, "seconds": round(seconds, 2),
                         "backend": backend})


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, token, transcribe, backend_name):
        super().__init__(addr, _Handler)
        self.token = token
        self.transcribe = transcribe
        self.backend_name = backend_name


class PhoneServer:
    """Owns the socket and the thread. Never fatal: if it cannot start,
    the desktop hotkey must keep working regardless."""

    def __init__(self, cfg, transcribe, backend_name):
        self.cfg = cfg
        self._transcribe = transcribe
        self._backend_name = backend_name
        self._srv: _Server | None = None
        self._thread: threading.Thread | None = None
        self.url: str | None = None

    def start(self) -> None:
        port = self.cfg.server.port
        host = self.cfg.server.host.strip() or "127.0.0.1"
        token = load_token()
        self._srv = _Server((host, port), token, self._transcribe,
                            self._backend_name)
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
         background: #10131a; color: #e8ecf4; font: 17px/1.5 system-ui,
         -apple-system, "Segoe UI", Roboto, sans-serif;
         padding: 24px calc(24px + env(safe-area-inset-right))
                  calc(24px + env(safe-area-inset-bottom))
                  calc(24px + env(safe-area-inset-left)); }
  #mic { width: 190px; height: 190px; border-radius: 50%; border: none;
         background: #2d6cdf; color: #fff; font-size: 20px; font-weight: 600;
         box-shadow: 0 10px 34px rgba(45,108,223,.42);
         transition: transform .12s, background .12s, box-shadow .12s;
         /* a long press must not raise selection or the callout menu */
         touch-action: none; user-select: none; -webkit-user-select: none;
         -webkit-touch-callout: none; }
  #mic:disabled { background: #39404e; box-shadow: none; }
  #mic.rec { background: #d6392f; transform: scale(1.07);
             box-shadow: 0 0 0 14px rgba(214,57,47,.18); }
  #status { min-height: 1.5em; color: #9aa6bd; text-align: center; }
  #out { width: min(560px, 100%); min-height: 8.5em; padding: 14px 16px;
         border-radius: 14px; border: 1px solid #29303d; background: #171b24;
         color: #e8ecf4; font: inherit; resize: vertical; }
  #copy { padding: 12px 22px; border-radius: 11px; border: 1px solid #39415280;
          background: #1d2330; color: #cfd070; color: #d8dde8; font: inherit; }
  .hint { color: #6d788d; font-size: 14px; text-align: center; }
</style>

<button id="mic">החזק ודבר</button>
<div id="status">מוכן</div>
<textarea id="out" placeholder="הטקסט יופיע כאן" dir="auto"></textarea>
<button id="copy">העתק</button>
<div class="hint">מחזיקים, מדברים, משחררים. הטקסט מועתק אוטומטית.</div>
<a class="hint" href="app.apk" style="color:#7fa6ee">התקן את אפליקציית המקלדת (APK)</a>

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
  statusEl.style.color = bad ? '#e8837b' : '#9aa6bd';
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
</script>
</html>
"""
