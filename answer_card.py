"""What the question box says, and how it is drawn.

THE REPORT CARD IN REVERSE. problem_card.py asks him what is wrong and
takes a sentence; this one hands back a question the weekly read could not
answer on its own and takes a decision. Same two-file split every
good-looking card in this repo uses (hint.py / overlay.HintCard,
review_card.py / overlay.ReviewCard, problem_card.py /
overlay.ProblemCard): this half owns the WORDS, the GEOMETRY and the
PICTURE — pure Python plus Pillow, no Tk, no window, nothing that needs a
screen — and overlay.AnswerCard owns the thread, the Tk interpreter, the
keyboard and the mouse.

IT IMPORTS ITS SIBLING RATHER THAN COPYING IT. Every number the two cards
share — the width, the padding, the field's line height and interior room,
the button widths, the palette door, the four cached text renderers, the
antialiased rounded rectangle — is read straight out of problem_card, the
way dashboard.py reads FIELD_* out of it. Two copies of 420 disagree by
the first tweak, and the whole point of this card is that it and the
report card read as ONE FAMILY: he reports a problem in one box and
answers the question that came out of it in a box that looks like the
first one. Half the file below is therefore aliases, and that is the file
working, not the file being lazy. The private helpers (_ltr, _rtl_block,
_rr) are reached across the module boundary on purpose: they carry a
cache and a bidi contract that took a week to get right, and a second
copy of them here would be the second thing to fix every time.

WHAT IS ACTUALLY NEW HERE IS THE OPTIONS, and they are the primary
control, not a row of chips. The report card's kinds are one word each —
"wrong", "slow" — so they fit a horizontal strip of pills. These are
SENTENCES: the routine asks "should the review run before or after the
backup, or somewhere else?" and each option is a clause. So they stack
VERTICALLY, one full-width row each, and every row grows to fit its own
wrapped text. A horizontal strip would either clip the sentences or wrap
mid-clause into a shape nobody can scan, and a dropdown hides three
answers behind a click to save 120 px on a card that has the room.

HOW MANY ROWS IS THE QUESTION'S BUSINESS — two to five, whatever it
actually carries. A fixed three would make the routine invent a row to
fill a slot, and an invented option is worse than no option: it is a
plausible sentence he might pick, written by something that had nothing
to say. Every row on this card is a real choice.

AND THERE IS ALWAYS A TEXT BOX, at the same time as the rows, live from
the moment the card opens to the moment it closes. Never dimmed, never
disabled, never conditional; it belongs to no row and no row can take it
away.

A PICK AND A TYPED LINE ARE ONE ANSWER, not two competitors. His own case
for it, in his words: he picks "run before the backup" and then writes
"actually after the backup, so that it doesn't fight the disk" — the row
is the decision and the line is the condition on it. A card that made him
choose between the two would throw one half of the answer away every time
he had one. So both go out together (see the `on_done` contract in
overlay.AnswerCard) and Send is armed by a choice OR words OR both; only
both-empty leaves it unarmed, which is exactly what the store's `answer()`
refuses.

AND THERE IS NO "SOMETHING ELSE — I'LL WRITE" ROW. That was this card's
first shape and it was wrong three ways. It is a choice that is not a
choice: every other row names an answer and that one names a widget, so
scanning the list means reading four answers and one piece of furniture.
It costs a slot out of the few the card has, so a question with four real
answers had to drop one to keep the door open. And it made him PICK
BEFORE HE COULD TYPE — press four, then write — with the field dimmed and
its caret painted out until he did, which is a lock on the one control
that should never have needed a key. The field is always there and
nothing has to be pressed to reach it, so the row that used to announce
it has nothing left to say.

RIGHT-TO-LEFT WHERE IT MATTERS, LEFT-TO-RIGHT WHERE IT DOES NOT — the
report card's rule, and this card has far more Hebrew on it. The frame is
English and left-aligned (the eyebrow, the title, the hint, the keys line,
the field's caption, the button labels) and everything the routine wrote
or he writes back is Hebrew and right-aligned: the question block, the
option rows, the echo under the field. All of it goes through
visual_qa.text_pil, which is
DrawTextW + DT_RTLREADING — the one bidi path in this repo that was
checked glyph by glyph — reached here through problem_card's cached
wrappers. ui.draw_text is the same call with the same flags but hands back
a Tk PhotoImage bound to an interpreter, which is no use to a painter that
must also work with no Tk in the process at all.

AND THE ECHO LINE IS NOT OPTIONAL. Measured on both widgets 2026-09-04:
a tk.Entry and a tk.Text scramble a mixed Hebrew/English line in exactly
the same way — "הכפתור של Settings לא עובד אחרי restart" draws as
"restart לא עובד אחרי Settings הכפתור של". Every character is right and
what gets stored is right; only the drawing lies. So whatever is in the
field is echoed under it through the renderer that gets it right, and he
can read back his own answer before he sends it.
"""
from __future__ import annotations

import problem_card as pc
from PIL import Image, ImageDraw

# --- the report card's numbers, borrowed rather than re-typed -------------
# getattr with problem_card's own literals as fallbacks, exactly as
# dashboard.py does it: a tree where that module has been cut down still
# draws the field the owner approved rather than a guess at it.
CARD_W = getattr(pc, "CARD_W", 420)
PAD = getattr(pc, "PAD", 22)
INNER = getattr(pc, "INNER", CARD_W - 2 * PAD)

EYEBROW_Y = getattr(pc, "EYEBROW_Y", 0)
TITLE_Y = getattr(pc, "TITLE_Y", 16)
HINT_Y = getattr(pc, "HINT_Y", 44)

FIELD_RADIUS = getattr(pc, "FIELD_RADIUS", 9)
FIELD_PAD_X = getattr(pc, "FIELD_PAD_X", 12)
FIELD_PAD_Y = getattr(pc, "FIELD_PAD_Y", 9)
FIELD_FONT = getattr(pc, "FIELD_FONT", ("Rubik", 12))
FIELD_FONT_LINE = getattr(pc, "FIELD_FONT_LINE", 18)
FIELD_LINE_H = getattr(pc, "FIELD_LINE_H", 22)
# Two lines, not the report card's three. A report is a paragraph he is
# composing from nothing; this field is usually a clause he is adding to
# a row he already picked — "but only if the CPU is under 20%" — and it
# grows the moment he needs the room. The MAX is the same, because an
# answer may well be an explanation, and it is never less than two,
# because a one-line well under five full-width rows reads as an
# afterthought rather than as half the answer.
FIELD_LINES_MIN = 2
FIELD_LINES_MAX = getattr(pc, "FIELD_LINES_MAX", 8)

ECHO_PT = getattr(pc, "ECHO_PT", 10.0)
ECHO_GAP = getattr(pc, "ECHO_GAP", 8)
KEYS_PT = getattr(pc, "KEYS_PT", 8.0)
ACTS_GAP = getattr(pc, "ACTS_GAP", 16)
BTN_H = getattr(pc, "BTN_H", 36)
BTN_RADIUS = getattr(pc, "BTN_RADIUS", 9)
BTN_GAP = getattr(pc, "BTN_GAP", 8)
SEND_W = getattr(pc, "SEND_W", 104)
CANCEL_W = getattr(pc, "CANCEL_W", 96)

# --- what only this card has ---------------------------------------------
QUESTION_PT = 11.5        # the one thing on the card he must read
QUESTION_GAP = 13         # above the question panel
Q_PAD_X = 13
Q_PAD_Y = 11
Q_RADIUS = 10
Q_BAR = 3                 # the accent stripe down its leading (right) edge

OPTS_GAP = 14             # between the question and the first option
OPT_PT = 10.5
OPT_PAD_X = 12
OPT_PAD_Y = 10
OPT_GAP = 7
OPT_RADIUS = 10
BADGE = 20                # the numbered dot: what key picks this row
BADGE_GAP = 11
# The field is a PEER of the option rows, not the last row's body, so the
# gap above it is the gap that separates two things rather than the six
# pixels that joined one to another. There used to be a hairline tail from
# row four down into the well; it went with the row it came out of.
FIELD_GAP = 15
CAP_PT = 8.0              # the one line that says both at once is allowed
CAP_GAP = 6

HINT_PT = 8.0
TITLE_PT = 14.0

SEND, CANCEL, FIELD, CARD_REGION = (getattr(pc, "SEND", "send"),
                                    getattr(pc, "CANCEL", "cancel"),
                                    getattr(pc, "FIELD", "field"),
                                    getattr(pc, "CARD_REGION", "card"))
OPT_PREFIX = "opt:"

# The words. The frame is this card's own — the report card's hint is
# about the screenshot it attaches, which has nothing to do with a
# question — but the KEYS line is deliberately NOT built out of
# problem_card.KEYS with a string replace, and that is the interesting
# one: Esc on that card cancels a report that never existed, and Esc on
# THIS one leaves a question pending that the routine is still waiting on.
# A `.replace("Esc cancels", ...)` that silently misses after someone
# rewords the other card would ship a line telling him Escape cancels
# something it does not. The shared clauses are spelled out here and
# tests.py is the place to assert they still match.
SOURCE = "the weekly review"
TITLE = "One thing it could not decide"
HINT = ("It came out of the weekly read of your reports. Answer it and the "
        "routine picks the work back up where it stopped.")
# THE CAPTION IS THE PERMISSION SLIP. Without it a text box under a list
# of choices reads as the alternative to them — pick a row OR write, one
# of the two — which is the shape this card used to have and the shape
# the owner threw out. One faint English line above the well says the
# thing the geometry cannot: a row and a sentence together are one
# answer, and the sentence is allowed to argue with the row.
FIELD_CAP = "In your own words — add to a choice, or answer instead."
SEND_LABEL = getattr(pc, "SEND_LABEL", "Send")
CANCEL_LABEL = getattr(pc, "CANCEL_LABEL", "Cancel")

# questions.OPTIONS_MIN/MAX, spelled out for the reason overlay spells out
# problems.TEXT_MAX: this module is reached on a machine where the feature
# is off and questions.py may not import at all, and a card that will not
# draw because a feature module is missing is worse than a card with a
# number in it. IT IS A COPY AND COPIES DRIFT — the pair wants an
# assertion in tests.py, which this change does not own.
#
# FIVE, not four: the fourth slot used to be spent on the "something else
# — I'll write" row, and with that row gone the ceiling is about how many
# sentences fit on a card and stay scannable rather than about leaving
# room for a door. Two is still the floor — one option is not a question.
OPTIONS_MIN = 2
OPTIONS_MAX = 5
QUESTION_MAX = 400

hex_of = pc.hex_of
rgb = pc.rgb
_ltr = pc._ltr
_rtl = pc._rtl
_rtl_block = pc._rtl_block
_rr = pc._rr


def field_lines(text: str, per_line: int = 46) -> int:
    """How many lines the field should show for `text`, clamped to THIS
    card's two-to-eight rather than the report card's three-to-eight.

    problem_card.field_lines is the same guess with the other floor, and
    it is a guess knowingly: the real answer is what the Text widget
    wrapped it to, which only the window knows and which the window
    overwrites the moment there is one. This exists so a headless render
    of a long answer is the right height, and so the first paint — before
    the widget has ever been measured — is not two lines under a
    four-line sentence.
    """
    count = 0
    for para in (text or "").split("\n"):
        count += max(1, -(-len(para) // max(8, per_line)))
    return max(FIELD_LINES_MIN, min(FIELD_LINES_MAX, count))


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------

def card_for(item, *, typed: str = "", choice=None,
             lines: int = FIELD_LINES_MIN, focused: bool = False,
             hover: str | None = None) -> dict:
    """The whole card as data: what overlay.AnswerCard holds and every
    painter consumes.

    `item` is a questions.py item — the dict the store hands back, keys
    and all — or, for a headless render and for the tests, a bare
    question string, or a plain dict of `question`/`options`. Nothing in
    here reads questions.py: the store is the caller's business and this
    module has to draw on a machine where the feature was never turned
    on.

    `focused` opens FALSE, unlike the report card's. The options are the
    primary control here, so the card opens with the keyboard on the
    CARD — 1..N pick, Enter sends — and the caret goes into the field when
    he puts it there. `focused` says only where the keys are GOING; it
    never says whether the field is in play, because the field is always
    in play.
    """
    if isinstance(item, str):
        item = {"question": item}
    item = item if isinstance(item, dict) else {}
    question = str(item.get("question") or "").strip()[:QUESTION_MAX]
    # BLANKS ARE DROPPED AND NOTHING IS INVENTED TO REPLACE THEM. Every
    # row that survives is a real choice, so an item that arrived with
    # two options draws two rows and an item with none draws none — a
    # question with the field alone under it, which is still answerable
    # and still honest. Padding the list to some floor would put a
    # sentence on the card that nothing in the store ever said, and this
    # module is not allowed to write answers.
    options = [text for text in (str(row or "").strip()
                                 for row in (item.get("options") or ()))
               if text][:OPTIONS_MAX]
    picked = choice if isinstance(choice, int) and 0 <= choice < len(options) \
        else None
    return {"where": str(item.get("where") or "").strip() or SOURCE,
            "report_id": str(item.get("report_id") or "").strip(),
            "question": question, "options": tuple(options),
            "choice": picked, "typed": typed or "",
            "lines": max(FIELD_LINES_MIN, min(FIELD_LINES_MAX, int(lines))),
            "focused": bool(focused), "hover": hover}


def answerable(card: dict) -> bool:
    """Whether Send has anything to send, which is what lights it up.

    A CHOICE OR WORDS OR BOTH. Only both-empty is unarmed, and that is
    the store's `answer()` rule copied exactly rather than approximated:
    a button that arms where the store would refuse teaches him to press
    something that does nothing, and a button that stays dark where the
    store would accept hides an answer he already gave.

    There is deliberately no special case left in here. The old one — a
    pick on the last row needed words, because the last row was "something
    else, I'll write" and picking it without writing was a non-answer —
    went with that row. Every row now names a real answer, so a pick with
    nothing typed is a complete answer, and a sentence with nothing picked
    is a complete answer, and the two together are one answer with a
    condition on it.
    """
    return (card.get("choice") is not None
            or bool((card.get("typed") or "").strip()))


def eyebrow_of(card: dict) -> str:
    """"FROM THE WEEKLY REVIEW  ·  REPORT: 4F2A9C" — where the question
    came from, which is not something he fills in and not something he
    should have to remember.

    THE COLON IS LOAD-BEARING and it cost a zoomed screenshot to find
    out. Measured 2026-09-05 through visual_qa.text_pil at 8 pt: Rubik
    kerns a capital T against a following SPACE to zero width, so
    "REPORT 4F2A9C" draws as "REPORT4F2A9C" — every character present,
    the gap gone — while "ABC 123 DEF" is spaced correctly. Any ink
    between the T and the space breaks the pair, and a colon is the one
    that also reads as a label. If this line ever loses its colon it
    will lose its space with it.
    """
    text = "FROM " + (card.get("where") or SOURCE)
    rid = (card.get("report_id") or "")[:8]
    if rid:
        text += "  ·  REPORT: " + rid
    return text.upper()


def keys_of(card: dict) -> str:
    """The keys line, counting the options this card actually has.

    THE COUNT IS THE REAL COUNT. A card that names a key which does
    nothing is how a keyboard shortcut stops being trusted, so a
    two-option card says "1-2" and a five-option card says "1-5" and the
    digits bound in the window are the same range. A question that
    arrived with no options at all names no digits — there is nothing to
    press — and still names Enter and Esc, because those work on every
    card here.

    IT NO LONGER SAYS ANYTHING ABOUT WRITING YOUR OWN, and that is the
    keys line keeping up with the card rather than being tidied. There is
    no key that reaches the field: it is already live and the caret goes
    in it with a click. The old last clause — "4 writes your own" —
    described a row that had to be pressed before the field would take a
    word, and naming a key for a lock that is gone would be worse than
    saying nothing.

    "again un-picks" is on the line because un-picking is otherwise
    invisible: pressing the digit of the row he is on is the only way to
    get back to no choice at all, and a card whose only undo is
    undocumented is a card he answers wrong once and then distrusts.

    AND SHIFT+ENTER IS NOT ON IT, which is the one clause the report
    card has that this line does not. It is bound (see
    overlay.AnswerCard._run's `newline`) and measured 2026-09-05 at
    KEYS_PT through _ltr: with the digits clause already here, a fourth
    clause takes this block from 10 px to 23 — it wraps, at two options
    and at five — and a two-line keys paragraph costs more than an
    unnamed shortcut on a field that is usually one clause long. Three
    clauses is the budget; the digits earned the third.
    """
    count = len(card.get("options") or ())
    parts = []
    if count == 1:
        parts.append("1 picks, again un-picks")
    elif count > 1:
        parts.append("1-%d pick, again un-picks" % count)
    # Esc does NOT cancel here, and that is the one clause this card
    # could not borrow from the report card: an unanswered question stays
    # pending and the routine is still waiting on it, which is a
    # different promise from "the report you were writing is gone".
    return "  ·  ".join(parts + ["Enter sends", "Esc leaves it pending"])


# The widest line any real card shows — five options, which is the
# ceiling — and the one the tests and any second surface can compare
# against. Built by the same function rather than typed out beside it, so
# the two cannot drift.
KEYS = keys_of({"options": ("",) * OPTIONS_MAX})


# ---------------------------------------------------------------------------
# the geometry
# ---------------------------------------------------------------------------

def layout(card: dict, cache: dict | None = None) -> dict:
    """Every rectangle on the card, card-relative. Pure arithmetic plus
    the height of a few wrapped blocks.

    One function, read by the painter AND by the hit test, which is what
    keeps an option pressed where it is drawn — problem_card.layout's
    contract exactly, so overlay's two cards can share one set of
    bindings in shape if not in code.
    """
    cache = cache if cache is not None else {}
    hint_h = _ltr(cache, HINT, HINT_PT, rgb("FAINT"), INNER).height
    keys = _ltr(cache, keys_of(card), KEYS_PT, rgb("FAINT"), INNER)
    keys_box = (0, HINT_Y + hint_h + 7, INNER,
                HINT_Y + hint_h + 7 + keys.height)
    y = keys_box[3] + QUESTION_GAP

    # -- the question, in a panel of its own. It is up to 400 characters
    # of Hebrew and it is the whole reason the card is on screen, so it
    # gets the brightest ink and a ground one step off the card rather
    # than being a third grey line under the hint.
    q_w = INNER - 2 * Q_PAD_X - Q_BAR
    q_h = _rtl_block(cache, card.get("question") or " ", QUESTION_PT,
                     rgb("FG"), q_w).height
    question = (0, y, INNER, y + q_h + 2 * Q_PAD_Y)
    y = question[3] + OPTS_GAP

    # -- the options, stacked, however many there are. Every row is as
    # tall as its own sentence needs, which is why this loop exists at
    # all: a fixed row height either clips the long one or leaves the
    # short ones swimming. Two rows, five rows or none — the loop does
    # not care, and neither does the card's height, which is the whole
    # reason nothing here is a fixed offset.
    options = tuple(card.get("options") or ())
    text_w = INNER - 2 * OPT_PAD_X - BADGE - BADGE_GAP
    rows: dict[int, tuple[int, int, int, int]] = {}
    heights: dict[int, int] = {}
    for index, text in enumerate(options):
        block = _rtl_block(cache, text or " ", OPT_PT, rgb("DIM"), text_w)
        height = max(BADGE + 2 * OPT_PAD_Y, block.height + 2 * OPT_PAD_Y)
        rows[index] = (0, y, INNER, y + height)
        heights[index] = block.height
        y += height + OPT_GAP
    y -= OPT_GAP if options else 0

    # -- the field, its own thing under the rows rather than the last
    # row's body: its caption, its well, and the echo. The caption is
    # skipped when there are no rows at all — with nothing above it to
    # add to, "add to a choice, or answer instead" would be a line about
    # controls that are not on the card.
    lines = max(FIELD_LINES_MIN, min(FIELD_LINES_MAX,
                                     int(card.get("lines")
                                         or FIELD_LINES_MIN)))
    y += FIELD_GAP
    cap_h = _ltr(cache, FIELD_CAP, CAP_PT, rgb("FAINT"),
                 INNER).height if options else 0
    cap = (0, y, INNER, y + cap_h)
    y += cap_h + (CAP_GAP if cap_h else 0)
    field_h = lines * FIELD_LINE_H + 2 * FIELD_PAD_Y
    field = (0, y, INNER, y + field_h)
    y = field[3] + ECHO_GAP

    typed = (card.get("typed") or "").strip()
    echo_h = _rtl_block(cache, typed, ECHO_PT, rgb("DIM"),
                        INNER).height if typed else 0
    y += echo_h + (6 if echo_h else 0)

    y += ACTS_GAP
    send = (INNER - CANCEL_W - BTN_GAP - SEND_W, y,
            INNER - CANCEL_W - BTN_GAP, y + BTN_H)
    cancel = (INNER - CANCEL_W, y, INNER, y + BTN_H)
    return {"hint_h": hint_h, "keys": keys_box, "question": question,
            "q_width": q_w, "rows": rows, "text_w": text_w,
            "text_h": heights, "cap": cap, "field": field,
            "echo_h": echo_h, "send": send, "cancel": cancel,
            "size": (CARD_W, int(PAD + y + BTN_H + PAD))}


def measure(card: dict, cache: dict | None = None) -> tuple[int, int]:
    """The card's size in pixels."""
    return layout(card, cache)["size"]


def regions(card: dict, cache: dict | None = None) -> dict:
    """The rectangles that take the mouse, in CARD coordinates (the window
    is the card exactly — no shadow margin, like the report card's and
    unlike review_card's, because this one is a modal in the middle of the
    screen rather than a glass card in a corner)."""
    box = layout(card, cache)
    out = {SEND: _shift(box["send"]), CANCEL: _shift(box["cancel"]),
           FIELD: _shift(box["field"])}
    for index, rect in box["rows"].items():
        out[OPT_PREFIX + str(index)] = _shift(rect)
    out[CARD_REGION] = (0, 0, CARD_W, box["size"][1])
    return out


def _shift(rect) -> tuple[int, int, int, int]:
    """A body rectangle moved into card coordinates: the body sits at
    (PAD, PAD) and everything above is measured from its corner."""
    return (int(rect[0] + PAD), int(rect[1] + PAD),
            int(rect[2] + PAD), int(rect[3] + PAD))


def hit_test(card: dict, x: int, y: int, cache: dict | None = None):
    """What is under (x, y) in card coordinates, or None.

    A name from the region dict — "send", "cancel", "field" or
    "opt:<n>" — and pointedly NOT the card itself: a press that is not on
    a control is a press on the background, which this window turns into
    a drag. Clicks OUTSIDE the card are the window's business, not the
    painter's.
    """
    for name, box in regions(card, cache).items():
        if name == CARD_REGION:
            continue
        if box[0] <= x < box[2] and box[1] <= y < box[3]:
            return name
    return None


def option_at(name) -> int | None:
    """The row index in a region name, or None if it is not a row. One
    door, so the window never slices the prefix by hand."""
    if isinstance(name, str) and name.startswith(OPT_PREFIX):
        try:
            return int(name[len(OPT_PREFIX):])
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# the picture
# ---------------------------------------------------------------------------

def compose(card: dict, cache: dict | None = None):
    """The whole card as one opaque RGB image, ready to go on a Canvas.

    Opaque and flat to its own edges, not a rounded bitmap on a
    background: the rounding is the WINDOW's job (overlay._round_corners,
    DWM attribute 33, which clips the window itself and antialiases the
    clip against the real desktop) and a rounded face painted underneath
    would only draw a second, differently-curved edge inside the first.
    """
    cache = cache if cache is not None else {}
    box = layout(card, cache)
    width, height = box["size"]
    img = Image.new("RGB", (width, height), rgb("CARD"))

    def put(layer, x, y) -> None:
        spot = (int(PAD + x), int(PAD + y))
        if layer.mode == "RGBA":
            img.paste(layer, spot, layer)
        else:
            img.paste(layer, spot)

    put(_ltr(cache, eyebrow_of(card), 8.0, rgb("FAINT"), INNER), 0, EYEBROW_Y)
    put(_ltr(cache, TITLE, TITLE_PT, rgb("FG"), INNER, weight=700), 0, TITLE_Y)
    put(_ltr(cache, HINT, HINT_PT, rgb("FAINT"), INNER), 0, HINT_Y)
    # What the keys mean, on the card. With no title bar there is no X to
    # click and no menu to read, so the keyboard is the only way out that
    # is always there — and the digits are the fast path he asked for:
    # read, press one, Enter, and the routine wakes up.
    put(_ltr(cache, keys_of(card), KEYS_PT, rgb("FAINT"), INNER),
        0, box["keys"][1])

    # -- THE QUESTION. A panel one step brighter than the card, with the
    # accent down its RIGHT edge, which is where a Hebrew line starts:
    # the stripe marks the beginning of what he is reading, not the end
    # of it, and a left-edge bar on a right-aligned block points at the
    # ragged margin.
    qx0, qy0, qx1, qy1 = box["question"]
    put(_rr((qx1 - qx0, qy1 - qy0), Q_RADIUS, fill=rgb("CARD_HI") + (255,)),
        qx0, qy0)
    put(_rr((Q_BAR, qy1 - qy0 - 2 * Q_PAD_Y + 6), Q_BAR / 2,
            fill=rgb("ACCENT") + (255,)),
        qx1 - Q_PAD_X + 5, qy0 + Q_PAD_Y - 3)
    put(_rtl_block(cache, card.get("question") or " ", QUESTION_PT,
                   rgb("FG"), box["q_width"]),
        Q_PAD_X, qy0 + Q_PAD_Y)

    # -- THE OPTIONS, and they carry the weight the report card's chips
    # do not: a chip is one word you glance at, a row here is a sentence
    # you read and commit to. Full width, stacked, numbered on the left
    # where the number column lines up with the English frame, and the
    # Hebrew hard against the right margin where it belongs. Every row
    # drawn here is a real answer — there is no row for reaching the
    # field, because the field needs no reaching.
    picked = card.get("choice")
    hover = card.get("hover")
    options = tuple(card.get("options") or ())
    for index, text in enumerate(options):
        rx0, ry0, rx1, ry1 = box["rows"][index]
        on = index == picked
        hot = hover == OPT_PREFIX + str(index)
        if on:
            fill, edge, ink = (rgb("ACCENT_SOFT"), rgb("ACCENT_EDGE"),
                               rgb("ACCENT_TEXT"))
        elif hot:
            fill, edge, ink = rgb("CARD_HI"), rgb("STROKE"), rgb("FG")
        else:
            fill, edge, ink = rgb("CARD"), rgb("LINE"), rgb("DIM")
        put(_rr((rx1 - rx0, ry1 - ry0), OPT_RADIUS, fill=fill + (255,),
                outline=edge + (255,), width=1), rx0, ry0)
        # The badge IS the pick indicator, not a decoration beside one:
        # filled with the accent when this row is the answer, a hairline
        # ring when it is not. One element doing both jobs, so there is
        # never a lit dot beside an unlit row.
        mid = (ry0 + ry1) / 2
        bx = rx0 + OPT_PAD_X
        put(_rr((BADGE, BADGE), BADGE / 2,
                fill=(rgb("ACCENT") if on else fill) + (255,),
                outline=(rgb("ACCENT") if on else edge) + (255,), width=1),
            bx, mid - BADGE / 2)
        digit = _rtl(cache, str(index + 1), 8.5,
                     rgb("ACCENT_ON") if on else ink, weight=600)
        put(digit, bx + (BADGE - digit.width) / 2, mid - digit.height / 2)
        block = _rtl_block(cache, text or " ", OPT_PT, ink, box["text_w"])
        put(block, OPT_PAD_X + BADGE + BADGE_GAP, mid - block.height / 2)

    # -- THE FIELD, and it has TWO faces where it used to have three.
    # Lit accent when it has the caret, hairline when the keys are
    # elsewhere, and that is the whole list: the third face — flat
    # ground, LINE edge, faint ink, a caret painted the colour of the
    # thing behind it — said "what is in here is not part of the answer",
    # and nothing on this card is allowed to say that any more. It is
    # always the same well, always the same ground, always typeable, and
    # the border says only where the keyboard is pointing.
    fx0, fy0, fx1, fy1 = box["field"]
    if box["cap"][3] > box["cap"][1]:
        put(_ltr(cache, FIELD_CAP, CAP_PT, rgb("FAINT"), INNER),
            0, box["cap"][1])
    edge = rgb("ACCENT") if card.get("focused") else rgb("STROKE")
    put(_rr((fx1 - fx0, fy1 - fy0), FIELD_RADIUS, fill=rgb("EDGE") + (255,),
            outline=edge + (255,), width=1), fx0, fy0)

    # -- and this is what the field cannot do. See the module docstring:
    # both Tk text widgets scramble a mixed Hebrew/English line, so what
    # is in the field is echoed here through DrawTextW, which does not.
    # One ink, DIM, because there is no longer a state in which what he
    # wrote is out of play — and this line is where he reads back his own
    # sentence before pressing Send, so it is never the faint grey the
    # frame is written in.
    typed = (card.get("typed") or "").strip()
    if typed and box["echo_h"]:
        put(_rtl_block(cache, typed, ECHO_PT, rgb("DIM"), INNER),
            0, fy1 + ECHO_GAP)

    # -- the two answers. Send is NOT ARMED until there is something to
    # send (see `answerable`): the store would refuse the answer and he
    # would have pressed a button for nothing, which is a worse way to
    # learn the rule than a button that visibly is not ready. It arms on
    # a pick, on a typed word, or on both — which is the only pair of
    # states left, since either one alone is now a whole answer.
    sx0, sy0, sx1, sy1 = box["send"]
    armed = answerable(card)
    hot = hover == SEND
    if armed:
        # ON the gold fill the label is ACCENT_ON: 8.52:1, against the
        # 1.8:1 FG would give. The disarmed face keeps FAINT on EDGE.
        face = rgb("ACCENT_HI") if hot else rgb("ACCENT")
        outline, ink = None, rgb("ACCENT_ON")
    else:
        face, outline, ink = rgb("EDGE"), rgb("STROKE"), rgb("FAINT")
    put(_rr((sx1 - sx0, sy1 - sy0), BTN_RADIUS, fill=face + (255,),
            outline=(outline + (255,)) if outline else None, width=1),
        sx0, sy0)
    label = _rtl(cache, SEND_LABEL, 9.5, ink, weight=600)
    icon = 14
    total = icon + 8 + label.width
    ix = sx0 + (sx1 - sx0 - total) / 2
    _circle_tick(img, (int(PAD + ix), int(PAD + (sy0 + sy1) / 2)), icon, ink)
    put(label, ix + icon + 8, (sy0 + sy1) / 2 - label.height / 2)

    cx0, cy0, cx1, cy1 = box["cancel"]
    hot = hover == CANCEL
    put(_rr((cx1 - cx0, cy1 - cy0), BTN_RADIUS,
            fill=(rgb("EDGE_HI") if hot else rgb("EDGE")) + (255,),
            outline=rgb("STROKE") + (255,), width=1), cx0, cy0)
    label = _rtl(cache, CANCEL_LABEL, 9.5, rgb("DIM"), weight=600)
    put(label, cx0 + (cx1 - cx0 - label.width) / 2,
        cy0 + (cy1 - cy0 - label.height) / 2)
    return img


def _circle_tick(img, centre, size: int, colour) -> None:
    """A circled check, drawn rather than typed.

    The report card's Send carries problem_card._circle_x — ui.ICON's
    circled cross, because that button files a fault. This one gives an
    answer, so it carries the same circle with a tick in it: the pair
    reads as one family at a glance and still says two different things.
    Two primitives rather than a glyph for the same reason its sibling
    gives: ui.ICON is a Tk PhotoImage table, and U+2713 is at the mercy
    of whatever face DrawTextW picks. Supersampled 4x, like _rr.
    """
    k = 4
    span = size * k
    layer = Image.new("RGBA", (span, span), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse((k, k, span - k, span - k), outline=colour + (255,),
              width=max(1, int(1.4 * k)))
    d.line((span * 0.30, span * 0.52, span * 0.45, span * 0.68),
           fill=colour + (255,), width=max(1, int(1.3 * k)))
    d.line((span * 0.45, span * 0.68, span * 0.72, span * 0.34),
           fill=colour + (255,), width=max(1, int(1.3 * k)))
    layer = layer.resize((size, size), Image.LANCZOS)
    img.paste(layer, (int(centre[0]), int(centre[1] - size / 2)), layer)


__all__ = ["card_for", "answerable",
           "eyebrow_of", "field_lines", "layout", "measure", "regions",
           "hit_test", "option_at", "keys_of", "compose", "rgb", "hex_of",
           "CARD_W", "PAD", "INNER", "FIELD_LINE_H", "FIELD_FONT",
           "FIELD_FONT_LINE",
           "FIELD_PAD_X", "FIELD_PAD_Y", "FIELD_RADIUS", "FIELD_LINES_MIN",
           "FIELD_LINES_MAX", "SEND", "CANCEL", "FIELD", "CARD_REGION",
           "OPT_PREFIX", "TITLE", "HINT", "KEYS", "SOURCE", "FIELD_CAP",
           "SEND_LABEL", "CANCEL_LABEL", "OPTIONS_MIN", "OPTIONS_MAX",
           "QUESTION_MAX"]
