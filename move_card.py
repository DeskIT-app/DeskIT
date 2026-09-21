"""What is on screen while the dot is being moved, and how it is drawn.

THE OWNER'S ASK, 2026-09-21, in his words: a button on the panel; "the
moment you press it the tab on the right closes, around every connected
screen there is a halo in the app's colour — gold, yellow, orange — and I
can press and hold the dot and move it wherever I want on the screen;
then a Done button somewhere strategic, and Enter finishes, Escape
cancels; when you press it the dot stays where it was dragged." Two
corrections on the first picture: "a little less shouting at the edges,
and a little further in" — so the light is quieter at the bezel and
reaches about a fifth of the way across — and the Move button's glyph is
the dot itself, "so they understand it moves the dot and not the bar".

WHAT IS ON IT:

  1. THE HALO — one per monitor, the size of that monitor: a warm rim of
     light, brightest at the edge, gone before the middle. `glow()` is
     that picture. Every pixel is alpha 0 well inside the picture, so
     the window IS the screen and there is no square to see; and the
     window never takes a click (skin\\move.py builds it click-through),
     so the halo is light on the glass and nothing more.
  2. THE DONE CARD — one small glass card at the top-centre of the
     monitor the dot is on: one plain line, a gold Done with its key
     drawn on it, and the way back ("Esc puts it back"). Top-centre
     because the dot lives at edges and corners, and the one place on a
     screen a dot is least likely to be wanted is the middle of the top
     edge — which is what "somewhere strategic" asked for. Enter and
     Esc do the same two things from the keyboard, so even a dot dropped
     ON the card is no problem.
  3. OPTIONS, at the right end of the button row (his second ask, the
     same evening: "an option — when I hover it, a little screen opens
     with my screen in it and four dots where it makes sense to put it,
     each corner; I click one and it puts the dot there"). Under the
     pointer the card grows downward by a MAP: every monitor drawn to
     scale in one row, a bead in each of its four corners; the bead
     under the pointer lights. A click on a bead is
     `corner:<monitor index>:<tl|tr|bl|br>`, and main.py puts the dot in
     that corner of that monitor's work area and ENDS the move — the
     one decision left to the builder ("if you think it disappears at
     that second, or I need to press Done too"): a corner is an answer,
     not a drag, so nothing is left to confirm. The pointer leaving the
     card folds the map away again.

Split the way every card here is split (shelf_card.py / shelf.py /
skin\\shelf.py): this half owns the WORDS, the GEOMETRY and the PICTURE —
pure Python plus Pillow, no Tk, no Win32, nothing that needs a screen —
so a test can measure the halo and press the button without a window.
dotmove.MoveFrame owns the thread, the queue and the deadline;
skin\\move.py owns the windows. Colours come out of shelf_card.INK, the
one table already read from skin\\palette.py by name: this card ends what
the shelf started and has to look like it.
"""
from __future__ import annotations

from PIL import Image, ImageChops

import shelf_card as sc

HTTRANSPARENT, HTCLIENT = sc.HTTRANSPARENT, sc.HTCLIENT

# ------------------------------------------------------------- the halo
# How far in the light reaches, as a share of the monitor's shorter side
# — 0.18 of 1440 px is 259 px on this machine's main screen. The owner's
# second picture; the first (0.11, and louder) he called "shouting".
REACH = 0.18
REACH_MIN = 96            # px, on a screen small enough for the share to be less
# Three layers, all gold, outermost first: a wide soft wash, a firmer
# band inside it, and a thin hot rim at the very edge — a lamp against
# the bezel rather than a painted border. (r, g, b), the share of REACH
# each one crosses, its alpha AT THE EDGE, and the power of its falloff.
WASH = ((236, 150, 46), 1.00, 118, 2.0)
BAND = ((243, 186, 78), 0.45, 110, 1.7)
RIM = ((255, 226, 150), 0.06, 96, 1.2)
LAYERS = (WASH, BAND, RIM)

# --------------------------------------------------------------- the card
DONE = "done"             # the button
OPTIONS = "options"       # the link that opens the map under the pointer
CORNERS = ("tl", "tr", "bl", "br")
MAP_MARGIN = 9            # a bead's centre, in from the drawn screen's corner
BEAD_PX = 16              # a bead at rest; lit, it is BEAD_PX + 6
BEAD_HIT = 13             # half the square a click on a bead may land in
SCREEN_GAP = 6            # between two drawn screens
LABEL_PT = 7.5
SHADOW = sc.SHADOW        # the room a glass window leaves around the card
RADIUS = 18
PAD = 18
TITLE_PT = 11.0
BTN_H = 34
BTN_PT = 10.5
KEY_PT = 7.5
KEY_H = 20
NOTE_PT = 9.0
GAP_TITLE = 12            # between the line and the button row
GAP_ESC = 18              # between the button and the Esc note
TOP_MARGIN = 26           # from the top of the work area to the card's face
SCALE_MIN, SCALE_MAX = sc.SCALE_MIN, sc.SCALE_MAX


def clamp_scale(scale: float) -> float:
    return sc.clamp_scale(scale)


def _ramp(length: int, a0: int, power: float) -> Image.Image:
    """A 1 x `length` alpha ramp: `a0` at the edge, 0 at the inner end,
    falling as (1 - t) ** power — steeper than linear so the light
    belongs to the edge rather than tinting the whole screen."""
    n = max(2, int(length))
    vals = bytes(int(a0 * (1.0 - i / (n - 1)) ** power) for i in range(n))
    return Image.frombytes("L", (1, n), vals)


def _rim_mask(w: int, h: int, length: int, a0: int, power: float
              ) -> Image.Image:
    """One layer's alpha over the whole monitor: the ramp laid along all
    four edges, joined with `lighter` where two meet so a corner is the
    brighter of the two and never their sum."""
    r = _ramp(length, a0, power)
    n = r.height
    top = r.resize((w, n))
    bottom = r.transpose(Image.FLIP_TOP_BOTTOM).resize((w, n))
    left = r.transpose(Image.ROTATE_90).resize((n, h))
    right = r.transpose(Image.ROTATE_270).resize((n, h))
    m = Image.new("L", (w, h), 0)
    m.paste(top, (0, 0))
    m.paste(ImageChops.lighter(m.crop((0, h - n, w, h)), bottom), (0, h - n))
    m.paste(ImageChops.lighter(m.crop((0, 0, n, h)), left), (0, 0))
    m.paste(ImageChops.lighter(m.crop((w - n, 0, w, h)), right), (w - n, 0))
    return m


def reach(w: int, h: int) -> int:
    """How many pixels in from the edge the light reaches on a monitor
    this size. The middle is dark from here on."""
    return max(REACH_MIN, int(round(min(int(w), int(h)) * REACH)))


def glow(w: int, h: int) -> Image.Image:
    """The rim of light for one monitor, as an RGBA picture its size.

    Built from three edge masks and three flat colours rather than drawn
    pixel by pixel: Pillow resizes a 1 px ramp into a band in one C pass,
    so a 2560 x 1440 halo is about 60 ms on this machine, and it is built
    once per session — nothing on it animates. The fade-in is the
    window's whole-picture alpha (skin\\glass.Glass.flush), not a repaint.
    """
    w, h = max(2, int(w)), max(2, int(h))
    span = reach(w, h)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for colour, share, a0, power in LAYERS:
        layer = Image.new("RGBA", (w, h), tuple(colour) + (0,))
        layer.putalpha(_rim_mask(w, h, max(4, int(span * share)), a0, power))
        out.alpha_composite(layer)
    return out


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------

def card_for(monitors=None) -> dict:
    """The Done card as data. Fixed words — there is one such card and it
    says one thing — plus the screens the map draws: `monitors` is a
    list of (left, top, right, bottom), primary first, the order
    capture.monitors() answers in and the order main.py resolves a
    bead's index against. Kept as a dict all the same, so the painter
    and the tests read it the way they read every other card here."""
    rects = []
    for m in monitors or []:
        l, t, r, b = (int(v) for v in (m["rect"] if isinstance(m, dict) else m))
        if r > l and b > t:
            rects.append((l, t, r, b))
    return {
        "title": "Drag the dot where you want it",
        "done": "Done",
        "enter": "Enter",
        "esc": "Esc",
        "back": "puts it back",
        "options": "Options",
        "corners": "OR PUT IT IN A CORNER",
        "monitors": rects,
    }


def corner_name(index: int, corner: str) -> str:
    """The region name of one bead: "corner:0:tr"."""
    return f"corner:{int(index)}:{corner}"


def parse_corner(name: str):
    """(index, corner) for a bead's name, None for anything else."""
    try:
        head, index, corner = str(name).split(":")
    except ValueError:
        return None
    if head != "corner" or corner not in CORNERS:
        return None
    try:
        return int(index), corner
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# the geometry
# ---------------------------------------------------------------------------

def _layout(card: dict, scale: float, cache: dict, open: bool = False) -> dict:
    """Every measured thing on the card, in CARD coordinates (the face's
    own top-left is 0, 0): the images and where they go. One function,
    read by measure(), regions() and compose(), so the three agree.
    `open` is the map unfolded under the row; the card is taller then
    and no wider, so the window keeps its place along the top."""
    s = clamp_scale(scale)
    title = sc._text(cache, card.get("title") or "", TITLE_PT * s,
                     colour="ink", weight=600, rtl=False)
    done = sc._text(cache, card.get("done") or "", BTN_PT * s,
                    colour="on_accent", weight=700, rtl=False)
    key = sc._text(cache, card.get("enter") or "", KEY_PT * s,
                   colour="on_accent", weight=700, rtl=False)
    esc = sc._text(cache, card.get("esc") or "", KEY_PT * s, colour="dim",
                   weight=700, rtl=False)
    back = sc._text(cache, card.get("back") or "", NOTE_PT * s, colour="dim",
                    weight=400, rtl=False)
    opt = sc._text(cache, card.get("options") or "", NOTE_PT * s,
                   colour="dim", weight=600, rtl=False)
    chev = sc._glyph(cache, "chevron", 11 * s, colour="faint")
    pad = PAD * s
    key_w = key.width + 12 * s
    btn_w = 14 * s + done.width + 10 * s + key_w + 10 * s
    btn_h = BTN_H * s
    esc_w = esc.width + 12 * s
    note_w = esc_w + 8 * s + back.width
    opt_w = opt.width + 6 * s + chev.width
    row_w = btn_w + GAP_ESC * s + note_w + GAP_ESC * s + 4 * s + opt_w
    width = int(round(pad + max(title.width, row_w) + pad))
    height = int(round(pad + title.height + GAP_TITLE * s + btn_h + pad))
    bx, by = pad, pad + title.height + GAP_TITLE * s
    ox = width - pad - opt_w
    out = {
        "s": s, "width": width, "height": height, "closed": height,
        "title": (title, pad, pad),
        "button": (bx, by, bx + btn_w, by + btn_h),
        "done": (done, bx + 14 * s, by + (btn_h - done.height) / 2),
        "key": (key, bx + 14 * s + done.width + 10 * s, by + (btn_h - KEY_H * s) / 2,
                key_w, KEY_H * s),
        "esc": (esc, bx + btn_w + GAP_ESC * s, by + (btn_h - KEY_H * s) / 2,
                esc_w, KEY_H * s),
        "back": (back, bx + btn_w + GAP_ESC * s + esc_w + 8 * s,
                 by + (btn_h - back.height) / 2),
        # the Options link, and the whole row-high box a hover lands in
        "options": (opt, chev, ox, by + (btn_h - opt.height) / 2),
        "options_box": (ox - 6 * s, by, width - pad + 6 * s, by + btn_h),
        "screens": [], "beads": [],
    }
    if not open:
        return out
    # THE MAP: every screen in one row, to one scale, the row as wide as
    # the card allows. A bead sits MAP_MARGIN in from each drawn corner.
    rects = card.get("monitors") or []
    label = sc._text(cache, card.get("corners") or "", LABEL_PT * s,
                     colour="faint", weight=700, rtl=False)
    y = height - pad + 8 * s
    out["rule"] = (pad, y, width - pad)
    y += 9 * s
    out["label"] = (label, pad, y)
    y += label.height + 8 * s
    if rects:
        ux0, uy0 = min(r[0] for r in rects), min(r[1] for r in rects)
        ux1, uy1 = max(r[2] for r in rects), max(r[3] for r in rects)
        k = (width - 2 * pad) / max(1, ux1 - ux0)
        map_h = int(round((uy1 - uy0) * k))
        for i, (l, t, r, b) in enumerate(rects):
            x0, y0 = pad + (l - ux0) * k, y + (t - uy0) * k
            x1, y1 = pad + (r - ux0) * k, y + (b - uy0) * k
            # a screen keeps a gap from its neighbour: shaved off its
            # right and bottom, never its origin
            x1, y1 = x1 - SCREEN_GAP * s, y1 - SCREEN_GAP * s * 0.5
            out["screens"].append((x0, y0, x1, y1))
            m_ = MAP_MARGIN * s
            for corner, (cx, cy) in (("tl", (x0 + m_, y0 + m_)),
                                     ("tr", (x1 - m_, y0 + m_)),
                                     ("bl", (x0 + m_, y1 - m_)),
                                     ("br", (x1 - m_, y1 - m_))):
                out["beads"].append((corner_name(i, corner), cx, cy))
        y += map_h
    out["height"] = int(round(y + pad))
    return out


def measure(card: dict, scale: float = 1.0,
            cache: dict | None = None, open: bool = False) -> tuple[int, int]:
    """The card's face at `scale`, (w, h). Text, so it needs the cache
    the painter uses — or its own, at the cost of a few short words."""
    lay = _layout(card, scale, cache if cache is not None else {}, open)
    return lay["width"], lay["height"]


def regions(card: dict, scale: float = 1.0,
            cache: dict | None = None, open: bool = False) -> dict:
    """Every button as a named rectangle, WINDOW-relative (the window is
    the card plus SHADOW on each side) — the same contract as
    shelf_card.regions, so a test can check it without a window. Done
    and Options always; a bead per screen corner while the map is
    open."""
    lay = _layout(card, scale, cache if cache is not None else {}, open)
    s = lay["s"]
    x0, y0, x1, y1 = lay["button"]
    out = {DONE: (x0 + SHADOW, y0 + SHADOW, x1 + SHADOW, y1 + SHADOW)}
    x0, y0, x1, y1 = lay["options_box"]
    out[OPTIONS] = (x0 + SHADOW, y0 + SHADOW, x1 + SHADOW, y1 + SHADOW)
    for name, cx, cy in lay["beads"]:
        h = BEAD_HIT * s
        out[name] = (cx - h + SHADOW, cy - h + SHADOW, cx + h + SHADOW,
                     cy + h + SHADOW)
    return out


def hit_test(card: dict, scale: float, x: int, y: int,
             cache: dict | None = None, open: bool = False):
    """(HT code, what) for a point in window coordinates: HTCLIENT on the
    button, on Options and on a bead, HTTRANSPARENT everywhere else —
    including the words, the face and the whole shadow margin, so a
    click aimed at whatever is under the card still lands there. Not
    HTCAPTION anywhere: this card is not dragged, it is dismissed."""
    for name, box in regions(card, scale, cache, open).items():
        if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
            return HTCLIENT, name
    return HTTRANSPARENT, None


def where(size: tuple[int, int], field: tuple[int, int, int, int],
          margin: int = SHADOW) -> tuple[int, int]:
    """The WINDOW's top-left for a card whose window is `size` (shadow
    included), centred along the top edge of `field` = (x, y, w, h) — the
    work area of the monitor the dot is on. `margin` is the shadow inset,
    so the FACE sits TOP_MARGIN below the field's top edge."""
    fx, fy, fw, _fh = field
    w, _h = size
    x = fx + (fw - w) // 2
    y = fy + TOP_MARGIN - margin
    return int(x), int(y)


# ---------------------------------------------------------------------------
# the picture
# ---------------------------------------------------------------------------

def compose(card: dict, scale: float = 1.0, hover: str | None = None,
            cache: dict | None = None, open: bool = False) -> Image.Image:
    """The card's CONTENT as one RGBA image the size of measure(), on a
    TRANSPARENT ground — the face belongs to the presenter, exactly as
    shelf_card.compose hands its content to skin\\shelf.py.

    `hover` is a region name; the button, the link or the bead under the
    pointer brightens. `open` draws the map under the row.
    """
    cache = cache if cache is not None else {}
    lay = _layout(card, scale, cache, open)
    s = lay["s"]
    img = Image.new("RGBA", (lay["width"], lay["height"]), (0, 0, 0, 0))

    def place(image, x, y):
        img.alpha_composite(image, (int(round(x)), int(round(y))))

    ink = sc.INK
    title, tx, ty = lay["title"]
    place(title, tx, ty)

    # THE BUTTON IS GOLD. The shelf keeps its one lit thing for the door
    # at the bottom; this card has exactly one thing on it, and it is the
    # way out, so the lamp is spent here.
    x0, y0, x1, y1 = lay["button"]
    lit = hover == DONE
    place(sc._rr((x1 - x0, y1 - y0), 10 * s,
                 fill=tuple(ink["accent_text" if lit else "accent"]) + (255,)),
          x0, y0)
    done, dx, dy = lay["done"]
    place(done, dx, dy)
    key, kx, ky, kw, kh = lay["key"]
    place(sc._rr((kw, kh), 5 * s, fill=(0, 0, 0, 0),
                 outline=tuple(ink["on_accent"]) + (170,), width=1), kx, ky)
    place(key, kx + (kw - key.width) / 2, ky + (kh - key.height) / 2)

    # the way back: a quiet key cap and four words
    esc, ex, ey, ew, eh = lay["esc"]
    place(sc._rr((ew, eh), 5 * s, fill=tuple(ink["card"]) + (255,),
                 outline=tuple(ink["line"]) + (255,), width=1), ex, ey)
    place(esc, ex + (ew - esc.width) / 2, ey + (eh - esc.height) / 2)
    back, bx, by = lay["back"]
    place(back, bx, by)

    # Options: a quiet word and a chevron, brighter under the pointer or
    # while the map it opens is showing
    opt, chev, ox, oy = lay["options"]
    lit_opt = hover == OPTIONS or open
    if lit_opt:
        opt = sc._text(cache, card.get("options") or "", NOTE_PT * s,
                       colour="ink", weight=600, rtl=False)
        chev = sc._glyph(cache, "chevron", 11 * s, colour="dim")
    place(opt, ox, oy)
    # the chevron points DOWN — at the map — and UP once it is out
    place(chev.rotate(90 if open else -90), ox + opt.width + 6 * s, oy + 1)
    if not open:
        return img

    # THE MAP. A hairline, the label, every screen as a plate the shape
    # of the real one, a taskbar strip along its foot so it reads as a
    # screen, and a bead in each corner: the dot's own picture, bigger
    # and ringed in gold under the pointer.
    rx, ry, rx1 = lay["rule"]
    place(sc._rr((rx1 - rx, 1), 0, fill=tuple(ink["line"]) + (170,)), rx, ry)
    label, lx, ly = lay["label"]
    place(label, lx, ly)
    for x0, y0, x1, y1 in lay["screens"]:
        place(sc._rr((x1 - x0, y1 - y0), 6 * s,
                     fill=tuple(ink["plate"]) + (255,),
                     outline=tuple(ink["plate_edge"]) + (255,), width=1),
              x0, y0)
        place(sc._rr((max(1, x1 - x0 - 2), 3 * s), 1 * s,
                     fill=tuple(ink["line"]) + (255,)), x0 + 1, y1 - 4 * s)
    for name, cx, cy in lay["beads"]:
        on = hover == name
        bead = sc._glyph(cache, "dot", (BEAD_PX + 6 if on else BEAD_PX) * s,
                         colour="cool")
        place(bead, cx - bead.width / 2, cy - bead.height / 2)
        if on:
            ring = BEAD_PX * s + 10 * s
            place(sc._rr((ring, ring), ring / 2, fill=None,
                         outline=tuple(ink["accent"]) + (230,), width=1.5),
                  cx - ring / 2, cy - ring / 2)
    return img


__all__ = ["DONE", "OPTIONS", "CORNERS", "SHADOW", "RADIUS", "PAD", "REACH",
           "REACH_MIN", "LAYERS", "TOP_MARGIN", "HTTRANSPARENT", "HTCLIENT",
           "clamp_scale", "reach", "glow", "card_for", "corner_name",
           "parse_corner", "measure", "regions", "hit_test", "where",
           "compose"]
