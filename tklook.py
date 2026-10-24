"""B+ for the Tk windows outside the desk: the first-run wizard and the
step windows.

The desk is a web page since 2026-10-23 and the cards beside the dot are
Pillow pictures (look.py). Two windows are still ordinary Tk with packed
widgets — firstrun.py's wizard and steps.py's step window — and they
draw with ui.py's pieces, which carry B+'s COLOURS (skin\\palette.py) but
not its SHAPES. This module is those shapes for them, with ui.py's own
API, so a page's code changes the class it names and nothing else:

* `Card`    — a pane: B+'s 22 px corner, the frosted rim the light
              catches top-left (look.rim), the inner top light. Its face
              is FLAT inside the rim, because the widgets packed on it
              are opaque rectangles in ui.CARD (AGENTS.md: a tk.Frame is
              an opaque rectangle, forever) — the rim is where the glass
              is.
* `Button`  — the lit pill (look.primary: iris from its top, the light
              pooled UNDER it, never a ring) or the quiet pill of frost
              (look.quiet); disabled is the desk's `.btn.dis`. A ui.Button
              subclass: the label is still its canvas text, so every
              caller and test that reads `_label` keeps working.
* `Switch`  — B+'s switch, which carries no accent: a lavender-grey track
              and a white knob when on, a hollow ring when off.
* `Field`   — the writing well (look.well): darker than the card, its own
              faint rim, an iris rim while it has the caret.
* `KeyCap`  — look.keycap, and `lit()` for the ring while a key is being
              listened for (it was a square Frame highlight).
* `Sky`     — the desk's night behind a whole window, worn by every
              widget that stands on it (`SkyFrame`, `SkyLabel`, `TrackBar`,
              and Card / Button given `sky=`).
* `slip`, `track`, `fill_pill` — the microphone rows, the meter's and the
              strip's track, and what a track holds.

Nothing here is module-level Tk (AGENTS.md: a PhotoImage belongs to the
interpreter that made it, and a global one is freed by the wrong thread):
every PhotoImage is made with `master=` the widget that shows it and kept
on that widget. What IS cached module-level is Pillow pictures, keyed on
everything that draws them.
"""
from __future__ import annotations

import tkinter as tk

from PIL import Image, ImageTk

import look
import ui

MUTED = "#{:02x}{:02x}{:02x}".format(*look.INK["muted"])   # the desk's ink-3
STRIP_FILL = "#{:02x}{:02x}{:02x}".format(*look.INK["sw_on"])   # progress: the switch's lavender-grey
CARD_RADIUS = 22            # bplus.css `.glass`: 22-24 px
BUTTON_INSET = 3            # the pill sits 3 px in from the canvas top...
POOL_ROOM = 6               # ...and leaves 6 at its foot for the light under it
ROW_RADIUS = 14

_PICTURES: dict = {}


def _keep(key, draw) -> Image.Image:
    got = _PICTURES.get(key)
    if got is None:
        if len(_PICTURES) > 160:
            _PICTURES.clear()
        got = _PICTURES[key] = draw()
    return got


def _rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*[int(round(v)) for v in rgb[:3]])


def mix(under: str, over, alpha: float) -> str:
    """`over` (an INK name or an (r, g, b)) at `alpha` on the flat colour
    `under`, as a hex — the one colour a flat Tk widget can wear where a
    translucent B+ layer would have been."""
    top = look.INK[over] if isinstance(over, str) else tuple(over)
    base = _rgb(under)
    return _hex(tuple(b + (t - b) * alpha for b, t in zip(base, top)))


def _ground(size, bg) -> Image.Image:
    """What a piece is drawn on: a flat colour, or — for a widget standing
    on the window's sky — the crop of the sky under it (a Pillow image)."""
    if isinstance(bg, Image.Image):
        img = bg.convert("RGBA")
        return img if img.size == (int(size[0]), int(size[1])) else img.resize(
            (int(size[0]), int(size[1])))
    return Image.new("RGBA", (int(size[0]), int(size[1])), _rgb(bg) + (255,))


def _keep_on(key, ground, draw) -> Image.Image:
    """_keep for a picture whose ground may be a crop: a crop is drawn
    fresh (its pixels are the key), a colour is cached."""
    if isinstance(ground, Image.Image):
        return draw()
    return _keep(key, draw)


def photo(widget, image: Image.Image) -> ImageTk.PhotoImage:
    """A PhotoImage in `widget`'s own interpreter, kept on the widget —
    and made ONCE per picture: a face asked for again (a button disabled
    on every tick, a row lit and unlit under the pointer) gets the same
    PhotoImage back, so nothing Tk-bound is made and thrown away while
    the window runs (AGENTS.md: a PhotoImage finalised on the wrong
    thread aborts the process; the fewer there are, the fewer to bury).
    The Pillow picture is kept beside it, so a reused id() can never
    hand back another picture's face."""
    held = getattr(widget, "_tklook_photos", None)
    if held is None:
        held = widget._tklook_photos = {}
        # A widget and its dict are a reference cycle, and a PhotoImage
        # left in one is freed by whichever thread next runs the cyclic
        # collector — a sign-in or download thread, in the middle of an
        # import — whose __del__ then calls a Tcl that is not its own and
        # hangs or aborts (AGENTS.md, Tcl_AsyncDelete; measured here
        # 2026-10-24: the wizard's sign-in thread stuck in
        # ImageTk.PhotoImage.__del__ under `import webbrowser`). So the
        # pictures are let go on the Tk thread, as the widget is destroyed.
        widget.bind("<Destroy>", lambda e, w=widget: _let_go(w, e), add="+")
    got = held.get(id(image))
    if got is not None and got[0] is image:
        return got[1]
    image_tk = ImageTk.PhotoImage(image.convert("RGB"), master=widget)
    if len(held) > 48:                           # a progress fill, many widths
        for key in list(held)[:-24]:
            held.pop(key, None)
    held[id(image)] = (image, image_tk)
    return image_tk


def _let_go(widget, event) -> None:
    """<Destroy> on a widget that holds pictures: drop them here, on the
    thread that owns its interpreter. A child's Destroy bubbles to a
    toplevel's bindings, so only the widget's own counts."""
    if str(event.widget) == str(widget):        # by path: the object may be gone
        held = getattr(widget, "_tklook_photos", None)
        if held:
            held.clear()


# ---------------------------------------------------------------- pictures
def pane(w: int, h: int, *, bg: str = ui.BG, fill: str = ui.CARD,
         radius: float = CARD_RADIUS, border: str | None = None) -> Image.Image:
    """A card's face: the flat face, the inner top light and the frosted
    rim (or, for a card that asks, a 1 px rim in `border` — the question
    on the sentence page keeps its iris edge)."""
    def draw():
        img = _ground((w, h), bg)
        mask = look.rounded((w, h), (0, 0, w, h), radius)
        img.alpha_composite(look.flat((w, h), _rgb(fill) + (255,), mask))
        if border:
            img.alpha_composite(look.flat((w, h), _rgb(border) + (150,),
                                          look.ring_of(mask)))
        else:
            img.alpha_composite(_rim_only(mask, w, h))
        return img
    return _keep_on(("pane", w, h, bg, fill, radius, border), bg, draw)


def _rim_only(mask, w: int, h: int) -> Image.Image:
    """look.glass's top light and rim, without its face (the face here is
    the card's own flat colour, so the widgets on it match it exactly)."""
    from PIL import ImageChops
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shifted = ImageChops.offset(mask, 0, 1)
    shifted.paste(0, (0, 0, w, 1))
    top = ImageChops.subtract(shifted, ImageChops.offset(shifted, 0, 1))
    top = ImageChops.multiply(top, look.ring_of(mask, 2.0))
    out.alpha_composite(look.flat((w, h), look.c("white", look.ALPHA["inner_hi"]), top))
    out.alpha_composite(look.rim(mask, (0, 0, w, h)))
    return out


def pill(w: int, h: int, *, bg: str, kind: str, state: int = 0) -> Image.Image:
    """A button's face, `kind` "primary" | "quiet" | "off", `state` 0 rest,
    1 hover, 2 down. The pill is B+'s 34 px on a 40 px canvas: it sits
    BUTTON_INSET from the top and leaves POOL_ROOM under it for the light
    the lit one pools beneath itself."""
    def draw():
        img = _ground((w, h), bg)
        ph = max(16, h - BUTTON_INSET - POOL_ROOM)
        box = (1, BUTTON_INSET, w - 1, BUTTON_INSET + ph)
        if kind == "primary":
            # the light pooled under the pill reaches past the canvas: draw
            # it on a taller picture and fade its last rows into the ground,
            # so it ends inside the canvas instead of at a cut line
            under = _ground((w, h), bg)
            tall = Image.new("RGBA", (w, h + 16), (0, 0, 0, 0))
            tall.paste(under, (0, 0))
            look.primary(tall, box, hover=state == 1, glow=True)
            if state == 2:
                mask = look.rounded((w, h + 16), box, ph / 2)
                tall.alpha_composite(look.flat((w, h + 16), (20, 15, 51, 40), mask))
            img = _fade_foot(tall.crop((0, 0, w, h)), under, box[3])
        elif kind == "off":
            mask = look.rounded((w, h), box, ph / 2)
            img.alpha_composite(look.flat((w, h), look.c("white", look.ALPHA["disc"]), mask))
        else:
            look.quiet(img, box, hover=state == 1, down=state == 2)
        return img
    return _keep_on(("pill", w, h, bg, kind, state), bg, draw)


def _fade_foot(img: Image.Image, under: Image.Image, from_y: float) -> Image.Image:
    """Ease every row below `from_y` back to `under` (what was there
    before the piece), reaching it on the picture's last row (a
    smoothstep)."""
    import numpy as np
    a = np.asarray(img.convert("RGBA"), np.float32)
    h = a.shape[0]
    start = int(from_y)
    if start >= h - 1:
        return img
    ground = np.asarray(under.convert("RGBA"), np.float32)
    t = np.clip((np.arange(h, dtype=np.float32) - start) / max(1, h - 1 - start), 0.0, 1.0)
    k = (t * t * (3 - 2 * t))[:, None, None]
    out = a * (1 - k) + ground * k
    return Image.fromarray(out.round().astype(np.uint8), "RGBA")


def slip(w: int, h: int, *, bg: str, state: str = "rest",
         radius: float = ROW_RADIUS) -> Image.Image:
    """A row of a list (the microphone page): a breath of frost and a rim
    at rest, a step brighter under the pointer, and the chosen one the
    desk's bubble — glass with violet light pooled in its foot."""
    def draw():
        img = _ground((w, h), bg)
        box = (0, 0, w, h)
        if state == "chosen":
            look.bubble(img, box, radius=radius)
        else:
            look.slip(img, box, radius, lit=state == "hot")
        return img
    return _keep(("slip", w, h, bg, state, radius), draw)


def track(w: int, h: int, *, bg: str) -> Image.Image:
    """A meter's or a progress strip's track: a well, round at both ends."""
    def draw():
        img = _ground((w, h), bg)
        look.well(img, (0, 0, w, h), h / 2)
        return img
    return _keep_on(("track", w, h, bg), bg, draw)


def fill_pill(w: int, h: int, *, colour: str, bg, inset: int = 0) -> Image.Image:
    """What a track (above) holds: a pill of `colour` whose corners are
    the well under it — on a flat `bg` the well's colour; on a crop of the
    sky (`bg` an image the track's size), the track drawn on that crop,
    read `inset` px in, where the fill sits."""
    def draw():
        if isinstance(bg, Image.Image):
            under = track(bg.width, bg.height, bg=bg).crop((inset, inset, inset + w, inset + h))
            img = under.convert("RGBA").copy()
        else:
            well = mix(bg, look.INK["well"], look.ALPHA["well"] / 255.0)
            img = _ground((w, h), well)
        mask = look.rounded((w, h), (0, 0, w, h), h / 2)
        img.alpha_composite(look.flat((w, h), _rgb(colour) + (255,), mask))
        return img
    return _keep_on(("fill", w, h, colour, bg, inset), bg, draw)


# ---------------------------------------------------------------- the sky
class Sky:
    """The desk's night with its fields of light (look.sky, bplus.css
    `.sky`) behind a whole Tk window — the owner's ask of 2026-10-24, on
    seeing it behind the installer's pages: "leave it so, but do it in the
    whole wizard".

    Tk cannot see through a widget: a Label, a Frame, a Canvas are opaque
    rectangles in one flat colour (AGENTS.md). So the sky is ONE picture
    the size of the window, shown on a canvas under everything, and every
    widget that stands on it WEARS its own crop of that picture as its
    background — a container is a canvas whose bottom item is its crop
    (`frame`), a line of words is a Label whose image is its crop with the
    words over it (`SkyLabel`), a button or a card draws its face on its
    crop (`wear`). Where a widget is depends on the layout, so every
    wearer is re-cropped after any of them moves or changes size (one
    pass, on idle); a crop that has not moved is not redrawn.

    Panes (cards) stay opaque — the widgets on them are flat — and the sky
    shows round them, under the words, the buttons and the page's own
    margins: B+'s glass on its night."""

    def __init__(self, root, size, fields=None):
        self.root = root
        self.size = (int(size[0]), int(size[1]))
        w, h = self.size
        self.picture = _keep(("sky", w, h, fields), lambda: look.sky(
            (w, h), **({"fields": fields} if fields else {})).convert("RGBA"))
        self.back = tk.Canvas(root, width=w, height=h, bd=0, highlightthickness=0,
                              bg=ui.BG)
        self.back.create_image(0, 0, anchor="nw", image=photo(self.back, self.picture))
        self.back.place(x=0, y=0)
        # under every sibling (Canvas.lower is the ITEM command; this is the window's)
        self.root.tk.call("lower", self.back._w)
        self._wearers: list = []
        self._pending = None
        root.bind_class("TklookSky", "<Configure>", lambda _e: self.later(), add="+")
        # a repaint still queued when the window goes would fire into a
        # destroyed interpreter ("invalid command name ...refresh")
        self.back.bind("<Destroy>", lambda _e: self._cancel(), add="+")

    def _cancel(self) -> None:
        if self._pending is not None:
            try:
                self.root.after_cancel(self._pending)
            except tk.TclError:
                pass
            self._pending = None
        self._wearers = []

    # -- where a widget is, and what is behind it
    def where(self, widget) -> tuple[int, int]:
        x = y = 0
        node = widget
        while node is not None and node is not self.root:
            x += node.winfo_x()
            y += node.winfo_y()
            node = node.master
        return x, y

    def crop(self, widget, w: int | None = None, h: int | None = None) -> Image.Image:
        x, y = self.where(widget)
        w = max(1, int(w if w is not None else widget.winfo_width()))
        h = max(1, int(h if h is not None else widget.winfo_height()))
        return self.picture.crop((x, y, x + w, y + h))

    # -- the wearers
    def wear(self, widget):
        """Have `widget` (anything with a `_wear(sky)`) show its crop, now
        and whenever the layout moves it."""
        widget.bindtags(widget.bindtags() + ("TklookSky",))
        self._wearers.append(widget)
        self.later()
        return widget

    def later(self) -> None:
        if self._pending is None:
            try:
                self._pending = self.root.after_idle(self.refresh)
            except tk.TclError:
                self._pending = None

    def refresh(self) -> None:
        self._pending = None
        alive = []
        for widget in self._wearers:
            try:
                if not widget.winfo_exists():
                    continue
            except tk.TclError:
                continue
            alive.append(widget)
            try:
                widget._wear(self)
            except tk.TclError:
                pass
        self._wearers = alive

    def frame(self, parent, **kw) -> "SkyFrame":
        return self.wear(SkyFrame(parent, self, **kw))

    def label(self, parent, **kw) -> "SkyLabel":
        return self.wear(SkyLabel(parent, self, **kw))


class TrackBar(tk.Canvas):
    """A slim progress track standing on the sky (the wizard's downloads
    strip): its bottom item is the well drawn on the sky's crop; the
    caller draws the fill over it."""

    def __init__(self, parent, sky, w: int, h: int):
        super().__init__(parent, width=w, height=h, bd=0, highlightthickness=0, bg=ui.BG)
        self._size = (w, h)
        self._item = self.create_image(0, 0, anchor="nw")
        self._shown = None
        sky.wear(self)

    def _wear(self, sky) -> None:
        key = sky.where(self) + self._size
        if key == self._shown:
            return
        self._shown = key
        self.itemconfig(self._item, image=photo(self, track(
            *self._size, bg=sky.crop(self, *self._size))))


class SkyFrame(tk.Canvas):
    """A container on the sky: a canvas (pack works in any widget) whose
    bottom item is the sky under it, with its children packed over it."""

    def __init__(self, parent, sky, **kw):
        kw.setdefault("bg", ui.BG)
        super().__init__(parent, width=kw.pop("width", 1), height=kw.pop("height", 1),
                         bd=0, highlightthickness=0, **kw)
        self.sky = sky
        self._bg_item = self.create_image(0, 0, anchor="nw")
        self._shown = None

    def _wear(self, sky) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        key = sky.where(self) + (w, h)
        if key == self._shown or w < 1 or h < 1:
            return
        self._shown = key
        self.itemconfig(self._bg_item, image=photo(self, sky.crop(self, w, h)))


class SkyLabel(tk.Label):
    """A Label on the sky: its own crop as its image, its words drawn over
    it (`compound="center"`, and an image exactly the size of the words,
    so they stay where a plain Label puts them). `picture` (RGBA) is drawn
    on the crop instead of words — the mark, a Hebrew paragraph from
    text_pil. Packed WITHOUT fill: a Label wider than its words would show
    its flat colour beside them."""

    def __init__(self, parent, sky, picture=None, **kw):
        for key, value in (("bd", 0), ("padx", 0), ("pady", 0),
                           ("highlightthickness", 0)):
            kw.setdefault(key, value)
        kw.setdefault("bg", ui.BG)
        super().__init__(parent, **kw)
        self.sky = sky
        self._picture = picture
        self._shown = None
        self._size = (1, 1)
        self._measure()

    def _measure(self) -> None:
        """The size of the words alone (a Label computes it at configure
        time), or of the picture."""
        if self._picture is not None:
            self._size = self._picture.size
            return
        super().configure(image="")
        self._size = (max(1, self.winfo_reqwidth()), max(1, self.winfo_reqheight()))

    def configure(self, cnf=None, **kw):
        if not kw and cnf is None:
            return super().configure()
        if isinstance(cnf, str):
            return super().configure(cnf)
        shape = {"text", "font", "wraplength", "justify", "picture"} & set(kw) or \
            (cnf and {"text", "font", "wraplength", "justify"} & set(cnf))
        if "picture" in kw:
            self._picture = kw.pop("picture")
        out = super().configure(cnf, **kw) if (cnf or kw) else None
        if shape:
            self._measure()
            self._shown = None
            self._wear(self.sky)
        return out

    config = configure

    def _wear(self, sky) -> None:
        key = sky.where(self) + self._size
        if key == self._shown:
            return
        self._shown = key
        crop = sky.crop(self, *self._size)
        if self._picture is not None:
            crop.alpha_composite(self._picture.convert("RGBA"))
        super().configure(image=photo(self, crop), compound="center")


# ---------------------------------------------------------------- widgets
class Card(tk.Canvas):
    """ui.Card in B+: a pane with a frame inside it to put widgets in.
    `body` is an ordinary Frame in `fill`, so labels on it take `bg=CARD`
    exactly as they did."""

    def __init__(self, parent, w: int, h: int, *, radius: float = CARD_RADIUS,
                 fill: str = ui.CARD, bg: str = ui.BG, border: str | None = None,
                 pad: int = 16, sky: "Sky | None" = None):
        super().__init__(parent, width=w, height=h, bg=bg,
                         highlightthickness=0, bd=0)
        self.w, self.h, self.fill = w, h, fill
        self._radius, self._ground, self._border, self._pad = radius, bg, border, pad
        self.sky = sky
        self._shown = None
        self.face_item = self.create_image(0, 0, anchor="nw", image=self._face(h))
        self.body = tk.Frame(self, bg=fill)
        self._body_item = self.create_window(pad, pad, anchor="nw", window=self.body,
                                             width=w - 2 * pad, height=h - 2 * pad)
        if sky is not None:
            sky.wear(self)

    def _face(self, h: int, ground=None):
        return photo(self, pane(self.w, h, bg=ground if ground is not None else self._ground,
                                fill=self.fill, radius=self._radius, border=self._border))

    def _wear(self, sky) -> None:
        """On the sky: the pane's corners are the sky's own pixels."""
        key = sky.where(self) + (self.w, self.h)
        if key == self._shown:
            return
        self._shown = key
        self.itemconfig(self.face_item, image=self._face(self.h, sky.crop(self, self.w, self.h)))

    def resize(self, h: int) -> None:
        h = max(2 * self._pad + 1, int(h))
        self.h = h
        self.configure(height=h)
        self.itemconfig(self.face_item, image=self._face(h))
        self.itemconfig(self._body_item, height=h - 2 * self._pad)
        if self.sky is not None:
            self._shown = None
            self.sky.later()

    def face(self, image) -> None:
        self.itemconfig(self.face_item, image=image)


class Button(ui.Button):
    """ui.Button in B+: the lit pill for the one primary action on a page,
    the quiet pill of frost for everything else."""

    def _build_faces(self, primary: bool, quiet: bool) -> list:
        kind = "primary" if primary else "quiet"
        ground = self._crop if self._crop is not None else self._bg
        return [photo(self, pill(self._width, self._height, bg=ground,
                                 kind=kind, state=s)) for s in (0, 1, 2)]

    def _wear(self, sky) -> None:
        """On the sky: the pill (and the light under the lit one) drawn on
        the sky's own pixels."""
        key = sky.where(self) + (self._width, self._height)
        if key == self._shown:
            return
        self._shown = key
        self._crop = sky.crop(self, self._width, self._height)
        self._off = None
        self._faces = self._build_faces(self._primary, self._quiet)
        self.enable(self._enabled)

    @staticmethod
    def _face_colour(primary: bool, quiet: bool, fg: str | None) -> str:
        if primary:
            return ui.ACCENT_ON
        return fg or (ui.DIM if quiet else ui.FG)

    def __init__(self, parent, text: str, command=None, **kw):
        self.sky = kw.pop("sky", None)
        self._crop = None
        self._off = None
        self._shown = None
        super().__init__(parent, text, command, **kw)
        # the label rides on the pill, which sits above the light under it
        mid = BUTTON_INSET + (self._height - BUTTON_INSET - POOL_ROOM) / 2 + 1
        x = self.coords(self._label)[0]
        self.coords(self._label, x, mid)
        if self._icon_item is not None:
            self.coords(self._icon_item, self.coords(self._icon_item)[0], mid)
        if self.sky is not None:
            self.sky.wear(self)

    def enable(self, on: bool) -> None:
        """Disabled is the desk's `.btn.dis`: a flat disc of frost and the
        third voice, and no hand cursor."""
        self._enabled = on
        self.config(cursor="hand2" if on else "arrow")
        if on:
            self.itemconfig(self._image, image=self._faces[0])
        else:
            if getattr(self, "_off", None) is None:
                # once per ground: a button disabled on every tick makes
                # nothing new (a crop's face is drawn fresh, not cached)
                self._off = photo(self, pill(
                    self._width, self._height,
                    bg=self._crop if self._crop is not None else self._bg, kind="off"))
            self.itemconfig(self._image, image=self._off)
        colour = self._colour if on else MUTED
        self.itemconfig(self._label, fill=colour)
        if self._icon_item is not None:
            self.itemconfig(self._icon_item, fill=colour)


class Switch(tk.Canvas):
    """ui.Switch in B+: no accent — on is a soft lavender-grey track with
    a white knob, off a hollow ring with a grey one."""

    def __init__(self, parent, value: bool = False, command=None, bg: str = ui.CARD):
        super().__init__(parent, width=ui.SWITCH_W, height=ui.SWITCH_H, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._bg = bg
        self._faces = {}
        for on in (False, True):
            self._faces[on] = photo(self, _keep(("switch", bg, on), lambda on=on: self._draw(on)))
        self._image = self.create_image(0, 0, anchor="nw", image=self._faces[False])
        self._value = value
        self._command = command
        self.bind("<Button-1>", lambda _e: self.toggle())
        self.set(value)

    def _draw(self, on: bool) -> Image.Image:
        w, h = ui.SWITCH_W, ui.SWITCH_H
        img = _ground((w, h), self._bg)
        s = min(w / 40.0, h / 22.0) * 0.98
        look.switch(img, (w - 40 * s) / 2, (h - 22 * s) / 2, on, s=s)
        return img

    def set(self, on: bool) -> None:
        self._value = bool(on)
        self.itemconfig(self._image, image=self._faces[self._value])

    def get(self) -> bool:
        return self._value

    def toggle(self) -> None:
        self.set(not self._value)
        if self._command:
            self._command(self._value)


class Field(ui.Field):
    """ui.Field in B+: the writing well. The Entry sits flat on the well's
    own colour (the well's .42 night composited onto the card), which is
    the only way an opaque Entry disappears into it; hover and focus
    change the RIM and never the fill, for the reason ui.Field gives."""

    def __init__(self, parent, value: str = "", *, w: int = 150, h: int = 30,
                 radius: int = 11, bg: str = ui.CARD, **kw):
        super().__init__(parent, value, w=w, h=h, radius=radius, bg=bg, **kw)
        well = mix(bg, look.INK["well"], look.ALPHA["well"] / 255.0)
        faces = []
        for state in ("rest", "hover", "focus"):
            faces.append(photo(self, _keep(("well", w, h, bg, radius, state),
                                           lambda s=state: self._draw(w, h, bg, radius, well, s))))
        self._faces = faces
        self.entry.configure(bg=well, disabledbackground=well, readonlybackground=well,
                             insertbackground=ui.FG, selectbackground=ui.ACCENT_SOFT)
        self.itemconfig(self._image, image=self._faces[0])

    @staticmethod
    def _draw(w, h, bg, radius, well, state) -> Image.Image:
        img = _ground((w, h), bg)
        mask = look.rounded((w, h), (0, 0, w, h), radius)
        img.alpha_composite(look.flat((w, h), _rgb(well) + (255,), mask))
        ring = look.ring_of(mask)
        if state == "focus":
            img.alpha_composite(look.flat((w, h), look.c("iris", 150), ring))
        else:
            img.alpha_composite(look.flat((w, h), look.c("white", 22 if state == "rest" else 44), ring))
        return img


class KeyCap(ui.KeyCap):
    """ui.KeyCap in B+: the desk's key cap (radius 7, its foot in shadow,
    its top edge lit), its words at the label weight rather than bold,
    and an iris ring while the wizard listens for its key."""

    def __init__(self, parent, text: str, command=None, *, bg: str = ui.CARD,
                 w: int = 122, h: int = ui.CAP_H):
        super().__init__(parent, text, command, bg=bg, w=w, h=h)
        self._bg, self._cw, self._ch = bg, w, h
        self._idle = photo(self, self._draw(False, False))
        self._hover = photo(self, self._draw(True, False))
        self._lit = photo(self, self._draw(False, True))
        self._on = False
        self.itemconfig(self._image, image=self._idle)
        self.bind("<Enter>", lambda _e: self.itemconfig(
            self._image, image=self._lit if self._on else self._hover))
        self.bind("<Leave>", lambda _e: self.itemconfig(
            self._image, image=self._lit if self._on else self._idle))
        self.set(text)

    def _draw(self, hover: bool, lit: bool) -> Image.Image:
        def draw():
            w, h = self._cw, self._ch
            img = _ground((w, h), self._bg)
            box = (1, 1, w - 1, h - 1)
            look.keycap(img, box, hover=hover)
            if lit:
                mask = look.rounded((w, h), (0, 0, w, h), 8)
                img.alpha_composite(look.flat((w, h), look.c("iris", 200), look.ring_of(mask, 1.6)))
            return img
        return _keep(("cap", self._cw, self._ch, self._bg, hover, lit), draw)

    def set(self, text: str) -> None:
        """ui.KeyCap.set, at B+'s label weight: the binding at the largest
        size that fits the cap, never bold."""
        off = text.lower() in ("", "off")
        shown = text or "off"
        size = ui.PT_BODY
        room = self.winfo_reqwidth() - 16
        while size > ui.PT_CAPS - 2 and ui._text_width(shown, size) > room:
            size -= 1
        self.itemconfig(self._label, text=shown, font=(ui.UI, size),
                        fill=ui.FAINT if off else ui.FG)

    def lit(self, on: bool) -> None:
        self._on = bool(on)
        if hasattr(self, "_lit"):
            self.itemconfig(self._image, image=self._lit if on else self._idle)
