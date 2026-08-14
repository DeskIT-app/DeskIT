"""The names this machine keeps getting wrong, and what they should be.

Whisper does not mishear randomly. It mishears the words it was never
trained on — project names, tool names, the jargon of whatever you happen
to be building. Measured from this user's own transcripts.log on
2026-08-14, the errors fall into two families that need OPPOSITE handling:

  A. words the model has never heard      "Expo Go" -> "xpogo"
                                          "--branch" -> "Brinth"
                                          "Cowork" -> "בקו-ורק"
                                          "HebrewDictation" -> "Hebrew reduction"

  B. real Hebrew words swapped for other real Hebrew words
                                          מקלדת -> מקללת   (keyboard -> curses)
                                          סריקה -> סירקה
                                          קירור -> קירוב

Family A is a vocabulary problem and this module fixes it. Family B is a
CONTEXT problem — the heard form is a legitimate word, so no lookup table
can safely rewrite it and a blunt find-and-replace would corrupt real
speech. That family belongs to polish.py, which reads the sentence around
it. The split matters: applying this module's mechanism to family B is
exactly the bug that "deleting real speech is worse than the one being
fixed" (see cleanup.py) warns about.

Two mechanisms, in this order:

1. **Prevention — hotwords.** The corrected forms are fed to the decoder
   before it runs, so it never produces the garble in the first place.
   This is the one that actually matters.

2. **Repair — replacement.** A learned garble that slips through anyway is
   swapped for its correction, but only after `replace_after_hits`
   independent corrections of the same string (default 2). One correction
   could be a slip of the finger in the edit box; two is a pattern.

WHY HOTWORDS AND NOT initial_prompt — measured 2026-08-14, and the reason
this module exists at all. local_whisper.py sets
`condition_on_previous_text=False`, and under that setting faster-whisper
drops `initial_prompt` after the FIRST 30-second window: it goes into
`all_tokens`, and the end of each segment loop does
`prompt_reset_since = len(all_tokens)`. `hotwords` is re-injected per
window inside `get_prompt()` and bypasses that entirely. Probed by spying
on `WhisperModel.get_prompt` with 125 s of real speech:

    initial_prompt='MARKERWORD'   marker present in 1/5 decoder windows
    hotwords='MARKERWORD'         marker present in 6/6 decoder windows

The two coexist (the prompt becomes " HOTWORD INITWORD"), so the existing
initial_prompt is kept — it is what sets the Hebrew-with-English register,
and it is worth 10.8% -> 9.6% WER on short clips. Hotwords are what carry
the vocabulary past the 30-second mark, which is where the long dictations
that garble the worst actually live.

BUDGET: faster-whisper truncates the hotword string at `max_length // 2 - 1`
= **223 tokens** (verified against faster_whisper 1.2.1), mid-token if it
has to. Hebrew tokenises badly — several tokens per word — so the list is
capped by `max_terms` well below that, and over-prompting Whisper makes it
emit the prompted words unbidden. A long list is not a better list.

The store lives in vocab.json next to the app. It is derived from dictated
speech, so it is gitignored for the same reason transcripts.log is.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger("app")

# Word tokens for diffing. Mirrors cleanup.py's _TOKEN so the two agree on
# what a word is, plus Latin letters and the internal dot/dash that make
# "Expo Go", "pull-request" and "node.js" survive as units.
_WORD = re.compile(r"[\w֐-׿]+(?:[.\-'\"׳״][\w֐-׿]+)*")

# A correction longer than this is a rewrite, not a term. Learning it would
# teach the app to replace whole sentences, which is not what any of this
# is for.
MAX_SPAN_WORDS = 4

# Hebrew glues its one-letter prefixes onto the following word, so a garble
# is corrected in ONE form and then met in another: the user fixes "סירקה"
# to "סריקה", and the next transcript says "לסירקה". Without this the
# repair silently never fires on exactly the words it was taught.
# (cleanup.py hits the same wall from the other side, where a dangling
# prefix splits a repeated phrase.)
#
# Matching a prefix cannot run a term into its neighbour — the lookahead
# still demands a word boundary at the END, which is what keeps a learned
# "הר" out of the middle of "הרבה". The prefix is captured and put back, so
# "לסירקה" becomes "לסריקה" rather than losing its ל.
_PREFIX = "[ובהלכמש]"

# Below this, allowing a prefix is more dangerous than useful: a one-letter
# garble plus a one-letter prefix matches an enormous amount of ordinary
# Hebrew.
MIN_PREFIXABLE = 2

# Hard ceiling from faster_whisper's get_prompt(); see the module docstring.
HOTWORD_TOKEN_LIMIT = 223


def words(text: str) -> list[str]:
    return _WORD.findall(text or "")


# How much of the transcript must still be recognisable in what was grabbed
# off the screen before it is believed to be the same utterance. Below this,
# the user has moved on and the field holds something else entirely —
# learning from that diff would poison the vocabulary with garbage.
MIN_MATCH = 0.5


def _word_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _WORD.finditer(text)]


def locate(transcript: str, haystack: str) -> tuple[str, float]:
    """Find the user's corrected version of `transcript` inside `haystack`.

    `haystack` is whatever was on screen when they pressed the key — often
    a whole chat box holding several paragraphs, of which the last dictation
    is one. Returns (the aligned span, how well it matched).

    Character offsets rather than re-joined words, so the punctuation the
    user actually has survives into the stored ground truth. The span is
    widened by however much of the transcript hangs off each end of the
    alignment, so a correction to the very first or very last word is not
    the one thing this cuts off.

    KNOWN LIMIT, measured 2026-08-14. The widening assumes a correction has
    roughly the word count of what it replaces, which is true everywhere
    except at the very edges. A mis-hearing that is BOTH the last word of
    the dictation AND expands into more words ("xpogo" -> "Expo Go") has no
    matching word after it to anchor its end, so the span stops early and
    the pair is learned truncated ("xpogo" -> "Expo"). Mid-sentence — which
    is the ordinary shape, because these dictations are paragraphs — the
    trailing words anchor it and the pair is exact:

        "...השרת של xpogo כי הוא נכבה"   ->  learns  xpogo -> Expo Go   ✓
        "...תריץ את xpogo"                ->  learns  xpogo -> Expo     ✗

    Deliberately not "fixed" by widening more: extending the span past the
    end of the transcript pulls in the user's NEXT sentence, and a
    four-word replacement built out of it is a far worse thing to learn
    than a short one. The blast radius of the truncated pair is small —
    "Expo" is a perfectly good hotword, and replace_after_hits keeps a
    single odd pair from ever rewriting anything.
    """
    a_spans, b_spans = _word_spans(transcript), _word_spans(haystack)
    a = [transcript[s:e].lower() for s, e in a_spans]
    b = [haystack[s:e].lower() for s, e in b_spans]
    if not a or not b:
        return "", 0.0
    blocks = [m for m in difflib.SequenceMatcher(
        None, a, b, autojunk=False).get_matching_blocks() if m.size]
    if not blocks:
        return "", 0.0
    start = max(0, blocks[0].b - blocks[0].a)
    tail = len(a) - (blocks[-1].a + blocks[-1].size)
    end = min(len(b), blocks[-1].b + blocks[-1].size + tail)
    span = haystack[b_spans[start][0]:b_spans[end - 1][1]]
    ratio = difflib.SequenceMatcher(None, a, b[start:end],
                                    autojunk=False).ratio()
    return span, ratio


def diff_corrections(raw: str, fixed: str) -> list[tuple[str, str]]:
    """(heard, meant) pairs from a raw transcript and the user's edit of it.

    Only SUBSTITUTIONS are learned. A pure insertion means the model missed
    words entirely (usually a decoder loop ate them — see local_whisper's
    loop warning) and there is no misheard form to key on; a pure deletion
    means it invented something, which is the hallucination filter's job,
    not the vocabulary's. Neither teaches "when you hear X, write Y".

    Spans longer than MAX_SPAN_WORDS are dropped for the same reason: they
    are the user rewriting their sentence, not correcting a name.
    """
    a, b = words(raw), words(fixed)
    if not a or not b:
        return []
    out: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False).get_opcodes():
        if tag != "replace":
            continue
        if (i2 - i1) > MAX_SPAN_WORDS or (j2 - j1) > MAX_SPAN_WORDS:
            continue
        heard, meant = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if heard and meant and heard.lower() != meant.lower():
            out.append((heard, meant))
    return out


class Vocab:
    """The learned store. Safe to read from any thread; writes are rare
    (one per correction) and go through save()."""

    def __init__(self, path: Path, seed_terms: tuple[str, ...] = (),
                 max_terms: int = 40, replace_after_hits: int = 2):
        self.path = path
        self.seed_terms = tuple(t.strip() for t in seed_terms if t.strip())
        self.max_terms = max_terms
        self.replace_after_hits = replace_after_hits
        self.corrections: list[dict] = []
        self.load()

    # ---- persistence ----

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            return
        except Exception as e:
            # A corrupt store must never stop dictation — the app works
            # fine without any learned vocabulary, it just works worse.
            log.warning("could not read %s (%s) — starting with an empty "
                        "vocabulary", self.path.name, e)
            return
        found = data.get("corrections")
        if isinstance(found, list):
            self.corrections = [c for c in found
                                if isinstance(c, dict) and c.get("meant")]

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(
                {"version": 1, "corrections": self.corrections},
                ensure_ascii=False, indent=2), "utf-8")
        except OSError as e:
            log.warning("could not write %s: %s", self.path.name, e)

    # ---- learning ----

    def learn(self, heard: str, meant: str) -> dict:
        """Record one correction, or bump the one already there."""
        key = heard.strip().lower()
        for entry in self.corrections:
            if entry.get("heard", "").strip().lower() == key:
                entry["hits"] = int(entry.get("hits", 1)) + 1
                entry["meant"] = meant          # the newest wins a conflict
                entry["last"] = time.strftime("%Y-%m-%d %H:%M:%S")
                return entry
        entry = {"heard": heard.strip(), "meant": meant.strip(), "hits": 1,
                 "last": time.strftime("%Y-%m-%d %H:%M:%S")}
        self.corrections.append(entry)
        return entry

    def learn_from_edit(self, raw: str, fixed: str) -> list[tuple[str, str]]:
        """Diff an edit and learn every substitution in it. Returns the
        pairs actually learned, for the log line."""
        pairs = diff_corrections(raw, fixed)
        for heard, meant in pairs:
            self.learn(heard, meant)
        if pairs:
            self.save()
        return pairs

    # ---- using what was learned ----

    def _ranked(self) -> list[str]:
        """Corrected forms, most worth spending prompt budget on first.

        Ranked by hits then recency: a name you have corrected four times is
        one you say often, and it earns its slot ahead of a one-off.
        """
        ordered = sorted(self.corrections,
                         key=lambda c: (int(c.get("hits", 1)),
                                        str(c.get("last", ""))),
                         reverse=True)
        out: list[str] = []
        seen: set[str] = set()
        # Seeds first and unconditionally: they are the user's own stack,
        # written by hand in config.toml, and should never be crowded out by
        # whatever was corrected most recently.
        for term in self.seed_terms + tuple(c["meant"] for c in ordered):
            key = term.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(term.strip())
        return out

    def terms(self) -> list[str]:
        """The bounded, ranked term list. Separate from hotwords() because
        `max_terms` counts TERMS and "Expo Go" is one of them — counting the
        joined string's words instead reports a budget that is wrong for
        every multi-word entry."""
        return self._ranked()[:max(0, self.max_terms)]

    def hotwords(self) -> str:
        """The string handed to faster-whisper's `hotwords=`.

        Space-separated rather than comma-separated: this is fed to the
        decoder as ordinary prompt tokens, and a comma between every term
        spends budget on punctuation the model then has to explain to
        itself.
        """
        return " ".join(self.terms())

    def glossary(self, limit: int = 60) -> list[tuple[str, str]]:
        """(heard, meant) pairs for polish.py's prompt — the confusions
        worth telling a language model about."""
        ordered = sorted(self.corrections,
                         key=lambda c: (int(c.get("hits", 1)),
                                        str(c.get("last", ""))),
                         reverse=True)
        return [(c.get("heard", ""), c["meant"]) for c in ordered[:limit]
                if c.get("heard")]

    def known_garbles(self) -> set[str]:
        """Lowercased heard-forms, for deciding whether a transcript is
        worth sending to polish.py at all."""
        return {c.get("heard", "").strip().lower()
                for c in self.corrections if c.get("heard")}

    def apply(self, text: str) -> tuple[str, list[str]]:
        """Repair pass: swap learned garbles that survived the decoder.

        Deliberately gated behind `replace_after_hits`. This is the one
        mechanism here that can damage real speech — every entry is a string
        the model DID produce, so some of them are real words that happened
        to be wrong once. Requiring the same correction twice means a slip
        in the edit box cannot silently start rewriting a word the user
        really says.

        Whole-token matching only, so a learned "הר" never eats the middle
        of "הרבה".
        """
        if not text.strip():
            return text, []
        ready = [c for c in self.corrections
                 if int(c.get("hits", 1)) >= self.replace_after_hits
                 and c.get("heard")]
        if not ready:
            return text, []
        applied: list[str] = []
        # Longest first: a two-word garble must win over either of its words.
        for entry in sorted(ready, key=lambda c: -len(c["heard"])):
            heard, meant = entry["heard"], entry["meant"]
            prefix = (_PREFIX + "?") if len(heard) >= MIN_PREFIXABLE else ""
            pattern = re.compile(
                r"(?<![\w֐-׿])(" + prefix + r")" + re.escape(heard)
                + r"(?![\w֐-׿])", re.IGNORECASE)
            # A function, not a template: `meant` is user data and a literal
            # backslash or \1 in it would otherwise be read as a group
            # reference and corrupt the output.
            text, n = pattern.subn(lambda m: m.group(1) + meant, text)
            if n:
                applied.append(f"{heard} -> {meant}")
        return text, applied

    def __len__(self) -> int:
        return len(self.corrections)
