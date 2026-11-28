"""Sign a release's update feed on the owner's PC — the half of signed
updates that never touches GitHub (update_sig.py has the why and the
format; AGENTS.md rule 9 has where it sits in a release).

    python dev\\sign_release.py --new-key        once: make the pair
    python dev\\sign_release.py --sign v1.2.3    the DRAFT's latest.json
    python dev\\sign_release.py --verify v1.2.3  any release, draft or not
    python dev\\sign_release.py --check-pinned   release.yml's first gate

--new-key makes an ECDSA P-256 pair through Windows' CNG. The PRIVATE half
goes into this PC's Credential Manager under the checkout's own prefix,
as `DeskIT.dev/release-signing-key` (generic credential, this Windows
account, encrypted by Windows with DPAPI; the base64 of CNG's private
blob). Credential Manager and not a file under secrets\\, because it is the
same slot from the main checkout and from every worktree, and it
survives the checkout being wiped or cloned again. The PUBLIC half is
written into update_key.py, which is committed and shipped: every copy
built after that checks every feed against it. It refuses when a key is
already in the slot, and when update_key.py already pins a real key —
making a second key strands every copy that pins the first.

--sign <tag> downloads latest.json from that release with the gh CLI,
refuses unless the release is still a DRAFT (a published feed is what
copies are reading right now), checks the file is a feed for that very
version, signs its exact bytes, and uploads latest.json.sig beside it
(`gh release upload --clobber`), then reads both back and verifies them.

--verify <tag> reads latest.json and latest.json.sig back from GitHub and
checks them against the key update_key.py pins. Exit 0 = signed, 1 = not.

--check-pinned: exit 1 while update_key.py holds the placeholder (or
anything that is not a P-256 point). release.yml runs it before it builds
anything, because a copy built with the placeholder can verify nothing
and would refuse every update for the rest of its life.

--new-key and --sign refuse to run under DESKIT_SUITE: a test never makes
or uses the owner's key. If the private key is ever lost, installed
copies stop installing updates on their own and tell the person to
download from the website (update_sig.py); that is the whole recovery.

Never imported by a product module (tests.DEV_MODULES holds the name).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

import update_sig  # noqa: E402

GH_REPO = "DeskIT-app/DeskIT"
KEY_NAME = "release-signing-key"
#: The checkout's own Credential Manager prefix (secretstore.prefix_for).
CHECKOUT_PREFIX = "DeskIT.dev"
TAG = re.compile(r"\Av\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?\Z")
KEY_FILE = REPO / "update_key.py"
_PUBLIC_LINE = re.compile(r'^PUBLIC_KEY = "[^"\r\n]*"(?=\r?$)', re.M)
_NO_WINDOW = 0x08000000


class Refused(Exception):
    """Said and exit 2: nothing was changed."""


def _not_under_the_suite(what: str) -> None:
    if os.environ.get("DESKIT_SUITE", "").strip() == "1":
        raise Refused(f"{what} refused under DESKIT_SUITE: a test never makes or "
                      f"uses the owner's release key")


# ------------------------------------------------ the private key's slot

def _target() -> str:
    import secretstore
    if secretstore.TARGET_PREFIX != CHECKOUT_PREFIX:
        raise Refused(f"this is not the checkout's own copy (prefix "
                      f"{secretstore.TARGET_PREFIX!r}, not {CHECKOUT_PREFIX!r}); run "
                      f"it from the checkout with no DESKIT_HOME or hatch set")
    return f"{CHECKOUT_PREFIX}/{KEY_NAME}"


def _read_private() -> bytes | None:
    import pywintypes
    import win32cred
    try:
        cred = win32cred.CredRead(TargetName=_target(), Type=win32cred.CRED_TYPE_GENERIC)
    except pywintypes.error as e:
        if e.winerror == 1168:                         # ERROR_NOT_FOUND
            return None
        raise Refused(f"Credential Manager refused to read {_target()}: {e.strerror}")
    text = bytes(cred.get("CredentialBlob") or b"").decode("utf-16-le").strip("\x00").strip()
    return base64.b64decode(text, validate=True) if text else None


def _write_private(private: bytes) -> None:
    import win32cred
    win32cred.CredWrite({
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": _target(),
        "UserName": "DeskIT release",
        "CredentialBlob": base64.b64encode(private).decode("ascii"),
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        "Comment": "DeskIT: the key the owner signs every update with. Do not "
                   "delete it: without it installed copies can no longer be "
                   "updated by the app.",
    }, 0)


# ------------------------------------------------------------- gh

def _gh(*args: str) -> str:
    proc = subprocess.run(["gh", *args, "--repo", GH_REPO], capture_output=True,
                          text=True, creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise Refused(f"gh {' '.join(args[:2])} failed: "
                      f"{(proc.stderr or proc.stdout).strip()[:300]}")
    return proc.stdout


def _release(tag: str) -> dict:
    if not TAG.match(tag):
        raise Refused(f"{tag!r} is not a release tag like v1.2.3")
    return json.loads(_gh("release", "view", tag, "--json", "tagName,isDraft,assets"))


def _download(tag: str, name: str, folder: Path) -> bytes | None:
    """The asset's exact bytes, or None when the release has no such asset."""
    names = {str(a.get("name")) for a in _release(tag).get("assets") or []}
    if name not in names:
        return None
    _gh("release", "download", tag, "--pattern", name, "--dir", str(folder), "--clobber")
    return (folder / name).read_bytes()


# ------------------------------------------------------------- the verbs

def new_key() -> int:
    _not_under_the_suite("--new-key")
    if not update_sig.pinned_problem() or update_sig.PLACEHOLDER not in update_sig.pinned():
        raise Refused("update_key.py already pins a key. If its private half is "
                      "truly lost, put the placeholder line back in update_key.py by "
                      "hand first: every installed copy will then have to be "
                      "downloaded again from the website.")
    if _read_private() is not None:
        raise Refused(f"{_target()} already holds a key: a second one would strand "
                      f"every copy that pins the first")
    private, public = update_sig.new_pair()
    _write_private(private)
    if _read_private() != private:
        raise Refused("the key did not read back from Credential Manager the same")
    text = KEY_FILE.read_bytes().decode("utf-8")       # its line ends as they are
    if len(_PUBLIC_LINE.findall(text)) != 1:
        raise Refused("update_key.py does not have exactly one PUBLIC_KEY line")
    KEY_FILE.write_bytes(_PUBLIC_LINE.sub(f'PUBLIC_KEY = "{public}"', text)
                         .encode("utf-8"))
    del private
    print(f"the private key is in Credential Manager as {_target()}")
    print(f"the public key is in {KEY_FILE.name}: {public}")
    print("commit update_key.py; every copy built after that checks updates against it")
    return 0


def sign(tag: str) -> int:
    _not_under_the_suite("--sign")
    rel = _release(tag)
    if not rel.get("isDraft"):
        raise Refused(f"{tag} is already published: copies are reading its feed now; "
                      f"only a draft is signed")
    problem = update_sig.pinned_problem()
    if problem:
        raise Refused(f"update_key.py: {problem}")
    with tempfile.TemporaryDirectory() as d:
        data = _download(tag, "latest.json", Path(d))
        if data is None:
            raise Refused(f"{tag} has no latest.json")
        import updates
        feed = updates.Release.parse(json.loads(data.decode("utf-8")))
        if "v" + feed.version != tag:
            raise Refused(f"{tag}'s latest.json is the feed of {feed.version}")
        private = _read_private()
        if private is None:
            raise Refused(f"no signing key in {_target()}: run --new-key first, once")
        if update_sig.public_of(private) != update_sig.pinned():
            raise Refused("the key in Credential Manager is not the one update_key.py "
                          "pins: copies would not accept this signature")
        sig = update_sig.sign(private, data)
        del private
        update_sig.verify(data, sig)
        out = Path(d) / "latest.json.sig"
        out.write_bytes(sig.encode("ascii"))
        _gh("release", "upload", tag, str(out), "--clobber")
    print(f"signed {tag}: latest.json.sig uploaded")
    return verify(tag)


def verify(tag: str) -> int:
    rel = _release(tag)
    with tempfile.TemporaryDirectory() as d:
        data = _download(tag, "latest.json", Path(d))
        sig = _download(tag, "latest.json.sig", Path(d))
    if data is None:
        print(f"{tag}: no latest.json")
        return 1
    try:
        update_sig.verify(data, sig)
    except update_sig.FeedSignatureError as e:
        print(f"{tag}: NOT signed for installed copies: {e}")
        return 1
    print(f"{tag}: latest.json is signed by the key update_key.py pins"
          f"{' (still a draft)' if rel.get('isDraft') else ''}")
    return 0


def check_pinned() -> int:
    problem = update_sig.pinned_problem()
    if problem:
        print(f"update_key.py: {problem}. Run dev/sign_release.py --new-key on the "
              f"owner's PC and commit update_key.py before building a release: a "
              f"copy built without a key can never install an update.")
        return 1
    print(f"update_key.py pins {update_sig.pinned()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--new-key", action="store_true")
    g.add_argument("--sign", metavar="TAG")
    g.add_argument("--verify", metavar="TAG")
    g.add_argument("--check-pinned", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.new_key:
            return new_key()
        if a.sign:
            return sign(a.sign)
        if a.verify:
            return verify(a.verify)
        return check_pinned()
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
