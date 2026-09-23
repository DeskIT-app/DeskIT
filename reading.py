"""Read this to me: a sentence on the screen, read aloud, kept as a pair.

corpus\\ holds 72 gold clips — 29.6 minutes of this voice with text the
owner has vouched for (2026-09-13). A LoRA fine-tune of the local model
on his own speech wants two to three hours of that, and dictation alone
gets there at a minute or two a day. This is the faster road: the
dashboard shows him one sentence at a time, he holds the dictation key
and reads it, and the recording is filed under the words on the card.

THE LABEL IS THE CARD, NOT THE TRANSCRIPT. That is the whole value of
reading over dictating: the text is known BEFORE the audio exists, so
the pair is right even where the model is wrong — and the clips where
the model is wrong are exactly the ones a fine-tune learns from. So
EVERY READING IS KEPT, the moment it is back, and the next sentence
comes up; the transcript is made only to notice that nothing came back
at all (a dead microphone, a key let go too soon), and is filed in the
sidecar with its match for a day when the pairs are sifted. It used to
be a verdict — every word as written kept on its own, anything else
put to him with the words that differed — and he asked the right
question (2026-09-13, late): "why do I need the transcript at all? I
said it, this is the text." He did not stumble; the model did, and
that is not his problem. A reading he knows he fumbled he takes back
with one press (forget), and the sentence comes up again.

WHERE THE SENTENCES COME FROM: WRITTEN TEXT, read in order. The first
version cut them out of his own gold dictations, and a dictation is
not prose: a clip cut at the cap ended "...במה שאתה מ.", a puzzle he
once talked through came back as "בכל מקרה שלא מותר לפרוש שני מספרים",
and a model asked to proofread it made it worse. His verdict
(2026-09-13): leave the past alone, give me real text, sentence by
sentence. So the deck is corpus\\read\\texts — any .txt or .md he drops
there, and paragraphs a language model writes for him (Writer: the
polish backends, Groq then Ollama, text only, a different subject each
time) when the folder runs dry — cut at full stops and offered in the
order they were written, so a paragraph reads as a paragraph. A
sentence is offered once: kept or skipped, it is not offered again.
`plausible` still stands between a file and the card: a lone letter for
a word, punctuation glued between words, a word three times running.

THE ENGLISH ON A CARD IS NOT CHECKED. A word he says in English comes
back in Hebrew letters — "קומיט" for commit — whichever way he says it,
and for an evening the card asked about every one, so English was kept
off the cards altogether. That threw away the best of it: the model
knows English, what it does not know is to write "commit" in Latin
letters in the middle of a Hebrew sentence, and a reading labelled
"commit" is exactly the pair that teaches it. So the sentences carry
a term or two where a developer would say one, and `match` forgives
whatever came back for a word with Latin or digits in it: only the
Hebrew has to come back as written. His decision, 2026-09-13 evening.

WHO OWNS WHAT. The app owns the microphone and the models, so the
recording and the transcript happen there (main.py: the read
diversion in _handle, the `read` control command). This module is the
part both sides share — the deck, the word match, and the folder. The
dashboard arms a sentence over the pipe, reads the app's answer off the
status poll, and says keep or drop. Nothing is pasted anywhere, and a
key held over any other window dictates exactly as it always has —
`takes` says so, at the press, from the foreground window alone.

THE FOLDER is corpus\\read, beside the corpus and not in it:
study.Corpus trims its own folder to [study] corpus_keep, and a set of
readings he sat down to make must never be the thing that trimming
loses. The sidecar is the corpus's — text, tier, seconds, kept — plus
`source: "read"`, the sentence's key, what the model heard, and the
match, so a clip can be told apart from a dictation and a disputed keep
can be re-examined.
"""
from __future__ import annotations

import ctypes
import difflib
import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import vocab as vocab_mod

log = logging.getLogger("dictation.reading")

TIER = "gold"
SOURCE = "read"
STAMP = "%Y%m%d-%H%M%S"
PENDING = "pending"          # the wav of a reading not yet kept or dropped
SKIPPED = "skipped.json"     # sentences he said he would never say
TEXTS = "texts"              # the folder of prose, under corpus\\read
WRITTEN = "written"          # what the model wrote: written-<stamp>.txt
TEXT_SUFFIXES = (".txt", ".md")
# A sentence worth reading: one breath. Shorter is a fragment ("סבבה."),
# longer is a paragraph he will stumble in.
MIN_WORDS, MAX_WORDS = 5, 22
_END = re.compile(r"(?<=[.?!:])\s+|\n+")
_HEBREW = re.compile(r"^[א-ת]$")
_FOREIGN = re.compile("[A-Za-z0-9]")   # a word the transcript may spell its way
_GLUE = re.compile(r"[א-ת][.,!?;:][א-ת]")   # "אחת,שתיים"
_MARKUP = re.compile(r"^\s*(?:[-*•]|\d+[.)]|#+)\s+")             # a list, a heading
_DASHES = re.compile("[‐‑‒–—−]")   # ‐ ‑ ‒ – — −
GA_ROOT = 2                  # GetAncestor: the top-level window
WRITE_SENTENCES = 12         # what one paragraph from the model is asked to hold
WRITE_NAMES = 3              # how many of his names it is offered at a time
# What the paragraphs are about, one subject a paragraph, round and
# round: the sentences have to vary, and a model asked for "a
# paragraph" twelve times writes the same paragraph twelve times.
SUBJECTS = (
    "a bug you ran into today and how to reproduce it",
    "asking the assistant to run the tests and report only what failed",
    "what the app should do the moment the key is released",
    "the plan for tomorrow morning, step by step",
    "a small thing about the phone app that annoys you",
    "explaining to a friend what the dictation app does and why",
    "a mistake the transcription keeps making and what you say instead",
    "a short story about something that happened at the desk today",
    "what a good summary of the day's work should and should not say",
    "asking for a screenshot before anything is changed",
    "why the machine has to stay awake while the screens are off",
    "what to do when the model gets a name wrong twice in a row",
)


def _root_of(hwnd: int) -> int:
    """The top-level window an HWND belongs to. Tk's winfo_id is a child
    of the frame Windows puts in the foreground, so both sides of the
    comparison in `takes` are taken up to the root."""
    if not hwnd:
        return 0
    try:
        return int(ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT)) or hwnd
    except Exception:                 # noqa: BLE001 — no user32 in a test
        return hwnd


def key_of(text: str) -> str:
    """A stable id for a sentence: its words, case-folded, hashed."""
    plain = " ".join(w.casefold() for w in vocab_mod.words(text))
    return hashlib.sha1(plain.encode("utf-8")).hexdigest()[:12]


def plausible(text: str) -> bool:
    """What a regex can tell is not a sentence to read aloud: a single
    Hebrew letter standing as a word (a recording cut mid-word, "שאתה
    מ."), punctuation glued between two words ("אחת,שתיים, שלוש.שלוש"),
    or a word three times running (a decoder loop)."""
    words = vocab_mod.words(text)
    if any(_HEBREW.match(w) for w in words):
        return False
    if _GLUE.search(text):
        return False
    folded = [w.casefold() for w in words]
    return not any(folded[i] == folded[i + 1] == folded[i + 2]
                   for i in range(len(folded) - 2))


def sentences(text: str) -> list[str]:
    """`text` cut at full stops and line ends, keeping the ones a breath
    long and plausible. A list marker or a heading mark at the front of
    a line is stripped: the sentence is what is read, not the bullet."""
    out = []
    # The typographic hyphens a model writes "ה‑tests" with (U+2011 and
    # its neighbours) are not the hyphen vocab.words keeps a prefix on,
    # so "ה" came off as a word of its own and the sentence was refused.
    text = _DASHES.sub("-", text or "")
    for piece in _END.split(text):
        piece = " ".join(_MARKUP.sub("", piece).split())
        if (MIN_WORDS <= len(vocab_mod.words(piece)) <= MAX_WORDS
                and plausible(piece)):
            out.append(piece)
    return out


@dataclass(frozen=True)
class Sentence:
    key: str
    text: str
    said: str                  # the file it came from, by stem
    terms: tuple[str, ...]     # the taught words it carries
    index: int = 0             # its place in that file, from 1
    count: int = 0             # how many the file holds


def terms_of(vocab_path: Path) -> list[str]:
    """The words he had to teach: the meant side of every correction
    that is a name or a term (vocab.family) or a phrase of more than
    one word. A single Hebrew word corrected once — "זה", "פה" — is a
    spelling wobble, not a word the model has never heard. They light
    the chips on a card that carries one; with no Latin on the cards,
    that is the Hebrew phrases."""
    try:
        data = json.loads(vocab_path.read_text("utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for c in data.get("corrections") or []:
        heard = " ".join(str(c.get("heard") or "").split())
        meant = " ".join(str(c.get("meant") or "").split())
        if not meant or meant in out:
            continue
        if (vocab_mod.family(heard, meant) == "term"
                or len(vocab_mod.words(meant)) > 1):
            out.append(meant)
    return out


def names_of(vocab_path: Path) -> list[str]:
    """The NAMES among the terms, for the writer: a term the decoder
    garbled INTO HEBREW ("גית-האב" for GitHub, "סלאש קליר" for slash
    clear), one corrected twice, or one with a capital inside it. An
    English word corrected to another English word ("it work" -> "it
    works") is an English dictation's slip, not a name, and a Hebrew
    paragraph written round "it works" reads like one."""
    try:
        data = json.loads(vocab_path.read_text("utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for c in data.get("corrections") or []:
        heard = " ".join(str(c.get("heard") or "").split())
        meant = " ".join(str(c.get("meant") or "").split())
        if not meant or meant in out or not _FOREIGN.search(meant) \
                or meant.replace(" ", "").isdigit():
            continue
        if (_HEBREW_ANY.search(heard) is not None
                or int(c.get("hits") or 1) >= 2
                or re.search(r"(?<=.)[A-Z]", meant) is not None):
            out.append(meant)
    return out


_HEBREW_ANY = re.compile("[א-ת]")
_PREFIX = re.compile(r"^[א-ת]{1,3}-")     # ל-GitHub, ה-API, וב-branch


def _bare(word: str) -> str:
    """A word without the Hebrew prefix hyphenated onto it: vocab.words
    keeps "ל-GitHub" as one token, and the term it carries is GitHub."""
    return _PREFIX.sub("", word).casefold()


def _carries(text: str, term: str) -> bool:
    """Whole words, in order — "branch" is not carried by "branches"."""
    have = [_bare(w) for w in vocab_mod.words(text)]
    want = [_bare(w) for w in vocab_mod.words(term)]
    if not want or len(want) > len(have):
        return False
    return any(have[i:i + len(want)] == want
               for i in range(len(have) - len(want) + 1))


def _done(read_root: Path) -> set[str]:
    """Keys of every sentence already kept or skipped."""
    done: set[str] = set()
    try:
        for side in read_root.glob("*.json"):
            if side.name == SKIPPED:
                continue
            try:
                meta = json.loads(side.read_text("utf-8"))
                done.add(str(meta.get("key") or key_of(meta.get("text", ""))))
            except (OSError, ValueError, AttributeError):
                pass
        skipped = json.loads((read_root / SKIPPED).read_text("utf-8"))
        done.update(str(k) for k in skipped)
    except (OSError, ValueError):
        pass
    return done


def text_files(texts: Path) -> list[Path]:
    """The prose, oldest file first — the order he put it there."""
    try:
        return sorted((p for p in texts.iterdir()
                       if p.suffix.lower() in TEXT_SUFFIXES and p.is_file()),
                      key=lambda p: (p.stat().st_mtime, p.name))
    except OSError:
        return []


def deck(texts: Path, vocab_path: Path, read_root: Path) -> list[Sentence]:
    """What is left to read, in the order it was written: file by file,
    sentence by sentence, nothing he has kept or skipped, nothing twice."""
    terms = terms_of(vocab_path)
    seen: set[str] = set(_done(read_root))
    out: list[Sentence] = []
    for path in text_files(texts):
        try:
            body = path.read_text("utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        found = sentences(body)
        for index, text in enumerate(found, 1):
            key = key_of(text)
            if key in seen:
                continue
            seen.add(key)
            carried = tuple(t for t in terms if _carries(text, t))
            out.append(Sentence(key, text, path.stem, carried, index,
                                len(found)))
    return out


def match(expected: str, heard: str) -> dict:
    """Did the transcript come back as written? Word for word — for the
    Hebrew. A word on the card with Latin or digits in it is FORGIVEN
    whatever came back for it ("קומיט" for commit, "גיט האב" for GitHub,
    "שש" for 6): the transcript cannot be trusted to spell English
    inside Hebrew, that is what the reading is for, and the card's
    spelling is the label either way.

    {"words": how many the card has, "same": how many came back in
    place or were forgiven, "forgiven": how many of those were
    forgiven, "pairs": [(heard, expected), ...] where a run of Hebrew
    words was replaced, "missing": words the transcript has no trace
    of, "extra": words it has that the card does not}.
    """
    a = [w.casefold() for w in vocab_mod.words(expected)]
    b = [w.casefold() for w in vocab_mod.words(heard)]
    ea, hb = vocab_mod.words(expected), vocab_mod.words(heard)
    same = forgiven = missing = extra = 0
    pairs: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            same += i2 - i1
        elif tag in ("replace", "delete"):
            # The names and numbers in the run are not held against
            # him, whatever came back for them or nothing at all; the
            # Hebrew beside them still has to be there.
            hebrew = [w for w in ea[i1:i2] if not _FOREIGN.search(w)]
            foreign = (i2 - i1) - len(hebrew)
            same += foreign
            forgiven += foreign
            if not hebrew:
                continue
            if tag == "replace":
                pairs.append((" ".join(hb[j1:j2]), " ".join(hebrew)))
            else:
                missing += len(hebrew)
        elif tag == "insert":
            extra += j2 - j1
    return {"words": len(a), "same": same, "forgiven": forgiven,
            "pairs": pairs, "missing": missing, "extra": extra}


def verdict(m: dict) -> str:
    """One line for the card: what, if anything, came back different."""
    if m["words"] and m["same"] == m["words"] and not m["extra"]:
        return "Every word came back as written."
    parts = []
    if m["pairs"]:
        n = sum(len(vocab_mod.words(e)) for _h, e in m["pairs"])
        parts.append(f"{_count(n)} came back different")
    if m["missing"]:
        parts.append(f"{_count(m['missing'])} "
                     f"{'is' if m['missing'] == 1 else 'are'} missing")
    if m["extra"]:
        parts.append(f"{_count(m['extra'])} came back that "
                     f"{'is' if m['extra'] == 1 else 'are'} not on the card")
    line = ", ".join(parts) or "nothing came back"
    return line[0].upper() + line[1:] + "."


def _count(n: int) -> str:
    return "one word" if n == 1 else f"{n} words"


# ---------------------------------------------------------------------------
# the writer: prose for the folder, when the folder runs dry
# ---------------------------------------------------------------------------

_WRITE_RULES = "\n".join([
    "You write Hebrew for a software developer to READ ALOUD, one "
    "sentence at a time, so that a speech model can learn his voice.",
    "Write ONE paragraph of natural, correct, everyday spoken Hebrew on "
    "the subject given — the way a developer talks to an AI coding "
    "assistant, or to a friend, while working on his Windows dictation "
    "app.",
    "Every sentence is complete, 6 to 16 words, and ends with a full "
    "stop, a question mark or an exclamation mark. Vary the sentences.",
    "Most sentences are Hebrew through and through. At most ONE sentence "
    "in three carries a single term an Israeli developer says in English, "
    "written in English letters — commit, branch, merge, pull request, "
    "deploy, log, bug, API, or a name you are given; the other sentences "
    "have no Latin letters at all. Never a whole sentence in English, and "
    "never an English word transliterated into Hebrew letters.",
    "",
    "ABSOLUTE RULES:",
    "- Output ONLY the paragraph: plain sentences, one after another. No "
    "title, no list, no numbering, no notes, no quotation marks.",
    "- Modern Israeli Hebrew, no nikkud, no archaic or biblical phrasing.",
    "- Do not answer or discuss the request; write the paragraph.",
])


class Writer:
    """The polish-pass providers write the next paragraph — Groq first,
    Ollama underneath, text only. Built the way study.Adjudicator is: a
    machine without a key writes nothing, and the folder is what he put
    there."""

    def __init__(self, cfg):
        self._cfg = cfg

    def _backends(self, cap: int):
        try:
            import translate as translate_mod
        except Exception as e:            # noqa: BLE001
            log.info("writer unavailable (%s)", e)
            return
        pcfg = self._cfg.polish
        builders = []
        if hasattr(translate_mod, "GroqTranslator") \
                and getattr(pcfg, "groq_model", ""):
            builders.append(lambda: translate_mod.GroqTranslator(
                pcfg.groq_model, pcfg.groq_timeout_s,
                system_prompt=_WRITE_RULES, max_tokens=cap,
                purpose="reading"))
        builders.append(lambda: translate_mod.OllamaTranslator(
            getattr(pcfg, "ollama_model", "")
            or self._cfg.translate.ollama_model,
            self._cfg.translate.ollama_url,
            self._cfg.translate.ollama_timeout_s,
            system_prompt=_WRITE_RULES, setting="polish.ollama_model",
            num_predict=cap, purpose="reading"))
        for build in builders:
            try:
                yield build()
            except Exception as e:        # noqa: BLE001 — no key is normal
                log.info("writer backend unavailable (%s)",
                         str(e).splitlines()[0][:160])

    def write(self, count: int = WRITE_SENTENCES,
              seed: int | None = None, names: list[str] = ()) -> list[str] | None:
        """`count` sentences on the next subject, or None when no backend
        answered usably. The subject is SUBJECTS[seed] round the table —
        the caller passes how many paragraphs exist — so consecutive
        paragraphs are not the same paragraph; `names` (names_of) are
        offered for it to use where natural, a few at a time, turning
        with the seed as well."""
        subject = SUBJECTS[(seed or 0) % len(SUBJECTS)]
        ask = f"Write {count} sentences. Subject: {subject}."
        names = list(names)
        if names:
            start = ((seed or 0) * WRITE_NAMES) % len(names)
            picked = [names[(start + i) % len(names)]
                      for i in range(min(WRITE_NAMES, len(names)))]
            ask += " Names you may use where natural: " + ", ".join(picked) + "."
        cap = max(768, count * 60)
        for backend in self._backends(cap):
            try:
                reply = backend.translate(ask) or ""
            except Exception as e:        # noqa: BLE001
                log.info("writing via %s failed (%s)", backend.name,
                         str(e).splitlines()[0][:160])
                continue
            found = mixed(sentences(reply))
            if len(found) < max(3, count // 2):
                log.info("writing via %s REJECTED — %d usable sentence(s) "
                         "in the reply", backend.name, len(found))
                continue
            log.info("wrote %d sentence(s) via %s on %r", len(found),
                     backend.name, subject)
            return found
        return None


def mixed(found: list[str]) -> list[str]:
    """At most a third of the sentences carry a term. Asked for one in
    three, the model gives one in two (measured 2026-09-13: 6, 6 and 5
    of 12), so the surplus term-bearing sentences are dropped, in
    order, and the paragraph is a little shorter for it."""
    hebrew = sum(1 for text in found if not _FOREIGN.search(text))
    cap = max(1, hebrew // 2)            # f <= (h + f) / 3  <=>  f <= h / 2
    out, used = [], 0
    for text in found:
        if _FOREIGN.search(text):
            if used >= cap:
                continue
            used += 1
        out.append(text)
    return out


def written_count(texts: Path) -> int:
    return sum(1 for p in text_files(texts) if p.stem.startswith(WRITTEN))


def save_written(texts: Path, found: list[str]) -> Path | None:
    """One paragraph into the folder as written-<stamp>.txt, a sentence
    a line — the same file he could have dropped there himself."""
    try:
        texts.mkdir(parents=True, exist_ok=True)
        stem = f"{WRITTEN}-{time.strftime(STAMP)}"
        path = texts / f"{stem}.txt"
        n = 1
        while path.exists():
            path = texts / f"{stem}-{n}.txt"
            n += 1
        path.write_text("\n".join(found) + "\n", "utf-8")
        return path
    except OSError as e:
        log.warning("could not keep the written paragraph (%s)", e)
        return None


class Reading:
    """The app's side: one armed sentence, and what came back for it.

    Everything here is a flag flip or a file move, so it is safe on the
    control thread, the worker and the keyboard hook alike.
    """

    def __init__(self, root: Path, root_of=_root_of):
        self.root = root
        self._root_of = root_of
        self._lock = threading.RLock()     # heard() reports through state()
        self._armed: dict | None = None      # {"id", "text", "hwnd"}
        self._heard: dict | None = None      # what came back, with "wav"

    # ---------------------------------------------------------- arming

    def arm(self, ident: str, text: str, hwnd: int = 0) -> dict:
        ident, text = str(ident or "").strip(), " ".join(str(text or "").split())
        with self._lock:
            if self._armed and self._armed["id"] != ident:
                self._drop_locked()
            if self._heard and self._heard["id"] != ident:
                self._drop_locked()
            self._armed = ({"id": ident, "text": text, "hwnd": int(hwnd or 0)}
                           if ident and text else None)
        return self.state()

    def disarm(self) -> None:
        with self._lock:
            self._armed = None
            self._drop_locked()

    def takes(self, foreground: int) -> bool:
        """Is a dictation begun over `foreground` a reading? Only with a
        sentence armed AND the dashboard that armed it in front — a key
        held over his editor dictates exactly as it always has."""
        with self._lock:
            armed = self._armed
        if not armed or not armed["hwnd"] or not foreground:
            return False
        return self._root_of(foreground) == self._root_of(armed["hwnd"])

    @property
    def armed_id(self) -> str | None:
        with self._lock:
            return self._armed["id"] if self._armed else None

    # ---------------------------------------------------------- results

    def heard(self, ident: str, wav: bytes, seconds: float,
              text: str) -> dict | None:
        """The transcript of a reading is back. The audio waits in the
        folder as a pending file until keep() or drop() decides."""
        with self._lock:
            if not self._armed or self._armed["id"] != ident:
                return None
            self._drop_locked()              # a second try replaces the first
            pending = self.root / f"{PENDING}-{ident}.wav"
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                pending.write_bytes(wav)
            except OSError as e:
                log.warning("could not keep the reading's audio (%s)", e)
                return None
            m = match(self._armed["text"], text)
            self._heard = {"id": ident, "text": text,
                           "seconds": round(float(seconds), 2),
                           "match": m, "wav": pending,
                           "when": time.strftime("%H:%M")}
            # D8: counts only. What was heard is this reading's `heard`,
            # filed in its sidecar when it is kept.
            log.info("reading: %s — %d of %d words as written, %d pair(s) "
                     "differ", verdict(m).rstrip("."), m["same"], m["words"],
                     len(m["pairs"]))
            return self.state()

    def keep(self, ident: str) -> Path | None:
        """File the pending audio under the card's words. The wav path,
        or None when there is nothing pending for `ident`."""
        with self._lock:
            heard, armed = self._heard, self._armed
            if not heard or heard["id"] != ident or not armed:
                return None
            stem = time.strftime(STAMP)
            wav = self.root / f"{stem}.wav"
            n = 1
            while wav.exists():
                wav = self.root / f"{stem}-{n}.wav"
                n += 1
            try:
                heard["wav"].replace(wav)
                wav.with_suffix(".json").write_text(json.dumps({
                    "text": armed["text"], "key": ident, "tier": TIER,
                    "seconds": heard["seconds"],
                    "kept": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "source": SOURCE, "heard": heard["text"],
                    "match": [heard["match"]["same"],
                              heard["match"]["words"]],
                }, ensure_ascii=False, indent=2), "utf-8")
            except OSError as e:
                log.warning("could not file the reading (%s)", e)
                return None
            self._heard = None
            self._armed = None
            log.info("reading kept: %s (%.1f s)", wav.name, heard["seconds"])
            return wav

    def drop(self, ident: str, skipped: bool = False) -> bool:
        """Read again (the pending audio goes) or skip (the sentence is
        not offered again either)."""
        with self._lock:
            armed = self._armed
            if skipped and armed and armed["id"] == ident:
                self._skip_locked(armed["text"])
                self._armed = None
            if not self._heard or self._heard["id"] != ident:
                return False
            self._drop_locked()
            return True

    def forget(self, name: str) -> bool:
        """A kept reading he takes back — the wav and its sidecar, by the
        name keep() answered with, and only a file of this folder."""
        if not name or "/" in name or "\\" in name or not name.endswith(".wav"):
            return False
        wav = self.root / name
        if not wav.exists() or wav.name.startswith(PENDING):
            return False
        for path in (wav, wav.with_suffix(".json")):
            try:
                path.unlink()
            except OSError as e:
                log.warning("could not take back %s (%s)", path.name, e)
                return False
        log.info("reading taken back: %s", name)
        return True

    def _drop_locked(self) -> None:
        heard, self._heard = self._heard, None
        if heard:
            try:
                heard["wav"].unlink()
            except OSError:
                pass

    def _skip_locked(self, text: str) -> None:
        path = self.root / SKIPPED
        try:
            keys = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            keys = []
        key = key_of(text)
        if key not in keys:
            keys.append(key)
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(keys, indent=0), "utf-8")
            except OSError as e:
                log.warning("could not note the skipped sentence (%s)", e)

    # ------------------------------------------------------------ status

    def state(self) -> dict:
        """What the dashboard draws: the armed sentence and, once it is
        back, the transcript with its match. No paths — nothing here is
        the dashboard's to touch."""
        with self._lock:
            armed = dict(self._armed) if self._armed else None
            heard = self._heard
            if armed:
                armed.pop("hwnd", None)
            return {
                "armed": armed,
                "heard": None if not heard else {
                    "id": heard["id"], "text": heard["text"],
                    "seconds": heard["seconds"], "when": heard["when"],
                    "match": dict(heard["match"]),
                    "verdict": verdict(heard["match"]),
                },
            }


def tally(read_root: Path, corpus: Path, today: str | None = None) -> dict:
    """How much of his voice is on file, and how much of it is today's.

    {"total_s": every gold second in corpus\\ and corpus\\read,
     "read_s": the readings alone, "today_s": today's readings,
     "today": [(when, text), ...] newest first}.
    """
    today = today or time.strftime("%Y-%m-%d")
    total = read_s = today_s = 0.0
    kept: list[tuple[str, str]] = []
    for folder, mine in ((corpus, False), (read_root, True)):
        try:
            sides = list(folder.glob("*.json"))
        except OSError:
            continue
        for side in sides:
            if side.name == SKIPPED:
                continue
            try:
                meta = json.loads(side.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(meta, dict) or meta.get("tier") != TIER:
                continue
            seconds = float(meta.get("seconds") or 0.0)
            total += seconds
            if mine:
                read_s += seconds
                when = str(meta.get("kept") or "")
                if when.startswith(today):
                    today_s += seconds
                    kept.append((when[11:16], str(meta.get("text") or "")))
    kept.sort(reverse=True)
    return {"total_s": round(total, 1), "read_s": round(read_s, 1),
            "today_s": round(today_s, 1), "today": kept}
