"""Light local cleanup for raw Whisper output.

Gemini transcribes AND cleans in one call (its system prompt removes
fillers, resolves self-corrections, writes digits). Whisper only
transcribes, so switching to the local backend would otherwise regress
output quality on real dictation — which is full of "אה", "אמ" and
restarted sentences.

This is deliberately CONSERVATIVE. It only removes things that are not
words, and only collapses repetitions that are exact. Anything ambiguous
(most notably "כאילו", which is a real word as often as it is filler) is
left alone unless the user opts in via config.
"""
from __future__ import annotations

import re

# Pure hesitation noises — these are never meaningful words on their own.
DEFAULT_FILLERS = ("אה", "אהה", "אממ", "אמm", "המ", "המם", "אמ",
                   "אוו", "אוה", "eh", "ehm", "um", "uh", "umm")

_WORD_SEP = r"[\s,]"


def _filler_pattern(fillers: tuple[str, ...]) -> re.Pattern:
    # Match a filler only as a WHOLE token, optionally trailed by a comma,
    # so "אמא" (mother) is never mistaken for the filler "אמ".
    alts = "|".join(sorted((re.escape(f) for f in fillers),
                           key=len, reverse=True))
    return re.compile(rf"(?<![\w֐-׿])(?:{alts}),?"
                      rf"(?![\w֐-׿])", re.IGNORECASE)


def strip_fillers(text: str, fillers: tuple[str, ...] = DEFAULT_FILLERS) -> str:
    return _filler_pattern(fillers).sub(" ", text)


def collapse_repeats(text: str, max_phrase: int = 4) -> str:
    """Collapse an immediately repeated run of words.

    Covers the way people actually restart a sentence:
    "רק את מה ש רק את מה שאנחנו בנינו" -> "רק את מה שאנחנו בנינו".
    Longer phrases are tried first so the largest restart wins.

    A dangling one- or two-letter fragment between the two copies is
    swallowed too: Hebrew prefixes (ש, ה, ו, ב, ל, כ, מ) mean a speaker who
    restarts mid-word leaves the prefix behind, which would otherwise break
    the repetition into two non-adjacent runs.
    """
    for n in range(max_phrase, 0, -1):
        pattern = re.compile(
            r"(?<![\w֐-׿])"
            r"((?:[\w֐-׿']+[ ,]+){%d}?[\w֐-׿']+)"
            r"[ ,]+(?:[\w֐-׿']{1,2}[ ,]+)?"
            r"\1(?![\w֐-׿])" % (n - 1),
            re.IGNORECASE)
        prev = None
        while prev != text:               # repeated restarts: "אני אני אני"
            prev = text
            text = pattern.sub(r"\1", text)
    return text


def tidy_spacing(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?:;])", r"\1", text)
    text = re.sub(r"([,.!?:;]){2,}", r"\1", text)
    return text.strip(" ,")


def clean(text: str, fillers: tuple[str, ...] = DEFAULT_FILLERS,
          collapse: bool = True) -> str:
    """Full pass. Returns "" unchanged for empty input."""
    if not text or not text.strip():
        return ""
    out = strip_fillers(text, fillers)
    if collapse:
        out = collapse_repeats(out)
    out = tidy_spacing(out)
    # Never hand back an empty string for input that had real content —
    # better a messy transcript than a silently dropped one.
    return out if out.strip() else text.strip()
