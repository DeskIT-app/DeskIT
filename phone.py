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

``publish(key, ...)`` writes this PC's ``link`` row when anything in it
changed. ``anchors()`` opens the phones' rows and leaves out the forgotten.
``refresh(key)`` reads them from the account. The sealed
rows are kept in ``secrets\\phone_rows.json``, because a PC restarted with the
house's internet down must still open its door (§3's "Home: nobody" rests on
this), and opening them needs only the account key, which is local.

NOTHING HERE KNOWS A NETWORK. This is a product for whoever downloads it, on
any router and any network: the addresses come from the machine's own
adapters at the moment they are asked for, the port from wherever the door
landed, and the firewall's profile from what Windows says about the network
it is on. No address, subnet, port or profile is written into this file.

RULES, the ones vault.py keeps. A key or a passphrase is made here, written
and forgotten: never logged, never put in a status, a report or a message.
What IS logged is that an identity exists, and its fingerprint. This module
imports no transport and reads no environment; a test holds that.
"""
from __future__ import annotations

import base64
import ctypes
import functools
import hashlib
import json
import logging
import os
import re
import secrets as _secrets
import subprocess
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


# ---------------------------------------------------------------- the rows
#
# Every device writes its own row and no other, sealed under the account key
# (vault.AAD_DEVICE), so the server cannot add a device: a row that does not
# open is ignored. A phone: {"v", "kind": "phone", "cert": <the DER, base64>,
# "proto", "backup"}. A PC: {"v", "kind": "pc", "cert": <SHA-256, hex>,
# "addrs", "port", "proto", "words_sync"}. An unknown field is ignored.

#: What this PC's door speaks, in a `link` row.
PROTO = 1
#: A row is small and a PC has few adapters; the sealed column is not free.
MAX_ADDRS = 8


def _uid() -> str:
    """The signed-in account's id, off the local session: no network."""
    import sb

    who = sb.user()
    return str((who or {}).get("id") or "")


def _read_rows() -> dict:
    """The file: {"uid", "rows": [the devices' rows, sealed], "forgotten",
    "known": [the ids of the phones seen]}; {} when there is none."""
    try:
        data = json.loads(rows_path().read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_rows(data: dict) -> None:
    target = rows_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    os.replace(tmp, target)


def _forgotten(kept: dict) -> set[str]:
    """Who stays out: what the account says, and what this file last heard
    of it. This list only ever grows, whatever a row says."""
    import sb

    gone = {str(x) for x in kept.get("forgotten") or []}
    try:
        gone |= {str(x) for x in sb.forgotten()}
    except Exception as e:                                   # noqa: BLE001
        log.debug("phone: the forgotten list was not read (%s)", type(e).__name__)
    return gone


def _open_rows(key: bytes, uid: str, rows: list, gone: set[str]) -> list[dict]:
    """The rows that open under the account key and are not forgotten, each
    the row's plain columns with ``link`` opened. The only reader: a row
    that does not open is nobody."""
    import vault

    out = []
    for row in rows:
        ident = str(row.get("id") or "")
        sealed = row.get("link")
        if not sealed or not ident or ident in gone:
            continue
        try:
            link = vault.open_json(key, str(sealed), vault.AAD_DEVICE.format(uid=uid, device_id=ident))
        except vault.VaultError as e:
            log.info("phone: a device's row did not open (%s) — ignored", e)
            continue
        if isinstance(link, dict):
            out.append({**{k: v for k, v in row.items() if k != "link"}, "link": link})
    return out


def _phone_cert(link: dict) -> bytes | None:
    """A phone's certificate, or None for a row that is not a phone's."""
    if link.get("kind") != "phone":
        return None
    try:
        return base64.b64decode(str(link.get("cert") or ""), validate=True) or None
    except ValueError:
        return None


def anchors(key: bytes | None = None) -> dict[str, dict]:
    """fingerprint -> {"device", "name", "der"}: every phone of the account
    that may come through the door, out of the kept rows, so this needs no
    network: opening them takes only the account key, which is local."""
    import vault

    with _lock:
        kept = _read_rows()
        uid = _uid()
        if not uid or str(kept.get("uid") or "") != uid:
            return {}
        key = key or vault.key(uid)
        if key is None:
            return {}
        gone = _forgotten(kept)
        out: dict[str, dict] = {}
        for row in _open_rows(key, uid, kept.get("rows") or [], gone):
            der = _phone_cert(row["link"])
            if der is None:
                continue
            mark = fingerprint(der)
            if mark in gone:                 # a new id under a forgotten certificate
                continue
            out[mark] = {"device": str(row["id"]), "name": str(row.get("name") or ""), "der": der}
        return out


def refresh(key: bytes) -> list[str]:
    """Read the account's rows and keep them; the ids of the phones this PC
    has not seen before. An account that cannot be read raises and leaves
    the file as it is: a door must not close because the internet went."""
    import sb

    with _lock:
        rows = sb.devices()
        uid = _uid()
        if not uid:
            return []
        kept = _read_rows()
        same = str(kept.get("uid") or "") == uid
        gone = _forgotten(kept if same else {})
        known = {str(i) for i in kept.get("known") or []} if same else set()
        keep = [{k: r.get(k) for k in ("id", "name", "platform", "last_seen", "link")}
                for r in rows]
        phones = [str(r["id"]) for r in _open_rows(key, uid, keep, gone)
                  if _phone_cert(r["link"]) is not None]
        fresh = [i for i in phones if i not in known]
        _write_rows({"uid": uid, "rows": keep, "forgotten": sorted(gone),
                     "known": sorted(known | set(phones)), "at": int(time.time()),
                     "seen": (kept.get("seen") or {}) if same else {}})
        return fresh


#: (the rows file's stamp, the session's id) -> view(), so the status poll
#: pays a stat and not an AES-GCM per row, every 800 ms.
_view_kept: tuple | None = None


def _stamp() -> tuple:
    try:
        st = rows_path().stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return 0, 0


def view() -> dict:
    """{"phones": [...], "pcs": [...]}: the devices of the account that open
    and are not forgotten, for the desk, off the kept rows with no network.
    Each is {"id", "name", "cert"}, and a phone has "reached" and "dictated"
    too, 0 until it has. This PC is not among them."""
    global _view_kept
    import sb
    import vault

    with _lock:
        uid = _uid()
        mark = (_stamp(), uid)
        if _view_kept is not None and _view_kept[0] == mark:
            return _view_kept[1]
        out: dict[str, list] = {"phones": [], "pcs": []}
        kept = _read_rows()
        key = vault.key(uid) if uid and str(kept.get("uid") or "") == uid else None
        if key is not None:
            gone = _forgotten(kept)
            seen = kept.get("seen") or {}
            mine = sb.device_id()
            for row in _open_rows(key, uid, kept.get("rows") or [], gone):
                link, ident = row["link"], str(row["id"])
                name = str(row.get("name") or "")
                der = _phone_cert(link)
                if der is not None:
                    cert = fingerprint(der)
                    if cert not in gone:
                        one = seen.get(cert) or {}
                        out["phones"].append({"id": ident, "name": name, "cert": cert,
                                              "reached": int(one.get("reached") or 0),
                                              "dictated": int(one.get("dictated") or 0)})
                elif link.get("kind") == "pc" and ident != mine:
                    out["pcs"].append({"id": ident, "name": name,
                                       "cert": str(link.get("cert") or "")})
        _view_kept = (mark, out)
        return out


#: How often a phone that only knocks rewrites the file. A dictation always
#: does: the desk's "dictated here today" reads it.
SEEN_WRITE_S = 60


def saw(cert: str, *, dictated: bool = False) -> None:
    """A phone came through the door, or dictated: Settings > Phone says so,
    and "hasn't reached this PC yet" is the one hint a person has that the
    firewall stands between them, because a PC cannot test its own door."""
    now = int(time.time())
    with _lock:
        kept = _read_rows()
        if not kept:
            return
        seen = kept.setdefault("seen", {})
        one = seen.setdefault(cert, {})
        if not dictated and now - int(one.get("reached") or 0) < SEEN_WRITE_S:
            return
        one["reached"] = now
        if dictated:
            one["dictated"] = now
        try:
            _write_rows(kept)
        except OSError as e:                # a line on a card must not cost a dictation
            log.debug("phone: what a phone did was not kept (%s)", type(e).__name__)


def drop_rows() -> None:
    """Signed out: what the door opened from goes with the session."""
    with _lock:
        try:
            rows_path().unlink()
        except FileNotFoundError:
            pass


def publish(key: bytes, *, port: int, listening: bool, words_sync: bool) -> bool:
    """This PC's ``link`` row, when anything in it changed; True when one
    went out. ``listening`` is whether a phone should try here at all: a
    PC that said no, or has the switch off, names no address."""
    import sb
    import vault

    with _lock:
        uid = _uid()
        mine = sb.device_id()
        kept = _read_rows()
        if not uid or mine in _forgotten(kept):
            return False
        row = {"v": 1, "kind": "pc", "cert": identity(),
               "addrs": addresses() if listening else [], "port": int(port), "proto": PROTO,
               "words_sync": bool(words_sync)}
        here = [r for r in kept.get("rows") or [] if str(r.get("id") or "") == mine]
        opened = _open_rows(key, uid, here, set())
        if opened and opened[0]["link"] == row:
            return False
        sb.write_link(vault.seal_json(key, row, vault.AAD_DEVICE.format(uid=uid, device_id=mine)))
        log.info("phone: this PC's row went out (%d address(es), port %d)", len(row["addrs"]), port)
        return True


# ------------------------------------------------------------ the addresses
#
# Every IPv4 of a real adapter that is up, the default route's first, and
# never Tailscale's 100.x or a virtual adapter's: the phone tries them all at
# once and keeps the one that answers, so a wrong one costs little, and it
# still is an address nobody can reach. Private on nearly every network, and
# not filtered to that: some campus and hotel networks, and a PC straight on
# a modem, hand out routable ones, and the row is sealed either way. A
# private handle on iphlpapi, for the reason the CNG one is private.

_AF_INET = 2
_GAA_SKIP = 0x2 | 0x4 | 0x8            # no anycast, multicast or DNS lists
_ERROR_BUFFER_OVERFLOW = 111
_IF_UP = 1
#: Loopback, tunnels, PPP dial-ups, and what Windows itself calls virtual
#: (Tailscale's and WireGuard's adapters among them).
_IF_NOT_A_NETWORK = (24, 131, 23, 53)
#: Windows gives these no type of their own: a Hyper-V or WSL switch is plain
#: Ethernet to it, so the adapter's own words are all there is to go on.
_VIRTUAL = re.compile(r"tailscale|hyper-v|vethernet|wsl|virtualbox|vmware|wireguard|wintun"
                      r"|tap-windows|openvpn|zerotier|hamachi|docker|bluetooth|loopback", re.I)


class _Unicast(ctypes.Structure):
    _fields_ = [("Length", ctypes.c_ulong), ("Flags", ctypes.c_ulong), ("Next", ctypes.c_void_p),
                ("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", ctypes.c_int)]


class _Adapter(ctypes.Structure):
    """The head of IP_ADAPTER_ADDRESSES, as far as the fields read here."""

    _fields_ = [("Length", ctypes.c_ulong), ("IfIndex", ctypes.c_ulong), ("Next", ctypes.c_void_p),
                ("AdapterName", ctypes.c_char_p), ("FirstUnicastAddress", ctypes.c_void_p),
                ("FirstAnycastAddress", ctypes.c_void_p),
                ("FirstMulticastAddress", ctypes.c_void_p),
                ("FirstDnsServerAddress", ctypes.c_void_p), ("DnsSuffix", ctypes.c_wchar_p),
                ("Description", ctypes.c_wchar_p), ("FriendlyName", ctypes.c_wchar_p),
                ("PhysicalAddress", ctypes.c_ubyte * 8), ("PhysicalAddressLength", ctypes.c_ulong),
                ("Flags", ctypes.c_ulong), ("Mtu", ctypes.c_ulong), ("IfType", ctypes.c_ulong),
                ("OperStatus", ctypes.c_int)]


def _reachable(ip: str) -> bool:
    """An address another device could dial: not loopback, not "this
    host", not the link-local one Windows gives itself with no network."""
    try:
        a, b = [int(x) for x in ip.split(".")[:2]]
    except ValueError:
        return False
    return not (a in (0, 127) or (a == 169 and b == 254))


def pick_addresses(adapters: list[dict], default_index: int | None) -> list[str]:
    """The row's list, from what Windows said. Pure, so a test can drive it
    with Tailscale, WSL and a laptop's two networks. Each adapter is
    {"index", "name", "description", "type", "up", "ipv4": [...]}."""
    usable = []
    for a in adapters:
        words = f"{a.get('name') or ''} {a.get('description') or ''}"
        if not a.get("up") or a.get("type") in _IF_NOT_A_NETWORK or _VIRTUAL.search(words):
            continue
        usable.append(a)
    usable.sort(key=lambda a: (a.get("index") != default_index, a.get("index") or 0))
    out: list[str] = []
    for a in usable:
        for ip in a.get("ipv4") or []:
            if _reachable(ip) and ip not in out:
                out.append(ip)
    return out[:MAX_ADDRS]


def _adapters() -> tuple[list[dict], int | None]:
    """What Windows says: the adapters, and the index of the default route's
    (asked about a public address, and nothing is sent)."""
    ip = ctypes.WinDLL("iphlpapi")
    size = ctypes.c_ulong(16 * 1024)
    buf = ctypes.create_string_buffer(size.value)
    status = ip.GetAdaptersAddresses(_AF_INET, _GAA_SKIP, None, buf, ctypes.byref(size))
    if status == _ERROR_BUFFER_OVERFLOW:
        buf = ctypes.create_string_buffer(size.value)
        status = ip.GetAdaptersAddresses(_AF_INET, _GAA_SKIP, None, buf, ctypes.byref(size))
    if status != 0:
        raise OSError(f"GetAdaptersAddresses answered {status}")
    found = []
    at = ctypes.addressof(buf)
    while at:
        one = _Adapter.from_address(at)
        ips = []
        uni = one.FirstUnicastAddress
        while uni:
            entry = _Unicast.from_address(uni)
            raw = ctypes.string_at(entry.lpSockaddr, 8)    # sockaddr_in as far as the address
            if int.from_bytes(raw[:2], "little") == _AF_INET:
                ips.append(".".join(str(b) for b in raw[4:8]))
            uni = entry.Next
        found.append({"index": int(one.IfIndex), "name": one.FriendlyName or "",
                      "description": one.Description or "", "type": int(one.IfType),
                      "up": one.OperStatus == _IF_UP, "ipv4": ips})
        at = one.Next
    best = ctypes.c_ulong(0)
    default = int(best.value) if ip.GetBestInterface(0x08080808, ctypes.byref(best)) == 0 else None
    return found, default


_addrs_kept: tuple[float, list[str]] = (0.0, [])


def addresses(max_age: float = 0.0) -> list[str]:
    """This PC's addresses as Windows says them now, the default
    route's first; ``max_age`` lets a status poll use an answer that young
    (the call is 4.7 ms). Never raises: a row with no address is a phone
    that waits, not a failed start."""
    global _addrs_kept
    if max_age and time.monotonic() - _addrs_kept[0] < max_age:
        return list(_addrs_kept[1])
    try:
        found = pick_addresses(*_adapters())
    except (OSError, ValueError, AttributeError) as e:
        log.info("phone: the addresses could not be read (%s)", e)
        return []
    _addrs_kept = (time.monotonic(), found)
    return list(found)


# -------------------------------------------------------------- the firewall
#
# A PC cannot test this itself: a connection to its own address never crosses
# its firewall, so only the phone can tell. And Windows answers the first
# listen with a dialog whose Cancel writes a BLOCK rule, which outranks any
# allow rule, and whose choices depend on the network's profile and on who is
# signed in. So Settings > Phone carries one button that says yes properly:
# one elevated cmd.exe that deletes this program's block rules and allows
# this program on this port, on the profile of the network the PC is on.
#
# An administrator presses Yes. A standard user meets Windows' own prompt for
# an administrator's password, and with none to give the answer is plain
# words on the card: nothing here can go round that, and nothing should. It
# works on any profile because the profile is read at the press, and when it
# cannot be read the rule says any.

#: The rule's name in Windows Firewall. A copy's own, so two copies on one PC
#: replace their own rule and nobody else's.
RULE_NAME = f"DeskIT{f' {paths.DEV_TAG}' if paths.DEV_TAG else ''} phone"
_FIREWALL_RULES = (r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters"
                   r"\FirewallPolicy\FirewallRules")
#: Only a name that cannot leave its quotes in an elevated cmd.exe is spelled
#: out; anything else is reached by its program instead.
_PLAIN_RULE = re.compile(r"[\w .()\-]+")
_NO_WINDOW = 0x08000000
_SEE_MASK_NOCLOSEPROCESS = 0x40
_SEE_MASK_FLAG_NO_UI = 0x400
_ERROR_CANCELLED = 1223
_INFINITE = 0xFFFFFFFF


def program() -> str:
    """The running image's own path, which is the program a firewall sees:
    under a venv that is the base interpreter, because the venv's pythonw is
    a launcher that starts it, and a rule on the launcher does nothing."""
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.WinDLL("kernel32").GetModuleFileNameW(None, buf, len(buf))
    return buf.value[:n] if n else ""


def network_profiles() -> str:
    """The profile words netsh takes for the networks this PC is on now
    (``public``, ``private``, ``domain``, comma-joined), or ``any`` when
    Windows will not say. Windows calls a new network Public unless told
    otherwise, so most people are there."""
    try:
        said = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-NetConnectionProfile).NetworkCategory"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=15,
            check=False, creationflags=_NO_WINDOW).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return "any"
    words = {"public": "public", "private": "private", "domainauthenticated": "domain"}
    found = sorted({words[w] for w in said.lower().split() if w in words})
    return ",".join(found) or "any"


def block_rules(exe: str) -> list[str] | None:
    """The names of the inbound rules that block ``exe``, read from the
    registry, which is plain words on a Hebrew Windows too where netsh's
    output is not. None when it cannot be read."""
    import winreg

    want = os.path.normcase(os.path.normpath(exe))
    names: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _FIREWALL_RULES) as hive:
            i = 0
            while True:
                try:
                    _name, value, _kind = winreg.EnumValue(hive, i)
                except OSError:
                    break
                i += 1
                parts = dict(p.split("=", 1) for p in str(value).split("|") if "=" in p)
                app = os.path.expandvars(parts.get("App") or "")
                if (parts.get("Action") == "Block" and parts.get("Dir") == "In" and app
                        and os.path.normcase(os.path.normpath(app)) == want):
                    names.append(parts.get("Name") or "")
    except OSError:
        return None
    return names


def firewall_line(netsh: str, exe: str, port: int, profiles: str,
                  blocks: list[str] | None) -> str:
    """The whole line the elevated cmd.exe runs. Pure, so a test can read it.

    netsh's delete has no ``action=`` filter, so a block rule is deleted by
    its name; a name that is not plain, or a registry that could not be read,
    takes every inbound rule of this program with it, which the allow below
    replaces. Our own rule goes first, so pressing twice leaves one."""
    fw = f'"{netsh}" advfirewall firewall'
    prog = f'program="{exe}"'
    steps = [f'{fw} delete rule name="{RULE_NAME}" dir=in']
    names = [] if blocks is None else [n for n in dict.fromkeys(blocks) if n]
    if blocks is None or not all(_PLAIN_RULE.fullmatch(n) for n in names):
        steps.append(f'{fw} delete rule name=all dir=in {prog}')
    else:
        steps += [f'{fw} delete rule name="{n}" dir=in {prog}' for n in names]
    steps.append(f'{fw} add rule name="{RULE_NAME}" dir=in action=allow {prog} '
                 f'protocol=TCP localport={int(port)} profile={profiles}')
    return " & ".join(steps)


class _ExecuteInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("fMask", ctypes.c_ulong), ("hwnd", ctypes.c_void_p),
                ("lpVerb", ctypes.c_wchar_p), ("lpFile", ctypes.c_wchar_p),
                ("lpParameters", ctypes.c_wchar_p), ("lpDirectory", ctypes.c_wchar_p),
                ("nShow", ctypes.c_int), ("hInstApp", ctypes.c_void_p),
                ("lpIDList", ctypes.c_void_p), ("lpClass", ctypes.c_wchar_p),
                ("hkeyClass", ctypes.c_void_p), ("dwHotKey", ctypes.c_ulong),
                ("hIcon", ctypes.c_void_p), ("hProcess", ctypes.c_void_p)]


def _elevated(system: str, line: str, verb: str = "runas") -> str:
    """One elevated, windowless cmd.exe; done, declined or failed. Absolute
    paths and system32 as its folder: an elevated cmd.exe looks in its own
    folder first, and that folder must not be one a person can write to.
    ``verb`` is a test's way through this code with no prompt."""
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32")
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    info = _ExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_FLAG_NO_UI
    info.lpVerb = verb
    info.lpFile = os.path.join(system, "cmd.exe")
    info.lpParameters = f'/s /c "{line}"'
    info.lpDirectory = system
    info.nShow = 0
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        return "declined" if error == _ERROR_CANCELLED else "failed"
    if not info.hProcess:
        return "failed"
    try:
        k32.WaitForSingleObject(info.hProcess, _INFINITE)
        code = ctypes.c_ulong(1)
        k32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return "done" if code.value == 0 else "failed"
    finally:
        k32.CloseHandle(info.hProcess)


def open_firewall(exe: str, port: int) -> str:
    """The phone can't connect? Called from the desk, on the press, because
    the prompt comes up in front of whoever owns the foreground, and a
    windowless process would only flash in the taskbar. Waits for the
    person's answer: ``done``, ``declined`` or ``failed``."""
    buf = ctypes.create_unicode_buffer(260)
    n = ctypes.WinDLL("kernel32").GetSystemDirectoryW(buf, len(buf))
    system = buf.value[:n]
    if not (system and exe and port):
        return "failed"
    line = firewall_line(os.path.join(system, "netsh.exe"), exe, port, network_profiles(),
                         block_rules(exe))
    log.info("phone: asking Windows to let this program through on port %d", port)
    return _elevated(system, line)


# ------------------------------------------------------------------ the QR

def download_url() -> str:
    """Where the keyboard comes from: the newest release's page, which
    exists whatever a release holds. It is only an address and holds no
    secret; a person's own account does the rest."""
    import updates

    return f"https://github.com/{updates.REPO}/releases/latest"


def qr_rows(text: str) -> list[list] | None:
    """A QR of ``text`` as rows of truths; None without segno, when a card
    says the address in words instead."""
    try:
        import segno
    except ImportError:
        return None
    return [list(r) for r in segno.make(text, error="m", boost_error=False).matrix]


@functools.lru_cache(maxsize=4)
def qr(text: str) -> tuple[str, int] | None:
    """A QR of ``text`` as one SVG path and its side in modules."""
    rows = qr_rows(text)
    if rows is None:
        return None
    path: list[str] = []
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            if not row[x]:
                x += 1
                continue
            start = x
            while x < len(row) and row[x]:
                x += 1
            path.append(f"M{start} {y}h{x - start}v1h-{x - start}z")
    return "".join(path), len(rows)
