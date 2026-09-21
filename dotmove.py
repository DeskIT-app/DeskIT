"""The move frame's thread, queue, deadline and keys — the presenter half.

`move_card.py` owns the words, the geometry and the pictures; this owns
the thread, the queue and every decision about them; `skin\\move.py`
paints the windows. With `skin\\` gone there is nothing to paint — the
loop below still runs, still keeps the deadline and still answers the
keys, so Enter and Esc end a move on every copy, light or no light.

WHAT A FRAMED MOVE IS. The shelf's Move button (shelf_card.MOVE) and the
desk's "Move the dot" both go to main.App._dot_move_begin: the shelf
closes, the dot is armed with `hold=True` (overlay.StatusDot.move — a
drop no longer ends the mode, because he may drag again), this frame is
shown, and the session ends by exactly one of four doors:

    Done (the card's button, a click)   -> pressed("done")
    Enter                                -> pressed("done")
    Esc                                  -> pressed("cancel")
    the deadline (overlay.DOT_FRAME_S)   -> pressed("expired")

What those MEAN is main.py's business — keep the drop, or put the dot
back where it was — and every one of them arrives on `on_press`
untouched. Done and expired leave the dot where it is; cancel puts it
back; all three take the frame down and un-arm the dot.

THE KEYS COME OFF THE GLOBAL HOOK, not off the windows. Nothing here
ever has the focus (a Glass is WS_EX_NOACTIVATE), so WM_KEYDOWN never
arrives; main.App._popup_key offers every key-down on the machine to
`on_key`, the way it does for the shelf. Claimed WITHOUT a pointer gate
and only while the frame is up: he asked for this mode a moment ago
and there is a light round every screen saying so, which is the shelf's
argument for its Esc and it holds for Enter here. Off, `on_key` answers
False to everything and costs one attribute read.

EVERY CALLBACK FIRES ON SOMEBODY ELSE'S THREAD — the painter's for a
click, the keyboard hook's for a key — so `on_press` may only enqueue,
flip a flag or start a thread. main.py's handler does the last.
"""
from __future__ import annotations

import logging
import queue
import threading

import overlay

try:
    import skin
except Exception:                                   # noqa: BLE001
    skin = None

_log = logging.getLogger("app")

VK_RETURN, VK_ESCAPE = 0x0D, 0x1B
# The verbs the frame reports. main.py matches on these strings.
DONE, CANCEL, EXPIRED = "done", "cancel", "expired"


class MoveFrame:
    """The light round every screen and the Done card, as a presenter.

    `on_press(verb)` is called with one of DONE, CANCEL, EXPIRED.
    `dot_hwnd` is a callable answering the dot's window handle (or None):
    the painter slips its windows under it. `scale` is the Done card's,
    the shelf's number so the two match.
    """

    def __init__(self, on_press=None, dot_hwnd=None, scale: float = 1.0) -> None:
        self._q: queue.Queue = queue.Queue()
        self._on_press = on_press
        self.dot_hwnd = dot_hwnd if callable(dot_hwnd) else (lambda: None)
        self.scale = float(scale)
        # The Done card's screen rectangle while it is up, None otherwise
        # — set by the painter, for whoever needs to keep out of it.
        self.rect = None
        self._up = threading.Event()
        self._thread: threading.Thread | None = None
        self._alive = threading.Event()
        self._closing = threading.Event()

    # -- lifecycle, like every card's --

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="move-frame")
        self._thread.start()
        self._alive.wait(2.0)

    def stop(self) -> None:
        if self._thread is None:
            return
        self._q.put(overlay._DONE)
        self._thread.join(2.0)

    # -- the doors in --

    def show(self, dot_rect, until: float) -> None:
        """Put the frame up: the light on every monitor, the Done card on
        the monitor `dot_rect` is on, and a deadline on the monotonic
        clock after which the painter reports EXPIRED. Enqueued only."""
        self._up.set()
        self._q.put((dot_rect, float(until)))

    def hide(self) -> None:
        """Down. Idempotent; enqueued only."""
        self._up.clear()
        self._q.put(None)

    def visible(self) -> bool:
        return self._up.is_set()

    # -- the doors out --

    def on_key(self, vk: int) -> bool:
        """Every key-down on the machine, while the frame is up: Enter is
        Done, Esc is cancel, both swallowed; anything else passes. Off,
        nothing is claimed."""
        if not self._up.is_set():
            return False
        if vk == VK_RETURN:
            self.pressed(DONE)
            return True
        if vk == VK_ESCAPE:
            self.pressed(CANCEL)
            return True
        return False

    def pressed(self, verb: str) -> None:
        """A door out, by name — from the painter (a click on Done), the
        hook (a key) or the painter's clock (the deadline). The frame
        takes ITSELF down first, so a second press cannot report twice,
        and hands the verb on untouched."""
        if not self._up.is_set():
            return
        self._up.clear()
        self._q.put(None)
        if self._on_press is None:
            return
        try:
            self._on_press(str(verb))
        except Exception:                            # noqa: BLE001
            _log.info("the move frame could not act on %r", verb,
                      exc_info=True)

    def expired(self) -> None:
        """The painter found the deadline. The same door, named."""
        self.pressed(EXPIRED)

    # -- the thread --

    def _run(self) -> None:
        """The skin paints when it can; without it the loop still keeps
        the deadline, because Enter and Esc must work on every copy."""
        if skin is not None:
            try:
                if skin.move_run(self):
                    return
            except Exception:                        # noqa: BLE001
                _log.info("the move frame's painter failed — no light, "
                          "the keys still work", exc_info=True)
        self._bare_loop()

    def _bare_loop(self) -> None:
        """No windows: drain the queue, watch the deadline, report it."""
        import time
        until = 0.0
        self._alive.set()
        try:
            while not self._closing.is_set():
                try:
                    while True:
                        item = self._q.get_nowait()
                        if item is overlay._DONE:
                            self._closing.set()
                            break
                        until = float(item[1]) if item else 0.0
                except queue.Empty:
                    pass
                if self._closing.is_set():
                    break
                if until and time.monotonic() >= until:
                    until = 0.0
                    self.expired()
                time.sleep(0.05)
        finally:
            self._closing.set()


__all__ = ["MoveFrame", "DONE", "CANCEL", "EXPIRED", "VK_RETURN", "VK_ESCAPE"]
