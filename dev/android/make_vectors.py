"""The test vectors of android/app/src/test/.../CryptChecks.kt, written by the
real vault.py: a key pair the way CNG makes it, a hand-over the way a PC makes
one, and the other direction with a chosen ephemeral pair and a chosen nonce,
so a hand-over made in Kotlin has to come out byte for byte.

    <venv python> dev\\android\\make_vectors.py

prints Kotlin constants to paste over the block in CryptChecks.kt. Fresh keys
every run, and all of them throwaway: nothing here is any account's. It needs
nothing from the app but vault.py, and it opens no window.
"""
import base64
import os
import pathlib
import sys

os.environ.setdefault("DESKIT_SUITE", "1")      # the test slots, never a real one
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import vault                                     # noqa: E402


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def scalar(blob: bytes) -> bytes:
    """d out of a CNG private blob: header (8), X, Y, d."""
    return blob[8 + 64:8 + 96]


def main() -> None:
    uid = "11111111-2222-3333-4444-555555555555"
    pid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    aad = vault.AAD_PAIRING.format(uid=uid, pairing_id=pid)
    account = bytes(range(32))

    # a PC handing the key to a phone: the shared secret in CNG's order
    priv, point = vault._ecdh_keypair()
    public = "p1." + b64(point)
    handed = vault.hand_over(account, public, aad)
    vault._applicants[pid] = priv
    assert vault.take(pid, handed, aad) == account

    # a phone handing the key to a PC: everything chosen, so Kotlin's bytes
    # can be compared, and vault.take opens it first
    pc_priv, pc_point = vault._ecdh_keypair()
    eph_priv, eph_point = vault._ecdh_keypair()
    nonce = bytes(range(100, 112))
    shared = vault._ecdh_shared(eph_priv, pc_point)
    wrap = vault._hkdf(shared, b"deskit pairing v1" + eph_point + pc_point)
    ct, tag = vault._gcm(wrap, nonce, account, aad.encode("utf-8"), encrypt=True)
    made = "w1." + b64(eph_point + nonce + ct + tag)
    other = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"
    vault._applicants[other] = pc_priv
    assert vault.take(other, made, aad) == account

    # a sealed row, and its fingerprint
    sealed_nonce = bytes(range(50, 62))
    plain = '{"v":"gsk_not_a_real_key"}'.encode("utf-8")
    row_aad = vault.AAD_VAULT.format(uid=uid, name="groq")
    row_ct, row_tag = vault._gcm(account, sealed_nonce, plain, row_aad.encode("utf-8"), encrypt=True)
    row = "v1." + b64(sealed_nonce + row_ct + row_tag)
    assert vault.open_json(account, row, row_aad) == {"v": "gsk_not_a_real_key"}

    print(f'    private const val PHONE_D = "{scalar(priv).hex()}"')
    print(f'    private const val PHONE_POINT = "{b64(point)}"')
    print(f'    private const val HANDED_BY_PC = "{handed}"')
    print(f'    private const val PC_POINT = "{b64(pc_point)}"')
    print(f'    private const val EPH_D = "{scalar(eph_priv).hex()}"')
    print(f'    private const val EPH_POINT = "{b64(eph_point)}"')
    print(f'    private const val HANDED_TO_PC = "{made}"')
    print(f'    private const val ROW = "{row}"')
    print(f'    private const val LOCK_ID = "{vault.fingerprint(account)}"')


if __name__ == "__main__":
    main()
