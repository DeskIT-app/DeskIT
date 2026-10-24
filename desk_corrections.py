"""Corrections on the web desk: every pending proposal of the second
reading, and every word it has learned, with the Words tab's tools —
the search, the Use them switch, [+ Teach a word], the pencil and the
cross on a row.

THE TK DESK IS THE SOURCE OF TRUTH (dashboard._screen_corrections and
everything it calls). Same files, same words, same doors:

- the proposals are review.json's pending items, newest first
  (review.Store.pending), each with the pile's two answers. Only the
  newest Yes is lit — ONE GOLD BUTTON PER SURFACE — and while a
  proposal waits [+ Teach a word] steps down to a quiet button
  (dashboard._fill_corrections). A verdict is written straight into
  review.json (Store.decide, by "dashboard") and the app is told
  (`review_absorb`), as dashboard._review_decide does;
- the learned words are vocab.json, newest first, each with one plain
  line about how it is used (dashboard._word_meta) and "in the prompt"
  when its meant form is one of the terms the decoder is handed —
  ranked the way the app ranks them (the same Vocab, the same config);
- a pair typed, changed or forgotten goes through the running app's
  `vocab` verb (main.App._vocab_command: the app owns vocab.json while
  it runs and its save would overwrite ours), and into the file itself
  when nothing runs (dashboard._vocab_change);
- Use them is `vocab.enabled`, through the app's `option` verb while it
  runs and config.save when it does not (dashboard._words_use), told
  in settings.saved_sentence's words.

READING NEVER WRITES. The Tk desk built a vocab.Vocab to list the
words, and Vocab.load() renames a file it cannot parse out of the way —
a read that moved his file, under the app that owns it. This module
reads vocab.json (and its last good copy) without touching either; only
the three doors write, through the same Vocab methods the Tk desk uses.

THE PAGE IS NOT TRUSTED. Every `do` is on ACTS; a proposal's id, a word
and a switch's value are checked before they reach review.json,
vocab.json, the config or the pipe; a failure answers with the
exception's type, never its text (web/README.md).

Reached through deskweb.Api.place("corrections", ...), one Place per
window, with the window's pipe function (`send`).
"""
from __future__ import annotations

import os
import re
import threading

import config as config_mod
import deskweb
import paths
import summary

#: What the page may ask this place to do.
ACTS = ("accept", "reject", "learn", "edit", "forget", "use")
#: The most a learned word may be, either side. The editor's fields stop
#: here too; anything longer is not a word anybody typed.
WORD_MAX = 200
#: The longest search the page may send.
QUERY_MAX = 200
#: A proposal's id is the recording's stem (review.py: item.wav_path.stem).
_SID = re.compile(r"^[\w.:\-]{1,120}$")
#: The words in front of a dropped tail: the pill is the only thing after
#: them, so a longer lead-in than this would push it out of sight
#: (deskweb._HEAD_WORDS is the same lesson for a change).
_DROP_HEAD_WORDS = 10
_COUNT_WORDS = ("No", "One", "Two", "Three", "Four", "Five", "Six")


def _count_word(n: int) -> str:
    return _COUNT_WORDS[n] if 0 <= n < len(_COUNT_WORDS) else str(n)


def _flat(text) -> str:
    return " ".join(str(text or "").split())


def _plain(text) -> str:
    """A word as typed: whitespace collapsed, and no control character —
    the editor cannot type one, so one that arrives is not his."""
    return _flat("".join(ch for ch in str(text) if ch >= " " or ch in "\t\n\r"))


def _vocab_cfg():
    try:
        return config_mod.load_layered().vocab
    except Exception:                     # noqa: BLE001 — unreadable config
        return config_mod.VocabConfig()


def _stat(path) -> tuple | None:
    try:
        st = os.stat(path)
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


# ------------------------------------------------------------ the words


def word_meta(entry: dict, ready_at: int) -> tuple[str, str, str, str]:
    """dashboard._word_meta as (the state's dot, its words, the rest, the
    whole line): "fixed on every dictation · ×3", "corrected once — fixed
    after the second time", "its own guess", and when it was last taught.
    The row draws the words and the rest — the approved picture's
    "Corrected once · 3 h ago" — and keeps the whole line under the
    pointer: in a row beside its pair it does not fit."""
    try:
        hits = int(entry.get("hits", 1) or 0)
    except (TypeError, ValueError):
        hits = 0
    when = deskweb.ago(deskweb.stamp_of(str(entry.get("last") or ""),
                                        "%Y-%m-%d %H:%M:%S"))
    if hits >= ready_at:
        dot, said, more, rest = "fix", "fixed on every dictation", "", [f"×{hits}"]
    elif hits >= 1:
        dot, said, rest = "once", "corrected once", []
        more = (" — fixed after the "
                + ("second" if ready_at == 2 else _count_word(ready_at).lower() + "th")
                + " time")
    else:
        dot, said, more, rest = "guess", "its own guess", "", []
    rest += [when] if when else []
    whole = "  ·  ".join([said + more] + rest)
    return dot, said, "  ·  ".join(rest), whole


def read_words(path) -> list[dict]:
    """vocab.json's pairs, or its last good copy's — read, never moved
    or written (Vocab.load sets an unreadable file aside)."""
    import vocab as vocab_mod
    path = paths.VOCAB_FILE if path is None else path
    for source in (path, path.with_name(path.name + ".bak")):
        try:
            data = vocab_mod._read_store(source)
        except FileNotFoundError:
            if source == path and not source.with_name(source.name + ".bak").exists():
                return []
            continue
        except Exception:                 # noqa: BLE001 — cut, locked, not a store
            continue
        found = data.get("corrections")
        return [c for c in found if isinstance(c, dict) and c.get("meant")] \
            if isinstance(found, list) else []
    return []


def prompt_terms(corrections: list, vcfg) -> list[str]:
    """The terms the decoder is handed, ranked by vocab.Vocab itself — the
    app's class, so "in the prompt" is the app's answer — over a list that
    was read here: its load() is not run, so nothing is set aside."""
    import vocab as vocab_mod

    class Reader(vocab_mod.Vocab):
        def load(self) -> None:           # read-only: the list is handed in
            return None

    v = Reader(paths.VOCAB_FILE, seed_terms=tuple(vcfg.terms),
               max_terms=vcfg.max_terms,
               replace_after_hits=vcfg.replace_after_hits,
               hebrew_after_hits=getattr(vcfg, "hebrew_after_hits", 3))
    v.corrections = list(corrections)
    return v.terms()


def entries_and_hot(vcfg) -> tuple[list, set]:
    """Every learned pair, newest first, and the lowercased meant forms
    in the decoder's prompt right now (dashboard._words_entries)."""
    entries = [c for c in read_words(paths.VOCAB_FILE)
               if str(c.get("heard") or "").strip() and str(c.get("meant") or "").strip()]
    entries.sort(key=lambda c: str(c.get("last") or ""), reverse=True)
    try:
        hot = {t.lower() for t in prompt_terms(entries, vcfg)}
    except Exception:                     # noqa: BLE001
        hot = set()
    return entries, hot


# ------------------------------------------------------- the proposals


def drop_segments(text: str, before: str) -> tuple[list[dict], str]:
    """A dropped run drawn where it sits: the words in front of it, the
    run on its red pill (the approved picture puts it at the end of the
    sentence it would leave), and what follows it to the sentence's
    stop. Returns (segments, the sentence shown)."""
    flat, goes_all = _flat(text), _flat(before)
    goes = deskweb.first_words(goes_all, 5)
    at = flat.rfind(goes_all) if goes_all else -1
    if at < 0:
        where = summary.first_sentence(flat)
        return [{"t": "drop", "s": goes}] + ([{"t": "ctx", "s": where}] if where else []), where
    found = summary.sentences(flat[:at].strip())
    head = (found[-1] if found else "").split()
    if len(head) > _DROP_HEAD_WORDS:
        head = ["…"] + head[-_DROP_HEAD_WORDS:]
    tail = flat[at + len(goes_all):].split()
    for k, word in enumerate(tail):
        if word and word[-1] in summary.STOPS:
            tail = tail[:k + 1]
            break
    if len(tail) > deskweb._CONTEXT_WORDS:
        tail = tail[:deskweb._CONTEXT_WORDS] + ["…"]
    segs: list[dict] = []
    if head:
        segs.append({"t": "ctx", "s": " ".join(head)})
    segs.append({"t": "drop", "s": goes})
    if tail:
        segs.append({"t": "ctx", "s": " ".join(tail)})
    return segs, " ".join(head + [goes] + tail)


def proposal_rows(pending: list) -> list[dict]:
    """The pending proposals as the page draws them — each said as WHAT
    CHANGED, every change in its place (dashboard._change_bands), the
    newest one's Yes the only lit button."""
    rows = []
    for item in pending:
        sid = str(item.get("id", ""))
        changes = [c for c in (item.get("changes") or []) if isinstance(c, dict)]
        heard_text = _flat(item.get("text"))
        proposed = _flat(item.get("proposed")) or heard_text
        count = (f"{_count_word(len(changes)).lower()} word"
                 f"{'' if len(changes) == 1 else 's'}")
        first = changes[0] if changes else {}
        why = _flat(first.get("why"))
        row = {"id": sid, "rtl": deskweb.is_rtl(heard_text or proposed),
               "why": why, "why_rtl": deskweb.is_rtl(why), "more": "",
               "buttons": [{"label": "Yes", "tone": "primary" if not rows else "quiet",
                            "do": "accept", "arg": sid},
                           {"label": "No", "tone": "quiet", "do": "reject", "arg": sid}]}
        if not changes:
            row.update(count="", why="", text=summary.first_sentence(proposed), segs=None)
        elif not str(first.get("after") or "").strip() or str(first.get("kind")) == "drop":
            segs, where = drop_segments(heard_text, _flat(first.get("before")))
            more = len(changes) - 1
            row.update(count=f"{count} to delete", segs=segs, text="",
                       more=(f"and {_count_word(more).lower()} more change"
                             f"{'' if more == 1 else 's'}") if more else "")
        else:
            segs, shown = deskweb.change_segments(heard_text, changes)
            left = len(changes) - shown
            row.update(count=f"{count} changed", segs=segs, text="",
                       more=(f"and {_count_word(left).lower()} more change"
                             f"{'' if left == 1 else 's'} in the sentence") if left else "")
        rows.append(row)
    return rows


# ------------------------------------------------------------ the place


class Place:
    """Corrections, as data, and what its buttons do. One per window;
    the page's calls arrive on threads of their own, so both public
    methods hold the lock."""

    def __init__(self, send) -> None:
        self._send = send
        self._lock = threading.RLock()
        #: the search the page last read with: an act answers with the
        #: place as that read would have drawn it
        self._query = ""
        #: (stamp, rows) of the last proposals and words read
        self._kept: dict[str, tuple] = {}
        #: the last `review_absorb` sent (a test joins it)
        self.absorb: threading.Thread | None = None

    # -- reading

    def read(self, q="", **unknown) -> dict:
        if unknown:
            return {"ok": False, "error": "Corrections reads with a search and nothing else"}
        if not isinstance(q, str):
            return {"ok": False, "error": "a search is words"}
        with self._lock:
            self._query = _flat(q)[:QUERY_MAX]
            return self._read()

    def _proposals(self) -> list[dict]:
        stamp = _stat(paths.REVIEW_FILE)
        kept = self._kept.get("review")
        if kept is not None and kept[0] == stamp and stamp is not None:
            return kept[1]
        try:
            import review as review_mod
            pending = review_mod.Store(paths.REVIEW_FILE).pending()
        except Exception:                 # noqa: BLE001 — absent or broken
            pending = []
        rows = proposal_rows(pending)
        self._kept["review"] = (stamp, rows)
        return rows

    def _words(self, vcfg) -> tuple[list, set]:
        stamp = (_stat(paths.VOCAB_FILE), vcfg.max_terms, vcfg.replace_after_hits,
                 getattr(vcfg, "hebrew_after_hits", 3), tuple(vcfg.terms))
        kept = self._kept.get("vocab")
        if kept is not None and kept[0] == stamp and stamp[0] is not None:
            return kept[1]
        got = entries_and_hot(vcfg)
        self._kept["vocab"] = (stamp, got)
        return got

    def _read(self) -> dict:
        vcfg = _vocab_cfg()
        proposals = self._proposals()
        entries, hot = self._words(vcfg)
        query = self._query
        low = query.lower()
        shown = [c for c in entries if not low or low in str(c["heard"]).lower()
                 or low in str(c["meant"]).lower()]
        ready_at = int(vcfg.replace_after_hits)
        ready = sum(1 for c in entries if _hits(c) >= ready_at)
        words = []
        for c in shown:
            heard, meant = str(c["heard"]), str(c["meant"])
            dot, said, rest, whole = word_meta(c, ready_at)
            words.append({"heard": heard, "meant": meant,
                          "rtl": deskweb.is_rtl(heard) or deskweb.is_rtl(meant),
                          "dot": dot, "said": said[:1].upper() + said[1:], "rest": rest,
                          "whole": whole,
                          "hot": meant.strip().lower() in hot})
        n = len(entries)
        if query:
            learned = (f"{len(shown)} of {n} word{'' if n == 1 else 's'} match "
                       f"“{query}”")
            empty = "" if shown or not entries else \
                f"No learned word has “{query}” in it."
        elif entries:
            learned = f"{n} word{'' if n == 1 else 's'}, newest first"
            empty = ""
        else:
            learned = "Nothing learned yet."
            empty = ""
        if not entries:
            empty = ("Say Yes to a second reading, press the teach key on a "
                     "word it got wrong, or teach it one here — the pairs "
                     "it learns are listed here, newest first.")
        teach = deskweb.key_caps(str(self._keys().get("correct_hotkey") or ""))
        cap = vcfg.max_terms
        return {
            "ok": True,
            "about": "The words it learned, and what the second reading proposes.",
            "proposals": proposals,
            "waiting": f"{len(proposals)}, newest first" if proposals else "",
            "learned": learned,
            "words": words,
            "empty": empty,
            "query": query,
            "use": bool(getattr(vcfg, "enabled", True)),
            # Teach a word holds the gold only while nothing waits
            "teach_lit": not proposals,
            "panel": {
                "n": n,
                "said": "words it has learned to hear your way",
                "facts": [{"dot": "fix", "n": ready, "said": "fixed on every dictation"},
                          {"dot": "li", "n": len(hot), "said": "in the decoder's prompt"}],
                "teach": teach,
                "teach_said": ["teaches it a word", "from what it just wrote"],
                "how": [("The best of them go into the decoder's prompt before it "
                         f"listens — {cap} at a time.") if cap else
                        "The best of them go into the decoder's prompt before it listens.",
                        "A word corrected twice is fixed on every dictation."],
            },
        }

    def _keys(self) -> dict:
        try:
            cfg = config_mod.load_layered()
        except Exception:                 # noqa: BLE001
            return {}
        return {name: getattr(cfg, name, "") for name, _label in config_mod.HOTKEY_FIELDS}

    # -- doing

    def act(self, do: str, arg=None) -> dict:
        """One button. Answers {"ok", "note", "done", "place"}: the note
        is the line the page shows for a moment; done says the editor's
        work is over (False keeps it open: a word is missing, or the two
        are the same); place is the place again, read after the press."""
        do = str(do)
        if do not in ACTS:
            return {"ok": False, "error": f"{do[:40]!r} is not a Corrections action"}
        with self._lock:
            if do in ("accept", "reject"):
                note, done = self._decide(arg, "accepted" if do == "accept" else "rejected"), True
            elif do == "use":
                if not isinstance(arg, bool):
                    return {"ok": False, "error": "the switch is on or off"}
                note, done = self._use(arg), True
            else:
                refused, checked = self._checked(do, arg)
                if refused:
                    return {"ok": False, "error": refused}
                note, done = self._vocab(do, checked)
            # whatever the press wrote is read again, whatever its stat says
            self._kept.clear()
            return {"ok": True, "note": note, "done": done, "place": self._read()}

    def _running(self) -> bool:
        reply = self._send("status", timeout_ms=1200)
        return isinstance(reply, dict) and reply.get("stage") == "running"

    def _decide(self, arg, verdict: str) -> str:
        """Yes or No on a row (dashboard._review_decide): written to
        review.json here, and the app told — it learns at once if it is
        listening, at its next idle tick otherwise."""
        sid = arg if isinstance(arg, str) else ""
        if not _SID.match(sid):
            return "that one was already decided"
        try:
            import review as review_mod
            item = review_mod.Store(paths.REVIEW_FILE).decide(sid, verdict, by="dashboard")
        except Exception as e:            # noqa: BLE001
            return f"could not save that ({type(e).__name__})"
        if item is None:
            return "that one was already decided"
        # off this thread, as the Tk desk's _ask: the row is already gone
        # from the answer, and a busy app must not hold it up
        self.absorb = threading.Thread(
            target=lambda: self._send("review_absorb", timeout_ms=1500),
            daemon=True, name="corrections-absorb")
        self.absorb.start()
        return "accepted — the app will learn it" if verdict == "accepted" else "rejected"

    def _checked(self, do: str, arg) -> tuple[str, dict]:
        """The editor's words, as dashboard._words_save collapses them:
        (a refusal, or "", and the words). A page that sends anything but
        words is refused in words."""
        if do == "forget":
            heard = _plain(arg) if isinstance(arg, str) else ""
            if not heard or len(heard) > WORD_MAX:
                return "that word is not in the list", {}
            return "", {"heard": heard}
        if not isinstance(arg, dict) or set(arg) - {"heard", "meant", "was"}                 or not all(isinstance(v, str) for v in arg.values()):
            return "a word is typed as words", {}
        heard, meant = _plain(arg.get("heard", "")), _plain(arg.get("meant", ""))
        if len(heard) > WORD_MAX or len(meant) > WORD_MAX:
            return "that is longer than a word", {}
        checked = {"heard": heard, "meant": meant}
        if do == "edit":
            was = _plain(arg.get("was", ""))
            if not was or len(was) > WORD_MAX:
                return "that word is not in the list", {}
            checked["was"] = was
        return "", checked

    def _vocab(self, do: str, args: dict) -> tuple[str, bool]:
        """One of the three doors (dashboard._words_save, _words_forget,
        _vocab_change): through the running app, which owns vocab.json
        while it runs, and straight into the file when nothing runs."""
        if do in ("learn", "edit"):
            if not args["heard"] or not args["meant"]:
                return "both words are needed", False
            if args["heard"].lower() == args["meant"].lower():
                return "the two words are the same", False
        if self._running():
            if do == "learn":
                reply = self._send("vocab", timeout_ms=4000, do="learn",
                                   heard=args["heard"], meant=args["meant"])
            elif do == "edit":
                reply = self._send("vocab", timeout_ms=4000, do="edit", heard=args["was"],
                                   new_heard=args["heard"], meant=args["meant"])
            else:
                reply = self._send("vocab", timeout_ms=4000, do="forget",
                                   heard=args["heard"])
            if reply is None:
                # it stopped between the question and the press
                return "dictation stopped — try again", True
            if not reply.get("ok"):
                return str(reply.get("error") or "that did not work")[:200], True
            return str(reply.get("message") or do)[:200], True
        import vocab as vocab_mod
        vcfg = _vocab_cfg()
        try:
            v = vocab_mod.Vocab(paths.VOCAB_FILE, replace_after_hits=vcfg.replace_after_hits)
        except Exception as e:            # noqa: BLE001
            return f"could not read the words ({type(e).__name__})", True
        try:
            if do == "learn":
                v.learn_by_hand(args["heard"], args["meant"])
                what = "learned"
            elif do == "edit":
                v.edit(args["was"], args["heard"], args["meant"])
                what = "changed"
            else:
                what = "forgotten" if v.forget(args["heard"]) else "not in the list"
        except KeyError:
            what = "not in the list"
        except ValueError as e:
            # learn_by_hand / edit's own two refusals, already said above
            what = str(e) if str(e) in ("both words are needed",
                                        "the two words are the same") else "not saved"
        return f"{what} — {len(v)} words (the app reads them when it starts)", True

    def _use(self, on: bool) -> str:
        """The switch (dashboard._words_use): vocab.enabled — off, the
        app neither repairs a dictation with the list nor puts its words
        in the decoder's prompt; the list itself stays."""
        import settings as settings_mod
        if self._running():
            reply = self._send("option", timeout_ms=4000, name="vocab.enabled", value=on)
            if reply is None:
                return "dictation is not running"
            if not reply.get("ok"):
                return str(reply.get("error") or "that did not work")[:200]
            return str(reply.get("message")
                       or settings_mod.saved_sentence("vocab.enabled", on))[:200]
        try:
            config_mod.save({"vocab.enabled": on})
        except Exception as e:            # noqa: BLE001
            return f"could not save that ({type(e).__name__})"
        return settings_mod.saved_sentence("vocab.enabled", on, live=False)


def _hits(entry: dict) -> int:
    try:
        return int(entry.get("hits", 1))
    except (TypeError, ValueError):
        return 0
