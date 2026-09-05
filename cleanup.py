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

# Boilerplate from the ivrit-ai fine-tune's training corpus, which is heavy
# on Knesset protocols. Whisper does not invent these out of nowhere — it
# appends them when the decoder runs past the end of real speech and keeps
# producing fluent text from its training distribution. Observed live
# 2026-08-12: a dictation about adding cities to an app ended with
# "אדוני היושב-ראש, חברי הכנסת", words that were never spoken.
#
# Every entry must be a phrase that is unmistakably parliamentary. Single
# common words ("הכנסת", "תודה רבה") are deliberately NOT here: they are
# things a person actually says, and stripping real speech is worse than
# leaving a stray hallucination in.
PARLIAMENTARY_BOILERPLATE = (
    "אדוני היושב ראש", "גברתי היושבת ראש", "כבוד היושב ראש",
    "אדוני היור", "גברתי היור", "אדוני היושב", "גברתי היושבת",
    "חברי הכנסת", "חבר הכנסת", "חברת הכנסת", "כל חברי הכנסת",
    "ישיבת הוועדה", "הישיבה נעולה", "הישיבה פתוחה",
    "אני מתכבד לפתוח את הישיבה", "תודה רבה אדוני היושב ראש",
    "בבקשה אדוני היושב ראש", "רשות הדיבור לחבר הכנסת",
)

# Tokens for phrase matching. Internal quotes are part of the token and
# then dropped, so the acronym היו"ר reduces to היור and matches however
# the model chose to punctuate it; "היושב-ראש" and "היושב ראש," reduce to
# the same two words either way.
_TOKEN = re.compile(r"[\w֐-׿]+(?:[\"'׳״][\w֐-׿]+)*")
_QUOTES = str.maketrans("", "", "\"'׳״")


def _word(token: str) -> str:
    return token.translate(_QUOTES).lower()


def _words(text: str) -> list[str]:
    return [_word(m.group(0)) for m in _TOKEN.finditer(text)]


def strip_trailing_boilerplate(
        text: str,
        phrases: tuple[str, ...] = PARLIAMENTARY_BOILERPLATE
) -> tuple[str, list[str]]:
    """Remove training-corpus boilerplate stuck to the END of a transcript.

    Returns (text, removed). Only the tail is touched, and only exact word
    sequences: the same phrase in the MIDDLE of a transcript is left alone,
    because there it is almost certainly something the user really said.
    Strips repeatedly, since the hallucination arrives as a chain
    ("אדוני היושב-ראש, חברי הכנסת" is two phrases, not one).
    """
    if not text or not text.strip():
        return text, []
    targets = [w for w in (_words(p) for p in phrases) if w]
    removed: list[str] = []
    while True:
        spans = [(m.start(), _word(m.group(0)))
                 for m in _TOKEN.finditer(text)]
        if not spans:
            break
        tail = [w for _, w in spans]
        # Longest match wins, so "תודה רבה אדוני היושב ראש" beats the
        # "אדוני היושב ראש" that sits inside it.
        best = max((t for t in targets
                    if len(t) <= len(tail) and tail[-len(t):] == t),
                   key=len, default=None)
        if best is None:
            break
        cut = spans[-len(best)][0]
        removed.insert(0, text[cut:].strip())
        text = text[:cut].rstrip().rstrip(",-–—").rstrip()
    return text, removed


def _filler_pattern(fillers: tuple[str, ...]) -> re.Pattern:
    # Match a filler only as a WHOLE token, optionally trailed by a comma,
    # so "אמא" (mother) is never mistaken for the filler "אמ".
    alts = "|".join(sorted((re.escape(f) for f in fillers),
                           key=len, reverse=True))
    return re.compile(rf"(?<![\w֐-׿])(?:{alts}),?"
                      rf"(?![\w֐-׿])", re.IGNORECASE)


def strip_fillers(text: str, fillers: tuple[str, ...] = DEFAULT_FILLERS) -> str:
    return _filler_pattern(fillers).sub(" ", text)


# A vocalised hesitation ("אהhhh...") has no phonetic structure, so Whisper
# has nothing correct to write for it — and once the decoder emits one ה,
# each ה makes the next more likely and it loops. Observed live 2026-08-13,
# three times, runs of up to 222 ה characters. The decoder-level guards
# don't catch it because they watch for SILENCE, and this is a sound.
_CHAR_RUN = re.compile(r"([א-ת])\1{3,}|([A-Za-z])\2{5,}")


def collapse_char_runs(text: str) -> str:
    """No word repeats one letter this many times in a row, so any such
    run is a decoder loop. Collapsed to a double, which turns 'אהההה…' into
    'אהה' — a filler strip_fillers() already knows how to drop.

    Two thresholds, because the scripts are not equally safe. Four is
    enough for Hebrew. Latin needs six: 'www' in a dictated URL must
    survive, and so must 'brrr'. Latin was excluded altogether until
    2026-09-05, when a 73-character 'Xxxxx…' run walked straight through
    into a dictation — English is not a foreign language on this
    microphone, and the decoder loops in it too.
    """
    return _CHAR_RUN.sub(lambda m: (m.group(1) or m.group(2)) * 2, text)


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
    out = collapse_char_runs(text)   # before fillers: 'אהההה…' -> 'אהה'
    out = strip_fillers(out, fillers)
    if collapse:
        out = collapse_repeats(out)
    out = tidy_spacing(out)
    # Never hand back an empty string for input that had real content —
    # better a messy transcript than a silently dropped one.
    return out if out.strip() else text.strip()
