"""His keyboard, drawn once, lit from the bindings.

Why a picture of a keyboard rather than a list of rows: he does not
remember that translate is F8, he remembers where his finger goes. A
list of fifteen "Translate (tap)  [F8]" rows is a lookup table for a
thing that is already spatial. Drawn on the board, the answer to "which
keys does this app take from me" is one glance, and the answer to "is
that one free" is the colour of the cap.

A FULL-SIZE ANSI BOARD, 104 caps, because that is what is on his desk.
It was tenkeyless for a day and he said so on 2026-09-07: "adapt them to
my keyboard because I also have num lock 1 to 9, 0 to 9, asterisk, and
other things". The keypad is the same unit grid with the standard 0.25u
gap after the navigation cluster, so nothing here is a special case
except the two caps that are two rows tall (its + and its Enter, named
in TALL).

One PIL image, one hit table. Everything is measured from a single unit
`u` (a 1x cap), so the board fits whatever room the screen has: at u=34
it is 781x239 and draws in 22 ms, at u=43 it is 984x298 and draws in
28 ms (medians of five, 2026-09-07, seventeen caps wider than the
tenkeyless board that cost 26-32 ms at u=43). A click redraws the whole
board, which is under a frame, so there is no partial-repaint machinery
here.

FIVE THINGS THIS GOT WRONG FIRST, all of them measured (spikes.md §2):

1. **One cap can carry two bindings.** `translate_hotkey = "f8"` and
   `lookup_hotkey = "ctrl+f8"` are the same cap. The map is
   `{cap: [binding, ...]}`; a dict of one silently lost `look up`.
2. **`hotkey.parse_binding` returns UNSIDED modifier VKs** — 0x11 for
   ctrl, not 0xA2. A cap map that calls the left one "left ctrl" never
   matches, and nine chords then lit their letter and no modifier at all.
   The modifier caps are named `ctrl` / `shift` / `alt` / `win`.
3. **Pillow has no font fallback.** Rubik holds no U+2190..2193, so
   every arrow cap drew as .notdef — while the same arrow inside a
   `ui.KeyCap` looked fine, because Tk falls back per glyph and PIL does
   not. The four arrows are drawn, not typed.
4. **Esc is not in config.toml.** It cancels a running recording — it is
   watched by the recorder, not registered as a hotkey — so it is named
   here and drawn with a broken edge that says "only sometimes".
5. **The keypad has its own virtual keys, and only while Num Lock is
   on.** VK_NUMPAD0..9 are 0x60..0x69, not the digit row's 0x30..0x39,
   and * + - . / are 0x6A/0x6B/0x6D/0x6E/0x6F. With Num Lock OFF the
   same physical keys arrive as Insert, Delete, the arrows and
   Home/End/PgUp/PgDn — so a press then lights THOSE caps, which is the
   truth about what the app was handed. The one keypad cap with no code
   of its own is its Enter: it is VK_RETURN, the same 0x0D as the main
   one, so `enter` lights both caps and no code can tell them apart.

The colours come from `ui` at call time (`palette()`), never copied into
a constant, because the palette is being retuned in another file.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageTk

import paths

import config as config_mod
import hotkey as hotkey_mod
import ui

APP_DIR = Path(__file__).resolve().parent
FONT_DIR = APP_DIR / "fonts"

# --------------------------------------------------------------- layout
# (id, label, units). A None id is dead space between clusters. A cap two
# rows tall is named in TALL and the row under it leaves that column
# empty, the way the board itself does.
FROW = [("esc", "Esc", 1), (None, "", 1),
        ("f1", "F1", 1), ("f2", "F2", 1), ("f3", "F3", 1), ("f4", "F4", 1),
        (None, "", .5),
        ("f5", "F5", 1), ("f6", "F6", 1), ("f7", "F7", 1), ("f8", "F8", 1),
        (None, "", .5),
        ("f9", "F9", 1), ("f10", "F10", 1), ("f11", "F11", 1),
        ("f12", "F12", 1), (None, "", .25),
        ("prtsc", "PrtSc", 1), ("scrlk", "ScrLk", 1), ("pause", "Pause", 1)]

ROW1 = [("`", "`", 1)] + [(str(d), str(d), 1) for d in
                          (1, 2, 3, 4, 5, 6, 7, 8, 9, 0)] + \
       [("-", "-", 1), ("=", "=", 1), ("backspace", "Backspace", 2),
        (None, "", .25),
        ("insert", "Ins", 1), ("home", "Home", 1), ("pgup", "PgUp", 1),
        (None, "", .25),
        ("numlock", "NumLk", 1), ("numdiv", "/", 1), ("nummul", "*", 1),
        ("numsub", "-", 1)]

ROW2 = [("tab", "Tab", 1.5)] + [(c, c.upper(), 1) for c in "qwertyuiop"] + \
       [("[", "[", 1), ("]", "]", 1), ("\\", "\\", 1.5), (None, "", .25),
        ("delete", "Del", 1), ("end", "End", 1), ("pgdn", "PgDn", 1),
        (None, "", .25),
        ("num7", "7", 1), ("num8", "8", 1), ("num9", "9", 1),
        ("numadd", "+", 1)]

ROW3 = [("caps", "Caps", 1.75)] + [(c, c.upper(), 1) for c in "asdfghjkl"] + \
       [(";", ";", 1), ("'", "'", 1), ("enter", "Enter", 2.25),
        (None, "", 3.5),          # the keypad's + comes down from ROW2
        ("num4", "4", 1), ("num5", "5", 1), ("num6", "6", 1)]

ROW4 = [("lshift", "Shift", 2.25)] + [(c, c.upper(), 1) for c in "zxcvbnm"] + \
       [(",", ",", 1), (".", ".", 1), ("/", "/", 1),
        ("rshift", "Shift", 2.75), (None, "", 1.25),
        ("up", "↑", 1), (None, "", 1.25),
        ("num1", "1", 1), ("num2", "2", 1), ("num3", "3", 1),
        ("numenter", "Enter", 1)]

ROW5 = [("lctrl", "Ctrl", 1.25), ("lwin", "Win", 1.25), ("lalt", "Alt", 1.25),
        ("space", "", 6.25), ("ralt", "Alt", 1.25), ("rwin", "Win", 1.25),
        ("menu", "Menu", 1.25), ("rctrl", "Ctrl", 1.25), (None, "", .25),
        ("left", "←", 1), ("down", "↓", 1), ("right", "→", 1),
        (None, "", .25),          # the keypad's Enter comes down from ROW4
        ("num0", "0", 2), ("numdot", ".", 1)]

ROWS = [FROW, ROW1, ROW2, ROW3, ROW4, ROW5]

# The keypad's own caps, named once rather than sniffed out of an id
# prefix. KEYPAD_NUMLOCK is the subset Num Lock actually gates: the
# digits and the dot send Insert / Delete / the arrows / the page keys
# with it off, while / * - + and Enter send the same code either way.
KEYPAD_NUMLOCK = frozenset({f"num{digit}" for digit in range(10)}
                           | {"numdot"})
KEYPAD = frozenset(KEYPAD_NUMLOCK | {"numlock", "numdiv", "nummul",
                                     "numsub", "numadd", "numenter"})

# The two caps that are two rows tall. They are drawn from the row they
# START in and the row below leaves the column empty, so no rectangle in
# the hit table ever overlaps another.
TALL = {"numadd": 2, "numenter": 2}

UNITS = 22.5           # the widest row, in cap units: 18.25 of tenkeyless,
                       # the standard 0.25 gap, and 4 of keypad
GRID_ROWS = 6

# The Israeli standard layout, letter by letter, as his fingers type it.
# Single letters, so no bidi is involved and plain text() is correct.
HEBREW = {"q": "/", "w": "'", "e": "ק", "r": "ר", "t": "א",
          "y": "ט", "u": "ו", "i": "ן", "o": "ם",
          "p": "פ", "a": "ש", "s": "ד", "d": "ג",
          "f": "כ", "g": "ע", "h": "י", "j": "ח",
          "k": "ל", "l": "ך", ";": "ף", "'": ",",
          "z": "ז", "x": "ס", "c": "ב", "v": "ה",
          "b": "נ", "n": "מ", "m": "צ", ",": "ת",
          ".": "ץ", "/": "."}

# The one word under a lit cap. config.toml's comments are prose, not
# labels, and HOTKEY_FIELDS' labels are sentences ("Report a problem
# (tap)"), so the single word a cap has room for is named here. A field
# with no entry falls back to the first word of its label, which is why
# a new key still draws.
CAPTION = {
    "hotkey": "dictate", "english_hotkey": "english",
    "latch_hotkey": "lock on", "translate_hotkey": "translate",
    "punctuate_hotkey": "punctuate", "correct_hotkey": "teach",
    "lookup_hotkey": "look up", "visual_qa_hotkey": "ask",
    "capture_hotkey": "shot", "record_hotkey": "record",
    "camera_hotkey": "camera", "pause_hotkey": "pause",
    "screens_hotkey": "screens", "report_hotkey": "report",
    "dismiss_hotkey": "dismiss",
}

HOLD = {"hotkey", "english_hotkey"}   # held down the whole time they work
WHILE_HELD = {"latch_hotkey"}         # tapped INSIDE a hold

# cap id -> the name hotkey.vk_for knows it by. UNSIDED for the
# modifiers: see the module docstring, trap 2.
CAP_NAMES = {"rctrl": "right ctrl", "lctrl": "ctrl",
             "rshift": "right shift", "lshift": "shift",
             "ralt": "right alt", "lalt": "alt", "lwin": "win",
             "rwin": "right win", "insert": "insert", "delete": "delete",
             "pgup": "page up", "pgdn": "page down", "caps": "caps lock",
             "scrlk": "scroll lock", "prtsc": "print screen",
             "backspace": "backspace", "enter": "enter", "tab": "tab",
             "space": "space", "esc": "esc", "left": "left",
             "right": "right", "up": "up", "down": "down", "home": "home",
             "end": "end", "pause": "pause", "menu": "menu",
             # The keypad. Its Enter is VK_RETURN like the main one — see
             # trap 5 — so it is named "enter" too and both caps light.
             "numlock": "num lock", "numdiv": "numpad /",
             "nummul": "numpad *", "numsub": "numpad -",
             "numadd": "numpad +", "numdot": "numpad .",
             "numenter": "enter"}
CAP_NAMES.update({f"num{digit}": f"numpad {digit}" for digit in range(10)})

ARROWS = {"←": 180, "↑": 90, "→": 0, "↓": 270}

STATES = ("hold", "tap", "held-too", "chord", "soft", "sometimes")

_cap_vks: dict | None = None
_fonts: dict = {}


def board_size(u: int) -> tuple[int, int]:
    """What `draw(u)` will return, without drawing it — so a screen can
    do its arithmetic before it pays for the image."""
    pad = 8
    row_gap = round(u * 0.55)
    return round(UNITS * u) + 2 * pad, GRID_ROWS * u + row_gap + 2 * pad


def unit_for(width: int, height: int) -> int:
    """The biggest cap that fits a box. Integer, because half a pixel of
    cap is a row of caps that do not line up."""
    pad = 8
    by_w = (width - 2 * pad) / UNITS
    by_h = (height - 2 * pad) / (GRID_ROWS + 0.55)
    return max(24, int(min(by_w, by_h)))


# --------------------------------------------------------------- palette

def palette() -> dict:
    """Read out of `ui` every time. The tokens are moving under this
    file tonight and a copy taken at import would be the old ones."""
    accent = ui.ACCENT
    lit_ink = getattr(ui, "ACCENT_TEXT", None) or accent
    soft = getattr(ui, "ACCENT_SOFT", None) or ui.CARD
    return {
        "bg": ui.BG,
        "face": ui.CARD,
        "edge": ui.LINE,
        "ink": ui.DIM,
        "heb": ui.FAINT,
        "hold_face": soft,
        "tap_face": _mix(soft, ui.CARD, 0.45),
        "lit_edge": accent,
        "lit_ink": lit_ink,
        "soft_face": _mix(soft, ui.CARD, 0.7),
        "soft_edge": _mix(accent, ui.CARD, 0.55),
        "soft_ink": _mix(lit_ink, ui.CARD, 0.4),
        "sel_face": _mix(soft, accent, 0.28),
        "sel_edge": _mix(accent, "#ffffff", 0.35),
        "sel_ink": ui.FG,
    }


def _mix(a: str, b: str, amount: float) -> str:
    def rgb(c):
        c = c.lstrip("#")
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    ra, ga, ba = rgb(a)
    rb, gb, bb = rgb(b)
    return "#%02x%02x%02x" % (int(ra + (rb - ra) * amount),
                              int(ga + (gb - ga) * amount),
                              int(ba + (bb - ba) * amount))


# -------------------------------------------------------------- bindings

def cap_vks() -> dict:
    """{cap id: virtual-key code}, asked of `hotkey.vk_for` rather than
    typed out here — so a cap and a binding are matched on the number
    Windows uses, never on the spelling of a name."""
    global _cap_vks
    if _cap_vks is not None:
        return _cap_vks
    out: dict[str, int] = {}
    for row in ROWS:
        for cap_id, _label, _units in row:
            if cap_id is None:
                continue
            for candidate in (CAP_NAMES.get(cap_id), cap_id):
                if not candidate:
                    continue
                try:
                    out[cap_id] = hotkey_mod.vk_for(candidate)
                    break
                except (ValueError, KeyError, AttributeError):
                    continue
    _cap_vks = out
    return out


def offered() -> list[str]:
    """The caps this window can draw that the app cannot bind at all —
    `vk_for` covers a-z, 0-9, F1-F24 and the named keys and nothing
    else. Generated rather than typed, so it stays true."""
    known = cap_vks()
    out = []
    for row in ROWS:
        for cap_id, label, _units in row:
            if cap_id is not None and cap_id not in known:
                out.append(label or cap_id)
    return out


def bindings(keys: dict | None = None) -> tuple[dict, list]:
    """({cap id: [(state, caption, field, raw), ...]}, unmapped).

    `keys` is {field: "ctrl+f8"} — the dashboard already has it, from
    the running app's status or from config.toml. Without one the file
    is read. `unmapped` is every binding whose key has no cap on this
    board, which is the list that has to stay empty.
    """
    if keys is None:
        try:
            cfg = config_mod.load(paths.CONFIG_FILE)
            keys = {name: getattr(cfg, name, "")
                    for name, _label in config_mod.HOTKEY_FIELDS}
        except Exception:                 # noqa: BLE001 — unreadable config
            keys = {}
    by_vk = vk_caps()
    lit: dict[str, list] = {}
    unmapped: list = []
    for field, label in config_mod.HOTKEY_FIELDS:
        raw = str(keys.get(field) or "")
        if not raw:
            continue                      # english_hotkey = "": bound to none
        try:
            bound = hotkey_mod.parse_binding(raw)
        except Exception:                 # noqa: BLE001 — a typo in the file
            unmapped.append((field, raw))
            continue
        caps = by_vk.get(bound.trigger) or []
        if not caps:
            unmapped.append((field, raw))
            continue
        if field in HOLD:
            state = "hold"
        elif field in WHILE_HELD:
            state = "held-too"
        elif bound.mods:
            state = "chord"
        else:
            state = "tap"
        caption = CAPTION.get(field) or label.split(" (")[0].lower()
        for cap in caps:
            lit.setdefault(cap, []).append((state, caption, field, raw))
        for mod in bound.mods:
            for target in by_vk.get(mod, ()):
                if not lit.get(target):
                    lit[target] = [("soft", "", "", "")]
    # Esc: watched by the recorder while one is running, never registered.
    lit.setdefault("esc", []).append(("sometimes", "cancel", "", "esc"))
    return lit, unmapped


def vk_caps() -> dict[int, list[str]]:
    """{virtual-key code: [cap id, ...]}. A LIST, because one code can be
    two caps: the keypad's Enter is VK_RETURN, exactly like the main one,
    and a dict of one silently lit whichever came last in ROWS."""
    out: dict[int, list[str]] = {}
    for cap, vk in cap_vks().items():
        out.setdefault(vk, []).append(cap)
    return out


def caps_for(raw: str) -> list[str]:
    """Every cap a binding string lands on. Two, for the two Enters."""
    try:
        bound = hotkey_mod.parse_binding(str(raw))
    except Exception:                     # noqa: BLE001
        return []
    return list(vk_caps().get(bound.trigger) or [])


def cap_for(raw: str) -> str | None:
    """Which cap a binding string lands on — the FIRST one, in the order
    the board draws them, so `enter` is the big one under Backspace and
    not the keypad's. `caps_for` is the honest answer for both."""
    found = caps_for(raw)
    return found[0] if found else None


def cap_for_vk(vk: int) -> str | None:
    """The cap a Windows virtual-key code lands on. Tk reports a key
    press on Windows with `keycode` = the VK, so this is how a REAL press
    finds its cap on the board — the owner's ask of 2026-09-07: "if I
    press R, it should tell me what it does". Modifiers come back
    unsided (0x11 is ctrl, left or right), which is how the caps are
    named — and a sided code from a hook is folded the same way.

    The keypad reports its OWN codes (VK_NUMPAD0..9 = 0x60..0x69, and
    0x6A..0x6F for * + - . /), and only while Num Lock is on; with it
    off the arrows and the navigation keys arrive from those same caps
    and light those, which is what the app was really handed. Both
    Enters are 0x0D and the first cap wins, which is the main one."""
    modifier = _MODIFIER_CAPS.get(int(vk))
    if modifier is not None:
        return modifier
    for cap, code in cap_vks().items():
        if code == vk:
            return cap
    return None


# The modifier caps are not in cap_vks (they are never a binding's
# trigger on their own), so a press on one is named here: VK_SHIFT /
# VK_CONTROL / VK_MENU / VK_LWIN as Tk reports them, and the sided
# codes a raw hook reports, all folded to the cap's one name.
_MODIFIER_CAPS = {0x10: "shift", 0xA0: "shift", 0xA1: "shift",
                  0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
                  0x12: "alt", 0xA4: "alt", 0xA5: "alt",
                  0x5B: "win", 0x5C: "win"}


def name_for(cap_id: str) -> str | None:
    """The name `hotkey.vk_for` knows a cap by — what a click on it has
    to turn into before anything can be bound to it."""
    if cap_id in CAP_NAMES:
        return CAP_NAMES[cap_id]
    return cap_id if cap_id in cap_vks() else None


# --------------------------------------------------------------- drawing

def _font(name: str, size: int):
    key = (name, size)
    if key not in _fonts:
        path = FONT_DIR / name
        try:
            _fonts[key] = ImageFont.truetype(str(path), size)
        except OSError:
            _fonts[key] = ImageFont.load_default()
    return _fonts[key]


def draw(u: int = 43, *, lit: dict, selected: str | None = None,
         scale: int = 2, colours: dict | None = None
         ) -> tuple[Image.Image, dict]:
    """The whole board as one image, plus {cap id: (x0, y0, x1, y1)} at
    1x for the hit test.

    Supersampled x2 and resized with LANCZOS: x1 is aliased, x4 costs
    51 ms for no visible gain at a 43 px cap.
    """
    p = colours or palette()
    gap = max(3, round(u * 0.14))
    pad = 8
    row_gap = round(u * 0.55)
    width, height = board_size(u)
    s = scale
    img = Image.new("RGB", (width * s, height * s), p["bg"])
    d = ImageDraw.Draw(img)
    f_label = _font("RubikMedium.ttf", round(u * 0.26 * s))
    f_small = _font("Rubik.ttf", round(u * 0.21 * s))
    f_heb = _font("Rubik.ttf", round(u * 0.21 * s))
    f_cap = _font("Rubik.ttf", max(7, round(u * 0.155 * s)))
    f_mark = _font("RubikMedium.ttf", round(u * 0.24 * s))
    rects: dict[str, tuple] = {}

    y = pad
    for index, row in enumerate(ROWS):
        if index == 1:
            y += row_gap
        x = pad
        for cap_id, label, units in row:
            w = units * u
            if cap_id is None:
                x += w
                continue
            x0, y0 = x, y
            tall = TALL.get(cap_id, 1) * u
            x1, y1 = x + w - gap, y + tall - gap
            rects[cap_id] = (round(x0), round(y0), round(x1), round(y1))
            on = lit.get(cap_id) or []
            bare = [b for b in on if "+" not in (b[3] or "")]
            first = (bare or on or [("", "", "", "")])[0]
            state, caption = first[0], first[1]
            also = len(on) > 1 or bool(on and not bare)
            face, edge, ink, dashed = _skin(state, cap_id == selected, p)
            box = (x0 * s, y0 * s, x1 * s, y1 * s)
            d.rounded_rectangle(box, radius=round(u * 0.13 * s), fill=face,
                                outline=edge,
                                width=(2 if state or cap_id == selected
                                       else 1) * s)
            if dashed:
                _dash(d, box, round(u * 0.13 * s), p["lit_edge"], 2 * s, 5 * s)
            cx = (x0 + x1) / 2 * s
            # A cap with a caption stacks the two lines around the cap's
            # own middle — which for the keypad's + and Enter is two rows
            # down, not one. 0.42u and 0.73u were that middle minus
            # 0.08u and plus 0.23u all along.
            middle = y0 + tall / 2
            if label:
                font = f_label if len(label) <= 2 else f_small
                anchor_y = ((middle - u * 0.08) * s if caption
                            else ((y0 + y1) / 2) * s)
                heb = HEBREW.get(cap_id)
                lx = cx if not heb else cx - u * 0.16 * s
                if label in ARROWS:
                    arrow(d, lx, anchor_y, u * 0.34 * s, ARROWS[label], ink,
                          max(1, round(u * 0.045 * s)))
                else:
                    d.text((lx, anchor_y), label, font=font, fill=ink,
                           anchor="mm")
                if heb:
                    d.text((cx + u * 0.22 * s, anchor_y), heb, font=f_heb,
                           fill=p["heb"], anchor="mm")
            if caption:
                d.text((cx, (middle + u * 0.23) * s), caption, font=f_cap,
                       fill=p["sel_ink"] if cap_id == selected
                       else p["lit_ink"], anchor="mm")
            if also:
                # A second binding on the same cap, with a modifier. F8
                # is `translate` bare and `look up` with ctrl.
                d.text(((x1 - u * 0.15) * s, (y0 + u * 0.2) * s), "^",
                       font=f_mark, fill=p["lit_ink"], anchor="mm")
            x += w
        y += u
    return img.resize((width, height), Image.LANCZOS), rects


def _skin(state, is_selected, p):
    if is_selected:
        return p["sel_face"], p["sel_edge"], p["sel_ink"], False
    if state == "hold":
        return p["hold_face"], p["lit_edge"], p["lit_ink"], False
    if state in ("tap", "held-too", "chord"):
        return p["tap_face"], p["lit_edge"], p["lit_ink"], False
    if state == "soft":
        return p["soft_face"], p["soft_edge"], p["soft_ink"], False
    if state == "sometimes":
        return p["face"], p["edge"], p["lit_ink"], True
    return p["face"], p["edge"], p["ink"], False


def _dash(d, box, radius, colour, width, step):
    """A dashed outline. Pillow's rounded_rectangle has no dash pattern,
    so the four sides are drawn by hand — which is fine, because the
    corners are where the rounding is and the dashes stop short of it."""
    x0, y0, x1, y1 = box
    pos = x0 + radius
    while pos < x1 - radius:
        d.line((pos, y0, min(pos + step, x1 - radius), y0), fill=colour,
               width=width)
        d.line((pos, y1, min(pos + step, x1 - radius), y1), fill=colour,
               width=width)
        pos += step * 2
    pos = y0 + radius
    while pos < y1 - radius:
        d.line((x0, pos, x0, min(pos + step, y1 - radius)), fill=colour,
               width=width)
        d.line((x1, pos, x1, min(pos + step, y1 - radius)), fill=colour,
               width=width)
        pos += step * 2


def arrow(d, cx, cy, size, degrees, colour, width):
    """The four arrow caps, drawn. Rubik has no U+2190..2193 and Pillow
    has no fallback, so typing them puts four .notdef boxes on the
    board — which is what the first draft shipped."""
    import math
    a = math.radians(degrees)
    dx, dy = math.cos(a), -math.sin(a)
    px, py = -dy, dx
    half = size / 2
    tipx, tipy = cx + dx * half, cy + dy * half
    tailx, taily = cx - dx * half, cy - dy * half
    d.line((tailx, taily, tipx, tipy), fill=colour, width=int(width))
    head = size * 0.42
    d.polygon([(tipx, tipy),
               (tipx - dx * head + px * head * 0.55,
                tipy - dy * head + py * head * 0.55),
               (tipx - dx * head - px * head * 0.55,
                tipy - dy * head - py * head * 0.55)], fill=colour)


def hit(rects: dict, x: int, y: int) -> str | None:
    """Which cap a click landed on, or None for the gap between two —
    the gaps belong to nobody on purpose, so a near miss does nothing
    rather than rebinding the neighbour."""
    for cap_id, (x0, y0, x1, y1) in rects.items():
        if x0 <= x <= x1 and y0 <= y <= y1:
            return cap_id
    return None

# ------------------------------------------------------------ the widget

class Board(tk.Canvas):
    """The board on a Tk canvas, with its hit table and one redraw a
    click.

    The whole image is redrawn when the selection moves — 26-34 ms,
    under a frame — so there is no partial-repaint machinery and no
    per-cap widget. A hundred and four Tk windows would be the obvious
    way and it is the wrong one: this is one Canvas with one image on it.
    """

    def __init__(self, parent, lit: dict, *, u: int = 43,
                 bg: str | None = None, command=None):
        self.lit = lit
        self.u = u
        self.selected: str | None = None
        self._command = command
        colours = palette()
        image, self.rects = draw(u, lit=lit, colours=colours)
        self.size = image.size
        super().__init__(parent, width=image.width, height=image.height,
                         bg=bg or ui.BG, highlightthickness=0, bd=0,
                         cursor="hand2")
        self.photo = ImageTk.PhotoImage(image)
        self.item = self.create_image(0, 0, anchor="nw", image=self.photo)
        self.bind("<Button-1>", self._clicked)

    def _clicked(self, event) -> None:
        cap_id = hit(self.rects, event.x, event.y)
        if self._command is not None:
            self._command(cap_id)
        else:
            self.pick(cap_id)

    def _redraw(self) -> None:
        image, self.rects = draw(self.u, lit=self.lit,
                                 selected=self.selected, colours=palette())
        self.photo = ImageTk.PhotoImage(image)
        self.itemconfig(self.item, image=self.photo)

    def pick(self, cap_id: str | None) -> str | None:
        if cap_id == self.selected:
            return cap_id
        self.selected = cap_id
        self._redraw()
        return cap_id

    def relight(self, lit: dict) -> None:
        """The bindings changed under us — a rebind, or the app answering
        with keys this window had only read off the disk."""
        if lit == self.lit:
            return
        self.lit = lit
        self._redraw()
