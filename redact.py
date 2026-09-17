"""The redactor: one pure function over every string that leaves the
person's PC in a problem report, a diagnose block or an export note.

DISTRIBUTION_PLAN.md 4.5, D8. Each pattern is replaced by a fixed
placeholder that NAMES the kind — ``[redacted:groq-key]`` — so the reader
still sees that a key was there, and never what it was. The last step
is belt and braces: whatever the secret store holds under a known name
is replaced too, even when it matches no pattern (``secretstore.scrub``
does that comparison inside the store, so the value never lands in a
variable here).

What the redactor deliberately does NOT touch: file paths carrying the
Windows user name. Whether a path is attached at all is the report
whitelist's decision (``problems.env``, chapter 7), not this module's.

Dictated text reaches this module only when the person ticked
"Transcript text" on a report; it is redacted like everything else,
because a key can be dictated.
"""
from __future__ import annotations

import re

#: (name, pattern) — the placeholder is ``[redacted:<name>]``. Order
#: matters only where one pattern could eat another's prefix: the phone
#: fragment and the bearer come first because they carry a token that
#: might also look like a key.
PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("phone-link", re.compile(r"#t=[0-9A-Za-z_-]+")),
    ("bearer", re.compile(r"\bBearer\s+[^\s\"']+")),
    ("gemini-key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("groq-key", re.compile(r"\bgsk_[0-9A-Za-z]{20,}")),
    ("openai-key", re.compile(r"\bsk-[0-9A-Za-z_-]{20,}")),
    ("supabase-key", re.compile(r"\bsb_(?:publishable|secret)_[0-9A-Za-z_-]{10,}")),
    ("jwt", re.compile(r"\beyJ[0-9A-Za-z_-]{20,}\.[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+")),
)


def placeholder(name: str) -> str:
    return f"[redacted:{name}]"


def redact(text: str, *, stored: bool = True) -> str:
    """``text`` with every key-shaped string replaced. ``stored=False``
    skips the secret-store comparison (a test with no store, say)."""
    if not text:
        return text
    out = str(text)
    for name, pattern in PATTERNS:
        out = pattern.sub(placeholder(name), out)
    if stored:
        try:
            import secretstore
            out = secretstore.scrub(out)
        except Exception:                                    # noqa: BLE001
            pass
    return out


def walk(value, *, stored: bool = True):
    """``redact`` applied to every string inside a dict/list/tuple, in
    place of the original structure (a new one is returned)."""
    if isinstance(value, str):
        return redact(value, stored=stored)
    if isinstance(value, dict):
        return {k: walk(v, stored=stored) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(walk(v, stored=stored) for v in value)
    return value


def looks_secret(text: str) -> bool:
    """Does the text carry anything the redactor would replace? For the
    tests that grep a whole data folder (lock 1)."""
    return redact(text, stored=False) != text


__all__ = ["PATTERNS", "placeholder", "redact", "walk", "looks_secret"]
