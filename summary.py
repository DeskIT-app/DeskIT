"""One line that says what a long thing is about, cut where a sentence ends.

The desk shows things that are long in places that are one line high. A
report is up to 600 characters typed into one box (`problems.TEXT_MAX`);
a notification carries a paragraph of body under its title; a second
reading is a whole dictated sentence. Until now every one of those was
cut by WIDTH — as many characters as the pixels allowed, ending wherever
the budget ran out, which is almost always the middle of a word. The
owner read that on 2026-09-07 and said, of his own bug reports: "I also
don't understand the report... so maybe for the report I'll do a summary
or something like that of the report each time so it displays it on the
home screen normally... Maybe display the sentence from point to point."

From point to point is the whole idea here, and it is why this is not a
truncation helper. `one_line` gives back the FIRST SENTENCE, whole, with
nothing appended to it — a whole sentence is a thing a person can read,
and an ellipsis after one is a lie about there being a cut. Only when
that single sentence is itself wider than the room it has is anything
shaved off, and then the cut goes to the last CLAUSE boundary that fits
(a comma, a colon, a dash), falling back to the last whole word and, for
one word wider than the box, to characters. Everything shaved is marked
with " …", so a line that was cut never pretends to be finished, and a
line that was not never wears the mark.

NO LANGUAGE MODEL, EVER. This runs while a window is being painted, off
a store just read from the disk, and it has to give the same answer with
the network down and the app not running. It is pure stdlib and it does
no I/O.

Two rules keep the sentence splitter honest without a dictionary of
abbreviations:

* a full stop ends a sentence only when a SPACE or the end of the text
  follows it — so "12.5 s", "gpt-oss-120b" and "127.0.0.1" are never cut
  in half; and
* what it would end must be at least two words — so "1. " at the head of
  a numbered line, and an initial like "J. Smith", carry on into the
  sentence they belong to instead of becoming one.

Both were chosen over a list of abbreviations on purpose: Hebrew marks
its abbreviations with a gershayim (״) and its acronyms with a geresh
(׳), never with a full stop, so such a list would be a list of English
words in a Hebrew app. `׃` (sof pasuq) is in the stop set because it is
the one Hebrew mark that really does end a sentence.

Measured on this machine, 2026-09-07, over 100000 calls each: 21.9 µs for
a 258-character English report and 10.1 µs for an 87-character Hebrew
one. A pile of twelve rows costs a quarter of a millisecond, which is
why nothing here is cached and none of it needs to be.
"""
from __future__ import annotations

from typing import Callable, NamedTuple

# The marks that end a sentence: full stop, bang, question, the single
# ellipsis character, and the Hebrew sof pasuq.
STOPS = ".!?…׃"

# The marks that end a clause, in the order they are tried — which is to
# say, not in any order: the LAST one that fits is the cut, wherever it
# is. Em and en dash, and the Hebrew maqaf, are here because a dictated
# line often has one where an English one would have a comma.
CLAUSES = ",;:—–־-"

# What a cut line ends with. The same mark ui.clamp uses, so a cut looks
# the same whoever made it.
MARK = " …"


class Line(NamedTuple):
    """What `one_line` decided, and enough to say so on the screen.

    `whole` is true when the line IS the text — nothing at all was left
    behind, so a row can say "that is the whole report" honestly.
    `cut` is true only when the sentence itself had to be shaved, which
    is the only case where `text` ends in the mark. A first sentence out
    of five is neither whole nor cut: it is a whole sentence, and the row
    says the rest is elsewhere rather than drawing an ellipsis.
    """

    text: str
    whole: bool
    cut: bool


def sentences(text) -> list[str]:
    """`text` as whole sentences, whitespace already flattened.

    A line break inside a typed report is not a sentence boundary — he
    presses Enter mid-thought — so the text is flattened first and only
    the marks decide. Never returns an empty string as a member, and
    returns [] for nothing.
    """
    flat = " ".join(str(text or "").split())
    out: list[str] = []
    start = index = 0
    end_of = len(flat)
    while index < end_of:
        if flat[index] not in STOPS:
            index += 1
            continue
        # "?!" and "..." are one ending, not two or three.
        last = index
        while last + 1 < end_of and flat[last + 1] in STOPS:
            last += 1
        after = flat[last + 1] if last + 1 < end_of else " "
        piece = flat[start:last + 1].strip()
        if after == " " and len(piece.split()) >= 2:
            out.append(piece)
            start = index = last + 2       # the mark, then its one space
            continue
        index = last + 1
    tail = flat[start:].strip()
    if tail:
        out.append(tail)
    return out


def first_sentence(text) -> str:
    """The first whole sentence, or "" — the flattened text when it holds
    no sentence mark at all, which is what most typed reports are."""
    found = sentences(text)
    return found[0] if found else ""


def one_line(text, room: int = 90,
             measure: Callable[[str], int] | None = None) -> Line:
    """The first sentence of `text`, inside `room`.

    `room` and `measure` are in whatever unit the caller thinks in:
    characters by default, and pixels when the caller hands over a
    measuring function (`ui.text_width` bound to a face and a size). A
    row measures in pixels, because a row is as wide as it is and Hebrew
    at 12 pt is 5.9 px a character where Latin is 7.6 — a character
    budget would cut one of the two languages in the wrong place.
    """
    measure = measure or len
    flat = " ".join(str(text or "").split())
    if not flat:
        return Line("", True, False)
    head = first_sentence(flat)
    if measure(head) <= room:
        return Line(head, head == flat, False)
    return Line(_shaved(head, room, measure), False, True)


def _shaved(text: str, room: int, measure: Callable[[str], int]) -> str:
    """One sentence that is too long, cut at the best boundary that fits.

    The mark is part of what has to fit — a line cut to exactly the room
    and THEN given an ellipsis is a line one ellipsis too wide, which is
    how the old width cut came to draw over the button beside it.
    """
    def fits(piece: str) -> bool:
        return measure(piece + MARK) <= room

    breaks = [at for at, ch in enumerate(text)
              if ch in CLAUSES and at + 1 < len(text) and text[at + 1] == " "]
    for at in reversed(breaks):
        piece = text[:at].rstrip()
        if piece and fits(piece):
            return piece + MARK
    words = text.split(" ")
    while len(words) > 1:
        words.pop()
        piece = " ".join(words)
        if fits(piece):
            return piece + MARK
    # One word wider than the room. Shaving characters off it is the same
    # thing ui.clamp does silently; the mark is what stops it reading as
    # a misspelling ("balanced" -> "balance") rather than as a cut.
    piece = words[0] if words else ""
    while piece and not fits(piece):
        piece = piece[:-1]
    return (piece + MARK) if piece else ""
