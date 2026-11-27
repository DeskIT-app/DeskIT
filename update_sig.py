"""The signature on the update feed (security-local 3; the owner's go,
2026-11-27): whoever takes over the GitHub account or the release job
must not be able to push a working update to every installed copy.

Until 2026-11-27 a copy trusted `latest.json` (the installer's URL and
SHA-256) because it sat in the release. Anyone who could write to the
release, through a stolen GitHub session or a poisoned step of
release.yml, could name an installer of their own together with its
hash, and every copy's weekly look would offer it. Now the owner signs
that file on his PC before he publishes the draft (`dev\\sign_release.py
--sign <tag>`), with a key that never touches GitHub, and a copy checks
the signature against the public half pinned in its own code
(update_key.py) before it offers or installs anything. The SHA-256 check
in updates.download stays: it binds the installer to the signed feed.

The format, small enough to check by hand with openssl:

    latest.json.sig  one line: the standard base64 of 64 bytes, the ECDSA
                     P-256 signature r || s over SHA-256 of latest.json's
                     exact bytes as the release serves them
    PUBLIC_KEY       "ecdsa-p256:" + the standard base64 of the 64-byte
                     public point X || Y (update_key.py)

Everything goes through Windows' own CNG (bcrypt.dll, by ctypes, on a
handle of this module's own, as vault.py does it), with no package.
Measured 2026-11-27 on the owner's PC: one verification, from opening the
provider to closing it, 0.17 ms (0.09 ms for BCryptVerifySignature
alone). A point that is not on the curve is refused at the import
(NTSTATUS 0xC000000D), and a wrong signature with 0xC000A000.

If the key is ever lost, installed copies stop installing updates on
their own, and Home's update row tells the person this update could not
be checked and to download it from the website. That is the known
recovery, and there is nothing else to it.

Signing lives here beside verifying because it is the same format; the
private key itself lives only in the owner's Credential Manager and only
dev\\sign_release.py reads it. No product module calls `sign` or
`new_pair`.
"""
from __future__ import annotations

import base64
import binascii
import ctypes
import hashlib
import re

#: What the public key's text starts with.
SCHEME = "ecdsa-p256:"
#: The word update_key.py carries until the owner has made the key.
PLACEHOLDER = "PLACEHOLDER"
_POINT_BYTES = 64                     # X || Y, 32 each
_SIG_BYTES = 64                       # r || s, 32 each
#: The longest .sig file read at all: 88 characters of base64 and a
#: line end. Anything bigger is not a signature of this format.
_SIG_MAX = 256
_SIG_TEXT = re.compile(r"\A[A-Za-z0-9+/]{86}==\Z")
_MAGIC_PUBLIC = 0x31534345            # 'ECS1', BCRYPT_ECDSA_PUBLIC_P256_MAGIC
_MAGIC_PRIVATE = 0x32534345           # 'ECS2', BCRYPT_ECDSA_PRIVATE_P256_MAGIC
_STATUS_INVALID_SIGNATURE = 0xC000A000


class FeedSignatureError(Exception):
    """The feed's signature is missing, malformed or wrong, or this build
    pins no key: the sentence is for the log."""


# ------------------------------------------------------------ CNG, by hand

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
        raise FeedSignatureError(f"{what} failed (NTSTATUS 0x{status & 0xFFFFFFFF:08X})")


def _alg():
    h = _PVOID()
    _ok(_cng().BCryptOpenAlgorithmProvider(ctypes.byref(h), "ECDSA_P256", None, 0),
        "open ECDSA_P256")
    return h


def _export(hkey, blob_type: str) -> bytes:
    cng = _cng()
    n = _ULONG()
    _ok(cng.BCryptExportKey(hkey, None, blob_type, None, 0, ctypes.byref(n), 0),
        f"size {blob_type}")
    buf = ctypes.create_string_buffer(n.value)
    _ok(cng.BCryptExportKey(hkey, None, blob_type, buf, n.value, ctypes.byref(n), 0),
        f"export {blob_type}")
    return buf.raw[:n.value]


def _header(magic: int) -> bytes:
    return magic.to_bytes(4, "little") + (32).to_bytes(4, "little")


# -------------------------------------------------------------- the key

def pinned() -> str:
    """The public key this build pins, read at every call (a test pins
    its own throwaway key by patching update_key.PUBLIC_KEY)."""
    import update_key
    return str(update_key.PUBLIC_KEY)


def _point(public: str) -> bytes:
    """The 64-byte point of a public key's text, or FeedSignatureError —
    the placeholder included: a build that pins no key checks nothing."""
    text = str(public or "").strip()
    if not text.startswith(SCHEME) or PLACEHOLDER in text:
        raise FeedSignatureError("this build pins no update key")
    try:
        point = base64.b64decode(text[len(SCHEME):], validate=True)
    except (binascii.Error, ValueError) as e:
        raise FeedSignatureError("the pinned update key is not base64") from e
    if len(point) != _POINT_BYTES:
        raise FeedSignatureError("the pinned update key is not a P-256 point")
    return point


def pinned_problem(public: str | None = None) -> str:
    """An empty string when the text (the pinned key by default) is a key
    a copy can check a feed with; otherwise the sentence why not. The
    release build asks this before it builds anything
    (dev\\sign_release.py --check-pinned)."""
    try:
        point = _point(pinned() if public is None else public)
        alg = _alg()
    except FeedSignatureError as e:
        return str(e)
    cng = _cng()
    try:
        hkey = _PVOID()
        blob = _header(_MAGIC_PUBLIC) + point
        status = cng.BCryptImportKeyPair(alg, None, "ECCPUBLICBLOB", ctypes.byref(hkey),
                                         blob, len(blob), 0)
        if status != 0:
            return "the pinned update key is not a point on P-256"
        cng.BCryptDestroyKey(hkey)
        return ""
    finally:
        cng.BCryptCloseAlgorithmProvider(alg, 0)


def _sig_bytes(sig) -> bytes:
    if sig is None:
        raise FeedSignatureError("the release has no latest.json.sig")
    raw = sig.encode("ascii", "replace") if isinstance(sig, str) else bytes(sig)
    if len(raw) > _SIG_MAX:
        raise FeedSignatureError("latest.json.sig is too long to be a signature")
    text = raw.decode("ascii", "replace").strip()
    if not text:
        raise FeedSignatureError("latest.json.sig is empty")
    if not _SIG_TEXT.match(text):
        raise FeedSignatureError("latest.json.sig is not one line of base64")
    out = base64.b64decode(text, validate=True)
    if len(out) != _SIG_BYTES:
        raise FeedSignatureError("latest.json.sig is not 64 bytes")
    return out


# ------------------------------------------------------------ the check

def verify(data: bytes, sig, public: str | None = None) -> None:
    """Return when `sig` (latest.json.sig's bytes or text) is a signature
    over exactly `data` by the pinned key (or `public`); raise
    FeedSignatureError otherwise — a missing file, an empty one, one that
    is not 64 bytes of base64, a wrong signature, no key pinned."""
    point = _point(pinned() if public is None else public)
    raw_sig = _sig_bytes(sig)
    digest = hashlib.sha256(bytes(data)).digest()
    cng = _cng()
    alg = _alg()
    try:
        hkey = _PVOID()
        blob = _header(_MAGIC_PUBLIC) + point
        _ok(cng.BCryptImportKeyPair(alg, None, "ECCPUBLICBLOB", ctypes.byref(hkey),
                                    blob, len(blob), 0), "the pinned update key")
        try:
            status = cng.BCryptVerifySignature(hkey, None, digest, len(digest),
                                               raw_sig, len(raw_sig), 0)
        finally:
            cng.BCryptDestroyKey(hkey)
    finally:
        cng.BCryptCloseAlgorithmProvider(alg, 0)
    if status & 0xFFFFFFFF == _STATUS_INVALID_SIGNATURE:
        raise FeedSignatureError("latest.json.sig does not match latest.json "
                                 "and the pinned key")
    _ok(status, "the signature check")


# ------------------------------------- the owner's half (dev\sign_release.py)

def new_pair() -> tuple[bytes, str]:
    """A fresh pair: (CNG's private blob, the public key's text). Only the
    owner's tool and the tests call this."""
    cng = _cng()
    alg = _alg()
    try:
        hkey = _PVOID()
        _ok(cng.BCryptGenerateKeyPair(alg, ctypes.byref(hkey), 256, 0), "the pair")
        try:
            _ok(cng.BCryptFinalizeKeyPair(hkey, 0), "the pair")
            private = _export(hkey, "ECCPRIVATEBLOB")
        finally:
            cng.BCryptDestroyKey(hkey)
    finally:
        cng.BCryptCloseAlgorithmProvider(alg, 0)
    return private, public_of(private)


def public_of(private: bytes) -> str:
    """The public key's text inside a CNG private blob (header, X, Y, d)."""
    if len(private) != 8 + 3 * 32 or private[:4] != _MAGIC_PRIVATE.to_bytes(4, "little"):
        raise FeedSignatureError("not a P-256 signing key")
    return SCHEME + base64.b64encode(private[8:8 + _POINT_BYTES]).decode("ascii")


def sign(private: bytes, data: bytes) -> str:
    """latest.json.sig's text for `data`: one line of base64 and "\\n"."""
    public_of(private)                                  # the shape, or refused
    digest = hashlib.sha256(bytes(data)).digest()
    cng = _cng()
    alg = _alg()
    try:
        hkey = _PVOID()
        _ok(cng.BCryptImportKeyPair(alg, None, "ECCPRIVATEBLOB", ctypes.byref(hkey),
                                    bytes(private), len(private), 0), "the signing key")
        try:
            n = _ULONG()
            _ok(cng.BCryptSignHash(hkey, None, digest, len(digest), None, 0,
                                   ctypes.byref(n), 0), "the signature's size")
            out = ctypes.create_string_buffer(n.value)
            _ok(cng.BCryptSignHash(hkey, None, digest, len(digest), out, n.value,
                                   ctypes.byref(n), 0), "the signature")
            raw = out.raw[:n.value]
        finally:
            cng.BCryptDestroyKey(hkey)
    finally:
        cng.BCryptCloseAlgorithmProvider(alg, 0)
    if len(raw) != _SIG_BYTES:
        raise FeedSignatureError("CNG gave a signature that is not 64 bytes")
    return base64.b64encode(raw).decode("ascii") + "\n"
