"""Where the Gemini API key comes from.

Environment variables are the documented path, but on this machine they are
fragile: Windows Terminal shares one process across all tabs and windows,
so a `setx` only reaches terminals opened after the whole app is restarted.
A key file in this folder removes that failure mode entirely — it works in
any shell, immediately.

Lookup order:
  1. GEMINI_API_KEY / GOOGLE_API_KEY in the environment
  2. a `.env` file next to this module (KEY=VALUE lines)
"""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ENV_FILE = APP_DIR / ".env"
_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


def _from_environment() -> tuple[str, str] | None:
    for name in _NAMES:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value, f"environment variable {name}"
    return None


def _from_env_file() -> tuple[str, str] | None:
    if not ENV_FILE.exists():
        return None
    try:
        lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip().upper() in _NAMES:
            value = value.strip().strip('"').strip("'")
            if value:
                return value, f"{ENV_FILE.name} file"
    return None


def find_api_key() -> tuple[str | None, str]:
    """Returns (key, human-readable source). key is None when not found."""
    for lookup in (_from_environment, _from_env_file):
        found = lookup()
        if found is not None:
            return found
    return None, "not found"


MISSING_KEY_MESSAGE = (
    "No Gemini API key found.\n"
    f"  Easiest fix: put this single line in {ENV_FILE}\n"
    "      GEMINI_API_KEY=your-key-here\n"
    "  (that file is read directly, so no terminal restart is ever needed)\n"
    "  Alternative: set the GEMINI_API_KEY environment variable."
)
