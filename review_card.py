"""What the second-reading card says, and how it is drawn.

Split the way the hint card is split (hint.py / overlay.HintCard /
skin\\hint.py): this half owns the WORDS and the PICTURE — pure Python
plus Pillow, no Tk, no window — and overlay.ReviewCard owns the thread,
the queue, the clock and the verdicts. The glass presenter (skin\\review.py)
and the flat Tk fallback both paint the same content image, so the card
reads identically with the skin folder deleted; only the face under it
changes.

THE ROW IS THE SENTENCE, NOT THE PAIR. Each proposal is drawn as the
sentence as it would read after the change — a few words either side,
the changed word on a pill — with the pasted form and the reason on a
small line beneath. That is the shape the owner asked for and the one a
person can answer at a glance: "מטוס -> מנטוס" is a puzzle, "הלכתי לאכול
[מנטוס] היום" is a sentence you either said or did not. A dropped tail
is the same row with the words struck through.

RIGHT-TO-LEFT, IN THREE PIECES. Every string goes through
visual_qa.text_pil (DrawTextW + DT_RTLREADING — the one bidi path in this
repo that was checked glyph by glyph), and a row is three separate
images laid out from the right edge leftwards: what is read BEFORE the
change sits to its RIGHT, what is read after it to its LEFT. The
context is trimmed word by word from the far ends until the three fit
the card, so a long dictation never wraps or clips — a row is always one
line, and the card never grows past three rows (the rest is counted).

Everything geometric is a function of the card dict and the scale, so
tests check the layout without a screen; `regions()` is what both the
painter and the hit test read, which is what keeps a button drawn where
it is pressed.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

# Win32 hit-test answers, spelled out so this module needs no skin import.
HTTRANSPARENT, HTCLIENT, HTCAPTION = -1, 1, 2

CARD_W = 400
RADIUS = 20
PAD = 16
HEAD_H = 40               # title and sub-line
BAR_H = 4                 # the clock under the head
ROW_H = 58                # one proposal: the sentence line and the note
MORE_H = 18               # "and N more in the dashboard"
BTN_H = 30
BTN_GAP = 8
SHADOW = 26               # room the glass window leaves around the card
SCALE_MIN, SCALE_MAX = 0.6, 1.4
MAX_ROWS = 3

ACCEPT, REJECT, LATER, DRAG = "accept", "reject", "later", "drag"
EDIT = "edit"             # a row's pencil is named "edit0", "edit1", ...
PENCIL_W = 22             # the pencil's own column at the left end of a row
PENCIL = "\u270e"          # ✎
VERDICT_OF = {ACCEPT: "accepted", REJECT: "rejected"}
BUTTONS = ((ACCEPT, 112), (REJECT, 92), (LATER, 104))   # name, width at 1.0

# skin\palette.py's values, spelled out: this module is reached with the
# skin folder deleted, and overlay.py keeps its fallback palette the same
# way. Tuples, because Pillow wants them.
INK = (232, 235, 243)
INK_DIM = (163, 171, 188)
INK_FAINT = (116, 125, 141)
LINE = (52, 58, 69)
EDGE = (36, 41, 50)
EDGE_HI = (46, 52, 64)
ACCENT = (29, 109, 212)
ACCENT_HI = (52, 130, 235)
ACCENT_SOFT = (18, 43, 78)
ACCENT_TEXT = (143, 190, 255)
RED = (248, 122, 125)
RED_SOFT = (74, 30, 36)
CARD = (31, 35, 45)

TITLE = "קריאה שנייה"
LABELS = {ACCEPT: "נכון", REJECT: "לא", LATER: "אחר כך"}
MORE = "ועוד {n} בדשבורד"
NOTE_INSTEAD = "במקום: {was}"
NOTE_DROP = "למחוק"
NOTE_HEARD_ONE = "גם פענוח נוסף שמע כך"
NOTE_HEARD = "גם {n} פענוחים שמעו כך"


def clamp_scale(scale: float) -> float:
    return max(SCALE_MIN, min(SCALE_MAX, round(float(scale), 3)))


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------

def card_for(suggestion: dict, *, seconds: float,
             keys=("V", "X", "L", "E"), max_rows: int = MAX_ROWS) -> dict:
    """The whole card as data: what overlay.ReviewCard queues and every
    painter consumes. `seconds` is how long the clock runs; 0 means the
    caller shows no card at all and this is only ever measured."""
    import review as review_mod

    text = suggestion.get("text", "")
    changes = list(suggestion.get("changes") or [])
    rows = [review_mod.snippet(text, c) for c in changes[:max_rows]]
    more = max(0, len(changes) - len(rows))
    n = len(changes)
    sub = "הצעה אחת" if n == 1 else f"{n} הצעות"
    return {"id": suggestion.get("id", ""),
            "title": TITLE, "sub": sub, "rows": rows, "more": more,
            "seconds": float(seconds),
            "keys": {ACCEPT: keys[0], REJECT: keys[1], LATER: keys[2],
                     EDIT: keys[3] if len(keys) > 3 else ""}}


def note_for(row: dict) -> str:
    """The small line under a sentence: the reason, what was pasted, and
    whether another decode heard it that way."""
    parts = [row.get("why", "").strip()] if row.get("why") else []
    if row.get("kind") == "drop":
        parts.insert(0, NOTE_DROP)
    else:
        parts.append(NOTE_INSTEAD.format(was=row.get("was", "")))
    support = int(row.get("support", 0))
    if support > 0 and row.get("kind") != "drop":
        parts.append(NOTE_HEARD_ONE if support == 1
                     else NOTE_HEARD.format(n=support))
    return " · ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# the geometry
# ---------------------------------------------------------------------------

def measure(card: dict, scale: float = 1.0) -> tuple[int, int]:
    """The card's size at `scale`. Pure arithmetic."""
    s = clamp_scale(scale)
    rows = len(card.get("rows") or [])
    h = PAD + HEAD_H + BAR_H + 10
    h += ROW_H * max(1, rows)
    if card.get("more"):
        h += MORE_H
    h += 10 + BTN_H + PAD
    return int(round(CARD_W * s)), int(round(h * s))


def regions(card: dict, scale: float = 1.0) -> dict:
    """The rectangles that take the mouse, window-relative (the window is
    the card plus SHADOW on every side). Buttons right to left along the
    bottom; everything else on the card is the handle you drag it by."""
    s = clamp_scale(scale)
    width, height = measure(card, s)
    x0 = y0 = SHADOW
    pad = PAD * s
    y1 = y0 + height - pad
    y_top = y1 - BTN_H * s
    x = x0 + width - pad
    out = {}
    for name, w in BUTTONS:
        bw = w * s
        out[name] = (x - bw, y_top, x, y1)
        x -= bw + BTN_GAP * s
    # a pencil at the left end of every row's sentence line
    y = y0 + (PAD + HEAD_H + BAR_H + 10) * s
    for i in range(len(card.get("rows") or [])):
        out[f"{EDIT}{i}"] = (x0 + pad, y + 2 * s, x0 + pad + PENCIL_W * s,
                             y + 30 * s)
        y += ROW_H * s
    out[DRAG] = (x0, y0, x0 + width, y0 + height)
    return out


def _in(box, x, y) -> bool:
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def hit_test(card: dict, scale: float, x: int, y: int):
    """(HT code, what) for a point in window coordinates: a button is a
    client hit, the rest of the card drags, the shadow margin is not
    ours at all."""
    boxes = regions(card, scale)
    for name, _w in BUTTONS:
        if _in(boxes[name], x, y):
            return HTCLIENT, name
    for name, box in boxes.items():
        if name.startswith(EDIT) and _in(box, x, y):
            return HTCLIENT, name
    if _in(boxes[DRAG], x, y):
        return HTCAPTION, DRAG
    return HTTRANSPARENT, None


# ---------------------------------------------------------------------------
# the picture
# ---------------------------------------------------------------------------

_text_pil = None


def _text(cache: dict, text: str, pt: float, colour=INK, weight: int = 400,
          rtl: bool = True):
    """One line as an RGBA image cropped to its glyphs — skin\\hint.py's
    recipe, with a cache the presenter owns (never module-level: the
    images belong to the card that is up)."""
    global _text_pil
    key = (text, round(pt, 2), colour, weight, rtl)
    img = cache.get(key)
    if img is not None:
        return img
    if _text_pil is None:
        # Deferred: importing visual_qa pulls in the whole ask card, and
        # this module is first reached in the middle of a dictation.
        from visual_qa import text_pil
        _text_pil = text_pil
    img = _text_pil(text or " ", 1400, pt=pt, colour=colour, weight=weight,
                    rtl=rtl, single=True)
    box = img.getchannel("A").getbbox()
    img = img.crop(box) if box else img
    cache[key] = img
    return img


def _rr(size, radius: float, fill=None, outline=None, width: float = 1.0,
        scale: int = 4):
    """An antialiased rounded rectangle layer, drawn big and shrunk."""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    big = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, w * scale - 1, h * scale - 1),
                        radius=max(1, int(radius * scale)),
                        fill=fill, outline=outline,
                        width=max(1, int(round(width * scale))))
    return big.resize((w, h), Image.LANCZOS)


def _fit(cache: dict, row: dict, avail: float, pt: float, s: float):
    """The three images of a sentence line, trimmed until they fit.

    The pill and the changed word are never trimmed; the contexts lose
    one word at a time from their FAR ends (the start of `right`, the end
    of `left`), the longer one first, and grow an ellipsis where they
    were cut."""
    word = _text(cache, row.get("word") or " ", pt, colour=(
        RED if row.get("kind") == "drop" else ACCENT_TEXT), weight=600)
    pill_w = word.width + 16 * s
    right_words = (row.get("right") or "").split()
    left_words = (row.get("left") or "").split()
    cut_r = cut_l = False
    gap = 8 * s

    def render():
        r = " ".join(right_words)
        lft = " ".join(left_words)
        if cut_r and r and not r.startswith("…"):
            r = "…" + r
        if cut_l and lft and not lft.endswith("…"):
            lft = lft + "…"
        ri = _text(cache, r, pt) if r else None
        li = _text(cache, lft, pt, colour=INK) if lft else None
        total = pill_w + (ri.width + gap if ri else 0) + (li.width + gap
                                                          if li else 0)
        return ri, li, total

    ri, li, total = render()
    while total > avail and (right_words or left_words):
        if len(right_words) >= len(left_words) and right_words:
            right_words.pop(0)
            cut_r = True
        else:
            left_words.pop()
            cut_l = True
        ri, li, total = render()
    return ri, word, li, pill_w


def compose(card: dict, scale: float = 1.0, progress: float = 1.0,
            hover: str | None = None, cache: dict | None = None):
    """The card's CONTENT as one RGBA image the size of measure(): text,
    clock, buttons — on a transparent ground. The face (glass or flat)
    is the presenter's; painting it here would bake one look into both.

    `progress` is the clock, 1.0 full to 0.0 spent; `hover` names the
    button under the pointer."""
    cache = cache if cache is not None else {}
    s = clamp_scale(scale)
    width, height = measure(card, s)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pad = PAD * s
    right = width - pad
    y = pad

    # -- head: title and count on the right
    title = _text(cache, card.get("title", TITLE), 12.0 * s, weight=600)
    img.alpha_composite(title, (int(right - title.width), int(y)))
    sub = _text(cache, card.get("sub", ""), 9.0 * s, colour=INK_DIM)
    img.alpha_composite(sub, (int(right - sub.width), int(y + 22 * s)))
    y += HEAD_H * s

    # -- the clock: a bar that empties towards the left
    bar_w = width - 2 * pad
    bar_h = max(2, int(round(BAR_H * s)))
    track = _rr((bar_w, bar_h), bar_h / 2, fill=LINE + (140,))
    img.alpha_composite(track, (int(pad), int(y)))
    left_w = int(round(bar_w * max(0.0, min(1.0, float(progress)))))
    if left_w > 0:
        fill = _rr((left_w, bar_h), bar_h / 2, fill=ACCENT + (255,))
        img.alpha_composite(fill, (int(right - left_w), int(y)))
    y += BAR_H * s + 10 * s

    # -- the rows
    rows = card.get("rows") or []
    pt = 11.0 * s
    avail = width - 2 * pad - (PENCIL_W + 8) * s
    for index, row in enumerate(rows):
        ri, word, li, pill_w = _fit(cache, row, avail, pt, s)
        line_h = max(word.height, ri.height if ri else 0,
                     li.height if li else 0) + 6 * s
        cy = y + line_h / 2
        # the pencil: type what the word should be
        pen = _text(cache, PENCIL, 12.0 * s, rtl=False,
                    colour=INK if hover == f"{EDIT}{index}" else INK_FAINT)
        img.alpha_composite(pen, (int(pad + (PENCIL_W * s - pen.width) / 2),
                                  int(cy - pen.height / 2)))
        x = right
        if ri is not None:
            img.alpha_composite(ri, (int(x - ri.width),
                                     int(cy - ri.height / 2)))
            x -= ri.width + 8 * s
        pill_h = word.height + 6 * s
        drop = row.get("kind") == "drop"
        pill = _rr((pill_w, pill_h), 7 * s,
                   fill=(RED_SOFT if drop else ACCENT_SOFT) + (230,),
                   outline=(RED if drop else ACCENT_TEXT) + (110,), width=1)
        img.alpha_composite(pill, (int(x - pill_w), int(cy - pill_h / 2)))
        img.alpha_composite(word, (int(x - pill_w + 8 * s),
                                   int(cy - word.height / 2)))
        if drop:
            # struck through: the words are the ones to go
            d = ImageDraw.Draw(img)
            d.line((int(x - pill_w + 6 * s), int(cy),
                    int(x - 6 * s), int(cy)),
                   fill=RED + (230,), width=max(1, int(round(2 * s))))
        x -= pill_w + 8 * s
        if li is not None:
            img.alpha_composite(li, (int(x - li.width),
                                     int(cy - li.height / 2)))
        y += line_h + 4 * s
        note = _text(cache, note_for(row), 8.5 * s, colour=INK_FAINT)
        if note.width > avail:
            note = note.crop((note.width - int(avail), 0, note.width,
                              note.height))
        img.alpha_composite(note, (int(right - note.width), int(y)))
        y += ROW_H * s - line_h - 4 * s
    if not rows:
        y += ROW_H * s
    if card.get("more"):
        more = _text(cache, MORE.format(n=card["more"]), 8.5 * s,
                     colour=INK_FAINT)
        img.alpha_composite(more, (int(right - more.width), int(y)))
        y += MORE_H * s

    # -- the buttons, from regions() so they are pressed where drawn
    boxes = regions(card, s)
    keys = card.get("keys") or {}
    for name, _w in BUTTONS:
        bx0, by0, bx1, by1 = boxes[name]
        bx0, by0, bx1, by1 = (bx0 - SHADOW, by0 - SHADOW,
                              bx1 - SHADOW, by1 - SHADOW)
        hot = hover == name
        if name == ACCEPT:
            face = _rr((bx1 - bx0, by1 - by0), 9 * s,
                       fill=(ACCENT_HI if hot else ACCENT) + (255,))
            colour = INK
        elif name == REJECT:
            face = _rr((bx1 - bx0, by1 - by0), 9 * s,
                       fill=(EDGE_HI if hot else EDGE) + (255,),
                       outline=LINE + (255,))
            colour = INK
        else:
            face = _rr((bx1 - bx0, by1 - by0), 9 * s,
                       fill=(EDGE + (120,)) if hot else None,
                       outline=LINE + (255,))
            colour = INK_DIM
        img.alpha_composite(face, (int(bx0), int(by0)))
        label = LABELS[name]
        key = keys.get(name, "")
        text = f"{label}  {key}" if key else label
        lab = _text(cache, text, 9.5 * s, colour=colour, weight=600)
        img.alpha_composite(lab, (int((bx0 + bx1) / 2 - lab.width / 2),
                                  int((by0 + by1) / 2 - lab.height / 2)))
    return img


def flat(card: dict, scale: float = 1.0, progress: float = 1.0,
         hover: str | None = None, cache: dict | None = None):
    """The card on a solid face — what the Tk fallback shows when the
    skin folder is gone: a rounded card in the fallback palette, the same
    content on top, no shadow, no glass. Opaque on CARD."""
    s = clamp_scale(scale)
    width, height = measure(card, s)
    face = Image.new("RGBA", (width, height), CARD + (255,))
    face.alpha_composite(_rr((width, height), RADIUS * s, fill=None,
                             outline=LINE + (255,), width=1))
    face.alpha_composite(compose(card, s, progress, hover, cache))
    return face


__all__ = ["card_for", "note_for", "measure", "regions", "hit_test",
           "compose", "flat", "clamp_scale", "SHADOW", "ACCEPT", "REJECT",
           "LATER", "EDIT", "DRAG", "VERDICT_OF", "BUTTONS"]
