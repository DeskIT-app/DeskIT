"""The one module that holds a secret in a variable: API keys and tokens.

Until 2026-09-17 the two cloud keys sat in a plaintext ``.env`` beside the
code and the phone's bearer token in ``server_token.txt`` beside it too.
Fine for one person's checkout; not for a program other people install,
where a key beside the code is a key in every backup, every "send me your
folder" and every screenshot of Explorer. DISTRIBUTION_PLAN.md chapter 3.6
and decisions D3 and D12 hold the argument; this module is what they ask
for, under a different file name — a module called ``secrets.py`` would
shadow the standard library's ``secrets`` (``token_urlsafe``) for the
whole app and for eleven files in the venv.

Two backends, chosen by NAME, never by the caller:

Windows Credential Manager (``win32cred``) — the two API keys.
    Generic credentials ``DeskIT/groq`` and ``DeskIT/gemini``, persisted
    for this Windows account. A person can SEE them and DELETE them in
    Control Panel > Credential Manager > Windows Credentials, which is
    part of the proof that the app keeps no copy anywhere else (D12).
    The store caps a value at ~1280 characters, plenty for a key.

DPAPI files (``win32crypt.CryptProtectData``) — everything bigger.
    ``DATA_DIR\\secrets\\<name>.bin``, user scope, ``UI_FORBIDDEN``: only
    this Windows account on this machine can open the blob, and no
    prompt can ever appear from a windowless process. The phone token
    lives here now; a Supabase session, the phone TLS key and per-phone
    tokens will (chapters 8 and 12).

Lookup order for the two keys (``find_key``): Credential Manager, then an
environment variable under the app's own prefix (``DESKIT_GROQ_API_KEY``,
``DESKIT_GEMINI_API_KEY``), then — ONLY in a portable/developer copy —
the old bare names (``GROQ_API_KEY``, ``GEMINI_API_KEY``) in the
environment and the ``.env`` beside ``main.py``. An installed copy reads
nothing but its own prefix, so a stranger's shell variables never leak
into it. The ``GOOGLE_API_KEY`` alias that quietly borrowed a gcloud key
is gone everywhere, and so is ``CEREBRAS_API_KEY`` (their free tier
ended; D3, D15).

Rules: a value is returned to the caller and forgotten — never logged,
never cached past the call, never written to any other file. What IS
logged is where a key came from (``source``), which names a store, not
a value.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import paths

log = logging.getLogger("app")

#: Names kept in Windows Credential Manager: short, shown to the person.
CRED_NAMES: tuple[str, ...] = ("groq", "gemini")

#: Names kept as DPAPI files under DATA_DIR\secrets\: blobs and tokens.
FILE_NAMES: tuple[str, ...] = ("phone_token", "hook_token",
                               "supabase_session", "phone_key", "phone_tokens",
                               "account_key")

#: The Credential Manager target is ``<prefix>/<name>``. The test hatch
#: (DESKIT_HOME) gets its own prefix so a suite can never overwrite the
#: person's real key — a stray ``DeskIT.test/groq`` entry is harmless and
#: visible, a lost ``DeskIT/groq`` is neither.
TARGET_PREFIX: str = "DeskIT.test" if paths._HOME_OVERRIDE else "DeskIT"

#: Environment variable per key name — the app's own prefix only.
ENV_VARS: dict[str, str] = {name: f"DESKIT_{name.upper()}_API_KEY"
                            for name in CRED_NAMES}

#: The bare names a developer's shell or .env has always used; honoured
#: only when paths.PORTABLE (D3, D4), after the prefixed name.
LEGACY_ENV_VARS: dict[str, str] = {name: f"{name.upper()}_API_KEY"
                                   for name in CRED_NAMES}

#: The developer's key file. Read only when paths.PORTABLE: an installed
#: copy has no such file and must never grow one.
ENV_FILE_NAME = ".env"
ENV_FILE: Path = paths.APP_DIR / ENV_FILE_NAME

CRYPTPROTECT_UI_FORBIDDEN = 0x1
_ERROR_NOT_FOUND = 1168


class SecretError(RuntimeError):
    """A backend refused: no Credential Manager, a blob from another account."""


def _check(name: str) -> str:
    if name in CRED_NAMES:
        return "cred"
    if name in FILE_NAMES:
        return "file"
    raise KeyError(f"no such secret name: {name!r} (known: "
                   f"{', '.join(CRED_NAMES + FILE_NAMES)})")


# ------------------------------------------------- Windows Credential Manager

def target(name: str) -> str:
    return f"{TARGET_PREFIX}/{name}"


#: The host each key travels to, for the sentence beside the field.
KEY_HOSTS: dict[str, str] = {"groq": "api.groq.com",
                             "gemini": "generativelanguage.googleapis.com"}


def storage_sentence(name: str) -> str:
    """The fixed wording next to every key field (plan arch-B section 4,
    D12): the Privacy tab's block draws it, the guide quotes it from
    docs/strings/keys.json, and a test holds the two equal.

    Until 2026-09-23 it said the key was "never sent to the developer",
    while the settings sync puts a sealed copy in the account's vault
    table on DeskIT's server (vault.export_keys, sb._sync_vault) — true
    of what the developer can READ, not of where it goes. It says both
    halves now: as it is, only to its provider; locked, to the account."""
    return (f"This key is stored in Windows Credential Manager on this PC "
            f"(Control Panel > Credential Manager > Windows Credentials > "
            f"{target(name)}). DeskIT sends it as it is only to {KEY_HOSTS[name]}. "
            f"While your settings sync to your account, a copy goes to your account "
            f"too, locked with a key only your own PCs hold. It is never written to "
            f"a file, a log or a report — see Settings > Privacy > EVERY CONNECTION "
            f"for every request.")


def _cred_read(name: str) -> str | None:
    import pywintypes
    import win32cred
    try:
        cred = win32cred.CredRead(TargetName=target(name),
                                  Type=win32cred.CRED_TYPE_GENERIC)
    except pywintypes.error as e:
        if e.winerror == _ERROR_NOT_FOUND:
            return None
        raise SecretError(f"Credential Manager refused to read "
                          f"{target(name)}: {e.strerror}") from e
    blob = cred.get("CredentialBlob") or b""
    # CredWrite from Python stores a str as UTF-16-LE; read it back the
    # same way, and tolerate a blob another tool wrote as UTF-8.
    try:
        value = bytes(blob).decode("utf-16-le")
    except UnicodeDecodeError:
        value = bytes(blob).decode("utf-8", "replace")
    value = value.strip("\x00").strip()
    return value or None


def _cred_write(name: str, value: str) -> None:
    import pywintypes
    import win32cred
    try:
        win32cred.CredWrite({
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": target(name),
            "UserName": "DeskIT",
            "CredentialBlob": value,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            "Comment": f"DeskIT: your {name.capitalize()} API key. Deleting "
                       f"this entry removes the key from DeskIT.",
        }, 0)
    except pywintypes.error as e:
        raise SecretError(f"Credential Manager refused to store "
                          f"{target(name)}: {e.strerror}") from e


def _cred_delete(name: str) -> bool:
    import pywintypes
    import win32cred
    try:
        win32cred.CredDelete(TargetName=target(name),
                             Type=win32cred.CRED_TYPE_GENERIC)
        return True
    except pywintypes.error as e:
        if e.winerror == _ERROR_NOT_FOUND:
            return False
        raise SecretError(f"Credential Manager refused to delete "
                          f"{target(name)}: {e.strerror}") from e


# ------------------------------------------------------------- DPAPI files

def blob_path(name: str) -> Path:
    return paths.SECRETS_DIR / f"{name}.bin"


def _file_read(name: str) -> str | None:
    p = blob_path(name)
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        return None
    if not raw:
        return None
    import pywintypes
    import win32crypt
    try:
        _desc, data = win32crypt.CryptUnprotectData(
            raw, None, None, None, CRYPTPROTECT_UI_FORBIDDEN)
    except pywintypes.error as e:
        # Another Windows account's blob, or a copied folder: unreadable
        # by design. Say so once; the caller treats it as absent.
        raise SecretError(f"{p.name} cannot be opened by this Windows "
                          f"account: {e.strerror}") from e
    value = bytes(data).decode("utf-8").strip()
    return value or None


def _file_write(name: str, value: str) -> None:
    import win32crypt
    blob = win32crypt.CryptProtectData(
        value.encode("utf-8"), f"DeskIT {name}", None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN)
    p = blob_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".bin.tmp")
    tmp.write_bytes(bytes(blob))
    os.replace(tmp, p)


def _file_delete(name: str) -> bool:
    p = blob_path(name)
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False


# ------------------------------------------------------------ the three ops

def get(name: str) -> str | None:
    """The stored value, or None. Raises SecretError only when a backend
    is present but refuses (a blob from another account, say)."""
    return _cred_read(name) if _check(name) == "cred" else _file_read(name)


def set(name: str, value: str) -> None:  # noqa: A001 — the plan's verb
    """Store ``value`` under ``name``; an empty value means delete."""
    value = (value or "").strip()
    if not value:
        delete(name)
        return
    if _check(name) == "cred":
        _cred_write(name, value)
    else:
        _file_write(name, value)


def delete(name: str) -> bool:
    """Remove it; True if something was there."""
    return _cred_delete(name) if _check(name) == "cred" else _file_delete(name)


def delete_all() -> list[str]:
    """Every secret this copy holds — for "Delete everything on this PC"
    and the uninstaller. Returns the names that were present."""
    gone = [name for name in CRED_NAMES + FILE_NAMES if delete(name)]
    try:
        paths.SECRETS_DIR.rmdir()          # only when empty
    except OSError:
        pass
    return gone


def present() -> dict[str, str]:
    """name -> where it is, for every stored secret; values never leave."""
    found: dict[str, str] = {}
    for name in CRED_NAMES:
        _value, source = find_key(name)
        if _value:
            found[name] = source
    for name in FILE_NAMES:
        if blob_path(name).is_file():
            found[name] = f"{blob_path(name).name} (DPAPI, this account only)"
    return found


def scrub(text: str) -> str:
    """``text`` with every value this store holds replaced by
    ``[redacted:<name>]`` — the redactor's belt and braces (plan 4.5).
    The comparison happens HERE so no value lands in a variable outside
    this module; a value shorter than eight characters is not matched
    (a stray "1234" in a log line is not a secret)."""
    if not text:
        return text
    out = str(text)
    for name in CRED_NAMES + FILE_NAMES:
        try:
            value = find_key(name)[0] if name in CRED_NAMES else get(name)
        except Exception:                                    # noqa: BLE001
            value = None
        if value and len(value) >= 8 and value in out:
            out = out.replace(value, f"[redacted:{name}]")
    return out


# ----------------------------------------------------- the key lookup order

def read_env_file(path: Path) -> dict[str, str]:
    """A .env's KEY=VALUE lines as {UPPER_NAME: value}: comments, blank
    lines, quotes and a UTF-8 BOM survive. Missing or unreadable -> {}.
    The one .env parser; --migrate's key import uses it too."""
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return {}
    found: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            found.setdefault(key.strip().upper(), value)
    return found


def env_file_in(folder: Path) -> Path:
    """Where an old checkout kept its keys — for --migrate."""
    return Path(folder) / ENV_FILE_NAME


def _from_env_file(name: str) -> str | None:
    """The developer's .env, prefixed name first, then the bare one."""
    if not paths.PORTABLE or not ENV_FILE.is_file():
        return None
    found = read_env_file(ENV_FILE)
    return found.get(ENV_VARS[name]) or found.get(LEGACY_ENV_VARS[name])


def find_key(name: str) -> tuple[str | None, str]:
    """(key, human-readable source) for ``groq`` / ``gemini``; the key is
    None when nothing holds one, and the source then says where it was
    looked for."""
    if name not in CRED_NAMES:
        raise KeyError(f"not an API key name: {name!r}")
    try:
        value = _cred_read(name)
    except (SecretError, ImportError) as e:
        log.warning("%s", e)
        value = None
    if value:
        return value, f"Windows Credential Manager ({target(name)})"
    for var in (ENV_VARS[name],) + ((LEGACY_ENV_VARS[name],) if paths.PORTABLE else ()):
        value = (os.environ.get(var) or "").strip()
        if value:
            return value, f"environment variable {var}"
    value = _from_env_file(name)
    if value:
        return value, f"{ENV_FILE.name} file (developer copy)"
    return None, "not found"


def missing_key_message(name: str) -> str:
    """One paragraph a log line or a card can show when a key is absent."""
    where = {"groq": "console.groq.com (free tier, no credit card)",
             "gemini": "aistudio.google.com"}[name]
    return (f"No {name.capitalize()} API key found.\n"
            f"  Get one at {where}, then store it with\n"
            f"      main.py --set-key {name}\n"
            f"  (it goes into Windows Credential Manager as {target(name)}; "
            f"Control Panel shows it and can delete it).\n"
            f"  Or set the environment variable {ENV_VARS[name]}."
            + (f"\n  A developer copy also reads {ENV_FILE.name} beside "
               f"main.py." if paths.PORTABLE else ""))


# ------------------------------------------------------------ the terminal

def cli_list(out=print) -> int:
    """``--keys``: what is stored and where — never a value."""
    found = present()
    if not found:
        out("No keys or tokens stored on this copy.")
    for name in CRED_NAMES + FILE_NAMES:
        if name in found:
            out(f"  {name:16} {found[name]}")
    for name in CRED_NAMES:
        if name not in found:
            out(f"  {name:16} — not set (main.py --set-key {name})")
    return 0


def cli_set(name: str, value: str | None = None, out=print) -> int:
    """``--set-key NAME``: prompt without echo unless a value was piped."""
    if name not in CRED_NAMES:
        out(f"--set-key takes one of: {', '.join(CRED_NAMES)}")
        return 2
    if value is None:
        import sys
        if sys.stdin is not None and not sys.stdin.isatty():
            value = sys.stdin.readline()
        else:
            import getpass
            value = getpass.getpass(f"Paste the {name} key (not shown): ")
    value = (value or "").strip()
    if not value:
        out("Nothing stored: the key was empty.")
        return 1
    try:
        set(name, value)
    except SecretError as e:
        out(str(e))
        return 1
    out(f"Stored in Windows Credential Manager as {target(name)}. The app "
        f"reads it there first; a .env line for it is no longer needed.")
    return 0


def cli_delete(name: str, out=print) -> int:
    """``--delete-key NAME``."""
    if name not in CRED_NAMES:
        out(f"--delete-key takes one of: {', '.join(CRED_NAMES)}")
        return 2
    try:
        gone = delete(name)
    except SecretError as e:
        out(str(e))
        return 1
    out(f"Removed {target(name)} from Windows Credential Manager."
        if gone else f"{target(name)} was not there.")
    return 0
