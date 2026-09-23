"""The lock: one key per account, held only by the account's own devices.

The owner, 2026-09-21, after the two syncs became one account: the
cloud keys and the text of what he said must be locked before they
leave the PC, so that the same account opens them on every PC of his
and the server — DeskIT's own project, and whoever runs it — cannot.
This module is the lock; sb.py carries what it produces and never sees
the inside of it.

What the big services do, and this copies (a short read of Apple's
keychain syncing, Bitwarden's log-in-with-device and Signal's secure
backups, 2026-09-21):

- ONE random key per account (``KEY_BYTES`` of them, from the system's
  own generator), kept on each device in a DPAPI file the person's
  Windows account alone can open (secretstore, ``KEY_NAME``), bound to
  the account's uid — a key of one account never unlocks another's rows.
  The server holds only its fingerprint (``fingerprint``: eight bytes of
  a hash, ``profiles.lock_id``), enough to tell whether a device has the
  right key, useless for opening anything.
- Every locked value is sealed with AES-256-GCM through Windows' own
  CNG (``bcrypt.dll``, ctypes — no package to install), a fresh nonce
  per value and the row's identity as the associated data, so a sealed
  history line cannot be moved under another row. ``seal``/``open_``.
- A NEW DEVICE never types a secret. It makes a key pair of its own
  (ECDH P-256, CNG again), publishes the public half, and shows a short
  code COMPUTED FROM that public half (``pairing_code``); a device that
  already holds the account key computes the code again from the public
  key it is about to wrap to — never from anything the server says the
  code is — and the person, having compared the two, presses Approve:
  the approving device wraps the account key to the applicant's public
  key (``hand_over``), the applicant unwraps it (``take``), and the
  server only ever carried a public key and a wrapped one. Apple and
  Bitwarden both do this; WhatsApp's link-with-phone-number is the same
  shape. Bitwarden's log-in-with-device shows a fingerprint phrase made
  from the request's own public key on both screens
  (bitwarden.com/help/log-in-with-device, and the phrase's inputs in
  github.com/bitwarden/android/issues/5856); until 2026-09-23 the code
  here was random, so a twin request with the same code and another key
  passed the comparison (the audit's A35/A74).
- THE PC IS THE TRUST ANCHOR, not the server (2026-09-23, the audit's
  A15: one write of ``profiles.lock_id`` used to make every PC delete
  its key and take the next one handed to it). A PC that holds a key
  never drops it or replaces it because the server names another lock:
  the key's fingerprint is pinned beside it in the DPAPI file, a lock
  that moved elsewhere is a question for the person on Home, and a key
  is only ever MOVED ASIDE (``set_aside``), never deleted, except by
  Delete my account. Apple's keychain circle works the same way: a new
  device is added by a device already in it, and Apple's servers cannot
  add one or swap the keys (support.apple.com/guide/security/
  sec0a319b35f); Signal shows "safety number changed" in the chat and
  trusts nothing silently (signal.org/blog/safety-number-updates).
- When no other device is at hand: a RECOVERY KEY the app generates
  (``new_recovery``, 24 characters in six groups — Apple's is 28,
  Signal's 64), shown once, kept by the person; the account key wrapped
  under it (``wrap_recovery``, scrypt at 2^17 — half a second on this
  PC, memory-hard against a rented GPU) sits on the server, and a new
  PC that types the recovery key opens it. Optional, replaceable.

The narrow door for the cloud keys (``export_keys``/``import_keys``):
this is the one module besides secretstore that touches a cloud key's
VALUE, and it hands sb.py only sealed strings. sb.py may not import the
modules that read a key (``test_sb_imports_are_narrow``) and still may
not; it iterates ``secretstore.CRED_NAMES`` and moves opaque text.

Formats, each with a version prefix so a later change is not a guess:
``v1.<base64>`` a sealed value (nonce ‖ ciphertext ‖ tag),
``p1.<base64>`` a public key (the P-256 point, X ‖ Y),
``w1.<base64>`` a key wrapped to a public key (the ephemeral point ‖ a
sealed value), ``r1.<base64>`` a key wrapped under the recovery key
(salt ‖ a sealed value). Standard base64 (``+/=``), never url-safe, so
no sealed value can spell a Groq (``gsk_``) or Supabase (``sb_``) key
by accident; the migration's ``is_sealed`` check is this shape.

Rules: a key or a value is returned to the caller and forgotten — never
logged, never written to any other file; what IS logged is that a lock
exists, whose fingerprint, and what state a device is in.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import logging
import os
import re
import secrets as _secrets
import threading

import secretstore

log = logging.getLogger("app")

KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16
#: The DPAPI file (secretstore.FILE_NAMES) the account key lives in:
#: a JSON blob {"uid", "key" (base64), "created", "lock" (the key's
#: fingerprint — the lock this PC trusts, pinned beside it), and
#: "refused" (a lock on the server the person said was not his)}.
KEY_NAME = "account_key"
#: Keys this PC moved aside instead of deleting — a change of lock the
#: person confirmed, or a key another one would have overwritten:
#: {"keys": [{"uid", "key" (base64, or "" for a confirmation alone),
#: "lock", "created", "aside_at", "for_lock", "why"}]}, oldest first.
ASIDE_NAME = "account_key_aside"

#: Crockford's base32 alphabet without I, L, O and U — nothing that reads
#: like something else on a screen or on paper.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ALIASES = str.maketrans({"O": "0", "I": "1", "L": "1"})
#: The pairing code both screens show: ten characters in two groups of
#: five, 50 bits of a slow hash of the applicant's public key. Why 50
#: and why slow: the one who wants to pass a twin request off as the
#: real one must find ANOTHER key (or request id — it picks its own)
#: whose code is the same, inside the few minutes the person spends
#: comparing. Each guess costs CODE_ROUNDS of PBKDF2-HMAC-SHA256 — the
#: way Signal iterates its safety number 5200 times for the same reason
#: — so 2^50 guesses at a big GPU's ~9e9 HMAC rounds a second (hashcat's
#: PBKDF2-SHA256 figure) are some 500 GPU-years, fifty million GPUs to
#: do it inside five minutes; eight characters of one plain SHA-256 (the
#: audit's first sketch) were under a minute of one GPU.
CODE_CHARS = 10
CODE_GROUP = 5
#: 2^17 rounds: 50 ms on the owner's PC (measured 2026-09-23), paid
#: once per request on each side (``_codes`` remembers it).
CODE_ROUNDS = 2 ** 17
#: The ``pairings.code`` column: 0004's check is eight characters of the
#: alphabet. It carries the first eight of the code, a lookup hint only
#: — the approver never shows it and never trusts it.
HINT_CHARS = 8
RECOVERY_CHARS = 24
GROUP = 4

#: scrypt for the recovery key: 2^17 / 8 / 1 needs 128 MiB and takes
#: about half a second on the owner's PC (measured 2026-09-21).
SCRYPT_N = 2 ** 17
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 256 * 1024 * 1024
SALT_BYTES = 16

#: Where a sealed value's associated data comes from — one line per
#: table, so a value sealed for one row cannot be opened as another.
AAD_HISTORY = "history/{uid}/{device_id}/{ts}/{kind}"
AAD_VAULT = "vault/{uid}/{name}"
AAD_PAIRING = "pairing/{uid}/{pairing_id}"
AAD_RECOVERY = "recovery/{uid}"


class VaultError(Exception):
    """A sealed value that will not open (the wrong key, a tampered
    row), a malformed blob, a key that is not there — the sentence is
    for the log, never the value."""


# ------------------------------------------------------------ CNG, by hand

_bcrypt = None
_PVOID = ctypes.c_void_p
_ULONG = ctypes.c_ulong
_STATUS_AUTH_TAG_MISMATCH = 0xC000A002


class _AUTH_INFO(ctypes.Structure):
    _fields_ = [("cbSize", _ULONG), ("dwInfoVersion", _ULONG),
                ("pbNonce", _PVOID), ("cbNonce", _ULONG),
                ("pbAuthData", _PVOID), ("cbAuthData", _ULONG),
                ("pbTag", _PVOID), ("cbTag", _ULONG),
                ("pbMacContext", _PVOID), ("cbMacContext", _ULONG),
                ("cbAAD", _ULONG), ("cbData", ctypes.c_ulonglong), ("dwFlags", _ULONG)]


def _cng():
    global _bcrypt
    if _bcrypt is None:
        _bcrypt = ctypes.WinDLL("bcrypt")
    return _bcrypt


def _ok(status: int, what: str) -> None:
    if status != 0:
        raise VaultError(f"{what} failed (NTSTATUS 0x{status & 0xFFFFFFFF:08X})")


def _alg(name: str):
    h = _PVOID()
    _ok(_cng().BCryptOpenAlgorithmProvider(ctypes.byref(h), name, None, 0), f"open {name}")
    return h


def _gcm(key: bytes, nonce: bytes, data: bytes, aad: bytes, *, encrypt: bool,
         tag: bytes = b"") -> tuple[bytes, bytes]:
    """AES-256-GCM one way or the other: (output, tag). A tag that does
    not match is a VaultError, not a wrong answer."""
    if len(key) != KEY_BYTES:
        raise VaultError("the key is not 32 bytes")
    cng = _cng()
    alg = _alg("AES")
    try:
        mode = "ChainingModeGCM\0".encode("utf-16-le")
        _ok(cng.BCryptSetProperty(alg, "ChainingMode", mode, len(mode), 0), "GCM mode")
        hkey = _PVOID()
        _ok(cng.BCryptGenerateSymmetricKey(alg, ctypes.byref(hkey), None, 0, key, len(key), 0),
            "the AES key")
        try:
            tagbuf = ctypes.create_string_buffer(tag, TAG_BYTES) if tag \
                else ctypes.create_string_buffer(TAG_BYTES)
            noncebuf = ctypes.create_string_buffer(nonce, len(nonce))
            aadbuf = ctypes.create_string_buffer(aad, len(aad)) if aad else None
            info = _AUTH_INFO()
            info.cbSize = ctypes.sizeof(_AUTH_INFO)
            info.dwInfoVersion = 1
            info.pbNonce = ctypes.cast(noncebuf, _PVOID)
            info.cbNonce = len(nonce)
            info.pbAuthData = ctypes.cast(aadbuf, _PVOID) if aadbuf is not None else None
            info.cbAuthData = len(aad)
            info.pbTag = ctypes.cast(tagbuf, _PVOID)
            info.cbTag = TAG_BYTES
            out = ctypes.create_string_buffer(max(len(data), 1))
            n = _ULONG()
            fn = cng.BCryptEncrypt if encrypt else cng.BCryptDecrypt
            status = fn(hkey, data, len(data), ctypes.byref(info), None, 0,
                        out, len(data), ctypes.byref(n), 0)
            if not encrypt and status & 0xFFFFFFFF == _STATUS_AUTH_TAG_MISMATCH:
                raise VaultError("the sealed value does not open with this key")
            _ok(status, "AES-GCM")
            return out.raw[:n.value], bytes(tagbuf.raw)
        finally:
            cng.BCryptDestroyKey(hkey)
    finally:
        cng.BCryptCloseAlgorithmProvider(alg, 0)


_ECC_MAGIC_PUBLIC = 0x314B4345          # 'ECK1' — BCRYPT_ECDH_PUBLIC_P256_MAGIC
_ECC_POINT_BYTES = 64                   # X ‖ Y, 32 each


def _export(hkey, blob_type: str) -> bytes:
    cng = _cng()
    n = _ULONG()
    _ok(cng.BCryptExportKey(hkey, None, blob_type, None, 0, ctypes.byref(n), 0),
        f"size {blob_type}")
    buf = ctypes.create_string_buffer(n.value)
    _ok(cng.BCryptExportKey(hkey, None, blob_type, buf, n.value, ctypes.byref(n), 0),
        f"export {blob_type}")
    return buf.raw[:n.value]


def _ecdh_keypair() -> tuple[bytes, bytes]:
    """(the private blob as CNG exports it, the public point X ‖ Y)."""
    cng = _cng()
    alg = _alg("ECDH_P256")
    try:
        hkey = _PVOID()
        _ok(cng.BCryptGenerateKeyPair(alg, ctypes.byref(hkey), 256, 0), "the pair")
        _ok(cng.BCryptFinalizeKeyPair(hkey, 0), "the pair")
        try:
            pub = _export(hkey, "ECCPUBLICBLOB")
            priv = _export(hkey, "ECCPRIVATEBLOB")
        finally:
            cng.BCryptDestroyKey(hkey)
        return priv, pub[8:8 + _ECC_POINT_BYTES]
    finally:
        cng.BCryptCloseAlgorithmProvider(alg, 0)


def _ecdh_shared(priv_blob: bytes, peer_point: bytes) -> bytes:
    """The raw shared secret (the x-coordinate as CNG hands it, 32
    bytes) between a private blob and the other side's point."""
    if len(peer_point) != _ECC_POINT_BYTES:
        raise VaultError("the other side's public key has the wrong length")
    cng = _cng()
    alg = _alg("ECDH_P256")
    handles = []
    try:
        hpriv, hpub = _PVOID(), _PVOID()
        _ok(cng.BCryptImportKeyPair(alg, None, "ECCPRIVATEBLOB", ctypes.byref(hpriv),
                                    priv_blob, len(priv_blob), 0), "this side's pair")
        handles.append(hpriv)
        header = _ECC_MAGIC_PUBLIC.to_bytes(4, "little") + (32).to_bytes(4, "little")
        blob = header + peer_point
        _ok(cng.BCryptImportKeyPair(alg, None, "ECCPUBLICBLOB", ctypes.byref(hpub),
                                    blob, len(blob), 0), "the other side's public key")
        handles.append(hpub)
        hsec = _PVOID()
        _ok(cng.BCryptSecretAgreement(hpriv, hpub, ctypes.byref(hsec), 0), "the agreement")
        try:
            n = _ULONG()
            _ok(cng.BCryptDeriveKey(hsec, "TRUNCATE", None, None, 0, ctypes.byref(n), 0),
                "the shared secret")
            buf = ctypes.create_string_buffer(n.value)
            _ok(cng.BCryptDeriveKey(hsec, "TRUNCATE", None, buf, n.value, ctypes.byref(n), 0),
                "the shared secret")
            return buf.raw[:n.value]
        finally:
            cng.BCryptDestroySecret(hsec)
    finally:
        for h in handles:
            cng.BCryptDestroyKey(h)
        cng.BCryptCloseAlgorithmProvider(alg, 0)


def _hkdf(secret: bytes, info: bytes, length: int = KEY_BYTES) -> bytes:
    """HKDF-SHA256 (RFC 5869), empty salt, one or two blocks."""
    prk = hmac.new(b"\0" * 32, secret, hashlib.sha256).digest()
    out, block, i = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([i]), hashlib.sha256).digest()
        out += block
        i += 1
    return out[:length]


# ---------------------------------------------------------------- formats

def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(prefix: str, text: str) -> bytes:
    text = str(text or "")
    if not text.startswith(prefix + "."):
        raise VaultError(f"not a {prefix} value")
    try:
        return base64.b64decode(text[len(prefix) + 1:], validate=True)
    except (ValueError, TypeError) as e:
        raise VaultError(f"a malformed {prefix} value") from e


#: The longest sealed value the server takes (migration 0005: the cap
#: sits in char_length, because Postgres caps a regex bound at 255).
SEALED_MAX = 7603


def is_sealed(text: str) -> bool:
    """The shape the migration's ``is_sealed()`` admits, so a value the
    server would refuse is refused here first."""
    text = str(text or "")
    return len(text) <= SEALED_MAX and bool(re.fullmatch(r"[a-z]\d\.[A-Za-z0-9+/]{16,}={0,2}", text))


def seal(key: bytes, data: bytes, aad: str) -> str:
    """``v1.`` + base64(nonce ‖ ciphertext ‖ tag)."""
    nonce = os.urandom(NONCE_BYTES)
    ct, tag = _gcm(key, nonce, data, aad.encode("utf-8"), encrypt=True)
    return "v1." + _b64(nonce + ct + tag)


def open_(key: bytes, sealed: str, aad: str) -> bytes:
    raw = _unb64("v1", sealed)
    if len(raw) < NONCE_BYTES + TAG_BYTES:
        raise VaultError("a sealed value too short to be one")
    nonce, ct, tag = raw[:NONCE_BYTES], raw[NONCE_BYTES:-TAG_BYTES], raw[-TAG_BYTES:]
    data, _tag = _gcm(key, nonce, ct, aad.encode("utf-8"), encrypt=False, tag=tag)
    return data


def seal_json(key: bytes, obj, aad: str) -> str:
    return seal(key, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), aad)


def open_json(key: bytes, sealed: str, aad: str):
    try:
        return json.loads(open_(key, sealed, aad).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise VaultError("a sealed value that is not JSON") from e


# ------------------------------------------------------- the account key

_lock = threading.RLock()


def fingerprint(key: bytes) -> str:
    """Sixteen hex characters that name the key without giving anything
    of it away — what ``profiles.lock_id`` holds."""
    return hashlib.sha256(b"deskit lock id\0" + key).hexdigest()[:16]


def _read() -> dict | None:
    try:
        raw = secretstore.get(KEY_NAME)
    except Exception as e:                                   # noqa: BLE001
        log.warning("lock: the account key file could not be read (%s)", e)
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        key = base64.b64decode(str(data.get("key") or ""), validate=True)
    except (ValueError, TypeError, AttributeError):
        log.warning("lock: the account key file is not what it should be — ignored")
        return None
    if len(key) != KEY_BYTES or not data.get("uid"):
        return None
    return {"uid": str(data["uid"]), "key": key, "created": str(data.get("created") or ""),
            "lock": str(data.get("lock") or "") or fingerprint(key),
            "refused": str(data.get("refused") or "")}


def _write(held: dict) -> None:
    secretstore.set(KEY_NAME, json.dumps({
        "uid": held["uid"], "key": _b64(held["key"]), "created": held["created"],
        "lock": fingerprint(held["key"]), "refused": held.get("refused") or ""}))


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def key(uid: str) -> bytes | None:
    """This device's copy of the account key for ``uid``, or None — a key
    of another account is None too, and stays where it is."""
    with _lock:
        held = _read()
        return held["key"] if held and held["uid"] == str(uid) else None


def have(uid: str) -> bool:
    return key(uid) is not None


def create(uid: str) -> bytes:
    """A fresh key for a fresh lock — the FIRST device of an account
    makes it; every later device receives it."""
    new = os.urandom(KEY_BYTES)
    keep(uid, new)
    log.info("lock: a new key for this account (%s)", fingerprint(new))
    return new


def keep(uid: str, new: bytes) -> None:
    """Store a received key for ``uid``, its fingerprint pinned beside it.
    A DIFFERENT key already here — another account's, or an older lock of
    this one — is moved aside first, never written over."""
    if len(new) != KEY_BYTES:
        raise VaultError("the key is not 32 bytes")
    with _lock:
        held = _read()
        if held is not None and held["key"] != new:
            _put_aside(held, for_lock="", why="replaced")
        _write({"uid": str(uid), "key": new, "created": _now(), "refused": ""})


def _aside() -> list[dict]:
    try:
        raw = secretstore.get(ASIDE_NAME)
        rows = json.loads(raw)["keys"] if raw else []
    except Exception:                                        # noqa: BLE001
        log.warning("lock: the file of keys set aside could not be read — kept as it is")
        raise VaultError("the keys set aside could not be read") from None
    return [r for r in rows if isinstance(r, dict)]


def _put_aside(held: dict | None, *, for_lock: str, why: str, uid: str = "") -> None:
    rows = _aside()
    rows.append({"uid": str(held["uid"] if held else uid),
                 "key": _b64(held["key"]) if held else "",
                 "lock": fingerprint(held["key"]) if held else "",
                 "created": held["created"] if held else "",
                 "aside_at": _now(), "for_lock": str(for_lock or ""), "why": why})
    secretstore.set(ASIDE_NAME, json.dumps({"keys": rows}))


def set_aside(uid: str, for_lock: str) -> bool:
    """The person confirmed that the account's lock changed to
    ``for_lock`` (Home's [It was me]): this PC's key for ``uid`` moves
    into the file of keys set aside — kept, never deleted — and the
    confirmation is written with it, so the key handed over for the new
    lock is taken and no other. With no key here, the confirmation
    alone. True when a key was moved."""
    with _lock:
        held = _read()
        mine = held if held and held["uid"] == str(uid) else None
        _put_aside(mine, for_lock=for_lock, why="the lock changed", uid=str(uid))
        if mine is not None:
            secretstore.delete(KEY_NAME)
        return mine is not None


def confirmed(uid: str) -> str | None:
    """The lock the person last confirmed a change to on this PC, or None
    when this PC never set a key of ``uid`` aside for one."""
    with _lock:
        try:
            rows = _aside()
        except VaultError:
            return ""                    # unreadable: nothing is confirmed
    for r in reversed(rows):
        if r.get("uid") == str(uid) and r.get("for_lock"):
            return str(r["for_lock"])
    return None


def aside(uid: str) -> list[str]:
    """The fingerprints of the keys of ``uid`` set aside here, oldest
    first — what the tests and a support question can see; never a key."""
    with _lock:
        return [str(r.get("lock") or "") for r in _aside()
                if r.get("uid") == str(uid) and r.get("key")]


def refuse(uid: str, lock_id: str) -> bool:
    """Home's [It wasn't me]: the lock ``lock_id`` on the server is not
    the person's — written beside the key so a restart does not ask
    again; "" clears it. False when this PC holds no key of ``uid``."""
    with _lock:
        held = _read()
        if held is None or held["uid"] != str(uid):
            return False
        held["refused"] = str(lock_id or "")
        _write(held)
        return True


def refused(uid: str) -> str:
    """The lock the person said was not his, or ""."""
    with _lock:
        held = _read()
        return held["refused"] if held and held["uid"] == str(uid) else ""


def forget(uid: str | None = None) -> bool:
    """Delete my account: the key, and — for ``uid`` — every key of that
    account set aside. Nothing else deletes a key."""
    with _lock:
        gone = secretstore.delete(KEY_NAME)
        if uid is not None:
            try:
                rows = _aside()
            except VaultError:
                rows = []
            left = [r for r in rows if r.get("uid") != str(uid)]
            if left:
                secretstore.set(ASIDE_NAME, json.dumps({"keys": left}))
            else:
                secretstore.delete(ASIDE_NAME)
        return gone


# --------------------------------------------------------- codes and keys

def _chunks(text: str, group: int = GROUP) -> str:
    return "-".join(text[i:i + group] for i in range(0, len(text), group))


def _random(n: int) -> str:
    return "".join(_secrets.choice(ALPHABET) for _ in range(n))


#: (uid, pairing id, public key) -> its code: 50 ms each, and the desk
#: asks for the same request's code on every poll. Public values only.
_codes: dict[tuple[str, str, str], str] = {}


def pairing_code(uid: str, pairing_id: str, public: str) -> str:
    """The code a request to join is compared by, ``XXXXX-XXXXX``,
    computed from the request itself: the account, the request's id and
    the applicant's public key (``p1.…``) — the applicant from the key
    it made, the approver from the key it is about to wrap to. Another
    key, or the same key under another request, is another code.
    VaultError when ``public`` is not a public key."""
    ident = (str(uid), str(pairing_id), str(public))
    with _lock:
        known = _codes.get(ident)
    if known:
        return known
    point = _unb64("p1", public)
    if len(point) != _ECC_POINT_BYTES:
        raise VaultError("the applicant's public key has the wrong length")
    material = b"\0".join((b"deskit pairing code v1", ident[0].encode("utf-8"),
                           ident[1].encode("utf-8"), point))
    digest = hashlib.pbkdf2_hmac("sha256", material, b"deskit pairing code v1",
                                 CODE_ROUNDS, dklen=32)
    bits = int.from_bytes(digest[:8], "big") >> (64 - 5 * CODE_CHARS)
    flat = "".join(ALPHABET[(bits >> (5 * (CODE_CHARS - 1 - i))) & 31]
                   for i in range(CODE_CHARS))
    code = _chunks(flat, CODE_GROUP)
    with _lock:
        if len(_codes) > 64:
            _codes.clear()
        _codes[ident] = code
    return code


def code_hint(code: str) -> str:
    """What the ``pairings.code`` column holds: the first HINT_CHARS of
    the code, flat. A hint for a person reading the table, never
    compared by the app."""
    return re.sub(r"[^0-9A-Z]", "", str(code or "").upper())[:HINT_CHARS]


def new_recovery() -> str:
    """A recovery key: ``XXXX-XXXX-XXXX-XXXX-XXXX-XXXX`` (120 bits)."""
    return _chunks(_random(RECOVERY_CHARS))


def normalize(text: str, length: int) -> str | None:
    """What a person typed or pasted, as the alphabet's own string of
    ``length`` characters — case, dashes, spaces and the four look-alike
    letters forgiven — or None when it cannot be one."""
    flat = re.sub(r"[^0-9A-Za-z]", "", str(text or "")).upper().translate(_ALIASES)
    if len(flat) != length or any(ch not in ALPHABET for ch in flat):
        return None
    return flat


def pretty(flat: str, group: int = GROUP) -> str:
    return _chunks(flat, group)


# ------------------------------------------------------------- the hand-off

#: pairing id -> this applicant's private blob, while a request is open.
_applicants: dict[str, bytes] = {}


def applicant(pairing_id: str) -> str:
    """A key pair for one request; the public half as ``p1.…`` for the
    server, the private half kept here until ``take`` or ``drop``."""
    priv, point = _ecdh_keypair()
    with _lock:
        _applicants[str(pairing_id)] = priv
    return "p1." + _b64(point)


def drop(pairing_id: str) -> None:
    with _lock:
        _applicants.pop(str(pairing_id), None)


def hand_over(account_key: bytes, public: str, aad: str) -> str:
    """The approving side: the account key wrapped to the applicant's
    public key — an ephemeral pair, ECDH, HKDF, one sealed value.
    ``w1.`` + base64(ephemeral point ‖ sealed)."""
    point = _unb64("p1", public)
    if len(point) != _ECC_POINT_BYTES:
        raise VaultError("the applicant's public key has the wrong length")
    eph_priv, eph_point = _ecdh_keypair()
    shared = _ecdh_shared(eph_priv, point)
    wrap_key = _hkdf(shared, b"deskit pairing v1" + eph_point + point)
    sealed = seal(wrap_key, account_key, aad)
    return "w1." + _b64(eph_point + _unb64("v1", sealed))


def take(pairing_id: str, handed: str, aad: str) -> bytes:
    """The applicant's side: the account key out of what was handed
    over, with the private half kept for this request."""
    with _lock:
        priv = _applicants.get(str(pairing_id))
    if priv is None:
        raise VaultError("no open request of this PC with that id")
    raw = _unb64("w1", handed)
    if len(raw) < _ECC_POINT_BYTES + NONCE_BYTES + TAG_BYTES:
        raise VaultError("a handed key too short to be one")
    eph_point, sealed = raw[:_ECC_POINT_BYTES], raw[_ECC_POINT_BYTES:]
    _my_priv, my_point = priv, _point_of(priv)
    shared = _ecdh_shared(priv, eph_point)
    wrap_key = _hkdf(shared, b"deskit pairing v1" + eph_point + my_point)
    account_key = open_(wrap_key, "v1." + _b64(sealed), aad)
    if len(account_key) != KEY_BYTES:
        raise VaultError("what was handed over is not a key")
    drop(pairing_id)
    return account_key


def _point_of(priv_blob: bytes) -> bytes:
    """The public point inside a CNG private blob (header, X, Y, d)."""
    return priv_blob[8:8 + _ECC_POINT_BYTES]


# ------------------------------------------------------------- the recovery

def _recovery_key(flat: str, salt: bytes) -> bytes:
    return hashlib.scrypt(flat.encode("ascii"), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
                          p=SCRYPT_P, dklen=KEY_BYTES, maxmem=SCRYPT_MAXMEM)


def wrap_recovery(account_key: bytes, recovery: str, aad: str) -> str:
    """The account key under the recovery key: ``r1.`` + base64(salt ‖
    sealed). Half a second, on purpose."""
    flat = normalize(recovery, RECOVERY_CHARS)
    if flat is None:
        raise VaultError("that is not a recovery key")
    salt = os.urandom(SALT_BYTES)
    sealed = seal(_recovery_key(flat, salt), account_key, aad)
    return "r1." + _b64(salt + _unb64("v1", sealed))


def unwrap_recovery(wrapped: str, recovery: str, aad: str) -> bytes:
    flat = normalize(recovery, RECOVERY_CHARS)
    if flat is None:
        raise VaultError("that is not a recovery key")
    raw = _unb64("r1", wrapped)
    if len(raw) < SALT_BYTES + NONCE_BYTES + TAG_BYTES:
        raise VaultError("a recovery wrap too short to be one")
    salt, sealed = raw[:SALT_BYTES], raw[SALT_BYTES:]
    try:
        account_key = open_(_recovery_key(flat, salt), "v1." + _b64(sealed), aad)
    except VaultError as e:
        raise VaultError("the recovery key does not open this account") from e
    if len(account_key) != KEY_BYTES:
        raise VaultError("what the recovery key opened is not a key")
    return account_key


# ------------------------------------------- the cloud keys' narrow door

def export_keys(account_key: bytes, uid: str, only=None) -> dict[str, str]:
    """Every cloud key this PC keeps in Windows Credential Manager (only
    there — a developer's .env or shell variable is that machine's
    affair), each sealed under the account key: {name: v1.…}; ``only``
    narrows it to some names. A name with no key is a sealed empty
    value, so a key removed here is removed on the other PCs too (sb.py
    decides when an empty one travels)."""
    out: dict[str, str] = {}
    for name in secretstore.CRED_NAMES:
        if only is not None and name not in only:
            continue
        try:
            value = secretstore.get(name) or ""
        except Exception as e:                               # noqa: BLE001
            log.info("lock: %s could not be read for the sync (%s)", name, e)
            continue
        out[name] = seal_json(account_key, {"v": value}, AAD_VAULT.format(uid=uid, name=name))
        del value
    return out


def digest_keys(account_key: bytes) -> tuple[dict[str, str], set[str]]:
    """A keyed hash per cloud key (never the key), so a sync pass can
    tell whether one changed since the last push without holding the
    values — and the set of names that hold one."""
    out: dict[str, str] = {}
    present: set[str] = set()
    for name in secretstore.CRED_NAMES:
        try:
            value = secretstore.get(name) or ""
        except Exception:                                    # noqa: BLE001
            value = ""
        if value:
            present.add(name)
        out[name] = hmac.new(account_key, f"{name}\0{value}".encode("utf-8"),
                             hashlib.sha256).hexdigest()[:24]
        del value
    return out, present


def import_keys(account_key: bytes, uid: str, rows: dict[str, str]) -> list[str]:
    """Sealed values from the account into Windows Credential Manager;
    the names that changed. A value that will not open is logged by
    name and skipped."""
    changed: list[str] = []
    for name, sealed in rows.items():
        if name not in secretstore.CRED_NAMES:
            continue
        try:
            value = str((open_json(account_key, sealed, AAD_VAULT.format(uid=uid, name=name))
                         or {}).get("v") or "")
        except VaultError as e:
            log.info("lock: the synced %s did not open (%s)", name, e)
            continue
        try:
            had = secretstore.get(name) or ""
            if had != value:
                secretstore.set(name, value)
                changed.append(name)
        except Exception as e:                               # noqa: BLE001
            log.info("lock: the synced %s could not be stored (%s)", name, e)
        finally:
            del value
    return changed


__all__ = [
    "VaultError", "KEY_NAME", "KEY_BYTES", "seal", "open_", "seal_json", "open_json",
    "is_sealed", "fingerprint", "key", "have", "create", "keep", "forget",
    "ASIDE_NAME", "set_aside", "confirmed", "aside", "refuse", "refused",
    "pairing_code", "code_hint", "new_recovery", "normalize", "pretty", "CODE_CHARS",
    "CODE_GROUP", "HINT_CHARS", "RECOVERY_CHARS",
    "applicant", "drop", "hand_over", "take", "wrap_recovery", "unwrap_recovery",
    "export_keys", "digest_keys", "import_keys",
    "AAD_HISTORY", "AAD_VAULT", "AAD_PAIRING", "AAD_RECOVERY",
]
