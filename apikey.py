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

# Each provider has its own bucket of names and its own message; the
# LOOKUP below is shared, because the file format and the precedence are
# not provider-specific.
_GEMINI_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
_CEREBRAS_NAMES = ("CEREBRAS_API_KEY",)
_GROQ_NAMES = ("GROQ_API_KEY",)


def _from_environment(names: tuple[str, ...]) -> tuple[str, str] | None:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value, f"environment variable {name}"
    return None


def _from_env_file(names: tuple[str, ...]) -> tuple[str, str] | None:
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
        if name.strip().upper() in names:
            value = value.strip().strip('"').strip("'")
            if value:
                return value, f"{ENV_FILE.name} file"
    return None


def find_key(names: tuple[str, ...]) -> tuple[str | None, str]:
    """Returns (key, human-readable source). key is None when not found."""
    for lookup in (_from_environment, _from_env_file):
        found = lookup(names)
        if found is not None:
            return found
    return None, "not found"


def find_api_key() -> tuple[str | None, str]:
    return find_key(_GEMINI_NAMES)


def find_cerebras_key() -> tuple[str | None, str]:
    return find_key(_CEREBRAS_NAMES)


def find_groq_key() -> tuple[str | None, str]:
    return find_key(_GROQ_NAMES)


MISSING_KEY_MESSAGE = (
    "No Gemini API key found.\n"
    f"  Easiest fix: put this single line in {ENV_FILE}\n"
    "      GEMINI_API_KEY=your-key-here\n"
    "  (that file is read directly, so no terminal restart is ever needed)\n"
    "  Alternative: set the GEMINI_API_KEY environment variable."
)

CEREBRAS_MISSING_KEY_MESSAGE = (
    "No Cerebras API key found.\n"
    "  Free tier: 1M tokens/day, no credit card — console.cerebras.ai\n"
    f"  Then put this single line in {ENV_FILE}:\n"
    "      CEREBRAS_API_KEY=your-key-here\n"
    "  Until then the repair pass stays on the local model, exactly as "
    "classic runs it.")

GROQ_MISSING_KEY_MESSAGE = (
    "No Groq API key found.\n"
    "  Free tier, no credit card — console.groq.com\n"
    f"  Then put this single line in {ENV_FILE}:\n"
    "      GROQ_API_KEY=your-key-here\n"
    "  Until then the repair pass stays on the local model, exactly as "
    "classic runs it.")

