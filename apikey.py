"""Where the cloud keys come from — a thin shim over secretstore.py.

Every cloud client (translate.py, transcribers/gemini.py, visual_qa.py)
asks here with the environment-variable NAMES it always used
(``GROQ_API_KEY``, ``GEMINI_API_KEY``); this module maps them to the
secret store's names and the store does the looking: Windows Credential
Manager, then ``DESKIT_*`` in the environment, then — in a developer or
portable copy only — the ``.env`` beside main.py. secretstore.py's
docstring has the order and the reasons (D3).

Two names are no longer answered, on purpose: ``GOOGLE_API_KEY`` (an alias
that silently borrowed whatever gcloud key the shell had) and
``CEREBRAS_API_KEY`` (their free tier ended in 2026-08; the backend stays
in the code for whoever sets ``[polish] prefer = "cerebras"`` and gets the
"no key" message below).
"""
from __future__ import annotations

import secretstore

#: environment-variable name -> secret store name
_NAMES = {"GROQ_API_KEY": "groq", "GEMINI_API_KEY": "gemini"}

_GEMINI_NAMES = ("GEMINI_API_KEY",)
_GROQ_NAMES = ("GROQ_API_KEY",)


def find_key(names: tuple[str, ...]) -> tuple[str | None, str]:
    """Returns (key, human-readable source). key is None when not found.

    The first name the store knows wins; a name it does not know
    (``GOOGLE_API_KEY``, ``CEREBRAS_API_KEY``) is skipped, not looked up.
    """
    for name in names:
        store_name = _NAMES.get(name.upper())
        if store_name is not None:
            return secretstore.find_key(store_name)
    return None, "not found"


def find_api_key() -> tuple[str | None, str]:
    return secretstore.find_key("gemini")


def find_groq_key() -> tuple[str | None, str]:
    return secretstore.find_key("groq")


def find_cerebras_key() -> tuple[str | None, str]:
    """Always absent: this version does not read CEREBRAS_API_KEY."""
    return None, "not found"


def __getattr__(name: str):
    # The messages are built on demand so they name the current store
    # target and the copy's own options (a developer copy mentions .env).
    if name == "MISSING_KEY_MESSAGE":
        return secretstore.missing_key_message("gemini")
    if name == "GROQ_MISSING_KEY_MESSAGE":
        return secretstore.missing_key_message("groq")
    if name == "CEREBRAS_MISSING_KEY_MESSAGE":
        return ("No Cerebras key: this version does not read CEREBRAS_API_KEY "
                "any more (their free tier ended, 2026-08).\n"
                '  Set [polish] prefer = "groq" (free, console.groq.com) or '
                '"ollama" (local) instead.')
    raise AttributeError(name)
