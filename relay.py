"""The sealed relay through the account: a phone away from home reaches this
PC's model (PHONE_LINK_PLAN.md stage 3, Q1, his answer of 2026-11-11: "also
through the account").

Away from home a phone has no road to this PC: his carrier's NAT is the hard
kind and his home has no IPv6 (M2), and so it is for many people. Every
signed-in copy already holds one websocket on the account's own private
topic, ``user:<uid>`` (sb._live_once), and so does the phone while it is
dictating. So the recording crosses that channel, in pieces, every piece
sealed under the account key, and the text comes back the same way. The
server, and anybody without the account key, carries sealed bytes and their
sizes and nothing else.

ONE PIECE ON THE WIRE (a broadcast payload, event ``link``)::

    {"device": <from>, "to": <to, or "*">, "rid": <request>, "n": <piece>,
     "s": "v1.<base64>"}

``s`` is vault.seal over ``<head JSON>\\n<body>`` with the AAD
``link/{uid}/{from}/{to}/{rid}/{n}`` (``AAD``): who sent it, who it is for,
which request and which piece are bound into the seal, so a piece moved to
another request, another place in it, another sender or another PC does not
open. The head says what the piece is (``k``):

    phone -> "*"  ping   is a PC of this account there, and can it take one?
    PC -> phone   pong   {"ready": true} or {"ready": false, "why": words}
    phone -> PC   audio  a slice of the WAV, in ``body``: pieces 0 .. N-1
    phone -> PC   end    piece N: {"frames": N, "bytes", "sha256", "at"}
    PC -> phone   took   piece 1: every piece is in, the model has it
    PC -> phone   text   piece 2: {"status", "body"}, /transcribe's answer

A ping is answered with no model involved: the phone learns while the person
speaks whether this PC is there, so the release already knows which road
the recording takes (Backup.kt, Road.next).

WHO MAY ASK. Only a phone of the account: the ``device`` of every piece
must be a phone whose row opens under the account key and that is not on the
forgotten list (phone.anchors(), the door's own list). Anything else is not
opened. The seal already keeps out anybody without the key; the list keeps
out a device of the account that was forgotten. A request is taken once: its
id is remembered for ``SEEN_S`` (a replay inside that window is dropped
whole), and an ``end`` whose own clock (``at``, sealed) is further than
``SKEW_S`` from this PC's is dropped too, so a replay after the window is
dropped by the clock. A phone's clock can be off; ``SKEW_S`` is wide for it.

WHAT IT DOES WITH ONE. The same as the phone door: ``Routes.handle(
"/transcribe", wav, peer)``, so the same detection, vocabulary, repair pass,
``recent\\`` and second reading, and the same logs. The answer goes back as
one sealed piece, by REST (sb.send_link, purpose ``link``, so net.py asks the
gate for every one).

THE BUDGET (Supabase Free, shared by every DeskIT user, read 2026-11-11):
256 KB a broadcast, 100 messages a second, 2 million messages and 5 GB of
egress a month, each broadcast counted once sent and once per device that
receives it. A WAV is 32,000 bytes a second, so a piece carries
``FRAME_BYTES`` (3 s), about 128 KB once sealed, half the cap. Egress binds
first: about 2.6 MB a minute of speech for each PC that hears it. The plan
has the arithmetic (stage 3, "the budget").

This module imports no transport and holds no key: it asks vault.py for
the account key per piece and drops it. Never logged: a word, a key, a
sealed value, an address.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict

log = logging.getLogger("app")

#: What this PC speaks, in every head. A head of another version is not taken.
PROTO = 1
#: The AAD of every piece.
AAD = "link/{uid}/{frm}/{to}/{rid}/{n}"
#: Audio bytes in one piece: 3.0 s of 16 kHz 16-bit mono. Sealed and in
#: base64 it is about 128 KB, half of Supabase Free's 256 KB a broadcast.
FRAME_BYTES = 96_000
#: The broadcast cap on Supabase Free (its limits page, 2026-11-11). A piece
#: is refused here before it would be refused there.
PAYLOAD_MAX = 256_000
#: The longest recording a phone makes (Recorder.MAX_SECONDS, 300 s), in
#: pieces, and a little room.
MAX_FRAMES = 110
MAX_BYTES = MAX_FRAMES * FRAME_BYTES
#: A request's id is remembered this long: a replay inside it is dropped.
SEEN_S = 12 * 3600.0
SEEN_MAX = 4096
#: ...and an ``end`` whose own clock is further than this from this PC's
#: is dropped, so a replay after the window is too. Wide, because a phone's
#: clock can be off (Account.kt says by how much).
SKEW_S = 11 * 3600.0
#: A request whose pieces stop coming is let go after this long.
ASSEMBLY_S = 120.0
#: After the ``end``, a piece still on its way gets this long.
STRAGGLE_S = 3.0
#: The pieces of the PC's own answers.
N_PONG, N_TOOK, N_TEXT = 0, 1, 2
#: Requests being put together at once. A phone sends one at a time.
MOST_OPEN = 8

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_RID = re.compile(r"^[0-9a-f]{32}$")


class Refused(Exception):
    """A piece that is not one: the wrong shape, or a seal that does not open."""


def aad(uid: str, frm: str, to: str, rid: str, n: int) -> str:
    return AAD.format(uid=uid, frm=frm, to=to, rid=rid, n=int(n))


def seal(key: bytes, uid: str, frm: str, to: str, rid: str, n: int,
         head: dict, body: bytes = b"") -> dict:
    """One piece, ready to broadcast."""
    import vault

    plain = json.dumps({"v": PROTO, **head}, ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8") + b"\n" + body
    payload = {"device": frm, "to": to, "rid": rid, "n": int(n),
               "s": vault.seal(key, plain, aad(uid, frm, to, rid, n))}
    if size(payload) > PAYLOAD_MAX:
        raise Refused(f"a piece of {size(payload)} bytes, over the broadcast cap")
    return payload


def size(payload: dict) -> int:
    """What the broadcast weighs on the wire, as the server counts it."""
    return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def shape(payload: dict) -> tuple[str, str, str, int, str]:
    """(from, to, rid, n, sealed) of a piece, or Refused. Nothing opened."""
    if not isinstance(payload, dict):
        raise Refused("not a piece")
    frm, to, rid, n, sealed = (payload.get("device"), payload.get("to"), payload.get("rid"),
                               payload.get("n"), payload.get("s"))
    if not (isinstance(frm, str) and _UUID.match(frm)):
        raise Refused("no sender")
    if not (isinstance(to, str) and (to == "*" or _UUID.match(to))):
        raise Refused("no receiver")
    if not (isinstance(rid, str) and _RID.match(rid)):
        raise Refused("no request")
    if not (isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= MAX_FRAMES):
        raise Refused("no piece number")
    if not (isinstance(sealed, str) and sealed.startswith("v1.")):
        raise Refused("nothing sealed")
    return frm, to, rid, n, sealed


def open_(key: bytes, uid: str, payload: dict) -> tuple[dict, bytes]:
    """(head, body) of a piece sealed under ``key``, or Refused."""
    import vault

    frm, to, rid, n, sealed = shape(payload)
    try:
        plain = vault.open_(key, sealed, aad(uid, frm, to, rid, n))
    except vault.VaultError as e:
        raise Refused("the seal does not open") from e
    raw, sep, body = plain.partition(b"\n")
    try:
        head = json.loads(raw.decode("utf-8")) if sep else None
    except (ValueError, UnicodeDecodeError):
        head = None
    if not isinstance(head, dict) or head.get("v") != PROTO or not isinstance(head.get("k"), str):
        raise Refused("not a head this PC reads")
    return head, body


class _Request:
    """One recording on its way in."""

    def __init__(self, frm: str, rid: str, now: float) -> None:
        self.frm, self.rid = frm, rid
        self.started = self.touched = now
        self.pieces: dict[int, bytes] = {}
        self.bytes = 0
        self.end: dict | None = None
        self.timer: threading.Timer | None = None

    def complete(self) -> bool:
        if self.end is None:
            return False
        frames = self.end.get("frames")
        return isinstance(frames, int) and all(i in self.pieces for i in range(frames))

    def wav(self) -> bytes:
        return b"".join(self.pieces[i] for i in range(int(self.end["frames"])))


class Relay:
    """This PC's end of the relay. Every callable is handed in, so a test
    drives the whole of it with no account and no network:

    ``who()`` -> (uid, this device's id) or None while nobody is signed in;
    ``key(uid)`` -> the account key or None; ``phones()`` -> {device id:
    peer}, the phones that may ask (phone.anchors()); ``can_take()`` -> None
    when a dictation would be taken now, else the PC's own sentence why not;
    ``allowed()`` -> the switch and the account's gate; ``send(payload)`` ->
    True when the server took a piece (sb.send_link); ``transcribe(wav,
    peer)`` -> (status, body), the phone door's route.
    """

    def __init__(self, *, who, key, phones, can_take, allowed, send, transcribe,
                 clock=time.time, mono=time.monotonic) -> None:
        self.who, self.key, self.phones = who, key, phones
        self.can_take, self.allowed, self.send = can_take, allowed, send
        self.transcribe = transcribe
        self.clock, self.mono = clock, mono
        self._lock = threading.Lock()
        self._open: dict[str, _Request] = {}
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._pinged: OrderedDict[str, float] = OrderedDict()
        self._told: dict[str, float] = {}
        #: What happened, for a test and for the log's counts.
        self.counts: dict[str, int] = {}

    def _count(self, what: str) -> None:
        self.counts[what] = self.counts.get(what, 0) + 1

    def _say_once(self, what: str, line: str, *args) -> None:
        """One log line per kind a minute: a phone that keeps knocking is not
        a page of the log."""
        now = self.mono()
        if now - self._told.get(what, -1e9) >= 60:
            self._told[what] = now
            log.info(line, *args)

    # ---- in

    def heard(self, payload: dict) -> None:
        """A ``link`` piece from another device (sb.LINK_HOOKS, on the link
        lane). Never raises; never waits on the model."""
        try:
            self._heard(payload)
        except Refused as e:
            self._count("refused")
            log.debug("link: a piece was not taken (%s)", e)
        except Exception:                                    # noqa: BLE001
            self._count("tripped")
            log.warning("link: a piece tripped", exc_info=True)

    def _heard(self, payload: dict) -> None:
        if not self.allowed():
            self._count("off")
            return
        frm, to, rid, n, _sealed = shape(payload)
        who = self.who()
        if who is None:
            return
        uid, me = who
        if to not in (me, "*"):
            return                                   # another PC's: not opened
        peer = self.phones().get(frm)
        if peer is None:
            self._count("stranger")
            self._say_once("stranger", "link: a piece from a device that is not a phone of "
                           "this account, or one it forgot — not opened")
            return
        key = self.key(uid)
        if key is None:
            return
        head, body = open_(key, uid, payload)
        del key
        kind = head["k"]
        if kind == "ping":
            self._ping(uid, me, frm, rid)
        elif to != me:
            raise Refused(f"a {kind} for every PC")
        elif kind == "audio":
            self._audio(frm, rid, n, body)
        elif kind == "end":
            self._end(uid, me, frm, rid, n, head, peer)
        else:
            raise Refused(f"a head of kind {kind!r}")

    def _ping(self, uid: str, me: str, frm: str, rid: str) -> None:
        now = self.mono()
        with self._lock:
            if rid in self._pinged:
                self._count("ping-again")
                return
            self._pinged[rid] = now
            while len(self._pinged) > SEEN_MAX or (
                    self._pinged and now - next(iter(self._pinged.values())) > SEEN_S):
                self._pinged.popitem(last=False)
        self._count("ping")
        why = self.can_take()
        head = {"k": "pong", "ready": why is None}
        if why is not None:
            head["why"] = str(why)[:300]
        self._reply(uid, me, frm, rid, N_PONG, head)

    def _expire(self, now: float) -> None:
        """Requests whose pieces stopped coming, and ids past their window."""
        for rid in [r for r, q in self._open.items() if now - q.touched > ASSEMBLY_S]:
            q = self._open.pop(rid)
            if q.timer is not None:
                q.timer.cancel()
            self._count("abandoned")
            log.info("link: a recording's pieces stopped coming — let go")
        while self._seen and (len(self._seen) > SEEN_MAX or
                              now - next(iter(self._seen.values())) > SEEN_S):
            self._seen.popitem(last=False)

    def _request(self, frm: str, rid: str, now: float) -> _Request | None:
        """The request this piece belongs to, made on its first piece; None
        for one already taken (a replay, or a piece sent twice)."""
        self._expire(now)
        if rid in self._seen:
            self._count("replay")
            return None
        q = self._open.get(rid)
        if q is None:
            if len(self._open) >= MOST_OPEN:
                oldest = min(self._open.values(), key=lambda r: r.touched)
                self._open.pop(oldest.rid)
            q = self._open[rid] = _Request(frm, rid, now)
        if q.frm != frm:
            raise Refused("a piece of another device's request")
        q.touched = now
        return q

    def _audio(self, frm: str, rid: str, n: int, body: bytes) -> None:
        now = self.mono()
        with self._lock:
            q = self._request(frm, rid, now)
            if q is None:
                return
            if len(body) > FRAME_BYTES or n >= MAX_FRAMES:
                raise Refused("a piece larger than a piece")
            had = q.pieces.get(n)
            if had is None:
                if q.bytes + len(body) > MAX_BYTES:
                    raise Refused("a recording longer than a phone makes")
                q.pieces[n] = body
                q.bytes += len(body)
            elif had != body:
                raise Refused("a piece that came twice, different")
            ready = q.complete()
        if ready:
            self._finish(rid)

    def _end(self, uid: str, me: str, frm: str, rid: str, n: int, head: dict, peer) -> None:
        now = self.mono()
        frames, total, digest, at = (head.get("frames"), head.get("bytes"),
                                     head.get("sha256"), head.get("at"))
        if not (isinstance(frames, int) and 0 < frames <= MAX_FRAMES and frames == n
                and isinstance(total, int) and 0 < total <= MAX_BYTES
                and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
                and isinstance(at, (int, float))):
            raise Refused("an end that does not say what came")
        if abs(self.clock() - at / 1000.0) > SKEW_S:
            self._count("stale")
            self._say_once("stale", "link: a recording from outside the time window — dropped")
            return
        with self._lock:
            q = self._request(frm, rid, now)
            if q is None:
                return
            if q.end is not None:
                return                                   # the end, twice
            q.end = {"frames": frames, "bytes": total, "sha256": digest, "uid": uid,
                     "me": me, "peer": peer}
            ready = q.complete()
            if not ready:
                # a piece may still be on its way: it gets a moment, then the
                # phone is told nothing and goes on by itself
                q.timer = threading.Timer(STRAGGLE_S, self._late, args=(rid,))
                q.timer.daemon = True
                q.timer.start()
        if ready:
            self._finish(rid)

    def _late(self, rid: str) -> None:
        with self._lock:
            q = self._open.get(rid)
            if q is None or q.complete():
                return
            self._open.pop(rid)
            self._seen[rid] = self.mono()
            got = len(q.pieces)
            want = q.end["frames"] if q.end else "?"
        self._count("incomplete")
        log.info("link: a recording arrived without all its pieces (%s of %s)", got, want)

    def _finish(self, rid: str) -> None:
        """Every piece is in: check the whole, say so, and hand it over."""
        with self._lock:
            q = self._open.pop(rid, None)
            if q is None or q.end is None:
                if q is not None:
                    self._open[rid] = q
                return
            self._seen[rid] = self.mono()
            if q.timer is not None:
                q.timer.cancel()
        end = q.end
        wav = q.wav()
        if len(wav) != end["bytes"] or hashlib.sha256(wav).hexdigest() != end["sha256"]:
            self._count("corrupt")
            log.info("link: a recording whose pieces do not add up — dropped")
            return
        self._count("took")
        self._reply(end["uid"], end["me"], q.frm, rid, N_TOOK, {"k": "took"})
        threading.Thread(target=self._transcribe, args=(q.frm, rid, wav, end), daemon=True,
                         name="link-transcribe").start()

    def _transcribe(self, frm: str, rid: str, wav: bytes, end: dict) -> None:
        started = self.mono()
        try:
            status, body = self.transcribe(wav, end["peer"])
        except Exception as e:                               # noqa: BLE001
            log.warning("link: the transcription tripped (%s)", type(e).__name__)
            status, body = 503, {"error": "the PC could not transcribe this"}
        self._count("answered")
        log.info("link: %.1f s of audio, answered %s in %.1f s", (len(wav) - 44) / 32000.0,
                 status, self.mono() - started)
        if not self.allowed():
            return                                   # the switch went meanwhile
        who = self.who()
        if who is None or who[0] != end["uid"]:
            return
        self._reply(end["uid"], end["me"], frm, rid, N_TEXT,
                    {"k": "text", "status": int(status), "body": body})

    # ---- out

    def _reply(self, uid: str, me: str, to: str, rid: str, n: int, head: dict) -> bool:
        key = self.key(uid)
        if key is None:
            return False
        try:
            payload = seal(key, uid, me, to, rid, n, head)
        except Refused as e:
            log.info("link: an answer was not sent (%s)", e)
            return False
        finally:
            del key
        sent = bool(self.send(payload))
        self._count("sent" if sent else "not-sent")
        return sent


#: The phones that may ask are read off the kept rows at most this often:
#: a recording is a burst of pieces, and a Forget is heard within it.
PHONES_TTL_S = 5.0


def for_app(*, can_take, allowed, transcribe) -> Relay:
    """The app's relay: who is signed in from sb, the account key from
    vault (asked per piece, here and not in main.py), the phones from
    phone.anchors(), the door's own list, and the pieces out through
    sb.send_link. Nothing is imported until a piece comes: the App is
    built before the account is."""
    def who():
        import sb
        uid = str((sb.user() or {}).get("id") or "")
        if not uid:
            return None
        try:
            return uid, sb.device_id()
        except sb.AccountError:
            return None

    def key(uid: str):
        import vault
        return vault.key(uid)

    kept: dict = {"at": float("-inf"), "phones": {}}

    def phones() -> dict:
        import net
        import phone as phone_mod
        now = time.monotonic()
        if now - kept["at"] >= PHONES_TTL_S:
            kept["phones"] = {str(one["device"]): net.Peer(mark, str(one.get("name") or ""))
                              for mark, one in phone_mod.anchors().items()}
            kept["at"] = now
        return kept["phones"]

    def send(payload: dict) -> bool:
        import sb
        return sb.send_link(payload)

    return Relay(who=who, key=key, phones=phones, can_take=can_take, allowed=allowed,
                 send=send, transcribe=transcribe)
