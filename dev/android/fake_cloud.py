"""Groq and Gemini as the keyboard's cloud backup speaks to them, faked on loopback
for the emulator (stage 2b): what the phone reaches as http://10.0.2.2:18793 in a
build made with `-PdeskitCloud=http://10.0.2.2:18793`.

It answers the one request each provider is sent (Groq's transcriptions, Gemini's
generateContent) and the one small key test (the list of models), checks what the
real ones would refuse (the key, the multipart body, the WAV), and records what it
saw: whether the key matched, the client's name, the fields. It never records or
logs a key: a key is compared and dropped.

M15 measured the real Groq on 2026-11-11 (the plan's row); this is not that, it is
the shape of it.
"""
import http.server
import json
import re
import socketserver
import threading
import time


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    cloud = None


class _Door(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, status: int, obj) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        cloud = self.server.cloud
        if cloud is None:
            self._send(503, {"error": "nobody"})
            return
        cloud.answer_get(self)

    def do_POST(self):
        cloud = self.server.cloud
        if cloud is None:
            self._send(503, {"error": "nobody"})
            return
        cloud.answer_post(self, self._body())


_LISTENERS: dict[int, _Server] = {}


def _parts(body: bytes, ctype: str) -> dict[str, bytes]:
    """multipart/form-data by hand: {name: value}, the file's bytes under its field."""
    m = re.search(r"boundary=([^;]+)", ctype or "")
    if not m:
        return {}
    sep = b"--" + m.group(1).strip().encode("ascii")
    out: dict[str, bytes] = {}
    for chunk in body.split(sep)[1:]:
        if chunk.startswith(b"--"):
            break
        head, _, value = chunk.lstrip(b"\r\n").partition(b"\r\n\r\n")
        name = re.search(rb'name="([^"]+)"', head)
        if name:
            out[name.group(1).decode("utf-8")] = value[:-2] if value.endswith(b"\r\n") else value
    return out


class FakeCloud:
    """One provider pair on one port. ``mode``: ok | refuse | limit | slow | down."""

    def __init__(self, port: int = 18793):
        self.port = port
        self.key = ""                 # the key the provider takes; "" takes none
        self.gemini_key = ""
        self.text = "the-cloud-heard-this"
        self.mode = "ok"
        self.delay = 0.0
        self.mutex = threading.Lock()
        #: one entry per request: path, whether the key matched, the client's name,
        #: the fields (never the key, never the audio)
        self.calls: list[dict] = []

    def start(self) -> "FakeCloud":
        server = _LISTENERS.get(self.port)
        if server is None:
            server = _LISTENERS[self.port] = _Server(("127.0.0.1", self.port), _Door)
            threading.Thread(target=server.serve_forever, daemon=True).start()
        server.cloud = self
        return self

    def stop(self) -> None:
        server = _LISTENERS.get(self.port)
        if server is not None and server.cloud is self:
            server.cloud = None

    def _note(self, h, matched: bool, **extra) -> None:
        with self.mutex:
            self.calls.append({"path": h.path.split("?")[0], "key_ok": matched,
                               "agent": h.headers.get("User-Agent", ""), **extra})

    def asked(self, path_part: str = "") -> list[dict]:
        with self.mutex:
            return [dict(c) for c in self.calls if path_part in c["path"]]

    def _groq_key(self, h) -> bool:
        return bool(self.key) and h.headers.get("Authorization") == f"Bearer {self.key}"

    def _gemini_key(self, h) -> bool:
        return bool(self.gemini_key) and h.headers.get("x-goog-api-key") == self.gemini_key

    def answer_get(self, h) -> None:
        path = h.path.split("?")[0]
        if path == "/openai/v1/models":
            ok = self._groq_key(h)
            self._note(h, ok)
            h._send(200 if ok else 401, {"data": [{"id": "whisper-large-v3-turbo"}]} if ok
                    else {"error": {"message": "Invalid API Key"}})
            return
        if path == "/v1beta/models":
            ok = self._gemini_key(h)
            self._note(h, ok)
            h._send(200 if ok else 400, {"models": [{"name": "models/gemini-flash-latest"}]} if ok
                    else {"error": {"message": "API key not valid. Please pass a valid API key."}})
            return
        h._send(404, {"error": "no such route"})

    def answer_post(self, h, body: bytes) -> None:
        path = h.path.split("?")[0]
        if self.delay:
            time.sleep(self.delay)
        if path == "/openai/v1/audio/transcriptions":
            ok = self._groq_key(h)
            parts = _parts(body, h.headers.get("Content-Type", ""))
            wav = parts.get("file", b"")
            fields = {k: v.decode("utf-8", "replace") for k, v in parts.items() if k != "file"}
            self._note(h, ok, fields=fields, wav=wav[:4] == b"RIFF" and wav[8:12] == b"WAVE",
                       wav_bytes=len(wav))
            if not ok or self.mode == "refuse":
                h._send(401, {"error": {"message": "Invalid API Key", "type": "invalid_request_error"}})
            elif self.mode == "limit":
                h._send(429, {"error": {"message": "Rate limit reached for model"}})
            elif fields.get("model") != "whisper-large-v3-turbo" or not wav.startswith(b"RIFF"):
                h._send(400, {"error": {"message": "bad request"}})
            else:
                h._send(200, {"text": " " + self.text})
            return
        m = re.match(r"^/v1beta/models/([^:/]+):generateContent$", path)
        if m:
            ok = self._gemini_key(h)
            try:
                payload = json.loads(body.decode("utf-8"))
                inline = payload["contents"][0]["parts"][0]["inlineData"]
                has_wav = inline["mimeType"] == "audio/wav" and len(inline["data"]) > 40
            except (ValueError, KeyError, IndexError, TypeError):
                has_wav = False
            self._note(h, ok, model=m.group(1), wav=has_wav)
            if not ok:
                h._send(400, {"error": {"message": "API key not valid. Please pass a valid API key."}})
            else:
                h._send(200, {"candidates": [{"content": {"parts": [{"text": self.text}]}}]})
            return
        h._send(404, {"error": "no such route"})
