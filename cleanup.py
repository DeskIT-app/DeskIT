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


_REPEAT_TOKEN = re.compile(r"[\w֐-׿']+")
_REPEAT_GAP = re.compile(r"[ ,]+")
_HEBREW_LETTERS = re.compile(r"[א-ת]+")
# The one-letter prefixes a restart mid-word leaves behind ("מה ש מה
# שאנחנו"). None of them is a word on its own.
_PREFIX_LETTERS = frozenset("ושהבלכמ")
# The words a restart repeats and a sentence never doubles on purpose, so
# that a PAIR of them ("זה זה לא עובד", "the the") is still a stutter. Any
# other word needs three in a row. Left out on purpose, because doubling
# them is real speech: לא/כן/טוב/רגע ("לא לא", "כן כן"), יש ("יש! יש!"),
# עם ("עם עם ישראל"), הוא/היא/הם (the emphatic "הוא הוא"), מה ("מה מה?"),
# and in/on/for/that/had/is/so ("log in in", "turn it on on Monday", "use
# for for loops", "I know that that works", "so so").
_PAIR_STUTTERS = frozenset((
    "אני", "אתה", "את", "אנחנו", "אתם", "זה", "זאת", "של", "על", "אם",
    "כי", "גם", "רק", "אז", "אבל", "כאילו",
    "i", "the", "a", "an", "to", "and", "but", "it", "we", "you", "my",
    "of",
))


def _stutter_fragment(fragment: str, word: str) -> bool:
    """Is `fragment`, standing between two copies of a run that starts with
    `word`, the leftover of a restart rather than a word of its own?

    Only two things are: one Hebrew prefix letter, or the start of the
    repeated word itself ("אנ אני", "רוצ רוצה"). Never a Latin word, never a
    digit, never a whole Hebrew word — "one by one", "end to end", "2 x 2",
    "פנים אל פנים" and "הוא לא הוא" are phrases, and the first version of
    this function took anything of one or two characters and ate them all.
    """
    if not _HEBREW_LETTERS.fullmatch(fragment):
        return False
    if len(fragment) == 1 and fragment in _PREFIX_LETTERS:
        return True
    return len(fragment) < len(word) and word.startswith(fragment)


def _repeat_at(text: str, toks: list, i: int, n: int):
    """The span to delete when the n words at toks[i] are said again right
    after (keeping the FIRST copy), or None. toks is [(start, end, word)]."""
    def joined(a: int, b: int) -> bool:           # only spaces and commas
        return bool(_REPEAT_GAP.fullmatch(text[toks[a][1]:toks[b][0]]))

    def same_run(at: int) -> bool:
        if at + n > len(toks):
            return False
        for k in range(n):
            if toks[at + k][2].lower() != toks[i + k][2].lower():
                return False
            if k and not joined(at + k - 1, at + k):
                return False
        return True

    run = [toks[i + k][2] for k in range(n)]
    # A code, a PIN, a phone number: "4 4 7 1" and "1 1 2 2" are digits
    # said twice on purpose, never a restart.
    if any(ch.isdigit() for w in run for ch in w):
        return None
    if not all(joined(i + k, i + k + 1) for k in range(n - 1)):
        return None
    last = i + n - 1
    if last + 1 >= len(toks) or not joined(last, last + 1):
        return None
    if same_run(i + n):
        if n > 1:
            return toks[last][1], toks[i + 2 * n - 1][1]
        # One word said again. Count the whole row: a pair is a stutter
        # only for the words that never double on purpose ("לאט לאט" is
        # how Hebrew says "slowly"); three or more is a stutter or a
        # decoder loop whatever the word.
        j = i + 1
        while (j + 1 < len(toks) and toks[j + 1][2].lower() == run[0].lower()
               and joined(j, j + 1)):
            j += 1
        if j - i + 1 >= 3 or run[0].lower() in _PAIR_STUTTERS:
            return toks[last][1], toks[j][1]
        return None
    frag = i + n
    if (frag + 1 < len(toks) and joined(frag, frag + 1)
            and _stutter_fragment(toks[frag][2], run[0])
            and same_run(frag + 1)):
        return toks[last][1], toks[frag + n][1]
    return None


def collapse_repeats(text: str, max_phrase: int = 4) -> str:
    """Collapse an immediately repeated run of words.

    Covers the way people actually restart a sentence:
    "רק את מה ש רק את מה שאנחנו בנינו" -> "רק את מה שאנחנו בנינו".
    Longer phrases are tried first so the largest restart wins.

    A dangling fragment between the two copies is swallowed too, but only
    a real one (`_stutter_fragment`): a Hebrew prefix letter (ש, ה, ו, ב,
    ל, כ, מ), which a speaker who restarts mid-word leaves behind, or the
    start of the repeated word. Until 2026-09-23 any one- or two-character
    token qualified and every exact pair collapsed, so "one by one" came
    out "one", "end to end" "end", "4 4 7 1" "4 7 1", "לאט לאט" "לאט" and
    "פנים אל פנים" "פנים" — words he said, deleted before the repair pass
    or the sidecar could see them. Now a run with a digit in it is never
    touched, and a single word needs three in a row unless it is one of
    `_PAIR_STUTTERS`.
    """
    for n in range(max_phrase, 0, -1):
        toks = [(m.start(), m.end(), m.group(0))
                for m in _REPEAT_TOKEN.finditer(text)]
        i = 0
        while i + 2 * n <= len(toks):
            cut = _repeat_at(text, toks, i, n)
            if cut is None:
                i += 1
                continue
            # the same i is tried again: repeated restarts, "אני א אני אני"
            text = text[:cut[0]] + text[cut[1]:]
            toks = [(m.start(), m.end(), m.group(0))
                    for m in _REPEAT_TOKEN.finditer(text)]
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
