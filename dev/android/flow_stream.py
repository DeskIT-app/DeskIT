"""Stage 2 on the emulator (PHONE_LINK_PLAN.md, "Faster: the same sentence, at the desk's
speed"): a phone dictation sent while it is spoken and decoded as it arrives, on the home
door and through the account, flow by flow, and the release-to-text table by length.

    <venv python> dev\\android\\flow_stream.py [name ...]
    <venv python> dev\\android\\flow_stream.py self_check      no emulator: the stand-in alone

Build first, for the fake account AND the fake provider, as for flow_relay.py:
gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791 -PdeskitCloud=http://10.0.2.2:18793

What is real: the whole keyboard (its recorder, LiveStream, the door's /stream, the relay's
streamed pieces, the ladder), and on the PC's side server.py's PhoneDoor with its /stream
handler and Routes, relay.py with sb.py's live channel, phonestream.py's sessions, a real
rolling.Roller over each stream, and transcribers/local_whisper.py's own decode_window,
transcribe_with_head and trim. What is fake is the account (fake_pc), and the model under
local_whisper: a stand-in (``Model``) that takes as long as his real one does and hears the
probe's voice.

THE STAND-IN'S CLOCK is his app.log's (rate_from_applog.py in the lane's notes, numbers
only, 2026-11-27, app.log + .1 + .2): over 218 whole desk decodes of 0.8-24.5 s the
decoder took 0.245 s + 0.0246 s per second of audio, and the language check 0.180 s +
0.0017 s per second (p50 0.19 s, n=267). Every call of the stand-in costs the first,
whatever it is (a window while he speaks, the tail, a whole recording), and every
transcription the second on top. On his PC a window measured 0.70 s per 25 s (p50,
n=49) and a tail 0.370 s + 0.020 s per second: the stand-in is a little slower than his
GPU on a window and about his on a tail, and on a WHOLE recording past 25 s it is faster
than his (the relay's app.log lines: 78.1 s answered in 4.2 s, 40.4 s in 4.2 s, where
the line says 2.2 s and 1.2 s), so every "before" below is if anything kinder to the old
road than his PC would be.

THE VOICE (`--es ime voice`, ProbeReceiver): four seconds of tone, one of silence, again;
the k-th voiced second at 200 + 20 k Hz. The stand-in reads the pitch back as the word
"s<k>", so a transcript says exactly which seconds reached the model and in what order,
and the oracle of every dictation is the stand-in's own WHOLE decode of the same WAV:
streamed or not, rolled or not, the text must be that.
"""
import dataclasses
import io
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flow_door as fd                            # noqa: E402  (sets DESKIT_HOME and DESKIT_SUITE)

import numpy as np                                # noqa: E402

import phonestream                                # noqa: E402
import relay as relay_mod                         # noqa: E402
import rolling                                    # noqa: E402
import server as server_mod                       # noqa: E402
from recorder import frames_to_wav                # noqa: E402
from transcribers import local_whisper as lw      # noqa: E402

import drive                                      # noqa: E402

fa = fd.fa
check, until = fd.check, fd.until
PKG = drive.PKG
#: [local] rolling_window_s as defaults.toml ships it.
WINDOW_S = 25.0
#: app.log, 2026-11-27 (the module's docstring says how).
DECODE_A, DECODE_B = 0.245, 0.0246
DETECT_A, DETECT_B = 0.180, 0.0017
#: "Like mobile data": 2 Mbit/s up, 8 down, 50-150 ms each way (SlowLink). The emulator's
#: own `network speed` / `network delay` were tried first and measured to shape nothing on
#: this image, Wi-Fi or cellular (a 60 s recording, 1.92 MB, crossed in the same 2.9 s at
#: "2000:8000" as at "full"), so the shaping is done on the PC's side, in front of what the
#: phone talks to: the door for the home road, the account for the relay.
MOBILE_SPEED, MOBILE_DELAY = "2000:8000", "50:150"
UP_BPS, DOWN_BPS, DELAY_S = 2_000_000, 8_000_000, (0.05, 0.15)
#: The fake account behind a slow link: the APK talks to 18791, the link forwards here.
SLOW_ACCOUNT_PORT = 18801
#: What each timing measured: (road, network, before|after, seconds) -> [ms].
TABLE: dict[tuple, list[int]] = {}


# ------------------------------------------------------------------ the stand-in

class _W:
    def __init__(self, word, start, end, p=0.97):
        self.word, self.start, self.end, self.probability = word, start, end, p


class _S:
    def __init__(self, words):
        self.words = words
        self.text = "".join(w.word for w in words).strip()


def hear(audio: np.ndarray, rate: int = 16000) -> list:
    """The probe's voice, read back: a word per voiced second, "s<k>" for 200 + 20 k Hz,
    timed where it sits in this clip."""
    n, hop = 1600, 800                              # 0.1 s windows, 0.05 s apart: 10 Hz
    if audio.size < n:
        return []
    win = np.hanning(n)
    words, cur, first, last = [], None, 0.0, 0.0
    for at in range(0, audio.size - n + 1, hop):
        seg = audio[at:at + n]
        k = None
        if float(np.sqrt(np.mean(seg * seg))) > 0.05:
            spec = np.abs(np.fft.rfft(seg * win))
            hz = float(np.argmax(spec)) * rate / n
            k = int(round((hz - 200.0) / 20.0))
        t0, t1 = at / rate, (at + n) / rate
        if k is not None and k == cur:
            last = t1
            continue
        if cur is not None:
            words.append(_W(f" s{cur}", round(first, 2), round(last, 2)))
        cur, first, last = k, t0, t1
    if cur is not None:
        words.append(_W(f" s{cur}", round(first, 2), round(last, 2)))
    return words


class Model:
    """faster-whisper's WhisperModel as local_whisper calls it, as slow as his GPU is."""

    def __init__(self, timed: bool = True):
        self.timed = timed
        self.calls: list[float] = []

    def transcribe(self, audio, **kw):
        began = time.perf_counter()
        seconds = len(audio) / 16000.0
        words = hear(np.asarray(audio, dtype=np.float32))
        if self.timed:
            left = DECODE_A + DECODE_B * seconds - (time.perf_counter() - began)
            if left > 0:
                time.sleep(left)
        self.calls.append(round(seconds, 2))
        return iter([_S(words)] if words else []), None


class Detector:
    """The English model's language check, as long as his takes: Hebrew, always."""

    def __init__(self, timed: bool = True):
        self.timed = timed

    def detect_language(self, audio=None, vad_filter=True):
        if self.timed:
            time.sleep(DETECT_A + DETECT_B * len(audio) / 16000.0)
        return "he", 0.99, None


def standin(timed: bool = True) -> lw.LocalWhisperTranscriber:
    """local_whisper's own class with the stand-in model under it: its _choose, _decode,
    _settle, decode_window, transcribe_with_head and trim are the real ones."""
    t = lw.LocalWhisperTranscriber.__new__(lw.LocalWhisperTranscriber)
    t.name = "local"
    t._model, t._english, t._language = Model(timed), Detector(timed), "he"
    t.english_state, t._said_loading, t._english_threshold = "ready", False, 0.8
    t._initial_prompt, t._hotwords, t._beam_size = None, None, 5
    t._guards = {"word_timestamps": True}
    t._boilerplate, t._cleanup, t._fillers = (), False, ()
    t.last_timing, t.last_words, t.last_removed = {}, [], []
    t.last_warning, t.last_windows = None, []
    return t


def whole_text(wav: bytes) -> str:
    """The oracle: the stand-in's whole decode of the same recording, untimed."""
    return standin(timed=False).transcribe(wav)


def voice_pcm(seconds: float, start: int = 0) -> bytes:
    """ProbeReceiver's voice, the same arithmetic in Python: for a check with no phone."""
    g = np.arange(start, start + int(seconds * 16000))
    second = g // 16000
    word = (second // 5) * 4 + second % 5
    hz = 200.0 + 20.0 * word
    v = (9830.0 * np.sin(2 * np.pi * hz * g / 16000)).astype(np.int32)
    v[second % 5 == 4] = 0
    return v.astype("<i2").tobytes()


class StandInPc:
    """What main.App does with a phone's recording, with the stand-in for the model: the
    rolling transcriber over a stream (App._stream_roller, through _start_roller's own
    decode under the model lock), and the answer (App._transcribe_for_phone): the head,
    only the tail decoded now, or the whole recording."""

    def __init__(self):
        self.t = standin()
        self.lock = threading.Lock()
        self.log: list[dict] = []

    def begin(self, stream):
        def decode(wav, lead_s, keep_s):
            with self.lock:
                return self.t.decode_window(wav, lead_s, keep_s)
        r = rolling.Roller(stream.chunks_since, stream.sample_rate, decode, WINDOW_S,
                           frames_to_wav, overlap=self.t.can_overlap)
        r.start()
        return r

    def answer(self, wav: bytes, rolled=None) -> str:
        began = time.perf_counter()
        head = rolled.finish() if rolled is not None else None
        with self.lock:
            text = (self.t.transcribe_with_head(wav, head) if head is not None
                    else self.t.transcribe(wav))
        self.log.append({"seconds": (len(wav) - 44) / 32000.0, "streamed": rolled is not None,
                         "windows": len(head.windows) if head else 0,
                         "head_s": round(head.end_s, 1) if head else 0.0,
                         "busy_s": round(rolled.busy_s, 2) if rolled is not None else 0.0,
                         "ms": int((time.perf_counter() - began) * 1000), "text": text, "wav": wav})
        return text


# ------------------------------------------------------------------ the PC, both roads

class StreamDoorPc(fd.Pc):
    """flow_door's PC with the App's stream on its door: /stream feeds a real Roller."""

    def __init__(self, acct, model: StandInPc, *, stream: bool = True, slow: bool = False):
        super().__init__(acct)
        self.model, self.stream = model, (server_mod.STREAM_PROTO if stream else 0)
        self.routes = server_mod.Routes(self._stand_in, self._translate, punctuate=self._punctuate,
                                        lookup=self._lookup, review_scope="phone",
                                        stream_begin=model.begin if stream else None)
        #: How often the door's /stream was asked. The stand-in's log cannot say: a
        #: stream to a PC that rolls nothing is answered like a whole recording, and
        #: the first old_pc check passed with the keyboard streaming to it (2026-11-28).
        self.streams_asked = 0
        begun = self.routes.stream

        def counted(phone):
            self.streams_asked += 1
            return begun(phone)
        self.routes.stream = counted
        self.door = server_mod.PhoneDoor(self.cfg, self.routes)
        #: The door behind a link like mobile data (SlowLink): the row names its port.
        self.slow_wanted, self.slow = slow, None

    def up(self) -> "StreamDoorPc":
        port = self.door.start(self.anchors())
        if self.slow_wanted:
            if self.slow is None or self.slow.target != port:
                if self.slow is not None:
                    self.slow.close()
                self.slow = SlowLink(port)
            port = self.slow.port
        self.write(port=port)
        return self

    def down(self):
        super().down()

    def _stand_in(self, wav: bytes, rolled=None):
        self.arrived.set()
        self.heard.append(wav)
        return self.model.answer(wav, rolled), "local", None


def stream_relay_pc(acct, model: StandInPc, *, stream: bool = True):
    import flow_relay as fr

    class StreamRelayPc(fr.RelayPc):
        def __init__(self):
            super().__init__(acct)
            self.routes = server_mod.Routes(self._stand_in,
                                            stream_begin=model.begin if stream else None)
            self.relay = relay_mod.for_app(
                can_take=lambda: self.why, allowed=lambda: self.on,
                transcribe=lambda wav, peer: self.routes.handle("/transcribe", wav, peer),
                stream=self.routes.stream if stream else None)

        def _stand_in(self, wav: bytes, rolled=None):
            self.heard.append(wav)
            self.answered_at = time.perf_counter()
            return model.answer(wav, rolled), "local", None

    return StreamRelayPc()


def join_with(acct, pc) -> None:
    """The phone joins; the PC's row (its /stream or none) and door follow, as on an Approve."""
    acct._door_pc = pc
    pc.up()
    fa.join(acct)
    pc.up()


# ------------------------------------------------------------------ the phone

def voice() -> None:
    """The emulator's silent microphone given the probe's voice, on the keyboard running now."""
    fa.told("--es", "ime", "voice")


def hold(seconds: float) -> None:
    """A real press, [seconds] long, on the real keyboard; the voice already on."""
    x, y = fd.spot("pill")
    drive.adb("shell", "input", "swipe", x, y, x, y, int(seconds * 1000), check=False,
              timeout=seconds + 60)


def released(road: str = "") -> list[int]:
    """'dictation: a text N ms after the release' lines, the keyboard's own clock: the
    release is DictationIme.deliverRecording's, the end is the text in hand."""
    tail = rf" \({road}\)" if road else ""
    return [int(x) for x in re.findall(rf"dictation: a text (\d+) ms after the release{tail}(?:\r?\n|$)",
                                       fa.log_so_far(), re.M)]


def throttle(net: str) -> None:
    if net == "mobile":
        drive.adb("emu", "network", "speed", MOBILE_SPEED, check=False)
        drive.adb("emu", "network", "delay", MOBILE_DELAY, check=False)
    else:
        drive.adb("emu", "network", "speed", "full", check=False)
        drive.adb("emu", "network", "delay", "none", check=False)


class SlowLink:
    """A link like mobile data between the phone and the door: the emulator's own
    `network speed` shapes its cellular modem and not the Wi-Fi a door is reached on
    (measured here: a 30 s recording's 960 KB crossed as fast at "2000:8000" as at
    "full"), so the door's road is shaped on the PC's side instead. A TCP relay on a
    port of its own, in front of the real door (TLS passes through it untouched):
    phone to PC at ``up`` bit/s, PC to phone at ``down``, each byte held ``delay``
    (a random value in the range, per chunk) before it goes on, in order."""

    def __init__(self, target: int, up: int = UP_BPS, down: int = DOWN_BPS,
                 delay: tuple[float, float] = DELAY_S, listen: int = 0):
        import random
        import socket as socket_mod
        self.target, self.up, self.down, self.delay = target, up, down, delay
        self._random = random.Random(7)
        self._sock = socket_mod.socket()
        self._sock.bind(("127.0.0.1", listen))
        self._sock.listen(16)
        self.port = self._sock.getsockname()[1]
        self._closing = False
        threading.Thread(target=self._accept, daemon=True, name="slow-link").start()

    def _accept(self):
        import socket as socket_mod
        while not self._closing:
            try:
                phone, _ = self._sock.accept()
            except OSError:
                return
            try:
                pc = socket_mod.create_connection(("127.0.0.1", self.target), timeout=5)
                # the 5 s was for the connect: a PC silent through a long upload is no
                # reason to cut the reply (it was, and every long recording broke)
                pc.settimeout(None)
            except OSError:
                phone.close()
                continue
            for src, dst, bps in ((phone, pc, self.up), (pc, phone, self.down)):
                threading.Thread(target=self._pump, args=(src, dst, bps), daemon=True).start()

    def _pump(self, src, dst, bps):
        import queue as queue_mod
        q: queue_mod.Queue = queue_mod.Queue()

        def deliver():
            while True:
                item = q.get()
                if item is None:
                    break
                due, data = item
                wait = due - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                try:
                    dst.sendall(data)
                except OSError:
                    break
            try:
                dst.shutdown(1)
            except OSError:
                pass

        threading.Thread(target=deliver, daemon=True).start()
        free = time.monotonic()                   # when the link is free for the next byte
        try:
            while True:
                data = src.recv(4096)
                if not data:
                    break
                free = max(free, time.monotonic()) + len(data) * 8 / bps
                wait = free - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                q.put((time.monotonic() + self._random.uniform(*self.delay), data))
        except OSError:
            pass
        q.put(None)

    def close(self):
        self._closing = True
        try:
            self._sock.close()
        except OSError:
            pass


def landed_as_whole(model: StandInPc, before: int) -> bool:
    """Every dictation since [before] gave exactly the whole decode's text."""
    return all(e["text"] == whole_text(e["wav"]) for e in model.log[before:])


# ------------------------------------------------------------------ the flows

def flow_self_check():
    """No emulator: the probe's voice, streamed through a real Roller as it would arrive,
    against the stand-in's whole decode. The same words, once each, at every length."""
    for seconds in (10.0, 31.0, 62.0, 95.0, 300.0):
        pcm = voice_pcm(seconds)
        wav = frames_to_wav([np.frombuffer(pcm, dtype="<i2")], 16000)
        whole = whole_text(wav)
        n_voiced = sum(1 for s in range(int(np.ceil(seconds))) if s % 5 != 4)
        check(f"{seconds:.0f} s: the whole decode hears every voiced second, in order",
              whole == " ".join(f"s{k}" for k in range(n_voiced)), whole[:120])
        pc = StandInPc()
        pc.t = standin(timed=False)
        s = phonestream.PhoneStream()
        r = pc.begin(s)
        step = 3200
        for i in range(0, len(pcm), step):                     # 50x real time
            s.feed(pcm[i:i + step])
            if i % (step * 25) == 0:
                time.sleep(0.04)
        time.sleep(0.5)
        text = pc.answer(wav, r)
        e = pc.log[-1]
        check(f"{seconds:.0f} s streamed: {e['windows']} window(s) before the end, the same text",
              text == whole and (seconds < 30 or e["windows"] >= 1), f"{text[:80]} / {whole[:80]}")


def flow_lands_door():
    """At home, the PC's row says it reads /stream: a 40 s dictation goes up while it is
    spoken, the PC decodes its stretches as they come, and at the release only the tail is
    left. The text is the whole decode's, once; the line says local."""
    acct = fa.fresh()
    model = StandInPc()
    try:
        join_with(acct, StreamDoorPc(acct, model))
        fd.field()
        voice()
        hold(40.0)
        check("the text lands", until(lambda: len(model.log) == 1 and model.log[0]["text"] in fd.in_field(), 30),
              fd.in_field()[:200])
        e = model.log[0] if model.log else {}
        check("it came as a stream, and windows were decoded while it was spoken",
              e.get("streamed") and e.get("windows", 0) >= 1, str({k: v for k, v in e.items() if k != "wav"}))
        check("the text is the whole decode's: no second lost, none twice", landed_as_whole(model, 0))
        check("the line says how long it was, from this PC", fd.says(r"status=\d+\.\d s · local reachable", 10), fd.status())
        check("the phone measured it", len(released()) == 1, str(released()))
        check("nothing waits", until(fd.spool_empty, 10), fd.spooled())
        print(f"      release to text {released()} ms; the PC: {e.get('windows')} window(s) to "
              f"{e.get('head_s')} s, the end {e.get('ms')} ms", flush=True)
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_lands_relay():
    """Away from home, the PC's row says it reads a stream: the pieces go up through the
    account while it is spoken, piece 0 last, and the PC decodes as they come. The text is
    the whole decode's, once, through the account; the release owes the door no moment."""
    import flow_backup as fb
    acct = fa.fresh(backup="off")
    model = StandInPc()
    pc = None
    try:
        join_with(acct, StreamDoorPc(acct, model))
        fb.away(acct._door_pc)
        pc = stream_relay_pc(acct, model).up()
        fd.field()
        until(lambda: "reachable=true" in fd.status(), 20)
        voice()
        hold(40.0)
        check("the text lands, through the account",
              until(lambda: len(model.log) == 1 and model.log[0]["text"] in fd.in_field(), 40), fd.in_field()[:200])
        e = model.log[0] if model.log else {}
        check("it came as a stream, decoded while it was spoken",
              e.get("streamed") and e.get("windows", 0) >= 1 and pc.relay.counts.get("streamed") == 1,
              f"{pc.relay.counts} {dict((k, v) for k, v in e.items() if k != 'wav')}")
        check("the text is the whole decode's", landed_as_whole(model, 0))
        check("the line says through the account", fd.says(r"local via your account", 10), fd.status())
        check("what crossed the account: sealed pieces only", "s0 s1" not in str(acct.events("link")))
        print(f"      release to text {released('relay')} ms; the PC: {e.get('windows')} window(s) "
              f"to {e.get('head_s')} s; the account counted {acct.realtime}", flush=True)
        for line in re.findall(r"(?:relay|stream|dictation|backup): .*", fa.log_so_far()):
            print("        " + line.strip(), flush=True)
    finally:
        if pc is not None:
            pc.down()
        fb.home_again()
        acct._door_pc.down()
        acct.stop()


def flow_old_pc():
    """A PC whose row names no /stream (a PC from before stage 2, or one with [server]
    stream off): at home the recording goes whole at the release, as it always did. The
    door's /stream is never asked: a PC from before stage 2 has none, and would answer a
    stream with a 404 the keyboard takes for the dictation's answer."""
    acct = fa.fresh()
    model = StandInPc()
    try:
        pc = StreamDoorPc(acct, model, stream=False)
        join_with(acct, pc)
        fd.field()
        voice()
        hold(8.0)
        check("the text lands", until(lambda: len(model.log) == 1, 30), fd.in_field()[:200])
        check("whole, and nothing streamed", model.log and not model.log[0]["streamed"], str(model.log[:1]))
        check("the same text as ever", landed_as_whole(model, 0))
        check("the door's /stream was never asked, and the keyboard began no stream",
              pc.streams_asked == 0 and "stream: the door" not in fa.log_so_far(),
              f"asked {pc.streams_asked}; " + "; ".join(re.findall(r"stream: .*", fa.log_so_far()))[:200])
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_old_pc_away():
    """The same PC away from home: its row names no /stream, so nothing of the recording
    crosses the account while it is spoken. The pieces go up at the release, whole, as
    stage 3 sends them, and the text lands through the account."""
    import flow_backup as fb
    acct = fa.fresh(backup="off")
    model = StandInPc()
    pc = None
    try:
        join_with(acct, StreamDoorPc(acct, model, stream=False))
        fb.away(acct._door_pc)
        pc = stream_relay_pc(acct, model, stream=False).up()
        fd.field()
        until(lambda: "reachable=true" in fd.status(), 20)
        voice()
        quiet = acct.realtime["largest"]
        finger = threading.Thread(target=hold, args=(10.0,))
        finger.start()
        time.sleep(8.5)
        # a ping and its pong are a few hundred bytes; an audio piece is about 128 KB
        spoken = acct.realtime["largest"]
        finger.join()
        check("the text lands, through the account",
              until(lambda: len(model.log) == 1 and model.log[0]["text"] in fd.in_field(), 40), fd.in_field()[:200])
        check("no audio crossed the account while it was spoken", quiet < 20000 and spoken < 20000,
              f"largest message before the hold {quiet}, 8.5 s into it {spoken}")
        log = fa.log_so_far()
        check("the pieces went up at the release, whole: the keyboard began no stream",
              "relay: streamed" not in log and re.search(r"relay: \d+ pieces up", log) is not None,
              "; ".join(re.findall(r"relay: .*", log))[-300:])
        e = model.log[0] if model.log else {}
        check("whole on the PC, and the same text as ever", e and not e["streamed"] and landed_as_whole(model, 0),
              str(e.get("streamed")))
        check("the line says through the account", fd.says(r"local via your account", 10), fd.status())
    finally:
        if pc is not None:
            pc.down()
        fb.home_again()
        acct._door_pc.down()
        acct.stop()


def flow_continue_whole():
    """A stream the keyboard closed on is cancelled, said to the PC; Continue streams the
    whole recording again from its first byte, kept part first; the end lands it once.
    The PC heard one cancelled stream and one answered one, and the text has every second
    of both parts, once."""
    import flow_keep as fk
    acct = fa.fresh()
    model = StandInPc()
    try:
        pc = StreamDoorPc(acct, model)
        join_with(acct, pc)
        fd.field()
        voice()
        fk.lock(12)
        fk.hide()
        check("the keyboard closed on it: nothing answered", until(lambda: True, 2) and not model.log)
        fk.show_again()
        voice()
        check("the mic offers Continue", until(lambda: fk.offered(10), 15), fk.st()["raw"][:200])
        fk.tap("pill")
        check("Continue: locked again", until(lambda: fk.st()["locked"], 10), fk.st()["raw"][:200])
        time.sleep(8)
        fk.tap("pill")
        check("the end lands it", until(lambda: len(model.log) == 1, 40), fd.in_field()[:200])
        e = model.log[0] if model.log else {}
        seconds = e.get("seconds", 0)
        check("the whole recording, both parts, once (about 20 s)", 18 <= seconds <= 24, str(seconds))
        check("streamed from its first byte, kept part first: the whole decode's text",
              e.get("streamed") and landed_as_whole(model, 0), str({k: v for k, v in e.items() if k != "wav"}))
        cancelled = fa.log_so_far().count("stream: cancelled on the door")
        check("the first stream was cancelled, said to the PC", cancelled >= 1, str(cancelled))
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_broken_falls_back():
    """The door goes down under the stream and comes back: the stream broke, so at the
    release the recording goes whole on the same road, /transcribe, and lands once."""
    acct = fa.fresh()
    model = StandInPc()
    try:
        pc = StreamDoorPc(acct, model)
        join_with(acct, pc)
        fd.field()
        voice()
        x, y = fd.spot("pill")
        finger = threading.Thread(target=lambda: drive.adb("shell", "input", "swipe", x, y, x, y, 14000,
                                                           check=False, timeout=80))
        finger.start()
        time.sleep(5)
        port = pc.door.port
        pc.door.stop()
        time.sleep(0.5)
        pc.door.start(pc.anchors())
        check("the door came back on its port", pc.door.port == port, f"{port} -> {pc.door.port}")
        finger.join()
        check("the text lands", until(lambda: len(model.log) == 1, 40), fd.in_field()[:200])
        e = model.log[0] if model.log else {}
        check("whole, on the same road: the stream had broken", e and not e["streamed"], str(e.get("streamed")))
        check("once, and the whole decode's text", len(model.log) == 1 and landed_as_whole(model, 0))
        check("the keyboard said the stream broke", "stream: the door broke" in fa.log_so_far())
    finally:
        acct._door_pc.down()
        acct.stop()


def flow_discard():
    """A held recording thrown away (a swipe down): the stream is cancelled, the PC
    answers nothing, the field stays empty."""
    acct = fa.fresh()
    model = StandInPc()
    try:
        join_with(acct, StreamDoorPc(acct, model))
        fd.field()
        voice()
        x, y = fd.spot("pill")
        drive.adb("shell", "input", "swipe", x, y, x, y + 420, 1500, check=False, timeout=60)
        time.sleep(0.3)
        # at once: a stream left going would give itself up only ORPHAN_MS (3 s) after the
        # recorder stopped, and that is not the discard saying so
        check("the stream was cancelled at the discard, said to the PC",
              "stream: cancelled on the door" in fa.log_so_far())
        time.sleep(3)
        check("nothing answered, nothing in the field", not model.log and "s0" not in fd.in_field(),
              str(len(model.log)))
    finally:
        acct._door_pc.down()
        acct.stop()


_account_link: list = []


def _fresh(slow: bool):
    """fa.fresh, and for a slow block the account behind a SlowLink on the port the APK
    was built for. One process is one or the other: fake_pc keeps its listeners."""
    if not slow:
        return fa.fresh(backup="off")
    import fake_pc
    drive.clear_app()
    fa.told("--es", "backup", "off")
    acct = fake_pc.FakeAccount(port=SLOW_ACCOUNT_PORT)
    acct.start()
    if not _account_link:
        _account_link.append(SlowLink(SLOW_ACCOUNT_PORT, listen=18791))
    return acct


def _timing_block(road: str, stream: bool, lengths: list[float], nets: list[str]) -> None:
    """One account, one road, before or after. The door's "mobile" is a SlowLink in
    front of it, so it is a block of its own; the relay's is the emulator's own shaping
    of its cellular link, which the relay rides off the Wi-Fi."""
    import flow_backup as fb
    slow = nets == ["mobile"]
    acct = _fresh(slow)
    model = StandInPc()
    pc = rpc = None
    when = "after" if stream else "before"
    try:
        pc = StreamDoorPc(acct, model, stream=stream, slow=(road == "door" and slow))
        join_with(acct, pc)
        if road == "relay":
            fb.away(pc)
            rpc = stream_relay_pc(acct, model, stream=stream).up()
        fd.field()
        if road == "relay":
            until(lambda: "reachable=true" in fd.status(), 20)
        for net in nets:
            time.sleep(1)
            for seconds in lengths:
                voice()
                before = len(released("relay" if road == "relay" else ""))
                n = len(model.log)
                hold(seconds)
                ok = until(lambda: len(released("relay" if road == "relay" else "")) > before
                           and len(model.log) > n, seconds + 120, 0.5)
                got = released("relay" if road == "relay" else "")[before:]
                e = model.log[-1] if len(model.log) > n else {}
                check(f"{road}, {net}, {when}, {seconds:.0f} s: landed, the whole decode's text",
                      ok and e.get("text") == whole_text(e.get("wav", b"")) and e.get("text", "") in fd.in_field()
                      and e.get("streamed") == stream, f"{got} {e.get('streamed')}")
                TABLE[(road, net, when, int(seconds))] = got
                print(f"      {road:5} {net:6} {when:6} {seconds:4.0f} s: release to text {got} ms; PC end "
                      f"{e.get('ms')} ms, {e.get('windows')} window(s) to {e.get('head_s')} s", flush=True)
                time.sleep(2)
    finally:
        throttle("full")
        if rpc is not None:
            rpc.down()
        if road == "relay":
            fb.home_again()
        if pc is not None:
            pc.down()
            if pc.slow is not None:
                pc.slow.close()
        acct.stop()


def flow_timing():
    """Release to text by length, before (a PC whose row names no /stream: the old road,
    the same APK) and after, on the door and through the account, the emulator's network
    unthrottled and like mobile data. DESKIT_STREAM_LENGTHS, _ROADS, _NETS narrow it."""
    lengths = [float(x) for x in os.environ.get("DESKIT_STREAM_LENGTHS", "10,30,60,90").split(",")]
    roads = os.environ.get("DESKIT_STREAM_ROADS", "door,relay").split(",")
    nets = os.environ.get("DESKIT_STREAM_NETS", "full").split(",")
    if "full" in nets and "mobile" in nets:
        raise SystemExit("one process is either the full network or the slow one "
                         "(fake_pc keeps its listeners): DESKIT_STREAM_NETS=full, then =mobile")
    for road in roads:
        for stream in (False, True):
            _timing_block(road, stream, lengths, nets)
    print("      road   network  when    seconds  release to text (ms)", flush=True)
    for (road, net, when, seconds), got in sorted(TABLE.items()):
        print(f"      {road:6} {net:8} {when:7} {seconds:7}  {got}", flush=True)


FLOWS = {name[5:]: fn for name, fn in list(globals().items()) if name.startswith("flow_")}


def main() -> None:
    names = sys.argv[1:] or [n for n in FLOWS if n != "self_check"]
    if names == ["self_check"]:
        flow_self_check()
        print(f"{fa._passed} passed, {fa._failed} failed", flush=True)
        sys.exit(1 if fa._failed else 0)
    apk = fd.APK if hasattr(fd, "APK") else None
    apk = apk or (Path(__file__).resolve().parents[2] / "android" / "app" / "build" / "outputs" / "apk"
                  / "debug" / "app-debug.apk")
    if not fa.built_for_the_fake(apk):
        sys.exit("this APK speaks to the real project, and no flow may: "
                 "gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791 -PdeskitCloud=http://10.0.2.2:18793")
    drive.adb("install", "-r", "-g", apk, timeout=300)
    drive.adb("logcat", "-G", "8M", check=False)
    if fa.sdk() >= fd.WIFI_ONLY:
        fd.settled()
    try:
        for name in names:
            print(f"--- {name}", flush=True)
            # each flow reads its own lines: log_so_far() keeps everything since the
            # last forget, and a check like "the stream was cancelled" was satisfied
            # by the flow before it when several ran in one process
            fa.log_forget()
            try:
                FLOWS[name]()
            except (AssertionError, subprocess.TimeoutExpired) as e:
                check(f"{name} ran to its end", False, str(e)[:500])
                drive.shot(f"failed_stream_{name}")
            finally:
                # the keyboard's own lines of this flow, numbers only, for the report
                lines = re.findall(r"(?:relay|stream|dictation|backup|link): .*", fa.log_so_far())
                with open(drive.OUT / "flow_stream_keyboard.log", "a", encoding="utf-8") as f:
                    f.write(f"--- {name} {time.strftime('%H:%M:%S')}\n" + "\n".join(lines) + "\n")
    finally:
        throttle("full")
        shutil.rmtree(fd.HOME, ignore_errors=True)
    print(f"{fa._passed} passed, {fa._failed} failed", flush=True)
    sys.exit(1 if fa._failed else 0)


if __name__ == "__main__":
    main()
