"""This PC's half of the home road: who it is to a phone, and which phones
it opens the door to (PHONE_LINK_PLAN.md stage 1, 2026-11-06).

A phone is one more device of the person's account, and everything the two
need to recognise each other at home lives in the account, sealed under the
account key: each device's row in ``devices.link``. This module is the PC's
hand on those rows, and on the key and the certificate the door is opened
with.

``identity()`` makes this PC's key and certificate, once. A P-256 key out of
Windows' own CNG (``bcrypt.dll``, as vault.py does it, no package) and a
self-signed X.509 certificate written by hand: 1.0 ms and 300 bytes, measured
2026-11-06 (the probes in notes/phone-link-probes). The certificate's SHA-256
is what a phone pins, so its dates and its name mean nothing to anybody.

The private key lives in ``secrets\\phone_key.pem`` as PKCS#8 under PBES2
(PBKDF2-HMAC-SHA256, AES-256-CBC), with its passphrase in the secret store
under ``phone_key_pass`` — DPAPI, this Windows account only. A PEM and not a
sealed blob because Python's ``ssl`` loads a private key from a file path and
from nowhere else; net.serve_tls is handed the passphrase by NAME and asks
the store for it inside load_cert_chain's callback, so the value never
reaches server.py or main.py.

``publish(key)`` writes this PC's ``link`` row when anything in it changed.
``anchors()`` opens the phones' rows and leaves out the forgotten. The sealed
rows are kept in ``secrets\\phone_rows.json``, because a PC restarted with the
house's internet down must still open its door (§3's "Home: nobody" rests on
this), and opening them needs only the account key, which is local.

RULES, the ones vault.py keeps. A key or a passphrase is made here, written
and forgotten: never logged, never put in a status, a report or a message.
What IS logged is that an identity exists, and its fingerprint. This module
imports no transport and reads no environment; a test holds that.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import logging
import os
import re
import secrets as _secrets
import threading
import time
from pathlib import Path

import paths
import secretstore

log = logging.getLogger("app")

#: The secret store's name for the key file's passphrase (FILE_NAMES).
PASS_NAME = "phone_key_pass"

#: The two files beside the DPAPI blobs, so no new folder appears in the
#: checkout and .gitignore already has them. Asked of paths.SECRETS_DIR at
#: every use and never kept in a constant: that folder is what the suite
#: moves to a scratch home, and a path built once at import would be this
#: checkout's real one. It was, for one test run, on 2026-11-06.
KEY_FILE = "phone_key.pem"
ROWS_FILE = "phone_rows.json"

#: The first thing in a certificate's subject. The rest is random, because
#: OpenSSL takes the first anchor of a name: three phones whose certificates
#: share one subject gave [ok, SSLError, refused] without PARTIAL_CHAIN
#: (2026-11-06). The door sets that flag; a random name is the other half.
SUBJECT = "DeskIT PC"

#: The key file's own PBKDF2. The passphrase is 256 random bits, so this is
#: not what protects it: it is here because PBES2 has to name a count, and
#: every open of the door pays for it. OpenSSL's own default.
PEM_ROUNDS = 2048

#: Only "this certificate" matters to a phone, and it compares a hash.
#: UTCTime on both sides, because RFC 5280 wants that until 2050.
NOT_BEFORE = b"200101000000Z"
NOT_AFTER = b"491231235959Z"

_lock = threading.RLock()


# ------------------------------------------------------------ CNG, by hand
#
# A private handle (AGENTS.md, the capture.py trap): a declaration on the
# shared ctypes.windll object would change it for every module. None is
# declared here anyway; vault.py's pattern, handles as c_void_p.

_bcrypt = None
_PVOID = ctypes.c_void_p
_ULONG = ctypes.c_ulong


def _cng():
    global _bcrypt
    if _bcrypt is None:
        _bcrypt = ctypes.WinDLL("bcrypt")
    return _bcrypt


def _ok(status: int, what: str) -> None:
    if status != 0:
        raise OSError(f"{what} failed (NTSTATUS 0x{status & 0xFFFFFFFF:08X})")


def _alg(name: str):
    handle = _PVOID()
    _ok(_cng().BCryptOpenAlgorithmProvider(ctypes.byref(handle), name, None, 0), f"open {name}")
    return handle


def _signing_pair() -> tuple[bytes, bytes, object, object]:
    """(X, Y, d, the key handle, the provider handle): a fresh ECDSA P-256
    key, the handles still open for the signature."""
    cng = _cng()
    alg = _alg("ECDSA_P256")
    hkey = _PVOID()
    _ok(cng.BCryptGenerateKeyPair(alg, ctypes.byref(hkey), 256, 0), "the key pair")
    _ok(cng.BCryptFinalizeKeyPair(hkey, 0), "the key pair")
    n = _ULONG()
    _ok(cng.BCryptExportKey(hkey, None, "ECCPRIVATEBLOB", None, 0, ctypes.byref(n), 0), "its size")
    blob = ctypes.create_string_buffer(n.value)
    _ok(cng.BCryptExportKey(hkey, None, "ECCPRIVATEBLOB", blob, n.value, ctypes.byref(n), 0),
        "the export")
    raw = blob.raw                     # the header's 8 bytes, X, Y, d, 32 each
    return raw[8:40], raw[40:72], raw[72:104], hkey, alg


def _sign(hkey, digest: bytes) -> tuple[bytes, bytes]:
    """(r, s) over a 32-byte digest."""
    sig = ctypes.create_string_buffer(64)
    got = _ULONG()
    _ok(_cng().BCryptSignHash(hkey, None, digest, len(digest), sig, 64, ctypes.byref(got), 0),
        "the signature")
    return sig.raw[:32], sig.raw[32:64]


def _close(hkey, alg) -> None:
    _cng().BCryptDestroyKey(hkey)
    _cng().BCryptCloseAlgorithmProvider(alg, 0)


def _aes_cbc(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-256-CBC of whole blocks; the padding is the caller's."""
    cng = _cng()
    alg = _alg("AES")
    try:
        mode = "ChainingModeCBC\0".encode("utf-16-le")
        _ok(cng.BCryptSetProperty(alg, "ChainingMode", mode, len(mode), 0), "CBC mode")
        hkey = _PVOID()
        _ok(cng.BCryptGenerateSymmetricKey(alg, ctypes.byref(hkey), None, 0, key, len(key), 0),
            "the AES key")
        try:
            ivbuf = ctypes.create_string_buffer(iv, len(iv))     # CNG writes the chain back
            out = ctypes.create_string_buffer(len(data))
            n = _ULONG()
            _ok(cng.BCryptEncrypt(hkey, data, len(data), None, ivbuf, len(iv), out, len(data),
                                  ctypes.byref(n), 0), "AES-CBC")
            return out.raw[:n.value]
        finally:
            cng.BCryptDestroyKey(hkey)
    finally:
        cng.BCryptCloseAlgorithmProvider(alg, 0)


# --------------------------------------------------------------- DER, by hand

_OID_ECDSA_SHA256 = bytes.fromhex("06082a8648ce3d040302")
_OID_EC = bytes.fromhex("06072a8648ce3d0201")
_OID_P256 = bytes.fromhex("06082a8648ce3d030107")
_OID_CN = bytes.fromhex("0603550403")
_OID_PBES2 = bytes.fromhex("06092a864886f70d01050d")
_OID_PBKDF2 = bytes.fromhex("06092a864886f70d01050c")
_OID_HMAC_SHA256 = bytes.fromhex("06082a864886f70d0209")
_OID_AES256_CBC = bytes.fromhex("060960864801650304012a")
_NULL = b"\x05\x00"


def _der_len(n: int) -> bytes:
    if n < 128:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(value)) + value


def _seq(*parts: bytes) -> bytes:
    return _tlv(0x30, b"".join(parts))


def _uint(raw: bytes) -> bytes:
    raw = raw.lstrip(b"\0") or b"\0"
    return _tlv(0x02, b"\0" + raw if raw[0] & 0x80 else raw)


def _bits(raw: bytes) -> bytes:
    return _tlv(0x03, b"\0" + raw)


def _name(cn: str) -> bytes:
    return _seq(_tlv(0x31, _seq(_OID_CN, _tlv(0x0C, cn.encode("utf-8")))))


def _pem(label: str, der: bytes) -> str:
    text = base64.b64encode(der).decode("ascii")
    lines = "\n".join(text[i:i + 64] for i in range(0, len(text), 64))
    return f"-----BEGIN {label}-----\n{lines}\n-----END {label}-----\n"


def make_pair(cn: str) -> tuple[bytes, bytes]:
    """(the certificate's DER, the private key as SEC1 DER): a self-signed
    P-256 certificate with ``cn`` as its subject and its issuer."""
    x, y, d, hkey, alg = _signing_pair()
    try:
        point = b"\x04" + x + y
        tbs = _seq(_tlv(0xA0, _tlv(0x02, b"\x02")),            # v3
                   _uint(_secrets.token_bytes(16)),
                   _seq(_OID_ECDSA_SHA256),
                   _name(cn),
                   _seq(_tlv(0x17, NOT_BEFORE), _tlv(0x17, NOT_AFTER)),
                   _name(cn),
                   _seq(_seq(_OID_EC, _OID_P256), _bits(point)))
        r, s = _sign(hkey, hashlib.sha256(tbs).digest())
        cert = _seq(tbs, _seq(_OID_ECDSA_SHA256), _bits(_seq(_uint(r), _uint(s))))
        sec1 = _seq(_tlv(0x02, b"\x01"), _tlv(0x04, d), _tlv(0xA0, _OID_P256),
                    _tlv(0xA1, _bits(point)))
        return cert, sec1
    finally:
        _close(hkey, alg)


def _encrypted_pkcs8(sec1: bytes, passphrase: str) -> bytes:
    """A SEC1 key as EncryptedPrivateKeyInfo: PKCS#8 inside, PBES2 outside,
    which OpenSSL opens with the password callback."""
    pkcs8 = _seq(_tlv(0x02, b"\x00"), _seq(_OID_EC, _OID_P256), _tlv(0x04, sec1))
    salt = os.urandom(16)
    iv = os.urandom(16)
    aes_key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, PEM_ROUNDS, dklen=32)
    pad = 16 - len(pkcs8) % 16
    sealed = _aes_cbc(aes_key, iv, pkcs8 + bytes([pad]) * pad)
    kdf = _seq(_OID_PBKDF2, _seq(_tlv(0x04, salt), _tlv(0x02, PEM_ROUNDS.to_bytes(2, "big")),
                                 _tlv(0x02, b"\x20"), _seq(_OID_HMAC_SHA256, _NULL)))
    scheme = _seq(_OID_AES256_CBC, _tlv(0x04, iv))
    return _seq(_seq(_OID_PBES2, _seq(kdf, scheme)), _tlv(0x04, sealed))


# ------------------------------------------------------------- the identity

_PEM_CERT = re.compile(r"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", re.S)


def fingerprint(der: bytes) -> str:
    """SHA-256 of a certificate's DER, hex: what a pin compares, and what
    a ``link`` row and the ``forgotten`` list call a certificate."""
    return hashlib.sha256(der).hexdigest()


def key_path() -> Path:
    return paths.SECRETS_DIR / KEY_FILE


def rows_path() -> Path:
    return paths.SECRETS_DIR / ROWS_FILE


def _on_disk() -> bytes | None:
    """The certificate in the key file, or None when there is no file or
    no certificate in it."""
    try:
        text = key_path().read_text("ascii")
    except (OSError, ValueError):
        return None
    found = _PEM_CERT.search(text)
    if found is None:
        return None
    try:
        return base64.b64decode("".join(found.group(1).split()), validate=True)
    except ValueError:
        return None


def _passphrase_here() -> bool:
    """Does the store open a passphrase? A blob another Windows account
    wrote is SecretError, and that is the same as none: a new identity,
    the way load_token treats it, never a crash."""
    try:
        return bool(secretstore.get(PASS_NAME))
    except secretstore.SecretError as e:
        log.warning("phone: %s", e)
        return False


def _make_identity() -> str:
    cert, sec1 = make_pair(f"{SUBJECT} {_secrets.token_hex(4)}")
    passphrase = _secrets.token_urlsafe(32)
    pem = _pem("CERTIFICATE", cert) + _pem("ENCRYPTED PRIVATE KEY", _encrypted_pkcs8(sec1, passphrase))
    secretstore.set(PASS_NAME, passphrase)
    del passphrase, sec1
    target = key_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.write_text(pem, "ascii", newline="\n")
    os.replace(tmp, target)
    made = fingerprint(cert)
    log.info("phone: a new identity for this PC (%s)", made[:16])
    return made


def identity() -> str:
    """This PC's certificate fingerprint. Makes the key and the certificate
    the first time; afterwards it only reads. A key file whose passphrase
    is gone is treated as no key at all: a new identity, and every phone
    picks it up from this PC's next ``link`` row."""
    with _lock:
        cert = _on_disk()
        if cert is not None and _passphrase_here():
            return fingerprint(cert)
        return _make_identity()


def rotate() -> str:
    """A new key and certificate, for a key that is lost or will not open.
    Nothing expires here, so this is never a matter of time."""
    with _lock:
        return _make_identity()
