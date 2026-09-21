"""The shelf's window, thread and queue — the presenter half.

`shelf_card.py` owns the words, the geometry and the picture; this owns
the thread, the queue, the window and every decision about them.
`skin\\shelf.py` paints the real one on glass, and `_build_and_loop`
below is the flat Tk card that comes back when `skin\\` is deleted.

WHY THIS IS A MODULE AND NOT A CLASS IN overlay.py. Every other card in
this app lives there, and this one is the same shape — it subclasses
`overlay.HintCard` and inherits the queue, the hush, the placement and
the corner rule unchanged. It sits in its own file so that the shelf can
be built without touching a file that three other people's work is also
in. Nothing here is a new contract; overlay.py is still where the
contract is written down.

AND IT CLOSES WHEN HE LOOKS AWAY. The owner, 2026-09-07: "when I press
the dot and the screen opens — I want that if I press outside of it, like
on Google or something, the small tab that opens when I press the dot
will disappear, so I will not need to press the dot again or the X." So
there is a fifth door, and it is the one every panel like this has: a
press of a mouse button anywhere that is not the panel takes it down.

HOW IT IS SEEN, AND WHY IT IS NOT A FOCUS EVENT. This window never has
the focus to lose. On the glass path it is a plain CreateWindowExW popup
carrying WS_EX_NOACTIVATE shown with SW_SHOWNOACTIVATE, and on the Tk
path `overlay._no_activate` puts the same flag on; that is deliberate —
a panel that stole the keyboard would interrupt whatever he was typing —
and it means WM_KILLFOCUS, WM_ACTIVATE and Tk's <FocusOut> never arrive
at all. What this app already does when it needs to know about a key or
a button it was not sent is ASK: capture.py, visual_qa.py and popup.py
all watch Escape with GetAsyncKeyState, which needs no focus, costs
microseconds and is the same question from any thread. `_away_loop` asks
the same way about the mouse, on its own thread, only while the panel is
up, and only about the DOWN EDGE — the button going from up to down —
so the press that opened the panel (the button is still down when the
dot's WM_LBUTTONDOWN fires) is never mistaken for the press that closes
it.

THE DOT IS NOT "AWAY", and that is the trap this had to be written
around. A click on the dot is a click outside the panel, and the dot is
already a toggle: seeing it as away would close the panel and let the
dot's own handler reopen it in the same press. So `spare` names the
squares a press may land on without closing anything, and main.py points
it at the status dot's window. The panel's OWN buttons need no such
exception — they are inside its rect.

AND IT IS ANCHORED TO THE DOT, since 2026-09-21. The owner, with the dot
dragged to the middle of the screen and the panel still opening in a
corner: "I want the tab to move with it together." Three rules used to
decide where it opened (overlay.HintCard.origin: his own drag of the
panel, then the dot if dragged, then the corner), and the first of them
was what he was looking at — a drag from a fortnight ago (`[shelf] x/y`)
pinned the panel to the top-right while the dot went wherever it went.
So this panel's `origin` asks the dot FIRST and ALWAYS when it follows
one (main.App._dot_rect hands it the dot's rectangle whether or not the
dot has been dragged), `beside_dot` puts it above or below the dot, and
skin\\shelf.py draws the face as a bubble whose tail sweeps out toward
the dot (skin\\bubble.py). A drag of the panel moves it for that opening
and is NOT remembered (`placed` below): a bubble that stayed where it
was dragged while the dot moved on would point at nothing. `[shelf]
x/y` still apply to a panel whose file names a corner of its own.

WHAT IT IS. A panel beside the status dot listing everything waiting for
an answer, with the owner's rule for it, verbatim: **it opens only on the
key press; the same press or Esc closes it; never on hover, never on
passing the corner.** That rule is what makes a panel this tall
acceptable at all — it is never on screen unless he asked for it half a
second ago — and it is why:

- there is no `after_ms` delay and no clock. Nothing takes it down but
  him;
- `on_key` claims Esc WITHOUT the pointer-over-it gate that
  `overlay.ReviewCard` and `overlay.NotifyCard` both use. Those two
  arrive uninvited, so eating a keystroke away from them would eat a
  letter somebody was typing; this one was asked for, and while it is up
  Esc means "close it";
- `dismissed()` is refused. That is the hint card's "don't show this
  again" and it writes `enabled = false` into config.toml. Closing the
  shelf is not a dismissal, and the NotifyCard docstring makes the same
  point in capitals.

IT TAKES CLICKS, which is the one thing the hint card may not do. Every
pixel that is not a named rectangle answers HTTRANSPARENT
(`shelf_card.hit_test`), including the whole shadow margin, so a click
aimed at whatever is underneath still lands there — the trap the status
dot paid for once already, back when both lived on the close button of
every maximised window. One of the named rectangles is the X at the
top-right of the head band (`shelf_card.CLOSE`): a press there is
`pressed("close")`, which main.py routes to `_shelf_close`, the same
door ctrl+alt+d and Esc use. It opens beside the dot — ABOVE a
bottom-right dot, which is where the dot lives now — and never over it.

EVERY CALLBACK FIRES ON THE PAINTER'S THREAD, so `on_press` and
`on_refresh` may only enqueue or spawn. That is `_notify_dismissed`'s rule
and it is not negotiable: the painter's pump must never wait on a disk, a
clipboard or a model.
"""
from __future__ import annotations

import ctypes
import logging
import queue
import threading

import overlay
import shelf_card as sc

try:
    import skin
except Exception:                                   # noqa: BLE001
    skin = None

_log = logging.getLogger("app")

# How often the panel asks main.py whether anything it is showing has
# moved. A second is fast enough that a notification arriving while he
# reads the panel is on it before he has finished reading, and slow
# enough to be free: the answer is three os.stat-sized stamps and a
# length, and the rebuild is skipped when they have not changed
# (main.App._shelf_card). The uptime line wants the same tick anyway.
REFRESH_S = 1.0

# How often the mouse is asked whether a button has just gone down, while
# the panel is up and only then. 25 ms: a click holds the button for
# 50-150 ms, so nothing real is missed, and the question is two
# GetAsyncKeyState calls and one GetCursorPos — the same three-microsecond
# question capture.py asks about Escape forty times a second while a
# selection is live. With the panel DOWN the loop still wakes on this
# beat but asks nothing: it reads one attribute, finds no panel and goes
# back to sleep, which is cheaper than the 50 Hz tick the panel's own
# painter has run at for the whole life of the app since it was written.
AWAY_S = 0.025
# The buttons a press on which means "I am doing something over there".
# Left and right: a left click is the case he described, and a right
# click is a context menu opening somewhere else, which is the same
# thing. The middle button is left out — it is the wheel, and pressing
# the wheel to scroll should not take a panel down.
AWAY_BUTTONS = (0x01, 0x02)               # VK_LBUTTON, VK_RBUTTON


def away_from(point, rect, spares=()) -> bool:
    """Is a press at `point` outside the panel and outside everything
    that is allowed to be pressed without closing it?

    `rect` is (left, top, right, bottom) of the visible panel, and None
    means there is no panel on screen — nothing to close, so nothing is
    away. `spares` is the same shape, and holds the status dot's window:
    see the module docstring for why that square is the one exception.

    Pure, so the rule can be checked without a window, a mouse or a
    screen — which matters, because a hidden desktop has no pointer to
    click with.
    """
    if rect is None:
        return False
    x, y = point

    def inside(box) -> bool:
        return (box is not None
                and box[0] <= x <= box[2] and box[1] <= y <= box[3])

    if inside(rect):
        return False
    return not any(inside(box) for box in (spares or ()))


class ShelfCard(overlay.HintCard):
    """The panel beside the dot. Built once at startup, shown on a key.

    `rows` is carried here rather than looked up in the config every time
    because the thing that builds the card (`main.App._shelf_card`) runs
    on a worker and this object is what both halves already share.
    """

    CORNERS = ("top-right", "top-left", "bottom-right", "bottom-left")
    # The face's distance from the dot's window: the tail's length plus a
    # little daylight, so the tip stops just short of the halo
    # (skin\bubble). overlay.DOT_GAP is the key card's 18.
    DOT_GAP = 30

    def __init__(self, corner: str = "bottom-right", margin: int = 14,
                 x: int = overlay.HINT_UNSET, y: int = overlay.HINT_UNSET,
                 scale: float = 1.0, rows: int = sc.PILE_MAX,
                 on_change=None, on_press=None, on_refresh=None,
                 on_away=None, spare=None,
                 dot_corner: str = "bottom-right", dot_at=None) -> None:
        # `dot_corner` is where the status dot STARTS: the panel opens
        # BESIDE it — above a bottom-right dot, to the left of a
        # top-right one — and never over it (overlay.HintCard.origin,
        # DOT_ROOM). `dot_at` is where the dot actually IS once he has
        # dragged it somewhere that is not a corner at all, which is the
        # thing he asked for on 2026-09-08: "I want it to be able to move
        # where the dot is." Both are the base class's; this panel adds
        # nothing to the rule, which is the point — the shelf and the key
        # card cannot disagree about where "beside the dot" is.
        super().__init__(after_ms=0, corner=corner, margin=margin, x=x, y=y,
                         scale=scale, on_change=on_change,
                         dot_corner=dot_corner, dot_at=dot_at)
        self.rows = max(sc.ROWS_MIN, min(sc.ROWS_MAX, int(rows)))
        self._on_press = on_press
        self._on_refresh = on_refresh
        # He pressed somewhere else, so the panel goes away. main.py
        # points this at the same `_shelf_close` the key, Esc, the X and
        # a second click on the dot all go through — closing the panel is
        # more than hiding a window (the notification column comes back,
        # the key card comes back, Stop disarms) and that knowledge lives
        # there, not here.
        self._on_away = on_away
        # What may be pressed without counting as away: the status dot's
        # own square. See the module docstring — it is a toggle, so
        # closing for it would close and reopen in one press.
        self._spare = spare
        self.rect = None            # the visible panel's screen rect, or None
        self._current = None        # the card dict on screen, or None
        self._state_lock = threading.Lock()
        self._refresher: threading.Thread | None = None
        self._watcher: threading.Thread | None = None

    # -- where it opens --

    def origin(self, width: int, height: int, screen, inset: int = 0,
               bounds=None, work=None) -> tuple[int, int]:
        """Beside the dot, first and always, when this panel follows one
        — see the module docstring. The field is the work area of the
        monitor the dot is on, inset by the panel's own margin so the
        face keeps its distance from the screen's edge the way the
        corner rule always kept it; the gap is the tail's. Without a dot
        to follow (no `dot_at`, no dot, a dot that will not say where it
        is) the base class's three rules apply as before."""
        dot = self.dot_now()
        if dot is None:
            return super().origin(width, height, screen, inset, bounds, work)
        sw, sh = screen
        m = self._margin
        card_w, card_h = width - inset * 2, height - inset * 2
        fx, fy, fw, fh = (overlay._monitor_work((dot[0] + dot[2]) // 2,
                                                (dot[1] + dot[3]) // 2)
                          or work or bounds or (0, 0, sw, sh))
        field = (fx + m, fy + m, max(1, fw - 2 * m), max(1, fh - 2 * m))
        x, y = overlay.beside_dot(dot, (card_w, card_h), field,
                                  self.DOT_GAP, bounds)
        return int(x - inset), int(y - inset)

    def placed(self, x: int, y: int) -> None:
        """A drag moved the panel for THIS opening and nothing is written:
        a follower is anchored to the dot and opens beside it next time.
        A panel whose file names a corner of its own is remembered as
        every card is (HintCard.placed)."""
        if self._dot_at is not None:
            _log.debug("shelf: dragged aside for now — it opens beside the "
                       "dot again next time")
            return
        super().placed(x, y)

    # -- caller's thread --

    def start(self) -> None:
        if not self._enabled:
            return
        try:
            import tkinter  # noqa: F401
        except Exception:
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="shelf-card")
        self._thread.start()
        self._alive.wait(timeout=3)
        # The tick that keeps the uptime and the pile honest while the
        # panel is up. Its own thread and not the painter's, so the two
        # paint paths (glass and Tk) get the same behaviour from one
        # implementation, and so that a slow rebuild can never stall a
        # click. It does nothing at all while the panel is down.
        self._refresher = threading.Thread(target=self._refresh_loop,
                                           daemon=True, name="shelf-refresh")
        self._refresher.start()
        # And the watch for a press that lands somewhere else. Its own
        # thread for the same two reasons: one implementation serves both
        # paint paths, and a close must never be decided from inside the
        # painter's pump.
        self._watcher = threading.Thread(target=self._away_loop, daemon=True,
                                         name="shelf-away")
        self._watcher.start()

    def show(self, card: dict | None) -> None:
        """Put the panel up, or take it down with None.

        Safe from any thread — it only enqueues. A card that arrives while
        one is up replaces it in place, which is what a refresh is.
        """
        if self._thread is None or not self._enabled:
            return
        if card is None:
            self.hide()
            return
        with self._state_lock:
            self._current = card
        self._q.put(card)

    def hide(self) -> None:
        with self._state_lock:
            self._current = None
        if self._thread is not None:
            self._q.put(None)

    def visible(self) -> bool:
        return self._current is not None

    def current(self) -> dict | None:
        with self._state_lock:
            return self._current

    def hovering(self) -> bool:
        """Is the pointer on the panel right now? A rect and a point, no
        window handle. NOT used to gate Esc — see the module docstring —
        but the presenter and a test both want the honest answer."""
        rect = self.rect
        if rect is None or not self.visible():
            return False
        try:
            pt = ctypes.wintypes.POINT()
            ctypes.WinDLL("user32").GetCursorPos(ctypes.byref(pt))
        except Exception:
            return False
        return rect[0] <= pt.x <= rect[2] and rect[1] <= pt.y <= rect[3]

    def on_key(self, vk: int) -> bool:
        """A key-down from the hook. Esc closes it, wherever the pointer is.

        True swallows the key, and `main.App._popup_key` returns before
        the state machine's `cancel_guard` is reached — which is what
        keeps this Esc from also throwing away a locked recording. Exactly
        one vk is ever claimed, and only while the panel is up, so nothing
        else on the keyboard is affected.
        """
        if int(vk) != 0x1B or not self.visible():
            return False
        self.hide()
        return True

    def dismissed(self) -> None:
        """Never. HintCard's version writes `enabled = false` into
        config.toml, which is "don't show this again" — and closing a
        panel you opened with a key is not that."""
        _log.debug("shelf: dismissed() is not this card's close")

    # -- the painter's thread --

    def pressed(self, name: str) -> None:
        """A click on a named rectangle, resolved against the card that
        drew it and handed on.

        Fired on the presenter's thread, so `on_press` may only enqueue or
        spawn. What an answer MEANS is main.py's business: this passes the
        verb and the id through untouched, exactly as
        `overlay.NotifyCard.pressed` passes an item id.
        """
        card = self.current()
        if card is None or self._on_press is None:
            return
        what = sc.action_at(card, name)
        if what is None:
            return
        try:
            self._on_press(what)
        except Exception:                            # noqa: BLE001
            _log.info("the shelf could not act on %r", name, exc_info=True)

    # -- the refresher's thread --

    def _refresh_loop(self) -> None:
        """Ask for a fresh card once a second, while one is up.

        `on_refresh` returns a card dict when something it is showing has
        changed and None when nothing has — main.py compares three store
        stamps before it reads anything, so the usual answer is None and
        the usual cost of this thread is one comparison a second.
        """
        while not self._closing.wait(REFRESH_S):
            try:
                if not self.visible() or self._on_refresh is None:
                    continue
                fresh = self._on_refresh()
                if fresh is not None and self.visible():
                    self.show(fresh)
            except Exception:                        # noqa: BLE001
                _log.debug("the shelf's refresh stumbled", exc_info=True)

    # -- the watcher's thread --

    def _away_loop(self) -> None:
        """Take the panel down when a mouse button goes down anywhere
        else. The fifth door — see the module docstring for why this is a
        poll and not a focus event.

        THE DOWN EDGE, and only the down edge. `GetAsyncKeyState`'s high
        bit says the button is down NOW; the state is remembered here and
        a close is decided on the transition, which is what keeps the
        press that OPENED the panel — the button is still down while the
        dot's WM_LBUTTONDOWN is being handled — from immediately closing
        it again. The low bit ("pressed since you last asked") is
        deliberately not used: it is consumed by whoever asks first, and
        three other files in this app ask about keys.

        `self.rect is None` means there is no panel on screen to close —
        it is down, or it is HUSHED off the live screen because he is
        dragging a screenshot selection, and a drag is exactly the press
        that must not close anything.
        """
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            point = ctypes.wintypes.POINT()
        except Exception:                            # noqa: BLE001
            _log.debug("the shelf cannot watch the mouse", exc_info=True)
            return
        # "Assume the button is already down", which is what makes the
        # first sample after the panel appears an edge that never fires.
        was_down = True
        while not self._closing.wait(AWAY_S):
            try:
                rect = self.rect
                if rect is None or self._on_away is None \
                        or not self.visible():
                    # Nothing on screen to close: the panel is down, or
                    # it is HUSHED off the live screen because he is
                    # dragging a screenshot selection. The mouse is not
                    # asked at all, and the latch is re-armed so that the
                    # press which brings the panel back — a click on the
                    # dot, with the button still down while the dot's
                    # handler runs — is not read as a press away from it.
                    was_down = True
                    continue
                down = any(user32.GetAsyncKeyState(vk) & 0x8000
                           for vk in AWAY_BUTTONS)
                pressed, was_down = down and not was_down, down
                if not pressed:
                    continue
                if not user32.GetCursorPos(ctypes.byref(point)):
                    continue
                spares = self._spare() if self._spare is not None else ()
                if not away_from((point.x, point.y), rect, spares):
                    continue
                _log.info("shelf: closed by a press at %d, %d — outside it",
                          point.x, point.y)
                self._on_away()
            except Exception:                        # noqa: BLE001
                _log.debug("the shelf's watch on the mouse stumbled",
                           exc_info=True)

    # -- the presenter's own thread --

    def _run(self) -> None:
        try:
            if skin is not None and skin.shelf_run(self):   # --- SKIN
                return
            self._build_and_loop()
        except Exception as e:                       # noqa: BLE001
            _log.info("shelf unavailable: %r", e)
        finally:
            self._alive.set()

    def _build_and_loop(self) -> None:
        """The flat Tk panel: what is on screen when skin\\ is gone.

        `shelf_card.flat()` paints the whole panel as one opaque image;
        this window shows it, moves it, and turns a click, a drag or a
        hush into `pressed` or `placed`. overlay.NotifyCard's fallback is
        the one this copies, mouse handling included — CLICK_PX and the
        press/release discrimination — with one difference that matters:
        `_no_activate` is called WITHOUT `click_through`, because unlike
        the hint card this panel has buttons on it.

        THE WINDOW IS THE CARD, NOT THE PICTURE. flat()'s image is the
        card alone; the SHADOW margin every hit test speaks in is added
        back to each mouse coordinate here.
        """
        import tkinter as tk

        from PIL import ImageTk

        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=overlay.CARD_BG)
        canvas = tk.Canvas(root, bg=overlay.CARD_BG, highlightthickness=0,
                           bd=0)
        canvas.pack()
        self._alive.set()

        st = {"card": None, "up": False, "hover": None, "drag": None,
              "from": None, "moved": 0, "photo": None, "hushed": False}
        cache: dict = {}
        CLICK_PX = 4          # a release that travelled less is a click

        def hide() -> None:
            st["card"], st["hover"] = None, None
            st["drag"] = None
            self.rect = None
            cache.clear()
            if st["up"]:
                root.withdraw()
                st["up"] = False

        def paint() -> None:
            if st["card"] is None:
                return
            img = sc.flat(st["card"], self.scale, st["hover"], cache)
            photo = ImageTk.PhotoImage(img, master=root)
            canvas.delete("all")
            canvas.configure(width=img.width, height=img.height)
            canvas.create_image(0, 0, anchor="nw", image=photo)
            st["photo"] = photo               # Tk keeps no reference

        def map_card() -> None:
            if st["card"] is None:
                return
            w, h = sc.measure(st["card"], self.scale)
            # bounds as well as work: a panel that follows a dot onto
            # the monitor to the left has to be clamped against the whole
            # desktop, not the primary. overlay.HintCard._build_and_loop
            # says the rest.
            x, y = self.origin(w, h, (root.winfo_screenwidth(),
                                      root.winfo_screenheight()),
                               bounds=overlay._virtual_screen(),
                               work=overlay._work_area())
            paint()
            root.geometry(f"{w}x{h}+{x}+{y}")
            self.rect = (x, y, x + w, y + h)
            root.deiconify()
            root.update_idletasks()
            if not st["up"]:
                # Needs a realised window and silently succeeds on an
                # unrealised one — the bug that put the dot on the close
                # button. Click-TAKING, not click-through: this panel's
                # buttons are the whole point of it.
                overlay._no_activate(root)
            st["up"] = True

        def set_hushed(on: bool) -> None:
            if on == st["hushed"]:
                return
            st["hushed"] = on
            if on:
                if st["up"]:
                    root.withdraw()
                    st["up"] = False
                self.rect = None
            elif st["card"] is not None:
                map_card()

        def hit(event):
            if st["card"] is None:
                return sc.HTTRANSPARENT, None
            return sc.hit_test(st["card"], self.scale, event.x + sc.SHADOW,
                               event.y + sc.SHADOW, cache)

        def on_press(event) -> None:
            code, what = hit(event)
            if code == sc.HTCLIENT and what:
                self.pressed(what)
            elif code == sc.HTCAPTION:
                st["drag"] = (event.x_root - root.winfo_x(),
                              event.y_root - root.winfo_y())
                st["from"] = (event.x_root, event.y_root)
                st["moved"] = 0

        def on_motion(event) -> None:
            if st["drag"] is not None:
                ox, oy = st["from"]
                st["moved"] = max(st["moved"], abs(event.x_root - ox)
                                  + abs(event.y_root - oy))
                if st["moved"] < CLICK_PX:
                    return                # still a click until it is not
                dx, dy = st["drag"]
                root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")
                return
            code, what = hit(event)
            want = what if code == sc.HTCLIENT else None
            if want != st["hover"]:
                st["hover"] = want
                paint()

        def on_leave(_event) -> None:
            if st["hover"] is not None:
                st["hover"] = None
                paint()

        def on_release(_event) -> None:
            if st["drag"] is None:
                return
            st["drag"] = None
            if st["moved"] < CLICK_PX:
                return                    # the head is a handle, not a button
            x, y = root.winfo_x(), root.winfo_y()
            if st["card"] is not None:
                w, h = sc.measure(st["card"], self.scale)
                self.rect = (x, y, x + w, y + h)
            self.placed(x, y)

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_motion)
        canvas.bind("<Motion>", on_motion)
        canvas.bind("<Leave>", on_leave)
        canvas.bind("<ButtonRelease-1>", on_release)

        def pump() -> None:
            try:
                while True:
                    item = self._q.get_nowait()
                    if item is overlay._DONE:
                        self._closing.set()
                        return
                    if item is None:
                        hide()
                    else:
                        st["card"], st["hover"] = item, None
                        cache.clear()
                        if not st["hushed"]:
                            map_card()
            except queue.Empty:
                pass
            set_hushed(self._hushed.is_set())
            root.after(30, pump)

        pump()
        try:
            overlay._pump_until(root, self._closing)
        finally:
            import gc                       # see Splash: same Tcl teardown
            try:
                overlay._forget_window(root)
                root.destroy()
            except Exception:
                pass
            st.clear()
            cache.clear()
            paint = pump = hide = map_card = None        # noqa: F841
            canvas = root = None                         # noqa: F841
            gc.collect()


__all__ = ["ShelfCard", "away_from", "REFRESH_S", "AWAY_S", "AWAY_BUTTONS"]
