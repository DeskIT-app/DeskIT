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
import threading
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

_LATIN = re.compile(r"[A-Za-z0-9]")


def family(heard: str, meant: str) -> str:
    """The A/B split of the module docstring, decided from one pair.

    "term" (family A) when either side carries Latin or digits — an
    unknown name, a flag, a tool. "context" (family B) when both sides
    are pure Hebrew: the heard form is a legitimate word, so only a
    reading of the sentence around it may ever act on it. Lives here,
    not in study.py, because the hotword list below needs the same
    answer and study.py imports this module.
    """
    return ("term" if _LATIN.search(meant or "") or _LATIN.search(heard or "")
            else "context")


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


def heard_by_decoder(pairs: list[tuple[str, str]],
                     raw: str) -> list[tuple[str, str]]:
    """Keep only the pairs whose heard side the DECODER actually produced.

    A correction is diffed against the text on screen, and that text has
    already been through apply() and polish. Where they rewrote something,
    the diff of screen-vs-fix describes THEIR edit, not a mishearing — and
    learning it files the app's own output as something Whisper got wrong.

    Observed live on 2026-08-28. "commit" was decoded correctly; a bad
    learned rule rewrote it to "make it"; the user fixed the screen back to
    "commit"; the diff produced (make -> commit) and the app learned it. One
    more press and every "make" would have become "commit". The heard side,
    "make", is nowhere in the decoder's transcript — which is exactly the
    tell, and exactly what this drops.

    An empty `raw` keeps everything: no transcript is no evidence either way,
    and this must never be the reason a real correction is silently lost.
    """
    raw_words = {w.lower() for w in words(raw)}
    if not raw_words:
        return list(pairs)
    return [(h, m) for h, m in pairs
            if all(w.lower() in raw_words for w in words(h))]


class Vocab:
    """The learned store. Safe to read from any thread; writes go through
    save(). Since the study engine (study.py) arrived there are TWO
    writer threads — the correction worker and the study thread — so the
    mutators and save() take a lock. Reads stay lock-free on purpose:
    they run on the hot path (hotwords() inside every transcription) and
    they only ever sort copies of the list.
    """

    def __init__(self, path: Path, seed_terms: tuple[str, ...] = (),
                 max_terms: int = 40, replace_after_hits: int = 2,
                 auto_after: int = 2, max_auto_terms: int = 12,
                 hebrew_after_hits: int = 3):
        self.path = path
        self.seed_terms = tuple(t.strip() for t in seed_terms if t.strip())
        self.max_terms = max_terms
        self.replace_after_hits = replace_after_hits
        # How many corrections a HEBREW pair needs before its corrected
        # form is fed to the decoder as a hotword. See _ranked.
        self.hebrew_after_hits = hebrew_after_hits
        # Machine evidence (study.py). Stricter than the human threshold on
        # purpose: a human correction is a person saying "this was wrong",
        # a study pair is a model's inference. auto_after counts DIFFERENT
        # recordings, and max_auto_terms keeps machine terms from crowding
        # the human ones out of the hotword budget.
        self.auto_after = auto_after
        self.max_auto_terms = max_auto_terms
        self.corrections: list[dict] = []
        self._write_lock = threading.RLock()
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
        with self._write_lock:
            try:
                self.path.write_text(json.dumps(
                    {"version": 1, "corrections": self.corrections},
                    ensure_ascii=False, indent=2), "utf-8")
            except OSError as e:
                log.warning("could not write %s: %s", self.path.name, e)

    # ---- learning ----

    def learn(self, heard: str, meant: str) -> dict:
        """Record one correction, or bump the one already there."""
        with self._write_lock:
            return self._learn(heard, meant)

    def _learn(self, heard: str, meant: str) -> dict:
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

    # ---- the hand doors: the Words list on the desk (2026-09-21) ----
    #
    # A person can now type a pair in, change one, or take one out,
    # rather than only teaching by correcting a dictation. The owner's
    # case: "the transcriber writes the same wrong thing every time and
    # the app never proposes it — let me add it myself". Each door
    # SAVES, because the desk's request is the whole transaction.

    def learn_by_hand(self, heard: str, meant: str) -> dict:
        """A pair typed on purpose counts as `replace_after_hits`
        corrections at once: both sides were spelled out by a person, so
        the two-strikes rule that protects against a slip in the edit
        box has nothing to protect. An existing pair keeps its hits if
        they are already higher, and takes the new meant form."""
        heard, meant = heard.strip(), meant.strip()
        if not heard or not meant:
            raise ValueError("both words are needed")
        if heard.lower() == meant.lower():
            raise ValueError("the two words are the same")
        with self._write_lock:
            entry = self._learn(heard, meant)
            # _learn bumped an existing pair by one (or made one at 1);
            # a hand-typed pair stands at the replace threshold at least.
            entry["hits"] = max(int(entry.get("hits", 1)),
                                self.replace_after_hits)
            self.save()
            return entry

    def forget(self, heard: str) -> bool:
        """Take one pair out. True if there was one. The next sync turns
        the absence into a tombstone (sync.vocab_rows), so the word goes
        from the account's other copies too."""
        key = heard.strip().lower()
        with self._write_lock:
            kept = [c for c in self.corrections
                    if str(c.get("heard", "")).strip().lower() != key]
            if len(kept) == len(self.corrections):
                return False
            self.corrections = kept
            self.save()
            return True

    def edit(self, heard: str, new_heard: str, new_meant: str) -> dict:
        """Change a pair in place. The heard form is the key, so a
        changed heard form is the old row taken out and a new one put
        in with the old row's hits — a correction he has made three
        times is still one he has made three times."""
        new_heard, new_meant = new_heard.strip(), new_meant.strip()
        if not new_heard or not new_meant:
            raise ValueError("both words are needed")
        if new_heard.lower() == new_meant.lower():
            raise ValueError("the two words are the same")
        key = heard.strip().lower()
        with self._write_lock:
            old = next((c for c in self.corrections
                        if str(c.get("heard", "")).strip().lower() == key),
                       None)
            if old is None:
                raise KeyError(heard)
            hits = max(int(old.get("hits", 1)), self.replace_after_hits)
            if new_heard.lower() != key:
                self.corrections = [c for c in self.corrections if c is not old]
                dup = next((c for c in self.corrections
                            if str(c.get("heard", "")).strip().lower()
                            == new_heard.lower()), None)
                if dup is not None:
                    old = dup
                    hits = max(hits, int(dup.get("hits", 1)))
                else:
                    old = {"heard": new_heard, "meant": new_meant, "hits": 1,
                           "last": ""}
                    self.corrections.append(old)
            old["heard"] = new_heard
            old["meant"] = new_meant
            old["hits"] = hits
            old["last"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.save()
            return old

    def find(self, heard: str) -> dict | None:
        key = heard.strip().lower()
        return next((c for c in self.corrections
                     if str(c.get("heard", "")).strip().lower() == key),
                    None)

    def learn_from_edit(self, raw: str, fixed: str,
                        heard_in: str | None = None
                        ) -> list[tuple[str, str]]:
        """Diff an edit and learn every substitution in it. Returns the
        pairs actually learned, for the log line.

        `raw` here is the text the edit was made against — on the human
        path that is what was on SCREEN, which apply() and polish may have
        already rewritten. Pass the decoder's own transcript as `heard_in`
        and anything those two invented is dropped before it is learned;
        see heard_by_decoder for what that costs when it is left off.
        """
        pairs = diff_corrections(raw, fixed)
        if heard_in is not None:
            pairs = heard_by_decoder(pairs, heard_in)
        for heard, meant in pairs:
            self.learn(heard, meant)
        if pairs:
            self.save()
        return pairs

    def learn_auto(self, heard: str, meant: str, source: str,
                   glossary_only: bool = False) -> dict | None:
        """Record machine evidence for one (heard, meant) pair — study.py.

        Three rules keep this weaker than a human correction, by design:

        - It can NEVER grant replace rights. apply() gates on the human
          `hits` counter, and nothing here touches it — an auto entry
          carries hits=0 until a human correction upgrades it.
        - The same recording never counts twice. Evidence is one
          `auto_hits` bump per distinct `source` (the recording's stem),
          so re-studying a clip after an engine change is not "the model
          said so again".
        - `glossary_only` entries (family B: Hebrew swapped for Hebrew)
          never become hotwords — prompting Whisper with common real
          words makes it emit them unbidden. They feed polish.py's
          glossary, where the sentence around them gates the repair.

        Returns the entry, or None when the pair teaches nothing.
        """
        heard, meant = heard.strip(), meant.strip()
        if not heard or not meant or heard.lower() == meant.lower():
            return None
        with self._write_lock:
            return self._learn_auto(heard, meant, source, glossary_only)

    def _learn_auto(self, heard: str, meant: str, source: str,
                    glossary_only: bool) -> dict:
        key = heard.lower()
        entry = next((c for c in self.corrections
                      if c.get("heard", "").strip().lower() == key), None)
        if entry is None:
            entry = {"heard": heard, "meant": meant, "hits": 0,
                     "last": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "auto_hits": 0, "auto_srcs": [],
                     "glossary_only": bool(glossary_only)}
            self.corrections.append(entry)
        srcs = entry.setdefault("auto_srcs", [])
        if source in srcs:
            return entry                  # this recording already testified
        srcs.append(source)
        del srcs[:-8]                     # the count matters, not the list
        entry["auto_hits"] = int(entry.get("auto_hits", 0)) + 1
        entry["last"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if int(entry.get("hits", 1)) == 0:
            # Auto-only entry: the newest inference wins, like learn().
            # A HUMAN entry's meant is never touched from here.
            entry["meant"] = meant
            entry["glossary_only"] = bool(glossary_only)
        return entry

    # ---- using what was learned ----

    def _ranked(self) -> list[str]:
        """Corrected forms, most worth spending prompt budget on first.

        Ranked by hits then recency: a name you have corrected four times is
        one you say often, and it earns its slot ahead of a one-off.
        """
        # A human correction earns a hotword slot at once ONLY when it is
        # a term — Latin or digits on either side, family A. A Hebrew word
        # swapped for a Hebrew word (family B) is a real word the owner
        # says, and a prompt made of real words is how the decoder comes
        # to emit them unbidden. Measured 2026-09-02: nine one-hit Hebrew
        # phrases at the tail of the prompt ("יש לי ריפו גיטאהאב אתה
        # שואל הרצץ מיליון באן יאללה דרוס ...") made a 2.8 s clip of five
        # words come out as 29, the extra 24 stamped into its last 140 ms
        # at p 0.04-0.58; the same clip decoded cleanly with the Latin
        # terms alone, and again with the list as it stood before the
        # last two Hebrew pairs were learned. A Hebrew pair still reaches
        # the prompt once it has been corrected `hebrew_after_hits` times
        # — that many corrections is a name, not a word — and it feeds
        # apply() and the polish glossary regardless, which is where a
        # context confusion belongs. study.py drew this line for machine
        # pairs a week earlier (glossary_only); this closes it for human
        # ones.
        # The gate asks about the MEANT form, not family(). family() is
        # the A/B split for whether a pair may be SUBSTITUTED, and it says
        # "term" when EITHER side carries Latin — right for that question,
        # wrong for this one. What lands in the prompt is `meant` and only
        # `meant`, so a pair whose meant form is ordinary Hebrew is
        # ordinary Hebrew in the prompt no matter what was heard. Found
        # 2026-09-05: 'Shush' -> 'שש' and '80 90 000' -> '80 אלף' had both
        # walked in at one hit and were sitting in the live string, which
        # is precisely the ingredient of the 2026-09-02 incident this gate
        # was built to keep out.
        human = sorted((c for c in self.corrections
                        if int(c.get("hits", 1)) > 0
                        and (_LATIN.search(str(c.get("meant", "")))
                             or int(c.get("hits", 1))
                             >= self.hebrew_after_hits)),
                       key=lambda c: (int(c.get("hits", 1)),
                                      str(c.get("last", ""))),
                       reverse=True)
        # Machine entries rank AFTER every human one, only once auto_after
        # different recordings agree, never when glossary_only, and capped
        # at max_auto_terms so they cannot crowd the humans out.
        auto = sorted((c for c in self.corrections
                       if int(c.get("hits", 1)) == 0
                       and int(c.get("auto_hits", 0)) >= self.auto_after
                       and not c.get("glossary_only")),
                      key=lambda c: (int(c.get("auto_hits", 0)),
                                     str(c.get("last", ""))),
                      reverse=True)[:max(0, self.max_auto_terms)]
        out: list[str] = []
        seen: set[str] = set()
        # Seeds first and unconditionally: they are the user's own stack,
        # written by hand in config.toml, and should never be crowded out by
        # whatever was corrected most recently.
        for term in (self.seed_terms
                     + tuple(c["meant"] for c in human)
                     + tuple(c["meant"] for c in auto)):
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
        human = sorted((c for c in self.corrections
                        if int(c.get("hits", 1)) > 0),
                       key=lambda c: (int(c.get("hits", 1)),
                                      str(c.get("last", ""))),
                       reverse=True)
        # Machine pairs follow the human ones — BOTH families: the
        # glossary is read by a model that sees the sentence, which is
        # exactly the gate a context-family pair needs.
        auto = sorted((c for c in self.corrections
                       if int(c.get("hits", 1)) == 0
                       and int(c.get("auto_hits", 0)) >= self.auto_after),
                      key=lambda c: (int(c.get("auto_hits", 0)),
                                     str(c.get("last", ""))),
                      reverse=True)
        return [(c.get("heard", ""), c["meant"])
                for c in (human + auto)[:limit] if c.get("heard")]

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
