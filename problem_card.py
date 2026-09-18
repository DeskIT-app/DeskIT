"""What the report box says, and how it is drawn.

The same two-file split the other good-looking cards in this repo use
(hint.py / overlay.HintCard, review_card.py / overlay.ReviewCard): this
half owns the WORDS, the GEOMETRY and the PICTURE — pure Python plus
Pillow, no Tk, no window, nothing that needs a screen — and
overlay.ProblemCard owns the thread, the Tk interpreter, the keyboard and
the mouse. Everything here can be rendered to a PNG and looked at without
opening a window, which is the whole reason the split exists: the card was
wrong for a week and nobody could see it was wrong without pressing the
hotkey.

WHY THERE IS A SECOND CARD AT ALL. dashboard._report already draws this
feature, and drawing it twice is a real cost. The alternative was worse:
the dashboard's card is built out of ui.Card, ui.Chip and ui.Button, which
are tk widgets placed in a Toplevel that is a CHILD OF THE DASHBOARD'S
INTERPRETER. The hotkey path has no dashboard — main.py may be running with
the window never opened — and a second Tk interpreter cannot borrow
widgets from the first. So the hotkey card is painted rather than
assembled, and the shared thing between the two surfaces is the LAYOUT AND
THE COPY, kept here where both can be read side by side. The strings below
are the dashboard's strings; if one changes, change both, and the tests
that compare them will say so.

RIGHT-TO-LEFT WHERE IT MATTERS, LEFT-TO-RIGHT WHERE IT DOES NOT. The card
is framed in English and left-aligned, exactly like the dashboard's — the
title, the hint, the caption, the button labels — and the one Hebrew thing
on it, the line he is writing, is right-aligned. Every string on this card
goes through visual_qa.text_pil, which is DrawTextW + DT_RTLREADING, the
one bidi path in this repo that was checked glyph by glyph. ui.draw_text is
the same call and the same flags, but it hands back a Tk PhotoImage bound
to an interpreter, which is no use to a painter that must also work with no
Tk at all; text_pil is the Pillow-shaped door onto the identical Windows
call, and it is what review_card.py uses for the same reason.

THE FIELD IS THE PART HE LOOKS AT. It was one 30 px line, the text jammed
against the border, and the owner's words for it were "very slop and
strict". So it is sized in LINES here (FIELD_LINES_MIN..FIELD_LINES_MAX)
rather than pixels, it starts at three and grows as he writes, and the card
grows under it — problems.TEXT_MAX is 600 characters and a field that
pretends the limit is forty is lying to him about what a report may be.
The window reports the wrapped line count back through the card dict, so
the geometry here stays a pure function of the data and the tests can walk
every height without a keyboard.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

CARD_W = 420
PAD = 22
RADIUS = 14
INNER = CARD_W - 2 * PAD

# The head: the "ON <WHERE>" eyebrow, the question, the hint under it.
EYEBROW_Y = 0
TITLE_Y = 16
HINT_Y = 44

FIELD_RADIUS = 9
FIELD_PAD_X = 12          # the interior breathing room the old one lacked
FIELD_PAD_Y = 9
FIELD_PT = 11.5
# One wrapped line in the Text widget the window lays over the field.
# Measured: Rubik at Tk size 12 has a linespace of 18 px, so the widget is
# given spacing3=FIELD_LINE_H-FIELD_FONT_LINE and the two agree to the
# pixel — which they must, because the painter draws the well from a LINE
# COUNT the widget reports and a well an inch short of its own text is
# how the old one came to look "strict".
FIELD_FONT = ("Rubik", 12)
FIELD_FONT_LINE = 18
FIELD_LINE_H = 22
FIELD_LINES_MIN = 3
FIELD_LINES_MAX = 8       # ~600 characters, which is problems.TEXT_MAX

ECHO_PT = 10.0
ECHO_GAP = 8
KEYS_PT = 8.0
CHIP_H = 30
CHIP_GAP = 8
CHIP_PAD = 26             # ui.Chip's own padding: width = CHIP_PAD + text
CHIPS_GAP = 14            # above the chip strip
SHOT_GAP = 12
SHOT_CAP_GAP = 16
ACTS_GAP = 16
BTN_H = 36
BTN_RADIUS = 9
BTN_GAP = 8
SEND_W = 104              # dashboard._report's ui.Button widths, to the pixel
CANCEL_W = 96

SEND, CANCEL, FIELD, CARD_REGION = "send", "cancel", "field", "card"
KIND_PREFIX = "kind:"
# The copy that travels (DISTRIBUTION_PLAN.md 7.6, screen 7; D16, D33).
# One checkbox under the chips — "Send to the developer", off — and,
# only while it is ticked, a strip of four toggles saying exactly what
# would leave this PC, each with its size. The primary button's label
# follows the checkbox: off, the report is kept here and the button
# says so; on, it says Preview, because nothing goes before he has
# seen the whole of it. `SEND` stays the primary button's region name
# on both surfaces whatever its label reads.
SEND_TOGGLE = "send_toggle"
ATTACH_PREFIX = "attach:"
ATTACH_ORDER = ("shot", "recording", "transcript", "settings")
# ui.Switch's pill, to the pixel (SWITCH_W, SWITCH_H, the knob's inset):
# a tick in a square box is the one thing this window's toolkit refuses
# to draw, and the desk's box uses the real ui.Switch in these rows.
SWITCH_W, SWITCH_H, KNOB_INSET = 46, 26, 4
ROW_H = 30                # one toggle row
STRIP_INDENT = SWITCH_W + 10   # the strip sits under the switch's label
STRIP_GAP = 8
CHECK_GAP = 14            # above the checkbox

# The dashboard's copy, verbatim except for one clause. Its hint opens
# with "One line." and this field is deliberately not one line any more,
# so that half of the sentence is gone and the keys line below says what
# replaced it. Everything else is the same words in the same order,
# because two surfaces of one feature that phrase it differently read as
# two features.
TITLE = "What is wrong?"
HINT = ("The screen you are on, the last dictation and the settings "
        "behind it are attached for you.")
KEYS = "Enter sends  ·  Shift+Enter for a new line  ·  Esc cancels"
# With Send ticked, Enter no longer files anything: it goes on to the
# Preview, and the line says so before he finds out by pressing it.
KEYS_SEND = "Enter continues  ·  Shift+Enter for a new line  ·  Esc cancels"
SHOT_CAPTION = ("The screen as it was a moment before this box opened. "
                "It goes with the report.")
SEND_LABEL = "Keep on this PC"
PREVIEW_LABEL = "Preview"
CANCEL_LABEL = "Cancel"
SEND_TOGGLE_LABEL = "Send to the developer"
STRIP_EYEBROW = "WHAT LEAVES THIS PC"
# The four toggles' words — problems.ATTACH_WORDS, spelled here as well
# so a painter with no problems module still draws them; a test keeps
# the two equal.
ATTACH_WORDS = {"shot": "Screenshot", "recording": "Recording",
                "transcript": "Transcript text",
                "settings": "Settings snapshot"}
NONE_WORD = "none"

# The palette, spelled out. Read lazily from `ui` when `ui` imports —
# so skin\palette.py's repaint reaches this card the way it reaches every
# other surface — and these values, which are ui.py's own literals, when
# it does not. A painter that must render with no Tk in the process cannot
# have `import ui` at the top of it (ui pulls in tkinter and ImageTk), and
# a card that cannot be rendered headless is a card nobody looks at until
# it is on screen and wrong. These are skin\palette.py's LAMPLIGHT
# values, which is what ui.py hands back once the skin has repainted it —
# so the headless card and the on-screen card are the same picture.
_FALLBACK = {"CARD": "#24201a", "CARD_HI": "#2e2921",
             "FG": "#f1ece2", "DIM": "#b2a896",
             "FAINT": "#7e7564", "LINE": "#3a342a", "STROKE": "#3a342a",
             "EDGE": "#29241d", "ACCENT": "#e3a63c", "ACCENT_HI": "#f0b854",
             "ACCENT_SOFT": "#332711", "ACCENT_TEXT": "#f0ba5c",
             "ACCENT_ON": "#1a1409",
             "ACCENT_EDGE": "#5a431a", "EDGE_HI": "#332d24",
             "CHIP_BG": "#292419", "TILE_EDGE": "#5a5240",
             "TRACK_OFF": "#4e4737"}


def hex_of(name: str) -> str:
    """One palette colour as ui.py spells it, for the Tk widgets the
    window lays over this card — the field is a real tk.Text and Tk takes
    "#rrggbb", not a triple."""
    try:
        import ui
        return str(getattr(ui, name))
    except Exception:                 # noqa: BLE001 — no Tk, no ui, no skin
        return _FALLBACK[name]


def rgb(name: str) -> tuple[int, int, int]:
    """One palette colour as a Pillow triple."""
    value = hex_of(name).lstrip("#")
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except (ValueError, IndexError):
        value = _FALLBACK[name].lstrip("#")
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------

def card_for(where: str, *, kinds=None, typed: str = "", kind: str = "",
             shot: bytes | str | None = None, lines: int = FIELD_LINES_MIN,
             focused: bool = True, hover: str | None = None,
             send: bool = False, attach: dict | None = None,
             sizes: dict | None = None) -> dict:
    """The whole card as data: what overlay.ProblemCard holds and every
    painter consumes.

    `where` is the eyebrow and is NOT something he fills in — the hotkey
    knows whether there is a fresh dictation to blame, the dashboard knows
    which tab he is on, and asking him would be asking him to type what
    the app already knows. `kinds` defaults to problems.KINDS so the two
    surfaces cannot drift; the default kind is the first of them, which
    the module orders as "wrong" first and "other" last on purpose.

    `send` is the checkbox; `attach` the four toggles (problems'
    defaults for the kind when not given); `sizes` the bytes behind
    each, 0 for a piece the report does not have — its toggle draws
    greyed and cannot be ticked.
    """
    if kinds is None:
        try:
            import problems
            kinds = tuple(getattr(problems, "KINDS", ()) or ())
        except Exception:             # noqa: BLE001 — reporting may be off
            kinds = ()
        kinds = kinds or ("wrong",)
    kinds = tuple(kinds)
    picked = kind if kind in kinds else kinds[0]
    return {"where": str(where or "").strip(), "kinds": kinds,
            "kind": picked,
            "typed": typed or "", "shot": shot,
            "lines": max(FIELD_LINES_MIN, min(FIELD_LINES_MAX, int(lines))),
            "focused": bool(focused), "hover": hover,
            "send": bool(send),
            "attach": attach_for(picked, attach),
            "sizes": {name: max(0, int((sizes or {}).get(name) or 0))
                      for name in ATTACH_ORDER}}


def attach_for(kind: str, attach: dict | None = None) -> dict:
    """The four toggles as booleans: what was handed in, else problems'
    defaults for the kind, else (no problems module) settings only."""
    if isinstance(attach, dict):
        return {name: bool(attach.get(name)) for name in ATTACH_ORDER}
    try:
        import problems
        got = problems.attach_defaults(kind)
    except Exception:                 # noqa: BLE001
        got = {"settings": True, "transcript": kind == "wrong"}
    return {name: bool(got.get(name)) for name in ATTACH_ORDER}


def size_word(n: int) -> str:
    """"214 KB", "1.1 MB", "0.4 KB" — or NONE_WORD for a piece that is
    not there."""
    n = int(n or 0)
    if n <= 0:
        return NONE_WORD
    if n >= 1000 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 10 * 1024:
        return f"{n // 1024} KB"
    return f"{n / 1024:.1f} KB"


def field_lines(text: str, per_line: int = 46) -> int:
    """How many lines the field should show for `text`, clamped.

    A guess, and knowingly one: the real answer is what the Text widget
    wrapped it to, which only the window knows, and the window overwrites
    this the moment there is one. It exists so a headless render of a long
    report is the right height, and so the first paint — before the widget
    has ever been measured — is not three lines under a five-line
    sentence.
    """
    count = 0
    for para in (text or "").split("\n"):
        count += max(1, -(-len(para) // max(8, per_line)))
    return max(FIELD_LINES_MIN, min(FIELD_LINES_MAX, count))


# ---------------------------------------------------------------------------
# the geometry
# ---------------------------------------------------------------------------

def _chip_w(cache: dict, name: str) -> int:
    return int(CHIP_PAD + _rtl(cache, name, 9.0, rgb("DIM")).width)


def _wrap(widths, avail: int):
    """(x, y) for each chip, wrapping into rows CHIP_H tall.

    ui.Chip is as wide as its own word and KINDS has five of them, so the
    strip's height is not known until they are measured — same arithmetic
    dashboard._report does with ui._wrap, kept here because this half owns
    the geometry and a sixth kind must grow the card on both surfaces.
    """
    spots, x, y = [], 0, 0
    for w in widths:
        if x and x + w > avail:
            x, y = 0, y + CHIP_H + CHIP_GAP
        spots.append((x, y))
        x += w + CHIP_GAP
    return spots


def layout(card: dict, cache: dict | None = None) -> dict:
    """Every rectangle on the card, card-relative. Pure arithmetic plus
    the width of five short words.

    One function, read by the painter AND by the hit test, which is what
    keeps a chip pressed where it is drawn. `hint_h`, `echo_h` and the
    chip widths are the only measured parts; everything else falls out of
    them.
    """
    cache = cache if cache is not None else {}
    send = bool(card.get("send"))
    hint = _ltr(cache, HINT, 8.0, rgb("FAINT"), INNER)
    hint_h = hint.height
    # The keys line goes HERE, above the field, and not on the empty half
    # of the button row where it was first put: at 8 pt it is 300 px of
    # sentence and the gap beside Send and Cancel is 144, so it ran
    # underneath the buttons. Above the field it has the card's whole
    # width, and it reads in the right order — what the box is for, what
    # gets attached, how to answer, then the place to answer.
    keys = _ltr(cache, KEYS_SEND if send else KEYS, KEYS_PT, rgb("FAINT"),
                INNER)
    keys_box = (0, HINT_Y + hint_h + 7, INNER,
                HINT_Y + hint_h + 7 + keys.height)
    y = keys_box[3] + 12

    lines = max(FIELD_LINES_MIN, min(FIELD_LINES_MAX,
                                     int(card.get("lines") or
                                         FIELD_LINES_MIN)))
    field_h = lines * FIELD_LINE_H + 2 * FIELD_PAD_Y
    field = (0, y, INNER, y + field_h)
    y += field_h + ECHO_GAP

    typed = (card.get("typed") or "").strip()
    echo_h = _rtl_block(cache, typed, ECHO_PT, rgb("DIM"),
                        INNER).height if typed else 0
    y += echo_h + (6 if echo_h else 0)

    y += CHIPS_GAP
    kinds = tuple(card.get("kinds") or ("wrong",))
    widths = [_chip_w(cache, name) for name in kinds]
    spots = _wrap(widths, INNER)
    chips = {name: (x, y + dy, x + w, y + dy + CHIP_H)
             for name, w, (x, dy) in zip(kinds, widths, spots)}
    y += (spots[-1][1] + CHIP_H) if spots else 0

    shot = _shot_image(card.get("shot"))
    if shot is not None:
        y += SHOT_GAP
        shot_box = (0, y, shot.width + 2, y + shot.height + 2)
        y = shot_box[3]
    else:
        shot_box = None

    # -- the checkbox, and under it — only while it is ticked — the strip
    # of what would leave. Each toggle row is the card's whole width so
    # the word is as pressable as the square.
    y += CHECK_GAP
    check = (0, y, INNER, y + ROW_H)
    y += ROW_H
    strip_head = None
    attach_rows: dict[str, tuple] = {}
    if send:
        y += STRIP_GAP
        eyebrow = _ltr(cache, STRIP_EYEBROW, 8.0, rgb("FAINT"),
                       INNER - STRIP_INDENT)
        strip_head = (STRIP_INDENT, y, INNER, y + eyebrow.height)
        y += eyebrow.height + 6
        for name in ATTACH_ORDER:
            attach_rows[name] = (STRIP_INDENT, y, INNER, y + ROW_H)
            y += ROW_H

    y += ACTS_GAP
    # The primary button is as wide as its word needs — "Keep on this
    # PC" is longer than "Send" was — and never narrower than the
    # dashboard's 104.
    label = _rtl(cache, PREVIEW_LABEL if send else SEND_LABEL, 9.5,
                 rgb("ACCENT_ON"), weight=600)
    primary_w = max(SEND_W, label.width + 14 + 8 + 2 * 16)
    send_box = (INNER - CANCEL_W - BTN_GAP - primary_w, y,
                INNER - CANCEL_W - BTN_GAP, y + BTN_H)
    cancel = (INNER - CANCEL_W, y, INNER, y + BTN_H)
    height = PAD + y + BTN_H + PAD
    return {"hint_h": hint_h, "keys": keys_box, "field": field,
            "echo_h": echo_h, "chips": chips, "shot": shot_box,
            "shot_image": shot, "check": check, "strip_head": strip_head,
            "attach": attach_rows, "send": send_box, "cancel": cancel,
            "size": (CARD_W, int(height))}


def measure(card: dict, cache: dict | None = None) -> tuple[int, int]:
    """The card's size in pixels."""
    return layout(card, cache)["size"]


def regions(card: dict, cache: dict | None = None) -> dict:
    """The rectangles that take the mouse, in CARD coordinates (the window
    is the card exactly — no shadow margin, unlike review_card's, because
    this one is a modal in the middle of the screen rather than a glass
    card in a corner)."""
    box = layout(card, cache)
    out = {SEND: _shift(box["send"]), CANCEL: _shift(box["cancel"]),
           FIELD: _shift(box["field"]), SEND_TOGGLE: _shift(box["check"])}
    for name, rect in box["chips"].items():
        out[KIND_PREFIX + name] = _shift(rect)
    for name, rect in box["attach"].items():
        out[ATTACH_PREFIX + name] = _shift(rect)
    out[CARD_REGION] = (0, 0, CARD_W, box["size"][1])
    return out


def _shift(rect) -> tuple[int, int, int, int]:
    """A body rectangle moved into card coordinates: the body sits at
    (PAD, PAD) and everything above is measured from its corner."""
    return (int(rect[0] + PAD), int(rect[1] + PAD),
            int(rect[2] + PAD), int(rect[3] + PAD))


def hit_test(card: dict, x: int, y: int, cache: dict | None = None):
    """What is under (x, y) in card coordinates, or None.

    A name from the region dict — "send", "cancel", "field", or
    "kind:<name>" — and pointedly NOT the card itself: this window takes
    the keyboard and is dragged by nothing, so a press that is not on a
    control is a press on the background and means nothing. Clicks
    OUTSIDE the card are the window's business, not the painter's.
    """
    for name, box in regions(card, cache).items():
        if name == CARD_REGION:
            continue
        if box[0] <= x < box[2] and box[1] <= y < box[3]:
            return name
    return None


# ---------------------------------------------------------------------------
# the picture
# ---------------------------------------------------------------------------

_text_pil = None


def _pil():
    global _text_pil
    if _text_pil is None:
        # Deferred, like review_card's: importing visual_qa pulls the whole
        # ask card in, and this module is first reached on a hotkey press
        # in the middle of whatever he was doing.
        from visual_qa import text_pil
        _text_pil = text_pil
    return _text_pil


def _raw(cache: dict, text: str, pt: float, colour, width: int, weight: int,
         rtl: bool, single: bool):
    key = (text, round(pt, 2), tuple(colour), width, weight, rtl, single)
    img = cache.get(key)
    if img is None:
        img = _pil()(text or " ", max(20, int(width)), pt=pt, colour=colour,
                     weight=weight, rtl=rtl, single=single)
        cache[key] = img
    return img


def _rtl(cache: dict, text: str, pt: float, colour, weight: int = 400):
    """One short line cropped tight to its glyphs, to be placed by an
    edge. Used for anything measured — a chip's word, a button's label."""
    key = ("tight", text, round(pt, 2), tuple(colour), weight)
    img = cache.get(key)
    if img is not None:
        return img
    img = _raw(cache, text, pt, colour, 1400, weight, True, True)
    box = img.getchannel("A").getbbox()
    img = img.crop(box) if box else img
    cache[key] = img
    return img


def _ltr(cache: dict, text: str, pt: float, colour, width: int,
         weight: int = 400):
    """An English block, wrapped to `width`, LEFT-aligned and KEPT at that
    width. Cropped vertically only: a horizontal crop would pull the block
    off the left margin every other paint, because where its bbox starts
    depends on which letter happens to begin the widest line."""
    key = ("ltr", text, round(pt, 2), tuple(colour), width, weight)
    img = cache.get(key)
    if img is not None:
        return img
    img = _raw(cache, text, pt, colour, width, weight, False, False)
    box = img.getchannel("A").getbbox()
    if box:
        img = img.crop((0, box[1], img.width, box[3]))
    cache[key] = img
    return img


def _rtl_block(cache: dict, text: str, pt: float, colour, width: int,
               weight: int = 400):
    """A Hebrew block, wrapped to `width` and RIGHT-aligned inside it —
    text_pil's own DT_RIGHT does the alignment, so the image is placed at
    the left margin and the words end up against the right one. Vertical
    crop only, for the same reason as _ltr."""
    key = ("rtlb", text, round(pt, 2), tuple(colour), width, weight)
    img = cache.get(key)
    if img is not None:
        return img
    img = _raw(cache, text, pt, colour, width, weight, True, False)
    box = img.getchannel("A").getbbox()
    if box:
        img = img.crop((0, box[1], img.width, box[3]))
    cache[key] = img
    return img


def _rr(size, radius: float, fill=None, outline=None, width: float = 1.0,
        scale: int = 4):
    """An antialiased rounded rectangle, drawn big and shrunk —
    review_card._rr exactly, because Pillow's own rounded_rectangle has no
    antialiasing and a 15 px chip radius shows every stair."""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    big = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, w * scale - 1, h * scale - 1),
                        radius=max(1, int(radius * scale)),
                        fill=fill, outline=outline,
                        width=max(1, int(round(width * scale))))
    return big.resize((w, h), Image.LANCZOS)


_shot_cache: dict = {}


def _shot_image(shot):
    """The attached screenshot as a Pillow thumbnail, or None.

    Takes BYTES or a PATH, and the two go different ways on purpose. The
    hotkey path already holds the screen as JPEG bytes — main.py grabs it
    before this box exists, or the report would be a photograph of the
    question — and those bytes have not been filed anywhere: he may still
    press Escape, and problems.pin_shot writes what it is handed, so a
    cancelled report must leave nothing on disk. dashboard._shot_photo has
    to write a temp file and unlink it in the same breath because
    problems.thumb takes a path and tk.PhotoImage needs PNG; a PILLOW
    painter needs neither, so bytes are simply opened and scaled here and
    the temp file does not exist. A path still goes to problems.thumb,
    which caches by mtime and is the module that owns how big a thumbnail
    is.

    Nothing in here may raise: a report with no picture is still a report,
    and "the screenshot failed to decode" must never be the reason the
    hotkey does nothing.
    """
    if not shot:
        return None
    try:
        import problems
        limit = int(getattr(problems, "THUMB_MAX", 220))
    except Exception:                 # noqa: BLE001
        problems, limit = None, 220
    # Keyed on the CONTENT, not on id(): a bytes object that has been
    # collected leaves its id free for the next one, and two different
    # screens of the same length would then share a thumbnail. Hashing
    # half a megabyte costs well under a millisecond and the card is
    # repainted on every keystroke, so the cache is what makes the
    # thumbnail free rather than the dominant cost of typing.
    key = (hash(bytes(shot)) if isinstance(shot, (bytes, bytearray))
           else ("path", str(shot)))
    got = _shot_cache.get(key)
    if got is not None:
        return got
    try:
        if isinstance(shot, (bytes, bytearray)):
            raw = bytes(shot)
        else:
            raw = problems.thumb(None, shot) if problems else None
            if raw is None:
                with open(shot, "rb") as handle:
                    raw = handle.read()
        image = Image.open(io.BytesIO(raw))
        image.load()
        image = image.convert("RGB")
        image.thumbnail((limit, limit), Image.LANCZOS)
    except Exception:                 # noqa: BLE001 — no picture, no row
        return None
    if len(_shot_cache) > 8:
        _shot_cache.clear()
    _shot_cache[key] = image
    return image


def compose(card: dict, cache: dict | None = None):
    """The whole card as one opaque RGB image, ready to go on a Canvas.

    Opaque and flat to its own edges, not a rounded bitmap on a
    background: the rounding is the WINDOW's job here
    (overlay._round_corners, DWM attribute 33, which clips the window
    itself and antialiases the clip against the real desktop) and a
    rounded face painted underneath would only draw a second,
    differently-curved edge inside the first. dashboard._round_frameless
    says the same thing at more length and is where the measurement lives.
    """
    cache = cache if cache is not None else {}
    box = layout(card, cache)
    width, height = box["size"]
    ground = rgb("CARD")
    img = Image.new("RGB", (width, height), ground)
    body = (PAD, PAD)

    def put(layer, x, y) -> None:
        if layer.mode == "RGBA":
            img.paste(layer, (int(body[0] + x), int(body[1] + y)), layer)
        else:
            img.paste(layer, (int(body[0] + x), int(body[1] + y)))

    where = (card.get("where") or "").upper()
    if where:
        eyebrow = _ltr(cache, f"ON {where}", 8.0, rgb("FAINT"), INNER)
        put(eyebrow, 0, EYEBROW_Y)
    title = _ltr(cache, TITLE, 14.0, rgb("FG"), INNER, weight=700)
    put(title, 0, TITLE_Y)
    put(_ltr(cache, HINT, 8.0, rgb("FAINT"), INNER), 0, HINT_Y)
    # What Enter means, on the card. With no title bar there is no X to
    # click and no menu to read, so the keyboard is the only way out that
    # is always there — and Enter changed meaning the moment the field
    # grew past one line, which he must not have to discover by losing a
    # sentence to it.
    send_on = bool(card.get("send"))
    put(_ltr(cache, KEYS_SEND if send_on else KEYS, KEYS_PT, rgb("FAINT"),
             INNER), 0, box["keys"][1])

    # -- the field: a well he can see the edges of, lit when it has the
    # caret. Drawn here and only drawn: the caret, the selection and the
    # characters are a real Text widget the window places over this
    # rectangle, because a painted field is a picture of typing.
    fx0, fy0, fx1, fy1 = box["field"]
    lit = bool(card.get("focused"))
    put(_rr((fx1 - fx0, fy1 - fy0), FIELD_RADIUS,
            fill=rgb("EDGE") + (255,),
            outline=(rgb("ACCENT") if lit else rgb("STROKE")) + (255,),
            width=1), fx0, fy0)

    # -- and this is what the field cannot do. Measured 2026-09-04 on both
    # widgets: typing "הכפתור של Settings לא עובד אחרי restart" into a
    # tk.Entry DRAWS as "restart לא עובד אחרי Settings הכפתור של", and a
    # tk.Text — checked because the field grew into one — scrambles it
    # exactly the same way. Every character is right and the report is
    # stored right; only the drawing lies. So the line is echoed here
    # through DrawTextW, the renderer that gets it right, and he can read
    # back what he actually typed before he sends it.
    typed = (card.get("typed") or "").strip()
    y = fy1 + ECHO_GAP
    if typed and box["echo_h"]:
        put(_rtl_block(cache, typed, ECHO_PT, rgb("DIM"), INNER), 0, y)

    # -- chips, not a dropdown: five values, one of them always on, and the
    # whole set worth seeing at once. Same call the History filters make,
    # and the same face ui.Chip paints — a 15 px pill, the accent at card
    # weight behind the one that is picked.
    picked = card.get("kind")
    hover = card.get("hover")
    for name, rect in box["chips"].items():
        cx0, cy0, cx1, cy1 = rect
        on = name == picked
        hot = hover == KIND_PREFIX + name
        # ui.Chip's own three faces, in palette names rather than the
        # literals it used to spell inline — its off fill and CARD are
        # one step apart at most, so an unpicked chip is a
        # hairline pill on the card and not a raised button, which is what
        # the dashboard's row looks like and what made this one look
        # heavier than it beside it.
        if on:
            fill, edge, ink = (rgb("ACCENT_SOFT"), rgb("ACCENT_EDGE"),
                               rgb("ACCENT_TEXT"))
        elif hot:
            fill, edge, ink = (rgb("CARD_HI"), rgb("STROKE"), rgb("FG"))
        else:
            fill, edge, ink = (rgb("CARD"), rgb("LINE"), rgb("DIM"))
        put(_rr((cx1 - cx0, cy1 - cy0), CHIP_H / 2, fill=fill + (255,),
                outline=edge + (255,), width=1), cx0, cy0)
        word = _rtl(cache, name, 9.0, ink)
        put(word, cx0 + (cx1 - cx0 - word.width) / 2,
            cy0 + (cy1 - cy0 - word.height) / 2)

    # -- THE PICTURE THAT IS GOING WITH IT. He asked to see the screenshot
    # before he sends the report: it is the only way to know it caught the
    # thing he is reporting, and — with [problems] shot off or the grab
    # failed — the only way to see that there is NO picture rather than
    # assume there is one. Left, with the caption beside it, because this
    # row is English and reads that way.
    shot, shot_box = box["shot_image"], box["shot"]
    if shot is not None and shot_box is not None:
        sx0, sy0 = shot_box[0], shot_box[1]
        put(_rr((shot.width + 2, shot.height + 2), 5,
                fill=None, outline=rgb("STROKE") + (255,), width=1),
            sx0, sy0)
        img.paste(shot, (int(body[0] + sx0 + 1), int(body[1] + sy0 + 1)))
        cap_w = max(80, INNER - shot.width - SHOT_CAP_GAP - 6)
        put(_ltr(cache, SHOT_CAPTION, 8.0, rgb("FAINT"), cap_w),
            shot.width + SHOT_CAP_GAP, sy0 + 2)

    # -- "Send to the developer": one checkbox, off. Under it, while it
    # is on, the strip — what would leave, each piece with its size,
    # each a toggle; a piece the report does not have is greyed and says
    # "none". The words are the row: a press anywhere on the line flips
    # it, and the square is only where the answer is drawn.
    cx0, cy0, cx1, cy1 = box["check"]
    _switch(img, (body[0] + cx0, body[1] + cy0 + (ROW_H - SWITCH_H) / 2),
            send_on, hot=hover == SEND_TOGGLE)
    word = _rtl(cache, SEND_TOGGLE_LABEL, 9.5,
                rgb("FG") if send_on else rgb("DIM"))
    put(word, cx0 + STRIP_INDENT, cy0 + (ROW_H - word.height) / 2)
    if send_on and box["strip_head"] is not None:
        hx0, hy0, _hx1, _hy1 = box["strip_head"]
        put(_ltr(cache, STRIP_EYEBROW, 8.0, rgb("FAINT"), INNER - STRIP_INDENT),
            hx0, hy0)
        attach = card.get("attach") or {}
        sizes = card.get("sizes") or {}
        for name, (ax0, ay0, _ax1, _ay1) in box["attach"].items():
            have = int(sizes.get(name) or 0) > 0
            on = have and bool(attach.get(name))
            _switch(img, (body[0] + ax0, body[1] + ay0 + (ROW_H - SWITCH_H) / 2),
                    on, hot=hover == ATTACH_PREFIX + name, dead=not have)
            text = f"{ATTACH_WORDS.get(name, name)}  ·  {size_word(sizes.get(name))}"
            word = _rtl(cache, text, 9.0,
                        rgb("FAINT") if not have else rgb("FG") if on else rgb("DIM"))
            put(word, ax0 + STRIP_INDENT, ay0 + (ROW_H - word.height) / 2)

    # -- the two answers. The primary carries the accent and the icon
    # the dashboard's does, and its word follows the checkbox — Keep on
    # this PC, or Preview; Cancel is the quiet one, and it is a real
    # button rather than only the Escape key because a floating card
    # with no frame gives the mouse nothing else to say no with.
    #
    # ON the accent fill the label is ACCENT_ON and not FG. Under the blue
    # palette white on the accent was 4.10:1 — already below AA — and on a
    # gold fill it is 1.8:1, which is a word you cannot read on the one
    # button the card is for. ACCENT_ON is 8.52:1 on it.
    sx0, sy0, sx1, sy1 = box["send"]
    hot = hover == SEND
    put(_rr((sx1 - sx0, sy1 - sy0), BTN_RADIUS,
            fill=(rgb("ACCENT_HI") if hot else rgb("ACCENT")) + (255,)),
        sx0, sy0)
    label = _rtl(cache, PREVIEW_LABEL if send_on else SEND_LABEL, 9.5,
                 rgb("ACCENT_ON"), weight=600)
    icon = 14
    total = icon + 8 + label.width
    ix = sx0 + (sx1 - sx0 - total) / 2
    _circle_x(img, (int(body[0] + ix), int(body[1] + (sy0 + sy1) / 2)),
              icon, rgb("ACCENT_ON"))
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


def _circle_x(img, centre, size: int, colour) -> None:
    """ui.ICON["error"]'s circled cross, drawn rather than typed.

    The dashboard's Send carries that icon and this card should carry the
    same one, but ui.ICON is a Tk PhotoImage table and a glyph (U+2297) is
    at the mercy of whatever face DrawTextW picks. Two primitives are
    neither. Supersampled 4x for the same reason _rr is.
    """
    k = 4
    r = size * k / 2
    layer = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse((k, k, size * k - k, size * k - k), outline=colour + (255,),
              width=max(1, int(1.4 * k)))
    off = r * 0.34
    d.line((r - off, r - off, r + off, r + off), fill=colour + (255,),
           width=max(1, int(1.3 * k)))
    d.line((r - off, r + off, r + off, r - off), fill=colour + (255,),
           width=max(1, int(1.3 * k)))
    layer = layer.resize((size, size), Image.LANCZOS)
    img.paste(layer, (int(centre[0]), int(centre[1] - size / 2)), layer)


def _switch(img, corner, on: bool, *, hot: bool = False,
            dead: bool = False) -> None:
    """ui.Switch, painted: the track a pill — the accent when on, the
    off track when not, LINE-faint when the piece is not there to turn
    on — and the knob a disc of FG at the end the answer is. Same
    numbers as the widget's, so the desk's box and this card show one
    switch. Supersampled 4x like the rest."""
    k = 4
    w, h, inset = SWITCH_W * k, SWITCH_H * k, KNOB_INSET * k
    if on:
        track = rgb("ACCENT_HI") if hot else rgb("ACCENT")
    elif dead:
        track = rgb("LINE")
    else:
        track = rgb("TRACK_OFF")
    knob = rgb("FAINT") if dead else rgb("FG")
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2,
                        fill=track + (255,))
    dia = h - 2 * inset
    x = w - inset - dia if on else inset
    d.ellipse((x, inset, x + dia, inset + dia), fill=knob + (255,))
    layer = layer.resize((SWITCH_W, SWITCH_H), Image.LANCZOS)
    img.paste(layer, (int(corner[0]), int(corner[1])), layer)


__all__ = ["card_for", "attach_for", "size_word", "field_lines", "layout",
           "measure", "regions", "hit_test", "compose", "rgb", "hex_of",
           "CARD_W", "PAD", "INNER", "FIELD_LINE_H", "FIELD_FONT",
           "FIELD_FONT_LINE", "FIELD_PAD_X", "FIELD_PAD_Y", "FIELD_PT",
           "FIELD_LINES_MIN", "FIELD_LINES_MAX", "SEND", "CANCEL", "FIELD",
           "CARD_REGION", "KIND_PREFIX", "SEND_TOGGLE", "ATTACH_PREFIX",
           "ATTACH_ORDER", "ATTACH_WORDS", "TITLE", "HINT", "KEYS",
           "KEYS_SEND", "SHOT_CAPTION", "SEND_LABEL", "PREVIEW_LABEL",
           "CANCEL_LABEL", "SEND_TOGGLE_LABEL", "STRIP_EYEBROW", "NONE_WORD"]
