"""What the shelf says, and how it is drawn.

THE SHELF is the small panel beside the status dot. It opens ONLY when a
key is pressed, the same key or Esc closes it, and it never opens on
hover — the owner's rule, and the whole reason it may be this tall: it is
never on screen unless he asked for it half a second ago.

Split the way every good-looking card in this repo is split (hint.py /
overlay.HintCard / skin\\hint.py; notify_card.py / overlay.NotifyCard /
skin\\notify.py; problem_card.py / answer_card.py / overlay.AnswerCard):
this half owns the WORDS, the GEOMETRY and the PICTURE — pure Python plus
Pillow, no Tk, no Win32, nothing that needs a screen — and the presenter
(shelf.ShelfCard) owns the thread, the queue, the window and every
decision.

WHAT IS ON IT, in this order and no other:

  1. THE STATE. A dot, one word for what the app is doing, and how long
     it has been up. Pause, and Stop. Stop ARMS on the first press and
     quits on the second (`stop_armed`): the door out of the app must not
     be one keystroke away from a live dictation, and there is no undo
     for a quit.
  2. THE PILE — one merged list of everything waiting for an answer:
     unread notifications, second-reading proposals, open problems,
     pending questions. ONE list, not four sections, because the question
     he is actually asking is "what wants me", and four headers is the
     dense home he rejected. Each row carries ITS OWN TWO ANSWERS, so the
     pile can be emptied without opening anything.
  3. THE LAST THING HE SAID, one right-to-left line, with Copy.
  4. SCREENS OFF, one row.
  5. ONE DOOR: "Open the desk".

  Never settings, never a key list, never history. Those are things you
  sit down to, and sitting down is what the window is for.

WHAT A ROW IS WORTH, MEASURED. review.json holds 5 pending proposals,
problems.json 2 open reports, questions.json 0 pending, notify.json 0
unread (2026-09-06). So the pile is normally 0-8 rows and occasionally
more after a night of notifications: it is capped at `max_rows`
(PILE_MAX by default, `[shelf] rows` in the live app) and the overflow
becomes one "+N more" row that opens the desk. A panel that can grow
without a ceiling is the "too many stuff" he already said no to.

THE ORDER IS NEWEST FIRST, one rule for all four sources — the order the
notification column already stacks in ("the first one will be at the
upper side and the oldest one will be on the down side", 2026-09-04).
Sorting is the CALLER's job, not this module's: it draws the list it is
handed, which is what lets a test hand it an order that could never
happen and see exactly what would be painted.

EVERY STRING IS ITS OWN IMAGE, and goes through visual_qa.text_pil —
DrawTextW + DT_RTLREADING, the one bidi path in this repo that was
checked glyph by glyph (popup.py). notify_card.py's reasoning applies
here word for word: a Hebrew title and a Latin label on one line come out
scrambled if they are concatenated, and `rtl` is decided per string by
its own first strong letter. The frame is English and left-aligned; what
he said, and what the app wants to say to him, is Hebrew and right-
aligned.

THE COLOURS ARE ONE TABLE (INK, below) AND IT IS READ FROM
skin\\palette.py BY NAME. Nothing else in this file names a colour, and
no hex in this file is a decision: the literals in `_INK_SOURCE` are the
values to draw with when `skin\\` HAS BEEN DELETED, which is the promise
that folder is built on (skin\\__init__.py) and the reason notify_card.py
spells its colours out. Reskinning is editing the palette; a name the
palette has lost falls back here, and `INK_FALLBACKS` names it so the
next person can see which ones did.
"""
from __future__ import annotations

import time
from datetime import datetime

from PIL import Image, ImageDraw

# Win32 hit-test answers, spelled out so this module needs no skin import.
HTTRANSPARENT, HTCLIENT, HTCAPTION = -1, 1, 2

# ---------------------------------------------------------------- THE TABLE
# name on this card -> (the names to try in skin\palette.py, in order, and
# the colour to draw with when none of them is there). The fallbacks are
# LAMPLIGHT, measured; they are what the panel looks like with skin\ gone.
_INK_SOURCE: dict[str, tuple[tuple[str, ...], str]] = {
    "ink":         (("FG",), "#f1ece2"),
    "dim":         (("DIM",), "#b2a896"),
    # rules and micro-labels only, never prose
    "faint":       (("FAINT",), "#7e7564"),
    "line":        (("LINE",), "#3a342a"),
    "ground":      (("BG",), "#14110c"),
    # the face the presenter paints, and a row's own plate one step over it
    "card":        (("CARD",), "#24201a"),
    "plate":       (("CARD_HI",), "#2e2921"),
    "plate_edge":  (("LINE_HI", "LINE"), "#4e4737"),
    "accent":      (("ACCENT",), "#e3a63c"),
    "accent_text": (("ACCENT_TEXT",), "#f0ba5c"),
    "accent_soft": (("ACCENT_SOFT",), "#332711"),
    "accent_edge": (("ACCENT_EDGE", "LINE_HI"), "#5a4520"),
    "on_accent":   (("ACCENT_ON",), "#1a1409"),
    "green":       (("GREEN",), "#63c88c"),
    "amber":       (("AMBER", "ACCENT"), "#e3a63c"),
    "red":         (("RED",), "#f1867a"),
    # the dot while the microphone is live, and while it is latched on
    "recording":   (("RECORDING", "RED"), "#ff5b4e"),
    "locked":      (("RECORDING", "RED"), "#ff8a7e"),
    "cool":        (("COOL", "TEAL"), "#8fc0f0"),
    "teal":        (("TEAL", "COOL"), "#8fc0f0"),
    "violet":      (("VIOLET", "ACCENT_TEXT"), "#c89ef7"),
}


def _hex(value: str) -> tuple[int, int, int]:
    value = str(value).lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def load_ink() -> tuple[dict, list]:
    """Read the table out of skin\\palette.py, and say what was missing.

    Returns (ink, fallbacks). A palette that has been reskinned answers
    for every name and `fallbacks` is empty; a palette that has lost one,
    or a `skin\\` folder that is not there at all, leaves the LAMPLIGHT
    literal above in its place and names it. Called once at import and
    again by `reink()`, so a test can prove the panel draws either way.

    The two recording states come out of `palette.DOT_STATES` when it has
    them — that map is where the status dot's own colours live, and the
    dot in the corner and the dot on this panel disagreeing about whether
    a recording is running is exactly the lie neither may tell.
    """
    ink: dict[str, tuple[int, int, int]] = {}
    missing: list[str] = []
    palette = None
    try:
        from skin import palette as palette_mod
        palette = palette_mod
    except Exception:
        palette = None
    for name, (candidates, default) in _INK_SOURCE.items():
        value = None
        for attr in candidates:
            got = getattr(palette, attr, None) if palette is not None else None
            if isinstance(got, str) and got.startswith("#"):
                value = _hex(got)
                break
        if value is None:
            value, _ = _hex(default), missing.append(name)
        ink[name] = value
    states = getattr(palette, "DOT_STATES", None) if palette is not None \
        else None
    if isinstance(states, dict):
        for name in ("recording", "locked"):
            got = states.get(name)
            fill = got[0] if isinstance(got, (tuple, list)) and got else None
            if isinstance(fill, str) and fill.startswith("#"):
                ink[name] = _hex(fill)
                if name in missing:
                    missing.remove(name)
    return ink, missing


def reink() -> None:
    """Read the palette again, in place. The presenter does not call this
    — a colour change is a restart — but a test that wants to see the
    fallback table can, and `INK` is the same object either way."""
    fresh, missing = load_ink()
    INK.clear()
    INK.update(fresh)
    INK_FALLBACKS[:] = missing


INK, INK_FALLBACKS = load_ink()

# The dot's colour per app state, and the pile's colour per kind. Both
# read out of the table above and nowhere else.
STATE_COLOUR = {"listening": "cool", "recording": "recording",
                "locked": "locked", "paused": "faint", "busy": "amber"}
STATE_WORD = {"listening": "Listening", "recording": "Recording",
              "locked": "Locked on", "paused": "Paused", "busy": "Working"}

# One colour and one word per thing that can be waiting. The four
# notification kinds keep notify_card.KIND_COLOUR's meanings, so a card
# and its row in the pile are the same colour.
KIND = {
    "done":     ("green",  "finished"),
    "input":    ("amber",  "needs you"),
    "error":    ("red",    "failed"),
    "info":     ("cool",   "note"),
    "review":   ("violet", "second reading"),
    "problem":  ("red",    "open problem"),
    "question": ("teal",   "question"),
}
FALLBACK_KIND = "info"
ELLIPSIS = "…"

# ------------------------------------------------------------- the numbers
CARD_W = 400              # the owner's "about 400"; the notify card is 360
SHADOW = 26               # the room a glass window leaves around the card
RADIUS = 22
PAD = 16
SCALE_MIN, SCALE_MAX = 0.6, 1.4

HEAD_H = 46               # the state row: dot, word, uptime, Pause, Stop
RULE_GAP = 12             # air on each side of a hairline
EYEBROW_H = 14            # a small all-caps section label
ROW_H = 56                # one pile row's plate: a header line and a
                          # sentence. TWO lines, never three — a row is a
                          # summons, not a reader
ROW_GAP = 8               # between plates. A gap, not a divider
MORE_H = 26               # the "+N more" row
EMPTY_H = 34              # the one line that stands in for an empty pile
LAST_H = 26               # the Hebrew line he last said
SCREENS_H = 34
DOOR_H = 46
BTN_H = 24                # a head button
ANSWER_H = 20             # a row's answer button
ANSWER_GAP = 6
PILE_MAX = 5              # rows shown; the rest become "+N more"
ROWS_MIN, ROWS_MAX = 1, 8  # what `[shelf] rows` may be set to

# What a hit landed on. The chrome's names are fixed strings; a pile row's
# are built by `row_name` so one scheme covers however many rows there are.
PAUSE, STOP, COPY, SCREENS, DOOR, MORE, DRAG = (
    "pause", "stop", "copy", "screens", "door", "more", "drag")
CHROME = (PAUSE, STOP, COPY, SCREENS, DOOR, MORE, DRAG)


def row_name(index: int, slot: str) -> str:
    """The region name for one answer on one row: "row3.a" / "row3.b"."""
    return f"row{int(index)}.{slot}"


def clamp_scale(scale: float) -> float:
    return max(SCALE_MIN, min(SCALE_MAX, round(float(scale), 3)))


def _is_rtl(text: str) -> bool:
    """Decided by the first strong letter, the way a bidi layout decides
    it — notify_card._is_rtl's rule, and settings.is_rtl's before that."""
    for ch in text or "":
        if "֐" <= ch <= "ࣿ":
            return True
        if ch.isalpha():
            return False
    return False


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------

def ago(at_iso: str, now: float | None = None) -> str:
    """How long ago, in the words a person uses. notify_card.ago's rule and
    its wording, so a notification says the same thing in both places."""
    try:
        at = datetime.fromisoformat(str(at_iso)).timestamp()
    except Exception:
        return ""
    stamp = time.time() if now is None else float(now)
    diff = stamp - at
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{int(diff // 60)} min ago"
    if diff < 86400:
        return f"{int(diff // 3600)} h ago"
    if diff < 2 * 86400:
        return "yesterday"
    when = datetime.fromtimestamp(at)
    return f"{when.day} {when.strftime('%b')}"


def uptime_words(seconds: float) -> str:
    """4h 32m, 12m, 40s. Never "0h 0m": an app that has been up for half a
    minute should say so rather than round itself away."""
    try:
        total = int(max(0.0, float(seconds)))
    except (TypeError, ValueError):
        return ""
    if total < 60:
        return f"up {total}s"
    if total < 3600:
        return f"up {total // 60}m"
    return f"up {total // 3600}h {(total % 3600) // 60:02d}m"


def card_for(state: dict, pile, last, screens_off: bool, *,
             max_rows: int = PILE_MAX, now: float | None = None) -> dict:
    """The whole shelf as data: what the presenter queues and every
    painter consumes.

    `state`   {"mode": listening|recording|locked|paused|busy,
               "uptime_s": float, "stop_armed": bool, "note": str}
              `note` is a short clause appended after the uptime — what
              main.py puts there is the length of a recording that is
              running, which is the one thing more useful than how long
              the app has been up while it is running.
    `pile`    the merged list, newest/most urgent first. Each item:
              {"kind": one of KIND, "id": ..., "text": one line,
               "at": ISO or "", "pill": the changed word or "",
               "answers": [(do, label), (do, label)]}
              `do` is a verb the presenter hands back untouched — this
              module never decides what an answer MEANS.
    `last`    the last dictation: a string, or {"text": ..., "at": ...}
    `screens_off`  whether the screens are dark right now

    Nothing is interpreted and nothing is looked up: every string arrives
    already cut and is DRAWN. That is what lets a test hand this a pile
    that could never happen and see exactly what would be painted.
    """
    mode = str((state or {}).get("mode") or "listening")
    if mode not in STATE_WORD:
        mode = "listening"
    rows = []
    for item in list(pile or [])[:max(0, int(max_rows))]:
        kind = str(item.get("kind") or FALLBACK_KIND)
        if kind not in KIND:
            kind = FALLBACK_KIND
        answers = [(str(d), str(l)) for d, l in
                   (item.get("answers") or [])][:2]
        rows.append({"kind": kind,
                     "colour": KIND[kind][0],
                     "word": KIND[kind][1],
                     "id": item.get("id"),
                     "text": str(item.get("text") or ""),
                     "pill": str(item.get("pill") or ""),
                     "when": ago(item.get("at") or "", now),
                     "answers": answers})
    more = max(0, len(list(pile or [])) - len(rows))
    if isinstance(last, dict):
        last_text = str(last.get("text") or "")
        last_when = ago(last.get("at") or "", now)
    else:
        last_text, last_when = str(last or ""), ""
    return {
        "mode": mode,
        "dot": STATE_COLOUR[mode],
        "title": STATE_WORD[mode],
        "uptime": " · ".join(
            p for p in (uptime_words((state or {}).get("uptime_s") or 0),
                        str((state or {}).get("note") or "").strip()) if p),
        "stop_armed": bool((state or {}).get("stop_armed")),
        # QUITTING IS REFUSED WHILE A RECORDING IS RUNNING, and the button
        # says so rather than disappearing. A button that vanishes leaves a
        # hole that clicks through to the desktop — and in this corner the
        # desktop is the close button of every maximised window (the trap
        # the status dot paid for once already). So the rectangle stays,
        # the word greys, and the press is refused OUT LOUD.
        "stop_ok": mode not in ("recording", "locked"),
        "waiting": len(list(pile or [])),
        "rows": rows,
        "more": more,
        # The two English words under an empty pile. Deliberately not
        # "0 waiting": a number is a score, and an empty shelf is good
        # news rather than a zero.
        "empty": "Nothing is waiting",
        "last": last_text,
        "last_when": last_when,
        "screens_off": bool(screens_off),
        "door": "Open the desk",
    }


# ---------------------------------------------------------------------------
# the picture: text
# ---------------------------------------------------------------------------

_text_pil = None


def _painter():
    global _text_pil
    if _text_pil is None:
        # Deferred, and deliberately not hoisted: importing visual_qa
        # pulls in the whole ask card, and this module is first reached
        # when the shelf key is pressed.
        from visual_qa import text_pil
        _text_pil = text_pil
    return _text_pil


def _text(cache: dict, text: str, pt: float, colour="ink", weight: int = 400,
          rtl: bool | None = None, width: int = 1400):
    """One line as an RGBA image, cropped to its glyphs.

    Cropped rather than trusted to a width, for skin\\hint.py's reason:
    text_pil's `pt` is scaled by the screen DPI, so any width guessed in
    points loses words on a 150% display. `colour` is a KEY INTO `INK`, so
    that a reskin is one table and not a search through the file.
    """
    if rtl is None:
        rtl = _is_rtl(text)
    key = (text, round(pt, 2), colour, weight, rtl, width)
    img = cache.get(key)
    if img is not None:
        return img
    img = _painter()(text or " ", max(20, int(width)), pt=pt,
                     colour=INK[colour], weight=weight, rtl=rtl, single=True)
    box = img.getchannel("A").getbbox()
    img = img.crop(box) if box else img
    cache[key] = img
    return img


def _fit(cache: dict, img, avail: float, rtl: bool, pt: float,
         colour: str = "dim"):
    """A line cut to `avail`, keeping the end that is read FIRST: the right
    of a Hebrew line, the left of a Latin one — notify_card._fit_line's
    rule, with an ellipsis painted on the cut end.

    The ellipsis is the whole difference and it is not decoration. A line
    cropped in silence ends mid-word and reads as a rendering bug; the
    body of a notification has said "…" at the cut for a year
    (notify_card._body) and this is the same promise for a single line.
    """
    if img.width <= avail:
        return img
    ell = _text(cache, ELLIPSIS, pt, colour=colour, rtl=False)
    w = max(1, int(avail))
    keep = max(1, w - ell.width - int(round(pt * 0.3)))
    # The dots sit ON the line, not under it. Both images are cropped to
    # their own glyphs, so aligning their bottoms puts an ellipsis whose
    # box is three dots high at the very bottom of a box that is a whole
    # Hebrew line high — which reads as a subscript. Lift it by a quarter
    # of the point size, which is where the baseline actually is.
    ey = max(0, img.height - ell.height - max(1, int(round(pt * 0.25))))
    out = Image.new("RGBA", (w, img.height), (0, 0, 0, 0))
    if rtl:
        out.alpha_composite(img.crop((img.width - keep, 0, img.width,
                                      img.height)), (w - keep, 0))
        out.alpha_composite(ell, (0, ey))
    else:
        out.alpha_composite(img.crop((0, 0, keep, img.height)), (0, 0))
        out.alpha_composite(ell, (w - ell.width, ey))
    return out


# ---------------------------------------------------------------------------
# the picture: shapes
# ---------------------------------------------------------------------------

def _rr(size, radius: float, fill=None, outline=None, width: float = 1.0,
        scale: int = 4):
    """An antialiased rounded rectangle, drawn at 4x and shrunk. Pillow
    antialiases no shape at all, and a rim at 1x is a staircase."""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    big = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, w * scale - 1, h * scale - 1),
                        radius=max(1, int(radius * scale)),
                        fill=fill, outline=outline,
                        width=max(1, int(round(width * scale))))
    return big.resize((w, h), Image.LANCZOS)


def _disc(cache: dict, size: float, colour, alpha: int = 255):
    key = ("disc", int(size), colour, alpha)
    got = cache.get(key)
    if got is not None:
        return got
    n, k = max(2, int(size)), 4
    big = Image.new("RGBA", (n * k, n * k), (0, 0, 0, 0))
    ImageDraw.Draw(big).ellipse((0, 0, n * k - 1, n * k - 1),
                                fill=tuple(INK[colour]) + (alpha,))
    got = big.resize((n, n), Image.LANCZOS)
    cache[key] = got
    return got


def _glyph(cache: dict, kind: str, size: float, colour="dim", weight=1.6):
    """One small line glyph, drawn at 4x and shrunk.

    `desk` is the mark the owner said he loves: a dalet drawn as a desk —
    the letter's top bar is the desk top, its right-hand leg is the desk's
    leg — with a lamp dot sitting on the bar.
    """
    key = ("glyph", kind, int(size), colour, round(weight, 2))
    got = cache.get(key)
    if got is not None:
        return got
    n, k = max(4, int(size)), 4
    m = n * k
    img = Image.new("RGBA", (m, m), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = tuple(INK[colour]) + (255,)
    lw = max(1, int(round(weight * k * n / 16)))
    if kind == "pause":
        d.rounded_rectangle((m * .30, m * .26, m * .42, m * .74), lw, fill=c)
        d.rounded_rectangle((m * .58, m * .26, m * .70, m * .74), lw, fill=c)
    elif kind == "play":
        d.polygon([(m * .34, m * .24), (m * .34, m * .76), (m * .74, m * .50)],
                  fill=c)
    elif kind == "stop":
        d.rounded_rectangle((m * .30, m * .30, m * .70, m * .70), lw * 1.5,
                            fill=c)
    elif kind == "copy":
        d.rounded_rectangle((m * .18, m * .12, m * .62, m * .66), m * .08,
                            outline=c, width=lw)
        d.rounded_rectangle((m * .36, m * .32, m * .82, m * .88), m * .08,
                            outline=c, width=lw)
    elif kind == "moon":
        # A FILLED crescent, cut out of a disc. An outlined one was drawn
        # first and read as the letter C at 14 px: the bite has to be
        # taken out of the shape, and an outline has nothing to take it
        # out of. Cut on its own layer, then composited, because
        # ImageDraw cannot erase.
        disc = Image.new("RGBA", (m, m), (0, 0, 0, 0))
        dd = ImageDraw.Draw(disc)
        dd.ellipse((m * .14, m * .14, m * .86, m * .86), fill=c)
        dd.ellipse((m * .34, m * .02, m * 1.10, m * .78), fill=(0, 0, 0, 0))
        img.alpha_composite(disc)
    elif kind == "chevron":
        d.line([(m * .40, m * .24), (m * .66, m * .50), (m * .40, m * .76)],
               fill=c, width=lw, joint="curve")
    elif kind == "desk":
        # ד as a desk: the bar, the leg, the lamp.
        d.line([(m * .16, m * .34), (m * .84, m * .34)], fill=c,
               width=int(lw * 1.4))
        d.line([(m * .68, m * .34), (m * .68, m * .86)], fill=c,
               width=int(lw * 1.4))
        d.ellipse((m * .24, m * .16, m * .40, m * .32),
                  fill=tuple(INK["accent"]) + (255,))
    got = img.resize((n, n), Image.LANCZOS)
    cache[key] = got
    return got


def _chip(cache: dict, label: str, pt: float, ink: str, fill: str,
          edge: str | None, pad_x: float, height: float, radius: float,
          weight: int = 700, rtl: bool | None = None, fill_a: int = 255,
          edge_a: int = 255):
    """A pill with a word in it, as one image. Every button on this card
    is one of these, so a button and a chip cannot drift apart."""
    text = _text(cache, label, pt, colour=ink, weight=weight, rtl=rtl)
    w = int(round(text.width + 2 * pad_x))
    h = int(round(height))
    img = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    img.alpha_composite(_rr((w, h), radius, fill=tuple(INK[fill]) + (fill_a,)))
    if edge:
        img.alpha_composite(_rr((w, h), radius, fill=None,
                                outline=tuple(INK[edge]) + (edge_a,), width=1))
    img.alpha_composite(text, (int((w - text.width) / 2),
                               int((h - text.height) / 2)))
    return img


def _answer_widths(cache: dict, row: dict, s: float) -> list:
    """How wide each of a row's two answers is. Measured, not fixed: "Open"
    and "Not now" are different words and a fixed width would either clip
    one or pad the other into a slab."""
    out = []
    for _do, label in row.get("answers") or []:
        text = _text(cache, label, 8.0 * s, colour="dim", weight=600,
                     rtl=False)
        out.append(int(round(text.width + 18 * s)))
    return out


# ---------------------------------------------------------------------------
# the geometry
#
# Every section's height is a constant, so `measure` is arithmetic and a
# test can assert the whole layout with no screen. The one thing that is
# NOT arithmetic is how wide a row's two answers are — that is text — so
# the widths are measured into a cache and `regions` takes the same cache
# the painter uses. A caller that has none gets its own, which costs one
# render of at most ten short Latin words.
# ---------------------------------------------------------------------------

def _sections(card: dict) -> list:
    """(name, height at scale 1.0) top to bottom, in the order drawn.

    One list, read by measure(), regions() and compose(), so the three can
    only ever agree. Adding a section is a line here.
    """
    out = [("head", HEAD_H), ("rule", 1), ("gap", RULE_GAP),
           ("eyebrow", EYEBROW_H), ("gap", 6)]
    rows = card.get("rows") or []
    if rows:
        for i, _row in enumerate(rows):
            out.append((f"row{i}", ROW_H))
            if i < len(rows) - 1:
                out.append(("gap", ROW_GAP))
        if int(card.get("more") or 0) > 0:
            out += [("gap", ROW_GAP), ("more", MORE_H)]
    else:
        out.append(("empty", EMPTY_H))
    out += [("gap", RULE_GAP), ("rule", 1), ("gap", RULE_GAP),
            ("lasthead", EYEBROW_H), ("gap", 6), ("last", LAST_H),
            ("gap", RULE_GAP), ("screens", SCREENS_H),
            ("gap", 10), ("door", DOOR_H)]
    return out


def measure(card: dict, scale: float = 1.0) -> tuple[int, int]:
    """The card's size at `scale`. Pure arithmetic."""
    s = clamp_scale(scale)
    h = 2 * PAD + sum(height for _n, height in _sections(card))
    return int(round(CARD_W * s)), int(round(h * s))


def _bands(card: dict, scale: float) -> dict:
    """name -> (top, height) in card coordinates, for every section."""
    s = clamp_scale(scale)
    out, y = {}, PAD * s
    for name, height in _sections(card):
        if name != "gap":
            out[name] = (y, height * s)
        y += height * s
    return out


def regions(card: dict, scale: float = 1.0,
            cache: dict | None = None) -> dict:
    """Every button and every row as a named rectangle, WINDOW-relative
    (the window is the card plus SHADOW on each side).

    Returned as data so a test can check that they are inside the card, do
    not overlap, and move with the scale — none of which needs a window, a
    screen or a mouse. The painter reads the same dictionary, which is
    what keeps a button pressed where it is drawn.
    """
    cache = cache if cache is not None else {}
    s = clamp_scale(scale)
    width, _height = measure(card, s)
    x0 = y0 = SHADOW
    pad = PAD * s
    left, right = x0 + pad, x0 + width - pad
    bands = _bands(card, s)
    out: dict = {}

    # -- the head: Stop then Pause, right to left along the row
    top, height = bands["head"]
    y = y0 + top + (height - BTN_H * s) / 2
    stop = _chip(cache, "Stop", 8.5 * s, "red", "card", "line", 11 * s,
                 BTN_H * s, 7 * s, weight=600, rtl=False)
    pause = _chip(cache, "Pause", 8.5 * s, "dim", "card", "line", 11 * s,
                  BTN_H * s, 7 * s, weight=600, rtl=False)
    # a glyph rides in front of each label; the box grows by its room
    glyph_room = 16 * s
    out[STOP] = (right - stop.width - glyph_room, y, right,
                 y + BTN_H * s)
    px = out[STOP][0] - 8 * s
    out[PAUSE] = (px - pause.width - glyph_room, y, px, y + BTN_H * s)

    # -- the pile. A row is a HEADER LINE and a SENTENCE. The header runs
    # right to left, which is the order it is read in: the kind's colour
    # and word, what it was, how long it has waited — and then, at the far
    # LEFT end, the two answers, because an action is the last thing you
    # reach for. `a` sits to the RIGHT of `b` for the same reason: it is
    # met first. The sentence underneath gets the WHOLE width, which is
    # what putting the buttons on the header line bought.
    for index, row in enumerate(card.get("rows") or []):
        top, _height = bands[f"row{index}"]
        widths = _answer_widths(cache, row, s)
        ay = y0 + top + 8 * s
        ax = left + 10 * s
        for slot, w in zip(("b", "a"), reversed(widths)):
            out[row_name(index, slot)] = (ax, ay, ax + w, ay + ANSWER_H * s)
            ax += w + ANSWER_GAP * s

    if "more" in bands:
        top, height = bands["more"]
        out[MORE] = (left, y0 + top, right, y0 + top + height)

    # -- Copy sits at the RIGHT end of the last line's eyebrow row, so
    # every all-caps section label on this card starts at the same left
    # edge and every control sits at the same right one.
    top, height = bands["lasthead"]
    copy = _chip(cache, "Copy", 7.5 * s, "dim", "card", "line", 9 * s,
                 18 * s, 6 * s, weight=600, rtl=False)
    box_w = copy.width + 14 * s
    out[COPY] = (right - box_w, y0 + top - 2 * s, right,
                 y0 + top - 2 * s + 18 * s)

    top, height = bands["screens"]
    out[SCREENS] = (left, y0 + top, right, y0 + top + height)
    top, height = bands["door"]
    out[DOOR] = (left, y0 + top, right, y0 + top + height)

    # The head strip drags the panel, exactly as the hint card's does —
    # but only the part of it that is not a button, which `hit_test`
    # settles by testing the buttons first.
    top, height = bands["head"]
    out[DRAG] = (x0, y0, x0 + width, y0 + top + height)
    return out


def _in(box, x, y) -> bool:
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def hit_test(card: dict, scale: float, x: int, y: int,
             cache: dict | None = None):
    """(HT code, what) for a point in window coordinates.

    Everything that is not a named rectangle is HTTRANSPARENT, which is
    what lets a click go through to the window underneath — the same rule
    the hint card and the notify column live by, and for the same reason:
    this thing sits in the top-right corner, where the close button of
    every maximised window is.
    """
    boxes = regions(card, scale, cache)
    for name, box in boxes.items():
        if name != DRAG and _in(box, x, y):
            return HTCLIENT, name
    if _in(boxes[DRAG], x, y):
        return HTCAPTION, DRAG
    return HTTRANSPARENT, None


def action_at(card: dict, name: str):
    """What a region name MEANS, resolved against the card that drew it.

    ("row", index, do, id) for one of a row's two answers, ("chrome",
    name) for everything else, None for a name this card never drew. The
    presenter forwards the verb; this module still decides nothing.
    """
    if not name:
        return None
    if name.startswith("row") and "." in name:
        head, slot = name.split(".", 1)
        try:
            index = int(head[3:])
        except ValueError:
            return None
        rows = card.get("rows") or []
        if not 0 <= index < len(rows):
            return None
        answers = rows[index].get("answers") or []
        pos = {"a": 0, "b": 1}.get(slot)
        if pos is None or pos >= len(answers):
            return None
        return ("row", index, answers[pos][0], rows[index].get("id"))
    if name in CHROME:
        return ("chrome", name)
    return None


# ---------------------------------------------------------------------------
# the picture
# ---------------------------------------------------------------------------

def compose(card: dict, scale: float = 1.0, hover: str | None = None,
            cache: dict | None = None):
    """The shelf's CONTENT as one RGBA image the size of measure(), on a
    TRANSPARENT ground — the face (glass, or the flat fallback) belongs to
    the presenter, exactly as notify_card.compose() hands its content to
    skin\\notify.py.

    `hover` is a region name; the thing under the pointer brightens.
    """
    cache = cache if cache is not None else {}
    s = clamp_scale(scale)
    width, height = measure(card, s)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pad = PAD * s
    left, right = pad, width - pad
    inner = right - left
    bands = _bands(card, s)
    boxes = regions(card, s, cache)

    def place(image, x, y):
        img.alpha_composite(image, (int(round(x)), int(round(y))))

    def button(name, label, ink, glyph=None, fill="card", edge="line"):
        """One head button, drawn inside the rectangle `regions` claimed
        for it — so a button can never be pressed anywhere but where it
        is painted."""
        x0, y0, x1, y1 = boxes[name]
        x0, y0, x1, y1 = x0 - SHADOW, y0 - SHADOW, x1 - SHADOW, y1 - SHADOW
        lit = hover == name
        plate = _rr((x1 - x0, y1 - y0), 7 * s,
                    fill=tuple(INK["plate" if lit else fill]) + (255, ),
                    outline=tuple(INK["line" if not lit else "plate_edge"])
                    + (255,), width=1)
        place(plate, x0, y0)
        text = _text(cache, label, 8.5 * s, colour=ink, weight=600, rtl=False)
        gx = x0 + 9 * s
        if glyph is not None:
            g = _glyph(cache, glyph, 12 * s, colour=ink)
            place(g, gx, y0 + ((y1 - y0) - g.height) / 2)
            gx += g.width + 5 * s
        place(text, gx, y0 + ((y1 - y0) - text.height) / 2)

    # ---- 1. the state -----------------------------------------------------
    top, band_h = bands["head"]
    dot = _disc(cache, 9 * s, card.get("dot") or "cool")
    place(dot, left + 1 * s, top + 6 * s)
    title = _text(cache, card.get("title") or "", 13.0 * s, colour="ink",
                  weight=700, rtl=False)
    place(title, left + 17 * s, top + 2 * s)
    sub = card.get("uptime") or ""
    if sub:
        sub_img = _text(cache, sub, 8.5 * s, colour="faint", rtl=False)
        place(sub_img, left + 17 * s, top + 22 * s)
    button(PAUSE, "Pause" if card.get("mode") != "paused" else "Resume",
           "dim", "pause" if card.get("mode") != "paused" else "play")
    # ARMED, not confirmed: the first press turns the word into a question
    # and the second one quits. There is no undo for a quit and this panel
    # opens with one keystroke.
    stop_ok = card.get("stop_ok", True)
    button(STOP,
           "Stop?" if (card.get("stop_armed") and stop_ok) else "Stop",
           ("red" if card.get("stop_armed") else "dim") if stop_ok
           else "faint", "stop")

    # ---- the hairlines ----------------------------------------------------
    # Walked off the sections list rather than off `bands`: there are two
    # rules on this card and `_bands` keeps one entry per NAME, so the map
    # would only ever remember the second one.
    y = pad
    for name, h in _sections(card):
        if name == "rule":
            place(_rr((inner, 1), 0, fill=tuple(INK["line"]) + (170,)),
                  left, y)
        y += h * s

    # ---- 2. the pile ------------------------------------------------------
    top, band_h = bands["eyebrow"]
    eyebrow = _text(cache, "WAITING FOR YOU", 7.5 * s, colour="faint",
                    weight=700, rtl=False)
    place(eyebrow, left, top + (band_h - eyebrow.height) / 2)
    waiting = int(card.get("waiting") or 0)
    if waiting:
        # A COUNT, NOT A LIGHT. The accent is the lamp and this panel has
        # exactly one lit thing on it — the door at the bottom — so the
        # badge that says how many are waiting is a plate with prose on
        # it. The rows underneath are what shouts.
        count = _chip(cache, str(waiting), 7.5 * s, "ink",
                      "plate", "plate_edge", 8 * s, 16 * s, 8 * s,
                      rtl=False)
        place(count, right - count.width, top + (band_h - count.height) / 2)

    for index, row in enumerate(card.get("rows") or []):
        top, band_h = bands[f"row{index}"]
        colour = row.get("colour") or "cool"
        lit = bool(hover and hover.startswith(f"row{index}."))
        plate = _rr((inner, band_h), 11 * s,
                    fill=tuple(INK["plate" if lit else "card"]) + (215,),
                    outline=tuple(INK["plate_edge"]) + (220,), width=1)
        place(plate, left, top)
        # the kind's colour as a 3 px bar down the RIGHT edge of the plate,
        # where a right-to-left eye starts the row
        place(_rr((3 * s, band_h - 16 * s), 1.5 * s,
                  fill=tuple(INK[colour]) + (235,)),
              right - 9 * s, top + 8 * s)

        # the header line: the kind, what it was, how long it has waited
        band = ANSWER_H * s
        ky = top + 8 * s
        word = _text(cache, row.get("word") or "", 7.5 * s, colour=colour,
                     weight=700, rtl=False)
        place(word, right - 16 * s - word.width,
              ky + (band - word.height) / 2)
        x_right = right - 16 * s - word.width - 8 * s
        pill = row.get("pill") or ""
        if pill:
            chip = _chip(cache, pill, 8.0 * s, "ink", "accent_soft",
                         "accent_edge", 7 * s, 17 * s, 5 * s, weight=600)
            place(chip, x_right - chip.width, ky + (band - chip.height) / 2)
            x_right -= chip.width + 8 * s
        when = row.get("when") or ""
        if when:
            w_img = _text(cache, when, 7.5 * s, colour="faint", rtl=False)
            place(w_img, x_right - w_img.width,
                  ky + (band - w_img.height) / 2)

        # the sentence, on its own line and across the whole plate
        room = inner - 26 * s
        text = row.get("text") or ""
        rtl = _is_rtl(text)
        t_img = _fit(cache, _text(cache, text, 10.0 * s, colour="ink"),
                     room, rtl, 10.0 * s)
        ty = top + 32 * s
        place(t_img, right - 16 * s - t_img.width if rtl else left + 10 * s,
              ty)

        # the two answers, at the far left of the header line
        for slot, (do, label) in zip(("a", "b"), row.get("answers") or []):
            name = row_name(index, slot)
            x0, y0, x1, y1 = (c - SHADOW for c in boxes[name])
            on = slot == "a"
            here = hover == name
            # THE FIRST ANSWER IS STRONGER, AND IT IS NOT GOLD. The accent
            # is the lamp: one lit thing per surface, and on this panel
            # that is the door at the bottom. Five gold buttons down a
            # pile would leave the door meaning nothing — so the primary
            # answer is a lifted plate with prose-weight text and the
            # second a quiet one, which is the same hierarchy without
            # spending the light on it five times.
            place(_rr((x1 - x0, y1 - y0), 6 * s,
                      fill=tuple(INK["plate" if on else "card"])
                      + (255 if here else 235 if on else 215,),
                      outline=tuple(INK["plate_edge" if on else "line"])
                      + (255,), width=1), x0, y0)
            lab = _text(cache, label, 8.0 * s,
                        colour="ink" if on else "dim",
                        weight=700 if on else 600, rtl=False)
            place(lab, x0 + ((x1 - x0) - lab.width) / 2,
                  y0 + ((y1 - y0) - lab.height) / 2)

    if int(card.get("more") or 0) > 0:
        top, band_h = bands["more"]
        lit = hover == MORE
        text = _text(cache, f"+{int(card['more'])} more on the desk",
                     8.5 * s, colour="accent_text" if lit else "dim",
                     rtl=False)
        place(text, left + 10 * s, top + (band_h - text.height) / 2)
        chev = _glyph(cache, "chevron", 11 * s,
                      colour="accent_text" if lit else "faint")
        place(chev, right - 10 * s - chev.width,
              top + (band_h - chev.height) / 2)

    if "empty" in bands:
        top, band_h = bands["empty"]
        text = _text(cache, card.get("empty") or "", 10.0 * s, colour="faint",
                     rtl=False)
        place(text, left + 2 * s, top + (band_h - text.height) / 2)

    # ---- 3. the last thing he said ----------------------------------------
    top, band_h = bands["lasthead"]
    head = _text(cache, "WHAT YOU SAID LAST", 7.5 * s, colour="faint",
                 weight=700, rtl=False)
    place(head, left, top + (band_h - head.height) / 2)
    button(COPY, "Copy", "dim", "copy")
    when = card.get("last_when") or ""
    if when:
        w_img = _text(cache, when, 7.5 * s, colour="faint", rtl=False)
        place(w_img, left + head.width + 10 * s,
              top + (band_h - w_img.height) / 2)
    top, band_h = bands["last"]
    line = card.get("last") or ""
    if line:
        l_img = _fit(cache, _text(cache, line, 11.0 * s, colour="ink",
                                  rtl=True), inner, True, 11.0 * s)
        place(l_img, right - l_img.width, top + (band_h - l_img.height) / 2)
    else:
        l_img = _text(cache, "nothing yet", 9.5 * s, colour="faint",
                      rtl=False)
        place(l_img, left, top + (band_h - l_img.height) / 2)

    # ---- 4. screens off ---------------------------------------------------
    top, band_h = bands["screens"]
    off = bool(card.get("screens_off"))
    lit = hover == SCREENS
    place(_rr((inner, band_h), 9 * s,
              fill=tuple(INK["plate" if lit else "card"]) + (200,),
              outline=tuple(INK["line"]) + (200,), width=1), left, top)
    moon = _glyph(cache, "moon", 14 * s, colour="amber" if off else "dim")
    place(moon, left + 11 * s, top + (band_h - moon.height) / 2)
    label = _text(cache, "Screens off", 9.5 * s,
                  colour="ink" if not off else "amber", rtl=False)
    place(label, left + 11 * s + moon.width + 9 * s,
          top + (band_h - label.height) / 2)
    state_chip = _chip(cache, "dark now" if off else "on", 7.5 * s,
                       "amber" if off else "faint",
                       "card", "line", 8 * s, 17 * s, 8 * s, rtl=False)
    place(state_chip, right - 10 * s - state_chip.width,
          top + (band_h - state_chip.height) / 2)

    # ---- 5. the door ------------------------------------------------------
    top, band_h = bands["door"]
    lit = hover == DOOR
    place(_rr((inner, band_h), 12 * s,
              fill=tuple(INK["accent_soft"]) + (255 if lit else 230,),
              outline=tuple(INK["accent_edge"]) + (255,), width=1),
          left, top)
    mark = _glyph(cache, "desk", 26 * s, colour="accent_text", weight=2.1)
    place(mark, left + 13 * s, top + (band_h - mark.height) / 2)
    door = _text(cache, card.get("door") or "", 11.0 * s,
                 colour="accent_text", weight=600, rtl=False)
    place(door, left + 13 * s + mark.width + 11 * s,
          top + (band_h - door.height) / 2 - 5 * s)
    hint = _text(cache, "history · keys · settings · everything else",
                 7.5 * s, colour="faint", rtl=False)
    place(hint, left + 13 * s + mark.width + 11 * s,
          top + (band_h - door.height) / 2 + 11 * s)
    chev = _glyph(cache, "chevron", 13 * s, colour="accent_text")
    place(chev, right - 12 * s - chev.width, top + (band_h - chev.height) / 2)
    return img


def flat(card: dict, scale: float = 1.0, hover: str | None = None,
         cache: dict | None = None):
    """The shelf on a solid face — what the Tk fallback shows when skin\\
    has been deleted: a rounded card in the fallback palette, the same
    content on top, no glass. Opaque on `card`, exactly as
    notify_card.flat() is opaque on CARD, and for the same reason: Tk has
    no per-pixel alpha, so the fallback is uglier and completely
    functional."""
    cache = cache if cache is not None else {}
    s = clamp_scale(scale)
    width, height = measure(card, s)
    face = Image.new("RGBA", (width, height), tuple(INK["card"]) + (255,))
    face.alpha_composite(_rr((width, height), RADIUS * s, fill=None,
                             outline=tuple(INK["line"]) + (255,), width=1))
    face.alpha_composite(compose(card, s, hover, cache))
    return face


__all__ = ["INK", "INK_FALLBACKS", "KIND", "STATE_WORD", "STATE_COLOUR",
           "load_ink", "reink", "ago", "uptime_words", "card_for",
           "measure", "regions", "hit_test", "action_at", "compose", "flat",
           "clamp_scale", "row_name", "CARD_W", "SHADOW", "PAD", "RADIUS",
           "PILE_MAX", "ROWS_MIN", "ROWS_MAX", "SCALE_MIN", "SCALE_MAX",
           "HTTRANSPARENT", "HTCLIENT", "HTCAPTION", "PAUSE", "STOP", "COPY",
           "SCREENS", "DOOR", "MORE", "DRAG", "CHROME"]
