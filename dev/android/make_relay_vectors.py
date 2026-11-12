"""The relay's test vectors (android/app/src/test/.../RelayChecks.kt), written by
the real relay.py and vault.py: a piece the PC seals, with a chosen nonce, so the
phone must open it and seal the same head to the same bytes.

    <venv python> dev\\android\\make_relay_vectors.py

prints Kotlin constants to paste over the block in RelayChecks.kt. Throwaway
keys and ids, nobody's. Opens no window, touches no store.
"""
import os
import pathlib
import sys

os.environ.setdefault("DESKIT_SUITE", "1")      # the test slots, never a real one
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import relay                                     # noqa: E402
import vault                                     # noqa: E402

UID = "11111111-2222-3333-4444-555555555555"
PC = "aaaaaaaa-0000-4000-8000-000000000001"
PHONE = "bbbbbbbb-0000-4000-8000-000000000002"
RID = "0123456789abcdef0123456789abcdef"


def chosen(nonce: bytes):
    """vault.seal with this nonce, for one call."""
    real = vault.os.urandom

    def urandom(n: int) -> bytes:
        vault.os.urandom = real
        assert n == len(nonce)
        return nonce
    vault.os.urandom = urandom


def main() -> None:
    key = bytes(range(32))
    # the PC's text, as relay.Relay sends it: Hebrew, a float, nested
    chosen(bytes(range(10, 22)))
    text = relay.seal(key, UID, PC, PHONE, RID, relay.N_TEXT,
                      {"k": "text", "status": 200,
                       "body": {"text": "שלום \"מהדרך\"", "seconds": 4.5, "backend": "local"}})
    assert relay.open_(key, UID, text)[0]["body"]["text"] == "שלום \"מהדרך\""
    # a ping, as the phone seals it: the phone must come out byte for byte
    chosen(bytes(range(30, 42)))
    ping = relay.seal(key, UID, PHONE, "*", RID, 0, {"k": "ping"})
    # an audio piece with a body
    chosen(bytes(range(50, 62)))
    audio = relay.seal(key, UID, PHONE, PC, RID, 3, {"k": "audio"}, bytes(range(256)) * 4)
    print(f'    const val TEXT_S = "{text["s"]}"')
    print(f'    const val PING_S = "{ping["s"]}"')
    print(f'    const val AUDIO_S = "{audio["s"]}"')


if __name__ == "__main__":
    main()
