"""The keyboard's release signing key, on the owner's PC: the Android half
of a release (DISTRIBUTION_PLAN.md 12.7, PHONE_LINK_PLAN.md "Getting the
keyboard"). The PC half is dev\\sign_release.py; this file is its twin.

    python dev\\keyboard_key.py --new                once: the keystore, its passphrase, the secrets
    python dev\\keyboard_key.py --secrets            give GitHub the two secrets again
    python dev\\keyboard_key.py --check              it opens, it is the pinned key, the secrets exist
    python dev\\keyboard_key.py --sign IN.apk OUT.apk   a release APK built on this PC
    python dev\\keyboard_key.py --backup FOLDER [--passphrase-to FILE]
    python dev\\keyboard_key.py --restore KEYSTORE PASSPHRASE_FILE

Why it matters: Android installs an update only when it carries the SAME
signing key as the copy on the phone. Lose this key and every phone that has
the keyboard must uninstall it and install a new one, with a new identity.
So it is made once, kept in two backups by the owner, and never made again.

--new makes a PKCS#12 keystore with one RSA 4096 key, valid 30 years, under
the alias `deskit`, in a folder OUTSIDE every git checkout
(Desktop\\Organized\\Projects\\DeskIT-keys by default). Its passphrase is 32
random bytes (43 characters) that are never printed, logged or written to a
file: Credential Manager holds them, under the checkout's own prefix as
`DeskIT.dev/keyboard-keystore-passphrase` — the slot sign_release.py's key
sits beside, which every worktree of this checkout shares. keytool and
apksigner are handed the passphrase in an environment variable of their own
process (`-storepass:env`, `--ks-pass env:`), never on a command line. Then
the certificate's SHA-256 goes into android/release-cert.sha256, which is
committed: release.yml refuses an APK signed with any other key. It refuses
when a keystore, a passphrase or a pinned certificate already exists: a
second key strands every phone that has the first.

--secrets hands GitHub the keystore (base64) and the passphrase as the
repository secrets ANDROID_KEYSTORE_B64 and ANDROID_KEYSTORE_PASSWORD, through
`gh secret set` reading stdin, and checks both NAMES are listed (a secret's
value can never be read back).

--backup FOLDER copies the keystore into FOLDER, writes the passphrase to
FILE (FOLDER\\keyboard-keystore-passphrase.txt unless --passphrase-to names
another place), checks the copy opens with it, and leaves a README beside
them. It prints file names only. Keep the two apart: the keystore without
the passphrase is useless to a thief, and so is the passphrase without it.

--restore puts a backed-up keystore back and the passphrase into Credential
Manager, on a new PC, and checks the pair is the pinned key.

--new, --secrets, --backup, --restore and --sign refuse under DESKIT_SUITE:
a test never makes, moves or uses the owner's key. Never imported by a
product module (tests.DEV_MODULES holds the name).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

GH_REPO = "DeskIT-app/DeskIT"
#: Where the keystore lives: beside the projects, in no git checkout.
KEY_DIR = Path.home() / "Desktop" / "Organized" / "Projects" / "DeskIT-keys"
STORE_NAME = "deskit-keyboard-release.p12"
ALIAS = "deskit"
#: The certificate's subject. It is public — every APK carries it — so it
#: names the app and nobody.
DNAME = "CN=DeskIT, O=DeskIT"
VALIDITY_DAYS = 30 * 365
PASS_NAME = "keyboard-keystore-passphrase"
#: The checkout's own Credential Manager prefix (secretstore.prefix_for).
CHECKOUT_PREFIX = "DeskIT.dev"
#: The repository secrets release.yml's `signing` job reads, by these names.
SECRET_STORE = "ANDROID_KEYSTORE_B64"
SECRET_PASS = "ANDROID_KEYSTORE_PASSWORD"
#: The pinned certificate: one line, 64 hex, committed.
CERT_FILE = REPO / "android" / "release-cert.sha256"
PASSPHRASE_FILE = "keyboard-keystore-passphrase.txt"
#: The one environment variable the passphrase ever travels in, and only
#: into keytool's or apksigner's own process.
_ENV = "DESKIT_KEYSTORE_PASS"
_NO_WINDOW = 0x08000000
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")


class Refused(Exception):
    """Said and exit 2: nothing was changed."""


def _not_under_the_suite(what: str) -> None:
    if os.environ.get("DESKIT_SUITE", "").strip() == "1":
        raise Refused(f"{what} refused under DESKIT_SUITE: a test never makes, moves or "
                      f"uses the owner's keyboard key")


# ------------------------------------------------------------ the tools

def _java_home() -> Path:
    for p in (os.environ.get("JAVA_HOME"), str(Path.home() / "dev-tools" / "jdk")):
        if p and (Path(p) / "bin" / "keytool.exe").exists():
            return Path(p)
    raise Refused("no JDK found: set JAVA_HOME (keytool and java come from it)")


def _build_tools() -> Path:
    for p in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
              str(Path.home() / "dev-tools" / "android-sdk")):
        bt = Path(p) / "build-tools" if p else None
        if bt and bt.is_dir():
            versions = sorted((d for d in bt.iterdir() if (d / "lib" / "apksigner.jar").exists()),
                              key=lambda d: [int(x) if x.isdigit() else 0 for x in d.name.split(".")])
            if versions:
                return versions[-1]
    raise Refused("no Android build-tools found: set ANDROID_HOME")


def _run(cmd: list[str], *, passphrase: str | None = None, what: str) -> str:
    """Run a tool; the passphrase, when there is one, only in its environment.
    A failure says the tool's last lines, which never hold the passphrase:
    it was never on the command line or in the input."""
    env = dict(os.environ)
    env.pop(_ENV, None)
    if passphrase is not None:
        env[_ENV] = passphrase
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                          creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-4:]
        raise Refused(f"{what} failed: {' / '.join(tail)[:400]}")
    return proc.stdout


def _keytool(*args: str, passphrase: str) -> str:
    return _run([str(_java_home() / "bin" / "keytool.exe"), *args],
                passphrase=passphrase, what="keytool")


def _apksigner(*args: str, passphrase: str | None = None) -> str:
    return _run([str(_java_home() / "bin" / "java.exe"), "-jar",
                 str(_build_tools() / "lib" / "apksigner.jar"), *args],
                passphrase=passphrase, what="apksigner")


# ---------------------------------------------- the passphrase's slot

def _target() -> str:
    import secretstore
    if secretstore.TARGET_PREFIX != CHECKOUT_PREFIX:
        raise Refused(f"this is not the checkout's own copy (prefix "
                      f"{secretstore.TARGET_PREFIX!r}, not {CHECKOUT_PREFIX!r}); run "
                      f"it from the checkout with no DESKIT_HOME or hatch set")
    return f"{CHECKOUT_PREFIX}/{PASS_NAME}"


def _read_pass() -> str | None:
    import pywintypes
    import win32cred
    try:
        cred = win32cred.CredRead(TargetName=_target(), Type=win32cred.CRED_TYPE_GENERIC)
    except pywintypes.error as e:
        if e.winerror == 1168:                         # ERROR_NOT_FOUND
            return None
        raise Refused(f"Credential Manager refused to read {_target()}: {e.strerror}")
    text = bytes(cred.get("CredentialBlob") or b"").decode("utf-16-le").strip("\x00").strip()
    return text or None


def _write_pass(passphrase: str) -> None:
    import win32cred
    win32cred.CredWrite({
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": _target(),
        "UserName": "DeskIT keyboard release",
        "CredentialBlob": passphrase,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        "Comment": "DeskIT: the passphrase of the phone keyboard's release keystore "
                   "(DeskIT-keys). Do not delete it: without it no update of the "
                   "keyboard can be signed.",
    }, 0)


def _delete_pass() -> None:
    import win32cred
    try:
        win32cred.CredDelete(TargetName=_target(), Type=win32cred.CRED_TYPE_GENERIC)
    except Exception:                                  # noqa: BLE001
        pass


def _need_pass() -> str:
    p = _read_pass()
    if not p:
        raise Refused(f"no passphrase in {_target()}: run --new once, or --restore "
                      f"from a backup")
    return p


# ------------------------------------------------------------ the files

def _in_a_checkout(folder: Path) -> Path | None:
    """The git work tree `folder` would be inside, or None."""
    for p in (folder.resolve(), *folder.resolve().parents):
        if (p / ".git").exists():
            return p
    return None


def _store(key_dir: Path) -> Path:
    return key_dir / STORE_NAME


def pinned() -> str:
    """The pinned certificate's SHA-256, or "" while none is pinned."""
    try:
        text = CERT_FILE.read_text("ascii").strip().lower()
    except OSError:
        return ""
    return text if _HEX64.match(text) else ""


def _fingerprint(store: Path, passphrase: str) -> str:
    """The SHA-256 of the key's certificate, DER — what apksigner prints as
    the signer's certificate digest."""
    with tempfile.TemporaryDirectory() as d:
        der = Path(d) / "cert.der"
        _keytool("-exportcert", "-keystore", str(store), "-storetype", "PKCS12",
                 "-alias", ALIAS, "-storepass:env", _ENV, "-file", str(der),
                 passphrase=passphrase)
        return hashlib.sha256(der.read_bytes()).hexdigest()


def _write_pinned(digest: str) -> None:
    CERT_FILE.write_bytes((digest + "\n").encode("ascii"))


# ------------------------------------------------------------- gh

def _gh(*args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(["gh", *args, "--repo", GH_REPO], capture_output=True, text=True,
                          input=stdin, creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise Refused(f"gh {' '.join(args[:2])} failed: "
                      f"{(proc.stderr or proc.stdout).strip()[:300]}")
    return proc.stdout


def _secret_names() -> set[str]:
    import json
    return {str(s.get("name")) for s in json.loads(_gh("secret", "list", "--json", "name"))}


# ------------------------------------------------------------- the verbs

def new(key_dir: Path) -> int:
    _not_under_the_suite("--new")
    store = _store(key_dir)
    if pinned():
        raise Refused(f"{CERT_FILE.relative_to(REPO)} already pins a key: a second key "
                      f"strands every phone that has the first. --restore it from a "
                      f"backup instead")
    if store.exists():
        raise Refused(f"{store} already exists")
    if _read_pass() is not None:
        raise Refused(f"{_target()} already holds a passphrase")
    inside = _in_a_checkout(key_dir)
    if inside:
        raise Refused(f"{key_dir} is inside the git checkout {inside}: the keystore "
                      f"must live outside every checkout")
    if SECRET_STORE in _secret_names():
        raise Refused(f"GitHub already holds {SECRET_STORE}: a key was handed over "
                      f"before. --restore it from its backup instead of making another")
    _java_home()
    passphrase = secrets.token_urlsafe(32)
    _write_pass(passphrase)
    if _read_pass() != passphrase:
        _delete_pass()
        raise Refused("the passphrase did not read back from Credential Manager the same")
    key_dir.mkdir(parents=True, exist_ok=True)
    try:
        _keytool("-genkeypair", "-keystore", str(store), "-storetype", "PKCS12",
                 "-alias", ALIAS, "-keyalg", "RSA", "-keysize", "4096",
                 "-validity", str(VALIDITY_DAYS), "-dname", DNAME,
                 "-storepass:env", _ENV, "-keypass:env", _ENV, passphrase=passphrase)
        digest = _fingerprint(store, passphrase)
    except Refused:
        if store.exists():
            store.unlink()
        _delete_pass()
        raise
    del passphrase
    _write_pinned(digest)
    print(f"the keystore is {store}")
    print(f"its passphrase is in Credential Manager as {_target()}")
    print(f"the certificate's SHA-256 is {digest}, pinned in "
          f"{CERT_FILE.relative_to(REPO)}: commit it")
    set_secrets(key_dir)
    print("make the two backups: python dev\\keyboard_key.py --backup <folder>")
    return 0


def set_secrets(key_dir: Path) -> int:
    _not_under_the_suite("--secrets")
    store = _store(key_dir)
    if not store.exists():
        raise Refused(f"no keystore at {store}")
    passphrase = _need_pass()
    digest = _fingerprint(store, passphrase)           # it opens, before GitHub gets it
    if pinned() and digest != pinned():
        raise Refused("the keystore is not the key android/release-cert.sha256 pins")
    _gh("secret", "set", SECRET_STORE, stdin=base64.b64encode(store.read_bytes()).decode("ascii"))
    _gh("secret", "set", SECRET_PASS, stdin=passphrase)
    del passphrase
    names = _secret_names()
    missing = [n for n in (SECRET_STORE, SECRET_PASS) if n not in names]
    if missing:
        raise Refused(f"GitHub does not list {', '.join(missing)} after setting it")
    print(f"GitHub holds {SECRET_STORE} and {SECRET_PASS} (names checked; a value "
          f"cannot be read back)")
    return 0


def check(key_dir: Path) -> int:
    store = _store(key_dir)
    bad = []
    passphrase = _read_pass()
    if not passphrase:
        bad.append(f"no passphrase in {_target()}")
    if not store.exists():
        bad.append(f"no keystore at {store}")
    digest = ""
    if not bad:
        digest = _fingerprint(store, passphrase)
        print(f"{store.name} opens; its certificate's SHA-256 is {digest}")
    del passphrase
    if not pinned():
        bad.append(f"{CERT_FILE.relative_to(REPO)} pins no key")
    elif digest and digest != pinned():
        bad.append("the keystore is not the key android/release-cert.sha256 pins")
    try:
        names = _secret_names()
        for n in (SECRET_STORE, SECRET_PASS):
            if n not in names:
                bad.append(f"GitHub has no secret {n}")
        if all(n in names for n in (SECRET_STORE, SECRET_PASS)):
            print(f"GitHub lists {SECRET_STORE} and {SECRET_PASS}")
    except Refused as e:
        bad.append(str(e))
    for b in bad:
        print(f"NOT OK: {b}")
    return 1 if bad else 0


def sign(key_dir: Path, unsigned: Path, out: Path) -> int:
    """A release APK built on this PC (the emulator's proof; a release is
    built and signed by release.yml): aligned, signed with the key, and
    refused unless its signer is the pinned certificate."""
    _not_under_the_suite("--sign")
    store = _store(key_dir)
    if not store.exists():
        raise Refused(f"no keystore at {store}")
    if not pinned():
        raise Refused(f"{CERT_FILE.relative_to(REPO)} pins no key")
    passphrase = _need_pass()
    bt = _build_tools()
    with tempfile.TemporaryDirectory() as d:
        aligned = Path(d) / "aligned.apk"
        _run([str(bt / "zipalign.exe"), "-f", "4", str(unsigned), str(aligned)], what="zipalign")
        _apksigner("sign", "--ks", str(store), "--ks-type", "PKCS12", "--ks-key-alias", ALIAS,
                   "--ks-pass", f"env:{_ENV}", "--key-pass", f"env:{_ENV}",
                   "--out", str(out), str(aligned), passphrase=passphrase)
    del passphrase
    certs = _apksigner("verify", "--print-certs", str(out))
    m = re.search(r"Signer #1 certificate SHA-256 digest: ([0-9a-f]{64})", certs)
    if not m or m.group(1) != pinned():
        out.unlink(missing_ok=True)
        raise Refused("the signed APK's certificate is not the pinned one")
    print(f"{out.name}: signed, certificate SHA-256 {m.group(1)}")
    return 0


def backup(key_dir: Path, folder: Path, passphrase_to: Path | None) -> int:
    _not_under_the_suite("--backup")
    store = _store(key_dir)
    if not store.exists():
        raise Refused(f"no keystore at {store}")
    inside = _in_a_checkout(folder)
    if inside:
        raise Refused(f"{folder} is inside the git checkout {inside}")
    passphrase = _need_pass()
    folder.mkdir(parents=True, exist_ok=True)
    copy = folder / STORE_NAME
    if copy.exists() and copy.read_bytes() != store.read_bytes():
        raise Refused(f"{copy} exists and is another file: not written over")
    shutil.copyfile(store, copy)
    if hashlib.sha256(copy.read_bytes()).digest() != hashlib.sha256(store.read_bytes()).digest():
        raise Refused(f"{copy} does not read back the same")
    target = passphrase_to or (folder / PASSPHRASE_FILE)
    if _in_a_checkout(target.parent):
        raise Refused(f"{target} is inside a git checkout")
    if target.exists() and target.read_text("utf-8").strip() != passphrase:
        raise Refused(f"{target} exists and holds something else: not written over")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(passphrase + "\n", "utf-8")
    digest = _fingerprint(copy, target.read_text("utf-8").strip())
    del passphrase
    if pinned() and digest != pinned():
        raise Refused("the backup is not the key android/release-cert.sha256 pins")
    (folder / "README.txt").write_text(
        "DeskIT phone keyboard: the release signing key\n\n"
        f"{STORE_NAME}: the keystore (PKCS#12, alias '{ALIAS}').\n"
        f"{target.name}: its passphrase"
        + ("" if target.parent == folder else f" (written to {target.parent})") + ".\n\n"
        f"Certificate SHA-256: {digest}\n\n"
        "Every keyboard update must be signed with this key, or phones refuse it.\n"
        "Keep this backup and the passphrase in two different places.\n"
        "To use it on a new PC: python dev\\keyboard_key.py --restore "
        f"<path to {STORE_NAME}> <path to the passphrase file>\n", "utf-8")
    print(f"wrote {copy}")
    print(f"wrote the passphrase to {target}")
    print(f"wrote {folder / 'README.txt'}")
    print("the copy opens with the passphrase and is the pinned key")
    return 0


def restore(key_dir: Path, keystore: Path, passphrase_file: Path) -> int:
    _not_under_the_suite("--restore")
    store = _store(key_dir)
    if store.exists():
        raise Refused(f"{store} already exists")
    if _read_pass() is not None:
        raise Refused(f"{_target()} already holds a passphrase")
    passphrase = passphrase_file.read_text("utf-8").strip()
    digest = _fingerprint(keystore, passphrase)
    if pinned() and digest != pinned():
        raise Refused("that keystore is not the key android/release-cert.sha256 pins")
    key_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(keystore, store)
    _write_pass(passphrase)
    if _read_pass() != passphrase:
        raise Refused("the passphrase did not read back from Credential Manager the same")
    del passphrase
    print(f"restored {store}; the passphrase is in Credential Manager as {_target()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--new", action="store_true")
    g.add_argument("--secrets", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--sign", nargs=2, metavar=("UNSIGNED", "OUT"))
    g.add_argument("--backup", metavar="FOLDER")
    g.add_argument("--restore", nargs=2, metavar=("KEYSTORE", "PASSPHRASE_FILE"))
    ap.add_argument("--passphrase-to", metavar="FILE")
    ap.add_argument("--dir", default=str(KEY_DIR), help="where the keystore lives")
    a = ap.parse_args(argv)
    key_dir = Path(a.dir)
    try:
        if a.new:
            return new(key_dir)
        if a.secrets:
            return set_secrets(key_dir)
        if a.check:
            return check(key_dir)
        if a.sign:
            return sign(key_dir, Path(a.sign[0]), Path(a.sign[1]))
        if a.backup:
            return backup(key_dir, Path(a.backup),
                          Path(a.passphrase_to) if a.passphrase_to else None)
        return restore(key_dir, Path(a.restore[0]), Path(a.restore[1]))
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
