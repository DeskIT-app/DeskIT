"""Move the project's secret key out of the user environment and into
Windows Credential Manager. Run it once, by hand:

    .venv\\Scripts\\python.exe dev\\move_supabase_secret.py

Why (audit 2026-09-23): DESKIT_SUPABASE_SECRET sat in HKCU\\Environment,
so every program the owner starts - a browser, an editor, any agent -
inherited the one key that can read every account's rows. In Credential
Manager it is read only by what asks for it by name (dev\\inbox.py's
CRED_TARGET).

What it does, in this order, and nothing else:
1. reads the variable from HKCU\\Environment (not from this process's own
   environment, which may be stale);
2. writes it to Credential Manager under inbox.CRED_TARGET;
3. reads it back and compares - only if the copy is identical does it
4. delete the variable from HKCU\\Environment and tell running programs
   that the environment changed (WM_SETTINGCHANGE).
It never prints the key, only its length. Programs already running keep
their copy of the old environment until they restart.
"""
from __future__ import annotations

import ctypes
import sys
import winreg
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import inbox  # noqa: E402

_user32 = ctypes.WinDLL("user32")     # private: never declare on windll
HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x001A
SMTO_ABORTIFHUNG = 0x0002


def _from_registry() -> str:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            value, _kind = winreg.QueryValueEx(key, inbox.SECRET_VAR)
        except FileNotFoundError:
            return ""
    return str(value or "").strip()


def main() -> int:
    value = _from_registry()
    if not value:
        if inbox.cred_secret():
            print(f"already moved: {inbox.SECRET_VAR} is not in your user "
                  f"environment and Credential Manager holds "
                  f"{inbox.CRED_TARGET}.")
            return 0
        print(f"nothing to move: {inbox.SECRET_VAR} is not in your user "
              f"environment, and Credential Manager has no "
              f"{inbox.CRED_TARGET} either.")
        return 1
    if not value.startswith("sb_secret_"):
        print(f"not moved: {inbox.SECRET_VAR} does not look like the "
              "project's secret key (sb_secret_...). Nothing was changed.")
        return 1

    import win32cred
    win32cred.CredWrite({
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": inbox.CRED_TARGET,
        "UserName": "deskit-owner",
        "CredentialBlob": value,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        "Comment": "DeskIT (owner only): the Supabase project's secret key, "
                   "read by dev\\inbox.py.",
    }, 0)
    if inbox.cred_secret() != value:
        print("not moved: the copy in Credential Manager did not read back "
              f"the same, so {inbox.SECRET_VAR} was left where it was.")
        return 1

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_SET_VALUE) as key:
        winreg.DeleteValue(key, inbox.SECRET_VAR)
    result = ctypes.c_size_t()
    _user32.SendMessageTimeoutW(
        ctypes.c_void_p(HWND_BROADCAST), WM_SETTINGCHANGE, 0,
        ctypes.c_wchar_p("Environment"), SMTO_ABORTIFHUNG, 2000,
        ctypes.byref(result))
    print(f"moved: the key ({len(value)} characters) is in Credential "
          f"Manager as {inbox.CRED_TARGET}, and {inbox.SECRET_VAR} is gone "
          "from your user environment. Programs you start from now on do "
          "not see it; ones already open keep their old copy until you "
          "close them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
