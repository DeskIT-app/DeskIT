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


class ShelfCard(overlay.HintCard):
    """The panel beside the dot. Built once at startup, shown on a key.

    `rows` is carried here rather than looked up in the config every time
    because the thing that builds the card (`main.App._shelf_card`) runs
    on a worker and this object is what both halves already share.
    """

    CORNERS = ("top-right", "top-left", "bottom-right", "bottom-left")

    def __init__(self, corner: str = "bottom-right", margin: int = 14,
                 x: int = overlay.HINT_UNSET, y: int = overlay.HINT_UNSET,
                 scale: float = 1.0, rows: int = sc.PILE_MAX,
                 on_change=None, on_press=None, on_refresh=None,
                 dot_corner: str = "bottom-right") -> None:
        # `dot_corner` is where the status dot is: the panel opens BESIDE
        # it — above a bottom-right dot, to the left of a top-right one —
        # and never over it (overlay.HintCard.origin, DOT_ROOM).
        super().__init__(after_ms=0, corner=corner, margin=margin, x=x, y=y,
                         scale=scale, on_change=on_change,
                         dot_corner=dot_corner)
        self.rows = max(sc.ROWS_MIN, min(sc.ROWS_MAX, int(rows)))
        self._on_press = on_press
        self._on_refresh = on_refresh
        self.rect = None            # the visible panel's screen rect, or None
        self._current = None        # the card dict on screen, or None
        self._state_lock = threading.Lock()
        self._refresher: threading.Thread | None = None

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
            x, y = self.origin(w, h, (root.winfo_screenwidth(),
                                      root.winfo_screenheight()),
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


__all__ = ["ShelfCard", "REFRESH_S"]
